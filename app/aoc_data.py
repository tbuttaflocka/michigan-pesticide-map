"""
Michigan Great Lakes Areas of Concern (AOCs) — curated registry + transcribed
Beneficial Use Impairment (BUI) status.

PROVENANCE / SOURCING (strict):
  * Geometry: per-AOC boundary files published by EPA's Great Lakes National
    Program Office, a frozen 2020 snapshot (mostly 2013-2015 NAD83 shapefiles;
    Rouge is a 2020 File Geodatabase). Converted once to app/aoc_boundaries.geojson
    by scripts/build_aoc.py (pyshp + shapely + pyogrio, dev-time only). The counties
    each AOC touches were DERIVED from the polygon by intersecting it against
    data/michigan_counties.geojson (shapely area-overlap) — never from a hand list.
  * BUIs: every row below was transcribed from that AOC's own EPA page (BUI_SOURCE)
    on 2026-10-04. Nothing here is written from model knowledge. Removal dates are
    recorded only where printed on the AOC page; where a removal is documented only
    in a separate PDF approval letter with no date on the page, removal_date is None
    and a note says so. Statuses that the page leaves ambiguous are marked
    "unconfirmed".
  * White Lake and Muskegon Lake have NO downloadable boundary file in EPA's
    snapshot, so they are stored with NULL geometry (not drawn/approximated) and
    their counties cannot be geometry-derived.
  * No identifier joins an AOC to anything else in this app. The Torch Lake AOC and
    our Torch Lake Superfund record are DIFFERENT identifiers for overlapping
    geography and are kept entirely separate (no name-matching).

The 14 standard IJC/EPA BUI names (used verbatim):
"""
from __future__ import annotations

TRANSCRIBED_ON = "2026-10-04"
SNAPSHOT = "EPA GLNPO AOC boundary files, 2020 snapshot"

# Canonical IJC/EPA Beneficial Use Impairment names (verbatim). Every BUI row's
# name must be one of these.
BUI_STANDARD = [
    "Restrictions on Fish and Wildlife Consumption",
    "Tainting of Fish and Wildlife Flavor",
    "Degradation of Fish and Wildlife Populations",
    "Fish Tumors or Other Deformities",
    "Bird or Animal Deformities or Reproduction Problems",
    "Degradation of Benthos",
    "Restrictions on Dredging Activities",
    "Eutrophication or Undesirable Algae",
    "Restrictions on Drinking Water Consumption, or Taste and Odor Problems",
    "Beach Closings",
    "Degradation of Aesthetics",
    "Added Costs to Agriculture or Industry",
    "Degradation of Phytoplankton and Zooplankton Populations",
    "Loss of Fish and Wildlife Habitat",
]
_B = {s.split()[0].lower() + s.split()[1].lower(): s for s in BUI_STANDARD}  # unused helper guard

_EPA = "https://www.epa.gov/great-lakes-aocs"

# slug -> registry. has_geom=False for the two with no published boundary file.
AOCS = [
    # slug          name                     status      delisted  has_geom  page
    ("clinton",     "Clinton River",         "active",   None,      True,  f"{_EPA}/clinton-river-aoc"),
    ("detroit",     "Detroit River",         "active",   None,      True,  f"{_EPA}/detroit-river-aoc"),
    ("kalamazoo",   "Kalamazoo River",       "active",   None,      True,  f"{_EPA}/kalamazoo-river-aoc"),
    ("manistique",  "Manistique River",      "active",   None,      True,  f"{_EPA}/manistique-river-aoc"),
    ("riverraisin", "River Raisin",          "active",   None,      True,  f"{_EPA}/river-raisin-aoc"),
    ("rouge",       "Rouge River",           "active",   None,      True,  f"{_EPA}/rouge-river-aoc"),
    ("saginaw",     "Saginaw River and Bay", "active",   None,      True,  f"{_EPA}/saginaw-river-and-bay-aoc"),
    ("stclair",     "St. Clair River",       "active",   None,      True,  f"{_EPA}/st-clair-river-aoc"),
    ("stmarys",     "St. Marys River",       "active",   None,      True,  f"{_EPA}/st-marys-river-aoc"),
    ("torchlake",   "Torch Lake",            "active",   None,      True,  f"{_EPA}/torch-lake-aoc"),
    ("whitelake",   "White Lake",            "delisted", "2014-10", False, f"{_EPA}/white-lake-aoc-delisted"),
    ("deerlake",    "Deer Lake",             "delisted", "2014-10", True,  f"{_EPA}/deer-lake-aoc-delisted"),
    ("menominee",   "Lower Menominee River", "delisted", "2020-08", True,  f"{_EPA}/lower-menominee-river-aoc"),
    ("muskegonlake","Muskegon Lake",         "delisted", "2025-09", False, f"{_EPA}/muskegon-lake-aoc"),
]

# Per-AOC BUIs transcribed from BUI_SOURCE (each AOC's EPA page) on TRANSCRIBED_ON.
# (BUI name, status 'impaired'|'removed'|'unconfirmed', removal_date 'YYYY-MM'|'YYYY'|None, note)
BUIS = {
    "clinton": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Eutrophication or Undesirable Algae", "impaired", None, None),
        ("Degradation of Fish and Wildlife Populations", "impaired", None, None),
        ("Beach Closings", "impaired", None, None),
        ("Degradation of Aesthetics", "removed", "2020-09", None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Restrictions on Dredging Activities", "impaired", None, None),
        ("Loss of Fish and Wildlife Habitat", "impaired", None, None),
    ],
    "detroit": [
        ("Tainting of Fish and Wildlife Flavor", "removed", "2013-08", None),
        ("Restrictions on Drinking Water Consumption, or Taste and Odor Problems", "removed", "2011-07", None),
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Degradation of Fish and Wildlife Populations", "impaired", None, None),
        ("Beach Closings", "impaired", None, None),
        ("Fish Tumors or Other Deformities", "impaired", None, None),
        ("Degradation of Aesthetics", "impaired", None, None),
        ("Bird or Animal Deformities or Reproduction Problems", "impaired", None, None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Restrictions on Dredging Activities", "impaired", None, None),
        ("Loss of Fish and Wildlife Habitat", "impaired", None, None),
    ],
    "kalamazoo": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Degradation of Fish and Wildlife Populations", "impaired", None, None),
        ("Beach Closings", "removed", "2011-03", None),
        ("Degradation of Aesthetics", "removed", "2012-04", None),
        ("Bird or Animal Deformities or Reproduction Problems", "impaired", None, None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Restrictions on Dredging Activities", "impaired", None, None),
        ("Loss of Fish and Wildlife Habitat", "impaired", None, None),
    ],
    "manistique": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Restrictions on Dredging Activities", "removed", "2021-09", None),
        ("Beach Closings", "removed", "2010-05", None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2008-09", None),
        ("Degradation of Benthos", "removed", "2006-11", None),
    ],
    "riverraisin": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Eutrophication or Undesirable Algae", "removed", "2013-09", None),
        ("Degradation of Fish and Wildlife Populations", "removed", "2015-08", None),
        ("Beach Closings", "removed", "2013-09", None),
        ("Degradation of Aesthetics", "removed", "2012-04", None),
        ("Bird or Animal Deformities or Reproduction Problems", "impaired", None, None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Restrictions on Dredging Activities", "impaired", None, None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2015-08", None),
    ],
    "rouge": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Eutrophication or Undesirable Algae", "impaired", None, None),
        ("Degradation of Fish and Wildlife Populations", "impaired", None, None),
        ("Beach Closings", "impaired", None, None),
        ("Fish Tumors or Other Deformities", "impaired", None, None),
        ("Degradation of Aesthetics", "impaired", None, None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Restrictions on Dredging Activities", "impaired", None, None),
        ("Loss of Fish and Wildlife Habitat", "impaired", None, None),
    ],
    "saginaw": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Eutrophication or Undesirable Algae", "impaired", None, None),
        ("Tainting of Fish and Wildlife Flavor", "removed", "2008-09", None),
        ("Restrictions on Drinking Water Consumption, or Taste and Odor Problems", "removed", "2008-06", None),
        ("Degradation of Fish and Wildlife Populations", "impaired", None, None),
        ("Beach Closings", "impaired", None, None),
        ("Degradation of Aesthetics", "impaired", None, None),
        ("Bird or Animal Deformities or Reproduction Problems", "impaired", None, None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Degradation of Phytoplankton and Zooplankton Populations", "impaired", None, None),
        ("Restrictions on Dredging Activities", "impaired", None, None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2014-05", None),
    ],
    "stclair": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Tainting of Fish and Wildlife Flavor", "removed", "2009-11", None),
        ("Restrictions on Drinking Water Consumption, or Taste and Odor Problems", "impaired", None, None),
        ("Beach Closings", "removed", "2016-05", None),
        ("Degradation of Aesthetics", "removed", "2012-07", None),
        ("Bird or Animal Deformities or Reproduction Problems", "removed", "2017", "page gives year only"),
        ("Added Costs to Agriculture or Industry", "removed", "2012-06", None),
        ("Degradation of Benthos", "removed", "2014-11", None),
        ("Restrictions on Dredging Activities", "removed", "2011-03", None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2017-09", None),
    ],
    "stmarys": [
        ("Degradation of Aesthetics", "removed", "2014-01", None),
        ("Bird or Animal Deformities or Reproduction Problems", "removed", "2014-03", None),
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Eutrophication or Undesirable Algae", "removed", "2017-12", None),
        ("Degradation of Fish and Wildlife Populations", "removed", "2019-09", None),
        ("Beach Closings", "removed", "2016-07", None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Restrictions on Dredging Activities", "removed", "2017-11", None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2019-09", None),
        ("Fish Tumors or Other Deformities", "impaired", None, "page notes a study was pending"),
    ],
    "torchlake": [
        ("Restrictions on Fish and Wildlife Consumption", "impaired", None, None),
        ("Degradation of Benthos", "impaired", None, None),
        ("Fish Tumors or Other Deformities", "removed", "2007-04", None),
    ],
    "whitelake": [
        ("Restrictions on Dredging Activities", "removed", "2011-09", None),
        ("Eutrophication or Undesirable Algae", "removed", "2012-04", None),
        ("Degradation of Benthos", "removed", "2012-06", None),
        ("Restrictions on Fish and Wildlife Consumption", "removed", "2013-02", None),
        ("Restrictions on Drinking Water Consumption, or Taste and Odor Problems", "removed", "2014-03", None),
        ("Degradation of Aesthetics", "removed", "2014-03", None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2014-04", None),
        ("Degradation of Fish and Wildlife Populations", "removed", "2014-04", None),
    ],
    "deerlake": [
        ("Restrictions on Fish and Wildlife Consumption", "removed", "2014-02", None),
        ("Bird or Animal Deformities or Reproduction Problems", "removed", "2011-09", None),
        ("Eutrophication or Undesirable Algae", "removed", "2011-09", None),
    ],
    "menominee": [
        ("Beach Closings", "removed", "2011-03", None),
        ("Degradation of Benthos", "removed", "2017-05", None),
        ("Restrictions on Dredging Activities", "removed", "2017-05", None),
        ("Restrictions on Fish and Wildlife Consumption", "removed", "2018-06", None),
        ("Degradation of Fish and Wildlife Populations", "removed", "2019-02", None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2019-02", None),
    ],
    "muskegonlake": [
        ("Restrictions on Dredging Activities", "removed", "2011-09", None),
        ("Restrictions on Fish and Wildlife Consumption", "removed", "2013-02", None),
        ("Beach Closings", "removed", "2015-08", None),
        ("Restrictions on Drinking Water Consumption, or Taste and Odor Problems", "removed", "2013-02", None),
        ("Degradation of Aesthetics", "removed", "2021-10", None),
        ("Degradation of Fish and Wildlife Populations", "removed", "2023-05", None),
        ("Loss of Fish and Wildlife Habitat", "removed", "2023-05", None),
        ("Eutrophication or Undesirable Algae", "removed", "2024-03", None),
        ("Degradation of Benthos", "removed", "2024-10", None),
    ],
}

# AOC-level transcription notes (shown in the report / stored as source caveats).
AOC_NOTES = {
    "torchlake": "EPA page lists only 3 BUIs; unconfirmed whether this is the complete "
                 "historical set for this AOC.",
    "stclair": "EPA page prose says 10 BUIs were identified on the U.S. side; 10 are "
               "listed and transcribed.",
}
