"""Reference data for the water-quality overlay.

* PESTICIDE_MCL — EPA Primary Drinking Water MCLs (µg/L) for the most
  commonly-detected pesticides. These are the regulatory limits we compare
  WQP result values against to colour-code sites red.
* AQUATIC_LIFE_BENCHMARKS — USGS aquatic-life-acute benchmarks (µg/L).
  Often much lower than drinking-water MCLs; used as a secondary threshold.
* NAWQA_MI_STREAMS — the 11 Michigan stream stations screened in USGS SIR
  2007-5077 (Stone et al.). The lat/lng are the published USGS station
  coordinates; the `pesticides_detected` list is what that publication
  reported during the 2002–2005 sampling window.
"""

import re

# Federal EPA drinking-water MCLs in micrograms per litre. None means
# "not regulated as MCL — use aquatic benchmark instead". Compounds in
# uppercase because WQP characteristic names mix case; we match
# case-insensitively in the loader.
PESTICIDE_MCL = {
    "ATRAZINE":          3.0,
    "SIMAZINE":          4.0,
    "ALACHLOR":          2.0,
    "2,4-D":             70.0,
    "LINDANE":           0.2,
    "GLYPHOSATE":        700.0,
    "CARBOFURAN":        40.0,
    "DALAPON":           200.0,
    "DINOSEB":           7.0,
    "DIQUAT":            20.0,
    "ENDOTHALL":         100.0,
    "HEPTACHLOR":        0.4,
    "HEPTACHLOR EPOXIDE":0.2,
    "METHOXYCHLOR":      40.0,
    "OXAMYL":            200.0,
    "PENTACHLOROPHENOL": 1.0,
    "PICLORAM":          500.0,
    "TOXAPHENE":         3.0,
}

# USGS aquatic-life benchmarks (chronic invertebrate / fish, µg/L).
# Cited values are the lower of the two for the common ag-pesticides.
AQUATIC_LIFE_BENCHMARKS = {
    "ATRAZINE":      1.0,
    "METOLACHLOR":   1.0,
    "CHLORPYRIFOS":  0.04,
    "CARBARYL":      0.5,
    "DIAZINON":      0.1,
    "DIURON":        2.4,
    "DICAMBA":       0.6,
    "GLYPHOSATE":    100.0,
    "ACETOCHLOR":    1.7,
    "MALATHION":     0.035,
    "PERMETHRIN":    0.0014,
    "IMIDACLOPRID":  0.385,
}


# Multipliers from a per-litre concentration unit to micrograms-per-litre (µg/L).
_PER_LITRE_UGL = {
    "mg/l": 1000.0, "ug/l": 1.0, "ng/l": 0.001, "pg/l": 1e-6,
    "milligrams per liter": 1000.0, "ppm": 1000.0,
    "micrograms per liter": 1.0, "ppb": 1.0,
    "nanograms per liter": 0.001, "ppt": 0.001,   # ppt = parts-per-trillion ≈ ng/L
    "picograms per liter": 1e-6,
}
# "<prefix>g<analyte-junk>/l" — some feeds fuse the analyte into the unit label,
# e.g. "ugAtrazn/L". We reduce it to its "<prefix>g/l" core.
_FUSED_UNIT_RE = re.compile(r"^([munp])g[a-z0-9,\-]*/l$")


def to_ugl(value: float | None, unit: str) -> float | None:
    """Convert a per-litre water concentration to micrograms-per-litre (µg/L).

    Returns None for units that are NOT volumetric water concentrations —
    mass-per-mass ratios (ng/g, ug/kg → sediment/tissue) and physical readings
    (psi, %, cfs) — because those cannot be compared against a µg/L drinking-
    water MCL. Case- and label-tolerant: handles "ng/L" vs "ng/l", "µg/l",
    spelled-out names, ppb/ppm/ppt, and fused labels like "ugAtrazn/L".
    """
    if value is None:
        return None
    u = (unit or "").strip().lower().replace("µ", "u")
    if not u:
        return None
    u = u.split()[0]                       # drop trailing analyte label ("ug/l 2,4-d")
    m = _FUSED_UNIT_RE.match(u)
    if m:
        u = m.group(1) + "g/l"
    mult = _PER_LITRE_UGL.get(u)
    return value * mult if mult is not None else None


def threshold_for(compound: str) -> tuple[float | None, str]:
    """Return (threshold µg/L, source label) for a compound name.
    MCL takes precedence; aquatic-life benchmark is the fallback."""
    if not compound:
        return None, ""
    key = compound.strip().upper()
    if key in PESTICIDE_MCL:
        return PESTICIDE_MCL[key], "EPA MCL"
    if key in AQUATIC_LIFE_BENCHMARKS:
        return AQUATIC_LIFE_BENCHMARKS[key], "USGS aquatic-life benchmark"
    return None, ""


# USGS SIR 2007-5077: 11 Michigan stream monitoring stations screened for
# atrazine, chlorpyrifos, diazinon, metolachlor, and simazine, 2002-2005.
NAWQA_MI_STREAMS = [
    {"site_id": "USGS-NAWQA-04101000", "name": "St. Joseph River near Burlington, MI",
     "lat": 41.7878, "lon": -85.1364, "huc8": "04050001",
     "pesticides_detected": ["ATRAZINE", "METOLACHLOR", "SIMAZINE"]},
    {"site_id": "USGS-NAWQA-04106000", "name": "Kalamazoo River at Comstock, MI",
     "lat": 42.2934, "lon": -85.4933, "huc8": "04050003",
     "pesticides_detected": ["ATRAZINE", "METOLACHLOR"]},
    {"site_id": "USGS-NAWQA-04119400", "name": "Grand River at Grand Rapids, MI",
     "lat": 42.9634, "lon": -85.6700, "huc8": "04050006",
     "pesticides_detected": ["ATRAZINE", "METOLACHLOR", "SIMAZINE"]},
    {"site_id": "USGS-NAWQA-04122500", "name": "Pere Marquette River at Scottville, MI",
     "lat": 43.9572, "lon": -86.2828, "huc8": "04060102",
     "pesticides_detected": ["ATRAZINE"]},
    {"site_id": "USGS-NAWQA-04121944", "name": "Muskegon River at Croton, MI",
     "lat": 43.4239, "lon": -85.6597, "huc8": "04060102",
     "pesticides_detected": ["ATRAZINE", "METOLACHLOR"]},
    {"site_id": "USGS-NAWQA-04135500", "name": "Au Sable River near Mio, MI",
     "lat": 44.6539, "lon": -84.1297, "huc8": "04070007",
     "pesticides_detected": []},
    {"site_id": "USGS-NAWQA-04137500", "name": "Thunder Bay River near Alpena, MI",
     "lat": 45.0606, "lon": -83.4644, "huc8": "04070004",
     "pesticides_detected": []},
    {"site_id": "USGS-NAWQA-04157000", "name": "Saginaw River at Saginaw, MI",
     "lat": 43.4253, "lon": -83.9700, "huc8": "04080202",
     "pesticides_detected": ["ATRAZINE", "METOLACHLOR", "SIMAZINE", "CHLORPYRIFOS"]},
    {"site_id": "USGS-NAWQA-04161820", "name": "Clinton River at Mt. Clemens, MI",
     "lat": 42.5959, "lon": -82.8835, "huc8": "04090003",
     "pesticides_detected": ["ATRAZINE", "DIAZINON"]},
    {"site_id": "USGS-NAWQA-04166500", "name": "River Rouge at Detroit, MI",
     "lat": 42.3097, "lon": -83.1797, "huc8": "04090004",
     "pesticides_detected": ["DIAZINON", "ATRAZINE"]},
    {"site_id": "USGS-NAWQA-04059500", "name": "Escanaba River at Cornell, MI",
     "lat": 45.9119, "lon": -87.2308, "huc8": "04030110",
     "pesticides_detected": ["ATRAZINE"]},
]


# WQP characteristic-name → canonical compound mapping for the most common
# pesticide entries. Many compounds appear as "Atrazine", "atrazine, total",
# "ATRAZINE", etc. — we normalise to upper-case canonical names so the
# choropleth can join on `compound` cleanly.
COMPOUND_ALIASES = {
    "atrazine":           "ATRAZINE",
    "atrazine, total":    "ATRAZINE",
    "atrazine, dissolved":"ATRAZINE",
    "metolachlor":        "METOLACHLOR",
    "metolachlor, total": "METOLACHLOR",
    "metolachlor-s":      "METOLACHLOR-S",
    "s-metolachlor":      "METOLACHLOR-S",
    "simazine":           "SIMAZINE",
    "chlorpyrifos":       "CHLORPYRIFOS",
    "diazinon":           "DIAZINON",
    "glyphosate":         "GLYPHOSATE",
    "2,4-d":              "2,4-D",
    "2,4-d, total":       "2,4-D",
    "alachlor":           "ALACHLOR",
    "acetochlor":         "ACETOCHLOR",
    "dicamba":            "DICAMBA",
    "imidacloprid":       "IMIDACLOPRID",
    "diuron":             "DIURON",
    "malathion":          "MALATHION",
    "carbaryl":           "CARBARYL",
    "carbofuran":         "CARBOFURAN",
}


def canonicalize_compound(name: str) -> str:
    if not name:
        return ""
    key = name.strip().lower()
    if key in COMPOUND_ALIASES:
        return COMPOUND_ALIASES[key]
    return name.strip().upper()
