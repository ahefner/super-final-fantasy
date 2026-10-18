#!/usr/bin/env python3
"""
genlogic.py -- the vanilla world's logic, for incentive placement.

    python3 tools/genlogic.py

Reads the world graph that worldgraph/ builds from the built ROM, and writes
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
ship sails the inner sea once found, and the airship, once raised, flies from
anywhere.  A found ship is moored at a dock chosen for the map it is found on
(give_vehicle, lut_ShipDock): the nearest the party can reach from there
without it (ship_docks).  This proves that reading holds of every choice --
from every place on the map, in every Early combination, the dock is reached
with what reached the place -- and that every dock is on the inner sea.
"""
import itertools
import os
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WG = os.path.join(ROOT, "worldgraph")
sys.path.insert(0, WG)

import analysis  # noqa: E402
import build  # noqa: E402
import overworld  # noqa: E402
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
#  FFR's docks (Items.cs, Dock): the sea tiles a found ship is moored at.
#  Coneria's first: Free SHIP's, and the dock of a map nothing is found on.
DOCKS = [("Coneria", (152, 169)), ("Pravoka", (210, 153)), ("Elfland", (141, 211)),
         ("Dwarf Cave", (121, 139)), ("Matoya's Cave", (158, 142))]
#  FFR's ShipLocations for the vanilla map (FF1Lib/maps/default.json): the dock
#  a ship found behind each overworld entrance is moored at; any other entrance,
#  Coneria's.  Held against ship_docks' choices wherever a dock can be walked to.
FFR_SHIP_DOCK = {2: 1, 16: 1, 3: 2, 10: 2, 23: 2, 11: 2, 5: 2, 15: 2, 20: 3, 21: 4}


def antichains(early):
    g, ow, _, _ = build.build(early=early)
    req = analysis.requirements(g, placement.vehicle_edges(g, ow))
    return g, ow, [analysis.location_requirements(l, req) for l in g.locations]


def dock_boards(g, ow):
    """For each dock, the overworld regions it is boarded from, on foot or by
    canoe -- and that it is on the inner sea, the one the logic sails."""
    sx, sy = ow.pos["ship"]
    sea = ow.slabel[sx | (sy << 8)]
    out = []
    for name, (x, y) in DOCKS:
        i = x | (y << 8)
        assert ow.slabel[i] == sea, "%s's dock is not on the ship's sea" % name
        nodes = set()
        for b in overworld._neighbours(i):
            if ow.flabel[b] >= 0:
                nodes.add(ow.fnode[ow.flabel[b]])
            if ow.rlabel[b] >= 0:
                nodes.add(ow.rnode[ow.rlabel[b]])
        assert nodes, "%s's dock is boarded from nowhere" % name
        out.append(nodes)
    return out


def reach_from(g, ow, adj, nodes, owned):
    """What is reached from nodes, owning owned, by an adjacency that has the
    way out of a map: build.py keeps the warps back to where the party came
    in as g.returns, apart from g.edges, since from the start they reach
    nothing new.  The airship is FFR's reading, flown from anywhere:
    placement.vehicle_edges has it from the start, which a walk from
    elsewhere need never pass through."""
    seen = set(nodes)
    if owned & BIT["AIRSHIP"]:
        seen.add(ow.sky)
    q = deque(seen)
    while q:
        n = q.popleft()
        for d, r in adj[n]:
            if d not in seen and not (r & ~owned):
                seen.add(d)
                q.append(d)
    return seen


def found_docks(g, ow, idx, masks):
    """For each map, the docks reached from wherever a ship can be found on it
    -- every reachable node of every pool location, with each of its masks
    that does not need the ship -- or None if nothing on it can hold one."""
    adj = analysis.adjacency(g, placement.vehicle_edges(g, ow))
    out = analysis.adjacency(g, list(placement.vehicle_edges(g, ow)) + list(g.returns))
    boards = dock_boards(g, ow)
    everything = analysis.reach(g, ~0, adj)
    ok = [None] * rd.MAP_COUNT
    for c, k in enumerate(idx[:248]):
        l = g.locations[k]
        if l.kind == "shop":                    # the caravan sells no ship
            continue
        #  No reward NPC stands where nothing reaches: the cart removed the
        #  one that did, the Ice Cave's void fairy (mkrom, overlay_strays).  A
        #  chest's sides can be sealed pockets of floor, which nothing does.
        assert l.kind != "npc" or all(n in everything for n in l.nodes), l.label
        for m in masks[k]:
            if m & BIT["SHIP"]:
                continue
            seen = analysis.reach(g, m, adj)
            for n in l.nodes:
                if n not in seen:               # a pocket, or a way in needing more
                    continue
                mp = rd.MAP_NAMES.index(g.nodes[n].where)
                there = reach_from(g, ow, out, [n], m)
                docks = {d for d, b in enumerate(boards) if b & there}
                ok[mp] = docks if ok[mp] is None else ok[mp] & docks
    return ok


def ship_docks(g, ow, idx, masks):
    """The dock a ship found on each map is moored at (user, 2026-10-14): of
    those reached from everywhere on it a ship can be found, the nearest --
    in overworld steps on foot and by canoe from the map's entrances, or,
    where none of them can be walked to, as the airship flies, the only way
    the party can have come.  Returns the dock per map, and the maps where
    that is not FFR's (FFR_SHIP_DOCK)."""
    ok = found_docks(g, ow, idx, masks)
    #  Each map's overworld entrances: the dungeon's, for its deeper floors.
    inside = {}
    for s, d, r, _ in g.edges:
        if g.nodes[s].where != "OW" and g.nodes[d].where != "OW":
            inside.setdefault(s, set()).add(d)
    ents = [set() for _ in range(rd.MAP_COUNT)]
    for src, land, m, what in g.entries:
        if what[0] != "entrance":
            continue
        seen, q = set(land), deque(land)
        while q:
            n = q.popleft()
            ents[rd.MAP_NAMES.index(g.nodes[n].where)].add(what[1])
            for d in inside.get(n, ()):
                if d not in seen:
                    seen.add(d)
                    q.append(d)
    tiles = {}
    for eid, src, req, tile in ow.entrances:
        tiles.setdefault(eid, []).append(tile)

    def walk(starts):
        dist, q = {t: 0 for t in starts}, deque(starts)
        while q:
            i = q.popleft()
            for b in overworld._neighbours(i):
                if b not in dist and (ow.flabel[b] >= 0 or ow.rlabel[b] >= 0):
                    dist[b] = dist[i] + 1
                    q.append(b)
        return dist

    def fly(a, b):
        dx, dy = abs((a & 255) - (b & 255)), abs((a >> 8) - (b >> 8))
        return min(dx, 256 - dx) + min(dy, 256 - dy)

    out, unlike = [], []
    for mp in range(rd.MAP_COUNT):
        if ok[mp] is None:
            out.append(0)
            continue
        assert ok[mp], "%s: no dock is reached from everywhere a ship can be found" % rd.MAP_NAMES[mp]
        starts = [t for e in sorted(ents[mp]) for t in tiles[e]]
        dist = walk(starts)
        steps = {}
        for d in ok[mp]:
            x, y = DOCKS[d][1]
            near = [dist[b] for b in overworld._neighbours(x | (y << 8)) if b in dist]
            if near:
                steps[d] = min(near)
        if steps:
            dock = min(steps, key=lambda d: (steps[d], d))
            ffr = {FFR_SHIP_DOCK.get(e, 0) for e in ents[mp]}
            assert ffr == {dock}, ("%s: walks to %s, FFR has %s" % (rd.MAP_NAMES[mp], DOCKS[dock][0], ffr))
        else:
            dock = min(ok[mp], key=lambda d: (min(fly(t, DOCKS[d][1][0] | (DOCKS[d][1][1] << 8))
                                                  for t in starts), d))
            if {FFR_SHIP_DOCK.get(e, 0) for e in ents[mp]} != {dock}:
                unlike.append(mp)
        out.append(dock)
    return out, unlike


def spread_groups(g, idx, masks):
    """FFR's spread placement's "near" (SanityCheckerV2.GetNearRewardSources):
    the chests of one dungeon -- reached from the same overworld entrances, a
    chest's own nodes' rather than its map's, so Cardia's islands are apart --
    behind the same requirements.  A number per pool chest, $FF for the
    rest.  No two incentive chests share one, under Standard or Wide, so
    FFR's spreading of incentives is nothing here and only loose items are
    spread (randoref._forward)."""
    inside = {}
    for s, d, r, _ in g.edges:
        if g.nodes[s].where != "OW" and g.nodes[d].where != "OW":
            inside.setdefault(s, set()).add(d)
    node_ents = {}
    for src, land, m, what in g.entries:
        if what[0] != "entrance":
            continue
        seen, q = set(land), deque(land)
        while q:
            n = q.popleft()
            node_ents.setdefault(n, set()).add(what[1])
            for d in inside.get(n, ()):
                if d not in seen:
                    seen.add(d)
                    q.append(d)
    keys, out = {}, []
    for c, k in enumerate(idx[:248]):
        l = g.locations[k]
        if l.kind != "chest":
            out.append(0xFF)
            continue
        dungeon = frozenset().union(*(node_ents.get(n, set()) for n in l.nodes))
        assert dungeon, l.label
        out.append(keys.setdefault((dungeon, tuple(sorted(masks[k]))), len(keys)))
    assert len(keys) < 0xFF
    return out


def check_docks(g, ow, idx, masks, docks):
    """Every map's dock is one reached from everywhere a ship can be found on
    it: what genlogic proves of each Early combination."""
    ok = found_docks(g, ow, idx, masks)
    for mp, d in enumerate(docks):
        assert ok[mp] is None or d in ok[mp], (rd.MAP_NAMES[mp], DOCKS[d][0], ok[mp])


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

    #  Where a found ship is moored, map by map, and that each is reached
    #  from where it was found.  Free SHIP's dock is the first.
    assert DOCKS[0][1] == FREESHIP
    docks, unlike = ship_docks(g, ow, idx, base)
    check_docks(g, ow, idx, base, docks)

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
            eg, eow, got = antichains(combo)
            check_docks(eg, eow, idx, got, docks)
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
    #  What each gives in the vanilla game, as a logic bit, for the
    #  unwinnable warning's sweep under Key items Vanilla (rando_winnable).
    global VANBIT
    VANBIT = [REQS.index(locs[k].reward) + 1 if locs[k].reward in BIT else 0 for k in idx]
    chaos_masks = sorted(base[chaos])
    assert chaos not in [k for k in idx] and chaos_early(clears) is None
    assert sum(1 for r in rows if r[2] & F_STANDARD) == 21
    assert sum(1 for r in rows if r[2] & F_WIDE) == 25

    groups = spread_groups(g, idx, base)
    for spot in (F_STANDARD, F_WIDE):
        inc = [groups[c] for c, r in enumerate(rows[:248]) if r[2] & spot and groups[c] != 0xFF]
        assert len(inc) == len(set(inc)), "two incentive chests in one spread group"
    write_py(rows, chaos_masks, docks, groups)
    write_inc(rows, chaos_masks, docks, groups)
    print("%d locations, %d masks, %d Early waivers; Chaos %d masks" % (
        len(rows), sum(len(r[4]) for r in rows), len(clears), len(chaos_masks)))
    for mp, d in enumerate(docks):
        if d or mp in unlike:
            print("  ship found in %-16s -> %s%s" % (rd.MAP_NAMES[mp], DOCKS[d][0],
                                                     "  (FFR: Coneria)" if mp in unlike else ""))


def chaos_early(clears):
    return clears.get(256)


def write_py(rows, chaos_masks, docks, groups):
    with open(os.path.join(HERE, "logicdata.py"), "w") as f:
        f.write('"""Generated by tools/genlogic.py from worldgraph/ -- do not edit.\n\n'
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
        f.write("#  The docks a found ship is moored at, and each map's.\n")
        f.write("DOCKS = %r\n" % (DOCKS,))
        f.write("SHIP_DOCK = %r\n" % (docks,))
        f.write("#  Each pool place's spread group: one dungeon, one set of requirements;\n"
                "#  $FF for a place that is not a chest.\n")
        f.write("SPREAD = %r\n" % (groups,))
        f.write("#  What each gives in the vanilla game: its logic bit + 1, or 0.\n")
        f.write("VANBIT = %r\n" % (VANBIT,))


def write_inc(rows, chaos_masks, docks, groups):
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
    head = (";  Generated by tools/genlogic.py from worldgraph/ -- do not edit.\n"
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
        f.write("LOGIC_DOCKS  = %d\n" % len(DOCKS))
        f.write("LOGIC_NOGROUP = $FF\n\n")
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
        f.write(";  What each gives in the vanilla game: its logic bit + 1, or 0 (the\n"
                ";  unwinnable warning's sweep under Key items Vanilla).\n")
        emit(f, "lut_LogicVanBit", VANBIT)
        f.write(";  Chaos: reached when every key item placed, the seed is winnable.\n")
        emit(f, "lut_LogicChaos", [b for m in chaos_masks for b in m.to_bytes(4, "little")])
        f.write(";  The docks a found ship is moored at (FFR's), as the sea tile it sits on.\n")
        #  ...and a sixth, Gaia's drydock, where Ship in Drydock moors every
        #  ship (DOCK_DRYDOCK): no map's choice, so not in DOCKS.
        import owedits
        emit(f, "lut_DockX", [xy[0] for _, xy in DOCKS] + [owedits.DRYDOCK_XY[0]])
        emit(f, "lut_DockY", [xy[1] for _, xy in DOCKS] + [owedits.DRYDOCK_XY[1]])
        f.write(";  Each pool place's spread group (pl_forward): the chests of one dungeon\n"
                ";  behind one set of requirements; LOGIC_NOGROUP for an NPC or the caravan.\n")
        emit(f, "lut_LogicGroup", groups)
        f.write(";  Each map's: the dock a ship found on it is moored at (give_vehicle).\n")
        f.write("lut_ShipDock:\n")
        for mp, d in enumerate(docks):
            f.write("  .BYTE %d   ; %s%s\n" % (d, rd.MAP_NAMES[mp], ": " + DOCKS[d][0] if d else ""))
        f.write("\n")


def emit(f, name, data):
    f.write("%s:\n" % name)
    for i in range(0, len(data), 16):
        f.write("  .BYTE %s\n" % ", ".join("$%02X" % b for b in data[i:i + 16]))
    f.write("\n")


if __name__ == "__main__":
    main()
