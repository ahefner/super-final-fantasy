#!/usr/bin/env python3
"""
genmaps.py -- the overworld maps Map Select offers, and what the game needs
to play each (user, 2026-11-15).

    gen/maps.inc       Map Select's (mapselect.inc, CHUNK_OWS): the names,
                       the minimaps' long addresses, the starts
    gen/mapdata.inc    the game's (altmaps.inc, CHUNK_WORLD; fun.asm): where
                       each map's record is (MAPINFOFAR), its layout (MI_*)
    gen/mapdlg.inc     Mirror World's dialogue lines (altmaps.inc)
    gen/mapbridge.inc  FUN%'s CHR overlay (fun.asm): the bridge drawn across
                       a horizontal strait, as FFR draws it
    gen/graph.inc, gen/logic_N/graphdata.inc
                       each map's world graph, for key item placement and
                       Map shuffle on it (write_logic), and where each map's
                       logic chunk goes (out/logic_slots.txt)
    out/maps_XX.bin    the data, in chunks' low halves (mkrom.py's LOWHALF):
                       the minimaps, the records, each map's rows

maps/custom-maps.txt lists the maps in the order the screen shows them: the
game's map first, then any of "mirror-lr" (the game's map mirrored left to
right) and maps drawn in maps/ (ffm_map), each with the name the screen
shows.  A drawn map is two files: STEM.ffm, its 65,536 tiles one byte each,
FFR's and FFHackster's format, so either can edit it; and STEM.toml, the
places the tiles do not show -- the start, Bikke's ship, the airship, the
bridge, the canal and the docks.  The rest follows from the tiles, as FFR's
map generator works it out (procgen/NewOverworld.cs): where each entrance
is, the exits' landings, which way the bridge runs, and each zone's
encounters.  One of FFR's maps becomes a pair with

    python3 tools/genmaps.py --import normal256 1EAA7BA6 long-march

from ../FF1Randomizer/FF1Lib/maps/, checked against what FFR's file says.

A map's record, 256 bytes (MI_*): where its rows are; its flags (the bridge
horizontal, the map a mirror); the start, the party's tile; where Bikke's
ship waits, the airship, the bridge and the canal, as lut_InitUnsramFirstPage
has the game's; where a Free SHIP waits; the zones the zone pass leaves
alone, those that take Coneria's encounters; each of the overworld's 64
zones' formations, as the zone they are taken from; its minimap's layout;
and its logic chunk.  Its exits and the docks a found ship moors at are its
world graph's (gengraph.py --map; write_logic).  The game's map's record is
the game's, for the tests; the game reads bank $01's map and the game's
tables for it.

A map's minimap layout (MI_MM; mm_layout): the minimap draws each 8 x 8
block of the map into the tile of its number and shows the blocks through
a nametable, lending the tiles of blocks of open sea to the logo and the
crests (genowedits.py).  Each map lends tiles of its open sea.

A map's rows are the game's format (DecompressMap): a tile below $80, or $80
plus a tile and a count (0 for 256), $FF ending the row; 256 rows, each a
16-bit address, in one chunk's low half with them.  The minimap is the map
edit screen's (genows.baked), 8KB.

Mirror World is the game's map mirrored left to right (mirror_lr): every
terrain piece by its mirror -- a forest's west edge for its east, and so on,
so the coasts and ridges are drawn as before, facing the other way -- the
docks and the towns' walls by theirs, the houses, caves and Cardia's holes
as they are; and the castles, the Temple of Fiends, the Mirage Tower and the
volcano moved whole, drawn as they are, their art having a left and a right.
Its places are mirrored the same way (mirror_pos), a place in a block's
columns, in it or beside it above or below, moved with the block: the party
lands at Northwest Castle's door, not beside it.  Its zones are the game's,
mirrored; its docks the game's five, mirrored; and its lines that say east
or west say the other (mirror_lines).
"""
import base64, json, os, re, sys, zipfile
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import genows

LIST = os.path.join(ROOT, "maps", "custom-maps.txt")
MAPDIR = os.path.join(ROOT, "maps")
#  FFR's maps, for --import and test_ffmrules: FF1Randomizer/ beside the
#  tree, or in $FFR_ROOT, as worldgraph/ finds FFR's source (romdata.py).
FFRMAPS = os.path.join(os.environ.get("FFR_ROOT") or os.path.dirname(ROOT), "FF1Randomizer", "FF1Lib", "maps")
OUT_SEL = os.path.join(ROOT, "gen", "maps.inc")
OUT_WORLD = os.path.join(ROOT, "gen", "mapdata.inc")
OUT_DLG = os.path.join(ROOT, "gen", "mapdlg.inc")
OUT_BRIDGE = os.path.join(ROOT, "gen", "mapbridge.inc")
BLOB = os.path.join(ROOT, "out", "maps_%02X.bin")

#  The chunks whose low halves hold it all, filled in order: mkrom.py's
#  LOWHALF gives each its maps_XX.bin.
CHUNKS = (0x19, 0x1A, 0x1B, 0x18, 0x17, 0x16, 0x15, 0x14, 0x13, 0x11, 0x1D)
HALF = 0x8000
PIC = 256 * 32                  # a minimap's bytes
MAPS_MAX = 16                   # two columns of eight
LEFT_W, RIGHT_W = 13, 12        # a name's letters, on the left and on the right
NMAPS = 61                      # the standard maps, cur_map 0-60

#  The record.
MI = dict(ROWBANK=0x00, ROWLO=0x01, FLAGS=0x03, START=0x04, SHIP=0x06, AIRSHIP=0x08,
          BRIDGE=0x0A, CANAL=0x0C, FREESHIP=0x0E, PINZONES=0x10, DOMAIN=0x30, MM=0xF0, LOGIC=0xF3)
PINS_MAX = MI["DOMAIN"] - MI["PINZONES"] - 1    # ...and $FF after them
#  The zones round Coneria that the zone pass leaves alone (rando.asm's
#  deal_zones; FFR's StartingZones, Formations.cs): on another map, every
#  zone that takes their encounters, wherever its start is (user,
#  2026-11-16) -- FFR leaves these four alone by number on every map.
START_ZONES = (0x1B, 0x1C, 0x24, 0x2C)

#  A drawn map (ffm_map), as FFR's map generator works it out
#  (procgen/NewOverworld.cs).  Its entrances (OverworldTeleportIndex), in
#  the order the generator lists them (FeatureCoordinates; FFR's map files
#  keep it), each with the game's zone whose encounters the land nearest it
#  takes, in octal (row, column) as FFR writes them, and its weight in the
#  vote (AssignEncounterDomains).
FEATURES = [("Coneria", 1, 0o44, 3), ("ConeriaCastle1", 9, 0o44, 3), ("TempleOfFiends1", 13, 0o34, 1),
            ("Pravoka", 2, 0o46, 1), ("Gaia", 6, 0o06, .75), ("CastleOrdeals1", 12, 0o14, .75),
            ("TitansTunnelWest", 26, 0o50, 1), ("SardasCave", 22, 0o50, 1), ("EarthCave1", 14, 0o52, 1),
            ("MirageTower1", 24, 0o16, .75), ("Onrac", 7, 0o11, .75), ("TitansTunnelEast", 25, 0o50, 1),
            ("MatoyasCave", 21, 0o35, 1), ("DwarfCave", 20, 0o43, 1), ("Elfland", 3, 0o64, 1),
            ("ElflandCastle", 10, 0o64, 1), ("MarshCave1", 23, 0o73, 1), ("NorthwestCastle", 11, 0o53, 1),
            ("Melmond", 4, 0o52, 1), ("CrescentLake", 5, 0o66, 1), ("Lefein", 8, 0o37, .75),
            ("BahamutCave1", 18, 0o13, .5), ("Cardia1", 0, 0o12, .5), ("Cardia2", 17, 0o12, .5),
            ("Cardia4", 27, 0o12, .5), ("Cardia5", 28, 0o13, .5), ("Cardia6", 29, 0o13, .5),
            ("Waterfall", 19, 0o01, 1), ("IceCave1", 16, 0o66, 1), ("GurguVolcano1", 15, 0o66, 1)]
#  An entrance of several tiles -- a town's walls, a castle's gate -- has
#  its place on one of them, the generator's: which, in reading order
#  (Pravoka's second, Crescent Lake's last, the volcano's east half, and so
#  on); else the first.
ENTRANCE_TILE = {2: 1, 3: 2, 4: 1, 5: 4, 6: 3, 8: 2, 15: 1}
#  The exits' landings, each an entrance's place (ReplacementMap's
#  TeleporterFixups): Titan's Tunnel's east and west ends, the Ice Cave, the
#  Castle of Ordeals, Coneria Castle, the Earth Cave, the volcano, Onrac,
#  the Mirage Tower.
EXIT_ENTRANCES = (25, 26, 16, 12, 9, 14, 15, 7, 24)
#  The tiles the nearest-entrance search walks (OverworldTiles'
#  TraversableRegionTypes: land, then river); the bridge runs east to west
#  where the tile east of it is land.
FFR_LAND = {0x00, 0x54, 0x60, 0x61, 0x70, 0x71, 0x55, 0x62, 0x63, 0x72, 0x73, 0x14, 0x03, 0x04, 0x05,
            0x13, 0x15, 0x23, 0x24, 0x25, 0x28, 0x26, 0x08, 0x06, 0x45, 0x42, 0x43, 0x52, 0x53, 0x3D, 0x37}
FFR_RIVER = {0x44, 0x40, 0x41, 0x50, 0x51}
PLACES = ("start", "ship", "airship", "bridge", "canal")
#  Each other map's logic chunk image (build.sh links one a map from
#  gen/logic_N/), sixteen KB a slot, two to a low half of the NES's chunks
#  $01-$09, which nothing else uses (genm7.py's tilt's tables take $0A's to
#  $0C's, its landmarks' frames $0D's to $0F's): mkrom.py lays out/logic_N.bin where out/logic_slots.txt
#  says.  The game's map's is CHUNK_LOGIC itself.
LOGIC_SLOTS = [(c, off) for c in range(0x01, 0x0A) for off in (0x0000, 0x4000)]
                                    # (0A-0C: genm7.py's TILT_CHUNKS)
LOGIC_SLOT = 0x4000
GRAPHDIR = os.path.join(ROOT, "maps", "graph")
#  The minimap's layout (MI_MM's long address): the nametable, then the
#  logo's and the crests' tiles' addresses, high bytes then low.
MM = dict(TITLEHI=0x400, TITLELO=0x428, DECORHI=0x450, DECORLO=0x480)
MM_SIZE = 0x4B0
MM_COL, MM_ROW = 8, 6           # genowedits.py's: where the 16 x 16 blocks are
MI_SIZE = 0x100
MIF_HBRIDGE, MIF_MIRROR = 0x01, 0x02

#  The game's tables, bank $00 (game/bank_00.dat): lut_InitUnsramFirstPage
#  and its offsets (variables.inc), the exits' landings, the tile properties.
INITPAGE = 0xB000
U_SHIP, U_AIRSHIP, U_BRIDGE, U_CANAL, U_SCROLL = 0x01, 0x05, 0x09, 0x0D, 0x10
EXIT_X, EXIT_Y = 0xAC60, 0xAC70
OWTILESET = 0x8000

#  Mirror World.  Each terrain piece's mirror, the rest of the pieces for
#  themselves (genows / overworld-design-rules.md, 3): forest, sea,
#  mountains, desert, marsh, plains, rivers; the docks (the pier's left end
#  $77 and right $79, its left wall $1F and right $0F); the towns' walls.
MIRROR_PAIRS = [(0x03, 0x05), (0x13, 0x15), (0x23, 0x25), (0x06, 0x08), (0x16, 0x18), (0x26, 0x28),
                (0x10, 0x12), (0x20, 0x22), (0x30, 0x33), (0x42, 0x43), (0x52, 0x53), (0x62, 0x63),
                (0x72, 0x73), (0x60, 0x61), (0x70, 0x71), (0x40, 0x41), (0x50, 0x51),
                (0x77, 0x79), (0x0F, 0x1F),
                (0x2C, 0x2E), (0x3B, 0x3F), (0x3C, 0x3E), (0x4B, 0x4F), (0x5B, 0x5F), (0x5C, 0x5E),
                (0x6B, 0x6F), (0x7B, 0x7F), (0x7D, 0x7E)]
#  ...the pieces that are their mirror: the terrains' centres and north
#  and south edges, grass and the castles' grass, the desert's caravan and
#  FLOATER spots, the pier's middle, the towns' top wall and ground, the
#  houses, the caves, the Waterfall, Cardia's holes.
MIRROR_SELF = [0x00, 0x04, 0x14, 0x24, 0x07, 0x17, 0x27, 0x11, 0x21, 0x31, 0x45, 0x55, 0x54, 0x44,
               0x76, 0x36, 0x37, 0x78, 0x2D, 0x3D, 0x49, 0x4A, 0x4C, 0x4D, 0x4E, 0x5A, 0x5D, 0x6D,
               0x0E, 0x2B, 0x2F, 0x32, 0x34, 0x35, 0x3A, 0x46, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x6C,
               0x6E]
#  ...and the blocks moved whole: the castles, the Temple of Fiends, the
#  Mirage Tower (and its shadow), the volcano.
MIRROR_RIGID = {0x01, 0x02, 0x09, 0x0A, 0x19, 0x1A, 0x29, 0x2A, 0x0B, 0x0C, 0x1B, 0x1C, 0x38, 0x39,
                0x47, 0x48, 0x56, 0x57, 0x58, 0x59, 0x0D, 0x1D, 0x1E, 0x64, 0x65, 0x74, 0x75}
#  The lines a mirror turns round: a direction with east or west in it.
DIRECTION = re.compile(r"(?<![A-Za-z])(north|south|North|South|NORTH|SOUTH)?"
                       r"(east|west|East|West|EAST|WEST)(ern)?(?![A-Za-z])")
SWAP = {"east": "west", "west": "east", "East": "West", "West": "East", "EAST": "WEST", "WEST": "EAST"}

#  FFR's horizontal bridge (OwMapExchange.UpdateBridgeSprite): the bridge's
#  four sprite characters, bank $02 $9C40-$9C7F, NES colours 0-2.
BRIDGE_AT = 0x9C40
BRIDGE_T0 = [[0, 0, 0, 0, 1, 1, 1, 1], [0, 0, 1, 1, 2, 2, 2, 2], [1, 1, 2, 2, 2, 2, 2, 2],
             [2, 2, 2, 1, 1, 1, 1, 1], [2, 1, 1, 2, 2, 2, 2, 2], [1, 2, 2, 2, 2, 2, 2, 2],
             [2, 2, 2, 2, 2, 2, 2, 2], [2, 2, 2, 2, 2, 2, 2, 2]]
BRIDGE_T1 = [[2, 2, 2, 2, 2, 2, 2, 2], [2, 2, 2, 2, 2, 2, 2, 2], [2, 2, 2, 2, 2, 2, 2, 2],
             [2, 2, 2, 2, 1, 1, 1, 1], [2, 2, 1, 1, 2, 2, 2, 2], [1, 1, 2, 2, 2, 2, 2, 2],
             [2, 2, 2, 1, 1, 1, 1, 1], [1, 1, 1, 0, 0, 0, 0, 0]]


def bank00():
    return open(os.path.join(ROOT, "game", "bank_00.dat"), "rb").read()


def init_xy(off):
    d = bank00()
    return d[INITPAGE - 0x8000 + off], d[INITPAGE - 0x8000 + off + 1]


def vanilla_start():
    x, y = init_xy(U_SCROLL)
    return x + 7, y + 7


def snes_const(name):
    for line in open(os.path.join(ROOT, "src", "snesmap.inc"), encoding="latin-1"):
        m = re.match(r"%s\s*=\s*(\d+)" % name, line)
        if m:
            return int(m.group(1))
    sys.exit("genmaps: no %s in snesmap.inc" % name)


def parse():
    """[(kind, stem, None, name)]: kind 'vanilla', 'mirror-lr' or 'ffm', a
    drawn map's stem its files' name in maps/."""
    out = []
    for n, line in enumerate(open(LIST, encoding="utf-8"), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        if word in ("vanilla", "mirror-lr"):
            out.append((word, None, None, rest))
        elif word == "ffm":
            stem, _, name = rest.partition(" ")
            if not re.match(r"^[a-z0-9-]+$", stem) or not name.strip():
                sys.exit("%s:%d: want ffm STEM NAME, STEM in lower case, digits and -"
                         % (os.path.relpath(LIST, ROOT), n))
            out.append(("ffm", stem, None, name.strip()))
        else:
            sys.exit("%s:%d: no kind of map \"%s\"" % (os.path.relpath(LIST, ROOT), n, word))
        if not out[-1][3]:
            sys.exit("%s:%d: a map with no name" % (os.path.relpath(LIST, ROOT), n))
    return out


# --- a drawn map ----------------------------------------------------------------

def ow_props():
    """The overworld tiles' properties, two bytes each (bank $00)."""
    return bank00()[OWTILESET - 0x8000:][:256]


def entrance_tiles(tiles):
    """{entrance: [(x, y)]}, each entrance's tiles in reading order: a tile
    whose second property byte has bit 7 is one, its low six bits which."""
    props = ow_props()
    out = {}
    for i, t in enumerate(tiles):
        if props[2 * t + 1] & 0x80:
            out.setdefault(props[2 * t + 1] & 0x3F, []).append((i & 255, i >> 8))
    return out


def entrance_places(tiles, what):
    """{entrance: (x, y)}: where each of FFR's entrances is (ENTRANCE_TILE),
    each there once, its tiles together."""
    where = entrance_tiles(tiles)
    out = {}
    for name, e, _, _ in FEATURES:
        ts = where.get(e)
        if not ts:
            sys.exit("genmaps: %s has no %s" % (what, name))
        xs, ys = [x for x, _ in ts], [y for _, y in ts]
        if max(xs) - min(xs) > 5 or max(ys) - min(ys) > 5:
            sys.exit("genmaps: %s has %s in more than one place: %s" % (what, name, ts[:6]))
        k = ENTRANCE_TILE.get(e, 0)
        if k >= len(ts):
            sys.exit("genmaps: %s's %s is %d tiles, not the generator's shape (its place the %s)"
                     % (what, name, len(ts), "tile %d" % (k + 1)))
        out[e] = ts[k]
    return out


def ffr_zones(tiles, places):
    """Each overworld zone's encounters, as the zone they are taken from
    (AssignEncounterDomains): every tile of land or river given its nearest
    entrance, walking from all at once in FEATURES' order, the first to
    reach a tile taking it; then each 32 x 32 zone the zone of the entrance
    whose tiles in it weigh most, the first to reach that weight on a tie;
    a zone with none, zone 0."""
    near = [None] * 65536
    q = deque((k, places[e]) for k, (_, e, _, _) in enumerate(FEATURES))
    while q:
        k, (x, y) = q.popleft()
        if near[x | y << 8] is not None:
            continue
        near[x | y << 8] = k
        for ax, ay in ((x, (y - 1) & 255), ((x + 1) & 255, y), (x, (y + 1) & 255), ((x - 1) & 255, y)):
            t = tiles[ax | ay << 8]
            if t in FFR_LAND or t in FFR_RIVER:
                q.append((k, (ax, ay)))
    out = []
    for j in range(8):
        for i in range(8):
            counts = {}
            for y in range(32):
                for x in range(32):
                    k = near[(j * 32 + y) << 8 | (i * 32 + x)]
                    if k is not None:
                        counts[k] = counts.get(k, 0) + FEATURES[k][3]
            pick, most = None, 0
            for k, c in counts.items():
                if c > most:
                    pick, most = k, c
            out.append(FEATURES[pick][2] if pick is not None else 0)
    return out


def ffm_map(stem):
    """maps/STEM.ffm and STEM.toml: the tiles; the start, Bikke's ship, the
    airship, the bridge and the canal; the docks, the first a Free SHIP's;
    and what follows from the tiles -- each entrance's place, the exits'
    landings (each an entrance's place), whether the bridge runs east to
    west, and each zone's encounters."""
    import tomllib
    what = "maps/%s" % stem
    path = os.path.join(MAPDIR, stem + ".ffm")
    if not os.path.exists(path):
        sys.exit("genmaps: no %s.ffm" % what)
    tiles = open(path, "rb").read()
    if len(tiles) != 65536:
        sys.exit("genmaps: %s.ffm is %d bytes, not 256 x 256" % (what, len(tiles)))
    if max(tiles) > 0x7F:
        sys.exit("genmaps: %s.ffm has a tile past $7F" % what)
    try:
        p = tomllib.load(open(os.path.join(MAPDIR, stem + ".toml"), "rb"))
    except FileNotFoundError:
        sys.exit("genmaps: no %s.toml" % what)
    except tomllib.TOMLDecodeError as e:
        sys.exit("genmaps: %s.toml: %s" % (what, e))
    extra = sorted(set(p) - set(PLACES) - {"docks"})
    if extra:
        sys.exit("genmaps: %s.toml: no place called %s" % (what, extra[0]))

    def xy(v, name):
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(c, int) and 0 <= c < 256 for c in v)):
            sys.exit("genmaps: %s.toml: %s wants [x, y], each 0-255" % (what, name))
        return tuple(v)
    for k in PLACES + ("docks",):
        if k not in p:
            sys.exit("genmaps: %s.toml has no %s" % (what, k))
    places = {k: xy(p[k], k) for k in PLACES}
    if not isinstance(p["docks"], list) or not p["docks"]:
        sys.exit("genmaps: %s.toml: docks wants a list of [x, y]" % what)
    docks = [xy(v, "docks") for v in p["docks"]]
    if len(set(docks)) != len(docks):
        sys.exit("genmaps: %s.toml lists a dock twice" % what)
    at = entrance_places(tiles, what)
    bx, by = places["bridge"]
    return {"tiles": tiles, "places": places, "docks": docks, "entrances": at,
            "exits": {k: at[e] for k, e in enumerate(EXIT_ENTRANCES)},
            "hbridge": tiles[((bx + 1) & 255) | by << 8] in FFR_LAND,
            "domains": ffr_zones(tiles, at),
            "digest_data": tiles + repr(sorted((k, v) for k, v in p.items())).encode()}


def import_ffr(pool, mid, stem):
    """One of FFR's maps, POOL's ID in ../FF1Randomizer/FF1Lib/maps, as a
    drawn map: maps/STEM.ffm and STEM.toml, its docks the default first and
    each other place once (by entrance), and what ffm_map works out from
    the tiles checked against FFR's file."""
    zp = os.path.join(FFRMAPS, pool + ".zip")
    if not os.path.exists(zp):
        sys.exit("genmaps: no pool %s (%s)" % (pool, zp))
    z = zipfile.ZipFile(zp)
    if mid + ".json" not in z.namelist():
        near = [n[:-5] for n in z.namelist() if n[:4] == mid[:4] and n.endswith(".json")]
        sys.exit("genmaps: no map %s in %s%s" % (mid, pool, " (near: %s)" % ", ".join(near) if near else ""))
    if not re.match(r"^[a-z0-9-]+$", stem):
        sys.exit("genmaps: a stem in lower case, digits and -")
    f = json.loads(z.read(mid + ".json"))
    tiles = b"".join(base64.b64decode(r) for r in f["DecompressedMapRows"])
    xy = lambda v: [v["X"], v["Y"]]
    ships = {sl["TeleporterIndex"]: [sl["X"], sl["Y"]] for sl in f["ShipLocations"]}
    docks = [ships[255]]
    for o in sorted(k for k in ships if k != 255):
        if ships[o] not in docks:
            docks.append(ships[o])
    pair = lambda v: "[%d, %d]" % tuple(v)
    toml = ["#  From FFR's %s map %s (FF1Randomizer/FF1Lib/maps/%s.zip)." % (pool, mid, pool),
            "#  The places the tiles do not show, [x, y] in tiles (tools/genmaps.py).",
            "",
            "start = %s" % pair(xy(f["StartingLocation"])),
            "ship = %s             # Bikke's, at Pravoka's dock" % pair(ships.get(2, ships[255])),
            "airship = %s" % pair(xy(f["AirShipLocation"])),
            "bridge = %s" % pair(xy(f["BridgeLocation"])),
            "canal = %s" % pair(xy(f["CanalLocation"])),
            "",
            "#  Where a found ship moors -- the nearest it can be boarded from -- the",
            "#  first where a Free SHIP waits.",
            "docks = [%s]" % ", ".join(pair(d) for d in docks)]
    with open(os.path.join(MAPDIR, stem + ".ffm"), "wb") as fo:
        fo.write(tiles)
    with open(os.path.join(MAPDIR, stem + ".toml"), "w") as fo:
        fo.write("\n".join(toml) + "\n")
    m = ffm_map(stem)
    owti = {name: e for name, e, _, _ in FEATURES}
    moved = [k for k, v in f["OverworldCoordinates"].items() if m["entrances"][owti[k]] != tuple(xy(v))]
    exits = {t["Index"]: tuple(xy(t["To"])) for t in f["TeleporterFixups"] or [] if t["Type"] == 1}
    zones = list(range(64))
    for du in f.get("DomainUpdates") or []:
        zones[du["To"]] = du["From"]
    print("genmaps: maps/%s.ffm, maps/%s.toml" % (stem, stem))
    for what, ok in (("the exits", exits == m["exits"]), ("the bridge's direction",
                     m["hbridge"] == bool(f.get("HorizontalBridge"))), ("the zones", zones == m["domains"])):
        if not ok:
            print("genmaps: warning: %s are not FFR's file's" % what)
    if moved:
        print("genmaps: note: %s placed on another of its tiles than FFR's file says" % ", ".join(moved))


# --- the game's map, and its mirror ----------------------------------------

def mirror_table():
    mt = {}
    for a, b in MIRROR_PAIRS:
        mt[a], mt[b] = b, a
    for t in MIRROR_SELF:
        assert t not in mt, "$%02X twice" % t
        mt[t] = t
    assert not set(mt) & MIRROR_RIGID
    return mt


def rigid_blocks(w):
    """The blocks moved whole: 4-connected runs of MIRROR_RIGID's pieces,
    each its cells and its columns x0..x1, rows y0..y1."""
    seen, out = set(), []
    for y in range(256):
        for x in range(256):
            if (x, y) in seen or w[x + 256 * y] not in MIRROR_RIGID:
                continue
            todo, cells = [(x, y)], []
            seen.add((x, y))
            while todo:
                cx, cy = todo.pop()
                cells.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < 256 and 0 <= ny < 256 and (nx, ny) not in seen \
                            and w[nx + 256 * ny] in MIRROR_RIGID:
                        seen.add((nx, ny))
                        todo.append((nx, ny))
            xs, ys = [c[0] for c in cells], [c[1] for c in cells]
            out.append((cells, min(xs), max(xs), min(ys), max(ys)))
    return out


def mirror_pos(blocks, x, y):
    """Where a place on the game's map is on its mirror: moved with a block it
    is in, or above or below in its columns; else straight across."""
    for _, x0, x1, y0, y1 in blocks:
        if x0 <= x <= x1 and y0 - 1 <= y <= y1 + 1:
            return 255 - x1 + (x - x0), y
    return 255 - x, y


def mirror_lr(w):
    """The game's map mirrored left to right: its 65,536 tiles."""
    mt = mirror_table()
    unknown = sorted({t for t in w if t not in mt and t not in MIRROR_RIGID})
    if unknown:
        sys.exit("genmaps: the mirror knows no piece %s" % " ".join("$%02X" % t for t in unknown))
    props = bank00()[OWTILESET - 0x8000:][:256]
    for a, b in MIRROR_PAIRS:
        if props[2 * a:2 * a + 2] != props[2 * b:2 * b + 2]:
            sys.exit("genmaps: $%02X and its mirror $%02X differ in what they let pass" % (a, b))
    out = [None] * 65536
    for y in range(256):
        for x in range(256):
            t = w[x + 256 * y]
            if t not in MIRROR_RIGID:
                out[255 - x + 256 * y] = mt[t]
    blocks = rigid_blocks(w)
    moved = set()
    for cells, x0, x1, _, _ in blocks:
        for x, y in cells:
            nx = 255 - x1 + (x - x0)
            out[nx + 256 * y] = w[x + 256 * y]
            moved.add((nx, y))
    #  A block whose outline is not symmetric leaves a hole where its mirror
    #  would have been: the commonest piece beside it, from outside the block.
    for i in range(65536):
        if out[i] is None:
            x, y = i & 255, i >> 8
            near = [out[(x + dx) + 256 * (y + dy)] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < 256 and 0 <= y + dy < 256 and (x + dx, y + dy) not in moved
                    and out[(x + dx) + 256 * (y + dy)] is not None]
            if not near:
                sys.exit("genmaps: a hole in the mirror at (%d, %d) with nothing beside it" % (x, y))
            out[i] = max(set(near), key=near.count)
    return bytes(out), blocks


# --- the records --------------------------------------------------------------

def vanilla_exits():
    d = bank00()
    return list(zip(d[EXIT_X - 0x8000:][:16], d[EXIT_Y - 0x8000:][:16]))


def record(kind, d, mirrorinfo=None):
    """A map's record, but its rows' address (MI_ROWBANK, MI_ROWLO)."""
    rec = bytearray(MI_SIZE)
    put = lambda field, xy: rec.__setitem__(slice(MI[field], MI[field] + 2), bytes(xy))
    freeship = (snes_const("FREESHIP_X"), snes_const("FREESHIP_Y"))
    if kind == "vanilla":
        put("START", vanilla_start())
        put("SHIP", init_xy(U_SHIP))
        put("AIRSHIP", init_xy(U_AIRSHIP))
        put("BRIDGE", init_xy(U_BRIDGE))
        put("CANAL", init_xy(U_CANAL))
        put("FREESHIP", freeship)
        domains = list(range(64))
    elif kind == "mirror-lr":
        rec[MI["FLAGS"]] |= MIF_MIRROR
        pos = lambda xy: mirror_pos(mirrorinfo, *xy)
        put("START", pos(vanilla_start()))
        put("SHIP", pos(init_xy(U_SHIP)))
        put("AIRSHIP", pos(init_xy(U_AIRSHIP)))
        put("BRIDGE", pos(init_xy(U_BRIDGE)))
        put("CANAL", pos(init_xy(U_CANAL)))
        put("FREESHIP", pos(freeship))
        domains = [(z & ~7) | (7 - (z & 7)) for z in range(64)]
    else:
        for k in PLACES:
            put(k.upper(), d["places"][k])
        put("FREESHIP", d["docks"][0])
        if d["hbridge"]:
            rec[MI["FLAGS"]] |= MIF_HBRIDGE
        domains = d["domains"]
    rec[MI["DOMAIN"]:MI["DOMAIN"] + 64] = bytes(domains)
    pins = [z for z in range(64) if domains[z] in START_ZONES]
    if len(pins) > PINS_MAX:
        sys.exit("genmaps: %d zones take Coneria's encounters, room for %d" % (len(pins), PINS_MAX))
    rec[MI["PINZONES"]:MI["PINZONES"] + len(pins) + 1] = bytes(pins + [0xFF])
    return rec


def mm_game():
    """The game's map's minimap layout, as tools/genowedits.py lays it out
    with the map edits in it: the nametable, the logo's tiles, the crests'."""
    nt = open(os.path.join(ROOT, "gen", "minimap_nt.nam"), "rb").read()

    def ids(name):
        src = open(os.path.join(ROOT, "gen", name)).read()
        lo = src[src.index("_lo:"):src.index("_hi:")]
        return [int(v, 16) >> 4 for v in re.findall(r"<\$([0-9A-Fa-f]{4})", lo)]
    return nt, ids("minimap_titledest.inc"), ids("minimap_decordest.inc")


def mm_layout(tiles, name):
    """Another map's minimap layout: each block of land shown with the
    tile of its number, every block of open sea with one blank tile (block 0's if it is
    sea), and the logo and the crests in the tiles of other blocks of open
    sea -- the game's choices where they are sea here -- so the drawing
    leaves them blank until the logo and crests are drawn into them."""
    import genowedits as GO
    ts = genows.minimap_tiles()
    vnt, vtitle, vdecor = mm_game()
    blank = {b for b in range(256) if GO.block_pixels(tiles, ts, b) == (0,) * 64}
    if not blank:
        sys.exit("genmaps: %s's minimap has no block of open sea" % name)
    bt = 0 if 0 in blank else min(blank)
    lent = vtitle + vdecor
    keep = {v for v in lent if v in blank and v != bt}
    pool = iter(sorted(blank - keep - {bt}))
    try:
        new = [v if v in keep else next(pool) for v in lent]
    except StopIteration:
        sys.exit("genmaps: %s's minimap has %d blocks of open sea, the logo and crests want %d"
                 % (name, len(blank), len(lent) + 1))
    remap = dict(zip(lent, new))
    cells = {(MM_ROW + (b >> 4)) * 32 + MM_COL + (b & 15): b for b in range(256)}
    nt = bytearray(vnt)
    for i in range(960):
        if i in cells:
            nt[i] = bt if cells[i] in blank else cells[i]
        elif nt[i] in remap:
            nt[i] = remap[nt[i]]
        elif nt[i] == 0:
            nt[i] = bt
        else:
            sys.exit("genmaps: the minimap's cell %d shows $%02X, neither a lent tile nor blank" % (i, nt[i]))
    assert len(set(new)) == len(new) and not set(new) & ({bt} | {b for b in range(256) if b not in blank})
    assert all(nt[i] in (cells[i], bt) for i in cells)
    return bytes(nt), new[:len(vtitle)], new[len(vtitle):]


def mm_blob(nt, title, decor):
    out = bytearray(MM_SIZE)
    out[0:len(nt)] = nt
    for field, ids in (("TITLE", title), ("DECOR", decor)):
        out[MM[field + "HI"]:MM[field + "HI"] + len(ids)] = bytes(t >> 4 for t in ids)
        out[MM[field + "LO"]:MM[field + "LO"] + len(ids)] = bytes((t << 4) & 0xFF for t in ids)
    assert len(title) == MM["TITLELO"] - MM["TITLEHI"] and len(decor) == MM["DECORLO"] - MM["DECORHI"]
    return bytes(out)


def rle_rows(tiles):
    """The rows in the game's format, and each row's offset from the first."""
    data, offs = bytearray(), []
    for r in range(256):
        row = tiles[256 * r:256 * r + 256]
        offs.append(len(data))
        i = 0
        while i < 256:
            j = i
            while j < 256 and row[j] == row[i]:
                j += 1
            if j - i == 1:
                data.append(row[i])
            else:
                data += bytes((0x80 | row[i], (j - i) & 0xFF))
            i = j
        data.append(0xFF)
    return data, offs


# --- Mirror World's lines -----------------------------------------------------

FONT = {" ": 0xFF, "'": 0xBE, ",": 0xBF, ".": 0xC0, "-": 0xC2, "!": 0xC4, "?": 0xC5}
FONT.update({chr(48 + i): 0x80 + i for i in range(10)})
FONT.update({chr(65 + i): 0x8A + i for i in range(26)})
FONT.update({chr(97 + i): 0xA4 + i for i in range(26)})
CHARS = {v: k for k, v in FONT.items()}
DTE_FIRST, DTE_N = 0x1A, 0x50
DLG_MAX = 0x50                  # OPTDESC, terminator and all


def dte():
    src = open(os.path.join(ROOT, "game", "bank_0F.asm"), encoding="latin-1").read()

    def table(name):
        vals = []
        for line in src[src.index(name + ":"):].split("\n")[1:]:
            line = line.split(";")[0]
            if re.match(r"^\w+:", line):
                break
            vals += [int(v, 16) for v in re.findall(r"\$([0-9A-Fa-f]{2})", line)]
            if len(vals) >= DTE_N:
                break
        return vals[:DTE_N]
    return table("lut_DTE1"), table("lut_DTE2")


def mirror_lines():
    """[(dialogue number, bytes)]: each of the game's lines with a direction
    in it, east and west swapped, coded with the game's pairs to fit."""
    d1, d2 = dte()
    pairs = {(a, b): DTE_FIRST + i for i, (a, b) in enumerate(zip(d1, d2))}
    text = open(os.path.join(ROOT, "game", "bank_0A.dat"), "rb").read()
    out = []
    for n in range(256):
        p = text[2 * n] | text[2 * n + 1] << 8
        if not 0x8000 <= p < 0xC000:
            continue
        p -= 0x8000
        raw = []
        while text[p]:
            b = text[p]
            raw += [d1[b - DTE_FIRST], d2[b - DTE_FIRST]] if DTE_FIRST <= b < DTE_FIRST + DTE_N else [b]
            p += 1
        #  As text: the font's letters, any other byte a character apart.
        s = "".join(CHARS.get(b, chr(0x100 + b)) for b in raw)
        if not DIRECTION.search(s):
            continue
        t = DIRECTION.sub(lambda m: (m.group(1) or "") + SWAP[m.group(2)] + (m.group(3) or ""), s)
        b = [FONT[c] if c in FONT else ord(c) - 0x100 for c in t]
        coded, i = [], 0
        while i < len(b):
            if i + 1 < len(b) and (b[i], b[i + 1]) in pairs:
                coded.append(pairs[(b[i], b[i + 1])])
                i += 2
            else:
                coded.append(b[i])
                i += 1
        if len(coded) + 1 > DLG_MAX:
            sys.exit("genmaps: dialogue $%02X mirrored is %d bytes, past OPTDESC" % (n, len(coded) + 1))
        out.append((n, bytes(coded + [0]), t))
    return out


# --- the logic ------------------------------------------------------------------

def graph_key(entry):
    kind, stem, _, _ = entry
    return "mirror-lr" if kind == "mirror-lr" else stem


def map_digest(entry):
    """A digest of what a map's world graph is made from: a drawn map's tiles
    and places, or Mirror World's tiles, its blocks and the game's places
    they move.  gengraph.py --map writes it with the graph, and makes the
    graph again for a map whose digest has changed (--stale, build.sh)."""
    import hashlib
    kind, stem, _, _ = entry
    if kind == "ffm":
        data = ffm_map(stem)["digest_data"]
    else:
        t, blocks = mirror_lr(genows.vanilla())
        data = bytes(t) + repr([b[1:] for b in blocks]).encode() + bank00()[INITPAGE - 0x8000:][:0x20] \
            + repr(vanilla_exits()).encode()
    return hashlib.sha256(data).hexdigest()[:16]


def graph_of(entry):
    """A map's world graph data, as gengraph.py writes it: the game's map's
    tools/graphdata.py, another's maps/graph/KEY.py."""
    if entry[0] == "vanilla":
        import graphdata as GD
        return {k: getattr(GD, k) for k in dir(GD) if k.isupper()}
    key = graph_key(entry)
    path = os.path.join(GRAPHDIR, key + ".py")
    if not os.path.exists(path):
        sys.exit("genmaps: %s has no world graph -- python3 tools/gengraph.py --stale" % entry[3])
    D = {}
    exec(open(path).read(), D)
    D = {k: v for k, v in D.items() if k.isupper()}
    if D.get("DIGEST") != map_digest(entry):
        sys.exit("genmaps: %s's world graph was made from other inputs -- python3 tools/gengraph.py --stale"
                 % entry[3])
    return D


def snes_hex(name):
    for line in open(os.path.join(ROOT, "src", "snesmap.inc"), encoding="latin-1"):
        m = re.match(r"%s\s*=\s*\$([0-9A-Fa-f]+)" % name, line)
        if m:
            return int(m.group(1), 16)
    sys.exit("genmaps: no %s in snesmap.inc" % name)


def write_logic(entries, recs):
    """The world graph's tables, every map's laid out alike (graphtables.py):
    gen/graph.inc, gen/logic_N/graphdata.inc; each map's logic image's place
    in its record (MI_LOGIC) and in out/logic_slots.txt."""
    import glob, shutil
    import graphtables
    clines, incs = graphtables.lay_out([graph_of(e) for e in entries])
    open(os.path.join(ROOT, "gen", "graph.inc"), "w").write("\n".join(clines) + "\n")
    for d in glob.glob(os.path.join(ROOT, "gen", "logic_*")):
        shutil.rmtree(d)
    for i, inc in enumerate(incs):
        d = os.path.join(ROOT, "gen", "logic_%d" % i)
        os.makedirs(d)
        open(os.path.join(d, "graphdata.inc"), "w").write("\n".join(inc) + "\n")
    if len(entries) - 1 > len(LOGIC_SLOTS):
        sys.exit("genmaps: %d maps, logic for %d" % (len(entries), len(LOGIC_SLOTS) + 1))
    slots = []
    for i, rec in enumerate(recs):
        if i == 0:
            at = (snes_hex("CHUNK0") + snes_hex("CHUNK_LOGIC")) * 0x10000 + 0x8000
        else:
            c, off = LOGIC_SLOTS[i - 1]
            at = 0xC00000 + (1 + c) * 0x10000 + off
            slots.append("%d %d %d" % (i, c, off))
        rec[MI["LOGIC"]:MI["LOGIC"] + 3] = at.to_bytes(3, "little")
    open(os.path.join(ROOT, "out", "logic_slots.txt"), "w").write("\n".join(slots) + "\n")


# --- out ------------------------------------------------------------------------

def check(entries):
    if not entries:
        sys.exit("genmaps: no maps in %s" % os.path.relpath(LIST, ROOT))
    if entries[0][0] != "vanilla" or any(e[0] == "vanilla" for e in entries[1:]):
        sys.exit("genmaps: the game's map (vanilla) must be the first, and only once")
    if len(entries) > MAPS_MAX:
        sys.exit("genmaps: %d maps, at most %d" % (len(entries), MAPS_MAX))
    rows = (len(entries) + 1) // 2
    for i, e in enumerate(entries):
        width = LEFT_W if i < rows else RIGHT_W
        if len(e[3]) > width:
            sys.exit("genmaps: \"%s\" is %d letters, at most %d in the %s column"
                     % (e[3], len(e[3]), width, "left" if i < rows else "right"))
        bad = [c for c in e[3] if not (c.isalnum() and c.isascii()) and c not in " '-.,!?"]
        if bad:
            sys.exit("genmaps: \"%s\": the game's font has no %r" % (e[3], bad[0]))
    return rows


class Halves:
    """The low halves, filled in turn: a piece goes in the first with room."""
    def __init__(self):
        self.blobs = {c: bytearray() for c in CHUNKS}

    def put(self, data, what):
        for c in CHUNKS:
            if len(self.blobs[c]) + len(data) <= HALF:
                at = 0xC00000 + (1 + c) * 0x10000 + len(self.blobs[c])
                self.blobs[c] += data
                return at
        sys.exit("genmaps: no low half has room for %s (%d bytes)" % (what, len(data)))


def tiles_of(entry):
    """(tiles, Mirror World's blocks, a drawn map's ffm_map)."""
    kind, stem, _, _ = entry
    if kind == "vanilla":
        return bytes(genows.vanilla()), None, None
    if kind == "mirror-lr":
        t, blocks = mirror_lr(genows.vanilla())
        return t, blocks, None
    m = ffm_map(stem)
    return m["tiles"], None, m


def main():
    if sys.argv[1:2] == ["--import"]:
        if len(sys.argv) != 5:
            sys.exit("usage: genmaps.py --import POOL ID STEM")
        import_ffr(*sys.argv[2:5])
        return
    import mkrom
    for c in CHUNKS:
        if mkrom.LOWHALF.get(c) != "maps_%02X.bin" % c:
            sys.exit("genmaps: mkrom.py's LOWHALF does not give maps_%02X.bin chunk $%02X's low half" % (c, c))
    entries = parse()
    rows = check(entries)
    ts = genows.screen_tiles()
    halves = Halves()
    maps = [tiles_of(e) for e in entries]
    pics = [halves.put(genows.baked(ts, t), "%s's minimap" % e[3]) for e, (t, _, _) in zip(entries, maps)]
    recs = [record(e[0], m, blocks) for e, (_, blocks, m) in zip(entries, maps)]
    info = halves.put(bytes(MI_SIZE * len(entries)), "the records")
    for i, (e, (t, _, _)) in enumerate(zip(entries, maps)):
        if e[0] == "vanilla":
            continue                            # bank $01's
        data, offs = rle_rows(t)
        at = halves.put(bytes(512) + data, "%s's rows" % e[3])
        lo = at & 0xFFFF
        table = b"".join((lo + 512 + o).to_bytes(2, "little") for o in offs)
        c = (at >> 16) - 0xC1
        base = lo
        halves.blobs[c][base:base + 512] = table
        recs[i][MI["ROWBANK"]] = at >> 16
        recs[i][MI["ROWLO"]:MI["ROWLO"] + 2] = lo.to_bytes(2, "little")
    for i, (e, (t, _, _)) in enumerate(zip(entries, maps)):
        lay = mm_game() if e[0] == "vanilla" else mm_layout(t, e[3])
        at = halves.put(mm_blob(*lay), "%s's minimap layout" % e[3])
        recs[i][MI["MM"]:MI["MM"] + 3] = at.to_bytes(3, "little")
    write_logic(entries, recs)
    c = (info >> 16) - 0xC1
    lo = info & 0xFFFF
    halves.blobs[c][lo:lo + MI_SIZE * len(entries)] = b"".join(recs)
    os.makedirs(os.path.dirname(BLOB), exist_ok=True)
    for c, b in halves.blobs.items():
        open(BLOB % c, "wb").write(bytes(b))

    starts = [(r[MI["START"]], r[MI["START"] + 1]) for r in recs]
    o = [";  Generated by tools/genmaps.py from maps/custom-maps.txt -- do not edit.",
         ";  Map Select's maps (mapselect.inc): their names, their minimaps' long",
         ";  addresses -- in chunks' low halves, mkrom.py's LOWHALF -- and their",
         ";  starts, the party's tile.  The first is the game's map.",
         "",
         "MAPS_N        = %d" % len(entries),
         "MAPS_ROWS     = %d          ; the left column's" % rows,
         "MAPS_LEFTW    = %d" % LEFT_W,
         "MAPS_RIGHTW   = %d" % RIGHT_W,
         "MAPS_VANILLAPIC = $%06X    ; the game's map's minimap" % pics[0],
         "",
         "lut_MapName:"]
    for e in entries:
        o.append('  FFPAD "%s", %d' % (e[3], LEFT_W))
    o.append("lut_MapPicLo:")
    o += ["  .WORD $%04X        ; %s" % (f & 0xFFFF, e[3]) for f, e in zip(pics, entries)]
    o.append("lut_MapPicBank:")
    o.append("  .BYTE " + ", ".join("$%02X" % (f >> 16) for f in pics))
    o.append("lut_MapStartX:")
    o.append("  .BYTE " + ", ".join("%d" % s[0] for s in starts))
    o.append("lut_MapStartY:")
    o.append("  .BYTE " + ", ".join("%d" % s[1] for s in starts))
    open(OUT_SEL, "w").write("\n".join(o) + "\n")

    o = [";  Generated by tools/genmaps.py from maps/custom-maps.txt -- do not edit.",
         ";  The maps' records (altmaps.inc): RANDO_MAP's at MAPINFOFAR + RANDO_MAP *",
         ";  MI_SIZE, its fields MI_*, its flags MIF_*.",
         "",
         "MAPINFO_N     = %d" % len(entries),
         "MAPINFOFAR    = $%06X" % info,
         "MI_SIZE       = $%02X" % MI_SIZE]
    o += ["MI_%-10s = $%02X" % (k, v) for k, v in sorted(MI.items(), key=lambda kv: kv[1])]
    o += ["MIF_HBRIDGE   = $%02X" % MIF_HBRIDGE, "MIF_MIRROR    = $%02X" % MIF_MIRROR]
    o += ["MM_%-10s = $%03X" % (k, v) for k, v in sorted(MM.items(), key=lambda kv: kv[1])]
    o += ["MM_SIZE       = $%03X" % MM_SIZE]
    open(OUT_WORLD, "w").write("\n".join(o) + "\n")

    lines = mirror_lines()
    o = [";  Generated by tools/genmaps.py -- do not edit.  Mirror World's lines",
         ";  (altmaps.inc's dlg_lines): the game's that say east or west, saying",
         ";  the other, coded with the game's pairs to fit OPTDESC.",
         "",
          "lut_DlgMirrorId:",
          "  .BYTE " + ", ".join("$%02X" % n for n, _, _ in lines),
          "DLG_NMIRROR = * - lut_DlgMirrorId"]
    for k, (n, b, t) in enumerate(lines):
        shown = "".join("/" if c in (chr(0x101), chr(0x105)) else ".." if c == chr(0x1C3) else
                        c if ord(c) < 0x80 else "<%02X>" % (ord(c) - 0x100) for c in t)
        o.append("lut_DlgMirror%d:   ; $%02X: \"%s\"" % (k, n, shown.replace('"', "'")))
        for i in range(0, len(b), 16):
            o.append("  .BYTE " + ", ".join("$%02X" % v for v in b[i:i + 16]))
    o.append("lut_DlgMirrorLo:")
    o.append("  .BYTE " + ", ".join("<lut_DlgMirror%d" % k for k in range(len(lines))))
    o.append("lut_DlgMirrorHi:")
    o.append("  .BYTE " + ", ".join(">lut_DlgMirror%d" % k for k in range(len(lines))))
    open(OUT_DLG, "w").write("\n".join(o) + "\n")

    def nes(tile):
        return bytes(sum((tile[r][c] & 1) << (7 - c) for c in range(8)) for r in range(8)) + \
            bytes(sum((tile[r][c] >> 1) << (7 - c) for c in range(8)) for r in range(8))
    flip = lambda t: [row[::-1] for row in t]
    tiles = nes(BRIDGE_T0) + nes(flip(BRIDGE_T0)) + nes(BRIDGE_T1) + nes(flip(BRIDGE_T1))
    o = [";  Generated by tools/genmaps.py -- do not edit.  The bridge across a",
         ";  horizontal strait (MIF_HBRIDGE), FFR's: the bridge's four sprite",
         ";  characters, bank $02 $%04X-$%04X, as lut_JapanRuns' records" % (BRIDGE_AT, BRIDGE_AT + len(tiles)),
         ";  (fun_chrload).",
         "",
         "lut_BridgeRuns:",
         "  .WORD $%04X, $%04X, (CHUNK0 + $02), lut_BridgeTiles" % (BRIDGE_AT, BRIDGE_AT + len(tiles)),
         "  .WORD 0",
         "  .ALIGN 16",
         "lut_BridgeTiles:"]
    for i in range(0, len(tiles), 16):
        o.append("  .BYTE " + ", ".join("$%02X" % v for v in tiles[i:i + 16]))
    o.append(".assert (lut_BridgeTiles & 15) = 0, error, \"jp_put wants each tile on a 16-byte boundary\"")
    open(OUT_BRIDGE, "w").write("\n".join(o) + "\n")


if __name__ == "__main__":
    main()
