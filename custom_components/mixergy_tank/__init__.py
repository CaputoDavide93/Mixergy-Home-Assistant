"""The Mixergy integration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.auth.permissions.const import CAT_ENTITIES, POLICY_CONTROL
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import MixergyApiClient, MixergyApiError, MixergyAuthError
from .const import (
    CONF_EXPERIENCE_MODE,
    CONF_SERIAL_NUMBER,
    DOMAIN,
    MODE_ADVANCED,
)
from .coordinator import MixergyConfigEntry, MixergyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]

# Service constants
SERVICE_SET_HOLIDAY = "set_holiday_dates"
SERVICE_CLEAR_HOLIDAY = "clear_holiday_dates"
SERVICE_BOOST_CHARGE = "boost_charge"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"
ATTR_SERIAL_NUMBER = "serial_number"

# Only the target keys we actually resolve in _resolve_target_entry_ids.
# Deliberately NOT cv.ENTITY_SERVICE_FIELDS — that also accepts floor_id and
# label_id, which we don't resolve; a floor/label target would then validate,
# resolve to nothing, and silently fall through to "all tanks" (acting far
# broader than intended). Restricting the schema makes such a target fail
# closed with a clear "extra keys not allowed" error instead.
# Annotated so mypy can infer the key type when this is splatted into a
# larger vol.Schema mapping below.
_TARGET_FIELDS: dict[Any, Any] = {
    vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_AREA_ID): vol.All(cv.ensure_list, [cv.string]),
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the domain's services.

    Services are registered here rather than in async_setup_entry so they
    exist whenever the integration is installed, independent of whether any
    config entry has loaded. Registering per-entry meant that if the entry
    failed to set up — the Mixergy cloud being unreachable at Home Assistant
    start is enough — the services did not exist at all, and every automation
    calling mixergy_tank.boost_charge failed validation rather than failing
    gracefully at call time.

    The handlers below resolve their targets at call time and raise
    ServiceValidationError when nothing matches, which is the correct
    behaviour for "installed but not currently loaded".
    """
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MixergyConfigEntry) -> bool:
    """Set up Mixergy from a config entry."""
    # Backfill experience_mode for entries created before the option existed.
    # The runtime fallback (const.is_advanced_mode) defaults to Simple for
    # safety, but a pre-option entry historically ran in Advanced — flipping
    # it to Simple on upgrade would silently drop its advanced entities and
    # break automations. Persist Advanced explicitly so behaviour is stable.
    if CONF_EXPERIENCE_MODE not in entry.options:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_EXPERIENCE_MODE: MODE_ADVANCED},
        )

    session = async_get_clientsession(hass)

    client = MixergyApiClient(
        session=session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        serial_number=entry.data[CONF_SERIAL_NUMBER],
    )

    coordinator = MixergyCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Options-change reload is handled by MixergyOptionsFlow subclassing
    # OptionsFlowWithReload (config_flow.py). Do NOT re-add an
    # add_update_listener(reload) here: combined with the reloading flow
    # methods (async_update_reload_and_abort in reauth/reconfigure) it is
    # deprecated since HA 2026.6 and an ERROR from 2026.12.

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MixergyConfigEntry
) -> bool:
    """Unload a Mixergy config entry.

    Services are deliberately NOT removed here — see async_setup. They are
    registered once for the domain and stay registered, so an automation
    referencing them keeps validating while entries come and go.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _coordinator_by_entry(
    hass: HomeAssistant,
) -> dict[str, MixergyCoordinator]:
    """Map loaded config-entry id → coordinator.

    async_loaded_entries excludes entries mid-unload, so a service call can
    never operate a coordinator whose platforms have already been torn down.
    """
    return {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if isinstance(entry.runtime_data, MixergyCoordinator)
    }


def _device_config_entry_ids(dev: dr.DeviceEntry) -> set[str]:
    """Config-entry ids for a device, across the HA 2026.8 registry change.

    HA 2026.8 moved devices to exactly one config entry: the new attribute is
    ``config_entry_id`` and the old ``config_entries`` set is a deprecated
    shim slated for removal in 2027.8. Prefer the new attribute when present
    and fall back on older cores, so this keeps working on both sides of the
    change — guard, don't assume.
    """
    entry_id = getattr(dev, "config_entry_id", None)
    if entry_id is not None:
        return {entry_id}
    return set(dev.config_entries)


def _resolve_target_entry_ids(
    hass: HomeAssistant, call: ServiceCall
) -> set[str] | None:
    """Resolve a call's entity/device/area target to config-entry ids.

    Returns None when no target was supplied (caller wants all tanks).
    """
    data = call.data
    entity_ids = cv.ensure_list(data.get(ATTR_ENTITY_ID, []))
    device_ids = cv.ensure_list(data.get(ATTR_DEVICE_ID, []))
    area_ids = cv.ensure_list(data.get(ATTR_AREA_ID, []))
    if not (entity_ids or device_ids or area_ids):
        return None

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    entry_ids: set[str] = set()

    for entity_id in entity_ids:
        ent = ent_reg.async_get(entity_id)
        if ent and ent.config_entry_id:
            entry_ids.add(ent.config_entry_id)
    for device_id in device_ids:
        dev = dev_reg.async_get(device_id)
        if dev:
            entry_ids.update(_device_config_entry_ids(dev))
    for area_id in area_ids:
        for dev in dr.async_entries_for_area(dev_reg, area_id):
            entry_ids.update(_device_config_entry_ids(dev))
        for ent in er.async_entries_for_area(ent_reg, area_id):
            if ent.config_entry_id:
                entry_ids.add(ent.config_entry_id)
    return entry_ids


async def _async_check_user_can_control(
    hass: HomeAssistant,
    call: ServiceCall,
    coordinators: list[MixergyCoordinator],
) -> None:
    """Authorise the caller for *each* targeted tank.

    System/automation calls (no user_id) and admins pass through. A non-admin
    must hold control permission on at least one entity of every targeted
    config entry — so a user scoped to tank A cannot drive tank B or "all
    tanks". This is stricter than a plain domain-control check.
    """
    user_id = call.context.user_id
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(
            context=call.context, permission=POLICY_CONTROL, user_id=user_id
        )
    if user.is_admin:
        return

    ent_reg = er.async_get(hass)
    for coordinator in coordinators:
        entry_id = coordinator.config_entry.entry_id
        entities = er.async_entries_for_config_entry(ent_reg, entry_id)
        if not any(
            user.permissions.check_entity(e.entity_id, POLICY_CONTROL)
            for e in entities
        ):
            raise Unauthorized(
                context=call.context,
                permission=POLICY_CONTROL,
                user_id=user_id,
                perm_category=CAT_ENTITIES,
            )


async def _target_coordinators(
    hass: HomeAssistant, call: ServiceCall
) -> list[MixergyCoordinator]:
    """Resolve which tanks a service call targets, then authorise the caller.

    Targeting precedence: an explicit entity/device/area target, else a
    ``serial_number``, else every configured tank (legacy behaviour). After
    resolution the caller's per-tank control permission is verified.
    """
    by_entry = _coordinator_by_entry(hass)
    all_coords = list(by_entry.values())

    entry_ids = _resolve_target_entry_ids(hass, call)
    serial = call.data.get(ATTR_SERIAL_NUMBER)

    if entry_ids is not None:
        targets = [by_entry[e] for e in entry_ids if e in by_entry]
        if not targets:
            # Bad input, not an integration fault: the user named a target
            # this integration does not own, or the entry is not loaded.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_matching_target",
            )
    elif serial is not None:
        serial = serial.upper().strip()
        targets = [
            c for c in all_coords
            if c.client.tank_info.serial_number == serial
        ]
        if not targets:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_serial_number",
                translation_placeholders={"serial": serial},
            )
    else:
        targets = all_coords

    await _async_check_user_can_control(hass, call, targets)
    return targets


def _as_local(value: datetime) -> datetime:
    """Interpret a naive service datetime as HA local time.

    ``cv.datetime`` yields naive datetimes; users mean their local time, not
    UTC. Attaching the local zone here lets the API client convert to UTC
    correctly instead of silently shifting holiday windows by the UTC offset.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return value


async def _run_on_targets(
    hass: HomeAssistant,
    call: ServiceCall,
    op: Callable[[MixergyCoordinator], Coroutine[Any, Any, None]],
    action_desc: str,
) -> None:
    """Apply ``op`` to each targeted tank with uniform error handling."""
    for coordinator in await _target_coordinators(hass, call):
        serial = coordinator.client.tank_info.serial_number
        try:
            await op(coordinator)
            await coordinator.async_request_refresh()
        except MixergyAuthError as err:
            # Command-time auth failure: open HA's reauth flow rather than
            # only surfacing an error the user can't act on. (Must precede
            # the MixergyApiError branch — it is a subclass.)
            coordinator.config_entry.async_start_reauth(hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_auth_failed",
                translation_placeholders={"serial": serial},
            ) from err
        except MixergyApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_failed",
                translation_placeholders={
                    "action": action_desc,
                    "serial": serial,
                    "error": str(err),
                },
            ) from err
        except (OSError, TimeoutError) as err:
            _LOGGER.exception(
                "Unexpected error during '%s' for tank %s", action_desc, serial
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_unexpected_error",
                translation_placeholders={"serial": serial, "error": str(err)},
            ) from err


def _register_services(hass: HomeAssistant) -> None:
    """Register Mixergy domain services."""

    async def handle_set_holiday(call: ServiceCall) -> None:
        """Set holiday mode dates on the targeted tank(s)."""
        start_date = _as_local(call.data[ATTR_START_DATE])
        end_date = _as_local(call.data[ATTR_END_DATE])

        if start_date >= end_date:
            # User input, not an integration fault — ServiceValidationError
            # renders this as a validation message rather than an error
            # attributed to the integration.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="holiday_start_after_end",
            )

        await _run_on_targets(
            hass, call,
            lambda c: c.client.set_holiday_dates(start_date, end_date),
            "set holiday dates",
        )

    async def handle_clear_holiday(call: ServiceCall) -> None:
        """Clear holiday mode on the targeted tank(s)."""
        await _run_on_targets(
            hass, call,
            lambda c: c.client.clear_holiday_dates(),
            "clear holiday dates",
        )

    async def handle_boost_charge(call: ServiceCall) -> None:
        """Boost hot water to 100% charge on the targeted tank(s)."""
        await _run_on_targets(
            hass, call,
            lambda c: c.client.set_target_charge(100),
            "boost charge",
        )

    # Each service accepts an optional entity/device/area target (resolved to
    # tanks, with per-target permission checks) plus the legacy serial_number
    # alias. _TARGET_FIELDS supplies the optional target keys.
    if not hass.services.has_service(DOMAIN, SERVICE_SET_HOLIDAY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_HOLIDAY,
            handle_set_holiday,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_START_DATE): cv.datetime,
                    vol.Required(ATTR_END_DATE): cv.datetime,
                    vol.Optional(ATTR_SERIAL_NUMBER): cv.string,
                    **_TARGET_FIELDS,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HOLIDAY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_HOLIDAY,
            handle_clear_holiday,
            schema=vol.Schema(
                {
                    vol.Optional(ATTR_SERIAL_NUMBER): cv.string,
                    **_TARGET_FIELDS,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_BOOST_CHARGE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_BOOST_CHARGE,
            handle_boost_charge,
            schema=vol.Schema(
                {
                    vol.Optional(ATTR_SERIAL_NUMBER): cv.string,
                    **_TARGET_FIELDS,
                }
            ),
        )
