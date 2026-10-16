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
STREAM_RUNS = 0x52554E53        # "RUNS"
STREAM_SURPRISE = 0x53555250    # "SURP"
STREAM_TOUCH = 0x54554348       # "TUCH"
STREAM_SCRIPTS = 0x53435250     # "SCRP"
STREAM_BSCRIPTS = 0x42534352    # "BSCR"
STREAM_SKILLS = 0x534B494C      # "SKIL"
STREAM_BSKILLS = 0x42534B4C     # "BSKL"
STREAM_RNG = 0x524E4754         # "RNGT"
STREAM_ORDEALS = 0x4F52444C     # "ORDL"
STREAM_KEYS = 0x4B455953        # "KEYS"
STREAM_CASTER = 0x43415354      # "CAST"
STREAM_ITEMMAGIC = 0x494D4147   # "IMAG"
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


#  FFR's Early Ordeals (EnableEarlyOrdeals): the Castle tileset's two thrones,
#  the only crown tiles, lose their special code and are plain teleports.
EARLY_ORDEALS = 0x08
TS_CASTLE = 1
THRONE_TILES = (0x61, 0x62)


def build_props(rom, seed, traps, early=0):
    """The eight property tables as the cache holds them."""
    src = rom_props(rom)
    out = bytearray(src)
    #  Random-encounter tiles: $80 -> $00, for SMMove_Battle's BNE.
    for i in range(0, PROPS_SIZE, 2):
        if out[i] == TP_SPEC_BATTLE and out[i + 1] & 0x80:
            out[i + 1] = 0
    if early & EARLY_ORDEALS:
        for t in THRONE_TILES:
            out[TS_CASTLE * 256 + t * 2] &= ~TP_SPEC_MASK & 0xFF
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


def deal_type(rows, rng, first, rom, caravan_fixed=False):
    """FFR's ShuffleShopType for the ten shop_ids from first.  Returns how many
    attempts it took.  With placement in, the caravan is not dealt: its one
    item is placement's (build_rewards)."""
    shops = [s for s in range(first, first + 10) if shop_ptr(rom, s) != shop_ptr(rom, 0)
             and not (caravan_fixed and s == SHOP_CARAVAN)]
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


SHOP_CARAVAN = 70


def build_shops(rom, seed, shops, attempts=None, caravan=None):
    """Every shop's row as the cache holds them: 71 rows of 8 bytes.  If
    attempts is a list, each type's attempt count is appended to it.  With
    caravan, placement's item for it, the caravan sells that alone."""
    rows = rom_shoprows(rom)
    if 0 < shops < SHOPS_MODES:
        rng = Stream(seed, STREAM_SHOPS)
        for first in SHOP_TYPES:
            n = deal_type(rows, rng, first, rom, caravan is not None)
            if attempts is not None:
                attempts.append(n)
    if caravan is not None:
        rows[SHOP_CARAVAN * 8:SHOP_CARAVAN * 8 + 5] = bytes([caravan, 0, 0, 0, 0])
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
            t[a + 0] = clamp(t[a + 0] - k * b, 0, 255)   # evade penalty, FFR's weight
            t[a + 1] = clamp(t[a + 1] + k * b, 1, 255)   # absorb
    return bytes(t), bonus


# --- item magic -------------------------------------------------------------------
#  FFR's ShuffleItemMagic: every item that casts a spell casts another, dealt
#  from a pool, weapons first and then armour as FFR concatenates them; the
#  item is named for it.  The modes are the high field of RANDO_MAGIC.
ITEMMAGIC_OFF, ITEMMAGIC_SHUFFLE, ITEMMAGIC_BALANCED = range(3)
ITEMMAGIC_SHIFT = 4
MAGIC_AT = GEAR_AT + 480                    # lut_MagicData, after the gear


def balanced_drops(d):
    """GetBalancedSpells' removals, on a record's bytes: 1 effectivity,
    2 element, 3 target, 4 routine."""
    eff, elem, tgt, rt = d[1], d[2], d[3], d[4]
    return ((rt == 0x0D and tgt != 0x04) or rt == 0x0C
            or (rt == 0x01 and eff > 55 and elem == 0)
            or (rt == 0x01 and eff > 70 and tgt == 0x01)
            or (rt == 0x01 and eff > 100) or (rt == 0x01 and eff < 20)
            or (rt == 0x08 and eff & 0x50 == 0) or rt == 0x0F
            or (rt == 0x02 and eff > 120)
            or (rt == 0x12 and eff & 0x03 and elem == 0)
            or (rt == 0x03 and eff & 0xD3 == 0) or (rt == 0x12 and eff & 0xD3 == 0)
            or (rt == 0x10 and eff > 80) or (rt == 0x09 and eff > 32)
            or (rt == 0x0A and eff == 0xFF))


def itemmagic_pool(records, mode):
    """The spells mode deals from, in spell order: every one with a battle
    routine (GetAllSpells), less balanced_drops for Balanced."""
    out = []
    for s in range(64):
        d = records[s * 8:s * 8 + 8]
        if d[4] == 0 or (mode == ITEMMAGIC_BALANCED and balanced_drops(d)):
            continue
        out.append(s)
    return out


def gear_spell_at(g):
    """Where gear g's spell byte is in the 480-byte tables."""
    return g * 8 + 3 if g < 40 else 320 + (g - 40) * 4 + 3


def build_itemmagic(rom, seed, mode):
    """{gear 0..79: its spell byte, 1-based}, for the items that cast one on
    the cartridge.  Fisher-Yates over the pool as far as the items go, so
    each item's spell is distinct, as FFR's shuffle-and-zip makes it."""
    if mode not in (ITEMMAGIC_SHUFFLE, ITEMMAGIC_BALANCED):
        return {}
    pool = itemmagic_pool(rom[MAGIC_AT:MAGIC_AT + 512], mode)
    items = [g for g in range(80) if rom[GEAR_AT + gear_spell_at(g)]]
    rng = Stream(seed, STREAM_ITEMMAGIC)
    deal = {}
    for k, g in enumerate(items):
        if k >= len(pool):
            break
        j = k + rng.below(len(pool) - k)
        pool[k], pool[j] = pool[j], pool[k]
        deal[g] = pool[k] + 1
    return deal


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
ZONES_OFF, ZONES_LIGHT, ZONES_SHUFFLE, ZONES_RANDOM = 0, 1, 2, 3
ZONES_MODES = 4
ZONES_NAMES = {"off": ZONES_OFF, "light": ZONES_LIGHT, "shuffle": ZONES_SHUFFLE,
               "random": ZONES_RANDOM}
STARTING_ZONES = (0x1B, 0x1C, 0x24, 0x2C)       # the land around Coneria
RARITY_CLASSES = ((0, 4), (4, 2), (6, 1), (7, 1))   # first slot, how many
LIGHT_CLASSES = ((0, 1), (3, 1), (5, 1), (6, 1))    # two common, an uncommon, a rare
WARMECH = 0x56                                  # never moved by Light or Shuffle
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


#  Unrunnable fights and surprise rates: byte $0C of a formation record is its
#  surprise rate, bit 0 of $0D its no-run flag, for both sides.  The cache
#  holds the flag per side (formation id, side in bit 7) and the rate per
#  formation.  0-114 are normal; 115-123 fiends and Chaos; 124-127 Vampire,
#  Astos, the pirates and Garland.
RUNS_OFF, RUNS_SHUFFLE = 0, 1
RUNS_MODES = 2
RUNS_NAMES = {"off": RUNS_OFF, "shuffle": RUNS_SHUFFLE}
RUNS_COUNT = 26                 # vanilla's 13 unrunnable normal formations, both sides
SURPRISE_OFF, SURPRISE_SHUFFLE = 0, 1
SURPRISE_MODES = 2
SURPRISE_NAMES = {"off": SURPRISE_OFF, "shuffle": SURPRISE_SHUFFLE}
NORMAL_FORMS, CHAOS_FORM = 115, 123


def build_runs(rom, seed, runs):
    """1 for every side that cannot be run from, 256 bytes by formation id."""
    t = bytearray(256)
    for f in range(128):
        t[f] = t[0x80 | f] = rom[FORMATIONS_AT + f * 16 + 0x0D] & 1
    if 0 < runs < RUNS_MODES:
        #  FFR's pool, cleared as it is built: A-sides 1-114, B-sides 0-114,
        #  the last four's B-sides.  Then RUNS_COUNT drawn without replacement.
        rng = Stream(seed, STREAM_RUNS)
        pool = []
        for f in range(NORMAL_FORMS):
            t[f] = t[0x80 | f] = 0
            if f:
                pool.append(f)
        pool += [0x80 | f for f in range(NORMAL_FORMS)]
        for f in range(CHAOS_FORM + 1, 128):
            t[0x80 | f] = 0
            pool.append(0x80 | f)
        for _ in range(RUNS_COUNT):
            j = rng.below(len(pool))
            t[pool[j]] = 1
            pool[j] = pool[-1]
            pool.pop()
    return bytes(t)


def build_surprise(rom, seed, surprise):
    """Every formation's surprise rate, 128 bytes."""
    t = bytearray(rom[FORMATIONS_AT + f * 16 + 0x0C] for f in range(128))
    if 0 < surprise < SURPRISE_MODES:
        rng = Stream(seed, STREAM_SURPRISE)
        for i in range(NORMAL_FORMS - 1, 0, -1):
            j = rng.below(i + 1)
            t[i], t[j] = t[j], t[i]
    return bytes(t)


# --- enemies: touches, scripts, skills & spells -------------------------------------
#  data_EnemyStats, bank $0C $8520: 128 records of 20 bytes; byte 7 the script
#  id ($FF none), $0E the touch's element, $0F its ailment.  lut_EnemyAi, bank
#  $0C $9020: 44 scripts of 16 bytes -- spell chance, skill chance, 8 spells,
#  a $FF, 4 skills, a $FF.  Enemies 0-117 are normal, 15 the pirates; 118
#  WarMECH, 119-126 the fiends and their refights alternately, 127 Chaos.
ENEMIES_AT = (1 + 0x0C) * 0x10000 + 0x8520
ENEMYAI_AT = (1 + 0x0C) * 0x10000 + 0x9020
STATUS_OFF, STATUS_SHUFFLE = 0, 1
STATUS_MODES = 2
STATUS_NAMES = {"off": STATUS_OFF, "shuffle": STATUS_SHUFFLE}
AI_OFF, AI_ENEMIES, AI_BOSSES, AI_BOTH = 0, 1, 2, 3
AI_MODES = 4
AI_NAMES = {"off": AI_OFF, "enemies": AI_ENEMIES, "bosses": AI_BOSSES, "both": AI_BOTH}
PIRATES = 15
FIENDS = (119, 121, 123, 125)                   # the overworld fiends
BIG_BOSSES = (118, 120, 122, 124, 126, 127)     # WarMECH, the refights, Chaos
NORMAL_SCRIPTS = tuple(range(32)) + (33, 43)
FIEND_SCRIPTS = (34, 36, 38, 40)
BIG_SCRIPTS = (32, 35, 37, 39, 41, 42)
NUKES = (57, 60)                                # FADE, NUKE: FFR's FindSpells
NUCLEAR = 0x14
CRACK_SCRIPT, TOXIC_SCRIPT = 7, 27              # FFR takes two of each out


def skill_name(rom, k):
    """An enemy skill's name: lut_EnemyAttack, bank $0A $B600."""
    b = (1 + 0x0A) * 0x10000
    p = b + 0xB600 + 2 * k
    return decode_text(rom[b + (rom[p] | rom[p + 1] << 8):][:12])


AILMENTS = ("dead", "stone", "poison", "dark", "stun", "sleep", "mute", "confuse")


def touch_text(elem, ail):
    names = [n for i, n in enumerate(AILMENTS) if ail >> i & 1]
    return "%s (element $%02X)" % ("+".join(names) or "none", elem)


def script_text(rom, rec):
    spells = [item_name(rom, 0xB0 + x) for x in rec[2:10] if x != 0xFF]
    skills = [skill_name(rom, x) for x in rec[11:15] if x != 0xFF]
    return "spells %d: %s; skills %d: %s" % (rec[0], " ".join(spells) or "-", rec[1],
                                              " ".join(skills) or "-")


def build_touch(rom, seed, status):
    """Every enemy's touch, element then ailment, 256 bytes."""
    t = bytearray()
    for e in range(128):
        t += rom[ENEMIES_AT + e * 20 + 0x0E:][:2]
    if 0 < status < STATUS_MODES:
        rng = Stream(seed, STREAM_TOUCH)
        es = [e for e in range(128) if e != PIRATES]
        for i in range(len(es) - 1, 0, -1):
            j = rng.below(i + 1)
            a, b = es[i] * 2, es[j] * 2
            t[a:a + 2], t[b:b + 2] = t[b:b + 2], t[a:a + 2]
    return bytes(t)


def _fisher_yates(xs, rng):
    for i in range(len(xs) - 1, 0, -1):
        j = rng.below(i + 1)
        xs[i], xs[j] = xs[j], xs[i]


def _bucketize(xs, count, size, rng):
    """FFR's Bucketize without its min2: one each in order, then the rest
    each to a random bucket with room."""
    out = [[x] for x in xs[:count]]
    i = count
    while i < len(xs):
        b = rng.below(count)
        if len(out[b]) < size:
            out[b].append(xs[i])
            i += 1
    return out


def _deal_group(table, group, rng, opening=True):
    """FFR's ShuffleIndexedSkillsSpells, No Consecutive Nukes on, No Empty
    Scripts off: pool the group's spells and skills, shuffle them and the
    chances, deal the pools into the scripts that cast, and deal again while
    any list has two nukes running or opens with NUKE and NUCLEAR both."""
    rec = lambda g, k: g * 16 + k
    spells = [table[rec(g, 2 + k)] for g in group for k in range(8) if table[rec(g, 2 + k)] != 0xFF]
    skills = [table[rec(g, 11 + k)] for g in group for k in range(4) if table[rec(g, 11 + k)] != 0xFF]
    sch = [table[rec(g, 0)] for g in group]
    kch = [table[rec(g, 1)] for g in group]
    nsp, nsk = sum(1 for c in sch if c), sum(1 for c in kch if c)
    while True:
        _fisher_yates(spells, rng)
        _fisher_yates(skills, rng)
        sb = _bucketize(spells, nsp, 8, rng)
        kb = _bucketize(skills, nsk, 4, rng)
        _fisher_yates(sch, rng)
        _fisher_yates(kch, rng)
        reroll, si, ki, out = False, 0, 0, []
        for i in range(len(group)):
            r = [sch[i], kch[i]] + [0xFF] * 14
            start = 0
            if sch[i]:
                prev = False
                for j, x in enumerate(sb[si]):
                    nuke = x in NUKES
                    reroll |= nuke and prev
                    prev = nuke
                    r[2 + j] = x
                start |= sb[si][0] in NUKES
                si += 1
            if kch[i]:
                prev = False
                for j, x in enumerate(kb[ki]):
                    nuke = x == NUCLEAR
                    reroll |= nuke and prev
                    prev = nuke
                    r[11 + j] = x
                start |= (kb[ki][0] == NUCLEAR) << 1
                ki += 1
            reroll |= opening and start == 3
            out.append(r)
        if not reroll:
            break
    for g, r in zip(group, out):
        table[g * 16:g * 16 + 16] = bytes(r)


def build_ai(rom, seed, scripts, skills, opening=True):
    """Each enemy's script id (128 bytes) and the 44 scripts (704).  opening
    False drops the NUKE-and-NUCLEAR opening rule, for the test that finds a
    seed where it matters."""
    eai = bytearray(rom[ENEMIES_AT + e * 20 + 7] for e in range(128))
    table = bytearray(rom[ENEMYAI_AT:ENEMYAI_AT + 44 * 16])
    if not 0 <= scripts < AI_MODES:
        scripts = AI_OFF
    if not 0 <= skills < AI_MODES:
        skills = AI_OFF
    if scripts & AI_ENEMIES:
        #  The normal enemies trade script ids, the pirates sitting out.
        rng = Stream(seed, STREAM_SCRIPTS)
        es = [e for e in range(118) if e != PIRATES]
        ids = [eai[e] for e in es]
        _fisher_yates(ids, rng)
        for e, v in zip(es, ids):
            eai[e] = v
    if scripts & AI_BOSSES:
        rng = Stream(seed, STREAM_BSCRIPTS)
        for group in (FIENDS, BIG_BOSSES):
            ids = [eai[e] for e in group]
            _fisher_yates(ids, rng)
            for e, v in zip(group, ids):
                eai[e] = v
    if skills & AI_ENEMIES:
        for sc in (CRACK_SCRIPT, TOXIC_SCRIPT):
            table[sc * 16 + 13] = table[sc * 16 + 14] = 0xFF
        _deal_group(table, NORMAL_SCRIPTS, Stream(seed, STREAM_SKILLS), opening)
    if skills & AI_BOSSES:
        rng = Stream(seed, STREAM_BSKILLS)
        _deal_group(table, FIEND_SCRIPTS, rng, opening)
        _deal_group(table, BIG_SCRIPTS, rng, opening)
    return bytes(eai), bytes(table)


# --- RNG tables -------------------------------------------------------------------
#  lut_RNG (the encounter table: whether a step fights, and from which slot)
#  and lut_BattleScramble (the battle table), as the cartridge's own files.
RNG_OFF, RNG_SHUFFLE = 0, 1
RNG_MODES = 2
RNG_NAMES = {"off": RNG_OFF, "shuffle": RNG_SHUFFLE}
ENCRNG_BIN = os.path.join(ROOT, "game", "bin", "0F_F100_rngtable.bin")
BATRNG_BIN = os.path.join(ROOT, "game", "bin", "0F_FCF1_rngtable.bin")


def build_rng(seed, rng_mode):
    """The encounter table and the battle table, 256 bytes each: the battle
    table shuffled first, then the encounter table, from one stream."""
    enc = bytearray(open(ENCRNG_BIN, "rb").read())
    bat = bytearray(open(BATRNG_BIN, "rb").read())
    if 0 < rng_mode < RNG_MODES:
        rng = Stream(seed, STREAM_RNG)
        for t in (bat, enc):
            for i in range(255, 0, -1):
                j = rng.below16(i + 1)
                t[i], t[j] = t[j], t[i]
    return bytes(enc), bytes(bat)


# --- the Castle of Ordeals' pillars --------------------------------------------
#  FFR's ShuffleOrdeals (StandardMaps/ShuffleOrdeals.cs).  Castle of Ordeals
#  2F is a maze of teleporting pillars, fifteen pads, and a pad's tile is its
#  destination: tiles $4C-$54 land in one room each, $55 leads on to the
#  stairs.  The rooms are shuffled into a chain from the start room to the
#  way out, one pad of each leading to the next; every other pad leads back
#  to the same room or an earlier one, except that the four-pad room sends
#  one of its three spare pads anywhere but onward.  Every room is on the
#  chain, so the maze always has a way through.
#
#  The pads, in FFR's order: the start room's, then the eight rooms' --
#  (x, y) on the map.  Each room: the tile that lands in it, and its pads as
#  indices into ORDEALS_PADS.  Room 8, entered by tile $54, cannot be reached
#  in vanilla; FFR moves teleport $3C's landing to (16, 18), inside it.
ORDEALS_PADS = [(0x10, 0x0F),
                (0x0F, 0x09),
                (0x08, 0x08), (0x08, 0x0A),
                (0x09, 0x0F),
                (0x04, 0x14), (0x04, 0x16),
                (0x04, 0x12),
                (0x01, 0x01), (0x03, 0x02),
                (0x06, 0x08), (0x14, 0x0B), (0x14, 0x0D), (0x12, 0x10),
                (0x08, 0x12)]
ORDEALS_ROOMS = [(0x4E, [0]),                   # the start room, never moved
                 (0x4C, [1]), (0x4D, [2, 3]), (0x4F, [4]), (0x50, [5, 6]),
                 (0x51, [7]), (0x52, [8, 9]), (0x53, [10, 11, 12, 13]),
                 (0x54, [14])]
ORDEALS_EXIT = 0x55
ORDEALS_MODES = 2           # Off, Shuffle
ORDEALS_LOST_TELE = 0x3C    # tile $54's teleport...
ORDEALS_LOST_TO = (0x10, 0x12)   # ...and where FFR has it land


def ordeals_text(pads):
    """Each pad's destination, room by room, and the shortest way through.
    A room is named by the tile that lands in it, as FFR names them."""
    land = {tile: r for r, (tile, _) in enumerate(ORDEALS_ROOMS)}
    name = lambda r: "start" if r == 0 else "room %02X" % ORDEALS_ROOMS[r][0]
    def dest(p):
        return None if pads[p] == ORDEALS_EXIT else land[pads[p]]
    lines = ["  Ordeals 2F pillars:"]
    for r, (_, ps) in enumerate(ORDEALS_ROOMS):
        lines.append("    %-8s " % name(r) + ", ".join(
            "(%d,%d) -> %s" % (ORDEALS_PADS[p][0], ORDEALS_PADS[p][1],
                               "the way on" if dest(p) is None else name(dest(p))) for p in ps))
    prev, todo = {0: None}, [0]
    while todo:                         # breadth first, for the shortest way
        r = todo.pop(0)
        for p in ORDEALS_ROOMS[r][1]:
            d = dest(p)
            if d is None:
                way = [p]
                while prev[r] is not None:
                    r, q = prev[r]
                    way.append(q)
                lines.append("    way through: " + " -> ".join(
                    "(%d,%d)" % ORDEALS_PADS[q] for q in reversed(way)))
                return "\n".join(lines)
            if d not in prev:
                prev[d] = (r, p)
                todo.append(d)
    lines.append("    no way through")
    return "\n".join(lines)


def build_ordeals(seed, mode):
    """The fifteen pads' tiles, in ORDEALS_PADS order, or None if off."""
    if not 0 < mode < ORDEALS_MODES:
        return None
    rng = Stream(seed, STREAM_ORDEALS)
    #  The eight rooms, shuffled until the four-pad room is not first.
    while True:
        order = list(range(1, 9))
        _fisher_yates(order, rng)
        if len(ORDEALS_ROOMS[order[0]][1]) != 4:
            break
    seq = [0] + order
    tiles = [None] * len(ORDEALS_PADS)
    left = [list(ORDEALS_ROOMS[r][1]) for r in seq]
    #  The chain: a pad of each room to the next, the last one out.
    for i in range(len(seq)):
        k = rng.below(len(left[i]))
        pad = left[i].pop(k)
        tiles[pad] = ORDEALS_ROOMS[seq[i + 1]][0] if i + 1 < len(seq) else ORDEALS_EXIT
    #  The rest: back to this room or an earlier one -- and for the four-pad
    #  room, two different ways back and one anywhere but onward.
    for i in range(len(seq)):
        if len(left[i]) == 1:
            tiles[left[i][0]] = ORDEALS_ROOMS[seq[rng.below(i + 1)]][0]
        elif len(left[i]) == 3:
            pads = left[i]
            _fisher_yates(pads, rng)
            back = rng.below(i + 1)
            other = back
            while other == back:
                other = rng.below(i + 1)
            anywhere = back
            while anywhere in (back, other, i + 1):
                anywhere = rng.below(len(seq))
            tiles[pads[0]] = ORDEALS_ROOMS[seq[back]][0]
            tiles[pads[1]] = ORDEALS_ROOMS[seq[other]][0]
            tiles[pads[2]] = ORDEALS_ROOMS[seq[anywhere]][0]
    return bytes(tiles)


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
        if zones in (ZONES_LIGHT, ZONES_SHUFFLE):
            #  Each class pooled across the zones, shuffled, dealt back --
            #  every slot of it but WarMECH's.
            for first, count in LIGHT_CLASSES if zones == ZONES_LIGHT else RARITY_CLASSES:
                pos = [z * 8 + k for z in range(128) if ok[z] for k in range(first, first + count)
                       if d[z * 8 + k] != WARMECH]
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


# --- entrance shuffle -------------------------------------------------------------
#  FFR's ShuffleEntrancesAndFloors (EntrancesFloorsShuffle.cs), as
#  ../worldgraph/wiring.fe_shuffle ports it, over graphdata.py's indices (from
#  tools/gengraph.py) and on the cartridge's PRNG: with the same draws the two
#  give the same wiring (tools/checkentrance.py holds them to it).  FFR's
#  settings as its Entrance and Floor Shuffle preset has them -- towns fixed,
#  dead ends dealt, Coneria's start safe -- and either mode: entrances alone,
#  which keeps every floor's links but the Sea Shrine's from Onrac, or with
#  floors, which deals every floor but the Ice Cave's loop.
#
#  A wiring is three tables, as the game reads them: entrance -> (map, x, y),
#  normal teleport -> (map, x, y), exit -> overworld (x, y).  Each New Game
#  attempt k draws its own (STREAM_ENTR + k), so Continue can draw the one
#  the save names without placing anything.
import graphdata as _GD

ENTRANCES_OFF, ENTRANCES_ONLY, ENTRANCES_FLOORS = 0, 1, 2
STREAM_ENTR = 0x454E5452        # "ENTR"
ES_SANITY = 100                 # FFR's: the sanity check's tries


class ShuffleRng:
    """The draws the shuffle makes, as Python's random makes them: shuffle is
    Fisher-Yates from the top, a pick below i + 1 for each i down to 1, and
    a splice is one pick below the length."""
    def __init__(self, stream):
        self.st = stream

    def shuffle(self, lst):
        for i in range(len(lst) - 1, 0, -1):
            j = self.st.below(i + 1)
            lst[i], lst[j] = lst[j], lst[i]

    def randrange(self, n):
        return self.st.below(n)


def _loc(r):
    return _GD.RECORDS[r][1]


def _sane(shuffled):
    """FFR's CheckEntranceSanity, an unsafe start not allowed."""
    starter = any(o in _GD.STARTING and _loc(r) in _GD.STARTER for o, r in shuffled.items())
    titans = (any(_loc(r) == "TitansTunnelEast" and o in _GD.CONNECTED for o, r in shuffled.items()) and
              any(_loc(r) == "TitansTunnelWest" and o in _GD.CONNECTED for o, r in shuffled.items()))
    danger = 6 - sum(1 for o in _GD.DANGER if o in shuffled and _loc(shuffled[o]) in _GD.SAFE)
    return titans and starter and danger <= 3


def es_shuffle(rng, mode):
    """One shuffle: (entrance, normal, exits, roots), or None if FFR's sanity
    check fails ES_SANITY times.  roots: each record dealt -> the entrance
    its chain hangs from."""
    rec = _GD.RECORDS
    vanilla_ow = {o: _GD.ENTER[o] for o in _GD.LISTS["vanilla_ow"]}
    vanilla_sm = {t: _GD.TELE[t] for t in _GD.LISTS["vanilla_sm"]}
    placed_maps = {o: r for o, r in vanilla_ow.items() if 1 <= o <= 8}     # Coneria..Lefein
    placed_floors = dict(vanilla_sm)
    placed_floors.pop(_GD.SEASHRINE1, None)
    if mode == ENTRANCES_FLOORS:
        placed_floors = {t: _GD.TELE[t] for t in _GD.LISTS["icecave_loop"]}
    placed_dest = {_loc(r) for r in placed_maps.values()} | {_loc(r) for r in placed_floors.values()}
    town_ents = _GD.LISTS["towns"]
    nontown_ents = [o for o in range(_GD.UNUSED1) if o not in town_ents]
    shuffled_ow_count = (sum(1 for o in town_ents if o not in placed_maps) +
                         sum(1 for o in nontown_ents if o not in placed_maps))

    def recs(rs):
        return [r for r in rs if _loc(r) not in placed_dest]

    towns_l = recs(_GD.ENTER[o] for o in town_ents)
    top = recs(_GD.ENTER[o] for o in _GD.LISTS["top"])
    sub = recs([_GD.ENTER[o] for o in _GD.LISTS["free_ow"]] + [_GD.TELE[t] for t in _GD.LISTS["free_sm"]])
    dead = []
    rng.shuffle(towns_l)
    while towns_l and rec[towns_l[0]][0] in ("Lefein", "Melmond"):
        towns_l.append(towns_l.pop(0))
    rng.shuffle(top)
    rng.shuffle(sub)
    forks = sum(len(rec[r][2]) - 1 for r in sub if len(rec[r][2]) > 1) + (1 if sub else 0)
    for _ in range(forks):
        k = next((i for i, r in enumerate(sub) if not rec[r][2]), None)
        if k is None:
            return None                     # FFR's code assumes there is one
        dead.append(sub.pop(k))
    rng.shuffle(sub)
    rng.shuffle(dead)
    dests = towns_l + top + sub + dead

    for _ in range(ES_SANITY):
        i = j = 0
        shuffled, floors_out, exits_out, roots = {}, {}, {}, {}
        s_towns, s_ents = list(town_ents), list(nontown_ents)
        rng.shuffle(s_towns)
        rng.shuffle(s_ents)
        for o in s_towns + s_ents:
            if o in placed_maps:
                d = placed_maps[o]
            else:
                d, i = dests[i], i + 1
            shuffled[o] = d
            roots[d] = o
            if rec[d][3] is not None:
                exits_out[rec[d][3]] = _GD.OW_COORDS[o]
            pending = list(rec[d][2])
            while pending:
                t = pending.pop(rng.randrange(len(pending)))
                if t in placed_floors:
                    f = placed_floors[t]
                else:
                    f, j = dests[shuffled_ow_count + j], j + 1
                pending += list(rec[f][2])
                floors_out[t] = f
                roots[f] = o
                if rec[f][3] is not None:
                    exits_out[rec[f][3]] = _GD.OW_COORDS[o]
        if _sane(shuffled):
            break
    else:
        return None
    entrance = list(_GD.VANILLA_ENTRANCE)
    normal = list(_GD.VANILLA_NORMAL)
    exits = list(_GD.VANILLA_EXIT)
    for o, d in shuffled.items():
        entrance[o] = _GD.LANDED[d]
    for t, f in floors_out.items():
        normal[t] = _GD.LANDED[f]
    for x, xy in exits_out.items():
        exits[x] = xy
    return entrance, normal, exits, roots


#  Each location's requirement masks on a wiring: the minimal sets of key items
#  and events that reach it, by relaxation over graphdata.py's graph with the
#  wiring's edges added -- analysis.requirements's fixpoint, which
#  tools/checkentrance.py holds this to.  ES_NODE_MASKS is the room the
#  cartridge has for one region's -- 3,000 wirings needed five at most -- and
#  ES_LOC_MASKS and ES_BYBIT its room for the locations' masks and placement's
#  index of them (588 and 968 at most): a wiring that needs more is refused
#  and another drawn.  The Early flags: King, Sarda and the Sage clear their NPC's
#  own requirement, as the game does; Ordeals clears the CROWN from the two
#  throne teleports' sources, in the graph.  Returns (masks per cartridge
#  location, Chaos's, each region's), each sorted, or None.
ES_NODE_MASKS = 6
ES_LOC_MASKS = 1024
ES_BYBIT = 1536


def _minimal(ms):
    out = []
    for m in sorted(set(ms), key=lambda m: (bin(m).count("1"), m)):
        if not any(o & m == o for o in out):
            out.append(m)
    return sorted(out)


def es_masks(entrance, normal, exits, early):
    M = _GD.MASKS
    adj = [[] for _ in range(_GD.NODES)]
    for src, dst, r in _GD.EDGES:
        adj[src].append((dst, M[r]))
    for e, src, r in _GD.ENT_SRC:
        for dst in _GD.LAND[tuple(entrance[e])]:
            adj[src].append((dst, M[r]))
    for t, src, r, ordeals in _GD.TELE_SRC:
        rr = 0 if ordeals and early >> 3 & 1 else M[r]
        for dst in _GD.LAND[tuple(normal[t])]:
            adj[src].append((dst, rr))
    for x, src, r in _GD.EXIT_SRC:
        for dst in _GD.EXIT_TO[tuple(exits[x])]:
            adj[src].append((dst, M[r]))
    req = [[] for _ in range(_GD.NODES)]
    req[0] = [0]
    queue, queued = [0], {0}
    while queue:
        n = queue.pop(0)
        queued.discard(n)
        for d, r in adj[n]:
            merged = _minimal(req[d] + [m | r for m in req[n]])
            if merged != req[d]:
                if len(merged) > ES_NODE_MASKS:
                    return None
                req[d] = merged
                if d not in queued:
                    queued.add(d)
                    queue.append(d)
    out = []
    for c, (nodes, r) in enumerate(zip(_GD.LOC_NODES, _GD.LOC_REQ)):
        own = M[r]
        e = _L.LOCS[c][3]
        if e and e != 4 and early >> (e - 1) & 1:
            own &= ~_L.EARLY_BIT[e - 1]
        out.append(_minimal([m | own for n in nodes for m in req[n]]))
    chaos = _minimal([m | M[_GD.CHAOS_REQ] for n in _GD.CHAOS_NODES for m in req[n]])
    if (sum(len(m) for m in out) > ES_LOC_MASKS or len(chaos) > ES_NODE_MASKS or
            sum(len({b for m in ms for b in range(32) if m >> b & 1}) for ms in out) > ES_BYBIT):
        return None
    return out, chaos, req


#  Each region's entrances on a wiring: those whose landing reaches it without
#  leaving the maps -- genlogic.spread_groups's dungeon, read off the wired
#  graph.  As a 32-bit mask, an entrance a bit.
def es_roots(entrance, normal):
    inside = [[] for _ in range(_GD.NODES)]
    for src, dst, r in _GD.EDGES:
        if not _GD.OW_NODE[src] and not _GD.OW_NODE[dst]:
            inside[src].append(dst)
    for t, src, r, ordeals in _GD.TELE_SRC:
        for dst in _GD.LAND[tuple(normal[t])]:
            if not _GD.OW_NODE[src] and not _GD.OW_NODE[dst]:
                inside[src].append(dst)
    roots = [0] * _GD.NODES
    for e in sorted({e for e, _, _ in _GD.ENT_SRC}):
        todo = list(_GD.LAND[tuple(entrance[e])])
        for n in todo:
            roots[n] |= 1 << e
        while todo:
            n = todo.pop()
            for d in inside[n]:
                if not roots[d] >> e & 1:
                    roots[d] |= 1 << e
                    todo.append(d)
    return roots


#  The spread groups on a wiring: a number per pool chest, the chests of one
#  dungeon (the same entrances) behind the same requirements sharing one, in
#  the order the chests come; $FF for an NPC or the caravan.  On the vanilla
#  wiring with no Early flag, logicdata.SPREAD (tools/checkentrance.py).
ES_GROUPMAX = 64                # the cartridge's room; 800 wirings needed 30


def es_groups(roots, masks):
    keys, out = {}, []
    for c in range(248):
        if _L.LOCS[c][0] != 0:
            out.append(0xFF)
            continue
        ents = 0
        for n in _GD.LOC_NODES[c]:
            ents |= roots[n]
        out.append(keys.setdefault((ents, tuple(masks[c])), len(keys)))
    if len(keys) > ES_GROUPMAX:
        return None
    return out


#  Where a ship found at location c is moored, on a shuffled wiring: of FFR's
#  five docks, those the party can reach whenever it can reach c -- every one
#  of c's masks that does not need the ship covers one of a dock's boarding
#  regions' -- the nearest to the entrances c hangs from: overworld steps on
#  foot and by canoe if any can be walked to, else as the airship flies.
#  Coneria's is boarded from the start's region, so it always qualifies.
def es_dock(c, masks, req, roots):
    ship = _BIT["SHIP"]
    ents = 0
    for n in _GD.LOC_NODES[c]:
        ents |= roots[n]
    best = None
    for d in range(len(_GD.DOCKS)):
        board = _minimal([m for n in _GD.DOCK_BOARD[d] for m in req[n]])
        if not all(any(b & ~m == 0 for b in board) for m in masks[c] if not m & ship):
            continue
        walk = [_GD.ENT_DOCK[e][d][0] for e in range(32) if ents >> e & 1 and e in _GD.ENT_DOCK
                and _GD.ENT_DOCK[e][d][0] is not None]
        fly = min([_GD.ENT_DOCK[e][d][1] for e in range(32) if ents >> e & 1 and e in _GD.ENT_DOCK]
                  or [0x7FFF])
        key = (0, min(walk), d) if walk else (1, fly, d)
        if best is None or key < best:
            best = key
    return best[2]




# --- incentive placement ----------------------------------------------------------
#  FFR's PredictivePlacement (FF1Lib/PredictivePlacement.cs), as
#  ../worldgraph/placement.py ports it, over the vanilla world's logic
#  (logicdata.py, from tools/genlogic.py): each cycle it asks, for every key
#  item still to place, how many more incentive and other places the party
#  could reach with it, sorts the items into bins by that, weights the bins by
#  how many places are reachable now, and draws an item and then a place.
#  Differences from FFR, all of them the cartridge's: its own PRNG; weights
#  in integers, 1.0 being 1024, so a weight halved past ten times is zero
#  where FFR's float never is; no shuffle of the candidates before the draw,
#  which changes nothing about the odds; up to PLACE_ATTEMPTS tries before
#  giving up, where FFR stops at three, and then key items stay where they
#  are.  FFR's safe tables, as it uses on its own map without Entrance
#  shuffle, and its unsafe ones under Map shuffle, as it does under
#  Entrances (TUNE_LOOSE); its BRIDGE at 2.0 in both, which it sets for the
#  vanilla overworld.  A draw with nowhere to go -- no incentive spot reached,
#  or no other place -- weighs nothing, where FFR draws anyway ("can't happen")
#  and can spin to cycle 100.  And forward placement, always, without FFR's
#  spread placement (_forward); and progression first, which FFR has not
#  (_first).
import logicdata as _L

PLACE_ATTEMPTS = 32
#  The items placement places, in the cartridge's order: nineteen key items,
#  the TAIL, then the nine gear rows.  (name, logic bit or None, the safe
#  weight in quarters, min cycle, min places reachable)
PLACE_ITEMS = [
    ("LUTE", 1), ("CROWN", 3), ("CRYSTAL", 3), ("HERB", 3), ("KEY", 1), ("TNT", 3),
    ("ADAMANT", 3), ("SLAB", 3), ("RUBY", 4), ("ROD", 4), ("FLOATER", 1), ("CHIME", 1),
    ("CUBE", 1), ("BOTTLE", 3), ("OXYALE", 1), ("CANOE", 3), ("SHIP", 4), ("BRIDGE", 8),
    ("CANAL", 4),
    ("TAIL", 0),
    ("MASAMUNE", 0), ("KATANA", 0), ("VORPAL", 0), ("DEFENSE", 0), ("OPAL", 0),
    ("POWERGAUNTLET", 0), ("WHITESHIRT", 0), ("RIBBON", 0), ("XCALBER", 0)]
PLACE_KEYS = 19                 # the first nineteen open something
PLACE_TAIL = 19
PLACE_GEAR = 20
MIN_CYCLE = {"KEY": 5, "SHIP": 2, "CANOE": 3, "FLOATER": 10, "CHIME": 5, "CUBE": 7, "OXYALE": 5}
MIN_ACCESS = {"CHIME": 60, "CUBE": 75, "OXYALE": 50}
#  FFR's unsafe tables, which it uses whenever Entrances is on
#  (PredictivePlacement.cs): on a shuffled world the CHIME, CUBE and OXYALE
#  can open somewhere early, so they lose their late limits and the CHIME and
#  OXYALE weigh more; the LUTE, which opens the end however the doors fall,
#  waits for cycle ten.  The BRIDGE stays at 2.0, the vanilla overworld's.
LOOSE_Q = {"CHIME": 5, "CUBE": 4, "OXYALE": 5}
MIN_CYCLE_LOOSE = {"KEY": 5, "SHIP": 2, "CANOE": 3, "FLOATER": 10, "LUTE": 10}
MIN_ACCESS_LOOSE = {"CHIME": 5, "CUBE": 5, "OXYALE": 5}
TUNE_SAFE = ({}, MIN_CYCLE, MIN_ACCESS)
TUNE_LOOSE = (LOOSE_Q, MIN_CYCLE_LOOSE, MIN_ACCESS_LOOSE)
NONKEY_MIN_CYCLE = 10
CRIT_NON, SAFE_NON, CRIT_INC, SAFE_INC = 5, 20, 2, 3
W1 = 1024                       # a weight of 1.0
#  The item rows (snesmap.inc's ITEMROW_*), and which item each governs.
ITEMROW_ITEM = ["SHIP", "FLOATER", "BRIDGE", "CANAL", "CANOE", "KEY", "CHIME", "CROWN", "LUTE",
                "TAIL", "ROD"]
OTHER_ITEMS = ["CRYSTAL", "HERB", "TNT", "ADAMANT", "SLAB", "RUBY", "CUBE", "BOTTLE", "OXYALE"]
ITEM_INCENTIVE, ITEM_LOOSE, ITEM_FREE = 0, 1, 2
KEYITEMS_VANILLA, KEYITEMS_STANDARD, KEYITEMS_WIDE = 0, 1, 2
_NAME = [n for n, _ in PLACE_ITEMS]
_BIT = {n: 1 << _L.BITS.index(n) for n in _NAME[:PLACE_KEYS]}
_BIT_AIRSHIP = 1 << _L.BITS.index("AIRSHIP")


def item_rows(items3):
    """The three RANDO_ITEMS bytes as twelve row values."""
    v = int.from_bytes(bytes(items3), "little")
    return [(v >> (2 * k)) & 3 for k in range(12)]


def place_setup(keyitems, items3, gear2, early):
    """The settings as placement sees them: the free mask, the items to place
    (cartridge order), which of those are incentives, the incentive places,
    and each location's masks with the Early flags' waivers applied."""
    rows = item_rows(items3)
    gear = int.from_bytes(bytes(gear2), "little")
    free, items, inc = 0, [], set()
    for k, name in enumerate(ITEMROW_ITEM):
        i = _NAME.index(name)
        v = rows[k] if rows[k] < 3 else ITEM_INCENTIVE
        if v == ITEM_FREE:
            if name in _BIT:
                free |= _BIT[name]
            if name == "FLOATER":
                free |= _BIT_AIRSHIP
            continue
        items.append(i)
        if v == ITEM_INCENTIVE:
            inc.add(i)
    other = rows[11] if rows[11] < 2 else ITEM_INCENTIVE
    for name in OTHER_ITEMS:
        i = _NAME.index(name)
        items.append(i)
        if other == ITEM_INCENTIVE:
            inc.add(i)
    for g in range(9):
        if gear >> g & 1:
            items.append(PLACE_GEAR + g)
            inc.add(PLACE_GEAR + g)
    items.sort()
    spot = 0x01 if keyitems == KEYITEMS_STANDARD else 0x02
    inclocs = {c for c, l in enumerate(_L.LOCS) if l[2] & spot}
    masks = []
    for kind, ident, flags, e, ms, _ in _L.LOCS:
        clear = _L.EARLY_BIT[e - 1] if e and early >> (e - 1) & 1 else 0
        masks.append([m & ~clear for m in ms])
    return free, items, inc, inclocs, masks


def place_accessible(masks, placed, owned):
    """Pool places reachable and not yet holding an item, and what is owned,
    once everything reachable has been collected."""
    while True:
        gained = 0
        open_ = []
        for c, ms in enumerate(masks):
            if any(m & ~owned == 0 for m in ms):
                open_.append(c)
                kind, ident = _L.LOCS[c][0], _L.LOCS[c][1]
                if kind == 3:
                    gained |= 1 << ident
                elif c in placed and placed[c] < PLACE_KEYS:
                    gained |= _BIT[_NAME[placed[c]]]
        if not gained & ~owned:
            return {c for c in open_ if c < 248 and c not in placed}, owned
        owned |= gained


def _weight(i, w, cycle, access, tune):
    name, q = PLACE_ITEMS[i]
    qs, min_cycle, min_access = tune
    q = qs.get(name, q)
    if access < min_access.get(name, 0) or cycle < min_cycle.get(name, 0):
        return 0
    if i >= PLACE_KEYS:
        return 0 if cycle < NONKEY_MIN_CYCLE else w >> 1
    return (w * q) >> 2


def _bins(cands, b0, b1, b2, b3, red, cycle, access, key, lo, hi, tune):
    out = []
    for i, cnt in cands:
        c = cnt[key]
        if c < 0:
            out.append((_weight(i, b0, cycle, access, tune), i))
        elif c < lo:
            out.append((_weight(i, b1, cycle, access, tune), i))
        elif c < hi:
            out.append((_weight(i, b2, cycle, access, tune), i))
    w = b3
    for i, cnt in sorted((x for x in cands if x[1][key] >= hi), key=lambda x: (x[1][key], x[0])):
        out.append((_weight(i, w, cycle, access, tune), i))
        w >>= red
    return out


#  The caravan: the one location a shop, so it can sell an item and nothing
#  else -- no vehicle, no gear.  FFR stocks it first, before the loop
#  (SelectVendorItem): a random one of the incentives a shop can sell, or, with
#  none, ordinary treasure, which the rewards deal.  Either way the loop never
#  places there.  CARAVAN_TREASURE marks the second.
CARAVAN = 247
CARAVAN_TREASURE = 0xFE
_SHOPPABLE = [_NAME.index(n) for n in ("LUTE", "CROWN", "CRYSTAL", "HERB", "KEY", "TNT", "ADAMANT",
                                       "SLAB", "RUBY", "ROD", "FLOATER", "CHIME", "CUBE", "BOTTLE",
                                       "OXYALE", "TAIL")]


#  Forward placement (user, 2026-10-14): an item that is not an incentive goes
#  to a place drawn by weight, and every place that could have taken it then
#  has its weight halved.  A place reached from the start has lost most of its
#  weight by the time a new area opens, so the new area's places are the
#  likelier, and loose items stop piling up where the party begins.  Then
#  spread placement (user, 2026-10-14): the chests in the same dungeon behind
#  the same requirements as the one drawn (logicdata.SPREAD) are quartered,
#  so the next item likelier goes to another dungeon than piles into this one.
#  Both are FFR's, LooseItemsForwardPlacement and LooseItemsSpreadPlacement
#  (RewardSourcePicker.Pick), off in every FFR preset.  The weights are whole
#  numbers, FWD_ONE at the start of an attempt and falling to no less than 1,
#  where FFR's doubles fall forever.  Incentives are drawn as before,
#  uniformly: FFR spreads them too, but no two incentive chests share a group
#  (genlogic.py asserts it), so that is nothing here.
FWD_ONE = 256


def _forward(rng, where, fwd, spread=None):
    """The place, of `where` (ascending), drawn by its weight in `fwd`; then
    every one of them halved, and those in its spread group quartered, each to
    no less than 1."""
    total = sum(fwd[c] for c in where)
    assert 0 < total < 0x10000
    r = rng.below16(total)
    pick = None
    for c in where:
        w = fwd[c]
        if pick is None:
            if r < w:
                pick = c
            else:
                r -= w
        if w > 1:
            fwd[c] = w >> 1
    spread = _L.SPREAD if spread is None else spread
    group = spread[pick]
    if group != 0xFF:
        for c in where:
            if spread[c] == group:
                fwd[c] = max(1, fwd[c] >> 2)
    return pick


#  Progression first (user, 2026-10-14; not FFR's): in the loose draw, while
#  any loose key item would open a place -- a count of 0 or more, the item's
#  own place taken off -- those that would open none, and loose gear, weigh
#  nothing.  FFR draws them alike once enough places are reached, so early on,
#  while those are only the start's few, they fill them.  Held back, they are
#  placed once nothing would open anything, or nothing else can be, and the
#  world has opened by then; forward placement then favours what opened last.
def _first(wc, cs):
    prog = {i for i, cnt in cs if cnt["non"] >= 0}
    keep = [(w, i) for w, i in wc if i in prog]
    return keep if sum(w for w, _ in keep) else wc


def _attempt(rng, free, items, inc0, inclocs, masks, chaos=None, spread=None, tune=TUNE_SAFE):
    incentives = set(inc0)
    n_inc_pool = len(inclocs)
    while len(incentives) > n_inc_pool:
        s = sorted(incentives)
        incentives.discard(s[rng.below(len(s))])
    remaining = list(items)
    keys = [i for i in remaining if i < PLACE_KEYS]
    placed = {}
    fwd = [FWD_ONE] * 248
    assert CARAVAN in inclocs and _L.LOCS[CARAVAN][0] == 2
    shoppable = [i for i in sorted(incentives) if i in _SHOPPABLE]
    if shoppable:
        item = shoppable[rng.below(len(shoppable))]
        placed[CARAVAN] = item
        remaining.remove(item)
        if item in keys:
            keys.remove(item)
    else:
        placed[CARAVAN] = CARAVAN_TREASURE
    state = "normal"
    SHIP, CANAL = _NAME.index("SHIP"), _NAME.index("CANAL")
    for cycle in range(1, 101):
        acc, owned = place_accessible(masks, placed, free)
        inc_src = {c for c in acc if c in inclocs}
        non_src = acc - inc_src
        cands = []
        for i in keys:
            acc2, _ = place_accessible(masks, placed, owned | _BIT[_NAME[i]])
            ni = len({c for c in acc2 if c in inclocs}) - len(inc_src)
            nn = len(acc2) - len(inc_src) - ni - len(non_src)
            if i in incentives:
                ni -= 1
            else:
                nn -= 1
            cands.append((i, {"inc": ni, "non": nn}))
        if SHIP in keys and CANAL in keys:
            acc2, _ = place_accessible(masks, placed, owned | _BIT["SHIP"] | _BIT["CANAL"])
            ni = len({c for c in acc2 if c in inclocs}) - len(inc_src)
            nn = len(acc2) - len(inc_src) - ni - len(non_src)
            for it in (SHIP, CANAL):
                if it in incentives:
                    ni -= 1
                else:
                    nn -= 1
            ni //= 2
            nn //= 2
            for i, cnt in cands:
                if i in (SHIP, CANAL):
                    if cnt["inc"] < ni and len(inc_src) > 1:
                        cnt["inc"] = ni
                    if cnt["non"] < nn and len(non_src) > 1:
                        cnt["non"] = nn
        inc_items = [i for i in remaining if i in incentives]
        access = len(acc)
        if state == "incentive" or (state == "normal" and rng.below(len(remaining)) < len(inc_items)):
            cs = [c for c in cands if c[0] in incentives]
            nonkey = [i for i in remaining if i >= PLACE_KEYS and i in incentives]
            n = len(inc_src)
            if n == 0:
                #  No incentive spot: nothing to weigh, so the other draw next
                #  cycle, or give up as stuck.  FFR draws anyway ("can't
                #  happen"), finds nowhere, and keeps its state -- in the
                #  incentive state, drawing the same way to cycle 100.
                wc = []
            elif n <= 1 or (n <= CRIT_INC and SHIP in keys and CANAL in keys):
                wc = _bins(cs, 0, W1 // 2, W1, W1, 1, cycle, access, "inc", 1, 2, tune)
            elif n <= SAFE_INC:
                wc = _bins(cs, W1 // 2, W1 // 2, W1, W1 // 2, 2, cycle, access, "inc", 1, 2, tune)
                wc += [(_weight(i, W1 // 2, cycle, access, tune), i) for i in nonkey]
            else:
                wc = _bins(cs, W1, W1, W1, W1 // 4, 2, cycle, access, "inc", 1, 2, tune)
                wc += [(_weight(i, W1, cycle, access, tune), i) for i in nonkey]
            if sum(w for w, _ in wc) == 0 and len(inc_items) <= n:
                wc += [(W1, i) for i in inc_items]
            if sum(w for w, _ in wc) == 0:
                if cycle >= 15 and state != "normal":
                    return None
                state = "nonincentive"
                continue
        else:
            cs = [c for c in cands if c[0] not in incentives]
            nonkey = [i for i in remaining if i >= PLACE_KEYS and i not in incentives]
            n = len(non_src)
            if n == 0:
                wc = []                 # likewise, with no other place
            elif n <= CRIT_NON:
                wc = _bins(cs, 0, W1 // 2, W1, W1, 1, cycle, access, "non", 5, 20, tune)
            elif n <= SAFE_NON:
                wc = _bins(cs, W1 // 2, W1 // 2, W1, W1 // 2, 2, cycle, access, "non", 5, 20, tune)
                wc += [(_weight(i, W1 // 2, cycle, access, tune), i) for i in nonkey]
            else:
                wc = _bins(cs, W1, W1, W1, W1 // 4, 2, cycle, access, "non", 5, 20, tune)
                wc += [(_weight(i, W1, cycle, access, tune), i) for i in nonkey]
            wc = _first(wc, cs)
            if sum(w for w, _ in wc) == 0:
                if cycle >= 15 and state != "normal":
                    return None
                state = "incentive"
                continue
        wc = [x for x in wc if x[0] > 0]
        total = sum(w for w, _ in wc)
        assert total < 0x10000
        r = rng.below16(total)
        for w, item in wc:
            if r < w:
                break
            r -= w
        where = sorted(inc_src if item in incentives else non_src)
        if not where:
            continue
        if item in incentives:
            placed[where[rng.below(len(where))]] = item
        else:
            placed[_forward(rng, where, fwd, spread)] = item
        remaining.remove(item)
        if item in keys:
            keys.remove(item)
        state = "normal"
        if not remaining:
            break
    if remaining:
        return None
    _, owned = place_accessible(masks, placed, free)
    if not any(m & ~owned == 0 for m in (_L.CHAOS_MASKS if chaos is None else chaos)):
        return None
    return placed


def build_placement(seed, keyitems, items3, gear2, early, world=None, stream=STREAM_KEYS,
                    attempts=PLACE_ATTEMPTS, tune=None):
    """Where each item goes: a list in PLACE_ITEMS order of cartridge location
    indices, $FF for an item not placed (free, or gear left as Treasure);
    None under Key items Vanilla, and None too if every attempt failed."""
    if keyitems not in (KEYITEMS_STANDARD, KEYITEMS_WIDE):
        return None
    free, items, inc, inclocs, masks = place_setup(keyitems, items3, gear2, early)
    if world is not None:
        masks, chaos, spread = world
    else:
        chaos = spread = None
    if tune is None:
        tune = TUNE_SAFE if world is None else TUNE_LOOSE
    rng = Stream(seed, stream)
    for _ in range(attempts):
        placed = _attempt(rng, free, items, inc, inclocs, masks, chaos, spread, tune)
        if placed is not None:
            out = [0xFF] * len(PLACE_ITEMS)
            for c, i in placed.items():
                if i != CARAVAN_TREASURE:
                    out[i] = c
            return out
    return None


#  A New Game's world under entrance shuffle: for each attempt k, a wiring
#  (STREAM_ENTR + k) whose masks fit, then its placement (STREAM_KEYS + k),
#  given ES_PLACE_ATTEMPTS tries -- FFR gives a placement three and then rolls
#  a new seed; a wiring that will not place often needs more than 32, and the
#  next wiring is cheaper.  The first that places is the game's.  Returns (k,
#  (entrance, normal, exits), placement, the ship's dock), or None.  Off is
#  build_placement on the vanilla tables, unchanged.
ES_ATTEMPTS = 16
ES_PLACE_ATTEMPTS = 4


def build_world(seed, keyitems, items3, gear2, early, entrances, tune=TUNE_LOOSE):
    if keyitems not in (KEYITEMS_STANDARD, KEYITEMS_WIDE) or entrances == ENTRANCES_OFF:
        return None
    ship = [n for n, _ in PLACE_ITEMS].index("SHIP")
    for k in range(ES_ATTEMPTS):
        w = es_shuffle(ShuffleRng(Stream(seed, STREAM_ENTR + k)), entrances)
        if w is None:
            continue
        mm = es_masks(w[0], w[1], w[2], early)
        if mm is None:
            continue
        masks, chaos, req = mm
        roots = es_roots(w[0], w[1])
        groups = es_groups(roots, masks)
        if groups is None:
            continue
        out = build_placement(seed, keyitems, items3, gear2, early,
                              world=(masks, chaos, groups), stream=STREAM_KEYS + k,
                              attempts=ES_PLACE_ATTEMPTS, tune=tune)
        if out is None:
            continue
        dock = 0 if out[ship] == 0xFF else es_dock(out[ship], masks, req, roots)
        return k, w[:3], out, dock
    return None


# --- rewards from placement ---------------------------------------------------------
#  What every chest, reward NPC and the caravan gives once placement has put the
#  key items: 255 slots, the 241 chests a map places, the thirteen NPCs and the
#  caravan.  A placed item takes its place.  Every item placement moves, and
#  every Free item, leaves its vanilla home; a Free item's home becomes gold,
#  one of FFR's spare amounts (ItemLists.UnusedGoldItems) -- the user's rule,
#  where FFR pads with CABINs.  The rest of the contents then go where the
#  Chests row sends them:
#    - Shuffle: every slot not placed is dealt from them all, as Tier 1 dealt
#      the chests, NPCs and caravan now among them;
#    - Off: only the slots placement touched change -- the contents a placed
#      item pushed out, and the gold, are dealt into the homes left empty.
#  The caravan is a shop: if placement left it to treasure, it is stocked
#  first, with a random one of what is dealt that a shop can sell.
STREAM_GOLD = 0x474F4C44        # "GOLD"
SLOT_NPC, SLOT_CARAVAN = 256, 269
#  rando_talk's vanilla rewards (lut_TalkReward), and the four vehicles' codes.
REWARD_SHIP, REWARD_BRIDGE, REWARD_CANAL, REWARD_CANOE = 0xF0, 0xF1, 0xF2, 0xF3
TALK_REWARD = [REWARD_BRIDGE, 0x01, REWARD_SHIP, 0x05, 0x03, 0x04, REWARD_CANAL, 0x42, 0x0A,
               REWARD_CANOE, 0x0E, 0x10, 0x0C]
#  What each PLACE_ITEMS item is, given: its chest code, or a vehicle's.
PLACE_CODE = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0E, 0x0F,
              0x10, REWARD_CANOE, REWARD_SHIP, REWARD_BRIDGE, REWARD_CANAL, 0x0D,
              0x43, 0x41, 0x3D, 0x3B, 0x51, 0x69, 0x52, 0x63, 0x42]
SPARE_GOLD = [0x6E, 0x6F, 0x70, 0x71, 0x72, 0x74, 0x78, 0x79, 0x7A, 0x7C, 0x7D, 0x7F, 0x84, 0x9E,
              0xA5, 0xA6, 0xA7, 0xA8, 0xAA, 0xAB, 0xAC]


def reward_slots():
    """The slots, in order: chest ids a map places, NPCs, the caravan."""
    return [c for c in range(256) if c not in UNUSED_CHESTS] + \
        list(range(SLOT_NPC, SLOT_NPC + 13)) + [SLOT_CARAVAN]


def loc_slot(c):
    kind, ident = _L.LOCS[c][0], _L.LOCS[c][1]
    return ident if kind == 0 else SLOT_NPC + ident if kind == 1 else SLOT_CARAVAN


def sellable(code):
    return 0 < code < 0x1C


def build_rewards(rom, seed, chests, place, items3):
    """(256 chest bytes, 13 NPC rewards, the caravan's item) once placement is
    in; place is RANDO_PLACE, items3 RANDO_ITEMS."""
    vanilla = {s: v for s, v in zip(range(256), rom_chests(rom))}
    for n, v in enumerate(TALK_REWARD):
        vanilla[SLOT_NPC + n] = v
    vanilla[SLOT_CARAVAN] = 0x0F
    slots = reward_slots()

    def home(code):
        return next(s for s in slots if vanilla[s] == code)

    placed = {loc_slot(c): PLACE_CODE[i] for i, c in enumerate(place) if c != 0xFF}
    rows = item_rows(items3)
    free = [ITEMROW_ITEM[k] for k in range(11) if rows[k] == ITEM_FREE]
    homes = [home(PLACE_CODE[i]) for i, c in enumerate(place) if c != 0xFF] + \
        [home(PLACE_CODE[_NAME.index(n)]) for n in free]
    gold_rng = Stream(seed, STREAM_GOLD)
    golds = [SPARE_GOLD[gold_rng.below(len(SPARE_GOLD))] for _ in free]
    out = dict(vanilla)
    out.update(placed)
    rng = Stream(seed, STREAM_CHESTS)
    if 0 < chests < CHESTS_MODES:
        pool = [vanilla[s] for s in slots if s not in homes] + golds
        dest = [s for s in slots if s not in placed]
    else:
        pool = [vanilla[s] for s in slots if s in placed and s not in homes] + golds
        dest = [s for s in slots if s in homes and s not in placed]
    assert len(pool) == len(dest)
    if SLOT_CARAVAN in dest:
        sell = [k for k, v in enumerate(pool) if sellable(v)]
        if sell:
            out[SLOT_CARAVAN] = pool.pop(sell[rng.below(len(sell))])
        else:
            out[SLOT_CARAVAN] = 0x17            # a CABIN, and the last left over
            pool.pop()
        dest.remove(SLOT_CARAVAN)
    for i in range(len(pool) - 1, 0, -1):
        j = rng.below(i + 1)
        pool[i], pool[j] = pool[j], pool[i]
    for s, v in zip(dest, pool):
        out[s] = v
    table = bytes(out[c] for c in range(256))
    return table, bytes(out[SLOT_NPC + n] for n in range(13)), out[SLOT_CARAVAN]


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
RANDO_SAVE_SIZE = 0x1D       # snesmap.inc: the settings, then entrance shuffle's k and dock


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
    ap.add_argument("--runs", choices=sorted(RUNS_NAMES), default="off",
                    help="unrunnable fights")
    ap.add_argument("--surprise", choices=sorted(SURPRISE_NAMES), default="off",
                    help="surprise rates")
    ap.add_argument("--status", choices=sorted(STATUS_NAMES), default="off",
                    help="status attacks: enemies' touches")
    ap.add_argument("--scripts", choices=sorted(AI_NAMES), default="off",
                    help="enemy scripts: who has which")
    ap.add_argument("--skills", choices=sorted(AI_NAMES), default="off",
                    help="enemy skills: what the scripts hold")
    ap.add_argument("--rng", choices=sorted(RNG_NAMES), default="off",
                    help="RNG tables: the encounter and battle tables")
    ap.add_argument("--ordeals", choices=["off", "shuffle"], default="off",
                    help="Ordeals pillars: the Castle of Ordeals 2F maze")
    ap.add_argument("--find", metavar="NAME",
                    help="only where an item is: every chest and shop selling it")
    ap.add_argument("--rom", default=ROM)
    a = ap.parse_args()
    rom = open(a.rom, "rb").read()
    if a.srm:
        #  The key item rows after Ordeals pillars place nothing here yet.
        (seed, traps, shops, chests, magic, bless, curse, rarity, zones, runs,
         surprise, status, scripts, skills, rngt, ordeals) = block_from_srm(open(a.srm, "rb").read())[:16]
    elif a.seed:
        (seed, traps, shops, chests, magic, bless, curse, rarity, zones, runs,
         surprise, status, scripts, skills, rngt, ordeals) = (
            int(a.seed, 16), TRAP_NAMES[a.traps], SHOP_NAMES[a.shops],
            CHEST_NAMES[a.chests], MAGIC_NAMES[a.magic], a.bless, a.curse,
            FORMS_NAMES[a.rarity], ZONES_NAMES[a.zones], RUNS_NAMES[a.runs],
            SURPRISE_NAMES[a.surprise], STATUS_NAMES[a.status], AI_NAMES[a.scripts],
            AI_NAMES[a.skills], RNG_NAMES[a.rng], int(a.ordeals == "shuffle"))
    else:
        ap.error("give a battery file or --seed")
    print("seed %08X, trap tiles mode %d, shops mode %d, chests mode %d, magic mode %d,"
          " blessing +%d, curse -%d, formation rarity %d, zones %d, unrunnable %d,"
          " surprise %d, status %d, scripts %d, skills %d, RNG tables %d, Ordeals %d"
          % (seed, traps, shops, chests, magic, bless, curse, rarity, zones, runs,
             surprise, status, scripts, skills, rngt, ordeals))
    pads = build_ordeals(seed, ordeals)
    if pads and not a.find:
        print(ordeals_text(pads))
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
    if rngt:
        #  For a runner learning the seed: BattleStepRNG walks this with
        #  battlestep, up or down as battlestep_sign says, and a step fights
        #  when its byte is below the map's rate.
        enc, _ = build_rng(seed, rngt)
        print("  encounter table (lut_RNG), by battlestep:")
        for row in range(16):
            print("    $%X0  %s" % (row, " ".join("%02X" % b for b in enc[row * 16:row * 16 + 16])))
    if status:
        was, now = build_touch(rom, seed, 0), build_touch(rom, seed, status)
        for e in range(128):
            if was[2 * e:2 * e + 2] != now[2 * e:2 * e + 2]:
                print("  touch  %-9s %s  (was %s)" % (enemy_name(rom, e), touch_text(*now[2 * e:2 * e + 2]),
                                                     touch_text(*was[2 * e:2 * e + 2])))
    if scripts or skills:
        (ew, tw), (en, tn) = build_ai(rom, seed, 0, 0), build_ai(rom, seed, scripts, skills)
        for e in range(128):
            if ew[e] != en[e]:
                print("  script %-9s %s  (was %s)" % (enemy_name(rom, e),
                      "none" if en[e] == 0xFF else "#%d" % en[e], "none" if ew[e] == 0xFF else "#%d" % ew[e]))
        for i in range(44):
            if tw[i * 16:i * 16 + 16] != tn[i * 16:i * 16 + 16]:
                print("  script #%-2d %s" % (i, script_text(rom, tn[i * 16:i * 16 + 16])))
    if runs:
        norun = build_runs(rom, seed, runs)
        for f in range(256):
            if norun[f] and (f & 0x7F) < NORMAL_FORMS or f >= 0x80 + CHAOS_FORM + 1 and norun[f]:
                print("  cannot run  $%02X %s" % (f, formation_text(rom, f)))
    if surprise:
        was, now = build_surprise(rom, seed, 0), build_surprise(rom, seed, surprise)
        for f in range(NORMAL_FORMS):
            if was[f] != now[f]:
                print("  surprise    $%02X %3d (was %3d)  %s / %s"
                      % (f, now[f], was[f], formation_text(rom, f), formation_text(rom, 0x80 | f)))
    src = rom_props(rom)
    out = build_props(rom, seed, traps)
    for i in trap_offsets(src):
        ts, tile = divmod(i // 2, 128)
        print("  tileset %d tile $%02X: formation $%02X -> $%02X"
              % (ts, tile, src[i + 1], out[i + 1]))


if __name__ == "__main__":
    main()
