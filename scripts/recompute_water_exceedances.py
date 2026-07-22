"""Recompute the water_quality_results.exceeds_mcl flag from stored values.

The MCL-exceedance flag is set at ingest time by comparing each sample's
concentration (normalised to µg/L) against the compound's drinking-water MCL
(or aquatic-life benchmark). When the unit-conversion table (`_to_ugl`) misses
a real volumetric unit — e.g. ``ppt``, ``pg/L``, or fused labels like
``ugAtrazn/L`` — those samples are silently left unflagged, under-reporting
genuine exceedances.

This script re-derives the flag for every detected row directly from the
already-stored ``result_value`` + ``unit`` + ``compound``, using the current
(fixed) loader logic. It needs no network access and does not re-download the
226 MB WQP export — it just corrects the flag in place.

Run from the project root:
    py scripts/recompute_water_exceedances.py          # apply + report
    py scripts/recompute_water_exceedances.py --dry-run # report only, no write
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import DB_PATH
from app.water_quality import threshold_for, to_ugl


def recompute(dry_run: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    before = conn.execute(
        "SELECT COUNT(*) FROM water_quality_results WHERE exceeds_mcl = 1"
    ).fetchone()[0]

    updates: list[tuple[int, int]] = []   # (new_flag, rowid)
    newly_flagged: list[sqlite3.Row] = []
    newly_cleared: list[sqlite3.Row] = []

    for r in conn.execute(
        "SELECT rowid, compound, result_value, unit, detected, exceeds_mcl "
        "  FROM water_quality_results"
    ):
        new_flag = 0
        if r["detected"] and r["result_value"] is not None:
            mcl, _ = threshold_for(r["compound"])
            if mcl is not None:
                ugl = to_ugl(r["result_value"], r["unit"])
                if ugl is not None and ugl > mcl:
                    new_flag = 1
        if new_flag != r["exceeds_mcl"]:
            updates.append((new_flag, r["rowid"]))
            (newly_flagged if new_flag else newly_cleared).append(r)

    after = before + len(newly_flagged) - len(newly_cleared)
    print(f"exceeds_mcl = 1  before: {before}")
    print(f"exceeds_mcl = 1  after:  {after}")
    print(f"  newly flagged (were missed):   {len(newly_flagged)}")
    print(f"  newly cleared (were wrong):    {len(newly_cleared)}")

    def _summ(rows: list[sqlite3.Row]) -> None:
        by_unit: dict[str, int] = {}
        for r in rows:
            by_unit[r["unit"]] = by_unit.get(r["unit"], 0) + 1
        for u, n in sorted(by_unit.items(), key=lambda x: -x[1]):
            print(f"      {u!r:16} {n}")

    if newly_flagged:
        print("  newly-flagged by unit:")
        _summ(newly_flagged)
    if newly_cleared:
        print("  newly-cleared by unit:")
        _summ(newly_cleared)

    if dry_run:
        print("\n[dry-run] no changes written.")
        conn.close()
        return

    conn.executemany(
        "UPDATE water_quality_results SET exceeds_mcl = ? WHERE rowid = ?", updates
    )
    conn.commit()
    conn.close()
    print(f"\nWrote {len(updates)} corrected flags.")


if __name__ == "__main__":
    recompute(dry_run="--dry-run" in sys.argv)
