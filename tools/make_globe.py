"""Draw the dotted world globe used as the page background (app/static/globe.webp).

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

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "globe.webp"
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
            # square "pixel" dots, foreshortened towards the edge of the sphere like the reference
            if is_land(polys, lon_d if lon_d <= 180 else lon_d - 360, lat_d):
                hw, hh = SS * (1.4 + 2.0 * cosc), SS * (1.4 + 2.0 * cosc) * (0.55 + 0.45 * cosc)
                col = LAND + (int(255 * (0.30 + 0.62 * cosc)),)
            else:
                hw = hh = SS * (0.45 + 0.55 * cosc)
                col = OCEAN + (int(255 * 0.18 * cosc),)
            draw.rectangle([x - hw, y - hh, x + hw, y + hh], fill=col)
        row += 1
        lat_d += STEP
    dots = dots.convert("RGBa").resize((SIZE, SIZE), Image.LANCZOS).convert("RGBA")  # premultiplied: no colour fringes

    # shaded sphere + atmosphere, computed per pixel at the final size
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    cc, rr = SIZE / 2, SIZE * 0.47
    dx, dy = (xx - cc) / rr, (yy - cc) / rr
    d = np.sqrt(dx * dx + dy * dy)
    inside = d <= 1.0
    nz = np.sqrt(np.clip(1 - d * d, 0, 1))
    lit = np.clip(0.55 * nz + 0.45 * (dx - dy) / 2 + 0.35, 0, 1)  # brighter towards the top-right
    sphere = np.zeros((SIZE, SIZE, 4), np.float32)
    sphere[..., :3] = np.array([200, 222, 252], np.float32)  # pale blue body
    sphere[..., 3] = np.where(inside, 255 * (0.30 + 0.45 * lit), 0)
    # limb: a bright, white-blue rim just inside the edge, strongest on the lower-left (sun-lit haze)
    side = np.clip(0.5 + 0.5 * (-dx + dy) / np.sqrt(2), 0, 1)
    rim_in = np.exp(-((1 - d) / 0.035) ** 2) * inside
    halo = np.exp(-((d - 1) / 0.06) ** 2) * (~inside)
    glow = np.zeros_like(sphere)
    glow[..., :3] = 255
    glow[..., 3] = 255 * np.clip(0.85 * rim_in * (0.35 + 0.65 * side) + 0.55 * halo * (0.25 + 0.75 * side), 0, 1)

    def over(dst, src):
        sa, da = src[..., 3:4] / 255, dst[..., 3:4] / 255
        oa = sa + da * (1 - sa)
        rgb = (src[..., :3] * sa + dst[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
        return np.concatenate([rgb, oa * 255], axis=-1)

    a = over(over(sphere, np.asarray(dots, np.float32)), glow)

    # fade towards the bottom-left so the globe melts into the page behind the content
    fx, fy = xx / (SIZE - 1), yy / (SIZE - 1)
    fade = np.clip(((fx + (1 - fy)) / 2 - 0.08) / 0.5, 0.12, 1.0)
    a[..., 3] *= fade
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    out.save(OUT, "WEBP", quality=88, alpha_quality=90, method=6)  # smooth gradients, small file (PNG palette bands)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
