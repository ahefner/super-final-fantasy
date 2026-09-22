#!/usr/bin/env python3
"""
profranges.py -- build a range file for the instrumented ares profiler.

The SCROLLSTAT trace that snesmap.inc describes is unusable: SRAM is 8KB and
every bank aliases it, so the page it wanted is the game's own PRG-RAM.  What
works instead is the profiler in the ares build under FFR/ares, which reports,
once per displayed frame:

    frame N total <master clocks> ... blanked <lines> lit <mask>
             <name> <clocks> <instructions> <first scanline> <last scanline>

`blanked` is the measurement that matters for flicker: it counts *picture*
scanlines rendered with forced blank, which is what the eye sees as a black
band when a flush runs past the end of vblank.  The per-range first/last
scanline is what says where a flush started and where it ended -- give it
flush_scroll (hal_flush's first stage) and flush_altar (its last) and the pair
brackets the whole flush.

    python3 tools/profranges.py > /tmp/ranges.txt
    ARES_HAL_PROF=/tmp/ranges.txt ARES_HAL_PROF_OUT=/tmp/prof.txt \
        tools/testrun.sh "f300, start, f150, ..."

Two things to know before reading any numbers off it.

**Keep every range inside one bank.**  The profiler rejects an instruction with
a single pair of comparisons against the lowest and highest range address, and
only walks the list for what falls between.  Ranges in two banks make that span
cover every game bank, so the list is walked for nearly every instruction and
the emulator drops to a few frames a second -- slow enough that drive.py's
frame waits time out and the script ends up somewhere else entirely.  That is
why this emits the HAL bank by default.

**A frame in the log is not a frame of the game.**  The dump happens when the
PPU finishes the picture, which is inside the flush, so a flush that overruns
is split across two lines of the log and its stages are counted in whichever
line they landed in.  Totals across a pair of lines are trustworthy; a single
line's are not.  `blanked` and the first/last scanlines are, which is why they
are the ones to reason from.

Labels come from ca65 listings rather than the link map, because ld65 -Ln
writes only exported symbols and almost nothing in the HAL is exported.  A
range runs from its label to the next one in the same file, so a routine's
callees are their own ranges and the breakdown is a breakdown rather than a
tree: hal_flush's own line is its bookkeeping, not its total.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#  Which file, at which bank, and the routines worth naming.  nt_piece is in
#  the list because leaving it out is how an entire flush went missing: it sat
#  between two named ranges, so its cost was filed under "other" and a flush
#  measured at nineteen scanlines was really forty-eight.
FILES = [
    ("hal.asm", 0xC0, """hal_waitvbl hal_flush flush_scroll flush_pal flush_chr
        flush_nt column_flush nt_put nt_piece flush_oam flush_raster
        flush_ntsplit flush_altar hal_ntblit hal_ntfill hal_w2006 hal_w2007
        hal_oamdma hal_swapprg""".split()),
]

LABEL = re.compile(r"^([0-9A-F]{6})r\s+\d+\s+(?:[0-9A-F ]*?)\s{2,}"
                   r"([A-Za-z_][A-Za-z0-9_]*):")


def listing(path, tmp):
    out = os.path.join(tmp, os.path.basename(path) + ".lst")
    subprocess.run(["ca65", "--cpu", "65816", "-I", "../gen", "-l", out,
                    os.path.basename(path), "-o", os.path.join(tmp, "x.o")],
                   cwd=os.path.join(ROOT, "src"), check=True)
    return sorted((int(m.group(1), 16), m.group(2))
                  for m in map(LABEL.match, open(out, encoding="latin-1")) if m)


def main():
    #  The segment base, from a symbol the link map does export.  Hard-coding
    #  $8000 would be right today and wrong the moment a segment moves.
    sym = {}
    for line in open(os.path.join(ROOT, "out", "labels.txt")):
        p = line.split()
        if len(p) >= 3 and p[0] == "al":
            sym[p[2].lstrip(".")] = int(p[1], 16)

    with tempfile.TemporaryDirectory() as tmp:
        for name, bank, want in FILES:
            labels = listing(os.path.join(ROOT, "src", name), tmp)
            anchor = next(n for a, n in labels if n in sym)
            base = sym[anchor] - dict((n, a) for a, n in labels)[anchor]
            for i, (addr, label) in enumerate(labels):
                if label not in want:
                    continue
                end = labels[i + 1][0] if i + 1 < len(labels) else addr + 0x400
                print("%06X %06X %s" % (bank << 16 | (addr + base),
                                        bank << 16 | (end + base), label))


if __name__ == "__main__":
    main()
