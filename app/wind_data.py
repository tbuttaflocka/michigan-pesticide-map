"""Reference data + helpers for the wind / pesticide-drift overlay.

* MI_ASOS_STATIONS — the Michigan ASOS/AWOS weather stations (airports) whose
  hourly wind observations we pull from the Iowa Environmental Mesonet (IEM).
  lat/lon here are approximate fallbacks; the loader overwrites them with the
  precise coordinates IEM returns alongside each observation.
* Direction helpers convert between compass degrees and 16-point labels.
* Drift geometry projects a downwind fan (near / mid / far bands) from a county
  centroid, used by /api/wind/drift-zone. This is a deliberately simple model —
  see DRIFT_DISCLAIMER.
"""
from __future__ import annotations

import math

# 16-point compass, clockwise from North.
DIRS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def deg_to_dir16(deg: float) -> str:
    """Compass degrees -> nearest 16-point label."""
    return DIRS_16[int((float(deg) % 360) / 22.5 + 0.5) % 16]


def dir16_to_deg(label: str) -> float:
    """16-point label -> its center in degrees."""
    return DIRS_16.index(label) * 22.5


def opposite_deg(deg: float) -> float:
    """Downwind bearing = 180° from the meteorological FROM direction."""
    return (float(deg) + 180.0) % 360.0


# Key Michigan ASOS stations (IEM ids are the 4-char ICAO, e.g. "KLAN").
# county_fips is the station's home county (used only for reference / display).
MI_ASOS_STATIONS = [
    {"id": "KDTW", "name": "Detroit Metro",        "county": "Wayne",          "county_fips": "26163", "lat": 42.231, "lon": -83.331},
    {"id": "KGRR", "name": "Grand Rapids",         "county": "Kent",           "county_fips": "26081", "lat": 42.881, "lon": -85.523},
    {"id": "KLAN", "name": "Lansing",              "county": "Ingham",         "county_fips": "26065", "lat": 42.779, "lon": -84.579},
    {"id": "KFNT", "name": "Flint",                "county": "Genesee",        "county_fips": "26049", "lat": 42.966, "lon": -83.749},
    {"id": "KMKG", "name": "Muskegon",             "county": "Muskegon",       "county_fips": "26121", "lat": 43.169, "lon": -86.238},
    {"id": "KBTL", "name": "Battle Creek",         "county": "Calhoun",        "county_fips": "26025", "lat": 42.307, "lon": -85.251},
    {"id": "KJXN", "name": "Jackson",              "county": "Jackson",        "county_fips": "26075", "lat": 42.260, "lon": -84.459},
    {"id": "KMBS", "name": "Saginaw / MBS",        "county": "Saginaw",        "county_fips": "26145", "lat": 43.533, "lon": -84.080},
    {"id": "KTVC", "name": "Traverse City",        "county": "Grand Traverse", "county_fips": "26055", "lat": 44.741, "lon": -85.582},
    {"id": "KAPN", "name": "Alpena",               "county": "Alpena",         "county_fips": "26007", "lat": 45.078, "lon": -83.560},
    {"id": "KCMX", "name": "Hancock / Houghton",   "county": "Houghton",       "county_fips": "26061", "lat": 47.168, "lon": -88.489},
    {"id": "KESC", "name": "Escanaba",             "county": "Delta",          "county_fips": "26041", "lat": 45.723, "lon": -87.094},
    {"id": "KIWD", "name": "Ironwood",             "county": "Gogebic",        "county_fips": "26053", "lat": 46.528, "lon": -90.131},
    {"id": "KSAW", "name": "Marquette / Sawyer",   "county": "Marquette",      "county_fips": "26103", "lat": 46.354, "lon": -87.395},
]


# ---------- geodesy (simple great-circle destination point) ----------

_EARTH_MI = 3958.8


def destination_point(lat: float, lon: float, bearing_deg: float, dist_mi: float) -> tuple[float, float]:
    """Return (lat, lon) reached by travelling dist_mi along bearing_deg."""
    ang = dist_mi / _EARTH_MI
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(ang) +
                     math.cos(lat1) * math.sin(ang) * math.cos(br))
    lon2 = lon1 + math.atan2(math.sin(br) * math.sin(ang) * math.cos(lat1),
                             math.cos(ang) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_MI * math.asin(math.sqrt(a))


# Drift bands (miles) — near-field heavy, mid moderate, far light/trace.
DRIFT_BANDS = [
    {"key": "near", "label": "Near-field (heavy deposition)", "r0": 0.0, "r1": 0.5},
    {"key": "mid",  "label": "Mid-field (moderate)",          "r0": 0.5, "r1": 2.0},
    {"key": "far",  "label": "Far-field (light / trace)",     "r0": 2.0, "r1": 5.0},
]

# Half-angle of the fan (total spread ~60°).
DRIFT_HALF_ANGLE = 30.0


def drift_fan(lat: float, lon: float, downwind_deg: float,
              half_angle: float = DRIFT_HALF_ANGLE, steps: int = 8) -> list[dict]:
    """Build ring coordinates for each drift band as a filled arc segment
    oriented along downwind_deg. Returns a list of
    {key, label, r0, r1, ring: [[lat, lon], ...]} (ring closes on itself).
    """
    bands = []
    a0 = downwind_deg - half_angle
    a1 = downwind_deg + half_angle
    for b in DRIFT_BANDS:
        ring: list[list[float]] = []
        # outer arc (r1) sweeping a0 -> a1
        for i in range(steps + 1):
            ang = a0 + (a1 - a0) * i / steps
            la, lo = destination_point(lat, lon, ang, b["r1"])
            ring.append([la, lo])
        # inner arc (r0) sweeping back a1 -> a0
        for i in range(steps + 1):
            ang = a1 - (a1 - a0) * i / steps
            if b["r0"] <= 0:
                ring.append([lat, lon])
            else:
                la, lo = destination_point(lat, lon, ang, b["r0"])
                ring.append([la, lo])
        ring.append(ring[0])
        bands.append({"key": b["key"], "label": b["label"],
                      "r0": b["r0"], "r1": b["r1"], "ring": ring})
    return bands


DRIFT_DISCLAIMER = (
    "Simplified illustrative model. Actual spray drift depends on droplet size, "
    "nozzle and application method, boom height, temperature inversions, humidity, "
    "canopy, and gust structure — not just the growing-season average wind. "
    "Bands (0–0.5 / 0.5–2 / 2–5 mi) are indicative, not regulatory buffers."
)
