#!/usr/bin/env python3
"""
check_logicmaps.py -- every map's logic chunk laid out alike.

build.sh links each map's logic chunk alone (out/logic_N.bin, its labels
out/logic_N.lbl).  The cartridge's code reads the one in WRAM at the
addresses the game's map's has (LOGICFAR, altmaps.inc's logic_ensure), so
every map's must have every label where the game's map's has it, and be
the same size, which genmaps.py's padding (graphtables.lay_out) makes so.
"""
import glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")


def labels(path):
    out = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and p[0] == "al":
            out[p[2].lstrip(".")] = int(p[1], 16)
    return out


def main():
    paths = sorted(glob.glob(os.path.join(OUT, "logic_*.lbl")), key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
    base = labels(paths[0])
    size = os.path.getsize(paths[0][:-4] + ".bin")
    bad = []
    for p in paths[1:]:
        got = labels(p)
        diff = sorted(n for n in set(base) | set(got) if base.get(n) != got.get(n))
        if diff:
            bad.append("%s: %s" % (os.path.basename(p), ", ".join(diff[:6])))
        if os.path.getsize(p[:-4] + ".bin") != size:
            bad.append("%s: %d bytes, the game's map's %d" % (os.path.basename(p)[:-4] + ".bin",
                                                             os.path.getsize(p[:-4] + ".bin"), size))
    if bad:
        print("check_logicmaps: maps' logic laid out apart:")
        for b in bad:
            print("   " + b)
        return 1
    print("logic: %d maps' chunks laid out alike, %d bytes" % (len(paths), size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
