"""DateTime platform for the Mixergy integration.

Exposes holiday start/end as writable datetime entities so users can set
holiday mode from a UI picker (in addition to the services). Advanced mode only.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import is_advanced_mode
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity

# Writes go through the cloud API; serialise them.
PARALLEL_UPDATES = 1

# Default span applied when only one end of the holiday window is set yet.
_DEFAULT_SPAN = timedelta(days=7)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Mixergy holiday datetime entities — Advanced mode only."""
    if not is_advanced_mode(entry):
        return
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MixergyHolidayDateTime(coordinator, is_start=True),
            MixergyHolidayDateTime(coordinator, is_start=False),
        ]
    )


class MixergyHolidayDateTime(MixergyEntity, DateTimeEntity):
    """Writable holiday start/end datetime.

    Holiday mode is a single window (start + end) PUT together, so setting
    one end reads the current value of the other (defaulting sensibly when
    unset) and writes the whole window via the schedule write-lock in the API.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: MixergyCoordinator, *, is_start: bool
    ) -> None:
        """Initialise the holiday datetime entity."""
        super().__init__(coordinator)
        self._is_start = is_start
        key = "holiday_start" if is_start else "holiday_end"
        self._attr_translation_key = f"{key}_set"
        self._attr_unique_id = (
            f"{coordinator.data.info.serial_number}_{key}_set"
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the current holiday start/end (UTC-aware) or None."""
        schedule = self.coordinator.data.schedule
        return schedule.holiday_start if self._is_start else schedule.holiday_end

    async def async_set_value(self, value: datetime) -> None:
        """Set this end of the holiday window, preserving the other end."""
        schedule = self.coordinator.data.schedule

        if self._is_start:
            start = value
            end = schedule.holiday_end or (value + _DEFAULT_SPAN)
        else:
            end = value
            start = schedule.holiday_start or dt_util.utcnow()

        await self._async_write_command(
            self.coordinator.client.set_holiday_dates(start, end),
            "Failed to set holiday dates",
        )
