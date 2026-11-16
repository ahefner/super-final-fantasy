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
    out/maps_XX.bin    the data, in chunks' low halves (mkrom.py's LOWHALF):
                       the minimaps, the records, each map's rows

maps/custom-maps.txt lists the maps in the order the screen shows them: the
game's map first, then any of "mirror-lr" (the game's map mirrored left to
right) and FFR's maps by pool and id, each with the name the screen shows.
FFR's maps are vendored into maps/ as POOL-ID.json.gz, FFR's file as it is in
its pool's zip, so the build needs nothing outside snes/:

    python3 tools/genmaps.py --vendor normal256 1EAA7BA6

copies one from ../FF1Randomizer/FF1Lib/maps/.

A map's record, 256 bytes (MI_*): where its rows are; its flags (the bridge
horizontal, the map a mirror); the start, the party's tile; where Bikke's
ship waits, the airship, the bridge and the canal, as lut_InitUnsramFirstPage
has the game's; where a Free SHIP waits; the sixteen exits' landings; each
of the overworld's 64 zones' formations, as the zone they are taken from;
and where a found ship moors, by the map it is found on (cur_map).  From
FFR's file as FFR's OwMapExchange writes it: StartingLocation,
AirShipLocation, BridgeLocation, CanalLocation; TeleporterFixups' exits,
the rest the game's; DomainFixups swapped, then DomainUpdates from the
game's zones; HorizontalBridge; and ShipLocations, FFR's dock for each
overworld entrance -- Bikke's ship at Pravoka's, a Free SHIP at the default
(255), a found ship at the dock of the entrance the map it is found on is
behind (FFR's SCLogic.GetShipIndex), else the default.  The game's map's
record is the game's, for the tests; the game reads bank $01's map and the
game's tables for it.

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
mirrored; its docks the game's (lut_ShipDock), mirrored; and its lines that
say east or west say the other (mirror_lines).
"""
import base64, gzip, json, os, re, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import genows

LIST = os.path.join(ROOT, "maps", "custom-maps.txt")
MAPDIR = os.path.join(ROOT, "maps")
FFRMAPS = os.path.join(os.path.dirname(ROOT), "FF1Randomizer", "FF1Lib", "maps")
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
          BRIDGE=0x0A, CANAL=0x0C, FREESHIP=0x0E, EXITX=0x10, EXITY=0x20, DOMAIN=0x30,
          DOCKX=0x70, DOCKY=0xB0, MM=0xF0)
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
    """[(kind, pool, id, name)]: kind 'vanilla', 'mirror-lr' or 'ffr'."""
    out = []
    for n, line in enumerate(open(LIST, encoding="utf-8"), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        if word in ("vanilla", "mirror-lr"):
            out.append((word, None, None, rest))
        else:
            mid, _, name = rest.partition(" ")
            if not mid or not name.strip():
                sys.exit("%s:%d: want POOL ID NAME" % (os.path.relpath(LIST, ROOT), n))
            out.append(("ffr", word, mid, name.strip()))
        if not out[-1][3]:
            sys.exit("%s:%d: a map with no name" % (os.path.relpath(LIST, ROOT), n))
    return out


def vendored(pool, mid):
    return os.path.join(MAPDIR, "%s-%s.json.gz" % (pool, mid))


def vendor(pool, mid):
    zp = os.path.join(FFRMAPS, pool + ".zip")
    if not os.path.exists(zp):
        sys.exit("genmaps: no pool %s (%s)" % (pool, zp))
    z = zipfile.ZipFile(zp)
    if mid + ".json" not in z.namelist():
        near = [n[:-5] for n in z.namelist() if n[:4] == mid[:4]]
        sys.exit("genmaps: no map %s in %s%s" % (mid, pool, " (near: %s)" % ", ".join(near) if near else ""))
    data = z.read(mid + ".json")
    #  mtime 0, so the file is the same bytes whenever it is vendored.
    with open(vendored(pool, mid), "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as g:
            g.write(data)
    print("genmaps: %s" % os.path.relpath(vendored(pool, mid), ROOT))


def ffr_file(pool, mid):
    path = vendored(pool, mid)
    if not os.path.exists(path):
        sys.exit("genmaps: %s is not vendored -- python3 tools/genmaps.py --vendor %s %s"
                 % (os.path.relpath(path, ROOT), pool, mid))
    return json.loads(gzip.open(path).read()), os.path.relpath(path, ROOT)


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


def map_entrances():
    """Each standard map's overworld entrance in the game's wiring: the one
    its floor hangs from (randoref.es_tree), or for the floors the shuffle
    never moves, those of the map whose stairs reach them."""
    import randoref as R
    import graphdata as GD
    out = {}
    for o, _, floors in R.es_tree(GD.VANILLA_ENTRANCE, GD.VANILLA_NORMAL):
        for _, _, (m, _, _), _ in floors:
            out.setdefault(m, o)
    #  Coneria Castle 2F, the Castle of Ordeals' 2F and 3F, and the Temple of
    #  Fiends' past, by the castle's and the temple's stairs.
    for m, by in ((24, 8), (25, 11), (26, 11)) + tuple((m, 12) for m in range(52, 60)):
        out.setdefault(m, out[by])
    missing = [m for m in range(NMAPS) if m not in out]
    if missing:
        sys.exit("genmaps: no entrance for maps %s" % missing)
    return out


def record(kind, d, mirrorinfo=None):
    """A map's record, but its rows' address (MI_ROWBANK, MI_ROWLO)."""
    import logicdata as L
    rec = bytearray(MI_SIZE)
    put = lambda field, xy: rec.__setitem__(slice(MI[field], MI[field] + 2), bytes(xy))
    vex = vanilla_exits()
    freeship = (snes_const("FREESHIP_X"), snes_const("FREESHIP_Y"))
    if kind == "vanilla":
        put("START", vanilla_start())
        put("SHIP", init_xy(U_SHIP))
        put("AIRSHIP", init_xy(U_AIRSHIP))
        put("BRIDGE", init_xy(U_BRIDGE))
        put("CANAL", init_xy(U_CANAL))
        put("FREESHIP", freeship)
        exits = vex
        domains = list(range(64))
        docks = [L.DOCKS[L.SHIP_DOCK[m]][1] for m in range(NMAPS)]
    elif kind == "mirror-lr":
        rec[MI["FLAGS"]] |= MIF_MIRROR
        pos = lambda xy: mirror_pos(mirrorinfo, *xy)
        put("START", pos(vanilla_start()))
        put("SHIP", pos(init_xy(U_SHIP)))
        put("AIRSHIP", pos(init_xy(U_AIRSHIP)))
        put("BRIDGE", pos(init_xy(U_BRIDGE)))
        put("CANAL", pos(init_xy(U_CANAL)))
        put("FREESHIP", pos(freeship))
        exits = [pos(xy) if xy != (0, 0) else xy for xy in vex]
        domains = [(z & ~7) | (7 - (z & 7)) for z in range(64)]
        docks = [pos(L.DOCKS[L.SHIP_DOCK[m]][1]) for m in range(NMAPS)]
    else:
        f, name = d
        xy = lambda v: (v["X"], v["Y"])
        put("START", xy(f["StartingLocation"]))
        put("AIRSHIP", xy(f["AirShipLocation"]))
        put("BRIDGE", xy(f["BridgeLocation"]))
        put("CANAL", xy(f["CanalLocation"]))
        if f.get("HorizontalBridge"):
            rec[MI["FLAGS"]] |= MIF_HBRIDGE
        ships = {s["TeleporterIndex"]: (s["X"], s["Y"]) for s in f["ShipLocations"]}
        if 255 not in ships:
            sys.exit("genmaps: %s has no default dock" % name)
        dock = lambda o: ships.get(o, ships[255])
        put("SHIP", dock(2))                    # Bikke's, Pravoka's entrance
        put("FREESHIP", ships[255])
        exits = list(vex)
        for t in f["TeleporterFixups"] or []:
            if t["Type"] != 1:
                sys.exit("genmaps: %s fixes a teleport of type %d" % (name, t["Type"]))
            exits[t["Index"]] = xy(t["To"])
        domains = list(range(64))
        for df in f.get("DomainFixups") or []:
            domains[df["From"]], domains[df["To"]] = domains[df["To"]], domains[df["From"]]
        for du in f.get("DomainUpdates") or []:
            if not (0 <= du["To"] < 64 and 0 <= du["From"] < 128):
                sys.exit("genmaps: %s moves zone %d to %d" % (name, du["From"], du["To"]))
            domains[du["To"]] = du["From"]
        ent = map_entrances()
        docks = [dock(ent[m]) for m in range(NMAPS)]
    for i, (x, y) in enumerate(exits):
        rec[MI["EXITX"] + i], rec[MI["EXITY"] + i] = x, y
    rec[MI["DOMAIN"]:MI["DOMAIN"] + 64] = bytes(domains)
    for m, (x, y) in enumerate(docks):
        rec[MI["DOCKX"] + m], rec[MI["DOCKY"] + m] = x, y
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
    kind, pool, mid, _ = entry
    if kind == "vanilla":
        return bytes(genows.vanilla()), None, None
    if kind == "mirror-lr":
        t, blocks = mirror_lr(genows.vanilla())
        return t, blocks, None
    f, name = ffr_file(pool, mid)
    rows = [base64.b64decode(r) for r in f["DecompressedMapRows"]]
    if len(rows) != 256 or any(len(r) != 256 for r in rows):
        sys.exit("genmaps: %s is not 256 rows of 256" % name)
    tiles = b"".join(rows)
    if max(tiles) > 0x7F:
        sys.exit("genmaps: %s has a tile past $7F" % name)
    return tiles, None, (f, name)


def main():
    if sys.argv[1:2] == ["--vendor"]:
        if len(sys.argv) != 4:
            sys.exit("usage: genmaps.py --vendor POOL ID")
        vendor(sys.argv[2], sys.argv[3])
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
    recs = [record(e[0], ffr, blocks) for e, (_, blocks, ffr) in zip(entries, maps)]
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
