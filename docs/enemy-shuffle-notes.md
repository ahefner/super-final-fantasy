# Enemies, formations and bosses -- FFR's shuffles on the cart

Parked exploration, 2026-10-07.  Nothing here is implemented.  It covers a
subset of FFR's "Enemies, Formations, and Bosses" tab, as requested:

  - the formation shuffle modes
  - Shuffle Surprise Bonus
  - Shuffle Scripts and Shuffle Skills & Spells, for enemies and bosses
  - status attacks in Shuffle mode
  - Shuffle Unrunnable Encounters, keeping vanilla's count rather than
    reassigning by percentage

Enemizer is out of scope.

Read alongside `randomization-notes.md`: the per-save seed, the WRAM cache
and the hook-payment rules in its §1 apply unchanged.  FFR references are to
`FF1Randomizer/FF1Lib`.  Counts were measured from the built ROM.


## 0. Summary

**Done 2026-10-07:** Weapon Stats is at parity with FFR; the enemy attack
element comes from byte `$0E`, not the weakness byte (§4).

All six fit the save-tied architecture as-is.  Each is a shuffle of a small
table, generated from the seed into the WRAM cache.  None of them affects
item logic, so they cannot make a seed unwinnable: they are Tier 1 work, in
the terms of `randomization-notes.md` §11.

Each field the shuffles change has **exactly one reader**, which is why the
whole set comes down to four hook sites.  Three of them replace routines the
features would rewrite anyway, so moving them out frees bytes rather than
costing them:

| feature | data | the one reader | hook | bytes | WRAM |
|---|---|---|---|---|---|
| formation shuffle (4 modes) | `lut_Domains`, 128 x 8 | `GetBattleFormation` (fixed bank, 39 bytes) | routine moved out | fixed +~30 | 1,024 |
| unrunnable shuffle | formation byte `$0D` bit 0 | the 16-byte formation copy (fixed bank) | the copy moved out | fixed +~30 | 32 |
| surprise bonus | formation byte `$0C` | the same copy | shared | -- | 115 |
| scripts (enemies, bosses) | enemy byte `$07` | the AI read (bank `$0C`, ~25 bytes) | read replaced, 16-byte shadow | `$0C` +~15 | 128 |
| skills & spells | `lut_EnemyAi`, 44 x 16 | the same read | shared | -- | 704 |
| status attacks | enemy byte `$0F` | enemy attack setup (bank `$0C`) | the existing `OptScaleEnemyAttack` hook, extended | `$0C` +7 | 128 |

That totals about 2.1KB of WRAM.  The save snapshot gains about 2 bytes of
flags.  Generation is shuffles of at most 256 items, under a millisecond.


## 1. Formation shuffle

**The data.**  `lut_Domains` (bank `$0B` `$8000`) is 128 domains of 8
formation ids:

  - 0-63 are the overworld's 8x8 grid of 32x32-tile areas
  - 64-127 are the standard maps, by `cur_map + 64`

A random encounter picks a slot by `lut_FormationWeight`: 12/64 each for
slots 0-3, 6/64 each for 4-5, 3/64 for slot 6 and 1/64 for slot 7.  31
domains are all zero, 12 overworld and 19 maps (towns and castles).  The
table uses 230 distinct ids: all 115 normal A-sides and all 115 B-sides.

**FFR's four modes** (`Formations.cs`, `ShuffleEnemyFormations`):

  - **Shuffle Rarity**: per domain, shuffle slots 0-3, then shuffle slots
    2-7 together.  Formations stay in their zone; only their frequency moves.
  - **Shuffle Rarity Tiered**: per domain, deal the 8 slots by weighted draw
    without replacement, with weights 48, 48, 48, 48, 24, 24, 8, 8 for the
    original slots.  So a formation mostly keeps its tier.
  - **Shuffle Across Zones**: overworld and dungeon encounters **do** mix,
    and its behaviour changed in 2024.  Checked against FFR's git history
    (review 2):
      - **2018-2024** (`b69af495`, then `Enemies.cs`): every formation
        entry of every eligible domain went into one pool, one entry at a
        time, and was dealt back.  That matches today's tooltip, "shuffles
        ALL encounters".
      - **Since 2024-04-12** ("Backend Clean Up 1", #1059, into
        `Formations.cs`): whole 8-slot domain lists are permuted as units.
        It arrived in a cleanup commit (`43c77f52`), so it is probably an
        accident rather
        than a design change.
    Either way the pool has 52 overworld domains (land, plus river `$40`/
    `$41` and sea `$42`, which reuse the slots of the first three towns) and
    42 dungeon floors.  So about 23 of the 52 overworld domains get a dungeon
    list on an average seed, in either version (simulated over 2,000 seeds).
    Excluded from the shuffle: four starting domains (`$1B`, `$1C`, `$24`,
    `$2C`, the vanilla Coneria/ToF area) and every all-zero domain.  One
    reason it is easy to miss: the battle backdrop comes from the overworld
    tile, so a dungeon formation fought outside looks like an overworld
    fight.
  - **Totally Random**: each slot is drawn independently from all 256 ids,
    except the boss formations (`$73-$7F`, `$F3-$FD`), and the starting
    domains are kept.  B-sides vanilla never uses can appear.

**The tooltip's own history (2026-10-08)** makes it a comedy of errors.
The first tooltip (`b39e032c`, 2019-12-29) described whole lists moving --
Ice Cave groups in Gurgu Volcano, "does not alter the contents of the domains
themselves" -- while the code pooled single slots.  `ef353c0f` (#856,
2022-06-14) rewrote it to "Shuffles ALL encounters ... regardless of zone or
rarity", matching the code.  Then the 2024 cleanup switched the code to whole
lists and left the tooltip alone.  Each version of the code has contradicted
one version of the text.  And in FFR's vocabulary a **zone is a domain**:
one 8-slot list of `lut_Domains`, so every overworld square and every
dungeon floor is its own zone (Enemizer has an unrelated, 11-entry notion).

**Decided (user, 2026-10-08): two orthogonal passes instead of FFR's one
mode.**  Whole-zone shuffling is treated as the bug.  Built and played:

  - **Formation rarity**: Off / Shuffle / Tiered -- FFR's Shuffle Rarity
    and Rarity Tiered, moving formations between the slots of a zone.
  - **Formation zones**: Off / Light / Shuffle / Random.  Shuffle moves
    formations between zones and keeps each one's rarity: lut_FormationWeight's
    four classes (slots 0-3, 4-5, 6, 7) are each pooled across the 94
    eligible zones and dealt back.  Light (user, 2026-10-08) pools only
    slots 0, 3, 5 and 6, each on its own -- two common fights, an uncommon
    and a rare from elsewhere, 33 of every 64 encounters -- so a zone keeps
    slots 1, 2, 4 and 7 and stays recognisably itself.  Random is
    FFR's Totally Random.
  - **WarMECH never leaves Sky Palace 5F under Light or Shuffle** (user):
    its one slot, the floor's 6, is left out of the zones pool.  The rarity
    pass may still move it within the floor, as FFR's does -- pinning it
    there too was tried and reverted, since FFR moves it.  Random, the
    chaotic mode, can put it anywhere.
  - Zones runs first, then rarity, each from its own stream.  Both on is
    the tooltip's "any encounter can appear anywhere regardless of zone or
    rarity".  The exclusions are FFR's: the zones around Coneria (`$2C` is
    itself all zero) and the 31 all-zero ones.

**The reader.**  `GetBattleFormation` in the fixed bank, and nothing else.
It is entered three ways (land, sea/river, standard maps) but is one routine.
Moving it out costs a `JSL` and an `RTS` in place of 39 bytes, reading the
shuffled table from WRAM.  It is the same hook alternate maps need for their
domain remap (`randomization-notes.md` §9.2), so building it once serves both.

**Alternate maps.**  The starting-domain exclusion is vanilla geography.  For
another map, the generator should exclude the domains around that map's
start instead, which means one more field of per-map metadata.


## 2. Unrunnable encounters and the surprise bonus

**The data.**  Each formation record is 16 bytes.  Byte `$0C` is the surprise
rate.  Bit 0 of byte `$0D` is "cannot run", and in vanilla it covers **both**
sides.  Measured:

  - 13 normal formations are unrunnable, so 26 sides.  That matches FFR's
    `VanillaUnrunnableCount`.  The 13 boss and miniboss formations are the
    rest of the 26 with the bit.
  - Of the 115 normal formations, 91 have surprise rate 4.  The other 24 are
    spread between 27 and 90.

**The readers.**  All three read the RAM copy, `btl_formdata`:

  - the ambush/first-strike check (bank `$0C`, which skips the check
    entirely for an unrunnable fight)
  - the RUN command (bank `$0C`)
  - the port's own Run -> Wait (options chunk)

That copy is filled by **one 16-byte loop in the fixed bank**, in battle setup
(`bank_0F.asm` around line 12100), indexed by `btlformation`, whose bit 7 is
the side.

**What FFR does.**

  - `SeparateUnrunnables` is a global hack, so it applies to every FFR rom.
    It gives the B side its own bit (`$02`), patches `PrepareEnemyFormation`
    to clear the other side's bit, and turns both `AND #$01` reads into
    `AND #$03`.
  - `ShuffleUnrunnable` then marks a random set of sides unrunnable from a
    pool of 233: A-sides 1-114, B-sides 0-114, and the B-sides of the four
    miniboss formations.  It never touches formation 0 (the imps), the
    fiends and Chaos, or the miniboss A-sides.
  - `ShuffleSurpriseBonus` shuffles byte `$0C` over the 115 normal
    formations, without regard to runnability.  An unrunnable formation never
    ambushes, so a high rate can land where it does nothing, exactly as in
    vanilla.

**What the port does.**  The fixed-bank copy moves out, keeping its `SwapPRG`.
The far routine copies the record with long reads, then writes two bytes into
the RAM copy:

  - the surprise rate, from a 115-byte table
  - bit 0 of `$0D`, set to "unrunnable **for this side**", from a two-bit-
    per-formation table

**No reader changes at all.**  Every reader already asks bit 0 of the RAM
copy, so per-side unrunnability needs neither FFR's second bit nor its two
operand patches, and Run -> Wait keeps working untouched.  The copy is about
35 bytes of fixed bank, so it pays for itself.  Trap tiles and scripted fights
come through the same copy; the tables leave bosses as they are.

**Built and played 2026-10-08**: as described above, as two rows,
Unrunnable fights and Surprise rates, each Off / Shuffle.  `rando_formdata`
replaces the 43-byte copy in `EnterBattle` (39 bytes back), keeping its
`SwapPRG`.

**"Shuffle only".**  Keep vanilla's count.  Two granularities are possible:

  - **26 sides out of FFR's 233** (chosen in review 2).  This is FFR's model, and
    the port gets it for nothing.  FFR's own presets ask for 12%, which
    rounds to 28 sides, so 26 is "vanilla's count", as asked.
  - **13 whole formations**, which is vanilla's model.

Either way the generator excludes what FFR excludes.


## 3. Scripts, and skills & spells

**The data.**

  - Enemy record byte `$07` is the script id; `$FF` means none.  36 of the
    118 normal enemies have a script, using 34 distinct scripts.  The 10
    bosses use scripts 32 and 34-42.
  - `lut_EnemyAi` (bank `$0C`) holds 44 scripts of 16 bytes: spell chance,
    skill chance, 8 spells, a pad, 4 skills, a pad.  Across all 44 there are
    151 spell entries and 109 skill entries.

**The reader.**  One site, at each enemy turn (bank `$0C`): it reads the id
**from the ROM record**, takes the no-script path on `$FF`, and builds a
pointer into `lut_EnemyAi`.  Everything after that reads through the pointer.
`LoadEnemyStats` also copies the id into battle RAM (`en_ai`), but nothing
reads it there.  Disch's comment at the read asks why it is stored at all.

**FFR's scripts shuffle** (`Enemies.cs`, `ShuffleEnemyScripts`):

  - **Enemies**: permute the script ids among the 118 normal enemies, which
    keeps the count.  The pirates are left out unless "Unsafe Pirates" is on,
    and the imps when Balanced Scripts is on.
  - **Bosses**: two separate permutations.  The four fiends exchange scripts
    among themselves.  WarMECH, the four refights and Chaos exchange among
    themselves.  The sub-options restrict the shuffle to the overworld
    fiends, or to the Temple of Fiends refights only.

**FFR's skills & spells shuffle** (`EnemyScripts.cs`,
`ShuffleEnemySkillsSpells`):

  - Remove two copies each of CRACK and TOXIC first, so they do not spread.
  - Pool every spell and every skill within a group, and deal them back into
    the scripts that have a non-zero chance.  Each such script gets at least
    one; with "No Empty Scripts", at least two.
  - Shuffle the chance bytes across the group.
  - There are three groups: normal scripts (0-31, 33, 43), fiends (34, 36,
    38, 40), and big bosses (32, 35, 37, 39, 41, 42).
  - Optionally reroll any script with two NUKEs or two NUCLEARs in a row.
  - "Generate Balanced Scripts" is a separate, tiered generator.  It is more
    work and is not covered here.

**What the port does.**  Replace the ~25-byte read with a `JSL`.  The far
routine:

  1. looks up the id in a 128-byte WRAM table, indexed by the enemy id from
     the RAM record
  2. on `$FF`, returns carry, and the existing jump to
     `ChooseAndAttackPlayer` follows
  3. otherwise copies the 16-byte script from the shuffled 704-byte WRAM
     table into a 16-byte shadow every chunk can see, and points `@aiptr` at
     it

This is the `OPTMAGSHADOW` pattern again: every later read is untouched.  The
shadow lives only while this enemy chooses its action.  The per-enemy AI
position counters stay in battle RAM and index the shadow exactly as they
indexed ROM.

**Interaction with magic levels.**  None, as built: the magic shuffle
redirects at the player's slot (`randomization-notes.md` §6.2a), so enemy AI
casts spells by identity as vanilla does and needs no inverse.  Enemy spells
still go through `Battle_PrepareMagic` and `opt_magicdata`, so Spell Fixes and
the spell buffs apply as now.

**Built and played 2026-10-09** (a full playthrough with every flag on).
Two rows, Enemy scripts and Enemy
skills, each Off / Enemies / Bosses / Both (§6).

  - `rando_enemyai` replaces `Enemy_DoAi`'s 30-byte lookup (byte-neutral:
    a JSL, the no-script branch, and 21 bytes of padding never executed).
    It reads the enemy id from battle RAM through `($9A)`, takes the script
    id from the cache's 128-byte table, copies the script into
    `OPTAISHADOW` (option page `$E0`, SRAM) and points `@aiptr` there;
    carry means none.
  - Scripts: the normal enemies but the pirates permute their ids (36
    casters stay 36); the bosses permute within FFR's two groups.  Skills:
    FFR's `ShuffleIndexedSkillsSpells` per group, No Consecutive Nukes on,
    No Empty Scripts off; the nukes are FADE and NUKE, as FFR's
    `FindSpells` finds them.  The CRACK/TOXIC removal only with the normal
    group (FFR does it with either).  Each half of each row draws from its
    own stream.
  - A full Tier 1 world with everything on now builds in up to ~760K
    instructions (about 0.85 s, once per power-on); the skills deal is up to
    295K of it, mostly the write phase walking the pools per script.
  - The rules no vanilla script trips (FADE, the NUKE-and-NUCLEAR opening,
    non-$FF pads) are tested on a doctored `lut_EnemyAi`
    (`test_rando_aisynth`), with a seed found where the opening rule bites.


## 4. Status attacks (Shuffle mode)

**The data.**  Enemy record byte `$0F` is the touch ailment.  Measured across
the 128 enemies: 91 have none, 16 poison, 16 stun, 2 sleep, and one each of
dark, stone and death.

FFR's `ShuffleEnemyStatusAttacks` permutes bytes `$0E` and `$0F` together
across all 128 enemies, bosses included.  The pirates keep theirs unless
"Unsafe Pirates" is on.

`$0E` is the touch's element, and it pairs with the ailment.  Measured:

  - poison touch: poison element (all 16)
  - stun, dark and one sleep: status
  - stone and the other sleep: poison/stone
  - death: no element at all

Vanilla's attack code ignores it and takes the attack element from the
enemy's *weakness* byte (`$12`); Disch flags it "BUGGED ?".  For most enemies
that is fire, lightning or ice.

**Correction (review 2): FFR fixes this, as part of Weapon Stats.**
`FixWeaponStats` includes "Fix player elemental and category defense".  Its
write at `0x325B0` sets the enemy attacker's category to 0 and reads the
element from `$0E`.  So in an FFR seed with Weapon Stats on, armour
resistances act on the touch's own element.  That is why FFR's status
shuffle moves `$0E` together with `$0F`, so the pair stays consistent.

**The port's Weapon Stats was missing that half; fixed 2026-10-07.**

  - Ported first: the weapon side (`opt_weaponstats`) and the
    player-as-defender zeroing, physical (`optweaponstats_def.patch`, FFR's
    `0x325E8`) and magic (`optweaponstats_mag.patch`).
  - Now ported: the enemy-as-attacker write.  Bank `$0C` still loads
    category `$10` and weakness `$12`, and `opt_scaleatk`, the existing
    `OptScaleEnemyAttack` hook just after, overwrites both under Weapon Stats
    (category 0, element from `$0E`).  No game bytes moved; the 14-byte load
    could still fold into the hook if `$0C` ever needs the room.
    `test_enemyelement` drives all 128 enemies with the flag off and on.

So the status shuffle can move both bytes (a 256-byte table).

**The reader.**  One `LDA ($86),Y` of `ENROMSTAT_ATTACKAIL`, in enemy attack
setup (bank `$0C`).  It sits right after the port's existing
`OptScaleEnemyAttack` hook for stat scaling.

**What the port does.**  Extend that hook to load the ailment from a 128-byte
WRAM table.  The 7-byte load that follows the hook (`LDY` / `LDA` / `STA`)
then goes away, a net +7 bytes in a bank with 4.

**Built and played 2026-10-09** (the same playthrough), as one row, Status attacks: Off /
Shuffle.  `opt_scaleatk` asks `rando_touch` for the enemy's touch from the
cache (element and ailment, 256 bytes) and stores the ailment, and under
Weapon Stats the element; bank `$0C`'s ROM load became seven NOPs (the
patches stay byte-neutral).  The shuffle is a clean permutation of the 127
enemies but the pirates, bosses included.  FFR's is not quite one: it
shuffles all 128 records and skips the pirates' slot as it writes back, so
the pirates' touch can go to a second enemy and another touch drop out.

The port's Enemy Status Attacks fix (one roll per *connecting* swing) is a
different site and composes with this.


## 5. Safety, and the order of work

None of this can soft-lock a run, but some of it can make the opening
brutal.  FFR's safeguards are part of the feel and should come across
whole:

  - **Starting domains** untouched under Shuffle Across Zones and Totally
    Random.
  - **Safe pirates**: script and touch fixed unless opted out.
  - **Unrunnable shuffle** never touches the imps (formation 0), the
    minibosses or the bosses.
  - **NoConsecutiveNukes** for boss scripts.
  - **Not protected (user, 2026-10-09): the enemies around Coneria.**  The
    starting zones keep their formations, but IMP, GrIMP, WOLF, BONE, CREEP,
    SPIDER and MADPONY still take part in the touch and script shuffles, as
    in FFR (which exempts the imps from scripts only under its balanced
    generator).  About one seed in five gives one of them a NUKE/XXXX or
    LIT3/FIR3 script or a death or stone touch.  Accepted: encounter
    manipulation is the player's answer to a rough opening.

The tables are seeded world data like everything in `randomization-notes.md`
§1:

  - The flags go in the save snapshot: the formation mode (3 bits), and one
    bit each for unrunnable, surprise, enemy and boss scripts, enemy and boss
    skills, status, and the boss sub-options.  About 2 bytes.
  - The tables live in the WRAM cache, built once.

Testing follows `randomization-notes.md` §13:

  - **The 65816 harness** can check each hook against its table directly.
    For every enemy id, the shadow must equal the table's script; for every
    formation and side, the RAM copy's bit 0 must equal the table.
  - **One forced-encounter debug build** covers the battle-side look and
    feel.

In Tier 1 terms, these come after trap tiles and share their character: one
table, one or two hooks, nothing the logic needs to know.


## 6. Open questions

  - **Settled 2026-10-08**: neither of FFR's versions of Shuffle Across
    Zones; rarity and zones are separate passes (§1).  The original question:
    port FFR's current behaviour (whole lists) or
    the original one the tooltip describes (single formations)?
  - **Settled in review 2**: unrunnable by side; Balanced Scripts excluded.
  - **Settled 2026-10-07**: the enemy attack element is fixed inside Weapon
    Stats as FFR does it (§4), and played (ghouls against an Ice Shield).
  - **Alternate maps**: which domains count as the starting area.
  - **Settled 2026-10-08 (user): the scripts and skills menu.**  Two value
    rows, *Enemy scripts* and *Enemy skills*, each Off / Enemies / Bosses /
    Both -- covers every combination FFR's presets use (all on by default;
    enemies only in the 2025 tournament; Free Enterprise's scripts both,
    skills enemies).  Fixed rather than offered: No Consecutive Nukes on
    (FFR's default preset has it), pirates always safe, FFR's "Everything has
    a Script" at Vanilla (a permutation, 36 casters), No Empty Scripts off.
    Not ported: Remove Boss Scripts, the balanced generator, the boss
    sub-options (Overworld Fiends Only, Temple Refights Only -- they could
    become extra values later without moving existing ones).  FFR strips two
    CRACKs and two TOXICs whenever either skills flag is on; here only when
    the enemies' skills shuffle, since that is the pool it is meant for.
