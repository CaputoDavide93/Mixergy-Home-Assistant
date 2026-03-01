"""Tests for Mixergy domain service handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mixergy.api import MixergyApiError

from .conftest import MOCK_SERIAL


def _make_coordinator(serial: str = MOCK_SERIAL) -> MagicMock:
    """Return a minimal mock coordinator."""
    coordinator = MagicMock()
    coordinator.client = MagicMock()
    coordinator.client.tank_info = MagicMock()
    coordinator.client.tank_info.serial_number = serial
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _make_hass(coordinators: list[MagicMock] | None = None) -> MagicMock:
    """Return a minimal mock HomeAssistant with optional coordinator entries."""
    hass = MagicMock()
    if coordinators is not None:
        entries = []
        for coord in coordinators:
            entry = MagicMock()
            entry.runtime_data = coord
            entries.append(entry)
        hass.config_entries.async_entries.return_value = entries
        hass.config_entries.async_loaded_entries.return_value = entries
    hass.services.has_service.return_value = False
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    return hass


# ── boost_charge service ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boost_charge_calls_set_target_charge_100() -> None:
    """boost_charge service sets the target charge to 100 on each coordinator."""
    from custom_components.mixergy import _register_services
    from custom_components.mixergy.coordinator import MixergyCoordinator

    coordinator = _make_coordinator()
    coordinator.client.set_target_charge = AsyncMock()

    hass = _make_hass([coordinator])
    # Only coordinators that are actual MixergyCoordinator instances are used;
    # patch isinstance to return True for our mock.
    with patch(
        "custom_components.mixergy.isinstance",
        side_effect=lambda obj, cls: True,
    ):
        _register_services(hass)

    # Extract the registered handler
    boost_call = hass.services.async_register.call_args_list
    # Find the boost_charge registration
    boost_handler = next(
        (call.args[2] for call in boost_call if call.args[1] == "boost_charge"),
        None,
    )
    assert boost_handler is not None

    call_mock = MagicMock()
    await boost_handler(call_mock)

    coordinator.client.set_target_charge.assert_awaited_once_with(100)
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_boost_charge_raises_homeassistant_error_on_api_failure() -> None:
    """boost_charge raises HomeAssistantError when the API call fails."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy import _register_services
    from custom_components.mixergy.coordinator import MixergyCoordinator

    coordinator = _make_coordinator()
    coordinator.client.set_target_charge = AsyncMock(
        side_effect=MixergyApiError("API unreachable")
    )

    hass = _make_hass([coordinator])
    with patch(
        "custom_components.mixergy.isinstance",
        side_effect=lambda obj, cls: True,
    ):
        _register_services(hass)

    boost_handler = next(
        call.args[2]
        for call in hass.services.async_register.call_args_list
        if call.args[1] == "boost_charge"
    )

    with pytest.raises(HomeAssistantError):
        await boost_handler(MagicMock())


# ── set_holiday_dates service ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_holiday_dates_raises_homeassistant_error_on_api_failure() -> None:
    """set_holiday_dates raises HomeAssistantError when the API call fails."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy import _register_services
    from custom_components.mixergy.coordinator import MixergyCoordinator

    coordinator = _make_coordinator()
    coordinator.client.set_holiday_dates = AsyncMock(
        side_effect=MixergyApiError("Schedule update failed")
    )

    hass = _make_hass([coordinator])
    with patch(
        "custom_components.mixergy.isinstance",
        side_effect=lambda obj, cls: True,
    ):
        _register_services(hass)

    holiday_handler = next(
        call.args[2]
        for call in hass.services.async_register.call_args_list
        if call.args[1] == "set_holiday_dates"
    )

    start = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

    call_mock = MagicMock()
    call_mock.data = {"start_date": start, "end_date": end}

    with pytest.raises(HomeAssistantError):
        await holiday_handler(call_mock)
