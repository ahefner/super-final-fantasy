"""
standard.py -- regions of the 61 standard maps (towns, castles, dungeons).

The rules are the game's, from bank $0F (CanPlayerMoveSM, IsObjectInPath and
the lut_SMMoveJmpTbl handlers):

  - A tile with no special code and the NOMOVE bit is a wall.  Otherwise the
    special code decides: a chest is a wall you open from beside it; a locked
    door needs the KEY; the crown, cube and four-orb tiles need the CROWN, the
    CUBE and all four orbs; the four altars light their orb when stepped on;
    everything else is floor.
  - Bits 6-7 of the first byte make a tile a teleport: normal ($80, to
    NormTele[id]), exit ($C0, to the overworld at ExitTele[id]), or warp ($40,
    back to wherever the party came from).  Warps are left out: they only ever
    return the party somewhere it has already been, so they add nothing to
    reachability.
  - A map object blocks its tile.  Only stationary, initially visible objects
    matter.  Of those, an object whose talk routine hides it unconditionally
    (a fight, a word) is no obstacle; one that hides only for an item is a gate
    needing that item; one that never hides is a wall.  The rod and lute
    plates are gates opened by using the item beside them.
  - Maps wrap at 64.
"""
from collections import deque

import romdata as rd
from model import BIT, ORBS, mask

N = 64

GATE_TILE = {"locked": BIT["KEY"], "crown": BIT["CROWN"], "cube": BIT["CUBE"],
             "4orbs": ORBS}
#  FFR's Early Ordeals clears the special code of the two thrones (Castle
#  tileset $61/$62), the only crown tiles; each is then floor and a teleport.
GATE_TILE_EARLY_ORDEALS = {k: v for k, v in GATE_TILE.items() if k != "crown"}
ALTAR = {"earthorb": "ORB_EARTH", "fireorb": "ORB_FIRE",
         "waterorb": "ORB_WATER", "airorb": "ORB_AIR"}

# Objects that leave once the party has an item (talk routine -> item).
GATE_ROUTINE = {"Talk_Titan": BIT["RUBY"], "Talk_SubEng": BIT["OXYALE"],
                "Talk_BlackOrb": ORBS, "Talk_Astos": BIT["CROWN"],
                "Talk_Nerrick": BIT["TNT"]}
GATE_OBJECT = {0x16: BIT["ROD"], 0x17: BIT["LUTE"]}      # OBJID_RODPLATE, _LUTEPLATE
# Objects that leave unconditionally once talked to (usually after a fight).
YIELDING_ROUTINE = {"Talk_Garland", "Talk_Vampire", "Talk_fight", "Talk_Replace",
                    "Talk_CoOGuy", "Talk_Princess1"}


def _neighbours(i):
    x, y = i & 63, i >> 6
    return (((x + 1) & 63) | (y << 6), ((x - 1) & 63) | (y << 6),
            x | (((y + 1) & 63) << 6), x | (((y - 1) & 63) << 6))


class StandardMap:
    def __init__(self, g, m, talk, gates=GATE_TILE):
        self.g, self.m = g, m
        name = rd.MAP_NAMES[m]
        self.tiles = rd.standard_map(m)
        ts = rd.TILESET_OF_MAP[m]
        props = [rd.sm_prop(ts, t) for t in self.tiles]
        spec = [rd.SPEC.get(p0 & rd.TP_SPEC_MASK) for p0, _ in props]
        self.props, self.spec = props, spec

        # What each tile is to a walking party.
        kind = []           # "floor" | "wall" | ("gate", req)
        for i, (p0, _) in enumerate(props):
            s = spec[i]
            if s is None:
                kind.append("wall" if p0 & rd.TP_NOMOVE else "floor")
            elif s == "treasure":
                kind.append("wall")
            elif s in gates:
                kind.append(("gate", gates[s]))
            else:
                kind.append("floor")

        self.objects = rd.map_objects(m)
        self.blockers = []
        for oid, x, y, flags in self.objects:
            visible = rd.INIT_GAME_FLAGS[oid] & 1
            if not visible or not flags & rd.OBJ_STATIONARY:
                continue
            i = x | (y << 6)
            routine = talk[oid]
            if kind[i] == "wall":
                #  e.g. a second copy of the rod plate, listed in Sky Palace 2F
                #  at the same coordinates as in Earth B3, where it is in a wall.
                self.blockers.append((oid, routine, "inert (on a wall)", 0, (x, y)))
            elif oid in GATE_OBJECT:
                kind[i] = ("gate", GATE_OBJECT[oid])
                self.blockers.append((oid, routine, "gate", GATE_OBJECT[oid], (x, y)))
            elif routine in GATE_ROUTINE:
                kind[i] = ("gate", GATE_ROUTINE[routine])
                self.blockers.append((oid, routine, "gate", GATE_ROUTINE[routine], (x, y)))
            elif routine in YIELDING_ROUTINE:
                self.blockers.append((oid, routine, "yields", 0, (x, y)))
            else:
                kind[i] = "wall"
                self.blockers.append((oid, routine, "wall", 0, (x, y)))
        self.kind = kind

        # Regions of floor.
        label = [-1] * (N * N)
        self.region_nodes = []
        for i in range(N * N):
            if kind[i] == "floor" and label[i] < 0:
                c = len(self.region_nodes)
                nid = g.node("sm", name, "%s#%d" % (name, c), [])
                self.region_nodes.append(nid)
                label[i] = c
                q = deque([i])
                while q:
                    j = q.popleft()
                    g.nodes[nid].tiles.append((j & 63, j >> 6))
                    for k in _neighbours(j):
                        if kind[k] == "floor" and label[k] < 0:
                            label[k] = c
                            q.append(k)
        self.label = label

        # Teleports, gates, chests, altars.  Teleport targets are resolved
        # once every map exists: pending = (src node, req, kind, id, tile).
        # Warp tiles are not edges (build.py makes them returns); the regions
        # holding one are noted here.
        self.pending = []
        self.warp_nodes = set()
        for i in range(N * N):
            p0, p1 = props[i]
            tele = p0 & rd.TP_TELE_MASK
            here = self.at(i)
            if isinstance(kind[i], tuple):
                req = kind[i][1]
                beside = self.beside(i)
                if tele in (rd.TP_TELE_NORM, rd.TP_TELE_EXIT):
                    for b in beside:
                        self.pending.append((b, req, tele, p1, i))
                else:
                    for a in beside:
                        for b in beside:
                            g.edge(a, b, req, "%s gate at (%d,%d)" % (name, i & 63, i >> 6))
            elif kind[i] == "floor" and tele in (rd.TP_TELE_NORM, rd.TP_TELE_EXIT):
                self.pending.append((here, 0, tele, p1, i))
            elif kind[i] == "floor" and tele == rd.TP_TELE_WARP:
                self.warp_nodes.add(here)
            if spec[i] == "treasure":
                g.location("chest", p1, "chest %02X (%s)" % (p1, name), self.beside(i), 0, None)
            elif spec[i] in ALTAR and kind[i] == "floor":
                g.location("altar", spec[i], "%s altar" % ALTAR[spec[i]][4:].lower(),
                           [here], 0, ALTAR[spec[i]])

    def at(self, i):
        return self.region_nodes[self.label[i]] if self.label[i] >= 0 else None

    def beside(self, i):
        return sorted({self.at(b) for b in _neighbours(i) if self.label[b] >= 0})

    def node_at(self, x, y):
        """Where a party put down at (x, y) can walk: that tile's region, or
        if it lands on a gate or a door-like tile, the regions beside it."""
        i = (x & 63) | ((y & 63) << 6)
        if self.label[i] >= 0:
            return [self.at(i)]
        return self.beside(i)

    def object_nodes(self, x, y):
        """Where the party can stand to talk to an object at (x, y)."""
        i = (x & 63) | ((y & 63) << 6)
        out = set(self.beside(i))
        if self.label[i] >= 0:
            out.add(self.at(i))
        return sorted(out)
