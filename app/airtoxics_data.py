"""
Metadata, styling, parsing, and caveats for the EPA air toxics risk layer.

Source: EPA AirToxScreen (successor to NATA), 2019 assessment, CENSUS-TRACT level,
from EPA's downloadable national result spreadsheets (cancer risk by source group
and by pollutant, plus the noncancer hazard index for five target organs). The
2019 release is the newest tract-level assessment (2020+ is census-block level and
is a separate decision). Michigan has ~2,756 tracts in 2019.

EPA cautions that assessment years are NOT comparable (inventory, modeling,
background, and health-benchmark changes between releases), so we show ONE year
and never trend it. This replaced the 2017 NATA snapshot; both are never kept
side by side in a way that could render as a trend.

WHAT THIS IS (and is NOT), baked in because EPA is emphatic about it:
  - A SCREENING assessment: modeled estimates from emissions inventories and
    dispersion models, NOT measured air quality. It identifies areas for further
    study; it does NOT determine risk at a specific home, school, or address.
  - Cancer risk is expressed as chance-in-a-million over a 70-year lifetime of
    continuous OUTDOOR exposure. Indoor air (where people spend most time) and
    non-inhalation routes are not included.

WHY TRACT-LEVEL / WHICH YEAR: the 2020 AirToxScreen is block-level only in bulk
form (Michigan ≈ 100k+ blocks — far too many polygons to render, and only served
as tiled maps or 150 MB+ per-region spreadsheets). The NATA tract-level release
is the finest granularity that is both queryable and renderable, and — unlike the
2020 per-pollutant block services — it carries the SOURCE-CATEGORY breakdown in a
single table, which is the most useful part (industry vs traffic vs background).

DATA INTEGRITY NOTE: the service's own `CR_Total_Risk` column is coarse/unreliable
(rounded, and it does not reconcile with the detail). We therefore compute each
tract's total as the SUM of the per-source-category fields, which — because total
risk = sum over sources = sum over pollutants — equals the sum of the per-pollutant
fields to the decimal. That yields a granular, self-consistent total.

EPA cautions against comparing across assessment years (methods change); we show
ONE assessment year and never trend it.
"""
from __future__ import annotations

# The eight EPA source categories, in display order. Each is (column-prefix, key,
# short label, color, glossary key). These eight groups sum to the tract's total
# cancer risk. The AirToxScreen 2019 spreadsheets break each group into SUBGROUPS
# (e.g. on-road by duty/fuel/network; non-road incl. CMV/locomotive/airport/
# railyard; nonpoint by industrial/oil-gas/residential-wood-combustion/etc.), so
# the column-prefix below maps every subgroup column back to its top-level group
# (see source_group_for_column). The eight groups themselves are UNCHANGED from the
# 2017 layer, so the legend/popup keys stay identical. Colors read as "who is
# responsible": industrial reds/browns for point & nonpoint, blues for mobile,
# greens for natural, grey for background.
SOURCE_CATEGORIES = [
    ("PT",         "point",      "Industry (point)",    "#c0553a", "point source"),
    ("NP",         "nonpoint",   "Area / nonpoint",     "#d98a3d", "nonpoint/area source"),
    ("OR",         "onroad",     "On-road traffic",     "#4f9dd6", "on-road traffic"),
    ("NR",         "nonroad",    "Non-road mobile",     "#7b6cd9", "non-road mobile"),
    ("FIRE",       "fire",       "Fires",               "#e0623c", "fire emissions"),
    ("BIOGENICS",  "biogenic",   "Biogenic",            "#4faa6b", "biogenic emissions"),
    ("SECONDARY",  "secondary",  "Secondary formation", "#9aa63c", "secondary formation"),
    ("BACKGROUND", "background", "Background",           "#8a94a3", "background concentration"),
]
SOURCE_META = {k: {"label": lbl, "color": col, "gloss": g}
               for _p, k, lbl, col, g in SOURCE_CATEGORIES}
# longest prefixes first so "BACKGROUND"/"BIOGENICS" never shadow a 2-letter code
_PREFIX_TO_KEY = sorted(((p.upper(), k) for p, k, *_ in SOURCE_CATEGORIES),
                        key=lambda t: -len(t[0]))

# Target organs for which AirToxScreen 2019 publishes a noncancer hazard index, in
# display order. Keys match the hi_<organ> columns in airtoxics_tracts.
HAZARD_ORGANS = [
    ("respiratory",   "Respiratory"),
    ("neurological",  "Neurological"),
    ("immunological", "Immunological"),
    ("kidney",        "Kidney"),
    ("liver",         "Liver"),
]


def source_group_for_column(header: str) -> str | None:
    """Map a 2019 result-file data column header to one of the eight top-level
    source groups by its prefix (e.g. 'OR-HeavyDuty-OnNetwork-Diesel Cancer Risk
    (per million)' -> 'onroad', 'NR- Point-Railyards ...' -> 'nonroad'). Returns
    None for non-source columns (geographic reference, the rounded Total)."""
    if not header:
        return None
    head = header.split(" ", 1)[0].upper().strip().strip("-")
    for prefix, key in _PREFIX_TO_KEY:
        if head.startswith(prefix):
            return key
    return None

# Sequential palette for the tract choropleth — deliberately COOL (indigo → teal →
# green → chartreuse) so it is NOT confused with the warm red/orange scale the
# cancer-incidence layer uses. These are different quantities and must look it.
RISK_PALETTE = ["#10233a", "#173a51", "#1c5462", "#1f7168", "#2f8c63",
                "#5aa657", "#8dbf4f", "#c3d64e"]

# Cancer-risk metric today; the selector is built to accept more (e.g. a future
# noncancer respiratory hazard index) without a redesign.
METRICS = {
    "cancer": {"label": "Cancer risk (in a million)", "unit": "in a million"},
}

# Clean display names for the air toxics that actually drive Michigan risk, so the
# popup's pollutant links resolve nicely through to the chemical/PubChem info. Any
# field not listed falls back to a humanized version of the field name.
POLLUTANT_NAMES = {
    "CR_Formaldehyde": "Formaldehyde",
    "CR_Carbon_tetrachloride": "Carbon tetrachloride",
    "CR_Benzene": "Benzene",
    "CR_Acetaldehyde": "Acetaldehyde",
    "CR_1_3_Butadiene": "1,3-Butadiene",
    "CR_Ethylene_oxide": "Ethylene oxide",
    "CR_Acrolein": "Acrolein",
    "CR_Naphthalene": "Naphthalene",
    "CR_Chromium_VI_hexavalent": "Chromium VI (hexavalent)",
    "CR_AsCompoundsInorgInclArsine": "Arsenic compounds (inorganic)",
    "CR_Benzoapyrene": "Benzo(a)pyrene",
    "CR_Nickel_compounds": "Nickel compounds",
    "CR_Cadmium_compounds": "Cadmium compounds",
    "CR_Ethylbenzene": "Ethylbenzene",
    "CR_Tetrachloroethylene": "Tetrachloroethylene",
    "CR_Trichloroethylene": "Trichloroethylene",
    "CR_1_4_Dichlorobenzene": "1,4-Dichlorobenzene",
    "CR_Coke_oven_emissions": "Coke oven emissions",
    "CR_Chloroprene": "Chloroprene",
    "CR_Hydrazine": "Hydrazine",
    "CR_Acrylonitrile": "Acrylonitrile",
    "CR_Ethylene_dibromide": "Ethylene dibromide",
    "CR_POM_Group_2": "Polycyclic organic matter (POM)",
    "CR_Diesel_PM": "Diesel particulate matter",
}


import re as _re
# Reverse lookup from curated display names, keyed by an alnum-only uppercase
# fold, so an EPA ALL-CAPS header column ("CARBON TETRACHLORIDE", "BENZOAPYRENE")
# resolves back to nicely-cased chemistry ("Carbon tetrachloride", "Benzo(a)pyrene")
# that still matches the chemical/PubChem links.
_POLL_BY_FOLD = {_re.sub(r"[^A-Z0-9]", "", v.upper()): v for v in POLLUTANT_NAMES.values()}


def pretty_pollutant_name(raw: str) -> str:
    """Normalize a 2019 result-file pollutant column name to a readable display
    name, preferring the curated spelling and falling back to title case."""
    hit = _POLL_BY_FOLD.get(_re.sub(r"[^A-Z0-9]", "", (raw or "").upper()))
    return hit if hit else (raw or "").title()


def clean_pollutant_name(field: str, alias: str | None = None) -> str:
    """Human-readable chemical name for a CR_<pollutant> field.

    Prefers the curated name, then the service field alias (stripped of the
    " Cancer Risk (per million)" suffix), then a humanized field name."""
    if field in POLLUTANT_NAMES:
        return POLLUTANT_NAMES[field]
    if alias and alias != field:
        a = alias
        for suf in (" Cancer Risk (per million)", " Cancer Risk (per Million)",
                    " Cancer Risk", " (per million)"):
            if a.endswith(suf):
                a = a[: -len(suf)]
        a = a.strip()
        if a:
            return a
    name = field[3:] if field.startswith("CR_") else field
    return name.replace("_", " ").strip()


# ---- caveats (shown prominently in the map popup AND the homebuyer report) ----
# EPA is explicit; these are near-verbatim to their guidance.
CAVEATS = [
    "These are MODELED estimates from emissions inventories and dispersion models, "
    "not measured air quality at this location.",
    "This is a SCREENING assessment designed to identify areas for further study — "
    "not to determine risk at a specific address, home, or school.",
    "It assumes continuous OUTDOOR exposure at this location for 70 years. Indoor "
    "air, where people spend most of their time, is not included.",
]

LAYER_CAVEAT = (
    "EPA's air toxics assessment is a SCREENING tool: modeled cancer-risk estimates "
    "(chance-in-a-million over a 70-year lifetime of outdoor exposure), not measured "
    "air. EPA cautions against using it to determine risk at an exact place like a "
    "home or school — it is meant to flag areas for further study. Indoor air is not "
    "included. EPA also cautions against comparing across assessment years because "
    "the methods change, so only one assessment year is shown here and it is not "
    "trended. Nothing here is fabricated."
)

ASSESSMENT_LABEL = "EPA AirToxScreen (2019 assessment)"
SOURCE_URL = "https://www.epa.gov/AirToxScreen"

# Facts for the caveat text (reported to the user; wired into UI copy in the UI
# phase). EPA does NOT quantify a cancer risk for diesel particulate matter — only
# its noncancer effects — because it has no cancer dose-response value; and only a
# subset of the modeled air toxics have dose-response values at all.
DIESEL_PM_CANCER_QUANTIFIED = False
DIESEL_PM_NOTE = (
    "Diesel particulate matter is NOT included in the cancer-risk totals — EPA has "
    "not set a cancer dose-response value for diesel PM — but its NONCANCER "
    "(respiratory) effects are included in the hazard index.")
# AirToxScreen models 181 air toxics; 127 carry dose-response values and thus
# contribute to the cancer-risk and hazard-index totals (per EPA's assessment docs).
AIR_TOXICS_MODELED = 181
AIR_TOXICS_WITH_DOSE_RESPONSE = 127


def legend_payload(national_avg: float | None, mi_avg: float | None) -> dict:
    return {
        "metrics": [{"key": k, **v} for k, v in METRICS.items()],
        "sources": [{"key": k, "label": lbl, "color": col, "gloss": g}
                    for _f, k, lbl, col, g in SOURCE_CATEGORIES],
        "palette": RISK_PALETTE,
        "assessment": ASSESSMENT_LABEL,
        "national_avg": national_avg,
        "mi_avg": mi_avg,
        "caveats": CAVEATS,
        "caveat": LAYER_CAVEAT,
        "source_url": SOURCE_URL,
    }
