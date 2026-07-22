"""Recompute the water_quality_results exceedance flags from stored values.

Two SEPARATE standards are tracked, never conflated:
  * exceeds_mcl       — sample above a human drinking-water MCL (EPA)
  * exceeds_benchmark — sample above an aquatic-life benchmark (ecological harm
                        to fish/insects/aquatic organisms; USGS/EPA OPP)

A sample can exceed either, both, or neither. Both flags are derived here
directly from the already-stored ``result_value`` + ``unit`` + ``compound``
(normalised to µg/L), using the current reference tables — no network access
and no re-download of the 226 MB WQP export. Also adds the exceeds_benchmark /
benchmark_value columns to an existing database if they are missing.

Run from the project root:
    py scripts/recompute_water_exceedances.py            # migrate + apply + report
    py scripts/recompute_water_exceedances.py --dry-run  # report only, no write
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import DB_PATH
from app.water_quality import benchmark_for, mcl_for, to_ugl


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(water_quality_results)")}
    if "exceeds_benchmark" not in cols:
        conn.execute("ALTER TABLE water_quality_results "
                     "ADD COLUMN exceeds_benchmark INTEGER DEFAULT 0")
    if "benchmark_value" not in cols:
        conn.execute("ALTER TABLE water_quality_results "
                     "ADD COLUMN benchmark_value REAL")
    conn.commit()


def recompute(dry_run: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if not dry_run:
        _ensure_columns(conn)

    def _count(col: str) -> int:
        try:
            return conn.execute(
                f"SELECT COUNT(*) FROM water_quality_results WHERE {col} = 1"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    mcl_before = _count("exceeds_mcl")
    bench_before = _count("exceeds_benchmark")

    updates: list[tuple] = []          # (exceeds_mcl, mcl_value, exceeds_benchmark, benchmark_value, id)
    mcl_after = bench_after = 0
    bench_by_compound: dict[str, int] = {}

    for r in conn.execute(
        "SELECT id, compound, result_value, unit, detected, exceeds_mcl "
        "  FROM water_quality_results"
    ):
        e_mcl = e_bench = 0
        # Re-derive BOTH stored thresholds from the reference tables. mcl_value
        # was previously written as a blended MCL-or-benchmark fallback, so it
        # held benchmark numbers for compounds with no MCL (e.g. imidacloprid,
        # metolachlor) — correct it to the true MCL (None when there is none).
        mcl = mcl_for(r["compound"])
        bench = benchmark_for(r["compound"])
        if r["detected"] and r["result_value"] is not None:
            ugl = to_ugl(r["result_value"], r["unit"])
            if ugl is not None:
                if mcl is not None and ugl > mcl:
                    e_mcl = 1
                if bench is not None and ugl > bench:
                    e_bench = 1
        mcl_after += e_mcl
        bench_after += e_bench
        if e_bench:
            bench_by_compound[r["compound"]] = bench_by_compound.get(r["compound"], 0) + 1
        updates.append((e_mcl, mcl, e_bench, bench, r["id"]))

    print(f"MCL exceedances        before: {mcl_before:5}   after: {mcl_after}")
    print(f"aquatic-benchmark exc. before: {bench_before:5}   after: {bench_after}")
    print("\naquatic-life-benchmark exceedances by compound:")
    for c, n in sorted(bench_by_compound.items(), key=lambda x: -x[1]):
        print(f"    {c:24} {n}")

    if dry_run:
        print("\n[dry-run] no changes written.")
        conn.close()
        return

    conn.executemany(
        "UPDATE water_quality_results "
        "   SET exceeds_mcl = ?, mcl_value = ?, exceeds_benchmark = ?, benchmark_value = ? "
        " WHERE id = ?",
        updates,
    )
    conn.commit()
    conn.close()
    print(f"\nWrote flags for {len(updates)} rows.")


if __name__ == "__main__":
    recompute(dry_run="--dry-run" in sys.argv)
