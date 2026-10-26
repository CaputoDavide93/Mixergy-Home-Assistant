# ⚙️ How it works

What the integration does between your Home Assistant and Mixergy's cloud, in plain terms. The developer-level reference, including the standalone Python client, is in [api.md](api.md).

## The path of a reading

The tank reports to Mixergy's cloud. The integration never talks to the tank. One coordinator per tank asks the cloud for fresh data on a timer (60 seconds by default, 30 to 300 allowed) and hands the result to every entity of that tank.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <img src="assets/architecture-light.svg" width="100%"
       alt="The Mixergy tank reports to the Mixergy cloud; the integration's coordinator polls the cloud API over HTTPS and feeds the Home Assistant entities and the Energy Dashboard, while services and controls write back to the cloud.">
</picture>

Each poll makes three requests at once: the latest measurement, the tank's settings and its schedule. The measurement is the part that matters most. If settings or schedule fail on one poll, the integration keeps the last good copy of them and still updates charge and temperatures, so one slow endpoint does not turn every entity unavailable. If the measurement itself fails, entities go unavailable until the next good poll.

## Finding the tank

The client knows only the API root. It signs in, follows the links in each response to find the tanks, measurement, settings and schedule endpoints, and remembers them. Before it sends your token to any link it was given, it checks the link is HTTPS and on Mixergy's own host, and refuses otherwise. Tokens are renewed five minutes before they expire. If Mixergy rejects your credentials, Home Assistant starts its normal re-authentication prompt.

## What a write does

Controls and services send a `PUT` to the cloud and then ask the coordinator to refresh at once, so a change shows up without waiting for the next poll. Changes to the holiday dates or the default heat source read the schedule, change one field and send the whole document back, under a lock, so two near-simultaneous changes cannot overwrite each other.

## Fresh, stale and offline

A successful request does not prove the tank is talking. The cloud can serve an old measurement, so the integration also looks at the time the tank last reported. The `Tank connectivity` binary sensor is on while that report is recent (within five minutes, or three poll intervals if that is longer), and the `Last tank measurement` sensor shows the time itself.

## How energy is counted

The tank reports power, not energy. The **Electric heat energy** sensor adds up power times the time since the previous poll and never goes down, so it works as a Home Assistant total for the Energy dashboard. Only finite, positive readings add anything. The reading used for electric power is named in the sensor's `source` attribute. The full rules and their limits are in [energy.md](energy.md#-how-does-the-integration-compute-energy).

## What it does not do

- It does not control the tank locally, and it does not work without internet.
- It does not send anything anywhere except `mixergy.io`.
- It does not change settings on its own. Every write comes from you, an automation or a service call.
