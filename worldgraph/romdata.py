"""
romdata.py -- the game's world data, read out of the built port.

Everything here is vanilla FF1 data at the addresses Disch's disassembly names
(game/Constants.inc).  The built ROM is the source because it is one file with
everything in it; NES bank N sits at image offset (N+1)*$10000 + $8000.  The
talk-routine table is parsed from the vanilla source instead, because there it
has names.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
#  The tree this lives in (snes/worldgraph since 2026-10-18), and where
#  FF1Randomizer/, FFR's source, sits: beside the tree, or FFR_ROOT, for a
#  copy of the tree made elsewhere (tools/mutate.py's).
SNES = os.path.dirname(HERE)
ROOT = os.environ.get("FFR_ROOT") or os.path.dirname(SNES)
ROM_PATH = os.path.join(SNES, "SuperFinalFantasy.sfc")

_rom = None


def rom():
    global _rom
    if _rom is None:
        _rom = open(ROM_PATH, "rb").read()
    return _rom


def nesbank(n):
    o = (n + 1) * 0x10000 + 0x8000
    return rom()[o:o + 0x4000]


def bank0(addr, size):
    """Bytes at a CPU address in NES bank $00 (BANK_OWINFO, _SMINFO, ...)."""
    o = addr - 0x8000
    return nesbank(0)[o:o + size]


# --- the overworld --------------------------------------------------------------

OW_PROPS = bank0(0x8000, 0x100)        # lut_OWTileset: 2 bytes per tile type

OWP_FOOT, OWP_CANOE, OWP_SHIP, OWP_NOLAND = 0x01, 0x02, 0x04, 0x08   # set = forbidden
OWP_FOREST, OWP_DOCK = 0x10, 0x20
OWP_SPEC_MASK = 0xC0
OWP_CHIME, OWP_CARAVAN, OWP_FLOATER = 0x40, 0x80, 0xC0


def ow_prop(t):
    return OW_PROPS[(t & 0x7F) * 2], OW_PROPS[(t & 0x7F) * 2 + 1]


def decode_rle(src, off, count):
    """The game's RLE (DecompressMap): $00-$7F one tile, $80-$FE tile+length
    (0 = 256), $FF ends.  Returns exactly `count` tiles or raises."""
    out = []
    while src[off] != 0xFF:
        b = src[off]
        if b < 0x80:
            out.append(b)
            off += 1
        else:
            n = src[off + 1] or 256
            out += [b & 0x7F] * n
            off += 2
    if len(out) != count:
        raise ValueError("row decodes to %d tiles, expected %d" % (len(out), count))
    return out


def vanilla_overworld():
    """256x256 tile ids, row-major, from bank $01."""
    b1 = nesbank(1)
    tiles = []
    for r in range(256):
        p = b1[r * 2] | (b1[r * 2 + 1] << 8)
        tiles += decode_rle(b1, p - 0x8000, 256)
    return bytes(tiles)


# lut_InitUnsramFirstPage: where the vehicles, bridge and canal start, and the
# party's scroll (the party stands at scroll + 7).
_INIT = bank0(0xB000, 0x100)
VANILLA_POS = {
    "start":   (_INIT[0x10] + 7, _INIT[0x11] + 7),
    "ship":    (_INIT[0x01], _INIT[0x02]),
    "airship": (_INIT[0x05], _INIT[0x06]),
    "bridge":  (_INIT[0x09], _INIT[0x0A]),
    "canal":   (_INIT[0x0D], _INIT[0x0E]),
}

# --- teleports -------------------------------------------------------------------

_ENTR = [bank0(0xAC00, 32), bank0(0xAC20, 32), bank0(0xAC40, 32)]
_EXIT = [bank0(0xAC60, 16), bank0(0xAC70, 16)]
_NORM = [bank0(0xAD00, 64), bank0(0xAD40, 64), bank0(0xAD80, 64)]
TILESET_OF_MAP = bank0(0xACC0, 64)     # lut_Tilesets


def entrance(i):
    """Overworld entrance teleport i -> (map, x, y) where the party lands."""
    return _ENTR[2][i], _ENTR[0][i] & 0x3F, _ENTR[1][i] & 0x3F


def normal_tele(i):
    return _NORM[2][i], _NORM[0][i] & 0x3F, _NORM[1][i] & 0x3F


def exit_tele(i):
    """Exit teleport i -> overworld (x, y) where the party lands."""
    return _EXIT[0][i], _EXIT[1][i]

# --- standard maps ---------------------------------------------------------------

MAP_COUNT = 61
MAP_NAMES = [   # FFR's MapIndex enum (FF1Lib/Enums.cs), which follows the ROM
    "ConeriaTown", "Pravoka", "Elfland", "Melmond", "CrescentLake", "Gaia",
    "Onrac", "Lefein", "ConeriaCastle1F", "ElflandCastle", "NorthwestCastle",
    "CastleOrdeals1F", "TempleOfFiends", "EarthCaveB1", "GurguVolcanoB1",
    "IceCaveB1", "Cardia", "BahamutCaveB1", "Waterfall", "DwarfCave",
    "MatoyasCave", "SardasCave", "MarshCaveB1", "MirageTower1F",
    "ConeriaCastle2F", "CastleOrdeals2F", "CastleOrdeals3F", "MarshCaveB2",
    "MarshCaveB3", "EarthCaveB2", "EarthCaveB3", "EarthCaveB4", "EarthCaveB5",
    "GurguVolcanoB2", "GurguVolcanoB3", "GurguVolcanoB4", "GurguVolcanoB5",
    "IceCaveB2", "IceCaveB3", "BahamutCaveB2", "MirageTower2F",
    "MirageTower3F", "SeaShrineB5", "SeaShrineB4", "SeaShrineB3",
    "SeaShrineB2", "SeaShrineB1", "SkyPalace1F", "SkyPalace2F",
    "SkyPalace3F", "SkyPalace4F", "SkyPalace5F", "ToFR1F", "ToFR2F",
    "ToFR3F", "ToFREarth", "ToFRFire", "ToFRWater", "ToFRAir", "ToFRChaos",
    "TitansTunnel",
]

# Standard-map tile properties (Constants.inc)
TP_NOMOVE = 0x01
TP_SPEC_MASK = 0x1E
TP_TELE_MASK = 0xC0
TP_TELE_EXIT, TP_TELE_NORM, TP_TELE_WARP = 0xC0, 0x80, 0x40
SPEC = {
    0x02: "door", 0x04: "locked", 0x06: "closeroom", 0x08: "treasure",
    0x0A: "battle", 0x0C: "damage", 0x0E: "crown", 0x10: "cube",
    0x12: "4orbs", 0x14: "userod", 0x16: "uselute", 0x18: "earthorb",
    0x1A: "fireorb", 0x1C: "waterorb", 0x1E: "airorb",
}

_SMPROPS = bank0(0x8800, 0x800)        # lut_SMTilesetProp: 8 tilesets x 128 x 2


def sm_prop(tileset, t):
    o = tileset * 256 + (t & 0x7F) * 2
    return _SMPROPS[o], _SMPROPS[o + 1]


def standard_map(m):
    """64x64 tile ids for standard map m.  The pointer table is at the start
    of bank $04 and maps run on through $05-$07; a pointer's top two bits pick
    the bank, which makes it a plain offset into the four banks together."""
    banks = b"".join(nesbank(n) for n in (4, 5, 6, 7))
    p = banks[m * 2] | (banks[m * 2 + 1] << 8)
    return bytes(decode_rle(banks, p, 4096))

# --- objects ---------------------------------------------------------------------

INIT_GAME_FLAGS = bank0(0xAF00, 256)   # lut_InitGameFlags: bit 0 = object visible
_MAPOBJ = bank0(0xB400, MAP_COUNT * 0x30)

OBJ_INROOM, OBJ_STATIONARY = 0x80, 0x40


def map_objects(m):
    """The 15 object slots of map m: (id, x, y, flags), skipping empty ones."""
    out = []
    for s in range(15):
        o = m * 0x30 + s * 3
        oid, xf, y = _MAPOBJ[o], _MAPOBJ[o + 1], _MAPOBJ[o + 2]
        if oid:
            out.append((oid, xf & 0x3F, y & 0x3F, xf & 0xC0))
    return out


def talk_routines():
    """Object id -> talk routine name, from lut_MapObjTalkJumpTbl in the
    vanilla source (bank $0E).  Names matter here: the routine is what decides
    whether an object can ever leave its tile."""
    src = open(os.path.join(SNES, "game", "bank_0E.asm")).read()
    i = src.index("lut_MapObjTalkJumpTbl:")
    names = []
    for line in src[i:].splitlines()[1:]:
        code = line.split(";")[0].strip()
        if code.startswith(".WORD"):
            names += [w.strip() for w in code[5:].split(",") if w.strip()]
        elif names and code and not code.startswith(".WORD"):
            break
    #  The table stops at $CF: no object id above that exists.
    assert len(names) == 0xD0, len(names)
    return names + [None] * (256 - len(names))

# --- treasure --------------------------------------------------------------------

TREASURE = bank0(0xB100, 256)          # lut_Treasure: chest id -> item id

ITEM_NAMES = ["", "LUTE", "CROWN", "CRYSTAL", "HERB", "KEY", "TNT", "ADAMANT",
              "SLAB", "RUBY", "ROD", "FLOATER", "CHIME", "TAIL", "CUBE",
              "BOTTLE", "OXYALE"]       # item ids $01-$10, items+N in variables.inc
