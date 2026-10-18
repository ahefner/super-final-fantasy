"""
overworld.py -- regions of the overworld and how the party moves between them.

The rules are the game's, from bank $0F (ProcessOWInput, OWCanMove, BoardCanoe,
BoardShip, UnboardBoat, LandAirship, FlyAirship, IsOnBridge, IsOnCanal):

  - A tile's first property byte forbids, by bit: foot ($01), canoe ($02),
    ship ($04), airship landing ($08).  $20 is a dock, $C0 the special code
    (chime $40, caravan $80, floater $C0).  The second byte's bit 7 marks an
    entrance; its low six bits are the entrance id.
  - On foot, moving onto a tile foot may not enter tries, in order: the bridge
    (bridge tile, if built), the canoe (canoe may enter, CANOE owned), the
    ship (the tile is where the ship is).
  - In the ship, moving onto a tile the ship may not enter tries the canoe,
    then a dock (foot may enter, and the dock bit is set).  The canal tile is
    blocked to the ship until the canal is built.
  - In the canoe, a tile the canoe may not enter is stepped onto on foot if
    foot may enter it.
  - The airship flies anywhere and lands where bit $08 is clear.  It rises
    where it was left (airship_x/y) once the FLOATER is used on a floater tile.

Reachability never needs to re-board the ship: everything the ship can reach is
reached from the sea the first time, so the only edge from land to sea is
where the ship starts.  (An edge from every dock would be wrong: it would let
the ship be boarded wherever the party happens to walk to.)
"""
from collections import deque

import romdata as rd
from model import BIT, mask

W = H = 256


def _neighbours(i):
    x, y = i & 255, i >> 8
    return (((x + 1) & 255) | (y << 8), ((x - 1) & 255) | (y << 8),
            x | (((y + 1) & 255) << 8), x | (((y - 1) & 255) << 8))


def _components(passable):
    label = [-1] * (W * H)
    sizes = []
    for i in range(W * H):
        if passable[i] and label[i] < 0:
            c = len(sizes)
            label[i] = c
            q, n = deque([i]), 0
            while q:
                j = q.popleft()
                n += 1
                for k in _neighbours(j):
                    if passable[k] and label[k] < 0:
                        label[k] = c
                        q.append(k)
            sizes.append(n)
    return label, sizes


class Overworld:
    def __init__(self, g, tiles, pos, entrance_names):
        self.g, self.tiles, self.pos = g, tiles, pos
        idx = lambda p: p[0] | (p[1] << 8)
        p0 = [rd.ow_prop(t)[0] for t in tiles]
        p1 = [rd.ow_prop(t)[1] for t in tiles]
        self.p0, self.p1 = p0, p1
        foot_ok = [not (v & rd.OWP_FOOT) for v in p0]
        canoe_ok = [not (v & rd.OWP_CANOE) for v in p0]
        ship_ok = [not (v & rd.OWP_SHIP) for v in p0]
        chime = [(v & rd.OWP_SPEC_MASK) == rd.OWP_CHIME for v in p0]
        bridge, canal = idx(pos["bridge"]), idx(pos["canal"])
        ship, airship, start = idx(pos["ship"]), idx(pos["airship"]), idx(pos["start"])

        foot = [foot_ok[i] and not chime[i] for i in range(W * H)]
        river = list(canoe_ok)
        sea = [ship_ok[i] and i != canal for i in range(W * H)]
        self.foot, self.river, self.sea = foot, river, sea

        self.findings = []
        if foot_ok[bridge] or not ship_ok[canal]:
            self.findings.append("bridge tile walkable, or canal tile not sea "
                                 "-- the sprites would be decoration")

        self.flabel, fsizes = _components(foot)
        self.rlabel, rsizes = _components(river)
        self.slabel, ssizes = _components(sea)

        # Name each foot region by the entrances it holds, for the report.
        ents = {}
        for i in range(W * H):
            if p1[i] & 0x80:
                ents.setdefault(i, entrance_names(p1[i] & 0x3F))
        self.fnode = [g.node("ow-foot", "OW", "land#%d" % c, []) for c in range(len(fsizes))]
        self.rnode = [g.node("ow-river", "OW", "river#%d" % c, []) for c in range(len(rsizes))]
        self.snode = [g.node("ow-sea", "OW", "sea#%d" % c, []) for c in range(len(ssizes))]
        for i in range(W * H):
            for lab, nodes in ((self.flabel, self.fnode), (self.rlabel, self.rnode),
                               (self.slabel, self.snode)):
                if lab[i] >= 0:
                    g.nodes[nodes[lab[i]]].tiles.append((i & 255, i >> 8))
        for c, nid in enumerate(self.fnode):
            names = sorted({ents[i] for i in ents if self.flabel[i] == c})
            if names:
                g.nodes[nid].label = "land#%d (%s)" % (c, ", ".join(names[:4]) +
                                                        (", ..." if len(names) > 4 else ""))

        F = lambda i: self.fnode[self.flabel[i]] if self.flabel[i] >= 0 else None
        R = lambda i: self.rnode[self.rlabel[i]] if self.rlabel[i] >= 0 else None
        S = lambda i: self.snode[self.slabel[i]] if self.slabel[i] >= 0 else None
        self.F = F

        bridge_banks, canal_seas = set(), set()
        for a in range(W * H):
            for b in _neighbours(a):
                if foot[a]:
                    if b == bridge:
                        bridge_banks.add(F(a))
                    elif not foot_ok[b] and canoe_ok[b]:
                        g.edge(F(a), R(b), BIT["CANOE"], "board canoe")
                    if b == ship:
                        g.edge(F(a), S(b), BIT["SHIP"], "board ship where it starts")
                if river[a]:
                    if not canoe_ok[b] and foot[b]:
                        g.edge(R(a), F(b), 0, "leave canoe")
                    if b == ship:
                        g.edge(R(a), S(b), BIT["SHIP"], "board ship from canoe")
                if sea[a]:
                    if b == canal:
                        canal_seas.add(S(a))
                    elif not ship_ok[b]:
                        if canoe_ok[b]:
                            g.edge(S(a), R(b), BIT["CANOE"], "ship to canoe")
                        if foot[b] and p0[b] & rd.OWP_DOCK:
                            g.edge(S(a), F(b), 0, "dock")
        for x in bridge_banks:
            for y in bridge_banks:
                g.edge(x, y, BIT["BRIDGE"], "bridge")
        for x in canal_seas:
            for y in canal_seas:
                g.edge(x, y, BIT["CANAL"], "canal")

        # The airship.  It is raised by the FLOATER on a floater tile, sits at
        # airship_x/y, and is boarded there on foot.  From the sky it can come
        # down on any region with a landable tile.
        self.sky = g.node("sky", "OW", "sky (airship)", [])
        floater_regions = {F(i) for i in range(W * H)
                           if (p0[i] & rd.OWP_SPEC_MASK) == rd.OWP_FLOATER and F(i) is not None}
        g.location("event", "RaiseAirship", "raise the airship", sorted(floater_regions),
                   BIT["FLOATER"], "AIRSHIP")
        if F(airship) is None:
            self.findings.append("airship start %s is not walkable" % (pos["airship"],))
        g.edge(F(airship), self.sky, BIT["AIRSHIP"], "take off")
        landable = {F(i) for i in range(W * H)
                    if foot[i] and not (p0[i] & rd.OWP_NOLAND)}
        for n in landable:
            g.edge(self.sky, n, 0, "land")
        self.landable = landable

        caravan = {F(i) for i in range(W * H)
                   if (p0[i] & rd.OWP_SPEC_MASK) == rd.OWP_CARAVAN and F(i) is not None}
        self.caravan_nodes = sorted(caravan)

        # Entrances: (entrance id, source node, requirement).  A tile the party
        # can stand on belongs to its region already; a chime tile cannot be
        # stood on without the CHIME, so it is reached from its neighbours.
        self.entrances = []
        for i in range(W * H):
            if not p1[i] & 0x80:
                continue
            eid = p1[i] & 0x3F
            if chime[i]:
                for b in _neighbours(i):
                    if foot[b]:
                        self.entrances.append((eid, F(b), BIT["CHIME"], i))
            if foot[i]:
                self.entrances.append((eid, F(i), 0, i))
            if canoe_ok[i]:
                self.entrances.append((eid, R(i), 0, i))

        g.start = F(start)
        self.stats = {"land regions": len(fsizes), "river regions": len(rsizes),
                      "sea regions": len(ssizes), "landable regions": len(landable)}

    def node_at(self, x, y):
        """The land region the party stands in at (x, y) -- for exit
        teleports, which put the party down on a tile, usually walkable."""
        i = (x & 255) | ((y & 255) << 8)
        if self.flabel[i] >= 0:
            return self.F(i)
        for b in _neighbours(i):
            if self.flabel[b] >= 0:
                return self.F(b)
        return None
