"""Diagnostics for bug reports, without the API key."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {CONF_API_KEY, "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Describe the account's state."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "free_plan": runtime.client.is_free_plan,
        "default_target_language": runtime.default_target_language,
        "cached_translations": len(runtime.cache),
        "usage": asdict(runtime.coordinator.data),
    }
