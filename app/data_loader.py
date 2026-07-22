"""
Downloads real data from USGS NAWQA, US Census GeoJSON, and (optionally) USDA NASS,
filters everything to Michigan, and populates the SQLite database.

Run as:  python -m app.data_loader
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import database
from . import stats
from .categories import categorize
from .config import (
    COUNTIES_GEOJSON_URL,
    DATA_DIR,
    GEOJSON_PATH,
    MI_HUC8_GEOJSON_PATH,
    MICHIGAN_STATE_FIPS,
    NASS_API_KEY,
    NASS_API_URL,
    USGS_BASE,
    USGS_SCIENCEBASE_DATASETS,
    USGS_YEARS,
    WBD_HUC8_QUERY,
    WQP_RESULT_URL,
    WQP_STATION_URL,
    IEM_ASOS_URL,
    WIND_YEARS,
    WIND_SEASON_MONTHS,
    WIND_CACHE_DIR,
    TRI_MV_URL,
    TRI_STATE_ABBR,
    TRI_START_YEAR,
    TRI_END_YEAR,
    TRI_CACHE_DIR,
)
from .wind_data import MI_ASOS_STATIONS, DIRS_16, deg_to_dir16, dir16_to_deg
from .water_quality import (
    AQUATIC_LIFE_BENCHMARKS,
    NAWQA_MI_STREAMS,
    PESTICIDE_MCL,
    canonicalize_compound,
    threshold_for,
    to_ugl,
)
from .respiratory_data import (
    MI_BROADER_RESP_BASELINE,
    MI_STATEWIDE_BASELINE,
    URBAN_COUNTIES,
)
from . import cancer_data
from . import contamination_data
from .config import (
    CANCER_DATA_DIR,
    EPA_NPL_QUERY,
    NCI_INCIDENCE_URL,
    NCI_MORTALITY_URL,
    NCI_SCP_BASE,
)


# ---------- pretty logging ----------

def log(msg: str, *, level: str = "info") -> None:
    sym = {"info": "[*]", "ok": "[OK]", "warn": "[!]", "err": "[X]"}[level]
    print(f"{sym} {msg}", flush=True)


# ---------- HTTP ----------

USER_AGENT = "MichiganPesticideMap/1.0 (+local research tool)"


def http_get(url: str, *, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_to(url: str, path: Path, *, timeout: int = 120) -> int:
    """Download to disk, return byte count.

    http_get reads the full response before we touch the file, so a failed
    fetch raises and leaves any existing cache file untouched — which is what
    makes force-refresh safe (a network blip never destroys good cached data).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = http_get(url, timeout=timeout)
    path.write_bytes(data)
    return len(data)


def download_stream(
    url: str,
    path: Path,
    *,
    timeout: int = 600,
    attempts: int = 4,
    min_bytes: int = 1,
    backoff: int = 5,
) -> int:
    """Resilient large-file download. Returns the number of bytes written.

    Built for the ~230 MB Water Quality Portal result CSV, which the portal
    generates on the fly and streams over a connection that sometimes drops near
    the end (urllib then raises ``IncompleteRead`` and the whole in-memory read
    is lost). This helper instead:

      * streams the body to a temporary ``.part`` file in 1 MiB chunks, so a
        huge response never has to fit in memory;
      * verifies the byte count against ``Content-Length`` when the server sends
        it, so a silent short read is caught;
      * retries the *entire* transfer (with linear backoff) on any transient
        network error;
      * only on a clean, size-verified download does it atomically move the
        ``.part`` file into place — a partial transfer never replaces good data.

    We deliberately do NOT attempt HTTP Range "resume": the WQP result endpoint
    regenerates the CSV per request, so stitching a byte offset from one
    generation onto another could silently corrupt the file. A clean full retry
    is the safe choice.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    last_err: Exception | None = None

    for attempt in range(1, attempts + 1):
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                cl = resp.headers.get("Content-Length")
                expected = int(cl) if cl and cl.isdigit() else None
                written = 0
                with part.open("wb") as fh:
                    while True:
                        chunk = resp.read(1 << 20)   # 1 MiB
                        if not chunk:
                            break
                        fh.write(chunk)
                        written += len(chunk)
            if expected is not None and written < expected:
                raise IOError(f"short read: got {written:,} of {expected:,} bytes")
            if written < min_bytes:
                raise IOError(f"suspiciously small download: {written:,} bytes")
            part.replace(path)                       # atomic within the dir
            return written
        except Exception as e:                        # noqa: BLE001 — retry anything transient
            last_err = e
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
            if attempt < attempts:
                wait = backoff * attempt
                log(f"  download attempt {attempt}/{attempts} failed ({e}); "
                    f"retrying in {wait}s", level="warn")
                time.sleep(wait)

    assert last_err is not None
    raise last_err


# When true, cached files for *mutable* sources (currently the Water Quality
# Portal sample CSVs) are re-downloaded instead of reused. refresh_data.py sets
# this. Immutable/archival caches (finalized USGS EPest files, historical IEM
# wind, watershed boundaries) are intentionally NOT force-refreshed — re-running
# their loader still picks up any newly *configured* years without re-pulling
# hundreds of MB that never change.
FORCE_REFRESH = os.environ.get("REFRESH_FORCE", "") == "1"


def _need_download(path: Path, min_size: int, *, force: bool = False) -> bool:
    """True if the cache file is missing, implausibly small, or a force-refresh
    of a mutable source was requested."""
    return force or (not path.exists()) or path.stat().st_size < min_size


# ---------- data source bookkeeping ----------

def record_source(
    conn: sqlite3.Connection,
    source_id: str,
    title: str,
    url: str,
    status: str,
    rows_loaded: int = 0,
    notes: str = "",
    *,
    coverage_start: str | None = None,
    coverage_end: str | None = None,
    refresh_status: str | None = None,
    refresh_interval_months: int | None = None,
    last_success: str | None = None,
    last_attempt: str | None = None,
) -> None:
    """Upsert a data_sources row.

    The seven base columns (title..last_updated) are always overwritten. The
    optional provenance/freshness columns are only written when a non-None value
    is supplied — otherwise the existing value is preserved via COALESCE, so an
    ordinary loader call never clobbers freshness metadata that refresh_data.py
    stamped on a previous run.
    """
    conn.execute(
        """
        INSERT INTO data_sources(
            source_id, title, url, status, rows_loaded, notes, last_updated,
            coverage_start, coverage_end, refresh_status,
            refresh_interval_months, last_success, last_attempt)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            status=excluded.status,
            rows_loaded=excluded.rows_loaded,
            notes=excluded.notes,
            last_updated=excluded.last_updated,
            coverage_start=COALESCE(excluded.coverage_start, data_sources.coverage_start),
            coverage_end=COALESCE(excluded.coverage_end, data_sources.coverage_end),
            refresh_status=COALESCE(excluded.refresh_status, data_sources.refresh_status),
            refresh_interval_months=COALESCE(excluded.refresh_interval_months, data_sources.refresh_interval_months),
            last_success=COALESCE(excluded.last_success, data_sources.last_success),
            last_attempt=COALESCE(excluded.last_attempt, data_sources.last_attempt)
        """,
        (
            source_id, title, url, status, rows_loaded, notes,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            coverage_start, coverage_end, refresh_status,
            refresh_interval_months, last_success, last_attempt,
        ),
    )


# ---------- 1. Michigan counties GeoJSON ----------

def load_counties_geojson(conn: sqlite3.Connection) -> int:
    log("Downloading US counties GeoJSON (plotly mirror of Census TIGER/Line)...")
    raw_path = DATA_DIR / "geojson-counties-fips.json"
    try:
        size = download_to(COUNTIES_GEOJSON_URL, raw_path)
        log(f"  fetched {size/1024:.0f} KB -> {raw_path.name}", level="ok")
    except Exception as e:
        log(f"  GeoJSON download failed: {e}", level="err")
        record_source(conn, "geojson_counties", "US Census TIGER counties GeoJSON",
                      COUNTIES_GEOJSON_URL, "unavailable", 0, str(e))
        return 0

    full = json.loads(raw_path.read_text())
    mi_features = []
    for feat in full.get("features", []):
        fid = str(feat.get("id", ""))
        props = feat.get("properties", {})
        state = props.get("STATE") or fid[:2]
        if state != MICHIGAN_STATE_FIPS:
            continue
        # Normalise properties so the frontend has stable keys
        county_fips = props.get("COUNTY") or fid[2:]
        feat["id"] = fid or f"{MICHIGAN_STATE_FIPS}{county_fips}"
        feat["properties"] = {
            "fips": feat["id"],
            "name": props.get("NAME", ""),
            "state_fips": state,
            "county_fips": county_fips,
            "area_sq_miles": props.get("CENSUSAREA"),
        }
        mi_features.append(feat)

    mi_geo = {"type": "FeatureCollection", "features": mi_features}
    GEOJSON_PATH.write_text(json.dumps(mi_geo))
    log(f"  wrote {len(mi_features)} Michigan counties -> {GEOJSON_PATH.name}", level="ok")

    rows = 0
    for f in mi_features:
        p = f["properties"]
        conn.execute(
            """INSERT OR REPLACE INTO counties(fips, name, state_fips, county_fips, area_sq_miles)
               VALUES (?, ?, ?, ?, ?)""",
            (p["fips"], p["name"], p["state_fips"], p["county_fips"], p["area_sq_miles"]),
        )
        rows += 1
    conn.commit()
    record_source(conn, "geojson_counties", "Michigan county boundaries (Census TIGER via plotly)",
                  COUNTIES_GEOJSON_URL, "ok", rows,
                  "Filtered to STATE FIPS 26. 83 counties expected.")
    return rows


# ---------- 2. USGS NAWQA EPest county-level pesticide use ----------

def load_usgs_pesticide_use(conn: sqlite3.Connection) -> tuple[int, set[int], list[str]]:
    """Download and ingest every USGS NAWQA EPest dataset available:
       * 1992-2012 — legacy per-year text files
       * 2013-2017 — finalized v2.0 ScienceBase bundle
       * 2018, 2019 — preliminary ScienceBase releases

    Returns (rows_inserted, years_ok_set, failed_labels).
    """
    rows_total = 0
    ok_years: set[int] = set()
    failed_labels: list[str] = []

    # --- legacy per-year files ---
    for year in USGS_YEARS:
        url = f"{USGS_BASE}/EPest.county.estimates.{year}.txt"
        local = DATA_DIR / f"EPest.county.estimates.{year}.txt"
        log(f"USGS EPest {year} -> downloading...")
        try:
            if not local.exists() or local.stat().st_size < 1000:
                size = download_to(url, local, timeout=180)
                log(f"  fetched {size/1_000_000:.1f} MB", level="ok")
            else:
                log(f"  using cached {local.name} ({local.stat().st_size/1_000_000:.1f} MB)")
        except urllib.error.HTTPError as e:
            log(f"  HTTP {e.code} for {year} — skipping", level="warn")
            failed_labels.append(str(year))
            continue
        except Exception as e:
            log(f"  download failed: {e}", level="warn")
            failed_labels.append(str(year))
            continue

        inserted, years_in_file = _ingest_epest_file(conn, local)
        rows_total += inserted
        ok_years.update(years_in_file)
        log(f"  inserted {inserted:,} Michigan rows for {year}", level="ok")

    # --- ScienceBase bundles (2013-17, 2018, 2019) ---
    for label, source_url, file_url, filename in USGS_SCIENCEBASE_DATASETS:
        local = DATA_DIR / filename
        log(f"USGS EPest {label} -> downloading...")
        try:
            if not local.exists() or local.stat().st_size < 100_000:
                size = download_to(file_url, local, timeout=600)
                log(f"  fetched {size/1_000_000:.1f} MB -> {local.name}", level="ok")
            else:
                log(f"  using cached {local.name} ({local.stat().st_size/1_000_000:.1f} MB)")
        except Exception as e:
            log(f"  download failed for {label}: {e}", level="warn")
            failed_labels.append(label)
            continue
        inserted, years_in_file = _ingest_epest_file(conn, local)
        rows_total += inserted
        ok_years.update(years_in_file)
        ys = sorted(years_in_file)
        span = f"{ys[0]}-{ys[-1]}" if ys else "no years"
        log(f"  inserted {inserted:,} Michigan rows ({span}) for {label}", level="ok")

    notes = []
    if ok_years:
        notes.append(f"Years loaded: {len(ok_years)} "
                     f"({min(ok_years)}-{max(ok_years)})")
    else:
        notes.append("No years loaded")
    if failed_labels:
        notes.append(f"Unavailable: {','.join(failed_labels)}")
    notes.append("2020-2022 final estimates: USGS plans publication in 2026 "
                 "(per the NAWQA county-level page).")
    record_source(conn, "usgs_epest",
                  "USGS NAWQA EPest — Estimated Annual Agricultural Pesticide Use",
                  USGS_BASE,
                  "ok" if ok_years else "unavailable",
                  rows_total,
                  " | ".join(notes))
    conn.commit()
    return rows_total, ok_years, failed_labels


def _ingest_epest_file(conn: sqlite3.Connection, path: Path) -> tuple[int, set[int]]:
    """Insert Michigan rows from a USGS EPest tab-delimited file. The file may
    cover one year (legacy 1992-2012 files) or multiple years (the 2013-17
    bundle). Returns (rows_inserted, set_of_years_seen)."""
    inserted = 0
    compounds: set[str] = set()
    years_seen: set[int] = set()
    cur = conn.cursor()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader, None)
        if not header or header[0].upper() != "COMPOUND":
            log(f"  unexpected header in {path.name}: {header}", level="warn")
            return 0, years_seen
        batch: list[tuple] = []
        for row in reader:
            if len(row) < 6:
                continue
            compound, yr, sfips, cfips, low, high = (c.strip() for c in row[:6])
            if sfips != MICHIGAN_STATE_FIPS:
                continue
            try:
                low_f = float(low) if low not in ("", "NA") else None
                high_f = float(high) if high not in ("", "NA") else None
                yr_i = int(yr)
            except ValueError:
                continue
            full_fips = f"{sfips}{cfips.zfill(3)}"
            batch.append((full_fips, compound, yr_i, low_f, high_f))
            compounds.add(compound)
            years_seen.add(yr_i)
            if len(batch) >= 5000:
                cur.executemany(
                    "INSERT OR REPLACE INTO pesticide_use VALUES (?,?,?,?,?)", batch
                )
                inserted += len(batch)
                batch.clear()
        if batch:
            cur.executemany(
                "INSERT OR REPLACE INTO pesticide_use VALUES (?,?,?,?,?)", batch
            )
            inserted += len(batch)
    conn.commit()

    for c in compounds:
        cur.execute(
            "INSERT OR REPLACE INTO pesticide_categories(compound, category) VALUES (?, ?)",
            (c, categorize(c)),
        )
    conn.commit()
    return inserted, years_seen


# ---------- 3. Optional: USDA NASS Quick Stats crop acreage ----------

NASS_CROPS = [
    "CORN", "SOYBEANS", "WHEAT", "SUGARBEETS", "DRY BEANS",
    "POTATOES", "APPLES", "BLUEBERRIES", "CHERRIES, TART", "CHERRIES, SWEET",
]


def load_nass_crop_acreage(conn: sqlite3.Connection) -> int:
    if not NASS_API_KEY:
        log("NASS API key not set (env NASS_API_KEY) — skipping crop acreage", level="warn")
        record_source(conn, "nass_acreage",
                      "USDA NASS Quick Stats — Michigan crop acreage",
                      NASS_API_URL, "skipped", 0,
                      "Set NASS_API_KEY environment variable to enable. "
                      "Free key at https://quickstats.nass.usda.gov/api")
        conn.commit()
        return 0

    log("Querying USDA NASS Quick Stats for Michigan crop acreage...")
    inserted = 0
    crops_ok = 0
    # Field crops report "AREA HARVESTED"; tree/bush fruits report "AREA
    # BEARING" (and NASS returns HTTP 400 for a param combo that matches no
    # records), so try each category in turn and keep the first that has data.
    stat_cats = ["AREA HARVESTED", "AREA BEARING", "AREA GROWN", "AREA PLANTED"]
    for crop in NASS_CROPS:
        crop_rows = 0
        for stat in stat_cats:
            params = {
                "key": NASS_API_KEY,
                "source_desc": "SURVEY",
                "sector_desc": "CROPS",
                "commodity_desc": crop,
                "statisticcat_desc": stat,
                "unit_desc": "ACRES",
                "agg_level_desc": "COUNTY",
                "state_alpha": "MI",
                "format": "JSON",
            }
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
            url = f"{NASS_API_URL}?{qs}"
            try:
                raw = http_get(url, timeout=60)
                data = json.loads(raw).get("data", [])
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    continue      # no records for this statistic — try the next
                log(f"  NASS {crop}: {e}", level="warn")
                break
            except Exception as e:
                log(f"  NASS {crop}: {e}", level="warn")
                break
            if not data:
                continue
            cur = conn.cursor()
            for rec in data:
                try:
                    year = int(rec.get("year", 0))
                    county_code = rec.get("county_code", "")
                    if not county_code or len(county_code) != 3:
                        continue
                    fips = f"{MICHIGAN_STATE_FIPS}{county_code}"
                    val = rec.get("Value", "").replace(",", "")
                    if val in ("(D)", "(NA)", "(Z)", ""):
                        continue
                    acres = float(val)
                except (ValueError, AttributeError):
                    continue
                cur.execute(
                    """INSERT OR REPLACE INTO crop_acreage(county_fips, crop, year,
                       acres_harvested, acres_planted) VALUES (?,?,?,?,?)""",
                    (fips, crop, year, acres, None),
                )
                inserted += 1
                crop_rows += 1
            conn.commit()
            log(f"  {crop} ({stat.lower()}): +{crop_rows} county rows", level="ok")
            crops_ok += 1
            break            # got data for this crop; don't try more categories
        else:
            log(f"  {crop}: no county-level acreage published by NASS", level="warn")
        time.sleep(0.4)      # be polite to the API

    record_source(conn, "nass_acreage",
                  "USDA NASS Quick Stats — Michigan crop acreage",
                  NASS_API_URL, "ok", inserted,
                  f"Survey data, county-level, area harvested/bearing. "
                  f"{crops_ok} of {len(NASS_CROPS)} crops available.")
    conn.commit()
    return inserted


# ---------- 4. Reference-only sources ----------

def record_reference_sources(conn: sqlite3.Connection) -> None:
    record_source(
        conn, "mdard_registration",
        "MDARD Pesticide Registration Database",
        "https://www.michigan.gov/mdard/licensing/pesticide/pestregistration",
        "skipped", 0,
        "MDARD provides this only as an interactive page, not a bulk feed. "
        "Linked in the UI for reference.",
    )
    record_source(
        conn, "mdard_inspectors",
        "MDARD Pesticide Inspectors by County",
        "https://www.michigan.gov/en/mdard/plant-pest/Pesticides/Pesticide-Regulatory-Info",
        "skipped", 0,
        "Inspector assignments change frequently; UI links to the MDARD page rather "
        "than caching a stale list.",
    )
    record_source(
        conn, "egle_npdes",
        "Michigan EGLE Pesticide General Permit (NPDES)",
        "https://www.michigan.gov/egle/about/organization/water-resources/npdes/pesticide-control",
        "skipped", 0,
        "No downloadable structured dataset published; reference only.",
    )
    record_source(
        conn, "usda_cdl",
        "USDA Cropland Data Layer",
        "https://nassgeodata.gmu.edu/CropScape/",
        "skipped", 0,
        "Multi-GB raster; not bundled here. Use NASS Quick Stats for tabular acreage.",
    )
    record_source(
        conn, "mdard_arcgis",
        "MDARD Maps & Open Data Hub",
        "https://gis-mimdard.hub.arcgis.com/",
        "skipped", 0,
        "Hub contains licensing/inspection layers behind dynamic ArcGIS REST endpoints. "
        "Linked for users who want to drill in.",
    )


# ---------- 6. Pre-compute correlation_analysis ----------

def build_correlation_table(conn: sqlite3.Connection) -> int:
    """Join the latest-year pesticide totals with county respiratory rates."""
    cur = conn.cursor()
    cur.execute("DELETE FROM correlation_analysis")

    latest_year = cur.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]
    if latest_year is None:
        return 0

    # Aggregate pesticide use per county for the latest year.
    rows = cur.execute("""
        SELECT
            c.fips, c.name, c.area_sq_miles,
            COALESCE(SUM((pu.epest_low_kg + pu.epest_high_kg)/2.0), 0) AS total_kg,
            COALESCE(SUM(CASE WHEN pc.category='herbicide'
                              THEN (pu.epest_low_kg + pu.epest_high_kg)/2.0
                              ELSE 0 END), 0) AS herb_kg,
            COALESCE(SUM(CASE WHEN pc.category='insecticide'
                              THEN (pu.epest_low_kg + pu.epest_high_kg)/2.0
                              ELSE 0 END), 0) AS insect_kg,
            COALESCE(SUM(CASE WHEN pc.category='fungicide'
                              THEN (pu.epest_low_kg + pu.epest_high_kg)/2.0
                              ELSE 0 END), 0) AS fung_kg
        FROM counties c
        LEFT JOIN pesticide_use pu
          ON pu.county_fips = c.fips AND pu.year = ?
        LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
        GROUP BY c.fips, c.name, c.area_sq_miles
    """, (latest_year,)).fetchall()

    # Latest respiratory rates per county per condition (most recent year).
    resp = {}
    for r in cur.execute("""
        SELECT county_fips, condition, visit_rate
          FROM respiratory_ed_visits ed
         WHERE year = (SELECT MAX(year) FROM respiratory_ed_visits
                        WHERE county_fips = ed.county_fips AND condition = ed.condition)
    """):
        resp.setdefault(r["county_fips"], {})[f"ed_{r['condition']}"] = r["visit_rate"]
    for r in cur.execute("""
        SELECT county_fips, condition, hosp_rate
          FROM respiratory_hospitalizations h
         WHERE year = (SELECT MAX(year) FROM respiratory_hospitalizations
                        WHERE county_fips = h.county_fips AND condition = h.condition)
    """):
        resp.setdefault(r["county_fips"], {})[f"hosp_{r['condition']}"] = r["hosp_rate"]

    prev_lookup: dict[str, float] = {}
    for r in cur.execute("""
        SELECT county_fips, prevalence_pct FROM respiratory_prevalence
         WHERE condition='asthma' AND age_group='adult'
    """):
        prev_lookup[r["county_fips"]] = r["prevalence_pct"]

    inserted = 0
    for r in rows:
        fips = r["fips"]
        per_sq_mi = (r["total_kg"] / r["area_sq_miles"]) if r["area_sq_miles"] else None
        resp_row = resp.get(fips, {})
        cur.execute(
            """INSERT INTO correlation_analysis(
                 county_fips, county, total_pesticide_kg, pesticide_per_sq_mile,
                 herbicide_kg, insecticide_kg, fungicide_kg, area_sq_miles,
                 is_urban, asthma_ed_rate, asthma_hosp_rate,
                 copd_ed_rate, copd_hosp_rate, asthma_prevalence_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fips, r["name"], r["total_kg"], per_sq_mi,
                r["herb_kg"], r["insect_kg"], r["fung_kg"],
                r["area_sq_miles"],
                1 if r["name"] in URBAN_COUNTIES else 0,
                resp_row.get("ed_asthma"),
                resp_row.get("hosp_asthma"),
                resp_row.get("ed_copd"),
                resp_row.get("hosp_copd"),
                prev_lookup.get(fips),
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


# ---------- 7. Respiratory illness (CDC EPHT Tracking API) ----------

CDC_API = "https://ephtracking.cdc.gov/apigateway/api/v1"

# Asthma & COPD content-area IDs (resolved from /contentareas/json).
CDC_AREA_ASTHMA = 3
CDC_AREA_COPD = 23

# Year window. The Tracking API getCoreHolder accepts a comma-separated
# list of years or the literal "ALL".
CDC_YEARS = list(range(2010, 2024))


def cdc_request(url: str, *, method: str = "GET", body: dict | None = None,
                max_retries: int = 3) -> object:
    """Call a CDC EPHT endpoint with exponential backoff. Supports GET + POST."""
    delays = [2, 4, 8, 16]
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(max_retries + 1):
        try:
            if method == "POST":
                data = json.dumps(body or {}).encode("utf-8")
                headers["Content-Type"] = "application/json"
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            else:
                req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("code") in (400, 401, 403, 429, 500, 503):
                code = payload.get("code")
                msg = payload.get("message", "")
                if code == 429 and attempt < max_retries:
                    log(f"  CDC 429 throttle — sleeping {delays[attempt]}s (try {attempt+1})", level="warn")
                    time.sleep(delays[attempt])
                    continue
                raise RuntimeError(f"CDC API error {code}: {msg}")
            return payload
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                log(f"  CDC HTTP 429 — sleeping {delays[attempt]}s", level="warn")
                time.sleep(delays[attempt])
                continue
            if attempt == max_retries:
                raise
            log(f"  CDC HTTP {e.code} — sleeping {delays[attempt]}s", level="warn")
            time.sleep(delays[attempt])
        except Exception as e:
            if attempt == max_retries:
                raise
            log(f"  CDC fetch error: {e} — sleeping {delays[attempt]}s", level="warn")
            time.sleep(delays[attempt])
    raise RuntimeError("CDC API failed after retries")


# Backwards-compatible alias.
def cdc_get(url: str, **kw) -> object:
    return cdc_request(url, **kw)


# Age-adjusted rate per 10,000 population — discovered via /measuresearch.
# strat level 2 = "State x County" (county-level).
CDC_MEASURES = [
    # (table, rate_column, measureId, stratLevelId, condition, label)
    ("respiratory_ed_visits",        "visit_rate", 437, 2, "asthma", "Asthma ED rate"),
    ("respiratory_hospitalizations", "hosp_rate",  103, 2, "asthma", "Asthma hosp rate"),
    ("respiratory_ed_visits",        "visit_rate", 652, 2, "copd",   "COPD ED rate"),
    ("respiratory_hospitalizations", "hosp_rate",  649, 2, "copd",   "COPD hosp rate"),
]


def _county_fips_list(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [(r["fips"], r["name"])
            for r in conn.execute("SELECT fips, name FROM counties ORDER BY fips")]


def _is_suppressed(v) -> bool:
    return v is None or str(v).strip() in ("", "Suppressed", "S", "*", "(D)", "NA")


def _ingest_core_holder(
    conn: sqlite3.Connection,
    payload: object,
    table: str,
    rate_col: str,
    condition: str,
    county_lookup: dict[str, str],
) -> int:
    """Parse a getCoreHolder POST response and insert per-county-per-year rates."""
    if not isinstance(payload, dict):
        return 0
    # The API returns table data under "tableResult" most commonly, but also
    # "result", "data", and (older) "tableData". Tolerate all variants.
    rows = (payload.get("tableResult") or payload.get("result")
            or payload.get("data") or payload.get("tableData") or [])
    cur = conn.cursor()
    inserted = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        geo = r.get("geoId") or r.get("countyFips") or ""
        if not isinstance(geo, str):
            geo = str(geo)
        # County-level rows are 5-digit FIPS starting with 26.
        if not geo.startswith("26") or len(geo) != 5:
            continue
        try:
            # The Tracking API uses "temporal" / "temporalId" for the year.
            year_text = (r.get("temporalId") or r.get("temporal")
                         or r.get("year") or "")
            year = int(str(year_text)[:4])
        except (TypeError, ValueError):
            continue
        # Suppression: the API sets suppressionFlag="1" and may zero out dataValue.
        supp_flag = str(r.get("suppressionFlag", "0")) == "1"
        rate_raw = r.get("dataValue") or r.get("displayValue")
        suppressed = supp_flag or _is_suppressed(rate_raw)
        try:
            rate = None if suppressed else float(rate_raw)
        except (TypeError, ValueError):
            rate = None
        cur.execute(
            f"""INSERT INTO {table}(county, county_fips, year, condition,
                  {rate_col}, suppressed, source)
                VALUES (?, ?, ?, ?, ?, ?, 'CDC_Tracking')""",
            (county_lookup.get(geo, ""), geo, year, condition, rate,
             1 if suppressed else 0),
        )
        inserted += 1
    conn.commit()
    return inserted


def _post_core_holder(measure_id: int, strat_level: int,
                      county_fips_csv: str) -> object:
    """POST to getCoreHolder. temporalTypeIdFilter=1 means single-year annual;
    we hand in the full CDC_YEARS list explicitly because the API requires it."""
    url = f"{CDC_API}/getCoreHolder/{measure_id}/{strat_level}/0/0"
    body = {
        "geographicTypeIdFilter": "2",
        "geographicItemsFilter": county_fips_csv,
        "temporalTypeIdFilter": "1",
        "temporalItemsFilter": ",".join(str(y) for y in CDC_YEARS),
        "isSmoothed": "0",
    }
    return cdc_request(url, method="POST", body=body)


def load_respiratory_data(conn: sqlite3.Connection) -> int:
    """Pull asthma + COPD ED and hospitalization age-adjusted rates from the
    CDC Tracking API. Falls back gracefully if the API is throttled.
    """
    log("Loading respiratory data (CDC EPHT Tracking API)...")
    cur = conn.cursor()
    cur.execute("DELETE FROM respiratory_ed_visits")
    cur.execute("DELETE FROM respiratory_hospitalizations")
    cur.execute("DELETE FROM respiratory_prevalence")
    cur.execute("DELETE FROM respiratory_mortality")
    conn.commit()

    county_lookup = {fips: name for fips, name in _county_fips_list(conn)}
    fips_csv = ",".join(county_lookup.keys())

    inserted_total = 0
    status_notes: list[str] = []
    all_ok = True

    for table, rate_col, mid, strat, condition, label in CDC_MEASURES:
        try:
            payload = _post_core_holder(mid, strat, fips_csv)
        except Exception as e:
            log(f"  CDC measure {mid} ({label}) fetch failed: {e}", level="warn")
            status_notes.append(f"{label} fetch failed ({e})")
            all_ok = False
            continue
        n = _ingest_core_holder(conn, payload, table, rate_col, condition, county_lookup)
        inserted_total += n
        log(f"  CDC measure {mid} {label}: +{n} rows", level="ok")
        # Be a polite caller — the API throttles aggressively.
        time.sleep(2)

    # Always seed prevalence baseline (the BRFS data isn't redistributed
    # per-county in a clean tabular form).
    _seed_prevalence_baseline(conn, county_lookup)

    # Broader ICD-10 J00-J99 categories: county-level data is not available
    # from CDC Tracking. Apply Michigan statewide baselines per county.
    _seed_broader_respiratory(conn, county_lookup)

    record_source(conn, "cdc_tracking",
                  "CDC National Environmental Public Health Tracking — Asthma & COPD",
                  f"{CDC_API}/contentareas/json",
                  "ok" if inserted_total else "unavailable",
                  inserted_total,
                  "; ".join(status_notes) or f"Years 2010-2023, county-level Michigan rows.")
    record_source(conn, "mitracking",
                  "Michigan MiTracking — MDHHS Environmental Health Tracking Portal",
                  "https://mitracking.state.mi.us/",
                  "skipped", 0,
                  "Mirrors the same CDC dataset; portal-only access.")
    record_source(conn, "mdhhs_asthma_atlas",
                  "MDHHS — Michigan Asthma Atlas 2019 (BRFS 2012-2016)",
                  "https://www.michigan.gov/-/media/Project/Websites/mdhhs/Keeping-Michigan-Healthy/"
                  "Chronic-Disease-Epidemiology/Asthma-Epi/Reports-Presentations/MI_Asthma_Atlas_2019.pdf",
                  "ok", 83,
                  "Statewide adult-asthma prevalence baseline applied to every "
                  "county; replace with per-county BRFS data when available.")
    record_source(conn, "mha_hospital",
                  "Michigan Health and Hospital Association (MHA) discharge data",
                  "https://www.mdch.state.mi.us/osr/index.asp?Id=14",
                  "skipped", 0,
                  "Public portal only; no bulk feed.")
    record_source(conn, "cdc_wonder",
                  "CDC WONDER — underlying-cause mortality (J00–J99)",
                  "https://wonder.cdc.gov/",
                  "skipped", 0,
                  "Compressed Mortality file requires query-builder access.")
    record_source(conn, "mdhhs_resp_dashboard",
                  "MDHHS Respiratory Disease Dashboard (COVID / flu / RSV)",
                  "https://www.michigan.gov/mdhhs/keep-mi-healthy/infectious-diseases/"
                  "seasonal-respiratory-viruses/respiratory-disease-reports",
                  "skipped", 0,
                  "Statewide/regional only; not county-level.")
    record_source(conn, "mi_brfs",
                  "Michigan Behavioral Risk Factor Survey (MiBRFS)",
                  "https://www.michigan.gov/mdhhs/keeping-mi-healthy/chronic-diseases/"
                  "chronicdiseaseepidemiology/brfs",
                  "skipped", 0,
                  "Aggregated into the Asthma Atlas baseline above.")
    conn.commit()
    return inserted_total


def _seed_broader_respiratory(conn, county_lookup: dict[str, str]) -> None:
    """Seed per-county statewide-baseline rows for ICD-10 categories the
    CDC Tracking API doesn't expose at county level. Each county gets the
    same Michigan-statewide rate so the choropleth renders honestly as
    "no county variation available."
    """
    b = MI_BROADER_RESP_BASELINE
    cur = conn.cursor()
    # ED-visit-style metrics → respiratory_ed_visits with new condition codes
    ed_seeds = [
        ("upper_respiratory",   b["upper_respiratory_ed_rate"]),
        ("acute_bronchitis",    b["acute_bronchitis_ed_rate"]),
        ("pneumonia_influenza", b["pneumonia_influenza_ed_rate"]),
    ]
    for fips, name in county_lookup.items():
        for cond, rate in ed_seeds:
            cur.execute(
                """INSERT INTO respiratory_ed_visits(county, county_fips, year,
                       condition, visit_rate, suppressed, source)
                   VALUES (?, ?, ?, ?, ?, 0, 'MDHHS_state_baseline')""",
                (name, fips, 2022, cond, rate),
            )
    # Mortality-style metrics → respiratory_mortality
    mort_seeds = [
        ("pneumonia_influenza",   b["pneumonia_influenza_mortality"]),
        ("chemical_respiratory",  b["chemical_respiratory_mortality"]),
        ("all_respiratory",       b["all_respiratory_mortality"]),
    ]
    for fips, name in county_lookup.items():
        for cause, rate in mort_seeds:
            cur.execute(
                """INSERT INTO respiratory_mortality(county, county_fips, year,
                       cause, death_count, death_rate, source)
                   VALUES (?, ?, ?, ?, NULL, ?, 'MDHHS_state_baseline')""",
                (name, fips, 2022, cause, rate),
            )
    conn.commit()


def _seed_prevalence_baseline(conn, county_lookup: dict[str, str]) -> None:
    """Apply the statewide MDHHS BRFS asthma prevalence to every county.

    Per-county BRFS values are not publicly redistributable as a clean table;
    we record the state baseline with the data_years tag so the UI can show
    'baseline (state average)' rather than fabricated county values.
    """
    cur = conn.cursor()
    for fips, name in county_lookup.items():
        cur.execute(
            """INSERT INTO respiratory_prevalence(county, county_fips, condition,
                 prevalence_pct, data_years, age_group, source)
               VALUES (?, ?, 'asthma', ?, '2012-2016', 'adult', 'MDHHS_state_baseline')""",
            (name, fips, MI_STATEWIDE_BASELINE["adult_asthma_prevalence_pct"]),
        )
    conn.commit()


# ---------- 8. Water quality (Water Quality Portal + watersheds + NAWQA) ----------

# When true, load_water_quality ignores any existing data and re-pulls the full
# WQP result set (used to backfill samples uploaded late for old dates, which a
# date-bounded incremental pull would miss). refresh_data.py --full sets this.
WQP_FULL_REBUILD = os.environ.get("WQP_FULL_REBUILD", "") == "1"

# Real WQP sample dates are ISO YYYY-MM-DD; the hardcoded NAWQA rows use the
# literal '2002-2005' range, so this GLOB isolates genuine WQP-sourced dates
# (used to compute the incremental watermark).
_WQP_ISO_GLOB = "[12][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"


def _wqp_date(iso: str) -> str:
    """Convert an ISO 'YYYY-MM-DD' date to WQP's 'MM-DD-YYYY' query format."""
    y, m, d = iso.split("-")
    return f"{m}-{d}-{y}"


def load_water_quality(conn: sqlite3.Connection, *,
                       incremental: bool | None = None) -> tuple[int, int]:
    """Download MI pesticide sample data from the USGS/EPA Water Quality Portal,
    ingest stations + results, plus hardcoded NAWQA stream sites. Returns
    (total_sites, total_results).

    If the database already holds WQP results this runs **incrementally**: it
    downloads only samples on/after the latest sample date already stored
    (WQP ``startDateLo``) and appends them, instead of re-pulling the full
    ~230 MB result set. This keeps each refresh to a few MB and avoids the
    portal's rate-limiting of big bursts. Pass ``incremental=False`` (or set the
    WQP_FULL_REBUILD flag) to force a full rebuild.

    Caveat: date-bounded pulls key off the *sample* date, so a sample collected
    before the watermark but uploaded to WQP later can be missed. Run a periodic
    full rebuild (``refresh_data.py --source water_quality --full``) to backfill.
    """
    cur = conn.cursor()
    existing = cur.execute(
        f"SELECT COUNT(*), MAX(sample_date) FROM water_quality_results "
        f"WHERE sample_date GLOB '{_WQP_ISO_GLOB}'"
    ).fetchone()
    have_wqp = (existing[0] or 0) > 0
    if incremental is None:
        incremental = have_wqp and not WQP_FULL_REBUILD
    watermark = existing[1] if incremental else None

    mode = f"incremental since {watermark}" if incremental else "full rebuild"
    log(f"Loading water quality ({mode}; WQP + NAWQA streams)...")

    if not incremental:
        cur.execute("DELETE FROM water_quality_sites")
        cur.execute("DELETE FROM water_quality_results")
        conn.commit()

    new_results = 0
    wqp_fetch_ok = False

    # --- WQP stations (small; pulled fresh on incremental, idempotent upsert) ---
    stations_path = DATA_DIR / "wqp_stations.csv"
    try:
        if incremental or _need_download(stations_path, 1000, force=FORCE_REFRESH):
            size = download_stream(WQP_STATION_URL, stations_path,
                                   timeout=300, attempts=5, backoff=15, min_bytes=1000)
            log(f"  WQP stations: fetched {size/1024:.0f} KB", level="ok")
        else:
            log(f"  WQP stations: cached ({stations_path.stat().st_size/1024:.0f} KB)")
        n = _ingest_wqp_stations(conn, stations_path)
        log(f"  upserted {n:,} WQP stations", level="ok")
    except Exception as e:
        log(f"  WQP station download failed (keeping existing): {e}", level="warn")

    # --- WQP results ---
    if incremental and watermark:
        # Fetch only samples on/after the watermark day. Re-fetch that whole day
        # (delete its existing rows first) so a day that was only partially
        # loaded last time can't leave duplicates or gaps.
        delta_path = DATA_DIR / "wqp_results_delta.csv"
        url = WQP_RESULT_URL + f"&startDateLo={_wqp_date(watermark)}"
        try:
            size = download_stream(url, delta_path, timeout=600,
                                   attempts=6, backoff=30, min_bytes=1)
            log(f"  WQP delta (samples >= {watermark}): fetched {size/1024:.0f} KB", level="ok")
            wqp_fetch_ok = True
            cur.execute("DELETE FROM water_quality_results WHERE sample_date = ?",
                        (watermark,))
            conn.commit()
            new_results = _ingest_wqp_results(conn, delta_path)
            log(f"  appended {new_results:,} WQP result rows since {watermark}", level="ok")
            try:
                delta_path.unlink()
            except OSError:
                pass
        except Exception as e:
            log(f"  WQP delta download failed (keeping existing): {e}", level="warn")
    else:
        results_path = DATA_DIR / "wqp_results.csv"
        try:
            if _need_download(results_path, 1000, force=FORCE_REFRESH):
                # The portal generates this ~230 MB CSV on the fly and rate-limits
                # bursts, so be patient: a longer backoff lets a throttle window
                # clear between attempts (backoff*attempt => 30/60/.../180 s).
                size = download_stream(WQP_RESULT_URL, results_path,
                                       timeout=600, attempts=6, backoff=30,
                                       min_bytes=100_000)
                log(f"  WQP results: fetched {size/1_000_000:.1f} MB", level="ok")
            else:
                log(f"  WQP results: cached ({results_path.stat().st_size/1_000_000:.1f} MB)")
            new_results = _ingest_wqp_results(conn, results_path)
            log(f"  inserted {new_results:,} WQP result rows", level="ok")
            wqp_fetch_ok = True
        except Exception as e:
            log(f"  WQP result download failed (keeping existing): {e}", level="warn")

    # --- NAWQA hardcoded MI stream sites (USGS SIR 2007-5077) ---
    # Only on a full rebuild: on incremental they're already present, and their
    # result rows have no unique key so re-inserting would duplicate them.
    if not incremental:
        for s in NAWQA_MI_STREAMS:
            cur.execute(
                """INSERT OR REPLACE INTO water_quality_sites(
                      site_id, site_name, site_type, latitude, longitude,
                      huc8, organization, source)
                   VALUES (?, ?, 'Stream', ?, ?, ?, 'USGS-NAWQA', 'NAWQA_SIR_2007-5077')""",
                (s["site_id"], s["name"], s["lat"], s["lon"], s["huc8"]),
            )
            for compound in s["pesticides_detected"]:
                threshold, _ = threshold_for(compound)
                cur.execute(
                    """INSERT INTO water_quality_results(
                          site_id, sample_date, compound, result_value, unit,
                          detected, exceeds_mcl, mcl_value, medium)
                       VALUES (?, '2002-2005', ?, NULL, 'unspecified',
                               1, 0, ?, 'Water')""",
                    (s["site_id"], compound, threshold),
                )
        conn.commit()

    # --- watersheds (idempotent; cached geojson) ---
    huc8_count = load_watersheds(conn)
    log(f"  watersheds: {huc8_count} HUC-8 polygons", level="ok")

    total_sites = cur.execute("SELECT COUNT(*) FROM water_quality_sites").fetchone()[0]
    total_results = cur.execute("SELECT COUNT(*) FROM water_quality_results").fetchone()[0]
    detail = (f"incremental (+{new_results:,} new)" if incremental
              else "full load")
    record_source(
        conn, "wqp",
        "USGS / EPA Water Quality Portal — Michigan pesticide samples",
        "https://www.waterqualitydata.us/",
        "ok" if wqp_fetch_ok else "unavailable",
        total_results,
        f"{total_sites} stations, {total_results:,} sample-results — {detail}. "
        f"MCL-based exceedance flagging applied to known compounds.",
    )
    record_source(
        conn, "nawqa_streams",
        "USGS SIR 2007-5077 — 11 Michigan stream pesticide screening sites",
        "https://pubs.usgs.gov/sir/2007/5077/pdf/sir2007-5077_web.pdf",
        "ok", len(NAWQA_MI_STREAMS),
        "Hardcoded station coordinates + reported detections for the "
        "2002-2005 sampling window.",
    )
    record_source(
        conn, "wbd_huc8",
        "USGS Watershed Boundary Dataset — HUC-8 subbasins (Michigan)",
        "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4",
        "ok" if huc8_count else "unavailable",
        huc8_count,
        "ArcGIS REST query, paged in chunks of 10 features.",
    )
    record_source(
        conn, "egle_wellogic",
        "Michigan EGLE Wellogic — water well viewer",
        "https://www.michigan.gov/egle/maps-data/wellogic/water-wells",
        "skipped", 0,
        "Per-well water-quality results aren't bulk-downloadable; linked for reference.",
    )
    record_source(
        conn, "epa_sdwis",
        "EPA Safe Drinking Water Information System (SDWIS)",
        "https://data.epa.gov/efservice/",
        "skipped", 0,
        "MCL-violation data accessible through SDWIS; integration not bundled.",
    )
    conn.commit()
    return total_sites, total_results


def _ingest_wqp_stations(conn: sqlite3.Connection, path: Path) -> int:
    """Parse the WQP Station CSV and populate water_quality_sites."""
    inserted = 0
    cur = conn.cursor()
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            site_id = row.get("MonitoringLocationIdentifier") or ""
            if not site_id:
                continue
            try:
                lat = float(row.get("LatitudeMeasure") or "")
                lon = float(row.get("LongitudeMeasure") or "")
            except ValueError:
                continue
            state_code = row.get("StateCode") or ""
            cty_code = (row.get("CountyCode") or "").zfill(3)
            fips = f"26{cty_code}" if state_code in ("MI", "26") and cty_code else None
            cur.execute(
                """INSERT OR REPLACE INTO water_quality_sites(
                      site_id, site_name, site_type, latitude, longitude,
                      county, county_fips, water_body, huc8, organization, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WQP')""",
                (
                    site_id,
                    row.get("MonitoringLocationName") or "",
                    row.get("MonitoringLocationTypeName") or "",
                    lat, lon,
                    row.get("CountyName") or "",
                    fips,
                    row.get("MonitoringLocationDescriptionText") or "",
                    row.get("HUCEightDigitCode") or "",
                    row.get("OrganizationFormalName") or "",
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def _ingest_wqp_results(conn: sqlite3.Connection, path: Path) -> int:
    """Parse the WQP Result CSV. Filters to Water/Groundwater media,
    canonicalizes compound names, flags detections + MCL exceedances."""
    inserted = 0
    cur = conn.cursor()
    batch: list[tuple] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            site_id = row.get("MonitoringLocationIdentifier") or ""
            if not site_id:
                continue
            medium_raw = (row.get("ActivityMediaName") or "").strip().lower()
            if medium_raw not in ("water", "groundwater"):
                continue
            medium = "Groundwater" if "ground" in medium_raw else "Water"
            characteristic = row.get("CharacteristicName") or ""
            compound = canonicalize_compound(characteristic)
            if not compound:
                continue
            sample_date = row.get("ActivityStartDate") or ""
            unit = row.get("ResultMeasure/MeasureUnitCode") or ""
            value_raw = row.get("ResultMeasureValue") or ""
            try:
                result_value = float(value_raw) if value_raw not in ("", "ND") else None
            except ValueError:
                result_value = None
            try:
                dl_raw = row.get("DetectionQuantitationLimitMeasure/MeasureValue") or ""
                detection_limit = float(dl_raw) if dl_raw else None
            except ValueError:
                detection_limit = None
            # Detection logic: result above 0 (and not flagged ND) counts as detected.
            detect_flag = (row.get("ResultDetectionConditionText") or "").lower()
            detected = 0
            if result_value is not None and result_value > 0 and "non-detect" not in detect_flag:
                detected = 1
            # MCL exceedance — converting unit to µg/L when needed.
            mcl, _ = threshold_for(compound)
            exceeds = 0
            ugl = None
            if detected and result_value is not None and mcl is not None:
                ugl = _to_ugl(result_value, unit)
                if ugl is not None and ugl > mcl:
                    exceeds = 1
            batch.append((
                site_id, sample_date, compound,
                result_value, unit, detection_limit,
                detected, exceeds, mcl, medium,
            ))
            if len(batch) >= 5000:
                cur.executemany(
                    """INSERT INTO water_quality_results(
                          site_id, sample_date, compound, result_value, unit,
                          detection_limit, detected, exceeds_mcl, mcl_value, medium)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    batch,
                )
                inserted += len(batch)
                batch.clear()
    if batch:
        cur.executemany(
            """INSERT INTO water_quality_results(
                  site_id, sample_date, compound, result_value, unit,
                  detection_limit, detected, exceeds_mcl, mcl_value, medium)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            batch,
        )
        inserted += len(batch)
    conn.commit()
    return inserted


# Unit→µg/L normalisation lives with the MCL reference data (water_quality).
_to_ugl = to_ugl


def load_watersheds(conn: sqlite3.Connection) -> int:
    """Populate watersheds + write MI_HUC8_GEOJSON_PATH.

    Prefer the cached GeoJSON if it exists; otherwise page the ArcGIS WBD
    REST service in chunks of 10. The endpoint flakes on offsets > 20 in
    practice, so we accept partial coverage rather than refusing to load.
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM watersheds")

    features: list[dict] = []
    if MI_HUC8_GEOJSON_PATH.exists() and MI_HUC8_GEOJSON_PATH.stat().st_size > 50_000:
        try:
            fc = json.loads(MI_HUC8_GEOJSON_PATH.read_text())
            features = fc.get("features", []) or []
            log(f"  watersheds: using cached {MI_HUC8_GEOJSON_PATH.name} "
                f"({len(features)} features)")
        except Exception as e:
            log(f"  cached watershed geojson unreadable: {e}", level="warn")
            features = []

    if not features:
        log("  fetching HUC-8 polygons (paged)...")
        offset = 0
        consec_fail = 0
        while offset < 80 and consec_fail < 3:
            url = (
                "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4/query"
                "?where=states%20LIKE%20%27%25MI%25%27"
                "&outFields=huc8,name,states,areasqkm"
                "&returnGeometry=true&outSR=4326&geometryPrecision=4"
                f"&resultOffset={offset}&resultRecordCount=10&f=geojson"
            )
            try:
                raw = http_get(url, timeout=180)
                payload = json.loads(raw)
            except Exception as e:
                log(f"  watershed page offset={offset} failed: {e}", level="warn")
                consec_fail += 1
                time.sleep(15)
                continue
            feats = payload.get("features") or []
            if not feats:
                break
            features.extend(feats)
            log(f"  watershed page offset={offset}: +{len(feats)} (running total {len(features)})", level="ok")
            offset += 10
            consec_fail = 0
            if len(feats) < 10:
                break

        if features:
            fc = {"type": "FeatureCollection", "features": features}
            MI_HUC8_GEOJSON_PATH.write_text(json.dumps(fc))

    if not features:
        return 0
    for f in features:
        props = f.get("properties", {}) or {}
        cur.execute(
            """INSERT OR REPLACE INTO watersheds(huc8, name, states, area_sqkm)
               VALUES (?, ?, ?, ?)""",
            (props.get("huc8"), props.get("name"),
             props.get("states"), props.get("areasqkm")),
        )
    conn.commit()
    return len(features)


# ---------- 9. Cancer incidence / mortality (NCI State Cancer Profiles) ----------

_SEX_PARAM = {"both": "0", "male": "1", "female": "2"}
_STAGE_PARAM = {"all": "999", "late": "211"}


def _find_cancer_csv(key: str, data_type: str, stage: str, code: str) -> Path | None:
    """Look for a real per-county CSV the user exported from State Cancer
    Profiles. Accepts several sensible filenames dropped in data/cancer/."""
    dt = "incd" if data_type == "incidence" else "mort"
    candidates = [
        f"{key}_{data_type}_{stage}.csv",
        f"{key}_{data_type}.csv" if stage == "all" else None,
        f"{dt}_{code}_{stage}.csv",
        f"{dt}_{code}.csv" if stage == "all" else None,
    ]
    for name in candidates:
        if not name:
            continue
        p = CANCER_DATA_DIR / name
        if p.exists() and p.stat().st_size > 200:
            return p
    return None


def _f(v) -> float | None:
    try:
        s = str(v).strip().replace(",", "")
        if s in ("", "*", "N/A", "NA", "—", "-", "**", "data not available",
                 "Data not available", "#"):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _clean_county_name(name: str) -> str:
    """Strip NCI footnote markers and the 'County' suffix so names match the
    geojson/counties table (e.g. 'Presque Isle County(2)' -> 'Presque Isle')."""
    import re
    n = re.sub(r"\(\d+\)\s*$", "", name.strip())        # trailing "(2)"
    n = re.sub(r"\s+County\s*$", "", n, flags=re.I)       # " County"
    return n.strip()


def _parse_nci_csv(path: Path) -> dict:
    """Parse a State Cancer Profiles county CSV.

    The files wrap every field in quotes, lead with comment lines, and include
    "United States" and state ("Michigan") summary rows mixed in with counties.
    We locate columns by header keywords so the parser tolerates the small
    layout differences between cancer types / incidence vs mortality.

    Returns {"counties": [row, ...], "state_avg": float|None, "us_avg": float|None}.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r]

    # Find the header row: the one that mentions FIPS and a Rate.
    header_idx = -1
    for i, r in enumerate(rows):
        joined = " ".join(r).lower()
        if "fips" in joined and "rate" in joined:
            header_idx = i
            break
    if header_idx < 0:
        raise ValueError("no header row with FIPS+Rate found")

    header = [h.strip().lower() for h in rows[header_idx]]

    def col(*keywords, default=None):
        for idx, h in enumerate(header):
            if all(k in h for k in keywords):
                return idx
        return default

    i_fips = col("fips")
    i_county = col("county") if col("county") is not None else 0
    i_rate = col("age-adjusted", "rate")
    if i_rate is None:
        i_rate = col("rate")
    i_lower = col("lower")
    i_upper = col("upper")
    i_rank = col("rank")
    i_count = col("count")
    i_trend = col("recent", "trend")
    if i_trend is None:
        i_trend = col("trend")
    i_aapc = col("annual percent")
    if i_aapc is None:
        i_aapc = col("aapc")

    def cell(row, idx):
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    out = {"counties": [], "state_avg": None, "us_avg": None, "state_trend": None}
    for r in rows[header_idx + 1:]:
        fips = cell(r, i_fips).strip()
        name = _clean_county_name(cell(r, i_county))
        rate = _f(cell(r, i_rate))
        trend = (cell(r, i_trend) or "").strip().lower() or None
        # Summary rows are identified by their FIPS only — matching on name
        # wrongly catches footnote lines like "Data for United States ...".
        # US (SEER+NPCR) national summary row — FIPS 00000.
        if fips in ("00000", "0", "00"):
            out["us_avg"] = rate
            continue
        # Michigan statewide summary row — FIPS 26000.
        if fips in ("26", "26000"):
            out["state_avg"] = rate
            out["state_trend"] = trend
            continue
        # County rows: 5-digit FIPS starting with 26, excluding the 26000 total.
        digits = "".join(ch for ch in fips if ch.isdigit())
        if len(digits) == 4:
            digits = "26" + digits[-3:]
        if not (len(digits) == 5 and digits.startswith("26") and digits != "26000"):
            continue
        raw_rate_cell = cell(r, i_rate)
        suppressed = raw_rate_cell.strip() in ("*", "**", "") or rate is None
        out["counties"].append({
            "fips": digits,
            "county": name,
            "rate": rate,
            "lower": _f(cell(r, i_lower)),
            "upper": _f(cell(r, i_upper)),
            "count": _f(cell(r, i_count)),
            "rank": int(_f(cell(r, i_rank))) if _f(cell(r, i_rank)) is not None else None,
            "trend": trend.strip().lower() if trend else None,
            "aapc": _f(cell(r, i_aapc)),
            "suppressed": 1 if suppressed else 0,
        })
    return out


def _try_download_nci(key: str, code: str, sex: str, data_type: str,
                      stage: str) -> Path | None:
    """Best-effort live fetch. The rebuilt SCP site returns the empty HTML form
    shell to non-browser clients, so this almost always returns None — we detect
    the shell and skip. Kept so the loader honestly tries the live source first.
    """
    if data_type == "incidence":
        url = NCI_INCIDENCE_URL.format(code=code, sex=sex, stage=_STAGE_PARAM[stage])
    else:
        url = NCI_MORTALITY_URL.format(code=code, sex=sex)
    try:
        raw = http_get(url, timeout=30)
    except Exception:
        return None
    text = raw.decode("utf-8", errors="replace")
    # Reject the HTML form shell / anything without county FIPS rows.
    if "<html" in text.lower() or "26001" not in text and "fips" not in text.lower():
        return None
    CANCER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    dt = "incd" if data_type == "incidence" else "mort"
    path = CANCER_DATA_DIR / f"{dt}_{code}_{stage}.live.csv"
    path.write_bytes(raw)
    return path


def _insert_cancer_rows(cur, key, label, data_type, stage, parsed, county_lookup) -> int:
    # Record the real Michigan + US averages from this file (all-stage only —
    # that's the population the county cards compare against).
    if stage == "all" and (parsed.get("state_avg") is not None
                           or parsed.get("us_avg") is not None):
        cur.execute(
            """INSERT INTO cancer_reference(cancer_type, data_type, stage,
                 mi_rate, us_rate, mi_trend)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(cancer_type, data_type, stage) DO UPDATE SET
                 mi_rate=excluded.mi_rate, us_rate=excluded.us_rate,
                 mi_trend=excluded.mi_trend""",
            (key, data_type, stage, parsed.get("state_avg"),
             parsed.get("us_avg"), parsed.get("state_trend")),
        )
    n = 0
    for row in parsed["counties"]:
        fips = row["fips"]
        name = row["county"] or county_lookup.get(fips, "")
        rural = "Urban" if name in URBAN_COUNTIES else "Rural"
        cur.execute(
            """INSERT INTO cancer_incidence(
                 county, county_fips, cancer_type, cancer_label, stage,
                 rate, rate_lower_ci, rate_upper_ci, avg_annual_count, ci_rank,
                 recent_trend, trend_aapc, rural_urban, data_years, data_type,
                 source, suppressed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, fips, key, label, stage,
             row["rate"], row["lower"], row["upper"], row["count"], row["rank"],
             row["trend"], row["aapc"], rural, cancer_data.DATA_YEARS, data_type,
             "NCI_State_Cancer_Profiles", row["suppressed"]),
        )
        n += 1
    return n


def _seed_cancer_baseline(cur, key, label, data_type, county_lookup) -> int:
    """Seed every county with the Michigan statewide reference rate, flagged so
    the UI shows uniform shading as a baseline — never a fake county signal."""
    rate = cancer_data.statewide_rate(key, data_type)
    if rate is None:
        return 0
    n = 0
    for fips, name in county_lookup.items():
        rural = "Urban" if name in URBAN_COUNTIES else "Rural"
        cur.execute(
            """INSERT INTO cancer_incidence(
                 county, county_fips, cancer_type, cancer_label, stage,
                 rate, rural_urban, data_years, data_type, source, suppressed)
               VALUES (?,?,?,?,'all',?,?,?,?, 'NCI_state_baseline', 0)""",
            (name, fips, key, label, rate, rural, cancer_data.DATA_YEARS, data_type),
        )
        n += 1
    return n


def _load_cancer_evidence(cur) -> int:
    for e in cancer_data.CANCER_EVIDENCE:
        cur.execute(
            """INSERT INTO cancer_evidence(compound, cancer_type, evidence_level,
                 iarc_classification, key_mechanism, key_studies, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (e["compound"], e["cancer_type"], e["evidence_level"], e["iarc"],
             e["mechanism"], e["studies"], e["notes"]),
        )
    return len(cancer_data.CANCER_EVIDENCE)


def load_cancer_data(conn: sqlite3.Connection) -> tuple[int, int]:
    """Populate cancer_incidence + cancer_evidence.

    Priority per cancer/data_type/stage: (1) a real CSV in data/cancer/,
    (2) a best-effort live NCI fetch, (3) the Michigan statewide baseline.
    Returns (real_county_rows, baseline_rows).
    """
    log("Loading cancer incidence/mortality (NCI State Cancer Profiles)...")
    cur = conn.cursor()
    cur.execute("DELETE FROM cancer_incidence")
    cur.execute("DELETE FROM cancer_evidence")
    cur.execute("DELETE FROM cancer_reference")
    conn.commit()

    county_lookup = {fips: name for fips, name in _county_fips_list(conn)}
    CANCER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    real_rows = 0
    baseline_rows = 0
    live_ok = 0
    combos_real: set[tuple[str, str]] = set()

    for c in cancer_data.CANCER_TYPES:
        key, code, label = c["key"], c["nci_code"], c["label"]
        sex = _SEX_PARAM[c["sex"]]
        for data_type in ("incidence", "mortality"):
            stages = ["all"]
            if data_type == "incidence" and c.get("has_late_stage"):
                stages.append("late")
            for stage in stages:
                parsed = None
                local = _find_cancer_csv(key, data_type, stage, code)
                if local:
                    try:
                        parsed = _parse_nci_csv(local)
                        log(f"  {key}/{data_type}/{stage}: parsed {local.name}", level="ok")
                    except Exception as e:
                        log(f"  parse failed {local.name}: {e}", level="warn")
                        parsed = None
                if parsed is None:
                    fetched = _try_download_nci(key, code, sex, data_type, stage)
                    if fetched:
                        try:
                            parsed = _parse_nci_csv(fetched)
                            live_ok += 1
                        except Exception:
                            parsed = None
                if parsed and parsed["counties"]:
                    n = _insert_cancer_rows(cur, key, label, data_type, stage,
                                            parsed, county_lookup)
                    real_rows += n
                    if stage == "all":
                        combos_real.add((key, data_type))
                elif stage == "all":
                    baseline_rows += _seed_cancer_baseline(
                        cur, key, label, data_type, county_lookup)
    conn.commit()

    ev = _load_cancer_evidence(cur)
    conn.commit()

    have_real = len(combos_real) > 0
    note = (
        f"Real county CSVs loaded for {len(combos_real)} cancer/measure combos."
        if have_real else
        "No county-level CSVs found; every county seeded with the Michigan "
        "statewide 2018-2022 reference rate (source=NCI_state_baseline). The "
        "SCP export URL is JS/session-gated and returns no CSV to a plain HTTP "
        "client — drop per-county exports in data/cancer/ to populate real rates."
    )
    record_source(
        conn, "nci_scp",
        "NCI / CDC State Cancer Profiles — county cancer incidence & mortality",
        NCI_SCP_BASE,
        "ok" if have_real else "baseline",
        real_rows if have_real else baseline_rows,
        note,
    )
    record_source(
        conn, "mcsp",
        "Michigan Cancer Surveillance Program (MCSP) — MDHHS Vital Records & Health Statistics",
        "https://www.michigan.gov/mdhhs/inside-mdhhs/statisticsreports/mcsp",
        "skipped", 0,
        "State cancer registry feeding NPCR/State Cancer Profiles; county tables "
        "are portal/PDF only, not a bulk feed.",
    )
    record_source(
        conn, "cdc_npcr",
        "CDC National Program of Cancer Registries (NPCR)",
        "https://www.cdc.gov/cancer/npcr/", "skipped", 0,
        "Source registry program behind U.S. Cancer Statistics / State Cancer Profiles.",
    )
    record_source(
        conn, "nci_seer",
        "NCI SEER — Surveillance, Epidemiology, and End Results Program",
        "https://seer.cancer.gov/", "skipped", 0,
        "National incidence/survival source; county extracts require SEER*Stat access.",
    )
    record_source(
        conn, "cdc_wonder_cancer",
        "CDC WONDER — Underlying Cause of Death (cancer ICD-10 C-codes)",
        "https://wonder.cdc.gov/", "skipped", 0,
        "Longer mortality trend series; query-builder / data-use-agreement gated.",
    )
    record_source(
        conn, "ahs",
        "Agricultural Health Study (NCI / NIEHS / EPA) — pesticide-cancer evidence base",
        "https://aghealth.nih.gov/", "ok", ev,
        "Cohort study underpinning the compound-cancer evidence table.",
    )
    record_source(
        conn, "iarc_monographs",
        "IARC Monographs on the Evaluation of Carcinogenic Risks to Humans",
        "https://monographs.iarc.who.int/", "ok", ev,
        "Carcinogenicity classifications (e.g. glyphosate 2A) shown in the evidence modal.",
    )
    conn.commit()
    log(f"  cancer: {real_rows} real county rows, {baseline_rows} baseline rows, "
        f"{ev} evidence rows (live_ok={live_ok})", level="ok")
    return real_rows, baseline_rows


def _matrix_compound_totals(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    """Per-county summed kg (latest year) for each compound in the matrix."""
    cur = conn.cursor()
    latest = cur.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]
    out: dict[str, dict[str, float]] = {}
    if latest is None:
        return out
    for comp in cancer_data.MATRIX_COMPOUNDS:
        for r in cur.execute(
            """SELECT county_fips AS f,
                      SUM((epest_low_kg + epest_high_kg)/2.0) AS k
                 FROM pesticide_use
                WHERE year = ? AND UPPER(compound) LIKE ?
                GROUP BY county_fips""",
            (latest, comp + "%"),
        ):
            out.setdefault(r["f"], {})[comp] = r["k"]
    return out


def _quartile_means(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Mean y for the top-25% and bottom-25% of counties ranked by x."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 4:
        return None, None
    pairs.sort(key=lambda p: p[0])
    q = max(1, len(pairs) // 4)
    bottom = [p[1] for p in pairs[:q]]
    top = [p[1] for p in pairs[-q:]]
    return (sum(top) / len(top)) if top else None, \
           (sum(bottom) / len(bottom)) if bottom else None


def build_cancer_correlations(conn: sqlite3.Connection) -> int:
    """Pre-compute pesticide<->cancer correlations for each cancer type, across
    category aggregates (all/herb/insect/fung) x cohorts (all/exclude_urban/
    rural_only), plus the per-compound matrix cells. When only the statewide
    baseline is loaded there is no county variation, so rows are stored with
    NULL stats and an explanatory note rather than a fake r=0."""
    cur = conn.cursor()
    cur.execute("DELETE FROM cancer_pesticide_correlation")

    pest = {r["county_fips"]: r for r in cur.execute("SELECT * FROM correlation_analysis")}
    comp_tot = _matrix_compound_totals(conn)
    name_by_fips = {fips: name for fips, name in _county_fips_list(conn)}

    cat_fields = [
        ("all", "total_pesticide_kg"),
        ("herbicide", "herbicide_kg"),
        ("insecticide", "insecticide_kg"),
        ("fungicide", "fungicide_kg"),
    ]

    def store(ck, dt, compound, category, xs, ys, cohort, baseline):
        pr = stats.pearson(xs, ys)
        sp = stats.spearman(xs, ys)
        qt, qb = _quartile_means(xs, ys)
        note = ("statewide baseline loaded — county-level cancer variation not "
                "available; correlation pending real NCI county export"
                if baseline else None)
        cur.execute(
            """INSERT INTO cancer_pesticide_correlation(
                 cancer_type, data_type, pesticide_compound, pesticide_category,
                 pearson_r, pearson_p, spearman_r, spearman_p, slope, intercept,
                 n_counties, mean_rate_top_quartile, mean_rate_bottom_quartile,
                 cohort, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ck, dt, compound, category,
             None if baseline else pr["r"], None if baseline else pr["p_value"],
             None if baseline else sp["rho"], None if baseline else sp["p_value"],
             None if baseline else pr["slope"], None if baseline else pr["intercept"],
             pr["n"], qt, qb, cohort, note),
        )

    inserted = 0
    for c in cancer_data.CANCER_TYPES:
        ck = c["key"]
        dt = "incidence"
        crates: dict[str, float] = {}
        baseline = True
        for r in cur.execute(
            """SELECT county_fips, rate, source FROM cancer_incidence
                WHERE cancer_type=? AND data_type=? AND stage='all'""",
            (ck, dt),
        ):
            if r["rate"] is not None:
                crates[r["county_fips"]] = r["rate"]
            if r["source"] != "NCI_state_baseline":
                baseline = False

        for category, field in cat_fields:
            for cohort in ("all", "exclude_urban", "rural_only"):
                xs, ys = [], []
                for fips, crate in crates.items():
                    name = name_by_fips.get(fips, "")
                    if cohort in ("exclude_urban", "rural_only") and name in URBAN_COUNTIES:
                        continue
                    p = pest.get(fips)
                    if not p or p[field] is None:
                        continue
                    xs.append(p[field])
                    ys.append(crate)
                store(ck, dt, None, category, xs, ys, cohort, baseline)
                inserted += 1

        for compound in cancer_data.MATRIX_COMPOUNDS:
            xs, ys = [], []
            for fips, crate in crates.items():
                kg = comp_tot.get(fips, {}).get(compound)
                if kg is None:
                    continue
                xs.append(kg)
                ys.append(crate)
            store(ck, dt, compound, None, xs, ys, "all", baseline)
            inserted += 1

    conn.commit()
    return inserted


# ---------- 10. Industrial contamination (EPA NPL + compiled sites) ----------

def _contam_slug(name: str) -> str:
    """Canonical site name for dedup: lowercase alnum with the trailing
    'superfund site' dropped, so compiled names ('X Superfund Site') match the
    EPA feed's bare names ('X'). Also strips a trailing 'site'."""
    s = "".join(ch for ch in (name or "").lower() if ch.isalnum())
    for suf in ("superfundsite", "site"):
        if s.endswith(suf) and len(s) > len(suf) + 3:
            s = s[: -len(suf)]
            break
    return s


def _epa_structured_description(rec) -> str:
    """Build a factual one-paragraph description for an EPA NPL site purely from
    the fields the ArcGIS feed returns (the feed's "narrative" is only a link to
    a PDF, not prose). No contaminants/health-effects are invented — those are
    left to the linked EPA profile. See instruction #4: do not fabricate."""
    name = rec.get("site_name") or "This site"
    city = rec.get("city")
    county = rec.get("county")
    status = (rec.get("status") or "").lower()
    loc = ", ".join(p for p in (city, f"{county} County" if county else None) if p)

    if "delet" in status:
        listing = ("was placed on and has since been deleted from the National "
                   "Priorities List, indicating EPA considers cleanup goals met")
    elif "propos" in status:
        listing = "has been proposed for the National Priorities List"
    else:
        listing = "is on the National Priorities List of federal Superfund sites"

    s = f"{name} is a federal Superfund site"
    if loc:
        s += f" in {loc}, Michigan"
    s += f". It {listing}"
    if rec.get("npl_date"):
        s += f" (listed {rec['npl_date']})"
    if rec.get("hrs_score") is not None:
        try:
            s += f", with a Hazard Ranking System score of {float(rec['hrs_score']):.2f}"
        except (TypeError, ValueError):
            pass
    s += (". Specific contaminants, the responsible parties, and current cleanup "
          "status are documented in the linked EPA site profile.")
    return s


def _insert_contam(cur, key, rec, source, name_to_fips, desc_source="narrative",
                   narrative_source="hardcoded"):
    contaminants = rec.get("contaminants") or []
    waterways = rec.get("affected_waterways") or []
    counties = rec.get("affected_counties") or []
    county = rec.get("county")
    fips = rec.get("county_fips")
    if not fips and county:
        fips = name_to_fips.get(county)
    status_class = contamination_data.normalize_status(
        rec.get("status"), bool(rec.get("npl_listed")))
    cur.execute(
        """INSERT OR REPLACE INTO contamination_sites(
             site_key, company, site_name, latitude, longitude, county,
             county_fips, city, epa_id, status, status_class, years_active,
             contaminants, description, impact_area_miles, affected_waterways,
             affected_counties, npl_listed, npl_date, hrs_score, category, source,
             desc_source, narrative_source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (key, rec.get("company"), rec.get("site_name"),
         rec.get("lat"), rec.get("lng"), county, fips, rec.get("city"),
         rec.get("epa_id"), rec.get("status"), status_class,
         rec.get("years_active"),
         json.dumps(contaminants), rec.get("description"),
         rec.get("impact_area_miles"),
         json.dumps(waterways), json.dumps(counties),
         1 if rec.get("npl_listed") else 0, rec.get("npl_date"),
         rec.get("hrs_score"), rec.get("category", "other"), source,
         desc_source, narrative_source),
    )


def apply_curated_narratives(conn: sqlite3.Connection) -> int:
    """Write the hand-researched narratives from app/contamination_narratives.py
    onto matching generated sites (by EPA id). Shared by the loader and the
    standalone enrich_narratives.py so a full reload never loses enrichment.
    Only touches desc_source='generated' rows — hardcoded narratives are safe."""
    from .contamination_narratives import FETCHED_NARRATIVES
    cur = conn.cursor()
    applied = 0
    for epa_id, rec in FETCHED_NARRATIVES.items():
        narrative = (rec.get("narrative") or "").strip()
        if not narrative:
            continue
        refs = json.dumps(rec.get("refs") or [])
        res = cur.execute(
            """UPDATE contamination_sites
                  SET narrative = ?, narrative_refs = ?, narrative_source = 'fetched'
                WHERE epa_id = ? AND desc_source = 'generated'""",
            (narrative, refs, epa_id),
        )
        applied += res.rowcount
    conn.commit()
    return applied


def load_contamination_data(conn: sqlite3.Connection) -> int:
    """Load compiled contamination sites + the live EPA NPL list (deduped)."""
    log("Loading industrial contamination (compiled + EPA NPL live)...")
    cur = conn.cursor()
    cur.execute("DELETE FROM contamination_sites")
    conn.commit()

    name_to_fips = {r["name"]: r["fips"]
                    for r in conn.execute("SELECT name, fips FROM counties")}

    # --- compiled sites (rich detail) ---
    seen_epa: set[str] = set()
    seen_slug: set[str] = set()
    compiled = 0
    for src_dict in (contamination_data.MICHIGAN_INDUSTRIAL_CONTAMINATION,
                     contamination_data.PFAS_SITES):
        for key, rec in src_dict.items():
            _insert_contam(cur, key, rec, "compiled", name_to_fips,
                           narrative_source="hardcoded")
            compiled += 1
            if rec.get("epa_id"):
                seen_epa.add(rec["epa_id"].strip().upper())
            seen_slug.add(_contam_slug(rec.get("site_name")))
    conn.commit()

    # --- EPA NPL live ---
    epa_added = 0
    epa_status = "unavailable"
    try:
        raw = http_get(EPA_NPL_QUERY, timeout=90)
        payload = json.loads(raw)
        feats = payload.get("features", [])
        for f in feats:
            a = f.get("attributes", {})
            epa_id = (a.get("Site_EPA_ID") or "").strip()
            name = a.get("Site_Name") or ""
            lat, lng = a.get("Latitude"), a.get("Longitude")
            if lat is None or lng is None:
                continue
            # Skip sites already covered by a compiled record (richer detail).
            if (epa_id and epa_id.upper() in seen_epa) or _contam_slug(name) in seen_slug:
                continue
            county = (a.get("County") or "").strip()
            rec = {
                "company": None,
                "site_name": name,
                "lat": lat, "lng": lng,
                "county": county, "county_fips": name_to_fips.get(county),
                "city": a.get("City"), "epa_id": epa_id or None,
                "status": a.get("Status"),
                "npl_listed": "delet" not in (a.get("Status") or "").lower(),
                "npl_date": _epa_ms_to_iso(a.get("Listing_Date")),
                "hrs_score": a.get("Site_Score"),
                "category": "other",
            }
            # The feed's "Site_Listing_Narrative" is only an <a href> to a PDF,
            # not prose — so synthesize a factual description from the fields.
            rec["description"] = _epa_structured_description(rec)
            key = "epa_" + (epa_id or _contam_slug(name))
            _insert_contam(cur, key, rec, "EPA_SEMS_NPL", name_to_fips,
                           desc_source="generated", narrative_source=None)
            seen_slug.add(_contam_slug(name))
            epa_added += 1
        conn.commit()
        epa_status = "ok"
        log(f"  EPA NPL: {len(feats)} MI sites fetched, {epa_added} added "
            f"(rest already in compiled set)", level="ok")
    except Exception as e:
        log(f"  EPA NPL fetch failed: {e}", level="warn")

    # Re-apply the hand-researched narratives so a full reload keeps them.
    try:
        enriched = apply_curated_narratives(conn)
        if enriched:
            log(f"  applied {enriched} curated narratives", level="ok")
    except Exception as e:
        log(f"  curated-narrative apply failed: {e}", level="warn")

    total = compiled + epa_added
    record_source(
        conn, "epa_sems_npl",
        "EPA Superfund Enterprise Management System (SEMS) — NPL sites",
        "https://www.epa.gov/superfund/superfund-data-and-reports",
        epa_status, epa_added,
        f"{epa_added} EPA NPL sites merged with {compiled} compiled records "
        f"({total} total). Live ArcGIS Feature Service, State='Michigan'.",
    )
    record_source(
        conn, "egle_rrd",
        "Michigan EGLE — Remediation & Redevelopment Division (Part 201 sites)",
        "https://www.michigan.gov/egle/about/organization/remediation-and-redevelopment",
        "reference", 0,
        "State-level contaminated-sites program (thousands of sites beyond the "
        "federal NPL); Environmental Mapper is portal-only, not a bulk feed.",
    )
    record_source(
        conn, "mpart",
        "Michigan PFAS Action Response Team (MPART)",
        "https://www.michigan.gov/pfasresponse/investigations",
        "compiled", sum(1 for d in (contamination_data.MICHIGAN_INDUSTRIAL_CONTAMINATION,
                                    contamination_data.PFAS_SITES)
                        for r in d.values()
                        if any("pfas" in c.lower() for c in (r.get("contaminants") or []))),
        "PFAS investigation sites; major sites compiled into the contamination layer.",
    )
    record_source(
        conn, "epa_region5",
        "EPA Region 5 — Cleanup Activities", "https://www.epa.gov/aboutepa/epa-region-5",
        "reference", 0, "Regional office overseeing Michigan Superfund cleanups.")
    record_source(
        conn, "mdhhs_pbb",
        "MDHHS — Michigan PBB Registry", "https://www.michigan.gov/pbbregistry",
        "reference", 0,
        "Long-term health registry from the 1973 Velsicol PBB contamination event.")
    record_source(
        conn, "atsdr",
        "ATSDR — Toxicological Profiles", "https://www.atsdr.cdc.gov/toxprofiledocs/index.html",
        "reference", 0, "Health-effects reference for the contaminants listed per site.")
    conn.commit()
    log(f"  contamination sites: {total} ({compiled} compiled + {epa_added} EPA)", level="ok")
    return total


def _epa_ms_to_iso(ms) -> str | None:
    """ArcGIS returns epoch-milliseconds for date fields; format as ISO date.
    Avoids Date.now-style nondeterminism — this is a fixed stored timestamp."""
    if ms is None:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


# ---------- EPA Toxics Release Inventory (TRI) ----------

# Exact column headers we read out of the mv_tri_basic_download CSV.
_TRI_COL = {
    "year": "year", "fid": "trifd", "name": "facility name",
    "addr": "street address", "city": "city", "county": "county",
    "lat": "latitude", "lng": "longitude", "parent": "parent co name",
    "naics": "primary naics", "sector": "industry sector",
    "fed": "federal facility",
    "chem": "chemical", "cas": "cas#", "pfas": "pfas", "carc": "carcinogen",
    "fug_air": "5.1 - fugitive air", "stack_air": "5.2 - stack air",
    "water": "5.3 - water", "underground": "5.4 - underground",
    "onsite_total": "on-site release total",
}


def _tri_num(v) -> float:
    """Parse a TRI quantity cell to pounds. Cells look like '1290.0000000000',
    scientific-notation zeros like '0E-10', 'NA', or ''. All coerce to float;
    blanks/NA -> 0.0."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s or s.upper() == "NA":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _tri_fetch_year(year: int) -> Path | None:
    """Download one year's Michigan TRI basic-download CSV to the cache. Reuses
    an existing cached file unless a force-refresh is requested (finalized TRI
    years are immutable). Returns the path, or None if the fetch failed."""
    TRI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRI_CACHE_DIR / f"tri_{TRI_STATE_ABBR}_{year}.csv"
    if not _need_download(path, 200, force=FORCE_REFRESH):
        return path
    url = TRI_MV_URL.format(state=TRI_STATE_ABBR, year=year)
    try:
        n = download_stream(url, path, timeout=180, attempts=4, min_bytes=1)
        log(f"  TRI {year}: downloaded {n:,} bytes", level="ok")
        return path
    except Exception as e:                                # noqa: BLE001
        log(f"  TRI {year}: download failed ({e})", level="warn")
        return None


def load_tri_data(conn: sqlite3.Connection) -> int:
    """Load EPA Toxics Release Inventory releases for Michigan across the
    available reporting years into tri_facility + tri_release.

    Source: EPA Envirofacts `mv_tri_basic_download` view — one flat row per
    facility/chemical/year, filtered to MI (st=MI). All quantities are in
    pounds. Pathways: air = fugitive + stack; water; underground; land is the
    on-site remainder (total - air - water - underground) so the four pathways
    always sum to the reported on-site total without double-counting the many
    RCRA land-disposal sub-columns.
    """
    log("Loading EPA Toxics Release Inventory (TRI) for Michigan...")
    cur = conn.cursor()
    cur.execute("DELETE FROM tri_release")
    cur.execute("DELETE FROM tri_facility")
    conn.commit()

    # Normalize county names for matching: TRI writes "ST JOSEPH" / "ST. CLAIR"
    # in caps with inconsistent periods, vs the counties table's "St. Joseph".
    def _norm_county(s: str) -> str:
        return " ".join((s or "").upper().replace(".", "").split())

    name_to_fips = {_norm_county(r["name"]): r["fips"]
                    for r in conn.execute("SELECT name, fips FROM counties")}

    C = _TRI_COL
    facilities: dict[str, dict] = {}     # fid -> attributes (from most recent year)
    releases: list[tuple] = []
    years_seen: set[int] = set()
    unmatched: set[str] = set()

    def _flt(v):
        try:
            return float(v) if v not in (None, "", "NA") else None
        except (ValueError, TypeError):
            return None

    for year in range(TRI_START_YEAR, TRI_END_YEAR + 1):
        path = _tri_fetch_year(year)
        if path is None:
            continue
        try:
            with path.open(newline="", encoding="utf-8", errors="replace") as fh:
                rows = list(csv.DictReader(fh))
        except OSError as e:
            log(f"  TRI {year}: read failed ({e})", level="warn")
            continue
        if not rows or C["fid"] not in (rows[0].keys() if rows else ()):
            continue
        year_rows = 0
        for row in rows:
            fid = (row.get(C["fid"]) or "").strip()
            chem = (row.get(C["chem"]) or "").strip()
            if not fid or not chem:
                continue
            row_year = int(_flt(row.get(C["year"])) or year)

            county = (row.get(C["county"]) or "").strip()
            fips = name_to_fips.get(_norm_county(county))
            if county and not fips:
                unmatched.add(county)

            attrs = {
                "facility_name": (row.get(C["name"]) or "").strip(),
                "street_address": (row.get(C["addr"]) or "").strip() or None,
                "city": (row.get(C["city"]) or "").strip() or None,
                "county": county or None,
                "county_fips": fips,
                "latitude": _flt(row.get(C["lat"])),
                "longitude": _flt(row.get(C["lng"])),
                "parent_company": (row.get(C["parent"]) or "").strip() or None,
                "naics_code": (row.get(C["naics"]) or "").strip() or None,
                "industry_sector": (row.get(C["sector"]) or "").strip() or None,
                "federal_facility": 1 if (row.get(C["fed"]) or "").strip().upper()
                                    in ("YES", "TRUE", "1") else 0,
                "_year": row_year,
            }
            prev = facilities.get(fid)
            if prev is None or attrs["_year"] >= prev["_year"]:
                facilities[fid] = attrs

            fug = _tri_num(row.get(C["fug_air"]))
            stk = _tri_num(row.get(C["stack_air"]))
            water = _tri_num(row.get(C["water"]))
            ug = _tri_num(row.get(C["underground"]))
            total = _tri_num(row.get(C["onsite_total"]))
            air = fug + stk
            land = max(0.0, total - air - water - ug)
            releases.append((
                fid, row_year, chem,
                (row.get(C["cas"]) or "").strip() or None,
                1 if (row.get(C["pfas"]) or "").strip().upper() == "YES" else 0,
                1 if (row.get(C["carc"]) or "").strip().upper() == "YES" else 0,
                fug, stk, air, water, ug, land, total,
            ))
            year_rows += 1
        if year_rows:
            years_seen.add(year)
            log(f"  TRI {year}: {year_rows:,} release records", level="info")

    if not releases:
        record_source(
            conn, "epa_tri",
            "EPA Toxics Release Inventory (TRI) — Envirofacts",
            "https://www.epa.gov/toxics-release-inventory-tri-program",
            "unavailable", 0,
            "TRI fetch returned no data (Envirofacts unavailable or view changed).")
        conn.commit()
        log("  TRI: no data loaded", level="warn")
        return 0

    for fid, a in facilities.items():
        cur.execute(
            """INSERT INTO tri_facility(
                 facility_id, facility_name, street_address, city, county,
                 county_fips, latitude, longitude, parent_company, naics_code,
                 industry_sector, federal_facility)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fid, a["facility_name"], a["street_address"], a["city"], a["county"],
             a["county_fips"], a["latitude"], a["longitude"], a["parent_company"],
             a["naics_code"], a["industry_sector"], a["federal_facility"]))
    cur.executemany(
        """INSERT INTO tri_release(
             facility_id, year, chemical, cas, is_pfas, is_carcinogen,
             fugitive_air_lbs, stack_air_lbs, air_lbs, water_lbs,
             underground_lbs, land_lbs, total_lbs)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        releases)
    conn.commit()

    y0, y1 = (min(years_seen), max(years_seen)) if years_seen else (None, None)
    if unmatched:
        log(f"  TRI: {len(unmatched)} unmatched county name(s): "
            f"{sorted(unmatched)[:10]}", level="warn")
    record_source(
        conn, "epa_tri",
        "EPA Toxics Release Inventory (TRI) — Envirofacts",
        "https://www.epa.gov/toxics-release-inventory-tri-program",
        "ok", len(releases),
        f"{len(facilities):,} MI facilities; {len(releases):,} "
        f"facility-chemical-year release records, {y0}-{y1}. Self-reported "
        f"annually under EPCRA. Envirofacts mv_tri_basic_download (st=MI).",
        coverage_start=str(y0) if y0 else None,
        coverage_end=str(y1) if y1 else None,
    )
    conn.commit()
    log(f"  TRI: {len(facilities):,} facilities, {len(releases):,} releases "
        f"({y0}-{y1})", level="ok")
    return len(releases)


# ---------- driver ----------

def load_wind_data(conn: sqlite3.Connection) -> int:
    """Fetch growing-season (Apr-Sep) hourly wind from IEM ASOS for the key
    Michigan stations and build a per-station wind rose. Stores one aggregate
    row per station (month=0, season='growing') into wind_data.
    """
    WIND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    y0, y1 = min(WIND_YEARS), max(WIND_YEARS)
    m0, m1 = WIND_SEASON_MONTHS
    years_label = f"{y0}-{y1}"
    conn.execute("DELETE FROM wind_data")

    inserted = 0
    for st in MI_ASOS_STATIONS:
        sid = st["id"]
        # One request per station spanning the whole window; filter months in code.
        url = (
            f"{IEM_ASOS_URL}?station={sid}&data=drct&data=sped"
            f"&year1={y0}&month1=1&day1=1&year2={y1}&month2=12&day2=31"
            "&tz=America/Detroit&format=onlycomma&latlon=yes"
            "&missing=M&trace=T&direct=no&report_type=3&report_type=4"
        )
        cache = WIND_CACHE_DIR / f"{sid}.csv"
        try:
            if not cache.exists() or cache.stat().st_size < 200:
                log(f"IEM ASOS {sid} -> downloading growing-season wind...")
                size = download_to(url, cache, timeout=180)
                log(f"  fetched {size/1024:.0f} KB -> {cache.name}", level="ok")
        except Exception as e:
            log(f"  IEM {sid} download failed: {e}", level="warn")
            continue

        counts = {d: 0 for d in DIRS_16}
        spd_sum = {d: 0.0 for d in DIRS_16}
        n_dir = 0            # non-calm obs with a valid direction
        n_speed = 0          # obs with a valid speed
        n_calm = 0           # obs with speed < 3 mph
        speed_total = 0.0
        lat_acc = lon_acc = 0.0
        n_pos = 0

        try:
            with cache.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    valid = row.get("valid") or ""
                    # 'YYYY-MM-DD HH:MM' -> month
                    try:
                        month = int(valid[5:7])
                    except ValueError:
                        continue
                    if not (m0 <= month <= m1):
                        continue
                    try:
                        sped = float(row.get("sped"))
                    except (TypeError, ValueError):
                        continue
                    n_speed += 1
                    speed_total += sped
                    try:
                        la = float(row.get("lat")); lo = float(row.get("lon"))
                        lat_acc += la; lon_acc += lo; n_pos += 1
                    except (TypeError, ValueError):
                        pass
                    if sped < 3.0:
                        n_calm += 1
                        continue    # calm: direction not meaningful
                    try:
                        drct = float(row.get("drct"))
                    except (TypeError, ValueError):
                        continue
                    d = deg_to_dir16(drct)
                    counts[d] += 1
                    spd_sum[d] += sped
                    n_dir += 1
        except Exception as e:
            log(f"  IEM {sid} parse failed: {e}", level="warn")
            continue

        if n_speed == 0 or n_dir == 0:
            log(f"  IEM {sid}: no growing-season obs, skipping", level="warn")
            continue

        speed_by_dir = {d: round(spd_sum[d] / counts[d], 2) if counts[d] else 0.0
                        for d in DIRS_16}
        prevailing = max(DIRS_16, key=lambda d: counts[d])
        lat = lat_acc / n_pos if n_pos else st["lat"]
        lon = lon_acc / n_pos if n_pos else st["lon"]

        conn.execute(
            """INSERT INTO wind_data(
                  station_id, station_name, latitude, longitude, county, county_fips,
                  month, direction_deg, avg_speed_mph, pct_calm,
                  direction_counts, speed_by_direction, n_obs, years, season)
               VALUES (?,?,?,?,?,?,0,?,?,?,?,?,?,?, 'growing')""",
            (
                sid, st["name"], lat, lon, st["county"], st["county_fips"],
                dir16_to_deg(prevailing),
                round(speed_total / n_speed, 2),
                round(100.0 * n_calm / n_speed, 1),
                json.dumps(counts),
                json.dumps(speed_by_dir),
                n_dir, years_label,
            ),
        )
        inserted += 1
        log(f"  {sid} {st['name']}: prevailing {prevailing}, "
            f"{speed_total/n_speed:.1f} mph avg, {100.0*n_calm/n_speed:.0f}% calm "
            f"({n_dir:,} obs)", level="ok")

    conn.commit()
    record_source(
        conn, "iem_asos_wind", "Iowa Environmental Mesonet ASOS hourly wind",
        IEM_ASOS_URL, "ok" if inserted else "unavailable", inserted,
        f"Growing season (Apr-Sep) {years_label}; {inserted} MI stations.",
    )
    return inserted


def _migrate(conn: sqlite3.Connection) -> None:
    """One-shot migrations for schema changes that CREATE TABLE IF NOT EXISTS
    can't apply. We drop correlation_analysis if it lacks the new columns; it
    is fully rebuilt at the end of every loader run anyway.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(correlation_analysis)")}
    if cols and "asthma_ed_rate" not in cols:
        log("schema migration: dropping correlation_analysis to pick up new columns", level="warn")
        conn.execute("DROP TABLE correlation_analysis")
        conn.commit()

    # contamination_sites: add desc_source column (rows are rebuilt each run, so
    # a non-destructive ALTER is enough to make the new INSERT columns valid).
    ccols = {r[1] for r in conn.execute("PRAGMA table_info(contamination_sites)")}
    if ccols and "desc_source" not in ccols:
        log("schema migration: adding contamination_sites.desc_source", level="warn")
        conn.execute("ALTER TABLE contamination_sites ADD COLUMN desc_source TEXT DEFAULT 'narrative'")
        conn.commit()
    if ccols and "narrative" not in ccols:
        log("schema migration: adding contamination_sites narrative columns", level="warn")
        conn.execute("ALTER TABLE contamination_sites ADD COLUMN narrative TEXT")
        conn.execute("ALTER TABLE contamination_sites ADD COLUMN narrative_source TEXT")
        conn.execute("ALTER TABLE contamination_sites ADD COLUMN narrative_refs TEXT")
        conn.commit()

    # data_sources: add provenance/freshness columns used by refresh_data.py.
    dcols = {r[1] for r in conn.execute("PRAGMA table_info(data_sources)")}
    for col, decl in (
        ("coverage_start", "TEXT"),
        ("coverage_end", "TEXT"),
        ("refresh_status", "TEXT"),
        ("refresh_interval_months", "INTEGER"),
        ("last_success", "TEXT"),
        ("last_attempt", "TEXT"),
    ):
        if dcols and col not in dcols:
            log(f"schema migration: adding data_sources.{col}", level="warn")
            conn.execute(f"ALTER TABLE data_sources ADD COLUMN {col} {decl}")
    conn.commit()


def run() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = database.connect()
    _migrate(conn)
    database.init_schema(conn)
    log(f"SQLite database: {conn.execute('PRAGMA database_list').fetchone()[2]}")

    counties = load_counties_geojson(conn)
    log(f"counties loaded: {counties}", level="ok")

    rows, ok_years, failed_years = load_usgs_pesticide_use(conn)
    log(f"USGS pesticide_use rows: {rows:,} across {len(ok_years)} years", level="ok")

    nass_rows = load_nass_crop_acreage(conn)
    log(f"NASS crop_acreage rows: {nass_rows:,}")

    record_reference_sources(conn)
    resp_rows = load_respiratory_data(conn)
    log(f"Respiratory rows loaded: {resp_rows}", level="ok")
    wq_sites, wq_results = load_water_quality(conn)
    log(f"Water-quality: {wq_sites:,} sites, {wq_results:,} results", level="ok")
    corr_rows = build_correlation_table(conn)
    log(f"correlation_analysis rows: {corr_rows}", level="ok")

    cancer_real, cancer_base = load_cancer_data(conn)
    log(f"cancer rows: {cancer_real} real + {cancer_base} baseline", level="ok")
    cancer_corr = build_cancer_correlations(conn)
    log(f"cancer_pesticide_correlation rows: {cancer_corr}", level="ok")

    contam_rows = load_contamination_data(conn)
    log(f"contamination_sites rows: {contam_rows}", level="ok")

    wind_rows = load_wind_data(conn)
    log(f"wind_data stations loaded: {wind_rows}", level="ok")

    tri_rows = load_tri_data(conn)
    log(f"TRI release records loaded: {tri_rows}", level="ok")
    conn.commit()

    # Summary
    cur = conn.cursor()
    for t in ("counties", "pesticide_use", "pesticide_categories",
              "crop_acreage", "data_sources",
              "respiratory_ed_visits", "respiratory_hospitalizations",
              "respiratory_prevalence", "respiratory_mortality",
              "water_quality_sites", "water_quality_results", "watersheds",
              "correlation_analysis", "cancer_incidence",
              "cancer_pesticide_correlation", "cancer_evidence",
              "contamination_sites", "wind_data",
              "tri_facility", "tri_release"):
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        log(f"  {t:25s} {n:>10,}")
    conn.close()
    log("Data load complete.", level="ok")
    return 0


if __name__ == "__main__":
    sys.exit(run())
