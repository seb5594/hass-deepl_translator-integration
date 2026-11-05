"""Offer the optional integration translator when its files are installed."""

from __future__ import annotations

from awesomeversion import AwesomeVersion, AwesomeVersionException
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.start import async_at_started
from homeassistant.loader import async_get_custom_components

TRANSLATOR = "custom_integration_translator"
MINIMUM_TRANSLATOR_VERSION = "2026.11.05.3"


@callback
def async_watch_translator(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Use startup and installer events; never poll or install the companion."""
    # The optional companion needs this core version. DeepL still supports older cores.
    if (MAJOR_VERSION, MINOR_VERSION) < (2026, 11):
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
