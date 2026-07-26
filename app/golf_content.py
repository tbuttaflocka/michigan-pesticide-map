"""
Published-source content for the Golf-courses overlay: the typical turf-
management chemical list, the cited intensity comparison, the disclosure-gap
explanation, and the source list.

IMPORTANT — sourcing rules
  * The chemical list describes what is TYPICALLY used in turfgrass management
    generally (sourced from GCSAA BMP / "Chemical Control of Turfgrass Diseases",
    MSU Extension turf IPM, and university turf-extension references). It is NOT a
    record of what any specific mapped course applies.
  * The intensity figures are a CITED regional study (Long Island, NY, 1989
    survey data), presented as such — NOT a Michigan measurement.
  * No per-course pesticide amount is stated anywhere. We do not have that data.

Active-ingredient names below are the ones verified against the cited turf
references. Common actives that could not be individually source-verified were
left out rather than asserted from memory (see the research notes in git).
"""
from __future__ import annotations

# ---- Typical turfgrass-management chemicals (classes + common AIs) -----------
#
# Golf turf is unusually fungicide-heavy: closely-mown, intensively-irrigated
# greens face constant disease pressure (dollar spot, brown patch, Pythium, snow
# mold, anthracnose), so fungicides dominate golf-course pesticide use far more
# than in agriculture. Actives below are drawn from the GCSAA "Chemical Control
# of Turfgrass Diseases" IPM guide, MSU Extension turf-disease / grub-control
# pages, and university weed-control & PGR references. See SOURCES.
TURF_CHEMICALS = [
    {
        "category": "Fungicides",
        "note": ("The heaviest category on golf turf — disease pressure on "
                 "closely-mown, irrigated greens (dollar spot, brown patch, "
                 "Pythium, snow mold, anthracnose) drives frequent, sometimes "
                 "weekly, applications, far above agricultural fungicide use."),
        "source": "GCSAA Chemical Control of Turfgrass Diseases; MSU Extension turf IPM",
        "chemicals": [
            "Chlorothalonil", "Propiconazole", "Azoxystrobin", "Pyraclostrobin",
            "Trifloxystrobin", "Boscalid", "Iprodione", "Fludioxonil",
            "Thiophanate-methyl", "Myclobutanil", "Fenarimol", "Triadimefon",
            "Mancozeb", "PCNB (quintozene)",
        ],
    },
    {
        "category": "Herbicides",
        "note": ("Broadleaf- and grassy-weed control on fairways, roughs, and "
                 "greens — pre-emergent crabgrass control and post-emergent "
                 "broadleaf mixes."),
        "source": "UGA Turfgrass Weed Control; PNW Weed Management Handbook",
        "chemicals": [
            "2,4-D", "Dicamba", "Mecoprop (MCPP)", "MCPA", "Prodiamine",
            "Dithiopyr", "Pendimethalin", "Mesotrione", "Glyphosate",
        ],
    },
    {
        "category": "Insecticides",
        "note": ("Turf insect control, most prominently white grubs (larvae of "
                 "Japanese beetle and chafers), plus annual bluegrass weevil, "
                 "cutworms, and chinch bugs."),
        "source": "MSU Extension grub-control / turf insect guidance",
        "chemicals": [
            "Imidacloprid", "Clothianidin", "Thiamethoxam", "Chlorantraniliprole",
            "Trichlorfon", "Carbaryl", "Bifenthrin", "Halofenozide",
        ],
    },
    {
        "category": "Plant growth regulators",
        "note": ("Not pest-killing pesticides, but applied heavily on golf turf "
                 "to slow vertical growth, improve density, and suppress annual "
                 "bluegrass seedheads."),
        "source": "University turf-science PGR references (UMN, Clemson)",
        "chemicals": ["Trinexapac-ethyl", "Paclobutrazol", "Flurprimidol",
                      "Ethephon", "Mefluidide", "Prohexadione-calcium"],
    },
]

# ---- Cited intensity comparison ----------------------------------------------
#
# From the New York State Attorney General's report "Toxic Fairways: Risking
# Groundwater Contamination From Pesticides on Long Island Golf Courses"
# (Environmental Protection Bureau; 1991, revised Dec 1995), based on a 1990
# survey of Nassau/Suffolk courses using 1989 application data. Verbatim: "If
# these 50,000 pounds were applied evenly across the total area of the 52 golf
# courses, it would amount to an average of 7 pounds of pesticides per acre
# annually. By comparison, a national average of 1.5 pounds of pesticides per
# acre are applied in agriculture annually." Figures are ACTIVE INGREDIENT, per
# TOTAL acre. Presented as the cited, REGIONAL finding it is — not a Michigan
# measurement. (The 1.5 lb/acre agricultural baseline the report cites is itself
# a 1991 figure from Pimentel et al., not a current USDA/USGS statistic.)
INTENSITY = {
    "golf_lbs_per_acre": 7,
    "ag_lbs_per_acre": 1.5,
    "multiple": "nearly 5×",
    "headline": ("A New York Attorney General's survey of Long Island golf "
                 "courses found roughly 7 lbs of pesticides applied per acre per "
                 "year — nearly 5× the ~1.5 lbs per acre applied in agriculture."),
    "basis_note": ("Figures are active-ingredient, averaged over each course's "
                   "total acreage (per treated acre the study reported ~18 vs "
                   "2.7 lbs, about 7×)."),
    "regional_note": ("This is a regional Long Island, New York study (1989 use "
                      "data), not a Michigan measurement. It conveys typical "
                      "golf-turf application intensity — it is NOT a rate for any "
                      "specific course. The ~1.5 lb/acre agricultural baseline is "
                      "a 1991 figure (Pimentel et al.), not a current USDA number."),
    "source": ('NY State Attorney General, "Toxic Fairways" '
               "(Environmental Protection Bureau, 1991; rev. 1995)"),
    "source_url": ("https://www.beyondpesticides.org/assets/media/documents/"
                   "documents/toxic-fairways-1995.pdf"),
}

# ---- The disclosure gap ------------------------------------------------------
DISCLOSURE = {
    "michigan": ("Michigan does not require public reporting of golf-course "
                 "pesticide use. Under NREPA Part 83, commercial applicators keep "
                 "records and transmit only a restricted-use county summary to the "
                 "state — and MCL 324.8311 makes that information confidential and "
                 "expressly NOT subject to the Freedom of Information Act. There is "
                 "no public database of how much any course applies."),
    "private_vs_public": (
        "Privately-owned courses are not a 'public body' under Michigan's FOIA "
        "(MCL 15.232) and are not required to disclose pesticide-application logs. "
        "Publicly-owned courses — municipal, county, or public-university — are "
        "public bodies whose grounds records can be obtained by a Michigan FOIA "
        "request."),
    "municipal_guidance": (
        "For a municipally- or county-owned course, file a public-records (FOIA) "
        "request with that government's FOIA coordinator — usually the city or "
        "county clerk's office — for the grounds department's pesticide-"
        "application records."),
    "industry": ("Outside California (the one state with mandatory pesticide-use "
                 "reporting), there are effectively no public records of what "
                 "pesticides are applied on U.S. golf courses; the national "
                 "superintendents' association publishes only aggregate, "
                 "anonymized survey data, not course-level records."),
    "could_exist": (
        "Other states show this data could exist if required: Vermont (6 V.S.A. "
        "Ch. 87) requires a permit and an integrated pest management (IPM) plan "
        "for any golf-course pesticide use, and New York's Pesticide Reporting "
        "Law (ECL Art. 33, Title 12 / §33-1205) requires commercial applicators "
        "to file annual use reports."),
}

# ---- Sources (also surfaced in the Data Sources modal) -----------------------
# SOURCES[0]=OSM (registered by the loader as osm_golf); [1..3] map to the loader's
# gcsaa_bmp / msu_turf / nysdec_li_golf reference source_ids — keep that order.
SOURCES = [
    {"title": "OpenStreetMap (via Overpass API) — golf-course locations",
     "url": "https://www.openstreetmap.org/copyright",
     "note": ("Course footprints and attributes are crowd-sourced; coverage may "
              "be incomplete or occasionally out of date. © OpenStreetMap "
              "contributors, ODbL.")},
    {"title": "GCSAA — Chemical Control of Turfgrass Diseases (BMP / IPM guide)",
     "url": ("https://www.gcsaa.org/docs/default-source/research-and-information/"
             "ipm-planning-guide/chemical-control_diseases.pdf"),
     "note": "Common turf fungicide/pesticide active ingredients and classes."},
    {"title": "MSU Extension — Turf IPM (disease & grub management)",
     "url": "https://www.canr.msu.edu/ipm/diseases/",
     "note": ("Michigan turfgrass disease pressure and common fungicide / "
              "insecticide active ingredients.")},
    {"title": ('NY State Attorney General — "Toxic Fairways" (Long Island golf '
               "courses, 1991; rev. 1995)"),
     "url": ("https://www.beyondpesticides.org/assets/media/documents/documents/"
             "toxic-fairways-1995.pdf"),
     "note": "Source of the ~7 lbs/acre golf-course pesticide-intensity figure."},
]

# ---- Collapsible layer caveat (shown under the toggle) -----------------------
LAYER_CAVEAT = (
    "This layer shows where golf courses are located, not how much pesticide "
    "they apply. Michigan does not require public reporting of golf-course "
    "pesticide use, and industry records are not publicly available. The "
    "chemicals listed are those commonly used in turfgrass management generally, "
    "not records for any specific course. Note also that the app's agricultural "
    "pesticide layer (USGS EPest) excludes golf courses, lawns, and other non-"
    "agricultural uses entirely — so this land use is missing from those county "
    "totals."
)
