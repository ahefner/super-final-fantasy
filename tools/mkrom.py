#!/usr/bin/env python3
"""
mkrom.py -- lay the linked pieces out as a HiROM image.

ROM bank 0        low half unused, HAL at $8000, header at $FFB0
ROM bank 1+N      low half unused, NES bank N at $8000, NES bank $0F at $C000

Running the game with PBR = $A1+N therefore puts NES bank N at $8000-$BFFF and
the fixed bank at $C000-$FFFF, which is exactly the map the MMC1 gave it -- and
because those banks also carry the SNES low-bank I/O map, the NES's RAM, its
PRG-RAM at $6000-$7FFF and the hardware registers all land where the code
already expects them.

The price is sixteen copies of the fixed bank, which is 240KB out of a 2MB
cartridge.

A previous revision spaced the chunks two banks apart, all on odd banks, so that
a 16KB SRAM paged by the low bank bit would give the HAL 8KB the game could not
reach -- somewhere to record traces.  That worked, and the trace channel found
real bugs, but the resulting cartridge shape (16KB SRAM paged by bank parity, a
2MB image half full of interleaved holes) is nothing like an ordinary HiROM
cart, and a Super Everdrive V2 misdetected such images as LoROM and refused to
boot them.  Instrumenting the emulator turned out to be the better tool anyway.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NES  = os.path.join(ROOT, "game")        # the vendored 6502 source
OUT  = os.path.join(ROOT, "out")

BANK   = 0x10000
ROMSZ  = 32 * BANK               # 2MB, the size declared in the header

# Which banks came out of the assembler, and which are still raw data blobs.
ASSEMBLED = {"01", "09", "0B", "0C", "0D", "0E", "0F"}
ORDER     = ["%02X" % n for n in range(16)]

# Chunks beyond the NES banks: {chunk number: out/bank_<name>.bin}.
# The CHUNK_ numbers in src/snesmap.inc must agree with the keys here,
# and the keys must run on from $11 without a gap: the image is assumed dense
# up to the last of them when it is mirrored out to 2MB below.
EXTRA_CHUNKS = {0x11: "OPT", 0x12: "CREDITS", 0x13: "RANDO", 0x14: "OPTTEXT", 0x15: "LOGIC",
                0x16: "WORLD", 0x17: "ROLL", 0x18: "TACTICS", 0x19: "OWS", 0x1A: "NEWGAME",
                0x1B: "OPTMENU"}


def read(path, want):
    d = open(path, "rb").read()
    if len(d) != want:
        sys.exit("%s: expected %d bytes, got %d" % (path, want, len(d)))
    return d


#  Tiles laid over a raw data bank.  The tileset CHR bank is vendored data
#  with no assembler pass to patch, and Chests Appear Opened needs two tiles
#  that vanilla does not have.  CHR $7E and $7F are referenced by no TSA entry
#  in any of the eight tilesets, so they are free to take; each tileset gets
#  its own $800 of CHR, and the same lid serves all of them.
OPENCHEST_TILE = 0x7E
TILESET_CHR_BANK = "03"
TILESET_CHR_SIZE = 0x800
TILESET_COUNT = 8


def overlay_openchest(data):
    art = read(os.path.join(OUT, "openchest.chr"), 32)
    out = bytearray(data)
    for ts in range(TILESET_COUNT):
        at = ts * TILESET_CHR_SIZE + OPENCHEST_TILE * 16
        out[at:at + 32] = art
    return bytes(out)


#  The menu font has no plus sign.
#
#  FFR's character table puts "+" at $7B and "/" at $7A, and DrawComplexString
#  draws both literally -- but LoadMenuCHR loads tiles $80-$FF and nothing
#  else, so those two land in whatever page happens to be at PPU $0000.  FFR
#  can rely on them because it rebuilds CHR loading around a new bank; here
#  $7B is shop scenery in a shop and orb graphics in a menu, so it is not
#  available in both.
#
#  So the glyph goes in the font page instead, which every screen that draws
#  text has loaded.  $C1 is the one slot in $80-$FF with no art in it.
#
#  That last sentence is the whole rule, and it took two wrong answers to
#  arrive at.  The top of the font page is not kana, it is battle-UI artwork:
#  runs of condensed lettering whose letters straddle the tile boundaries, the
#  ailment names at $E2-$EA ("Poison" $E2-$E5, "Stone" $E6-$E9, "Asleep"
#  ending on $EA) and the command labels at $EB-$F6 ("MAGIC" $EB-$EE, "FIGHT"
#  $EF-$F2, "DRINK" $F3-$F6).  $E6 put a plus through the S of "Stone"; $EC
#  put one through "MAGIC".
#
#  Neither was findable by surveying text, which is why both got through: the
#  ailment names live in data_BattleMessages as raw tile bytes behind a pointer
#  table, and the command labels are .BYTE runs inside bank $0F.  The test that
#  holds this now asks a question that does not depend on finding every string
#  -- the stock font must have no ink in the tile we paint over.  $E6 and $EC
#  both had ink.  $C1 and $FF are the only two that do not, and $FF is space.
#
#  The font stores its background in plane 1: a blank tile is $00 x8 then
#  $FF x8, ink is a set bit in plane 0.  The stroke matches the hyphen at
#  $C2, which is row 4, columns 2-6.
PLUS_CODE = 0xC1
PLUS_ART = ["........",
            "........",
            "....X...",
            "....X...",
            "..XXXXX.",
            "....X...",
            "....X...",
            "........"]
MENUCHR_BANK = "09"
MENUFONT_OFF = 0x0800           # $8800 in the bank, the tiles for $80-$FF


def overlay_plus(data):
    out = bytearray(data)
    at = MENUFONT_OFF + (PLUS_CODE - 0x80) * 16
    for y, row in enumerate(PLUS_ART):
        out[at + y] = sum(1 << (7 - x) for x, c in enumerate(row) if c == "X")
        out[at + 8 + y] = 0xFF
    return bytes(out)


#  The Ribbon's name is eight bytes where every other weapon and armour name in
#  the cartridge is seven, and seven is the field the shop draws.  "Ribbon"
#  followed by two spaces, so the eighth is padding that writes a blank over the
#  right-hand border of the name box -- visible when selling armour to a
#  character carrying one, and not visible for longer names like "Dragon" plus
#  its icon, which are seven and fit.
#
#  Trimming the terminator back by one leaves "Ribbon " and changes no glyph.
#  FFR does exactly this, in FF1Text.cs: ItemNames.Write opens with a
#  FixRibbonSpace() that drops character 7 when it is a space, unconditionally,
#  so every FFR rom has it fixed.  Armor.cs's "Don't adjust vanilla Ribbon with
#  no icon" is a separate decision about shortening names to fit an icon and
#  says nothing about the box.
#
#  The expected bytes are asserted rather than assumed: this is vendored data,
#  and a patch that silently matches nothing is worse than no patch.
ITEMS_BANK = "0A"
RIBBON_AT = 0x3BF5
RIBBON_WAS = bytes([0x9B, 0xAC, 0xA5, 0xA5, 0xB2, 0xB1, 0xFF, 0xFF, 0x00])


def overlay_ribbon(data):
    at = RIBBON_AT
    if data[at:at + len(RIBBON_WAS)] != RIBBON_WAS:
        sys.exit("bank_0A: the Ribbon name is not where it was ($%04X)" % at)
    out = bytearray(data)
    out[at + 7] = 0x00              # terminate after seven, as the field is
    return bytes(out)


#  Two stray objects in the map object tables (lut_MapObjects, $B400 of bank
#  $00: fifteen three-byte slots a map, id, x and flags, y; id 0 is empty).
#  Each is a second copy of a quest object: the fairy ($13) in Ice Cave B1 as
#  well as Gaia, and the rod plate ($16) in Sky Palace 2F as well as Earth
#  Cave B3, each alone in slot 0 of its map.  The fairy stands in Ice Cave
#  B1's outer void, joined to nothing, once the bottle is opened.  The plate
#  stands inside a wall, shown until the ROD is used anywhere -- which vanilla
#  always does before Sky Palace, and a placed ROD need not.  Removed,
#  unconditionally (user, 2026-10-14): neither can be reached, the plate can
#  be seen, and the world graph, which reads the cart, has one of each.
#  Asserted, as the Ribbon is.
OBJINFO_BANK = "00"
MAPOBJ_OFF = 0xB400 - 0x8000
MAPOBJ_STRIDE = 0x30
STRAY_OBJECTS = [(15, 0, bytes([0x13, 0x6F, 0x1E])),     # Ice Cave B1: the fairy
                 (48, 0, bytes([0x16, 0xDA, 0x1B]))]     # Sky Palace 2F: the rod plate


def overlay_strays(data):
    out = bytearray(data)
    for m, slot, was in STRAY_OBJECTS:
        at = MAPOBJ_OFF + m * MAPOBJ_STRIDE + slot * 3
        if data[at:at + 3] != was:
            sys.exit("bank_00: map %d's slot %d is not the stray it was" % (m, slot))
        out[at:at + 3] = bytes(3)
    return bytes(out)


def nesbank(name):
    if name in ASSEMBLED:
        data = read(os.path.join(OUT, "bank_%s.bin" % name), 0x4000)
        if name == MENUCHR_BANK:
            data = overlay_plus(data)
        return data
    data = read(os.path.join(NES, "bank_%s.dat" % name), 0x4000)
    if name == TILESET_CHR_BANK:
        data = overlay_openchest(data)
    if name == ITEMS_BANK:
        data = overlay_ribbon(data)
    if name == OBJINFO_BANK:
        data = overlay_strays(data)
    return data


def main():
    hal = read(os.path.join(OUT, "hal.bin"), 0x7FB0)
    hdr = read(os.path.join(OUT, "hdr.bin"), 0x0050)
    fixed = nesbank("0F")

    rom = bytearray(ROMSZ)
    rom[0x8000:0x8000 + len(hal)] = hal            # ROM bank 0: HAL...
    rom[0x10000 - len(hdr):0x10000] = hdr          # ...and the header at its tail

    for i, name in enumerate(ORDER):               # ROM banks 1..16
        base = (1 + i) * BANK
        rom[base + 0x8000:base + 0xC000] = nesbank(name)
        rom[base + 0xC000:base + 0x10000] = fixed
        # The low half is never addressed -- the game runs in banks $A1+ where
        # that range is I/O, WRAM and SRAM -- so mirror the high half into it
        # rather than leave 32KB of zeros in every chunk (see below).
        rom[base:base + 0x8000] = rom[base + 0x8000:base + 0x10000]

    #  Chunks this project adds, beyond the NES's sixteen.  Each one is laid
    #  out exactly like a game chunk -- new code at $8000-$BFFF, the fixed bank
    #  stamped into $C000-$FFFF -- so a routine there sees the address space
    #  the game's own banks see and reaches the fixed bank with a 16-bit JSR.
    #  Chunk N is image bank 1+N, which is what PBR CHUNK0+N decodes to.
    #
    #  $10 is skipped: image bank 17 is the altar beam's tables, below.
    for chunk, name in EXTRA_CHUNKS.items():
        base = (1 + chunk) * BANK
        rom[base + 0x8000:base + 0xC000] = read(
            os.path.join(OUT, "bank_%s.bin" % name), 0x4000)
        rom[base + 0xC000:base + 0x10000] = fixed
        rom[base:base + 0x8000] = rom[base + 0x8000:base + 0x10000]

    #  The altar beam's HDMA tables, pre-built by genbeam.py.  They get a bank
    #  of their own because HDMA reads them straight out of ROM: nothing has to
    #  copy them anywhere, and the CPU spends nothing per frame beyond pointing
    #  a channel at the right offset.  HiROM puts image bank N at SNES bank
    #  $C0+N, so this one is $D1 -- BEAMBANK in snesmap.inc.
    beam = open(os.path.join(OUT, "beam.bin"), "rb").read()
    if len(beam) > BANK:
        sys.exit("beam.bin is %d bytes, more than one bank" % len(beam))
    beambank = 1 + len(ORDER)
    rom[beambank * BANK:beambank * BANK + len(beam)] = beam

    used = (2 + len(ORDER) + len(EXTRA_CHUNKS)) * BANK

    # Make the image dense, as a real cartridge is.
    #
    # A real HiROM cart is ROM from end to end; ours had two large regions of
    # zero fill -- bank 0's low half, and the million bytes past the last
    # chunk.  The low half of bank 0 repeats its own high half, which is what a
    # chip with an unwired address line would show, and the tail repeats the
    # chunks.
    #
    # The original reason given for this was wrong, and is recorded because the
    # mistake is instructive.  Lacking a disassembly, it was guessed that the
    # flash cart keys its HiROM/LoROM decision on content -- that long runs of
    # zeros were what made the image unlike a cartridge.  It does no such thing:
    # it reads four bytes at 0x7FDC (see below and NOTES-rom-detect.md).  Worse,
    # mirroring bank 0 is what put a valid checksum pair at that very offset, so
    # the change made to cure the misdetection was the thing causing it.
    #
    # The mirroring stays because a dense image is harmless and arguably more
    # faithful, but nothing depends on it.
    rom[0x0000:0x7FB0] = rom[0x8000:0xFFB0]     # ...stopping short of the
                                                # second header copy above
    tail = used
    while tail < ROMSZ:
        n = min(used - BANK, ROMSZ - tail)          # the chunks, less bank 0
        rom[tail:tail + n] = rom[BANK:BANK + n]
        tail += n

    # A second copy of the header, at the LoROM offset -- with its checksum
    # pair deliberately left zero.
    #
    # An earlier revision put a *valid* pair there, on the theory that the
    # Super EverDrive reads the header at $7FC0 first and believes its map-mode
    # byte.  Disassembly of the cart's OS (see NOTES-rom-detect.md) shows that
    # theory was wrong in the one way that mattered.  sub_81B457 never reads
    # the map-mode byte at all.  What it does is probe ROM offset 0x7FDC, and
    # if the four bytes there form a consistent checksum pair that is neither
    # 0000 nor FFFF, it declares the image LoROM and never looks at 0xFFB0.
    #
    # Because bank 0's low half mirrors its high half here, that copy carried a
    # perfectly good pair -- so the cart read this HiROM cartridge as LoROM
    # every single time, and the better the checksum was, the more certain the
    # misdetection.  Zeroing the pair makes probe 1 fail (chk == 0 is rejected
    # outright), the loader falls through to 0xFFB0, and the real pair there
    # answers.  The rest of the header copy is harmless and is left in place.
    rom[0x7FB0:0x8000] = rom[0xFFB0:0x10000]

    MIRROR, REAL = 0x7FDC, 0xFFDC

    # SNES checksum: zero both fields, total the image, then add back the $1FE
    # that the complement and checksum will themselves contribute -- once, now,
    # because only the real pair is ever filled in.
    for off in (MIRROR, REAL):
        for i in range(4):
            rom[off + i] = 0
    total = (sum(rom) + 0x01FE) & 0xFFFF
    comp = total ^ 0xFFFF
    rom[REAL+0], rom[REAL+1] = comp & 0xFF, comp >> 8
    rom[REAL+2], rom[REAL+3] = total & 0xFF, total >> 8

    # Check it the way the cart does, rather than checking the parts.
    #
    # This is sub_81B457's test, transcribed: a pair counts only if the
    # checksum is the one's complement of the complement field and is neither
    # 0000 nor FFFF.  Probe 1 must fail and probe 2 must pass, or the cart maps
    # the cartridge wrongly and the console shows nothing -- a failure mode that
    # says nothing about itself and costs a hardware round-trip to find.
    def pair_valid(off):
        cmpl = rom[off + 0] | (rom[off + 1] << 8)
        chk  = rom[off + 2] | (rom[off + 3] << 8)
        return chk == (~cmpl & 0xFFFF) and chk not in (0x0000, 0xFFFF)

    if pair_valid(MIRROR):
        sys.exit("the mirrored checksum pair at 0x%04X is valid; a Super "
                 "EverDrive would read this as LoROM" % MIRROR)
    if not pair_valid(REAL):
        sys.exit("the checksum pair at 0x%04X is not valid (complement $%04X, "
                 "checksum $%04X)" % (REAL,
                 rom[REAL] | (rom[REAL+1] << 8), rom[REAL+2] | (rom[REAL+3] << 8)))

    verify = bytearray(rom)
    for off in (MIRROR, REAL):
        for i in range(4):
            verify[off + i] = 0
    if (sum(verify) + 0x01FE) & 0xFFFF != total:
        sys.exit("header checksum does not match the image")

    dst = os.path.join(ROOT, "SuperFinalFantasy.sfc")
    open(dst, "wb").write(rom)
    print("%s: %d KB used of %d KB, checksum $%04X"
          % (os.path.basename(dst), used // 1024, ROMSZ // 1024, total))


if __name__ == "__main__":
    main()
