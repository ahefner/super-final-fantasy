#!/usr/bin/env python3
"""
check_bankswap.py -- find options-bank calls that would lose the program bank.

Code in the options bank reaches the fixed bank with a plain JSR, because the
fixed bank is stamped into every chunk.  That is safe right up until the
routine it calls swaps banks: SwapPRG returns into whichever bank cur_bank
names, and if that is not the options bank, the instruction after the JSR is
some other bank's bytes.  On hardware it is a freeze; in the source it looks
like an ordinary call.

So: for every routine the options bank JSRs into, walk the fixed bank's source
from that label and report any that reach SwapPRG, directly or through another
call.  A reported routine is not necessarily a bug -- it is a call that must
set cur_bank first, and the report says which ones do.

The walk has to follow fallthrough as well as JSR and JMP.  Disch's code ends
a routine by running off the end of it into the next one all over the place:

    Battle_UpdatePPU_UpdateAudio_FixedBank:
        ...
      ; JMP BattleUpdateAudio_FixedBank  ; <- flow continues to this routine

    BattleUpdateAudio_FixedBank:
        ...
        JSR CallMusicPlay

There is no call to follow, so an earlier version of this script walked the
first routine, found nothing, and pronounced it safe -- while that very call
was freezing battles on entry.  A routine whose last instruction is not a
return or an unconditional jump continues into the label below it, and is
treated here as calling it.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXED = os.path.join(ROOT, "game", "bank_0F.asm")
#  Each file this project adds a chunk for, with the chunk cur_bank has to name
#  before a swapping call made from it.  The credits chunk has the same hazard
#  as the options chunk -- it calls the music driver every frame.
OPT = [(os.path.join(ROOT, "src", "optbank.asm"), "CHUNK_OPT"),
       (os.path.join(ROOT, "src", "optmenu.asm"), "CHUNK_OPT"),
       (os.path.join(ROOT, "src", "optshop.asm"), "CHUNK_OPT"),
       (os.path.join(ROOT, "src", "credits.asm"), "CHUNK_CREDITS"),
       (os.path.join(ROOT, "src", "rando.asm"), "CHUNK_RANDO")]

SWAPPERS = ("SwapPRG", "CallMusicPlay", "MusicPlay_L")


#  Instructions after which control does not continue to the next line.
TERMINATORS = re.compile(r"\b(RTS|RTL|RTI|JMP|BRA|BRL)\b", re.I)


def fixed_bodies():
    """label -> (source lines of its routine, the label it falls through to)."""
    lines = open(FIXED, encoding="latin-1").read().split("\n")
    bodies, order, cur = {}, [], None
    for l in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", l)
        if m:
            cur = m.group(1)
            bodies[cur] = []
            order.append(cur)
            #  a label may carry code on the same line
            rest = l[m.end():].split(";")[0].strip()
            if rest:
                bodies[cur].append(rest)
        elif cur:
            bodies[cur].append(l)

    out = {}
    for i, label in enumerate(order):
        body = bodies[label]
        last = None
        for l in reversed(body):
            code = l.split(";")[0].strip()
            if code and not code.startswith("."):
                last = code
                break
        falls = None
        if last is None or not TERMINATORS.search(last):
            #  runs off the end into whatever is defined next
            if i + 1 < len(order):
                falls = order[i + 1]
        out[label] = (body, falls)
    return out


def reaches_swap(label, bodies, seen=None, depth=0):
    """Does this routine reach a bank swap, directly or a few calls down?"""
    if seen is None:
        seen = set()
    if label in seen or depth > 6 or label not in bodies:
        return None
    seen.add(label)
    body, falls = bodies[label]
    for l in body:
        code = l.split(";")[0]
        for s in SWAPPERS:
            if s in code:
                return label
        m = re.search(r"\b(?:JSR|JMP)\s+([A-Za-z_][A-Za-z0-9_]*)", code)
        if m:
            hit = reaches_swap(m.group(1), bodies, seen, depth + 1)
            if hit:
                return hit
    if falls:                      # runs off the end into the next routine
        return reaches_swap(falls, bodies, seen, depth + 1)
    return None


def forces_bank(label, bodies):
    """Does this routine pick its own bank to return to?

    Setting cur_bank before the call is only half the contract: the callee has
    to honour it.  DrawEquipMenuStrings does not -- it ends

        LDA #BANK_MENUS
        STA cur_bank
        STA ret_bank
        JSR SwapPRG_L
        RTS

    so it returns to bank $0E whatever the caller asked for, and a JSR to it
    from the options chunk lands the RTS in the wrong chunk.  Such a routine
    can only be called from the bank it chooses, or through a trampoline
    that lives there.

    The test is the *last* store to cur_bank in the body: if what feeds it is
    an immediate, the bank is the routine's choice.  DrawComplexString also
    writes cur_bank, but its last write restores a saved value, so it honours
    what it was given.
    """
    if label not in bodies:
        return None
    body, _ = bodies[label]
    prev = ""
    forced = None
    for l in body:
        code = l.split(";")[0].strip()
        if re.match(r"STA\s+cur_bank\b", code, re.I):
            m = re.match(r"LDA\s+#([A-Za-z_][A-Za-z0-9_]*)", prev, re.I)
            forced = m.group(1) if m else None
        if code:
            prev = code
    return forced


def main():
    bodies = fixed_bodies()
    called = {}
    for path, chunk in OPT:
        src = open(path, encoding="latin-1").read().split("\n")
        for n, l in enumerate(src, 1):
            code = l.split(";")[0]
            m = re.search(r"\b(?:JSR|JMP)\s+([A-Za-z_][A-Za-z0-9_]*)", code)
            if m and m.group(1) in bodies:
                #  A call is guarded if cur_bank was pointed at this bank just
                #  before it.  Look back a little way rather than at one line:
                #  the setup is usually a few instructions above.
                window = "\n".join(src[max(0, n - 15):n])
                guarded = "STA cur_bank" in window and chunk in window
                called.setdefault(m.group(1), []).append(
                    ("%s:%d" % (os.path.basename(path), n), guarded))

    unguarded = []
    guarded = []
    for label in sorted(called):
        via = reaches_swap(label, bodies)
        if not via:
            continue
        for site, ok in called[label]:
            (guarded if ok else unguarded).append((label, via, site))

    for label, via, site in guarded:
        print("   ok        %-22s swaps via %-20s %s" % (label, via, site))
    for label, via, site in unguarded:
        print("   UNGUARDED %-22s swaps via %-20s %s" % (label, via, site))

    #  A callee that chooses its own return bank cannot be reached with a
    #  plain JSR from here at all, however carefully cur_bank was set.
    forced = []
    for label in sorted(called):
        bank = forces_bank(label, bodies)
        if bank:
            for site, _ in called[label]:
                forced.append((label, bank, site))
    for label, bank, site in forced:
        print("   FORCED    %-22s returns to %-19s %s" % (label, bank, site))
    if forced:
        print("\n%d call(s) return to a bank of the callee's choosing: reach "
              "them through a trampoline in that bank." % len(forced))
        return 1
    if unguarded:
        print("\n%d call(s) would lose the program bank: point cur_bank at "
              "the calling chunk first." % len(unguarded))
        return 1
    print("\nevery options-bank call that swaps banks sets cur_bank first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
