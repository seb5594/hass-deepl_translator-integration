"""DeepL Translator: the DeepL translation service as Home Assistant services and sensors."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import DeepLAuthError, DeepLError, Translation
from .cache import TranslationCache
from .const import (
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CACHE_SIZE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .coordinator import DeepLUsageCoordinator
from .data import DeepLRuntimeData, async_create_client
from .languages import target_from_home_assistant_language
from .oauth import async_create_oauth_backend
from .services import DeepLServices

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once, so they exist even before an account is loaded."""
    DeepLServices(hass).register()
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Connect to DeepL with the stored API key or OAuth sign-in."""
    options = entry.options
    coordinator: DeepLUsageCoordinator | None = None
    platforms: list[Platform] = []

    if CONF_API_KEY in entry.data:
        client = await async_create_client(hass, entry.data[CONF_API_KEY])
        coordinator = DeepLUsageCoordinator(
            hass, client, options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        await coordinator.async_config_entry_first_refresh()
        platforms = [Platform.SENSOR]
    else:
        client = await async_create_oauth_backend(hass, entry)
        try:
            await client.async_connect()
        except DeepLAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DeepLError as err:
            raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = DeepLRuntimeData(
        entry=entry,
        client=client,
        coordinator=coordinator,
        cache=TranslationCache[Translation](options.get(CONF_CACHE_SIZE, DEFAULT_CACHE_SIZE)),
        default_target_language=options.get(
            CONF_DEFAULT_TARGET_LANGUAGE,
            target_from_home_assistant_language(hass.config.language),
        ),
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    if platforms:
        await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an account."""
    platforms = [Platform.SENSOR] if CONF_API_KEY in entry.data else []
    if unloaded := await hass.config_entries.async_unload_platforms(entry, platforms):
        runtime = hass.data[DOMAIN].pop(entry.entry_id)
        if runtime.coordinator is not None:
            await runtime.coordinator.async_shutdown()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed options by reloading the account."""
    await hass.config_entries.async_reload(entry.entry_id)
