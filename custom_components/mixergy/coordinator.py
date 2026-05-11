"""DataUpdateCoordinator for the Mixergy integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
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

    async def _async_update_data(self) -> TankData:
        """Fetch data from the Mixergy API."""
        try:
            data = await self.client.fetch_all()
            # Stamp the successful fetch time so the diagnostic sensor can show it
            data.last_update_time = dt_util.utcnow()
            return data
        except MixergyAuthError as err:
            # Triggers HA reauth flow
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except MixergyTankNotFoundError as err:
            # Tank serial no longer present in the user's account
            # (decommissioned, account changed, hardware replaced). Map
            # to ConfigEntryError so HA surfaces a clear fix-flow rather
            # than spamming a traceback on every 30s poll with no user-
            # facing remediation.
            raise ConfigEntryError(
                f"Mixergy tank not found in account: {err}"
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
