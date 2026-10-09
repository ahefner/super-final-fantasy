# New Consumables -- notes for a future feature

Parked exploration, 2026-09-26.  Nothing here is implemented.  The question
was whether FFR's **New Consumables** could be ported as an option flag, and
in particular where the player would buy the new items without a randomizer
to scatter them.

Not a first-priority feature.  It is the largest single item looked at so far
-- bigger than any flag in `options-design.md` -- and most of its weight is in
one place (the in-battle DRINK box) that can be cut away.

Everything below was read out of `FF1Lib/ExtConsumables.cs`, the disassembly,
and `game/bin/0E_8300_shopdata.bin`.  Figures name their label or file.

## 1. What FFR's feature is

`flags.ExtConsumableSet` selects one of three sets of four items:

    SetA   FCURE  PHNIX  BLAST  SMOKE
    SetB   RFRSH  FLARE  BLACK  GUARD
    SetC   QUICK  HIGH   WIZRD  CLOAK

`AddExtConsumables()` (FF1Lib/ExtConsumables.cs:47) runs ~15 code generations.
The whole file is 626 lines and emits **965 bytes** across 29 `Blob.FromHex`
literals.  `PutInBank` targets: 13x bank `$0E`, 11x `$1F`, 10x `$0C`, 2x `$1C`.

Banks `$1C` and `$1F` do not exist in a 256KB image -- FFR expands the ROM.
For us those become the options chunk with JSL hooks; the image has ~832KB
free, so bank space is not the constraint.  The constraints are item ids and
magic records, below.

## 2. Item ids: there is no free space, so FFR eats four weapons

Vanilla's carryable id space is fully allocated:

    0        None
    1-16     Lute .. Oxyale (key/quest items, contiguous)
    17-20    the four Orbs
    21       **free** (FFR repurposes it for the Shard)
    22-27    Tent Cabin House Heal Pure Soft (the counted consumables)
    28-67    weapons, all forty used
    68-107   armor
    108+     gold pseudo-items -- a chest-contents encoding, not carryable

So exactly **one** free carryable id, number 21, and it happens to sit
directly below TENT inside the counted-consumable range.

FFR takes the four it needs from the bottom of the weapon list --
`WoodenNunchucks` 28, `SmallKnife` 29, `WoodenRod` 30, `Rapier` 31 --
renamed in `ChangeItemNames()` (:360).

**It does not simply delete them.**  Two fixups keep the early game coherent,
and they are the reason this is less destructive than it first looks:

  - `ClearShops()` (:527) -- in every weapon shop, an entry equal to one of the
    four gets **`+= 4`**, promoting it to the weapon four ids later:
    Nunchucks->IronHammer, SmallKnife->ShortSword, WoodenRod->HandAxe,
    Rapier->Scimitar.  That is the next tier up, i.e. Pravoka's stock.
  - `ExtConsumableStartingEquipmentFix()` (:593) -- the same shift applied to
    starting equipment.

Net effect in a non-randomized game: the four lowest-tier weapons vanish and
their shop and starting slots are filled by the tier above.  A Fighter starts
with a Scimitar instead of a Rapier.  A mild power-up at game start, not a
break -- and with the flag off, none of it happens.

## 3. Magic records: exactly two spare, and they are the DRINK effects

This is the real reason the feature is big.

`lut_MagicData` (`$0C:81E0`, `game/bank_0C.asm`, 8 bytes per record):

    $40 spells          $200 bytes
    $02 potions         $010 bytes   <-- slots $40 and $41
    $1A enemy attacks   $0D0 bytes
                        $2E0 total

The two "potion" records are vanilla's **in-battle HEAL and PURE effects**,
read by the DRINK command.  FFR's `CreateLifeSpell`, `CreateSmokeSpell`,
`CreateHighPotionSpell` and `CreateBlackPotionSpell` (:477-526) all write
`MagicOffset + 0x40 * MagicSize` or `+ 0x41`, i.e. **they overwrite those two
records**.

That is why the DRINK box has to be rebuilt rather than extended: once the two
potion records belong to new items, the battle menu needs its own order,
effect and target tables to say which record each visible entry uses.  Hence
`WriteDrawDrinkBoxRoutine`, `WriteLutDrinkBoxOrder/Effect/Target`,
`WriteLutDrinkBox`, `WriteCursorPositions`, `WriteDrinkBoxMenuRoutine`,
`ModifyBattle_PlMag_TargetOnePlayer`, `WriteCureAilmentsBreakout`,
`ModifyUndoBattleCommand`, `ModifyAfterFadeIn`, `WriteBattleDoTurn`,
`ModifyBattleLogicLoop` -- eleven of the ~15 generations, and nearly all of
the 965 bytes.

**We are better placed than FFR here.**  `opt_magicdata` already copies a
record into a buffer and asks `opt_spelloverride` per field before handing the
pointer back, so records no longer have to live in `lut_MagicData` at all.
Adding new records costs options-chunk space, not scarce table slots.  If the
two potion records can be left alone, most of section 3's work disappears.
This is the single most important thing to check before starting.

## 4. Where you buy them

### 4.1 The shop table

`lut_ShopData` at `$0E:8300`, 384 bytes (`game/bin/0E_8300_shopdata.bin`):
70 pointers of 2 bytes, then **variable-length, null-terminated, tightly
packed** inventory lists.  Unused shop slots share one null record at `$838E`.
Sections are 10 shops each: Weapon 0, Armor 10, White 20, Black 30, Clinic 40,
Inn 50, Item 60; the caravan is id 70, past the end of the sections, and
`EnterShop_Caravan` is a `BNE` straight into `EnterShop_Item`.

`LoadShopInventory` (`bank_0E.asm:4871`) copies **exactly 5 bytes** with
`LDY #$04` / `BPL`, then hard-terminates at `item_box+5`.  Five items is the
ceiling and it is enforced by the copy length, not by the data.  Short records
have their 4th and 5th bytes read out of the *next* record and ignored,
because the null already terminated the display.

The item shops as shipped:

    id 61   HEAL PURE TENT                 3 of 5
    id 62   HEAL PURE TENT CABIN           4
    id 63   HEAL PURE CABIN HOUSE SOFT     5  full
    id 64   HEAL PURE CABIN HOUSE          4
    id 65   CABIN HOUSE HEAL PURE          4
    id 66   CABIN HOUSE HEAL PURE SOFT     5  full
    id 70   BOTTLE  (caravan)              1 of 5

Five of the seven have *display* room.  None has *table* room -- each record's
terminator is immediately followed by the next record, so lengthening one means
rebuilding the region.

### 4.2 Three ways to place them

  1. **Replace, don't append.**  FFR's own non-random path,
     `AddNormalShopEntries()` (:549), gated on `NormalShopsHaveExtConsumables`:
     HEAL->FCURE, HEAL->PHNIX, PURE->BLAST, SOFT->SMOKE, each in a randomly
     chosen item shop that stocks the donor.  Fixing the shop choice instead of
     randomizing it makes this a **pure data edit with no table growth** -- the
     record length never changes.  Cheapest option by a wide margin.
  2. **The caravan.**  Four free display slots, already the game's one-off
     oddity vendor, ship-gated so the items arrive mid-game.  Needs the record
     lengthened, so it needs 4.3.
  3. **Chests.**  FFR's randomizer answer (`MoreConsumableChests.cs`).  The
     port already has the chest machinery from Chests Appear Opened and Chest
     Information, and chest contents are a flat table.

### 4.3 Relocating the shop table, if append is wanted

Same shape as the `lut_ShopTypes` move already done: lift the 384-byte blob
into the options chunk, rebuild the records with the slack wanted, and repoint
the two `LDA lut_ShopData, X` in `LoadShopInventory`.  Note this does **not**
raise the 5-item ceiling; going past 5 additionally needs the copy loop, the
shop cursor table and the box height, which is not worth it.

## 5. The out-of-battle half is cheap

Worth separating out, because it is the part that could ship alone.

  - `ChangeItemJumpTable()` (:107) -- the item-use jump table is at `$0E:B177`,
    36 entries x 2 bytes.  FFR copies it to `$0E:96B0` and repoints the two
    loads at `$0E:B16A` and `$B16F` with 3 bytes each.  Exactly our existing
    table-relocation pattern.
  - `WriteOutOfBattleRoutines()` (:145) -- four routines at `$0E:96F8`,
    `$9748`, `$9790`, `$9795`.  The two substantial ones are ~60 and ~48 bytes;
    the "generic" ones are **5 bytes** each (`LDA #n` / `JMP $B1B8`, deferring
    to the existing item-as-spell path).  Under 200 bytes for all four.
  - `ChangeItemNames()` (:360) and `ChangeMenuTexts()` (:394) -- text only.

So an out-of-battle-only subset is roughly: one 72-byte table relocation, two
3-byte repoints, ~200 bytes of routines, and text.  That is ordinary-flag
sized.

Side effect to watch: with the feature on, FFR also points Crystal, Herb, Key
and Tnt at the "bad item" handler, disabling their use from the menu.  Those
are trade items, so this is probably deliberate cleanup, but it is a visible
behaviour change and should be its own decision rather than a silent rider.

## 6. Prices -- unverified

`ExtConsumablePriceFix()` (:566) returns values far above the 16-bit gold
range (SetA: FCURE 49152, PHNIX 262144, BLAST 16384, SMOKE 12288), so these
are pre-scaling figures in whatever domain `Scale.cs` works in, not gold.
Only the **relative ordering** should be trusted from this: PHNIX is by far the
most expensive, FCURE next, then BLAST and SMOKE.  Check against the real price
table before choosing numbers.

## 7. Shapes this could take

  1. **Out-of-battle only** (section 5), items placed by replacement
     (4.2 option 1).  Skips the entire DRINK rebuild -- most of the 965 bytes
     and eleven of the fifteen generations -- and leaves the two potion records
     untouched, so section 3 evaporates.  Ordinary flag size.  Recommended if
     this is picked up at all.
  2. **One item at id 21**, sold in the caravan.  No weapon dies and vanilla is
     untouched with the flag off, but it still needs whatever battle work its
     effect requires, so it is a similar cost for a quarter of the payoff.
     Only attractive combined with 1, where the cost is already low.
  3. **The full four items with the battle menu.**  Multi-session.  Do not
     start without first settling section 3's question: whether
     `opt_magicdata`'s copy-and-override path lets new records live in the
     options chunk and the two vanilla potion records stay put.  If it does,
     the drink box may be extendable instead of rebuilt, and the estimate
     changes completely.

## 8. Order, if this is picked up

1. Answer section 3: can new magic records live in the options chunk behind
   `opt_magicdata`, leaving slots `$40`/`$41` alone?  Everything else scales
   off this answer.
2. Shape 1 above.  Self-contained and testable: buy the item, use it on the
   map, watch the effect.
3. The battle menu only if shape 1 proves the concept worth extending, and
   only with section 3 answered favourably.
