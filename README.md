# Final Fantasy (NES) -> SNES

A port of Disch's fully-commented Final Fantasy disassembly from the 6502/NES
to the 65816/SNES.  The game logic is not rewritten: the 65816 runs the
original code essentially verbatim, and everything that touched NES hardware is
translated instead.

    ./build.sh          # -> FinalFantasy.sfc  (2MB HiROM)
    tools/run.sh        # build, launch under ares, screenshot
    tools/drive.py "…"  # scripted play-through, see below

## How it works

**The CPU.** The game runs in 65816 *emulation* mode, where the chip is a 6502
in every respect that matters -- 8-bit registers, page-1 stack, zero page at
$0000.  That was chosen over native mode for fidelity: the magic menu performs
stack surgery with `TSX`/`TXS` that only works if the stack is forced to page 1.

**Memory.** HiROM, chosen because it is the map that puts SRAM at $6000-$7FFF,
exactly where the NES's PRG-RAM lived.  ROM bank 1+N is one "chunk":

    $8000-$BFFF   NES PRG bank N
    $C000-$FFFF   NES PRG bank $0F, the fixed bank, stamped into all 16 chunks

Game code executes with PBR = $A1+N, so the low half of the bank supplies the
SNES I/O map -- WRAM at $0000, PPU at $2100, SRAM at $6000 -- and the NES's
memory map lands on top of the SNES's almost unchanged.  ($A1 rather than $81
because HiROM only reliably decodes SRAM in banks $20-$3F/$A0-$BF; in a 2MB
image $A0+n mirrors $80+n, so it costs nothing.)

**Bank switching** is the program bank register.  `SwapPRG` returns into a
different PBR, with DBR following it so ROM data reads land in the right bank.

**Video.** There is no PPU emulation.  Writes to $2007 are filed straight into
WRAM shadows that are *already in SNES format* -- pattern bytes permuted into
4bpp planar order, nametable bytes into tilemap words, attribute bytes smeared
across the sixteen tilemap words they cover -- and DMA'd to VRAM at vblank.

**No interrupts.** WaitForVBlank polls $4212.  A 65816 in emulation mode loses
the program bank when it takes an interrupt, which would break bank switching.
The NMI handler's `LDA soft2000 / STA $2000` is done by hand each frame instead;
the game depends on it and nothing else writes $2000.

## Layout

    build.sh              build the ROM
    snes.cfg              link map
    src/hal.asm           the NES hardware the SNES pretends to be
    src/nesio.inc         macros the converter rewrites hardware accesses into
    src/nesio_thunks.inc  3-byte call sites, so no bank grows
    src/snesmap.inc       memory map and HAL variables
    src/header.asm        cartridge header and vectors
    tools/convert.py      rewrites the 6502 source; run by build.sh
    tools/genpal.py       NES palette -> CGRAM, from tenes/nespal.c
    patches/              routines that cannot be translated locally
    tools/drive.py        scripted input for testing

`patches/` holds whole-routine replacements -- reset, MMC1 bank switching, the
NMI/vblank handshake, the joypad reader, the scanline wait.  A patch whose "old"
text is not found verbatim is a hard error, so they cannot silently rot.

## Testing

ares takes the ROM on its command line; `open -a Snes9x` launches the app but
silently loads nothing, which looks exactly like a game that booted to black.

    STATE=1 python3 tools/drive.py "w5, h3:up, shot:castle"

Save state is bound to `t` and restore to `r` in ares' hotkey settings, and
slot 1 holds an overworld save, so tests start there rather than replaying
character creation.

## Status

Working: intro, title, character creation, overworld, map transitions, town and
castle interiors, battles with correct enemy and party graphics.

Not done: audio, the map-transition wipe (written, but disabled behind
ENABLE_RASTER_SPLITS), and the orb lighting effect.  pAPU writes are recorded in
a shadow register file for the eventual SPC700 driver.

Sprite-0 hit needs no emulation: the game never reads it.  Every BVS/BVC in the
codebase tests map tile properties, and all four BIT $2002 sites are there to
reset the $2005/$2006 write toggle, discarding the flag.  Final Fantasy times
its raster effects by counting CPU cycles instead, which is why those loops had
to become waits on the vertical counter.
