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
    game/                 the 6502 source, and the game's own binary data
    src/hal.asm           the NES hardware the SNES pretends to be
    src/nesio.inc         macros the converter rewrites hardware accesses into
    src/nesio_thunks.inc  3-byte call sites, so no bank grows
    src/snesmap.inc       memory map and HAL variables
    src/header.asm        cartridge header and vectors
    tools/convert.py      rewrites the 6502 source; run by build.sh
    tools/genpal.py       NES palette -> CGRAM, from tenes/nespal.c
    patches/              routines that cannot be translated locally
    tools/drive.py        scripted input for testing

`game/` is the 6502 source the port is built from.  It used to be read from a
sibling checkout, which made the build depend on a path outside the repository
and left the game's own code somewhere this project could not change.  It is
vendored now, so a clone builds on its own and bugfixes can edit the game
directly rather than only through `patches/`.

`patches/` holds whole-routine replacements -- reset, MMC1 bank switching, the
NMI/vblank handshake, the joypad reader, the scanline wait.  A patch whose "old"
text is not found verbatim is a hard error, so they cannot silently rot.

A patch named `debug_*` applies only when the build is run with FFDEBUG set.
These change how the game plays, to put an effect that is normally hours away in
front of a fresh save:

    debug_epilogue      entering any standard map runs the ending scene instead
                        (the "The End" pen-plot into CHR RAM); loops forever
    debug_chaosform     every random encounter is formation $7B, Chaos, so the
                        end-of-battle dissolve can be watched
    debug_weakenemies   every enemy loads with 1 HP and no defence, evasion or
                        strength
    debug_noai          every enemy reads as "no AI script", so none of them cast
    debug_altartiles    five orb altars in Coneria -- a column at x=$14,
                        y=$0E..$11, and one on the path at x=$10, y=$14, three
                        steps up from the town entrance
    debug_altarearm     altars lose their "already lit" check, so they re-fire

One tag is not a patch at all: `dark` blackens the town's grass (NES $1A) in
flush_pal, so the altar beam can be judged against the black background a
dungeon would give it rather than against Coneria's green.  It is a HAL change,
so it rides on a ca65 define set by build.sh rather than the patch-name gate.

`FFDEBUG=1` (or `all`) turns on every one, which is rarely wanted: debug_epilogue
takes over every standard map, so it and debug_altartiles cannot both be on and
still let you walk into a town.  `FFDEBUG=<tag>[,<tag>...]` applies only the
patches whose names contain a tag -- `FFDEBUG=altar`, `FFDEBUG=chaos`.

The last two add no code: bank $0C is full to the byte, so they re-point the
ROM-to-RAM stat table and the AI-id read at offsets that already hold the
constants wanted ($01, $00, $FF in Chaos's record).  A normal build never sees
any of this -- `./build.sh` alone skips every `debug_*` patch.

## Testing

ares takes the ROM on its command line; `open -a Snes9x` launches the app but
silently loads nothing, which looks exactly like a game that booted to black.

    STATE=1 python3 tools/drive.py "w5, h3:up, shot:castle"

Save state is bound to `t` and restore to `r` in ares' hotkey settings, and
slot 1 holds an overworld save, so tests start there rather than replaying
character creation.

## Status

Functionally complete.  Intro, title, character creation, overworld, map
transitions, town and castle interiors, battles, menus, the minimap, shops and
dialogue, the battle transition with its colour cycling, the map-transition
wipe, the orb lighting, and the endgame -- Chaos's dissolve and the epilogue,
including its pen-plot of "The End" into CHR RAM a pixel at a time.

Audio is an SPC700 driver fed from the pAPU shadow: two pulses with duty, sweep
and envelope, the triangle with its linear counter, and noise with envelope and
length counter.  The waveforms are BRR, sized per note, so a bass note carries
harmonics the Gaussian interpolation would otherwise eat.

Known gaps, none of them observed to matter in play:

  - The triangle's length counter is not modelled.  The linear counter is, and
    that is what the driver's silence writes actually drive, but the
    disassembly says "length or linear" -- so the triangle can sound in cases
    where hardware would not.
  - h_apuok is a one-way latch.  It is set once at boot and cleared for good if
    apu_send ever times out, which would take all audio down for the session
    with no way back.  Nothing has been seen to trigger it.
  - The triangle stopped sounding once inside the start menu and recovered on
    leaving it.  Never reproduced.  The orbfx merge commit records what the
    symptom rules out and where to start if it recurs.

ENABLE_RASTER_SPLITS is off and cannot be made to work; the note beside it
explains why the game's cycle-counted split positions are not recoverable here.
The wipe is drawn instead from the two variables the game already keeps, as
three spans of an HDMA table over TM -- see hal_wipewindow.

Sprite-0 hit needs no emulation: the game never reads it.  Every BVS/BVC in the
codebase tests map tile properties, and all four BIT $2002 sites are there to
reset the $2005/$2006 write toggle, discarding the flag.  Final Fantasy times
its raster effects by counting CPU cycles instead, which is why those loops had
to become waits on the vertical counter.
