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
from .const import (
    CONF_LOW_WATER_THRESHOLD,
    CONF_NO_WATER_THRESHOLD,
    LOW_HOT_WATER_THRESHOLD,
    NO_HOT_WATER_THRESHOLD,
)
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity

# Read-only, coordinator-driven platform — no per-entity API fan-out.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MixergyBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a Mixergy binary sensor."""

    is_on_fn: Callable[[TankData], bool]
    available_fn: Callable[[TankData], bool] = lambda _: True


# Sensors whose state doesn't depend on user-configurable thresholds.
STATIC_BINARY_SENSOR_DESCRIPTIONS: tuple[
    MixergyBinarySensorEntityDescription, ...
] = (
    # ── Heat source active indicators ────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="electric_heat",
        translation_key="electric_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=lambda data: data.measurement.electric_heat_source,
    ),
    MixergyBinarySensorEntityDescription(
        key="indirect_heat",
        translation_key="indirect_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=lambda data: data.measurement.indirect_heat_source,
    ),
    MixergyBinarySensorEntityDescription(
        key="heatpump_heat",
        translation_key="heatpump_heat",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=lambda data: data.measurement.heatpump_heat_source,
    ),
    # ── Heating status ───────────────────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="is_heating",
        translation_key="is_heating",
        device_class=BinarySensorDeviceClass.HEAT,
        is_on_fn=lambda data: data.measurement.is_heating,
    ),
    # ── Holiday mode ─────────────────────────────────────────────────
    MixergyBinarySensorEntityDescription(
        key="holiday_mode",
        translation_key="holiday_mode",
        is_on_fn=lambda data: data.measurement.in_holiday_mode,
    ),
)


def _threshold_descriptions(
    low: float, no: float
) -> tuple[MixergyBinarySensorEntityDescription, ...]:
    """Build the water-level alert sensors using configured thresholds."""
    return (
        MixergyBinarySensorEntityDescription(
            key="low_hot_water",
            translation_key="low_hot_water",
            device_class=BinarySensorDeviceClass.PROBLEM,
            is_on_fn=lambda data: data.measurement.charge < low,
        ),
        MixergyBinarySensorEntityDescription(
            key="no_hot_water",
            translation_key="no_hot_water",
            device_class=BinarySensorDeviceClass.PROBLEM,
            is_on_fn=lambda data: data.measurement.charge < no,
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mixergy binary sensor entities.

    Water-level thresholds are read from options and baked into the entity
    descriptions here, so a threshold change takes effect when the entry
    reloads. That reload comes from MixergyOptionsFlow subclassing
    OptionsFlowWithReload — deliberately NOT from an update listener, which
    __init__ explains must not be re-added.
    """
    coordinator = entry.runtime_data
    low = entry.options.get(CONF_LOW_WATER_THRESHOLD, LOW_HOT_WATER_THRESHOLD)
    no = entry.options.get(CONF_NO_WATER_THRESHOLD, NO_HOT_WATER_THRESHOLD)

    descriptions = (
        *STATIC_BINARY_SENSOR_DESCRIPTIONS,
        *_threshold_descriptions(low, no),
    )
    async_add_entities(
        MixergyBinarySensor(coordinator, description)
        for description in descriptions
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
