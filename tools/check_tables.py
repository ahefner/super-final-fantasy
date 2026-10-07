#!/usr/bin/env python3
"""
check_tables.py -- the '_L' jump tables must stay contiguous.

The fixed bank opens and closes with tables of three-byte JMPs.  Disch calls
them "pseudo-jump tables": the original assembler had no linker, so other banks
reached the fixed bank through entries at known, evenly spaced addresses.  ca65
does have a linker and resolves them by name, which makes them *look* like an
ordinary run of routines -- an inviting place to tuck a new one.

It is not.  bank $0B reaches bank $0C's equivalent list by arithmetic:

    DoCrossPageJump:
        CLC
        ADC #<BankC_CrossBankJumpList     ; A is an entry index, a multiple of 3
        STA btltmp+6

Anything inserted into a table like that shifts every entry after it, and an
entry index then lands part-way through an instruction.  A five-byte routine
dropped into the middle of the battle table displaced everything from
UndrawNBattleBlocks_L onward -- the box drawing, BattleWaitForVBlank,
BattleScreenShake, FormatBattleString -- which is a battle that glitches on
entry, corrupts the enemy-name box, breaks attack animations and eventually
jumps somewhere it should not.  None of it is visible in the source, and the
patch that caused it applied cleanly and assembled without a word.

So: check the spacing, every build.  Run after linking, with a label file:

    ld65 -C snes.cfg -o /dev/null -Ln out/labels.txt out/*.o
    python3 tools/check_tables.py out/labels.txt
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#  Each table, in the order its entries appear in the source.  A new entry has
#  to be added here as well, or the check will not know to expect it.
TABLES = {
    "$C000 fixed-bank entry table": [
        "GameStart_L", "DrawComplexString_L", "DrawBox_L",
        "CallMusicPlay_L", "UpdateJoy_L", "DrawPalette_L",
    ],
    "battle cross-bank table": [
        "EnterBattle_L", "Battle_WritePPUData_L", "Battle_ReadPPUData_L",
        "BattleCrossPageJump_L", "ClearBattleMessageBuffer_L",
        "UndrawNBattleBlocks_L", "DrawRosterBox_L", "DrawCommandBox_L",
        "DrawCombatBox_L", "DrawBattleMagicBox_L", "BattleWaitForVBlank_L",
        "DrawBattleItemBox_L", "DrawDrinkBox_L", "BattleRNG_L",
        "BattleScreenShake_L", "FormatBattleString_L", "SwapBtlTmpBytes_L",
    ],
    "bank $0C cross-bank list": [
        "ExitBattle_L", "BattleFadeOutAndRestartGame_L",
    ],
}

ENTRY = 3                # JMP abs
DESC_LINES = 5           # rows in the settings screen's description pane


def labels(path):
    out = {}
    for line in open(path):
        f = line.split()
        if len(f) >= 3 and f[0] == "al":
            out[f[2].lstrip(".")] = int(f[1], 16)
    return out


def descriptions():
    """A menu description says how many lines it has; make it tell the truth.

    The records used to be five fixed lines, padded with spaces.  That padding
    came to 2.8KB in a bank with nothing left, so each one now begins with a
    count and holds only the lines it uses.  The count is the one thing in the
    record the assembler cannot check: too small and the last lines never
    appear, too large and the pane draws the next description's first line.
    Both are quiet -- the menu still works, the text is just wrong -- and only
    on the row that has the bad count.
    """
    src = open(os.path.join(ROOT, "src", "opttext.asm"), encoding="latin-1").read()
    bad = []
    n = 0
    for m in re.finditer(r"^(lut_Desc\w*):[^\n]*\n"
                         r"  FFLINES (\d+)\n"
                         r"((?:  (?:\.BYTE|FFPAD)[^\n]*\n)*)", src, re.M):
        name, said, body = m.group(1), int(m.group(2)), m.group(3)
        have = len([l for l in body.split("\n") if l.strip()])
        n += 1
        if said != have:
            bad.append("   COUNT  %s says %d lines and has %d" % (name, said, have))
        elif said > DESC_LINES:
            bad.append("   LONG   %s has %d lines; the pane holds %d"
                       % (name, said, DESC_LINES))
    if n == 0:
        bad.append("   ?? no description records found -- has the format changed?")
    for line in bad:
        print(line)
    if not bad:
        print("   ok     %-28s %2d records, each as long as it claims"
              % ("menu descriptions", n))
    return bool(bad)


def main():
    sym = labels(sys.argv[1] if len(sys.argv) > 1 else "out/labels.txt")
    bad = False
    for name, entries in TABLES.items():
        have = [(e, sym[e]) for e in entries if e in sym]
        missing = [e for e in entries if e not in sym]
        if len(have) < 2:
            print("   ?? %-28s only %d of %d entries are exported; not checked"
                  % (name, len(have), len(entries)))
            continue
        for (n1, a1), (n2, a2) in zip(have, have[1:]):
            if a2 - a1 != ENTRY:
                bad = True
                print("   SPLIT  %s: %d bytes between %s ($%04X) and %s ($%04X)"
                      % (name, a2 - a1, n1, a1, n2, a2))
        if not bad:
            note = "" if not missing else "  (%d not exported)" % len(missing)
            print("   ok     %-28s %2d entries, 3 bytes apart, from $%04X%s"
                  % (name, len(have), have[0][1], note))
    if descriptions():
        print("\na menu description's line count disagrees with the lines"
              "\nbelow it, so the pane will draw the wrong text.")
        return 1
    if bad:
        print("\na jump table has something wedged into it -- entries reached by"
              "\nindex now land inside an instruction.  Move the new code out.")
        return 1
    print("\njump tables are contiguous")
    return 0


if __name__ == "__main__":
    sys.exit(main())
