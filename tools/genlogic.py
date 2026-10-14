#!/usr/bin/env python3
"""
genlogic.py -- the vanilla world's logic, for incentive placement.

    python3 tools/genlogic.py

Reads the world graph that ../worldgraph builds from the built ROM, and writes
what placement needs to know about each of the 256 places an item can be or an
event can happen: the minimal sets of key items and events that reach it (an
antichain of 32-bit masks, model.py's bit order), whether it is one of the 248
places an item can go, and whether it is an incentive spot under Standard or
Wide.  Two outputs, kept in git, so neither the build nor the tests need the
world graph:

    src/logic.inc        the cartridge's constants (place.inc)
    src/logicdata.inc    its tables, chunk CHUNK_LOGIC (logicdata.asm)
    tools/logicdata.py   the same, for randoref.py

The order is the cartridge's location index: the 234 chests before the Black
Orb by chest id, the 13 reward NPCs in rando_talk's table order, the caravan
-- those 248 are the pool -- then the eight events, each granting its bit.
Chaos is not a location; its masks are kept apart, for the last check.

FFR's Early flags each waive one requirement of a few locations, and that is
all they do to the logic: Early King the PRINCESS for the King, Sarda the
VAMPIRE for Sarda, Sage the ORB_EARTH for the Canoe Sage, Ordeals the CROWN
for everything past the Ordeals' thrones.  So the tables hold the masks with
none of them on, and each location the one Early flag that clears one bit of
its masks.  This script proves that reading exact: for every combination of
the four it builds the graph again and checks that clearing the bits gives the
same reachability, mask for mask after minimising.

The ship and the airship are FFR's readings (placement.vehicle_edges): the
ship sails the inner sea once found -- rando_talk moves a found ship to
Coneria's dock, as Free SHIP does, which this checks is that sea -- and the
airship, once raised, flies from anywhere.
"""
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WG = os.path.join(os.path.dirname(ROOT), "worldgraph")
sys.path.insert(0, WG)

import analysis  # noqa: E402
import build  # noqa: E402
import placement  # noqa: E402
import romdata as rd  # noqa: E402
from model import BIT, REQS  # noqa: E402

#  rando_talk's table order (rando.asm, lut_TalkObj).
TALK_ORDER = ["Talk_KingConeria", "Talk_Princess2", "Talk_Bikke", "Talk_ElfPrince", "Talk_Astos",
              "Talk_Matoya", "Talk_Nerrick", "Talk_Smith", "Talk_Sarda", "Talk_CanoeSage",
              "Talk_CubeBot", "Talk_Fairy", "Talk_Chime"]
EVENT_ORDER = ["Talk_Princess1", "Talk_Vampire", "Talk_Unne", "earthorb", "fireorb", "waterorb",
               "airorb", "RaiseAirship"]
EARLY = ["king", "sarda", "sage", "ordeals"]            # RANDO_EARLY's bits 0-3
#  What each Early flag waives: the bit it clears.
EARLY_BIT = {"king": "PRINCESS", "sarda": "VAMPIRE", "sage": "ORB_EARTH", "ordeals": "CROWN"}
KIND_CHEST, KIND_NPC, KIND_SHOP, KIND_EVENT = 0, 1, 2, 3
F_STANDARD, F_WIDE, F_POOL = 0x01, 0x02, 0x04
FREESHIP = (152, 169)        # snesmap.inc's FREESHIP_X/Y: Coneria's dock


def antichains(early):
    g, ow, _, _ = build.build(early=early)
    req = analysis.requirements(g, placement.vehicle_edges(g, ow))
    return g, ow, [analysis.location_requirements(l, req) for l in g.locations]


def order(g):
    """Graph location index for each cartridge location, and Chaos's."""
    locs = g.locations
    chests = sorted((l.ident, k) for k, l in enumerate(locs) if l.kind == "chest")
    one_way = {m for m, n in enumerate(rd.MAP_NAMES) if n.startswith("ToFR")}
    pool_chests = [k for ident, k in chests
                   if not all(g.nodes[n].kind == "sm" and rd.MAP_NAMES.index(g.nodes[n].where) in one_way
                              for n in locs[k].nodes)]
    by_ident = {l.ident: k for k, l in enumerate(locs) if l.kind != "chest"}
    out = pool_chests + [by_ident[r] for r in TALK_ORDER] + [by_ident["Caravan"]]
    assert len(out) == 248, len(out)
    out += [by_ident[e] for e in EVENT_ORDER]
    assert len(out) == 256
    return out, by_ident["Chaos"]


def minimise(masks):
    out = []
    for m in sorted(set(masks), key=lambda m: bin(m).count("1")):
        if not any(o & m == o for o in out):
            out.append(m)
    return sorted(out)


def main():
    g, ow, base = antichains(())
    idx, chaos = order(g)
    locs = g.locations

    #  The found ship's sea is the vanilla ship's: Coneria's dock is on it.
    sx, sy = ow.pos["ship"]
    i = sx | (sy << 8)
    j = FREESHIP[0] | (FREESHIP[1] << 8)
    assert ow.slabel[i] == ow.slabel[j], "Coneria's dock is not on the ship's sea"

    #  Which Early flag touches which location, and that clearing its bit is
    #  the whole of it, alone and in every combination.
    clears = {}
    for e in EARLY:
        _, _, got = antichains((e,))
        bit = BIT[EARLY_BIT[e]]
        for c, k in enumerate(idx + [chaos]):
            if got[k] != base[k]:
                assert c not in clears, ("two Early flags on one location", c)
                clears[c] = e
    for n in range(1, len(EARLY) + 1):
        for combo in itertools.combinations(EARLY, n):
            _, _, got = antichains(combo)
            for c, k in enumerate(idx + [chaos]):
                e = clears.get(c)
                want = sorted(base[k]) if e not in combo else minimise(m & ~BIT[EARLY_BIT[e]] for m in base[k])
                assert sorted(got[k]) == want, ("Early %s at location %d" % (combo, c), got[k], want)

    rows = []
    for c, k in enumerate(idx):
        l = locs[k]
        if l.kind == "chest":
            kind, ident = KIND_CHEST, l.ident
        elif l.kind == "shop":
            kind, ident = KIND_SHOP, 0
        elif c < 248:
            kind, ident = KIND_NPC, TALK_ORDER.index(l.ident)
        else:
            kind, ident = KIND_EVENT, REQS.index(l.reward)
        flags = 0
        if c < 248:
            flags |= F_POOL
            if kind in (KIND_NPC, KIND_SHOP) or ident in placement.STANDARD_CHESTS and kind == KIND_CHEST:
                flags |= F_STANDARD
            if kind in (KIND_NPC, KIND_SHOP) or ident in placement.WIDE_CHESTS and kind == KIND_CHEST:
                flags |= F_WIDE
        early = EARLY.index(clears[c]) + 1 if c in clears else 0
        rows.append((kind, ident, flags, early, sorted(base[k]), l.label))
    chaos_masks = sorted(base[chaos])
    assert chaos not in [k for k in idx] and chaos_early(clears) is None
    assert sum(1 for r in rows if r[2] & F_STANDARD) == 21
    assert sum(1 for r in rows if r[2] & F_WIDE) == 25

    write_py(rows, chaos_masks)
    write_inc(rows, chaos_masks)
    print("%d locations, %d masks, %d Early waivers; Chaos %d masks" % (
        len(rows), sum(len(r[4]) for r in rows), len(clears), len(chaos_masks)))


def chaos_early(clears):
    return clears.get(256)


def write_py(rows, chaos_masks):
    with open(os.path.join(HERE, "logicdata.py"), "w") as f:
        f.write('"""Generated by tools/genlogic.py from ../worldgraph -- do not edit.\n\n'
                'LOCS: (kind, ident, flags, early, masks, label) per cartridge location.\n'
                'kind 0 chest (ident: chest id), 1 reward NPC (rando_talk entry), 2 the\n'
                'caravan, 3 an event (ident: the bit it grants).  flags: 1 Standard spot,\n'
                '2 Wide spot, 4 in the pool.  early: the RANDO_EARLY bit + 1 that clears\n'
                'EARLY_BIT[early] from its masks, or 0.  Masks in model.py\'s bit order.\n"""\n\n')
        f.write("BITS = %r\n" % (REQS,))
        f.write("EARLY_BIT = %r\n" % ([BIT[EARLY_BIT[e]] for e in EARLY],))
        f.write("CHAOS_MASKS = %r\n" % (chaos_masks,))
        f.write("LOCS = [\n")
        for r in rows:
            f.write("    %r,\n" % (r,))
        f.write("]\n")


def write_inc(rows, chaos_masks):
    masks, offs = [], []
    for r in rows:
        offs.append(len(masks))
        masks += r[4]
    offs.append(len(masks))
    lists = [[c for c, r in enumerate(rows) if any(m >> b & 1 for m in r[4])] for b in range(32)]
    boffs, at = [], 0
    for l in lists:
        boffs.append(at)
        at += len(l)
    boffs.append(at)
    head = (";  Generated by tools/genlogic.py from ../worldgraph -- do not edit.\n"
            ";  The vanilla world's logic for incentive placement, location by\n"
            ";  location in the cartridge's order (see genlogic.py's docstring).\n\n")
    with open(os.path.join(ROOT, "src", "logic.inc"), "w") as f:
        f.write(head)
        f.write("LOGIC_LOCS   = %d\n" % len(rows))
        f.write("LOGIC_POOL   = 248\n")
        f.write("LOGIC_MASKS  = %d\n" % len(masks))
        f.write("LOGIC_BYBIT  = %d\n" % at)
        f.write("LOGIC_CHAOSMASKS = %d\n" % len(chaos_masks))
        f.write("LOGIC_STANDARD = $%02X\nLOGIC_WIDE   = $%02X\nLOGIC_INPOOL = $%02X\n" % (F_STANDARD, F_WIDE, F_POOL))
        f.write("LOGIC_NSTANDARD = %d\nLOGIC_NWIDE = %d\n\n" % (
            sum(1 for r in rows if r[2] & F_STANDARD), sum(1 for r in rows if r[2] & F_WIDE)))
        f.write(";  The logic's bits, model.py's order.\n")
        for i, n in enumerate(REQS):
            f.write("LBIT_%-10s = %d\n" % (n, i))
    with open(os.path.join(ROOT, "src", "logicdata.inc"), "w") as f:
        f.write(head)
        f.write(";  Kind and identity: 0 a chest (its id), 1 a reward NPC (rando_talk's\n"
                ";  entry), 2 the caravan, 3 an event (the bit it grants).\n")
        emit(f, "lut_LogicKind", [r[0] for r in rows])
        emit(f, "lut_LogicIdent", [r[1] for r in rows])
        f.write(";  LOGIC_STANDARD, LOGIC_WIDE, LOGIC_INPOOL; and in bits 4-6 the Early flag\n"
                ";  (its RANDO_EARLY bit number + 1) that waives one of its requirements.\n")
        emit(f, "lut_LogicFlags", [r[2] | (r[3] << 4) for r in rows])
        f.write(";  Where each location's masks start in lut_LogicMasks, and where they end.\n")
        emit(f, "lut_LogicMaskLo", [o & 0xFF for o in offs])
        emit(f, "lut_LogicMaskHi", [o >> 8 for o in offs])
        f.write(";  Four bytes each, low first, in model.py's bit order.\n")
        emit(f, "lut_LogicMasks", [b for m in masks for b in m.to_bytes(4, "little")])
        f.write(";  For each bit, the locations whose masks name it, so that gaining a bit\n"
                ";  asks again only of those: where each bit's list starts and ends.\n")
        emit(f, "lut_LogicByBitLo", [o & 0xFF for o in boffs])
        emit(f, "lut_LogicByBitHi", [o >> 8 for o in boffs])
        emit(f, "lut_LogicByBit", [c for l in lists for c in l])
        f.write(";  Chaos: reached when every key item placed, the seed is winnable.\n")
        emit(f, "lut_LogicChaos", [b for m in chaos_masks for b in m.to_bytes(4, "little")])


def emit(f, name, data):
    f.write("%s:\n" % name)
    for i in range(0, len(data), 16):
        f.write("  .BYTE %s\n" % ", ".join("$%02X" % b for b in data[i:i + 16]))
    f.write("\n")


if __name__ == "__main__":
    main()
