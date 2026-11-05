#!/usr/bin/env python3
"""
genscream.py -- the Exploding Dwarf's scream, as the SPC700 plays it.

The user's recording, sound/scream.raw: 8-bit signed, no header, exported at
11kHz (user, 2026-11-04: "downsample this slightly to reduce the size, and
also lower the pitch during playback to stretch it out slightly").

    sound/scream.raw    11025Hz, 1.85 s
      -> DC out, resampled to RATE, the last FADE seconds faded
      -> BRR, every block's filter and shift the best of the sixteen-odd
         that decode it, an extra silent block last with END and no LOOP --
         the DSP silences a voice the moment that block's header is current,
         so the block before it is the last heard
      -> out/fundata.bin: the sample as hal_spcplay wants it in the SPC700's
         RAM -- its pitch, its two volumes, then the BRR -- laid into the
         low half of Taverns' image bank by mkrom.py (FUNDATAFAR)
      -> gen/scream.inc: its length, and where it sits there

Under 1% of the recording's energy is above 4kHz (-24dB, measured), so 8kHz
loses next to nothing and saves 27%.  Played at STRETCH of its rate it runs
longer and lower, as asked: 10%, 2.06 s and under two semitones.
"""
import math, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "sound", "scream.raw")
OUT = os.path.join(ROOT, "out", "fundata.bin")
INC = os.path.join(ROOT, "gen", "scream.inc")

SRC_RATE = 11025
RATE = 8000            # stored
STRETCH = 0.90         # played at this share of RATE: longer, and lower
CUTOFF = 3700          # Hz, the resampler's low-pass: under RATE / 2
TAPS = 24              # the resampler's half-width, in source samples
FADE = 0.060           # seconds faded out at the end; the export stops on a
                       #   level a tenth of full, a click if cut
PEAK = 22600           # the BRR's loudest decoded sample, of 32768.  Not near
                       #   the rail: the DSP's interpolator sums three taps
                       #   before it truncates, and wraps (genspc.py, BRR_SCALE).
                       #   16000 at first; 3dB up (user, 2026-11-04: "increase
                       #   the volume of the scream by 3 dB"), here because
                       #   VOLUME would have needed 136
VOLUME = 96            # the voice's VOL, each side, of 127: the scream's peak
                       #   at 16950, a full NES pulse's at 6720

#  The DSP's pitch register: 4096 plays a sample at 32kHz, one source sample
#  a DSP sample.
PITCH = round(4096 * RATE * STRETCH / 32000)


def source():
    raw = open(SRC, "rb").read()
    x = [b - 256 if b > 127 else b for b in raw]
    mean = sum(x) / len(x)
    return [v - mean for v in x]


def resample(x):
    """A windowed-sinc low-pass and resample, SRC_RATE -> RATE."""
    step = SRC_RATE / RATE
    fc = CUTOFF / SRC_RATE                      # cycles per source sample
    n = int(len(x) / step)
    out = []
    for j in range(n):
        c = j * step
        lo, hi = int(math.floor(c)) - TAPS + 1, int(math.floor(c)) + TAPS
        acc = wsum = 0.0
        for i in range(max(lo, 0), min(hi, len(x) - 1) + 1):
            t = i - c
            u = t / TAPS
            if abs(u) >= 1:
                continue
            w = 0.42 + 0.5 * math.cos(math.pi * u) + 0.08 * math.cos(2 * math.pi * u)
            h = 2 * fc * (math.sin(2 * math.pi * fc * t) / (2 * math.pi * fc * t) if t else 1.0)
            acc += x[i] * h * w
            wsum += h * w
        out.append(acc / wsum if wsum else 0.0)
    return out


def shaped(y):
    """Faded out at the end, and scaled to PEAK."""
    nf = int(FADE * RATE)
    y = list(y)
    for k in range(nf):
        y[len(y) - nf + k] *= 0.5 + 0.5 * math.cos(math.pi * (k + 1) / nf)
    peak = max(abs(v) for v in y)
    return [round(v * PEAK / peak) for v in y]


# --- BRR ---------------------------------------------------------------------
#  The S-DSP's decode, as blargg's SPC_DSP has it.  p1 and p2 are the last two
#  samples as decoded (doubled, sixteen bits); the result is the next.
def brr_decode(nib, shift, filt, p1, p2):
    s = (nib << shift) >> 1
    if filt == 1:
        s += (p1 >> 1) + ((-p1) >> 5)
    elif filt >= 2:
        q2 = p2 >> 1
        s += p1 - q2
        if filt == 2:
            s += (q2 >> 4) + ((p1 * -3) >> 6)
        else:
            s += ((p1 * -13) >> 7) + ((q2 * 3) >> 4)
    s = max(-32768, min(32767, s))
    return ((s * 2 + 32768) & 0xFFFF) - 32768


def _try(block, shift, filt, p1, p2):
    nibs, err = [], 0
    for t in block:
        q = brr_decode(0, shift, filt, p1, p2)  # the prediction alone
        n = max(-8, min(7, round((t - q) / (1 << shift)))) if shift else max(-8, min(7, t - q))
        best = None
        for m in (n - 1, n, n + 1):
            if -8 <= m <= 7:
                v = brr_decode(m, shift, filt, p1, p2)
                if best is None or abs(v - t) < abs(best[1] - t):
                    best = (m, v)
        m, v = best
        nibs.append(m)
        err += (v - t) ** 2
        p1, p2 = v, p1
    return err, nibs, p1, p2


def brr(samples):
    """BRR blocks for `samples` (whole blocks of 16), then a silent END one.
    The first block filter 0: a key-on keeps whatever history the voice had."""
    out = bytearray()
    p1 = p2 = 0
    for b in range(0, len(samples), 16):
        block = samples[b:b + 16]
        best = None
        for filt in ((0,) if b == 0 else (0, 1, 2, 3)):
            for shift in range(13):
                r = _try(block, shift, filt, p1, p2)
                if best is None or r[0] < best[0][0]:
                    best = (r, shift, filt)
        (err, nibs, p1, p2), shift, filt = best
        out.append(shift << 4 | filt << 2)
        for i in range(0, 16, 2):
            out.append((nibs[i] & 15) << 4 | (nibs[i + 1] & 15))
    out += bytes([0x01]) + bytes(8)             # END, no LOOP: silence
    return bytes(out)


def build():
    """(the samples, as stored, padded to whole blocks; the BRR)"""
    y = shaped(resample(source()))
    y += [0] * (-len(y) % 16)
    return y, brr(y)


def main():
    y, data = build()
    blob = bytes([PITCH & 0xFF, PITCH >> 8, VOLUME, VOLUME]) + data
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    os.makedirs(os.path.dirname(INC), exist_ok=True)
    open(OUT, "wb").write(blob)
    with open(INC, "w") as f:
        f.write("; GENERATED by tools/genscream.py -- do not edit.\n")
        f.write("SCREAM_AT     = $0000      ; in out/fundata.bin, so at FUNDATAFAR\n")
        f.write("SCREAM_LEN    = %d       ; pitch, volumes, BRR\n" % len(blob))
        f.write("SCREAM_PITCH  = $%04X\n" % PITCH)
    print("scream: %d samples at %dHz, %.2f s played, %d bytes -> %s"
          % (len(y), RATE, len(y) / (RATE * STRETCH), len(blob), OUT))


if __name__ == "__main__":
    main()
