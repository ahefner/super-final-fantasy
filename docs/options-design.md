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
    `OPTMENU_VIEW` (`OPTWORK+$31`) and opens the window on the blank above
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

**Every description is readable text** (`FFPAD {"..."}, 28` lines in
`opttext.asm`).  The 28 oldest records were raw character bytes until
2026-10-27 (0b0913b), converted for the text audit with the ROM byte for
byte the same.

**The text audit** (user, 2026-10-27: batches, every change the user's to
accept or deny; plain direct words, American spelling as the game's ARMOR
menu has it).  Batch 1, SCALE and QUALITY OF LIFE: Boss stats says what it
scales rather than "The same" (the pane shows one description at a time);
Enemy stats "defense", Chest information "armor"; Encounter rate names the
land, the sea and dungeons; Elemental bonus "The original game adds 4.
Requires Weapon Stats enabled." (the user's ending); Faster walking's
grammar; Run becomes Wait says the character waits; Lefein SuperStore "sells
every spell except those from nearby Gaia" (the user's).  The other rows of
those sections were left as they were.  Batch 2, BUGFIXES and VARIATIONS:
House MP and HP fix without its "which the save then records"; Weapon stats
"Fixes weapon critical hit rates, elements, and creature bonuses to work as
advertised." (the user's); Thief and Ninja hit% in plain sentences; Thief
lockpicking "...can open locked doors without the KEY." (the user's, its
Off sentence dropped); Double weapon crit "Requires Weapon Stats enabled.";
White Mage HARM "HARM cast by a White Mage or Wizard hurts all monster
types, not just undead." (the user's); TRANCE status element in two
sentences; RUSE Staff and NUKE Stick worded alike; Short ToFR without
"ToFR" (the locked door dropped to fit); Better Thief and Ninja says what
"it" and "both" are.  One space after a full stop throughout, every record
re-wrapped with its words unchanged.  The row "Improve FIRE, LIT, ICE" is
"Better FIRE, LIT, ICE" (the presets' files name it so).  Boss tactics'
descriptions left as they are.  Batch 3, TREASURES
and RANDOMIZATION: Explorer Pack without "Most of FFR's presets"; Shops'
Shuffle "...including the Caravan's BOTTLE." (the user's, "The Caravan stays
open" dropped); Chests' Shuffle "The 234 treasure chests trade contents. Loose items may
enter the mix." and Off "Chests retain their vanilla treasure, except when
displaced by a shuffled key item." (both the user's);
Max gear blessing "adds 3 hit%, 2 damage and 3 crit"; Min gear curse "The
lowest penalty gear may roll..." (the user's); Formation zones' Random
"...the game never used. Coneria is unmodified." (the user's); Surprise
rates' Shuffle without "and you it"; Status attacks' Shuffle "Enemies trade
touch effects, bosses included. Pirates are unmodified." (the user's; the
pirates' sentence, and Enemy scripts' "The pirates keep theirs.", dropped
2026-10-30 for the Pirates row, user: "remove mention of the pirates"); Enemy
skills' Enemies rearranged, and its Bosses "Spells and skills are shuffled
among the fiends, WarMECH, and CHAOS. No consecutive NUKE or NUCLEAR." (the
user's).  Batch 4, KEY ITEMS: Key items' Vanilla names what
still applies under it (Goal, Free, Remove, the Early rows); Standard
without "as in FFR's default", Wide without "--" and "Free Enterprise's";
Map shuffle's Entrances and Floors without "FFR's."; SHIP's Remove "The SHIP
is removed from the game." (the user's); Other items lists the nine inline
(the font has no colon or brackets); the gear rows "Incentive adds this item
to the pool of key items. Treasure places it among the 234 loot chests." and
Xcalber "Crafted from ADAMANT." before the same (the user's).  The item
rows' shared Incentive and Loose texts stay as they were.  The audit closed
there (user, 2026-10-27: those two dropped from the list, to come back to
if they bother the user).  Batch 5, the
New Game list: Custom Game "Starts from your current settings. Change them
on the screens that follow."; the presets' descriptions (`presets/*.toml`)
without "FFR's ..." and in full sentences -- Improved Vanilla, Beginner, the
two shuffles, Chaos Rush (its gear incentives and short Temple dropped to
fit), Free Enterprise (its short Temple dropped) and Oops All Loose (without
"placed forward and spread out").  Vanilla, Classic and Floaterless as they
were.  Batch 6, the map edit screen's descriptions (`tools/genows.py`):
Early Open "...to Crescent Lake."; Bahamut Dock "A dock on Bahamut's Island,
no airship required." (the user's); Lefein River "...without the AIRSHIP.";
Lefein Bridge "...and Coneria's bridge becomes land."; Melmond River "A
river connects Melmond to the Dwarf Cave." (the user's); Airship Trail
"...without the CANOE."; the two warnings with one space after the full
stop.  "Short ToFR" keeps its label (user: "FFR heads know").  Batch 7, the
reward NPCs' lines (`dlgtext.inc`, FFR's): Bikke "Arrrr, you got me. / Take
this and go."; Astos "HA, HA, HA! I am Astos! / I possess the [item] / Soon
I'll have the CROWN!" -- both the user's, Astos's also the fix for his
padded name before a full stop (`randomization-notes.md` §3).  The rest as
FFR wrote them.  Played 2026-10-28 in part (user: "partially verified the
text audit"); Bikke's and Astos's lines seen.  The game's lines that say
where a key item is give way to neutral ones under Key items Standard or
Wide (user, 2026-10-28; played 2026-10-28 in Improved Vanilla and under
Entrances, "Seems to work"): fourteen, each approved by the user, listed in
`randomization-notes.md` §3.  Under Map shuffle, eight more that say where a
dungeon is, and under Floors two that say the way through one (2026-10-28,
the user's wording or approved; played 2026-10-29, user: "Verified").
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

### New Game's presets (`presets/*.toml`)

**Built 2026-10-21, the first step of the New Game flow (`menus.txt` in the
project directory; `randomization-notes.md` 12); built, not yet played.**  The list's entries, in
filename order: Vanilla, Improved Vanilla, Beginner, Classic, Entrance
Shuffle, Entrance and Floor Shuffle, Chaos Rush, Free Enterprise, and since
2026-10-24 Oops All Loose and Floaterless (built, not yet played; after the
rest, so a saved preset's number keeps its meaning) -- their
settings from `ffr-presets.md` and FFR's own preset files, each file saying
where.  The user's requirement: "in a subdirectory under snes/, in some
easily-edited format. Flags set there should default against the Improved
Vanilla preset if left unset."  So each is a TOML file whose keys are the
settings screen's labels and whose values are its readouts, as the screen
shows them ("Gold and XP" = "250%", "Speed hacks" = true;
`presets/README.md`).  Improved Vanilla is the base and sets every setting,
the build stopping if it misses one, so a new row gets its default there;
the rest set only what differs, `inherit` naming another preset to start
from (Classic, the two shuffles, Chaos Rush, Free Enterprise, Oops All
Loose and Floaterless start from Beginner; Entrance and Floor Shuffle from
Entrance Shuffle).  `title`
names the title screen's preset an entry is (Vanilla, Improved), so the
title's options row reads that name after choosing it; any other reads
Custom.  `[map_edits]` (user, 2026-10-24: "Presets should be able to toggle
map edits individually") is the set of edits the map edit screen starts
from for the preset, by the screen's own labels, true or false, a preset's
table over its parent's.  genpresets.py reads the labels from the screen's
table (`lut_OwsName`; label i is bit i), makes each preset one word of
`RANDO_OWEDITS` bits (`lut_NgpEdits`), and `ng_presetedits` puts it there
as the flow brings the screen up for a preset.  Custom Game starts from
the saved game's edits, or none.  The build refuses a label the screen
lacks (naming the nearest), a value not true or false, and an edit on a preset that skips the
screens.  So the file and the cart cannot drift: `test_ngpresets` names
each preset's word in the ROM through the ROM's own label and bit tables
and compares it with the file's table, resolved without genpresets;
`test_ngflow` has the screen start from Floaterless's seven and from a word
with a bit past the first eight.  `skip_to_party = true` sends a preset straight to party creation,
past every screen of New Game's flow (`lut_NgpFlow`): Vanilla's alone
(user, 2026-10-22: Improved Vanilla goes through them, being "the baseline
preset one might customize"; before, every preset that randomized nothing
skipped them).  The build refuses it on a preset that randomizes anything,
whose world only the map edit screen checks can be won.  The title's own three presets are untouched (user: no change to
the main menu).

`tools/presetdefs.py` reads every row's label, kind, bit or scalar, and
every value row's readouts, from `optmenu.asm` as the assembler lays them
out; `tools/genpresets.py` checks each file against them -- an unknown
setting with the near ones named, a value the row lacks with its values,
text the font cannot draw, a description past five lines of 28 -- and
writes `gen/presets.inc`: names, descriptions, and each preset's every
setting as (row, value) pairs.  `ngp_apply` (`newgame.asm`, a chunk of its
own, `CHUNK_NEWGAME = $1A`) clears the flag word and the new-game bytes and
writes each pair through the settings screen's own tables (`lut_ValOff`,
`lut_ValBit`, `lut_ValMask`), so the presets hold no copy of the block's
layout; the respond rate stays the player's; then `opt_commit`.
`test_ngpresets`: the parse against the ROM's tables, each preset applied
over decoys and read back, sealed, the respond rate kept; Vanilla and
Improved Vanilla byte for byte the title's; inheritance through two
levels; the generator's refusals.  Eight mutations, all caught.

### New Game's list

**Built 2026-10-21, not yet played.**  New Game on the title opens a list
(`opt_newgamelist`): Custom Game, then the presets by name, the pane under
it describing each -- Custom Game "Starts from your current settings.
Change them on the screens that follow." (the text audit, 2026-10-27).
A or START picks; B goes back to the title, which is rebuilt as after the
settings screen.  A preset is written over the options as it is picked
(`ngp_apply`) and stays written; Custom Game writes nothing.  The title
screen itself is unchanged (user: "nothing here should require modifying
it").

### New Game's screens

**Built 2026-10-21, not yet played.**  `ng_flow` (`newgame.asm`), from the
title's New Game, runs the screens in turn (`menus.txt`;
`randomization-notes.md` 12): the list; then, for Custom Game or a preset
that randomizes anything, the **randomization screen** -- the TREASURES,
RANDOMIZATION and KEY ITEMS sections, opening on Starting items -- the
**map edit screen** (below; the overworld select before it is skipped for
now, the vanilla map taken), the **options**, the rest of the settings, and
the **seed** (below), when anything is randomized, and after the roll
screen the **Seed Summary** under Key items Standard or Wide (below).  START goes on, B back
to the screen before; B on the list goes back to the title.  Vanilla goes
straight on to party creation, its file saying `skip_to_party`
(genpresets' `lut_NgpFlow`); every other preset goes through the screens,
Improved Vanilla included (user, 2026-10-22).  **Party
creation** is the flow's last screen (below), its B on the first
character back to the screen before; the world is built after it, the roll
screen up meanwhile, and the game begins.  Both settings screens are the
engine's windows: the options everything above TREASURES
(`ROW_TREASURES`), the randomization screen the blank row above TREASURES
to the list's rows -- the heading a row down, clear of a CRT's overscan, as
the options' SCALE is (user, 2026-10-24: the top of it was cut off) --
and the engine answers `NGNAV_FORWARD` for START and `NGNAV_BACK` for B.
**The title's options row opens the options too**, so it no longer shows
the three sections that moved -- the main menu's "Options select" in
`menus.txt`, B and START both back to the title (user, 2026-10-21) -- and
they are reached only through New Game.  `test_ngflow` answers the screens
as a player would and checks the order they come in, the answer, and the
options the presets leave -- B screen by screen, a preset backed out of
staying applied -- then runs the randomization screen a frame at a time.
Seven mutations, all caught.

**The map edit screen in the flow** (built 2026-10-21, not yet played).
Every New Game through the randomization screen comes to it, after that
screen, so that what it ticks is checked against settings already chosen:
everything that can make a world unwinnable -- Key items, the removals and
Free rows, the Early flags -- is on the randomization screen, none on the
options after it.  The screen took the place of a Map edits row, Off /
Open / All, which is gone (below).  The screen is `ows_choose` with `OWS_CANBACK`: B leaves it too, with the
select's chirp and the edits as ticked, answering `NGNAV_BACK`; START is
refused on unwinnable edits as ever.  It starts, for Custom Game, from the
saved game's edits when Continue would load that save, else none -- on a
blank battery, then, Custom Game is Improved Vanilla byte for byte (the
option block `opt_init` writes) with no edit ticked -- and for a preset
from its `[map_edits]` (`OWS_KEEP`, `RANDO_OWEDITS` as given); come back to from the options, from what was
ticked last, B having kept it.  What it leaves goes to `NGF_OWEDITS`
(`MENURAM`, which the build's refill of the save block's page leaves
alone), and the build takes those edits as they are (`rando_build`, since
2026-10-27 before party creation: below).  Vanilla
takes its own, none, without a screen.  Before the screen comes up,
`ng_settings` copies the options' new-game bytes into the save block,
where its check reads the settings.

**The Map edits row, removed** (user, 2026-10-24: "No value in it ...
Clean it up").  A stopgap to test the edits before the screen existed
(below), hidden once the screen replaced it, and since presets carried
their own `[map_edits]` nothing but Custom Game's fallback, which the base
preset set Off.  Gone with it: the row (`lut_OptRowHidden`, `ROW_HIDDEN`
-- the randomization screen and the save view now end at `NGROW_HEAD`),
its scalar, readouts and descriptions, `lut_OwEditsMode`, and
`rando_newgame`'s old way without the flow, the row expanded and the
screen brought up from it -- or forced up (`OWS_FORCED`, the music-only
tick `OWS_TICKMUSIC`) when the settings could not be won without edits.
Every New Game comes through the flow; without it, which only the tests
start a game without, `rando_newgame` takes no edits and shows no screen.
Bits 4-5 of the Early byte are free, and an option block from before may
still hold the row there: every reader of the Early flags tests its own
bit, and `test_owedits` checks no field claims them.  The tests that came
to the screen through the row come to it as the flow does (`mapscreen_pressing`,
`mapscreen_up`: `ows_choose`, the settings copied first), or give
`rando_newgame` the flow's edits (`flow_edits`); the forced start's case is
now the screen's own first check finding the settings unwinnable, red,
START refused with the warning and the error sound.  `test_ngflow` also
holds a blank battery's Custom Game to Improved Vanilla byte for byte (the
block `opt_init` writes and the list's preset).  Nine mutations, all
caught (the save view's window one short hangs `test_saveview`, as
before).  Built, not yet played.
`test_ngflow` answers the map edit screen too: what each start gives it,
B from it back to the randomization screen and from the options back to
it, the ticks kept, and the settings in the save block when it comes up;
then drives the real screen, B leaving and `OWS_KEEP` starting from the
edits given, and `rando_newgame` after the flow taking its edits without
a screen.  `test_saveview`'s window ends at the New Game list's rows.  Ten
mutations, all caught.  `tools/mutate.py` now gives a test 900 seconds: a
mutation that showed the (since removed) hidden row hung `test_saveview`
for good.

**The seed screen** (`seedscreen.asm`, `seed_choose`; built 2026-10-21, not
yet played).  After the options, when anything on the randomization screen
is away from its first value (`opt_needseed`: genpresets' rule for a
preset's way past that screen, at run time; map edits alone randomize
nothing) -- so not for Vanilla or Improved
Vanilla, nor for Custom Game on options that randomize nothing.  The flow
latches a seed from the pool as it goes on to the screen (`ng_latch`; an
`FFSEED` build's seed instead), into `NGF_SEED`, and the screen shows it,
eight hex digits high nibble first as the save view shows a seed, beside a
grid of the sixteen digits.  As menus.txt has it: A on a digit types it,
the first blanking the seed shown -- the rest of the eight are blank
pieces until typed -- and the eighth hides the hand; B takes the last digit back, the
hand showing again; B on the seed as given, or with nothing typed, goes
back to the options.  START goes on with the seed as given, or with the one
typed once all eight are in, and before then plays the game's error sound;
with all eight in, A goes on as well.  A typed seed was kept as typed
(`NGF_TYPED`) for the way back from party creation, which showed it whole,
the hand hidden, B taking a digit back, until 2026-10-27; since then the
screen gets a fresh seed every time it comes up (below).  Without the
screen the flow latches all the same, so New Game's seed is always `NGF_SEED`, which the build takes as it takes the edits.

**Its art is the 15-puzzle minigame's** (user, 2026-10-22: "a more
artistic take ... base it on the artwork from the 15-puzzle game"; built,
not yet played).  The background is the bridge scene the minigame is
played over -- the logo, the cliff, the birds -- its story box taken out,
and one black box across the top in its place: columns 2-29, rows 2-11
(the user's "S2", of the mockups in the project directory's
`map-renders/seed-screen/`), inside the
cells a CRT shows and clear of the birds (user).  In it the sixteen
buttons are the minigame's pieces, 16x16, a cell apart across and touching
down; 1-9 its own, and 0 and A-F drawn in their style (5x7, the stems two
pixels wide, as its 6, 8 and 9 have them; its 10-15 are two digits).
"Seed Entry" and the read-out, two rows of four pieces -- untyped places
the blank piece -- are beside them.  The description box is gone.  The
hand stands two cells before its piece, in front, over the right half of
the piece to its left, as the name input's stands over the letter before
(user: of that, the hand behind the pieces with only its finger showing,
and wider gaps with "Seed" over "Entry", that one); and without its shadow
here (user: on black it is unseen, and over a white piece a dark smear):
`seed_hand` loads the hand's four tiles with the shadow's rows -- the
bottom four of the lower two -- cleared, and puts them back whole.

`tools/genseedart.py` makes it from the game's own art, as the
disassembly keeps it (`game/bin`: the bridge scene's CHR and nametable,
the minigame's pieces, the menu font) -- `gen/seedart.inc`: 96 tiles from
$80, over the menu font's (the pieces 0-F and the blank, four tiles each,
the box's border recoloured, a tile of backdrop, the letters of "Seed
Entry" recoloured), the whole nametable with its attributes, the box,
grid and heading already in it, the palette, and the layout as constants.
The pieces are background tiles, not sprites as in the minigame: 24
pieces would be 96 sprites of the 64 the HAL's NES sprite list holds.  The
box is in palette 0, which the bridge scene gives only to rows below the
picture: the pieces' black (the backdrop), red ($15, the minigame's),
grey and white; the border and letters recoloured onto those, the box's
inside the backdrop tile, so nothing in it needs another palette and only
the box's outer edges need lie on the 16-pixel attribute grid -- which the
generator asserts, with the CRT cells and the birds.  `seed_build`
loads it all through `hal_chrload`, the game's own bulk path -- the bridge
scene's tiles from bank $0B, the screen's over the font's, the nametable
-- a breath after each for the music; keeps `cur_pal` to put back and sets
the background's; `seed_drawread` draws the read-out, four runs of eight
tiles, as digits are typed.  Leaving, `seed_restore` loads the menu font
back from where `LoadMenuCHR` takes it, the hand whole and the palette,
for the options or party creation after.

It is handled as the game's name input is: the grid's hand wraps at each
edge, the move's chirp on a move, the select's on A and B.  It runs in the
engine's chunk on the engine's frame: `WaitForVBlank_L`, so the music and
the L + X / L + Y reset, the engine's release waits, and its pad bytes
(`OPTMENU_PREV`, `_EDGE`), whose definitions moved to `optmenu.inc` for
the two files to share.  The error sound is the map edit screen's way of
playing it, `PlaySFX_Error`'s writes on the screen's own frames while the
screen goes on (`seed_sfxerr`, `seed_music`), written out again because
the two screens are in different chunks and modes.  (The text grid it had
before the art drew odd digits in rows 1-3 for one seed in two,
`hal_ntblit` shifting a word of zero page on each blit -- fixed 2026-10-22;
"Things learned the hard way".)  Its scratch is `MENURAM`+$20 on
(`SEED_SEL`, `SEED_N`, `SEED_ERR`, `SEED_DIG`, and `SEED_PAL`, the palette
it found).

`test_seedscreen` runs it a frame at a time: the screen as built, checked
against the game's own art rather than the generator's word -- the grid's
pieces 0-F where the layout has them, the seed read out, the nametable
the bridge scene's but for the story box and the box, inside the CRT's
cells with the birds untouched, the bridge tiles and the screen's loaded,
the pieces 1-9 the minigame's own and 0, A-F sixteen different glyphs on
its back, the palette, the hand shadowless, and on leaving the font, the
hand and the palette as they were; the read-out over seeds with their top
bits set; then the hand's wrap and chirp, START and B on the seed given,
typing and taking back, START refused with the error sound's sixteen
frames and no music, B down to nothing and back, all eight hiding the hand
with the d-pad then idle, A and START going on, a typed seed and a latched
one coming back, five seeds typed reading back as typed; and
`opt_needseed` over every row set alone -- each of the randomization
screen's needing a seed, the options' not -- and every
preset as genpresets judges it.  `test_ngflow` the seed screen in the flow:
after the options for a preset that randomizes, not for Custom Game on the
defaults, B back to the options, a fresh seed latched for each visit and
the typed mark cleared, the one left or typed New Game's, Vanilla's
latched without it, and `rando_newgame` taking `NGF_SEED` after the flow
and the pool's without.  26 mutations, 25 caught; the one missed is
equivalent today, `opt_needseed`'s checkbox path, the randomization screen
having no checkbox rows -- kept for the first it gets, which the row by
row check will then hold.

**Party creation in the flow** (built 2026-10-21, not yet played).  The
game's party creation is the flow's last screen, after the seed -- so
that a seeded feature, such as class blursings, could show there what the
party is choosing between (user) -- and the world was built after it, as
menus.txt has it, until 2026-10-27 (built before it since: below).  Bank $0E's `NewGamePartyGeneration` is split
(`patches/bank_0E/optfreestuff.patch`): `NewGamePartyUI`, the game's
screens as they were, which the flow calls through `OptCallFar`
(`ng_party`); and what GameStart still calls, now only `opt_freestuff` --
the Treasures rows' gifts, and then the world, the roll screen up
meanwhile, until the world moved ahead of party creation -- and back.  B on the first character, which went round to it again, now
leaves with C set (`ngparty_back.patch`, a branch to the RTS between the
two), and the flow goes back a screen: the seed screen, with a fresh
seed since 2026-10-27 (below); the options, when nothing needed a seed;
or the list, for Vanilla.  A
party made leaves with C clear, which the last `@RecordClassAndName`
gives (X = $30, its two ASLs shifting out zeros).  The flow is marked as
run (`NGF_ACTIVE`) only once party creation goes on.  Coming back to
party creation starts it afresh, as the game always did.  The split cost
bank $0E one byte, of the two it had at its end.

  - The title's music plays on from the title through every screen to the
    end of party creation, whose frames drive it as they always did; the
    roll screen came after, and ended with no track (`roll_end` given 0,
    not the title's $41 again), `PrepOverworld` starting the overworld's,
    as after a cold build.  Since the world is built before party creation
    the roll screen ends with the title's track again (below).
  - Party creation loads its own CHR and palettes; the flow's screens it
    goes back to need none of what differs.  Its background tiles and
    palettes are the title's own (`LoadMenuBGCHRAndPalettes`), its sprite
    tiles its classes' but with the hand among them, and the engine loads
    its two checkbox tiles itself.
  - Continue with no save the game would load was a New Game -- GameStart
    falls through to party creation -- which without the flow would start
    a party never made.  `opt_titlechoose` now asks `opt_savevalid`, the
    game's own tests, and sends that Continue through the flow.

`test_ngparty` runs `NewGamePartyUI` through the trampoline as the flow
does, a frame at a time: B on the first character answering C set; a party
named and confirmed answering C clear with each class and name recorded;
B on the second going back to the first, not out; and
`NewGamePartyGeneration` building the world and returning without party
creation.  `test_ngflow` answers party creation as the flow's last screen
on every path, and B from it back to the seed (the one typed, still
typed; the one latched, not latched again), the options or the list, the
flow not marked as run until it goes on.  `test_saveview`: Continue with
no save through the flow, on and backed out of; `test_roll`: no track
after the fanfare.  Nine mutations, eight caught; the one missed is
equivalent -- the flow marked as run before party creation rather than
after -- since every way back to the title passes the list, which clears
the mark.

**The world built before party creation** (user, 2026-10-27: "Everything
random should be locked down prior to party select"; built, not yet
played).  The flow builds the world (`ng_build`, `rando_build`) right
after the seed screen -- after the options when nothing is randomized,
after the list for Vanilla -- and party creation follows.  `rando_build`
refills the save's first page as GameStart leaves it
(`lut_InitUnsramFirstPage`, then the party on foot: the table's vehicle
byte is 0), so nothing of a build backed out of stays, such as a BRIDGE
at Lefein or a placement.  Then it writes the flow's seed (`NGF_SEED`) and
map edits (`NGF_OWEDITS`) into the save and runs `new_world`, which
`rando_newgame` shares: the options' new-game rows into the save, the
BRIDGE, the reward NPCs' state, the roll screen and placement.  Then the
cache and the fanfare, `roll_end` starting the title's music again for
party creation -- or, nothing randomized, no roll screen at all (below).  `rando_newgame`, from `opt_freestuff` after party
creation, now only clears `NGF_ACTIVE`; without the flow, which only the
tests start a game without, it builds as before.  The menus' music ticks
are off through the build (`MENU_TICKON`); the roll screen plays its own.

  - **No roll screen when nothing is randomized** (user, 2026-10-27:
    "Skip the roll screen if nothing is randomized"; played
    2026-10-28).  `ng_build` asks `opt_needseed`, the same test that decides
    whether the seed screen comes up, and passes the answer to
    `rando_build` in A.  With nothing randomized, `new_world` skips
    `DisableAPU` and `roll_begin`, and `rando_build` skips `roll_end`: the
    screen stays dark as the options left it, the build takes about three
    frames (some 33,000 instructions), the menus' music holds its note
    through them and plays on into party creation.  The held note is
    accepted (user: not worth more code).  Key items is Vanilla then, so
    the build cannot fail and `roll_fail`, which needs `roll_begin`'s font,
    is never reached.  Vanilla, Improved Vanilla and a blank Custom Game
    take this path; tests: test_ngflow (which builds roll), test_rando_build
    (the same world, the PPU, the APU shadow and the music untouched).
  - **A fresh seed every time** (user, 2026-10-27: "Seed select screen
    should choose a new seed on entry, whether you are progressing forward
    into it or backward from a failed roll or party select").  The flow
    latches a seed from the pool (`ng_latch`) each time it brings the seed
    screen up, so the screen always opens on the seed given, the hand
    shown, and `NGF_TYPED` is gone (its byte, `MENURAM+$19`, free).
    Nothing randomized, it latches one unseen on each pass from the options.
  - **Kept on the way back** (user: an unchanged seed keeps the world).
    `NGF_BUILT` marks that this pass of the flow built the world.
    `ng_build` keeps it, with no roll screen, when the cache's tag
    (`RW_TAGBLK`, a copy of the save block it was built from) holds the
    seed, the options' new-game rows and the map edits the flow has now;
    if any of them changed, it builds again.  With a fresh seed every
    time, only a seed typed again keeps it.  The list clears the mark, so
    a preset picked again builds afresh, and so does a failed build, which
    has refilled the save's first page.
  - **No world** (user: "display the message but make it say 'Failed to
    roll a world for this seed' ..., turn the background to red, and play
    the game over music").  Placement keeps its 32 attempts
    (`PLACE_ATTEMPTS`) and gets no fallback (user: "I don't think we need a
    fallback placement").  When Key items Standard or Wide places nothing,
    `rando_build` calls `roll_fail` instead of the cache and the fanfare.
    The roll stops; the backdrop turns the map edit screen's red
    (`NESCOL_06`) and the game over track ($52) starts.  Under the sprite,
    which keeps walking, "Failed to roll a world" / "for this seed" appear
    in white, in the menu font, on BG3 (rows 23-24, centred).  `roll_begin`
    loads BG3's characters in forced blank (`roll_textload`: a blank, then
    the menu font's 128 glyphs, NES 2bpp rearranged as SNES 2bpp) and
    clears its tilemap, so the failure itself writes only 35 tilemap
    entries and six colour bytes, at the top of a vblank.  A, B or START
    ends it; a button held as it comes up counts only once let go.  L+X
    and L+Y reset from it, as from the menus (`roll_reset`, the map edit
    screen's way: the PPU back to the HAL first).  It fades, the title's
    music starts again, and the seed screen comes back with a fresh seed.
    Nothing randomized cannot fail (nothing to
    place), but would go back to the options.
  - **No stray note under the fanfare or the game over music** (user,
    2026-10-28: "stray notes on the pulse channels when the defeat music
    starts"; played 2026-10-28: "Seems like it's fixed").  The music driver keeps each pulse's
    next pitch until it writes it, the high bit of `ch_freq+1` clear until
    then.  While a sound effect holds pulse 2 (`sq2_sfx`) it doesn't write,
    so the title's next pulse 2 note waits.  The seed screen's A plays the
    select sound and the roll cuts the title off (`DisableAPU`), often with
    a pitch waiting.  The fanfare and the game over track both open pulse 2
    with a rest, and a rest leaves a pulse's pitch alone, so the driver
    wrote the title's waiting pitch and it played through the rest, about
    80 frames under the game over music.  `roll_begin` marks pulse 2's
    pitch as written (`$80`); the new track's halt has left the channel at
    period 0, silent, until its first note.  Pulse 1 opens on a note in
    both tracks; the triangle's rest silences it (`$FF`).  The first fix
    (82589ee) silenced the roll's own voices instead.  The driver's halt
    already did that within a frame, so it was taken out.  Test:
    test_rando_build, pulse 2 frame by frame under both tracks after the
    title cut off that way, against a driver that never played; both
    mutations caught.
  - **The Seed Summary** (user, 2026-10-27, from "a 'Seed Summary' screen
    after the seed select which lists the incentive locations"; layout and
    names approved from a mock-up; "Excluding unreachable places and NPCs
    would be a nice touch"; played 2026-10-28).  `sumscreen.asm`, in
    the settings engine's chunk beside the seed screen, after the roll
    screen and before party creation, under Key items Standard or Wide
    (the flow asks `RW_PLACED`: with Key items Vanilla there is nothing to
    list, and party creation follows the roll screen as before).  Rows
    2-26 of the CRT's 30 x 26, text from column 2:
      - "SEED" and the save's seed, eight hex digits, centred on row 2;
      - Goal (`lut_ValGoal`'s readout), Map shuffle -- the mode the game
        has, `RW_ENTRANCES`, so Off when no wiring placed -- and Removed
        (None, SHIP, AIRSHIP, or both), rows 4-6;
      - the five numbers, rows 8-12, under the map edit screen's own
        labels (`lut_OwsIncLabel`, read from its chunk) and worked as its
        Select works them: the incentive items, the locations the setting
        names (21 or 25), those the party reaches holding every key item,
        the excess loose (past the locations) and the unreachable loose
        (past those reached, less the excess).  All five here, Map shuffle
        or not: the wiring is chosen;
      - from row 14, the incentive places the party can reach, by name:
        the thirteen people on the left (King, Princess, Bikke, Astos,
        Matoya, Elf Prince, Nerrick, Smith, Sarda, Canoe Sage, Fairy, Cube
        Robot, Lefein), the places on the right (Coneria Vault, Marsh Cave,
        Marsh Vault, Earth Cave, Volcano, Ice Cave, Ordeals, Sea Shrine,
        Sky Palace, Titan's Trove, Cardia, Caravan -- Standard without
        Marsh Vault, Volcano, Titan's Trove and Cardia), each column packed
        from the top, those out of reach left out.
    The numbers and places come from placement (`pl_summary`, run as
    `pl_store` ends): the incentive items as the settings have them
    (`RP_INC0`), then `pl_reachspots` once more -- every key item held, the
    count placement trims incentives by -- into `RW_SUMINC`, `RW_SUMREACH`
    and `RW_SUMSPOTS`, a byte per pool place, 1 for an incentive spot
    reached.  They are cache bytes, built with the world in every build,
    so a kept world keeps them.  A or START goes on to party creation, B
    back to the seed screen (a fresh seed), each with the select chirp;
    party creation's B comes back to the summary, the world kept.  No
    hand.  The screen loads nothing: the roll writes only characters
    $00-$40 of the HAL's pattern table, and the menu font is $80-$FF; the
    HAL sends the menus' palette again as the roll hands the PPU back.
    Tests: test_sumscreen (the places against logicdata, every line
    against a model over made-up records -- each readout, out-of-range
    steps, every count, columns of every length -- the pad, and two real
    builds behind the roll screen against `randoref.seed_summary`, the font
    and colours as the menus had them), test_es_place (the cache bytes
    against the reference over Off, Entrances and Floors, map edits, and
    Floaterless with two edits, Gaia's Fairy and Lefein out of reach),
    test_ngflow (where it comes and goes).

`test_rando_build` (new): a build from a junk first page answers C clear,
with the same world and cache that `rando_newgame` builds from the same
seed and settings, the page as GameStart leaves it but for the world's own
bytes, and the title's music after the fanfare.  Then a world with the SHIP
removed and 0 orbs, whose seed 3 places nothing (the reference agrees): the
screen waits on the pad, the game over track asked for, the backdrop red,
BG3 on beside BG1, the two lines centred on rows 23-24 and nothing else on
the map (VRAM junked first), and the font as converted.  A held as it comes
up, Select and the d-pad don't end it; A pressed does, with C set, the fade,
the title's track and no cache.  B and START end it, Select doesn't, and a
throbbing roll screen's colour math is turned off.  Each frame runs the
reset check once, and L+X resets, the PPU given back first.  `test_ngflow` intercepts
the build (answered built, its tag made as `rando_ensure` makes it, or
failed) and checks: when the build comes on each path; the seed screen
again after a failure (the options when nothing is randomized); the world
kept back through the seed screen unchanged (a fresh seed since, below); built again
for another seed, option or map edit, after a failed build, and after a
fresh pick from the list; and once for real.  `flow_edits` now builds the
world as the flow does, and `test_owedits` expects the BRIDGE and the ship
where GameStart put them unless Bridge to Lefein moves the BRIDGE.
28 mutations, all caught (the throb left on only once the button checks
ran on a throbbing screen).

The fresh seed (2026-10-27): `test_ngflow` checks a fresh seed on every
visit to the seed screen -- after a failed roll, back from party creation,
a typed seed replaced -- and a world kept only for a seed typed again or
the same settings and edits; a pass with nothing randomized builds again
from a seed latched unseen.  The harness now stirs the pool at the options
as well as the seed screen, as the frames do: stirred only at the seed
screen, a pass with nothing randomized had looked as if it kept its seed.
`test_seedscreen`: the screen opens on the seed given, the hand shown,
whatever `NGF_TYPED`'s old byte holds.  Ten mutations, all caught, the
earlier keep-the-world ones among them.

**Placement out of the save** (user, 2026-10-27: "We should drop it from
the save.  We were running short of space for flag bits, but removing this
frees up plenty of space"; built, not yet played).  The save keeps the
settings, the seed and the map edits, and nothing drawn from them.
Placement's results -- the key items' places (`RW_PLACED`, `RW_PLACE`),
under entrance shuffle the attempt whose wiring placed (`RW_ESK`), a found
ship's dock (`RW_SHIPDOCK`), and the Map shuffle mode the game has
(`RW_ENTRANCES`: Off under Key items Vanilla or when no wiring places,
where the setting was overwritten before) -- are the cache's, at
`$7F9840`, between the gear bonuses and the formations.  `pl_place` runs
first in every cache build (`build`), so New Game's build places, and a
Continue's first build after power-on places the same way from the same
settings; the readers -- the chests' and NPCs' rewards, the caravan, a
found ship's dock, the Princess's warp, the teleport tables -- read the
cache.  A failed New Game build clears the cache's tag.

  - **The save, v3** (SAVEVER 3): `RANDO_ESK` and `RANDO_SHIPDOCK` gone
    from the block, `RANDO_OWEDITS` at `$1C`, the block `$1E` bytes; and
    `$6040-$609F`, where `RANDO_PLACE` was, free again (the dead copy of
    the class stats).  Older saves do not load.
  - **The cost** is a first Continue after power-on: it now places, with
    the roll screen up, as New Game does for the same seed -- 0.6 million
    instructions for Beginner, 1.3 million with Floors, 8.5 million for the
    slowest seed the tests keep (seven wirings); the rest of the cache is
    about 0.1 million.  A soft reset keeps the cache and still only
    compares the tag.
  - **A change to placement's code or logic now moves the key items of a
    game in progress**, as a change to the shops' or chests' deals always
    did: nothing of the world is kept but its inputs.
  - `tools/randoref.py SAVE --map` works the wiring out from the save's
    settings too (`new_world`).

The tests read placement from the cache.  Where one planted a placement in
the save and then built the cache, it now gives the settings and holds the
build's own placement to randoref's (`test_rando_rewards`,
`test_rando_remove`, `test_es_tables` -- which now checks seed 18's second
wiring, the attempt placement takes, and the hooks on a cold cache);
`test_es_place` checks the save untouched by placement, and in the forced
fallback the mode the game has Off while the setting stays, the teleport
tables then vanilla, and with map edits the vanilla wiring's placement;
`test_rando_shipdock` and `test_rando_princess` the mode the game has, not
the setting; `test_rando_build` the save's first page as GameStart leaves
it but for the settings.  Eleven mutations, all caught.

It is the settings screen's engine, held to a **window** of the row table:
`OPTMENU_BEGIN` and `OPTMENU_END` (`MENURAM`), the first row a screen shows
and one past its last, where every bound was `OPTROW_COUNT` or 0 -- moving,
seeking, scrolling, paging, a section's toggle, the drawing.  The options'
window ends at TREASURES; the randomization screen's and the save view's
after the key items, where the list's own rows begin (`NGROW_HEAD`).  The list is a window with `OPTMENU_PICK` set: only its **pick rows**
(`OPTROW_PICK`, kind 5; byte 1 the preset, `NGPICK_CUSTOM` for Custom Game)
can hold the cursor, A and START answer with the row's byte, B with
`NGPICK_BACK`, and left and right do nothing.  A pick row draws its name
across the row's whole 29 columns from the box's, a cell in, and the hand
a cell in with it (`PICK_HAND_DX`), just before the name as in the game's
own menus; names are 28 long at most.  The list had a NEW GAME heading
above it until the user had it taken out and the names and hand moved a
cell right (2026-10-22; built, not yet played) -- the row is a blank now,
so the list has not moved down.  The two blanks and Custom Game are in
`optmenu.asm`; the presets' rows and descriptions are
generated (`gen/presetrows.inc`, `gen/presetdesc.inc`), so the list is
whatever `presets/` holds.

`test_ngscreen`, a frame at a time: the rows as drawn and each preset's
description, the cursor kept to the choices and the window, what A, START
and B answer; the settings screen down to its end and paged past it, still
on its last row; a window cut short drawing nothing past its end (the
options' will, above the randomization rows).  `test_saveview`'s title
cases: New Game opens the list, Custom Game leaves the options as they
were, a preset is applied as `ngp_apply` writes it, B rebuilds the title.
Eight mutations, all caught.


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

### Menu cursors move on a new press -- not a flag

**Decision (user, 2026-10-24): unconditional, every menu cursor in the game
that moves on both axes.  Played 2026-10-24 on a SNES, in various menus.**  The report: in the Magic or Status menu's 2x2
of characters, a quick Down then Right landed somewhere unexpected -- a bug of the original, and
FFR's.  Every one of the game's menu cursors moved on *any change* of the
directions held and took the whole set held as the press: roll from Down
onto Right and Down+Right read as Down again (the 2x2 tests "up or down in
it?" first), the cursor going back up, and letting go of Down read as Right
-- top right, not bottom right.  A list that moves on one axis only would
need two opposite directions held at once, which a d-pad cannot do; the
first cut patched the four lists too, on a claim the user tested in a shop
and found did not hold, and they went back as they were.

Now a direction counts only on the frame it is newly pressed.  The seven
two-axis tests -- party creation's class, name entry, the title (its rows
and the respond rate), the item menu, the Magic/Status target, the magic
menu and the equip menu -- are each `LDA #$0F / JSL opt_dpadnew / BEQ` and
six NOPs in the fourteen bytes the old test took
(`patches/bank_0E/dpadnew_*.patch`, generated from the source, so each
matches its routine exactly); `opt_dpadnew` (`optbank.asm`) answers a
direction held now and not last time, keeping `joy_prevdir` as the game
kept it.  Each routine reads a single direction right, so a single press
moves as ever -- and two at once each wrongly in its own way: name entry took
anything with Up or Down in it but Up alone for Down, so Up+Right moved the
cursor *down* (the user's further find, on party creation's naming screen,
2026-10-24), and the item menu took Down+Right for Up.  So the helper hands
over one direction a frame, the lowest bit, leaving any other pressed in the
same frame out of `joy_prevdir` to come the next: Down and Right together
are right, then down, the diagonal.  The settings engine, the seed screen
and the map edit screen already counted presses so.  `test_dpadnew`: the
helper over every mask, pad and last pad; the 2x2 rolled both ways,
pressed together, held, and round the square; name entry with Up and Right
together, frame by frame through party creation (right, then up -- the
last build moved it down); no two-axis test left in the bank, seven calls.
Mutations caught: the 2x2's patch undone (it reproduces the report), and
the helper answering the held or not keeping them.

### None in the party -- not a flag

**Decision (user, 2026-10-09): unconditional, with no menu row.**  On the
party creation screen, slots 2-4 cycle Fighter to Black Mage, then None, then
round again; slot 1 never offers it.  (Since the Party row, 2026-11-02,
that is Free's; the cycle follows the row's mode, `lut_PartySlots`.)  It is for solo and small-party runs,
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

### Scale (11)

Value rows, and the first section in the list: Gold + XP Scaling, Encounter
Rate, Enemy stats min and max, Enemy HP min and max, Boss stats min and
max, Boss HP min and max, Elemental and Type Bonus.

**The scaling's ranges (2026-10-31; the menu played 2026-11-02, the battles not yet).**  FFR's
EnemyScaleStats, EnemyScaleHp, BossScaleStats and BossScaleHp are each a
low and a high percentage, and so are the cart's four now: a row for the
minimum and a maximum row under it, labelled min and max (user:
'"up to" (or min/max) is more clear'; drafted as "up to", renamed min
and max on the user's word, 2026-11-01), every row an ordinary dial of
`lut_ValStat`'s 25% steps.  A max row reads only "max", under its min's
"min", and the four pairs' min and max share one column (user, 2026-11-02:
"removing 'Boss HP' on the max line ... keeping min and max aligned"):

```
Enemy stats min         75%
            max        150%
Enemy HP    min         75%
            max        150%
```

`presetdefs` and the presets still name a max row for its min, "Enemy HP
max", so the presets' files read as before.  HP has
its own rows, with no "Stats" value to follow the stats range (user: it
"just makes the min/max UI logic that much more complex"): FFR gives HP its
own roll either way, so HP rows set to the stats rows' numbers are FFR's
default, SeparateHP off.  With the max at its min a range is the single
value the dial was before.  The rows' bytes are the block's six after the
starting items (`OPT_ENEMYTO` .. `OPT_BOSSHPTO`), `OPT_FORMAT` 10.  A max
below its min counts as the min where the scaling reads it
(`opt_statrange`).  **How the two rows hold each other** (2026-11-01,
built for the user to judge in play: "I can judge the min/max adjustment
behavior once I can test it"; tested, no change asked, 2026-11-02: "I've
tested the menu, not the gameplay").  The max is stored, not an excess over the
min.  Left on a max stops at its min (`opt_range_floor`); right on a min
that passes its max pushes the max up with it, and repaints the max's row,
the one under it (`opt_range_push`).  Left on a min leaves its max where it
is.  The pairs are `lut_RangeMin` / `lut_RangeMax`, each max's row right
under its min's (`test_rangerows`).  The other way, an excess stored and
the max dragged along by every move of the min, was the alternative
offered.  A preset may not set a max below its min: `genpresets.resolve`
refuses it.  The labels and descriptions are the user's approved text
(2026-11-01: "Labels and descriptions look fine").  How the ranges scale:
"Enemy and Boss stat scaling".

**Decision: the dials come first, because of the paging.**  Left and right page
the list by half a screen everywhere except on a value row, where they belong
to the value -- so a cursor sitting among the dials cannot page at all.  At the
top of the list that costs nothing: the cursor starts on the heading, where
left and right still page, and the first page lands well below them.  Anywhere
else it would be a hole in the middle of the scrolling, in a position that
moved every time a flag was added above it.  With the eleven dials of the
scaling's ranges, the d-pad's first page from the heading lands on Boss HP
min, where a second press steps it; left as it is (user, 2026-11-01: "this
is why we use the l/r triggers for scrolling").

**The shoulders page anywhere** (user, 2026-10-15: "the idiomatic SNES way to
page through menus is using the left and right shoulder buttons").  L pages
up half a screen and R down, on any row -- the dials and the randomization
rows included, where left and right belong to the value -- once a press, not
repeating while held.  The NES pad has no shoulders, so the HAL reads them:
`aux_capture`, which already filed L, X and Y into `h_joyaux` for the reset
combos, files R too, in its own JOY1L bit ($10); the combos are tested
against L|X|Y and do not see it.  `opt_shoulders` takes the press edge
against `OPTMENU_SHPREV` and calls `opt_page`, which is the d-pad's paging
split out of `opt_sideways`.  The save view pages with them too (user,
2026-10-16, asking for both screens): `opt_page` seeks through
`opt_row_selectable` and scrolls through `opt_menu_scroll`, which already
keep the view to its value rows and its window, so the change is only the
guard that skipped the shoulders there.  The d-pad's left and right page
the view too (user, the same day: "the left/right d-pad cursoring should
still work in the saved game screen") -- they never had, since the view
began (fe1cbd9), because every row there is a value row and the settings
would step it; the view has no value to step, so `opt_sideways` pages
whenever the view is up.  The HAL files the shoulders in the frame wait, so
they are heard a frame after the d-pad.  `test_shoulders`; `test_saveview`
pages the view to its last row and back with them and with the d-pad, on
value rows only, the window as saved, nothing written, and a held shoulder
pages once.

**The hand moves with the page** (user, 2026-10-16: paging back to the top
of the save view, the cursor "initially lands on either SAVED GAME or SEED
... and then an instant later jumps down to the Trap Tile line").  A repaint
takes several frames (`opt_menu_breathe`), and the loop placed the hand only
after it, so the hand stood at its old screen row beside whatever the new
window drew there.  A scroll that keeps SEL - TOP hid it; a page, or the
view's top snapping back to the blank over its heading, did not.
`opt_menu_repaint` now places the hand and copies it to the HAL's shadow
before `opt_menu_drawall`, so the repaint's first vblank sends it.  And the
loop copies the hand before its frame wait rather than after: the NES order
(wait, then DMA inside vblank) left the copy after the flush here, so every
move of the cursor showed a frame late.  `test_saveview` records the hand at
every vblank while it pages down and back up, and holds each to the row the
page lands on.

**Decision: the elemental bonus is a dial, not a checkbox.**  FFR has both -- a
checkbox and a "Damage Bonus" slider under it, greyed out until the box is
ticked.  A list of rows cannot grey anything out, and a checkbox that has to be
on for a dial elsewhere to mean anything is the sort of interaction this menu
avoids.  One dial: +0 to +50 in twos, where +4 is what the cartridge does and
+0 is an off position no checkbox could reach.

### Variations (16)

Better Thief + Ninja, Thief and Ninja Hit%, Thief lockpicking, Double Weapon Crit Rate, Improved
CURE/HEAL, Improved FIRE/LIT/ICE, Cast Life in Battle, SOFT in Battle, White
Mage HARM, LOCK / LOK2 Mode, TRANCE Status Element, Asshat Octopus, Boss
tactics, RUSE Staff, NUKE Stick, Short ToFR.

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
says a vblank has begun it runs the battle's frame of music -- `music_track`'s follow-up, then
`CallMusicPlay` with `cur_bank` at this chunk so the driver swaps back here
-- and the HAL's frame of sound.  Nothing on screen moves while a boss
thinks, so nothing else of the frame is owed.  RDNMI's latch clears at the
vblank's end as well as when read, so a look between vblanks misses the
frame and the music can lose one now and then while a boss thinks.  The
HAL's `framedue` would tell every frame (the menus use it), but only by
the game's frame waits keeping count after their vblank, which the
dialogue box has no time for: tried on 2026-10-24, it slowed every open
box to half speed, and the boss went back to RDNMI.

**Where it is.**  Its own chunk, `CHUNK_TACTICS` (`$18`, `src/tactics.asm`),
native and sixteen bits wide, with its scratch at `TC_BASE` in bank `$7F`
-- between the roll screen's and placement's until 2026-10-30, since in the
lower half (the enemy records took its place, "Pirates") -- cleared each decision -- nothing
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
NOP.  The decision borrowed `$84` and the eight attacker bytes to ask
`opt_scaleatk` for the swing's scaled numbers until 2026-10-30; since then
the record it reads through `en_romptr` is the battle's copy, scaled at the
load, so its hit%, hits, crit% and max HP are the swing's own (the max HP
had been the ROM's, unscaled, beside a scaled HP).

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
reads "RUSE Staff", the spell's name in capitals as the game spells it;
played 2026-10-17) is FFR's Guaranteed Defense Item set to RUSE, one setting of
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
staff, as "bonk" is for a gauntlet; played 2026-10-28) is the same
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

**Short ToFR** (user, 2026-10-19: "port the short ToFR flag from FFR";
played and verified by the user the same day) is FFR's `ToFRMode.Short` with its default
`ShortToFRFiendsRefights.All` (`TempleOfFiends.cs`, `ShortenToFR`).  The
Black Orb sends the party to Chaos's floor rather than ToFR 1F, landing at
(15, 3) in a room FFR builds over the floor's top, eleven by ten from
(10, 0): all seven of the Temple's chests ($F8-$FE: the Masmune, 26000 and
45000 and 65000 gold, the Katana, ProRing and ProCape), the LUTE plate
across the room's one way out at (15, 5), then a locked door, then the four
fiends' refights on each path down, Tiamat to Lich left of the middle and
Lich to Tiamat right.  So Chaos still asks the four orbs, the LUTE and the
KEY -- what placement's logic already asks of it, so the logic is
unchanged -- and the chests the orbs alone; ToFR's chests were never
placement's, and the Chests shuffle deals them as ever, now all
reachable.  A Variation, retroactive like the Lefein map edits: every piece
is written as the game loads what it changes, where FFR writes the ROM,
and the party is never inside the Temple at Continue.  Off in every
preset, as in all of FFR's; Super's "everything on" stops short of the
game's shape (the user's to change).  FFR's other refight modes (Two
Paths, Lopsided, Progressive, Anything Goes, Rude, None, Random) and its
Mid ToFR are not ported.

The pieces, all in the randomizer's chunk (`rando.asm`, `tofr_*`): the room
over the map as it decompresses (`tofr_land`, from `rando_mapedits`); the
plate in object slot 3 after the map's objects load (`rando_tofrplate`,
through the game's own `LoadSingleMapObject`, so it shows exactly while the
LUTE has not been played and `HideMapObject` finds it); the plate's
graphic for slot 3 (`rando_objid`) -- `LoadMapObjCHR` reads the ROM's
object table, not the objects loaded, and slot 3 is empty there; the
Black Orb's landing in `rando_teledest`, in the room ($81), under entrance
shuffle too; and FFR's line for the LUTE, "The tune plays, opening the
pathway." (`rando_lute`, drawn from this chunk by the game's own
`DrawComplexString`; `UseItem_Lute`'s success path reshaped byte-neutral
in bank $0E, its pointless `ASL` gone).  And FFR's two cosmetic fixes: on
this floor the plate's bottom half draws in NPC palette 3's colour 1,
black, so that colour is gold (`rando_smpal`, FFR's `Put(0x02B2D, 27)`),
and Garland's outline, the same colour, is cleared in his standing
sprite's four tiles (`rando_objchrfix`, in `CHRSHADOW` before the flush;
FFR's `MakeGarlandsBorderTransparent`) -- on this floor alone, where FFR's
changes Garland's CHR everywhere, the opening's Garland included.  Bit 26,
the first of the Free items' old bits, spare since format 9, so the format
stays 9.  `test_shorttofr`: the room against FFR's source (when it is
beside the tree), the map, objects, CHR and palette as loaded, on and off
and on other maps, the Orb's landing, a walk of the floor as loaded (Chaos
with the LUTE and the KEY, not without; the seven chests with nothing),
and the LUTE's line beside the game's own.  Fifteen mutations, all caught.

**Thief lockpicking** (ported 2026-10-15, the batch's own pick; played
2026-10-17) is FFR's `Lockpicking` with its `LockpickingLevelRequirement`:
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

### FUN% (1)

**Built 2026-11-03, not yet played.**  The user's Fun% flags
(`fun-percent.txt`: "goofy flags that don't change anything about
gameplay"), a section of their own after VARIATIONS.  **Not part of the
seed settings** (user, 2026-11-03): they are the player's own, as the
respond rate is, and share its byte (`OPT_FUN` is `OPT_RESPOND`, bits 3-7
above the rate's 0-2), so no preset writes them.  `genpresets.py` leaves
the section out (`PLAYER_SECTIONS`; a preset naming one of its rows is
refused), `ngp_apply` never touches the byte, and the title's presets
(`opt_loadpreset`) reset the rate as before but keep these; a block that
fails its checks clears them.  The rate's two readers take its three bits
alone (`optrespond.patch`, `opt_titleleftright`).  The heading's
description is the user's file's wording.  Planned beside it (user,
2026-11-03): Palette swap -- one On/Off, fixed per seed, the overworld too;
enemies' colours as FFR's shuffle has them, backgrounds tinted ("toward
blue or brown") -- and the Exploding Dwarf: the Hurray dwarf only, "Oh
shit!" in place of his "Hurray!", back every visit.  Music Shuffle later.

**Stereo Sound** (user: "pan the two pulse channels hard left and right";
"pulse 2 from center for sound effects"): Off and On; the description is
the user's, "In Stereo For Her Pleasure".  The label keeps the user's
capitals.

  - **The SPC700** wrote a voice's volume to left and right alike.  A
    pulse's packet now carries a pan in byte 3, bits 6-5 (`genspc.py`'s
    `PAN_LEFT`, `PAN_RIGHT`), and the other side's volume goes to zero; the
    pan is cached beside the volume, so a change of pan alone is written.
    The triangle and noise stay in the middle.  The program is 1226 of its
    1280 bytes.
  - **The HAL** decides each pulse packet's pan (`apu_pan`) from a register
    the game sets -- `h_stereo`, and `h_panbusy`, the address of a byte that
    puts pulse 2 back in the middle while it is nonzero -- so the HAL knows
    nothing of the game's.  `opt_derive` sets them from the row, naming
    `sq2_sfx`, which every one of the game's sound effects sets while it has
    pulse 2 and the music driver counts down.  Every frame path -- the
    game's frame wait, the menus' audio frames, the roll screen's ticks --
    sends its packets through `hal_apu_frame`, so all of them pan.
  - A mono TV sums the two sides, so nothing is lost there, and each side
    carries less than it did, so nothing new can clip.
  - **Checked in ares's DSP log** (2026-11-03, the instrumented build's
    `ARES_DSP_LOG`): with the row On, voice 0's right volume and voice 1's
    left stay zero through the intro's and the title's music, and at each of
    five menu sounds pulse 2 is written to both sides at the sound's level,
    then back to the right.  `test_stereo` holds the game's side: the row,
    the presets and the block, `opt_derive`, and the packets' pan.

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
seeds so the player has some hope of progressing"; played 2026-10-17) is
FFR's `StartingEquipmentRandomCasterItem`, a row under Starting items, off
in every preset but Free Enterprise's.  It reads Off / AoE / Any (user,
2026-10-29: "Off / AoE / Any"; AoE played 2026-10-30): Any is the item
below, AoE FFR's `StartingEquipmentRandomAoe` (below), which Free
Enterprise turns on.  A new game gives the first character one weapon
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
mode is `OPT_STARTITEMS`'s top two bits (scalar 50: `STARTITEMS_CASTER`,
`CASTER_SHIFT`), the set in its low four (`STARTITEMS_SET`).  Any is bit 7
alone, as On was, so a block from before reads as it did and the format
stays 9; a step past Any, which the checksum should stop, gives nothing.
`test_casteritem` holds the pool to one transcribed
from FFR's rule and the ROM's tables, sweeps the rule over all 256 spell
bytes in the cache at both ends of both tables with every flag off and on,
deals 44 seeds under the staff flags and pools of one and two at the ends,
and runs New Game itself beside each starting set.  Thirty-two mutations,
one equivalent: splitting weapons from armour at 41 rather than 40 reads
weapon 40's byte 3, which in the cache is armour 0's.

**AoE** (user, 2026-10-29: "One thing we're missing is the random AoE
caster item ... not one which guarantees an offensive magic") deals the same
way from `GetRandomAoe`'s pool instead: an item whose spell targets every
enemy (`SpellTargeting.AllEnemies`, the byte whole) and is Damage, or
InflictStatus or PowerWord with exactly death.  On this cartridge that is
five -- the Mage Staff (FIR2), Thor's Hammer (LIT2), the Bane Sword (BANE),
the Black Shirt (ICE2) and the Zeus Gauntlets (LIT2) -- six with the NUKE
Stick.  FFR has the two as separate flags, both on giving two items; none
of its presets turns on both, so here they are one row's values, one item
(user: "one row, three options").  `opt_castergood` asks the mode itself.
`test_casteritem` holds AoE's pool too, sweeps both rules over every spell
byte as before and over made-up records (each target, routine and status in
turn, in a private ROM: the cartridge has no PowerWord on every enemy, and
no death alongside another status), deals under both, and runs New Game
under each mode, the step past Any among them.  Ten mutations of the AoE
code, all caught.

### New game (18)

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
played 2026-10-17).  Every item that casts a spell on the cartridge --
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
zero, so plain gear is always possible.  Left takes the curse further
down, to -5, and right back up to 0 -- the d-pad swapped on this row and the
Goal's, whose numbers fall as their steps rise (user, 2026-10-27: a player
"will expect it to default to 0 but press left rather than right to reduce
it"; `opt_valdir`; played 2026-10-28).

Formation rarity (Off, Shuffle, Tiered) and Formation zones (Off, Shaken,
Stirred, Random -- Light and Shuffle until the user renamed them, 2026-10-17,
the new names seen in the menu the same day, and still `ZONES_LIGHT` and
`ZONES_SHUFFLE` inside), two value rows: FFR's one Formation Shuffle Mode split into two
passes, the user's design.  Rarity moves formations between a zone's eight
slots, as FFR's Shuffle Rarity and Rarity Tiered do.  Zones moves them
between zones and keeps each one's rarity, which none of FFR's modes does:
FFR's Shuffle Across Zones moved single slots, rarity and all, until 2024 and
whole zones since, and its tooltip has described each in turn.  Shaken moves
only slots 0, 3, 5 and 6, so a zone keeps four of its eight fights.  Neither
moves WarMECH off Sky Palace 5F; rarity may change its slot there, as FFR's
does.  Random is FFR's Totally Random.  Rarity's Shuffle and zones' Stirred
together are "any encounter anywhere, regardless of zone or rarity".  `GetBattleFormation`
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
flag on.  The pirates' safety became the Pirates row's (below).

**Pirates** (user, 2026-10-30: "Three values - Off, Buffed, and Nasty";
built; Buffed and the world's enemy records played the same day, a full
Chaos Rush seed with Pirates Buffed, every battle loading through them;
Nasty played before the option page cleanup), a value row after Enemy skills.  Off: "Pirates
retain their vanilla stats."  Buffed, FFR's `SwolePirates`: "Pirates are
stronger and tougher."  Nasty, that and FFR's `AllowUnsafePirates`:
"Pirates may gain new abilities."  (All three the user's words.)  Free
Enterprise sets Nasty, as FFR's preset sets both flags; every other preset
Off.

  - **Buffed** is FFR's `EnableSwolePirates`, its values over the pirates'
    record: 800 XP and 800 gold (40 and 40), 160 HP (6), 2 hits (1), 32
    damage (8), 32 absorb (0), 35 hit% (2), 5 crit% (1), 24 evade (12), 30
    magic defense (15).  Boss stats and Gold and XP scale them after, as
    FFR's scaling comes after (FFR counts the pirates a boss, as this cart's
    `opt_isboss` does).
  - **Nasty** deals the pirates into Status attacks and Enemy scripts like
    any other enemy, as `AllowUnsafePirates` does in FFR's touch shuffle and
    script shuffle (user: both): `list_enemies` lists them.  With those rows
    off it is Buffed.
  - **The world's enemy records.**  The battle copies 8 of an enemy's 20
    record bytes into its RAM stats (`LoadEnemyStats`) and reads the other
    12 -- hits, hit%, crit%, max HP, magic defense, category, weakness,
    resistances -- from the ROM through `en_romptr` each time, a 16-bit
    pointer that reaches SRAM but not the cache.  So rather than hook each
    read (user: "it's better to minimize the number of code hooks ... And
    this is more flexible"), the cache holds all 128 records, `RW_ENEMIES`,
    built by `copy_enemies` with Buffed's values in the pirates'; and on
    each battle's load `rando_btlenemies` (from `opt_scaleenemies`, the
    existing hook) copies each kind's record, four kinds at most, into
    `OPTBTLENEMIES` (OPTDESC, which only the menus and the dialogue box
    build) and points every enemy's `en_romptr` at its kind's;
    `opt_scaleenemies` scales the copies and copies every enemy's RAM stats
    from its kind's as `LoadEnemyStats` does (since 2026-10-30, "Enemy and
    Boss stat scaling").  Whatever the world
    changes in a record from now on -- stronger Astos or Bahamut, alternate
    fiends, per-boss HP -- the battle sees with no new hook.  The touches
    and scripts keep their own tables (`RW_TOUCH`, `RW_ESCRIPT`).
  - **Where things went.**  The field is `RANDO_STATUS`'s bits 4-5
    (`PIRATES_FIELD`), Status attacks keeping bit 0 (`STATUS_FIELD`): the
    settings page had no byte left.  Zero in every save before, which reads
    Off, so the save format stays.  `RW_ENEMIES` took $7F:B380-$7F:BD7F,
    after the teleport tables; the roll screen's variables moved above it
    (`ROLLRAM`), and Boss tactics' scratch, `TC_BASE`, moved to $7F:4800,
    in bank $7F's lower half between the map edit screen's WRAM and the
    ending's buffer, neither up in a battle.
  - `test_pirates` holds the records, the touches and the scripts to
    `randoref` under each mode (FFR's record transcribed again), and a
    battle's load through `OptLoadEnemyStats` as bank $0C calls it: Buffed
    loads and scales exactly as the plain `LoadEnemyStats` does from a ROM
    holding FFR's pirate record; nine pirates share one record; Off, four
    kinds and a fifth, loads as the plain load does from the ROM, the fifth
    keeping the ROM's record, the empty slots untouched.
    `test_scaleenemies` now puts its cases' stats in the records.

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

**Party** (user, 2026-11-02, the design in `forced-party.txt` beside the
tree; built, and played the same day: "Tested"), after Ordeals pillars: sixteen values in
four bits -- FFR's whole forced-party screen "reduced to a single line"
(the user) of the common cases.  Free (the screen as it was), Balanced, 4
Forced, 3 Forced, 2 Forced, 1 Forced, 2 Nones, Solo, Th + Wm, Fi + 3, Th +
3, 4 WM, 4 BM, 4 RM, 4 Th, RWB: the user's names, and the readouts.

  - **The model is FFR's** (`Party.cs`, `UpdateCharacterFromOptions`): each
    slot a set of the classes it allows and whether it is forced.
    `lut_PartySlots` (`rando.asm`) is a row of four slot bytes per mode:
    bits 0-5 Fighter to Black Mage, bit 6 the None, bit 7 forced.  A forced
    slot is the seed's pick of what it allows, which the party creation
    screen will not change; the player still names it, and confirms a forced
    None with A, as any None (user: no skipping).  An unforced slot cycles
    through what it allows, from its default.  `randoref.PARTY_MODES` is the
    design written out apart from the ROM, and `test_forcedparty` holds the
    table to it.
  - **Nones go in the later slots** (user), and slot 1 never has one, as the
    screen never offered it there: 3 Forced is three and a None, 2 Forced
    two and two Nones, 1 Forced one and three; 2 Nones is two of the
    player's choosing and two Nones, Solo one and three; Th + Wm a Thief, a
    White Mage and two Nones; RWB a Red Mage, a White Mage, a Black Mage and
    a None.  Balanced is the seed's two of Fighter, Thief, Black Belt and Red
    Mage, then a White Mage and a Black Mage.  Fi + 3 and Th + 3 are the
    class and then three slots of any class or a None.
  - **Repeats are allowed** (user), as FFR picks each slot alone: 4 Forced
    can be two Fighters.  The free slots of 2 Nones and Solo offer the six
    classes only (user): their descriptions are "Choose two party members"
    and "Choose a single adventurer".
  - **The picks.**  `rando_party`, by JSL from `NewGamePartyUI` where the
    game ended the screen's setup (`party_forced.patch`, the four bytes that
    terminated `$60`'s draw buffer, which it does too), right after the copy
    of `lut_PtyGenBuf`: a stream of its own (`STREAM_PARTY`, "PRTY") from
    the save's seed, every slot drawing one below the count it allows,
    forced or not, so each mode reads the stream the same way.  Party
    creation runs after `rando_build` has written the seed, so B back into
    the screen forces the same party again.  `none_nextclass` steps an
    unforced slot to the next class it allows, and leaves a forced one.
  - **The seed screen** only for a mode the seed picks in (user: "some of
    the values ... don't depend on the seed"): Balanced, the four Forced,
    Fi + 3 and Th + 3.  `opt_needseed` asks `rando_partyseeded` -- a forced
    slot with more than one choice -- and `genpresets.PARTY_SEEDED` is the
    same list for a preset's way past the screens.
  - **Stored** in the high half of Surprise rates' byte (`PARTY_FIELD`),
    which the build masks to its own half (`SURPRISE_FIELD`), as Pirates
    shares Status attacks'.  Zero in every save and settings block before
    it: Free.  The save view shows it with the other rows.
  - **Presets** (user): Chaos Rush 4 Forced, FFR's four forced random slots;
    Free Enterprise 2 Nones, in place of the party FFR recruits from NPCs,
    which is not being ported; every other preset Free.  The presets'
    descriptions do not mention it, and stay as they are (user: "Don't
    modify the descriptions").

The descriptions, by value: Free "Choose all four party members, Nones
included, as usual."  Balanced "The seed chooses two of Fighter, Thief,
Black Belt and Red Mage. A White Mage and a Black Mage join them."  4
Forced "The seed chooses all four party members."  3 Forced "The seed
chooses three party members. The fourth is a None."  2 Forced and 1 Forced
the same for two and one.  2 Nones "Choose two party members."  Solo
"Choose a single adventurer."  Th + Wm "The classic Thief + White Mage
duo."  Fi + 3 "A Fighter, then three more that the seed chooses. Any of
them may be a None.", Th + 3 the same for a Thief.  4 WM "Four White
Mages.", and so on.  RWB "A Red Mage, a White Mage, a Black Mage and a
None."  (The user's words where they gave them, 2026-11-02; the rest the
drafts they kept.)

**Taverns** (user, 2026-11-02: "Off / Recruit / Replace"; built, not yet
played), after Party: FFR's Tavern Recruitment (`Party.cs` PubReplaceClinic,
`asm/0E Tavern Mode.asm`), every clinic a tavern.  Recruit's hire takes a
None's place; Replace's a None's or a party member's (user: "Replace means
you can fill a NONE slot or replace an existing party member").  Free
Enterprise sets Recruit (user: "since we don't have NPC Recruits"); every
other preset Off.

  - **Each town hires out one class**, the seed's (`deal_taverns`,
    `randoref.build_taverns`): FFR's deal, the six classes shuffled and
    shuffled again, the clinic towns taking them in turn -- Coneria,
    Pravoka, Elfland, Crescent Lake, Onrac and Gaia one each, Lefein the
    second shuffle's first.  Melmond has no clinic.  `RW_TAVERNS`, by map;
    `rando_tavern` reads it for the visit.
  - **The visit** (`tavern.asm`, `CHUNK_TAVERN = $1C`, by JSL from
    `EnterShop_Clinic`'s first six bytes): "Hire a <class>", and Revive or
    Hire.  Revive is the clinic, from its first instruction on, as FFR keeps
    it (user: keep revive).  Hire lists the slots it may take -- a None by
    its class, which reads "None" -- asks the clinic's price with the
    clinic's own confirm, and takes it (`tav_afford`: the clinic's
    `InnClinic_CanAfford` leaves its caller's caller on a no, so it is not
    called through the trampoline).  Recruit with no None says the party is
    full.  The shop's routines are reached through `OptCallFar`, the CHR
    loaders too: they end by swapping to bank $0E whatever called them.
  - **The hire** (`tav_make`): the class's starting stats as New Game loads
    them (`StartingStatsOne`, Better Thief and Ninja's agility included),
    then a level up at a time to **the party's lowest level** (user: "fun
    arbitrary divergence from FFR behavior, and slightly exploitable in an
    interesting way") -- the members that are not Nones, the one replaced
    counting -- and the experience that level takes.  **Deviation from
    FFR,** whose hire levels to the replaced member's experience, so a
    None's hire starts at level 1.  As FFR's: the slot's gear stays,
    unequipped; its spells and MP go; the class is promoted once Bahamut has
    promoted the party; it arrives with 1 HP, as a revive does.
  - **The level up** (`tav_levelup`) is bank $0B's `LvlUp_LevelUp` line for
    line up to its report (`Draw4EobBoxes`, which has nothing to draw on
    outside a battle and waits for the pad), its tables read from bank $0B
    and the cartridge's two hooks into it called the same way (Thief and
    Ninja hit%, Better Thief's agility).  `test_taverns` holds it to the
    original over every class, low and high levels, the caps and the
    armed and unarmed Black Belt, roll for roll.
  - **The name** (user: "Bring up the name screen, since we can't name NONEs
    presently"): party creation's own `DoNameInput`, on ptygen's fourth
    record, then the shop drawn again.
  - **The look** (user: "Full redecoration"): TAVERN over the shop
    (`tavern_title`), and FFR's three borrowings over the clinic's tiles as
    the shop's CHR loads (`tavern_shoppal`): the caravan's first four (a
    tablecloth), the item shop's next four (barrels) and the armour shop's
    last six (its armourer, tending bar), with the item shop's backdrop
    colours.  **The pub sign** is the town tileset's palm tree, tile $34,
    which no town places (user: "We don't need the palm tree"), as FFR's
    `MakePubSign` has it: mkrom.py (`overlay_pubsign`) points it at a roof
    (CHR $45-$46) over the sign art the tileset has and never used ($76-$77),
    with the clinic sign's palette -- FFR copies that art over the palm
    tree's CHR; pointing the tile at it is the same picture.  The art is
    the original ROM's, "PUB" on a board, but for its B (user, 2026-11-02:
    "I don't like the letter 'B'"; a wider U was tried and reverted, "shift
    the 'B' to match"): three wide with two bowls, one column in, where it
    was four with its right-hand corners filled (`overlay_pubsign_letters`,
    the town tileset's copy only).  Under Taverns
    a town's clinic signs become it as the map loads (`tav_signs`, from
    `rando_mapedits`).
  - **Stored** in Unrunnable fights' byte, bits 4-5 (`TAVERNS_FIELD`), which
    the build masks to its own half (`RUNS_FIELD`).

The descriptions, by value, the user's words (2026-11-02, the first drafts
"read like Claude-ese"): Off "Clinics revive fallen party members."
Recruit "Clinics become pubs, where new party members can be recruited."
Replace "Recruits may replace existing party members."  They are the first
records in `CHUNK_OPTTEXT2`.  The tavern's own words, in seven-column shop
boxes: TAVERN; "Hire a" and the class; Revive, Hire; "Who makes room?";
"Your party is full."; "Welcome aboard!".

**Rebellious Princess** (user, 2026-11-02, `rebellious-princess.txt`: a
flag of our own, not FFR's; built, not yet played), after Taverns, Off and
On, Off in every preset (user).  On, the kidnapped princess is at one of
eight spots, the seed's: Garland's; the Dwarf Cave beside the blacksmith
(8,2); Elfland Castle with the sleeping prince; Crescent Lake in the circle
of sages; Sarda's Cave on the chair (8,2); the empty cave beside Bahamut's
at Cardia; Pravoka near Bikke; the middle of Melmond (the user placed the
Dwarf Cave, Sarda's and Cardia; `worldgraph/romdata.PRINCESS_SPOTS`,
gengraph.py's `SARA_AT`).

  - **Talking to her is the rescue** (user: yes): Talk_Princess1 as ever, she
    disappears and the rescued princess appears in Coneria Castle, and the
    King's and the castle princess's rewards wait on it as before -- but
    **no teleport home** (`rando_princesswarp`; the user's note).  Garland
    still fights (user: "yes, but not really, since you have to get to the
    black orb eventually").
  - **Her lines**, the user's, swapped in for dialogue $05 at each spot, and
    Garland's $04 with her away (`rando_dlgtext`, `dlgsara.inc`, the world
    chunk's): "The king is a fool! I would never lay a hand upon the young
    lady. How dare you besmirch my honor!" (user: "I would never", an
    edit-induced error fixed).  It is 98 bytes, past OPTDESC's $50, into the
    shop and description screens' scratch after it, which nothing on a map
    uses (`OPTDLG_MAX`, $68).  The lines that call it a kidnapping stay (user:
    "the joke is that everyone thinks Garland kidnapped the princess, but
    it's usually a false accusation").
  - **On the maps** (`sara.inc`'s `rando_saraobjects`, from
    `rando_tofrplate` after the map's objects): the Temple's slot for her
    emptied; on her spot's map she is loaded into a slot it leaves empty
    through the game's `LoadSingleMapObject`, standing, so her game flag
    hides her once found.  Her graphic needs nothing: the empty slot loads
    object 0's, which is the kidnapped princess's (`lut_MapObjGfx`).  At
    Crescent Lake the sages are set loose (user: "just set
    them loose, they'll wander around a little before the player can walk
    there"), FFR's ConfusedOldMen's twelve, where they stand.
  - **Her spot** (`pl_sara`, `randoref.sara_world`): the seed orders the
    eight (`STREAM_SARA`, a Fisher-Yates), and a spot that cannot be won is
    passed over (user: "correct").  Under Key items Vanilla, the first
    `rando_winnable` passes with her there (`RW_SARALOG`) -- so without
    Early King, which lets the King give the BRIDGE before her rescue, she
    stays with Garland unless something free reaches her.  Under Standard or
    Wide, **placement tries her spots on each world it builds**
    (`pl_trysara`): in the seed's order, each with her masks there and the
    world's tries of its own, every spot whose placement can start --
    reaches an incentive spot with what is free and the Loose key items
    (`pl_sarago`); and if none places, Garland's unchecked, as without the
    flag (it can start by sending an incentive loose).  Garland's tries are
    the flag-off tries, so the flag never costs a world (`test_princess`
    holds the reference to that).  So with Early King, or the SHIP and
    airship free, she is at the seed's first spot; with neither and nothing
    free, the King waits on her and nothing can start: Garland's.  Under Map
    shuffle the start region varies, and she is at Garland's more often
    than one in eight.
  - **Her masks**: the vanilla tables' (genlogic.py's `SARA`, past the
    locations' in `lut_LogicMasks`, `lut_LogicSaraLo/Hi`), and under Map
    shuffle or map edits es_build's -- all eight worked out with the wiring
    (`es_saraspots`, while `RW_SARAON`), so a wiring is built once, not once
    per spot (the first build did, and a Map shuffle New Game took 5.7
    times as long).  Her place in `RP_MASK` is `SARA_SLOT` long, one more
    than a spot's masks can be, padded with `SARA_NEVER`, and placement
    copies the spot it tries there (`pl_sarause`); `SARA_NEVER` is never met
    and names every bit, so es_build's by-bit index asks after her on all of
    them (the vanilla tables' names her under every bit a spot does).
    Moving her moves no other location's masks (genlogic.py checks, with
    Early Ordeals and without).
  - **Stored** in the RNG tables' byte, bit 4 (`PRINCESS_FIELD`); RNG tables
    is bits 0-3 (`RNG_FIELD`), which the build masks (it once read the whole
    byte, and the flag turned the RNG shuffle off).

The descriptions, by value, drafts: Off "Garland holds the princess in the
Temple of Fiends."  On "The princess has run away from home. She may be
found in one of several places."

This section is the start of the randomizer, and its rows are a different
kind of setting from everything above.  They describe the *next* new game:
New Game's build copies them into the save, beside a seed, as the game
starts (`rando_build`), and nothing reads the settings screen's copy after
that.  Changing a
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
    Goal             4 orbs / 3 / 2 / 1 / 0 orbs  (below; built 2026-10-25)
    Map edits        Off / Open / All             (below; removed 2026-10-24)
    SHIP .. ROD      Incentive / Loose / Free     the eleven Free rows; the
                     (SHIP, AIRSHIP: ... / Remove) SHIP's and AIRSHIP's go on
    Other items      Incentive / Loose            the nine with no Free
    Masmune .. Xcalber   Treasure / Incentive     nine gear rows
    Early King, Sarda, Sage, Ordeals   Off / On

All of it works now (built 2026-10-14; played once): Free, which
`opt_freestuff` reads from the save New Game's build wrote
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

**Remove** (user, 2026-10-18; built, not yet played): the SHIP and AIRSHIP
rows' last value, the SHIP or the FLOATER in no place and never held --
FFR's NoFloater for the second, the airship never rising.  Placement places
neither (`pl_items`, `randoref.place_setup`); its home turns to gold as a
Free item's does (`deal_rewards`, `build_rewards`).  Under Key items Vanilla
too: the FLOATER's chest holds gold before the Chests row deals
(`nofloater_gold`, `build_chests`), and Bikke keeps his ship, the removed one
reading as held (`talk_holds`).  With the FLOATER gone Map shuffle keeps
FFR's doors the airship alone reaches -- Titan's Tunnel's west end, Cardia's
but under the Cardia Land Bridge, the first and Bahamut's but under Bahamut's
dock (`EntrancesFloorsShuffle.cs`; `es_wiring`, `es_shuffle`).  Either alone
leaves the unedited map unwinnable, as in FFR, where they go with map edits:
FFR's walking set -- Early Open, River to Melmond, Highway to Ordeals, Bridge
to Lefein, the land bridge -- places with both removed.  The unwinnable
warning is for the rest.  The two rows have four values (`ITEMVEHICLE_MODES`)
in the same two-bit fields, so no byte moves.  `test_rando_remove` holds it
all to the reference; `checkplace.py` plays the settings on the edited maps.

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

**Built 2026-10-14; played 2026-10-28** (user: an Entrance and floor seed
to near the end, placement held up, the seed winnable).  FFR's Entrance Shuffle and Entrance
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

`python3 tools/randoref.py SAVE.ram --map` prints a battery file's wiring
(user, 2026-10-17): each overworld entrance, by where it leads in the
vanilla game, and the floors beneath it as the stairs and teleports lead,
each under the floor it is reached from -- FFR's location name beside the
map's where it says more, which of Cardia's six, which floor holds Lich --
and which floors have a way back out.  The full dump shows it too whenever
Map shuffle is on.  `test_es_tree` holds it to the shuffle's own roots.

### Goal

**Built 2026-10-25; not yet played.**  How many of the four orbs the Black
Orb waits for (user, 2026-10-24: a Goal selector, 4 orbs by default, 0-4,
to which FFR's Shard Hunt may later add counts of shards): FFR's Orbs
Required in its Any mode -- any of the orbs, not chosen ones; its Specific
mode and spoiler lines are not ported.  A row after Map shuffle, one byte at
the end of the new-game settings (`RANDO_GOAL`, `OPT_NG_GOAL`), holding the
orbs waived, so zero is the game's four; GOAL_ORBS is the bar, lit + waived.
Chaos Rush takes 0 orbs, FFR's `OrbsRequiredCount` 0 (ffr-presets.md 3.5);
every other preset 4.  The row's descriptions say what each goal does and
no longer name FFR's flag (user, 2026-10-27: a reference only FFR's players
would follow).  Left lowers the orbs and right raises them, as left lowers
every other row's number (user, 2026-10-27: left raising them was
counterintuitive): `opt_value_adjust` swaps the d-pad on this row and Min
gear curse (`opt_valdir`, which knows them by their readout tables), the
steps and what the save means by them unchanged.  Built, not yet played.

  - **The Black Orb** (`orbgoal.patch`): its four-way AND becomes a call to
    `opt_orbgoal`, which counts the orbs lit, adds the Goal's waived and
    asks for 4, byte-neutral.  Its line when it gives way (dialogue $21)
    begins "The four ORBS now cover", wrong when the Goal waives some.  FFR
    rewords that first line by the Goal; here it goes by the orbs the party
    carries (user, 2026-10-27: "You can't base the wording on the goal...
    has to be based on the number of orbs carried"): two or three lit "The
    ORBS now cover", one "The ORB now covers", none "You lay your hands upon"
    (the user's, not FFR's "You now approach"); all four, the game's own
    line, so Vanilla is unchanged.  `opt_orbgoal` arms `RW_DLGNPC`
    (`DLG_ORB0` + 0, 1 or 2) as it says yes, and `rando_dlgtext`
    (`rando_dlgorb`) builds the line in OPTDESC: the game's rest of $21 from
    its first break, still DTE (55 bytes; written out it would not fit), then
    the first line before it.  Built, not yet played; test_goal checks the
    arming over every goal and lit set, and the three lines byte for byte.
  - **The tile beneath it** (`orbportal.patch`): TP_SPEC_4ORBS's entry in
    `lut_SMMoveJmpTbl` goes to `SMMove_HaveSpecialItem`, the fanfare and on,
    as FFR's `Remove4OrbRequirementForToFRPortal` does, unconditionally:
    the orb stands on the one such tile in the game (Temple of Fiends,
    (20, 17); every map searched) until it gives way.
  - **The logic, both checks** (`goal.inc`; user, 2026-10-24: the flagset's
    validation must follow the goal, or removing the airship without the
    edits that reach the north "claim[s] the flagset is unwinnable ...
    (which it is)" a bug).  Placement's last test (`pl_attempt`) and the map
    edit screen's (`rando_winnable`) read the same Chaos masks, and both now
    count the orbs: the orbs come into those masks all four at once, only
    through the Black Orb and its tile (worldgraph's GATE_ROUTINE and
    GATE_TILE), so a mask holding all four is met with its orbs aside once
    lit + waived >= 4, and one without them -- a way round the orb a shuffle
    may make -- as it is.  At 4 orbs that is the old test exactly.  Places
    beyond the Black Orb still count all four in their own masks: a little
    strict, never wrong.  `randoref.chaos_won` is the reference.
  - **Placement in a smaller world.**  With the goal smaller the world
    needed can be too: the FLOATER removed with no map edit reaches Lich
    and Kary only, and the screen now says that world can be won at 2 orbs.
    FFR's placement could not place it -- every incentive needs a spot the
    party reaches, and only 15 of Standard's 21 are (18 of Wide's 25) -- so
    no seed built (0 of 6, randoref).  Its rule sends an incentive loose
    while there are more of them than spots; the spots counted now are
    those the party can reach at all, holding every key item to place, the
    screen's own assumption (`pl_reachspots`, `randoref._attempt`), and the
    caravan is stocked with an incentive only when it is among them
    (`pl_vendor`): FFR stocks it unreached, and the CROWN went there.  So
    every key item lands where the party can go, the useless ones too --
    the player's choice "so long as there is room for them" (user,
    2026-10-25).  The map edit screen shows the counts on Select (below).  Wherever every spot is reached -- any world with the
    airship, map edits that open the north -- the count is FFR's: 640
    worlds of ordinary settings, the shuffle and edits among them, and 60
    with the FLOATER removed and edits, place as before.
  - **The tiniest worlds.**  The SHIP removed and 0 orbs -- the world is
    Coneria, Pravoka and the Temple -- the screen says winnable, but FFR's
    step-by-step placement stalls there and most seeds place nothing (1-2
    of 6).  New Game left the key items at home then, which without the
    ship cannot be won; since 2026-10-27 it says so on the roll screen and
    goes back to the seed screen, with no fallback placement (user; "The
    world built before party creation", above).
  - **The save.**  `RANDO_GOAL` is the settings' last byte, so `RANDO_ESK`,
    `RANDO_SHIPDOCK` and `RANDO_OWEDITS` moved up one (the first two since
    gone, "Placement out of the save" above): SAVEVER 1, older
    saves do not load (user, 2026-10-25: not a concern for a major feature,
    only for a fix mid-playthrough).  In the option page the Goal took its
    last spare byte, `$DF`, inside the block's sum: an older block with zero
    there still sums and reads as 4 orbs; `OPT_FORMAT` stays.

`test_goal`: the row and its readouts, the byte New Game copies; the Black
Orb under every goal and every set of orbs lit, 80 cases, giving way, hidden,
the treasure sound, exactly when lit + waived >= 4; the tile's table entry;
`rando_winnable` against `randoref.winnable` under every goal over removals,
edits and Early flags, a smaller goal never less winnable; the user's case on
the map edit screen, red at 3 orbs and blue at 2; and New Game's placement,
the cart's randoref's, a world at 2 orbs every seed and none at 3, every key
item reachable and the caravan unstocked.  `tools/checkplace.py`'s new last
part plays each goal's placements on the world graph, the Black Orb asking
the Goal's orbs there, beside the screen's answer.

### Map edits

**Removed 2026-10-24** (user: "No value in it ... Clean it up"; "New
Game's screens", above).  Built 2026-10-17, never played; hidden from
every screen 2026-10-21, the map edit screen having taken its place in New
Game's flow, then only Custom Game's fallback once presets carried their
own `[map_edits]`.  What follows is its history; the edits themselves,
`RANDO_OWEDITS`, the BRIDGE and the docks, and the tests of them, stay.
FFR's overworld map edits, one row
standing in for its fourteen flags until New Game has a screen of its own
(user: "don't mess up labels on the existing options screen just for the
sake of toggling map edits, as the long term plan is to put those toggles
on their own screen during new game creation").  Off; Open, FFR's Early
Open Progression, the one edit its randomized presets turn on (Coneria to
the Dwarf Cave on foot, the Volcano's and the Ice Cave's rivers joined);
All, every edit that only adds a way through -- Early and Extended Open
Progression, the Northern, Ryukahn Desert, Bahamut Cardia and Lefein River
docks, Bridge to Lefein, Gaia Mountain Pass, Highway to Ordeals, River to
Melmond and the Hiking Trail.  Not Sarda's Forest, which takes a way away,
nor the Cardia Land Bridge, which moves Cardia's doors, nor Ship in
Drydock, which leaves the ship useless: those three are the map edit
screen's to tick (below).  Since 2026-10-18 (played 2026-10-28)
placement's logic is the edited map's, every edit known to it, as FFR's is
-- before, it was the vanilla map's, sound only because the eleven only
open the map.  How it works is `randomization-notes.md` §9.1.

The row is a field, bits 4-5, of the Early flags' byte (`RANDO_EARLY`,
`OPT_NG_EARLY`), whose readers each test their own bit; `OPT_NG` has no
byte to spare.  New Game expands it into `RANDO_OWEDITS`, two bytes
appended to the save block with a bit per FFR flag, which is all the game
reads -- so the screen to come can set them one by one, and zero, no edits,
is every older save.  Neither `OPT_FORMAT` nor `SAVEVER` moves.  Bridge to
Lefein also sets the BRIDGE down at (230, 123), as FFR does, and moors a
ship that would have berthed at Matoya's dock, which its edits delete, at
Coneria's (FFR's `UpdateDocks`); placement then weighs the BRIDGE at FFR's
0.75, not the vanilla map's 2.0 (2026-10-18, built, not yet played;
`test_es_place`, both sides' mutations caught).  Four columns of readout, one description
per value.  `test_owedits` holds the transcription to FFR's source (beside
the tree), the cart's rows, window and minimap, to `owedits.apply` flag by
flag, New Game's expansion and the BRIDGE, and the row's field, with no two
of the page's fields sharing a bit; `test_rando_shipdock` the dock.  26
mutations, 24 caught; the two missed are equivalent (the window's slot
masked to five bits, `$70` already holding the fifth; the canal list, gated
on a bit no mask holds, in the table).

The row acts at New Game, which writes `RANDO_OWEDITS`; a save continued
has the edits it was started with.  To look at the edited map with any save
-- flying it in the airship, the minimap -- `FFDEBUG=owedits ./build.sh`
turns every edit on whatever the save says, all fourteen, the three no mode
offers among them (user, 2026-10-18, for a first look before the New Game
screen).  It edits only the map: the BRIDGE stays where the save built it.
The minimap was wrong with it, by design of the minimap rather than the
edits: Sarda's Forest and the Cardia Land Bridge put land in blocks whose
tiles the logo borrowed.  Fixed 2026-10-18 (played 2026-10-28; user):
those blocks have their tiles back and the logo's moved into two blocks
of open sea's, which show the blank tile.  The first layout used twins'
tiles, which lit two pixels early as the minimap drew (user, 2026-10-29);
fixed the same day (9d7a03d), played 2026-10-29 (user: "Checks out") --
`randomization-notes.md` §9.1.

### New Game's map edit screen

**Built 2026-10-18; the menu judged good by the user and merged, the
batch after it played 2026-10-28 (user: "fairly confident on the map edits and validation logic").**  A checkbox for each of FFR's
overworld edits -- thirteen since Ship in Drydock went (below) -- the
world's minimap as they would make it, and a
zoom of the selected edit in the game's dialog box frame (user: per-edit
toggles on a screen of their own during New Game, the Map edits row only
standing in).  `owscreen.asm`, a native screen in a chunk of its own
(`CHUNK_OWS`).

**Ship in Drydock removed** (user, 2026-10-27: "It isn't very useful
without the Airboat flag. It still has the tiniest impact of allowing a
useless SHIP as a key item, but that's just silly and otherwise equivalent
to removing the SHIP").  Gone: its line on the screen, its description, its
mooring of every ship at Gaia's drydock (`rando_newgame`, `give_vehicle`,
`opt_freestuff`, `es_dock`'s sixth dock), its share of the screen's slow
path -- a tick now checks only under a removed SHIP or FLOATER -- and its
regions in the world graph (two, regenerated: `gengraph.py`,
`genlogic.py`).  Its bit 13 of `RANDO_OWEDITS` is unread, `OWEDIT_FLAGS`
`$1FFF`; SAVEVER 2.  FFR's `GaiaDrydock` list stays transcribed in
`owedits.py`, gated never (`DROPPED`), so the check against FFR's source
still holds every list.  `checkwin.py`: all 8,192 combinations of the
thirteen winnable without a removal, both modes; `checkplace.py` loses no
seed.  `test_winnable`'s screen sequence, which used Ship in Drydock as its
red-and-back tick, now runs on the FLOATER removed, North Docks the edit
that wins it, the SHIP removed for the other reason, and no removal for
no check at all.  Played 2026-10-28.

The user saw four layouts -- the minimap above a two-column
grid or beside a single column, each with the zoom or without -- and chose
the side one with the zoom (2026-10-18); the others' code went once it
was chosen.  All inside the 30x26 cells a CRT shows: the column is rows
2-15 beside the minimap's 1-16 (user: aligned with it), the zoom below the
minimap, the title and description beside the zoom.

  - It comes up in New Game's flow, between the randomization screen and
    the options (2026-10-21; "New Game's screens", above), starting, for
    Custom Game, from the saved game's edits when Continue would load that
    save and it has any (no option block bytes), else none; for a preset,
    from its `[map_edits]`.  Before the flow it came up from
    `rando_newgame` when the Map edits row was not Off.  START keeps
    what is ticked (Sarda's Forest, the Cardia Land Bridge and Ship in
    Drydock were grey and dropped until the logic knew them, 2026-10-18;
    Ship in Drydock is gone since, above).  The title's music plays on through it (`rando_newgame`
    silences it after, for the roll screen).
  - As the other menus: the settings screen's own checkbox tiles (from
    `optmenu.asm`'s `lut_CheckboxCHR`) and the game's hand, two cells before
    the box.  The names are the user's, up to 13 letters; with the hand,
    a grid of two columns needs 32 cells, so the hand overlaps the end of a
    long name in the left column, and in the side layout the minimap's edge
    (user: rather that than shorter names).  No control hints.  The
    settings screen's chirps: the move's on a move, the select's on a tick.
  - **The unwinnable warning** (user, 2026-10-18; played 2026-10-28).
    START is not taken on edits that, with the rest of the settings, make a
    world that cannot be won: the description's place says why -- "This
    can't be won.  The AIRSHIP never rises." when the airship is never
    raised though the FLOATER is there, "The way to Chaos never opens."
    otherwise -- until a move puts the description back, or a check finds
    the edits winnable again (user, 2026-10-20: it stayed until the hand
    moved; played 2026-10-28): `ows_rewarn`, at the end of every check,
    the fast path's included, puts the selected setting's description back
    if the warning is up (`V_WARNED`) and they can be won, and otherwise
    redraws the warning for the reason as it now is.  And a refused START
    plays the game's error sound (user, 2026-10-20: "the annoying error
    sound"; played and verified 2026-10-21), `PlaySFX_Error`'s writes on the
    screen's own frames: square 1 and the noise silenced, then square 2
    struck sixteen frames running with the music held, as the game holds it,
    then silenced.  The game's routine waits on `WaitForVBlank_L`, whose
    flush would put the game's picture over this screen's, so here
    `ows_music` strikes it in place of the frame's music while `V_ERR`
    counts, and the screen goes on meanwhile.  The check,
    `rando_winnable` (`randoref.winnable`), works out the vanilla wiring's
    logic under the edits and Early flags, then under Key items Standard or
    Wide asks whether Chaos is reached owning every key item there is --
    all but a removed one -- and every event that reaches: placement finds
    a world exactly then, over every setting `checkplace.py` tries.  Under
    Key items Vanilla the items stay home, so it sweeps from the free ones,
    each place reached giving its vanilla item (`lut_LogicVanBit`) but a
    removed one.  130,000 to 265,000
    instructions.  Before the flow, with the Map edits row Off New Game
    checked only when the SHIP or the FLOATER was removed and if so forced
    the screen up, saying why (`OWS_FORCED`); removed with the row
    (2026-10-24), the flow's screen checking on its first frame instead.
  - **The numbers, on Select** (user, 2026-10-25/26; built, not yet
    played).  Under Key items Standard or Wide, Select shows five numbers
    where the description goes, each a label and two cells (`ows_incdesc`,
    `lut_OwsIncLabel`, the user's labels): Incentive Items, as placement
    takes them (`pl_items`); Locations, the settings' 21 or 25; Reachable,
    holding every key item to place (`pl_reachspots`'s count); Loose Items
    ("Excess Loose" until 2026-10-27, user), FFR's rule, the incentives past
    the locations; and Unreachable Loose,
    those loose besides for want of reachable locations -- the removals and
    the edits.  They stay until the hand moves, and are drawn again after
    every check while they are up.  A Select pressed while a check runs is
    kept for after it, as A and START are, but a move made after it undoes
    it.  Under Map shuffle Reachable and Unreachable Loose are not shown:
    the wiring is the seed's, chosen later, and placement may try several
    (user: "Hide always").  Under Key items Vanilla Select does nothing.
    Reachable is the check's (`rando_winnable` counts it as it goes,
    `ES_NREACH`); without a removal, where the screen runs no check, every
    location is reachable, over all 8,192 combinations of the edits, both
    modes and the Early flags (32,768, randoref).  A first version put an "Incentives" line under the edits, the
    numbers its description (8772629): the user found it ugly and bad UX,
    and its last two numbers wrong under Map shuffle.  `test_owsinc` holds
    the numbers to `randoref.incentive_counts` over 62 settings, the text,
    a tick redrawing them, Select during a check, a move undoing it, Map
    shuffle's three lines, and the Vanilla screen without them.
  - **Blue is red** while the ticked edits cannot be won (user, 2026-10-18;
    played 2026-10-28): the backdrop, which the minimap's ocean and the
    boxes are, and the selection's flashing ocean (`lut_OwsBack`), checked
    again on every tick (`V_CHECK`, `ows_check`).  A check is a quarter of a
    second, so the screen goes on through it: each vblank `rando_yield`
    calls `ows_tick`, which with `OWS_TICKFRAME` runs the screen's frame --
    the transfers, the music, the pad, the reset -- the hand moving, A and
    START kept for after (`V_PEND`); a reset taken in a check's frame turns
    the ticks off.  But a tick checks only with the SHIP or the FLOATER
    removed (user: "running down the column checking every box"): without
    them every combination of the edits can be won,
    under every Key items mode and Early flag, which `tools/checkwin.py`
    proves over all 8,192 -- Free items and Early flags only open the
    world further -- so the usual tick costs nothing.  A table of answers
    was not the way: the removals, Key items, Early flags and Free rows
    multiply it, and every routing flag to come would again.
    `test_winnable` holds the cart to the reference over Key items,
    removals, Early flags and edits, and the screen through red and back,
    a move and a held A in a check's frames, START refused and taken, L + X
    in a check, and the forced screen red from the start; and the warning
    kept by an A that leaves the edits unwinnable, gone with no move for
    one that makes them winnable by a whole check (North Docks ticked, the
    FLOATER removed).  Since 2026-10-27 the sequence runs on the FLOATER
    removed (it ran on Ship in Drydock under Key items Vanilla), with a
    second for no removal, no check at all.  Four mutations, all caught.  The error
    sound: the opening writes, sixteen frames without music striking
    square 2 as `PlaySFX_Error`'s `@Frame` does, the last silencing it,
    then the music; six mutations, all caught.
  - **A check's tick sends only early in its vblank** (`OWS_TICK_LAST`,
    line 232; user, 2026-10-18: "sometimes clicking the button doesn't
    toggle an item. It makes the sound ... but the checkbox doesn't
    change", until the hand moved; played 2026-10-18, not seen again, and
    the user called it fixed).  A tick comes
    when `rando_yield` next looks (`framedue`), and during a check its looks are
    up to 6,800 instructions apart, so a tick could run `ows_vblank` past
    the end of the vblank: the PPU dropped the tilemap with the new box
    while its flag (`V_NTD`) was cleared, and only a move's description
    sent it again.  The check's instructions are the same for the same
    edits, from the same point in the frame, so a box missed the same way
    every time -- Ship in Drydock ticked (since removed) or a ship removed,
    there being no check otherwise.  The worst `ows_vblank`, the tilemap and the zoom, is
    3,360 bytes and 267 instructions, some 26 of vblank's 37 lines.  A
    later tick reads the V counter as `hal_waitvbl` does and leaves the
    transfers, flags and all, for the next tick on time or the loop's next
    frame, which always starts at the top of one; the music and the pad go
    on.  The roll screen's tick writes only registers, so it was never
    exposed.  `test_owscreen` sets the harness's V counter, which keeps no
    time, to each side of the line; the old code fails it.
  - L + X and L + Y reset from it as from anywhere (user).  Its loop waits
    on `hal_vblaudio`, not `WaitForVBlank`, so it makes the reset's two
    calls itself: `hal_auxdetect` (the HAL's look at L, X and Y alone) after
    its vblank's transfers, then `opt_padreset`, which also stirs the seed's
    pool as every frame of the menus does -- and when a reset is coming,
    hands the PPU back to the HAL first, as leaving the screen does.
  - Responsive (user: "the most important problem"): the pad is read and
    answered every frame -- the hand, a box, the description -- and the
    pictures follow, a frame drawing at most a pixel row of the minimap or
    two map rows of the zoom (`BUDGET`, about three quarters of a frame at
    worst; the first build drew a whole zoom in one go, twelve frames
    without reading the pad).  The zoom on screen is the last one finished.
  - The minimap is decoded from the game's own RLE rows and edited from
    `world.asm`'s tables, as the game edits its map, so it shows what the
    game will, in the game's minimap colours (bank $09's
    `lut_MinimapTileset`); a row decodes straight to colours, a run's looked
    up once, with bit 3 marking the selection's tiles.  A tick or a move
    redraws only the rows its edit writes, and of those only the 8-pixel
    characters an edit list writes in (`lut_OwsCharMask`).
  - It comes up whole (user: not drawn in while you watch, as the first
    builds did over about two seconds).  The unedited minimap is in ROM,
    rendered by `genows.py` from bank $01's rows (`lut_OwsBaked`, 8KB); in
    forced blank it is copied in, the rows the ticked boxes and the
    selection change are drawn over it, and the first zoom, before the
    display goes on: about 117,000 instructions with nothing ticked,
    223,000 with all eleven that play, a fifth to a third of a second black
    by a rough rate.  The title's music is kept going meanwhile, a frame of
    it whenever a frame has begun whose music nobody has played (`ows_audio`,
    the HAL's `framedue`), the setup looking every half frame or so, as the
    roll screen keeps its sound.  Runs fill by MVN, and the zoom's doubled lines are copied, not
    packed twice.
  - The selection's pixels flash and rings mark its places
    (`tools/genows.py` clusters each list's writes); the zoom shows one
    place at a time, 28 tiles at two pixels a tile or 56 at one when the
    place is wider.  What is marked follows the other box where one changes
    the other (user): Bahamut's dock is its own list, or with the Cardia
    Land Bridge ticked the two's variant alone -- as `ows_actives` applies
    them -- not both docks.  The land bridge needs no second view, its own
    tiles taking in the variant's two.
  - Its WRAM is $7F1000-$7F44FF, between the credits' ($7F0000-$7F04BF) and
    the ending's ($7F6800), neither ever up with it; `snesmap.inc` and
    `credits.asm` assert both edges.
  - `test_owscreen` holds the minimap and the zoom to a rendering of
    `owedits.apply`'s map, the selection's tiles named list by list for
    Bahamut's dock and the land bridge, and the dock's ring; checks VRAM
    holds the whole minimap and zoom as the display goes on, a frame of
    music for each vblank meanwhile; and runs the screen from New Game: the
    saved game's default, A ticking, the held-back dropped, the row Off
    skipping it, the chirps, and L + X resetting with the PPU handed back
    first.  The harness now keeps OAM too, for the pictures the screen was
    judged from before it went to the user.

### Respond rate

**Decision: independent of the presets.**  It keeps its own title-screen
control and its own byte in the options block, and defaults to 8.  The
byte's three low bits are the rate; above them, since 2026-11-03, the FUN%
rows, which are the player's own too (`OPT_FUN`, above).

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
| Enemy stats min, max | 25-500% | 25% | 20 | 100%, 100% |
| Enemy HP min, max | 25-500% | 25% | 20 | 100%, 100% |
| Boss stats min, max | 25-500% | 25% | 20 | 100%, 100% |
| Boss HP min, max | 25-500% | 25% | 20 | 100%, 100% |
| Elemental bonus | +0 to +50 | 2 | 26 | +30 |
| Trap tiles | Off, Shuffle, A, B, A+B | -- | 5 | Off |
| Shops | Off, Shuffle | -- | 2 | Off |
| Chests | Off, Shuffle | -- | 2 | Off |
| Magic levels | Off, Shuffle | -- | 2 | Off |
| Item magic | Off, Shuffle, Balanced | -- | 3 | Off |
| Max gear blessing | 0 to +5 | 1 | 6 | 0 |
| Min gear curse | 0 to -5 | 1 | 6 | 0 |
| Formation rarity | Off, Shuffle, Tiered | -- | 3 | Off |
| Formation zones | Off, Shaken, Stirred, Random | -- | 4 | Off |
| Unrunnable fights | Off, Shuffle | -- | 2 | Off |
| Surprise rates | Off, Shuffle | -- | 2 | Off |
| Status attacks | Off, Shuffle | -- | 2 | Off |
| Enemy scripts | Off, Enemies, Bosses, Both | -- | 4 | Off |
| Enemy skills | Off, Enemies, Bosses, Both | -- | 4 | Off |
| Pirates | Off, Buffed, Nasty | -- | 3 | Off |
| RNG tables | Off, Shuffle | -- | 2 | Off |
| Party | Free, Balanced, 4 Forced ... RWB | -- | 16 | Free |
| Taverns | Off, Recruit, Replace | -- | 3 | Off |
| Rebellious Princess | Off, On | -- | 2 | Off |
| Stereo Sound | Off, On | -- | 2 | Off |
| Thief and Ninja hit% | +2, +3, +4 | 1 | 3 | +4 |
| Thief lockpicking | Off, level 1, 5, 10 ... 50 | -- | 12 | 15 |
| Starting items | None and FFR's eight sets | -- | 9 | None |
| Starting caster item | Off, AoE, Any | -- | 3 | Off |

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

Layout, 25 bytes of the 256:

    (at OPTBLOCK = $6E00, 25 of the 256 bytes available)
    magic       2    distinguishes an initialised block from battery noise
    version     1    format version
    preset id   1    0-2 preset, 3 = Custom
    flags       6    checkbox bits; 26-36 spare since format 9
    scalars    13    gold/XP, encounter, enemy, boss, elemental, Thief hit,
                     starting items, then the scaling's six ranges' (enemy
                     stats max, enemy HP min and max, boss stats max, boss
                     HP min and max) -- step indices
    respondrate 1    0-based
    checksum    1    sum forced to $FF, as the game's own save does

**The page holds only what must outlive a power-off (2026-10-30, user:
"start the settings page cleanup"; played the same day, a full Chaos Rush
seed with Pirates Buffed: "seems to be in good working order").**  The block above, `RANDO_POOL`
(`$C4`, the seed's entropy) and `OPT_NG` (`$C8`, New Game's settings) stay
on `$6E00`.  Everything else that lived there -- the derived bytes, the
settings code's working bytes, `OPTDESC`, the shadows game code reads through
pointers, the battle's enemy records -- moved to `OPTWORK`, `$0E00` in low
WRAM, each at its old page offset.  Every bank the game and the settings run
in (the chunks, `$A1-$BF`) mirrors low WRAM at `$0000-$1FFF`, so absolute
addressing, 16-bit pointers and the long addresses built on a chunk's bank
(`SRAMFAR`, `CHUNK0 * $10000`) reach it unchanged; no instruction changed,
only the symbols' values.  Reset zeroes WRAM, and `opt_init` cooks `OPTD`
and clears the poses every boot, as before.  The persistent layout did not
move, so `OPT_FORMAT` stays 9 and every saved setting keeps.  Free on the
page now: `$13-$C3` above the block (177 bytes) and `$E0-$FF` after
`OPT_NG` (32), room for the scaling rows and more -- which took six,
2026-10-31, so `$19-$C3` (171).  The tests' `blk` and
`setblk` refuse an offset that moved (`pageoff`), and `work` / `setwork` read
the work area by the same offsets.

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

`OPT_FORMAT` is 10.  It went to 3 when the flag word grew its fifth byte, to 4
when the elemental bonus became a dial and needed a fifth scalar, to 5 when
the checksum took in the new-game bytes, to 6 when Thief hit growth became a
sixth scalar, to 7 when the starting items took a seventh, to 8 when the
flag word grew its sixth byte, and to 9 when the Free items left the flag
word (bits 26-36 spare; Short ToFR took 26 on 2026-10-19) for the key item rows, and to 10
when the scaling's six range scalars came (2026-10-31); each bump
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
otherwise.**  `OPT_SIZE` is `$19` (`$13` until 2026-10-31), so only the settings are covered by the
checksum -- everything from `OPTBLOCK+$13` up was working storage that
happened to live in SRAM (in low WRAM, `OPTWORK`, since 2026-10-30).  That is fine for per-call scratch, which every routine writes
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
  - **Short ToFR is retroactive across a game.**  Its pieces are written as
    the Temple's maps load, and the party is never inside the Temple at
    Continue.  Chests opened on the long Temple's floors stay opened in the
    room (chest flags are by chest), and the plate on either floor is one
    object, so a LUTE played on one has opened the other.

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

The **NEW GAME** rows.  New Game's build (`rando_build`, before party
creation) copies them into the save block at `$60A0` with the seed.  From
then on the save's copy is the only one read, and the save holds nothing
else of the randomizer's but the reward NPCs' state: everything drawn from
the settings, placement included since 2026-10-27, is the cache's, drawn
again whenever the cache is built.  A Continue gets the world it was started with,
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
  - **A chirp is the press's, played once where it is heard; no screen
    chirps for appearing** (2026-10-22; built, not yet played).  The
    game's title plays no chirp for its choice, so the screens it opens --
    the settings, the save view, the credits -- each played one as they
    appeared.  In New Game's flow that made two of most steps, the screen
    left chirping at the press and the next chirping again once built,
    a moment later, as if on the release (user: "the sound to play twice
    when transitioning between menus").  Now `opt_titlechirp` chirps as the
    title hears a row that opens a screen -- New Game, the options row,
    Credits, Select on Continue, and Continue with no save, which is a New
    Game -- and Continue to a game stays silent, as the game has it; no
    screen chirps on entry; and the map edit screen's START, the one
    leaving press that was silent (the options' entry chirp covered it),
    chirps.  So every step of the flow is one chirp, at the press:
    `test_chirps` runs each screen -- the list, the options, the
    randomization screen, the seed, the map edits, the credits -- for no
    chirp from entry to its first pad read and one for the press that
    leaves it, and the title for one before the screen it opens and none
    for Continue.  Seven mutations, all caught.
  - **The title's music plays through the menus' builds** (user,
    2026-10-23: "the music stalls between most of these screen
    transitions"; played 2026-10-24, with the next entry's mends).  A screen builds with the screen
    off, and nothing called the music driver until its first frame wait:
    some three frames into the settings engine's screens (the clear, the
    blue fill, the description box), ten into the seed screen (its
    nametable, through the slow path a byte at a time), seven into party
    creation (the game's own CHR loads and clears).  Now the HAL's bulk
    calls -- `hal_chrload`, `hal_ntfill`, `hal_clearnt` at its entry and
    its end -- ask, at their entry, `menutick`: with `MENU_TICKON` set and
    a frame begun whose music nobody has played (`framedue`; at first this
    asked RDNMI, which the next entry mends), `menu_tick` (`optmenu.asm`)
    plays the frame's music and the HAL's audio frame, as the map edit
    screen's checks tick theirs (`ows_tick`).  It keeps everything the
    interrupted code holds: the registers, the data bank, `cur_bank`, and
    all of `tmp`, which the music driver works in (`mu_scoreptr` is
    `tmp+8`) and `hal_chrload` takes its source from.  Taking the vblank's
    latch, it makes a frame wait inside that vblank wait for the next, so
    no frame plays twice.  With the flag on a long `hal_chrload` goes two
    rows at a time with a chance between (`CHRLOAD_TICKROWS`); with it off,
    whole as ever.  The flag is the title's: `opt_titlechirp` sets it as a
    row opens a screen, `opt_titleleave` clears it as the title leaves for
    a game, so a game's own loads, and the soft reset's path, are as they
    were; a reset zeroes `MENURAM`.  The seed screen's nametable now goes a
    row at a time through `hal_ntblit`'s fast path, a chance every fourth
    row, and its attributes 8 at a time -- and the screen is up in some
    seven frames' work rather than twelve (86,000 instructions, from
    147,000).  Measured as the harness can, in
    instructions (~12,000 a frame): the longest stretch without a chance at
    the music is now about half a frame on the settings engine's screens
    and the title's rebuild, under three quarters on the seed screen and
    party creation.
  - **The menus' music, a frame of it every frame, in ares** (user,
    2026-10-23: "It still sounds like multiple frames of stalling between
    most of the frames (all of them after preset selection)"; played
    2026-10-24 -- the menus' music, the dialogue boxes at full speed after
    the fix below, the roll screen's wandering tempo back).  The ticks above asked RDNMI whether a vblank had begun,
    and RDNMI's latch clears at the vblank's end as well as when read --
    ares as the hardware, which the harness never modelled -- so a look had
    to land in the vblank's 37 lines, and work that looks every half frame
    mostly did not.  The instrumented ares, counting the music driver's
    calls frame by frame, had the screens after the list running silent
    for two to seven frames at a time.  Now one HAL routine, `framedue`,
    answers the menus' ticks -- the HAL's (`menutick`), the map edit
    screen's build (`ows_audio`) and its checks (`rando_yield`): has a
    frame begun whose music nobody has played?  (The roll screen's ticks and
    a boss's thinking took it too, and went back to RDNMI, 2026-10-24: the
    roll screen at the user's word -- its missed frames made the tune's
    tempo wander, which the user liked -- and the boss with the game's
    frame waits, below.)  It reads the V
    counter as a phase from the vblank's first line, 225, the lines above
    it pushed past by 512, so NTSC's and PAL's alike count in order, and
    the phase only goes down when a vblank has begun since the last look.
    `h_vframe` counts those, `h_vplayed` is the last frame played
    (`HAL_VARS+$D0`); a look that finds a frame due marks it and takes
    RDNMI's latch, so a wait inside the same vblank waits for the next.
    Every frame wait, before it spins, marks the frame it is about to serve
    as played -- its caller plays that one -- and sets the phase so the
    first look after that vblank counts it however long the wait spun
    (`waitahead`); in the menus `hal_waitvbl` looks again after its flush,
    which can run near a frame.  A game's wait looks at nothing after its
    vblank begins.  At first every wait looked after its flush, 45
    instructions, and a game's dialogue box -- which must reach scanline 9
    after the wait and arrived in line 9 itself, 183 frames of 184 in ares
    -- missed it and waited a whole frame each time: half speed and the
    music with it while a box was open (user, 2026-10-24: "if I open the
    black orb, it plays the treasure sound at a very slow speed").  Now the
    game pays 8 cycles there for the menus' test, and 13 less for the frame
    counter (eight bits and a carry, not a trip to sixteen): its dialogue
    reaches line 9 as it always did, 188 frames of 189, none spun.  It needs
    a look at least once a frame -- one more than a frame after the last
    cannot see the vblank between -- so the long work looks every half
    frame or so:
      - The map edit screen's setup: its VRAM clear in eight pieces (the
        whole a frame and a half of DMA, the CPU stopped), the font every
        32 glyphs, either side of the map, the baked minimap's copy in
        four.  Its loop played each frame's music before
        the wait, the frame before the wait's, and left the last frame
        unplayed as it left for the options; now after the wait's
        transfers (`ows_playframe`), the next wait sending it -- sending it
        there as well clocked the APU's half frames twice, the error
        sound's envelope at double pace.  `ows_wait` ticks first, as the
        HAL's wait does, and a check's tick sends its transfers only in
        vblank as HVBJOY has it: a tick can come in the picture now.
      - `hal_ppureclaim`'s VRAM clear, the way back from that screen: in
        eight pieces, `menutick` before each.
      - `hal_waitvbl` in the menus: a frame whose vblank it will not serve
        -- gone by already, or too late in it to flush -- plays its music
        first if nobody has: party creation's drawing ran past a vblank and
        then waited, and the randomization screen's build, backing out of
        the map edits, came to its wait too late in one.  Not one it will
        serve: a tick there would take the latch, the wait would pass the
        vblank by, and the late-arrival rescue would be lost.
      - `TurnMenuScreenOn` plays the music straight after its wait
        (`optturnonmusic*.patch`, byte-neutral, a ten-byte helper in bank
        `$0E`'s unused space): after party creation's build its wait's
        flush -- the screen's whole CHR and nametable -- ran most of a
        frame, and the music, after the sprites and the palette, came after
        the next vblank, a frame late and then doubled.  Every menu's
        turn-on goes this way now; the register writes are the HAL's
        shadows', so their order with the music is nothing to the picture.
    Measured in ares, the whole flow from the title to party creation and
    back out from the map edits to the title: a call of the music driver
    in every frame, none doubled.  The one gap left is the prologue's
    START, which restarts the game and its track, as the original does.
    The harness: its frame clock (`bus.frames()`) has a V counter now, a
    share of the frame at each look; `Clock` keeps ares's time -- RDNMI's
    latch gone at the vblank's end, the V counter moving with the
    instructions, a DMA and an MVN taking the time they stop the CPU --
    and `test_menumusic` times every menu screen's build with it, one frame
    of the music in every frame (the committed build failed it on four),
    and the reclaim's clear; the wait's three cases; `TurnMenuScreenOn`'s
    order; and both clears whole, whatever VRAM held.  Twenty-nine
    mutations: twenty-four caught at first; of the five, one showed a tick
    redundant -- after the map edit screen's text, 42 instructions before
    the copy's first -- and it went, and four wanted sharper tests: the
    latch a tick takes, `ows_wait`'s tick (the frame-by-frame run now goes
    a frame further), a tick that plays whatever, and the copy's pieces
    against a staging of junk (the test's own setup had laid the right
    minimap there).  All caught now.  After the dialogue box's slowdown
    (2026-10-24, above): measured in ares on a guard's box in Coneria
    Castle, line 9 reached on time 188 frames of 189 and none spun (the
    build before had 102 of 205 spun), and the flow forward and back again
    a call every frame; `test_menumusic` asks that a game's wait reads no
    V counter from its flush on, that its frame is marked for the menus'
    ticks coming on after it (the title's press doubled one before that
    went in), and that the frame counter still carries.  Nine more
    mutations, all caught once the frame-by-frame run went on into the map
    edit screen's own loop and the ticks-on check started from a stale
    count.
  - **Back on the title, its music plays on** rather than starting over
    (user, 2026-10-23).  The title rebuilds after each of its screens
    through `IntroTitlePrepare`, whose `LDA #$41 / STA music_track` started
    the title's track again; its four bytes are a JSL to `opt_titlemusic`
    now (`patches/bank_0E/opttitlemusic.patch`), which leaves the track
    alone when `opt_titlechoose` marked the rebuild (`MENU_KEEPMUSIC`, set
    as it returns to rebuild -- every screen of the title's keeps the
    title's music) and starts it otherwise, the intro's and the title's
    first entry as ever.  `test_menumusic`: the hook on and off and
    without a vblank, everything kept; a long load in pieces, byte for
    byte a whole one's, from a first row's middle; `hal_clearnt` a chance
    at both ends; every menu screen's longest stretch; the title's flags;
    the music left playing on a rebuild and started otherwise.  Fifteen
    mutations: fourteen caught, and the fifteenth showed the pieces' reset
    of Y redundant -- each piece leaves it zero -- so it went.  A reset
    zeroes the flags with `MENURAM`, and leaving for a game is two stores,
    so the soft reset's way to Continue gains nothing.
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
    emulation mode (`cr_frame`).  The text is the game's font, which has the
    dash and the period, plus the crawl's own one-bit glyphs at tiles $01 up
    (`lut_CrawlGlyphs`): the copyright sign, and a colon and a slash for a
    URL (user, 2026-10-19; played the same day: both draw correctly).  The
    credits use the colon ("For the full FFR experience, visit:"), and give
    the site without its scheme, so the slash is unused for now.  `CRLINE`
    writes each as itself.
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
        2026-10-14 New Game builds the cache itself, after placement and
        before party creation (user: one pause, and all the randomization
        done before the party-select screen, which a future class flag will
        need) -- in `rando_newgame`, and since 2026-10-27 in `rando_build`,
        party creation having come before it in between; it silences the
        music first, and the roll screen's end starts the title's again.  `@Begin` then only
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
    kinds, the pane's size and the record format.  **A second chunk,
    `CHUNK_OPTTEXT2 = $1D`** (`src/opttext2.asm`, 2026-11-02), when the
    first filled with Party's sixteen: a row's `lut_DescHi` byte is
    `DESC_SECOND` ($40) over its record's, $C0-$FF where every record's is
    $80-$BF, and `opt_menu_descptr` leaves the record's bank in
    `OPTMENU_DESCBANK` for `opt_menu_desc`.  A DESC_BYVALUE table's records
    are in its own bank.  `check_tables.py` reads both files.
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
  - **CHR goes as a list of words when that is cheaper** (2026-10-17; user:
    forced blank "after the minimap renders as the crests and final fantasy
    logo display").  The HAL kept one dirty span over the CHR shadow, lowest
    write to highest, and the flush sent it whole by DMA.  The minimap draws
    its crests and title a bitplane row a frame for 16 frames each, one byte
    to each of 48 (40) tiles spread across the pattern table: a span of
    tiles $01-$FC, 8034 bytes of 4bpp shadow a frame -- about 47 scanlines
    of DMA against a 37-line vblank -- for 48 bytes that changed; the title's
    6946.  Now `chr_write` also lists each word it writes in `CHRQUEUE` (64
    words at $0D00, `h_chrqn`; one more and the list is given up, as it is
    by `hal_chrload`'s bulk path), and `flush_chr` writes the listed words
    through the port, an address each, when twenty times their count is
    less than the span's bytes -- a word through the port costs about what
    twenty bytes of DMA do.  A crest frame's flush is 706 instructions and
    no DMA, a title frame's 610; a minimap row (32 words in a 512-byte span)
    still goes by DMA.  `test_chrflush` runs crest, title, row, scattered,
    over-full, bulk and bulk-with-a-few frames through the flush with the
    DMAs on and holds VRAM's 16KB of CHR to the shadow after every one, the
    list empty and nothing past it written; and bounds the crest and title
    frames.  Ten mutations; one equivalent kept (an empty list sends the
    span, which only a future writer of the span alone could need).
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
    32-bit accumulator, saturating rather than wrapping -- at $FFFF since
    2026-10-17 (built, not yet played: the user asked to test it later,
    2026-10-18), the sixteen bits the battle prints, divides and awards a
    reward in.  It pegged at $FFFFFF, and over $FFFF the third byte stayed
    in `battlereward` from the gold into `LvlUp_AwardExp`'s two-byte copy of
    the EXP: 65536 EXP to each survivor per 65536 GP (WarMECH at 250% is
    80000 of each).  Only WarMECH reaches the peg at 250%, a dozen fights at
    500%.  And the battle's number printer divided signed (`BMI` in
    `DrawBattle_Division`), so from 42768 a reward printed as one stray
    tile: four Gas Dragons' 50000 GP at 250% (user, 2026-10-17); `BCC`
    now (`btlnumber_unsigned.patch`, byte-neutral).  FFR never meets either:
    its multiplier divides the level requirements and the prices
    (`ExpGoldBoost`, `ScalePrices`), so its rewards stay the vanilla
    game's size.  `test_goldxp` holds the peg, `test_eobreward` the printer
    over the digit boundaries, the old edge and the top of the range.
  - **Enemy and Boss stat scaling** -- `opt_scaleenemies`, FFR's
    `RangeScale`.  Since 2026-10-30 (the plan for the scaling rows, user:
    "scale them just in time") it scales each kind's record in the
    battle's copies once at the load -- HP, absorb, evade, damage, hits,
    hit% and crit% -- and copies every enemy's RAM stats from it, so max HP
    (as a spell lands, and Boss tactics) is scaled too, as FFR's rewritten
    ROM is.  `opt_scaleatk` scaled hits, hit% and crit% at every attack
    until then; it keeps the touch and Weapon Stats.

    **Ranges (2026-10-31; built, not yet played in battle -- the menu
    rows played 2026-11-02).**  Each stat of each kind
    is drawn between its group's range for it (`opt_statrange`: Boss stats
    and Boss HP for the thirteen, Enemy stats and Enemy HP for the rest),
    log-evenly as FFR draws (user: log-scale), by the enemy's roll for that
    stat.  The rolls are the seed's and the enemy's alone (`rando_dice`:
    the enemy id XORed into the seed with `STREAM_DICE`, warmed, seven
    draws, HP's first), drawn into `OPTBTLDICE` as each kind loads and
    never kept, so the dials stay live and decide only what a roll means
    (user, 2026-10-30, "So the cached monster stats would be the base
    stats, and we'd scale them 'just in time'"): a Goblin is the same all
    game, the same seed gives the same Goblins, and a dial changed on the
    title moves every enemy within the new range by the same rolls.  The
    arithmetic (`opt_scalestat`, native mode, 16-bit): the factor is
    lo * (hi/lo)^(u/256) in 4.12 fixed point -- log2(hi/lo) from
    `lut_StatLog` in 1/256ths of an octave, times the roll, its fraction's
    power of two from `lut_StatExp` -- then FFR's adjustment (1 + (s-1)*adj
    above 1, 1 - (1-s)*adj below; adj 1, 1/2 or 1/4, a shift), the value
    times that rounded half to even as C#'s `Math.Round`, and the clamp.
    With hi equal to lo the factor is exactly lo, n/4, so a single value
    scales exactly as the dials did.  Over a range it is FFR's to within
    the grain of a 256-step roll and a 1/256-octave exponent, under 0.3% of
    the factor, where FFR's 32-bit draw is continuous.  A group whose four
    numbers are all 100% is left as it is, as FFR returns early for each
    group (`ScaleEnemyStats`, `ScaleBossStats`) -- which matters only for
    the hits floor: a record of 0 hits stays 0 there, and none in the
    cartridge has.  `test_statscale` holds the ROM's tables and every case
    to `randoref.py`'s `stat_scale`, a single value to FFR's exact rational
    and a range to FFR's floating `RangeScale`; `test_scaleenemies` holds
    each slot's record and RAM stats to `randoref.scale_record` with the
    enemy's `enemy_dice`, HP's range apart from the stats', the clamps, a
    max below its min, and two enemies alike but for their ids
    coming out apart.
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

    BANK_FIXED   219 free    the scarce one; stamped into every chunk.  7
                             declared, and 231 at the end: the randomizer's
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
                             randomizer's rando_coldbuild, gave back 3;
                             the overworld's edits took 12, LoadOWMapRow's
                             JSR and JSL where it ran on into DecompressMap,
                             and CallMinimapDecompress's JSL; Short ToFR's
                             four hooks 14 (the plate, its graphic's id,
                             Garland's outline, the palette)
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
    BANK_0E       36 free    12 declared unused at $BFF4, after House MP took
                             four; 25 NOPs in the old LoadShopInventory;
                             one byte at the end, New Game's party split
                             having taken the other (2026-10-21).
                             Besides: 28 zero bytes after TitleScreen_Music,
                             reachable only by code before the pinned $8500
                             blob (the save view took two), and four NOPs
                             after the title's @OptionChosen
    BANK_OPT    5623 free   the settings screen's engine and rows (6695)
                             moved to BANK_OPTMENU on 2026-10-21; before
                             that it had 140 free once the descriptions
                             moved out, the None, the
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
                             scalar, the pool's rule and walk; its AoE 55
                             more, 2026-10-29), and Thief
                             lockpicking (176: its row, readouts and
                             scalar, opt_lockpick, Thief hit's mask), and
                             Item magic (59: its row, readouts and scalar;
                             opt_itemspell shrank, asking the readers), and
                             Map edits (51: its row, readouts and scalar;
                             removed 2026-10-24),
                             and Short ToFR's row (32; its code went to the
                             randomizer's chunk), and the scaling moved
                             onto the battle's records (101, 2026-10-30),
                             and the scaling's ranges (739: opt_scalestat,
                             its log and exponential tables, 552 of it,
                             opt_statrange; ld65's map read 6449 before
                             them, 2026-10-31), and Party's class cycle
                             (52 more than the None's, 2026-11-02) -- the
                             next feature with much code goes to a chunk
                             of its own, as Boss tactics did; the respond
                             rate's mask at boot 2 (FUN%, 2026-11-03)
    BANK_OPTTEXT   157 free  the settings screen's descriptions (measured
                             2026-10-22, the presets' since; the seed
                             screen's went with its art); Map
                             shuffle's took 376, the Ruse Staff's 115,
                             Boss tactics' three 432, the NUKE Stick's 115,
                             the starting caster item's 115 (236 with
                             AoE's three by value, 2026-10-29), Pirates'
                             three 124 (2026-10-30), the scaling's ranges'
                             three and six pointers 267 (ld65's map read
                             1411 before them, 2026-10-31; 239 once the
                             max rows' text lost a line, 2026-11-01), Thief
                             lockpicking's 115, Item magic's 115, Map
                             edits' three 348 (freed 2026-10-24), Short
                             ToFR's 143, Party's sixteen 1003 (2026-11-02:
                             nearly full; later rows' descriptions go to
                             BANK_OPTTEXT2, Taverns' first; Rebellious
                             Princess's pointers 2, 2026-11-02)
                             (measured 2026-10-14 from
                             ld65's map: the 10788 here before dated from
                             10-09 and was not kept up as descriptions were
                             added)
    BANK_CREDITS 13065 free  the credits screen; mostly its text and tables
    BANK_RANDO     57 free  the randomizer: FULL -- the next feature moves something out
                             (measured with ld65's map, 2026-11-03: Rebellious
                             Princess 576 -- pl_sara, pl_trysara and its
                             helpers, the dialogue swap; its map loading
                             went to BANK_WORLD to fit; 2026-10-28;
                             rando_dice 59, 2026-10-31; Party 259, Taverns 178, 2026-11-02); the Ordeals pillars took 622,
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
                             gear_spellat and the dealt names; Map edits'
                             New Game, BRIDGE and Matoya's dock 68 (the
                             row's part removed 2026-10-24); Short
                             ToFR 485, 110 of it the room; New Game taking
                             the flow's edits and seed 21 + 21; the Seed
                             Summary's numbers and places (pl_summary) 52;
                             the hint lines' lookup 88 (the lines are
                             BANK_WORLD's); the enemy records, Pirates
                             Buffed and Nasty, and the battle's copies
                             352 (2026-10-30), 68 of it back when the
                             RAM-stat copy moved to opt_scaleenemies; Party
                             259 (lut_PartySlots 64, rando_party,
                             party_pick, rando_partyseeded, the surprise
                             mask; 2026-11-02)
    BANK_LOGIC   6011 free  the vanilla world's logic for placement (3714),
                             each map's ship dock (71) and each place's
                             spread group (248), and entrance shuffle's
                             graph (5440), generated; data only; Rebellious
                             Princess's spots 138 (2026-11-03)
    BANK_WORLD   4518 free  (measured 2026-11-03; 5337 on 2026-10-28)
                             Rebellious Princess 819: her lines (dlgsara.inc),
                             her map loading (sara.inc), es_saraspots;
                             entrance shuffle's code
                             (4430): the wiring, the seed's logic, roots,
                             groups, the dock, and the landing tables; the
                             roll screen's yields 40;
                             the overworld's edits 4375 -- every FFR list's
                             writes by row (4230, tools/genowedits.py) and
                             ow_edit; the hint lines and their tables 1388
    BANK_ROLL    8843 free  New Game's roll screen (7541): its code, and
                             38 pictures' resolved frames, colours,
                             effects and voices, the scales and their
                             reach (from tools/genroll.py)
    BANK_TACTICS  7567 free  Boss tactics (8937): gathering, the deck, the threat, the
                             race, the dice's sums, the normal tail, the
                             choice, the arithmetic, and gentactics.py's
                             tables (199 + 3 x 129 words + 81 words);
                             tac_bossatk's 120 freed 2026-10-30
    BANK_NEWGAME 14507 free  New Game's flow: its presets (eight of 90
                             pairs; their names and descriptions are in
                             the engine's chunk and the descriptions'),
                             ngp_apply and ng_flow (measured 2026-10-21)
    BANK_OPTMENU  3131 free  the settings screen's engine (optmenu.asm):
                             its code, the rows and readouts, a chunk of
                             its own since 2026-10-21 so the New Game
                             flow's screens can be more of it, which the
                             seed screen is (3500 with its art: 1536 of
                             tiles, 1024 of nametable; measured
                             2026-10-22); it reaches opt_commit by JSL now;
                             the Seed Summary 1264 (sumscreen.asm,
                             2026-10-27); the scaling's six rows 234
                             (ld65's map read 3904 before them,
                             2026-10-31); min and max held together 102
                             (opt_range_floor and opt_range_push, a
                             listing's count, 2026-11-01); Party 179 (its
                             row, readouts, scalar and opt_needseed's ask,
                             2026-11-02); Taverns' row 86, the second
                             descriptions bank's choice in it (2026-11-02);
                             Rebellious Princess's row 39 (2026-11-03);
                             FUN% and Stereo Sound's rows 135 (2026-11-03)
    BANK_TAVERN  ~14840 free Taverns' visit, hire, level up and look
                             (tavern.asm, ~1540; 2026-11-02)
    BANK_OPTTEXT2 15917 free the descriptions past the first bank's:
                             Taverns' three (~300; 2026-11-02), Rebellious
                             Princess's two (147; 2026-11-03), FUN%'s and
                             Stereo Sound's (114; 2026-11-03)
    HALCODE      6156 free   not available; see below (Stereo Sound's
                             apu_pan 39, 2026-11-03: hardware, a pan
                             register the game sets)

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

  - **The settings screen's scratch lay on four of the derived bytes**
    (found 2026-10-21, building the New Game flow; built, not yet played).
    `OPTMENU_SHPREV`, `_ANY`, `_LEFT` and `_WAS` were at `OPTBLOCK+$1A..$1D`,
    which is `OPTD+$07..$0A`: `OPTD_LINEUP`, `_PALCYC`, `_MSGROWS` and
    `_MSGROWSREV`.  opt_derive writes those only on a commit, and opt_init
    never did, so leaving the screen left them the screen's scratch, in the
    battery, until the next commit -- `OPTD_LINEUP` read 0 after any visit,
    and the lineup's slide steps by it until it passes its mark, so it would
    never end; the others took whatever the visit left (a section of only
    dials, toggled, left the palette cycle's mask 0).  The engine's scratch
    is in `MENURAM` ($7F0800, bank $7F's gap between the credits' and the
    map edit screen's) now, long-addressed, and opt_init cooks the derived
    bytes every boot, which mends a cart still holding a bad step.  Its
    `OPTMENU_PREV` and `_EDGE` had lain on the battle's `OPTBTLSOFT` and
    `OPTDRINKROW` -- scratch on scratch -- and moved too.
    `test_menuscratch`: the screen through every path that writes them, and
    a boot over a poisoned block; five mutations caught.

  - **RDNMI is not "has a vblank begun since I last asked"**
    (2026-10-23/24).  Its latch is set as a vblank begins and cleared when
    read -- and when the vblank ends.  The harness held it set until read,
    so four ticks built on it passed their tests -- the menus', the
    randomizer's yields, the map edit screen's build, a boss's thinking --
    and in ares each fired only when a look happened to land inside the
    vblank: the music stalled frames at a time through the menus.  The
    menus' ticks read the V counter instead (`framedue`), which says it
    at any look less than a frame after the last; the roll screen's and a
    boss's still ask RDNMI (the roll's wandering tempo the user keeps; the
    boss's because counting frames in a game cost the dialogue box its
    frame, entry above).  A harness answering a hardware
    register should answer it as the hardware does, its clearing too; the
    instrumented ares counting the driver's calls frame by frame is what
    showed it.

  - **A test named twice fork-bombed the machine** (2026-10-21).  A second
    `def` of an existing test's name silently replaced it, and the name went
    into `main()`'s tuple a second time; asked for that test, the runner saw
    two, ran each as a process of its own, and each of those did the same --
    a hundred gigabytes, and the laptop went down.  `main()` now refuses a
    test named twice, in the tuple or as two `def`s, and runs tests apart
    only when asked for more than one distinct test.

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
    its four bytes, at every step (the page and the work area both, since
    the work area moved).  Give a multi-byte scratch its own name
    and size, and never put a byte that must survive beside one that is
    merely free.
  - **A routine's width is its caller's, whatever its directives say.**
    (Found 2026-10-22 from the user's report of the seed screen's grid
    drawn "0 1 2 3 / 5 5 7 7 / 9 9 B B / D D F F", now and then, flipping
    between screens; fixed, built, not yet played.)  `hal_ntblit`
    widened the accumulator for a PLB, which takes no width, and called
    `mark_dirty8`, which is `.a8`, sixteen bits wide.  Its `LDA #1`
    took the next instruction's opcode as an operand byte, and the rest ran
    as `ASL $08,X`, X the row: every fast blit since 2026-09-16 shifted the
    zero page word at `$08` plus its row -- `inroom`, `doorppuaddr`,
    `tmp`, the `joy_` catchers -- and its 16-bit compares marked the next
    row dirty from column 0.  Only the menus blit, and `@Begin` clears zero
    page, so a game never saw it; the seed screen did, its row counter in
    `tmp+1` and a seed byte left in `tmp`, whose top bit the shift carried
    in -- one seed in two.  `test_seedscreen` had used one seed, whose low
    byte was $4D.  `test_ntblit` now checks the property instead: a blit
    on every row, both halves, with zero page full of decoys, writes its
    run, its own row's marks and the address, and nothing else; and the
    seed screen's grid is checked over seeds with the top bits set.  When a
    routine is entered by JSR, look at the width at each call site, not at
    the directive above the routine.

