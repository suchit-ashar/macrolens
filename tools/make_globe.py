"""Draw the dotted world globe used as the page background (app/static/globe.png).

One-off design build step, not part of the daily data pipeline. Land outlines come from
Natural Earth 1:110m land (public domain, https://www.naturalearthdata.com/), file
ne_110m_land.geojson from https://github.com/nvkelso/natural-earth-vector.

Usage:  python tools/make_globe.py path/to/ne_110m_land.geojson
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "globe.png"
SIZE, SS = 920, 3         # final size in pixels (shown at about half that), supersampling factor
LAT0, LON0 = 20.0, 62.0   # view centre: Arabian Sea, so India, Europe, Africa and East Asia are in view
STEP = 1.8                # dot spacing in degrees
LAND, OCEAN = (37, 99, 235), (96, 165, 250)


def load_polygons(path: str) -> list[tuple]:
    polys = []
    for feat in json.loads(Path(path).read_text(encoding="utf-8"))["features"]:
        geom = feat["geometry"]
        parts = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for rings in parts:
            xs, ys = [p[0] for p in rings[0]], [p[1] for p in rings[0]]
            polys.append((min(xs), max(xs), min(ys), max(ys), rings[0], rings[1:]))
    return polys


def in_ring(ring: list, x: float, y: float) -> bool:
    hit, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def is_land(polys: list[tuple], lon: float, lat: float) -> bool:
    for x0, x1, y0, y1, outer, holes in polys:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and in_ring(outer, lon, lat):
            return not any(in_ring(h, lon, lat) for h in holes)
    return False


def main(src: str) -> None:
    polys = load_polygons(src)
    w = SIZE * SS
    c, r = w / 2, w * 0.47
    lat0, lon0 = math.radians(LAT0), math.radians(LON0)

    # dots only: the soft glow behind the sphere is a CSS gradient, which keeps this file small
    dots = Image.new("RGBA", (w, w), LAND + (0,))
    draw = ImageDraw.Draw(dots)
    row, lat_d = 0, -88.0
    while lat_d <= 88.0:
        lat = math.radians(lat_d)
        n = max(1, round(360 / STEP * math.cos(lat)))
        for k in range(n):
            lon_d = -180 + 360 * (k + 0.5 * (row % 2)) / n
            lon = math.radians(lon_d)
            cosc = math.sin(lat0) * math.sin(lat) + math.cos(lat0) * math.cos(lat) * math.cos(lon - lon0)
            if cosc <= 0.03:
                continue
            x = c + r * math.cos(lat) * math.sin(lon - lon0)
            y = c - r * (math.cos(lat0) * math.sin(lat) - math.sin(lat0) * math.cos(lat) * math.cos(lon - lon0))
            if is_land(polys, lon_d if lon_d <= 180 else lon_d - 360, lat_d):
                rad, col = SS * (1.2 + 2.3 * cosc), LAND + (int(255 * (0.22 + 0.68 * cosc)),)
            else:
                rad, col = SS * (0.5 + 0.6 * cosc), OCEAN + (int(255 * 0.16 * cosc),)
            draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=col)
        row += 1
        lat_d += STEP
    img = dots.convert("RGBa").resize((SIZE, SIZE), Image.LANCZOS).convert("RGBA")  # premultiplied: no colour fringes

    # fade towards the bottom-left so the globe melts into the page behind the content
    a = np.asarray(img, dtype=np.float32).copy()
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / (SIZE - 1)
    fade = np.clip(((xx + (1 - yy)) / 2 - 0.12) / 0.55, 0.08, 1.0)
    a[..., 3] *= fade
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = Image.fromarray(a.astype(np.uint8), "RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    out.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
