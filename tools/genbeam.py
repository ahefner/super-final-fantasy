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
import math, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(os.path.dirname(HERE), "out")

VISIBLE   = 224
CENTRE    = 119          # ALTARCENTRE
LTRIM     = 1            # ALTARLTRIM: a pixel off the left, to sit on a half pixel
APEX      = 1            # ALTARAPEX
SHIFT     = 28           # ALTARSHIFT
SNAP      = 6            # ALTARSNAP


HOLD   = 20              # frames held at full extension, for the drama

#  The water orb ripples.  The offset is a travelling wave: a sine in the
#  distance above the apex, its phase advancing with the frame, so the crests
#  run up the beam rather than the whole thing leaning together.  Scaled by
#  that same distance, so the tip stays planted and the wide end moves most,
#  and faded to nothing across the last WAVE_FADE frames -- otherwise the beam
#  would still be wriggling when it is meant to have closed to a column.
WAVE_PERIOD  = 30        # frames for one crest to travel one cycle
WAVE_AMP     = 16        # pixels of displacement at the widest point
WAVE_FADE    = 0         # frames over which it settles straight; 0 = never

#  One entry per variant, indexed by the HAL through BEAMOFF0..2.
#
#    wave        spatial period in pixels, or None for a beam that stays put
#    shrink_to   the width the contraction ends on; 2 closes to a column
#    end_bottom  where the band's bottom edge finishes, BOTTOM for "stays under
#                the player".  Walking it upward is how the original retracted,
#                which read as the beam scrolling off the top of the screen --
#                wrong for an orb going out, but exactly right for air, where
#                the wisp is supposed to escape.
#    max_width   the width the beam grows to, in place of the full 110.  It
#                scales the whole growth rather than clipping it, so the cone
#                still opens smoothly, just to a narrower maximum.
#    hold        frames spent at full extension before that starts.  Spending
#                fewer buys frames for the departure, which is the only way to
#                make it drift rather than race: the budget is fixed.
VARIANTS = (
    dict(wave=None),                                    # earth and fire
    dict(wave=55),                                      # water
    dict(wave=32, shrink_to=12, end_bottom=56, hold=6, max_width=70),  # air
)
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


def frames(shrink_to=2, end_bottom=BOTTOM, hold=HOLD, max_width=None):
    """(top, height, width) per frame.

    While the beam grows, its bottom is pinned under the player and height is
    simply BOTTOM minus top, which reproduces the NES's two-lines-a-frame.  The
    budget is then spent grow / hold / shrink rather than the NES's grow /
    shrink: holding at full extension reads as the orb gathering itself, and
    the contraction has fewer frames to cover the same ground so it goes out
    faster.  The whole thing still takes exactly as long as before.

    What the contraction does is the variant's to choose.  Closing the width to
    a column leaves the beam where it stood; walking the bottom edge up instead
    carries it off the top of the screen.
    """
    total = game_frame_count()

    grow = [(tmp, 140 - tmp) for tmp in range(138, 28, -2)]
    held = [grow[-1]] * hold
    n = total - len(grow) - hold
    if n < 1:
        sys.exit("a hold of %d leaves no frames to contract in" % hold)
    full = grow[-1][1]
    cap = max_width or full

    out = []
    for tmp, lit in grow + held:
        top = max(0, tmp - SHIFT)
        if top < SNAP:
            top = 0
        out.append((top, BOTTOM - top, lit * cap // full))

    top = out[-1][0]
    for i in range(1, n + 1):
        w = cap - (cap - shrink_to) * i // n
        bot = BOTTOM - (BOTTOM - end_bottom) * i // n
        out.append((top, max(0, bot - top), w))
    return out


def profile(height, width):
    """Half-width for each scanline of the band, widest at the top.

    The apex is the last entry, so a beam whose bottom edge is walking upward
    keeps its point: the taper is measured against the band it actually has,
    not against the one it had at full extension.
    """
    if height <= 0:
        return []
    span = width // 2                        # total narrowing, top to apex
    return [APEX + (span * (height - 1 - i)) // max(1, height - 1)
            for i in range(height)]


def sway(frame, total, d, dmax, yscreen, yperiod):
    """Horizontal offset for one scanline of the band, on frame `frame`.

    Two different measures of position, deliberately.  The phase is taken from
    the screen scanline, so the crests keep their own speed no matter what the
    band is doing; the amplitude is taken from the distance above the apex, so
    the tip stays planted and the wide end moves most.

    Keying the phase to the apex as well looked right until a variant started
    moving its apex: air's band retreats upward, so the pattern rode up with it
    on top of its own travel and the ripple appeared to accelerate through the
    contraction.
    """
    if dmax <= 0:
        return 0
    amp = WAVE_AMP
    if WAVE_FADE:
        left = total - 1 - frame
        if left < WAVE_FADE:
            amp = WAVE_AMP * left / WAVE_FADE
    phase = 2.0 * math.pi * (yscreen / yperiod + frame / WAVE_PERIOD)
    return int(round(amp * (d / dmax) * math.sin(phase)))


def table(top, height, width, frame=0, total=1, wave=None):
    t = bytearray()

    def skip(n):                              # empty window: left > right
        while n > 0:
            k = min(n, 127)
            t.extend((k, 255, 0))
            n -= k

    skip(top)
    hw = profile(height, width)
    i = 0
    while i < len(hw):
        k = min(len(hw) - i, 127)
        t.append(0x80 | k)                    # repeat: a pair for every line
        for j in range(i, i + k):
            c = CENTRE
            if wave:
                c += sway(frame, total, height - 1 - j, max(1, height - 1),
                          top + j, wave)
            left = max(0, c - hw[j]) + LTRIM
            right = min(255, max(0, c + hw[j]))
            if left > right:                  # degenerate: keep it a column
                left = right
            t.extend((left, right))
        i += k
    skip(max(0, VISIBLE - (top + height)))
    t.append(0)                               # a zero line count ends it
    return bytes(t)


def main():
    fs = frames()
    n = len(fs)
    sets = []
    for spec in VARIANTS:
        vf = frames(spec.get("shrink_to", 2), spec.get("end_bottom", BOTTOM),
                    spec.get("hold", HOLD), spec.get("max_width"))
        sets.append([table(*f, frame=i, total=n, wave=spec.get("wave"))
                     for i, f in enumerate(vf)])

    #  Fixed offsets for the index arrays, so the HAL reaches any of them with
    #  one long-indexed load and an eight-bit frame index.
    OFFS = (0x0004, 0x0100, 0x0200)
    DATA = 0x0300
    if len(sets) > len(OFFS):
        sys.exit("%d variants, but only %d index slots" % (len(sets), len(OFFS)))
    for i, o in enumerate(OFFS[:len(sets)]):
        end = (OFFS + (DATA,))[i + 1]
        if o + 2 * n > end:
            sys.exit("%d frames overrun index slot %d" % (n, i))

    blob = bytearray(DATA)
    blob[0:2] = struct.pack("<H", n)
    pos = DATA
    for v, tables in enumerate(sets):
        base = OFFS[v]
        for i, tb in enumerate(tables):
            blob[base + 2 * i:base + 2 * i + 2] = struct.pack("<H", pos)
            blob += tb
            pos += len(tb)
    if pos > 0x10000:
        sys.exit("beam tables total %d bytes, which will not fit one bank" % pos)
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "beam.bin"), "wb").write(blob)
    print("beam: %d frames x %d variants, %d bytes" % (n, len(sets), len(blob)))


if __name__ == "__main__":
    main()
