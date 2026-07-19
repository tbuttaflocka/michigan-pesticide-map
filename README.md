# Michigan Pesticide Application Heat Map

Interactive single-page web app showing county-level agricultural pesticide use across
Michigan's 83 counties from 1992 through 2012, sourced directly from the USGS NAWQA
Pesticide National Synthesis Project. Built with Flask + SQLite + Leaflet + Chart.js.

## Quick start

```bash
# macOS / Linux
./setup.sh

# Windows
setup.bat
```

Or step by step:

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python -m app.data_loader         # downloads ~120 MB of real USGS files into ./data
python app.py                     # serves http://127.0.0.1:8080
```

### Optional API keys (`.env`)

Some data sources need a free API key. Keys live in a **gitignored `.env`** file
so they're never committed — copy the template and fill in your own:

```bash
cp .env.example .env              # then edit .env
```

| Variable | Enables | Get a key |
|---|---|---|
| `NASS_API_KEY` | USDA NASS county crop acreage → crop-context features + the **lbs per cropland acre** map normalization | https://quickstats.nass.usda.gov/api |

`.env` is loaded automatically at startup (no extra dependency). After adding the
key, run `python refresh_data.py --source nass_crop` to pull the crop data.

## Features

- **Heat-map view** — county choropleth, layer toggles (category / specific compound),
  Low/Avg/High estimate switch, total-vs-kg/mi² normalization, time slider
  (1992–2012) with play animation, click-for-county-detail with charts.
- **CWD overlay** — toggle-able layers on top of the pesticide map:
  CWD-positive county choropleth, per-township wild-deer markers, farmed-cervid
  facility markers, and per-year surveillance zones. County detail panel shows
  CWD status, first-detected date, and confirmed-positive count alongside
  pesticide totals.
- **Correlation view** — separate tab with a scatter plot of pesticide intensity
  vs CWD positives (with OLS fit), Welch's t-test of CWD-positive vs negative
  county means, per-compound mean comparison with significance stars, and a
  sortable comparison table across all 83 counties. Statistical tests are
  computed in pure stdlib so no scipy install is required.
- **Water contamination overlay** — three toggleable layers in the left
  sidebar: monitoring sites (2,514 stations colour-coded green / amber / red
  by detection severity), Leaflet heatmap of detection density, and HUC-8
  watershed polygons shaded by total detections / MCL exceedances. A
  dropdown filters every layer to a single compound (e.g. ATRAZINE); a
  "Match the main map's compound" checkbox automatically links it to
  whatever compound the pesticide-application filter is on, so picking
  Atrazine in the main filter immediately shows where Atrazine is being
  detected in Michigan's water. Click any site marker for a popup showing
  the full per-compound sample summary and MCL comparison.
- **Respiratory view** — third tab covering ICD-10 J00-J99. The sidebar
  layer has a single on/off checkbox plus a dropdown that picks one of nine
  metrics: All Respiratory (combined), Asthma — ED, Asthma — Hospitalizations,
  COPD — ED, COPD — Hospitalizations, Acute Bronchitis, Pneumonia & Influenza,
  Upper Respiratory Infections, All Respiratory Mortality (J00-J99). The four
  CDC-Tracking measures vary at county level; the broader ICD categories use
  MDHHS-published Michigan statewide baselines (uniform shading + clear
  labeling). Hover tooltip adds one clean line with the active metric.
  County detail shows every metric with a vs-MI percentage arrow.
- **Cancer view** — fourth tab covering the cancer types with the strongest
  epidemiological links to pesticide exposure (Non-Hodgkin Lymphoma — default —
  Leukemia, Bladder, Colon & Rectum, Pancreas, Lung, Prostate, Kidney, plus
  All Sites, Breast, and Thyroid as controls). The sidebar overlay adds an
  orange-red county choropleth with a cancer-type dropdown and an
  incidence/mortality toggle; the county detail panel gains a cancer card
  showing each type's age-adjusted rate, ▲/▼ vs the Michigan average, the US
  (SEER+NPCR) rate, the recent trend, and a "top 20%" flag. The correlation
  tab has a rural/urban scatter (pesticide metric or specific compound vs
  cancer rate, with Pearson/Spearman + quartile comparison and confound
  toggles), a compound × cancer correlation matrix with the IARC/AHS evidence
  attached to each cell (click a cell to load it in the scatter), a
  pesticide-quartile bar chart, an evidence-reference modal, and a
  collapsed-by-default caveats block. All rates are real county-level NCI
  State Cancer Profiles values (2018–2022); picking a compound like Glyphosate
  on the main map pre-loads its "Glyphosate vs NHL" deep dive.
- **Industrial contamination overlay** — Michigan's contamination legacy on
  top of the pesticide map: 105 sites (66 active Superfund NPL + deleted/
  proposed, plus compiled PFAS/state sites). Toggleable in the left sidebar
  with status sub-filters (Superfund NPL / PFAS / state cleanup / deleted),
  translucent impact zones for sites with a known spread radius, and a magenta
  county-density choropleth. Markers use category glyphs (☣ chemical, 🏭
  steel/auto, ★ military/AFFF, ⛏ mining, ☠ waste, 💧 PFAS) colored by status
  and sized by HRS score, on a dedicated high-z pane above every choropleth.
  Clicking a marker shows the responsible company, EPA ID, years operated,
  HRS score, contaminant chips, full narrative, affected waterways/counties,
  and a link to the EPA Superfund profile. The county detail panel lists that
  county's sites; the Cancer tab gains "Contamination sites (count)" and
  "Superfund NPL sites (count)" as X-axis options so you can compare whether a
  county's cancer rate tracks agricultural pesticides or industrial
  contamination. Federal NPL sites are pulled live from EPA's ArcGIS SEMS
  feature service and merged (deduped) with the compiled dataset. Every site
  has a description: the ~30 major/mid-tier compiled sites carry full narratives,
  and the EPA-API sites (whose feed only returns a PDF link, not prose) get a
  factual auto-generated summary built from name/location/NPL status/listing
  date/HRS score. Auto-generated popups are labelled "Summary generated from the
  EPA site record" with a link to the full EPA profile, so it's transparent
  which descriptions are hand-written narratives vs. structured summaries.
  A further ~20 notable EPA-API sites (Berlin & Farro, Verona Well Field, Tar
  Lake, Ten-Mile Drain, Bofors Nobel, G&H Landfill, etc.) carry researched
  narratives — the real story (operator, what was dumped, when, how it was
  found, impact, cleanup) — drawn from EPA/EGLE/news and shown with a "Sources:"
  line in the popup. These live in `app/contamination_narratives.json` and are
  applied by the re-runnable `enrich_narratives.py` (curated data + optional
  Wikipedia auto-fetch; `--only`, `--force`, `--no-web`, `--list` flags). Sites
  with no available narrative say "No detailed public narrative found" rather
  than inventing one.
- **Wind & pesticide-drift overlay** — three stackable overlays under Map
  layers → Overlays, built from real growing-season (Apr–Sep) hourly wind at 14
  Michigan ASOS airport stations (Iowa Environmental Mesonet). *Wind roses* plot
  a per-station SVG rose (petal length = direction frequency, petal color = that
  direction's mean-speed band 0-5/5-10/10-15/15+ mph), semi-transparent over the
  map; hover for prevailing direction, average speed, and % calm. *Drift arrows*
  draw a downwind arrow from the centroid of each top-25%-application county
  (nearest station's prevailing wind + 180°), colored by application intensity
  and lengthened by wind speed, with a "Prevailing wind: SW at 8.3 mph → drift
  NE" tooltip. *Show drift zone on county click* draws a fan-shaped downwind
  buffer (near 0–0.5 / mid 0.5–2 / far 2–5 mi bands, ~60° spread) when you open a
  county, with a tooltip disclaiming that real drift depends on droplet size,
  application method, inversions, etc. This is a deliberately simple illustrative
  model, not a regulatory buffer.
- **Correlation panel (simplified)** — one big urban/rural scatter with the
  trend line and R² built into the legend; one plain-English quartile-comparison
  sentence ("top 25% pesticide counties average X vs Y for bottom 25%"); a
  year-over-year respiratory trend line; sortable comparison table flagging
  overlap counties. Caveats live in a collapsed-by-default `<details>` block
  marked "ℹ️ Important context — click to expand". The seasonal-overlap chart
  was removed because monthly granularity isn't available at the county level.

## Data sources

| Source | Status | Notes |
|---|---|---|
| **USGS NAWQA EPest** county-level pesticide use, 1992–2019 | ✅ live download | Primary heat-map dataset. ~388 active ingredients × 83 MI counties × 28 years. 1992–2012 from the legacy per-year files; 2013–2017 from the finalized v2.0 ScienceBase release (DOI 10.5066/P9F2SRYH); 2018 + 2019 from the preliminary ScienceBase releases (DOIs 10.5066/P920L09S and 10.5066/P9EDTHQL). USGS plans 2020–2022 final estimates for publication in 2026. |
| **US Census TIGER** county boundaries (plotly mirror) | ✅ live download | Filtered to STATE FIPS 26. |
| **Pesticide categories** (herbicide / insecticide / fungicide / etc.) | ✅ embedded reference | Curated mapping built from EPA labels and university extension publications; see `app/categories.py`. |
| **USDA NASS Quick Stats** crop acreage | ⚙️ optional | Set `NASS_API_KEY=...` (free at quickstats.nass.usda.gov/api) before running the loader. |
| **Michigan DNR** CWD wild-deer test results (compiled to Feb 2026) | ✅ baked baseline | 18 positive counties / 378 wild positives. DNR's per-season tables are behind JS-rendered widgets; the loader uses the static fallback in `app/cwd_data.py`. |
| **MDARD** farmed-cervid CWD surveillance | ✅ baked baseline | 16 captive facilities CWD-positive since 2008. |
| MSU Veterinary Diagnostic Lab, USDA NVSL, CWD-Info.org | 🔗 reference link | Confirmation labs and Alliance case tracking. |
| **NCI / CDC State Cancer Profiles** county cancer incidence & mortality, 2018–2022 | ✅ live download | County age-adjusted rates for 11 cancer types (incidence + mortality + late-stage). The site's `?…&output=1` export returns the empty HTML form to a browser but real CSV to the loader's `urllib` client; parsed rows land in `data/cancer/` and SQLite. Falls back to the Michigan statewide baseline in `app/cancer_data.py` if a fetch yields no county rows. |
| **Agricultural Health Study** + **IARC Monographs** | ✅ embedded reference | Compound→cancer evidence table (evidence level, IARC class, mechanism, key studies) in `app/cancer_data.py`; powers the evidence modal + matrix dots. |
| Michigan Cancer Surveillance Program (MCSP), CDC NPCR, NCI SEER, CDC WONDER | 🔗 reference link | Registry programs behind State Cancer Profiles; county extracts are portal/agreement-gated, not bulk feeds. |
| **EPA Superfund (SEMS) NPL sites** | ✅ live download | ~90 Michigan NPL sites (66 active, 22 deleted, 2 proposed) with coordinates, HRS score, status, county, listing date. ArcGIS Feature Service (org `cJ9YHowT8TU7DUyn`, `State='Michigan'`); merged/deduped with the compiled dataset. |
| **Compiled industrial polluters + PFAS sites** | ✅ embedded reference | 31 hand-compiled major sites (Dow, Velsicol/PBB, Wolverine/Hush Puppies PFAS, Torch Lake, McLouth Steel, GM, Kalamazoo River PCBs, Wurtsmith AFB, Gelman 1,4-dioxane, etc.) with company attribution, contaminant lists, narratives, impact radii, and affected waterways in `app/contamination_data.py`. Many are non-NPL and don't appear in the EPA feed. |
| Michigan EGLE Remediation & Redevelopment (Part 201), MPART (PFAS), EPA Region 5, MDHHS PBB Registry, ATSDR | 🔗 reference link | State/PFAS programs and toxicological references; portal-only or embedded, not bulk feeds. |
| **EPA Toxics Release Inventory (TRI)** — active industrial releases, 2013–2024 | ✅ live download | ~1,090 Michigan facilities and ~37k facility-chemical-year release records from the Envirofacts `mv_tri_basic_download` view (filtered `st=MI`, one CSV per year). Each record carries county, lat/lng, NAICS + plain-language industry sector, PFAS/carcinogen flags, and pounds released per pathway (air = fugitive + stack, water, underground, land). Complements the legacy Superfund layer by showing what facilities are *actively* releasing now. Self-reported annually under EPCRA. Powers factory markers, the "TRI toxic releases" choropleth (with air/water/land/PFAS sub-options), correlation X-variables, and a year-over-year trend. No API key required. |
| **CDC EPHT Tracking Network** asthma + COPD rates | ✅ live download | 2,822 county-year-condition rows pulled from `getCoreHolder` measures 437/103/652/649 with exponential-backoff retry. |
| MDHHS Asthma Atlas 2019 — statewide baseline | ✅ baked baseline | Adult prevalence applied uniformly across counties; "Above / below state average" comparison shown per county. |
| Michigan MiTracking, MDHHS Resp. Dashboard, MHA, CDC WONDER, MiBRFS | 🔗 reference link | All five appear in the Data Sources modal but are not bulk-downloadable. |
| MDARD pesticide registration DB | 🔗 reference link | No bulk feed published. |
| MDARD inspectors by county | 🔗 reference link | Assignments change; live MDARD page linked from each county panel. |
| Michigan EGLE NPDES pesticide permits | 🔗 reference link | No structured public dataset. |
| USDA Cropland Data Layer (CDL) | 🔗 reference link | Multi-GB raster, not bundled. |
| **Iowa Environmental Mesonet (IEM) ASOS** hourly wind | ✅ live download | Growing-season (Apr–Sep) wind direction + speed for 14 Michigan airport stations (2021–2023), fetched via the free IEM CSV endpoint and reduced to per-station wind roses in `wind_data`. Powers the wind-rose, drift-arrow, and drift-zone overlays. Station metadata + drift geometry in `app/wind_data.py`. |
| NOAA NCEI CDO / NCEP-NCAR Reanalysis | 🔗 reference link | Alternative gridded/token-gated wind sources noted in the spec; ASOS point observations are used instead (no token required). |

The status of every source is also shown in the **Data sources** modal in the app.

## Year coverage

The loader pulls every publicly released USGS NAWQA EPest dataset:

| Years | Source | Status |
|---|---|---|
| 1992–2012 | Legacy per-year text files at `water.usgs.gov/.../PesticideUseEstimates/` | Final |
| 2013–2017 | ScienceBase release v2.0 — DOI 10.5066/P9F2SRYH | Final |
| 2018 | ScienceBase release — DOI 10.5066/P920L09S | Preliminary |
| 2019 | ScienceBase release — DOI 10.5066/P9EDTHQL | Preliminary |
| 2020–2022 | Not yet published | USGS plans 2026 release |

The 2018 and 2019 preliminary releases cover fewer compounds than the final
files (52 in 2019 vs 188 in earlier years), so totals dip in the late-year
trend. This is a property of the source data, not the loader.

## Keeping the data fresh

`refresh_data.py` re-pulls every live source and updates the database **safely**.
Each source is refreshed independently — one failing source never blocks the
others, and the app is never left empty or half-written:

1. The source's loader runs against a private **staging** database.
2. The staged result is **validated** (expected tables/columns present, primary
   table non-empty, row count not collapsed vs. the live data).
3. Only if validation passes are the live tables **atomically swapped** in one
   transaction. If a source is down or changed its format, the last good data is
   kept and the failure is logged.

Every run is appended to `refresh.log`, and each source's last-refresh time,
coverage window, and status are recorded in the `data_sources` table and shown
in the app's **Data sources** modal (with a "Data current as of …" line and a
subtle *stale* flag on anything past its refresh interval).

```bash
python refresh_data.py                     # refresh all sources
python refresh_data.py --source water_quality   # refresh just one
python refresh_data.py --list              # show each source's last status
python refresh_data.py --no-derived        # skip rebuilding correlations
python refresh_data.py --source water_quality --full   # full WQP rebuild (see below)
```

The script is idempotent (re-running never duplicates data). Immutable archival
caches (finalized USGS EPest files, historical wind, watershed boundaries) are
reused — re-running still picks up any newly *published* years added to
`app/config.py`.

**Water Quality Portal is pulled incrementally.** The full MI pesticide result
set is ~230 MB, and the portal rate-limits large repeated downloads. So after
the first load, each refresh downloads only samples on/after the latest sample
date already stored (WQP `startDateLo`) — usually a few MB — and appends them,
re-fetching the boundary day in full to avoid gaps or duplicates. If a WQP fetch
fails, the existing data is kept and the source is marked failed (it is never
silently left partial). Because date-bounded pulls key off the *sample* date, a
sample collected before the watermark but uploaded to WQP late can be missed;
run `--full` occasionally (e.g. yearly) to re-pull everything and backfill.

### Recommended refresh interval per source

| Source (`--source`) | Cadence | Why |
|---|---|---|
| `usgs_epest` (pesticide use) | **Annual** | USGS publishes one release per year |
| `nass_crop` (crop acreage) | **Annual** | NASS county data is yearly |
| `cancer` (NCI cancer profiles) | **Annual** | 5-year rolling rates update yearly |
| `respiratory` (CDC Tracking/WONDER) | **Annual** | Annual county measures |
| `wind` (IEM ASOS) | **Annual** | Growing-season aggregates |
| `tri` (EPA Toxics Release Inventory) | **Annual** (quarterly-safe) | TRI is published yearly (a year's data finalizes ~Oct of the following year). A quarterly run simply reuses the cached finalized years and picks up the newly-finalized year when it lands. |
| `water_quality` (WQP samples) | **Quarterly** | New samples posted continuously |
| `superfund` (EPA NPL) | **Quarterly** | Site statuses change through the year |
| `cwd` (DNR CWD) | **Quarterly** | Updated through hunting/testing seasons |

### Scheduling on Windows (Task Scheduler)

`refresh_data.py` does **not** schedule itself — set it up with the built-in
Task Scheduler. Use the full path to the venv's Python and to the script, and
quote paths that contain spaces. A simple approach is one monthly all-sources
run (the per-source guards make it a no-op for anything already current):

```bat
schtasks /create /tn "PesticideMap Refresh" /sc MONTHLY /d 1 /st 03:00 ^
  /tr "\"C:\Users\tarbu\Desktop\michigan-pesticide-map\.venv\Scripts\python.exe\" \"C:\Users\tarbu\Desktop\michigan-pesticide-map\refresh_data.py\""
```

For tighter control, create two tasks that call the script with `--source` for
the quarterly sources and a yearly task for the annual ones. Example — quarterly
water-quality refresh on the 1st of Jan/Apr/Jul/Oct:

```bat
schtasks /create /tn "PesticideMap WQ Refresh" /sc MONTHLY /mo 3 /d 1 /st 03:30 ^
  /tr "\"...\.venv\Scripts\python.exe\" \"...\refresh_data.py\" --source water_quality"
```

The script exits non-zero if **every** selected source fails, so Task Scheduler
can surface a failed run. Check `refresh.log` (and `python refresh_data.py
--list`) to see what happened.

## Architecture

```
michigan-pesticide-map/
├── app.py                  Flask server + REST API
├── refresh_data.py         Safe, staged data-refresh harness (scheduled)
├── app/
│   ├── config.py           Paths, URLs, env wiring
│   ├── database.py         SQLite schema + connection helper
│   ├── data_loader.py      Downloads + ingests all data
│   └── categories.py       Compound -> category lookup
├── data/                   Raw downloads + SQLite DB (created on first run)
├── static/css|js/          Dark-theme stylesheet + Leaflet/Chart.js app
├── templates/index.html    Single-page UI shell
├── requirements.txt
├── setup.sh / setup.bat
└── README.md
```

## API

| Endpoint | Description |
|---|---|
| `GET /api/meta` | Years, categories, compounds, counties, source status |
| `GET /api/geojson` | Michigan-only GeoJSON FeatureCollection |
| `GET /api/choropleth?year=&category=&compound=&estimate=&normalize=` | Per-county values for current filters |
| `GET /api/county/<fips>?year=&estimate=` | Detail for the county sidebar |
| `GET /api/statewide?year=&estimate=` | Top-N counties + compounds + trend + categories |
| `GET /api/compound/<name>?estimate=` | Statewide trend + per-county breakdown for one compound |
| `GET /api/search?q=` | Type-ahead search over counties & compounds |
| `GET /api/cwd/counties` | One row per CWD-positive county |
| `GET /api/cwd/points` | Per-township wild-deer marker points |
| `GET /api/cwd/timeline` | CWD detections by year (drives animation) |
| `GET /api/cwd/farmed` | Farmed-cervid CWD facility counts |
| `GET /api/cwd/surveillance` | DNR focused surveillance counties by year |
| `GET /api/correlation` | Sortable comparison table — pesticide totals + CWD per county |
| `GET /api/correlation/scatter?metric=` | Scatter points + OLS trend line |
| `GET /api/correlation/stats?metric=` | Welch t-test, Pearson r, plain-English summary |
| `GET /api/correlation/compounds` | Per-compound mean-kg comparison (CWD+ vs CWD−) |
| `GET /api/correlation/crops` | Crop-mix comparison (requires NASS) |
| `GET /api/respiratory/counties?metric=` | Per-county asthma/COPD ED + hosp rates for the choropleth |
| `GET /api/respiratory/trends?metric=&fips=` | Yearly trend, statewide or county |
| `GET /api/respiratory/seasonal` | Statewide season-of-year asthma ED index |
| `GET /api/respiratory/baseline` | Statewide reference rates |
| `GET /api/correlation/respiratory` | Full joined table with urban flag |
| `GET /api/correlation/respiratory/scatter?pest=&resp=&exclude_wayne=` | Scatter + OLS line |
| `GET /api/correlation/respiratory/stats?pest=&resp=&urban_only=&rural_only=` | Pearson + Spearman + quartile t-test |
| `GET /api/correlation/respiratory/seasonal` | Growing-season vs respiratory-index monthly overlay |
| `GET /api/correlation/respiratory/rankings?resp=` | Rankings table with overlap flag |
| `GET /api/water/sites?compound=&medium=` | Monitoring sites with detection/exceedance counts |
| `GET /api/water/site/<id>` | Site detail + per-compound sample summary |
| `GET /api/water/compounds` | All compounds detected with sample/detection/exceedance counts |
| `GET /api/water/heatmap?compound=` | `[lat, lon, weight]` points for `L.heatLayer` |
| `GET /api/water/watersheds?compound=` | HUC-8 GeoJSON with per-watershed detection counts |
| `GET /api/cancer/types` | Cancer-type registry + matrix compounds/cancers |
| `GET /api/cancer/counties?type=&data_type=&stage=` | Per-county age-adjusted rates for the cancer choropleth |
| `GET /api/cancer/county/<fips>` | All-cancer card for one county (rate, vs MI/US, trend, top-20%) |
| `GET /api/cancer/evidence` | Pesticide→cancer evidence table (IARC + AHS) |
| `GET /api/correlation/cancer?cancer=&pesticide=&data_type=&exclude_urban=&rural_only=` | Scatter + Pearson/Spearman + quartile comparison |
| `GET /api/correlation/cancer/matrix?data_type=` | Compound × cancer correlation grid with evidence per cell |
| `GET /api/correlation/cancer/quartiles?cancer=&pesticide=` | Mean cancer rate per pesticide-use quartile (`pesticide=contamination` supported) |
| `GET /api/contamination/sites?category=&status=` | All contamination sites with coordinates, glyph, status color, contaminants |
| `GET /api/contamination/county/<fips>` | Contamination sites in one county |
| `GET /api/contamination/density` | Per-county site counts (total / NPL / PFAS) for the density choropleth |
| `GET /api/correlation/contamination?cancer=&metric=count\|npl` | Cancer incidence vs contamination-site count per county |

## Notes on data limitations

USGS EPest values are **estimates**, not field-reported measurements. They are derived
from proprietary pesticide-sale data combined with crop-acreage models. The Low and High
brackets reflect the published uncertainty range; the UI defaults to the average of the
two. Only **agricultural** use is included — lawn-care, golf-course, and aquatic
non-agricultural applications are out of scope. See USGS Data Series 907 for full
methodology.
