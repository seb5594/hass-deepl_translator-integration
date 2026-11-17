"""Sensors that show how much of the DeepL quota is used."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

try:
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:  # Home Assistant older than 2023.9
    from homeassistant.helpers.entity import DeviceInfo

from .api import Usage
from .const import DOMAIN
from .coordinator import DeepLUsageCoordinator

UNIT_CHARACTERS = "characters"


def _description_dataclass(cls):
    """Entity descriptions are frozen dataclasses since Home Assistant 2024.4 and plain ones
    before; a subclass has to follow its base class."""
    try:
        return dataclass(frozen=True, kw_only=True)(cls)
    except TypeError:
        return dataclass(kw_only=True)(cls)


@_description_dataclass
class DeepLSensorDescription(SensorEntityDescription):
    """A sensor and the way to read its value from the usage data."""

    value_fn: Callable[[Usage], int | float | datetime | None]


SENSORS: tuple[DeepLSensorDescription, ...] = (
    DeepLSensorDescription(
        key="characters_used",
        translation_key="characters_used",
        native_unit_of_measurement=UNIT_CHARACTERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda usage: usage.character_count,
    ),
    DeepLSensorDescription(
        key="characters_limit",
        translation_key="characters_limit",
        native_unit_of_measurement=UNIT_CHARACTERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda usage: None if usage.is_unlimited else usage.character_limit,
    ),
    DeepLSensorDescription(
        key="characters_remaining",
        translation_key="characters_remaining",
        native_unit_of_measurement=UNIT_CHARACTERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda usage: usage.characters_remaining,
    ),
    DeepLSensorDescription(
        key="usage_percent",
        translation_key="usage_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda usage: usage.usage_percent,
    ),
    DeepLSensorDescription(
        key="billing_period_end",
        translation_key="billing_period_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda usage: dt_util.parse_datetime(usage.end_time) if usage.end_time else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the usage sensors of an account."""
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    async_add_entities(DeepLUsageSensor(coordinator, entry, description) for description in SENSORS)


class DeepLUsageSensor(CoordinatorEntity[DeepLUsageCoordinator], SensorEntity):
    """One figure of the quota."""

    _attr_has_entity_name = True
    entity_description: DeepLSensorDescription

    def __init__(
        self,
        coordinator: DeepLUsageCoordinator,
        entry: ConfigEntry,
        description: DeepLSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="DeepL",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.deepl.com/your-account/usage",
        )

    @property
    def native_value(self) -> int | float | datetime | None:
        """The current value; unknown when the account has no such limit."""
        return self.entity_description.value_fn(self.coordinator.data)
