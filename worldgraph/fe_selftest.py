#!/usr/bin/env python3
"""
fe_selftest.py -- the entrance-and-floor checks, shown to bite.

Each case breaks one thing the shuffle must get right and confirms the check
for it notices; vanilla and a shuffled seed must come out clean first.
"""
import sys

import build
import fecheck
import romdata as rd
import wiring

fails = []


def expect(what, got, want):
    if got != want:
        fails.append("%s: got %r, want %r" % (what, got, want))


def main():
    van = wiring.Wiring.vanilla()
    g, *_ = build.build()
    r = fecheck.report(g, van)
    expect("vanilla: no strands", r["strands"], [])
    expect("vanilla: nothing unreachable", r["unreachable locations"], [])

    w = wiring.fe_shuffle(7)
    g, *_ = build.build(wiring=w)
    r = fecheck.report(g, w)
    expect("seed 7: clean", (r["strands"], r["shared landings"], r["dealt without a warp back"]), ([], {}, []))

    #  Without the warp-back edges, every dungeon floor looks like a trap.
    g, *_ = build.build()
    g.returns = [e for e in g.returns if not e[3].startswith("warp back")]
    expect("vanilla without warps back: strands", bool(fecheck.report(g, van)["strands"]), True)

    #  The past is one-way by design; without the exemption it shows.
    g, *_ = build.build()
    keep = fecheck.ONE_WAY_MAPS
    fecheck.ONE_WAY_MAPS = set()
    try:
        expect("vanilla, ToFR not exempt: strands", bool(fecheck.report(g, van)["strands"]), True)
    finally:
        fecheck.ONE_WAY_MAPS = keep

    #  A floor dealt where nothing warps back: Earth Cave B1's way down
    #  pointed at Coneria Castle 2F, whose only way out is its own teleport.
    bad = wiring.fe_shuffle(7)
    tid = 5                                     # Earth B1 -> B2 in vanilla
    bad.normal[tid] = rd.normal_tele(0)         # Coneria 1F -> 2F's landing
    bad.dealt = set(bad.dealt) | {bad.normal[tid]}
    g, *_ = build.build(wiring=bad)
    r = fecheck.report(g, bad)
    expect("Coneria 2F dealt as a floor: no warp back", [t for t, *_ in r["dealt without a warp back"]], [tid])
    expect("...and two callers on one landing", rd.normal_tele(0) in r["shared landings"], True)

    #  An exit sent somewhere the party cannot come back from: the sea.
    bad = wiring.Wiring.vanilla()
    bad.exits[2] = (0, 0)                       # the Ice Cave's exit, into the corner of the ocean
    g, *_ = build.build(wiring=bad)
    expect("an exit into the ocean: strands", bool(fecheck.report(g, bad)["strands"]), True)

    if fails:
        print("FAIL (%d)" % len(fails))
        for f in fails:
            print("   " + f)
        return 1
    print("fe_selftest: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
