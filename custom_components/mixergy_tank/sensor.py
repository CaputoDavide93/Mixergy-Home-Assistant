"""Sensor platform for the Mixergy integration."""

from __future__ import annotations

import logging
import math
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
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import OperatingReason, TankData
from .const import CONF_ELECTRIC_RATE, PERCENTAGE_UNIT
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity

_LOGGER = logging.getLogger(__name__)

# Read-only, coordinator-driven platform — no per-entity API fan-out.
PARALLEL_UPDATES = 0


def _capped_elapsed_hours(
    now: float, last_update: float | None, interval: object
) -> float:
    """Hours since the last tick, capped at 2× the poll interval, floored at 0.

    Capping stops a long outage from crediting a fictitious multi-hour spike;
    flooring at 0 stops clock skew / NTP correction from subtracting from a
    TOTAL_INCREASING total (which HA would read as a counter reset).
    """
    if last_update is None:
        return 0.0
    elapsed = (now - last_update) / 3600
    total_seconds = getattr(interval, "total_seconds", None)
    if callable(total_seconds):
        cap = (total_seconds() * 2) / 3600
        elapsed = min(elapsed, cap)
    return max(0.0, elapsed)


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
        available_fn=lambda data: data.measurement.hot_water_temperature is not None,
    ),
    MixergySensorEntityDescription(
        key="coldest_water_temperature",
        translation_key="coldest_water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.measurement.coldest_water_temperature,
        available_fn=lambda data: (
            data.measurement.coldest_water_temperature is not None
        ),
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
        native_unit_of_measurement=PERCENTAGE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.measurement.charge,
        available_fn=lambda data: data.measurement.charge is not None,
    ),
    MixergySensorEntityDescription(
        key="target_charge",
        translation_key="target_charge",
        native_unit_of_measurement=PERCENTAGE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: data.measurement.target_charge,
        available_fn=lambda data: data.measurement.target_charge is not None,
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
            else 0.0
        ),
        available_fn=lambda data: (
            not data.measurement.electric_heat_source
            or data.measurement.clamp_power_w is not None
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
        available_fn=lambda data: (
            data.info.has_pv_diverter and data.measurement.pv_power_kw is not None
        ),
    ),
    MixergySensorEntityDescription(
        key="clamp_power",
        translation_key="clamp_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.measurement.clamp_power_w,
        available_fn=lambda data: (
            data.info.has_pv_diverter and data.measurement.clamp_power_w is not None
        ),
    ),
    # ── Heat source sensors ──────────────────────────────────────────
    MixergySensorEntityDescription(
        key="active_heat_source",
        translation_key="active_heat_source",
        device_class=SensorDeviceClass.ENUM,
        options=["electric", "indirect", "heat_pump", "none"],
        value_fn=lambda data: data.measurement.active_heat_source.value,
    ),
    MixergySensorEntityDescription(
        key="default_heat_source",
        translation_key="default_heat_source",
        device_class=SensorDeviceClass.ENUM,
        options=["electric", "indirect", "heat_pump"],
        value_fn=lambda data: data.schedule.default_heat_source,
    ),
    MixergySensorEntityDescription(
        key="operating_reason",
        translation_key="operating_reason",
        device_class=SensorDeviceClass.ENUM,
        options=[reason.value for reason in OperatingReason],
        value_fn=lambda data: (
            data.measurement.operating_reason.value
            if data.measurement.operating_reason is not None
            else None
        ),
        available_fn=lambda data: data.measurement.operating_reason is not None,
    ),
    # ── Holiday date sensors ─────────────────────────────────────────
    MixergySensorEntityDescription(
        key="holiday_start",
        translation_key="holiday_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.schedule.holiday_start,
    ),
    MixergySensorEntityDescription(
        key="holiday_end",
        translation_key="holiday_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.schedule.holiday_end,
    ),
    # ── Diagnostic / info sensors ────────────────────────────────────
    MixergySensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.info.firmware_version,
    ),
    MixergySensorEntityDescription(
        key="model",
        translation_key="model",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.info.model_code,
    ),
    MixergySensorEntityDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.last_update_time,
    ),
    MixergySensorEntityDescription(
        key="recorded_time",
        translation_key="recorded_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.measurement.recorded_time,
        available_fn=lambda data: data.measurement.recorded_time is not None,
    ),
    MixergySensorEntityDescription(
        key="received_time",
        translation_key="received_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.measurement.received_time,
        available_fn=lambda data: data.measurement.received_time is not None,
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
        MixergySensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    ]

    # Energy accumulation sensors (persisted across restarts via RestoreSensor)
    entities.extend(
        [
            MixergyEnergySensor(
                coordinator,
                key="electric_energy",
                translation_key="electric_energy",
                power_w_fn=lambda data: (
                    data.measurement.clamp_power_w or 0.0
                    if data.measurement.electric_heat_source
                    else 0.0
                ),
            ),
            MixergyEnergySensor(
                coordinator,
                key="pv_energy",
                translation_key="pv_energy",
                power_w_fn=lambda data: (data.measurement.pv_power_kw or 0.0) * 1000,
                available_fn=lambda data: (
                    data.info.has_pv_diverter
                    and data.measurement.pv_power_kw is not None
                ),
            ),
        ]
    )

    # Optional electric cost sensor — only when a tariff rate is configured.
    rate = entry.options.get(CONF_ELECTRIC_RATE, 0.0)
    if rate and rate > 0:
        entities.append(MixergyElectricCostSensor(coordinator, rate=rate))

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
        return super().available and self.entity_description.available_fn(
            self.coordinator.data
        )


class _MixergyAccumulatingSensor(MixergyEntity, RestoreSensor):
    """Shared persistence and integration safeguards for running totals."""

    def __init__(
        self,
        coordinator: MixergyCoordinator,
        *,
        key: str,
        translation_key: str,
        available_fn: Callable[[TankData], bool] = lambda _: True,
    ) -> None:
        """Initialise a persisted running-total sensor."""
        super().__init__(coordinator)
        self._available_fn = available_fn
        self._accumulated_value = 0.0
        self._last_update: float | None = None
        self._attr_unique_id = f"{coordinator.data.info.serial_number}_{key}"
        self._attr_translation_key = translation_key

    def _value_per_hour(self, data: TankData) -> float:
        """Return the value accumulated over one hour at the current rate."""
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        """Restore the total, start the wall clock, and publish immediately.

        Publishing the restored value avoids a transient zero that Home
        Assistant could interpret as a counter reset. Wall-clock time lets a
        short restart gap be bridged, while the integration cap below limits
        how much can be credited after a longer outage.
        """
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._accumulated_value = float(last.native_value or 0)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                self._accumulated_value = 0.0
        self._last_update = time.time()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Accumulate one safe, bounded interval from a fresh reading."""
        now = time.time()
        if (
            not self.coordinator.last_update_success
            or self.coordinator.data.measurement.report_is_fresh is False
        ):
            # Never persist a value derived from failed or stale data, and do
            # not credit the gap later when fresh reports resume.
            self._last_update = now
            self.async_write_ha_state()
            return

        if self._last_update is not None:
            interval = getattr(self.coordinator, "update_interval", None)
            elapsed_hours = _capped_elapsed_hours(now, self._last_update, interval)
            value_per_hour = self._value_per_hour(self.coordinator.data)
            # A non-finite sample must never poison a restored total.
            if math.isfinite(value_per_hour) and value_per_hour > 0:
                self._accumulated_value += value_per_hour * elapsed_hours
        self._last_update = now
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Return a finite accumulated value."""
        if not math.isfinite(self._accumulated_value):
            _LOGGER.warning(
                "Accumulator for %s went non-finite (%s); resetting to 0",
                self._attr_unique_id,
                self._accumulated_value,
            )
            self._accumulated_value = 0.0
        return round(self._accumulated_value, 4)

    @property
    def available(self) -> bool:
        """Return True if the entity and its source reading are available."""
        return super().available and self._available_fn(self.coordinator.data)


class MixergyEnergySensor(_MixergyAccumulatingSensor):
    """Cumulative energy sensor backed by per-poll power readings."""

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
        power_w_fn: Callable[[TankData], float],
        available_fn: Callable[[TankData], bool] = lambda _: True,
    ) -> None:
        """Initialise the energy sensor."""
        self._power_w_fn = power_w_fn
        super().__init__(
            coordinator,
            key=key,
            translation_key=translation_key,
            available_fn=available_fn,
        )

    def _value_per_hour(self, data: TankData) -> float:
        """Convert the current power in watts to kWh accumulated per hour."""
        return self._power_w_fn(data) / 1000

    @property
    def _accumulated_kwh(self) -> float:
        """Compatibility alias for the energy-specific accumulator name."""
        return self._accumulated_value

    @_accumulated_kwh.setter
    def _accumulated_kwh(self, value: float) -> None:
        self._accumulated_value = value


class MixergyElectricCostSensor(_MixergyAccumulatingSensor):
    """Cumulative cost of electric immersion heating.

    Integrates electric power × elapsed time × tariff into a running cost.
    Stores the COST directly (not kWh) so RestoreSensor round-trips correctly
    even if the tariff later changes. Created only when a rate is configured.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    # HA's DEVICE_CLASS_STATE_CLASSES permits ONLY `TOTAL` for MONETARY —
    # TOTAL_INCREASING logs an "impossible state class" warning on every
    # state write and fails long-term statistics validation. The value is
    # still a monotonic running total, so TOTAL (without last_reset)
    # records identically.
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_translation_key = "electric_cost"

    def __init__(self, coordinator: MixergyCoordinator, *, rate: float) -> None:
        """Initialise the cost sensor."""
        self._rate = rate
        super().__init__(
            coordinator,
            key="electric_cost",
            translation_key="electric_cost",
        )
        self._attr_native_unit_of_measurement = coordinator.hass.config.currency

    def _value_per_hour(self, data: TankData) -> float:
        """Return the cost accumulated per hour at the current power."""
        measurement = data.measurement
        power_w = (
            measurement.clamp_power_w or 0.0
            if measurement.electric_heat_source
            else 0.0
        )
        return (power_w / 1000) * self._rate

    @property
    def _accumulated_cost(self) -> float:
        """Compatibility alias for the cost-specific accumulator name."""
        return self._accumulated_value

    @_accumulated_cost.setter
    def _accumulated_cost(self, value: float) -> None:
        self._accumulated_value = value
