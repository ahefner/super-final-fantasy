#!/usr/bin/env python3
"""
genm7.py -- the overworld's Mode 7 characters, out/ow7.bin, and its
metatile tables, gen/ow7.inc (ow7.asm).

Mode 7 has one layer of 8x8 characters, 256 of them, eight bits a pixel,
and a pixel's value is its CGRAM entry.  The NES overworld is 128 metatiles,
each four characters of the overworld's pattern table under one palette.
So a Mode 7 character is a (character, palette) pair drawn out: colour 0 is
0, the backdrop, as on the NES; colour c of palette p is p * 16 + c, the
HAL's CGRAM entry for it (snesmap.inc), so the game's palette, its cycling,
fades, tints and Palette swap reach the plane unchanged.

The pairs are the 128 metatiles' four corners: 236 of them on the game's
map, under the 256.  Pairs whose pixels come out the same share one
character; character 0 is blank, so a cleared plane shows the backdrop.

Read from the game's data: the pattern table from bank $02 at $8000
(LoadOWBGCHR's), the metatiles from bank $00 at $8000 (lut_OWTileset, which
LoadOWTilesetData copies to tileset_data).  No option changes either (the
Japanese tiles are the towns', caves' and battles', and a horizontal
bridge is a sprite); test_m7tiles holds the result to the pattern table and
metatiles the game actually loads.

The tilt (user, 2026-11-17: the later Final Fantasies' airship view, "the
perspective tilts back to let you see slightly farther"; it "should pivot
around the player sprite's location ... anchored at the center of the
screen").  A camera orbits the centre of the player's tile -- screen x 120,
line 112, where the game draws the party and the airship's shadow -- at
CAMERA pixels, looking down at ANGLE degrees: 90 is the NES's view.  Each
screen line is then one depth: the plane's scale across it (M7A) and the
step down the map to it (M7D), an HDMA table each, one entry a line.  At
the pivot both are 1 across, and down 1 / sin(ANGLE): the ground
foreshortens as it should, and the pivot never moves as the angle changes.
For a screen line y, with t = (y - 112) / CAMERA and w = sin + t cos:

    the map row it shows     v = (y - 112) / w   pixels from the pivot's
    the scale across it      sin / w             (M7A, x256)
    the step to it           1 / w               (M7D, x256: v / (y - 112),
                                                  as the hardware rounds it:
                                                  hw_d)

A haze is added the farther north a line looks (COLDATA, additive colour
maths, two HDMA tables: red and green, then blue), from FOG_NEAR pixels
north of the pivot to full at FOG_FAR, its ramp between to FOG_CURVE's
power -- the same at every angle, so an angle between them has it too --
coming in over the first FOG_TILT degrees of tilt: none on the flat view.  And for the objects ow7.asm places (the ship, the airship
parked, the landmarks), the screen line a point v pixels north or south
of the pivot lands on -- south past the screen's bottom, as far as an
object TALLEST high standing there still shows -- and per angle the step
of a line's inverse scale, which is linear in the line, so ow7.asm puts
them where the plane shows their tiles, at its size there.

The landmarks -- the castles, the Temple of Fiends, the Mirage Tower and
the volcano (LANDMARKS) -- stand up as sprites, their art from
art/landmarks/*.png (read_art, which says how they are laid out; --extract
writes a starting point where there is none): each one's metatiles drawn in
the plane as the ground under it, its frames at LAND_KS, and where each
stands on each of Map Select's maps (genmaps.py's), found in their tiles.

Out:
    out/ow7.bin      16KB: character n's 64 pixels at n * 64, row by row
    out/ow7tilt_XX.bin
                     the tilt's tables, in NES chunk XX's low half
                     (TILT_CHUNKS): every angle's objects' lines in the
                     first, its four HDMA tables in one of the others
    gen/ow7.inc      lut_M7Row: per metatile UL, UR, DL, DR (a row's two
                     lines a word each); lut_M7Col: UL, DL, UR, DR (a
                     column's two); the tilt's constants and, per angle,
                     its tables' banks and addresses; the docked
                     ship's frames, SHIP_SIZES across, and which to use
                     for a size; the landmarks' lists, a map each, and
                     their frames' records
    out/ow7land_XX.bin
                     the landmarks' frames, tiles and sprite lists, in
                     NES chunk XX's low half (LAND_CHUNKS)
"""
import math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.join(ROOT, "game")
OUTBIN = os.path.join(ROOT, "out", "ow7.bin")
OUTINC = os.path.join(ROOT, "gen", "ow7.inc")
OUTLAND = os.path.join(ROOT, "out", "ow7land_%02X.bin")
OUTTILT = os.path.join(ROOT, "out", "ow7tilt_%02X.bin")

CHR_OFF = 0x0000        # bank $02 $8000: the overworld's BG pattern table
TSA_OFF = 0x0000        # bank $00 $8000: lut_OWTileset
METATILES = 128

# ---- the tilt: what there is to tune ---------------------------------------
ANGLES = [90 - 40 * i / 32 for i in range(33)]  # degrees: 90, the NES's view, to
                                    #   50 a step a line the airship rises in its
                                    #   take-off (3D Overworld: Airship), $6F to
                                    #   $4F; Always the last (user, 2026-11-20:
                                    #   "from strictly overhead ... to whatever the
                                    #   second-to-last angle available by the
                                    #   current R button selection is", 50 of 90,
                                    #   75, 65, 55, 50, 45)
DEFAULT = ANGLES.index(55)          # with no angle set yet (M7P_DEFAULT): the tests'
CAMERA = 256                        # pixels from the pivot: less, a stronger
                                    #   perspective at the same angle
FOG_NEAR, FOG_FAR = 51, 240         # pixels north of the pivot: no haze nearer,
                                    #   full haze farther
FOG_CURVE = 2                       # the ramp between, its fraction of the way to
                                    #   this power: slow from the bottom (user,
                                    #   2026-11-19: "extend it 32 pixels lower at
                                    #   the max perspective", "more concave, so the
                                    #   ramp starts slower from bottom to top";
                                    #   "don't special case the angle because we
                                    #   need to animate between them") -- at 45
                                    #   degrees from line 80, 32 below where
                                    #   FOG_NEAR 120 began; 1.5 tried, 2 kept
                                    #   ("I think I liked exponent 2 better")
FOG_TILT = 15                       # degrees of tilt it comes in over: none on
                                    #   the flat view, the NES's (user,
                                    #   2026-11-19: "In the flat view there can't
                                    #   be any color step, it needs to look like
                                    #   the original game"), all of it from 75
                                    #   down, part of it at an angle between
FOG_RGB = (13, 15, 21)              # added at full, 0-31 each
FOG_SUBTRACT = False                # a fade to dark instead of a haze
# ---- the docked ship, drawn at its distance's size (user, 2026-11-18: "The
#      ship needs scaled frames, it still looks too big in the distance") ----
SHIP_SIZES = list(range(8, 23)) + [24]  # pixels across: 16 frames, 16 the game's
# ---- the castles, the Temple of Fiends, the Mirage Tower and the volcano,
#      stood up as sprites (user, 2026-11-18: castles that "don't flatten out
#      like they're painted on the ground"; Coneria's first, then "the other
#      castles, mirage tower, and the volcano") -------------------------------
LAND_KS = [n / 16 for n in range(9, 24)]  # their sizes, as inverse scales: 15, 1 among them
#  Each: its name, its art's file in art/landmarks/, and its metatiles row by
#  row -- the plane draws each of them, wherever it is, as the ground under
#  it -- and how --extract cuts a starting point from the map's tiles.
LANDMARKS = [
    ("coneria",   ((0x09, 0x0A), (0x19, 0x1A), (0x01, 0x02)), None),
    #  Northwest Castle, drawn as Elfland Castle on every map (user,
    #  2026-11-21: "Elfland Castle and Northwest share one png such that
    #  Northwest has the same appearance as Elfland Castle (the FFR
    #  style)"): the game's map's, under Coneria's towers...
    ("northwest", ((0x09, 0x0A), (0x29, 0x2A)), dict(ground=(1,), foot=16, art="elfland")),
    #  ...and FFR's drawn maps', under Elfland's
    ("northwest-ffr", ((0x0B, 0x0C), (0x29, 0x2A)), dict(ground=(1,), foot=15, art="elfland")),
    ("elfland",   ((0x0B, 0x0C), (0x1B, 0x1C)), dict(ground=(1,), foot=15)),
    #  The Castle of Ordeals: in a swamp, its PNG -- the swamp drawn back
    #  under it, which the NES's attributes could not -- and on grass,
    #  sand or by the sea, as Elfland Castle (user, 2026-11-21: "it's just
    #  two possibilities - castle on grass, and castle on swamp, with the
    #  same castle image and two different backgrounds"; landmark_art)
    ("ordeals",   ((0x0B, 0x0C), (0x38, 0x39)), dict(ground=(1,), foot=15, art="elfland", swamp="ordeals")),
    #  The Temple of Fiends, with its slab's two ends, which are only ever
    #  beside it (user, 2026-11-21: black pixels on the ground left after
    #  every one was taken out of its PNG -- the small pillar's, in $59):
    #  four across, its top row's corners not its (None: whatever the map
    #  has there, drawn as the map's; in its PNG's ground, magenta with
    #  black stripes, read as nothing -- user: "make it clear that the
    #  ground corners are being ignored by coloring them magenta with some
    #  diagonal caution stripes through it").
    ("temple",    ((None, 0x47, 0x48, None), (0x56, 0x57, 0x58, 0x59)),
                  dict(ground=(1, 2), foot=9, below=30, pillar=(26, 17, 22), fill=1)),
    ("mirage",    ((0x0D,), (0x1D,)),           dict(ground=(2, 3), foot=22, right=11, fillmt=0x45)),
    ("volcano",   ((0x64, 0x65), (0x74, 0x75)), dict(ground=(1,), foot=22)),
]
#  The towns' houses (user, 2026-11-18: "converting the towns to scaled
#  sprites as well.  They don't need shadows"): each one metatile, stood up
#  as one 32x32 sprite at its distance's size, the ground under it plain.
#  How --extract cuts each: its ground colours, the plain one under it.
HOUSES = [
    ("house-coneria",  0x49, dict(ground=(2, 1), foot=16, fill=2)),
    ("house-pravoka",  0x4A, dict(ground=(2, 1), foot=16, fill=2)),
    ("house-elfland",  0x4C, dict(ground=(1,), foot=16, fill=1)),
    ("house-melmond",  0x4D, dict(ground=(1,), foot=16, fill=1)),
    ("house-crescent", 0x4E, dict(ground=(2, 1), foot=16, fill=2)),
    ("house-gaia",     0x5A, dict(ground=(1,), foot=16, fill=1)),
    ("house-onrac",    0x5D, dict(ground=(1,), foot=16, fill=1)),
    ("house-lefein",   0x6D, dict(ground=(2, 1), foot=16, fill=2)),
]
ART = os.path.join(ROOT, "art", "landmarks")
SWAMP = 0x55                        # the marsh's metatile (landmark_art)
VGROUND0 = 0x82                     # each landmark art's ground, a metatile a tile, from
                                    #   here (past the bridge's and canal's $80, $81): every
                                    #   landmark's tiles on every map drawn as its art's
                                    #   ground, wherever two share a metatile (user,
                                    #   2026-11-21: "all of these editable independently")
ART_GAP = 4                         # key-coloured columns between the art and the ground
KEY = (255, 0, 255)                 # the art's "nothing here"
LAND_SLOT = 48                      # tiles a frame may take: three slots, sprite table $70-$FF
LAND_SPRITES = 60                   # sprites a frame may take: the extras past the ship's four
LAND_CHUNKS = (0x0F, 0x0E, 0x0D)    # the frames: these NES chunks' low halves, unused
                                    #   (their code runs at $8000 up; mkrom.py's LOWHALF)
GROUP_NEAR = 6                      # tiles apart at most within a group culled whole
TALLEST = 64                        # pixels an object stands at k 1, at most: the
                                    #   objects' table runs on south till one that
                                    #   tall, its base below the screen, shows none
SHIP_ADD = 0x20                     # DrawOWObj_Ship's tile additive (the ship's graphics)
OBJCHR_OFF = 0x1C00                 # bank $02 $9C00: LoadOWObjectCHR's source, sprite tile $10 on
PIVOT_X, PIVOT_LINE = 120, 112      # the player's tile's centre on screen: the
                                    #   NES puts it at x 112-127, NES lines
                                    #   112-127, and the HAL crops 8 lines
LINES = 224
TILT_CHUNKS = (0x0C, 0x0B, 0x0A)    # the tilt's tables: these NES chunks' low halves,
                                    #   unused (genmaps.py's LOGIC_SLOTS stop short)
RING = 32                           # rows ow7.asm keeps decoded (M7RING)
SPECIAL = 248                       # characters 248-255: the bridge's, the canal's


def nes_tile(chr_, t):
    """Character t of a NES pattern table as 8 rows of 8 colours 0-3."""
    b = chr_[t * 16:t * 16 + 16]
    return [[((b[r] >> (7 - x)) & 1) | (((b[r + 8] >> (7 - x)) & 1) << 1) for x in range(8)]
            for r in range(8)]


def m7_pixels(chr_, t, pal):
    """The Mode 7 character for NES character t under BG palette pal."""
    return bytes((pal * 16 + c) if c else 0 for row in nes_tile(chr_, t) for c in row)


def build(chr_, tsa, ground):
    """-> (characters as a list of 64-byte strings, per metatile the four
    corners' character numbers UL, UR, DL, DR, the characters' numbers by
    their pixels).  A metatile in ground (its 16x16 pixels) is drawn so --
    the landmarks' -- and the characters of its tiles are not made."""
    ul, ur, dl, dr, at = (tsa[0x100 + 0x80 * k:0x180 + 0x80 * k] for k in range(5))
    chars = [bytes(64)]
    index = {chars[0]: 0}
    corners = []
    for m in range(METATILES):
        pal = at[m] & 3
        four = []
        for q, t in enumerate((ul[m], ur[m], dl[m], dr[m])):
            if m in ground:
                pix = bytes(ground[m][(q >> 1) * 8 + y][(q & 1) * 8 + x] for y in range(8) for x in range(8))
            else:
                pix = m7_pixels(chr_, t, pal)
            if pix not in index:
                index[pix] = len(chars)
                chars.append(pix)
            four.append(index[pix])
        corners.append(four)
    return chars, corners, index


def specials(chars, corners):
    """Metatiles $80 and $81, which no map has: the bridge and the canal's
    land, flattened into the plane (ow7.asm's m7_objchars draws their
    characters at the way in, the sprite over the map's tile under it)."""
    corners.append([SPECIAL + k for k in range(4)])
    corners.append([SPECIAL + 4 + k for k in range(4)])
    if len(chars) > SPECIAL:
        sys.exit("genm7: %d characters, past the %d before the bridge's and the canal's" % (len(chars), SPECIAL))


def line_view(angle, y):
    """Screen line y at this angle -> (v, the map pixels north (-) or south
    of the pivot it shows; s, map pixels per screen pixel across it; d, the
    step M7D gives it, v / (y - PIVOT_LINE))."""
    a = math.radians(angle)
    w = math.sin(a) + (y - PIVOT_LINE) / CAMERA * math.cos(a)
    if w < 0.05:
        sys.exit("genm7: at %d degrees line %d is at or past the horizon" % (angle, y))
    return (y - PIVOT_LINE) / w, math.sin(a) / w, 1 / w


def point_line(angle, v):
    """A map point v pixels north (-) or south of the pivot -> the screen
    line it lands on, or None past the horizon."""
    a = math.radians(angle)
    q = 1 - v * math.cos(a) / CAMERA
    if q < 0.05:
        return None
    return PIVOT_LINE + v * math.sin(a) / q


def region():
    """The rows and columns any angle can show, around the tile the pivot
    is in, with a row and a column to spare: (north, south, west, east)."""
    vtop = min(line_view(a, 0)[0] for a in ANGLES)
    vbot = max(line_view(a, LINES - 1)[0] for a in ANGLES)
    smax = max(line_view(a, y)[1] for a in ANGLES for y in (0, LINES - 1))
    north = -math.floor(vtop / 16) + 1
    south = math.floor((15 + vbot) / 16) + 1
    west = -math.floor(-PIVOT_X * smax / 16) + 1
    east = math.floor((15 + (255 - PIVOT_X) * smax) / 16) + 1
    if north + south + 1 > RING or west + east + 1 > 63:
        sys.exit("genm7: the steepest angle shows %d rows by %d columns, past the ring's %d or the plane's 63"
                 % (north + south + 1, west + east + 1, RING))
    return north, south, west, east


def hw_d(v, y):
    """The M7D for screen line y showing the map v pixels from the pivot,
    as the hardware will compute it: it adds D * (VOFS - M7Y) and D * its
    line, each with its low six bits dropped (ares' mode7.cpp), and the
    two need not cancel -- at the pivot's line, D * 113 not a multiple
    of 64 put the pivot a pixel north.  So of the D near v / (y - pivot),
    the one whose sum comes nearest v; any multiple of 64 at the pivot."""
    line = y + 1                    # the hardware's: the screen's first is 1
    want = v * 256
    def got(d):
        return (d * -(PIVOT_LINE + 1) & ~63) + (d * line & ~63)
    if y == PIVOT_LINE:
        return 256
    ideal = round(256 * v / (y - PIVOT_LINE))
    return min(range(ideal - 4, ideal + 5), key=lambda d: (abs(got(d) - want), abs(d - ideal)))


def hdma_words(vals):
    """A repeat-mode HDMA table writing a word a line: 112 lines a header."""
    out = bytearray()
    for i in range(0, len(vals), 112):
        part = vals[i:i + 112]
        out.append(0x80 | len(part))
        for v in part:
            out += (v & 0xFFFF).to_bytes(2, "little")
    return bytes(out + b"\x00")


def hdma_bytes(vals):
    out = bytearray()
    for i in range(0, len(vals), 112):
        part = vals[i:i + 112]
        out.append(0x80 | len(part))
        out += bytes(part)
    return bytes(out + b"\x00")


def fog_of(v, angle):
    """The haze, 0 to 1, of a line showing v (north negative) at this angle."""
    ramp = min(1.0, max(0.0, (-v - FOG_NEAR) / (FOG_FAR - FOG_NEAR))) ** FOG_CURVE
    return min(1.0, (90 - angle) / FOG_TILT) * ramp


def slope(angle):
    """A line's inverse scale is linear in it: k = 1 + (y - 112) cot / CAMERA.
    -> the angle's 65536 cot / CAMERA, k's 8.8 step a line, x256."""
    return round(65536 / math.tan(math.radians(angle)) / CAMERA) if angle < 90 else 0


def line_k(angle, y):
    return 1 + (y - PIVOT_LINE) / math.tan(math.radians(angle)) / CAMERA


def south_reach():
    """The objects' table's last v: past it, at every angle, an object
    TALLEST high, its base there, is below the screen (its k, as m7_project
    has it, unclamped)."""
    v = 0
    while any((lambda y: y is not None and y - TALLEST * line_k(a, y) < LINES)(point_line(a, v))
              for a in ANGLES):
        v += 1
    return v


LINE_LO, LINE_HI = -64, 400             # the objects' lines kept: past them, none


def tilt_tables(vmin, vmax):
    """-> ({chunk: its low half's bytes}, per angle {table: offset}, its
    HDMA tables' chunk).  Every angle's objects' lines (Y) in
    TILT_CHUNKS[0], its four HDMA tables together in whichever of the
    others has room: one bank for the four channels."""
    blobs, offs, banks = {c: bytearray() for c in TILT_CHUNKS}, [], []
    for angle in ANGLES:
        views = [line_view(angle, y) for y in range(LINES)]
        m7a = [round(256 * s) for _, s, _ in views]
        m7d = [hw_d(v, y) for y, (v, _, _) in enumerate(views)]
        fog = [fog_of(v, angle) for v, _, _ in views]
        rg = []
        for f in fog:
            rg += [0x20 | round(FOG_RGB[0] * f), 0x40 | round(FOG_RGB[1] * f)]
        b = [0x80 | round(FOG_RGB[2] * f) for f in fog]
        yy = bytearray()                # each v's line, signed; $8000 none
        for v in range(vmin, vmax + 1):
            y = point_line(angle, v)
            y = None if y is None else round(y)
            yy += (0x8000 if y is None or not LINE_LO <= y <= LINE_HI else y & 0xFFFF).to_bytes(2, "little")
        parts = {"A": hdma_words(m7a), "D": hdma_words(m7d),
                 "RG": hdma_words([rg[2 * i] | rg[2 * i + 1] << 8 for i in range(LINES)]),
                 "B": hdma_bytes(b), "Y": bytes(yy)}
        here = {"Y": len(blobs[TILT_CHUNKS[0]])}
        blobs[TILT_CHUNKS[0]] += parts.pop("Y")
        size = sum(len(p) for p in parts.values())
        c = next((c for c in TILT_CHUNKS[1:] if len(blobs[c]) + size <= 0x8000), None)
        if c is None or len(blobs[TILT_CHUNKS[0]]) > 0x8000:
            sys.exit("genm7: the tilt's tables for %d angles do not fit TILT_CHUNKS' low halves" % len(ANGLES))
        for k, part in parts.items():
            here[k] = len(blobs[c])
            blobs[c] += part
        offs.append(here)
        banks.append(c)
    return blobs, offs, banks


def ship_source():
    """The docked ship as DrawOWObj_Ship draws it: lut_VehicleSprTbl's first
    entry (facing right, from the disassembly), its tiles + SHIP_ADD from
    the object graphics LoadOWObjectCHR loads, each tile's flips applied.
    -> (16x16 colours 0-3, the palette)."""
    asm = open(os.path.join(GAME, "bank_0F.asm")).read()
    row = re.search(r"\.BYTE\s+([^;\n]+)", asm[asm.index("lut_VehicleSprTbl:"):]).group(1)
    vals = [int(v.strip().replace("$", "0x"), 16) for v in row.split(",")]
    chr_ = open(os.path.join(GAME, "bank_02.dat"), "rb").read()[OBJCHR_OFF - 0x100:OBJCHR_OFF + 0x600]
    img = [[0] * 16 for _ in range(16)]
    for e, (qx, qy) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):    # UL, DL, UR, DR
        t, attr = vals[2 * e] + SHIP_ADD, vals[2 * e + 1]
        tile = nes_tile(chr_, t)
        for y in range(8):
            for x in range(8):
                sx = 7 - x if attr & 0x40 else x
                sy = 7 - y if attr & 0x80 else y
                img[qy * 8 + y][qx * 8 + x] = tile[sy][sx]
    return img, vals[1] & 3


def blocks_of(chr_, tsa):
    """Each metatile's 16x16 pixels as the plane has them (pal * 16 + c)."""
    ul, ur, dl, dr, at = (tsa[0x100 + 0x80 * k:0x180 + 0x80 * k] for k in range(5))
    out = []
    for m in range(METATILES):
        pal = at[m] & 3
        b = [[0] * 16 for _ in range(16)]
        for q, t in enumerate((ul[m], ur[m], dl[m], dr[m])):
            pix = m7_pixels(chr_, t, pal)
            for y in range(8):
                for x in range(8):
                    b[(q >> 1) * 8 + y][(q & 1) * 8 + x] = pix[y * 8 + x]
        out.append(b)
    return out


def grid_image(blocks, tiles):
    """A landmark's metatiles' pixels, as the plane has them (pal * 16 + c)."""
    return [[blocks[tiles[y // 16][x // 16]][y % 16][x % 16] for x in range(16 * len(tiles[0]))]
            for y in range(16 * len(tiles))]


def land_palette(tsa, name, tiles):
    """The BG palette of a landmark's metatiles: one, 0 or 1 (its sprites
    are drawn in OBJ palette 4's spare entries, where the HAL copies those
    two: colour c of palette p as 4 + 4p + c)."""
    at = tsa[0x300:0x380]
    pals = {at[m] & 3 for row in tiles for m in row if m is not None}
    if len(pals) != 1 or not pals <= {0, 1}:
        sys.exit("genm7: %s's metatiles take palettes %s, not one of 0 and 1" % (name, sorted(pals)))
    return pals.pop()


def shades():
    """The overworld's shades: [(NES palette entry, CGRAM entry)], from
    snesmap.inc's M7SHADEn_NES and M7SHADEn, each the entry's colour one NES
    step darker (pal_prep's)."""
    text = open(os.path.join(ROOT, "src", "snesmap.inc")).read()
    out = []
    for n in range(8):
        a = re.search(r"^M7SHADE%d_NES\s*=\s*(\d+)" % n, text, re.M)
        b = re.search(r"^M7SHADE%d\s*=\s*(\d+)" % n, text, re.M)
        if not a or not b:
            break
        out.append((int(a.group(1)), int(b.group(1))))
    return out


def darker(nes):
    """An NES colour one step darker, as pal_prep makes a shade."""
    return nes - 0x10 if nes >= 0x10 else 0x0F


def ground_colours(tsa, pal):
    """The colours a landmark's ground may take (user, 2026-11-21): black;
    every overworld BG palette's three, the art's palette's first (so
    a colour two palettes have is the art's); then the shades.  ->
    [(rgb, the plane's value: its CGRAM entry)]."""
    import genpal
    owpal = tsa[0x380:0x3B0]
    out = [(genpal.NESPAL[owpal[0] & 0x3F], 0)]
    for p in [pal] + [q for q in range(4) if q != pal]:
        out += [(genpal.NESPAL[owpal[p * 4 + c] & 0x3F], p * 16 + c) for c in (1, 2, 3)]
    out += [(genpal.NESPAL[darker(owpal[i] & 0x3F)], at) for i, at in shades()]
    return out


def land_colours(tsa, pal):
    """The art's four colours as the game's map palette has them: black (the
    backdrop), then palette pal's three."""
    import genpal
    owpal = tsa[0x380:0x3B0]
    return [genpal.NESPAL[owpal[0] & 0x3F]] + [genpal.NESPAL[owpal[pal * 4 + c] & 0x3F] for c in (1, 2, 3)]


def cut_coneria(img):
    """--extract's Coneria: its top two rows are drawn over grass, its last
    over the courtyard, and the courtyard's top wall runs behind its middle.
    The castle is what is not grass above the wall, and across each row of
    the wall and below, everything from its leftmost such pixel to its
    rightmost, the green at its foot with it.  Under it: grass above the
    wall; from the wall down, its footprint, black (user, 2026-11-18: "a
    full black shape underneath the footprint of the castle")."""
    green = img[0][0]
    yard = img[47][0]
    wall = [y for y in range(16, 32) if img[y][0] != green]
    mask = [[False] * 32 for _ in range(48)]
    for y in range(min(wall)):
        mask[y] = [v != green for v in img[y]]
    #  Its body's width, from its rows over grass just above the wall: the
    #  wall's battlements, past it, stay on the ground.
    body = [x for y in range(min(wall) - 8, min(wall)) for x in range(32) if mask[y][x]]
    for y in range(min(wall), 48):
        ground = img[y][0] if y in wall else yard
        xs = [x for x in range(min(body), max(body) + 1) if img[y][x] not in (ground, green)]
        if xs:
            mask[y] = [min(xs) <= x <= max(xs) for x in range(32)]
    under = [[(green if y < min(wall) else 0) if mask[y][x] else img[y][x] for x in range(32)] for y in range(48)]
    return mask, under


def cut(img, blocks, pal, ground, foot, below=None, right=None, pillar=None, fill=None, fillmt=None):
    """--extract's others: the landmark is every pixel not reached from the
    picture's edge through its ground colours (ground, palette pal's), above
    row below and left of column right -- past row pillar[0], only columns
    pillar[1]-pillar[2] -- and from row foot down each row's span of it
    whole.  Under it: from foot down black, its footprint; above, ground
    colour fill, or metatile fillmt's pixels."""
    h, w = len(img), len(img[0])
    below = h if below is None else below
    right = w - 1 if right is None else right
    gset = {pal * 16 + c for c in ground}
    ext = [[x > right or y >= below for x in range(w)] for y in range(h)]
    todo = [(x, y) for y in range(below) for x in range(right + 1)
            if (y == 0 or x == 0 or x == right) and img[y][x] in gset]
    for x, y in todo:
        ext[y][x] = True
    while todo:
        x, y = todo.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not ext[ny][nx] and img[ny][nx] in gset:
                ext[ny][nx] = True
                todo.append((nx, ny))
    mask = [[not ext[y][x] for x in range(w)] for y in range(h)]
    if pillar:
        for y in range(pillar[0], h):
            mask[y] = [m and pillar[1] <= x <= pillar[2] for x, m in enumerate(mask[y])]
    for y in range(foot, h):
        xs = [x for x in range(w) if mask[y][x]]
        if xs:
            mask[y] = [min(xs) <= x <= max(xs) for x in range(w)]
    under = [[(0 if y >= foot else blocks[fillmt][y % 16][x % 16] if fillmt is not None
               else pal * 16 + (fill or ground[0])) if mask[y][x] else img[y][x]
              for x in range(w)] for y in range(h)]
    return mask, under


def art_of(name):
    """The PNG a landmark is drawn from, without its .png: its name, or the
    art it shares (LANDMARKS' art)."""
    for n, _, how in LANDMARKS:
        if n == name:
            return (how or {}).get("art", n)
    return name


def art_names():
    """Every landmark art's PNG's name: each art_of's, each swamp art."""
    return {art_of(n) for n, _, _ in LANDMARKS} | {how["swamp"] for _, _, how in LANDMARKS if how and "swamp" in how}


def landmark_art(name, t, x, y):
    """The art landmark NAME is drawn from at column x, bottom row y of map
    tiles t: its swamp art (LANDMARKS' swamp) where at least half the
    tiles beside it -- above, below, left and right, not the corners --
    are marsh, else art_of(name)."""
    tiles, how = next((tl, h or {}) for n, tl, h in LANDMARKS if n == name)
    if "swamp" in how:
        rows, cols, top = len(tiles), len(tiles[0]), y - len(tiles) + 1
        at = lambda cx, cy: t[(cy & 255) * 256 + (cx & 255)]
        edge = [at(x + c, top - 1) for c in range(cols)] + [at(x + c, y + 1) for c in range(cols)] + \
               [at(x - 1, top + r) for r in range(rows)] + [at(x + cols, top + r) for r in range(rows)]
        if 2 * sum(1 for m in edge if m == SWAMP) >= len(edge):
            return how["swamp"]
    return art_of(name)


def art_tiles(art):
    """The metatiles of the landmark an art is named for: its palette's."""
    return next(t for n, t, _ in LANDMARKS if n == art)


def house_or_art(name):
    return name in art_names() or name in [n for n, _, _ in HOUSES]


def extract(blocks, tsa):
    """--extract: each landmark's art, cut from its metatiles, into
    art/landmarks/NAME.png, where there is none: a starting point, to be
    retouched by hand (user, 2026-11-18: "extracting these and the
    corresponding shadows to a PNG file for manual editing")."""
    import pngio
    for name, tiles, how in LANDMARKS + [(n, ((m,),), how) for n, m, how in HOUSES]:
        if not house_or_art(name):
            continue                        # (another's art)
        if any(m is None for row in tiles for m in row):
            print("genm7: %s's art is not cut here (its corners are not its); draw it by hand" % name)
            continue
        path = os.path.join(ART, name + ".png")
        if os.path.exists(path):
            print("genm7: %s is there; left as it is" % os.path.relpath(path, ROOT))
            continue
        pal = land_palette(tsa, name, tiles)
        img = grid_image(blocks, tiles)
        mask, under = cut_coneria(img) if how is None else cut(img, blocks, pal, **how)
        w = len(img[0])
        code = lambda v: 1 + (v & 3)            # black 1, colour c 1 + c
        idx = [[code(img[y][x]) if mask[y][x] else 0 for x in range(w)] + [0] * ART_GAP +
               [code(under[y][x]) for x in range(w)] for y in range(len(img))]
        pngio.png_write_indexed(path, idx, [KEY] + land_colours(tsa, pal))
        print("genm7: wrote %s" % os.path.relpath(path, ROOT))


def read_art(tsa, name, tiles, wide=True):
    """art/landmarks/NAME.png -> (the landmark standing, as tall as it is,
    None where it is not; the ground under it, its metatiles' pixels; its
    base, the row past its lowest; its palette).  Left, the landmark, the
    key colour (or a clear pixel) where it is not -- as wide as its
    metatiles, or wider to the right if wide (user, 2026-11-21: the Mirage
    Tower's shadow, moved from the ground to the sprite, two pixels past
    its tile), its anchor the middle of its metatiles' width either way;
    ART_GAP columns; right, the ground, as wide as its metatiles.  The landmark's pixels the nearest of black, the palette's
    three and the key; the ground's, of black, every overworld BG
    palette's colours and the shades (ground_colours), never the key."""
    import pngio
    pal = land_palette(tsa, name, tiles)
    cols = land_colours(tsa, pal)
    path = os.path.join(ART, name + ".png")
    rel = os.path.relpath(path, ROOT)
    if not os.path.exists(path):
        sys.exit("genm7: no %s (tools/genm7.py --extract writes a starting point)" % rel)
    w, h = 16 * len(tiles[0]), 16 * len(tiles)
    pw, ph, rows, _ = pngio.png_read(path)
    fw = pw - ART_GAP - w                   # the landmark's columns
    if ph != h or fw < w or (fw != w and not wide):
        sys.exit("genm7: %s is %dx%d, not %s x %d: the landmark, %d columns%s; %d; the ground, %d"
                 % (rel, pw, ph, ("%d or more" % (2 * w + ART_GAP)) if wide else 2 * w + ART_GAP, h, w,
                    " or more" if wide else "", ART_GAP, w))
    choice = [KEY] + cols
    def val(px):
        if px[3] < 128:
            return None
        i = min(range(5), key=lambda i: sum((px[k] - choice[i][k]) ** 2 for k in range(3)))
        return None if i == 0 else 0 if i == 1 else pal * 16 + i - 1
    stand = [[val(rows[y][x]) for x in range(fw)] for y in range(h)]
    gcols = ground_colours(tsa, pal)

    def gval(px):
        if px[3] < 128:
            return None
        rgb, v = min(gcols, key=lambda cv: sum((px[k] - cv[0][k]) ** 2 for k in range(3)))
        if sum((px[k] - KEY[k]) ** 2 for k in range(3)) < sum((px[k] - rgb[k]) ** 2 for k in range(3)):
            return None
        return v
    under = [[gval(rows[y][fw + ART_GAP + x]) if tiles[y // 16][x // 16] is not None else None
              for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if under[y][x] is None and tiles[y // 16][x // 16] is not None:
                sys.exit("genm7: %s: the ground at (%d, %d) is the key colour" % (rel, x, y))
    shown = [y for y in range(h) if any(v is not None for v in stand[y])]
    if not shown:
        sys.exit("genm7: %s has nothing standing" % rel)
    base = max(shown) + 1
    return stand[:base], under, base, pal


def land_frames(fig, base, ax):
    """A landmark at each of LAND_KS, anchored at its base, column ax: for
    each, the 8x8 tiles that have any of it (SNES 4bpp, colour c of BG
    palette p as 4 + 4p + c, black 4: OBJ palette 4's spare entries), and
    the sprites, (dx, dy, tile), dx and dy the tile's corner from the
    anchor.  A screen pixel (ox, oy) from the anchor shows its pixel (ax +
    (ox + 0.5) / k, base + (oy + 0.5) / k), nearest-neighbour; at k 1
    exactly its pixel."""
    out = []
    width = len(fig[0])
    for k in LAND_KS:
        tiles, sprites = [], []
        left, right = math.ceil(ax * k / 8) * 8, math.ceil((width - ax) * k / 8) * 8
        tall = math.ceil(base * k / 8) * 8
        for dy in range(-tall, 0, 8):
            for dx in range(-left, right, 8):
                pix = []
                for y in range(8):
                    for x in range(8):
                        sx = math.floor(ax + (dx + x + 0.5) / k)
                        sy = math.floor(base + (dy + y + 0.5) / k)
                        v = fig[sy][sx] if 0 <= sx < width and 0 <= sy < base else None
                        pix.append(0 if v is None else 4 if v == 0 else 4 + 4 * (v >> 4) + (v & 3))
                if any(pix):
                    t = bytearray(32)
                    for y in range(8):
                        for x in range(8):
                            v = pix[y * 8 + x]
                            for plane in range(4):
                                if v >> plane & 1:
                                    t[(16 if plane >= 2 else 0) + 2 * y + (plane & 1)] |= 0x80 >> x
                    sprites.append((dx, dy, len(tiles)))
                    tiles.append(bytes(t))
        out.append((tiles, sprites))
    return out


def block_tiles(box):
    """A 32x32 box of colours 0-15 as a 32x32 sprite's 4x4 tiles, SNES 4bpp:
    -> (each row of four tiles with any colour in it, 128 bytes, the rows
    end to end; their mask, bit r row r).  A row with none is not stored:
    the upload writes it from a zero."""
    data, mask = bytearray(), 0
    for tr in range(4):
        row = bytearray()
        for tc in range(4):
            t = bytearray(32)
            for r in range(8):
                for c in range(8):
                    v = box[tr * 8 + r][tc * 8 + c]
                    for plane in range(4):
                        if v >> plane & 1:
                            t[(16 if plane >= 2 else 0) + 2 * r + (plane & 1)] |= 0x80 >> c
            row += t
        if any(row):
            data += row
            mask |= 1 << tr
    return bytes(data), mask


def house_frames(fig, base, ax):
    """A house at each of LAND_KS in a 32x32 box, its base's middle at the
    box's bottom middle: box pixel (bx, by) shows its pixel (ax + (bx - 16
    + 0.5) / k, base + (by - 32 + 0.5) / k), colour c of BG palette p as 4 +
    4p + c, black 4, as the landmarks' are.  -> [(rows, mask)]."""
    out = []
    width = len(fig[0])
    for k in LAND_KS:
        box = [[0] * 32 for _ in range(32)]
        for by in range(32):
            for bx in range(32):
                sx = math.floor(ax + (bx - 16 + 0.5) / k)
                sy = math.floor(base + (by - 32 + 0.5) / k)
                v = fig[sy][sx] if 0 <= sx < width and 0 <= sy < base else None
                if v is not None:
                    box[by][bx] = 4 if v == 0 else 4 + 4 * (v >> 4) + (v & 3)
        if base * k > 32 or width * k > 32:
            sys.exit("genm7: a house past its 32x32 box at k %.3f" % k)
        out.append(block_tiles(box))
    return out


def ship_frames(img):
    """The docked ship at each of SHIP_SIZES pixels across, centred in a
    32x32 box (the tile's centre at the box's), nearest-neighbour as Mode 7
    samples the ground, its colours 0-3 of its sprite palette.
    -> [(rows, mask)]."""
    out = []
    for n in SHIP_SIZES:
        f = n / 16
        box = [[0] * 32 for _ in range(32)]
        for dy in range(32):
            for dx in range(32):
                sx, sy = math.floor((dx + 0.5 - 16) / f + 8), math.floor((dy + 0.5 - 16) / f + 8)
                if 0 <= sx < 16 and 0 <= sy < 16:
                    box[dy][dx] = img[sy][sx]
        out.append(block_tiles(box))
    return out


def groups_of(members):
    """Members [(record, x, bottom row)] into groups culled whole: those
    within GROUP_NEAR tiles of one another, by way of others (wrapping).
    -> [(members, lowest row, rows spanned less one, lowest column, columns
    spanned less one)], each group's span measured from its first member,
    its members the southmost first."""
    near = lambda a, b: abs((a[1] - b[1] + 128) % 256 - 128) <= GROUP_NEAR and \
        abs((a[2] - b[2] + 128) % 256 - 128) <= GROUP_NEAR
    left, out = list(members), []
    while left:
        group, todo = [left.pop(0)], None
        todo = [group[0]]
        while todo:
            m = todo.pop()
            for o in [o for o in left if near(m, o)]:
                left.remove(o)
                group.append(o)
                todo.append(o)
        x0, y0 = group[0][1], group[0][2]
        #  The nearest first: the southmost row; in a row its houses of an
        #  art together (one record, placed once), then its landmarks.
        group.sort(key=lambda m: (-((m[2] - y0 + 128) % 256 - 128), not m[0][0] & 0x80, m[0][0], m[0][5], m[1]))
        dxs = [(m[1] - x0 + 128) % 256 - 128 for m in group]
        dys = [(m[2] - y0 + 128) % 256 - 128 for m in group]
        out.append((group, (y0 + min(dys)) & 255, max(dys) - min(dys),
                    (x0 + min(dxs)) & 255, max(dxs) - min(dxs)))
    return out


def find_landmarks(t, what):
    """Where each landmark is on a map (65,536 tiles): [(its index in
    LANDMARKS and then HOUSES, its left column, its bottom row)].  A landmark's metatile
    anywhere but in one whole is an error: the plane draws it as ground."""
    found, covered = [], set()
    for i, (name, tiles, _) in enumerate(LANDMARKS + [(n, ((m,),), how) for n, m, how in HOUSES]):
        rows, cols = len(tiles), len(tiles[0])
        r0, c0 = next((r, c) for r in range(rows) for c in range(cols) if tiles[r][c] is not None)
        at = t.find(bytes([tiles[r0][c0]]))
        while at >= 0:
            x, y = ((at & 255) - c0) & 255, ((at >> 8) - r0) & 255
            cells = [(((y + r) & 255) * 256 + ((x + c) & 255), tiles[r][c])
                     for r in range(rows) for c in range(cols) if tiles[r][c] is not None]
            if all(t[p] == m for p, m in cells):
                found.append((i, x, (y + rows - 1) & 255))
                covered.update(p for p, _ in cells)
            at = t.find(bytes([tiles[r0][c0]]), at + 1)
    alls = {m for _, tiles, _ in LANDMARKS for row in tiles for m in row if m is not None} | \
        {m for _, m, _ in HOUSES}
    stray = [(p & 255, p >> 8, t[p]) for p in range(65536) if t[p] in alls and p not in covered]
    if stray:
        sys.exit("genm7: %s has landmark tiles not in a whole landmark: %s"
                 % (what, ", ".join("$%02X at (%d, %d)" % (m, x, y) for x, y, m in stray[:6])))
    return found


def main():
    chr_ = open(os.path.join(GAME, "bank_02.dat"), "rb").read()[CHR_OFF:CHR_OFF + 0x1000]
    tsa = open(os.path.join(GAME, "bank_00.dat"), "rb").read()[TSA_OFF:TSA_OFF + 0x400]
    blocks = blocks_of(chr_, tsa)
    if sys.argv[1:] == ["--extract"]:
        extract(blocks, tsa)
        return
    #  The landmarks' and the houses' art.  A house's metatile is drawn in
    #  the plane as the ground under it.  A landmark's tiles are drawn as
    #  its art's ground, each tile a separate metatile from VGROUND0 on
    #  (vground), which ow7.asm puts in their place as it decodes a row
    #  (the ground tables below): two landmarks sharing a metatile need not
    #  share a ground.  The metatile itself takes the first ground found
    #  (none is drawn so).  A landmark's picture is an 8x8-sprite art, a
    #  house's a 32x32 one: arts the same picture share their frames.
    arts, barts, kinds, ground, owner, vground, vid, artinfo, under_of = [], [], [], {}, {}, [], {}, {}, {}

    def take(name, tiles, art, house):
        """art's PNG, read once, for a landmark or house of these metatiles:
        -> (its frames' art, base, rows, width)."""
        if not house and [len(r) for r in art_tiles(art)] != [len(r) for r in tiles]:
            sys.exit("genm7: %s shares %s.png, a different shape" % (name, art))
        if art not in under_of:
            under_of[art] = read_art(tsa, art, tiles if house else art_tiles(art), wide=not house)
        fig, under, base, pal = under_of[art]
        for r, row in enumerate(tiles):
            for c, m in enumerate(row):
                if m is None:
                    continue                    # (not its: the map's tile)
                block = [under[r * 16 + y][c * 16:c * 16 + 16] for y in range(16)]
                if house and m in ground and ground[m] != block:
                    sys.exit("genm7: metatile $%02X's ground differs in art/landmarks/%s.png and %s.png"
                             % (m, owner[m], name))
                if m not in ground:
                    ground[m], owner[m] = block, art
                if not house and (art, r, c) not in vid:
                    vid[(art, r, c)] = VGROUND0 + len(vground)
                    vground.append(block)
        if art in artinfo:
            return artinfo[art]
        pool = barts if house else arts
        ax = 8 * len(tiles[0])                  # its anchor: its metatiles' middle
        key = (tuple(map(tuple, fig)), base, ax)
        if key not in [a[0] for a in pool]:
            pool.append((key, fig, base, ax))
        a = [a[0] for a in pool].index(key) + (1 if house else 0)   # (the ship is 32x32 art 0)
        artinfo[art] = ((0x80 | a) if house else a, base, len(tiles), 16 * len(tiles[0]))
        return artinfo[art]
    everything = [(n, t, False) for n, t, _ in LANDMARKS] + [(n, ((m,),), True) for n, m, _ in HOUSES]
    for name, tiles, house in everything:
        kinds.append(take(name, tiles, name if house else art_of(name), house))
        how = {} if house else next(h for n, _, h in LANDMARKS if n == name) or {}
        if "swamp" in how:
            take(name, tiles, how["swamp"], False)
    chars, corners, index = build(chr_, tsa, ground)
    specials(chars, corners)
    for block in vground:
        four = []
        for q in range(4):
            pix = bytes(block[(q >> 1) * 8 + y][(q & 1) * 8 + x] for y in range(8) for x in range(8))
            if pix not in index:
                index[pix] = len(chars)
                chars.append(pix)
            four.append(index[pix])
        corners.append(four)
    if len(chars) > SPECIAL or len(corners) > 256:
        sys.exit("genm7: %d characters, past the %d before the bridge's and the canal's" % (len(chars), SPECIAL))
    if len(arts) > 15 or len(barts) + 1 > 15:
        sys.exit("genm7: %d and %d arts; a frame is named art * 16 + size, $FF none" % (len(arts), len(barts) + 1))
    #  The landmarks' frames: every sprite list in LAND_CHUNKS[0]'s low half
    #  (ow7.asm reads them from one bank): its corner's place from the
    #  anchor, the last sprite's (signed), and each sprite's from that corner
    #  with its tile.  Their tiles, and the houses' and the ship's rows, in
    #  whichever of LAND_CHUNKS has room.
    allframes = [land_frames(fig, base, ax) for _, fig, base, ax in arts]
    blobs = {c: bytearray() for c in LAND_CHUNKS}
    sprat = []
    for frames in allframes:
        for tiles, sprites in frames:
            if not tiles or len(tiles) > LAND_SLOT or len(sprites) > LAND_SPRITES:
                sys.exit("genm7: a landmark's frame takes %d tiles and %d sprites, not 1-%d and %d"
                         % (len(tiles), len(sprites), LAND_SLOT, LAND_SPRITES))
            x0, y0 = min(dx for dx, _, _ in sprites), min(dy for _, dy, _ in sprites)
            x1, y1 = max(dx for dx, _, _ in sprites), max(dy for _, dy, _ in sprites)
            sprat.append(len(blobs[LAND_CHUNKS[0]]))
            blobs[LAND_CHUNKS[0]] += bytes(v & 0xFF for v in (x0, x1, y0, y1))
            blobs[LAND_CHUNKS[0]] += bytes(b for dx, dy, t in sprites for b in (dx - x0, dy - y0, t, 0))
    def place(size):
        room = [c for c in LAND_CHUNKS if len(blobs[c]) + size <= 0x8000]
        if not room:
            sys.exit("genm7: the landmarks' frames past %s's low halves" % ", ".join("$%02X" % c for c in LAND_CHUNKS))
        return room[0]
    records = []
    for frames in allframes:
        c = place(sum(32 * len(t) for t, _ in frames))
        for tiles, sprites in frames:
            records.append((len(blobs[c]), 0xC1 + c, sprat[len(records)], len(tiles), len(sprites)))
            blobs[c] += b"".join(tiles)
    #  The 32x32 frames: the docked ship's (art 0, SHIP_SIZES), the houses'.
    ship, ship_pal = ship_source()
    bframes = [ship_frames(ship)] + [house_frames(fig, base, ax) for _, fig, base, ax in barts]
    brecords = []
    for frames in bframes:
        c = place(sum(len(d) for d, _ in frames))
        recs = []
        for data, mask in frames:
            recs.append((len(blobs[c]), 0xC1 + c, mask))
            blobs[c] += data
        brecords.append(recs + [(0, 0, 0)] * (16 - len(recs)))
    #  Where they stand on each of Map Select's maps (genmaps.py's list), in
    #  groups culled whole.
    import genmaps
    lists, grounds = [], []
    for entry in genmaps.parse():
        members, here = [], {}
        mt = bytes(genmaps.tiles_of(entry)[0])
        for k, x, y in find_landmarks(mt, entry[3]):
            art, base, rows, width = kinds[k]
            if k < len(LANDMARKS):
                name, tiles, _ = LANDMARKS[k]
                file = landmark_art(name, mt, x, y)
                art, base, rows, width = artinfo[file]
                for r, row in enumerate(tiles):
                    for c in [c for c in range(len(row)) if row[c] is not None]:
                        here.setdefault((y - rows + 1 + r) & 255, []).append(((x + c) & 255, vid[(file, r, c)]))
            #  In front of the party when it is north of the top row: on
            #  any tile of it, the party is in front (user, 2026-11-19).
            top = (y - rows + 1) & 255
            rec = (art, x, y, top,
                   (width // 2 - 8) & 0xFF, (base - (rows - 1) * 16 - 8) & 0xFF)
            members.append((rec, x, y, everything[k][0]))
        lists.append(groups_of(members))
        grounds.append(here)
    #  The ground tables, after the characters (M7G_TABLES): per map 256
    #  words, a row's record's address or 0; then the records: how many,
    #  then each one's column and metatile.
    gtab = bytearray(512 * len(grounds))
    for mi, here in enumerate(grounds):
        for row, cells in sorted(here.items()):
            at = 0x4000 + len(gtab)
            gtab[mi * 512 + 2 * row:mi * 512 + 2 * row + 2] = at.to_bytes(2, "little")
            gtab += bytes([len(cells)]) + bytes(b for col, m in sorted(cells) for b in (col, m))
    if 0x4000 + len(gtab) > 0x8000:
        sys.exit("genm7: the ground tables end at $%04X, past the low half" % (0x4000 + len(gtab)))
    north, south, west, east = region()
    vmin, vmax = -(north + 1) * 16, max((south + 1) * 16, south_reach())
    tblobs, offs, banks = tilt_tables(vmin, vmax)
    os.makedirs(os.path.dirname(OUTBIN), exist_ok=True)
    with open(OUTBIN, "wb") as f:
        f.write(b"".join(chars) + bytes(64 * (256 - len(chars))) + bytes(gtab))
    for c, blob in tblobs.items():
        with open(OUTTILT % c, "wb") as f:
            f.write(bytes(blob))
    out = ["; generated by tools/genm7.py -- do not edit",
           "; %d Mode 7 characters (out/ow7.bin, the chunk's low half)" % len(chars),
           "M7_CHARS = %d" % len(chars),
           "M7_SPECIAL = %d          ; the bridge's characters, then the canal's: metatiles $80, $81" % SPECIAL,
           "M7P_ANGLES = %d" % len(ANGLES),
           "M7P_DEFAULT = %d" % DEFAULT,
           "M7P_YFAR = $%06X          ; the objects' lines' bank (TILT_CHUNKS' first)"
           % (0xC00000 + (1 + TILT_CHUNKS[0]) * 0x10000),
           "M7P_PIVOTX = %d" % PIVOT_X,
           "M7P_PIVOTLINE = %d" % PIVOT_LINE,
           "M7_NORTH = %d          ; rows kept north of the pivot's, south, columns west, east" % north,
           "M7_SOUTH = %d" % south,
           "M7_WEST = %d" % west,
           "M7_EAST = %d" % east,
           "M7P_VMIN = %d          ; the objects' table: pixels from the pivot, north negative" % vmin,
           "M7P_VMAX = %d" % vmax,
           "M7P_FOGSUB = %d" % (1 if FOG_SUBTRACT else 0),
           "M7G_TABLES = $4000          ; the ground tables: per map 256 words, then the records",
           "M7G_FIRST = $%02X           ; the landmarks' grounds' metatiles, %d of them" % (VGROUND0, len(vground))]
    for k in ("A", "D", "RG", "B", "Y"):
        out.append("lut_M7P%s: .WORD %s" % (k, ", ".join("$%04X" % o[k] for o in offs)))
    out.append("lut_M7PBank: .BYTE %s          ; the HDMA tables' bank"
               % ", ".join("$%02X" % (0xC1 + c) for c in banks))
    out.append("lut_M7PS: .WORD %s          ; k's step a line, x65536" % ", ".join("$%04X" % slope(a) for a in ANGLES))
    if len(SHIP_SIZES) != 16:
        sys.exit("genm7: %d ship frames; a 32x32 art has 16" % len(SHIP_SIZES))
    out.append("M7SHIP_PAL = %d          ; the docked ship's sprite palette" % ship_pal)
    #  For a size n (8-24, from a line's inverse scale), the nearest frame.
    near = [min(range(16), key=lambda j: (abs(SHIP_SIZES[j] - n), -SHIP_SIZES[j])) for n in range(8, 25)]
    out.append("lut_M7ShipSize:          ; sizes 8-24: the docked ship's frame")
    out.append("  .BYTE " + ", ".join("%d" % j for j in near))
    out.append("M7L_FRAMES = %d          ; a landmark's sizes: k M7L_K0 / 16 on, a sixteenth apart" % len(LAND_KS))
    out.append("M7L_K0 = %d" % round(LAND_KS[0] * 16))
    out.append("M7L_SLOT = %d            ; tiles a frame may take" % LAND_SLOT)
    out.append("M7L_SPRITES = %d         ; sprites a frame may take" % LAND_SPRITES)
    out.append("M7L_MAPS = %d             ; Map Select's maps, a list each" % len(lists))
    out.append("M7L_REC = 6              ; a landmark's record: art, column, bottom row, top")
    out.append("                         ;   row (in front of a party north of it), x and y")
    out.append("                         ;   offsets")
    out.append("M7L_ROW = 5              ; a row of houses' record: $80 + their 32x32 art, the")
    out.append("                         ;   row, the row again (in front of a party north of it),")
    out.append("                         ;   the y offset, how many; then each one's column, west")
    out.append("                         ;   to east")
    out.append("M7L_GROUP = 6            ; a group's header: records (0 past the last), its")
    out.append("                         ;   last bottom row, the window m7_lands takes it in (35")
    out.append("                         ;   rows widened by those it spans), its last column, its")
    out.append("                         ;   window (37 columns, so), its records' bytes")
    out.append("lut_M7LMaps:")
    out.append("  .WORD " + ", ".join("m7l_map%d" % i for i in range(len(lists))))
    for i, groups in enumerate(lists):
        out.append("m7l_map%d:" % i)
        for members, y0, ys, x0, xs in groups:
            #  A row's houses of one art, one record: placed together.
            recs = []
            for rec, x, y, name in members:
                last = recs[-1] if recs else None
                if rec[0] & 0x80 and last and last[0] == "row" and last[1][0] == rec[0] and \
                        last[1][2] == rec[2] and last[1][5] == rec[5]:
                    last[2].append(x)
                    last[3].append(name)
                elif rec[0] & 0x80:
                    if rec[4] != 0:
                        sys.exit("genm7: a house not centred in its metatile")
                    recs.append(["row", rec, [x], [name]])
                else:
                    recs.append(["one", rec, name])
            body = []
            for r in recs:
                if r[0] == "one":
                    body.append("  .BYTE %d, %d, %d, %d, $%02X, $%02X   ; %s" % (r[1] + (r[2],)))
                else:
                    art, x, y, front, ox, oy = r[1]
                    cols = sorted(r[2])
                    body.append("  .BYTE $%02X, %d, %d, $%02X, %d, %s   ; %s" % (
                        art, y, front, oy, len(cols), ", ".join("%d" % c for c in cols), r[3][0]))
            size = sum(6 if r[0] == "one" else 5 + len(r[2]) for r in recs)
            if size > 255:
                sys.exit("genm7: a group of %d bytes" % size)
            out.append("  .BYTE %d, %d, %d, %d, %d, %d" % (len(recs), (y0 + ys) & 255, 35 + ys,
                                                       (x0 + xs) & 255, 37 + xs, size))
            out += body
        out.append("  .BYTE 0")
    out.append("M7L_SPRCHUNK = $%02X       ; the chunk whose low half has the sprite lists" % LAND_CHUNKS[0])
    out.append("lut_M7LFrame:            ; per art, 16 sizes (the last unused): its tiles' address")
    out.append("                         ;   and bank, its sprite list's, how many of each")
    for i, (at, bank, spr, nt, ns) in enumerate(records):
        out.append("  .WORD $%04X" % at)
        out.append("  .BYTE $%02X" % bank)
        out.append("  .WORD $%04X" % spr)
        out.append("  .BYTE %d, %d, 0" % (nt, ns))
        if i % len(LAND_KS) == len(LAND_KS) - 1:
            out.append("  .BYTE 0, 0, 0, 0, 0, 0, 0, 0")
    out.append("lut_M7BFrame:            ; per 32x32 art (the ship's, the houses'), 16 sizes: its")
    out.append("                         ;   rows' address and bank, which rows")
    for recs in brecords:
        for at, bank, mask in recs:
            out.append("  .WORD $%04X" % at)
            out.append("  .BYTE $%02X, $%02X" % (bank, mask))
    for c in LAND_CHUNKS:
        with open(OUTLAND % c, "wb") as f:
            f.write(bytes(blobs[c]))
    out += ["lut_M7Row:"]
    for m, (a, b, c, d) in enumerate(corners):
        out.append("  .BYTE $%02X, $%02X, $%02X, $%02X   ; metatile $%02X" % (a, b, c, d, m))
    out.append("lut_M7Col:")
    for m, (a, b, c, d) in enumerate(corners):
        out.append("  .BYTE $%02X, $%02X, $%02X, $%02X   ; metatile $%02X" % (a, c, b, d, m))
    with open(OUTINC, "w") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
