"""The optional API-key account in ``configuration.yaml``.

YAML only ever describes one API-key account. It is imported into a normal config entry, so
the account shows up in the UI, keeps its sensors and can still be removed there.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .accounts import account_title, account_unique_id
from .const import (
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_DISCOVER_TRANSLATOR,
    CONF_UPDATE_INTERVAL,
    CONF_YAML_MANAGED,
    DOMAIN,
    MAX_CACHE_SIZE,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)
from .languages import normalize_target_language

YAML_ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): vol.All(cv.string, str.strip, vol.Length(min=1)),
        vol.Optional(CONF_DEFAULT_TARGET_LANGUAGE): vol.All(cv.string, normalize_target_language),
        vol.Optional(CONF_UPDATE_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
        ),
        vol.Optional(CONF_CACHE_SIZE): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_CACHE_SIZE)),
        vol.Optional(CONF_DISCOVER_TRANSLATOR): cv.boolean,
    }
)

# Other integrations' keys share configuration.yaml, so unknown top-level keys must pass.
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): YAML_ACCOUNT_SCHEMA}, extra=vol.ALLOW_EXTRA)


class YamlConflict(Exception):
    """The YAML key belongs to an account other than the one YAML manages."""


def _find_accounts(
    entries: list[ConfigEntry], api_key: str
) -> tuple[ConfigEntry | None, ConfigEntry | None]:
    """The account YAML manages, and the account that already uses this key."""
    unique_id = account_unique_id(api_key)
    managed = next(
        (e for e in entries if e.source == SOURCE_IMPORT or e.data.get(CONF_YAML_MANAGED)), None
    )
    matching = next(
        (e for e in entries if e.unique_id == unique_id or e.data.get(CONF_API_KEY) == api_key),
        None,
    )
    return managed, matching


def apply_to_existing_account(hass: HomeAssistant, imported: dict[str, Any]) -> bool:
    """Write the YAML values into the account they belong to; False if there is none yet.

    This is synchronous on purpose: during startup it runs before any account is set up, so
    the account starts with the new values and no reload is needed. A loaded account is
    reloaded by its own update listener.
    """
    imported = dict(imported)
    api_key = imported.pop(CONF_API_KEY)
    unique_id = account_unique_id(api_key)
    managed, matching = _find_accounts(hass.config_entries.async_entries(DOMAIN), api_key)
    if managed is not None and matching is not None and managed.entry_id != matching.entry_id:
        raise YamlConflict
    current = managed or matching
    if current is None:
        return False
    data = {**current.data, CONF_API_KEY: api_key, CONF_YAML_MANAGED: True}
    options = {**current.options, **imported}
    if (data, options, current.unique_id) != (current.data, current.options, unique_id):
        hass.config_entries.async_update_entry(
            current, data=data, options=options, unique_id=unique_id, title=account_title(api_key)
        )
    return True
