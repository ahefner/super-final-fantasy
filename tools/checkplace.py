#!/usr/bin/env python3
"""
checkplace.py -- is every placement winnable, on the world graph itself?

    pypy3 tools/checkplace.py [seeds]

randoref.build_placement draws from logicdata.py, the tables genlogic.py
distilled from ../worldgraph; test_rando_place holds the cartridge to it.
This checks the other side, without the tables: each placement is put into
the world graph's own locations, and the game played through on the graph
from what the party starts with, Early flags and all.  The ship is where the
cart moors it -- at the dock of the map it is found on (logicdata.SHIP_DOCK,
which give_vehicle reads), or Coneria's when it is free -- and is boarded only
there, not by FFR's reading, the inner sea from anywhere, which placement's
own logic uses.  A seed that does not reach Chaos is printed.  It needs
../worldgraph, which is why it is not part of test_options.py.
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
import logicdata as LD  # noqa: E402
import analysis  # noqa: E402
import build  # noqa: E402
import placement  # noqa: E402
import romdata as rd  # noqa: E402
from model import BIT  # noqa: E402

SHIP_ITEM = [n for n, _ in R.PLACE_ITEMS].index("SHIP")

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
    #  The first playtest's (seed D1625106): Wide, every key item loose but
    #  the free BRIDGE and KEY, four gear incentives, Early King.
    "wide-loose": (2, [0x65, 0x59, 0x55], [0x39, 0x00], 0x01),
}


def world(early, dock):
    """The graph with the ship starting at a dock: build boards it there and
    nowhere else.  The airship is FFR's reading, flown from anywhere."""
    names = tuple(n for k, n in enumerate(G.EARLY) if early >> k & 1)
    pos = dict(rd.VANILLA_POS, ship=LD.DOCKS[dock][1])
    g, ow, _, _ = build.build(pos=pos, early=names)
    idx, _ = G.order(g)
    adj = analysis.adjacency(g, [e for e in placement.vehicle_edges(g, ow) if e[2] != BIT["SHIP"]])
    vanilla = {k: g.locations[k].reward for k in idx[:248]}
    return g, idx, adj, vanilla


def ship_docks(g, idx, out):
    """Where the cart moors the ship this placement gives: the dock of each
    map its location stands on, or Coneria's if it is not placed (free)."""
    c = out[SHIP_ITEM]
    if c == 0xFF:
        return {0}
    return {LD.SHIP_DOCK[rd.MAP_NAMES.index(g.nodes[n].where)] for n in g.locations[idx[c]].nodes}


def loose_spheres(cfg, out):
    """The playthrough sphere of each loose key item's place: 0 reached from
    the start, then one more for each round of collecting everything
    reached.  What forward placement moves later (randoref._forward)."""
    free, items, inc, inclocs, masks = R.place_setup(*cfg)
    placed = {c: i for i, c in enumerate(out) if c != 0xFF}
    owned, sph, s = free, {}, 0
    while True:
        new = [c for c, ms in enumerate(masks) if c not in sph and any(m & ~owned == 0 for m in ms)]
        if not new:
            break
        for c in new:
            sph[c] = s
            kind, ident = LD.LOCS[c][0], LD.LOCS[c][1]
            if kind == 3:
                owned |= 1 << ident
            elif c in placed and placed[c] < R.PLACE_KEYS:
                owned |= R._BIT[R._NAME[placed[c]]]
        s += 1
    return [sph[c] for c, i in placed.items() if i < R.PLACE_KEYS and c not in inclocs]


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
    def get(early, dock):
        if (early, dock) not in worlds:
            worlds[(early, dock)] = world(early, dock)
        return worlds[(early, dock)]

    for name, cfg in CONFIGS.items():
        early = cfg[3]
        free = R.place_setup(*cfg)[0]
        stats, moored, spheres = Counter(), Counter(), Counter()
        for seed in range(1, seeds + 1):
            out = R.build_placement(seed, *cfg)
            if out is None:
                stats["unplaced"] += 1
                continue
            spheres.update(loose_spheres(cfg, out))
            g0, idx0, _, _ = get(early, 0)
            won = True
            for dock in sorted(ship_docks(g0, idx0, out)):
                moored[LD.DOCKS[dock][0]] += 1
                g, idx, adj, vanilla = get(early, dock)
                for k in idx[:248]:
                    g.locations[k].reward = None
                for i, c in enumerate(out):
                    if c != 0xFF and R.PLACE_ITEMS[i][0] in BIT:
                        g.locations[idx[c]].reward = R.PLACE_ITEMS[i][0]
                if not winnable(g, adj, free):
                    print("  %s seed %d, ship at %s: Chaos out of reach" % (name, seed, LD.DOCKS[dock][0]))
                    won = False
                for k, r in vanilla.items():
                    g.locations[k].reward = r
            if won:
                stats["won"] += 1
            else:
                lost += 1
        print("%-11s %d seeds: %d winnable, %d with no placement; ship at %s" % (
            name, seeds, stats["won"], stats["unplaced"],
            ", ".join("%s %d" % kv for kv in moored.most_common())))
        n = sum(spheres.values())
        if n:
            print("%-11s loose key items by sphere: %s" % ("", " ".join(
                "%d:%.0f%%" % (k, 100 * spheres[k] / n) for k in sorted(spheres))))
    print("%.0fs" % (time.time() - t0))
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
