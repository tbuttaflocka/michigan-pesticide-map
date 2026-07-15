"""enrich_narratives.py — fill real narratives for contamination sites that
otherwise only carry the auto-generated structured description.

Sources, in priority order:
  1. Curated hand-researched narratives in app/contamination_narratives.py
     (authoritative; drawn from EPA / EGLE / news — cited per entry).
  2. Wikipedia (only sites notable enough to have an article; validated to be
     the right Michigan Superfund site before use).
  Sites with nothing available are marked narrative_source='none' so the popup
  shows "No detailed public narrative found" instead of inventing a story.

Re-runnable and idempotent:
  * Curated narratives are (re)applied every run — add entries and re-run to
    fill gaps; a full `python -m app.data_loader` also re-applies them.
  * Web (Wikipedia) fetches are skipped for sites already attempted unless
    --force, and never override a curated narrative.

Usage:
  python enrich_narratives.py                 # apply curated + Wikipedia for the rest
  python enrich_narratives.py --no-web        # curated only (offline, deterministic)
  python enrich_narratives.py --only MID980499966   # one site (testing)
  python enrich_narratives.py --force         # re-attempt web fetches too
  python enrich_narratives.py --list          # show enrichment status, no changes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

from app import database
from app.data_loader import apply_curated_narratives
from app.contamination_narratives import FETCHED_NARRATIVES

UA = {"User-Agent": "MichiganPesticideMap/1.0 (research; contact via repo)"}
WIKI_DELAY_S = 1.1   # be polite to Wikipedia


def log(msg: str) -> None:
    print(msg, flush=True)


def _get(url: str, timeout: int = 20) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    except Exception:
        return None


def _sentences(text: str, n: int = 5, max_chars: int = 700) -> str:
    """First n sentences of a clean prose blob, capped at max_chars."""
    text = " ".join((text or "").split())
    out, count = [], 0
    for part in text.replace("! ", ". ").replace("? ", ". ").split(". "):
        part = part.strip()
        if not part:
            continue
        out.append(part)
        count += 1
        if count >= n or len(". ".join(out)) >= max_chars:
            break
    s = ". ".join(out).strip()
    if s and not s.endswith("."):
        s += "."
    return s


def wiki_narrative(name: str, city: str, county: str) -> tuple[str, str] | None:
    """Try to find a Wikipedia article for this Michigan Superfund site and
    return (narrative, page_url). Validated to avoid unrelated same-name pages."""
    for query in (f"{name} Superfund", name):
        js = _get("https://en.wikipedia.org/w/api.php?action=opensearch&limit=5&format=json"
                  f"&search={urllib.parse.quote(query)}")
        if not js:
            continue
        try:
            _, titles, _descs, urls = json.loads(js)
        except (ValueError, TypeError):
            continue
        for title, url in zip(titles, urls):
            summ = _get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                        + urllib.parse.quote(title.replace(" ", "_")))
            if not summ:
                continue
            try:
                d = json.loads(summ)
            except ValueError:
                continue
            extract = (d.get("extract") or "").strip()
            if len(extract) < 120:
                continue
            hay = extract.lower()
            # Must clearly be the right Michigan environmental site.
            ok = ("superfund" in hay or "national priorities list" in hay
                  or (("michigan" in hay or (county or "").lower() in hay)
                      and any(w in hay for w in ("contaminat", "landfill", "dump",
                                                 "waste", "groundwater", "pollut"))))
            if not ok:
                continue
            page_url = (d.get("content_urls", {}).get("desktop", {}).get("page")
                        or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}")
            return _sentences(extract), page_url
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich contamination-site narratives.")
    ap.add_argument("--only", metavar="EPA_ID", help="enrich a single site by EPA id")
    ap.add_argument("--force", action="store_true", help="re-attempt web fetches too")
    ap.add_argument("--no-web", action="store_true", help="curated narratives only")
    ap.add_argument("--list", action="store_true", help="show status, make no changes")
    args = ap.parse_args()

    conn = database.connect()
    database.init_schema(conn)   # ensure narrative columns exist

    if args.list:
        rows = conn.execute(
            "SELECT epa_id, site_name, narrative_source FROM contamination_sites "
            "WHERE desc_source='generated' ORDER BY hrs_score DESC NULLS LAST").fetchall()
        for r in rows:
            log(f"  {(r['narrative_source'] or '-'):9} {r['epa_id'] or '-':14} {r['site_name']}")
        fetched = sum(1 for r in rows if r["narrative_source"] == "fetched")
        log(f"\n{fetched}/{len(rows)} generated sites enriched.")
        conn.close()
        return 0

    # 1) Curated narratives (authoritative) — always (re)applied.
    applied = apply_curated_narratives(conn)
    log(f"[curated] applied {applied} researched narratives")

    # 2) Web enrichment for the remaining generated sites.
    rows = [dict(r) for r in conn.execute(
        "SELECT epa_id, site_name, city, county, narrative_source "
        "FROM contamination_sites WHERE desc_source='generated' "
        "ORDER BY hrs_score DESC NULLS LAST")]
    if args.only:
        rows = [r for r in rows if r["epa_id"] == args.only]
        if not rows:
            log(f"No generated site with EPA id {args.only}")
            conn.close()
            return 1

    # Never web-fetch a curated site; skip already-attempted unless --force.
    curated_ids = set(FETCHED_NARRATIVES)
    todo = [r for r in rows
            if r["epa_id"] not in curated_ids
            and (args.force or r["narrative_source"] not in ("fetched", "none"))]

    fetched = none = 0
    if args.no_web:
        log("[web] skipped (--no-web)")
    else:
        log(f"[web] attempting Wikipedia for {len(todo)} site(s)...")
        for i, r in enumerate(todo, 1):
            res = wiki_narrative(r["site_name"], r["city"], r["county"])
            time.sleep(WIKI_DELAY_S)
            if res:
                text, url = res
                conn.execute(
                    "UPDATE contamination_sites SET narrative=?, narrative_refs=?, "
                    "narrative_source='fetched' WHERE epa_id=?",
                    (text, json.dumps([{"label": "Wikipedia", "url": url}]), r["epa_id"]))
                fetched += 1
                log(f"  [{i}/{len(todo)}] Wikipedia ✓  {r['site_name']}")
            else:
                conn.execute(
                    "UPDATE contamination_sites SET narrative_source='none' "
                    "WHERE epa_id=? AND narrative IS NULL", (r["epa_id"],))
                none += 1
                log(f"  [{i}/{len(todo)}] no narrative  {r['site_name']}")
            conn.commit()

    # Total status
    total = conn.execute("SELECT COUNT(*) FROM contamination_sites WHERE desc_source='generated'").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM contamination_sites "
                        "WHERE desc_source='generated' AND narrative_source='fetched'").fetchone()[0]
    conn.close()
    log(f"\nDone. curated={applied} wikipedia={fetched} none={none} "
        f"| {done}/{total} generated sites now have a narrative.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
