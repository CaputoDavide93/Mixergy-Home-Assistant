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
        resp = AsyncMock()
        resp.status = 401
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

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

    def get_side_effect(url, **kwargs):
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        resp.release = AsyncMock()
        if "measurement" in url:
            resp.json = AsyncMock(return_value=payload)
        elif url.endswith("/api/v2"):
            from .conftest import MOCK_ROOT_RESPONSE, MOCK_TANKS_RESPONSE, MOCK_TANK_DETAIL_RESPONSE
            resp.json = AsyncMock(return_value=MOCK_ROOT_RESPONSE)
        elif url.endswith("/tanks"):
            from .conftest import MOCK_TANKS_RESPONSE
            resp.json = AsyncMock(return_value=MOCK_TANKS_RESPONSE)
        elif url.endswith(MOCK_SERIAL):
            from .conftest import MOCK_TANK_DETAIL_RESPONSE
            resp.json = AsyncMock(return_value=MOCK_TANK_DETAIL_RESPONSE)
        else:
            resp.json = AsyncMock(return_value={})
        return resp

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
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
    from .conftest import MOCK_TANKS_RESPONSE

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
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        resp.release = AsyncMock()
        if url.endswith("/tanks"):
            resp.json = AsyncMock(return_value=wrong_tanks)
        elif url.endswith("/api/v2"):
            from .conftest import MOCK_ROOT_RESPONSE
            resp.json = AsyncMock(return_value=MOCK_ROOT_RESPONSE)
        else:
            resp.json = AsyncMock(return_value={})
        return resp

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
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
    # Ensure the client is initialised
    await api_client.fetch_all()

    put_calls: list = []

    def put_side_effect(url, **kwargs):
        put_calls.append(kwargs.get("json", {}))
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    mock_aiohttp_session.request = MagicMock(
        side_effect=lambda method, url, **kw: put_side_effect(url, **kw)
        if method.upper() == "PUT"
        else AsyncMock()
    )

    await api_client.set_target_charge(150)  # Should be clamped to 100
    assert any(c.get("charge") == 100 for c in put_calls)


@pytest.mark.asyncio
async def test_set_target_temperature_clamps_value(
    api_client: MixergyApiClient, mock_aiohttp_session: MagicMock
) -> None:
    """set_target_temperature clamps values to 45–70 before sending."""
    await api_client.fetch_all()

    put_calls: list = []

    def put_side_effect(url, **kwargs):
        put_calls.append(kwargs.get("json", {}))
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    mock_aiohttp_session.request = MagicMock(
        side_effect=lambda method, url, **kw: put_side_effect(url, **kw)
        if method.upper() == "PUT"
        else AsyncMock()
    )

    await api_client.set_target_temperature(100)  # Should be clamped to 70
    assert any(c.get("max_temp") == 70 for c in put_calls)


# ── Heat source normalisation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_schedule_normalises_heatpump_to_heat_pump(
    mock_aiohttp_session: MagicMock,
) -> None:
    """fetch_schedule normalises API "heatpump" → HA "heat_pump"."""
    from .conftest import (
        MOCK_MEASUREMENT_RESPONSE,
        MOCK_ROOT_RESPONSE,
        MOCK_SERIAL,
        MOCK_TANK_DETAIL_RESPONSE,
        MOCK_TANKS_RESPONSE,
    )

    schedule_with_heatpump = '{"defaultHeatSource": "heatpump"}'

    def get_side_effect(url, **kwargs):
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        resp.release = AsyncMock()
        if url.endswith("/api/v2"):
            resp.json = AsyncMock(return_value=MOCK_ROOT_RESPONSE)
        elif url.endswith("/tanks"):
            resp.json = AsyncMock(return_value=MOCK_TANKS_RESPONSE)
        elif url.endswith(MOCK_SERIAL):
            resp.json = AsyncMock(return_value=MOCK_TANK_DETAIL_RESPONSE)
        elif "measurement" in url:
            resp.json = AsyncMock(return_value=MOCK_MEASUREMENT_RESPONSE)
        elif "schedule" in url:
            resp.text = AsyncMock(return_value=schedule_with_heatpump)
        else:
            resp.json = AsyncMock(return_value={})
            resp.text = AsyncMock(return_value="{}")
        return resp

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
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

    def request_side_effect(method, url, **kwargs):
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        resp.release = AsyncMock()
        if method.upper() == "PUT":
            put_bodies.append(kwargs.get("json", {}))
        resp.text = AsyncMock(return_value="{}")
        return resp

    mock_aiohttp_session.request = MagicMock(side_effect=request_side_effect)
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
        resp = AsyncMock()
        resp.status = 200
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        resp.release = AsyncMock()
        if url.endswith("/api/v2"):
            resp.json = AsyncMock(return_value=MOCK_ROOT_RESPONSE)
        elif url.endswith("/tanks"):
            resp.json = AsyncMock(return_value=MOCK_TANKS_RESPONSE)
        elif url.endswith(MOCK_SERIAL):
            resp.json = AsyncMock(return_value=broken_detail)
        else:
            resp.json = AsyncMock(return_value={})
        return resp

    mock_aiohttp_session.get = MagicMock(side_effect=get_side_effect)
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
