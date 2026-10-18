"""
build.py -- assemble the world graph from an overworld and the 61 standard maps.

Most of the graph is derived from tile data.  What is not derivable lives in
the two tables below and nowhere else: what each reward NPC hands out and asks
for, keyed by talk routine (so the object ids come from the ROM's own talk
table), and which talk routine is the game's goal.
"""
import romdata as rd
from model import BIT, Graph, mask
from overworld import Overworld
from standard import GATE_TILE, GATE_TILE_EARLY_ORDEALS, StandardMap

# talk routine -> (reward, requirement).  Vanilla FF1; FFR's NpcReward list
# (ItemLocations.cs) is the same thirteen plus the two events here.
NPC_REWARDS = {
    "Talk_KingConeria": ("BRIDGE", mask("PRINCESS")),
    "Talk_Princess2":   ("LUTE", mask("PRINCESS")),
    "Talk_Bikke":       ("SHIP", 0),
    "Talk_ElfPrince":   ("KEY", mask("HERB")),
    "Talk_Astos":       ("CRYSTAL", mask("CROWN")),
    "Talk_Matoya":      ("HERB", mask("CRYSTAL")),
    "Talk_Nerrick":     ("CANAL", mask("TNT")),
    "Talk_Smith":       (None, mask("ADAMANT")),        # Xcalber: not a logic item
    "Talk_Sarda":       ("ROD", mask("VAMPIRE")),
    "Talk_CanoeSage":   ("CANOE", mask("ORB_EARTH")),
    "Talk_CubeBot":     ("CUBE", 0),
    "Talk_Fairy":       ("OXYALE", mask("BOTTLE")),
    "Talk_Chime":       ("CHIME", mask("TRANSLATED")),
    # events
    "Talk_Princess1":   ("PRINCESS", 0),
    "Talk_Vampire":     ("VAMPIRE", 0),
    "Talk_Unne":        ("TRANSLATED", mask("SLAB")),
}
#  FFR's Early King, Early Sarda and Early Sage: the reward without the event.
#  Early Ordeals is a tile change (standard.GATE_TILE_EARLY_ORDEALS).
EARLY = {"king": "Talk_KingConeria", "sarda": "Talk_Sarda", "sage": "Talk_CanoeSage",
         "ordeals": None}
GOAL = ("ToFRChaos", "Talk_fight")      # Chaos: the one fight on the last floor


def build(ow_tiles=None, pos=None, exits=None, wiring=None, early=(), edits=None):
    """`wiring` (wiring.Wiring) says where every entrance, teleport and exit
    leads; without it, where the ROM's tables say.  `exits` moves exits for
    an alternate overworld.  `early` names FFR's Early flags that are on,
    from EARLY's keys.  `edits` (owedits.graph_edits) builds the overworld
    for every combination of the map edits at once (edited.py), `pos` then
    owedits.graph_positions's: a conditional graph."""
    assert set(early) <= set(EARLY), early
    early_npcs = {EARLY[e] for e in early if EARLY[e]}
    g = Graph(conditional=edits is not None)
    talk = rd.talk_routines()
    ow_tiles = ow_tiles or rd.vanilla_overworld()
    pos = pos or rd.VANILLA_POS
    entrance = (lambda e: wiring.entrance[e]) if wiring else rd.entrance
    normal = (lambda t: wiring.normal[t]) if wiring else rd.normal_tele
    exit_at = dict(wiring.exits) if wiring else {}
    exit_at.update(exits or {})
    ent_name = lambda e: rd.MAP_NAMES[entrance(e)[0]]

    if edits is not None:
        from edited import EditedOverworld
        ow = EditedOverworld(g, ow_tiles, pos, ent_name, edits)
    else:
        ow = Overworld(g, ow_tiles, pos, ent_name)
    ent_cond = getattr(ow, "ent_cond", {})
    gates = GATE_TILE_EARLY_ORDEALS if "ordeals" in early else GATE_TILE
    maps = [StandardMap(g, m, talk, gates) for m in range(rd.MAP_COUNT)]

    #  Every way into a map: (caller node, landing nodes, map, what).  The
    #  warp-back edges and the checks in fecheck.py are made from these.
    g.entries = []

    # Overworld entrances into the maps.
    for eid, src, req, tile in ow.entrances:
        m, x, y = entrance(eid)
        land = maps[m].node_at(x, y)
        for dst in land:
            g.edge(src, dst, req, "entrance %d (%s)" % (eid, rd.MAP_NAMES[m]),
                   ent_cond.get((eid, src, req, tile)))
        g.entries.append((src, land, m, ("entrance", eid)))

    #  Where an exit puts the party.  An exit recomputed to an entrance's own
    #  tile, as the shuffle does, returns the party to the region that
    #  entrance is entered from -- the river, in the canoe, for the
    #  Waterfall's -- not to whatever land is nearest the coordinate.
    at_entrance = {}
    for eid, src, req, tile in ow.entrances:
        if not req:
            at_entrance.setdefault((tile & 255, tile >> 8), set()).add(src)

    def exit_nodes(x, y):
        nodes = sorted(at_entrance.get((x, y), ())) or [ow.node_at(x, y)]
        if nodes == [None]:
            #  Nowhere a party can stand: in the game it is dropped there and
            #  stuck.  A node with no way out, so the stranding check sees it,
            #  rather than no edge, which would hide it.
            nodes = [g.node("void", (x, y), "nowhere (%d,%d)" % (x, y), [])]
        return nodes

    # Map teleports: normal ones to another map, exits to the overworld.
    for sm in maps:
        for src, req, tele, tid, tile in sm.pending:
            if tele == rd.TP_TELE_NORM:
                m, x, y = normal(tid)
                land = maps[m].node_at(x, y)
                for dst in land:
                    g.edge(src, dst, req, "teleport %d -> %s" % (tid, rd.MAP_NAMES[m]))
                g.entries.append((src, land, m, ("teleport", tid)))
            else:
                #  An alternate overworld moves the exits with it.
                x, y = exit_at.get(tid, rd.exit_tele(tid))
                assert edits is None or (x | y << 8) not in ow.edited, "an exit on an edited tile"
                for dst in exit_nodes(x, y):
                    g.edge(src, dst, req, "exit %d" % tid)

    #  Warps back.  A warp tile returns the party to whoever brought it into
    #  this map: DoStandardMap returning one level.  So every region with a
    #  warp, among those reachable inside the map from a landing, gets an
    #  edge back to that landing's caller.  They add nothing to what can be
    #  reached -- the caller was reached first -- so they are kept apart from
    #  g.edges; the stranding check (fecheck.py) is what reads them.
    intra = {}
    for a, b, r, why in g.edges:
        na, nb = g.nodes[a], g.nodes[b]
        if na.kind == "sm" and nb.kind == "sm" and na.where == nb.where:
            intra.setdefault(a, []).append(b)
    g.returns = []
    g.warp_back = {}                # (kind, id) -> regions that warp back
    for src, land, m, what in g.entries:
        seen, todo = set(land), list(land)
        while todo:
            n = todo.pop()
            for b in intra.get(n, ()):
                if b not in seen:
                    seen.add(b)
                    todo.append(b)
        for n in sorted(seen & maps[m].warp_nodes):
            g.returns.append((n, src, 0, "warp back (%s)" % (what,)))
            g.warp_back.setdefault(what, []).append(n)

    #  Re-boarding where the vehicle was left.  The model boards the ship and
    #  takes off in the airship only where each starts (README); a party that
    #  docked can sail away from the same dock, and one that landed can take
    #  off where it landed.  Returns too: they reach nothing new.
    for s, d, r, why in list(g.edges):
        if why in ("dock", "ship to canoe"):
            g.returns.append((d, s, BIT["SHIP"], "re-board the ship"))
        elif why == "land":
            g.returns.append((d, s, BIT["AIRSHIP"], "take off again"))

    # Chests found in more than one map (a tile type shared by maps on one
    # tileset) are one chest: merge them.
    chests = {}
    for loc in list(g.locations):
        if loc.kind == "chest":
            if loc.ident in chests:
                chests[loc.ident].nodes = sorted(set(chests[loc.ident].nodes) | set(loc.nodes))
                g.locations.remove(loc)
            else:
                chests[loc.ident] = loc
                item = rd.TREASURE[loc.ident]
                loc.item_id = item
                loc.reward = rd.ITEM_NAMES[item] if 1 <= item <= 16 else None

    # Reward NPCs and events, wherever their objects stand.  An object id
    # listed in more than one map is one NPC with several places to find it
    # (visibility is per id): vanilla lists the fairy in Ice Cave B1 as well
    # as Gaia.  Every copy counts, and the copies are reported.
    npcs = {}
    g.duplicates = {}
    for sm in maps:
        for oid, x, y, flags in sm.objects:
            routine = talk[oid]
            g.duplicates.setdefault(oid, []).append((rd.MAP_NAMES[sm.m], x, y))
            if routine in NPC_REWARDS:
                if routine in npcs:
                    loc = npcs[routine]
                    loc.nodes = sorted(set(loc.nodes) | set(sm.object_nodes(x, y)))
                else:
                    reward, req = NPC_REWARDS[routine]
                    if routine in early_npcs:
                        req = 0
                    npcs[routine] = g.location("npc", routine, "%s (%s)" % (routine[5:], rd.MAP_NAMES[sm.m]),
                                               sm.object_nodes(x, y), req, reward)
            if (rd.MAP_NAMES[sm.m], routine) == GOAL:
                g.location("event", "Chaos", "Chaos", sm.object_nodes(x, y), 0, "CHAOS")
    g.duplicates = {oid: v for oid, v in g.duplicates.items()
                    if len({m for m, _, _ in v}) > 1}
    missing = set(NPC_REWARDS) - set(npcs)

    g.location("shop", "Caravan", "caravan (bottle)", ow.caravan_nodes, 0, "BOTTLE")
    return g, ow, maps, sorted(missing)
