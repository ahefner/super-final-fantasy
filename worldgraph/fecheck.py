"""
fecheck.py -- what a wiring has to satisfy beyond "the goal is reachable",
checked on a built graph (randomization-notes.md §9.3).

  stranded(g, owned)     regions reachable with `owned` from which the party
                         cannot get back to the start with the same items --
                         a soft-lock, unless the region is one-way by design
                         (the Temple of Fiends' past).  Uses g.returns, the
                         warp-back edges: assumed fill's premise, that a
                         region once reached stays reachable, is this.
  shared_landings(w)     landings more than one teleport or entrance leads to
  dealt_without_warp(g, w)  dealt floors with no warp back to their caller
  nesting(g)             for each node, the fewest DoStandardMap levels it can
                         be reached at: the stack depth of the shallowest
                         route there
  report(g, w)           all of the above, plus winnable with the vanilla item
                         placement and every location reachable at all
"""
from collections import defaultdict, deque

import analysis
import romdata as rd
from model import BIT

ONE_WAY_MAPS = {m for m, name in enumerate(rd.MAP_NAMES) if name.startswith("ToFR")}


def _back_adjacency(g):
    radj = defaultdict(list)
    for s, d, r, _ in list(g.edges) + list(g.returns):
        radj[d].append((s, r))
    return radj


def stranded(g, owned, radj=None, adj=None):
    radj = radj or _back_adjacency(g)
    there = analysis.reach(g, owned, adj)
    back, q = {g.start}, deque([g.start])
    while q:
        n = q.popleft()
        for s, r in radj[n]:
            if s not in back and not (r & ~owned):
                back.add(s)
                q.append(s)
    out = []
    for n in sorted(there - back):
        node = g.nodes[n]
        if node.kind == "sm" and rd.MAP_NAMES.index(node.where) in ONE_WAY_MAPS:
            continue
        out.append(n)
    return out


def shared_landings(w):
    by = defaultdict(list)
    for e, dest in w.entrance.items():
        if dest[0] < rd.MAP_COUNT and e < 30:
            by[dest].append(("entrance", e))
    used = set()
    for m in range(rd.MAP_COUNT):
        tiles = rd.standard_map(m)
        ts = rd.TILESET_OF_MAP[m]
        for t in set(tiles):
            p0, p1 = rd.sm_prop(ts, t)
            if p0 & rd.TP_TELE_MASK == rd.TP_TELE_NORM:
                used.add(p1 & 0x3F)
    for t in sorted(used):
        by[w.normal[t]].append(("teleport", t))
    return {d: who for d, who in by.items() if len(who) > 1}


def dealt_without_warp(g, w):
    """Dealt floors (normal teleports the shuffle moved) whose landing has no
    warp back to the caller anywhere in reach inside the map.  The shuffle's
    rule is that a dealt destination's way back is the stack; FFR's records
    are all of that kind -- floors land on their up-staircase, and towns,
    castles and caves dealt as floors have walk-off borders."""
    out = []
    for t, dest in sorted(w.normal.items()):
        if dest != rd.normal_tele(t) and dest in getattr(w, "dealt", ()):
            if not g.warp_back.get(("teleport", t)):
                out.append((t, rd.MAP_NAMES[dest[0]], dest[1:]))
    return out


def nesting(g):
    """Fewest DoStandardMap levels per node: 0 on the overworld, +1 through
    an entrance or a normal teleport, unchanged inside a map, back to 0
    through an exit.  0-1 BFS over every edge, requirements ignored."""
    level = {g.start: 0}
    q = deque([g.start])
    kinds = {}
    for s, land, m, what in g.entries:
        for d in land:
            kinds[(s, d)] = 1
    adj = defaultdict(list)
    for s, d, r, why in g.edges:
        step = 1 if (s, d) in kinds else 0
        if why.startswith("exit"):
            step = None
        adj[s].append((d, step))
    while q:
        n = q.popleft()
        for d, step in adj[n]:
            lv = 0 if step is None else level[n] + step
            if d not in level or lv < level[d]:
                level[d] = lv
                if step == 0:
                    q.appendleft(d)
                else:
                    q.append(d)
    return level


TITAN = rd.MAP_NAMES.index("TitansTunnel")


def titan_opens(g):
    """Overworld regions holding an entrance or a location that the party can
    reach without the airship only through Titan's Tunnel.  The preference
    (user, 2026-10-11) is that the tunnel open new ground, not just shorten
    a walk -- preferred, not required."""
    owned = ~BIT["AIRSHIP"]
    full = analysis.reach(g, owned)
    tunnel = {n.id for n in g.nodes if n.kind == "sm" and n.where == rd.MAP_NAMES[TITAN]}
    adj = defaultdict(list)
    for s, d, r, _ in g.edges:
        if s not in tunnel and d not in tunnel:
            adj[s].append((d, r))
    without = analysis.reach(g, owned, adj)
    worth = {n for l in g.locations for n in l.nodes} | {src for src, land, m, what in g.entries}
    return sorted(n for n in full - without
                  if g.nodes[n].kind.startswith("ow") and n in worth)


def report(g, w=None, owned_all=None):
    adj = analysis.adjacency(g)
    radj = _back_adjacency(g)
    spheres, owned = analysis.playthrough(g)
    win = bool(owned & BIT["CHAOS"])
    strands = []
    have = 0
    for seen, new, gained in spheres:
        s = stranded(g, have, radj, adj)
        if s:
            strands.append((bin(have).count("1"), s))
        have |= gained
    everything = owned_all if owned_all is not None else ~0
    reach_all = analysis.reach(g, everything, adj)
    unreachable = [l for l in g.locations if not any(n in reach_all for n in l.nodes)]
    lv = nesting(g)
    deepest = max((v for n, v in lv.items() if g.nodes[n].kind == "sm"), default=0)
    out = {"winnable": win, "spheres": len(spheres), "strands": strands,
           "unreachable locations": [l.label for l in unreachable],
           "deepest level": deepest, "titan opens": titan_opens(g)}
    if w is not None:
        out["shared landings"] = shared_landings(w)
        out["dealt without a warp back"] = dealt_without_warp(g, w)
    return out
