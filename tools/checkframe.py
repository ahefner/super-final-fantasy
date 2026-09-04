#!/usr/bin/env python3
"""
checkframe.py -- look for the "black band across the top" artifact.

A frame where the top of the picture is near-black while the bottom is not
means forced blank was still on when the display started, i.e. the flush
overran vblank.  Reports mean brightness of the top 40% and the rest, so a
run of captures can be scanned without looking at every one.
"""
import os, struct, subprocess, sys, tempfile


def mean_rows(path, lo, hi):
    """Mean brightness over the fractional row range [lo, hi) of an image."""
    bmp = tempfile.mktemp(suffix=".bmp")
    subprocess.run(["sips", "-s", "format", "bmp", path, "--out", bmp],
                   capture_output=True)
    d = open(bmp, "rb").read()
    os.unlink(bmp)
    off = struct.unpack_from("<I", d, 10)[0]
    w, h = struct.unpack_from("<ii", d, 18)
    bpp = struct.unpack_from("<H", d, 28)[0]
    if bpp not in (24, 32):
        return None
    px = bpp // 8
    stride = (w * px + 3) & ~3
    total = n = 0
    # BMP rows run bottom-up, so row 0 of the picture is the last one stored.
    for y in range(int(h * lo), int(h * hi)):
        base = off + (h - 1 - y) * stride
        for x in range(0, w, 7):                  # sparse sample; plenty here
            p = base + x * px
            total += d[p] + d[p+1] + d[p+2]
            n += 3
    return total / n if n else 0


for path in sys.argv[1:]:
    top = mean_rows(path, 0.02, 0.40)
    bot = mean_rows(path, 0.45, 0.95)
    flag = ""
    if top is not None and bot is not None:
        if top < 12 and bot > 30:
            flag = "  <-- BLACK BAND ACROSS TOP"
        elif top < 12 and bot < 12:
            flag = "  (whole frame dark)"
    print("%-28s top=%6.1f  bottom=%6.1f%s"
          % (os.path.basename(path), top or 0, bot or 0, flag))
