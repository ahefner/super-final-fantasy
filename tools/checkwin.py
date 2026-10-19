#!/usr/bin/env python3
"""
checkwin.py -- the map edit screen's fast path, proved.

    pypy3 tools/checkwin.py

owscreen.asm's ows_check skips the unwinnable check (rando_winnable) on a
tick unless Ship in Drydock is ticked or the SHIP or the FLOATER is removed:
with neither, every combination of the map edits can be won.  This checks
that over all 8,192 combinations of the other thirteen, under Key items
Vanilla (the items at home, swept) and Standard (every key item held, as
Wide's check is too), with no Early flag and nothing free -- the hardest
case, since the Early flags only waive requirements and Free items are only
held sooner.  randoref.winnable is the check (test_winnable holds the cart's
to it).  A few minutes under pypy3; run it after the logic changes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owedits as O  # noqa: E402
import randoref as R  # noqa: E402


def main():
    dry = 1 << O.SHIP_DRYDOCK
    bad = [(ki, f) for f in range(1 << len(O.SETTINGS)) if not f & dry
           for ki in (R.KEYITEMS_VANILLA, R.KEYITEMS_STANDARD)
           if not R.winnable(ki, [0, 0, 0], 0, f)[0]]
    for ki, f in bad[:10]:
        print("  Key items %d, edits $%04X: cannot be won" % (ki, f))
    print("%d of %d combinations without Ship in Drydock cannot be won" % (len(bad), 2 * (1 << 13)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
