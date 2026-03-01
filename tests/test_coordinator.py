"""Tests for the Mixergy DataUpdateCoordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mixergy.api import (
    MixergyAuthError,
    MixergyConnectionError,
)
from custom_components.mixergy.const import (
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    UPDATE_INTERVAL,
)
from custom_components.mixergy.coordinator import MixergyCoordinator

from .conftest import MOCK_SERIAL, mock_tank_data


def _make_config_entry(options: dict | None = None) -> MagicMock:
    """Return a minimal mock config entry."""
    entry = MagicMock()
    entry.options = options or {}
    entry.data = {"serial_number": MOCK_SERIAL}
    return entry


def _make_hass() -> MagicMock:
    """Return a minimal mock HomeAssistant instance."""
    hass = MagicMock()
    hass.loop = MagicMock()
    return hass


# ── Interval configuration ────────────────────────────────────────────────────


def test_coordinator_uses_default_interval_when_no_options() -> None:
    """Coordinator falls back to UPDATE_INTERVAL when options are empty."""
    entry = _make_config_entry(options={})
    client = AsyncMock()
    coordinator = MixergyCoordinator(_make_hass(), client, entry)

    assert coordinator.update_interval == timedelta(seconds=UPDATE_INTERVAL)


def test_coordinator_respects_custom_interval() -> None:
    """Coordinator uses the value from config entry options."""
    entry = _make_config_entry(options={CONF_UPDATE_INTERVAL: 120})
    client = AsyncMock()
    coordinator = MixergyCoordinator(_make_hass(), client, entry)

    assert coordinator.update_interval == timedelta(seconds=120)


# ── Data refresh ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_update_data_calls_fetch_all(mock_tank_data) -> None:
    """_async_update_data delegates to client.fetch_all()."""
    entry = _make_config_entry()
    client = AsyncMock()
    client.fetch_all = AsyncMock(return_value=mock_tank_data)

    coordinator = MixergyCoordinator(_make_hass(), client, entry)
    result = await coordinator._async_update_data()

    client.fetch_all.assert_awaited_once()
    assert result is mock_tank_data


@pytest.mark.asyncio
async def test_async_update_data_raises_update_failed_on_connection_error(
    mock_tank_data,
) -> None:
    """MixergyConnectionError is wrapped in UpdateFailed."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    entry = _make_config_entry()
    client = AsyncMock()
    client.fetch_all = AsyncMock(side_effect=MixergyConnectionError("timed out"))

    coordinator = MixergyCoordinator(_make_hass(), client, entry)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_raises_config_entry_auth_failed_on_auth_error(
    mock_tank_data,
) -> None:
    """MixergyAuthError is wrapped in ConfigEntryAuthFailed."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    entry = _make_config_entry()
    client = AsyncMock()
    client.fetch_all = AsyncMock(side_effect=MixergyAuthError("token expired"))

    coordinator = MixergyCoordinator(_make_hass(), client, entry)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_update_data_stamps_last_update_time(mock_tank_data) -> None:
    """Successful update sets last_update_time on the returned TankData."""
    from datetime import datetime

    entry = _make_config_entry()
    client = AsyncMock()
    client.fetch_all = AsyncMock(return_value=mock_tank_data)

    coordinator = MixergyCoordinator(_make_hass(), client, entry)
    result = await coordinator._async_update_data()

    assert result.last_update_time is not None
    assert isinstance(result.last_update_time, datetime)
