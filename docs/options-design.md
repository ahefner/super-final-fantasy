# Super Final Fantasy -- options menu design

Design decisions for the runtime options system: the menu, the flag set, how
settings are stored, and how each one reaches the game.  Companion to
`analysis.md`, which covers the bank/space architecture this depends on.

Status: design settled.  Implementation in progress -- see "Implementation
status" at the end.  Line references are to the tree at commit d98ea12
and were checked against it.


## 1. Screen design

### Title screen

The existing title screen is the basis.  It currently draws three boxes --
Continue at (11,10), New Game at (11,15), Respond Rate at (8,20), each 4 rows
tall.

**The visible area is tile rows 1-28, not 0-29.**  The HAL sets 224-line mode
and shows NES lines 8..231 (`src/hal.asm:3986`), cropping the way a
television did -- deliberately, because the game rebuilds the wrapping map row
in what it assumes is overscan.  So row 0 and row 29 never reach the screen,
and every layout below is budgeted against 28 usable rows.

That leaves rows 24-28 free below the Respond Rate box.  `EnterTitleScreen` is
at
`game/bank_0E.asm:3472`.

A fourth box goes at (8,24), 16 wide, showing the active preset.  The cursor
grows from two positions to three (Continue / New Game / Options); it is a
sprite drawn from `lut_TitleCursor_Y` (`game/bank_0E.asm:3668`), so adding
a row is one more table entry.

**Decision: left/right stays contextual rather than global.**  Today left/right
adjusts the respond rate from any cursor position.  It will cycle
Vanilla -> Improved -> Super -> Custom while the cursor is on the Options row,
and go on adjusting the respond rate everywhere else.  This preserves the
existing muscle memory exactly -- nobody who never moves the cursor to the new
row sees a behaviour change.

Pressing A or Start on the Options row opens the settings screen rather than
starting the game.

### Settings screen

**Decision: one scrolling list, not two columns and not category pages.**  Two
columns would cap labels at about 12 characters.  A single list gives roughly
26, and with 42 settings plus 5 category headers and their separators the list
is 57 rows against 20 visible -- light scrolling, and no paging UI to build.
Categories appear as inline header rows using the overview's own grouping.

**The list opens with a blank row.**  `OPTLIST_TOP` is 1 because nametable row
0 is cropped, but on a CRT row 1 is still half inside the overscan, so the
first heading was clipped.  A blank list row rather than a larger
`OPTLIST_TOP`: it occupies a slot only while the list is scrolled to the top,
where raising the margin would cost a visible row for good and collide with
the description box at row 21.

The bottom of the screen is a reserved description pane showing detail for the
row under the cursor.  A `DrawBox` of height H yields H-3 text rows (the
Continue box is 4 tall and holds one line), and a full-width box leaves 28
usable columns.

**Decision: 5 description lines.**  The box is 8 rows at y=21, covering rows
21-28, with text on rows 23-27; the list gets rows 1-20.  The tradeoff:

    text lines   list rows   budget
        4           21        112
        5           20        140     <- chosen
        6           19        168
        7           18        196

**Decision: reuse the checkbox tiles as radio buttons for the preset list.**
The alternative -- a different BG palette for the active row -- means fighting
the attribute grid for no visual gain.

**Decision: Start leaves the screen; only A toggles.**  The title screen treats
A and Start as one button, so Start arrived here already meaning "yes" and was
wired to toggle the row under the cursor.  On a list of switches that is a
second way to do what A does, while the thing a player wants Start to mean --
done, take me back -- had only B.  So Start now exits alongside B.  Nothing
extra is needed to put the title cursor back on Continue: the way out is
`JMP EnterTitleScreen`, and `IntroTitlePrepare` on that path already zeroes
`cursor` along with the button catchers.

### Save view -- Select on Continue

**Built 2026-10-09, played 2026-10-10.**  Select with the title cursor on
Continue opens a read-only view of the saved game: its seed and its
RANDOMIZATION rows, read from the battery copy (`$64A0`) that Continue would
load -- the world that game is, where the settings screen shows what the next
new game would be.  **Seed entry is not part of it (user, 2026-10-09):** it
belongs to the New Game flow, which needs more thought first.

  - It is the settings screen held to its last section.  `opt_saveview` sets
    `OPTMENU_VIEW` (`OPTBLOCK+$31`) and opens the window on the blank above
    RANDOMIZATION; the heading reads SAVED GAME, and the blank row under it
    the seed, as eight hex digits high byte first -- the way `FFSEED=` and
    `randoref.py` take it.  The rows keep their indices, so the labels,
    readouts and per-value descriptions are the settings' own, and a save
    and the settings can never be described two ways.
  - Values come through `opt_menu_valbyte`: the option block, or in the view
    the save, which keeps the new-game bytes in the option page's order from
    Trap tiles on.  A step past its row's count reads as the first, as the
    description pane already did.
  - Up and down move between the value rows for their descriptions; B or
    Start leaves.  Since the key item rows came (2026-10-14) the section is
    longer than the window, so the view scrolls as the settings do, never
    above the blank over its heading and back to it at the first row; the
    cursor passes over the KEY ITEMS heading and the blanks.  A, left, right and Select are masked off (A on a value row
    did nothing anyway).  Nothing is written: the preset is not switched to
    Custom and the option checksum is untouched.  The flag is cleared on the
    way out, and `opt_settings` clears it on the way in, so a soft reset in
    the middle of the view cannot leave the settings reading the save.
  - With no save Continue would load -- the game's own assertion bytes and
    checksum, in its order (`opt_savevalid`) -- Select does nothing, as it
    does on every other row.
  - The title loop hears Select through `TitleScreen_Music`, which now ORs
    `joy_select` into the A catcher it returns (two of the thirty unused
    bytes after it).  `opt_titlechoose` makes every decision about A, Start
    and Select and answers in the flags -- N: back to the loop; Z: a screen
    was shown, rebuild the title; otherwise leave, C set for New Game.  It
    calls each screen with `JSL` rather than tail-jumping into it: the
    screens end in `PLB` / `RTL`, which would hand back the flags of the bank
    byte.  Bank `$0E`'s call site went from 16 bytes to 12 and four NOPs.
  - Nothing on the title screen says Select does anything.  A hint belongs
    with the New Game and Continue rethink.
  - The hand sits 12 pixels further right than on the settings screen
    (`VIEW_HAND_DX`; user, 2026-10-13, played).  A save view row is a value
    row with nothing in the checkbox column the hand normally points at, so
    at the settings screen's x it stood two tiles off its label.

### Tiles and palette

Two new CHR tiles: unchecked and checked.  A white rectangle with a grey
bevelled edge on the blue background.

**No palette work is needed.**  `LoadBorderPalette_Blue`
(`game/bank_0F.asm:10200`) already sets BG palette 3 to `$0F` black /
`$00` grey / `$01` blue / `$30` white -- exactly the four colours the widget
wants, and the palette the boxes and text already use.

**No CHR pressure either.**  This screen draws only text (`$80`+) and box
borders (`$F7`-`$FF`), so all of `$00`-`$7F` is free to load the two tiles
into without evicting anything the screen uses.

### Description text

**Source: FFR's own tooltips**, in
`FF1Randomizer/FF1Blazorizer/wwwroot/tooltips/tooltips.json` -- 468 entries of
`Id` / `title` / `description`.  29 of our 30 settings have one; only Boss
Stats does not (Enemy Stats has `enemyStatsDoubleSlider`, and the boss slider
has no entry), so that one needs an original.

**They do not fit as written.**  Measured at 28 columns, wrapped:

    budget                fit as written
    4 lines / 112 chars       5 of 29
    5 lines / 140 chars      10 of 29
    6 lines / 168 chars      15 of 29
    7 lines / 196 chars      16 of 29

They run from 62 to 512 characters, median about 165.  Even at 7 lines -- which
would cost three rows of the list -- barely half fit, and the ones that overflow
are the ones that most need explaining (Cast Life in Battle is 512, Encounter
Rate 450, Gold + XP 418).

**Decision: treat the tooltips as source material, not as copy.**  They are
written for a web tooltip sitting next to a screenshot, and most of the length
is boilerplate that strips out cleanly -- "If enabled, the player's..." and
restatements of the label.  An editorial pass at 5 lines is tractable:

    Auto Retargeting   157 -> 93 chars
        Melee attacks and spells
        aimed at a dead enemy
        retarget a living one
        instead of being wasted.

    Speed Hacks        145 -> 68 chars
        Area transitions, menus,
        battle boxes and animations
        all run faster.

Two descriptions have to carry a caveat that is not in FFR's text at all,
because it is specific to toggling settings on an existing save: NPC Guillotine
is permanent, and Better Thief + Ninja applies only at character creation and
future level-ups.  See section 7.

DTE compresses storage but not display width, so it helps the 16KB chunk
budget, not the fit.

**Decision: a row whose values mean different things describes the value it
holds.**  The RANDOMIZATION rows' values are modes, not amounts, and five modes'
worth of explanation in one five-line box was a list rather than a
description.  So the record for such a row is `DESC_BYVALUE` and a pointer
per value, and the pane redraws when left or right changes it.  The dials
keep one description: their values differ only in degree.

### Text rendering

Labels and descriptions live in the options chunk and render through the
existing machinery unchanged: `DrawComplexString` does `LDA cur_bank` /
`JSR SwapPRG_L` before reading `text_ptr` (`game/bank_0F.asm:7371`), and
`hal_swapprg` is just `adc #CHUNK0`, so a chunk number above 15 works today.
This was verified by the new-bank probe described in `analysis.md`.

Budget: 31 labels at ~14 characters and 31 descriptions at ~80 characters is
roughly 2.9KB before DTE, plus pointer tables.  The whole feature -- menu code,
labels, descriptions, tiles -- fits in one 16KB chunk with room to spare.


## 2. Presets

Three presets plus Custom: **Vanilla**, **Improved**, **Super**.  Super was
called Deluxe until 2026-10-10 (user).

**Decision: presets are a single table in source, one row per preset, one named
constant per setting.**  Retuning a preset is editing one line.  This was an
explicit requirement -- the Super values below are a starting point, not a
settled balance.

Super: everything on but Auto retargeting, encounter rate 60%, gold and XP
250%, enemy and boss stats 100%, elemental bonus +30, Thief and Ninja hit +4.

**Decision (user, 2026-10-11): Improved is FFR's Improved Vanilla.**  Every
quality-of-life row but Auto retargeting, the bugfixes, gold and XP at 200%,
the elemental bonus at the cartridge's +4, and Thief and Ninja hit growth at
+3, FFR's Moderate; no other variation.  It replaces "quality of life and
bugfixes" with one variation, which had carried hit growth at Double and the
bonus at +10.  That +10 was a misreading: FFR's preset has the bonus checkbox
off, so its slider's 10 never applies.  FFR's Improved Vanilla has four small
rules the cartridge lacks (`ffr-presets.md` §3.2).  Built 2026-10-11 and
checked by `test_presets`; not yet played.

**Decision (user, 2026-10-11): Auto retargeting is off in every preset**, for
the player to turn on.  It takes strategy out of a fight, and in FFR most
fights are run from or swept with magic, so it matters little.  FFR turns it
on in its Improved Vanilla and Beginner.

Vanilla turns everything off.

**Decision: Custom is seeded from whichever preset was last active, and only
becomes Custom when a value actually changes.**  Entering the settings screen
from a preset and leaving without touching anything keeps the preset selected.


## 3. The settings

50 settings: 43 checkboxes and 7 value rows.

### Quality of life (17)

Speed hacks, Faster Walking, Faster Ship, No Party Shuffle, Identify Treasures,
Chests Appear Opened, Buy Quantity, Run -> Wait, Battle Magic Menu Wraparound,
Auto Retargeting, Autosort Inventory, Repeated Heal Potion Use, Shop
Information, Chest Information, NPC Guillotine, Lefein Inn and Clinic, Lefein
SuperStore.

**The two Lefein rows** (2026-10-13; played the same day) are FFR's
Lefeinish Hospitality and Add Lefein SuperStore, which FFR files under
standard maps; quality of life here (user).  They are the cartridge's first
edits to a standard map, and change nothing about what is reachable, so they
are ordinary options that can be flipped mid-game -- an edit appears the next
time Lefein loads.  Bits 41 and 42; Super has them, and Improved, following
FFR's Improved Vanilla, does not.
  - **Lefein Inn and Clinic**: an Inn sign and a Clinic sign over two of
    Lefein's houses, and in them Crescent Lake's own door tiles ($71 and
    $65): a door tile carries its shop's number, so these are Crescent
    Lake's Inn and Clinic, shops 55 and 43.
  - **Lefein SuperStore**: Lefein's magic shop rebuilt 24 tiles wide with
    sixteen doors, every town's white and black magic shop but Gaia's next
    door (21-26, 29-30, 31-36, 39-40), and one tree above it turned to grass.
  - **How a map is edited.**  FFR rewrites the map in its ROM; a flag here
    can change between loads, so `opt_mapedits` writes over the map as it
    loads.  `LoadStandardMapAndObjects` -- the only path a standard map is
    loaded by, a Continue included -- calls it between `LoadStandardMap`,
    which has decompressed the map into `mapdata` ($7000, 64x64), and
    `LoadMapObjects`.  `lut_MapEdits` is a list of rectangles: flag byte and
    mask, map, x, y, width, height, then the tiles, row by row.  The
    coordinates and tiles are FFR's, from `StandardMaps/SMUpdates.cs`.  Four
    fixed-bank bytes for the hook.  `test_mapedits` loads Lefein through the
    real routine with the flags off and on and checks the difference is
    FFR's edits exactly, that the door tiles in this ROM lead to the shops
    FFR names, and that no NPC stands on an edited tile.  An edit that
    changes what is reachable (a shortcut, Titan's Trove) is another matter:
    it belongs with the world, fixed at New Game and known to the logic.

### Controller Reset -- not a flag

**Decision: unconditional, with no menu row.**  L + X restarts through
`OnReset`, the entry the boot itself uses, leaving work RAM alone.  L + Y clears
zero page from `$FF` down to `$01` on the way.

**Decision: fire on the press.**  The rule is the whole of it: the combo bits
changed since last frame, and what they changed to is a whole combo.  It feels
faster than waiting for the release, and it is simpler -- one comparison against
`h_joyauxprev` rather than a case per combo.

A press edge is also naturally one-shot, which is what stops the reset going
round again.  The buttons are still down when the title screen comes up, but
`h_joyauxprev` already holds the combo -- nothing in `OnReset` or the zero page
wipe reaches `$08xx` -- so there is no change and no second edge.  Firing on
release needed a deliberate trick for the same property, and carried a hazard
besides: a combo left in `h_joyauxprev` by power-on WRAM was a reset on the first
frame that read it.  On a press edge that garbage is harmless, because the first
frame can only ever clear it.  `init_halvars` zeroes the byte regardless.  It is the only feature in the
options bank that is not gated, and the reason is that L, X and Y are buttons
the cartridge never had: no vanilla behaviour is displaced, the combos cannot
collide with anything the game does, and there is nothing a player might want
switched off.  A flag would have cost a bit, a row, a description and a preset
column to express "leave the new buttons alone", which is not a preference
anyone holds.

The pair is what the feature is for.  `battlestep` and `battlestep_sign` at
`$F5`/`$F6` are the index into `lut_RNG` that decides whether a step produces an
encounter, and `GameStart`'s `ClearZeroPage` stops at `$EF` -- so an ordinary
reset preserves them, and re-entering from a known index is how the encounter
table gets manipulated.  The hard combo is for when that is precisely not
wanted, and on a console the alternative is reaching for the hardware.

**What gets cleared is FFR's range, unchanged: zero page `$01`-`$FF`.**  The
store is direct-page indexed, and the direct page is always bank 0, so it cannot
reach SRAM whatever `DBR` holds.  That is the point: SRAM is where the save lives
-- `unsram` at `$6000`, the saved file at `$6400`-`$67FF`, the option block at
`$6E00` -- and a hard reset costs neither the save nor the settings.  Nothing has
moved since FFR, so the range needed no rethinking.

Two differences from FFR.  It reads controller 2 and guards with Up, where this
uses L with X or Y on controller 1.  And its hard reset jumps straight to
`GameStart`, where this goes through `OnReset` for both: the hardware is already
up either way, so the longer path costs a few hundred cycles and removes one
thing that can be subtly wrong.

**Decision: detect in the HAL once a frame, act from `WaitForVBlank`.**  This
started as a port of FFR's arrangement -- hook the three joypad handlers,
`UpdateJoy` plus the two independent ones the battle has -- and that design is
wrong.  Those routines only run when the game reads buttons, and plenty of loops
never do: both palette fades, so the inn's save fade could not be reset out of,
the battle message waits, and the transitions.  Hooking readers means finding
them one at a time, forever.

So `aux_detect` in the HAL reads L, X and Y once a frame, straight after the
flush, does the release edge, and leaves the combo in `h_padreset`.  One `JSL` in
`WaitForVBlank` acts on it.  Every frame loop in the game waits for vblank, so
there is no loop this misses, and the reset still leaves from game code rather
than from inside a HAL thunk.  Straight after the flush is also what makes the
`HVBJOY` wait free: the auto-latch runs at the top of vblank and is long finished
by the time the transfers are done.

The HAL has to do the reading regardless, because nothing else can -- `joy` is
eight bits wide and every one is spoken for.  What it does not do is decide or
jump.

This replaced four hooks with one, and **gave banks `$0B` and `$0C` their slack
back**: the four `.res` NOPs in `optthiefgrowth.patch` and `$0C`'s four unused
tail bytes are unspent again.

### None in the party -- not a flag

**Decision (user, 2026-10-09): unconditional, with no menu row.**  On the
party creation screen, slots 2-4 cycle Fighter to Black Mage, then None, then
round again; slot 1 never offers it.  It is for solo and small-party runs,
which before meant making four characters and killing three.  A on a None
confirms it with a blank name, without name input.

The model is FFR's: class `CLS_NONE` (`$FF`) and the out-of-battle dead
ailment from the start, on a page of zeros.  Being dead, it already takes no
turn, is not targeted, is skipped by enemies' area spells, is not raised by the
inn or tents, takes no share of experience, and the party falls when its last
living member does.  `src/nones.asm` and sixteen `nones_*` patches cover the
rest -- where the class byte would index past a table, something could raise
it, or the game would speak of it as one of the dead:

  - party creation: the cycle, the name "None" (spelled out: no item name is
    free), no sprite, and A without name input
  - stat code `$01` in the menus prints "None"; menus and the party-order
    screen already draw no dead character
  - battle draws nothing (`DrawCharacter`), and the CHR loader gives its slot
    the Fighter's tiles rather than reading past the table
  - the walking sprite and its palette come from the first member who is not
    a None (`LeadClass`), so one can be moved to the front of the line
  - class change passes it by (a None plus 6 would be a Black Mage)
  - **it holds gear, but cannot wear it or learn spells.**  Shops can give it
    weapons and armour and the equip menu can trade them -- extra bag space,
    as in FFR, the user's wish -- but `IsEquipLegal_N` refuses to equip, the
    magic shop says it cannot learn, and Shop Information shows it using
    nothing.  FFR leaves these to whatever lies past each table.
  - the clinic does not list it, and neither LIFE and LIF2 from the menu nor
    Cast Life in Battle raise it
  - **a spell on the whole party passes over it** (playtest, 2026-10-09: INV2
    read "Ineffective" for both Nones).  `Battle_PlMag_TargetAllPlayers`
    shows "Ineffective" for the dead and stoned; `none_aoetarget` sends a None
    straight to the loop's counter.  **Deviation from FFR:** FFR's patch skips
    to the loop's tail, which still waits out the respond-rate delay, a beat
    with nothing new on screen per None.  This skips the delay too, as the
    enemies' loop over the party already passes the dead.

Bank `$0E`'s and `$0C`'s sites are byte-neutral JSLs into the options chunk; `$0E`'s two
same-bank helpers (`PtyGen_A`, `IsEquipLegal_N`) live in the 39 bytes
`DoClassChange` gave back.

### Bugfixes (5)

House MP Restoration, Weapon Stats, Spell Fixes, Enemy Status Attacks, Run
Chance Fix, Turn Order Fix.

**Run Chance Fix** (2026-10-11; played the same day) is FFR's
`ChanceToRun` at "Corrected", which every FFR preset uses, Improved Vanilla
included; Improved and Super have it.  Running is luck against
rand[0, level + 15], and the original reads the level through the in-battle
stat pointer, where that offset is something else -- Disch: "the ailment byte
for 2 players after this one (for top 2 slots) or other garbage memory for
the bottom 2".  FFR's fix is one byte, the out-of-battle pointer;
`opt_runlevel` replaces the seven bytes that load the level and add 15, and
reads through either pointer by the flag.  The level is 0-based there, as
FFR reads it too.  Bit 38.  FFR's fixed chances (25% to 100%) are left out:
no preset uses them.

**Turn Order Fix** (2026-10-11; played the same day) is FFR's
`ImproveTurnOrderRandomization`, in every FFR preset.  `DoBattleRound` starts
the order enemies first, party last, and shuffles it by swapping two random
picks seventeen times (Disch counts sixteen; the counter starts at 17).  That
leaves entries near where they started: over all 256 RNG states a party
member ends the round's order last 57% of the time, where a fair shuffle
gives 4 in 13 (31%), and 1.9 entries never move, where fair is 1.  The flag
makes it FFR's Fisher-Yates walk -- 30% and 1.0 -- in twelve rolls rather than
34.  The loop stays in bank `$0C`, because `RandAX` is there; three helpers
say how many passes and over what range (`opt_turncount`, `_hi`, `_second`),
and with the flag off they reproduce the original's passes and its RNG use
exactly.  FFR also baked a seeded permutation into the starting list; a fair
shuffle makes the start irrelevant, so that half is left out.  `test_turnfix`
runs the real `DoBattleRound` to the end of its shuffle against models of
both, from the disassembly and FFR's patch.  Bit 39.

**Decision: the BB/Master absorb fix is unconditional, not a flag.**  It lives
in the same equipment-stat path as the Weapon Stats fix and writes the same
saved fields; making it always-on removes an interaction without costing
anything anyone wants.

**Decision (user, 2026-10-11): the critical hit count is unconditional
too** -- not worth a flag bit and a menu row.  It is FFR's
`EnableCritNumberDisplay`: an attack that lands several criticals reports
"3 Critical hits!" (FFR's wording) where the original says "Critical hit!!"
whatever the number; one critical reads as it always did.  FFR offers it
only with its speed hacks, because its code lives there.  Played 2026-10-11.
`opt_critbox` replaces the thirteen bytes that report the criticals, and the
site now calls `PrepareAndDrawSimpleCombatBox` -- the routine under
`DrawBattleMessageCombatBox`, which writes "code, value, 00" into combat box
4's buffer and draws it -- with the codes `opt_critbox` picks: $0F and the
message as before, or $11 and the count, the routine's 00 becoming the
number's high byte, after `opt_critbox` has written the words and terminator
past those three bytes.  Nineteen bytes, three past box 4's sixteen, as
FFR's own are; no combat box uses them.  `test_critcount` runs the real
routine and reads back what the box will print.

**The stack-depth softlock fix is unconditional too (2026-10-11, played the
same day)**, as FFR applies its own on every ROM.  Walking Coneria Castle's
stairs up and down, a build without it crashed after a run of round trips;
with it, Mesen showed the stack bottoming out at `$0169` and staying there --
the map loop held at `$017D` and 20 bytes of per-frame calls beneath it.  Each normal teleport nests
another `DoStandardMap` -- seven bytes of page 1 -- and only a warp gives
them back, so walking Coneria Castle's stairs up and down (both ways are
normal teleports, and 2F has no warp) or the Ice Cave loop runs the stack off
the bottom of the page.  On a NES that wraps and breaks the next warp; here
the HAL's and the randomizer's native-mode pushes would go on into zero
page.  `opt_stackshift`, called from `@NormalTeleport` before its pushes,
slides the stack up a frame over the oldest one once S is low enough: no map
runs below `$7D`, leaving 125 bytes beneath it, and 18 levels fit before
anything is forgotten (FFR's floor is `$30`, 41 bytes on a NES).  The cost,
past 18 levels, is that a warp from the second floor goes to the overworld.
It checks the oldest frame's return address against the current level's
before moving anything, which FFR's does not.  `test_stackshift` runs the
fixed bank's own `@NormalTeleport` over real frames, sixty Coneria trips
included; the harness's 65816 gained `TSX` and `TXS` for it.  Details:
`randomization-notes.md` §9.3.

**Two stray map objects are removed, unconditionally (user, 2026-10-14; built,
not yet played).**  The map object tables list two quest objects twice.  The
fairy (`$13`) is in Ice Cave B1 as well as Gaia, standing in the map's outer
void, joined to nothing, once the bottle is opened.  The rod plate (`$16`) is
in Sky Palace 2F as well as Earth Cave B3, inside a wall, and shown until the
ROD is used anywhere.  Vanilla always uses it before Sky Palace; a placed ROD
need not, and then the plate shows in the wall.  Neither can be reached, so
neither does anything else.  mkrom empties both slots, asserting the bytes as
it does the Ribbon's (`overlay_strays`), and `test_strayobjects` holds bank
`$00` to those six bytes.  The world graph reads the cart, so it now has one
fairy and one plate; the logic tables come out the same.

### Scale (5)

Value rows, and the first section in the list: Gold + XP Scaling, Encounter
Rate, Enemy Stats, Boss Stats, Elemental and Type Bonus.

**Decision: the dials come first, because of the paging.**  Left and right page
the list by half a screen everywhere except on a value row, where they belong
to the value -- so a cursor sitting among the dials cannot page at all.  At the
top of the list that costs nothing: the cursor starts on the heading, where
left and right still page, and the first page lands well below them.  Anywhere
else it would be a hole in the middle of the scrolling, in a position that
moved every time a flag was added above it.

**The shoulders page anywhere** (user, 2026-10-15: "the idiomatic SNES way to
page through menus is using the left and right shoulder buttons").  L pages
up half a screen and R down, on any row -- the dials and the randomization
rows included, where left and right belong to the value -- once a press, not
repeating while held.  The NES pad has no shoulders, so the HAL reads them:
`aux_capture`, which already filed L, X and Y into `h_joyaux` for the reset
combos, files R too, in its own JOY1L bit ($10); the combos are tested
against L|X|Y and do not see it.  `opt_shoulders` takes the press edge
against `OPTMENU_SHPREV` and calls `opt_page`, which is the d-pad's paging
split out of `opt_sideways`.  The save view pages nothing, shoulders
included.  `test_shoulders`.

**Decision: the elemental bonus is a dial, not a checkbox.**  FFR has both -- a
checkbox and a "Damage Bonus" slider under it, greyed out until the box is
ticked.  A list of rows cannot grey anything out, and a checkbox that has to be
on for a dial elsewhere to mean anything is the sort of interaction this menu
avoids.  One dial: +0 to +50 in twos, where +4 is what the cartridge does and
+0 is an off position no checkbox could reach.

### Variations (15)

Better Thief + Ninja, Thief and Ninja Hit%, Thief lockpicking, Double Weapon Crit Rate, Improved
CURE/HEAL, Improved FIRE/LIT/ICE, Cast Life in Battle, SOFT in Battle, White
Mage HARM, LOCK / LOK2 Mode, TRANCE Status Element, Asshat Octopus, Boss
tactics, RUSE Staff, NUKE Stick.

**TRANCE Status Element** (2026-10-11; played the same day) is FFR's
`TranceHasStatusElement`, in every FFR preset, Improved Vanilla included --
so Improved has it though it sits among the variations.  TRANCE is the enemy
skill that paralyzes the whole party (record 81, attack `$51`); its record
has no element, and FFR gives it Status (`$01`), so a Ribbon resists it.
`opt_magicdata`, which already swings `btl_magdataptr` at an edited copy for
the spell flags, does the same for this one record.  Enemy attacks reach it
too: `Enemy_DoMagicEffect` calls `Battle_PrepareMagic`, where it is hooked,
and `test_trance` runs that routine for TRANCE.  Bit 40, the first of the
sixth flag byte, which the flag word grew for it (format 8) -- and grew
for the critical hit count too, until that became unconditional.

**Asshat Octopus** (user, 2026-10-14, for fun; played the same day, both fights;
named Asshole Kraken until 2026-10-15, user) is not FFR's, and is off in
every preset.  Kraken and Kraken 2 (enemies `$7B`
and `$7C`) spend every turn hitting a White Mage or White Wizard with their
eight-hit melee attack, while one is neither dead nor stone: no INK, and no
LIT2 from the second.  With nobody to hit the turn is the enemy's own, and
the battle RNG is not touched.  With two or more white mages, which one is
`GetRandomPlayerTarget`'s weighting, half the time the first slot, rerolled
until it lands on one.  `opt_kraken` decides it at the head of `Enemy_DoAi`,
before the enemy's script is read, and the hook jumps to
`EnemyAttackPlayer_Physical` as `ChooseAndAttackPlayer` does: twelve of the
21 never-executed bytes the script lookup left there, so bank `$0C` stays
byte-neutral.  The patch is `randoai_kraken.patch`, named to sort after
`randoai.patch`, whose output it edits.  Bit 43, which no build had set, so
every saved block reads it off and the format stays 9.  `test_kraken` runs
the real `Enemy_DoAi` from all 256 RNG states: always the white mage with
the flag, and the enemy's own turns, roll for roll, without it, with nobody
to hit, for any other enemy, and for every other class.

**Boss tactics** (user, 2026-10-15: bosses that "strategically select
targets or choose spells to their best advantage" -- and, after a first cut
that only aimed, "do the real shit"; built, not yet played) is not FFR's --
FFR only shuffles or removes boss scripts -- and is off in every preset.  A
value row, Off / Clever / Ruthless, in two bits of the sixth flag byte (45
and 46, which no build had set, so every saved block reads Off and the
format stays 9): the scalar tables already take a field of any byte of the
option page, as the key item rows do.

Every enemy runs its script: a roll against its magic rate, then its skill
rate, else a swing; the next spell or skill in turn, whatever it is; and
`GetRandomPlayerTarget`'s half, quarter, eighth, eighth for the aim.  With
the dial on, a boss (`opt_isboss`, FFR's list, through `opt_isbossfar` so
there is one list) weighs every action it has -- the swing, each spell and
each skill of the script in force (the cache's, `OPTAISHADOW`, so Enemy
scripts and skills shuffles count), at each target -- and takes the one worth
most.  **Ruthless** decides everything.  **Clever** keeps the script's rhythm
-- its rates still roll, as `EnemyAi_ShouldPerformAction` rolls them, for a
spell, a skill or a swing -- and decides what and at whom; a kind with
nothing worth casting is a swing.  Garland and the Pirates have no script:
their swing is weighed at its hook.  Asshat Octopus's aim stands.

**The script is the boss's deck** (user, 2026-10-15, before the first
playtest: "if Chaos is just going to spam NUKE, that's not very sporting").
The first build had no such limit, and against a likely endgame party it did
not spam NUKE -- but once Chaos was down two rounds of the party's damage,
CUR4 was its best move every turn, and a boss that heals to full forever
has won and is no fight.  Now each slot of the script plays once in every
eight of the boss's turns (`DECK_TURNS`), the boss choosing which and when,
and the swing is always there: Chaos one CUR4 and one NUKE an eight, Lich 2
two NUKEs, Kary 2 four FIR3s -- the script's own mix bounds each boss, as
vanilla's rotation does.  A pass is eight turns rather than "until every
slot is played" because a boss that would rather swing than play its weak
cards would never reach the end of its deck and never get its NUKE back,
and reshuffling whenever it is stuck brings NUKE straight back.  The deck
lives in the two rotation bytes `Enemy_DoAi` no longer reads when the dial
is on: `en_aimagpos` the spell slots played, a bit each, `en_aiatkpos` the
skill slots in its low nibble and the pass's turns in its high; both zeroed
by `LoadEnemyStats` for every battle.

**The worth is the race, in rounds.**  Dp is the party's damage a round to
the boss: each living member's best, its swing by `DoPhysicalAttack`'s own
rules (its weapon's element and category against the boss's weakness, the
elemental bonus, evade, absorb, DARK, FAST) or a damage spell it knows and
has the MP for (resisted, weak, HARM against the undead or anything with
White Mage HARM), whichever is more; mute casters have only their swing.  Rb,
the boss's rounds left, is its HP over Dp.  Db is the most any of its own
actions is expected to take off the party.  Then, in rounds:

  - HP off the party, over Db: a turn's worth for its best.
  - A kill, the HP and the rounds Rb grows when Dp loses that member -- Rb
    d/(Dp - d), all of the cap if under 16 of Dp would be left -- and its
    healing (CURE to CUR4, HEAL, what it has the MP for) over the rounds
    left, and the whole fight if it was the last one standing.
  - Stun four turns of that member's damage and healing (a stunned player
    recovers one turn in four, `Battle_PlayerTryUnstun`), sleep as many as
    `Battle_PlayerTryWakeup`'s max HP roll makes it (one, past 80 HP),
    confusion two; nothing more on one out already.  MUTE a caster's spells
    for the fight; DARK and SLOW a fighter's swing, by the swing in the dark
    or a multiplier down; poison two HP a round for the fight.
  - Its own heal, the HP it is missing at most, over Dp; CUR4 all of it,
    once a pass of the deck; FAST
    (nothing at a multiplier of 2) the party falling sooner to its faster
    swing for the rest of the fight -- if its swing then beats its best.

A muted boss's spells and skills are worth nothing; it swings.

**From the dice.**  A swing's mean and variance are summed exactly over the
256 values of the battle's dice as `RandAX` turns them into rolls -- a hit's
damage and its square, a crit adding the roll again, `RandAX`'s quirk that a
range of 256 is 0 so B 255 rolls 255 -- and a spell's from its roll (each
share counted as holding 256/k dice for the square).  The chance of a kill
and the HP short of overkill come from the normal tail at z = (16 HP - 8 -
mean) / sd, in sixteenths from -4 to 4 (`gentactics.py`'s tables, checked
against `erf`).  The sums: a closed form while no roll caps -- the dice's
shares sum to ((k-1)*255 + gcd(k,256) - 1)/2 -- and otherwise a count share
by share, each share Q or Q+1 dice of 256 = Qk + R; for absorb under the
base damage the squared sums follow from the rolls' alone, kept for two base
damages.  Spells' records come through `opt_spellbyte`, the battle's own rule
(Improved spells, Spell Fixes), once a decision each.  CURE, CUR2, CUR3 and
HEAL are effect 7 -- the jump table has RecoverHP twice -- which a mutation
run caught the reckoning missing.

**Thinking takes frames; the music does not wait.**  A decision is up to
about 120000 instructions -- Chaos against four casters each with a full
spell list -- a fifth of a second; most are a few thousand.  The game's own
calls each frame drive the music, so the thinking yields: whenever RDNMI
says a vblank has begun (its latch holds until read, so no frame is missed)
it runs the battle's frame of music -- `music_track`'s follow-up, then
`CallMusicPlay` with `cur_bank` at this chunk so the driver swaps back here
-- and the HAL's frame of sound.  Nothing on screen moves while a boss
thinks, so nothing else of the frame is owed.

**Where it is.**  Its own chunk, `CHUNK_TACTICS` (`$18`, `src/tactics.asm`),
native and sixteen bits wide, with its scratch at `TC_BASE` in bank `$7F`
between the roll screen's and placement's, cleared each decision -- nothing
there is power-on clean, and the tests fill it with junk first.  Three
byte-neutral hooks in bank `$0C`: `tactics_turn.patch` takes four of the nine
dead bytes `randoai.patch` left in `Enemy_DoAi` for `JSL tac_turn`, which, if
it decides, drops its own return and jumps into `EnemyAttackPlayer_Physical`
or `Enemy_DoMagicEffect` as `Enemy_DoAi` would, leaving the aim in a latch
(the slot with a mark, its complement, the attacker: all three must agree,
the slot must still be alive, and whoever reads it clears it);
`tactics_swing.patch` takes the seven NOPs `randostatus.patch` left in
`EnemyAttackPlayer_Physical` for `JSL tac_swing` and `JSR
PrepCharStatPointers`; `tactics_cast.patch` turns
`Battle_CastMagicOnRandomPlayer`'s load and `ORA` into `JSL tac_cast` and a
NOP.  The decision borrows `$84` and the eight attacker bytes to ask
`opt_scaleatk` for the swing's scaled numbers, and puts them back.

`tools/tacref.py` is the reckoning in Python, integer for integer.
`test_bosstactics` holds the game to it first -- one swing through the real
hit loop for chosen dice, every spell effect through the real
`BtlMag_Effect_*` for every roll, the per-die damage and its square summed
over all 65536 pairs -- then the cart to it: every intermediate (threat, Dp,
Rb, Db, kill and disable worth, each candidate's worth and aim, the choice
and the dice it used) over 160 drawn turns with spell lists, MP and the
spell buffs, and the edges; `Enemy_DoAi` in place for every boss, Clever and
Ruthless, with the boss's stats scaled, the swing reaching its hook; the
latch's rules; the deck over drawn states and a sixteen-turn fight with
Chaos, dice and deck carried from turn to turn (no slot twice in a pass, CUR4
once a pass however hurt); cases a player knows (Lich and Ribbons -- SLP2 has no element
in this cartridge, so a Ribbon does nothing for it; Chaos's CUR4 at full HP
and hurt; FAST once fast; XXXX's 300; MUTE with and without a caster; the
last one standing); the music running between thoughts and the decision the
same; the arithmetic called as the reckoning calls it; the dial.  96
mutations, all caught; one more equivalent (SLOW on one already slowed is
worth nothing by the threat arithmetic anyway).

**RUSE Staff** (user, 2026-10-15: "Everyone loves the ruse staff"; the row
reads "RUSE Staff", the spell's name in capitals as the game spells it; built,
not yet played) is FFR's Guaranteed Defense Item set to RUSE, one setting of
its dropdown; Super has it, Improved does not.  FFR's `CraftDefenseItem`
runs whenever item magic is not None -- Vanilla included, which is how all
its presets but Improved Vanilla and Over Randomizer have it -- after any
shuffle, so the
staff stands over the deal; here it stands over Item magic the same way.
The Power Staff, used in battle, casts RUSE as the Defense sword does -- the
same spell byte, 4 -- and is named for it as FFR's `WriteItemSpellData`
names it: the spell's name padded to six, then the staff's own icon, so
"RUSE" in capitals beside the game's mixed-case names, as in FFR.  Nothing
is written to the weapon table; three readers ask the flag instead, so it
follows a change of settings mid-game.  Battle's Use is
`optrusestaff.patch`: the five bytes after `@GetSpellCast` reads the
record's spell byte (`TAX`, `DEX`, `LDY btlcmd_curchar`) become a JSL to
`opt_itemspell` and a NOP, which hands back the same X and Y but RUSE when
the item just recorded in `btl_charcmditem` is the Power Staff; armour goes
through the same code, its ids from `$44`, so it never matches.  The
equipment text reads spell bytes through `opt_weapbyte`, which answers 4
for weapon 27's byte 3.  The name is `rando_nameptr`'s, built in
`OPTNAMEBUF` as a vehicle's is, a blursing's sign and digit placed on it as
on any name.  Bit 44, no build having set it, so the format stays 9.
`test_staffspells` (with the NUKE Stick's below) runs the game's own item
path from the menu's choice to `SetCharacterBattleCommand` for all 40
weapons and 40 armours and every character, each pair of the two flags and
the byte's other bits against both off, the other characters' items decoy
staves, and sweeps every weapon byte and all 256 names the same way: only
the flagged staff moves.

**NUKE Stick** (user, 2026-10-15; "stick" is the community's word for a
staff, as "bonk" is for a gauntlet; built, not yet played) is the same
idea for the Wizard Staff: used in battle it casts NUKE (spell `$3C`, byte
`$3D`) instead of CONF, its equipment text says NUKE where it said CONF, and
it is named "NUKE" and the staff's icon.  FFR has no flag of this name; a
NUKE stick is what its item magic shuffle (`ItemMagicMode.Randomized`, in
`ShuffleItemMagic`) makes when it happens to deal NUKE to a staff, renaming
the item for the spell as above.  That shuffle is the general form -- every
casting item's spell redealt, from a pool with the useless ones weighed out
-- and would be the follow-up if this one is liked; here it is one flag, off
in every preset, Super included: a NUKE every turn from whoever holds the
Wizard Staff is a different game.  The same three readers as the RUSE
Staff's, each now asking which staff and which flag: `opt_itemspell` checks
the item before the flags, so a staff with its flag off leaves the record's
byte; `opt_weapbyte` answers `$3D` for weapon 32's byte 3; `rando_nameptr`
copies the second name in `lut_StaffNames`.  Bit 47, the sixth flag byte's
last, no build having set it, so the format stays 9.  Nineteen mutations
caught, one equivalent removed (`opt_itemspell` reloading Y, which nothing
between had changed).

**Thief lockpicking** (ported 2026-10-15, the batch's own pick; built, not
yet played) is FFR's `Lockpicking` with its `LockpickingLevelRequirement`:
a locked door opens without the KEY if anyone in the party is a Thief or a
Ninja of the set level or above.  A value row under Thief and Ninja hit%:
Off, then levels 1, 5, 10 ... 50 -- FFR takes any of 1-50, and every one
of its randomized presets uses 15, so Super has 15 (step 4) and Improved,
as FFR's Improved Vanilla, has it off.  FFR's `1B_9300_LockpickDoors`
checks class and level and nothing else, so a dead or stoned Thief still
counts, here as there.  The hook is `optlockpick.patch`: `SMMove_Door`'s
seven bytes from `LDX #0` to `LDX item_mystickey` become a JSL to
`opt_lockpick` and three NOPs, byte-neutral in the fixed bank; it makes the
two stores itself, keeps A (the door bits `@OpenDoor` stores) and answers
in X and Z for the `BNE` that follows.  FFR's version also sets a bit at
`$62FA` for its tracker, which has no counterpart here.  The step is
`OPT_THIEFHIT`'s top four bits (scalar 51; Thief hit narrowed to the low
two, `THIEFHIT_FIELD`, and `opt_hitgrowth` masks it); no build had set
them, so the format stays 9, and a step past the table reads Off.

**Decision: placement logic does not count on it**, as FFR's does not --
the party is the player's choice, and a seed must be finishable without a
Thief.  Picking round the KEY is a sequence break the player earns (user,
2026-10-15: "a legit strat").  With forced parties (FFR's Chaos Rush has
one, `randomization-notes.md` §12) the logic could count it, and flags could
be designed round it (user, the same day) -- the follow-up if forced
parties come.  `test_lockpick` sweeps `opt_lockpick` over every setting,
past-the-table ones included, every slot, every class and None, and the
levels about each threshold, the other three characters decoys (a Thief and
a Ninja one level short, strong non-thieves); then walks `SMMove_Door`
itself for the door, the KEY, Off, a Ninja last in line and an open door to
a shop.  Twenty-one mutations caught.  The harness's 65816 gained the rest
of the stack-relative family (`ADC`, `CMP`, `STA`, `AND`, `EOR`, `SBC`
`sr,S`) for this and Thief hit's new mask.

**Decision: FFR's two Thief dropdowns stay two settings here.**  It has
"Better Thief & Ninja Agility" and "Adjust Thief & Ninja Hit% Growth"
separately, and they change different things -- one is a starting stat and a
growth rate, the other is only a growth rate and applies to both classes
rather than one.  Folding them would make a single checkbox that does four
things.

**Decision (2026-10-11): Thief and Ninja hit% is a value row, +2, +3, +4 a
level** -- FFR's Vanilla, Moderate and Double, the middle three of its five.
It was a checkbox doing Double until Improved took Moderate.  Readouts are the
hit% gained a level, four columns like the other dials: an eight-column word
would run into the twenty-column label.  Played 2026-10-11, all three steps.

**How strong the two together are** (measured 2026-10-11, the cartridge's own
`LvlUp_LevelUp` run from level 1 to 50 for forty Thieves; it matches FFR's
rules exactly, and `test_thiefhit` now holds it to them every level):

    level 30     hit% (attacks)   evade   agility
    vanilla        63 (2)          78       30
    both on       121 (4)         157       99
    level 50
    vanilla       103 (4)          94       46
    both on       200 (7)         177       99

Hit% / 32 + 1 is the attacks a round, so at Double the Thief out-hits the
Fighter (5 at level 50); at Moderate it matches the Fighter's growth of 3.
Agility caps at 99 by level 20, but the original code grants the evade point
whether or not agility rose, so evade keeps climbing.  A two-character party
doubles each member's XP and gets there sooner (user's playthrough).

**SOFT in Battle** (2026-10-11; played the same day, spell and potion, each way) is FFR's
`EnableSoftInBattle`: the SOFT spell and the SOFT potion both work in battle.
Bit 21, which no row or preset had set since Thief hit became a scalar, so it
needed no format bump.  Every FFR preset but Improved Vanilla has it on.

  - **The spell** is Cast Life's pattern.  Vanilla's SOFT is the same blank
    stub as LIFE; the flag supplies FFR's record -- cure ailment ($08) on
    AIL_STONE, single ally, graphic 184, palette 40 -- through
    `opt_spellfixed`, and three of Cast Life's hooks learn it: its battle
    message goes quiet (`opt_magicmsg`; it carried the same $4A, "ineffective
    now"), curing stone reads "cured" rather than the INEFFECTIVENOW that
    Constants.inc says is there because "you cannot cure stone in battle"
    (`opt_curedmsg`), and the target check lets it reach the stoned but still
    refuses the dead, which also keeps it off a None (`opt_playervalid`).
  - **The potion** is a third row in the DRINK box, and vanilla's box is
    built for two throughout: two battle counters with `battle_bank` in the
    byte after them, the choice taken as `btlcurs_y AND 1` over a cursor
    table that mirrors two rows across the 2x4 selector's four, the effect as
    $40 plus the choice -- and $42 is the first enemy attack -- and a box
    drawn two rows high, row by row.  So bank `$0C` keeps its control flow
    and eight hooks, each the size of what it replaced, ask the options bank
    instead (`opt_drinkinit`, `_any`, `_pick`, `_dec`, `_undo`, `_effect`,
    `_name`, `_cursor`); SOFT's count is `OPTBTLSOFT`, set at each battle's
    start.  The potion's effect is the SOFT spell itself, as FFR's DRINK
    table has it, so it shares the spell's record, targeting and messages; it
    needs its own name for the message box, or it would announce the LUTE.
  - **SOFT's row spells its name out.**  The cartridge stores HEAL and PURE
    as four letters and the potion icon but SOFT with two spaces after the
    icon -- the width of the item lists -- and vanilla never drew it in this
    box, so through the `$0E` escape its count landed two columns right of
    the others and off the edge of the box (user, first play).  So
    `opt_drinksoftname` copies the cartridge's own name, drops the padding,
    and lays out the number as the escape rows do; `test_softbattle` checks
    that every row's count falls in one column, from the cartridge's names.
    The inventory needed nothing: the turn's `DEC item_heal, X` reaches
    `item_soft` when X is 2.
  - **`DrawDrinkBox`, in the fixed bank, is now a loop**: the options bank
    gives it the box's spec (ten rows high rather than six with the flag on,
    the ITEM box's height) and then each row's text, and the drawing calls
    stay in the fixed bank.  Vanilla wrote its two rows out longhand, so the
    loop gave the fixed bank 89 bytes.
  - **Decision: the fourth row is empty and answers "nothing", as FFR's
    does.**  The 2x4 selector moves over four rows; mirroring a row instead
    would make the cursor stand still for one press at the wrap.

**White Mage HARM** (2026-10-11; played the same day: HARM and HRM4 cast by a White Wizard -- that other classes stay ineffective is checked by `test_wmharm` alone) is FFR's
`WhiteMageHarmEveryone`: HARM spells cast or used -- item magic shares the
effect -- by a White Mage or White Wizard damage anything, not only the
undead.  Bit 37, in the fifth flag byte; Super has it, Improved does not.
`opt_harmundead` replaces the undead test in `BtlMag_Effect_DamageUndead`
(five bytes for four and a NOP) and answers "damage" for the undead, as
ever, or for a White Mage's or Wizard's cast at the living -- zeroing the hit
chance first, as FFR does, so the double that the undead usually take
(rolled against it in `BtlMag_ApplyDamage`) almost never comes.  Measured
through the real routine over all 256 battle RNG states, HARM on the living
averages 30.3 and doubles 3 times in 256 -- FFR's tooltip says "averaging
30/60/90/120" and "except on a 3/256" -- while the undead still double 208
times in 256.  No enemy casts HARM -- none of the 44 vanilla scripts lists
one, and Enemy skills only redeals the spells the scripts already hold -- so
the check that only a party member can be a White Mage is insurance: FFR's
lookup by the attacker's low seven bits would read past its four-entry table
for an enemy (user asked, 2026-10-11).

### Treasures (2)

Starting items, Starting caster item.  *Until 2026-10-14 also* Free SHIP, Free AIRSHIP, Free
BRIDGE, Free CANAL, Free CANOE, Free KEY, Free CHIME, Free CROWN, Free LUTE,
Free TAIL and Free ROD: those are now the Free value of the key item rows
(Key items, below), saved with the game, and what follows describes them.

These are not in FFR's own quality-of-life grouping; they are its starting-
inventory flags, and they exist here for the same reason FFR has them -- to
put a feature that is otherwise hours away in front of a fresh save.  Each
grants exactly one thing and touches nothing else.

**Decision: none of them are in any preset, including Super.**  A preset
describes how the game plays, not what the party is handed; a Super run that
starts with the airship is a different game, not a smoother one.  They also
only affect a *new* game -- `opt_freestuff` runs off the new-game path, so an
existing save is untouched whatever these are set to.  *Planned
(2026-10-11):* the section moves to the New Game flow, and its FFR-derived
presets free what FFR's do; `randomization-notes.md` §12.  *Planned
(2026-10-13):* each Free row becomes a three-value row, Incentive / Loose /
Free, beside a Key items row, an Other items row, nine incentive gear rows
and FFR's four Early flags -- the incentive rows, `randomization-notes.md`
§12.

**Starting items** (2026-10-11; played the same day, spot checks and a new game) is a value row of
FFR's `StartingItemSet`, its nine fixed sets in its order: None, Safety Bit,
Beggar's Choice, Just Tents, Explorer Pack, Real Estate, Warrior's Standard,
Royal Packmule, Duckling Boon.  Each sets the counts of TENT, CABIN, HOUSE,
HEAL, PURE and SOFT, which a new game starts at zero, so `opt_freestuff`
copies the set's six-byte row of `lut_StartItems` over `item_tent` through
`item_soft`.  The readout is an eight-column short name; the description,
one per set, gives FFR's full name and the contents.  FFR's presets but
Improved Vanilla use the Explorer Pack.  **Decision: the six randomized sets
are left out** -- none of FFR's presets uses one, and each would need a
seeded roll at New Game.  Approved by the user, 2026-10-11, as "a subset ...
or all of them".

**Starting caster item** (user, 2026-10-15: "useful for high-difficulty
seeds so the player has some hope of progressing"; built, not yet played) is
FFR's `StartingEquipmentRandomCasterItem`, an Off/On row under Starting
items, off in every preset.  A new game gives the first character one weapon
or armour, unequipped, dealt evenly from `GetCasterItemPool`: every item
whose spell's routine is Damage, DamageUndead, Heal, Fast, Sabr, Lock,
FullHeal, Ruse or PowerWord, or InflictStatus with exactly death, stone or
confusion -- FFR's `SpellRoutine` and `SpellStatus` values, compared whole as
FFR compares them.  Weapons first, then armour, as FFR concatenates them.
The spell is the one the item really casts, through `opt_weapbyte`,
`opt_armbyte` and `opt_spellbyte`, so the RUSE Staff's RUSE and the NUKE
Stick's NUKE count, and so does Item magic's deal.  On this
cartridge every casting item passes: twelve (the Light Axe, Heal Staff, Mage
Staff, Defense, Wizard Staff, Thor's Hammer, Bane Sword, White and Black
Shirts, Heal Helm, Zeus and Power Gauntlets), thirteen with the RUSE Staff.
The draw is the seed's own stream, `STREAM_CASTER` ("CAST"), through
`rando_caster`, so a seed always starts with the same item.  FFR's `Write`
puts its first weapon in the first character's first weapon slot and its
first armour in the first armour slot, and so does `opt_casteritem`, from
`opt_freestuff` after the starting set: GameStart zeroed the stat page
before the title, party creation writes only the class and the name, and
the first character is never a None.  It goes to the first character
whatever the class, as in FFR, and the equip screen's trade moves it.  The
bit is `OPT_STARTITEMS`'s top one (scalar 50), the set in its low four
(`STARTITEMS_SET`); no build had set it, so the format stays 9, and a block
from before reads Off.  `test_casteritem` holds the pool to one transcribed
from FFR's rule and the ROM's tables, sweeps the rule over all 256 spell
bytes in the cache at both ends of both tables with every flag off and on,
deals 44 seeds under the staff flags and pools of one and two at the ends,
and runs New Game itself beside each starting set.  Thirty-two mutations,
one equivalent: splitting weapons from armour at 41 rather than 40 reads
weapon 40's byte 3, which in the cache is armour 0's.

### New game (16)

**Decision (user, 2026-10-09): the section is headed RANDOMIZATION, and each
row's first value reads "Off".**  Under the old NEW GAME heading, "Trap tiles:
Off" read as if the trap tiles were taken out.  "Vanilla" for every first
value was tried for a day and was a wall of it; with the heading saying what
the rows are, "Off" is the randomization off, and a Shuffle stands out
against a column of Offs.  The blessing and the curse read 0, a number in
their range.  `test_rando_options` holds every row to it.

Trap Tiles, a value row: Off, Shuffle, A, B, A+B -- FFR's `TrapTileMode` in its
own order, first five modes.  Local, Remove, Undead, Curated and Overpowered
are left out; across FFR's own presets only Vanilla, Shuffle and B-side are
used.

Shops, a value row: Off, Shuffle -- FFR's Shops flag, on in nearly all of its
presets.  A value row rather than a checkbox because FFR applies Random Wares
only on top of it, so that is the natural third value.

Chests, a value row: Off, Shuffle -- FFR's treasure shuffle without its logic.
The seven key items stay in their chests; the other 234 trade contents.

Magic levels, a value row: Off, Shuffle -- FFR's MagicLevels as all its
presets use it.  White spells trade slots with white, black with black, and
MP, price, shop and who may learn stay with the slot.  Tiered, mixed books
and permissions that follow the spell are left out; every FFR preset has them
off.

Item magic, a value row: Off, Shuffle, Balanced -- FFR's `ShuffleItemMagic`
(user, 2026-10-15, after the NUKE Stick: "item magic shuffle sounds easy";
built, not yet played).  Every item that casts a spell on the cartridge --
the twelve, weapons first and then armour as FFR concatenates them -- casts
another, dealt from a pool without repeats, and is named for it as FFR's
`WriteItemSpellData` names it: the spell's four letters padded to six and
the item's own icon, or padded to seven without one, a blursing's digits on
top.  Shuffle is FFR's All pool (every spell that does something in battle:
59, all but LIFE, LIF2, WARP, EXIT and SOFT), Balanced its Balanced (45:
less FFR's removals -- FIRE and LIT, the sleep and dark spells, LAMP, PURE,
TMPR, FAST, CUR4, NUKE, FADE, WALL).  Low, Support and Curated are left
out; none of FFR's presets shuffles item magic at all, so the row is Off in
every preset.  `genitemmagic.py` works the pools out at build time from the
cartridge's records -- not the option-adjusted ones, so a world stays a
function of the seed and the save -- and `deal_itemmagic` deals at cache
build, after the blursings (which never touch the spell byte), from its own
stream ("IMAG"), into byte 3 of the gear cache's records.  Every reader asks
the cache: the descriptions and the starting caster item through
`opt_weapbyte` and `opt_armbyte`, battle's Use through `opt_itemspell` (now
those two readers, not the record's ROM byte), the names through
`rando_nameptr`.

**The RUSE Staff and the NUKE Stick stand over it** (user, the same day:
"ruse staff and nuke stick should override it and force their presence").
They are options and the deal is the world's, so the deal never sees them:
`opt_weapbyte` puts them over the record as it reads, and the names take
theirs first.  The Power Staff casts nothing on the cartridge, so it is
never dealt; the Wizard Staff's dealt spell waits under the NUKE Stick, and
turning either flag on or off mid-game moves nothing else.  The starting
caster item deals from what the items really cast, staves and deal
together.

The mode is `RANDO_MAGIC`'s bits 4-5 (scalar 52), Magic levels narrowed to
the low two (`MAGIC_FIELD`): no save had set them, so a game begun before
reads Off, and the save's layout -- and every playtest file -- stays as it
was.  `test_itemmagic` holds the pools to its own transcription of FFR's
rules (and randoref's rule to it over every synthetic record), the cache to
randoref's deal over seeds, modes, blursings and the levels shuffle, the
walk's two ends through a cartridge copy where they cast, every reader to
the deal with the staves over it, all 256 names on and off, with and
without bonuses, and the icon rule over every value of the seventh byte.
Thirty-seven mutations caught; one equivalent removed (a test for a space
before the icon rule, which keeps a space as itself anyway).

Max gear blessing (0 to +5) and Min gear curse (0 to -5), two value rows:
FFR's blursings.  Every weapon and armour rolls a bonus from -curse to
+blessing.  The user's design narrows FFR's range sliders (-9 to 9 each, for
weapons and armour separately): one range for all gear, always containing
zero, so plain gear is always possible.

Formation rarity (Off, Shuffle, Tiered) and Formation zones (Off, Light,
Shuffle, Random), two value rows: FFR's one Formation Shuffle Mode split into two
passes, the user's design.  Rarity moves formations between a zone's eight
slots, as FFR's Shuffle Rarity and Rarity Tiered do.  Zones moves them
between zones and keeps each one's rarity, which none of FFR's modes does:
FFR's Shuffle Across Zones moved single slots, rarity and all, until 2024 and
whole zones since, and its tooltip has described each in turn.  Light moves
only slots 0, 3, 5 and 6, so a zone keeps four of its eight fights.  Neither
moves WarMECH off Sky Palace 5F; rarity may change its slot there, as FFR's
does.  Random is FFR's Totally Random.  Both Shuffles together are "any
encounter anywhere, regardless of zone or rarity".  `GetBattleFormation`
reads the cache's copy of `lut_Domains` (26 fixed-bank bytes back).  Played
2026-10-08.  See `enemy-shuffle-notes.md` §1.

Unrunnable fights and Surprise rates, two value rows: Off, Shuffle.  FFR's
Shuffle Unrunnable Encounters at vanilla's count -- 26 sides drawn from FFR's
pool of 233, each side on its own, where the cartridge's no-run bit covers
both -- and its Shuffle Surprise Bonus over the 115 normal formations.  The
fiends, Chaos and the last four boss A-sides keep their flags.
`EnterBattle`'s formation copy moved out (39 fixed-bank bytes back) and writes
the side's flag into bit 0 of the RAM copy, which every reader already asks,
so no reader changed and FFR's second bit is not needed.  Played 2026-10-08.

Status attacks (Off, Shuffle), Enemy scripts and Enemy skills (Off, Enemies,
Bosses, Both), three value rows.  Status attacks is FFR's Enemy Status
Attacks in Shuffle mode: every enemy's touch, ailment and element together,
dealt among all but the pirates.  Enemy scripts is FFR's Shuffle Scripts --
which enemy has which script -- and Enemy skills its Shuffle Skills & Spells
-- what each script holds -- each for the normal enemies, the bosses, or
both.  Fixed rather than offered (the user's call): No Consecutive Nukes
on, pirates safe, the vanilla script count, No Empty Scripts off; no Remove
Boss Scripts, balanced generator or boss sub-options.  The touch reaches the
battle through `opt_scaleatk`, the script through `rando_enemyai` and a
16-byte shadow in SRAM.  Played 2026-10-09, in a full playthrough with every
flag on.

RNG tables, a value row: Off, Shuffle -- FFR's flag of that name, on in all
its presets but Improved Vanilla.  The encounter table (`lut_RNG`: whether a
step fights, and from which slot) and the battle table (`lut_BattleScramble`)
are each shuffled into the cache, so every probability stays and the order
does not; known manipulation routes stop working, while a seed's own table
can still be learned (`randoref.py --rng` prints it) and L+X still keeps
`battlestep`.  `BattleStepRNG` reads the cache through `rando_steprng`, which
ensures like every consumer; `BattleRNG` reads it directly, since
New Game or `@Begin` has built the cache before any game code runs and every battle
comes through `rando_formdata` besides; `GetBattleFormation` already read
through the cache.  The minigame's puzzle shuffle keeps the
ROM table.  **Declined (user, 2026-10-09):** Fix Missing Battle RNG Entry,
Set RNG (identical battles for racers) and Advanced Encounter RNG.  Played
2026-10-09, in the same playthrough.

Ordeals pillars, a value row: Off, Shuffle -- FFR's `OrdealsPillars`
(2026-10-13; played the same day, off and several runs on), in every FFR
preset but Improved Vanilla.  Castle of Ordeals 2F is a maze of teleporting pillars, fifteen pads,
and a pad's tile is its destination: $4C-$54 land in one room each, and $55
leads on to the stairs.  `deal_ordeals` is FFR's `ShuffleOrdeals` draw for
draw with `randoref.build_ordeals`: the eight rooms shuffled until the
four-pad room is not first, chained from the start room by one random pad
each, the last one out; every other pad back to the same room or an earlier
one, except that the four-pad room's three spare pads, shuffled, go back two
different ways and one anywhere but onward.  Every room is on the chain, so
there is always a way through -- `test_rando_ordeals` checks every room is
reached and the way out found for the cart's deals, and for two thousand of
the reference's.  The fifteen tiles go to the cache (`RW_ORDPADS`), and
`rando_mapedits`, which `opt_mapedits` hands on to, writes them over 2F as
it loads.  FFR also moves teleport $3C, tile $54's, to land at (16, 18), in
the room vanilla never reaches, so that room can join the chain: the fixed
bank's `@NormalTeleport` now asks `rando_teledest` for the landing rather than
reading `lut_NormTele_X` and `_Y` itself.  Since entrance shuffle it reads the
cache's table, as `rando_entrdest` and `rando_exitdest` do for the overworld
entrances and the exits (`randomization-notes.md` §9.3).  The room table and pads are FFR's,
held to this ROM by the test.  When incentive placement comes, its logic has
to see 2F through the deal.

This section is the start of the randomizer, and its rows are a different
kind of setting from everything above.  They describe the *next* new game:
`rando_newgame` copies them into the save, beside a seed, when the game
starts, and nothing reads the settings screen's copy after that.  Changing a
row with a game in progress changes nothing in that game.  See §7 and
`randomization-notes.md`.

**Decision: not in any preset.**  For the same reason as Treasures, and
because a preset describes how the game plays rather than which world it is.
*Planned (2026-10-11):* the section moves to the New Game flow, whose
FFR-derived presets set it; `randomization-notes.md` §12, `ffr-presets.md`.

### Key items (26)

**Built 2026-10-14; played once 2026-10-14, a full run with mostly loose key items, completable; another wanted.**  The incentive rows settled in
`randomization-notes.md` §12, at the end of the RANDOMIZATION section under a
KEY ITEMS heading of their own, saved with the game like the rows above it
and shown by the save view with them:

    Key items        Vanilla / Standard / Wide
    Map shuffle      Off / Entrances / Floors     (below)
    SHIP .. ROD      Incentive / Loose / Free     the eleven Free rows
    Other items      Incentive / Loose            the nine with no Free
    Masmune .. Xcalber   Treasure / Incentive     nine gear rows
    Early King, Sarda, Sage, Ordeals   Off / On

All of it works now (built 2026-10-14; played once): Free, which
`opt_freestuff` reads from the save `rando_newgame` has just written
(`opt_isfree`) rather than from flag bits; the Early flags; and under Key
items Standard or Wide, placement and the rewards it deals
(`randomization-notes.md` sections 4.7 and 4.8).  Under Key items Vanilla
only Free and the Early rows mean anything.  The Chests row's descriptions
say what each value does once key items move.  A ship found under placement
is moored at the dock nearest the map it is found on -- FFR's
`ShipLocations` wherever a dock can be walked to, Ice Cave to Pravoka's
(built 2026-10-14 after the first run, where it was always Coneria's; not
yet played): section 4.8 there.  Loose items are placed progression first,
forward and spread (section 4.7; built 2026-10-14, early places spot-checked,
not yet played): an item
that opens nothing waits while others open something, places reached early
lose weight with every draw, and a dungeon that has taken an item is less
likely to take the next, so loose items spread through the game instead of
piling up where the party begins.

**The Early flags** are FFR's, under Key items Vanilla too.  Early King,
Sarda and Sage waive what that NPC waits for in `rando_talk`'s table
(`lut_TalkEarly`, `TALKF_WAIVED`): the Princess rescued, the Vampire beaten,
the Earth Orb lit.  The held test still runs, so a Free BRIDGE, ROD or CANOE
is not given twice.  Early Ordeals is FFR's `EnableEarlyOrdeals`, in the
cache build: the Castle tileset's two thrones, `$61` and `$62`, the only
crown tiles, lose their special code and are plain teleports.  Under Key
items Vanilla the NPCs keep their vanilla giving lines, as in FFR, which
rewrites them only when NPC rewards move: Early King's King still thanks the
party for the Princess.  Under placement every reward NPC has FFR's line,
naming its gift (`rando_dlgtext`, `randomization-notes.md` §3), and the King
and the Sage have FFR's Early ones.  `test_rando_early` holds the three
waivers to their own NPC and the thrones to the reference;
`test_rando_dialogue` the lines.

**Packed: the option page had nine bytes left and these are 26 rows.**  Each
row is a field of a byte -- two bits for a three- or two-value item row, one
for a gear row or an Early flag -- seven bytes in all (`RANDO_KEYITEMS`,
`RANDO_ITEMS`, `RANDO_GEAR`, `RANDO_EARLY`).  The settings screen reads any
scalar as a field: `lut_ValBit` its lowest bit, `lut_ValMask` the mask in
place, the whole byte for every older row.  `opt_field_get` reads it,
`opt_field_put` writes it back without touching its neighbours (a pushed
field merged with `ORA $01,S`, an opcode the harness's CPU gained for it).
Zero is vanilla throughout: Vanilla, Incentive, Treasure, Off -- so a save
from before them is a vanilla world, and no SAVEVER bump.  Gear reads
Treasure first, not Off, which would read as the piece taken out (user).

The item and gear rows read "Incentive", nine columns, so their readouts are
sixteen wide (`lut_ValShift` 4) and their labels at most eleven: the gear
goes by the game's own names, "Opal", "Power" and "White" with their icons
as the inventory shows them.  Descriptions: Key items by value; each item
row by value, Incentive and Loose shared and Free the old Free row's text;
Other items naming its nine; one shared by eight gear rows and the
Xcalber's own; one per Early flag.

`test_treasures` drives the Free items through the rows, and checks that
Incentive and Loose give nothing.  `test_rando_options` steps packed rows
in a byte whose other bits are all set, and reads every key item row with
only one field set, from the settings and from the save, so two rows that
alias one field cannot pass.  `test_saveview` scrolls the view through the
whole section from a save whose fields alternate, against settings that
differ in every one.

### Map shuffle

**Built 2026-10-14; not yet played.**  FFR's Entrance Shuffle and Entrance
and Floor Shuffle as one row under Key items (user: three values, not two
rows), saved with the game: Off; Entrances, every overworld dungeon and
castle entrance leading into another's; Floors, the entrances and the
stairs and teleports inside too (the user's readout; its description says
"As Entrances").  Towns stay put, as FFR's preset has them.  Only under
Key items Standard or Wide, as in FFR: `rando_place` clears it under Vanilla,
and when no wiring of the seed's 16 places, so the save -- and the save view
-- says Off whenever the world is vanilla.  Under it the rescued Princess no
longer teleports the party to Coneria Castle, as in FFR (user: the warp can
strand the player), and key items are placed with FFR's unsafe tables, as
FFR does under Entrances -- tied to the mode, not a row of its own (user,
to keep FFR's flags down).  How it works is `randomization-notes.md` §9.3.

The row is a whole byte appended to the new-game settings (`RANDO_ENTRANCES`,
`OPT_NG_ENTRANCES`), so zero is Off in every older option block and save;
`OPT_FORMAT` and `SAVEVER` stay.  "Entrances" is nine columns, so its
readouts are the item rows' width and its label at most eleven; one
description per value.  `test_rando_options` steps it and reads it alone,
from the settings and from the save; `test_saveview` shows it.

### Respond rate

**Decision: independent of the presets.**  It keeps its own title-screen
control and its own byte in the options block, and defaults to 8.

Stored 0-based and displayed `+1`, so 8 is a stored 7 -- which is also what
FFR's speed hack uses.  It is explicitly zeroed in two places,
`game/bank_0E.asm:94` and `:3454`; both must load from the options block
instead or the default will not stick.  `TitleScreen_DrawRespondRate` is at
`game/bank_0E.asm:3630`.


## 4. Value rows

| setting | range | step | positions | Super |
|---|---|---|---|---|
| Gold + XP | 0-500% | 50% | 11 | 250% |
| Encounter rate | see below | -- | 14 | 60% |
| Enemy stats | 25-500% | 25% | 20 | 100% |
| Boss stats | 25-500% | 25% | 20 | 100% |
| Elemental bonus | +0 to +50 | 2 | 26 | +30 |
| Trap tiles | Off, Shuffle, A, B, A+B | -- | 5 | Off |
| Shops | Off, Shuffle | -- | 2 | Off |
| Chests | Off, Shuffle | -- | 2 | Off |
| Magic levels | Off, Shuffle | -- | 2 | Off |
| Item magic | Off, Shuffle, Balanced | -- | 3 | Off |
| Max gear blessing | 0 to +5 | 1 | 6 | 0 |
| Min gear curse | 0 to -5 | 1 | 6 | 0 |
| Formation rarity | Off, Shuffle, Tiered | -- | 3 | Off |
| Formation zones | Off, Light, Shuffle, Random | -- | 4 | Off |
| Unrunnable fights | Off, Shuffle | -- | 2 | Off |
| Surprise rates | Off, Shuffle | -- | 2 | Off |
| Status attacks | Off, Shuffle | -- | 2 | Off |
| Enemy scripts | Off, Enemies, Bosses, Both | -- | 4 | Off |
| Enemy skills | Off, Enemies, Bosses, Both | -- | 4 | Off |
| RNG tables | Off, Shuffle | -- | 2 | Off |
| Thief and Ninja hit% | +2, +3, +4 | 1 | 3 | +4 |
| Thief lockpicking | Off, level 1, 5, 10 ... 50 | -- | 12 | 15 |
| Starting items | None and FFR's eight sets | -- | 9 | None |
| Starting caster item | Off, On | -- | 2 | Off |

Each stores a step index in one byte.  Adjusted with left/right, consistent
with the existing Respond Rate control.  A readout is four columns, or eight
where `lut_ValShift` says so: the RANDOMIZATION rows, for "Shuffle".  The wide
field starts four columns early, over the end of the label's, so those rows'
labels have 18 columns, and every readout ends in the same column.  `opt_value_adjust` and
`opt_value_ptr` find the byte through `lut_ValOff`, an offset into the option
page per scalar, so a value row's byte can live anywhere on the page.  Until
the trap row they reached it as `OPT_GOLDXP, X`, which is why the five dials
are adjacent and why the fifth one was a format bump.

The elemental bonus is the odd one out in two ways.  It reads `+N` rather than
a percentage, and its field is right-aligned one column left of the others --
the percentage rows spend their last column on the `%`, so right-aligning it
would put its digits under that sign instead of under their digits.  Aligning
the numbers to each other reads better than aligning the fields.

Its presets: vanilla +4; Improved +10, FFR's slider default; Super +30, FFR's
default preset and most of the rest (its 2025 tournament presets use +42).
Improved's +10 was taken for FFR's Improved Vanilla value, but that preset
leaves the bonus checkbox off, which keeps the cartridge's +4: the slider's
10 never applies.  `ffr-presets.md` §2 lists it with Improved's other
departures from FFR's preset.


## 5. Encounter rate

### What the data actually looks like

`lut_BattleRates` is 63 map entries (entry 0 is an unused overworld slot).
57 of them are exactly 8.  The overworld is a hardcoded `LDA #10` and the ocean
a hardcoded `LDA #3` at `game/bank_0F.asm:1188` and `:1192` -- so the
feature has **three** inputs, not one.  `battlerate` itself is written at
`game/bank_0F.asm:1773` and `:3757` and compared at `:3303`.

Decompressing every standard map and checking it against its own tileset's tile
properties shows that **23 of the 63 maps have a nonzero rate but no
random-encounter tiles at all** -- every town and castle, plus ToFR Chaos
(map `$3B`, rate 1).  Those rate bytes are never consulted.

The rates that are live are 8 (35 maps), 9/10/11/12 for the four ToFR elemental
floors, and 24 for the sky bridge (map `$33`, 138 encounter tiles).

**Consequence: the lowest live rate is 8, so no clamp is needed.**  An earlier
draft proposed flooring scaled rates at 1 to stop low settings silently
disabling maps.  That was only ever protecting ToFR Chaos's rate of 1, which
does nothing.  Dropped.

### Stepping

**Decision: label the steps by their overworld effect, table the two hardcoded
bytes, and compute only the per-map dungeon rate.**

The overworld base is 10, so 10% steps are *exactly* the integers 1-10 -- and
the overworld is what people actually tune.  Each step stores an overworld
byte, an ocean byte, and a dungeon numerator over 16.  The first two are exact
by construction and hand-editable; the dungeon rate is
`(rate * N + 8) >> 4`, a shift rather than a divide.

| label | OW | ocean | N/16 | dungeon (8) | ToFR 9/10/11/12 | sky bridge (24) |
|---|---:|---:|---:|---:|---:|---:|
| Off | 0 | 0 | 0 | 0 | 0/0/0/0 | 0 |
| 10% | 1 | 1* | 2 | 1 | 1/1/1/2 | 3 |
| 20% | 2 | 1 | 3 | 2 | 2/2/2/2 | 5 |
| 30% | 3 | 1 | 5 | 3 | 3/3/3/4 | 8 |
| 40% | 4 | 1 | 6 | 3 | 3/4/4/5 | 9 |
| 50% | 5 | 2 | 8 | 4 | 5/5/6/6 | 12 |
| 60% | 6 | 2 | 10 | 5 | 6/6/7/8 | 15 |
| 70% | 7 | 2 | 11 | 6 | 6/7/8/8 | 17 |
| 80% | 8 | 2 | 13 | 7 | 7/8/9/10 | 20 |
| 90% | 9 | 3 | 14 | 7 | 8/9/10/11 | 21 |
| 100% | 10 | 3 | 16 | 8 | 9/10/11/12 | 24 |
| 150% | 15 | 5 | 24 | 12 | 14/15/17/18 | 36 |
| 200% | 20 | 6 | 32 | 16 | 18/20/22/24 | 48 |
| 300% | 30 | 9 | 48 | 24 | 27/30/33/36 | 72 |

`*` The ocean base is 3, which rounds to 0 below about 17%.  **Decision: floor
it at 1.**  This only bites at the 10% step; 20-40% round to 1 on their own.
The alternative -- no sea encounters at all on the lowest setting -- is a
surprising thing for a rate labelled 10% to do.

The 100% row reproduces vanilla byte for byte.  That is the property to
regression-test first.

Above 100% exists for completeness rather than because anyone will play it.

### Where the scaling happens

Overworld and ocean bytes are read straight from the step table -- no
arithmetic, so no rounding drift.  The dungeon rate is scaled at the two
`STA battlerate` sites.


## 6. Storage

The options block lives in SRAM, outside the save block, with its own
integrity check.  See `analysis.md` for why SRAM is not enlarged: the repo
already tried a paged 16KB SRAM and abandoned it, and above 8KB the window's
identity would depend on which chunk is live.

**Decision: evict `theend_drawbuf` to WRAM to make room, and put the block at
`$6E00`.**  The buffer occupies `$6800` for `$700` bytes but is used by exactly
one scene, the ending pen-plot at `game/bank_0D.asm:340`.

**The free page is `$6E00`-`$6EFF`, 256 bytes -- not the 334 bytes at `$6DB2`
an earlier draft claimed.**  That draft read variable *start* addresses without
their sizes.  `lutmp_ch_magic` at `$6D00` is a full page: `LineupMenu_Finalize`
(`game/bank_0E.asm:2453`) copies `$100` bytes into it, so `$6D00`-`$6DFF`
is live whenever the player rearranges the party, and anything at `$6DB2` would
be destroyed by ordinary play.

What makes `$6E00`-`$6EFF` safe is checkable rather than inferred:

  - no named variable in `variables.inc` starts anywhere in that page;
  - the only `$6Exx` literals in the whole tree are two CGRAM colour words in
    `src/nespal.inc`, which are data, not addresses;
  - the highest-reaching indexed buffer below it is `lutmp_ch_magic`, and
    `$6D00 + $100` stops at `$6DFF`.

So the page is claimed by `theend_drawbuf` alone, and moving the buffer frees
it outright.  Precedent for the move: `tools/convert.py` already relocates
`mm_decorchr` to WRAM `$0D00` under `DECOR_IN_WRAM`, and WRAM bank `$7F` is
64KB of untouched space.

**Any future scavenging of this 8KB must be checked the same way.**  Start
addresses are not extents, and several buffers here are deliberately overlaid
on each other because their scenes are mutually exclusive.  Coverage by a
single name is the test, not absence of a name.

Layout, 19 bytes of the 256:

    (at OPTBLOCK = $6E00, 19 of the 256 bytes available)
    magic       2    distinguishes an initialised block from battery noise
    version     1    format version
    preset id   1    0-2 preset, 3 = Custom
    flags       6    checkbox bits; 26-36 spare since format 9
    scalars     7    gold/XP, encounter, enemy, boss, elemental, Thief hit,
                     starting items -- step indices
    respondrate 1    0-based
    checksum    1    sum forced to $FF, as the game's own save does

The derived bytes (`OPTD`) follow at `$6E13`, eleven of them, then SOFT in
battle's two (`OPTBTLSOFT`, `OPTDRINKROW`) at `$6E1E`; `OPTSCRATCH` is
`$6E20`.  `snesmap.inc` asserts they do not overlap.

Two more ranges on the page belong to the randomizer:

    $6EC4  pool      4    entropy for the seed; stirred every frame, unchecked
    $6EC8  new game 22    one byte per RANDOMIZATION row, then the key item rows
                          packed into seven; in the save block's order
    $6EE0  ai       16    the script an enemy is choosing by (OPTAISHADOW)
    $6EF0  gear      8    a blursed weapon or armour record, for the adjusters
    $6EF8  name      8    a blursed item name and its terminator; "None"
                          padded to seven, for the None's class name

The new-game bytes are covered by the checksum -- `opt_sum` adds them after the
block's eighteen -- and cleared by every preset.  The pool is deliberately
outside it: battery noise on a fresh cartridge is welcome there.

`OPT_FORMAT` is 9.  It went to 3 when the flag word grew its fifth byte, to 4
when the elemental bonus became a dial and needed a fifth scalar, to 5 when
the checksum took in the new-game bytes, to 6 when Thief hit growth became a
sixth scalar, to 7 when the starting items took a seventh, to 8 when the
flag word grew its sixth byte, and to 9 when the Free items left the flag
word (bits 26-36 are spare) for the key item rows; each bump
costs a cartridge its saved settings once, on the first boot after.  The Shops, Chests, Magic,
gear and Map shuffle bytes did not bump it:
an appended byte whose zero means off reads correctly in an older block, and
anything else there fails the checksum and resets to a preset.

The flag word was four bytes until the Treasures section needed bits 26-36.
Widening it moved everything after it, which is exactly what the version byte
is for: `OPT_FORMAT` went to 3 and the first boot on an existing cartridge
discards its settings and falls back to the default preset.  That looks like
the settings being forgotten and is the check doing its job.

**Decision: include a format version byte.**  An options block changes shape
between builds, and a stale block that still checksums correctly is worse than
one that is obviously absent.  On a version mismatch, fall back to a preset.

**Decision: keep the block strictly outside `$6400`-`$67FF`.**  `SaveGame`
(`game/bank_0E.asm:5806`) copies that range wholesale from `unsram` and
`VerifyChecksum` sums exactly those `$400` bytes.  Staying clear of it means
the two integrity checks never interact, and options survive starting a new
game.

The checksum scheme is modelled on the game's own at
`game/bank_0E.asm:5837`.

**Decision: scratch above the checksum is initialized at boot, and any byte
that outlives the routine writing it is treated as hostile until proven
otherwise.**  `OPT_SIZE` is `$13`, so only the settings are covered by the
checksum -- everything from `OPTBLOCK+$13` up is working storage that happens
to live in SRAM.  That is fine for per-call scratch, which every routine writes
before it reads.  It is not fine for a byte whose lifetime spans screens.

`OPTPOSE` (`OPTBLOCK+$B0`, four bytes) was the one such byte: the shop writes
the victory poses, the main menu reads them a screen later, and `opt_zeroposes`
was the only thing that cleared them.  On a cartridge that had not yet been
through a shop they read as whatever the battery held.  `DrawOBSprite` adds the
byte to its tile base with `CLC` / `ADC` and no range check, so `$FF` from a
fresh cartridge drew the entire party one tile into the previous class's CHR --
a scramble that was per-character, changed with the party, survived resets and
power cycles, and could not be reproduced under emulation, where the `.ram`
starts zeroed and zero is the correct value.  The party-creation screen was
unaffected because it calls `DrawSimple2x3Sprite` directly and never reaches
the hook.

Two locks, because they fail differently.  `opt_init` zeroes the poses on every
boot, before the magic and checksum tests rather than inside the reset path: a
block that validates perfectly says nothing about the bytes above it.  And
`opt_pose` tests Shop Information and clamps its own result, because the hook
site is an unconditional `JSL` on `DrawOBSprite`'s standing path -- the read
happens in every menu whether the feature is on or not, so the value has to be
safe rather than merely usually zero.

`OPTCTX` (`+$C1`) is the other byte that selects a drawing path rather than
feeding one calculation; it is written by every screen that draws a description
box, but it is the next one to check if anything similar appears.


## 7. Changing settings on an existing save

Options are reachable only from the title screen, so there is never an
in-progress game state to corrupt.  The question is whether a setting applies
cleanly to a save made under different settings.

**Decision: no separate in-game UI.**  Save, soft reset, change, continue.

### Fully retroactive -- the large majority

Everything read at the point of use: speed hacks, movement speed, encounter
rate, gold/XP, enemy and boss scaling (`LoadEnemyStats` runs per battle,
`game/bank_0C.asm:6142`), crit rate, elemental bonuses, spell effectivity,
LOCK/LOK2, and all the menu and UI features.

Two verified rather than assumed:

  - **Autosort is safe.**  It reads the saved item array at `$6020` and builds
    the sorted list in `str_buf`/`item_box` at `$0300`, a shared RAM scratch
    buffer.  It never reorders the save.
  - **Chests Appear Opened is retroactive in the right direction.**  It reads
    the saved chest flags at `$6200` on map load, so enabling it mid-game shows
    chests already looted rather than resetting them.

### Needs a recompute on load

`ch_dmg`, `ch_hitrate`, `ch_absorb`, `ch_evade` and `ch_resist` are
`ch_substats` inside `ch_stats` = `unsram+$0100` -- **inside the saved block**.
They are derived values, cached in the save and recomputed only on equipment
change or level-up.  `UnadjustBBEquipStats` and `ReadjustBBEquipStats`
(`game/bank_0F.asm:10974` and `:11014`) write them.

**Decision: re-run the equipment-stat recompute for all four characters
immediately after Continue.**  That makes the Weapon Stats fix safe to toggle
on an existing save, and it is why the BB absorb fix could be made
unconditional without a migration step.

### Partially applied by nature

**Better Thief + Ninja** is `HitGrowth` and `AgiStarting` plus agility growth --
class growth tables and starting stats.

**Decision: accept that it applies at character creation and future level-ups
only.**  Starting stats do nothing on an existing party, and a level-30 Thief
keeps what it accumulated under vanilla growth.  Recomputing stats from level
is not worth attempting.  The description text should say so.

### Fixed at New Game, kept in the save

The **NEW GAME** rows.  `rando_newgame`, called from `opt_freestuff`, copies
them into the save block at `$60A0` with the seed.  From then on the save's
copy is the only one read.  A Continue gets the world it was started with,
whatever the menu says now.  That is the point: a menu row must not quietly
change the world under a game in progress.

### Writes saved state by design

**NPC Guillotine** is one-way.  `HideThisMapObject`
(`game/bank_0E.asm:805`) clears the object's visibility bit in
`game_flags` = `unsram+$0200`, inside the saved block.  Swatted NPCs stay dead
across save and reload, and turning the flag off does not bring them back.
The description text should say so.


## 8. Implementation notes

**NPC repositioning** (under Speed Hacks).  `LoadMapObjects`
(`game/bank_0F.asm:9438`) reads
15 objects of 3 bytes each (`$30` per map) and expands each into 16 bytes of
`mapobj` at `$6F00`.  It is called from one site,
`game/bank_0F.asm:3688`.

**Decision: a patch list applied after the load, not a duplicate table.**
Duplicating costs 3KB for fourteen moved NPCs.  Entries of (map, slot, x, y,
flags) walked after the load are about 70 bytes of data and 40 of code.
`inRoom` and `stationary` are bits `$80` and `$40` of `mapobj_flgs`.  Safe to
toggle: objects reload from ROM on every map entry.

**NPC Guillotine.**  Vanilla already has the behaviour.  `Talk_CoOGuy`
(`game/bank_0E.asm:1487`) hides the object and prints its text -- exactly
what swatting means.  The hook is in `TalkToObject`
(`game/bank_0E.asm:681`): after the script pointer is fetched and before
`JMP (tmp+6)`, substitute `Talk_CoOGuy` for `Talk_norm` when the flag is on.
About 15 bytes.  FFR protects LutePlate and RodPlate, which are `Talk_norm`
objects whose removal breaks progression; the object ID is still in hand at
that point, so the same two exceptions are cheap.  *Since 2026-10-13* the
substitution is `rando_talk`'s, in the randomizer's chunk: the funnel in the
fixed bank (still `OptGuillotine`) is now a JSL and a jump, and `rando_talk`
also runs the reward NPCs (`randomization-notes.md` §3).

**Use the SNES hardware multiplier.**  `$4202` x `$4203` -> `$4216/$4217` is an
8x8 -> 16 multiply ready in 8 cycles.  Nothing in the port references these
registers today.  Every scaling feature -- gold/XP, enemy and boss stats, the
dungeon encounter rate -- wants exactly this, and it removes the need for a
software multiply routine in banks that have no room for one.

**Gold and XP scaling** hooks after `SumBattleReward` in `EndOfBattleWrapUp`
(`game/bank_0B.asm:641`).  **Enemy and boss scaling** hooks the ROM-to-RAM
loop in `LoadEnemyStats` (`game/bank_0C.asm:6142`), which already copies
each enemy's stats through `lut_RomRamMapping` -- so no duplicate tables, and
it re-reads the flag every battle.


## 9. Open items

  - Super values are provisional and expected to be retuned.
  - Condensing all 30 descriptions to 5 lines, from the FFR tooltips, plus an
    original for Boss Stats and the two save-compatibility caveats.


## 10. Implementation status

**Everything through commit ddf45b8 has been played** (user, 2026-10-09): a
full playthrough with every flag enabled, after the earlier rounds that each
covered part of it.  Nothing built is waiting on a playtest.

### Done and in `main`

  - **The options chunk.**  `CHUNK_OPT = $11` at PBR `$B2`, wired through
    `snes.cfg`, `build.sh` and `mkrom.py`.  `EXTRA_CHUNKS` in `mkrom.py` is the
    list to add to for further banks.  `src/optbank.asm` holds the block, the
    presets and the feature hooks; `src/optmenu.asm` holds the screen.
  - **The ending buffer** moved to WRAM `$7F`, freeing `$6E00-$6EFF` for the
    option block.  Three HAL routines do what bank `$0D` no longer can:
    `hal_theendclear`, `hal_theendplot`, and `hal_theendand` for the fill
    pass's "left wall" *read*, which is the one easy to miss.
  - **The option block** at `$6E00`, validated from `GameStart`, with presets
    in `lut_Presets`.
  - **The title screen's mode row**, and **the settings screen**: scrolling
    list, checkboxes, section toggles from the headings, value rows with
    readouts and left/right adjustment, half-screen paging, and the
    description pane.
  - **`hal_ntblit`**, which is what makes the repaint affordable -- a row of
    single `$2007` writes was a couple of hundred cycles a tile.
  - **The menu chirps.**  The screen plays the game's own `PlaySFX_MenuSel`
    and `PlaySFX_MenuMove` through `OptCallFar` rather than writing the APU
    registers out again.  A chirp means something changed: pressing up at the
    top of the list, `A` on a value row, or left at 0% is silent, which is
    what the screen shows too.  `$4007` goes through `hal_w4007`, not a plain
    shadow store, and the HAL's sweep infers a replayed effect from `sq2_sfx`
    going *up* -- get either wrong and the chirp sounds once and then stays
    flat however fast the cursor moves.
  - **The Credits row and the credits screen.**  The title screen has four
    rows: Continue and New Game moved up four (`optcredits_continue.patch`,
    `optcredits_newgame.patch`) so the mode box sits at row 16, Credits at 20
    and the respond rate stays at 24.  `opt_titlechoose` tells the mode row
    from Credits, so the `@OptionChosen` patch only changed a `BNE` to a
    `BCC` and the target of a `JSL` -- bank `$0E` grew by nothing.
    The screen is `src/credits.asm` in its own chunk, `CHUNK_CREDITS = $12`,
    and is native SNES code rather than the game: mode 7, the game's font
    expanded from bank `$09`'s 2bpp CHR to 8bpp at entry, white on the
    prologue's blue (`NESCOL_01`/`NESCOL_30`, which `genpal.py` now writes
    to `src/nescol.inc`).  The text lies on a plane tilted back from the
    screen.  With M7B, M7C and M7D held at zero a line's scale is M7A alone
    and its texture row M7Y alone, so three HDMA channels do the whole
    effect: 6 the scale (a ROM table), 7 the row (indirect, into one of two
    WRAM buffers `cr_fill` rewrites each frame from the scroll, in eighths of
    a texel), and 5 the text colour, faded to the background over the top of
    the screen.  `tools/gencrawl.py` builds all three at build time; its
    parameters are the tuning, overridable from the environment
    (`CRAWL_ANGLE=50 ./build.sh`).  Settled at angle 50, zoom 1.5, fade 96.
    It still borrows the game for the music and the pad, once a frame in
    emulation mode (`cr_frame`).
  - **Lending the PPU.**  Two HAL entry points make a native screen possible
    without it knowing about the shadows.  `hal_vblaudio` is `hal_waitvbl`
    without the flush: sound goes out, nothing reaches the PPU.
    `hal_ppureclaim` hands the hardware back -- VRAM and CGRAM cleared,
    `init_ppu`, the CHR shadow sent at once and the tilemap, palette and OAM
    marked dirty end to end -- so the screen may use all of VRAM and restore
    nothing.  `init_ppu` now also zeroes MOSAIC, the window registers, WBGLOG
    and WOBJLOG and TMW/TSW, which the port never wrote and a console does not
    promise are zero at power-up.  The credits variables and row buffers sit
    at the bottom of WRAM bank `$7F`, clear of the ending's `THEENDBUF`.

  - **The randomizer's foundation, proven on Trap Tiles.**  Design and the
    tiers after this one are in `randomization-notes.md`.
      - **The chunk.**  `src/rando.asm`, `CHUNK_RANDO = $13` at PBR `$B4`.
        It runs with DBR = `$7F` and reaches everything else long.
      - **The save block** at `$60A0`: seed (4) and one byte per NEW GAME
        row.  Page 0 is zero-filled from `lut_InitUnsramFirstPage` on boot,
        so every older save reads as seed 0, everything off -- the vanilla
        world.  That is why introducing it needed no `SAVEVER` bump.
      - **The checksum version.**  `SaveGame` seeds its sum with `SAVEVER`
        and `VerifyChecksum` expects `SAVEK = $FF - (2*SAVEVER mod 255)`.
        Both are operand changes, and at version 0 the bytes are vanilla's.
        Bump it when a change would give an existing save a different world.
      - **The PRNG** is xorshift32 (13, 17, 5).  Each feature has its own
        stream, seed XOR a constant, warmed up 8 steps.  Bounded draws use
        mask-and-reject, never a modulo.
      - **The seed** comes from a pool at `$6EC4`.  `rando_stir` folds
        `JOY1L/H` into it and steps it every frame from `opt_padreset`.
        `FFSEED=xxxxxxxx ./build.sh` forces a seed.
      - **The cache** is at `$7F:8000`, tagged with a marker byte plus a copy
        of the save block.  The tag is cleared first and written last.
        `GameStart`'s `@Begin`, where New Game and Continue meet, builds it
        (`JSL rando_ensure`, since 2026-10-09; at first each consumer built
        it lazily, which stopped paying once a full world took ~0.85 s).  It
        asks `rando_stale` first, and only on a miss silences the music
        (`DisableAPU`) and calls `rando_ensure`: nothing calls the driver
        during a build, so the SPC700 held its last note through it, and the
        overworld track `PrepOverworld` starts next turns the channels back
        on.  A match costs 116 instructions and leaves the music alone.  L+X
        and L+Y keep WRAM, so the soft resets do not rebuild.  Since
        2026-10-14 New Game builds the cache itself, at the end of
        `rando_newgame`, after placement and before party creation (user:
        one pause, and all the randomization done before the party-select
        screen, which a future class flag will need); it silences the music
        first, and party creation turns it back on.  `@Begin` then only
        compares the tag, and builds for a cold Continue.  Consumers still
        `ensure`, as a safety net,
        except that `rando_nameptr` ensures only for gear ($1C-$6B).  It is
        the game's one table of short names, and party creation draws its
        class names through it after New Game has written a new seed:
        ensuring there built the world on that screen, a pause under its
        music (playtest, 2026-10-09).  New Game now builds first, so that
        screen would find the cache whole either way.
      - **Trap Tiles.**  The cache holds all eight tile property tables, 2KB.
        Every random-encounter tile's `$80` becomes `$00`, and the 34 traps
        are dealt per FFR's `ShuffleTrapTiles`.  `LoadSMTilesetData`'s
        20-byte property copy is now a `JSL rando_tileprop`, an `MVN` from
        the cache, which leaves `tmp` as `Copy256` did.  `SMMove_Battle`'s
        `BPL` became `BNE` (FFR's `UpdateTrapTilesCode`), so zero is the
        random encounter and `$80` up is a B-side.  The rewrite and the `BNE`
        apply with the randomizer off as well; no map places a formation-0
        trap, so vanilla play is unchanged.
      - **`tools/randoref.py`** is the same generator in Python, held
        byte-identical by `test_options.py`.  Given a `.srm` it prints the
        world.  `cpu65816.py` gained `XBA` and `MVN`/`MVP` for it.
  - **The descriptions moved to a chunk of their own**, `CHUNK_OPTTEXT = $14`
    (`src/opttext.asm`, data only).  They were 53% of the options chunk, and
    the per-value descriptions would not have fit beside them.
    `opt_menu_desc` and `opt_menu_descptr` point the data bank there while
    they read, which is safe because nothing else they touch is in either
    chunk's ROM.  `src/optmenu.inc` holds what both files need: the row
    kinds, the pane's size and the record format.
  - **Shop shuffle**, FFR's ShuffleShops.  Weapons, armor and items are each
    pooled and dealt back out: every shop gets at least one, none more than
    five, and none sells the same thing twice.  If an entry fits nowhere, the
    type starts over, about one item deal in 750.  The Caravan is an item shop
    here as in FFR, so the BOTTLE can land in any town.  `rando_caravan` keeps
    the Caravan open once the fairy is out (FFR's `PermanentCaravan`), but
    only for a save whose shops are shuffled.
      - `LoadShopInventory` is a `JSL rando_shopinv` that MVNs a row out of
        the cache: 71 rows of 8 bytes at `$7F:9000`.  Each row is the five
        bytes the game used to copy, junk past the terminator included, so
        with shops off `item_box` is unchanged, inns' and clinics' prices too.
      - FFR's PURE-and-SOFT-in-Coneria is not ported.  FFR computes it from
        status-touch changes, entrance shuffle and Enemizer, none of which
        exist here yet.
      - A rebuild with both features on is up to about 83K instructions,
        once per world change.  `cpu65816.py` gained `STZ abs,X`/`dp,X`.
  - **Chest shuffle**, FFR's treasure shuffle with the key items pinned
    rather than placed.  The 234 chests that hold no key item trade contents,
    gold included.  TNT, CROWN, RUBY, FLOATER, TAIL, SLAB and ADAMANT stay.
      - The pool is FFR's 241 chests not marked unused.  Those are exactly the
        chest ids the 61 maps place.  The 14 unused ones and id 0 hold items
        nobody can reach, a Zeus Gauntlet among them.
      - `OpenTreasureChest`'s one read of `lut_Treasure` is a `JSL
        rando_chest` into a 256-byte cache at `$7F:9400`, one byte more than
        the `LDA abs,X` in the fixed bank.  Moving the routine out (+109)
        waits for Tier 2's pseudo-items, which need it.
      - The free items are not taken out of the pool yet; a Free X still
        leaves its chest's copy.  That changes with Tier 2: see
        `randomization-notes.md` §11.
      - A rebuild with all three features on is up to about 118K
        instructions, roughly nine frames by estimate, once per world change
        on the first map load.  If it shows, the build can move to New Game
        and Continue, where the screen changes anyway.
  - **Magic level shuffle**, FFR's ShuffleMagicLevels with its presets'
    settings.  FFR permutes the spell tables and mends everything that names a
    spell by its old index.  Here nothing moves: the cache holds the spell in
    each slot and the inverse, and a slot becomes its spell only where a
    character's slot turns into one.
      - The battle's spell list at `ConvertOBStatsToIB`, and back at
        `ConvertIBStatsToOB` (bank `$0B`, byte-neutral).  Everything in battle
        then deals in spells as it always did: records, messages, enemy AI,
        equipment, confused FIRE, Spell Fixes, Cast Life, LOCK and LOK2, the
        Improved spells.
      - The out-of-battle dispatch (bank `$0E`, byte-neutral).  It also mends
        the game's `ORA` for `ADC`, which the shuffle would make live for an
        8th spell, and makes an empty slot "can't cast".
      - Names: the magic menu's list (fixed bank, +1) and `ShopSelectBuyMagic`
        (bank `$0E`, byte-neutral).  The shop's string carries each item id
        twice; the name's becomes the spell's, the price's stays the slot's,
        and the level shown is read from the price's.
      - `opt_descgear`'s spell branch, for Shop and Magic Information.
      - `randoref.py` names the floor each chest is on, decoding the maps from
        the ROM, and `--find NAME` lists every chest and shop holding an item.
  - **Blursings**, FFR's RandomWeaponBonus and RandomArmorBonus.
      - The stat rules and names are FFR's.  Weapon: hit +3b (0..50), damage
        +2b and crit +3b (at least 1 each).  Armour: absorb +kb (at least 1)
        and the evade penalty -kb (at least 0; FFR calls it weight), with k = 2 for body armour.  The last two
        letters before the icon become the bonus.
      - Not ported: Exclude Masamune, and the clean-names preference.
      - Stats: the four record-pointer setups in `UnadjustEquipStats` and
        `ReadjustEquipStats` call `rando_weaprec`/`rando_armrec`, which copy
        the record into an SRAM shadow and point `(tmp)` at it.  The game's
        banks see SRAM and no WRAM above $2000.  Battle takes damage, hit,
        absorb and evade from the substats these build, and crit from
        `opt_weapcrit`.  `opt_weapbyte`/`opt_armbyte` read the blursed copy,
        and keep the caller's high byte of A, as they always did.
      - Names: the menu text's `$02`, the dialogue's `$02`, the equip menu,
        and the tail of `BattleDrawLoadSubSrcPtr` all ask `rando_nameptr`,
        which answers with the ROM's pointer or the SRAM buffer.  Battle's
        tail tells the item table from the others by bank and address.
      - These replacements are shorter than what they replaced, so the fixed
        bank went from 22 bytes free to 91.
      - A rebuild with everything on is up to about 145K instructions, once
        per world change.

### What a repaint costs

Two budgets, and they are not the same one:

  - **A frame holds about 196 scanlines of drawing**, once the screen's own
    loop -- `ClearOAM`, the cursor, `CallMusicPlay`, `UpdateJoy` -- has taken
    its 66.  Overrun it and the loop never reaches `WaitForVBlank`, so the
    music driver goes uncalled: an audible stall, and a chirp that starts and
    then sits on one pitch.
  - **A vblank holds about 37 scanlines of flush**, and a dirty row costs it
    roughly four: `nt_put` sends every row twice, once for the tilemap row and
    once for the duplicate that gives the NES's 30-row wrap, and each of those
    is an `nt_piece` whose setup costs several times its DMA.  Overrun it and
    the forced blank `hal_flush` holds runs into the picture, which is a black
    band across the top of the screen.

So a full-window repaint -- twenty rows and the description, about 660 bytes --
does not fit in either.  It is drawn five rows at a time, with
`opt_menu_breathe` (a vblank wait and a music call, the shape `DrawBox` calls
a stall) between the pieces.  Five ordinary frames rather than one long one:
the list arrives in bands over about 83ms, which at a single keypress is not
something the eye finds, and the cursor does not lag with it because a window
that scrolls keeps `SEL - TOP` constant.

What made the pieces small enough to be worth splitting:

  - **`flush_nt` walks only the dirty rows.**  It used to walk all thirty
    whatever was dirty, rebuilding four running addresses for each -- so five
    dirty rows, which is what a description update is, spent about 26
    scanlines of vblank stepping over clean ones.  The scan it already does
    now records where the dirty rows begin and end.  This is the whole game's
    hot path, not the menu's: it took the prologue screen's flicker with it.
  - **The palette's arithmetic runs before the wait** (2026-10-16; user:
    "forced vblank-looking flicker when walking on the damaging lava tiles").
    `flush_pal` converted each entry in vblank -- which ones moved, the tint,
    the grey, where it lands in CGRAM -- at about sixty instructions an
    entry, so a whole palette was some two thousand, most of a vblank.  The
    whole palette moves whenever greyscale or emphasis does, and
    `MapTileDamage` flips greyscale every frame on lava and ice, while the
    walk's dirty rows already fill vblank: a black band of thirty-odd lines
    across the top, flickering.  Now `pal_prep` converts from `hal_waitvbl`
    before the wait, as the frame's sound already is, into `PALSTAGE` records
    laid out for DMA mode 3 (CGADD twice, CGDATA twice), and `flush_pal`
    sends them with one DMA: a whole palette costs the vblank 22 more
    instructions and 128 bytes, about a scanline.  Measured in the harness by
    instruction count (2004 inside vblank before, 22 after), not yet with the
    ares profiler; `test_palflush` holds it, with the harness's 65816 now
    running general-purpose DMA when a test asks (`bus.dma`) and BRL.
  - **A walking frame's flush lost a third** (2026-10-16; user: "an
    occasional (unpredictable) flicker of ~8 forced vblank lines when
    walking").  The likely cause is the late serve: `hal_waitvbl` serves a
    vblank it arrives inside of up to line 244 (`LATE_FLUSH_LAST`), 17 lines
    from the end, on a measured 15 for a walking flush -- and a sideways step
    cost more.  Measured in the harness with the game's own `DrawMapRowCol`
    and `hal_drawattr` run into the HAL: a column frame's flush was 1713
    instructions, a row's 700-1060, an attribute frame's up to 1350, and
    most of it bookkeeping, not transfer.  `flush_nt`'s dirty-row scan
    switched the accumulator's width twice a row, clean rows included (435
    instructions a frame); `column_flush`'s gather was ten instructions an
    entry, 714 a step; the column path's clean-up marked rows a byte at a
    time.  Now the scan runs in eight bits, the gather is unrolled (thirty
    loads and stores), the clean-up goes a word at a time, and short spans
    go through the port sixteen bits at a store: a column frame is 1070, a
    row 680-950.  `test_ntflush` runs random row, column, attribute and
    scattered frames through the flush with the harness's DMA on -- which
    now steps VMAIN's 32-word increment -- and holds VRAM's tilemap to the
    shadow word for word, every row and its duplicate, every row clean
    after, and bounds a walking frame's cost.  Played the same day: "much
    improved", a band of two or three lines seen once or twice in a session.
    Not measured on the ares profiler; `LATE_FLUSH_LAST` is unchanged, and
    a late serve that asked how much the flush holds before taking the frame
    would be the next step for what is left.
  - **The description box is drawn once.**  It is rows 21-28 and the list is
    rows 1-20, so a repaint of the list cannot damage it.
  - **A checkbox or a value repaints one row**, not the window.  Nothing else
    on screen depends on a flag, not even the description.
  - **`opt_menu_scroll` says whether it repainted**, because a caller that
    then put the description back was drawing it twice on every scroll.
  - **Nothing calls a routine per byte.**  The staging loops write
    `NTSTAGE` directly, and `hal_ntblit` moves them into the raw nametable
    with `MVN`: the same two WRAM accesses per byte, without the compare,
    the branch and the two increments around them.

Measured with the profiler in the instrumented `ares`, which reports forced-
blank picture lines per frame; `tools/profranges.py` builds its range file and
its docstring says how to read the output.  Before: 8 blanked lines on a
cursor move, 71 and three music-less frames on a scroll.  After: none, with
the worst flush ending at scanline 255 of 262.

### Features reading their flags

  - **CUR4 out of battle**, the last of Spell Fixes.  Every spell in that
    menu refuses a dead or stoned target and comes back for another; CUR4
    never did, so it would refill a corpse's HP and the corpse stayed dead,
    because it still had the ailment -- spell and MP gone.  One byte-neutral
    hook over the HP copy.  The error sound and the retry stay at the call
    site: a routine that only decides can be run by the test harness, and
    `PlaySFX_Error` cannot, because it ends up spinning on an SPC handshake
    that `tools/cpu65816.py` does not model.
  - **TMPR and SABR on a player**, the largest half of Spell Fixes.  Disch
    marks both ends of it: `BtlMag_LoadPlayerDefenderStats` "does not load
    `btlmag_defender_strength`" and the save routine does not write it back,
    so the spell added its effectivity to whatever was at `$6882` and the
    result went nowhere.  The hit rate beside it was worse -- nothing in the
    game had ever named `$6884`.  Three byte-neutral hooks: the magdef load,
    the evade save, and the magdef save, which vanilla sends to the
    out-of-battle record where a change would outlast the fight.  FFR's
    fourth patch is not needed here -- it only stops calling
    `PrepareEnemyMagAttack` because it writes its new loader over that
    routine, and ours is in the options chunk.
  - **LOCK / LOK2 Mode**, and the LOCK half of Spell Fixes.
    `BtlMag_Effect_EvadeDown` prepares a hit roll and then unconditionally
    `JMP`s past everything it prepared, so vanilla LOCK and LOK2 do nothing
    at all.  Spell Fixes makes it the `BEQ` it should have been; the LOK2
    flag overrides that to always hit, which needed no second code path --
    accuracy 255 does it, because the roll is `[0,200]` and
    `BtlMag_DidSpellConnect` only compares the two.  The exception is the
    guaranteed miss on an exact 200, which `opt_lockroll` declines to take.
    **Disch's comment on that line is wrong**: it calls 200 an automatic hit,
    and every other spell in the bank treats it as a guaranteed miss.
  - **Cast Life in Battle** -- data, not code.  FFR writes no battle routine
    for LIFE and LIF2; it rewrites their records to routine `$08`, cure
    ailment, with the death element, and curing death is revival.
  - **Spell Fixes -- half of it.**  The four data corrections are in: LOK2's
    wrong routine, HEL2's effectivity, SABR's missing hit% bonus, and
    LOCK/LOK2 accuracy at 162.  The three code fixes are not: LOCK's `JMP`
    where a `BEQ` belongs, the TMPR/SABR defender-stat surgery, and CUR4.
    They need call sites in bank `$0C`, which has four bytes.
  - **All three spell flags go through one accessor.**  `opt_magicdata` used
    to copy the record and overwrite the two bytes a buff could move; it
    copies and then asks `opt_spelloverride` for each of the eight, which is
    the routine the shop's description box asks.  Buff beats fix beats the
    record, stated once.  That ordering is the HEL2 question: Spell Fixes
    lowers its effectivity to 24 and Improved CURE and HEAL raises it to 32,
    and the deliberate buff wins.
  - **Better Thief and Ninja** -- `opt_startagi`, `opt_startevade` and
    `opt_thiefgrowth`, which is FFR's `BuffThiefAGI`: the Thief starts with 80
    agility instead of 10, starts with evade 48 above that instead of 58, and
    gains agility at every level rather than one time in four.  Vanilla is
    agility 10 and evade 58, and 58 is 10 + 48, so the evade rule is the
    game's own relationship rather than FFR's invention.  Only the Thief for
    the starting stats, because promotion keeps what the character grew; both
    classes for the growth, since a promoted character levels on the Thief's
    data under the Ninja's id.
  - **Thief and Ninja Hit%** -- `opt_hitgrowth`.  Every level adds a per-class
    constant to hit rate, 2 for these two against the Fighter's 3; this adds
    the row's step on top, 0, 1 or 2, for FFR's "2 (Vanilla)", "3 (Moderate)"
    and "4 (Double)".  The vanilla constant stays in the table and nowhere
    else.  It is the block's sixth scalar, `OPT_THIEFHIT`; it was bit 21 as
    a Double checkbox, and bit 21 is unused again.
  - **Elemental and Type Bonus** -- a dial rather than a hook.  A physical
    attack matching the defender's weakness or category gets +40 hit chance on
    a base of 168 and +4 base damage on a base of the attacker's strength.  The
    hit half lands; the damage half is under a tenth of a mid-game weapon,
    which is why elemental weapons never felt different even once the element
    bug was fixed.  So the dial sets the damage half and leaves the hit half
    alone, exactly as FFR does -- `IncreaseWeaponBonus` in
    `FF1Lib/Balances.cs` is one byte written over the same immediate.
    `opt_derive` doubles the step into `OPTD_ELEMDMG` and bank `$0C` adds that
    byte instead of the constant, one byte more than the immediate it
    replaced.  **It needs Weapon Stats on to do anything for the party**: the
    attacker's element and category are only non-zero because `opt_weaponstats`
    fills them, so without it only monsters get the bonus.  **Fixed
    2026-10-09, played 2026-10-10:** the Ninja's Ice sword against Northwest
    Castle's trap AGAMA, Gold/XP at 500%, swung for 600 and more after other
    fights, where a lost bonus caps a swing near 410.  Off 100% Gold/XP, the
    end of every battle
    overwrote `OPTD_ELEMDMG` with a byte of the reward (see "A name is as wide
    as its widest use", below), so from the second battle on the bonus was
    usually 0 until the options were next committed.
  - **House restores HP and MP** -- `opt_housemp`.  A HOUSE restores MP only
    if the player accepts the save, and does it *after* the write, so the file
    just saved still holds the old MP.  The hook moves the restore in front of
    the save and makes it unconditional; the vanilla restore after it is left
    alone and runs a second time against full MP, which costs nothing.  Four
    bytes at the call site, because the body is a routine the test harness can
    run -- the ordering, which cannot be run, is asserted by reading the call
    site instead.

    It fills HP as well, in the same place and for the same reason.  Vanilla
    gives 120, which was a night's rest in Coneria and is a rounding error by
    the endgame.  FFR has these as two flags, `HouseMPRestoration` and
    `HousesFillHp`, both under bugfixes rather than variations; they are one
    switch here because nobody who wants either wants the other off.

    FFR's HP patch is two calls, `MenuFillPartyHP` and then `$B400`, which is
    `DrawItemTargetMenu`.  Both are needed.  `MenuFillPartyHP` only writes the
    numbers, while the `MenuRecoverPartyHP` the call site already uses ends in a
    `JMP` to that redraw -- so porting the fill alone left it correct and
    invisible, with the save prompt over a screen still showing pre-fill
    figures and the real ones appearing only after the save.

    `FFDEBUG=house` puts nine HOUSEs in a new game, because one is 3000 gold
    against a starting 400 -- but it cannot test the HP half.  A starting party's
    maximum HP is below 120, so the partial restore saturates and reads exactly
    like a full one.  That is why this went unnoticed through a playthrough, and
    why the test sets maximum HP to 999.
  - **Faster Walking** and **Faster Ship** -- `opt_movespeed` and `opt_owrate`.
  - **Encounter rate**, all three inputs: overworld, standard maps and
    dungeons.  The dungeon table is scaled through `WRMPYA`/`RDMPYL`.
  - **No Party Shuffle** -- `CondReSortParty` in the fixed bank, plus
    `opt_chkalivex` / `opt_chkalivey` for the two bank `$0E` sites.
  - **NPC Guillotine** -- `TalkToObject` substitutes `Talk_CoOGuy`, except for
    LutePlate and RodPlate.
  - **Speed Hacks**, which is the whole bundle rather than one switch:

        battle message box draw / undraw   opt_msgdraw, opt_msgdraw_rev
        battle transition                  opt_btltrans
        battle animation and explosions    opt_setbattlerate, opt_explodecount
        run delay and respond rate         opt_responddelay, opt_respondlookup
        screen wipe open / close           OPTD wipe constants
        dialogue box open / close          OPTD dialogue constants
        lineup menu animation              three bank $0E sites
        palette cycling                    opt_palcyc
        NPC repositioning                  opt_movenpcs

  - **Battle Magic Menu Wraparound** -- `opt_magicpgdn` / `opt_magicpgup`.
  - **Autosort Inventory** -- `opt_sortinv`, after `DrawItemBox`'s own fill.
  - **Auto Retargeting** -- `opt_retarget` and `opt_retarget_mag`.
  - **Run -> Wait** -- `OptRunLabel` and `OptRunFail`, both in the fixed bank.
  - **Identify Treasures** -- `opt_dlgident`, with the replacement string at
    `lut_CantHoldWhat` in the fixed bank.
  - **Enemy Status Attacks** (Bugfixes) -- `opt_thishit`.
  - **Gold and XP scaling** -- `opt_scalereward`, by repeated addition into a
    32-bit accumulator, saturating rather than wrapping.
  - **Enemy and Boss stat scaling** -- `opt_scaleenemies` / `opt_scaleatk`,
    reproducing FFR's `RangeScale` exactly: with low equal to high the random
    exponent drops out and the result is `value * (1 + (p-1) * adj)`, rounded
    half to even because C#'s `Math.Round` is.
  - **Repeated Potion Use** -- `opt_usedpotion`.
  - **Buy Quantity** -- `OptShopConfirmQty` and its loop in the fixed bank,
    with the arithmetic in `opt_shopmax` / `opt_shopscale`.
  - **Chests Appear Opened** -- `opt_openchests` rewrites the TSA at map load;
    `OptOpenChest` sends two tiles when one is opened.  The lid is drawn in
    `src/openchest.txt` and laid over CHR `$7E`/`$7F` by `mkrom.py`.
  - **Improved CURE/HEAL** and **Improved FIRE/LIT/ICE** -- `opt_magicdata`
    for battle and `opt_healroll` for the menu, over `lut_SpellBuff`.
  - **Weapon Stats** and **Double Weapon Crit Rate** -- `opt_weaponstats`,
    called from `LoadOneCharacterIBStats`, filling the three fields vanilla
    reads from nowhere.  The crit rate comes from `opt_weapcrit`, which is
    also what the shop box prints.  The enemy half is FFR's `0x325B0` write,
    left out at first: when an enemy attacks, `opt_scaleatk` (the existing
    `OptScaleEnemyAttack` hook, so no game bytes) zeroes the attacker's
    category and takes its element from ROM byte `$0E`, the touch's own
    element, in place of vanilla's `$12`, its *weakness*.  Against the party
    the element decides only whether resisting armour stops the touch's
    ailment: with the flag on an Aegis Shield stops a poisoner, and an Ice
    Shield no longer stops a ghoul's stun because ghouls are weak to fire.
    Played: ghouls against an Ice Shield, stuns blocked off and landing on.
  - **Shop Information** -- `src/optshop.asm`: the description box in shops,
    the equip menu and the magic menu, and the victory poses.

The remaining seven checkboxes toggle and persist, but nothing consults them
yet; they are listed under "What is left" below.

Speed Hacks also carries its own respond-rate table.  Vanilla's rates are a
poor fit once everything else is fast, so `opt_respondlookup` substitutes a
second table; it is checked to descend monotonically and never to reach zero,
because a zero there stalls the battle.

### Text that describes the game's own numbers

Shop Information is the first feature whose output is *about* the rest of the
settings, and it forced a decision worth recording.

FFR bakes its 144 descriptions as strings at generation time.  It has no
choice: its weapon and spell tables are randomised and the text has to agree
with whatever it rolled.  Here the tables are vanilla but the flags are not,
and baked text is wrong the moment one is toggled.  Double Weapon Crit Rate is
the plainest case -- FFR implements it by rewriting the crit byte in the ROM,
which is exactly what a runtime flag cannot do.

So the text is generated at run time, and **the rule that keeps it honest is
that nothing which draws may read a weapon, armour or spell field directly**.
Every such field goes through an accessor -- `opt_weapcrit`, `opt_weapbyte`,
`opt_armbyte`, `opt_spellbyte`, `opt_gearlive` -- and a flag hooks the
accessor rather than the thing that draws.  The accessors are shared with the
battle: `opt_weaponstats` and the description box both ask `opt_weapcrit`, and
`opt_spellbyte` and `opt_magicdata` both ask `opt_spellbuffed`.  There is one
definition of what a spell does, so the box and the battle cannot drift apart.

That rule pays immediately.  Splitting `opt_spellbuffed` out of
`opt_magicdata` failed an existing test on the first build, because HARM's
single-target change had been written against Improved CURE when it rides on
Improved FIRE -- the two flags had never been exercised apart.

Which flags this matters for, audited once so it need not be guessed at again:

    Weapon Stats            changes whether crit/element/category are live
    Double Weapon Crit Rate the crit byte
    Spell Fixes             LOK2's routine, HEL2's effectivity, SABR's accuracy
    Cast Life in Battle     LIFE and LIF2's whole record
    Improved CURE/HEAL      effectivity, and HARM's target
    Improved FIRE/LIT/ICE   effectivity

    House MP Restoration    no effect on any description
    Elemental/Type Bonus    changes a code operand, not a displayed value
    Better Thief + Ninja    class hit growth; the box shows permissions
    LOCK/LOK2 Mode          spell accuracy, shown only for routine $0D

**This is not multiplicative.**  Five of the six are byte overrides funnelling
through two accessors, so the renderer is correct for every combination
without knowing which flags are on.  Weapon Stats is the one structural case,
because it changes whether a field is live rather than what it holds, and that
costs exactly one conditional.

### Fitting the box

Generated text has to fit a box that cannot grow: the shop, equip and magic
boxes give **12 usable columns and 7 text rows**, the chest's full-width
dialogue box 28 columns and 8, and every description shares one 80-byte buffer
(`OPTDESC_MAX`) that `opt_emit` truncates in silence when it fills.

The lists are the hard part, and the layout is FFR's, from
`ShopInformation.cs`.  For resistances it keys off how many there are:

    1       "Resistance" and the element spelled out    Resistance / Poison
    2 - 3   "Resist" plus the first, then the rest      Resist Fire / Ice, Lit.
    4 - 7   two named and the remainder counted         Resist Stat / Pois and 2+
    8       all of them                                 Resist All

FFR keeps two columns of element names -- `Status/Stat`, `Lightng/Lit.` -- and
both are ported verbatim, long for the one-resistance line that has room and
short for the lists that do not.  The delimiters matter as much as the words:
the first name shares the header's line, the second opens a new one and the
third follows after a comma, which is what fits three names in two lines.  An
earlier version put the header alone on its line and stopped at two names, so
the Dragon Armour said "and 1 more" about an element there was room to name.

**The widths are measured, not reasoned about.**  `test_descsynth` patches
synthetic weapon and armour records into a copy of the ROM image and renders
items that do not exist, sweeping every byte of each record over its whole
domain and then applying every axis's worst value at once.  It measures three
separate things -- columns per line, rows per box, and total bytes against the
buffer -- because only the first is visible on screen when it goes wrong.

This matters for Phase 3 specifically.  Sweeping the cartridge's 52 items is a
regression test and nothing more; it cannot reach a combination the cartridge
does not contain.  The first run of the synthetic sweep found a line of 13
columns in the 12-column box, on a four-resistance armour that does not exist
in the cartridge and that a randomiser produces immediately.  Worst case now
sits at 12 columns, 7 rows and 66 bytes -- inside every limit, with no margin
on two of the three, so a new line or a longer word needs re-measuring rather
than estimating.

The box also takes the hand cursor off the screen, but only in the equip
menu -- the shop's box and cursor do not overlap, and clearing there would cost
the victory poses.  FFR does the same, in the same place.

Worth knowing for anything else that hides a sprite: `ClearOAM` does not hide
anything by itself.  It fills the NES staging page at `$0200` with `$F8`, and
the upload is a separate `$4014` write -- which in this port is what copies the
page into `OAMSHADOW`, which the *next* flush sends to the PPU.  So a bare
`ClearOAM` leaves the sprite on screen until the next ordinary frame.  The pair
is `ClearOAM`, then `LDA #>oam` and `wOAMDMA`; `DrawBox` stalls through
`MenuCondStall`, so one of those stalls uploads the blank while the box is still
being drawn.

Item names have a width too, and it is not generated -- it is vendored.  The
shop's inventory list is box 2 and `lut_ShopBox_Wd[2]` is `$09`, so seven
columns between the borders, which is why all forty weapon names and
thirty-nine of the forty armour names are exactly seven bytes, padded with
spaces or ending in an icon tile.  The fortieth is the Ribbon, `"Ribbon"` and
two spaces, whose eighth byte paints a blank over the right border when selling
armour to a character carrying one.  `mkrom.py`'s `overlay_ribbon` trims the
terminator back by one; FFR fixes the same byte in `ItemNames.Write`, via a
`FixRibbonSpace()` that drops character 7 when it is a space.
`test_itemnamewidth` asserts the rule over the whole table rather than that one
item, because Phase 3 renames these.

### The font page, and the rule for taking a tile from it

`LoadMenuCHR` loads eight rows to PPU `$0800`, so the font is tiles `$80-$FF`
and nothing else -- 128 tiles, which is why FFR's `"+"` at `$7B` and `"/"` at
`$7A` cannot be used here.  FFR gets away with them by replacing `LoadMenuCHR`
outright and loading its own CHR from a new bank; we have no such bank.

So the plus sign is painted over a tile in the page, by `overlay_plus` in
`mkrom.py`.  **The rule for choosing that tile is that the stock font must have
no ink in it.**  Not "no text region references it" -- that reasoning produced
two wrong answers and shipped both.

The top of the page is not spare kana.  It is battle-UI artwork: runs of
condensed lettering whose letters straddle the tile boundaries.

    $E2-$E5  "Poison"      $E6-$E9  "Stone"      $EA (+ $C8/$C9)  "Asleep"
    $EB-$EE  "MAGIC"       $EF-$F2  "FIGHT"      $F3-$F6          "DRINK"

`$E6` put a plus through the S of "Stone"; `$EC` put one through "MAGIC".
Neither is findable by surveying text, which is the point: the ailment names are
raw tile bytes behind `data_BattleMessages`' pointer table, and the command
labels are `.BYTE` runs inside bank `$0F`.  Any survey of strings will keep
missing things like these.  Ink will not -- artwork has ink, a free slot does
not.  `$C1` and `$FF` are the only two tiles with none, and `$FF` is the space,
so `$C1` is the only one there is.  `test_options.py` checks the tile against
`out/bank_09.bin`, the font before the overlay.

**A glyph code belongs in exactly one place.**  `CHR_PLUS` in `snesmap.inc` is
it; `mkrom.py` and `fftext.inc` are checked against it, and the harness parses
it rather than repeating it.  The one copy that was missed cost a second bug:
`lut_ValElem` had the sign as a literal `$E6` in all twenty-six entries, so
after the move the elemental dial read "S50" -- the S of "Stone" again.
`test_dialvalues` now requires every byte the five dial tables draw to be in
the glyph set `FFCHAR` maps, which a stale literal falls outside the moment the
glyph it names moves.

### Menu row labels

A row in `lut_OptRows` stores thirty bytes of label after its two header bytes
and the menu draws `OPTROW_LABELW` of them, which is twenty-two.  Padding to
thirty therefore proves nothing: `FFPAD {"House restores HP and MP"}, 30`
assembled happily and the screen showed "House restores HP and".  Use the
`OPTLABEL` macro, which checks the width that is drawn and pads out the rest, so
a long label is an assembly error.  `test_rowlabels` covers the rows that
predate it by looking for a glyph in the bytes past the drawn width.

### How to port the next flag

**Match by routine name, not by address.**  Three trees are involved and only
one of them is a reliable coordinate system:

  - the **disassembly**, which is fully labelled -- that is its whole value;
  - **FFR**, which is a 512KB expansion with banks moved wholesale (`0F` to
    `1F`, `0B` to `1B`, `0E` to `1E`) and whose offsets reflect its own earlier
    patches, so a site may already be FFR-modified code rather than vanilla;
  - the **SNES port**, whose fixed bank has been reshaped by its own patches.

So the order of work is:

  1. **Read FFR for the semantics** -- `FF1Lib/asm/` has commented sources for
     much of the list, and the tooltips say what the flag is meant to do.  Use
     it to learn *which routine* and *what change*, never to derive an address.
  2. **Find that routine by name** in `game/bank_*.asm`.  Disch's labels are
     the common vocabulary between the three trees.
  3. **Confirm the site reads the way FFR describes** before changing it.  If
     FFR's bytes and the port's source disagree about what is there, FFR is
     patching something FFR already moved.
  4. Generate a listing when an exact address is genuinely needed -- it gives a
     line-to-address map for every bank:

         cd gen && ca65 --cpu 65816 --feature force_range -I ../src \
             -l bank_0C.lst bank_0C.asm -o /dev/null

     FFR's offsets exclude the iNES header, so `bank = offset >> 14` and
     `address = (offset & $3FFF) + $8000` -- useful as a cross-check on a name
     match, not as a substitute for one.
  5. **Keep the patch byte-neutral** unless it is in the fixed bank.  See
     "Edits to a bank must be byte-neutral" in `analysis.md`.
  6. **Put the body in the options bank** when a conditional will not fit.  A
     `JSL` plus `RTL` is usually smaller than the code it replaces, which is
     why both constrained banks have *more* free space now than at the start.

### What checks the work

Two failure classes are invisible in the source and were each found the
expensive way once, so both are now checked on every build:

  - **`tools/convert.py`** asserts the address of all 30 pinned `.INCBIN`
    blobs.  A patch that changes a bank's size moves every blob after it, and
    the symptom is wrong orbs and truncated strings, not a build error.
  - **`tools/check_bankswap.py`** finds every call from the options bank into
    the fixed bank that can reach `SwapPRG`, and fails unless `cur_bank` names
    the options bank first.  On hardware the symptom is a freeze.  It follows
    fallthrough as well as calls, which is how it finds the one that goes
    `Battle_UpdatePPU_UpdateAudio_FixedBank` -> `BattleUpdateAudio_FixedBank`
    -> `CallMusicPlay`.
  - **`tools/check_tables.py`** verifies the `_L` pseudo-jump tables are still
    runs of three-byte entries.  Other banks index them by arithmetic, so a
    routine tucked inside one assembles cleanly and silently displaces every
    entry after it.

`tools/test_options.py` runs the hooks on the 65816 in `tools/cpu65816.py`
against the built ROM.  It tests the arithmetic, not the drawing -- the part
where a mistake is silent.  The suite is five and a half minutes of one
core's time, so it runs a process per test across the cores, about seventy
seconds on eight, and `test_descsynth`'s four thousand cases spread out
through `pmap`; `-j 1` is the old serial run.  Under `pypy3` the same suite
is fifteen seconds: its JIT runs the emulator 15-25 times faster, though a
light test pays a few tenths of a second more to start.  So
`python3 tools/test_options.py` hands itself to `pypy3` when it is installed,
mutation runs included; `FFNOPYPY=1` keeps CPython.  The randomizer
consumer tests call `warm(bus)` once the save is set, which hands every case
after the first to build a world the memory the cartridge's own build left,
instead of rebuilding it for each -- 469 identical builds were all but a
fraction of `test_rando_chestload`'s 37 seconds.  A world stays cold until a
case has built it through the consumer's own call to `ensure`, so a
consumer that skips the call still fails every case.  Break the source and confirm a failure
appears before trusting a new group: `tools/mutate.py` takes a list of
mutations, each a replacement and the test that should notice it, and runs
them in parallel, each in its own rsync'd copy of the tree, after checking
every test passes unmutated.

For generated text it also checks the things that are invisible in source:
that all 240 gear descriptions and all 64 spell descriptions fit twelve
columns and seven rows, that every number matches the table it came from in
every flag state, and that every byte drawn is a glyph the menu font actually
holds.  That last one exists because `LoadMenuCHR` loads tiles `$80-$FF` and
nothing else, so FFR's `"+"` at `$7B` came out as kana -- a string of the
right length and the right shape.  `src/fftext.inc` rejects an unmappable
character at assembly time, and `mkrom.py` draws the missing plus sign into an
unused kana at `$E6`; it and `$EC` are the only two codes in `$80-$FF` that no
text region in the game references.

### Budgets, and what is nearly out

    BANK_FIXED   250 free    the scarce one; stamped into every chunk.  7
                             declared, and 243 at the end: the randomizer's
                             hooks gave back 149 between them -- the
                             item-name lookups blursings replaced, then
                             GetBattleFormation (26) and EnterBattle's
                             formation copy (39) -- the None took 74 (its
                             class name, LeadClass, starting stats, the
                             battle CHR loader), @Begin's mute 9, and the
                             stack fix's JSL 4; SOFT in battle's loop in
                             DrawDrinkBox gave back 89; the map-edit hook
                             took 4; the teleport landing, now asked of
                             rando_teledest, gave back 16; the talk funnel,
                             its Guillotine moved to rando_talk, gave back 31;
                             LoadPrice, its table read moved to rando_price,
                             gave back 24, the chest's exit for a vehicle
                             took 3, and the reward NPCs' lines' hook 4;
                             the entrance and exit landings, asked of
                             rando_entrdest and rando_exitdest, and the
                             teleport's map, of rando_teledest, gave back 34;
                             @Begin's cold build, one JSL to the
                             randomizer's rando_coldbuild, gave back 3
    BANK_0B        0 free    ends in pinned .INCBIN graphics; nothing to take
    BANK_0C        4 free    declared unused at $BFFC; and 5 bytes of
                             padding inside routines the randomizer took
                             over, never executed in Enemy_DoAi (Asshat
                             Octopus's hook took 12 of 21, Boss tactics'
                             turn 4 of the 9 left; the 7 NOPs in the
                             enemy attack setup are its swing's hook now)
                             -- and 33 never executed where the DRINK
                             choice used to be
    BANK_0D      212 free
    BANK_0E       37 free    12 declared unused at $BFF4, after House MP took
                             four; 25 NOPs in the old LoadShopInventory.
                             Besides: 28 zero bytes after TitleScreen_Music,
                             reachable only by code before the pinned $8500
                             blob (the save view took two), and four NOPs
                             after the title's @OptionChosen
    BANK_OPT     223 free   once the descriptions moved out, the None, the
                             save view (259), the stack fix (45), Thief hit
                             and the starting items (207), SOFT in battle
                             (513), White Mage HARM (82), and Improved
                             Vanilla's four small rules (247), and the
                             Lefein map edits (288), and the Ordeals
                             pillars' row and hand-on (40), and the key
                             item rows (1071: 20 more rows of 32 bytes, their
                             readouts and field tables, the field code), and
                             Asshat Octopus (138: its row and opt_kraken),
                             and Map shuffle (87: its row, readouts and
                             scalar), and the Ruse Staff (78: its row,
                             opt_itemspell and opt_weapbyte's answer), and
                             Boss tactics (75: its row, readouts, scalar
                             tables, opt_isbossfar and opt_spellbytefar),
                             and the shoulders (68: opt_shoulders and the
                             split of opt_sideways), and the NUKE Stick
                             (63: its row and the two readers' second staff),
                             and the starting caster item (194: its row and
                             scalar, the pool's rule and walk), and Thief
                             lockpicking (176: its row, readouts and
                             scalar, opt_lockpick, Thief hit's mask), and
                             Item magic (59: its row, readouts and scalar;
                             opt_itemspell shrank, asking the readers) --
                             the next feature with much code goes to a
                             chunk of its own, as Boss tactics did
    BANK_OPTTEXT  3232 free  the settings screen's descriptions; Map
                             shuffle's took 376, the Ruse Staff's 115,
                             Boss tactics' three 432, the NUKE Stick's 115,
                             the starting caster item's 115, Thief
                             lockpicking's 115, Item magic's 115
                             (measured 2026-10-14 from
                             ld65's map: the 10788 here before dated from
                             10-09 and was not kept up as descriptions were
                             added)
    BANK_CREDITS 13065 free  the credits screen; mostly its text and tables
    BANK_RANDO   2949 free  the randomizer; the Ordeals pillars took 622,
                             the reward NPCs' table and routine 673, the
                             Early flags 58, placement's code 2791, the
                             rewards and their giving 1232, the reward
                             NPCs' lines 1094, the ship's dock 13, forward
                             placement 165, progression first 75, spread
                             placement 60; entrance shuffle 391 -- the
                             placement tables in RAM 79, New Game's
                             attempts and the PRNG lent 210, the landing
                             hooks and the ship's dock under it 102, the
                             Princess's warp 15, FFR's unsafe tables and
                             their choice 94; New Game building the
                             cache, and its mute, 7; a draw with nowhere
                             to go, and the counts reused, 33; the roll
                             screen's yields, stages and yelps 89, and
                             Continue's cold build under it 22; the Ruse
                             Staff's name 57, and the NUKE Stick's beside
                             it 32; the caster item's draw 43; Item
                             magic 416 -- its two pools 104, the deal,
                             gear_spellat and the dealt names
    BANK_LOGIC   6911 free  the vanilla world's logic for placement (3714),
                             each map's ship dock (71) and each place's
                             spread group (248), and entrance shuffle's
                             graph (5440), generated; data only
    BANK_WORLD  11914 free  entrance shuffle's code (4430): the wiring, the
                             seed's logic, roots, groups, the dock, and the
                             landing tables; the roll screen's yields 40
    BANK_ROLL    9233 free  New Game's roll screen (7151): its code, and
                             38 pictures' resolved frames, colours,
                             effects and voices, the scales and their
                             reach (from tools/genroll.py)
    BANK_TACTICS  7447 free  Boss tactics (8937): gathering, the deck, the threat, the
                             race, the dice's sums, the normal tail, the
                             choice, the arithmetic, and gentactics.py's
                             tables (199 + 3 x 129 words + 81 words)
    HALCODE     ~6200 free   not available; see below

**Measure with a listing that counts each line's bytes**, not the address the
last line starts at, and not trailing zeros.  All three disagree.  And a bank
whose source ends in a declared block of unused `$00`s has that space only in
the sense that a patch can take it: it is emitted, so the linker counts it as
used, and a hook that needs four bytes needs a second patch that shortens the
block by four.  `patches/bank_0E/opthousemp_room.patch` is what that looks
like.  Nothing is pinned past the last `.INCBIN` assertion in a bank, so the
tail may move.

**Nothing of the game's goes in `HALCODE`.**  It has the most room of any bank
and it is the one bank that must not be spent.  The HAL is what the SNES
pretends to be: everything in it is there because a NES register had to be
answered for.  Put a table of option descriptions in it and that stops being
true -- the bank no longer says what it is, and the next person cannot tell
hardware from content by looking.  Its free space is headroom for hardware
that is not emulated yet, and it stays that way even when another bank is
full.

**`BANK_OPT` is no longer the roomy one.**  It absorbed Shop Information's
renderer and its word and description tables.  When it runs out, claim a
second chunk: `EXTRA_CHUNKS` in `mkrom.py` plus a `MEM_`/segment pair in
`snes.cfg` is the whole change, and the ROM has 800KB unused.  That is the
answer, and it is the only one.

**Where the options chunk actually goes**, since it is mostly not code:

    optbank.asm   option block, presets, feature hooks    2498
    optmenu.asm   the settings screen                     7371
    optdata.asm   game tables evicted from full banks      487
    optshop.asm   Shop and Chest Information              3478
    free                                                  2550

(as it stood before the descriptions went to `CHUNK_OPTTEXT`), and inside the
settings screen, which was more than half of it:

    code -- the screen itself                       1337   18%
    row table -- 55 rows x 32 bytes, the labels     1760   24%
    checkbox tiles and the value readouts            225    3%
    description text                                3798   53%
    description pointers                             110    2%

The menu is 82% text.  A description used to be five fixed lines of 28
characters, space-padded, where most are two or three -- 2.8KB of spaces, and
the SCALE section would not fit until they went.  A record now begins with a
line count and holds only the lines it uses; `opt_menu_desc` blanks the rest of
the pane with `hal_ntfill`, which is cheaper than writing the spaces was.  The
count is the one thing in a record the assembler cannot check, and getting it
wrong is quiet -- the text is simply wrong, on that one row -- so
`check_tables.py` verifies every count against the lines below it on each
build.  A flag cost about 117 bytes all in.  That was what ran the chunk out,
and why the descriptions now have a chunk of their own.

**Measure these from the assembler listing, not by counting trailing zeros.**
A bank whose source ends in a declared block of unused `$00`s -- `$0E` ends in
sixteen of them -- reads as having that much headroom when it has none.  That
mistake cost a build that overflowed by eight bytes after it had been
"measured" as having eighteen spare.  `ca65 -l` and taking the highest address
emitted is the figure that is true.

**The fixed bank is the binding constraint**, and is now effectively full.
Put logic in the options chunk and reach it with `JSL ... + OPTFAR` (four
bytes) from the call site directly; fall back to a three-byte `JSR` into a
fixed-bank trampoline only when the site cannot afford four.

Bank `$0E` is nearly full too, but it is reachable: `OptCallFar` is a seven-
byte trampoline that calls *any* routine in that bank, because `JMP (abs)`
takes its pointer from bank `$00`, whose low pages mirror WRAM.  One
trampoline rather than a table of them is what made the menus fit.  Where a
hook needs room, look for calls to fold: each menu loop opened with
`ClearOAM`, a cursor draw and a frame, and replacing those three with the one
`JSL` that also reads Select paid for the trampoline twice over.

**A hook can pay for itself, and in the scarce banks usually does.**  Better
Thief and Ninja put three of them in: two replaced an `LDA abs,Y` / `STA abs,X`
pair, six bytes for four, and one replaced three `ASL abs`, nine for four.  The
fixed bank went from three bytes free to seven.  Bank `$0B` could not keep its
five -- see below -- but the padding it took instead paid for the hit-growth
hook next door, which is the same thing one step removed.

**Bank `$0C`'s tail can move, but bank `$0B`'s cannot**, and neither can any
blob `convert.py` pins.  The byte-neutrality rule exists because other banks
reach data through absolute addresses baked into `Constants.inc`; check
whether any actually point into the range being moved before assuming a patch
must be padded.  For bank `$0E` past its four pinned blobs, none do.

Zero page `$6E..$7B` -- the hole `snesmap.inc` documents -- is **full**: the
menu uses all fourteen bytes.  Anything further needs the option block's spare
page at `$6E0E-$6EFF`, which is fine for flags but cannot be used with
indirect addressing.  The two exceptions so far both need a direct-page
pointer and borrow `tmp`: `OPTWPTR` at `tmp+13`, live only while a description
string is being built, and `OPTCALLV` at `$0113` just above `tmp_hi`, which
rides the same assumption `tmp_hi` does about how far the stack descends.

### What is left, and what it costs

**All thirty-seven checkboxes and all five value rows are done.**  Every box
the menu draws is read by something.

Two pieces of FFR's `FixSpellBugs` are deliberately not ported, because the
menu never promised them: `TameExitAndWarpBoss`, which puts a B-to-abort
prompt on EXIT and WARP, and its "Attack rate down" battle message.  Both are
UX changes rather than spell fixes.  If they are wanted they are their own
flag, not this one.

Neither is blocked on space, which an earlier draft of this section claimed.
**Every FFR patch is an in-place overwrite** -- it never grows a bank, it
writes over working code and pads with `EA`.  So a conditional port costs a
`JSL` where code already sits, not new bytes: the LOCK fix landed
byte-neutral, eight bytes of `LDA` / `CMP` / `JMP` becoming `JSL` / `BNE` and
two NOPs, and bank `$0C` still has its four.  Read the FFR blob's length
before assuming a hook needs room.

**A runtime flag over a data byte is not a one-byte change**: the value has to
move to a load, and the load has to fit where the constant was.  That is the
cost that matters now, because the banks these flags touch are the full ones.
Spell Fixes writes to magic records in bank `$0C`, which has nothing left, so
its hooks have to pay for themselves at their own call sites -- as Weapon
Stats did, by dropping a buggy store and an `AND` that set a flag the previous
instruction had already set.

### Things learned the hard way

  - A patch that changes a bank's size moves every data blob after it.
  - `cur_bank` is where `CallMusicPlay` returns *to*; a routine in a new chunk
    must set it or lose the program bank.
  - Reading this bank's own tables needs `PHB / PHK / PLB`, because `JSL`
    leaves DBR pointing at the caller's chunk.
  - Stack pushes are register-width dependent: `pha` after `rep #$20` pushes
    two bytes.
  - Anonymous `:` labels retarget silently when an edit inserts another one.
  - A screen transition must wait for the pad to read zero.  The menu also does
    its own edge detection rather than trusting `joy_a` and `joy_ignore`, which
    the previous screen owns.  The game's own input handling is untouched, and
    must stay that way: the battle screen deliberately overlaps cursor movement
    with button presses, and players have that in their hands.
  - A test harness that caches a label file silently tests the previous build.
  - Prefer a bounded loop to a sentinel.  A table walked until `$FF` keeps
    reading into the code behind it if the terminator is ever dropped, and no
    test noticed; `CPX #end - start` cannot fail that way.
  - Where a call site cannot grow, let the helper do the stores.  Auto
    Retargeting's physical entry writes both defender variables itself, which
    is the only reason a four-byte `JSL` fits where six bytes of stores were.
  - Re-reading a variable is often cheaper than splitting a branch.  Run ->
    Wait tells its two failure exits apart by reading the formation's no-run
    bit a second time, because the path that sets it skips the roll entirely.
  - A mutation that no test notices is a test that is not testing.  Both
    `$FF`-sentinel bugs and the magic-menu party guard were found that way --
    change one constant, rebuild, and see whether anything fails.
  - **`SwapPRG` sets the data bank as well as the program bank**, because
    `hal_swapprg` ends in `PLB`.  Nothing in the 6502 source hints at it, and
    it bites in both directions.  Returning with the wrong DBR made the shop
    loop read its cursor table out of the options chunk and put the hand at
    (8,141); calling with the wrong DBR made the equip menu redraw its boxes
    from the same wrong chunk.  Anything that crosses chunks must say what the
    data bank is on the way out *and* on the way in.
  - **Do not read a byte of the option block that nothing has written.**  It
    is battery-backed, so an uninitialised value is not zero and not random
    either -- it is whatever the last build left, which makes the bug
    perfectly reproducible and perfectly confusing.  `OPTCTX` was only ever
    cleared on the way out of a menu, so a stale value sent every shop down
    the menu's full-screen redraw path.  A value that selects behaviour is a
    parameter: set it at every entry, before anything can return early.
  - An eight-bit index register reaches 256 bytes, and a long read does not
    help.  Tables past that size get split at a power of two -- the weapon
    table at 32 entries, the magic table likewise -- or walked with a
    direct-page pointer and `LDA [dp],Y`.
  - A macro that sets something up may need the register a caller wanted to
    pass a parameter in.  `CALL0E` used `A` for the address, so a routine
    taking a parameter in `A` got the address's high byte instead.
  - **A mid-routine `LEAVE16` lies to the assembler.**  It asserts `.a8`, and
    everything below it still runs in sixteen bits, so `cmp #8` assembled two
    bytes wide against a 16-bit accumulator and would have eaten the branch
    behind it.  `flush_nt` carries a note about this at `@byrows`; an early
    exit added later hit exactly the same trap, and the build was clean.
    Check the listing, not the build.
  - **Profile ranges must stay inside one bank.**  The instrumented emulator
    rejects an instruction with one pair of comparisons against the lowest and
    highest range address; ranges in two banks make that span cover every game
    bank and drop it to a few frames a second -- slow enough that scripted
    runs time out and end up on a different screen than the one being
    measured.
  - Build the control before blaming the change; see `test-the-control-first`.
    A sign-off covers what was actually exercised, not everything the commit
    touched.
  - **Mode 7 shrinks by skipping texels.**  It samples the nearest texel and
    nothing else, so wherever a line shows more than one texel per pixel,
    whole rows and columns of the plane are simply not drawn -- and the
    game's font has one-pixel strokes, so letters lose pieces as they recede.
    Magnifying the near edge (the crawl's zoom) moves the problem up the
    screen; the fade hides most of what is left.  A crawl font with strokes
    two texels wide would cure it.
  - **Enable HDMA inside a vblank.**  A channel switched on mid-picture runs
    from a table address it never loaded.  The credits screen turns channels
    5-7 on in the same vblank that first points them at their tables.
  - **Scripted input can be dropped wholesale** when another app has focus:
    every keypress of a run was lost and the intro played through untouched.
    If a run shows no response to any input at all, rerun it before
    suspecting the build.
  - **`f:label` in a chunk's own code gets bank 0.**  The segment is linked
    at `$8000` with no bank, so ca65 has none to give it, and a long read of
    the chunk's own table went to the HAL's bank instead.  Write
    `f:RANDOFAR + label`, the way `ROMSHOPS` adds `BANK0EFAR`.  The chest
    shuffle's unused-chest list was read that way, and the tests caught the
    unused chests moving.
  - **Native code leaves the high byte of A changed.**  The game's 8-bit code
    never sees it, but a routine that promises "A as it came" has to put it
    back, and the Weapon Stats test checks all sixteen bits.  It caught
    blursings' `opt_weapbyte` returning with a record offset's high byte.
  - **The harness's `call()` leaks a stack byte per RTS-ending routine.**
    Harmless in emulation mode, which wraps within page 1.  Four hundred calls
    in, native code walked off the bottom.  `call()` now restores S.
  - **A wiring check proves only that the call is where I put it.**  The
    magic shuffle first hooked `DrawItemBox`, on the belief that it drew the
    magic shop's list, and a test confirmed the `JSL` was there.  Magic shops
    build their own string in `ShopSelectBuyMagic`, and the first shop the
    user opened showed vanilla names.  The test that catches it runs the real
    routine, stops it at its input wait with a step limit, and reads the names
    off `NESNT`.  Find a hook site by tracing from the screen's entry routine,
    not by grepping for the table it reads.
  - **Test a generator over junk scratch.**  The harness starts with WRAM
    zeroed, and so does `hal_reset`, so a missing clear of scratch is
    invisible until something else writes there.  `test_rando_cache` fills
    the scratch with `$FF` before a build and checks the world comes out the
    same.  Without the counters' clear, that build runs away.
  - **A mutation can be a no-op, and then it proves nothing.**  `CPX #0` in
    place of `CPX #OPT_NG_SIZE` still runs a one-byte loop once; a `LDA` slipped
    in before a `PLA` is undone by it.  Both "survived", and the tests were
    fine.  Before crediting a miss to the tests, check that the mutant behaves
    differently at all.
  - **If `cpu65816.py` lacks an instruction, add it.**  The harness exists to
    test the code the cartridge should have, not to steer what gets written.
  - **A mutation test must restore from a unique temp file.**  Backing a
    source file up to a fixed name and restoring it afterwards silently
    reverted a day's work here: the backup step was chained with `&&` and so
    was skipped when a build failed, while the restore ran unconditionally
    and copied back a two-day-old file.  `mktemp`, and let the restore fail
    loudly rather than succeed with the wrong contents.  `tools/mutate.py`
    sidesteps it: it mutates only copies, and the tree is never written.
  - **A name is as wide as its widest use, not its comment.**  `OPTSCRATCH`
    was declared "a byte the option code may use freely", and
    `opt_scalereward` used it and the three bytes after it as an
    accumulator.  The next byte was later given to `OPTD_ELEMDMG`, a derived
    byte that has to persist -- so off 100% Gold/XP every battle's end
    overwrote the weakness bonus with a byte of the reward, until the options
    were next committed.  The accumulator is `OPTREWARD` now, four bytes of
    its own.  A grep of every `NAME+k` in the option code against each name's
    declared size found no other overreach; `test_goldxp` now fills the
    option page with a pattern and fails if the reward scaler writes outside
    its four bytes, at every step.  Give a multi-byte scratch its own name
    and size, and never put a byte that must survive beside one that is
    merely free.
