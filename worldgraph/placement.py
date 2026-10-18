"""
placement.py -- FFR's PredictivePlacement (FF1Lib/PredictivePlacement.cs),
ported onto the world graph.

A forward fill.  Each cycle it asks, for every key item still to place, how
many more locations the party could reach if it had that item, sorts the
items into bins by that count, weights the bins by how many incentive (or
loose) locations are reachable right now, applies FFR's per-item weights,
minimum cycles and minimum accessibility, picks one item, and puts it in a
reachable location of its kind.  Incentive items go to incentive locations,
the rest anywhere else.  Up to three attempts, as FFR.

The query each cycle repeats -- what can be reached once everything already
placed is collected, perhaps with one or two items more -- is a fixpoint of
analysis.reach() on the graph, where FFR asks its sanity checker.

Simplifications, for now:
  - the location is drawn uniformly, not by FFR's balanced RewardSourcePicker
    (which also weighs NPCs against chests and "spread" placement)
  - the shop slot is just the caravan, in the pool like any location, where
    FFR picks a vendor item up front
  - FFR's vehicle readings are the two edges run_vanilla.py adds: the airship
    flies from anywhere once raised, and the ship appears in the inner sea
    once found (FFR moves it to the dock nearest where it was found)
  - no shards, no plando, no loose-item tuning flags
"""
import random

import analysis
import romdata as rd
from model import BIT, mask

#  FFR's KeyItems: everything that opens something.  TAIL opens nothing in the
#  logic; it is placed as an incentive that is not a key item.
KEY_ITEMS = ["LUTE", "CROWN", "CRYSTAL", "HERB", "KEY", "TNT", "ADAMANT", "SLAB", "RUBY", "ROD",
             "FLOATER", "CHIME", "CUBE", "BOTTLE", "OXYALE", "CANOE", "SHIP", "BRIDGE", "CANAL"]
NON_KEY_INCENTIVES = ["TAIL"]

#  Entrance shuffle on means FFR's "unsafe" tables.
EXCEPTION_WEIGHTS = {"BRIDGE": 0.75, "KEY": 0.25, "CANOE": 0.75, "FLOATER": 0.25, "LUTE": 0.25,
                     "OXYALE": 1.25, "CHIME": 1.25, "ADAMANT": 0.75, "HERB": 0.75, "CROWN": 0.75,
                     "CRYSTAL": 0.75, "BOTTLE": 0.75, "SLAB": 0.75, "TNT": 0.75}
MIN_CYCLES = {"KEY": 5, "SHIP": 2, "CANOE": 3, "FLOATER": 10, "LUTE": 10}
MIN_ACCESS = {"CHIME": 5, "CUBE": 5, "OXYALE": 5}
NON_KEY_WEIGHT, NON_KEY_MIN_CYCLE = 0.5, 10
CRIT_NON, SAFE_NON, CRIT_INC, SAFE_INC = 5, 20, 2, 3

#  The NPCs whose reward is fixed: events, not places to put items.
FIXED_NPCS = {"Talk_Princess1", "Talk_Vampire", "Talk_Unne"}
MAJOR_CHESTS = {0x03, 0x1C, 0x3D, 0x6A, 0x72, 0x83, 0xB4, 0xE9}   # FFR's *Major chests

#  Placer's own default, kept for run_fe.py's numbers: the vehicles and the
#  BOTTLE loose.  It was chosen when all twenty incentivised seemed to fail two
#  seeds in three; that was the comparison, not the pool (run_fe.py shuffles
#  the towns, and the graph then had no Early flags).  New callers use setup().
DEFAULT_INCENTIVES = set(KEY_ITEMS + NON_KEY_INCENTIVES) - {"SHIP", "BRIDGE", "CANAL", "CANOE", "BOTTLE"}

#  The cart's incentive rows (randomization-notes.md §12).  Each Free row is
#  Incentive / Loose / Free; its logic item is the FLOATER for the AIRSHIP row.
FREE_ROWS = {"SHIP": "SHIP", "AIRSHIP": "FLOATER", "BRIDGE": "BRIDGE", "CANAL": "CANAL",
             "CANOE": "CANOE", "KEY": "KEY", "CHIME": "CHIME", "CROWN": "CROWN",
             "LUTE": "LUTE", "TAIL": "TAIL", "ROD": "ROD"}
#  "Other items": Incentive / Loose, one row for the nine with no Free row.
OTHER_ITEMS = ["CRYSTAL", "HERB", "TNT", "ADAMANT", "SLAB", "RUBY", "CUBE", "BOTTLE", "OXYALE"]
#  Gear rows: Incentive / Treasure.  Gear is nothing to the logic; an
#  incentive piece is placed as TAIL is, and a Treasure one not at all.
GEAR = ["MASAMUNE", "KATANA", "VORPAL", "DEFENSE", "OPAL", "POWERGAUNTLET", "WHITESHIRT",
        "RIBBON", "XCALBER"]
#  Spots.  Standard is FFR's default: the 14 reward NPCs (the caravan among
#  them) and the *Major chests but Volcano's.  Wide is Free Enterprise's:
#  VolcanoMajor, MarshCave13 (the locked room), TitansTunnel1 and Cardia4 more.
STANDARD_CHESTS = MAJOR_CHESTS - {0x6A}
WIDE_CHESTS = MAJOR_CHESTS | {0x20, 0x46, 0x87}


def setup(g, spots="standard", rows=None, other="incentive", gear=()):
    """The Placer's arguments from the cart's rows.  `rows` maps a Free row to
    "incentive", "loose" or "free" (default incentive); `gear` lists the
    incentive gear.  Returns (free mask, items to place, incentive items,
    incentive locations)."""
    rows = dict.fromkeys(FREE_ROWS, "incentive") | dict(rows or {})
    assert set(rows) == set(FREE_ROWS) and set(rows.values()) <= {"incentive", "loose", "free"}, rows
    assert other in ("incentive", "loose") and set(gear) <= set(GEAR), (other, gear)
    free, items, inc = 0, [], set()
    for row, state in rows.items():
        item = FREE_ROWS[row]
        if state == "free":
            free |= BIT[item] | (BIT["AIRSHIP"] if row == "AIRSHIP" else 0)
            continue
        items.append(item)
        if state == "incentive":
            inc.add(item)
    items += OTHER_ITEMS
    if other == "incentive":
        inc.update(OTHER_ITEMS)
    items += list(gear)
    inc.update(gear)
    chests = {"standard": STANDARD_CHESTS, "wide": WIDE_CHESTS}[spots]
    locs = {k for k, l in enumerate(g.locations)
            if l.kind in ("npc", "shop") or (l.kind == "chest" and l.ident in chests)}
    return free, items, inc, locs



def vehicle_edges(g, ow):
    sx, sy = ow.pos["ship"]
    i = sx | (sy << 8)
    sea = ow.snode[ow.slabel[i]]
    return [(g.start, ow.sky, BIT["AIRSHIP"], "FFR: the airship flies from anywhere"),
            (g.start, sea, BIT["SHIP"], "FFR: the ship appears where it is found")]


class Placer:
    def __init__(self, g, ow, incentive_items=None, incentive_locs=None, free=0, items=None):
        self.g = g
        self.adj = analysis.adjacency(g, vehicle_edges(g, ow))
        locs = g.locations
        one_way = {m for m, n in enumerate(rd.MAP_NAMES) if n.startswith("ToFR")}

        def before_black_orb(l):
            return not all(g.nodes[n].kind == "sm" and rd.MAP_NAMES.index(g.nodes[n].where) in one_way
                           for n in l.nodes)

        self.pool = [k for k, l in enumerate(locs)
                     if (l.kind == "chest" and before_black_orb(l)) or l.kind == "shop"
                     or (l.kind == "npc" and l.ident not in FIXED_NPCS)]
        self.fixed = {k: BIT.get(l.reward, 0) for k, l in enumerate(locs) if k not in set(self.pool)}
        if incentive_locs is None:
            incentive_locs = {k for k in self.pool if locs[k].kind in ("npc", "shop")
                              or (locs[k].kind == "chest" and locs[k].ident in MAJOR_CHESTS)}
        self.incentive_locs = set(incentive_locs) & set(self.pool)
        self.items = list(items) if items is not None else KEY_ITEMS + NON_KEY_INCENTIVES
        self.incentives = set(incentive_items if incentive_items is not None else DEFAULT_INCENTIVES)
        self.free = free

    # --- the one query ----------------------------------------------------------
    def accessible(self, placed, extra=0):
        """Empty pool locations reachable once everything reachable is
        collected, owning `extra` as well."""
        g, locs = self.g, self.g.locations
        owned = self.free | extra
        while True:
            seen = analysis.reach(g, owned, self.adj)
            open_ = [k for k, l in enumerate(locs)
                     if not (l.req & ~owned) and any(n in seen for n in l.nodes)]
            gained = 0
            for k in open_:
                gained |= self.fixed.get(k, 0) | BIT.get(placed.get(k), 0)
            if not gained & ~owned:
                break
            owned |= gained
        pool = set(self.pool)
        return {k for k in open_ if k in pool and k not in placed}, owned

    # --- FFR's weighting ----------------------------------------------------------
    def weight(self, item, w, cycle, access):
        if access < MIN_ACCESS.get(item, 0) or cycle < MIN_CYCLES.get(item, 0):
            return 0.0
        if item not in KEY_ITEMS:
            return 0.0 if cycle < NON_KEY_MIN_CYCLE else w * NON_KEY_WEIGHT
        return w * EXCEPTION_WEIGHTS.get(item, 1.0)

    def bins(self, cands, b0, b1, b2, b3, b3red, cycle, access, key, edges):
        out = []
        lo, hi = edges
        for item, cnt in cands:
            c = cnt[key]
            if c < 0:
                out.append((self.weight(item, b0, cycle, access), item))
            elif c < lo:
                out.append((self.weight(item, b1, cycle, access), item))
            elif c < hi:
                out.append((self.weight(item, b2, cycle, access), item))
        w = b3
        for item, cnt in sorted((x for x in cands if x[1][key] >= hi), key=lambda x: x[1][key]):
            out.append((self.weight(item, w, cycle, access), item))
            w *= b3red
        return out

    def place(self, rng):
        for attempt in range(3):
            placed, ok = self._attempt(rng)
            if ok:
                return placed, attempt + 1
        return None, 3

    def _attempt(self, rng):
        incentives = set(self.incentives)
        nonincentives = [i for i in self.items if i not in incentives]
        inc_pool = [k for k in self.pool if k in self.incentive_locs]
        while len(incentives) > len(inc_pool):
            moved = rng.choice(sorted(incentives))
            incentives.discard(moved)
            nonincentives.append(moved)
        remaining = [i for i in self.items]
        keys = [i for i in remaining if i in KEY_ITEMS]
        placed = {}
        state = "normal"
        for cycle in range(1, 101):
            acc, owned = self.accessible(placed)
            inc_src = {k for k in acc if k in self.incentive_locs}
            non_src = acc - inc_src
            cands = []
            for item in keys:
                acc2, _ = self.accessible(placed, BIT[item])
                inc = len({k for k in acc2 if k in self.incentive_locs}) - len(inc_src)
                non = len(acc2) - len(inc_src) - inc - len(non_src)
                if item in incentives:
                    inc -= 1
                else:
                    non -= 1
                cands.append((item, {"inc": inc, "non": non}))
            if "SHIP" in keys and "CANAL" in keys:
                acc2, _ = self.accessible(placed, BIT["SHIP"] | BIT["CANAL"])
                inc = len({k for k in acc2 if k in self.incentive_locs}) - len(inc_src)
                non = len(acc2) - len(inc_src) - inc - len(non_src)
                for it in ("SHIP", "CANAL"):
                    if it in incentives:
                        inc -= 1
                    else:
                        non -= 1
                inc //= 2
                non //= 2
                for item, cnt in cands:
                    if item in ("SHIP", "CANAL"):
                        if cnt["inc"] < inc and len(inc_src) > 1:
                            cnt["inc"] = inc
                        if cnt["non"] < non and len(non_src) > 1:
                            cnt["non"] = non
            inc_items = [i for i in remaining if i in incentives]
            access = len(acc)
            if state == "incentive" or (state == "normal" and rng.randint(1, len(remaining)) <= len(inc_items)):
                cs = [c for c in cands if c[0] in incentives]
                nonkey = [i for i in remaining if i not in KEY_ITEMS and i in incentives]
                n = len(inc_src)
                if n <= 1 or (n <= CRIT_INC and "SHIP" in keys and "CANAL" in keys):
                    wc = self.bins(cs, 0.0, 0.5, 1.0, 1.0, 0.5, cycle, access, "inc", (1, 2))
                elif n <= SAFE_INC:
                    wc = self.bins(cs, 0.5, 0.5, 1.0, 0.5, 0.25, cycle, access, "inc", (1, 2))
                    wc += [(self.weight(i, 0.5, cycle, access), i) for i in nonkey]
                else:
                    wc = self.bins(cs, 1.0, 1.0, 1.0, 0.25, 0.25, cycle, access, "inc", (1, 2))
                    wc += [(self.weight(i, 1.0, cycle, access), i) for i in nonkey]
                if sum(w for w, _ in wc) == 0 and len(inc_items) <= n:
                    wc += [(1.0, i) for i in inc_items]
                if sum(w for w, _ in wc) == 0:
                    if cycle >= 15 and state != "normal":
                        return placed, False
                    state = "nonincentive"
                    continue
                where = sorted(inc_src)
            else:
                cs = [c for c in cands if c[0] not in incentives]
                nonkey = [i for i in remaining if i not in KEY_ITEMS and i not in incentives]
                n = len(non_src)
                if n <= CRIT_NON:
                    wc = self.bins(cs, 0.0, 0.5, 1.0, 1.0, 0.5, cycle, access, "non", (5, 20))
                elif n <= SAFE_NON:
                    wc = self.bins(cs, 0.5, 0.5, 1.0, 0.5, 0.25, cycle, access, "non", (5, 20))
                    wc += [(self.weight(i, 0.5, cycle, access), i) for i in nonkey]
                else:
                    wc = self.bins(cs, 1.0, 1.0, 1.0, 0.25, 0.25, cycle, access, "non", (5, 20))
                    wc += [(self.weight(i, 1.0, cycle, access), i) for i in nonkey]
                if sum(w for w, _ in wc) == 0:
                    if cycle >= 15 and state != "normal":
                        return placed, False
                    state = "incentive"
                    continue
                where = sorted(non_src)
            wc = [x for x in wc if x[0] > 0]
            rng.shuffle(wc)
            r = rng.random() * sum(w for w, _ in wc)
            item, s = wc[-1][1], 0.0
            for w, i in wc:
                s += w
                if r <= s:
                    item = i
                    break
            if item in incentives:
                where = sorted(inc_src)
            else:
                where = sorted(non_src)
            if not where:
                continue
            placed[rng.choice(where)] = item
            remaining.remove(item)
            if item in keys:
                keys.remove(item)
            state = "normal"
            if not remaining:
                break
        if remaining:
            return placed, False
        _, owned = self.accessible(placed)
        return placed, bool(owned & BIT["CHAOS"])


def apply(g, ow, placer, placed):
    """The graph as the seed plays: pool locations hand out what was put
    there and nothing else, and FFR's vehicle readings are real edges."""
    for k in placer.pool:
        g.locations[k].reward = placed.get(k)
    for e in vehicle_edges(g, ow):
        g.edge(*e)
