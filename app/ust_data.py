"""
Metadata, classification, and context for the Underground Storage Tank layer
(EGLE Remediation & Redevelopment Division).

USTs are the most common near-home contamination source in Michigan — an old
gas station two blocks away is real information a homebuyer rarely gets. The
dataset mixes two very different things, and conflating them would be misleading:

  * Part 211 (LARA) — a tank merely LICENSED. A working gas station's tanks are
    not, by themselves, a contaminated site.
  * Part 213 (EGLE) — a LEAKING tank: a confirmed release requiring corrective
    action. This is the one that matters for contamination.

So `category` splits into three, styled from prominent to muted:
  leaking_open   — Open_Release > 0: an open, confirmed release (PROMINENT, red)
  leaking_closed — Part 213 with releases, all closed/remediated (secondary)
  licensed       — Part 211, no reported release (muted; NOT a contaminated site)

No site or status is ever fabricated. Point locations vary in accuracy (some are
geocoded by address rather than GPS) and that is surfaced honestly.
"""
from __future__ import annotations

from .config import EGLE_RIDE_URL, EGLE_UST_HOME_URL

# category -> (glyph, color, legend label, short label)
CATEGORY_META = {
    "leaking_open":   ("⚠", "#e5484d", "Leaking — open release (corrective action)",
                       "Open leaking release"),
    "leaking_closed": ("◐", "#c9973b", "Leaking — closed / remediated",
                       "Closed / remediated release"),
    "licensed":       ("⛽", "#7f8b99", "Licensed tank — no reported release",
                       "Licensed tank (no release)"),
}


def classify(open_release, total_release, regulatory_program) -> str:
    """Split a UST row into leaking_open / leaking_closed / licensed based on its
    ACTUAL release history (not just the program code)."""
    o = open_release or 0
    t = total_release or 0
    if o > 0:
        return "leaking_open"
    if t > 0 or regulatory_program == 213:
        return "leaking_closed" if t > 0 else "licensed"
    return "licensed"


def program_label(program) -> str:
    if program == 213:
        return "Part 213 — leaking UST (EGLE corrective action)"
    if program == 211:
        return "Part 211 — licensed UST (LARA)"
    return "Regulatory program not recorded"


def accuracy_note(accuracy_m, address_matched) -> str | None:
    """Plain-language caution when a point's location is imprecise. Returns None
    when the location looks reliable (GPS, small accuracy value)."""
    if address_matched:
        return ("This point was located by address matching, not GPS — its "
                "position is approximate and may be off by the length of a "
                "parcel or block.")
    if accuracy_m and accuracy_m >= 50:
        return (f"Location accuracy is about {round(accuracy_m)} m — treat the "
                "point as approximate, not a pinpoint.")
    return None


def augment_row(row: dict) -> dict:
    """Add glyph/color/labels + accuracy note for the API response."""
    cat = row.get("category") or "licensed"
    glyph, color, label, short = CATEGORY_META.get(cat, CATEGORY_META["licensed"])
    row["glyph"] = glyph
    row["color"] = color
    row["category_label"] = label
    row["category_short"] = short
    row["program_label"] = program_label(row.get("regulatory_program"))
    row["accuracy_note"] = accuracy_note(row.get("horizontal_accuracy"),
                                         bool(row.get("address_matched")))
    return row


LAYER_CAVEAT = (
    "Michigan regulates underground storage tanks under two different laws, and "
    "this layer keeps them distinct: Part 211 (LARA) covers tanks that are merely "
    "LICENSED — a working gas station's tanks are not, by themselves, a "
    "contaminated site — while Part 213 (EGLE) covers LEAKING tanks with a "
    "confirmed release requiring corrective action. Red markers are open releases; "
    "amber are releases that have been closed/remediated; grey are licensed tanks "
    "with no reported release. This dataset covers KNOWN, registered tanks — "
    "unregistered or long-abandoned tanks, including most residential heating-oil "
    "tanks, are generally NOT included, so absence of a tank here does not mean "
    "none was ever present. Point locations vary in accuracy; some were placed by "
    "address matching rather than GPS. Nothing here is fabricated. "
    "Source: Michigan EGLE Remediation & Redevelopment Division (RRD); per-site "
    "detail is in EGLE's RIDE Mapper."
)


def legend_payload() -> dict:
    return {
        "categories": [
            {"key": k, "glyph": g, "color": c, "label": lbl, "short": short}
            for k, (g, c, lbl, short) in CATEGORY_META.items()
        ],
        "caveat": LAYER_CAVEAT,
        "ride_url": EGLE_RIDE_URL,
        "ust_home_url": EGLE_UST_HOME_URL,
    }
