"""Validate the optional API-key configuration in configuration.yaml."""

import voluptuous as vol

from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_UPDATE_INTERVAL,
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
    }
)

CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): YAML_ACCOUNT_SCHEMA}, extra=vol.ALLOW_EXTRA)
