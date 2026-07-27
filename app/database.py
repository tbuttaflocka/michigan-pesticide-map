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

CREATE TABLE IF NOT EXISTS data_sources (
    source_id       TEXT PRIMARY KEY,
    title           TEXT,
    url             TEXT,
    status          TEXT,                    -- ok / unavailable / skipped / reference / baseline / compiled
    rows_loaded     INTEGER,
    notes           TEXT,
    last_updated    TEXT,
    -- ---- provenance / freshness (written by refresh_data.py) ----
    coverage_start          TEXT,            -- earliest data point covered (e.g. "1992" or "2018-01")
    coverage_end            TEXT,            -- latest data point covered
    refresh_status          TEXT,            -- success / failed / partial / skipped / never
    refresh_interval_months INTEGER,         -- expected refresh cadence (staleness threshold)
    last_success            TEXT,            -- ISO timestamp of last successful refresh
    last_attempt            TEXT             -- ISO timestamp of last refresh attempt
);

CREATE TABLE IF NOT EXISTS correlation_analysis (
    county_fips           TEXT PRIMARY KEY,
    county                TEXT NOT NULL,
    total_pesticide_kg    REAL,
    pesticide_per_sq_mile REAL,
    herbicide_kg          REAL,
    insecticide_kg        REAL,
    fungicide_kg          REAL,
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
    exceeds_mcl       INTEGER DEFAULT 0,   -- above human drinking-water MCL
    mcl_value         REAL,                -- the MCL compared against (µg/L)
    exceeds_benchmark INTEGER DEFAULT 0,   -- above aquatic-life benchmark (ecological)
    benchmark_value   REAL,                -- the aquatic-life benchmark compared against (µg/L)
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

-- ===== Landfills & waste facilities overlay (Michigan EGLE) =====
-- Live from EGLE Materials Management Open Data (ArcGIS): Part 115 solid-waste
-- landfills (Type II municipal, Type III industrial / C&D / coal-ash) + the
-- disposal-capable Part 111 hazardous-waste TSDFs. The Part 115 open-data layer
-- is ACTIVE-only; closed / post-closure / pre-regulation landfills are not in it
-- (many surface instead in contamination_sites). tri_* / contam_site_key carry
-- cross-links to the TRI and Superfund overlays, matched at load time so a
-- landfill that also self-reports toxic releases or is a contaminated site links
-- straight to those records. Monitoring RESULTS are never stored here — they are
-- FOIA-only (see app/landfill_data.py).
CREATE TABLE IF NOT EXISTS landfill_sites (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    site_key          TEXT UNIQUE NOT NULL,   -- egle:<wdsid> or tsdf:<siteid>
    program           TEXT,                   -- part115 | part111
    name              TEXT NOT NULL,          -- specific facility name
    operator          TEXT,                   -- legal / operating entity
    category          TEXT,                   -- msw|industrial|cnd|coal_ash|hazardous
    type_label        TEXT,                   -- plain-language type
    facility_types    TEXT,                   -- JSON array of raw EGLE disposal-area types
    status_class      TEXT,                   -- active|closed|post_closure|unknown
    status_label      TEXT,                   -- raw disposalareastatus text
    license_id        TEXT,                   -- EGLE wdsid / site id
    alt_id            TEXT,                   -- extra facility identifier (Part 111: EGLE WDS ID)
    alt_id_label      TEXT,                   -- human label for alt_id
    address           TEXT,
    city              TEXT,
    zip               TEXT,
    county            TEXT,
    county_fips       TEXT,
    latitude          REAL NOT NULL,
    longitude         REAL NOT NULL,
    egle_url          TEXT,                   -- EGLE facility record link
    federal_regulated INTEGER DEFAULT 0,      -- Part 111 FederallyRegulatedTSD
    commercial        INTEGER DEFAULT 0,      -- accepts offsite hazardous waste
    -- cross-links (matched at load time) to the app's other overlays --
    tri_facility_id   TEXT,                   -- tri_facility.facility_id
    tri_total_lbs     REAL,                   -- matched facility latest-year total
    tri_year          INTEGER,
    contam_site_key   TEXT,                   -- contamination_sites.site_key
    contam_status     TEXT,                   -- matched contamination status label
    source            TEXT DEFAULT 'EGLE_MMD'
);
CREATE INDEX IF NOT EXISTS ix_landfill_county ON landfill_sites(county_fips);
CREATE INDEX IF NOT EXISTS ix_landfill_cat    ON landfill_sites(category);

-- ===== Golf courses (OpenStreetMap) =====
-- Locations of Michigan golf courses, a pesticide-intensive turf land use that
-- the USGS EPest agricultural layer excludes entirely. We map WHERE intensive
-- turf pesticide use happens; actual per-course amounts are NOT public in
-- Michigan and are never stored or estimated (see app/golf_data.py). Geometry is
-- the OSM course footprint (GeoJSON) where available; acres is derived from that
-- polygon, never guessed. Cross-refs to county ag-use and nearby water
-- monitoring are context only — never attributed to the course.
CREATE TABLE IF NOT EXISTS golf_courses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    course_key        TEXT UNIQUE NOT NULL,   -- osm:way/<id> or osm:relation/<id>
    osm_type          TEXT,                   -- way | relation
    osm_id            INTEGER,
    name              TEXT NOT NULL,
    operator          TEXT,                   -- operator/owner string, if tagged
    ownership_class   TEXT,                   -- municipal | private | unknown
    ownership_label   TEXT,                   -- plain-language ownership description
    access            TEXT,                   -- raw OSM access tag (private/public/…)
    address           TEXT,
    city              TEXT,
    zip               TEXT,
    county            TEXT,
    county_fips       TEXT,
    latitude          REAL NOT NULL,          -- representative point (polygon centroid)
    longitude         REAL NOT NULL,
    acres             REAL,                   -- from OSM polygon; NULL if point-only
    has_polygon       INTEGER DEFAULT 0,
    geometry          TEXT,                   -- GeoJSON geometry (Polygon/MultiPolygon)
    website           TEXT,
    -- cross-references (context only; NOT causal) --
    high_ag_use       INTEGER DEFAULT 0,      -- county in top quartile of ag pesticide use
    county_ag_rank    INTEGER,                -- 1 = highest-use county (latest EPest year)
    county_ag_total_lbs REAL,                 -- county's latest-year ag pesticide total (lbs)
    water_site_id     TEXT,                   -- nearest water-monitoring site w/ turf-compound detection
    water_site_name   TEXT,
    water_site_km     REAL,
    water_compounds   TEXT,                   -- JSON list of turf-associated compounds detected there
    source            TEXT DEFAULT 'OSM'
);
CREATE INDEX IF NOT EXISTS ix_golf_county ON golf_courses(county_fips);
CREATE INDEX IF NOT EXISTS ix_golf_owner  ON golf_courses(ownership_class);

-- ===== PFAS (Michigan PFAS Action Response Team / EGLE, live) =====
-- One row per mapped PFAS feature across all five MPART feeds, discriminated by
-- `kind`. Confirmed Sites vs Areas of Interest (AOI = area under investigation
-- where the source hasn't been determined) are distinguished by kind. Sampling
-- results are aggregated to their location (max concentration + latest date);
-- Public Water Supply results are HEXBINS (polygons), never precise locations,
-- by EGLE's design. No concentration or site is ever fabricated. Sites/AOIs are
-- cross-linked (name-token + proximity) to the app's Superfund/TRI/landfill data.
CREATE TABLE IF NOT EXISTS pfas_features (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_key       TEXT UNIQUE NOT NULL,   -- <kind>:<source id>
    kind              TEXT NOT NULL,          -- site|aoi|surface_water|pws|fish|potw
    name              TEXT,
    site_type         TEXT,                   -- Type (Landfill/Airport/…) or waterbody
    address           TEXT,
    city              TEXT,
    zip               TEXT,
    county            TEXT,
    county_fips       TEXT,
    latitude          REAL,                   -- representative point (hexbin centroid for pws)
    longitude         REAL,
    geometry          TEXT,                   -- GeoJSON polygon for pws hexbins; NULL for points
    residential_wells TEXT,                   -- site/aoi: whether residential wells were sampled
    hyperlink         TEXT,                   -- site investigation summary / MiEnviro / Eat-Safe-Fish
    site_lead         TEXT,
    site_lead_email   TEXT,
    site_lead_phone   TEXT,
    max_ppt           REAL,                   -- key concentration (surface_water/pws), ppt/ng-L
    sample_date       TEXT,                   -- latest sample date, ISO
    summary           TEXT,                   -- short human-readable key figures
    props             TEXT,                   -- JSON: kind-specific fields
    contam_site_key   TEXT,                   -- cross-link: contamination_sites.site_key
    tri_facility_id   TEXT,                   -- cross-link: tri_facility.facility_id
    landfill_site_key TEXT,                   -- cross-link: landfill_sites.site_key
    source            TEXT DEFAULT 'EGLE_MPART'
);
CREATE INDEX IF NOT EXISTS ix_pfas_kind   ON pfas_features(kind);
CREATE INDEX IF NOT EXISTS ix_pfas_county ON pfas_features(county_fips);

-- ===== Underground Storage Tanks (EGLE RRD, regularly updated) =====
-- The most common near-home contamination source. CRITICAL distinction, carried
-- in `category`: a licensed Part 211 tank (a working gas station, not
-- necessarily a problem) must NEVER look like a confirmed Part 213 release.
--   leaking_open   — Open_Release > 0: a confirmed leak still under corrective action
--   leaking_closed — Part 213 with releases, all closed/remediated
--   licensed       — Part 211, no reported release
-- Point locations vary in accuracy (some geocoded by address, not GPS) — the
-- horizontal_accuracy / collection_method fields are surfaced honestly.
CREATE TABLE IF NOT EXISTS ust_sites (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    site_key               TEXT UNIQUE NOT NULL,   -- ust:<FacilityID or OBJECTID>
    facility_id            TEXT,
    facility_name          TEXT,
    category               TEXT NOT NULL,          -- leaking_open|leaking_closed|licensed
    regulatory_program     INTEGER,                -- 211 (LARA licensed) | 213 (EGLE leaking)
    address                TEXT,
    city                   TEXT,
    zip                    TEXT,
    county                 TEXT,
    county_fips            TEXT,
    latitude               REAL NOT NULL,
    longitude              REAL NOT NULL,
    project_manager        TEXT,
    work_unit              TEXT,                   -- EGLE district / work unit
    total_tanks            INTEGER,
    active_tanks           INTEGER,
    total_release          INTEGER,
    open_release           INTEGER,
    closed_release         INTEGER,
    release_status         TEXT,
    current_classification TEXT,                   -- EGLE risk classification (Class 1..4, etc.)
    highest_classification TEXT,
    risk_condition         TEXT,
    has_bea                TEXT,
    horizontal_accuracy    REAL,                   -- metres (larger = less precise)
    collection_method      TEXT,                   -- short label (GPS vs address-matched)
    address_matched        INTEGER DEFAULT 0,      -- 1 if located by address match, not GPS
    reference_point        TEXT,
    facility_url           TEXT,                   -- RIDE / EGLE record link if any
    last_updated           TEXT,
    contam_site_key        TEXT,                   -- cross-link: contamination_sites.site_key
    source                 TEXT DEFAULT 'EGLE_RRD'
);
CREATE INDEX IF NOT EXISTS ix_ust_category ON ust_sites(category);
CREATE INDEX IF NOT EXISTS ix_ust_county   ON ust_sites(county_fips);

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

-- ===== EPA Toxics Release Inventory (TRI) — active industrial toxic releases =====
-- Complements the (legacy) contamination/Superfund layer: TRI is what active,
-- covered industrial & federal facilities SELF-REPORT releasing each year under
-- EPCRA. All quantities are already in POUNDS (TRI's native unit), so they are
-- stored as *_lbs and pass through the kg->lbs response walker untouched.

CREATE TABLE IF NOT EXISTS tri_facility (
    facility_id      TEXT PRIMARY KEY,        -- EPA TRI Facility ID (trifd)
    facility_name    TEXT NOT NULL,
    street_address   TEXT,
    city             TEXT,
    county           TEXT,
    county_fips      TEXT,
    latitude         REAL,
    longitude        REAL,
    parent_company   TEXT,
    naics_code       TEXT,                    -- primary 6-digit NAICS
    industry_sector  TEXT,                    -- EPA industry-sector label (plain language)
    federal_facility INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_tri_fac_county ON tri_facility(county_fips);

CREATE TABLE IF NOT EXISTS tri_release (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id      TEXT NOT NULL,
    year             INTEGER NOT NULL,
    chemical         TEXT NOT NULL,
    cas              TEXT,
    is_pfas          INTEGER DEFAULT 0,
    is_carcinogen    INTEGER DEFAULT 0,
    fugitive_air_lbs REAL DEFAULT 0,
    stack_air_lbs    REAL DEFAULT 0,
    air_lbs          REAL DEFAULT 0,          -- fugitive + stack
    water_lbs        REAL DEFAULT 0,
    underground_lbs  REAL DEFAULT 0,
    land_lbs         REAL DEFAULT 0,          -- on-site total minus air/water/underground
    total_lbs        REAL DEFAULT 0,          -- on-site release total (all pathways)
    FOREIGN KEY (facility_id) REFERENCES tri_facility(facility_id)
);
CREATE INDEX IF NOT EXISTS ix_tri_rel_fac  ON tri_release(facility_id);
CREATE INDEX IF NOT EXISTS ix_tri_rel_year ON tri_release(year);
CREATE INDEX IF NOT EXISTS ix_tri_rel_chem ON tri_release(chemical);

-- Cached PubChem enrichment for every chemical/compound that appears in the
-- data (pesticide compounds, TRI chemicals, water-quality detections). Keyed by
-- the upper-cased name so popups resolve instantly with no live API call.
-- Populated by enrich_chemicals.py / app.chemical_reference.
CREATE TABLE IF NOT EXISTS chemical_reference (
    name_key           TEXT PRIMARY KEY,   -- UPPER(name) lookup key
    name               TEXT,               -- display name as it appears in data
    cas                TEXT,               -- CAS number (from data or PubChem)
    pubchem_cid        INTEGER,            -- PubChem Compound ID
    description        TEXT,               -- plain-language summary from PubChem
    description_source TEXT,               -- attribution for the description
    molecular_formula  TEXT,
    molecular_weight   REAL,
    iupac_name         TEXT,
    synonyms           TEXT,               -- JSON array of a few common synonyms
    source             TEXT,               -- 'pubchem' | 'none'
    fetched_at         TEXT                -- ISO timestamp of the fetch
);
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
