#!/usr/bin/env python3
"""
genbeam.py -- pre-build the altar beam's HDMA window tables, one per frame.

The beam is a cone whose edges move every scanline.  Computing that in vblank
cost more than vblank had: per-scanline it pushed the flush past the end of the
interval and put a black band across the top of the picture, and the cheaper
run-length version bought the time back only by quantising the taper into
visible stairsteps.

Neither trade is necessary.  The animation is a fixed, input-independent
sequence of about 110 frames, so every table it will ever need can be built
here and read straight out of ROM by HDMA -- which costs the CPU nothing at
all, and lets the edges move a pixel at a time.  It also means the shape is
data: a wavy beam, or a different profile per orb, is a change to this file
rather than to the HAL.

Layout of out/beam.bin, which mkrom.py places at its own ROM bank:

    $0000  frame count, 16-bit
    $0002  one 16-bit offset per frame, to that frame's table
    ....   the tables themselves

A table is an ordinary HDMA table over WH0/WH1 (transfer mode 1, two bytes to
two registers).  Lines outside the beam get an empty window -- left 255, right
0 -- which switches colour maths off there by itself, so the beam needs no
second channel over CGADSUB the way the first version did.
"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(os.path.dirname(HERE), "out")

VISIBLE   = 224
CENTRE    = 119          # ALTARCENTRE
LTRIM     = 1            # ALTARLTRIM: a pixel off the left, to sit on a half pixel
APEX      = 1            # ALTARAPEX
SHIFT     = 28           # ALTARSHIFT
SNAP      = 6            # ALTARSNAP


HOLD   = 20              # frames held at full extension, for the drama
BOTTOM = 112             # the band's bottom edge: 138 - SHIFT + 2, held there
                         # by the NES through the whole expansion


def game_frame_count():
    """How many times DoAltarEffect's loop runs, and so how many frames we get.

    The loop is what paces the effect -- AltarFrame waits for vblank once an
    iteration -- and it also owns the screen shake and the sound, so its timing
    is left alone.  What each of those frames looks like is entirely up to us.
    """
    tmp, lit, phase, n = 138, 2, 0, 0
    while True:
        n += 1
        if phase == 0:
            lit += 2
            tmp -= 2
            if tmp < 32:
                phase = 1
        else:
            lit -= 2
            if lit < 2:
                break
    return n


def frames():
    """(top, height, width) per frame.

    The band's bottom is pinned under the player throughout, so height is
    always BOTTOM minus top: while the beam grows that reproduces the NES's
    own two-lines-a-frame, and once it stops growing the band simply stays
    full while the width comes down instead.

    The budget is spent grow / hold / shrink rather than the NES's grow /
    shrink.  Holding at full extension reads as the orb gathering itself; the
    shrink then has fewer frames to cover the same ground, so it goes out
    faster, and the whole thing still takes exactly as long as before.
    """
    total = game_frame_count()

    grow = [(tmp, 140 - tmp) for tmp in range(138, 28, -2)]
    hold = [grow[-1]] * HOLD
    n = total - len(grow) - HOLD
    if n < 1:
        sys.exit("HOLD of %d leaves no frames to contract in" % HOLD)
    full = grow[-1][1]
    shrink = [(grow[-1][0], full - (full - 2) * i // n) for i in range(1, n + 1)]

    out = []
    for tmp, lit in grow + hold + shrink:
        top = max(0, tmp - SHIFT)
        if top < SNAP:
            top = 0
        out.append((top, BOTTOM - top, lit))
    return out


def profile(top, height, width):
    """Half-width for each scanline of the band, apex at the bottom."""
    if height <= 0:
        return []
    span = APEX + width // 2 - APEX          # total narrowing, top to apex
    return [APEX + (span * (height - 1 - i)) // max(1, height - 1)
            for i in range(height)]


def table(top, height, width):
    t = bytearray()

    def skip(n):                              # empty window: left > right
        while n > 0:
            k = min(n, 127)
            t.extend((k, 255, 0))
            n -= k

    skip(top)
    hw = profile(top, height, width)
    i = 0
    while i < len(hw):
        k = min(len(hw) - i, 127)
        t.append(0x80 | k)                    # repeat: a pair for every line
        for j in range(i, i + k):
            left = max(0, CENTRE - hw[j]) + LTRIM
            right = min(255, CENTRE + hw[j])
            if left > right:                  # degenerate: keep it a column
                left = right
            t.extend((left, right))
        i += k
    skip(max(0, VISIBLE - (top + height)))
    t.append(0)                               # a zero line count ends it
    return bytes(t)


def main():
    fs = frames()
    tables = [table(*f) for f in fs]
    head = 2 + 2 * len(fs)
    offs, pos = [], head
    for tb in tables:
        offs.append(pos)
        pos += len(tb)
    if pos > 0x10000:
        sys.exit("beam tables total %d bytes, which will not fit one bank" % pos)
    blob = bytearray(struct.pack("<H", len(fs)))
    for o in offs:
        blob += struct.pack("<H", o)
    for tb in tables:
        blob += tb
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "beam.bin"), "wb").write(blob)
    print("beam: %d frames, %d bytes of HDMA tables (%d total)"
          % (len(fs), pos - head, len(blob)))


if __name__ == "__main__":
    main()
