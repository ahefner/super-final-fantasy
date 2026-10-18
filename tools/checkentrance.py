#!/usr/bin/env python3
"""
checkentrance.py -- the entrance shuffle's reference against the world graph.

    pypy3 tools/checkentrance.py [seeds]

randoref.es_shuffle is FFR's ShuffleEntrancesAndFloors over graphdata.py's
indices, on the cartridge's PRNG.  worldgraph/wiring.fe_shuffle is the same
shuffle over FFR's own records, held to FFR's ROMs by run_ffr_fe.py.  Given
the same draws they must deal the same wiring, table for table, and this
checks they do, in both modes.  For each wiring it then runs the world
graph's own checks on it (fecheck: nothing strands the party, no two callers
share a landing, every dealt floor warps back), and holds the masks the
reference works out from graphdata.py (randoref.es_masks) to the world
graph's own, built on the wiring.  It needs worldgraph/, which is why it is
not part of test_options.py.
"""
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "worldgraph"))

import randoref as R  # noqa: E402
import graphdata as GD  # noqa: E402
import genlogic as G  # noqa: E402
import analysis  # noqa: E402
import build  # noqa: E402
import fecheck  # noqa: E402
import placement  # noqa: E402
import wiring  # noqa: E402


def proto(seed, mode):
    rng = R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR))
    try:
        w = wiring.fe_shuffle(rng, towns=False, floors=mode == R.ENTRANCES_FLOORS, dead_ends=True,
                              include_coneria=False)
    except RuntimeError:
        return None
    return [w.entrance[e] for e in range(32)], [w.normal[t] for t in range(64)], [w.exits[x] for x in range(16)]


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    t0 = time.time()
    bad = 0
    for mode, name in ((R.ENTRANCES_ONLY, "entrances"), (R.ENTRANCES_FLOORS, "entrances and floors")):
        stats = Counter()
        for seed in range(1, seeds + 1):
            ref = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR)), mode)
            want = proto(seed, mode)
            same = (ref is None and want is None) or (
                ref is not None and want is not None and [list(t) for t in ref[:3]] == [list(t) for t in want])
            if not same:
                print("  %s seed %d: the reference and the prototype differ" % (name, seed))
                bad += 1
                continue
            if ref is None:
                stats["sanity failed"] += 1
                continue
            entrance, normal, exits, roots = ref
            w = wiring.Wiring({e: entrance[e] for e in range(32)}, {t: normal[t] for t in range(64)},
                              {x: exits[x] for x in range(16)})
            van = wiring.Wiring.vanilla()
            w.dealt = {d for t, d in w.normal.items() if d != van.normal[t]} | \
                {d for e, d in w.entrance.items() if d != van.entrance[e]}
            g, ow, *_ = build.build(wiring=w)
            r = fecheck.report(g, w)
            for k in ("strands", "shared landings", "dealt without a warp back", "unreachable locations"):
                if r[k]:
                    print("  %s seed %d: %s: %s" % (name, seed, k, r[k][:3]))
                    bad += 1
            req = analysis.requirements(g, placement.vehicle_edges(g, ow))
            idx, chaos = G.order(g)
            want_masks = [sorted(analysis.location_requirements(g.locations[k], req)) for k in idx + [chaos]]
            got = R.es_masks(entrance, normal, exits, 0)
            if got is None or got[0] + [got[1]] != want_masks:
                print("  %s seed %d: the masks differ" % (name, seed))
                bad += 1
            stats["shuffled"] += 1
            stats["titan opens"] += bool(r["titan opens"])
        print("%-22s %d seeds: %d shuffled, %d failed FFR's sanity check 100 times; Titan's Tunnel "
              "opens new ground in %d" % (name, seeds, stats["shuffled"], stats["sanity failed"],
                                          stats["titan opens"]))
    print("%d problems, %.0fs" % (bad, time.time() - t0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
