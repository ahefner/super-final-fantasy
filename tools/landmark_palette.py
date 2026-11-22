#!/usr/bin/env python3
"""
landmark_palette.py -- art/landmark-palette.png, the colours the landmarks'
and houses' PNGs may use, as swatches to pick from (user, 2026-11-21: "a
palette PNG so I can pick these colors without remembering the RGB values.
Not part of the game build, just an aid for doing art").  Not run by
build.sh; run it again if the overworld palette or the shades change.

The swatches, a row each, left to right (the image's own palette holds just
these, then the background):

  1  magenta, "nothing here" (the picture's half only); black (both halves)
  2  the picture's half, palette 0 -- Coneria, Elfland, Ordeals, the Temple,
     the houses: grass green, grey, white
  3  the picture's half, palette 1 -- the volcano, the Mirage Tower: grass
     green, orange, peach
  4  the ground's half may use rows 1-3 (not magenta) and these, the other
     palettes' colours: the swamp's light blue and blue, light green, dark
     green
  5  the ground's half, the derived colours (snesmap.inc's M7DERIVEn): the
     shades -- dark grass, dark swamp blue, dark grey -- and the Mountains'
     browns

The colours are genm7.py's, as it reads the PNGs: each pixel snaps to the
nearest allowed one.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import genm7, genpal, pngio

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "art", "landmark-palette.png")
SW, GAP, PAD = 24, 6, 8
BACK = (40, 40, 48)


def main():
    tsa = open(os.path.join(ROOT, "game", "bank_00.dat"), "rb").read()[:0x400]
    owpal = tsa[0x380:0x3B0]
    nes = lambda i: genpal.NESPAL[owpal[i] & 0x3F]
    pal0 = [nes(0 * 4 + c) for c in (1, 2, 3)]
    pal1 = [nes(1 * 4 + c) for c in (1, 2, 3)]
    seen = set(pal0) | set(pal1) | {nes(0)}
    others = []
    for p in (2, 3):
        for c in (1, 2, 3):
            if nes(p * 4 + c) not in seen and nes(p * 4 + c) not in others:
                others.append(nes(p * 4 + c))
    shades = [genpal.NESPAL[genm7.derive(owpal[i] & 0x3F, rows, hues)] for i, _, rows, hues in genm7.derived()]
    rows = [[genm7.KEY, nes(0)], pal0, pal1, others, shades]
    colours = []
    for row in rows:
        for c in row:
            if c not in colours:
                colours.append(c)
    pal = colours + [BACK]
    w = PAD * 2 + max(len(r) for r in rows) * (SW + GAP) - GAP
    h = PAD * 2 + len(rows) * (SW + GAP) - GAP
    idx = [[len(pal) - 1] * w for _ in range(h)]
    for r, row in enumerate(rows):
        for k, c in enumerate(row):
            x0, y0 = PAD + k * (SW + GAP), PAD + r * (SW + GAP)
            for y in range(y0, y0 + SW):
                for x in range(x0, x0 + SW):
                    idx[y][x] = pal.index(c)
    pngio.png_write_indexed(OUT, idx, pal)
    print("landmark_palette: wrote %s" % os.path.relpath(OUT, ROOT))
    for r, row in enumerate(rows):
        print("  row %d: %s" % (r + 1, "  ".join("(%d, %d, %d)" % c for c in row)))


if __name__ == "__main__":
    main()
