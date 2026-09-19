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
import sys

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

ENTRY = 3           # JMP abs


def labels(path):
    out = {}
    for line in open(path):
        f = line.split()
        if len(f) >= 3 and f[0] == "al":
            out[f[2].lstrip(".")] = int(f[1], 16)
    return out


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
    if bad:
        print("\na jump table has something wedged into it -- entries reached by"
              "\nindex now land inside an instruction.  Move the new code out.")
        return 1
    print("\njump tables are contiguous")
    return 0


if __name__ == "__main__":
    sys.exit(main())
