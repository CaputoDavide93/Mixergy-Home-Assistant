"""Select platform for the Mixergy integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import MixergyApiError
from .const import HEAT_SOURCE_OPTIONS, is_advanced_mode
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mixergy select entities — Advanced mode only."""
    if not is_advanced_mode(entry):
        return

    coordinator = entry.runtime_data
    async_add_entities([MixergyDefaultHeatSourceSelect(coordinator)])


class MixergyDefaultHeatSourceSelect(MixergyEntity, SelectEntity):
    """Select entity for the default heat source (Advanced mode)."""

    _attr_translation_key = "default_heat_source_select"
    _attr_icon = "mdi:fire-circle"
    _attr_options = HEAT_SOURCE_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MixergyCoordinator) -> None:
        """Initialise the select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.data.info.serial_number}_default_heat_source_select"
        )

    @property
    def current_option(self) -> str | None:
        """Return the currently selected heat source."""
        return self.coordinator.data.schedule.default_heat_source

    async def async_select_option(self, option: str) -> None:
        """Set the default heat source."""
        try:
            await self.coordinator.client.set_default_heat_source(option)
            await self.coordinator.async_request_refresh()
        except MixergyApiError as err:
            raise HomeAssistantError(str(err)) from err
