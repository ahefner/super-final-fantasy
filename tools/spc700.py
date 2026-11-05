#!/usr/bin/env python3
"""
spc700.py -- just enough SPC700 to run genspc.py's program in a test.

The instructions are the ones genspc.py's assembler can emit and no others:
an opcode outside them stops the run, so a program that grows a new one has
to grow it here too.  The S-DSP is its register file and a log of the writes
to it, and the timers read as no time passing -- no sound is made, only what
the program tells the DSP.  The four ports are two sets, as on the console:
`inp` what the 65816 last wrote (the SPC700's reads of $F4-$F7), `out` what
the SPC700 last wrote (the 65816's reads of $2140-$2143).

attach(bus, spc) puts it behind a cpu65816 Bus's $2140-$2143, run a few
instructions on every read the 65816 makes of them: a coarse lockstep that
lets a handshake on either side finish, not a model of time.

Cycle counts are the SPC700's own, kept so a test can say how long a run of
the program takes at 1.024MHz.
"""

#  opcode: (mnemonic, bytes, cycles); the cycles of a branch are not taken
OPS = {
    0xE8: ("mov a,#", 2, 2), 0xE4: ("mov a,dp", 2, 3), 0xF4: ("mov a,dp+x", 2, 4),
    0xF5: ("mov a,!abs+x", 3, 5), 0xF7: ("mov a,[dp]+y", 2, 6),
    0xC4: ("mov dp,a", 2, 4), 0xD4: ("mov dp+x,a", 2, 5), 0xD6: ("mov !abs+y,a", 3, 6),
    0xC5: ("mov !abs,a", 3, 5), 0xD7: ("mov [dp]+y,a", 2, 7),
    0x8F: ("mov dp,#", 3, 5), 0xFA: ("mov dp,dp", 3, 5),
    0x5D: ("mov x,a", 1, 2), 0xFD: ("mov y,a", 1, 2), 0x7D: ("mov a,x", 1, 2),
    0xF8: ("mov x,dp", 2, 3), 0xD8: ("mov dp,x", 2, 4), 0xCD: ("mov x,#", 2, 2),
    0x8D: ("mov y,#", 2, 2), 0xEB: ("mov y,dp", 2, 3), 0xCB: ("mov dp,y", 2, 4),
    0x5C: ("lsr a", 1, 2), 0x1C: ("asl a", 1, 2), 0x4B: ("lsr dp", 2, 4),
    0x6B: ("ror dp", 2, 4), 0x0B: ("asl dp", 2, 4), 0x2B: ("rol dp", 2, 4),
    0x3D: ("inc x", 1, 2), 0xFC: ("inc y", 1, 2), 0xBC: ("inc a", 1, 2),
    0x1D: ("dec x", 1, 2), 0xDC: ("dec y", 1, 2), 0x9C: ("dec a", 1, 2),
    0xAB: ("inc dp", 2, 4), 0xAC: ("inc !abs", 3, 5), 0x8C: ("dec !abs", 3, 5),
    0x04: ("or a,dp", 2, 3), 0x14: ("or a,dp+x", 2, 4), 0x08: ("or a,#", 2, 2),
    0x24: ("and a,dp", 2, 3), 0x28: ("and a,#", 2, 2),
    0x44: ("eor a,dp", 2, 3), 0x48: ("eor a,#", 2, 2),
    0x64: ("cmp a,dp", 2, 3), 0x74: ("cmp a,dp+x", 2, 4), 0x68: ("cmp a,#", 2, 2),
    0xC8: ("cmp x,#", 2, 2), 0x7E: ("cmp y,dp", 2, 3), 0xAD: ("cmp y,#", 2, 2),
    0x84: ("adc a,dp", 2, 3), 0x88: ("adc a,#", 2, 2), 0xB4: ("sbc a,dp+x", 2, 4),
    0x60: ("clrc", 1, 2), 0x80: ("setc", 1, 2), 0x20: ("clrp", 1, 2), 0xC0: ("di", 1, 3),
    0x9F: ("xcn a", 1, 5), 0x6F: ("ret", 1, 5), 0x3F: ("call", 3, 8), 0x5F: ("jmp", 3, 3),
    0x90: ("bcc", 2, 2), 0xB0: ("bcs", 2, 2), 0xF0: ("beq", 2, 2), 0xD0: ("bne", 2, 2),
    0x2F: ("bra", 2, 4), 0x10: ("bpl", 2, 2),
    0xBA: ("movw ya,dp", 2, 5), 0xDA: ("movw dp,ya", 2, 5), 0x7A: ("addw ya,dp", 2, 5),
    0x9A: ("subw ya,dp", 2, 5), 0x1A: ("decw dp", 2, 6), 0x5A: ("cmpw ya,dp", 2, 4),
}


class SPC700:
    def __init__(self, ram=None):
        self.ram = bytearray(ram) if ram is not None else bytearray(0x10000)
        self.dsp = bytearray(128)
        self.dsplog = []                # (register, value), every write
        self.inp = [0, 0, 0, 0]         # the 65816's writes: our $F4-$F7
        self.out = [0, 0, 0, 0]         # ours: its $2140-$2143
        self.dspaddr = 0
        self.a = self.x = self.y = 0
        self.sp = 0xEF
        self.pc = 0
        self.n = self.z = self.c = self.v = 0
        self.p = 0
        self.cycles = 0
        self.steps = 0

    # --- memory ---------------------------------------------------------------
    def rd(self, addr):
        addr &= 0xFFFF
        if 0xF0 <= addr <= 0xFF:
            if addr == 0xF2:
                return self.dspaddr
            if addr == 0xF3:
                return self.dsp[self.dspaddr & 0x7F]
            if 0xF4 <= addr <= 0xF7:
                return self.inp[addr - 0xF4]
            if 0xFD <= addr <= 0xFF:
                return 0                # the timers: no time passes
            return 0
        return self.ram[addr]

    def wr(self, addr, val):
        addr &= 0xFFFF
        val &= 0xFF
        if 0xF0 <= addr <= 0xFF:
            if addr == 0xF2:
                self.dspaddr = val
            elif addr == 0xF3:
                if self.dspaddr < 0x80:
                    self.dsp[self.dspaddr] = val
                    self.dsplog.append((self.dspaddr, val))
            elif 0xF4 <= addr <= 0xF7:
                self.out[addr - 0xF4] = val
            return
        self.ram[addr] = val

    def dp(self, d):
        return (self.p << 8) | (d & 0xFF)

    def rdw(self, d):
        return self.rd(self.dp(d)) | self.rd(self.dp(d + 1)) << 8

    def fetch(self):
        b = self.rd(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return b

    def nz(self, v, bits=8):
        self.n = v >> (bits - 1) & 1
        self.z = int(v & ((1 << bits) - 1) == 0)
        return v

    # --- one instruction -------------------------------------------------------
    def step(self):
        at = self.pc
        op = self.fetch()
        if op not in OPS:
            raise RuntimeError("SPC700: opcode $%02X at $%04X is not one genspc.py emits" % (op, at))
        name, size, cyc = OPS[op]
        self.cycles += cyc
        self.steps += 1
        ops = [self.fetch() for _ in range(size - 1)]
        o = ops[0] if ops else 0
        absa = ops[0] | ops[1] << 8 if size == 3 else 0

        def cmp(r, m):
            self.c = int(r >= m)
            self.nz((r - m) & 0xFF)

        def adc(m):
            r = self.a + m + self.c
            self.v = int(~(self.a ^ m) & (self.a ^ r) & 0x80 != 0)
            self.c = int(r > 0xFF)
            self.a = self.nz(r & 0xFF)

        def branch(take):
            if take:
                self.cycles += 2
                self.pc = (self.pc + (o - 256 if o > 127 else o)) & 0xFFFF

        if op == 0xE8: self.a = self.nz(o)
        elif op == 0xE4: self.a = self.nz(self.rd(self.dp(o)))
        elif op == 0xF4: self.a = self.nz(self.rd(self.dp(o + self.x)))
        elif op == 0xF5: self.a = self.nz(self.rd(absa + self.x))
        elif op == 0xF7: self.a = self.nz(self.rd(self.rdw(o) + self.y))
        elif op == 0xC4: self.wr(self.dp(o), self.a)
        elif op == 0xD4: self.wr(self.dp(o + self.x), self.a)
        elif op == 0xD6: self.wr(absa + self.y, self.a)
        elif op == 0xC5: self.wr(absa, self.a)
        elif op == 0xD7: self.wr(self.rdw(o) + self.y, self.a)
        elif op == 0x8F: self.wr(self.dp(ops[1]), ops[0])
        elif op == 0xFA: self.wr(self.dp(ops[1]), self.rd(self.dp(ops[0])))
        elif op == 0x5D: self.x = self.nz(self.a)
        elif op == 0xFD: self.y = self.nz(self.a)
        elif op == 0x7D: self.a = self.nz(self.x)
        elif op == 0xF8: self.x = self.nz(self.rd(self.dp(o)))
        elif op == 0xD8: self.wr(self.dp(o), self.x)
        elif op == 0xCD: self.x = self.nz(o)
        elif op == 0x8D: self.y = self.nz(o)
        elif op == 0xEB: self.y = self.nz(self.rd(self.dp(o)))
        elif op == 0xCB: self.wr(self.dp(o), self.y)
        elif op == 0x5C:
            self.c = self.a & 1; self.a = self.nz(self.a >> 1)
        elif op == 0x1C:
            self.c = self.a >> 7; self.a = self.nz(self.a << 1 & 0xFF)
        elif op in (0x4B, 0x6B, 0x0B, 0x2B):
            a = self.dp(o); m = self.rd(a)
            if op == 0x4B: r, c = m >> 1, m & 1
            elif op == 0x6B: r, c = m >> 1 | self.c << 7, m & 1
            elif op == 0x0B: r, c = m << 1 & 0xFF, m >> 7
            else: r, c = (m << 1 | self.c) & 0xFF, m >> 7
            self.c = c; self.wr(a, self.nz(r))
        elif op == 0x3D: self.x = self.nz(self.x + 1 & 0xFF)
        elif op == 0xFC: self.y = self.nz(self.y + 1 & 0xFF)
        elif op == 0xBC: self.a = self.nz(self.a + 1 & 0xFF)
        elif op == 0x1D: self.x = self.nz(self.x - 1 & 0xFF)
        elif op == 0xDC: self.y = self.nz(self.y - 1 & 0xFF)
        elif op == 0x9C: self.a = self.nz(self.a - 1 & 0xFF)
        elif op in (0xAB, 0xAC, 0x8C):
            a = self.dp(o) if op == 0xAB else absa
            self.wr(a, self.nz(self.rd(a) + (-1 if op == 0x8C else 1) & 0xFF))
        elif op == 0x04: self.a = self.nz(self.a | self.rd(self.dp(o)))
        elif op == 0x14: self.a = self.nz(self.a | self.rd(self.dp(o + self.x)))
        elif op == 0x08: self.a = self.nz(self.a | o)
        elif op == 0x24: self.a = self.nz(self.a & self.rd(self.dp(o)))
        elif op == 0x28: self.a = self.nz(self.a & o)
        elif op == 0x44: self.a = self.nz(self.a ^ self.rd(self.dp(o)))
        elif op == 0x48: self.a = self.nz(self.a ^ o)
        elif op == 0x64: cmp(self.a, self.rd(self.dp(o)))
        elif op == 0x74: cmp(self.a, self.rd(self.dp(o + self.x)))
        elif op == 0x68: cmp(self.a, o)
        elif op == 0xC8: cmp(self.x, o)
        elif op == 0x7E: cmp(self.y, self.rd(self.dp(o)))
        elif op == 0xAD: cmp(self.y, o)
        elif op == 0x84: adc(self.rd(self.dp(o)))
        elif op == 0x88: adc(o)
        elif op == 0xB4: adc(self.rd(self.dp(o + self.x)) ^ 0xFF)
        elif op == 0x60: self.c = 0
        elif op == 0x80: self.c = 1
        elif op == 0x20: self.p = 0
        elif op == 0xC0: pass
        elif op == 0x9F: self.a = self.nz((self.a >> 4 | self.a << 4) & 0xFF)
        elif op == 0x6F:
            lo = self.rd(0x100 + (self.sp + 1 & 0xFF)); hi = self.rd(0x100 + (self.sp + 2 & 0xFF))
            self.sp = self.sp + 2 & 0xFF; self.pc = lo | hi << 8
        elif op == 0x3F:
            self.wr(0x100 + self.sp, self.pc >> 8); self.wr(0x100 + (self.sp - 1 & 0xFF), self.pc & 0xFF)
            self.sp = self.sp - 2 & 0xFF; self.pc = absa
        elif op == 0x5F: self.pc = absa
        elif op == 0x90: branch(not self.c)
        elif op == 0xB0: branch(self.c)
        elif op == 0xF0: branch(self.z)
        elif op == 0xD0: branch(not self.z)
        elif op == 0x2F: self.cycles -= 2; branch(True)
        elif op == 0x10: branch(not self.n)
        elif op == 0xBA:
            w = self.rdw(o); self.a, self.y = w & 0xFF, w >> 8; self.nz(w, 16)
        elif op == 0xDA:
            self.wr(self.dp(o), self.a); self.wr(self.dp(o + 1), self.y)
        elif op in (0x7A, 0x9A, 0x5A):
            ya, m = self.y << 8 | self.a, self.rdw(o)
            if op == 0x7A:
                r = ya + m; self.c = int(r > 0xFFFF)
                self.v = int(~(ya ^ m) & (ya ^ r) & 0x8000 != 0)
            else:
                r = ya - m; self.c = int(r >= 0)
                self.v = int((ya ^ m) & (ya ^ r) & 0x8000 != 0)
            r &= 0xFFFF
            self.nz(r, 16)
            if op != 0x5A:
                self.a, self.y = r & 0xFF, r >> 8
        elif op == 0x1A:
            a = self.dp(o); w = self.rdw(o) - 1 & 0xFFFF
            self.wr(a, w & 0xFF); self.wr(self.dp(o + 1), w >> 8); self.nz(w, 16)

    def run(self, n):
        for _ in range(n):
            self.step()


def boot(image, load, baseline):
    """genspc.py's image in a fresh SPC700 at `load`, entered as its loader
    leaves it: the 65816's last index `baseline` on port 0."""
    spc = SPC700()
    spc.ram[load:load + len(image)] = image
    spc.pc = load
    spc.inp[0] = baseline
    return spc


def attach(bus, spc, per_read=6):
    """The SPC700 behind `bus`'s ports: the 65816's writes to $2140-$2143 go
    to its inputs, and every read of them runs it `per_read` instructions
    first and answers with its outputs."""
    read, write = bus.read, bus.write

    def rd(bank, addr):
        a = addr & 0xFFFF
        if 0x2140 <= a <= 0x2143 and (bank & 0x40) == 0:
            spc.run(per_read)
            return spc.out[a - 0x2140]
        return read(bank, addr)

    def wr(bank, addr, val):
        a = addr & 0xFFFF
        if 0x2140 <= a <= 0x2143 and (bank & 0x40) == 0:
            spc.inp[a - 0x2140] = val & 0xFF
            return
        write(bank, addr, val)

    bus.read, bus.write = rd, wr
    return spc


#  The S-DSP's BRR decode, for a test to read a sample back as the DSP would:
#  blargg's SPC_DSP, written again here rather than taken from the encoder,
#  so that the two are not one mistake.
def brr_samples(ram, addr):
    """Every sample from the BRR at `addr` up to its END block, as the DSP
    decodes them, and the header of each block."""
    out, heads, old, older = [], [], 0, 0
    while True:
        h = ram[addr]
        heads.append(h)
        shift, filt = h >> 4, h >> 2 & 3
        for i in range(16):
            b = ram[addr + 1 + i // 2]
            nib = (b >> 4) if i % 2 == 0 else (b & 15)
            if nib >= 8:
                nib -= 16
            s = (nib << shift) >> 1 if shift <= 12 else (-2048 if nib < 0 else 0)
            p1, p2 = old, older >> 1
            if filt == 1:
                s += p1 >> 1
                s += (-p1) >> 5
            elif filt == 2:
                s += p1
                s -= p2
                s += p2 >> 4
                s += (p1 * -3) >> 6
            elif filt == 3:
                s += p1
                s -= p2
                s += (p1 * -13) >> 7
                s += (p2 * 3) >> 4
            s = max(-32768, min(32767, s))
            s = (s * 2) & 0xFFFF
            s = s - 0x10000 if s & 0x8000 else s
            older, old = old, s
            out.append(s)
        addr += 9
        if h & 1:
            return out, heads
