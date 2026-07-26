"""
Metadata, classification, and PUBLISHED-SOURCE content for the "Golf courses"
overlay.

Why this layer exists
---------------------
Golf courses are one of the most pesticide-intensive land uses in Michigan, yet
they are a complete blind spot in this app's other data: the USGS EPest layer
estimates AGRICULTURAL pesticide use only, so golf courses, lawns, parks, and
roadsides are absent from every county total. This layer maps WHERE intensive
turf pesticide use happens and explains WHY no one can tell you how much.

The hard rule: we never show or estimate per-course pesticide amounts.
--------------------------------------------------------------------------
Michigan has no golf-course-specific public pesticide-use reporting; private
courses generally aren't required to disclose application logs; and the
industry's trade association does not publish U.S. course pesticide records. So
this module carries only:
  * WHAT is *typically* applied to golf turf generally (a sourced list of
    classes + common active ingredients from turfgrass-management references) —
    explicitly NOT a record of what any specific course applies; and
  * a cited intensity COMPARISON (a regional study), presented as the cited
    finding it is, never as a Michigan measurement.
No amount is ever attributed to a mapped course. See TURF_CHEMICALS / INTENSITY.
"""
from __future__ import annotations

import json
import re
from math import radians, sin, cos, asin, sqrt


# ---- ownership classification -------------------------------------------------
#
# Public vs private matters because RECORDS ACCESS differs: a municipally- or
# otherwise publicly-owned course is a public body subject to Michigan FOIA
# (records obtainable via the city/county clerk or the owning agency), while a
# privately-owned course generally is not required to disclose its pesticide
# logs. NOTE: play access (members-only vs daily-fee "public") is NOT ownership —
# most daily-fee "public" courses are privately owned — so we only infer PUBLIC
# ownership from explicit ownership/owner/operator signals, never from a course
# being open to the public.

OWNERSHIP_META = {
    # class -> (glyph, color, short legend label)
    "municipal": ("⛳", "#3fb950", "Publicly / municipally owned"),   # ⛳ green
    "private":   ("⛳", "#d98c3f", "Private course"),                 # ⛳ amber
    "unknown":   ("⛳", "#8b98a5", "Ownership not indicated"),        # ⛳ grey
}

# Owner/operator/ownership FIELDS explicitly name who owns/runs a course, so a
# broad keyword list is safe there — "University of Michigan" or "City of Ann
# Arbor" is unambiguous.
_OWNER_KW = (
    "city of", "township", " twp", "village of", "county of", "county parks",
    "state of", "michigan dnr", " dnr", "metropark", "parks and recreation",
    "parks & recreation", "recreation department", "recreation authority",
    "university", "college", "community college", "municipal", "authority",
)
# NAME matching is far riskier — "College Fields Golf Club" is a private club, not
# a college course. So against the NAME we accept only tokens that are essentially
# never a misleading part of a private course's name.
_NAME_PUBLIC_RE = re.compile(
    r"\b(municipal|metroparks?|county park|state park|township park)\b", re.I)


def classify_ownership(tags: dict) -> tuple[str, str]:
    """Map OSM tags to (ownership_class, plain-language label).

    Precision-first: we only call a course PUBLIC when OSM explicitly says so
    (ownership tag), names a governmental / public-institution owner/operator, or
    carries an unambiguous public token in its NAME. Everything else is 'private'
    only on an explicit private signal, otherwise 'unknown' — we never guess a
    course into the public bucket, because the records-request guidance hinges on
    it (a wrong 'public' label would wrongly imply the logs are FOIA-able)."""
    ownership = (tags.get("ownership") or "").strip().lower()
    optype = (tags.get("operator:type") or "").strip().lower()
    access = (tags.get("access") or "").strip().lower()
    owner_blob = " ".join(
        (tags.get(k) or "") for k in ("owner", "operator")).lower()

    is_public = (
        ownership in ("municipal", "public", "government", "state", "county", "city")
        or optype in ("government", "public", "municipal")
        or any(kw in owner_blob for kw in _OWNER_KW)
        or bool(_NAME_PUBLIC_RE.search(tags.get("name") or ""))
    )
    if is_public:
        return "municipal", (
            "Publicly / municipally owned — as a public body its pesticide "
            "records may be obtainable by a Michigan public-records (FOIA) "
            "request to the owning government (e.g. the city or county clerk)."
        )
    if ownership == "private" or optype == "private" or access in ("private", "members"):
        return "private", (
            "Private course — privately owned courses are generally not required "
            "to disclose pesticide-application records in Michigan."
        )
    return "unknown", (
        "Ownership is not indicated in OpenStreetMap. Records access depends on "
        "whether the course is publicly or privately owned."
    )


# ---- geometry helpers (OSM `out geom`) ---------------------------------------

LBS_PER_KG = 2.2046226218


def _ring_lonlat(geometry: list) -> list:
    """Convert an OSM way `geometry` ([{lat,lon},...]) to [[lon,lat],...]."""
    return [[p["lon"], p["lat"]] for p in geometry
            if p.get("lon") is not None and p.get("lat") is not None]


def _close_ring(ring: list) -> list:
    if len(ring) >= 3 and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring


def _stitch_outer_rings(members: list) -> list:
    """Assemble a relation's 'outer' member ways into closed rings.

    Overpass `out geom` gives each member way its own coordinate list; multipolygon
    outers may be split across several ways that must be stitched end-to-end. We
    greedily chain ways whose endpoints meet. Robust to ordering; tolerant of
    small gaps (a way that doesn't connect just starts a new ring)."""
    segs = []
    for m in members:
        if m.get("type") != "way" or m.get("role") not in ("outer", "", None):
            continue
        if m.get("role") not in ("outer", None, ""):
            continue
        g = m.get("geometry")
        if not g:
            continue
        seg = _ring_lonlat(g)
        if len(seg) >= 2:
            segs.append(seg)
    rings, used = [], [False] * len(segs)
    for i, seg in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        ring = list(seg)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for j, other in enumerate(segs):
                if used[j]:
                    continue
                if ring[-1] == other[0]:
                    ring += other[1:]; used[j] = True; changed = True
                elif ring[-1] == other[-1]:
                    ring += list(reversed(other))[1:]; used[j] = True; changed = True
                elif ring[0] == other[-1]:
                    ring = other[:-1] + ring; used[j] = True; changed = True
                elif ring[0] == other[0]:
                    ring = list(reversed(other))[:-1] + ring; used[j] = True; changed = True
        if len(ring) >= 4:
            rings.append(_close_ring(ring))
    return rings


def _ring_area_signed_m2(ring: list) -> float:
    """Shoelace area (m^2) of a lon/lat ring via equirectangular projection at
    the ring's mean latitude. Sign encodes winding; caller takes abs()."""
    if len(ring) < 4:
        return 0.0
    lat0 = sum(p[1] for p in ring) / len(ring)
    mlat = radians(lat0)
    mx = 111320.0 * cos(mlat)      # metres per degree lon at this latitude
    my = 110540.0                  # metres per degree lat
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        s += (x1 * mx) * (y2 * my) - (x2 * mx) * (y1 * my)
    return s / 2.0


def polygon_metrics(rings: list) -> tuple[float, float, float]:
    """Return (acres, centroid_lon, centroid_lat) for a list of outer rings.

    Acreage is the summed absolute ring area converted m^2 -> acres. The centroid
    is area-weighted across rings, falling back to the vertex mean."""
    total_a = 0.0
    cx = cy = 0.0
    all_pts = []
    for ring in rings:
        a = _ring_area_signed_m2(ring)
        aa = abs(a)
        total_a += aa
        # ring centroid (planar, same projection) weighted by area
        if aa > 0:
            lat0 = sum(p[1] for p in ring) / len(ring)
            mx = 111320.0 * cos(radians(lat0)); my = 110540.0
            rx = ry = 0.0
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                cross = (x1 * mx) * (y2 * my) - (x2 * mx) * (y1 * my)
                rx += (x1 + x2) * cross
                ry += (y1 + y2) * cross
            rx /= (6 * a); ry /= (6 * a)
            cx += rx * aa; cy += ry * aa
        all_pts.extend(ring)
    if total_a > 0:
        acres = total_a / 4046.8564224
        return acres, cx / total_a, cy / total_a
    # degenerate: no area — average the points
    if all_pts:
        return 0.0, sum(p[0] for p in all_pts) / len(all_pts), \
            sum(p[1] for p in all_pts) / len(all_pts)
    return 0.0, 0.0, 0.0


def geometry_geojson(osm_type: str, element: dict) -> tuple[dict | None, list]:
    """Build a GeoJSON geometry (Polygon/MultiPolygon) + list of outer rings from
    an Overpass element. Returns (geojson_or_None, outer_rings)."""
    if osm_type == "way":
        g = element.get("geometry")
        if not g:
            return None, []
        ring = _close_ring(_ring_lonlat(g))
        if len(ring) < 4:
            return None, []
        return {"type": "Polygon", "coordinates": [ring]}, [ring]
    # relation: stitch outer ways into rings -> MultiPolygon (one polygon/ring)
    rings = _stitch_outer_rings(element.get("members", []))
    rings = [r for r in rings if len(r) >= 4]
    if not rings:
        return None, []
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}, rings
    return {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}, rings


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * 6371.0088 * asin(sqrt(a))


# ---- water cross-reference (turf-associated compounds) -----------------------
#
# Compounds registered for TURFGRASS use (fungicides, herbicides, insecticides,
# and some breakdown products) that ALSO appear in the app's water-monitoring
# data. Used only to surface *nearby* monitoring as CONTEXT — never to attribute
# a detection to a golf course. Many of these (e.g. 2,4-D) have agricultural and
# residential uses too, which is exactly why the popup states detections are not
# attributable to any specific course.
TURF_WATER_COMPOUNDS = {
    # herbicides
    "2,4-D", "DICAMBA", "MCPP", "MECOPROP", "MCPP (MECOPROP)", "TRICLOPYR",
    "DITHIOPYR", "PENDIMETHALIN", "PRODIAMINE", "QUINCLORAC",
    # fungicides
    "CHLOROTHALONIL", "PROPICONAZOLE", "TEBUCONAZOLE", "AZOXYSTROBIN",
    "MYCLOBUTANIL", "IPRODIONE", "CARBENDAZIM", "THIOPHANATE-METHYL",
    "FLUTOLANIL", "TRIADIMEFON",
    # insecticides
    "IMIDACLOPRID", "CLOTHIANIDIN", "THIAMETHOXAM", "CHLORPYRIFOS", "CARBARYL",
    "FIPRONIL", "BIFENTHRIN", "HALOFENOZIDE", "TRICHLORFON",
}


# =============================================================================
# PUBLISHED-SOURCE CONTENT — turf chemical list, intensity comparison, sources.
# Everything below is sourced from the cited references (MSU Extension turf
# program, GCSAA BMP, state golf-course BMP manuals) — NOT asserted from memory.
# It describes what is TYPICAL for turf management generally; it is NEVER a record
# of any specific course's applications. Filled from research in golf_content.py.
# =============================================================================
from .golf_content import (  # noqa: E402
    TURF_CHEMICALS, INTENSITY, DISCLOSURE, SOURCES, LAYER_CAVEAT,
)


def turf_chemicals_payload() -> list:
    """The sourced turf-management chemical list, for popups/legend."""
    return TURF_CHEMICALS


def legend_payload() -> dict:
    """Ownership legend + the shared turf-management context for the frontend."""
    return {
        "ownership": [
            {"key": k, "glyph": g, "color": c, "label": lbl}
            for k, (g, c, lbl) in OWNERSHIP_META.items()
        ],
        "turf_chemicals": TURF_CHEMICALS,
        "intensity": INTENSITY,
        "disclosure": DISCLOSURE,
        "sources": SOURCES,
        "caveat": LAYER_CAVEAT,
    }


def augment_row(row: dict) -> dict:
    """Add glyph/color/label + parsed cross-ref fields to a golf_courses row
    (a plain dict) for the API response. Non-destructive."""
    oc = row.get("ownership_class") or "unknown"
    glyph, color, oc_label = OWNERSHIP_META.get(oc, OWNERSHIP_META["unknown"])
    row["glyph"] = glyph
    row["color"] = color
    row["ownership_legend"] = oc_label
    # water_compounds stored as a JSON string in the DB
    wc = row.get("water_compounds")
    if isinstance(wc, str):
        try:
            row["water_compounds"] = json.loads(wc) if wc else []
        except (TypeError, ValueError):
            row["water_compounds"] = []
    elif wc is None:
        row["water_compounds"] = []
    return row
