#!/usr/bin/env python3
"""
randoref.py -- the randomizer's generator, in Python.

The same worlds src/rando.asm builds, from the same seeds, byte for byte.
tools/test_options.py holds the two to that, so this is also the
specification: when they disagree, decide which one is right and fix the
other, rather than nudging either until they agree.

Run it to see a world without playing it:

    python3 tools/randoref.py SuperFinalFantasy.srm      # the saved game's
    python3 tools/randoref.py --seed 12345678 --traps b   # any other

It reads the cartridge's tables from the built ROM, so build first.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROM = os.path.join(ROOT, "SuperFinalFantasy.sfc")

M32 = 0xFFFFFFFF


# --- the PRNG ---------------------------------------------------------------
def xs32(x):
    """One step of Marsaglia's xorshift32, triple (13, 17, 5)."""
    x ^= (x << 13) & M32
    x ^= x >> 17
    x ^= (x << 5) & M32
    return x


#  Each feature's stream constant, XORed into the seed.
STREAM_TRAPS = 0x54524150       # "TRAP"
WARMUP = 8


class Stream:
    """A feature's draws: seed ^ constant, nudged off zero, warmed up."""

    def __init__(self, seed, const):
        s = (seed ^ const) & M32
        if s == 0:
            s = 1           # xorshift never leaves zero
        for _ in range(WARMUP):
            s = xs32(s)
        self.s = s

    def below(self, n):
        """Uniform in [0, n), n in 1..255: mask and reject, never modulo."""
        assert 1 <= n <= 255
        m = n - 1
        m |= m >> 1
        m |= m >> 2
        m |= m >> 4
        while True:
            self.s = xs32(self.s)
            r = self.s & 0xFF & m
            if r < n:
                return r


# --- the cartridge's tables -------------------------------------------------
#  NES bank N sits at image offset (N+1)*$10000 + $8000; the tile property
#  tables are bank $00's $8800, eight tilesets of 128 two-byte tiles.
PROPS_AT = 0x10000 + 0x8800
PROPS_SIZE = 8 * 256
TP_SPEC_BATTLE = 0x0A


def rom_props(rom):
    return bytes(rom[PROPS_AT:PROPS_AT + PROPS_SIZE])


def is_trap(props, i):
    """FFR's IsNonBossTrapTile: a battle tile on formation 1..$72."""
    return props[i] == TP_SPEC_BATTLE and 0 < props[i + 1] < 0x73


def trap_offsets(props):
    return [i for i in range(0, PROPS_SIZE, 2) if is_trap(props, i)]


# --- trap tiles ---------------------------------------------------------------
TRAPS_OFF, TRAPS_SHUFFLE, TRAPS_ASIDE, TRAPS_BSIDE, TRAPS_BOTH = range(5)
TRAPS_MODES = 5
TRAP_NAMES = {"off": TRAPS_OFF, "shuffle": TRAPS_SHUFFLE, "a": TRAPS_ASIDE,
              "b": TRAPS_BSIDE, "both": TRAPS_BOTH}

ASIDE = [f for f in range(0x01, 0x73) if f != 0x56]     # all but WarMECH
BSIDE = list(range(0x80, 0xF3)) + [0xFF]


def build_props(rom, seed, traps):
    """The eight property tables as the cache holds them."""
    src = rom_props(rom)
    out = bytearray(src)
    #  Random-encounter tiles: $80 -> $00, for SMMove_Battle's BNE.
    for i in range(0, PROPS_SIZE, 2):
        if out[i] == TP_SPEC_BATTLE and out[i + 1] & 0x80:
            out[i + 1] = 0
    if not (0 < traps < TRAPS_MODES):
        return bytes(out)

    rng = Stream(seed, STREAM_TRAPS)
    where = trap_offsets(src)
    if traps == TRAPS_SHUFFLE:
        pool = [src[i + 1] for i in where]
    else:
        pool = []
        if traps in (TRAPS_ASIDE, TRAPS_BOTH):
            pool += ASIDE
        if traps in (TRAPS_BSIDE, TRAPS_BOTH):
            pool += BSIDE
    for i in where:
        if not pool:
            continue
        r = rng.below(len(pool))
        out[i + 1] = pool[r]
        pool[r] = pool[-1]
        pool.pop()
    return bytes(out)


# --- the save block -----------------------------------------------------------
RANDO_SAVE = 0x60A0
SRAM_SAVE = 0x6400          # SaveGame's copy of unsram
RANDO_SAVE_SIZE = 5


def block_from_srm(srm):
    at = SRAM_SAVE - 0x6000 + (RANDO_SAVE - 0x6000)
    b = srm[at:at + RANDO_SAVE_SIZE]
    return int.from_bytes(b[0:4], "little"), b[4]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("srm", nargs="?", help="a battery file: show its world")
    ap.add_argument("--seed", help="eight hex digits")
    ap.add_argument("--traps", choices=sorted(TRAP_NAMES), default="off")
    ap.add_argument("--rom", default=ROM)
    a = ap.parse_args()
    rom = open(a.rom, "rb").read()
    if a.srm:
        seed, traps = block_from_srm(open(a.srm, "rb").read())
    elif a.seed:
        seed, traps = int(a.seed, 16), TRAP_NAMES[a.traps]
    else:
        ap.error("give a battery file or --seed")
    print("seed %08X, trap tiles mode %d" % (seed, traps))
    src = rom_props(rom)
    out = build_props(rom, seed, traps)
    for i in trap_offsets(src):
        ts, tile = divmod(i // 2, 128)
        print("  tileset %d tile $%02X: formation $%02X -> $%02X"
              % (ts, tile, src[i + 1], out[i + 1]))


if __name__ == "__main__":
    main()
