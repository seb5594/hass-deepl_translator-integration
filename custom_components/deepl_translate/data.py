"""What a loaded config entry keeps in memory."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import DeepLClient, Translation
from .cache import TranslationCache
from .const import DOMAIN
from .coordinator import DeepLUsageCoordinator


@dataclass
class DeepLRuntimeData:
    """Shared by the services and the entities of one DeepL account."""

    client: DeepLClient
    coordinator: DeepLUsageCoordinator
    cache: TranslationCache[Translation]
    default_target_language: str


async def async_create_client(hass: HomeAssistant, api_key: str) -> DeepLClient:
    """Build a client on Home Assistant's shared HTTP session."""
    integration = await async_get_integration(hass, DOMAIN)
    user_agent = f"home-assistant-{DOMAIN}/{integration.version}"
    return DeepLClient(async_get_clientsession(hass), api_key, user_agent)
