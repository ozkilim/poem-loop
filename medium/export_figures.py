#!/usr/bin/env python3
"""Screenshot each figure of the blog page (export mode) to a trimmed 2x PNG on white.
  python medium/export_figures.py <rendered blog html>
"""
import subprocess, sys
from pathlib import Path
from PIL import Image, ImageChops

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = Path(__file__).resolve().parent / "images"
FIGS = [("x-cover", "00-cover"), ("x-machine", "01-the-loop"), ("x-fig1", "02-similarity"), ("x-triptych", "03-chain0-round-0-20-100"),
        ("x-fig2", "04-core-samples"), ("x-fig3", "05-rhyme-length-people"), ("x-fig4", "06-memory-and-quiet-spells"),
        ("x-fig5", "07-temperature-sweep"), ("x-twins", "08-butterfly-rewrites"),
        ("x-fig6", "09-twin-divergence"), ("x-fig7", "10-six-starting-poems"), ("x-eval", "11-does-it-get-better")]

def trim(p, pad=36):
    im = Image.open(p).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).point(lambda v: 255 if v > 6 else 0).getbbox()
    if box:
        l, t, r, b = box
        im = im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))
    im.save(p, optimize=True)
    return im.size

src = Path(sys.argv[1]).resolve()
for fid, name in FIGS:
    out = OUT / f"{name}.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=1100,2600", "--virtual-time-budget=6000", f"--screenshot={out}",
                    f"file://{src}#export-{fid}"], capture_output=True)
    print(name, trim(out))
