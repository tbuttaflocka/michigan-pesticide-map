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

-- USGS state-level pesticide use by major crop or crop group (DOI
-- 10.5066/P900FZ6Y). One row per state x compound x crop-group x year. The
-- source publishes crop use in a wide layout (one column per crop group) with
-- the EPest-LOW and EPest-HIGH methods in two separate files; we unpivot to
-- long form and keep both estimates in their own columns (never averaged).
-- NULL in an estimate = "no use estimated"; 0 = estimated but below the
-- reporting threshold. Compound / crop values are stored exactly as published.
CREATE TABLE IF NOT EXISTS pesticide_use_by_crop (
    state_fips      TEXT NOT NULL,          -- state FIPS (Michigan = 26)
    state           TEXT,                   -- state name as published
    compound        TEXT NOT NULL,          -- pesticide active-ingredient common name
    crop            TEXT NOT NULL,          -- crop group as published (e.g. 'Corn',
                                            --   'Vegetables_and_fruit', 'Other_crops')
    year            INTEGER NOT NULL,
    epest_low_kg    REAL,                   -- EPest LOW-method estimate, kg
    epest_high_kg   REAL,                   -- EPest HIGH-method estimate, kg
    PRIMARY KEY (state_fips, compound, crop, year)
);
CREATE INDEX IF NOT EXISTS ix_pubc_compound ON pesticide_use_by_crop(compound);
CREATE INDEX IF NOT EXISTS ix_pubc_crop     ON pesticide_use_by_crop(crop);
CREATE INDEX IF NOT EXISTS ix_pubc_year     ON pesticide_use_by_crop(year);

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
    -- optional curated narrative layer (app/pfas_narratives.py), attached to the
    -- matching live MPART site/AOI record at load time; adds history + severity
    -- context on top of the terse live feed. NULL for records with no narrative.
    narrative         TEXT,                   -- researched prose (history + source)
    narrative_title   TEXT,                   -- short heading for the narrative block
    narrative_facts   TEXT,                   -- JSON {peaks:[], advisories:[], status}
    narrative_refs    TEXT,                   -- JSON [{label,url}] source attribution
    narrative_source  TEXT,                   -- 'curated' | NULL
    source            TEXT DEFAULT 'EGLE_MPART'
);
CREATE INDEX IF NOT EXISTS ix_pfas_kind   ON pfas_features(kind);
CREATE INDEX IF NOT EXISTS ix_pfas_county ON pfas_features(county_fips);

-- ===== EPA air toxics risk (NATA / AirToxScreen), census-tract level =====
-- Modeled cancer-risk SCREENING estimates (chance-in-a-million, 70-yr outdoor
-- lifetime). One row per Michigan census tract. `total_risk` is computed as the
-- sum of the source-category fields (== sum of pollutant fields); the service's
-- own coarse total column is NOT trusted. `sources` and `pollutants` are JSON so
-- the popup can show the source-driver breakdown and top contributing chemicals.
CREATE TABLE IF NOT EXISTS airtoxics_tracts (
    tract_geoid   TEXT PRIMARY KEY,       -- 11-digit census tract GEOID
    county_fips   TEXT,                   -- 5-digit (STCOFIPS) -> counties.fips
    county_name   TEXT,
    population    INTEGER,                 -- POP2010 (tract population)
    total_risk    REAL,                    -- total cancer risk, in a million
    sources       TEXT,                    -- JSON {key: risk} for the 8 categories
    pollutants    TEXT,                    -- JSON [[name, risk], ...] top contributors
    geometry      TEXT                     -- GeoJSON Polygon/MultiPolygon (simplified)
);
CREATE INDEX IF NOT EXISTS ix_airtox_county ON airtoxics_tracts(county_fips);

-- Tiny key/value companion for assessment-wide reference numbers (national and
-- Michigan average tract risk) so popups can say "vs the national/Michigan avg".
CREATE TABLE IF NOT EXISTS airtoxics_stats (
    key   TEXT PRIMARY KEY,
    value REAL
);

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

-- ===== Searchable places (US Census TIGER gazetteer) =====
-- Cities, villages, townships, CDPs and ZIP-code areas so the search box can
-- find a location the way people actually think of it (most don't think in
-- counties, and Michigan township identity is strong). Every row carries its
-- `kind` and parent county so the UI can disambiguate Michigan's many duplicate
-- names — the canonical trap being Oscoda County (inland, NE Lower Peninsula)
-- vs Oscoda Township (Iosco County, on the Lake Huron shore; Wurtsmith/PFAS).
-- `lat`/`lng` is the Census internal point (guaranteed inside the polygon); the
-- bbox is derived from land area purely to frame a zoom-to-place. `counties` is
-- a JSON name array only when a place spans more than one county. Loaded once
-- from the tiny, stable gazetteer text files — no live API call per keystroke.
CREATE TABLE IF NOT EXISTS places (
    place_id     TEXT PRIMARY KEY,   -- 'place:2661320' | 'cousub:2606961340' | 'zcta:48750'
    name         TEXT NOT NULL,      -- display name, type suffix stripped ('Oscoda')
    name_full    TEXT,               -- original gazetteer name ('Oscoda charter township')
    kind         TEXT NOT NULL,      -- city | village | township | cdp | zcta
    county_fips  TEXT,               -- primary (containing) county FIPS
    county_name  TEXT,               -- primary county name
    counties     TEXT,               -- JSON [names] when the place spans >1 county, else NULL
    lat          REAL NOT NULL,      -- Census internal point (inside the polygon)
    lng          REAL NOT NULL,
    min_lat      REAL,               -- approx bbox (from land area) for zoom-to-place
    min_lng      REAL,
    max_lat      REAL,
    max_lng      REAL,
    area_sq_mi   REAL
);
CREATE INDEX IF NOT EXISTS ix_places_name ON places(name);
CREATE INDEX IF NOT EXISTS ix_places_kind ON places(kind);

-- ===== EPA ECHO enforcement & compliance (All-Data REST web service) =====
-- One row per Michigan regulated facility from EPA's Enforcement and Compliance
-- History Online. Covers Clean Air Act, Clean Water Act, RCRA and Safe Drinking
-- Water Act: current compliance status, significant-noncompliance / high-priority
-- flags, inspection counts + dates, formal enforcement action counts, and
-- penalties. Status strings are stored EXACTLY as EPA returns them
-- ("No Violation Identified" / "Violation Identified" / "Significant Violation" /
-- NULL) — never recoded, ranked, or collapsed. Compliance history is the trailing
-- 12 federal-fiscal-year quarters (3 years); ECHO lags source databases by up to
-- three months and refreshes weekly except SDWA (quarterly). Data quality prior
-- to Nov 2000 is, per EPA, "unknown", and violation flags are alleged not
-- adjudicated. The matched_* columns hold the subset of each space-delimited ECHO
-- program-ID list that EXACTLY matches one of our existing records (ID join only,
-- never name matching): TRI_IDS->tri_facility.facility_id,
-- SEMS_IDS->contamination_sites.epa_id, RCRA_IDS->landfill_sites.license_id
-- (Part 111 TSDFs only; Part 115 solid-waste landfills carry no FRS/RCRA ID and
-- are intentionally left unjoined).
CREATE TABLE IF NOT EXISTS echo_facilities (
    registry_id              TEXT PRIMARY KEY,  -- REGISTRY_ID (FRS Registry ID)
    facility_name            TEXT,              -- FAC_NAME
    street                   TEXT,              -- FAC_STREET
    city                     TEXT,              -- FAC_CITY
    state                    TEXT,              -- FAC_STATE
    zip                      TEXT,              -- FAC_ZIP
    county                   TEXT,              -- FAC_COUNTY (raw, as EPA returns)
    county_fips              TEXT,              -- derived from county name
    latitude                 REAL,              -- FAC_LAT
    longitude                REAL,              -- FAC_LONG
    -- current compliance status — stored verbatim, no recoding --
    compliance_status        TEXT,              -- FAC_COMPLIANCE_STATUS
    caa_compliance_status    TEXT,              -- CAA_COMPLIANCE_STATUS
    cwa_compliance_status    TEXT,              -- CWA_COMPLIANCE_STATUS
    rcra_compliance_status   TEXT,              -- RCRA_COMPLIANCE_STATUS
    sdwa_compliance_status   TEXT,              -- SDWA_COMPLIANCE_STATUS
    snc_flag                 TEXT,              -- FAC_SNC_FLG (Y/N)
    caa_hpv_flag             TEXT,              -- CAA_HPV_FLAG (Y/N)
    programs_with_snc        TEXT,              -- FAC_PROGRAMS_WITH_SNC
    -- inspections --
    inspection_count         INTEGER,           -- FAC_INSPECTION_COUNT
    date_last_inspection     TEXT,              -- FAC_DATE_LAST_INSPECTION (MM/DD/YYYY as returned)
    days_last_inspection     INTEGER,           -- FAC_DAYS_LAST_INSPECTION
    -- penalties --
    penalty_count            INTEGER,           -- FAC_PENALTY_COUNT
    total_penalties          TEXT,              -- FAC_TOTAL_PENALTIES (currency string as returned, e.g. "$0")
    total_penalties_usd      REAL,              -- numeric parse of total_penalties (derived convenience)
    date_last_penalty        TEXT,              -- FAC_DATE_LAST_PENALTY
    -- formal enforcement action counts --
    formal_action_count      INTEGER,           -- FAC_FORMAL_ACTION_COUNT
    caa_formal_action_count  INTEGER,           -- CAA_FORMAL_ACTION_COUNT
    cwa_formal_action_count  INTEGER,           -- CWA_FORMAL_ACTION_COUNT
    rcra_formal_action_count INTEGER,           -- RCRA_FORMAL_ACTION_COUNT
    sdwa_formal_action_count INTEGER,           -- SDWA_FORMAL_ACTION_COUNT
    -- timeframe --
    qtrs_with_nc             INTEGER,           -- FAC_QTRS_WITH_NC
    compliance_history_3yr   TEXT,              -- FAC_3YR_COMPLIANCE_HISTORY (12-quarter string)
    -- raw program-ID lists (space-delimited, exactly as returned) --
    tri_ids                  TEXT,              -- TRI_IDS
    sems_ids                 TEXT,              -- SEMS_IDS
    rcra_ids                 TEXT,              -- RCRA_IDS
    npdes_ids                TEXT,              -- NPDES_IDS
    -- ID-join results: matched subset present in our data (NULL if none) --
    matched_tri_ids          TEXT,              -- ⊆ TRI_IDS in tri_facility.facility_id
    matched_sems_ids         TEXT,              -- ⊆ SEMS_IDS in contamination_sites.epa_id
    matched_rcra_ids         TEXT,              -- ⊆ RCRA_IDS in landfill_sites.license_id (part111)
    source                   TEXT DEFAULT 'EPA_ECHO'
);
CREATE INDEX IF NOT EXISTS ix_echo_county   ON echo_facilities(county_fips);
CREATE INDEX IF NOT EXISTS ix_echo_snc      ON echo_facilities(snc_flag);
CREATE INDEX IF NOT EXISTS ix_echo_tri_m    ON echo_facilities(matched_tri_ids);
CREATE INDEX IF NOT EXISTS ix_echo_sems_m   ON echo_facilities(matched_sems_ids);
CREATE INDEX IF NOT EXISTS ix_echo_rcra_m   ON echo_facilities(matched_rcra_ids);

-- ===== EGLE oil, gas & mineral wells (GrmdOpenData ArcGIS, layer 10) =====
-- Surface (wellhead) locations for ALL Michigan oil/gas/mineral wells (~92,577),
-- refreshed weekly from EGLE's GRMD RBDMS database. Fields are stored as EGLE
-- publishes them — WellType/WellStatus values are kept VERBATIM (never recoded or
-- grouped). There is NO hydraulic-fracturing flag and NO fluid-volume field here;
-- High Volume Hydraulic Fracturing is FracFocus-only (see fracfocus_* below) and
-- EGLE's HVHF map is a separate PDF. county_fips is DERIVED as '26' + the
-- published 3-digit County_fips purely for county aggregation (a code transform);
-- there is NO facility-level identifier shared with tri_facility /
-- contamination_sites / landfill_sites / echo_facilities, so no join to those.
CREATE TABLE IF NOT EXISTS oil_gas_wells (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pkey                INTEGER,   -- RBDMS PKey (row identifier)
    well_id             TEXT,      -- WellID
    api_num             TEXT,      -- 14-digit API number (join key to FracFocus)
    permit_number       TEXT,      -- PermitNumber
    well_name           TEXT,      -- WellName
    well_number         TEXT,      -- WellNumber
    well_name_full      TEXT,      -- WellNameFull
    company_name        TEXT,      -- CompanyName (operator)
    well_type           TEXT,      -- WellType (VERBATIM)
    top_well_type       TEXT,      -- TopWellType (VERBATIM)
    well_status         TEXT,      -- WellStatus (VERBATIM)
    top_well_status     TEXT,      -- TopWellStatus (VERBATIM)
    slant               TEXT,      -- Slant
    wellbore_type       TEXT,      -- WellboreType
    dtd                 REAL,      -- DTD (drilled total depth, ft)
    tvd                 REAL,      -- TVD (true vertical depth, ft)
    producing_formation TEXT,      -- ProducingFormation
    prod_formation_code TEXT,      -- ProdFormationCode
    field_name          TEXT,      -- FieldName
    field_type          TEXT,      -- FieldType
    permit_date         TEXT,      -- PermitDate (ISO yyyy-mm-dd)
    plugging_date       TEXT,      -- PluggingDate (ISO yyyy-mm-dd)
    concentration_h2s   INTEGER,   -- Concentration_H2S
    county_fips3        TEXT,      -- County_fips as published (3-digit)
    county_fips         TEXT,      -- derived 5-digit '26'+County_fips (county aggregation)
    longitude           REAL,      -- X (WGS84)
    latitude            REAL,      -- Y (WGS84)
    source              TEXT DEFAULT 'EGLE_GRMD'
);
CREATE INDEX IF NOT EXISTS ix_ogw_api    ON oil_gas_wells(api_num);
CREATE INDEX IF NOT EXISTS ix_ogw_county ON oil_gas_wells(county_fips);
CREATE INDEX IF NOT EXISTS ix_ogw_type   ON oil_gas_wells(well_type);
CREATE INDEX IF NOT EXISTS ix_ogw_status ON oil_gas_wells(well_status);

-- ===== FracFocus hydraulic-fracturing chemical disclosures (Michigan) =====
-- Michigan disclosures from the FracFocus national bulk download. MI required
-- disclosure only for High Volume Hydraulic Fracturing (100,000+ gal) from April
-- 2015, so this is the ~30 HVHF wells — NOT the 12,000+ shallow Antrim fracks.
-- Joined to oil_gas_wells by exact api_num = APINumber (matched_api_num, NULL when
-- no well matches). Ingredient rows preserve trade-secret masking VERBATIM
-- ('Proprietary' / 'Trade Secret' / 'TS' / 'Confidential' / 'CBI' in place of a
-- CAS number); is_masked is an additive flag for reporting the masked share and
-- never replaces or drops the published value.
CREATE TABLE IF NOT EXISTS fracfocus_disclosures (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    disclosure_key          TEXT UNIQUE,  -- FracFocus disclosure id (dedupe key)
    api_number              TEXT,         -- APINumber
    operator_name           TEXT,         -- OperatorName
    well_name               TEXT,         -- WellName
    latitude                REAL,         -- Latitude
    longitude               REAL,         -- Longitude
    state_name              TEXT,         -- StateName
    county_name             TEXT,         -- CountyName
    total_base_water_volume REAL,         -- TotalBaseWaterVolume (gallons)
    tvd                     REAL,         -- TVD
    job_start_date          TEXT,         -- JobStartDate
    job_end_date            TEXT,         -- JobEndDate
    matched_api_num         TEXT,         -- oil_gas_wells.api_num exact match, else NULL
    source                  TEXT DEFAULT 'FracFocus'
);
CREATE INDEX IF NOT EXISTS ix_ff_api ON fracfocus_disclosures(api_number);

CREATE TABLE IF NOT EXISTS fracfocus_ingredients (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    disclosure_key   TEXT,       -- -> fracfocus_disclosures.disclosure_key
    api_number       TEXT,       -- APINumber (denormalized)
    ingredient_name  TEXT,       -- IngredientName (VERBATIM; may be 'Proprietary' etc.)
    cas_number       TEXT,       -- CASNumber (VERBATIM; may be 'Trade Secret'/'TS'/'CBI')
    percent_hf_job   REAL,       -- PercentHFJob
    mass_ingredient  REAL,       -- MassIngredient
    is_masked        INTEGER DEFAULT 0   -- 1 if CAS/name is a trade-secret placeholder
);
CREATE INDEX IF NOT EXISTS ix_ffi_disc ON fracfocus_ingredients(disclosure_key);
CREATE INDEX IF NOT EXISTS ix_ffi_cas  ON fracfocus_ingredients(cas_number);

-- ===== Power plants — EIA Form 860 inventory + EPA CAMD emissions =====
-- EIA-860 (via EIA API v2) is the plant/generator INVENTORY: every Michigan
-- generator at a plant >=1 MW, all fuels incl nuclear / hydro / wind / solar /
-- storage. plant_code is the EIA Plant Code = EPA ORIS code (the exact CAMD join
-- key). One row per generator (latest monthly snapshot). in_camd is set at load
-- time from the exact ORIS match to a CAMD facility (no name matching).
CREATE TABLE IF NOT EXISTS power_plants (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_code            TEXT,     -- EIA plantid = ORIS code (join key)
    plant_name            TEXT,     -- plantName
    generator_id          TEXT,     -- generatorid
    entity_name           TEXT,     -- entityName (operator)
    county                TEXT,
    latitude              REAL,
    longitude             REAL,
    energy_source_code    TEXT,     -- energy_source_code (e.g. WAT, NG, SUB)
    energy_source_desc    TEXT,     -- energy-source-desc (Water, Natural Gas...)
    technology            TEXT,     -- technology
    prime_mover_code      TEXT,     -- prime_mover_code
    nameplate_capacity_mw REAL,     -- nameplate-capacity-mw
    status                TEXT,     -- status (OP/SB/OS/...)
    status_description    TEXT,     -- statusDescription (Operating/Standby/...)
    operating_year_month  TEXT,     -- operating-year-month
    planned_retirement    TEXT,     -- planned-retirement-year-month
    sector_name           TEXT,     -- sectorName
    balancing_authority   TEXT,     -- balancing_authority_code
    period                TEXT,     -- EIA snapshot period (YYYY-MM)
    in_camd               INTEGER DEFAULT 0,   -- 1 if plant_code matched a CAMD ORIS
    source                TEXT DEFAULT 'EIA_860'
);
CREATE INDEX IF NOT EXISTS ix_pp_code   ON power_plants(plant_code);
CREATE INDEX IF NOT EXISTS ix_pp_fuel   ON power_plants(energy_source_desc);
CREATE INDEX IF NOT EXISTS ix_pp_incamd ON power_plants(in_camd);

-- CAMD annual apportioned emissions, unit x year. SO2/NOx/CO2 are CEMS STACK
-- MEASUREMENTS under 40 CFR Part 75 (with Part 75 missing-data substitution when
-- a monitor is offline; some smaller units report calculated Appendix D/E values
-- rather than CEMS). Values stored verbatim. Mercury MASS is NOT in this dataset
-- (only hg_control_info) — Hg is MATS-only, from 2015, reported separately.
CREATE TABLE IF NOT EXISTS power_plant_emissions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id          INTEGER,  -- ORIS (join to power_plants.plant_code)
    facility_name        TEXT,
    unit_id              TEXT,     -- unitId (e.g. '1')
    unit_id_num          INTEGER,  -- unit_id (CAMD internal integer)
    year                 INTEGER,
    so2_mass             REAL,     -- so2Mass (tons)
    so2_rate             REAL,     -- so2Rate (lb/mmBtu)
    nox_mass             REAL,     -- noxMass (tons)
    nox_rate             REAL,     -- noxRate (lb/mmBtu)
    co2_mass             REAL,     -- co2Mass (tons)
    co2_rate             REAL,     -- co2Rate (short tons/mmBtu)
    heat_input           REAL,     -- heatInput (mmBtu)
    gross_load           REAL,     -- grossLoad (MWh)
    steam_load           REAL,     -- steamLoad
    count_op_time        REAL,     -- countOpTime
    sum_op_time          REAL,     -- sumOpTime
    primary_fuel_info    TEXT,     -- primaryFuelInfo
    secondary_fuel_info  TEXT,     -- secondaryFuelInfo
    unit_type            TEXT,     -- unitType
    so2_control_info     TEXT,     -- so2ControlInfo
    nox_control_info     TEXT,     -- noxControlInfo
    pm_control_info      TEXT,     -- pmControlInfo
    hg_control_info      TEXT,     -- hgControlInfo (control only; no Hg mass here)
    program_code_info    TEXT,     -- programCodeInfo (ARP, CSAPR, MATS...)
    associated_stacks    TEXT,     -- associatedStacks
    source               TEXT DEFAULT 'EPA_CAMD'
);
CREATE INDEX IF NOT EXISTS ix_ppe_fac  ON power_plant_emissions(facility_id);
CREATE INDEX IF NOT EXISTS ix_ppe_year ON power_plant_emissions(year);

-- CAMD facility-level attributes (one row per facility, most-recent attr year).
-- This is where the lat/lon lives — it is NOT on the emissions rows. in_eia is set
-- from the exact ORIS match to an EIA plant (no name matching).
CREATE TABLE IF NOT EXISTS power_plant_camd_facilities (
    facility_id         INTEGER PRIMARY KEY,   -- ORIS
    facility_name       TEXT,
    latitude            REAL,
    longitude           REAL,
    county              TEXT,
    fips_code           TEXT,
    operating_status    TEXT,     -- operatingStatus
    owner_operator      TEXT,     -- ownerOperator
    primary_fuel_info   TEXT,
    secondary_fuel_info TEXT,
    so2_control_info    TEXT,
    nox_control_info    TEXT,
    pm_control_info     TEXT,
    hg_control_info     TEXT,
    program_code_info   TEXT,
    source_category     TEXT,
    attr_year           INTEGER,  -- year these attributes were taken from
    in_eia              INTEGER DEFAULT 0,   -- 1 if ORIS matched an EIA plant
    source              TEXT DEFAULT 'EPA_CAMD'
);
CREATE INDEX IF NOT EXISTS ix_ppcf_ineia ON power_plant_camd_facilities(in_eia);

-- ===================================================================
-- EPA AQS ambient air monitoring (AirData pre-generated files; Michigan only).
-- MEASURED ambient concentrations from physical monitors -- distinct from CAMD
-- (measured stack emissions) and airtoxics_tracts (modeled NATA/AirToxScreen risk).
-- NO FRS/TRI identifier exists in AQS; county_fips ('26'||County Code) is the only
-- shared key (county aggregation only) -- NO joins to tri/echo/power_plants.
-- ===================================================================

-- One row per Michigan monitor = State+County+Site+Parameter+POC (from aqs_monitors).
CREATE TABLE IF NOT EXISTS air_monitors (
    state_code            TEXT,     -- "26" (Michigan)
    county_code           TEXT,     -- 3-digit AQS county code
    site_num              TEXT,     -- AQS "Site Number"
    parameter_code        TEXT,     -- part of the monitor key (site+param+POC)
    parameter_name        TEXT,
    poc                   TEXT,     -- Parameter Occurrence Code
    latitude              REAL,
    longitude             REAL,
    datum                 TEXT,
    county_fips           TEXT,     -- derived: '26' || county_code
    county_name           TEXT,
    city_name             TEXT,
    local_site_name       TEXT,
    address               TEXT,
    monitor_type          TEXT,
    networks              TEXT,
    reporting_agency      TEXT,
    monitoring_objective  TEXT,
    measurement_scale     TEXT,
    naaqs_primary_monitor TEXT,
    first_year_of_data    INTEGER,
    last_sample_date      TEXT,
    source                TEXT DEFAULT 'EPA_AQS_AirData',
    PRIMARY KEY (state_code, county_code, site_num, parameter_code, poc)
);
CREATE INDEX IF NOT EXISTS ix_air_monitors_fips ON air_monitors(county_fips);

-- Annual summary rows. GRAIN WARNING: one row per monitor per pollutant per year
-- PER APPLICABLE STANDARD -- count monitors by DISTINCT
-- state+county+site+parameter+poc, never by row count. NAAQS comparison fields
-- (pollutant_standard/metric_used/*_exceedance_count) are stored EXACTLY as
-- published by AQS; we never recompute a standard comparison ourselves.
CREATE TABLE IF NOT EXISTS air_monitor_annual (
    state_code                 TEXT,
    county_code                TEXT,
    site_num                   TEXT,
    parameter_code             TEXT,
    parameter_name             TEXT,
    poc                        TEXT,
    year                       INTEGER,
    county_fips                TEXT,     -- derived: '26' || county_code
    county_name                TEXT,
    latitude                   REAL,
    longitude                  REAL,
    sample_duration            TEXT,
    pollutant_standard         TEXT,     -- AQS's standard label; stored verbatim
    metric_used                TEXT,
    method_name                TEXT,
    units_of_measure           TEXT,
    observation_count          INTEGER,
    observation_percent        REAL,
    completeness_indicator     TEXT,
    certification_indicator    TEXT,
    valid_day_count            INTEGER,
    primary_exceedance_count   INTEGER,
    secondary_exceedance_count INTEGER,
    arithmetic_mean            REAL,
    first_max_value            REAL,
    first_max_datetime         TEXT,
    percentile_99              REAL,
    percentile_98              REAL,
    percentile_95              REAL,
    percentile_90              REAL,
    percentile_75              REAL,
    percentile_50              REAL,
    percentile_10              REAL,
    source                     TEXT DEFAULT 'EPA_AQS_AirData'
);
CREATE INDEX IF NOT EXISTS ix_air_annual_fips ON air_monitor_annual(county_fips);
CREATE INDEX IF NOT EXISTS ix_air_annual_param_year ON air_monitor_annual(parameter_code, year);
CREATE INDEX IF NOT EXISTS ix_air_annual_std ON air_monitor_annual(pollutant_standard);

-- The CURRENT NAAQS per pollutant, sourced from EPA's NAAQS table. `pollutant_standard`
-- is the EXACT AQS label to filter air_monitor_annual by, so the UI compares a reading
-- only to its own matched standard/averaging form (never a mismatched one).
CREATE TABLE IF NOT EXISTS air_naaqs_current (
    parameter_code      TEXT,
    parameter_name      TEXT,
    pollutant_standard  TEXT,     -- exact AQS 'Pollutant Standard' value that is current
    level               TEXT,
    units               TEXT,
    averaging_time      TEXT,
    form                TEXT,
    source_url          TEXT
);

-- Derived: which of Michigan's 83 counties have an ACTIVE monitor and which have none.
CREATE TABLE IF NOT EXISTS air_county_coverage (
    county_fips        TEXT PRIMARY KEY,   -- 26XXX
    county_name        TEXT,
    has_monitor        INTEGER,            -- 1 if >=1 active monitoring site, else 0
    active_site_count  INTEGER,
    source             TEXT DEFAULT 'EPA_AQS_AirData (derived)'
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
