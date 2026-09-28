#!/bin/sh
#  Build the SNES port.  Run from this directory.
set -e
cd "$(dirname "$0")"
mkdir -p out gen

#  FFDEBUG=...,apustat paints three bars across the top of the screen showing
#  whether the game, the HAL and the DSP each believe the triangle is sounding.
#  It needs both halves: the ca65 define for the bars, and FFAPUSTAT so the SPC
#  program reports the DSP's ENVX back through the acknowledge port.  This sits
#  above the generators rather than with the other FFDEBUG cases below, because
#  genspc.py reads FFAPUSTAT and runs before them.
case "$FFDEBUG" in
  *apustat*) CA65EXTRA="$CA65EXTRA -DAPUSTAT"; export FFAPUSTAT=1 ;;
esac

python3 tools/genpal.py
python3 tools/genapu.py
python3 tools/genspc.py
python3 tools/genbeam.py
python3 tools/convert.py

#  FFDEBUG=...,dark blackens the town's grass so the altar beam can be judged
#  against a dungeon-like background.  That is a HAL change rather than a
#  source patch, so it rides on a ca65 define rather than the patch-name gate.
case "$FFDEBUG" in
  *dark*) CA65EXTRA="$CA65EXTRA -DFFDARK" ;;
esac
case "$FFDEBUG" in
  *tone*) CA65EXTRA="$CA65EXTRA -DAUDIOTEST" ;;
esac

#  FFDEBUG=...,trisweep replaces the tone pattern with a sweep of the triangle
#  through every pitch it can be given, so a capture can say which ones click.
case "$FFDEBUG" in
  *trisweep*) CA65EXTRA="$CA65EXTRA -DAUDIOTEST -DTRISWEEP" ;;
esac

#  FFDEBUG=...,trionly silences the pulses and the noise so the triangle plays
#  alone.  The directory slots are per-voice and do not overlap, so if the
#  cutout survives with nothing else sounding it is the triangle's own
#  repoint racing its own loop wrap; if it stops, the corruption comes from
#  another voice or from bus contention.
#  FFDEBUG=...,trionly / pulse1 / pulse2 / noiseonly silences every channel but
#  the named one, so an artifact can be attributed to a voice without guessing.
case "$FFDEBUG" in
  *trionly*)   CA65EXTRA="$CA65EXTRA -DSOLOMASK=\$04" ;;
  *pulse1*)    CA65EXTRA="$CA65EXTRA -DSOLOMASK=\$01" ;;
  *pulse2*)    CA65EXTRA="$CA65EXTRA -DSOLOMASK=\$02" ;;
  *noiseonly*) CA65EXTRA="$CA65EXTRA -DSOLOMASK=\$08" ;;
esac

CA65="ca65 --cpu 65816 $CA65EXTRA"

#  The disassembly writes negative immediates (LDA #-1, AND #-33), which ca65
#  rejects unless told to truncate them to a byte.  The generated banks need
#  that leniency; nothing else does.
#
#  Keep it off everywhere else, because the same leniency silently truncates a
#  16-bit immediate written where the assembler happens to think A is 8-bit --
#  which is how "and #$FFFE" in flush_chr became a two-byte instruction that
#  ate the following opcode, and cost a long hunt.  Assembling the HAL strictly
#  turns that class of mistake into a build error at the offending line.
CA65_GEN="$CA65 --feature force_range"

# The generated banks live in gen/, which also carries the 'bin' symlink the
# original .incbin paths need; ca65 resolves those against the current
# directory, so assemble from in there.
( cd gen && for b in 01 09 0B 0C 0D 0E 0F; do
    $CA65_GEN -I ../src bank_$b.asm -o ../out/bank_$b.o
  done )

( cd src && $CA65 hal.asm    -o ../out/hal.o
           $CA65 header.asm -o ../out/header.o )

ld65 -C snes.cfg -o /dev/null \
    out/hal.o out/header.o \
    out/bank_01.o out/bank_09.o out/bank_0B.o out/bank_0C.o \
    out/bank_0D.o out/bank_0E.o out/bank_0F.o

python3 tools/mkrom.py
