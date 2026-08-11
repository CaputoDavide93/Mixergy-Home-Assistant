"""Mixergy API client.

Standalone async API client for the Mixergy cloud API (v2).
Handles authentication, token lifecycle, and all tank operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_ROOT = "https://www.mixergy.io/api/v2"

# Host we are willing to send the bearer token to. HATEOAS links are
# attacker-influenceable (a compromised/misconfigured upstream could serve
# off-host or http:// links); restrict to the Mixergy origin.
_ALLOWED_API_HOST = "www.mixergy.io"

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

def _require_object(
    value: Any,
    context: str,
    error_type: type[MixergyApiError] = MixergyConnectionError,
) -> dict[str, Any]:
    """Require a decoded JSON object and keep schema faults typed."""
    if not isinstance(value, dict):
        raise error_type(f"{context} was not a JSON object")
    return value


def _require_array(value: Any, context: str) -> list[Any]:
    """Require a decoded JSON array and keep schema faults typed."""
    if not isinstance(value, list):
        raise MixergyConnectionError(f"{context} was not a JSON array")
    return value

def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce an API value to a finite float, else return default.

    Cloud responses occasionally carry null, strings, or non-finite numbers;
    feeding those straight into entities (or the energy integrator) produces
    bad states. Normalise at the boundary.
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _as_bool(value: Any, default: bool = False) -> bool:
    """Coerce common API boolean encodings without treating "false" as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    return default


def _require_safe_link(href: Any, link_name: str) -> str:
    """Validate a discovered HATEOAS link before we send a token to it.

    aiohttp ``ssl=True`` only enforces TLS *when* the URL is https://; an
    http:// link silently downgrades and leaks the bearer token over
    plaintext, and an off-host link exfiltrates it to a third party. Reject
    anything that isn't https:// on the Mixergy origin.
    """
    if not isinstance(href, str) or not href:
        raise MixergyConnectionError(
            f"Missing required API link '{link_name}'"
        )
    try:
        parsed = urlparse(href)
    except ValueError as err:
        # urlparse itself raises for malformed URLs (e.g. an unclosed IPv6
        # bracket). Attacker-influenceable input must stay inside the
        # MixergyApiError taxonomy — an untyped ValueError would escape as a
        # raw traceback from the coordinator and as "unknown" in the flows.
        raise MixergyConnectionError(
            f"API link '{link_name}' is not a parseable URL"
        ) from err
    if parsed.scheme != "https":
        raise MixergyConnectionError(
            f"API link '{link_name}' is not HTTPS: {href[:60]} "
            "(refusing to leak bearer token over plaintext)"
        )
    host = parsed.hostname or ""
    if host != _ALLOWED_API_HOST:
        raise MixergyConnectionError(
            f"API link '{link_name}' points to unexpected host "
            f"'{host}' (refusing to send token off the Mixergy origin)"
        )
    if parsed.username is not None or parsed.password is not None:
        raise MixergyConnectionError(
            f"API link '{link_name}' contains user information "
            "(refusing an ambiguous credential-bearing URL)"
        )
    try:
        port = parsed.port
    except ValueError as err:
        raise MixergyConnectionError(
            f"API link '{link_name}' contains an invalid port"
        ) from err
    if port not in (None, 443):
        raise MixergyConnectionError(
            f"API link '{link_name}' uses unexpected port {port}"
        )
    return href


def _require_link(links: dict[str, Any], link_name: str) -> str:
    """Extract and validate one HATEOAS link object."""
    raw_link = links.get(link_name)
    if raw_link is None:
        return _require_safe_link(None, link_name)
    link = _require_object(raw_link, f"API link '{link_name}'")
    return _require_safe_link(link.get("href"), link_name)


def _api_to_ha_heat_source(api_value: Any) -> str:
    """Normalise API heat-source format to HA-facing format.

    The Mixergy API uses "heatpump" (no underscore) for the schedule's
    defaultHeatSource field, but the HA select/sensor entities use "heat_pump"
    (with underscore) to match their translation keys.
    """
    if not isinstance(api_value, str):
        raise MixergyConnectionError(
            "Schedule defaultHeatSource was not a string"
        )
    if api_value not in {"electric", "indirect", "heatpump"}:
        raise MixergyConnectionError(
            f"Unsupported schedule heat source: {api_value}"
        )
    return "heat_pump" if api_value == "heatpump" else api_value


# The writable heat sources, derived from the enum so a new source added
# there (and to const.HEAT_SOURCE_OPTIONS for the select) is accepted here
# without a third hand-typed copy of the list.
_WRITABLE_HEAT_SOURCES = frozenset(
    hs.value for hs in HeatSource if hs is not HeatSource.NONE
)


def _ha_to_api_heat_source(ha_value: str) -> str:
    """Normalise HA-facing heat-source format back to API format."""
    if ha_value not in _WRITABLE_HEAT_SOURCES:
        raise MixergyApiError(f"Unsupported heat source: {ha_value}")
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
                API_ROOT,
                ssl=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    raise MixergyConnectionError(
                        f"Root endpoint returned {resp.status}"
                    )
                root = _require_object(await resp.json(), "Root response")
                root_links = _require_object(root.get("_links"), "Root links")
                account_url = _require_link(root_links, "account")

            async with self._session.get(
                account_url,
                ssl=True,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    raise MixergyConnectionError(
                        f"Account endpoint returned {resp.status}"
                    )
                account = _require_object(await resp.json(), "Account response")
                account_links = _require_object(
                    account.get("_links"), "Account links"
                )
                self._login_url = _require_link(account_links, "login")

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError,
                json.JSONDecodeError) as err:
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

            login_url = self._require_url(self._login_url, "login")
            try:
                async with self._session.post(
                    login_url,
                    json={"username": self._username, "password": self._password},
                    ssl=True,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                ) as resp:
                    if resp.status == 401 or resp.status == 403:
                        raise MixergyAuthError("Invalid username or password")
                    if resp.status != 201:
                        raise MixergyAuthError(
                            f"Authentication failed with status {resp.status}"
                        )

                    data = _require_object(
                        await resp.json(),
                        "Authentication response",
                        MixergyAuthError,
                    )
                    token = data.get("token")
                    if not isinstance(token, str) or not token:
                        raise MixergyAuthError(
                            "Authentication response missing a valid token"
                        )
                    self._token = token

                    # Use token TTL from API response if available, but don't
                    # trust it blindly: a non-numeric/zero TTL would crash the
                    # arithmetic, and a TTL below the refresh buffer would make
                    # the token instantly "expired" — forcing a fresh login on
                    # every request and risking API throttling. Clamp it.
                    ttl = data.get("ttl", DEFAULT_TOKEN_TTL)
                    if not isinstance(ttl, (int, float)) or ttl <= 0:
                        ttl = DEFAULT_TOKEN_TTL
                    ttl = max(ttl, TOKEN_REFRESH_BUFFER * 2)
                    self._token_expiry = time.time() + ttl

                    _LOGGER.debug("Authenticated successfully, token TTL=%s", ttl)
                    return True

            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise MixergyConnectionError(
                    f"Authentication request failed: {err}"
                ) from err
            except (json.JSONDecodeError, ValueError) as err:
                raise MixergyAuthError(
                    f"Malformed authentication response: {err}"
                ) from err

    def invalidate_token(self) -> None:
        """Force token invalidation (e.g. after a 401 during polling)."""
        self._token = None
        self._token_expiry = 0.0

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Get authorization headers."""
        return {"Authorization": f"Bearer {self._token}"}

    def _require_url(self, url: str | None, name: str) -> str:
        """Snapshot a discovered URL, raising a typed error when absent.

        fetch_all() gathers three sub-fetches concurrently, and the 404/410
        handler in _request_with_reauth nulls the whole discovery cache
        mid-flight. A sibling sub-fetch that already passed _discover_tank()'s
        fast path can then observe a None URL. An `assert` here would (a)
        escape the MixergyApiError taxonomy — the coordinator would log an
        untyped traceback instead of a clean UpdateFailed — and (b) be
        stripped entirely under `python -O`, passing None to aiohttp.
        MixergyConnectionError retries cleanly on the next poll, which
        re-runs discovery.
        """
        if url is None:
            raise MixergyConnectionError(
                f"Discovered URL for '{name}' is no longer cached; "
                "the next request will re-discover"
            )
        return url

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
                # Get tanks list URL from root. Authenticated discovery now
                # goes through _request_with_reauth so a server-side token
                # revocation is retried/surfaced as MixergyAuthError instead
                # of being misreported as a connectivity failure.
                async with await self._request_with_reauth(
                    "GET", API_ROOT
                ) as resp:
                    if resp.status != 200:
                        raise MixergyConnectionError(
                            f"Root endpoint returned {resp.status}"
                        )
                    root = _require_object(await resp.json(), "Root response")
                    root_links = _require_object(root.get("_links"), "Root links")
                    self._tanks_url = _require_link(root_links, "tanks")

                # Get list of tanks
                async with await self._request_with_reauth(
                    "GET", self._tanks_url
                ) as resp:
                    if resp.status != 200:
                        raise MixergyConnectionError(
                            f"Tanks endpoint returned {resp.status}"
                        )
                    data = _require_object(await resp.json(), "Tanks response")
                    embedded = _require_object(
                        data.get("_embedded"), "Tanks embedded data"
                    )
                    tanks = _require_array(embedded.get("tankList"), "Tank list")

                # Find our tank
                tank = None
                for raw_tank in tanks:
                    t = _require_object(raw_tank, "Tank list entry")
                    serial = t.get("serialNumber")
                    if (
                        isinstance(serial, str)
                        and serial.strip().upper() == self._serial_number
                    ):
                        tank = t
                        break

                if tank is None:
                    raise MixergyTankNotFoundError(
                        f"No tank with serial number {self._serial_number}"
                    )

                firmware_version = tank.get("firmwareVersion", "0.0.0")
                if not isinstance(firmware_version, str):
                    firmware_version = "0.0.0"

                # Get detailed tank info
                tank_links = _require_object(
                    tank.get("_links"), "Tank list entry links"
                )
                tank_url = _require_link(tank_links, "self")
                async with await self._request_with_reauth(
                    "GET", tank_url
                ) as resp:
                    if resp.status != 200:
                        raise MixergyConnectionError(
                            f"Tank detail endpoint returned {resp.status}"
                        )
                    detail = _require_object(
                        await resp.json(), "Tank detail response"
                    )

                # Validate every required HATEOAS link (https + Mixergy host)
                # before we cache it and start sending the bearer token to it.
                links = _require_object(detail.get("_links"), "Tank detail links")
                measurement_url = _require_link(links, "latest_measurement")
                control_url = _require_link(links, "control")
                settings_url = _require_link(links, "settings")
                schedule_url = _require_link(links, "schedule")

                model_code = detail.get("tankModelCode", "Unknown")
                if not isinstance(model_code, str):
                    model_code = "Unknown"

                # Parse PV diverter presence
                config_json = detail.get("configuration", "{}")
                has_pv_diverter = False
                try:
                    config = json.loads(config_json)
                    if isinstance(config, dict):
                        pv_type = config.get("mixergyPvType", "NO_INVERTER")
                        has_pv_diverter = (
                            isinstance(pv_type, str)
                            and pv_type != "NO_INVERTER"
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

                # Publish discovery atomically only after every required link
                # and metadata field has validated. A failed late link must not
                # make the measurement-only fast path skip future discovery.
                self._measurement_url = measurement_url
                self._control_url = control_url
                self._settings_url = settings_url
                self._schedule_url = schedule_url
                self._tank_info.firmware_version = firmware_version
                self._tank_info.model_code = model_code
                self._tank_info.has_pv_diverter = has_pv_diverter

                _LOGGER.debug(
                    "Tank discovered: model=%s, fw=%s, pv=%s",
                    self._tank_info.model_code,
                    self._tank_info.firmware_version,
                    self._tank_info.has_pv_diverter,
                )

            except (aiohttp.ClientError, asyncio.TimeoutError,
                    json.JSONDecodeError, KeyError) as err:
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

        # Network-layer failures (DNS, TLS, connection reset, timeout) must
        # be normalised to MixergyConnectionError here — otherwise a raw
        # aiohttp.ClientError escapes the API boundary during polling and
        # the coordinator (which only knows MixergyApiError subclasses)
        # surfaces an untyped traceback instead of a clean UpdateFailed.
        try:
            resp = await self._session.request(
                method, url, headers=self._auth_headers, ssl=True,
                timeout=REQUEST_TIMEOUT, allow_redirects=False, **kwargs
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise MixergyConnectionError(
                f"Request to {url} failed: {err}"
            ) from err

        if resp.status == 401:
            _LOGGER.debug("Got 401, re-authenticating...")
            resp.release()
            self.invalidate_token()
            await self.authenticate()
            try:
                resp = await self._session.request(
                    method, url, headers=self._auth_headers, ssl=True,
                    timeout=REQUEST_TIMEOUT, allow_redirects=False, **kwargs
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise MixergyConnectionError(
                    f"Request to {url} failed after re-auth: {err}"
                ) from err

        # Still rejected after a fresh login (or a 403 the retry can't fix):
        # the credentials are genuinely bad/revoked. Surface MixergyAuthError
        # so the coordinator opens HA's reauth flow, instead of looping on a
        # retryable MixergyConnectionError forever.
        if resp.status in (401, 403):
            resp.release()
            self.invalidate_token()
            raise MixergyAuthError(
                f"Authentication rejected for {url} (status {resp.status})"
            )

        # 404/410 on a discovered HATEOAS URL means the cached link is
        # stale — the cloud API rotated endpoints or the tank firmware
        # update changed the URL shape. Without this guard the
        # coordinator kept hitting the dead URL every poll forever, and
        # the only user remedy was to reload the integration. Clear the
        # cached discovery so the NEXT call re-runs _discover_tank().
        #
        # 3xx joins the list because redirects are never followed
        # (allow_redirects=False, so a redirect can't replay the bearer
        # token elsewhere): a permanent redirect on a cached endpoint is
        # the same "this URL moved" signal as a 404 — without clearing,
        # an endpoint rotation signalled via 301/308 would fail every
        # poll forever, the exact failure mode this guard exists for.
        # The response still propagates as a non-200 to the caller; the
        # NEXT poll walks discovery and picks up the new links.
        if resp.status in (301, 302, 303, 307, 308, 404, 410):
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

        url = self._require_url(self._measurement_url, "measurement")
        async with await self._request_with_reauth("GET", url) as resp:
            if resp.status != 200:
                raise MixergyConnectionError(
                    f"Measurement fetch failed: {resp.status}"
                )
            try:
                data = _require_object(
                    await resp.json(), "Measurement response"
                )
            except (aiohttp.ClientError, ValueError) as err:
                raise MixergyConnectionError(
                    f"Measurement response was not valid JSON: {err}"
                ) from err

        measurement = TankMeasurement(
            hot_water_temperature=_as_float(data.get("topTemperature")),
            coldest_water_temperature=_as_float(data.get("bottomTemperature")),
            charge=_as_float(data.get("charge")),
        )

        # PV power: API returns energy in joules per minute
        if "pvEnergy" in data:
            measurement.pv_power_kw = _as_float(data["pvEnergy"]) / 60000
        if "clampPower" in data:
            measurement.clamp_power_w = _as_float(data["clampPower"])

        # Parse state JSON
        try:
            state = json.loads(data.get("state", "{}"))
            current = state.get("current", {})

            measurement.target_charge = _as_float(current.get("target"))

            # Holiday mode
            source = current.get("source", "")
            measurement.in_holiday_mode = source == "Vacation"

            if not measurement.in_holiday_mode:
                # `or` (not the .get default) guards against an explicit null
                # value for these keys — .get only substitutes when the key is
                # absent, so a present-but-None value would crash on .lower().
                heat_source_str = (current.get("heat_source") or "none").lower()
                immersion_on = (current.get("immersion") or "off").lower() == "on"

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

        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as err:
            _LOGGER.warning("Failed to parse measurement state: %s", err)

        return measurement

    async def fetch_settings(self) -> TankSettings:
        """Fetch tank settings."""
        await self._discover_tank()

        url = self._require_url(self._settings_url, "settings")
        async with await self._request_with_reauth("GET", url) as resp:
            if resp.status != 200:
                raise MixergyConnectionError(
                    f"Settings fetch failed: {resp.status}"
                )
            # Settings endpoint returns text/plain content-type
            try:
                text = await resp.text()
                data = _require_object(
                    json.loads(text), "Settings response"
                )
            except (aiohttp.ClientError, ValueError) as err:
                raise MixergyConnectionError(
                    f"Settings response was not valid JSON: {err}"
                ) from err

        settings = TankSettings(
            target_temperature=_as_float(data.get("max_temp")),
            dsr_enabled=_as_bool(data.get("dsr_enabled")),
            frost_protection_enabled=_as_bool(
                data.get("frost_protection_enabled", False)
            ),
            distributed_computing_enabled=_as_bool(
                data.get("distributed_computing_enabled", False)
            ),
            cleansing_temperature=_as_float(data.get("cleansing_temperature")),
        )

        # PV settings may not exist on all tanks
        settings.divert_exported_enabled = _as_bool(
            data.get("divert_exported_enabled")
        )
        settings.pv_cut_in_threshold = _as_float(data.get("pv_cut_in_threshold"))
        settings.pv_charge_limit = _as_float(data.get("pv_charge_limit"))
        settings.pv_target_current = _as_float(data.get("pv_target_current"))
        settings.pv_over_temperature = _as_float(data.get("pv_over_temperature"))

        return settings

    async def fetch_schedule(self) -> TankSchedule:
        """Fetch tank schedule."""
        await self._discover_tank()

        url = self._require_url(self._schedule_url, "schedule")
        async with await self._request_with_reauth("GET", url) as resp:
            if resp.status != 200:
                raise MixergyConnectionError(
                    f"Schedule fetch failed: {resp.status}"
                )
            try:
                text = await resp.text()
                data = _require_object(
                    json.loads(text), "Schedule response"
                )
            except (aiohttp.ClientError, ValueError) as err:
                raise MixergyConnectionError(
                    f"Schedule response was not valid JSON: {err}"
                ) from err

        schedule = TankSchedule(raw=data)

        # Normalise "heatpump" (API) → "heat_pump" (HA) so the select entity
        # and default_heat_source sensor always show the HA-canonical value.
        raw_heat_source = data.get("defaultHeatSource", "electric")
        schedule.default_heat_source = _api_to_ha_heat_source(raw_heat_source)

        # `holiday` should be a dict; tolerate a schema change (string/list)
        # without raising AttributeError out of the coordinator.
        holiday = data.get("holiday")
        if isinstance(holiday, dict):
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

        url = self._require_url(self._control_url, "control")
        async with await self._request_with_reauth(
            "PUT",
            url,
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

        url = self._require_url(self._settings_url, "settings")
        async with await self._request_with_reauth(
            "PUT",
            url,
            json={"max_temp": temperature},
        ) as resp:
            if resp.status != 200:
                raise MixergyApiError(
                    f"Set target temperature failed: {resp.status}"
                )

    async def set_setting(self, key: str, value: Any) -> None:
        """Set a single tank setting by key."""
        await self._discover_tank()

        url = self._require_url(self._settings_url, "settings")
        async with await self._request_with_reauth(
            "PUT",
            url,
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
        def _to_utc_epoch_ms(d: datetime) -> int:
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return int(d.astimezone(timezone.utc).timestamp() * 1000)

        start_ms = _to_utc_epoch_ms(start)
        end_ms = _to_utc_epoch_ms(end)
        if start_ms >= end_ms:
            raise MixergyApiError(
                "Holiday start date must be before the end date"
            )

        await self._discover_tank()

        async with self._schedule_write_lock:
            schedule_data = await self.fetch_schedule()
            raw = schedule_data.raw

            raw["holiday"] = {
                "departDate": start_ms,
                "returnDate": end_ms,
            }

            url = self._require_url(self._schedule_url, "schedule")
            async with await self._request_with_reauth(
                "PUT",
                url,
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

            url = self._require_url(self._schedule_url, "schedule")
            async with await self._request_with_reauth(
                "PUT",
                url,
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
        api_heat_source = _ha_to_api_heat_source(heat_source)
        await self._discover_tank()

        async with self._schedule_write_lock:
            schedule_data = await self.fetch_schedule()
            raw = schedule_data.raw
            raw["defaultHeatSource"] = api_heat_source

            url = self._require_url(self._schedule_url, "schedule")
            async with await self._request_with_reauth(
                "PUT",
                url,
                json=raw,
            ) as resp:
                if resp.status != 200:
                    raise MixergyApiError(
                        f"Set default heat source failed: {resp.status}"
                    )

    async def async_list_tanks(self) -> list[dict[str, str]]:
        """Return all tanks on the account: ``[{"serial", "firmware"}, ...]``.

        Used by the config flow to offer a picker instead of manual serial
        entry. Authenticated HATEOAS walk; does not require a serial.
        """
        await self._ensure_authenticated()
        try:
            async with await self._request_with_reauth("GET", API_ROOT) as resp:
                if resp.status != 200:
                    raise MixergyConnectionError(
                        f"Root endpoint returned {resp.status}"
                    )
                root = _require_object(await resp.json(), "Root response")
            root_links = _require_object(root.get("_links"), "Root links")
            tanks_url = _require_link(root_links, "tanks")
            async with await self._request_with_reauth("GET", tanks_url) as resp:
                if resp.status != 200:
                    raise MixergyConnectionError(
                        f"Tanks endpoint returned {resp.status}"
                    )
                data = _require_object(await resp.json(), "Tanks response")
            embedded = _require_object(data.get("_embedded"), "Tanks embedded data")
            tanks = _require_array(embedded.get("tankList"), "Tank list")
        except (aiohttp.ClientError, asyncio.TimeoutError,
                json.JSONDecodeError, KeyError, TypeError) as err:
            raise MixergyConnectionError(
                f"Failed to list tanks: {err}"
            ) from err

        result: list[dict[str, str]] = []
        for raw_tank in tanks:
            tank = _require_object(raw_tank, "Tank list entry")
            serial = tank.get("serialNumber")
            if not isinstance(serial, str) or not serial.strip():
                continue
            firmware = tank.get("firmwareVersion", "")
            if not isinstance(firmware, str):
                firmware = ""
            result.append(
                {
                    "serial": serial.strip().upper(),
                    "firmware": firmware,
                }
            )
        return result

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
