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


def read(path, want):
    d = open(path, "rb").read()
    if len(d) != want:
        sys.exit("%s: expected %d bytes, got %d" % (path, want, len(d)))
    return d


def nesbank(name):
    if name in ASSEMBLED:
        return read(os.path.join(OUT, "bank_%s.bin" % name), 0x4000)
    return read(os.path.join(NES, "bank_%s.dat" % name), 0x4000)


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

    used = (2 + len(ORDER)) * BANK

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

    dst = os.path.join(ROOT, "FinalFantasy.sfc")
    open(dst, "wb").write(rom)
    print("%s: %d KB used of %d KB, checksum $%04X"
          % (os.path.basename(dst), used // 1024, ROMSZ // 1024, total))


if __name__ == "__main__":
    main()
