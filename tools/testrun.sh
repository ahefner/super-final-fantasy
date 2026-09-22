#!/bin/bash
#  testrun.sh -- drive the current build under ares against a COPY of the save.
#
#  ares writes SRAM back on exit, and drive.py kills it, so pointing a test run
#  at snes/FinalFantasy.srm risks the file the user plays on.  That is not
#  hypothetical: a run here destroyed a save that had been made a few minutes
#  earlier, and the "backup" taken beforehand raced the write and preserved the
#  older content instead.  So the ROM and the save are copied to /tmp and ares
#  is pointed there.  Nothing in snes/ is written.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cp "$HERE/SuperFinalFantasy.sfc" /tmp/fftest.sfc
#  ares names its battery file .ram, not .srm.  A stale .srm sat beside it and
#  was mistaken for the save once, which wasted a real one.
#
#  SAVE=<suffix> picks one of the named save points kept beside the ROM --
#  FinalFantasy.ram.midtown for the screen transitions, .pravoka-walk to walk
#  right into a battle, .pravoka to walk down and board the ship.  Those predate
#  the rename and keep their names; without SAVE the current cartridge RAM,
#  SuperFinalFantasy.ram, is used.  Either way the copy is what ares gets.
#
#  SAVE=none starts from an empty cartridge, which is what a test of the
#  options menu wants: opt_init then writes a fresh block and the run does not
#  depend on whatever was last saved.
if [ "$SAVE" = none ]; then
  rm -f /tmp/fftest.ram /tmp/fftest.srm
elif [ -n "$SAVE" ]; then
  if [ ! -f "$HERE/FinalFantasy.ram.$SAVE" ]; then
    echo "testrun.sh: no save named FinalFantasy.ram.$SAVE" >&2; exit 1
  fi
  cp "$HERE/FinalFantasy.ram.$SAVE" /tmp/fftest.ram
else
  rm -f /tmp/fftest.ram /tmp/fftest.srm
  for ext in ram srm; do
    if [ -f "$HERE/SuperFinalFantasy.$ext" ]; then cp "$HERE/SuperFinalFantasy.$ext" "/tmp/fftest.$ext"; fi
  done
fi
export ROM=/tmp/fftest.sfc
export ARES_BIN="${ARES_BIN:-/Users/hefner/stuff/FFR/ares/build_macos/desktop-ui/RelWithDebInfo/ares.app/Contents/MacOS/ares}"
exec python3 "$HERE/tools/drive.py" "$@"
