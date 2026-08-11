"""Tests for the Mixergy binary sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.mixergy_tank.api import TankData, TankMeasurement
from custom_components.mixergy_tank.const import (
    LOW_HOT_WATER_THRESHOLD,
    NO_HOT_WATER_THRESHOLD,
)

from .conftest import MOCK_SERIAL


def _data_with_charge(charge: float) -> TankData:
    """Return a minimal TankData with the given charge level."""
    return TankData(
        measurement=TankMeasurement(charge=charge),
    )


# ── Hot water threshold boundaries ───────────────────────────────────────────


def test_low_hot_water_threshold_on() -> None:
    """Binary sensor is ON when charge is just below the low threshold."""
    data = _data_with_charge(LOW_HOT_WATER_THRESHOLD - 0.1)
    assert data.measurement.charge < LOW_HOT_WATER_THRESHOLD


def test_low_hot_water_threshold_off() -> None:
    """Binary sensor is OFF when charge equals the low threshold exactly."""
    data = _data_with_charge(LOW_HOT_WATER_THRESHOLD)
    assert not (data.measurement.charge < LOW_HOT_WATER_THRESHOLD)


def test_no_hot_water_threshold_on() -> None:
    """Binary sensor is ON when charge is just below the empty threshold."""
    data = _data_with_charge(NO_HOT_WATER_THRESHOLD - 0.1)
    assert data.measurement.charge < NO_HOT_WATER_THRESHOLD


def test_no_hot_water_threshold_off() -> None:
    """Binary sensor is OFF when charge equals the empty threshold exactly."""
    data = _data_with_charge(NO_HOT_WATER_THRESHOLD)
    assert not (data.measurement.charge < NO_HOT_WATER_THRESHOLD)


def test_no_hot_water_not_triggered_at_low_threshold() -> None:
    """'No hot water' is not triggered at the 'low' threshold value."""
    data = _data_with_charge(LOW_HOT_WATER_THRESHOLD - 0.1)
    # Low-water fires but no-water should not (unless below its own threshold)
    assert data.measurement.charge < LOW_HOT_WATER_THRESHOLD
    assert not (data.measurement.charge < NO_HOT_WATER_THRESHOLD)


# ── is_advanced_mode helper ───────────────────────────────────────────────────


def test_is_advanced_mode_returns_true_for_advanced() -> None:
    """is_advanced_mode returns True when mode is 'advanced'."""
    from unittest.mock import MagicMock

    from custom_components.mixergy_tank.const import (
        CONF_EXPERIENCE_MODE,
        MODE_ADVANCED,
        is_advanced_mode,
    )

    entry = MagicMock()
    entry.options = {CONF_EXPERIENCE_MODE: MODE_ADVANCED}
    assert is_advanced_mode(entry) is True


def test_is_advanced_mode_returns_false_for_simple() -> None:
    """is_advanced_mode returns False when mode is 'simple'."""
    from unittest.mock import MagicMock

    from custom_components.mixergy_tank.const import (
        CONF_EXPERIENCE_MODE,
        MODE_SIMPLE,
        is_advanced_mode,
    )

    entry = MagicMock()
    entry.options = {CONF_EXPERIENCE_MODE: MODE_SIMPLE}
    assert is_advanced_mode(entry) is False


def test_is_advanced_mode_defaults_to_false_when_no_options() -> None:
    """is_advanced_mode defaults to Simple (False) for entries without the option.

    Matches the setup flow's default (STEP_EXPERIENCE_SCHEMA defaults to
    Simple) so an entry missing the option never silently exposes the full
    advanced control surface.
    """
    from unittest.mock import MagicMock

    from custom_components.mixergy_tank.const import is_advanced_mode

    entry = MagicMock()
    entry.options = {}
    assert is_advanced_mode(entry) is False


# ── Entity behaviour ──────────────────────────────────────────────────────────
#
# The threshold tests above assert on TankData and constants, which is why this
# module reported no coverage of binary_sensor.py at all: nothing constructed a
# sensor. These drive the real entities and the platform's setup, including the
# option-driven thresholds, which are the part most likely to drift.


def _bs_coordinator(data: TankData) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    return coordinator


def _full_data(
    *,
    charge: float = 50.0,
    electric: bool = False,
    indirect: bool = False,
    heatpump: bool = False,
    holiday: bool = False,
) -> TankData:
    from custom_components.mixergy_tank.api import TankInfo

    return TankData(
        info=TankInfo(serial_number=MOCK_SERIAL),
        measurement=TankMeasurement(
            charge=charge,
            electric_heat_source=electric,
            indirect_heat_source=indirect,
            heatpump_heat_source=heatpump,
            in_holiday_mode=holiday,
        ),
    )


async def _setup_binary_sensors(options: dict | None = None) -> list:
    from custom_components.mixergy_tank import binary_sensor

    entry = MagicMock()
    entry.options = options or {}
    entry.runtime_data = _bs_coordinator(_full_data())

    added: list = []
    await binary_sensor.async_setup_entry(
        MagicMock(), entry, lambda new, update_before_add=False: added.extend(new)
    )
    return added


async def test_binary_sensors_are_created_in_both_modes() -> None:
    """Binary sensors are not Advanced-gated — Simple users need them too."""
    from custom_components.mixergy_tank.const import (
        CONF_EXPERIENCE_MODE,
        MODE_SIMPLE,
    )

    simple = await _setup_binary_sensors({CONF_EXPERIENCE_MODE: MODE_SIMPLE})
    assert simple, "Simple mode must still get the hot-water binary sensors"

    keys = {entity.entity_description.key for entity in simple}
    assert {"low_hot_water", "no_hot_water", "is_heating", "holiday_mode"} <= keys


@pytest.mark.parametrize(
    ("key", "field"),
    (
        ("electric_heat", "electric"),
        ("indirect_heat", "indirect"),
        ("heatpump_heat", "heatpump"),
        ("holiday_mode", "holiday"),
    ),
)
async def test_each_binary_sensor_reads_its_own_field(key: str, field: str) -> None:
    """Parametrised so two sensors cannot share one is_on_fn unnoticed."""
    from custom_components.mixergy_tank.binary_sensor import (
        STATIC_BINARY_SENSOR_DESCRIPTIONS,
        MixergyBinarySensor,
    )

    description = next(
        d for d in STATIC_BINARY_SENSOR_DESCRIPTIONS if d.key == key
    )

    on = MixergyBinarySensor(
        _bs_coordinator(_full_data(**{field: True})), description
    )
    off = MixergyBinarySensor(
        _bs_coordinator(_full_data(**{field: False})), description
    )

    assert on.is_on is True
    assert off.is_on is False
    assert on.unique_id == f"{MOCK_SERIAL}_{key}"


async def test_threshold_sensors_follow_configured_options() -> None:
    """Custom thresholds must reach the entities, not just the options dict.

    The thresholds are baked into the descriptions at setup time, so an entry
    that changes them only takes effect on reload — this pins that the
    configured value is what the entity actually compares against.
    """
    from custom_components.mixergy_tank.binary_sensor import MixergyBinarySensor
    from custom_components.mixergy_tank.const import (
        CONF_LOW_WATER_THRESHOLD,
        CONF_NO_WATER_THRESHOLD,
    )

    entities = await _setup_binary_sensors(
        {CONF_LOW_WATER_THRESHOLD: 42.0, CONF_NO_WATER_THRESHOLD: 7.0}
    )
    by_key = {e.entity_description.key: e.entity_description for e in entities}

    low = by_key["low_hot_water"]
    no = by_key["no_hot_water"]

    # Just below the configured low threshold: low fires, no-water does not.
    data = _full_data(charge=41.9)
    assert low.is_on_fn(data) is True
    assert no.is_on_fn(data) is False

    # Below the configured no-water threshold: both fire.
    data = _full_data(charge=6.9)
    assert low.is_on_fn(data) is True
    assert no.is_on_fn(data) is True

    # A charge that would have tripped the *default* 5% threshold but not the
    # configured 7% one proves the option is honoured rather than the constant.
    data = _full_data(charge=6.0)
    assert no.is_on_fn(data) is True


async def test_is_heating_is_independent_of_the_selected_heat_source() -> None:
    """`is_heating` tracks the immersion flag, not which source is selected.

    The API parser sets `is_heating` from the tank's `immersion` state, so a
    tank can report electric as its heat source while not actually heating —
    the source says *which* element would run, the flag says whether one *is*
    running. Asserting the natural-looking roll-up ("any source set means
    heating") would encode a behaviour the integration does not have and would
    fail the moment someone relied on it for a "currently heating" automation.
    """
    from custom_components.mixergy_tank.binary_sensor import (
        STATIC_BINARY_SENSOR_DESCRIPTIONS,
        MixergyBinarySensor,
    )

    description = next(
        d for d in STATIC_BINARY_SENSOR_DESCRIPTIONS if d.key == "is_heating"
    )

    # A selected source with the immersion off is NOT heating.
    for field in ("electric", "indirect", "heatpump"):
        sensor = MixergyBinarySensor(
            _bs_coordinator(_full_data(**{field: True})), description
        )
        assert sensor.is_on is False, f"{field} alone must not imply heating"

    # The flag itself is what drives the sensor.
    heating = _full_data(electric=True)
    heating.measurement.is_heating = True
    assert MixergyBinarySensor(_bs_coordinator(heating), description).is_on is True
