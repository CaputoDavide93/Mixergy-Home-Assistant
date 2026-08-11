"""Tests for the API client's write surface.

The setters were almost entirely uncovered, which matters more than the line
count suggests: several of them silently clamp their argument to the range the
tank firmware accepts, so a caller passing an out-of-range value gets a
different value written than it asked for. Nothing pinned those bounds, and
nothing pinned that each setter writes its own settings key — a copy-paste
between the eight one-line wrappers would have been invisible.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mixergy_tank.api import (
    MixergyApiClient,
    MixergyApiError,
)

from .conftest import MOCK_PASSWORD, MOCK_SERIAL, MOCK_TOKEN, MOCK_USERNAME
from .test_api import _make_resp


def _write_client(session: MagicMock, status: int = 200) -> MixergyApiClient:
    """Return a client with discovery pre-primed so writes go straight out."""
    client = MixergyApiClient(
        session=session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    base = f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}"
    client._measurement_url = f"{base}/measurement"
    client._control_url = f"{base}/control"
    client._settings_url = f"{base}/settings"
    client._schedule_url = f"{base}/schedule"
    client._token = MOCK_TOKEN
    client._token_expiry = time.time() + 3600
    return client


def _capture(session: MagicMock, status: int = 200) -> list[dict]:
    """Record the JSON body of every request the client makes."""
    sent: list[dict] = []

    async def request(method, url, **kwargs):
        if kwargs.get("json") is not None:
            sent.append(kwargs["json"])
        return _make_resp(status, {})

    session.request = AsyncMock(side_effect=request)
    return sent


# ── Settings setters ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "arg", "expected_key", "expected_value"),
    (
        ("set_dsr_enabled", True, "dsr_enabled", True),
        ("set_dsr_enabled", False, "dsr_enabled", False),
        ("set_frost_protection_enabled", True, "frost_protection_enabled", True),
        (
            "set_distributed_computing_enabled",
            True,
            "distributed_computing_enabled",
            True,
        ),
        ("set_divert_exported_enabled", True, "divert_exported_enabled", True),
    ),
)
async def test_boolean_setters_write_their_own_key(
    mock_aiohttp_session: MagicMock,
    method: str,
    arg: bool,
    expected_key: str,
    expected_value: bool,
) -> None:
    """Each boolean setter must write its own settings key, not a neighbour's."""
    sent = _capture(mock_aiohttp_session)
    client = _write_client(mock_aiohttp_session)

    await getattr(client, method)(arg)

    assert sent == [{expected_key: expected_value}]


@pytest.mark.parametrize(
    ("method", "key", "given", "written"),
    (
        # (value below range, clamped up) and (above range, clamped down)
        ("set_cleansing_temperature", "cleansing_temperature", 10, 51),
        ("set_cleansing_temperature", "cleansing_temperature", 99, 55),
        ("set_cleansing_temperature", "cleansing_temperature", 53, 53),
        ("set_pv_cut_in_threshold", "pv_cut_in_threshold", -50, 0),
        ("set_pv_cut_in_threshold", "pv_cut_in_threshold", 9999, 500),
        ("set_pv_charge_limit", "pv_charge_limit", -1, 0),
        ("set_pv_charge_limit", "pv_charge_limit", 250, 100),
        ("set_pv_target_current", "pv_target_current", -5.0, -1.0),
        ("set_pv_target_current", "pv_target_current", 5.0, 0.0),
        ("set_pv_over_temperature", "pv_over_temperature", 1, 45),
        ("set_pv_over_temperature", "pv_over_temperature", 100, 60),
    ),
)
async def test_numeric_setters_clamp_to_firmware_range(
    mock_aiohttp_session: MagicMock,
    method: str,
    key: str,
    given: float,
    written: float,
) -> None:
    """Out-of-range values are clamped, not rejected — pin the actual bounds.

    Clamping silently changes the caller's value, so the bounds are part of the
    contract: widening one by accident would let an out-of-spec value reach the
    tank, and narrowing one would quietly cap a legitimate setting.
    """
    sent = _capture(mock_aiohttp_session)
    client = _write_client(mock_aiohttp_session)

    await getattr(client, method)(given)

    assert sent == [{key: written}]


async def test_set_setting_raises_on_non_200(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A rejected write must raise rather than appear to succeed."""
    _capture(mock_aiohttp_session, status=500)
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(MixergyApiError, match="Set setting"):
        await client.set_dsr_enabled(True)


async def test_failed_setter_names_the_setting(
    mock_aiohttp_session: MagicMock,
) -> None:
    """The error names the key, so a multi-write failure is diagnosable.

    Uses 500 rather than 401/403: those are claimed by the reauth wrapper
    before the setter's own error branch is reached, which is its own
    behaviour and covered separately.
    """
    _capture(mock_aiohttp_session, status=500)
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(MixergyApiError, match="pv_charge_limit"):
        await client.set_pv_charge_limit(50)


# ── Control setters ───────────────────────────────────────────────────────────


async def test_set_target_charge_writes_control_endpoint(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Target charge goes to the control endpoint, not settings."""
    urls: list[str] = []

    async def request(method, url, **kwargs):
        urls.append(url)
        return _make_resp(200, {})

    mock_aiohttp_session.request = AsyncMock(side_effect=request)
    client = _write_client(mock_aiohttp_session)

    await client.set_target_charge(60)

    assert urls and urls[0].endswith("/control")


async def test_set_target_charge_raises_on_non_200(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A rejected charge write must raise."""
    _capture(mock_aiohttp_session, status=502)
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(MixergyApiError):
        await client.set_target_charge(60)


async def test_set_target_temperature_raises_on_non_200(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A rejected temperature write must raise."""
    _capture(mock_aiohttp_session, status=502)
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(MixergyApiError):
        await client.set_target_temperature(55)


# ── Holiday schedule ──────────────────────────────────────────────────────────


async def test_clear_holiday_dates_removes_only_the_holiday_key(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Clearing holiday must preserve the rest of the schedule.

    The schedule is read-modify-written, so dropping unrelated keys here would
    silently wipe the user's heating schedule as a side effect of cancelling
    a holiday.
    """
    existing = {
        "holiday": {"start": "2026-01-01", "end": "2026-01-08"},
        "defaultHeatSource": "electric",
        "weekly": {"monday": ["06:00"]},
    }
    sent: list[dict] = []

    async def request(method, url, **kwargs):
        if method == "PUT":
            sent.append(kwargs["json"])
            return _make_resp(200, {})
        return _make_resp(200, None, __import__("json").dumps(existing))

    mock_aiohttp_session.request = AsyncMock(side_effect=request)
    client = _write_client(mock_aiohttp_session)

    await client.clear_holiday_dates()

    assert sent, "no schedule write was made"
    written = sent[0]
    assert "holiday" not in written
    assert written["defaultHeatSource"] == "electric"
    assert written["weekly"] == {"monday": ["06:00"]}


async def test_clear_holiday_dates_raises_on_non_200(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A rejected schedule write must raise."""

    async def request(method, url, **kwargs):
        if method == "PUT":
            return _make_resp(500, {})
        return _make_resp(200, None, "{}")

    mock_aiohttp_session.request = AsyncMock(side_effect=request)
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(MixergyApiError, match="Clear holiday dates"):
        await client.clear_holiday_dates()


async def test_set_holiday_dates_raises_on_non_200(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A rejected holiday write must raise."""

    async def request(method, url, **kwargs):
        if method == "PUT":
            return _make_resp(500, {})
        return _make_resp(200, None, "{}")

    mock_aiohttp_session.request = AsyncMock(side_effect=request)
    client = _write_client(mock_aiohttp_session)

    start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    end = datetime(2026, 6, 8, 9, 0, tzinfo=UTC)

    with pytest.raises(MixergyApiError, match="Set holiday dates"):
        await client.set_holiday_dates(start, end)


# ── Fetch error branches and defensive fallbacks ──────────────────────────────
#
# Every fetch checks its HTTP status and every parse tolerates a missing or
# wrong-typed field. Uncovered, none of that was pinned: an upstream that
# starts omitting firmwareVersion, or returns 503 on one endpoint, must degrade
# predictably rather than surfacing an AttributeError from deep in the client.


@pytest.mark.parametrize(
    ("method", "url_attr", "match"),
    (
        ("fetch_measurement", "_measurement_url", "Measurement fetch failed"),
        ("fetch_settings", "_settings_url", "Settings fetch failed"),
        ("fetch_schedule", "_schedule_url", "Schedule fetch failed"),
    ),
)
async def test_fetch_raises_on_non_200(
    mock_aiohttp_session: MagicMock, method: str, url_attr: str, match: str
) -> None:
    """A failed fetch must raise a typed error naming the endpoint."""
    mock_aiohttp_session.request = AsyncMock(return_value=_make_resp(503, {}))
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(MixergyApiError, match=match):
        await getattr(client, method)()


async def test_request_with_reauth_rejects_one_shot_bodies(
    mock_aiohttp_session: MagicMock,
) -> None:
    """`data=` is refused because the 401 retry replays kwargs verbatim.

    A stream passed as `data=` would be exhausted by the first attempt and the
    retry would silently send an empty body, so misuse is made loud.
    """
    client = _write_client(mock_aiohttp_session)

    with pytest.raises(TypeError, match="json=<dict>"):
        await client._request_with_reauth(
            "PUT", "https://www.mixergy.io/api/v2/x", data=b"raw"
        )


async def test_missing_firmware_and_model_fall_back_to_placeholders(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Absent or wrong-typed metadata must not break discovery.

    These feed the device registry; a non-string slipping through would raise
    while HA builds the device entry, taking the whole integration down over a
    cosmetic field.
    """
    import json as _json

    base = f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}"
    tanks = {
        "_embedded": {
            "tankList": [
                {
                    "serialNumber": MOCK_SERIAL,
                    "firmwareVersion": 12345,  # not a string
                    "_links": {"self": {"href": base}},
                }
            ]
        }
    }
    detail = {
        "tankModelCode": None,  # not a string
        "configuration": _json.dumps({"mixergyPvType": "NO_INVERTER"}),
        "_links": {
            "latest_measurement": {"href": f"{base}/measurement"},
            "control": {"href": f"{base}/control"},
            "settings": {"href": f"{base}/settings"},
            "schedule": {"href": f"{base}/schedule"},
        },
    }

    def get_side_effect(url, **kwargs):
        if url.endswith("/api/v2"):
            return _make_resp(200, {
                "_links": {
                    "account": {"href": "https://www.mixergy.io/api/v2/account"},
                    "tanks": {"href": "https://www.mixergy.io/api/v2/tanks"},
                }
            })
        if url.endswith("/account"):
            return _make_resp(200, {
                "_links": {
                    "login": {"href": "https://www.mixergy.io/api/v2/login"}
                }
            })
        if url.endswith("/tanks"):
            return _make_resp(200, tanks)
        return _make_resp(200, detail)

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    client._token = MOCK_TOKEN
    client._token_expiry = time.time() + 3600

    await client._discover_tank()

    assert client.tank_info.firmware_version == "0.0.0"
    assert client.tank_info.model_code == "Unknown"


async def test_measurement_parses_pv_and_clamp_when_present(
    mock_aiohttp_session: MagicMock,
) -> None:
    """PV energy is joules/minute and must be converted, not passed through."""
    payload = {
        "topTemperature": 50.0,
        "bottomTemperature": 15.0,
        "charge": 40.0,
        "pvEnergy": 60000.0,  # 1 kW once converted
        "clampPower": 275.0,
    }
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, payload)
    )
    client = _write_client(mock_aiohttp_session)

    measurement = await client.fetch_measurement()

    assert measurement.pv_power_kw == 1.0
    assert measurement.clamp_power_w == 275.0


def test_require_array_rejects_a_non_list() -> None:
    """Schema faults stay typed rather than escaping as TypeError."""
    from custom_components.mixergy_tank.api import (
        MixergyConnectionError,
        _require_array,
    )

    assert _require_array([1, 2], "ctx") == [1, 2]
    with pytest.raises(MixergyConnectionError, match="not a JSON array"):
        _require_array({"not": "a list"}, "ctx")


@pytest.mark.parametrize(
    ("value", "expected"),
    ((1, True), (0, False), (True, True), ("true", True), ("0", False)),
)
def test_as_bool_accepts_the_encodings_the_api_actually_sends(
    value: object, expected: bool
) -> None:
    """The cloud mixes bools, 0/1 and strings for the same setting."""
    from custom_components.mixergy_tank.api import _as_bool

    assert _as_bool(value) is expected


# ── Token lifecycle ───────────────────────────────────────────────────────────
#
# The TTL is taken from the API but deliberately not trusted. A zero, negative
# or non-numeric TTL would either crash the expiry arithmetic or mark the token
# instantly stale, forcing a login on every single request and risking API
# throttling — a failure that looks like a mysterious outage, not a bad field.


@pytest.mark.parametrize(
    "bad_ttl", (0, -1, "3600", None, float("nan"), float("inf"), True),
)
async def test_untrustworthy_ttl_falls_back_to_the_default(
    mock_aiohttp_session: MagicMock, bad_ttl: object
) -> None:
    """A non-positive or non-numeric TTL must not reach the expiry maths."""
    from custom_components.mixergy_tank.api import (
        DEFAULT_TOKEN_TTL,
        TOKEN_REFRESH_BUFFER,
    )

    mock_aiohttp_session.post = MagicMock(
        return_value=_make_resp(201, {"token": "tok", "ttl": bad_ttl})
    )
    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    client._login_url = "https://www.mixergy.io/api/v2/login"

    before = time.time()
    assert await client.authenticate() is True

    expected = max(DEFAULT_TOKEN_TTL, TOKEN_REFRESH_BUFFER * 2)
    assert client._token_expiry >= before + expected - 5


async def test_short_ttl_is_raised_above_the_refresh_buffer(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A TTL under the refresh buffer would re-login on every request."""
    from custom_components.mixergy_tank.api import TOKEN_REFRESH_BUFFER

    mock_aiohttp_session.post = MagicMock(
        return_value=_make_resp(201, {"token": "tok", "ttl": 5})
    )
    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    client._login_url = "https://www.mixergy.io/api/v2/login"

    before = time.time()
    await client.authenticate()

    assert client._token_expiry >= before + TOKEN_REFRESH_BUFFER * 2 - 5


@pytest.mark.parametrize("status", (401, 403))
async def test_rejected_credentials_raise_auth_error(
    mock_aiohttp_session: MagicMock, status: int
) -> None:
    """401 and 403 both mean 'bad credentials', not 'try again later'."""
    from custom_components.mixergy_tank.api import MixergyAuthError

    mock_aiohttp_session.post = MagicMock(return_value=_make_resp(status))
    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password="wrong",
        serial_number=MOCK_SERIAL,
    )
    client._login_url = "https://www.mixergy.io/api/v2/login"

    with pytest.raises(MixergyAuthError, match="Invalid username or password"):
        await client.authenticate()


async def test_unexpected_login_status_raises_auth_error(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Any non-201 login response is an auth failure, not a silent success."""
    from custom_components.mixergy_tank.api import MixergyAuthError

    mock_aiohttp_session.post = MagicMock(return_value=_make_resp(500))
    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    client._login_url = "https://www.mixergy.io/api/v2/login"

    with pytest.raises(MixergyAuthError, match="status 500"):
        await client.authenticate()


@pytest.mark.parametrize("token", (None, "", 12345))
async def test_missing_or_wrong_typed_token_is_rejected(
    mock_aiohttp_session: MagicMock, token: object
) -> None:
    """A 201 without a usable token must fail loudly, not store junk."""
    from custom_components.mixergy_tank.api import MixergyAuthError

    mock_aiohttp_session.post = MagicMock(
        return_value=_make_resp(201, {"token": token})
    )
    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    client._login_url = "https://www.mixergy.io/api/v2/login"

    with pytest.raises(MixergyAuthError, match="valid token"):
        await client.authenticate()


# ── Measurement state parsing ─────────────────────────────────────────────────
#
# The tank reports which element is selected and whether it is currently drawing
# power as two separate fields, and the parser fans them out into per-source
# booleans. Only the electric path had coverage, so a wrong branch for indirect
# or heat-pump would have shown the wrong element heating on the dashboard.


@pytest.mark.parametrize(
    ("api_source", "expected_attr"),
    (
        ("indirect", "indirect_heat_source"),
        ("electric", "electric_heat_source"),
        ("heatpump", "heatpump_heat_source"),
    ),
)
@pytest.mark.parametrize("immersion", ("on", "off"))
async def test_each_heat_source_sets_only_its_own_flag(
    mock_aiohttp_session: MagicMock,
    api_source: str,
    expected_attr: str,
    immersion: str,
) -> None:
    """A selected source must set its own flag and leave the others alone.

    is_heating follows the immersion field, not the selection — a tank can have
    electric selected while idle, so the two must not be conflated.
    """
    import json as _json

    payload = {
        "topTemperature": 50.0,
        "bottomTemperature": 15.0,
        "charge": 40.0,
        "state": _json.dumps({
            "current": {
                "source": "Schedule",
                "heat_source": api_source,
                "immersion": immersion,
            }
        }),
    }
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, payload)
    )
    client = _write_client(mock_aiohttp_session)

    measurement = await client.fetch_measurement()
    heating = immersion == "on"

    assert getattr(measurement, expected_attr) is heating
    assert measurement.is_heating is heating

    others = {
        "indirect_heat_source",
        "electric_heat_source",
        "heatpump_heat_source",
    } - {expected_attr}
    for attr in others:
        assert getattr(measurement, attr) is False, f"{attr} leaked"


async def test_unknown_heat_source_falls_back_to_none(
    mock_aiohttp_session: MagicMock,
) -> None:
    """An unrecognised source must not leave a stale active source."""
    import json as _json

    from custom_components.mixergy_tank.api import HeatSource

    payload = {
        "charge": 40.0,
        "state": _json.dumps({
            "current": {"source": "Schedule", "heat_source": "fusion"}
        }),
    }
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, payload)
    )
    client = _write_client(mock_aiohttp_session)

    measurement = await client.fetch_measurement()
    assert measurement.active_heat_source == HeatSource.NONE


async def test_null_heat_source_and_immersion_do_not_crash(
    mock_aiohttp_session: MagicMock,
) -> None:
    """An explicit null must be tolerated, not just an absent key.

    ``.get(key, default)`` only substitutes when the key is *missing*, so a
    present-but-null value would reach ``.lower()`` and raise. The parser uses
    ``or`` for exactly this; pin it.
    """
    import json as _json

    payload = {
        "charge": 40.0,
        "state": _json.dumps({
            "current": {
                "source": "Schedule",
                "heat_source": None,
                "immersion": None,
            }
        }),
    }
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, payload)
    )
    client = _write_client(mock_aiohttp_session)

    measurement = await client.fetch_measurement()
    assert measurement.is_heating is False


async def test_vacation_source_marks_holiday_and_skips_heat_parsing(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Holiday mode is reported through the same source field."""
    import json as _json

    payload = {
        "charge": 40.0,
        "state": _json.dumps({
            "current": {
                "source": "Vacation",
                "heat_source": "electric",
                "immersion": "on",
            }
        }),
    }
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, payload)
    )
    client = _write_client(mock_aiohttp_session)

    measurement = await client.fetch_measurement()
    assert measurement.in_holiday_mode is True
    # Heat parsing is skipped in holiday mode, so no element reports heating.
    assert measurement.is_heating is False


async def test_unparsable_state_json_degrades_without_raising(
    mock_aiohttp_session: MagicMock,
) -> None:
    """A malformed state blob must not fail the whole measurement fetch."""
    payload = {"charge": 40.0, "topTemperature": 50.0, "state": "not json"}
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, payload)
    )
    client = _write_client(mock_aiohttp_session)

    measurement = await client.fetch_measurement()
    assert measurement.charge == 40.0


# ── Holiday schedule parsing ──────────────────────────────────────────────────


async def test_holiday_dates_parse_from_millisecond_timestamps(
    mock_aiohttp_session: MagicMock,
) -> None:
    """The API sends epoch milliseconds; treating them as seconds is 50k years out."""
    import json as _json

    depart = 1_780_000_000_000
    ret = 1_780_600_000_000
    body = _json.dumps({
        "defaultHeatSource": "electric",
        "holiday": {"departDate": depart, "returnDate": ret},
    })
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, None, body)
    )
    client = _write_client(mock_aiohttp_session)

    schedule = await client.fetch_schedule()

    assert schedule.holiday_start == datetime.fromtimestamp(
        depart / 1000, tz=UTC
    )
    assert schedule.holiday_end == datetime.fromtimestamp(
        ret / 1000, tz=UTC
    )


@pytest.mark.parametrize(
    "holiday",
    (
        "a string",                       # schema change
        ["a", "list"],                    # schema change
        {"departDate": "not-a-number"},   # wrong type
        {"departDate": None},             # explicit null
        {},                               # empty
    ),
)
async def test_malformed_holiday_block_is_tolerated(
    mock_aiohttp_session: MagicMock, holiday: object
) -> None:
    """A schema change in `holiday` must not raise out of the coordinator."""
    import json as _json

    body = _json.dumps({"defaultHeatSource": "electric", "holiday": holiday})
    mock_aiohttp_session.request = AsyncMock(
        return_value=_make_resp(200, None, body)
    )
    client = _write_client(mock_aiohttp_session)

    schedule = await client.fetch_schedule()
    assert schedule.holiday_start is None


# ── Connection tests force re-discovery ───────────────────────────────────────


async def test_test_credentials_forces_a_fresh_login(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Reauth must not silently pass on a cached token from the old password.

    Without invalidating first, a still-valid token would make any password —
    including the wrong one — appear to authenticate.
    """
    client = _write_client(mock_aiohttp_session)
    client._login_url = "https://www.mixergy.io/api/v2/login"
    mock_aiohttp_session.post = MagicMock(
        return_value=_make_resp(201, {"token": "fresh", "ttl": 3600})
    )

    assert await client.test_credentials() is True
    assert client._token == "fresh"
    mock_aiohttp_session.post.assert_called()


async def test_test_connection_forces_tank_rediscovery(
    mock_aiohttp_session: MagicMock,
) -> None:
    """The serial check must re-walk discovery, not trust cached URLs."""
    client = _write_client(mock_aiohttp_session)
    assert client._measurement_url is not None

    called: list[str] = []

    async def rediscover():
        called.append("discover")
        client._measurement_url = "https://www.mixergy.io/api/v2/x/measurement"

    client._discover_tank = rediscover

    assert await client.test_connection() is True
    assert called == ["discover"]
