# Super Final Fantasy

This is a port of Final Fantasy (NES) on the SNES, with the QoL and bugfixes
ported from the FF1 community including Final Fantasy Randomizer, and a
randomizer on the cartridge. A love letter to the original Final Fantasy
game, and to the Final Fantasy Randomizer community that has sustained so
much interest in it.

The intent is to bring an interesting subset of the FFR experience to a
self-contained game runnable on original SNES hardware, for people who have
completed the original game dozens of times and are looking for some
variation at their leisure. It's not designed for racing - for that, visit
the vibrant Final Fantasy Randomizer community.

It remains a work in progress.

AI was heavily used in this production. Sorry. AI techslop follows:


The base is a port of Disch's fully-commented disassembly from the 6502/NES
to the 65816/SNES.  The game logic is not rewritten: the 65816 runs the
original code essentially verbatim, and everything that touched NES hardware
is translated instead.  On top of that sit the settings screen -- quality of
life, bugfixes, scaling, variations, key items, map shuffle and map edits,
under three presets -- and a randomizer that rolls the seed's world at New
Game on the console itself, porting FF1 Randomizer's (FFR's) rules rather
than needing its tool.

    ./build.sh                       # -> SuperFinalFantasy.sfc  (2MB HiROM)
    python3 tools/test_options.py    # the test suite, against the built ROM
    tools/run.sh                     # build, launch under ares, screenshot
    tools/drive.py "…"               # scripted play-through, see below

The build needs ca65/ld65 (cc65) and Python 3, nothing else; the game's
source and data are in the repository.

## How it works

**The CPU.** The game runs in 65816 *emulation* mode, where the chip is a 6502
in every respect that matters -- 8-bit registers, page-1 stack, zero page at
$0000.  That was chosen over native mode for fidelity: the magic menu performs
stack surgery with `TSX`/`TXS` that only works if the stack is forced to page 1.
The options code runs in emulation mode alongside the game; the randomizer
and the native screens run in native mode and drop back to call it.

**Memory.** HiROM, chosen because it is the map that puts SRAM at $6000-$7FFF,
exactly where the NES's PRG-RAM lived.  ROM bank 1+N is one "chunk":

    $8000-$BFFF   NES PRG bank N, or a bank this project adds
    $C000-$FFFF   NES PRG bank $0F, the fixed bank, stamped into every chunk

Game code executes with PBR = $A1+N, so the low half of the bank supplies the
SNES I/O map -- WRAM at $0000, PPU at $2100, SRAM at $6000 -- and the NES's
memory map lands on top of the SNES's almost unchanged.  ($A1 rather than $81
because HiROM only reliably decodes SRAM in banks $20-$3F/$A0-$BF; in a 2MB
image $A0+n mirrors $80+n, so it costs nothing.)  Chunks $00-$0F are the
NES's banks, $10 the altar beam's HDMA tables, and $11-$19 this project's
(`snesmap.inc`): the options bank, the credits, the randomizer, the settings
screen's text, the logic tables, entrance shuffle and the seed's logic, the
roll screen, Boss tactics and the map edit screen.  Each sees the fixed bank
at the usual address and reaches it with a plain `JSR`.

**Bank switching** is the program bank register.  `SwapPRG` returns into a
different PBR, with DBR following it so ROM data reads land in the right bank.

**Video.** There is no PPU emulation.  Writes to $2007 are filed straight into
WRAM shadows that are *already in SNES format* -- pattern bytes permuted into
4bpp planar order, nametable bytes into tilemap words, attribute bytes smeared
across the sixteen tilemap words they cover -- and DMA'd to VRAM at vblank.
The native screens (credits in mode 7, New Game's roll and map edit screens)
borrow the PPU outright through `hal_vblaudio` and give it back with
`hal_ppureclaim`, which rebuilds the picture from the untouched shadows.

**No interrupts.** WaitForVBlank polls $4212.  A 65816 in emulation mode loses
the program bank when it takes an interrupt, which would break bank switching.
The NMI handler's `LDA soft2000 / STA $2000` is done by hand each frame instead;
the game depends on it and nothing else writes $2000.  Long work, such as the
randomizer at New Game, keeps a screen alive by ticking it from
`rando_yield` whenever RDNMI says a vblank has begun -- and a tick that
writes VRAM checks the V counter first, since it can arrive late.

**Audio** is an SPC700 driver fed from the pAPU shadow: two pulses with duty,
sweep and envelope, the triangle with its linear counter, and noise with
envelope and length counter.  The waveforms are BRR, sized per note, so a bass
note carries harmonics the Gaussian interpolation would otherwise eat.

## The options and the randomizer

The title screen leads to the settings screen; Select on Continue shows a
save's settings.  Vanilla, Improved (FFR's Improved Vanilla) and Super are
presets, and any change makes it Custom.  The settings live in an option block
in SRAM, and most apply to an existing save at once.  The randomizing rows
take effect at New Game, which rolls a seed (or takes `FFSEED`) and builds
the world from it: shuffled treasures, shops, magic, formations and enemy
scripts; key items placed by FFR's PredictivePlacement over the world's
logic; entrance and floor shuffle; FFR's fourteen overworld map edits on a
screen of their own, which turns the ocean red when the ticked edits and the
rest of the settings cannot be won.  FFR's tuning is the default, and the
deviations are recorded.

`docs/options-design.md` is the live description of all of it -- every
setting, how it is stored, what reads it, the bank budgets, and "Things
learned the hard way" -- and is updated with each change it describes.  A
feature is "built, not yet played" in its commit and its docs until it has
been played on a console.

## Layout

    build.sh              build the ROM
    snes.cfg              link map
    game/                 the 6502 source, and the game's own binary data
    src/hal.asm           the NES hardware the SNES pretends to be
    src/nesio.inc         macros the converter rewrites hardware accesses into
    src/nesio_thunks.inc  3-byte call sites, so no bank grows
    src/snesmap.inc       memory map, chunks and HAL variables
    src/header.asm        cartridge header and vectors
    src/opt*.asm          the options bank, the settings screen, its text
    src/rando.asm         the randomizer: PRNG, New Game, its hooks
    src/place.inc         key item placement (FFR's PredictivePlacement)
    src/world.asm         entrance shuffle and the seed's logic (entrance.inc)
    src/logicdata.asm     the vanilla world's logic tables
    src/owscreen.asm      New Game's map edit screen
    src/roll.asm          New Game's roll screen
    src/credits.asm       the credits, in mode 7
    src/tactics.asm       Boss tactics
    tools/convert.py      rewrites the 6502 source; run by build.sh
    tools/gen*.py         tables and pictures generated at build time
    tools/mkrom.py        assembles the image
    tools/cpu65816.py     a 65816 for the tests
    tools/test_options.py the test suite
    tools/randoref.py     the randomizer's reference model in Python
    tools/check*.py       build-time checks, and placement and logic sweeps
    tools/mutate.py       breaks the source on purpose to show tests bite
    tools/drive.py        scripted input for testing
    patches/              routines that cannot be translated locally
    patches/debug/        gated behind FFDEBUG; never in a normal build
    worldgraph/           the world as a graph, which the logic is distilled from
    docs/                 design notes; options-design.md is the live one

`game/` is the 6502 source the port is built from.  It used to be read from a
sibling checkout, which made the build depend on a path outside the repository
and left the game's own code somewhere this project could not change.  It is
vendored now, so a clone builds on its own and bugfixes can edit the game
directly rather than only through `patches/`.

`patches/` holds whole-routine replacements -- reset, MMC1 bank switching, the
NMI/vblank handshake, the joypad reader, the scanline wait, and the bugfixes
and hooks the options need.  A patch whose "old" text is not found verbatim is
a hard error, so they cannot silently rot.

FF1 Randomizer's C# source is not part of the repository.  When it sits
beside it (`../FF1Randomizer/`, or at `FFR_ROOT`), `worldgraph/` checks its
model against FFR's and a few tests check transcriptions against FFR's
source; without it, those checks are skipped and the build is unaffected.

## Debug builds

`patches/debug/` is a separate tree, and the distinction is the point: patches
under `patches/bank_XX/` are the port, and a build without them is not the game.
Patches under `patches/debug/bank_XX/` change how the game plays, to put an
effect that is normally hours away in front of a fresh save, and apply only when
FFDEBUG asks for them:

    epilogue            entering any standard map runs the ending scene instead
                        (the "The End" pen-plot into CHR RAM); loops forever
    chaos_form          every random encounter is formation $7B, Chaos, so the
                        end-of-battle dissolve can be watched
    chaos_weakenemies   every enemy loads with 1 HP and no defence, evasion or
                        strength
    chaos_noai          every enemy reads as "no AI script", so none of them cast
    altar_tiles         five orb altars in Coneria -- a column at x=$14,
                        y=$0E..$11, and one on the path at x=$10, y=$14, three
                        steps up from the town entrance
    altar_rearm         altars lose their "already lit" check, so they re-fire
    house               nine HOUSEs in the bag at New Game
    menumusic           the title plays the start menu's music
    menusfx, errsfx     the title plays the menus' chirps, or the error sound,
                        on a timer -- listening tests for the audio driver
    trackcycle          the title alternates music tracks every 256 frames

A tag matches any patch whose name contains it, and the names are grouped so a
tag brings a whole setup: `FFDEBUG=chaos` fetches chaos_form along with the two
patches that make the fight survivable, which is the only way it is any use.

The chaos patches add no code: bank $0C is full to the byte, so they re-point
the ROM-to-RAM stat table and the AI-id read at offsets that already hold the
constants wanted ($01, $00, $FF in Chaos's record).

Some tags are not patches but ca65 defines set by build.sh, where each is
explained: `dark` blackens the town's grass so the altar beam can be judged
against a dungeon's black; `apustat` paints the triangle's state as three bars;
`tone`, `trisweep`, `trionly`, `pulse1`, `pulse2` and `noiseonly` isolate the
audio; `owedits` turns every overworld map edit on whatever the save says;
`vanilla`, `improved` and `super` force a preset on every boot.
`FFSEED=xxxxxxxx` gives every new game that seed, so a world can be
reproduced on a console without a battery file.

`FFDEBUG=1` (or `all`) turns on every patch, which is rarely wanted: epilogue
takes over every standard map, so it and altar_tiles cannot both be on and still
let you walk into a town.  A normal build never sees any of this --
`./build.sh` alone skips every `debug_*` patch.

## Testing

    ./build.sh && python3 tools/test_options.py [test_name ...]

The suite runs the built ROM's own code on `tools/cpu65816.py`: the option
hooks, the randomizer against `tools/randoref.py`, the menus and screens down
to the tilemap, VRAM and palette they leave.  It hands itself to pypy3 when that
is installed, several times faster than CPython.  The harness models no time --
waits on the PPU are let through, and every VRAM write lands -- so timing
bugs need a test that sets the counters it reads, or play.  `tools/mutate.py`
applies a list of deliberate bugs, each in its own copy of the tree, and
reports which tests caught them.  `tools/checkplace.py`, `checkentrance.py`
and `checkwin.py` sweep placement, entrance shuffle and winnability over many
seeds and settings.

ares takes the ROM on its command line; `open -a Snes9x` launches the app but
silently loads nothing, which looks exactly like a game that booted to black.

    STATE=1 python3 tools/drive.py "w5, h3:up, shot:castle"

Save state is bound to `t` and restore to `r` in ares' hotkey settings, and
slot 1 holds an overworld save, so tests start there rather than replaying
character creation.

## Status

The port is functionally complete.  Intro, title, character creation,
overworld, map transitions, town and castle interiors, battles, menus, the
minimap, shops and dialogue, the battle transition with its colour cycling,
the map-transition wipe, the orb lighting, and the endgame -- Chaos's dissolve
and the epilogue, including its pen-plot of "The End" into CHR RAM a pixel at
a time.  The options and the randomizer are in progress;
`docs/options-design.md` §10 says what is done and what has been played.

Known gaps in the port, none of them observed to matter in play:

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
