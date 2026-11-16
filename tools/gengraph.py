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
from graphtables import lay_out  # noqa: E402,F401  (the cartridge's layout)
import owedits as O  # noqa: E402
import placement  # noqa: E402
import romdata as rd  # noqa: E402
import wiring  # noqa: E402
from model import BIT  # noqa: E402

WIRED = ("entrance ", "teleport ", "exit ")
#  The normal teleports into rooms that FFR's records leave out (LAND_ROOM).
TOFR_IN_ROOM = (1, 51)


def strip(early=(), spec=None):
    """The graph on the vanilla wiring, for every combination of the map
    edits (worldgraph/edited.py), with the wired edges set apart.  Static
    edges and entrance sources carry their conditions, the rest hold
    always.  For another map (spec, map_spec's), its overworld, with no
    edits: every condition always."""
    if spec is None:
        g, ow, maps, _ = build.build(early=early, edits=O.graph_edits(),
                                     pos=O.graph_positions(rd.VANILLA_POS))
        edges = [(s, d, r, g.edge_cond(s, d, r)) for s, d, r, why in g.edges if not why.startswith(WIRED)]
        edges += [(s, d, r, c) for s, d, r, _, c in edited.vehicle_edges(g, ow)]
        ent = [(eid, src, req, ow.ent_cond[(eid, src, req, tile)]) for eid, src, req, tile in ow.entrances]
    else:
        g, ow, maps, _ = build.build(ow_tiles=spec["tiles"], pos=spec["pos"], exits=spec["exits"], early=early)
        edges = [(s, d, r, [edited.ALWAYS]) for s, d, r, why in g.edges if not why.startswith(WIRED)]
        edges += [(s, d, r, [edited.ALWAYS]) for s, d, r, _ in placement.vehicle_edges(g, ow)]
        ent = [(eid, src, req, [edited.ALWAYS]) for eid, src, req, tile in ow.entrances]
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
    global STRIP_MAPS
    STRIP_MAPS = maps                   # Rebellious Princess's spots' regions
    return g, ow, edges, ent, tele, exits, land, exit_to


MAPGRAPH = os.path.join(ROOT, "maps", "graph")


def map_spec(key):
    """Another map of maps/custom-maps.txt, for strip and graph: its tiles,
    its positions and exits for build.build, its docks -- the first a Free
    SHIP's -- and its entrances' coordinates, where an exit Map shuffle
    wires to one sets the party down.  key: "mirror-lr", or FFR's
    POOL-ID, as maps/ vendors it.  With them, a digest of the inputs, so the
    build can tell a graph made from other inputs (genmaps.py)."""
    import base64, gzip, hashlib, json
    import genmaps as GM
    import genows
    m = ft.load()
    if key == "mirror-lr":
        van = genows.vanilla()
        tiles, blocks = GM.mirror_lr(bytes(van))
        pos = {k: GM.mirror_pos(blocks, *xy) for k, xy in rd.VANILLA_POS.items()}
        exits = {x: GM.mirror_pos(blocks, *rd.exit_tele(x)) for x in range(16) if rd.exit_tele(x) != (0, 0)}
        docks = [(name, GM.mirror_pos(blocks, *xy)) for name, xy in G.DOCKS]
        owc = {m.owti[o]: GM.mirror_pos(blocks, *xy) for o, xy in m.ow_coords.items()}
    else:
        f = json.loads(gzip.open(os.path.join(ROOT, "maps", key + ".json.gz")).read())
        tiles = b"".join(base64.b64decode(r) for r in f["DecompressedMapRows"])
        xy = lambda v: (v["X"], v["Y"])
        ships = {sl["TeleporterIndex"]: xy(sl) for sl in f["ShipLocations"]}
        pos = {"start": xy(f["StartingLocation"]), "ship": ships.get(2, ships[255]),
               "airship": xy(f["AirShipLocation"]), "bridge": xy(f["BridgeLocation"]),
               "canal": xy(f["CanalLocation"])}
        exits = {t["Index"]: xy(t["To"]) for t in f["TeleporterFixups"] if t["Type"] == 1}
        #  FFR's docks, each place once, the default (its Free SHIP's) first.
        docks = [("default", ships[255])]
        for o in sorted(k for k in ships if k != 255):
            if ships[o] not in [d for _, d in docks]:
                docks.append(("entrance %d" % o, ships[o]))
        owc = {m.owti[o]: xy(v) for o, v in f["OverworldCoordinates"].items()}
    entry = ("mirror-lr", None, None, "") if key == "mirror-lr" else ("ffr",) + tuple(key.split("-", 1)) + ("",)
    return {"key": key, "tiles": bytes(tiles), "pos": pos, "exits": exits, "docks": docks,
            "ow_coords": owc, "digest": GM.map_digest(entry)}


def check_map(D, spec):
    """Another map's tables against its graph, worked out afresh: on the
    game's wiring, every location's masks and Chaos's the requirement
    fixpoint gives, with and without Early Ordeals (the one Early flag the
    graph holds; the cartridge waives the rest's bits itself), and at each
    of Rebellious Princess's spots her event's."""
    for early, bits in (((), 0), (("ordeals",), 8)):
        g, ow, _, _ = build.build(ow_tiles=spec["tiles"], pos=spec["pos"], exits=spec["exits"], early=early)
        req = analysis.requirements(g, placement.vehicle_edges(g, ow))
        idx, chaos = G.order(g)
        want = [sorted(analysis.location_requirements(g.locations[k], req)) for k in idx + [chaos]]
        got = masks_for(D, D["VANILLA_ENTRANCE"], D["VANILLA_NORMAL"], D["VANILLA_EXIT"], bits)
        bad = [c for c in range(len(want)) if sorted(got[c]) != want[c]]
        assert not bad, ("%s, Early %s: locations %s" % (spec["key"], early, bad[:8]))
    princess = G.EVENT_ORDER.index("Talk_Princess1") + 248
    for s_, nodes in enumerate(D["SARA_NODES"]):
        g, ow, _, _ = build.build(ow_tiles=spec["tiles"], pos=spec["pos"], exits=spec["exits"], sara=s_)
        req = analysis.requirements(g, placement.vehicle_edges(g, ow))
        idx, _ = G.order(g)
        want = sorted(analysis.location_requirements(g.locations[idx[princess]], req))
        moved = dict(D, LOC_NODES=D["LOC_NODES"][:princess] + [nodes] + D["LOC_NODES"][princess + 1:])
        got = masks_for(moved, D["VANILLA_ENTRANCE"], D["VANILLA_NORMAL"], D["VANILLA_EXIT"], 0)[princess]
        assert sorted(got) == want, ("%s, the princess at spot %d" % (spec["key"], s_), got, want)


def alt_main(key):
    """maps/graph/KEY.py: another map's tables, checked against its graph."""
    spec = map_spec(key)
    out, idx = graph(spec)
    check_map(out, spec)
    out["DIGEST"] = spec["digest"]
    os.makedirs(MAPGRAPH, exist_ok=True)
    path = os.path.join(MAPGRAPH, key + ".py")
    with open(path, "w") as f:
        f.write('"""Generated by tools/gengraph.py --map %s from worldgraph/ -- do not edit.\n\n'
                'The map\'s world graph without its wiring, as tools/graphdata.py has\n'
                'the game\'s map\'s.  DIGEST: map_spec\'s, of the inputs."""\n\n' % key)
        for k in sorted(out):
            f.write("%s = %r\n" % (k, out[k]))
    print("%s: checked against its graph -> %s" % (key, os.path.relpath(path, ROOT)))


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


def graph(spec=None):
    """The tables for the game's map (spec None), or another (map_spec's)."""
    g, ow, edges, ent, tele, exits, land, exit_to = strip(spec=spec)
    idx, chaos = G.order(g)
    m = ft.load()

    #  Every coordinate a wiring can name: vanilla's, and every FFR record's.
    landings = {rd.entrance(e) for e in range(32)} | {rd.normal_tele(t) for t in range(64)}
    for o, name in m.enter.items():
        landings.add(rd.entrance(m.owti[o]))
    for t, name in m.tele.items():
        landings.add(rd.normal_tele(m.tidx[t]))
    if spec is None:
        exit_xy = {rd.exit_tele(x) for x in range(16)} | set(m.ow_coords.values())
        #  The Cardia Land Bridge moves six entrances, and FFR moves their
        #  overworld coordinates with them (OverworldMap.ApplyMapEdits): where
        #  an exit wired to one sets the party down, under it.  Read off the
        #  edited map: each entrance tile it moves, where it is with the bridge.
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
        vexit = [rd.exit_tele(x) for x in range(16)]
    else:
        #  Another map: no edits, nothing moved; its exits and its entrances'
        #  coordinates from the map.
        owc = dict(spec["ow_coords"])
        moved = {}
        vexit = [spec["exits"].get(x, rd.exit_tele(x)) for x in range(16)]
        exit_xy = set(vexit) | set(owc.values())

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
    #  Rebellious Princess: where the party talks to the princess at each of
    #  her spots (romdata.PRINCESS_SPOTS), the vanilla first -- her event's
    #  regions when she is there.  On this graph her spots are open floor.
    princess = G.EVENT_ORDER.index("Talk_Princess1") + 248
    sara_nodes = [list(g.locations[idx[princess]].nodes)]
    for _, m_, x_, y_, _ in rd.PRINCESS_SPOTS[1:]:
        sara_nodes.append(STRIP_MAPS[m_].object_nodes(x_, y_))
    for ns in sara_nodes:
        named |= set(ns)
    #  Another map's docks: the regions beside each, kept (the game's are
    #  kept as the regions around them are named).
    dock_nodes = []
    if spec is not None:
        import overworld
        for name, (x, y) in spec["docks"]:
            ns = set()
            for b in overworld._neighbours(x | (y << 8)):
                if ow.flabel[b] >= 0:
                    ns.add(ow.fnode[ow.flabel[b]])
                if ow.rlabel[b] >= 0:
                    ns.add(ow.rnode[ow.rlabel[b]])
            dock_nodes.append(sorted(ns))
            named |= ns
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
    for ns in sara_nodes + dock_nodes:
        for n in ns:
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
    _, _, _, _, tele_eo, _, _, _ = strip(early=("ordeals",), spec=spec)
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
        "SARA_NODES": [[num[n] for n in ns] for ns in sara_nodes],
        "SARA_AT": [[m_, x_, y_, f_] for _, m_, x_, y_, f_ in rd.PRINCESS_SPOTS],
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
    out["VANILLA_EXIT"] = vexit

    #  For per-seed spread groups: which regions are the overworld's.
    out["OW_NODE"] = [g.nodes[n].where == "OW" for n in used]
    #  For per-seed ship docks: each dock's boarding regions, the settings it
    #  is a dock under -- Bridge to Lefein's edits delete Matoya's -- and each
    #  entrance's distance to it, overworld steps on foot and by canoe from
    #  its tiles, or None, and as the airship flies (genlogic.ship_docks's),
    #  on the map: a choice of the nearest, which the masks check.
    from collections import deque as _dq
    import overworld
    boards, dconds = [], []
    if spec is None:
        gv, owv, _, _ = build.build()
        out["DOCKS"] = G.DOCKS
        for name, (x, y) in G.DOCKS:
            i = x | (y << 8)
            cubes = [c for c, t in ow.states(i) if ow.layers["sea"](i, t)]
            nodes = {n for b in overworld._neighbours(i) for n in (ow.F(b), ow.R(b)) if n is not None}
            assert nodes and len(cubes) == 1, name
            boards.append(sorted(num[n] for n in nodes))
            dconds.append(cubes[0])
        assert dconds[4] == (0, 1 << O.BRIDGE_LEFEIN) and set(dconds[:4]) == {edited.ALWAYS}, dconds
        assert 0 in boards[0], "Coneria's dock is not boarded from the start's region"
    else:
        #  The map's docks (map_spec), its first a Free SHIP's; boarded from
        #  the regions beside each on foot or by canoe, every one always.
        owv = ow
        out["DOCKS"] = spec["docks"]
        for (name, (x, y)), nodes in zip(spec["docks"], dock_nodes):
            assert nodes, "%s's dock %s at (%d, %d) is boarded from nowhere" % (spec["key"], name, x, y)
            boards.append(sorted(num[n] for n in nodes))
            dconds.append(edited.ALWAYS)
    out["DOCK_BOARD"] = boards
    out["DOCK_COND"] = dconds
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
        for name, (x, y) in out["DOCKS"]:
            i = x | (y << 8)
            near = [dist[b] for b in overworld._neighbours(i) if b in dist]
            row.append((min(near) if near else None, min(fly(t, i) for t in ts)))
        ent_dock[eid] = row
    out["ENT_DOCK"] = ent_dock
    print("%d regions, %d edges, %d sources (%d entrance, %d teleport, %d exit), %d masks; "
          "%d records; %d landings, %d exit coordinates; %d docks" % (
              out["NODES"], len(out["EDGES"]), len(ent) + len(tele) + len(exits), len(ent), len(tele),
              len(exits), len(masks), len(recs), len(landings), len(exit_xy), len(out["DOCKS"])))
    return out, idx


def main():
    if sys.argv[1:2] == ["--map"]:
        for key in sys.argv[2:]:
            alt_main(key)
        return
    out, idx = graph()
    check(out, idx)
    check_sara(out)
    n = check_edits(out)
    write_py(out)
    print("map edits: the tables agree with the edited maps' graphs in %d combinations" % n)


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
    overworld.py's regions, not edited.py's.  The vehicles as FFR reads them."""
    tiles = O.apply(rd.vanilla_overworld(), flags)
    pos = O.positions(rd.VANILLA_POS, flags)
    g, ow, _, _ = build.build(ow_tiles=tiles, pos=pos, early=early)
    extra = [(g.start, ow.sky, BIT["AIRSHIP"], "air")]
    i = pos["ship"][0] | pos["ship"][1] << 8
    extra.append((g.start, ow.snode[ow.slabel[i]], BIT["SHIP"], "ship"))
    req = analysis.requirements(g, extra)
    idx, chaos = G.order(g)
    return [sorted(analysis.location_requirements(g.locations[k], req)) for k in idx + [chaos]]


#  The settings check_edits tries: none, each alone, every pair, the two
#  the logic first held back in every combination with Bahamut's dock, all,
#  and a fixed sample of the rest.
def edit_combos():
    import random
    n = len(O.SETTINGS)
    out = {0, (1 << n) - 1}
    for a in range(n):
        for b in range(a, n):
            out.add(1 << a | 1 << b)
    held = [O.SARDAS_FOREST, O.CARDIA_BRIDGE, O.BAHAMUT_DOCK]
    for k in range(1 << len(held)):
        out.add(sum(1 << b for j, b in enumerate(held) if k >> j & 1))
    rng = random.Random(14)
    out |= {rng.getrandbits(n) for _ in range(40)}
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


def check_sara(D):
    """At each of Rebellious Princess's spots, her event's regions give the
    masks genlogic found there with the princess moved."""
    import logicdata as L
    princess = G.EVENT_ORDER.index("Talk_Princess1") + 248
    assert D["SARA_NODES"][0] == D["LOC_NODES"][princess]
    #  One region each, so a spot's masks are at most a region's (ES_NODEMAX),
    #  the room the cartridge keeps for them (snesmap.inc's SARA_SPOTMAX).
    assert all(len(ns) == 1 for ns in D["SARA_NODES"]), D["SARA_NODES"]
    for s, nodes in enumerate(D["SARA_NODES"]):
        moved = dict(D, LOC_NODES=D["LOC_NODES"][:princess] + [nodes] + D["LOC_NODES"][princess + 1:])
        got = masks_for(moved, D["VANILLA_ENTRANCE"], D["VANILLA_NORMAL"], D["VANILLA_EXIT"], 0)[princess]
        assert sorted(got) == sorted(L.SARA[s]), ("Sara at spot %d" % s, got, L.SARA[s])


def write_py(out):
    with open(os.path.join(HERE, "graphdata.py"), "w") as f:
        f.write('"""Generated by tools/gengraph.py from worldgraph/ -- do not edit.\n\n'
                'The world graph without its wiring, and FFR\'s entrance shuffle data:\n'
                'see gengraph.py\'s docstring.  Regions are numbered from 0, the start;\n'
                'requirements are indices into MASKS."""\n\n')
        for k in sorted(out):
            f.write("%s = %r\n" % (k, out[k]))


if __name__ == "__main__":
    main()
