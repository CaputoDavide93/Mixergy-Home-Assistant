# ❓ FAQ

Short answers to the questions people ask before and after installing the Mixergy integration. Setup, step by step, is in [setup.md](setup.md); faults are in [troubleshooting.md](troubleshooting.md).

## Getting started

### What is the Mixergy integration for Home Assistant?

It is a free, open-source (MIT) Home Assistant custom integration that reads and controls a Mixergy smart hot water tank through Mixergy's cloud API. It gives you sensors for charge, temperatures, heat source and energy, a hot water boost control, an optional native water heater entity, and services for holiday scheduling. You install it through HACS as a custom repository.

### Is it an official Mixergy product?

No. It is an independent project and is not made or endorsed by Mixergy. It talks to the same cloud service as the Mixergy app, using your own account.

### Can I run it next to another Mixergy integration?

Avoid it: two integrations polling the same tank double the cloud requests. Remove the other one first.

### How do I install it?

Add `https://github.com/CaputoDavide93/Mixergy-Home-Assistant` to HACS as a custom repository of type Integration, download Mixergy, restart Home Assistant, then add it from **Settings → Devices & services**. The numbered walkthrough with screenshots is in [setup.md](setup.md).

### What do I need before I start?

You need Home Assistant 2025.8 or newer, HACS, and the email address and password of your Mixergy app account. The tank serial number is printed on its label, but the setup lists the tanks on your account, so you can usually pick it from a dropdown.

### What is the difference between Simple and Advanced mode?

Simple creates every sensor plus one control, the Hot water boost slider. Advanced adds the full control surface: a water heater entity, temperature numbers, the heat source select, PV diverter settings, switches and holiday pickers. You can change the mode at any time from the integration's Configure button. The exact entity lists are in [configuration.md](configuration.md).

## How it works

### Does it work without internet, or locally?

No. It polls Mixergy's cloud API at `www.mixergy.io`, and the tank has no supported local API, so every reading and every command goes through the cloud. When your internet connection or Mixergy's service is down, entities show as unavailable until it returns.

### How often does it update?

Every 60 seconds by default, and you can set anything from 30 to 300 seconds in the options. Polling faster than the tank reports does not produce fresher data, because the tank sends a new measurement about once a minute. The `Last tank measurement` sensor shows when the tank last reported.

### How many tanks can I add?

As many as your account has. Each tank is its own config entry and its own device. The `set_holiday_dates`, `clear_holiday_dates` and `boost_charge` services accept a standard Home Assistant target (entity, device or area) to act on one tank, and apply to every configured tank when called without one.

### Does boosting cost extra API calls?

No. A boost is one write followed by one refresh request. Reads come from one coordinator per tank on your poll interval, and schedule writes take a lock so two callers cannot overwrite each other.

### Can I use it with voice assistants?

In Advanced mode the tank is a native Home Assistant `water_heater` entity, so anything that works with water heaters in Home Assistant can address it. Simple mode has no water heater entity, only the boost slider as a number entity.

## Energy and cost

### Does it work with the Energy dashboard?

Yes. Add **Electric heat energy** under Individual devices. On tanks with a PV diverter, **PV energy** can go there too. Do not add PV energy under Solar production, because it measures energy diverted into the tank, not what your panels generate. Details are in [energy.md](energy.md).

### Can I track what heating costs?

Yes. Set an electricity price per kWh in the options and an `Electric heating cost` sensor appears. A price of 0 turns it off.

## Hardware and compatibility

### Which tanks does it work with?

The code handles electric immersion, indirect (gas or oil coil) and heat pump heating, and tanks with a PV diverter. The maintainer has run it live on one tank, an indirect-heated model on firmware 7.2.1. Other configurations are covered by unit tests with sample API responses but are unverified on hardware, so if you run one, please [report what you see](../CONTRIBUTING.md#reporting-untested-hardware).

### Why are the PV entities unavailable?

They are created for every tank but stay unavailable unless the tank reports a PV diverter. The PV controls also exist only in Advanced mode. See [troubleshooting.md](troubleshooting.md#why-are-the-pv-entities-missing-or-unavailable).

### Will it break on new Home Assistant versions?

The test suite runs weekly against the latest Home Assistant release, so core changes tend to surface in CI before they reach users. The CI matrix runs the minimum supported Home Assistant and the current one (see `.github/workflows/tests.yaml`).

## Privacy and security

### What data leaves my network?

Your Mixergy credentials and the commands you send go to `mixergy.io` over TLS, and nothing else goes anywhere. The client checks every API link before it sends the bearer token and refuses plain HTTP or any host other than Mixergy's. There is no analytics or telemetry.

### Where are my credentials stored?

In Home Assistant's config entry storage on your machine. They are never written to logs, and the diagnostics download redacts the username, password and tank serial.

## Upgrading

### I upgraded from 1.x and the old entities stopped. What do I do?

Version 2.0.0 changed the integration domain from `mixergy` to `mixergy_tank`, so the old `custom_components/mixergy/` folder must be removed. The steps are in [installation.md](installation.md#upgrading-from-1x-to-2x).

### Why is the icon grey in HACS?

It is a known HACS limitation that affects custom integrations published since February 2026, not a fault in your install. The icon shows correctly everywhere inside Home Assistant. See [troubleshooting.md](troubleshooting.md#why-is-the-icon-missing-in-hacs).
