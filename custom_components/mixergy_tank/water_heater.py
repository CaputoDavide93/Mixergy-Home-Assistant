"""Water heater platform for the Mixergy integration.

Represents the tank as a first-class HA water heater: current/target
temperature, heat-source operation modes, and an away (holiday) toggle.
Exposed in Advanced mode only — Simple mode keeps the boost slider.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.water_heater import (
    STATE_ELECTRIC,
    STATE_GAS,
    STATE_HEAT_PUMP,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import is_advanced_mode
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity

# Writes go through the cloud API; serialise them.
PARALLEL_UPDATES = 1

# Target temperature bounds (match number.py / api.set_target_temperature).
MIN_TARGET_TEMP = 45
MAX_TARGET_TEMP = 70

# When away mode is toggled on we set a long holiday window; the tank reports
# in_holiday_mode while it's active and the user clears it by toggling off.
_AWAY_HOLIDAY = timedelta(days=3650)

# HA water-heater operation state  <->  Mixergy heat source.
_OP_TO_HEAT_SOURCE = {
    STATE_ELECTRIC: "electric",
    STATE_GAS: "indirect",
    STATE_HEAT_PUMP: "heat_pump",
}
_HEAT_SOURCE_TO_OP = {v: k for k, v in _OP_TO_HEAT_SOURCE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Mixergy water heater entity — Advanced mode only."""
    if not is_advanced_mode(entry):
        return
    async_add_entities([MixergyWaterHeater(entry.runtime_data)])


class MixergyWaterHeater(MixergyEntity, WaterHeaterEntity):
    """Tank represented as a Home Assistant water heater."""

    _attr_name = None  # primary entity → uses the device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_WHOLE
    _attr_min_temp = MIN_TARGET_TEMP
    _attr_max_temp = MAX_TARGET_TEMP
    # RUF012 wants ClassVar here, but WaterHeaterEntity declares
    # _attr_operation_list as an *instance* variable, so annotating it
    # ClassVar makes mypy reject the override. The list is never mutated —
    # HA reads it to build the operation dropdown — so a shared class-level
    # list is correct and matches how core integrations declare it.
    _attr_operation_list = [  # noqa: RUF012
        STATE_ELECTRIC,
        STATE_GAS,
        STATE_HEAT_PUMP,
    ]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.AWAY_MODE
    )

    def __init__(self, coordinator: MixergyCoordinator) -> None:
        """Initialise the water heater entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.data.info.serial_number}_water_heater"

    @property
    def current_temperature(self) -> float | None:
        """Return the current (top) tank temperature."""
        return self.coordinator.data.measurement.hot_water_temperature

    @property
    def target_temperature(self) -> float:
        """Return the configured target temperature."""
        return self.coordinator.data.settings.target_temperature

    @property
    def current_operation(self) -> str | None:
        """Return the current operation mode (mapped from heat source)."""
        return _HEAT_SOURCE_TO_OP.get(
            self.coordinator.data.schedule.default_heat_source
        )

    @property
    def is_away_mode_on(self) -> bool:
        """Return True when the tank is in holiday/away mode."""
        return self.coordinator.data.measurement.in_holiday_mode

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._async_write_command(
            self.coordinator.client.set_target_temperature(int(temperature)),
            "Setting the target temperature",
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set the heat source from the operation mode."""
        heat_source = _OP_TO_HEAT_SOURCE.get(operation_mode)
        if heat_source is None:
            return
        await self._async_write_command(
            self.coordinator.client.set_default_heat_source(heat_source),
            "Setting the operation mode",
        )

    async def async_turn_away_mode_on(self) -> None:
        """Enable away mode by opening a long holiday window."""
        now = dt_util.utcnow()
        await self._async_write_command(
            self.coordinator.client.set_holiday_dates(now, now + _AWAY_HOLIDAY),
            "Enabling away mode",
        )

    async def async_turn_away_mode_off(self) -> None:
        """Disable away mode by clearing the holiday window."""
        await self._async_write_command(
            self.coordinator.client.clear_holiday_dates(),
            "Disabling away mode",
        )
