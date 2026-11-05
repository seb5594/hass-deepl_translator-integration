"""Offer the optional integration translator when its files are installed."""

from __future__ import annotations

from awesomeversion import AwesomeVersion, AwesomeVersionException
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.start import async_at_started
from homeassistant.loader import async_get_custom_components

from .const import CONF_DISCOVER_TRANSLATOR, DOMAIN

TRANSLATOR = "custom_integration_translator"
MINIMUM_TRANSLATOR_VERSION = "2026.11.05.3"


@callback
def async_watch_translator(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Use startup and installer events; never poll or install the companion."""
    if not entry.options.get(CONF_DISCOVER_TRANSLATOR, True):
        # Another enabled account may still offer discovery. Leave forms the user
        # has already opened for account selection alone.
        if not any(
            other.entry_id != entry.entry_id
            and other.state is ConfigEntryState.LOADED
            and other.options.get(CONF_DISCOVER_TRANSLATOR, True)
            for other in hass.config_entries.async_entries(DOMAIN)
        ):
            for flow in hass.config_entries.flow.async_progress():
                if (
                    flow["handler"] == TRANSLATOR
                    and flow["context"].get("source") == SOURCE_INTEGRATION_DISCOVERY
                    and flow["step_id"] == "discovery_confirm"
                ):
                    hass.config_entries.flow.async_abort(flow["flow_id"])
        return

    active = True

    @callback
    def stop() -> None:
        nonlocal active
        active = False

    entry.async_on_unload(stop)

    async def discover(_hass=None) -> None:
        if not active or hass.config_entries.async_entries(TRANSLATOR):
            return
        integrations = await async_get_custom_components(hass)
        integration = integrations.get(TRANSLATOR)
        if not active or integration is None or not integration.config_flow:
            return
        try:
            if AwesomeVersion(integration.version) < AwesomeVersion(
                MINIMUM_TRANSLATOR_VERSION
            ):
                return
            # Earlier companion releases needed Core 2026.11; .4 adds 2023.7+.
            if (MAJOR_VERSION, MINOR_VERSION) < (2026, 11) and AwesomeVersion(
                integration.version
            ) < AwesomeVersion("2026.11.05.4"):
                return
        except AwesomeVersionException:
            return
        discovery_flow.async_create_flow(
            hass, TRANSLATOR, {"source": SOURCE_INTEGRATION_DISCOVERY}, {}
        )

    async def repository_changed(data) -> None:
        if isinstance(data, dict) and data.get("action") == "install":
            await discover()

    async def marketplace_finished(data) -> None:
        if isinstance(data, dict) and data.get("progress") is False:
            await discover()

    entry.async_on_unload(async_at_started(hass, discover))
    for signal, handler in (
        ("hacs_dispatch_repository", repository_changed),
        ("marketplace_repository_install_progress", marketplace_finished),
    ):
        entry.async_on_unload(async_dispatcher_connect(hass, signal, handler))
