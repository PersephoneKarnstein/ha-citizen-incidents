#!/usr/bin/env python3
"""
Standalone GeoJSON server for Citizen incidents.

Fetches incidents from the Citizen API and serves them as a GeoJSON
FeatureCollection. Can be consumed by Home Assistant's built-in
`geo_json_events` integration or any GeoJSON-compatible tool.

Usage:
    python citizen_geojson_server.py [--lat 40.7128] [--lon -74.0060] \
        [--radius 5] [--port 8099] [--limit 50] [--interval 120]

Then add to Home Assistant configuration.yaml:
    geo_json_events:
      - url: "http://localhost:8099/incidents.geojson"
        radius: 50
"""

import argparse
import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
_LOGGER = logging.getLogger("citizen_geojson")

EARTH_RADIUS_KM = 6371.0

API_BASE_URL = "https://citizen.com/api/incident/trending"
API_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def bounding_box(lat: float, lon: float, radius_km: float) -> dict:
    """Calculate bounding box from center and radius."""
    lat_rad = math.radians(lat)
    delta_lat = radius_km / EARTH_RADIUS_KM
    cos_lat = math.cos(lat_rad)
    if abs(cos_lat) < 1e-10:
        delta_lon = math.pi
    else:
        delta_lon = radius_km / (EARTH_RADIUS_KM * cos_lat)
    return {
        "lowerLatitude": lat - math.degrees(delta_lat),
        "lowerLongitude": lon - math.degrees(delta_lon),
        "upperLatitude": lat + math.degrees(delta_lat),
        "upperLongitude": lon + math.degrees(delta_lon),
    }


def _safe_timestamp(ms) -> datetime | None:
    """Convert a millisecond Unix timestamp to a datetime, or None on failure."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OSError, ValueError, OverflowError, TypeError):
        return None


def incident_to_feature(incident: dict) -> dict | None:
    """Convert a single Citizen incident to a GeoJSON Feature."""
    try:
        lat = float(incident.get("latitude"))
        lon = float(incident.get("longitude"))
    except (TypeError, ValueError):
        return None

    key = incident.get("key", "unknown")
    title = incident.get("title", "Unknown Incident")

    # Collect update texts
    updates = []
    raw_updates = incident.get("updates")
    if raw_updates:
        if isinstance(raw_updates, dict):
            items = raw_updates.values()
        elif isinstance(raw_updates, list):
            items = raw_updates
        else:
            items = []
        for upd in sorted(
            (u for u in items if isinstance(u, dict)),
            key=lambda u: u.get("ts", 0),
        ):
            text = upd.get("text", "")
            dt = _safe_timestamp(upd.get("ts"))
            if dt is not None:
                text = f"[{dt.strftime('%H:%M')}] {text}"
            updates.append(text)

    # Summary
    summary = ""
    if nib := incident.get("nib"):
        if isinstance(nib, dict):
            summary = nib.get("text", "")

    # Timestamps
    created = ""
    updated = ""
    created_dt = _safe_timestamp(incident.get("cs"))
    if created_dt is not None:
        created = created_dt.isoformat()
    updated_dt = _safe_timestamp(incident.get("ts"))
    if updated_dt is not None:
        updated = updated_dt.isoformat()

    properties = {
        "id": key,
        "title": title,
        "address": incident.get("address", ""),
        "location": incident.get("location", ""),
        "neighborhood": incident.get("neighborhood", ""),
        "city_code": incident.get("cityCode", ""),
        "severity": incident.get("severity", ""),
        "categories": incident.get("categories", []),
        "source": incident.get("source", ""),
        "has_video": incident.get("hasVod", False),
        "summary": summary,
        "updates": updates,
        "created": created,
        "updated": updated,
        "external_url": f"https://citizen.com/incident/{key}",
        "attribution": "Data provided by Citizen (citizen.com)",
    }

    # Add image if available
    if ps := incident.get("preferredStream"):
        if img := ps.get("image"):
            properties["image_url"] = img

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon, lat],
        },
        "properties": properties,
    }


class CitizenGeoJSONServer:
    """Fetches Citizen data and serves as GeoJSON."""

    def __init__(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        limit: int,
        interval: int,
    ):
        self.lat = lat
        self.lon = lon
        self.radius_km = radius_km
        self.limit = limit
        self.interval = interval
        self._geojson: dict = {"type": "FeatureCollection", "features": []}
        self._last_fetch: float = 0
        self._session: aiohttp.ClientSession | None = None

    async def start(self):
        """Create the HTTP session."""
        self._session = aiohttp.ClientSession()

    async def stop(self):
        """Close the HTTP session."""
        if self._session:
            await self._session.close()

    async def fetch_incidents(self) -> list[dict]:
        """Fetch incidents from the Citizen API."""
        if not self._session:
            _LOGGER.error("HTTP session not initialized; call start() first")
            return []

        bbox = bounding_box(self.lat, self.lon, self.radius_km)
        params = {
            **bbox,
            "fullResponse": "true",
            "limit": str(self.limit),
        }
        headers = {
            "Accept": "*/*",
            "Referer": "https://citizen.com/explore",
            "User-Agent": API_USER_AGENT,
        }

        async with self._session.get(
            API_BASE_URL,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        if not isinstance(data, dict):
            _LOGGER.warning("Unexpected API response type: %s", type(data).__name__)
            return []
        results = data.get("results", [])
        if not isinstance(results, list):
            _LOGGER.warning("Unexpected 'results' type: %s", type(results).__name__)
            return []
        return results

    async def refresh(self):
        """Refresh the cached GeoJSON if the interval has elapsed."""
        now = time.monotonic()
        if now - self._last_fetch < self.interval:
            return

        try:
            incidents = await self.fetch_incidents()
            features = []
            for inc in incidents:
                feature = incident_to_feature(inc)
                if feature:
                    features.append(feature)

            self._geojson = {
                "type": "FeatureCollection",
                "features": features,
            }
            self._last_fetch = now
            _LOGGER.info("Fetched %d incidents (%d features)", len(incidents), len(features))
        except Exception:
            _LOGGER.exception("Failed to fetch Citizen incidents")

    async def handle_geojson(self, request: web.Request) -> web.Response:
        """Handle GET /incidents.geojson."""
        await self.refresh()
        return web.json_response(
            self._geojson,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health."""
        return web.json_response({
            "status": "ok",
            "features": len(self._geojson.get("features", [])),
            "center": [self.lat, self.lon],
            "radius_km": self.radius_km,
        })


async def main():
    parser = argparse.ArgumentParser(
        description="Serve Citizen incidents as GeoJSON"
    )
    parser.add_argument("--lat", type=float, default=40.7128, help="Center latitude (default: NYC)")
    parser.add_argument("--lon", type=float, default=-74.0060, help="Center longitude (default: NYC)")
    parser.add_argument("--radius", type=float, default=5.0, help="Radius in km (default: 5)")
    parser.add_argument("--port", type=int, default=8099, help="HTTP port (default: 8099)")
    parser.add_argument("--limit", type=int, default=50, help="Max incidents (default: 50)")
    parser.add_argument("--interval", type=int, default=120, help="Refresh interval in seconds (default: 120)")
    args = parser.parse_args()

    server = CitizenGeoJSONServer(
        lat=args.lat,
        lon=args.lon,
        radius_km=args.radius,
        limit=args.limit,
        interval=args.interval,
    )
    await server.start()

    app = web.Application()
    app.router.add_get("/incidents.geojson", server.handle_geojson)
    app.router.add_get("/health", server.handle_health)

    async def _cleanup(_app):
        await server.stop()

    app.on_cleanup.append(_cleanup)

    _LOGGER.info(
        "Starting Citizen GeoJSON server on port %d (center: %f, %f, radius: %f km)",
        args.port, args.lat, args.lon, args.radius,
    )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", args.port)
    await site.start()

    _LOGGER.info("Serving at http://0.0.0.0:%d/incidents.geojson", args.port)

    # Run forever
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
