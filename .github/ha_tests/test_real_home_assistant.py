"""The integration inside a genuine Home Assistant core, with DeepL's API replaced by a mock.

They need Home Assistant and pytest-homeassistant-custom-component. The shared
engine installs both for every release the Compatibility workflow lists; to run them
locally: python .engine/.scripts/ha_matrix.py run 2026.9.4
"""

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_API_KEY  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.helpers.aiohttp_client import async_get_clientsession  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.deepl_translate.api import (  # noqa: E402
    DeepLClient,
    DeepLError,
    Usage,
    split_into_batches,
)
from custom_components.deepl_translate.const import (  # noqa: E402
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.deepl_translate.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)

API_KEY = "secret-test-key:fx"
BASE = "https://api-free.deepl.com"
USAGE = {"character_count": 12345, "character_limit": 500000}


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


async def test_user_flow_preselects_the_server_language_and_creates_an_entry(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    hass.config.language = "de"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form" and result["step_id"] == "user"
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
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
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
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_DEFAULT_TARGET_LANGUAGE: "DE"}
    )
    assert result["type"] == "form" and result["errors"] == {"base": error}


async def test_the_same_account_cannot_be_added_twice(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    for expected in ("create_entry", "abort"):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
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
    assert diagnostics["free_plan"] is True
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
    mock_translation(aioclient_mock, "Deux")
    french = await call(hass, "translate_text", text="Two", target_language="FR")
    assert french["text"] == "Deux"  # another language is another translation
    assert aioclient_mock.call_count == 1


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
        await call(hass, "translate_text", text="Hi", target_language="XX")


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
    from custom_components.deepl_translate import async_setup

    await async_setup(hass, {})
    with pytest.raises(HomeAssistantError, match="No DeepL account"):
        await call(hass, "translate_text", text="Hello")


# --- get_languages ---------------------------------------------------------------------------


async def test_get_languages_is_cached(hass, aioclient_mock):
    mock_usage(aioclient_mock)
    await setup_entry(hass)
    aioclient_mock.get(
        f"{BASE}/v2/languages",
        json=[{"language": "DE", "name": "German", "supports_formality": True}],
    )
    response = await call(hass, "get_languages")
    assert response == {"languages": [{"code": "DE", "name": "German", "supports_formality": True}]}
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
        await call(hass, "translate_document", input_file="/etc/hostname")


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
        if path == "/v2/document":
            return {"document_id": "D1", "document_key": "K1"}
        if path == "/v2/document/D1":
            return next(statuses)
        return b"translated bytes"  # the result download

    with patch.object(DeepLClient, "_request", fake_request):
        await setup_entry(hass)
        with patch("custom_components.deepl_translate.api.asyncio.sleep", new=AsyncMock()) as sleep:
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
    with patch("custom_components.deepl_translate.api.asyncio.sleep", new=AsyncMock()) as sleep:
        usage = await client.async_get_usage()
    assert usage.character_count == 12345
    sleep.assert_awaited_once_with(7.0)


async def test_client_gives_up_after_repeated_overload():
    session = ScriptedSession(*[(529, {}, {})] * 3)
    client = DeepLClient(session, API_KEY, "test")
    with patch("custom_components.deepl_translate.api.asyncio.sleep", new=AsyncMock()) as sleep:
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
