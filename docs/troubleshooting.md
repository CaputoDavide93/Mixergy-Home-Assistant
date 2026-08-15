# Troubleshooting & FAQ

Symptom-first fixes for the problems people actually hit with the Mixergy integration — setup failures, unavailable entities, missing PV controls, stuck holiday mode, reauthentication loops — followed by how to gather debug logs and diagnostics, where to file issues, and answers to the most common questions about how the integration works.

Entity ids in the examples use `<serial>` as a placeholder for your tank's serial number. The integration names devices `Mixergy Tank (<SERIAL>)`, so a real id looks like `sensor.mixergy_tank_mx001234_current_charge`.

## 🚑 Setup problems

### Why does setup fail with "Invalid email address or password"?

The integration authenticates against the Mixergy cloud, so it needs your **Mixergy account** email and password — the same credentials you use in the Mixergy app and at mixergy.io. There are no local credentials, API keys, or tokens to create; if the app accepts the login, the integration will too.

Check in this order:

1. Log in at [www.mixergy.io](https://www.mixergy.io) with the exact same email and password. If that fails, reset your password with Mixergy first.
2. Watch for a trailing space in the password — the email field is trimmed, the password is used verbatim.
3. If the error is "Unable to connect to the Mixergy API" rather than "Invalid email address or password", the problem is reachability, not credentials — see [Why are all my entities unavailable?](#why-are-all-my-entities-unavailable) below.

If your password changed after setup, you do not need to remove the entry — Home Assistant raises a reauthentication prompt and the integration's reauth flow accepts the new credentials in place.

### Why does setup say "No tank found with the specified serial number"?

The serial number you entered does not appear on the tanks list of the account you signed in with. The serial is printed on the label on the tank itself, and the tank must be registered to **your** Mixergy account — an installer's or previous owner's registration is invisible to your login.

Check in this order:

1. Read the serial from the label on the tank (or from the Mixergy app) and re-enter it. Case does not matter — the integration uppercases it.
2. Confirm the tank shows up when you log in to the Mixergy app or [www.mixergy.io](https://www.mixergy.io) with the same account. If it does not, ask Mixergy support to move the registration to your account.
3. When the account lists tanks, the config flow offers a dropdown of serials it can see — pick from the list instead of typing.

If a tank that used to work disappears from your account later (decommissioned, hardware replaced, account changed), the integration raises a **repair issue** in Settings → Repairs pointing you at the Reconfigure flow. The repair clears itself automatically on the first successful poll after the tank is reachable again — no manual dismissal needed.

## 📡 Runtime problems

### Why are all my entities unavailable?

Every entity is fed by one data coordinator per tank, so a failed poll marks the whole device unavailable at once. The most common cause is connectivity: the integration polls `https://www.mixergy.io`, and anything that blocks that host — DNS, a firewall rule, an upstream outage — blanks every entity until the next successful poll.

Check in this order:

1. Confirm your Home Assistant host can reach the API — from the HA machine:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://www.mixergy.io/api/v2
   ```

   A `200` means the cloud is reachable; anything else points at your network or a Mixergy outage.
2. Check the Mixergy app — if the app cannot see the tank either, the tank has lost its own connection to the cloud and there is nothing to fix on the HA side.
3. Enable [debug logging](#how-do-i-enable-debug-logging) and look for `Error communicating with Mixergy API` in the log — the message includes the underlying cause (timeout, DNS, HTTP status).

The integration is deliberately tolerant of partial failures. Each poll fetches three things — measurement, settings, and schedule. Only the **measurement** fetch is required to succeed; if the settings or schedule sub-fetch fails transiently, the integration logs a warning and falls back to the last successfully fetched values. A brief cloud hiccup on a secondary endpoint therefore does **not** blank your entities:

| What fails | What you see |
| --- | --- |
| Measurement fetch | All entities unavailable until the next successful poll |
| Settings fetch only | Warning in the log; settings entities keep their last-known values |
| Schedule fetch only | Warning in the log; schedule/holiday entities keep their last-known values |
| Authentication (after retry) | Reauthentication prompt in Settings → Devices & Services |
| Tank missing from account | Repair issue raised; entities unavailable until the tank is back on the account |

### Why are the PV entities missing or unavailable?

The PV entities only work when your tank actually has a PV diverter fitted. The integration reads the tank's configuration from the API at discovery — a `mixergyPvType` of `NO_INVERTER` means no diverter, and every PV entity (PV power, clamp power, PV energy, export divert switch, and the four PV number controls) reports **unavailable**.

Check in this order:

1. Confirm the tank has a PV diverter — the availability of the PV entities follows the API's configuration flag exactly, so if Mixergy's own app shows no solar features, neither will Home Assistant.
2. The PV **controls** (cut-in threshold 0–500 W, charge limit 0–100%, target current −1–0, over-temperature 45–60 °C, export divert switch) exist only in **Advanced** experience mode. Switch modes in the integration's Configure dialogue.
3. If a diverter was fitted after setup, reload the integration (or restart Home Assistant) so tank discovery re-reads the configuration.

### Why is my energy sensor not offered in the Energy dashboard?

The Energy dashboard offers entities that are enabled, carry an energy device class with an energy unit, and use a `total` or `total_increasing` state class. `sensor.mixergy_tank_<serial>_electric_heat_energy` (kWh, `total_increasing`) qualifies out of the box, so it appears under "Individual devices" without any configuration — if it is missing, the entity has been disabled or renamed.

Check in this order:

1. Open Settings → Devices & Services → Mixergy → your tank, and confirm the **Electric heat energy** sensor exists and is enabled. Re-enable it from the entity's settings cog if someone disabled it.
2. Confirm the entity has a numeric state — a freshly added entity needs at least one successful poll before the dashboard accepts it.
3. `sensor.mixergy_tank_<serial>_pv_energy` follows the PV diverter flag — on a tank without a diverter it is unavailable and will not be offered.

The optional running-cost sensor only exists when you set an electricity rate in the integration's options; without a rate there is no cost entity to add.

### Why is the charge stuck or updating slowly?

The tank reports measurements to the Mixergy cloud roughly once a minute, so that is the freshest data any client can see — polling faster cannot invent newer readings. The integration polls every 60 seconds by default (configurable 30–300 s) to match that cadence, so consecutive polls can still legitimately return the same value.

Check in this order:

1. Compare against the Mixergy app — if the app shows the same value, the integration is faithfully reporting what the cloud has.
2. Check **Tank connectivity**. Online means the tank report is fresh; offline means Home Assistant reached the cloud but the latest physical-tank report is older than five minutes (or three configured poll intervals). If the tank does not provide report timestamps, this entity is unavailable rather than guessing.
3. Compare **Last tank measurement** (enabled diagnostic) with **Last successful update** (disabled diagnostic). If Last successful update advances but Last tank measurement does not, the cloud is serving an old tank report; check the tank's network connection and power.
4. Check **Operating reason** and **Charge target active**. They show whether an automatic schedule, manual schedule, boost, cleansing cycle, or vacation mode is currently requesting a target — the integration does not run a background automation that holds charge at a fixed level.
5. If polls are failing intermittently, see [Why are all my entities unavailable?](#why-are-all-my-entities-unavailable).
6. If you want to reduce load on the Mixergy cloud, raise the poll interval in Configure — anywhere up to 300 s. Given the roughly one-minute server-side cadence, 60 s costs you almost nothing in freshness.

### Why will holiday mode not clear?

You have three routes to clear holiday mode, and all three end in the same API call — pick whichever is closest to hand. The tank's holiday state comes from the cloud, so after a clear the integration refreshes immediately; if the state lingers, the write failed and the error will say why.

Try in this order:

1. Call the service directly — works in both experience modes. With no target it clears every configured tank; in a multi-tank home add a `target:` with the tank's device:

   ```yaml
   actions:
     - action: mixergy_tank.clear_holiday_dates
   ```

2. Press the **Clear holiday** button on the device page (Advanced experience mode only).
3. Toggle **away mode** off on the water heater entity (Advanced only) — away mode is implemented as a holiday window, so switching it off clears the same dates.

If the command raises an authentication error, complete the reauthentication prompt first — write commands trigger the reauth flow on an auth failure, and nothing is written until credentials are valid again.

### Why does Home Assistant keep asking me to reauthenticate?

A reauthentication prompt means the Mixergy cloud rejected your credentials even after a fresh login attempt — the integration retries a `401` once with a new token before giving up, so a prompt is never a transient blip. The usual cause is a password changed server-side (in the app or at mixergy.io).

Check in this order:

1. Log in at [www.mixergy.io](https://www.mixergy.io) and confirm the credentials work there. If you changed your password recently, enter the new one in the reauth prompt.
2. If the reauth form itself reports "tank not found", the account you entered no longer owns this tank. The reauth flow deliberately verifies tank ownership before saving — otherwise the entry would reload straight into a tank-not-found error. Reauthenticate with the owning account, or reconfigure with the correct serial.
3. If prompts recur with credentials you know are valid, capture a [debug log](#how-do-i-enable-debug-logging) around one occurrence and [file an issue](#where-do-i-file-issues).

## 🔍 Diagnosing

### How do I enable debug logging?

Add the integration's logger to your `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.mixergy_tank: debug
```

Alternatively, enable debug logging without a restart from Settings → Devices & Services → Mixergy → **Enable debug logging**; disabling it again downloads the captured log. Debug level shows authentication events, tank discovery (model, firmware, PV flag), and cached-fallback warnings for failed settings/schedule fetches.

### How do I download diagnostics?

Open Settings → Devices & Services → Mixergy, click the three-dot menu on the entry, and choose **Download diagnostics**. The file is safe to attach to a public issue: your username, password, and tank serial number are redacted, and the raw schedule payload is removed because it can contain account-specific data.

What remains is what a maintainer needs to reproduce your setup — the integration options (experience mode, poll interval, thresholds, tariff), the coordinator's poll interval and last-update status, and the current tank data (measurement, settings, parsed schedule fields).

### Where do I file issues?

File issues at [github.com/CaputoDavide93/Mixergy-Home-Assistant/issues](https://github.com/CaputoDavide93/Mixergy-Home-Assistant/issues). A report the maintainer can act on includes:

1. What you expected and what happened instead.
2. Your Home Assistant version and the integration version (Settings → Devices & Services → Mixergy).
3. The [diagnostics download](#how-do-i-download-diagnostics) — it is already redacted.
4. A [debug log](#how-do-i-enable-debug-logging) excerpt covering the failure, if the problem is intermittent.

## ❓ FAQ

### Why is the icon missing in HACS?

HACS shows a grey placeholder instead of the Mixergy icon. **Nothing is wrong with your install** — the icon appears correctly everywhere inside Home Assistant itself (Settings → Devices & Services, the device page, and every entity).

It is a known HACS limitation, not an issue with this integration. Since Home Assistant 2026.3 custom integrations ship their brand images inside the integration (this one does — `custom_components/mixergy_tank/brand/`), and `home-assistant/brands` no longer accepts submissions from custom integrations. The HACS dashboard still reads icons from that older brands CDN, so any custom integration published after February 2026 shows a placeholder there.

There is nothing to fix on your side and no effect on functionality. Tracked upstream at [hacs/integration#5171](https://github.com/hacs/integration/issues/5171), with a fix proposed in [hacs/integration#5388](https://github.com/hacs/integration/pull/5388).

### Does this work without internet, or locally?

No. This is a cloud-polling integration for the official Mixergy API at `www.mixergy.io` — the tank has no supported local API, so every reading and every command goes through Mixergy's cloud. If your internet connection or Mixergy's service is down, entities go unavailable until it recovers.

### Is this the Mixergy integration from the HACS default store?

No. This is an independent project, installed as a **HACS custom repository**. Any other Mixergy integration is an unrelated codebase — never run two integrations against the same tank, and file issues for this one at [github.com/CaputoDavide93/Mixergy-Home-Assistant](https://github.com/CaputoDavide93/Mixergy-Home-Assistant/issues).

### How many tanks does it support?

Multiple — one config entry per tank, each keyed by its serial number. The config flow lists the tanks on your account so you can pick each one; the `set_holiday_dates`, `clear_holiday_dates`, and `boost_charge` services accept a standard Home Assistant target (entity, device, or area) to act on a specific tank, and apply to every configured tank when called without a target.

### Does boosting cost extra API calls or hammer the cloud?

No. Reads come from one coordinator per tank on your configured poll interval, and writes are serialised — schedule operations (holiday dates, default heat source) take a lock so concurrent callers cannot interleave, and each write platform runs one update at a time. A boost is one write plus one refresh request, nothing more.

### Will it break on new Home Assistant versions?

The CI test suite runs on a weekly schedule against the latest Home Assistant core, so core API churn is caught between releases rather than by users. The integration also tracks deprecations ahead of enforcement — the v1.3.2 changelog entry documents fixes landed before their HA 2026.12 and 2027.8 deadlines. Release 2.2.0 is verified on HA 2026.8.2, and the supported floor remains HA 2025.8.

### What data leaves my network?

Your Mixergy account credentials and tank commands go to `mixergy.io` over TLS — nothing else, to nobody else. The client validates every API URL before sending the bearer token and refuses plain-HTTP or off-origin links, so the token cannot leak to a third party even if the cloud served a bad link. There are no analytics, telemetry, or third-party services.

## 🔗 See also

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Entities](entities.md)
- [Automations](automations.md)
- [Energy dashboard](energy.md)
- [API client](api.md)
- [README](../README.md)
