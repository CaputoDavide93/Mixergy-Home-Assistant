"""Tests for the Mixergy DataUpdateCoordinator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mixergy_tank.api import (
    MixergyAuthError,
    MixergyConnectionError,
    TankData,
    TankMeasurement,
)
from custom_components.mixergy_tank.const import (
    CONF_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
)
from custom_components.mixergy_tank.coordinator import MixergyCoordinator

from .conftest import MOCK_SERIAL


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


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    ((299, True), (301, False)),
)
async def test_report_freshness_uses_tank_timestamp(
    age_seconds: int, expected: bool
) -> None:
    """A successful cloud request must not disguise an old tank report."""
    from homeassistant.util import dt as dt_util

    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    data = TankData(
        measurement=TankMeasurement(received_time=now - timedelta(seconds=age_seconds))
    )
    client = AsyncMock()
    client.fetch_all = AsyncMock(return_value=data)
    coordinator = MixergyCoordinator(_make_hass(), client, _make_config_entry())

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(dt_util, "utcnow", lambda: now)
        result = await coordinator._async_update_data()

    assert result.measurement.report_is_fresh is expected


async def test_report_freshness_is_unknown_without_tank_timestamps() -> None:
    """Older tanks without report times retain backwards-compatible behaviour."""
    data = TankData(measurement=TankMeasurement())
    client = AsyncMock()
    client.fetch_all = AsyncMock(return_value=data)
    coordinator = MixergyCoordinator(_make_hass(), client, _make_config_entry())

    result = await coordinator._async_update_data()

    assert result.measurement.report_is_fresh is None


def test_default_poll_interval_is_inside_the_advertised_range() -> None:
    """The default must be selectable, and must not out-run the data source.

    The tank reports to the cloud at roughly 60 s, so a default below that
    polls faster than data can change — three requests per cycle for readings
    that cannot have moved. This pins the default against both the configurable
    bounds and the upstream cadence, so a future tweak cannot quietly
    reintroduce over-polling.
    """
    from custom_components.mixergy_tank.const import (
        MAX_UPDATE_INTERVAL,
        MIN_UPDATE_INTERVAL,
        UPDATE_INTERVAL,
    )

    assert MIN_UPDATE_INTERVAL <= UPDATE_INTERVAL <= MAX_UPDATE_INTERVAL
    assert UPDATE_INTERVAL >= 60, (
        "the cloud refreshes about once a minute; a faster default only "
        "multiplies requests without surfacing fresher data"
    )
