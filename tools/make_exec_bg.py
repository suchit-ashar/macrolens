"""Prepare the Executive Summary card background (app/static/exec_bg.webp) from the owner's image.

The source has white rounded corners baked in, so a margin is trimmed off; the top quarter fades to
transparent so the image blends into the card's CSS navy gradient when the summary is taller than the image.

Usage:  python tools/make_exec_bg.py path/to/source_image
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "exec_bg.webp"
TRIM, WIDTH, FADE = 0.03, 1400, 0.28  # trim fraction per side, output width, faded top fraction


def main(src: str) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    t = int(round(min(w, h) * TRIM * 2))  # same pixel margin on every side
    im = im.crop((t, t, w - t, h - t))
    im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    a = np.asarray(im.convert("RGBA"), np.float32).copy()
    ramp = np.clip(np.linspace(0, 1, a.shape[0]) / FADE, 0, 1)
    a[..., 3] *= (ramp * ramp * (3 - 2 * ramp))[:, None]  # smoothstep fade-in from the top
    OUT.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a.astype(np.uint8), "RGBA").save(OUT, "WEBP", quality=86, alpha_quality=90, method=6)
    top = np.asarray(im)[int(a.shape[0] * FADE)]
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB), {im.size}; colour at fade end: "
          f"left {tuple(top[20])}, mid {tuple(top[len(top) // 2])}, right {tuple(top[-20])}")


if __name__ == "__main__":
    main(sys.argv[1])
