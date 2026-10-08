#!/usr/bin/env python3
"""
randoref.py -- the randomizer's generator, in Python.

The same worlds src/rando.asm builds, from the same seeds, byte for byte.
tools/test_options.py holds the two to that, so this is also the
specification: when they disagree, decide which one is right and fix the
other, rather than nudging either until they agree.

Run it to see a world without playing it:

    python3 tools/randoref.py SuperFinalFantasy.srm      # the saved game's
    python3 tools/randoref.py --seed 12345678 --traps b --shops shuffle --chests shuffle
    python3 tools/randoref.py SuperFinalFantasy.srm --find "heal staff"
    python3 tools/randoref.py --seed 12345678 --zones shuffle --rarity tiered

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
STREAM_CHESTS = 0x43485354      # "CHST"
STREAM_MAGIC = 0x4D414743       # "MAGC"
STREAM_GEAR = 0x424C5253        # "BLRS"
STREAM_ZONES = 0x5A4F4E45       # "ZONE"
STREAM_RARITY = 0x52415245      # "RARE"
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

    def below16(self, n):
        """The same for n in 1..$FFFF, from the low sixteen bits."""
        assert 1 <= n <= 0xFFFF
        m = n - 1
        m |= m >> 1
        m |= m >> 2
        m |= m >> 4
        m |= m >> 8
        while True:
            self.s = xs32(self.s)
            r = self.s & 0xFFFF & m
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


# --- chests --------------------------------------------------------------------
#  lut_Treasure: bank $00's $B100, a chest id's contents.  FFR's ItemLocations
#  marks 14 chests unused, and does not list id 0; no map places any of them.
#  Key items are the ids below item_qty_start ($16), and stay put.
CHESTS_OFF, CHESTS_SHUFFLE = range(2)
CHESTS_MODES = 2
CHEST_NAMES = {"off": CHESTS_OFF, "shuffle": CHESTS_SHUFFLE}
TREASURE = 0x10000 + 0xB100
UNUSED_CHESTS = {0x00, 0x91, 0x92, 0x93, 0x94, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
                 0xC0, 0xC1, 0xC2, 0xC3, 0xFF}
ITEM_QTY_START = 0x16


def rom_chests(rom):
    return bytes(rom[TREASURE:TREASURE + 256])


def moving_chests(table):
    """The chest ids whose contents are dealt, in id order."""
    return [c for c in range(256)
            if c not in UNUSED_CHESTS and table[c] >= ITEM_QTY_START]


def build_chests(rom, seed, chests):
    """Every chest's contents as the cache holds them: 256 bytes by id."""
    table = bytearray(rom_chests(rom))
    if 0 < chests < CHESTS_MODES:
        rng = Stream(seed, STREAM_CHESTS)
        locs = moving_chests(table)
        pool = [table[c] for c in locs]
        for i in range(len(pool) - 1, 0, -1):
            j = rng.below(i + 1)
            pool[i], pool[j] = pool[j], pool[i]
        for c, v in zip(locs, pool):
            table[c] = v
    return bytes(table)


# --- blursings ---------------------------------------------------------------------
#  FFR's RandomWeaponBonus and RandomArmorBonus, one range for both: every
#  piece rolls a bonus from -curse to +bless, weapons first.  The tables are
#  bank $0C's $8000: 40 weapons of 8 bytes, then 40 armour of 4.
GEAR_AT = (1 + 0x0C) * 0x10000 + 0x8000
BLURSE_STEPS = 6


def build_gear(rom, seed, bless, curse):
    """(the tables as blursed, 480 bytes; the 80 bonuses, signed)."""
    t = bytearray(rom[GEAR_AT:GEAR_AT + 480])
    bonus = [0] * 80
    if not (0 <= bless < BLURSE_STEPS and 0 <= curse < BLURSE_STEPS) or not (bless or curse):
        return bytes(t), bonus
    rng = Stream(seed, STREAM_GEAR)
    clamp = lambda v, lo, hi: max(lo, min(hi, v))
    for i in range(80):
        b = rng.below(bless + curse + 1) - curse
        bonus[i] = b
        if not b:
            continue
        if i < 40:
            w = i * 8
            t[w + 0] = clamp(t[w + 0] + 3 * b, 0, 50)    # hit
            t[w + 1] = clamp(t[w + 1] + 2 * b, 1, 255)   # damage
            t[w + 2] = clamp(t[w + 2] + 3 * b, 1, 255)   # crit
        else:
            j = i - 40
            k = 2 if j < 16 else 1                         # body armour
            a = 320 + j * 4
            t[a + 0] = clamp(t[a + 0] - k * b, 0, 255)   # weight
            t[a + 1] = clamp(t[a + 1] + k * b, 1, 255)   # absorb
    return bytes(t), bonus


def blursed_name_bytes(rom, item, b):
    """The name's bytes as drawn: the last two before an icon made the sign
    and the digit, FFR's rule for the icon being a seventh byte above 200
    that is not a space."""
    bank = (1 + 0x0A) * 0x10000
    p = bank + 0xB700 + item * 2
    at = bank + (rom[p] | rom[p + 1] << 8)
    name = bytearray(rom[at:at + 7])
    if b:
        i = 5 if (name[6] > 200 and name[6] != 0xFF) else 6
        name[i] = 0x80 + abs(b)
        name[i - 1] = 0xC1 if b > 0 else 0xC2
    return bytes(name)


# --- where things are ---------------------------------------------------------------
#  The 61 standard maps, decoded the way DecompressMap does it, so a chest can
#  be named by the floor it is on.  The names are FFR's MapIndex (Enums.cs),
#  which follows the ROM's order.
MAP_NAMES = [
    "Coneria", "Pravoka", "Elfland", "Melmond", "Crescent Lake", "Gaia",
    "Onrac", "Lefein", "Coneria Castle 1F", "Elfland Castle",
    "Northwest Castle", "Castle of Ordeals 1F", "Temple of Fiends",
    "Earth Cave B1", "Gurgu Volcano B1", "Ice Cave B1", "Cardia",
    "Bahamut's Cave B1", "Waterfall", "Dwarf Cave", "Matoya's Cave",
    "Sarda's Cave", "Marsh Cave B1", "Mirage Tower 1F", "Coneria Castle 2F",
    "Castle of Ordeals 2F", "Castle of Ordeals 3F", "Marsh Cave B2",
    "Marsh Cave B3", "Earth Cave B2", "Earth Cave B3", "Earth Cave B4",
    "Earth Cave B5", "Gurgu Volcano B2", "Gurgu Volcano B3",
    "Gurgu Volcano B4", "Gurgu Volcano B5", "Ice Cave B2", "Ice Cave B3",
    "Bahamut's Cave B2", "Mirage Tower 2F", "Mirage Tower 3F",
    "Sea Shrine B5", "Sea Shrine B4", "Sea Shrine B3", "Sea Shrine B2",
    "Sea Shrine B1", "Sky Palace 1F", "Sky Palace 2F", "Sky Palace 3F",
    "Sky Palace 4F", "Sky Palace 5F", "Temple of Fiends (past) 1F",
    "Temple of Fiends (past) 2F", "Temple of Fiends (past) 3F",
    "Temple of Fiends (past) Earth", "Temple of Fiends (past) Fire",
    "Temple of Fiends (past) Water", "Temple of Fiends (past) Air",
    "Temple of Fiends (past) Chaos", "Titan's Tunnel",
]
TILESETS = 0x10000 + 0xACC0              # lut_Tilesets: one per map


# --- formations ---------------------------------------------------------------
#  lut_Domains, bank $0B $8000: 128 zones of 8 formation ids.  Zones 0-63 are
#  the overworld's 8x8 grid; 64 up are the standard maps by cur_map, except
#  that the river's halves and the sea use the first three towns' zones.  A
#  battle picks slot 0-3 12/64 of the time each, 4-5 6/64, 6 3/64, 7 1/64.
DOMAINS_AT = (1 + 0x0B) * 0x10000 + 0x8000
FORMS_OFF, FORMS_SHUFFLE, FORMS_TIERED = 0, 1, 2
FORMS_MODES = 3
FORMS_NAMES = {"off": FORMS_OFF, "shuffle": FORMS_SHUFFLE, "tiered": FORMS_TIERED}
ZONES_OFF, ZONES_SHUFFLE, ZONES_RANDOM = 0, 1, 2
ZONES_MODES = 3
ZONES_NAMES = {"off": ZONES_OFF, "shuffle": ZONES_SHUFFLE, "random": ZONES_RANDOM}
STARTING_ZONES = (0x1B, 0x1C, 0x24, 0x2C)       # the land around Coneria
RARITY_CLASSES = ((0, 4), (4, 2), (6, 1), (7, 1))   # first slot, how many
NOT_BOSS = list(range(0x00, 0x73)) + list(range(0x80, 0xF3)) + [0xFE, 0xFF]
TIER_SLOT = (6, 7, 4, 5, 0, 1, 2, 3)            # lightest first, as FFR walks them
TIER_WEIGHT = (1, 1, 3, 3, 6, 6, 6, 6)          # FFR's 8, 24, 48 over 8


def rom_domains(rom):
    return bytes(rom[DOMAINS_AT:DOMAINS_AT + 128 * 8])


#  lut_BattleFormations, bank $0B $8400: 16 bytes a formation.  Enemy ids in
#  bytes 2-5 and their counts in 6-9, minimum in the high nibble and maximum in
#  the low.  A B-side (bit 7 of the formation id) fights only the first two,
#  with the counts in bytes 14-15.  data_EnemyNames, bank $0B $94E0: a pointer
#  per enemy into the same bank.
BANK0B = (1 + 0x0B) * 0x10000
FORMATIONS_AT = BANK0B + 0x8400
ENEMY_NAMES_AT = BANK0B + 0x94E0
SLOT_ODDS = ("12/64", "12/64", "12/64", "12/64", "6/64", "6/64", "3/64", "1/64")


def enemy_name(rom, e):
    p = ENEMY_NAMES_AT + e * 2
    return decode_text(rom[BANK0B + (rom[p] | rom[p + 1] << 8):][:9])


def formation_text(rom, f):
    """Who a formation fights: "2-5 IMP, 0-2 GrIMP"."""
    rec = rom[FORMATIONS_AT + (f & 0x7F) * 16:][:16]
    groups = ([(rec[2], rec[14]), (rec[3], rec[15])] if f & 0x80
              else [(rec[2 + i], rec[6 + i]) for i in range(4)])
    out = []
    for e, q in groups:
        lo, hi = q >> 4, q & 0x0F
        if hi:
            out.append("%s %s" % (lo if lo == hi else "%d-%d" % (lo, hi), enemy_name(rom, e)))
    return ", ".join(out) or "nobody"


def zone_name(z):
    if z < 64:
        return "overworld %d,%d" % (z % 8, z // 8)
    if z - 64 >= len(MAP_NAMES):
        return "no map"
    return {64: "river, north", 65: "river, south", 66: "sea"}.get(z, MAP_NAMES[z - 64])


def build_domains(rom, seed, rarity, zones):
    """Every zone's eight formations as the cache holds them: zones, then
    rarity, each pass from its own stream."""
    d = bytearray(rom_domains(rom))
    if 0 < zones < ZONES_MODES:
        rng = Stream(seed, STREAM_ZONES)
        ok = [z not in STARTING_ZONES and (zones == ZONES_RANDOM or any(d[z * 8:z * 8 + 8]))
              for z in range(128)]
        if zones == ZONES_SHUFFLE:
            #  Each rarity class pooled across the zones, shuffled, dealt back.
            for first, count in RARITY_CLASSES:
                pos = [z * 8 + k for z in range(128) if ok[z] for k in range(first, first + count)]
                for i in range(len(pos) - 1, 0, -1):
                    j = rng.below16(i + 1)
                    d[pos[i]], d[pos[j]] = d[pos[j]], d[pos[i]]
        else:
            for z in range(128):
                if ok[z]:
                    for k in range(8):
                        d[z * 8 + k] = NOT_BOSS[rng.below(len(NOT_BOSS))]
    if 0 < rarity < FORMS_MODES:
        rng = Stream(seed, STREAM_RARITY)
        for z in range(128):
            b = z * 8
            if rarity == FORMS_SHUFFLE:
                for base, n in ((b, 4), (b + 2, 6)):        # slots 0-3, then 2-7
                    for i in range(n - 1, 0, -1):
                        j = rng.below(i + 1)
                        d[base + i], d[base + j] = d[base + j], d[base + i]
            else:
                v, w = [d[b + t] for t in TIER_SLOT], list(TIER_WEIGHT)
                for k in range(8):
                    r, m = rng.below(sum(w)), 0
                    while r >= w[m]:
                        r -= w[m]
                        m += 1
                    d[b + k] = v.pop(m)
                    w.pop(m)
    return bytes(d)
TP_SPEC_MASK, TP_SPEC_TREASURE = 0x1E, 0x08


def nesbank(rom, n):
    o = (n + 1) * 0x10000 + 0x8000
    return rom[o:o + 0x4000]


def decode_rle(src, off, count):
    """DecompressMap: $00-$7F one tile, $80-$FE a tile and a run length (0 is
    256), $FF the end."""
    out = []
    while src[off] != 0xFF and len(out) < count:
        b = src[off]
        if b < 0x80:
            out.append(b)
            off += 1
        else:
            out += [b & 0x7F] * (src[off + 1] or 256)
            off += 2
    return out[:count]


def chest_floors(rom):
    """chest id -> the names of the maps that place it.  The pointer table is
    at the start of bank $04 and the maps run on through $07; a pointer is a
    plain offset into the four banks together."""
    banks = b"".join(nesbank(rom, n) for n in (4, 5, 6, 7))
    props = rom_props(rom)
    where = {}
    for m, name in enumerate(MAP_NAMES):
        p = banks[m * 2] | banks[m * 2 + 1] << 8
        ts = rom[TILESETS + m]
        for t in set(decode_rle(banks, p, 4096)):
            o = ts * 256 + (t & 0x7F) * 2
            if props[o] & TP_SPEC_MASK == TP_SPEC_TREASURE:
                where.setdefault(props[o + 1], []).append(name)
    return where


# --- magic levels ----------------------------------------------------------------
#  Slots and spells are both level * 8 + position, 0..63; positions 0-3 are
#  white and 4-7 black.  FFR un-interleaves the books, shuffles each, and
#  interleaves them again: the k-th white slot gets the k-th white spell of
#  the shuffled list.
MAGIC_OFF, MAGIC_SHUFFLE = range(2)
MAGIC_MODES = 2
MAGIC_NAMES = {"off": MAGIC_OFF, "shuffle": MAGIC_SHUFFLE}


def book_slot(k, black):
    return 8 * (k >> 2) + (k & 3) + (4 if black else 0)


def build_magic(seed, magic):
    """perm (the spell in each slot) and its inverse, 64 bytes each."""
    perm = list(range(64))
    if 0 < magic < MAGIC_MODES:
        rng = Stream(seed, STREAM_MAGIC)
        for black in (False, True):
            book = [book_slot(k, black) for k in range(32)]
            for i in range(31, 0, -1):
                j = rng.below(i + 1)
                a, b = book[i], book[j]
                perm[a], perm[b] = perm[b], perm[a]
    inv = [0] * 64
    for s, sp in enumerate(perm):
        inv[sp] = s
    return bytes(perm), bytes(inv)


#  Item names, for printing: lut_ItemNamePtrTbl in bank $0A at $B700.  The
#  last tile of a weapon or armor name is an icon for its kind.
ICONS = {0xD4: "Sword", 0xD5: "Hammer", 0xD6: "Knife", 0xD7: "Axe",
         0xD8: "Staff", 0xD9: "Nunchuck", 0xDA: "Armor", 0xDB: "Shield",
         0xDC: "Helmet", 0xDD: "Gauntlet", 0xDE: "Bracelet", 0xDF: "Shirt",
         0xE1: "Potion"}


PUNCT = {0xBE: "'", 0xBF: ",", 0xC0: ".", 0xC2: "-", 0xC4: "!", 0xC5: "?"}


GEAR_BONUS = {}       # item id -> bonus, for item_name; set by main()


def item_name(rom, item):
    bank = (1 + 0x0A) * 0x10000
    p = bank + 0xB700 + item * 2
    at = bank + (rom[p] | rom[p + 1] << 8)
    text = bytearray(rom[at:at + 12])
    if 0x1C <= item < 0x6C and GEAR_BONUS.get(item):
        text[:7] = blursed_name_bytes(rom, item, GEAR_BONUS[item])
    return decode_text(text)


def decode_text(text):
    """The menu font's codes as text, up to the terminator."""
    out = ""
    for b in text:
        if not b:
            break
        if 0x80 <= b <= 0x89: out += chr(ord("0") + b - 0x80)
        elif 0x8A <= b <= 0xA3: out += chr(ord("A") + b - 0x8A)
        elif 0xA4 <= b <= 0xBD: out += chr(ord("a") + b - 0xA4)
        elif b == 0xFF: out += " "
        elif b in PUNCT: out += PUNCT[b]
        elif b in ICONS: out += " " + ICONS[b]
        elif b == 0xC1: out += "+"
        else: out += "?"
    return " ".join(out.split())


# --- the save block -----------------------------------------------------------
RANDO_SAVE = 0x60A0
SRAM_SAVE = 0x6400          # SaveGame's copy of unsram
RANDO_SAVE_SIZE = 12


def block_from_srm(srm):
    at = SRAM_SAVE - 0x6000 + (RANDO_SAVE - 0x6000)
    b = srm[at:at + RANDO_SAVE_SIZE]
    return (int.from_bytes(b[0:4], "little"),) + tuple(b[4:RANDO_SAVE_SIZE])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("srm", nargs="?", help="a battery file: show its world")
    ap.add_argument("--seed", help="eight hex digits")
    ap.add_argument("--traps", choices=sorted(TRAP_NAMES), default="off")
    ap.add_argument("--shops", choices=sorted(SHOP_NAMES), default="off")
    ap.add_argument("--chests", choices=sorted(CHEST_NAMES), default="off")
    ap.add_argument("--magic", choices=sorted(MAGIC_NAMES), default="off")
    ap.add_argument("--bless", type=int, default=0, help="max gear blessing, 0..5")
    ap.add_argument("--curse", type=int, default=0, help="min gear curse, 0..5")
    ap.add_argument("--rarity", choices=sorted(FORMS_NAMES), default="off")
    ap.add_argument("--zones", choices=sorted(ZONES_NAMES), default="off")
    ap.add_argument("--find", metavar="NAME",
                    help="only where an item is: every chest and shop selling it")
    ap.add_argument("--rom", default=ROM)
    a = ap.parse_args()
    rom = open(a.rom, "rb").read()
    if a.srm:
        (seed, traps, shops, chests, magic, bless, curse,
         rarity, zones) = block_from_srm(open(a.srm, "rb").read())
    elif a.seed:
        seed, traps, shops, chests, magic, bless, curse, rarity, zones = (
            int(a.seed, 16), TRAP_NAMES[a.traps], SHOP_NAMES[a.shops],
            CHEST_NAMES[a.chests], MAGIC_NAMES[a.magic], a.bless, a.curse,
            FORMS_NAMES[a.rarity], ZONES_NAMES[a.zones])
    else:
        ap.error("give a battery file or --seed")
    print("seed %08X, trap tiles mode %d, shops mode %d, chests mode %d, magic mode %d,"
          " blessing +%d, curse -%d, formation rarity %d, zones %d"
          % (seed, traps, shops, chests, magic, bless, curse, rarity, zones))
    _, bonus = build_gear(rom, seed, bless, curse)
    GEAR_BONUS.update({0x1C + i: b for i, b in enumerate(bonus)})
    if any(bonus) and not a.find:
        print("  blursed: " + ", ".join(item_name(rom, 0x1C + i)
                                         for i, b in enumerate(bonus) if b))
    perm, _ = build_magic(seed, magic)
    if magic:
        for level in range(8):
            names = [item_name(rom, 0xB0 + perm[level * 8 + p]) for p in range(8)]
            print("  L%d  white %-23s black %s" % (level + 1, " ".join(names[:4]),
                                                  " ".join(names[4:])))
    vanilla, dealt = rom_chests(rom), build_chests(rom, seed, chests)
    floors = chest_floors(rom)
    if a.find:
        want = a.find.lower()
        hits = 0
        for c in range(256):
            if c in floors and want in item_name(rom, dealt[c]).lower():
                print("  %-16s chest $%02X  %s" % (item_name(rom, dealt[c]), c,
                                                    " / ".join(floors[c])))
                hits += 1
        rows = build_shops(rom, seed, shops)
        for first, kind in zip(SHOP_TYPES, ("weapon", "armor", "item")):
            for s in range(first, first + 10):
                for i in row_list(rows[s * 8:s * 8 + 8]):
                    if shop_ptr(rom, s) != shop_ptr(rom, 0) and want in item_name(rom, i).lower():
                        print("  %-16s %s %s shop" % (item_name(rom, i),
                                                      TOWNS[s - 10 if 11 <= s <= 20 else s], kind))
                        hits += 1
        if not hits:
            print("  nothing called %r in any chest or shop" % a.find)
        return
    for c in range(256):
        if dealt[c] != vanilla[c]:
            print("  chest $%02X  %-16s (was %-16s)  %s"
                  % (c, item_name(rom, dealt[c]), item_name(rom, vanilla[c]),
                     " / ".join(floors.get(c, ["?"]))))
    rows = build_shops(rom, seed, shops)
    for first, kind in zip(SHOP_TYPES, ("weapon", "armor", "item")):
        for s in range(first, first + 10):
            if shop_ptr(rom, s) == shop_ptr(rom, 0):
                continue
            names = [item_name(rom, i) for i in row_list(rows[s * 8:s * 8 + 8])]
            town = TOWNS[s - 10 if 11 <= s <= 20 else s]   # armor: as weapons
            print("  %-13s %-6s  %s" % (town, kind, ", ".join(names)))
    was, now = rom_domains(rom), build_domains(rom, seed, rarity, zones)
    for z in range(128):
        if was[z * 8:z * 8 + 8] != now[z * 8:z * 8 + 8]:
            print("  zone $%02X  %s" % (z, zone_name(z)))
            for k in range(8):
                f, v = now[z * 8 + k], was[z * 8 + k]
                line = "    %-5s  $%02X %-34s%s" % (SLOT_ODDS[k], f, formation_text(rom, f),
                                                    "" if f == v else "  was $%02X %s"
                                                    % (v, formation_text(rom, v)))
                print(line.rstrip())
    src = rom_props(rom)
    out = build_props(rom, seed, traps)
    for i in trap_offsets(src):
        ts, tile = divmod(i // 2, 128)
        print("  tileset %d tile $%02X: formation $%02X -> $%02X"
              % (ts, tile, src[i + 1], out[i + 1]))


if __name__ == "__main__":
    main()
