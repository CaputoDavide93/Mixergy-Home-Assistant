# Entity Reference

Every entity the Mixergy integration creates, in one place: sensors, binary sensors, controls, the water heater, device triggers, and the device page. The tables are generated from the source code, so they never drift; the prose around them explains the behaviour the tables cannot carry — availability rules, energy accumulation, thresholds, and mode gating.

## 🏷️ How entity ids are formed

Every entity id starts with the device name. The integration uses `has_entity_name`, and all entities belong to a single device named **Mixergy Tank (\<serial\>)** — so Home Assistant builds each object id from the device name plus the entity's display name. The "Hot water temperature" sensor becomes `sensor.mixergy_tank_<serial>_hot_water_temperature`.

Throughout this page, `<serial>` stands for your tank's serial number in lower case — a real id looks like `sensor.mixergy_tank_mx001234_hot_water_temperature`. Two consequences of this scheme:

- The **water heater** entity has no name of its own (it is the device's primary entity), so its id is the bare device name: `water_heater.mixergy_tank_<serial>`.
- Entity ids follow the **display name**, not the internal key — the "Current charge" sensor (internal key `charge`) gets the id `sensor.mixergy_tank_<serial>_current_charge`.

You can rename any entity id from its settings dialog; the tables below list the internal key and display name so you can match either.

## 📊 Sensors

The sensor platform reports temperatures, charge level, power draw, heat sources, holiday dates, and diagnostics — all read-only, all refreshed on every poll (30–300 s, default 60). Three diagnostic sensors ship disabled; the two energy sensors and the optional cost sensor accumulate over time and are covered in their own sections below.

<!-- AUTOGEN:entities:sensors -->
| Sensor | Unit | Description |
| ------ | ---- | ----------- |
| Hot water temperature | °C | Current top-of-tank temperature |
| Coldest water temperature | °C | Current bottom-of-tank temperature |
| Target temperature | °C | Configured target temperature |
| Cleansing temperature | °C | Anti-legionella cleansing temperature |
| Current charge | % | Current hot water charge level |
| Target charge | % | Configured target charge level |
| Electric heat power | W | Real power draw from CT clamp |
| Electric heat energy | kWh | Cumulative electric energy (Energy Dashboard) |
| PV power | kW | Solar PV power being diverted *(PV diverter only)* |
| PV energy | kWh | Cumulative PV energy (Energy Dashboard) *(PV diverter only)* |
| Clamp power | W | CT clamp power reading *(PV diverter only)* |
| Active heat source | — | Currently active heat source |
| Default heat source | — | Configured default heat source |
| Holiday start date | Timestamp | Holiday mode start date |
| Holiday end date | Timestamp | Holiday mode end date |
| Electric heating cost | currency | Cumulative cost *(only when a tariff rate is set in options)* |
| Firmware version | — | Tank firmware *(diagnostic, disabled by default)* |
| Model | — | Tank model code *(diagnostic, disabled by default)* |
| Last successful update | Timestamp | Time of the last API refresh *(diagnostic, disabled by default)* |
<!-- /AUTOGEN:entities:sensors -->

### Where are the firmware and model sensors?

Disabled by default. **Firmware version**, **Model**, and **Last successful update** are diagnostic sensors (`entity_category: diagnostic`) registered with `entity_registry_enabled_default: False` — they exist in the entity registry but record no state until you enable them. To switch one on:

1. Open **Settings → Devices & services → Mixergy**, then select the tank device.
2. Find the sensor in the **Diagnostic** section — disabled entities are listed under "not shown".
3. Open the entity, press the cog, and toggle **Enabled**.

The same firmware and model values always appear on the device page (see below), so most installations never need these sensors enabled.

## ⚡ How do the energy sensors accumulate?

**Electric heat energy** and **PV energy** are cumulative kWh totals built by integrating power over time: on each successful poll, the sensor multiplies the current power reading by the hours elapsed since the previous tick and adds the result. The totals survive Home Assistant restarts, and outages can never inflate them.

The accumulation rule, exactly as implemented:

| Safeguard | Behaviour |
| --- | --- |
| Integration step | ΔE (kWh) = P (W) × Δt (h) ÷ 1000, added on every successful poll |
| Outage cap | Δt is capped at **2× the poll interval** — a long gap (HA stopped, network down, API outage) credits at most two intervals of energy, never a fictitious multi-hour spike |
| Clock-skew floor | Δt is floored at 0, so an NTP correction can never subtract from the total |
| Failed polls | a failed poll adds nothing and resynchronises the clock, so the outage window is not credited on recovery either |
| Restart persistence | the running total is a `RestoreSensor` — it restores on startup and is written back to the state machine immediately, so the Energy dashboard never sees a transient 0 that would read as a counter reset |
| Non-finite readings | a NaN or infinite power reading is discarded; if the stored total itself ever goes non-finite it resets to 0 with a logged warning rather than poisoning long-term statistics |

Both sensors carry `device_class: energy` and `state_class: total_increasing`, which makes them directly usable in the Energy dashboard — see [energy.md](energy.md) for the setup walkthrough.

### When is the cost sensor created?

Only when you set a tariff. **Electric heating cost** exists solely when the *Electricity price per kWh* option is greater than 0 — set it from **Configure** on the integration card, or leave it at 0 and the sensor is never created. It accumulates electric power × elapsed time × your rate, with the same outage cap, failed-poll, restart-restore, and non-finite safeguards as the energy sensors.

Two details worth knowing:

- The sensor stores the **cost** directly, not kWh — so changing the tariff later never rewrites history; new energy accrues at the new rate.
- Its state class is `total` (Home Assistant permits only `total` for monetary sensors), and its unit follows your Home Assistant currency setting.

## 🚨 Binary sensors

Seven on/off indicators cover heat-source activity, heating status, holiday mode, and two configurable water-level alerts. **Low hot water** turns on when charge drops below 5% and **No hot water** below 0.5% — both thresholds are options you can change, and the options flow rejects a "no" threshold that is not below the "low" one.

<!-- AUTOGEN:entities:binary-sensors -->
| Sensor | Description |
| ------ | ----------- |
| Electric heat active | Electric immersion heater is currently on |
| Indirect heat active | Gas/oil indirect coil is heating |
| Heat pump active | Heat pump is heating |
| Heating | Any heat source is actively heating |
| Low hot water | Charge is below the low threshold (default 5%, configurable) |
| No hot water | Charge is below the no-water threshold (default 0.5%, configurable) |
| Holiday mode | Tank is currently in holiday mode |
<!-- /AUTOGEN:entities:binary-sensors -->

### How do I change the water-level thresholds?

1. Open **Settings → Devices & services → Mixergy** and press **Configure**.
2. Set *Low hot water alert threshold (%)* and *No hot water alert threshold (%)*.
3. Save — the integration reloads and the new thresholds apply immediately.

The "no hot water" threshold must be lower than the "low hot water" threshold; the form rejects anything else.

## 🎛️ Controls — Simple mode

Simple mode exposes exactly one control: the **Hot water boost** slider (0–100% in steps of 5), shown as a primary entity on the device card. Sliding it sets the tank's target charge, telling the tank to heat until that percentage of the water is hot.

<!-- AUTOGEN:entities:controls-simple -->
| Entity | Type | Description |
| ------ | ---- | ----------- |
| Hot water boost | Number (0–100 %) | Set how full you want the tank right now |
<!-- /AUTOGEN:entities:controls-simple -->

The boost slider shares its registry identity with the Advanced-mode *Target charge* control, so switching between Simple and Advanced preserves the entity's history — nothing is lost when you change experience mode from the **Configure** dialog.

## ⚙️ Controls — Advanced mode

Advanced mode replaces the single boost slider with the full control set: temperature and charge numbers, PV divert tuning, feature switches, the default heat source selector, holiday date pickers, a clear-holiday button — plus the water heater entity described in the next section. Switch modes any time from **Configure**; the integration reloads.

<!-- AUTOGEN:entities:controls-advanced -->
| Entity | Type | Description |
| ------ | ---- | ----------- |
| Water heater | Water heater | Temperature, operation mode & away in one card |
| Holiday start | DateTime | Set the holiday start from a date/time picker |
| Holiday end | DateTime | Set the holiday end from a date/time picker |
| Target temperature | Number (45–70 °C) | Set the desired water temperature |
| Target charge | Number (0–100 %) | Set the desired charge level |
| Cleansing temperature | Number (51–55 °C) | Set anti-legionella temperature |
| Default heat source | Select | Choose default heat source |
| Grid assistance (DSR) | Switch | Enable/disable demand-side response |
| Frost protection | Switch | Enable/disable frost protection |
| Medical research donation | Switch | Enable/disable distributed computing |
| PV export divert | Switch | Enable/disable PV divert *(PV diverter only)* |
| PV cut-in threshold | Number (0–500) | PV diverter cut-in threshold, in watts *(PV diverter only)* |
| PV charge limit | Number (0–100 %) | Maximum charge from PV *(PV diverter only)* |
| PV target current | Number (−1–0) | PV target current *(PV diverter only)* |
| PV over-temperature limit | Number (45–60 °C) | Maximum PV heating temperature *(PV diverter only)* |
| Clear holiday dates | Button | Clear holiday mode immediately |
<!-- /AUTOGEN:entities:controls-advanced -->

Ranges enforced by the controls, matching the Mixergy API limits:

| Control | Range | Step |
| --- | --- | --- |
| Target temperature | 45–70 °C | 1 |
| Target charge | 0–100% | 5 |
| Cleansing temperature | 51–55 °C | 1 |
| PV cut-in threshold | 0–500 W | 50 |
| PV charge limit | 0–100% | 10 |
| PV target current | −1–0 | 0.1 |
| PV over-temperature limit | 45–60 °C | 1 |

Behaviour shared by every control:

- **Writes go to the Mixergy cloud**, serialised per platform (one in-flight command per entity type), followed by a coordinator refresh so the new value shows up straight away. Holiday-schedule writes are additionally serialised against each other, so two near-simultaneous schedule changes cannot overwrite one another.
- **A failed write raises an error** in the UI rather than silently pretending it worked; an authentication failure additionally starts the re-authentication flow.
- **Holiday date pickers work as a window.** Setting *Holiday start* when no end is set defaults the end to start + 7 days; setting *Holiday end* with no start defaults the start to now. *Clear holiday dates* removes the window entirely.

## 🚿 Water heater entity

Advanced mode represents the tank as a first-class Home Assistant water heater — `water_heater.mixergy_tank_<serial>`, the device's primary entity. It carries the current top-of-tank temperature, a 45–70 °C target temperature, an operation mode that switches the default heat source, and an away toggle that drives holiday mode.

The three HA operation modes map onto Mixergy heat sources:

| HA operation mode | Mixergy heat source |
| --- | --- |
| `electric` | Electric (immersion) |
| `gas` | Indirect (gas/oil boiler coil) |
| `heat_pump` | Heat pump |

**Away mode is holiday mode.** Toggling away on opens a holiday window from now to roughly ten years ahead (3650 days), which keeps the tank in holiday mode until you act; toggling it off clears the holiday dates. The toggle reflects the tank's own holiday state, so it also reads `on` when a holiday window set elsewhere is active.

## 🟢 Availability

Two rules decide whether an entity is available. Every entity goes unavailable together when polling the Mixergy cloud fails — states freeze as `unavailable` rather than showing stale data. PV-related entities are additionally available only when the tank reports a fitted PV diverter.

### Why are my entities unavailable?

The last poll failed. All entities share one data coordinator, so a cloud API error, an expired login, or a network outage marks every entity unavailable at once until the next successful poll. Check **Settings → Devices & services** for a re-authentication prompt, then see [troubleshooting.md](troubleshooting.md).

### Why can't I see the PV entities?

Your tank reports no PV diverter. **PV power**, **Clamp power**, **PV energy**, the **PV export divert** switch, and the four PV number controls stay unavailable unless the tank's cloud record says a PV diverter is fitted — they are created regardless, so they appear the moment the hardware does.

## 🔔 Device triggers

Five ready-made triggers appear in the automation editor when you pick the tank as a device — no entity ids needed. They cover the moments most automations care about: hot water running low, heating starting or stopping, and holiday mode beginning or ending.

| Trigger | Shown in the UI as | Fires when |
| --- | --- | --- |
| `low_hot_water` | Hot water is low | *Low hot water* turns on |
| `heating_started` | Heating started | *Heating* turns on |
| `heating_stopped` | Heating stopped | *Heating* turns off |
| `holiday_started` | Holiday mode started | *Holiday mode* turns on |
| `holiday_ended` | Holiday mode ended | *Holiday mode* turns off |

You find them under **Settings → Automations & scenes → Create automation → Add trigger → Device**, then select your Mixergy tank. Each one delegates to the core state trigger on the matching binary sensor, so a plain state trigger in YAML behaves identically:

```yaml
automation:
  - alias: "Mixergy: warn when hot water is low"
    triggers:
      - trigger: state
        entity_id: binary_sensor.mixergy_tank_<serial>_low_hot_water
        to: "on"
    conditions: []
    actions:
      - action: notify.persistent_notification
        data:
          title: "Hot water is low"
          message: "Tank charge has dropped below the low threshold."
```

More worked examples live in [automations.md](automations.md).

## 🖥️ Device page

All entities hang off a single device, so the device page is the natural hub: entity list, controls, diagnostics, and automation shortcuts in one view. Find it under **Settings → Devices & services → Mixergy → Mixergy Tank (\<serial\>)**.

The device registers with:

| Field | Value |
| --- | --- |
| Manufacturer | Mixergy Ltd |
| Model | The tank's model code, as reported by the cloud |
| Serial number | Your tank's serial number |
| Firmware | The tank's firmware version |
| Configuration URL | [mixergy.io](https://www.mixergy.io) — links to the Mixergy site for account management |

## 🔗 See also

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Automations](automations.md)
- [Energy dashboard](energy.md)
- [Troubleshooting](troubleshooting.md)
- [API notes](api.md)
- [README](../README.md)
