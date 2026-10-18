"""
wiring.py -- where every teleport leads: the three tables entrance and floor
shuffle rewrite, as data the graph is built from (build.build(wiring=...)).

  Wiring.vanilla()       the ROM's tables
  w.entrance[eid]        overworld entrance 0-31 -> (map, x, y)
  w.normal[tid]          normal teleport 0-63    -> (map, x, y)
  w.exits[xid]           exit teleport 0-15      -> overworld (x, y)

  fe_shuffle(rng, ...)   FFR's ShuffleEntrancesAndFloors (EntrancesFloors
                         Shuffle.cs), ported onto these tables.  Its
                         destinations are FFR's own records (ffr_teleports),
                         landing where the ROM says they land.

The port follows FFR line by line where it matters for the result: the lists
it draws from, the dead ends it sets aside for forks, the order it fills
entrances and then each chain's teleports, and its sanity check.  Left out:
the flags for a removed floater, alternate overworlds, deep castles and deep
towns.
"""
import random

import ffr_teleports as ft
import romdata as rd


class Wiring:
    def __init__(self, entrance, normal, exits, log=None, chains=None):
        self.entrance = dict(entrance)
        self.normal = dict(normal)
        self.exits = dict(exits)
        self.log = log or []
        self.chains = chains or {}      # entrance id -> [(teleport id, depth)]

    @classmethod
    def vanilla(cls):
        return cls({e: rd.entrance(e) for e in range(32)},
                   {t: rd.normal_tele(t) for t in range(64)},
                   {x: rd.exit_tele(x) for x in range(16)})


_model = None


def model():
    global _model
    if _model is None:
        _model = ft.load()
    return _model


# --- FFR's sanity check (CheckEntranceSanity) --------------------------------
STARTER_DESTINATIONS = {"TempleOfFiends1", "Cardia6", "Cardia4", "Cardia2", "MatoyasCave",
                        "DwarfCave", "SeaShrineMermaids"}
SAFE_LOCATIONS = {"IceCave3", "GurguVolcano4", "GurguVolcano5", "SeaShrine5", "SeaShrine6",
                  "BahamutCave1", "BahamutCave2", "ElflandCastle", "NorthwestCastle",
                  "ConeriaCastle1", "SardasCave", "Cardia1", "Cardia5", "Coneria", "Pravoka",
                  "Elfland", "Melmond", "CrescentLake", "Gaia", "Onrac", "Lefein"} | STARTER_DESTINATIONS
CONNECTED = {"ConeriaCastle1", "Coneria", "TempleOfFiends1", "MatoyasCave", "Pravoka",
             "ElflandCastle", "Elfland", "NorthwestCastle", "MarshCave1", "Melmond",
             "EarthCave1", "TitansTunnelEast", "SardasCave", "TitansTunnelWest", "Cardia1",
             "BahamutCave1", "GurguVolcano1", "IceCave1", "Onrac"}
STARTING = {"Coneria", "ConeriaCastle1", "TempleOfFiends1"}


def _sane(shuffled, allow_danger):
    starter = any(o in STARTING and r.location in STARTER_DESTINATIONS for o, r in shuffled.items())
    titans = (any(r.location == "TitansTunnelEast" and o in CONNECTED for o, r in shuffled.items()) and
              any(r.location == "TitansTunnelWest" and o in CONNECTED for o, r in shuffled.items()))
    danger = 6 - sum(1 for o in ("Coneria", "ConeriaCastle1", "TempleOfFiends1", "DwarfCave",
                                 "MatoyasCave", "Pravoka")
                     if o in shuffled and shuffled[o].location in SAFE_LOCATIONS)
    return titans and (allow_danger or (starter and danger <= 3))


def fe_shuffle(seed, towns=True, entrances=True, floors=True, mixed=False,
               dead_ends=True, include_coneria=True, unsafe_start=False):
    """One FFR-style entrance and floor shuffle.  Returns a Wiring.  Entrances
    without floors keeps every floor's links but the Sea Shrine's from Onrac,
    as FFR does; floors without entrances is not FFR's, and not here."""
    if not entrances:
        raise NotImplementedError("FFR shuffles floors only with entrances")
    m = model()
    #  A seed, or anything that shuffles and picks as random.Random does --
    #  the cartridge's draws, to hold its port to this (snes/tools/checkentrance.py).
    rng = seed if hasattr(seed, "shuffle") else random.Random(seed)
    rec = m.records

    #  Every record lands where the ROM says its index lands (FFR's LoadData
    #  overwrites its own coordinates the same way).
    land = {}
    for o, name in m.enter.items():
        land[name] = rd.entrance(m.owti[o])
    for t, name in m.tele.items():
        land[name] = rd.normal_tele(m.tidx[t])

    vanilla_ow = {o: rec[m.enter[o]] for o in m.lists["vanilla_ow"]}
    vanilla_sm = {t: rec[m.tele[t]] for t in m.lists["vanilla_sm"]}
    placed_maps = dict(vanilla_ow)
    placed_floors = dict(vanilla_sm)
    town_names = ["Pravoka", "Elfland", "Melmond", "CrescentLake", "Onrac", "Gaia", "Lefein"]
    if towns:
        if include_coneria:
            placed_maps.pop("Coneria", None)
        for t in town_names:
            placed_maps.pop(t, None)
    if entrances:
        keepers = [o for o in vanilla_ow if 1 <= m.owti[o] <= 8]       # Coneria..Lefein
        if not dead_ends:
            keepers += ["Cardia1", "Cardia5"]
        placed_maps = {o: r for o, r in placed_maps.items() if o in keepers}
        placed_floors.pop("SeaShrine1", None)
    if floors and entrances:
        placed_floors = {t: rec[m.tele[t]] for t in m.lists["icecave_loop"]}

    #  FFR compares destinations by MapLocation, not by record: IceCave5 and
    #  IceCave7 share one.
    placed_dest = {r.location for r in placed_maps.values()} | {r.location for r in placed_floors.values()}
    town_ents = m.lists["towns"]
    nontown_ents = [o for o, i in sorted(m.owti.items(), key=lambda kv: kv[1])
                    if o not in town_ents and i < m.owti["Unused1"]]
    shuffled_ow_count = (sum(1 for o in town_ents if o not in placed_maps) +
                         sum(1 for o in nontown_ents if o not in placed_maps))

    def recs(names):
        return [rec[n] for n in names if rec[n].location not in placed_dest]

    towns_l = recs(m.enter[o] for o in town_ents)
    top = recs(m.enter[o] for o in m.lists["top"])
    sub = recs([m.enter[o] for o in m.lists["free_ow"]] + [m.tele[t] for t in m.lists["free_sm"]])
    dead = []

    rng.shuffle(towns_l)
    while towns_l and towns_l[0].name in ("Lefein", "Melmond"):
        towns_l.append(towns_l.pop(0))
    rng.shuffle(top)
    rng.shuffle(sub)
    forks = sum(len(r.teleports) - 1 for r in sub if len(r.teleports) > 1) + (1 if sub else 0)
    for _ in range(forks):
        k = next(i for i, r in enumerate(sub) if not r.teleports)
        dead.append(sub.pop(k))
    rng.shuffle(sub)
    rng.shuffle(dead)
    dests = towns_l + top + sub + dead

    for attempt in range(1, 101):
        i = j = 0
        shuffled, floors_out, exits_out, chains = {}, {}, {}, {}
        s_towns, s_ents = list(town_ents), list(nontown_ents)
        if mixed:
            removed = not unsafe_start and "Coneria" in s_towns
            if removed:
                s_towns.remove("Coneria")
            s_ents = s_towns + s_ents
            rng.shuffle(s_ents)
            if removed:
                s_ents.insert(0, "Coneria")
        else:
            rng.shuffle(s_towns)
            rng.shuffle(s_ents)
            s_ents = s_towns + s_ents
        for o in s_ents:
            if o in placed_maps:
                d = placed_maps[o]
            else:
                d, i = dests[i], i + 1
            shuffled[o] = d
            if d.exit:
                exits_out[d.exit] = m.ow_coords[o]
            pending = [(t, 1) for t in d.teleports]
            chain = chains.setdefault(o, [])
            while pending:
                t, depth = pending.pop(rng.randrange(len(pending)))
                if t in placed_floors:
                    f = placed_floors[t]
                else:
                    f, j = dests[shuffled_ow_count + j], j + 1
                pending += [(u, depth + 1) for u in f.teleports]
                floors_out[t] = f
                chain.append((t, depth))
                if f.exit:
                    exits_out[f.exit] = m.ow_coords[o]
        if _sane(shuffled, unsafe_start):
            break
    else:
        raise RuntimeError("FFR's sanity check failed 100 times")

    w = Wiring.vanilla()
    log = ["sanity passed on attempt %d" % attempt]
    for o, d in shuffled.items():
        w.entrance[m.owti[o]] = land[d.name]
        log.append("%-18s -> %s" % (o, d.name))
    for t, f in floors_out.items():
        w.normal[m.tidx[t]] = land[f.name]
        log.append("    %-18s -> %s" % (t, f.name))
    for x, xy in exits_out.items():
        w.exits[m.xidx[x]] = xy
    w.log = log
    w.chains = {m.owti[o]: [(m.tidx[t], d) for t, d in c] for o, c in chains.items()}
    w.dealt = {land[d.name] for d in shuffled.values()} | {land[f.name] for f in floors_out.values()}
    w.exit_roots = {m.xidx[x]: xy for x, xy in exits_out.items()}
    return w
