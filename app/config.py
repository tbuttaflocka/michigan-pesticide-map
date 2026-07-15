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
