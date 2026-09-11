#!/usr/bin/env python3
"""
genspc.py -- build the SPC700 program and its sample data into src/spcprog.inc

The SPC700 side of the audio port is deliberately dumb: the 65816 works out
what every voice should be doing each frame and sends it over the four I/O
ports; this program just applies it to the S-DSP.  Keeping the logic on the
65816 keeps it where it can be traced and profiled.  Nothing here needs to
change once it works.

Port protocol (65816 -> SPC700), one packet per voice per frame:
    $2141  cmd    bit 7 key-off, bit 6 key-on, bits 5-4 voice, bits 3-0 volume
    $2142  pitch, low byte           (S-DSP 14-bit pitch, from apupitch.inc)
    $2143  pitch, high byte in bits 5-0; bits 7-6 select the waveform (duty)

Each voice's directory entry is rewritten to the chosen waveform on every
packet.  The DSP reads a voice's loop address from the directory each time
the sample loops, so a duty change takes effect at the next cycle with no
key-on -- which is how the NES does it, and the only way a change mid-note
does not click.
    $2140  sequence number, written last; the SPC700 acts when it changes and
           echoes it back as the acknowledgement.

SPC700 memory:
    $0200  this program
    $0400  sample directory (DIR = $04), one entry per waveform
    $0410  BRR sample data
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(os.path.dirname(HERE), "src", "spcprog.inc")

LOAD = 0x0200          # where the image lands in SPC RAM, and the entry point
DIRPAGE = 0x04         # directory at $0400
ADDRTAB = 0x0410       # waveform address table, one word per waveform
BRRBASE = 0x0460       # BRR sample data (past a 40-entry address table)

# --- a very small SPC700 assembler ----------------------------------------
class Asm:
    def __init__(self, org):
        self.org = org; self.code = bytearray(); self.labels = {}; self.fix = []
    def pc(self): return self.org + len(self.code)
    def label(self, n): self.labels[n] = self.pc()
    def emit(self, *b): self.code += bytes(b)
    # instructions
    def mov_a_imm(self, i):    self.emit(0xE8, i)
    def mov_a_dp(self, d):     self.emit(0xE4, d)
    def mov_a_dpx(self, d):    self.emit(0xF4, d)
    def mov_a_absx(self, a):   self.emit(0xF5, a & 0xFF, a >> 8)  # MOV A,!abs+X
    def mov_dp_a(self, d):     self.emit(0xC4, d)
    def mov_dp_imm(self, d, i):self.emit(0x8F, i, d)     # operand order: imm, dp
    def mov_x_a(self):         self.emit(0x5D)
    def mov_y_a(self):         self.emit(0xFD)
    def lsr_a(self):           self.emit(0x5C)
    def inc_x(self):           self.emit(0x3D)
    def mov_absy_a(self, a):   self.emit(0xD6, a & 0xFF, a >> 8)     # MOV !abs+Y,A
    def mov_a_x(self):         self.emit(0x7D)
    def cmp_a_dp(self, d):     self.emit(0x64, d)
    def cmp_a_imm(self, i):    self.emit(0x68, i)
    def adc_a_dp(self, d):     self.emit(0x84, d)
    def adc_a_imm(self, i):    self.emit(0x88, i)
    def clc(self):             self.emit(0x60)
    def and_a_imm(self, i):    self.emit(0x28, i)
    def or_a_imm(self, i):     self.emit(0x08, i)
    def asl_a(self):           self.emit(0x1C)
    def xcn_a(self):           self.emit(0x9F)
    def clrp(self):            self.emit(0x20)
    def di(self):              self.emit(0xC0)
    def branch(self, op, lab):
        self.emit(op, 0); self.fix.append((len(self.code) - 1, lab))
    def beq(self, l): self.branch(0xF0, l)
    def bne(self, l): self.branch(0xD0, l)
    def bra(self, l): self.branch(0x2F, l)
    def jmp(self, l):
        self.emit(0x5F, 0, 0); self.fix.append((len(self.code) - 2, ("abs", l)))
    def link(self):
        for pos, lab in self.fix:
            if isinstance(lab, tuple):
                a = self.labels[lab[1]]
                self.code[pos] = a & 0xFF; self.code[pos + 1] = a >> 8
            else:
                rel = self.labels[lab] - (self.org + pos + 1)
                assert -128 <= rel <= 127, (lab, rel)
                self.code[pos] = rel & 0xFF
    # helpers
    def dsp(self, reg, val):   # write a constant to a DSP register
        self.mov_dp_imm(0xF2, reg); self.mov_dp_imm(0xF3, val)
    def dsp_a(self, reg):      # write A to a DSP register
        self.mov_dp_imm(0xF2, reg); self.mov_dp_a(0xF3)

# direct-page variables (page 0, clear of the $F0-$FF I/O registers)
LAST, CMD, VOL, VB, PHI, MASK = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
WIDX    = 0x06        # waveform index from the sequence byte
MASKTAB = 0x10        # four bytes: 1<<voice
DIRBASE = 0x0400      # directory: entry v at DIRBASE + 4v

def program():
    a = Asm(LOAD)
    a.di(); a.clrp()
    # key-on mask table, written into direct page at start-up
    for i in range(4): a.mov_dp_imm(MASKTAB + i, 1 << i)
    # Port 0 still holds the boot ROM's final handshake value.  Take that as the
    # sequence baseline rather than 0, or it reads as a first packet -- one made
    # of whatever the upload left on the other ports.
    a.mov_a_dp(0xF4); a.mov_dp_a(LAST)
    # S-DSP global set-up
    a.dsp(0x6C, 0x20)         # FLG: reset off, mute off, echo writes disabled
    #  Main volume, backed off far enough that the mix cannot clip.
    #
    #  The pulses are unipolar (see square()), so every voice's offset pushes
    #  the same way instead of partly cancelling as bipolar waves would, and
    #  the worst case is just the sum of all four peaks.  Measured against the
    #  emulator's own output, one unit of a voice's VOL is worth about 242 at
    #  MVOL $68, and VOL reaches 60+60+45+60 = 225 with both pulses loud, the
    #  triangle under them and a noise effect on top.  That is 54572 against a
    #  32767 ceiling: it clips, and not rarely enough to ignore -- it is what
    #  the overworld and town music do.
    #
    #  $3E leaves that worst case at 32533, just inside the rail, so no
    #  combination of channels can clip.  It costs about 4.5dB against the
    #  previous setting and changes no voice's level relative to another.
    #
    #  The bill is really the unipolar waveforms': half their swing is a DC
    #  offset nobody can hear -- the console AC-couples its output -- but it
    #  occupies headroom all the same.  A NES has the same shape of problem
    #  and answers it with a non-linear mixer that compresses as channels pile
    #  up instead of clipping.  Nothing here can do that: the SPC700 sets a
    #  volume per voice and the DSP sums them, so the only lever is the level
    #  they are summed at.
    a.dsp(0x0C, 0x3E)         # MVOL_L
    a.dsp(0x1C, 0x3E)         # MVOL_R
    a.dsp(0x2C, 0x00)         # EVOL_L
    a.dsp(0x3C, 0x00)         # EVOL_R
    a.dsp(0x5C, 0xFF)         # KOFF everything
    a.dsp(0x4C, 0x00)         # KON nothing
    a.dsp(0x2D, 0x00)         # PMON off
    a.dsp(0x3D, 0x08)         # NON: voice 3 plays the noise generator
    a.dsp(0x4D, 0x00)         # EON off
    a.dsp(0x5D, DIRPAGE)      # DIR
    for v in range(4):        # each voice: its own directory entry, gain mode
        a.dsp(v * 0x10 + 0x04, v)        # SRCN = voice; the entry is repointed
        a.dsp(v * 0x10 + 0x05, 0x00)     # ADSR1: bit7 clear -> GAIN used
        # GAIN in linear-increase mode at the fastest rate: 0 to full in 64
        # samples, 2 ms.  Not direct mode.  With direct gain the voice jumps
        # from silence to its first sample at key-on, and the interpolator --
        # which softens every other edge of a stretched low-pitch square --
        # cannot soften that one, so it clicks.  A 2 ms ramp is below the
        # threshold where an attack reads as soft, and key-off gets the DSP's
        # release fade for free.
        a.dsp(v * 0x10 + 0x07, 0xDF)     # GAIN: linear increase, rate 31
    a.dsp(0x5C, 0x00)         # release KOFF so voices can be keyed later
    a.mov_dp_imm(0xF4, 0)     # tell the 65816 we are alive: ack = 0

    a.label("loop")
    a.mov_a_dp(0xF4)          # sequence number from the 65816
    a.cmp_a_dp(LAST)
    a.beq("loop")             # unchanged: nothing to do
    a.mov_dp_a(LAST)
    a.mov_a_dp(0xF5)          # cmd
    a.mov_dp_a(CMD)
    a.and_a_imm(0x30)         # voice bits are already voice*16 == DSP reg base
    a.mov_dp_a(VB)
    a.xcn_a()                 # $30 -> $03: the voice number...
    a.mov_x_a(); a.mov_a_dpx(MASKTAB)
    a.mov_dp_a(MASK)          # ...and its key mask
    # A key-off writes KOFF and nothing else.  Zeroing the volume in the same
    # packet -- as a first version did -- cuts the output dead before the
    # DSP's release can fade it, and that cut is a click on every note-off,
    # loud on the smooth triangle and audible on a low pulse sitting on a long
    # plateau.  Leave VOL and PITCH where they are; the release does the rest.
    a.mov_a_dp(CMD); a.and_a_imm(0x80); a.beq("sounding")
    a.mov_a_dp(MASK); a.dsp_a(0x5C)  # KOFF = mask
    a.jmp("ack")
    a.label("sounding")
    a.mov_a_dp(CMD)
    a.and_a_imm(0x0F)         # NES 4-bit volume.
    a.asl_a()                 # x2 for everything...
    a.mov_dp_a(VOL)
    a.mov_a_dp(VB); a.cmp_a_imm(TRIANGLE_VOICE * 0x10); a.beq("trivol")
    a.mov_a_dp(VOL); a.asl_a(); a.mov_dp_a(VOL)   # ...x4 for the pulses and
    a.bra("volset")                               # noise: a unipolar wave
    a.label("trivol")                             # swings half as far for the
    a.mov_a_dp(VOL); a.lsr_a(); a.mov_dp_a(PHI)   # same peak, so this restores
    a.mov_a_dp(VOL); a.clc(); a.adc_a_dp(PHI)     # the level that was right
    a.mov_dp_a(VOL)                               # x3 for the bipolar triangle
    a.label("volset")
    # VOL_L, VOL_R
    a.mov_a_dp(VB);                  a.mov_dp_a(0xF2); a.mov_a_dp(VOL); a.mov_dp_a(0xF3)
    a.mov_a_dp(VB); a.or_a_imm(1);   a.mov_dp_a(0xF2); a.mov_a_dp(VOL); a.mov_dp_a(0xF3)
    # The noise voice takes no pitch or waveform: instead its packet's pitch-low
    # byte is the global noise rate, written into FLG's low five bits (echo
    # writes stay disabled, bit 5).
    a.mov_a_dp(VB); a.cmp_a_imm(NOISE_VOICE * 0x10); a.bne("tonal")
    a.mov_a_dp(0xF6); a.and_a_imm(0x1F); a.or_a_imm(0x20); a.dsp_a(0x6C)
    a.jmp("keys")
    a.label("tonal")
    # PITCH_L, PITCH_H straight from the ports; the duty rides in PITCH_H's top bits
    a.mov_a_dp(VB); a.or_a_imm(2);   a.mov_dp_a(0xF2); a.mov_a_dp(0xF6); a.mov_dp_a(0xF3)
    a.mov_a_dp(0xF7); a.mov_dp_a(PHI)
    a.mov_a_dp(VB); a.or_a_imm(3);   a.mov_dp_a(0xF2); a.mov_a_dp(PHI); a.and_a_imm(0x3F); a.mov_dp_a(0xF3)
    #  Repoint this voice's directory entry (start and loop) at the waveform
    #  the 65816 chose.  Both duty and cycle length ride in the sequence byte's
    #  top five bits; the triangle's eight sit above the pulses' thirty-two.
    #  The entry is the loop address too, so a change with no key-on takes hold
    #  at the end of the cycle in progress rather than cutting one short.
    a.mov_a_dp(LAST)
    for _ in range(3): a.lsr_a()                                    # 0..31
    a.mov_dp_a(WIDX)
    a.mov_a_dp(VB); a.cmp_a_imm(TRIANGLE_VOICE * 0x10); a.bne("pulsewave")
    a.mov_a_dp(WIDX); a.clc(); a.adc_a_imm(TRIWAVE0); a.mov_dp_a(WIDX)
    a.label("pulsewave")
    a.mov_a_dp(VB); a.lsr_a(); a.lsr_a(); a.mov_y_a()               # Y = voice*4
    a.mov_a_dp(WIDX); a.asl_a(); a.mov_x_a()                        # X = index*2
    a.mov_a_absx(ADDRTAB);    a.mov_absy_a(DIRBASE);     a.mov_absy_a(DIRBASE + 2)
    a.inc_x()
    a.mov_a_absx(ADDRTAB);    a.mov_absy_a(DIRBASE + 1); a.mov_absy_a(DIRBASE + 3)
    a.label("keys")
    a.mov_a_dp(CMD); a.and_a_imm(0x40); a.beq("ack")
    a.dsp(0x5C, 0x00)                # a key-on needs KOFF clear first
    a.mov_a_dp(MASK); a.dsp_a(0x4C)  # KON = mask
    a.label("ack")
    a.mov_a_dp(LAST); a.mov_dp_a(0xF4)   # acknowledge
    a.jmp("loop")
    a.link()
    return bytes(a.code)

# --- sample data -----------------------------------------------------------
def brr_block(nibbles, shift, loop, end):
    hdr = (shift << 4) | (int(loop) << 1) | int(end)   # filter 0
    out = bytearray([hdr])
    for i in range(0, 16, 2):
        out.append(((nibbles[i] & 0xF) << 4) | (nibbles[i + 1] & 0xF))
    return bytes(out)

#  One cycle of a waveform is not a fixed length here.  The DSP makes a note
#  higher by playing a waveform faster, and both ends of that are bounded: the
#  pitch register stops at $3FFF, four times native rate, and a waveform of N
#  samples can only hold N/2 harmonics however slowly it is played.  A single
#  length is therefore wrong at both ends at once -- a 64-sample cycle gives a
#  55Hz bass note just 32 harmonics, stopping at 1.7kHz, while the menu chirp
#  at 3.4kHz needs a pitch of 27764 that does not exist.
#
#  So keep a family, and pick per note (see genapu.py) the one whose playback
#  rate lands near TARGET_RATE.  Bass notes get a long cycle and hundreds of
#  harmonics; the chirp gets a short one it can play fast enough.
#
#  A BRR block is 16 samples, so a cycle shorter than that is stored as
#  several cycles filling one block -- the loop is still seamless, the voice
#  just runs through more than one period per loop.
SIZES  = [8, 16, 32, 64, 128, 256, 512, 1024]
DUTIES = [(1, 8), (1, 4), (1, 2), (3, 4)]     # NES duty 0..3

def brr_wave(samples, shift):
    """A looping BRR waveform of any whole number of 16-sample blocks: the
    last block is flagged loop+end, so the voice runs the cycle for ever."""
    assert len(samples) % 16 == 0 and samples
    n = len(samples) // 16
    return b"".join(brr_block(samples[i*16:(i+1)*16], shift,
                              i == n - 1, i == n - 1) for i in range(n))

def square(num, den, period):
    """One cycle: the silent phase, then the duty's share of it at full value.

    Unipolar, 0 to +7, the way a NES pulse works -- it outputs its volume
    during the high phase and zero during the low one.  That matters because
    the driver rewrites volume every frame to shape its own envelopes and the
    DSP applies volume as a plain multiplier: with a bipolar wave, at full
    amplitude the whole cycle, every one of those writes steps the output
    wherever it lands, and that step is the click.  Against zero it multiplies
    to nothing and cannot be heard.  A change during the high phase still
    steps, but a NES steps there too.

    The silent phase leads, so a key-on also starts from zero.
    """
    high = max(1, period * num // den)
    cycle = [0] * (period - high) + [7] * high
    reps = max(1, 16 // period)              # short cycles fill a whole block
    return brr_wave(cycle * reps, 12)

def triangle(period):
    """The NES triangle: a 32-step staircase 15..0, 0..15, resampled to the
    cycle length in use.  Longer cycles do not add steps -- the NES has 32 and
    no more -- they place the same steps more sharply in time."""
    steps = list(range(15, -1, -1)) + list(range(0, 16))
    cycle = [steps[i * 32 // period] - 8 for i in range(period)]   # -8..+7
    reps = max(1, 16 // period)
    return brr_wave(cycle * reps, 12)

# NES duty 0..3 = 12.5%, 25%, 50%, 75%  (75% is 25% inverted: same tone);
# waveform 4 is the triangle, voice 2's for good
#  Waveform order fixes the index the 65816 sends in the sequence byte's top
#  five bits: pulses at duty*8 + size, the triangle's eight above them at
#  32 + size.  Five bits only reach 31, so the triangle's index is the size
#  alone and the SPC700 adds the 32 once it knows the packet is voice 2.
WAVES    = [square(n, d, p) for (n, d) in DUTIES for p in SIZES] \
         + [triangle(p) for p in SIZES]
WAVEADDR = []
_o = 0
for _w in WAVES:
    WAVEADDR.append(BRRBASE + _o); _o += len(_w)
TRIWAVE0 = len(SIZES) * len(DUTIES)          # index of the triangle's first

TRIANGLE_VOICE = 2
NOISE_VOICE = 3

def main():
    prog = program()
    assert len(prog) <= 0x200, len(prog)
    image = bytearray(prog) + bytes(0x200 - len(prog))         # pad to $0400
    # directory: start/loop for each waveform
    # four directory entries, one per VOICE (not per waveform); each starts on
    # waveform 0 and is repointed by the program as packets arrive
    brr = b"".join(WAVES)
    #  Four directory entries, one per voice.  Every one is repointed by the
    #  program as packets arrive, so the values here only have to be sane
    #  until the first note.
    ent = lambda w: bytes([w & 0xFF, w >> 8, w & 0xFF, w >> 8])
    w0 = WAVEADDR[0]; wt = WAVEADDR[TRIWAVE0]
    dirent = ent(w0) + ent(w0) + ent(wt) + ent(w0)     # voice 2 is the triangle
    assert len(dirent) == ADDRTAB - DIRBASE, len(dirent)
    addrtab = b"".join(bytes([w & 0xFF, w >> 8]) for w in WAVEADDR)
    assert ADDRTAB + len(addrtab) <= BRRBASE, len(addrtab)
    addrtab += bytes(BRRBASE - ADDRTAB - len(addrtab))
    image += dirent + addrtab + brr
    with open(OUT, "w") as f:
        f.write("; GENERATED by tools/genspc.py -- do not edit.\n")
        f.write("SPCPROG_LOAD  = $%04X\n" % LOAD)
        f.write("SPCPROG_ENTRY = $%04X\n" % LOAD)
        f.write("SPCPROG_LEN   = %d\n" % len(image))
        f.write("spcprog:\n")
        for i in range(0, len(image), 16):
            f.write("    .byte " + ",".join("$%02X" % b for b in image[i:i+16]) + "\n")
    print("SPC program %d bytes, image %d bytes -> %s" % (len(prog), len(image), OUT))

if __name__ == "__main__":
    main()
