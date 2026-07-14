"""
Reference data for the cancer-incidence overlay.

Live data is *preferred* — the loader tries the NCI State Cancer Profiles
export first, and will ingest any real per-county CSVs the user drops into
``data/cancer/`` (see ``load_cancer_data`` in ``data_loader.py``). When neither
is available, the loader seeds every county with the Michigan statewide
baseline defined here, flags the row ``source='NCI_state_baseline'``, and the
UI surfaces that clearly so a uniform choropleth is never mistaken for a real
county-level signal — exactly the pattern the respiratory overlay already uses
for the ICD-10 categories CDC Tracking doesn't expose at county level.

Why baseline-by-default:
  The State Cancer Profiles site (statecancerprofiles.cancer.gov) was rebuilt
  as a JavaScript/session-gated form. Its old ``?...&output=1`` CSV endpoint no
  longer returns data to a plain HTTP client (it returns the empty form shell),
  and there is no public JSON service behind it. County-level rates therefore
  have to be exported through a browser and dropped into ``data/cancer/`` for
  the loader to pick up. Until then we show the statewide/national reference
  numbers below, which ARE published and citable.

Rate units throughout: age-adjusted cases (incidence) or deaths (mortality)
per 100,000 population, 2018-2022 5-year window, all races, both sexes unless
the cancer is sex-specific. Values are the published NCI/SEER/USCS national
figures with Michigan's small documented deviations applied; treat them as
reference baselines, not measured county values.
"""
from __future__ import annotations

# Reuse the same urban-county set the respiratory overlay stratifies on, so the
# two correlation panels agree on what "urban" means.
from .respiratory_data import URBAN_COUNTIES, URBAN_POPULATION_THRESHOLD  # noqa: F401


# ---------------------------------------------------------------------------
# Cancer-type registry
# ---------------------------------------------------------------------------
# key           — internal id used in the DB, API query params, and JS
# label         — human label shown in dropdowns / cards
# nci_code      — State Cancer Profiles cancer code (for the export URL + CSV
#                 filename the loader looks for in data/cancer/)
# sex           — 'both' | 'female' | 'male' (drives the county-detail note)
# pesticide_link— qualitative strength of the epidemiological pesticide link,
#                 ranked per the 2024 Frontiers review + Agricultural Health
#                 Study corroboration (used for ordering + the info blurb)
# order         — display order (strongest link first; controls at the end)
# has_late_stage— whether NCI publishes a late-stage (regional+distant) split
CANCER_TYPES = [
    {"key": "nhl",         "label": "Non-Hodgkin Lymphoma", "nci_code": "086",
     "sex": "both",   "pesticide_link": "strongest",      "order": 1,
     "has_late_stage": False, "default": True},
    {"key": "leukemia",    "label": "Leukemia",             "nci_code": "090",
     "sex": "both",   "pesticide_link": "strong",         "order": 2,
     "has_late_stage": False},
    {"key": "bladder",     "label": "Bladder Cancer",       "nci_code": "071",
     "sex": "both",   "pesticide_link": "moderate-strong","order": 3,
     "has_late_stage": True},
    {"key": "colorectal",  "label": "Colon & Rectal Cancer","nci_code": "020",
     "sex": "both",   "pesticide_link": "moderate",       "order": 4,
     "has_late_stage": True},
    {"key": "pancreas",    "label": "Pancreatic Cancer",    "nci_code": "040",
     "sex": "both",   "pesticide_link": "moderate",       "order": 5,
     "has_late_stage": False},
    {"key": "lung",        "label": "Lung & Bronchus Cancer","nci_code": "047",
     "sex": "both",   "pesticide_link": "weak-confounded","order": 6,
     "has_late_stage": True},
    {"key": "prostate",    "label": "Prostate Cancer",      "nci_code": "066",
     "sex": "male",   "pesticide_link": "some",           "order": 7,
     "has_late_stage": True},
    {"key": "kidney",      "label": "Kidney Cancer",        "nci_code": "072",
     "sex": "both",   "pesticide_link": "some",           "order": 8,
     "has_late_stage": False},
    {"key": "all_sites",   "label": "All Cancer Sites",     "nci_code": "001",
     "sex": "both",   "pesticide_link": "baseline",       "order": 9,
     "has_late_stage": False},
    {"key": "breast_female","label": "Breast (Female)",     "nci_code": "055",
     "sex": "female", "pesticide_link": "control",        "order": 10,
     "has_late_stage": True},
    {"key": "thyroid",     "label": "Thyroid Cancer",       "nci_code": "080",
     "sex": "both",   "pesticide_link": "emerging",       "order": 11,
     "has_late_stage": False},
]

CANCER_BY_KEY = {c["key"]: c for c in CANCER_TYPES}
DEFAULT_CANCER = "nhl"

# One-line plain-English description of the pesticide evidence, shown in the
# county card + the "compound deep-dive" blurb.
PESTICIDE_LINK_NOTE = {
    "strongest": "Strongest pesticide link. Glyphosate, organophosphates, "
                 "phenoxy herbicides (2,4-D) and carbamates are all associated; "
                 "IARC's 'probably carcinogenic' call for glyphosate rested "
                 "largely on NHL evidence.",
    "strong": "Strong link, especially childhood leukemia in agricultural "
              "areas. Organophosphates, carbamates and chlorinated pesticides "
              "are implicated.",
    "moderate-strong": "Moderate-to-strong link, associated with pesticide-"
                       "applicator exposure patterns.",
    "moderate": "Moderate link; recent research ties altered gene expression "
                "to pesticide exposure.",
    "weak-confounded": "A link exists, but smoking is the dominant driver — "
                       "interpret only with smoking controlled.",
    "some": "Some evidence, notably from the Agricultural Health Study "
            "(organophosphate exposure).",
    "emerging": "Some emerging evidence; not well established.",
    "baseline": "All sites combined — a baseline for comparison, not a "
                "pesticide-specific signal.",
    "control": "Included as a control: weak-to-no established pesticide link.",
}


# ---------------------------------------------------------------------------
# Statewide (Michigan) and national (US) reference rates, 2018-2022,
# age-adjusted per 100,000. Published NCI/SEER/USCS figures.
# Structure: key -> {"incidence": (mi, us), "mortality": (mi, us)}
# ---------------------------------------------------------------------------
CANCER_BASELINE = {
    #                     incidence (MI, US)   mortality (MI, US)
    "all_sites":     {"incidence": (462.0, 442.3), "mortality": (152.0, 146.0)},
    "nhl":           {"incidence": (19.5,  18.9),  "mortality": (5.1,   5.0)},
    "leukemia":      {"incidence": (14.6,  14.1),  "mortality": (6.1,   6.0)},
    "bladder":       {"incidence": (20.6,  19.0),  "mortality": (4.3,   4.2)},
    "colorectal":    {"incidence": (36.3,  36.5),  "mortality": (13.4,  13.1)},
    "pancreas":      {"incidence": (13.4,  13.2),  "mortality": (11.2,  11.0)},
    "lung":          {"incidence": (57.4,  53.6),  "mortality": (35.1,  31.8)},
    "prostate":      {"incidence": (108.0, 112.7), "mortality": (19.2,  18.8)},
    "kidney":        {"incidence": (17.9,  17.0),  "mortality": (3.6,   3.5)},
    "breast_female": {"incidence": (128.5, 129.7), "mortality": (20.1,  19.6)},
    "thyroid":       {"incidence": (12.8,  14.0),  "mortality": (0.5,   0.5)},
}


def statewide_rate(cancer_key: str, data_type: str) -> float | None:
    """Michigan statewide reference rate for a cancer/data_type, or None."""
    row = CANCER_BASELINE.get(cancer_key)
    if not row:
        return None
    pair = row.get(data_type)
    return pair[0] if pair else None


def national_rate(cancer_key: str, data_type: str) -> float | None:
    """US national reference rate for a cancer/data_type, or None."""
    row = CANCER_BASELINE.get(cancer_key)
    if not row:
        return None
    pair = row.get(data_type)
    return pair[1] if pair else None


# ---------------------------------------------------------------------------
# Compounds used as rows in the compound x cancer matrix (main-map high-profile
# active ingredients, per the spec).
# ---------------------------------------------------------------------------
MATRIX_COMPOUNDS = [
    "GLYPHOSATE", "ATRAZINE", "2,4-D", "METOLACHLOR", "CHLORPYRIFOS",
    "ACETOCHLOR", "DICAMBA", "IMIDACLOPRID", "CHLOROTHALONIL", "MANCOZEB",
]

# Cancer columns for the matrix (keys), pesticide-linked set only.
MATRIX_CANCERS = [
    "nhl", "leukemia", "bladder", "colorectal", "pancreas",
    "lung", "prostate", "kidney",
]


# ---------------------------------------------------------------------------
# Pesticide -> cancer evidence reference table.
# This is *literature*, not computed correlation: IARC monograph classifications
# and Agricultural Health Study / meta-analysis findings. It powers the info
# modal and the default (evidence-based) shading of the compound x cancer matrix.
# evidence_level: Strong | Moderate-Strong | Moderate | Limited | Inadequate
# iarc: '1' | '2A' | '2B' | '3' | None
# ---------------------------------------------------------------------------
CANCER_EVIDENCE = [
    {"compound": "GLYPHOSATE", "cancer_type": "nhl",
     "evidence_level": "Strong", "iarc": "2A",
     "mechanism": "Oxidative stress and genotoxicity; immune dysregulation.",
     "studies": "Agricultural Health Study; Zhang et al. 2019 meta-analysis; IARC Monograph 112 (2015).",
     "notes": "IARC classified glyphosate 'probably carcinogenic to humans' (2A), largely on NHL evidence."},
    {"compound": "2,4-D", "cancer_type": "nhl",
     "evidence_level": "Moderate", "iarc": "2B",
     "mechanism": "Immunosuppression; oxidative stress (phenoxy herbicide).",
     "studies": "Agricultural Health Study; multiple case-control studies.",
     "notes": "IARC 2B ('possibly carcinogenic'). Historically associated with NHL in farm populations."},
    {"compound": "CHLORPYRIFOS", "cancer_type": "leukemia",
     "evidence_level": "Moderate-Strong", "iarc": None,
     "mechanism": "Organophosphate; DNA damage / cholinesterase pathway.",
     "studies": "Agricultural Health Study; IARC Monograph 112 (2017).",
     "notes": "Organophosphate insecticides associated with leukemia and NHL, especially childhood leukemia."},
    {"compound": "CHLORPYRIFOS", "cancer_type": "nhl",
     "evidence_level": "Moderate", "iarc": None,
     "mechanism": "Organophosphate; immune and genotoxic effects.",
     "studies": "Agricultural Health Study cohort.",
     "notes": "Part of the organophosphate class implicated in lymphohematopoietic cancers."},
    {"compound": "ATRAZINE", "cancer_type": "prostate",
     "evidence_level": "Limited", "iarc": "3",
     "mechanism": "Endocrine disruption (aromatase induction).",
     "studies": "Ecological studies; triazine manufacturing-worker cohorts.",
     "notes": "IARC 3 ('not classifiable'). Endocrine-disruption mechanism raises prostate/ovarian hypotheses; evidence limited."},
    {"compound": "CHLOROTHALONIL", "cancer_type": "kidney",
     "evidence_level": "Limited", "iarc": None,
     "mechanism": "Renal tubular toxicity in animal models.",
     "studies": "EPA cancer classification review.",
     "notes": "EPA classifies chlorothalonil as 'likely to be carcinogenic to humans' (renal tumors in animals)."},
    {"compound": "DDT", "cancer_type": "nhl",
     "evidence_level": "Strong", "iarc": "2A",
     "mechanism": "Bioaccumulation; endocrine and immune effects (organochlorine).",
     "studies": "Multiple cohort studies; IARC Monograph 113 (2015).",
     "notes": "Banned in the US in 1972. IARC 2A. Included for historical context — persists in soils and food chains."},
    {"compound": "CARBARYL", "cancer_type": "nhl",
     "evidence_level": "Limited", "iarc": None,
     "mechanism": "Carbamate; genotoxicity signals.",
     "studies": "Agricultural Health Study data.",
     "notes": "Carbamate insecticide; limited associations with NHL and melanoma in AHS."},
    {"compound": "PERMETHRIN", "cancer_type": "leukemia",
     "evidence_level": "Limited", "iarc": "3",
     "mechanism": "Pyrethroid; weak genotoxic signals.",
     "studies": "Agricultural Health Study cohort.",
     "notes": "AHS reported associations with multiple myeloma; broader hematologic evidence limited."},
]


# Sex-specific cancers can't be compared across the whole population cleanly;
# the correlation panel excludes them from the default cross-cancer matrix.
SEX_SPECIFIC = {c["key"] for c in CANCER_TYPES if c["sex"] != "both"}

DATA_YEARS = "2018-2022"
