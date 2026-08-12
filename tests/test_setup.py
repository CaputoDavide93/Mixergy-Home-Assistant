"""Tests for config-entry setup/unload and service target resolution.

These paths decide whether the integration comes up at all and, for the
services, which tanks a call actually reaches. The target resolver is the
sharpest edge: it walks the entity, device and area registries, and a wrong
answer means a service call silently acts on the wrong tank — or on every tank
in a multi-tank account.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.mixergy_tank.const import (
    CONF_EXPERIENCE_MODE,
    MODE_ADVANCED,
    MODE_SIMPLE,
)

from .conftest import MOCK_PASSWORD, MOCK_SERIAL, MOCK_USERNAME

_MODULE = "custom_components.mixergy_tank"


def _entry(options: dict | None = None, entry_id: str = "entry-1") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {
        "username": MOCK_USERNAME,
        "password": MOCK_PASSWORD,
        "serial_number": MOCK_SERIAL,
    }
    entry.options = {} if options is None else options
    return entry


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_loaded_entries = MagicMock(return_value=[])
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    return hass


# ── Setup ─────────────────────────────────────────────────────────────────────


async def test_setup_backfills_advanced_mode_for_pre_option_entries() -> None:
    """An entry predating the option must be pinned to Advanced, not Simple.

    is_advanced_mode() defaults to Simple for safety, but a pre-option entry
    historically ran Advanced. Letting the runtime default decide would silently
    drop its advanced entities on upgrade and break the user's automations, so
    setup persists Advanced explicitly.
    """
    from custom_components.mixergy_tank import async_setup_entry

    hass = _hass()
    entry = _entry(options={})

    with patch(f"{_MODULE}.MixergyApiClient"), \
         patch(f"{_MODULE}.async_get_clientsession"), \
         patch(f"{_MODULE}.MixergyCoordinator") as coordinator_cls:
        coordinator_cls.return_value.async_config_entry_first_refresh = AsyncMock()
        assert await async_setup_entry(hass, entry) is True

    hass.config_entries.async_update_entry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["options"][CONF_EXPERIENCE_MODE] == MODE_ADVANCED


async def test_setup_leaves_an_existing_mode_untouched() -> None:
    """A configured mode must never be rewritten by setup."""
    from custom_components.mixergy_tank import async_setup_entry

    hass = _hass()
    entry = _entry(options={CONF_EXPERIENCE_MODE: MODE_SIMPLE})

    with patch(f"{_MODULE}.MixergyApiClient"), \
         patch(f"{_MODULE}.async_get_clientsession"), \
         patch(f"{_MODULE}.MixergyCoordinator") as coordinator_cls:
        coordinator_cls.return_value.async_config_entry_first_refresh = AsyncMock()
        await async_setup_entry(hass, entry)

    hass.config_entries.async_update_entry.assert_not_called()


async def test_setup_forwards_platforms_and_stores_the_coordinator() -> None:
    """The coordinator must be on runtime_data before platforms are forwarded."""
    from custom_components.mixergy_tank import async_setup_entry

    hass = _hass()
    entry = _entry(options={CONF_EXPERIENCE_MODE: MODE_ADVANCED})

    with patch(f"{_MODULE}.MixergyApiClient"), \
         patch(f"{_MODULE}.async_get_clientsession"), \
         patch(f"{_MODULE}.MixergyCoordinator") as coordinator_cls:
        coordinator_cls.return_value.async_config_entry_first_refresh = AsyncMock()
        await async_setup_entry(hass, entry)

    assert entry.runtime_data is coordinator_cls.return_value
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


# ── Unload ────────────────────────────────────────────────────────────────────


async def test_services_are_registered_by_async_setup_not_per_entry() -> None:
    """Services must exist as soon as the integration is set up.

    Registering them in async_setup_entry meant that if the entry failed to
    load — the Mixergy cloud being unreachable at Home Assistant start is
    enough — the services did not exist at all, and every automation calling
    mixergy_tank.boost_charge failed validation instead of failing gracefully
    at call time.
    """
    from custom_components.mixergy_tank import async_setup

    hass = _hass()
    assert await async_setup(hass, {}) is True

    registered = {call.args[1] for call in hass.services.async_register.call_args_list}
    assert registered == {
        "set_holiday_dates",
        "clear_holiday_dates",
        "boost_charge",
    }


async def test_unload_never_removes_services() -> None:
    """Unloading an entry must leave the domain's services registered.

    Previously the last unload removed them, which is the anti-pattern the
    action-setup quality rule targets: an automation referencing a service of
    an installed-but-unloaded integration should still validate. The handlers
    raise ServiceValidationError at call time when no tank matches, which is
    the actionable failure.
    """
    from custom_components.mixergy_tank import async_unload_entry

    for loaded in ([], [MagicMock()]):
        hass = _hass()
        hass.config_entries.async_loaded_entries.return_value = loaded
        assert await async_unload_entry(hass, _entry()) is True
        hass.services.async_remove.assert_not_called()


async def test_failed_platform_unload_is_reported() -> None:
    """A refused platform unload must propagate as False."""
    from custom_components.mixergy_tank import async_unload_entry

    hass = _hass()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    assert await async_unload_entry(hass, _entry()) is False
    hass.services.async_remove.assert_not_called()


# ── Service target resolution ─────────────────────────────────────────────────


def _call(**data) -> MagicMock:
    call = MagicMock()
    call.data = data
    return call


def test_no_target_means_all_tanks() -> None:
    """An untargeted call returns None, which callers read as 'every tank'."""
    from custom_components.mixergy_tank import _resolve_target_entry_ids

    assert _resolve_target_entry_ids(MagicMock(), _call()) is None


def test_entity_target_resolves_to_its_config_entry() -> None:
    """An entity target must resolve through the entity registry."""
    from custom_components.mixergy_tank import _resolve_target_entry_ids

    hass = MagicMock()
    entity = MagicMock()
    entity.config_entry_id = "entry-1"

    with patch(f"{_MODULE}.er") as er_mod, patch(f"{_MODULE}.dr"):
        er_mod.async_get.return_value.async_get.return_value = entity
        result = _resolve_target_entry_ids(
            hass, _call(entity_id="sensor.mixergy_charge")
        )

    assert result == {"entry-1"}


def test_unknown_entity_target_resolves_to_nothing() -> None:
    """An entity that is not in the registry must not widen the target.

    Returning an empty set (rather than None) matters: None means "all tanks",
    so a typo'd entity_id must not be treated as an untargeted call.
    """
    from custom_components.mixergy_tank import _resolve_target_entry_ids

    with patch(f"{_MODULE}.er") as er_mod, patch(f"{_MODULE}.dr"):
        er_mod.async_get.return_value.async_get.return_value = None
        result = _resolve_target_entry_ids(
            MagicMock(), _call(entity_id="sensor.does_not_exist")
        )

    assert result == set()
    assert result is not None


def test_device_target_resolves_through_the_device_registry() -> None:
    """A device target resolves via the registry compatibility helper."""
    from custom_components.mixergy_tank import _resolve_target_entry_ids

    device = MagicMock()
    device.config_entry_id = "entry-2"

    with patch(f"{_MODULE}.er"), patch(f"{_MODULE}.dr") as dr_mod:
        dr_mod.async_get.return_value.async_get.return_value = device
        result = _resolve_target_entry_ids(MagicMock(), _call(device_id="dev-1"))

    assert result == {"entry-2"}


def test_area_target_collects_devices_and_entities() -> None:
    """An area target must sweep both registries, not just one."""
    from custom_components.mixergy_tank import _resolve_target_entry_ids

    device = MagicMock()
    device.config_entry_id = "entry-dev"
    entity = MagicMock()
    entity.config_entry_id = "entry-ent"

    with patch(f"{_MODULE}.er") as er_mod, patch(f"{_MODULE}.dr") as dr_mod:
        dr_mod.async_entries_for_area.return_value = [device]
        er_mod.async_entries_for_area.return_value = [entity]
        result = _resolve_target_entry_ids(MagicMock(), _call(area_id="landing"))

    assert result == {"entry-dev", "entry-ent"}


def test_device_entry_ids_prefer_the_modern_attribute() -> None:
    """HA 2026.8 moved devices to a single config_entry_id.

    The old ``config_entries`` set is a deprecated shim due for removal in
    2027.8, so the new attribute must win where present — and the fallback must
    still work on older cores.
    """
    from custom_components.mixergy_tank import _device_config_entry_ids

    modern = MagicMock()
    modern.config_entry_id = "new-style"
    modern.config_entries = {"old-style"}
    assert _device_config_entry_ids(modern) == {"new-style"}

    legacy = MagicMock()
    legacy.config_entry_id = None
    legacy.config_entries = {"old-style", "second"}
    assert _device_config_entry_ids(legacy) == {"old-style", "second"}


# ── Service validation errors ─────────────────────────────────────────────────
#
# ServiceValidationError vs HomeAssistantError is not cosmetic: HA presents the
# former as "your input was wrong" and the latter as "the integration failed".
# Getting it backwards sends a user hunting for a fault that isn't there.


async def test_services_survive_an_entry_that_never_loaded() -> None:
    """The whole point of async_setup registration.

    With no loaded entries the services must still exist and, when called,
    fail with an actionable validation error rather than not existing.
    """
    from custom_components.mixergy_tank import _target_coordinators

    hass = _hass()
    hass.config_entries.async_loaded_entries.return_value = []

    call = MagicMock()
    call.data = {"serial_number": "MX999999"}

    with pytest.raises(ServiceValidationError):
        await _target_coordinators(hass, call)


async def test_unknown_serial_raises_validation_error_naming_the_serial() -> None:
    """A typo'd serial is user input, and the message must identify it."""
    from custom_components.mixergy_tank import _target_coordinators

    hass = _hass()
    hass.config_entries.async_loaded_entries.return_value = []
    call = MagicMock()
    call.data = {"serial_number": "mx999999"}

    with pytest.raises(ServiceValidationError) as err:
        await _target_coordinators(hass, call)

    assert err.value.translation_key == "unknown_serial_number"
    # Normalised to upper case before matching and before being reported.
    assert err.value.translation_placeholders == {"serial": "MX999999"}


async def test_target_matching_nothing_raises_validation_error() -> None:
    """An entity/device/area target owned by another integration is user error."""
    from custom_components.mixergy_tank import _target_coordinators

    hass = _hass()
    hass.config_entries.async_loaded_entries.return_value = []
    call = MagicMock()
    call.data = {"entity_id": ["sensor.someone_elses"]}

    with patch("custom_components.mixergy_tank.er") as er_mod, \
         patch("custom_components.mixergy_tank.dr"):
        er_mod.async_get.return_value.async_get.return_value = None
        with pytest.raises(ServiceValidationError) as err:
            await _target_coordinators(hass, call)

    assert err.value.translation_key == "no_matching_target"


async def test_holiday_start_after_end_raises_validation_error() -> None:
    """Reversed dates are the user's mistake, not a cloud failure."""
    import custom_components.mixergy_tank as integration

    hass = _hass()
    registered: dict = {}
    hass.services.async_register = MagicMock(
        side_effect=lambda domain, name, handler, **kw: registered.__setitem__(
            name, handler
        )
    )
    hass.services.has_service = MagicMock(return_value=False)

    await integration.async_setup(hass, {})

    call = MagicMock()
    call.data = {
        "start_date": datetime(2026, 6, 8, 9, 0),
        "end_date": datetime(2026, 6, 1, 9, 0),
    }

    with pytest.raises(ServiceValidationError) as err:
        await registered["set_holiday_dates"](call)

    assert err.value.translation_key == "holiday_start_after_end"


async def test_every_exception_translation_key_exists_in_strings() -> None:
    """A raised translation_key with no string renders as a raw key to users."""
    import json
    import re
    from pathlib import Path

    component = Path(__file__).parents[1] / "custom_components" / "mixergy_tank"
    declared = set(
        json.loads((component / "strings.json").read_text())
        .get("exceptions", {})
    )

    used: set[str] = set()
    for source in component.glob("*.py"):
        text = source.read_text()
        for match in re.finditer(r'translation_key="([^"]+)"', text):
            # Entity translation keys live in the entity block, not exceptions;
            # only collect keys raised alongside a translation_domain.
            start = max(0, match.start() - 300)
            if "translation_domain" in text[start : match.end()]:
                used.add(match.group(1))

    missing = used - declared
    assert not missing, f"raised translation keys with no string: {missing}"


async def test_untargeted_call_with_nothing_loaded_fails_loudly() -> None:
    """An untargeted call must not report success while doing nothing.

    The entity/device/area and serial branches already raised when they
    resolved to nothing, but the untargeted branch returned an empty list —
    so `action: mixergy_tank.boost_charge` with no target reported SUCCESS
    while the entry was unloaded. No error, no log line, and no hot water.
    That is exactly the state async_setup exists to serve: installed, but the
    entry failed to load because the cloud was unreachable at startup.
    """
    from custom_components.mixergy_tank import _target_coordinators

    hass = _hass()
    hass.config_entries.async_loaded_entries.return_value = []

    call = MagicMock()
    call.data = {}

    with pytest.raises(ServiceValidationError) as err:
        await _target_coordinators(hass, call)

    assert err.value.translation_key == "no_tanks_loaded"
