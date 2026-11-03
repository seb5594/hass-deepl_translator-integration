"""Post-install discovery and YAML import against real Home Assistant."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import instance_id
from homeassistant.loader import async_get_zeroconf
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deepl_translator import CONFIG_SCHEMA
from custom_components.deepl_translator.config_flow import _unique_id
from custom_components.deepl_translator.const import (
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    CONF_YAML_MANAGED,
    DOMAIN,
)

KEY = "yaml-test-key:fx"
USAGE_URL = "https://api-free.deepl.com/v2/usage"


@pytest.fixture(autouse=True)
def usage(aioclient_mock):
    aioclient_mock.get(USAGE_URL, json={"character_count": 0, "character_limit": 500000})


async def discover(hass, uuid=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF},
        data=SimpleNamespace(properties={"uuid": uuid or await instance_id.async_get(hass)}),
    )


async def test_manifest_registers_local_ha_discovery_and_only_suggests_setup(hass):
    matchers = await async_get_zeroconf(hass)
    assert any(item["domain"] == DOMAIN for item in matchers["_home-assistant._tcp.local."])
    with patch("custom_components.deepl_translator.config_flow.async_create_client") as client:
        result = await discover(hass)
        assert result["type"] == "form" and result["step_id"] == "discovery_confirm"
        assert not hass.config_entries.async_entries(DOMAIN)
        client.assert_not_called()
    duplicate = await discover(hass)
    assert duplicate["type"] == "abort" and duplicate["reason"] == "already_in_progress"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "menu" and result["menu_options"] == ["api_key", "oauth"]


async def test_other_servers_do_not_trigger_discovery(hass):
    result = await discover(hass, "another-ha-instance")
    assert result["type"] == "abort" and result["reason"] == "not_local_instance"


@pytest.mark.parametrize("source,unique_id", [
    (config_entries.SOURCE_USER, "api-account"),
    (config_entries.SOURCE_USER, "oauth-account"),
    (config_entries.SOURCE_IGNORE, DOMAIN),
])
async def test_configured_and_ignored_accounts_are_not_suggested_again(hass, source, unique_id):
    MockConfigEntry(domain=DOMAIN, source=source, unique_id=unique_id).add_to_hass(hass)
    result = await discover(hass)
    assert result["type"] == "abort" and result["reason"] == "already_configured"


def test_yaml_schema_validates_and_normalizes_account_settings():
    config = CONFIG_SCHEMA({DOMAIN: {CONF_API_KEY: f" {KEY} ", CONF_DEFAULT_TARGET_LANGUAGE: "pt_br",
                                     CONF_UPDATE_INTERVAL: 45, CONF_CACHE_SIZE: 0}, "other": {}})
    assert config[DOMAIN][CONF_API_KEY] == KEY
    assert config[DOMAIN][CONF_DEFAULT_TARGET_LANGUAGE] == "PT-BR"
    for data in ({}, {CONF_API_KEY: " "}, {CONF_API_KEY: KEY, CONF_UPDATE_INTERVAL: 0},
                 {CONF_API_KEY: KEY, CONF_CACHE_SIZE: -1}, {CONF_API_KEY: KEY, "unknown": True}):
        with pytest.raises(vol.Invalid):
            CONFIG_SCHEMA({DOMAIN: data})


async def test_yaml_startup_imports_a_working_account_and_clears_discovery(hass):
    hass.config.language = "de"
    suggestion = await discover(hass)
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {CONF_API_KEY: KEY, CONF_CACHE_SIZE: 0}})
    await hass.async_block_till_done()
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == config_entries.SOURCE_IMPORT
    assert entry.data == {CONF_API_KEY: KEY, CONF_YAML_MANAGED: True}
    assert entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "DE"
    assert hass.data[DOMAIN][entry.entry_id].default_target_language == "DE"
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert suggestion["flow_id"] not in [flow["flow_id"] for flow in hass.config_entries.flow.async_progress()]


async def test_repeated_yaml_import_reuses_entry_and_key_rotation_updates_it(hass):
    async def imported(data):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
        await hass.async_block_till_done()
        return result

    await imported({CONF_API_KEY: KEY, CONF_DEFAULT_TARGET_LANGUAGE: "fr", CONF_CACHE_SIZE: 10})
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await imported({CONF_API_KEY: KEY})
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    assert entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "FR"
    assert entry.options[CONF_CACHE_SIZE] == 10
    rotated = "rotated-key:fx"
    await imported({CONF_API_KEY: rotated, CONF_CACHE_SIZE: 0})
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.data[CONF_API_KEY] == rotated
    assert entry.unique_id == _unique_id(rotated)
    assert entry.options[CONF_CACHE_SIZE] == 0
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_yaml_adopts_same_ui_account_without_duplicates(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=_unique_id(KEY), data={CONF_API_KEY: KEY},
                            options={CONF_DEFAULT_TARGET_LANGUAGE: "FR"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={CONF_API_KEY: KEY, CONF_CACHE_SIZE: 0}
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.data[CONF_YAML_MANAGED]
    assert entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "FR"


async def test_yaml_rotation_does_not_collide_with_another_account(hass):
    managed = MockConfigEntry(domain=DOMAIN, source=config_entries.SOURCE_IMPORT, unique_id=_unique_id(KEY),
                              data={CONF_API_KEY: KEY, CONF_YAML_MANAGED: True})
    managed.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, unique_id=_unique_id("other:fx"), data={CONF_API_KEY: "other:fx"})
    other.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={CONF_API_KEY: "other:fx"}
    )
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    assert managed.data[CONF_API_KEY] == KEY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
