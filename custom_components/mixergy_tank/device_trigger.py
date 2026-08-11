"""Device triggers for the Mixergy integration.

Exposes friendly, automation-UI-discoverable triggers (low hot water,
heating started/stopped, holiday started/ended) backed by the existing
binary sensors via the core state trigger.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import (
    state as state_trigger,
)
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_PLATFORM,
    CONF_TYPE,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

# trigger type -> (binary_sensor key suffix, target state)
_TRIGGER_MAP: dict[str, tuple[str, str]] = {
    "low_hot_water": ("low_hot_water", STATE_ON),
    "heating_started": ("is_heating", STATE_ON),
    "heating_stopped": ("is_heating", STATE_OFF),
    "holiday_started": ("holiday_mode", STATE_ON),
    "holiday_ended": ("holiday_mode", STATE_OFF),
}
TRIGGER_TYPES = set(_TRIGGER_MAP)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Required(CONF_ENTITY_ID): cv.entity_id_or_uuid,
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List device triggers for a Mixergy tank device."""
    registry = er.async_get(hass)
    # Map this device's binary_sensor keys -> entity_id.
    key_to_entity: dict[str, str] = {}
    for entry in er.async_entries_for_device(registry, device_id):
        if entry.domain != "binary_sensor" or not entry.unique_id:
            continue
        for _key, _state in _TRIGGER_MAP.values():
            if entry.unique_id.endswith(f"_{_key}"):
                key_to_entity[_key] = entry.entity_id

    triggers: list[dict[str, str]] = []
    for trigger_type, (key, _state) in _TRIGGER_MAP.items():
        if key in key_to_entity:
            triggers.append(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_TYPE: trigger_type,
                    CONF_ENTITY_ID: key_to_entity[key],
                }
            )
    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a device trigger by delegating to the core state trigger."""
    _key, to_state = _TRIGGER_MAP[config[CONF_TYPE]]
    state_config = {
        CONF_PLATFORM: "state",
        CONF_ENTITY_ID: config[CONF_ENTITY_ID],
        state_trigger.CONF_TO: to_state,
    }
    state_config = await state_trigger.async_validate_trigger_config(
        hass, state_config
    )
    return await state_trigger.async_attach_trigger(
        hass, state_config, action, trigger_info, platform_type="device"
    )
