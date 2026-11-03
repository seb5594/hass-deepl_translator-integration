"""The integration inside a genuine Home Assistant core, with DeepL's API replaced by a mock.

They need Home Assistant and pytest-homeassistant-custom-component. The shared
engine installs both for every release the Compatibility workflow lists; to run them
locally: python .engine/.scripts/ha_matrix.py run 2026.9.4
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_API_KEY  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.helpers import config_entry_oauth2_flow, entity_registry as er  # noqa: E402
from homeassistant.helpers.aiohttp_client import async_get_clientsession  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.deepl_translator.api import (  # noqa: E402
    DeepLClient,
    DeepLError,
    Usage,
    split_into_batches,
)
from custom_components.deepl_translator.languages import TARGET_LANGUAGES  # noqa: E402
from custom_components.deepl_translator.mcp_client import DeepLMcpBackend  # noqa: E402
from custom_components.deepl_translator.oauth import async_create_oauth_backend  # noqa: E402
from custom_components.deepl_translator.const import (  # noqa: E402
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.deepl_translator.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)

API_KEY = "secret-test-key:fx"
BASE = "https://api-free.deepl.com"
USAGE = {"character_count": 12345, "character_limit": 500000}


LANGUAGES = [
    {"language": "DE", "name": "German", "supports_formality": True},
    {"language": "EN", "name": "English"},
    {"language": "EN-GB", "name": "English (British)", "supports_formality": False},
    {"language": "EN-US", "name": "English (American)", "supports_formality": False},
    {"language": "FR", "name": "French", "supports_formality": True},
    {"language": "PT-BR", "name": "Portuguese (Brazilian)", "supports_formality": True},
]


def mock_languages(aioclient_mock):
    aioclient_mock.get(f"{BASE}/v2/languages", json=LANGUAGES)


@pytest.fixture(autouse=True)
def languages(aioclient_mock):
    """DeepL's language list, which the services consult before every request."""
    mock_languages(aioclient_mock)


def translate_requests(aioclient_mock):
    return [call for call in aioclient_mock.mock_calls if str(call[1]).endswith("/v2/translate")]


def mock_usage(aioclient_mock, payload=USAGE, status=200):
    aioclient_mock.get(f"{BASE}/v2/usage", json=payload, status=status)


def mock_translation(aioclient_mock, *texts, language="EN"):
    aioclient_mock.post(
        f"{BASE}/v2/translate",
        json={"translations": [{"detected_source_language": language, "text": text} for text in texts]},
    )


async def setup_entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: API_KEY},
        options={CONF_DEFAULT_TARGET_LANGUAGE: "DE", **(options or {})},
        title="DeepL (Free)",
        unique_id="test-account",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def last_request_body(aioclient_mock):
    return aioclient_mock.mock_calls[-1][2]


async def call(hass, service, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


# --- config flow -----------------------------------------------------------------------------


async def start_api_key_flow(hass):
    """Open the config flow and choose to sign in with an API key."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu" and result["menu_options"] == ["api_key", "oauth"]
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "api_key"})


async def test_user_flow_preselects_the_server_language_and_creates_an_entry(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    hass.config.language = "de"
    result = await start_api_key_flow(hass)
    assert result["type"] == "form" and result["step_id"] == "api_key"
    default = next(key for key in result["data_schema"].schema if key == CONF_DEFAULT_TARGET_LANGUAGE)
    assert default.default() == "DE"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: f" {API_KEY} ", CONF_DEFAULT_TARGET_LANGUAGE: "pt_br"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "DeepL (Free)"
    assert result["data"] == {CONF_API_KEY: API_KEY}
    assert result["options"] == {CONF_DEFAULT_TARGET_LANGUAGE: "PT-BR"}
    await hass.async_block_till_done()


async def test_pro_key_uses_the_pro_host(hass, aioclient_mock):
    aioclient_mock.get("https://api.deepl.com/v2/usage", json=USAGE)
    result = await start_api_key_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "pro-key", CONF_DEFAULT_TARGET_LANGUAGE: "EN-GB"}
    )
    assert result["type"] == "create_entry" and result["title"] == "DeepL (Pro)"
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("mock", "error"),
    [
        ({"status": 403, "json": {"message": "Forbidden"}}, "invalid_auth"),
        ({"status": 500, "text": "boom"}, "cannot_connect"),
        ({"exc": aiohttp.ClientError}, "cannot_connect"),
    ],
)
async def test_user_flow_reports_a_rejected_or_unreachable_service(hass, aioclient_mock, mock, error):
    aioclient_mock.get(f"{BASE}/v2/usage", **mock)
    result = await start_api_key_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_DEFAULT_TARGET_LANGUAGE: "DE"}
    )
    assert result["type"] == "form" and result["errors"] == {"base": error}


async def test_the_same_account_cannot_be_added_twice(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    for expected in ("create_entry", "abort"):
        result = await start_api_key_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY, CONF_DEFAULT_TARGET_LANGUAGE: "DE"}
        )
        assert result["type"] == expected
        await hass.async_block_till_done()
    assert result["reason"] == "already_configured"


async def test_rejected_key_starts_reauth_and_a_new_key_recovers(hass, aioclient_mock):
    mock_usage(aioclient_mock, {"message": "Forbidden"}, status=403)
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]

    aioclient_mock.clear_requests()
    mock_usage(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_API_KEY: "new-key:fx"}
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key:fx"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_change_reloads_the_account(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    entry = await setup_entry(hass)
    assert hass.data[DOMAIN][entry.entry_id].cache.enabled

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form" and result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_DEFAULT_TARGET_LANGUAGE: "fr", CONF_UPDATE_INTERVAL: 10, CONF_CACHE_SIZE: 0},
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options == {
        CONF_DEFAULT_TARGET_LANGUAGE: "FR",
        CONF_UPDATE_INTERVAL: 10,
        CONF_CACHE_SIZE: 0,
    }
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime.default_target_language == "FR" and not runtime.cache.enabled


# --- setup and sensors -----------------------------------------------------------------------


async def test_entry_loads_and_unloads(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "translate_text")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_unreachable_service_retries_the_setup(hass, aioclient_mock):
    aioclient_mock.get(f"{BASE}/v2/usage", exc=aiohttp.ClientError)
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY


def sensor_state(hass, entry, key):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def test_sensors_show_the_quota(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    entry = await setup_entry(hass)
    assert sensor_state(hass, entry, "characters_used").state == "12345"
    assert sensor_state(hass, entry, "characters_limit").state == "500000"
    assert sensor_state(hass, entry, "characters_remaining").state == "487655"
    assert float(sensor_state(hass, entry, "usage_percent").state) == 2.5


async def test_accounts_without_a_limit_have_no_remaining_figures(hass, aioclient_mock):
    mock_usage(aioclient_mock, {"character_count": 10, "character_limit": 1000000000000})
    entry = await setup_entry(hass)
    assert sensor_state(hass, entry, "characters_used").state == "10"
    for key in ("characters_limit", "characters_remaining", "usage_percent"):
        assert sensor_state(hass, entry, key).state == "unknown"


def test_usage_arithmetic():
    usage = Usage(character_count=250, character_limit=1000)
    assert (usage.characters_remaining, usage.usage_percent, usage.is_unlimited) == (750, 25.0, False)
    assert Usage(1200, 1000).characters_remaining == 0
    assert Usage(5, 0).is_unlimited


async def test_diagnostics_hide_the_api_key(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    entry = await setup_entry(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert API_KEY not in str(diagnostics)
    assert diagnostics["sign_in"] == "api_key"
    assert diagnostics["usage"]["character_count"] == 12345


# --- translate_text --------------------------------------------------------------------------


async def test_translate_text_uses_the_default_language_and_returns_the_result(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Guten Morgen!")
    response = await call(hass, "translate_text", text="Good morning!")
    assert response == {
        "text": "Guten Morgen!",
        "translations": [{"text": "Guten Morgen!", "detected_source_language": "EN"}],
        "target_language": "DE",
    }
    assert last_request_body(aioclient_mock) == {"text": ["Good morning!"], "target_lang": "DE"}


async def test_translate_text_passes_the_options_and_normalizes_languages(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Hello")
    await call(
        hass,
        "translate_text",
        text="Hallo",
        target_language="en",
        source_language="de-DE",
        formality="prefer_more",
        context="greeting",
        glossary_id="g-1",
        tag_handling="html",
    )
    assert last_request_body(aioclient_mock) == {
        "text": ["Hallo"],
        "target_lang": "EN-US",
        "source_lang": "DE",
        "formality": "prefer_more",
        "context": "greeting",
        "glossary_id": "g-1",
        "tag_handling": "html",
    }


async def test_translate_text_cache_spares_the_quota(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Eins", "Zwei")
    first = await call(hass, "translate_text", text=["One", "", "Two", "One"])
    assert [item["text"] for item in first["translations"]] == ["Eins", "", "Zwei", "Eins"]
    assert last_request_body(aioclient_mock)["text"] == ["One", "Two"]

    requests = aioclient_mock.call_count
    second = await call(hass, "translate_text", text="Two")
    assert second["text"] == "Zwei"
    assert aioclient_mock.call_count == requests  # answered from the cache

    aioclient_mock.clear_requests()
    mock_languages(aioclient_mock)
    mock_translation(aioclient_mock, "Deux")
    french = await call(hass, "translate_text", text="Two", target_language="FR")
    assert french["text"] == "Deux"  # another language is another translation
    assert len(translate_requests(aioclient_mock)) == 1


async def test_translate_text_without_cache_asks_every_time(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass, {CONF_CACHE_SIZE: 0})
    mock_translation(aioclient_mock, "Eins")
    await call(hass, "translate_text", text="One")
    requests = aioclient_mock.call_count
    await call(hass, "translate_text", text="One")
    assert aioclient_mock.call_count == requests + 1


async def test_glossary_needs_a_source_language(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="source_language"):
        await call(hass, "translate_text", text="Hi", glossary_id="g-1")


@pytest.mark.parametrize(
    ("status", "message"),
    [(456, "quota"), (400, "Value for 'target_lang' not supported."), (403, "Forbidden")],
)
async def test_translate_text_reports_what_deepl_says(hass, aioclient_mock, status, message):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    aioclient_mock.post(f"{BASE}/v2/translate", status=status, json={"message": message})
    with pytest.raises(HomeAssistantError, match=message):
        await call(hass, "translate_text", text="Hi", target_language="FR")


async def test_several_accounts_need_an_explicit_choice(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    first = await setup_entry(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "other:fx"},
        options={CONF_DEFAULT_TARGET_LANGUAGE: "FR"},
        unique_id="other-account",
    )
    second.add_to_hass(hass)
    await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    mock_translation(aioclient_mock, "Bonjour")
    with pytest.raises(HomeAssistantError, match="config_entry_id"):
        await call(hass, "translate_text", text="Hello")
    response = await call(hass, "translate_text", text="Hello", config_entry_id=second.entry_id)
    assert response["target_language"] == "FR"
    assert first.entry_id != second.entry_id


async def test_services_without_an_account_explain_themselves(hass):
    from custom_components.deepl_translator import async_setup

    await async_setup(hass, {})
    with pytest.raises(HomeAssistantError, match="No DeepL account"):
        await call(hass, "translate_text", text="Hello")


# --- get_languages ---------------------------------------------------------------------------


async def test_get_languages_is_cached(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    response = await call(hass, "get_languages")
    assert response["languages"][0] == {"code": "DE", "name": "German", "supports_formality": True}
    assert len(response["languages"]) == len(LANGUAGES)
    requests = aioclient_mock.call_count
    await call(hass, "get_languages")
    assert aioclient_mock.call_count == requests


# --- translate_document ----------------------------------------------------------------------


def mock_document(aioclient_mock, state="done"):
    aioclient_mock.post(f"{BASE}/v2/document", json={"document_id": "D1", "document_key": "K1"})
    aioclient_mock.post(
        f"{BASE}/v2/document/D1",
        json={"status": state, "seconds_remaining": 3, "billed_characters": 42, "error_message": "bad file"},
    )
    aioclient_mock.post(f"{BASE}/v2/document/D1/result", content=b"translated bytes")


@pytest.fixture
def documents(hass, tmp_path):
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    source = tmp_path / "manual.txt"
    source.write_text("Hello")
    return tmp_path, source


async def test_translate_document_writes_next_to_the_original_by_default(hass, aioclient_mock, documents):
    folder, source = documents
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_document(aioclient_mock)
    response = await call(hass, "translate_document", input_file=str(source))
    target = folder / "manual.de.txt"
    assert target.read_bytes() == b"translated bytes"
    assert response == {
        "output_file": str(target),
        "target_language": "DE",
        "document_id": "D1",
        "billed_characters": 42,
    }
    assert not list(folder.glob("*.part"))


async def test_translate_document_honours_output_path_and_never_overwrites_silently(
    hass, aioclient_mock, documents
):
    folder, source = documents
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_document(aioclient_mock)
    output = folder / "nested" / "result.txt"
    await call(hass, "translate_document", input_file=str(source), output_file=str(output))
    assert output.read_bytes() == b"translated bytes"

    uploads = aioclient_mock.call_count
    with pytest.raises(HomeAssistantError, match="overwrite"):
        await call(hass, "translate_document", input_file=str(source), output_file=str(output))
    assert aioclient_mock.call_count == uploads  # refused before anything was billed

    output.write_text("old")
    await call(
        hass, "translate_document", input_file=str(source), output_file=str(output), overwrite=True
    )
    assert output.read_bytes() == b"translated bytes"


async def test_translate_document_refuses_paths_outside_the_allowed_folders(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="allowlist_external_dirs"):
        await call(hass, "translate_document", input_file="/etc/shadow.txt")


async def test_translate_document_waits_for_a_slow_translation(hass, documents):
    folder, source = documents
    statuses = iter(
        [
            {"status": "queued"},
            {"status": "translating", "seconds_remaining": 3},
            {"status": "done", "billed_characters": 7},
        ]
    )

    async def fake_request(self, method, path, **kwargs):
        if path == "/v2/usage":
            return USAGE
        if path == "/v2/languages":
            return LANGUAGES
        if path == "/v2/document":
            return {"document_id": "D1", "document_key": "K1"}
        if path == "/v2/document/D1":
            return next(statuses)
        return b"translated bytes"  # the result download

    with patch.object(DeepLClient, "_request", fake_request):
        await setup_entry(hass)
        with patch("custom_components.deepl_translator.api.asyncio.sleep", new=AsyncMock()) as sleep:
            response = await call(hass, "translate_document", input_file=str(source))
    assert [item.args[0] for item in sleep.await_args_list] == [2, 3]
    assert response["billed_characters"] == 7
    assert (folder / "manual.de.txt").exists()


async def test_translate_document_reports_a_failed_translation(hass, aioclient_mock, documents):
    folder, source = documents
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_document(aioclient_mock, state="error")
    with pytest.raises(HomeAssistantError, match="bad file"):
        await call(hass, "translate_document", input_file=str(source))
    assert not (folder / "manual.de.txt").exists()


# --- client details --------------------------------------------------------------------------


class ScriptedSession:
    """Answers one prepared (status, headers, payload) per request, in order."""

    def __init__(self, *answers):
        self._answers = iter(answers)
        self.requests = 0

    def request(self, *args, **kwargs):
        self.requests += 1
        status, headers, payload = next(self._answers)
        return ScriptedResponse(status, headers, payload)


class ScriptedResponse:
    def __init__(self, status, headers, payload):
        self.status, self.headers, self._payload = status, headers, payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def json(self, **kwargs):
        return self._payload

    async def read(self):
        return b""


async def test_client_backs_off_when_deepl_is_busy():
    session = ScriptedSession((429, {"Retry-After": "7"}, {}), (200, {}, USAGE))
    client = DeepLClient(session, API_KEY, "test")
    with patch("custom_components.deepl_translator.api.asyncio.sleep", new=AsyncMock()) as sleep:
        usage = await client.async_get_usage()
    assert usage.character_count == 12345
    sleep.assert_awaited_once_with(7.0)


async def test_client_gives_up_after_repeated_overload():
    session = ScriptedSession(*[(529, {}, {})] * 3)
    client = DeepLClient(session, API_KEY, "test")
    with patch("custom_components.deepl_translator.api.asyncio.sleep", new=AsyncMock()) as sleep:
        with pytest.raises(DeepLError, match="overloaded"):
            await client.async_get_usage()
    assert session.requests == 3
    assert [item.args[0] for item in sleep.await_args_list] == [1, 2]  # 1 s, then 2 s


async def test_client_turns_timeouts_into_connection_errors(hass, aioclient_mock):
    client = DeepLClient(async_get_clientsession(hass), API_KEY, "test")
    aioclient_mock.get(f"{BASE}/v2/usage", exc=asyncio.TimeoutError)
    with pytest.raises(DeepLError, match="Timed out"):
        await client.async_get_usage()


async def test_client_sends_the_key_and_identifies_itself(hass, aioclient_mock):
    client = DeepLClient(async_get_clientsession(hass), API_KEY, "agent/1.0")
    aioclient_mock.get(f"{BASE}/v2/usage", json=USAGE)
    await client.async_get_usage()
    headers = aioclient_mock.mock_calls[-1][3]
    assert headers["Authorization"] == f"DeepL-Auth-Key {API_KEY}"
    assert headers["User-Agent"] == "agent/1.0"


def test_batches_respect_the_request_limits():
    assert [len(batch) for batch in split_into_batches(["x"] * 120)] == [50, 50, 20]
    big = "ä" * 40_000  # 80 kB in UTF-8
    assert [len(batch) for batch in split_into_batches([big, big, "x"])] == [1, 2]
    assert list(split_into_batches([])) == []


# --- translate_structure ---------------------------------------------------------------------


async def test_translate_structure_translates_inline_data_and_keeps_its_shape(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Willkommen", "Öffnen", "Schließen")
    response = await call(
        hass,
        "translate_structure",
        data={
            "title": "Welcome",
            "icon": "mdi:door",
            "count": 3,
            "items": ["Open", {"label": "Close"}],
        },
    )
    assert last_request_body(aioclient_mock) == {"text": ["Welcome", "Open", "Close"], "target_lang": "DE"}
    assert response == {
        "target_language": "DE",
        "translated_strings": 3,
        "skipped_strings": 1,
        "data": {"title": "Willkommen", "icon": "mdi:door", "count": 3, "items": ["Öffnen", {"label": "Schließen"}]},
    }


async def test_translate_structure_keeps_the_layout_of_a_json_file(hass, aioclient_mock, documents):
    folder, _ = documents
    source = folder / "en.json"
    source.write_text('{\n    "title": "Welcome",\n    "id": "door_1",\n    "buttons": ["Open", "Close"]\n}\n')
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Willkommen", "Öffnen", "Schließen")
    response = await call(hass, "translate_structure", input_file=str(source))
    target = folder / "en.de.json"
    assert target.read_text() == (
        '{\n    "title": "Willkommen",\n    "id": "door_1",\n    "buttons": ["Öffnen", "Schließen"]\n}\n'
    )
    assert response["output_file"] == str(target)
    assert response["translated_strings"] == 3


async def test_translate_structure_keeps_comments_of_a_yaml_file(hass, aioclient_mock, documents):
    folder, _ = documents
    source = folder / "card.yaml"
    source.write_text(
        "# Door card\ntype: markdown   # keep\ntitle: Front door\ncontent: |\n  Closed since morning\n"
    )
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Haustür", "Seit heute früh geschlossen")
    output = folder / "card.de.yaml"
    await call(
        hass,
        "translate_structure",
        input_file=str(source),
        output_file=str(output),
        only_keys=["title", "content"],
    )
    assert last_request_body(aioclient_mock)["text"] == ["Front door", "Closed since morning"]
    assert output.read_text() == (
        "# Door card\ntype: markdown   # keep\ntitle: Haustür\ncontent: |\n  Seit heute früh geschlossen\n"
    )


async def test_translate_structure_shields_placeholders(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Hallo <x>{name}</x>, du hast <x>{{ count }}</x> &amp; mehr")
    response = await call(
        hass, "translate_structure", data={"greeting": "Hello {name}, you have {{ count }} & more"}
    )
    assert last_request_body(aioclient_mock) == {
        "text": ["Hello <x>{name}</x>, you have <x>{{ count }}</x> &amp; more"],
        "target_lang": "DE",
        "tag_handling": "xml",
        "ignore_tags": ["x"],
    }
    assert response["data"] == {"greeting": "Hallo {name}, du hast {{ count }} & mehr"}


async def test_translate_structure_dry_run_costs_nothing(hass, aioclient_mock, documents):
    folder, _ = documents
    source = folder / "en.json"
    source.write_text('{"title": "Welcome", "nested": {"text": "Hello there"}}')
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    requests = aioclient_mock.call_count
    response = await call(hass, "translate_structure", input_file=str(source), dry_run=True)
    assert response == {
        "dry_run": True,
        "strings": [{"path": "title", "text": "Welcome"}, {"path": "nested.text", "text": "Hello there"}],
        "characters": 18,
        "skipped_strings": 0,
        "characters_remaining": 487655,
    }
    assert aioclient_mock.call_count == requests
    assert not (folder / "en.de.json").exists()


async def test_translate_structure_explains_bad_input(hass, aioclient_mock, documents):
    folder, _ = documents
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="either"):
        await call(hass, "translate_structure")
    with pytest.raises(HomeAssistantError, match="either"):
        await call(hass, "translate_structure", data={"a": "b"}, input_file="x.json")

    broken = folder / "broken.json"
    broken.write_text('{"a": }')
    with pytest.raises(HomeAssistantError, match="not valid JSON"):
        await call(hass, "translate_structure", input_file=str(broken))

    unknown = folder / "notes.txt"
    unknown.write_text("hello")
    with pytest.raises(HomeAssistantError, match="format"):
        await call(hass, "translate_structure", input_file=str(unknown))


# --- nothing is sent when the whole request cannot be translated ----------------------------------


async def test_unknown_target_language_is_refused_before_anything_is_sent(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="cannot translate into 'XX'.*Nothing was sent"):
        await call(hass, "translate_text", text="Hello", target_language="xx")
    with pytest.raises(HomeAssistantError, match="Did you mean DE"):
        await call(hass, "translate_text", text="Hello", target_language="DEU")
    with pytest.raises(HomeAssistantError, match="cannot translate from 'KLINGON'"):
        await call(hass, "translate_text", text="Hello", source_language="klingon")
    assert translate_requests(aioclient_mock) == []


async def test_strict_formality_is_refused_for_languages_without_it(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="formal or informal.*Nothing was sent"):
        await call(hass, "translate_text", text="Hello", target_language="EN-GB", formality="more")
    assert translate_requests(aioclient_mock) == []
    mock_translation(aioclient_mock, "Hello")
    await call(hass, "translate_text", text="Hello", target_language="EN-GB", formality="prefer_more")
    assert len(translate_requests(aioclient_mock)) == 1


async def test_a_request_the_quota_cannot_cover_is_refused_completely(hass, aioclient_mock):
    mock_usage(aioclient_mock, {"character_count": 499900, "character_limit": 500000, "end_time": "2026-12-01T00:00:00Z"})
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match=r"needs about 500 characters but only 100 are left.*2026-12-01.*Nothing was sent"):
        await call(hass, "translate_text", text=["x" * 250, "y" * 250])
    assert translate_requests(aioclient_mock) == []

    mock_translation(aioclient_mock, "ok")
    await call(hass, "translate_text", text="x" * 100)  # exactly what is left
    assert len(translate_requests(aioclient_mock)) == 1


async def test_a_stale_usage_figure_is_refreshed_before_refusing(hass, aioclient_mock):
    mock_usage(aioclient_mock, {"character_count": 499900, "character_limit": 500000})
    await setup_entry(hass)
    aioclient_mock.clear_requests()  # the quota was raised in the meantime
    mock_languages(aioclient_mock)
    mock_usage(aioclient_mock, {"character_count": 10, "character_limit": 1000000})
    mock_translation(aioclient_mock, "ok")
    response = await call(hass, "translate_text", text="x" * 500)
    assert response["text"] == "ok"


async def test_cached_texts_need_no_quota(hass, aioclient_mock):
    mock_usage(aioclient_mock, {"character_count": 0, "character_limit": 500000})
    await setup_entry(hass)
    mock_translation(aioclient_mock, "Hallo")
    await call(hass, "translate_text", text="Hello")
    aioclient_mock.clear_requests()
    mock_usage(aioclient_mock, {"character_count": 500000, "character_limit": 500000})
    assert (await call(hass, "translate_text", text="Hello"))["text"] == "Hallo"
    assert aioclient_mock.call_count == 0


async def test_a_single_text_that_cannot_fit_a_request_is_refused(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="too long for one DeepL request.*Nothing was sent"):
        await call(hass, "translate_text", text=["short", "ä" * 70_000])
    assert translate_requests(aioclient_mock) == []


async def test_structure_that_does_not_fit_the_quota_writes_and_sends_nothing(hass, aioclient_mock, documents):
    folder, _ = documents
    source = folder / "en.json"
    source.write_text('{"a": "' + "x" * 300 + '", "b": "' + "y" * 300 + '"}')
    mock_usage(aioclient_mock, {"character_count": 499500, "character_limit": 500000})
    await setup_entry(hass)
    with pytest.raises(HomeAssistantError, match="Not enough DeepL quota"):
        await call(hass, "translate_structure", input_file=str(source))
    assert translate_requests(aioclient_mock) == []
    assert not (folder / "en.de.json").exists()
    dry = await call(hass, "translate_structure", input_file=str(source), dry_run=True)
    assert dry["characters"] == 600 and dry["characters_remaining"] == 500


async def test_documents_are_checked_before_they_are_read_or_uploaded(hass, aioclient_mock, documents):
    folder, source = documents
    mock_usage(aioclient_mock, {"character_count": 500000, "character_limit": 500000})
    await setup_entry(hass)
    program = folder / "tool.exe"
    program.write_bytes(b"MZ")
    with pytest.raises(HomeAssistantError, match=r"cannot translate \.exe files.*Nothing was sent"):
        await call(hass, "translate_document", input_file=str(program))
    with pytest.raises(HomeAssistantError, match="Not enough DeepL quota"):
        await call(hass, "translate_document", input_file=str(source))
    assert not [call_ for call_ in aioclient_mock.mock_calls if "/v2/document" in str(call_[1])]


# --- sign in with OAuth (DeepL's hosted MCP server) -----------------------------------------------

MCP_URL = "https://mcp.deepl.com/v1/mcp"
AUTH_URL = "https://mcp.deepl.com/.idp/auth"
TOKEN_URL = "https://mcp.deepl.com/.idp/token"
REGISTER_URL = "https://mcp.deepl.com/.idp/register"
METADATA_URL = "https://mcp.deepl.com/.well-known/oauth-protected-resource"
MY_REDIRECT = "https://my.home-assistant.io/redirect/oauth"

TRANSLATE_TOOL = {
    "name": "translate-text",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "array", "items": {"type": "string"}},
            "targetLangCode": {"type": "string"},
            "formality": {"type": "string"},
        },
    },
}
FREE_TOOLS = [TRANSLATE_TOOL, {"name": "rephrase-text"}]
SEAT_TOOLS = [*FREE_TOOLS, {"name": "list-glossaries"}]


def upper_case_translation(arguments):
    texts = arguments["text"]
    return {"structuredContent": {"translations": [{"text": text.upper()} for text in texts]}}


class McpServer:
    """Stands in for the transport of the MCP backend and records the tool calls."""

    def __init__(self, tools=FREE_TOOLS, translate=upper_case_translation):
        self.tools, self.translate, self.tool_calls = tools, translate, []

    async def post(self, backend, message, expect_answer):
        if not expect_answer:
            return {}
        method = message["method"]
        if method == "tools/list":
            return {"result": {"tools": self.tools}}
        if method == "tools/call":
            self.tool_calls.append(message["params"])
            return {"result": self.translate(message["params"]["arguments"])}
        return {"result": {}}

    def patch(self):
        server = self

        async def fake_post(backend, message, expect_answer):
            return await server.post(backend, message, expect_answer)

        return patch.object(DeepLMcpBackend, "_post", fake_post)


def token_data(expires_in=3600):
    return {
        "access_token": "access",
        "refresh_token": "refresh",
        "token_type": "Bearer",
        "expires_in": expires_in,
        "expires_at": time.time() + expires_in,
    }


def oauth_entry(expires_in=3600):
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "auth_implementation": "deepl_translator_abc",
            "client_id": "client-1",
            "client_secret": None,
            "authorize_url": AUTH_URL,
            "token_url": TOKEN_URL,
            "token": token_data(expires_in),
        },
        options={CONF_DEFAULT_TARGET_LANGUAGE: "DE"},
        title="DeepL (OAuth)",
        unique_id="client-1",
    )


async def setup_oauth_entry(hass, server=None):
    server = server or McpServer()
    entry = oauth_entry()
    entry.add_to_hass(hass)
    with server.patch():
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, server


async def test_oauth_account_translates_text_without_usage_sensors(hass):
    entry, server = await setup_oauth_entry(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.async_entity_ids("sensor") == []
    with server.patch():
        response = await call(hass, "translate_text", text=["Hello", "Bye"], formality="prefer_more")
    assert response["translations"] == [{"text": "HELLO", "detected_source_language": None}, {"text": "BYE", "detected_source_language": None}]
    assert server.tool_calls == [
        {"name": "translate-text", "arguments": {"text": ["Hello", "Bye"], "targetLangCode": "DE", "formality": "prefer_more"}}
    ]


async def test_oauth_account_splits_work_by_the_limit_of_its_plan(hass):
    _, server = await setup_oauth_entry(hass)
    texts = ["a" * 3000, "b" * 3000, "c" * 100]
    with server.patch():
        response = await call(hass, "translate_text", text=texts)
    assert [item["text"] for item in response["translations"]] == [text.upper() for text in texts]
    assert [len(item["arguments"]["text"]) for item in server.tool_calls] == [1, 2]  # 5,000 per call on free

    _, seat_server = await setup_oauth_entry(hass, McpServer(tools=SEAT_TOOLS))
    assert seat_server.tools == SEAT_TOOLS  # seat plans see the glossary tools and may send 128,000 at once


async def test_oauth_account_refuses_an_oversized_text_before_sending(hass):
    _, server = await setup_oauth_entry(hass)
    with server.patch(), pytest.raises(HomeAssistantError, match=r"longer than the 5,000 characters.*Nothing was sent"):
        await call(hass, "translate_text", text="x" * 5001)
    assert server.tool_calls == []


async def test_oauth_account_refuses_what_only_api_key_accounts_can_do(hass, documents):
    folder, source = documents
    _, server = await setup_oauth_entry(hass)
    with server.patch():
        with pytest.raises(HomeAssistantError, match=r"Document translation needs an account that signed in with an API key"):
            await call(hass, "translate_document", input_file=str(source))
        with pytest.raises(HomeAssistantError, match="Markup handling needs an account"):
            await call(hass, "translate_text", text="<b>Hi</b>", tag_handling="html")
        with pytest.raises(HomeAssistantError, match=r"placeholders.*protect_placeholders.*Nothing was sent"):
            await call(hass, "translate_structure", data={"greeting": "Hello {name}"})
        translated = await call(hass, "translate_structure", data={"greeting": "Hello {name}"}, protect_placeholders=False)
        languages = await call(hass, "get_languages")
    assert translated["data"] == {"greeting": "HELLO {NAME}"}
    assert [item["code"] for item in languages["languages"]] == list(TARGET_LANGUAGES)
    assert len(server.tool_calls) == 1


async def test_oauth_tool_errors_are_reported(hass):
    quota = {"isError": True, "content": [{"type": "text", "text": "Quota exceeded"}]}
    _, server = await setup_oauth_entry(hass, McpServer(translate=lambda arguments: quota))
    with server.patch(), pytest.raises(HomeAssistantError, match="Quota exceeded"):
        await call(hass, "translate_text", text="Hello")


async def test_oauth_token_is_refreshed_when_it_expires(hass, aioclient_mock):
    entry = oauth_entry(expires_in=-60)
    entry.add_to_hass(hass)
    aioclient_mock.post(
        TOKEN_URL, json={"access_token": "fresh", "expires_in": 3600, "token_type": "Bearer"}
    )
    backend = await async_create_oauth_backend(hass, entry)
    assert await backend._get_token() == "fresh"
    request = aioclient_mock.mock_calls[-1][2]
    assert request["grant_type"] == "refresh_token" and request["refresh_token"] == "refresh"
    assert request["client_id"] == "client-1" and "client_secret" not in request
    assert entry.data["token"]["access_token"] == "fresh"
    assert entry.data["token"]["refresh_token"] == "refresh"  # kept when DeepL sends no new one


async def test_oauth_rejected_refresh_starts_reauth(hass, aioclient_mock):
    entry = oauth_entry(expires_in=-60)
    entry.add_to_hass(hass)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [(flow["context"]["source"], flow["step_id"]) for flow in flows] == [("reauth", "reauth_oauth")]


async def test_oauth_without_translation_tool_is_not_ready(hass):
    entry = oauth_entry()
    entry.add_to_hass(hass)
    with McpServer(tools=[{"name": "rephrase-text"}]).patch():
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


def mock_oauth_server(aioclient_mock, registration=None):
    aioclient_mock.post(
        MCP_URL, status=401, headers={"WWW-Authenticate": f'Bearer resource_metadata="{METADATA_URL}"'}
    )
    aioclient_mock.get(
        METADATA_URL,
        json={"resource": MCP_URL, "authorization_servers": ["https://mcp.deepl.com/"]},
    )
    aioclient_mock.get(
        "https://mcp.deepl.com/.well-known/oauth-authorization-server",
        json={
            "issuer": "https://mcp.deepl.com/",
            "authorization_endpoint": AUTH_URL,
            "token_endpoint": TOKEN_URL,
            "registration_endpoint": REGISTER_URL,
            "code_challenge_methods_supported": ["S256"],
        },
    )
    aioclient_mock.post(REGISTER_URL, **(registration or {"json": {"client_id": "client-123"}, "status": 201}))
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "token_type": "Bearer"})


async def walk_to_the_login_page(hass, aioclient_mock):
    hass.config.components.add("my")
    mock_oauth_server(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "oauth"})
    assert result["type"] == "external", result
    return result


async def finish_the_login(hass, result):
    query = parse_qs(urlparse(result["url"]).query)
    state = config_entry_oauth2_flow._decode_jwt(hass, query["state"][0])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "the-code", "state": state})
    assert result["type"] == "external_done"
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def test_oauth_flow_registers_a_client_sends_the_user_to_deepl_and_creates_the_entry(hass, aioclient_mock):
    result = await walk_to_the_login_page(hass, aioclient_mock)
    query = {key: values[0] for key, values in parse_qs(urlparse(result["url"]).query).items()}
    assert result["url"].startswith(AUTH_URL)
    assert query["client_id"] == "client-123" and query["response_type"] == "code"
    assert query["redirect_uri"] == MY_REDIRECT
    assert query["scope"] == "offline_access" and query["resource"] == MCP_URL
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    registration = next(call_[2] for call_ in aioclient_mock.mock_calls if str(call_[1]) == REGISTER_URL)
    assert registration["redirect_uris"] == [MY_REDIRECT]
    assert registration["token_endpoint_auth_method"] == "none"

    with McpServer().patch():
        result = await finish_the_login(hass, result)
        await hass.async_block_till_done()
    assert result["type"] == "create_entry" and result["title"] == "DeepL (OAuth)"
    exchange = next(call_[2] for call_ in aioclient_mock.mock_calls if str(call_[1]) == TOKEN_URL)
    assert exchange["grant_type"] == "authorization_code" and exchange["code"] == "the-code"
    assert exchange["client_id"] == "client-123" and exchange["redirect_uri"] == MY_REDIRECT
    from custom_components.deepl_translator import protocol

    assert protocol.compute_code_challenge(exchange["code_verifier"]) == query["code_challenge"]
    data = result["data"]
    assert data["token"]["access_token"] == "at" and data["client_id"] == "client-123"
    assert data["authorize_url"] == AUTH_URL and data["token_url"] == TOKEN_URL
    assert result["options"] == {CONF_DEFAULT_TARGET_LANGUAGE: "EN-US"}
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED


async def test_oauth_flow_does_not_add_an_account_whose_test_translation_fails(hass, aioclient_mock):
    result = await walk_to_the_login_page(hass, aioclient_mock)
    broken = {"isError": True, "content": [{"type": "text", "text": "boom"}]}
    with McpServer(translate=lambda arguments: broken).patch():
        result = await finish_the_login(hass, result)
    assert result["type"] == "abort" and result["reason"] == "translation_failed"
    assert result["description_placeholders"]["error"] == "boom"
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_oauth_flow_explains_a_refused_registration(hass, aioclient_mock):
    hass.config.components.add("my")
    mock_oauth_server(aioclient_mock, {"status": 400, "json": {"error": "invalid_redirect_uri"}})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "oauth"})
    assert result["type"] == "abort" and result["reason"] == "oauth_unsupported"
    assert "invalid_redirect_uri" in result["description_placeholders"]["error"]


async def test_oauth_flow_reports_an_unreachable_server(hass, aioclient_mock):
    aioclient_mock.post(MCP_URL, exc=aiohttp.ClientError)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "oauth"})
    assert result["type"] == "abort" and result["reason"] == "cannot_connect"


async def test_oauth_reauth_replaces_the_token_and_reloads(hass, aioclient_mock):
    entry = oauth_entry(expires_in=-60)
    entry.add_to_hass(hass)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]

    aioclient_mock.clear_requests()
    hass.config.components.add("my")
    mock_oauth_server(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] == "external"
    with McpServer().patch():
        result = await finish_the_login(hass, result)
        await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "reauth_successful"
    assert entry.data["token"]["access_token"] == "at" and entry.data["client_id"] == "client-123"
    assert entry.state is ConfigEntryState.LOADED


# --- the MCP transport ----------------------------------------------------------------------------


class StubResponse:
    def __init__(self, status=200, headers=None, body="", content_type="application/json"):
        self.status, self._body = status, body
        self.headers = {"Content-Type": content_type, **(headers or {})}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def text(self):
        return self._body


class StubSession:
    """Answers the n-th POST with the n-th prepared response and keeps what was sent."""

    def __init__(self, *responses):
        self._responses, self.sent = iter(responses), []

    def post(self, url, json, headers, timeout):
        self.sent.append((json, headers))
        return next(self._responses)


def rpc_answer(result, request_id):
    import json

    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


async def static_token():
    return "token-1"


async def test_mcp_backend_speaks_streamable_http_with_a_session():
    schema = TRANSLATE_TOOL
    session = StubSession(
        StubResponse(headers={"Mcp-Session-Id": "s-1"}, body=rpc_answer({}, 1)),
        StubResponse(status=202),
        StubResponse(body=rpc_answer({"tools": [schema]}, 2)),
        StubResponse(  # answered as an event stream
            content_type="text/event-stream",
            body='event: message\ndata: ' + rpc_answer({"structuredContent": {"translations": [{"text": "Hallo"}]}}, 3) + "\n\n",
        ),
    )
    backend = DeepLMcpBackend(session, static_token, "agent/1")
    await backend.async_connect()
    from custom_components.deepl_translator.api import TranslateOptions

    result = await backend.async_translate(["Hello"], TranslateOptions(target_lang="DE"))
    assert [item.text for item in result] == ["Hallo"]
    first, second, third, fourth = (headers for _, headers in session.sent)
    assert first["Authorization"] == "Bearer token-1" and first["User-Agent"] == "agent/1"
    assert "application/json" in first["Accept"] and "text/event-stream" in first["Accept"]
    assert "Mcp-Session-Id" not in first and "MCP-Protocol-Version" not in first
    assert second["Mcp-Session-Id"] == "s-1" and fourth["MCP-Protocol-Version"] == "2025-06-18"
    assert session.sent[1][0] == {"jsonrpc": "2.0", "method": "notifications/initialized"}


async def test_mcp_backend_starts_a_new_session_when_the_server_forgot_it():
    session = StubSession(
        StubResponse(headers={"Mcp-Session-Id": "old"}, body=rpc_answer({}, 1)),
        StubResponse(status=202),
        StubResponse(body=rpc_answer({"tools": [TRANSLATE_TOOL]}, 2)),
        StubResponse(status=404),  # the session is gone
        StubResponse(headers={"Mcp-Session-Id": "new"}, body=rpc_answer({}, 4)),
        StubResponse(status=202),
        StubResponse(body=rpc_answer({"structuredContent": {"translations": [{"text": "Hallo"}]}}, 5)),
    )
    backend = DeepLMcpBackend(session, static_token, "agent/1")
    await backend.async_connect()
    from custom_components.deepl_translator.api import TranslateOptions

    result = await backend.async_translate(["Hello"], TranslateOptions(target_lang="DE"))
    assert result[0].text == "Hallo"
    assert session.sent[-1][1]["Mcp-Session-Id"] == "new"


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, "rejected the sign-in"), (403, "rejected the sign-in")],
)
async def test_mcp_backend_reports_a_rejected_sign_in(status, error):
    backend = DeepLMcpBackend(StubSession(StubResponse(status=status)), static_token, "agent/1")
    with pytest.raises(DeepLError, match=error):
        await backend.async_connect()


async def test_mcp_backend_rejects_servers_it_cannot_use():
    for tools, message in (
        ([{"name": "rephrase-text"}], "no text translation"),
        ([{"name": "translate-text", "inputSchema": {"properties": {"sentence": {"type": "string"}}}}], "arguments this integration does not know"),
    ):
        session = StubSession(
            StubResponse(body=rpc_answer({}, 1)), StubResponse(status=202), StubResponse(body=rpc_answer({"tools": tools}, 2))
        )
        with pytest.raises(DeepLError, match=message):
            await DeepLMcpBackend(session, static_token, "agent/1").async_connect()
