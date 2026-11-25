#!/usr/bin/env python3
"""Build the historic-WATER-only tile pyramid (Downriver Detroit).

Companion to build_historic_topo_tiles.py: same two public-domain USGS HTMC
GeoTIFFs (Wyandotte 1906 / Detroit 1905), same neatline clip, same EPSG:3857
z15-aligned mosaic grid, same z9..z15 XYZ output — but instead of the full
sheets it extracts ONLY the blue-printed water ink by color and tints it
bright cyan.

THE RULE (validated in the Nov 2026 color investigation): the scans are so
age-yellowed that no literal blue survives — water ink reads as a green-vs-
red signature instead (ink G-R ~= +19..+32, paper -10..-1, brown contours
-23..-33, black ink ~=0). Extraction is GRADED, not binary — the overlay is
the actual scanned lithography, not traced geometry:

    alpha = clip((G - R - 6) * 14, 0, 255)
    alpha[7x7-neighborhood mean alpha < 18] = 0     # despeckle black-edge jitter

computed on the NATIVE sheet pixels (where the rule was calibrated), then
only the alpha band is warped to the mosaic grid. What survives includes
everything the engraver printed in blue: channels (as their parallel
water-lining, not solid fill), creeks, marsh tufts, dashed intermittent
drains, and blue water-name lettering. Marsh vs channel vs lettering is NOT
separable by color — they are the same ink.

Output: static/tiles/historic_water/{z}/{x}/{y}.png (RGBA, quantized) +
meta.json. Registers provenance as 'usgs_htmc_water' in data_sources.
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
OUT_DIR = ROOT / "static" / "tiles" / "historic_water"

S3 = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Maps/HistoricalTopo/GeoTIFF/MI/"
SHEETS = [
    ("MI_Wyandotte_278613_1906_62500_geo.tif", (-83.25, 42.00, -83.00, 42.25)),
    ("MI_Detroit_278077_1905_62500_geo.tif",   (-83.25, 42.25, -83.00, 42.50)),
]

ZMAX, ZMIN = 15, 9
TILE = 256
WEB_R = 6378137.0
ORIGIN = math.pi * WEB_R
INK = (43, 217, 255)                              # bright cyan tint


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
    ring = []
    for i in range(pts):
        ring.append((w + (e - w) * i / pts, s))
    for i in range(pts):
        ring.append((e, s + (n - s) * i / pts))
    for i in range(pts):
        ring.append((e - (e - w) * i / pts, n))
    for i in range(pts):
        ring.append((w, n - (n - s) * i / pts))
    ring.append(ring[0])
    xs, ys = rio_transform("EPSG:4267", crs, [p[0] for p in ring], [p[1] for p in ring])
    return {"type": "Polygon", "coordinates": [list(zip(xs, ys))]}


def box_mean(a: np.ndarray, r: int = 3) -> np.ndarray:
    """7x7 (r=3) neighborhood mean via summed-area table."""
    pad = np.pad(a.astype(np.float32), r, mode="edge")
    cs = pad.cumsum(0).cumsum(1)
    cs = np.pad(cs, ((1, 0), (1, 0)))
    n = 2 * r + 1
    return (cs[n:, n:] - cs[:-n, n:] - cs[n:, :-n] + cs[:-n, :-n]) / (n * n)


def water_alpha(rgb: np.ndarray) -> np.ndarray:
    """The validated graded G-R rule. rgb is HxWx3 uint8 -> HxW uint8 alpha."""
    a = rgb.astype(np.int16)
    gr = (a[:, :, 1] - a[:, :, 0]).astype(np.float32)
    alpha = np.clip((gr - 6.0) * 14.0, 0, 255)
    alpha[box_mean(alpha, 3) < 18] = 0
    return alpha.astype(np.uint8)


def main():
    res = 2 * ORIGIN / (TILE * 2 ** ZMAX)
    clipped = []
    for name, (w, s, e, n) in SHEETS:
        p = fetch(name)
        with rasterio.open(p) as src:
            poly = neatline_poly_in(src.crs, w, s, e, n)
            data, tr = rio_mask(src, [poly], crop=True, filled=True, nodata=255)
            rgb = np.moveaxis(data, 0, -1)
            # inside-neatline mask: nodata fill is paper-white 255s which the
            # G-R rule maps to 0 anyway, but mask explicitly for cleanliness
            inside = ~rio_mask(src, [poly], crop=True, filled=False)[0].mask[0]
            alpha = water_alpha(rgb)
            alpha[~inside] = 0
            clipped.append((alpha, tr, src.crs))
            print(f"  {name}: ink pixels {np.count_nonzero(alpha)/alpha.size*100:.2f}%")

    # Identical mosaic grid to the base build (same quads, same snapping).
    def merc(lon, lat):
        x = lon / 180.0 * ORIGIN
        y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / math.pi * ORIGIN
        return x, y
    x0, y1 = merc(-83.25, 42.50)
    x1, y0 = merc(-83.00, 42.00)
    pad = 500.0
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    tile_m = TILE * res
    x0 = math.floor((x0 + ORIGIN) / tile_m) * tile_m - ORIGIN
    y1 = ORIGIN - math.floor((ORIGIN - y1) / tile_m) * tile_m
    x1 = math.ceil((x1 + ORIGIN) / tile_m) * tile_m - ORIGIN
    y0 = ORIGIN - math.ceil((ORIGIN - y0) / tile_m) * tile_m
    width = round((x1 - x0) / res)
    height = round((y1 - y0) / res)
    dst_tr = from_origin(x0, y1, res, res)
    print(f"  mosaic: {width}x{height} px @ z{ZMAX} grid")

    mosaic = np.zeros((height, width), dtype=np.uint8)
    for alpha, tr, crs in clipped:
        reproject(alpha, mosaic, src_transform=tr, src_crs=crs,
                  dst_transform=dst_tr, dst_crs="EPSG:3857",
                  resampling=Resampling.bilinear, dst_nodata=0,
                  init_dest_nodata=False)

    wb = array_bounds(height, width, dst_tr)
    def inv_merc(x, y):
        return (x / ORIGIN * 180.0,
                math.degrees(2 * math.atan(math.exp(y / ORIGIN * math.pi)) - math.pi / 2))
    sw = inv_merc(wb[0], wb[1]); ne = inv_merc(wb[2], wb[3])

    img = Image.fromarray(mosaic, "L")
    del mosaic, clipped

    total_bytes = total_tiles = 0
    tx0_base = round((x0 + ORIGIN) / tile_m)
    ty0_base = round((ORIGIN - y1) / tile_m)
    for z in range(ZMAX, ZMIN - 1, -1):
        shrink = 2 ** (ZMAX - z)
        zw, zh = img.width // shrink, img.height // shrink
        zimg = img if shrink == 1 else img.resize((zw, zh), Image.LANCZOS)
        tx_origin = tx0_base / shrink
        ty_origin = ty0_base / shrink
        ntx = math.ceil(tx_origin + zw / TILE) - math.floor(tx_origin)
        nty = math.ceil(ty_origin + zh / TILE) - math.floor(ty_origin)
        n = b = 0
        for ix in range(ntx):
            for iy in range(nty):
                tx = math.floor(tx_origin) + ix
                ty = math.floor(ty_origin) + iy
                px0 = round((tx - tx_origin) * TILE)
                py0 = round((ty - ty_origin) * TILE)
                sx0, sy0 = max(0, px0), max(0, py0)
                sx1, sy1 = min(zw, px0 + TILE), min(zh, py0 + TILE)
                if sx1 <= sx0 or sy1 <= sy0:
                    continue
                a_tile = Image.new("L", (TILE, TILE), 0)
                a_tile.paste(zimg.crop((sx0, sy0, sx1, sy1)), (sx0 - px0, sy0 - py0))
                if a_tile.getextrema()[1] == 0:
                    continue                      # no ink in this tile
                tile = Image.new("RGBA", (TILE, TILE), (*INK, 0))
                tile.putalpha(a_tile)
                d = OUT_DIR / str(z) / str(tx)
                d.mkdir(parents=True, exist_ok=True)
                fp = d / f"{ty}.png"
                tile.quantize(colors=64, method=Image.FASTOCTREE).save(
                    fp, "PNG", optimize=True)
                n += 1
                b += fp.stat().st_size
        total_tiles += n
        total_bytes += b
        print(f"  z{z}: {n} tiles, {b/1e6:.2f} MB")

    meta = {"bounds": [[round(sw[1], 6), round(sw[0], 6)],
                       [round(ne[1], 6), round(ne[0], 6)]],
            "min_zoom": ZMIN, "max_zoom": ZMAX,
            "rule": "alpha=clip((G-R-6)*14,0,255); 7x7-mean<18 zeroed; cyan tint",
            "sources": [S3 + s for s, _ in SHEETS]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"TOTAL: {total_tiles} tiles, {total_bytes/1e6:.2f} MB -> {OUT_DIR}")

    # Provenance row — this layer is DERIVED by color extraction, say so.
    try:
        sys.path.insert(0, str(ROOT))
        import sqlite3
        from app import data_loader as dl
        from app.config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        dl.record_source(
            conn, "usgs_htmc_water",
            "Historic water (1905-06) — color-extracted from USGS HTMC sheets",
            "https://www.usgs.gov/programs/national-geospatial-program/historical-topographic-maps-preserving-past",
            "ok", total_tiles,
            f"{total_tiles} tiles derived from the Wyandotte 1906 / Detroit "
            f"1905 USGS sheets by COLOR EXTRACTION of the blue water ink "
            f"(rule: alpha = clip((G-R-6)*14, 0, 255), pixels with 7x7 "
            f"neighborhood mean alpha < 18 zeroed; graded, not binary; "
            f"tinted cyan). The actual scanned ink, not traced/digitized "
            f"geometry. Cannot tell marsh from open channel from blue "
            f"place-name lettering (same ink). Same tens-of-meters "
            f"positional error as the base sheets. Shows where water was "
            f"drawn in 1905-06 and nothing more — no link to any modern "
            f"record is asserted or inferred.")
        conn.commit()
        conn.close()
        print("  data_sources: usgs_htmc_water registered")
    except Exception as e:                        # noqa: BLE001
        print(f"  (data_sources registration skipped: {e})")


if __name__ == "__main__":
    main()
