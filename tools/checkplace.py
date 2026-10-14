#!/usr/bin/env python3
"""
checkplace.py -- is every placement winnable, on the world graph itself?

    pypy3 tools/checkplace.py [seeds]

randoref.build_placement draws from logicdata.py, the tables genlogic.py
distilled from ../worldgraph; test_rando_place holds the cartridge to it.
This checks the other side, without the tables: each placement is put into
the world graph's own locations, and the game played through on the graph
from what the party starts with, Early flags and all.  A seed that does not
reach Chaos is printed.  It needs ../worldgraph, which is why it is not part
of test_options.py.
"""
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "worldgraph"))

import randoref as R  # noqa: E402
import genlogic as G  # noqa: E402
import analysis  # noqa: E402
import build  # noqa: E402
import placement  # noqa: E402
from model import BIT  # noqa: E402

#  name: (Key items, item row bytes, gear bytes, Early flags), as
#  test_rando_place has them.
CONFIGS = {
    "beginner":   (1, [0x20, 0x00, 0x00], [0x81, 0x00], 0x0F),
    "late":       (1, [0x20, 0x00, 0x00], [0x81, 0x00], 0x00),
    "bridge":     (1, [0x00, 0x00, 0x00], [0x81, 0x00], 0x0F),
    "everything": (1, [0x00, 0x00, 0x00], [0xFF, 0x01], 0x0F),
    "wide-bare":  (2, [0x00, 0x00, 0x00], [0x00, 0x00], 0x0F),
    "all-loose":  (1, [0x65, 0x55, 0x55], [0x00, 0x00], 0x0F),
    "free-ent":   (2, [0xAA, 0x02, 0x08], [0xFE, 0x01], 0x0F),
}


def world(early):
    names = tuple(n for k, n in enumerate(G.EARLY) if early >> k & 1)
    g, ow, _, _ = build.build(early=names)
    idx, _ = G.order(g)
    adj = analysis.adjacency(g, placement.vehicle_edges(g, ow))
    vanilla = {k: g.locations[k].reward for k in idx[:248]}
    return g, idx, adj, vanilla


def winnable(g, adj, free):
    owned = free
    while True:
        seen = analysis.reach(g, owned, adj)
        gained = 0
        for loc in g.locations:
            if not (loc.req & ~owned) and loc.reward in BIT and any(n in seen for n in loc.nodes):
                gained |= BIT[loc.reward]
        if not gained & ~owned:
            return bool(owned & BIT["CHAOS"])
        owned |= gained


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    worlds = {}
    t0 = time.time()
    lost = 0
    for name, cfg in CONFIGS.items():
        early = cfg[3]
        if early not in worlds:
            worlds[early] = world(early)
        g, idx, adj, vanilla = worlds[early]
        free = R.place_setup(*cfg)[0]
        stats = Counter()
        for seed in range(1, seeds + 1):
            out = R.build_placement(seed, *cfg)
            if out is None:
                stats["unplaced"] += 1
                continue
            for k in idx[:248]:
                g.locations[k].reward = None
            for i, c in enumerate(out):
                if c != 0xFF and R.PLACE_ITEMS[i][0] in BIT:
                    g.locations[idx[c]].reward = R.PLACE_ITEMS[i][0]
            if winnable(g, adj, free):
                stats["won"] += 1
            else:
                print("  %s seed %d: Chaos out of reach" % (name, seed))
                lost += 1
            for k, r in vanilla.items():
                g.locations[k].reward = r
        print("%-11s %d seeds: %d winnable, %d with no placement" % (
            name, seeds, stats["won"], stats["unplaced"]))
    print("%.0fs" % (time.time() - t0))
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
