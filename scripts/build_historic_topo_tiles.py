#!/usr/bin/env python3
"""Build the self-hosted historic-topo tile pyramid (Downriver Detroit).

Sources — USGS Historical Topographic Map Collection, public domain, fetched
from the public S3 bucket (verified live before processing):

  MI_Wyandotte_278613_1906_62500_geo.tif   (Wyandotte quad, 1906)
  MI_Detroit_278077_1905_62500_geo.tif     (Detroit quad, 1905)

Pipeline (equivalent to gdalwarp -cutline + gdal2tiles, implemented with
rasterio because no GDAL CLI wheels exist for CPython 3.14 on Windows):

  1. Clip each sheet to its quadrangle NEATLINE — the collar (white margins,
     legend blocks) would otherwise cover adjacent terrain. Neatlines are the
     round 15-arcminute graticule values IN NAD27 (the datum the corner ticks
     were surveyed in); the rectangle is densified before projecting into the
     sheet's polyconic CRS so the curved graticule edges clip correctly.
  2. Reproject both clipped sheets onto one EPSG:3857 mosaic aligned to the
     z15 slippy-tile grid (native scan resolution ~5.3 m/px ~= z15 here).
  3. Emit an XYZ tile pyramid (z9..z15, 256px RGBA PNGs) by halving the
     mosaic per zoom. Tiles fully outside the sheets stay unwritten; the
     Leaflet layer's `bounds` keeps requests inside the quads.

Output: static/tiles/historic_topo/{z}/{x}/{y}.png + a tiny meta.json with
the exact WGS84 bounds for the Leaflet layer. Prints per-zoom counts and the
total size — the result is reviewed for repo-worthiness before committing.
"""
import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.warp import reproject, Resampling, transform as rio_transform
from rasterio.transform import from_origin, array_bounds
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data" / "historic_topo"
OUT_DIR = ROOT / "static" / "tiles" / "historic_topo"

S3 = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/MI/"
SHEETS = [
    # (filename, neatline in NAD27 degrees: W, S, E, N — 15' graticule values)
    ("MI_Wyandotte_278613_1906_62500_geo.tif", (-83.25, 42.00, -83.00, 42.25)),
    ("MI_Detroit_278077_1905_62500_geo.tif",   (-83.25, 42.25, -83.00, 42.50)),
]

ZMAX, ZMIN = 15, 9
TILE = 256
WEB_R = 6378137.0
ORIGIN = math.pi * WEB_R                      # 20037508.34...


def fetch(name: str) -> Path:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    p = SRC_DIR / name
    if p.exists() and p.stat().st_size > 1_000_000:
        return p
    url = S3 + name
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "michigan-pesticide-map"})
    with urllib.request.urlopen(req, timeout=300) as r, open(p, "wb") as fh:
        fh.write(r.read())
    if p.stat().st_size < 1_000_000:
        sys.exit(f"download of {name} looks truncated — aborting")
    return p


def neatline_poly_in(crs, w, s, e, n, pts=64):
    """Quad neatline rectangle (NAD27 degrees) densified then projected into
    `crs`, as a GeoJSON polygon. Densification matters: the graticule edges
    are curves in the sheet's polyconic projection."""
    ring = []
    for i in range(pts):
        ring.append((w + (e - w) * i / pts, s))        # south edge W->E
    for i in range(pts):
        ring.append((e, s + (n - s) * i / pts))        # east edge S->N
    for i in range(pts):
        ring.append((e - (e - w) * i / pts, n))        # north edge E->W
    for i in range(pts):
        ring.append((w, n - (n - s) * i / pts))        # west edge N->S
    ring.append(ring[0])
    xs, ys = rio_transform("EPSG:4267", crs, [p[0] for p in ring], [p[1] for p in ring])
    return {"type": "Polygon", "coordinates": [list(zip(xs, ys))]}


def merc(lon, lat):
    x = lon / 180.0 * ORIGIN
    y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / math.pi * ORIGIN
    return x, y


def main():
    res = 2 * ORIGIN / (TILE * 2 ** ZMAX)             # z15 metres/px
    clipped = []
    for name, (w, s, e, n) in SHEETS:
        p = fetch(name)
        with rasterio.open(p) as src:
            poly = neatline_poly_in(src.crs, w, s, e, n)
            data, tr = rio_mask(src, [poly], crop=True, filled=True, nodata=0)
            # alpha: inside-neatline = 255 (mask() zero-fills outside; the
            # map body itself has no pure-black pixels that matter at 3857
            # res, but build alpha from the mask, not the pixel values)
            amask, _ = rio_mask(src, [poly], crop=True, filled=True, nodata=0,
                                indexes=[1])
            alpha = (rio_mask(src, [poly], crop=True, filled=False)[0].mask[0] == False)  # noqa: E712
            clipped.append((data, alpha.astype(np.uint8) * 255, tr, src.crs))
            print(f"  clipped {name}: {data.shape[2]}x{data.shape[1]} px")

    # Mosaic grid: union of both sheets in 3857, snapped outward to the z15
    # tile grid so tile cuts land exactly on 256-px boundaries.
    lons = [-83.25, -83.00]
    lats = [42.00, 42.50]
    # NAD27->WGS84 shift is ~10-20 m here; pad the mercator extent by 500 m
    # so warped edges are never cropped, then snap to tile-grid multiples.
    x0, y1 = merc(lons[0], lats[1])
    x1, y0 = merc(lons[1], lats[0])
    pad = 500.0
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    tile_m = TILE * res
    x0 = math.floor((x0 + ORIGIN) / tile_m) * tile_m - ORIGIN
    y1 = ORIGIN - math.floor((ORIGIN - y1) / tile_m) * tile_m
    x1 = math.ceil((x1 + ORIGIN) / tile_m) * tile_m - ORIGIN
    y0 = ORIGIN - math.ceil((ORIGIN - y0) / tile_m) * tile_m
    width = round((x1 - x0) / res)
    height = round((y1 - y0) / res)
    print(f"  mosaic: {width}x{height} px @ z{ZMAX} grid")
    dst_tr = from_origin(x0, y1, res, res)

    mosaic = np.zeros((4, height, width), dtype=np.uint8)
    for data, alpha, tr, crs in clipped:
        for b in range(3):
            reproject(data[b], mosaic[b], src_transform=tr, src_crs=crs,
                      dst_transform=dst_tr, dst_crs="EPSG:3857",
                      resampling=Resampling.bilinear, dst_nodata=0,
                      init_dest_nodata=False)
        reproject(alpha, mosaic[3], src_transform=tr, src_crs=crs,
                  dst_transform=dst_tr, dst_crs="EPSG:3857",
                  resampling=Resampling.nearest, dst_nodata=0,
                  init_dest_nodata=False)

    # WGS84 bounds of the actual mosaic (for the Leaflet layer's `bounds`).
    wb = array_bounds(height, width, dst_tr)
    def inv_merc(x, y):
        return (x / ORIGIN * 180.0,
                math.degrees(2 * math.atan(math.exp(y / ORIGIN * math.pi)) - math.pi / 2))
    sw = inv_merc(wb[0], wb[1]); ne = inv_merc(wb[2], wb[3])

    img = Image.fromarray(np.moveaxis(mosaic, 0, -1), "RGBA")
    del mosaic, clipped

    total_bytes = total_tiles = 0
    per_zoom = {}
    tx0_base = round((x0 + ORIGIN) / tile_m)          # tile col of mosaic origin @ zmax
    ty0_base = round((ORIGIN - y1) / tile_m)          # tile row (XYZ, from north)
    for z in range(ZMAX, ZMIN - 1, -1):
        shrink = 2 ** (ZMAX - z)
        zw, zh = img.width // shrink, img.height // shrink
        zimg = img if shrink == 1 else img.resize((zw, zh), Image.LANCZOS)
        # mosaic origin falls on tile boundaries at every zoom only if the
        # base tile indices are even enough — handle offset generally:
        tx_origin = tx0_base / shrink
        ty_origin = ty0_base / shrink
        ntx = math.ceil(tx_origin + zw / TILE) - math.floor(tx_origin)
        nty = math.ceil(ty_origin + zh / TILE) - math.floor(ty_origin)
        n = b = 0
        for ix in range(ntx):
            for iy in range(nty):
                tx = math.floor(tx_origin) + ix
                ty = math.floor(ty_origin) + iy
                # pixel window of this tile within zimg
                px0 = round((tx - tx_origin) * TILE)
                py0 = round((ty - ty_origin) * TILE)
                tile_img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
                sx0, sy0 = max(0, px0), max(0, py0)
                sx1, sy1 = min(zw, px0 + TILE), min(zh, py0 + TILE)
                if sx1 <= sx0 or sy1 <= sy0:
                    continue
                piece = zimg.crop((sx0, sy0, sx1, sy1))
                tile_img.paste(piece, (sx0 - px0, sy0 - py0))
                ex = tile_img.getextrema()
                if ex[3][1] == 0:
                    continue                           # fully transparent
                d = OUT_DIR / str(z) / str(tx)
                d.mkdir(parents=True, exist_ok=True)
                fp = d / f"{ty}.png"
                # PNG8: scanned sheets have few distinct inks — palette
                # quantization cuts tile weight to ~1/5 with no visible loss.
                tile_img.quantize(colors=256, method=Image.FASTOCTREE).save(
                    fp, "PNG", optimize=True)
                n += 1
                b += fp.stat().st_size
        per_zoom[z] = (n, b)
        total_tiles += n
        total_bytes += b
        print(f"  z{z}: {n} tiles, {b/1e6:.1f} MB")

    meta = {"bounds": [[round(sw[1], 6), round(sw[0], 6)],
                       [round(ne[1], 6), round(ne[0], 6)]],
            "min_zoom": ZMIN, "max_zoom": ZMAX,
            "sources": [S3 + s for s, _ in SHEETS]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"TOTAL: {total_tiles} tiles, {total_bytes/1e6:.1f} MB -> {OUT_DIR}")
    print("bounds (WGS84 SW/NE):", meta["bounds"])

    # Register provenance so the Data Sources modal lists the layer.
    try:
        sys.path.insert(0, str(ROOT))
        import sqlite3
        from app import data_loader as dl
        from app.config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        dl.record_source(
            conn, "usgs_htmc",
            "USGS Historical Topographic Map Collection — Wyandotte 1906 / Detroit 1905",
            "https://www.usgs.gov/programs/national-geospatial-program/historical-topographic-maps-preserving-past",
            "ok", total_tiles,
            f"{total_tiles} self-hosted map tiles built from two public-domain "
            f"USGS HTMC GeoTIFFs (scan IDs 278613, 278077), collar-clipped to "
            f"the quad neatlines. Shows where water was mapped in 1905-1906 — "
            f"nothing more. 1:62,500 sheets georeferenced by corner ticks; "
            f"positional error on the order of tens of meters (not "
            f"parcel-level). Not a contamination layer; no link to any modern "
            f"record is asserted or inferred.")
        conn.commit()
        conn.close()
        print("  data_sources: usgs_htmc registered")
    except Exception as e:                       # noqa: BLE001
        print(f"  (data_sources registration skipped: {e})")


if __name__ == "__main__":
    main()
