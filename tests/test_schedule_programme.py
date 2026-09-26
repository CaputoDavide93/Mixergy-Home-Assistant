"""The tank's own weekly programme, parsed read-only (issue #38).

The document shape follows a third-party capture of the schedule endpoint
(serialbandicoot/solar-flow-diverter ``mock_data/schedule.json``): lower-case
three-letter weekdays, ``HH:MM`` times, ``set`` as a charge percentage, and a
``maintain`` band. A live tank on its learned automatic schedule returned the
same keys with empty ``schedule`` and ``heatSourceSchedule`` arrays, so an
empty programme is a normal state, not an error.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.mixergy_tank.api import (
    ScheduledCharge,
    ScheduledHeatSource,
    TankData,
    TankInfo,
    TankSchedule,
)

from .test_api import _make_resp
from .test_api_writes import _write_client

LONDON = ZoneInfo("Europe/London")

CAPTURED_SCHEDULE = {
    "ignoreOffpeakSense": True,
    "defaultHeatSource": "indirect",
    "schedule": [
        {
            "days": ["mon", "tue", "wed", "thu", "sat", "sun"],
            "items": [
                {"set": 75, "time": "02:01", "maintain": {"off": 60, "on": 50}}
            ],
        }
    ],
    "heatSourceSchedule": [
        {"heatSource": "electric", "startTime": "01:00"},
        {"heatSource": "indirect", "startTime": "06:00"},
    ],
}

# What a live tank following its learned automatic schedule returned.
AUTO_SCHEDULE_DOCUMENT = {
    "defaultHeatSource": "indirect",
    "schedule": [],
    "heatSourceSchedule": [],
}


async def _fetch(session: MagicMock, document: dict) -> TankSchedule:
    session.request = AsyncMock(
        return_value=_make_resp(200, None, json.dumps(document))
    )
    return await _write_client(session).fetch_schedule()


async def test_captured_programme_parses(mock_aiohttp_session: MagicMock) -> None:
    schedule = await _fetch(mock_aiohttp_session, CAPTURED_SCHEDULE)

    assert schedule.charge_programme == (
        ScheduledCharge(
            days=("mon", "tue", "wed", "thu", "sat", "sun"),
            time="02:01",
            target_charge=75.0,
            maintain_on=50.0,
            maintain_off=60.0,
        ),
    )
    assert schedule.heat_source_programme == (
        ScheduledHeatSource(start_time="01:00", heat_source="electric"),
        ScheduledHeatSource(start_time="06:00", heat_source="indirect"),
    )
    # The verbatim document that writes round-trip is untouched by parsing.
    assert schedule.raw == CAPTURED_SCHEDULE


async def test_auto_schedule_has_an_empty_programme(
    mock_aiohttp_session: MagicMock,
) -> None:
    schedule = await _fetch(mock_aiohttp_session, AUTO_SCHEDULE_DOCUMENT)

    assert schedule.charge_programme == ()
    assert schedule.heat_source_programme == ()
    assert schedule.next_charge(datetime(2026, 9, 28, tzinfo=LONDON)) is None


async def test_documents_without_programme_keys_still_parse(
    mock_aiohttp_session: MagicMock,
) -> None:
    schedule = await _fetch(mock_aiohttp_session, {"defaultHeatSource": "electric"})
    assert schedule.charge_programme == ()
    assert schedule.heat_source_programme == ()


async def test_malformed_entries_are_skipped_not_fatal(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A schema surprise drops the entry; the poll and the rest survive."""
    document = {
        "defaultHeatSource": "electric",
        "schedule": [
            "not-a-block",
            {"days": "mon", "items": []},  # days not a list
            {"days": [0, 1, 2], "items": [{"time": "01:00"}]},  # ambiguous ints
            {"days": ["mon"], "items": "nope"},
            {
                "days": ["Monday", "FRI", "funday", None],
                "items": [
                    "not-an-item",
                    {"time": 130},  # not a string
                    {"time": "25:00"},
                    {"time": "7:5x"},
                    {"time": "01:02:03"},
                    {"time": "05:30", "set": 150, "maintain": "bad"},
                    {"time": "04:15", "set": True, "maintain": {"on": -1, "off": "x"}},
                    {"time": "23:00", "set": "80"},
                ],
            },
        ],
        "heatSourceSchedule": [
            "nope",
            {"heatSource": "solar", "startTime": "01:00"},
            {"heatSource": 3, "startTime": "01:00"},
            {"heatSource": "electric", "startTime": "late"},
            {"heatSource": " HeatPump ", "startTime": "22:00"},
        ],
    }
    schedule = await _fetch(mock_aiohttp_session, document)

    assert schedule.charge_programme == (
        ScheduledCharge(days=("mon", "fri"), time="01:02"),
        ScheduledCharge(days=("mon", "fri"), time="04:15"),
        ScheduledCharge(days=("mon", "fri"), time="05:30"),
        ScheduledCharge(days=("mon", "fri"), time="23:00", target_charge=80.0),
    )
    assert schedule.heat_source_programme == (
        ScheduledHeatSource(start_time="22:00", heat_source="heat_pump"),
    )


@pytest.mark.parametrize("value", ("not-a-list", {"days": ["mon"]}, None))
async def test_non_list_programmes_are_empty(
    mock_aiohttp_session: MagicMock, value: object
) -> None:
    document = {"schedule": value, "heatSourceSchedule": value}
    schedule = await _fetch(mock_aiohttp_session, document)
    assert schedule.charge_programme == ()
    assert schedule.heat_source_programme == ()


async def test_holiday_write_round_trips_the_programme_verbatim(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Reading the programme must not change what a write sends back."""
    existing = copy.deepcopy(CAPTURED_SCHEDULE)
    sent: list[dict] = []

    async def request(method, url, **kwargs):
        if method == "PUT":
            sent.append(kwargs["json"])
            return _make_resp(200, {})
        return _make_resp(200, None, json.dumps(existing))

    mock_aiohttp_session.request = AsyncMock(side_effect=request)
    client = _write_client(mock_aiohttp_session)

    await client.set_holiday_dates(
        datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC)
    )

    written = sent[0]
    for key in ("ignoreOffpeakSense", "schedule", "heatSourceSchedule"):
        assert written[key] == CAPTURED_SCHEDULE[key]


# ── next_charge ───────────────────────────────────────────────────────────────


def _schedule(*charges: ScheduledCharge) -> TankSchedule:
    return TankSchedule(charge_programme=charges)


NIGHTLY = ScheduledCharge(days=("mon", "tue", "wed", "thu", "sat", "sun"), time="02:01")


def test_next_charge_later_today() -> None:
    # Monday 28 September 2026, 01:00 local.
    now = datetime(2026, 9, 28, 1, 0, tzinfo=LONDON)
    when, charge = _schedule(NIGHTLY).next_charge(now)  # type: ignore[misc]
    assert when == datetime(2026, 9, 28, 2, 1, tzinfo=LONDON)
    assert charge is NIGHTLY


def test_next_charge_skips_days_outside_the_programme() -> None:
    # Thursday 03:00: Thursday's charge has passed and Friday is not listed.
    now = datetime(2026, 10, 1, 3, 0, tzinfo=LONDON)
    when, _ = _schedule(NIGHTLY).next_charge(now)  # type: ignore[misc]
    assert when == datetime(2026, 10, 3, 2, 1, tzinfo=LONDON)  # Saturday


def test_next_charge_is_strictly_after_now() -> None:
    now = datetime(2026, 9, 28, 2, 1, tzinfo=LONDON)
    when, _ = _schedule(NIGHTLY).next_charge(now)  # type: ignore[misc]
    assert when == datetime(2026, 9, 29, 2, 1, tzinfo=LONDON)


def test_next_charge_wraps_to_the_same_weekday_next_week() -> None:
    weekly = ScheduledCharge(days=("mon",), time="02:00")
    now = datetime(2026, 9, 28, 3, 0, tzinfo=LONDON)
    when, _ = _schedule(weekly).next_charge(now)  # type: ignore[misc]
    assert when == datetime(2026, 10, 5, 2, 0, tzinfo=LONDON)


def test_next_charge_picks_the_earliest_of_several() -> None:
    early = ScheduledCharge(days=("mon",), time="05:00", target_charge=40)
    late = ScheduledCharge(days=("mon",), time="23:00", target_charge=90)
    now = datetime(2026, 9, 28, 4, 0, tzinfo=LONDON)
    when, charge = _schedule(late, early).next_charge(now)  # type: ignore[misc]
    assert when.hour == 5
    assert charge is early


def test_next_charge_uses_wall_clock_across_a_dst_change() -> None:
    # UK clocks go back on Sunday 25 October 2026.
    now = datetime(2026, 10, 24, 12, 0, tzinfo=LONDON)
    when, _ = _schedule(NIGHTLY).next_charge(now)  # type: ignore[misc]
    assert (when.hour, when.minute) == (2, 1)
    assert when.utcoffset() == timedelta(0)


# ── Sensor ────────────────────────────────────────────────────────────────────


def _sensor(schedule: TankSchedule):
    from custom_components.mixergy_tank.sensor import (
        SENSOR_DESCRIPTIONS,
        MixergySensor,
    )

    coordinator = MagicMock()
    coordinator.data = TankData(info=TankInfo(serial_number="T1"), schedule=schedule)
    coordinator.last_update_success = True
    description = next(
        d for d in SENSOR_DESCRIPTIONS if d.key == "next_scheduled_charge"
    )
    return MixergySensor(coordinator, description)


def test_sensor_reports_the_next_charge_and_programme() -> None:
    charge = ScheduledCharge(
        days=("mon",), time="02:01", target_charge=75, maintain_on=50, maintain_off=60
    )
    schedule = TankSchedule(
        charge_programme=(charge,),
        heat_source_programme=(
            ScheduledHeatSource(start_time="01:00", heat_source="electric"),
        ),
    )
    now = datetime(2026, 9, 28, 1, 0, tzinfo=LONDON)
    with patch("custom_components.mixergy_tank.sensor.dt_util.now", return_value=now):
        sensor = _sensor(schedule)
        assert sensor.available is True
        assert sensor.native_value == datetime(2026, 9, 28, 2, 1, tzinfo=LONDON)
        assert sensor.extra_state_attributes == {
            "target_charge": 75,
            "maintain_on": 50,
            "maintain_off": 60,
            "programme": [
                {
                    "days": ["mon"],
                    "time": "02:01",
                    "target_charge": 75,
                    "maintain_on": 50,
                    "maintain_off": 60,
                }
            ],
            "heat_source_programme": [
                {"start_time": "01:00", "heat_source": "electric"}
            ],
        }


def test_sensor_is_unknown_without_a_programme() -> None:
    sensor = _sensor(TankSchedule())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {
        "target_charge": None,
        "maintain_on": None,
        "maintain_off": None,
        "programme": [],
        "heat_source_programme": [],
    }


# ── Diagnostics ───────────────────────────────────────────────────────────────


async def test_diagnostics_show_the_parsed_programme_and_raw_keys() -> None:
    from custom_components.mixergy_tank.coordinator import MixergyCoordinator
    from custom_components.mixergy_tank.diagnostics import (
        REDACTED,
        async_get_config_entry_diagnostics,
    )

    coordinator = MagicMock(spec=MixergyCoordinator)
    coordinator.data = TankData(
        schedule=TankSchedule(
            raw=CAPTURED_SCHEDULE,
            charge_programme=(NIGHTLY,),
        )
    )
    coordinator.update_interval = timedelta(seconds=60)
    coordinator.last_update_success = True
    entry = SimpleNamespace(data={}, options={}, runtime_data=coordinator)

    result = await async_get_config_entry_diagnostics(None, entry)  # type: ignore[arg-type]

    schedule = result["tank_data"]["schedule"]
    assert schedule["raw"] == REDACTED
    assert schedule["raw_keys"] == sorted(CAPTURED_SCHEDULE)
    assert schedule["charge_programme"][0]["time"] == "02:01"
