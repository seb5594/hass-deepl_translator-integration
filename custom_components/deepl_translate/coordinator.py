"""Keeps the character quota up to date."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeepLAuthError, DeepLClient, DeepLError, Usage
from .const import DOMAIN, USAGE_REFRESH_COOLDOWN

_LOGGER = logging.getLogger(__name__)


class DeepLUsageCoordinator(DataUpdateCoordinator[Usage]):
    """Polls the usage endpoint, which is free of charge."""

    def __init__(self, hass: HomeAssistant, client: DeepLClient, interval_minutes: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} usage",
            update_interval=timedelta(minutes=interval_minutes),
            # Translations ask for a refresh; collapse bursts into a single request.
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=USAGE_REFRESH_COOLDOWN, immediate=False
            ),
        )
        self._client = client

    async def _async_update_data(self) -> Usage:
        try:
            return await self._client.async_get_usage()
        except DeepLAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DeepLError as err:
            raise UpdateFailed(str(err)) from err
