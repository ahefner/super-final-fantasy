#!/usr/bin/env python3
"""
genpresets.py -- New Game's presets, from presets/*.toml, for the cart.

Each file is one entry of the New Game list, in filename order:

    name        what the list shows (28 columns)
    description the pane under the list, wrapped here to 5 lines of 28
    base        true for exactly one, Improved Vanilla: it must set every
                setting, and the rest start from it (user, 2026-10-21:
                "default against the Improved Vanilla preset if left unset")
    inherit     optional: another preset's name, whose settings come first
    title       optional: the title screen's preset this one is ("Vanilla",
                "Improved"), so choosing it leaves the title's options row
                naming it; any other reads Custom
    skip_to_party
                optional: true to go straight to party creation, past every
                screen of New Game's flow -- Vanilla alone (user,
                2026-10-22: Improved Vanilla is "the baseline preset one
                might customize").  Not with anything randomized: the map
                edit screen's winnability check would be skipped too
    [settings]  label = readout, or label = true/false for a checkbox
    [map_edits] the map edit screen's label = true or false: the edits
                the screen starts from for this preset, over its parent's
                (user, 2026-10-24: "Presets should be able to toggle map
                edits individually").  The labels are read from the
                screen's own table, so they cannot drift from the bits

Labels and readouts are the settings screen's own, read from the source by
presetdefs.py; anything else stops the build with the choices.  Writes

  gen/presets.inc       each preset's every setting as (row, value) pairs,
                        which newgame.asm's ngp_apply writes through the
                        settings screen's own tables; and its map edits,
                        the bits the map edit screen starts from
  gen/presetcount.inc   NGP_COUNT, for optmenu.inc's row count
  gen/presetrows.inc    the New Game list's rows, one a preset, at the end
                        of optmenu.asm's lut_OptRows
  gen/presetdesc.inc    their descriptions, for opttext.asm, and the macros
                        NGP_DESCLO and NGP_DESCHI that list them in its
                        pointer tables
"""
import os, sys, textwrap, tomllib, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import presetdefs

ROOT = presetdefs.ROOT
PRESETS = os.path.join(ROOT, "presets")
OUT = os.path.join(ROOT, "gen", "presets.inc")
GEN = os.path.join(ROOT, "gen")
NAME_W = 28                     # a pick row's label: the 29 columns of a row, less the cell it is set in
DESC_W, DESC_LINES = 28, 5
TITLE_PRESETS = {"Vanilla": 0, "Improved": 1}
TITLE_CUSTOM = 3
#  The randomization screen's sections (optmenu.asm, from ROW_TREASURES): a
#  preset that sets anything in them away from its first value randomizes
#  something -- needs a seed, as opt_needseed asks at run time -- and may not
#  skip New Game's screens.
RANDO_SECTIONS = ("TREASURES", "RANDOMIZATION", "KEY ITEMS")


#  The Party modes that draw on the seed, by readout: rando.asm's
#  rando_partyseeded, which test_forcedparty holds this to.  The others are
#  the same party every game and need no seed (user, 2026-11-02).
PARTY_SEEDED = {"Balanced", "4 Forced", "3 Forced", "2 Forced", "1 Forced", "Fi + 3", "Th + 3"}


def randomizes(settings, rows):
    """Whether a preset sets anything on the randomization screen -- Party
    only in a mode that draws on the seed."""
    for r in rows:
        if r.section in RANDO_SECTIONS and settings[r.label]:
            if r.label != "Party" or r.values[settings[r.label]] in PARTY_SEEDED:
                return True
    return False
TEXT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ',.-!?%+")


class PresetError(Exception):
    pass


def load(directory=PRESETS):
    """[(filename, table)], in filename order."""
    out = []
    for f in sorted(os.listdir(directory)):
        if f.endswith(".toml"):
            with open(os.path.join(directory, f), "rb") as fh:
                try:
                    out.append((f, tomllib.load(fh)))
                except tomllib.TOMLDecodeError as e:
                    raise PresetError("%s: %s" % (f, e))
    return out


def _value(row, v, where):
    if row.kind == "chk":
        if not isinstance(v, bool):
            raise PresetError("%s: \"%s\" is a checkbox: true or false, not %r" % (where, row.label, v))
        return int(v)
    if not isinstance(v, str) or v not in row.values:
        raise PresetError("%s: \"%s\" = %r is not one of its values: %s"
                          % (where, row.label, v, ", ".join('"%s"' % x for x in row.values)))
    return row.values.index(v)


def _text(s, where, what):
    bad = sorted(set(s) - TEXT_CHARS)
    if bad:
        raise PresetError("%s: the %s has %s, which the game's font cannot draw"
                          % (where, what, ", ".join(repr(c) for c in bad)))


def resolve(files, rows=None):
    """Each preset as (name, description lines, title index, {label: value index}),
    in list order.  Raises PresetError with what is wrong and where."""
    rows = rows if rows is not None else presetdefs.rows()
    by_label = {r.label: r for r in rows}
    labels = [r.label for r in rows]
    if len(by_label) != len(rows):
        raise PresetError("two settings share a label")
    tables, names = {}, []
    for f, t in files:
        for key in t:
            if key not in ("name", "description", "base", "inherit", "title", "skip_to_party", "settings",
                           "map_edits"):
                raise PresetError("%s: unknown field \"%s\"" % (f, key))
        name = t.get("name")
        if not isinstance(name, str) or not name:
            raise PresetError("%s: no name" % f)
        _text(name, f, "name")
        if len(name) > NAME_W:
            raise PresetError("%s: the name is %d long, past %d" % (f, len(name), NAME_W))
        if name in tables:
            raise PresetError("%s: a second preset named \"%s\"" % (f, name))
        own = {}
        for label, v in t.get("settings", {}).items():
            if label not in by_label:
                near = difflib.get_close_matches(label, labels, 3)
                raise PresetError("%s: no setting \"%s\"%s" % (f, label,
                                  "; did you mean %s?" % ", ".join('"%s"' % n for n in near) if near else ""))
            own[label] = _value(by_label[label], v, f)
        tables[name] = (f, t, own)
        names.append(name)
    bases = [n for n in names if tables[n][1].get("base")]
    if len(bases) != 1:
        raise PresetError("exactly one preset must be the base; %s" % (bases or "none is"))
    base = bases[0]
    missing = [l for l in labels if l not in tables[base][2]]
    if missing:
        raise PresetError("%s, the base, leaves out %s" % (tables[base][0], ", ".join('"%s"' % m for m in missing)))

    def settings(name, seen=()):
        if name in seen:
            raise PresetError("presets inherit in a circle: %s" % " -> ".join(seen + (name,)))
        f, t, own = tables[name]
        if t.get("base"):
            return dict(own)
        parent = t.get("inherit")
        if parent is None:
            out = settings(base, seen + (name,))
        elif parent not in tables:
            raise PresetError("%s: inherits \"%s\", which no preset is named" % (f, parent))
        else:
            out = settings(parent, seen + (name,))
        out.update(own)
        return out

    out = []
    for name in names:
        f, t, _ = tables[name]
        desc = " ".join(str(t.get("description", "")).split())
        _text(desc, f, "description")
        lines = textwrap.wrap(desc, DESC_W)
        if len(lines) > DESC_LINES:
            raise PresetError("%s: the description wraps to %d lines of %d; %d fit"
                              % (f, len(lines), DESC_W, DESC_LINES))
        title = t.get("title")
        if title is not None and title not in TITLE_PRESETS:
            raise PresetError("%s: title \"%s\" is not one of %s" % (f, title, ", ".join(TITLE_PRESETS)))
        skip = t.get("skip_to_party", False)
        if not isinstance(skip, bool):
            raise PresetError("%s: skip_to_party is true or false" % f)
        if skip and randomizes(settings(name), rows):
            raise PresetError("%s: skips New Game's screens but randomizes something, which only "
                              "the map edit screen checks can be won" % f)
        #  A scaling range's max no lower than its min, as the menu keeps it.
        #  Their steps are in percent order, so the indices compare.
        s = settings(name)
        for label in s:
            if label.endswith(" max") and s.get(label[:-4] + " min", 0) > s[label]:
                raise PresetError("%s: \"%s\" is below \"%s\"" % (f, label, label[:-4] + " min"))
        out.append((name, lines, TITLE_PRESETS.get(title, TITLE_CUSTOM), s))
    return out


def edit_bits(files, labels=None):
    """Each preset's map edits, as the bits of RANDO_OWEDITS the map edit
    screen starts from, in list order: its [map_edits] over its parent's,
    label i being bit i (the screen's own table, presetdefs.map_edits).
    Raises PresetError for a label the screen has not, a value not true or
    false, or an edit on a preset that skips New Game's screens."""
    labels = labels if labels is not None else presetdefs.map_edits()
    tables = {}
    for f, t in files:
        own = {}
        for label, v in t.get("map_edits", {}).items():
            if label not in labels:
                near = difflib.get_close_matches(label, labels, 3)
                raise PresetError("%s: no map edit \"%s\"%s" % (f, label,
                                  "; did you mean %s?" % ", ".join('"%s"' % n for n in near) if near else ""))
            if not isinstance(v, bool):
                raise PresetError("%s: map edit \"%s\" is true or false, not %r" % (f, label, v))
            own[label] = v
        tables[t.get("name")] = (t, own)
    base = next(n for n, (t, _) in tables.items() if t.get("base"))

    def edits(name):
        t, own = tables[name]
        out = {} if t.get("base") else dict(edits(t.get("inherit") or base))
        out.update(own)
        return out
    out = []
    for f, t in files:
        bits = sum(1 << labels.index(l) for l, v in edits(t.get("name")).items() if v)
        if bits and t.get("skip_to_party"):
            raise PresetError("%s: skips New Game's screens but has map edits, which only the map "
                              "edit screen checks can be won" % f)
        out.append(bits)
    return out


def skips(files):
    """Whether each preset goes straight to party creation, in list order."""
    return [bool(t.get("skip_to_party")) for _, t in files]


def emit(presets, rows, skip, edits):
    o = ["; Generated by tools/genpresets.py from presets/*.toml -- edit those.", ""]
    o.append("lut_NgpEdits:                   ; the map edits each starts from (RANDO_OWEDITS)")
    o.append("  .WORD " + ", ".join("$%04X" % e for e in edits))
    o.append("lut_NgpTitle:                   ; the title's preset each is, or Custom")
    o.append("  .BYTE " + ", ".join(str(t) for _, _, t, _ in presets))
    o.append("lut_NgpFlow:                    ; 1: on to the randomization screen; 0: to party creation")
    o.append("  .BYTE " + ", ".join(str(int(not k)) for k in skip))
    o.append("lut_NgpDataPtr:")
    o.append("  .WORD " + ", ".join("lut_NgpData%d" % i for i in range(len(presets))))
    #  Each setting a pair: a checkbox's flag bit + $80, or a value row's
    #  scalar; then the value.  $FF ends it.
    for i, (name, _, _, s) in enumerate(presets):
        o.append("lut_NgpData%d:                  ; %s" % (i, name))
        for r in rows:
            code = (0x80 | r.arg) if r.kind == "chk" else r.arg
            o.append("  .BYTE $%02X, %d          ; %s" % (code, s[r.label], r.label))
        o.append("  .BYTE $FF")
    assert all(r.arg < 0x80 for r in rows if r.kind == "val") and len(rows) * 2 < 255
    return "\n".join(o) + "\n"


def emit_rows(presets):
    o = ["; Generated by tools/genpresets.py from presets/*.toml -- edit those.",
         "; The New Game list's presets, as rows of lut_OptRows (optmenu.asm)."]
    for i, (name, _, _, _) in enumerate(presets):
        o.append("  .BYTE OPTROW_PICK, %d   ; %s" % (i, name))
        o.append('  FFPAD "%s", 30' % name)
    return "\n".join(o) + "\n"


def emit_desc(presets):
    o = ["; Generated by tools/genpresets.py from presets/*.toml -- edit those.",
         "; The New Game list's descriptions (opttext.asm), one per preset row."]
    for i, (name, lines, _, _) in enumerate(presets):
        o.append("lut_DescNgp%d:  ; %s" % (i, name))
        o.append("  FFLINES %d" % len(lines))
        for line in lines:
            o.append('  FFPAD {"%s"}, %d' % (line, DESC_W))
    for half, op in (("LO", "<"), ("HI", ">")):
        o.append(".macro NGP_DESC%s" % half)
        o.append("  .BYTE " + ", ".join("%slut_DescNgp%d" % (op, i) for i in range(len(presets))))
        o.append(".endmacro")
    return "\n".join(o) + "\n"


def main():
    rows = presetdefs.rows()
    try:
        files = load()
        presets = resolve(files, rows)
        edits = edit_bits(files)
    except PresetError as e:
        sys.exit("presets: %s" % e)
    os.makedirs(GEN, exist_ok=True)
    open(OUT, "w").write(emit(presets, rows, skips(files), edits))
    open(os.path.join(GEN, "presetcount.inc"), "w").write(
        "; Generated by tools/genpresets.py.\nNGP_COUNT = %d\n" % len(presets))
    open(os.path.join(GEN, "presetrows.inc"), "w").write(emit_rows(presets))
    open(os.path.join(GEN, "presetdesc.inc"), "w").write(emit_desc(presets))
    print("presets: %d, %d settings each" % (len(presets), len(rows)))


if __name__ == "__main__":
    main()
