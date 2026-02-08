"""Constants for the Citizen integration."""

DOMAIN = "citizen"

CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_KM = "radius_km"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_INCIDENTS = "max_incidents"

DEFAULT_RADIUS_KM = 5.0
DEFAULT_SCAN_INTERVAL = 120  # seconds
DEFAULT_MAX_INCIDENTS = 50

API_BASE_URL = "https://citizen.com/api/incident/trending"
API_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ATTR_INCIDENT_KEY = "incident_key"
ATTR_TITLE = "title"
ATTR_ADDRESS = "address"
ATTR_NEIGHBORHOOD = "neighborhood"
ATTR_CITY_CODE = "city_code"
ATTR_SEVERITY = "severity"
ATTR_CATEGORIES = "categories"
ATTR_UPDATES = "updates"
ATTR_NIB = "summary"
ATTR_SOURCE = "incident_source"
ATTR_HAS_VIDEO = "has_video"
ATTR_CREATED = "created"
ATTR_UPDATED = "updated"
ATTR_EXTERNAL_URL = "external_url"
ATTR_AGE_MINUTES = "age_minutes"
ATTR_RECENCY_RADIUS = "recency_radius"
ATTR_RECENCY_COLOR = "recency_color"
ATTR_RECENCY_OPACITY = "recency_opacity"
ATTR_RECENCY_TIER = "recency_tier"

# Recency tiers: (max_age_minutes, icon, radius_meters, color, fill_opacity, tier_name)
# Radii sized for zoom 16 (street-level, ~500m visible)
RECENCY_TIERS = [
    (30, "mdi:alert-circle", 80, "rgba(160,0,255,0.9)", 0.30, "critical"),      # < 30 min — purple
    (120, "mdi:alert-circle", 55, "rgba(255,0,0,0.85)", 0.22, "recent"),       # 30 min - 2 hr — red
    (720, "mdi:alert-circle", 35, "rgba(255,120,0,0.7)", 0.15, "moderate"),    # 2 hr - 12 hr — orange
    (2880, "mdi:alert-circle", 25, "rgba(255,200,0,0.6)", 0.10, "aging"),      # 12 hr - 2 days — yellow
    (float("inf"), "mdi:alert-circle", 15, "rgba(140,140,140,0.5)", 0.08, "old"),  # 2+ days — gray
]
