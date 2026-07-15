"""Offline test of the incremental WQP refresh path (no network / no portal).

Stubs data_loader.download_stream to emulate the Water Quality Portal's
startDateLo date filtering, runs the real refresh_source() harness against a
COPY of the live DB, and checks: seeding, watermark delta append, atomic swap,
idempotency, and that a failed delta preserves existing data.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import data_loader as dl
from app.config import DB_PATH, DATA_DIR
import refresh_data as R

TEST_DB = DATA_DIR / "_test_incremental.sqlite"

# Synthetic "portal" rows: (sample_date, compound, value). The stub returns only
# those on/after the startDateLo encoded in the requested URL — exactly as WQP
# would — so the watermark-day re-fetch and idempotency behave realistically.
MASTER = [
    ("2023-12-20", "Atrazine", "0.5"),     # on the current watermark day
    ("2024-03-15", "Atrazine", "0.3"),     # new
    ("2024-06-01", "Metolachlor", "0.2"),  # new
]
SITE_ID = None  # filled from the copied DB


def _iso_from_wqp(mmddyyyy: str) -> str:
    m, d, y = mmddyyyy.split("-")
    return f"{y}-{m}-{d}"


def make_stub(fail_delta=False):
    def stub(url, path, **kw):
        if "Station" in url:
            raise RuntimeError("stations stubbed offline (keep existing)")
        if fail_delta:
            raise RuntimeError("simulated WQP delta failure")
        # parse startDateLo=MM-DD-YYYY -> ISO, filter MASTER
        lo = None
        if "startDateLo=" in url:
            lo = _iso_from_wqp(url.split("startDateLo=")[1].split("&")[0])
        rows = [r for r in MASTER if lo is None or r[0] >= lo]
        header = ("MonitoringLocationIdentifier,ActivityMediaName,CharacteristicName,"
                  "ActivityStartDate,ResultMeasure/MeasureUnitCode,ResultMeasureValue,"
                  "DetectionQuantitationLimitMeasure/MeasureValue,ResultDetectionConditionText")
        lines = [header]
        for date, comp, val in rows:
            lines.append(f"{SITE_ID},Water,{comp},{date},ug/l,{val},,")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return sum(len(l) for l in lines)
    return stub


def counts(db):
    c = sqlite3.connect(db)
    tot = c.execute("SELECT COUNT(*) FROM water_quality_results").fetchone()[0]
    iso = c.execute(f"SELECT COUNT(*) FROM water_quality_results "
                    f"WHERE sample_date GLOB '{dl._WQP_ISO_GLOB}'").fetchone()[0]
    wm = c.execute(f"SELECT MAX(sample_date) FROM water_quality_results "
                   f"WHERE sample_date GLOB '{dl._WQP_ISO_GLOB}'").fetchone()[0]
    st = c.execute("SELECT status, refresh_status FROM data_sources "
                   "WHERE source_id='wqp'").fetchone()
    c.close()
    return tot, iso, wm, st


def main():
    global SITE_ID
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.copy(DB_PATH, TEST_DB)
    SITE_ID = sqlite3.connect(TEST_DB).execute(
        "SELECT site_id FROM water_quality_sites LIMIT 1").fetchone()[0]

    wq = R.SOURCES_BY_ID["water_quality"]
    log = R.RunLogger(DATA_DIR / "_test_incremental.log")
    orig = dl.download_stream
    ok = True
    try:
        base = counts(TEST_DB)
        # The watermark day is deleted and re-fetched in full. Our stub only
        # re-emits 1 synthetic row for that day (WQP would return all of them),
        # so account for the real day's row count in the expectation.
        wm_day = sqlite3.connect(TEST_DB).execute(
            "SELECT COUNT(*) FROM water_quality_results WHERE sample_date=?",
            (base[2],)).fetchone()[0]
        print(f"[base]  total={base[0]:,} iso={base[1]:,} watermark={base[2]} "
              f"(rows on that day={wm_day})")

        # --- Run 1: successful incremental append ---
        dl.download_stream = make_stub()
        r1 = R.refresh_source(wq, TEST_DB, log)
        c1 = counts(TEST_DB)
        print(f"[run1]  status={r1.status} total={c1[0]:,} iso={c1[1]:,} "
              f"watermark={c1[2]} wqp_status={c1[3]}")
        # delete watermark-day rows (wm_day) then re-ingest the 3 delta rows
        expect1 = base[0] - wm_day + 3
        assert r1.status == "success", r1.message
        assert c1[0] == expect1, f"expected {expect1}, got {c1[0]}"
        assert c1[2] == "2024-06-01", c1[2]
        assert c1[3] == ("ok", "success"), c1[3]

        # --- Run 2: idempotent (same portal data, watermark now 2024-06-01) ---
        r2 = R.refresh_source(wq, TEST_DB, log)
        c2 = counts(TEST_DB)
        print(f"[run2]  status={r2.status} total={c2[0]:,} iso={c2[1]:,} watermark={c2[2]}")
        assert r2.status == "success", r2.message
        assert c2[0] == c1[0], f"NOT idempotent: {c1[0]} -> {c2[0]}"

        # --- Run 3: delta fetch fails -> keep data, mark failed ---
        dl.download_stream = make_stub(fail_delta=True)
        r3 = R.refresh_source(wq, TEST_DB, log)
        c3 = counts(TEST_DB)
        print(f"[run3]  status={r3.status} total={c3[0]:,} (should equal run2) "
              f"wqp_status={c3[3]}")
        assert r3.status == "failed", "should fail when delta download fails"
        assert c3[0] == c2[0], f"data lost on failure: {c2[0]} -> {c3[0]}"
        assert c3[3][1] == "failed", c3[3]

        print("\nALL ASSERTIONS PASSED")
    except AssertionError as e:
        ok = False
        print(f"\nASSERTION FAILED: {e}")
    finally:
        dl.download_stream = orig
        log.close()
        if TEST_DB.exists():
            TEST_DB.unlink()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
