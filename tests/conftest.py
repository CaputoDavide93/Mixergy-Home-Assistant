"""Shared fixtures for Mixergy tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.mixergy_tank.api import (
    MixergyApiClient,
    TankData,
    TankInfo,
    TankMeasurement,
    TankSchedule,
    TankSettings,
)

def attach_body(
    resp,
    body: bytes,
    *,
    declared_length: int | str | None = -1,
    charset: str | None = "utf-8",
) -> None:
    """Give a mock response the streaming surface the capped reader uses.

    ``declared_length`` defaults to the real body length; pass ``None`` to omit
    the header (chunked transfer) or an explicit value to model an upstream
    that lies about its size.
    """
    length = len(body) if declared_length == -1 else declared_length
    headers: dict[str, str] = {}
    if length is not None:
        headers["Content-Length"] = str(length)
    resp.headers = headers
    resp.charset = charset

    async def iter_chunked(chunk_size: int) -> AsyncIterator[bytes]:
        for start in range(0, len(body), chunk_size):
            yield body[start : start + chunk_size]

    content = MagicMock()
    content.iter_chunked = iter_chunked
    resp.content = content


MOCK_SERIAL = "TEST001"
MOCK_USERNAME = "user@example.com"
MOCK_PASSWORD = "secret"

MOCK_TOKEN = "mock-jwt-token"
MOCK_TOKEN_TTL = 3600

# ── Raw API payloads ──────────────────────────────────────────────────────────

MOCK_ROOT_RESPONSE = {
    "_links": {
        "account": {"href": "https://www.mixergy.io/api/v2/account"},
        "tanks": {"href": "https://www.mixergy.io/api/v2/tanks"},
    }
}

MOCK_ACCOUNT_RESPONSE = {
    "_links": {"login": {"href": "https://www.mixergy.io/api/v2/login"}}
}

MOCK_LOGIN_RESPONSE = {
    "token": MOCK_TOKEN,
    "ttl": MOCK_TOKEN_TTL,
}

MOCK_TANKS_RESPONSE = {
    "_embedded": {
        "tankList": [
            {
                "serialNumber": MOCK_SERIAL,
                "firmwareVersion": "2.1.0",
                "_links": {
                    "self": {"href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}"}
                },
            }
        ]
    }
}

MOCK_TANK_DETAIL_RESPONSE = {
    "tankModelCode": "MIXERGY-180",
    "configuration": '{"mixergyPvType": "NO_INVERTER"}',
    "_links": {
        "latest_measurement": {
            "href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/measurement"
        },
        "control": {
            "href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/control"
        },
        "settings": {
            "href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/settings"
        },
        "schedule": {
            "href": f"https://www.mixergy.io/api/v2/tank/{MOCK_SERIAL}/schedule"
        },
    },
}

MOCK_MEASUREMENT_RESPONSE = {
    "topTemperature": 65.5,
    "bottomTemperature": 20.3,
    "charge": 80.0,
    "state": '{"current": {"target": 80, "source": "Schedule", "heat_source": "electric", "immersion": "off"}}',
}

MOCK_SETTINGS_RESPONSE = (
    '{"max_temp": 60, "dsr_enabled": false, "frost_protection_enabled": true, '
    '"distributed_computing_enabled": false, "cleansing_temperature": 53}'
)

MOCK_SCHEDULE_RESPONSE = (
    '{"defaultHeatSource": "electric"}'
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_aiohttp_session() -> Generator[MagicMock, None, None]:
    """Return a mock aiohttp ClientSession.

    All HTTP methods (get, post, put, request) are AsyncMock so that
    ``await session.get(...)`` works correctly in the API client.
    The side-effects return context-manager-compatible AsyncMock responses.
    """
    session = MagicMock(spec=aiohttp.ClientSession)

    def make_response(status: int, json_data=None, text_data: str | None = None):
        resp = AsyncMock()
        resp.status = status
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        # aiohttp ClientResponse.release() is synchronous — use MagicMock so
        # un-awaited calls in the client don't emit coroutine warnings.
        resp.release = MagicMock()
        if json_data is not None:
            resp.json = AsyncMock(return_value=json_data)
        if text_data is not None:
            resp.text = AsyncMock(return_value=text_data)

        # The client never calls resp.json()/resp.text() — every body goes
        # through the capped reader, which streams resp.content and consults
        # Content-Length. Model both here so tests exercise the real path.
        if text_data is not None:
            body = text_data.encode()
        elif json_data is not None:
            body = json.dumps(json_data).encode()
        else:
            body = b""
        attach_body(resp, body)
        return resp

    def get_side_effect(url, **kwargs):
        if url.endswith("/api/v2"):
            return make_response(200, MOCK_ROOT_RESPONSE)
        if url.endswith("/account"):
            return make_response(200, MOCK_ACCOUNT_RESPONSE)
        if url.endswith("/tanks"):
            return make_response(200, MOCK_TANKS_RESPONSE)
        if url.endswith(MOCK_SERIAL):
            return make_response(200, MOCK_TANK_DETAIL_RESPONSE)
        if "measurement" in url:
            return make_response(200, MOCK_MEASUREMENT_RESPONSE)
        if "settings" in url:
            return make_response(200, None, MOCK_SETTINGS_RESPONSE)
        if "schedule" in url:
            return make_response(200, None, MOCK_SCHEDULE_RESPONSE)
        return make_response(404)

    def post_side_effect(url, **kwargs):
        if "login" in url:
            return make_response(201, MOCK_LOGIN_RESPONSE)
        return make_response(404)

    def put_side_effect(url, **kwargs):
        return make_response(200, {})

    async def request_side_effect(method, url, **kwargs):
        # Delegate to the *live* session.get/session.put mocks (not the
        # closures above) so a test that overrides session.get is honoured
        # for requests the client now routes through session.request — e.g.
        # authenticated HATEOAS discovery, which goes through the reauth
        # wrapper. In production .request and .get hit the same server.
        if method.upper() == "GET":
            return session.get(url, **kwargs)
        if method.upper() == "PUT":
            return session.put(url, **kwargs)
        return make_response(404)

    # session.get / session.post are used as ``async with session.get(...) as resp``
    # (no preceding ``await``), so they must be regular MagicMock returning a
    # context-manager-compatible response object directly.
    session.get = MagicMock(side_effect=get_side_effect)
    session.post = MagicMock(side_effect=post_side_effect)
    session.put = MagicMock(side_effect=put_side_effect)
    # session.request is used as ``resp = await session.request(...)`` so it must
    # be an AsyncMock so that the await expression produces the response object.
    session.request = AsyncMock(side_effect=request_side_effect)

    yield session


@pytest.fixture
def api_client(mock_aiohttp_session: MagicMock) -> MixergyApiClient:
    """Return a MixergyApiClient backed by the mock session."""
    return MixergyApiClient(
        session=mock_aiohttp_session,
        username=MOCK_USERNAME,
        password=MOCK_PASSWORD,
        serial_number=MOCK_SERIAL,
    )


@pytest.fixture
def mock_tank_data() -> TankData:
    """Return a realistic TankData fixture."""
    return TankData(
        info=TankInfo(
            serial_number=MOCK_SERIAL,
            model_code="MIXERGY-180",
            firmware_version="2.1.0",
            has_pv_diverter=False,
        ),
        measurement=TankMeasurement(
            hot_water_temperature=65.5,
            coldest_water_temperature=20.3,
            charge=80.0,
            target_charge=80.0,
            electric_heat_source=False,
            indirect_heat_source=False,
            heatpump_heat_source=False,
            in_holiday_mode=False,
            pv_power_kw=0.0,
            clamp_power_w=0.0,
        ),
        settings=TankSettings(
            target_temperature=60.0,
            dsr_enabled=False,
            frost_protection_enabled=True,
            distributed_computing_enabled=False,
            cleansing_temperature=53.0,
        ),
        schedule=TankSchedule(
            raw={},
            default_heat_source="electric",
        ),
    )
