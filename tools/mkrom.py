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
NES  = os.path.join(os.path.dirname(ROOT), "FF1Disassembly", "Final Fantasy Disassembly")
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

    used = (1 + len(ORDER)) * BANK

    # Poison the LoROM header position.
    #
    # A flash cart or emulator decides HiROM vs LoROM by scoring the bytes at
    # both candidate header offsets, $FFC0 and $7FC0.  Ours is a HiROM image, so
    # $7FB0-$7FFF is simply unused -- bank $C0's low half, which nothing in the
    # port ever addresses.  Left as the zero fill, though, it collects points it
    # has no business collecting: a zero map-mode byte reads as "even, therefore
    # LoROM" (+3), and a zero at $7FD0 has a low nibble under 4 (+2).
    #
    # Writing two bytes takes both away.  Under the snes9x scoring that most of
    # these detectors descend from, that widens HiROM's margin from 10 to 15.
    # It is not a diagnosis -- the header fields that actually select the mapper
    # are identical to those of builds that boot, and this margin was already
    # decisive -- but the bytes are free and a wider margin can only help.
    rom[0x7FD5] = 0x31              # odd map mode: not the LoROM shape
    rom[0x7FD0] = 0x0F              # low nibble >= 4

    # SNES checksum: zero the two fields, total the image, then add the $1FE
    # the complement and the checksum themselves will contribute.
    cs = 0xFFDC
    for i in range(4):
        rom[cs + i] = 0
    total = (sum(rom) + 0x01FE) & 0xFFFF
    comp = total ^ 0xFFFF
    rom[cs+0], rom[cs+1] = comp & 0xFF, comp >> 8
    rom[cs+2], rom[cs+3] = total & 0xFF, total >> 8

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
    for i in range(4):
        verify[cs + i] = 0
    if (sum(verify) + 0x01FE) & 0xFFFF != (rom[cs+2] | (rom[cs+3] << 8)):
        sys.exit("header checksum does not match the image")

    dst = os.path.join(ROOT, "FinalFantasy.sfc")
    open(dst, "wb").write(rom)
    print("%s: %d KB used of %d KB, checksum $%04X"
          % (os.path.basename(dst), used // 1024, ROMSZ // 1024, total))


if __name__ == "__main__":
    main()
