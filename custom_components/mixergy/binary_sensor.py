"""Binary sensor platform for the Mixergy integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import TankData
from .const import LOW_HOT_WATER_THRESHOLD, NO_HOT_WATER_THRESHOLD
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity


@dataclass(frozen=True, kw_only=True)
class MixergyBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Mixergy binary sensor."""

    is_on_fn: Callable[[TankData], bool]
    available_fn: Callable[[TankData], bool] = lambda _: True


BINARY_SENSOR_DESCRIPTIONS: tuple[
    MixergyBinarySensorEntityDescription, ...
] = (
    # ── Heat source active indicators ────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="electric_heat",
        translation_key="electric_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        icon="mdi:lightning-bolt",
        is_on_fn=lambda data: data.measurement.electric_heat_source,
    ),
    MixergyBinarySensorEntityDescription(
        key="indirect_heat",
        translation_key="indirect_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        icon="mdi:fire",
        is_on_fn=lambda data: data.measurement.indirect_heat_source,
    ),
    MixergyBinarySensorEntityDescription(
        key="heatpump_heat",
        translation_key="heatpump_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        icon="mdi:heat-pump",
        is_on_fn=lambda data: data.measurement.heatpump_heat_source,
    ),
    # ── Heating status ───────────────────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="is_heating",
        translation_key="is_heating",
        device_class=BinarySensorDeviceClass.HEAT,
        icon="mdi:water-boiler",
        is_on_fn=lambda data: data.measurement.is_heating,
    ),
    # ── Water level alerts ───────────────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="low_hot_water",
        translation_key="low_hot_water",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-percent-alert",
        is_on_fn=lambda data: data.measurement.charge < LOW_HOT_WATER_THRESHOLD,
    ),
    MixergyBinarySensorEntityDescription(
        key="no_hot_water",
        translation_key="no_hot_water",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-remove-outline",
        is_on_fn=lambda data: data.measurement.charge < NO_HOT_WATER_THRESHOLD,
    ),
    # ── Holiday mode ─────────────────────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="holiday_mode",
        translation_key="holiday_mode",
        icon="mdi:airplane-takeoff",
        is_on_fn=lambda data: data.measurement.in_holiday_mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mixergy binary sensor entities."""
    coordinator = entry.runtime_data

    async_add_entities(
        MixergyBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class MixergyBinarySensor(MixergyEntity, BinarySensorEntity):
    """Representation of a Mixergy binary sensor."""

    entity_description: MixergyBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: MixergyCoordinator,
        description: MixergyBinarySensorEntityDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.data.info.serial_number}_{description.key}"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is on."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return (
            super().available
            and self.entity_description.available_fn(self.coordinator.data)
        )
