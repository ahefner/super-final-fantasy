#!/bin/sh
#  Build and run under ares, then screenshot it.
#
#  Use ares rather than Snes9x for this: it takes the ROM on its command line,
#  so a scripted run definitely loads the game.  Opening Snes9x with `open -a`
#  launches the app but silently leaves it with no ROM, which looks exactly
#  like a game that booted to a black screen.
#
#  usage: tools/run.sh [seconds] [-D DIAG_STOP=n ...]
set -e
cd "$(dirname "$0")/.."
SECS=${1:-6}; shift 2>/dev/null || true
CA65EXTRA="$*" ./build.sh >/dev/null
killall ares Snes9x 2>/dev/null || true
sleep 1
/Applications/ares.app/Contents/MacOS/ares --system "Super Famicom" --no-file-prompt \
    "$PWD/FinalFantasy.sfc" >/dev/null 2>&1 &
sleep "$SECS"
osascript -e 'tell application "ares" to activate' >/dev/null 2>&1
sleep 1
OUT="${SNESSHOT:-/tmp/snesshot.png}"
screencapture -x "$OUT.full.png"
#  Crop to the emulator's picture.  ares centres its window, so these bounds
#  are stable; capturing the whole 2880x1800 desktop every iteration is a lot
#  of pixels for a 256x224 console.
sips -c 1130 1390 --cropOffset 330 710 "$OUT.full.png" --out "$OUT" >/dev/null
echo "$OUT"
