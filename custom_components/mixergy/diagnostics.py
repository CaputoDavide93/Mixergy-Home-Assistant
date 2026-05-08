"""Diagnostics support for the Mixergy integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL_NUMBER
from .coordinator import MixergyConfigEntry, MixergyCoordinator

REDACTED = "**REDACTED**"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MixergyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: MixergyCoordinator = entry.runtime_data

    # Redact sensitive data from config. Serial number is a stable
    # physical-asset identifier — knowing it doesn't grant access on
    # its own, but it lets a third party correlate diagnostics dumps
    # to a specific customer install. Redact alongside credentials.
    config_data = dict(entry.data)
    config_data[CONF_USERNAME] = REDACTED
    config_data[CONF_PASSWORD] = REDACTED
    if CONF_SERIAL_NUMBER in config_data:
        config_data[CONF_SERIAL_NUMBER] = REDACTED

    # Convert tank data to dict, redacting identifiers + raw schedule
    tank_data = asdict(coordinator.data)

    # Same logic for tank_data.info.serial_number — it's the same value
    # surfaced via a different field path.
    if "info" in tank_data and "serial_number" in tank_data["info"]:
        tank_data["info"]["serial_number"] = REDACTED

    # Remove raw schedule payload (may contain account-specific data)
    if "schedule" in tank_data and "raw" in tank_data["schedule"]:
        tank_data["schedule"]["raw"] = REDACTED

    return {
        "config": config_data,
        "tank_data": tank_data,
    }
