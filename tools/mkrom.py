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
    # zero fill -- bank 0's low half, and the million bytes past the last chunk.
    # A flash cart deciding HiROM against LoROM has nothing in the header to go
    # on here (the mapper fields are identical across builds it has accepted
    # and refused), so whatever it is keying on is content, and long runs of
    # zeros are the one thing that makes this image unlike every cartridge it
    # was built to recognise.  Mirror real data into them instead: the low half
    # of bank 0 repeats its own high half, which is what a chip with an unwired
    # address line would show, and the tail repeats the chunks.
    rom[0x0000:0x7FB0] = rom[0x8000:0xFFB0]     # ...stopping short of the
                                                # second header copy above
    tail = used
    while tail < ROMSZ:
        n = min(used - BANK, ROMSZ - tail)          # the chunks, less bank 0
        rom[tail:tail + n] = rom[BANK:BANK + n]
        tail += n

    # A second copy of the header, at the LoROM offset.
    #
    # Some flash-cart firmware reads the header at $7FC0 first and, if it
    # passes as a header, believes its map-mode byte -- falling back to $FFC0
    # only when it does not.  A HiROM image therefore maps correctly only if
    # the $7FC0 slot holds a valid header that itself says HiROM.  Ours held
    # zeros with a planted $31, which the checksum-pair test rejected before
    # the $31 was ever read.  So: the same header, twice.  The copy lives in
    # bank $C0's low half, which nothing in the port addresses.
    #
    # The checksum must then be computed with BOTH pairs zeroed and both
    # credited, or the two copies disagree with the sum.  See below.
    rom[0x7FB0:0x8000] = rom[0xFFB0:0x10000]

    # SNES checksum: zero the two fields, total the image, then add the $1FE
    # the complement and the checksum themselves will contribute.
    SLOTS = (0xFFDC, 0x7FDC)          # the pair, in both header copies
    for cs in SLOTS:
        for i in range(4):
            rom[cs + i] = 0
    total = (sum(rom) + 0x01FE * len(SLOTS)) & 0xFFFF
    comp = total ^ 0xFFFF
    for cs in SLOTS:
        rom[cs+0], rom[cs+1] = comp & 0xFF, comp >> 8
        rom[cs+2], rom[cs+3] = total & 0xFF, total >> 8
    cs = SLOTS[0]

    # Check the pair before writing it out.
    #
    # A Super Everdrive V2 decides HiROM vs LoROM partly on whether the
    # complement and the checksum add up to $FFFF, and it weights that far more
    # heavily than the published heuristics do.  Tested directly: an image whose
    # checksum value is simply wrong, but whose pair is well formed, is detected
    # as HiROM and runs; the same image with a malformed pair is detected as
    # LoROM and black screens.  Four bytes, one variable.  The cart never says a
    # word about a checksum either way, so a mistake here is invisible until the
    # console shows nothing.
    #
    # The pair is correct by construction above, so this only catches a future
    # change to that arithmetic -- which is exactly the mistake that would cost
    # another blind hardware round to find.
    check = (rom[cs+0] | (rom[cs+1] << 8)) + (rom[cs+2] | (rom[cs+3] << 8))
    if check != 0xFFFF:
        sys.exit("header checksum pair is malformed (sums to $%04X, want $FFFF); "
                 "a cart would read this as LoROM and refuse to boot" % check)
    verify = bytearray(rom)
    for c in SLOTS:
        for i in range(4):
            verify[c + i] = 0
    if (sum(verify) + 0x01FE * len(SLOTS)) & 0xFFFF != (rom[cs+2] | (rom[cs+3] << 8)):
        sys.exit("header checksum does not match the image")
    if rom[0x7FDC:0x7FE0] != rom[0xFFDC:0xFFE0] or rom[0x7FC0:0x7FDC] != rom[0xFFC0:0xFFDC]:
        sys.exit("the two header copies disagree")

    dst = os.path.join(ROOT, "FinalFantasy.sfc")
    open(dst, "wb").write(rom)
    print("%s: %d KB used of %d KB, checksum $%04X"
          % (os.path.basename(dst), used // 1024, ROMSZ // 1024, total))


if __name__ == "__main__":
    main()
