#!/usr/bin/env python3
"""
randoref.py -- the randomizer's generator, in Python.

The same worlds src/rando.asm builds, from the same seeds, byte for byte.
tools/test_options.py holds the two to that, so this is also the
specification: when they disagree, decide which one is right and fix the
other, rather than nudging either until they agree.

Run it to see a world without playing it:

    python3 tools/randoref.py SuperFinalFantasy.srm      # the saved game's
    python3 tools/randoref.py --seed 12345678 --traps b --shops shuffle

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
STREAM_SHOPS = 0x53484F50       # "SHOP"
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


# --- shops ---------------------------------------------------------------------
#  lut_ShopData: bank $0E's $8300, a pointer per shop_id (0..70) into
#  zero-terminated lists in the same bank.  Shop 0's is the shared empty list.
SHOPS_OFF, SHOPS_SHUFFLE = range(2)
SHOPS_MODES = 2
SHOP_NAMES = {"off": SHOPS_OFF, "shuffle": SHOPS_SHUFFLE}
SHOPROWS = 71
BANK0E = (1 + 0x0E) * 0x10000
SHOPDATA = 0x8300
#  The three types FFR deals, by their first shop_id: weapons 1-10, armor
#  11-20, items 61-70 (the Caravan is 70).
SHOP_TYPES = (1, 11, 61)
#  Where each one is, from FFR's ShopPrototypes (whose index is shop_id - 1).
TOWNS = {1: "Coneria", 2: "Pravoka", 3: "Elfland", 4: "Melmond",
         5: "Crescent Lake", 6: "Gaia", 61: "Coneria", 62: "Pravoka",
         63: "Elfland", 64: "Crescent Lake", 65: "Gaia", 66: "Onrac",
         70: "Caravan"}


def shop_ptr(rom, s):
    at = BANK0E + SHOPDATA + 2 * s
    return rom[at] | rom[at + 1] << 8


def rom_shoprows(rom):
    """Each shop's five bytes as LoadShopInventory copied them, padded to 8."""
    out = bytearray()
    for s in range(SHOPROWS):
        p = BANK0E + shop_ptr(rom, s)
        out += bytes(rom[p:p + 5]) + bytes(3)
    return out


def row_list(row):
    out = []
    for b in row[:5]:
        if b == 0:
            break
        out.append(b)
    return out


def deal_type(rows, rng, first, rom):
    """FFR's ShuffleShopType for the ten shop_ids from first.  Returns how many
    attempts it took."""
    shops = [s for s in range(first, first + 10) if shop_ptr(rom, s) != shop_ptr(rom, 0)]
    orig = [x for s in shops for x in row_list(rows[s * 8:s * 8 + 8])]
    attempts = 0
    while True:
        attempts += 1
        deal = {s: [] for s in shops}
        a = list(orig)
        for i in range(len(a) - 1, 0, -1):
            j = rng.below(i + 1)
            a[i], a[j] = a[j], a[i]
        e = 0
        for s in shops:
            deal[s].append(a[e])
            e += 1
        stuck = False
        while e < len(a):
            elig = [s for s in shops if len(deal[s]) < 5 and a[e] not in deal[s]]
            if not elig:
                stuck = True
                break
            deal[elig[rng.below(len(elig))]].append(a[e])
            e += 1
        if not stuck:
            break
    for s in shops:
        rows[s * 8:s * 8 + 5] = bytes(deal[s] + [0] * (5 - len(deal[s])))
    return attempts


def build_shops(rom, seed, shops, attempts=None):
    """Every shop's row as the cache holds them: 71 rows of 8 bytes.  If
    attempts is a list, each type's attempt count is appended to it."""
    rows = rom_shoprows(rom)
    if 0 < shops < SHOPS_MODES:
        rng = Stream(seed, STREAM_SHOPS)
        for first in SHOP_TYPES:
            n = deal_type(rows, rng, first, rom)
            if attempts is not None:
                attempts.append(n)
    return bytes(rows)


#  Item names, for printing: lut_ItemNamePtrTbl in bank $0A at $B700.  The
#  last tile of a weapon or armor name is an icon for its kind.
ICONS = {0xD4: "Sword", 0xD5: "Hammer", 0xD6: "Knife", 0xD7: "Axe",
         0xD8: "Staff", 0xD9: "Nunchuck", 0xDA: "Armor", 0xDB: "Shield",
         0xDC: "Helmet", 0xDD: "Gauntlet", 0xDE: "Bracelet", 0xDF: "Shirt",
         0xE1: "Potion"}


def item_name(rom, item):
    bank = (1 + 0x0A) * 0x10000
    p = bank + 0xB700 + item * 2
    at = bank + (rom[p] | rom[p + 1] << 8)
    out = ""
    while rom[at] and len(out) < 12:
        b = rom[at]
        if 0x80 <= b <= 0x89: out += chr(ord("0") + b - 0x80)
        elif 0x8A <= b <= 0xA3: out += chr(ord("A") + b - 0x8A)
        elif 0xA4 <= b <= 0xBD: out += chr(ord("a") + b - 0xA4)
        elif b == 0xFF: out += " "
        elif b in ICONS: out += " " + ICONS[b]
        else: out += "?"
        at += 1
    return " ".join(out.split())


# --- the save block -----------------------------------------------------------
RANDO_SAVE = 0x60A0
SRAM_SAVE = 0x6400          # SaveGame's copy of unsram
RANDO_SAVE_SIZE = 6


def block_from_srm(srm):
    at = SRAM_SAVE - 0x6000 + (RANDO_SAVE - 0x6000)
    b = srm[at:at + RANDO_SAVE_SIZE]
    return int.from_bytes(b[0:4], "little"), b[4], b[5]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("srm", nargs="?", help="a battery file: show its world")
    ap.add_argument("--seed", help="eight hex digits")
    ap.add_argument("--traps", choices=sorted(TRAP_NAMES), default="off")
    ap.add_argument("--shops", choices=sorted(SHOP_NAMES), default="off")
    ap.add_argument("--rom", default=ROM)
    a = ap.parse_args()
    rom = open(a.rom, "rb").read()
    if a.srm:
        seed, traps, shops = block_from_srm(open(a.srm, "rb").read())
    elif a.seed:
        seed, traps, shops = int(a.seed, 16), TRAP_NAMES[a.traps], SHOP_NAMES[a.shops]
    else:
        ap.error("give a battery file or --seed")
    print("seed %08X, trap tiles mode %d, shops mode %d" % (seed, traps, shops))
    rows = build_shops(rom, seed, shops)
    for first, kind in zip(SHOP_TYPES, ("weapon", "armor", "item")):
        for s in range(first, first + 10):
            if shop_ptr(rom, s) == shop_ptr(rom, 0):
                continue
            names = [item_name(rom, i) for i in row_list(rows[s * 8:s * 8 + 8])]
            town = TOWNS[s - 10 if 11 <= s <= 20 else s]   # armor: as weapons
            print("  %-13s %-6s  %s" % (town, kind, ", ".join(names)))
    src = rom_props(rom)
    out = build_props(rom, seed, traps)
    for i in trap_offsets(src):
        ts, tile = divmod(i // 2, 128)
        print("  tileset %d tile $%02X: formation $%02X -> $%02X"
              % (ts, tile, src[i + 1], out[i + 1]))


if __name__ == "__main__":
    main()
