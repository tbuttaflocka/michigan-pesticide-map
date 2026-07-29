# Michigan Pollution Map

Interactive single-page web app that brings together county-level pollution,
contamination, and community-health data for Michigan's 83 counties on one map so
you can explore it and ask questions. It combines agricultural **pesticide use** (USGS NAWQA EPest), **water-quality**
sampling, **industrial contamination** (EPA Superfund), active **industrial toxic
releases** (EPA Toxics Release Inventory), **landfills & waste facilities** (Michigan
EGLE), **respiratory** and **cancer** health measures,
crop acreage, and growing-season **wind/drift**. Built with Flask + SQLite + Leaflet +
Chart.js.

> **Disclaimer — please read.** This tool is for **exploration and education only**. It is
> **not** medical, legal, regulatory, or scientific advice. Any patterns it shows are
> **associations, not proof of cause** — counties differ in age, income, industry, smoking,
> and many other ways that affect health. It is an **independent, non-commercial project**
> and is not affiliated with or endorsed by any government agency. Do not use it to draw
> conclusions about any individual person, place, or product. See **[Disclaimer &
> limitations](#disclaimer--limitations)** below.

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
python scripts/fetch_db.py --if-missing   # grabs the ~90 MB prebuilt DB if absent
python app.py                     # serves http://127.0.0.1:8080
```

> **The database is not stored in git.** It outgrew GitHub's file-size limits, so
> it's published as a GitHub Release asset (tag `data`) and fetched by
> `scripts/fetch_db.py`. `--if-missing` only downloads when the DB is absent, so
> it's safe to run any time and does nothing once you have it. The app refuses to
> start without a real database rather than serving an empty one.
>
> Prefer to **build the DB from source** instead of downloading it? Run
> `python -m app.data_loader` (downloads ~120 MB of raw USGS/Census files and
> ingests them — slower, but no Release asset needed). `setup.sh` / `setup.bat`
> take this from-source path.

> `python app.py` starts Flask's built-in **development** server — fine for local
> use, but **not** for public hosting. To share the app publicly, use the
> production setup below.

### Running in production (public sharing)

Flask's dev server is single-threaded and not hardened for the public internet.
For a shared deployment, serve the app with **Waitress** (a pure-Python,
production-grade WSGI server that also runs on Windows) via the included
`serve.py`:

```bash
pip install -r requirements.txt        # includes Waitress
python serve.py                        # serves HOST:PORT (default 127.0.0.1:8080)
```

`serve.py` respects the `HOST` and `PORT` environment variables and exposes the
WSGI app as `serve:application` (so `waitress-serve --listen=127.0.0.1:8080
serve:application`, or gunicorn `serve:application` on Linux, also work).

**Put HTTPS in front of it.** Waitress speaks plain HTTP; terminate TLS with a
reverse proxy in front of it. `serve.py` always binds `0.0.0.0` on `$PORT`
(default 8080), so restrict outside access to that port at the firewall/proxy
layer and let the proxy handle TLS and the public port:

```bash
PORT=8080 python serve.py
```

- **Caddy** (automatic HTTPS via Let's Encrypt) — simplest:
  ```
  your-domain.example {
      reverse_proxy 127.0.0.1:8080
  }
  ```
- **nginx** — `proxy_pass http://127.0.0.1:8080;` inside a `server { listen 443 ssl; }`
  block with your certificate, plus a redirect from port 80 → 443.
- **Windows/IIS** — use the Application Request Routing (ARR) reverse-proxy module
  pointed at `http://127.0.0.1:8080`.

Notes for a public deployment:

- Serve **only over HTTPS** and add **HSTS** (`Strict-Transport-Security`) at the
  proxy — it's intentionally not set in-app so local HTTP still works.
- The app already sends a Content-Security-Policy and other security headers
  (see `_security_headers` in `app.py`); the reverse proxy can add HSTS on top.
- The app is **read-only** (no login, no user data, no write endpoints), so it
  needs no database credentials or session secret.
- Run the data refresh on a schedule (see [Keeping the data fresh](#keeping-the-data-fresh)).

### Deploying to Render

This repo is ready to deploy on [Render](https://render.com) as a free Python web
service. The ~90 MB database is **not** in the repo (it outgrew GitHub's file-size
limits); Render downloads it during the build from a GitHub Release asset via
`scripts/fetch_db.py`. That script **verifies** the download (size + SHA-256) and
**fails the build loudly** if the file is missing or truncated, so a broken app is
never deployed.

The included **`render.yaml`**, **`runtime.txt`**, and **`serve.py`** provide everything
Render needs:

| Setting | Value |
|---|---|
| Runtime | Python (`runtime.txt` → `python-3.13.4`) |
| Build command | `pip install -r requirements.txt && python scripts/fetch_db.py` |
| Start command | `python serve.py` |
| Env vars | none required — `serve.py` binds `0.0.0.0` and reads the `PORT` Render sets automatically |

Steps: push this repo to GitHub → **publish the database as a Release asset once**
(see [Keeping the data fresh](#keeping-the-data-fresh)) → in Render, **New → Web
Service** → connect the repo → Render reads `render.yaml` (or enter the build/start
commands above) → **Create**. Render provides HTTPS automatically on the
`*.onrender.com` URL. On the free plan the service sleeps after inactivity, so the
first request after idle takes ~30–60 s to wake.

> **If your Render service was created before this change** (build command was just
> `pip install -r requirements.txt`), update it: Render dashboard → your service →
> **Settings → Build Command** → set it to
> `pip install -r requirements.txt && python scripts/fetch_db.py`. Services created
> from `render.yaml` as a Blueprint pick this up automatically.

To update the deployed data later, refresh locally and **re-upload the Release asset**
(don't commit the DB) — see [Keeping the data fresh](#keeping-the-data-fresh). Render
downloads the new database on the next deploy.

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

- **Search** — one box over four grouped result types: **Places** (cities, villages,
  townships, CDPs and ZIP codes — because most people don't think in counties, and
  Michigan township identity is strong), **Counties**, **Facilities** (named sites
  across TRI, Superfund/contamination, landfills, PFAS, storage tanks and coal ash —
  so someone who heard "Wurtsmith", "Velsicol", "Wolverine" or "Wayne Disposal" in
  the news can find it), and **Chemicals**. Every place shows its **type + parent
  county** so Michigan's many duplicate names disambiguate at a glance (the canonical
  trap: *Oscoda County* inland vs *Oscoda Township* in Iosco County, on the Lake
  Huron shore by the former Wurtsmith AFB / PFAS site; *Grant* is a township in 10+
  counties). Multi-county places list all their counties. Selecting a place zooms to
  its bounds, drops a pin, opens its **parent county's** detail panel, and shows a
  banner explaining that county-level data covers the whole county — with a one-click
  path into the address-level report. Keyboard-navigable (↑/↓/Enter/Esc) and
  mobile-friendly. Data is the Census TIGER gazetteer loaded locally (no per-keystroke
  API call).
- **Heat-map view** — county choropleth, layer toggles (category / specific compound),
  Low/Avg/High estimate switch, total-vs-kg/mi² normalization, time slider
  (1992–2012) with play animation, click-for-county-detail with charts.
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
  top of the map: 105 sites (66 active Superfund NPL + deleted/
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
- **Landfills & waste-facilities overlay** — Michigan's licensed waste-disposal
  sites on top of the map: ~115 facilities pulled live from EGLE's Materials
  Management Open Data ArcGIS service — all active/accepting Part 115 solid-waste
  landfills (Type II municipal, Type III industrial / C&D / coal-ash) plus the
  disposal-capable Part 111 hazardous-waste facilities (e.g. Wayne Disposal).
  Toggleable in the left sidebar with type sub-filters (municipal / industrial /
  coal-ash / hazardous), a rounded-square marker colored by type on a dedicated
  pane, marker clustering, a "by type" legend key, and an earthy county-density
  choropleth ("Landfill density"). Each popup shows the operator, facility type,
  license status + ID, address, **what environmental monitoring is legally
  required at that facility type** (40 CFR Part 258 for Type II, the CCR rule for
  coal-ash, RCRA Subtitle C for hazardous), and — honestly — a note that
  monitoring *results* (groundwater/air/leachate) are not published online and
  must be requested from **EGLE by FOIA**, with a link. Where a landfill also
  appears in the app's own data it is **cross-linked**: a facility that reports to
  TRI shows its latest-year release total with a "show on map" button (Wayne
  Disposal → ~15.4M lbs), and one that is a contaminated/Superfund site links to
  that record — matched at load time by name-token overlap + coordinate proximity
  (precision-first, so a wrong link never fabricates releases). The county detail
  panel lists each county's landfills. **Coverage is honest about its limits:**
  the EGLE open-data layer is active-only — closed, post-closure, and
  pre-regulation (unlined) landfills, often the bigger contamination risk, are
  not comprehensively mapped here and many surface in the contamination overlay
  instead; capacity/volume and monitoring results are absent from the feed and
  are never guessed. Glossary adds Type II/III landfill, leachate, post-closure
  care, RCRA, TSDF, landfill gas, and FOIA.
- **Coal ash (CCR) sites overlay** — a curated, essentially-complete directory of
  Michigan's 17 coal combustion residuals facilities (mirroring EPA's list of
  publicly accessible CCR compliance sites): DTE's Monroe, Belle River, St. Clair,
  Trenton Channel and River Rouge; Consumers Energy's Campbell, Karn, Weadock,
  Whiting and B.C. Cobb (the last now closed by Charah/MERG); Lansing BWL's
  Erickson; plus Holland (De Young), Grand Haven (Sims), Marquette (Shiras),
  We Energies' Presque Isle, and the Harbor Beach & Morrow legacy impoundments.
  Because the federal **CCR rule is self-implementing** — each utility posts its
  own monitoring data on its own website, with no central database — this layer is
  a directory that **links to those official CCR pages** rather than aggregating
  live results. Rounded-square markers are colored by closure status (active /
  cap-in-place / closure-by-removal / retired / legacy), lettered by unit type
  (P = ash pond/impoundment, L = landfill), and **⚠-ringed when a unit is
  confirmed unlined** — the higher-risk kind. Popups carry the operator, units,
  lined/unlined status, closure method, and groundwater contaminants **attributed
  to the third parties that reported them** (Earthjustice / the Environmental
  Integrity Project, from utilities' own disclosures) with the utilities' dispute
  noted — never stated as established fact. They also surface a real **data gap**
  (DTE stopped posting post-2017 heavy-metal data for several impoundments,
  arguing clay walls prevent leaching; DTE contests the characterization),
  precision-first **cross-links** to the TRI / landfill / contamination layers
  (name-token overlap **plus** proximity, so city-named plants don't mislink), and
  clickable contaminant names → the PubChem chemical popup. Coal ash also appears
  in the "Check an Address" report and the Data Sources modal (EPA CCR rule, the
  2024 Legacy CCR Rule, EGLE, the utility CCR pages, and the EIP/Earthjustice
  Ashtracker database). Glossary adds coal combustion residuals, fly/bottom ash,
  boiler slag, flue-gas desulfurization material, surface impoundment,
  cap-in-place vs closure-by-removal, the CCR rule, and legacy impoundment.
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
| **US Census TIGER Gazetteer** places, county subdivisions & ZCTAs | ✅ live download | Powers the search box's city / village / township / CDP / ZIP lookup. Tiny, stable, pipe-delimited text tables (no shapefile/API-key dependency) parsed into the `places` table: 745 cities/villages/CDPs, 1,240 townships, ~990 Michigan ZIP areas. Each row carries a type + parent county so duplicate names disambiguate (Oscoda County inland vs Oscoda Township in Iosco, on the Lake Huron shore). Township parent county is exact (embedded in the cousub GEOID); places/ZIPs are located by point-in-polygon against the county boundaries. Centroid = Census internal point; bbox derived from land area for zoom-to-place. |
| **Pesticide categories** (herbicide / insecticide / fungicide / etc.) | ✅ embedded reference | Curated mapping built from EPA labels and university extension publications; see `app/categories.py`. |
| **USDA NASS Quick Stats** crop acreage | ⚙️ optional | Set `NASS_API_KEY=...` (free at quickstats.nass.usda.gov/api) before running the loader. |
| **NCI / CDC State Cancer Profiles** county cancer incidence & mortality, 2018–2022 | ✅ live download | County age-adjusted rates for 11 cancer types (incidence + mortality + late-stage). The site's `?…&output=1` export returns the empty HTML form to a browser but real CSV to the loader's `urllib` client; parsed rows land in `data/cancer/` and SQLite. Falls back to the Michigan statewide baseline in `app/cancer_data.py` if a fetch yields no county rows. |
| **Agricultural Health Study** + **IARC Monographs** | ✅ embedded reference | Compound→cancer evidence table (evidence level, IARC class, mechanism, key studies) in `app/cancer_data.py`; powers the evidence modal + matrix dots. |
| Michigan Cancer Surveillance Program (MCSP), CDC NPCR, NCI SEER, CDC WONDER | 🔗 reference link | Registry programs behind State Cancer Profiles; county extracts are portal/agreement-gated, not bulk feeds. |
| **EPA Superfund (SEMS) NPL sites** | ✅ live download | ~90 Michigan NPL sites (66 active, 22 deleted, 2 proposed) with coordinates, HRS score, status, county, listing date. ArcGIS Feature Service (org `cJ9YHowT8TU7DUyn`, `State='Michigan'`); merged/deduped with the compiled dataset. |
| **Compiled industrial polluters + PFAS sites** | ✅ embedded reference | 31 hand-compiled major sites (Dow, Velsicol/PBB, Wolverine/Hush Puppies PFAS, Torch Lake, McLouth Steel, GM, Kalamazoo River PCBs, Wurtsmith AFB, Gelman 1,4-dioxane, etc.) with company attribution, contaminant lists, narratives, impact radii, and affected waterways in `app/contamination_data.py`. Many are non-NPL and don't appear in the EPA feed. |
| Michigan EGLE Remediation & Redevelopment (Part 201), MPART (PFAS), EPA Region 5, MDHHS PBB Registry, ATSDR | 🔗 reference link | State/PFAS programs and toxicological references; portal-only or embedded, not bulk feeds. |
| **Michigan EGLE — Part 115 landfills & Part 111 hazardous-waste facilities** | ✅ live download | ~115 facilities from EGLE's Materials Management Open Data ArcGIS service (`gisagoegle.state.mi.us`, layers 6 + 7): all active/accepting Part 115 solid-waste landfills (Type II municipal, Type III industrial / C&D / coal-ash) plus disposal-capable Part 111 hazardous-waste TSDFs (a FacilityType containing "D", e.g. Wayne Disposal). Each carries operator, type, license status/ID, address, county, lat/lng, and the EGLE facility link. Cross-linked at load time to the app's TRI and Superfund records by name-token + coordinate matching (precision-first). Active-only — closed/pre-regulation landfills are not in the feed; capacity/volume and monitoring results are absent and never guessed. Powers the "Landfills & waste facilities" overlay, the "Landfill density" choropleth, and the per-county rollup. |
| Michigan EGLE Materials Management Division (solid-waste disposal areas) | 🔗 reference link | Searchable list + interactive map of Type II / Type III disposal areas and annual solid-waste reports; source of the Part 115 layer. |
| EPA Landfill Methane Outreach Program (LMOP) | 🔗 reference link | National landfill methane generation / gas-collection & energy-project database, published as a bulk file (no per-facility API); referenced for landfill-gas context, not joined per facility. |
| EPA RCRAInfo / Envirofacts (RCRA Subtitle C) | 🔗 reference link | Federal hazardous-waste facility system behind the Part 111 TSDFs; the mapped disposal facilities come from EGLE's state layer. |
| **Coal ash (CCR) sites** — Michigan's 17 coal combustion residuals facilities | ✅ embedded reference | Curated directory in `app/coal_ash_data.py`, web-verified against EPA's list of publicly accessible CCR compliance sites, each operator's CCR page (DTE, Consumers, LBWL, Holland BPW, Grand Haven BLP, Marquette BLP, We Energies, Charah/MERG, ccrsites.com), Earthjustice/EIP Ashtracker, and utility retirement notices. Coordinates from plant infoboxes or geocoded street addresses (a few flagged approximate). The CCR rule is self-implementing (no central feed), so this links to each utility's official page rather than aggregating live results; contaminant findings are attributed to Earthjustice/EIP with the utilities' dispute noted, and the DTE post-2017 data gap is surfaced. Precision-first cross-links (name-token + proximity) to TRI/landfill/contamination. Powers the "Coal ash sites" overlay and its entries in the address report + Data Sources modal. |
| EPA Coal Combustion Residuals (CCR) rule, 2024 Legacy CCR Rule, Michigan EGLE coal-ash program, EIP/Earthjustice Ashtracker | 🔗 reference link | The federal self-implementing rule (each utility posts its own data), the 2024 rule extending to legacy impoundments, Michigan's Part 115 oversight, and the watchdog groundwater database behind the (attributed, disputed) contaminant findings. |
| **EPA Toxics Release Inventory (TRI)** — active industrial releases, 2013–2024 | ✅ live download | ~1,090 Michigan facilities and ~37k facility-chemical-year release records from the Envirofacts `mv_tri_basic_download` view (filtered `st=MI`, one CSV per year). Each record carries county, lat/lng, NAICS + plain-language industry sector, PFAS/carcinogen flags, and pounds released per pathway (air = fugitive + stack, water, underground, land). Complements the legacy Superfund layer by showing what facilities are *actively* releasing now. Self-reported annually under EPCRA. Powers factory markers, the "TRI toxic releases" choropleth (with air/water/land/PFAS sub-options), correlation X-variables, and a year-over-year trend. No API key required. |
| **PubChem (NCBI)** chemical descriptions & properties | ✅ live download (cached) | Real plain-language descriptions, molecular formula/weight, CAS, common synonyms and PubChem CID for every chemical/compound in the data (pesticides, TRI chemicals, water detections). Pre-fetched once via the re-runnable `enrich_chemicals.py` (PUG REST, no API key, rate-limited) into the `chemical_reference` table, so the chemical-info popups read locally with no live call on click. Complements — does not replace — the EPA/IARC hazard classifications. |
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

### Publishing the refreshed database (deploy step)

The database is **not committed to git** — it's a GitHub Release asset (fixed tag
`data`) that the Render build downloads. So after refreshing locally, you **upload
the new DB to the Release** instead of committing it. The download URL never
changes, so nothing in the build has to be edited.

```bash
python refresh_data.py            # 1. refresh the local DB as usual
python scripts/publish_db.py      # 2. hash it, write the .sha256, upload the asset
```

`publish_db.py` computes the SHA-256, writes a `data/michigan_pesticides.sqlite.sha256`
sidecar (the build verifies against it), then:

- **If the [GitHub CLI](https://cli.github.com) (`gh`) is installed and authenticated**,
  it creates the `data` release if needed and uploads both files with `--clobber`
  (replacing the previous copies). One command, done.
- **If `gh` isn't installed**, it prints exact step-by-step instructions to attach
  the two files through the GitHub web UI, and the fixed asset URL to expect.

Then trigger a deploy (Render auto-deploys on push, or use **Manual Deploy** in the
Render dashboard). The build runs `scripts/fetch_db.py`, which downloads the new
asset, verifies its size and SHA-256, and only then swaps it into place — a failed
or truncated download **fails the build** rather than shipping a broken app.

> **First-time setup:** you must create the `data` release once (either
> `python scripts/publish_db.py` with `gh`, or the web-UI steps it prints) *before*
> the first Render deploy, or the build will have nothing to download and will fail
> loudly by design. The asset lives at:
> `https://github.com/tbuttaflocka/michigan-pesticide-map/releases/download/data/michigan_pesticides.sqlite`

> **Why not commit the DB or use Git LFS?** At ~90 MB it's over GitHub's 50 MB
> warning and near the 100 MB hard limit, and every committed copy bloats history
> permanently. Git LFS was rejected too: the free tier's 1 GB/month bandwidth cap
> would be exhausted quickly because Render pulls the file on every deploy, and
> hitting the cap breaks deploys. A Release asset has no such bandwidth cap.

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
| `landfills` (EGLE Part 115 / Part 111) | **Quarterly** | Facility licensing/status changes through the year; EGLE refreshes the open-data layers periodically. |
| `places` (Census TIGER gazetteer) | **Annual** | The gazetteer is republished yearly; the search index rarely needs updating. |

### Scheduling on Windows (Task Scheduler)

`refresh_data.py` does **not** schedule itself — set it up with the built-in
Task Scheduler. Use the full path to the venv's Python and to the script, and
quote paths that contain spaces. A simple approach is one monthly all-sources
run (the per-source guards make it a no-op for anything already current):

```bat
schtasks /create /tn "PesticideMap Refresh" /sc MONTHLY /d 1 /st 03:00 ^
  /tr "\"C:\path\to\michigan-pesticide-map\.venv\Scripts\python.exe\" \"C:\path\to\michigan-pesticide-map\refresh_data.py\""
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

## Disclaimer & limitations

This is an **independent, non-commercial educational project**. It compiles publicly
available data from USGS, EPA, CDC, NCI, USDA, and Michigan state agencies; it is **not
affiliated with or endorsed by** any of them. It is provided for **exploration and
education only** and is **not medical, legal, regulatory, or scientific advice**.

**Correlation is not causation.** The comparison tools show whether two things rise and
fall together across counties. That is a starting point for questions — never proof that
one causes the other. County-level (ecological) comparisons cannot establish individual
risk (the *ecological fallacy*), and counties differ in age, income, industry, smoking,
and screening in ways that independently affect health (confounding).

Known limitations, by source:

| Source | Key limitations |
| --- | --- |
| **USGS NAWQA EPest** (pesticide use) | *Modeled estimates*, not measurements — derived from proprietary sales + crop-extent models and reported as a low/high range. Covers crop-protection use only (no lawn/golf/aquatic use). Latest finalized years lag by several years. |
| **EPA TRI** (industrial releases) | *Self-reported* annually by facilities above size/chemical thresholds; **undercounts** — small emitters and non-covered industries are excluded. Reporting a release does not mean it is illegal or unsafe. |
| **NCI/CDC State Cancer Profiles** | Cancer has **10–30 year latency**, so current rates reflect past exposure. Counts under a threshold (≈16 cases) are **suppressed**, leaving gaps. Ecological comparison only. |
| **CDC Environmental Tracking** (respiratory) | Annual, county-level, age-adjusted; some measures fall back to a Michigan statewide baseline where county breakdowns aren't published. Urban asthma is driven mostly by air quality/industry, not farming. |
| **EPA Superfund / compiled sites** | Point locations and status change over time; the compiled set is a curated subset, not an exhaustive inventory of every contaminated site. |
| **Michigan EGLE landfills** | The Part 115 open-data layer is **active/accepting only** — closed, post-closure, and pre-regulation (unlined) landfills, often the bigger contamination risk, are not comprehensively mapped (many appear in the contamination layer instead). Capacity/volume is not in the feed. **Monitoring results** (groundwater/air/leachate) are legally required but not published online — request them from EGLE by FOIA. Part 111 markers cover disposal-capable hazardous-waste facilities, not storage/treatment-only sites. |
| **USGS/EPA Water Quality Portal** | Sampling is uneven in space and time; absence of detections can reflect a lack of sampling, not clean water. |
| **IEM ASOS wind** | Prevailing growing-season wind at a handful of airport stations; drift arrows are a coarse approximation, not a dispersion model. |

The in-app **Data sources** dialog shows each source's coverage window and last-refresh
date. Coverage years, refresh cadence, and per-source status are listed above under
[Data sources](#data-sources) and [Keeping the data fresh](#keeping-the-data-fresh).

## Architecture

```
michigan-pesticide-map/
├── app.py                  Flask server + REST API
├── refresh_data.py         Safe, staged data-refresh harness (scheduled)
├── enrich_chemicals.py     Cache PubChem chemical info (re-runnable)
├── enrich_narratives.py    Fill contamination-site narratives (re-runnable)
├── scripts/
│   ├── fetch_db.py         Download + verify the prebuilt DB (build/local)
│   └── publish_db.py       Hash + upload the DB as a GitHub Release asset
├── app/
│   ├── config.py           Paths, URLs, env wiring
│   ├── database.py         SQLite schema + connection helper
│   ├── data_loader.py      Downloads + ingests all data
│   ├── chemical_reference.py  PubChem client + chemical_reference cache
│   └── categories.py       Compound -> category lookup
├── data/                   Raw downloads + SQLite DB (fetched, not committed)
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
| `GET /api/search?q=` | Grouped type-ahead search over **places** (city/village/township/CDP/ZIP, each with its type + parent county for disambiguation), counties, **facilities** (named sites across TRI/Superfund/landfills/PFAS/UST/coal-ash), and chemicals |
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
| `GET /api/landfill/sites?category=` | All landfills & waste facilities with coordinates, type glyph/color, status, monitoring context, FOIA link, and TRI/Superfund cross-links; includes the type/status legend |
| `GET /api/landfill/county/<fips>` | Landfills & waste facilities in one county |
| `GET /api/landfill/density` | Per-county landfill counts (total / hazardous / municipal) for the density choropleth |

## Notes on data limitations

USGS EPest values are **estimates**, not field-reported measurements. They are derived
from proprietary pesticide-sale data combined with crop-acreage models. The Low and High
brackets reflect the published uncertainty range; the UI defaults to the average of the
two. Only **agricultural** use is included — lawn-care, golf-course, and aquatic
non-agricultural applications are out of scope. See USGS Data Series 907 for full
methodology.
