#!/usr/bin/env python3
"""
genchest.py -- src/openchest.txt to two NES tiles of 2bpp CHR.

The open chest's lid.  Kept as text because it is the one piece of artwork in
this project and it will want changing by eye; the ROM wants planar bitplanes,
which nobody can edit by eye.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src", "openchest.txt")
#  Not gen/bin: that is a symlink to the vendored game/bin, and a build
#  product has no business in the 6502 source tree.
OUT = os.path.join(ROOT, "out", "openchest.chr")
INK = {" ": 0, ".": 1, "o": 2, "X": 3}


def main():
    rows = [l.rstrip("\n") for l in open(SRC)
            if l.strip() and not l.lstrip().startswith("#")]
    if len(rows) != 8:
        sys.exit("openchest.txt: expected 8 pixel rows, got %d" % len(rows))
    for n, r in enumerate(rows):
        if len(r) != 16:
            sys.exit("openchest.txt line %d: expected 16 columns, got %d" % (n + 1, len(r)))
        bad = set(r) - set(INK)
        if bad:
            sys.exit("openchest.txt line %d: %s is not one of '%s'"
                     % (n + 1, sorted(bad), "".join(INK)))
    px = [[INK[c] for c in r] for r in rows]

    out = bytearray()
    for half in (0, 8):                     # left tile, then right
        lo = bytearray(8)
        hi = bytearray(8)
        for y in range(8):
            for x in range(8):
                v = px[y][half + x]
                lo[y] |= (v & 1) << (7 - x)
                hi[y] |= ((v >> 1) & 1) << (7 - x)
        out += lo + hi
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "wb").write(out)
    print("open chest: %d bytes -> %s" % (len(out), os.path.relpath(OUT, ROOT)))


if __name__ == "__main__":
    main()
