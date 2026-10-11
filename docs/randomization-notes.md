# Randomization on the cartridge -- feasibility notes

Parked exploration, 2026-10-06.  Nothing here is implemented.  It answers
`randomization-concepts.txt`: can the port carry FFR-style shuffles that are
tied to a save rather than to a ROM, and what would each one cost.

Measured against commit 03f5052 and FFR's source in `FF1Randomizer/`.
Byte counts for routines come from an assembler listing of `gen/bank_0F.asm`
and `gen/bank_0E.asm`, not from reading the source.  Companions:
`overworld-notes.md` (the map's storage, RLE and the minimap bug -- not
repeated here) and `options-design.md` (budgets, hook conventions).


## 0. Summary

Everything on the list is feasible.  ROM space (about 800KB unused) and CPU
time (validated placement takes a fraction of a second) are not the limits.
There are two real constraints:

  1. **Hook bytes in the full banks.**  The fixed bank has 7 bytes free, `$0C`
     has 4, `$0E` has 12.  This is solved more easily than it looks, because
     most of these features replace a *whole routine* rather than a branch
     inside one.  Moving the routine out and leaving a `JSL` behind frees
     space.  The chest routine and the three teleport blocks alone return
     about 200 bytes to the fixed bank, more than every hook below costs.
  2. **Correctness of the logic data.**  The placement code is small.  The
     description of the world it reasons over is where seeds become
     unwinnable.  That needs an oracle that is independent of the tables (§4).

Two findings about storage (your two notes):

  - **Low WRAM is full, as you guessed.**  `$0800-$1FFF` is HAL variables,
    the OAM shadow, the HDMA buffers, the decor CHR and the 4KB tilemap
    shadow.  So no generated table can sit at an address every chunk can see.
    Every redirected read becomes a long address (+1 byte at the site) or a
    call into a far routine.
  - **There is room in the save.**  `$603C-$60FC` in the first page of
    `unsram`, 193 bytes, is referenced by nothing.  It is saved,
    checksummed and restored by the game's own code.  See §1.1.

**Architecture, as revised after review 1** (`architecture-feedback-1.txt`).
The save holds the seed, a snapshot of the randomization flags, and the
*result* of the expensive step (where each logic-placed item went).  Every
generated table is cached in WRAM bank `$7F`.  L+X and L+Y soft resets keep
WRAM, so on the reset path Continue only compares the cache's tag against the
save, a few hundred cycles.  Rebuilding happens only after power-on or a
console reset (WRAM is zeroed then), or when the save being continued is not
the world in the cache.  Validated placement runs only at New Game (§1.4).

| feature | hook sites | fixed bank net | WRAM | effort |
|---|---|---|---|---|
| seed, snapshot, regeneration | New Game (existing `opt_freestuff` site), `@Begin` | −4 | tag | medium |
| chest shuffle | `OpenTreasureChest` moved out | **+109** | 256 | low |
| incentive placement | none beyond chests and NPCs | 0 | <1KB | **high** (the logic data) |
| NPC rewards | existing `OptGuillotine` funnel, body moved out | +~30 | ~16 | medium |
| shop shuffle | `LoadShopInventory` (`$0E`, 30 bytes) moved out | 0 (`$0E` +25) | 420 | low |
| magic levels | about 10 sites in `$0C`/`$0E`/fixed | positive if names are moved out | 128 | medium |
| weapon and armour tables | 5 sites | ~0 | 480 | medium |
| trap tiles | the property copy in `LoadSMTilesetData` | +~10 | ~40 | low |
| overworld edits | `LoadOWMapRow` + minimap moved out | +~40 | none | low-medium |
| alternate maps | as edits, plus domain remap and start positions | +~35 | ~100 | medium |
| entrance and floor shuffle | three teleport blocks moved out | **+~90** | ~150 | medium-high |


## 1. Per-save state

### 1.1 Room in the save

The save is `unsram` (`$6000-$63FF`), copied wholesale to `$6400-$67FF` by
`SaveGame` and back by Continue, and summed by `VerifyChecksum`.  Of its four
pages, the last three are spoken for:

  - `ch_stats`, one `$40` page per character
  - `game_flags`, one byte per object and chest id
  - `ch_magicdata`

The spare tail of each character's page is no use.  `LineupMenu_Finalize`
copies whole character pages when the party is rearranged, so per-character
bytes move with the character.

**Page 0 is the room.**  Resolving every symbol in `variables.inc` gives 50
names in page 0, and the last one is `item_stop` at `$603C`.  Every indexed
access was checked for its bound:

  - The chest's `INC items, X` takes an item id below `TCITYPE_WEPSTART`
    (`$1C`).
  - The inventory scan in the fixed bank stops at `item_stop-items`.
  - `opt_sortinv` stops at `$12`.
  - `Talk_ifitem` indexes by item id.

No literal `$603x-$60Fx` and no `unsram+$3C..` appears anywhere in `gen/`,
`src/`, `patches/` or `tools/`.  The only accesses are the whole-page loops:

  - the boot init
  - `SaveGame`
  - Continue's copy

Those loops are exactly what we want: they carry the bytes into the save.

What the bytes hold before anything writes them:

  - **`$603C-$603F` and `$60A0-$60FC` are zero.**  `GameStart` fills page 0
    from `lut_InitUnsramFirstPage` (bank `$00` `$B000`) on every boot,
    before the title screen.  So these 97 bytes are zero on a new game and
    zero in every save ever made by this port.
  - **`$6040-$609F` holds a dead copy of the class starting stats.**  The
    game reads them from ROM at `lut_ClassStartingStats` (`$B040`,
    `bank_0F.asm:1837`), never from here.  These bytes are free, but they
    hold junk rather than zero until something writes them.
  - **`$60FD-$60FF` must not be used.**  In the saved copy they are
    `sram_checksum` and the two assert bytes.  `SaveGame` overwrites them
    after its copy, and Continue copies them back.

Saves made before this feature do not need to survive: the version guard in
§1.5 invalidates them.

The option block at `$6E00` is the wrong place for any of this.  It is
global, and a world must belong to a save.

### 1.2 What goes in it

Every input to the generator has to be in the save.  If a Continue rebuilt
from the *current* settings, changing a menu row would quietly change the
world.  That includes three things that are global today:

  - The **Treasures** "Free X" flags.  They only ever apply to a new game,
    but they are logic inputs: a free CANAL is a pre-owned item.
  - The **overworld variant and edit set**.
  - **Character-creation and growth flags** (Better Thief and Ninja, Thief
    and Ninja Hit%).  Making them per-save also removes the "applies to new
    characters and future levels only" caveat in `options-design.md` §7.

A sketch, at `$60A0`:

    seed         4
    flags       ~12  treasure/NPC/shop/magic/trap modes, edit bitmask (16),
                     map variant, entrance mode, free-item and class bits
    placement  25-60 where the logic placed each item (see below)

That comes to 40-75 bytes of the 93 zero-initialised ones.  The 96 at
`$6040` are there if needed, provided New Game writes all of them.

**What "placement" holds, and loose incentives.**  FFR has two kinds of
item:

  - **Incentive items**: the key items it is told to incentivise, plus any
    incentivised equipment such as the Masamune or the Ribbon.
  - **Incentive locations**: the guaranteed spots, such as NPCs and dungeon
    major chests.

When there are more incentive items than incentive locations,
`PredictivePlacement` moves the surplus, at random, to the "loose" list.
Key items that were never incentivised are loose too.  Loose key items are
*still placed by the logic*, just into the whole location pool instead of the
incentive pool.

So the stored list is simply **every item whose location the placer chose**:

  - incentives in incentive locations
  - loose key items wherever they landed
  - any incentivised equipment the placer pinned

That is 20-35 items.  At 9 bits of location each (there are fewer than 512
locations) it packs into 25-40 bytes; as plain 2-byte entries, 40-70.

Everything else is filler.  Continue and New Game share one path:

  1. pin the stored items
  2. deal the rest of the pool into the remaining locations from the seed

The solver runs only at New Game, before step 1, so Continue never depends
on it.

The menu consequence: the randomization rows describe the **next new game**.
They do not describe the save in the slot, and changing them after Continue
does nothing.  That is a new category for `options-design.md` §7, beside
"fully retroactive" and "applies at creation".  The settings screen should
probably show the loaded save's world settings read-only somewhere, as FFR's
flag string does.

### 1.3 Generated tables

They go in WRAM bank `$7F`.  Two things live there today:

  - `CREDITSRAM`, from `$7F:0000` to about `$04C0` (credits only)
  - `THEENDBUF`, `$7F:6800-$6EFF` (the ending only)

Everything this document proposes fits in a few KB away from both.  The one
thing that would not fit is a 64KB flat copy of the overworld (the WRAM-map
idea in `overworld-notes.md` §6), because it would collide with both.
§9.1 avoids needing it.

Since low WRAM is full, every table read changes form.  An `abs,X` read
becomes `long,X` (+1 byte), or the routine around it moves to the options
chunk.  A `(dp),Y` read becomes `[dp],Y`, which is the same length, but its
pointer needs a third byte.

Moving `NTSHADOW` out of low WRAM to free 4KB was considered and rejected.
The per-byte `$2007` path (`nt_write`, `nt_attr`) runs with the *game's*
data bank and reaches `NTSHADOW` through the low-WRAM mirror.  The attribute
path indexes it with Y, and the 65816 has no `long,Y`.  That path is the
hard-won flicker work; table reads in shops and menus are not, so they take
the long reads instead.

### 1.4 When generation runs, and resets

Generation runs in two places:

  - **New Game.**  Put a generator call next to `opt_freestuff`, which
    already runs at the top of `NewGamePartyGeneration` in bank `$0E` after
    page 0 has been initialised.  That costs no new bytes.  Draw the seed
    there (from the frame counter, or an entered seed), run the full
    validated placement, write the save block, and build the WRAM tables.
  - **Continue.**  The save block arrives with the SRAM copy.  Both paths
    meet at `@Begin` in the fixed bank.  One `JSL` after `ClearZeroPage`
    covers both: if the WRAM tag does not match the unsram block, rebuild.
    That is 4 bytes, paid for by §1.6.

The unsaved state after New Game works by construction.  The new world is in
`unsram` and WRAM, the old save is untouched in SRAM, and a reset followed by
Continue finds a mismatched tag and rebuilds the old world.

**Reset cost: cache everything.**  The resets that matter are L+X and L+Y.
Runners use them to manipulate the encounter index, so they have to stay
instant.  Both go through `OnReset`.  WRAM is untouched (L+Y clears only
zero page), so every generated table survives them.  Continue then costs one
comparison: the WRAM tag against the save's seed, flags and placement, a few
dozen bytes, a few hundred cycles.

A full rebuild happens in only three cases:

  - **The first Continue after power-on, or after the console's reset
    button.**  `hal_reset` DMA-zeroes all 128KB of WRAM, so the tag reads
    zero and cannot match.  This also means the cache never sees random
    power-on contents, because the HAL hands it zeros.  The console-only
    hazard in memory therefore does not arise here, as long as the tag
    includes something non-zero.
  - **Continuing a save that is not the world in the cache.**  For example:
    New Game, no save, reset, Continue the old file.
  - **New Game.**

With the placement stored in the save, a rebuild is the shuffles only.
(Measured 2026-10-09, with every Tier 1 shuffle on: up to ~760K
instructions, about 0.85 s, most of it the formation and enemy-skill deals --
far past the estimate below, which predates them.)  The original estimate,
from instruction counts:

  - Fisher-Yates over ~256 chest contents, about 40K cycles
  - shops, trap tiles and spells together, about 30K more

That is about 20ms at 3.58MHz, slower where it touches WRAM.  Worth
measuring with the profiler before anyone relies on the figure, but it only
runs in the three cases above.

Two rules keep the cache honest:

  - **Write the tag last, and clear it first.**  L+X pressed during
    generation must leave a cache that reads as invalid, not as complete.
  - **Keep the cache clear of `CREDITSRAM` and `THEENDBUF`.**  Both scenes
    run with a save loaded and are left by reset.  `$7F:8000` up is free.

### 1.5 Determinism and versions

The 65816 generator and a Python reference must produce **byte-identical**
tables from the same seed.  So:

  - Specify the PRNG ourselves.  A 32-bit xorshift is a few lines in both
    languages.
  - Draw bounded values by rejection, or by multiply-high on `$4202/$4203`.
    Never use a modulo that differs between implementations.
  - Give each feature its own sub-stream (seed XOR a per-feature constant).
    Then turning shop shuffle on does not reshuffle the trap tiles, and
    each feature can be tested alone.

Seeds will not match FFR's.  FFR uses MT19937 and a different order of
operations, so FFR flag strings and seeds cannot be imported.  The port's
seeds are its own.

**A changed generator is a changed world for every existing save.**  Opened
chests stay opened, because the flags are by location.  But unopened chests,
shops and spell levels would all change, and a learned spell is stored as a
level slot, so a reshuffle would turn a learned FIRE into something else.

**Decision (review 1): fold the version into the save checksum**, with no
version byte in the save.  Continue already falls through to New Game when
`VerifyChecksum` fails, so a version mismatch behaves like a corrupt file.
Existing saves do not need preserving.  The cost is that every bump also
invalidates the playtest saves.

The obvious form does not work.  Replacing `SaveGame`'s `EOR #$FF` with
`EOR #V` gives a data-dependent result, because the sum is an add-with-carry
chain: each carry feeds the next add, which makes it ones'-complement
arithmetic.  Simulated against the real loops, the form that works is:

  - **`SaveGame`** (bank `$0E`): `LDA #$00 / STA sram_checksum` becomes
    `LDA #SAVEVER / STA sram_checksum`.  The byte is preset to the version,
    and the same `A` starts the sum.
  - **`VerifyChecksum`** (fixed bank): `CMP #$FF` becomes `CMP #SAVEK`, with
    `SAVEK = $FF - ((2*SAVEVER) mod 255)` computed by the assembler.  For
    example, V=1 gives `$FD` and V=2 gives `$FB`; V=0 is vanilla.

Both are operand changes, so it is byte-neutral.  Simulated on saves built
from the real SRAM dumps in the repository root, with the proposed `$60A0` block
randomised: under each version tried (V = `$00`, `$01`, `$02`, `$03`, `$10`,
`$7F`, `$80`, `$AA`), every save summed to exactly that version's constant.
Distinct versions have distinct constants, so a save always fails under any
version but its own.  Use `SAVEVER` 1-`$FE`, because `$FF` aliases vanilla.

**A hazard this turned up, in vanilla.**  The game's checksum is not an
identity.  It only works because the **last byte summed, `$67FF`, is always
zero**.  That byte is the unused tail of the fourth character's magic page,
`$63FF` in `unsram`.  Saves with a random last byte fail verification about
half the time (1497 of 3000 simulated).  Nothing writes it today.  Nothing
must, and none of this work goes near it.

### 1.6 Paying for the hooks

Listing sizes of fixed-bank code these features would replace anyway:

    OpenTreasureChest           114 bytes   -> JSL + RTS            +109
    entrance teleport block      41 bytes   -> JSL                   +37
    normal teleport block        38 bytes   -> JSL                   +34
    exit teleport block          23 bytes   -> JSL                   +19
    LoadOWMapRow                 47 bytes   -> JSL + RTS             +42
    GetBattleFormation           39 bytes   (alternate maps only)
    LoadSMTilesetData, the property-copy prologue, ~14 bytes -> JSL  +~10

The routine moved out has to follow two rules already in
`options-design.md`:

  - **It may not `JSR` into a fixed-bank routine that swaps banks.**
    `check_bankswap.py` enforces this.  `OpenTreasureChest` calls
    `LoadPrice`, which swaps to `BANK_ITEMPRICES`, so the far version reads
    `lut_ItemPrices` with a long address instead.
  - **It must leave the program and data banks as its caller expects.**
    Check whether the code after each teleport block relies on bank `$00`
    still being swapped in.  If it does, keep the 5-byte `SwapPRG` at the
    call site.


## 2. Chests

`lut_Treasure` is 256 bytes at bank `$00` `$B100`.  It has exactly **one
read**: `LDA lut_Treasure, X` in `OpenTreasureChest`.  The two chest features
already shipped do not read the table:

  - **Chest Information** keys on `DLGID_TCGET` and reads `dlg_itemid`.
  - **Identify Treasures** works through the dialogue.

Both therefore follow a shuffle with no changes.  The opened flag is
`game_flags,X` by chest id, which is a property of the *location*, so it is
unaffected.

What the table can hold:

  - `$01-$1B`: items
  - `$1C-$43`: weapons
  - `$44-$6B`: armour
  - `$6C-$AF`: gold, through `lut_ItemPrices`

The key-item fanfare is chosen by id (`< item_qty_start`), so it follows the
item without any work.  The tileset tables carry 254 chest tile types.  FFR
lists 255 `TreasureChest` locations, a few marked unused.

**Plain chest shuffle** (permute the contents) needs only the WRAM table and
a +1-byte long read.  **Incentive placement** needs more, because FFR can put
the SHIP, BRIDGE, CANAL, CANOE and AIRSHIP in a chest.  FFR gives them ids
`$E0/$E8/$EC/$F2/$E4`, which are `$E0` plus the unsram offset of the byte to
set (`ship_vis`, `bridge_vis`, ...).  That is a neat trick and ports
directly.  Spells never appear in chests, so the overlap with spell item ids
is harmless in the table.

That is why the right move is to take all of `OpenTreasureChest` out (+109
bytes to the fixed bank) rather than patch it.  The far version handles all
of these:

  - pseudo-items
  - weapons and armour through `FindEmptyWeaponSlot`/`FindEmptyArmorSlot`,
    which do not swap banks
  - gold, with prices read long

The pseudo-items need **names**.  The chest message prints `dlg_itemid`
through the item-name table, and there is no "SHIP" in it.  That needs a
small name table in the options chunk and a hook in the item-name lookup.
The lookup is wanted anyway for magic (§6) and blursings (§7), so it is
built once and serves all three.

**Built and played (Tier 1 item 3): the plain shuffle only.**  `OpenTreasureChest`'s one
read became a `JSL rando_chest`, one byte more than the `LDA abs,X`.  Moving
the whole routine out waits for Tier 2's pseudo-items, which are what need
it.

  - **Which chests:** FFR's 241 that are not marked `isUnused`.  Decoding
    the 61 maps shows these are exactly the chest ids some map places.  The
    14 unused ones and id 0 hold items nobody can reach, a Zeus Gauntlet
    among them, and stay out of the pool.
  - **Key items stay:** TNT, CROWN, RUBY, FLOATER, TAIL, SLAB and ADAMANT, one
    chest each.  The other 234 trade contents, gold included.  This is FFR's
    filler step: after placing key items, it shuffles the rest of the pool
    onto the remaining locations, and here the key items are pinned rather
    than placed.
  - **Not ported:** BetterTrapChests, OpenChestsInOrder and the treasure
    generators.  Each is its own FFR flag.
  - **Cost:** a rebuild with all three Tier 1 features on is up to about
    118K instructions, once per world change, on the first map load.


## 3. NPC rewards

FFR's model has two kinds of reward source:

  - **13 NPCs.**  King (bridge), Princess (lute), Bikke (ship), Elf Prince
    (key), Astos (crystal), Matoya (herb), Sarda (rod), Canoe Sage (canoe),
    CubeBot (cube), Fairy (oxyale), Lefein (chime), Nerrick (canal), Smith
    (Xcalber).
  - **The Caravan's shop slot** (bottle).  That one is a shop entry and
    belongs to §5.

In the port's bank `$0E`, each reward is hard-coded in its talk routine: an
`INC item_x`, `INC ship_vis`, `STA canal_vis` or `INC has_canoe`.  The
routines run 16-49 bytes each.  Patching each grant would cost a byte or more
per routine, 13 times, in a bank with 12 free.

**No new site is needed.**  Every talk dispatch already ends in
`JMP OptGuillotine`.  At that point `tmp+6/7` holds the handler pointer and
`X` still indexes the map object.  That funnel is about 40 bytes of the
fixed bank, and it currently substitutes only `Talk_norm`.

The change is to move its body out:

    JSL opt_talk        ; Guillotine's test, plus the reward NPCs
    BCC :+
    RTS                 ; handled far: A = dialogue id, as a handler returns
:   JMP (tmp+6)         ; otherwise dispatch as now, possibly redirected

That is 10 bytes where 40 were, so about 30 are freed.  When NPC shuffle is
on and the object is a reward NPC, `opt_talk` runs the generic routine
itself and returns the dialogue id.  The vanilla handlers stay for vanilla
play.

The generic routine is FFR's design (`asm/11_8200_TalkRoutines.asm`): give
on event, give on item, trade item.  The parameters are a per-NPC entry in
the WRAM table: the reward and the required item.

Two points to settle in the design:

  - **"Already given" can no longer be "has the item".**  The Princess
    checks for the LUTE, but with shuffle she may be holding the SHIP.  The
    object's own event bit in `game_flags` is the right record, and it is
    already in the save.
  - **Dialogue.**  Decoded, 11 of the 12 vanilla reward lines name their
    item: "Take my SHIP.", "This LUTE has been passed down...", "...give
    you the mystic KEY."  The other is Sarda's, whose ROD mention is on the
    line FFR replaces.  So appending "Received X" under them would
    contradict them; the line has to be *replaced*.  FFR replaces 12 lines
    (`Dialogues.cs`, `UpdateNPCDialogues`), each ending in "Received #",
    where `#` is control code `$02`, `dlg_itemid`'s name.
    Bank `$0A` has no room for alternates.  The dialogue text runs to
    `$B485`, and there is no free run of 32 bytes anywhere in the bank.
    **Recommendation: draw the replacement from the options chunk.**  The
    machinery exists.  `opt_chestinfo` already builds text into `OPTDESC`
    (SRAM, visible from every chunk) and hands it to
    `DrawDialogueString_PtrLoaded`.  It also already solved the
    `cur_bank`/`$02` trap.  The one difference is that it runs *after* the
    vanilla string.  A replacement needs either a hook a few instructions
    earlier in `DrawDialogueBox`, or a vanilla dialogue id with empty text to
    stand in.  The twelve lines live in the options chunk, at about 70 bytes
    each in plain text.

The far routine reaches `CheckGameEventFlag`, `HideThisMapObject` and the
battle starters through `CALL0E`.  Bikke and Astos combine a reward with a
fight and a hide, so their scripts are reproduced, not generalised.


## 4. Placement and validation

### 4.1 The model

FFR's `PredictivePlacement` places items against `SCLogic`.  Each reward
source carries a set of requirement masks, where `SCRequirements` is a 20-bit
flag word: Lute, Crown, Key, Ruby, Rod, Chime, Cube, Oxyale, Orbs, TNT,
Canoe, Floater, Bridge, Canal, Bottle, Crystal, Herb, Adamant, Slab, Ship.
That fits the 65816 well: three bytes, compared with `AND`/`CMP`.

Your graph framing is the general form, and the right one for the cart,
because it is the only form that survives entrance shuffle.  Three tables in
ROM per world variant:

**Nodes.**  At most 256, so the reached set is a 32-byte bitmap and a node
id a byte.  (This said 128 and 16 bytes.  Vanilla already prunes to 161, and
only by using its own wiring; kept without knowing the wiring it is 182 --
§9.3.)

  - overworld regions, roughly 25 for vanilla (separated by water, river,
    mountain and desert)
  - dungeon sections split at gates: Earth below the rod plate, the
    ToFR floors below the lute plate, Ordeals above 1F, the Coneria and
    Elfland treasuries and the Marsh locked rooms behind the KEY, Mirage
    inside the CHIME, Sky behind the CUBE, the Sea Shrine behind the OXYALE,
    Titan's Tunnel behind the RUBY

**Edges.**  `(from, to, requirement index)`, about 250 of them at 3 bytes
each.  Requirements are indices into a table of distinct masks, a few dozen
at 3 bytes each.  Vehicles become requirements:

  - dock pairs need SHIP
  - river edges need CANOE
  - airship edges need FLOATER plus reaching the desert, and connect only
    to landable regions
  - the bridge and canal edges need BRIDGE and CANAL

**Locations.**  About 270 of them, as `(node, kind, id)`:

  - 255 chests
  - 13 NPCs
  - the caravan slot
  - a few **events**, pre-placed items at fixed locations: Lich gives the
    Earth orb, which the Canoe Sage requires; the Vampire, Kary, Kraken,
    Tiamat

Three properties fall out of this and keep the cart code tiny:

  - **Map-edit flags and Free-X flags are just pre-owned items.**  An edit
    that adds a river is an edge whose requirement is `EDIT_x`.  A free
    CANAL starts the search owning CANAL.  No table per combination of the
    16 edit flags.
  - **Entrance and floor shuffle is a rewrite of edge endpoints** -- for
    reachability.  It also needs the way back modelled and its invariants
    checked per seed; §9.3 has what that takes.  Each
    overworld entrance edge points at the map node its permuted destination
    names.
  - **Incentive rules are a location mask.**  Key items go only to locations
    in the "incentive" set, which is a 270-bit bitmap.

### 4.2 The algorithm

Assumed fill guarantees a beatable result whenever the item set is
consistent, with no retry loop for winnability:

    shuffle the progression items
    for each item, popped in turn:
        assumed = start | free items | every item not yet popped
        R = reach(assumed)  -- BFS, then add the items already placed at
                               reached locations, repeat to fixpoint
        place the item at a random empty eligible location in R
    shuffle the filler into the remaining locations
    verify: forward sweep from start reaches the Chaos node

The cost depends on `reach()`.  One BFS over 250 edges is about 15K cycles.
A naive fixpoint repeats the BFS 3-6 times.  An incremental one keeps a list
of blocked edges and retries only those when the owned mask grows, about 25K
cycles per placement.  Over 25 progression items, plus the verify sweep,
that is **0.15-0.6 seconds at 3.58MHz**.  That is fine once per New Game,
and with the placement stored in the save it never runs on Continue.

RAM: the masks, a 32-byte bitmap, a 256-byte worklist and a candidate list,
all under 1KB.  ROM: about 2KB of logic per world variant.

**For FFR's feel, port `PredictivePlacement` itself, not just its
guarantee** (review 1: preserve FFR's feel within a self-contained cart).
Its tuning is what makes a seed play like an FFR seed:

  - item weights: bridge 0.75, or 2.0 on the vanilla map; floater 0.25
  - minimum cycles: floater not before cycle 10, cube not before 7
  - minimum accessibility: the oxyale only once 50 sources are reachable,
    the cube 75, the chime 60
  - safe and critical counts of incentive locations

It is a forward fill.  Each cycle needs one reachability pass, the same
primitive as above, so the cost is about the same.  Unlike assumed fill it
can fail and retry: FFR allows three attempts and three outer retries.  The
retries happen only at New Game, because the result is stored.  Assumed fill
stays useful as the oracle's cross-check: a second, simpler placer whose
beatability verdict must agree.

### 4.3 The precomputed alternative

Run placement offline and store N results per world variant.  For example,
4096 placements × 32 bytes is 128KB.  The cart then only picks one.  It
removes the on-cart solver entirely and is a fine first phase.  The cost is
that every combination of edit flags, free items and entrance mode needs its
own pool, which is exactly what the on-cart graph avoids.  Since the solver
is cheap, precomputation is the fallback, not the plan.

### 4.4 Verifying it

The danger is the logic tables, not the solver.  The rule from
`tests-that-encode-the-bug` applies directly: a reference implementation
written from the same tables will agree with the cart about a missing edge.
So there are three layers:

  1. **Differential, cart against Python.**  The same seeds produce
     byte-identical tables.  `tools/cpu65816.py` and `test_options.py`
     already run real 65816 code against the built ROM.  A generation run of
     a few hundred thousand cycles takes well under a second there, so
     thousands of seeds are a minutes-long test.
  2. **An independent oracle for the tables.**  A Python walker over the
     *actual tile data* answers "can the party reach chest k with items S"
     without the node and edge tables:
       - the overworld rows from `bank_01`
       - the standard maps from banks `$04-$07`
       - tile properties from `lut_OWTileset` and `lut_SMTilesetProp`
       - the teleport tables
     This is what FFR's `SanityCheckerV2` does.  Disagreements between it
     and the graph are bugs in the graph.
  3. **FFR itself as a third opinion.**  Its C# is in the tree.  Dumping
     `SCLogic`'s requirement sets for the vanilla world and diffing them
     against the graph's derived requirements is cheap insurance, and
     `SCLogic` already knows about every edit flag.

Then mutation testing as usual.  Delete one edge and confirm the oracle
catches seeds that relied on it.

### 4.5 Prototype: `worldgraph/` (vanilla)

Built from the tiles, per the rules above (`worldgraph/README.md`).  On the
vanilla world:

  - **Winnable in 22 spheres, in the familiar order.**
  - **All 260 locations match FFR's hand-kept requirements exactly**, as
    minimal requirement sets: every chest, NPC reward, altar, the caravan
    and Chaos.
  - **Pruned, the graph is 161 nodes, 287 edges and 26 distinct masks**,
    about 1.3KB of tables.
  - **`selftest.py` proves the check bites.**  Breaking the KEY, RUBY,
    CANAL or CROWN rule produces 5 to 40 disagreements each.

One design consequence surfaced.  FFR reads **SHIP as "can board it"**,
because it spawns the ship at whichever of five inner-sea docks is nearest
the location that gave it (`ItemLocations.ShipLocations`).  Read literally,
the ship waits at Pravoka and everything by sea also needs the way there.
**A shuffled cart needs that spawn table**, or a SHIP found in Coneria strands
the ship.  FFR's "AIRSHIP flies from anywhere" is safe as it stands, since
raising the airship already puts the party where it waits.

### 4.6 Prototype: entrance and floor shuffle, and placement (2026-10-11)

`worldgraph/` now builds its graph from a *wiring* -- the three teleport
tables, vanilla or shuffled (`wiring.py`) -- with the warp-back and
vehicle-return edges kept apart from the graph's own (`build.py`), and
checks a wiring the way §9.3 asks (`fecheck.py`; `fe_selftest.py` shows
each check biting).  `wiring.fe_shuffle` ports FFR's
`ShuffleEntrancesAndFloors` onto FFR's own destination records
(`ffr_teleports.py`, read from its source and checked against the ROM's
tables: all agree but `IceCave6`'s coordinate, which FFR also overwrites
from the ROM).  `placement.py` ports `PredictivePlacement`: FFR's bins,
weights, minimum cycles and accessibility, with a uniform location draw
where FFR has its balanced picker.

Over 200 seeds (`run_fe.py 200 --place`, 19 s under PyPy):

  - **every seed places on the first attempt, is winnable, and reaches
    every location** with everything owned
  - **no seed strands the party at any sphere of its own playthrough**:
    assumed fill's premise, that a region once reached stays reachable,
    holds under FFR's shuffle once warps are edges back to the caller
  - seeds run 6-14 spheres, against vanilla's 22
  - nesting: 187 stay at vanilla's 11 levels; the deepest reaches 19, one
    short of where the stack fix starts forgetting
  - Titan's Tunnel opens new ground in 97 (§9.3)

**The incentive pool decides whether placement works at all.**  With all
twenty key items incentivised into FFR's default incentive locations -- the
13 NPCs, the caravan and the eight "Major" chests, 22 in all -- placement
fails two seeds in three.  That is the pool, not the port: with the vehicles
and the BOTTLE loose it is 200 out of 200, and everything loose likewise.
The prototype defaults to that until the incentive options are chosen
(§12).

**Cost on the cart.**  One placement does about 280 reachability fixpoints
-- 1,100 BFS passes and 85,000 edge relaxations at the median, 150,000 at
worst -- plus a scan of the locations on every pass.  Naively on the 65816
that is several seconds (rough: 40 cycles an edge, 30 a location test).  So
incremental reach and per-node location lists, as §4.2 proposes, and
**placement stored in the save, not regenerated at power-on**: one pool
index per item, 20 bytes, since the pool is 248 locations.  The wiring is
cheap to regenerate from the seed, or about 70 bytes to store.

**Against FFR's own output (2026-10-11).**  FFR's command-line tool now
builds here (.NET 10; `dotnet build FF1R -c Release -p:NuGetAudit=false`,
since the project treats NuGet's ImageSharp advisory as an error), and
`worldgraph/run_ffr_fe.py` generates ROMs from the original game
(`../ff1e.nes`, outside the repository and to stay so), reads each one's
teleport tables and overworld back (`ffr_rom.py`), and checks them beside
the port's shuffles run with the same preset's settings.  Over 50 seeds of
FFR's Entrance and Floor Shuffle preset:

  - neither strands the party, shares a landing, or deals a floor without a
    warp back
  - entrances moved: FFR 19-22, port 20-22 (the preset leaves towns alone);
    teleports moved: FFR 32-35, port 29-33, the difference being FFR's
    `OrdealsPillars` rearranging the Ordeals maze, a separate flag
  - Titan's Tunnel opens new ground in 51% of FFR's seeds and 49% of the
    port's (400 seeds)
  - **FFR itself fails some seeds**: one of the 50 died in placement ("could
    not meet incentivization requirements"; its command line tool does not
    retry), and the shuffle's 100-try sanity loop gives up on about one seed
    in 400 under these settings -- in FFR and the port alike.  The cart must
    re-roll rather than fail.

Not yet: FFR's ship-spawn table (the ship appears in the inner sea once
found, as `run_vanilla.py` reads it), its balanced location picker, and a
comparison of placement, which needs FFR's NPC rewards read back as well as
its chests.

## 5. Shops

`lut_ShopData` (`$0E` `$8300`) is a pointer table and zero-terminated lists.
It has **one read**: `LoadShopInventory`, 30 bytes in bank `$0E`, which
copies five bytes into `item_box`.  Shop Information and everything else
downstream read `item_box`.

The pools, measured from the data:

    weapon   23 entries in 6 shops      white magic  32 in 10
    armour   25 entries in 6 shops      black magic  32 in 10
    item     25 entries in 6 shops      caravan       1 (the bottle)

FFR's `ShuffleShopType` pools a type and deals the entries back out:

  - every shop gets at least one
  - no shop gets more than five
  - no duplicates within a shop
  - optionally PURE and SOFT in the first town's item shop

Shop sizes change, so this wants a table rather than an on-the-fly
permutation.  70 shops × 6 bytes = 420 bytes of WRAM.  `LoadShopInventory`
becomes a `JSL` and an `RTS`, and the far side copies from the table.  That
frees about 25 bytes in `$0E`.  Clinic and inn "inventories" are prices; the
table carries them unchanged.

Doing the shuffle at display time in the shop code, as the concepts file
suggests, also works for weapons, armour and items.  But it gains nothing
over the table, and it cannot express FFR's size changes.

**Magic shops** are left out: see §6.3.  Level shuffle does not touch the
shop data at all, because the shops sell slots.

**Built and played (Tier 1 item 2).**  Implementation corrected four things above:

  - **The Caravan is an item shop to FFR.**  Its pool is 26 entries in 7
    shops, the BOTTLE included, so the BOTTLE can land in any town and the
    Caravan can sell anything.  It stays winnable without logic: the fairy is
    at Gaia, which needs the airship, and by then every item shop is in reach.
  - **FFR keeps the Caravan open for good** (`PermanentCaravan`, an
    unconditional global hack over the fairy check in `OWCanMove`).  Here it
    is `rando_caravan`, applied only when the save's shops are shuffled.
  - **PURE and SOFT in Coneria is not a flag.**  FFR computes
    `ImmediatePureAndSoftRequired` from status-touch changes, entrance shuffle
    and Enemizer.  It is not ported until one of those is.  When it is, its
    reshuffle of that shop comes with it.
  - **FFR's shop index is the game's `shop_id` minus one**: its pointer table
    starts at `$8302`.  The Caravan is `shop_id` 70.

The cache is 71 rows of 8 bytes at `$7F:9000`.  Each row is the 5 bytes
`LoadShopInventory` used to copy, junk after the terminator included, so
with shops off `item_box` is unchanged, inns' and clinics' prices too.  A
type restarts its deal in about one item deal in 750, never more than once in
20,000 seeds, and never for weapons or armor.  So the retry is unbounded, as
FFR's is.


## 6. Shuffle Magic Levels

### 6.1 Why it is the expensive one

A spell's index *is* its level.  The level determines three things:

  - which MP pool a cast spends
  - which of the three per-level slots in `ch_spells` it occupies
  - which shop sells it

FFR permutes the index space wholesale: records, names, battle-message
pointers and permissions all move.  It then fixes every place in the ROM
that names a spell by its *vanilla* identity:

  - enemy AI spell lists
  - the weapon and armour cast byte
  - the 13-entry out-of-battle table
  - the confused enemy's FIRE

Shops are left alone, which is what "not which level is sold where" means.

The port has to do the same thing at runtime, as a 64-byte permutation and
its inverse.  The data-carrying reads look up through the permutation.  The
identity-carrying reads go through the inverse.

### 6.2 Sites

| site | bank | cost |
|---|---|---|
| battle record pointer | `$0C`, through the existing `OptMagicData` hook | 0 |
| record at target selection | the existing `OptMagicTarget` | 0 |
| `GetPointerToMagicData` (one caller) | `$0C` | routine moved out, frees bytes |
| spell names, all screens | five item-name lookups in the fixed bank: four menu paths and the battle attack-name printer | moved to one far routine, frees bytes |
| battle message pointer | `$0C` | 1 site |
| learn permission | `$0E`, `lut_MagicPermisPtr` | 1 site |
| out-of-battle dispatch (13 `CMP`s) | `$0E` | the chain moved out, frees bytes |
| enemy AI spell id | `$0C`, at `lut_EnemyAi` | 1 site |
| equipment cast | `$0C` | 1-2 sites |
| confused FIRE (`LDA #MG_FIRE-MG_START`) | `$0C` | +1 byte |
| Shop Information, `opt_spelloverride`, Cast Life's spell tests | options chunk | free, but must ask by identity |

The groundwork already exists.  `opt_magicdata` copies every cast's record
into `OPTMAGSHADOW` and asks `opt_spelloverride`, field by field, whether a
flag replaces it.  The shop asks the same rule, and the result is that "the
box and the spell that gets cast cannot drift apart."  Level shuffle is one
more question at the top of that path: which record.

**A latent bug becomes live.**  The out-of-battle dispatch builds the spell
id with `ORA` where it needed `ADC`.  Disch's comment documents it: the 8th
spell of a level collides with the next level.  It is harmless in vanilla
only because every 8th spell is black and none is castable out of battle.
Level shuffle, and especially FFR's "mixed spellbooks", breaks that
assumption.  The far dispatcher fixes it in passing.

**Risk** is in the permutation plumbing, not the spells.  Correction from
review 1: the spell work has had a full round of play, and only one or two
oddball spells were not exercised.  An earlier draft overstated this from a
stale memory note.

### 6.2a Built and played (Tier 1 item 4): redirect at the player's slot, not FFR's model

§6.1 and §6.2 assumed FFR's model: permute the tables, then mend every
reader that names a spell by identity.  Built, the port does the reverse.
Nothing moves.  The cache holds the spell in each slot and the inverse
(`RW_PERM`, `RW_INV`), and a slot becomes its spell only where a
character's slot turns into one.  Everything downstream sees the spell
itself, as vanilla does: records, battle messages, enemy AI, the equipment
cast byte, confused FIRE, Spell Fixes, Cast Life, LOCK/LOK2 and the Improved
spells.  Those §6.2 sites need nothing.  The sites that do:

  - `ConvertOBStatsToIB`/`ConvertIBStatsToOB` (bank `$0B`, byte-neutral):
    the battle's spell list becomes spells at battle start, and slots again
    at the end, through the inverse.
  - The out-of-battle dispatch (bank `$0E`, byte-neutral).  It also mends the
    `ORA` bug, and makes an empty slot "can't cast", where it used to compute
    the previous level's 8th spell, which could now be WARP.
  - Names: the magic menu's list builder (fixed bank, +1 byte), and the
    magic shops' own list string, `ShopSelectBuyMagic` (bank `$0E`,
    byte-neutral).  The shop string carries the item id twice, once for the
    name and once for the price.  Only the name's becomes the spell's, and
    the level shown is read from the price's.  Not at the generic item-name
    path: Shop Information's "Cast X" line on gear goes through it carrying
    an identity.  (A first try hooked `DrawItemBox`, the item menu's box; no
    magic shop goes through it.)
  - `opt_descgear`'s spell branch, for Shop and Magic Information.

Stays with the slot, as FFR's presets have it: MP (the level), price and shop,
and learning permission (`MagicPermissions` is off in all 30 FFR presets).
Tiered and mixed books are left out, also off in every preset.

### 6.3 Why level shuffle and not shop shuffle

Decision from review 1: no magic *shop* shuffle.  FFR's `ShuffleMagicShops`
shuffles spells across shops of a type regardless of level.  That puts
level-8 spells in Coneria, which you can neither afford nor cast, and that
stonewalls the run.  Level shuffle is the reverse, and the version worth
having.  `ShuffleMagicLevels` leaves `lut_ItemPrices` alone, and the price is
by item id, which is the slot.  So when NUKE, FADE, LIF2, TMPR or FAST lands
in a level-1 slot, Coneria sells it at a level-1 price and it casts from the
level-1 MP pool.  FFR's "tiered" variant (`MagicLevelsTiered`) biases each
spell toward its original tier, if that is ever too wild.


## 7. Weapon and armour tables, and blursings

The "tables, not shop code" approach the concepts file prefers is the right
one.  Once the stats come from a WRAM copy:

  - shop shuffle, random wares and blursings are all edits to data
  - Shop Information and the chest descriptions follow automatically, as
    long as they read the same copy

Read sites:

  - **Battle, bank `$0C`.**  `GetPointerToWeaponData` has two callers (the
    stat load, and using an item); `GetPointerToArmorData` has one.  Both
    return a pointer that the caller reads `(ptr),Y` with `DBR` in `$0C`.
  - **Out of battle, the fixed bank.**  The two equip-stat adjusters compute
    `(tmp)` inline from `#>lut_Weapons`/`#>lut_Armor`.
  - **The options chunk.**  Three `f:lut_WeaponData`/`f:lut_ArmorData`
    reads in `optshop.asm`.  These are already long and just change address.

The cheapest redirection is the **shadow record**, the pattern
`opt_magicdata` already uses.  The far routine copies the record from WRAM
into a buffer every chunk can see and returns a pointer to it.  The two
`GetPointerTo*` routines become `JSL`/`RTS`.  Each check needs one fact
verified: no caller holds two equipment pointers at once.  The battle stat
load walks one weapon at a time; confirm the rest when it is built.

The save already has the hook this needs.  `ch_substats` is a cached
derivation inside the save, and the port **already re-runs the
equipment-stat recompute after Continue** (`options-design.md` §7).  So
blursed stats that are regenerated from the seed stay consistent with the
cache.

**Names.**  FFR marks a blursed item by renaming it ("Long+2").  The item-name
lookup moved out in §6 can append a suffix into a scratch buffer.  The font
already has the `+` at `$C1`.  `sweep-synthetic-records` is the test
discipline for the description boxes, and it was written for exactly this
phase.


**Blursings built and played (Tier 1 item 4b).**  Two value rows, Max gear blessing (0
to +5) and Min gear curse (0 to -5).  Each weapon and armour rolls from
[-curse, +blessing], so a plain piece is always possible.  That deliberately
narrows FFR, whose sliders allow a range without zero; the user's design.  The
stat rules and the renaming are FFR's (`RandomWeaponBonus`,
`RandomArmorBonus`).  Left out: Exclude Masamune, and the
`CleanBlursedEquipmentNames` preference.

  - **Stats.**  The record-pointer setups in `UnadjustEquipStats` and
    `ReadjustEquipStats` (four sites, fixed bank, each shorter now) call
    `rando_weaprec`/`rando_armrec`.  These copy the blursed record into
    `OPTGEARSHADOW` and point `(tmp)` at it.  That shadow and the name buffer
    are in SRAM, because the game's banks see SRAM and not WRAM above $2000.
    `opt_weapbyte`/`opt_armbyte` read the copy for crit and the descriptions.
    Battle needs nothing: it takes damage, hit, absorb and evade from the
    character's substats, and crit from `opt_weapcrit`.
  - **Names, four readers:** the menu text's `$02` (shop and sell lists), the
    dialogue's `$02` (chest messages), the equip menu, and the tail of
    `BattleDrawLoadSubSrcPtr`.  The last tells the item table from the others
    by bank and address.  All four ask `rando_nameptr`, which returns the
    ROM's pointer or `OPTNAMEBUF`.  It consults the cache, and so builds it,
    only for gear: class names come through the same lookup on the party
    creation screen, before `@Begin` has built anything.
  - The shadow-record question in the paragraph above, whether any caller
    holds two equipment pointers at once, did not arise.  Each adjuster reads
    one record and is done with it.

## 8. Trap tiles

Spiked tiles are tile *types*: property byte 1 holds `TP_SPEC_BATTLE` and
byte 2 holds a formation below `$80`.  `$80` and up means a random encounter.
The tileset property table holds **43** of them across six of the eight
tilesets.  FFR's `IsNonBossTrapTile` excludes formation 0 and the boss range
`$73-$7F`, leaving **34** by property.

Decoding all 61 standard maps (each comes out at exactly 4096 tiles) shows
that only **34 of the 43 types are placed in any map**.  The intersection
with FFR's rule is **30**.  Four of FFR's 34 are never placed:

  - tileset 3 tile 66 (`$2E`)
  - tileset 4 tile 29 (`$50`)
  - tileset 5 tiles 82 and 84 (`$04`, `$10`)

So FFR's shuffle can move a formation onto a tile nobody walks on, and it
disappears from the game.  Whether to shuffle the 30 placed ones or FFR's
34 is invisible in play either way.  Under the feel principle the default is
FFR's 34, for parity.

`LoadSMTilesetData` copies the tileset's 256 property bytes into
`tileset_prop` on every map load.  So this is the "rescale at an existing
ROM-to-RAM copy" pattern from `analysis.md`.  Replace the property-copy
prologue with one `JSL` that does the copy from bank `$00` with long reads,
substituting the shuffled formations from a WRAM list as it goes.  It leaves
`tmp+2/3` where `Copy256` would have, for the TSA copies that follow.  That
saves about 10 bytes of fixed bank.  It is safe to toggle because the
properties reload on every map entry.

FFR's other modes (A-side, B-side, curated, random) take from a formation
list rather than permuting.

**B-sides.**  FFR's `UpdateTrapTilesCode` uses a one-byte trick:

  - `SMMove_Battle`'s `BPL @Spiked` becomes `BNE` (`$10` to `$D0`).
  - Every random-encounter tile's `$80` is rewritten to `$00`.

Then zero means random, and any non-zero byte is a full formation id, with
`$80` and up the B-side.  Here:

  - The branch is an opcode change in the fixed bank, so byte-neutral.  It
    has to be unconditional.
  - The re-encoding is free, because the property-copy hook above already
    rewrites these bytes on every map load.  It just has to run for vanilla
    play too.

The only vanilla behaviour `BNE` could change is a trap with formation 0,
which would turn into a random tile.  There are five such tile types, and
none is placed in any map.  So vanilla play is unchanged.


## 9. The overworld

### 9.1 Preset edits

FFR's edits, counted from `OverworldMapEdits.cs` (tiles written, rows
touched):

    OnracDock             7  (3)     BridgeToLefein       36 (10)
    MirageDock            4  (2)     HighwayToOrdeals     28  (8)
    AirshipDock           4  (2)     RiverToMelmond       60  (8)
    ConeriaToDwarves     13  (4)     SardasForest        117 (21)
    VolcanoIceRiver       9  (3)     AirshipHike          11  (4)
    CanalSoftLockMountain 6  (2)     GaiaMountainPass     46 (15)
    DwarvesNorthwestGrass 3  (1)     GaiaDrydock          11  (3)
    BahamutCardiaDock     9  (3)     CardiaLandBridge    549 (44)
    LefeinRiverDock      14  (5)     ...BahamutDock         2  (1)

With every compatible edit on, that is 926 tile writes over 98 rows, at
most 34 in any one row.  It is under 3KB as `(x, y, tile)`, and less as runs
per row.  **Space is a non-issue.**  `MapOpenProgression` is VolcanoIceRiver
plus ConeriaToDwarves.

**Overlaps (review 1).**  Only the Cardia group writes the same tiles twice:

  - **BahamutCardiaDock and CardiaLandBridge** share 9 tiles, all with
    different values.  FFR never applies both: the dock edit is gated
    `&& !MapCardiaLandBridge`.
  - **CardiaLandBridgeBahamutDock** overwrites 2 of the land bridge's tiles.
    It is a modifier applied after it.

No other pair of lists shares a tile or even touches one diagonally.  But 35
rows are touched by two or three lists.  For example, CardiaLandBridge and
GaiaMountainPass share 12 rows without sharing a tile.  So the edits are
independent per tile but not per row, and the order of application only
matters inside the Cardia group.

**How the map is stored (review 1).**  By full-width rows, not rectangles:

  - 256 rows, each the whole 256-tile width.
  - Each row is RLE-compressed on its own.
  - A 512-byte table holds one pointer per row.
  - In RAM, a window of 16 full-width rows sits at `$7000-$7FFF`, slot
    `row & 15`.

`LoadOWMapRow` has one call site, in the vertical branch of the map-move
code.  So:

  - each north or south step decompresses one new row
  - east and west steps decompress nothing, since the window already holds
    the full width
  - entering the overworld fills the window, 16 rows

Standard maps (64×64) decompress whole on entry.

Mechanism: the bridge and canal are no precedent here.  They are **sprites**
(`DrawOWObj_BridgeCanal`) plus a collision override (`IsOnBridge` and
`IsOnCanal`), not map tiles.  There are two ways to put edits in the map:

  - **(a) A 64KB WRAM copy of the map with the edits applied**
    (`overworld-notes.md` §6).  It collides with `CREDITSRAM` and
    `THEENDBUF` in `$7F`, as noted in §1.3.  It only becomes necessary if
    the map has to be writable at runtime.
  - **(b) Patch each row as it is decompressed.**  This is the
    recommendation.  `LoadOWMapRow` (47 bytes) moves out to a far routine
    that does three things:
      - decompresses the row into the `$7000` window with long reads, from
        whichever map is active
      - applies the active edits for that row from a row-sorted list
      - leaves `DecompressMap` in place for standard maps
    `CallMinimapDecompress` gets the same treatment, so the minimap shows
    the edits and stops depending on a copy of itself in the map's own bank.

**What (b) costs per step (review 1's flicker question).**  This is an
estimate from instruction counts, to be confirmed with the profiler.

  - A vanilla row decode is about 16 cycles per tile written (an `(dp),Y`
    store to SRAM, then `INY`, `DEX` and two branches) plus per-run
    overhead.  That is about 5,000 cycles, roughly 1.5ms, once per vertical
    step.
  - The far version reads its source with `[dp],Y`.  That is one cycle more
    per *source* byte, and rows average 61 source bytes, so about 60 cycles,
    plus about 15 for the `JSL`/`RTL`.
  - The edit check for a row nothing touches is one bit test against a
    32-byte "rows with edits" bitmap, about 25 cycles.
  - The worst row (34 tiles) adds about 850 cycles.

So the common case is about 2% slower and the worst row about 17%, against a
16.6ms frame.  Two other facts make flicker unlikely:

  - The decode runs in the game loop, not in vblank.  The HAL flushes the
    new tilemap row in vblank exactly as now.
  - At walking speed a step is 8-16 frames.

Overworld entry is the place to look if anything shows.  It decodes 16 rows,
about 80K cycles in vanilla, which is also a candidate when looking at why
transitions feel slow.

**The "fetch from here rather than there" alternative.**  Store pre-edited
RLE copies of the touched rows and redirect the row pointer.  The decode
costs the same, and it is if anything slightly faster, since there is no
patch loop.  But the 35 rows that two or three lists share need a variant for
every combination of the lists touching them.  That is up to 8 copies of a
row, and the selection logic grows with it.  Patching handles overlap
uniformly, so it stays the recommendation unless the profiler says
otherwise.

**`EDIT_x` edges versus a generated edge list.**  Edges gated on edit bits
compress the connectivity of every edit combination into one table.  They
stay exact if three conditions hold:

  - edits only ever add an edge, or, in Sarda's case, remove one
  - an edge that needs two edits together carries a mask with both bits
  - the region split is fine enough that every edit's effect is a set of
    whole edges

None of those is something to trust by inspection.  The Python oracle (§4.4)
can check it exhaustively.  There are only 2^16 edit combinations.  A
tile-level flood fill of the 256×256 overworld per combination, comparing
the regions it finds with what the edge table predicts, is minutes of numpy,
and it would catch exactly the "surprise interaction" you are worried about.

A *dynamically generated* edge list could mean either of two things:

  - **Filtering the superset at New Game.**  Drop edges whose edit bits are
    off, so the BFS never tests them.  That is the same data and a fine
    optimisation.
  - **Deriving connectivity from the edited tiles on the cart.**  That means
    labelling regions over 65,536 tiles per movement type (on foot, canoe,
    ship, airship).  On a 65816 that is seconds of CPU, and it needs either
    a 64KB working copy or a streaming row-by-row labeller.  It would
    duplicate on the cart what the oracle does better offline.

Do the minimap run-length-1 fix first (`overworld-notes.md` §4).  It is the
prerequisite for anything that re-encodes a map.

Two edits are more than tiles:

  - **BridgeToLefein moves the bridge** to (230, 123).  `bridge_x/y` are
    unsram, so New Game writes them, the way Free SHIP writes `ship_x/y`.
  - **Sarda's Forest is the one edit that reduces connectivity.**  In the
    logic it removes edges rather than adding them, so it cannot be a
    simple pre-owned item.  It needs a flag-gated *absence*: edges that
    require `NOT EDIT_x`.  That is one bit of extra edge semantics.

Everything else is additive, so as you note, a placement made without the
edits stays valid with them.

### 9.2 Alternate maps

Measured with the vanilla RLE encoder, without length-1 runs, including the
512-byte row pointer table:

    FFR prebuilt starts   crescent 16,137   elfland 16,030   melmond 16,057
    FFR procgen pools     768 maps (normal, shuffled, unsafe x 256)
                          10,226 - 13,027, mean 11,450
    vanilla               15,529 + 512

FFR's three "start" maps turn out to be vanilla with town entrances swapped,
not new worlds.  130-195 tiles differ, so the party starts beside the
relocated "Coneria".  On the cart they belong with entrance shuffle (§9.3) as
presets, not with alternate maps.  Renders of all 775 maps, with per-map
statistics, are in `map-renders/`.

FFR caps the map data at `0x3E00` because it targets the same NES bank, so
every map it can produce fits the format this port already reads.

Per-map metadata, from FFR's `OwMapExchangeData`:

  - start, airship, bridge and canal coordinates (8 bytes)
  - ship spawn per entrance (16 × 3)
  - the nine exit-teleport coordinates (18)
  - 30 entrance coordinates (60, for entrance shuffle and the logic)
  - a 64-byte domain remap
  - a horizontal-bridge flag, which needs a second bridge sprite

That is about 200 bytes, plus about 2KB of logic tables (§4).  **Allow 14KB
per procgen map**, which packs four or five to a 64KB data-only image bank.
With ~800KB free, the ceiling is about 55 maps.  A practical selection of 16
costs about 225KB.

The hooks are the §9.1 ones, plus three more:

  - **The domain remap.**  `GetBattleFormation` (39 bytes, fixed bank) moves
    out, or one remap lookup is inserted.
  - **The positions.**  New Game writes them into unsram.
  - **The variant number** goes in the save snapshot.

Procedural generation on the cart: agreed, not worth it.  FFR's generator is
a multi-stage cellular, BSP and repair pipeline with retries, and 768 of its
outputs are sitting in the tree to choose from.

### 9.3 Entrance and floor shuffle

The entrance tile's 6-bit teleport id is a tile property, so **moving where
an entrance leads is a table edit, not a map edit**.  The tables are in bank
`$00`:

  - `lut_EntrTele_*`, 32 slots, 30 used
  - `lut_NormTele_*`, 64, for floors
  - `lut_ExitTele_*`, 16, 9 used

Each is read in one block of the fixed bank: 41, 38 and 23 bytes.  All three
move out to far routines reading WRAM copies of the permuted tables, and
together they free about 90 bytes.

What the shuffle itself has to produce, following FFR's
`ShuffleEntrancesAndFloors`:

  - **The entrance and floor permutations**, under FFR's rules:
      - towns with towns unless mixed
      - Coneria's entrance safe
      - Lefein and Melmond not first
      - dead ends set aside for forked floors
      - Titan's Tunnel's two ends tracked
  - **Exit-teleport coordinates recomputed** from where each exiting
    destination ended up.  Warps need nothing, since warp is stack
    unwinding and returns to the entrance by construction
    (`overworld-notes.md` §3).
  - **The ship's spawn moved** to the dock nearest whatever entrance now
    leads to Pravoka, from a per-entrance table.
  - **Logic rebuilt per seed.**  Floors become separate nodes, as your note
    says, and entrance edges get rewritten endpoints.  This is the only
    feature that requires the on-cart BFS rather than precomputed
    requirements.  What that takes is below.

**What the shuffle moves (2026-10-11, checked against the tile data and
FFR's `EntrancesFloorsShuffle.cs` / `Teleporters.cs`).**  "Rewrite the edge
endpoints" holds for reachability and for nothing else.  The rest:

  - **The unit is a destination, not a map and not a staircase.**  FFR's
    `TeleportDestination` is a landing point in one region of a map plus
    that region's outgoing teleports.  Gurgu B3 and B4 are two destinations
    each: what looks like B3 and B4 linked both ways, counted by map, is a
    forward chain through different regions, B3(a) -> B4(a') -> B3(b) ->
    B4(b') -> B5.  Sea Shrine is the same; Cardia is one map and five
    destinations.  And teleport ids are tile properties, so one id can be
    placed many times: Ice Cave B2's fifteen holes are all id 18.
  - **The way back is the stack.**  A warp is `DoStandardMap` returning one
    level (`overworld-notes.md` §3), so it goes wherever the party came
    from, not anywhere a table says.  44 of the 63 normal teleports land on
    the destination floor's up-staircase, a warp, and FFR's free-placement
    floors are all of that kind: deal one anywhere and its way back follows.
    The other 19 are exactly what FFR pins, each as a group:
      - Coneria Castle 2F, which returns by a normal teleport (FFR: "could
        be used if the teleporter here is turned into warp stairs")
      - the Temple of Fiends -> ToFR link, one way by design
      - the Ice Cave's back half, `IceCave5`-`8`, pinned when floors and
        entrances are both shuffled: the holes always drop into the Ice
        Cave and run on to its own exit
      - the Castle of Ordeals: ten teleports into its own 2F (the maze), and
        an exit rather than a warp
    **Invariant for the cart's shuffle: a dealt destination lands on a warp;
    anything that does not is pinned, with its group.**  Checked per seed,
    not assumed.
  - **One caller per destination.**  FFR never lets two teleports target the
    same destination.  That is what lets an exit be recomputed to a single
    root entrance, and keeps a warp's return a single edge.  Titan's Tunnel
    is two destinations in one map, each with its own exit.
  - **Titan's Tunnel should open new ground (user, 2026-10-11): preferred,
    not required.**  Ideally its two entrances land so that the tunnel gives
    access to a region not otherwise reachable, as vanilla's does (Sarda's).
    Not a hard rule: in a floaterless seed -- an FFR option not ported --
    there is value in the tunnel simply working as a long-distance overworld
    warp that saves walking.  FFR's only rule is that both ends sit at
    "connected" entrances, and under it the tunnel opens ground nobody could
    reach without the airship in 97 of 200 seeds (`worldgraph/run_fe.py`,
    `fecheck.titan_opens`).  So the preference needs a rule of the cart's
    own: re-roll, a bounded number of times, for a placement that opens
    ground, and keep the last one if none does.
  - **Exits go back to the root entrance's own region, vehicle and all.**
    The Waterfall is entered from the river; an exit recomputed to it lands
    the party in the canoe, not in whatever foot region holds the
    coordinate.  The ship stays where it was left, so the party comes out
    where it went in, as in vanilla's warp-outs.
  - **No game code tests a map id.**  Every read of `cur_map` indexes a
    table -- the map data, its objects and their graphics, the encounter
    domain and rate -- so a floor's behaviour goes where it goes.  What also
    goes with it is its difficulty: a deep floor can land near the start.
    FFR has no depth rule beyond its dead-end and fork bookkeeping; that is
    a question of feel for the cart's rules, not one the graph can see.
  - **In-room landings are not a requirement.**  FFR replaced the teleport
    handlers to take `inroom` from an unused high bit of the X coordinate
    (`TeleportXYInroom`).  Vanilla's tables never set those bits, and the
    two landings FFR marks in-room are pinned Ice Cave links.

**The stack.**  Each normal teleport pushes five bytes and `JSR`s a new
`DoStandardMap`: seven bytes of page 1 per level, unwound only by a warp.
Vanilla already lets a party walk Coneria Castle's stairs, or the Ice Cave
loop, round and round until the stack wraps and the game crashes, at about
29 levels.  FFR's "Softlock fix" (`asm/StackShift.asm`, installed on every
ROM from `ExtraTrackingAndInitCode`) catches it before each normal
teleport: with S below `$30` it slides the stack up seven bytes, dropping
the oldest frame.  At that depth a warp from the second floor returns to
the overworld rather than the first floor.  That is harmless to the logic --
a warp can only come back nearer the overworld -- and a shuffle that chains
floors deeper than vanilla makes it likelier to matter.  **Ported as an
unconditional fix, 2026-10-11** (`opt_stackshift`; `options-design.md`,
Bugfixes), with the threshold re-derived for the port: battles, menus and
the HAL's native-mode code use more stack than the NES game did, and native
pushes past `$0100` would land in zero page.  No map runs below S = `$7D`,
which leaves 125 bytes; the deepest routines the harness runs use 31.

**The graph, per seed.**  Static: the regions of every map and the gated
edges between them; a table from each teleport placement to its region, and
from each destination record to its landing region.  Per seed: an edge from
each placement's region to the landing region of the destination its id now
names; an exit edge from a destination's region to its root entrance's
region; and a warp as an edge back to the caller.  Warps add no
reachability, but they are what make assumed fill's premise true -- a region
once reached stays reachable -- and the stranding check needs them.

  - **Node budget: 256.**  Kept without knowing the wiring -- every region
    holding a location, either end of a teleport, or an overworld entrance,
    plus what vanilla's own pruning keeps -- the graph is 182 nodes, 129 in
    standard maps and 53 elsewhere (`worldgraph`, 2026-10-11).
  - **The cross-check against FFR covers only the vanilla wiring.**  All
    260 locations agree there.  For shuffled wiring: generate FFR ROMs with
    entrance and floor shuffle on, read their teleport tables through
    `worldgraph`, and compare against FFR's own logic, as `run_ffr_map.py`
    does for its overworld maps.

FFR also retints dungeon palettes by entrance region.  That is cosmetic and
can be skipped.

Effort is medium-high, almost entirely in the logic and FFR's rules rather
than the hooks.


## 10. Interactions with shipped flags

  - **NPC Guillotine.**  It only ever replaces `Talk_norm`, so reward NPCs,
    which all have their own handlers, are already immune.  Keep the reward
    test ahead of the Guillotine test in `opt_talk`, so a reward can never
    be swatted even if a later change moves a reward onto a `Talk_norm`
    object (FFR's `ShuffleObjectiveNPCs` does exactly that).
  - **Free X flags.**  They become logic inputs and must be snapshotted
    (§1.2).  A free item still in the pool should be replaced by filler, as
    FFR does.
  - **Chests Appear Opened, Identify Treasures, Chest Information.**
    Unaffected; see §2.
  - **Shop Information.**  It reads `item_box` and the stat tables, so it
    follows shop shuffle automatically.  It follows blursings once its three
    long reads point at the WRAM copy.
  - **Spell Fixes, Improved CURE/FIRE, Cast Life.**  Keyed by vanilla spell
    id.  Under level shuffle they must ask by identity (§6).


## 11. Order of work

**Status, 2026-10-07: Tier 1 item 1 is built, played (Off, B, A+B) and committed.**
Where it departs from the plan below or from §1:

  - **No hook at Continue -- reversed 2026-10-09; the cache is now built at
    `@Begin`, as §1.4 planned.**  At first every consumer called `ensure`,
    which compares the tag with the save and rebuilds on a mismatch.  That
    covered New Game, Continue, Continue of another file and power-on with no
    fixed-bank bytes spent at `@Begin` (22 were free), and the rebuild -- 11K
    to 39K instructions, a few frames -- vanished into the first standard-map
    load.  It stopped paying: a full world grew to ~760K instructions (about
    0.85 s), and RNG tables made the first overworld step a consumer, so the
    pause could land mid-walk.  The incentive and entrance shuffles would
    force building before the game anyway.  Now `GameStart`'s `@Begin`, where
    New Game and Continue meet, JSLs `rando_ensure` after `ClearZeroPage`
    (4 fixed-bank bytes): the pause falls in the transition into the game,
    and a Continue after a soft reset only compares the tag (112
    instructions, about 0.1 ms).  The consumers still `ensure` -- a check
    that should never fire now, kept as a safety net.
  - **Silent while it builds (playtest, 2026-10-09).**  Nothing calls the
    music driver during a build, so the SPC700 held its last note under the
    pause.  `@Begin` now asks `rando_stale` and, only on a miss, calls
    `DisableAPU` before `rando_ensure` (13 bytes where the JSL was 4).  The
    overworld track `PrepOverworld` starts next turns the channels back on.
    A soft reset's Continue still only compares the tag (116 instructions)
    and keeps its music.  Still to come, as the playtester put it: the build
    after party creation and flag selection on a black screen, and a
    "thinking" sound if it grows much longer.
  - **The read-only view on Continue, built 2026-10-09** (Select on
    Continue; `options-design.md`, "Save view"): the saved game's seed and
    RANDOMIZATION rows.  The rest of item 1's minimum UI -- seed entry, and
    the New Game flow around it -- waits for that flow's design (user, the
    same day).
  - **The cache holds all eight property tables** (2KB at `$7F:8800`), and
    `rando_tileprop` MVNs the current one in.  The `$80`-to-`$00` re-encoding
    and the trap deal both happen at build time.  `LoadSMTilesetData`'s
    prologue shrank from 20 bytes to a 4-byte JSL.
  - **Trap modes: FFR's first five** (Off, Shuffle, A-side, B-side, A+B),
    one value row under a new NEW GAME heading (since renamed
    RANDOMIZATION).  Local, Remove, Undead,
    Curated and Overpowered are left out.  Across FFR's presets only
    Vanilla, Shuffle and B-side are used.
  - **`SAVEVER` is 0.**  Every existing save has a zero block, which is the
    vanilla world, so introducing the block needed no bump.  The mechanism
    is in place and tested at nine versions on the real loops.
  - **`OPT_FORMAT` went to 5**, because the option checksum now covers the
    new-game byte at `OPT_NG` (`$6EC8`).  The entropy pool is at
    `$6EC4-$6EC7`, stirred every frame from `opt_padreset`.
  - **Debug seed** is `FFSEED=xxxxxxxx ./build.sh`, not an `FFDEBUG` tag.

Revised after review 1 into **tiers**.  Each tier ends in a complete game
that can ship and be played, so the work can stop at any boundary.  The
order follows the playtest burden, not the code.

**Tier 1: shuffles that cannot make a seed unwinnable.**  No logic.  Every
key item stays where vanilla put it.

  1. The foundation, proven on trap tiles:
       - the save block, PRNG, generator skeleton and WRAM cache
       - the versioned checksum
       - the Python reference and the differential harness
       - the minimum UI: seed, flags, and the read-only view on Continue
     Then **trap tiles, B-sides included**.
  2. **Shop shuffle**: weapons, armour, items.
  3. **Chest shuffle of non-progression contents.**  This moves
     `OpenTreasureChest` out, which banks 109 bytes.
  4. **Magic level shuffle**, then **stat tables and blursings**.  Both need
     the item-name lookup moved out.

  5. **Enemy and formation shuffles**: formation modes, unrunnable,
     surprise, scripts, skills & spells, status attacks.  Four hooks, three
     of which free bytes.  See `enemy-shuffle-notes.md`.  Formations built
     and played 2026-10-08 as two passes, rarity and zones (notes §1);
     unrunnable fights and surprise rates built and played the same day (§2);
     status attacks, scripts and skills & spells built 2026-10-09 (§3, §4)
     and played the same day in a full playthrough with every flag on,
     which completes the item.  RNG tables (FFR's flag: the encounter and
     battle tables shuffled per seed) built and played the same day; see
     `options-design.md`.

**Random Wares is dropped (user, 2026-10-08)**: it fills shops with a pile
of junk items and is not interesting.  The shop row stays Off / Shuffle.

None of these can soft-lock a run.  Each is exercised in the first hour of
any seed, and each has a small forced-scenario test (§13).

**Tier 2: incentive placement.**  The logic graph and its oracle for the
vanilla world, then key items across chests, then NPC rewards and their
dialogue.  This is the core of the project and the one tier whose
correctness cannot come from playing.  It has to come from the oracle.

**Free items leave the pool as a random chest of gold (user, 2026-10-07).**
Today a Treasures "Free X" flag hands the party the item, but the chest or
NPC that holds it still gives a second copy.  Tier 1 leaves key items alone,
so that was out of scope.  When the incentive shuffle takes key items into
the pool, each free item comes out of it and its slot gets a random amount of
gold.  This deliberately departs from FFR, which drops free items from
placement and pads a short pool with CABINs (`PlacementContext`,
`treasureDifference`).  FFR's `ItemLists.UnusedGoldItems` holds 21 gold ids
no vanilla chest uses, an obvious place to draw from.

**Tier 3: the world changes shape.**

  5. **Preset overworld edits**, minimap fix first.  This needs the edits
     screen.
  6. **Entrance and floor shuffle.**

**Tier 4: alternate maps**, with the map-select screen.  Each map adds a
logic table set and a metadata block, and nothing in code beyond Tier 3.


## 12. Open questions

Settled in review 1:

  - **Version policy**: detect and reset, through the checksum (§1.5).
  - **`NTSHADOW`** stays where it is (§1.3).
  - **No spoiler log on the cart.**
  - **No magic shop shuffle** (§6.3).
  - **Global dials stay global.**  Gold/XP, encounter rate and enemy stats
    are not snapshotted.  Turning encounters off mid-game is too useful for
    testing to give up.  Racing would argue for baking *every* flag into the
    save, which is consistent but out of scope.  Distributing an SRAM file
    for a race is impractical with common emulators anyway.
  - **Guiding principle: FFR's feel, inside a self-contained cart.**
    Default to FFR's rules and tuning, and deviate only where the cart
    forces it.  Seeds will still differ from FFR's, since the RNG does.
  - **Seed.**  Entropy from the frame count and controller input, gathered
    while the player is on the title and New Game screens, and editable.  A
    game in progress shows its seed somewhere other than the title screen,
    which is full.  The read-only view is the natural place.
  - **UI flow (user, 2026-10-11; the sketch is `menus.txt` in the project
    directory).**  The title screen stays as it is -- Continue, New Game,
    the options row -- and Select on Continue opens the save view (built).
    New Game opens a list: Custom Game, then presets adapted from FFR's
    (Vanilla, Improved Vanilla, Beginner, Classic, Entrance Shuffle,
    Entrance and Floor Shuffle, Chaos Rush, Free Enterprise).
      - Vanilla and Improved Vanilla randomize nothing and go straight to
        party creation.
      - Custom Game goes to overworld map select: a list of names, the
        map's preview beside it.  The vanilla map goes on to map edits
        (checkboxes); an alternate map skips them.
      - The other presets assume the vanilla map and open at map edits, so
        everything they set can be reviewed and changed on the way through.
      - Then: randomization (the shuffles now on the settings screen, and
        the incentive options under their own heading) -> options (the
        existing screen, less its RANDOMIZATION section) -> seed, when
        anything needs one -> party creation, after which the world is
        built and placed and the game begins.
      - **B returns to the previous screen, throughout** -- to whichever
        screen led there, so map edits goes back to the preset list when a
        preset opened it.  On the seed screen B is backspace while a seed
        is being edited, and goes back when nothing has been edited or the
        entry is empty.  Party creation's B on its first slot, with nothing
        chosen, goes back (to the seed screen, options, or the preset list).
      - The seed screen latches a random seed and shows it; a 4x4 grid of
        hex digits edits it, A entering a digit and B deleting one; Start,
        or A once all eight digits are in, goes on, and Start before then
        plays the error sound.
    This replaces the map-select-first flow settled in review 1.
  - **A preset sets the global options (user, 2026-10-11).**  Choosing one
    overwrites the option block, comfort settings and all, and a Continue
    of an older save then plays under it; that is accepted, because the
    options stay editable mid-game from the title screen, which matters
    more.  "Global dials stay global" above stands.  Open: what the title's
    options row shows afterwards -- today it cycles Vanilla, Improved,
    Super and Custom, and would read Custom.

Still open:

  - **NPC dialogue**: replacement text drawn from the options chunk is the
    recommendation (§3).  It needs a hook point before the vanilla string,
    or an empty stand-in dialogue.
  - **Map select layout.**  A 4×3 grid of 32×32 thumbnails gives 12 maps, a
    native-mode screen, and about 512 bytes of 4bpp tiles per map, generated
    offline.  The alternative is a scrolling list of names beside one large
    preview, say 64×64 or 128×128.  That has no count limit and shows far
    more of each map, at the cost of a DMA of 2-8KB when the cursor moves.
  - **Which FFR incentive options to carry.**  It has about 30
    `Incentivize*` switches.  Two or three presets of the incentive location
    mask would cover most real use.  They are not independent of the item
    list: twenty incentive items into FFR's 22 default incentive locations
    fails two seeds in three (§4.6), so a preset is an item list and a
    location set chosen together.


## 13. Keeping the playtest load down

Review 1's worry is two or three months of playtesting.  What actually needs
a human, and what does not:

  - **Winnability never needs a human.**  The oracle answers it for every
    seed of every flag combination, overnight if need be.  If a placement
    bug reaches a playthrough, the oracle missed it, and the fix is to the
    oracle.
  - **Hooks need a human once each, briefly, if the scenario is forced.**
    `FFDEBUG=house` is the model: a debug build that puts the case under
    test in front of a fresh save.  For example:
      - the SHIP in Coneria's first chest
      - the CANAL as Sarda's reward
      - a B-side in the first trap
      - LIF2 in a level-1 slot
    Each is a five-minute check, not a run.  The 65816 harness covers the
    same paths without a screen.
  - **A spoiler from the `.srm` on the desktop.**  The Python reference
    reads the seed and placement out of a battery file and prints the world.
    That is not a spoiler on the cart, and it turns "where is the canoe in
    this seed?" from an hour into a second.
  - **Feel is FFR's, mostly.**  Pacing and difficulty of these modes were
    tuned by FFR's community.  Porting its rules rather than inventing new
    ones keeps the design iteration small.  The exceptions are the decisions
    made here: the 30-tile trap pool, and the stored placement.

What remains is the UI, which is design work and wants hands-on iteration,
and one or two full Tier 2 runs to see the whole thing hold together.  Those
runs are also the game, which is the point.
