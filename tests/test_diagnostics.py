"""Tests for privacy-safe Mixergy diagnostics."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.mixergy.const import CONF_SERIAL_NUMBER
from custom_components.mixergy.coordinator import MixergyCoordinator
from custom_components.mixergy.diagnostics import REDACTED


@pytest.mark.asyncio
async def test_diagnostics_handles_entry_that_never_loaded() -> None:
    """Failed setup must still return redacted, actionable diagnostics."""
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    from custom_components.mixergy.diagnostics import async_get_config_entry_diagnostics

    entry = SimpleNamespace(
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_SERIAL_NUMBER: "TEST001",
        },
        options={"update_interval": 60},
    )

    diagnostics = await async_get_config_entry_diagnostics(None, entry)  # type: ignore[arg-type]

    assert diagnostics["config"] == {
        CONF_USERNAME: REDACTED,
        CONF_PASSWORD: REDACTED,
        CONF_SERIAL_NUMBER: REDACTED,
    }
    assert diagnostics["options"] == {"update_interval": 60}
    assert diagnostics["coordinator"] == {
        "loaded": False,
        "update_interval": None,
        "last_update_success": None,
    }
    assert diagnostics["tank_data"] is None


@pytest.mark.asyncio
async def test_loaded_diagnostics_redacts_tank_identifiers_and_schedule(
    mock_tank_data,
) -> None:
    """Loaded diagnostics must not expose customer-correlatable tank data."""
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

    from custom_components.mixergy.diagnostics import async_get_config_entry_diagnostics

    mock_tank_data.schedule.raw = {"private": "schedule"}
    coordinator = MagicMock(spec=MixergyCoordinator)
    coordinator.data = mock_tank_data
    coordinator.update_interval = timedelta(seconds=30)
    coordinator.last_update_success = True
    entry = SimpleNamespace(
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_SERIAL_NUMBER: "TEST001",
        },
        options={},
        runtime_data=coordinator,
    )

    diagnostics = await async_get_config_entry_diagnostics(None, entry)  # type: ignore[arg-type]

    assert diagnostics["coordinator"] == {
        "loaded": True,
        "update_interval": 30.0,
        "last_update_success": True,
    }
    assert diagnostics["tank_data"]["info"]["serial_number"] == REDACTED
    assert diagnostics["tank_data"]["schedule"]["raw"] == REDACTED
