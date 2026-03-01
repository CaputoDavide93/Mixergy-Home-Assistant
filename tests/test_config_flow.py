"""Tests for the Mixergy config flow and options flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.mixergy.api import (
    MixergyAuthError,
    MixergyConnectionError,
    MixergyTankNotFoundError,
)
from custom_components.mixergy.const import (
    CONF_SERIAL_NUMBER,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    UPDATE_INTERVAL,
)

from .conftest import MOCK_PASSWORD, MOCK_SERIAL, MOCK_USERNAME

# Patch target for the API client used inside the config flow
_CLIENT_PATCH = "custom_components.mixergy.config_flow.MixergyApiClient"


# ── Config Flow ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_flow_creates_entry_on_valid_input() -> None:
    """A valid username/password/serial creates a config entry."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(return_value=True)
    mock_client.test_connection = AsyncMock(return_value=True)

    with patch(_CLIENT_PATCH, return_value=mock_client):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = AsyncMock()
        flow.hass.config_entries.async_entries.return_value = []
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_create_entry = lambda title, data: {"type": "create_entry", "title": title, "data": data}

        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            "serial_number": MOCK_SERIAL,
        })

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SERIAL_NUMBER] == MOCK_SERIAL
    assert result["data"]["username"] == MOCK_USERNAME


@pytest.mark.asyncio
async def test_config_flow_auth_error_shows_form() -> None:
    """An auth failure sets the 'invalid_auth' error on the form."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(side_effect=MixergyAuthError)

    with patch(_CLIENT_PATCH, return_value=mock_client):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = AsyncMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_show_form = lambda step_id, data_schema, errors: {
            "type": "form",
            "errors": errors,
        }

        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": "wrong",
            "serial_number": MOCK_SERIAL,
        })

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_config_flow_tank_not_found_error() -> None:
    """A missing tank serial sets the 'tank_not_found' field error."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(return_value=True)
    mock_client.test_connection = AsyncMock(side_effect=MixergyTankNotFoundError)

    with patch(_CLIENT_PATCH, return_value=mock_client):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = AsyncMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_show_form = lambda step_id, data_schema, errors: {
            "type": "form",
            "errors": errors,
        }

        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            "serial_number": "BADBADSERIAL",
        })

    assert result["type"] == "form"
    assert result["errors"][CONF_SERIAL_NUMBER] == "tank_not_found"


@pytest.mark.asyncio
async def test_config_flow_connection_error() -> None:
    """A connection failure sets the 'cannot_connect' base error."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(side_effect=MixergyConnectionError)

    with patch(_CLIENT_PATCH, return_value=mock_client):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = AsyncMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_show_form = lambda step_id, data_schema, errors: {
            "type": "form",
            "errors": errors,
        }

        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            "serial_number": MOCK_SERIAL,
        })

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


# ── Options Flow ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_options_flow_shows_current_interval() -> None:
    """Options flow init step shows the current update interval as default."""
    from custom_components.mixergy.config_flow import MixergyOptionsFlow

    flow = MixergyOptionsFlow()
    flow.config_entry = AsyncMock()
    flow.config_entry.options = {CONF_UPDATE_INTERVAL: 60}
    flow.async_show_form = lambda step_id, data_schema: {
        "type": "form",
        "step_id": step_id,
        "schema": data_schema,
    }

    result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_options_flow_saves_new_interval() -> None:
    """Submitting new interval calls async_create_entry with correct data."""
    from custom_components.mixergy.config_flow import MixergyOptionsFlow

    flow = MixergyOptionsFlow()
    flow.config_entry = AsyncMock()
    flow.config_entry.options = {}
    flow.async_create_entry = lambda data: {"type": "create_entry", "data": data}

    result = await flow.async_step_init({CONF_UPDATE_INTERVAL: 60})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_UPDATE_INTERVAL] == 60


@pytest.mark.asyncio
async def test_options_flow_defaults_to_update_interval_constant() -> None:
    """When no option is stored, the default should equal UPDATE_INTERVAL."""
    from custom_components.mixergy.config_flow import MixergyOptionsFlow

    flow = MixergyOptionsFlow()
    flow.config_entry = AsyncMock()
    flow.config_entry.options = {}  # No stored options

    captured: dict = {}

    def capture_form(step_id, data_schema):
        # Extract the default from the schema
        for key in data_schema.schema:
            if hasattr(key, "default"):
                captured["default"] = key.default()
        return {"type": "form"}

    flow.async_show_form = capture_form
    await flow.async_step_init()

    assert captured.get("default") == UPDATE_INTERVAL
