#!/usr/bin/env python3
"""
genroll.py -- the pictures New Game's roll screen can show (roll.asm).

While New Game rolls the seed, the screen shows one of the game's own map
sprites scaled up eight times -- every pixel a character cell -- walking in
place, the seed choosing which (user, 2026-10-14).  The choices are every
map object graphic some map uses, but the Black Orb and the rod and lute
plates, which are not creatures, and Bahamut -- no black outline, so brown
on the blue clashes, and no step (user, 2026-10-15) -- and the twelve
classes' mapmen.  Garland and the bats are in (user).

Each is drawn as the game draws it facing down (lut_2x2MapObj_Down,
lut_PlayerMapmanSprTbl), its two frames of walking in place -- but a bat
facing left (lut_2x2MapObj_Left), whose frames flap, where facing down they
do not.  Both frames are resolved here, tiles chosen and mirrored as the
table says, so the cart reads eight tiles and needs no rule of its own.

Each has an effect, lut_RollFx: most walk in place, the two frames swapping;
one whose two frames are the same hops instead, half a cell on the same
beat -- Garland and the Vampire on black (user: Garland's armour is the
window's own blue; the Vampire throbbed red at first) -- but the sleeping
Elf Prince, who cannot be hopping about like a grasshopper, sleeps while the
backdrop breathes slowly from black to a dim blue (user).  A throb's byte is
the fixed colour's channels (COLDATA's bits 7-5) with FX_THROB, and FX_SLOW
for half the speed and half the brightness; FX_BLACK puts any on black.

For each: its two frames, four tiles each in the order UL, UR, DL, DR, NES
2bpp, mirrored already; and its six colours in SNES form, the top half's
three then the legs' three.  An object's colours are sprite palettes 2 and 3
of the first map it stands on -- but Matoya's, whose graphic a woman in Gaia
shares, of her cave, or she is not Matoya (user) -- a mapman's palettes 0
and 1 of the
overworld's, with each half's second colour its class's
(lut_MapmanPalettes), as LoadSMPalettes sets them.

Read from the game's own banks (game/bank_00.dat, bank_02.dat); the NES
colours in SNES form from nescol.inc, which genpal.py writes first.
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DST = os.path.join(ROOT, "gen", "roll.inc")

#  Where things are, as Constants.inc has them: bank $00 and $02 at $8000.
MAPOBJGFX = 0xAE00 - 0x8000     # object id -> graphic id, $D0 of them
MAPOBJECTS = 0xB400 - 0x8000    # per map, $30 bytes: 15 objects of id, x, y
SMPALETTES = 0xA000 - 0x8000    # per map, $30 bytes: sprite palettes at +$10
MAPMANPAL = 0x83A0 - 0x8000     # per class, the two halves' second colours
MAPOBJCHR = 0xA200 - 0x8000     # in bank $02: per graphic, sixteen tiles
MAPMANCHR = 0x9000 - 0x8000     # in bank $02: per class, sixteen tiles
MAPS = 61
CLASSES = 12
LEFT_OUT = {0x04,              # the Black Orb
            0x1B,              # the rod and lute plates
            0x17}              # Bahamut
BAT = 0x11                      # the bats and the Sky Warriors
FX_WALK, FX_HOP, FX_THROB, FX_SLOW, FX_BLACK = 0, 1, 2, 1, 0x10   # FX_SLOW only with FX_THROB
BLUE = 0x80
ON_BLACK = {0x12,              # Garland
            0x1D}              # the Vampire
THROB = {0x1A: BLUE | FX_THROB | FX_SLOW}       # the Elf Prince, asleep
COLOURS_FROM = {0x05: 20}      # Matoya: her cave's palette, not Gaia's

#  The game's 2x2 tables, as (tile, attributes) for UL, DL, UR, DR, two
#  frames each: lut_2x2MapObj_Down (lut_PlayerMapmanSprTbl's is the same but
#  for the palettes) and lut_2x2MapObj_Left.  test_options.py finds both in
#  the fixed bank by these bytes, so a change here is caught.
DOWN = ((0x00, 0x02, 0x02, 0x03, 0x01, 0x02, 0x03, 0x03), (0x00, 0x02, 0x03, 0x43, 0x01, 0x02, 0x02, 0x43))
LEFT = ((0x08, 0x02, 0x0A, 0x03, 0x09, 0x02, 0x0B, 0x03), (0x0C, 0x02, 0x0E, 0x03, 0x0D, 0x02, 0x0F, 0x03))


def mirror(t16):
    return bytes(int("{:08b}".format(b)[::-1], 2) for b in t16)


def frames(chr256, table):
    """Both frames as eight tiles: UL, UR, DL, DR, then the same again."""
    out = b""
    for f in table:
        q = {}
        for k, where in enumerate(("UL", "DL", "UR", "DR")):
            t16 = chr256[f[k * 2] * 16:][:16]
            q[where] = mirror(t16) if f[k * 2 + 1] & 0x40 else t16
        out += q["UL"] + q["UR"] + q["DL"] + q["DR"]
    return out


def choices():
    b0 = open(os.path.join(ROOT, "game", "bank_00.dat"), "rb").read()
    b2 = open(os.path.join(ROOT, "game", "bank_02.dat"), "rb").read()
    col = {int(m.group(1), 16): int(m.group(2), 16) for m in re.finditer(
        r"NESCOL_([0-9A-F]{2}) = \$([0-9A-F]{4})", open(os.path.join(ROOT, "src", "nescol.inc")).read())}
    first = {}
    for m in range(MAPS):
        for o in range(15):
            oid = b0[MAPOBJECTS + m * 0x30 + o * 3]
            if oid:
                first.setdefault(b0[MAPOBJGFX + oid], m)
    pal = lambda m: b0[SMPALETTES + m * 0x30:SMPALETTES + m * 0x30 + 0x30]

    def effect(g, fr):
        if g in THROB:
            return THROB[g]
        return (FX_HOP if fr[:64] == fr[64:] else FX_WALK) | (FX_BLACK if g in ON_BLACK else 0)

    out = []
    for g in sorted(first):
        if g in LEFT_OUT:
            continue
        p = pal(COLOURS_FROM.get(g, first[g]))
        fr = frames(b2[MAPOBJCHR + g * 0x100:][:256], LEFT if g == BAT else DOWN)
        out.append(("graphic $%02X (map %d)" % (g, COLOURS_FROM.get(g, first[g])), fr,
                    [col[p[0x18 + i] & 0x3F] for i in (1, 2, 3)] + [col[p[0x1C + i] & 0x3F] for i in (1, 2, 3)],
                    effect(g, fr)))
    ow = pal(0)
    for c in range(CLASSES):
        top, bot = list(ow[0x10:0x14]), list(ow[0x14:0x18])
        top[2], bot[2] = b0[MAPMANPAL + c * 2], b0[MAPMANPAL + c * 2 + 1]
        fr = frames(b2[MAPMANCHR + c * 0x100:][:256], DOWN)
        out.append(("class %d" % c, fr,
                    [col[top[i] & 0x3F] for i in (1, 2, 3)] + [col[bot[i] & 0x3F] for i in (1, 2, 3)],
                    effect(None, fr)))
    return out


def main():
    cs = choices()
    o = ["; GENERATED by tools/genroll.py -- do not edit.",
         "; The roll screen's pictures: %d map sprites, the seed picks one." % len(cs),
         "", "ROLL_SPRITES = %d" % len(cs), "",
         ";  Each: two frames of four tiles, UL UR DL DR, mirrored already; NES 2bpp.",
         "lut_RollChr:"]
    for name, fr, _, _ in cs:
        o.append("  ; " + name)
        for t in range(8):
            o.append("  .byte " + ", ".join("$%02X" % b for b in fr[t * 16:t * 16 + 16]))
    o += ["", ";  Each: the top half's colours 1-3, then the legs', SNES BGR.", "lut_RollPal:"]
    for name, _, c, _ in cs:
        o.append("  .word " + ", ".join("$%04X" % v for v in c) + "   ; " + name)
    o += ["", ";  Each: 0 walks, 1 hops (its frames the same), or 2 the backdrop throbs:",
          ";  COLDATA's channels with it, and 1 for slow; $10 a black backdrop.", "lut_RollFx:"]
    for name, _, _, fx in cs:
        o.append("  .byte $%02X   ; %s" % (fx, name))
    open(DST, "w").write("\n".join(o) + "\n")


if __name__ == "__main__":
    main()
