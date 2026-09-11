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
cp "$HERE/FinalFantasy.sfc" /tmp/fftest.sfc
#  ares names its battery file .ram, not .srm.  A stale FinalFantasy.srm sat
#  beside it and was mistaken for the save once, which wasted a real one.
for ext in ram srm; do
  if [ -f "$HERE/FinalFantasy.$ext" ]; then cp "$HERE/FinalFantasy.$ext" "/tmp/fftest.$ext"; fi
done
export ROM=/tmp/fftest.sfc
export ARES_BIN="${ARES_BIN:-/Users/hefner/stuff/FFR/ares/build_macos/desktop-ui/RelWithDebInfo/ares.app/Contents/MacOS/ares}"
exec python3 "$HERE/tools/drive.py" "$@"
