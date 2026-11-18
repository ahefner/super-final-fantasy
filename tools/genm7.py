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
north of the pivot to full at FOG_FAR -- nothing on the flat view, which
sees 112 north.  And for the objects ConvertOWToSprite places (the ship,
the airship parked, the bridge, the canal), the screen line a point v
pixels north or south of the pivot lands on, and the inverse of each
line's scale, so ow7.asm puts them where the plane shows their tiles.

Out:
    out/ow7.bin      16KB: character n's 64 pixels at n * 64, row by row;
                     from $4000, the tilt's tables, ANGLES' each
    gen/ow7.inc      lut_M7Row: per metatile UL, UR, DL, DR (a row's two
                     lines a word each); lut_M7Col: UL, DL, UR, DR (a
                     column's two); the tilt's constants and, per angle,
                     its tables' addresses in the low half; the docked
                     ship's frames, SHIP_SIZES across, and which to use
                     for a size
"""
import math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.path.join(ROOT, "game")
OUTBIN = os.path.join(ROOT, "out", "ow7.bin")
OUTINC = os.path.join(ROOT, "gen", "ow7.inc")

CHR_OFF = 0x0000        # bank $02 $8000: the overworld's BG pattern table
TSA_OFF = 0x0000        # bank $00 $8000: lut_OWTileset
METATILES = 128

# ---- the tilt: what there is to tune ---------------------------------------
ANGLES = [90, 75, 65, 55, 50, 45]   # degrees; 90 the NES's view.  R steps
                                    #   through them on the overworld (for now)
DEFAULT = 3                         # ...from this one at power-on
CAMERA = 256                        # pixels from the pivot: less, a stronger
                                    #   perspective at the same angle
FOG_NEAR, FOG_FAR = 120, 240        # pixels north of the pivot: no haze nearer,
                                    #   full haze farther
FOG_RGB = (13, 15, 21)              # added at full, 0-31 each
FOG_SUBTRACT = False                # a fade to dark instead of a haze
# ---- the docked ship, drawn at its distance's size (user, 2026-11-18: "The
#      ship needs scaled frames, it still looks too big in the distance") ----
SHIP_SIZES = list(range(8, 23)) + [24]  # pixels across: 16 frames, 16 the game's
# -----------------------------------------------------------------------------
SHIP_ADD = 0x20                     # DrawOWObj_Ship's tile additive (the ship's graphics)
OBJCHR_OFF = 0x1C00                 # bank $02 $9C00: LoadOWObjectCHR's source, sprite tile $10 on
PIVOT_X, PIVOT_LINE = 120, 112      # the player's tile's centre on screen: the
                                    #   NES puts it at x 112-127, NES lines
                                    #   112-127, and the HAL crops 8 lines
LINES = 224
TABLES = 0x4000                     # where the tilt's tables start in ow7.bin
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


def build(chr_, tsa):
    """-> (characters as a list of 64-byte strings, per metatile the four
    corners' character numbers UL, UR, DL, DR)."""
    ul, ur, dl, dr, at = (tsa[0x100 + 0x80 * k:0x180 + 0x80 * k] for k in range(5))
    chars = [bytes(64)]
    index = {chars[0]: 0}
    corners = []
    for m in range(METATILES):
        pal = at[m] & 3
        four = []
        for t in (ul[m], ur[m], dl[m], dr[m]):
            pix = m7_pixels(chr_, t, pal)
            if pix not in index:
                index[pix] = len(chars)
                chars.append(pix)
            four.append(index[pix])
        corners.append(four)
    if len(chars) > SPECIAL:
        sys.exit("genm7: %d characters, past the %d before the bridge's and the canal's" % (len(chars), SPECIAL))
    #  Metatiles $80 and $81, which no map has: the bridge and the canal's
    #  land, flattened into the plane (ow7.asm's m7_objchars draws their
    #  characters at the way in, the sprite over the map's tile under it).
    corners.append([SPECIAL + k for k in range(4)])
    corners.append([SPECIAL + 4 + k for k in range(4)])
    return chars, corners


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


def fog_of(v):
    """The haze, 0 to 1, of a line showing v (north negative)."""
    return min(1.0, max(0.0, (-v - FOG_NEAR) / (FOG_FAR - FOG_NEAR)))


def tilt_tables(vmin, vmax):
    """-> (bytes from TABLES on, per angle its tables' offsets in the chunk)."""
    blob, offs = bytearray(), []
    for angle in ANGLES:
        views = [line_view(angle, y) for y in range(LINES)]
        m7a = [round(256 * s) for _, s, _ in views]
        m7d = [hw_d(v, y) for y, (v, _, _) in enumerate(views)]
        fog = [fog_of(v) for v, _, _ in views]
        rg = []
        for f in fog:
            rg += [0x20 | round(FOG_RGB[0] * f), 0x40 | round(FOG_RGB[1] * f)]
        b = [0x80 | round(FOG_RGB[2] * f) for f in fog]
        kk = bytearray()                # lines -16 to 239, as the objects' table has them
        for y in range(-16, 240):
            kk += round(256 / line_view(angle, y)[1]).to_bytes(2, "little")
        yy = bytearray()
        for v in range(vmin, vmax + 1):
            y = point_line(angle, v)
            y = None if y is None else round(y)
            yy.append(0 if y is None or not -16 <= y <= 238 else y + 16)
        parts = {"A": hdma_words(m7a), "D": hdma_words(m7d),
                 "RG": hdma_words([rg[2 * i] | rg[2 * i + 1] << 8 for i in range(LINES)]),
                 "B": hdma_bytes(b), "K": bytes(kk), "Y": bytes(yy)}
        here = {}
        for k, part in parts.items():
            here[k] = TABLES + len(blob)
            blob += part
        offs.append(here)
    return bytes(blob), offs


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


def ship_frames(img):
    """The ship at each of SHIP_SIZES pixels across, centred in 32x32 (the
    tile's centre at the box's), nearest-neighbour as Mode 7 samples the
    ground; as OBJ table 0 on the overworld holds them: frame j a 4x4 block
    of tiles from tile (j mod 4) * 4 + (j div 4) * 64, SNES 4bpp, the top
    two planes clear.  -> 8KB."""
    out = bytearray(0x2000)
    for j, n in enumerate(SHIP_SIZES):
        f = n / 16
        box = [[0] * 32 for _ in range(32)]
        for dy in range(32):
            for dx in range(32):
                sx, sy = math.floor((dx + 0.5 - 16) / f + 8), math.floor((dy + 0.5 - 16) / f + 8)
                if 0 <= sx < 16 and 0 <= sy < 16:
                    box[dy][dx] = img[sy][sx]
        base = (j % 4) * 4 + (j // 4) * 64
        for tr in range(4):
            for tc in range(4):
                t = base + tr * 16 + tc
                for r in range(8):
                    p0 = p1 = 0
                    for c in range(8):
                        v = box[tr * 8 + r][tc * 8 + c]
                        p0 |= (v & 1) << (7 - c)
                        p1 |= (v >> 1 & 1) << (7 - c)
                    out[t * 32 + 2 * r], out[t * 32 + 2 * r + 1] = p0, p1
    return bytes(out)


def main():
    chr_ = open(os.path.join(GAME, "bank_02.dat"), "rb").read()[CHR_OFF:CHR_OFF + 0x1000]
    tsa = open(os.path.join(GAME, "bank_00.dat"), "rb").read()[TSA_OFF:TSA_OFF + 0x400]
    chars, corners = build(chr_, tsa)
    north, south, west, east = region()
    vmin, vmax = -(north + 1) * 16, (south + 1) * 16
    tables, offs = tilt_tables(vmin, vmax)
    if TABLES + len(tables) > 0x8000:
        sys.exit("genm7: the tilt's tables end at $%04X, past the low half" % (TABLES + len(tables)))
    os.makedirs(os.path.dirname(OUTBIN), exist_ok=True)
    with open(OUTBIN, "wb") as f:
        f.write(b"".join(chars) + bytes(64 * (256 - len(chars))) + tables)
    out = ["; generated by tools/genm7.py -- do not edit",
           "; %d Mode 7 characters (out/ow7.bin, the chunk's low half)" % len(chars),
           "M7_CHARS = %d" % len(chars),
           "M7_SPECIAL = %d          ; the bridge's characters, then the canal's: metatiles $80, $81" % SPECIAL,
           "M7P_ANGLES = %d" % len(ANGLES),
           "M7P_DEFAULT = %d" % DEFAULT,
           "M7P_PIVOTX = %d" % PIVOT_X,
           "M7P_PIVOTLINE = %d" % PIVOT_LINE,
           "M7_NORTH = %d          ; rows kept north of the pivot's, south, columns west, east" % north,
           "M7_SOUTH = %d" % south,
           "M7_WEST = %d" % west,
           "M7_EAST = %d" % east,
           "M7P_VMIN = %d          ; the objects' table: pixels from the pivot, north negative" % vmin,
           "M7P_VMAX = %d" % vmax,
           "M7P_FOGSUB = %d" % (1 if FOG_SUBTRACT else 0)]
    for k in ("A", "D", "RG", "B", "K", "Y"):
        out.append("lut_M7P%s: .WORD %s" % (k, ", ".join("$%04X" % o[k] for o in offs)))
    if len(SHIP_SIZES) != 16:
        sys.exit("genm7: %d ship frames; OBJ table 0 holds 16 of 32x32" % len(SHIP_SIZES))
    ship, ship_pal = ship_source()
    frames = ship_frames(ship)
    out.append("M7SHIP_PAL = %d          ; the docked ship's sprite palette" % ship_pal)
    #  For a size n (8-24, from a line's inverse scale), the nearest frame's
    #  first tile.
    near = [min(range(16), key=lambda j: (abs(SHIP_SIZES[j] - n), -SHIP_SIZES[j])) for n in range(8, 25)]
    out.append("lut_M7ShipTile:          ; sizes 8-24")
    out.append("  .BYTE " + ", ".join("$%02X" % ((j % 4) * 4 + (j // 4) * 64) for j in near))
    out.append("lut_M7Ship:              ; OBJ table 0 on the overworld: the ship's 16 frames")
    for i in range(0, len(frames), 16):
        out.append("  .BYTE " + ", ".join("$%02X" % b for b in frames[i:i + 16]))
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
