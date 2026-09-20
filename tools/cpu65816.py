"""
cpu65816.py -- enough of a 65816 to execute the port's option routines.

Not an emulator for the game: no PPU, no APU, no DMA, no interrupts.  What it
does is load the built ROM, map memory the way the cartridge does, and run a
single routine to its RTL so a test can assert on what came back.  That covers
the option hooks, which are pure arithmetic over the option block and a handful
of game variables -- which is precisely the code where a mistake is invisible
until someone plays far enough to notice.

Anything it cannot do raises.  An emulator that quietly guesses at an opcode
would be worse than no emulator, because the tests would still pass.
"""


class Bus:
    """The cartridge's memory map, as snesmap.inc describes it."""

    def __init__(self, rom):
        self.rom = rom
        self.wram = bytearray(0x20000)      # $7E:0000-$7F:FFFF
        self.sram = bytearray(0x2000)       # $6000-$7FFF, aliased in every bank
        self.io = {}                        # $2000-$5FFF, recorded not emulated
        self.mul_a = 0
        self.mul_b = 0

    def _rom(self, bank, addr):
        image = bank & 0x1F                 # 2MB, so the bank number wraps at 32
        off = image * 0x10000 + addr
        return self.rom[off]

    def read(self, bank, addr):
        bank &= 0xFF
        addr &= 0xFFFF
        if bank in (0x7E, 0x7F):
            return self.wram[(bank - 0x7E) * 0x10000 + addr]
        if addr < 0x2000:
            return self.wram[addr]          # low WRAM mirrors $7E:0000
        if 0x4216 <= addr <= 0x4217:
            p = (self.mul_a * self.mul_b) & 0xFFFF
            return p & 0xFF if addr == 0x4216 else p >> 8
        if addr < 0x6000:
            return self.io.get(addr, 0)
        if addr < 0x8000:
            return self.sram[addr - 0x6000]
        return self._rom(bank, addr)

    def write(self, bank, addr, val):
        bank &= 0xFF
        addr &= 0xFFFF
        val &= 0xFF
        if bank in (0x7E, 0x7F):
            self.wram[(bank - 0x7E) * 0x10000 + addr] = val
            return
        if addr < 0x2000:
            self.wram[addr] = val
            return
        if addr == 0x4202:
            self.mul_a = val
            return
        if addr == 0x4203:
            self.mul_b = val
            return
        if addr < 0x6000:
            self.io[addr] = val
            return
        if addr < 0x8000:
            self.sram[addr - 0x6000] = val
            return
        raise RuntimeError("write to ROM at $%02X:%04X" % (bank, addr))


N, V, M, X, D, I, Z, C = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01


class CPU:
    def __init__(self, bus):
        self.bus = bus
        self.a = self.x = self.y = 0
        self.s = 0x01FF
        self.d = 0
        self.pbr = 0
        self.dbr = 0
        self.p = M | X | I
        self.e = True
        self.pc = 0
        self.steps = 0

    # --- helpers ----------------------------------------------------------
    def m8(self):
        return self.e or (self.p & M)

    def x8(self):
        return self.e or (self.p & X)

    def rd(self, bank, addr):
        return self.bus.read(bank, addr)

    def wr(self, bank, addr, v):
        self.bus.write(bank, addr, v)

    def fetch(self):
        v = self.rd(self.pbr, self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch()
        return lo | (self.fetch() << 8)

    def push(self, v):
        self.wr(0, self.s, v & 0xFF)
        self.s -= 1
        if self.e:
            self.s = 0x0100 | (self.s & 0xFF)
        else:
            self.s &= 0xFFFF

    def pull(self):
        self.s += 1
        if self.e:
            self.s = 0x0100 | (self.s & 0xFF)
        else:
            self.s &= 0xFFFF
        return self.rd(0, self.s)

    def setzn(self, v, eight):
        mask = 0x80 if eight else 0x8000
        self.p = (self.p & ~(Z | N)) | (Z if v == 0 else 0) | (N if v & mask else 0)

    # --- addressing -------------------------------------------------------
    def a_imm(self, eight):
        if eight:
            v = self.fetch()
        else:
            v = self.fetch16()
        return v

    def a_abs(self):
        return (self.dbr, self.fetch16())

    def a_absx(self):
        a = self.fetch16()
        return (self.dbr, (a + self.x) & 0xFFFF)

    def a_absy(self):
        a = self.fetch16()
        return (self.dbr, (a + self.y) & 0xFFFF)

    def a_long(self):
        a = self.fetch16()
        return (self.fetch(), a)

    def a_longx(self):
        a = self.fetch16()
        b = self.fetch()
        t = a + self.x
        return (b + (t >> 16), t & 0xFFFF)

    def a_dp(self):
        return (0, (self.d + self.fetch()) & 0xFFFF)

    def a_dpx(self):
        return (0, (self.d + self.fetch() + self.x) & 0xFFFF)

    def a_dpy(self):
        return (0, (self.d + self.fetch() + self.y) & 0xFFFF)

    def a_dpx_ind(self):
        """(dp,X) -- the pointer is picked out of direct page by X, and only
        then dereferenced.  The battle drawing code uses it, which is why the
        harness could not run past DrawBlockBuffer before."""
        p = (self.d + self.fetch() + self.x) & 0xFFFF
        base = self.rd(0, p) | (self.rd(0, (p + 1) & 0xFFFF) << 8)
        return (self.dbr, base)

    def a_dpind(self):
        p = (self.d + self.fetch()) & 0xFFFF
        base = self.rd(0, p) | (self.rd(0, (p + 1) & 0xFFFF) << 8)
        return (self.dbr, base)

    def a_dpindlong(self):
        p = (self.d + self.fetch()) & 0xFFFF
        base = self.rd(0, p) | (self.rd(0, (p + 1) & 0xFFFF) << 8)
        return (self.rd(0, (p + 2) & 0xFFFF), base)

    def a_dpind_y(self):
        p = (self.d + self.fetch()) & 0xFFFF
        base = self.rd(0, p) | (self.rd(0, (p + 1) & 0xFFFF) << 8)
        t = base + self.y
        return (self.dbr + (t >> 16), t & 0xFFFF)

    def a_dpindlong_y(self):
        p = (self.d + self.fetch()) & 0xFFFF
        base = self.rd(0, p) | (self.rd(0, (p + 1) & 0xFFFF) << 8)
        bank = self.rd(0, (p + 2) & 0xFFFF)
        t = base + self.y
        return (bank + (t >> 16), t & 0xFFFF)

    def load(self, ba, eight):
        b, a = ba
        v = self.rd(b, a)
        if not eight:
            v |= self.rd(b, (a + 1) & 0xFFFF) << 8
        return v

    def store(self, ba, v, eight):
        b, a = ba
        self.wr(b, a, v & 0xFF)
        if not eight:
            self.wr(b, (a + 1) & 0xFFFF, (v >> 8) & 0xFF)

    def branch(self, take):
        off = self.fetch()
        if off & 0x80:
            off -= 0x100
        if take:
            self.pc = (self.pc + off) & 0xFFFF

    # --- arithmetic -------------------------------------------------------
    def adc(self, v, eight):
        mask = 0xFF if eight else 0xFFFF
        bit = 0x80 if eight else 0x8000
        a = self.a & mask
        r = a + v + (1 if self.p & C else 0)
        self.p &= ~(C | V)
        if (~(a ^ v) & (a ^ r)) & bit:
            self.p |= V
        if r > mask:
            self.p |= C
        r &= mask
        self.a = (self.a & ~mask) | r if not eight else (self.a & 0xFF00) | r
        self.setzn(r, eight)

    def sbc(self, v, eight):
        mask = 0xFF if eight else 0xFFFF
        self.adc(v ^ mask, eight)

    # --- the interpreter --------------------------------------------------
    def run(self, bank, addr, limit=2_000_000):
        """Call a routine as JSL would, and return when its RTL comes back."""
        self.pbr, self.pc = bank, addr
        #  A return address no real code occupies.  The bank byte is pushed
        #  too, so this works whether the routine ends in RTL or in RTS --
        #  several of them end in RTS, being reached by JSR from the fixed
        #  bank rather than by JSL from another chunk.  Only the address is
        #  tested, because an RTS leaves the bank byte behind.
        self.push(0xFF)
        self.push(0xFF)
        self.push(0xFD)
        while True:
            self.steps += 1
            if self.steps > limit:
                raise RuntimeError("ran away at $%02X:%04X" % (self.pbr, self.pc))
            if self.pc == 0xFFFE:
                return
            self.step()

    def step(self):
        op = self.fetch()
        m8, x8 = self.m8(), self.x8()
        amask = 0xFF if m8 else 0xFFFF

        # loads and stores
        if op == 0xA9: v = self.a_imm(m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xAD: v = self.load(self.a_abs(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xBD: v = self.load(self.a_absx(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xB9: v = self.load(self.a_absy(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xA5: v = self.load(self.a_dp(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xB5: v = self.load(self.a_dpx(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xAF: v = self.load(self.a_long(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xBF: v = self.load(self.a_longx(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xB1: v = self.load(self.a_dpind_y(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xB7: v = self.load(self.a_dpindlong_y(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xA1: v = self.load(self.a_dpx_ind(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xB2: v = self.load(self.a_dpind(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0xA7: v = self.load(self.a_dpindlong(), m8); self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0x8D: self.store(self.a_abs(), self.a, m8)
        elif op == 0x9D: self.store(self.a_absx(), self.a, m8)
        elif op == 0x99: self.store(self.a_absy(), self.a, m8)
        elif op == 0x85: self.store(self.a_dp(), self.a, m8)
        elif op == 0x95: self.store(self.a_dpx(), self.a, m8)
        elif op == 0x8F: self.store(self.a_long(), self.a, m8)
        elif op == 0x9F: self.store(self.a_longx(), self.a, m8)
        elif op == 0x91: self.store(self.a_dpind_y(), self.a, m8)
        elif op == 0x97: self.store(self.a_dpindlong_y(), self.a, m8)
        elif op == 0x81: self.store(self.a_dpx_ind(), self.a, m8)
        elif op == 0x92: self.store(self.a_dpind(), self.a, m8)
        elif op == 0x87: self.store(self.a_dpindlong(), self.a, m8)
        elif op == 0x64: self.store(self.a_dp(), 0, m8)
        elif op == 0x9C: self.store(self.a_abs(), 0, m8)
        elif op == 0xA2: v = self.a_imm(x8); self.x = v; self.setzn(v, x8)
        elif op == 0xAE: v = self.load(self.a_abs(), x8); self.x = v; self.setzn(v, x8)
        elif op == 0xA6: v = self.load(self.a_dp(), x8); self.x = v; self.setzn(v, x8)
        elif op == 0xBE: v = self.load(self.a_absy(), x8); self.x = v; self.setzn(v, x8)
        elif op == 0xB6: v = self.load(self.a_dpy(), x8); self.x = v; self.setzn(v, x8)
        elif op == 0xA0: v = self.a_imm(x8); self.y = v; self.setzn(v, x8)
        elif op == 0xAC: v = self.load(self.a_abs(), x8); self.y = v; self.setzn(v, x8)
        elif op == 0xA4: v = self.load(self.a_dp(), x8); self.y = v; self.setzn(v, x8)
        elif op == 0xBC: v = self.load(self.a_absx(), x8); self.y = v; self.setzn(v, x8)
        elif op == 0xB4: v = self.load(self.a_dpx(), x8); self.y = v; self.setzn(v, x8)
        elif op == 0x8E: self.store(self.a_abs(), self.x, x8)
        elif op == 0x86: self.store(self.a_dp(), self.x, x8)
        elif op == 0x96: self.store(self.a_dpy(), self.x, x8)
        elif op == 0x8C: self.store(self.a_abs(), self.y, x8)
        elif op == 0x84: self.store(self.a_dp(), self.y, x8)
        elif op == 0x94: self.store(self.a_dpx(), self.y, x8)
        # transfers
        elif op == 0xAA: self.x = self.a & (0xFF if x8 else 0xFFFF); self.setzn(self.x, x8)
        elif op == 0xA8: self.y = self.a & (0xFF if x8 else 0xFFFF); self.setzn(self.y, x8)
        elif op == 0x8A: v = self.x & amask; self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0x98: v = self.y & amask; self.a = (self.a & 0xFF00 | v) if m8 else v; self.setzn(v, m8)
        elif op == 0x9B: self.y = self.x; self.setzn(self.y, x8)
        elif op == 0xBB: self.x = self.y; self.setzn(self.x, x8)
        elif op == 0x5B: self.d = self.a & 0xFFFF
        elif op == 0x7B: self.a = self.d; self.setzn(self.a, False)
        # logic and arithmetic
        elif op in (0x29, 0x2D, 0x3D, 0x39, 0x25, 0x2F, 0x3F):
            v = self.a_imm(m8) if op == 0x29 else self.load(
                {0x2D: self.a_abs, 0x3D: self.a_absx, 0x39: self.a_absy,
                 0x25: self.a_dp, 0x2F: self.a_long, 0x3F: self.a_longx}[op](), m8)
            r = (self.a & amask) & v
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op in (0x09, 0x0D, 0x1D, 0x19, 0x05, 0x0F, 0x1F):
            v = self.a_imm(m8) if op == 0x09 else self.load(
                {0x0D: self.a_abs, 0x1D: self.a_absx, 0x19: self.a_absy,
                 0x05: self.a_dp, 0x0F: self.a_long, 0x1F: self.a_longx}[op](), m8)
            r = (self.a & amask) | v
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op in (0x49, 0x4D, 0x5D, 0x59, 0x45, 0x4F, 0x5F):
            v = self.a_imm(m8) if op == 0x49 else self.load(
                {0x4D: self.a_abs, 0x5D: self.a_absx, 0x59: self.a_absy,
                 0x45: self.a_dp, 0x4F: self.a_long, 0x5F: self.a_longx}[op](), m8)
            r = (self.a & amask) ^ v
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op in (0x69, 0x6D, 0x7D, 0x79, 0x65, 0x6F, 0x7F):
            v = self.a_imm(m8) if op == 0x69 else self.load(
                {0x6D: self.a_abs, 0x7D: self.a_absx, 0x79: self.a_absy,
                 0x65: self.a_dp, 0x6F: self.a_long, 0x7F: self.a_longx}[op](), m8)
            self.adc(v, m8)
        elif op in (0xE9, 0xED, 0xFD, 0xF9, 0xE5, 0xEF, 0xFF):
            v = self.a_imm(m8) if op == 0xE9 else self.load(
                {0xED: self.a_abs, 0xFD: self.a_absx, 0xF9: self.a_absy,
                 0xE5: self.a_dp, 0xEF: self.a_long, 0xFF: self.a_longx}[op](), m8)
            self.sbc(v, m8)
        elif op in (0xC9, 0xCD, 0xDD, 0xD9, 0xC5, 0xCF, 0xDF):
            v = self.a_imm(m8) if op == 0xC9 else self.load(
                {0xCD: self.a_abs, 0xDD: self.a_absx, 0xD9: self.a_absy,
                 0xC5: self.a_dp, 0xCF: self.a_long, 0xDF: self.a_longx}[op](), m8)
            r = (self.a & amask) - v
            self.p = (self.p & ~C) | (C if r >= 0 else 0); self.setzn(r & amask, m8)
        elif op in (0xE0, 0xEC, 0xE4):
            v = self.a_imm(x8) if op == 0xE0 else self.load(
                {0xEC: self.a_abs, 0xE4: self.a_dp}[op](), x8)
            xm = 0xFF if x8 else 0xFFFF
            r = (self.x & xm) - v
            self.p = (self.p & ~C) | (C if r >= 0 else 0); self.setzn(r & xm, x8)
        elif op in (0xC0, 0xCC, 0xC4):
            v = self.a_imm(x8) if op == 0xC0 else self.load(
                {0xCC: self.a_abs, 0xC4: self.a_dp}[op](), x8)
            xm = 0xFF if x8 else 0xFFFF
            r = (self.y & xm) - v
            self.p = (self.p & ~C) | (C if r >= 0 else 0); self.setzn(r & xm, x8)
        else:
            self.step2(op, m8, x8, amask)

    def step2(self, op, m8, x8, amask):
        xm = 0xFF if x8 else 0xFFFF
        # shifts and rotates
        if op == 0x0A:
            r = (self.a & amask) << 1
            self.p = (self.p & ~C) | (C if r > amask else 0); r &= amask
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op == 0x4A:
            v = self.a & amask
            self.p = (self.p & ~C) | (C if v & 1 else 0); r = v >> 1
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op == 0x2A:
            v = self.a & amask; r = (v << 1) | (1 if self.p & C else 0)
            self.p = (self.p & ~C) | (C if r > amask else 0); r &= amask
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op == 0x6A:
            v = self.a & amask; c = 1 if self.p & C else 0
            self.p = (self.p & ~C) | (C if v & 1 else 0)
            r = (v >> 1) | (c * ((amask + 1) >> 1))
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op in (0x06, 0x0E, 0x16, 0x1E, 0x26, 0x2E, 0x46, 0x4E, 0x66, 0x6E):
            ba = {0x06: self.a_dp, 0x0E: self.a_abs, 0x16: self.a_dpx, 0x1E: self.a_absx,
                  0x26: self.a_dp, 0x2E: self.a_abs, 0x46: self.a_dp, 0x4E: self.a_abs,
                  0x66: self.a_dp, 0x6E: self.a_abs}[op]()
            v = self.load(ba, m8)
            if op in (0x06, 0x0E, 0x16, 0x1E):
                r = v << 1; self.p = (self.p & ~C) | (C if r > amask else 0)
            elif op in (0x26, 0x2E):
                r = (v << 1) | (1 if self.p & C else 0)
                self.p = (self.p & ~C) | (C if r > amask else 0)
            elif op in (0x46, 0x4E):
                self.p = (self.p & ~C) | (C if v & 1 else 0); r = v >> 1
            else:
                c = 1 if self.p & C else 0
                self.p = (self.p & ~C) | (C if v & 1 else 0)
                r = (v >> 1) | (c * ((amask + 1) >> 1))
            r &= amask; self.store(ba, r, m8); self.setzn(r, m8)
        # inc and dec
        elif op == 0x1A:
            r = ((self.a & amask) + 1) & amask
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op == 0x3A:
            r = ((self.a & amask) - 1) & amask
            self.a = (self.a & 0xFF00 | r) if m8 else r; self.setzn(r, m8)
        elif op == 0xE8: self.x = (self.x + 1) & xm; self.setzn(self.x, x8)
        elif op == 0xCA: self.x = (self.x - 1) & xm; self.setzn(self.x, x8)
        elif op == 0xC8: self.y = (self.y + 1) & xm; self.setzn(self.y, x8)
        elif op == 0x88: self.y = (self.y - 1) & xm; self.setzn(self.y, x8)
        elif op in (0xE6, 0xEE, 0xF6, 0xFE, 0xC6, 0xCE, 0xD6, 0xDE):
            ba = {0xE6: self.a_dp, 0xEE: self.a_abs, 0xF6: self.a_dpx, 0xFE: self.a_absx,
                  0xC6: self.a_dp, 0xCE: self.a_abs, 0xD6: self.a_dpx, 0xDE: self.a_absx}[op]()
            v = self.load(ba, m8)
            r = (v + (1 if op in (0xE6, 0xEE, 0xF6, 0xFE) else -1)) & amask
            self.store(ba, r, m8); self.setzn(r, m8)
        # bit
        elif op in (0x24, 0x2C):
            v = self.load(self.a_dp() if op == 0x24 else self.a_abs(), m8)
            bit = 0x80 if m8 else 0x8000
            self.p = (self.p & ~(N | V | Z))
            if v & bit: self.p |= N
            if v & (bit >> 1): self.p |= V
            if not ((self.a & amask) & v): self.p |= Z
        # branches
        elif op == 0xD0: self.branch(not (self.p & Z))
        elif op == 0xF0: self.branch(bool(self.p & Z))
        elif op == 0x90: self.branch(not (self.p & C))
        elif op == 0xB0: self.branch(bool(self.p & C))
        elif op == 0x10: self.branch(not (self.p & N))
        elif op == 0x30: self.branch(bool(self.p & N))
        elif op == 0x50: self.branch(not (self.p & V))
        elif op == 0x70: self.branch(bool(self.p & V))
        elif op == 0x80: self.branch(True)
        # jumps and calls
        elif op == 0x4C: self.pc = self.fetch16()
        elif op == 0x5C: a = self.fetch16(); self.pbr = self.fetch(); self.pc = a
        elif op == 0x6C:
            p = self.fetch16()
            self.pc = self.rd(0, p) | (self.rd(0, (p + 1) & 0xFFFF) << 8)
        elif op == 0x20:
            a = self.fetch16(); r = (self.pc - 1) & 0xFFFF
            self.push(r >> 8); self.push(r & 0xFF); self.pc = a
        elif op == 0x22:
            a = self.fetch16(); b = self.fetch(); r = (self.pc - 1) & 0xFFFF
            self.push(self.pbr); self.push(r >> 8); self.push(r & 0xFF)
            self.pbr, self.pc = b, a
        elif op == 0x60:
            lo = self.pull(); hi = self.pull(); self.pc = ((hi << 8) | lo) + 1 & 0xFFFF
        elif op == 0x6B:
            lo = self.pull(); hi = self.pull(); self.pbr = self.pull()
            self.pc = (((hi << 8) | lo) + 1) & 0xFFFF
        # stack
        elif op == 0x48:
            if m8: self.push(self.a & 0xFF)
            else: self.push((self.a >> 8) & 0xFF); self.push(self.a & 0xFF)
        elif op == 0x68:
            if m8: v = self.pull(); self.a = (self.a & 0xFF00) | v
            else: v = self.pull() | (self.pull() << 8); self.a = v
            self.setzn(v, m8)
        elif op == 0xDA:
            if x8: self.push(self.x & 0xFF)
            else: self.push((self.x >> 8) & 0xFF); self.push(self.x & 0xFF)
        elif op == 0xFA:
            self.x = self.pull() if x8 else (self.pull() | (self.pull() << 8))
            self.setzn(self.x, x8)
        elif op == 0x5A:
            if x8: self.push(self.y & 0xFF)
            else: self.push((self.y >> 8) & 0xFF); self.push(self.y & 0xFF)
        elif op == 0x7A:
            self.y = self.pull() if x8 else (self.pull() | (self.pull() << 8))
            self.setzn(self.y, x8)
        elif op == 0x8B: self.push(self.dbr)
        elif op == 0xAB: self.dbr = self.pull(); self.setzn(self.dbr, True)
        elif op == 0x4B: self.push(self.pbr)
        elif op == 0x08: self.push(self.p)
        elif op == 0x28: self.p = self.pull()
        elif op == 0x0B: self.push((self.d >> 8) & 0xFF); self.push(self.d & 0xFF)
        elif op == 0x2B: self.d = self.pull() | (self.pull() << 8)
        # flags and mode
        elif op == 0x18: self.p &= ~C
        elif op == 0x38: self.p |= C
        elif op == 0x58: self.p &= ~I
        elif op == 0x78: self.p |= I
        elif op == 0xB8: self.p &= ~V
        elif op == 0xD8: self.p &= ~D
        elif op == 0xF8: self.p |= D
        elif op == 0xC2: self.p &= ~self.fetch()
        elif op == 0xE2: self.p |= self.fetch()
        elif op == 0xFB:
            c = bool(self.p & C); self.p = (self.p & ~C) | (C if self.e else 0)
            self.e = c
            if self.e:
                self.p |= M | X; self.x &= 0xFF; self.y &= 0xFF
                self.s = 0x0100 | (self.s & 0xFF)
        elif op == 0xEA: pass
        else:
            raise NotImplementedError(
                "opcode $%02X at $%02X:%04X" % (op, self.pbr, (self.pc - 1) & 0xFFFF))
