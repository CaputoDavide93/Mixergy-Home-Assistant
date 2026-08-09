"""Tests for v1.3.0 features: water_heater, datetime, cost sensor, triggers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mixergy.api import (
    TankData,
    TankInfo,
    TankMeasurement,
    TankSchedule,
    TankSettings,
)


def _coordinator(
    *,
    top: float = 55.0,
    target_temp: float = 60.0,
    heat_source: str = "electric",
    holiday: bool = False,
    holiday_start: datetime | None = None,
    holiday_end: datetime | None = None,
) -> MagicMock:
    """Build a mock coordinator with real TankData."""
    coordinator = MagicMock()
    coordinator.data = TankData(
        info=TankInfo(serial_number="T1", model_code="MX-180"),
        measurement=TankMeasurement(
            hot_water_temperature=top, in_holiday_mode=holiday
        ),
        settings=TankSettings(target_temperature=target_temp),
        schedule=TankSchedule(
            default_heat_source=heat_source,
            holiday_start=holiday_start,
            holiday_end=holiday_end,
        ),
    )
    client = MagicMock()
    client.set_target_temperature = AsyncMock()
    client.set_default_heat_source = AsyncMock()
    client.set_holiday_dates = AsyncMock()
    client.clear_holiday_dates = AsyncMock()
    coordinator.client = client
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


# ── water_heater ──────────────────────────────────────────────────────────────


def test_water_heater_reads_state() -> None:
    from custom_components.mixergy.water_heater import MixergyWaterHeater

    wh = MixergyWaterHeater(_coordinator(top=58.0, target_temp=62.0))
    assert wh.current_temperature == 58.0
    assert wh.target_temperature == 62.0
    assert wh.current_operation == "electric"
    assert wh.is_away_mode_on is False


def test_water_heater_operation_mapping() -> None:
    from custom_components.mixergy.water_heater import MixergyWaterHeater

    assert MixergyWaterHeater(
        _coordinator(heat_source="indirect")
    ).current_operation == "gas"
    assert MixergyWaterHeater(
        _coordinator(heat_source="heat_pump")
    ).current_operation == "heat_pump"


@pytest.mark.asyncio
async def test_water_heater_set_temperature() -> None:
    from homeassistant.const import ATTR_TEMPERATURE

    from custom_components.mixergy.water_heater import MixergyWaterHeater

    coordinator = _coordinator()
    wh = MixergyWaterHeater(coordinator)
    await wh.async_set_temperature(**{ATTR_TEMPERATURE: 65})
    coordinator.client.set_target_temperature.assert_awaited_once_with(65)


@pytest.mark.asyncio
async def test_water_heater_set_operation_mode_maps_back() -> None:
    from custom_components.mixergy.water_heater import MixergyWaterHeater

    coordinator = _coordinator()
    wh = MixergyWaterHeater(coordinator)
    await wh.async_set_operation_mode("gas")
    coordinator.client.set_default_heat_source.assert_awaited_once_with("indirect")


@pytest.mark.asyncio
async def test_water_heater_away_mode_on_off() -> None:
    from custom_components.mixergy.water_heater import MixergyWaterHeater

    coordinator = _coordinator()
    wh = MixergyWaterHeater(coordinator)
    await wh.async_turn_away_mode_on()
    coordinator.client.set_holiday_dates.assert_awaited_once()
    await wh.async_turn_away_mode_off()
    coordinator.client.clear_holiday_dates.assert_awaited_once()


# ── datetime holiday entities ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_holiday_datetime_set_start_preserves_end() -> None:
    from custom_components.mixergy.datetime import MixergyHolidayDateTime

    end = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    coordinator = _coordinator(holiday_end=end)
    ent = MixergyHolidayDateTime(coordinator, is_start=True)

    start = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    await ent.async_set_value(start)
    coordinator.client.set_holiday_dates.assert_awaited_once_with(start, end)


@pytest.mark.asyncio
async def test_holiday_datetime_set_start_defaults_end_when_unset() -> None:
    from custom_components.mixergy.datetime import MixergyHolidayDateTime

    coordinator = _coordinator()  # no existing holiday_end
    ent = MixergyHolidayDateTime(coordinator, is_start=True)
    start = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    await ent.async_set_value(start)
    args = coordinator.client.set_holiday_dates.await_args.args
    assert args[0] == start
    assert args[1] == start + timedelta(days=7)


def test_holiday_datetime_native_value() -> None:
    from custom_components.mixergy.datetime import MixergyHolidayDateTime

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    coordinator = _coordinator(holiday_start=start)
    ent = MixergyHolidayDateTime(coordinator, is_start=True)
    assert ent.native_value == start
    assert MixergyHolidayDateTime(coordinator, is_start=False).native_value is None


# ── cost sensor ───────────────────────────────────────────────────────────────


def test_cost_sensor_integrates_with_rate() -> None:
    import time

    from custom_components.mixergy.sensor import MixergyElectricCostSensor

    coordinator = MagicMock()
    coordinator.update_interval = timedelta(seconds=30)
    coordinator.data = TankData(
        info=TankInfo(serial_number="T1"),
        measurement=TankMeasurement(
            clamp_power_w=2000.0, electric_heat_source=True
        ),
    )
    coordinator.hass = MagicMock()
    coordinator.hass.config.currency = "GBP"

    sensor = MixergyElectricCostSensor.__new__(MixergyElectricCostSensor)
    sensor.coordinator = coordinator
    sensor._rate = 0.30
    sensor._accumulated_cost = 0.0
    sensor._last_update = time.time() - 30  # 30s ago
    sensor.async_write_ha_state = MagicMock()
    sensor._attr_unique_id = "T1_electric_cost"

    sensor._handle_coordinator_update()
    # 2 kW for 30s (capped at 60s) = up to 0.0333 kWh -> * 0.30
    assert sensor._accumulated_cost > 0
    assert sensor.native_value == round(sensor._accumulated_cost, 4)


def test_cost_sensor_ignores_non_electric_power() -> None:
    import time

    from custom_components.mixergy.sensor import MixergyElectricCostSensor

    coordinator = MagicMock()
    coordinator.update_interval = timedelta(seconds=30)
    coordinator.data = TankData(
        info=TankInfo(serial_number="T1"),
        measurement=TankMeasurement(
            clamp_power_w=2000.0, electric_heat_source=False
        ),
    )
    sensor = MixergyElectricCostSensor.__new__(MixergyElectricCostSensor)
    sensor.coordinator = coordinator
    sensor._rate = 0.30
    sensor._accumulated_cost = 1.0
    sensor._last_update = time.time() - 30
    sensor.async_write_ha_state = MagicMock()
    sensor._attr_unique_id = "T1_electric_cost"

    sensor._handle_coordinator_update()
    assert sensor._accumulated_cost == 1.0  # unchanged: heat source not electric


def test_cost_sensor_state_class_is_total() -> None:
    """MONETARY permits ONLY SensorStateClass.TOTAL — TOTAL_INCREASING is
    rejected by HA's DEVICE_CLASS_STATE_CLASSES and breaks statistics."""
    from homeassistant.components.sensor import SensorStateClass

    from custom_components.mixergy.sensor import MixergyElectricCostSensor

    # HA's CachedProperties metaclass shadows class-level _attr_* with a
    # property, so read it through an instance.
    sensor = MixergyElectricCostSensor.__new__(MixergyElectricCostSensor)
    assert sensor._attr_state_class == SensorStateClass.TOTAL
    assert sensor.state_class == SensorStateClass.TOTAL


def test_percentage_entities_use_ratio_enum() -> None:
    """HA 2026.7 deprecated PERCENTAGE as a unit; use UnitOfRatio instead."""
    from homeassistant.const import UnitOfRatio

    from custom_components.mixergy.number import (
        NUMBER_DESCRIPTIONS,
        MixergyBoostNumber,
    )
    from custom_components.mixergy.sensor import SENSOR_DESCRIPTIONS

    descriptions = (*NUMBER_DESCRIPTIONS, *SENSOR_DESCRIPTIONS)
    percentage_descriptions = [
        item
        for item in descriptions
        if item.native_unit_of_measurement == UnitOfRatio.PERCENTAGE
    ]
    assert len(percentage_descriptions) == 4

    boost = MixergyBoostNumber.__new__(MixergyBoostNumber)
    assert boost.native_unit_of_measurement == UnitOfRatio.PERCENTAGE
    assert UnitOfRatio.PERCENTAGE.value == "%"


def test_cost_sensor_skips_integration_on_failed_poll() -> None:
    """A failed coordinator poll notifies listeners with STALE data; the
    cost accumulator must not integrate it (phantom cost would be
    persisted forever via RestoreSensor). The clock must resync so the
    outage window is not credited on recovery either."""
    import time

    from custom_components.mixergy.sensor import MixergyElectricCostSensor

    coordinator = MagicMock()
    coordinator.update_interval = timedelta(seconds=30)
    coordinator.last_update_success = False  # failed-poll edge
    coordinator.data = TankData(
        info=TankInfo(serial_number="T1"),
        measurement=TankMeasurement(
            clamp_power_w=3000.0, electric_heat_source=True  # stale 3 kW
        ),
    )

    sensor = MixergyElectricCostSensor.__new__(MixergyElectricCostSensor)
    sensor.coordinator = coordinator
    sensor._rate = 0.30
    sensor._accumulated_cost = 1.0
    sensor._last_update = time.time() - 30
    sensor.async_write_ha_state = MagicMock()
    sensor._attr_unique_id = "T1_electric_cost"

    before = time.time()
    sensor._handle_coordinator_update()

    assert sensor._accumulated_cost == 1.0  # no phantom cost
    assert sensor._last_update >= before  # clock resynced
    sensor.async_write_ha_state.assert_called_once()


def test_energy_sensor_skips_integration_on_failed_poll() -> None:
    """Same guard for the kWh accumulator: stale power on the
    success->failure edge must not be integrated into a persisted total."""
    import time

    from custom_components.mixergy.sensor import MixergyEnergySensor

    coordinator = MagicMock()
    coordinator.update_interval = timedelta(seconds=30)
    coordinator.last_update_success = False
    coordinator.data = MagicMock()

    sensor = MixergyEnergySensor.__new__(MixergyEnergySensor)
    sensor.coordinator = coordinator
    sensor._accumulated_kwh = 5.0
    sensor._power_w_fn = lambda _data: 3000.0  # stale 3 kW reading
    sensor._last_update = time.time() - 30
    sensor.async_write_ha_state = MagicMock()

    before = time.time()
    sensor._handle_coordinator_update()

    assert sensor._accumulated_kwh == 5.0  # no phantom energy
    assert sensor._last_update >= before  # clock resynced
    sensor.async_write_ha_state.assert_called_once()


def test_capped_elapsed_hours():
    from custom_components.mixergy.sensor import _capped_elapsed_hours

    interval = timedelta(seconds=30)
    # 1 hour gap capped to 2x30s = 60s = 0.01667h
    assert _capped_elapsed_hours(3600.0, 0.0, interval) == pytest.approx(60 / 3600)
    # negative -> 0
    assert _capped_elapsed_hours(0.0, 100.0, interval) == 0.0
    # no last update -> 0
    assert _capped_elapsed_hours(100.0, None, interval) == 0.0


# ── device triggers ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_get_triggers_maps_binary_sensors(monkeypatch) -> None:
    from custom_components.mixergy import device_trigger

    def _entry(key):
        e = MagicMock()
        e.domain = "binary_sensor"
        e.unique_id = f"T1_{key}"
        e.entity_id = f"binary_sensor.t1_{key}"
        return e

    entries = [_entry("low_hot_water"), _entry("is_heating"), _entry("holiday_mode")]
    monkeypatch.setattr(device_trigger.er, "async_get", lambda hass: MagicMock())
    monkeypatch.setattr(
        device_trigger.er, "async_entries_for_device", lambda reg, dev: entries
    )

    triggers = await device_trigger.async_get_triggers(MagicMock(), "dev1")
    types = {t["type"] for t in triggers}
    assert types == {
        "low_hot_water",
        "heating_started",
        "heating_stopped",
        "holiday_started",
        "holiday_ended",
    }
    # is_heating drives both started/stopped, pointing at the same entity
    heating = [t for t in triggers if "heating" in t["type"]]
    assert all(t["entity_id"] == "binary_sensor.t1_is_heating" for t in heating)
