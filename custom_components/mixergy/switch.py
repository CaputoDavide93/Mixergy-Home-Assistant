"""Switch platform for the Mixergy integration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import MixergyApiClient, MixergyApiError, TankData
from .const import is_advanced_mode
from .coordinator import MixergyConfigEntry, MixergyCoordinator
from .entity import MixergyEntity


@dataclass(frozen=True, kw_only=True)
class MixergySwitchEntityDescription(SwitchEntityDescription):
    """Describe a Mixergy switch."""

    is_on_fn: Callable[[TankData], bool]
    turn_on_fn: Callable[[MixergyApiClient], Coroutine[Any, Any, None]]
    turn_off_fn: Callable[[MixergyApiClient], Coroutine[Any, Any, None]]
    available_fn: Callable[[TankData], bool] = lambda _: True


SWITCH_DESCRIPTIONS: tuple[MixergySwitchEntityDescription, ...] = (
    MixergySwitchEntityDescription(
        key="dsr_enabled",
        translation_key="dsr_enabled",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:transmission-tower",
        is_on_fn=lambda data: data.settings.dsr_enabled,
        turn_on_fn=lambda client: client.set_dsr_enabled(True),
        turn_off_fn=lambda client: client.set_dsr_enabled(False),
    ),
    MixergySwitchEntityDescription(
        key="frost_protection",
        translation_key="frost_protection",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:snowflake-alert",
        is_on_fn=lambda data: data.settings.frost_protection_enabled,
        turn_on_fn=lambda client: client.set_frost_protection_enabled(True),
        turn_off_fn=lambda client: client.set_frost_protection_enabled(False),
    ),
    MixergySwitchEntityDescription(
        key="distributed_computing",
        translation_key="distributed_computing",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:molecule",
        is_on_fn=lambda data: data.settings.distributed_computing_enabled,
        turn_on_fn=lambda client: client.set_distributed_computing_enabled(True),
        turn_off_fn=lambda client: client.set_distributed_computing_enabled(False),
    ),
    MixergySwitchEntityDescription(
        key="pv_divert",
        translation_key="pv_divert",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:solar-power",
        is_on_fn=lambda data: data.settings.divert_exported_enabled,
        turn_on_fn=lambda client: client.set_divert_exported_enabled(True),
        turn_off_fn=lambda client: client.set_divert_exported_enabled(False),
        available_fn=lambda data: data.info.has_pv_diverter,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MixergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mixergy switch entities — Advanced mode only."""
    if not is_advanced_mode(entry):
        return

    coordinator = entry.runtime_data
    async_add_entities(
        MixergySwitch(coordinator, description)
        for description in SWITCH_DESCRIPTIONS
    )


class MixergySwitch(MixergyEntity, SwitchEntity):
    """Representation of a Mixergy switch."""

    entity_description: MixergySwitchEntityDescription

    def __init__(
        self,
        coordinator: MixergyCoordinator,
        description: MixergySwitchEntityDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.data.info.serial_number}_{description.key}"
        )

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            super().available
            and self.entity_description.available_fn(self.coordinator.data)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            await self.entity_description.turn_on_fn(self.coordinator.client)
            await self.coordinator.async_request_refresh()
        except MixergyApiError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            await self.entity_description.turn_off_fn(self.coordinator.client)
            await self.coordinator.async_request_refresh()
        except MixergyApiError as err:
            raise HomeAssistantError(str(err)) from err
