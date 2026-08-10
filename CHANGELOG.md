# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.5] - 2026-08-10

### Changed

- Replaced the fixed-width README banner and badge wall with a compact header
  that renders cleanly in HACS on desktop and mobile.
- Regenerated the packaged standard and high-DPI integration icons from the
  repository's vector source.
- Clarified the boundary between packaged Home Assistant brand images and the
  separate CDN-backed icon used by HACS repository listings.

## [1.3.4] - 2026-08-10

Post-release correctness fixes from a deep review of `v1.3.3`.

### Fixed

- Successful HTTP responses with wrong-shaped JSON now raise typed
  `MixergyAuthError` or `MixergyConnectionError` instead of leaking raw
  `AttributeError` / `TypeError` exceptions into config flows and polling.
- HATEOAS discovery and tank listing validate object, array, entry, and link
  shapes consistently before reading fields.
- Holiday windows are rejected before discovery or network I/O unless the
  start is strictly before the end, protecting services and DateTime entities
  with one API-level invariant.

## [1.3.3] - 2026-08-10

Hardening release: exact-origin API-link validation, a public-release CI
pipeline with minimum/current/latest Home Assistant coverage, and the fixes
from an adversarial review of the hardening itself. Also carries the refreshed
brand assets and the repository's canonical name.

### Fixed

- Percentage sensors and controls now use `UnitOfRatio.PERCENTAGE` on Home
  Assistant 2026.7+ while retaining the equivalent legacy unit on the supported
  2025.8 floor.
- Diagnostics now return redacted config metadata when an entry failed before
  its coordinator loaded, instead of raising while users are troubleshooting.
- Corrected the polling-interval description to the enforced 30–300 second
  range in **every** locale (it/de/fr); the guard test is parametrised over
  all translation files so a locale can no longer drift alone.
- API discovery, login, and authenticated calls no longer follow redirects;
  HATEOAS links are restricted to the exact verified `www.mixergy.io:443`
  origin, and invalid heat-source writes fail before any network request.
- A malformed discovered URL now raises a clean `MixergyConnectionError`
  instead of letting `urlparse`'s own `ValueError` escape the error taxonomy.
- A permanent redirect on a cached endpoint clears the discovery cache (like
  404/410), so an endpoint rotation signalled via 3xx self-heals on the next
  poll instead of failing forever.
- Removed the private-home assumption that every tank belongs in Utility Room.

### Security

- GitHub Actions are pinned to immutable commits with explicit read-only token
  permissions and timeouts; the repository-hygiene test covers both workflow
  extensions and rejects job-level permission widening.
- Added a security policy backed by GitHub private vulnerability reporting;
  Dependabot alerts and automated security updates are enabled.

### Testing

- CI now tests the advertised minimum HA 2025.8.0 and current HA 2026.8.1 on
  every change, with a separate scheduled latest-HA canary that asserts it
  really resolved the latest core release.
- Test-tool versions are pinned and a 65% coverage floor is enforced (measured
  68%, with headroom so unrelated changes don't flip CI red). The inaccurate
  `quality_scale: silver` claim was removed until coverage exceeds Home
  Assistant's required 95% threshold.

### Changed

- Banner wordmark updated to **Mixergy Home Assistant**; all badges, links,
  and the HACS redirect use the canonical repository name
  `Mixergy-Home-Assistant`.

## [1.3.2] - 2026-08-09

Compatibility release for Home Assistant 2026.x: closes upcoming core
deprecations before they become errors and hardens the CI pipeline so the
suite always runs against the current HA core. Full suite verified green on
HA 2026.8.1 / Python 3.14. Also rolls up the previously-unreleased
documentation and tooling changes.

### Fixed
- **Deprecated reload combination (HA 2026.12 hard error)** — the options
  update listener registered in `async_setup_entry` combined with the
  reloading flow methods used by reauth/reconfigure
  (`async_update_reload_and_abort`) is deprecated since HA 2026.6 and becomes
  an error in 2026.12 (double-reload race). The options flow now subclasses
  `OptionsFlowWithReload` and the listener is gone.
- **Device registry single-config-entry migration (HA 2027.8 removal)** —
  service target resolution read `DeviceEntry.config_entries`, deprecated in
  HA 2026.8. New `_device_config_entry_ids()` prefers `config_entry_id` and
  falls back on older cores.
- **Untruthful HACS minimum version** — `hacs.json` claimed `2024.4.0` while
  the code already used `_get_reauth_entry()` (2024.11+) and the coordinator
  `config_entry` kwarg (2024.8+); on an old core that's a hard setup crash.
  Now `2025.8.0`, the floor `OptionsFlowWithReload` actually needs.
- **CI tested a stale core** — the workflow pinned Python 3.12, so
  `pip install homeassistant` silently resolved an old release (HA 2026.8
  needs ≥3.14.2). CI now runs Python 3.14 and the test job gained a weekly
  schedule so core API churn is caught between pushes.

### Added
- `tools/gen_entity_docs.py` — generates the README sensor / binary-sensor /
  controls / services tables from the integration source (`strings.json`,
  platform modules, `services.yaml`). The tables now live between
  `<!-- AUTOGEN:entities:* -->` markers; the script's `--check` mode runs in
  the Tests workflow so CI fails when the docs drift from the code.
- Tests workflow badge in the README.

### Changed
- All repository URLs (README badges, HACS custom-repository instructions,
  release/issues links, `manifest.json` `documentation` / `issue_tracker`)
  updated to the current repository name.
- HACS badge corrected from "Default" to "Custom" — this integration is
  installed as a HACS custom repository (the HACS default store lists a
  different Mixergy integration).
- README restyled to the house format: centered header with tagline, emoji
  section headings, and a Mermaid architecture diagram (config flow →
  coordinator → cloud API → entities) near the end of the file.
- `brand/BRAND_IMAGES.md` now reflects the shipped files: `icon.png` and
  `icon@2x.png` are present, `logo.png` is optional (HA falls back to the
  icon when it is absent).

## [1.3.1] - 2026-07-06

Hardening release from an adversarial code review focused on HA-core
compatibility and robustness. Also fixes the hassfest `services.yaml`
schema failures (invalid `area`/`device` target filters).

### Fixed
- **Cost sensor state class** — `MONETARY` device class only permits `TOTAL`;
  was `TOTAL_INCREASING`, which HA core rejects for long-term statistics.
- **Stale-poll accumulator poisoning** — the energy and cost accumulator
  sensors kept integrating power across failed coordinator polls,
  manufacturing phantom kWh from stale readings. They now skip integration
  and resync their clock while the poll is failing.
- **API URL guards** — 10 `assert <url> is not None` sites in `api.py`
  replaced with a typed `_require_url()` raising `MixergyConnectionError`;
  `AssertionError` escaped the integration's error taxonomy and disappears
  under `python -O`.
- **Options flow cross-field validation** — `no_water_threshold` can no longer
  be set at or above `low_water_threshold` (which made the "low water" state
  unreachable); the form re-shows with a translated error (en/de/fr/it).
- **services.yaml schema drift** — removed `area: {}` and `device:` filters
  from service `target:` blocks; hassfest now only accepts `entity:` filters.

### Added
- 4 regression tests covering the fixes above (failed-poll guard ×2,
  MONETARY/TOTAL, `_require_url`). 76 tests total.

## [1.3.0] - 2026-06-27

Feature release: a native water-heater entity plus several new entities and
flows, shaped by a full review pass for both bugs and features.

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
plus per-tank service targeting, driven by a dedicated security review.

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
