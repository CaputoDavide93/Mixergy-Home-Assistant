# Installation

This page covers everything needed to get the integration running: what you need before you start, installing through HACS (recommended) or manually, how updates arrive and how to apply them safely, how to uninstall cleanly, and where the integration stores your data. Entity ids in examples use `<serial>` as a placeholder for your tank's serial number — the integration names devices `Mixergy Tank (<SERIAL>)`, so real ids look like `sensor.mixergy_tank_mx001234_current_charge`.

---

## ✅ Requirements

You need Home Assistant 2025.8 or newer, a Mixergy smart hot water tank, and the Mixergy cloud account you use in the Mixergy app. Your Home Assistant instance must be able to reach `https://www.mixergy.io` — this is a cloud-polling integration with no local API, so no internet means no data.

| Requirement | Detail |
| ----------- | ------ |
| Home Assistant | 2025.8 or newer |
| Mixergy tank | Any model; PV diverter hardware adds extra entities |
| Mixergy cloud account | The username and password from the Mixergy app |
| Tank serial number | Printed on the label of your tank |
| Network | Outbound HTTPS to `www.mixergy.io` |
| Extra Python packages | None — the integration has no external requirements |

The integration polls the Mixergy cloud API over HTTPS with certificate verification on every call. There is no local connection to the tank itself.

---

## 📦 Install via HACS (recommended)

This integration is distributed as a HACS **custom repository** — it is not in the HACS default store. Add `https://github.com/CaputoDavide93/mixergy-home-assistant` as a custom repository with category **Integration**, install it, and restart Home Assistant. The badge below opens the repository directly in your instance.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=CaputoDavide93&repository=mixergy-home-assistant&category=integration)

Or add the repository by hand:

1. Open [HACS](https://hacs.xyz/) in Home Assistant
2. Go to **Integrations** → click the 3-dots menu → **Custom repositories**
3. Add `https://github.com/CaputoDavide93/mixergy-home-assistant` with category **Integration**
4. Search for **Mixergy** and install it
5. Restart Home Assistant

> Searching HACS without adding the custom repository first can surface unrelated Mixergy projects from the default store. Check the repository owner is **CaputoDavide93** before installing.

After the restart, add the integration itself: **Settings** → **Devices & Services** → **Add Integration** → search for **Mixergy**, then enter your Mixergy account username, password, and the serial number from your tank label. The [configuration guide](configuration.md) covers the rest of the setup flow, including the Simple/Advanced experience modes.

---

## 🛠️ Manual installation

Manual installation copies the integration files into your Home Assistant configuration directory yourself. It works identically to a HACS install once running, but you take on the job of applying updates by hand — HACS will not know the integration exists.

1. Download the [latest release](https://github.com/CaputoDavide93/mixergy-home-assistant/releases) from GitHub
2. Copy `custom_components/mixergy/` into your HA `config/custom_components/` directory
3. Restart Home Assistant
4. Add the integration via **Settings** → **Devices & Services** → **Add Integration** → **Mixergy**

Your directory should end up looking like this:

```text
config/
└── custom_components/
    └── mixergy/
        ├── __init__.py
        ├── manifest.json
        └── ...
```

---

## 🔄 How do updates arrive?

Updates arrive as GitHub releases on [CaputoDavide93/mixergy-home-assistant](https://github.com/CaputoDavide93/mixergy-home-assistant/releases). If you installed through HACS, new releases appear in the HACS update list and on Home Assistant's **Settings** page like any other update. Manual installs receive nothing automatically — watch the releases page yourself.

---

## ⬆️ How do I update safely?

Read the release notes first, take a Home Assistant backup, then apply the update through HACS and restart. Your configuration entry — credentials, serial number, experience mode, and options — survives updates, so you never re-enter anything after upgrading.

1. Open the release notes for the new version on the [releases page](https://github.com/CaputoDavide93/mixergy-home-assistant/releases) and check for breaking changes
2. Take a Home Assistant backup (**Settings** → **System** → **Backups**)
3. In HACS, open **Mixergy** and select **Update** (or use the update entry on the Settings page)
4. Restart Home Assistant
5. Confirm the tank device still reports — check an entity such as `sensor.mixergy_tank_<serial>_current_charge` has a fresh state

For a manual install, replace the whole `config/custom_components/mixergy/` directory with the new release's copy, then restart. Do not merge old and new files — stale leftovers from a previous version cause hard-to-diagnose errors.

---

## 🗑️ How do I uninstall cleanly?

Remove the integration entry first, then remove the repository from HACS. Deleting the entry removes the device, its entities, and the stored credentials; removing the repository deletes the code. Doing it in the other order leaves an orphaned config entry pointing at code that no longer exists.

1. Go to **Settings** → **Devices & Services** → **Mixergy**
2. Open the 3-dots menu on the entry and select **Delete**
3. In HACS, open **Mixergy** → 3-dots menu → **Remove**
4. Restart Home Assistant

For a manual install, replace steps 3–4 with deleting the `config/custom_components/mixergy/` directory and restarting.

If you created automations, dashboards, or Energy Dashboard entries that reference Mixergy entities, remove those references too — they will show as unavailable entities otherwise.

---

## 🔐 What data is stored where?

Your Mixergy username, password, and tank serial number live in the Home Assistant config entry — Home Assistant's own storage under your `config/.storage/` directory, protected by the same access controls as the rest of your HA configuration. Nothing is written elsewhere, and deleting the integration entry removes the credentials with it.

| Data | Where | Notes |
| ---- | ----- | ----- |
| Username, password, serial | HA config entry | Removed when you delete the entry |
| API bearer token | In memory | Refreshed automatically 5 minutes before expiry |
| Diagnostics downloads | File you export | Credentials and tokens are automatically redacted |

All communication with the Mixergy cloud runs over TLS with certificate verification and a 30-second request timeout. If your credentials change or expire, the integration prompts you to re-authenticate through the Home Assistant UI rather than storing anything new on its own.

---

## 🔗 See also

- [Configuration](configuration.md) — setup flow, experience modes, and options
- [Entities](entities.md) — every sensor, binary sensor, and control
- [Automations](automations.md) — services, device triggers, and examples
- [Energy Dashboard](energy.md) — electric and PV energy sensors
- [Troubleshooting](troubleshooting.md) — common errors and debugging
- [API](api.md) — the Mixergy cloud API client
- [README](../README.md) — project overview
