"""Hand-researched narratives for EPA-NPL contamination sites that otherwise
only have the auto-generated structured description (desc_source='generated').

The data lives in the sibling file ``contamination_narratives.json`` — a list of
records keyed by EPA id, each with:
  * narrative — a factual 3-6 sentence story (who caused it, what was dumped,
    when, how it was found, impact, cleanup). Written ONLY from the cited
    sources in `refs`. No fabricated dates/tonnages/health claims.
  * refs — the sources the narrative was drawn from (shown in the popup).

These are applied to the DB by app.data_loader.apply_curated_narratives()
(re-applied on every full loader run) and by the standalone enrich_narratives.py
script. To add coverage: append records to the JSON and re-run either one.

Accuracy rule: if a detail can't be verified in a real source, don't write it.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

_JSON_PATH = Path(__file__).with_name("contamination_narratives.json")


def _clean(s: str) -> str:
    # The researched text/URLs may carry HTML entities (e.g. &amp;); normalize.
    return html.unescape(s or "").strip()


def _load() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not _JSON_PATH.exists():
        return out
    try:
        records = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return out
    for r in records:
        epa_id = (r.get("epa_id") or "").strip()
        narrative = _clean(r.get("narrative"))
        if not epa_id or not narrative:
            continue
        refs = [{"label": _clean(x.get("label")), "url": _clean(x.get("url"))}
                for x in (r.get("refs") or []) if x.get("label")]
        out[epa_id] = {"narrative": narrative, "refs": refs}
    return out


# {epa_id: {"narrative": str, "refs": [{"label", "url"}]}}
FETCHED_NARRATIVES: dict[str, dict] = _load()
