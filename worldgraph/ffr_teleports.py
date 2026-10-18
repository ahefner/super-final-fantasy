"""
ffr_teleports.py -- FFR's model of where teleports lead, read out of its C#
source (FF1Lib/Teleporters.cs, Enums.cs), for the entrance and floor shuffle.

FFR's unit is a *destination*: a landing point in one region of a map, plus
the teleports out of that region that the shuffle may deal (`Teleports`) and
the exit it holds (`Exit`).  The outgoing lists are kept by hand, and what
they leave out is what FFR pins: the Temple of Fiends lists no teleports, so
the ToFR link is never dealt; Coneria Castle 1F and Ordeals 1F list only
their exits, so 2F and the maze stay vanilla.

  load()  -> Model: the records, the index -> record mappings, the enums, and
             the lists the shuffle draws on.
"""
import os
import re
from collections import namedtuple

import romdata as rd

FFR = os.path.join(rd.ROOT, "FF1Randomizer", "FF1Lib")

Record = namedtuple("Record", "name location map x y inroom teleports exit")
Model = namedtuple("Model", "records enter tele exitmap owti tidx xidx mapidx lists ow_coords")


def _enum(src, name):
    body = src[src.index("enum %s" % name):]
    body = body[body.index("{") + 1:body.index("}")]
    out = {}
    for m in re.finditer(r"(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)", body):
        out[m.group(1)] = int(m.group(2), 0)
    return out


def _list(src, name, kind):
    m = re.search(r"%s\s*=\s*(?:new\(\)|new List<%s>(?:\(\))?)\s*\{([^}]*)\}" % (name, kind), src)
    if not m:
        m = re.search(r"%s\s*=>\s*new List<%s>\s*\{([^}]*)\}" % (name, kind), src)
    return re.findall(r"%s\.(\w+)" % kind, m.group(1))


def load():
    tsrc = open(os.path.join(FFR, "Teleporters.cs"), encoding="utf-8-sig").read()
    esrc = open(os.path.join(FFR, "Enums.cs"), encoding="utf-8-sig").read()
    owti = _enum(esrc, "OverworldTeleportIndex")
    tidx = _enum(esrc, "TeleportIndex")
    xidx = _enum(esrc, "ExitTeleportIndex")
    mapidx = _enum(esrc, "MapIndex")

    body = tsrc[tsrc.index("public static class TeleportersList"):]
    records = {}
    pat = re.compile(
        r"public static TeleportDestination (\w+) = new TeleportDestination\("
        r"MapLocation\.(\w+), MapIndex\.(\w+), new Coordinate\((\d+), (\d+), CoordinateLocale\.(\w+)\)"
        r"(?:, (?:TeleportIndex\.(\w+)|new List<TeleportIndex> \{([^}]*)\}|ExitTeleportIndex\.(\w+)))?\)")
    for m in pat.finditer(body):
        name, loc, mp, x, y, locale, one, many, ex = m.groups()
        tele = [one] if one else re.findall(r"TeleportIndex\.(\w+)", many) if many else []
        records[name] = Record(name, loc, mapidx[mp], int(x), int(y), locale == "StandardInRoom",
                               tuple(tele), ex)

    def mapping(name, kind):
        blk = tsrc[tsrc.index("Dictionary<%s, string> %s" % (kind, name)):]
        blk = blk[:blk.index("};")]
        return {k: v for k, v in re.findall(r"\{%s\.(\w+), \"(\w+)\"\}" % kind, blk)}

    enter = mapping("EnterMapping", "OverworldTeleportIndex")
    tele = mapping("TeleMapping", "TeleportIndex")
    exitmap = mapping("ExitMapping", "ExitTeleportIndex")

    lists = {
        "towns": _list(tsrc, "TownEntrances", "OverworldTeleportIndex"),
        "top": _list(tsrc, "NonTownForcedTopFloorsIndex", "OverworldTeleportIndex"),
        "free_ow": _list(tsrc, "FreePlacementFloorsOw", "OverworldTeleportIndex"),
        "free_sm": _list(tsrc, "FreePlacementFloorsSm", "TeleportIndex"),
        "icecave_loop": _list(tsrc, "IceCaveLoopTeleList", "TeleportIndex"),
        "vanilla_ow": _list(tsrc, "VanillaOverworldTeleList", "OverworldTeleportIndex"),
        "vanilla_sm": _list(tsrc, "VanillaStandardTeleList", "TeleportIndex"),
    }

    blk = tsrc[tsrc.index("Dictionary<OverworldTeleportIndex, Coordinate> VanillaOverworldCoordinates"):]
    blk = blk[:blk.index("};")]
    ow_coords = {k: (int(x), int(y)) for k, x, y in
                 re.findall(r"\{OverworldTeleportIndex\.(\w+),\s*new Coordinate\((\d+), (\d+)", blk)}
    return Model(records, enter, tele, exitmap, owti, tidx, xidx, mapidx, lists, ow_coords)


def check_against_rom(model, rd):
    """FFR's records against the ROM's own tables: every mapped entrance and
    teleport lands where its record says.  Returns a list of mismatches."""
    bad = []
    for ow, name in model.enter.items():
        r = model.records[name]
        got = rd.entrance(model.owti[ow])
        if got != (r.map, r.x, r.y):
            bad.append(("entrance", ow, got, (r.map, r.x, r.y)))
    for t, name in model.tele.items():
        r = model.records[name]
        got = rd.normal_tele(model.tidx[t])
        if got != (r.map, r.x, r.y):
            bad.append(("teleport", t, got, (r.map, r.x, r.y)))
    return bad


if __name__ == "__main__":
    import romdata as rd
    m = load()
    print("%d records, %d entrances, %d teleports, %d exits mapped" %
          (len(m.records), len(m.enter), len(m.tele), len(m.exitmap)))
    for k, v in m.lists.items():
        print("  %-12s %d" % (k, len(v)))
    bad = check_against_rom(m, rd)
    print("against the ROM:", "all agree" if not bad else bad)
