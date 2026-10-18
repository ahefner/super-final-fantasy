"""
run_incentives.py -- the cart's incentive rows through placement.py.

    pypy3 run_incentives.py [seeds] [--efs [FFR rom]] [--only NAME]

Each configuration is a setting of the rows randomization-notes.md §12
settles (placement.setup): Key items Standard or Wide, the eleven Free rows
(Incentive / Loose / Free), Other items, the incentive gear, and FFR's four
Early flags.  For every seed it places, then plays the seed through from the
free items, and reports how often placement succeeds, on which try, whether
the result is winnable, how many incentive items the spots could not hold,
and the playthrough's spheres.

On the vanilla world by default.  --efs shuffles entrances and floors with
FFR's Entrance and Floor Shuffle preset's own settings (towns left alone);
given one of FFR's ROMs of that preset, it also takes FFR's overworld, whose
Open Progression edits the vanilla one lacks.
"""
import random
import sys
import time
from collections import Counter

import analysis
import build
import ffr_rom
import placement
import wiring
from model import BIT

EARLY = ("king", "sarda", "sage", "ordeals")
VEHICLES_FREE = {"SHIP": "free", "AIRSHIP": "free", "BRIDGE": "free", "CANAL": "free", "CANOE": "free"}
LOOSE_ALL = dict.fromkeys(placement.FREE_ROWS, "loose") | {"BRIDGE": "free"}

#  name: (spots, rows, other, gear, early)
CONFIGS = {
    #  FFR's Beginner and default presets: 19 key items and two gear, 21 spots.
    "beginner":        ("standard", {"BRIDGE": "free"}, "incentive", ["MASAMUNE", "RIBBON"], EARLY),
    "beginner-late":   ("standard", {"BRIDGE": "free"}, "incentive", ["MASAMUNE", "RIBBON"], ()),
    "bridge-placed":   ("standard", {}, "incentive", ["MASAMUNE", "RIBBON"], EARLY),
    #  Chaos Rush: vehicles, LUTE and TAIL free, its eight gear pieces.
    "chaos-rush":      ("standard", VEHICLES_FREE | {"LUTE": "free", "TAIL": "free"}, "incentive",
                        ["MASAMUNE", "KATANA", "VORPAL", "DEFENSE", "OPAL", "POWERGAUNTLET",
                         "WHITESHIRT", "RIBBON"], EARLY),
    #  Free Enterprise, less the three pieces the cart leaves out.
    "free-enterprise": ("wide", VEHICLES_FREE | {"TAIL": "free"}, "incentive",
                        ["KATANA", "VORPAL", "DEFENSE", "OPAL", "POWERGAUNTLET", "WHITESHIRT",
                         "RIBBON", "XCALBER"], EARLY),
    #  Oops All Loose, near enough: no incentives at all.
    "all-loose":       ("standard", LOOSE_ALL, "loose", [], EARLY),
    #  Overflow: 20 key items and all nine gear into 21 spots.
    "everything":      ("standard", {}, "incentive", placement.GEAR, EARLY),
    "everything-late": ("standard", {}, "incentive", placement.GEAR, ()),
    #  Underflow: 20 key items, no gear, 25 spots.
    "wide-bare":       ("wide", {}, "incentive", [], EARLY),
    #  Half and half: vehicles loose, the rest in spots.
    "vehicles-loose":  ("standard", {"SHIP": "loose", "AIRSHIP": "loose", "CANAL": "loose",
                                     "CANOE": "loose", "BRIDGE": "loose"}, "incentive",
                        ["MASAMUNE", "RIBBON"], EARLY),
}


def run(name, seeds, efs, ffr_ow):
    spots, rows, other, gear, early = CONFIGS[name]
    stats, tries, spheres, over = Counter(), Counter(), Counter(), Counter()
    for seed in range(1, seeds + 1):
        w = wiring.fe_shuffle(seed, towns=False, include_coneria=False, dead_ends=True) if efs else None
        g, ow, maps, missing = build.build(ow_tiles=ffr_ow, wiring=w, early=early)
        free, items, inc, locs = placement.setup(g, spots, rows, other, gear)
        p = placement.Placer(g, ow, inc, locs, free, items)
        over[max(0, len(inc) - len(p.incentive_locs))] += 1
        placed, attempt = p.place(random.Random(seed))
        if placed is None:
            continue
        tries[attempt] += 1
        placement.apply(g, ow, p, placed)
        sph, owned = analysis.playthrough(g, free)
        stats["winnable"] += bool(owned & BIT["CHAOS"])
        spheres[len(sph)] += 1
        #  Where the incentive items went: a spot unless the spots overflowed.
        stats["incentive item off a spot"] += sum(
            1 for k, it in placed.items() if it in inc and k not in p.incentive_locs)
        stats["loose item on a spot"] += sum(
            1 for k, it in placed.items() if it not in inc and k in p.incentive_locs)
    n = sum(tries.values())
    print("%-16s %s, %2d items (%2d incentive) -> %d spots%s" % (
        name, spots, len(items), len(inc), len(p.incentive_locs),
        "" if early else ", no Early flags"))
    print("  placed %d / %d   tries %s   winnable %d   overflow %s" % (
        n, seeds, dict(sorted(tries.items())), stats["winnable"], dict(over)))
    print("  incentive items off a spot %d, loose items on a spot %d   spheres %s" % (
        stats["incentive item off a spot"], stats["loose item on a spot"],
        ", ".join("%d: %d" % kv for kv in sorted(spheres.items()))))
    return n


def main():
    argv = sys.argv[1:]
    only = argv.pop(argv.index("--only") + 1) if "--only" in argv else None
    args = [a for a in argv if not a.startswith("--")]
    seeds = int(args[0]) if args else 100
    efs = "--efs" in sys.argv
    rom = args[1] if efs and len(args) > 1 else None
    ffr_ow = ffr_rom.overworld(rom) if rom else None
    names = [only] if only else list(CONFIGS)
    t0 = time.time()
    print("%d seeds, %s" % (seeds, ("entrance and floor shuffle (FFR's preset settings)%s" % (
        ", FFR's overworld" if rom else "")) if efs else "vanilla world"))
    for name in names:
        run(name, seeds, efs, ffr_ow)
    print("%.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
