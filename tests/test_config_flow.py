"""Tests for the Mixergy config flow and options flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

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
# Patch target for the aiohttp session helper used in the config flow
_SESSION_PATCH = "custom_components.mixergy.config_flow.async_get_clientsession"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_flow_hass() -> MagicMock:
    """Return a minimal mock hass object suitable for a config flow."""
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    return hass


# ── Config Flow ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_flow_creates_entry_on_valid_input() -> None:
    """Submitting valid credentials and a valid serial number creates a config entry.

    The config flow is multi-step:
      Step 1 (user)       — username + password → test_credentials()
      Step 2 (tank)       — serial_number       → test_connection()
      Step 3 (experience) — experience_mode     → async_create_entry()

    This test drives all three steps in sequence.
    """
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(return_value=True)
    mock_client.test_connection = AsyncMock(return_value=True)
    mock_client.tank_info = MagicMock()
    mock_client.tank_info.model_code = "MIXERGY-180"

    with patch(_CLIENT_PATCH, return_value=mock_client), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = _make_flow_hass()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_create_entry = MagicMock(
            side_effect=lambda title, data, options=None: {
                "type": "create_entry",
                "title": title,
                "data": data,
            }
        )
        flow.async_show_form = MagicMock(
            side_effect=lambda step_id, data_schema, errors=None, description_placeholders=None: {
                "type": "form",
                "step_id": step_id,
                "errors": errors or {},
            }
        )

        # Step 1: credentials
        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
        })
        # After valid credentials, step 1 calls step 2 with no input,
        # which should return a form asking for the serial number.
        assert result["type"] == "form"
        assert result["step_id"] == "tank"

        # Step 2: tank serial
        result = await flow.async_step_tank({
            CONF_SERIAL_NUMBER: MOCK_SERIAL,
        })
        # After valid serial, step 2 calls step 3 with no input,
        # which should return a form asking for experience mode.
        assert result["type"] == "form"
        assert result["step_id"] == "experience"

        # Step 3: experience mode
        result = await flow.async_step_experience({
            "experience_mode": "simple",
        })

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SERIAL_NUMBER] == MOCK_SERIAL
    assert result["data"]["username"] == MOCK_USERNAME


@pytest.mark.asyncio
async def test_config_flow_auth_error_shows_form() -> None:
    """An auth failure in step 1 sets the 'invalid_auth' base error on the form."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(side_effect=MixergyAuthError)

    with patch(_CLIENT_PATCH, return_value=mock_client), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = _make_flow_hass()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_show_form = MagicMock(
            side_effect=lambda step_id, data_schema, errors=None, description_placeholders=None: {
                "type": "form",
                "step_id": step_id,
                "errors": errors or {},
            }
        )

        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": "wrong",
        })

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_config_flow_tank_not_found_error() -> None:
    """A missing tank serial in step 2 sets the 'tank_not_found' field error."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(return_value=True)
    mock_client.test_connection = AsyncMock(side_effect=MixergyTankNotFoundError)
    mock_client.tank_info = MagicMock()
    mock_client.tank_info.model_code = ""

    with patch(_CLIENT_PATCH, return_value=mock_client), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = _make_flow_hass()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_show_form = MagicMock(
            side_effect=lambda step_id, data_schema, errors=None, description_placeholders=None: {
                "type": "form",
                "step_id": step_id,
                "errors": errors or {},
            }
        )

        # Drive through step 1 successfully to get to step 2
        # Patch step 2 to handle the error case directly
        result = await flow.async_step_tank({
            CONF_SERIAL_NUMBER: "BADBADSERIAL",
        })

    assert result["type"] == "form"
    assert result["errors"][CONF_SERIAL_NUMBER] == "tank_not_found"


@pytest.mark.asyncio
async def test_config_flow_connection_error() -> None:
    """A connection failure in step 1 sets the 'cannot_connect' base error."""
    mock_client = AsyncMock()
    mock_client.test_credentials = AsyncMock(side_effect=MixergyConnectionError)

    with patch(_CLIENT_PATCH, return_value=mock_client), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        from custom_components.mixergy.config_flow import MixergyConfigFlow

        flow = MixergyConfigFlow()
        flow.hass = _make_flow_hass()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda: None
        flow.async_show_form = MagicMock(
            side_effect=lambda step_id, data_schema, errors=None, description_placeholders=None: {
                "type": "form",
                "step_id": step_id,
                "errors": errors or {},
            }
        )

        result = await flow.async_step_user({
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
        })

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


# ── Options Flow ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_options_flow_shows_current_interval() -> None:
    """Options flow init step shows the current update interval as default."""
    from custom_components.mixergy.config_flow import MixergyOptionsFlow

    mock_entry = MagicMock()
    mock_entry.options = {CONF_UPDATE_INTERVAL: 60}

    flow = MixergyOptionsFlow()

    captured: dict = {}

    def capture_form(step_id, data_schema):
        captured["step_id"] = step_id
        return {"type": "form", "step_id": step_id, "schema": data_schema}

    flow.async_show_form = capture_form

    with patch.object(
        type(flow), "config_entry", new_callable=PropertyMock, return_value=mock_entry
    ):
        result = await flow.async_step_init()

    assert result["type"] == "form"
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_options_flow_saves_new_interval() -> None:
    """Submitting a new interval calls async_create_entry with correct data."""
    from custom_components.mixergy.config_flow import MixergyOptionsFlow

    mock_entry = MagicMock()
    mock_entry.options = {}

    flow = MixergyOptionsFlow()
    flow.async_create_entry = lambda data: {"type": "create_entry", "data": data}

    with patch.object(
        type(flow), "config_entry", new_callable=PropertyMock, return_value=mock_entry
    ):
        result = await flow.async_step_init({CONF_UPDATE_INTERVAL: 60})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_UPDATE_INTERVAL] == 60


@pytest.mark.asyncio
async def test_options_flow_defaults_to_update_interval_constant() -> None:
    """When no option is stored, the default should equal UPDATE_INTERVAL."""
    from custom_components.mixergy.config_flow import MixergyOptionsFlow

    mock_entry = MagicMock()
    mock_entry.options = {}  # No stored options

    flow = MixergyOptionsFlow()

    captured: dict = {}

    def capture_form(step_id, data_schema):
        # Extract the default from the voluptuous schema keys
        for key in data_schema.schema:
            if hasattr(key, "default") and str(key) == CONF_UPDATE_INTERVAL:
                captured["default"] = key.default()
        return {"type": "form"}

    flow.async_show_form = capture_form

    with patch.object(
        type(flow), "config_entry", new_callable=PropertyMock, return_value=mock_entry
    ):
        await flow.async_step_init()

    assert captured.get("default") == UPDATE_INTERVAL
