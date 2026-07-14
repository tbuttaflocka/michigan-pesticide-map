"""
Static reference values for the respiratory overlay.

Live data is preferred — the loader queries the CDC EPHT API at runtime.
This module supplies:
  * URBAN_COUNTIES  — Michigan counties flagged "urban" for the scatter
                      stratification, sourced from US Census urban-area
                      thresholds applied to MI.
  * MI_STATEWIDE_BASELINE — published statewide rates from the MDHHS
                      Michigan Asthma Atlas 2019 (BRFS 2012-2016) and CDC
                      WONDER. Used as fallback annotations and for the
                      "Above / below state average" comparison shown in
                      the county detail panel.
  * SEASONAL_PATTERN — monthly multiplier curve for asthma ED visits
                      derived from MDHHS Respiratory Disease Dashboard
                      season-of-year averages (statewide aggregate).
"""

# Michigan counties classified urban (high-population, predominantly
# non-agricultural). The Detroit metro counties are the well-known asthma
# hotspots and dominate hospitalization counts; isolating them is essential
# for the urban/rural pesticide-vs-respiratory comparison.
URBAN_COUNTIES = {
    "Wayne",     # Detroit
    "Oakland",
    "Macomb",
    "Kent",      # Grand Rapids
    "Genesee",   # Flint
    "Washtenaw", # Ann Arbor
    "Ingham",    # Lansing
    "Kalamazoo",
    "Saginaw",
    "Muskegon",
}

# Published statewide reference figures (citations in code comments).
MI_STATEWIDE_BASELINE = {
    # Michigan Asthma Atlas 2019, BRFS 2012-2016
    "adult_asthma_prevalence_pct": 10.4,
    "child_asthma_prevalence_pct": 8.7,
    # MDHHS Asthma Surveillance 2019, age-adjusted, per 10,000
    "adult_asthma_hospitalization_rate": 9.7,
    "child_asthma_hospitalization_rate": 12.5,
    # CDC Tracking Network statewide rates, age-adjusted, per 10,000
    "asthma_ed_visit_rate": 56.3,
    "copd_ed_visit_rate": 25.1,
    "copd_hospitalization_rate": 33.4,
    # CDC WONDER 2018-2021 underlying-cause-of-death, per 100,000
    "respiratory_mortality_rate_per_100k": 79.3,
    "asthma_mortality_rate_per_100k": 1.1,
}

# Seasonal pattern: relative-to-mean monthly index for asthma ED visits in
# Michigan. Two well-documented peaks: a spring peak in April-May (tree/grass
# pollen) and a much larger fall peak in September-October (the "back-to-
# school" surge driven by rhinovirus). Numbers normalized so mean == 1.0.
# Source: MDHHS Asthma Surveillance season-of-year averages.
SEASONAL_PATTERN = {
    1:  0.95,  # Jan
    2:  0.93,  # Feb
    3:  1.00,  # Mar
    4:  1.05,  # Apr
    5:  1.02,  # May
    6:  0.88,  # Jun
    7:  0.86,  # Jul
    8:  0.95,  # Aug
    9:  1.28,  # Sep
    10: 1.20,  # Oct
    11: 1.00,  # Nov
    12: 0.88,  # Dec
}

# Growing-season months (April through September). Used by the seasonal
# overlap chart to draw the shaded band.
GROWING_SEASON_MONTHS = list(range(4, 10))


# ICD-10 Chapter X ranges. Used for UI legend / source labelling.
ICD10_RESP_RANGES = {
    "upper_respiratory":    "J00-J06 — Acute upper respiratory infections",
    "pneumonia_influenza":  "J09-J18 — Influenza and pneumonia",
    "acute_bronchitis":     "J20-J22 — Other acute lower respiratory infections",
    "asthma":               "J45-J46 — Asthma",
    "copd":                 "J40-J44 — Chronic obstructive pulmonary disease",
    "chemical_respiratory": "J60-J70 — Lung diseases due to external agents",
    "all_respiratory":      "J00-J99 — All respiratory diseases",
}


# Michigan statewide rates for ICD-10 categories that the CDC Tracking API
# does not expose at county level. Numbers are taken from published MDHHS
# annual health-statistics tables and CDC WONDER state-level mortality
# (2018–2022 average, age-adjusted).
#
# Units:
#   *_mortality_rate      — deaths per 100,000 population, age-adjusted
#   *_ed_rate             — ED visits per 10,000, age-adjusted
#   *_hospitalization_rate— hospitalizations per 10,000, age-adjusted
#
# When the loader has no per-county data for one of these categories, every
# Michigan county is seeded with the statewide value and the row is flagged
# `source = 'MDHHS_state_baseline'`. The UI surfaces this as
# "statewide baseline" so the user never mistakes uniform shading for a real
# county-level signal.
MI_BROADER_RESP_BASELINE = {
    "upper_respiratory_ed_rate":      105.0,   # /10k, MDHHS hospital ER survey
    "acute_bronchitis_ed_rate":        62.0,   # /10k
    "pneumonia_influenza_ed_rate":     38.5,   # /10k
    "pneumonia_influenza_mortality":   16.4,   # /100k, age-adjusted
    "chemical_respiratory_mortality":   0.4,   # /100k — rare (J60-J70)
    "all_respiratory_mortality":       78.2,   # /100k — sum of all J-codes
}


# Population threshold used to flag a county "urban" on the scatter plot.
URBAN_POPULATION_THRESHOLD = 100_000
