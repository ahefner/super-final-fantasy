#!/usr/bin/env python3
"""
genapu.py -- generate the NES-timer -> S-DSP-pitch tables for the audio port.

The NES sets a channel's frequency with an 11-bit timer divider; the SNES sets
a voice's frequency with a 14-bit pitch register that scales a sample's
playback rate.  Both are fixed functions of hardware constants, so the whole
mapping is a table computed once here rather than arithmetic on a CPU that has
no divide instruction.

Model
-----
Every voice plays a single-cycle waveform of PERIOD samples on a loop (see
PULSE_PERIOD and TRI_PERIOD below; the pulses and the triangle differ).
The S-DSP plays it back at   32000 * (pitch / 4096)   samples/sec, so the tone
that comes out has frequency

        f_out = 32000 * (pitch/4096) / PERIOD

We want f_out to equal the NES channel's frequency, so

        pitch = f_nes * PERIOD * 4096 / 32000

NES frequencies (NTSC, CPU = 1789773 Hz):
        pulse/noise:  f = CPU / (16 * (t + 1))
        triangle:     f = CPU / (32 * (t + 1))     (an octave lower for the same t)

t is the 11-bit timer, 0..2047.  t = 0 is never a real note here (the driver
parks silent channels), and the smallest musical timers would demand a pitch
past the 14-bit ceiling, so the table clamps -- those slots are never read.
"""
import os

CPU        = 1789773.0        # NTSC 2A03 CPU clock
DSP_RATE   = 32000.0          # S-DSP output sample rate
PITCH_UNIT = 4096.0           # DSP pitch of 4096 == play sample at native rate
PITCH_MAX  = 0x3FFF           # 14-bit pitch register
#  Cycle lengths available, and the playback rate to aim for.  These must
#  match SIZES in genspc.py.
#
#  The DSP raises a note by playing a waveform faster, and that is bounded at
#  both ends: the pitch register stops at $3FFF (four times native rate), and
#  an N-sample cycle holds only N/2 harmonics however slowly it is played.  One
#  fixed length is therefore wrong at both ends at once.  A 64-sample cycle
#  gave a 55Hz bass note 32 harmonics reaching only 1.7kHz -- audibly dull --
#  while the menu chirp at 3.4kHz wanted a pitch of 27764, which does not
#  exist, so it came out clamped nearly an octave flat.
#
#  Instead pick, per timer value, the longest cycle whose playback rate stays
#  at or under TARGET_RATE.  Since pitch = rate * 4096 / 32000, capping the
#  rate caps the pitch: at 64000 no entry can exceed 8192, half the register's
#  range, so nothing clamps anywhere a real note or effect can reach.
#
#  TARGET_RATE is the one dial worth turning here, and it trades brightness
#  against aliasing.  Low, at 32000, the waveform's own Nyquist lands exactly
#  on the output's and nothing folds -- but the DSP's 4-tap Gaussian smears
#  each edge across four source samples, and at that rate four source samples
#  is a long time, so the tone is soft.  High, at the 128000 the pitch register
#  can just reach, the smear covers a quarter as long and the edges stay sharp,
#  at the cost of folding the harmonics above the 16kHz output Nyquist back
#  down.  For a square those fall off as 1/n, so they fold in 30dB or more
#  below the fundamental.
#
#  It is set high deliberately.  The build before this one used a fixed
#  64-sample cycle, which happened to run the top musical notes at 117000 --
#  heavily oversampled, and bright -- while starving a 55Hz bass note at 3500.
#  An earlier attempt here capped the rate at 64000, which brightened the bass
#  but pulled those high notes down to 58000 and came out darker overall.  At
#  128000 no note is played slower than the fixed-64 build played it, and the
#  low end gains the most.
SIZES       = [8, 16, 32, 64, 128, 256, 512, 1024]
TARGET_RATE = 127000.0     # a hair under 128000, so rounding cannot pass $3FFF
#  FFRATE overrides it for listening tests.  Lower is darker and aliases less, and
#  below 64000 it leaves a whole octave of pitch headroom for upward hysteresis.
TARGET_RATE = float(os.environ.get("FFRATE", TARGET_RATE))

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(os.path.dirname(HERE), "src", "apupitch.inc")


def size_for(freq):
    """The longest cycle whose playback rate stays at or under TARGET_RATE."""
    best = SIZES[0]
    for p in SIZES:
        if freq * p <= TARGET_RATE:
            best = p
    return best


def pitch_for(freq, period):
    p = round(freq * period * PITCH_UNIT / DSP_RATE)
    return max(0, min(PITCH_MAX, p))


def table(divisor):
    """Per timer value: the pitch, and the index of the cycle length it is
    computed for.  The size index is returned pre-shifted into the position it
    occupies in the sequence byte, so the caller only has to OR it in."""
    pitches, sizes = [], []
    for t in range(2048):
        if t == 0:                       # never a real note: the driver parks
            pitches.append(0); sizes.append(0)
            continue
        f = CPU / (divisor * (t + 1))
        p = size_for(f)
        pitches.append(pitch_for(f, p))
        sizes.append(SIZES.index(p) << 3)
    return pitches, sizes


def emit(f, name, vals):
    f.write("\n%s:\n" % name)
    for i in range(0, len(vals), 8):
        row = vals[i:i+8]
        f.write("    .word " + ",".join("$%04X" % v for v in row) +
                ("    ; t=%d\n" % i))


# S-DSP global noise clock, rate 0..31, in Hz (hardware table).
DSP_NOISE = [0,16,21,25,31,42,50,63,83,100,125,167,200,250,333,400,
             500,667,800,1000,1300,1600,2000,2700,3200,4000,5300,6400,
             8000,10700,16000,32000]
#  NES noise: the LFSR is clocked at CPU / period, with this period table on
#  NTSC.  That is the rate to match, because the SNES's noise generator is
#  also a 15-bit LFSR and its FLG rate is likewise the rate its LFSR is
#  clocked at, so equal clocks give comparable spectra.
#
#  These were previously entered as frequencies about 93 times too low --
#  4811Hz at the top where the hardware runs at 447kHz -- which mapped every
#  period onto a far slower DSP rate and made the whole channel sound too low
#  to be noise.  The top few periods are faster than the DSP can go at all and
#  clamp at its 32kHz maximum; nothing better is available.
NES_NOISE_PERIOD = [4, 8, 16, 32, 64, 96, 128, 160,
                    202, 254, 380, 508, 762, 1016, 2034, 4068]
NES_NOISE = [CPU / p for p in NES_NOISE_PERIOD]

#  NES length counter table, indexed by the top five bits of $400F.
NES_LENGTH = [10,254, 20,  2, 40,  4, 80,  6,160,  8, 60, 10, 14, 12, 26, 14,
              12, 16, 24, 18, 48, 20, 96, 22,192, 24, 72, 26, 16, 28, 32, 30]


def noise_table():
    #  Rate 0 is excluded deliberately.  It does not mean "very slow": the
    #  DSP's counter never fires at rate 0, so the noise LFSR stops dead and
    #  the voice emits whatever value it froze on -- a constant, which is a DC
    #  offset rather than noise.  The slowest NES period, index 15 at 4.7Hz,
    #  is nearer 0 than to rate 1's 16Hz by simple distance, so an unguarded
    #  search picked it and turned that period into silence-plus-offset.
    out=[]
    for f in NES_NOISE:
        out.append(min(range(1, 32), key=lambda i: abs(DSP_NOISE[i]-f)))
    return out

def emitb(f, name, vals):
    f.write("\n%s:\n" % name)
    for i in range(0, len(vals), 16):
        f.write("    .byte " + ",".join("$%02X" % v for v in vals[i:i+16]) +
                ("    ; t=%d\n" % i))


def main():
    pulse, psize = table(16)    # pulse and noise share the /16 divisor
    tri,   tsize = table(32)    # triangle is an octave down, same timer
    with open(OUT, "w") as f:
        f.write("; GENERATED by tools/genapu.py -- do not edit.\n")
        f.write("; NES 11-bit timer -> S-DSP 14-bit pitch, paired with the\n"
                "; cycle length that pitch is computed for (see SIZES).  Two\n"
                "; sets: pulse/noise, and the octave-lower triangle.\n"
                "; The size bytes are pre-shifted into their place in the\n"
                "; sequence byte, bits 5-3.\n")
        emit(f, "apupitch_pulse", pulse)
        emit(f, "apupitch_tri",   tri)
        emitb(f, "apusize_pulse", psize)
        emitb(f, "apusize_tri",   tsize)
        nt=noise_table()
        f.write("\n; NES noise period -> S-DSP noise rate (bits 4-0 of FLG)\napunoise:\n")
        f.write("    .byte " + ",".join("$%02X"%v for v in nt) + "\n")
        f.write("\n; NES length counter, indexed by the top five bits of $400F\napulen:\n")
        for i in range(0, 32, 16):
            f.write("    .byte " + ",".join("$%02X"%v for v in NES_LENGTH[i:i+16]) + "\n")
    # a short human summary of the musically-useful span
    def span(vals, lo, hi):
        return "t=%d->$%04X .. t=%d->$%04X" % (lo, vals[lo], hi, vals[hi])
    print("wrote %s" % OUT)
    print("  pulse: %s" % span(pulse, 32, 2032))
    print("  tri:   %s" % span(tri, 16, 762))
    clamped = sum(1 for v in pulse if v == PITCH_MAX)
    print("  pulse timers clamped at ceiling (never musical): %d of 2048" % clamped)


if __name__ == "__main__":
    main()
