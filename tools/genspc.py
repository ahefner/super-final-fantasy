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
import os, re

#  Diagnostic only: FFTONE=vol or FFTONE=pitch suppresses that register's
#  write cache, so it goes onto the DSP bus every frame carrying a value the
#  DSP already holds.  Dithering the value instead -- the obvious way to force
#  a write -- is a 30Hz modulation in its own right, which is audible and
#  confounds exactly the comparison it was meant to serve.
_NOCACHE = os.environ.get("FFTONE", "")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(os.path.dirname(HERE), "src", "spcprog.inc")

LOAD = 0x0200          # where the image lands in SPC RAM, and the entry point
DIRPAGE = 0x05         # directory at $0500.  It has to be page aligned, so
                       # whatever sits below it is the program's whole budget:
                       # $0200..$04FF, 768 bytes.  It was one page lower, and
                       # the program grew past the 512 bytes that left it.
ADDRTAB = 0x0520       # waveform address table, one word per waveform
BRRBASE = 0x0570       # BRR sample data (past a 40-entry address table)

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
    def or_a_dp(self, d):      self.emit(0x04, d)
    def and_a_dp(self, d):     self.emit(0x24, d)
    def eor_a_dp(self, d):     self.emit(0x44, d)
    def inc_a(self):           self.emit(0xBC)
    def bcc(self, lbl):        self.branch(0x90, lbl)
    def mov_dpx_a(self, d):    self.emit(0xD4, d)
    def cmp_a_dpx(self, d):    self.emit(0x74, d)
    def eor_a_imm(self, v):    self.emit(0x48, v)
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
DIRBASE = 0x0500      # directory: entry n at DIRBASE + 4n, eight of them --
                      # two per voice, so one can be rewritten while the DSP
                      # is still reading the other
LASTIDX = 0x14        # four bytes: waveform index each voice was last given
SRCNV   = 0x18        # four bytes: which directory slot each voice points at
NEWSRCN = 0x1C        # scratch: the slot being switched to
ENDXACC = 0x1D        # ENDX bits seen since each voice last consumed its own
DEADCNT = 0x20        # four bytes: packets since each voice last looped
DEADFRAMES = 8        # ...before we conclude it has stopped and key it again
VOLC    = 0x24        # four bytes: volume each voice was last actually sent
PITCHLC = 0x28        # four bytes: ...and its pitch, low
PITCHHC = 0x2C        # four bytes: ...and high
KONPEND = 0x30        # nonzero while a key-on is still asserted in KON

def _check_opcodes():
    """No two mnemonics may emit the same opcode byte.

    A duplicate is silent: the assembler is happy, the program runs, and it
    quietly does different arithmetic than it reads as.
    """
    import collections, inspect
    seen = collections.defaultdict(list)
    for name, fn in inspect.getmembers(Asm, predicate=inspect.isfunction):
        src = inspect.getsource(fn)
        m = re.search(r"self\.emit\((0x[0-9A-Fa-f]+)", src)
        if m and name not in ("emit", "branch", "dsp", "dsp_a"):
            seen[int(m.group(1), 16)].append(name)
    dupes = {op: names for op, names in seen.items() if len(names) > 1}
    if dupes:
        raise SystemExit("genspc: duplicate opcodes -- " + "; ".join(
            "$%02X used by %s" % (op, " and ".join(n)) for op, n in dupes.items()))


def program():
    _check_opcodes()
    a = Asm(LOAD)
    a.di(); a.clrp()
    # key-on mask table, written into direct page at start-up
    for i in range(4): a.mov_dp_imm(MASKTAB + i, 1 << i)
    #  Which directory slot each voice points at, and the waveform index it was
    #  last given.  $FF is not a real index, so the first packet always moves.
    for i in range(4):
        a.mov_dp_imm(SRCNV + i, i)
        a.mov_dp_imm(LASTIDX + i, 0xFF)
        a.mov_dp_imm(DEADCNT + i, 0)
        a.mov_dp_imm(VOLC + i, 0xFF)     # nothing has been sent yet, so the
        a.mov_dp_imm(PITCHLC + i, 0xFF)  #   first packet always writes
        a.mov_dp_imm(PITCHHC + i, 0xFF)
    a.mov_dp_imm(ENDXACC, 0)
    a.mov_dp_imm(KONPEND, 0)
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
    #  $7C leaves that worst case just inside the rail, so no combination of
    #  channels can clip, and changes no voice's level relative to another.
    #  (It reads as twice the figure this once was because BRR_SCALE dropped by
    #  one at the same time and halved every sample: the product, and with it
    #  the output level, is unchanged.)
    #
    #  The bill is really the unipolar waveforms': half their swing is a DC
    #  offset nobody can hear -- the console AC-couples its output -- but it
    #  occupies headroom all the same.  A NES has the same shape of problem
    #  and answers it with a non-linear mixer that compresses as channels pile
    #  up instead of clipping.  Nothing here can do that: the SPC700 sets a
    #  volume per voice and the DSP sums them, so the only lever is the level
    #  they are summed at.
    a.dsp(0x0C, 0x7C)         # MVOL_L
    a.dsp(0x1C, 0x7C)         # MVOL_R
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

    #  Release the previous packet's key-on before doing anything else.
    #
    #  KON is a level the DSP samples, not an edge it catches.  Left set, a
    #  voice is keyed on again every sample period, and every key-on resets
    #  that voice's envelope to zero -- so a voice whose bit stays in KON goes
    #  silent and stays silent, until some later key-on for another voice
    #  happens to overwrite the byte.  That is minutes, if the music does not
    #  need the other voices.
    #
    #  Clearing it here rather than straight after the write gives the DSP its
    #  sample period to latch it: packets are separated by the 65816's
    #  handshake round trip, which is hundreds of microseconds, where the few
    #  cycles between the write and the acknowledge would not be enough.
    a.mov_a_dp(KONPEND)       # ...but only if one is actually asserted: an
    a.beq("nokon")            #   idle voice should put nothing on the bus
    a.dsp(0x4C, 0x00)
    a.mov_dp_imm(KONPEND, 0)
    a.label("nokon")

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
    #  One NES nibble, scaled per voice, because the three kinds of voice do
    #  not arrive at the same amplitude.  Our pulses are unipolar and peak at
    #  14336, the triangle is bipolar and peaks at 16384, and the noise is not
    #  a waveform of ours at all -- the DSP's own generator, which spans the
    #  whole sixteen-bit range.  Left at the same scale the noise comes out
    #  four times a pulse where a NES puts it at 1.17, which is audible as the
    #  noise channel sitting far too high in the mix.
    #
    #  The targets are the NES's non-linear mixer at full level: a pulse at
    #  0.1494, the triangle at 0.2464 and noise at 0.1744, or 1.65 and 1.17
    #  times a pulse.  Against those, x4 / x3 / x1 gives 1.50 and 1.00 -- the
    #  triangle a little under and the noise a little under, both inside a
    #  decibel and a half, which is as close as whole multiples of a four-bit
    #  nibble reach.
    #
    #  It also settles the last of the headroom: the noise at x4 put the
    #  worst case at 44619 against a 32767 rail, and at x1 it is 29746.
    a.and_a_imm(0x0F)         # NES 4-bit volume
    a.mov_dp_a(VOL)           # x1 -- which is the noise voice's share
    a.mov_a_dp(VB); a.cmp_a_imm(NOISE_VOICE * 0x10); a.beq("volset")
    a.mov_a_dp(VB); a.cmp_a_imm(TRIANGLE_VOICE * 0x10); a.beq("trivol")
    a.mov_a_dp(VOL); a.asl_a(); a.asl_a()         # x4 for the pulses: unipolar
    a.mov_dp_a(VOL)                               #   swings half as far
    a.bra("volset")
    a.label("trivol")
    a.mov_a_dp(VOL); a.asl_a(); a.mov_dp_a(PHI)   # x3 for the triangle
    a.mov_a_dp(VOL); a.clc(); a.adc_a_dp(PHI)
    a.mov_dp_a(VOL)
    a.label("volset")
    #  Only write what changed.
    #
    #  A packet arrives for every sounding voice every frame whether or not
    #  anything about it moved, and this rewrote volume and pitch each time.
    #  Measured on two steady voices, that is twelve DSP register writes a
    #  frame carrying values the DSP already holds.  Each one is a chance to
    #  land on the moment the DSP is reading that register in its own
    #  thirty-two cycle voice loop, and two voices double the chances -- which
    #  is where the popping starts.  Held music notes are the same situation.
    #
    #  So cache what was last sent per voice and skip the write when it has not
    #  moved.  With nothing changing, nothing is written at all.
    a.mov_a_dp(VB); a.xcn_a(); a.and_a_imm(0x0F); a.mov_x_a()   # X = voice
    a.mov_a_dp(VOL)
    a.cmp_a_dpx(VOLC)
    if "vol" not in _NOCACHE:
        a.beq("volsame")
    a.mov_dpx_a(VOLC)
    a.mov_a_dp(VB);                  a.mov_dp_a(0xF2); a.mov_a_dp(VOL); a.mov_dp_a(0xF3)
    a.mov_a_dp(VB); a.or_a_imm(1);   a.mov_dp_a(0xF2); a.mov_a_dp(VOL); a.mov_dp_a(0xF3)
    a.label("volsame")
    # The noise voice takes no pitch or waveform: instead its packet's pitch-low
    # byte is the global noise rate, written into FLG's low five bits (echo
    # writes stay disabled, bit 5).
    a.mov_a_dp(VB); a.cmp_a_imm(NOISE_VOICE * 0x10); a.bne("tonal")
    a.mov_a_dp(0xF6); a.and_a_imm(0x1F); a.or_a_imm(0x20); a.dsp_a(0x6C)
    a.jmp("keys")
    a.label("tonal")
    # PITCH_L, PITCH_H straight from the ports; the duty rides in PITCH_H's top
    # bits.  Skipped entirely when neither byte has moved -- see volset.
    a.mov_a_dp(0xF7); a.and_a_imm(0x3F); a.mov_dp_a(PHI)
    a.mov_a_dp(VB); a.xcn_a(); a.and_a_imm(0x0F); a.mov_x_a()   # X = voice
    a.mov_a_dp(0xF6)
    a.cmp_a_dpx(PITCHLC)
    a.bne("pitchwrite")
    a.mov_a_dp(PHI)
    a.cmp_a_dpx(PITCHHC)
    if "pitch" not in _NOCACHE:
        a.beq("pitchsame")
    a.label("pitchwrite")
    a.mov_a_dp(0xF6); a.mov_dpx_a(PITCHLC)
    a.mov_a_dp(PHI);  a.mov_dpx_a(PITCHHC)
    a.mov_a_dp(VB); a.or_a_imm(2);   a.mov_dp_a(0xF2); a.mov_a_dp(0xF6); a.mov_dp_a(0xF3)
    a.mov_a_dp(VB); a.or_a_imm(3);   a.mov_dp_a(0xF2); a.mov_a_dp(PHI);  a.mov_dp_a(0xF3)
    a.label("pitchsame")
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
    #  Repoint the voice's waveform -- without ever letting the DSP read a
    #  half-written pointer.
    #
    #  A directory entry is four bytes, and the second pair is the loop address
    #  the DSP fetches every time the voice wraps its cycle -- a thousand times
    #  a second for a short waveform.  Writing those four bytes in place, as
    #  this did, means a fetch landing between the low byte and the high byte
    #  gets one of each: an address in neither waveform, decoded as BRR.  That
    #  is a pop, and if the garbage block happens to carry END without LOOP the
    #  voice stops dead -- and stays stopped, because the 65816 believes it is
    #  still sounding and so never keys it again.  Rare enough to be invisible
    #  under an emulator that fetches on a different schedule; on hardware it
    #  is minutes.
    #
    #  So: write the spare slot, then move the voice to it with the single byte
    #  of SRCN.  A fetch either side of that write sees one whole entry or the
    #  other.  Nothing is written at all unless the index actually changed,
    #  which is most frames.
    a.mov_a_dp(VB); a.xcn_a(); a.and_a_imm(0x0F); a.mov_x_a()       # X = voice
    a.mov_a_dp(WIDX)
    a.cmp_a_dpx(LASTIDX)
    a.beq("dirdone")
    a.mov_dpx_a(LASTIDX)
    a.mov_a_dpx(SRCNV); a.eor_a_imm(0x04); a.mov_dpx_a(SRCNV)       # the spare
    a.mov_dp_a(NEWSRCN)                                             # X is about
    a.asl_a(); a.asl_a(); a.mov_y_a()                               # Y = slot*4
    a.mov_a_dp(WIDX); a.asl_a(); a.mov_x_a()                        # X = index*2
    a.mov_a_absx(ADDRTAB);    a.mov_absy_a(DIRBASE);     a.mov_absy_a(DIRBASE + 2)
    a.inc_x()
    a.mov_a_absx(ADDRTAB);    a.mov_absy_a(DIRBASE + 1); a.mov_absy_a(DIRBASE + 3)
    a.mov_a_dp(VB); a.or_a_imm(0x04); a.mov_dp_a(0xF2)              # DSP SRCN
    a.mov_a_dp(NEWSRCN); a.mov_dp_a(0xF3)
    a.label("dirdone")

    #  Is this voice still making sound?
    #
    #  The 65816 keys a voice on when it starts sounding and not again while it
    #  believes it still is, so a voice the DSP stops for any reason stays
    #  stopped.  That hardly matters for a staccato part -- it re-keys every
    #  note and repairs itself within a note or two -- but a sustained one can
    #  go thousands of frames without a key event.  Measured: the overworld
    #  bassline re-keys every twelve to twenty-four frames and recovers on its
    #  own; the menu bassline runs its notes together and does not.
    #
    #  This asked ENDX first, which was the wrong question.  ENDX says the BRR
    #  engine is still advancing, and a voice whose envelope is pinned at zero
    #  keeps looping and keeps setting it -- alive by that test, and silent.
    #  ENVX is the envelope itself, so zero there while we believe the voice
    #  should be sounding is the symptom rather than a proxy for it.
    #
    #  A key-on ramps the envelope up from zero, so a freshly keyed voice reads
    #  zero for a frame or two; DEADFRAMES is well clear of that.
    a.mov_a_dp(VB); a.cmp_a_imm(NOISE_VOICE * 0x10); a.beq("livedone")
    a.mov_a_dp(VB); a.xcn_a(); a.and_a_imm(0x0F); a.mov_x_a()
    a.mov_a_dp(VB); a.or_a_imm(0x08); a.mov_dp_a(0xF2)      # ENVX for this voice
    a.mov_a_dp(0xF3)
    a.bne("alive")
    a.mov_a_dpx(DEADCNT); a.inc_a(); a.mov_dpx_a(DEADCNT)
    a.cmp_a_imm(DEADFRAMES)
    a.bcc("livedone")
    a.mov_a_imm(0); a.mov_dpx_a(DEADCNT)
    a.mov_a_dp(CMD); a.or_a_imm(0x40); a.mov_dp_a(CMD)      # force a key-on
    a.bra("livedone")
    a.label("alive")
    a.mov_a_imm(0); a.mov_dpx_a(DEADCNT)
    a.label("livedone")
    a.label("keys")
    a.mov_a_dp(CMD); a.and_a_imm(0x40); a.beq("ack")
    a.dsp(0x5C, 0x00)                # a key-on needs KOFF clear first
    a.mov_a_dp(MASK); a.dsp_a(0x4C)  # KON = mask
    a.mov_dp_imm(KONPEND, 1)         # release it on the next packet
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
#  BRR scale for every waveform here.  Not 12, the maximum, and that matters.
#
#  The decoder computes  (nibble << scale) >> 1  and stores the sample doubled,
#  so at scale 12 a nibble of -8 becomes exactly -32768 -- the floor of the
#  voice's internal range.  The triangle is the only waveform that uses -8; the
#  pulses are unipolar, 0 to +7, and reach 87.5%.
#
#  That matters because of how the DSP interpolates.  It sums four Gaussian
#  weighted taps, and after three of them truncates the running total to
#  sixteen bits -- wrapping, not clamping (gaussian.cpp).  Feed it samples
#  already at the rail and that partial sum can pass the boundary and come back
#  with the opposite sign: a full-scale discontinuity in one sample.  It is
#  heard as clipping, and only while the triangle plays.
#
#  Measured in a capture of the town music before this changed: eleven
#  one-sample jumps above 12000, every one while the triangle sounded and none
#  at any other time, the largest 16129.
#
#  Scale 11 halves every sample -- the waveforms are 4-bit, so no shape is lost,
#  only headroom gained -- and MVOL doubles to put the level back.  What then
#  bounds the mix is the clamp at the end of the chain, which saturates
#  properly, rather than a wrap in the middle of the interpolator.
BRR_SCALE = 11

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
    return brr_wave(cycle * reps, BRR_SCALE)

def triangle(period):
    """The NES triangle: a 32-step staircase 15..0, 0..15, resampled to the
    cycle length in use.  Longer cycles do not add steps -- the NES has 32 and
    no more -- they place the same steps more sharply in time."""
    steps = list(range(15, -1, -1)) + list(range(0, 16))
    cycle = [steps[i * 32 // period] - 8 for i in range(period)]   # -8..+7
    reps = max(1, 16 // period)
    return brr_wave(cycle * reps, BRR_SCALE)

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
    assert len(prog) <= DIRBASE - LOAD, (len(prog), DIRBASE - LOAD)
    #  Derived, not written down twice: the program runs from LOAD up to the
    #  directory page, and moving the directory moves the budget with it.
    pad = DIRBASE - LOAD - len(prog)
    assert pad >= 0, ("SPC program is %d bytes; only %d fit below the directory"
                      % (len(prog), DIRBASE - LOAD))
    image = bytearray(prog) + bytes(pad)
    # directory: start/loop for each waveform
    # four directory entries, one per VOICE (not per waveform); each starts on
    # waveform 0 and is repointed by the program as packets arrive
    brr = b"".join(WAVES)
    #  Four directory entries, one per voice.  Every one is repointed by the
    #  program as packets arrive, so the values here only have to be sane
    #  until the first note.
    ent = lambda w: bytes([w & 0xFF, w >> 8, w & 0xFF, w >> 8])
    w0 = WAVEADDR[0]; wt = WAVEADDR[TRIWAVE0]
    four = ent(w0) + ent(w0) + ent(wt) + ent(w0)       # voice 2 is the triangle
    dirent = four + four                               # ...and each one's spare
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
