#!/usr/bin/env python3
"""
presetdefs.py -- every setting a preset can name, read from the source.

The settings screen's rows (optmenu.asm's lut_OptRows) and its value rows'
readouts (lut_ValTab, lut_ValCount), parsed as the assembler would lay them
out, so a preset file names a setting by the label the screen shows and a
value by the readout the screen shows.  Nothing here is a second copy of the
settings: a row added to the screen is a row the presets can set, and a test
holds this parse to the built ROM's tables (test_presets).

    rows()   -> [Row], every checkbox and value row, in screen order
    Row      -> section, label, kind ("chk"/"val"), arg (flag bit or scalar),
                values (the readouts, stripped; None for a checkbox)
"""
import os, re
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

Row = namedtuple("Row", "section label kind arg values")

#  The game's font, the way fftext.inc writes it, read back.
_FONT = {0xFF: " ", 0xBE: "'", 0xBF: ",", 0xC0: ".", 0xC2: "-", 0xC4: "!", 0xC5: "?", 0xE0: "%",
         0xC1: "+"}
_FONT.update({0x80 + i: str(i) for i in range(10)})
_FONT.update({0x8A + i: chr(ord("A") + i) for i in range(26)})
_FONT.update({0xA4 + i: chr(ord("a") + i) for i in range(26)})


def _consts():
    """Every NAME = expression in the include files the tables use, evaluated."""
    raw = {}
    for f in ("snesmap.inc", "optmenu.inc"):
        for m in re.finditer(r"^([A-Za-z_]\w*)\s*=\s*([^;\n]+)", open(os.path.join(SRC, f)).read(), re.M):
            raw.setdefault(m.group(1), m.group(2).strip())
    out = {}
    def ev(name, depth=0):
        if name in out:
            return out[name]
        if depth > 40 or name not in raw:
            raise KeyError(name)
        out[name] = _eval(raw[name], lambda n: ev(n, depth + 1))
        return out[name]
    for n in list(raw):
        try:
            ev(n)
        except (KeyError, SyntaxError, ZeroDivisionError, TypeError, ValueError, NameError):
            pass
    return out


def _eval(expr, look):
    e = expr.replace(".MOD", "%").replace(".mod", "%")
    e = re.sub(r"\$([0-9A-Fa-f]+)", lambda m: str(int(m.group(1), 16)), e)
    e = re.sub(r"%([01]+)\b", lambda m: str(int(m.group(1), 2)), e)
    e = re.sub(r"[A-Za-z_]\w*", lambda m: str(look(m.group(0))), e)
    e = e.replace("~", "~")
    return int(eval(e, {"__builtins__": {}}))


def _table(src, label, end_labels=None):
    """The lines of src from label: to the next label definition."""
    i = src.index("\n" + label + ":")
    j = len(src)
    for m in re.finditer(r"^\w+:", src[i + len(label) + 3:], re.M):
        j = i + len(label) + 3 + m.start()
        break
    return src[i:j]


def _expand(text, consts, var=None):
    """The items of .BYTE/.RES/.REPEAT lines, flattened, as source tokens or ints."""
    out, lines, k = [], text.split("\n"), 0
    while k < len(lines):
        line = lines[k].split(";")[0].strip()
        k += 1
        m = re.match(r"\.REPEAT\s+([^,]+)(?:,\s*(\w+))?", line, re.I)
        if m:
            depth, body = 1, []
            while depth:
                l2 = lines[k]
                k += 1
                t = l2.split(";")[0].strip()
                if re.match(r"\.REPEAT", t, re.I):
                    depth += 1
                elif re.match(r"\.ENDREP", t, re.I):
                    depth -= 1
                    if not depth:
                        break
                body.append(l2)
            n = _eval(m.group(1), lambda x: consts[x])
            for i in range(n):
                local = dict(consts)
                if m.group(2):
                    local[m.group(2)] = i
                out += _expand("\n".join(body), local)
            continue
        m = re.match(r"(?:\w+:\s*)?\.RES\s+([^,]+),\s*(.+)", line, re.I)
        if m:
            out += [m.group(2).strip()] * _eval(m.group(1), lambda x: consts[x])
            continue
        m = re.match(r"(?:\w+:\s*)?\.BYTE\s+(.+)", line, re.I)
        if m:
            out += [t.strip() for t in m.group(1).split(",")]
    return out


def _readouts(src, label, consts):
    """A readout table's entries, stripped: FFPAD strings, or bytes decoded."""
    body = _table(src, label)
    items = []
    for line in body.split("\n")[1:]:
        code = line.split(";")[0]
        m = re.search(r'FFPAD\s+"([^"]*)"', code)
        if m:
            items.append(m.group(1).strip())
            continue
        m = re.match(r"\s*\.BYTE\s+(.+)", code, re.I)
        if m:
            vals = [_eval(t.strip(), lambda x: consts[x]) for t in m.group(1).split(",")]
            items.append("".join(_FONT.get(v, "?") for v in vals).strip())
    return items


def rows():
    src = open(os.path.join(SRC, "optmenu.asm")).read()
    consts = _consts()
    tab = [t.lstrip("<") for t in _expand(_table(src, "lut_ValTabLo"), consts)]
    count = [_eval(t, lambda x: consts[x]) for t in _expand(_table(src, "lut_ValCount"), consts)]
    assert len(tab) == len(count), (len(tab), len(count))
    body = src[src.index("\nlut_OptRows:"):src.index("\nlut_OptRowsEnd:")]
    lines = body.split("\n")
    out, section, k = [], None, 0
    while k < len(lines):
        m = re.match(r"\s*\.BYTE\s+\$0([0-3]),\s*(\$?[0-9A-Fa-f]+)\b", lines[k])
        k += 1
        if not m:
            continue
        kind = int(m.group(1))
        arg = int(m.group(2)[1:], 16) if m.group(2).startswith("$") else int(m.group(2))
        #  The label: FFPAD, OPTLABEL, or raw bytes over the next lines.
        nxt = lines[k] if k < len(lines) else ""
        s = re.search(r'(?:FFPAD|OPTLABEL)\s+\{?"([^"]*)"', nxt)
        if s:
            label = s.group(1)
            k += 1
        else:
            vals = []
            while k < len(lines) and len(vals) < 30 and re.match(r"\s*\.BYTE\s+\$[0-9A-F]{2}", lines[k]) \
                    and not re.match(r"\s*\.BYTE\s+\$0[0-3],", lines[k]):
                vals += [int(t.strip()[1:], 16) for t in lines[k].split(";")[0].split(".BYTE")[1].split(",")]
                k += 1
            label = "".join(_FONT.get(v, "") for v in vals)   # an item's icon: not text
        label = " ".join(label.split())
        if kind == 0:
            section = label
        elif kind == 1:
            out.append(Row(section, label, "chk", arg, None))
        elif kind == 2:
            vals = _readouts(src, tab[arg], consts)[:count[arg]]
            out.append(Row(section, label, "val", arg, vals))
    return out


if __name__ == "__main__":
    for r in rows():
        print("%-16s %-24s %s %3d %s" % (r.section, r.label, r.kind, r.arg, r.values or ""))
