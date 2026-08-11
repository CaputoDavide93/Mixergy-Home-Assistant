"""Tests for config-entry setup/unload and service target resolution.

These paths decide whether the integration comes up at all and, for the
services, which tanks a call actually reaches. The target resolver is the
sharpest edge: it walks the entity, device and area registries, and a wrong
answer means a service call silently acts on the wrong tank — or on every tank
in a multi-tank account.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mixergy_tank.const import (
    CONF_EXPERIENCE_MODE,
    DOMAIN,
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


async def test_unload_removes_services_only_with_no_entries_left() -> None:
    """Services are domain-wide: removing them early breaks the other tank."""
    from custom_components.mixergy_tank import async_unload_entry

    hass = _hass()
    hass.config_entries.async_loaded_entries.return_value = [MagicMock()]

    assert await async_unload_entry(hass, _entry()) is True
    hass.services.async_remove.assert_not_called()


async def test_unload_removes_services_when_the_last_entry_goes() -> None:
    """The final unload must clean up all three services."""
    from custom_components.mixergy_tank import async_unload_entry

    hass = _hass()
    hass.config_entries.async_loaded_entries.return_value = []

    assert await async_unload_entry(hass, _entry()) is True
    assert hass.services.async_remove.call_count == 3


async def test_failed_platform_unload_keeps_services_registered() -> None:
    """If platforms refuse to unload, the entry is still live — keep services."""
    from custom_components.mixergy_tank import async_unload_entry

    hass = _hass()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    hass.config_entries.async_loaded_entries.return_value = []

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
