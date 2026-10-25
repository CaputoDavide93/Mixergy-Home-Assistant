"""The screenshot instance's stand-ins. Never installed anywhere real.

`tools/screenshots/take_screenshots.py` copies this into the throwaway Home
Assistant it starts, beside the integration. It does two things:

- It replaces the network methods of the integration's API client with a
  demo tank (serial A12345, a made-up model code), so no Mixergy account is
  needed and no request leaves the machine. The integration's own entities,
  config flow and coordinator run unchanged on top of it.
- A `screenshot_env.backfill` action writes earlier states of an entity with
  their own timestamps, so a history graph has hours to show.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import voluptuous as vol
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.tasks import StatisticsTask
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from custom_components.mixergy_tank import api

DOMAIN = "screenshot_env"
SERIAL = "A12345"
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

BACKFILL_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        # [[ISO time, state], ...], oldest first.
        vol.Required("points"): [vol.ExactSequence([cv.string, cv.string])],
    }
)

# What the demo tank reports right now; the writes below change it.
STATE = {
    "charge": 62.0,
    "target_charge": 80.0,
    "target_temperature": 60.0,
}


def _info() -> api.TankInfo:
    return api.TankInfo(
        serial_number=SERIAL,
        model_code="MX-DEMO-180",
        firmware_version="7.2.1",
        has_pv_diverter=True,
    )


def _install_fake_cloud() -> None:
    client = api.MixergyApiClient

    async def test_credentials(self) -> bool:
        return True

    async def test_connection(self) -> bool:
        self._tank_info = _info()
        return True

    async def list_tanks(self) -> list[dict[str, str]]:
        return [{"serial": SERIAL, "firmware": "7.2.1"}]

    async def fetch_all(self) -> api.TankData:
        now = dt_util.utcnow()
        self._tank_info = _info()
        return api.TankData(
            info=_info(),
            measurement=api.TankMeasurement(
                hot_water_temperature=58.4,
                coldest_water_temperature=24.1,
                charge=STATE["charge"],
                target_charge=STATE["target_charge"],
                electric_heat_source=False,
                indirect_heat_source=False,
                heatpump_heat_source=True,
                pv_power_kw=0.0,
                clamp_power_w=-420.0,
                immersion_energy_reported=False,
                active_heat_source=api.HeatSource.HEAT_PUMP,
                is_heating=True,
                operating_reason=api.OperatingReason.AUTO_SCHEDULE,
                recorded_time=now - timedelta(seconds=40),
                received_time=now - timedelta(seconds=30),
            ),
            settings=api.TankSettings(
                target_temperature=STATE["target_temperature"],
                dsr_enabled=True,
                frost_protection_enabled=True,
                cleansing_temperature=53.0,
                divert_exported_enabled=True,
                pv_cut_in_threshold=150.0,
                pv_charge_limit=90.0,
                pv_target_current=-0.5,
                pv_over_temperature=55.0,
            ),
            schedule=api.TankSchedule(default_heat_source="heat_pump"),
        )

    async def set_target_charge(self, charge: int) -> None:
        STATE["target_charge"] = float(charge)

    async def set_target_temperature(self, temperature: int) -> None:
        STATE["target_temperature"] = float(temperature)

    client.test_credentials = test_credentials
    client.test_connection = test_connection
    client.async_list_tanks = list_tanks
    client.fetch_all = fetch_all
    client.set_target_charge = set_target_charge
    client.set_target_temperature = set_target_temperature


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _install_fake_cloud()

    async def backfill(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        current = hass.states.get(entity_id)
        attributes = dict(current.attributes) if current else {}
        times = []
        for when, state in call.data["points"]:
            times.append(datetime.fromisoformat(when))
            hass.states.async_set(
                entity_id,
                state,
                attributes,
                force_update=True,
                timestamp=times[-1].timestamp(),
            )
        recorder = get_instance(hass)
        await recorder.async_block_till_done()
        period = timedelta(minutes=5)
        start = times[0].replace(
            minute=times[0].minute // 5 * 5, second=0, microsecond=0
        )
        while start + period <= dt_util.utcnow():
            recorder.queue_task(StatisticsTask(start, False))
            start += period
        await recorder.async_block_till_done()

    hass.services.async_register(DOMAIN, "backfill", backfill, BACKFILL_SCHEMA)
    return True
