"""PubChem-backed chemical reference.

Real, plain-language chemical information (description, molecular formula/weight,
CAS, synonyms, PubChem CID) for every chemical/compound that appears in the app's
data — the USGS pesticide compounds, the EPA TRI chemicals, and the water-quality
detections. Results are cached in the ``chemical_reference`` table so the popups
read locally and instantly: no live API call on click, no latency, no rate-limit
risk.

Source: PubChem PUG REST (https://pubchem.ncbi.nlm.nih.gov/rest/pug), free, no key.
It complements — it does NOT replace — the EPA/IARC health & carcinogen
classification already carried on the TRI data and in ``tri_reference``.

Re-runnable and incremental: :func:`enrich` skips names already resolved unless
``force=True``, so new chemicals can be filled in later. Nothing is invented — a
name that can't be resolved keeps whatever we already have (name, CAS) and is
marked ``source='none'``.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from . import database

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
UA = {"User-Agent": "MichiganPollutionMap/1.0 (research; "
                    "+https://github.com/tbuttaflocka/michigan-pesticide-map)"}
REQ_DELAY_S = 0.22    # ~4.5 req/s — under PubChem's ~5/s guidance
TIMEOUT_S = 30        # PubChem's own per-request timeout

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _norm(name: str) -> str:
    return (name or "").strip().upper()


def _looks_like_cas(cas: str | None) -> bool:
    return bool(cas) and bool(_CAS_RE.match(cas.strip()))


# --------------------------------------------------------------------------- #
# PubChem HTTP (rate-limited, retry-once, graceful)                            #
# --------------------------------------------------------------------------- #
def _get_json(url: str, *, retries: int = 1):
    """GET a PubChem JSON endpoint. Returns the parsed object, or None for a
    genuine "not found" (HTTP 404 / PUGREST.NotFound). Retries once on transient
    errors (timeouts, 5xx, PubChem 503 "server busy"). Always spaces requests by
    REQ_DELAY_S first so a full batch stays within the rate limit."""
    for attempt in range(retries + 1):
        time.sleep(REQ_DELAY_S)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None            # not found — do not retry
            if attempt >= retries:
                return None
            time.sleep(0.6)            # busy / rate-limited — back off, retry once
        except Exception:
            if attempt >= retries:
                return None
            time.sleep(0.6)
    return None


def _cids_for_name(name: str) -> list[int] | None:
    d = _get_json(f"{PUBCHEM}/compound/name/{urllib.parse.quote(name)}/cids/JSON")
    if d and d.get("IdentifierList", {}).get("CID"):
        return d["IdentifierList"]["CID"]
    return None


def _cids_for_cas(cas: str) -> list[int] | None:
    d = _get_json(f"{PUBCHEM}/compound/xref/RegistryID/{urllib.parse.quote(cas)}/cids/JSON")
    if d and d.get("IdentifierList", {}).get("CID"):
        return d["IdentifierList"]["CID"]
    return None


def _name_variants(name: str) -> list[str]:
    """Fallback spellings for messy TRI/USGS names, in priority order."""
    n = " ".join((name or "").split())
    variants: list[str] = []

    def add(v: str) -> None:
        v = v.strip()
        if v and v not in variants:
            variants.append(v)

    add(n)
    add(n.lower())
    # Drop trailing parenthetical qualifiers, e.g. "Asbestos (friable)".
    no_paren = re.sub(r"\s*\([^)]*\)\s*$", "", n).strip()
    add(no_paren)
    add(no_paren.lower())
    # Category names like "Zinc compounds" / "Nitrate compounds" -> base element.
    base = re.sub(r"\s+and\s+compounds?$", "", no_paren, flags=re.I)
    base = re.sub(r"\s+compounds?$", "", base, flags=re.I).strip()
    add(base)
    add(base.lower())
    return variants


def resolve_cid(name: str, cas: str | None) -> tuple[int | None, str | None]:
    """Resolve a name to a PubChem CID, trying name variants first, then the CAS
    number if we have a real one. Returns (cid, matched_query) or (None, None)."""
    for v in _name_variants(name):
        cids = _cids_for_name(v)
        if cids:
            return cids[0], v
    if _looks_like_cas(cas):
        cids = _cids_for_cas(cas.strip())
        if cids:
            return cids[0], cas.strip()
    return None, None


def _properties(cid: int) -> dict:
    d = _get_json(f"{PUBCHEM}/compound/cid/{cid}/property/"
                  "MolecularFormula,MolecularWeight,IUPACName/JSON")
    try:
        return d["PropertyTable"]["Properties"][0] or {}
    except (TypeError, KeyError, IndexError):
        return {}


def _description(cid: int) -> tuple[str | None, str | None]:
    d = _get_json(f"{PUBCHEM}/compound/cid/{cid}/description/JSON")
    if not d:
        return None, None
    for info in d.get("InformationList", {}).get("Information", []):
        if info.get("Description"):
            return info["Description"].strip(), info.get("DescriptionSourceName")
    return None, None


def _fetch_synonyms(cid: int) -> list[str]:
    d = _get_json(f"{PUBCHEM}/compound/cid/{cid}/synonyms/JSON")
    try:
        return d["InformationList"]["Information"][0]["Synonym"] or []
    except (TypeError, KeyError, IndexError):
        return []


def _pick_synonyms(raw: list[str]) -> list[str]:
    picked: list[str] = []
    seen_lower: set[str] = set()
    for s in raw:
        s = s.strip()
        # Keep a few short, human-readable common names; skip CAS numbers, long
        # systematic strings, and registry codes (UNII/DTXSID/EC/EINECS etc.).
        if not s or _CAS_RE.match(s) or len(s) > 40:
            continue
        if re.search(r"\d{5,}", s):
            continue
        if re.fullmatch(r"[0-9A-Z\-]{6,}", s) and re.search(r"\d", s):
            continue          # e.g. "07PV14BK6X", "DTXSID9020049"
        if s.lower() in seen_lower:
            continue          # drop case-only duplicates (Deethylatrazine/DEETHYL…)
        seen_lower.add(s.lower())
        picked.append(s)
        if len(picked) >= 5:
            break
    return picked


def _cas_from_synonyms(raw: list[str]) -> str | None:
    for s in raw:
        if _CAS_RE.match(s.strip()):
            return s.strip()
    return None


# --------------------------------------------------------------------------- #
# Collect the names that actually appear in the data                          #
# --------------------------------------------------------------------------- #
def collect_names(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return {UPPER(name): {"name": display, "cas": cas|None}} across the
    pesticide, TRI, and water-quality tables (deduped by upper-cased name)."""
    names: dict[str, dict] = {}

    def add(display: str | None, cas: str | None = None) -> None:
        if not display:
            return
        key = _norm(display)
        entry = names.setdefault(key, {"name": display, "cas": None})
        if cas and not entry["cas"] and _looks_like_cas(cas):
            entry["cas"] = cas.strip()

    for (compound,) in conn.execute(
            "SELECT DISTINCT compound FROM pesticide_use WHERE compound IS NOT NULL"):
        add(compound)
    for chemical, cas in conn.execute(
            "SELECT DISTINCT chemical, cas FROM tri_release WHERE chemical IS NOT NULL"):
        add(chemical, cas)
    for (compound,) in conn.execute(
            "SELECT DISTINCT compound FROM water_quality_results WHERE compound IS NOT NULL"):
        add(compound)
    return names


def _upsert(conn: sqlite3.Connection, key: str, name: str, cas: str | None,
            cid: int | None, desc: str | None, dsrc: str | None,
            formula: str | None, weight: float | None, iupac: str | None,
            synonyms: list[str] | None, source: str) -> None:
    conn.execute(
        """INSERT INTO chemical_reference
             (name_key, name, cas, pubchem_cid, description, description_source,
              molecular_formula, molecular_weight, iupac_name, synonyms,
              source, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name_key) DO UPDATE SET
             name=excluded.name, cas=excluded.cas, pubchem_cid=excluded.pubchem_cid,
             description=excluded.description, description_source=excluded.description_source,
             molecular_formula=excluded.molecular_formula,
             molecular_weight=excluded.molecular_weight, iupac_name=excluded.iupac_name,
             synonyms=excluded.synonyms, source=excluded.source,
             fetched_at=excluded.fetched_at""",
        (key, name, cas, cid, desc, dsrc, formula,
         float(weight) if weight else None, iupac,
         json.dumps(synonyms) if synonyms else None, source, _now()))


def enrich(conn: sqlite3.Connection, *, force: bool = False,
           only: str | None = None, limit: int | None = None,
           log=print) -> dict:
    """Fetch PubChem data for every chemical name in the data and cache it.

    Incremental: names already resolved (source in 'pubchem'/'none') are skipped
    unless ``force``. Returns a small summary dict.
    """
    database.init_schema(conn)   # ensure the chemical_reference table exists
    names = collect_names(conn)
    if only:
        k = _norm(only)
        names = {kk: vv for kk, vv in names.items() if kk == k or only.lower() in kk.lower()}

    done_keys = {r["name_key"] for r in conn.execute(
        "SELECT name_key FROM chemical_reference WHERE source IN ('pubchem','none')")}
    todo = sorted(k for k in names if force or k not in done_keys)
    total = len(todo)
    log(f"[pubchem] {len(names)} distinct chemicals; {total} to enrich "
        f"({len(names) - total} already cached)")

    enriched = resolved = unresolved = errors = 0
    for i, key in enumerate(todo, 1):
        info = names[key]
        try:
            cid, matched = resolve_cid(info["name"], info["cas"])
            if cid:
                props = _properties(cid)
                desc, dsrc = _description(cid)
                raw_syn = _fetch_synonyms(cid)
                syns = _pick_synonyms(raw_syn)
                cas = info["cas"] or _cas_from_synonyms(raw_syn)
                _upsert(conn, key, info["name"], cas, cid, desc, dsrc,
                        props.get("MolecularFormula"), props.get("MolecularWeight"),
                        props.get("IUPACName"), syns, "pubchem")
                resolved += 1
            else:
                # Genuinely unresolvable — keep name + CAS, mark so we don't
                # re-hit it every run (still re-tried under --force).
                _upsert(conn, key, info["name"], info["cas"], None, None, None,
                        None, None, None, None, "none")
                unresolved += 1
            enriched += 1
        except Exception as e:              # never let one bad name break the run
            errors += 1
            log(f"  ! {info['name']}: {e}")
        if i % 10 == 0 or i == total:
            log(f"  Enriched {i} of {total} chemicals... "
                f"(resolved={resolved} unresolved={unresolved} err={errors})")
        conn.commit()
        if limit and i >= limit:
            log(f"  stopped at --limit {limit}")
            break

    with_desc = conn.execute(
        "SELECT COUNT(*) FROM chemical_reference WHERE description IS NOT NULL").fetchone()[0]
    total_rows = conn.execute("SELECT COUNT(*) FROM chemical_reference").fetchone()[0]
    _record_source(conn, total_rows, with_desc)
    conn.commit()
    log(f"[pubchem] done — {resolved} resolved, {unresolved} unresolved, "
        f"{errors} errors; {with_desc}/{total_rows} cached rows have a description")
    return {"resolved": resolved, "unresolved": unresolved,
            "errors": errors, "with_desc": with_desc, "total": total_rows}


def _record_source(conn: sqlite3.Connection, rows: int, with_desc: int) -> None:
    try:
        from .data_loader import record_source
        record_source(
            conn, "pubchem_chem",
            title="PubChem (NCBI) — chemical descriptions & properties",
            url="https://pubchem.ncbi.nlm.nih.gov/",
            status="ok" if rows else "unavailable",
            rows_loaded=rows,
            notes=(f"Cached descriptions, molecular formula/weight, CAS and "
                   f"synonyms for chemicals in the data; {with_desc} have a "
                   f"plain-language description."),
        )
    except Exception:
        pass


def load_chemical_reference(conn: sqlite3.Connection, log=print) -> None:
    """Loader entry point for refresh_data.py. Enriches only the new chemicals
    (incremental). If PubChem is unreachable the run degrades gracefully and the
    already-cached rows are preserved."""
    enrich(conn, log=log)
