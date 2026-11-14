#!/usr/bin/env python3
"""
genbestiary.py -- the Bestiary's tables and pictures, gen/bestiary.inc
(src/bestiary.asm), from the cartridge's own data.

Every enemy has one picture and one palette in every formation it appears in
(checked here: a second look is an error).  The 119 small and large ones are
the battle CHR as it is, read by the screen straight from banks $07-$08; only
their table entries come from here.  The four fiend pictures and Chaos's are
bigger than the grid's 48 x 48 cells, so they are scaled down -- once, here,
into art/bestiary/*.png, which the user retouches by hand (user, 2026-11-11:
"Putting the rescaled enemies into a PNG or similar for manual retouching is
the best way").  A PNG that exists is never overwritten; delete one to have it
scaled afresh.  They are palette PNGs of the picture's seven colours (black,
and its two palettes' three each, a colour the two share nudged a step so
they stay apart): kept indexed, a pixel's index is read; saved as RGB, a
pixel's colour, exactly or the nearest.  Each <name>-orig.png beside it is
the picture at its own size, for reference.  The nine fiend and Chaos
entries' characters are made here, each for its own cell's two colour
groups, into out/bestiary.bin, the low half of the Bestiary's chunk.

The grid's colours (src/bestiary.asm): BG1 4bpp, eight palettes of fifteen
colours, each split into five groups of three, an enemy's picture in one group
(a fiend's or Chaos's in two of the same palette).  Up to six grid rows are on
screen, the grid row r in slot r mod 6, and every cell of a slot has its
groups for good -- which fits because the fiends, the only ones that need two,
are the last nine.  Palette 0's first group is the text's (BG3's palette 0 is
CGRAM 1-3).  The assignment is worked out here and checked.

Writes out/bestiary_preview.png, the whole grid with every enemy seen, and
with the prototype's fake mask, for looking at.
"""
import os, sys, struct, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from genpal import NESPAL

BIN = os.path.join(ROOT, "game", "bin")
ART = os.path.join(ROOT, "art", "bestiary")
OUT = os.path.join(ROOT, "gen", "bestiary.inc")
PREVIEW = os.path.join(ROOT, "out", "bestiary_preview.png")

NENEMY = 128
COLS = 5
ROWS = (NENEMY + COLS - 1) // COLS          # 26
SLOTS = 6
CELL = 48
KIND_SMALL, KIND_LARGE, KIND_SPECIAL = 0, 1, 2
SPECIAL_NAMES = ["lich", "kary", "kraken", "tiamat", "chaos"]
REFIGHT_FORM, REFIGHTS = 0x73, 4    # Lich's, Kary's, Kraken's, Tiamat's second fights
PAL_REFIGHT = 64                    # their palettes' numbers, past the 64 (fun.asm)


def rd(name):
    return open(os.path.join(BIN, name), "rb").read()


FORM = rd("0B_8400_battleformations.bin")
CHR = (open(os.path.join(ROOT, "game", "bank_07.dat"), "rb").read() +
       open(os.path.join(ROOT, "game", "bank_08.dat"), "rb").read())
FIENDTSA = rd("0B_92E0_fiendtsa.bin")
CHAOSTSA = rd("0B_9420_chaostsa.bin")
PALS = rd("0C_8F20_battlepalettes.bin")


# --- PNG, by hand: no PIL here ----------------------------------------------
def png_write(path, w, h, rgb):
    """rgb: h rows of w (r, g, b)."""
    raw = b"".join(b"\0" + bytes(c for px in row for c in px) for row in rgb)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)


def png_write_indexed(path, w, h, idx, pal):
    """idx: h rows of w palette indices; pal: (r, g, b) each."""
    raw = b"".join(b"\0" + bytes(row) for row in idx)
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)) +
            chunk(b"PLTE", bytes(c for rgb in pal for c in rgb)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)


def png_read(path, want_index=False):
    """-> (w, h, rows of (r, g, b)); 8-bit grey, RGB, RGBA and palette (1-8 bit),
    non-interlaced -- what an editor saves.  With want_index, also the rows
    of palette indices for a palette PNG, else None."""
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit("%s: not a PNG" % path)
    at, idat, plte, trns = 8, b"", None, None
    while at < len(d):
        n, = struct.unpack(">I", d[at:at + 4])
        t, body = d[at + 4:at + 8], d[at + 8:at + 8 + n]
        at += 12 + n
        if t == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
        elif t == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif t == b"IDAT":
            idat += body
    if inter:
        sys.exit("%s: interlaced PNGs are not read; save it without" % path)
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    if ctype != 3 and depth != 8:
        sys.exit("%s: %d-bit channels are not read; save it as 8-bit" % (path, depth))
    bpp = max(1, chans * depth // 8)
    stride = (w * chans * depth + 7) // 8
    raw = zlib.decompress(idat)
    rows, prev, p = [], bytearray(stride), 0
    indices = [] if ctype == 3 else None
    for _ in range(h):
        f, line = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        if ctype == 3:
            per = 8 // depth
            idx = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(w)]
            rows.append([plte[i] for i in idx])
            indices.append(idx)
        else:
            rows.append([tuple(line[x * chans:x * chans + chans][:3]) if chans >= 3 else
                         (line[x * chans],) * 3 for x in range(w)])
    if want_index:
        return w, h, rows, (indices, plte)
    return w, h, rows


# --- the enemies, from the formations ---------------------------------------
def looks():
    """enemy -> (shape, chr set, pic, pal1, pal2, its palette)."""
    out = {}
    for i in range(128):
        d = FORM[i * 16:i * 16 + 16]
        shape, ts, pics, ids = d[0] >> 4, d[0] & 15, d[1], d[2:6]
        mx = [d[6 + k] & 15 for k in range(4)] + [d[14] & 15, d[15] & 15]
        for k in range(4):
            present = mx[k] or (k < 2 and mx[k + 4])
            if shape in (3, 4):
                present = k == 0
            if not present:
                continue
            pic = (pics >> (k * 2)) & 3
            pal = d[11] if d[13] & (0x80 >> k) else d[10]
            look = (shape if shape >= 3 else 0, ts, pic if shape < 3 else pics, d[10], d[11],
                    pal if shape < 3 else None)
            e = ids[k]
            key = look[:3] + (look[5],) if shape < 3 else look[:5]
            if e in out and out[e][1] != key:
                sys.exit("enemy $%02X has two looks: %s and %s" % (e, out[e][1], key))
            out[e] = (look, key)
    if len(out) != NENEMY:
        sys.exit("only %d enemies in the formations" % len(out))
    return {e: v[0] for e, v in out.items()}


def nes_rgb(c):
    return NESPAL[c & 0x3F]


def pal_rgb(p):
    return [nes_rgb(PALS[p * 4 + i]) for i in range(4)]


def tile_px(set_, t):
    """PPU tile t of enemy CHR set set_: 8 rows of 8 values 0-3."""
    if t < 0x12:
        return [[0] * 8 for _ in range(8)]
    b = set_ * 0x800 + t * 16
    return [[((CHR[b + r] >> (7 - x)) & 1) | (((CHR[b + 8 + r] >> (7 - x)) & 1) << 1)
             for x in range(8)] for r in range(8)]


def pic_tile(pic):
    """A formation's picture number: bit 0 large, bit 1 which of the two --
    the small ones at PPU tiles $12 and $22 (DrawSmallEnemy), the large at
    $32 and $56 (DrawLargeEnemy).  -> (kind, first tile)."""
    if pic & 1:
        return KIND_LARGE, 0x32 + 0x24 * (pic >> 1)
    return KIND_SMALL, 0x12 + 0x10 * (pic >> 1)


def regular_px(set_, pic):
    """The small or large picture: rows of values 0-3."""
    kind, base = pic_tile(pic)
    size = 4 if kind == KIND_SMALL else 6
    img = [[0] * (size * 8) for _ in range(size * 8)]
    for ty in range(size):
        for tx in range(size):
            px = tile_px(set_, base + ty * size + tx)
            for r in range(8):
                img[ty * 8 + r][tx * 8:tx * 8 + 8] = px[r]
    return img


def special_px(look):
    """A fiend's or Chaos's picture as battle draws it: rows of w, 0 black,
    1-3 its first palette, 4-6 its second."""
    shape, set_, gfx = look[0], look[1], look[2]
    if shape == 3:
        tsa = FIENDTSA[gfx * 0x50:gfx * 0x50 + 0x50]
        nt, attr, r0, c0, h, w = tsa[:0x40], tsa[0x40:0x50], 8, 4, 8, 8
    else:
        nt, attr, r0, c0, h, w = CHAOSTSA[:0xA8], CHAOSTSA[0xA8:0xB8], 6, 2, 12, 14
    img = [[0] * (w * 8) for _ in range(h * 8)]
    stray = 0
    for ty in range(h):
        for tx in range(w):
            R, C = r0 + ty, c0 + tx              # nametable cell; attributes cover rows 4-19, cols 0-15
            k = ((R - 4) // 4) * 4 + C // 4
            pal = (attr[k] >> (((R % 4) // 2) * 4 + ((C % 4) // 2) * 2)) & 3
            px = tile_px(set_, nt[ty * w + tx])
            for r in range(8):
                for x in range(8):
                    v = px[r][x]
                    if v and pal not in (1, 2):
                        stray += 1
                        v = 0
                    img[ty * 8 + r][tx * 8 + x] = 0 if not v else (v if pal == 1 else v + 3)
    if stray:
        print("genbestiary: %d pixels of a fiend picture in neither enemy palette, dropped" % stray)
    return img


def special_tiles(look):
    """The fiend's or Chaos's picture as battle's nametable has it, for the
    detail view's full size: (width, height, a byte a cell) -- the cell's
    PPU tile, bit 7 set if its attribute is the second palette, 0 a cell
    with nothing (no tile below $12 is the enemy's, nor any whose
    attribute is neither enemy palette: special_px drops those too)."""
    shape, gfx = look[0], look[2]
    if shape == 3:
        tsa = FIENDTSA[gfx * 0x50:gfx * 0x50 + 0x50]
        nt, attr, r0, c0, h, w = tsa[:0x40], tsa[0x40:0x50], 8, 4, 8, 8
    else:
        nt, attr, r0, c0, h, w = CHAOSTSA[:0xA8], CHAOSTSA[0xA8:0xB8], 6, 2, 12, 14
    out = []
    for ty in range(h):
        for tx in range(w):
            R, C = r0 + ty, c0 + tx
            k = ((R - 4) // 4) * 4 + C // 4
            pal = (attr[k] >> (((R % 4) // 2) * 4 + ((C % 4) // 2) * 2)) & 3
            t = nt[ty * w + tx]
            if t >= 0x80:
                sys.exit("a fiend's tile $%02X past its set's 128" % t)
            out.append(0 if t < 0x12 or pal not in (1, 2) else t | (0x80 if pal == 2 else 0))
    return w, h, out


def special_colours(look):
    """Black, the first palette's three, the second's -- every one of the
    four fiends' and Chaos's palette pairs shares a colour or two, and a
    pixel read back by colour alone would take the first's, wrong under
    Palette swap's shuffle.  So a repeat is nudged a step per channel:
    unseen, and still told apart once an editor has made the PNG RGB."""
    a, b = pal_rgb(look[3]), pal_rgb(look[4])
    cols = [(0, 0, 0)] + a[1:] + b[1:]
    for i in range(1, len(cols)):
        while cols[i] in cols[:i]:
            cols[i] = tuple(c + 1 if c < 255 else c - 1 for c in cols[i])
    return cols


def downscale(img, tw, th):
    """Each target pixel the colour covering most of its source area, the
    picture's colours weighted over black so thin parts survive."""
    sh, sw = len(img), len(img[0])
    sx, sy = sw / tw, sh / th
    out = [[0] * tw for _ in range(th)]
    for y in range(th):
        for x in range(tw):
            cover = {}
            y0, y1, x0, x1 = y * sy, (y + 1) * sy, x * sx, (x + 1) * sx
            for py in range(int(y0), min(sh, int(y1 + 0.999))):
                hy = min(py + 1, y1) - max(py, y0)
                for px in range(int(x0), min(sw, int(x1 + 0.999))):
                    hx = min(px + 1, x1) - max(px, x0)
                    v = img[py][px]
                    cover[v] = cover.get(v, 0) + hx * hy * (1.0 if v == 0 else 1.6)
            out[y][x] = max(sorted(cover), key=lambda v: cover[v])
    return out


def fit48(img):
    sh, sw = len(img), len(img[0])
    if sw >= sh:
        tw, th = CELL, round(sh * CELL / sw)
    else:
        th, tw = CELL, round(sw * CELL / sh)
    small = downscale(img, tw, th)
    out = [[0] * CELL for _ in range(CELL)]
    oy, ox = (CELL - th) // 2, (CELL - tw) // 2
    for y in range(th):
        out[oy + y][ox:ox + tw] = small[y]
    return out


def render(img, cols):
    return [[cols[v] for v in row] for row in img]


def nearest(rgb, cols):
    return min(range(len(cols)), key=lambda i: (sum((a - b) ** 2 for a, b in zip(rgb, cols[i])), i))


def special_art(idx, look):
    """The retouchable 48 x 48 picture, as w values: read, or made and written."""
    name = SPECIAL_NAMES[idx]
    cols = special_colours(look)
    full = special_px(look)
    path = os.path.join(ART, name + ".png")
    png_write_indexed(os.path.join(ART, name + "-orig.png"), len(full[0]), len(full), full, cols)
    if not os.path.exists(path):
        png_write_indexed(path, CELL, CELL, fit48(full), cols)
        print("genbestiary: wrote %s, scaled from the game's; retouch it as you like" % os.path.relpath(path, ROOT))
    w, h, rows, (idx, plte) = png_read(path, want_index=True)
    if (w, h) != (CELL, CELL):
        sys.exit("%s: %dx%d, not %dx%d" % (path, w, h, CELL, CELL))
    #  Kept indexed, a pixel's index is its colour; else its colour says,
    #  exactly if it is one of the seven, or the nearest.
    if idx is not None and plte[:len(cols)] == cols:
        return [[v if v < len(cols) else nearest(row_rgb[x], cols) for x, v in enumerate(row)]
                for row, row_rgb in zip(idx, rows)]
    return [[cols.index(px) if px in cols else nearest(px, cols) for px in row] for row in rows]


def special_4bpp(img, ga, gb):
    """36 SNES 4bpp characters: w 1-3 colour 3ga + w, 4-6 colour 3gb + w - 3."""
    out = bytearray()
    for ty in range(6):
        for tx in range(6):
            t = bytearray(32)
            for r in range(8):
                for x in range(8):
                    w = img[ty * 8 + r][tx * 8 + x]
                    if not w:
                        continue
                    i = 3 * ga + w if w <= 3 else 3 * gb + w - 3
                    for j in range(4):
                        if i >> j & 1:
                            t[(j // 2) * 16 + r * 2 + (j & 1)] |= 0x80 >> x
            out += t
    return bytes(out)


# --- the colour groups ---------------------------------------------------------
def assign_groups(kinds):
    """slot cell (s, c) -> (palette, group A, group B or None)."""
    pair = {(s, c): False for s in range(SLOTS) for c in range(COLS)}
    for e in range(NENEMY):
        if kinds[e] == KIND_SPECIAL:
            pair[((e // COLS) % SLOTS, e % COLS)] = True
    free = {p: list(range(5)) for p in range(8)}
    free[0].remove(0)                       # the text's colours, CGRAM 1-3
    out = {}
    for cell in sorted(pair):
        if pair[cell]:
            p = next((p for p in range(7, -1, -1) if len(free[p]) >= 2), None)
            if p is None:
                sys.exit("genbestiary: no palette has two groups free for a fiend")
            out[cell] = (p, free[p].pop(0), free[p].pop(0))
    for cell in sorted(pair):
        if not pair[cell]:
            p = next((p for p in range(8) if free[p]), None)
            if p is None:
                sys.exit("genbestiary: more cells than colour groups")
            out[cell] = (p, free[p].pop(0), None)
    return out


def fake_seen():
    """The prototype's stand-in for the defeated mask: 57 of the 128, scattered."""
    order = sorted(range(NENEMY), key=lambda e: ((e * 2654435761) >> 7) & 0xFFFF)
    return set(order[:57])


def main():
    lk = looks()
    kinds, src, pala, palb, special_of = {}, {}, {}, {}, {}
    specials = []
    for e in range(NENEMY):
        look = lk[e]
        if look[0] >= 3:
            kinds[e] = KIND_SPECIAL
            key = (look[0], look[2])
            if key not in [k for k, _ in specials]:
                specials.append((key, look))
            special_of[e] = [k for k, _ in specials].index(key)
            pala[e], palb[e] = look[3], look[4]
        else:
            set_, pic = look[1], look[2]
            kinds[e], tile = pic_tile(pic)
            src[e] = (set_, tile, pic)
            pala[e], palb[e] = look[5], look[5]
    if len(specials) != 5:
        sys.exit("expected five special pictures, found %d" % len(specials))
    #  Fiend refight colors (user, 2026-11-14): the refight palettes are
    #  numbered 64-71, past the 64.  The game's fun_btlpal shows them as the
    #  seed's RW_PALREF entries, or with the row Off as the formation's
    #  original palettes (fun.asm's PAL_REFIGHT).
    for k in range(REFIGHTS):
        e = FORM[(REFIGHT_FORM + k) * 16 + 2]
        if kinds[e] != KIND_SPECIAL or (pala[e], palb[e]) != tuple(FORM[(REFIGHT_FORM + k) * 16 + 10:][:2]):
            sys.exit("genbestiary: formation $%02X is not a refight's" % (REFIGHT_FORM + k))
        pala[e], palb[e] = PAL_REFIGHT + 2 * k, PAL_REFIGHT + 2 * k + 1
    # Name the specials in the order SPECIAL_NAMES expects: Lich, Kary, Kraken, Tiamat, Chaos.
    want = {0x77: 0, 0x79: 1, 0x7B: 2, 0x7D: 3, 0x7F: 4}
    remap = {special_of[e]: want[e] for e in want}
    specials = sorted(specials, key=lambda kv: remap[[k for k, _ in specials].index(kv[0])])
    special_of = {e: remap[i] for e, i in special_of.items()}
    art = [special_art(i, look) for i, (_, look) in enumerate(specials)]

    #  The ring: the rows on screen and the one coming in, seven at most.
    tiles = lambda e: 16 if kinds[e] == KIND_SMALL else 36
    rows = [sum(tiles(e) for e in range(r * COLS, min(NENEMY, r * COLS + COLS))) for r in range(ROWS)]
    worst = max(sum(rows[i:i + SLOTS + 1]) for i in range(ROWS - SLOTS))
    if worst > 1023:
        sys.exit("genbestiary: seven rows need %d characters, past the ring's 1023" % worst)
    groups = assign_groups(kinds)
    seen = fake_seen()
    #  The fiends' and Chaos's characters, each made for its own cell's two
    #  groups (user, 2026-11-12: the rows with them waited for their
    #  conversion): 36 characters, 1152 bytes, a special entry.  The colours
    #  stay the screen's to write, so Palette swap's palettes fill the same
    #  groups.  Into the low half of the Bestiary's chunk (BSTDATAFAR).
    bstdata, special_at = bytearray(), {}
    for e in range(NENEMY):
        if kinds[e] == KIND_SPECIAL:
            _, ga, gb = groups[((e // COLS) % SLOTS, e % COLS)]
            special_at[e] = len(bstdata)
            bstdata += special_4bpp(art[special_of[e]], ga, gb)
    open(os.path.join(ROOT, "out", "bestiary.bin"), "wb").write(bstdata)

    # The preview: every cell as the screen draws it.
    def cell_img(e, silhouette):
        if kinds[e] == KIND_SPECIAL:
            cols = special_colours(specials[special_of[e]][1])
            img = art[special_of[e]]
        else:
            cols = pal_rgb(pala[e])
            cols[0] = (0, 0, 0)
            set_, tile, pic = src[e]
            small = regular_px(set_, pic)
            off = (CELL - len(small)) // 2
            img = [[0] * CELL for _ in range(CELL)]
            for y, row in enumerate(small):
                img[off + y][off:off + len(row)] = row
        if silhouette:
            cols = [(0, 0, 0)] + [SILHOUETTE_RGB] * (len(cols) - 1)
        return render(img, cols)
    sheet = []
    for mode in (False, True):
        for r in range(ROWS):
            band = [[(0, 0, 0)] * (COLS * CELL + 16) for _ in range(CELL)]
            for c in range(COLS):
                e = r * COLS + c
                if e >= NENEMY:
                    continue
                img = cell_img(e, mode and e not in seen)
                for y in range(CELL):
                    band[y][8 + c * CELL:8 + (c + 1) * CELL] = img[y]
            sheet += band
        sheet += [[(40, 40, 40)] * (COLS * CELL + 16) for _ in range(8)]
    png_write(PREVIEW, COLS * CELL + 16, len(sheet), sheet)

    o = ["; GENERATED by tools/genbestiary.py -- do not edit.", ""]
    o.append("BST_NENEMY = %d" % NENEMY)
    o.append("BST_COLS   = %d" % COLS)
    o.append("BST_ROWS   = %d" % ROWS)
    o.append("BST_SLOTS  = %d" % SLOTS)
    o.append("KIND_SMALL = %d" % KIND_SMALL)
    o.append("KIND_LARGE = %d" % KIND_LARGE)
    o.append("KIND_SPECIAL = %d" % KIND_SPECIAL)
    o.append("")
    o.append(";  Each enemy: its kind; its picture's first tile, far -- the battle CHR")
    o.append(";  (banks $07-$08, a set every $800, PPU tile t at t * 16), or a special's")
    o.append(";  36 SNES characters ready made (out/bestiary.bin, BSTDATAFAR); and its")
    o.append(";  palettes (the second a special's).")
    o.append("lut_BstKind:")
    for i in range(0, NENEMY, 16):
        o.append("  .BYTE " + ", ".join("%d" % kinds[e] for e in range(i, i + 16)))
    o.append("lut_BstSrc:")
    for e in range(NENEMY):
        if kinds[e] == KIND_SPECIAL:
            o.append("  .FARADDR BSTDATAFAR + %d    ; $%02X" % (special_at[e], e))
        else:
            set_, tile, _ = src[e]
            o.append("  .FARADDR (CHUNK0 + BANK_BATTLECHR + %d) * $10000 + $%04X    ; $%02X"
                     % (set_ // 8, 0x8000 + (set_ % 8) * 0x800 + tile * 16, e))
    o.append("lut_BstPalA:")
    for i in range(0, NENEMY, 16):
        o.append("  .BYTE " + ", ".join("$%02X" % pala[e] for e in range(i, i + 16)))
    o.append("lut_BstPalB:")
    for i in range(0, NENEMY, 16):
        o.append("  .BYTE " + ", ".join("$%02X" % palb[e] for e in range(i, i + 16)))
    o.append("")
    o.append(";  The detail view's full-size fiends and Chaos (special_tiles): each special's")
    o.append(";  battle CHR set, its size in characters, and where its cells start in")
    o.append(";  lut_BstBigMap -- a byte a cell, row by row: the set's tile, bit 7 the")
    o.append(";  second palette, 0 nothing.  lut_BstBigOf: the special of enemy")
    o.append(";  BST_BIGFIRST on.")
    firsts = [e for e in range(NENEMY) if kinds[e] == KIND_SPECIAL]
    if firsts != list(range(firsts[0], NENEMY)):
        sys.exit("genbestiary: the fiends and Chaos are not the last enemies")
    o.append("BST_BIGFIRST = %d" % firsts[0])
    o.append("lut_BstBigOf:")
    o.append("  .BYTE " + ", ".join("%d" % special_of[e] for e in firsts))
    bigmap, at = [], []
    sizes = []
    for i, (_, look) in enumerate(specials):
        w, h, cells = special_tiles(look)
        if w > 16 or w * h > 192 or w % 2 or h % 2:
            sys.exit("genbestiary: special %d is %d x %d, past the sprite sheet" % (i, w, h))
        at.append(len(bigmap))
        bigmap += cells
        sizes.append((look[1], w, h))
    o.append("lut_BstBigSet:")
    for set_, w, h in sizes:
        o.append("  .FARADDR (CHUNK0 + BANK_BATTLECHR + %d) * $10000 + $%04X"
                 % (set_ // 8, 0x8000 + (set_ % 8) * 0x800))
    o.append("lut_BstBigW:")
    o.append("  .BYTE " + ", ".join("%d" % w for _, w, _ in sizes))
    o.append("lut_BstBigH:")
    o.append("  .BYTE " + ", ".join("%d" % h for _, _, h in sizes))
    o.append("lut_BstBigAt:")
    o.append("  .WORD " + ", ".join("%d" % a for a in at))
    o.append("lut_BstBigMap:")
    for i in range(0, len(bigmap), 16):
        o.append("  .BYTE " + ", ".join("$%02X" % b for b in bigmap[i:i + 16]))
    o.append("")
    o.append(";  The slots' cells, slot * 5 + column: the BG palette, the CGRAM index of")
    o.append(";  its first group's first colour and of its second's ($FF: none).")
    o.append("lut_BstCellPal:")
    o.append("  .BYTE " + ", ".join("%d" % groups[(s, c)][0] for s in range(SLOTS) for c in range(COLS)))
    o.append("lut_BstCellCgA:")
    o.append("  .BYTE " + ", ".join("%d" % (groups[(s, c)][0] * 16 + 3 * groups[(s, c)][1] + 1)
                                    for s in range(SLOTS) for c in range(COLS)))
    o.append("lut_BstCellCgB:")
    o.append("  .BYTE " + ", ".join(("%d" % (groups[(s, c)][0] * 16 + 3 * groups[(s, c)][2] + 1))
                                    if groups[(s, c)][2] is not None else "$FF"
                                    for s in range(SLOTS) for c in range(COLS)))
    o.append(";  ...and its first group's number in the palette, 0-4, for the fast")
    o.append(";  conversion a small or large picture's characters get (bst_convg0-4).")
    o.append("lut_BstCellGA:")
    o.append("  .BYTE " + ", ".join("%d" % groups[(s, c)][1] for s in range(SLOTS) for c in range(COLS)))
    o.append("")
    o += reach_tables()
    o.append("")
    open(OUT, "w").write("\n".join(o) + "\n")
    used = len({(p, g) for p, a, b in groups.values() for g in (a, b) if g is not None})
    print("bestiary: %d colour groups of 39, %d characters of 1023 at the worst, preview in %s"
          % (used, worst, os.path.relpath(PREVIEW, ROOT)))


#  Unseen enemies: a dark slate blue, showing against the black (user: "a dark
#  grey or blue").  Kept with the screen's own value (src/bestiary.asm).
SILHOUETTE_RGB = (40, 48, 72)


# --- what a seed can produce (bst_reach) ---------------------------------------
#  The header's count is out of the enemies a seed can put in front of the
#  party (user, 2026-11-12: "If you can count how many are reachable, that
#  makes more sense").  The screen works it out as it opens from the world's
#  own tables -- every zone's eight formations (RW_DOMAINS) and every trap
#  tile's (RW_PROPS) -- so these say only which zones and trap tiles can start
#  a fight at all, and which of a formation's groups can show up.
#
#  A zone fights if a party can stand somewhere and step onto a tile that
#  starts one there: on the overworld the zone is the square the party steps
#  from, of the kind the tile it steps onto says (OWCanMove: land by the
#  square, the river by the map's half, $40 and $41, the sea $42); on a
#  standard map, if the map has random-encounter tiles (SMMove_Battle).  Being
#  all zero is not the test: five such squares fight formation 0's IMPs, and
#  Sea Shrine B1's zone and Chaos's floor's hold formations no tile starts.
#  The tile test alone says squares a party never reaches fight; those are
#  UNREACHED, checked against worldgraph's reach by test_bestiary.
ZONE_NEVER, ZONE_FIGHTS, ZONE_LONGTOFR = 0, 1, 2
ZONE_UNLESSEDIT = 0x80          # + the overworld edit (RANDO_OWEDITS's bit)
UNREACHED = {0x19}              # all zero; land no party reaches
SHORT_TOFR_MAPS = range(52, 59) # the Temple of Fiends (past)'s floors before Chaos's
NMAPS = 61
OWP_FIGHT = 0x40                # the second property byte's: steps can fight


def bank(n):
    return open(os.path.join(ROOT, "game", "bank_%02X.dat" % n), "rb").read()


def decode_rle(src, off, count):
    out = []
    while src[off] != 0xFF and len(out) < count:
        b = src[off]
        if b < 0x80:
            out.append(b)
            off += 1
        else:
            out += [b & 0x7F] * (src[off + 1] or 256)
            off += 2
    return out[:count]


def ow_fighting(tiles):
    """The zones a step on the overworld can fight in, by the tiles alone."""
    props = bank(0)[0x0000:0x0100]
    p0 = [props[(t & 0x7F) * 2] for t in tiles]
    p1 = [props[(t & 0x7F) * 2 + 1] for t in tiles]
    live = set()
    for a in range(65536):
        x, y = a & 255, a >> 8
        for veh in (1, 2, 4):                   # foot, canoe, ship
            if p0[a] & veh:
                continue
            for b in (((x + 1) & 255) | y << 8, ((x - 1) & 255) | y << 8,
                      x | ((y + 1) & 255) << 8, x | ((y - 1) & 255) << 8):
                if p0[b] & veh or not p1[b] & OWP_FIGHT:
                    continue
                kind = p1[b] & 3
                live.add((y >> 5) * 8 + (x >> 5) if kind == 0 else
                         0x42 if kind == 2 else 0x40 | (y >> 7))
    return live - UNREACHED


def map_tiles():
    """Each standard map's tileset and its tiles."""
    b0 = bank(0)
    banks = b"".join(bank(n) for n in (4, 5, 6, 7))
    out = []
    for m in range(NMAPS):
        p = banks[m * 2] | banks[m * 2 + 1] << 8
        out.append((b0[0x2CC0 + m], set(decode_rle(banks, p, 4096))))
    return out


def zone_kinds():
    import owedits
    from genows import vanilla
    van = vanilla()
    live = ow_fighting(van)
    kinds = [ZONE_FIGHTS if z in live else ZONE_NEVER for z in range(128)]
    for k, name in enumerate(owedits.SETTINGS):
        edited = ow_fighting(owedits.apply(van, 1 << k))
        if edited - live:
            sys.exit("genbestiary: %s makes zones fight: %s" % (name, sorted(edited - live)))
        for z in live - edited:
            if kinds[z] != ZONE_FIGHTS:
                sys.exit("genbestiary: zone $%02X has two conditions" % z)
            kinds[z] = ZONE_UNLESSEDIT + k
    props = bank(0)[0x0800:0x1000]
    rates = rd("0B_8C00_mapencounterrates.bin")
    for m, (ts, tiles) in enumerate(map_tiles()):
        rnd = any(props[ts * 256 + t * 2] == TP_SPEC_BATTLE and props[ts * 256 + t * 2 + 1] & 0x80
                  for t in tiles)
        if not (rnd and rates[m]):
            continue
        z = 64 + m
        if kinds[z] != ZONE_NEVER:
            sys.exit("genbestiary: map %d's zone is the overworld's too" % m)
        kinds[z] = ZONE_LONGTOFR if m in SHORT_TOFR_MAPS else ZONE_FIGHTS
    return kinds


TP_SPEC_BATTLE = 0x0A
TRAP_LONGTOFR = 0x8000          # lut_BstTraps: only on floors Short ToFR skips


def trap_tiles():
    """The trap tiles some map places -- FFR's IsNonBossTrapTile, formation
    1-$72, as deal_traps deals them -- each a property offset, with
    TRAP_LONGTOFR if every map placing it is one Short ToFR skips.  The fiends'
    refights ($73-$76) are battle tiles too but never dealt; with the other
    bosses' fights they are the screen's own (bst_reach)."""
    props = bank(0)[0x0800:0x1000]
    where = {}
    for m, (ts, tiles) in enumerate(map_tiles()):
        for t in tiles:
            o = ts * 256 + (t & 0x7F) * 2
            if props[o] == TP_SPEC_BATTLE and 0 < props[o + 1] < 0x73:
                where.setdefault(o, set()).add(m)
    return [o | (TRAP_LONGTOFR if maps <= set(SHORT_TOFR_MAPS) else 0)
            for o, maps in sorted(where.items())]


def form_groups(f):
    """Which of formation f's groups can show up, as PrepareEnemyFormation
    fills its slots: a group of max 0 never does, nor one whose size has no
    slot left once the groups before it took their minimum.  Bits 0-3 the
    A-side's four, bits 4-5 the B-side's two (its first two groups, with
    bytes 14-15's counts).  A fiend or Chaos is its first group alone, whatever
    the counts (FinalizeEnemyFormation_FiendChaos)."""
    rec = FORM[f * 16:f * 16 + 16]
    kind, gfx = rec[0] >> 4, rec[1]
    out = 0
    for side, qty, shift in ((0, rec[6:10], 0), (1, rec[14:16], 4)):
        if kind >= 3:
            out |= 1 << shift
            continue
        if any(q >> 4 > q & 0x0F for q in qty):
            sys.exit("genbestiary: formation $%02X has a group's minimum past its maximum"
                     % (f | side << 7))
        slots = {0: [9, 0], 1: [0, 4], 2: [6, 2]}[kind]
        for g, q in enumerate(qty):
            size = gfx >> (2 * g) & 1           # the picture's bit 0: large
            lo, hi = q >> 4, q & 0x0F
            if hi and slots[size]:
                out |= 1 << (shift + g)
            slots[size] = max(0, slots[size] - min(lo, hi))
    return out


def reach_tables():
    o = [";  What a seed can produce (bst_reach; tools/genbestiary.py's zone_kinds,",
         ";  trap_tiles and form_groups).  Each zone: 0 it never fights, 1 it does, 2",
         ";  it does but under Short ToFR, $80 + k but under overworld edit k.",
         "BST_ZONE_LONGTOFR = %d" % ZONE_LONGTOFR,
         "BST_ZONE_UNLESSEDIT = $%02X" % ZONE_UNLESSEDIT,
         "lut_BstZone:"]
    kinds = zone_kinds()
    for i in range(0, 128, 16):
        o.append("  .BYTE " + ", ".join("$%02X" % k for k in kinds[i:i + 16]))
    traps = trap_tiles()
    o.append(";  The trap tiles a map places, each its property offset, bit 15 if only")
    o.append(";  on floors Short ToFR skips.")
    o.append("BST_NTRAPS = %d" % len(traps))
    o.append("lut_BstTraps:")
    for i in range(0, len(traps), 8):
        o.append("  .WORD " + ", ".join("$%04X" % t for t in traps[i:i + 8]))
    o.append(";  Each formation's groups that can show up: bits 0-3 the A-side's, 4-5")
    o.append(";  the B-side's.")
    o.append("lut_BstGroups:")
    groups = [form_groups(f) for f in range(128)]
    for i in range(0, 128, 16):
        o.append("  .BYTE " + ", ".join("$%02X" % g for g in groups[i:i + 16]))
    o.append("")
    return o

if __name__ == "__main__":
    main()
