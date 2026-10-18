#!/usr/bin/env python3
"""
gengraph.py -- the world graph without its wiring, for entrance shuffle.

    python3 tools/gengraph.py

genlogic.py distils the vanilla world into each location's requirement masks.
Under entrance shuffle the masks depend on the seed, so the cartridge works
them out itself at New Game, from a graph whose teleports are left open: this
writes that graph, and what FFR's ShuffleEntrancesAndFloors needs to wire it.

    tools/graphdata.py   for randoref.py
    src/graph.inc        the same for the cartridge: constants, and the tables
                         declared .global, for logicdata.asm and entrance.inc
    src/graphdata.inc    the tables themselves, in the logic chunk

The graph is worldgraph/'s, built on the vanilla wiring and then stripped
of every edge an entrance, a normal teleport or an exit makes.  What is left:

  - the static edges -- inside maps, over the overworld, and FFR's two vehicle
    readings (placement.vehicle_edges) -- each with its requirement;
  - every source of a wired edge: an entrance tile's region, a teleport's or
    an exit's, with its requirement (two of the Castle of Ordeals' teleport
    sources need the CROWN only without Early Ordeals);
  - the regions a party set down at each coordinate a wiring can name stands
    in -- landings for entrances and teleports, overworld regions for exits;
  - each location's regions and requirement, in the cartridge's order
    (genlogic.order).

A seed's wiring adds, for each source, an edge to the regions its id now
leads to; the requirement fixpoint over that graph gives each location's
masks.  This checks, for the vanilla wiring and every Early combination, that
it gives genlogic.py's own masks, mask for mask.

Only regions that something can touch are kept -- an edge's end, a source, a
landing, a location's -- 210 of the graph's 654, so a region fits in a byte.
FFR's records and lists are its own (ffr_teleports, read from its source).
"""
import itertools
import os
import sys
from collections import defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WG = os.path.join(ROOT, "worldgraph")
sys.path.insert(0, WG)
sys.path.insert(0, HERE)

import analysis  # noqa: E402
import build  # noqa: E402
import edited  # noqa: E402
import ffr_teleports as ft  # noqa: E402
import genlogic as G  # noqa: E402
import owedits as O  # noqa: E402
import placement  # noqa: E402
import romdata as rd  # noqa: E402
import wiring  # noqa: E402
from model import BIT  # noqa: E402

WIRED = ("entrance ", "teleport ", "exit ")
#  The normal teleports into rooms that FFR's records leave out (LAND_ROOM).
TOFR_IN_ROOM = (1, 51)


def strip(early=()):
    """The graph on the vanilla wiring, for every combination of the map
    edits (worldgraph/edited.py), with the wired edges set apart.  Static
    edges and entrance sources carry their conditions, the rest hold
    always."""
    g, ow, maps, _ = build.build(early=early, edits=O.graph_edits(),
                                 pos=O.graph_positions(rd.VANILLA_POS))
    edges = [(s, d, r, g.edge_cond(s, d, r)) for s, d, r, why in g.edges if not why.startswith(WIRED)]
    edges += [(s, d, r, c) for s, d, r, _, c in edited.vehicle_edges(g, ow)]
    ent = [(eid, src, req, ow.ent_cond[(eid, src, req, tile)]) for eid, src, req, tile in ow.entrances]
    tele, exits = [], []
    for sm in maps:
        for src, req, kind, tid, _ in sm.pending:
            (tele if kind == rd.TP_TELE_NORM else exits).append((tid, src, req))
    #  Where an exit puts the party: build.exit_nodes.
    at_entrance = {}
    for eid, src, req, tile in ow.entrances:
        if not req:
            at_entrance.setdefault((tile & 255, tile >> 8), set()).add(src)

    def exit_to(x, y):
        nodes = sorted(at_entrance.get((x, y), ())) or [ow.node_at(x, y)]
        return [n for n in nodes if n is not None]

    def land(m, x, y):
        return maps[m].node_at(x, y)
    return g, ow, edges, ent, tele, exits, land, exit_to


def fixpoint(start, edges):
    """Minimal requirement masks per region: analysis.requirements's relaxation."""
    adj = defaultdict(list)
    for s, d, r in edges:
        adj[s].append((d, r))
    req = defaultdict(list)
    req[start] = [0]
    q, queued = deque([start]), {start}
    while q:
        n = q.popleft()
        queued.discard(n)
        for d, r in adj[n]:
            merged = analysis._minimise(req[d] + [s | r for s in req[n]])
            if merged != req[d]:
                req[d] = merged
                if d not in queued:
                    queued.add(d)
                    q.append(d)
    return req


def main():
    g, ow, edges, ent, tele, exits, land, exit_to = strip()
    idx, chaos = G.order(g)
    m = ft.load()

    #  Every coordinate a wiring can name: vanilla's, and every FFR record's.
    landings = {rd.entrance(e) for e in range(32)} | {rd.normal_tele(t) for t in range(64)}
    for o, name in m.enter.items():
        landings.add(rd.entrance(m.owti[o]))
    for t, name in m.tele.items():
        landings.add(rd.normal_tele(m.tidx[t]))
    exit_xy = {rd.exit_tele(x) for x in range(16)} | set(m.ow_coords.values())

    #  The Cardia Land Bridge moves six entrances, and FFR moves their
    #  overworld coordinates with them (OverworldMap.ApplyMapEdits): where an
    #  exit wired to one sets the party down, under it.  Read off the edited
    #  map: each entrance tile it moves, where it is with the bridge.
    cb = 1 << O.CARDIA_BRIDGE
    where = defaultdict(dict)
    for i in ow.edited:
        for c, t in ow.states(i):
            if rd.ow_prop(t)[1] & 0x80:
                where[rd.ow_prop(t)[1] & 0x3F][c] = (i & 255, i >> 8)
    owc = {m.owti[o]: xy for o, xy in m.ow_coords.items()}
    moved = {e: v[(cb, 0)] for e, v in where.items() if (cb, 0) in v}
    assert len(moved) == 6 and all(where[e][(0, cb)] == owc[e] for e in moved), (moved, where)
    exit_xy |= set(moved.values())

    #  Only regions that can matter.  The edits leave the overworld in many
    #  more pieces than vanilla's, mostly slivers that lead nowhere: a region
    #  stays if something names it -- a location, a source, where a wiring
    #  can set a party down, the start -- or it lies between where a party
    #  can be and something named, by any edge under any settings.  Dropping
    #  the rest changes no location's masks, which check_edits proves.
    named = {g.start}
    for lst in (ent, tele, exits):
        for _, s, *_ in lst:
            named.add(s)
    roots = {g.start}
    for c in landings:
        roots |= set(land(*c))
    for c in exit_xy:
        roots |= set(exit_to(*c))
    named |= roots
    for k in idx + [chaos]:
        named |= set(g.locations[k].nodes)
    fwd, back = defaultdict(set), defaultdict(set)
    for s, d, _, _ in edges:
        fwd[s].add(d)
        back[d].add(s)

    def closure(start, adj):
        seen, todo = set(start), list(start)
        while todo:
            n = todo.pop()
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    todo.append(m)
        return seen
    matter = (closure(roots, fwd) & closure(named, back)) | named
    edges = [e for e in edges if e[0] in matter and e[1] in matter]

    #  The regions anything touches, renumbered from 0 with the start first.
    used = [g.start]
    seen = {g.start}

    def keep(n):
        if n not in seen:
            seen.add(n)
            used.append(n)
    for s, d, r, _ in edges:
        keep(s)
        keep(d)
    for lst in (ent, tele, exits):
        for _, s, *_ in lst:
            keep(s)
    for c in sorted(landings):
        for n in land(*c):
            keep(n)
    for c in sorted(exit_xy):
        for n in exit_to(*c):
            keep(n)
    for k in idx + [chaos]:
        for n in g.locations[k].nodes:
            keep(n)
    assert len(used) < 256, len(used)
    num = {n: i for i, n in enumerate(used)}

    #  Requirements: a handful of distinct masks, by index, each with the
    #  cube of map edit settings it holds under -- an edge or a source with
    #  a condition of several cubes is one entry for each.
    masks = [(0, edited.ALWAYS)]

    def mi(r, cube=edited.ALWAYS):
        if (r, cube) not in masks:
            masks.append((r, cube))
        return masks.index((r, cube))

    def each(cubes):
        return edited.simplify(cubes)
    #  Early Ordeals's two sources, found as the difference it makes.
    _, _, _, _, tele_eo, _, _, _ = strip(early=("ordeals",))
    assert [(t, s) for t, s, _ in tele] == [(t, s) for t, s, _ in tele_eo]
    ordeals = [r != r2 for (_, _, r), (_, _, r2) in zip(tele, tele_eo)]
    assert sum(ordeals) == 2 and all(r2 == 0 for (_, _, r2), o in zip(tele_eo, ordeals) if o)

    out = {
        "NODES": len(used),
        "LABELS": [g.nodes[n].label for n in used],
        "EDGES": [(num[s], num[d], mi(r, c)) for s, d, r, cs in edges for c in each(cs)],
        "ENT_SRC": [(e, num[s], mi(r, c)) for e, s, r, cs in ent for c in each(cs)],
        "TELE_SRC": [(t, num[s], mi(r), o) for (t, s, r), o in zip(tele, ordeals)],
        "EXIT_SRC": [(x, num[s], mi(r)) for x, s, r in exits],
        "LAND": {c: [num[n] for n in land(*c)] for c in sorted(landings)},
        "EXIT_TO": {c: [num[n] for n in exit_to(*c)] for c in sorted(exit_xy)},
        "LOC_NODES": [[num[n] for n in g.locations[k].nodes] for k in idx],
        "LOC_REQ": [mi(g.locations[k].req) for k in idx],
        "CHAOS_NODES": [num[n] for n in g.locations[chaos].nodes],
        "CHAOS_REQ": mi(g.locations[chaos].req),
    }
    out["MASKS"] = [m for m, _ in masks]
    out["CONDS"] = [c for _, c in masks]

    #  FFR's side: records, mappings, lists, coordinates, the sanity sets.
    recs = sorted(m.records)
    rnum = {n: i for i, n in enumerate(recs)}
    out["RECORDS"] = [(n, m.records[n].location,
                       [m.tidx[t] for t in m.records[n].teleports],
                       m.xidx[m.records[n].exit] if m.records[n].exit else None) for n in recs]
    out["ENTER"] = {m.owti[o]: rnum[n] for o, n in m.enter.items()}
    out["TELE"] = {m.tidx[t]: rnum[n] for t, n in m.tele.items()}
    #  Where each record lands, as the ROM has its index land (FFR's LoadData).
    landed = {}
    for o, n in m.enter.items():
        landed[rnum[n]] = rd.entrance(m.owti[o])
    for t, n in m.tele.items():
        landed[rnum[n]] = rd.normal_tele(m.tidx[t])
    out["LANDED"] = landed
    #  FFR's StandardInRoom destinations: a party set down at one of these is
    #  inside a room, and FFR's teleport code sets inroom from the landing
    #  (StatsTracking.cs, the routine at $0F:9200) rather than carrying it
    #  over from wherever the party left -- which only ever agreed with the
    #  landing while the wiring was vanilla.  Its records leave out two, the
    #  Temple of Fiends Revisited's, which are never shuffled and so never a
    #  record: the Black Orb's teleport onto 1F, and the one into 2F's small
    #  room (TeleportIndex TempleOfFiends2 and TempleOfFiends6).  Setting
    #  inroom from the landing must know them all the same, or the party is
    #  set down on 1F's room mask after the Orb (user, 2026-10-17).  FFR's
    #  MetroidVaniaMap.cs, which rewires every teleport, names all nine in its
    #  inroomTeleporter; and a flood from each of the game's 96 landings, to
    #  the doors before any door's way out, finds the same nine.
    tofr = {rd.normal_tele(t) for t in TOFR_IN_ROOM}
    out["LAND_ROOM"] = sorted({(r.map, r.x, r.y) for r in m.records.values() if r.inroom} | tofr)
    out["LISTS"] = {
        "towns": [m.owti[o] for o in m.lists["towns"]],
        "top": [m.owti[o] for o in m.lists["top"]],
        "free_ow": [m.owti[o] for o in m.lists["free_ow"]],
        "free_sm": [m.tidx[t] for t in m.lists["free_sm"]],
        "icecave_loop": [m.tidx[t] for t in m.lists["icecave_loop"]],
        "vanilla_ow": [m.owti[o] for o in m.lists["vanilla_ow"]],
        "vanilla_sm": [m.tidx[t] for t in m.lists["vanilla_sm"]],
    }
    #  FFR's keepers with the FLOATER removed (EntrancesFloorsShuffle.cs).
    out["NOFLOATER_KEEP"] = {"titan": [m.owti["TitansTunnelWest"]],
                             "cardia": [m.owti[n] for n in ("Cardia2", "Cardia4", "Cardia5", "Cardia6")],
                             "cardia_dock": [m.owti[n] for n in ("Cardia1", "BahamutCave1")]}
    out["UNUSED1"] = m.owti["Unused1"]
    out["SEASHRINE1"] = m.tidx["SeaShrine1"]
    out["OW_COORDS"] = owc
    out["OW_COORDS_CARDIA"] = {e: moved.get(e, xy) for e, xy in owc.items()}
    out["STARTER"] = sorted(wiring.STARTER_DESTINATIONS)
    out["SAFE"] = sorted(wiring.SAFE_LOCATIONS)
    out["CONNECTED"] = sorted(m.owti[o] for o in wiring.CONNECTED)
    out["STARTING"] = sorted(m.owti[o] for o in wiring.STARTING)
    out["DANGER"] = [m.owti[o] for o in ("Coneria", "ConeriaCastle1", "TempleOfFiends1", "DwarfCave",
                                         "MatoyasCave", "Pravoka")]
    out["VANILLA_ENTRANCE"] = [rd.entrance(e) for e in range(32)]
    out["VANILLA_NORMAL"] = [rd.normal_tele(t) for t in range(64)]
    out["VANILLA_EXIT"] = [rd.exit_tele(x) for x in range(16)]

    #  For per-seed spread groups: which regions are the overworld's.
    out["OW_NODE"] = [g.nodes[n].where == "OW" for n in used]
    #  For per-seed ship docks: each dock's boarding regions, the settings it
    #  is a dock under -- Bridge to Lefein's edits delete Matoya's -- and each
    #  entrance's distance to it, overworld steps on foot and by canoe from
    #  its tiles, or None, and as the airship flies (genlogic.ship_docks's),
    #  on the vanilla map: a choice of the nearest, which the masks check.
    #  Under Ship in Drydock there is one dock, Gaia's, and no choice.
    from collections import deque as _dq
    import overworld
    gv, owv, _, _ = build.build()
    out["DOCKS"] = G.DOCKS
    boards, dconds = [], []
    for name, (x, y) in G.DOCKS:
        i = x | (y << 8)
        cubes = [c for c, t in ow.states(i) if ow.layers["sea"](i, t)]
        nodes = {n for b in overworld._neighbours(i) for n in (ow.F(b), ow.R(b)) if n is not None}
        assert nodes and len(cubes) == 1, name
        boards.append(sorted(num[n] for n in nodes))
        dconds.append(cubes[0])
    assert dconds[4] == (0, 1 << O.BRIDGE_LEFEIN) and set(dconds[:4]) == {edited.ALWAYS}, dconds
    out["DOCK_BOARD"] = boards
    out["DOCK_COND"] = dconds
    assert 0 in out["DOCK_BOARD"][0], "Coneria's dock is not boarded from the start's region"
    tiles = {}
    for eid, src, req, tile in owv.entrances:
        tiles.setdefault(eid, []).append(tile)
    ow = owv

    def walk(starts):
        dist, q = {t: 0 for t in starts}, _dq(starts)
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
    ent_dock = {}
    for eid, ts in sorted(tiles.items()):
        dist = walk(ts)
        row = []
        for name, (x, y) in G.DOCKS:
            i = x | (y << 8)
            near = [dist[b] for b in overworld._neighbours(i) if b in dist]
            row.append((min(near) if near else None, min(fly(t, i) for t in ts)))
        ent_dock[eid] = row
    out["ENT_DOCK"] = ent_dock

    check(out, idx)
    n = check_edits(out)
    write_py(out)
    write_inc(out)
    print("map edits: the tables agree with the edited maps' graphs in %d combinations" % n)
    print("%d regions, %d edges, %d sources (%d entrance, %d teleport, %d exit), %d masks; "
          "%d records; %d landings, %d exit coordinates" % (
              out["NODES"], len(out["EDGES"]), len(ent) + len(tele) + len(exits), len(ent), len(tele),
              len(exits), len(masks), len(recs), len(landings), len(exit_xy)))


def masks_for(D, entrance, normal, exits, early, flags=0):
    """Each location's masks on a wiring, under the map edit settings `flags`
    -- the reference's own reading of the data written here, which check()
    holds to genlogic and check_edits to the edited maps' own graphs.  An
    edge or a source is there when its requirement's cube holds."""
    M, C = D["MASKS"], D["CONDS"]
    ok = lambda r: edited.holds(C[r], flags)
    edges = [(s, d, M[r]) for s, d, r in D["EDGES"] if ok(r)]
    for e, s, r in D["ENT_SRC"]:
        if ok(r):
            edges += [(s, d, M[r]) for d in D["LAND"][entrance[e]]]
    for t, s, r, o in D["TELE_SRC"]:
        rr = 0 if (o and early >> 3 & 1) else M[r]
        edges += [(s, d, rr) for d in D["LAND"][normal[t]]]
    for x, s, r in D["EXIT_SRC"]:
        edges += [(s, d, M[r]) for d in D["EXIT_TO"][exits[x]]]
    req = fixpoint(0, edges)
    out = []
    for nodes, r in zip(D["LOC_NODES"] + [D["CHAOS_NODES"]], D["LOC_REQ"] + [D["CHAOS_REQ"]]):
        out.append(sorted(analysis._minimise([s | M[r] for n in nodes for s in req[n]])))
    return out


def truth(flags, early=()):
    """Each location's masks, in the cartridge's order, Chaos last, on the
    map the edits `flags` make, as worldgraph builds that map on its own --
    overworld.py's regions, not edited.py's.  The vehicles as FFR reads them,
    but for Ship in Drydock: the ship is boarded only at the drydock."""
    tiles = O.apply(rd.vanilla_overworld(), flags)
    pos = O.positions(rd.VANILLA_POS, flags)
    g, ow, _, _ = build.build(ow_tiles=tiles, pos=pos, early=early)
    extra = [(g.start, ow.sky, BIT["AIRSHIP"], "air")]
    if not flags >> O.SHIP_DRYDOCK & 1:
        i = pos["ship"][0] | pos["ship"][1] << 8
        extra.append((g.start, ow.snode[ow.slabel[i]], BIT["SHIP"], "ship"))
    req = analysis.requirements(g, extra)
    idx, chaos = G.order(g)
    return [sorted(analysis.location_requirements(g.locations[k], req)) for k in idx + [chaos]]


#  The settings check_edits tries: none, each alone, every pair, the three
#  the logic first held back in every combination with Bahamut's dock, all,
#  and a fixed sample of the rest.
def edit_combos():
    import random
    out = {0, (1 << 14) - 1}
    for a in range(14):
        for b in range(a, 14):
            out.add(1 << a | 1 << b)
    held = [O.SARDAS_FOREST, O.CARDIA_BRIDGE, O.SHIP_DRYDOCK, O.BAHAMUT_DOCK]
    for k in range(16):
        out.add(sum(1 << b for j, b in enumerate(held) if k >> j & 1))
    rng = random.Random(14)
    out |= {rng.getrandbits(14) for _ in range(40)}
    return sorted(out)


def check_edits(D):
    """The tables, under every combination edit_combos tries and the vanilla
    wiring, give each location the masks the edited map's own graph does."""
    for flags in edit_combos():
        got = masks_for(D, D["VANILLA_ENTRANCE"], D["VANILLA_NORMAL"], D["VANILLA_EXIT"], 0, flags)
        want = truth(flags)
        bad = [c for c in range(len(want)) if sorted(got[c]) != want[c]]
        assert not bad, ("edits $%04X, location %d" % (flags, bad[0]), got[bad[0]], want[bad[0]])
    return len(edit_combos())


def check(D, idx):
    """The vanilla wiring gives genlogic's masks, in every Early combination."""
    import logicdata as L
    for k in range(16):
        names = tuple(e for b, e in enumerate(G.EARLY) if k >> b & 1)
        got = masks_for(D, D["VANILLA_ENTRANCE"], D["VANILLA_NORMAL"], D["VANILLA_EXIT"], k)
        for c, (kind, ident, flags, e, ms, label) in enumerate(L.LOCS):
            #  genlogic's waiver: one bit off the location's masks.  Here the
            #  King's, Sarda's and the Sage's are the same, and Ordeals's is
            #  in the graph already, its two thrones' sources.
            clear = L.EARLY_BIT[e - 1] if e and k >> (e - 1) & 1 else 0
            want = analysis._minimise([mm & ~clear for mm in ms])
            npc = clear if e != 4 else 0
            mine = analysis._minimise([mm & ~npc for mm in got[c]])
            assert sorted(want) == sorted(mine), ("Early %s, location %d %s" % (names, c, label), mine, want)


def write_py(out):
    with open(os.path.join(HERE, "graphdata.py"), "w") as f:
        f.write('"""Generated by tools/gengraph.py from worldgraph/ -- do not edit.\n\n'
                'The world graph without its wiring, and FFR\'s entrance shuffle data:\n'
                'see gengraph.py\'s docstring.  Regions are numbered from 0, the start;\n'
                'requirements are indices into MASKS."""\n\n')
        for k in sorted(out):
            f.write("%s = %r\n" % (k, out[k]))


def write_inc(D):
    """The cartridge's copy.  Lists are CSR: an offset table one longer than
    the list it indexes (words), then the entries.  Coordinates are by index:
    a landing (map, x, y) or an exit's overworld (x, y)."""
    lands = sorted(D["LAND"])
    lidx = {c: i for i, c in enumerate(lands)}
    exits = sorted(D["EXIT_TO"])
    xidx = {c: i for i, c in enumerate(exits)}
    N = D["NODES"]
    head = [";  Generated by tools/gengraph.py from worldgraph/ -- do not edit.",
            ";  The world graph without its wiring, and FFR's entrance shuffle data;",
            ";  see gengraph.py.  Regions number from 0, the start.", ""]
    lines = list(head)
    consts = list(head)
    names = []

    def const(name, v):
        consts.append("%-16s = %d" % (name, v))

    def table(name, data, word=False):
        names.append(name)
        lines.append("%s:" % name)
        step = 8 if word else 16
        for i in range(0, len(data), step):
            chunk = data[i:i + step]
            if word:
                lines.append("  .WORD %s" % ", ".join("$%04X" % (v & 0xFFFF) for v in chunk))
            else:
                lines.append("  .BYTE %s" % ", ".join("$%02X" % (v & 0xFF) for v in chunk))
        if not data:
            lines.append("  ; (empty)")
        lines.append("")

    def csr(prefix, lists):
        off, flat = [0], []
        for l in lists:
            flat += l
            off.append(len(flat))
        table(prefix + "Off", off, word=True)
        return flat

    const("GR_NODES", N)
    const("GR_MASKS", len(D["MASKS"]))
    const("GR_LANDINGS", len(lands))
    const("GR_EXITXY", len(exits))
    const("GR_LOCS", len(D["LOC_NODES"]) + 1)          # Chaos last
    const("GR_DOCKS", len(D["DOCKS"]))
    lines.append("")
    lines.append(";  The requirement masks, four bytes each, low first.")
    table("lut_GrMask", [b for m in D["MASKS"] for b in m.to_bytes(4, "little")])
    lines.append(";  The map edit settings each holds under: every RANDO_OWEDITS bit of")
    lines.append(";  the first set, none of the second (worldgraph/edited.py's cubes).")
    table("lut_GrCondOn", [on for on, _ in D["CONDS"]], word=True)
    table("lut_GrCondOff", [off for _, off in D["CONDS"]], word=True)
    by_src = [[] for _ in range(N)]
    for s_, d_, r in D["EDGES"]:
        by_src[s_].append((d_, r))
    lines.append(";  Static edges by source: destination, requirement.")
    flat = csr("lut_GrEdge", [[d_ for d_, _ in l] for l in by_src])
    table("lut_GrEdgeDst", flat)
    table("lut_GrEdgeReq", [r for l in by_src for _, r in l])
    src = [[] for _ in range(N)]
    for e, n, r in D["ENT_SRC"]:
        src[n].append((0, e, r))
    for t, n, r, o in D["TELE_SRC"]:
        src[n].append((1 | (0x80 if o else 0), t, r))
    for x, n, r in D["EXIT_SRC"]:
        src[n].append((2, x, r))
    lines.append(";  Wired sources by region: kind (0 entrance, 1 teleport, 2 exit; $80 the")
    lines.append(";  CROWN waived by Early Ordeals), its id, its requirement.")
    csr("lut_GrSrc", [[k for k, _, _ in l] for l in src])
    table("lut_GrSrcKind", [k for l in src for k, _, _ in l])
    table("lut_GrSrcId", [i for l in src for _, i, _ in l])
    table("lut_GrSrcReq", [r for l in src for _, _, r in l])
    lines.append(";  Landings: where each lands, as the game's tables hold it, and its regions.")
    table("lut_GrLandX", [c[1] for c in lands])
    table("lut_GrLandY", [c[2] for c in lands])
    table("lut_GrLandMap", [c[0] for c in lands])
    room = set(D["LAND_ROOM"])
    assert room <= set(lands), "an in-room destination no wiring lands on: %s" % sorted(room - set(lands))
    lines.append(";  $80 for a landing inside a room (FFR's StandardInRoom), as bit 7 of its x.")
    table("lut_GrLandRoom", [0x80 if c in room else 0 for c in lands])
    table("lut_GrLandNodes", csr("lut_GrLand", [D["LAND"][c] for c in lands]))
    lines.append(";  Exit coordinates: where on the overworld, and its regions there.")
    table("lut_GrExitX", [c[0] for c in exits])
    table("lut_GrExitY", [c[1] for c in exits])
    table("lut_GrExitNodes", csr("lut_GrExit", [D["EXIT_TO"][c] for c in exits]))
    lines.append(";  The cartridge's locations, then Chaos: their regions and requirement.")
    table("lut_GrLocNodes", csr("lut_GrLoc", D["LOC_NODES"] + [D["CHAOS_NODES"]]))
    table("lut_GrLocReq", D["LOC_REQ"] + [D["CHAOS_REQ"]])
    ents = sorted({e for e, _, _ in D["ENT_SRC"]})
    const("GR_ENTIDS", len(ents))
    lines.append(";  The entrances the overworld has, in order (es_roots).")
    table("lut_GrEntIds", ents)
    lines.append(";  1 for a region of the overworld.")
    table("lut_GrOwNode", [1 if o else 0 for o in D["OW_NODE"]])
    lines.append(";  The docks: their boarding regions; each entrance's distance to each,")
    lines.append(";  walking ($FFFF none) and flying, entrance * GR_DOCKS + dock.")
    table("lut_GrDockNodes", csr("lut_GrDock", D["DOCK_BOARD"]))
    lines.append(";  The settings each is a dock under (Bridge to Lefein deletes Matoya's).")
    table("lut_GrDockCondOn", [on for on, _ in D["DOCK_COND"]], word=True)
    table("lut_GrDockCondOff", [off for _, off in D["DOCK_COND"]], word=True)
    walk, fly = [], []
    for e in range(32):
        row = D["ENT_DOCK"].get(e, [(None, 0x7FFF)] * len(D["DOCKS"]))
        walk += [0xFFFF if w is None else w for w, _ in row]
        fly += [f for _, f in row]
    table("lut_GrEntWalk", walk, word=True)
    table("lut_GrEntFly", fly, word=True)

    #  FFR's shuffle.
    recs = D["RECORDS"]
    locs = sorted({r[1] for r in recs})
    lnum = {l: i for i, l in enumerate(locs)}
    landed = D["LANDED"]
    lines.append(";  FFR's shuffle: records, by index -- location id, landing, exit ($FF")
    lines.append(";  none), the teleports out of it; and flags (1: Lefein or Melmond, which")
    lines.append(";  never come first).")
    const("ES_RECORDS", len(recs))
    const("ES_LOCATIONS", len(locs))
    const("ES_UNUSED1", D["UNUSED1"])
    nk = D["NOFLOATER_KEEP"]
    assert len(nk["titan"]) == 1 and len(nk["cardia"]) == 4 and len(nk["cardia_dock"]) == 2
    const("ES_KEEP_TITAN", nk["titan"][0])
    const("ES_SEASHRINE1", D["SEASHRINE1"])
    const("ES_LOC_TITANEAST", lnum["TitansTunnelEast"])
    const("ES_LOC_TITANWEST", lnum["TitansTunnelWest"])
    lines.append("")
    table("lut_EsRecLoc", [lnum[r[1]] for r in recs])
    table("lut_EsRecLand", [lidx[landed[i]] if i in landed else 0xFF for i in range(len(recs))])
    table("lut_EsRecExit", [0xFF if r[3] is None else r[3] for r in recs])
    table("lut_EsRecFlags", [1 if r[0] in ("Lefein", "Melmond") else 0 for r in recs])
    table("lut_EsRecTeles", csr("lut_EsRecTele", [r[2] for r in recs]))
    table("lut_EsEnter", [D["ENTER"].get(e, 0xFF) for e in range(32)])
    table("lut_EsTele", [D["TELE"].get(t, 0xFF) for t in range(64)])
    for name in ("towns", "top", "free_ow", "free_sm", "icecave_loop", "vanilla_ow", "vanilla_sm"):
        lab = "lut_Es" + "".join(w.capitalize() for w in name.split("_"))
        const("ES_" + name.upper() + "_N", len(D["LISTS"][name]))
        table(lab, D["LISTS"][name])
    table("lut_EsOwCoord", [xidx[D["OW_COORDS"][e]] if e in D["OW_COORDS"] else 0xFF for e in range(32)])
    lines.append(";  ...and under the Cardia Land Bridge, which moves six of them.")
    lines.append(";  FFR's keepers with the FLOATER removed: Cardia's four, then the first and")
    lines.append(";  Bahamut's (ES_KEEP_TITAN apart).")
    table("lut_EsKeepCardia", nk["cardia"] + nk["cardia_dock"])
    table("lut_EsOwCoordCardia", [xidx[D["OW_COORDS_CARDIA"][e]] if e in D["OW_COORDS_CARDIA"] else 0xFF
                                  for e in range(32)])
    #  The sanity check's sets: locations as a bitset over location ids,
    #  entrances as a 32-bit mask.
    def bits(ids, n):
        v = 0
        for i in ids:
            v |= 1 << i
        return list(v.to_bytes(n, "little"))
    nb = (len(locs) + 7) // 8
    table("lut_EsStarter", bits([lnum[l] for l in D["STARTER"] if l in lnum], nb))
    table("lut_EsSafe", bits([lnum[l] for l in D["SAFE"] if l in lnum], nb))
    table("lut_EsConnected", bits(D["CONNECTED"], 4))
    table("lut_EsStarting", bits(D["STARTING"], 4))
    table("lut_EsDanger", D["DANGER"])
    lines.append(";  The vanilla wiring, as landings and exit coordinates.")
    table("lut_EsVanEnt", [lidx[c] for c in D["VANILLA_ENTRANCE"]])
    table("lut_EsVanNorm", [lidx[c] for c in D["VANILLA_NORMAL"]])
    table("lut_EsVanExit", [xidx[c] for c in D["VANILLA_EXIT"]])
    with open(os.path.join(ROOT, "src", "graphdata.inc"), "w") as f:
        f.write("\n".join(lines) + "\n")
    consts.append("")
    for i in range(0, len(names), 4):
        consts.append(".global %s" % ", ".join(names[i:i + 4]))
    with open(os.path.join(ROOT, "src", "graph.inc"), "w") as f:
        f.write("\n".join(consts) + "\n")


if __name__ == "__main__":
    main()
