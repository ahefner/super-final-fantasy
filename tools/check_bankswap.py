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
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXED = os.path.join(ROOT, "game", "bank_0F.asm")
OPT = [os.path.join(ROOT, "src", "optbank.asm"),
       os.path.join(ROOT, "src", "optmenu.asm")]

SWAPPERS = ("SwapPRG", "CallMusicPlay", "MusicPlay_L")


def fixed_bodies():
    """label -> the source lines of its routine, up to the next label."""
    lines = open(FIXED, encoding="latin-1").read().split("\n")
    out, cur = {}, None
    for l in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", l)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur:
            out[cur].append(l)
    return out


def reaches_swap(label, bodies, seen=None, depth=0):
    """Does this routine reach a bank swap, directly or a few calls down?"""
    if seen is None:
        seen = set()
    if label in seen or depth > 3 or label not in bodies:
        return None
    seen.add(label)
    for l in bodies[label]:
        code = l.split(";")[0]
        for s in SWAPPERS:
            if s in code:
                return label
        m = re.search(r"\b(?:JSR|JMP)\s+([A-Za-z_][A-Za-z0-9_]*)", code)
        if m:
            hit = reaches_swap(m.group(1), bodies, seen, depth + 1)
            if hit:
                return hit
    return None


def main():
    bodies = fixed_bodies()
    called = {}
    for path in OPT:
        src = open(path, encoding="latin-1").read().split("\n")
        for n, l in enumerate(src, 1):
            code = l.split(";")[0]
            m = re.search(r"\b(?:JSR|JMP)\s+([A-Za-z_][A-Za-z0-9_]*)", code)
            if m and m.group(1) in bodies:
                #  A call is guarded if cur_bank was pointed at this bank just
                #  before it.  Look back a little way rather than at one line:
                #  the setup is usually a few instructions above.
                window = "\n".join(src[max(0, n - 15):n])
                guarded = "STA cur_bank" in window and "CHUNK_OPT" in window
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
    if unguarded:
        print("\n%d call(s) would lose the program bank: point cur_bank at "
              "CHUNK_OPT first." % len(unguarded))
        return 1
    print("\nevery options-bank call that swaps banks sets cur_bank first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
