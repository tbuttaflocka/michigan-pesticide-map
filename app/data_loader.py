"""
Downloads real data from USGS NAWQA, US Census GeoJSON, and (optionally) USDA NASS,
filters everything to Michigan, and populates the SQLite database.

Run as:  python -m app.data_loader
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import database
from . import spraying_programs
from . import stats
from .categories import categorize
from .config import (
    CENSUS_GAZ_BASE,
    CENSUS_GAZ_CACHE_DIR,
    CENSUS_GAZ_COUSUB_URL,
    CENSUS_GAZ_PLACE_URL,
    CENSUS_GAZ_YEAR,
    CENSUS_GAZ_ZCTA_URL,
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
    USGS_CROP_USE_DOI,
    USGS_CROP_USE_FILES,
    USGS_CROP_GROUPS,
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
    benchmark_for,
    canonicalize_compound,
    mcl_for,
    to_ugl,
)
from .respiratory_data import (
    MI_BROADER_RESP_BASELINE,
    MI_STATEWIDE_BASELINE,
    URBAN_COUNTIES,
)
from . import cancer_data
from . import contamination_data
from . import landfill_data
from . import golf_data
from . import pfas_data
from . import ust_data
from .config import (
    CANCER_DATA_DIR,
    EPA_NPL_QUERY,
    NCI_INCIDENCE_URL,
    NCI_MORTALITY_URL,
    NCI_SCP_BASE,
    EGLE_LANDFILL_QUERY,
    EGLE_TSDF_QUERY,
    EGLE_FOIA_URL,
    GEOJSON_PATH,
    OVERPASS_ENDPOINTS,
    OVERPASS_GOLF_QUERY,
    PFAS_SITES_URL,
    PFAS_SURFACE_WATER_URL,
    PFAS_PWS_HEXBIN_URL,
    PFAS_PWS_RESULTS_URL,
    PFAS_FISH_SITES_URL,
    PFAS_FISH_DATA_URL,
    PFAS_POTW_URL,
    MPART_HOME_URL,
    MPART_HUB_URL,
    MDHHS_EAT_SAFE_FISH_URL,
    UST_URL,
    EGLE_RIDE_URL,
    EGLE_UST_HOME_URL,
    AIRTOXICS_RISK_URL,
    AIRTOXICS_HOME_URL,
)
from . import airtoxics_data


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


# ---------- 2b. USGS state-level pesticide use by major crop / crop group ----

def _crop_use_norm(s: str) -> str:
    """Exact-match key: lowercase, strip ALL whitespace and punctuation. Used
    ONLY to CHECK correspondence against existing tables (compounds vs
    pesticide_use, crop groups vs crop_acreage) — never to rewrite, fuzzy-match,
    or force-match the published names."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _read_mi_crop_use(path: Path) -> dict:
    """Parse one wide-format estimate file into
    {(compound, year): {crop_group: raw_value_str}} for Michigan (FIPS 26) only.
    Values are kept as raw strings so blank ("no estimate") stays distinct from
    "0" (estimated but below the reporting threshold)."""
    out: dict = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            if (row.get("State_FIPS_code") or "").strip() != MICHIGAN_STATE_FIPS:
                continue
            try:
                year = int(row["Year"])
            except (ValueError, KeyError, TypeError):
                continue
            key = ((row.get("Compound") or "").strip(), year)
            out[key] = {c: (row.get(c) or "").strip() for c in USGS_CROP_GROUPS}
    return out


def load_usgs_pesticide_use_by_crop(conn: sqlite3.Connection) -> int:
    """Download + ingest the USGS state-level 'pesticide use by major crop or
    crop group' release (DOI 10.5066/P900FZ6Y), Michigan only, into
    pesticide_use_by_crop.

    The release ships the EPest-LOW and EPest-HIGH methods as two separate
    wide-format files (one crop group per column); we unpivot to long form and
    keep both estimates in their own columns (never averaged). A blank cell means
    "no use estimated" (stored NULL); an explicit 0 means "estimated but below
    threshold" (stored 0.0) — the two are preserved distinctly.

    Logs how the file's compounds and crop groups line up with our existing
    pesticide_use / crop_acreage tables on an EXACT normalized key. Nothing is
    force-matched or dropped on a mismatch — unmatched names are reported as-is.
    Returns the number of rows inserted."""
    paths: dict = {}
    for est, (url, filename) in USGS_CROP_USE_FILES.items():
        local = DATA_DIR / filename
        log(f"USGS pesticide-use-by-crop ({est}) -> {filename}")
        try:
            if not local.exists() or local.stat().st_size < 100_000:
                size = download_to(url, local, timeout=600)
                log(f"  fetched {size/1_000_000:.1f} MB", level="ok")
            else:
                log(f"  using cached ({local.stat().st_size/1_000_000:.1f} MB)")
        except Exception as e:
            log(f"  download failed ({est}): {e}", level="warn")
            record_source(conn, "usgs_epest_crop",
                          "USGS — agricultural pesticide use by major crop or "
                          "crop group (state-level, 1992-2019)",
                          USGS_CROP_USE_DOI, "unavailable", 0,
                          f"Download failed for {est}-estimate file: {e}")
            conn.commit()
            return 0
        paths[est] = local

    low = _read_mi_crop_use(paths["low"])
    high = _read_mi_crop_use(paths["high"])

    def _val(v: str):
        """Raw cell -> float or None. Blank/NA = no estimate (None); '0' kept."""
        if v in ("", "NA", "ND", "NaN"):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    cur = conn.cursor()
    # Idempotent re-run: clear Michigan rows so a compound/crop that dropped out
    # of the source doesn't linger (INSERT OR REPLACE only overwrites collisions).
    cur.execute("DELETE FROM pesticide_use_by_crop WHERE state_fips = ?",
                (MICHIGAN_STATE_FIPS,))
    batch: list[tuple] = []
    inserted = 0
    compounds: set[str] = set()
    years: set[int] = set()
    crops_present: set[str] = set()
    for (compound, year) in set(low) | set(high):
        lo = low.get((compound, year), {})
        hi = high.get((compound, year), {})
        compounds.add(compound)
        years.add(year)
        for crop in USGS_CROP_GROUPS:
            lv, hv = lo.get(crop, ""), hi.get(crop, "")
            if lv == "" and hv == "":
                continue                 # no estimate for this crop/compound/year
            batch.append((MICHIGAN_STATE_FIPS, "Michigan", compound, crop, year,
                          _val(lv), _val(hv)))
            crops_present.add(crop)
            if len(batch) >= 5000:
                cur.executemany("INSERT OR REPLACE INTO pesticide_use_by_crop "
                                "VALUES (?,?,?,?,?,?,?)", batch)
                inserted += len(batch)
                batch.clear()
    if batch:
        cur.executemany("INSERT OR REPLACE INTO pesticide_use_by_crop "
                        "VALUES (?,?,?,?,?,?,?)", batch)
        inserted += len(batch)
    conn.commit()

    # ---- exact-normalized correspondence checks (report only) ----
    db_comp = {r[0] for r in cur.execute(
        "SELECT DISTINCT compound FROM pesticide_use")}
    db_comp_norm = {_crop_use_norm(c) for c in db_comp}
    matched = sorted(c for c in compounds if _crop_use_norm(c) in db_comp_norm)
    unmatched = sorted(c for c in compounds if _crop_use_norm(c) not in db_comp_norm)
    log(f"  compound exact-match vs pesticide_use: "
        f"{len(matched)}/{len(compounds)} matched", level="ok")
    if unmatched:
        log(f"  unmatched compounds (kept as published, NOT force-matched): "
            f"{unmatched}", level="warn")

    nass = {r[0] for r in cur.execute("SELECT DISTINCT crop FROM crop_acreage")}
    nass_norm = {_crop_use_norm(c): c for c in nass}
    file_norm = {_crop_use_norm(c) for c in USGS_CROP_GROUPS}
    for crop in USGS_CROP_GROUPS:
        m = nass_norm.get(_crop_use_norm(crop))
        log(f"    crop group {crop!r} -> "
            f"{m + ' (crop_acreage)' if m else 'no exact NASS counterpart'}")
    nass_only = sorted(c for c in nass if _crop_use_norm(c) not in file_norm)
    if nass_only:
        log(f"  NASS crops with no crop-group counterpart: {nass_only}",
            level="warn")

    ys = sorted(years)
    span = f"{ys[0]}-{ys[-1]}" if ys else "none"
    notes = (
        f"Michigan only. {inserted:,} rows; {len(compounds)} compounds; "
        f"{len(crops_present)} of {len(USGS_CROP_GROUPS)} crop groups with data; "
        f"years {span}. EPest low/high kept separate (never averaged); "
        f"blank=no estimate, 0=below threshold. Compound exact-match to county "
        f"EPest: {len(matched)}/{len(compounds)}"
        + (f" (unmatched: {', '.join(unmatched)})" if unmatched else "")
        + ". Crop groups matching NASS crop_acreage: Corn, Soybeans, Wheat."
    )
    record_source(conn, "usgs_epest_crop",
                  "USGS — agricultural pesticide use by major crop or crop group "
                  "(state-level, 1992-2019)",
                  USGS_CROP_USE_DOI, "ok", inserted, notes,
                  coverage_start=str(ys[0]) if ys else None,
                  coverage_end=str(ys[-1]) if ys else None)
    conn.commit()
    log(f"pesticide_use_by_crop rows: {inserted:,} (MI, {span})", level="ok")
    return inserted


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
    # --- Spraying Programs directory (curated, links out to official pages) --- #
    record_source(
        conn, "spraying_programs",
        "Michigan Spraying Programs (directory)",
        "https://www.michigan.gov/invasives/id-report/insects/spongy-moth",
        "reference", len(spraying_programs.SPRAYING_PROGRAMS),
        "Curated directory of organized, publicly-documented Michigan spraying "
        "programs (county spongy-moth suppression, county mosquito abatement, and "
        "MDHHS arbovirus response). Each entry links to its official page for "
        "current schedules; not a live spray-date feed and not a complete list of "
        "all spraying.",
    )
    record_source(
        conn, "mdhhs_arbovirus",
        "MDHHS Arbovirus (EEE / West Nile) Response",
        "https://www.michigan.gov/emergingdiseases/home/eastern-equine-encephalitis",
        "reference", 0,
        "State outbreak-year aerial ULV mosquito treatment response. Current-year "
        "info at Michigan.gov/EEE. Linked in the Spraying Programs layer.",
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
                # Presence-only records (SIR 2007-5077 reported detections, not
                # concentrations) — no value to compare, so neither standard is
                # flagged; we still record which limits apply for reference.
                cur.execute(
                    """INSERT INTO water_quality_results(
                          site_id, sample_date, compound, result_value, unit,
                          detected, exceeds_mcl, mcl_value,
                          exceeds_benchmark, benchmark_value, medium)
                       VALUES (?, '2002-2005', ?, NULL, 'unspecified',
                               1, 0, ?, 0, ?, 'Water')""",
                    (s["site_id"], compound, mcl_for(compound), benchmark_for(compound)),
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
            # Exceedances — compared in µg/L. The human drinking-water MCL and
            # the ecological aquatic-life benchmark are SEPARATE standards; a
            # sample can exceed either, both, or neither, so we flag them
            # independently and never conflate them.
            mcl = mcl_for(compound)
            benchmark = benchmark_for(compound)
            exceeds_mcl = 0
            exceeds_benchmark = 0
            if detected and result_value is not None:
                ugl = _to_ugl(result_value, unit)
                if ugl is not None:
                    if mcl is not None and ugl > mcl:
                        exceeds_mcl = 1
                    if benchmark is not None and ugl > benchmark:
                        exceeds_benchmark = 1
            batch.append((
                site_id, sample_date, compound,
                result_value, unit, detection_limit,
                detected, exceeds_mcl, mcl, exceeds_benchmark, benchmark, medium,
            ))
            if len(batch) >= 5000:
                cur.executemany(
                    """INSERT INTO water_quality_results(
                          site_id, sample_date, compound, result_value, unit,
                          detection_limit, detected, exceeds_mcl, mcl_value,
                          exceeds_benchmark, benchmark_value, medium)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    batch,
                )
                inserted += len(batch)
                batch.clear()
    if batch:
        cur.executemany(
            """INSERT INTO water_quality_results(
                  site_id, sample_date, compound, result_value, unit,
                  detection_limit, detected, exceeds_mcl, mcl_value,
                  exceeds_benchmark, benchmark_value, medium)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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


# ---------- Landfills & waste facilities (Michigan EGLE Materials Mgmt) ----------

def _to_float(v) -> float | None:
    try:
        f = float(str(v).strip())
        return f if f == f else None      # reject NaN
    except (TypeError, ValueError):
        return None


def _title_case_county(name: str | None) -> str | None:
    return name.title() if name else None


def _build_crosslink_index(conn: sqlite3.Connection):
    """Group the app's existing TRI facilities and contamination sites by
    county_fips so each landfill only compares against local candidates."""
    tri_by_fips: dict[str, list] = {}
    for r in conn.execute(
        "SELECT facility_id, facility_name, latitude, longitude, county_fips "
        "FROM tri_facility WHERE county_fips IS NOT NULL"):
        tri_by_fips.setdefault(r["county_fips"], []).append(dict(r))

    contam_by_fips: dict[str, list] = {}
    for r in conn.execute(
        "SELECT site_key, site_name, company, status, latitude, longitude, "
        "county_fips FROM contamination_sites WHERE county_fips IS NOT NULL"):
        contam_by_fips.setdefault(r["county_fips"], []).append(dict(r))
    return tri_by_fips, contam_by_fips


def _best_crosslink(lf: dict, candidates: list, *name_fields: str):
    """Return the best-matching candidate for a landfill, or None. Matches on
    genuine shared name tokens (against the landfill's name AND operator); a
    coordinate check only rejects implausibly distant pairs — it never creates a
    match (see landfill_data for the precision-first rationale)."""
    lf_names = [lf.get("name"), lf.get("operator")]
    best, best_score, best_dist = None, 0.0, None
    for c in candidates:
        cand_names = [c.get(f) for f in name_fields]
        score = max(landfill_data.match_names(ln, cn)
                    for ln in lf_names for cn in cand_names)
        if score <= 0:
            continue
        dist = None
        if c.get("latitude") is not None and c.get("longitude") is not None:
            dist = landfill_data.haversine_km(
                lf["latitude"], lf["longitude"], c["latitude"], c["longitude"])
            if dist > landfill_data.CROSSLINK_MAX_KM:
                continue
        # Prefer the stronger name match, then the closer facility.
        better = (best is None or score > best_score
                  or (score == best_score and dist is not None
                      and (best_dist is None or dist < best_dist)))
        if better:
            best, best_score, best_dist = c, score, dist
    return best


def _tri_latest_total(conn: sqlite3.Connection, facility_id: str):
    row = conn.execute(
        "SELECT year, SUM(total_lbs) AS total FROM tri_release "
        "WHERE facility_id = ? GROUP BY year ORDER BY year DESC LIMIT 1",
        (facility_id,)).fetchone()
    if not row:
        return None, None
    return row["total"], row["year"]


def load_landfills(conn: sqlite3.Connection) -> int:
    """Load Michigan landfills & disposal-capable hazardous-waste facilities from
    EGLE's Materials Management Open Data ArcGIS service, and cross-link each to
    the app's existing TRI and Superfund/contamination records."""
    log("Loading landfills & waste facilities (Michigan EGLE Open Data)...")
    cur = conn.cursor()
    cur.execute("DELETE FROM landfill_sites")
    conn.commit()

    # EGLE writes county names without the period ("St Clair"); the counties
    # table has "St. Clair". Normalize both sides so the FIPS lookup matches.
    def _ckey(name):
        return (name or "").replace(".", "").strip().lower()
    fips_by_lname = {_ckey(name): fips
                     for fips, name in _county_fips_list(conn)}
    tri_by_fips, contam_by_fips = _build_crosslink_index(conn)

    sites: dict[str, dict] = {}      # site_key -> assembled record

    # ---- Part 115 solid-waste landfills (layer 6), grouped by facility ----
    p115_ok = False
    p115_rows = 0
    try:
        payload = json.loads(http_get(EGLE_LANDFILL_QUERY, timeout=90))
        for f in payload.get("features", []):
            a = f.get("attributes", {})
            lat = _to_float(a.get("latdeccord"))
            lng = _to_float(a.get("longdeccord"))
            if lat is None or lng is None:
                continue
            wdsid = a.get("wdsid")
            key = f"egle:{wdsid}" if wdsid else f"egle:{a.get('specificsitename')}"
            ftype = a.get("facilitytype")
            cat, tlabel = landfill_data.classify_type(ftype)
            county = _title_case_county(a.get("countyname"))
            rec = sites.get(key)
            if rec is None:
                st_class, st_label = landfill_data.classify_status(
                    a.get("disposalareastatus"))
                sites[key] = {
                    "site_key": key,
                    "program": "part115",
                    "name": (a.get("specificsitename") or a.get("legalsitename")
                             or "Solid-waste landfill").strip(),
                    "operator": (a.get("legalsitename") or "").strip() or None,
                    "category": cat,
                    "type_label": tlabel,
                    "facility_types": [ftype] if ftype else [],
                    "status_class": st_class,
                    "status_label": st_label,
                    "license_id": str(wdsid) if wdsid else None,
                    # Part 115 carries a single facility ID (the WDS ID, above);
                    # no distinct second identifier to surface.
                    "alt_id": None,
                    "alt_id_label": None,
                    "address": (a.get("addrline1") or "").strip() or None,
                    "city": (a.get("city") or "").strip().title() or None,
                    "zip": (a.get("zip") or "").strip() or None,
                    "county": county,
                    "county_fips": fips_by_lname.get(_ckey(county)),
                    "latitude": lat,
                    "longitude": lng,
                    "egle_url": (a.get("landfilllink") or "").strip() or None,
                    "federal_regulated": 0,
                    "commercial": 0,
                }
            else:
                if ftype and ftype not in rec["facility_types"]:
                    rec["facility_types"].append(ftype)
            p115_rows += 1
        p115_ok = True
        log(f"  Part 115 landfills: {p115_rows} disposal-area rows across "
            f"{len(sites)} facilities", level="ok")
    except Exception as e:                       # noqa: BLE001
        log(f"  Part 115 landfill fetch failed: {e}", level="warn")

    # Multi-area sites: keep the joined list of types and refine the label.
    for rec in sites.values():
        if len(rec["facility_types"]) > 1:
            rec["type_label"] = "; ".join(dict.fromkeys(rec["facility_types"]))

    # ---- Part 111 hazardous-waste TSDFs (layer 7): disposal-capable only ----
    p111_ok = False
    p111_count = 0
    try:
        payload = json.loads(http_get(EGLE_TSDF_QUERY, timeout=90))
        for f in payload.get("features", []):
            a = f.get("attributes", {})
            code = (a.get("FacilityType") or "").strip().upper()
            if "D" not in code:                  # keep only land-disposal TSDFs
                continue
            lat = _to_float(a.get("Latitude"))
            lng = _to_float(a.get("Longitude"))
            if lat is None or lng is None:
                continue
            sid = a.get("SiteId") or a.get("WDSId")
            wdsid = a.get("WDSId")
            key = f"tsdf:{sid}"
            county = _title_case_county(a.get("County"))
            commercial = 1 if "accepts" in (a.get("CommercialFacility") or "").lower() \
                and "does not" not in (a.get("CommercialFacility") or "").lower() else 0
            sites[key] = {
                "site_key": key,
                "program": "part111",
                "name": (a.get("SiteSpecificName") or a.get("LegalName")
                         or "Hazardous-waste facility").strip(),
                "operator": (a.get("LegalName") or "").strip() or None,
                "category": "hazardous",
                "type_label": "Hazardous waste — "
                              + landfill_data.tsdf_type_label(code).lower(),
                "facility_types": [landfill_data.tsdf_type_label(code)],
                "status_class": "active",
                "status_label": "Active (Part 111 licensed)",
                "license_id": str(sid) if sid else None,
                # The Part 111 layer carries TWO identifiers: the EPA/RCRA handler
                # ID (SiteId, used above as license_id) and EGLE's internal Waste
                # Data System ID (WDSId). EGLE's records center asks for a facility
                # ID, so expose the EGLE-native WDS ID as an additional field when
                # it's genuinely a second, distinct identifier.
                "alt_id": (str(wdsid) if wdsid and str(wdsid) != str(sid) else None),
                "alt_id_label": ("EGLE Waste Data System (WDS) ID"
                                 if wdsid and str(wdsid) != str(sid) else None),
                "address": (a.get("Address") or "").strip() or None,
                "city": (a.get("City") or "").strip().title() or None,
                "zip": None,
                "county": county,
                "county_fips": fips_by_lname.get(_ckey(county)),
                "latitude": lat,
                "longitude": lng,
                "egle_url": (a.get("Hyperlink") or "").strip() or None,
                "federal_regulated": 1 if a.get("FederallyRegulatedTSD") in (-1, 1) else 0,
                "commercial": commercial,
            }
            p111_count += 1
        p111_ok = True
        log(f"  Part 111 TSDFs (disposal-capable): {p111_count}", level="ok")
    except Exception as e:                       # noqa: BLE001
        log(f"  Part 111 TSDF fetch failed: {e}", level="warn")

    # ---- cross-link to TRI + contamination, then insert ----
    tri_links = contam_links = 0
    for rec in sites.values():
        fips = rec["county_fips"]
        tri = _best_crosslink(rec, tri_by_fips.get(fips, []), "facility_name") if fips else None
        if tri:
            total, year = _tri_latest_total(conn, tri["facility_id"])
            rec["tri_facility_id"] = tri["facility_id"]
            rec["tri_total_lbs"] = total
            rec["tri_year"] = year
            tri_links += 1
        cs = _best_crosslink(rec, contam_by_fips.get(fips, []),
                             "site_name", "company") if fips else None
        if cs:
            rec["contam_site_key"] = cs["site_key"]
            rec["contam_status"] = cs.get("status")
            contam_links += 1

    for rec in sites.values():
        cur.execute(
            """INSERT OR REPLACE INTO landfill_sites(
                 site_key, program, name, operator, category, type_label,
                 facility_types, status_class, status_label, license_id,
                 alt_id, alt_id_label, address,
                 city, zip, county, county_fips, latitude, longitude, egle_url,
                 federal_regulated, commercial, tri_facility_id, tri_total_lbs,
                 tri_year, contam_site_key, contam_status, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec["site_key"], rec["program"], rec["name"], rec.get("operator"),
             rec["category"], rec["type_label"],
             json.dumps(rec["facility_types"]), rec["status_class"],
             rec["status_label"], rec.get("license_id"),
             rec.get("alt_id"), rec.get("alt_id_label"), rec.get("address"),
             rec.get("city"), rec.get("zip"), rec.get("county"),
             rec.get("county_fips"), rec["latitude"], rec["longitude"],
             rec.get("egle_url"), rec.get("federal_regulated", 0),
             rec.get("commercial", 0), rec.get("tri_facility_id"),
             rec.get("tri_total_lbs"), rec.get("tri_year"),
             rec.get("contam_site_key"), rec.get("contam_status"), "EGLE_MMD"),
        )
    conn.commit()

    total = len(sites)
    status = "ok" if (p115_ok and total) else ("partial" if total else "unavailable")
    log(f"  landfills: {total} facilities "
        f"({tri_links} TRI cross-links, {contam_links} contamination cross-links)",
        level="ok" if total else "warn")
    record_source(
        conn, "egle_landfills",
        "Michigan EGLE — Part 115 landfills & Part 111 hazardous-waste facilities",
        "https://www.michigan.gov/egle/about/organization/materials-management/"
        "solid-waste/solid-waste-disposal-areas",
        status, total,
        f"{total} facilities from EGLE Materials Management Open Data (live "
        f"ArcGIS): active/accepting Part 115 solid-waste landfills + "
        f"disposal-capable Part 111 hazardous-waste TSDFs. Active-only — closed / "
        f"pre-regulation landfills are not in this feed. Monitoring results are "
        f"FOIA-only.",
    )
    # Secondary sources referenced in the overlay (context; not per-facility joined).
    record_source(
        conn, "egle_materials_mgmt",
        "Michigan EGLE — Materials Management Division (solid-waste disposal areas)",
        "https://www.michigan.gov/egle/about/organization/materials-management/"
        "solid-waste/solid-waste-disposal-areas",
        "reference", 0,
        "Searchable list + interactive map of Type II / Type III disposal areas; "
        "annual solid-waste reports. Source of the Part 115 facility layer.",
    )
    record_source(
        conn, "epa_lmop",
        "EPA Landfill Methane Outreach Program (LMOP) — landfill gas database",
        "https://www.epa.gov/lmop/landfill-technical-data",
        "reference", 0,
        "National landfill methane generation / gas-collection & energy-project "
        "data. Published as a bulk database (not a per-facility API); referenced "
        "for landfill-gas context, not joined per facility.",
    )
    record_source(
        conn, "epa_rcrainfo",
        "EPA RCRAInfo / Envirofacts — hazardous-waste handlers (RCRA Subtitle C)",
        "https://enviro.epa.gov/envirofacts/rcrainfo/search",
        "reference", 0,
        "Federal hazardous-waste facility system behind the Part 111 TSDFs. "
        "The mapped disposal facilities come from EGLE's state layer.",
    )
    return total


# ---------- Golf courses (OpenStreetMap via Overpass) ----------
#
# We map golf-course LOCATIONS only. Michigan publishes no golf-course pesticide
# data, so no amount is ever loaded or estimated (see app/golf_data.py). County
# is derived from the course centroid by point-in-polygon against the Michigan
# counties GeoJSON — OSM courses aren't reliably tagged with a county.

def _build_county_locator():
    """Return locate(lng, lat) -> (fips, name) using the counties GeoJSON.

    Pure-Python ray-casting with a bbox pre-filter (no shapely dependency). Reads
    the on-disk GeoJSON so it works identically in live and staging runs."""
    try:
        gj = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
    except OSError:
        return lambda lng, lat: (None, None)
    polys = []   # (fips, name, [ (ring, minx,miny,maxx,maxy), ... ])
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        fips = props.get("fips")
        name = props.get("name")
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        rings = []
        if gtype == "Polygon":
            rings = coords[:1]                       # outer ring only
        elif gtype == "MultiPolygon":
            rings = [poly[0] for poly in coords if poly]   # each part's outer ring
        boxed = []
        for ring in rings:
            xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
            boxed.append((ring, min(xs), min(ys), max(xs), max(ys)))
        if boxed:
            polys.append((fips, name, boxed))

    def _in_ring(x, y, ring) -> bool:
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > y) != (yj > y)) and \
               (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-16) + xi):
                inside = not inside
            j = i
        return inside

    def locate(lng, lat):
        for fips, name, boxed in polys:
            for ring, minx, miny, maxx, maxy in boxed:
                if minx <= lng <= maxx and miny <= lat <= maxy and _in_ring(lng, lat, ring):
                    return fips, name
        # Fallback for points that fall just outside a county polygon (coastal /
        # island courses whose centroid lands over water): snap to the nearest
        # county boundary vertex, but only within ~0.3° so we never assign a
        # genuinely out-of-state point to a Michigan county.
        best = None
        for fips, name, boxed in polys:
            for ring, minx, miny, maxx, maxy in boxed:
                if lng < minx - 0.4 or lng > maxx + 0.4 or lat < miny - 0.4 or lat > maxy + 0.4:
                    continue
                for vx, vy in ring:
                    d = (vx - lng) ** 2 + (vy - lat) ** 2
                    if best is None or d < best[0]:
                        best = (d, fips, name)
        if best and best[0] <= 0.09:                 # (~0.3°)^2
            return best[1], best[2]
        return None, None

    return locate


# ---------- searchable places (Census TIGER gazetteer) ----------
#
# Cities, villages, townships, CDPs and ZIP areas for the search box. The
# gazetteer files are tiny, stable, pipe-delimited text tables; we cache them and
# parse with the stdlib (no shapefile/geopandas dependency). Type is read from the
# name suffix ("Oscoda charter township" -> township). Township parent county is
# EXACT (embedded in the 10-digit cousub GEOID); places and ZIP areas are located
# by point-in-polygon of their internal point against the county boundaries.

# Name suffix -> our `kind`. Order matters: "charter township" before "township".
_GAZ_SUFFIX_KIND = [
    ("charter township", "township"),
    ("township", "township"),
    ("city", "city"),
    ("village", "village"),
    ("CDP", "cdp"),
]


def _gaz_split_name(name: str) -> tuple[str, str | None]:
    """'Oscoda charter township' -> ('Oscoda', 'township'). Unknown suffix -> (name, None)."""
    for suffix, kind in _GAZ_SUFFIX_KIND:
        if name.endswith(" " + suffix):
            return name[: -(len(suffix) + 1)].strip(), kind
    return name.strip(), None


def _parse_gaz(text: str):
    """Yield dict rows from a pipe-delimited Census gazetteer table (header row 1)."""
    lines = text.splitlines()
    if not lines:
        return
    header = [h.strip() for h in lines[0].split("|")]
    for ln in lines[1:]:
        parts = ln.split("|")
        if len(parts) != len(header):
            continue
        yield {h: v.strip() for h, v in zip(header, parts)}


def _gaz_bbox(lat: float, lng: float, aland_m2: float, pad: float = 1.35):
    """Approximate (min_lat, min_lng, max_lat, max_lng) from a centroid + land
    area, treating the footprint as an equal-area circle. Used ONLY to frame a
    zoom-to-place — never for analysis, so the circle approximation is fine."""
    r = math.sqrt(max(aland_m2, 1.0) / math.pi) * pad          # metres
    dlat = r / 111_320.0
    dlng = r / (111_320.0 * max(math.cos(math.radians(lat)), 0.2))
    return (lat - dlat, lng - dlng, lat + dlat, lng + dlng)


def _gaz_cache(url: str) -> Path:
    """Download a gazetteer file into the cache (once) and return its path."""
    CENSUS_GAZ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CENSUS_GAZ_CACHE_DIR / url.rsplit("/", 1)[-1]
    if _need_download(path, 1000, force=FORCE_REFRESH):
        size = download_to(url, path, timeout=180)
        log(f"  fetched {size/1024:.0f} KB -> {path.name}", level="ok")
    return path


def load_places(conn: sqlite3.Connection) -> int:
    """Load searchable Michigan places from the US Census TIGER gazetteer:
    incorporated cities & villages and CDPs (place file), townships (county-
    subdivision file), and ZIP-code areas (national ZCTA file, filtered to MI).

    Every row keeps a `kind` and parent county so the search UI can disambiguate
    Michigan's duplicate names (Oscoda County vs Oscoda Township in Iosco). The
    centroid is the Census internal point; the bbox is derived from land area for
    zoom-to-place. Townships get their exact county from the cousub GEOID; places
    and ZIP areas are located by point-in-polygon against the county boundaries.
    """
    log("Loading Census TIGER gazetteer places (cities/villages/townships/CDPs/ZIPs)...")
    conn.execute("DELETE FROM places")
    locate = _build_county_locator()
    name_by_fips = {r["fips"]: r["name"]
                    for r in conn.execute("SELECT fips, name FROM counties")}

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def resolve_counties(lat, lng, aland):
        """(primary_fips, primary_name, counties_json|None) for a place/ZIP by
        point-in-polygon. Samples 8 compass points at the equal-area radius so a
        place that genuinely spans counties lists them all; a compact place stays
        single-county. The internal point's county is always the primary."""
        pf, pn = locate(lng, lat)
        found: dict[str, str] = {}
        if pf:
            found[pf] = pn
        r = math.sqrt(max(aland, 1.0) / math.pi)               # metres (unpadded)
        for ang in range(0, 360, 45):
            dlat = (r * math.cos(math.radians(ang))) / 111_320.0
            dlng = (r * math.sin(math.radians(ang))) / (
                111_320.0 * max(math.cos(math.radians(lat)), 0.2))
            f, n = locate(lng + dlng, lat + dlat)
            if f:
                found.setdefault(f, n)
        if not pf and found:
            pf, pn = next(iter(found.items()))
        names = sorted({n for n in found.values() if n})
        counties_json = json.dumps(names) if len(names) > 1 else None
        return pf, pn, counties_json

    rows: list[tuple] = []
    n_place = n_twp = n_zip = 0

    def add(place_id, name, name_full, kind, cfips, cname, counties, lat, lng, aland):
        bb = _gaz_bbox(lat, lng, aland)
        rows.append((place_id, name, name_full, kind, cfips, cname, counties,
                     lat, lng, bb[0], bb[1], bb[2], bb[3],
                     round(aland / 2_589_988.11, 3) if aland else None))

    # --- places: cities / villages / CDPs ---
    try:
        text = _gaz_cache(CENSUS_GAZ_PLACE_URL).read_text(encoding="latin-1")
        for row in _parse_gaz(text):
            lat, lng, aland = _num(row.get("INTPTLAT")), _num(row.get("INTPTLONG")), _num(row.get("ALAND")) or 0.0
            if lat is None or lng is None:
                continue
            disp, kind = _gaz_split_name(row.get("NAME", ""))
            if kind not in ("city", "village", "cdp"):
                continue
            cfips, cname, counties = resolve_counties(lat, lng, aland)
            add(f"place:{row.get('GEOID')}", disp, row.get("NAME"), kind,
                cfips, cname, counties, lat, lng, aland)
            n_place += 1
    except Exception as e:                                       # noqa: BLE001
        log(f"  place file failed: {e}", level="warn")

    # --- county subdivisions: townships (exact county from GEOID) ---
    try:
        text = _gaz_cache(CENSUS_GAZ_COUSUB_URL).read_text(encoding="latin-1")
        for row in _parse_gaz(text):
            disp, kind = _gaz_split_name(row.get("NAME", ""))
            if kind != "township":                              # cities here duplicate the place file
                continue
            lat, lng, aland = _num(row.get("INTPTLAT")), _num(row.get("INTPTLONG")), _num(row.get("ALAND")) or 0.0
            if lat is None or lng is None:
                continue
            geoid = row.get("GEOID", "")
            cfips = geoid[:5] if len(geoid) >= 5 else None       # state(2)+county(3)
            cname = name_by_fips.get(cfips)
            add(f"cousub:{geoid}", disp, row.get("NAME"), kind,
                cfips, cname, None, lat, lng, aland)
            n_twp += 1
    except Exception as e:                                       # noqa: BLE001
        log(f"  cousub file failed: {e}", level="warn")

    # --- ZCTAs: ZIP areas (national file, filter to MI by prefix + county) ---
    try:
        zpath = _gaz_cache(CENSUS_GAZ_ZCTA_URL)
        with zipfile.ZipFile(zpath) as zf:
            member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
            text = zf.read(member).decode("latin-1")
        for row in _parse_gaz(text):
            zcta = row.get("GEOID", "")
            if zcta[:2] not in ("48", "49"):                    # Michigan ZIP prefixes
                continue
            lat, lng, aland = _num(row.get("INTPTLAT")), _num(row.get("INTPTLONG")), _num(row.get("ALAND")) or 0.0
            if lat is None or lng is None:
                continue
            cfips, cname, counties = resolve_counties(lat, lng, aland)
            if not cfips:                                        # centroid not in any MI county — skip
                continue
            add(f"zcta:{zcta}", zcta, f"ZIP {zcta}", "zcta",
                cfips, cname, counties, lat, lng, aland)
            n_zip += 1
    except Exception as e:                                       # noqa: BLE001
        log(f"  ZCTA file failed: {e}", level="warn")

    conn.executemany(
        """INSERT OR REPLACE INTO places(
             place_id, name, name_full, kind, county_fips, county_name, counties,
             lat, lng, min_lat, min_lng, max_lat, max_lng, area_sq_mi)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()

    total = len(rows)
    status = "ok" if total else "unavailable"
    record_source(
        conn, "census_gazetteer",
        "US Census TIGER Gazetteer — places, townships & ZIP areas (Michigan)",
        CENSUS_GAZ_BASE, status, total,
        f"{n_place} cities/villages/CDPs, {n_twp} townships, {n_zip} ZIP areas "
        f"({CENSUS_GAZ_YEAR} gazetteer, state FIPS 26). Powers the search box's "
        f"place/township/ZIP lookup and disambiguation.",
        coverage_start=str(CENSUS_GAZ_YEAR), coverage_end=str(CENSUS_GAZ_YEAR),
    )
    log(f"  places loaded: {n_place} places + {n_twp} townships + {n_zip} ZIPs "
        f"= {total}", level="ok")
    return total


def overpass_fetch(query: str, *, timeout: int = 180) -> dict:
    """POST an Overpass QL query, trying each mirror in turn. Raises if all fail."""
    data = query.encode("utf-8")
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint, data=data,
                headers={"User-Agent": USER_AGENT,
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:                       # noqa: BLE001
            last_err = e
            log(f"  Overpass endpoint failed ({endpoint}): {e}", level="warn")
    raise RuntimeError(f"all Overpass endpoints failed: {last_err}")


def _golf_county_ag_context(conn: sqlite3.Connection):
    """Rank Michigan counties by latest-year agricultural pesticide use (EPest).

    Returns (rank_by_fips, total_lbs_by_fips, high_use_fips_set). 'High use' =
    top quartile of counties by total applied. Context only — golf courses are
    NOT in these agricultural totals (that's the whole point of the layer)."""
    yr = conn.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]
    rank_by_fips, total_by_fips, high = {}, {}, set()
    if yr is None:
        return rank_by_fips, total_by_fips, high
    rows = conn.execute(
        "SELECT county_fips, SUM((epest_low_kg + epest_high_kg)/2.0) AS kg "
        "FROM pesticide_use WHERE year = ? GROUP BY county_fips "
        "HAVING kg > 0 ORDER BY kg DESC", (yr,)).fetchall()
    for i, r in enumerate(rows):
        rank_by_fips[r["county_fips"]] = i + 1
        total_by_fips[r["county_fips"]] = r["kg"] * golf_data.LBS_PER_KG
    cutoff = max(1, len(rows) // 4)
    high = {r["county_fips"] for r in rows[:cutoff]}
    return rank_by_fips, total_by_fips, high


def _golf_water_sites(conn: sqlite3.Connection):
    """Water-monitoring sites with >=1 detection of a turf-associated compound,
    for a nearby-monitoring cross-reference. CONTEXT ONLY — never attributed to a
    course. Returns [ {site_id, name, lat, lng, compounds:[...]} ]."""
    placeholders = ",".join("?" * len(golf_data.TURF_WATER_COMPOUNDS))
    rows = conn.execute(
        f"""SELECT s.site_id, s.site_name, s.latitude AS lat, s.longitude AS lng,
                   r.compound AS compound
              FROM water_quality_results r
              JOIN water_quality_sites s ON s.site_id = r.site_id
             WHERE r.detected = 1
               AND UPPER(r.compound) IN ({placeholders})
               AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL""",
        tuple(sorted(golf_data.TURF_WATER_COMPOUNDS))).fetchall()
    by_site: dict = {}
    for r in rows:
        d = by_site.setdefault(r["site_id"], {
            "site_id": r["site_id"], "name": r["site_name"],
            "lat": r["lat"], "lng": r["lng"], "compounds": set()})
        d["compounds"].add((r["compound"] or "").title())
    for d in by_site.values():
        d["compounds"] = sorted(d["compounds"])
    return list(by_site.values())


def load_golf_courses(conn: sqlite3.Connection) -> int:
    """Load Michigan golf-course LOCATIONS from OpenStreetMap (Overpass), derive
    county + acreage + footprint geometry, and attach context-only cross-refs
    (county ag-use rank, nearest turf-compound water detection). No pesticide
    amounts are loaded or estimated — Michigan publishes none for golf courses."""
    log("Loading golf courses (OpenStreetMap via Overpass)...")
    cur = conn.cursor()

    try:
        payload = overpass_fetch(OVERPASS_GOLF_QUERY)
    except Exception as e:                           # noqa: BLE001
        log(f"  Overpass fetch failed: {e}", level="warn")
        record_source(
            conn, "osm_golf", "OpenStreetMap — Michigan golf courses (Overpass API)",
            "https://www.openstreetmap.org/copyright", "unavailable", 0,
            "Overpass fetch failed on this run; keeping any previously loaded data.")
        return 0

    locate = _build_county_locator()
    rank_by_fips, total_by_fips, high_use = _golf_county_ag_context(conn)
    water_sites = _golf_water_sites(conn)
    WATER_MAX_KM = 8.0

    courses: dict[str, dict] = {}
    for el in payload.get("elements", []):
        osm_type = el.get("type")
        if osm_type not in ("way", "relation"):
            continue
        tags = el.get("tags", {}) or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue                                 # unnamed features: skip (can't identify)
        geojson, rings = golf_data.geometry_geojson(osm_type, el)
        if rings:
            acres, clng, clat = golf_data.polygon_metrics(rings)
        else:
            # point-only fallback: use element center if present
            c = el.get("center") or {}
            clat, clng = c.get("lat"), c.get("lon")
            acres = None
        if clat is None or clng is None:
            continue
        # keep only points that land inside Michigan (defensive; query is bounded)
        fips, county = locate(clng, clat)

        oc, oc_label = golf_data.classify_ownership(tags)
        addr_parts = [tags.get("addr:housenumber"), tags.get("addr:street")]
        address = " ".join(p for p in addr_parts if p) or None

        rec = {
            "course_key": f"osm:{osm_type}/{el.get('id')}",
            "osm_type": osm_type, "osm_id": el.get("id"),
            "name": name,
            "operator": (tags.get("operator") or tags.get("owner") or "").strip() or None,
            "ownership_class": oc, "ownership_label": oc_label,
            "access": (tags.get("access") or "").strip() or None,
            "address": address,
            "city": (tags.get("addr:city") or "").strip().title() or None,
            "zip": (tags.get("addr:postcode") or "").strip() or None,
            "county": county, "county_fips": fips,
            "latitude": clat, "longitude": clng,
            "acres": round(acres, 1) if acres else None,
            "has_polygon": 1 if rings else 0,
            "geometry": json.dumps(geojson) if geojson else None,
            "website": (tags.get("website") or tags.get("contact:website")
                        or "").strip() or None,
            "high_ag_use": 1 if fips in high_use else 0,
            "county_ag_rank": rank_by_fips.get(fips),
            "county_ag_total_lbs": round(total_by_fips[fips]) if fips in total_by_fips else None,
        }
        # nearest turf-compound water-monitoring site within WATER_MAX_KM
        best = None
        for ws in water_sites:
            if abs(ws["lat"] - clat) > 0.12 or abs(ws["lng"] - clng) > 0.16:
                continue                             # ~13 km bbox pre-filter
            km = golf_data.haversine_km(clat, clng, ws["lat"], ws["lng"])
            if km <= WATER_MAX_KM and (best is None or km < best[0]):
                best = (km, ws)
        if best:
            km, ws = best
            rec["water_site_id"] = ws["site_id"]
            rec["water_site_name"] = ws["name"]
            rec["water_site_km"] = round(km, 1)
            rec["water_compounds"] = json.dumps(ws["compounds"][:8])
        courses[rec["course_key"]] = rec

    # light dedupe: same normalized name within ~500 m (a relation + a stray
    # member way, or a duplicated import). Keep the one with a polygon / more acres.
    def _nkey(r):
        return re.sub(r"[^a-z0-9]", "", (r["name"] or "").lower())
    kept: list[dict] = []
    for r in sorted(courses.values(),
                    key=lambda x: (x["has_polygon"], x["acres"] or 0), reverse=True):
        dup = False
        for k in kept:
            if _nkey(k) == _nkey(r) and golf_data.haversine_km(
                    r["latitude"], r["longitude"], k["latitude"], k["longitude"]) < 0.5:
                dup = True
                break
        if not dup:
            kept.append(r)

    cur.execute("DELETE FROM golf_courses")
    for r in kept:
        cur.execute(
            """INSERT OR REPLACE INTO golf_courses(
                 course_key, osm_type, osm_id, name, operator, ownership_class,
                 ownership_label, access, address, city, zip, county, county_fips,
                 latitude, longitude, acres, has_polygon, geometry, website,
                 high_ag_use, county_ag_rank, county_ag_total_lbs,
                 water_site_id, water_site_name, water_site_km, water_compounds,
                 source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["course_key"], r["osm_type"], r["osm_id"], r["name"], r.get("operator"),
             r["ownership_class"], r["ownership_label"], r.get("access"),
             r.get("address"), r.get("city"), r.get("zip"), r.get("county"),
             r.get("county_fips"), r["latitude"], r["longitude"], r.get("acres"),
             r["has_polygon"], r.get("geometry"), r.get("website"),
             r.get("high_ag_use", 0), r.get("county_ag_rank"),
             r.get("county_ag_total_lbs"), r.get("water_site_id"),
             r.get("water_site_name"), r.get("water_site_km"),
             r.get("water_compounds"), "OSM"),
        )
    conn.commit()

    total = len(kept)
    polys = sum(1 for r in kept if r["has_polygon"])
    muni = sum(1 for r in kept if r["ownership_class"] == "municipal")
    water_links = sum(1 for r in kept if r.get("water_site_id"))
    log(f"  golf courses: {total} ({polys} with footprint polygons, {muni} public/"
        f"municipal, {water_links} near turf-compound water detections)",
        level="ok" if total else "warn")
    record_source(
        conn, "osm_golf",
        "OpenStreetMap — Michigan golf courses (Overpass API)",
        "https://www.openstreetmap.org/copyright",
        "ok" if total else "unavailable", total,
        f"{total} Michigan golf courses from OpenStreetMap (leisure=golf_course) "
        f"via the Overpass API, {polys} with footprint polygons. Crowd-sourced — "
        f"coverage may be incomplete or out of date. LOCATIONS ONLY: no pesticide-"
        f"use amounts (Michigan publishes none for golf courses). © OpenStreetMap "
        f"contributors, ODbL.",
    )
    # Turf-management BMP references cited in the popup content (context sources).
    for sid, src in (
        ("gcsaa_bmp", golf_data.SOURCES[1]),
        ("msu_turf", golf_data.SOURCES[2]),
        ("ny_ag_toxic_fairways", golf_data.SOURCES[3]),
    ):
        record_source(conn, sid, src["title"], src["url"], "reference", 0, src["note"])
    return total


# ---------- PFAS (Michigan PFAS Action Response Team / EGLE, live) ----------
#
# Five live MPART feeds -> one pfas_features table (kind-discriminated). Sampling
# results are aggregated to their location; Public Water Supply results stay as
# hexbin polygons (never pinpointed). No site/concentration is ever fabricated.

def _arcgis_all(url: str, out_fields: str = "*", *, where: str = "1=1",
                geometry: bool = False, page: int = 2000, cap: int = 200000,
                max_offset: float | None = None) -> list:
    """Fetch ALL features from an ArcGIS FeatureServer/MapServer layer, paging via
    resultOffset (ordered by OBJECTID for stability). Returns raw feature dicts.

    max_offset (in outSR units — degrees for 4326) asks the server to GENERALIZE
    geometry, which both shrinks the transfer and gives us display-ready polygons
    without any client-side simplification."""
    out, offset = [], 0
    while True:
        base = {
            "where": where, "outFields": out_fields,
            "returnGeometry": "true" if geometry else "false", "outSR": "4326",
            "orderByFields": "OBJECTID", "resultOffset": offset,
            "resultRecordCount": page, "f": "json"}
        if geometry and max_offset:
            base["maxAllowableOffset"] = max_offset
        params = urllib.parse.urlencode(base)
        try:
            d = json.loads(http_get(f"{url}/query?{params}", timeout=120))
        except Exception:                    # noqa: BLE001 — retry once without ordering
            base.pop("orderByFields", None)
            params = urllib.parse.urlencode(base)
            d = json.loads(http_get(f"{url}/query?{params}", timeout=120))
        feats = d.get("features", [])
        out.extend(feats)
        if len(feats) < page or len(out) >= cap or not d.get("exceededTransferLimit", len(feats) == page):
            if len(feats) < page:
                break
        if len(feats) < page or len(out) >= cap:
            break
        offset += page
    return out


# Key PFAS analytes we summarise for surface water (value column, ppt/ng-L).
_SW_ANALYTES = [
    ("CAS1763231_PFOS", "PFOS"), ("CAS335671_PFOA", "PFOA"),
    ("CAS355464_PFHxS", "PFHxS"), ("CAS375951_PFNA", "PFNA"),
    ("CAS375735_PFBS", "PFBS"), ("CAS307244_PFHxA", "PFHxA"),
    ("CAS13252136_GenX", "GenX"),
]


def _poly_centroid(rings):
    """Rough area-weighted centroid of an ArcGIS polygon's rings ([[[x,y],...]])."""
    xs, ys, n = 0.0, 0.0, 0
    for ring in rings or []:
        for x, y in ring:
            xs += x; ys += y; n += 1
    return (xs / n, ys / n) if n else (None, None)


def _arcgis_rings_to_geojson(rings: list) -> dict | None:
    """Convert an ArcGIS polygon (list of rings) to a GeoJSON geometry.

    ArcGIS uses clockwise rings for outer boundaries and counter-clockwise for
    holes (opposite of GeoJSON, but Leaflet renders either winding). We classify
    each ring by its signed area so islands become separate polygons instead of
    being mistaken for holes — important for the handful of Great-Lakes tracts."""
    if not rings:
        return None

    def signed_area(ring):
        s = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[i + 1][0], ring[i + 1][1]
            s += x1 * y2 - x2 * y1
        return s / 2.0

    outers, holes = [], []
    for r in rings:
        if len(r) < 4:
            continue
        (outers if signed_area(r) < 0 else holes).append(r)
    if not outers:                       # fall back: treat everything as outer
        outers = [r for r in rings if len(r) >= 4]
        holes = []
    if len(outers) == 1:
        return {"type": "Polygon", "coordinates": [outers[0]] + holes}
    # Multiple outer rings -> MultiPolygon; attach each hole to the first outer
    # that contains its first vertex (cheap point-in-ring test).
    def in_ring(pt, ring):
        x, y, inside = pt[0], pt[1], False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    polys = [[o] for o in outers]
    for h in holes:
        for poly in polys:
            if in_ring(h[0], poly[0]):
                poly.append(h)
                break
    return {"type": "MultiPolygon", "coordinates": polys}


def load_airtoxics(conn: sqlite3.Connection) -> int:
    """Load EPA air toxics (NATA / AirToxScreen) cancer-risk SCREENING estimates
    for Michigan census tracts from EPA's ArcGIS ATS_Risk_View layer.

    Per tract we store the total cancer risk (in a million) — computed as the SUM
    of the eight source-category fields, which equals the sum of the per-pollutant
    fields and is far more granular/reliable than the service's coarse total
    column — plus the source-category breakdown and the top contributing pollutants
    (for the popup's driver analysis and clickable chemical links)."""
    log("Loading EPA air toxics risk (NATA/AirToxScreen, Michigan census tracts)...")
    cur = conn.cursor()

    # 1. Field metadata -> discover the per-pollutant columns + their nice aliases.
    meta = json.loads(http_get(f"{AIRTOXICS_RISK_URL}?f=json", timeout=60))
    alias_by_field = {f["name"]: f.get("alias") for f in meta.get("fields", [])}
    poll_fields = [f for f in alias_by_field if airtoxics_data.is_pollutant_field(f)]
    src_fields = airtoxics_data.SOURCE_FIELDS
    out_fields = ",".join(["FIPS", "STCOFIPS", "County_Nam", "POP2010"]
                          + src_fields + poll_fields)

    # 2. Page all Michigan tracts with geometry.
    # maxAllowableOffset ~0.0015° (~130 m) generalizes tract boundaries server-side
    # — plenty for a statewide/county choropleth and it cuts the geometry payload
    # roughly 4x versus full-resolution rings.
    feats = _arcgis_all(AIRTOXICS_RISK_URL, out_fields, where="State='MI'",
                        geometry=True, page=1000, max_offset=0.0015)
    log(f"  fetched {len(feats)} Michigan tract features")

    rows, mi_total_sum, kept = [], 0.0, 0
    for ft in feats:
        a = ft.get("attributes") or {}
        geoid = a.get("FIPS")
        g = ft.get("geometry") or {}
        geom = _arcgis_rings_to_geojson(g.get("rings"))
        if not geoid or not geom:
            continue
        sources = {}
        for field in src_fields:
            v = a.get(field)
            sources[airtoxics_data.SOURCE_KEY_BY_FIELD[field]] = round(v, 3) if v else 0.0
        total = round(sum(sources.values()), 2)
        polls = []
        for field in poll_fields:
            v = a.get(field)
            if v and v > 0:
                polls.append([airtoxics_data.clean_pollutant_name(field, alias_by_field.get(field)),
                              round(v, 3)])
        polls.sort(key=lambda p: p[1], reverse=True)
        polls = polls[:6]
        geom = pfas_data.round_geometry(geom)          # 5-dp coords, smaller payload
        county_fips = a.get("STCOFIPS")
        cty = (a.get("County_Nam") or "").replace(" County", "").strip() or None
        rows.append({
            "tract_geoid": str(geoid), "county_fips": county_fips, "county_name": cty,
            "population": int(a["POP2010"]) if a.get("POP2010") is not None else None,
            "total_risk": total, "sources": json.dumps(sources),
            "pollutants": json.dumps(polls), "geometry": json.dumps(geom),
        })
        mi_total_sum += total
        kept += 1

    if kept < 200:
        log(f"  only {kept} tracts parsed — leaving air toxics unchanged", level="warn")
        airtoxics_data_record(conn, "skipped", 0)
        return 0

    cur.execute("DELETE FROM airtoxics_tracts")
    cur.executemany(
        "INSERT OR REPLACE INTO airtoxics_tracts"
        "(tract_geoid, county_fips, county_name, population, total_risk,"
        " sources, pollutants, geometry) VALUES"
        "(:tract_geoid, :county_fips, :county_name, :population, :total_risk,"
        " :sources, :pollutants, :geometry)", rows)

    # 3. Reference averages: national unweighted tract mean (sum of the per-source
    #    field averages over ALL US tracts) and the Michigan tract mean. Both are
    #    simple tract means so they are directly comparable in the popup.
    national_avg = None
    try:
        stat_defs = [{"statisticType": "avg", "onStatisticField": f,
                      "outStatisticFieldName": f"a{i}"} for i, f in enumerate(src_fields)]
        q = urllib.parse.urlencode({"where": "1=1", "f": "json",
                                    "outStatistics": json.dumps(stat_defs)})
        sd = json.loads(http_get(f"{AIRTOXICS_RISK_URL}/query?{q}", timeout=90))
        at = (sd.get("features") or [{}])[0].get("attributes", {})
        national_avg = round(sum((at.get(f"a{i}") or 0) for i in range(len(src_fields))), 2)
    except Exception as e:                     # noqa: BLE001 — reference number is optional
        log(f"  national-average query failed ({e}); leaving null", level="warn")
    mi_avg = round(mi_total_sum / kept, 2) if kept else None

    cur.execute("DELETE FROM airtoxics_stats")
    cur.executemany("INSERT OR REPLACE INTO airtoxics_stats(key, value) VALUES (?, ?)",
                    [("national_avg", national_avg), ("mi_avg", mi_avg)])

    airtoxics_data_record(conn, "ok", kept)
    conn.commit()
    log(f"  loaded {kept} MI tracts · MI avg {mi_avg} / national {national_avg} in-a-million",
        level="ok")
    return kept


def airtoxics_data_record(conn: sqlite3.Connection, status: str, rows: int) -> None:
    record_source(
        conn, "epa_airtoxics",
        "EPA air toxics risk (NATA / AirToxScreen) — census-tract cancer-risk screening",
        AIRTOXICS_HOME_URL, status, rows,
        "Modeled cancer-risk SCREENING estimates (chance-in-a-million, 70-yr outdoor "
        "lifetime) at census-tract level, with source-category and pollutant "
        "breakdown. EPA releases new assessments every year or two and cautions "
        "against comparing across years (methods change), so only one assessment "
        "year is shown and it is not trended. Not a measurement; identifies areas "
        "for further study, not risk at a specific address.")


def load_pfas(conn: sqlite3.Connection) -> int:
    """Load Michigan PFAS features from the five live MPART/EGLE feeds, cross-link
    Sites/AOIs to the app's Superfund/TRI/landfill records, and insert them."""
    log("Loading PFAS features (Michigan MPART / EGLE, live)...")
    cur = conn.cursor()

    def _ckey(name):
        return (name or "").replace(".", "").replace(" county", "", 1).strip().lower()
    fips_by_lname = {_ckey(name): fips for fips, name in _county_fips_list(conn)}
    locate = _build_county_locator()

    def county_of(county_name, lat, lng):
        """Prefer the feed's county name; fall back to point-in-polygon."""
        fips = fips_by_lname.get(_ckey(county_name)) if county_name else None
        name = pfas_data.title_county(county_name)
        if not fips and lat is not None and lng is not None:
            fips, nm = locate(lng, lat)
            name = name or nm
        return name, fips

    # cross-link indexes (Sites/AOIs only)
    tri_by_fips, contam_by_fips = _build_crosslink_index(conn)
    landfill_by_fips: dict[str, list] = {}
    for r in conn.execute("SELECT site_key, name, operator, latitude, longitude, "
                          "county_fips FROM landfill_sites WHERE county_fips IS NOT NULL"):
        landfill_by_fips.setdefault(r["county_fips"], []).append(dict(r))

    rows: list[dict] = []
    counts = {}

    # ---- 1. Sites & Areas of Interest (flagship) ----
    try:
        for f in _arcgis_all(PFAS_SITES_URL):
            a = f.get("attributes", {})
            lat, lng = _to_float(a.get("Latitude")), _to_float(a.get("Longitude"))
            if lat is None or lng is None:
                continue
            is_aoi = (a.get("SiteOrAoi") or "").strip().lower().startswith("area")
            cname, fips = county_of(a.get("County"), lat, lng)
            rows.append({
                "feature_key": f"{'aoi' if is_aoi else 'site'}:{a.get('GlobalID') or a.get('OBJECTID')}",
                "kind": "aoi" if is_aoi else "site",
                "name": (a.get("Name") or "PFAS site").strip(),
                "site_type": (a.get("Type") or "").strip() or None,
                "address": (a.get("Address") or "").strip() or None,
                "city": (a.get("City") or "").strip().title() or None,
                "zip": str(a.get("ZipCode")).strip() if a.get("ZipCode") else None,
                "county": cname, "county_fips": fips, "latitude": lat, "longitude": lng,
                "residential_wells": (a.get("ResidentialWellsSampled") or "").strip() or None,
                "hyperlink": (a.get("WebpageSite") or "").strip() or None,
                "site_lead": (a.get("SiteLead") or "").strip() or None,
                "site_lead_email": (a.get("SiteLeadEmail") or "").strip() or None,
                "site_lead_phone": (a.get("SiteLeadPhone") or "").strip() or None,
                "summary": None,
                "props": {"site_or_aoi": a.get("SiteOrAoi"),
                          "additional_files": (a.get("WebpageAdditionalFiles") or "").strip() or None},
            })
        counts["sites_aois"] = sum(1 for r in rows if r["kind"] in ("site", "aoi"))
        log(f"  PFAS sites/AOIs: {counts['sites_aois']}", level="ok")
    except Exception as e:                   # noqa: BLE001
        log(f"  PFAS sites fetch failed: {e}", level="warn")

    # ---- 2. Surface water sampling (aggregate to location, max PFOS+PFOA) ----
    try:
        of = ",".join(["SiteCode", "CocSampleId", "CollectionDate", "Unit", "Waterbody",
                       "Longitude", "Latitude"]
                      + [c for c, _ in _SW_ANALYTES] + [c + "Flag" for c, _ in _SW_ANALYTES])
        best: dict = {}
        for f in _arcgis_all(PFAS_SURFACE_WATER_URL, of):
            a = f.get("attributes", {})
            lat, lng = _to_float(a.get("Latitude")), _to_float(a.get("Longitude"))
            if lat is None or lng is None:
                continue
            detected = {}
            for col, nm in _SW_ANALYTES:
                v, det = pfas_data.parse_ppt(a.get(col))
                flag = (a.get(col + "Flag") or "").strip().upper()
                if det and flag not in ("U", "ND"):
                    detected[nm] = v
            score = (detected.get("PFOS", 0) or 0) + (detected.get("PFOA", 0) or 0)
            key = a.get("SiteCode") or f"{lat:.5f},{lng:.5f}"
            prev = best.get(key)
            if prev is None or score > prev["_score"]:
                best[key] = {
                    "_score": score, "name": (a.get("CocSampleId") or a.get("SiteCode")
                                              or "Surface-water sample"),
                    "waterbody": a.get("Waterbody"), "unit": a.get("Unit") or "ng/L",
                    "date": pfas_data.epoch_to_iso(a.get("CollectionDate")),
                    "lat": lat, "lng": lng, "detected": detected,
                    "site_code": a.get("SiteCode")}
        for key, b in best.items():
            cname, fips = county_of(None, b["lat"], b["lng"])
            total = round(sum(b["detected"].values()), 1) if b["detected"] else None
            rows.append({
                "feature_key": f"sw:{key}", "kind": "surface_water",
                "name": str(b["name"]).strip(), "site_type": b["waterbody"],
                "county": cname, "county_fips": fips, "latitude": b["lat"], "longitude": b["lng"],
                "max_ppt": max(b["detected"].values()) if b["detected"] else None,
                "sample_date": b["date"],
                "summary": None,
                "props": {"waterbody": b["waterbody"], "unit": b["unit"],
                          "detected": {k: round(v, 1) for k, v in b["detected"].items()},
                          "total_key_pfas": total}})
        counts["surface_water"] = len(best)
        log(f"  PFAS surface-water locations: {len(best)}", level="ok")
    except Exception as e:                   # noqa: BLE001
        log(f"  PFAS surface-water fetch failed: {e}", level="warn")

    # ---- 3. Public Water Supply — hexbins + results (aggregate by HexID) ----
    try:
        agg: dict = {}
        for f in _arcgis_all(PFAS_PWS_RESULTS_URL,
                             "HexID,WSSN,SystemName,SampleDate,PFOS,PFOA"):
            a = f.get("attributes", {})
            hid = a.get("HexID")
            if hid is None:
                continue
            d = agg.setdefault(hid, {"systems": set(), "samples": 0, "detections": 0,
                                     "max_pfos": None, "max_pfoa": None, "latest": None})
            d["systems"].add(a.get("WSSN"))
            d["samples"] += 1
            pfos, dets = pfas_data.parse_ppt(a.get("PFOS"))
            pfoa, deta = pfas_data.parse_ppt(a.get("PFOA"))
            if dets or deta:
                d["detections"] += 1
            if pfos is not None:
                d["max_pfos"] = max(d["max_pfos"] or 0, pfos)
            if pfoa is not None:
                d["max_pfoa"] = max(d["max_pfoa"] or 0, pfoa)
            iso = pfas_data.epoch_to_iso(a.get("SampleDate"))
            if iso and (d["latest"] is None or iso > d["latest"]):
                d["latest"] = iso
        pws_n = 0
        for f in _arcgis_all(PFAS_PWS_HEXBIN_URL, "HexID", geometry=True):
            a = f.get("attributes", {})
            hid = a.get("HexID")
            g = f.get("geometry") or {}
            rings = g.get("rings")
            if hid not in agg or not rings:
                continue                     # only hexbins that actually have results
            clng, clat = _poly_centroid(rings)
            if clat is None:
                continue
            d = agg[hid]
            cname, fips = county_of(None, clat, clng)
            rows.append({
                "feature_key": f"pws:{hid}", "kind": "pws",
                "name": f"Public water supply area (hex {hid})",
                "county": cname, "county_fips": fips, "latitude": clat, "longitude": clng,
                "geometry": json.dumps({"type": "Polygon", "coordinates": rings}),
                "max_ppt": max(d["max_pfos"] or 0, d["max_pfoa"] or 0) or None,
                "sample_date": d["latest"], "summary": None,
                "props": {"systems": len([s for s in d["systems"] if s is not None]),
                          "samples": d["samples"], "detections": d["detections"],
                          "max_pfos": d["max_pfos"], "max_pfoa": d["max_pfoa"]}})
            pws_n += 1
        counts["pws"] = pws_n
        log(f"  PFAS public-water hexbins with results: {pws_n}", level="ok")
    except Exception as e:                   # noqa: BLE001
        log(f"  PFAS public-water fetch failed: {e}", level="warn")

    # ---- 4. Fish contaminant monitoring (sites + data aggregated by StationID) ----
    try:
        fagg: dict = {}
        for f in _arcgis_all(PFAS_FISH_DATA_URL,
                             "StationID,WaterBody,Species,CollectionDate,PFOSppb,PFOScode"):
            a = f.get("attributes", {})
            sid = a.get("StationID")
            if sid is None:
                continue
            d = fagg.setdefault(sid, {"species": set(), "samples": 0,
                                      "max_pfos_ppb": None, "latest": None})
            d["samples"] += 1
            if a.get("Species"):
                d["species"].add(a.get("Species"))
            pfos = _to_float(a.get("PFOSppb"))
            code = (a.get("PFOScode") or "").strip().upper()
            if pfos is not None and code not in ("U", "ND", "NA"):
                d["max_pfos_ppb"] = max(d["max_pfos_ppb"] or 0, pfos)
            iso = pfas_data.epoch_to_iso(a.get("CollectionDate"))
            if iso and (d["latest"] is None or iso > d["latest"]):
                d["latest"] = iso
        fish_n = 0
        for f in _arcgis_all(PFAS_FISH_SITES_URL,
                             "StationID,WaterBody,CountyName,SamplingLocation,Lat,Long"):
            a = f.get("attributes", {})
            sid = a.get("StationID")
            lat, lng = _to_float(a.get("Lat")), _to_float(a.get("Long"))
            if lat is None or lng is None:
                continue
            d = fagg.get(sid)
            cname, fips = county_of(a.get("CountyName"), lat, lng)
            rows.append({
                "feature_key": f"fish:{sid}", "kind": "fish",
                "name": (a.get("WaterBody") or "Fish sampling site").strip(),
                "site_type": (a.get("SamplingLocation") or "").strip() or None,
                "county": cname, "county_fips": fips, "latitude": lat, "longitude": lng,
                "hyperlink": MDHHS_EAT_SAFE_FISH_URL,
                "max_ppt": (d["max_pfos_ppb"] if d else None),   # note: fish is ppb, labelled in popup
                "sample_date": d["latest"] if d else None, "summary": None,
                "props": {"waterbody": a.get("WaterBody"),
                          "species": sorted(d["species"])[:8] if d else [],
                          "samples": d["samples"] if d else 0,
                          "max_pfos_ppb": d["max_pfos_ppb"] if d else None,
                          "unit": "ppb (fish tissue)"}})
            fish_n += 1
        counts["fish"] = fish_n
        log(f"  PFAS fish sampling sites: {fish_n}", level="ok")
    except Exception as e:                   # noqa: BLE001
        log(f"  PFAS fish fetch failed: {e}", level="warn")

    # ---- 5. Publicly Owned Treatment Works with PFAS data ----
    try:
        potw_n = 0
        for f in _arcgis_all(PFAS_POTW_URL):
            a = f.get("attributes", {})
            lat, lng = _to_float(a.get("Latitude")), _to_float(a.get("Longitude"))
            if lat is None or lng is None:
                continue
            cname, fips = county_of(a.get("County"), lat, lng)
            rows.append({
                "feature_key": f"potw:{a.get('GlobalID') or a.get('OBJECTID')}",
                "kind": "potw", "name": (a.get("Name") or "Treatment plant").strip(),
                "site_type": a.get("DischargeType"),
                "county": cname, "county_fips": fips, "latitude": lat, "longitude": lng,
                "hyperlink": (a.get("MiEnviroUrl") or "").strip() or None,
                "site_lead": (a.get("EGLEContact") or "").strip() or None,
                "site_lead_email": (a.get("ContactEmail") or "").strip() or None,
                "site_lead_phone": (a.get("ContactPhone") or "").strip() or None,
                "summary": None,
                "props": {"permit": a.get("PermitNumber"), "outfall": a.get("NPDESOutfall"),
                          "receiving_water": a.get("ReceivingWaterbody"),
                          "approved_ipp": a.get("ApprovedIPP"),
                          "exceeds_gw_criteria": a.get("ExceedsGwCleanUpCriteria")}})
            potw_n += 1
        counts["potw"] = potw_n
        log(f"  PFAS treatment plants (POTW): {potw_n}", level="ok")
    except Exception as e:                   # noqa: BLE001
        log(f"  PFAS POTW fetch failed: {e}", level="warn")

    # ---- cross-link Sites/AOIs to Superfund / TRI / landfill (precision-first) ----
    xlinks = 0
    for rec in rows:
        if rec["kind"] not in ("site", "aoi"):
            continue
        fips = rec["county_fips"]
        if not fips:
            continue
        c = _best_crosslink(rec, contam_by_fips.get(fips, []), "site_name", "company")
        if c:
            rec["contam_site_key"] = c["site_key"]; xlinks += 1
        t = _best_crosslink(rec, tri_by_fips.get(fips, []), "facility_name")
        if t:
            rec["tri_facility_id"] = t["facility_id"]
        lf = _best_crosslink(rec, landfill_by_fips.get(fips, []), "name", "operator")
        if lf:
            rec["landfill_site_key"] = lf["site_key"]

    cur.execute("DELETE FROM pfas_features")
    for r in rows:
        cur.execute(
            """INSERT OR REPLACE INTO pfas_features(
                 feature_key, kind, name, site_type, address, city, zip, county,
                 county_fips, latitude, longitude, geometry, residential_wells,
                 hyperlink, site_lead, site_lead_email, site_lead_phone, max_ppt,
                 sample_date, summary, props, contam_site_key, tri_facility_id,
                 landfill_site_key, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["feature_key"], r["kind"], r.get("name"), r.get("site_type"),
             r.get("address"), r.get("city"), r.get("zip"), r.get("county"),
             r.get("county_fips"), r.get("latitude"), r.get("longitude"),
             r.get("geometry"), r.get("residential_wells"), r.get("hyperlink"),
             r.get("site_lead"), r.get("site_lead_email"), r.get("site_lead_phone"),
             r.get("max_ppt"), r.get("sample_date"), r.get("summary"),
             json.dumps(r.get("props") or {}), r.get("contam_site_key"),
             r.get("tri_facility_id"), r.get("landfill_site_key"), "EGLE_MPART"))
    conn.commit()

    # Attach the curated narratives (history + severity context) to the matching
    # live MPART records. The live feed stays the source of truth for location/
    # status/contact; this only adds context on top.
    try:
        n_narr = apply_pfas_narratives(conn)
        if n_narr:
            log(f"  applied {n_narr} curated PFAS narratives", level="ok")
    except Exception as e:                    # noqa: BLE001 — enrichment is optional
        log(f"  PFAS narrative apply failed: {e}", level="warn")

    total = len(rows)
    sites = counts.get("sites_aois", 0)
    status = "ok" if sites else ("partial" if total else "unavailable")
    log(f"  PFAS: {total} features ({sites} sites/AOIs, {xlinks} contamination "
        f"cross-links)", level="ok" if total else "warn")
    record_source(
        conn, "egle_mpart_pfas",
        "Michigan PFAS Action Response Team (MPART) / EGLE — PFAS data",
        MPART_HOME_URL, status, total,
        f"{total} PFAS features from five live EGLE/MPART ArcGIS feeds: "
        f"{sites} Sites & Areas of Interest, plus surface-water, public-water-"
        f"supply (hexbin), fish, and treatment-plant sampling. Live-updated; "
        f"investigation ongoing. Public water results are hexbins, not precise "
        f"locations, by EGLE design. No site or concentration is fabricated.")
    record_source(
        conn, "mdhhs_eat_safe_fish",
        "MDHHS Eat Safe Fish — Michigan fish consumption guidance",
        MDHHS_EAT_SAFE_FISH_URL, "reference", 0,
        "Official Michigan fish-consumption advisories (incl. PFOS). Fish PFAS "
        "sampling popups link here rather than inventing consumption advice.")
    record_source(
        conn, "mpart_hub",
        "EGLE PFAS Open Data Hub (ArcGIS)", MPART_HUB_URL, "reference", 0,
        "Live EGLE ArcGIS feeds behind the PFAS layer (sites/AOIs, surface water, "
        "public water supply, fish, treatment plants).")
    return total


def apply_pfas_narratives(conn: sqlite3.Connection) -> int:
    """Attach the hand-researched narratives in app/pfas_narratives.py to the
    matching live MPART site/AOI records (county + name-token match). Re-applied on
    every full loader run so a reload never loses the curated context. Only touches
    site/AOI rows; the live feed remains the source of truth for location/status.
    """
    from . import pfas_narratives

    cur = conn.cursor()
    applied = 0
    for r in cur.execute(
        "SELECT feature_key, name, county_fips FROM pfas_features "
        "WHERE kind IN ('site','aoi')").fetchall():
        rec = pfas_narratives.narrative_for(r["name"], r["county_fips"])
        if not rec:
            continue
        facts = {
            "peaks": rec.get("peaks") or [],
            "advisories": rec.get("advisories") or [],
            "status": rec.get("status") or None,
        }
        conn.execute(
            """UPDATE pfas_features
                  SET narrative = ?, narrative_title = ?, narrative_facts = ?,
                      narrative_refs = ?, narrative_source = 'curated'
                WHERE feature_key = ?""",
            (rec.get("narrative"), rec.get("title"), json.dumps(facts),
             json.dumps(rec.get("refs") or []), r["feature_key"]))
        applied += 1
    conn.commit()
    return applied


# ---------- Underground Storage Tanks (EGLE RRD) ----------
#
# The most common near-home contamination source (~6,400 open leaking releases).
# Part 211 licensed tanks and Part 213 leaking tanks are kept strictly distinct
# so a working gas station never looks like a contaminated site. No fabrication.

def load_ust(conn: sqlite3.Connection) -> int:
    """Load all Michigan Underground Storage Tank sites from EGLE's RRD open-data
    layer, classify each (open leaking / closed leaking / licensed), and cross-
    link OPEN releases to the app's contamination/Superfund records."""
    log("Loading Underground Storage Tanks (EGLE RRD, live)...")
    cur = conn.cursor()

    def _ckey(name):
        return (name or "").replace(".", "").strip().lower()
    fips_by_lname = {_ckey(name): fips for fips, name in _county_fips_list(conn)}
    locate = _build_county_locator()
    _, contam_by_fips = _build_crosslink_index(conn)

    try:
        feats = _arcgis_all(UST_URL)
    except Exception as e:                       # noqa: BLE001
        log(f"  UST fetch failed: {e}", level="warn")
        record_source(conn, "egle_ust", "Michigan EGLE — Underground Storage Tanks",
                      EGLE_UST_HOME_URL, "unavailable", 0,
                      "EGLE RRD UST fetch failed this run; keeping prior data.")
        return 0

    rows = []
    for f in feats:
        a = f.get("attributes", {})
        lat, lng = _to_float(a.get("Latitude")), _to_float(a.get("Longitude"))
        if lat is None or lng is None:
            continue
        prog = a.get("RegulatoryProgram")
        try:
            prog = int(prog) if prog is not None else None
        except (TypeError, ValueError):
            prog = None
        cat = ust_data.classify(a.get("Open_Release"), a.get("Total_Release"), prog)
        method = (a.get("HorizontalCollectionMethod") or "").strip()
        ml = method.lower()
        addr_matched = 1 if "address match" in ml else 0
        method_short = ("Address-matched (approximate)" if addr_matched
                        else "GPS" if "gps" in ml
                        else "Interpolation/other" if method else None)
        cname = a.get("County")
        fips = fips_by_lname.get(_ckey(cname))
        cty = (cname or "").title() or None
        if not fips:
            fips, nm = locate(lng, lat)
            cty = cty or nm
        fid = a.get("FacilityID")
        rows.append({
            "site_key": f"ust:{fid or a.get('OBJECTID')}", "facility_id": fid,
            "facility_name": (a.get("FacilityName") or "Storage-tank facility").strip(),
            "category": cat, "regulatory_program": prog,
            "address": (a.get("Address") or "").strip() or None,
            "city": (a.get("City") or "").strip().title() or None,
            "zip": (a.get("ZipCode") or "").strip() or None,
            "county": cty, "county_fips": fips, "latitude": lat, "longitude": lng,
            "project_manager": (a.get("ProjectManager") or "").strip() or None,
            "work_unit": (a.get("WorkUnit") or "").strip() or None,
            "total_tanks": a.get("Total_Tank"), "active_tanks": a.get("Active_Tank"),
            "total_release": a.get("Total_Release"), "open_release": a.get("Open_Release"),
            "closed_release": a.get("Closed_Release"),
            "release_status": (a.get("ReleaseStatus") or "").strip() or None,
            "current_classification": (a.get("CurrentClassification") or "").strip() or None,
            "highest_classification": (a.get("HighestClassification") or "").strip() or None,
            "risk_condition": (a.get("RiskCondition") or "").strip() or None,
            "has_bea": (a.get("HasBEA") or "").strip() or None,
            "horizontal_accuracy": _to_float(a.get("HorizontalAccuracy")),
            "collection_method": method_short, "address_matched": addr_matched,
            "reference_point": (a.get("ReferencePoint") or "").strip() or None,
            "facility_url": None,
            "last_updated": pfas_data.epoch_to_iso(a.get("LastUpdated")),
            "name": (a.get("FacilityName") or "").strip(),   # for _best_crosslink
        })

    # Cross-link OPEN leaking releases to the app's contamination/Superfund records
    # (precision-first: shared name tokens + proximity, never coordinates alone).
    xlinks = 0
    for rec in rows:
        if rec["category"] != "leaking_open" or not rec["county_fips"]:
            continue
        c = _best_crosslink(rec, contam_by_fips.get(rec["county_fips"], []),
                            "site_name", "company")
        if c:
            rec["contam_site_key"] = c["site_key"]; xlinks += 1

    cur.execute("DELETE FROM ust_sites")
    cur.executemany(
        """INSERT OR REPLACE INTO ust_sites(
             site_key, facility_id, facility_name, category, regulatory_program,
             address, city, zip, county, county_fips, latitude, longitude,
             project_manager, work_unit, total_tanks, active_tanks, total_release,
             open_release, closed_release, release_status, current_classification,
             highest_classification, risk_condition, has_bea, horizontal_accuracy,
             collection_method, address_matched, reference_point, facility_url,
             last_updated, contam_site_key, source)
           VALUES (:site_key,:facility_id,:facility_name,:category,:regulatory_program,
             :address,:city,:zip,:county,:county_fips,:latitude,:longitude,
             :project_manager,:work_unit,:total_tanks,:active_tanks,:total_release,
             :open_release,:closed_release,:release_status,:current_classification,
             :highest_classification,:risk_condition,:has_bea,:horizontal_accuracy,
             :collection_method,:address_matched,:reference_point,:facility_url,
             :last_updated,:contam_site_key,'EGLE_RRD')""",
        [{**r, "contam_site_key": r.get("contam_site_key")} for r in rows])
    conn.commit()

    total = len(rows)
    n_open = sum(1 for r in rows if r["category"] == "leaking_open")
    n_closed = sum(1 for r in rows if r["category"] == "leaking_closed")
    n_lic = sum(1 for r in rows if r["category"] == "licensed")
    log(f"  USTs: {total} ({n_open} open leaking, {n_closed} closed/remediated, "
        f"{n_lic} licensed; {xlinks} contamination cross-links)",
        level="ok" if total else "warn")
    record_source(
        conn, "egle_ust",
        "Michigan EGLE — Underground Storage Tanks (Part 211 / Part 213)",
        EGLE_UST_HOME_URL, "ok" if total else "unavailable", total,
        f"{total} registered UST facilities from EGLE's Remediation & "
        f"Redevelopment open data (live): {n_open} with an open leaking release "
        f"(Part 213 corrective action), {n_closed} with closed/remediated "
        f"releases, {n_lic} licensed-only (Part 211). Unregistered / abandoned "
        f"tanks (incl. most residential heating-oil tanks) are not included. "
        f"Point locations vary in accuracy. No site or status is fabricated.")
    record_source(
        conn, "egle_ride",
        "EGLE RIDE — Remediation Information Data Exchange (per-site mapper)",
        EGLE_RIDE_URL, "reference", 0,
        "EGLE's interactive viewer for per-site release status, classification, "
        "and corrective-action detail behind the UST layer.")
    return total


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

    # landfill_sites: add extra-identifier columns (Part 111 EGLE WDS ID). Rows
    # are rebuilt each run, so a non-destructive ALTER is enough.
    lcols = {r[1] for r in conn.execute("PRAGMA table_info(landfill_sites)")}
    if lcols and "alt_id" not in lcols:
        log("schema migration: adding landfill_sites.alt_id / alt_id_label", level="warn")
        conn.execute("ALTER TABLE landfill_sites ADD COLUMN alt_id TEXT")
        conn.execute("ALTER TABLE landfill_sites ADD COLUMN alt_id_label TEXT")
        conn.commit()

    # pfas_features: add curated-narrative columns (rows are rebuilt each run, so
    # a non-destructive ALTER is enough to make the new INSERT/UPDATE columns valid).
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(pfas_features)")}
    if pcols and "narrative" not in pcols:
        log("schema migration: adding pfas_features narrative columns", level="warn")
        for col in ("narrative TEXT", "narrative_title TEXT", "narrative_facts TEXT",
                    "narrative_refs TEXT", "narrative_source TEXT"):
            conn.execute(f"ALTER TABLE pfas_features ADD COLUMN {col}")
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

    places = load_places(conn)
    log(f"searchable places loaded: {places}", level="ok")

    rows, ok_years, failed_years = load_usgs_pesticide_use(conn)
    log(f"USGS pesticide_use rows: {rows:,} across {len(ok_years)} years", level="ok")

    crop_use_rows = load_usgs_pesticide_use_by_crop(conn)
    log(f"USGS pesticide_use_by_crop rows: {crop_use_rows:,}", level="ok")

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
    for t in ("counties", "places", "pesticide_use", "pesticide_categories",
              "pesticide_use_by_crop", "crop_acreage", "data_sources",
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
