"""Shared fixtures for Mixergy tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.mixergy.api import (
    MixergyApiClient,
    TankData,
    TankInfo,
    TankMeasurement,
    TankSchedule,
    TankSettings,
)

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
    """Return a mock aiohttp ClientSession."""
    session = MagicMock(spec=aiohttp.ClientSession)

    def make_response(status: int, json_data=None, text_data: str | None = None):
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

    def request_side_effect(method, url, **kwargs):
        if method.upper() == "GET":
            return get_side_effect(url, **kwargs)
        if method.upper() == "PUT":
            return put_side_effect(url, **kwargs)
        return make_response(404)

    session.get = MagicMock(side_effect=get_side_effect)
    session.post = MagicMock(side_effect=post_side_effect)
    session.put = MagicMock(side_effect=put_side_effect)
    session.request = MagicMock(side_effect=request_side_effect)

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
