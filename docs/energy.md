# Energy Dashboard & Cost Tracking

This page shows you how to add your Mixergy tank to the Home Assistant Energy Dashboard, explains exactly how the integration turns CT-clamp power readings into cumulative kWh totals, covers the optional electric cost sensor and its tariff option, and finishes with how to reset totals and how to shift heating into cheap tariff windows.

Entity ids on this page use `<serial>` as a placeholder for your tank's serial number — a real id looks like `sensor.mixergy_tank_mx001234_electric_heat_energy`.

## ⚡ Which entities belong in the Energy Dashboard?

Add **Electric heat energy** under *Individual devices* — it is a kWh sensor with device class `energy` and state class `total_increasing`, which is what the dashboard requires. On tanks with a PV diverter, **PV energy** is live too; add it under *Individual devices* as well (the entity exists on every tank but stays unavailable without diverter hardware). The power sensors do not qualify — the dashboard consumes energy (kWh), not power (W or kW).

| Entity | Unit | State class | Dashboard placement |
| --- | --- | --- | --- |
| `sensor.mixergy_tank_<serial>_electric_heat_energy` | kWh | `total_increasing` | Individual devices |
| `sensor.mixergy_tank_<serial>_pv_energy` | kWh | `total_increasing` | Individual devices — unavailable unless the tank has a PV diverter |
| `sensor.mixergy_tank_<serial>_electric_heating_cost` | HA currency | `total` | Not a dashboard entity — chart it with a statistics card or use it in automations |

Keep **PV energy** out of the *Solar production* section. It measures energy the diverter pushes **into the tank**, not what your panels generate — if your inverter already feeds the dashboard, adding PV energy as production would double-count it.

## 🖱️ How do I add the tank to the dashboard?

1. Open **Settings → Dashboards → Energy**.
2. Scroll to the **Individual devices** section.
3. Select **Add device**.
4. Pick `Electric heat energy` for your tank.
5. If your tank has a PV diverter, repeat steps 3–4 for `PV energy`.
6. Select **Save**.

The dashboard builds its view from long-term statistics, which accumulate hourly — expect the first data to appear within an hour or two of adding the sensors.

## 🧮 How does the integration compute energy?

On every successful poll the integration multiplies the current power reading by the time elapsed since the previous poll — the rectangle method, ΔE (kWh) = P (W) × Δt (h) ÷ 1000 — and adds the result to a running total. Only finite, positive power readings accumulate; anything else adds zero.

The two totals draw from different power sources:

- **Electric heat energy** integrates the CT-clamp power, and only while the electric immersion is the active heat source. Clamp power measured while the immersion is off contributes nothing.
- **PV energy** integrates the PV diverter power on tanks that have one.

Three protections keep the totals honest:

| Protection | Behaviour |
| --- | --- |
| Outage cap | The integration window is capped at 2× the poll interval, so a long outage (HA paused, network gone, API down) never credits a fictitious multi-hour spike on the next successful poll. Short gaps within the cap are bridged correctly. |
| Failed polls | A failed poll accumulates nothing — the integration resynchronises its clock and re-writes the current total unchanged. Totals never go backwards, so Home Assistant never misreads a failure as a counter reset. |
| Restart persistence | The sensors are `RestoreSensor` entities: the running total survives restarts and is written back to the state machine immediately on startup, so the Energy Dashboard never sees a transient zero between restart and the first poll. |

Clock corrections (NTP skew) are floored at zero elapsed time, so a backwards clock step can never subtract from a total. Totals display to 3 decimal places and carry 4 internally.

## 🤔 Why do my readings differ from the Mixergy app?

Expect small differences — the integration samples power at your configured poll interval (30–300 s, default 30) and assumes it stays constant between polls, while Mixergy meters on its own side. Short bursts of heating that start and end between two polls are approximated, not measured exactly.

Other sources of divergence:

- The totals start at zero when you install the integration — they never include history from before that point.
- Energy used during an outage longer than 2× the poll interval is deliberately discarded by the outage cap rather than guessed.
- Electric heat energy excludes clamp power measured while the immersion is inactive, so it tracks heating energy specifically.

## 💷 Electric cost sensor

Set a tariff in the integration's options to enable `sensor.mixergy_tank_<serial>_electric_heating_cost` — a running total of what electric heating has cost you. The sensor accumulates cost directly (kWh × your rate at the moment of use), so changing the tariff later affects new heating only and never rewrites history.

To enable it:

1. Open **Settings → Devices & services → Mixergy**.
2. Select **Configure**.
3. Set **Electricity price per kWh (0 to disable cost sensor)** — the field accepts 0–10 in steps of 0.001, so tariffs like `0.285` work to three decimal places.
4. Select **Submit**. The cost sensor appears after the options save. Setting the rate back to 0 stops providing it — delete the leftover unavailable entity from the entities list if you want it gone completely.

| Property | Value |
| --- | --- |
| Device class | `monetary` |
| State class | `total` |
| Unit | Follows your Home Assistant configured currency (**Settings → System → General**) |
| Display precision | 2 decimal places |
| Persistence | `RestoreSensor` — survives restarts, never goes backwards on failed polls |

The state class is `total` rather than `total_increasing` because Home Assistant permits only `total` for monetary sensors — the value is still a monotonic running total and records identically in long-term statistics. Cost accrual uses the same capped rectangle integration as the energy sensors, including the failed-poll and outage protections.

## 🔄 How do I reset the totals?

Correct the recorded history through Home Assistant's statistics tools — the Energy Dashboard reads long-term statistics, so adjusting them fixes what the dashboard shows.

1. Open **Developer tools → Statistics**.
2. Search for the sensor — for example `sensor.mixergy_tank_<serial>_electric_heat_energy`.
3. Use the adjust-sum control on the sensor's row to correct the recorded sum from a chosen point in time.

## 🌙 Shifting heating into cheap tariff windows

Pair the energy tracking with the low-charge binary sensors to recharge the tank when electricity is cheap. `binary_sensor.mixergy_tank_<serial>_low_hot_water` turns on when charge drops below its threshold (default 5%; `no_hot_water` fires at 0.5%) — both thresholds are configurable in the integration's options.

```yaml
automation:
  - alias: "Recharge Mixergy tank during off-peak window"
    triggers:
      - trigger: state
        entity_id: binary_sensor.mixergy_tank_<serial>_low_hot_water
        to: "on"
    conditions:
      - condition: time
        after: "00:30"
        before: "04:30"
    actions:
      - action: number.set_value
        target:
          entity_id: number.mixergy_tank_<serial>_target_charge
        data:
          value: 80
```

The target-charge number is named **Target charge** in Advanced mode and **Hot water boost** in Simple mode — check your entity id under **Settings → Devices & services → Mixergy**. More patterns, including tariff-window heating schedules, live on the [automations page](automations.md).

## 🔗 See also

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Entities](entities.md)
- [Automations](automations.md)
- [Troubleshooting](troubleshooting.md)
- [API reference](api.md)
- [README](../README.md)
