# Super Final Fantasy -- technical analysis

An evaluation of how to bring the feature list in `overview.txt` to the SNES
port in this repository, written after reading the port, the 6502 disassembly and the
relevant parts of Final Fantasy Randomizer.

Everything with a number attached was measured against the tree at
commit d98ea12 and is reproducible; the two places where a claim
rests on reasoning rather than measurement say so.


## Summary

The overview's premise -- "code space is at a premium and there won't be room
to squeeze new if/else code paths into the existing code banks" -- is right
about the existing banks and wrong about the cartridge.  The port uses 1152KB
of a 2MB image.  Fourteen 64KB image banks are unused, and they can be
addressed as ordinary NES-style chunks: the same `$8000-$BFFF` swappable half
with the fixed bank at `$C000-$FFFF`, reached with one `JSL`.

So the recommendation is the first of the three approaches the overview
floats: **runtime flags, with routines migrated into new banks to make room.**
The other two are not needed as the primary mechanism.  Copying code into Work
RAM and patching it in place does not survive contact with `SwapPRG`; baking
pre-patched preset banks works but cannot compose, so it is only ever a
fallback for individual features that resist a runtime branch.

Three findings make this much cheaper than the same job was in FFR:

  - There is room for 14 new code banks, verified working (below).
  - 45% of the assembled banks is `.INCBIN` data, not code.  Bank `$0C` --
    the one with zero free bytes and most of the battle features -- is 29%
    data across only 20 access sites.  Evicting those tables frees 4.6KB
    in the bank under the most pressure, for about 20 bytes of cost.
  - `JSL`/`RTL` replaces FFR's `LongJump` entirely, and leaves DBR alone,
    so a migrated routine still reads its original bank's tables with plain
    absolute addressing.


## Verification: the seventeenth chunk

The whole plan rests on being able to add a bank and call into it, so that was
built and run rather than assumed.

A new chunk was placed at ROM image bank 18, which HiROM shows at SNES bank
`$B2` = `CHUNK0 + 17`, with the fixed bank stamped into its `$C000-$FFFF`
exactly as `mkrom.py` does for chunks 0..15.  A probe routine there was called
from `GameStart` with `JSL $B28000`.  The probe stores to WRAM through DBR,
`JSR`s `ClearBGPalette` in the fixed bank -- which goes out through the PPU
thunks into the HAL -- reads the value back, and returns a sentinel by `RTL`.
`GameStart` hangs deliberately if the sentinel is wrong.

    probe returns $5A     boots; intro renders identically to baseline
    probe returns $5B     black screen, hung at GameStart   (negative control)

The negative control matters: without it, "the game still boots" would also be
consistent with the call never having happened.

That establishes all four properties the migration needs -- the bank is mapped
and executing, its own copy of the fixed bank answers a plain 16-bit `JSR`,
DBR still points at the caller's chunk so absolute addressing finds NES RAM and
the I/O map, and `RTL` returns correctly.  `ld65` links the new segment against
the existing ones without complaint.  The build change was about twelve lines
across `snes.cfg`, `build.sh` and `tools/mkrom.py`.


## Space

### ROM

Chunk N runs at PBR `$A1+N`.  In a 2MB image the bank number masks to image
bank `1+N`, which gives 31 chunk slots at `$A1..$BF`.  Sixteen are the NES
banks, one (`$B1`, image bank 17) is the beam bank, and **fourteen are free**.
The arithmetic closes exactly against the free space in the image:

    14 x 16KB  new code at $8000-$BFFF                       224KB
    14 x 32KB  long-addressable data in the low half         448KB
    14 x 16KB  fixed-bank copies                             224KB
                                                            ------
                                                             896KB

The low half of a chunk is unaddressable while running there -- it is I/O,
WRAM and SRAM -- but the same image bank is readable in full at `$C0+N`, which
is how `BEAMBANK` already works.  So each new chunk is 16KB of code plus 32KB
of data.

### The existing banks

Full, but mostly of data.  Fill runs are runs of 16 or more identical `$00` or
`$FF` bytes in the linked output; some of those are legitimate zeros in tables
rather than free space, so the column is an upper bound.

    bank   fill runs   .INCBIN data        role
    ----   ---------   -----------------   -------------------------
    01           179    8192  (50%)        overworld map
    09          1446    8192  (50%)        minimap, CHR
    0B           611   12456  (76%)        battle data
    0C             0    4736  (29%)        battle code -- the pressure point
    0D           225   11951  (73%)        music, scenes
    0E           199    4144  (25%)        menus, title
    0F           169     512   (3%)        fixed bank, copied 16x

Bank `$0C` has literally no free run of 16 bytes, and it is where most of the
bugfixes and battle variations land.  Its tables are:

    lut_WeaponData            320     lut_BattlePalettes        256
    lut_ArmorData             160     aidata                    704
    lut_MagicData             736     lut_MagicBattleMessages     -
    data_EnemyStats          2560     lut_CharMagicData           -
                                      lut_WeaponSwingTSA          -
                                                     total     4736

Twenty access sites, all inside `$0C` except `lut_BattlePalettes`, which `$0F`
also reads.  Moving the tables to a new chunk and converting those sites to
long addressing costs roughly a byte each and frees 4.6KB where it is needed
most.  This is the highest-leverage single change in the project.

Of the fixed bank, 151 bytes are free at `$FF69`.  That is the scarcest real
estate in the cartridge: it is only 3% data, and it is stamped into every
chunk, so anything hooked from it spends address space that adding banks
cannot recover.  Budget it deliberately.

### WRAM

All of `$7F:0000-$FFFF` is unused -- 64KB.  `$7E:2000-$3FFF` is free, and
there are small holes in `$0800-$0FFF` between the HAL's own buffers.

### SRAM

8KB at `$6000-$7FFF`, and every byte is already spoken for:

    $6000-$63FF   unsram          working copy of the save
    $6400-$67FF   sram            the saved block, checksummed
    $6800-$6EFF   battle RAM      ...with theend_drawbuf ($700 bytes) on top
    $6F00-$6FFF   mapobj
    $7000-$7FFF   mapdata         the full 4KB; indexed AND #$0F / ORA #>mapdata

There is no hole.  Options storage therefore needs one byte of work first --
see below.


## Cross-bank calls

FFR's `LongJump` (`FF1Randomizer/FF1Lib/asm/LongJump.asm`) costs 56 bytes of
runtime, 6 bytes per call site and 7 bytes of zero page, clobbers registers on
the way through, and saves and restores the current bank via `$60FC`.

The 65816 does the same job in `JSL` (4 bytes) and `RTL` (1 byte).  Three
properties make migration nearly free:

  - **`JSL` does not touch DBR.**  A routine evicted to a new bank goes on
    reading its *original* bank's tables with ordinary absolute addressing.
    This is the opposite of the NES situation, and it is what makes moving
    code out of a full bank cheap instead of viral.
  - **The fixed bank is in every chunk**, so a migrated routine still calls
    `DrawBox`, `DrawComplexString` and `WaitForVBlank` with a plain `JSR`.
  - **Nothing reads `h_curbank`.**  It is written at `src/hal.asm:1102` and
    `:4016` and never read, so `JSL` cannot desynchronise any bookkeeping.

The invariant `SwapPRG` depends on is also already clean: it is called only
from the fixed bank.  There are zero call sites across all six swappable
banks, which is what makes its return-into-a-different-PBR trick safe, and
`JSL` does not disturb it.


## Options storage

**Do not enlarge the SRAM.**  Above 8KB, HiROM pages SRAM by bank bits, so
each chunk would see a different page while the game reads `$6000-$7FFF` from
whatever bank happens to be live -- and the game does that constantly, from
code that runs in every chunk.

This repository has already sprung that trap.  The docstring in
`tools/mkrom.py` records the previous attempt: 16KB paged by bank parity,
which worked, but forced every chunk onto an odd bank -- halving the fourteen
chunks this plan spends -- and produced an image a Super EverDrive V2
misdetected as LoROM and refused to boot.  The `TRACEFAR` comment in
`src/snesmap.inc` records the aliasing hazard from the same episode.

**Make the room instead.**  `theend_drawbuf` (`$6800`, `$700` bytes) is used by
exactly one scene -- the ending pen-plot at `game/bank_0D.asm:340` --
across about ten reference sites.  Battle RAM tops out at `$6DB1`, so moving
that buffer into WRAM frees `$6DB2-$6EFF`, **334 bytes** of battery-backed
SRAM that nothing else claims.  That is far more than an options block needs,
and the eviction is contained to one scene.  There is precedent in tree:
`tools/convert.py` already relocates `mm_decorchr` from `$7000` to WRAM
`$0D00` under `DECOR_IN_WRAM`, and WRAM bank `$7F` is entirely untouched.

**Integrity.**  Model it on the game's own scheme at
`game/bank_0E.asm:5837` -- two assertion bytes plus a sum forced to `$FF`
-- with two changes:

  - Add a **format-version byte**.  An options block changes shape between
    builds, and a stale block that still checksums correctly is worse than one
    that is obviously absent.  On a version mismatch, fall back to a preset.
  - Keep it strictly outside `$6400-$67FF`, so `SaveGame`'s wholesale copy from
    `unsram` and `VerifyChecksum`'s `$400`-byte sum never interact with it.
    Options are global; they should survive starting a new game.


## Feature triage

The requested list splits four ways, and the first two groups are much larger
than the overview assumes.

### (a) Constant becomes variable -- zero net bytes

The important trick.  `LDA #$02` becomes `LDA opt_movespeed`: same instruction
length, no branch, no new code path.  Most of the list lands here.

  - Speed hacks: wipe divisors, dialogue box, battle entry, palette cycling,
    explosion counts, lineup animation, respond rate.
  - Faster Walking / Faster Ship -- the vehicle-speed block at
    `game/bank_0F.asm:3945-3957`, the same `move_speed` (`$34`) and
    `vehicle` (`$42`) variables FFR patches at `1F:D077`.
  - Encounter Rate -- `battlerate` is a single byte, written at
    `bank_0F.asm:1773` and `:3757` and compared at `:3303`.
  - LOCK / LOK2 accuracy, Double Weapon Crit Rate, elemental and type bonus,
    and the CURE / FIRE / HEL2 / SABR effectivity constants.

### (b) Rescaling at an existing ROM-to-RAM copy -- free

The copy already exists, so these need a hook, not a table.

  - Enemy Stats and Boss Stats: `LoadEnemyStats` at
    `game/bank_0C.asm:6142` already walks each enemy's stats from ROM into
    RAM through `lut_RomRamMapping`.  Scaling is a hook in that loop.  No
    duplicate tables, and it is per-battle so it can respond to a flag change.
  - Gold and XP Scaling: two hooks after `SumBattleReward`, in
    `EndOfBattleWrapUp` at `game/bank_0B.asm:641`.

This is the honest version of the overview's "copy the base code into Work RAM
and patch it" idea -- the game already does the copy, for exactly the data
that wants rescaling.

### (c) Conditional branches in full banks -- these cost bytes

No Party Shuffle, Run to Wait, Battle Magic Menu Wraparound, Enemy Status
Attacks, House MP Restoration, Weapon Stats, Spell Fixes, BB/Master Absorb.
Most land in `$0C` and `$0E`, which is why freeing `$0C` comes first.

### (d) New routines -- new chunk

Buy Quantity, Autosort Inventory, Repeated Heal Potion Use, Auto Retargeting,
Shop Information, Chest Information, Identify Treasures, Chests Appear Opened,
Better Thief + Ninja, Cast Life in Battle -- and the options menu itself.

For (c) and (d), most of this need not be reverse-engineered from hex blobs.
FFR ships 106 commented assembly sources in `FF1Randomizer/FF1Lib/asm/`,
covering a good part of the list: `0F_8740_Unrunnable.asm`,
`0F_8670_SortInventory.asm`, `1C_A250_AutoRetargeting.asm`,
`1A_8600_RepeatedHealPotionUse.asm`, `0E_9E00_NewItemShopCode.asm`,
`1F_D077_Speedboat.asm` and others.  `FF1Lib/BankUsageRegister.md` is in effect
a migration map: FFR solved this same problem by expanding to MMC3 and moving
`0B` to `1B`, `0E` to `1E` and `0F` to `1F`.


## Alternatives evaluated

**Copy the base code into Work RAM and patch it.**  Workable in principle --
`$7F` is exactly one chunk's worth, `$7F:8000-$BFFF` for the patched bank and
`$7F:C000-$FFFF` for a copy of the fixed bank, with DBR left pointing at a real
chunk so I/O and SRAM still resolve.  It collapses on `SwapPRG`: only one chunk
fits in `$7F`, so every bank switch would have to re-copy and re-patch 16KB,
and the game switches banks constantly.  Not viable as a general mechanism.
(Reasoned, not measured.)

**Pre-patched preset banks baked into the ROM.**  Affordable now -- fourteen
spare chunks and 896KB -- and worth keeping as the escape hatch for any single
feature that genuinely resists a runtime branch.  But it does not compose: N
independent flags need 2^N variants, so it can only ever back a small fixed set
of presets, not the toggleable menu the overview asks for.


## Edits to a bank must be byte-neutral

Found the hard way, by breaking the game.

The banks lay their data out by sequential assembly.  There is no `.org` and no
`.res`: a blob sits wherever the code before it happens to end.  But other
banks reach that data at absolute addresses baked into `Constants.inc` --
`lut_OrbCHR = $B600`, `lut_ItemPrices = $BC00`, `lut_Treasure = $B100` and
about thirty more -- and pointer tables inside the data hold absolute addresses
too.  Nothing checks the two agree.

So shrinking a routine by 24 bytes in bank `$0D` moved every blob after it down
by 24.  The symptoms were not obviously related to the change: wrong orb
graphics on the start menu, broken text in several menus, and story strings
rendering with their first 24 characters missing, because a fixed pointer now
landed 24 bytes into the string.

Two consequences for the migration plan:

  - **A patch replaces N bytes with exactly N bytes.**  Where the replacement
    is shorter, pad it -- `.res N - k, $EA`.  Where it is longer, move the body
    into the HAL or a new bank and call it, so the call site stays the size of
    what it replaced.
  - **Moving data out of a bank leaves a hole, not a saving.**  Evicting bank
    `$0C`'s 4,736 bytes of tables still yields 4,736 usable bytes, but they
    stay *where the tables were*; everything after has to keep its address.
    New code goes in the hole rather than the bank being compacted.

`tools/convert.py` now asserts that every `.INCBIN` lands on the address its
filename records -- `bin/0D_B600_orbchr.bin` must assemble at `$B600` -- which
turns this class of mistake into a build error naming the blob that moved.  30
blobs across banks `$0B`, `$0C`, `$0D` and `$0E` are pinned this way.  The
fixed bank is exempt: every literal in `Constants.inc` points into
`$8000-$BFFF`, its contents are reached by linked symbol, and the port's own
patches reshape it deliberately.


## Risks and open questions

  - **The fixed bank is the scarce resource, not the ROM.**  151 free bytes,
    stamped into every chunk.  Adding banks does not help it.
  - **`JMP (abs)` reads its vector from bank `$00` on the 65816**, not from
    PBR.  That is fine for the RAM pointers the game actually uses -- and is
    presumably why the port works today -- but it is a trap if migrated code
    introduces a ROM-resident indirect jump.
  - **The options menu needs a home.**  The body belongs in a new chunk;
    `DrawComplexString_L` (`$C003`), `DrawBox_L` (`$C006`) and `DrawPalette_L`
    (`$C00F`) are already exported and callable from there with a plain `JSR`.
    What is not yet settled is where it hangs off the title screen, which lives
    in `$0E` and is itself tight.
  - **Flag changes mid-game.**  Group (a) and (b) features respond immediately
    because they are read at the point of use.  Group (c) and (d) mostly do
    too, but anything that alters saved state rather than behaviour needs a
    rule about what happens when a flag is toggled on an existing save.
  - **Presets and the version byte.**  Vanilla / Improved Vanilla / Super (then called Deluxe)
    should be expressible as a bitmask the options block stores directly, so a
    version bump can reset to a preset without needing to migrate the old
    block's layout.


## Suggested order of work

  1. Make the bank-adding machinery permanent -- `snes.cfg`, `build.sh`,
     `mkrom.py` -- with one new chunk and a test that fails loudly if it stops
     being reachable.  The probe described above is the shape of that test.
  2. Move bank `$0C`'s 4,736 bytes of tables into it.  This is the change that
     unblocks the battle features, and it is measurable: `$0C` should go from
     zero free bytes to about 4.6KB.
  3. Options block in SRAM: evict `theend_drawbuf` to WRAM, define the block at
     `$6DB2`, write the magic, version and checksum routines.
  4. Group (a) features.  They cost nothing and they exercise the options block
     end to end before any structural change depends on it.
  5. Options menu on the title screen, with the three presets.
  6. Groups (b), (c), (d), in whatever order the free space allows.
