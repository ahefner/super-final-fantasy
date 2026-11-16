#!/usr/bin/env python3
"""
graphtables.py -- the world graph's tables as the cartridge holds them, for
every map of Map Select laid out alike.

The data is gengraph.py's: tools/graphdata.py for the game's map, and
maps/graph/KEY.py for each other (gengraph.py --map KEY).  The build lays
them out (genmaps.py, lay_out): gen/graph.inc, the constants, and for each
map gen/logic_N/graphdata.inc, its tables -- each table the room the most
any map's takes, so it is at one address whichever map's tables are loaded
(altmaps.inc's logic_ensure).  No worldgraph import: the build reads only
the data.
"""

def tables(D, ndocks=None):
    """The cartridge's copy of D: (constants, tables), each table (name,
    entries, word, pad, comments) -- pad the entry to fill with past its
    end when every map's tables are laid out alike (lay_out), "last" for a
    CSR offset table, whose fill is its last entry: an empty list.  Lists
    are CSR: an offset table one longer than the list it indexes (words),
    then the entries.  Coordinates are by index: a landing (map, x, y) or
    an exit's overworld (x, y).  ndocks: the docks a row of lut_GrEntWalk
    and lut_GrEntFly holds, the most any map has; the rest none."""
    lands = sorted(D["LAND"])
    lidx = {c: i for i, c in enumerate(lands)}
    exits = sorted(D["EXIT_TO"])
    xidx = {c: i for i, c in enumerate(exits)}
    N = D["NODES"]
    nd = ndocks or len(D["DOCKS"])
    consts, out = {}, []
    note = []

    def table(name, data, word=False, pad=0):
        out.append((name, list(data), word, pad, list(note)))
        note.clear()

    def csr(prefix, lists):
        off, flat = [0], []
        for l in lists:
            flat += l
            off.append(len(flat))
        table(prefix + "Off", off, word=True, pad="last")
        return flat

    consts["GR_NODES"] = N
    consts["GR_MASKS"] = len(D["MASKS"])
    consts["GR_LANDINGS"] = len(lands)
    consts["GR_EXITXY"] = len(exits)
    consts["GR_LOCS"] = len(D["LOC_NODES"]) + 1          # Chaos last
    consts["GR_DOCKS"] = nd
    note.append(";  The requirement masks, four bytes each, low first.")
    table("lut_GrMask", [b for m in D["MASKS"] for b in m.to_bytes(4, "little")])
    note.append(";  The map edit settings each holds under: every RANDO_OWEDITS bit of")
    note.append(";  the first set, none of the second (worldgraph/edited.py's cubes).")
    table("lut_GrCondOn", [on for on, _ in D["CONDS"]], word=True)
    table("lut_GrCondOff", [off for _, off in D["CONDS"]], word=True)
    by_src = [[] for _ in range(N)]
    for s_, d_, r in D["EDGES"]:
        by_src[s_].append((d_, r))
    note.append(";  Static edges by source: destination, requirement.")
    flat = csr("lut_GrEdge", [[d_ for d_, _ in l] for l in by_src])
    table("lut_GrEdgeDst", flat)
    table("lut_GrEdgeReq", [r for l in by_src for _, r in l])
    src = [[] for _ in range(N)]
    for e, n, r in D["ENT_SRC"]:
        src[n].append((0, e, r))
    for t, n, r, o in D["TELE_SRC"]:
        src[n].append((1 | (0x80 if o else 0), t, r))
    for x, n, r in D["EXIT_SRC"]:
        src[n].append((2, x, r))
    note.append(";  Wired sources by region: kind (0 entrance, 1 teleport, 2 exit; $80 the")
    note.append(";  CROWN waived by Early Ordeals), its id, its requirement.")
    csr("lut_GrSrc", [[k for k, _, _ in l] for l in src])
    table("lut_GrSrcKind", [k for l in src for k, _, _ in l])
    table("lut_GrSrcId", [i for l in src for _, i, _ in l])
    table("lut_GrSrcReq", [r for l in src for _, _, r in l])
    note.append(";  Landings: where each lands, as the game's tables hold it, and its regions.")
    table("lut_GrLandX", [c[1] for c in lands])
    table("lut_GrLandY", [c[2] for c in lands])
    table("lut_GrLandMap", [c[0] for c in lands])
    room = set(D["LAND_ROOM"])
    assert room <= set(lands), "an in-room destination no wiring lands on: %s" % sorted(room - set(lands))
    note.append(";  $80 for a landing inside a room (FFR's StandardInRoom), as bit 7 of its x.")
    table("lut_GrLandRoom", [0x80 if c in room else 0 for c in lands])
    table("lut_GrLandNodes", csr("lut_GrLand", [D["LAND"][c] for c in lands]))
    note.append(";  Exit coordinates: where on the overworld, and its regions there.")
    table("lut_GrExitX", [c[0] for c in exits])
    table("lut_GrExitY", [c[1] for c in exits])
    table("lut_GrExitNodes", csr("lut_GrExit", [D["EXIT_TO"][c] for c in exits]))
    note.append(";  The cartridge's locations, then Chaos: their regions and requirement --")
    note.append(";  and past Chaos's, the princess's event's at each of Rebellious")
    note.append(";  Princess's spots, where each starts in lut_GrLocNodes in lut_GrSaraOff.")
    flat = csr("lut_GrLoc", D["LOC_NODES"] + [D["CHAOS_NODES"]])
    soff = []
    for ns in D["SARA_NODES"]:
        soff.append(len(flat))
        flat = flat + ns
    soff.append(len(flat))
    table("lut_GrLocNodes", flat)
    table("lut_GrSaraOff", soff, word=True)
    table("lut_GrLocReq", D["LOC_REQ"] + [D["CHAOS_REQ"]])
    ents = sorted({e for e, _, _ in D["ENT_SRC"]})
    consts["GR_ENTIDS"] = len(ents)
    note.append(";  The entrances the overworld has, in order (es_roots).")
    table("lut_GrEntIds", ents)
    note.append(";  1 for a region of the overworld.")
    table("lut_GrOwNode", [1 if o else 0 for o in D["OW_NODE"]])
    note.append(";  The docks: where each is, a found ship moored there (give_vehicle);")
    note.append(";  their boarding regions; each entrance's distance to each, walking")
    note.append(";  ($FFFF none) and flying, entrance * GR_DOCKS + dock.  A map with fewer")
    note.append(";  than GR_DOCKS has the rest boarded from nowhere, under no settings,")
    note.append(";  never walked to and furthest flown.")
    table("lut_GrDockX", [xy[0] for _, xy in D["DOCKS"]])
    table("lut_GrDockY", [xy[1] for _, xy in D["DOCKS"]])
    table("lut_GrDockNodes", csr("lut_GrDock", D["DOCK_BOARD"] + [[] for _ in range(nd - len(D["DOCKS"]))]))
    note.append(";  The settings each is a dock under (Bridge to Lefein deletes Matoya's).")
    table("lut_GrDockCondOn", [on for on, _ in D["DOCK_COND"]] + [0xFFFF] * (nd - len(D["DOCKS"])), word=True)
    table("lut_GrDockCondOff", [off for _, off in D["DOCK_COND"]] + [0] * (nd - len(D["DOCKS"])), word=True)
    walk, fly = [], []
    for e in range(32):
        row = D["ENT_DOCK"].get(e, [(None, 0x7FFF)] * len(D["DOCKS"]))
        assert len(row) == len(D["DOCKS"]), "entrance %d's distances are to %d docks of %d" % (
            e, len(row), len(D["DOCKS"]))
        row = list(row) + [(None, 0x7FFF)] * (nd - len(row))
        walk += [0xFFFF if w is None else w for w, _ in row]
        fly += [f for _, f in row]
    table("lut_GrEntWalk", walk, word=True)
    table("lut_GrEntFly", fly, word=True)

    #  FFR's shuffle.
    recs = D["RECORDS"]
    locs = sorted({r[1] for r in recs})
    lnum = {l: i for i, l in enumerate(locs)}
    landed = D["LANDED"]
    note.append(";  FFR's shuffle: records, by index -- location id, landing, exit ($FF")
    note.append(";  none), the teleports out of it; and flags (1: Lefein or Melmond, which")
    note.append(";  never come first).")
    consts["ES_RECORDS"] = len(recs)
    consts["ES_LOCATIONS"] = len(locs)
    consts["ES_UNUSED1"] = D["UNUSED1"]
    nk = D["NOFLOATER_KEEP"]
    assert len(nk["titan"]) == 1 and len(nk["cardia"]) == 4 and len(nk["cardia_dock"]) == 2
    consts["ES_KEEP_TITAN"] = nk["titan"][0]
    consts["ES_SEASHRINE1"] = D["SEASHRINE1"]
    consts["ES_LOC_TITANEAST"] = lnum["TitansTunnelEast"]
    consts["ES_LOC_TITANWEST"] = lnum["TitansTunnelWest"]
    table("lut_EsRecLoc", [lnum[r[1]] for r in recs])
    table("lut_EsRecLand", [lidx[landed[i]] if i in landed else 0xFF for i in range(len(recs))])
    table("lut_EsRecExit", [0xFF if r[3] is None else r[3] for r in recs])
    table("lut_EsRecFlags", [1 if r[0] in ("Lefein", "Melmond") else 0 for r in recs])
    table("lut_EsRecTeles", csr("lut_EsRecTele", [r[2] for r in recs]))
    table("lut_EsEnter", [D["ENTER"].get(e, 0xFF) for e in range(32)])
    table("lut_EsTele", [D["TELE"].get(t, 0xFF) for t in range(64)])
    for name in ("towns", "top", "free_ow", "free_sm", "icecave_loop", "vanilla_ow", "vanilla_sm"):
        lab = "lut_Es" + "".join(w.capitalize() for w in name.split("_"))
        consts["ES_" + name.upper() + "_N"] = len(D["LISTS"][name])
        table(lab, D["LISTS"][name])
    table("lut_EsOwCoord", [xidx[D["OW_COORDS"][e]] if e in D["OW_COORDS"] else 0xFF for e in range(32)])
    note.append(";  ...and under the Cardia Land Bridge, which moves six of them.")
    note.append(";  FFR's keepers with the FLOATER removed: Cardia's four, then the first and")
    note.append(";  Bahamut's (ES_KEEP_TITAN apart).")
    table("lut_EsKeepCardia", nk["cardia"] + nk["cardia_dock"])
    table("lut_EsOwCoordCardia", [xidx[D["OW_COORDS_CARDIA"][e]] if e in D["OW_COORDS_CARDIA"] else 0xFF
                                  for e in range(32)])
    #  The sanity check's sets: locations as a bitset over location ids,
    #  entrances as a 32-bit mask.

    def bits(ids, n):
        v = 0
        for i in ids:
            v |= 1 << i
        return list(v.to_bytes(n, "little"))
    nb = (len(locs) + 7) // 8
    table("lut_EsStarter", bits([lnum[l] for l in D["STARTER"] if l in lnum], nb))
    table("lut_EsSafe", bits([lnum[l] for l in D["SAFE"] if l in lnum], nb))
    table("lut_EsConnected", bits(D["CONNECTED"], 4))
    table("lut_EsStarting", bits(D["STARTING"], 4))
    table("lut_EsDanger", D["DANGER"])
    note.append(";  The vanilla wiring, as landings and exit coordinates.")
    table("lut_EsVanEnt", [lidx[c] for c in D["VANILLA_ENTRANCE"]])
    table("lut_EsVanNorm", [lidx[c] for c in D["VANILLA_NORMAL"]])
    table("lut_EsVanExit", [xidx[c] for c in D["VANILLA_EXIT"]])
    return consts, out


#  The constants a map may have more or fewer of: the tables are laid out
#  for the most any map has.  The rest are the same for every map.
GROWS = ("GR_NODES", "GR_MASKS", "GR_LANDINGS", "GR_EXITXY", "GR_DOCKS")
HEAD = [";  Generated by tools/gengraph.py from worldgraph/ -- do not edit.",
        ";  The world graph without its wiring, and FFR's entrance shuffle data;",
        ";  see gengraph.py.  Regions number from 0, the start.", ""]


def lay_out(Ds):
    """Every map's tables, laid out alike: (graph.inc's lines, each map's
    graphdata.inc's lines).  A table takes the room the most any map's
    takes, the rest filled (tables' pad), so each table is at one address
    whichever map's is loaded; a constant that grows is the most, the
    others the same for every map."""
    ndocks = max(len(D["DOCKS"]) for D in Ds)
    each = [tables(D, ndocks) for D in Ds]
    consts = {}
    for c, _ in each:
        for k, v in c.items():
            if k in GROWS:
                consts[k] = max(consts.get(k, 0), v)
            else:
                assert consts.setdefault(k, v) == v, ("%s differs between maps" % k, consts[k], v)
    sizes = {}
    for _, ts in each:
        for name, data, word, pad, _ in ts:
            sizes[name] = max(sizes.get(name, 0), len(data))
    incs = []
    for _, ts in each:
        lines = list(HEAD)
        for name, data, word, pad, note in ts:
            lines += note
            fill = data[-1] if pad == "last" and data else (0 if pad == "last" else pad)
            data = data + [fill] * (sizes[name] - len(data))
            lines.append("%s:" % name)
            step = 8 if word else 16
            for i in range(0, len(data), step):
                chunk = data[i:i + step]
                if word:
                    lines.append("  .WORD %s" % ", ".join("$%04X" % (v & 0xFFFF) for v in chunk))
                else:
                    lines.append("  .BYTE %s" % ", ".join("$%02X" % (v & 0xFF) for v in chunk))
            if not data:
                lines.append("  ; (empty)")
            lines.append("")
        incs.append(lines)
    clines = list(HEAD)
    for k, v in consts.items():
        clines.append("%-16s = %d" % (k, v))
    clines.append("")
    names = [name for name, *_ in each[0][1]]
    for i in range(0, len(names), 4):
        clines.append(".global %s" % ", ".join(names[i:i + 4]))
    return clines, incs


