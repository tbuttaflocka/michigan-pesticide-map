"""SQLite schema and helper queries for the Michigan Pesticide Heat Map."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS counties (
    fips            TEXT PRIMARY KEY,        -- 5-char state+county FIPS (e.g. 26009)
    name            TEXT NOT NULL,
    state_fips      TEXT NOT NULL,
    county_fips     TEXT NOT NULL,
    area_sq_miles   REAL
);

CREATE TABLE IF NOT EXISTS pesticide_use (
    county_fips     TEXT NOT NULL,
    compound        TEXT NOT NULL,
    year            INTEGER NOT NULL,
    epest_low_kg    REAL,
    epest_high_kg   REAL,
    PRIMARY KEY (county_fips, compound, year)
);
CREATE INDEX IF NOT EXISTS ix_use_year     ON pesticide_use(year);
CREATE INDEX IF NOT EXISTS ix_use_compound ON pesticide_use(compound);
CREATE INDEX IF NOT EXISTS ix_use_county   ON pesticide_use(county_fips);

CREATE TABLE IF NOT EXISTS pesticide_categories (
    compound        TEXT PRIMARY KEY,
    category        TEXT NOT NULL,           -- herbicide / insecticide / fungicide / growth_regulator / other
    toxicity_class  TEXT
);

CREATE TABLE IF NOT EXISTS crop_acreage (
    county_fips     TEXT NOT NULL,
    crop            TEXT NOT NULL,
    year            INTEGER NOT NULL,
    acres_harvested REAL,
    acres_planted   REAL,
    PRIMARY KEY (county_fips, crop, year)
);
CREATE INDEX IF NOT EXISTS ix_crop_county ON crop_acreage(county_fips);
CREATE INDEX IF NOT EXISTS ix_crop_year   ON crop_acreage(year);

CREATE TABLE IF NOT EXISTS registered_pesticides (
    epa_reg_number      TEXT PRIMARY KEY,
    product_name        TEXT,
    active_ingredient   TEXT,
    registrant          TEXT,
    registration_status TEXT
);

CREATE TABLE IF NOT EXISTS water_monitoring (
    station_id      TEXT PRIMARY KEY,
    station_name    TEXT,
    county_fips     TEXT,
    latitude        REAL,
    longitude       REAL,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_id       TEXT PRIMARY KEY,
    title           TEXT,
    url             TEXT,
    status          TEXT,                    -- ok / unavailable / skipped
    rows_loaded     INTEGER,
    notes           TEXT,
    last_updated    TEXT
);

-- ===== Chronic Wasting Disease (CWD) overlay =====

CREATE TABLE IF NOT EXISTS cwd_wild_deer (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    county          TEXT NOT NULL,
    county_fips     TEXT NOT NULL,
    township        TEXT,
    latitude        REAL,
    longitude       REAL,
    first_detected  TEXT,                    -- ISO date
    total_positives INTEGER DEFAULT 0,
    source          TEXT DEFAULT 'DNR',
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS ix_cwd_wild_county ON cwd_wild_deer(county_fips);

CREATE TABLE IF NOT EXISTS cwd_farmed_deer (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    county              TEXT NOT NULL,
    county_fips         TEXT NOT NULL,
    facilities_positive INTEGER DEFAULT 0,
    first_detected      TEXT,
    source              TEXT DEFAULT 'MDARD',
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS ix_cwd_farm_county ON cwd_farmed_deer(county_fips);

CREATE TABLE IF NOT EXISTS cwd_surveillance (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    county             TEXT NOT NULL,
    county_fips        TEXT NOT NULL,
    surveillance_year  INTEGER NOT NULL,
    deer_tested        INTEGER,
    positives_found    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_cwd_surv_county ON cwd_surveillance(county_fips);
CREATE INDEX IF NOT EXISTS ix_cwd_surv_year   ON cwd_surveillance(surveillance_year);

CREATE TABLE IF NOT EXISTS correlation_analysis (
    county_fips           TEXT PRIMARY KEY,
    county                TEXT NOT NULL,
    total_pesticide_kg    REAL,
    pesticide_per_sq_mile REAL,
    herbicide_kg          REAL,
    insecticide_kg        REAL,
    fungicide_kg          REAL,
    cwd_positive          INTEGER DEFAULT 0,
    cwd_positives_count   INTEGER DEFAULT 0,
    cwd_farmed_facilities INTEGER DEFAULT 0,
    deer_tested           INTEGER,
    surveillance_years    TEXT,
    area_sq_miles         REAL,
    is_urban              INTEGER DEFAULT 0,
    asthma_ed_rate        REAL,
    asthma_hosp_rate      REAL,
    copd_ed_rate          REAL,
    copd_hosp_rate        REAL,
    asthma_prevalence_pct REAL
);

-- ===== Respiratory illness overlay =====

CREATE TABLE IF NOT EXISTS respiratory_ed_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    county      TEXT NOT NULL,
    county_fips TEXT NOT NULL,
    year        INTEGER NOT NULL,
    condition   TEXT NOT NULL,         -- 'asthma' | 'copd'
    visit_count INTEGER,
    visit_rate  REAL,                  -- age-adjusted, per 10,000
    population  INTEGER,
    suppressed  INTEGER DEFAULT 0,
    source      TEXT DEFAULT 'CDC_Tracking'
);
CREATE INDEX IF NOT EXISTS ix_resp_ed_county ON respiratory_ed_visits(county_fips);
CREATE INDEX IF NOT EXISTS ix_resp_ed_year   ON respiratory_ed_visits(year);
CREATE INDEX IF NOT EXISTS ix_resp_ed_cond   ON respiratory_ed_visits(condition);

CREATE TABLE IF NOT EXISTS respiratory_hospitalizations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    county      TEXT NOT NULL,
    county_fips TEXT NOT NULL,
    year        INTEGER NOT NULL,
    condition   TEXT NOT NULL,
    hosp_count  INTEGER,
    hosp_rate   REAL,                  -- age-adjusted, per 10,000
    population  INTEGER,
    suppressed  INTEGER DEFAULT 0,
    source      TEXT DEFAULT 'CDC_Tracking'
);
CREATE INDEX IF NOT EXISTS ix_resp_h_county ON respiratory_hospitalizations(county_fips);
CREATE INDEX IF NOT EXISTS ix_resp_h_year   ON respiratory_hospitalizations(year);
CREATE INDEX IF NOT EXISTS ix_resp_h_cond   ON respiratory_hospitalizations(condition);

CREATE TABLE IF NOT EXISTS respiratory_prevalence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    county          TEXT NOT NULL,
    county_fips     TEXT NOT NULL,
    condition       TEXT NOT NULL,
    prevalence_pct  REAL,
    data_years      TEXT,
    age_group       TEXT,
    source          TEXT DEFAULT 'MDHHS_Asthma_Atlas'
);

CREATE TABLE IF NOT EXISTS respiratory_mortality (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    county      TEXT NOT NULL,
    county_fips TEXT NOT NULL,
    year        INTEGER,
    cause       TEXT,                  -- 'asthma' | 'copd' | 'all_respiratory'
    death_count INTEGER,
    death_rate  REAL,                  -- per 100,000
    source      TEXT DEFAULT 'CDC_WONDER'
);

-- ===== Water quality / pesticide contamination =====

CREATE TABLE IF NOT EXISTS water_quality_sites (
    site_id        TEXT PRIMARY KEY,
    site_name      TEXT,
    site_type      TEXT,               -- Stream / River / Lake / Well / Spring / Other
    latitude       REAL,
    longitude      REAL,
    county         TEXT,
    county_fips    TEXT,
    water_body     TEXT,
    huc8           TEXT,
    organization   TEXT,
    source         TEXT DEFAULT 'WQP'
);
CREATE INDEX IF NOT EXISTS ix_wq_site_fips ON water_quality_sites(county_fips);
CREATE INDEX IF NOT EXISTS ix_wq_site_huc  ON water_quality_sites(huc8);
CREATE INDEX IF NOT EXISTS ix_wq_site_type ON water_quality_sites(site_type);

CREATE TABLE IF NOT EXISTS water_quality_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         TEXT,
    sample_date     TEXT,
    compound        TEXT,
    result_value    REAL,
    unit            TEXT,
    detection_limit REAL,
    detected        INTEGER DEFAULT 0,
    exceeds_mcl     INTEGER DEFAULT 0,
    mcl_value       REAL,
    medium          TEXT,
    FOREIGN KEY(site_id) REFERENCES water_quality_sites(site_id)
);
CREATE INDEX IF NOT EXISTS ix_wq_res_site     ON water_quality_results(site_id);
CREATE INDEX IF NOT EXISTS ix_wq_res_compound ON water_quality_results(compound);
CREATE INDEX IF NOT EXISTS ix_wq_res_detected ON water_quality_results(detected);
CREATE INDEX IF NOT EXISTS ix_wq_res_date     ON water_quality_results(sample_date);

CREATE TABLE IF NOT EXISTS watersheds (
    huc8       TEXT PRIMARY KEY,
    name       TEXT,
    states     TEXT,
    area_sqkm  REAL
);

-- ===== Cancer incidence / mortality overlay =====

CREATE TABLE IF NOT EXISTS cancer_incidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    county          TEXT NOT NULL,
    county_fips     TEXT NOT NULL,
    cancer_type     TEXT NOT NULL,               -- 'nhl' | 'leukemia' | ...
    cancer_label    TEXT NOT NULL,               -- 'Non-Hodgkin Lymphoma'
    stage           TEXT DEFAULT 'all',          -- 'all' | 'late'
    rate            REAL,                         -- age-adjusted per 100,000 (NULL if suppressed)
    rate_lower_ci   REAL,
    rate_upper_ci   REAL,
    avg_annual_count REAL,
    ci_rank         INTEGER,
    recent_trend    TEXT,                         -- 'rising' | 'stable' | 'falling'
    trend_aapc      REAL,                         -- average annual percent change
    trend_lower_ci  REAL,
    trend_upper_ci  REAL,
    rural_urban     TEXT,                         -- 'Urban' | 'Rural'
    data_years      TEXT DEFAULT '2018-2022',
    data_type       TEXT DEFAULT 'incidence',     -- 'incidence' | 'mortality'
    source          TEXT DEFAULT 'NCI_State_Cancer_Profiles',
    suppressed      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_cancer_county ON cancer_incidence(county_fips);
CREATE INDEX IF NOT EXISTS ix_cancer_type   ON cancer_incidence(cancer_type);
CREATE INDEX IF NOT EXISTS ix_cancer_dtype  ON cancer_incidence(data_type);
CREATE INDEX IF NOT EXISTS ix_cancer_stage  ON cancer_incidence(stage);

CREATE TABLE IF NOT EXISTS cancer_pesticide_correlation (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    cancer_type             TEXT NOT NULL,
    data_type               TEXT DEFAULT 'incidence',   -- 'incidence' | 'mortality'
    pesticide_compound      TEXT,                        -- NULL for a category aggregate
    pesticide_category      TEXT,                        -- 'all'|'herbicide'|'insecticide'|'fungicide'
    pearson_r               REAL,
    pearson_p               REAL,
    spearman_r              REAL,
    spearman_p              REAL,
    slope                   REAL,
    intercept               REAL,
    n_counties              INTEGER,
    mean_rate_top_quartile  REAL,
    mean_rate_bottom_quartile REAL,
    cohort                  TEXT DEFAULT 'all',          -- 'all'|'rural_only'|'exclude_urban'
    notes                   TEXT
);
CREATE INDEX IF NOT EXISTS ix_cancer_corr_type   ON cancer_pesticide_correlation(cancer_type);
CREATE INDEX IF NOT EXISTS ix_cancer_corr_cohort ON cancer_pesticide_correlation(cohort);

CREATE TABLE IF NOT EXISTS cancer_evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    compound            TEXT NOT NULL,
    cancer_type         TEXT NOT NULL,
    evidence_level      TEXT,                    -- 'Strong'|'Moderate-Strong'|'Moderate'|'Limited'
    iarc_classification TEXT,                    -- '1'|'2A'|'2B'|'3' or NULL
    key_mechanism       TEXT,
    key_studies         TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS ix_cancer_evidence_cmp ON cancer_evidence(compound);

CREATE TABLE IF NOT EXISTS cancer_reference (
    cancer_type TEXT NOT NULL,
    data_type   TEXT NOT NULL,               -- 'incidence' | 'mortality'
    stage       TEXT DEFAULT 'all',
    mi_rate     REAL,                          -- Michigan statewide age-adjusted rate
    us_rate     REAL,                          -- US (SEER+NPCR) age-adjusted rate
    mi_trend    TEXT,
    source      TEXT DEFAULT 'NCI_State_Cancer_Profiles',
    PRIMARY KEY (cancer_type, data_type, stage)
);

-- ===== Industrial contamination overlay (Superfund / PFAS / state sites) =====

CREATE TABLE IF NOT EXISTS contamination_sites (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    site_key           TEXT UNIQUE NOT NULL,
    company            TEXT,
    site_name          TEXT NOT NULL,
    latitude           REAL NOT NULL,
    longitude          REAL NOT NULL,
    county             TEXT,
    county_fips        TEXT,
    city               TEXT,
    epa_id             TEXT,
    status             TEXT,                    -- free-text status
    status_class       TEXT,                    -- npl|proposed|deleted|state|unknown
    years_active       TEXT,
    contaminants       TEXT,                    -- JSON array
    description        TEXT,
    impact_area_miles  REAL,
    affected_waterways TEXT,                    -- JSON array
    affected_counties  TEXT,                    -- JSON array
    npl_listed         INTEGER DEFAULT 0,
    npl_date           TEXT,
    hrs_score          REAL,
    category           TEXT,                    -- chemical_manufacturing|steel|auto|mining|military|...
    source             TEXT DEFAULT 'compiled', -- compiled|EPA_SEMS_NPL
    desc_source        TEXT DEFAULT 'narrative', -- narrative (rich) | generated (from EPA fields)
    narrative          TEXT,                    -- researched story (fetched enrichment); NULL if none
    narrative_source   TEXT,                    -- hardcoded | fetched | none
    narrative_refs     TEXT                     -- JSON: [{"label":..,"url":..}] source attribution
);
CREATE INDEX IF NOT EXISTS ix_contam_county   ON contamination_sites(county_fips);
CREATE INDEX IF NOT EXISTS ix_contam_category ON contamination_sites(category);
CREATE INDEX IF NOT EXISTS ix_contam_status   ON contamination_sites(status_class);

-- ===== Wind / pesticide-drift modeling =====

CREATE TABLE IF NOT EXISTS wind_data (
    station_id         TEXT NOT NULL,
    station_name       TEXT,
    latitude           REAL,
    longitude          REAL,
    county             TEXT,
    county_fips        TEXT,
    month              INTEGER DEFAULT 0,      -- 0 = growing-season aggregate
    direction_deg      REAL,                   -- prevailing (modal) FROM direction, degrees
    avg_speed_mph      REAL,
    pct_calm           REAL,                   -- % of obs with wind < 3 mph
    direction_counts   TEXT,                   -- JSON {"N": 120, "NNE": 95, ...}
    speed_by_direction TEXT,                   -- JSON {"N": 7.2, "NNE": 6.8, ...}
    n_obs              INTEGER DEFAULT 0,
    years              TEXT,                    -- e.g. "2021-2023"
    season             TEXT DEFAULT 'growing',  -- 'growing' (Apr-Sep) or 'annual'
    PRIMARY KEY (station_id, month, season)
);
CREATE INDEX IF NOT EXISTS ix_wind_station ON wind_data(station_id);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
