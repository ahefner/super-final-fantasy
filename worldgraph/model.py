"""
model.py -- the requirement vocabulary and the graph container.

A requirement is a bitmask over REQS.  Items are the things a placement moves
around; events are things that happen at fixed places (a fiend's altar, Unne's
translation) and are modelled as items handed out by fixed locations.  Map
edits and the Treasures section's free items would be more bits on the same
word: a map-edit flag is just an item the party starts with.
"""

REQS = [
    # key items, item ids $01-$10
    "LUTE", "CROWN", "CRYSTAL", "HERB", "KEY", "TNT", "ADAMANT", "SLAB",
    "RUBY", "ROD", "FLOATER", "CHIME", "TAIL", "CUBE", "BOTTLE", "OXYALE",
    # vehicles and map changes
    "CANOE", "SHIP", "BRIDGE", "CANAL",
    # events
    "AIRSHIP",      # the airship has been raised (FLOATER used in the desert)
    "PRINCESS",     # the princess has been rescued
    "VAMPIRE",      # the vampire has been beaten
    "TRANSLATED",   # Unne has read the slab
    "ORB_EARTH", "ORB_FIRE", "ORB_WATER", "ORB_AIR",
    "CHAOS",        # the goal
]
BIT = {name: 1 << i for i, name in enumerate(REQS)}
ORBS = BIT["ORB_EARTH"] | BIT["ORB_FIRE"] | BIT["ORB_WATER"] | BIT["ORB_AIR"]


def mask(*names):
    m = 0
    for n in names:
        m |= BIT[n]
    return m


def names(m):
    return [n for n in REQS if m & BIT[n]]


def fmt(m):
    return "+".join(names(m)) or "-"


class Node:
    def __init__(self, nid, kind, where, label, tiles):
        self.id, self.kind, self.where, self.label = nid, kind, where, label
        self.tiles = tiles          # list of (x, y) in this region


class Location:
    """Something that hands out an item or event.  `nodes` is a list: the
    location is available from any of them (a chest opened from either side of
    a corridor, an NPC standing in a doorway)."""
    def __init__(self, kind, ident, label, nodes, req, reward):
        self.kind, self.ident, self.label = kind, ident, label
        self.nodes, self.req, self.reward = nodes, req, reward


class Graph:
    def __init__(self):
        self.nodes = []
        self.edges = []             # (src, dst, req, why)
        self._seen = set()
        self.locations = []
        self.start = None

    def node(self, kind, where, label, tiles):
        n = Node(len(self.nodes), kind, where, label, tiles)
        self.nodes.append(n)
        return n.id

    def edge(self, src, dst, req, why):
        #  The overworld scan proposes the same edge once per pair of
        #  neighbouring tiles along a whole coastline; keep the first.
        if src is None or dst is None or src == dst or (src, dst, req) in self._seen:
            return
        self._seen.add((src, dst, req))
        self.edges.append((src, dst, req, why))

    def location(self, kind, ident, label, nodes, req, reward):
        nodes = sorted(set(n for n in nodes if n is not None))
        self.locations.append(Location(kind, ident, label, nodes, req, reward))
        return self.locations[-1]
