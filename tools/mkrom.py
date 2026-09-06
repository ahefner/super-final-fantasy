#!/usr/bin/env python3
"""
mkrom.py -- lay the linked pieces out as a HiROM image.

ROM bank 0        low half unused, HAL at $8000, header at $FFB0
ROM bank 1+2N     low half unused, NES bank N at $8000, NES bank $0F at $C000
ROM bank 2+2N     unused

Running the game with PBR = $A1+2N therefore puts NES bank N at $8000-$BFFF and
the fixed bank at $C000-$FFFF, which is exactly the map the MMC1 gave it -- and
because those banks also carry the SNES low-bank I/O map, the NES's RAM, its
PRG-RAM at $6000-$7FFF and the hardware registers all land where the code
already expects them.

The chunks are two banks apart, and all of them odd, to buy somewhere to put
trace data.  The cart declares 16KB of SRAM, and a HiROM board pages that by the
low bank bit: even banks see the first 8KB, odd banks the second.  Every chunk
being odd means the game sees one consistent 8KB no matter which bank is swapped
in, and the even-bank page -- reachable from the HAL at bank $C0 -- is 8KB the
game can never touch.  Every other region of the game's own SRAM turned out to
be live during play, which is what made this worth the empty banks.

The price is sixteen copies of the fixed bank plus sixteen empty banks; the
image was already declared 2MB and now essentially fills it.
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

    for i, name in enumerate(ORDER):               # ROM banks 1, 3, 5 ... 31
        base = (1 + 2 * i) * BANK
        rom[base + 0x8000:base + 0xC000] = nesbank(name)
        rom[base + 0xC000:base + 0x10000] = fixed

    used = (1 + 2 * (len(ORDER) - 1) + 1) * BANK

    # SNES checksum: zero the two fields, total the image, then add the $1FE
    # the complement and the checksum themselves will contribute.
    cs = 0xFFDC
    for i in range(4):
        rom[cs + i] = 0
    total = (sum(rom) + 0x01FE) & 0xFFFF
    comp = total ^ 0xFFFF
    rom[cs+0], rom[cs+1] = comp & 0xFF, comp >> 8
    rom[cs+2], rom[cs+3] = total & 0xFF, total >> 8

    dst = os.path.join(ROOT, "FinalFantasy.sfc")
    open(dst, "wb").write(rom)
    print("%s: %d KB used of %d KB, checksum $%04X"
          % (os.path.basename(dst), used // 1024, ROMSZ // 1024, total))


if __name__ == "__main__":
    main()
