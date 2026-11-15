#!/usr/bin/env python3
"""
genjtiles.py -- Graphics: Japan's tiles, gen/jtiles.inc (fun.asm).

FUN%'s Graphics row (user, 2026-11-14: "Graphics" - "USA", "Japan") draws
the tiles the Japanese release had where the US release redrew them: the
crosses on the town windows and the clinic sign, the cross on a stand in
the caves where the US release has a candlestick, the six-pointed star
where it has a triangle, the EYE and MEDUSA, the battle poses of six
classes (all of the Master's), the shopkeeper's hat and two weapons.

The tiles are in game/jtiles.dat, taken once from the Japanese ROM:

    python3 tools/genjtiles.py --extract ../ff1e.nes ../ff1j.nes

so the build needs neither ROM (user: "Build must be self-contained").
The file is runs of tiles: the NES bank, the first tile's address (low
byte first), the count, then the tiles, sixteen bytes each; a zero bank
ends it.

What is taken, by comparing the two ROMs tile by tile at the same address:

    bank $03  the eight tilesets' map tiles, but not $7B-$7F of any of
              them: leftover kana in the Japanese ROM, blank in most of the
              US tilesets, and $7E-$7F are Chests Appear Opened's lid
              (mkrom.py's overlay)
    $07, $08  each enemy picture with a changed tile, whole -- the
              Bestiary reads a picture from its first tile on, so a run
              starts where the picture does (fun_japanpic)
    $09       the shop's tiles, but not $79 (blank in the Japanese ROM,
              where the US shop screen fills with it); the battle sprites
              and battle objects

Left as they are: the font ($09 $8800-$8FFF, kana in the Japanese ROM)
and the bridge scene (bank $0B: the user, 2026-11-14, would "rather
respect the original copyright/trademark notices").  The build checks the
file against those rules where it can without the Japanese ROM.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DAT = os.path.join(ROOT, "game", "jtiles.dat")
OUT = os.path.join(ROOT, "gen", "jtiles.inc")

#  (NES bank, first address, end, a picture's whole run?)
REGIONS = [
    (0x03, 0x8000, 0xC000, False),      # the tilesets, $800 each
    (0x07, 0x8000, 0xC000, True),       # battle backdrops and enemies, $800 a page
    (0x08, 0x8000, 0xC000, True),
    (0x09, 0x8000, 0x8800, False),      # the shop
    (0x09, 0x9000, 0xB000, False),      # battle sprites, $200 a class, and battle objects
]
#  An enemy page's pictures: the first tile and the count, small then large.
PICTURES = ((0x12, 16), (0x22, 16), (0x32, 36), (0x56, 36))
PAGE = 0x800
#  The clinic's roof in the town tileset: map tile $19, characters $45-$48,
#  above the clinic sign in every town.  Taverns' pub sign takes its top
#  from two of them, so on Japan the pub showed two crosses; the run is
#  flagged, and fun_chrload leaves it US under Taverns (user, 2026-11-14:
#  no crosses on the pub).
PUB_ROOF = (0x03, 0x8450, 0x8490)
JAPAN_PUB = 0x01


def skipped(bank, addr):
    """A tile the rules leave out, though it differs."""
    if bank == 0x03:
        return (addr - 0x8000) % PAGE // 16 >= 0x7B
    if bank == 0x09:
        return addr == 0x8000 + 0x79 * 16
    return False


def select(E, J):
    """game/jtiles.dat's bytes, from the two ROMs' PRG (headers off)."""
    at = lambda rom, bank, addr: rom[bank * 0x4000 + addr - 0x8000:][:16]
    runs = []                                   # (bank, first address, tiles)
    for bank, start, end, whole in REGIONS:
        changed = [a for a in range(start, end, 16)
                   if at(E, bank, a) != at(J, bank, a) and not skipped(bank, a)]
        if whole:
            want = []
            for a in changed:
                t = (a - 0x8000) % PAGE // 16
                pic = [(f, n) for f, n in PICTURES if f <= t < f + n]
                if not pic:
                    sys.exit("bank $%02X $%04X: a changed tile outside the pictures" % (bank, a))
                first = a - (t - pic[0][0]) * 16
                for k in range(pic[0][1]):
                    if first + 16 * k not in want:
                        want.append(first + 16 * k)
            changed = sorted(want)
        for a in changed:
            if runs and runs[-1][0] == bank and runs[-1][1] + 16 * runs[-1][2] == a:
                runs[-1][2] += 1
            else:
                runs.append([bank, a, 1])
    out = bytearray()
    for bank, first, n in runs:
        out += bytes((bank, first & 0xFF, first >> 8, n))
        for k in range(n):
            out += at(J, bank, first + 16 * k)
    out.append(0)
    return bytes(out)


def extract(epath, jpath):
    out = select(open(epath, "rb").read()[16:], open(jpath, "rb").read()[16:])
    open(DAT, "wb").write(out)
    runs = load()
    print("genjtiles: %d runs, %d tiles into %s" % (len(runs), sum(len(t) // 16 for _, _, t in runs),
                                                  os.path.relpath(DAT, ROOT)))


def load():
    d = open(DAT, "rb").read()
    runs, i = [], 0
    while d[i]:
        bank, first, n = d[i], d[i + 1] | d[i + 2] << 8, d[i + 3]
        runs.append((bank, first, d[i + 4:i + 4 + 16 * n]))
        i += 4 + 16 * n
    if i != len(d) - 1:
        sys.exit("game/jtiles.dat: %d bytes after its end" % (len(d) - 1 - i))
    return runs


def check(runs):
    """What can be held without the Japanese ROM: each run inside a region
    and none of the tiles the rules leave out; the runs in order, apart;
    a picture's run its whole picture; and a run of tiles that are not
    already the US ones (a whole picture's may have some)."""
    def vendored(bank):
        if bank == 0x09:
            return None                         # assembled: out/ is not built yet
        return open(os.path.join(ROOT, "game", "bank_%02X.dat" % bank), "rb").read()
    last = (0, 0)
    for bank, first, tiles in runs:
        n = len(tiles) // 16
        end = first + 16 * n
        reg = [r for r in REGIONS if r[0] == bank and r[1] <= first and end <= r[2]]
        if len(reg) != 1:
            sys.exit("game/jtiles.dat: bank $%02X $%04X-$%04X is in no region" % (bank, first, end))
        if any(skipped(bank, a) for a in range(first, end, 16)):
            sys.exit("game/jtiles.dat: bank $%02X $%04X-$%04X takes a tile the rules leave out"
                     % (bank, first, end))
        if (bank, first) < last:
            sys.exit("game/jtiles.dat: bank $%02X $%04X is out of order or overlaps" % (bank, first))
        last = (bank, end)
        if reg[0][3]:
            t = (first - 0x8000) % PAGE // 16
            if (t, n) not in PICTURES:
                sys.exit("game/jtiles.dat: bank $%02X $%04X is not a whole picture" % (bank, first))
        us = vendored(bank)
        if us is not None and tiles == us[first - 0x8000:end - 0x8000]:
            sys.exit("game/jtiles.dat: bank $%02X $%04X is the US tiles" % (bank, first))
        if bank == PUB_ROOF[0] and first < PUB_ROOF[2] and PUB_ROOF[1] < end and \
                (first, end) != PUB_ROOF[1:]:
            sys.exit("game/jtiles.dat: bank $%02X $%04X is not the clinic's roof alone" % (bank, first))
    if not any((b, f, f + len(t)) == PUB_ROOF for b, f, t in runs):
        sys.exit("game/jtiles.dat: no run is the clinic's roof")


def generate():
    runs = load()
    check(runs)
    o = [";  Generated by tools/genjtiles.py from game/jtiles.dat -- do not edit.",
         ";  Graphics: Japan's tiles (fun_chrload, fun_japanpic).  lut_JapanRuns: per",
         ";  run, its first tile's address in its NES bank, the address past its",
         ";  last, that bank's chunk (CHUNK0 + the bank) and its flags, and its",
         ";  tiles in lut_JapanTiles; a zero address ends it.  The tiles as the",
         ";  NES has them, sixteen bytes each, from a 16-byte boundary (jp_put's",
         ";  rows).  JAPAN_PUB: the clinic's roof, left US under Taverns.",
         "",
         "JAPAN_PUB   = $%02X" % JAPAN_PUB,
         "JAPAN_RUNS  = %d" % len(runs),
         "JAPAN_TILES = %d" % sum(len(t) // 16 for _, _, t in runs),
         "",
         "lut_JapanRuns:"]
    for k, (bank, first, tiles) in enumerate(runs):
        flags = JAPAN_PUB if (bank, first, first + len(tiles)) == PUB_ROOF else 0
        o.append("  .WORD $%04X, $%04X, (CHUNK0 + $%02X) | $%02X << 8, jt_%02d"
                 % (first, first + len(tiles), bank, flags, k))
    o += ["  .WORD 0", "", "  .ALIGN 16", "lut_JapanTiles:"]
    for k, (bank, first, tiles) in enumerate(runs):
        o.append("jt_%02d:   ; bank $%02X, $%04X, %d tiles" % (k, bank, first, len(tiles) // 16))
        for i in range(0, len(tiles), 16):
            o.append("  .BYTE " + ", ".join("$%02X" % b for b in tiles[i:i + 16]))
    o.append(".assert (lut_JapanTiles & 15) = 0, error, \"jp_put wants each tile on a 16-byte boundary\"")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(o) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--extract"]:
        if len(sys.argv) != 4:
            sys.exit("usage: genjtiles.py --extract US.nes JAPAN.nes")
        extract(sys.argv[2], sys.argv[3])
    else:
        generate()
