"""Geo-location platform for Citizen incidents."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

import aiohttp

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL,
    CONF_MAX_INCIDENTS,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_MAX_INCIDENTS,
    API_BASE_URL,
    API_USER_AGENT,
    ATTR_INCIDENT_KEY,
    ATTR_TITLE,
    ATTR_ADDRESS,
    ATTR_NEIGHBORHOOD,
    ATTR_CITY_CODE,
    ATTR_SEVERITY,
    ATTR_CATEGORIES,
    ATTR_UPDATES,
    ATTR_NIB,
    ATTR_SOURCE,
    ATTR_HAS_VIDEO,
    ATTR_CREATED,
    ATTR_UPDATED,
    ATTR_EXTERNAL_URL,
    ATTR_AGE_MINUTES,
    ATTR_RECENCY_RADIUS,
    ATTR_RECENCY_COLOR,
    ATTR_RECENCY_OPACITY,
    ATTR_RECENCY_TIER,
    RECENCY_TIERS,
)

_LOGGER = logging.getLogger(__name__)

# Earth radius in km for bounding box calculation
EARTH_RADIUS_KM = 6371.0


def _bounding_box(lat: float, lon: float, radius_km: float) -> dict:
    """Calculate bounding box coordinates from center point and radius."""
    lat_rad = math.radians(lat)
    delta_lat = radius_km / EARTH_RADIUS_KM
    cos_lat = math.cos(lat_rad)
    if abs(cos_lat) < 1e-10:
        # At the poles, longitude is meaningless; span the full range
        delta_lon = math.pi
    else:
        delta_lon = radius_km / (EARTH_RADIUS_KM * cos_lat)

    return {
        "lowerLatitude": lat - math.degrees(delta_lat),
        "lowerLongitude": lon - math.degrees(delta_lon),
        "upperLatitude": lat + math.degrees(delta_lat),
        "upperLongitude": lon + math.degrees(delta_lon),
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    # Clamp to 1.0 to avoid domain error from floating-point rounding
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(a, 1.0)))


def _safe_timestamp(ms: int | float | None) -> datetime | None:
    """Convert a millisecond Unix timestamp to a datetime, or None on failure."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OSError, ValueError, OverflowError, TypeError):
        return None


def _safe_float(value) -> float | None:
    """Coerce a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Citizen geo-location platform."""
    # Purge stale entity registry entries from previous runs. All entities
    # are ephemeral and rebuilt from the API, so a clean slate is correct.
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        ent_reg.async_remove(reg_entry.entity_id)

    config = hass.data[DOMAIN][entry.entry_id]

    center_lat = config[CONF_LATITUDE]
    center_lon = config[CONF_LONGITUDE]
    radius_km = config.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
    scan_interval = config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    max_incidents = config.get(CONF_MAX_INCIDENTS, DEFAULT_MAX_INCIDENTS)

    manager = CitizenFeedManager(
        hass,
        async_add_entities,
        center_lat,
        center_lon,
        radius_km,
        max_incidents,
        entry.entry_id,
    )

    # Do initial fetch
    await manager.async_update()

    # Schedule periodic updates
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            manager.async_update,
            timedelta(seconds=scan_interval),
        )
    )


class CitizenFeedManager:
    """Manage fetching Citizen incidents and creating/removing entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddEntitiesCallback,
        center_lat: float,
        center_lon: float,
        radius_km: float,
        max_incidents: int,
        entry_id: str,
    ) -> None:
        """Initialize the feed manager."""
        self.hass = hass
        self.async_add_entities = async_add_entities
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.radius_km = radius_km
        self.max_incidents = max_incidents
        self.entry_id = entry_id
        self._tracked: dict[str, CitizenIncidentEvent] = {}

    async def async_update(self, _now=None) -> None:
        """Fetch incidents from Citizen API and update entities."""
        try:
            incidents = await self._fetch_incidents()
        except Exception:
            _LOGGER.exception("Error fetching Citizen incidents")
            return

        current_keys = set()
        new_entities = []

        for incident in incidents:
            key = incident.get("key")
            if not key:
                continue
            current_keys.add(key)

            if key in self._tracked:
                # Update existing entity
                self._tracked[key].update_from_data(incident)
            else:
                # Create new entity
                entity = CitizenIncidentEvent(
                    self.center_lat,
                    self.center_lon,
                    incident,
                    self.entry_id,
                )
                self._tracked[key] = entity
                new_entities.append(entity)

        if new_entities:
            self.async_add_entities(new_entities, True)

        # Remove stale entities
        stale_keys = set(self._tracked) - current_keys
        for key in stale_keys:
            entity = self._tracked.pop(key)
            entity.async_remove_self()

    async def _fetch_incidents(self) -> list[dict]:
        """Fetch trending incidents from the Citizen API."""
        session = async_get_clientsession(self.hass)
        bbox = _bounding_box(self.center_lat, self.center_lon, self.radius_km)

        params = {
            **bbox,
            "fullResponse": "true",
            "limit": str(self.max_incidents),
        }
        headers = {
            "Accept": "*/*",
            "Referer": "https://citizen.com/explore",
            "User-Agent": API_USER_AGENT,
        }

        async with session.get(
            API_BASE_URL, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
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


class CitizenIncidentEvent(GeolocationEvent):
    """Represent a single Citizen incident as a geo-location entity."""

    _attr_should_poll = False
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_attribution = "Data provided by Citizen (citizen.com)"

    def __init__(
        self,
        center_lat: float,
        center_lon: float,
        data: dict,
        entry_id: str,
    ) -> None:
        """Initialize the incident entity."""
        self._center_lat = center_lat
        self._center_lon = center_lon
        self._entry_id = entry_id
        self._incident_key: str = data["key"]
        self._data: dict = {}
        self._removed = False
        self.update_from_data(data)

    @property
    def unique_id(self) -> str:
        """Return a unique ID for this entity."""
        return f"citizen_{self._entry_id}_{self._incident_key}"

    @property
    def source(self) -> str:
        """Return source of this event."""
        return DOMAIN

    @staticmethod
    def _format_age(minutes: float) -> str:
        """Format age in minutes to a human-readable string."""
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{int(minutes)}m ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h ago"
        days = hours / 24
        return f"{int(days)}d ago"

    @property
    def name(self) -> str | None:
        """Return the name / title of the incident with time-ago suffix."""
        title = self._data.get("title")
        if not title:
            return None
        age = self._age_minutes()
        if age != float("inf"):
            return f"{title} · {self._format_age(age)}"
        return title

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        return _safe_float(self._data.get("latitude"))

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        return _safe_float(self._data.get("longitude"))

    @property
    def distance(self) -> float | None:
        """Return distance from the configured center point in km."""
        lat = self.latitude
        lon = self.longitude
        if lat is not None and lon is not None:
            return round(
                _haversine_km(self._center_lat, self._center_lon, lat, lon), 2
            )
        return None

    def _age_minutes(self) -> float:
        """Return the age of the incident in minutes based on last update."""
        ts = self._data.get("ts") or self._data.get("cs")
        incident_time = _safe_timestamp(ts)
        if incident_time is None:
            return float("inf")
        now = datetime.now(tz=timezone.utc)
        return max(0, (now - incident_time).total_seconds() / 60)

    def _recency_tier(self) -> tuple:
        """Return the recency tier for this incident."""
        age = self._age_minutes()
        for tier in RECENCY_TIERS:
            if age <= tier[0]:
                return tier
        return RECENCY_TIERS[-1]

    @property
    def icon(self) -> str:
        """Return the icon based on recency."""
        return self._recency_tier()[1]

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        attrs = {
            ATTR_INCIDENT_KEY: self._incident_key,
        }

        if addr := self._data.get("address"):
            attrs[ATTR_ADDRESS] = addr
        if neighborhood := self._data.get("neighborhood"):
            attrs[ATTR_NEIGHBORHOOD] = neighborhood
        if city_code := self._data.get("cityCode"):
            attrs[ATTR_CITY_CODE] = city_code
        if severity := self._data.get("severity"):
            attrs[ATTR_SEVERITY] = severity
        if categories := self._data.get("categories"):
            attrs[ATTR_CATEGORIES] = categories
        if source := self._data.get("source"):
            attrs[ATTR_SOURCE] = source

        attrs[ATTR_HAS_VIDEO] = self._data.get("hasVod", False)

        # Citizen summary blurb
        if nib := self._data.get("nib"):
            if isinstance(nib, dict) and "text" in nib:
                attrs[ATTR_NIB] = nib["text"]

        # Flatten updates into a list of timestamped strings
        if raw_updates := self._data.get("updates"):
            try:
                if isinstance(raw_updates, dict):
                    items = raw_updates.values()
                elif isinstance(raw_updates, list):
                    items = raw_updates
                else:
                    items = []
                update_list = []
                for upd in sorted(
                    (u for u in items if isinstance(u, dict)),
                    key=lambda u: u.get("ts", 0),
                ):
                    text = upd.get("text", "")
                    dt = _safe_timestamp(upd.get("ts"))
                    if dt is not None:
                        text = f"[{dt.isoformat()}] {text}"
                    update_list.append(text)
                attrs[ATTR_UPDATES] = update_list
            except (TypeError, AttributeError):
                _LOGGER.debug("Skipping malformed updates for %s", self._incident_key)

        # Timestamps
        if (created_dt := _safe_timestamp(self._data.get("cs"))) is not None:
            attrs[ATTR_CREATED] = created_dt.isoformat()
        if (updated_dt := _safe_timestamp(self._data.get("ts"))) is not None:
            attrs[ATTR_UPDATED] = updated_dt.isoformat()

        attrs[ATTR_EXTERNAL_URL] = (
            f"https://citizen.com/incident/{self._incident_key}"
        )

        # Recency attributes for map card circle scaling
        age = self._age_minutes()
        tier = self._recency_tier()
        attrs[ATTR_AGE_MINUTES] = round(age, 1)
        attrs[ATTR_RECENCY_RADIUS] = tier[2]
        attrs[ATTR_RECENCY_COLOR] = tier[3]
        attrs[ATTR_RECENCY_OPACITY] = tier[4]
        attrs[ATTR_RECENCY_TIER] = tier[5]

        return attrs

    @callback
    def update_from_data(self, data: dict) -> None:
        """Update entity from new API data."""
        self._data = data
        if self.hass:
            self.async_write_ha_state()

    @callback
    def async_remove_self(self) -> None:
        """Remove this entity when the incident is no longer in the feed."""
        if not self._removed:
            self._removed = True
            if self.hass and self.entity_id:
                ent_reg = er.async_get(self.hass)
                if ent_reg.async_get(self.entity_id):
                    ent_reg.async_remove(self.entity_id)
                else:
                    self.hass.async_create_task(self.async_remove())
            elif self.hass:
                self.hass.async_create_task(self.async_remove())
