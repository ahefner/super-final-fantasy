#!/usr/bin/env python3
"""genows.py -- the map edit screen's tables (src/owscreen.asm).

    lut_OwsTiles    the minimap's colour for each overworld tile, as the
                    game's minimap has it (bank $09's lut_MinimapTileset):
                    bits 0-1 the colour, bit 2 a marker
    lut_OwsGates    each view's list gates, as a mask of the active-list
                    bits (owedits.py).  A view is what the screen shows for
                    the selected setting: its own list, but Bahamut's dock
                    is the two's variant alone when the land bridge is
                    ticked (OWS_VIEW_BAHAMUTBRIDGE).  The land bridge needs
                    no second view: the variant's two tiles are its own
    lut_OwsRows     each setting's minimap rows -- pixel rows, two map rows
                    each -- that any of its lists writes, a bit each
    lut_OwsSiteN    how many places each view edits, at most OWS_SITES
    lut_OwsSiteX/Y  each place's middle, map tiles, OWS_SITES a view
    lut_OwsSiteW    each place's span, the larger of its width and height
    lut_OwsCharMask each pixel row's characters that any list writes in, a
                    bit each, the first in bit 0: the rest are the baked
                    minimap's whatever is ticked or selected, so ows_prow
                    packs only these
    lut_OwsBaked    the minimap with no edit and nothing selected, as the
                    screen draws it: its 256 4bpp characters, OWS_CHR's
                    8KB, copied whole

A place is a cluster of its writes no two of which are more than
CLUSTER tiles apart, largest first.
"""
import os, re, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import owedits as O

OUT = os.path.join(ROOT, "gen", "owscreen.inc")

#  What each does, in the order of owedits.SETTINGS; the game's font has no
#  colon or semicolon.
DESCRIPTIONS = [
    "Walk to the Dwarves, and canoe from Pravoka to Crescent.",
    "Walk the Dwarf Cave's lands to Northwest Castle.",
    "Docks by Onrac and by the Mirage Tower.",
    "A dock by the Ryukahn Desert, where the AIRSHIP rises.",
    "A dock on Bahamut's island, no AIRSHIP to his cave.",
    "A river dock that reaches Lefein, no AIRSHIP.",
    "The BRIDGE joins Pravoka and Lefein, Coneria's is land.",
    "A pass through the mountains to Gaia from Lefein.",
    "Roads from Lefein to the desert, and on to Ordeals.",
    "A river from the Dwarf Cave to Melmond, no CANAL.",
    "A forest hides Sarda, reached only through Titan's Tunnel.",
    "Walk across the swamp to the AIRSHIP, no CANOE.",
    "Land from Ordeals through Cardia to the Waterfall river.",
    "The SHIP sits useless in a drydock at the Gaia Fjord.",
]
#  The unwinnable warning's, by rando_winnable's reason: 0 anything, 1
#  (WIN_AIRSHIP) the airship never raised though the FLOATER is there.
WARNINGS = [
    "This can't be won.  The way to Chaos never opens.",
    "This can't be won.  The AIRSHIP never rises.",
]
OWS_SITES = 4
CLUSTER = 6


def minimap_tiles():
    src = open(os.path.join(ROOT, "game", "bank_09.asm"), encoding="latin-1").read()
    at = src.index("lut_MinimapTileset:")
    vals = []
    for line in src[at:].split("\n")[1:]:
        line = line.split(";")[0]
        if ".BYTE" in line:
            vals += [int(v) for v in re.findall(r"\b\d+\b", line.replace(".BYTE", ""))]
        if len(vals) >= 128:
            break
    assert len(vals) >= 128
    return vals[:128]


#  The view past the fourteen settings' own.
OWS_VIEW_BAHAMUTBRIDGE = 14     # Bahamut's dock, the land bridge ticked
OWS_VIEWS = 15


def view_gates(v):
    """The lists view v shows: as owedits.active_lists has them, the dock's
    own list gives way to the variant under the land bridge."""
    if v == OWS_VIEW_BAHAMUTBRIDGE:
        return 1 << O.LIST_BAHAMUT_BRIDGE
    return 1 << v


def view(sel, flags):
    if sel == O.BAHAMUT_DOCK and flags >> O.CARDIA_BRIDGE & 1:
        return OWS_VIEW_BAHAMUTBRIDGE
    return sel


def gate_writes(g):
    return [(x, y) for name, gate in O.ORDER if g >> gate & 1 for x, y, _ in O.LISTS[name]]


def writes(s):
    """Every tile any of setting s's views writes: the rows to redraw when
    it is ticked or selected."""
    g = 1 << s
    if s in (O.BAHAMUT_DOCK, O.CARDIA_BRIDGE):
        g |= 1 << O.LIST_BAHAMUT_BRIDGE
    return gate_writes(g)


def sites(v):
    pts = sorted(set(gate_writes(view_gates(v))))
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(pts)):
        for j in range(i):
            if max(abs(pts[i][0] - pts[j][0]), abs(pts[i][1] - pts[j][1])) <= CLUSTER:
                parent[find(i)] = find(j)
    groups = {}
    for i, p in enumerate(pts):
        groups.setdefault(find(i), []).append(p)
    out = []
    for g in sorted(groups.values(), key=lambda g: (-len(g), g[0])):
        xs, ys = [p[0] for p in g], [p[1] for p in g]
        out.append(((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2,
                    max(max(xs) - min(xs), max(ys) - min(ys)) + 1))
    return out[:OWS_SITES]


def bank01():
    """Bank $01 as the disassembly has it: its binary's 8KB, then the .BYTE
    lines up to the first label -- the overworld's rows and their pointers
    at $8000."""
    data = bytearray(open(os.path.join(ROOT, "game", "bin", "bank_01_data.bin"), "rb").read())
    for line in open(os.path.join(ROOT, "game", "bank_01.asm"), encoding="latin-1").read().split("\n"):
        line = line.split(";")[0]
        if re.match(r"^\w+:", line):
            break
        if ".BYTE" in line:
            data += bytes(int(v, 16) for v in re.findall(r"\$([0-9A-Fa-f]{2})", line))
    return bytes(data)


def vanilla():
    """The overworld unedited, 256 x 256, as DecompressMap reads it."""
    b = bank01()
    out = []
    for r in range(256):
        off = (b[2 * r] | b[2 * r + 1] << 8) - 0x8000
        row = []
        while b[off] != 0xFF and len(row) < 256:
            if b[off] < 0x80:
                row.append(b[off])
                off += 1
            else:
                row += [b[off] & 0x7F] * (b[off + 1] or 256)
                off += 2
        assert len(row) == 256, r
        out += row
    return out


def baked(ts):
    """The minimap of vanilla(), a pixel its four tiles' colours ORed, as
    ows_prow packs it with nothing selected: 32 bytes a character, plane 3
    -- the selection's -- clear."""
    w = vanilla()
    out = bytearray()
    for cy in range(16):
        for cx in range(16):
            planes = [[0] * 8 for _ in range(3)]
            for r in range(8):
                p = cy * 8 + r
                for c in range(8):
                    x = (cx * 8 + c) * 2
                    v = 0
                    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                        v |= ts[w[x + dx + 256 * (2 * p + dy)]]
                    col = 4 if v & 4 else v & 3
                    for k in range(3):
                        if col >> k & 1:
                            planes[k][r] |= 0x80 >> c
            for r in range(8):
                out += bytes((planes[0][r], planes[1][r]))
            for r in range(8):
                out += bytes((planes[2][r], 0))
    return bytes(out)


def main():
    n = len(O.SETTINGS)
    lines = [";  Generated by tools/genows.py -- do not edit.", "",
             "OWS_SETTINGS = %d" % n, "OWS_SITES = %d" % OWS_SITES,
             "OWS_VIEWS = %d" % OWS_VIEWS,
             "OWS_VIEW_BAHAMUTBRIDGE = %d" % OWS_VIEW_BAHAMUTBRIDGE, "",
             "lut_OwsTiles:"]
    t = minimap_tiles()
    for i in range(0, 128, 16):
        lines.append("  .BYTE " + ", ".join("$%02X" % v for v in t[i:i + 16]))
    lines.append("lut_OwsGates:")
    lines.append("  .WORD " + ", ".join("$%04X" % view_gates(v) for v in range(OWS_VIEWS)))
    lines.append("lut_OwsRows:              ; 16 bytes a setting, pixel row p in bit p & 7 of byte p >> 3")
    for s in range(n):
        bits = [0] * 16
        for _, y in writes(s):
            p = y // 2
            bits[p >> 3] |= 1 << (p & 7)
        lines.append("  .BYTE " + ", ".join("$%02X" % b for b in bits) + "   ; " + O.SETTINGS[s])
    st = [sites(v) for v in range(OWS_VIEWS)]
    lines.append("lut_OwsSiteN:")
    lines.append("  .BYTE " + ", ".join(str(len(x)) for x in st))
    for name, k in (("X", 0), ("Y", 1), ("W", 2)):
        lines.append("lut_OwsSite%s:" % name)
        for s in range(OWS_VIEWS):
            row = [x[k] for x in st[s]] + [0] * (OWS_SITES - len(st[s]))
            lines.append("  .BYTE " + ", ".join("%d" % v for v in row))
    ring = [[1 if 5.6 <= ((x - 7.5) ** 2 + (y - 7.5) ** 2) ** 0.5 < 7.6 else 0 for x in range(16)] for y in range(16)]
    lines.append("lut_OwsRingChr:           ; OBJ characters 0, 1, 16, 17, 4bpp, 32 bytes each")
    for ty, tx in ((0, 0), (0, 1), (1, 0), (1, 1)):
        rows = [sum(ring[ty * 8 + r][tx * 8 + c] << (7 - c) for c in range(8)) for r in range(8)]
        planes = []
        for r in rows:
            planes += [r, 0]                         # planes 0 and 1
        planes += [0] * 16                           # planes 2 and 3
        lines.append("  .BYTE " + ", ".join("$%02X" % b for b in planes))
    #  The settings screen's own two checkbox tiles (optmenu.asm's
    #  lut_CheckboxCHR, NES 2bpp: a grey ring, 1, on the window's blue, 2,
    #  filled white, 3, when ticked), as SNES 2bpp for BG3: the ring colour
    #  2, the fill 3, the blue clear.
    src = open(os.path.join(ROOT, "src", "optmenu.asm"), encoding="latin-1").read()
    at = src.index("lut_CheckboxCHR:")
    cb = []
    for line in src[at:].split("\n")[1:7]:
        if ".BYTE" in line:
            cb += [int(v, 16) for v in re.findall(r"\$([0-9A-Fa-f]{2})", line.split(";")[0])]
    assert len(cb) == 32, cb
    lines.append("lut_OwsBoxChr:            ; BG3 characters 1 and 2, the settings screen's boxes")
    for t in range(2):
        p0, p1 = cb[t * 16:t * 16 + 8], cb[t * 16 + 8:t * 16 + 16]
        lines.append("  .WORD " + ", ".join("$%04X" % ((a & b) | (a << 8)) for a, b in zip(p0, p1)))
    #  Each setting's description, and each warning, wrapped for the two
    #  layouts: two lines of 30 below the grid, five of 20 beside the zoom's
    #  frame.
    for label, width, count, texts in (("lut_OwsDescWide", 30, 2, DESCRIPTIONS),
                                       ("lut_OwsDescNarrow", 20, 5, DESCRIPTIONS),
                                       ("lut_OwsWarnWide", 30, 2, WARNINGS),
                                       ("lut_OwsWarnNarrow", 20, 5, WARNINGS)):
        lines.append("%s:" % label)
        for s_, text in enumerate(texts):
            wrapped = textwrap.wrap(text, width)
            assert len(wrapped) <= count, (O.SETTINGS[s_], width, wrapped)
            for k in range(count):
                lines.append('  FFPAD "%s", %d' % (wrapped[k] if k < len(wrapped) else "", width))
    #  Each setting's minimap colour for a decoded tile's byte: bits 0-1 the
    #  colour, bit 2 a marker, bit 3 the selected setting's mark.
    lines.append("lut_OwsCol16:")
    lines.append("  .BYTE " + ", ".join("%d" % ((4 if v & 4 else v & 3) | (8 if v & 8 else 0)) for v in range(16)))
    masks = [0] * 128
    for name, _ in O.ORDER:
        for x, y, _ in O.LISTS[name]:
            masks[y // 2] |= 1 << (x // 16)
    lines.append("lut_OwsCharMask:")
    for i in range(0, 128, 16):
        lines.append("  .WORD " + ", ".join("$%04X" % m for m in masks[i:i + 16]))
    bk = baked(minimap_tiles())
    lines.append("lut_OwsBaked:              ; 256 characters, 32 bytes each")
    for i in range(0, len(bk), 32):
        lines.append("  .BYTE " + ", ".join("$%02X" % b for b in bk[i:i + 32]))
    lines.append("OWS_DESCWIDE = 30")
    lines.append("OWS_DESCNARROW = 20")
    lines.append("")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(lines))


if __name__ == "__main__":
    main()
