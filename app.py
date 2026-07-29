"""Michigan Pesticide Application Heat Map — Flask backend.

Usage:
    python -m app.data_loader   # one-time, downloads and populates SQLite
    python app.py               # runs the web server on :8080
"""
from __future__ import annotations

import gzip
import json
import math
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from app import database
from app import cancer_data
from app.water_quality import to_ugl, mcl_for, benchmark_for, AQUATIC_BENCHMARK_SOURCE
from app import contamination_data
from app import landfill_data
from app import golf_data
from app import pfas_data
from app import airtoxics_data
from app import ust_data
from app import spraying_programs
from app import coal_ash_data
from app import tri_reference
from app import pfas_chem
from app.config import GEOJSON_PATH, HOST, PORT
from app.config import EPA_SITE_PROFILE
from app.config import MI_HUC8_GEOJSON_PATH
from app.respiratory_data import (
    GROWING_SEASON_MONTHS,
    ICD10_RESP_RANGES,
    MI_BROADER_RESP_BASELINE,
    MI_STATEWIDE_BASELINE,
    SEASONAL_PATTERN,
    URBAN_COUNTIES,
)
from app.stats import pearson, spearman, welch_t_test
from app.wind_data import (
    DIRS_16,
    deg_to_dir16,
    opposite_deg,
    haversine_mi,
    drift_fan,
    DRIFT_DISCLAIMER,
)


app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False


# ---------- security headers ----------
# Applied to every response. The Content-Security-Policy is scoped to exactly
# what the app loads: its own assets, the Leaflet/MarkerCluster/Heat libraries
# from unpkg, Chart.js from jsDelivr, and CARTO/OSM basemap tiles. There are no
# inline <script> blocks, so script-src stays strict (no 'unsafe-inline');
# style-src allows inline because Leaflet and the charts set element styles.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    "img-src 'self' data: https://*.basemaps.cartocdn.com https://*.cartocdn.com; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy",
                            "geolocation=(), microphone=(), camera=()")
    return resp


# Gzip compressible responses. The big win is the API GeoJSON — the PFAS feature
# collection (with 1,449 hexbin polygons) is a few MB of highly repetitive JSON
# that compresses ~85%. The dev server does not compress; a production proxy may,
# but doing it here means the payload shrinks regardless of how it is served.
_GZIP_MIN_BYTES = 1024
_GZIP_TYPES = ("application/json", "application/javascript",
               "text/css", "text/html", "text/plain", "image/svg+xml")


@app.after_request
def _gzip_response(resp):
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        return resp
    # Never touch streamed responses, already-encoded bodies, or non-2xx.
    if resp.direct_passthrough or not (200 <= resp.status_code < 300):
        return resp
    if resp.headers.get("Content-Encoding"):
        return resp
    ctype = (resp.content_type or "").split(";")[0].strip().lower()
    if ctype not in _GZIP_TYPES:
        return resp
    data = resp.get_data()
    if len(data) < _GZIP_MIN_BYTES:
        return resp
    resp.set_data(gzip.compress(data, 6))
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(resp.get_data()))
    resp.headers.add("Vary", "Accept-Encoding")
    return resp


# ---------- error handlers ----------
# Clean, generic responses so a public visitor never sees a stack trace or an
# internal path. JSON for /api/* callers, a small styled HTML page otherwise.
# (Flask already hides tracebacks with debug=False; these just make it tidy.)

def _wants_json() -> bool:
    return request.path.startswith("/api/")


def _error_response(code: int, title: str, message: str):
    if _wants_json():
        return jsonify({"error": title, "message": message, "status": code}), code
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{code} — {title}</title>"
        "<style>body{background:#0d1117;color:#e6edf3;font-family:-apple-system,"
        "Segoe UI,Roboto,Helvetica,Arial,sans-serif;display:flex;min-height:100vh;"
        "margin:0;align-items:center;justify-content:center;text-align:center}"
        ".box{max-width:460px;padding:24px}h1{font-size:52px;margin:0;color:#3fb950}"
        "p{color:#9aa4b2;line-height:1.5}a{color:#58a6ff}</style></head><body>"
        f"<div class='box'><h1>{code}</h1><p><strong>{title}.</strong> {message}</p>"
        "<p><a href='/'>← Back to the map</a></p></div></body></html>"
    )
    return html, code


@app.errorhandler(404)
def _handle_404(e):
    return _error_response(404, "Page not found",
                           "That address doesn't exist here.")


@app.errorhandler(500)
def _handle_500(e):
    return _error_response(500, "Something went wrong",
                           "An unexpected error occurred. Please try again.")


# ---------- units: kg -> lbs (single chokepoint) ----------
#
# The USGS source data and the SQLite DB store everything in kilograms.
# The public API serves pounds. Every JSON response is passed through
# `_to_lbs()` which (a) multiplies numeric values whose key looks like a
# kg quantity by 2.20462, and (b) renames the key to its *_lbs counterpart
# so downstream code never sees a "kg" label again.

KG_TO_LB = 2.20462

# Keys whose value is a kg amount that should be converted in place. We only
# accept *_kg-suffixed keys and the bare "kg" — generic names like "value",
# "mean", "x" appear in BOTH pesticide and respiratory endpoints with different
# units, so pesticide endpoints do their own explicit pre-conversion.
_KG_KEYS = {
    "kg",
    "total_kg",
    "epest_low_kg", "epest_high_kg",
    "total_pesticide_kg",
    "herbicide_kg", "insecticide_kg", "fungicide_kg",
    "mean_positive_kg", "mean_negative_kg",
}
_KG_VALUES_NO_RENAME: set[str] = set()


def _rename_kg(key: str) -> str:
    if key.endswith("_kg"):
        return key[:-3] + "_lbs"
    if key == "kg":
        return "lbs"
    return key


def _to_lbs(obj):
    """Walk a JSON-able structure converting kg quantities to lbs."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _KG_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                converted = v * KG_TO_LB
                out_k = k if k in _KG_VALUES_NO_RENAME else _rename_kg(k)
                out[out_k] = converted
            elif k.endswith("_kg") and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[_rename_kg(k)] = v * KG_TO_LB
            else:
                out[k] = _to_lbs(v)
        return out
    if isinstance(obj, list):
        return [_to_lbs(x) for x in obj]
    return obj


def lb_jsonify(payload):
    """jsonify() drop-in that converts kg -> lbs first."""
    return jsonify(_to_lbs(payload))


# ---------- DB helpers ----------

def db() -> sqlite3.Connection:
    return database.connect()


def category_filter_sql(category: str | None) -> tuple[str, list]:
    """Return SQL fragment + params restricting compounds to a category."""
    if not category or category == "all":
        return "", []
    return (
        "AND pu.compound IN (SELECT compound FROM pesticide_categories WHERE category = ?)",
        [category],
    )


def compound_filter_sql(compound: str | None) -> tuple[str, list]:
    if not compound:
        return "", []
    return "AND pu.compound = ?", [compound.upper()]


def estimate_column(estimate: str) -> str:
    """Map ?estimate=low|high|avg to a SELECT expression."""
    if estimate == "low":
        return "epest_low_kg"
    if estimate == "high":
        return "epest_high_kg"
    # average of low+high, treating NULLs gracefully
    return "(COALESCE(epest_low_kg, epest_high_kg) + COALESCE(epest_high_kg, epest_low_kg))/2.0"


# ---------- views ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/geojson")
def api_geojson():
    if not GEOJSON_PATH.exists():
        abort(503, "Michigan GeoJSON not loaded — run `python -m app.data_loader` first.")
    return send_from_directory(GEOJSON_PATH.parent, GEOJSON_PATH.name, mimetype="application/geo+json")


def _ccr_source(source_id, title, url, notes, rows=None):
    """One reference-source row for the coal-ash layer, shaped like a data_sources
    row so it renders in the Data Sources modal (no DB backing — curated)."""
    return {"source_id": source_id, "title": title, "url": url, "status": "reference",
            "rows_loaded": rows, "notes": notes, "last_updated": None,
            "coverage_start": None, "coverage_end": None, "refresh_status": None,
            "refresh_interval_months": None, "last_success": None, "last_attempt": None}


# Sources behind the "Coal ash sites" layer. The CCR rule is self-implementing —
# each utility posts its own data — so these are the authoritative rule pages plus
# the watchdog database; the per-utility CCR pages are linked from each popup.
_CCR_DATA_SOURCES = [
    _ccr_source(
        "coal_ash_directory",
        "Michigan coal ash (CCR) sites — curated directory",
        "https://www.epa.gov/coal-combustion-residuals",
        "Curated from EPA's 'List of Publicly Accessible Internet Sites Hosting CCR "
        "Compliance Data' (17 Michigan facilities), each operator's CCR page, and "
        "Earthjustice/EIP. Links to sources rather than aggregating live results.",
        rows=len(coal_ash_data.COAL_ASH_SITES)),
    _ccr_source(
        "epa_ccr_rule", "EPA — Coal Combustion Residuals (CCR) Rule",
        "https://www.epa.gov/coal-combustion-residuals/coal-ash-rule",
        "The federal rule requiring each utility to publicly post coal-ash "
        "groundwater monitoring, closure and structural-integrity data."),
    _ccr_source(
        "epa_ccr_legacy", "EPA — 2024 Legacy CCR Surface Impoundments Rule",
        "https://www.epa.gov/coal-combustion-residuals/final-rule-legacy-coal-combustion-residuals-surface-impoundments-and-ccr",
        "May 2024 rule extending CCR requirements to previously unregulated "
        "inactive/legacy impoundments and CCR management units."),
    _ccr_source(
        "egle_coal_ash", "Michigan EGLE — Coal Ash Facilities",
        "https://www.michigan.gov/egle/about/organization/materials-management/solid-waste/solid-waste-disposal-areas/coal-ash-facilities-license-review-process",
        "Michigan's state oversight of coal-ash disposal (Part 115; PA 640 of 2018)."),
    _ccr_source(
        "utility_ccr_pages", "Utility CCR compliance pages (DTE, Consumers Energy, LBWL, others)",
        "https://www.dteenergy.com/us/en/residential/community-and-news/environment/Coal-Combustion-Residual-Rule-Compliance-Data-and-Information.html",
        "Where the legally-required monitoring data actually lives — each operator "
        "hosts its own. Direct links are in each coal-ash site's popup."),
    _ccr_source(
        "eip_ashtracker", "Environmental Integrity Project / Earthjustice — Ashtracker",
        "https://ashtracker.org/",
        "Watchdog database of CCR groundwater-monitoring results compiled from "
        "utilities' own disclosures. Basis for the contaminant findings shown "
        "(attributed; disputed by the utilities). Michigan feature: "
        "earthjustice.org/feature/coal-ash-states/michigan"),
]


def _annotate_source_freshness(sources: list[dict]) -> None:
    """Add a `stale` flag and `age_days` to each data_sources row in place.

    A source is stale when it has an expected refresh interval and its last
    successful refresh is older than that interval plus a 25% grace period
    (so a 12-month/annual source flags at ~15 months, matching the app spec).
    Sources without an interval (reference/skipped rows) are never stale.
    """
    now = datetime.now(timezone.utc)
    for s in sources:
        s["stale"] = False
        s["age_days"] = None
        interval = s.get("refresh_interval_months")
        last = s.get("last_success")
        if not interval or not last:
            continue
        try:
            ts = datetime.fromisoformat(last)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age_days = (now - ts).days
        s["age_days"] = age_days
        s["stale"] = age_days > interval * 30.44 * 1.25


@app.route("/api/meta")
def api_meta():
    """Bootstrap data the frontend needs on first load."""
    conn = db()
    cur = conn.cursor()
    years = [r[0] for r in cur.execute(
        "SELECT DISTINCT year FROM pesticide_use ORDER BY year"
    )]
    categories = [r[0] for r in cur.execute(
        "SELECT DISTINCT category FROM pesticide_categories ORDER BY category"
    )]
    compounds = [r[0] for r in cur.execute(
        "SELECT DISTINCT compound FROM pesticide_use ORDER BY compound"
    )]
    counties = [
        {"fips": r["fips"], "name": r["name"]}
        for r in cur.execute("SELECT fips, name FROM counties ORDER BY name")
    ]
    sources = [dict(r) for r in cur.execute(
        "SELECT source_id, title, url, status, rows_loaded, notes, last_updated, "
        "coverage_start, coverage_end, refresh_status, refresh_interval_months, "
        "last_success, last_attempt FROM data_sources"
    )]
    conn.close()
    sources.extend(_CCR_DATA_SOURCES)   # curated coal-ash reference sources
    _annotate_source_freshness(sources)
    data_current_as_of = max(
        (s["last_success"] for s in sources if s.get("last_success")),
        default=None,
    )
    featured = [
        "GLYPHOSATE", "ATRAZINE", "2,4-D", "METOLACHLOR", "CHLORPYRIFOS",
        "DICAMBA", "ACETOCHLOR", "IMIDACLOPRID", "MESOTRIONE",
    ]
    cancer_types = [
        {"key": c["key"], "label": c["label"],
         "pesticide_link": c["pesticide_link"], "sex": c["sex"],
         "has_late_stage": c.get("has_late_stage", False),
         "default": c.get("default", False)}
        for c in cancer_data.CANCER_TYPES
    ]
    return lb_jsonify({
        "years": years,
        "categories": categories,
        "compounds": compounds,
        "featured_compounds": [c for c in featured if c in compounds],
        "counties": counties,
        "data_sources": sources,
        "data_current_as_of": data_current_as_of,
        "cancer_types": cancer_types,
        "cancer_default": cancer_data.DEFAULT_CANCER,
    })


# Below this many acres of surveyed cropland, "lbs per cropland acre" is not
# meaningful (non-agricultural counties, or ones where the 5 surveyed crops are
# a tiny slice), so those counties are left uncolored instead of showing a wild
# ratio from dividing by a near-zero denominator.
MIN_CROPLAND_ACRES = 10_000


def _cropland_acres_by_fips(conn) -> dict:
    """{county_fips: harvested cropland acres}. For each county, take EACH crop's
    most recent reported acreage and sum them (so a county isn't undercounted
    just because one crop didn't report in its latest overall year). Denominator
    for the 'lbs per cropland acre' normalization; {} when no NASS data loaded."""
    rows = conn.execute("""
        WITH latest AS (
            SELECT county_fips, crop, MAX(year) AS y
              FROM crop_acreage WHERE acres_harvested IS NOT NULL
             GROUP BY county_fips, crop
        )
        SELECT ca.county_fips AS f, SUM(ca.acres_harvested) AS acres
          FROM crop_acreage ca
          JOIN latest l ON l.county_fips = ca.county_fips
                       AND l.crop = ca.crop AND l.y = ca.year
         GROUP BY ca.county_fips
    """).fetchall()
    return {r["f"]: r["acres"] for r in rows if r["acres"]}


@app.route("/api/choropleth")
def api_choropleth():
    """Per-county totals for the current map filters.

    Query params:
        year      — single year (default: latest)
        category  — herbicide | insecticide | fungicide | growth_regulator | other | all
        compound  — specific compound name (case-insensitive)
        estimate  — low | high | avg (default avg)
        normalize — total | per_sq_mile | per_acre  (default total)
                    per_acre = lbs per acre of harvested cropland (needs NASS data)
    """
    year = request.args.get("year", type=int)
    category = request.args.get("category", "all")
    compound = request.args.get("compound")
    estimate = request.args.get("estimate", "avg")
    normalize = request.args.get("normalize", "total")

    conn = db()
    cur = conn.cursor()
    if year is None:
        row = cur.execute("SELECT MAX(year) FROM pesticide_use").fetchone()
        year = row[0]
        if year is None:
            return lb_jsonify({"year": None, "counties": [], "stats": {}})

    col = estimate_column(estimate)
    cat_sql, cat_p = category_filter_sql(category)
    cmp_sql, cmp_p = compound_filter_sql(compound)

    q = f"""
        SELECT c.fips, c.name, c.area_sq_miles,
               COALESCE(SUM({col}), 0) AS total_kg,
               COUNT(DISTINCT pu.compound) AS compound_count
          FROM counties c
     LEFT JOIN pesticide_use pu
            ON pu.county_fips = c.fips AND pu.year = ?
                 {cat_sql} {cmp_sql}
         GROUP BY c.fips, c.name, c.area_sq_miles
         ORDER BY c.name
    """
    rows = cur.execute(q, [year, *cat_p, *cmp_p]).fetchall()
    cropland = _cropland_acres_by_fips(conn) if normalize == "per_acre" else {}
    conn.close()

    counties = []
    for r in rows:
        total = r["total_kg"] or 0.0
        acres = cropland.get(r["fips"])
        if normalize == "per_sq_mile" and r["area_sq_miles"]:
            value = total / r["area_sq_miles"]
        elif normalize == "per_acre":
            # Undefined where a county has little/no surveyed cropland (urban or
            # non-row-crop counties) — leave it uncolored rather than showing a
            # wild ratio from a near-zero denominator.
            value = (total / acres) if (acres and acres >= MIN_CROPLAND_ACRES) else 0.0
        else:
            value = total
        # Pre-convert the generic "value" key to lbs here; lb_jsonify only
        # converts *_kg keys to keep respiratory endpoints' generic
        # "value"/"rate" keys safe.
        counties.append({
            "fips": r["fips"],
            "name": r["name"],
            "total_kg": total,           # walker renames to total_lbs
            "value": value * KG_TO_LB,   # already in lbs
            "compound_count": r["compound_count"],
            "area_sq_miles": r["area_sq_miles"],
            "cropland_acres": acres,
        })
    values = [c["value"] for c in counties if c["value"] > 0]
    stats = {
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
        "mean": (sum(values)/len(values)) if values else 0,
        "non_zero_counties": len(values),
        "total_counties": len(counties),
    }
    return lb_jsonify({
        "year": year,
        "category": category,
        "compound": compound,
        "estimate": estimate,
        "normalize": normalize,
        "counties": counties,
        "stats": stats,
    })


@app.route("/api/county/<fips>")
def api_county(fips: str):
    """Detail panel for a single county."""
    year = request.args.get("year", type=int)
    estimate = request.args.get("estimate", "avg")
    col = estimate_column(estimate)

    conn = db()
    cur = conn.cursor()
    county = cur.execute(
        "SELECT * FROM counties WHERE fips = ?", (fips,)
    ).fetchone()
    if not county:
        conn.close()
        abort(404, "Unknown county FIPS")

    if year is None:
        year = cur.execute(
            "SELECT MAX(year) FROM pesticide_use WHERE county_fips = ?",
            (fips,),
        ).fetchone()[0]

    # All compounds applied in this county/year (sorted high→low). The panel
    # charts the top 10 and offers a "show all" list for the full set.
    top_compounds = cur.execute(f"""
        SELECT pu.compound, pc.category, {col} AS kg
          FROM pesticide_use pu
     LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
         WHERE pu.county_fips = ? AND pu.year = ? AND {col} > 0
         ORDER BY kg DESC NULLS LAST
    """, (fips, year)).fetchall()

    by_category = cur.execute(f"""
        SELECT COALESCE(pc.category, 'other') AS category,
               SUM({col}) AS kg
          FROM pesticide_use pu
     LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
         WHERE pu.county_fips = ? AND pu.year = ?
         GROUP BY category
         ORDER BY kg DESC NULLS LAST
    """, (fips, year)).fetchall()

    trend = cur.execute(f"""
        SELECT year, SUM({col}) AS kg
          FROM pesticide_use
         WHERE county_fips = ?
         GROUP BY year
         ORDER BY year
    """, (fips,)).fetchall()

    crops = cur.execute("""
        SELECT crop, year, acres_harvested
          FROM crop_acreage
         WHERE county_fips = ?
         ORDER BY year DESC, acres_harvested DESC NULLS LAST
         LIMIT 20
    """, (fips,)).fetchall()

    total_kg = cur.execute(f"""
        SELECT SUM({col}) FROM pesticide_use
         WHERE county_fips = ? AND year = ?
    """, (fips, year)).fetchone()[0] or 0

    # Respiratory: one row per metric — value + units + comparison to state.
    metrics_order = [
        # (key, table, col, cond_col, cond_val, label, units, state_mean_key)
        ("asthma_ed",            "respiratory_ed_visits",        "visit_rate", "condition", "asthma",
         "Asthma — ED",          "per 10,000",         "asthma_ed_visit_rate"),
        ("asthma_hosp",          "respiratory_hospitalizations", "hosp_rate",  "condition", "asthma",
         "Asthma — Hospitalizations", "per 10,000",   "adult_asthma_hospitalization_rate"),
        ("copd_ed",              "respiratory_ed_visits",        "visit_rate", "condition", "copd",
         "COPD — ED",            "per 10,000",         "copd_ed_visit_rate"),
        ("copd_hosp",            "respiratory_hospitalizations", "hosp_rate",  "condition", "copd",
         "COPD — Hospitalizations", "per 10,000",      "copd_hospitalization_rate"),
        ("upper_respiratory",    "respiratory_ed_visits",        "visit_rate", "condition", "upper_respiratory",
         "Upper Respiratory — ED",  "per 10,000",      None),
        ("acute_bronchitis",     "respiratory_ed_visits",        "visit_rate", "condition", "acute_bronchitis",
         "Acute Bronchitis — ED",   "per 10,000",      None),
        ("pneumonia_influenza",  "respiratory_ed_visits",        "visit_rate", "condition", "pneumonia_influenza",
         "Pneumonia & Influenza — ED", "per 10,000",   None),
        ("all_respiratory_mort", "respiratory_mortality",        "death_rate", "cause",     "all_respiratory",
         "All Respiratory — Mortality", "deaths /100k", None),
    ]
    state_means = {
        "asthma_ed":   MI_STATEWIDE_BASELINE["asthma_ed_visit_rate"],
        "asthma_hosp": MI_STATEWIDE_BASELINE["adult_asthma_hospitalization_rate"],
        "copd_ed":     MI_STATEWIDE_BASELINE["copd_ed_visit_rate"],
        "copd_hosp":   MI_STATEWIDE_BASELINE["copd_hospitalization_rate"],
        # broader categories: the statewide value IS the baseline, so any
        # county-level deviation would always read 0% — skip the compare arrow.
    }
    resp_metrics = []
    for key, table, col, cond_col, cond_val, label, units, _ in metrics_order:
        row = cur.execute(
            f"SELECT {col} AS v, year, source FROM {table} "
            f" WHERE county_fips = ? AND {cond_col} = ? "
            f" ORDER BY year DESC LIMIT 1",
            (fips, cond_val),
        ).fetchone()
        value = row["v"] if row else None
        src = row["source"] if row else None
        state_mean = state_means.get(key)
        pct = None
        if value is not None and state_mean:
            pct = (value - state_mean) / state_mean * 100.0
        resp_metrics.append({
            "key": key, "label": label, "units": units,
            "value": value, "year": row["year"] if row else None,
            "source": src,
            "state_mean": state_mean,
            "pct_vs_state": pct,
            "is_baseline_only": src == "MDHHS_state_baseline",
        })

    ca = cur.execute(
        "SELECT is_urban, asthma_prevalence_pct FROM correlation_analysis "
        "WHERE county_fips = ?", (fips,)).fetchone()
    is_urban = bool(ca["is_urban"]) if ca else False
    asthma_prev = ca["asthma_prevalence_pct"] if ca else None
    state_prev = MI_STATEWIDE_BASELINE["adult_asthma_prevalence_pct"]
    resp = {
        "metrics": resp_metrics,
        "is_urban": is_urban,
        "asthma_prevalence_pct": asthma_prev,
        "asthma_prevalence_state_mean": state_prev,
    }

    cancer_card = _cancer_county_card(conn, fips)

    contam = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status_class='npl' THEN 1 ELSE 0 END) AS npl,
                  MAX(hrs_score) AS max_hrs
             FROM contamination_sites WHERE county_fips = ?""", (fips,)).fetchone()
    contam_sites = conn.execute(
        """SELECT site_name, company, status_class, hrs_score, category
             FROM contamination_sites WHERE county_fips = ?
            ORDER BY hrs_score DESC NULLS LAST, site_name LIMIT 12""", (fips,)).fetchall()
    contamination = {
        "total": contam["total"] or 0,
        "npl": contam["npl"] or 0,
        "max_hrs": contam["max_hrs"],
        "sites": [dict(s) for s in contam_sites],
    }

    lf = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN category='hazardous' THEN 1 ELSE 0 END) AS hazardous
             FROM landfill_sites WHERE county_fips = ?""", (fips,)).fetchone()
    lf_sites = conn.execute(
        """SELECT name, operator, category, type_label, status_class, tri_total_lbs
             FROM landfill_sites WHERE county_fips = ?
            ORDER BY (category='hazardous') DESC, name LIMIT 12""", (fips,)).fetchall()
    landfills = {
        "total": lf["total"] or 0,
        "hazardous": lf["hazardous"] or 0,
        "sites": [dict(s) for s in lf_sites],
    }

    conn.close()
    return lb_jsonify({
        "fips": fips,
        "name": county["name"],
        "area_sq_miles": county["area_sq_miles"],
        "year": year,
        "total_kg": total_kg,
        "kg_per_sq_mile": (total_kg / county["area_sq_miles"]) if county["area_sq_miles"] else None,
        "top_compounds": [dict(r) for r in top_compounds],
        "by_category": [dict(r) for r in by_category],
        "trend": [{"year": r["year"], "kg": r["kg"] or 0} for r in trend],
        "crops": [dict(r) for r in crops],
        "respiratory": resp,
        "cancer": cancer_card,
        "contamination": contamination,
        "landfills": landfills,
        "mdard_inspector_url":
            "https://www.michigan.gov/en/mdard/plant-pest/Pesticides/Pesticide-Regulatory-Info",
    })


@app.route("/api/statewide")
def api_statewide():
    """Statewide top-N panels and overall trend."""
    year = request.args.get("year", type=int)
    estimate = request.args.get("estimate", "avg")
    col = estimate_column(estimate)

    conn = db()
    cur = conn.cursor()
    if year is None:
        year = cur.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]

    top_counties = cur.execute(f"""
        SELECT c.fips, c.name, SUM({col}) AS kg
          FROM pesticide_use pu
          JOIN counties c ON c.fips = pu.county_fips
         WHERE pu.year = ?
         GROUP BY c.fips, c.name
         ORDER BY kg DESC NULLS LAST
         LIMIT 10
    """, (year,)).fetchall()

    top_compounds = cur.execute(f"""
        SELECT pu.compound, COALESCE(pc.category, 'other') AS category,
               SUM({col}) AS kg
          FROM pesticide_use pu
     LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
         WHERE pu.year = ?
         GROUP BY pu.compound, pc.category
         ORDER BY kg DESC NULLS LAST
         LIMIT 10
    """, (year,)).fetchall()

    trend = cur.execute(f"""
        SELECT year, SUM({col}) AS kg
          FROM pesticide_use
         GROUP BY year
         ORDER BY year
    """).fetchall()

    by_category = cur.execute(f"""
        SELECT COALESCE(pc.category, 'other') AS category,
               SUM({col}) AS kg
          FROM pesticide_use pu
     LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
         WHERE pu.year = ?
         GROUP BY category
         ORDER BY kg DESC NULLS LAST
    """, (year,)).fetchall()

    total = cur.execute(
        f"SELECT SUM({col}) FROM pesticide_use WHERE year = ?", (year,)
    ).fetchone()[0] or 0
    distinct_compounds = cur.execute(
        "SELECT COUNT(DISTINCT compound) FROM pesticide_use WHERE year = ?",
        (year,),
    ).fetchone()[0]

    conn.close()
    return lb_jsonify({
        "year": year,
        "estimate": estimate,
        "total_kg": total,
        "distinct_compounds": distinct_compounds,
        "top_counties": [dict(r) for r in top_counties],
        "top_compounds": [dict(r) for r in top_compounds],
        "trend": [{"year": r["year"], "kg": r["kg"] or 0} for r in trend],
        "by_category": [dict(r) for r in by_category],
    })


def _ov_scalar(cur, sql, params=(), default=None):
    """Run a scalar query, tolerating a missing table/column (older DB) by
    returning `default` — so the overview never 500s on a partial database."""
    try:
        row = cur.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return default
    return row[0] if row and row[0] is not None else default


def _ov_row(cur, sql, params=()):
    try:
        return cur.execute(sql, params).fetchone()
    except sqlite3.OperationalError:
        return None


def _compact_lbs(n) -> str | None:
    """Compact pounds label matching the app's fmtLbs style (37.9M lbs)."""
    if n is None:
        return None
    n = float(n)
    if abs(n) >= 1e9:
        return f"{n/1e9:.1f}B lbs"
    if abs(n) >= 1e6:
        return f"{n/1e6:.1f}M lbs"
    if abs(n) >= 1e3:
        return f"{n/1e3:.1f}K lbs"
    return f"{n:,.0f} lbs"


@app.route("/api/overview")
def api_overview():
    """Statewide snapshot across EVERY pollution layer the app tracks — computed
    live from the loaded data so the headline counts never go stale or contradict
    the layers. Powers the statewide overview grid + a few honest cross-layer
    callouts. Year-independent (except the pesticide/TRI snapshots, which use the
    latest available year and say so)."""
    conn = db()
    cur = conn.cursor()

    tri_year = _tri_latest_year(conn)
    tri_ct = _ov_scalar(cur, "SELECT COUNT(*) FROM tri_facility", (), 0)
    tri_lbs = _ov_scalar(cur, "SELECT SUM(total_lbs) FROM tri_release WHERE year = ?",
                         (tri_year,), 0) if tri_year else 0

    contam_ct = _ov_scalar(cur, "SELECT COUNT(*) FROM contamination_sites", (), 0)
    ust_open = _ov_scalar(cur, "SELECT COUNT(*) FROM ust_sites WHERE category='leaking_open'", (), 0)
    landfill_ct = _ov_scalar(cur, "SELECT COUNT(*) FROM landfill_sites", (), 0)
    pfas_ct = _ov_scalar(cur, "SELECT COUNT(*) FROM pfas_features WHERE kind IN ('site','aoi')", (), 0)
    golf_ct = _ov_scalar(cur, "SELECT COUNT(*) FROM golf_courses", (), 0)
    coal_ct = len(coal_ash_data.COAL_ASH_SITES)

    water_ct = _ov_scalar(cur, "SELECT COUNT(*) FROM water_quality_sites", (), 0)
    water_det = _ov_scalar(cur, "SELECT COUNT(DISTINCT site_id) FROM water_quality_results WHERE detected=1", (), 0)
    water_exc = _ov_scalar(cur, "SELECT COUNT(DISTINCT site_id) FROM water_quality_results WHERE exceeds_mcl=1", (), 0)

    atx_avg = _ov_scalar(cur, "SELECT value FROM airtoxics_stats WHERE key='mi_avg'")
    atx_top = _ov_row(cur, "SELECT total_risk, county_name FROM airtoxics_tracts "
                           "ORDER BY total_risk DESC LIMIT 1")

    col = estimate_column("avg")
    pest_year = _ov_scalar(cur, "SELECT MAX(year) FROM pesticide_use")
    pest_kg = _ov_scalar(cur, f"SELECT SUM({col}) FROM pesticide_use WHERE year = ?",
                         (pest_year,), 0) if pest_year else 0
    pest_lbs = (pest_kg or 0) * KG_TO_LB

    def _num(n):
        return f"{int(n):,}" if n is not None else "—"

    def _compact(n):
        if n is None:
            return "—"
        n = float(n)
        if abs(n) >= 1e6:
            return f"{n/1e6:.1f}M"
        if abs(n) >= 1e4:
            return f"{n/1e3:.0f}K"
        return f"{int(round(n)):,}"

    def card(key, value, value_display, label, sub, tip, action, undercount=None, year=None):
        return {"key": key, "value": value, "value_display": value_display,
                "label": label, "sub": sub, "tip": tip, "action": action,
                "undercount": undercount, "year": year}

    totals = [
        card("pesticides", round(pest_lbs), _compact(pest_lbs),
             "lbs pesticide applied", (str(pest_year) if pest_year else None),
             "Agricultural pesticide applied statewide (USGS NAWQA EPest, latest year). "
             "A modeled estimate of crop-protection use only — excludes lawn, golf and aquatic use.",
             {"type": "choropleth", "value": "pesticide"}, year=pest_year),
        card("tri", tri_ct, _num(tri_ct), "TRI industrial facilities",
             (f"{_compact_lbs(tri_lbs)} released · {tri_year}" if tri_lbs else None),
             "Facilities that self-report toxic chemical releases under EPA's Toxics "
             "Release Inventory, and total pounds released on-site in the latest year.",
             {"type": "layer", "cb": "tri-sites"},
             undercount="Self-reported; small emitters and non-covered industries are excluded.",
             year=tri_year),
        card("contamination", contam_ct, _num(contam_ct), "Superfund / contamination sites", None,
             "Federal Superfund (NPL) sites plus compiled major contaminated sites (EPA SEMS + curated).",
             {"type": "layer", "cb": "contam-sites"},
             undercount="A curated subset, not every contaminated site in Michigan."),
        card("ust_open", ust_open, _num(ust_open), "leaking storage-tank sites (open releases)", None,
             "Underground storage tank sites with an OPEN confirmed release still under "
             "corrective action (EGLE Part 213). Excludes closed and merely-licensed tanks.",
             {"type": "layer", "cb": "ust-sites"},
             undercount="Regulated tanks only — unregistered residential/home heating-oil tanks are not included."),
        card("landfills", landfill_ct, _num(landfill_ct), "landfills & waste facilities", None,
             "Active/accepting licensed solid-waste landfills + disposal hazardous-waste "
             "facilities (Michigan EGLE Part 115 / Part 111).",
             {"type": "layer", "cb": "landfill-sites"},
             undercount="Active-only — closed/pre-regulation landfills are not in this layer."),
        card("pfas", pfas_ct, _num(pfas_ct), "PFAS sites & areas of interest", None,
             "Confirmed PFAS sites and areas of interest under investigation (Michigan MPART / EGLE).",
             {"type": "layer", "cb": "pfas-sites"},
             undercount="The PFAS list keeps growing as investigation continues."),
        card("coal_ash", coal_ct, _num(coal_ct), "coal ash (CCR) sites", None,
             "Michigan coal combustion residuals facilities (curated directory mirroring EPA's CCR list).",
             {"type": "layer", "cb": "coal-ash-sites"}),
        card("golf", golf_ct, _num(golf_ct), "golf courses", None,
             "Golf-course locations (OpenStreetMap) — an intensive-turf land use the "
             "agricultural pesticide layer excludes. Amounts applied are not public and never shown.",
             {"type": "layer", "cb": "golf-sites"}),
        card("water", water_ct, _num(water_ct), "water monitoring sites",
             (f"{water_det:,} with a detection · {water_exc:,} over an MCL" if water_ct else None),
             "Surface- and ground-water pesticide monitoring stations (USGS/EPA Water "
             "Quality Portal), and how many have any detection or an MCL exceedance.",
             {"type": "layer", "cb": "wq-sites"},
             undercount="Sampling is uneven — absence of detections can reflect a lack of sampling."),
        card("air_toxics", round(atx_avg, 1) if atx_avg is not None else None,
             (f"{atx_avg:.1f}" if atx_avg is not None else "—"),
             "avg air-toxics cancer risk (per million)",
             (f"highest tract {round(atx_top['total_risk'])} · {atx_top['county_name']} Co."
              if atx_top else None),
             "Modeled lifetime cancer risk from air toxics, chance-in-a-million, averaged "
             "over Michigan census tracts, with the single highest-risk tract (EPA AirToxScreen). "
             "A screening estimate, not measured risk at any address.",
             {"type": "choropleth", "value": "air_toxics"}),
    ]

    # ---- honest cross-layer callouts (factual, sourced; medium/standard labelled) ----
    notable = []
    r = _ov_row(cur, "SELECT co.name, COUNT(*) c FROM ust_sites u "
                     "JOIN counties co ON co.fips = u.county_fips "
                     "WHERE u.category='leaking_open' GROUP BY u.county_fips "
                     "ORDER BY c DESC LIMIT 1")
    if r:
        notable.append({
            "label": "Most open leaking-tank releases",
            "value": f"{r['name']} County — {r['c']:,}",
            "source": "Michigan EGLE RRD (Part 213)"})
    r = _ov_row(cur, "SELECT name, site_type, county, max_ppt FROM pfas_features "
                     "WHERE kind='surface_water' AND max_ppt IS NOT NULL "
                     "ORDER BY max_ppt DESC LIMIT 1")
    if r and r["max_ppt"]:
        wb = (r["site_type"] or "").strip()
        cty = f"{r['county']} Co." if r["county"] else None
        where = " · ".join(x for x in (wb or None, cty) if x) or "a monitored water body"
        notable.append({
            "label": "Highest PFAS in surface water",
            "value": f"{round(r['max_ppt']):,} ppt — {where}",
            "note": "single PFAS analyte in a surface-water sample — surface water, not drinking water",
            "source": "Michigan EGLE surface-water PFAS sampling"})
    if tri_year:
        r = _ov_row(cur, "SELECT f.facility_name, f.county, SUM(r.total_lbs) t "
                         "FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id "
                         "WHERE r.year = ? GROUP BY r.facility_id ORDER BY t DESC LIMIT 1",
                    (tri_year,))
        if r and r["t"]:
            loc = f" ({r['county']} Co.)" if r["county"] else ""
            notable.append({
                "label": f"Largest single TRI releaser ({tri_year})",
                "value": f"{r['facility_name']}{loc} — {_compact_lbs(r['t'])}",
                "source": "EPA Toxics Release Inventory (self-reported)"})

    conn.close()
    return jsonify({"totals": totals, "notable": notable,
                    "as_of_years": {"tri": tri_year, "pesticides": pest_year}})


_TREND_CATS = [
    ("herbicide", "Herbicides"),
    ("insecticide", "Insecticides"),
    ("fungicide", "Fungicides"),
    ("other", "Other"),
]
_TREND_TOP_N = 9   # top individual compounds; the rest fold into "All others"


@app.route("/api/trend")
def api_trend():
    """Year-over-year pesticide composition (pounds per year) for the statewide
    total or one county, split by category and by top individual compounds.

    Query params: fips (optional — statewide if omitted), estimate, category
    (optional — scopes the 'top compounds' set to that category).
    Returns years[], categories[] (4 stacked bands), compounds[] (top N + "All
    others"), total[], and a scope label.
    """
    fips = (request.args.get("fips") or "").strip()
    estimate = request.args.get("estimate", "avg")
    category = request.args.get("category", "all")
    col = estimate_column(estimate)

    conn = db()
    cur = conn.cursor()
    base_cond = ""
    base_params: list = []
    scope = "Statewide"
    if fips:
        row = cur.execute("SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
        if row:
            base_cond = "WHERE pu.county_fips = ?"
            base_params = [fips]
            scope = f"{row['name']} County"

    years = [r[0] for r in cur.execute(
        f"SELECT DISTINCT year FROM pesticide_use pu {base_cond} ORDER BY year",
        base_params)]
    yi = {y: i for i, y in enumerate(years)}
    n = len(years)

    def to_lbs(kg):
        return (kg or 0.0) * KG_TO_LB

    # --- per-year totals ---
    total = [0.0] * n
    for r in cur.execute(
        f"SELECT pu.year AS y, SUM({col}) AS kg FROM pesticide_use pu "
        f"{base_cond} GROUP BY pu.year", base_params):
        total[yi[r["y"]]] = to_lbs(r["kg"])

    # --- per-year by category (folding growth_regulator etc. into 'other') ---
    cat_series = {k: [0.0] * n for k, _ in _TREND_CATS}
    for r in cur.execute(
        f"""SELECT pu.year AS y, COALESCE(pc.category,'other') AS cat, SUM({col}) AS kg
              FROM pesticide_use pu
         LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
            {base_cond} GROUP BY pu.year, cat""", base_params):
        bucket = r["cat"] if r["cat"] in ("herbicide", "insecticide", "fungicide") else "other"
        cat_series[bucket][yi[r["y"]]] += to_lbs(r["kg"])
    categories = [{"key": k, "label": lbl,
                   "values": [round(v, 1) for v in cat_series[k]]}
                  for k, lbl in _TREND_CATS]

    # --- top individual compounds (optionally scoped to a category filter) ---
    valid_cat = {"herbicide", "insecticide", "fungicide"}
    if category in valid_cat:
        cat_cond = "AND COALESCE(pc.category,'other') = ?"
        cat_p = [category]
        ref_total = cat_series[category]
    elif category in ("other", "growth_regulator"):
        cat_cond = "AND COALESCE(pc.category,'other') NOT IN ('herbicide','insecticide','fungicide')"
        cat_p = []
        ref_total = cat_series["other"]
    else:
        cat_cond, cat_p, ref_total = "", [], total

    where_for_top = base_cond if base_cond else "WHERE 1=1"
    top = cur.execute(
        f"""SELECT pu.compound AS c, SUM({col}) AS kg
              FROM pesticide_use pu
         LEFT JOIN pesticide_categories pc ON pc.compound = pu.compound
            {where_for_top} {cat_cond}
             GROUP BY pu.compound ORDER BY kg DESC NULLS LAST LIMIT ?""",
        [*base_params, *cat_p, _TREND_TOP_N]).fetchall()
    top_names = [r["c"] for r in top]

    compounds = []
    if top_names:
        comp_series = {name: [0.0] * n for name in top_names}
        placeholders = ",".join("?" * len(top_names))
        comp_cond = f"pu.compound IN ({placeholders})"
        comp_params = list(top_names)
        if fips:
            comp_cond += " AND pu.county_fips = ?"
            comp_params.append(fips)
        for r in cur.execute(
            f"SELECT pu.year AS y, pu.compound AS c, SUM({col}) AS kg "
            f"FROM pesticide_use pu WHERE {comp_cond} GROUP BY pu.year, pu.compound",
            comp_params):
            comp_series[r["c"]][yi[r["y"]]] += to_lbs(r["kg"])
        compounds = [{"name": name.title(),
                      "values": [round(v, 1) for v in comp_series[name]]}
                     for name in top_names]
        others = [max(0.0, ref_total[i] - sum(comp_series[nm][i] for nm in top_names))
                  for i in range(n)]
        if any(v > 0 for v in others):
            compounds.append({"name": "All others",
                              "values": [round(v, 1) for v in others]})

    conn.close()
    return jsonify({
        "scope": scope,
        "fips": fips or None,
        "category_filter": category if category != "all" else None,
        "years": years,
        "total": [round(v, 1) for v in total],
        "categories": categories,
        "compounds": compounds,
    })


@app.route("/api/compound/<compound>")
def api_compound(compound: str):
    """Statewide trend for one compound, plus per-county breakdown for the latest year."""
    conn = db()
    cur = conn.cursor()
    compound = compound.upper()
    estimate = request.args.get("estimate", "avg")
    col = estimate_column(estimate)
    trend = cur.execute(f"""
        SELECT year, SUM({col}) AS kg
          FROM pesticide_use
         WHERE compound = ?
         GROUP BY year
         ORDER BY year
    """, (compound,)).fetchall()
    if not trend:
        conn.close()
        abort(404, "Unknown compound")
    latest = trend[-1]["year"]
    counties = cur.execute(f"""
        SELECT c.fips, c.name, {col} AS kg
          FROM pesticide_use pu
          JOIN counties c ON c.fips = pu.county_fips
         WHERE pu.compound = ? AND pu.year = ?
         ORDER BY kg DESC NULLS LAST
    """, (compound, latest)).fetchall()
    category = cur.execute(
        "SELECT category FROM pesticide_categories WHERE compound = ?",
        (compound,),
    ).fetchone()
    conn.close()
    return lb_jsonify({
        "compound": compound,
        "category": category["category"] if category else "other",
        "trend": [{"year": r["year"], "kg": r["kg"] or 0} for r in trend],
        "latest_year": latest,
        "counties": [dict(r) for r in counties],
    })


# Facility layers searchable by name. Each tuple:
#   (table, name_col, alt_name_col, id_col, county_col, layer, type_label)
# `layer` maps to the frontend's _FOCUS config so selecting a result flies to
# the site and opens its popup. UST is handled specially (its category picks the
# focus layer); coal-ash lives in a Python module, not the DB (handled below).
_FACILITY_TABLES = [
    ("tri_facility",        "facility_name", "parent_company", "facility_id", "county",
     "tri",           "TRI toxic-release facility"),
    ("contamination_sites", "site_name",     "company",        "site_key",    "county",
     "contamination", "Contamination / Superfund site"),
    ("landfill_sites",      "name",          "operator",       "site_key",    "county",
     "landfill",      "Landfill / waste facility"),
    ("pfas_features",       "name",          None,             "feature_key", "county",
     "pfas",          "PFAS site"),
]


def _table_exists(cur, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _search_places(cur, q: str, limit: int = 12) -> list[dict]:
    """Cities, villages, townships, CDPs and ZIP areas matching `q`, each with its
    type and parent county so the UI can disambiguate duplicate names."""
    if not _table_exists(cur, "places"):
        return []
    qu = q.upper()
    rows = cur.execute(
        """
        SELECT place_id, name, name_full, kind, county_fips, county_name, counties,
               lat, lng, min_lat, min_lng, max_lat, max_lng
          FROM places
         WHERE UPPER(name) LIKE :contains OR UPPER(name_full) LIKE :contains
         ORDER BY
           CASE WHEN UPPER(name) = :exact THEN 0
                WHEN UPPER(name) LIKE :starts THEN 1
                ELSE 2 END,
           CASE kind WHEN 'city' THEN 0 WHEN 'township' THEN 1
                     WHEN 'village' THEN 2 WHEN 'cdp' THEN 3 ELSE 4 END,
           length(name), name
         LIMIT :lim
        """,
        {"contains": f"%{qu}%", "exact": qu, "starts": f"{qu}%", "lim": limit},
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "place_id": r["place_id"],
            "name": r["name"],
            "name_full": r["name_full"],
            "kind": r["kind"],
            "county_fips": r["county_fips"],
            "county_name": r["county_name"],
            "counties": json.loads(r["counties"]) if r["counties"] else None,
            "lat": r["lat"], "lng": r["lng"],
            "bbox": [r["min_lat"], r["min_lng"], r["max_lat"], r["max_lng"]],
        })
    return out


def _search_facilities(cur, q: str, limit: int = 10) -> list[dict]:
    """Named sites across TRI, Superfund/contamination, landfills, PFAS, UST and
    coal ash — so people who heard about Wurtsmith, Velsicol, Wolverine or Wayne
    Disposal in the news can find them by name."""
    qu = q.upper()
    contains = f"%{qu}%"
    found: list[dict] = []

    def _rank(name: str) -> int:
        n = (name or "").upper()
        return 0 if n == qu else (1 if n.startswith(qu) else 2)

    for table, name_col, alt_col, id_col, county_col, layer, type_label in _FACILITY_TABLES:
        if not _table_exists(cur, table):
            continue
        where = f"UPPER({name_col}) LIKE ?"
        params = [contains]
        if alt_col:
            where += f" OR UPPER({alt_col}) LIKE ?"
            params.append(contains)
        sql = (f"SELECT {name_col} AS name, {id_col} AS id, {county_col} AS county, "
               f"latitude AS lat, longitude AS lng FROM {table} "
               f"WHERE ({where}) AND latitude IS NOT NULL LIMIT 6")
        for r in cur.execute(sql, params).fetchall():
            found.append({
                "name": r["name"], "id": r["id"], "county": r["county"],
                "lat": r["lat"], "lng": r["lng"],
                "layer": layer, "type_label": type_label,
            })

    # UST: category decides which focus layer (open leak vs other) to fly to.
    if _table_exists(cur, "ust_sites"):
        for r in cur.execute(
            "SELECT facility_name AS name, site_key AS id, county, latitude AS lat, "
            "longitude AS lng, category FROM ust_sites "
            "WHERE UPPER(facility_name) LIKE ? AND latitude IS NOT NULL LIMIT 6",
            (contains,),
        ).fetchall():
            found.append({
                "name": r["name"], "id": r["id"], "county": r["county"],
                "lat": r["lat"], "lng": r["lng"],
                "layer": "ust_open" if r["category"] == "leaking_open" else "ust_other",
                "type_label": "Storage-tank site",
            })

    # Coal ash lives in a curated Python module, not the DB.
    for s in coal_ash_data.COAL_ASH_SITES:
        nm = s.get("name", "")
        if qu in nm.upper():
            found.append({
                "name": nm, "id": None, "county": s.get("county"),
                "lat": s.get("lat"), "lng": s.get("lon"),
                "layer": "coal_ash", "type_label": "Coal ash (CCR) site",
            })

    found.sort(key=lambda f: (_rank(f["name"]), len(f["name"] or "")))
    # de-dupe identical name+layer collisions, keep first (best-ranked)
    seen = set()
    deduped = []
    for f in found:
        key = (f["name"], f["layer"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped[:limit]


@app.route("/api/search")
def api_search():
    """Free-text search over places, counties, facilities and chemicals.

    Grouped so a mixed result set stays readable: Places (city/village/township/
    CDP/ZIP, each with its parent county for disambiguation), Counties, Facilities
    (named sites across the overlays), and Chemicals (pesticide compounds).
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return lb_jsonify({"places": [], "counties": [],
                           "facilities": [], "compounds": []})
    like = f"%{q.upper()}%"
    conn = db()
    cur = conn.cursor()
    counties = [dict(r) for r in cur.execute(
        "SELECT fips, name FROM counties WHERE UPPER(name) LIKE ? ORDER BY name LIMIT 8",
        (like,),
    )]
    compounds = [r[0] for r in cur.execute(
        "SELECT DISTINCT compound FROM pesticide_use WHERE compound LIKE ? ORDER BY compound LIMIT 12",
        (like,),
    )]
    places = _search_places(cur, q)
    facilities = _search_facilities(cur, q)
    conn.close()
    return lb_jsonify({"places": places, "counties": counties,
                       "facilities": facilities, "compounds": compounds})


# ---------- Respiratory endpoints ----------

# Each tuple: (table, rate_col, cond_col, cond_value, label, units, is_county_level)
# cond_col is "condition" for ED/hosp tables but "cause" for the mortality table.
_RESP_METRICS = {
    "asthma_ed":            ("respiratory_ed_visits",        "visit_rate","condition","asthma",             "Asthma — ED Visits",                  "per 10,000 population (age-adjusted)", True),
    "asthma_hosp":          ("respiratory_hospitalizations", "hosp_rate", "condition","asthma",             "Asthma — Hospitalizations",           "per 10,000 population (age-adjusted)", True),
    "copd_ed":              ("respiratory_ed_visits",        "visit_rate","condition","copd",               "COPD — ED Visits",                    "per 10,000 population (age-adjusted)", True),
    "copd_hosp":            ("respiratory_hospitalizations", "hosp_rate", "condition","copd",               "COPD — Hospitalizations",             "per 10,000 population (age-adjusted)", True),
    "upper_respiratory":    ("respiratory_ed_visits",        "visit_rate","condition","upper_respiratory",  "Upper Respiratory Infections — ED",   "per 10,000 (MI statewide baseline)",   False),
    "acute_bronchitis":     ("respiratory_ed_visits",        "visit_rate","condition","acute_bronchitis",   "Acute Bronchitis — ED",               "per 10,000 (MI statewide baseline)",   False),
    "pneumonia_influenza":  ("respiratory_ed_visits",        "visit_rate","condition","pneumonia_influenza","Pneumonia & Influenza — ED",          "per 10,000 (MI statewide baseline)",   False),
    "all_respiratory_mort": ("respiratory_mortality",        "death_rate","cause",    "all_respiratory",    "All Respiratory Mortality (J00-J99)", "deaths per 100,000 (MI baseline)",     False),
    # synthetic combined metric (computed) — handled specially
    "combined":             (None, None, None, None,
                             "All Respiratory (combined)",
                             "average of available age-adjusted rates", True),
}


def _resp_choice(metric: str | None):
    return _RESP_METRICS.get(metric or "combined", _RESP_METRICS["combined"])


def _resp_meta(metric_key: str) -> dict:
    table, col, cond_col, cond_val, label, units, county_level = _RESP_METRICS.get(
        metric_key, _RESP_METRICS["combined"])
    return {
        "metric": metric_key, "label": label, "units": units,
        "county_level": county_level,
        "icd10": ICD10_RESP_RANGES.get(cond_val) if cond_val else None,
    }


@app.route("/api/respiratory/counties")
def api_respiratory_counties():
    """Latest-year rates per county for the chosen metric (choropleth source).

    ?metric = combined (default) | asthma_ed | asthma_hosp | copd_ed | copd_hosp
              | upper_respiratory | acute_bronchitis | pneumonia_influenza
              | all_respiratory_mort
    """
    metric = request.args.get("metric", "combined")
    meta = _resp_meta(metric)
    conn = db()
    cur = conn.cursor()

    # --- combined: average of the four real CDC measures ---
    if metric == "combined":
        rows = cur.execute("""
            SELECT c.fips, c.name,
                   ca.asthma_ed_rate, ca.asthma_hosp_rate,
                   ca.copd_ed_rate, ca.copd_hosp_rate,
                   ca.is_urban
              FROM counties c
         LEFT JOIN correlation_analysis ca ON ca.county_fips = c.fips
        """).fetchall()
        out = []
        for r in rows:
            vals = [r["asthma_ed_rate"], r["asthma_hosp_rate"],
                    r["copd_ed_rate"], r["copd_hosp_rate"]]
            present = [v for v in vals if v is not None]
            combined = sum(present) / len(present) if present else None
            out.append({
                "fips": r["fips"], "name": r["name"],
                "value": combined, "is_urban": bool(r["is_urban"]),
                "components": {
                    "asthma_ed_rate":   r["asthma_ed_rate"],
                    "asthma_hosp_rate": r["asthma_hosp_rate"],
                    "copd_ed_rate":     r["copd_ed_rate"],
                    "copd_hosp_rate":   r["copd_hosp_rate"],
                },
            })
        conn.close()
        return jsonify({**meta, "counties": out})

    # --- single-condition metric ---
    table, col, cond_col, cond_val, _, _, _ = _RESP_METRICS.get(
        metric, _RESP_METRICS["asthma_ed"])
    rows = cur.execute(f"""
        SELECT c.fips, c.name, ca.is_urban,
               (SELECT {col} FROM {table} t
                 WHERE t.county_fips = c.fips AND t.{cond_col} = ?
                 ORDER BY year DESC LIMIT 1) AS rate,
               (SELECT year FROM {table} t
                 WHERE t.county_fips = c.fips AND t.{cond_col} = ?
                 ORDER BY year DESC LIMIT 1) AS year,
               (SELECT source FROM {table} t
                 WHERE t.county_fips = c.fips AND t.{cond_col} = ?
                 ORDER BY year DESC LIMIT 1) AS source
          FROM counties c
     LEFT JOIN correlation_analysis ca ON ca.county_fips = c.fips
         ORDER BY c.name
    """, (cond_val, cond_val, cond_val)).fetchall()
    conn.close()
    return jsonify({
        **meta,
        "condition": cond_val,
        "counties": [
            {"fips": r["fips"], "name": r["name"], "value": r["rate"],
             "year": r["year"], "is_urban": bool(r["is_urban"]),
             "source": r["source"]}
            for r in rows
        ],
    })


@app.route("/api/respiratory/trends")
def api_respiratory_trends():
    """Yearly trend, statewide or for one county."""
    fips = request.args.get("fips")
    metric = request.args.get("metric", "combined")
    if metric == "combined":
        # average of the 4 real-data series
        conn = db()
        rows = []
        if fips:
            q = """SELECT year, AVG(rate) AS rate FROM (
                     SELECT year, visit_rate AS rate FROM respiratory_ed_visits
                      WHERE county_fips = ? AND condition IN ('asthma','copd')
                     UNION ALL
                     SELECT year, hosp_rate AS rate FROM respiratory_hospitalizations
                      WHERE county_fips = ? AND condition IN ('asthma','copd')
                   ) GROUP BY year ORDER BY year"""
            rows = conn.execute(q, (fips, fips)).fetchall()
        else:
            q = """SELECT year, AVG(rate) AS rate FROM (
                     SELECT year, visit_rate AS rate FROM respiratory_ed_visits
                      WHERE condition IN ('asthma','copd')
                     UNION ALL
                     SELECT year, hosp_rate AS rate FROM respiratory_hospitalizations
                      WHERE condition IN ('asthma','copd')
                   ) GROUP BY year ORDER BY year"""
            rows = conn.execute(q).fetchall()
        conn.close()
        return jsonify({"fips": fips, "metric": metric,
                        "trend": [{"year": r["year"], "rate": r["rate"]} for r in rows]})

    table, col, cond_col, cond_val, _, _, _ = _RESP_METRICS.get(
        metric, _RESP_METRICS["asthma_ed"])
    conn = db()
    if fips:
        rows = conn.execute(f"""
            SELECT year, {col} AS rate FROM {table}
             WHERE county_fips = ? AND {cond_col} = ?
             ORDER BY year
        """, (fips, cond_val)).fetchall()
    else:
        rows = conn.execute(f"""
            SELECT year, AVG({col}) AS rate FROM {table}
             WHERE {cond_col} = ?
             GROUP BY year ORDER BY year
        """, (cond_val,)).fetchall()
    conn.close()
    return jsonify({
        "fips": fips, "metric": metric, "condition": cond_val,
        "trend": [{"year": r["year"], "rate": r["rate"]} for r in rows],
    })


@app.route("/api/respiratory/seasonal")
def api_respiratory_seasonal():
    """Monthly seasonal pattern (statewide derived from MDHHS dashboard)."""
    return jsonify({
        "pattern": [
            {"month": m, "month_name": _MONTH_NAMES[m - 1], "index": SEASONAL_PATTERN[m]}
            for m in range(1, 13)
        ],
        "growing_season_months": GROWING_SEASON_MONTHS,
        "note": ("Asthma ED visits at the county level are reported only "
                 "annually. This monthly index is the statewide MDHHS "
                 "season-of-year average applied uniformly to provide a "
                 "seasonal overlay."),
    })


@app.route("/api/respiratory/baseline")
def api_respiratory_baseline():
    return jsonify({"state_baseline": MI_STATEWIDE_BASELINE})


_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------- Pesticide x Respiratory correlation endpoints ----------

_PEST_METRICS = {
    "total":       "total_pesticide_kg",
    "per_sq_mile": "pesticide_per_sq_mile",
    "herbicide":   "herbicide_kg",
    "insecticide": "insecticide_kg",
    "fungicide":   "fungicide_kg",
}
_RESP_CORR_COLS = {
    "asthma_ed":   "asthma_ed_rate",
    "asthma_hosp": "asthma_hosp_rate",
    "copd_ed":     "copd_ed_rate",
    "copd_hosp":   "copd_hosp_rate",
    "prevalence":  "asthma_prevalence_pct",
}


@app.route("/api/correlation/respiratory")
def api_correlation_respiratory():
    """Full joined table with respiratory rates and urban flag."""
    exclude_wayne = request.args.get("exclude_wayne") in ("1", "true", "yes")
    conn = db()
    rows = conn.execute("""
        SELECT county_fips, county, total_pesticide_kg, pesticide_per_sq_mile,
               herbicide_kg, insecticide_kg, fungicide_kg,
               is_urban, asthma_ed_rate, asthma_hosp_rate,
               copd_ed_rate, copd_hosp_rate, asthma_prevalence_pct
          FROM correlation_analysis
         ORDER BY total_pesticide_kg DESC NULLS LAST
    """).fetchall()
    conn.close()
    out = [dict(r) for r in rows]
    if exclude_wayne:
        out = [r for r in out if r["county"] != "Wayne"]
    return lb_jsonify({"rows": out, "exclude_wayne": exclude_wayne})


@app.route("/api/correlation/respiratory/scatter")
def api_correlation_respiratory_scatter():
    pest_metric = request.args.get("pest", "total")
    resp_metric = request.args.get("resp", "asthma_ed")
    exclude_wayne = request.args.get("exclude_wayne") in ("1", "true", "yes")
    px = _PEST_METRICS.get(pest_metric, "total_pesticide_kg")
    py = _RESP_CORR_COLS.get(resp_metric, "asthma_ed_rate")
    conn = db()
    rows = conn.execute(f"""
        SELECT county_fips, county, is_urban,
               {px} AS x, {py} AS y
          FROM correlation_analysis
    """).fetchall()
    conn.close()
    # Pre-convert x (kg → lbs) here; y is already a rate.
    pts = []
    for r in rows:
        pts.append({
            "county_fips": r["county_fips"], "county": r["county"],
            "is_urban": bool(r["is_urban"]),
            "x": r["x"] * KG_TO_LB if r["x"] is not None else None,
            "y": r["y"],
        })
    if exclude_wayne:
        pts = [r for r in pts if r["county"] != "Wayne"]
    valid = [(r["x"], r["y"]) for r in pts
             if r["x"] is not None and r["y"] is not None]
    xs = [v[0] for v in valid]
    ys = [v[1] for v in valid]
    fit = pearson(xs, ys)
    line = None
    if fit.get("slope") is not None and xs:
        xmin, xmax = min(xs), max(xs)
        line = [
            {"x": xmin, "y": fit["intercept"] + fit["slope"] * xmin},
            {"x": xmax, "y": fit["intercept"] + fit["slope"] * xmax},
        ]
    return jsonify({
        "pesticide_metric": pest_metric,
        "respiratory_metric": resp_metric,
        "exclude_wayne": exclude_wayne,
        "points": pts,
        "fit": fit,
        "trend_line": line,
    })


@app.route("/api/correlation/respiratory/seasonal")
def api_correlation_respiratory_seasonal():
    """Seasonal overlap chart data: monthly pesticide intensity (derived from
    the growing-season profile) vs the statewide respiratory seasonal index.

    Pesticide application data is annual at the county level. To get a
    monthly signal we use the published growing-season application pattern
    (most field applications occur April–September, with herbicide spike
    around April-May and fungicide/insecticide later)."""
    pest_pattern = {
        1: 0.02, 2: 0.02, 3: 0.05, 4: 0.18, 5: 0.20, 6: 0.13,
        7: 0.10, 8: 0.10, 9: 0.10, 10: 0.06, 11: 0.02, 12: 0.02,
    }
    return jsonify({
        "growing_season_months": GROWING_SEASON_MONTHS,
        "months": [
            {
                "month": m,
                "month_name": _MONTH_NAMES[m - 1],
                "pesticide_fraction": pest_pattern[m],
                "respiratory_index": SEASONAL_PATTERN[m],
            }
            for m in range(1, 13)
        ],
        "note": ("Pesticide monthly fractions are the typical Michigan "
                 "field-application calendar (USGS and MSU Extension); "
                 "respiratory indices are statewide MDHHS season-of-year "
                 "averages. Both are statewide reference patterns, not "
                 "measurements from these specific counties."),
    })


@app.route("/api/correlation/respiratory/stats")
def api_correlation_respiratory_stats():
    """Pearson + Spearman + top-quartile vs bottom-quartile comparison."""
    pest_metric = request.args.get("pest", "total")
    resp_metric = request.args.get("resp", "asthma_ed")
    exclude_wayne = request.args.get("exclude_wayne") in ("1", "true", "yes")
    urban_only   = request.args.get("urban_only") in ("1", "true", "yes")
    rural_only   = request.args.get("rural_only") in ("1", "true", "yes")
    px = _PEST_METRICS.get(pest_metric, "total_pesticide_kg")
    py = _RESP_CORR_COLS.get(resp_metric, "asthma_ed_rate")

    conn = db()
    rows = conn.execute(f"""
        SELECT county, is_urban, {px} AS x, {py} AS y
          FROM correlation_analysis
    """).fetchall()
    conn.close()

    # x is kg from the DB; convert to lbs so reported means match the chart axis.
    pts = [{"county": r["county"], "is_urban": r["is_urban"],
            "x": r["x"] * KG_TO_LB if r["x"] is not None else None,
            "y": r["y"]}
           for r in rows if r["x"] is not None and r["y"] is not None]
    if exclude_wayne:
        pts = [r for r in pts if r["county"] != "Wayne"]
    if urban_only:
        pts = [r for r in pts if r["is_urban"]]
    elif rural_only:
        pts = [r for r in pts if not r["is_urban"]]

    if not pts:
        return jsonify({
            "pearson": {"r": None, "n": 0},
            "spearman": {"rho": None, "n": 0},
            "quartile_comparison": None,
            "note": "Respiratory data is empty — CDC fetch may have failed.",
            "interpretation": "No respiratory data available to correlate.",
        })

    xs = [r["x"] for r in pts]
    ys = [r["y"] for r in pts]
    pear = pearson(xs, ys)
    spear = spearman(xs, ys)

    sorted_by_x = sorted(pts, key=lambda r: r["x"])
    q = max(1, len(sorted_by_x) // 4)
    bottom = [r["y"] for r in sorted_by_x[:q]]
    top    = [r["y"] for r in sorted_by_x[-q:]]
    t = welch_t_test(top, bottom)

    interp = _resp_interp(pear, spear, t, exclude_wayne, urban_only, rural_only)

    return jsonify({
        "pesticide_metric": pest_metric,
        "respiratory_metric": resp_metric,
        "exclude_wayne": exclude_wayne,
        "urban_only": urban_only, "rural_only": rural_only,
        "n": len(pts),
        "pearson": pear,
        "spearman": spear,
        "quartile_comparison": {
            "top_quartile_n": len(top), "bottom_quartile_n": len(bottom),
            "top_mean": t.get("mean_a"),     "bottom_mean": t.get("mean_b"),
            "welch_t_test": t,
        },
        "interpretation": interp,
    })


def _resp_interp(pear, spear, t, ex_wayne: bool, urban_only: bool, rural_only: bool) -> str:
    bits = []
    r = pear.get("r"); rho = spear.get("rho"); p = pear.get("p_value")
    if r is None:
        bits.append("Insufficient data for correlation analysis.")
    else:
        bits.append(
            f"Pearson r = {r:.2f} (p = {p:.3g}); Spearman ρ = {rho:.2f}. "
            f"R² = {pear['r2']:.2f}."
        )
    tp = t.get("p_value")
    if tp is not None:
        sig = "statistically significant" if tp < 0.05 else "not significant"
        bits.append(
            f"Top-quartile pesticide counties' mean respiratory rate = "
            f"{t['mean_a']:.1f} vs bottom-quartile = {t['mean_b']:.1f} "
            f"(Welch t = {t['t']:.2f}, p = {tp:.3g}, {sig} at α=0.05)."
        )
    flags = []
    if ex_wayne:    flags.append("Wayne County excluded")
    if urban_only:  flags.append("urban subset only")
    if rural_only:  flags.append("rural subset only")
    if flags:
        bits.append("Filters applied: " + ", ".join(flags) + ".")
    bits.append(
        "Reminder: rural and urban counties have fundamentally different "
        "respiratory risk profiles. Air quality, smoking rates, housing, "
        "industrial emissions, and occupational exposures dominate asthma "
        "and COPD outcomes — not agricultural pesticide application."
    )
    return " ".join(bits)


@app.route("/api/correlation/respiratory/rankings")
def api_correlation_respiratory_rankings():
    """For the comparison table: each county ranked by pesticide and by respiratory rate,
       flagged if it falls in the top 20 of both."""
    resp_metric = request.args.get("resp", "asthma_ed")
    py = _RESP_CORR_COLS.get(resp_metric, "asthma_ed_rate")
    conn = db()
    rows = conn.execute(f"""
        SELECT county_fips, county, is_urban,
               total_pesticide_kg AS pest_kg,
               {py} AS resp_rate,
               asthma_ed_rate, asthma_hosp_rate, copd_ed_rate, copd_hosp_rate
          FROM correlation_analysis
    """).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    by_pest = sorted([r for r in data if r["pest_kg"] is not None],
                     key=lambda r: -r["pest_kg"])
    by_resp = sorted([r for r in data if r["resp_rate"] is not None],
                     key=lambda r: -r["resp_rate"])
    for i, r in enumerate(by_pest, 1): r["rank_pest"] = i
    for i, r in enumerate(by_resp, 1): r["rank_resp"] = i
    # mark overlap (top 20 in both)
    top_pest = {r["county_fips"] for r in by_pest[:20]}
    top_resp = {r["county_fips"] for r in by_resp[:20]}
    overlap = top_pest & top_resp
    for r in data:
        r["overlap_top20"] = r["county_fips"] in overlap
    return lb_jsonify({
        "rows": sorted(data, key=lambda r: r.get("rank_pest") or 999),
        "overlap_count": len(overlap),
        "overlap_fips": sorted(overlap),
    })


# ---------- Water quality endpoints ----------

def _site_severity(detected: int, exceeds_mcl: int, total: int,
                   exceeds_benchmark: int = 0) -> str:
    """Worst-case severity for a site's marker. A drinking-water MCL violation
    (human-health) outranks an aquatic-life-benchmark exceedance (ecological),
    which outranks a plain detection — so the two standards stay visually
    distinct and an ecological exceedance never looks like a health violation."""
    if total == 0:
        return "no_data"
    if exceeds_mcl > 0:
        return "exceeds_mcl"
    if exceeds_benchmark > 0:
        return "exceeds_benchmark"
    if detected > 0:
        return "detected"
    return "tested_no_detect"


@app.route("/api/water/sites")
def api_water_sites():
    """Monitoring sites with detection counts.
    ?compound=ATRAZINE filters to sites where that compound was detected."""
    compound = (request.args.get("compound") or "").strip().upper()
    medium = (request.args.get("medium") or "").strip().lower()
    conn = db()
    cur = conn.cursor()

    cmp_join = ""
    cmp_args: list = []
    if compound:
        cmp_join = """
            AND EXISTS (
                SELECT 1 FROM water_quality_results r
                 WHERE r.site_id = s.site_id
                   AND r.compound = ? AND r.detected = 1
            )
        """
        cmp_args = [compound]

    med_clause = ""
    med_args: list = []
    if medium in ("water", "groundwater"):
        med_clause = "AND LOWER(r.medium) = ?"
        med_args = [medium]

    rows = cur.execute(f"""
        SELECT s.site_id, s.site_name, s.site_type, s.latitude, s.longitude,
               s.county, s.county_fips, s.huc8, s.organization, s.source,
               COUNT(r.id) AS samples,
               SUM(CASE WHEN r.detected = 1 THEN 1 ELSE 0 END) AS detections,
               SUM(CASE WHEN r.exceeds_mcl = 1 THEN 1 ELSE 0 END) AS exceedances,
               SUM(CASE WHEN r.exceeds_benchmark = 1 THEN 1 ELSE 0 END) AS benchmark_exceedances,
               COUNT(DISTINCT CASE WHEN r.detected = 1 THEN r.compound END) AS compounds
          FROM water_quality_sites s
     LEFT JOIN water_quality_results r ON r.site_id = s.site_id {med_clause}
         WHERE 1=1 {cmp_join}
         GROUP BY s.site_id
    """, (*med_args, *cmp_args)).fetchall()

    out = []
    for r in rows:
        sev = _site_severity(r["detections"] or 0, r["exceedances"] or 0,
                             r["samples"] or 0, r["benchmark_exceedances"] or 0)
        out.append({
            "site_id": r["site_id"], "site_name": r["site_name"],
            "site_type": r["site_type"],
            "latitude": r["latitude"], "longitude": r["longitude"],
            "county": r["county"], "county_fips": r["county_fips"],
            "huc8": r["huc8"], "organization": r["organization"],
            "source": r["source"],
            "samples": r["samples"], "detections": r["detections"],
            "exceedances": r["exceedances"],
            "benchmark_exceedances": r["benchmark_exceedances"],
            "compounds": r["compounds"],
            "severity": sev,
        })
    conn.close()
    return jsonify({"compound": compound or None, "medium": medium or None,
                    "sites": out})


@app.route("/api/water/site/<path:site_id>")
def api_water_site_detail(site_id: str):
    """Full sample-result detail for one site."""
    conn = db()
    cur = conn.cursor()
    site = cur.execute(
        "SELECT * FROM water_quality_sites WHERE site_id = ?", (site_id,)
    ).fetchone()
    if not site:
        conn.close()
        abort(404, "Unknown site")
    rows = cur.execute("""
        SELECT compound, MAX(sample_date) AS latest_date, COUNT(*) AS samples,
               SUM(CASE WHEN detected = 1 THEN 1 ELSE 0 END) AS detections,
               SUM(CASE WHEN exceeds_mcl = 1 THEN 1 ELSE 0 END) AS exceedances,
               SUM(CASE WHEN exceeds_benchmark = 1 THEN 1 ELSE 0 END) AS benchmark_exceedances,
               MAX(CASE WHEN detected = 1 THEN result_value END) AS max_value,
               MAX(unit) AS unit,
               MAX(mcl_value) AS mcl,
               MAX(benchmark_value) AS benchmark
          FROM water_quality_results
         WHERE site_id = ?
         GROUP BY compound
         ORDER BY exceedances DESC, benchmark_exceedances DESC, detections DESC, samples DESC
    """, (site_id,)).fetchall()
    conn.close()
    return jsonify({
        "site": dict(site),
        "compound_summary": [dict(r) for r in rows],
    })


@app.route("/api/water/heatmap")
def api_water_heatmap():
    """Points (lat, lon, weight) for leaflet.heat. Weight = detection count,
    boosted if any exceedances. ?compound filters to one compound."""
    compound = (request.args.get("compound") or "").strip().upper()
    conn = db()
    cur = conn.cursor()
    where = ["r.detected = 1"]
    args: list = []
    if compound:
        where.append("r.compound = ?")
        args.append(compound)
    rows = cur.execute(f"""
        SELECT s.latitude, s.longitude,
               COUNT(*) AS detections,
               SUM(CASE WHEN r.exceeds_mcl = 1 THEN 1 ELSE 0 END) AS exceedances
          FROM water_quality_results r
          JOIN water_quality_sites s ON s.site_id = r.site_id
         WHERE {' AND '.join(where)}
           AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
         GROUP BY s.site_id
    """, args).fetchall()
    conn.close()
    pts = []
    for r in rows:
        weight = float(r["detections"] or 0) + 4.0 * float(r["exceedances"] or 0)
        pts.append([r["latitude"], r["longitude"], weight])
    return jsonify({"compound": compound or None, "points": pts})


# ---- HUC-8 watershed geometry + point-in-polygon aggregation ----

_HUC_POLYS: list | None = None       # [(huc8, [outer_ring, ...])]
_WS_EXTRA: dict | None = None        # {huc8: {contam, contam_npl, pesticide_kg, total_sites}}
_WS_BASE: list | None = None         # cached simplified display features (built once)

# Douglas-Peucker tolerance in degrees for the display geometry (~222 m). The
# raw HUC-8 file is ~1.2M points / 25 MB; at Michigan statewide zoom that detail
# is invisible, so we simplify to ~3% of the points (~0.8 MB) once and cache it.
_WS_SIMPLIFY_TOL = 0.002


def _dp_simplify(points: list, tol: float) -> list:
    """Iterative Douglas-Peucker line simplification. `points` is [[lon,lat],...];
    keeps the endpoints. Returns the reduced point list."""
    n = len(points)
    if n < 3:
        return points
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        ax, ay = points[s]
        bx, by = points[e]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        dmax, idx = 0.0, -1
        for i in range(s + 1, e):
            px, py = points[i]
            if seg == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / seg
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                d = ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5
            if d > dmax:
                dmax, idx = d, i
        if idx != -1 and dmax > tol:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [points[i] for i in range(n) if keep[i]]


def _simplify_ring(ring: list, tol: float) -> list | None:
    """Simplify one polygon ring; drop it if it collapses below a valid polygon."""
    r = _dp_simplify(ring, tol)
    if len(r) < 4:                    # need >=4 pts (closed ring) to stay valid
        return None
    if r[0] != r[-1]:                 # keep the ring closed
        r = r + [r[0]]
    return r


def _simplify_geometry(geom: dict, tol: float) -> dict | None:
    """Return a new Polygon/MultiPolygon geometry with simplified rings."""
    t = geom.get("type")
    coords = geom.get("coordinates") or []
    if t == "Polygon":
        rings = [rr for rr in (_simplify_ring(r, tol) for r in coords) if rr]
        return {"type": "Polygon", "coordinates": rings} if rings else None
    if t == "MultiPolygon":
        polys = []
        for poly in coords:
            rings = [rr for rr in (_simplify_ring(r, tol) for r in poly) if rr]
            if rings:
                polys.append(rings)
        return {"type": "MultiPolygon", "coordinates": polys} if polys else None
    return geom


_WS_FC: dict | None = None           # cached HUC-8 FC with simplified geometry
MI_HUC8_SIMPLIFIED_PATH = MI_HUC8_GEOJSON_PATH.with_name("mi_huc8.simplified.geojson")


def _ws_simplified_fc() -> dict:
    """The HUC-8 FeatureCollection with display-ready simplified geometry.

    Prefers a prebuilt on-disk simplified file (a fast ~0.8 MB parse). If it's
    missing, simplifies the ~25 MB source ONCE (Douglas-Peucker), writes the
    small file for next time, and caches it in memory. After the first build no
    request ever does runtime simplification, so responses stay fast."""
    global _WS_FC
    if _WS_FC is not None:
        return _WS_FC
    if MI_HUC8_SIMPLIFIED_PATH.exists():
        try:
            _WS_FC = json.loads(MI_HUC8_SIMPLIFIED_PATH.read_text())
            return _WS_FC
        except (OSError, ValueError):
            pass
    if not MI_HUC8_GEOJSON_PATH.exists():
        _WS_FC = {"type": "FeatureCollection", "features": []}
        return _WS_FC
    raw = json.loads(Path(MI_HUC8_GEOJSON_PATH).read_text())
    feats = []
    for f in raw.get("features", []):
        geom = _simplify_geometry(f.get("geometry") or {}, _WS_SIMPLIFY_TOL)
        if not geom:
            continue
        props = f.get("properties") or {}
        feats.append({"type": "Feature",
                      "properties": {"huc8": props.get("huc8"), "name": props.get("name")},
                      "geometry": geom})
    fc = {"type": "FeatureCollection", "features": feats}
    try:
        MI_HUC8_SIMPLIFIED_PATH.write_text(json.dumps(fc))
    except OSError:
        pass
    _WS_FC = fc
    return _WS_FC


def _huc_polys() -> list:
    """Outer rings + bounding box per HUC-8 for point-in-polygon, cached. Built
    from the already-simplified geometry, so there is no runtime DP work and the
    bbox rejects far-away points before the ray-cast even starts."""
    global _HUC_POLYS
    if _HUC_POLYS is not None:
        return _HUC_POLYS
    out: list = []
    for f in _ws_simplified_fc().get("features", []):
        huc = (f.get("properties") or {}).get("huc8")
        geom = f.get("geometry") or {}
        t = geom.get("type")
        coords = geom.get("coordinates") or []
        polys = [coords] if t == "Polygon" else (coords if t == "MultiPolygon" else [])
        outers = []
        for p in polys:
            if not p:
                continue
            ring = p[0]                        # already simplified
            if len(ring) >= 4:
                xs = [pt[0] for pt in ring]
                ys = [pt[1] for pt in ring]
                outers.append((ring, (min(xs), min(ys), max(xs), max(ys))))
        if huc and outers:
            out.append((huc, outers))
    _HUC_POLYS = out
    return out


def _pip(x: float, y: float, ring: list) -> bool:
    """Ray-casting point-in-polygon. ring = [[lon, lat], ...]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _huc_for_point(lon, lat) -> str | None:
    if lon is None or lat is None:
        return None
    for huc, outers in _huc_polys():
        for ring, (minx, miny, maxx, maxy) in outers:
            if lon < minx or lon > maxx or lat < miny or lat > maxy:
                continue                       # bbox reject — skip the ray-cast
            if _pip(lon, lat, ring):
                return huc
    return None


def _watershed_extra(conn) -> dict:
    """Per-watershed aggregates that aren't keyed on huc8 in the DB — computed
    by point-in-polygon and cached. Pesticide is an approximation: each county's
    latest-year total is attributed to the HUC-8 its centroid falls in."""
    global _WS_EXTRA
    if _WS_EXTRA is not None:
        return _WS_EXTRA
    from collections import defaultdict
    extra = defaultdict(lambda: {"contam": 0, "contam_npl": 0,
                                 "pesticide_kg": 0.0, "total_sites": 0})
    # total monitoring sites per watershed (huc8 is stored on the site)
    for r in conn.execute("SELECT huc8, COUNT(*) c FROM water_quality_sites "
                          "WHERE huc8 IS NOT NULL AND huc8 <> '' GROUP BY huc8"):
        extra[r["huc8"]]["total_sites"] = r["c"]
    # contamination / Superfund sites within each watershed (point-in-polygon)
    for r in conn.execute("SELECT latitude lat, longitude lng, status_class "
                          "FROM contamination_sites"):
        huc = _huc_for_point(r["lng"], r["lat"])
        if huc:
            extra[huc]["contam"] += 1
            if r["status_class"] == "npl":
                extra[huc]["contam_npl"] += 1
    # approximate pesticide use per watershed via county centroid → HUC
    latest = conn.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]
    pest = {r["county_fips"]: (r["kg"] or 0) for r in conn.execute(
        "SELECT county_fips, SUM((COALESCE(epest_low_kg,0)+COALESCE(epest_high_kg,0))/2.0) kg "
        "FROM pesticide_use WHERE year = ? GROUP BY county_fips", (latest,))}
    for fips, c in _county_centroids().items():
        huc = _huc_for_point(c["lon"], c["lat"])
        if huc and fips in pest:
            extra[huc]["pesticide_kg"] += pest[fips]
    _WS_EXTRA = dict(extra)
    return _WS_EXTRA


def _ws_base_features(conn) -> list:
    """Cached display features: simplified geometry + the static (non-compound)
    properties (name, monitoring-site count, contamination counts, approx
    pesticide use). Built once — the 25 MB source file is read, simplified, and
    merged a single time for the life of the process."""
    global _WS_BASE
    if _WS_BASE is not None:
        return _WS_BASE
    base: list = []
    fc = _ws_simplified_fc()
    if fc.get("features"):
        extra = _watershed_extra(conn)
        for f in fc.get("features", []):
            props = f.get("properties", {}) or {}
            huc = props.get("huc8")
            geom = f.get("geometry")            # already simplified
            if not huc or not geom:
                continue
            e = extra.get(huc, {"contam": 0, "contam_npl": 0,
                                "pesticide_kg": 0.0, "total_sites": 0})
            base.append({
                "huc8": huc, "geometry": geom,
                "static": {
                    "huc8": huc, "name": props.get("name"),
                    "total_sites": e["total_sites"],
                    "contam_sites": e["contam"], "contam_npl": e["contam_npl"],
                    "pesticide_lbs": round((e["pesticide_kg"] or 0) * KG_TO_LB),
                },
            })
    _WS_BASE = base
    return _WS_BASE


@app.route("/api/water/watersheds")
def api_water_watersheds():
    """HUC-8 watershed polygons with per-watershed data for the interactive
    choropleth: pesticide detections/exceedances, monitoring-site counts,
    contamination-site counts, and (approx) upstream pesticide use.

    Geometry is simplified and cached once; each request only re-derives the
    compound-specific detection counts, so responses are small and fast."""
    compound = (request.args.get("compound") or "").strip().upper()
    conn = db()
    cur = conn.cursor()
    where = ["r.detected = 1"]
    args: list = []
    if compound:
        where.append("r.compound = ?")
        args.append(compound)
    counts = {
        row["huc8"]: {"detections": row["detections"],
                      "exceedances": row["exceedances"],
                      "sites_with_detections": row["sites"]}
        for row in cur.execute(f"""
            SELECT s.huc8,
                   COUNT(*) AS detections,
                   SUM(CASE WHEN r.exceeds_mcl = 1 THEN 1 ELSE 0 END) AS exceedances,
                   COUNT(DISTINCT s.site_id) AS sites
              FROM water_quality_results r
              JOIN water_quality_sites s ON s.site_id = r.site_id
             WHERE {' AND '.join(where)} AND s.huc8 IS NOT NULL AND s.huc8 <> ''
             GROUP BY s.huc8
        """, args)
    }
    base = _ws_base_features(conn)
    conn.close()
    if not base:
        return jsonify({"type": "FeatureCollection", "features": [],
                        "note": "Watershed polygons not yet downloaded — run the loader."})
    features = []
    for b in base:
        props = dict(b["static"])          # fresh copy; cached geometry is shared read-only
        props.update(counts.get(b["huc8"],
                                {"detections": 0, "exceedances": 0,
                                 "sites_with_detections": 0}))
        features.append({"type": "Feature", "geometry": b["geometry"],
                         "properties": props})
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/api/water/compounds")
def api_water_compounds():
    """List of compounds with detection counts (for the UI dropdown / matchup)."""
    conn = db()
    rows = conn.execute("""
        SELECT compound,
               COUNT(*) AS samples,
               SUM(CASE WHEN detected = 1 THEN 1 ELSE 0 END) AS detections,
               SUM(CASE WHEN exceeds_mcl = 1 THEN 1 ELSE 0 END) AS exceedances,
               MAX(mcl_value) AS mcl_value
          FROM water_quality_results
         GROUP BY compound
         HAVING detections > 0
         ORDER BY detections DESC
    """).fetchall()
    conn.close()
    return jsonify({"compounds": [dict(r) for r in rows]})


# ---------- Wind / pesticide-drift overlay ----------

_COUNTY_CENTROIDS: dict[str, dict] | None = None


def _county_centroids() -> dict[str, dict]:
    """{fips: {name, lat, lon}} — bbox centers from the county GeoJSON, cached.
    Matches the frontend's bounds-center so arrows originate consistently."""
    global _COUNTY_CENTROIDS
    if _COUNTY_CENTROIDS is not None:
        return _COUNTY_CENTROIDS
    out: dict[str, dict] = {}
    geo = json.loads(Path(GEOJSON_PATH).read_text())
    for feat in geo.get("features", []):
        fips = str(feat.get("id", ""))
        name = (feat.get("properties") or {}).get("name", "")
        lats: list[float] = []
        lons: list[float] = []

        def walk(coords):
            if not coords:
                return
            if isinstance(coords[0], (int, float)):
                lons.append(coords[0]); lats.append(coords[1])
            else:
                for c in coords:
                    walk(c)
        walk((feat.get("geometry") or {}).get("coordinates"))
        if lats and lons:
            out[fips] = {"name": name,
                         "lat": (min(lats) + max(lats)) / 2,
                         "lon": (min(lons) + max(lons)) / 2}
    _COUNTY_CENTROIDS = out
    return out


def _wind_stations(conn) -> list[dict]:
    """All loaded wind_data station rows as dicts (growing-season aggregate)."""
    rows = conn.execute(
        "SELECT * FROM wind_data WHERE season='growing' AND month=0"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["direction_counts"] = json.loads(d.get("direction_counts") or "{}")
        d["speed_by_direction"] = json.loads(d.get("speed_by_direction") or "{}")
        out.append(d)
    return out


def _nearest_station(lat: float, lon: float, stations: list[dict]) -> dict | None:
    best = None
    best_d = 1e18
    for s in stations:
        if s.get("latitude") is None or s.get("longitude") is None:
            continue
        d = haversine_mi(lat, lon, s["latitude"], s["longitude"])
        if d < best_d:
            best_d = d
            best = s
    if best is None:
        return None
    return {**best, "distance_mi": round(best_d, 1)}


@app.route("/api/wind/stations")
def api_wind_stations():
    """Per-station growing-season wind roses for the map overlay."""
    conn = db()
    stations = _wind_stations(conn)
    conn.close()
    out = []
    for s in stations:
        prevailing = deg_to_dir16(s["direction_deg"]) if s["direction_deg"] is not None else None
        out.append({
            "station_id": s["station_id"], "station_name": s["station_name"],
            "latitude": s["latitude"], "longitude": s["longitude"],
            "county": s["county"], "county_fips": s["county_fips"],
            "direction_deg": s["direction_deg"],
            "prevailing_from": prevailing,
            "drift_toward": deg_to_dir16(opposite_deg(s["direction_deg"])) if s["direction_deg"] is not None else None,
            "avg_speed_mph": s["avg_speed_mph"],
            "pct_calm": s["pct_calm"],
            "direction_counts": s["direction_counts"],
            "speed_by_direction": s["speed_by_direction"],
            "n_obs": s["n_obs"], "years": s["years"],
        })
    return jsonify({"directions": DIRS_16, "stations": out,
                    "season": "growing (Apr–Sep)"})


@app.route("/api/wind/drift")
def api_wind_drift():
    """Drift arrows for high-application counties (default top 25% by total
    pesticide applied). Each arrow originates at the county centroid, points
    downwind (nearest-station prevailing wind + 180°), colored by application
    intensity and lengthened by wind speed."""
    try:
        pct = float(request.args.get("top_pct", "25"))
    except ValueError:
        pct = 25.0
    conn = db()
    rows = conn.execute("""
        SELECT county_fips, county, total_pesticide_kg, pesticide_per_sq_mile
          FROM correlation_analysis
         WHERE total_pesticide_kg IS NOT NULL
         ORDER BY total_pesticide_kg DESC
    """).fetchall()
    stations = _wind_stations(conn)
    conn.close()
    if not rows or not stations:
        return jsonify({"arrows": [], "cutoff_lbs": 0, "top_pct": pct})

    centroids = _county_centroids()
    n_top = max(1, round(len(rows) * pct / 100.0))
    top = rows[:n_top]
    # Intensity color scale over the selected counties (lbs/mi²).
    intensities = [r["pesticide_per_sq_mile"] or 0 for r in top]
    imax = max(intensities) or 1.0
    speeds = [s["avg_speed_mph"] or 0 for s in stations]
    smax = max(speeds) or 1.0
    cutoff_kg = top[-1]["total_pesticide_kg"]

    arrows = []
    for r in top:
        c = centroids.get(r["county_fips"])
        if not c:
            continue
        st = _nearest_station(c["lat"], c["lon"], stations)
        if not st or st["direction_deg"] is None:
            continue
        from_deg = st["direction_deg"]
        drift_deg = opposite_deg(from_deg)
        intensity = (r["pesticide_per_sq_mile"] or 0) / imax
        arrows.append({
            "county_fips": r["county_fips"], "county": r["county"],
            "lat": c["lat"], "lon": c["lon"],
            "total_lbs": (r["total_pesticide_kg"] or 0) * KG_TO_LB,
            "per_sq_mile_lbs": (r["pesticide_per_sq_mile"] or 0) * KG_TO_LB,
            "intensity": round(intensity, 3),
            "prevailing_from_deg": from_deg,
            "prevailing_from": deg_to_dir16(from_deg),
            "drift_deg": drift_deg,
            "drift_toward": deg_to_dir16(drift_deg),
            "avg_speed_mph": st["avg_speed_mph"],
            "speed_scale": round((st["avg_speed_mph"] or 0) / smax, 3),
            "station_id": st["station_id"], "station_name": st["station_name"],
            "station_distance_mi": st["distance_mi"],
        })
    return jsonify({"arrows": arrows, "cutoff_lbs": cutoff_kg * KG_TO_LB,
                    "top_pct": pct, "count": len(arrows)})


@app.route("/api/wind/drift-zone/<fips>")
def api_wind_drift_zone(fips: str):
    """Fan-shaped downwind drift buffer (near/mid/far bands) for one county."""
    conn = db()
    stations = _wind_stations(conn)
    row = conn.execute(
        "SELECT county_fips, county, total_pesticide_kg, pesticide_per_sq_mile "
        "FROM correlation_analysis WHERE county_fips=?", (fips,)
    ).fetchone()
    conn.close()
    centroids = _county_centroids()
    c = centroids.get(fips)
    if not c or not stations:
        abort(404)
    st = _nearest_station(c["lat"], c["lon"], stations)
    if not st or st["direction_deg"] is None:
        abort(404)
    from_deg = st["direction_deg"]
    drift_deg = opposite_deg(from_deg)
    bands = drift_fan(c["lat"], c["lon"], drift_deg)
    return jsonify({
        "county_fips": fips, "county": c["name"],
        "origin": [c["lat"], c["lon"]],
        "prevailing_from_deg": from_deg,
        "prevailing_from": deg_to_dir16(from_deg),
        "drift_deg": drift_deg,
        "drift_toward": deg_to_dir16(drift_deg),
        "avg_speed_mph": st["avg_speed_mph"],
        "station_id": st["station_id"], "station_name": st["station_name"],
        "station_distance_mi": st["distance_mi"],
        "total_lbs": (row["total_pesticide_kg"] or 0) * KG_TO_LB if row else None,
        "bands": bands,
        "disclaimer": DRIFT_DISCLAIMER,
    })


# ---------- Cancer incidence / mortality overlay ----------

_CANCER_PEST_METRICS = {
    "all":         ("total_pesticide_kg",   "total pesticide"),
    "herbicide":   ("herbicide_kg",         "herbicide"),
    "insecticide": ("insecticide_kg",       "insecticide"),
    "fungicide":   ("fungicide_kg",         "fungicide"),
    "per_sq_mile": ("pesticide_per_sq_mile","pesticide per mi²"),
}


def _cancer_key(key: str | None) -> str:
    return key if key in cancer_data.CANCER_BY_KEY else cancer_data.DEFAULT_CANCER


def _bool_arg(name: str) -> bool:
    return request.args.get(name) in ("1", "true", "yes", "on")


def _cancer_pest_x(conn, pesticide: str | None) -> tuple[dict, str]:
    """Return ({fips: kg}, label) for the chosen pesticide metric or compound."""
    if pesticide and pesticide.startswith("compound:"):
        comp = pesticide.split(":", 1)[1].upper()
        latest = conn.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]
        rows = conn.execute(
            """SELECT county_fips AS f,
                      SUM((epest_low_kg + epest_high_kg)/2.0) AS k
                 FROM pesticide_use
                WHERE year = ? AND UPPER(compound) LIKE ?
                GROUP BY county_fips""",
            (latest, comp + "%"),
        ).fetchall()
        return {r["f"]: r["k"] for r in rows}, comp.title()
    col, label = _CANCER_PEST_METRICS.get(pesticide, _CANCER_PEST_METRICS["all"])
    rows = conn.execute(
        f"SELECT county_fips AS f, {col} AS k FROM correlation_analysis"
    ).fetchall()
    return {r["f"]: r["k"] for r in rows}, label


def _cancer_units(data_type: str) -> str:
    return "deaths per 100,000" if data_type == "mortality" else "cases per 100,000"


def _contam_count_by_fips(conn, status_class: str | None = None) -> dict:
    """{county_fips: contamination-site count}. Optional status_class filter
    (e.g. 'npl' for Superfund-only)."""
    q = "SELECT county_fips AS f, COUNT(*) AS n FROM contamination_sites WHERE county_fips IS NOT NULL"
    params: list = []
    if status_class:
        q += " AND status_class = ?"
        params.append(status_class)
    q += " GROUP BY county_fips"
    return {r["f"]: r["n"] for r in conn.execute(q, params)}


def _cancer_x_map(conn, pesticide: str | None):
    """Return (xmap, label, is_count). Supports pesticide metrics/compounds and
    the special 'contamination' / 'contamination:npl' count axes."""
    if pesticide and pesticide.startswith("contamination"):
        stc = pesticide.split(":", 1)[1] if ":" in pesticide else None
        label = "Superfund (NPL) sites" if stc == "npl" else "contamination sites"
        return _contam_count_by_fips(conn, stc), label, True
    xmap, label = _cancer_pest_x(conn, pesticide)
    return xmap, label, False


def _cancer_county_card(conn, fips: str) -> dict:
    """All-cancer summary for one county: rate, vs-MI, vs-US, trend, top-20%."""
    my = {r["cancer_type"]: r for r in conn.execute(
        """SELECT cancer_type, rate, recent_trend, rural_urban, suppressed
             FROM cancer_incidence
            WHERE county_fips = ? AND data_type = 'incidence' AND stage = 'all'""",
        (fips,))}
    refs = {r["cancer_type"]: r for r in conn.execute(
        """SELECT cancer_type, mi_rate, us_rate FROM cancer_reference
            WHERE data_type = 'incidence' AND stage = 'all'""")}
    allrates: dict[str, list] = {}
    for r in conn.execute(
        """SELECT cancer_type, rate FROM cancer_incidence
            WHERE data_type = 'incidence' AND stage = 'all' AND rate IS NOT NULL"""):
        allrates.setdefault(r["cancer_type"], []).append(r["rate"])

    metrics = []
    rural = None
    for c in cancer_data.CANCER_TYPES:
        k = c["key"]
        row = my.get(k)
        rate = row["rate"] if row else None
        if row and row["rural_urban"]:
            rural = row["rural_urban"]
        ref = refs.get(k)
        mi = ref["mi_rate"] if ref else None
        us = ref["us_rate"] if ref else None
        pct = ((rate - mi) / mi * 100.0) if (rate is not None and mi) else None
        top20 = False
        if rate is not None:
            arr = sorted(allrates.get(k, []))
            if len(arr) >= 5:
                thr = arr[min(len(arr) - 1, int(0.8 * len(arr)))]
                top20 = rate >= thr
        metrics.append({
            "key": k, "label": c["label"], "rate": rate,
            "suppressed": bool(row["suppressed"]) if row else False,
            "mi_rate": mi, "us_rate": us, "pct_vs_state": pct,
            "trend": row["recent_trend"] if row else None,
            "pesticide_link": c["pesticide_link"], "is_top20": top20,
        })
    return {
        "metrics": metrics,
        "rural_urban": rural,
        "data_years": cancer_data.DATA_YEARS,
        "units": "cases per 100,000 (age-adjusted, 2018-2022)",
    }


def _cancer_interp(cancer_label, pest_label, pear, spear, qc, data_type) -> str:
    r = pear.get("r")
    p = pear.get("p_value")
    n = pear.get("n")
    if r is None or not n or n < 3:
        return (f"Not enough county-level data to correlate {pest_label} with "
                f"{cancer_label}.")
    direction = "positive" if r > 0 else ("negative" if r < 0 else "flat")
    sig = ("statistically significant (p<0.05)" if (p is not None and p < 0.05)
           else "not statistically significant (p≥0.05)")
    rho = spear.get("rho")
    rho_txt = f"{rho:.2f}" if rho is not None else "n/a"
    measure = "incidence" if data_type == "incidence" else "mortality"
    bits = [f"Across {n} Michigan counties, {pest_label} use vs {cancer_label} "
            f"{measure} shows a {direction} correlation (Pearson r={r:.2f}, {sig}; "
            f"Spearman ρ={rho_txt})."]
    if qc and qc.get("top_mean") is not None and qc.get("bottom_mean") is not None:
        bits.append(f"Counties in the top 25% for {pest_label} average "
                    f"{qc['top_mean']:.1f} vs {qc['bottom_mean']:.1f} per 100,000 "
                    f"in the bottom 25%.")
    bits.append("Ecological comparison only — cancer latency (10–30 years), "
                "the ecological fallacy, and confounders (smoking, age, industry) "
                "mean this is not evidence of causation.")
    return " ".join(bits)


@app.route("/api/cancer/types")
def api_cancer_types():
    return jsonify({
        "types": [
            {"key": c["key"], "label": c["label"],
             "pesticide_link": c["pesticide_link"],
             "note": cancer_data.PESTICIDE_LINK_NOTE.get(c["pesticide_link"]),
             "sex": c["sex"], "has_late_stage": c.get("has_late_stage", False),
             "default": c.get("default", False)}
            for c in cancer_data.CANCER_TYPES
        ],
        "default": cancer_data.DEFAULT_CANCER,
        "matrix_compounds": cancer_data.MATRIX_COMPOUNDS,
        "matrix_cancers": [
            {"key": k, "label": cancer_data.CANCER_BY_KEY[k]["label"]}
            for k in cancer_data.MATRIX_CANCERS
        ],
    })


@app.route("/api/cancer/counties")
def api_cancer_counties():
    """Per-county rates for the choropleth."""
    cancer = _cancer_key(request.args.get("type") or request.args.get("cancer"))
    data_type = request.args.get("data_type", "incidence")
    if data_type not in ("incidence", "mortality"):
        data_type = "incidence"
    stage = request.args.get("stage", "all")
    if stage not in ("all", "late"):
        stage = "all"
    conn = db()
    rows = conn.execute(
        """SELECT county_fips, county, rate, recent_trend, rural_urban,
                  suppressed, source, ci_rank
             FROM cancer_incidence
            WHERE cancer_type = ? AND data_type = ? AND stage = ?
            ORDER BY county""",
        (cancer, data_type, stage)).fetchall()
    ref = conn.execute(
        """SELECT mi_rate, us_rate, mi_trend FROM cancer_reference
            WHERE cancer_type = ? AND data_type = ? AND stage = 'all'""",
        (cancer, data_type)).fetchone()
    conn.close()
    is_baseline = bool(rows) and all(r["source"] == "NCI_state_baseline" for r in rows)
    return jsonify({
        "cancer": cancer,
        "label": cancer_data.CANCER_BY_KEY[cancer]["label"],
        "data_type": data_type, "stage": stage,
        "units": _cancer_units(data_type),
        "county_level": not is_baseline, "is_baseline": is_baseline,
        "mi_rate": ref["mi_rate"] if ref else None,
        "us_rate": ref["us_rate"] if ref else None,
        "mi_trend": ref["mi_trend"] if ref else None,
        "pesticide_link": cancer_data.CANCER_BY_KEY[cancer]["pesticide_link"],
        "link_note": cancer_data.PESTICIDE_LINK_NOTE.get(
            cancer_data.CANCER_BY_KEY[cancer]["pesticide_link"]),
        "counties": [
            {"fips": r["county_fips"], "name": r["county"], "value": r["rate"],
             "rate": r["rate"], "trend": r["recent_trend"],
             "rural_urban": r["rural_urban"], "suppressed": bool(r["suppressed"]),
             "source": r["source"]}
            for r in rows
        ],
    })


@app.route("/api/cancer/county/<fips>")
def api_cancer_county(fips: str):
    conn = db()
    county = conn.execute("SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
    if not county:
        conn.close()
        abort(404, "Unknown county FIPS")
    card = _cancer_county_card(conn, fips)
    conn.close()
    return jsonify({"fips": fips, "name": county["name"], **card})


@app.route("/api/cancer/evidence")
def api_cancer_evidence():
    conn = db()
    rows = conn.execute(
        """SELECT compound, cancer_type, evidence_level, iarc_classification,
                  key_mechanism, key_studies, notes
             FROM cancer_evidence
            ORDER BY CASE evidence_level
                       WHEN 'Strong' THEN 0 WHEN 'Moderate-Strong' THEN 1
                       WHEN 'Moderate' THEN 2 ELSE 3 END, compound""").fetchall()
    conn.close()
    labels = {c["key"]: c["label"] for c in cancer_data.CANCER_TYPES}
    return jsonify({"evidence": [
        {**dict(r), "cancer_label": labels.get(r["cancer_type"], r["cancer_type"])}
        for r in rows
    ]})


@app.route("/api/correlation/cancer")
def api_correlation_cancer():
    """Scatter points + Pearson/Spearman + quartile comparison for a
    pesticide metric (or specific compound) vs a cancer rate, with confound
    filters (exclude urban / rural only)."""
    cancer = _cancer_key(request.args.get("cancer"))
    data_type = request.args.get("data_type", "incidence")
    if data_type not in ("incidence", "mortality"):
        data_type = "incidence"
    pesticide = request.args.get("pesticide", "all")
    exclude_urban = _bool_arg("exclude_urban")
    rural_only = _bool_arg("rural_only")
    control_smoking = _bool_arg("control_smoking")

    conn = db()
    xmap, pest_label, is_count = _cancer_x_map(conn, pesticide)
    rows = conn.execute(
        """SELECT ci.county_fips AS f, ci.county AS county, ci.rate AS rate,
                  ci.recent_trend AS trend, ca.is_urban AS is_urban
             FROM cancer_incidence ci
        LEFT JOIN correlation_analysis ca ON ca.county_fips = ci.county_fips
            WHERE ci.cancer_type = ? AND ci.data_type = ? AND ci.stage = 'all'""",
        (cancer, data_type)).fetchall()
    ref = conn.execute(
        """SELECT mi_rate, us_rate FROM cancer_reference
            WHERE cancer_type = ? AND data_type = ? AND stage = 'all'""",
        (cancer, data_type)).fetchone()
    conn.close()

    label = cancer_data.CANCER_BY_KEY[cancer]["label"]
    pts = []
    for r in rows:
        if r["rate"] is None:
            continue
        is_urban = bool(r["is_urban"])
        if (exclude_urban or rural_only) and is_urban:
            continue
        xv = xmap.get(r["f"])
        if is_count:
            xv = xv or 0   # counties with no sites are a real 0, not missing
        elif xv is None:
            continue
        pts.append({"county_fips": r["f"], "county": r["county"],
                    "is_urban": is_urban,
                    "x": xv if is_count else xv * KG_TO_LB, "y": r["rate"],
                    "trend": r["trend"]})

    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    pear = pearson(xs, ys)
    spear = spearman(xs, ys)
    line = None
    if pear.get("slope") is not None and xs:
        xmin, xmax = min(xs), max(xs)
        line = [{"x": xmin, "y": pear["intercept"] + pear["slope"] * xmin},
                {"x": xmax, "y": pear["intercept"] + pear["slope"] * xmax}]
    qc = None
    if len(pts) >= 4:
        sx = sorted(pts, key=lambda p: p["x"])
        q = max(1, len(sx) // 4)
        top = [p["y"] for p in sx[-q:]]
        bot = [p["y"] for p in sx[:q]]
        t = welch_t_test(top, bot)
        qc = {"top_quartile_n": len(top), "bottom_quartile_n": len(bot),
              "top_mean": t.get("mean_a"), "bottom_mean": t.get("mean_b"),
              "welch_t_test": t}

    smoking_note = None
    if control_smoking:
        smoking_note = ("Smoking-adjusted analysis isn't available — county-level "
                        "smoking prevalence was not loaded, so results below are "
                        "unadjusted. Interpret lung and bladder links with care.")
    link = cancer_data.CANCER_BY_KEY[cancer]["pesticide_link"]
    return jsonify({
        "cancer": cancer, "cancer_label": label, "data_type": data_type,
        "pesticide": pesticide, "pesticide_label": pest_label,
        "x_label": f"{pest_label} (count)" if is_count
                   else f"{pest_label} (lbs, latest year)",
        "y_label": f"{label} — {_cancer_units(data_type)}",
        "points": pts, "fit": pear, "spearman": spear, "trend_line": line,
        "quartile_comparison": qc, "n": len(pts),
        "mi_rate": ref["mi_rate"] if ref else None,
        "us_rate": ref["us_rate"] if ref else None,
        "exclude_urban": exclude_urban, "rural_only": rural_only,
        "control_smoking": control_smoking, "smoking_note": smoking_note,
        "link_note": cancer_data.PESTICIDE_LINK_NOTE.get(link),
        "interpretation": _cancer_interp(label, pest_label, pear, spear, qc, data_type),
    })


@app.route("/api/correlation/cancer/matrix")
def api_correlation_cancer_matrix():
    """Compound x cancer correlation grid (computed r), with the literature
    evidence level attached to each cell."""
    data_type = request.args.get("data_type", "incidence")
    if data_type not in ("incidence", "mortality"):
        data_type = "incidence"
    conn = db()
    rows = conn.execute(
        """SELECT cancer_type, pesticide_compound, pearson_r, pearson_p, n_counties
             FROM cancer_pesticide_correlation
            WHERE pesticide_compound IS NOT NULL AND data_type = ?""",
        (data_type,)).fetchall()
    cells = {(r["pesticide_compound"], r["cancer_type"]):
             {"r": r["pearson_r"], "p": r["pearson_p"], "n": r["n_counties"]}
             for r in rows}
    ev = {(e["compound"], e["cancer_type"]):
          {"level": e["evidence_level"], "iarc": e["iarc_classification"]}
          for e in conn.execute(
              "SELECT compound, cancer_type, evidence_level, iarc_classification "
              "FROM cancer_evidence")}
    conn.close()
    matrix = []
    for comp in cancer_data.MATRIX_COMPOUNDS:
        row = []
        for ck in cancer_data.MATRIX_CANCERS:
            cc = cells.get((comp, ck), {})
            row.append({"r": cc.get("r"), "p": cc.get("p"), "n": cc.get("n"),
                        "evidence": ev.get((comp, ck))})
        matrix.append({"compound": comp, "cells": row})
    return jsonify({
        "data_type": data_type,
        "compounds": cancer_data.MATRIX_COMPOUNDS,
        "cancers": [{"key": k, "label": cancer_data.CANCER_BY_KEY[k]["label"]}
                    for k in cancer_data.MATRIX_CANCERS],
        "matrix": matrix,
    })


@app.route("/api/correlation/cancer/quartiles")
def api_correlation_cancer_quartiles():
    """Mean cancer rate per pesticide-use quartile (bar-chart source)."""
    cancer = _cancer_key(request.args.get("cancer"))
    data_type = request.args.get("data_type", "incidence")
    if data_type not in ("incidence", "mortality"):
        data_type = "incidence"
    pesticide = request.args.get("pesticide", "all")
    exclude_urban = _bool_arg("exclude_urban")
    rural_only = _bool_arg("rural_only")

    conn = db()
    xmap, pest_label, is_count = _cancer_x_map(conn, pesticide)
    rows = conn.execute(
        """SELECT ci.county_fips AS f, ci.rate AS rate, ca.is_urban AS is_urban
             FROM cancer_incidence ci
        LEFT JOIN correlation_analysis ca ON ca.county_fips = ci.county_fips
            WHERE ci.cancer_type = ? AND ci.data_type = ? AND ci.stage = 'all'""",
        (cancer, data_type)).fetchall()
    ref = conn.execute(
        """SELECT mi_rate FROM cancer_reference
            WHERE cancer_type = ? AND data_type = ? AND stage = 'all'""",
        (cancer, data_type)).fetchone()
    conn.close()

    pts = []
    for r in rows:
        if r["rate"] is None:
            continue
        if (exclude_urban or rural_only) and r["is_urban"]:
            continue
        x = xmap.get(r["f"])
        if is_count:
            x = x or 0
        elif x is None:
            continue
        pts.append((x if is_count else x * KG_TO_LB, r["rate"]))
    pts.sort(key=lambda p: p[0])
    bars = []
    labels = ["Q1 (lowest use)", "Q2", "Q3", "Q4 (highest use)"]
    if len(pts) >= 4:
        n = len(pts)
        for i in range(4):
            lo = i * n // 4
            hi = (i + 1) * n // 4 if i < 3 else n
            grp = [p[1] for p in pts[lo:hi]]
            bars.append({"quartile": i + 1, "label": labels[i],
                         "mean_rate": (sum(grp) / len(grp)) if grp else None,
                         "n": len(grp)})
    return jsonify({
        "cancer": cancer,
        "cancer_label": cancer_data.CANCER_BY_KEY[cancer]["label"],
        "pesticide_label": pest_label, "data_type": data_type,
        "units": _cancer_units(data_type),
        "mi_rate": ref["mi_rate"] if ref else None,
        "bars": bars,
    })


# ---------- Unified "Explore correlations" endpoint ----------

# Respiratory Y options (column, label, unit).
_EXPLORE_RESP = {
    "asthma_ed":   ("asthma_ed_rate",     "Asthma ER visits",       "per 10,000 (age-adjusted)"),
    "asthma_hosp": ("asthma_hosp_rate",   "Asthma hospitalizations","per 10,000 (age-adjusted)"),
    "copd_ed":     ("copd_ed_rate",       "COPD ER visits",         "per 10,000 (age-adjusted)"),
    "copd_hosp":   ("copd_hosp_rate",     "COPD hospitalizations",  "per 10,000 (age-adjusted)"),
    "prevalence":  ("asthma_prevalence_pct","Adult asthma prevalence","% of adults"),
}

# Pesticide X options (metric key -> label, unit). Compounds/contamination/water
# are handled specially below.
_EXPLORE_PEST = {
    "total":       ("Total pesticide use",   "lbs applied (latest year)"),
    "herbicide":   ("Herbicides",            "lbs applied (latest year)"),
    "insecticide": ("Insecticides",          "lbs applied (latest year)"),
    "fungicide":   ("Fungicides",            "lbs applied (latest year)"),
    "per_sq_mile": ("Pesticide intensity",   "lbs per square mile of county"),
}

_EXPLORE_CAVEAT = {
    "cancer": ("Cancer has a long latency (often 10–30 years), so today's rates "
               "reflect exposures from decades ago — not current pesticide use."),
    "respiratory": ("Asthma and COPD are driven mostly by air quality, smoking, "
                    "housing, and industrial emissions — not farm pesticide use."),
}


def _explore_water_detections(conn) -> dict:
    """{county_fips: number of detected pesticide results}."""
    rows = conn.execute(
        """SELECT s.county_fips AS f, COUNT(*) AS n
             FROM water_quality_results r
             JOIN water_quality_sites s ON s.site_id = r.site_id
            WHERE r.detected = 1 AND s.county_fips IS NOT NULL
            GROUP BY s.county_fips""").fetchall()
    return {r["f"]: r["n"] for r in rows}


def _explore_tri_map(conn, x_key: str):
    """Return (xmap {fips: value}, label, unit) for a TRI X variable. Values are
    already in pounds (TRI's native unit) — the caller treats TRI as a 'count'
    so it is NOT run through the kg->lbs multiply, and a county with no reporting
    facility is a genuine zero."""
    latest = conn.execute("SELECT MAX(year) FROM tri_release").fetchone()[0]
    sub = x_key.split(":", 1)[1] if ":" in x_key else "total"
    if sub == "facilities":
        rows = conn.execute(
            "SELECT county_fips AS f, COUNT(*) AS n FROM tri_facility "
            "WHERE county_fips IS NOT NULL GROUP BY county_fips").fetchall()
        return {r["f"]: r["n"] for r in rows}, "TRI facilities", "facilities reporting"
    if latest is None:
        return {}, "TRI releases", "pounds released per year"
    col = {"total": "total_lbs", "air": "air_lbs", "water": "water_lbs",
           "land": "land_lbs"}.get(sub, "total_lbs")
    rows = conn.execute(
        f"""SELECT f.county_fips AS f, SUM(r.{col}) AS v
              FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
             WHERE r.year = ? AND f.county_fips IS NOT NULL
             GROUP BY f.county_fips""", (latest,)).fetchall()
    labels = {"total": "Industrial toxic releases (TRI)",
              "air": "Industrial air releases (TRI)",
              "water": "Industrial water releases (TRI)",
              "land": "Industrial land releases (TRI)"}
    return ({r["f"]: (r["v"] or 0.0) for r in rows},
            labels.get(sub, "TRI releases"), f"pounds released ({latest})")


def _explore_x_map(conn, x_key: str):
    """Return (xmap {fips: value}, label, unit, is_count) for any X variable."""
    if x_key == "water_detections":
        return (_explore_water_detections(conn),
                "Water pesticide detections", "number of detections", True)
    if x_key and x_key.startswith("tri"):
        xmap, label, unit = _explore_tri_map(conn, x_key)
        return xmap, label, unit, True         # pounds already; skip kg->lbs
    if x_key and x_key.startswith("contamination"):
        xmap, label, _ = _cancer_x_map(conn, x_key)
        return xmap, label.capitalize(), "number of sites", True
    if x_key == "air_toxics:cancer_risk":
        # Population-weighted mean tract risk per county — a genuine control: it
        # lets you weigh "pesticides vs cancer" against "modeled air toxics vs
        # cancer" and see which association is stronger.
        rows = conn.execute(
            "SELECT county_fips AS f, "
            "SUM(total_risk*COALESCE(population,1))/SUM(COALESCE(population,1)) AS v "
            "FROM airtoxics_tracts WHERE total_risk IS NOT NULL "
            "GROUP BY county_fips").fetchall()
        return ({r["f"]: r["v"] for r in rows},
                "Air toxics cancer risk (EPA, modeled)", "in a million", False)
    # pesticide metric or compound (kg values, converted to lbs by caller)
    xmap, label, is_count = _cancer_x_map(conn, x_key)
    unit = _EXPLORE_PEST.get(x_key, ("", "lbs applied (latest year)"))[1]
    if x_key and x_key.startswith("compound:"):
        unit = "lbs applied (latest year)"
    return xmap, label, unit, is_count


def _explore_y_map(conn, y_key: str):
    """Return (ymap {fips: value}, label, unit, family) for any Y variable.
    family is one of 'cancer' | 'respiratory' (for the caveat)."""
    if y_key and y_key.startswith("cancer:"):
        ck = _cancer_key(y_key.split(":", 1)[1])
        rows = conn.execute(
            """SELECT county_fips AS f, rate FROM cancer_incidence
                WHERE cancer_type = ? AND data_type = 'incidence' AND stage = 'all'
                  AND rate IS NOT NULL""", (ck,)).fetchall()
        label = cancer_data.CANCER_BY_KEY[ck]["label"]
        return ({r["f"]: r["rate"] for r in rows}, label,
                "cases per 100,000 (age-adjusted)", "cancer")
    # respiratory (default)
    col, label, unit = _EXPLORE_RESP.get(y_key, _EXPLORE_RESP["asthma_ed"])
    rows = conn.execute(
        f"SELECT county_fips AS f, {col} AS v FROM correlation_analysis "
        f"WHERE {col} IS NOT NULL").fetchall()
    return {r["f"]: r["v"] for r in rows}, label, unit, "respiratory"


def _explore_variables(conn) -> dict:
    """The X and Y option lists that populate the explorer's dropdowns."""
    present = {r[0] for r in conn.execute(
        "SELECT DISTINCT UPPER(compound) FROM pesticide_use")}
    featured = ["GLYPHOSATE", "ATRAZINE", "2,4-D", "METOLACHLOR", "CHLORPYRIFOS",
                "DICAMBA", "ACETOCHLOR", "IMIDACLOPRID", "MESOTRIONE"]
    x = [{"key": k, "label": lbl, "unit": u, "group": "Pesticide use"}
         for k, (lbl, u) in _EXPLORE_PEST.items()]
    for c in featured:
        if c in present:
            x.append({"key": f"compound:{c}", "label": c.title(),
                      "unit": "lbs applied (latest year)", "group": "Specific compound"})
    x += [
        {"key": "contamination", "label": "Contamination sites (all)",
         "unit": "number of sites", "group": "Pollution"},
        {"key": "contamination:npl", "label": "Superfund (NPL) sites",
         "unit": "number of sites", "group": "Pollution"},
        {"key": "water_detections", "label": "Water pesticide detections",
         "unit": "number of detections", "group": "Pollution"},
    ]
    # Air toxics cancer risk (modeled) — a control variable, only if loaded.
    if conn.execute("SELECT COUNT(*) FROM airtoxics_tracts").fetchone()[0]:
        x.append({"key": "air_toxics:cancer_risk",
                  "label": "Air toxics cancer risk (EPA, modeled)",
                  "unit": "in a million (pop-weighted)", "group": "Air quality"})
    # Industrial toxic releases (TRI) — only when the layer has data. Air
    # releases in particular are a well-established respiratory driver, so they
    # double as a control/comparison against the agricultural-pesticide signal.
    has_tri = conn.execute("SELECT 1 FROM tri_release LIMIT 1").fetchone()
    if has_tri:
        x += [
            {"key": "tri:total", "label": "Industrial toxic releases (TRI, all)",
             "unit": "pounds released per year", "group": "Industrial releases (TRI)"},
            {"key": "tri:air", "label": "Industrial air releases (TRI)",
             "unit": "pounds released to air per year", "group": "Industrial releases (TRI)"},
            {"key": "tri:water", "label": "Industrial water releases (TRI)",
             "unit": "pounds released to water per year", "group": "Industrial releases (TRI)"},
            {"key": "tri:facilities", "label": "Number of TRI facilities",
             "unit": "facilities reporting", "group": "Industrial releases (TRI)"},
        ]
    y = [{"key": f"cancer:{c['key']}", "label": c["label"],
          "unit": "cases per 100,000 (age-adjusted)", "group": "Cancer"}
         for c in cancer_data.CANCER_TYPES]
    y += [{"key": k, "label": lbl, "unit": u, "group": "Respiratory"}
          for k, (col, lbl, u) in _EXPLORE_RESP.items()]
    return {"x": x, "y": y,
            "x_default": "total", "y_default": f"cancer:{cancer_data.DEFAULT_CANCER}"}


@app.route("/api/explore/variables")
def api_explore_variables():
    conn = db()
    try:
        return jsonify(_explore_variables(conn))
    finally:
        conn.close()


@app.route("/api/explore")
def api_explore():
    """Flexible county-level scatter/correlation for any X (pesticide use,
    compound, contamination, water detections) vs any Y (cancer, respiratory).
    Returns raw stats + points; the frontend does the plain-language
    translation so it can update live."""
    x_key = request.args.get("x", "total")
    y_key = request.args.get("y", f"cancer:{cancer_data.DEFAULT_CANCER}")
    cohort = request.args.get("cohort", "all")          # all | rural
    exclude_missing = _bool_arg("exclude_missing")

    conn = db()
    xmap, x_label, x_unit, is_count = _explore_x_map(conn, x_key)
    ymap, y_label, y_unit, family = _explore_y_map(conn, y_key)
    urban = {r["county_fips"]: bool(r["is_urban"]) for r in conn.execute(
        "SELECT county_fips, is_urban FROM correlation_analysis")}
    names = {r["fips"]: r["name"] for r in conn.execute(
        "SELECT fips, name FROM counties")}
    conn.close()

    n_urban = n_rural = n_excluded_missing = 0
    pts = []
    for fips, yv in ymap.items():
        if yv is None:
            continue
        is_urban = urban.get(fips, False)
        if cohort == "rural" and is_urban:
            continue
        xv = xmap.get(fips)
        if xv is None:
            if is_count and not exclude_missing:
                xv = 0                     # no sites/detections is a real zero
            else:
                n_excluded_missing += 1
                continue
        pts.append({
            "county_fips": fips, "county": names.get(fips, fips),
            "is_urban": is_urban,
            "x": xv if is_count else xv * KG_TO_LB,
            "y": yv,
        })
        if is_urban:
            n_urban += 1
        else:
            n_rural += 1

    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    fit = pearson(xs, ys)
    spear = spearman(xs, ys)
    line = None
    if fit.get("slope") is not None and xs:
        xmin, xmax = min(xs), max(xs)
        line = [{"x": xmin, "y": fit["intercept"] + fit["slope"] * xmin},
                {"x": xmax, "y": fit["intercept"] + fit["slope"] * xmax}]
    quart = None
    if len(pts) >= 8:
        sx = sorted(pts, key=lambda p: p["x"])
        q = max(1, len(sx) // 4)
        top = [p["y"] for p in sx[-q:]]
        bot = [p["y"] for p in sx[:q]]
        quart = {"top_mean": sum(top) / len(top), "bottom_mean": sum(bot) / len(bot),
                 "top_n": len(top), "bottom_n": len(bot)}

    return jsonify({
        "x": {"key": x_key, "label": x_label, "unit": x_unit, "is_count": is_count},
        "y": {"key": y_key, "label": y_label, "unit": y_unit, "family": family},
        "cohort": cohort, "exclude_missing": exclude_missing,
        "points": pts, "fit": fit, "spearman": spear, "trend_line": line,
        "quartiles": quart,
        "n": len(pts), "n_urban": n_urban, "n_rural": n_rural,
        "n_excluded_missing": n_excluded_missing,
        "caveat": _EXPLORE_CAVEAT.get(family, ""),
    })


# ---------- EPA Toxics Release Inventory (TRI) ----------

# Pathway keys shared by the choropleth, county detail, and trend chart. Air =
# fugitive + stack; land = on-site remainder; these four sum to total_lbs.
_TRI_PATHWAYS = [
    ("air", "air_lbs", "Air (fugitive + smokestack)"),
    ("water", "water_lbs", "Water (surface-water discharge)"),
    ("land", "land_lbs", "Land (on-site landfill / disposal)"),
    ("underground", "underground_lbs", "Underground injection"),
]
_TRI_TREND_TOP_N = 8       # top individual chemicals; the rest fold into "All others"


def _tri_latest_year(conn) -> int | None:
    r = conn.execute("SELECT MAX(year) FROM tri_release").fetchone()
    return r[0] if r and r[0] is not None else None


@app.route("/api/tri/sites")
def api_tri_sites():
    """TRI facility markers. Each facility carries its most-recent reporting
    year's pathway breakdown, its top chemicals that year, a per-year total
    sparkline, and an up/down trend flag. Quantities are pounds (no kg convert).
    """
    conn = db()
    latest = _tri_latest_year(conn)
    if latest is None:
        conn.close()
        return jsonify({"latest_year": None, "facilities": [], "stats": {}})

    facs = {r["facility_id"]: dict(r)
            for r in conn.execute("SELECT * FROM tri_facility")}

    yearly: dict = {}     # fid -> {year: {total,air,water,land,underground}}
    for r in conn.execute(
        """SELECT facility_id AS fid, year,
                  SUM(total_lbs) t, SUM(air_lbs) a, SUM(water_lbs) w,
                  SUM(land_lbs) l, SUM(underground_lbs) u
             FROM tri_release GROUP BY facility_id, year"""):
        yearly.setdefault(r["fid"], {})[r["year"]] = {
            "total": r["t"] or 0.0, "air": r["a"] or 0.0, "water": r["w"] or 0.0,
            "land": r["l"] or 0.0, "underground": r["u"] or 0.0}

    chems: dict = {}      # fid -> {year: [ {chemical, lbs, pfas, carcinogen} ]}
    for r in conn.execute(
        """SELECT facility_id AS fid, year, chemical, is_pfas, is_carcinogen,
                  SUM(total_lbs) lbs
             FROM tri_release GROUP BY facility_id, year, chemical
             ORDER BY lbs DESC"""):
        chems.setdefault(r["fid"], {}).setdefault(r["year"], []).append({
            "chemical": (r["chemical"] or "").title(),
            "lbs": round(r["lbs"] or 0.0, 1),
            "pfas": bool(r["is_pfas"]), "carcinogen": bool(r["is_carcinogen"])})
    conn.close()

    out = []
    for fid, f in facs.items():
        yrs = yearly.get(fid)
        if not yrs:
            continue
        fac_latest = max(yrs)
        cur = yrs[fac_latest]
        spark = [{"year": y, "total": round(yrs[y]["total"], 1)}
                 for y in sorted(yrs)]
        vals = [p["total"] for p in spark]
        trend = "flat"
        if len(vals) >= 2 and vals[0] > 0:
            change = (vals[-1] - vals[0]) / vals[0]
            trend = "up" if change > 0.15 else "down" if change < -0.15 else "flat"
        top_chem = (chems.get(fid, {}).get(fac_latest, []))[:6]
        summary = tri_reference.company_summary(
            f["parent_company"], f["facility_name"], f["industry_sector"],
            [c["chemical"] for c in top_chem], fac_latest)
        out.append({
            "facility_id": fid, "name": f["facility_name"],
            "parent_company": f["parent_company"], "city": f["city"],
            "street_address": f["street_address"],
            "county": f["county"], "county_fips": f["county_fips"],
            "lat": f["latitude"], "lng": f["longitude"],
            "naics_code": f["naics_code"], "industry_sector": f["industry_sector"],
            "federal": bool(f["federal_facility"]),
            "company_summary": summary["text"], "summary_sourced": summary["sourced"],
            "year": fac_latest,
            "total_lbs": round(cur["total"], 1),
            "air_lbs": round(cur["air"], 1), "water_lbs": round(cur["water"], 1),
            "land_lbs": round(cur["land"], 1),
            "underground_lbs": round(cur["underground"], 1),
            "top_chemicals": top_chem,
            "spark": spark, "trend": trend,
        })
    out.sort(key=lambda x: x["total_lbs"], reverse=True)
    stats = {"max_total": out[0]["total_lbs"] if out else 0,
             "facility_count": len(out), "latest_year": latest}
    return jsonify({"latest_year": latest, "facilities": out, "stats": stats})


@app.route("/api/tri/density")
def api_tri_density():
    """Per-county TRI choropleth. ?metric=total|air|water|land|pfas selects the
    pathway; ?year defaults to the latest reporting year."""
    metric = request.args.get("metric", "total")
    year = request.args.get("year", type=int)
    conn = db()
    latest = _tri_latest_year(conn)
    if latest is None:
        conn.close()
        return jsonify({"metric": metric, "year": None, "counties": [], "stats": {}})
    if year is None:
        year = latest
    if metric == "pfas":
        val_expr = "SUM(CASE WHEN r.is_pfas = 1 THEN r.total_lbs ELSE 0 END)"
    else:
        col = {"total": "total_lbs", "air": "air_lbs", "water": "water_lbs",
               "land": "land_lbs"}.get(metric, "total_lbs")
        val_expr = f"SUM(r.{col})"
    rows = conn.execute(
        f"""SELECT c.fips, c.name, {val_expr} AS value,
                   COUNT(DISTINCT r.facility_id) AS facilities
              FROM counties c
         LEFT JOIN tri_facility f ON f.county_fips = c.fips
         LEFT JOIN tri_release r ON r.facility_id = f.facility_id AND r.year = ?
          GROUP BY c.fips, c.name ORDER BY c.name""", (year,)).fetchall()
    conn.close()
    out = [{"fips": r["fips"], "name": r["name"],
            "value": round(r["value"] or 0.0, 1), "facilities": r["facilities"] or 0}
           for r in rows]
    vals = [o["value"] for o in out if o["value"] > 0]
    stats = {"max": max(vals) if vals else 0, "min": min(vals) if vals else 0,
             "mean": (sum(vals) / len(vals)) if vals else 0,
             "counties_with_data": len(vals), "total_counties": len(out),
             "year": year}
    return jsonify({"metric": metric, "year": year, "counties": out, "stats": stats})


@app.route("/api/tri/county")
def api_tri_county():
    """County-click detail for the TRI choropleth: pathway breakdown, top
    facilities, and top chemicals for the given county + year."""
    fips = (request.args.get("fips") or "").strip()
    year = request.args.get("year", type=int)
    conn = db()
    latest = _tri_latest_year(conn)
    if year is None:
        year = latest
    name_row = conn.execute("SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
    if not name_row or latest is None:
        conn.close()
        return jsonify({"fips": fips, "name": None, "year": year, "total_lbs": 0,
                        "pathways": [], "top_facilities": [], "top_chemicals": []})
    p = conn.execute(
        """SELECT SUM(r.total_lbs) t, SUM(r.air_lbs) a, SUM(r.water_lbs) w,
                  SUM(r.land_lbs) l, SUM(r.underground_lbs) u,
                  COUNT(DISTINCT r.facility_id) facs
             FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
            WHERE f.county_fips = ? AND r.year = ?""", (fips, year)).fetchone()
    pathways = [
        {"key": "air", "label": "Air", "lbs": round(p["a"] or 0.0, 1)},
        {"key": "water", "label": "Water", "lbs": round(p["w"] or 0.0, 1)},
        {"key": "land", "label": "Land", "lbs": round(p["l"] or 0.0, 1)},
        {"key": "underground", "label": "Underground", "lbs": round(p["u"] or 0.0, 1)},
    ]
    top_f = [{"facility_id": r["facility_id"], "name": r["facility_name"],
              "industry": r["industry_sector"], "lbs": round(r["t"] or 0.0, 1)}
             for r in conn.execute(
        """SELECT f.facility_id, f.facility_name, f.industry_sector, SUM(r.total_lbs) t
             FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
            WHERE f.county_fips = ? AND r.year = ?
            GROUP BY r.facility_id ORDER BY t DESC LIMIT 5""", (fips, year))]
    # `key` is the raw chemical name (used to drill into /api/tri/chemical);
    # `chemical` is the title-cased display form.
    top_c = [{"key": r["chemical"], "chemical": (r["chemical"] or "").title(),
              "cas": r["cas"], "lbs": round(r["t"] or 0.0, 1),
              "pfas": bool(r["pf"]), "carcinogen": bool(r["cc"])}
             for r in conn.execute(
        """SELECT r.chemical, MAX(r.cas) cas, MAX(r.is_pfas) pf, MAX(r.is_carcinogen) cc,
                  SUM(r.total_lbs) t
             FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
            WHERE f.county_fips = ? AND r.year = ?
            GROUP BY r.chemical ORDER BY t DESC LIMIT 6""", (fips, year))]
    conn.close()
    return jsonify({
        "fips": fips, "name": name_row["name"], "year": year,
        "total_lbs": round(p["t"] or 0.0, 1), "facilities": p["facs"] or 0,
        "pathways": pathways, "top_facilities": top_f, "top_chemicals": top_c,
    })


@app.route("/api/tri/chemical")
def api_tri_chemical():
    """Drill-down for one chemical in one county: sourced plain-language profile
    (what it is, uses, health/carcinogen class, typical pathways), the county's
    and the statewide total pounds released, the per-pathway split in the county,
    and the county facilities that release it. ?fips= &chemical= (raw name)."""
    fips = (request.args.get("fips") or "").strip()
    chem = (request.args.get("chemical") or "").strip()
    year = request.args.get("year", type=int)
    conn = db()
    latest = _tri_latest_year(conn)
    if year is None:
        year = latest
    if not chem or latest is None:
        conn.close()
        return jsonify({"chemical": chem, "found": False})

    name_row = conn.execute("SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
    # County-level totals + pathway split for this chemical (case-insensitive match).
    c = conn.execute(
        """SELECT MAX(r.cas) cas, MAX(r.is_pfas) pf, MAX(r.is_carcinogen) cc,
                  SUM(r.total_lbs) t, SUM(r.air_lbs) a, SUM(r.water_lbs) w,
                  SUM(r.land_lbs) l, SUM(r.underground_lbs) u
             FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
            WHERE f.county_fips = ? AND r.year = ? AND UPPER(r.chemical) = UPPER(?)""",
        (fips, year, chem)).fetchone()
    statewide = conn.execute(
        "SELECT SUM(total_lbs) t FROM tri_release WHERE year = ? AND UPPER(chemical) = UPPER(?)",
        (year, chem)).fetchone()
    facilities = [{"name": r["facility_name"], "lbs": round(r["t"] or 0.0, 1)}
                  for r in conn.execute(
        """SELECT f.facility_name, SUM(r.total_lbs) t
             FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
            WHERE f.county_fips = ? AND r.year = ? AND UPPER(r.chemical) = UPPER(?)
            GROUP BY r.facility_id ORDER BY t DESC""", (fips, year, chem))]
    conn.close()

    is_carc = bool(c["cc"]) if c else False
    profile = tri_reference.chemical_profile(chem, c["cas"] if c else None, is_carc)
    return jsonify({
        "found": True,
        "chemical": chem.title(), "cas": (c["cas"] if c else None),
        "pfas": bool(c["pf"]) if c else False, "carcinogen": is_carc,
        "county": name_row["name"] if name_row else None, "fips": fips, "year": year,
        "county_total_lbs": round((c["t"] or 0.0) if c else 0.0, 1),
        "statewide_total_lbs": round((statewide["t"] or 0.0) if statewide else 0.0, 1),
        "pathways": [
            {"key": "air", "label": "Air", "lbs": round((c["a"] or 0.0) if c else 0.0, 1)},
            {"key": "water", "label": "Water", "lbs": round((c["w"] or 0.0) if c else 0.0, 1)},
            {"key": "land", "label": "Land", "lbs": round((c["l"] or 0.0) if c else 0.0, 1)},
            {"key": "underground", "label": "Underground", "lbs": round((c["u"] or 0.0) if c else 0.0, 1)},
        ],
        "facilities": facilities,
        "profile": profile,
    })


@app.route("/api/chemical")
def api_chemical():
    """General chemical-info lookup, reusable wherever a chemical/compound name
    appears (water-site popups, TRI popups, county compound lists, trends).

    Merges three honest sources: the curated hazard profile (tri_reference),
    reported agricultural pesticide use, and reported industrial TRI releases.
    Whatever isn't available is simply omitted — no health claims are invented.
    ?name= (required), optional ?fips= to add county-level TRI detail."""
    name = (request.args.get("name") or "").strip()
    fips = (request.args.get("fips") or "").strip()
    site = (request.args.get("site") or "").strip()
    if not name:
        return jsonify({"found": False, "name": name})
    conn = db()

    # --- cached PubChem enrichment (real description, formula, CAS, CID) --- #
    chem = conn.execute(
        "SELECT name, cas, pubchem_cid, description, description_source, "
        "       molecular_formula, molecular_weight, iupac_name, synonyms "
        "  FROM chemical_reference WHERE name_key = UPPER(?)", (name,)).fetchone()
    pubchem = None
    if chem and chem["pubchem_cid"]:
        try:
            syns = json.loads(chem["synonyms"]) if chem["synonyms"] else []
        except (TypeError, ValueError):
            syns = []
        pubchem = {
            "cid": chem["pubchem_cid"],
            "description": chem["description"],
            "description_source": chem["description_source"],
            "molecular_formula": chem["molecular_formula"],
            "molecular_weight": chem["molecular_weight"],
            "iupac_name": chem["iupac_name"],
            "synonyms": syns,
            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{chem['pubchem_cid']}",
        }

    # --- pesticide side (agricultural use) -------------------------------- #
    pc = conn.execute(
        "SELECT category, toxicity_class FROM pesticide_categories "
        "WHERE UPPER(compound) = UPPER(?)", (name,)).fetchone()
    puse = conn.execute(
        "SELECT year, SUM(epest_high_kg) kg FROM pesticide_use "
        "WHERE UPPER(compound) = UPPER(?) GROUP BY year ORDER BY year", (name,)).fetchall()
    is_pesticide = bool(pc) or bool(puse)
    pest = None
    if is_pesticide:
        latest = puse[-1] if puse else None
        pest = {
            "category": pc["category"] if pc else None,
            "toxicity_class": pc["toxicity_class"] if pc else None,
            "latest_year": latest["year"] if latest else None,
            "statewide_lbs": round((latest["kg"] or 0.0) * KG_TO_LB, 1) if latest else None,
        }
        # County-specific applied amount, same (latest) year as the statewide
        # figure so the two are directly comparable in the popup.
        if fips and latest:
            crow = conn.execute(
                "SELECT SUM(epest_high_kg) kg FROM pesticide_use "
                "WHERE UPPER(compound) = UPPER(?) AND county_fips = ? AND year = ?",
                (name, fips, latest["year"])).fetchone()
            cnm = conn.execute(
                "SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
            pest["county"] = cnm["name"] if cnm else None
            pest["county_lbs"] = round((crow["kg"] or 0.0) * KG_TO_LB, 1) if crow else 0.0

    # --- TRI side (industrial releases) ----------------------------------- #
    tri_latest = _tri_latest_year(conn)
    trow = conn.execute(
        "SELECT MAX(cas) cas, MAX(is_pfas) pf, MAX(is_carcinogen) cc, SUM(total_lbs) t "
        "FROM tri_release WHERE year = ? AND UPPER(chemical) = UPPER(?)",
        (tri_latest, name)).fetchone() if tri_latest is not None else None
    is_tri = bool(trow and (trow["t"] or 0) > 0)
    cas = trow["cas"] if trow else None
    carcinogen = bool(trow["cc"]) if trow else False
    pfas = bool(trow["pf"]) if trow else False
    tri = None
    if is_tri:
        tri = {"year": tri_latest, "statewide_lbs": round(trow["t"] or 0.0, 1)}
        if fips:
            cc = conn.execute(
                "SELECT SUM(r.total_lbs) t, SUM(r.air_lbs) a, SUM(r.water_lbs) w, "
                "       SUM(r.land_lbs) l, SUM(r.underground_lbs) u "
                "  FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id "
                " WHERE f.county_fips = ? AND r.year = ? AND UPPER(r.chemical) = UPPER(?)",
                (fips, tri_latest, name)).fetchone()
            nm = conn.execute("SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
            tri["county"] = nm["name"] if nm else None
            tri["county_lbs"] = round((cc["t"] or 0.0) if cc else 0.0, 1)
            tri["pathways"] = [
                {"label": "Air", "lbs": round((cc["a"] or 0.0) if cc else 0.0, 1)},
                {"label": "Water", "lbs": round((cc["w"] or 0.0) if cc else 0.0, 1)},
                {"label": "Land", "lbs": round((cc["l"] or 0.0) if cc else 0.0, 1)},
                {"label": "Underground", "lbs": round((cc["u"] or 0.0) if cc else 0.0, 1)},
            ]
            tri["facilities"] = [
                {"name": r["facility_name"], "lbs": round(r["t"] or 0.0, 1)}
                for r in conn.execute(
                    "SELECT f.facility_name, SUM(r.total_lbs) t "
                    "  FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id "
                    " WHERE f.county_fips = ? AND r.year = ? AND UPPER(r.chemical) = UPPER(?) "
                    " GROUP BY r.facility_id ORDER BY t DESC LIMIT 6",
                    (fips, tri_latest, name))]

    # --- water side (monitoring detections) ------------------------------- #
    # When the popup is opened from a water monitoring site, surface how often
    # this compound was found there (and county), for site/county context.
    water = None
    if site:
        rows = conn.execute(
            "SELECT result_value, unit, detected, exceeds_mcl, exceeds_benchmark "
            "  FROM water_quality_results "
            " WHERE site_id = ? AND UPPER(compound) = UPPER(?)",
            (site, name)).fetchall()
        if rows:
            # Highest detection normalised to µg/L — raw result values arrive in
            # mixed units (ng/L, µg/L, …), so a bare MAX(result_value) is
            # meaningless and can pair a value with another row's unit. Convert
            # each detection to µg/L and take the max, so it's comparable to the
            # limits shown beside it.
            max_ugl = None
            for r in rows:
                if r["detected"] and r["result_value"] is not None:
                    ugl = to_ugl(r["result_value"], r["unit"])
                    if ugl is not None and (max_ugl is None or ugl > max_ugl):
                        max_ugl = ugl
            srow = conn.execute(
                "SELECT site_name, county FROM water_quality_sites WHERE site_id = ?",
                (site,)).fetchone()
            water = {
                "scope": "site",
                "site_name": srow["site_name"] if srow else site,
                "county": srow["county"] if srow else None,
                "samples": len(rows),
                "detections": sum(1 for r in rows if r["detected"]),
                # Two SEPARATE standards, reported independently and never merged.
                "mcl_exceedances": sum(1 for r in rows if r["exceeds_mcl"]),
                "benchmark_exceedances": sum(1 for r in rows if r["exceeds_benchmark"]),
                "max_value": round(max_ugl, 4) if max_ugl is not None else None,
                "unit": "µg/L" if max_ugl is not None else None,
                "mcl": mcl_for(name),
                "benchmark": benchmark_for(name),
                "benchmark_source": AQUATIC_BENCHMARK_SOURCE,
            }
    conn.close()

    profile = tri_reference.chemical_profile(name, cas, carcinogen)
    # The curated fallback blurb is TRI-flavored ("tracked by the EPA TRI"); only
    # keep it for chemicals that really are TRI chemicals. For everything else the
    # PubChem description (or the honest no-info note) carries the explanation.
    if not profile.get("sourced") and not is_tri:
        profile = {"what": None, "uses": None, "health": None,
                   "carcinogen": None, "pathways": None, "sourced": False}

    # Fall back to the CAS PubChem resolved when the TRI data didn't carry one.
    if not cas and chem and chem["cas"]:
        cas = chem["cas"]

    # --- PFAS reference (code-side; app/pfas_chem.py) --------------------- #
    # PFAS are labelled by abbreviation (PFOS, GenX, …) that the PubChem cache
    # doesn't hold. Resolve the abbreviation to a full identity + drinking-water
    # limits so the shared popup can explain it — no DB republish required.
    display_name = name.title()
    regulatory = None
    pref = pfas_chem.lookup(name)
    if pref:
        pfas = True
        display_name = pref["display"]
        cas = cas or pref.get("cas")
        regulatory = pref.get("regulatory")
        if not pubchem:
            cid = pref.get("cid")
            pubchem = {
                "cid": cid,
                "description": pref.get("description"),
                "description_source": "EPA / EGLE",
                "molecular_formula": pref.get("formula"),
                "molecular_weight": None,
                "iupac_name": pref.get("name"),
                "synonyms": [],
                # None when no CID — the frontend then omits the PubChem link but
                # still shows the name, CAS, description and limits (graceful).
                "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else None,
            }

    return jsonify({
        "found": True,
        "name": display_name,
        "cas": cas,
        "carcinogen": carcinogen,
        "pfas": pfas,
        "is_pesticide": is_pesticide,
        "pesticide": pest,
        "is_tri": is_tri,
        "tri": tri,
        "water": water,
        "pubchem": pubchem,
        "regulatory": regulatory,
        "profile": profile,
    })


@app.route("/api/tri/trend")
def api_tri_trend():
    """Year-over-year TRI releases — statewide (no fips) or one county — broken
    down by pathway and by top individual chemicals. Mirrors /api/trend's shape
    so the frontend trend panel can render it the same way."""
    fips = (request.args.get("fips") or "").strip()
    conn = db()
    where, params, scope = "", [], "Statewide"
    if fips:
        row = conn.execute("SELECT name FROM counties WHERE fips = ?", (fips,)).fetchone()
        if row:
            where = "AND f.county_fips = ?"
            params = [fips]
            scope = f"{row['name']} County"

    years = [r[0] for r in conn.execute(
        f"""SELECT DISTINCT r.year FROM tri_release r
              JOIN tri_facility f ON f.facility_id = r.facility_id
             WHERE 1=1 {where} ORDER BY r.year""", params)]
    yi = {y: i for i, y in enumerate(years)}
    n = len(years)

    total = [0.0] * n
    path_series = {k: [0.0] * n for k, _, _ in _TRI_PATHWAYS}
    for r in conn.execute(
        f"""SELECT r.year y, SUM(r.total_lbs) t, SUM(r.air_lbs) a,
                   SUM(r.water_lbs) w, SUM(r.land_lbs) l, SUM(r.underground_lbs) u
              FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
             WHERE 1=1 {where} GROUP BY r.year""", params):
        i = yi[r["y"]]
        total[i] = round(r["t"] or 0.0, 1)
        path_series["air"][i] = round(r["a"] or 0.0, 1)
        path_series["water"][i] = round(r["w"] or 0.0, 1)
        path_series["land"][i] = round(r["l"] or 0.0, 1)
        path_series["underground"][i] = round(r["u"] or 0.0, 1)
    categories = [{"key": k, "label": lbl, "values": path_series[k]}
                  for k, _, lbl in _TRI_PATHWAYS]

    top = conn.execute(
        f"""SELECT r.chemical c, SUM(r.total_lbs) t
              FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
             WHERE 1=1 {where} GROUP BY r.chemical
             ORDER BY t DESC NULLS LAST LIMIT ?""", [*params, _TRI_TREND_TOP_N]).fetchall()
    top_names = [r["c"] for r in top]
    compounds = []
    if top_names:
        comp_series = {name: [0.0] * n for name in top_names}
        placeholders = ",".join("?" * len(top_names))
        for r in conn.execute(
            f"""SELECT r.year y, r.chemical c, SUM(r.total_lbs) t
                  FROM tri_release r JOIN tri_facility f ON f.facility_id = r.facility_id
                 WHERE r.chemical IN ({placeholders}) {where}
                 GROUP BY r.year, r.chemical""", [*top_names, *params]):
            comp_series[r["c"]][yi[r["y"]]] += round(r["t"] or 0.0, 1)
        compounds = [{"name": (name or "").title(), "values": comp_series[name]}
                     for name in top_names]
        others = [max(0.0, total[i] - sum(comp_series[nm][i] for nm in top_names))
                  for i in range(n)]
        if any(v > 0 for v in others):
            compounds.append({"name": "All others",
                              "values": [round(v, 1) for v in others]})
    conn.close()
    return jsonify({
        "scope": scope, "fips": fips or None, "years": years,
        "total": total, "categories": categories, "compounds": compounds,
    })


# ---------- Industrial contamination overlay ----------

def _contam_row(r) -> dict:
    """Parse a contamination_sites row into a JSON-friendly dict with the
    marker glyph/color the frontend needs."""
    glyph, cat_label = contamination_data.CATEGORY_META.get(
        r["category"], contamination_data.CATEGORY_META["other"])
    color, status_label = contamination_data.STATUS_COLORS.get(
        r["status_class"], contamination_data.STATUS_COLORS["unknown"])

    def _json(v):
        try:
            return json.loads(v) if v else []
        except (TypeError, ValueError):
            return []

    epa_url = (EPA_SITE_PROFILE.format(epa_id=r["epa_id"])
               if r["epa_id"] else None)
    return {
        "site_key": r["site_key"], "company": r["company"],
        "site_name": r["site_name"], "lat": r["latitude"], "lng": r["longitude"],
        "county": r["county"], "county_fips": r["county_fips"], "city": r["city"],
        "epa_id": r["epa_id"], "status": r["status"],
        "status_class": r["status_class"], "status_label": status_label,
        "status_color": color, "years_active": r["years_active"],
        "contaminants": _json(r["contaminants"]),
        "description": r["description"],
        "impact_area_miles": r["impact_area_miles"],
        "affected_waterways": _json(r["affected_waterways"]),
        "affected_counties": _json(r["affected_counties"]),
        "npl_listed": bool(r["npl_listed"]), "npl_date": r["npl_date"],
        "hrs_score": r["hrs_score"], "category": r["category"],
        "category_label": cat_label, "glyph": glyph, "source": r["source"],
        "epa_profile_url": epa_url,
        "desc_source": (r["desc_source"] if "desc_source" in r.keys() else "narrative"),
        "narrative": (r["narrative"] if "narrative" in r.keys() else None),
        "narrative_source": (r["narrative_source"] if "narrative_source" in r.keys() else None),
        "narrative_refs": _json(r["narrative_refs"]) if "narrative_refs" in r.keys() else [],
    }


@app.route("/api/contamination/sites")
def api_contamination_sites():
    """All contamination sites, optionally filtered by ?category= or ?status=."""
    category = request.args.get("category")
    status = request.args.get("status")   # status_class: npl|proposed|deleted|state
    q = "SELECT * FROM contamination_sites WHERE 1=1"
    params: list = []
    if category and category != "all":
        q += " AND category = ?"
        params.append(category)
    if status and status != "all":
        q += " AND status_class = ?"
        params.append(status)
    q += " ORDER BY hrs_score DESC NULLS LAST, site_name"
    conn = db()
    rows = conn.execute(q, params).fetchall()
    conn.close()
    sites = [_contam_row(r) for r in rows]
    return jsonify({
        "count": len(sites),
        "categories": [{"key": k, "glyph": v[0], "label": v[1]}
                       for k, v in contamination_data.CATEGORY_META.items()],
        "statuses": [{"key": k, "color": v[0], "label": v[1]}
                     for k, v in contamination_data.STATUS_COLORS.items()],
        "sites": sites,
    })


@app.route("/api/spraying/programs")
def api_spraying_programs():
    """Curated directory of Michigan's organized pest-control spraying programs
    (spongy moth, mosquito abatement, state arbovirus response). A directory of
    who-runs-what with links to official schedules — not a live spray-date feed.
    Static reference data; no DB access."""
    return jsonify(spraying_programs.programs_payload())


# Generic words that must NOT drive a cross-link match — they collide across
# unrelated facilities ("power plant", "energy company", county/utility words).
_COAL_LINK_STOP = {
    "power", "plant", "station", "generating", "generation", "energy", "electric",
    "company", "the", "and", "facility", "steam", "complex", "development",
    "acquisition", "solutions", "board", "light", "water", "municipal", "city",
    "county", "michigan", "coal", "ash", "former", "site", "unit", "pond",
    "impoundment", "landfill", "legacy", "dte", "consumers",
}


def _link_tokens(name: str) -> set:
    """Distinctive lowercase tokens (len>=4, not a generic word) from a name."""
    cleaned = "".join(c if c.isalnum() else " " for c in (name or "").lower())
    return {t for t in cleaned.split() if len(t) >= 4 and t not in _COAL_LINK_STOP}


def _coal_ash_crosslinks(conn, site: dict) -> dict:
    """Precision-first cross-links from a coal-ash site to the app's TRI, landfill,
    and contamination layers — linking a site to ITS OWN appearance in another
    layer, not to unrelated neighbours. Coordinates alone won't do (dense
    industrial waterfronts) and a name token alone won't either (city-named plants
    like Monroe/River Rouge would match every facility in town). So:

      * If the plant has a DISTINCTIVE name token (Campbell, Karn, Channel, Sims…),
        require that token in common AND proximity <= 1.5 mi (covers the plant's
        own ash landfill/impoundment listed separately).
      * If the plant is named only after its city/county (Monroe, River Rouge,
        St. Clair), there is no distinctive token, so require same-site proximity
        (<= 0.5 mi) — i.e. the co-located facility, not a cross-town namesake.
    """
    out = {"tri": [], "landfill": [], "contamination": []}
    lat, lon = site.get("lat"), site.get("lon")
    if lat is None or lon is None:
        return out
    geo = _link_tokens(site.get("city", "")) | _link_tokens(site.get("county", ""))
    distinctive = _link_tokens(site.get("name", "")) - geo
    if distinctive:
        match_toks, MAX_MI, limit = distinctive, 1.5, 4
    else:
        # City-named plant: no distinctive token, so only the single nearest
        # co-located facility counts (avoid pulling in adjacent-waterfront namesakes).
        match_toks, MAX_MI, limit = _link_tokens(site.get("name", "")), 0.5, 1
    if not match_toks:
        return out

    def scan(sql, id_col, name_col, layer):
        hits = []
        for r in conn.execute(sql):
            rla, rlo = r["latitude"], r["longitude"]
            if rla is None or rlo is None:
                continue
            if not (_link_tokens(r[name_col]) & match_toks):
                continue
            d = haversine_mi(lat, lon, rla, rlo)
            if d <= MAX_MI:
                hits.append({"id": r[id_col], "name": r[name_col],
                             "distance_mi": round(d, 1)})
        hits.sort(key=lambda x: x["distance_mi"])
        out[layer] = hits[:limit]

    scan("SELECT facility_id, facility_name, latitude, longitude FROM tri_facility",
         "facility_id", "facility_name", "tri")
    scan("SELECT site_key, name, latitude, longitude FROM landfill_sites",
         "site_key", "name", "landfill")
    scan("SELECT site_key, site_name, latitude, longitude FROM contamination_sites",
         "site_key", "site_name", "contamination")
    return out


@app.route("/api/coal-ash/sites")
def api_coal_ash_sites():
    """Curated directory of Michigan's coal combustion residuals (coal ash) sites.
    The federal CCR rule is self-implementing — each utility posts its own
    monitoring data on its own site — so this is a directory that links to those
    official pages, enriched with precision-first cross-links to the app's TRI,
    landfill and contamination layers. See app/coal_ash_data.py for the sources."""
    payload = coal_ash_data.sites_payload()
    conn = db()
    for s in payload["sites"]:
        s["crosslinks"] = _coal_ash_crosslinks(conn, s)
    return jsonify(payload)


@app.route("/api/contamination/county/<fips>")
def api_contamination_county(fips: str):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM contamination_sites WHERE county_fips = ? "
        "ORDER BY hrs_score DESC NULLS LAST, site_name", (fips,)).fetchall()
    conn.close()
    return jsonify({"fips": fips, "count": len(rows),
                    "sites": [_contam_row(r) for r in rows]})


@app.route("/api/contamination/density")
def api_contamination_density():
    """Per-county site counts for the density choropleth."""
    conn = db()
    rows = conn.execute("""
        SELECT c.fips, c.name,
               COUNT(cs.id) AS total,
               SUM(CASE WHEN cs.status_class='npl' THEN 1 ELSE 0 END) AS npl,
               SUM(CASE WHEN cs.contaminants LIKE '%PFAS%' THEN 1 ELSE 0 END) AS pfas,
               MAX(cs.hrs_score) AS max_hrs
          FROM counties c
     LEFT JOIN contamination_sites cs ON cs.county_fips = c.fips
      GROUP BY c.fips, c.name
      ORDER BY c.name
    """).fetchall()
    conn.close()
    out = [{"fips": r["fips"], "name": r["name"], "value": r["total"],
            "total": r["total"], "npl": r["npl"] or 0, "pfas": r["pfas"] or 0,
            "max_hrs": r["max_hrs"]} for r in rows]
    counts = [r["value"] for r in out if r["value"]]
    return jsonify({
        "counties": out,
        "stats": {"max": max(counts) if counts else 0,
                  "counties_with_sites": len(counts),
                  "total_sites": sum(counts)},
    })


# ---------- Landfills & waste facilities overlay ----------

def _landfill_row(r) -> dict:
    """Parse a landfill_sites row into a JSON-friendly dict with marker
    glyph/color, monitoring context, and TRI/contamination cross-links."""
    def _json(v):
        try:
            return json.loads(v) if v else []
        except (TypeError, ValueError):
            return []
    row = {
        "site_key": r["site_key"], "program": r["program"],
        "name": r["name"], "operator": r["operator"],
        "category": r["category"], "type_label": r["type_label"],
        "facility_types": _json(r["facility_types"]),
        "status_class": r["status_class"], "status_label": r["status_label"],
        "license_id": r["license_id"],
        "alt_id": r["alt_id"], "alt_id_label": r["alt_id_label"],
        "address": r["address"],
        "city": r["city"], "zip": r["zip"], "county": r["county"],
        "county_fips": r["county_fips"], "lat": r["latitude"], "lng": r["longitude"],
        "egle_url": r["egle_url"],
        "federal_regulated": bool(r["federal_regulated"]),
        "commercial": bool(r["commercial"]),
        "tri_facility_id": r["tri_facility_id"],
        "tri_total_lbs": r["tri_total_lbs"], "tri_year": r["tri_year"],
        "contam_site_key": r["contam_site_key"],
        "contam_status": r["contam_status"],
    }
    return landfill_data.augment_row(row)


@app.route("/api/landfill/sites")
def api_landfill_sites():
    """All Michigan landfills & disposal-capable hazardous-waste facilities,
    optionally filtered by ?category=. Includes the type/status legend."""
    category = request.args.get("category")
    q = "SELECT * FROM landfill_sites WHERE 1=1"
    params: list = []
    if category and category != "all":
        q += " AND category = ?"
        params.append(category)
    q += " ORDER BY (category='hazardous') DESC, name"
    conn = db()
    rows = conn.execute(q, params).fetchall()
    conn.close()
    sites = [_landfill_row(r) for r in rows]
    return jsonify({
        "count": len(sites),
        "legend": landfill_data.legend_payload(),
        "sites": sites,
    })


@app.route("/api/landfill/county/<fips>")
def api_landfill_county(fips: str):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM landfill_sites WHERE county_fips = ? "
        "ORDER BY (category='hazardous') DESC, name", (fips,)).fetchall()
    conn.close()
    return jsonify({"fips": fips, "count": len(rows),
                    "sites": [_landfill_row(r) for r in rows]})


@app.route("/api/landfill/density")
def api_landfill_density():
    """Per-county landfill counts for the density choropleth."""
    conn = db()
    rows = conn.execute("""
        SELECT c.fips, c.name,
               COUNT(l.id) AS total,
               SUM(CASE WHEN l.category='hazardous' THEN 1 ELSE 0 END) AS hazardous,
               SUM(CASE WHEN l.category='msw' THEN 1 ELSE 0 END) AS msw
          FROM counties c
     LEFT JOIN landfill_sites l ON l.county_fips = c.fips
      GROUP BY c.fips, c.name
      ORDER BY c.name
    """).fetchall()
    conn.close()
    out = [{"fips": r["fips"], "name": r["name"], "value": r["total"],
            "total": r["total"], "hazardous": r["hazardous"] or 0,
            "msw": r["msw"] or 0} for r in rows]
    counts = [r["value"] for r in out if r["value"]]
    return jsonify({
        "counties": out,
        "stats": {"max": max(counts) if counts else 0,
                  "counties_with_sites": len(counts),
                  "total_sites": sum(counts)},
    })


# ---------- Golf courses overlay (OpenStreetMap) ----------

def _golf_row(r) -> dict:
    """Parse a golf_courses row into a JSON-friendly dict with marker glyph/color,
    ownership label, footprint geometry, and context-only cross-refs. No pesticide
    amounts — Michigan publishes none for golf courses (see app/golf_data.py)."""
    geom = None
    if r["geometry"]:
        try:
            geom = json.loads(r["geometry"])
        except (TypeError, ValueError):
            geom = None
    row = {
        "course_key": r["course_key"], "osm_type": r["osm_type"],
        "name": r["name"], "operator": r["operator"],
        "ownership_class": r["ownership_class"],
        "ownership_label": r["ownership_label"], "access": r["access"],
        "address": r["address"], "city": r["city"], "zip": r["zip"],
        "county": r["county"], "county_fips": r["county_fips"],
        "lat": r["latitude"], "lng": r["longitude"],
        "acres": r["acres"], "has_polygon": bool(r["has_polygon"]),
        "geometry": geom, "website": r["website"],
        "high_ag_use": bool(r["high_ag_use"]),
        "county_ag_rank": r["county_ag_rank"],
        "county_ag_total_lbs": r["county_ag_total_lbs"],
        "water_site_id": r["water_site_id"],
        "water_site_name": r["water_site_name"],
        "water_site_km": r["water_site_km"],
        "water_compounds": r["water_compounds"],
    }
    return golf_data.augment_row(row)


@app.route("/api/golf/sites")
def api_golf_sites():
    """All Michigan golf courses from OpenStreetMap, plus the ownership legend and
    the shared (sourced) turf-management context. Optional ?ownership= filter."""
    ownership = request.args.get("ownership")
    q = "SELECT * FROM golf_courses WHERE 1=1"
    params: list = []
    if ownership and ownership != "all":
        q += " AND ownership_class = ?"
        params.append(ownership)
    q += " ORDER BY name"
    conn = db()
    rows = conn.execute(q, params).fetchall()
    conn.close()
    sites = [_golf_row(r) for r in rows]
    return jsonify({
        "count": len(sites),
        "legend": golf_data.legend_payload(),
        "sites": sites,
    })


# ---------- PFAS overlay (Michigan MPART / EGLE) ----------

def _pfas_row(r) -> dict:
    row = {
        "feature_key": r["feature_key"], "kind": r["kind"], "name": r["name"],
        "site_type": r["site_type"], "address": r["address"], "city": r["city"],
        "zip": r["zip"], "county": r["county"], "county_fips": r["county_fips"],
        "lat": r["latitude"], "lng": r["longitude"], "geometry": r["geometry"],
        "residential_wells": r["residential_wells"], "hyperlink": r["hyperlink"],
        "site_lead": r["site_lead"], "site_lead_email": r["site_lead_email"],
        "site_lead_phone": r["site_lead_phone"], "max_ppt": r["max_ppt"],
        "sample_date": r["sample_date"], "props": r["props"],
        "contam_site_key": r["contam_site_key"], "tri_facility_id": r["tri_facility_id"],
        "landfill_site_key": r["landfill_site_key"],
    }
    # Optional curated narrative layer (app/pfas_narratives.py) — guarded so an
    # older DB without the columns, or a malformed value, still serves fine (a bad
    # JSON blob degrades that one field, never 500s the whole feed).
    def _safe_json(v, default):
        try:
            return json.loads(v) if v else default
        except (TypeError, ValueError):
            return default
    keys = r.keys()
    if "narrative" in keys and r["narrative"]:
        row["narrative"] = r["narrative"]
        row["narrative_title"] = r["narrative_title"] if "narrative_title" in keys else None
        row["narrative_facts"] = _safe_json(r["narrative_facts"], {})
        row["narrative_refs"] = _safe_json(r["narrative_refs"], [])
    # Drop null columns before serializing. Most fields are kind-specific (a pws
    # hexbin has no address/site_lead/hyperlink, etc.), and 1,449 hexbins each
    # carrying a dozen "key": null pairs is pure payload weight. The client reads
    # missing keys as absent (JS `undefined == null`), so behavior is unchanged.
    row = {k: v for k, v in row.items() if v is not None}
    return pfas_data.augment_row(row)


@app.route("/api/pfas/features")
def api_pfas_features():
    """Michigan PFAS features (MPART/EGLE), optionally filtered by ?kind= (a
    comma-separated list). Includes the legend + caveat."""
    kinds = request.args.get("kind")
    q = "SELECT * FROM pfas_features WHERE 1=1"
    params: list = []
    if kinds and kinds != "all":
        wanted = [k.strip() for k in kinds.split(",") if k.strip()]
        if wanted:
            q += " AND kind IN (%s)" % ",".join("?" * len(wanted))
            params += wanted
    q += " ORDER BY (kind IN ('site','aoi')) DESC, max_ppt DESC NULLS LAST, name"
    conn = db()
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify({"count": len(rows), "legend": pfas_data.legend_payload(),
                    "features": [_pfas_row(r) for r in rows]})


@app.route("/api/pfas/density")
def api_pfas_density():
    """Per-county PFAS Site + Area-of-Interest count for the choropleth option."""
    conn = db()
    rows = conn.execute("""
        SELECT c.fips, c.name,
               COUNT(p.id) AS total,
               SUM(CASE WHEN p.kind='site' THEN 1 ELSE 0 END) AS sites,
               SUM(CASE WHEN p.kind='aoi'  THEN 1 ELSE 0 END) AS aois
          FROM counties c
     LEFT JOIN pfas_features p ON p.county_fips = c.fips AND p.kind IN ('site','aoi')
      GROUP BY c.fips, c.name ORDER BY c.name
    """).fetchall()
    conn.close()
    out = [{"fips": r["fips"], "name": r["name"], "value": r["total"],
            "total": r["total"], "sites": r["sites"] or 0, "aois": r["aois"] or 0}
           for r in rows]
    vals = [r["value"] for r in out if r["value"]]
    return jsonify({"counties": out,
                    "stats": {"max": max(vals) if vals else 0,
                              "counties_with_sites": len(vals),
                              "total_sites": sum(vals)}})


# ---------- EPA air toxics risk (NATA / AirToxScreen) ----------
def _airtoxics_stats(conn) -> dict:
    return {r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM airtoxics_stats")}


@app.route("/api/airtoxics/features")
def api_airtoxics_features():
    """Michigan census-tract air toxics cancer-risk polygons for the choropleth.

    Returns one lightweight feature per tract (geometry already generalized and
    5-dp rounded) with total risk, the eight-category source breakdown, and the
    top contributing pollutants — enough for the popup without a second request.
    Colors are assigned client-side from the value + palette so the legend and the
    fill stay consistent. The response is gzipped by the after_request hook."""
    conn = db()
    rows = conn.execute(
        "SELECT tract_geoid, county_name, total_risk, sources, pollutants, geometry "
        "FROM airtoxics_tracts").fetchall()
    stats = _airtoxics_stats(conn)
    conn.close()
    tracts, mx = [], 0.0
    for r in rows:
        try:
            geom = json.loads(r["geometry"]) if r["geometry"] else None
        except (TypeError, ValueError):
            geom = None
        if not geom:
            continue
        risk = r["total_risk"] or 0
        if risk > mx:
            mx = risk
        tracts.append({
            "g": r["tract_geoid"], "c": r["county_name"], "r": risk,
            "src": json.loads(r["sources"] or "{}"),
            "poll": json.loads(r["pollutants"] or "[]"),
            "geometry": geom,
        })
    legend = airtoxics_data.legend_payload(stats.get("national_avg"), stats.get("mi_avg"))
    return jsonify({
        "count": len(tracts), "tracts": tracts, "legend": legend,
        "stats": {"max": round(mx, 1), "national_avg": stats.get("national_avg"),
                  "mi_avg": stats.get("mi_avg")},
    })


# ---------- Underground Storage Tanks overlay (EGLE RRD) ----------

def _ust_row(r) -> dict:
    # Lean payload: there can be ~32k of these, so we omit per-row label strings
    # (glyph/color/category label/program label/accuracy note) and let the client
    # derive them from the legend + a couple of fields. Null fields are dropped.
    row = {
        "k": r["site_key"], "id": r["facility_id"], "n": r["facility_name"],
        "c": r["category"], "pg": r["regulatory_program"],
        "a": r["address"], "ci": r["city"], "co": r["county"],
        "lat": r["latitude"], "lng": r["longitude"],
        "pm": r["project_manager"], "wu": r["work_unit"],
        "tt": r["total_tanks"], "at": r["active_tanks"],
        "tr": r["total_release"], "orl": r["open_release"], "cr": r["closed_release"],
        "rs": r["release_status"], "cc": r["current_classification"],
        "rk": r["risk_condition"], "ha": r["horizontal_accuracy"],
        "am": 1 if r["address_matched"] else 0, "lu": r["last_updated"],
        "xc": r["contam_site_key"],
    }
    return {k: v for k, v in row.items() if v is not None and v != ""}


@app.route("/api/ust/sites")
def api_ust_sites():
    """Underground storage tanks (EGLE RRD). Given the volume (~32k), the frontend
    lazy-loads by ?category= (comma-separated: leaking_open, leaking_closed,
    licensed) so only the toggled-on categories are fetched."""
    cats = request.args.get("category")
    q = "SELECT * FROM ust_sites WHERE 1=1"
    params: list = []
    if cats and cats != "all":
        wanted = [c.strip() for c in cats.split(",") if c.strip()]
        if wanted:
            q += " AND category IN (%s)" % ",".join("?" * len(wanted))
            params += wanted
    # Prominent (open leaking) first; within a category, higher risk first.
    q += (" ORDER BY (category='leaking_open') DESC, open_release DESC, "
          "facility_name")
    conn = db()
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify({"count": len(rows), "legend": ust_data.legend_payload(),
                    "sites": [_ust_row(r) for r in rows]})


@app.route("/api/ust/density")
def api_ust_density():
    """Per-county OPEN leaking-release count for the choropleth (Wayne leads)."""
    conn = db()
    rows = conn.execute("""
        SELECT c.fips, c.name,
               COALESCE(SUM(u.open_release), 0) AS open_releases,
               SUM(CASE WHEN u.category='leaking_open' THEN 1 ELSE 0 END) AS open_sites
          FROM counties c
     LEFT JOIN ust_sites u ON u.county_fips = c.fips
      GROUP BY c.fips, c.name ORDER BY c.name
    """).fetchall()
    conn.close()
    out = [{"fips": r["fips"], "name": r["name"], "value": r["open_releases"],
            "open_releases": r["open_releases"], "open_sites": r["open_sites"] or 0}
           for r in rows]
    vals = [r["value"] for r in out if r["value"]]
    return jsonify({"counties": out,
                    "stats": {"max": max(vals) if vals else 0,
                              "counties_with_sites": len(vals),
                              "total_sites": sum(vals)}})


# ==========================================================================
# "Check an address" — homebuyer environmental report
# ==========================================================================
#
# PRIVACY (built in, not bolted on): the entered address is used ONLY to geocode
# and build the report, then discarded. It is NEVER stored, NEVER written to any
# database, NEVER logged, and NEVER placed in a URL or query string — the browser
# sends it in a POST body, and the server's access log records only method+path.
# Geocoding is server-side because the US Census geocoder sends no CORS headers
# and the app CSP is connect-src 'self', so the browser cannot call it directly.
#
# HONESTY: two clearly separated sections (point-based "near this address" with
# real haversine distances, vs "county-wide context"), a monitoring-coverage
# safeguard so "no data" is never read as "clean", and qualitative rating bands
# only (never a numeric score, never the words safe/clean/healthy).

_GEOCODE_UA = "MichiganPollutionMap/1.0 (environmental due-diligence research tool; contact via app)"
_ADDR_LOCATOR = None


def _address_locator():
    """Cached point-in-polygon county locator (built once from the counties
    GeoJSON). Reuses the same ray-casting locator the data loader uses."""
    global _ADDR_LOCATOR
    if _ADDR_LOCATOR is None:
        from app.data_loader import _build_county_locator
        _ADDR_LOCATOR = _build_county_locator()
    return _ADDR_LOCATOR


# --- per-IP rate limiter (fixed window). Stores IPs + timestamps only, never the
# address. In-memory; fine for a single-process deployment. ---
_RL_LOCK = threading.Lock()
_RL_HITS: dict = {}
_RL_WINDOW_S = 300
_RL_MAX = 20


def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _RL_LOCK:
        hits = [t for t in _RL_HITS.get(ip, ()) if now - t < _RL_WINDOW_S]
        if len(hits) >= _RL_MAX:
            _RL_HITS[ip] = hits
            return False
        hits.append(now)
        _RL_HITS[ip] = hits
        if len(_RL_HITS) > 4096:            # bound memory
            for k in [k for k, v in list(_RL_HITS.items())
                      if all(now - t > _RL_WINDOW_S for t in v)]:
                _RL_HITS.pop(k, None)
    return True


def _geocode(address: str):
    """US Census geocoder (primary) with OSM Nominatim fallback. Returns
    {lat, lng, matched, source} or None. The address is used only for the
    outbound geocoder request — never stored, never logged here."""
    addr = " ".join(str(address).split()).strip()
    if len(addr) < 3:
        return None
    try:
        q = urllib.parse.urlencode({"address": addr,
                                    "benchmark": "Public_AR_Current", "format": "json"})
        url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + q
        req = urllib.request.Request(url, headers={"User-Agent": _GEOCODE_UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        m = (d.get("result") or {}).get("addressMatches") or []
        if m:
            c = m[0]["coordinates"]
            return {"lat": float(c["y"]), "lng": float(c["x"]),
                    "matched": m[0].get("matchedAddress"),
                    "source": "US Census Bureau Geocoder"}
    except Exception:                        # noqa: BLE001 — fall through to Nominatim
        pass
    try:
        q = urllib.parse.urlencode({"q": addr, "format": "json", "countrycodes": "us",
                                    "limit": 1, "addressdetails": 0})
        url = "https://nominatim.openstreetmap.org/search?" + q
        req = urllib.request.Request(url, headers={"User-Agent": _GEOCODE_UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        if d:
            return {"lat": float(d[0]["lat"]), "lng": float(d[0]["lon"]),
                    "matched": d[0].get("display_name"),
                    "source": "OpenStreetMap Nominatim"}
    except Exception:                        # noqa: BLE001
        pass
    return None


def _bearing_deg(lat1, lon1, lat2, lon2):
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dl))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


_RINGS_MI = (1, 3, 5)


def _layer_block(sorted_pairs, alat, alng, layer, build):
    """sorted_pairs: [(distance_mi, row), ...] ascending. build(row,dist)->dict of
    layer-specific fields. Returns {within(<=5mi, enriched), nearest(any dist),
    rings{1,3,5 counts}, count_5mi}."""
    def mk(dist, row):
        base = {"layer": layer, "distance_mi": round(dist, 1),
                "direction": deg_to_dir16(_bearing_deg(alat, alng,
                                                       row["latitude"], row["longitude"])),
                "lat": row["latitude"], "lng": row["longitude"]}
        base.update(build(row, dist))
        return base
    within = [mk(d, r) for d, r in sorted_pairs if d <= 5][:12]
    nearest = mk(sorted_pairs[0][0], sorted_pairs[0][1]) if sorted_pairs else None
    rings = {str(k): sum(1 for d, _ in sorted_pairs if d <= k) for k in _RINGS_MI}
    return {"within": within, "nearest": nearest, "rings": rings,
            "count_5mi": rings["5"]}


def _sorted_by_distance(rows, alat, alng):
    out = []
    for r in rows:
        la, lo = r["latitude"], r["longitude"]
        if la is None or lo is None:
            continue
        out.append((haversine_mi(alat, alng, la, lo), r))
    out.sort(key=lambda x: x[0])
    return out


def _band(n):
    return "multiple" if n >= 3 else "some" if n >= 1 else "few"


_BAND_LABEL = {
    "few": "Few documented concerns nearby",
    "some": "Some documented concerns nearby",
    "multiple": "Multiple documented concerns nearby",
    "insufficient": "Insufficient data to assess",
}

_REPORT_DISCLAIMERS = [
    "This is not a substitute for a Phase I Environmental Site Assessment — the "
    "professional environmental due-diligence product used in real-estate "
    "transactions. Consult a qualified environmental professional before making a "
    "purchase decision.",
    "For educational purposes only. Not legal, real-estate, medical, or "
    "environmental advice.",
    "Absence of documented hazards does not mean absence of hazards. Closed and "
    "pre-regulation landfills, private agricultural spraying, and many "
    "contamination sources are not comprehensively mapped in public data.",
    "This reflects only what is documented in public datasets. Many hazards are "
    "not publicly mapped, and each underlying dataset has its own coverage limits "
    "(see the layer caveats and Data Sources in the app).",
]

_REPORT_SOURCES = [
    "US Census Bureau Geocoder / OpenStreetMap Nominatim (address → coordinates)",
    "EPA Superfund (SEMS/NPL) — contamination sites",
    "EPA Toxics Release Inventory (TRI) — industrial releases",
    "Michigan EGLE Materials Management — landfills & hazardous-waste facilities",
    "EPA CCR rule / operator CCR pages / EGLE / Earthjustice-EIP Ashtracker — coal ash sites",
    "USGS/EPA Water Quality Portal — water monitoring & pesticide detections",
    "OpenStreetMap — golf courses (locations only)",
    "USGS NAWQA EPest — county agricultural pesticide use (excludes non-agricultural use)",
    "NCI State Cancer Profiles; CDC Tracking / MDHHS — cancer & respiratory rates",
    "Iowa Environmental Mesonet (ASOS) — growing-season prevailing wind",
]


def _report_near(conn, lat, lng):
    """Point-based section: real haversine distances to every layer that supports
    genuine per-facility distance. Returns a dict of layer blocks."""
    # --- Contamination / Superfund ---
    rows = conn.execute(
        "SELECT site_key, site_name, latitude, longitude, county, city, status, "
        "status_class, category, npl_listed, hrs_score FROM contamination_sites").fetchall()
    contam = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng, "contamination",
        lambda r, d: {"id": r["site_key"], "name": r["site_name"], "county": r["county"],
                      "status": r["status"], "status_class": r["status_class"],
                      "npl": bool(r["npl_listed"]), "hrs_score": r["hrs_score"]})

    # --- TRI industrial facilities (with latest-year total + multi-year trend) ---
    rows = conn.execute(
        "SELECT facility_id, facility_name, latitude, longitude, county, city, "
        "industry_sector FROM tri_facility").fetchall()

    def _tri_build(r, d):
        py = conn.execute("SELECT year, SUM(total_lbs) t FROM tri_release "
                          "WHERE facility_id=? GROUP BY year ORDER BY year",
                          (r["facility_id"],)).fetchall()
        vals = [p["t"] or 0 for p in py]
        trend = "flat"
        if len(vals) >= 2 and vals[0] > 0:
            ch = (vals[-1] - vals[0]) / vals[0]
            trend = "up" if ch > 0.15 else "down" if ch < -0.15 else "flat"
        return {"id": r["facility_id"], "name": r["facility_name"], "county": r["county"],
                "sector": r["industry_sector"],
                "latest_release_lbs": round(vals[-1]) if vals else 0,
                "latest_year": py[-1]["year"] if py else None, "trend": trend}
    tri = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng, "tri", _tri_build)

    # --- Landfills & waste facilities ---
    rows = conn.execute(
        "SELECT site_key, name, latitude, longitude, county, category, type_label, "
        "status_class, status_label FROM landfill_sites").fetchall()
    landfill = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng, "landfill",
        lambda r, d: {"id": r["site_key"], "name": r["name"], "county": r["county"],
                      "category": r["category"], "type_label": r["type_label"],
                      "status": r["status_label"]})

    # --- Water monitoring sites (with detection/exceedance summary) ---
    rows = conn.execute(
        "SELECT site_id, site_name, latitude, longitude, county, water_body, site_type "
        "FROM water_quality_sites WHERE latitude IS NOT NULL").fetchall()

    def _water_build(r, d):
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(detected),0) det, "
            "COALESCE(SUM(exceeds_mcl),0) mcl, COALESCE(SUM(exceeds_benchmark),0) bench, "
            "MAX(sample_date) latest FROM water_quality_results WHERE site_id=?",
            (r["site_id"],)).fetchone()
        sev = _site_severity(agg["det"], agg["mcl"], agg["n"], agg["bench"])
        comps = [c["compound"] for c in conn.execute(
            "SELECT compound FROM water_quality_results WHERE site_id=? AND detected=1 "
            "GROUP BY compound ORDER BY SUM(exceeds_mcl) DESC, SUM(exceeds_benchmark) DESC, "
            "COUNT(*) DESC LIMIT 4", (r["site_id"],)).fetchall()]
        return {"id": r["site_id"], "name": r["site_name"], "county": r["county"],
                "water_body": r["water_body"], "severity": sev,
                "detections": agg["det"], "mcl_exceedances": agg["mcl"],
                "benchmark_exceedances": agg["bench"], "latest_sample": agg["latest"],
                "top_compounds": comps}
    water = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng, "water", _water_build)

    # --- Golf courses ---
    rows = conn.execute(
        "SELECT course_key, name, latitude, longitude, county, ownership_class, "
        "ownership_label, acres FROM golf_courses").fetchall()
    golf = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng, "golf",
        lambda r, d: {"id": r["course_key"], "name": r["name"], "county": r["county"],
                      "ownership_class": r["ownership_class"], "acres": r["acres"]})

    # --- PFAS sites & Areas of Interest (AOIs flag areas where residential wells
    # may be affected — especially relevant to a homebuyer) ---
    rows = conn.execute(
        "SELECT feature_key, kind, name, latitude, longitude, county, site_type, "
        "residential_wells, hyperlink FROM pfas_features WHERE kind IN ('site','aoi')").fetchall()
    pfas = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng, "pfas",
        lambda r, d: {"id": r["feature_key"], "name": r["name"], "county": r["county"],
                      "kind": r["kind"], "site_type": r["site_type"],
                      "residential_wells": r["residential_wells"], "hyperlink": r["hyperlink"]})

    # --- PFAS surface-water sampling ---
    rows = conn.execute(
        "SELECT feature_key, name, latitude, longitude, county, max_ppt, sample_date, props "
        "FROM pfas_features WHERE kind='surface_water'").fetchall()
    def _pfas_water(r, d):
        try:
            p = json.loads(r["props"] or "{}")
        except (TypeError, ValueError):
            p = {}
        return {"id": r["feature_key"], "name": r["name"], "county": r["county"],
                "max_ppt": r["max_ppt"], "sample_date": r["sample_date"],
                "waterbody": p.get("waterbody"), "detected": p.get("detected")}
    pfas_water = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng,
                              "pfas_water", _pfas_water)

    # --- Underground storage tanks. Open leaking releases are called out
    # separately and prominently from closed/licensed tanks (the whole point:
    # an old leaking gas station nearby is real information a buyer rarely gets). ---
    def _ust_build(r, d):
        return {"id": r["site_key"], "name": r["facility_name"], "county": r["county"],
                "category": r["category"], "address": r["address"], "city": r["city"],
                "open_release": r["open_release"], "total_release": r["total_release"],
                "classification": r["current_classification"],
                "address_matched": bool(r["address_matched"]),
                "program": r["regulatory_program"]}
    rows = conn.execute(
        "SELECT site_key, facility_name, latitude, longitude, county, category, "
        "address, city, open_release, total_release, current_classification, "
        "address_matched, regulatory_program FROM ust_sites "
        "WHERE category='leaking_open'").fetchall()
    ust_open = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng,
                            "ust_open", _ust_build)
    rows = conn.execute(
        "SELECT site_key, facility_name, latitude, longitude, county, category, "
        "address, city, open_release, total_release, current_classification, "
        "address_matched, regulatory_program FROM ust_sites "
        "WHERE category IN ('leaking_closed','licensed')").fetchall()
    ust_other = _layer_block(_sorted_by_distance(rows, lat, lng), lat, lng,
                             "ust_other", _ust_build)

    return {"contamination": contam, "tri": tri, "landfill": landfill,
            "water": water, "golf": golf, "pfas": pfas, "pfas_water": pfas_water,
            "ust_open": ust_open, "ust_other": ust_other}


def _report_spraying(alat, alng, fips, locate):
    """Spraying programs whose coverage includes this address: statewide programs
    always apply; a county program applies if its point is in this county; other
    scopes are included when within ~25 mi (their point is a representative
    location, not a boundary)."""
    out = []
    for p in spraying_programs.programs_payload().get("programs", []):
        pl, po, scope = p.get("lat"), p.get("lon"), p.get("scope")
        covered, dist = False, None
        if scope == "statewide":
            covered = True
        elif pl is not None and po is not None:
            dist = haversine_mi(alat, alng, pl, po)
            pfips, _ = locate(po, pl)
            if scope == "county" and pfips and pfips == fips:
                covered = True
            elif dist <= 25:
                covered = True
        if covered:
            item = {"layer": "spraying", "id": p.get("id"), "name": p.get("name"),
                    "type": p.get("type"), "scope": scope, "area": p.get("area"),
                    "url": p.get("url"), "lat": pl, "lng": po}
            if dist is not None:
                item["distance_mi"] = round(dist, 1)
                item["direction"] = deg_to_dir16(_bearing_deg(alat, alng, pl, po))
            out.append(item)
    out.sort(key=lambda x: (x.get("scope") != "statewide", x.get("distance_mi") or 0))
    return out


def _report_coal_ash(alat, alng):
    """Coal ash (CCR) sites near this address. These curated sites carry real
    per-facility coordinates, so this is a genuine distance section. Several sit
    on populated waterfronts, so we surface any within ~10 miles (with the 5-mile
    ring count feeding the same 'nearby concerns' framing as the other layers)."""
    pairs = []
    for s in coal_ash_data.sites_payload()["sites"]:
        la, lo = s.get("lat"), s.get("lon")
        if la is None or lo is None:
            continue
        pairs.append((haversine_mi(alat, alng, la, lo), s))
    pairs.sort(key=lambda x: x[0])

    def mk(dist, s):
        return {"layer": "coal_ash", "id": s["id"], "name": s["name"],
                "operator": s["operator"], "county": s["county"],
                "status": s["status"], "status_label": s["status_label"],
                "unlined": s["unlined"], "unit_type_label": s["unit_type_label"],
                "url": s["ccr_url"], "distance_mi": round(dist, 1),
                "direction": deg_to_dir16(_bearing_deg(alat, alng, s["lat"], s["lon"])),
                "lat": s["lat"], "lng": s["lon"]}

    within = [mk(d, s) for d, s in pairs if d <= 10][:8]
    nearest = mk(pairs[0][0], pairs[0][1]) if pairs else None
    rings = {str(k): sum(1 for d, _ in pairs if d <= k) for k in _RINGS_MI}
    return {"within": within, "nearest": nearest, "rings": rings,
            "count_5mi": rings["5"]}


def _report_county_context(conn, fips):
    """County-wide context — describes the WHOLE county, not the parcel."""
    ctx = {}
    # Agricultural pesticide use (latest EPest year) + per-acre + statewide rank.
    yr = conn.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]
    ctx["pesticide_year"] = yr
    if yr is not None:
        avg = ("(COALESCE(epest_low_kg,epest_high_kg)+COALESCE(epest_high_kg,epest_low_kg))/2.0")
        totals = conn.execute(
            f"SELECT county_fips, SUM({avg}) kg FROM pesticide_use WHERE year=? "
            "GROUP BY county_fips HAVING kg>0 ORDER BY kg DESC", (yr,)).fetchall()
        rank_by = {r["county_fips"]: i + 1 for i, r in enumerate(totals)}
        kg_by = {r["county_fips"]: r["kg"] for r in totals}
        acres = _cropland_acres_by_fips(conn).get(fips)
        county_lbs = kg_by[fips] * KG_TO_LB if fips in kg_by else None
        ctx["pesticide"] = {
            "total_lbs": round(county_lbs) if county_lbs else None,
            "per_acre_lbs": round(county_lbs / acres, 2)
                            if (county_lbs and acres and acres >= 10000) else None,
            "cropland_acres": round(acres) if acres else None,
            "statewide_rank": rank_by.get(fips), "counties_ranked": len(totals),
            "note": ("EPest estimates AGRICULTURAL use only — golf courses, lawns, "
                     "and other non-agricultural use are excluded from these totals."),
        }
    # Cancer (Non-Hodgkin lymphoma — the app's pesticide-linked headline) vs state.
    crow = conn.execute(
        "SELECT rate, suppressed FROM cancer_incidence WHERE county_fips=? AND "
        "cancer_type='nhl' AND stage='all' AND data_type='incidence'", (fips,)).fetchone()
    cref = conn.execute(
        "SELECT mi_rate FROM cancer_reference WHERE cancer_type='nhl' AND "
        "data_type='incidence' AND stage='all'").fetchone()
    if crow is not None and cref is not None:
        rate = None if crow["suppressed"] else crow["rate"]
        ctx["cancer_nhl"] = {
            "label": "Non-Hodgkin lymphoma incidence", "county_rate": rate,
            "state_rate": cref["mi_rate"], "suppressed": bool(crow["suppressed"]),
            "pct_vs_state": (round((rate - cref["mi_rate"]) / cref["mi_rate"] * 100)
                             if (rate and cref["mi_rate"]) else None),
        }
    # Respiratory (adult asthma ED visits, latest year) vs statewide baseline.
    ry = conn.execute("SELECT MAX(year) FROM respiratory_ed_visits "
                      "WHERE condition='asthma'").fetchone()[0]
    if ry is not None:
        rrow = conn.execute("SELECT visit_rate, suppressed FROM respiratory_ed_visits "
                            "WHERE county_fips=? AND condition='asthma' AND year=?",
                            (fips, ry)).fetchone()
        base = MI_STATEWIDE_BASELINE.get("asthma_ed_visit_rate")
        if rrow is not None and not rrow["suppressed"] and rrow["visit_rate"] is not None:
            ctx["respiratory_asthma"] = {
                "label": "Adult asthma ED visits (per 10,000)",
                "county_rate": rrow["visit_rate"], "state_rate": base, "year": ry,
                "pct_vs_state": (round((rrow["visit_rate"] - base) / base * 100)
                                 if base else None)}
    # Densities: contamination, landfills, TRI totals.
    cd = conn.execute("SELECT COUNT(*) t, COALESCE(SUM(CASE WHEN status_class='npl' "
                      "THEN 1 ELSE 0 END),0) npl FROM contamination_sites WHERE county_fips=?",
                      (fips,)).fetchone()
    ld = conn.execute("SELECT COUNT(*) t, COALESCE(SUM(CASE WHEN category='hazardous' "
                      "THEN 1 ELSE 0 END),0) haz FROM landfill_sites WHERE county_fips=?",
                      (fips,)).fetchone()
    triy = conn.execute("SELECT MAX(year) FROM tri_release").fetchone()[0]
    tri_total = conn.execute(
        "SELECT COALESCE(SUM(rl.total_lbs),0) FROM tri_release rl "
        "JOIN tri_facility f ON f.facility_id=rl.facility_id "
        "WHERE f.county_fips=? AND rl.year=?", (fips, triy)).fetchone()[0]
    tri_count = conn.execute("SELECT COUNT(*) FROM tri_facility WHERE county_fips=?",
                             (fips,)).fetchone()[0]
    ctx["density"] = {
        "contamination_sites": cd["t"], "npl_sites": cd["npl"],
        "landfills": ld["t"], "hazardous_landfills": ld["haz"],
        "tri_facilities": tri_count, "tri_total_lbs": round(tri_total),
        "tri_year": triy}
    return ctx


# Cached point-in-tract index for the air toxics section of the address report.
# Built once from the tract geometries (same "cache until restart" pattern the
# county/watershed locators use; a refresh + restart rebuilds it).
_ATX_INDEX = None


def _atx_index():
    global _ATX_INDEX
    if _ATX_INDEX is not None:
        return _ATX_INDEX
    conn = db()
    try:
        rows = conn.execute(
            "SELECT tract_geoid, county_name, total_risk, sources, pollutants, geometry "
            "FROM airtoxics_tracts").fetchall()
    finally:
        conn.close()
    idx = []
    for r in rows:
        try:
            geom = json.loads(r["geometry"]) if r["geometry"] else None
        except (TypeError, ValueError):
            geom = None
        if not geom:
            continue
        if geom["type"] == "Polygon":
            outer_rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            outer_rings = [poly[0] for poly in geom["coordinates"]]
        else:
            continue
        boxed = []
        for ring in outer_rings:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            boxed.append((min(xs), min(ys), max(xs), max(ys), ring))
        idx.append((r["tract_geoid"], r["county_name"], r["total_risk"],
                    r["sources"], r["pollutants"], boxed))
    _ATX_INDEX = idx
    return idx


def _report_airtoxics(lat, lng, stats):
    """The air toxics section of the homebuyer report: the modeled cancer risk for
    the census tract containing this point, how it compares to the Michigan and
    national tract averages, and the dominant source category — framed as
    AREA-LEVEL context with EPA's screening caveats, never a property finding."""
    hit = None
    for geoid, cty, total, srcjson, polljson, boxed in _atx_index():
        for (minx, miny, maxx, maxy, ring) in boxed:
            if minx <= lng <= maxx and miny <= lat <= maxy and _pip(lng, lat, ring):
                hit = (geoid, cty, total, srcjson, polljson)
                break
        if hit:
            break
    if not hit:
        return None
    geoid, cty, total, srcjson, polljson = hit
    try:
        sources = json.loads(srcjson or "{}")
    except (TypeError, ValueError):
        sources = {}
    try:
        polls = json.loads(polljson or "[]")
    except (TypeError, ValueError):
        polls = []
    ssum = sum(sources.values()) or 1.0
    src_list = sorted(
        ({"key": k, "label": airtoxics_data.SOURCE_META.get(k, {}).get("label", k),
          "color": airtoxics_data.SOURCE_META.get(k, {}).get("color", "#8a94a3"),
          "gloss": airtoxics_data.SOURCE_META.get(k, {}).get("gloss", ""),
          "risk": round(v, 2), "pct": round(v / ssum * 100)}
         for k, v in sources.items()), key=lambda s: s["risk"], reverse=True)
    dominant = src_list[0] if src_list else None
    mi_avg = stats.get("mi_avg")
    vs_mi = round((total - mi_avg) / mi_avg * 100) if mi_avg else None
    return {
        "tract_geoid": geoid, "county": cty, "total_risk": round(total, 1),
        "mi_avg": mi_avg, "national_avg": stats.get("national_avg"),
        "vs_mi_pct": vs_mi, "dominant": dominant, "sources": src_list,
        "pollutants": polls, "assessment": airtoxics_data.ASSESSMENT_LABEL,
        "caveats": airtoxics_data.CAVEATS,
    }


@app.route("/api/address-report", methods=["POST"])
def api_address_report():
    """Homebuyer environmental report for one address. PRIVACY: the address is
    read from the POST body, used only to geocode + build the report, and then
    discarded — never stored, never logged, never echoed into a URL."""
    ip = request.remote_addr or "unknown"
    if not _rate_ok(ip):
        return jsonify({"error": "rate_limited",
                        "message": "Too many lookups from your connection. Please wait "
                        "a few minutes and try again."}), 429
    body = request.get_json(silent=True) or {}
    address = body.get("address")
    if not isinstance(address, str) or not (3 <= len(address.strip()) <= 250):
        return jsonify({"error": "bad_address",
                        "message": "Please enter a street address, city, and ZIP."}), 400

    geo = _geocode(address)
    del address, body                      # drop the address ASAP; never persisted
    if not geo:
        return jsonify({"error": "geocode_failed",
                        "message": "Couldn't find that address — try including the "
                        "city and ZIP code."}), 422

    lat, lng = geo["lat"], geo["lng"]
    locate = _address_locator()
    fips, county = locate(lng, lat)
    location = {"lat": round(lat, 6), "lng": round(lng, 6),
                "matched_address": geo.get("matched"), "geocoder": geo.get("source"),
                "county": county, "county_fips": fips}
    if not fips:
        return jsonify({"location": location, "in_michigan": False,
                        "message": "This location does not appear to be in Michigan. "
                        "This tool only covers Michigan environmental data.",
                        "disclaimers": _REPORT_DISCLAIMERS}), 200

    conn = db()
    try:
        near = _report_near(conn, lat, lng)
        near["spraying"] = _report_spraying(lat, lng, fips, locate)
        near["coal_ash"] = _report_coal_ash(lat, lng)
        ctx = _report_county_context(conn, fips)

        # --- Monitoring coverage (the "no data != clean" safeguard) ---
        # "No data" must never read as "clean". We surface how well-monitored this
        # location actually is, and warn prominently when it is not.
        water_nearest = near["water"]["nearest"]
        water_nearest_mi = water_nearest["distance_mi"] if water_nearest else None
        contam_nearest = near["contamination"]["nearest"]
        landfill_nearest = near["landfill"]["nearest"]
        contam_mi = contam_nearest["distance_mi"] if contam_nearest else None
        landfill_mi = landfill_nearest["distance_mi"] if landfill_nearest else None
        county_water_sites = conn.execute(
            "SELECT COUNT(*) FROM water_quality_sites WHERE county_fips=?", (fips,)).fetchone()[0]
        county_has_tri = ctx["density"]["tri_facilities"] > 0

        # Water is the primary local-monitoring signal; >10 mi (or a county with
        # ≤1 site) means genuinely limited local water data.
        water_sparse = (water_nearest_mi is None) or (water_nearest_mi > 10) \
            or (county_water_sites <= 1)
        notes = []
        if water_nearest_mi is None:
            notes.append("No water-quality monitoring sites are mapped near this address.")
        elif water_nearest_mi > 10:
            notes.append(f"The nearest water-sampling site is {round(water_nearest_mi)} "
                         "miles away, so local water-quality data is limited.")
        if county_water_sites <= 1:
            notes.append(f"This county has {'no' if county_water_sites == 0 else 'only one'} "
                         "mapped water-monitoring site.")
        if not county_has_tri:
            notes.append("No TRI-reporting industrial facilities are registered in this "
                         "county; facilities below federal reporting thresholds are never "
                         "listed anywhere.")
        if contam_mi is not None and contam_mi > 15:
            notes.append(f"The nearest mapped contamination/Superfund site is "
                         f"{round(contam_mi)} miles away — note that closed and "
                         "pre-regulation sites are not comprehensively mapped.")
        # Overall coverage is sparse when water data is limited, or when the whole
        # neighbourhood is far from any mapped facility of every kind.
        sparse = water_sparse or (
            (contam_mi is None or contam_mi > 25)
            and (landfill_mi is None or landfill_mi > 25)
            and (water_nearest_mi is None or water_nearest_mi > 10))
        coverage = {
            "nearest_water_site_mi": water_nearest_mi,
            "nearest_water_site_name": water_nearest["name"] if water_nearest else None,
            "nearest_contamination_mi": contam_mi,
            "nearest_landfill_mi": landfill_mi,
            "county_water_sites": county_water_sites,
            "county_has_tri": county_has_tri,
            "sparse": sparse, "water_sparse": water_sparse,
            "notes": notes, "warning": None,
        }
        if water_nearest_mi is not None and water_nearest_mi > 10:
            coverage["warning"] = (
                f"Limited local monitoring data — the nearest water-sampling site is "
                f"{round(water_nearest_mi)} miles away. Absence of detections here does "
                f"not mean absence of contamination.")
        elif water_sparse:
            coverage["warning"] = (
                "Limited local monitoring data — few or no water-sampling sites cover "
                "this area. Absence of detections does not mean absence of contamination.")

        # --- Downwind check (prevailing growing-season wind only) ---
        stations = _wind_stations(conn)
        ns = _nearest_station(lat, lng, stations)
        downwind = None
        if ns and ns.get("direction_deg") is not None:
            from_deg = float(ns["direction_deg"])
            upwind = []
            for it in (near["tri"]["within"] + near["landfill"]["within"]):
                b = _bearing_deg(lat, lng, it["lat"], it["lng"])
                diff = abs((b - from_deg + 180) % 360 - 180)
                if diff <= 45:
                    upwind.append({"name": it["name"], "layer": it["layer"],
                                   "distance_mi": it["distance_mi"], "id": it["id"],
                                   "lat": it["lat"], "lng": it["lng"]})
            upwind.sort(key=lambda x: x["distance_mi"])
            downwind = {
                "prevailing_from": deg_to_dir16(from_deg), "from_deg": round(from_deg),
                "station": ns.get("station_name"), "station_mi": ns.get("distance_mi"),
                "upwind": upwind[:6],
                "note": ("Prevailing growing-season (Apr–Sep) wind direction only — "
                         "this is directional context, not a dispersion or plume model."),
            }

        # --- Qualitative rating (bands only; never a number, never safe/clean) ---
        water_near_conc = sum(1 for it in near["water"]["within"]
                              if it.get("severity") in ("exceeds_mcl", "exceeds_benchmark"))
        rank = (ctx.get("pesticide") or {}).get("statewide_rank")
        n_co = (ctx.get("pesticide") or {}).get("counties_ranked") or 83
        cats = {
            "contamination": _band(near["contamination"]["count_5mi"]),
            "industrial": _band(near["tri"]["count_5mi"]),
            "waste": _band(near["landfill"]["count_5mi"]),
            # Water is graded on documented exceedances, but only when there is
            # enough local sampling to say anything — otherwise "insufficient".
            "water": "insufficient" if water_sparse else _band(water_near_conc),
            "pesticides": ("multiple" if (rank and rank <= max(1, n_co // 4))
                           else "some" if (rank and rank <= n_co // 2) else "few"),
        }
        near_total = (near["contamination"]["count_5mi"] + near["tri"]["count_5mi"]
                      + near["landfill"]["count_5mi"] + water_near_conc)
        contam_far = (contam_mi is None or contam_mi > 20)
        # Overall is "insufficient" only when coverage is sparse AND nothing was
        # documented nearby — i.e. we genuinely cannot say either way.
        if sparse and near_total == 0 and contam_far:
            overall = "insufficient"
        else:
            order = {"few": 0, "some": 1, "multiple": 2}
            concrete = [v for v in cats.values() if v != "insufficient"]
            overall = max(concrete, key=lambda v: order[v]) if concrete else "insufficient"
        rating = {
            "overall": overall, "overall_label": _BAND_LABEL[overall],
            "categories": {k: {"band": v, "label": _BAND_LABEL[v]} for k, v in cats.items()},
            "adjacent_note": ("This reflects only what is documented in public "
                              "datasets. Many hazards are not publicly mapped."),
        }

        air_toxics = _report_airtoxics(lat, lng, _airtoxics_stats(conn))

        report = {
            "location": location, "in_michigan": True,
            "near": near, "county_context": ctx, "monitoring": coverage,
            "air_toxics": air_toxics,
            "downwind": downwind, "rating": rating,
            "rings_mi": list(_RINGS_MI),
            "disclaimers": _REPORT_DISCLAIMERS, "sources": _REPORT_SOURCES,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
    finally:
        conn.close()
    return jsonify(report)


@app.route("/api/correlation/contamination")
def api_correlation_contamination():
    """Cancer incidence vs contamination-site count per county (scatter +
    Pearson/Spearman + quartile comparison). ?metric=count|npl."""
    cancer = _cancer_key(request.args.get("cancer"))
    metric = request.args.get("metric", "count")   # count | npl
    exclude_urban = _bool_arg("exclude_urban")
    rural_only = _bool_arg("rural_only")
    stc = "npl" if metric == "npl" else None
    conn = db()
    counts = _contam_count_by_fips(conn, stc)
    rows = conn.execute(
        """SELECT ci.county_fips AS f, ci.county AS county, ci.rate AS rate,
                  ca.is_urban AS is_urban
             FROM cancer_incidence ci
        LEFT JOIN correlation_analysis ca ON ca.county_fips = ci.county_fips
            WHERE ci.cancer_type = ? AND ci.data_type = 'incidence'
                  AND ci.stage = 'all'""", (cancer,)).fetchall()
    conn.close()
    pts = []
    for r in rows:
        if r["rate"] is None:
            continue
        if (exclude_urban or rural_only) and r["is_urban"]:
            continue
        pts.append({"county": r["county"], "is_urban": bool(r["is_urban"]),
                    "x": counts.get(r["f"], 0), "y": r["rate"]})
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    pear = pearson(xs, ys)
    spear = spearman(xs, ys)
    line = None
    if pear.get("slope") is not None and xs and max(xs) > min(xs):
        xmin, xmax = min(xs), max(xs)
        line = [{"x": xmin, "y": pear["intercept"] + pear["slope"] * xmin},
                {"x": xmax, "y": pear["intercept"] + pear["slope"] * xmax}]
    qc = None
    if len(pts) >= 4:
        sx = sorted(pts, key=lambda p: p["x"])
        q = max(1, len(sx) // 4)
        top = [p["y"] for p in sx[-q:]]
        bot = [p["y"] for p in sx[:q]]
        t = welch_t_test(top, bot)
        qc = {"top_mean": t.get("mean_a"), "bottom_mean": t.get("mean_b"),
              "welch_t_test": t}
    label = cancer_data.CANCER_BY_KEY[cancer]["label"]
    pest_label = "Superfund (NPL) sites" if stc else "contamination sites"
    return jsonify({
        "cancer": cancer, "cancer_label": label, "metric": metric,
        "x_label": f"{pest_label} per county (count)",
        "y_label": f"{label} — cases per 100,000",
        "points": pts, "fit": pear, "spearman": spear, "trend_line": line,
        "quartile_comparison": qc, "n": len(pts),
        "interpretation": _cancer_interp(label, pest_label, pear, spear, qc, "incidence"),
    })


# ---------- entrypoint ----------

if __name__ == "__main__":
    from app.config import require_db
    require_db()  # fail fast if the DB wasn't fetched/built (serves empty otherwise)
    print(f" * Michigan Pollution Map serving on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
