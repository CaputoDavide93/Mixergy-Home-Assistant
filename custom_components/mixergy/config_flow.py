"""Config flow for the Mixergy integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MixergyApiClient,
    MixergyAuthError,
    MixergyConnectionError,
    MixergyTankNotFoundError,
    TankInfo,
)
from .const import (
    CONF_EXPERIENCE_MODE,
    CONF_SERIAL_NUMBER,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    MODE_ADVANCED,
    MODE_SIMPLE,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# ── Step schemas ──────────────────────────────────────────────────────────────

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)

STEP_TANK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL_NUMBER): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
        ),
    }
)

STEP_EXPERIENCE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EXPERIENCE_MODE, default=MODE_SIMPLE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": MODE_SIMPLE, "label": "Simple"},
                    {"value": MODE_ADVANCED, "label": "Advanced"},
                ],
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


# ── Config flow ───────────────────────────────────────────────────────────────


class MixergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the guided multi-step config flow for Mixergy."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state carried across steps."""
        super().__init__()
        self._username: str = ""
        self._password: str = ""
        self._serial: str = ""
        self._model: str = ""

    # ── Step 1: credentials ──────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 — Collect and validate account credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            # We don't have a serial yet; use a placeholder so we can auth-test
            client = MixergyApiClient(
                session=session,
                username=username,
                password=password,
                serial_number="PLACEHOLDER",
            )

            try:
                await client.test_credentials()
            except MixergyAuthError:
                errors["base"] = "invalid_auth"
            except MixergyConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during authentication")
                errors["base"] = "unknown"
            else:
                self._username = username
                self._password = password
                return await self.async_step_tank()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    # ── Step 2: tank serial ──────────────────────────────────────────

    async def async_step_tank(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 — Find and validate the tank serial number."""
        errors: dict[str, str] = {}

        if user_input is not None:
            serial = user_input[CONF_SERIAL_NUMBER].upper().strip()

            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = MixergyApiClient(
                session=session,
                username=self._username,
                password=self._password,
                serial_number=serial,
            )

            try:
                await client.test_connection()
            except MixergyTankNotFoundError:
                errors[CONF_SERIAL_NUMBER] = "tank_not_found"
            except MixergyConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during tank lookup")
                errors["base"] = "unknown"
            else:
                self._serial = serial
                # Grab the model name for the next step's description
                info: TankInfo = client.tank_info
                self._model = info.model_code or "Mixergy Tank"
                return await self.async_step_experience()

        return self.async_show_form(
            step_id="tank",
            data_schema=STEP_TANK_SCHEMA,
            errors=errors,
        )

    # ── Step 3: experience mode ──────────────────────────────────────

    async def async_step_experience(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3 — Let the user choose Simple or Advanced experience."""
        if user_input is not None:
            mode = user_input[CONF_EXPERIENCE_MODE]
            return self.async_create_entry(
                title=f"Mixergy Tank ({self._serial})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_SERIAL_NUMBER: self._serial,
                },
                options={
                    CONF_EXPERIENCE_MODE: mode,
                },
            )

        return self.async_show_form(
            step_id="experience",
            data_schema=STEP_EXPERIENCE_SCHEMA,
            description_placeholders={
                "serial": self._serial,
                "model": self._model,
            },
        )

    # ── Reauth ───────────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials expire."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle re-auth credential input."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = MixergyApiClient(
                session=session,
                username=user_input[CONF_USERNAME].strip(),
                password=user_input[CONF_PASSWORD],
                serial_number=reauth_entry.data[CONF_SERIAL_NUMBER],
            )

            try:
                await client.test_credentials()
            except MixergyAuthError:
                errors["base"] = "invalid_auth"
            except MixergyConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={
                CONF_SERIAL_NUMBER: reauth_entry.data[CONF_SERIAL_NUMBER],
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: Any) -> MixergyOptionsFlow:
        """Return the options flow handler."""
        return MixergyOptionsFlow()


# ── Options flow ──────────────────────────────────────────────────────────────


class MixergyOptionsFlow(OptionsFlow):
    """Handle Mixergy integration options (experience mode + poll interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single options step covering experience mode and poll interval."""
        if user_input is not None:
            # NumberSelector returns float; coerce interval to int for timedelta
            data = dict(user_input)
            if CONF_UPDATE_INTERVAL in data:
                data[CONF_UPDATE_INTERVAL] = int(data[CONF_UPDATE_INTERVAL])
            return self.async_create_entry(data=data)

        current_mode = self.config_entry.options.get(
            CONF_EXPERIENCE_MODE, MODE_ADVANCED
        )
        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL, UPDATE_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EXPERIENCE_MODE, default=current_mode
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": MODE_SIMPLE, "label": "Simple"},
                                {"value": MODE_ADVANCED, "label": "Advanced"},
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=current_interval
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                }
            ),
        )
