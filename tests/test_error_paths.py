"""Tests for coordinator failure classification and remaining entity branches.

The coordinator's except-ladder decides how a cloud problem is shown to the
user: a transient outage should retry quietly, whereas a tank that has left the
account should raise a repair issue with an actionable fix. Getting that
mapping wrong either spams tracebacks on every poll or hides a permanent fault
behind a retry loop, so each branch is pinned separately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.mixergy_tank.api import (
    MixergyApiError,
    MixergyAuthError,
    MixergyConnectionError,
    MixergyTankNotFoundError,
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

_MODULE = "custom_components.mixergy_tank.coordinator"


def _coordinator_under_test(fetch_error: Exception | None = None):
    """Build a real MixergyCoordinator with a stubbed client and hass."""
    from custom_components.mixergy_tank.coordinator import MixergyCoordinator

    client = MagicMock()
    client.fetch_all = AsyncMock(side_effect=fetch_error)
    client.tank_info = MagicMock()
    client.tank_info.serial_number = MOCK_SERIAL

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {}

    hass = MagicMock()
    with patch(f"{_MODULE}.DataUpdateCoordinator.__init__", return_value=None):
        coordinator = MixergyCoordinator(hass, client, entry)
    coordinator.hass = hass
    coordinator.client = client
    coordinator.config_entry = entry
    return coordinator


async def test_tank_not_found_raises_config_entry_error_with_repair_issue() -> None:
    """A tank missing from the account is permanent — surface it as such.

    UpdateFailed would retry forever against an account that no longer has the
    tank, so this must escalate to ConfigEntryError *and* raise a repair issue
    pointing at reconfigure.
    """
    coordinator = _coordinator_under_test(MixergyTankNotFoundError("gone"))

    with patch(f"{_MODULE}.ir") as issue_registry:
        with pytest.raises(ConfigEntryError, match="tank not found"):
            await coordinator._async_update_data()

    issue_registry.async_create_issue.assert_called_once()
    _, kwargs = issue_registry.async_create_issue.call_args
    assert kwargs["translation_key"] == "tank_not_found"
    assert kwargs["translation_placeholders"]["serial"] == MOCK_SERIAL


async def test_connection_error_is_retryable() -> None:
    """A transient outage must stay UpdateFailed so polling resumes."""
    coordinator = _coordinator_under_test(MixergyConnectionError("timeout"))

    with pytest.raises(UpdateFailed, match="communicating"):
        await coordinator._async_update_data()


async def test_unclassified_api_error_is_retryable_not_fatal() -> None:
    """An unexpected API error must not abort the coordinator outright."""
    coordinator = _coordinator_under_test(MixergyApiError("weird"))

    with pytest.raises(UpdateFailed, match="API error"):
        await coordinator._async_update_data()


# ── water_heater ──────────────────────────────────────────────────────────────


def _wh_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = TankData(
        info=TankInfo(serial_number=MOCK_SERIAL),
        measurement=TankMeasurement(hot_water_temperature=55.0),
        settings=TankSettings(target_temperature=60.0),
        schedule=TankSchedule(raw={}, default_heat_source="electric"),
    )
    coordinator.last_update_success = True
    client = MagicMock()
    client.set_target_temperature = AsyncMock()
    client.set_default_heat_source = AsyncMock()
    client.set_target_charge = AsyncMock()
    client.set_holiday_dates = AsyncMock()
    coordinator.client = client
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry = MagicMock()
    return coordinator


async def test_water_heater_is_advanced_mode_only() -> None:
    """Simple mode must not get a water-heater entity."""
    from custom_components.mixergy_tank import water_heater

    for mode, expected in ((MODE_SIMPLE, 0), (MODE_ADVANCED, 1)):
        entry = MagicMock()
        entry.options = {CONF_EXPERIENCE_MODE: mode}
        entry.runtime_data = _wh_coordinator()
        added: list = []
        await water_heater.async_setup_entry(
            MagicMock(), entry, lambda new, update_before_add=False: added.extend(new)
        )
        assert len(added) == expected


async def test_water_heater_ignores_a_temperature_call_without_a_temperature() -> None:
    """No ATTR_TEMPERATURE means nothing to write — must not call the API.

    HA can deliver a set_temperature call carrying only operation mode; writing
    None here would raise inside the client instead of being a no-op.
    """
    from custom_components.mixergy_tank.water_heater import MixergyWaterHeater

    coordinator = _wh_coordinator()
    await MixergyWaterHeater(coordinator).async_set_temperature()

    coordinator.client.set_target_temperature.assert_not_awaited()


async def test_water_heater_ignores_an_unknown_operation_mode() -> None:
    """An unmapped mode is a no-op rather than a write of None."""
    from custom_components.mixergy_tank.water_heater import MixergyWaterHeater

    coordinator = _wh_coordinator()
    await MixergyWaterHeater(coordinator).async_set_operation_mode("nonsense")

    coordinator.client.set_default_heat_source.assert_not_awaited()


async def test_water_heater_writes_a_known_operation_mode() -> None:
    """A mapped mode reaches the API."""
    from custom_components.mixergy_tank.water_heater import (
        _OP_TO_HEAT_SOURCE,
        MixergyWaterHeater,
    )

    mode, expected = next(iter(_OP_TO_HEAT_SOURCE.items()))
    coordinator = _wh_coordinator()

    await MixergyWaterHeater(coordinator).async_set_operation_mode(mode)

    coordinator.client.set_default_heat_source.assert_awaited_once_with(expected)


async def test_water_heater_sets_temperature() -> None:
    """A temperature call forwards an int to the API."""
    from homeassistant.components.water_heater import ATTR_TEMPERATURE

    from custom_components.mixergy_tank.water_heater import MixergyWaterHeater

    coordinator = _wh_coordinator()
    await MixergyWaterHeater(coordinator).async_set_temperature(
        **{ATTR_TEMPERATURE: 58.6}
    )

    coordinator.client.set_target_temperature.assert_awaited_once_with(58)


# ── datetime ──────────────────────────────────────────────────────────────────


async def test_datetime_entities_are_advanced_mode_only() -> None:
    """Holiday datetime pickers belong to the advanced surface.

    The platform module must be reached via importlib: the package's
    __init__ does ``from datetime import datetime``, so the stdlib class
    shadows the same-named submodule on a plain ``from … import datetime``.
    """
    import importlib

    dt_platform = importlib.import_module(
        "custom_components.mixergy_tank.datetime"
    )

    for mode, expected_any in ((MODE_SIMPLE, False), (MODE_ADVANCED, True)):
        entry = MagicMock()
        entry.options = {CONF_EXPERIENCE_MODE: mode}
        entry.runtime_data = _wh_coordinator()
        added: list = []
        await dt_platform.async_setup_entry(
            MagicMock(), entry, lambda new, update_before_add=False: added.extend(new)
        )
        assert bool(added) is expected_any


# ── device triggers ───────────────────────────────────────────────────────────
#
# Device triggers are the documented automation entry point, so a wrong mapping
# silently attaches an automation to the wrong state change — it still "works",
# it just fires on the wrong event.


async def test_device_triggers_skip_non_binary_sensor_entities() -> None:
    """Only binary sensors back a trigger; other entities must be ignored."""
    from custom_components.mixergy_tank import device_trigger

    unrelated = MagicMock()
    unrelated.domain = "sensor"
    unrelated.unique_id = f"{MOCK_SERIAL}_charge"
    no_uid = MagicMock()
    no_uid.domain = "binary_sensor"
    no_uid.unique_id = None

    with patch(
        "custom_components.mixergy_tank.device_trigger.er"
    ) as er_mod:
        er_mod.async_entries_for_device.return_value = [unrelated, no_uid]
        er_mod.async_get.return_value = MagicMock()
        triggers = await device_trigger.async_get_triggers(
            MagicMock(), "device-1"
        )

    assert triggers == []


async def test_device_trigger_maps_each_type_to_its_entity_and_state() -> None:
    """Every trigger type must resolve to its own binary sensor and state."""
    from custom_components.mixergy_tank import device_trigger
    from custom_components.mixergy_tank.device_trigger import _TRIGGER_MAP

    entries = []
    for key, _state in _TRIGGER_MAP.values():
        entry = MagicMock()
        entry.domain = "binary_sensor"
        entry.unique_id = f"{MOCK_SERIAL}_{key}"
        entry.entity_id = f"binary_sensor.mixergy_{key}"
        entries.append(entry)

    with patch(
        "custom_components.mixergy_tank.device_trigger.er"
    ) as er_mod:
        er_mod.async_entries_for_device.return_value = entries
        er_mod.async_get.return_value = MagicMock()
        triggers = await device_trigger.async_get_triggers(
            MagicMock(), "device-1"
        )

    assert len(triggers) == len(_TRIGGER_MAP)
    for trigger in triggers:
        key, _state = _TRIGGER_MAP[trigger["type"]]
        assert trigger["entity_id"].endswith(key)


async def test_device_trigger_attaches_via_the_core_state_trigger() -> None:
    """Attachment delegates to HA's state trigger with the mapped to-state.

    Delegating rather than reimplementing is deliberate; this pins that the
    mapped state actually reaches the core trigger config.
    """
    from custom_components.mixergy_tank import device_trigger
    from custom_components.mixergy_tank.device_trigger import _TRIGGER_MAP

    trigger_type = next(iter(_TRIGGER_MAP))
    _key, to_state = _TRIGGER_MAP[trigger_type]
    config = {
        "type": trigger_type,
        "entity_id": "binary_sensor.mixergy_low_hot_water",
    }
    captured: dict = {}

    async def validate(hass, state_config):
        captured.update(state_config)
        return state_config

    with patch(
        "custom_components.mixergy_tank.device_trigger.state_trigger"
    ) as st:
        st.async_validate_trigger_config = AsyncMock(side_effect=validate)
        st.async_attach_trigger = AsyncMock(return_value="unsub")
        st.CONF_TO = "to"

        result = await device_trigger.async_attach_trigger(
            MagicMock(), config, MagicMock(), MagicMock()
        )

    assert result == "unsub"
    assert captured["to"] == to_state
    assert captured["entity_id"] == config["entity_id"]


# ── Remaining entity and service branches ─────────────────────────────────────


async def test_boost_number_shares_the_target_charge_unique_id() -> None:
    """Simple and Advanced must reuse one unique_id for the same control.

    The boost slider (Simple) and target-charge control (Advanced) are the same
    underlying setting. Sharing the unique_id is what lets a user switch modes
    without the entity being recreated and losing its id, customisations and
    history — so this is a compatibility contract, not an implementation detail.
    """
    from custom_components.mixergy_tank.number import MixergyBoostNumber

    coordinator = _wh_coordinator()
    coordinator.data.measurement.target_charge = 45.0
    boost = MixergyBoostNumber(coordinator)

    assert boost.unique_id == f"{MOCK_SERIAL}_target_charge_control"
    assert boost.native_value == 45.0

    await boost.async_set_native_value(70.9)
    coordinator.client.set_target_charge.assert_awaited_once_with(70)


async def test_holiday_datetime_derives_the_missing_end_of_the_window() -> None:
    """Setting only one end of a holiday must not send a half-window.

    The API needs both bounds, so setting the start with no stored end derives
    a default span, and setting the end with no stored start anchors to now.
    """
    import importlib

    dt_platform = importlib.import_module(
        "custom_components.mixergy_tank.datetime"
    )
    from custom_components.mixergy_tank.api import TankSchedule

    coordinator = _wh_coordinator()
    coordinator.client.set_holiday_dates = AsyncMock()
    coordinator.data.schedule = TankSchedule(
        raw={}, default_heat_source="electric"
    )

    start_entity = dt_platform.MixergyHolidayDateTime(coordinator, is_start=True)
    chosen = dt_util.utcnow()
    await start_entity.async_set_value(chosen)

    sent_start, sent_end = coordinator.client.set_holiday_dates.await_args[0]
    assert sent_start == chosen
    assert sent_end > chosen, "no end derived for an open-ended holiday"

    coordinator.client.set_holiday_dates.reset_mock()
    end_entity = dt_platform.MixergyHolidayDateTime(coordinator, is_start=False)
    future_end = chosen + __import__("datetime").timedelta(days=3)
    await end_entity.async_set_value(future_end)

    sent_start, sent_end = coordinator.client.set_holiday_dates.await_args[0]
    assert sent_end == future_end
    assert sent_start < future_end, "start must anchor before the chosen end"


def test_naive_datetimes_are_localised_before_reaching_the_api() -> None:
    """A tz-naive input must gain the local zone, not be treated as UTC.

    HA hands services naive local times; assuming UTC would shift every holiday
    window by the machine's offset — an hour or more, silently.
    """
    from custom_components.mixergy_tank import _as_local

    naive = __import__("datetime").datetime(2026, 6, 1, 9, 0)
    assert _as_local(naive).tzinfo is not None

    aware = dt_util.utcnow()
    assert _as_local(aware) is aware


async def test_service_auth_failure_starts_reauth_and_names_the_tank() -> None:
    """A service-time auth failure must open reauth, not just error."""
    from custom_components.mixergy_tank import _run_on_targets

    coordinator = MagicMock()
    coordinator.client.tank_info.serial_number = MOCK_SERIAL
    coordinator.config_entry = MagicMock()
    coordinator.async_request_refresh = AsyncMock()

    async def boom(_coordinator):
        raise MixergyAuthError("expired")

    with patch(
        "custom_components.mixergy_tank._target_coordinators",
        AsyncMock(return_value=[coordinator]),
    ):
        with pytest.raises(HomeAssistantError, match="re-authentication required"):
            await _run_on_targets(
                MagicMock(), MagicMock(), boom, "boost charge"
            )

    coordinator.config_entry.async_start_reauth.assert_called_once()
