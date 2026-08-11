"""Tests for Mixergy domain service handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mixergy_tank.api import MixergyApiError

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


def _make_call(data: dict | None = None) -> MagicMock:
    """Return a mock ServiceCall with a system context.

    user_id is None so _async_check_user_can_control treats it as a
    trusted/system call and skips per-target permission checks. data is a
    real dict so _resolve_target_entry_ids / serial_number lookups work.
    """
    call = MagicMock()
    call.data = data if data is not None else {}
    call.context.user_id = None
    return call


# ── boost_charge service ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boost_charge_calls_set_target_charge_100() -> None:
    """boost_charge service sets the target charge to 100 on each coordinator."""
    from custom_components.mixergy_tank import _register_services

    coordinator = _make_coordinator()
    coordinator.client.set_target_charge = AsyncMock()

    hass = _make_hass()

    # Patch _coordinator_by_entry so the service handler sees our mock coordinator
    # without needing isinstance() to pass against a real MixergyCoordinator.
    # The patch must remain active when the handler is invoked, so we keep the
    # context manager open across both _register_services() and the handler call.
    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": coordinator},
    ):
        _register_services(hass)

        # Extract the registered boost_charge handler
        boost_handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "boost_charge"
        )
        assert boost_handler is not None

        await boost_handler(_make_call())

    coordinator.client.set_target_charge.assert_awaited_once_with(100)
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_boost_charge_raises_homeassistant_error_on_api_failure() -> None:
    """boost_charge raises HomeAssistantError when the API call fails."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy_tank import _register_services

    coordinator = _make_coordinator()
    coordinator.client.set_target_charge = AsyncMock(
        side_effect=MixergyApiError("API unreachable")
    )

    hass = _make_hass()

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": coordinator},
    ):
        _register_services(hass)

        boost_handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "boost_charge"
        )

        with pytest.raises(HomeAssistantError):
            await boost_handler(_make_call())


# ── set_holiday_dates service ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_holiday_dates_raises_homeassistant_error_on_api_failure() -> None:
    """set_holiday_dates raises HomeAssistantError when the API call fails."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy_tank import _register_services

    coordinator = _make_coordinator()
    coordinator.client.set_holiday_dates = AsyncMock(
        side_effect=MixergyApiError("Schedule update failed")
    )

    hass = _make_hass()

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": coordinator},
    ):
        _register_services(hass)

        holiday_handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "set_holiday_dates"
        )

        start = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        end = datetime(2026, 3, 22, 12, 0, tzinfo=UTC)

        call_mock = _make_call({"start_date": start, "end_date": end})

        with pytest.raises(HomeAssistantError):
            await holiday_handler(call_mock)


# ── serial_number targeting ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boost_charge_targets_single_tank_by_serial() -> None:
    """With serial_number set, only the matching tank is acted on."""
    from custom_components.mixergy_tank import _register_services

    tank_a = _make_coordinator("AAA111")
    tank_a.client.set_target_charge = AsyncMock()
    tank_b = _make_coordinator("BBB222")
    tank_b.client.set_target_charge = AsyncMock()

    hass = _make_hass()

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"a": tank_a, "b": tank_b},
    ):
        _register_services(hass)
        boost_handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "boost_charge"
        )
        await boost_handler(_make_call({"serial_number": "bbb222"}))

    tank_b.client.set_target_charge.assert_awaited_once_with(100)
    tank_a.client.set_target_charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_boost_charge_unknown_serial_raises() -> None:
    """An unknown serial_number raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy_tank import _register_services

    tank_a = _make_coordinator("AAA111")
    tank_a.client.set_target_charge = AsyncMock()

    hass = _make_hass()

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"a": tank_a},
    ):
        _register_services(hass)
        boost_handler = next(
            call.args[2]
            for call in hass.services.async_register.call_args_list
            if call.args[1] == "boost_charge"
        )
        with pytest.raises(HomeAssistantError):
            await boost_handler(_make_call({"serial_number": "ZZZ999"}))

    tank_a.client.set_target_charge.assert_not_awaited()


# ── entity/device targeting + per-target authorization ────────────────────────


@pytest.mark.asyncio
async def test_target_resolves_device_to_coordinator() -> None:
    """An entity/device target resolves to the matching coordinator."""
    from custom_components.mixergy_tank import _target_coordinators

    coord = _make_coordinator("BBB222")
    hass = _make_hass()
    call = _make_call({})  # target keys supplied via _resolve patch below

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"entryB": coord},
    ), patch(
        "custom_components.mixergy_tank._resolve_target_entry_ids",
        return_value={"entryB"},
    ):
        targets = await _target_coordinators(hass, call)

    assert targets == [coord]


@pytest.mark.asyncio
async def test_target_unknown_reference_raises() -> None:
    """A target that resolves to no Mixergy entry raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.mixergy_tank import _target_coordinators

    hass = _make_hass()
    call = _make_call({})

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"entryA": _make_coordinator("AAA111")},
    ), patch(
        "custom_components.mixergy_tank._resolve_target_entry_ids",
        return_value={"some-other-entry"},
    ):
        with pytest.raises(HomeAssistantError):
            await _target_coordinators(hass, call)


@pytest.mark.asyncio
async def test_non_admin_without_permission_is_unauthorized() -> None:
    """A non-admin lacking control on the targeted tank is rejected."""
    from homeassistant.exceptions import Unauthorized

    from custom_components.mixergy_tank import _target_coordinators

    coord = _make_coordinator("AAA111")
    coord.config_entry.entry_id = "e1"
    hass = _make_hass()

    user = MagicMock()
    user.is_admin = False
    user.permissions.check_entity.return_value = False
    hass.auth.async_get_user = AsyncMock(return_value=user)

    call = _make_call({"serial_number": "AAA111"})
    call.context.user_id = "user-123"

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": coord},
    ), patch(
        "custom_components.mixergy_tank.er.async_entries_for_config_entry",
        return_value=[MagicMock(entity_id="number.tank_boost")],
    ):
        with pytest.raises(Unauthorized):
            await _target_coordinators(hass, call)


@pytest.mark.asyncio
async def test_non_admin_with_permission_allowed() -> None:
    """A non-admin holding control on the targeted tank is allowed."""
    from custom_components.mixergy_tank import _target_coordinators

    coord = _make_coordinator("AAA111")
    coord.config_entry.entry_id = "e1"
    hass = _make_hass()

    user = MagicMock()
    user.is_admin = False
    user.permissions.check_entity.return_value = True
    hass.auth.async_get_user = AsyncMock(return_value=user)

    call = _make_call({"serial_number": "AAA111"})
    call.context.user_id = "user-123"

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": coord},
    ), patch(
        "custom_components.mixergy_tank.er.async_entries_for_config_entry",
        return_value=[MagicMock(entity_id="number.tank_boost")],
    ):
        targets = await _target_coordinators(hass, call)

    assert targets == [coord]


@pytest.mark.asyncio
async def test_admin_bypasses_per_entity_check() -> None:
    """An admin is authorised without per-entity permission lookups."""
    from custom_components.mixergy_tank import _target_coordinators

    coord = _make_coordinator("AAA111")
    coord.config_entry.entry_id = "e1"
    hass = _make_hass()

    user = MagicMock()
    user.is_admin = True
    hass.auth.async_get_user = AsyncMock(return_value=user)

    call = _make_call({})
    call.context.user_id = "admin-1"

    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": coord},
    ):
        targets = await _target_coordinators(hass, call)

    assert targets == [coord]
    user.permissions.check_entity.assert_not_called()


@pytest.mark.asyncio
async def test_floor_label_target_rejected_by_schema() -> None:
    """floor_id/label_id targets must fail closed, not act on all tanks.

    The service schema only accepts entity_id/device_id/area_id (the targets
    we resolve), so a floor/label target raises vol.Invalid rather than
    silently broadening to every tank.
    """
    import voluptuous as vol

    from custom_components.mixergy_tank import _register_services

    hass = _make_hass()
    with patch(
        "custom_components.mixergy_tank._coordinator_by_entry",
        return_value={"e1": _make_coordinator()},
    ):
        _register_services(hass)

    schema = next(
        call.kwargs["schema"]
        for call in hass.services.async_register.call_args_list
        if call.args[1] == "boost_charge"
    )

    # entity/device/area accepted
    schema({"entity_id": ["number.tank_boost"]})
    schema({"device_id": "abc"})
    # floor/label rejected
    with pytest.raises(vol.Invalid):
        schema({"floor_id": "ground_floor"})
    with pytest.raises(vol.Invalid):
        schema({"label_id": "hot_water"})
