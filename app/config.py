"""Configuration constants for the Michigan Pesticide Heat Map app."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _load_dotenv(path: Path) -> None:
    """Minimal, dependency-free .env loader.

    Reads KEY=VALUE lines from a .env file at the project root and puts them in
    the process environment. Secrets (e.g. NASS_API_KEY) live there — the file
    is gitignored — instead of being hardcoded into tracked source. Real
    environment variables always win, so `.env` never overrides them.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


_load_dotenv(BASE_DIR / ".env")
DB_PATH = DATA_DIR / "michigan_pesticides.sqlite"
GEOJSON_PATH = DATA_DIR / "michigan_counties.geojson"

MICHIGAN_STATE_FIPS = "26"

# USGS NAWQA EPest county-level files.
#
# 1992-2012 — finalized, one TXT file per year at the legacy "PesticideUseEstimates"
# directory.
# 2013-2017 — finalized v2.0 bundle published via ScienceBase DOI 10.5066/P9F2SRYH.
# 2018      — preliminary release, DOI 10.5066/P920L09S.
# 2019      — preliminary release, DOI 10.5066/P9EDTHQL.
# 2020-2022 — USGS plans to publish final estimates in 2026; not yet available.
USGS_BASE = "https://water.usgs.gov/nawqa/pnsp/usage/maps/county-level/PesticideUseEstimates"
USGS_YEARS = list(range(1992, 2013))

# Each entry is (label, source_url, ScienceBase file-get URL, local filename).
USGS_SCIENCEBASE_DATASETS = [
    (
        "2013-2017 (finalized v2.0)",
        "https://doi.org/10.5066/P9F2SRYH",
        "https://www.sciencebase.gov/catalog/file/get/5e95c12282ce172707f2524e"
        "?f=__disk__62%2F83%2Fd3%2F6283d3501f1028b1ccc3976ea2e6de848bc2fef8",
        "EPest_county_estimates_2013_2017_v2.txt",
    ),
    (
        "2018 (preliminary)",
        "https://doi.org/10.5066/P920L09S",
        "https://www.sciencebase.gov/catalog/file/get/6081a706d34e8564d686618e"
        "?f=__disk__58%2F6a%2Fed%2F586aed9a844eac0174a0600c8a7293ec4cda0265",
        "EPest_county_estimates_2018.txt",
    ),
    (
        "2019 (preliminary)",
        "https://doi.org/10.5066/P9EDTHQL",
        "https://www.sciencebase.gov/catalog/file/get/6081a924d34e8564d68661a1"
        "?f=__disk__08%2F42%2Fcd%2F0842cdac3a7d8b5056645a4dc08d1da96ad4e0b7",
        "EPest_county_estimates_2019.txt",
    ),
]

# Plotly counties GeoJSON (TIGER/Line derived)
COUNTIES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
)

# Optional USDA NASS Quick Stats — set NASS_API_KEY env var to enable
NASS_API_KEY = os.environ.get("NASS_API_KEY", "").strip()
NASS_API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))

# ---- Water Quality Portal (USGS/EPA) ----
WQP_BASE = "https://www.waterqualitydata.us/data"
WQP_STATION_URL = (
    f"{WQP_BASE}/Station/search?"
    "statecode=US%3A26&characteristicType=Organics%2C%20Pesticide&mimeType=csv"
)
WQP_RESULT_URL = (
    f"{WQP_BASE}/Result/search?"
    "statecode=US%3A26&characteristicType=Organics%2C%20Pesticide"
    "&mimeType=csv&dataProfile=resultPhysChem"
)

# ---- NCI State Cancer Profiles (cancer incidence / mortality) ----
# The public site was rebuilt as a JS/session-gated form; the old
# "?...&output=1" CSV endpoint no longer returns data to a plain HTTP client.
# The loader still *tries* these URLs (and detects the empty HTML shell), then
# ingests any real per-county CSVs the user exports into CANCER_DATA_DIR, and
# otherwise seeds the Michigan statewide baseline from app/cancer_data.py.
CANCER_DATA_DIR = DATA_DIR / "cancer"
NCI_SCP_BASE = "https://statecancerprofiles.cancer.gov"
NCI_INCIDENCE_URL = (
    NCI_SCP_BASE + "/incidencerates/index.php?stateFIPS=26&areatype=county"
    "&cancer={code}&race=00&sex={sex}&age=001&stage={stage}&year=0&type=incd"
    "&sortVariableName=name&sortOrder=default&output=1"
)
NCI_MORTALITY_URL = (
    NCI_SCP_BASE + "/deathrates/index.php?stateFIPS=26&areatype=county"
    "&cancer={code}&race=00&sex={sex}&age=001&year=0&type=death"
    "&sortVariableName=name&sortOrder=default&output=1"
)

# ---- EPA Superfund NPL sites (ArcGIS Feature Service) ----
# NOTE: EPA's ArcGIS org id changed from the one in older docs
# (cJ9YHowT8TkDC48t) to cJ9YHowT8TU7DUyn, and the STATE field stores full
# names ("Michigan"), not the "MI" abbreviation. ~90 MI sites (66 active NPL,
# 22 deleted, 2 proposed) with coordinates + HRS score + status.
EPA_NPL_QUERY = (
    "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
    "Superfund_National_Priorities_List_(NPL)_Sites_with_Status_Information/"
    "FeatureServer/0/query?where=State%3D%27Michigan%27&outFields="
    "Site_Name,Site_EPA_ID,Site_Score,City,County,Status,Latitude,Longitude,"
    "Proposed_Date,Listing_Date,Deletion_Date,Site_Listing_Narrative"
    "&returnGeometry=false&outSR=4326&f=json"
)
EPA_SITE_PROFILE = (
    "https://cumulis.epa.gov/supercpad/SiteProfiles/index.cfm"
    "?fuseaction=second.cleanup&id={epa_id}"
)

# ---- EPA Toxics Release Inventory (TRI) via Envirofacts ----
# The `mv_tri_basic_download` materialized view is a fully denormalized, flat
# per-facility/chemical/year row carrying county, lat/lng, primary NAICS + a
# plain-language "industry sector" label, PFAS/carcinogen flags, and every
# release pathway broken out (5.1 fugitive air, 5.2 stack air, 5.3 water,
# 5.4 underground, 5.5.x land). No API key required. Filter columns are `st`
# (2-letter state) and `year`. One filtered CSV per year (~3k MI rows/yr).
TRI_MV_URL = ("https://data.epa.gov/efservice/mv_tri_basic_download/"
              "st/{state}/year/{year}/CSV")
TRI_STATE_ABBR = "MI"
TRI_START_YEAR = 2013          # pull >= 10 years so trends have depth
TRI_END_YEAR = 2025            # probe downward from here; skip empty years
TRI_CACHE_DIR = DATA_DIR / "tri"

# ---- Michigan EGLE Materials Management Open Data (ArcGIS MapServer) ----
# Solid-waste + hazardous-waste facility layers published by EGLE. We use two:
#   * Layer 6 — Part 115 Solid Waste Landfills (Type II municipal + Type III
#     industrial / C&D / coal-ash). NOTE: this open-data layer only carries
#     currently ACTIVE / accepting licensed facilities — closed / post-closure /
#     pre-regulation landfills are NOT in it (see app/landfill_data.py).
#   * Layer 7 — Part 111 Treatment, Storage & Disposal Facilities (hazardous
#     waste, e.g. Wayne Disposal). We keep only disposal-capable TSDFs (a
#     FacilityType containing "D") — the actual hazardous-waste land-disposal
#     sites — not the many storage/treatment-only generator locations.
# Coordinates come back as WGS84 (latdeccord/longdeccord strings on L6,
# Latitude/Longitude doubles on L7).
EGLE_MMD_BASE = ("https://gisagoegle.state.mi.us/arcgis/rest/services/"
                 "EGLE/MmdOpenData/MapServer")
EGLE_LANDFILL_QUERY = (
    EGLE_MMD_BASE + "/6/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"
)
EGLE_TSDF_QUERY = (
    EGLE_MMD_BASE + "/7/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"
)
# EGLE FOIA — monitoring RESULTS (groundwater/air/leachate) are not published as
# open data and must be requested here. FOIA_URL is EGLE's procedures/summary
# page; SUBMIT_URL is the EGLE FOIA Request Center portal (GovQA) where a request
# is actually filed. Both verified live from michigan.gov/egle/contact/foia.
EGLE_FOIA_URL = "https://www.michigan.gov/egle/contact/foia/summary"
EGLE_FOIA_SUBMIT_URL = "https://michiganegle.govqa.us/WEBAPP/_rs/SupportHome.aspx"

# ---- USGS Watershed Boundary Dataset (HUC-8 polygons) ----
WBD_HUC8_QUERY = (
    "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4/query"
    "?where=states%20LIKE%20%27%25MI%25%27"
    "&outFields=huc8,name,states,areasqkm"
    "&returnGeometry=true&outSR=4326&f=geojson"
)
MI_HUC8_GEOJSON_PATH = DATA_DIR / "mi_huc8.geojson"

# ---- Iowa Environmental Mesonet (IEM) ASOS hourly wind ----
# Free CSV of hourly wind direction (drct, deg) + speed (sped, mph) per station.
# We pull growing-season (Apr-Sep) observations across WIND_YEARS and build
# per-station wind roses. report_type 3+4 = routine + special METARs.
IEM_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
WIND_YEARS = [2021, 2022, 2023]
WIND_SEASON_MONTHS = (4, 9)   # April through September, inclusive
WIND_CACHE_DIR = DATA_DIR / "wind"

# ---- Golf courses (OpenStreetMap via the Overpass API) ----
#
# Michigan has no golf-course-specific public pesticide-use reporting, so no
# agency publishes course footprints. OpenStreetMap tags golf courses well
# (leisure=golf_course, as closed ways and multipolygon relations) and has good
# Michigan coverage, so we pull course LOCATIONS from Overpass. We never pull or
# infer pesticide amounts — that data is not public (see app/golf_data.py).
#
# The query is bounded to Michigan's admin boundary (area, admin_level=4) rather
# than a bbox so we don't pick up courses in neighbouring states/Ontario, and
# `out geom` returns full polygon geometry so we can render course footprints.
# Multiple public mirrors are tried in order — the main instance rate-limits.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
# ---- Underground Storage Tanks (EGLE RRD, regularly updated) ----
#
# The single richest source of everyday near-home contamination: EGLE's UST layer
# carries BOTH tanks merely licensed under Part 211 (LARA — a working gas
# station, not necessarily a problem) AND leaking tanks regulated under Part 213
# (EGLE — confirmed releases needing corrective action). RegulatoryProgram
# (211 vs 213) + Open_Release/Total_Release distinguish them; the layer already
# includes release status/classification, so no fragile RIDE join is needed. RIDE
# Mapper is cited as the per-site reference viewer.
UST_URL = ("https://gisagoegle.state.mi.us/arcgis/rest/services/"
           "EGLE/RRDOpenData/MapServer/1")
EGLE_RIDE_URL = "https://www.egle.state.mi.us/RIDE/"
EGLE_UST_HOME_URL = ("https://www.michigan.gov/egle/about/organization/"
                     "remediation-and-redevelopment/storage-tanks")

# ---- PFAS (Michigan PFAS Action Response Team / EGLE, live ArcGIS) ----
#
# Michigan runs the most aggressive state PFAS program in the country; MPART
# publishes five live feeds. Two orgs host them: EGLE's ArcGIS Online org
# (services1.arcgis.com/FNjlrOFR0aGJ71Tg) and EGLE's on-prem server
# (gisagoegle.state.mi.us). The Public Water Supply results are published as
# HEXBINS (not precise locations) by EGLE's design to protect critical
# infrastructure — we render the hexbins as provided and never pinpoint systems.
PFAS_AGO_BASE = "https://services1.arcgis.com/FNjlrOFR0aGJ71Tg/arcgis/rest/services"
PFAS_EGLE_BASE = "https://gisagoegle.state.mi.us/arcgis/rest/services/EGLE"
PFAS_SITES_URL = (PFAS_AGO_BASE
    + "/Michigan_PFAS_Sites_and_Areas_of_Interest_PUBLIC_view/FeatureServer/1")
PFAS_SURFACE_WATER_URL = PFAS_EGLE_BASE + "/PfasOpenData/MapServer/0"
PFAS_PWS_HEXBIN_URL = PFAS_EGLE_BASE + "/PublicWaterSupplySamplingOpenData/FeatureServer/0"
PFAS_PWS_RESULTS_URL = PFAS_EGLE_BASE + "/PublicWaterSupplySamplingOpenData/FeatureServer/1"
PFAS_FISH_SITES_URL = PFAS_EGLE_BASE + "/FcmpOpenData/FeatureServer/0"
PFAS_FISH_DATA_URL = PFAS_EGLE_BASE + "/FcmpOpenData/FeatureServer/1"
PFAS_POTW_URL = (PFAS_AGO_BASE
    + "/Industrial_Pretreatment_Program_Waste_Water_Treatment_Plants_Public_View/FeatureServer/0")
# EPA air toxics risk (NATA / AirToxScreen) — census-tract cancer-risk screening.
# Served from EPA's OAR/OAQPS ArcGIS Online org (the same org we already use for
# contamination). ATS_Risk_View exposes tract polygons with total + per-pollutant
# cancer risk AND the source-category breakdown in a single queryable layer.
EPA_ATS_ORG = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services"
AIRTOXICS_RISK_URL = EPA_ATS_ORG + "/ATS_Risk_View/FeatureServer/0"
AIRTOXICS_HOME_URL = "https://www.epa.gov/AirToxScreen"

# Official landing pages (Data Sources modal + popups).
MPART_HUB_URL = "https://gis-egle.hub.arcgis.com/search?tags=pfas"
MPART_HOME_URL = "https://www.michigan.gov/pfasresponse"
MDHHS_EAT_SAFE_FISH_URL = ("https://www.michigan.gov/mdhhs/safety-injury-prev/"
                           "environmental-health/topics/eat-safe-fish")

OVERPASS_GOLF_QUERY = (
    "[out:json][timeout:180];"
    'area["name"="Michigan"]["admin_level"="4"]["boundary"="administrative"]->.mi;'
    "("
    '  way["leisure"="golf_course"](area.mi);'
    '  relation["leisure"="golf_course"](area.mi);'
    '  way["landuse"="recreation_ground"]["sport"="golf"](area.mi);'
    '  relation["landuse"="recreation_ground"]["sport"="golf"](area.mi);'
    ");"
    "out geom tags;"
)
