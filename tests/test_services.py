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


def _make_hass() -> MagicMock:
    """Return a minimal mock HomeAssistant."""
    hass = MagicMock()
    hass.services.has_service.return_value = False
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    return hass


# ── boost_charge service ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boost_charge_calls_set_target_charge_100() -> None:
    """boost_charge service sets the target charge to 100 on each coordinator."""
    from custom_components.mixergy import _register_services

    coordinator = _make_coordinator()
    coordinator.client.set_target_charge = AsyncMock()

    hass = _make_hass()

    # Patch _get_coordinators so the service handler sees our mock coordinator
    # without needing isinstance() to pass against a real MixergyCoordinator.
    # The patch must remain active when the handler is invoked, so we keep the
    # context manager open across both _register_services() and the handler call.
    with patch(
        "custom_components.mixergy._get_coordinators",
        return_value=[coordinator],
    ):
        _register_services(hass)

        # Extract the registered boost_charge handler
        boost_handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "boost_charge"
        )
        assert boost_handler is not None

        await boost_handler(MagicMock())

    coordinator.client.set_target_charge.assert_awaited_once_with(100)
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_boost_charge_raises_homeassistant_error_on_api_failure() -> None:
    """boost_charge raises HomeAssistantError when the API call fails."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy import _register_services

    coordinator = _make_coordinator()
    coordinator.client.set_target_charge = AsyncMock(
        side_effect=MixergyApiError("API unreachable")
    )

    hass = _make_hass()

    with patch(
        "custom_components.mixergy._get_coordinators",
        return_value=[coordinator],
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

    coordinator = _make_coordinator()
    coordinator.client.set_holiday_dates = AsyncMock(
        side_effect=MixergyApiError("Schedule update failed")
    )

    hass = _make_hass()

    with patch(
        "custom_components.mixergy._get_coordinators",
        return_value=[coordinator],
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
