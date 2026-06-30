# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-06-27

Feature release: a native water-heater entity plus several new entities and
flows, driven by a dual-AI (Claude + Codex) review for both bugs and features.

### Added
- **Water heater entity** — the tank now appears as a first-class HA
  `water_heater`: current/target temperature, heat-source operation modes
  (electric / gas / heat pump), and an away (holiday) toggle. Advanced mode.
- **Holiday datetime entities** — set holiday start/end from a UI picker
  (in addition to the services). Advanced mode.
- **Reconfigure flow** — update account credentials from the integration's
  Reconfigure button without removing and re-adding the entry.
- **Multi-tank picker** — the config flow now lists the tanks on your account
  to choose from instead of typing the serial (manual entry still allowed).
- **Repair issues** — a "tank not found" repair card guides you to reconfigure,
  and clears automatically once the tank is reachable again.
- **Device triggers** — automate on "hot water low", "heating started/stopped",
  and "holiday started/ended" directly from the Automations UI.
- **Configurable alert thresholds** — set the low / no hot water percentages in
  the integration options.
- **Optional electricity cost sensor** — set a price per kWh in options to get a
  running electric-heating cost in your currency.
- `quality_scale.yaml` checklist tracking Bronze→Platinum rule status.

### Changed
- Entity write commands (switches, numbers, select, button, water heater) now
  trigger HA's re-auth flow on an auth failure, consistent with the services.
- Experience-mode selector labels are translatable.
- Diagnostics now include (non-secret) options and coordinator metadata.
- `PARALLEL_UPDATES` declared on every platform (0 for read, 1 for write).
- Device info now includes the serial number and a configuration URL.

### Fixed
- API numeric fields are coerced to finite floats; null/NaN/inf/garbage values
  no longer mislead entities or the energy/cost integrators.
- Options help text corrected to the real 30–300 s poll-interval range.
- `electric_power` reports a float when idle (was an int `0`).
- Services expose an area target in the UI (the backend already resolved it).

## [1.2.0] - 2026-06-27

Hardening and security pass across the API client, coordinator, and services,
plus per-tank service targeting. Driven by a dual-AI (Claude + Codex) review.

### Added
- **Per-tank service targeting.** `set_holiday_dates`, `clear_holiday_dates`,
  and `boost_charge` now accept a standard Home Assistant target
  (entity / device / area), so you can act on a specific tank in a multi-tank
  home. A legacy `serial_number` field is also accepted. With no target, the
  service still applies to every configured tank.
- **Per-target authorization.** Service calls are permission-checked per tank:
  a non-admin user must hold control permission on the targeted tank(s).
  System/automation calls and admins are unaffected.
- **Options take effect immediately.** Changing the poll interval or experience
  mode now reloads the entry automatically (previously required a manual
  reload).
- Regression test suite expanded (error boundaries, HATEOAS link validation,
  energy non-finite guard, targeting, authorization, fail-closed schema).

### Changed
- Re-authentication now triggers correctly when the cloud API rejects the token
  during polling or HATEOAS discovery (previously surfaced as a generic
  connection error and never opened the reauth flow).
- Holiday `start_date` / `end_date` without a timezone are now interpreted in
  Home Assistant local time instead of UTC.
- Experience-mode default is consistent (Simple) across setup, options, and
  runtime; entries created before the option existed are migrated to Advanced
  on upgrade so no controls silently disappear.

### Fixed
- Network errors (DNS, TLS, connection reset, timeout) on API requests are now
  normalised to the integration's error types instead of escaping as untyped
  tracebacks.
- HATEOAS links from the cloud API are validated to be HTTPS on the Mixergy
  origin before the bearer token is sent, preventing token leakage over
  plaintext or to an unexpected host.
- Token / TTL values from the auth response are validated and clamped, avoiding
  crashes and login storms on malformed responses.
- Malformed JSON, unexpected content types, and null fields in the
  measurement / settings / schedule responses are handled gracefully.
- An infinite or non-numeric power reading can no longer poison the persisted
  cumulative energy total.

### Security
- Bearer token is never sent over non-HTTPS or off-origin URLs (HATEOAS link
  validation).
- Domain services are permission-checked per targeted tank rather than only
  per domain.
