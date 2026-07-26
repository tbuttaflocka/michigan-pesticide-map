"""
Metadata + helpers for the "Landfills & waste facilities" overlay.

The data is pulled LIVE from Michigan EGLE's Materials Management Open Data
ArcGIS service (see data_loader.load_landfills). Two source layers:

  * Part 115 Solid Waste Landfills — Type II municipal solid waste and Type III
    industrial / construction-and-demolition / coal-ash landfills.
  * Part 111 hazardous-waste Treatment/Storage/Disposal Facilities — we keep only
    the disposal-capable ones (a FacilityType containing "D"), i.e. the actual
    hazardous-waste land-disposal sites such as Wayne Disposal.

HONESTY NOTES (see the overlay caveat + README):
  * The EGLE Part 115 open-data layer only carries currently ACTIVE / accepting
    facilities. Closed, post-closure, and pre-regulation (unlined) landfills —
    frequently the bigger contamination risk — are NOT comprehensively mapped
    here; many appear instead in the Superfund/contamination overlay. We never
    fabricate closed-site records.
  * Groundwater / air / leachate / leak-detection monitoring is legally required
    but the RESULTS are not published as open data. Popups state what monitoring
    is required and point to EGLE's FOIA page rather than inventing numbers.
  * Capacity / remaining-volume is not in the EGLE feed, so it is left out rather
    than guessed.

CATEGORY_META / STATUS_META drive the map marker glyphs, colors, and legend.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .config import EGLE_FOIA_URL  # re-exported for the routes/popup

# category -> (glyph, color, legend label). Plain unicode glyphs (no icon font).
CATEGORY_META = {
    "msw":        ("\U0001F5D1", "#d96b35", "Type II — Municipal solid waste"),      # 🗑
    "industrial": ("\U0001F3ED", "#b5762e", "Type III — Industrial / low-hazard"),  # 🏭
    "cnd":        ("\U0001F9F1", "#a4883c", "Type III — Construction & demolition"), # 🧱
    "coal_ash":   ("⚫",     "#6f7785", "Type III — Coal ash"),                  # ⚫
    "hazardous":  ("☣",     "#f85149", "Part 111 — Hazardous waste (disposal)"),# ☣
}

# status -> (color, label). Closed / post-closure are styled distinctly by the
# frontend (desaturated fill + dashed ring). All current Part 115 open-data rows
# are "active"; the others are kept so the layer degrades honestly if EGLE ever
# publishes closed facilities.
STATUS_META = {
    "active":       ("#3fb950", "Active — accepting waste"),
    "post_closure": ("#d0a215", "Post-closure care"),
    "closed":       ("#9aa4b2", "Closed"),
    "unknown":      ("#9aa4b2", "Status not reported"),
}

# Part 111 FacilityType letter-codes (T=treatment, S=storage, D=disposal).
TSDF_TYPE_LABELS = {
    "T":   "Treatment",
    "S":   "Storage",
    "D":   "Disposal",
    "TS":  "Treatment & storage",
    "TD":  "Treatment & disposal",
    "SD":  "Storage & disposal",
    "TSD": "Treatment, storage & disposal",
}


def classify_type(facilitytype: str | None) -> tuple[str, str]:
    """Map an EGLE Part 115 ``facilitytype`` string to (category_key, label).

    Order matters: "Type III Low Hazardous Waste Landfill" is a low-hazard
    INDUSTRIAL landfill, not a RCRA hazardous-waste facility, so it must be
    caught by the industrial branch — the ``hazardous`` category is reserved for
    Part 111 TSDFs and is never assigned from a Part 115 type string.
    """
    t = (facilitytype or "").lower()
    if "coal ash" in t or "coal-ash" in t:
        return "coal_ash", (facilitytype or "Coal-ash landfill")
    if "c&d" in t or "construction" in t or "demolition" in t:
        return "cnd", (facilitytype or "Construction & demolition landfill")
    if "industrial" in t or "low hazardous" in t:
        return "industrial", (facilitytype or "Industrial waste landfill")
    if "type ii" in t or "msw" in t or "municipal" in t or "incinerator ash" in t:
        return "msw", (facilitytype or "Municipal solid-waste landfill")
    return "industrial", (facilitytype or "Solid-waste landfill")


def classify_status(disposalareastatus: str | None) -> tuple[str, str]:
    """Map an EGLE ``disposalareastatus`` string to (status_class, label)."""
    raw = (disposalareastatus or "").strip()
    s = raw.lower()
    if "post" in s:
        return "post_closure", (raw or "Post-closure care")
    if "accept" in s or "active" in s or "open" in s:
        return "active", (raw or "Active")
    if "clos" in s or "inactive" in s or "final" in s:
        return "closed", (raw or "Closed")
    return "unknown", (raw or "Status not reported")


def tsdf_type_label(facilitytype: str | None) -> str:
    code = (facilitytype or "").strip().upper()
    return TSDF_TYPE_LABELS.get(code, "Hazardous-waste facility")


def monitoring_note(category: str) -> str:
    """What environmental monitoring is legally REQUIRED at this facility type.

    Describes the requirement only — never actual results (those are FOIA-only).
    """
    if category == "hazardous":
        return (
            "As a hazardous-waste land-disposal facility (RCRA Subtitle C / "
            "Michigan Part 111), it must run groundwater detection and "
            "compliance monitoring, capture and manage leachate, and carry out "
            "corrective action for any release, throughout operation and the "
            "post-closure care period."
        )
    if category == "msw":
        return (
            "As a Type II municipal solid-waste landfill, federal law "
            "(40 CFR Part 258) requires groundwater monitoring for 62 "
            "constituents, sampled at least semiannually throughout the "
            "facility's active life and its post-closure care period. Michigan's "
            "operating license additionally requires monitoring of air, surface "
            "water, soil, leachate, and leak-detection systems."
        )
    if category == "coal_ash":
        return (
            "As a coal-combustion-residuals (coal-ash) disposal unit it is "
            "subject to the federal CCR rule (40 CFR Part 257), which requires "
            "groundwater monitoring and corrective action, plus the groundwater "
            "and leachate monitoring in its Michigan Part 115 operating license."
        )
    # industrial / C&D Type III
    return (
        "As a Type III industrial / construction-and-demolition landfill, "
        "Michigan's Part 115 operating license requires groundwater and "
        "leachate monitoring scaled to the waste stream, through operation and "
        "the post-closure care period."
    )


# ---- name matching (for TRI / Superfund cross-links) ----
#
# Precision matters far more than recall here: a WRONG cross-link would falsely
# attribute another facility's toxic releases or Superfund status to a landfill,
# which is misinformation. So we match on genuine shared DISTINCTIVE tokens, not
# on coordinate proximity alone — two unrelated facilities routinely sit within a
# kilometre of each other in an industrial corridor. Coordinates only *gate* a
# name match (reject implausibly distant pairs); they never create one.

# Corporate / structural tokens with no identifying value — stripped before
# comparing. City/county names, "landfill/disposal/waste", and plant numbers are
# deliberately KEPT: they are what actually distinguishes one facility's name
# from another's.
_GENERIC_TOKENS = {
    "llc", "inc", "incorporated", "co", "corp", "corporation", "company", "ltd",
    "lp", "llp", "the", "of", "and", "div", "division", "dept", "department",
    "plant", "facility", "facilities", "former", "frmr", "site",
}


def name_tokens(name: str | None) -> set[str]:
    """Distinctive lowercase tokens of a facility name (drops corporate noise and
    bare single letters, but keeps digits so 'Plant 3' ≠ 'Plant 6')."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return {t for t in s.split()
            if (len(t) > 1 or t.isdigit()) and t not in _GENERIC_TOKENS}


def match_names(a: str | None, b: str | None) -> float:
    """Return a match score in (0,1], or 0.0 if the two names are not confidently
    the same facility. A match requires either substantial token overlap
    (Jaccard ≥ 0.5) or one multi-token name fully contained in the other."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    jaccard = inter / len(ta | tb)
    smaller = min(len(ta), len(tb))
    contained = smaller >= 2 and inter >= smaller
    if jaccard >= 0.5 or contained:
        return max(jaccard, inter / smaller)
    return 0.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * 6371.0088 * asin(sqrt(a))


# Max separation for a name match to be plausibly the same physical site. Every
# verified true match sits within ~2 km; 5 km leaves headroom for imprecise
# geocodes while still rejecting same-named facilities in different cities.
CROSSLINK_MAX_KM = 5.0


def augment_row(row: dict) -> dict:
    """Add glyph/color/labels + monitoring/FOIA context to a landfill_sites row
    (a plain dict) for the API response. Non-destructive; returns the same dict."""
    cat = row.get("category") or "industrial"
    glyph, color, cat_label = CATEGORY_META.get(cat, CATEGORY_META["industrial"])
    st = row.get("status_class") or "unknown"
    st_color, st_label = STATUS_META.get(st, STATUS_META["unknown"])
    row["glyph"] = glyph
    row["color"] = color
    row["category_label"] = cat_label
    row["status_color"] = st_color
    row["status_display"] = row.get("status_label") or st_label
    row["monitoring"] = monitoring_note(cat)
    row["foia_url"] = EGLE_FOIA_URL
    return row


def legend_payload() -> dict:
    """Category + status legend for the frontend marker key."""
    return {
        "categories": [
            {"key": k, "glyph": g, "color": c, "label": lbl}
            for k, (g, c, lbl) in CATEGORY_META.items()
        ],
        "statuses": [
            {"key": k, "color": c, "label": lbl}
            for k, (c, lbl) in STATUS_META.items()
            if k != "unknown"
        ],
        "foia_url": EGLE_FOIA_URL,
    }
