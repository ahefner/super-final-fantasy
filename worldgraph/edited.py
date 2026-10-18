"""
edited.py -- the overworld for every combination of the map edits at once.

overworld.Overworld makes the regions of one map.  FFR's fourteen map edits
make 16,384 maps, too many to build one by one, and the cart's logic needs
one graph that is right for each.  This makes it: the regions and edges of
the vanilla overworld where no edit writes, and for the tiles the edits do
write, regions and edges that hold only under the settings that make them.

**Conditions.**  A condition is a list of cubes, any of which holding makes
it hold; a cube `(on, off)` is a pair of masks of edit settings, holding for
the settings F when F has every bit of `on` and none of `off`.  ALWAYS,
`(0, 0)`, holds for all.  An edge carries one (model.Graph.cond).

**Tiles.**  Each list comes with the cubes under which it applies, and is
applied in FFR's order (owedits.graph_edits), so a tile the edits write holds
one value or another as the settings fall: its states, a partition of the
settings into cubes, each with the tile it holds then.  Only the Cardia group
writes a tile twice; every other edited tile has two states, its list on and
off.

**Regions.**  A region in a layer -- on foot, by canoe, by ship, as
overworld.py has them -- is a connected set of tiles that the layer can enter
under exactly the same settings: so whenever one of its tiles can be entered,
all of them can, and they are joined.  Tiles no edit writes, and edited tiles
the layer can enter under every setting, are always enterable and make the
vanilla-like regions; an edited tile enterable only under some makes regions
with that condition.  Two regions of a layer side by side are joined under
the conjunction of their conditions.  Every other rule -- boarding, docks,
the bridge and canal, landing the airship, entrances -- is overworld.py's,
taken for each pair of neighbouring tiles under each pair of their states,
and holds under the conjunction of those states' cubes.

So the graph under any one combination of settings, its edges filtered by
their conditions (model.Graph.under), is the graph overworld.py makes of that
map, but for how its regions are cut: tools/gengraph.py proves the masks
equal, location for location, over every combination of the settings that
matter.

Positions move too (owedits.graph_positions): the BRIDGE under Bridge to
Lefein, the ship's start under Ship in Drydock.  Neither the start, the
airship, the canal, the floater, the caravan nor any special tile is written
by an edit, which is asserted.
"""
from collections import defaultdict

import romdata as rd
from model import BIT
from overworld import W, H, _neighbours

ALWAYS = (0, 0)


def holds(cube, flags):
    on, off = cube
    return flags & on == on and not flags & off


def conj(a, b):
    on, off = a[0] | b[0], a[1] | b[1]
    return None if on & off else (on, off)


def conj_all(*cubes):
    c = ALWAYS
    for x in cubes:
        c = conj(c, x)
        if c is None:
            return None
    return c


def _merge(a, b):
    """X with a bit, and X without it: X."""
    d_on, d_off = a[0] ^ b[0], a[1] ^ b[1]
    if d_on and d_on == d_off and d_on & (d_on - 1) == 0:
        if a[0] & ~d_on == b[0] & ~d_on and a[1] & ~d_off == b[1] & ~d_off:
            return (a[0] & ~d_on, a[1] & ~d_off)
    return None


def _covers(o, c):
    return not (o[0] & ~c[0]) and not (o[1] & ~c[1])


def simplify(cubes):
    """A condition's prime implicants: the same settings, in fewest-literal
    cubes, none covering another."""
    cs = set(cubes)
    while True:
        new = set(cs)
        for a in cs:
            for b in cs:
                m = _merge(a, b)
                if m is not None:
                    new.add(m)
        if new == cs:
            break
        cs = new
    return sorted(c for c in cs if not any(o != c and _covers(o, c) for o in cs))


def fn_key(cubes):
    """A condition's function, canonically: the bits it depends on and its
    truth table over them -- so two conditions with the same key hold under
    the same settings."""
    bits = 0
    for on, off in cubes:
        bits |= on | off
    bl = [b for b in range(16) if bits >> b & 1]

    def table(bl):
        out = []
        for k in range(1 << len(bl)):
            f = sum(1 << b for j, b in enumerate(bl) if k >> j & 1)
            out.append(any(holds(c, f) for c in cubes))
        return tuple(out)
    tt = table(bl)
    for b in list(bl):
        j = bl.index(b)
        if all(tt[k] == tt[k ^ (1 << j)] for k in range(len(tt))):
            bl.remove(b)
            tt = table(bl)
    return tuple(bl), tt


def implies(a, b):
    """Every setting condition a holds under, b holds under too."""
    bits = 0
    for on, off in a + b:
        bits |= on | off
    bl = [x for x in range(16) if bits >> x & 1]
    for k in range(1 << len(bl)):
        f = sum(1 << x for j, x in enumerate(bl) if k >> j & 1)
        if any(holds(c, f) for c in a) and not any(holds(c, f) for c in b):
            return False
    return True


def key_cubes(key):
    bl, tt = key
    ms = []
    for k, v in enumerate(tt):
        if v:
            on = sum(1 << b for j, b in enumerate(bl) if k >> j & 1)
            ms.append((on, sum(1 << b for b in bl) & ~on))
    return simplify(ms)


ALWAYS_KEY = fn_key([ALWAYS])


def tile_states(tiles, edits):
    """{tile index: [(cube, tile)]} for every tile an edit writes: the tile
    it holds under each cube, the cubes partitioning the settings."""
    writers = defaultdict(list)
    for cubes, writes in edits:
        if cubes:
            for x, y, t in writes:
                writers[x | y << 8].append((cubes, t))
    states = {}
    for i, ws in writers.items():
        bits = 0
        for cubes, _ in ws:
            for on, off in cubes:
                bits |= on | off
        bl = [b for b in range(16) if bits >> b & 1]
        by_val = defaultdict(list)
        for k in range(1 << len(bl)):
            f = sum(1 << b for j, b in enumerate(bl) if k >> j & 1)
            v = tiles[i]
            for cubes, t in ws:
                if any(holds(c, f) for c in cubes):
                    v = t
            by_val[v].append((f, bits & ~f))
        states[i] = [(c, v) for v, ms in sorted(by_val.items()) for c in simplify(ms)]
    return states


class EditedOverworld:
    """overworld.Overworld's interface, for every combination of the edits:
    `edits` is owedits.graph_edits(), `pos` owedits.graph_positions().  The
    graph `g` must be conditional (model.Graph(conditional=True)); entrances
    carry theirs in `ent_cond`."""

    def __init__(self, g, tiles, pos, entrance_names, edits):
        self.g, self.tiles = g, tiles
        idx = lambda p: p[0] | (p[1] << 8)
        st = tile_states(tiles, edits)
        self.states = lambda i: st.get(i, [(ALWAYS, tiles[i])])
        self.edited = set(st)

        def fixed(name):
            (cube, xy), = pos[name]
            assert cube == ALWAYS and idx(xy) not in st, "%s is moved or edited" % name
            return idx(xy)
        start, airship, canal = fixed("start"), fixed("airship"), fixed("canal")
        self.pos = {k: v[0][1] for k, v in pos.items() if len(v) == 1}
        bridges = [(c, idx(xy)) for c, xy in pos["bridge"]]
        ships = [(c, idx(xy)) for c, xy in pos["ship"]]
        self.ships = ships

        prop = rd.ow_prop
        foot_ok = lambda t: not (prop(t)[0] & rd.OWP_FOOT)
        canoe_ok = lambda t: not (prop(t)[0] & rd.OWP_CANOE)
        ship_ok = lambda t: not (prop(t)[0] & rd.OWP_SHIP)
        chime = lambda t: (prop(t)[0] & rd.OWP_SPEC_MASK) == rd.OWP_CHIME
        special = lambda t: prop(t)[0] & rd.OWP_SPEC_MASK
        for i in st:
            for _, t in st[i]:
                assert special(t) == special(tiles[i]), "an edit changes a special tile at %s" % (
                    (i & 255, i >> 8),)
        layers = {
            "foot": lambda i, t: foot_ok(t) and not chime(t),
            "river": lambda i, t: canoe_ok(t),
            "sea": lambda i, t: ship_ok(t) and i != canal,
        }
        self.layers = layers

        #  Each tile's key in each layer, then the regions: tiles of one key
        #  side by side, by union-find.
        self.label, self.cond, self.node = {}, {}, {}
        for name, ok in layers.items():
            key = [None] * (W * H)
            for i in range(W * H):
                if i in st:
                    cubes = [c for c, t in st[i] if ok(i, t)]
                    key[i] = fn_key(cubes) if cubes else None
                    if key[i] is not None and key[i][1] == (False,):
                        key[i] = None
                else:
                    key[i] = ALWAYS_KEY if ok(i, tiles[i]) else None
            parent = list(range(W * H))

            def find(i):
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i
            for i in range(W * H):
                if key[i] is None:
                    continue
                for b in _neighbours(i)[:3:2]:          # right and down: each pair once
                    if key[b] == key[i]:
                        ra, rb = find(i), find(b)
                        if ra != rb:
                            parent[ra] = rb
            group = [-1] * (W * H)
            roots = {}
            gconds = []
            for i in range(W * H):
                if key[i] is not None:
                    r = find(i)
                    if r not in roots:
                        roots[r] = len(gconds)
                        gconds.append(key_cubes(key[i]))
                    group[i] = roots[r]
            #  A group there only when a neighbouring one is, which it always
            #  touches then, is never apart from it: one region, under the
            #  wider condition.  Its edges keep their own conditions, so the
            #  merged region is whatever of it the settings make, joined.
            near = set()
            for i in range(W * H):
                if group[i] >= 0:
                    for b in _neighbours(i)[:3:2]:
                        if group[b] >= 0 and group[b] != group[i]:
                            near.add((group[i], group[b]))
            up = list(range(len(gconds)))

            def top(x):
                while up[x] != x:
                    up[x] = up[up[x]]
                    x = up[x]
                return x
            #  A set merges, through its first group, into a group it
            #  touches whenever that group is there whenever the first is --
            #  so each member is there only with the set's first group, and
            #  then joined to it, by induction.
            near |= {(b, a) for a, b in near}
            merged = True
            while merged:
                merged = False
                for a, b in sorted(near):
                    if top(a) == a and top(b) != a and implies(gconds[a], gconds[b]):
                        up[a] = top(b)
                        merged = True
            reps = sorted({top(x) for x in range(len(gconds))})
            rnum = {r: k for k, r in enumerate(reps)}
            conds = [gconds[r] for r in reps]
            label = [rnum[top(group[i])] if group[i] >= 0 else -1 for i in range(W * H)]
            self.gcond = getattr(self, "gcond", {})
            self.gcond[name] = (group, gconds)
            kind = {"foot": "ow-foot", "river": "ow-river", "sea": "ow-sea"}[name]
            nodes = [g.node(kind, "OW", "%s#%d" % (name, c), []) for c in range(len(conds))]
            for i in range(W * H):
                if label[i] >= 0:
                    g.nodes[nodes[label[i]]].tiles.append((i & 255, i >> 8))
            self.label[name], self.cond[name], self.node[name] = label, conds, nodes
        F = lambda i: self.node["foot"][self.label["foot"][i]] if self.label["foot"][i] >= 0 else None
        R = lambda i: self.node["river"][self.label["river"][i]] if self.label["river"][i] >= 0 else None
        S = lambda i: self.node["sea"][self.label["sea"][i]] if self.label["sea"][i] >= 0 else None
        self.F, self.R, self.S = F, R, S
        self.flabel = self.label["foot"]
        self.findings = []

        #  Name the foot regions by their entrances, as overworld.py does.
        ents = defaultdict(set)
        for i in range(W * H):
            for _, t in self.states(i):
                if prop(t)[1] & 0x80 and self.label["foot"][i] >= 0:
                    ents[self.label["foot"][i]].add(entrance_names(prop(t)[1] & 0x3F))
        for c, nid in enumerate(self.node["foot"]):
            names = sorted(ents.get(c, ()))
            if names:
                g.nodes[nid].label = "land#%d (%s)" % (c, ", ".join(names[:4]) +
                                                        (", ..." if len(names) > 4 else ""))

        #  A layer's regions side by side, joined while both tiles' groups
        #  are there.
        for name in layers:
            label, nodes = self.label[name], self.node[name]
            group, gconds = self.gcond[name]
            for a in range(W * H):
                if label[a] < 0:
                    continue
                for b in _neighbours(a):
                    if label[b] >= 0 and label[b] != label[a]:
                        cubes = [c for x in gconds[group[a]] for y in gconds[group[b]]
                                 for c in [conj(x, y)] if c is not None]
                        g.edge(nodes[label[a]], nodes[label[b]], 0, "joined", cubes)

        def bridge_at(b):
            return [c for c, i in bridges if i == b]

        def not_bridge(b, cube):
            """cube, where b is not the bridge: the bridge's cubes are each a
            single literal, so their complement is the other sign's."""
            out = [cube]
            for c in bridge_at(b):
                assert bin(c[0] | c[1]).count("1") == 1
                out = [x for x in (conj(o, (c[1], c[0])) for o in out) if x is not None]
            return out

        bridge_banks = defaultdict(list)            # bridge cube -> [(region, cube)]
        canal_seas = []
        foot, river, sea = layers["foot"], layers["river"], layers["sea"]
        for a in range(W * H):
            for ca, ta in self.states(a):
                fa, ra, sa = foot(a, ta), river(a, ta), sea(a, ta)
                if not (fa or ra or sa):
                    continue
                for b in _neighbours(a):
                    for cb, tb in self.states(b):
                        c = conj(ca, cb)
                        if c is None:
                            continue
                        if fa:
                            for bc in bridge_at(b):
                                cc = conj(c, bc)
                                if cc is not None:
                                    bridge_banks[bc].append((F(a), cc))
                            if not foot_ok(tb) and canoe_ok(tb):
                                g.edge(F(a), R(b), BIT["CANOE"], "board canoe", not_bridge(b, c))
                            for sc, si in ships:
                                if b == si:
                                    cc = conj(c, sc)
                                    if cc is not None:
                                        g.edge(F(a), S(b), BIT["SHIP"], "board ship where it starts", [cc])
                        if ra:
                            if not canoe_ok(tb) and foot(b, tb):
                                g.edge(R(a), F(b), 0, "leave canoe", [c])
                            for sc, si in ships:
                                if b == si:
                                    cc = conj(c, sc)
                                    if cc is not None:
                                        g.edge(R(a), S(b), BIT["SHIP"], "board ship from canoe", [cc])
                        if sa:
                            if b == canal:
                                canal_seas.append((S(a), c))
                            elif not ship_ok(tb):
                                if canoe_ok(tb):
                                    g.edge(S(a), R(b), BIT["CANOE"], "ship to canoe", [c])
                                if foot(b, tb) and prop(tb)[0] & rd.OWP_DOCK:
                                    g.edge(S(a), F(b), 0, "dock", [c])
        for bc, banks in bridge_banks.items():
            for x, cx in banks:
                for y, cy in banks:
                    c = conj(cx, cy)
                    if c is not None:
                        g.edge(x, y, BIT["BRIDGE"], "bridge", [c])
        for x, cx in canal_seas:
            for y, cy in canal_seas:
                c = conj(cx, cy)
                if c is not None:
                    g.edge(x, y, BIT["CANAL"], "canal", [c])

        #  The airship, as overworld.py has it.  The floater tiles, its start
        #  and the caravan are written by no edit (asserted above for every
        #  special tile, here for the start).
        self.sky = g.node("sky", "OW", "sky (airship)", [])
        floater = [i for i in range(W * H) if special(tiles[i]) == rd.OWP_FLOATER]
        assert not set(floater) & set(st)
        g.location("event", "RaiseAirship", "raise the airship", sorted({F(i) for i in floater} - {None}),
                   BIT["FLOATER"], "AIRSHIP")
        g.edge(F(airship), self.sky, BIT["AIRSHIP"], "take off", [ALWAYS])
        self.landable = set()
        for i in range(W * H):
            for c, t in self.states(i):
                if foot(i, t) and not (prop(t)[0] & rd.OWP_NOLAND):
                    g.edge(self.sky, F(i), 0, "land", [c])
                    self.landable.add(F(i))
        caravan = [i for i in range(W * H) if special(tiles[i]) == rd.OWP_CARAVAN]
        assert not set(caravan) & set(st)
        self.caravan_nodes = sorted({F(i) for i in caravan} - {None})

        #  Entrances: (entrance id, region, requirement, tile), each with its
        #  condition in ent_cond.
        self.entrances, self.ent_cond = [], {}

        def entrance(e, cube):
            if e[1] is None:
                return
            if e not in self.ent_cond:
                self.entrances.append(e)
                self.ent_cond[e] = []
            self.ent_cond[e].append(cube)
        for i in range(W * H):
            for c, t in self.states(i):
                if not prop(t)[1] & 0x80:
                    continue
                eid = prop(t)[1] & 0x3F
                if chime(t):
                    for b in _neighbours(i):
                        for cb, tb in self.states(b):
                            cc = conj(c, cb)
                            if cc is not None and foot(b, tb):
                                entrance((eid, F(b), BIT["CHIME"], i), cc)
                if foot(i, t):
                    entrance((eid, F(i), 0, i), c)
                if canoe_ok(t):
                    entrance((eid, R(i), 0, i), c)
        for e in self.ent_cond:
            self.ent_cond[e] = simplify(self.ent_cond[e])

        g.start = F(start)
        self.stats = {"foot regions": len(self.node["foot"]), "river regions": len(self.node["river"]),
                      "sea regions": len(self.node["sea"]), "edited tiles": len(st)}

    def node_at(self, x, y):
        """The land region at (x, y), or beside it: for exits, which the
        edits never move (asserted where they are read)."""
        i = (x & 255) | ((y & 255) << 8)
        if self.flabel[i] >= 0:
            return self.F(i)
        for b in _neighbours(i):
            if self.flabel[b] >= 0:
                return self.F(b)
        return None


def vehicle_edges(g, ow):
    """placement.vehicle_edges for the edited overworld: the airship flies
    from anywhere once raised; the ship, as FFR reads it, sails from
    wherever it is found -- but under Ship in Drydock every ship is moored
    at Gaia's drydock (owedits.DRYDOCK_XY), so it is boarded only there,
    by ow's own 'board ship where it starts' edges, as FFR's sanity
    checker boards it only from the dock's land (SanityCheckerV2)."""
    out = [(g.start, ow.sky, BIT["AIRSHIP"], "FFR: the airship flies from anywhere", [ALWAYS])]
    sc, si = ow.ships[0]
    out.append((g.start, ow.S(si), BIT["SHIP"], "FFR: the ship appears where it is found", [sc]))
    return out
