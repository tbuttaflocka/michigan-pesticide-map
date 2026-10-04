"""build_aoc.py — ONE-TIME prep for the Areas of Concern layer. NOT run by
refresh_data.py (the loader reads the committed app/aoc_boundaries.geojson).

What it does, reproducibly:
  1. Downloads each Michigan AOC's boundary file from EPA's frozen 2020 snapshot
     (19january2021snapshot.epa.gov). 12 of 14 AOCs publish one (White Lake and
     Muskegon Lake do not); most are 2013-2015 NAD83 shapefiles, Rouge is a 2020
     File Geodatabase whose Waterbodies layer we use.
  2. Converts every geometry to a GeoJSON MultiPolygon (NAD83 lon/lat, 5-dp).
  3. DERIVES the counties each polygon touches by intersecting it against
     data/michigan_counties.geojson (shapely area-overlap) — not from any list.
  4. Writes app/aoc_boundaries.geojson (FeatureCollection; properties: slug, counties).

Dev-time dependencies (NOT in requirements.txt, NOT needed at refresh):
    pip install pyshp shapely pyogrio
Run from the repo root:  python scripts/build_aoc.py
"""
from __future__ import annotations
import glob
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AOC_DIR = ROOT / "data" / "aoc"
OUT = ROOT / "app" / "aoc_boundaries.geojson"
COUNTIES = ROOT / "data" / "michigan_counties.geojson"
SNAP = "https://19january2021snapshot.epa.gov/sites/static/files"

# slug -> boundary file path on the snapshot host (verified 2026-10-04).
# White Lake and Muskegon Lake have no published boundary file -> omitted.
SOURCES = {
    "clinton":     "2015-08/aoc_mi_clinton.zip",
    "detroit":     "2015-07/aoc_mi_detroit.zip",
    "kalamazoo":   "2015-08/aoc_mi_kalamazoo.zip",
    "manistique":  "2021-01/aoc_mi_manistique_2020.zip",
    "menominee":   "2015-07/aoc_mi_menominee.zip",
    "riverraisin": "2015-09/aoc_mi_riverraisin.zip",
    "saginaw":     "2015-08/aoc_mi_saginaw_river_bay.zip",
    "stclair":     "2015-09/aoc_mi_stclair.zip",
    "stmarys":     "2015-07/aoc_mi_stmarys.zip",
    "torchlake":   "2015-09/aoc_mi_torchlake.zip",
    "deerlake":    "2013-10/aoc_mi_deerlake.zip",
    "rouge":       "2020-12/aoc_mi_rouge_2020.zip",   # File Geodatabase
}
UA = {"User-Agent": "Mozilla/5.0 (MichiganPollutionMap AOC build)"}


def fetch(slug: str, rel: str) -> Path:
    AOC_DIR.mkdir(parents=True, exist_ok=True)
    zp = AOC_DIR / f"{slug}.zip"
    if not zp.exists() or zp.stat().st_size < 2000:
        data = urllib.request.urlopen(
            urllib.request.Request(f"{SNAP}/{rel}", headers=UA), timeout=120).read()
        zp.write_bytes(data)
    dd = AOC_DIR / f"{slug}_x"
    if not dd.exists():
        with zipfile.ZipFile(io.BytesIO(zp.read_bytes())) as z:
            z.extractall(dd)
    return dd


def round_geom(g, nd=5):
    def rc(x):
        return round(x, nd) if isinstance(x, (int, float)) else [rc(i) for i in x]
    return {"type": g["type"], "coordinates": rc(g["coordinates"])}


def main() -> int:
    import shapefile                       # pyshp
    import shapely.geometry as sg
    import shapely.wkb as wkb
    from shapely.ops import unary_union
    import numpy as np
    from pyogrio.raw import read as ogr_read

    def clean(u):
        return u if u.is_valid else u.buffer(0)

    feats = []
    for slug, rel in SOURCES.items():
        dd = fetch(slug, rel)
        if slug == "rouge":                # File Geodatabase: use the Waterbodies layer
            gdb = glob.glob(str(dd / "**" / "*.gdb"), recursive=True)[0]
            res = ogr_read(gdb, layer="Rouge_River_AOC_Waterbodies")
            garr = next(x for x in res if isinstance(x, np.ndarray) and x.dtype == object)
            u = clean(unary_union([wkb.loads(bytes(b)) for b in garr if b]))
        else:
            shp = glob.glob(str(dd / "**" / "*.shp"), recursive=True)[0]
            u = clean(unary_union([clean(sg.shape(s.__geo_interface__))
                                   for s in shapefile.Reader(shp).shapes()]))
        feats.append({"type": "Feature", "properties": {"slug": slug},
                      "geometry": round_geom(sg.mapping(u)), "_geom": u})

    # counties DERIVED from each polygon by intersecting michigan_counties.geojson
    counties = []
    for f in json.loads(COUNTIES.read_text())["features"]:
        g = sg.shape(f["geometry"])
        counties.append((f["properties"]["fips"], f["properties"]["name"],
                         g if g.is_valid else g.buffer(0)))
    for feat in feats:
        a = feat.pop("_geom")
        hits = [(n, fp) for fp, n, cg in counties
                if a.intersects(cg) and a.intersection(cg).area > 1e-7]
        feat["properties"]["counties"] = [{"fips": fp, "name": n} for n, fp in hits]

    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"wrote {OUT} ({round(OUT.stat().st_size/1024)} KB, {len(feats)} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
