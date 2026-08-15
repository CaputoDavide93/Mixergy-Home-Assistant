# Automation cookbook

This page shows how to automate a Mixergy tank from Home Assistant: the three `mixergy_tank.*` services (holiday dates, clearing them, and boost), how service calls target tanks, the five device triggers the integration adds to the automation UI, and eleven complete recipes you can paste in and adapt — from workday morning boosts to solar-surplus charging and holiday handling.

All examples use `<serial>` as a placeholder for your tank's serial number. The integration names each device `Mixergy Tank (<SERIAL>)`, so entity ids follow the pattern `sensor.mixergy_tank_<serial>_current_charge` with the serial in lower case. Home Assistant generates ids when entities first register — confirm yours in **Developer Tools → States** before copying a recipe. Replace `notify.mobile_app_<your_phone>` with your own notify service. Every recipe uses the modern automation syntax (`triggers:` / `conditions:` / `actions:`); the integration requires Home Assistant 2025.8 or newer, which supports it.

## 🧰 The three services

The integration registers three services: `mixergy_tank.set_holiday_dates` puts the tank into holiday mode between two dates, `mixergy_tank.clear_holiday_dates` removes the holiday window, and `mixergy_tank.boost_charge` sets the target charge to 100% so the tank heats a full cylinder. All three accept the same targeting options and run per-tank permission checks.

| Service | Required fields | Optional fields | Effect |
| --- | --- | --- | --- |
| `mixergy_tank.set_holiday_dates` | `start_date`, `end_date` | target, `serial_number` | Sets a holiday window on the tank |
| `mixergy_tank.clear_holiday_dates` | — | target, `serial_number` | Clears any holiday window |
| `mixergy_tank.boost_charge` | — | target, `serial_number` | Sets target charge to 100% |

Rules for `set_holiday_dates`:

- `start_date` and `end_date` accept datetimes. A **naive** value (no timezone, e.g. `2026-03-15 16:00:00`) is read as **Home Assistant local time**, not UTC. Timezone-aware values pass through unchanged.
- `start_date` must be before `end_date` — otherwise the call fails with *"Holiday start date must be before the end date."*
- The window ends on its own at `end_date`; you only need `clear_holiday_dates` to cut a holiday short.

After every successful command the integration requests a data refresh, so sensors reflect the change at the next update rather than waiting a full poll cycle.

### Which tanks does a call target?

Targeting precedence: an explicit entity, device, or area target wins; otherwise the legacy `serial_number` field selects a tank; otherwise the call applies to **every configured tank**. Pick any entity belonging to the tank as the target — the integration resolves it to the tank's config entry, so one target drives the whole device.

```yaml
# Target one tank by entity (any Mixergy entity works)
- action: mixergy_tank.boost_charge
  target:
    entity_id: sensor.mixergy_tank_<serial>_current_charge

# Target by area
- action: mixergy_tank.boost_charge
  target:
    area_id: utility_room

# Legacy: target by serial number (matched case-insensitively, whitespace trimmed)
- action: mixergy_tank.boost_charge
  data:
    serial_number: "<serial>"

# No target at all: applies to ALL configured tanks
- action: mixergy_tank.boost_charge
```

The targeting fails closed. A target that matches no Mixergy tank raises *"No Mixergy tanks match the supplied target."* rather than falling through to all tanks, an unknown serial number raises an error naming it, and floor or label targets are rejected outright at validation because the integration does not resolve them.

### Who can call these services?

Automations, scripts, and admin users pass without restriction — a service call with no user context (which is what an automation is) skips the check entirely. A non-admin user must hold control permission on at least one entity of **every** tank the call targets, so a user scoped to tank A cannot drive tank B, and cannot use the no-target form to reach all tanks.

## 🎛️ Device triggers

The integration exposes five triggers in the automation editor's device picker. Each one wraps a core state trigger on one of the tank's binary sensors — the device trigger is a convenience, not a separate mechanism, so anything you build with it can also be written as a plain state trigger.

| Device trigger | UI label | Backing entity | Fires when |
| --- | --- | --- | --- |
| `low_hot_water` | Hot water is low | `binary_sensor.mixergy_tank_<serial>_low_hot_water` | Charge drops below the low threshold (default 5%) |
| `heating_started` | Heating started | `binary_sensor.mixergy_tank_<serial>_heating` | The tank starts heating |
| `heating_stopped` | Heating stopped | `binary_sensor.mixergy_tank_<serial>_heating` | The tank stops heating |
| `holiday_started` | Holiday mode started | `binary_sensor.mixergy_tank_<serial>_holiday_mode` | Holiday mode becomes active |
| `holiday_ended` | Holiday mode ended | `binary_sensor.mixergy_tank_<serial>_holiday_mode` | Holiday mode ends |

Picking **Hot water is low** in the UI produces an automation like this — the UI fills in `device_id` and stores the entity's registry id (both the readable id and the registry uuid are accepted):

```yaml
alias: "Tank — low hot water (device trigger)"
triggers:
  - trigger: device
    domain: mixergy_tank
    device_id: <device_id_filled_by_the_ui>
    entity_id: binary_sensor.mixergy_tank_<serial>_low_hot_water
    type: low_hot_water
actions:
  - action: notify.mobile_app_<your_phone>
    data:
      message: "Hot water is low."
```

### What is the state-trigger equivalent?

Each device trigger delegates to the core state trigger with a fixed `to:` state, so the equivalent of the automation above is a state trigger on the same binary sensor. Use this form when you prefer YAML, want to add `for:` durations, or want one automation listening to several tanks at once.

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.mixergy_tank_<serial>_low_hot_water
    to: "on"
```

The mapping for the other four: `heating_started` = `…_heating` to `"on"`, `heating_stopped` = `…_heating` to `"off"`, `holiday_started` = `…_holiday_mode` to `"on"`, `holiday_ended` = `…_holiday_mode` to `"off"`.

## 📖 Recipes

Eleven complete automations, ordered roughly by popularity. Recipes 1–9 work in both Simple and Advanced experience mode; recipes 10 and 11 need entities that exist only in Advanced mode (the `Target temperature` number and the `water_heater` entity — switch modes in the integration's options, see [configuration.md](configuration.md)).

### 1. Low hot water → phone notification

The state-trigger version of the device-trigger example above, with the live charge in the message. The `Low hot water` sensor turns on when charge falls below the low threshold — 5% by default, adjustable in the integration options alongside the no-water threshold (default 0.5%).

```yaml
alias: "Tank — low hot water alert"
triggers:
  - trigger: state
    entity_id: binary_sensor.mixergy_tank_<serial>_low_hot_water
    to: "on"
actions:
  - action: notify.mobile_app_<your_phone>
    data:
      title: "Hot water is low"
      message: >-
        Tank charge is down to
        {{ states('sensor.mixergy_tank_<serial>_current_charge') | round(0) }}%.
        Boost it from the Mixergy card if you need a bath tonight.
```

### 2. Morning boost on workdays

Boost the tank early on working days only, using the [Workday integration](https://www.home-assistant.io/integrations/workday/) as the condition. `mixergy_tank.boost_charge` sets the target charge to 100%; to boost to a lower level, use `number.set_value` on the `Target charge` control instead (0–100% in steps of 5).

```yaml
alias: "Tank — workday morning boost"
triggers:
  - trigger: time
    at: "05:30:00"
conditions:
  - condition: state
    entity_id: binary_sensor.workday_sensor
    state: "on"
actions:
  - action: mixergy_tank.boost_charge
    target:
      entity_id: sensor.mixergy_tank_<serial>_current_charge
```

### 3. Solar-surplus boost

Turn spare solar export into hot water: boost when export has held above a threshold for ten minutes and the tank still has room. Adjust `above:` to your inverter's sustained surplus and `below:` to the charge level you consider "room".

```yaml
alias: "Tank — solar surplus boost"
mode: single
triggers:
  - trigger: numeric_state
    entity_id: sensor.grid_export_power
    above: 1500
    for: "00:10:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.mixergy_tank_<serial>_current_charge
    below: 80
actions:
  - action: mixergy_tank.boost_charge
    target:
      entity_id: sensor.mixergy_tank_<serial>_current_charge
```

If your tank has a PV diverter, it can do this natively without any automation — the integration exposes the PV cut-in threshold (0–500 W), PV charge limit (0–100%), PV target current (−1–0) and PV over-temperature (45–60 °C) as number controls in Advanced mode. See [entities.md](entities.md) and [energy.md](energy.md).

### 4. Cheap-tariff overnight boost window

Charge the tank during an off-peak window (Economy 7, Intelligent Octopus, and similar). The condition skips the call when the tank is already at a full target; adapt the trigger time to the start of your cheap window.

```yaml
alias: "Tank — off-peak overnight charge"
triggers:
  - trigger: time
    at: "00:35:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.mixergy_tank_<serial>_current_charge
    below: 100
actions:
  - action: mixergy_tank.boost_charge
    target:
      entity_id: sensor.mixergy_tank_<serial>_current_charge
```

### 5. Holiday mode from a calendar

Set the tank's holiday window straight from a calendar event. This fires when an event containing "holiday" starts, and passes the event's own start and end through to the service — the window then expires on its own at the event's end, so no second automation is needed.

```yaml
alias: "Tank — holiday from calendar"
triggers:
  - trigger: calendar
    entity_id: calendar.family
    event: start
conditions:
  - condition: template
    value_template: "{{ 'holiday' in trigger.calendar_event.summary | lower }}"
actions:
  - action: mixergy_tank.set_holiday_dates
    target:
      entity_id: sensor.mixergy_tank_<serial>_current_charge
    data:
      start_date: "{{ trigger.calendar_event.start }}"
      end_date: "{{ trigger.calendar_event.end }}"
```

Timed events work as-is because they carry full datetimes. All-day events supply a date with no time, which the service reads as **local midnight** — usually not the hour you want, so for an all-day calendar build an explicit datetime in the template, e.g. `start_date: "{{ trigger.calendar_event.start }} 16:00:00"` (read as local time, per the naive-datetime rule).

### 6. Holiday mode from input_datetime helpers

Prefer picking dates on a dashboard? Two helpers plus a script give you a manual holiday form. The helper's state (`YYYY-MM-DD HH:MM:SS`, no timezone) is read as Home Assistant local time. In Advanced mode you can skip all of this — the integration ships writable `Holiday start` and `Holiday end` datetime entities that do the same from a UI picker.

```yaml
input_datetime:
  tank_holiday_start:
    name: Tank holiday start
    has_date: true
    has_time: true
  tank_holiday_end:
    name: Tank holiday end
    has_date: true
    has_time: true

script:
  tank_set_holiday:
    alias: "Tank — set holiday from helpers"
    sequence:
      - action: mixergy_tank.set_holiday_dates
        target:
          entity_id: sensor.mixergy_tank_<serial>_current_charge
        data:
          start_date: "{{ states('input_datetime.tank_holiday_start') }}"
          end_date: "{{ states('input_datetime.tank_holiday_end') }}"
```

### 7. Auto-clear holiday on arrival

Coming home early should mean hot water, not a cold tank until the window expires. This clears the holiday the moment someone arrives home while holiday mode is active, then boosts so the tank starts reheating immediately. Swap the `person` trigger for a `zone` trigger if you track arrival differently.

```yaml
alias: "Tank — end holiday on arrival"
triggers:
  - trigger: state
    entity_id: person.<you>
    to: "home"
conditions:
  - condition: state
    entity_id: binary_sensor.mixergy_tank_<serial>_holiday_mode
    state: "on"
actions:
  - action: mixergy_tank.clear_holiday_dates
    target:
      entity_id: sensor.mixergy_tank_<serial>_current_charge
  - action: mixergy_tank.boost_charge
    target:
      entity_id: sensor.mixergy_tank_<serial>_current_charge
```

### 8. Heating started/stopped logbook pair

Write a logbook entry every time the tank starts or stops heating — useful for correlating heating spells with tariff windows or the energy dashboard. One automation with two trigger ids covers both edges; swap `logbook.log` for a notify action if you want it on your phone.

```yaml
alias: "Tank — log heating activity"
triggers:
  - trigger: state
    entity_id: binary_sensor.mixergy_tank_<serial>_heating
    to: "on"
    id: started
  - trigger: state
    entity_id: binary_sensor.mixergy_tank_<serial>_heating
    to: "off"
    id: stopped
actions:
  - action: logbook.log
    data:
      name: Mixergy tank
      entity_id: binary_sensor.mixergy_tank_<serial>_heating
      message: >-
        {{ 'started heating' if trigger.id == 'started' else 'stopped heating' }}
```

### 9. No hot water — critical alert, distinct from low

`No hot water` is a separate binary sensor with its own threshold (default 0.5% charge) — treat it as the emergency tier above the 5% "low" warning. This recipe sends a critical push that breaks through silent mode on iOS; on Android, `ttl: 0` with `priority: high` delivers immediately.

```yaml
alias: "Tank — NO hot water (critical)"
triggers:
  - trigger: state
    entity_id: binary_sensor.mixergy_tank_<serial>_no_hot_water
    to: "on"
actions:
  - action: notify.mobile_app_<your_phone>
    data:
      title: "Tank is empty"
      message: "Hot water charge has fallen below the no-water threshold."
      data:
        ttl: 0
        priority: high
        push:
          sound:
            name: default
            critical: 1
            volume: 1.0
```

Both thresholds are configurable in the integration options — see [configuration.md](configuration.md).

### 10. Night setback on target temperature

Drop the target temperature overnight and restore it in the morning using `number.set_value` on the `Target temperature` control (45–70 °C, whole degrees, Advanced mode only). The tank also has a separate cleansing temperature control (51–55 °C) — leave that alone here.

```yaml
alias: "Tank — target temperature day/night"
triggers:
  - trigger: time
    at: "06:00:00"
    id: day
  - trigger: time
    at: "22:30:00"
    id: night
actions:
  - action: number.set_value
    target:
      entity_id: number.mixergy_tank_<serial>_target_temperature
    data:
      value: "{{ 60 if trigger.id == 'day' else 50 }}"
```

### 11. Driving the water_heater entity

In Advanced mode the tank is also a first-class `water_heater` entity, so the core water-heater services work against it. This script bundles the three: set the target temperature (45–70 °C), pick the heat source, and control away mode. `operation_mode` maps to the tank's default heat source — `electric` is the electric heater, `gas` is the indirect (boiler coil) source, `heat_pump` is the heat pump.

```yaml
script:
  tank_guest_setup:
    alias: "Tank — guest setup"
    sequence:
      - action: water_heater.set_temperature
        target:
          entity_id: water_heater.mixergy_tank_<serial>
        data:
          temperature: 65
      - action: water_heater.set_operation_mode
        target:
          entity_id: water_heater.mixergy_tank_<serial>
        data:
          operation_mode: electric
      - action: water_heater.set_away_mode
        target:
          entity_id: water_heater.mixergy_tank_<serial>
        data:
          away_mode: false
```

Away mode is holiday mode by another name: turning it **on** opens an open-ended holiday window (3650 days from now), turning it **off** clears the window — the same effect as `mixergy_tank.clear_holiday_dates`. Use the services from recipes 5–7 when you want a dated window; use away mode for an indefinite "off until I say otherwise".

## ❓ FAQ

### How quickly do these triggers fire?

Within one poll cycle of the cloud reporting the change. This is a cloud-polling integration — Home Assistant polls the Mixergy API every 30–300 seconds (default 60), and the tank's measurements update server-side at roughly 60-second cadence. Expect up to a minute or two between the physical event and your automation firing; none of these triggers is instant.

### Why is the water_heater entity missing?

Your config entry is in Simple experience mode. The `water_heater` entity, the holiday datetime entities, and the full set of number controls exist only in Advanced mode; Simple mode keeps a single `Hot water boost` slider. Switch modes in the integration's options — see [configuration.md](configuration.md).

### Why does set_holiday_dates reject my dates?

Two common causes: the start is not before the end (the service requires strictly earlier), or a floor/label target slipped in, which the services reject by design. A date with no time is accepted and read as local midnight. Naive datetimes are read as local time, so no timezone suffix is needed.

## 🔗 See also

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Entities](entities.md)
- [Energy dashboard](energy.md)
- [Troubleshooting](troubleshooting.md)
- [API notes](api.md)
- [README](../README.md)
