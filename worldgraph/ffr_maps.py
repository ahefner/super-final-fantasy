"""
ffr_maps.py -- FFR's alternate overworlds, as inputs to build.build().

An FFR map is a 256x256 tile grid plus a JSON of what moved with it
(MapExchange/OwMapExchangeData.cs):

  - StartingLocation, AirShipLocation, BridgeLocation, CanalLocation: tiles.
    When absent, FFR uses the vanilla start-up values, and so does this.
  - TeleporterFixups: Type 1 (Exit) entries move exit teleport Index to a new
    overworld tile.  The dungeons themselves are vanilla.
  - ShipLocations: where the ship appears, by TeleporterIndex -- the
    overworld entrance through which the SHIP was found (255 is the default).
    FFR's OverworldTeleportIndex is the ROM's entrance id.

The entrances need nothing: they are tiles in the map, and each tile type
carries its entrance id.
"""
import base64
import json
import os
import zipfile

import romdata as rd

MAPDIR = os.path.join(rd.ROOT, "FF1Randomizer", "FF1Lib", "maps")
PRAVOKA = 2             # OverworldTeleportIndex.Pravoka: where Bikke is


def load(name):
    """name is 'procgen1' (a .ffm/.json pair) or 'normal256/00CDC625'."""
    if "/" in name:
        pool, member = name.split("/")
        zf = zipfile.ZipFile(os.path.join(MAPDIR, pool + ".zip"))
        d = json.loads(zf.read(member + ".json"))
        tiles = b"".join(base64.b64decode(r) for r in d["DecompressedMapRows"])
    else:
        tiles = open(os.path.join(MAPDIR, name + ".ffm"), "rb").read()
        d = json.load(open(os.path.join(MAPDIR, name + ".json")))
    assert len(tiles) == 65536

    pos = dict(rd.VANILLA_POS)
    for key, field in (("start", "StartingLocation"), ("airship", "AirShipLocation"),
                       ("bridge", "BridgeLocation"), ("canal", "CanalLocation")):
        if d.get(field):
            pos[key] = (d[field]["X"], d[field]["Y"])
    ships = {s["TeleporterIndex"]: (s["X"], s["Y"]) for s in d.get("ShipLocations") or []}
    if PRAVOKA in ships or 255 in ships:
        pos["ship"] = ships.get(PRAVOKA, ships.get(255))

    exits = {}
    for f in d.get("TeleporterFixups") or []:
        if f["Type"] == 1 and f.get("Index") is not None:
            exits[f["Index"]] = (f["To"]["X"], f["To"]["Y"])
    return tiles, pos, exits, d


def pool_names(pool):
    zf = zipfile.ZipFile(os.path.join(MAPDIR, pool + ".zip"))
    return [pool + "/" + os.path.splitext(n)[0] for n in sorted(zf.namelist())]
