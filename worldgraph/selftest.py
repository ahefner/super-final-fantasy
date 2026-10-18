#!/usr/bin/env python3
"""
selftest.py -- the checks in run_vanilla.py, plus proof that they bite.

A comparison that passes against a broken model is decoration.  Each mutation
below breaks one rule the graph is built from; the FFR comparison must notice
every one, and the vanilla playthrough must still be winnable unmutated.

    python3 selftest.py       # exits non-zero on any failure
"""
import sys

import analysis
import ffr_oracle as fo
import romdata as rd
import standard
from model import BIT


def differences():
    import build
    g, ow, maps, missing = build.build()
    chests, owr, floors = fo.load()
    others = fo.load_others()
    si = ow.pos["ship"][0] | (ow.pos["ship"][1] << 8)
    extra = [(g.start, ow.sky, BIT["AIRSHIP"], ""),
             (g.start, ow.snode[ow.slabel[si]], BIT["SHIP"], "")]
    req = analysis.requirements(g, extra)
    mine = {(l.kind, l.ident): l for l in g.locations}
    targets = [(c["maploc"], mine[("chest", cid)].nodes)
               for cid, c in chests.items() if not c["unused"]]
    targets += [(ml, mine[k].nodes) for k, (_, ml) in others.items()]
    bad = sum(1 for ml, nodes in targets
              if sorted(analysis._minimise(fo.maploc_requirements(ml, owr, floors))) !=
              sorted(analysis._minimise([s for n in nodes for s in req.get(n, [])])))
    _, owned = analysis.playthrough(g)
    return bad, bool(owned & BIT["CHAOS"]), missing


def main():
    failures = []

    bad, win, missing = differences()
    print("unmutated: %d differ, winnable %s" % (bad, win))
    if bad or not win or missing:
        failures.append("unmutated graph disagrees with FFR or is not winnable")

    def mutation(label, apply, undo):
        apply()
        try:
            bad, _, _ = differences()
        finally:
            undo()
        print("%-30s %d differ" % (label, bad))
        if not bad:
            failures.append("mutation not caught: " + label)

    saved = dict(standard.GATE_TILE)
    mutation("locked doors need no KEY",
             lambda: standard.GATE_TILE.pop("locked"),
             lambda: standard.GATE_TILE.update(saved))
    mutation("the Titan needs no RUBY",
             lambda: (standard.GATE_ROUTINE.pop("Talk_Titan"),
                      standard.YIELDING_ROUTINE.add("Talk_Titan")),
             lambda: (standard.GATE_ROUTINE.update({"Talk_Titan": BIT["RUBY"]}),
                      standard.YIELDING_ROUTINE.discard("Talk_Titan")))
    pos = dict(rd.VANILLA_POS)
    mutation("the canal never blocks",
             lambda: rd.VANILLA_POS.update(canal=(0, 0)),
             lambda: rd.VANILLA_POS.update(pos))
    mutation("the crown tile needs no CROWN",
             lambda: standard.GATE_TILE.pop("crown"),
             lambda: standard.GATE_TILE.update(saved))

    bad, win, _ = differences()
    if bad or not win:
        failures.append("state not restored after mutations")
    for f in failures:
        print("FAIL:", f)
    print("ok" if not failures else "%d failure(s)" % len(failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
