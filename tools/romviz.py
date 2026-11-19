#!/usr/bin/env python3
"""
romviz.py -- the 2MB image drawn bank by bank, out/romviz.html (user,
2026-11-18: "a visualization, bank by bank, of what's stored in that bank,
and a box mapping to bytes in that bank (downscaled) that indicates black
for 0 bytes and some color mapping that corresponds to the entropy of bytes
in that region", "with a short description for each box of what the bank is
used for").

Each of the image's 64KB banks is a box of 64-byte cells, 64 to a row (4KB
a row): rows 0-7 its low half, $0000-$7FFF; rows 8-11 $8000-$BFFF; rows
12-15 $C000-$FFFF.  A cell is

    black      its 64 bytes all zero
    coloured   its bytes' entropy, 0 to 6 bits a byte (64 bytes can show
               no more), dark purple to yellow: code and packed data run
               high, tables and text lower, fills at 0
    grey       a copy of data elsewhere in the image, by the same entropy:
               its 1KB page the same as one counted elsewhere (the fixed
               bank stamped into every chunk's $C000-$FFFF, the low halves
               that mirror their high halves, any bank past the last chunk)

and hovering one says where it is and what it is a copy of.  Beside each
box, what the bank holds, part by part, from mkrom.py's layout (ORDER,
EXTRA_CHUNKS, LOWHALF, the logic slots), and its count of data, copies and
blank.  At the top, the image's totals by kind.

    python3 tools/romviz.py [ROM] [OUT]

ROM is SuperFinalFantasy.sfc and OUT out/romviz.html unless given.  Reads
the ROM and out/ (the logic slots, the blobs' sizes) as the last build left
them; one self-contained page, no libraries.
"""
import base64, html, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mkrom

CELL = 64                       # bytes a cell
PAGE = 1024                     # bytes a page, the unit a copy is found in
BANK = mkrom.BANK

#  The game's sixteen NES banks (Constants.inc's BANK_* names, the
#  disassembly's).  Each is assembled from the disassembly and patched
#  (mkrom.ASSEMBLED), or raw data as the cartridge has it.
NES = {
    0x00: "Game data: the overworld's and the maps' tilesets, map objects, "
          "treasure, teleports, starting stats, a new game's save",
    0x01: "The overworld map, compressed, and the minimap's decompression",
    0x02: "Graphics: the overworld's and the map objects' (vehicles, people)",
    0x03: "Graphics: the towns' and dungeons' tiles",
    0x04: "Town and dungeon maps, compressed (first of three)",
    0x05: "Town and dungeon maps, compressed",
    0x06: "Town and dungeon maps, compressed (the last; the rest empty)",
    0x07: "Graphics: battle backdrops and enemies",
    0x08: "Graphics: battle enemies, continued",
    0x09: "The minimap; the menus' font; battle sprite graphics",
    0x0A: "Text: dialogue, item and spell names",
    0x0B: "Battle data: formations, encounter rates, enemy names, battle "
          "messages; the bridge and ending pictures",
    0x0C: "The battle engine; equipment stats; battle palettes",
    0x0D: "Music and sound; the minigame, the bridge and ending scenes, the "
          "intro's text, item prices",
    0x0E: "Menus, shops, the title screen, party creation, talking to people",
    0x0F: "The fixed bank: the main loop, walking and the maps, drawing, the "
          "routines every bank calls",
}
#  The chunks this project adds (mkrom.EXTRA_CHUNKS' names).
EXTRA = {
    "OPT": "Settings: the option block, presets and the options' code the game calls",
    "CREDITS": "The credits screen; the Bestiary's code",
    "RANDO": "The randomizer: its random numbers, the shuffles, their hooks in the game",
    "OPTTEXT": "The settings screen's descriptions (text)",
    "LOGIC": "The game's map's world logic, for key item placement (data)",
    "WORLD": "Entrance shuffle and the seed's logic; Map Select's map code",
    "ROLL": "New Game's roll screen: its picture, bleeps and fanfare",
    "TACTICS": "Boss tactics: where a boss aims",
    "OWS": "New Game's map edit screen",
    "NEWGAME": "New Game's flow and its presets",
    "OPTMENU": "The settings screen's engine and rows",
    "TAVERN": "Taverns; FUN%'s code",
    "OPTTEXT2": "More of the settings screen's descriptions",
    "OW7": "The Mode 7 overworld: the plane, the tilt, the ship, the landmarks",
}
#  Data laid into a chunk's low half (mkrom.LOWHALF), by file name.
BLOBS = [
    (r"fundata\.bin", "FUN%'s data: the scream's sample"),
    (r"bestiary\.bin", "The Bestiary's fiend and Chaos pictures"),
    (r"maps_..\.bin", "Map Select's maps: their minimaps, records and rows"),
    (r"ow7\.bin", "The Mode 7 plane's 256 characters, then the tilt's tables"),
    (r"ow7land_..\.bin", "The landmarks' frames: castles, the Temple, the Mirage Tower, the volcano"),
]
MIRROR = "A mirror of the high half: code never reads it"


def snesmap_comments():
    """CHUNK_X -> its comment in snesmap.inc, for a chunk EXTRA lacks."""
    out = {}
    for line in open(os.path.join(ROOT, "src", "snesmap.inc"), encoding="latin-1"):
        m = re.match(r"CHUNK_(\w+)\s*=\s*\$[0-9A-Fa-f]+\s*;\s*(.*)", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def blob_text(name):
    path = os.path.join(ROOT, "out", name)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    what = next((t for p, t in BLOBS if re.fullmatch(p, name)), name)
    if not size:
        return "Kept for %s (%s, empty now): %s" % (what[0].lower() + what[1:], name, MIRROR.lower())
    return "%s (%s, %s bytes)" % (what, name, format(size, ","))


def logic_slots():
    """[(map, chunk, offset)] from out/logic_slots.txt, the maps' names
    from maps/custom-maps.txt where genmaps.py can say."""
    names = {}
    try:
        import genmaps
        names = {i: e[3] for i, e in enumerate(genmaps.parse())}
    except Exception:
        pass
    out = []
    path = os.path.join(ROOT, "out", "logic_slots.txt")
    if os.path.exists(path):
        for line in open(path):
            if line.strip():
                i, c, off = map(int, line.split())
                out.append((names.get(i, "map %d" % i), c, off))
    return out


def describe(nbanks):
    """Per image bank: (title, [(range, text)])."""
    extra = {c: n for c, n in mkrom.EXTRA_CHUNKS.items()}
    comments = snesmap_comments()
    slots = logic_slots()
    used = (2 + len(mkrom.ORDER) + len(mkrom.EXTRA_CHUNKS)) * BANK // BANK
    out = []

    def low(chunk):
        parts = []
        mine = [(n, off) for n, c, off in slots if c == chunk]
        if chunk in mkrom.LOWHALF:
            parts.append(("$0000-$7FFF", blob_text(mkrom.LOWHALF[chunk])))
        elif mine:
            for half, rng in ((0x0000, "$0000-$3FFF"), (0x4000, "$4000-$7FFF")):
                n = next((n for n, off in mine if off == half), None)
                parts.append((rng, "World logic for %s, for key item placement on it" % n if n else MIRROR))
        else:
            parts.append(("$0000-$7FFF", MIRROR))
        return parts

    for b in range(nbanks):
        chunk = b - 1
        if b == 0:
            out.append(("The HAL", [
                ("$0000-$7FFF", MIRROR + "; the header's second copy at $7FB0"),
                ("$8000-$FFFF", "The HAL: the SNES layer under the game -- the NES's picture, "
                                "sound and controllers done on the SNES, DMA, the sound driver; "
                                "the SNES header at $FFB0")]))
        elif b >= used:
            src = 1 + (b - used) % (used - 1)
            out.append(("A repeat", [("$0000-$FFFF", "A repeat of image bank %d: the image made "
                                     "dense past the last chunk" % src)]))
        elif 1 <= b <= len(mkrom.ORDER):
            nes = int(mkrom.ORDER[chunk], 16)
            how = "patched" if mkrom.ORDER[chunk] in mkrom.ASSEMBLED else "as the cartridge has it"
            parts = low(chunk)
            if nes == 0x0F:
                parts += [("$8000-$BFFF", NES[nes] + " (%s)" % how),
                          ("$C000-$FFFF", "The fixed bank again, where the NES has it")]
            else:
                parts += [("$8000-$BFFF", NES[nes] + " (%s)" % how),
                          ("$C000-$FFFF", "The fixed bank, NES bank $0F, stamped into every chunk")]
            out.append(("NES bank $%02X" % nes, parts))
        elif b == 1 + len(mkrom.ORDER):
            size = os.path.getsize(os.path.join(ROOT, "out", "beam.bin"))
            out.append(("The altar beam", [("$0000-$FFFF", "The altar beam's HDMA tables, read "
                                            "straight from ROM (beam.bin, %s bytes); the rest empty"
                                            % format(size, ","))]))
        elif chunk in extra:
            name = extra[chunk]
            text = EXTRA.get(name) or comments.get(name, name)
            out.append(("Chunk $%02X, %s" % (chunk, name), low(chunk) + [
                ("$8000-$BFFF", text),
                ("$C000-$FFFF", "The fixed bank, NES bank $0F, stamped into every chunk")]))
        else:
            out.append(("Unassigned", [("$0000-$FFFF", "Nothing assigned")]))
    return out


def entropy(b):
    n = len(b)
    counts = {}
    for v in b:
        counts[v] = counts.get(v, 0) + 1
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def analyse(rom):
    """Per cell: entropy (0-255, of 6 bits a byte), and its kind: 0 data,
    1 zero, 2 copy, 3 a fill of one other value; per page the offset of
    the data it copies, or -1."""
    pages = len(rom) // PAGE
    first = {}
    #  The page counted as the data: the high half's over the low's, then
    #  $8000-$BFFF over $C000-$FFFF (a chunk's own over the fixed bank's
    #  stamp), then the earliest bank.
    def rank(off):
        bank, o = divmod(off, BANK)
        return (o < 0x8000, not 0x8000 <= o < 0xC000, bank, o)
    for p in range(pages):
        blk = rom[p * PAGE:(p + 1) * PAGE]
        if len(set(blk)) <= 1:
            continue
        key = bytes(blk)
        off = p * PAGE
        if key not in first or rank(off) < rank(first[key]):
            first[key] = off
    copy = [-1] * pages
    for p in range(pages):
        blk = bytes(rom[p * PAGE:(p + 1) * PAGE])
        if len(set(blk)) > 1 and first[blk] != p * PAGE:
            copy[p] = first[blk]
    ent, kind = bytearray(), bytearray()
    for c in range(len(rom) // CELL):
        blk = rom[c * CELL:(c + 1) * CELL]
        ent.append(min(255, round(entropy(blk) / 6 * 255)))
        if copy[c * CELL // PAGE] >= 0:
            kind.append(2)
        elif not any(blk):
            kind.append(1)
        elif len(set(blk)) == 1:
            kind.append(3)
        else:
            kind.append(0)
    return ent, kind, copy


PAGE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ROM Bank Map</title>
<style>
:root { --bg: #f7f7f5; --fg: #1d1d1b; --muted: #66665f; --line: #d8d8d2; --card: #ffffff; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg: #161615; --fg: #ececea; --muted: #a3a39c; --line: #34342f; --card: #1f1f1d; }
}
:root[data-theme="dark"] { --bg: #161615; --fg: #ececea; --muted: #a3a39c; --line: #34342f; --card: #1f1f1d; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--muted); margin: 0 0 20px; }
table.tot { border-collapse: collapse; margin: 8px 0 18px; font-variant-numeric: tabular-nums; }
table.tot td { padding: 3px 14px 3px 0; border-bottom: 1px solid var(--line); }
table.tot td.n { text-align: right; white-space: nowrap; }
.legend { display: flex; flex-wrap: wrap; gap: 18px; align-items: center; margin: 0 0 22px; color: var(--muted); }
.legend span.sw { display: inline-block; width: 14px; height: 14px; vertical-align: -2px; margin-right: 6px; border: 1px solid var(--line); }
.ramp { display: inline-block; width: 160px; height: 14px; vertical-align: -2px; margin: 0 6px; border: 1px solid var(--line); }
.bank { display: grid; grid-template-columns: minmax(0, 1fr) 560px; gap: 16px; padding: 14px 0;
        border-top: 1px solid var(--line); align-items: start; }
.bank h2 { font-size: 15px; margin: 0 0 2px; }
.bank .addr { color: var(--muted); font-size: 12px; margin: 0 0 6px; font-variant-numeric: tabular-nums; }
.bank dl { margin: 0; display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 2px 8px; font-size: 13px; }
.bank dt { color: var(--muted); font-variant-numeric: tabular-nums; }
.bank dd { margin: 0; }
.bank .counts { color: var(--muted); font-size: 12px; margin-top: 6px; font-variant-numeric: tabular-nums; }
canvas { width: 560px; height: 104px; display: block; image-rendering: pixelated; cursor: crosshair; }
#tip { position: fixed; pointer-events: none; background: var(--card); color: var(--fg); border: 1px solid var(--line);
       padding: 6px 8px; font-size: 12px; border-radius: 4px; display: none; white-space: nowrap;
       box-shadow: 0 2px 8px rgba(0,0,0,.15); font-variant-numeric: tabular-nums; }
@media (max-width: 900px) {
  .bank { grid-template-columns: minmax(0, 1fr); }
  canvas { width: 100%; height: auto; }
}
</style></head>
<body><main>
<h1>The ROM, bank by bank</h1>
<p class="sub">__SUB__</p>
<table class="tot">__TOTALS__</table>
<div class="legend">
  <span><span class="sw" style="background:#000"></span>all zero</span>
  <span>data, by entropy: 0<canvas class="ramp" id="ramp" width="160" height="14"></canvas>6 bits a byte</span>
  <span><span class="sw" style="background:#9a9a9a"></span>a copy of data elsewhere (grey by entropy)</span>
  <span>Each box: 64 bytes a cell, 4KB a row; rows from the top: $0000-$7FFF, $8000-$BFFF, $C000-$FFFF</span>
</div>
<div id="banks"></div>
</main>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const STOPS = [[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];
function ramp(t) {
  t = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(t)), f = t - i, a = STOPS[i], b = STOPS[i + 1];
  return [0, 1, 2].map(k => Math.round(a[k] + (b[k] - a[k]) * f));
}
function bytes(s) { const b = atob(s), out = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i); return out; }
const ent = bytes(DATA.ent), kind = bytes(DATA.kind);
const hex = (n, w) => n.toString(16).toUpperCase().padStart(w, "0");
const GUT = 46, CW = 8, CH = 6, SEP = 4;
function rowY(r) { return r * CH + (r >= 8 ? SEP : 0) + (r >= 12 ? SEP : 0); }
const rc = document.getElementById("ramp").getContext("2d");
for (let x = 0; x < 160; x++) { const c = ramp(x / 159); rc.fillStyle = `rgb(${c})`; rc.fillRect(x, 0, 1, 14); }
const host = document.getElementById("banks"), tip = document.getElementById("tip");
const muted = getComputedStyle(document.body).getPropertyValue("--muted") || "#888";
DATA.banks.forEach((bk, b) => {
  const div = document.createElement("div");
  div.className = "bank";
  const left = document.createElement("div");
  left.innerHTML = `<h2>Image bank ${b}: ${bk.title}</h2>` +
    `<div class="addr">SNES $${hex(0xC0 + b, 2)}:0000-FFFF` + (b ? ` (the game runs it at $${hex(0xA0 + b, 2)}:8000)` : "") + `</div>` +
    `<dl>${bk.parts.map(p => `<dt>${p[0]}</dt><dd>${p[1]}</dd>`).join("")}</dl>` +
    `<div class="counts">${bk.counts}</div>`;
  const cv = document.createElement("canvas");
  const W = GUT + 64 * CW, H = rowY(16) + 0;
  cv.width = W * 2; cv.height = H * 2;
  cv.style.aspectRatio = `${W} / ${H}`;
  const g = cv.getContext("2d");
  g.scale(2, 2);
  g.font = "10px ui-monospace, Menlo, monospace";
  g.fillStyle = muted.trim() || "#888";
  [["$0000", 0], ["$8000", 8], ["$C000", 12]].forEach(([t, r]) => g.fillText(t, 2, rowY(r) + 9));
  for (let i = 0; i < 1024; i++) {
    const c = b * 1024 + i, r = i >> 6, x = GUT + (i & 63) * CW, y = rowY(r);
    const k = kind[c], e = ent[c] / 255;
    let col;
    if (k === 1) col = [0, 0, 0];
    else if (k === 2) { const v = Math.round(70 + 120 * e); col = [v, v, v]; }
    else col = ramp(e);
    g.fillStyle = `rgb(${col})`;
    g.fillRect(x, y, CW, CH);
  }
  cv.addEventListener("mousemove", ev => {
    const rect = cv.getBoundingClientRect();
    const px = (ev.clientX - rect.left) * W / rect.width, py = (ev.clientY - rect.top) * H / rect.height;
    const col = Math.floor((px - GUT) / CW);
    let r = -1;
    for (let k = 0; k < 16; k++) if (py >= rowY(k) && py < rowY(k) + CH) r = k;
    if (col < 0 || col > 63 || r < 0) { tip.style.display = "none"; return; }
    const i = r * 64 + col, c = b * 1024 + i, off = i * 64;
    const k = kind[c], src = DATA.copy[(b * 65536 + off) >> 10];
    let what = ["data", "all zero", "a copy", "one value repeated"][k];
    if (k === 2) what += ` of image bank ${src >> 16}, $${hex((src & 0xFFFF) + (off & 1023), 4)}`;
    tip.innerHTML = `$${hex(0xC0 + b, 2)}:${hex(off, 4)}-${hex(off + 63, 4)}<br>` +
      `entropy ${(ent[c] / 255 * 6).toFixed(2)} bits a byte<br>${what}`;
    tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = (ev.clientY + 14) + "px";
  });
  cv.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  div.appendChild(left);
  div.appendChild(cv);
  host.appendChild(div);
});
</script>
</body></html>
"""


def kb(n):
    return "%s KB" % format(round(n / 1024), ",")


def main():
    rom_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "SuperFinalFantasy.sfc")
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "out", "romviz.html")
    rom = open(rom_path, "rb").read()
    if len(rom) % BANK:
        sys.exit("romviz: %s is %d bytes, not whole 64KB banks" % (rom_path, len(rom)))
    nbanks = len(rom) // BANK
    ent, kind, copy = analyse(rom)
    desc = describe(nbanks)
    per = BANK // CELL

    #  The totals, by kind: data where it is counted, copies, blank.
    groups = {}
    def add(g, n):
        groups[g] = groups.get(g, 0) + n
    banks = []
    nes_end = len(mkrom.ORDER)
    for b in range(nbanks):
        cells = kind[b * per:(b + 1) * per]
        n = [cells.count(k) * CELL for k in range(4)]
        for i, k in enumerate(cells):
            o = i * CELL
            if k == 2:
                add("Copies of data counted above", CELL)
            elif k in (1, 3):
                add("Blank: zeros, or one value repeated", CELL)
            elif b == 0:
                add("The HAL (the SNES layer under the game)", CELL)
            elif b <= nes_end and o >= 0x8000:
                add("The game's sixteen NES banks, as patched", CELL)
            elif o < 0x8000:
                add("Data in the chunks' low halves (maps, logic, Mode 7, Bestiary, scream, landmarks)", CELL)
            elif b == nes_end + 1:
                add("The altar beam's tables", CELL)
            else:
                add("The added chunks' code and data ($8000-$BFFF)", CELL)
        title, parts = desc[b]
        banks.append({"title": html.escape(title),
                      "parts": [[html.escape(r), html.escape(t)] for r, t in parts],
                      "counts": "data %s &middot; copies %s &middot; blank %s" % (
                          kb(n[0]), kb(n[2]), kb(n[1] + n[3]))})
    order = ["The game's sixteen NES banks, as patched", "The HAL (the SNES layer under the game)",
             "The added chunks' code and data ($8000-$BFFF)",
             "Data in the chunks' low halves (maps, logic, Mode 7, Bestiary, scream, landmarks)",
             "The altar beam's tables", "Copies of data counted above", "Blank: zeros, or one value repeated"]
    rows = "".join("<tr><td>%s</td><td class=\"n\">%s</td></tr>" % (html.escape(g), kb(groups[g]))
                   for g in order if g in groups)
    rows += "<tr><td><b>The image</b></td><td class=\"n\"><b>%s</b></td></tr>" % kb(len(rom))
    data = {"ent": base64.b64encode(bytes(ent)).decode(), "kind": base64.b64encode(bytes(kind)).decode(),
            "copy": copy, "banks": banks}
    sub = ("%s, %d banks of 64KB.  The original game is 256KB: sixteen 16KB banks." %
           (html.escape(os.path.basename(rom_path)), nbanks))
    page = (PAGE_HTML.replace("__SUB__", sub).replace("__TOTALS__", rows)
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(page)
    for g in order:
        if g in groups:
            print("%-90s %9s" % (g, kb(groups[g])))
    print("wrote %s" % os.path.relpath(out_path, ROOT))


if __name__ == "__main__":
    main()
