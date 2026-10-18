"""
ffr_oracle.py -- FFR's own, hand-maintained model of the vanilla world, read
out of its C# source (FF1Randomizer/FF1Lib/ItemLocations*.cs) as an
independent check on the graph.

FFR describes each location as a MapLocation; each MapLocation either has a
list of alternative overworld requirements (MapLocationRequirements, in
vehicles: Bridge, Ship, Canal, Canoe, Airship, Chime, TitanFed) or a parent
floor plus one AccessRequirement (MapLocationFloorRequirements).  Expanding
that gives, per chest, the minimal sets of things needed -- the same question
analysis.requirements() answers from the tiles.
"""
import os
import re

import romdata as rd
from model import BIT, ORBS

SRC = os.path.join(rd.ROOT, "FF1Randomizer", "FF1Lib", "ItemLocations.cs")

MAPCHANGE = {"Bridge": BIT["BRIDGE"], "Ship": BIT["SHIP"], "Canal": BIT["CANAL"],
             "TitanFed": BIT["RUBY"], "Canoe": BIT["CANOE"],
             "Airship": BIT["AIRSHIP"], "Chime": BIT["CHIME"], "None": 0}
COMBOS = {"AirshipAndCanoe": BIT["AIRSHIP"] | BIT["CANOE"],
          "CanalAndShip": BIT["CANAL"] | BIT["SHIP"],
          "ShipAndCanoe": BIT["CANOE"] | BIT["SHIP"]}
ACCESS = {"None": 0, "Key": BIT["KEY"], "Rod": BIT["ROD"], "Oxyale": BIT["OXYALE"],
          "Cube": BIT["CUBE"], "Bottle": BIT["BOTTLE"], "Lute": BIT["LUTE"],
          "Crown": BIT["CROWN"], "Crystal": BIT["CRYSTAL"], "Herb": BIT["HERB"],
          "Tnt": BIT["TNT"], "Adamant": BIT["ADAMANT"], "Slab": BIT["SLAB"],
          "Ruby": BIT["RUBY"], "EarthOrb": BIT["ORB_EARTH"], "FireOrb": BIT["ORB_FIRE"],
          "WaterOrb": BIT["ORB_WATER"], "AirOrb": BIT["ORB_AIR"],
          "BlackOrb": ORBS}


def _term(expr):
    m = 0
    for part in expr.split("|"):
        part = part.strip().replace("MapChange.", "")
        m |= COMBOS[part] if part in COMBOS else MAPCHANGE[part]
    return m


def load():
    src = open(SRC).read()
    chests = {}
    for m in re.finditer(r"TreasureChest\((0x[0-9A-F]+), nameof\((\w+)\), (MapLocation\.(\w+)|0), Item\.(\w+)(, isUnused: true)?\)", src):
        chests[int(m.group(1), 16) - 0x3100] = {
            "name": m.group(2), "maploc": m.group(4), "item": m.group(5),
            "unused": bool(m.group(6))}
    ow = {}
    block = src[src.index("MapLocationRequirements =>"):src.index("MapLocationFloorRequirements =>")]
    for m in re.finditer(r"\{MapLocation\.(\w+), new List<MapChange>\{([^}]*)\}\}", block):
        ow[m.group(1)] = [_term(t) for t in m.group(2).split(",") if t.strip()]
    floors = {}
    block = src[src.index("MapLocationFloorRequirements =>"):]
    for m in re.finditer(r"\{MapLocation\.(\w+), new Tuple<MapLocation, AccessRequirement>\(MapLocation\.(\w+), AccessRequirement\.(\w+)\)\}", block):
        floors[m.group(1)] = (m.group(2), ACCESS[m.group(3)])
    return chests, ow, floors


# FFR names for the graph's NPC and event locations.
NPC_ROUTINE = {"King": "Talk_KingConeria", "Princess2": "Talk_Princess2",
               "Matoya": "Talk_Matoya", "Bikke": "Talk_Bikke",
               "ElfPrince": "Talk_ElfPrince", "Astos": "Talk_Astos",
               "Sarda": "Talk_Sarda", "CanoeSage": "Talk_CanoeSage",
               "CubeBot": "Talk_CubeBot", "Fairy": "Talk_Fairy",
               "Lefein": "Talk_Chime", "Nerrick": "Talk_Nerrick", "Smith": "Talk_Smith"}
STATIC = {"LichReward": "earthorb", "KaryReward": "fireorb",
          "KrakenReward": "waterorb", "TiamatReward": "airorb", "ChaosReward": "Chaos"}


def load_others():
    """FFR's NPC rewards, fiend rewards and the caravan: name -> MapLocation."""
    src = open(SRC).read()
    out = {}
    for m in re.finditer(r"new NpcReward\(ObjectId\.(\w+), MapLocation\.(\w+), Item\.(\w+)", src):
        if m.group(1) in NPC_ROUTINE:
            out[("npc", NPC_ROUTINE[m.group(1)])] = (m.group(1), m.group(2))
    for m in re.finditer(r"new StaticItemLocation\(nameof\((\w+)\), MapLocation\.(\w+)", src):
        if m.group(1) in STATIC:
            kind = "event" if m.group(1) == "ChaosReward" else "altar"
            out[(kind, STATIC[m.group(1)])] = (m.group(1), m.group(2))
    m = re.search(r"CaravanItemShop1 =\s*new ItemShopSlot\(0x[0-9A-F]+, nameof\(\w+\), MapLocation\.(\w+)", src)
    out[("shop", "Caravan")] = ("CaravanItemShop1", m.group(1))
    return out


def maploc_requirements(maploc, ow, floors, _depth=0):
    """Minimal requirement masks for a MapLocation, FFR's way."""
    if maploc in ow:
        return ow[maploc]
    if maploc in floors and _depth < 40:
        parent, acc = floors[maploc]
        return [s | acc for s in maploc_requirements(parent, ow, floors, _depth + 1)]
    return None
