"""dwarfref.py -- FUN%'s Exploding Dwarf as fun.asm runs it.

The user's (2026-11-03, fun-percent.txt; "Hurray dwarf only", "I want to
watch him explode again and again"), after tenes's 2021 particle hack
(commit 72995c0): the Hurray dwarf in the Dwarf Cave bursts into blood,
bones and his skull, which fly, fall and come to rest on the floor.  The
NES-side overlay of a thousand pixels does not go to the SNES; this is
the sprites' version -- PARTICLES gibs in OAM entries the NES never uses,
each an 8x8 tile of the gib set (GIBS), in the cartridge's own integer
arithmetic so that test_dwarf can hold fun.asm to it frame for frame.

Units: positions and speeds in 1/256 px, per frame; x right, y down the
screen, z up from the floor.  A particle's place is relative to the
origin, the dwarf's feet as his sprite is drawn.
"""

PARTICLES = 56
GRAVITY = 12                    # 1/256 px per frame, per frame
REST_VZ = 0x30                  # a bounce slower than this comes to rest

#  The classes: (count, first tile, tile mask, palette, z base, z mask,
#  vx mask, vy mask, vz base, vz mask, bounces, tile once resting).
#  A tile is GIB_FIRST + first + (draw & mask); vx and vy are centred
#  (draw & mask) - (mask + 1) / 2, vx with an outward push of x / 16.
CLASSES = [
    # blood: four drops, which pool where they land
    (32, 0x0, 3, 4, 0x0200, 0x0BFF, 0x01FF, 0x00FF, 0x0060, 0x01FF, False, 0x4),
    # chunks
    (8, 0x6, 1, 4, 0x0400, 0x07FF, 0x01FF, 0x00FF, 0x0080, 0x00FF, False, None),
    # bones
    (12, 0x8, 3, 5, 0x0600, 0x07FF, 0x01FF, 0x00FF, 0x00A0, 0x00FF, True, None),
    # the skull: the cranium, the jaw
    (1, 0xC, 0, 5, 0x0B00, 0x01FF, 0x00FF, 0x007F, 0x0180, 0x007F, True, None),
    (1, 0xD, 0, 5, 0x0800, 0x01FF, 0x00FF, 0x007F, 0x00E0, 0x007F, True, None),
    # the eyes
    (2, 0xE, 0, 5, 0x0A00, 0x03FF, 0x01FF, 0x00FF, 0x0100, 0x00FF, True, None),
]
assert sum(c[0] for c in CLASSES) == PARTICLES
BODY_X = 0x07FF                 # spawn x: (draw & BODY_X) - $400, the dwarf's width
BODY_Y = 0x01FF                 # spawn y: (draw & BODY_Y) - $100

GIB_FIRST = 0xF0                # the gibs' tiles: object slot 14's row, NES $1F00
#  The gib set, 8x8, colours 1-3 of OBJ palette 4 (reds) or 5 (bone): each
#  row a string, '.' clear.  A gib is drawn with its centre, (4, 4), on the
#  particle.
GIBS = [
    # $F0-$F3 blood drops
    ["........", "........", "........", "...2....", "........", "........", "........", "........"],
    ["........", "........", "........", "...23...", "........", "........", "........", "........"],
    ["........", "........", "....3...", "...22...", "....1...", "........", "........", "........"],
    ["........", "........", "...3....", "..222...", "...21...", "........", "........", "........"],
    # $F4-$F5 pools, as a drop that landed
    ["........", "........", "........", "..3222..", ".122221.", "........", "........", "........"],
    ["........", "........", "........", "...232..", ".12221..", "..11....", "........", "........"],
    # $F6-$F7 chunks
    ["........", "........", "...32...", "..2221..", "..1211..", "...1....", "........", "........"],
    ["........", "........", "..3.....", "..221...", "...211..", "....1...", "........", "........"],
    # $F8-$FB bones
    ["........", "........", "........", ".2.....2", "..22222.", ".2.....2", "........", "........"],
    ["........", "......2.", ".....22.", "....2...", "...2....", ".22.....", ".2......", "........"],
    ["........", "........", "........", "..2222..", "........", "........", "........", "........"],
    ["........", "........", "...2....", "..2.2...", "...2....", "...2....", "........", "........"],
    # $FC the cranium, $FD the jaw
    ["........", "..2222..", ".222222.", ".233232.", ".222222.", "..2..2..", "........", "........"],
    ["........", "........", "........", ".2.2.2..", ".222222.", "..2222..", "........", "........"],
    # $FE an eye
    ["........", "........", "...22...", "..2332..", "..2332..", "...22...", "........", "........"],
    # $FF spare
    ["........"] * 8,
]
assert len(GIBS) == 16 and all(len(t) == 8 and all(len(r) == 8 for r in t) for t in GIBS)
#  OBJ palettes 4 and 5, NES colours: blood dark, red, bright; bone grey,
#  white, the sockets black.
GIB_PALETTES = [0x0F, 0x06, 0x16, 0x26, 0x0F, 0x00, 0x30, 0x0F]


def xs16(s):
    """A 16-bit xorshift (7, 9, 8): the gibs' own draws, seeded at the burst."""
    s ^= (s << 7) & 0xFFFF
    s ^= s >> 9
    s ^= (s << 8) & 0xFFFF
    return s


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Gib:
    __slots__ = ("x", "y", "z", "vx", "vy", "vz", "tile", "pal", "bounces", "rest_tile", "rest")


def burst(seed):
    """The particles as they start: seed the draws' 16-bit state, nonzero."""
    s = seed & 0xFFFF or 1
    out = []
    for (count, first, tmask, pal, zb, zm, vxm, vym, vzb, vzm, bounces, rest_tile) in CLASSES:
        for _ in range(count):
            g = Gib()
            s = xs16(s); g.tile = first + (s & tmask)
            s = xs16(s); g.x = (s & BODY_X) - (BODY_X + 1) // 2
            s = xs16(s); g.y = (s & BODY_Y) - (BODY_Y + 1) // 2
            s = xs16(s); g.z = zb + (s & zm)
            s = xs16(s); g.vx = (s & vxm) - (vxm + 1) // 2 + (g.x >> 4)
            s = xs16(s); g.vy = (s & vym) - (vym + 1) // 2
            s = xs16(s); g.vz = vzb + (s & vzm)
            g.pal, g.bounces, g.rest_tile, g.rest = pal, bounces, rest_tile, False
            out.append(g)
    return out


def step(gibs):
    """One frame: fly, fall, bounce or settle."""
    for g in gibs:
        if g.rest:
            continue
        g.x = s16(g.x + g.vx)
        g.y = s16(g.y + g.vy)
        g.z = s16(g.z + g.vz)
        g.vz = s16(g.vz - GRAVITY)
        if g.z < 0:
            g.z = 0
            vz = (-g.vz * 5) >> 3
            if not g.bounces or vz < REST_VZ:
                g.rest = True
                g.vx = g.vy = g.vz = 0
                if g.rest_tile is not None:
                    g.tile = g.rest_tile + (g.tile & 1)
            else:
                g.vz = vz
                g.vx = (g.vx * 3) >> 2
                g.vy >>= 1


NES_TOP_CROP = 8
HIDDEN_Y = 0xF0


def oam(gibs, ox, oy, scroll_x, scroll_y):
    """Each particle's four OAM bytes: (x, y, tile, attributes), the origin
    at map pixel (ox, oy) and the screen's left and top at (scroll_x,
    scroll_y) -- off the screen, Y HIDDEN_Y.  Tiles from the NES's second
    pattern table (the name select bit), priority over BG1."""
    out = []
    for g in gibs:
        px = (ox + (g.x >> 8) - scroll_x) & 1023
        py = (oy + (g.y >> 8) - (g.z >> 8) - scroll_y) & 1023
        if 4 <= px < 252 and NES_TOP_CROP + 4 <= py < NES_TOP_CROP + 224 - 4:
            out.append((px - 4, py - 4 - NES_TOP_CROP, GIB_FIRST + g.tile, 0x21 | g.pal << 1))
        else:
            out.append((0, HIDDEN_Y, GIB_FIRST + g.tile, 0x21 | g.pal << 1))
    return out


def cover(sprites, cutoff):
    """A dialogue box's frame (fun_cover, as Dialogue_CoverSprites_VBl the
    game's sprites): those whose NES Y -- the SNES's plus the cropped lines
    less the one the NES draws below -- is above the box's bottom, tmp+11,
    hidden; the rest as they were."""
    return [(x, HIDDEN_Y if y + NES_TOP_CROP - 1 < cutoff else y, t, a) for (x, y, t, a) in sprites]


def tile_bytes(rows):
    """A gib as the SNES's 4bpp tile: planes 0 and 1 interleaved by row,
    then planes 2 and 3, clear."""
    out = bytearray(32)
    for y, r in enumerate(rows):
        for x, c in enumerate(r):
            v = 0 if c == "." else int(c)
            if v & 1:
                out[2 * y] |= 0x80 >> x
            if v & 2:
                out[2 * y + 1] |= 0x80 >> x
    return bytes(out)


def write_inc(path):
    """gen/dwarfgibs.inc: the gib set's 4bpp tiles, the classes as fun.asm
    reads them (one record a particle), and the palettes."""
    o = ["; GENERATED by tools/dwarfref.py -- do not edit.", ""]
    o.append("DWARF_PARTICLES = %d" % PARTICLES)
    o.append("DWARF_GRAVITY   = %d" % GRAVITY)
    o.append("DWARF_REST_VZ   = $%02X" % REST_VZ)
    o.append("DWARF_BODY_X    = $%04X" % BODY_X)
    o.append("DWARF_BODY_Y    = $%04X" % BODY_Y)
    o.append("DWARF_GIB_FIRST = $%02X" % GIB_FIRST)
    o.append("")
    o.append(";  The gib set: sixteen 8x8 tiles, the SNES's 4bpp, planes 2-3 clear.")
    o.append("lut_DwarfGibs:")
    for t in GIBS:
        o.append("  .BYTE " + ", ".join("$%02X" % b for b in tile_bytes(t)))
    o.append(";  OBJ palettes 4 and 5, NES colours (the HAL's h_xpal).")
    o.append("lut_DwarfPals:  .BYTE " + ", ".join("$%02X" % c for c in GIB_PALETTES))
    #  A record a particle, field by field, so the spawn loop indexes each
    #  table by the particle: words for the masks and bases, bytes else.
    recs = [c for c in CLASSES for _ in range(c[0])]
    def words(name, f):
        o.append("%s:" % name)
        for i in range(0, PARTICLES, 8):
            o.append("  .WORD " + ", ".join("$%04X" % f(r) for r in recs[i:i + 8]))
    o.append(";  Each particle's class, a field to a word table (dwarfref.CLASSES), so")
    o.append(";  one index, the particle times two, reads them all.")
    words("lut_DwarfTile", lambda r: r[1])
    words("lut_DwarfTMask", lambda r: r[2])
    words("lut_DwarfAttr", lambda r: 0x21 | r[3] << 1)
    words("lut_DwarfZB", lambda r: r[4])
    words("lut_DwarfZM", lambda r: r[5])
    words("lut_DwarfVXM", lambda r: r[6])
    words("lut_DwarfVXC", lambda r: (r[6] + 1) // 2)
    words("lut_DwarfVYM", lambda r: r[7])
    words("lut_DwarfVYC", lambda r: (r[7] + 1) // 2)
    words("lut_DwarfVZB", lambda r: r[8])
    words("lut_DwarfVZM", lambda r: r[9])
    words("lut_DwarfBounce", lambda r: 1 if r[10] else 0)
    words("lut_DwarfRest", lambda r: 0xFFFF if r[11] is None else r[11])
    open(path, "w").write("\n".join(o) + "\n")


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(here), "gen", "dwarfgibs.inc")
    write_inc(out)
    print("dwarfgibs.inc: %d particles, %d gib tiles" % (PARTICLES, len(GIBS)))
