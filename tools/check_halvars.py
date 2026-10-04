#!/usr/bin/env python3
"""
check_halvars.py -- no two live HAL variables may share a byte.

HAL_VARS is a flat run of bytes at $0800 that every HAL variable is placed in
by hand, as `h_name = HAL_VARS+$nn` in snesmap.inc.  There is no allocator and
no linker involvement, so nothing stops two names from naming one byte.  The
file is long, the declarations are grouped by feature rather than by address,
and a feature's group sits nowhere near the addresses its neighbours use -- so
the way to collide is simply to pick an offset that looks free in the group you
are reading.

A collision assembles without a word and costs a variable a value it never
wrote.  That is the worst class of bug this port produces: it is silent, it is
timing-dependent, and it looks like a fault in whichever feature reads the byte
second.  Merging is the likeliest moment for one to appear, because two
branches can each add a variable at the same free offset and the merge of two
disjoint hunks is clean.  That is the case this was written for.

Widths, which is the part worth getting right:

  - the declaration's own "N bytes" annotation, where there is one;
  - every `h_name+k` the sources actually reference.

A declaration claims {off+k} for each k seen, NOT the contiguous span up to the
largest one.  The difference matters: the pulse envelope variables are strided
per-channel arrays read as h_pestart and h_pestart+4, so they own $BC and $C0
and nothing between.  Treating that as a five-byte span invents four bytes the
variable does not own and reports collisions that are not there.

    python3 tools/check_halvars.py
"""
import collections, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "src", "snesmap.inc")

#  There is deliberately no allowlist here.  There used to be an overlap worth
#  excusing: the SCROLLSTAT trace's variables sat under the raster and tilemap
#  machinery that was allocated over them after the trace was retired, and its
#  declarations outlived its usefulness.  That instrumentation has since been
#  removed, so every declaration in the map is live and any shared byte is a
#  fault.  Keep it that way -- if a collision appears, move a variable rather
#  than teaching this check to ignore it.


def sources():
    out = []
    for pat in ("src/*.asm", "src/*.inc"):
        out += glob.glob(os.path.join(ROOT, pat))
    return "".join(open(f).read() for f in out)


def claims():
    """Every declaration -> the set of HAL_VARS offsets it owns."""
    src = sources()
    out = {}
    for line in open(MAP):
        m = re.match(r"(h_\w+)\s*=\s*HAL_VARS\+\$([0-9A-Fa-f]+)(.*)", line.strip())
        if not m:
            continue
        name, off, rest = m.group(1), int(m.group(2), 16), m.group(3)
        owned = {off}
        wide = re.search(r"(\d+)\s+bytes", rest)
        if wide:
            owned |= set(range(off, off + int(wide.group(1))))
        for k in re.findall(re.escape(name) + r"\s*\+\s*(\d+)", src):
            owned.add(off + int(k))
        out[name] = owned
    return out


def main():
    owned = claims()
    if len(owned) < 50:
        print("   ?? HAL variables          only %d declarations found; not checked"
              % len(owned))
        return 0

    who = collections.defaultdict(list)
    for name, offsets in owned.items():
        for off in offsets:
            who[off].append(name)

    bad = [(off, sorted(who[off])) for off in sorted(who) if len(who[off]) > 1]

    if bad:
        for off, names in bad:
            print("   CLASH  HAL_VARS+$%02X is claimed by %s"
                  % (off, " and ".join(names)))
        print("\ntwo live HAL variables share a byte, so one of them loses its"
              "\nvalue to the other.  Give one a free offset in snesmap.inc --"
              "\nthe highest claimed is $%02X." % max(who))
        return 1

    print("   ok     %-28s %d names over %d bytes, none shared"
          % ("HAL variables", len(owned), len(who)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
