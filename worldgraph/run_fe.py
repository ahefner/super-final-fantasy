#!/usr/bin/env python3
"""
run_fe.py -- FFR-style entrance and floor shuffles through the graph.

    python3 run_fe.py [seeds] [--mixed] [--place]

For each seed: wiring.fe_shuffle, build the graph on it, and fecheck.report
with the vanilla item placement.  Prints a summary, and every seed that
strands the party, shares a landing, or deals a floor off a warp.

With --place, key items are placed by placement.py (FFR's PredictivePlacement)
and every check runs on the placed seed.  Without it, "winnable as placed" is
with vanilla's key items where vanilla has them,
which FFR never pairs with a shuffle -- it shows how much the wiring alone
moves the game, not whether a seed would be fair.  "Every location
reachable" is with every item owned: whether the wiring itself is sound.
"""
import sys
import time
from collections import Counter

import random

import build
import fecheck
import placement
import wiring


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 200
    mixed = "--mixed" in sys.argv
    t0 = time.time()
    stats = Counter()
    depths = Counter()
    worst = []
    place = "--place" in sys.argv
    spheres = Counter()
    for seed in range(1, n + 1):
        w = wiring.fe_shuffle(seed, mixed=mixed)
        g, ow, maps, missing = build.build(wiring=w)
        if place:
            p = placement.Placer(g, ow)
            placed, attempts = p.place(random.Random(seed))
            stats["placed on attempt 1"] += attempts == 1 and placed is not None
            stats["placed at all"] += placed is not None
            if placed is None:
                continue
            placement.apply(g, ow, p, placed)
        r = fecheck.report(g, w)
        spheres[r["spheres"]] += 1
        stats["winnable as placed"] += r["winnable"]
        stats["every location reachable"] += not r["unreachable locations"]
        stats["no strands"] += not r["strands"]
        stats["no shared landings"] += not r["shared landings"]
        stats["every dealt floor warps back"] += not r["dealt without a warp back"]
        depths[r["deepest level"]] += 1
        stats["Titan's Tunnel opens new ground"] += bool(r["titan opens"])
        if r["strands"] or r["shared landings"] or r["dealt without a warp back"] or r["unreachable locations"]:
            worst.append((seed, r, g))
    print("%d seeds%s in %.1fs" % (n, " (towns mixed in)" if mixed else "", time.time() - t0))
    for k, v in stats.items():
        print("  %-28s %d / %d" % (k, v, n))
    print("  deepest DoStandardMap level: %s" % ", ".join("%d: %d" % kv for kv in sorted(depths.items())))
    print("  spheres: %s" % ", ".join("%d: %d" % kv for kv in sorted(spheres.items())))
    for seed, r, g in worst[:8]:
        print("seed %d:" % seed)
        for owned, nodes in r["strands"][:2]:
            print("   strands with %d items: %s" % (owned, [g.nodes[x].label for x in nodes][:6]))
        if r["shared landings"]:
            print("   shared landings:", r["shared landings"])
        if r["dealt without a warp back"]:
            print("   dealt without a warp back:", r["dealt without a warp back"])
        if r["unreachable locations"]:
            print("   unreachable:", r["unreachable locations"][:6])


if __name__ == "__main__":
    main()
