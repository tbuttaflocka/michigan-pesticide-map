"""enrich_chemicals.py — cache real PubChem chemical info for the compounds in
the app's data, so the chemical-info popups show a genuine plain-language
description (what it is, what it's used for) plus molecular formula, CAS, common
synonyms and a link to the full PubChem page — instead of a generic placeholder.

Source: PubChem PUG REST (NCBI), free, no API key. See app/chemical_reference.py.
This complements the EPA/IARC health & carcinogen classifications already shown;
it does not replace them.

Runs one HTTP-batched pass over every distinct chemical name in the pesticide,
TRI and water-quality tables, resolves each to a PubChem CID (with name/CAS
fallbacks), and stores the result in the chemical_reference table. Rate-limited
to stay under PubChem's ~5 requests/second guidance.

Re-runnable and incremental — names already cached are skipped unless --force,
so you can enrich newly-added chemicals later without re-fetching everything.

Usage:
  python enrich_chemicals.py                 # enrich everything not yet cached
  python enrich_chemicals.py --force         # re-fetch all (refresh descriptions)
  python enrich_chemicals.py --only atrazine # just matching names (testing)
  python enrich_chemicals.py --limit 20      # stop after N (a quick smoke test)
  python enrich_chemicals.py --list          # show cache status, make no changes
"""
from __future__ import annotations

import argparse
import sys

from app import chemical_reference as cr
from app import database


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cache PubChem chemical info for the compounds in the data.")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch every chemical, even ones already cached")
    ap.add_argument("--only", metavar="TEXT",
                    help="only chemicals whose name contains TEXT (case-insensitive)")
    ap.add_argument("--limit", type=int, metavar="N",
                    help="stop after N chemicals (smoke test)")
    ap.add_argument("--list", action="store_true",
                    help="show cache status and exit without fetching")
    args = ap.parse_args()

    conn = database.connect()
    database.init_schema(conn)

    if args.list:
        total = conn.execute("SELECT COUNT(*) FROM chemical_reference").fetchone()[0]
        with_desc = conn.execute(
            "SELECT COUNT(*) FROM chemical_reference WHERE description IS NOT NULL").fetchone()[0]
        pub = conn.execute(
            "SELECT COUNT(*) FROM chemical_reference WHERE source='pubchem'").fetchone()[0]
        names = cr.collect_names(conn)
        log(f"{len(names)} distinct chemicals in the data.")
        log(f"cached rows: {total} ({pub} resolved via PubChem, "
            f"{with_desc} with a description).")
        conn.close()
        return 0

    summary = cr.enrich(conn, force=args.force, only=args.only,
                        limit=args.limit, log=log)
    conn.close()
    # Non-zero exit only if literally nothing could be resolved (e.g. offline).
    return 0 if summary["resolved"] or summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
