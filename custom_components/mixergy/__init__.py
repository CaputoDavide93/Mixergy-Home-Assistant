"""The Mixergy integration."""

from __future__ import annotations

import logging
from datetime import datetime

import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import MixergyApiClient, MixergyApiError
from .const import CONF_SERIAL_NUMBER, DOMAIN
from .coordinator import MixergyConfigEntry, MixergyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Service constants
SERVICE_SET_HOLIDAY = "set_holiday_dates"
SERVICE_CLEAR_HOLIDAY = "clear_holiday_dates"
SERVICE_BOOST_CHARGE = "boost_charge"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"


async def async_setup_entry(hass: HomeAssistant, entry: MixergyConfigEntry) -> bool:
    """Set up Mixergy from a config entry."""
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

    # Register services (only once per domain)
    _register_services(hass)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MixergyConfigEntry
) -> bool:
    """Unload a Mixergy config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove services when the last entry is unloaded
    loaded_entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if unload_ok and not loaded_entries:
        for service in (SERVICE_SET_HOLIDAY, SERVICE_CLEAR_HOLIDAY, SERVICE_BOOST_CHARGE):
            hass.services.async_remove(DOMAIN, service)

    return unload_ok


def _get_coordinators(hass: HomeAssistant) -> list[MixergyCoordinator]:
    """Return all active Mixergy coordinators."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.runtime_data and isinstance(entry.runtime_data, MixergyCoordinator)
    ]


def _register_services(hass: HomeAssistant) -> None:
    """Register Mixergy domain services."""

    async def handle_set_holiday(call: ServiceCall) -> None:
        """Set holiday mode dates on all configured tanks."""
        start_date: datetime = call.data[ATTR_START_DATE]
        end_date: datetime = call.data[ATTR_END_DATE]

        if start_date >= end_date:
            raise HomeAssistantError(
                "Holiday start date must be before the end date."
            )

        for coordinator in _get_coordinators(hass):
            serial = coordinator.client.tank_info.serial_number
            try:
                await coordinator.client.set_holiday_dates(start_date, end_date)
                await coordinator.async_request_refresh()
            except MixergyApiError as err:
                raise HomeAssistantError(
                    f"Failed to set holiday dates for tank {serial}: {err}"
                ) from err
            except Exception as err:
                _LOGGER.exception("Unexpected error setting holiday dates for tank %s", serial)
                raise HomeAssistantError(
                    f"Unexpected error for tank {serial}"
                ) from err

    async def handle_clear_holiday(_call: ServiceCall) -> None:
        """Clear holiday mode on all configured tanks."""
        for coordinator in _get_coordinators(hass):
            serial = coordinator.client.tank_info.serial_number
            try:
                await coordinator.client.clear_holiday_dates()
                await coordinator.async_request_refresh()
            except MixergyApiError as err:
                raise HomeAssistantError(
                    f"Failed to clear holiday dates for tank {serial}: {err}"
                ) from err
            except Exception as err:
                _LOGGER.exception("Unexpected error clearing holiday dates for tank %s", serial)
                raise HomeAssistantError(
                    f"Unexpected error for tank {serial}"
                ) from err

    async def handle_boost_charge(_call: ServiceCall) -> None:
        """Boost hot water to 100% charge on all configured tanks."""
        for coordinator in _get_coordinators(hass):
            serial = coordinator.client.tank_info.serial_number
            try:
                await coordinator.client.set_target_charge(100)
                await coordinator.async_request_refresh()
            except MixergyApiError as err:
                raise HomeAssistantError(
                    f"Failed to boost charge for tank {serial}: {err}"
                ) from err
            except Exception as err:
                _LOGGER.exception("Unexpected error boosting charge for tank %s", serial)
                raise HomeAssistantError(
                    f"Unexpected error for tank {serial}"
                ) from err

    if not hass.services.has_service(DOMAIN, SERVICE_SET_HOLIDAY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_HOLIDAY,
            handle_set_holiday,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_START_DATE): cv.datetime,
                    vol.Required(ATTR_END_DATE): cv.datetime,
                }
            ),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HOLIDAY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_HOLIDAY,
            handle_clear_holiday,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_BOOST_CHARGE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_BOOST_CHARGE,
            handle_boost_charge,
            schema=vol.Schema({}),
        )
