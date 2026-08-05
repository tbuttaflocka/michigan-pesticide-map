"""Per-county data export.

Builds, on request, a ZIP containing one CSV per dataset that actually has
rows in the requested county, plus a README.txt. No database writes.

Design notes:
  * Values are published exactly as stored in the source table/module — no
    renaming, recoding, or unit conversion. Non-scalar module values (lists)
    are JSON-encoded because CSV cells must be text; DB text/JSON columns are
    emitted verbatim.
  * Each CSV carries a short provenance header block (source_id / title / url /
    coverage years / last_updated) pulled from the data_sources table, or from
    module constants where data_sources has no row (coal ash).
  * A dataset with zero rows for the county is omitted entirely; the README
    lists which datasets had no records, and states that "no records" does not
    mean "no contamination".
  * echo_facilities and oil_gas_wells use county_fips where present and fall
    back to point-in-polygon (michigan_counties.geojson) for NULL-county rows.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile


# --------------------------------------------------------------------------- #
# point-in-polygon (ray casting) against the county boundary GeoJSON
# --------------------------------------------------------------------------- #
def _point_in_ring(lng: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _geometry_contains(geom: dict, lng: float, lat: float) -> bool:
    """True if (lng,lat) is inside a Polygon/MultiPolygon (outer ring, minus holes)."""
    if not geom:
        return False
    t = geom.get("type")
    coords = geom.get("coordinates") or []
    polys = [coords] if t == "Polygon" else coords if t == "MultiPolygon" else []
    for poly in polys:
        if not poly:
            continue
        if _point_in_ring(lng, lat, poly[0]) and not any(
            _point_in_ring(lng, lat, hole) for hole in poly[1:]
        ):
            return True
    return False


def _county_geometry(geojson_path, fips: str):
    with open(geojson_path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)
    for feat in gj.get("features", []):
        if str(feat.get("properties", {}).get("fips")) == str(fips):
            return feat.get("geometry")
    return None


# --------------------------------------------------------------------------- #
# CSV helpers
# --------------------------------------------------------------------------- #
def _cell(v):
    """CSV cells must be text; DB scalars pass through, module lists/dicts are
    JSON-encoded (the only reformatting, and only for the two Python modules)."""
    if v is None or isinstance(v, (str, int, float)):
        return v
    return json.dumps(v, ensure_ascii=False)


def _fmt_coverage(start, end) -> str:
    if start and end:
        return f"{start}-{end}"
    if start or end:
        return str(start or end)
    return "not specified"


def _write_csv(zf, filename, prov, colnames, rows, gen_date):
    prov = prov or {}
    buf = io.StringIO()
    header = [
        "# Michigan Pollution Map - per-county data export",
        f"# generated: {gen_date}",
        f"# source_id: {prov.get('source_id') or ''}",
        f"# source_title: {prov.get('title') or ''}",
        f"# source_url: {prov.get('url') or ''}",
        f"# coverage_years: {_fmt_coverage(prov.get('coverage_start'), prov.get('coverage_end'))}",
        f"# last_updated: {prov.get('last_updated') or 'not specified'}",
        "# Values are published exactly as stored by the source (not reformatted).",
        "# See README.txt for units, caveats, and full provenance.",
    ]
    buf.write("\n".join(header) + "\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(colnames)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    zf.writestr(filename, buf.getvalue())


def _provenance(cur, source_id):
    if not source_id:
        return None
    r = cur.execute(
        "SELECT source_id, title, url, coverage_start, coverage_end, last_updated "
        "FROM data_sources WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if not r:
        return None
    return {
        "source_id": r[0], "title": r[1], "url": r[2],
        "coverage_start": r[3], "coverage_end": r[4], "last_updated": r[5],
    }


# --------------------------------------------------------------------------- #
# dataset catalogue  (file, source_id, param, sql, and README metadata)
#   param: 'fips'  -> 5-digit county_fips
#          'name'  -> county name
#          'fips3' -> 3-digit county FIPS (EPA CAMD stores it that way)
# --------------------------------------------------------------------------- #
_SQL_DATASETS = [
    # ---- Group A: direct county_fips ----
    dict(file="pesticide_use", source_id="usgs_epest", param="fips",
         sql="SELECT * FROM pesticide_use WHERE county_fips=? ORDER BY year, compound",
         desc="USGS-estimated annual agricultural pesticide use, by compound and year.",
         units="epest_low_kg / epest_high_kg are KILOGRAMS PER YEAR as published (the app displays pounds).",
         caveat="Model-based ESTIMATES, agricultural use only, 1992-2019."),
    dict(file="crop_acreage", source_id="nass_acreage", param="fips",
         sql="SELECT * FROM crop_acreage WHERE county_fips=? ORDER BY year, crop",
         desc="USDA NASS county crop acreage (harvested / planted), by crop and year.",
         units="acres.",
         caveat="Survey data; 5 of 10 crops available."),
    dict(file="ust_sites", source_id="egle_ust", param="fips",
         sql="SELECT * FROM ust_sites WHERE county_fips=?",
         desc="EGLE registered underground storage tank (UST) facilities and release status.",
         units="tank counts; release status codes.",
         caveat="A merely LICENSED tank is not a contaminated site; open leaking releases are the contamination signal."),
    dict(file="tri_facility", source_id="epa_tri", param="fips",
         sql="SELECT * FROM tri_facility WHERE county_fips=?",
         desc="EPA Toxics Release Inventory facilities located in the county.",
         units="n/a (facility inventory).",
         caveat="Self-reported by facilities under EPCRA."),
    dict(file="tri_release", source_id="epa_tri", param="fips",
         sql="SELECT r.* FROM tri_release r JOIN tri_facility f ON r.facility_id=f.facility_id "
             "WHERE f.county_fips=? ORDER BY r.year, r.chemical",
         desc="EPA TRI facility-chemical-year release records for facilities in the county.",
         units="*_lbs columns are POUNDS PER YEAR.",
         caveat="Self-reported (EPCRA); 2013-2024."),
    dict(file="contamination_sites", source_id="epa_sems_npl", param="fips",
         sql="SELECT * FROM contamination_sites WHERE county_fips=?",
         desc="Superfund/NPL and compiled state contamination sites.",
         units="hrs_score is the EPA Hazard Ranking Score (0-100) where available.",
         caveat="Curated + EPA SEMS; not an exhaustive list of every state cleanup."),
    dict(file="landfill_sites", source_id="egle_landfills", param="fips",
         sql="SELECT * FROM landfill_sites WHERE county_fips=?",
         desc="EGLE Part 115 landfills and Part 111 hazardous-waste disposal facilities.",
         units="n/a (facility inventory).",
         caveat="Active / disposal-only per EGLE Materials Management open data."),
    dict(file="golf_courses", source_id="osm_golf", param="fips",
         sql="SELECT * FROM golf_courses WHERE county_fips=?",
         desc="OpenStreetMap golf courses (turf land area under management).",
         units="acres (turf footprint).",
         caveat="LOCATIONS / footprints only - contains no pesticide-application amounts."),
    dict(file="pfas_features", source_id="egle_mpart_pfas", param="fips",
         sql="SELECT * FROM pfas_features WHERE county_fips=?",
         desc="Michigan PFAS (MPART) sites and areas of interest.",
         units="max_ppt is PARTS PER TRILLION.",
         caveat="Investigation status varies by site; absence is not clearance."),
    dict(file="water_quality_sites", source_id="wqp", param="fips",
         sql="SELECT * FROM water_quality_sites WHERE county_fips=?",
         desc="USGS/EPA Water Quality Portal monitoring stations in the county.",
         units="n/a (station inventory).",
         caveat="Station list; see water_quality_results.csv for the measurements."),
    dict(file="water_quality_results", source_id="wqp", param="fips",
         sql="SELECT r.* FROM water_quality_results r JOIN water_quality_sites s ON r.site_id=s.site_id "
             "WHERE s.county_fips=? ORDER BY r.sample_date",
         desc="Water Quality Portal sample results for stations in the county.",
         units="result_value is in the row's own 'unit' column (varies by analyte).",
         caveat="1967-2025; exceeds_mcl / exceeds_benchmark flag threshold exceedances."),
    dict(file="airtoxics_tracts", source_id="epa_airtoxics", param="fips",
         sql="SELECT * FROM airtoxics_tracts WHERE county_fips=?",
         desc="EPA AirToxScreen air-toxics cancer-risk estimates by census tract.",
         units="total_risk is chance-in-a-million (70-yr lifetime), MODELED.",
         caveat="MODELED SCREENING estimate (2017) - not a measurement. Includes tract geometry."),
    dict(file="wind_data", source_id="iem_asos_wind", param="fips",
         sql="SELECT * FROM wind_data WHERE county_fips=?",
         desc="IEM ASOS growing-season wind roses by weather station.",
         units="avg_speed_mph (mph); direction_deg (degrees).",
         caveat="Growing season (Apr-Sep) 2021-2023; few stations per county."),
    # ---- Group C: child tables via a name-joined parent ----
    dict(file="fracfocus_disclosures", source_id="fracfocus", param="name",
         sql="SELECT * FROM fracfocus_disclosures WHERE UPPER(county_name)=UPPER(?)",
         desc="FracFocus hydraulic-fracturing disclosures (county name match).",
         units="total_base_water_volume (gallons); tvd (feet).",
         caveat="Only ~31 HVHF disclosures exist statewide."),
    dict(file="fracfocus_ingredients", source_id="fracfocus", param="name",
         sql="SELECT i.* FROM fracfocus_ingredients i JOIN fracfocus_disclosures d "
             "ON i.disclosure_key=d.disclosure_key WHERE UPPER(d.county_name)=UPPER(?)",
         desc="FracFocus disclosed fracturing-fluid ingredients for the county's disclosures.",
         units="percent_hf_job (%); mass_ingredient (lbs).",
         caveat="is_masked=1 rows are trade-secret withheld."),
    # ---- Group D: name / 3-digit-FIPS joined ----
    dict(file="power_plants", source_id="eia_860", param="name",
         sql="SELECT * FROM power_plants WHERE UPPER(TRIM(county))=UPPER(?)",
         desc="EIA-860 power-plant generators (county-name match).",
         units="nameplate_capacity_mw is MEGAWATTS.",
         caveat="Inventory snapshot; one row per generator."),
    dict(file="power_plant_camd_facilities", source_id="epa_camd", param="fips3",
         sql="SELECT * FROM power_plant_camd_facilities WHERE fips_code=?",
         desc="EPA CAMD facility attributes (fuel, emission controls) for county plants.",
         units="n/a (facility metadata).",
         caveat="CAMD 3-digit county FIPS join."),
    dict(file="power_plant_emissions", source_id="epa_camd", param="fips3",
         sql="SELECT e.* FROM power_plant_emissions e JOIN power_plant_camd_facilities f "
             "ON e.facility_id=f.facility_id WHERE f.fips_code=? ORDER BY e.year, e.unit_id",
         desc="EPA CAMD annual unit emissions for plants in the county.",
         units="so2_mass / nox_mass / co2_mass are TONS; *_rate are lb/mmBtu.",
         caveat="MEASURED continuous emissions monitoring (CEMS) under 40 CFR Part 75 - not modeled; 1995-2026."),
]

# Group B: county_fips + point-in-polygon fallback for NULL-county rows.
_FALLBACK_DATASETS = [
    dict(file="echo_facilities", source_id="epa_echo", table="echo_facilities",
         desc="EPA ECHO enforcement & compliance facilities.",
         units="penalty amounts in USD; various compliance/inspection counts.",
         caveat="ALLEGED violations, NOT final adjudications. Compliance status covers a 12-quarter "
                "(3-year) window and can lag reality by up to ~3 months."),
    dict(file="oil_gas_wells", source_id="egle_oil_gas_wells", table="oil_gas_wells",
         desc="EGLE oil / gas / mineral well surface locations.",
         units="dtd / tvd depths (feet).",
         caveat="well_status is verbatim from EGLE; this dataset has no hydraulic-fracturing flag."),
]

# Module datasets (not in the DB).
_MODULE_META = {
    "coal_ash_sites": dict(
        desc="Curated Michigan coal ash (CCR) disposal sites.",
        units="n/a (site directory).",
        caveat="Curated directory that links to each utility's own CCR data. Contaminant findings are "
               "attributed to Ashtracker / EIP and are disputed by the utilities."),
    "spraying_programs": dict(
        desc="Publicly-documented organized pest-control spraying programs located in the county.",
        units="n/a (program directory).",
        caveat="Statewide-scope programs are excluded from county files (they are not county-specific)."),
}

_EXCLUDED = [
    ("pesticide_use_by_crop", "Michigan STATEWIDE by design (state_fips only) - not a county-level dataset."),
    ("watersheds (HUC-8)", "Watershed boundaries cross county lines; they cannot be attributed to a single county."),
    ("reference lookups (chemical_reference, pesticide_categories, cancer_evidence/reference, airtoxics_stats)",
     "Non-geographic lookup tables with no county attribution."),
    ("cancer_* and respiratory_* tables", "Health-outcome data was removed from the app; not exported."),
    ("correlation_analysis", "Derived analysis table, not a primary source dataset - excluded."),
]


# --------------------------------------------------------------------------- #
# module row builders
# --------------------------------------------------------------------------- #
def _coal_ash_rows(sites, county_name):
    cols = list(sites[0].keys()) if sites else []
    key = county_name.strip().lower()
    rows = [[s.get(c) for c in cols] for s in sites
            if str(s.get("county", "")).strip().lower() == key]
    return cols, rows


def _spraying_rows(payload, geom):
    progs = (payload or {}).get("programs", []) or []
    # Exclude purely-visual fields; keep everything substantive as stored.
    drop = {"glyph", "color", "type_label"}
    cols = [k for k in (progs[0].keys() if progs else []) if k not in drop]
    rows = []
    for p in progs:
        if p.get("scope") == "statewide":
            continue
        lat, lng = p.get("lat"), p.get("lon")
        if lat is None or lng is None or geom is None:
            continue
        if _geometry_contains(geom, lng, lat):
            rows.append([p.get(c) for c in cols])
    return cols, rows


def _fallback_rows(cur, table, fips, geom):
    """Direct county_fips rows + NULL-county rows whose point falls in the county.
    Returns (colnames, rows, n_resolved_by_fallback)."""
    cur.execute(f"SELECT * FROM {table} WHERE county_fips=?", (fips,))
    cols = [d[0] for d in cur.description]
    rows = [list(r) for r in cur.fetchall()]
    resolved = 0
    if geom is not None:
        lat_i, lng_i = cols.index("latitude"), cols.index("longitude")
        cur.execute(
            f"SELECT * FROM {table} WHERE (county_fips IS NULL OR county_fips='') "
            f"AND latitude IS NOT NULL AND longitude IS NOT NULL"
        )
        for r in cur.fetchall():
            rr = list(r)
            if _geometry_contains(geom, rr[lng_i], rr[lat_i]):
                rows.append(rr)
                resolved += 1
    return cols, rows, resolved


# --------------------------------------------------------------------------- #
# README
# --------------------------------------------------------------------------- #
def _readme(county_name, fips, gen_date, included, empty, fallback, meta_by_file):
    L = []
    add = L.append
    add(f"MICHIGAN POLLUTION MAP - DATA EXPORT")
    add(f"County: {county_name} County   FIPS: {fips}")
    add(f"Generated: {gen_date}")
    add("")
    add("This export was produced by an INDEPENDENT project. It is NOT affiliated")
    add("with, endorsed by, or an official product of the EPA, EGLE, USGS, USDA, EIA,")
    add("or any other agency. Always confirm against the primary sources linked below.")
    add("")
    add("HOW TO READ THIS DATA - PLEASE READ")
    add("-" * 60)
    add("* Each CSV begins with a few '#' provenance lines, then a normal header row.")
    add("* Values are published EXACTLY as stored by the source - not renamed,")
    add("  recoded, or unit-converted. Notably pesticide_use is in KILOGRAMS PER YEAR")
    add("  as USGS publishes it, whereas the app's map displays pounds.")
    add("* 'No records' does NOT mean clean or safe. Many places have never been")
    add("  sampled, monitored, or inspected; a dataset with no rows here may simply")
    add("  reflect the absence of monitoring, not the absence of contamination.")
    add("* ECHO lists ALLEGED violations, not final legal adjudications. Its compliance")
    add("  status reflects a rolling 12-quarter (3-year) window and can lag actual")
    add("  conditions by up to ~3 months.")
    add("* power_plant_emissions are MEASURED stack emissions (continuous emissions")
    add("  monitoring / CEMS under 40 CFR Part 75) - not modeled. By contrast,")
    add("  airtoxics_tracts is a MODELED screening estimate, not a measurement.")
    add("")
    add("INCLUDED DATASETS (one CSV each; only datasets with rows in this county)")
    add("-" * 60)
    for file, n in included:
        m = meta_by_file.get(file, {})
        add(f"[{file}.csv]  ({n:,} rows)")
        add(f"  What: {m.get('desc','')}")
        add(f"  Source: {m.get('source_title','') or m.get('source_id','')}")
        add(f"  URL: {m.get('url','')}")
        add(f"  Coverage: {m.get('coverage','not specified')}   Last updated: {m.get('last_updated','not specified')}")
        add(f"  Units: {m.get('units','')}")
        add(f"  Caveat: {m.get('caveat','')}")
        if file in fallback:
            add(f"  County assignment: county_fips where present; {fallback[file]:,} additional "
                f"NULL-county rows resolved to this county by point-in-polygon.")
        add("")
    if empty:
        add("DATASETS WITH NO RECORDS FOR THIS COUNTY (CSV omitted)")
        add("-" * 60)
        add("These app datasets returned zero rows for this county, so no CSV was written.")
        add("Again: no records does NOT mean no contamination - it often means no one has")
        add("sampled or inspected here.")
        for file in empty:
            add(f"  - {file}: {meta_by_file.get(file, {}).get('desc','')}")
        add("")
    add("EXCLUDED DATASETS (never part of a county export) AND WHY")
    add("-" * 60)
    for name, why in _EXCLUDED:
        add(f"  - {name}: {why}")
    add("")
    add("Questions about the underlying data belong with the originating agency, via")
    add("the source URLs above.")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def _slug(name: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in name.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def build_county_zip(conn, fips, *, geojson_path, coal_ash_sites,
                     spraying_payload, ccr_source, now):
    """Return (zip_bytes, filename, stats) or None if the FIPS is unknown.

    `now` is a datetime supplied by the caller (kept out of this module for
    testability). `stats` is a dict with counts used by verification/logging.
    """
    cur = conn.cursor()
    crow = cur.execute("SELECT fips, name FROM counties WHERE fips=?", (fips,)).fetchone()
    if not crow:
        return None
    fips, county_name = str(crow[0]), crow[1]
    fips3 = fips[-3:]
    gen_date = now.strftime("%Y-%m-%d %H:%M UTC")
    geom = _county_geometry(geojson_path, fips)

    params = {"fips": fips, "name": county_name, "fips3": fips3}
    included, empty, fallback = [], [], {}
    meta_by_file = {}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        def emit(file, source_id, cols, rows, prov=None, meta=None):
            prov = prov or _provenance(cur, source_id)
            m = dict(meta or {})
            m.update({
                "source_id": source_id or (prov or {}).get("source_id", ""),
                "source_title": (prov or {}).get("title", ""),
                "url": (prov or {}).get("url", ""),
                "coverage": _fmt_coverage((prov or {}).get("coverage_start"),
                                          (prov or {}).get("coverage_end")),
                "last_updated": (prov or {}).get("last_updated") or "not specified",
            })
            meta_by_file[file] = m
            if rows:
                _write_csv(zf, file + ".csv", prov, cols, rows, gen_date)
                included.append((file, len(rows)))
            else:
                empty.append(file)

        # SQL-backed datasets
        for spec in _SQL_DATASETS:
            cur.execute(spec["sql"], (params[spec["param"]],))
            cols = [d[0] for d in cur.description]
            rows = [list(r) for r in cur.fetchall()]
            emit(spec["file"], spec["source_id"], cols, rows,
                 meta={k: spec[k] for k in ("desc", "units", "caveat")})

        # point-in-polygon fallback datasets
        for spec in _FALLBACK_DATASETS:
            cols, rows, resolved = _fallback_rows(cur, spec["table"], fips, geom)
            fallback[spec["file"]] = resolved
            emit(spec["file"], spec["source_id"], cols, rows,
                 meta={k: spec[k] for k in ("desc", "units", "caveat")})

        # coal ash module (provenance from module/app constant, no data_sources row)
        ca_cols, ca_rows = _coal_ash_rows(coal_ash_sites, county_name)
        emit("coal_ash_sites", ccr_source.get("source_id"), ca_cols, ca_rows,
             prov=ccr_source, meta=_MODULE_META["coal_ash_sites"])

        # spraying module (has a data_sources row: spraying_programs)
        sp_cols, sp_rows = _spraying_rows(spraying_payload, geom)
        emit("spraying_programs", "spraying_programs", sp_cols, sp_rows,
             meta=_MODULE_META["spraying_programs"])

        readme = _readme(county_name, fips, gen_date, included, empty, fallback, meta_by_file)
        zf.writestr("README.txt", readme)

    filename = f"{_slug(county_name)}-county-data.zip"
    stats = {
        "county": county_name, "fips": fips,
        "included": included, "empty": empty, "fallback_resolved": fallback,
        "bytes": buf.tell(),
    }
    return buf.getvalue(), filename, stats
