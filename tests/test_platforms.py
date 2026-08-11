"""Tests for the button, select and switch platforms.

These three platforms had no coverage at all, so nothing caught an entity that
failed to construct, a description wired to the wrong API call, or an
Advanced-mode gate that stopped gating. They are exercised here without a real
``hass``: entities are constructed directly against a mock coordinator, which
is the same approach the water-heater and datetime tests already use.

``async_setup_entry`` is driven through a stub ``async_add_entities`` so the
mode gates and the produced entity sets are asserted, not just the entity
classes in isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.mixergy_tank.api import (
    MixergyApiError,
    MixergyAuthError,
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


def _tank_data(
    *,
    dsr: bool = False,
    frost: bool = True,
    distributed: bool = False,
    divert: bool = False,
    has_pv: bool = True,
    default_heat_source: str = "electric",
) -> TankData:
    """Return TankData with the fields the three platforms actually read."""
    return TankData(
        info=TankInfo(
            serial_number=MOCK_SERIAL,
            model_code="MIXERGY-180",
            firmware_version="2.1.0",
            has_pv_diverter=has_pv,
        ),
        measurement=TankMeasurement(charge=50.0),
        settings=TankSettings(
            dsr_enabled=dsr,
            frost_protection_enabled=frost,
            distributed_computing_enabled=distributed,
            divert_exported_enabled=divert,
        ),
        schedule=TankSchedule(raw={}, default_heat_source=default_heat_source),
    )


def _coordinator(data: TankData | None = None) -> MagicMock:
    """Return a mock coordinator with an AsyncMock-backed client."""
    coordinator = MagicMock()
    coordinator.data = data if data is not None else _tank_data()
    coordinator.last_update_success = True
    client = MagicMock()
    for method in (
        "clear_holiday_dates",
        "set_default_heat_source",
        "set_dsr_enabled",
        "set_frost_protection_enabled",
        "set_distributed_computing_enabled",
        "set_divert_exported_enabled",
    ):
        setattr(client, method, AsyncMock())
    coordinator.client = client
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry = MagicMock()
    return coordinator


def _entry(mode: str = MODE_ADVANCED, coordinator: MagicMock | None = None):
    """Return a mock config entry carrying an experience mode."""
    entry = MagicMock()
    entry.options = {CONF_EXPERIENCE_MODE: mode}
    entry.runtime_data = coordinator if coordinator is not None else _coordinator()
    return entry


async def _collect(setup_entry, entry) -> list:
    """Run a platform's async_setup_entry and return the entities it added."""
    added: list = []

    def async_add_entities(new_entities, update_before_add: bool = False) -> None:
        added.extend(new_entities)

    await setup_entry(MagicMock(), entry, async_add_entities)
    return added


# ── Advanced-mode gating ──────────────────────────────────────────────────────
#
# All three platforms are Advanced-only. A gate that stops gating silently
# exposes the full control surface to Simple-mode users, which is the exact
# thing is_advanced_mode() defaults conservatively to prevent.


@pytest.mark.parametrize(
    "module_name",
    ("button", "select", "switch"),
)
async def test_platform_adds_nothing_in_simple_mode(module_name: str) -> None:
    """Simple mode must not create any Advanced-only entity."""
    module = __import__(
        f"custom_components.mixergy_tank.{module_name}", fromlist=["async_setup_entry"]
    )
    entities = await _collect(
        module.async_setup_entry, _entry(mode=MODE_SIMPLE)
    )
    assert entities == []


@pytest.mark.parametrize(
    "module_name",
    ("button", "select", "switch"),
)
async def test_platform_adds_entities_in_advanced_mode(module_name: str) -> None:
    """Advanced mode must create at least one entity per platform."""
    module = __import__(
        f"custom_components.mixergy_tank.{module_name}", fromlist=["async_setup_entry"]
    )
    entities = await _collect(
        module.async_setup_entry, _entry(mode=MODE_ADVANCED)
    )
    assert entities, f"{module_name} produced no entities in Advanced mode"
    for entity in entities:
        assert entity.unique_id.startswith(MOCK_SERIAL)


async def test_missing_experience_mode_option_is_treated_as_simple() -> None:
    """An entry with no mode option must not expose Advanced entities.

    is_advanced_mode() defaults to Simple precisely so a pre-options entry
    cannot silently gain the full control surface after an upgrade.
    """
    from custom_components.mixergy_tank import switch

    entry = _entry()
    entry.options = {}
    assert await _collect(switch.async_setup_entry, entry) == []


# ── Button ────────────────────────────────────────────────────────────────────


async def test_clear_holiday_button_calls_api_and_refreshes() -> None:
    """Pressing the button clears holiday dates and refreshes the coordinator."""
    from custom_components.mixergy_tank.button import MixergyClearHolidayButton

    coordinator = _coordinator()
    button = MixergyClearHolidayButton(coordinator)

    assert button.unique_id == f"{MOCK_SERIAL}_clear_holiday"

    await button.async_press()

    coordinator.client.clear_holiday_dates.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


# ── Select ────────────────────────────────────────────────────────────────────


async def test_select_reports_current_heat_source() -> None:
    """current_option reflects the coordinator's schedule."""
    from custom_components.mixergy_tank.select import MixergyDefaultHeatSourceSelect

    select = MixergyDefaultHeatSourceSelect(
        _coordinator(_tank_data(default_heat_source="heat_pump"))
    )
    assert select.current_option == "heat_pump"


async def test_select_sets_option_and_refreshes() -> None:
    """Selecting an option forwards it to the API and refreshes."""
    from custom_components.mixergy_tank.select import MixergyDefaultHeatSourceSelect

    coordinator = _coordinator()
    select = MixergyDefaultHeatSourceSelect(coordinator)

    await select.async_select_option("indirect")

    coordinator.client.set_default_heat_source.assert_awaited_once_with("indirect")
    coordinator.async_request_refresh.assert_awaited_once()


async def test_select_offers_only_known_heat_sources() -> None:
    """The advertised options must match the shared constant."""
    from custom_components.mixergy_tank.const import HEAT_SOURCE_OPTIONS
    from custom_components.mixergy_tank.select import MixergyDefaultHeatSourceSelect

    select = MixergyDefaultHeatSourceSelect(_coordinator())
    assert select.options == list(HEAT_SOURCE_OPTIONS)


# ── Switch ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "field", "client_method"),
    (
        ("dsr_enabled", "dsr", "set_dsr_enabled"),
        ("frost_protection", "frost", "set_frost_protection_enabled"),
        (
            "distributed_computing",
            "distributed",
            "set_distributed_computing_enabled",
        ),
        ("pv_divert", "divert", "set_divert_exported_enabled"),
    ),
)
async def test_switch_reads_state_and_writes_both_directions(
    key: str, field: str, client_method: str
) -> None:
    """Each switch reads its own setting and drives its own API call.

    Parametrised over every description so a copy-paste error — two switches
    sharing one is_on_fn, or turn_off wired to turn_on — cannot pass.
    """
    from custom_components.mixergy_tank.switch import (
        SWITCH_DESCRIPTIONS,
        MixergySwitch,
    )

    description = next(d for d in SWITCH_DESCRIPTIONS if d.key == key)

    on_switch = MixergySwitch(_coordinator(_tank_data(**{field: True})), description)
    assert on_switch.is_on is True

    coordinator = _coordinator(_tank_data(**{field: False}))
    off_switch = MixergySwitch(coordinator, description)
    assert off_switch.is_on is False
    assert off_switch.unique_id == f"{MOCK_SERIAL}_{key}"

    await off_switch.async_turn_on()
    getattr(coordinator.client, client_method).assert_awaited_with(True)

    await off_switch.async_turn_off()
    getattr(coordinator.client, client_method).assert_awaited_with(False)

    assert coordinator.async_request_refresh.await_count == 2


async def test_pv_switch_unavailable_without_a_diverter() -> None:
    """The PV switch must hide itself on a tank with no diverter fitted."""
    from custom_components.mixergy_tank.switch import (
        SWITCH_DESCRIPTIONS,
        MixergySwitch,
    )

    description = next(d for d in SWITCH_DESCRIPTIONS if d.key == "pv_divert")

    without = MixergySwitch(_coordinator(_tank_data(has_pv=False)), description)
    assert without.available is False

    with_pv = MixergySwitch(_coordinator(_tank_data(has_pv=True)), description)
    assert with_pv.available is True


async def test_non_pv_switches_stay_available_without_a_diverter() -> None:
    """Only the PV switch is diverter-gated; the rest must not inherit it."""
    from custom_components.mixergy_tank.switch import (
        SWITCH_DESCRIPTIONS,
        MixergySwitch,
    )

    coordinator = _coordinator(_tank_data(has_pv=False))
    for description in SWITCH_DESCRIPTIONS:
        if description.key == "pv_divert":
            continue
        assert MixergySwitch(coordinator, description).available is True


# ── Write-command error handling (shared base) ────────────────────────────────
#
# Every write on these platforms funnels through MixergyEntity._async_write_command.
# MixergyAuthError is a subclass of MixergyApiError, so the ordering of those
# except branches is load-bearing: catching the base first would swallow the
# reauth trigger and leave the user with an error they cannot act on.


async def test_write_failure_raises_home_assistant_error() -> None:
    """An API error surfaces as HomeAssistantError, not the raw client error."""
    from custom_components.mixergy_tank.button import MixergyClearHolidayButton

    coordinator = _coordinator()
    coordinator.client.clear_holiday_dates = AsyncMock(
        side_effect=MixergyApiError("upstream exploded")
    )
    button = MixergyClearHolidayButton(coordinator)

    with pytest.raises(HomeAssistantError, match="Failed to clear holiday dates"):
        await button.async_press()

    coordinator.async_request_refresh.assert_not_awaited()


async def test_write_auth_failure_starts_reauth() -> None:
    """A command-time auth failure must start the reauth flow."""
    from custom_components.mixergy_tank.button import MixergyClearHolidayButton

    coordinator = _coordinator()
    coordinator.client.clear_holiday_dates = AsyncMock(
        side_effect=MixergyAuthError("token rejected")
    )
    button = MixergyClearHolidayButton(coordinator)
    button.hass = MagicMock()

    with pytest.raises(HomeAssistantError, match="re-authentication required"):
        await button.async_press()

    coordinator.config_entry.async_start_reauth.assert_called_once()


async def test_switch_write_failure_reports_the_failing_switch() -> None:
    """The error names the switch, so a multi-switch failure is diagnosable."""
    from custom_components.mixergy_tank.switch import (
        SWITCH_DESCRIPTIONS,
        MixergySwitch,
    )

    description = next(d for d in SWITCH_DESCRIPTIONS if d.key == "dsr_enabled")
    coordinator = _coordinator()
    coordinator.client.set_dsr_enabled = AsyncMock(
        side_effect=MixergyApiError("nope")
    )

    with pytest.raises(HomeAssistantError, match="dsr_enabled"):
        await MixergySwitch(coordinator, description).async_turn_on()


# ── Availability follows the coordinator ──────────────────────────────────────


def test_entities_go_unavailable_when_the_coordinator_fails() -> None:
    """A failed poll must mark entities unavailable, not serve stale values.

    CoordinatorEntity supplies this, but each platform overrides `available`
    to add its own predicate — an override that forgets to consult
    super().available would keep reporting the last known reading through an
    outage, which reads as "everything is fine" on the dashboard.
    """
    from custom_components.mixergy_tank.binary_sensor import (
        STATIC_BINARY_SENSOR_DESCRIPTIONS,
        MixergyBinarySensor,
    )
    from custom_components.mixergy_tank.number import (
        NUMBER_DESCRIPTIONS,
        MixergyNumber,
    )
    from custom_components.mixergy_tank.switch import (
        SWITCH_DESCRIPTIONS,
        MixergySwitch,
    )

    coordinator = _coordinator()
    coordinator.last_update_success = False

    entities = [
        MixergyBinarySensor(coordinator, STATIC_BINARY_SENSOR_DESCRIPTIONS[0]),
        MixergyNumber(coordinator, NUMBER_DESCRIPTIONS[0]),
        MixergySwitch(coordinator, SWITCH_DESCRIPTIONS[0]),
    ]

    for entity in entities:
        assert entity.available is False, type(entity).__name__
