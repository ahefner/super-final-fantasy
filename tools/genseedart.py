#!/usr/bin/env python3
"""
genseedart.py -- the seed screen's art (seedscreen.asm), from the game's own:
the 15-puzzle minigame's pieces over the bridge scene it is played on (user,
2026-10-22: "base it on the artwork from the 15-puzzle game").

The pieces are the minigame's, 16x16, the blank one the back of every other;
1-9 are the game's own, and 0 and A-F are drawn here in their style (5x7,
the stems two pixels wide, as the game's 6, 8 and 9 have them) -- its 10-15
being two digits.  They are background tiles, not sprites as the minigame
has them: sixteen buttons and eight read-out pieces would be ninety-six
sprites of the sixty-four the screen has.

The background is the bridge scene, the story box over it taken out, and
one black box in its place across the top (user: "the design that put
everything in one box ... tighten it up"), clear of the birds on the right
and inside the cells a CRT shows (30x26).  Everything in the box is in
palette 0, which the bridge scene shows nowhere -- its attribute table gives
it only to the rows below the picture -- so it can be the pieces' colours:
the backdrop's black, red, grey and white.  The box's border and the letters
of "Seed Entry" are the menu font's, recoloured for it (their grey and the
box's black on palette 0's grey and backdrop), and the box's inside is a
tile of backdrop, so the hand, behind the background, shows there and not
over a piece.

Writes gen/seedart.inc: the tiles, loaded over the menu font's at $80 (the
screen needs nothing else of the font, and puts it back as it leaves), the
whole nametable with its attributes, the background palette, and the layout
as constants for seedscreen.asm.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "game", "bin")
OUT = os.path.join(ROOT, "gen", "seedart.inc")

#  The game's art, as the disassembly keeps it: bank $09's first 8KB (the menu
#  font at $8800), bank $0B's $A800-$BFFF (the bridge scene's CHR at $B400 and
#  its nametable at $BC00), the minigame's pieces at bank $0D's $9E00.
MENU = open(os.path.join(BIN, "bank_09_data.bin"), "rb").read()[0x800:0x1000]
BRIDGE = open(os.path.join(BIN, "0B_A800_endingbridge_chrnt.bin"), "rb").read()
BRIDGE_CHR, BRIDGE_NT = BRIDGE[0xC00:0x1400], BRIDGE[0x1400:0x1800]
PUZZLE = open(os.path.join(BIN, "0D_9E00_puzzle_1bpp.chr"), "rb").read()

#  lut_BridgeBGPal (bank $0D), but palette 0, which the scene shows nowhere:
#  the pieces' backdrop black, red (the minigame's $15), grey, white.
PALETTE = [0x0F, 0x15, 0x00, 0x30,  0x0F, 0x3B, 0x11, 0x24,
           0x0F, 0x3B, 0x0B, 0x2B,  0x0F, 0x00, 0x0F, 0x30]

SKY = 0x6D                      # the bridge scene's sky
STORY = (4, 4, 21, 15)          # its story box: columns 4-21, rows 4-15

#  The layout (S2, user 2026-10-22).  The box: columns 2-29, rows 2-11 --
#  above the birds at (26,13), (27,14), (26,15).  The grid's pieces three
#  columns apart, so the hand stands in the gap, its rows touching; "Seed
#  Entry" and the read-out, two rows of four, to its right.
BOX = (2, 2, 28, 10)            # column, row, width, height
GRID = (5, 3, 3, 2)             # first piece's column and row, the pitch
TEXT = (18, 4, "Seed Entry")
READ = (19, 6)                  # the read-out's first piece
BIRDS = [(26, 13), (27, 14), (26, 15), (25, 17)]

#  The tiles, at $80: the 16 pieces 0-F and the blank, four each (UL, UR, DL,
#  DR); the box's eight border tiles; a tile of backdrop; the letters.
BASE = 0x80
PIECES = BASE
BORDER = PIECES + 17 * 4
ZERO = BORDER + 8
LETTERS = ZERO + 1
TEXT_LETTERS = sorted(set(TEXT[2].replace(" ", "")), key=TEXT[2].index)
ROWS = 6                        # loaded as six rows of 256 bytes: tiles $80-$DF

NEW_GLYPHS = {
    0x0: [".ooo.", "oo.oo", "oo.oo", "oo.oo", "oo.oo", "oo.oo", ".ooo."],
    0xA: [".ooo.", "oo.oo", "oo.oo", "ooooo", "oo.oo", "oo.oo", "oo.oo"],
    0xB: ["oooo.", "oo.oo", "oo.oo", "oooo.", "oo.oo", "oo.oo", "oooo."],
    0xC: [".ooo.", "oo.oo", "oo...", "oo...", "oo...", "oo.oo", ".ooo."],
    0xD: ["oooo.", "oo.oo", "oo.oo", "oo.oo", "oo.oo", "oo.oo", "oooo."],
    0xE: ["ooooo", "oo...", "oo...", "oooo.", "oo...", "oo...", "ooooo"],
    0xF: ["ooooo", "oo...", "oo...", "oooo.", "oo...", "oo...", "oo..."],
}


def bits(tile8, y, x):
    return (tile8[y] >> (7 - x)) & 1


def nes_tile(px):
    """8x8 colour values 0-3 as a NES tile."""
    lo = bytes(sum((px[y][x] & 1) << (7 - x) for x in range(8)) for y in range(8))
    hi = bytes(sum((px[y][x] >> 1) << (7 - x) for x in range(8)) for y in range(8))
    return lo + hi


def font_px(t):
    d = MENU[(t - 0x80) * 16:(t - 0x80) * 16 + 16]
    return [[bits(d, y, x) | bits(d[8:], y, x) << 1 for x in range(8)] for y in range(8)]


def piece_tiles(n):
    """Piece n (0-15, or 16 the blank): four tiles of the back (white, 3)
    with the glyph (red, 1) let into it; outside the back, backdrop.  The
    minigame's own pieces draw their glyph as holes in the back, the blank
    piece being the back itself."""
    blank = PUZZLE[0:32]
    if n < 16 and n not in NEW_GLYPHS:
        own = PUZZLE[n * 32:n * 32 + 32]
        glyph = lambda y, x: not bits(own[((y >= 8) * 2 + (x >= 8)) * 8:], y & 7, x & 7)
    else:
        rows = NEW_GLYPHS.get(n)
        glyph = lambda y, x: rows is not None and 4 <= y < 11 and 5 <= x < 10 and rows[y - 4][x - 5] == "o"
    out = []
    for k in range(4):
        px = []
        for y in range(8):
            Y = (k >> 1) * 8 + y
            row = []
            for x in range(8):
                X = (k & 1) * 8 + x
                back = bits(blank[k * 8:], y, x)
                row.append(0 if not back else 1 if glyph(Y, X) else 3)
            px.append(row)
        out.append(nes_tile(px))
    return out


def chr_block():
    tiles = []
    for n in range(17):
        tiles += piece_tiles(n)
    #  The menu's colours on palette 0's: its grey (1) on grey (2), its box
    #  black (2) on the backdrop (0), white (3) as it is.
    recolour = {0: 0, 1: 2, 2: 0, 3: 3}
    for t in (0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE):
        tiles.append(nes_tile([[recolour[v] for v in r] for r in font_px(t)]))
    tiles.append(bytes(16))
    for ch in TEXT_LETTERS:
        t = 0x8A + ord(ch) - 65 if ch.isupper() else 0xA4 + ord(ch) - 97
        tiles.append(nes_tile([[recolour[v] for v in r] for r in font_px(t)]))
    assert BASE + len(tiles) <= BASE + ROWS * 16, "the screen's tiles overrun what it loads"
    assert BASE + ROWS * 16 <= 0xF7, "the screen's tiles reach the box tiles the next screens need"
    return b"".join(tiles) + bytes(ROWS * 256 - 16 * len(tiles))


def nametable():
    nt = bytearray(BRIDGE_NT)

    def attr(c, r, p):
        i = 0x3C0 + (r // 4) * 8 + c // 4
        q = ((r % 4) // 2) * 2 + (c % 4) // 2
        nt[i] = (nt[i] & ~(3 << (q * 2)) & 0xFF) | (p << (q * 2))

    c0, r0, c1, r1 = STORY
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            nt[r * 32 + c] = SKY
            attr(c, r, 1)               # the sky's palette

    bc, br, bw, bh = BOX
    assert bc % 2 == 0 and br % 2 == 0 and bw % 2 == 0 and bh % 2 == 0, \
        "the box's edges on the attribute grid, so the sky beside it keeps its palette"
    assert 1 <= bc and bc + bw - 1 <= 30 and 2 <= br and br + bh - 1 <= 27, \
        "the box inside the cells a CRT shows (30x26)"
    assert not any(bc <= c < bc + bw and br <= r < br + bh for c, r in BIRDS), "the box over the birds"
    for r in range(bh):
        for c in range(bw):
            if r == 0:
                t = BORDER + (0 if c == 0 else 2 if c == bw - 1 else 1)
            elif r == bh - 1:
                t = BORDER + (5 if c == 0 else 7 if c == bw - 1 else 6)
            else:
                t = BORDER + 3 if c == 0 else BORDER + 4 if c == bw - 1 else ZERO
            nt[(br + r) * 32 + bc + c] = t
            attr(bc + c, br + r, 0)

    def put_piece(c, r, n):
        for k in range(4):
            nt[(r + (k >> 1)) * 32 + c + (k & 1)] = PIECES + n * 4 + k

    gc, gr, dc, dr = GRID
    for d in range(16):
        put_piece(gc + (d & 3) * dc, gr + (d >> 2) * dr, d)
    tc, tr, words = TEXT
    for i, ch in enumerate(words):
        nt[tr * 32 + tc + i] = ZERO if ch == " " else LETTERS + TEXT_LETTERS.index(ch)
    for i in range(8):
        put_piece(READ[0] + (i & 3) * 2, READ[1] + (i >> 2) * 2, 16)
    return bytes(nt)


def main():
    chrs, nt = chr_block(), nametable()
    o = ["; Generated by tools/genseedart.py from the game's own art -- edit that.", ""]
    o.append("SEEDART_BASE    = $%02X       ; the screen's tiles, over the menu font's" % BASE)
    o.append("SEEDART_ROWS    = %d         ; ...loaded as this many rows of 256 bytes" % ROWS)
    o.append("SEEDART_PIECE   = $%02X       ; piece n's four tiles from here + 4n; 16 the blank" % PIECES)
    o.append("SEEDART_BLANK   = 16")
    o.append("SEEDART_GRIDCOL = %d          ; the grid's first piece, and the pitch" % GRID[0])
    o.append("SEEDART_GRIDROW = %d" % GRID[1])
    o.append("SEEDART_GRIDDC  = %d" % GRID[2])
    o.append("SEEDART_GRIDDR  = %d" % GRID[3])
    o.append("SEEDART_READCOL = %d          ; the read-out's first piece" % READ[0])
    o.append("SEEDART_READROW = %d" % READ[1])
    o.append("")
    o.append("lut_SeedPal:                    ; the background's palettes")
    o.append("  .BYTE " + ", ".join("$%02X" % v for v in PALETTE))
    o.append("lut_SeedCHR:                    ; SEEDART_ROWS rows, to PPU $0800 + SEEDART_BASE * 16 - $800")
    for i in range(0, len(chrs), 16):
        o.append("  .BYTE " + ", ".join("$%02X" % v for v in chrs[i:i + 16]))
    o.append("lut_SeedNT:                     ; the whole nametable and its attributes, to $2000")
    for i in range(0, len(nt), 32):
        o.append("  .BYTE " + ", ".join("$%02X" % v for v in nt[i:i + 32]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(o) + "\n")


if __name__ == "__main__":
    main()
