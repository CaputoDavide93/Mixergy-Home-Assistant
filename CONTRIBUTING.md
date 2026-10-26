# Contributing

Bug reports, hardware reports and pull requests are welcome.

## Reporting untested hardware

The maintainer has run this integration live on one tank only (an indirect-heated model, firmware 7.2.1). Heat pump tanks, electric-only tanks and tanks with a PV diverter are handled by the code and covered by unit tests with sample API responses, but they are unverified on hardware. Your report is the only way they become verified.

Open an [issue](https://github.com/CaputoDavide93/Mixergy-Home-Assistant/issues) with:

1. The heating type (electric immersion, indirect gas or oil, heat pump, PV diverter) and whether anything looked wrong or worked first time.
2. The tank firmware version and the model code shown on the device page.
3. Your Home Assistant version and the integration version (Settings → Devices & services → Mixergy).
4. The diagnostics file: Settings → Devices & services → Mixergy → three-dot menu → **Download diagnostics**. Credentials, tokens and the tank serial are redacted, and the raw schedule is removed.
5. A debug log excerpt if the problem comes and goes (see [troubleshooting](docs/troubleshooting.md#how-do-i-enable-debug-logging)).

Do not post your password, your serial number or a screenshot that shows either. For a suspected vulnerability, use the private route in [SECURITY.md](SECURITY.md).

## Working on the code

You need [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
make venv     # test environment with Home Assistant 2026.8.2
make check    # ruff, mypy, pytest with the 95% coverage floor, generated docs and diagrams
```

`make check` runs what CI runs. Two generators keep the docs honest and fail the check when stale:

- `python3 tools/gen_entity_docs.py` rewrites the entity and service tables in [docs/entities.md](docs/entities.md).
- `python3 tools/gen_diagram.py` redraws the diagrams in `docs/assets/`.

Run both without arguments after changing entities or services, and with `--check` to verify.

## Screenshots

`make screenshots` starts a throwaway Home Assistant with a demo tank, walks through the setup in Chromium and rewrites `docs/assets/screenshots/`. It uses no real account and sends nothing to Mixergy. Run it when the setup screens or entity names change. The images carry demo data only.

## Pull requests

- Branch from `main`; commit messages follow conventional commits (`fix:`, `feat:`, `docs:`).
- Add a test for changed behaviour, and an entry under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.
- Keep entity ids, the `mixergy_tank` domain and statistic ids stable. Renaming any of them orphans users' history.
