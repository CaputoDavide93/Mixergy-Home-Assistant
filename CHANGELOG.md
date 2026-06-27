# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
