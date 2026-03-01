# Mixergy Integration for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/CaputoDavide93/Mixergy_HomeAssistant_Integration)](https://github.com/CaputoDavide93/Mixergy_HomeAssistant_Integration/releases)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/CaputoDavide93/Mixergy_HomeAssistant_Integration/validate.yaml?label=HACS%20validation)](https://github.com/CaputoDavide93/Mixergy_HomeAssistant_Integration/actions/workflows/validate.yaml)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/CaputoDavide93/Mixergy_HomeAssistant_Integration/hassfest.yaml?label=Hassfest)](https://github.com/CaputoDavide93/Mixergy_HomeAssistant_Integration/actions/workflows/hassfest.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HA Version](https://img.shields.io/badge/HA-2024.4%2B-blue)](https://www.home-assistant.io/)

Custom Home Assistant integration for [Mixergy](https://www.mixergy.io/) smart hot water tanks. Monitor your tank in real time, control temperature and charge levels, manage PV diverter settings, and schedule holiday mode — all from within Home Assistant.

---

## Installation

### Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=CaputoDavide93&repository=Mixergy_HomeAssistant_Integration&category=integration)

Or add manually in HACS:

1. Open [HACS](https://hacs.xyz/) in Home Assistant
2. Go to **Integrations** → click the 3-dots menu → **Custom repositories**
3. Add `https://github.com/CaputoDavide93/Mixergy_HomeAssistant_Integration` with category **Integration**
4. Search for **Mixergy** and install it
5. Restart Home Assistant

### Manual Installation

1. Download the [latest release](https://github.com/CaputoDavide93/Mixergy_HomeAssistant_Integration/releases)
2. Copy `custom_components/mixergy/` into your HA `config/custom_components/` directory
3. Restart Home Assistant

---

## Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Mixergy**
3. Enter your Mixergy account **username** and **password**
4. The integration discovers your tank automatically via the Mixergy API
5. Choose your **experience mode** (see below)

### Experience Modes

| Mode | Who it's for | Entities shown |
| ---- | ------------ | -------------- |
| **Simple** | Most users | Current charge, target charge (boost slider), binary sensor alerts |
| **Advanced** | Power users | Everything: temperature controls, PV diverter settings, heat source select, holiday scheduling, switches |

You can switch between modes at any time via **Settings → Devices & Services → Mixergy → Configure**.

---

## Features

### Sensors

| Sensor | Unit | Description |
| ------ | ---- | ----------- |
| Hot water temperature | °C | Current top-of-tank temperature |
| Coldest water temperature | °C | Current bottom-of-tank temperature |
| Target temperature | °C | Configured target temperature |
| Cleansing temperature | °C | Anti-legionella cleansing temperature |
| Current charge | % | Current hot water charge level |
| Target charge | % | Configured target charge level |
| Electric heat power | W | Real power draw from CT clamp |
| PV power | kW | Solar PV power being diverted *(PV diverter only)* |
| Clamp power | W | CT clamp power reading *(PV diverter only)* |
| Active heat source | — | Currently active heat source |
| Default heat source | — | Configured default heat source |
| Holiday start / end | Timestamp | Holiday mode dates |
| Firmware version | — | Tank firmware version |
| Model | — | Tank model code |
| Last successful update | Timestamp | Time of the last successful data refresh *(diagnostic)* |

### Binary Sensors

| Sensor | Description |
| ------ | ----------- |
| Electric heat active | Electric immersion is currently heating |
| Indirect heat active | Gas/oil indirect heat is active |
| Heat pump active | Heat pump is heating |
| Heating | Any heat source is actively heating |
| Low hot water | Charge is below 5% |
| No hot water | Charge is below 0.5% |
| Holiday mode | Tank is in holiday mode |

### Controls *(Advanced mode)*

| Entity | Type | Description |
| ------ | ---- | ----------- |
| Target temperature | Number (45–70 °C) | Set the target water temperature |
| Target charge | Number (0–100 %) | Set the desired charge level |
| Cleansing temperature | Number (51–55 °C) | Set anti-legionella temperature |
| Default heat source | Select | Choose default heat source |
| Grid assistance (DSR) | Switch | Enable/disable demand-side response |
| Frost protection | Switch | Enable/disable frost protection |
| Medical research donation | Switch | Enable/disable distributed computing |
| PV export divert | Switch | Enable/disable PV divert *(PV diverter only)* |
| PV cut-in threshold | Number (0–500 W) | PV diverter cut-in threshold *(PV diverter only)* |
| PV charge limit | Number (0–100 %) | Maximum charge from PV *(PV diverter only)* |
| PV target current | Number (−1–0) | PV target current *(PV diverter only)* |
| PV over-temperature | Number (45–60 °C) | Maximum PV heating temperature *(PV diverter only)* |
| Clear holiday dates | Button | Clear holiday mode |

### Simple mode controls

| Entity | Type | Description |
| ------ | ---- | ----------- |
| Boost hot water | Number (0–100 %) | One-slider boost control — set how full you want the tank |

### Services

| Service | Description |
| ------- | ----------- |
| `mixergy.set_holiday_dates` | Set holiday start and end dates |
| `mixergy.clear_holiday_dates` | Clear holiday mode immediately |
| `mixergy.boost_charge` | Instantly boost the tank to 100 % charge |

---

## Supported Devices

| Device | Support |
| ------ | ------- |
| Mixergy hot water tanks (all models) | Full |
| Tanks with PV diverter | Full — additional PV sensors & controls |
| Heat pump configurations | Full |
| Indirect (gas/oil) heating | Full |
| Electric immersion | Full |

---

## Re-authentication

If your credentials change or expire, the integration automatically prompts you to re-authenticate through the Home Assistant UI — no manual reconfiguration needed.

---

## Architecture & Design

- **SSL verification enabled** — all API calls use proper certificate validation
- **API timeout** — 30-second timeout on all calls to prevent indefinite hangs
- **Token lifecycle management** — automatic re-authentication on token expiry with retry
- **HATEOAS-safe parsing** — defensive link validation with meaningful error messages
- **Modern HA patterns** — `native_value`, `native_unit_of_measurement`, `has_entity_name`, `CoordinatorEntity`
- **Single coordinator** — one `DataUpdateCoordinator` polling the API, no double-polling
- **Standalone API client** — fully separated from HA for testability
- **Diagnostics support** — downloadable diagnostics with automatic credential redaction
- **Entity descriptions** — declarative definitions via `EntityDescription` pattern
- **Unique ID deduplication** — prevents configuring the same tank twice

---

## Security

- All API communication uses **TLS with certificate verification** (no `verify_ssl=False`)
- Credentials stored in HA's config entry (supports HA's built-in secrets management)
- Bearer tokens are automatically refreshed before expiry
- Diagnostics output **redacts** all credentials and sensitive data

---

## Debugging

Enable debug logging by adding this to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.mixergy: debug
```

Then download the integration diagnostics from **Settings → Devices & Services → Mixergy → Download diagnostics** and attach it to any bug reports.

---

## Contributing

Contributions are welcome! Please open an [issue](https://github.com/CaputoDavide93/Mixergy_HomeAssistant_Integration/issues) or pull request.

## License

This project is licensed under the [MIT License](LICENSE).

---

Made with love for the Home Assistant community
