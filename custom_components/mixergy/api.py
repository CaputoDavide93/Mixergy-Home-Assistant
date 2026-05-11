"""Mixergy API client.

Standalone async API client for the Mixergy cloud API (v2).
Handles authentication, token lifecycle, and all tank operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_ROOT = "https://www.mixergy.io/api/v2"

# Token refresh buffer — refresh 5 minutes before expiry
TOKEN_REFRESH_BUFFER = 300
# Default token TTL if the API doesn't tell us (1 hour)
DEFAULT_TOKEN_TTL = 3600
# Per-request timeout: 30 s total prevents indefinite hangs
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class MixergyApiError(Exception):
    """Base exception for Mixergy API errors."""


class MixergyAuthError(MixergyApiError):
    """Authentication failed."""


class MixergyConnectionError(MixergyApiError):
    """Could not reach the Mixergy API."""


class MixergyTankNotFoundError(MixergyApiError):
    """Tank with the specified serial number was not found."""


class HeatSource(StrEnum):
    """Heat source types."""

    ELECTRIC = "electric"
    INDIRECT = "indirect"
    HEAT_PUMP = "heat_pump"
    NONE = "none"


class PVType(StrEnum):
    """PV diverter types."""

    NO_INVERTER = "NO_INVERTER"


# ── Format helpers ────────────────────────────────────────────────────────────

def _api_to_ha_heat_source(api_value: str) -> str:
    """Normalise API heat-source format to HA-facing format.

    The Mixergy API uses "heatpump" (no underscore) for the schedule's
    defaultHeatSource field, but the HA select/sensor entities use "heat_pump"
    (with underscore) to match their translation keys.
    """
    return "heat_pump" if api_value == "heatpump" else api_value


def _ha_to_api_heat_source(ha_value: str) -> str:
    """Normalise HA-facing heat-source format back to API format."""
    return "heatpump" if ha_value == "heat_pump" else ha_value


@dataclass
class TankMeasurement:
    """Snapshot of the latest tank measurement."""

    hot_water_temperature: float = 0.0
    coldest_water_temperature: float = 0.0
    charge: float = 0.0
    target_charge: float = 0.0
    electric_heat_source: bool = False
    indirect_heat_source: bool = False
    heatpump_heat_source: bool = False
    in_holiday_mode: bool = False
    pv_power_kw: float = 0.0
    clamp_power_w: float = 0.0
    active_heat_source: HeatSource = HeatSource.NONE
    is_heating: bool = False


@dataclass
class TankSettings:
    """Tank settings from the API."""

    target_temperature: float = 0.0
    dsr_enabled: bool = False
    frost_protection_enabled: bool = False
    distributed_computing_enabled: bool = False
    cleansing_temperature: float = 0.0
    divert_exported_enabled: bool = False
    pv_cut_in_threshold: float = 0.0
    pv_charge_limit: float = 0.0
    pv_target_current: float = 0.0
    pv_over_temperature: float = 0.0


@dataclass
class TankSchedule:
    """Tank schedule from the API."""

    raw: dict[str, Any] = field(default_factory=dict)
    holiday_start: datetime | None = None
    holiday_end: datetime | None = None
    default_heat_source: str = "electric"


@dataclass
class TankInfo:
    """Static tank information."""

    serial_number: str = ""
    model_code: str = ""
    firmware_version: str = "0.0.0"
    has_pv_diverter: bool = False


@dataclass
class TankData:
    """Complete tank data bundle returned by the coordinator."""

    info: TankInfo = field(default_factory=TankInfo)
    measurement: TankMeasurement = field(default_factory=TankMeasurement)
    settings: TankSettings = field(default_factory=TankSettings)
    schedule: TankSchedule = field(default_factory=TankSchedule)
    last_update_time: datetime | None = None


class MixergyApiClient:
    """Async API client for the Mixergy cloud API.

    This is a standalone client that does NOT depend on Home Assistant.
    It only requires an aiohttp.ClientSession.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        serial_number: str,
    ) -> None:
        """Initialise the API client."""
        self._session = session
        self._username = username
        self._password = password
        self._serial_number = serial_number.upper()

        # Auth state
        self._token: str | None = None
        self._token_expiry: float = 0.0

        # Discovered URLs (HATEOAS)
        self._login_url: str | None = None
        self._tanks_url: str | None = None
        self._tank_url: str | None = None
        self._measurement_url: str | None = None
        self._control_url: str | None = None
        self._settings_url: str | None = None
        self._schedule_url: str | None = None

        # Static info
        self._tank_info = TankInfo(serial_number=self._serial_number)

        # Concurrency guards
        self._auth_lock = asyncio.Lock()
        self._discover_lock = asyncio.Lock()

        # Last-known-good sub-fetch results. fetch_all() falls back to
        # these when settings/schedule sub-fetches fail transiently —
        # measurement (the primary signal) still updates; settings and
        # schedule are slow-changing and tolerate a brief miss without
        # blanking every entity to `unavailable`.
        self._last_settings: TankSettings | None = None
        self._last_schedule: TankSchedule | None = None

        # Serialises schedule read-modify-write operations
        # (set_holiday_dates, clear_holiday_dates, set_default_heat_source).
        # Each fetches the current schedule, mutates a field, and PUTs the
        # whole object back. Two near-simultaneous callers (UI button +
        # automation, or two automations firing on overlapping triggers)
        # could read the same starting point, mutate independent fields,
        # and overwrite each other — only one mutation wins. Lock makes
        # GET-mutate-PUT atomic from the integration's perspective.
        self._schedule_write_lock = asyncio.Lock()

    # ── Authentication ───────────────────────────────────────────────

    @property
    def _token_valid(self) -> bool:
        """Check if the current token is still valid."""
        return (
            self._token is not None
            and time.time() < self._token_expiry - TOKEN_REFRESH_BUFFER
        )

    async def _discover_login_url(self) -> None:
        """Walk the HATEOAS links to find the login endpoint."""
        if self._login_url is not None:
            return

        try:
            async with self._session.get(
                API_ROOT, ssl=True, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise MixergyConnectionError(
                        f"Root endpoint returned {resp.status}"
                    )
                root = await resp.json()
                account_url = root["_links"]["account"]["href"]

            async with self._session.get(
                account_url, ssl=True, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise MixergyConnectionError(
                        f"Account endpoint returned {resp.status}"
                    )
                account = await resp.json()
                self._login_url = account["_links"]["login"]["href"]

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as err:
            raise MixergyConnectionError(
                f"Failed to discover login URL: {err}"
            ) from err

    async def authenticate(self) -> bool:
        """Authenticate with the Mixergy API and obtain a token.

        Returns True on success. Raises MixergyAuthError on failure.
        """
        async with self._auth_lock:
            # Re-check inside the lock — a peer coroutine may have refreshed
            # while we were waiting.
            if self._token_valid:
                return True

            # Clear stale token
            self._token = None
            self._token_expiry = 0.0

            await self._discover_login_url()

            try:
                assert self._login_url is not None
                async with self._session.post(
                    self._login_url,
                    json={"username": self._username, "password": self._password},
                    ssl=True,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == 401 or resp.status == 403:
                        raise MixergyAuthError("Invalid username or password")
                    if resp.status != 201:
                        raise MixergyAuthError(
                            f"Authentication failed with status {resp.status}"
                        )

                    data = await resp.json()
                    self._token = data["token"]

                    # Use token TTL from API response if available
                    ttl = data.get("ttl", DEFAULT_TOKEN_TTL)
                    self._token_expiry = time.time() + ttl

                    _LOGGER.debug("Authenticated successfully, token TTL=%s", ttl)
                    return True

            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise MixergyConnectionError(
                    f"Authentication request failed: {err}"
                ) from err

    def invalidate_token(self) -> None:
        """Force token invalidation (e.g. after a 401 during polling)."""
        self._token = None
        self._token_expiry = 0.0

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Get authorization headers."""
        return {"Authorization": f"Bearer {self._token}"}

    # ── Tank Discovery ───────────────────────────────────────────────

    async def _ensure_authenticated(self) -> None:
        """Make sure we have a valid token, re-authenticating if needed."""
        if not self._token_valid:
            await self.authenticate()

    async def _discover_tank(self) -> None:
        """Discover the tank URLs from the API (HATEOAS walk)."""
        # Fast path — already discovered.
        if self._measurement_url is not None:
            return

        async with self._discover_lock:
            # Re-check after acquiring the lock; concurrent first-refresh
            # callers (gather of measurement/settings/schedule) would
            # otherwise each issue a full HATEOAS walk.
            if self._measurement_url is not None:
                return

            await self._ensure_authenticated()

            try:
                # Get tanks list URL from root
                async with self._session.get(
                    API_ROOT, headers=self._auth_headers, ssl=True, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        raise MixergyConnectionError(
                            f"Root endpoint returned {resp.status}"
                        )
                    root = await resp.json()
                    self._tanks_url = root["_links"]["tanks"]["href"]

                # Get list of tanks
                async with self._session.get(
                    self._tanks_url, headers=self._auth_headers, ssl=True, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        raise MixergyConnectionError(
                            f"Tanks endpoint returned {resp.status}"
                        )
                    data = await resp.json()
                    tanks = data["_embedded"]["tankList"]

                # Find our tank
                tank = None
                for t in tanks:
                    if t["serialNumber"].upper() == self._serial_number:
                        tank = t
                        break

                if tank is None:
                    raise MixergyTankNotFoundError(
                        f"No tank with serial number {self._serial_number}"
                    )

                self._tank_info.firmware_version = tank.get(
                    "firmwareVersion", "0.0.0"
                )

                # Get detailed tank info
                tank_url = tank["_links"]["self"]["href"]
                async with self._session.get(
                    tank_url, headers=self._auth_headers, ssl=True, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        raise MixergyConnectionError(
                            f"Tank detail endpoint returned {resp.status}"
                        )
                    detail = await resp.json()

                # Validate required HATEOAS links before accessing them
                links = detail.get("_links", {})
                for link_name in ("latest_measurement", "control", "settings", "schedule"):
                    href = links.get(link_name, {}).get("href")
                    if not href:
                        raise MixergyConnectionError(
                            f"Missing required API link '{link_name}' in tank detail response"
                        )
                    # Defence-in-depth: HATEOAS links come from the cloud
                    # API response. A compromised or misconfigured upstream
                    # could serve http:// links; we'd then silently
                    # downgrade and leak the bearer token over plaintext.
                    # aiohttp `ssl=True` only enforces TLS WHEN the URL is
                    # https:// — http:// urls happily skip TLS entirely.
                    if not href.startswith("https://"):
                        raise MixergyConnectionError(
                            f"API link '{link_name}' is not HTTPS: {href[:60]} "
                            "(refusing to leak bearer token over plaintext)"
                        )

                self._measurement_url = links["latest_measurement"]["href"]
                self._control_url = links["control"]["href"]
                self._settings_url = links["settings"]["href"]
                self._schedule_url = links["schedule"]["href"]

                self._tank_info.model_code = detail.get("tankModelCode", "Unknown")

                # Parse PV diverter presence
                config_json = detail.get("configuration", "{}")
                try:
                    config = json.loads(config_json)
                    pv_type = config.get("mixergyPvType", "NO_INVERTER")
                    self._tank_info.has_pv_diverter = pv_type != "NO_INVERTER"
                except (json.JSONDecodeError, TypeError):
                    self._tank_info.has_pv_diverter = False

                _LOGGER.debug(
                    "Tank discovered: model=%s, fw=%s, pv=%s",
                    self._tank_info.model_code,
                    self._tank_info.firmware_version,
                    self._tank_info.has_pv_diverter,
                )

            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise MixergyConnectionError(
                    f"Failed to discover tank: {err}"
                ) from err

    # ── Data Fetching ────────────────────────────────────────────────

    async def _request_with_reauth(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make an API request, re-authenticating on 401.

        Only ``json=<dict>`` request bodies are supported (we replay
        ``kwargs`` verbatim on the 401 retry). Passing ``data=<stream>``
        or any other one-shot body would silently send an empty payload
        on the second attempt — assert on import-time-detectable misuse
        so a future caller can't introduce that footgun unnoticed.
        """
        if "data" in kwargs:
            raise TypeError(
                "_request_with_reauth: pass `json=<dict>` instead of "
                "`data=...`; the retry path replays kwargs and one-shot "
                "streams would be exhausted on the first attempt"
            )
        await self._ensure_authenticated()

        resp = await self._session.request(
            method, url, headers=self._auth_headers, ssl=True,
            timeout=REQUEST_TIMEOUT, **kwargs
        )

        if resp.status == 401:
            _LOGGER.debug("Got 401, re-authenticating...")
            resp.release()
            self.invalidate_token()
            await self.authenticate()
            resp = await self._session.request(
                method, url, headers=self._auth_headers, ssl=True,
                timeout=REQUEST_TIMEOUT, **kwargs
            )

        # 404/410 on a discovered HATEOAS URL means the cached link is
        # stale — the cloud API rotated endpoints or the tank firmware
        # update changed the URL shape. Without this guard the
        # coordinator kept hitting the dead URL every poll forever, and
        # the only user remedy was to reload the integration. Clear the
        # cached discovery so the NEXT call re-runs _discover_tank().
        if resp.status in (404, 410):
            _LOGGER.warning(
                "Mixergy URL %s returned %s — clearing cached HATEOAS "
                "discovery so the next request re-discovers",
                url, resp.status,
            )
            self._measurement_url = None
            self._control_url = None
            self._settings_url = None
            self._schedule_url = None
            # tank_url is keyed by serial so it survives — only the
            # per-tank sub-endpoints can rotate independently.

        return resp

    async def fetch_measurement(self) -> TankMeasurement:
        """Fetch the latest measurement from the tank."""
        await self._discover_tank()

        assert self._measurement_url is not None
        async with await self._request_with_reauth(
            "GET", self._measurement_url
        ) as resp:
            if resp.status != 200:
                raise MixergyConnectionError(
                    f"Measurement fetch failed: {resp.status}"
                )
            data = await resp.json()

        measurement = TankMeasurement(
            hot_water_temperature=data.get("topTemperature", 0.0),
            coldest_water_temperature=data.get("bottomTemperature", 0.0),
            charge=data.get("charge", 0.0),
        )

        # PV power: API returns energy in joules per minute
        if "pvEnergy" in data:
            measurement.pv_power_kw = data["pvEnergy"] / 60000
        if "clampPower" in data:
            measurement.clamp_power_w = data["clampPower"]

        # Parse state JSON
        try:
            state = json.loads(data.get("state", "{}"))
            current = state.get("current", {})

            measurement.target_charge = current.get("target", 0)

            # Holiday mode
            source = current.get("source", "")
            measurement.in_holiday_mode = source == "Vacation"

            if not measurement.in_holiday_mode:
                heat_source_str = current.get("heat_source", "none").lower()
                immersion_on = current.get("immersion", "off").lower() == "on"

                if heat_source_str == "indirect":
                    measurement.active_heat_source = HeatSource.INDIRECT
                    measurement.indirect_heat_source = immersion_on
                    measurement.is_heating = immersion_on
                elif heat_source_str == "electric":
                    measurement.active_heat_source = HeatSource.ELECTRIC
                    measurement.electric_heat_source = immersion_on
                    measurement.is_heating = immersion_on
                elif heat_source_str == "heatpump":
                    measurement.active_heat_source = HeatSource.HEAT_PUMP
                    measurement.heatpump_heat_source = immersion_on
                    measurement.is_heating = immersion_on
                else:
                    measurement.active_heat_source = HeatSource.NONE

        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.warning("Failed to parse measurement state: %s", err)

        return measurement

    async def fetch_settings(self) -> TankSettings:
        """Fetch tank settings."""
        await self._discover_tank()

        assert self._settings_url is not None
        async with await self._request_with_reauth(
            "GET", self._settings_url
        ) as resp:
            if resp.status != 200:
                raise MixergyConnectionError(
                    f"Settings fetch failed: {resp.status}"
                )
            # Settings endpoint returns text/plain content-type
            text = await resp.text()
            data = json.loads(text)

        settings = TankSettings(
            target_temperature=data.get("max_temp", 0.0),
            dsr_enabled=data.get("dsr_enabled", False),
            frost_protection_enabled=data.get("frost_protection_enabled", False),
            distributed_computing_enabled=data.get(
                "distributed_computing_enabled", False
            ),
            cleansing_temperature=data.get("cleansing_temperature", 0.0),
        )

        # PV settings may not exist on all tanks
        settings.divert_exported_enabled = data.get(
            "divert_exported_enabled", False
        )
        settings.pv_cut_in_threshold = data.get("pv_cut_in_threshold", 0.0)
        settings.pv_charge_limit = data.get("pv_charge_limit", 0.0)
        settings.pv_target_current = data.get("pv_target_current", 0.0)
        settings.pv_over_temperature = data.get("pv_over_temperature", 0.0)

        return settings

    async def fetch_schedule(self) -> TankSchedule:
        """Fetch tank schedule."""
        await self._discover_tank()

        assert self._schedule_url is not None
        async with await self._request_with_reauth(
            "GET", self._schedule_url
        ) as resp:
            if resp.status != 200:
                raise MixergyConnectionError(
                    f"Schedule fetch failed: {resp.status}"
                )
            text = await resp.text()
            data = json.loads(text)

        schedule = TankSchedule(raw=data)

        # Normalise "heatpump" (API) → "heat_pump" (HA) so the select entity
        # and default_heat_source sensor always show the HA-canonical value.
        raw_heat_source = data.get("defaultHeatSource", "electric")
        schedule.default_heat_source = _api_to_ha_heat_source(raw_heat_source)

        holiday = data.get("holiday")
        if holiday:
            try:
                depart = holiday.get("departDate")
                ret = holiday.get("returnDate")
                if depart:
                    schedule.holiday_start = datetime.fromtimestamp(
                        depart / 1000, tz=timezone.utc
                    )
                if ret:
                    schedule.holiday_end = datetime.fromtimestamp(
                        ret / 1000, tz=timezone.utc
                    )
            except (TypeError, ValueError, OSError):
                pass

        return schedule

    async def fetch_all(self) -> TankData:
        """Fetch all tank data in one call (used by coordinator).

        Tolerant of partial failure: a single failing endpoint (e.g.
        rate-limited schedule) used to fail the entire poll and blank
        every entity to `unavailable` for one cycle. Now, measurement
        is the primary signal (must succeed); settings + schedule fall
        back to the previous successfully-fetched values if their
        sub-fetch raises. Tank charge/temperature is what users care
        about most — settings/schedule change slowly and can ride a
        brief upstream hiccup without blanking the device card.
        """
        await self._discover_tank()

        results = await asyncio.gather(
            self.fetch_measurement(),
            self.fetch_settings(),
            self.fetch_schedule(),
            return_exceptions=True,
        )
        measurement, settings, schedule = results

        # Measurement is the primary signal — bubble up if it failed.
        if isinstance(measurement, BaseException):
            raise measurement

        # Settings / schedule: fall back to previous values on failure.
        if isinstance(settings, BaseException):
            _LOGGER.warning(
                "Mixergy settings fetch failed (using cached): %s", settings
            )
            settings = self._last_settings
            if settings is None:
                # No prior good fetch — let it propagate.
                raise results[1]
        else:
            self._last_settings = settings

        if isinstance(schedule, BaseException):
            _LOGGER.warning(
                "Mixergy schedule fetch failed (using cached): %s", schedule
            )
            schedule = self._last_schedule
            if schedule is None:
                raise results[2]
        else:
            self._last_schedule = schedule

        return TankData(
            info=TankInfo(
                serial_number=self._serial_number,
                model_code=self._tank_info.model_code,
                firmware_version=self._tank_info.firmware_version,
                has_pv_diverter=self._tank_info.has_pv_diverter,
            ),
            measurement=measurement,
            settings=settings,
            schedule=schedule,
        )

    # ── Tank info ────────────────────────────────────────────────────

    @property
    def tank_info(self) -> TankInfo:
        """Get static tank info (available after first fetch)."""
        return self._tank_info

    # ── Commands (Write Operations) ──────────────────────────────────

    async def set_target_charge(self, charge: int) -> None:
        """Set the desired charge level (0-100)."""
        await self._discover_tank()
        charge = max(0, min(100, charge))

        assert self._control_url is not None
        async with await self._request_with_reauth(
            "PUT",
            self._control_url,
            json={"charge": charge},
        ) as resp:
            if resp.status != 200:
                raise MixergyApiError(
                    f"Set target charge failed: {resp.status}"
                )

    async def set_target_temperature(self, temperature: int) -> None:
        """Set target temperature (45-70°C)."""
        await self._discover_tank()
        temperature = max(45, min(70, temperature))

        assert self._settings_url is not None
        async with await self._request_with_reauth(
            "PUT",
            self._settings_url,
            json={"max_temp": temperature},
        ) as resp:
            if resp.status != 200:
                raise MixergyApiError(
                    f"Set target temperature failed: {resp.status}"
                )

    async def set_setting(self, key: str, value: Any) -> None:
        """Set a single tank setting by key."""
        await self._discover_tank()

        assert self._settings_url is not None
        async with await self._request_with_reauth(
            "PUT",
            self._settings_url,
            json={key: value},
        ) as resp:
            if resp.status != 200:
                raise MixergyApiError(
                    f"Set setting '{key}' failed: {resp.status}"
                )

    async def set_dsr_enabled(self, enabled: bool) -> None:
        """Enable/disable DSR (grid assistance)."""
        await self.set_setting("dsr_enabled", enabled)

    async def set_frost_protection_enabled(self, enabled: bool) -> None:
        """Enable/disable frost protection."""
        await self.set_setting("frost_protection_enabled", enabled)

    async def set_distributed_computing_enabled(self, enabled: bool) -> None:
        """Enable/disable distributed computing (medical research)."""
        await self.set_setting("distributed_computing_enabled", enabled)

    async def set_cleansing_temperature(self, value: int) -> None:
        """Set cleansing temperature (51-55°C)."""
        value = max(51, min(55, value))
        await self.set_setting("cleansing_temperature", value)

    async def set_divert_exported_enabled(self, enabled: bool) -> None:
        """Enable/disable PV export divert."""
        await self.set_setting("divert_exported_enabled", enabled)

    async def set_pv_cut_in_threshold(self, value: int) -> None:
        """Set PV cut-in threshold (0-500W)."""
        value = max(0, min(500, value))
        await self.set_setting("pv_cut_in_threshold", value)

    async def set_pv_charge_limit(self, value: int) -> None:
        """Set PV charge limit (0-100%)."""
        value = max(0, min(100, value))
        await self.set_setting("pv_charge_limit", value)

    async def set_pv_target_current(self, value: float) -> None:
        """Set PV target current (-1 to 0)."""
        value = max(-1.0, min(0.0, value))
        await self.set_setting("pv_target_current", value)

    async def set_pv_over_temperature(self, value: int) -> None:
        """Set PV over-temperature limit (45-60°C)."""
        value = max(45, min(60, value))
        await self.set_setting("pv_over_temperature", value)

    async def set_holiday_dates(
        self, start: datetime, end: datetime
    ) -> None:
        """Set holiday mode dates.

        Naive datetimes (no tzinfo) are interpreted as UTC (matching
        fetch_schedule's tz=UTC read). Aware datetimes are converted
        explicitly. Both write and read now agree on timezone.

        Serialised on _schedule_write_lock — see __init__.
        """
        await self._discover_tank()

        def _to_utc_epoch_ms(d: datetime) -> int:
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return int(d.astimezone(timezone.utc).timestamp() * 1000)

        async with self._schedule_write_lock:
            schedule_data = await self.fetch_schedule()
            raw = schedule_data.raw

            raw["holiday"] = {
                "departDate": _to_utc_epoch_ms(start),
                "returnDate": _to_utc_epoch_ms(end),
            }

            assert self._schedule_url is not None
            async with await self._request_with_reauth(
                "PUT",
                self._schedule_url,
                json=raw,
            ) as resp:
                if resp.status != 200:
                    raise MixergyApiError(
                        f"Set holiday dates failed: {resp.status}"
                    )

    async def clear_holiday_dates(self) -> None:
        """Clear holiday mode. Serialised on _schedule_write_lock."""
        await self._discover_tank()

        async with self._schedule_write_lock:
            schedule_data = await self.fetch_schedule()
            raw = schedule_data.raw
            raw.pop("holiday", None)

            assert self._schedule_url is not None
            async with await self._request_with_reauth(
                "PUT",
                self._schedule_url,
                json=raw,
            ) as resp:
                if resp.status != 200:
                    raise MixergyApiError(
                        f"Clear holiday dates failed: {resp.status}"
                    )

    async def set_default_heat_source(self, heat_source: str) -> None:
        """Set the default heat source (electric / indirect / heat_pump).

        Accepts HA-canonical values ("heat_pump") and normalises to the API
        format ("heatpump") before sending. Serialised on _schedule_write_lock.
        """
        await self._discover_tank()

        async with self._schedule_write_lock:
            schedule_data = await self.fetch_schedule()
            raw = schedule_data.raw
            raw["defaultHeatSource"] = _ha_to_api_heat_source(heat_source)

            assert self._schedule_url is not None
            async with await self._request_with_reauth(
                "PUT",
                self._schedule_url,
                json=raw,
            ) as resp:
                if resp.status != 200:
                    raise MixergyApiError(
                        f"Set default heat source failed: {resp.status}"
                    )

    # ── Connection Testing ───────────────────────────────────────────

    async def test_credentials(self) -> bool:
        """Test that the credentials are valid. Returns True or raises."""
        self.invalidate_token()
        self._login_url = None  # Force re-discovery
        await self.authenticate()
        return True

    async def test_connection(self) -> bool:
        """Test that the serial number is valid. Returns True or raises."""
        self._measurement_url = None  # Force re-discovery
        await self._discover_tank()
        return True
