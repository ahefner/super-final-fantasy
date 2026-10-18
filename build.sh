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
python3 tools/genspellnames.py
python3 tools/genbeam.py
python3 tools/gencrawl.py
python3 tools/genroll.py
python3 tools/gentactics.py
python3 tools/genitemmagic.py
python3 tools/genowedits.py
python3 tools/genows.py
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

#  FFDEBUG=...,owedits turns every overworld map edit on, whatever the save
#  says -- all fourteen of FFR's, the three no Map edits mode offers among
#  them -- so a save that has the airship can fly round the edited map and
#  open the minimap.  Only the map: a save started without Bridge to Lefein
#  keeps its BRIDGE where it was built.
case "$FFDEBUG" in
  *owedits*) CA65EXTRA="$CA65EXTRA -DOWEDITS_FORCE" ;;
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

#  FFDEBUG=vanilla|improved|super forces that option preset on every boot,
#  ignoring whatever is in SRAM.  Without it there is no way to try a preset
#  other than the one already written to the cartridge, because a valid block
#  is deliberately left alone.  Remove once the options menu can do this.
case "$FFDEBUG" in
  *vanilla*)  CA65EXTRA="$CA65EXTRA -DOPT_FORCE=0" ;;
  *improved*) CA65EXTRA="$CA65EXTRA -DOPT_FORCE=1" ;;
  *super*)    CA65EXTRA="$CA65EXTRA -DOPT_FORCE=2" ;;
esac

#  FFSEED=xxxxxxxx (eight hex digits) gives every new game that seed, so a
#  world can be reproduced on a console without a battery file.  The settings
#  still come from the settings screen.
if [ -n "$FFSEED" ]; then
  CA65EXTRA="$CA65EXTRA -DFORCE_SEED=\$$FFSEED"
fi

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

( cd src && $CA65 -I ../gen optbank.asm -o ../out/bank_OPT.o
           $CA65 -I ../gen optmenu.asm -o ../out/bank_OPTMENU.o
           $CA65 -I ../gen optdata.asm -o ../out/bank_OPTDATA.o
           $CA65 -I ../gen optshop.asm -o ../out/bank_OPTSHOP.o
           $CA65 -I ../gen nones.asm -o ../out/bank_NONES.o
           $CA65 -I ../gen credits.asm -o ../out/bank_CREDITS.o
           $CA65 -I ../gen rando.asm -o ../out/bank_RANDO.o
           $CA65 opttext.asm -o ../out/bank_OPTTEXT.o
           $CA65 logicdata.asm -o ../out/bank_LOGIC.o
           $CA65 -I ../gen world.asm -o ../out/bank_WORLD.o
           $CA65 -I ../gen roll.asm -o ../out/bank_ROLL.o
           $CA65 -I ../gen tactics.asm -o ../out/bank_TACTICS.o
           $CA65 -I ../gen owscreen.asm -o ../out/bank_OWS.o
           $CA65 hal.asm    -o ../out/hal.o
           $CA65 header.asm -o ../out/header.o )

ld65 -C snes.cfg -o /dev/null -Ln out/labels.txt \
    out/hal.o out/header.o \
    out/bank_01.o out/bank_09.o out/bank_0B.o out/bank_0C.o \
    out/bank_0D.o out/bank_0E.o out/bank_0F.o out/bank_OPT.o out/bank_OPTMENU.o \
    out/bank_OPTDATA.o out/bank_OPTSHOP.o out/bank_NONES.o out/bank_CREDITS.o out/bank_RANDO.o \
    out/bank_OPTTEXT.o out/bank_LOGIC.o out/bank_WORLD.o out/bank_ROLL.o \
    out/bank_TACTICS.o out/bank_OWS.o

#  HAL_VARS is hand-allocated, so two names can land on one byte and assemble
#  without complaint.  Two branches each taking the same free offset is the
#  likely case, and the merge of two disjoint hunks is clean, so check it here
#  rather than hope someone reads the whole map.
python3 tools/check_halvars.py || exit 1

#  Code in the options bank reaches the fixed bank with a plain JSR, which is
#  safe until the routine it calls swaps banks.  That is a freeze on hardware
#  and looks like an ordinary call in the source, so check it every build.
python3 tools/check_bankswap.py || exit 1

#  The fixed bank's '_L' tables are runs of three-byte JMPs that other banks
#  index by arithmetic.  ca65 resolves them by name, so a routine tucked into
#  one assembles cleanly and silently shifts every entry after it.  That cost a
#  long debugging session; check the spacing instead.
python3 tools/check_tables.py out/labels.txt || exit 1

python3 tools/genchest.py
python3 tools/mkrom.py
