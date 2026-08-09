# Configuration

This page covers the full setup and configuration of the integration: the three-step guided config flow, the Simple and Advanced experience modes and exactly which entities each creates, every option in the options flow, reauthentication, reconfiguring credentials, and multi-tank setups. Entity ids in examples use `<serial>` as a placeholder for your tank's serial number — the integration names devices `Mixergy Tank (<SERIAL>)`, so real ids look like `sensor.mixergy_tank_mx001234_current_charge`.

---

## 🧭 The guided setup flow

Setup is a three-step guided flow: sign in with your Mixergy account, pick your tank, then choose an experience mode. Each step validates against the Mixergy cloud API before you can continue, so a typo in your password or serial number surfaces immediately rather than as a broken integration later.

Start it from **Settings** → **Devices & Services** → **Add Integration** → **Mixergy**.

The whole flow — and every option, entity name, and repair message — is
localised in English, German, French, and Italian, following your Home
Assistant language setting.

### Step 1 — Sign in to Mixergy

1. Enter the **email address** and **password** you use in the Mixergy app.
2. The flow tests the credentials against the Mixergy cloud API before moving on.
3. On failure you stay on the form with a specific error — **Invalid email address or password** for bad credentials, **Unable to connect to the Mixergy API** for network problems, or a generic unexpected-error message.

Leading and trailing whitespace in the email address is stripped, so a stray space from a password manager does no harm. After a successful sign-in the flow also fetches the list of tanks on your account — this powers the picker in the next step. If that listing fails, setup still continues; you type the serial by hand instead.

### Step 2 — Find your tank

When the account listing succeeded, this step shows a **dropdown of the tanks on your account** — with any serials you have already configured filtered out. The dropdown also accepts a typed value, so you can enter a serial that is not in the list. When the listing failed or every tank is already configured, you get a plain text field instead.

1. Pick your tank from the dropdown, or type the serial number printed on the white label on the side of the tank.
2. The serial is **uppercased** and whitespace-stripped automatically — `a12345 ` becomes `A12345`.
3. The flow checks the serial is not already configured — if it is, setup aborts with **This tank is already configured**.
4. The flow then verifies the tank exists on your account. **No tank found with the specified serial number** means the serial does not match a tank your account owns.

### Step 3 — Choose your experience

Pick **Simple** or **Advanced**. Simple is the default and suits everyday monitoring plus a hot water boost slider; Advanced unlocks the full control surface — temperature settings, heat source switching, PV divert controls, and holiday scheduling. You can change the mode at any time from the options flow, so the choice is not permanent.

Confirming this step creates the config entry, titled `Mixergy Tank (<SERIAL>)`.

---

## 🎛️ Simple vs Advanced — what does each mode create?

Both modes create every sensor and binary sensor — monitoring is never restricted. Simple adds one control on top: the **Hot water boost** slider. Advanced replaces that with the full control surface across the water heater, switch, select, button, datetime, and number platforms. The difference is purely which control entities exist; the data is identical.

| Platform | Simple | Advanced |
| -------- | ------ | -------- |
| **Sensor** | ✅ All 18 sensors (19 with the cost sensor enabled) | ✅ Same |
| **Binary sensor** | ✅ All 7 binary sensors | ✅ Same |
| **Number** | ✅ Hot water boost slider only | ✅ All 7 number controls |
| **Water heater** | ❌ | ✅ 1 entity |
| **Switch** | ❌ | ✅ 4 switches |
| **Select** | ❌ | ✅ 1 select |
| **Button** | ❌ | ✅ 1 button |
| **Datetime** | ❌ | ✅ 2 datetimes |

The [entities reference](entities.md) documents every entity in detail. In summary, Advanced mode adds:

| Platform | Entities |
| -------- | -------- |
| Water heater | The tank as a `water_heater` entity — target temperature (45–70 °C), operation mode, away mode |
| Number | Target temperature (45–70 °C), Target charge (0–100 %), Cleansing temperature (51–55 °C), PV cut-in threshold (0–500 W), PV charge limit (0–100 %), PV target current (−1–0), PV over-temperature limit (45–60 °C) |
| Switch | Grid assistance (DSR), Frost protection, Medical research donation, PV export divert |
| Select | Default heat source (electric / indirect / heat pump) |
| Button | Clear holiday dates |
| Datetime | Holiday start, Holiday end |

PV entities are created regardless of hardware but show as **unavailable** when your tank has no PV diverter fitted.

### What happens to the boost slider when I switch to Advanced?

Nothing is lost. The Simple-mode **Hot water boost** slider and the Advanced-mode **Target charge** number share the same unique id — they are the same underlying control with a different name — so entity history is preserved when you switch modes in either direction.

### Which mode do upgraded installations get?

Config entries created before experience modes existed are backfilled to **Advanced** on their first load after upgrading. Those installations historically had every entity, and flipping them to Simple would silently remove entities and break automations. Fresh installations default to Simple in the setup flow.

---

## ⚙️ Options

Open **Settings** → **Devices & Services** → **Mixergy** → **Configure** to change the experience mode, poll interval, water-level alert thresholds, and electricity rate. Saving the form reloads the integration automatically — new entities appear straight away, and threshold or rate changes take effect on the rebuilt entities without a Home Assistant restart. Switching from Advanced to Simple stops providing the advanced entities, but their registry entries remain (shown as unavailable) until you delete them from the entities list.

| Option | Range | Default | Effect |
| ------ | ----- | ------- | ------ |
| Experience mode | Simple / Advanced | Simple | Which control entities exist — see the comparison above |
| Update interval | 30–300 s, step 1 | 30 s | How often the integration polls the Mixergy cloud API |
| Low hot water alert threshold | 0–100 %, step 1 | 5 % | `Low hot water` binary sensor turns on below this charge |
| No hot water alert threshold | 0–100 %, step 0.5 | 0.5 % | `No hot water` binary sensor turns on below this charge |
| Electricity price per kWh | 0–10, step 0.001 | 0 | Creates the `Electric heating cost` sensor; 0 disables it |

### How often should I poll?

Leave the update interval at the default 30 s unless you have a reason to slow it down. Tank measurements update server-side at roughly 60-second cadence, so polling faster than 30 s wastes API calls and risks rate-limit throttling — which is why the flow rejects anything below 30 s.

### How do the water-level thresholds interact?

The **no hot water** threshold must sit strictly below the **low hot water** threshold. The options form rejects a no-water value greater than or equal to the low-water value — otherwise the two alert binary sensors would contradict each other, with the no-water alert on while the low-water alert stays off.

On a validation error the form re-opens pre-filled with what you typed, not the stored values, so you correct one field rather than retyping the lot.

The thresholds drive the two alert binary sensors, which you can use directly in automations:

```yaml
alias: "Warn when hot water runs low"
triggers:
  - trigger: state
    entity_id: binary_sensor.mixergy_tank_<serial>_low_hot_water
    to: "on"
conditions:
  - condition: time
    after: "07:00:00"
    before: "22:00:00"
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: "Hot water charge has dropped below the low threshold."
```

### How do I enable the cost sensor?

Set **Electricity price per kWh** to your tariff rate — for example `0.245` for 24.5p/kWh. Any value above 0 creates the `Electric heating cost` sensor on the next reload. Setting it back to 0 stops providing the sensor — its registry entry lingers as unavailable until you delete it from the entities list. The 0.001 step allows sub-penny tariff precision. The [energy guide](energy.md) covers what the sensor tracks.

---

## 🔁 What happens when my credentials stop working?

Home Assistant starts a reauthentication flow automatically — you do not need to remove and re-add the integration. An authentication failure during polling, or during a command such as setting the target temperature, raises a repair notification asking you to re-enter your Mixergy credentials for the affected tank.

The reauth form asks for your email address and password again. Beyond checking the new credentials authenticate, the flow also verifies the account **still owns the configured tank** — without that check you could reauthenticate with a different valid Mixergy account and the integration would reload straight into a tank-not-found failure. On success the entry updates and reloads.

---

## 🛠️ How do I change my account credentials?

Use the reconfigure flow: **Settings** → **Devices & Services** → **Mixergy** → three-dots menu → **Reconfigure**. You can update the email address and password; the **tank serial stays fixed** because it is the device's identity. The new credentials are validated for both authentication and ownership of the configured tank before the entry reloads.

To point Home Assistant at a different tank, add a new config entry for that tank instead — see below.

---

## 🛁 Can I add more than one tank?

Yes — each tank is its own config entry, so add the integration once per tank: **Settings** → **Devices & Services** → **Add Integration** → **Mixergy** and run the setup flow again. Each entry has its own credentials, experience mode, poll interval, thresholds, and electricity rate, configured independently.

The tank picker in step 2 filters out serials that are already configured, so on a multi-tank account the second run offers only the remaining tanks. The serial number is the unique id — attempting to add the same tank twice aborts with **This tank is already configured**.

---

## 🔗 See also

- [Installation](installation.md) — requirements, HACS custom repository, manual install
- [Entities reference](entities.md) — every entity, per mode, in detail
- [Automations](automations.md) — services and example automations
- [Energy](energy.md) — Energy Dashboard and the cost sensor
- [Troubleshooting](troubleshooting.md) — errors, reauth loops, connectivity
- [API notes](api.md) — how the integration talks to the Mixergy cloud
- [README](../README.md) — project overview
