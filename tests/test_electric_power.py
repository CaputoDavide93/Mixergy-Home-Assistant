"""Electric heat power: which measurement field backs it (issue #35).

``clampPower`` is the PV diverter's grid CT clamp, not the immersion element,
and is absent on tanks without a diverter. The measurement's ``energy`` field
is the immersion's own consumption in joules over the one-minute report window
— a captured cleansing report carried ``energy`` 169623 J alongside 231.81 V
and 12.14 A, i.e. ≈2.83 kW from energy / 60 against ≈2.81 kW from V × I.
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.mixergy_tank.api import (
    ElectricPowerSource,
    TankData,
    TankInfo,
    TankMeasurement,
)
from custom_components.mixergy_tank.const import CONF_ELECTRIC_RATE

from .test_api import _make_resp
from .test_api_writes import _write_client

# The captured cleansing report: the immersion ran while the nominal heat
# source was the heat pump, so the old heat-source gate reported 0 W.
CAPTURED_CLEANSING_REPORT = {
    "recordedTime": 1742699760088,
    "receivedTime": 1742699760527,
    "topTemperature": 58.8,
    "bottomTemperature": 58.1,
    "charge": 100.0,
    "energy": 169623,
    "voltage": 231.81,
    "current": 12.14,
    "state": {
        "current": {
            "immersion": "On",
            "source": "Cleansing",
            "heat_source": "HeatPump",
            "temperature": 63,
        },
    },
}


async def _fetch(session: MagicMock, payload: dict) -> TankMeasurement:
    session.request = AsyncMock(return_value=_make_resp(200, payload))
    return await _write_client(session).fetch_measurement()


async def test_energy_is_converted_from_joules_per_minute(
    mock_aiohttp_session: MagicMock,
) -> None:
    """energy / 60 gives watts and agrees with the report's own V × I."""
    measurement = await _fetch(mock_aiohttp_session, CAPTURED_CLEANSING_REPORT)

    assert measurement.immersion_energy_reported is True
    assert measurement.immersion_power_w == pytest.approx(169623 / 60)
    volts_times_amps = 231.81 * 12.14
    assert measurement.immersion_power_w == pytest.approx(volts_times_amps, rel=0.01)


async def test_immersion_energy_counts_even_when_another_source_is_nominal(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Cleansing in heat-pump mode energises the immersion; it must count."""
    measurement = await _fetch(mock_aiohttp_session, CAPTURED_CLEANSING_REPORT)

    assert measurement.electric_heat_source is False
    assert measurement.electric_power_source is ElectricPowerSource.IMMERSION_ENERGY
    assert measurement.electric_heat_power_w == pytest.approx(2827.05)


async def test_energy_is_preferred_over_the_diverter_clamp(
    mock_aiohttp_session: MagicMock,
) -> None:
    """On a diverter tank the grid clamp must not stand in for the element."""
    payload = {
        "charge": 40.0,
        "energy": 180000,  # 3 kW
        "clampPower": -1200.0,  # exporting to the grid
        "state": {"current": {"heat_source": "electric", "immersion": "on"}},
    }
    measurement = await _fetch(mock_aiohttp_session, payload)

    assert measurement.clamp_power_w == -1200.0
    assert measurement.electric_heat_power_w == 3000.0


@pytest.mark.parametrize("raw", (None, "junk", float("nan"), -60, True))
async def test_malformed_energy_is_unknown_not_zero(
    mock_aiohttp_session: MagicMock, raw: object
) -> None:
    """A present-but-unusable reading must not fall back to the clamp."""
    payload = {
        "energy": raw,
        "clampPower": 500.0,
        "state": {"current": {"heat_source": "electric", "immersion": "on"}},
    }
    measurement = await _fetch(mock_aiohttp_session, payload)

    assert measurement.immersion_energy_reported is True
    assert measurement.immersion_power_w is None
    assert measurement.electric_heat_power_w is None


async def test_implausible_energy_is_rejected(
    mock_aiohttp_session: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """A cumulative counter or unit change must not be integrated as watts."""
    payload = {"energy": 5_000_000_000}
    measurement = await _fetch(mock_aiohttp_session, payload)

    assert measurement.immersion_power_w is None
    assert measurement.electric_heat_power_w is None
    assert "implausible immersion energy" in caplog.text


async def test_absent_energy_keeps_the_legacy_clamp_fallback(
    mock_aiohttp_session: MagicMock,
) -> None:
    """Without energy, an electric-heating tank still reports the clamp."""
    payload = {
        "clampPower": 2750.0,
        "state": {"current": {"heat_source": "electric", "immersion": "on"}},
    }
    measurement = await _fetch(mock_aiohttp_session, payload)

    assert measurement.immersion_energy_reported is False
    assert measurement.electric_power_source is ElectricPowerSource.CLAMP_POWER
    assert measurement.electric_heat_power_w == 2750.0


def test_idle_immersion_reads_zero() -> None:
    """No energy key and no electric heating is a genuine 0 W."""
    measurement = TankMeasurement(clamp_power_w=900.0)
    assert measurement.electric_power_source is ElectricPowerSource.IDLE
    assert measurement.electric_heat_power_w == 0.0


def test_electric_heating_without_any_reading_is_unavailable() -> None:
    """A heating tank with neither field has an unknown draw, not 0 W."""
    measurement = TankMeasurement(electric_heat_source=True)
    assert measurement.electric_power_source is ElectricPowerSource.CLAMP_POWER
    assert measurement.electric_heat_power_w is None


# ── Entities ──────────────────────────────────────────────────────────────────


def _coordinator(measurement: TankMeasurement) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = TankData(
        info=TankInfo(serial_number="T1"), measurement=measurement
    )
    coordinator.last_update_success = True
    coordinator.update_interval = timedelta(seconds=60)
    coordinator.hass = MagicMock()
    coordinator.hass.config.currency = "GBP"
    return coordinator


def _power_sensor(coordinator: MagicMock):
    from custom_components.mixergy_tank.sensor import (
        SENSOR_DESCRIPTIONS,
        MixergySensor,
    )

    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "electric_power")
    return MixergySensor(coordinator, description)


@pytest.mark.parametrize(
    ("measurement", "value", "source"),
    (
        (
            TankMeasurement(immersion_energy_reported=True, immersion_power_w=2800.0),
            2800.0,
            "immersion_energy",
        ),
        (
            TankMeasurement(electric_heat_source=True, clamp_power_w=2500.0),
            2500.0,
            "clamp_power",
        ),
        (TankMeasurement(clamp_power_w=2500.0), 0.0, "idle"),
    ),
)
def test_power_sensor_reports_value_and_source(
    measurement: TankMeasurement, value: float, source: str
) -> None:
    """The source attribute makes the backing field visible to the user."""
    sensor = _power_sensor(_coordinator(measurement))

    assert sensor.available is True
    assert sensor.native_value == value
    assert sensor.extra_state_attributes == {"source": source}


def test_power_sensor_is_unavailable_for_an_unusable_energy_reading() -> None:
    measurement = TankMeasurement(
        immersion_energy_reported=True, immersion_power_w=None, clamp_power_w=100.0
    )
    assert _power_sensor(_coordinator(measurement)).available is False


def test_other_sensors_carry_no_extra_attributes() -> None:
    from custom_components.mixergy_tank.sensor import (
        SENSOR_DESCRIPTIONS,
        MixergySensor,
    )

    coordinator = _coordinator(TankMeasurement())
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "charge")
    assert MixergySensor(coordinator, description).extra_state_attributes is None


async def test_energy_and_cost_integrate_immersion_energy() -> None:
    """Electric energy and cost both accumulate from the immersion reading."""
    from custom_components.mixergy_tank.sensor import (
        MixergyElectricCostSensor,
        MixergyEnergySensor,
        async_setup_entry,
    )

    coordinator = _coordinator(
        TankMeasurement(
            immersion_energy_reported=True,
            immersion_power_w=3000.0,
            report_is_fresh=True,
        )
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.options = {CONF_ELECTRIC_RATE: 0.5}
    added: list = []
    await async_setup_entry(
        MagicMock(), entry, lambda new, update_before_add=False: added.extend(new)
    )

    energy = next(
        e
        for e in added
        if isinstance(e, MixergyEnergySensor) and e.unique_id == "T1_electric_energy"
    )
    cost = next(e for e in added if isinstance(e, MixergyElectricCostSensor))
    for sensor in (energy, cost):
        sensor.async_write_ha_state = MagicMock()
        sensor._last_update = time.time() - 60
        sensor._handle_coordinator_update()

    # 3 kW for one minute = 0.05 kWh, at 0.50 per kWh = 0.025.
    assert energy.native_value == pytest.approx(0.05, rel=0.05)
    assert cost.native_value == pytest.approx(0.025, rel=0.05)


async def test_diagnostics_record_the_power_source() -> None:
    """A diagnostics dump says which field backed electric power."""
    from custom_components.mixergy_tank.coordinator import MixergyCoordinator
    from custom_components.mixergy_tank.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    coordinator = MagicMock(spec=MixergyCoordinator)
    coordinator.data = TankData(
        measurement=TankMeasurement(
            immersion_energy_reported=True, immersion_power_w=2827.05
        )
    )
    coordinator.update_interval = timedelta(seconds=60)
    coordinator.last_update_success = True
    entry = MagicMock()
    entry.data = {"username": "u", "password": "p"}
    entry.options = {}
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(MagicMock(), entry)

    measurement = result["tank_data"]["measurement"]
    assert measurement["electric_power_source"] == "immersion_energy"
    assert measurement["immersion_power_w"] == 2827.05
