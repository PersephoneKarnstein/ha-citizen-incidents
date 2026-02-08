# Citizen Incidents for Home Assistant

![citizen](citizen.png)

A Home Assistant custom integration that displays live [Citizen](https://citizen.com) incident reports as geo-location entities on the HA map. Incidents are color-coded by recency and disappear automatically when they leave the Citizen feed.

Two deployment options are included:

| Option | How it works |
|---|---|
| **Native HA integration** (recommended) | Runs inside Home Assistant, creates `geo_location` entities directly, configured via the UI. |
| **Standalone GeoJSON server** | A separate Python process that serves incidents as a GeoJSON feed, consumed by HA's built-in `geo_json_events` integration. |

## Prerequisites

- Home Assistant 2024.1 or later
- [HACS](https://hacs.xyz) (optional, for easier installation)
- For the dashboard card:
  - [map-card](https://github.com/nathan-gs/ha-map-card) (custom Lovelace card)
  - [auto-entities](https://github.com/thomasloven/lovelace-auto-entities) (custom Lovelace card)
  - [card-mod](https://github.com/thomasloven/lovelace-card-mod) (optional, for the legend overlay)

All three frontend cards can be installed through HACS under **Frontend**.

## Option A: Native Integration (Recommended)

### 1. Install the custom component

Copy the `custom_components/citizen/` directory into your Home Assistant config directory:

```
<ha-config>/
  custom_components/
    citizen/
      __init__.py
      config_flow.py
      const.py
      geo_location.py
      manifest.json
      strings.json
```

Then restart Home Assistant.

### 2. Add the integration

1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for **Citizen Incidents**.
3. Configure:
   - **Latitude / Longitude** -- Center point for the incident feed. Defaults to your HA home location. For Manhattan, use `40.7580` / `-73.9855`.
   - **Radius (km)** -- How far from the center to fetch incidents (0.5 -- 50 km). `5` is a good default for a city.
   - **Update interval (seconds)** -- How often to poll the Citizen API. Minimum 30, default 120.
   - **Maximum incidents** -- Cap on the number of incidents fetched per poll (1 -- 200).

Entities will appear under the `geo_location` domain with source `citizen`.

## Option B: Standalone GeoJSON Server

If you prefer not to install a custom component, you can run the GeoJSON server separately and point HA's built-in `geo_json_events` integration at it.

### 1. Run the server

```bash
pip install aiohttp
python citizen_geojson_server.py --lat 40.7580 --lon -73.9855 --radius 5 --port 8099
```

All flags are optional and default to Manhattan / 5 km / port 8099.

### 2. Add to Home Assistant

In `configuration.yaml`:

```yaml
geo_json_events:
  - url: "http://<server-ip>:8099/incidents.geojson"
    radius: 50
```

Replace `<server-ip>` with the IP or hostname of the machine running the server. If it's on the same host as HA, use `localhost` or `127.0.0.1`.

Restart Home Assistant after editing the config.

## Dashboard Card

The included `citizen-card.yaml` provides a Lovelace map card that displays incidents color-coded by age. It requires the `map-card`, `auto-entities`, and `card-mod` frontend components listed in Prerequisites.

### Adding the card to a dashboard

1. Open a Lovelace dashboard in edit mode.
2. Click **Add Card > Manual** (the YAML editor).
3. Paste the contents of `citizen-card.yaml`.
4. Save.

### Configuring the map center and zoom

The card's map position is controlled by these fields in the `card:` section:

```yaml
card:
  type: custom:map-card
  zoom: 16
  x: 40.7580      # latitude of the map center
  y: -73.9855     # longitude of the map center
```

- **`x`** -- Latitude of the map center (north/south).
- **`y`** -- Longitude of the map center (east/west).
- **`zoom`** -- OpenStreetMap zoom level. `16` is street-level (~500 m visible). Lower numbers zoom out (`13` shows a borough, `11` shows a metro area).

Set `x` and `y` to match the latitude/longitude you configured in the integration. For example, for Midtown Manhattan:

```yaml
  x: 40.7580
  y: -73.9855
```

### Recency tiers

Incidents are displayed with different colors and icon sizes based on age:

| Color | Age | Tier |
|---|---|---|
| Purple | < 30 min | critical |
| Red | 30 min -- 2 hr | recent |
| Orange | 2 -- 12 hr | moderate |
| Yellow | 12 hr -- 2 days | aging |
| Gray | 2+ days | old |

These are defined in `const.py` (`RECENCY_TIERS`) and matched by the `auto-entities` filter in the card YAML.

## Entity Attributes

Each incident entity exposes the following attributes:

| Attribute | Description |
|---|---|
| `incident_key` | Citizen's unique incident identifier |
| `address` | Street address |
| `neighborhood` | Neighborhood name |
| `severity` | Citizen severity level |
| `categories` | Incident categories |
| `summary` | Citizen's narrative summary |
| `updates` | Chronological list of timestamped update strings |
| `has_video` | Whether the incident has associated video |
| `created` | ISO 8601 creation timestamp |
| `updated` | ISO 8601 last-update timestamp |
| `external_url` | Link to the incident on citizen.com |
| `age_minutes` | Age of the incident in minutes |
| `recency_tier` | One of: `critical`, `recent`, `moderate`, `aging`, `old` |
| `recency_color` | RGBA color string for map rendering |

## Notes

- The Citizen API is unofficial and unauthenticated. It may change without notice.
- Entities are ephemeral: they are created when incidents appear in the feed and automatically removed when they drop out.
- The integration polls on a timer. It does not receive push notifications.
- The standalone GeoJSON server caches responses and only re-fetches from Citizen after the configured interval elapses.
