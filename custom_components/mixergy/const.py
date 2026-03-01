"""Constants for the Mixergy integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

DOMAIN: Final = "mixergy"
MANUFACTURER: Final = "Mixergy Ltd"

# Config keys
CONF_SERIAL_NUMBER: Final = "serial_number"

# Options keys
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_EXPERIENCE_MODE: Final = "experience_mode"

# Experience mode values
MODE_SIMPLE: Final = "simple"
MODE_ADVANCED: Final = "advanced"

# Coordinator update interval (seconds)
UPDATE_INTERVAL: Final = 30
MIN_UPDATE_INTERVAL: Final = 10
MAX_UPDATE_INTERVAL: Final = 300

# Heat source options for the select entity (HA-facing format)
HEAT_SOURCE_OPTIONS: Final = ["electric", "indirect", "heat_pump"]

# Binary sensor thresholds for hot water level alerts
LOW_HOT_WATER_THRESHOLD: Final = 5    # % charge — "low" warning
NO_HOT_WATER_THRESHOLD: Final = 0.5  # % charge — "empty" warning


def is_advanced_mode(entry: ConfigEntry) -> bool:
    """Return True when the config entry is in Advanced experience mode."""
    return entry.options.get(CONF_EXPERIENCE_MODE, MODE_ADVANCED) == MODE_ADVANCED
