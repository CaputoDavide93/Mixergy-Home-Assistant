"""Config-flow tests driven through the real Home Assistant flow manager.

The existing config-flow tests construct MixergyConfigFlow directly and stub
async_set_unique_id, _abort_if_unique_id_configured, async_show_form and
async_create_entry. That exercises the branching but mocks away the very
machinery the config-flow quality rules exist to verify — most importantly the
duplicate-entry abort, which cannot be observed at all when the uniqueness
helpers are stubs.

These tests use a real ``hass`` and go through
``hass.config_entries.flow.async_init``, so the unique-id handling, the step
transitions and the created entry are the genuine article.

Requires pytest-homeassistant-custom-component, which pins one exact Home
Assistant version. The module skips cleanly where it is absent so the
minimum-HA CI lane keeps running the mock-based suite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="fixture-backed flow tests run only on the pinned-HA lane",
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.mixergy_tank.api import (
    MixergyAuthError,
    MixergyConnectionError,
    MixergyTankNotFoundError,
)
from custom_components.mixergy_tank.const import (
    CONF_EXPERIENCE_MODE,
    CONF_SERIAL_NUMBER,
    DOMAIN,
    MODE_ADVANCED,
    MODE_SIMPLE,
)

from .conftest import MOCK_PASSWORD, MOCK_SERIAL, MOCK_USERNAME

_CLIENT = "custom_components.mixergy_tank.config_flow.MixergyApiClient"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load this custom integration in every test here."""
    return


def _client(**failures) -> MagicMock:
    """Return a stub API client; pass credentials=/connection= to fail a step."""
    client = MagicMock()
    client.test_credentials = AsyncMock(side_effect=failures.get("credentials"))
    client.test_connection = AsyncMock(side_effect=failures.get("connection"))
    client.async_list_tanks = AsyncMock(
        return_value=failures.get("tanks", [{"serial": MOCK_SERIAL}])
    )
    client.tank_info = MagicMock()
    client.tank_info.model_code = "MIXERGY-180"
    return client


async def _run_full_flow(hass: HomeAssistant, serial: str = MOCK_SERIAL) -> dict:
    """Drive user → tank → experience through the real flow manager."""
    with patch(_CLIENT, return_value=_client()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": MOCK_USERNAME, "password": MOCK_PASSWORD},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_NUMBER: serial}
        )
        if result["type"] is FlowResultType.FORM:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_EXPERIENCE_MODE: MODE_SIMPLE}
            )
        await hass.async_block_till_done()
    return result


async def test_user_flow_creates_an_entry(hass: HomeAssistant) -> None:
    """The happy path must produce a real config entry."""
    result = await _run_full_flow(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SERIAL_NUMBER] == MOCK_SERIAL
    assert result["data"]["username"] == MOCK_USERNAME

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].unique_id == MOCK_SERIAL


async def test_duplicate_serial_aborts(hass: HomeAssistant) -> None:
    """A second entry for the same tank must abort as already_configured.

    This is the rule's headline requirement and could not be tested at all
    while async_set_unique_id and _abort_if_unique_id_configured were stubbed:
    with those mocked, a duplicate silently created a second entry.
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SERIAL,
        data={
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            CONF_SERIAL_NUMBER: MOCK_SERIAL,
        },
    )
    existing.add_to_hass(hass)

    result = await _run_full_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # And critically: still exactly one entry, not two.
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_a_different_serial_is_not_treated_as_duplicate(
    hass: HomeAssistant,
) -> None:
    """Multi-tank accounts must still be able to add a second, different tank."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="MX000001",
        data={CONF_SERIAL_NUMBER: "MX000001"},
    )
    existing.add_to_hass(hass)

    result = await _run_full_flow(hass, serial=MOCK_SERIAL)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (MixergyAuthError("bad"), "invalid_auth"),
        (MixergyConnectionError("down"), "cannot_connect"),
        (OSError("socket"), "unknown"),
    ),
)
async def test_credential_failures_show_their_own_error(
    hass: HomeAssistant, failure: Exception, expected: str
) -> None:
    """Each failure re-shows the user form with its own message.

    Through the real flow manager, so the form is genuinely re-shown and the
    flow stays resumable rather than the branch merely being executed.
    """
    with patch(_CLIENT, return_value=_client(credentials=failure)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": MOCK_USERNAME, "password": "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected}


async def test_recovers_after_a_failed_attempt(hass: HomeAssistant) -> None:
    """A user who mistypes once must be able to continue in the same flow."""
    with patch(_CLIENT, return_value=_client(credentials=MixergyAuthError("no"))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": MOCK_USERNAME, "password": "wrong"}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch(_CLIENT, return_value=_client()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": MOCK_USERNAME, "password": MOCK_PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tank"


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        # tank_not_found is attached to the serial_number FIELD, not "base":
        # the user can fix that specific input, so the error belongs next to
        # it. cannot_connect is not about the field, so it stays on "base".
        (MixergyTankNotFoundError("gone"), {CONF_SERIAL_NUMBER: "tank_not_found"}),
        (MixergyConnectionError("down"), {"base": "cannot_connect"}),
    ),
)
async def test_tank_step_failures_show_their_own_error(
    hass: HomeAssistant, failure: Exception, expected: dict[str, str]
) -> None:
    """A bad serial must be correctable without restarting the flow."""
    with patch(_CLIENT, return_value=_client(connection=failure)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": MOCK_USERNAME, "password": MOCK_PASSWORD},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_NUMBER: "MX999999"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tank"
    assert result["errors"] == expected


async def test_options_flow_round_trips(hass: HomeAssistant) -> None:
    """Options must persist through the real options flow manager."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_SERIAL,
        data={
            "username": MOCK_USERNAME,
            "password": MOCK_PASSWORD,
            CONF_SERIAL_NUMBER: MOCK_SERIAL,
        },
        options={CONF_EXPERIENCE_MODE: MODE_SIMPLE},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_EXPERIENCE_MODE: MODE_ADVANCED, "update_interval": 120},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPERIENCE_MODE] == MODE_ADVANCED
    assert entry.options["update_interval"] == 120


async def test_tank_listing_failure_falls_back_to_free_text(
    hass: HomeAssistant,
) -> None:
    """If the tank list can't be fetched, the user must still be able to type.

    Credentials are already known good at this point, so aborting would strand
    someone whose account lists fine but whose /tanks call blipped. The flow
    degrades to free-text serial entry instead.
    """
    client = _client()
    client.async_list_tanks = AsyncMock(
        side_effect=MixergyConnectionError("listing down")
    )

    with patch(_CLIENT, return_value=client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": MOCK_USERNAME, "password": MOCK_PASSWORD},
        )

    # Not an abort and not an error — the tank step is still reachable.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tank"
    assert not result["errors"]


async def test_unexpected_tank_step_error_is_reported_as_unknown(
    hass: HomeAssistant,
) -> None:
    """A non-Mixergy exception must not escape the flow as a traceback."""
    with patch(_CLIENT, return_value=_client(connection=OSError("socket"))):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": MOCK_USERNAME, "password": MOCK_PASSWORD},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SERIAL_NUMBER: MOCK_SERIAL}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tank"
    assert result["errors"] == {"base": "unknown"}
