"""
analysis.py -- questions asked of a world graph.

  reach()          which nodes a party owning `owned` can get to.  This is the
                   one primitive the cart's placer needs.
  playthrough()    collect everything reachable, repeat until stuck: the
                   "spheres" of a seed.  Winnable iff CHAOS is collected.
  requirements()   for every node, the minimal sets of items that reach it.
                   This is what the static tables FFR keeps by hand say, so it
                   is what gets compared with them.
  prune()          the part of the graph a cart would actually carry.
"""
from collections import defaultdict, deque

from model import BIT


def adjacency(g, extra=()):
    adj = defaultdict(list)
    for s, d, r, _ in list(g.edges) + list(extra):
        adj[s].append((d, r))
    return adj


def reach(g, owned, adj=None):
    adj = adj or adjacency(g)
    seen = {g.start}
    q = deque([g.start])
    while q:
        n = q.popleft()
        for d, r in adj[n]:
            if d not in seen and not (r & ~owned):
                seen.add(d)
                q.append(d)
    return seen


def reward_bit(loc):
    return BIT.get(loc.reward, 0) if loc.reward else 0


def playthrough(g, start_owned=0):
    adj = adjacency(g)
    owned, spheres, taken = start_owned, [], set()
    while True:
        seen = reach(g, owned, adj)
        new = [loc for loc in g.locations
               if id(loc) not in taken and any(n in seen for n in loc.nodes)
               and not (loc.req & ~owned)]
        if not new:
            break
        for loc in new:
            taken.add(id(loc))
        gained = 0
        for loc in new:
            gained |= reward_bit(loc)
        spheres.append((seen, new, gained & ~owned))
        owned |= gained
    return spheres, owned


def _minimise(sets):
    out = []
    for s in sorted(set(sets), key=lambda m: bin(m).count("1")):
        if not any((t & s) == t for t in out):
            out.append(s)
    return out


def requirements(g, extra=()):
    """Antichain of minimal requirement masks per node, by relaxation."""
    adj = adjacency(g, extra)
    req = defaultdict(list)
    req[g.start] = [0]
    q = deque([g.start])
    queued = {g.start}
    while q:
        n = q.popleft()
        queued.discard(n)
        for d, r in adj[n]:
            cand = [s | r for s in req[n]]
            merged = _minimise(req[d] + cand)
            if merged != req[d]:
                req[d] = merged
                if d not in queued:
                    queued.add(d)
                    q.append(d)
    return req


def location_requirements(loc, req):
    return _minimise([s | loc.req for n in loc.nodes for s in req.get(n, [])])


def prune(g):
    """Nodes that matter: reachable from the start with everything owned, and
    able to lead somewhere that holds a location.  The rest -- islands nobody
    lands on, slivers of river -- would not be in a cart's tables."""
    adj = adjacency(g)
    radj = defaultdict(list)
    for s, d, r, _ in g.edges:
        radj[d].append(s)
    fwd = reach(g, ~0, adj)
    useful = set()
    q = deque(n for loc in g.locations for n in loc.nodes)
    useful.update(q)
    while q:
        n = q.popleft()
        for s in radj[n]:
            if s not in useful:
                useful.add(s)
                q.append(s)
    keep = fwd & useful
    edges = [e for e in g.edges if e[0] in keep and e[1] in keep]
    return keep, edges
