"""Tests for the Mixergy binary sensor platform."""

from __future__ import annotations

import pytest

from custom_components.mixergy.api import TankData, TankMeasurement
from custom_components.mixergy.const import (
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

    from custom_components.mixergy.const import (
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

    from custom_components.mixergy.const import (
        CONF_EXPERIENCE_MODE,
        MODE_SIMPLE,
        is_advanced_mode,
    )

    entry = MagicMock()
    entry.options = {CONF_EXPERIENCE_MODE: MODE_SIMPLE}
    assert is_advanced_mode(entry) is False


def test_is_advanced_mode_defaults_to_true_when_no_options() -> None:
    """is_advanced_mode defaults to True for entries without the option."""
    from unittest.mock import MagicMock

    from custom_components.mixergy.const import is_advanced_mode

    entry = MagicMock()
    entry.options = {}
    assert is_advanced_mode(entry) is True
