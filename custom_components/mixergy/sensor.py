"""Sensor platform for the Mixergy integration."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import TankData
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity


@dataclass(frozen=True, kw_only=True)
class MixergySensorEntityDescription(SensorEntityDescription):
    """Describe a Mixergy sensor."""

    value_fn: Callable[[TankData], float | int | str | datetime | None]
    available_fn: Callable[[TankData], bool] = lambda _: True


SENSOR_DESCRIPTIONS: tuple[MixergySensorEntityDescription, ...] = (
    # ── Temperature sensors ──────────────────────────────────────────
    MixergySensorEntityDescription(
        key="hot_water_temperature",
        translation_key="hot_water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.measurement.hot_water_temperature,
    ),
    MixergySensorEntityDescription(
        key="coldest_water_temperature",
        translation_key="coldest_water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.measurement.coldest_water_temperature,
    ),
    MixergySensorEntityDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.settings.target_temperature,
    ),
    MixergySensorEntityDescription(
        key="cleansing_temperature",
        translation_key="cleansing_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.settings.cleansing_temperature,
    ),
    # ── Charge sensors ───────────────────────────────────────────────
    MixergySensorEntityDescription(
        key="charge",
        translation_key="charge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        suggested_display_precision=0,
        value_fn=lambda data: data.measurement.charge,
    ),
    MixergySensorEntityDescription(
        key="target_charge",
        translation_key="target_charge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        suggested_display_precision=0,
        value_fn=lambda data: data.measurement.target_charge,
    ),
    # ── Power sensors ────────────────────────────────────────────────
    MixergySensorEntityDescription(
        key="electric_power",
        translation_key="electric_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            data.measurement.clamp_power_w
            if data.measurement.electric_heat_source
            else 0
        ),
    ),
    MixergySensorEntityDescription(
        key="pv_power",
        translation_key="pv_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda data: data.measurement.pv_power_kw,
        available_fn=lambda data: data.info.has_pv_diverter,
    ),
    MixergySensorEntityDescription(
        key="clamp_power",
        translation_key="clamp_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.measurement.clamp_power_w,
        available_fn=lambda data: data.info.has_pv_diverter,
    ),
    # ── Heat source sensors ──────────────────────────────────────────
    MixergySensorEntityDescription(
        key="active_heat_source",
        translation_key="active_heat_source",
        device_class=SensorDeviceClass.ENUM,
        options=["electric", "indirect", "heat_pump", "none"],
        icon="mdi:fire",
        value_fn=lambda data: data.measurement.active_heat_source.value,
    ),
    MixergySensorEntityDescription(
        key="default_heat_source",
        translation_key="default_heat_source",
        device_class=SensorDeviceClass.ENUM,
        options=["electric", "indirect", "heat_pump"],
        icon="mdi:fire-circle",
        value_fn=lambda data: data.schedule.default_heat_source,
    ),
    # ── Holiday date sensors ─────────────────────────────────────────
    MixergySensorEntityDescription(
        key="holiday_start",
        translation_key="holiday_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:airplane-takeoff",
        value_fn=lambda data: data.schedule.holiday_start,
    ),
    MixergySensorEntityDescription(
        key="holiday_end",
        translation_key="holiday_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:airplane-landing",
        value_fn=lambda data: data.schedule.holiday_end,
    ),
    # ── Diagnostic / info sensors ────────────────────────────────────
    MixergySensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.info.firmware_version,
    ),
    MixergySensorEntityDescription(
        key="model",
        translation_key="model",
        icon="mdi:water-boiler",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.info.model_code,
    ),
    MixergySensorEntityDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.last_update_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mixergy sensor entities."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        MixergySensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]

    # Energy accumulation sensors (persisted across restarts via RestoreSensor)
    entities.extend([
        MixergyEnergySensor(
            coordinator,
            key="electric_energy",
            translation_key="electric_energy",
            icon="mdi:lightning-bolt",
            power_w_fn=lambda data: (
                data.measurement.clamp_power_w
                if data.measurement.electric_heat_source
                else 0.0
            ),
        ),
        MixergyEnergySensor(
            coordinator,
            key="pv_energy",
            translation_key="pv_energy",
            icon="mdi:solar-power",
            power_w_fn=lambda data: data.measurement.pv_power_kw * 1000,
            available_fn=lambda data: data.info.has_pv_diverter,
        ),
    ])

    async_add_entities(entities)


class MixergySensor(MixergyEntity, SensorEntity):
    """Representation of a Mixergy sensor."""

    entity_description: MixergySensorEntityDescription

    def __init__(
        self,
        coordinator: MixergyCoordinator,
        description: MixergySensorEntityDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.data.info.serial_number}_{description.key}"
        )

    @property
    def native_value(self) -> float | int | str | datetime | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return (
            super().available
            and self.entity_description.available_fn(self.coordinator.data)
        )


class MixergyEnergySensor(MixergyEntity, RestoreSensor):
    """Cumulative energy sensor backed by per-poll power readings.

    Uses RestoreSensor so the running total survives HA restarts.
    Accumulation: ΔE (kWh) = P (W) × Δt (h) / 1000
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self,
        coordinator: MixergyCoordinator,
        *,
        key: str,
        translation_key: str,
        icon: str,
        power_w_fn: Callable[[TankData], float],
        available_fn: Callable[[TankData], bool] = lambda _: True,
    ) -> None:
        """Initialise the energy sensor."""
        super().__init__(coordinator)
        self._power_w_fn = power_w_fn
        self._available_fn = available_fn
        self._accumulated_kwh: float = 0.0
        self._last_update: float | None = None

        self._attr_unique_id = f"{coordinator.data.info.serial_number}_{key}"
        self._attr_translation_key = translation_key
        self._attr_icon = icon

    async def async_added_to_hass(self) -> None:
        """Restore previous total and begin accumulating."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._accumulated_kwh = float(last.native_value or 0)
            except (ValueError, TypeError):
                self._accumulated_kwh = 0.0
        self._last_update = time.monotonic()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate power over elapsed time to accumulate energy."""
        now = time.monotonic()
        if self._last_update is not None:
            elapsed_hours = (now - self._last_update) / 3600
            power_w = self._power_w_fn(self.coordinator.data)
            if power_w > 0:
                self._accumulated_kwh += (power_w / 1000) * elapsed_hours
        self._last_update = now
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Return the accumulated energy in kWh."""
        return round(self._accumulated_kwh, 4)

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return super().available and self._available_fn(self.coordinator.data)
