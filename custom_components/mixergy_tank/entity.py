"""Base entity for the Mixergy integration."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MixergyApiError, MixergyAuthError
from .const import DOMAIN, MANUFACTURER
from .coordinator import MixergyCoordinator


class MixergyEntity(CoordinatorEntity[MixergyCoordinator]):
    """Base class for all Mixergy entities.

    Uses CoordinatorEntity properly — should_poll defaults to False,
    and state updates are driven entirely by the coordinator.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: MixergyCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)

        serial = coordinator.data.info.serial_number

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            name=f"Mixergy Tank ({serial})",
            model=coordinator.data.info.model_code,
            sw_version=coordinator.data.info.firmware_version,
            serial_number=serial,
            configuration_url="https://www.mixergy.io",
        )

    async def _async_write_command(
        self, command: Awaitable[None], action: str
    ) -> None:
        """Run a write command, then refresh — with uniform error handling.

        A command-time auth failure starts HA's reauth flow (consistent with
        the domain services) instead of only surfacing a generic error the
        user can't act on. MixergyAuthError must be caught before
        MixergyApiError — it is a subclass.
        """
        try:
            await command
            await self.coordinator.async_request_refresh()
        except MixergyAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_auth_failed",
                translation_placeholders={"action": action},
            ) from err
        except MixergyApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"action": action, "error": str(err)},
            ) from err
