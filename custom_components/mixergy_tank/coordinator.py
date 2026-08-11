"""DataUpdateCoordinator for the Mixergy integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import (
    MixergyApiClient,
    MixergyApiError,
    MixergyAuthError,
    MixergyConnectionError,
    MixergyTankNotFoundError,
    TankData,
)
from .const import CONF_UPDATE_INTERVAL, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class MixergyCoordinator(DataUpdateCoordinator[TankData]):
    """Coordinator to manage fetching Mixergy tank data."""

    config_entry: MixergyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: MixergyApiClient,
        config_entry: MixergyConfigEntry,
    ) -> None:
        """Initialise the coordinator."""
        interval = timedelta(
            seconds=config_entry.options.get(CONF_UPDATE_INTERVAL, UPDATE_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval,
            config_entry=config_entry,
        )
        self.client = client

    @property
    def _tank_not_found_issue_id(self) -> str:
        """Stable repair-issue id for this entry's tank-not-found state."""
        return f"tank_not_found_{self.config_entry.entry_id}"

    async def _async_update_data(self) -> TankData:
        """Fetch data from the Mixergy API."""
        try:
            data = await self.client.fetch_all()
            # Stamp the successful fetch time so the diagnostic sensor can show it
            data.last_update_time = dt_util.utcnow()
            # Clear a previously-raised tank-not-found repair if we recovered.
            ir.async_delete_issue(
                self.hass, DOMAIN, self._tank_not_found_issue_id
            )
            return data
        except MixergyAuthError as err:
            # Triggers HA reauth flow
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except MixergyTankNotFoundError as err:
            # Tank serial no longer present in the user's account
            # (decommissioned, account changed, hardware replaced). Raise a
            # repair issue with an actionable fix (reconfigure) and map to
            # ConfigEntryError so HA surfaces a clear state rather than
            # spamming a traceback on every poll.
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._tank_not_found_issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="tank_not_found",
                translation_placeholders={
                    "serial": self.client.tank_info.serial_number
                },
            )
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="tank_not_found_setup",
                translation_placeholders={
                    "serial": self.client.tank_info.serial_number
                },
            ) from err
        except MixergyConnectionError as err:
            raise UpdateFailed(
                f"Error communicating with Mixergy API: {err}"
            ) from err
        except MixergyApiError as err:
            # Any other API-layer error that escapes the more-specific
            # branches above — surface as UpdateFailed (retryable) rather
            # than letting the bare exception abort the coordinator.
            raise UpdateFailed(
                f"Mixergy API error: {err}"
            ) from err


# Type alias defined after the class so MixergyCoordinator is in scope.
MixergyConfigEntry = ConfigEntry[MixergyCoordinator]
