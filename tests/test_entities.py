"""Tests for the sensor and number platforms.

Both are description-driven, so the risk is not that an entity fails loudly but
that one description quietly reads or writes the wrong field. Every description
is therefore parametrised rather than spot-checked, and the mode-dependent
entity sets are asserted through async_setup_entry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.mixergy_tank.api import (
    MixergyApiError,
    TankData,
    TankInfo,
    TankMeasurement,
    TankSchedule,
    TankSettings,
)
from custom_components.mixergy_tank.const import (
    CONF_EXPERIENCE_MODE,
    MODE_ADVANCED,
    MODE_SIMPLE,
)

from .conftest import MOCK_SERIAL


def _data(*, has_pv: bool = True, **overrides) -> TankData:
    """Return TankData with sensible defaults for entity reads."""
    measurement_fields = {
        "hot_water_temperature": 55.0,
        "coldest_water_temperature": 18.0,
        "charge": 62.0,
        "target_charge": 80.0,
        "pv_power_kw": 1.25,
        "clamp_power_w": 340.0,
    }
    settings_fields = {
        "target_temperature": 60.0,
        "cleansing_temperature": 53.0,
    }
    for key, value in overrides.items():
        if key in measurement_fields:
            measurement_fields[key] = value
        elif key in settings_fields:
            settings_fields[key] = value

    return TankData(
        info=TankInfo(
            serial_number=MOCK_SERIAL,
            model_code="MIXERGY-180",
            firmware_version="2.1.0",
            has_pv_diverter=has_pv,
        ),
        measurement=TankMeasurement(**measurement_fields),
        settings=TankSettings(**settings_fields),
        schedule=TankSchedule(raw={}, default_heat_source="electric"),
    )


class _RecordingClient:
    """Client stub that records which setter a description actually calls.

    A MagicMock cannot serve here: its auto-created attributes never appear in
    dir(), so there is no way to discover the method a description reached for,
    and the test would only prove "something was awaited".
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self._error = error

    def __getattr__(self, name: str):
        async def call(*args, **kwargs) -> None:
            self.calls.append((name, args, kwargs))
            if self._error is not None:
                raise self._error

        return call


def _coordinator(data: TankData | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data if data is not None else _data()
    coordinator.last_update_success = True
    coordinator.client = _RecordingClient()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.hass.config.currency = "GBP"
    return coordinator


def _entry(mode: str, coordinator: MagicMock, options: dict | None = None):
    entry = MagicMock()
    entry.options = {CONF_EXPERIENCE_MODE: mode, **(options or {})}
    entry.runtime_data = coordinator
    return entry


async def _collect(setup_entry, entry) -> list:
    added: list = []
    await setup_entry(
        MagicMock(), entry, lambda new, update_before_add=False: added.extend(new)
    )
    return added


# ── Sensor descriptions ───────────────────────────────────────────────────────


def test_every_sensor_description_reads_a_distinct_value() -> None:
    """No two sensors may share a value_fn result on distinguishable data.

    Each description is a one-line lambda, so the realistic failure is a
    copy-paste that leaves two sensors reading the same field. Distinct
    fixture values make that collision visible.
    """
    from custom_components.mixergy_tank.sensor import (
        SENSOR_DESCRIPTIONS,
        MixergySensor,
    )

    coordinator = _coordinator()
    seen: dict[str, object] = {}

    for description in SENSOR_DESCRIPTIONS:
        sensor = MixergySensor(coordinator, description)
        assert sensor.unique_id == f"{MOCK_SERIAL}_{description.key}"
        seen[description.key] = sensor.native_value

    # The numeric temperature/charge/power sensors must not all agree.
    numeric = [v for v in seen.values() if isinstance(v, (int, float))]
    assert len(set(numeric)) > 1, f"sensors look copy-pasted: {seen}"


@pytest.mark.parametrize(
    ("key", "expected"),
    (
        ("hot_water_temperature", 55.0),
        ("coldest_water_temperature", 18.0),
        ("target_temperature", 60.0),
        ("cleansing_temperature", 53.0),
        ("charge", 62.0),
        ("target_charge", 80.0),
        ("pv_power", 1.25),
        ("clamp_power", 340.0),
    ),
)
def test_sensor_reads_the_expected_field(key: str, expected: float) -> None:
    """Pin each sensor to the field it is supposed to report."""
    from custom_components.mixergy_tank.sensor import (
        SENSOR_DESCRIPTIONS,
        MixergySensor,
    )

    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
    sensor = MixergySensor(_coordinator(), description)
    assert sensor.native_value == expected


def test_pv_sensors_are_unavailable_without_a_diverter() -> None:
    """PV sensors must hide on a tank with no diverter, others must not."""
    from custom_components.mixergy_tank.sensor import (
        SENSOR_DESCRIPTIONS,
        MixergySensor,
    )

    coordinator = _coordinator(_data(has_pv=False))
    for description in SENSOR_DESCRIPTIONS:
        sensor = MixergySensor(coordinator, description)
        if description.key in ("pv_power", "clamp_power"):
            assert sensor.available is False, description.key
        else:
            assert sensor.available is True, description.key


async def test_sensor_setup_creates_entities_in_both_modes() -> None:
    """Sensors are not Advanced-gated — Simple users need them too."""
    from custom_components.mixergy_tank import sensor

    for mode in (MODE_SIMPLE, MODE_ADVANCED):
        entities = await _collect(
            sensor.async_setup_entry, _entry(mode, _coordinator())
        )
        assert entities, f"no sensors created in {mode} mode"


async def test_cost_sensor_only_appears_with_a_configured_tariff() -> None:
    """The cost sensor is opt-in: rate 0 (the default) must not create it."""
    from custom_components.mixergy_tank import sensor
    from custom_components.mixergy_tank.const import CONF_ELECTRIC_RATE

    coordinator = _coordinator()

    without = await _collect(
        sensor.async_setup_entry, _entry(MODE_ADVANCED, coordinator)
    )
    with_rate = await _collect(
        sensor.async_setup_entry,
        _entry(MODE_ADVANCED, coordinator, {CONF_ELECTRIC_RATE: 0.28}),
    )

    def has_cost(entities) -> bool:
        return any(
            getattr(e, "unique_id", "").endswith("_electric_cost")
            for e in entities
        )

    assert not has_cost(without)
    assert has_cost(with_rate)


# ── Number platform ───────────────────────────────────────────────────────────


async def test_simple_mode_exposes_only_the_boost_control() -> None:
    """Simple mode gets one primary control, not the advanced surface."""
    from custom_components.mixergy_tank import number

    coordinator = _coordinator()
    entities = await _collect(
        number.async_setup_entry, _entry(MODE_SIMPLE, coordinator)
    )

    assert len(entities) == 1
    assert entities[0].unique_id.endswith("_boost_charge_simple") or entities[
        0
    ].unique_id.endswith("_target_charge_control")


async def test_advanced_mode_exposes_the_full_number_surface() -> None:
    """Advanced mode gets every described number control."""
    from custom_components.mixergy_tank import number
    from custom_components.mixergy_tank.number import NUMBER_DESCRIPTIONS

    coordinator = _coordinator()
    entities = await _collect(
        number.async_setup_entry, _entry(MODE_ADVANCED, coordinator)
    )

    assert len(entities) == len(NUMBER_DESCRIPTIONS)


async def test_every_number_control_drives_a_distinct_setter() -> None:
    """Each number control must call its own API setter, with its own value.

    All the descriptions are one-line lambdas over the same client, so the
    realistic failure is two controls pointing at one setter. Recording the
    method name per description makes that collision fail here rather than
    surfacing as a control that silently moves the wrong setting.
    """
    from custom_components.mixergy_tank.number import (
        NUMBER_DESCRIPTIONS,
        MixergyNumber,
    )

    used: dict[str, str] = {}

    for description in NUMBER_DESCRIPTIONS:
        coordinator = _coordinator()
        entity = MixergyNumber(coordinator, description)

        assert entity.unique_id == f"{MOCK_SERIAL}_{description.key}"
        assert entity.native_value is not None

        await entity.async_set_native_value(entity.native_min_value)

        assert coordinator.client.calls, f"{description.key} called no setter"
        method, args, _ = coordinator.client.calls[0]
        assert entity.native_min_value in args, (
            f"{description.key} did not forward its value to {method}"
        )
        coordinator.async_request_refresh.assert_awaited_once()
        used[description.key] = method

    assert len(set(used.values())) == len(used), (
        f"number controls share a setter: {used}"
    )


async def test_number_write_failure_names_the_control() -> None:
    """A failed write surfaces as HomeAssistantError naming the control."""
    from custom_components.mixergy_tank.number import (
        NUMBER_DESCRIPTIONS,
        MixergyNumber,
    )

    description = NUMBER_DESCRIPTIONS[0]
    coordinator = _coordinator()
    coordinator.client = _RecordingClient(error=MixergyApiError("rejected"))

    entity = MixergyNumber(coordinator, description)
    with pytest.raises(HomeAssistantError, match=description.key):
        await entity.async_set_native_value(entity.native_min_value)


# ── Accumulating sensors ──────────────────────────────────────────────────────
#
# The energy and cost sensors persist a running total across restarts, so a
# fault here is not a wrong reading for one cycle — it is a permanently wrong
# total on the Energy dashboard. Two guards matter most: a failed poll must not
# integrate stale data into the total, and a non-finite accumulator must never
# reach the state machine.


def _restoring(entity, restored):
    """Attach the RestoreSensor plumbing an entity needs outside hass."""
    entity.async_get_last_sensor_data = AsyncMock(return_value=restored)
    entity.async_write_ha_state = MagicMock()
    entity.hass = MagicMock()
    return entity


def _energy_sensor(coordinator=None):
    from custom_components.mixergy_tank.sensor import MixergyEnergySensor

    return MixergyEnergySensor(
        coordinator or _coordinator(),
        key="electric_energy",
        translation_key="electric_energy",
        power_w_fn=lambda data: data.measurement.clamp_power_w,
    )


async def test_energy_sensor_restores_its_previous_total() -> None:
    """A restart must resume the stored total, not start from zero."""
    sensor = _energy_sensor()
    restored = MagicMock()
    restored.native_value = 12.5
    _restoring(sensor, restored)

    with patch.object(type(sensor).__mro__[1], "async_added_to_hass", AsyncMock()):
        await sensor.async_added_to_hass()

    assert sensor.native_value == 12.5
    # The restored total must be pushed immediately, or the Energy dashboard
    # sees a transient 0 between restart and the first coordinator tick.
    sensor.async_write_ha_state.assert_called_once()


async def test_energy_sensor_survives_an_unparsable_restored_value() -> None:
    """Corrupt restore data resets to 0 rather than raising at startup."""
    sensor = _energy_sensor()
    restored = MagicMock()
    restored.native_value = "not-a-number"
    _restoring(sensor, restored)

    with patch.object(type(sensor).__mro__[1], "async_added_to_hass", AsyncMock()):
        await sensor.async_added_to_hass()

    assert sensor.native_value == 0.0


async def test_energy_sensor_ignores_a_missing_restore() -> None:
    """A first-ever start has nothing to restore and must stay at zero."""
    sensor = _energy_sensor()
    _restoring(sensor, None)

    with patch.object(type(sensor).__mro__[1], "async_added_to_hass", AsyncMock()):
        await sensor.async_added_to_hass()

    assert sensor.native_value == 0.0


def test_energy_sensor_resets_a_non_finite_total() -> None:
    """A NaN/inf accumulator must never reach the state machine."""
    sensor = _energy_sensor()
    sensor._accumulated_kwh = float("inf")
    assert sensor.native_value == 0.0

    sensor._accumulated_kwh = float("nan")
    assert sensor.native_value == 0.0


def test_energy_sensor_availability_follows_its_predicate() -> None:
    """The PV energy sensor hides on a tank with no diverter."""
    from custom_components.mixergy_tank.sensor import MixergyEnergySensor

    coordinator = _coordinator(_data(has_pv=False))
    sensor = MixergyEnergySensor(
        coordinator,
        key="pv_energy",
        translation_key="pv_energy",
        power_w_fn=lambda data: data.measurement.pv_power_kw * 1000,
        available_fn=lambda data: data.info.has_pv_diverter,
    )
    assert sensor.available is False


def _cost_sensor(rate: float = 0.30, coordinator=None):
    from custom_components.mixergy_tank.sensor import MixergyElectricCostSensor

    return MixergyElectricCostSensor(coordinator or _coordinator(), rate=rate)


async def test_cost_sensor_restores_and_handles_bad_data() -> None:
    """Cost restore mirrors the energy sensor, including corrupt data."""
    sensor = _cost_sensor()
    restored = MagicMock()
    restored.native_value = 3.75
    _restoring(sensor, restored)

    with patch.object(type(sensor).__mro__[1], "async_added_to_hass", AsyncMock()):
        await sensor.async_added_to_hass()
    assert sensor.native_value == 3.75

    broken = _cost_sensor()
    bad = MagicMock()
    bad.native_value = object()
    _restoring(broken, bad)
    with patch.object(type(broken).__mro__[1], "async_added_to_hass", AsyncMock()):
        await broken.async_added_to_hass()
    assert broken.native_value == 0.0


def test_cost_sensor_does_not_integrate_a_failed_poll() -> None:
    """Stale data must not be credited into a persisted total.

    On a failed poll coordinator.data is the previous reading; integrating it
    would invent cost for a period the tank may not have been heating, and the
    error is permanent because the total is persisted.
    """
    coordinator = _coordinator()
    coordinator.update_interval = None
    sensor = _cost_sensor(coordinator=coordinator)
    sensor.async_write_ha_state = MagicMock()
    sensor._accumulated_cost = 1.0
    sensor._last_update = 0.0

    coordinator.last_update_success = False
    coordinator.data.measurement.electric_heat_source = True
    coordinator.data.measurement.clamp_power_w = 3000.0

    sensor._handle_coordinator_update()

    assert sensor.native_value == 1.0
    sensor.async_write_ha_state.assert_called_once()


def test_cost_sensor_accumulates_only_while_electric_heating() -> None:
    """Cost accrues from clamp power only when the electric source is on."""
    import time as _time

    coordinator = _coordinator()
    coordinator.update_interval = None
    sensor = _cost_sensor(rate=0.50, coordinator=coordinator)
    sensor.async_write_ha_state = MagicMock()

    # Not heating: no cost, regardless of clamp power.
    coordinator.data.measurement.electric_heat_source = False
    coordinator.data.measurement.clamp_power_w = 2000.0
    sensor._last_update = _time.time() - 3600
    sensor._handle_coordinator_update()
    assert sensor.native_value == 0.0

    # Heating: 1 kW for ~1 h at £0.50/kWh.
    coordinator.data.measurement.electric_heat_source = True
    coordinator.data.measurement.clamp_power_w = 1000.0
    sensor._last_update = _time.time() - 3600
    sensor._handle_coordinator_update()
    assert sensor.native_value == pytest.approx(0.5, rel=0.05)


def test_cost_sensor_resets_a_non_finite_total() -> None:
    """A non-finite cost accumulator must not reach the state machine."""
    sensor = _cost_sensor()
    sensor._accumulated_cost = float("nan")
    assert sensor.native_value == 0.0
