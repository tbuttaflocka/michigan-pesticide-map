"""Michigan Pesticide Application Heat Map — Flask backend.

Usage:
    python -m app.data_loader   # one-time, downloads and populates SQLite
    python app.py               # runs the web server on :8080
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from app import database
from app import cancer_data
from app import contamination_data
from app.config import GEOJSON_PATH, HOST, PORT
from app.config import EPA_SITE_PROFILE
from app.config import MI_HUC8_GEOJSON_PATH
from app.cwd_data import SURVEILLANCE_STATS
from app.respiratory_data import (
    GROWING_SEASON_MONTHS,
    ICD10_RESP_RANGES,
    MI_BROADER_RESP_BASELINE,
    MI_STATEWIDE_BASELINE,
    SEASONAL_PATTERN,
    URBAN_COUNTIES,
)
from app.stats import pearson, spearman, welch_t_test
from app.water_quality import PESTICIDE_MCL, AQUATIC_LIFE_BENCHMARKS, threshold_for
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


@app.route("/api/search")
def api_search():
    """Free-text search over counties and compounds."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return lb_jsonify({"counties": [], "compounds": []})
    like = f"%{q.upper()}%"
    conn = db()
    cur = conn.cursor()
    counties = [dict(r) for r in cur.execute(
        "SELECT fips, name FROM counties WHERE UPPER(name) LIKE ? ORDER BY name LIMIT 10",
        (like,),
    )]
    compounds = [r[0] for r in cur.execute(
        "SELECT DISTINCT compound FROM pesticide_use WHERE compound LIKE ? ORDER BY compound LIMIT 15",
        (like,),
    )]
    conn.close()
    return lb_jsonify({"counties": counties, "compounds": compounds})


# ---------- CWD endpoints ----------

@app.route("/api/cwd/counties")
def api_cwd_counties():
    """One row per CWD-positive county with summary fields for the choropleth."""
    conn = db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT county, county_fips,
               SUM(total_positives) AS positives,
               MIN(first_detected)  AS first_detected,
               GROUP_CONCAT(DISTINCT township) AS townships,
               MIN(notes)           AS notes
          FROM cwd_wild_deer
         GROUP BY county, county_fips
         ORDER BY positives DESC
    """).fetchall()
    conn.close()
    return lb_jsonify({
        "counties": [dict(r) for r in rows],
        "stats": SURVEILLANCE_STATS,
    })


@app.route("/api/cwd/points")
def api_cwd_points():
    """Per-township CWD marker points (lat/lon present)."""
    conn = db()
    rows = conn.execute("""
        SELECT county, county_fips, township, latitude, longitude,
               first_detected, total_positives, source, notes
          FROM cwd_wild_deer
         WHERE latitude IS NOT NULL AND longitude IS NOT NULL
         ORDER BY first_detected
    """).fetchall()
    conn.close()
    return lb_jsonify({"points": [dict(r) for r in rows]})


@app.route("/api/cwd/timeline")
def api_cwd_timeline():
    """Per-year list of counties that turned positive — drives the animation."""
    conn = db()
    rows = conn.execute("""
        SELECT county, county_fips,
               MIN(SUBSTR(first_detected, 1, 4)) AS year,
               SUM(total_positives) AS positives
          FROM cwd_wild_deer
         GROUP BY county, county_fips
    """).fetchall()
    conn.close()
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        try:
            y = int(r["year"])
        except (TypeError, ValueError):
            continue
        by_year.setdefault(y, []).append({
            "county": r["county"], "county_fips": r["county_fips"],
            "positives": r["positives"],
        })
    cumulative = []
    seen: set[str] = set()
    for y in sorted(by_year):
        for c in by_year[y]:
            seen.add(c["county_fips"])
        cumulative.append({
            "year": y,
            "new_counties": [c["county"] for c in by_year[y]],
            "cumulative_counties": sorted(seen),
        })
    return lb_jsonify({"by_year": [
        {"year": y, "counties": by_year[y]} for y in sorted(by_year)
    ], "cumulative": cumulative})


@app.route("/api/cwd/farmed")
def api_cwd_farmed():
    conn = db()
    rows = conn.execute("""
        SELECT county, county_fips, facilities_positive,
               first_detected, source, notes
          FROM cwd_farmed_deer
         ORDER BY facilities_positive DESC
    """).fetchall()
    # attach county centroid (approx) for marker placement: average of geojson bbox
    # provided by counties table area is not enough — we just emit FIPS and the
    # frontend looks up the matching county GeoJSON feature for its centroid.
    conn.close()
    return lb_jsonify({"facilities": [dict(r) for r in rows]})


@app.route("/api/cwd/surveillance")
def api_cwd_surveillance():
    """County → surveillance year list, plus per-year county lists."""
    conn = db()
    rows = conn.execute("""
        SELECT county, county_fips, surveillance_year
          FROM cwd_surveillance
         ORDER BY surveillance_year, county
    """).fetchall()
    conn.close()
    by_year: dict[int, list[str]] = {}
    by_fips: dict[str, list[int]] = {}
    for r in rows:
        by_year.setdefault(r["surveillance_year"], []).append(r["county_fips"])
        by_fips.setdefault(r["county_fips"], []).append(r["surveillance_year"])
    return lb_jsonify({
        "by_year": [{"year": y, "county_fips": v} for y, v in sorted(by_year.items())],
        "by_county": [{"county_fips": f, "years": v} for f, v in by_fips.items()],
    })


# ---------- Correlation analysis endpoints ----------

_METRIC_COLUMNS = {
    "total":       "total_pesticide_kg",
    "per_sq_mile": "pesticide_per_sq_mile",
    "herbicide":   "herbicide_kg",
    "insecticide": "insecticide_kg",
    "fungicide":   "fungicide_kg",
}


@app.route("/api/correlation")
def api_correlation():
    """Full comparison table — one row per county."""
    conn = db()
    rows = conn.execute("""
        SELECT * FROM correlation_analysis
         ORDER BY total_pesticide_kg DESC NULLS LAST
    """).fetchall()
    conn.close()
    return lb_jsonify({"rows": [dict(r) for r in rows]})


@app.route("/api/correlation/scatter")
def api_correlation_scatter():
    """Points + OLS trend line for the scatter chart. x values are kg from
    the DB; we pre-convert to lbs here so the response is unit-clean."""
    metric = request.args.get("metric", "total")
    col = _METRIC_COLUMNS.get(metric, "total_pesticide_kg")
    conn = db()
    rows = conn.execute(f"""
        SELECT county_fips, county, {col} AS x, cwd_positives_count AS y,
               cwd_positive
          FROM correlation_analysis
    """).fetchall()
    conn.close()
    pts = []
    for r in rows:
        x_kg = r["x"]
        pts.append({
            "county_fips": r["county_fips"], "county": r["county"],
            "x": x_kg * KG_TO_LB if x_kg is not None else None,
            "y": r["y"], "cwd_positive": r["cwd_positive"],
        })
    xs = [p["x"] for p in pts if p["x"] is not None]
    ys = [p["y"] for p in pts if p["x"] is not None]
    fit = pearson(xs, ys)
    line = None
    if fit.get("slope") is not None and xs:
        xmin, xmax = min(xs), max(xs)
        line = [
            {"x": xmin, "y": fit["intercept"] + fit["slope"] * xmin},
            {"x": xmax, "y": fit["intercept"] + fit["slope"] * xmax},
        ]
    return jsonify({
        "metric": metric,
        "points": pts,
        "fit": fit,
        "trend_line": line,
    })


@app.route("/api/correlation/stats")
def api_correlation_stats():
    """Welch t-test + Pearson r for CWD-positive vs CWD-negative county pesticide use.
    Group means/SDs are pre-converted to lbs."""
    metric = request.args.get("metric", "total")
    col = _METRIC_COLUMNS.get(metric, "total_pesticide_kg")
    conn = db()
    rows = conn.execute(f"""
        SELECT {col} AS v, cwd_positive, cwd_positives_count
          FROM correlation_analysis
    """).fetchall()
    conn.close()
    pos = [r["v"] * KG_TO_LB for r in rows if r["cwd_positive"] and r["v"] is not None]
    neg = [r["v"] * KG_TO_LB for r in rows if not r["cwd_positive"] and r["v"] is not None]
    t = welch_t_test(pos, neg)
    cont = pearson(
        [r["v"] * KG_TO_LB for r in rows if r["v"] is not None],
        [r["cwd_positives_count"] for r in rows if r["v"] is not None],
    )
    return jsonify({
        "metric": metric,
        "n_positive_counties": len(pos),
        "n_negative_counties": len(neg),
        "welch_t_test": t,
        "pearson_continuous": cont,
        "interpretation": _interpret_stats(t, cont),
    })


@app.route("/api/correlation/compounds")
def api_correlation_compounds():
    """For featured compounds: mean kg in CWD-positive vs negative counties + t-test."""
    featured = ["GLYPHOSATE", "ATRAZINE", "2,4-D", "METOLACHLOR",
                "CHLORPYRIFOS", "DICAMBA"]
    year = request.args.get("year", type=int)
    conn = db()
    cur = conn.cursor()
    if year is None:
        year = cur.execute("SELECT MAX(year) FROM pesticide_use").fetchone()[0]

    out = []
    for compound in featured:
        rows = cur.execute("""
            SELECT (pu.epest_low_kg + pu.epest_high_kg)/2.0 AS kg,
                   ca.cwd_positive
              FROM correlation_analysis ca
         LEFT JOIN pesticide_use pu
                ON pu.county_fips = ca.county_fips
               AND pu.compound = ? AND pu.year = ?
        """, (compound, year)).fetchall()
        # Convert kg → lbs at the source so downstream means and t-test are in lbs.
        pos = [(r["kg"] or 0) * KG_TO_LB for r in rows if r["cwd_positive"]]
        neg = [(r["kg"] or 0) * KG_TO_LB for r in rows if not r["cwd_positive"]]
        out.append({
            "compound": compound,
            "year": year,
            "mean_positive_kg": (sum(pos) / len(pos)) if pos else 0,
            "mean_negative_kg": (sum(neg) / len(neg)) if neg else 0,
            "welch_t_test": welch_t_test(pos, neg),
        })
    conn.close()
    return lb_jsonify({"compounds": out, "year": year})


@app.route("/api/correlation/crops")
def api_correlation_crops():
    """Compare crop mix in CWD-positive vs CWD-negative counties.

    Returns the totals so the UI can render side-by-side bars. Falls back
    to an empty list (and a `note`) when no NASS crop data is loaded.
    """
    conn = db()
    cur = conn.cursor()
    n_crop_rows = cur.execute("SELECT COUNT(*) FROM crop_acreage").fetchone()[0]
    if n_crop_rows == 0:
        conn.close()
        return lb_jsonify({
            "crops": [],
            "note": ("No USDA NASS crop acreage data loaded. "
                     "Set NASS_API_KEY and re-run the loader to enable "
                     "this comparison."),
        })
    rows = cur.execute("""
        SELECT crop, ca.cwd_positive, SUM(acres_harvested) AS acres
          FROM crop_acreage cr
          JOIN correlation_analysis ca ON ca.county_fips = cr.county_fips
         GROUP BY crop, ca.cwd_positive
    """).fetchall()
    conn.close()
    grouped: dict[str, dict] = {}
    for r in rows:
        d = grouped.setdefault(r["crop"], {"crop": r["crop"], "pos": 0, "neg": 0})
        if r["cwd_positive"]:
            d["pos"] = r["acres"] or 0
        else:
            d["neg"] = r["acres"] or 0
    return lb_jsonify({"crops": sorted(grouped.values(), key=lambda d: -d["pos"] - d["neg"])})


def _interpret_stats(t: dict, cont: dict) -> str:
    """Plain-English headline for the stats box."""
    p = t.get("p_value")
    r = cont.get("r")
    parts = []
    if p is None:
        parts.append("Insufficient data for Welch's t-test.")
    else:
        sig = "statistically significant" if p < 0.05 else "not statistically significant"
        direction = ("higher" if t["mean_a"] > t["mean_b"] else "lower")
        parts.append(
            f"Mean pesticide use in CWD-positive counties is {direction} "
            f"than in CWD-negative counties (Welch's t = {t['t']:.2f}, "
            f"p = {p:.3g}; {sig} at α = 0.05)."
        )
    if r is not None:
        parts.append(
            f"Pearson r = {r:.2f} (R² = {cont['r2']:.2f}) "
            f"between pesticide use and the count of CWD positives across "
            f"all 83 counties."
        )
    parts.append(
        "Reminder: CWD is caused by prion proteins, not chemicals. "
        "Geographic overlap with agricultural regions is a strong confounder."
    )
    return " ".join(parts)


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
               copd_ed_rate, copd_hosp_rate, asthma_prevalence_pct,
               cwd_positive, cwd_positives_count
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

def _site_severity(detected: int, exceeds: int, total: int) -> str:
    if total == 0:
        return "no_data"
    if exceeds > 0:
        return "exceeds_mcl"
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
               COUNT(DISTINCT CASE WHEN r.detected = 1 THEN r.compound END) AS compounds
          FROM water_quality_sites s
     LEFT JOIN water_quality_results r ON r.site_id = s.site_id {med_clause}
         WHERE 1=1 {cmp_join}
         GROUP BY s.site_id
    """, (*med_args, *cmp_args)).fetchall()

    out = []
    for r in rows:
        sev = _site_severity(r["detections"] or 0, r["exceedances"] or 0, r["samples"] or 0)
        out.append({
            "site_id": r["site_id"], "site_name": r["site_name"],
            "site_type": r["site_type"],
            "latitude": r["latitude"], "longitude": r["longitude"],
            "county": r["county"], "county_fips": r["county_fips"],
            "huc8": r["huc8"], "organization": r["organization"],
            "source": r["source"],
            "samples": r["samples"], "detections": r["detections"],
            "exceedances": r["exceedances"], "compounds": r["compounds"],
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
               MAX(CASE WHEN detected = 1 THEN result_value END) AS max_value,
               MAX(unit) AS unit,
               MAX(mcl_value) AS mcl
          FROM water_quality_results
         WHERE site_id = ?
         GROUP BY compound
         ORDER BY exceedances DESC, detections DESC, samples DESC
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


def _huc_polys() -> list:
    """Outer rings per HUC-8, cached. Rings are [[lon, lat], ...]."""
    global _HUC_POLYS
    if _HUC_POLYS is not None:
        return _HUC_POLYS
    out: list = []
    if MI_HUC8_GEOJSON_PATH.exists():
        fc = json.loads(Path(MI_HUC8_GEOJSON_PATH).read_text())
        for f in fc.get("features", []):
            huc = (f.get("properties") or {}).get("huc8")
            geom = f.get("geometry") or {}
            t = geom.get("type")
            coords = geom.get("coordinates") or []
            polys = [coords] if t == "Polygon" else (coords if t == "MultiPolygon" else [])
            outers = [p[0] for p in polys if p]   # outer ring of each polygon
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
        for ring in outers:
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


@app.route("/api/water/watersheds")
def api_water_watersheds():
    """HUC-8 watershed polygons with per-watershed data for the interactive
    choropleth: pesticide detections/exceedances, monitoring-site counts,
    contamination-site counts, and (approx) upstream pesticide use."""
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
    extra = _watershed_extra(conn)
    conn.close()
    geojson_path = MI_HUC8_GEOJSON_PATH
    if not geojson_path.exists():
        return jsonify({"type": "FeatureCollection", "features": [],
                        "note": "Watershed polygons not yet downloaded — run the loader."})
    fc = json.loads(geojson_path.read_text())
    for f in fc.get("features", []):
        props = f.get("properties", {}) or {}
        huc = props.get("huc8")
        c = counts.get(huc, {"detections": 0, "exceedances": 0, "sites_with_detections": 0})
        e = extra.get(huc, {"contam": 0, "contam_npl": 0, "pesticide_kg": 0.0, "total_sites": 0})
        props.update(c)
        props["total_sites"] = e["total_sites"]
        props["contam_sites"] = e["contam"]
        props["contam_npl"] = e["contam_npl"]
        props["pesticide_lbs"] = round((e["pesticide_kg"] or 0) * KG_TO_LB)
        f["properties"] = props
    return jsonify(fc)


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
    "cwd": ("Chronic Wasting Disease spreads deer-to-deer and through the "
            "environment; a link to pesticide use is not established."),
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


def _explore_x_map(conn, x_key: str):
    """Return (xmap {fips: value}, label, unit, is_count) for any X variable."""
    if x_key == "water_detections":
        return (_explore_water_detections(conn),
                "Water pesticide detections", "number of detections", True)
    if x_key and x_key.startswith("contamination"):
        xmap, label, _ = _cancer_x_map(conn, x_key)
        return xmap, label.capitalize(), "number of sites", True
    # pesticide metric or compound (kg values, converted to lbs by caller)
    xmap, label, is_count = _cancer_x_map(conn, x_key)
    unit = _EXPLORE_PEST.get(x_key, ("", "lbs applied (latest year)"))[1]
    if x_key and x_key.startswith("compound:"):
        unit = "lbs applied (latest year)"
    return xmap, label, unit, is_count


def _explore_y_map(conn, y_key: str):
    """Return (ymap {fips: value}, label, unit, family) for any Y variable.
    family is one of 'cancer' | 'respiratory' | 'cwd' (for the caveat)."""
    if y_key and y_key.startswith("cancer:"):
        ck = _cancer_key(y_key.split(":", 1)[1])
        rows = conn.execute(
            """SELECT county_fips AS f, rate FROM cancer_incidence
                WHERE cancer_type = ? AND data_type = 'incidence' AND stage = 'all'
                  AND rate IS NOT NULL""", (ck,)).fetchall()
        label = cancer_data.CANCER_BY_KEY[ck]["label"]
        return ({r["f"]: r["rate"] for r in rows}, label,
                "cases per 100,000 (age-adjusted)", "cancer")
    if y_key == "cwd":
        rows = conn.execute(
            "SELECT county_fips AS f, cwd_positives_count AS v FROM correlation_analysis"
        ).fetchall()
        return ({r["f"]: r["v"] for r in rows}, "CWD-positive deer",
                "confirmed positive deer", "cwd")
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
    y = [{"key": f"cancer:{c['key']}", "label": c["label"],
          "unit": "cases per 100,000 (age-adjusted)", "group": "Cancer"}
         for c in cancer_data.CANCER_TYPES]
    y += [{"key": k, "label": lbl, "unit": u, "group": "Respiratory"}
          for k, (col, lbl, u) in _EXPLORE_RESP.items()]
    y += [{"key": "cwd", "label": "CWD-positive deer (count)",
           "unit": "confirmed positive deer", "group": "Wildlife disease"}]
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
    compound, contamination, water detections) vs any Y (cancer, respiratory,
    CWD). Returns raw stats + points; the frontend does the plain-language
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
    print(f" * Michigan Pesticide Heat Map serving on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
