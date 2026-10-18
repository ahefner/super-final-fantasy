#!/usr/bin/env python3
"""
run_ffr_map.py -- is an FFR overworld winnable with the vanilla item placement?

    python3 run_ffr_map.py procgen1
    python3 run_ffr_map.py normal256/00CDC625
    python3 run_ffr_map.py --pool normal256      # summary over a whole pool

The dungeons, chests and NPCs are vanilla; only the overworld (and the exits,
start, vehicles and dock that move with it) comes from FFR's map.
"""
import sys
from collections import Counter

import analysis
import build
import ffr_maps
from model import BIT, fmt


def complete_with_everything(g, ow, d):
    """Could *some* placement win?  The necessary condition: with every item
    owned, every rewarding location is reachable.  The ship is FFR's here: it
    spawns at whichever ShipLocations dock goes with where it was found, so
    with everything owned it can be boarded at any of them."""
    import overworld
    extra = []
    for sl in d.get("ShipLocations") or []:
        i = sl["X"] | (sl["Y"] << 8)
        if ow.slabel[i] >= 0:
            for b in overworld._neighbours(i):
                if ow.flabel[b] >= 0:
                    extra.append((ow.fnode[ow.flabel[b]], ow.snode[ow.slabel[i]], BIT["SHIP"], "ship spawn"))
    seen = analysis.reach(g, ~0, analysis.adjacency(g, extra))
    return all(any(n in seen for n in l.nodes) for l in g.locations if l.reward)


def run(name, verbose=True):
    tiles, pos, exits, d = ffr_maps.load(name)
    g, ow, maps, missing = build.build(tiles, pos, exits)
    spheres, owned = analysis.playthrough(g)
    win = bool(owned & BIT["CHAOS"])
    complete = complete_with_everything(g, ow, d)
    if verbose:
        print("%s: start %s, ship %s, airship %s, bridge %s, canal %s"
              % (name, pos["start"], pos["ship"], pos["airship"], pos["bridge"], pos["canal"]))
        for i, (seen, new, gained) in enumerate(spheres):
            src = sorted({l.label for l in new if l.reward and BIT.get(l.reward, 0) & gained})
            print("  %2d  %-28s %s" % (i, fmt(gained), ", ".join(src)))
        print("  winnable with the vanilla placement:", win)
        print("  every location reachable with everything owned (FFR's ship):", complete)
    stuck = []
    if not win and verbose:         # the summary only needs the verdict
        # What is still out there, and what each needs beyond what is owned.
        req = analysis.requirements(g)
        for l in g.locations:
            if l.reward and not (owned & BIT.get(l.reward, 0)) and BIT.get(l.reward, 0):
                sets = analysis.location_requirements(l, req)
                short = sorted({fmt(s & ~owned) for s in sets}) or ["unreachable on any items"]
                stuck.append((l.label, l.reward, short))
        if verbose:
            print("  owned at the end:", fmt(owned))
            print("  still out there:")
            for label, reward, short in stuck:
                print("    %-34s %-10s missing: %s" % (label, reward, " | ".join(short)))
    return win, owned, spheres, stuck, complete


def main():
    args = sys.argv[1:]
    if args and args[0] == "--pool":
        tally, blocker, full = Counter(), Counter(), 0
        for name in ffr_maps.pool_names(args[1]):
            win, owned, spheres, stuck, complete = run(name, verbose=False)
            tally[win] += 1
            full += complete
            if not win:
                # the first missing key item in vanilla order is the blocker
                first = next((r for r in ("BRIDGE", "SHIP", "CROWN", "CRYSTAL", "HERB", "KEY",
                                          "TNT", "CANAL", "RUBY", "ROD", "ORB_EARTH", "CANOE",
                                          "FLOATER", "AIRSHIP", "CUBE", "BOTTLE", "OXYALE",
                                          "SLAB", "CHIME", "ADAMANT", "CHAOS")
                              if not owned & BIT[r]), "?")
                blocker[first] += 1
        print("%s: %d winnable with the vanilla placement, %d not; %d with every location"
              " reachable once everything is owned" % (args[1], tally[True], tally[False], full))
        for k, v in blocker.most_common():
            print("  stuck before %-10s %d" % (k, v))
    else:
        for name in args or ["procgen1"]:
            run(name)


if __name__ == "__main__":
    main()
