"""Button platform for the Mixergy integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import is_advanced_mode
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity

# Writes go through the cloud API; serialise them to avoid hammering it.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mixergy button entities — Advanced mode only."""
    if not is_advanced_mode(entry):
        return

    coordinator = entry.runtime_data
    async_add_entities([MixergyClearHolidayButton(coordinator)])


class MixergyClearHolidayButton(MixergyEntity, ButtonEntity):
    """Button to clear holiday mode dates (Advanced mode)."""

    _attr_translation_key = "clear_holiday"
    _attr_icon = "mdi:airplane-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MixergyCoordinator) -> None:
        """Initialise the button entity."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.data.info.serial_number}_clear_holiday"
        )

    async def async_press(self) -> None:
        """Clear the holiday dates."""
        await self._async_write_command(
            self.coordinator.client.clear_holiday_dates(),
            "Failed to clear holiday dates",
        )
