"""
Metadata, styling, parsing, and context for the dedicated PFAS layer (Michigan
PFAS Action Response Team / EGLE).

Michigan runs the most aggressive state PFAS program in the country. This layer
maps five live MPART feeds as one `pfas_features` table discriminated by `kind`:

  site           — a confirmed PFAS site (source identified/being addressed)
  aoi            — an Area of Interest: an area under investigation where the
                   source has NOT been determined. This distinction matters and
                   is made visually obvious.
  surface_water  — EGLE Water Resources surface-water PFAS samples (ppt)
  pws            — Public Water Supply sampling, published as HEXBINS (not precise
                   locations) by EGLE's design to protect critical infrastructure
  fish           — Fish Contaminant Monitoring sampling sites (PFOS in fish)
  potw           — Publicly Owned Treatment Works that tested for PFAS

HONESTY: no site or concentration is ever fabricated. Absence of a PFAS site does
not mean absence of PFAS — investigation is ongoing and the list grows. Public
water results are shown as general hexbin areas, never pinpointed.
"""
from __future__ import annotations

import json

from . import landfill_data   # reuse precision-first name-token matching
from .config import MDHHS_EAT_SAFE_FISH_URL

# kind -> (glyph, color, legend label). Confirmed Sites read as solid red hazard
# markers; Areas of Interest are amber diamonds so "under investigation" is
# obvious at a glance.
KIND_META = {
    "site":          ("⚠", "#e5484d", "Confirmed PFAS site"),
    "aoi":           ("◈", "#e8873c", "Area of Interest (under investigation)"),
    "surface_water": ("💧", "#3b82c4", "Surface-water sampling"),
    "pws":           ("⬡", "#8957e5", "Public water supply (hexbin area)"),
    "fish":          ("🐟", "#2fa39a", "Fish sampling"),
    "potw":          ("🏭", "#b0863c", "Treatment plant (POTW)"),
}

# EPA has enforceable drinking-water limits (MCLs, 2024) of 4 ppt for PFOA and
# PFOS. We use these only to add plain-language context to a measured value — we
# never invent a value. (Surface water and fish are not drinking water, so we
# frame those as "detected", not as MCL exceedances.)
EPA_MCL_PPT = {"PFOA": 4.0, "PFOS": 4.0}


def parse_ppt(val):
    """Parse an EGLE analyte value into (value_ppt, detected).

    Values arrive as numbers (detected) or non-detect qualifiers like '<2'
    (below the reporting limit). Returns (float|None, bool)."""
    if val is None:
        return None, False
    s = str(val).strip()
    if not s or s.upper() in ("ND", "U", "NA", "N/A"):
        return None, False
    if s[0] in "<":                    # '<2' = non-detect below RL
        return None, False
    try:
        return float(s), True
    except ValueError:
        return None, False


def epoch_to_iso(ms):
    """ArcGIS epoch-millis -> 'YYYY-MM-DD' (dependency-free, UTC)."""
    if ms is None:
        return None
    try:
        import datetime
        return datetime.datetime.fromtimestamp(
            int(ms) / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def title_county(name):
    """'Kent County' / 'kent' -> 'Kent'."""
    if not name:
        return None
    s = str(name).strip()
    if s.lower().endswith(" county"):
        s = s[:-7]
    return s.title() or None


MDHHS_FISH_URL = MDHHS_EAT_SAFE_FISH_URL


# Coordinate precision for the hexbin geometry sent to the browser. EGLE's raw
# rings carry ~14 decimal places (sub-micron) — absurd overkill for hexagons a
# few km across. 5 decimals is ~1.1 m at Michigan's latitude, far finer than the
# hexbins need, and it roughly halves the geometry payload before gzip.
GEOM_COORD_DIGITS = 5


def round_coords(coords, ndigits: int = GEOM_COORD_DIGITS):
    """Recursively round the leaf [x, y] numbers of a GeoJSON coordinate tree."""
    if not coords:
        return coords
    if isinstance(coords[0], (int, float)):
        return [round(c, ndigits) for c in coords]
    return [round_coords(c, ndigits) for c in coords]


def round_geometry(geom):
    """Return a copy of a GeoJSON geometry with coordinates rounded for transport."""
    if not isinstance(geom, dict) or "coordinates" not in geom:
        return geom
    return {"type": geom.get("type"),
            "coordinates": round_coords(geom["coordinates"])}


def augment_row(row: dict) -> dict:
    """Add glyph/color/label and parse JSON props for the API response."""
    kind = row.get("kind") or "site"
    glyph, color, label = KIND_META.get(kind, KIND_META["site"])
    row["glyph"] = glyph
    row["color"] = color
    row["kind_label"] = label
    p = row.get("props")
    if isinstance(p, str):
        try:
            row["props"] = json.loads(p) if p else {}
        except (TypeError, ValueError):
            row["props"] = {}
    elif p is None:
        row["props"] = {}
    if row.get("geometry") and isinstance(row["geometry"], str):
        try:
            row["geometry"] = json.loads(row["geometry"])
        except (TypeError, ValueError):
            row["geometry"] = None
    if row.get("geometry"):
        row["geometry"] = round_geometry(row["geometry"])
    return row


LAYER_CAVEAT = (
    "PFAS investigation in Michigan is ONGOING — the site list grows as new "
    "contamination is found, so the absence of a PFAS site near a location does "
    "NOT mean absence of PFAS. An Area of Interest (AOI) is an area under "
    "investigation where the source has not yet been determined; residential "
    "wells there may be affected. Public water supply results are shown as "
    "general hexbin areas rather than precise locations — EGLE withholds exact "
    "system locations by design to protect critical infrastructure. "
    "Concentrations are in parts per trillion (ppt); EPA's 2024 drinking-water "
    "limit for PFOA and PFOS is 4 ppt. Nothing here is fabricated. "
    "Sources: Michigan PFAS Action Response Team (MPART) / EGLE, live."
)


def legend_payload() -> dict:
    return {
        "kinds": [{"key": k, "glyph": g, "color": c, "label": lbl}
                  for k, (g, c, lbl) in KIND_META.items()],
        "caveat": LAYER_CAVEAT,
        "mdhhs_fish_url": MDHHS_EAT_SAFE_FISH_URL,
    }
