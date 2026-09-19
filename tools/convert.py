#!/usr/bin/env python3
"""
convert.py -- rewrite Disch's 6502 Final Fantasy disassembly into 65816 source
for the SNES port.

The game logic is left completely alone; the 65816 runs it verbatim in
emulation mode.  What changes is every touch of NES hardware:

  $2000-$2007  PPU        -> macros in src/nesio.inc that call into the HAL
  $4000-$4017  pAPU / I/O -> pAPU shadow writes, OAM DMA, controller reads

Anything that cannot be expressed as a local substitution -- the reset code,
the MMC1 bank switching, the NMI/vblank handshake, the joypad reader -- is
replaced wholesale by a patch file under snes/patches/.  A patch whose "old"
text is not found verbatim is a hard error, so the patches cannot silently rot
when the upstream source changes.
"""

import os, re, sys, shutil

HERE   = os.path.dirname(os.path.abspath(__file__))
ROOT   = os.path.dirname(HERE)                       # snes/
#  The 6502 source, vendored into the tree.  It used to be read from a sibling
#  checkout of the disassembly, which made a build depend on a path outside the
#  repository and left the game's own code somewhere this project could not
#  change.  Both were fine while the port was only translating; neither is,
#  now that bugfixes and QoL work mean editing the game itself.
SRCDIR = os.path.join(ROOT, "game")
GEN    = os.path.join(ROOT, "gen")
PATCH  = os.path.join(ROOT, "patches")

BANKS  = ["01", "09", "0B", "0C", "0D", "0E", "0F"]

# ---------------------------------------------------------------------------
#  Instruction-level substitutions
# ---------------------------------------------------------------------------
SUBS = [
    (r"STA\s+\$2000\b", "wPPUCTRL"),
    (r"STA\s+\$2001\b", "wPPUMASK"),
    (r"STY\s+\$2001\b", "wPPUMASK_Y"),
    (r"LDA\s+\$2002\b", "rPPUSTATUS"),
    (r"LDX\s+\$2002\b", "rPPUSTATUS_X"),
    (r"LDY\s+\$2002\b", "rPPUSTATUS_Y"),
    (r"BIT\s+\$2002\b", "bPPUSTATUS"),
    (r"STA\s+\$2005\b", "wPPUSCROLL"),
    (r"STA\s+\$2006\b", "wPPUADDR"),
    (r"STX\s+\$2006\b", "wPPUADDR_X"),
    (r"STY\s+\$2006\b", "wPPUADDR_Y"),
    (r"STA\s+\$2007\b", "wPPUDATA"),
    (r"STX\s+\$2007\b", "wPPUDATA_X"),
    (r"STY\s+\$2007\b", "wPPUDATA_Y"),
    (r"LDA\s+\$2007\b", "rPPUDATA"),
    (r"STA\s+\$4014\b", "wOAMDMA"),
    (r"STA\s+\$4016\b", "wJOYSTROBE"),
    (r"STY\s+\$4016\b", "wJOYSTROBE_Y"),
    (r"STX\s+\$4016\b", "wJOYSTROBE_X"),
    (r"LDA\s+\$4016\b", "rJOYPAD"),
    (r"LDA\s+\$4015\b", "rAPUSTATUS"),
]
# everything else in $4000-$4017 is a plain pAPU register write
APU_SUBS = [
    (r"STA\s+\$40([01][0-9A-F])\b", r"wAPU $\1"),
    (r"STX\s+\$40([01][0-9A-F])\b", r"wAPU_X $\1"),
    (r"STY\s+\$40([01][0-9A-F])\b", r"wAPU_Y $\1"),
]

SUBS_C     = [(re.compile(p, re.I), r) for p, r in SUBS]
APU_SUBS_C = [(re.compile(p, re.I), r) for p, r in APU_SUBS]

# Lines that define data must never be touched.
DATA_DIRECTIVE = re.compile(r"^\s*\.?(BYTE|WORD|DBYT|ADDR|RES|ASCIIZ|INCBIN)\b", re.I)

#  Most of the game's data blobs carry their own address in their filename --
#  bin/0D_B600_orbchr.bin belongs at $B600 of bank $0D.  That is not decoration:
#  the banks lay their data out by sequential assembly, with no .org and no
#  .res, and other banks reach it at absolute addresses baked into
#  Constants.inc (lut_OrbCHR = $B600) or at pointers baked into the data.  So a
#  patch that changes size by even one byte silently drags every blob after it,
#  which is how a 24-byte saving in the ending scene's clear loop turned into
#  wrong orb graphics, broken menu text, and story strings missing their first
#  24 characters.
#
#  Turn that into a build error: assert each blob lands where its name says.
#  Six blobs predate the convention and are skipped; everything else is covered.
INCBIN_ADDR = re.compile(r'^(\s*)\.INCBIN\s+"bin/([0-9A-F]{2})_([0-9A-F]{4})_', re.I)


def split_comment(line):
    """Split a source line into (code, comment) at the first ';' outside a string."""
    inq = False
    for i, ch in enumerate(line):
        if ch == '"':
            inq = not inq
        elif ch == ';' and not inq:
            return line[:i], line[i:]
    return line, ""


NOT_APU = re.compile(r"\$401[46]\b")


def convert_line(line):
    code, comment = split_comment(line)
    if DATA_DIRECTIVE.match(code):
        return line, 0
    n = 0
    for rx, rep in SUBS_C:
        code, k = rx.subn(rep, code)
        n += k
    if NOT_APU.search(code):
        sys.exit("unhandled access to a non-audio register, which the pAPU "
                 "catch-all would silently swallow:\n    %s" % line.strip())
    for rx, rep in APU_SUBS_C:
        code, k = rx.subn(rep, code)
        n += k
    return code + comment, n


# ---------------------------------------------------------------------------
#  Patches
# ---------------------------------------------------------------------------
def debug_wanted(name):
    """Does FFDEBUG ask for this debug patch?

    FFDEBUG=1 (or "all") turns on every one, which is rarely what is wanted:
    epilogue takes over every standard map, so it and altar_tiles cannot both
    be on and still let you walk into a town.  FFDEBUG=<tag>[,<tag>...] applies
    only the patches whose names contain one of the tags, and the names are
    grouped so a tag picks up a whole setup -- FFDEBUG=chaos brings chaos_form
    along with the two patches that make the fight winnable.
    """
    want = os.environ.get("FFDEBUG", "")
    if not want:
        return False
    if want in ("1", "all"):
        return True
    return any(t.strip() and t.strip() in name for t in want.split(","))


def load_patches(bank):
    """Read this bank's patches -> list of (name, old, new).

    patches/bank_XX/ always applies: those are the routines the port cannot
    translate locally, and a build without them is not the game.  Everything
    under patches/debug/ changes how the game plays -- to put an effect that is
    normally hours away in front of a fresh save -- and applies only when
    FFDEBUG asks.  The two live in separate trees so that distinction is a
    property of where a patch is, not of what it was named.
    """
    out = []
    for d, is_debug in ((os.path.join(PATCH, "bank_" + bank), False),
                        (os.path.join(PATCH, "debug", "bank_" + bank), True)):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".patch"):
                continue
            if is_debug and not debug_wanted(name):
                continue
            text = open(os.path.join(d, name)).read()
            if "--- OLD\n" not in text or "\n--- NEW\n" not in text:
                sys.exit("%s/%s: missing '--- OLD' / '--- NEW' markers" % (d, name))
            body = text.split("--- OLD\n", 1)[1]
            old, new = body.split("\n--- NEW\n", 1)
            # a patch file may end with a trailing newline the author did not mean
            if new.endswith("\n") and not new.endswith("\n\n"):
                new = new[:-1]
            out.append((name, old, new))
    return out



HEADER = """; ---------------------------------------------------------------------------
;  GENERATED by snes/tools/convert.py from %s -- do not edit.
;  Edit the original 6502 source, or add a patch under snes/patches/.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
%s.include "snesmap.inc"
.include "nesio.inc"

"""


def main():
    os.makedirs(GEN, exist_ok=True)

    # Constants.inc / variables.inc are pure equates: use them as-is, except
    # that the minimap's CHR staging buffer can be moved out of PRG-RAM (which
    # is cartridge SRAM here) into WRAM, to test whether that memory is at
    # fault.  $0D00-$0FFF is exactly the $300 bytes it needs and the game never
    # touches it.
    shutil.copyfile(os.path.join(SRCDIR, "Constants.inc"),
                    os.path.join(GEN, "Constants.inc"))
    v = open(os.path.join(SRCDIR, "variables.inc"), encoding="latin-1").read()
    #  The ending scene's draw buffer moves out of PRG-RAM into WRAM bank $7F,
    #  which frees $6E00-$6EFF -- the only page the buffer claimed on its own --
    #  for the option block.  The two patches under patches/bank_0D/ put the
    #  data bank where these stores need it.  This is a port change, not a game
    #  change, so it is rewritten here rather than edited into the 6502 source.
    v = v.replace("theend_drawbuf  = $6800     ; $700 bytes!",
                  "theend_drawbuf  = THEENDBUF ; $700 bytes, in WRAM bank $7F")

    v = v.replace("mm_decorchr     = $7000",
                  ".ifdef DECOR_IN_WRAM\n"
                  "mm_decorchr     = $0D00\n"
                  ".else\n"
                  "mm_decorchr     = $7000\n"
                  ".endif")
    open(os.path.join(GEN, "variables.inc"), "w", encoding="latin-1").write(v)

    # macros.inc: keep LDABRA, but the page-boundary assertions describe NES
    # raster timing that no longer applies, so they become no-ops.
    open(os.path.join(GEN, "macros.inc"), "w").write(
        ".macro LDABRA v, lbl\n"
        "    LDA #v\n"
        "  .if v = 0\n"
        "    BEQ lbl\n"
        "  .else\n"
        "    BNE lbl\n"
        "  .endif\n"
        ".endmacro\n\n"
        "; Page-crossing checks guarded NES cycle timing; meaningless here.\n"
        ".macro CRITPAGECHECK lbl\n.endmacro\n"
        ".macro PAGECHECK lbl\n.endmacro\n")

    # .incbin paths in the source are relative to the file's directory
    link = os.path.join(GEN, "bin")
    want = os.path.join(SRCDIR, "bin")
    #  Re-point it if it aims somewhere else: a stale link from before the
    #  source was vendored would still resolve, and the build would quietly go
    #  on reading the old tree.
    if os.path.islink(link) and os.path.realpath(link) != os.path.realpath(want):
        os.unlink(link)
    if not os.path.exists(link):
        os.symlink(want, link)

    total = 0
    for bank in BANKS:
        path = os.path.join(SRCDIR, "bank_%s.asm" % bank)
        text = open(path, "r", encoding="latin-1").read()
        #  The disassembly uses CRLF.  Normalise first so patch files can
        #  be written with ordinary newlines and still match verbatim.
        text = text.replace("\r\n", "\n")

        patches = load_patches(bank)
        for name, old, new in patches:
            #  ".res n" fills with zero, and $00 is BRK.  Padding a patch
            #  that way puts a BRK in the instruction stream; where the bytes
            #  are reachable the game jumps through the BRK vector and lands
            #  somewhere unrelated.  That is a crash a long way from its
            #  cause, so refuse it here -- padding must say ", $EA".
            for ln, l in enumerate(new.split("\n"), 1):
                code = l.split(";")[0].rstrip()
                if re.match(r"^\s*\.res\s+[^,]+$", code):
                    sys.exit("%s/%s line %d: '.res' without a fill value "
                             "pads with $00 (BRK); write '.res n, $EA'"
                             % (bank, name, ln))

            if text.count(old) != 1:
                sys.exit("bank_%s: patch %s matched %d times (want exactly 1)"
                         % (bank, name, text.count(old)))
            text = text.replace(old, new)

        out, n, guards = [], 0, 0
        for line in text.split("\n"):
            l, k = convert_line(line)
            #  The fixed bank is exempt.  Its contents are reached by linked
            #  symbol rather than by baked address -- every literal in
            #  Constants.inc points into $8000-$BFFF, never into $C000-$FFFF --
            #  and the port's own patches reshape it on purpose, so its blobs
            #  have long since moved off the addresses their names record.
            m = None if bank == "0F" else INCBIN_ADDR.match(l)
            if m:
                out.append('%s.assert * = $%s, error, "bank %s: data blob moved '
                           'from $%s -- a patch changed size; see snesmap.inc"'
                           % (m.group(1), m.group(3), m.group(2), m.group(3)))
                guards += 1
            out.append(l)
            n += k
        total += n

        dst = os.path.join(GEN, "bank_%s.asm" % bank)
        with open(dst, "w", encoding="latin-1") as f:
            home = "NESIO_HOME = 1        ; the hardware thunks live in this bank\n" if bank == "0F" else ""
            f.write(HEADER % ("bank_%s.asm" % bank, home))
            f.write("\n".join(out))
        print("bank_%s: %4d hardware accesses rewritten, %d patches, "
              "%d data blobs pinned" % (bank, n, len(patches), guards))
    print("total: %d" % total)


if __name__ == "__main__":
    main()
