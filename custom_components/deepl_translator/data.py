"""What a loaded config entry keeps in memory."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import DeepLClient, Translation
from .backend import TranslationBackend
from .cache import TranslationCache
from .const import DOMAIN
from .coordinator import DeepLUsageCoordinator


@dataclass
class DeepLRuntimeData:
    """Shared by the services and the entities of one DeepL account.

    The coordinator only exists for accounts with an API key: DeepL offers no usage
    figures to accounts that signed in with OAuth.
    """

    entry: ConfigEntry
    client: TranslationBackend
    coordinator: DeepLUsageCoordinator | None
    cache: TranslationCache[Translation]
    default_target_language: str


async def async_user_agent(hass: HomeAssistant) -> str:
    """Identify this integration to DeepL."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"home-assistant-{DOMAIN}/{integration.version}"


async def async_create_client(hass: HomeAssistant, api_key: str) -> DeepLClient:
    """Build an API-key client on Home Assistant's shared HTTP session."""
    return DeepLClient(async_get_clientsession(hass), api_key, await async_user_agent(hass))
