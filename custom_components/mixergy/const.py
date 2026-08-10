"""Constants for the Mixergy integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

try:
    from homeassistant.const import UnitOfRatio
except ImportError:  # Home Assistant < 2026.7
    from homeassistant.const import PERCENTAGE as PERCENTAGE_UNIT
else:
    PERCENTAGE_UNIT = UnitOfRatio.PERCENTAGE

DOMAIN: Final = "mixergy"
MANUFACTURER: Final = "Mixergy Ltd"

# Config keys
CONF_SERIAL_NUMBER: Final = "serial_number"

# Options keys
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_EXPERIENCE_MODE: Final = "experience_mode"
CONF_LOW_WATER_THRESHOLD: Final = "low_water_threshold"
CONF_NO_WATER_THRESHOLD: Final = "no_water_threshold"
# Energy cost (per kWh) for the optional cost sensors
CONF_ELECTRIC_RATE: Final = "electric_rate"

# Experience mode values
MODE_SIMPLE: Final = "simple"
MODE_ADVANCED: Final = "advanced"

# Coordinator update interval (seconds).
# 30 s is the default; 30–300 s is the allowed range.
# Tank measurements update server-side at ~60 s cadence so values below
# 30 s waste API calls and risk rate-limit throttling on the cloud API.
UPDATE_INTERVAL: Final = 30
MIN_UPDATE_INTERVAL: Final = 30
MAX_UPDATE_INTERVAL: Final = 300

# Heat source options for the select entity (HA-facing format)
HEAT_SOURCE_OPTIONS: Final = ["electric", "indirect", "heat_pump"]

# Binary sensor thresholds for hot water level alerts
LOW_HOT_WATER_THRESHOLD: Final = 5    # % charge — "low" warning
NO_HOT_WATER_THRESHOLD: Final = 0.5  # % charge — "empty" warning


def is_advanced_mode(entry: ConfigEntry) -> bool:
    """Return True when the config entry is in Advanced experience mode.

    Defaults to Simple when the option is absent, matching the setup flow's
    default (config_flow STEP_EXPERIENCE_SCHEMA) so an entry missing the
    option never silently exposes the full advanced control surface.
    """
    return entry.options.get(CONF_EXPERIENCE_MODE, MODE_SIMPLE) == MODE_ADVANCED
