"""Generate app_icon.ico — Michigan silhouette in green on a dark rounded square.

Renders at 1024x1024 from the real Michigan-counties GeoJSON we already have,
then writes a multi-resolution .ico containing 16/32/48/64/128/256 px frames.

Run from project root:
    py scripts/make_icon.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GEOJSON = PROJECT_ROOT / "data" / "michigan_counties.geojson"
OUTPUT  = PROJECT_ROOT / "app_icon.ico"

SIZE = 1024                 # render size
PAD = 110                   # padding around the silhouette
BG_COLOR = (13, 17, 23, 255)        # --bg
FG_COLOR = (63, 185, 80, 255)       # --accent green
FG_GLOW  = (63, 185, 80, 120)
OUTLINE  = (16, 60, 30, 255)
ACCENT   = (240, 180, 41, 255)      # --accent-2 amber leaf

ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _polygons(geom):
    """Yield each polygon's outer ring (skipping holes)."""
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    else:
        polys = geom["coordinates"]
    for poly in polys:
        yield poly[0]


def _bbox(features):
    xs, ys = [], []
    for f in features:
        for ring in _polygons(f["geometry"]):
            for lon, lat in ring:
                xs.append(lon)
                ys.append(lat)
    return min(xs), min(ys), max(xs), max(ys)


def _projector(bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    # equirectangular projection scaled into the inner rectangle
    span_lon = max_lon - min_lon
    span_lat = max_lat - min_lat
    inner = SIZE - 2 * PAD
    # preserve aspect by fitting the larger dimension
    scale_lon = inner / span_lon
    # lat range gets compressed by cos(mean_lat) — close enough at Michigan latitudes
    mean_lat_rad = math.radians((min_lat + max_lat) / 2)
    scale_lat = inner / (span_lat / math.cos(mean_lat_rad))
    scale = min(scale_lon, scale_lat)

    proj_w = span_lon * scale
    proj_h = (span_lat / math.cos(mean_lat_rad)) * scale
    off_x = (SIZE - proj_w) / 2
    off_y = (SIZE - proj_h) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = off_x + (lon - min_lon) * scale
        y = off_y + (max_lat - lat) / math.cos(mean_lat_rad) * scale
        return (x, y)

    return project


def _draw_leaf(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    """A small stylized amber leaf overlapping the bottom-right of the silhouette."""
    # leaf body — an ellipse rotated 45°, drawn via a polygon approximation
    pts = []
    for t_deg in range(0, 360, 6):
        t = math.radians(t_deg)
        a, b = r, r * 0.55
        x = a * math.cos(t)
        y = b * math.sin(t)
        # rotate 45°
        rx = x * math.cos(-math.pi / 4) - y * math.sin(-math.pi / 4)
        ry = x * math.sin(-math.pi / 4) + y * math.cos(-math.pi / 4)
        pts.append((cx + rx, cy + ry))
    draw.polygon(pts, fill=ACCENT, outline=(120, 90, 18, 255))
    # midrib
    draw.line(
        [(cx - r * 0.7, cy + r * 0.7), (cx + r * 0.7, cy - r * 0.7)],
        fill=(120, 90, 18, 255),
        width=max(2, int(r * 0.08)),
    )


def make_icon() -> Path:
    if not GEOJSON.exists():
        raise SystemExit(
            f"Michigan GeoJSON not found at {GEOJSON}\n"
            "Run the data loader first:  py -m app.data_loader"
        )
    gj = json.loads(GEOJSON.read_text())
    features = gj["features"]

    project = _projector(_bbox(features))

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # rounded-square background card
    draw.rounded_rectangle(
        (24, 24, SIZE - 24, SIZE - 24),
        radius=140,
        fill=BG_COLOR,
        outline=(40, 50, 65, 255),
        width=4,
    )

    # subtle inner glow (draw all polygons fat and blurred, then real polygons)
    glow_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    for f in features:
        for ring in _polygons(f["geometry"]):
            glow_draw.polygon([project(lon, lat) for lon, lat in ring], fill=FG_GLOW)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(glow_layer)

    # filled state silhouette (all counties merged visually by overlapping fills)
    for f in features:
        for ring in _polygons(f["geometry"]):
            pts = [project(lon, lat) for lon, lat in ring]
            draw.polygon(pts, fill=FG_COLOR, outline=OUTLINE)

    # accent leaf near lower-right of Lower Peninsula
    _draw_leaf(draw, SIZE * 0.74, SIZE * 0.72, r=SIZE * 0.085)

    # write multi-resolution .ico
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT, format="ICO", sizes=ICO_SIZES)
    print(f"[ok] wrote {OUTPUT}  ({OUTPUT.stat().st_size:,} bytes)")
    return OUTPUT


if __name__ == "__main__":
    make_icon()
