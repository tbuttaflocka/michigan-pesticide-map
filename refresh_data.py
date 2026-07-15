#!/usr/bin/env python3
r"""
Unified data-refresh harness for the Michigan Pesticide Heat Map.
=================================================================

Re-pulls every live data source and updates the SQLite database *safely*: each
source is refreshed independently (one failing source never blocks the others),
into a private staging database that is validated before it is allowed to
replace the live tables. If a source goes down or changes its format, the app
keeps the data it already had — it is never left empty or half-written.

WHAT IT DOES, PER SOURCE
------------------------
  1. Build a throwaway staging SQLite file and seed it with the `counties`
     table (the only table every loader reads).
  2. Run the source's existing loader(s) from app/data_loader.py against the
     staging database (mutable sources are force re-downloaded; immutable
     archival caches such as finalized USGS EPest files are reused).
  3. Validate the staged result: expected tables/columns present, primary table
     non-empty, and total row count not collapsed vs. the current live data
     (guards against a source that started returning an empty/broken payload).
  4. Only if validation passes: atomically swap the staged tables into the live
     database inside a single transaction (ATTACH + DELETE + INSERT..SELECT).
  5. Record provenance/freshness into the `data_sources` table (last success,
     coverage window, refresh status, expected refresh interval).

After any successful swap the derived analysis tables
(`correlation_analysis`, `cancer_pesticide_correlation`) are rebuilt from the
live database so the correlations stay consistent with the refreshed inputs.

USAGE
-----
    python refresh_data.py                      # refresh all sources
    python refresh_data.py --source water_quality   # refresh just one
    python refresh_data.py --list               # show sources + last status
    python refresh_data.py --help

Every run is appended to  refresh.log  with timestamps and per-source results.
The script is idempotent — running it twice does not duplicate data.

SCHEDULING (Windows Task Scheduler)
-----------------------------------
See the "Keeping the data fresh" section of README.md. Recommended cadence:
  * Annual   (Jan): usgs_epest, nass_crop, respiratory, cancer, wind
  * Quarterly:      water_quality, superfund, cwd
Example (monthly all-sources check; per-source guards skip anything unchanged):

    schtasks /create /tn "PesticideMap Refresh" /sc MONTHLY /d 1 /st 03:00 ^
      /tr "\"C:\path\to\.venv\Scripts\python.exe\" \"C:\path\to\refresh_data.py\""
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import data_loader as dl          # noqa: E402
from app import database                    # noqa: E402
from app.config import DB_PATH, DATA_DIR    # noqa: E402

STAGING_DIR = DATA_DIR / "staging"
LOG_PATH = BASE_DIR / "refresh.log"


# --------------------------------------------------------------------------- #
# Logging — everything goes to stdout AND to refresh.log                        #
# --------------------------------------------------------------------------- #

class RunLogger:
    def __init__(self, path: Path):
        self.path = path
        self._fh = path.open("a", encoding="utf-8")
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")   # avoid cp1252 mojibake
            except Exception:
                pass

    def line(self, msg: str, level: str = "info") -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sym = {"info": "[*]", "ok": "[OK]", "warn": "[!]",
               "err": "[X]", "hdr": "==="}.get(level, "[*]")
        text = f"{ts} {sym} {msg}"
        print(text, flush=True)
        self._fh.write(text + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Coverage helpers — compute the data window from the LIVE db after a swap      #
# --------------------------------------------------------------------------- #

def year_range(table: str, col: str = "year") -> Callable[[sqlite3.Connection], tuple]:
    def fn(conn):
        row = conn.execute(
            f"SELECT MIN({col}), MAX({col}) FROM {table} "
            f"WHERE {col} IS NOT NULL"
        ).fetchone()
        if not row or row[0] is None:
            return (None, None)
        return (str(int(row[0])), str(int(row[1])))
    return fn


def year4_range(table: str, col: str) -> Callable[[sqlite3.Connection], tuple]:
    """Coverage from a text date column, using the leading 4-digit year."""
    def fn(conn):
        row = conn.execute(
            f"SELECT MIN(substr({col},1,4)), MAX(substr({col},1,4)) FROM {table} "
            f"WHERE {col} GLOB '[12][0-9][0-9][0-9]*'"
        ).fetchone()
        if not row or not row[0]:
            return (None, None)
        return (row[0], row[1])
    return fn


def label_range(table: str, col: str) -> Callable[[sqlite3.Connection], tuple]:
    """Coverage from a stored 'YYYY-YYYY' label (wind years, cancer data_years)."""
    def fn(conn):
        row = conn.execute(
            f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != '' LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return (None, None)
        parts = str(row[0]).replace("–", "-").split("-")
        start = parts[0].strip()
        end = parts[-1].strip()
        return (start or None, end or None)
    return fn


# --------------------------------------------------------------------------- #
# Source registry                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class Source:
    id: str                          # module id used with --source
    label: str                       # human-readable name
    loaders: list                    # loader callables f(conn) run in order
    targets: list                    # live tables this source owns (parent->child)
    primary_target: str              # table that must be non-empty to be valid
    primary_source_id: str           # data_sources.source_id to carry freshness
    interval_months: int             # expected refresh cadence (staleness)
    coverage: Callable               # f(live_conn) -> (start, end)
    min_abs: int = 1                 # absolute floor on primary_target rows
    floor_frac: float = 0.5          # staged rows must be >= this * live rows
    allow_skip: bool = True          # a loader that self-reports 'skipped' is OK
    seed_extra: tuple = ()           # live tables (besides counties) to copy into
                                     #   staging first — needed by incremental
                                     #   loaders that append onto existing data
    require_primary_ok: bool = False # fail the refresh if the loader records the
                                     #   primary source as not 'ok' (for seeded
                                     #   sources where old rows would mask a
                                     #   failed fetch and fool the row-count guard)


SOURCES: list[Source] = [
    Source(
        id="usgs_epest", label="USGS NAWQA EPest — agricultural pesticide use",
        loaders=[dl.load_usgs_pesticide_use],
        targets=["pesticide_use", "pesticide_categories"],
        primary_target="pesticide_use", primary_source_id="usgs_epest",
        interval_months=12, min_abs=1000, floor_frac=0.8,
        coverage=year_range("pesticide_use"),
    ),
    Source(
        id="nass_crop", label="USDA NASS — Michigan crop acreage",
        loaders=[dl.load_nass_crop_acreage],
        targets=["crop_acreage"],
        primary_target="crop_acreage", primary_source_id="nass_acreage",
        interval_months=12, min_abs=1, floor_frac=0.5,
        coverage=year_range("crop_acreage"),
    ),
    Source(
        id="cwd", label="Michigan DNR — Chronic Wasting Disease",
        loaders=[dl.load_cwd_data],
        targets=["cwd_wild_deer", "cwd_farmed_deer", "cwd_surveillance"],
        primary_target="cwd_wild_deer", primary_source_id="dnr_cwd",
        interval_months=3, min_abs=1, floor_frac=0.5,
        coverage=year_range("cwd_surveillance", "surveillance_year"),
    ),
    Source(
        id="respiratory", label="CDC Environmental Tracking + WONDER — respiratory",
        loaders=[dl.load_respiratory_data],
        targets=["respiratory_ed_visits", "respiratory_hospitalizations",
                 "respiratory_prevalence", "respiratory_mortality"],
        primary_target="respiratory_ed_visits", primary_source_id="cdc_tracking",
        interval_months=12, min_abs=1, floor_frac=0.4,
        coverage=year_range("respiratory_ed_visits"),
    ),
    Source(
        id="water_quality", label="USGS/EPA Water Quality Portal — pesticide samples",
        loaders=[dl.load_water_quality],
        targets=["watersheds", "water_quality_sites", "water_quality_results"],
        primary_target="water_quality_results", primary_source_id="wqp",
        interval_months=3, min_abs=1, floor_frac=0.4,
        coverage=year4_range("water_quality_results", "sample_date"),
        # Incremental: seed staging with the existing WQP data so the loader
        # only appends the date-bounded delta. require_primary_ok makes a failed
        # WQP fetch a real failure (the seeded rows would otherwise pass the
        # collapse guard and look like a success).
        seed_extra=("water_quality_sites", "water_quality_results", "watersheds"),
        require_primary_ok=True,
    ),
    Source(
        id="superfund", label="EPA Superfund — NPL contamination sites",
        loaders=[dl.load_contamination_data],
        targets=["contamination_sites"],
        primary_target="contamination_sites", primary_source_id="epa_sems_npl",
        interval_months=3, min_abs=20, floor_frac=0.5,
        coverage=year4_range("contamination_sites", "npl_date"),
    ),
    Source(
        id="wind", label="Iowa Environmental Mesonet — ASOS growing-season wind",
        loaders=[dl.load_wind_data],
        targets=["wind_data"],
        primary_target="wind_data", primary_source_id="iem_asos_wind",
        interval_months=12, min_abs=1, floor_frac=0.5,
        coverage=label_range("wind_data", "years"),
    ),
    Source(
        id="cancer", label="NCI/CDC State Cancer Profiles — incidence & mortality",
        loaders=[dl.load_cancer_data],
        targets=["cancer_incidence", "cancer_reference", "cancer_evidence"],
        primary_target="cancer_incidence", primary_source_id="nci_scp",
        interval_months=12, min_abs=50, floor_frac=0.5,
        coverage=label_range("cancer_incidence", "data_years"),
    ),
]

SOURCES_BY_ID = {s.id: s for s in SOURCES}


# --------------------------------------------------------------------------- #
# Staging + validation + swap                                                  #
# --------------------------------------------------------------------------- #

def _table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return 0


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


@dataclass
class Result:
    source_id: str
    status: str                       # success | failed | partial | skipped
    rows: int = 0
    message: str = ""
    coverage: tuple = (None, None)


def _build_staging(src: Source, live_path: Path, log: RunLogger) -> Path:
    """Create a fresh staging DB seeded with counties (every loader's only
    prerequisite) plus any `seed_extra` tables an incremental loader appends
    onto. `seed_extra` is copied in declared order so parent tables land before
    their FK children."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staging_path = STAGING_DIR / f"{src.id}.staging.sqlite"
    if staging_path.exists():
        staging_path.unlink()

    stg = database.connect(staging_path)
    try:
        database.init_schema(stg)
        stg.execute("ATTACH DATABASE ? AS live", (str(live_path),))
        for table in ("counties", *src.seed_extra):
            n = stg.execute(f"SELECT COUNT(*) FROM live.{table}").fetchone()[0]
            stg.execute(f"INSERT INTO {table} SELECT * FROM live.{table}")
            if table != "counties":
                log.line(f"  seeded {n:,} rows into staging.{table}")
        stg.commit()                 # release the txn before DETACH
        stg.execute("DETACH DATABASE live")
    finally:
        stg.close()
    return staging_path


def _validate(src: Source, stg: sqlite3.Connection,
              live: sqlite3.Connection, log: RunLogger) -> tuple[bool, str]:
    """Row-count / column sanity vs. the current live data. Returns (ok, msg)."""
    # Expected columns present on every target (guards a schema drift that would
    # make the INSERT..SELECT swap misalign).
    for t in src.targets:
        scols, lcols = _columns(stg, t), _columns(live, t)
        if scols != lcols:
            missing = lcols - scols
            extra = scols - lcols
            return False, (f"column mismatch on {t} "
                           f"(missing={sorted(missing)}, extra={sorted(extra)})")

    staged_primary = _table_count(stg, src.primary_target)
    live_primary = _table_count(live, src.primary_target)
    staged_total = sum(_table_count(stg, t) for t in src.targets)
    live_total = sum(_table_count(live, t) for t in src.targets)

    if staged_primary <= 0:
        return False, f"{src.primary_target} came back empty (0 rows)"
    if staged_primary < src.min_abs:
        return False, (f"{src.primary_target} has only {staged_primary} rows "
                       f"(<{src.min_abs} floor)")
    floor = int(src.floor_frac * live_total) if live_total else 0
    if staged_total < floor:
        return False, (f"staged rows {staged_total:,} collapsed vs live "
                       f"{live_total:,} (floor {floor:,}) — refusing swap")
    return True, (f"{staged_primary:,} {src.primary_target} rows, "
                  f"{staged_total:,} total (live had {live_total:,})")


def _swap(src: Source, staging_path: Path, live_path: Path, log: RunLogger) -> None:
    """Atomically replace live target tables with the staged ones."""
    live = database.connect(live_path)
    live.isolation_level = None            # manual transaction control
    try:
        live.execute("PRAGMA foreign_keys=OFF")
        live.execute("ATTACH DATABASE ? AS stg", (str(staging_path),))
        live.execute("BEGIN IMMEDIATE")
        try:
            for t in src.targets:
                live.execute(f"DELETE FROM {t}")
                live.execute(f"INSERT INTO {t} SELECT * FROM stg.{t}")
            live.execute("COMMIT")
        except Exception:
            live.execute("ROLLBACK")
            raise
        finally:
            live.execute("DETACH DATABASE stg")
            live.execute("PRAGMA foreign_keys=ON")
    finally:
        live.close()


def _copy_source_rows(staging_path: Path, live: sqlite3.Connection) -> None:
    """Copy the data_sources rows the loader wrote into staging over to live,
    preserving freshness columns (record_source COALESCEs them)."""
    stg = sqlite3.connect(staging_path)
    stg.row_factory = sqlite3.Row
    try:
        rows = stg.execute(
            "SELECT source_id, title, url, status, rows_loaded, notes "
            "FROM data_sources"
        ).fetchall()
    finally:
        stg.close()
    for r in rows:
        dl.record_source(live, r["source_id"], r["title"], r["url"],
                         r["status"], r["rows_loaded"] or 0, r["notes"] or "")


def _stamp_success(src: Source, live: sqlite3.Connection, rows: int,
                   coverage: tuple, now: str) -> None:
    start, end = coverage
    live.execute(
        """UPDATE data_sources SET
              refresh_status='success', last_success=?, last_attempt=?,
              refresh_interval_months=?, coverage_start=?, coverage_end=?
           WHERE source_id=?""",
        (now, now, src.interval_months, start, end, src.primary_source_id),
    )


def _stamp_outcome(src: Source, live: sqlite3.Connection, status: str,
                   msg: str, now: str) -> None:
    """Record a failed/skipped attempt on the primary source without touching
    last_success / coverage / rows (the last good data is preserved)."""
    exists = live.execute("SELECT 1 FROM data_sources WHERE source_id=?",
                          (src.primary_source_id,)).fetchone()
    if not exists:
        dl.record_source(live, src.primary_source_id, src.label, "",
                         "unavailable", 0, f"Refresh {status}: {msg}")
    live.execute(
        """UPDATE data_sources SET refresh_status=?, last_attempt=?,
              refresh_interval_months=COALESCE(refresh_interval_months, ?)
           WHERE source_id=?""",
        (status, now, src.interval_months, src.primary_source_id),
    )


def refresh_source(src: Source, live_path: Path, log: RunLogger) -> Result:
    """Refresh a single source end to end. Never raises — returns a Result."""
    log.line(f"--- {src.id}: {src.label}", level="hdr")
    now = _now()
    staging_path = None
    try:
        staging_path = _build_staging(src, live_path, log)

        # Run the loader(s) against staging (WQP force-refresh enabled globally).
        stg = database.connect(staging_path)
        try:
            for loader in src.loaders:
                loader(stg)
            stg.commit()

            # If the loader itself declared the source skipped (e.g. NASS with no
            # API key), honour that instead of failing validation on 0 rows.
            skip_row = stg.execute(
                "SELECT status FROM data_sources WHERE source_id=?",
                (src.primary_source_id,)).fetchone()
            if src.allow_skip and skip_row and skip_row[0] == "skipped":
                stg.close()
                live = database.connect(live_path)
                try:
                    _copy_source_rows(staging_path, live)
                    _stamp_outcome(src, live, "skipped",
                                   "loader reported source unavailable/unconfigured", now)
                    live.commit()
                finally:
                    live.close()
                log.line(f"{src.id}: SKIPPED (loader self-reported skipped)", level="warn")
                return Result(src.primary_source_id, "skipped",
                              message="loader reported skipped")

            # For seeded/incremental sources, a failed fetch leaves the seeded
            # rows in place — the row-count guard can't see the failure, so trust
            # the loader's own status on the primary source instead.
            if src.require_primary_ok:
                prow = stg.execute(
                    "SELECT status FROM data_sources WHERE source_id=?",
                    (src.primary_source_id,)).fetchone()
                if not prow or prow[0] != "ok":
                    ok, msg = False, (
                        f"primary source '{src.primary_source_id}' reported "
                        f"status='{prow[0] if prow else 'missing'}' (fetch failed)")
                    live_ro = None
                else:
                    live_ro = database.connect(live_path)
            else:
                live_ro = database.connect(live_path)

            if live_ro is not None:
                try:
                    ok, msg = _validate(src, stg, live_ro, log)
                finally:
                    live_ro.close()
        finally:
            stg.close()

        if not ok:
            live = database.connect(live_path)
            try:
                _stamp_outcome(src, live, "failed", msg, now)
                live.commit()
            finally:
                live.close()
            log.line(f"{src.id}: VALIDATION FAILED — {msg}. Live data kept.", level="err")
            return Result(src.primary_source_id, "failed", message=msg)

        # Validation passed -> swap into live.
        _swap(src, staging_path, live_path, log)

        live = database.connect(live_path)
        try:
            _copy_source_rows(staging_path, live)
            coverage = src.coverage(live)
            rows = _table_count(live, src.primary_target)
            _stamp_success(src, live, rows, coverage, now)
            live.commit()
        finally:
            live.close()

        cov = f"{coverage[0]}-{coverage[1]}" if coverage[0] else "n/a"
        log.line(f"{src.id}: SUCCESS — {msg}; coverage {cov}", level="ok")
        return Result(src.primary_source_id, "success", rows=rows,
                      message=msg, coverage=coverage)

    except Exception as e:
        tb = traceback.format_exc()
        log.line(f"{src.id}: ERROR — {e}. Live data kept.", level="err")
        for ln in tb.strip().splitlines():
            log.line("    " + ln, level="err")
        try:
            live = database.connect(live_path)
            try:
                _stamp_outcome(src, live, "failed", str(e), now)
                live.commit()
            finally:
                live.close()
        except Exception:
            pass
        return Result(src.primary_source_id, "failed", message=str(e))
    finally:
        if staging_path and staging_path.exists():
            try:
                staging_path.unlink()
            except OSError:
                pass


def rebuild_derived(live_path: Path, log: RunLogger) -> None:
    """Rebuild cross-source analysis tables from the live DB after refreshes."""
    log.line("--- rebuilding derived analysis tables", level="hdr")
    conn = database.connect(live_path)
    try:
        for name, fn in (("correlation_analysis", dl.build_correlation_table),
                         ("cancer_pesticide_correlation", dl.build_cancer_correlations)):
            try:
                n = fn(conn)
                conn.commit()
                log.line(f"{name}: {n:,} rows rebuilt", level="ok")
            except Exception as e:
                log.line(f"{name}: rebuild failed — {e}", level="warn")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def cmd_list(log: RunLogger) -> int:
    conn = database.connect(DB_PATH)
    try:
        print(f"{'SOURCE':<16} {'INTERVAL':<9} {'PRIMARY ID':<18} "
              f"{'REFRESH':<9} {'LAST SUCCESS':<21} COVERAGE")
        print("-" * 96)
        for s in SOURCES:
            row = conn.execute(
                "SELECT refresh_status, last_success, coverage_start, coverage_end "
                "FROM data_sources WHERE source_id=?", (s.primary_source_id,)
            ).fetchone()
            rs = (row["refresh_status"] if row and row["refresh_status"] else "never")
            ls = (row["last_success"][:19] if row and row["last_success"] else "-")
            cov = "-"
            if row and row["coverage_start"]:
                cov = f"{row['coverage_start']}-{row['coverage_end']}"
            print(f"{s.id:<16} {str(s.interval_months)+'mo':<9} "
                  f"{s.primary_source_id:<18} {rs:<9} {ls:<21} {cov}")
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Refresh the Michigan Pesticide Heat Map data sources.")
    p.add_argument("--source", help="refresh only this source id (see --list)")
    p.add_argument("--all", action="store_true",
                   help="refresh every source (default when --source is omitted)")
    p.add_argument("--list", action="store_true",
                   help="list sources with their last refresh status and exit")
    p.add_argument("--no-derived", action="store_true",
                   help="skip rebuilding correlation_analysis / cancer correlations")
    p.add_argument("--full", action="store_true",
                   help="force a full rebuild of water_quality (re-pull the whole "
                        "~230 MB WQP result set) instead of an incremental delta; "
                        "use occasionally to backfill late-uploaded old samples")
    args = p.parse_args(argv)

    log = RunLogger(LOG_PATH)
    try:
        # Make sure the live DB exists and has the freshness columns before any
        # command reads or writes them.
        conn = database.connect(DB_PATH)
        dl._migrate(conn)
        database.init_schema(conn)
        conn.close()

        if args.list:
            return cmd_list(log)

        if args.source:
            if args.source not in SOURCES_BY_ID:
                log.line(f"unknown source '{args.source}'. Known: "
                         f"{', '.join(SOURCES_BY_ID)}", level="err")
                return 2
            selected = [SOURCES_BY_ID[args.source]]
        else:
            selected = list(SOURCES)

        # Force re-download of mutable cached sources (WQP) for this run.
        dl.FORCE_REFRESH = True
        if args.full:
            dl.WQP_FULL_REBUILD = True
            log.line("water_quality: --full requested (full WQP rebuild)", level="info")

        log.line(f"REFRESH RUN START — {len(selected)} source(s): "
                 f"{', '.join(s.id for s in selected)}", level="hdr")

        results: list[Result] = []
        for src in selected:
            results.append(refresh_source(src, DB_PATH, log))

        any_success = any(r.status == "success" for r in results)
        if any_success and not args.no_derived:
            rebuild_derived(DB_PATH, log)

        # Summary
        log.line("REFRESH RUN COMPLETE", level="hdr")
        tally = {"success": 0, "failed": 0, "skipped": 0, "partial": 0}
        for r in results:
            tally[r.status] = tally.get(r.status, 0) + 1
            lvl = {"success": "ok", "skipped": "warn"}.get(r.status, "err")
            log.line(f"  {r.source_id:<18} {r.status:<8} {r.message}", level=lvl)
        log.line(f"  totals: {tally['success']} ok, {tally['failed']} failed, "
                 f"{tally['skipped']} skipped", level="info")
        # Non-zero exit if everything failed (useful for Task Scheduler alerts).
        return 0 if any_success or tally["skipped"] == len(results) else 1
    finally:
        log.close()


if __name__ == "__main__":
    sys.exit(main())
