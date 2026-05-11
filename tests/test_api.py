"""Tests for the Mixergy API client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mixergy.api import (
    HeatSource,
    MixergyApiClient,
    MixergyAuthError,
    MixergyConnectionError,
    MixergyTankNotFoundError,
    TankData,
    TankMeasurement,
    TankSettings,
)

from .conftest import (
    MOCK_LOGIN_RESPONSE,
    MOCK_PASSWORD,
    MOCK_SERIAL,
    MOCK_TOKEN,
    MOCK_USERNAME,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_resp(status: int = 200, json_data=None, text_data: str | None = None):
    """Build a context-manager-compatible mock response."""
    resp = AsyncMock()
    resp.status = status
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    resp.release = AsyncMock()
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    if text_data is not None:
        resp.text = AsyncMock(return_value=text_data)
    return resp


def _make_login_post():
    """Return an async post side_effect that always returns a 201 login response."""
    def post_side_effect(url, **kwargs):
        return _make_resp(201, MOCK_LOGIN_RESPONSE)
    return post_side_effect


# ── Authentication ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authenticate_success(api_client: MixergyApiClient) -> None:
    """Token is stored after successful authentication."""
    result = await api_client.authenticate()
    assert result is True
    assert api_client._token == MOCK_TOKEN


@pytest.mark.asyncio
async def test_authenticate_invalid_credentials(
    mock_aiohttp_session: MagicMock,
) -> None:
    """MixergyAuthError is raised on 401 response."""
    def post_401(url, **kwargs):
        return _make_resp(401)

    mock_aiohttp_session.post = MagicMock(side_effect=post_401)

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password="wrong",
        serial_number=MOCK_SERIAL,
    )
    with pytest.raises(MixergyAuthError):
        await client.authenticate()


@pytest.mark.asyncio
async def test_token_not_refreshed_when_valid(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """A valid token is reused without a new login request."""
    await api_client.authenticate()
    initial_call_count = mock_aiohttp_session.post.call_count

    # Second call should not trigger a new POST /login
    await api_client.authenticate()
    assert mock_aiohttp_session.post.call_count == initial_call_count


@pytest.mark.asyncio
async def test_invalidate_token_forces_reauth(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """After invalidation, the next authenticate() POSTs to /login again."""
    await api_client.authenticate()
    initial_call_count = mock_aiohttp_session.post.call_count

    api_client.invalidate_token()
    await api_client.authenticate()
    assert mock_aiohttp_session.post.call_count == initial_call_count + 1


# ── Data Fetching ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_measurement_returns_correct_values(
    api_client: MixergyApiClient,
) -> None:
    """fetch_measurement parses top/bottom temperature and charge correctly."""
    measurement = await api_client.fetch_measurement()

    assert isinstance(measurement, TankMeasurement)
    assert measurement.hot_water_temperature == 65.5
    assert measurement.coldest_water_temperature == 20.3
    assert measurement.charge == 80.0


@pytest.mark.asyncio
async def test_fetch_measurement_heat_source_electric_on(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Electric heat source and immersion=on sets is_heating correctly."""
    from .conftest import (
        MOCK_ACCOUNT_RESPONSE,
        MOCK_ROOT_RESPONSE,
        MOCK_TANK_DETAIL_RESPONSE,
        MOCK_TANKS_RESPONSE,
    )

    payload = {
        "topTemperature": 50.0,
        "bottomTemperature": 15.0,
        "charge": 40.0,
        "state": json.dumps({
            "current": {
                "target": 100,
                "source": "Schedule",
                "heat_source": "electric",
                "immersion": "on",
            }
        }),
    }

    # session.get is used as ``async with session.get(url) as resp`` (no await),
    # so the side_effect must be a sync function returning the response directly.
    def get_side_effect(url, **kwargs):
        if url.endswith("/api/v2"):
            return _make_resp(200, MOCK_ROOT_RESPONSE)
        if url.endswith("/account"):
            return _make_resp(200, MOCK_ACCOUNT_RESPONSE)
        if url.endswith("/tanks"):
            return _make_resp(200, MOCK_TANKS_RESPONSE)
        if url.endswith(MOCK_SERIAL):
            return _make_resp(200, MOCK_TANK_DETAIL_RESPONSE)
        if "measurement" in url:
            return _make_resp(200, payload)
        return _make_resp(404)

    # session.request is used as ``resp = await session.request(...)`` so it
    # must be an AsyncMock whose side_effect is an async function.
    async def request_side_effect(method, url, **kwargs):
        if method.upper() == "GET":
            return get_side_effect(url, **kwargs)
        return _make_resp(200)

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
    mock_aiohttp_session.post = MagicMock(side_effect=_make_login_post())
    mock_aiohttp_session.request = AsyncMock(side_effect=request_side_effect)

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    measurement = await client.fetch_measurement()

    assert measurement.electric_heat_source is True
    assert measurement.is_heating is True
    assert measurement.active_heat_source == HeatSource.ELECTRIC


@pytest.mark.asyncio
async def test_fetch_settings_returns_correct_values(
    api_client: MixergyApiClient,
) -> None:
    """fetch_settings parses max_temp and boolean flags correctly."""
    settings = await api_client.fetch_settings()

    assert isinstance(settings, TankSettings)
    assert settings.target_temperature == 60.0
    assert settings.frost_protection_enabled is True
    assert settings.dsr_enabled is False


@pytest.mark.asyncio
async def test_fetch_all_returns_tank_data(
    api_client: MixergyApiClient,
) -> None:
    """fetch_all bundles all three sub-fetches into a TankData."""
    data = await api_client.fetch_all()

    assert isinstance(data, TankData)
    assert data.info.serial_number == MOCK_SERIAL
    assert data.info.model_code == "MIXERGY-180"
    assert data.measurement.charge == 80.0
    assert data.settings.target_temperature == 60.0
    assert data.schedule.default_heat_source == "electric"


@pytest.mark.asyncio
async def test_tank_not_found_raises_error(
    mock_aiohttp_session: MagicMock,
) -> None:
    """MixergyTankNotFoundError is raised when serial number does not match."""
    from .conftest import MOCK_ACCOUNT_RESPONSE, MOCK_ROOT_RESPONSE

    wrong_tanks = {
        "_embedded": {
            "tankList": [
                {
                    "serialNumber": "OTHERSERIAL",
                    "firmwareVersion": "1.0.0",
                    "_links": {"self": {"href": "https://www.mixergy.io/api/v2/tank/OTHERSERIAL"}},
                }
            ]
        }
    }

    def get_side_effect(url, **kwargs):
        if url.endswith("/api/v2"):
            return _make_resp(200, MOCK_ROOT_RESPONSE)
        if url.endswith("/account"):
            return _make_resp(200, MOCK_ACCOUNT_RESPONSE)
        if url.endswith("/tanks"):
            return _make_resp(200, wrong_tanks)
        return _make_resp(404)

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
    mock_aiohttp_session.post = MagicMock(side_effect=_make_login_post())

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number="NOTFOUND",
    )
    with pytest.raises(MixergyTankNotFoundError):
        await client._discover_tank()


# ── Write Operations ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_target_charge_clamps_value(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """set_target_charge clamps values to 0–100 before sending."""
    # Ensure the client is initialised (discovers tank URLs)
    await api_client.fetch_all()

    put_calls: list = []

    async def request_side_effect(method, url, **kwargs):
        if method.upper() == "PUT":
            put_calls.append(kwargs.get("json", {}))
        return _make_resp(200)

    mock_aiohttp_session.request = AsyncMock(side_effect=request_side_effect)

    await api_client.set_target_charge(150)  # Should be clamped to 100
    assert any(c.get("charge") == 100 for c in put_calls)


@pytest.mark.asyncio
async def test_set_target_temperature_clamps_value(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """set_target_temperature clamps values to 45–70 before sending."""
    await api_client.fetch_all()

    put_calls: list = []

    async def request_side_effect(method, url, **kwargs):
        if method.upper() == "PUT":
            put_calls.append(kwargs.get("json", {}))
        return _make_resp(200)

    mock_aiohttp_session.request = AsyncMock(side_effect=request_side_effect)

    await api_client.set_target_temperature(100)  # Should be clamped to 70
    assert any(c.get("max_temp") == 70 for c in put_calls)


# ── Heat source normalisation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_schedule_normalises_heatpump_to_heat_pump(
    mock_aiohttp_session: MagicMock,
) -> None:
    """fetch_schedule normalises API "heatpump" → HA "heat_pump"."""
    from .conftest import (
        MOCK_ACCOUNT_RESPONSE,
        MOCK_MEASUREMENT_RESPONSE,
        MOCK_ROOT_RESPONSE,
        MOCK_SERIAL,
        MOCK_TANK_DETAIL_RESPONSE,
        MOCK_TANKS_RESPONSE,
    )

    schedule_with_heatpump = '{"defaultHeatSource": "heatpump"}'

    def get_side_effect(url, **kwargs):
        if url.endswith("/api/v2"):
            return _make_resp(200, MOCK_ROOT_RESPONSE)
        if url.endswith("/account"):
            return _make_resp(200, MOCK_ACCOUNT_RESPONSE)
        if url.endswith("/tanks"):
            return _make_resp(200, MOCK_TANKS_RESPONSE)
        if url.endswith(MOCK_SERIAL):
            return _make_resp(200, MOCK_TANK_DETAIL_RESPONSE)
        if "measurement" in url:
            return _make_resp(200, MOCK_MEASUREMENT_RESPONSE)
        # For any other URL (settings, schedule), return appropriate defaults
        return _make_resp(200, None, "{}")

    async def request_side_effect(method, url, **kwargs):
        if method.upper() == "GET":
            if "schedule" in url:
                return _make_resp(200, None, schedule_with_heatpump)
            return get_side_effect(url, **kwargs)
        return _make_resp(200)

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
    mock_aiohttp_session.post = MagicMock(side_effect=_make_login_post())
    mock_aiohttp_session.request = AsyncMock(side_effect=request_side_effect)

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    schedule = await client.fetch_schedule()

    assert schedule.default_heat_source == "heat_pump"


@pytest.mark.asyncio
async def test_set_default_heat_source_sends_heatpump_to_api(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """set_default_heat_source normalises "heat_pump" → "heatpump" in the PUT body."""
    await api_client.fetch_all()

    put_bodies: list = []

    async def request_side_effect(method, url, **kwargs):
        if method.upper() == "GET" and "schedule" in url:
            return _make_resp(200, None, '{"defaultHeatSource": "electric"}')
        if method.upper() == "PUT":
            put_bodies.append(kwargs.get("json", {}))
        return _make_resp(200)

    mock_aiohttp_session.request = AsyncMock(side_effect=request_side_effect)
    await api_client.set_default_heat_source("heat_pump")

    # Find the PUT that updated defaultHeatSource
    heat_source_calls = [b for b in put_bodies if "defaultHeatSource" in b]
    assert heat_source_calls, "No PUT call contained 'defaultHeatSource'"
    assert heat_source_calls[-1]["defaultHeatSource"] == "heatpump"


# ── HATEOAS link validation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_hateoas_link_raises_connection_error(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Missing HATEOAS link in tank detail raises MixergyConnectionError."""
    from .conftest import (
        MOCK_ACCOUNT_RESPONSE,
        MOCK_ROOT_RESPONSE,
        MOCK_SERIAL,
        MOCK_TANKS_RESPONSE,
    )

    # Detail response without the 'latest_measurement' link
    broken_detail = {
        "tankModelCode": "MIXERGY-180",
        "configuration": '{}',
        "_links": {
            "control": {"href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/control"},
            "settings": {"href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/settings"},
            "schedule": {"href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/schedule"},
            # 'latest_measurement' intentionally absent
        },
    }

    def get_side_effect(url, **kwargs):
        if url.endswith("/api/v2"):
            return _make_resp(200, MOCK_ROOT_RESPONSE)
        if url.endswith("/account"):
            return _make_resp(200, MOCK_ACCOUNT_RESPONSE)
        if url.endswith("/tanks"):
            return _make_resp(200, MOCK_TANKS_RESPONSE)
        if url.endswith(MOCK_SERIAL):
            return _make_resp(200, broken_detail)
        return _make_resp(404)

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
    mock_aiohttp_session.post = MagicMock(side_effect=_make_login_post())

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    with pytest.raises(MixergyConnectionError, match="Missing required API link"):
        await client._discover_tank()


# ── Timeout ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_passes_timeout(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """Every authenticated request passes REQUEST_TIMEOUT to the session."""
    from custom_components.mixergy.api import REQUEST_TIMEOUT

    # Trigger a request
    await api_client.fetch_all()

    # Check that the 'request' calls all included a timeout kwarg
    for call in mock_aiohttp_session.request.call_args_list:
        _, kwargs = call
        assert "timeout" in kwargs, "request() called without timeout"
        assert kwargs["timeout"] is REQUEST_TIMEOUT


# ── Concurrency: auth lock + discover lock ────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_authenticate_calls_share_one_login(
    mock_aiohttp_session,
):
    """Two concurrent ``authenticate()`` calls must share one login POST.

    Without the asyncio.Lock guard, two coroutines that both find an
    expired token would each fire a /login POST. This regression test
    races two coroutines and asserts only ONE login POST hit the wire.
    """
    import asyncio
    from .conftest import MOCK_ACCOUNT_RESPONSE, MOCK_ROOT_RESPONSE

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )

    login_calls = 0

    def post_side_effect(url, **kwargs):
        nonlocal login_calls
        if "login" in url:
            login_calls += 1
        return _make_resp(status=201, json_data=MOCK_LOGIN_RESPONSE)

    mock_aiohttp_session.get.side_effect = lambda url, **kw: _make_resp(
        status=200,
        json_data=MOCK_ROOT_RESPONSE if url.endswith("/api/v2") else MOCK_ACCOUNT_RESPONSE,
    )
    mock_aiohttp_session.post.side_effect = post_side_effect

    # Fire two authenticate() coroutines as a race.
    await asyncio.gather(client.authenticate(), client.authenticate())
    assert login_calls == 1, f"expected 1 login POST under lock, got {login_calls}"


@pytest.mark.asyncio
async def test_concurrent_discover_tank_walks_hateoas_once(
    mock_aiohttp_session,
):
    """Two concurrent first-refresh callers must not each walk the HATEOAS
    chain. With ``_discover_lock``, the second coroutine awaits the lock
    and then short-circuits on the now-set ``_measurement_url``.
    """
    import asyncio
    from .conftest import (
        MOCK_ROOT_RESPONSE,
        MOCK_TANKS_RESPONSE,
        MOCK_TANK_DETAIL_RESPONSE,
    )

    client = MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )
    # Pre-authenticate so _discover_tank doesn't trip the auth path.
    client._token = MOCK_TOKEN
    client._token_expiry = 9999999999.0

    tanks_list_hits = 0

    def get_side_effect(url, **kwargs):
        nonlocal tanks_list_hits
        if url.endswith("/tanks"):
            tanks_list_hits += 1
            return _make_resp(status=200, json_data=MOCK_TANKS_RESPONSE)
        if url.endswith("/api/v2"):
            return _make_resp(status=200, json_data=MOCK_ROOT_RESPONSE)
        if url == f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}":
            return _make_resp(status=200, json_data=MOCK_TANK_DETAIL_RESPONSE)
        return _make_resp(status=200, json_data={})

    mock_aiohttp_session.get.side_effect = get_side_effect

    # Race two _discover_tank() calls.
    await asyncio.gather(client._discover_tank(), client._discover_tank())
    # Even though two callers raced, the lock + double-checked guard means
    # the tanks-list endpoint should be hit exactly once.
    assert tanks_list_hits == 1, (
        f"expected 1 tanks-list fetch under lock, got {tanks_list_hits}"
    )


# ── Energy integration cap (post-outage spike protection) ─────────────────────


def test_energy_elapsed_hours_capped_post_outage():
    """A multi-hour gap between coordinator updates must NOT credit a
    fictitious spike. The integration window is capped at
    2 × update_interval per tick.
    """
    import datetime as dt

    from custom_components.mixergy.sensor import MixergyEnergySensor

    # Fabricate a coordinator with a 30s update interval and 1 kW reading.
    coordinator = MagicMock()
    coordinator.update_interval = dt.timedelta(seconds=30)
    coordinator.data = MagicMock()

    sensor = MixergyEnergySensor.__new__(MixergyEnergySensor)
    sensor.coordinator = coordinator
    sensor._accumulated_kwh = 0.0
    sensor._power_w_fn = lambda _data: 1000.0  # constant 1 kW
    sensor._last_update = 0.0  # wall-clock 0 (epoch)
    sensor.async_write_ha_state = MagicMock()

    # Simulate an hour-long outage: time.time() jumps 3600 s.
    # Sensor migrated from time.monotonic() to time.time() so kWh
    # accumulation survives HA restarts (monotonic resets at process
    # start and silently dropped any energy from before the restart).
    import time
    real_time = time.time

    def fake_time():
        return 3600.0  # +1h since last_update

    time.time = fake_time
    try:
        sensor._handle_coordinator_update()
    finally:
        time.time = real_time

    # Cap = 2 × 30s = 60s = 1/60 h. At 1 kW that's 1/60 kWh ≈ 0.01667.
    # Without the cap we'd have credited 1.0 kWh as a fictitious spike.
    assert sensor._accumulated_kwh < 0.02, (
        f"energy not capped: got {sensor._accumulated_kwh:.4f} kWh"
    )
    assert sensor._accumulated_kwh > 0.0, "cap dropped energy entirely"


def test_energy_negative_elapsed_clamps_to_zero():
    """Clock skew or NTP correction can produce negative elapsed time —
    that must NOT subtract energy (TOTAL_INCREASING treats decreases as
    counter resets and the Energy dashboard loses history).
    """
    import datetime as dt
    import time

    from custom_components.mixergy.sensor import MixergyEnergySensor

    coordinator = MagicMock()
    coordinator.update_interval = dt.timedelta(seconds=30)
    coordinator.data = MagicMock()

    sensor = MixergyEnergySensor.__new__(MixergyEnergySensor)
    sensor.coordinator = coordinator
    sensor._accumulated_kwh = 5.0  # 5 kWh accumulated before the skew
    sensor._power_w_fn = lambda _data: 1000.0
    sensor._last_update = 10_000.0  # FUTURE relative to the fake time below
    sensor.async_write_ha_state = MagicMock()

    real_time = time.time
    time.time = lambda: 9_000.0  # NTP rolled wall-clock backwards by 1000 s
    try:
        sensor._handle_coordinator_update()
    finally:
        time.time = real_time

    # Accumulated kWh must not decrease.
    assert sensor._accumulated_kwh == 5.0, (
        f"clock skew subtracted energy: {sensor._accumulated_kwh} kWh"
    )


@pytest.mark.asyncio
async def test_energy_restore_writes_state_immediately():
    """async_added_to_hass MUST call async_write_ha_state after restoring,
    so the Energy dashboard never sees a transient 0/unknown after restart.
    TOTAL_INCREASING treats any transient 0 as a counter reset, permanently
    losing all accumulated kWh stats.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.mixergy.sensor import MixergyEnergySensor

    coordinator = MagicMock()
    coordinator.data = MagicMock()

    sensor = MixergyEnergySensor.__new__(MixergyEnergySensor)
    sensor.coordinator = coordinator
    sensor._accumulated_kwh = 0.0
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()

    # Stub the RestoreSensor + CoordinatorEntity bases for the test.
    last_state = MagicMock()
    last_state.native_value = "42.5"
    sensor.async_get_last_sensor_data = AsyncMock(return_value=last_state)

    # Skip the real super().async_added_to_hass() — it requires a full
    # HA core fixture. We're testing only our additions.
    async def _noop(self):
        pass
    import custom_components.mixergy.sensor as sensor_mod
    base = sensor_mod.MixergyEnergySensor.__mro__[1]
    original = base.async_added_to_hass
    base.async_added_to_hass = _noop
    try:
        await sensor.async_added_to_hass()
    finally:
        base.async_added_to_hass = original

    assert sensor._accumulated_kwh == 42.5, "restored kWh not loaded"
    sensor.async_write_ha_state.assert_called_once_with()
