# FFR's presets on the cartridge

The New Game list (`randomization-notes.md` §12) offers presets adapted from
FFR's.  This is the inventory of what each one needs: what the cartridge
already sets, what it approximates, and what it lacks.  The bar is the
user's: "it doesn't have to be exact" (2026-10-11).

Sources are FFR's own preset files, `FF1Randomizer/FF1Blazorizer/wwwroot/
presets/*.json`.  A key missing from a file takes its default from
`FF1Lib/Flags/Flags.cs`, and the comparison here fills gaps that way.  Values
were checked against FFR's enums and the code that reads them, not only the
tooltips.

| List entry                 | FFR source                                       |
|----------------------------|--------------------------------------------------|
| Vanilla                    | ours; FFR has no such preset                     |
| Improved Vanilla           | `Improved_Vanilla.json`; the title's Improved too |
| Beginner                   | `Beginner.json`                                  |
| Classic                    | Beginner, for now (user, 2026-10-11); to be retuned toward an intermediate Spring Tournament set |
| Entrance Shuffle           | `Entrance_Floor_Shuffle.json` with Floors off; FFR has no such preset |
| Entrance and Floor Shuffle | `Entrance_Floor_Shuffle.json`                    |
| Chaos Rush                 | `Chaos_Rush.json`                                |
| Free Enterprise            | `Free_Enterprise.json`, without recruitment (user) |

**Entrance and Floor Shuffle is Beginner plus the wiring.**  Its only other
differences are the Short ToFR, a 60% encounter rate in dungeons as well as
on the overworld (Beginner has 70% in dungeons), Auto retargeting off, and
three comfort rows.  Both use the same incentive set.


## 1. What a preset writes

Every row, as the title's presets do today (user, 2026-10-11):

  - **Vanilla turns everything off** and is the original game.
  - **Every other preset turns on every quality-of-life row**, as FFR's do.
    Three such flags differ between FFR's preset files -- Repeated potion
    use, Chests appear opened and Magic menu spell reordering -- but only
    because the older files predate them: they are missing there, not
    switched off.
  - **Auto retargeting is the exception: off in every preset**, for the
    player to turn on (user).  FFR turns it on in Improved Vanilla and
    Beginner and off in the rest.

A model that left "comfort" rows alone was considered and dropped.

## 2. What the cartridge already sets

Vanilla is everything off, with the dials at 100% and the elemental bonus at
+4.  IV is Improved Vanilla, Beg Beginner, ES Entrance Shuffle, EFS Entrance
and Floor Shuffle, CR Chaos Rush and FE Free Enterprise.

| Setting               | IV    | Beg, Classic | ES      | EFS     | CR      | FE      |
|-----------------------|-------|--------------|---------|---------|---------|---------|
| Gold and XP           | 200%¹ | 250%         | 250%    | 250%    | 500%    | 300%    |
| Encounter rate        | 100%  | 60%²         | 60%     | 60%     | 30%     | Off     |
| Enemy, boss stats     | 100%  | 100%³        | 100%³   | 100%³   | 100%³   | 100%³ ⁴ |
| Elemental bonus       | +4⁵   | +30          | +30     | +30     | +30     | +30     |
| Auto retargeting      | off   | off          | off     | off     | off     | off     |
| Bugfixes, all four    | on    | on           | on      | on      | on      | on      |
| Better Thief + Ninja  | -     | on           | on      | on      | on      | on      |
| Thief and Ninja hit%  | on⁶   | on           | on      | on      | on      | on      |
| Double weapon crit    | -     | on           | on      | on      | on      | on      |
| Improved Cure spells  | -     | on           | on      | on      | on      | on      |
| Improved Fire spells  | -     | -            | -       | -       | -       | -       |
| Cast Life in battle   | -     | on           | on      | on      | on      | on      |
| LOK2 accuracy         | -⁷    | on           | on      | on      | on      | on      |
| Free BRIDGE           | -     | on           | on      | on      | on      | on      |
| Free SHIP, AIRSHIP, CANAL, CANOE, TAIL | - | -   | -       | -       | on      | on      |
| Free LUTE             | -     | -            | -       | -       | on      | -       |
| Trap tiles            | Off   | Shuffle      | Shuffle | Shuffle | Shuffle | B       |
| Shops, Chests, Magic levels | Off | Shuffle   | Shuffle | Shuffle | Shuffle | Shuffle |
| Blessing, curse       | 0, 0  | +5, -3       | +5, -3  | +5, -3  | +5, -3  | +5, -3  |
| Formation rarity      | Off   | Shuffle      | Shuffle | Shuffle | Shuffle | Shuffle |
| Formation zones       | Off   | Off          | Off     | Off     | Off     | Off     |
| Unrunnable, Surprise  | Off   | Shuffle      | Shuffle | Shuffle | Shuffle | Shuffle |
| Status attacks        | Off   | Shuffle⁸     | Shuffle⁸ | Shuffle⁸ | Shuffle⁸ | Shuffle⁸ |
| Enemy scripts         | Off   | Both         | Both    | Both    | Both    | Both    |
| Enemy skills          | Off   | Both         | Both    | Both    | Both    | Enemies |
| RNG tables            | Off   | Shuffle      | Shuffle | Shuffle | Shuffle | Shuffle |

1. FFR's `ExpMultiplier` leaves enemy gold alone.  It divides shop prices,
   gold chests and the level thresholds by 2 instead (`Scale.cs`,
   `ScalePrices` and `ExpGoldBoost`).  Measured against what things cost,
   that doubles the gold and XP from enemies, which is our dial at 200%.
   Our Improved was 100%; it changes to 200% (user, 2026-10-11).
2. FFR has two rates: Beginner is 60% on the overworld and 70% in dungeons.
   Our dial has one.
3. FFR rolls each enemy's stats between 70% and 150%, and its HP between 50%
   and 150%.  Our dials are one fixed percentage each, HP included, so 100%
   stands in.
4. Free Enterprise also scales boss HP on its own, 80-240%.
5. FFR's Improved Vanilla has its "Weapon Type Bonus" checkbox off, so the
   +10 on its slider does nothing (`IncreaseWeaponBonus` returns early).
   Our Improved was +10, from misreading this as FFR's value; it changes
   to +4 (user, 2026-10-11).
6. FFR's Improved Vanilla has hit growth at Balanced, 3 a level against
   vanilla's 2; the other four presets have Double, 4.  Our checkbox was
   Double; the row becomes Vanilla, Balanced, Double, and Improved takes
   Balanced (user, 2026-10-11).
7. FFR's Improved Vanilla sets LOCK accuracy to 162.  On the cartridge that
   is part of Spell fixes; the LOK2 row is FFR's Auto Hit.
8. FFR's presets use Randomize, not Shuffle: each enemy draws a touch from
   all of them except stun, and the bosses are included.  Our row offers
   only Shuffle.

Two fixed choices also differ, in Free Enterprise only: it allows the pirates
shuffled skills and a status touch, and it allows consecutive nukes.  The
cartridge fixes both the other way.


## 3. What is missing

Each item lists the presets that use it.  Every randomized preset means
Beginner, Classic, ES, EFS, CR and FE.

### 3.1 Already planned

  - **Incentive placement** (Tier 2), in every randomized preset.  This
    covers the key items in chests, the NPC and fetch-quest items, FFR's
    `Incentivize*` locations, and Early King, Sarda, Sage and Ordeals (the
    item without the vanilla precondition; Ordeals without the CROWN).  It
    is what these presets are built on: without it, Beginner is shuffles
    and scaling around vanilla's key items.  Beginner, ES and EFS share one
    incentive set.  CR and FE add gear (Katana, Vorpal, Opal, the casting
    weapons and armour, FE more) and drop what they hand out free.
  - **The wiring** (Tier 3): Entrances with dead ends (ES, EFS), Floors
    (EFS), and the Short ToFR (EFS, CR, FE).
  - **Map edits**, in every randomized preset:
      - Early Open Progression, an overworld edit that, among other things,
        lets the party walk from Coneria to the Dwarf Cave.
      - Titan's Trove.
      - The Gaia shortcut, and the item shop moved beside it.
      - The Lefein shortcut.
      - The ToFR exit portal.
      - The Ordeals pillars.

### 3.2 Cheap

Approved (user, 2026-10-11), each a flag and a commit of its own: the
starting items (FFR's sets, some or all), SOFT in battle, and White Mage
HARM.

  - **In all five presets, Improved Vanilla included, and not yet on the
    cartridge:**
      - Run chance corrected (`ChanceToRun` Corrected).  Vanilla's chance
        to run is bugged.  *Played 2026-10-11:* a Bugfixes row.
      - Turn order randomized properly (`ImproveTurnOrderRandomization`).
        It shuffles the initial bias, so enemies no longer always start the
        order, and makes the shuffle a true Fisher-Yates.  *Played
        2026-10-11:* a Bugfixes row, the Fisher-Yates half.
      - TRANCE given the status element (`TranceHasStatusElement`), so a
        Ribbon resists it.  *Played 2026-10-11:* a Variations row.
      - Critical hits shown as numbers (`EnableCritNumberDisplay`, with
        speed hacks).  *Played 2026-10-11:* unconditional, not a row
        (user).
    FFR's Improved Vanilla is otherwise covered: its BB absorb fix is
    unconditional here.

  - **XP and gold bonus +100** (`ExpBonus`), in every randomized preset.
    Every enemy is worth 100 more of each, which makes the early game far
    faster: an Imp's 6 XP becomes 106 before the multiplier.  FFR adds the
    gold against prices it has already divided, so the bonus is multiplied
    here too.  It belongs in `opt_scalereward`.
  - **Progressive scaling, +10% per key item** (`ProgressiveScaleMode`), in
    every randomized preset.  XP and gold gains grow 10% for each key item
    collected, counting free and turned-in items.  It goes in the same
    place, with a count of the key item bits.
  - **Starting items: FFR's Explorer pack** (`StartingItemSet`) of 10
    Tents, 50 Heals, 4 Pures and 2 Softs, in every randomized preset.
    *Played 2026-10-11:* a Treasures row with FFR's nine
    fixed sets.
  - **Hit% cap raised from 200 to 250** (`FixHitChanceCap`), in every
    randomized preset.
  - **SOFT in battle** (`EnableSoftInBattle`), as both the spell and the
    potion, in every randomized preset.  *Played 2026-10-11:* a
    Variations row.
  - **White Mage HARM** (`WhiteMageHarmEveryone`), in every randomized
    preset.  *Played 2026-10-11:* a Variations row.  HARM damages anything when a White Mage or White Wizard casts
    or uses it, and averages 30/60/90/120 on targets that aren't undead.
  - **Consumable stacks** (`ConsumableTreasureStackSize` Adequate), in
    every randomized preset.  Chests and NPCs holding consumables give a
    small stack.
  - **A separate dungeon encounter rate**, Beginner only.  It can be
    skipped: one rate of 60% is near enough.

### 3.3 Medium

  - **Random-range values on the stat dials** (FFR's 70-150%, and HP
    50-150%), in every randomized preset.  It needs a per-enemy roll into
    the cache.
  - **Random shop prices, 30-250%** (`PriceScaleFactor`), in every
    randomized preset.  Each item's price is rolled into the cache.
  - **XP chests** (`ExpChestConversion` 20%), in every randomized preset.
    A fifth of the gold chests give XP instead, which needs a new kind of
    chest content.
  - **Thief lockpicking**, in every randomized preset.  A Thief of the set
    level opens every locked door without the KEY.  Placement logic has to
    know about it.
  - **Lefein's Inn, Clinic and SuperStore**, in every randomized preset.
    These are town edits and shop data.
  - **Hints**: the town hint-givers and the Sky Warrior bats, in every
    randomized preset.  They mean something only with incentive placement,
    and they wait on the NPC dialogue question still open in §12.
  - **Fanfare for incentive gear** found in chests, in every randomized
    preset.  It is trivial once incentive placement exists.

### 3.4 Large

  - **Class blursings** (`RandomizeClassMode` Blursings, with spellcasting
    bonuses), in every randomized preset.  Each class rolls random bonuses
    and maluses, which Select reveals at party creation.  It is one of
    modern FFR's signatures.  It touches the class data, level-ups and spell
    permissions, and needs text for the party screen.

### 3.5 What defines Chaos Rush and Free Enterprise

**Chaos Rush:**

  - **Unlocked ToFR** (`ChaosRush`) and zero orbs required
    (`OrbsRequiredCount`).  The locked doors in ToFR Revisited open, so with
    the Short ToFR, Chaos is there as soon as the party can survive him.
    Both are cheap; the Short ToFR waits for map edits.
  - **A forced random party**: all four slots rolled, no Nones, and FFR's
    slot allow-lists.  This is a party-creation feature.
  - Red Mage hit growth (`RedMageHitBuff`), which is minor.
  - Its free vehicles, 500% XP and 30% encounters are already in §2.

**Free Enterprise:**

  - Alternate fiends; buffed Astos, Bahamut and pirates; WarMECH guarding
    Tiamat; an alternate final boss.
  - Bahamut must be fought for the class change.
  - The Masamune is guaranteed, with a guardian.
  - Better trap chests, random loot with High wealth, a random AoE-casting
    item at the start, and boss HP scaled 80-240%.
  - **Its party is a problem.**  Slots 1 and 2 are forced random, and slots
    3 and 4 allow only None, because FFR fills them by recruiting classes
    from NPCs.  We're not porting recruitment (user), and taken literally
    that leaves a party of two.  The cartridge needs its own rule here.

### 3.6 Not porting

  - Random Wares (CR and FE): declined (user, 2026-10-08).
  - Recruitment (FE): declined (user).
  - Dormant in all five, because their parent flag is off:
      - the guaranteed defense item, which needs item-magic shuffle;
      - wealth, except under FE's random loot;
      - Beginner's early-encounter, damage-tile and poison sub-values.
  - `NoBossSkillScriptShuffle` (FE): no code reads it.
  - Magic menu spell reordering (Beginner, comfort): possible later as a
    comfort row; no preset needs it.
  - FFR's poison routine.  FFR swaps it in for every preset, Improved
    Vanilla included, with a fixed damage that defaults to 3; vanilla takes
    2 HP a round.  This reading is from the code and wasn't tested.


## 4. Per preset, and an order

  - **Vanilla**: complete, apart from what the cartridge does
    unconditionally.  The None class is offered at party creation, the BB
    absorb fix applies, Controller Reset works, the stack fix holds, and
    several criticals are counted.
    Those stay: almost identical is identical enough (user, 2026-10-11).
  - **Improved Vanilla** becomes FFR's (user, 2026-10-11): 200% gold and
    XP, elemental bonus +4, Thief hit Balanced, NPC guillotine on, Auto
    retargeting off.  It then lacks only the four small rules in §3.2 that
    every FFR preset has.
  - **Beginner and Classic** already get their scaling, variations,
    shuffles and the Free BRIDGE.  What's missing, roughly by weight:
      1. incentive placement;
      2. the XP economy (the +100, progressive scaling, XP chests);
      3. the Explorer pack and the small rules of §3.2;
      4. map edits;
      5. class blursings;
      6. lockpicking, random prices and hints.
  - **ES and EFS** are Beginner plus the wiring and the Short ToFR.
  - **Chaos Rush** is Beginner's list plus the unlocked ToFR, the orb count
    and the forced party.  It is otherwise the most complete already.
  - **Free Enterprise** is the most expensive and the least faithful,
    because it lacks recruitment.

A suggested order:

  1. The cheap batch of §3.2.  Every randomized preset gains, and none of
     it needs the new UI.
  2. Incentive placement.
  3. Chaos Rush's unlocked ToFR, orb count and forced party.
  4. Map edits and the wiring.
  5. Class blursings.
  6. Free Enterprise last, if at all: without recruitment, its difference
     from Chaos Rush is mostly bosses.
