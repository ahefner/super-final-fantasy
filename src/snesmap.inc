;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  snesmap.inc -- SNES memory map for the Final Fantasy 65816 port
;;
;;  ROM is HiROM (mode 21), FastROM, 8KB SRAM.
;;
;;  ROM bank 0  (SNES $C0 / $00 hi half) ...... HAL code + SNES header
;;  ROM bank 1+N (seen as $A1+N, N = $00..$0F) ... one NES "chunk":
;;        $8000-$BFFF   NES PRG bank N
;;        $C000-$FFFF   NES PRG bank $0F  (the fixed bank -- copied 16x)
;;
;;  Game code executes with PBR = $81+N so that the low half of the bank
;;  exposes the SNES I/O map, which lines up with the NES map beautifully:
;;
;;        $0000-$1FFF   WRAM      (NES RAM lives at $0000-$07FF)
;;        $2100-$21FF   PPU regs
;;        $4200-$44FF   CPU regs / DMA
;;        $6000-$7FFF   SRAM      (NES PRG-RAM, $6000-$7FFF, verbatim)
;;        $8000-$FFFF   ROM
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

; --- Bank numbers -------------------------------------------------------
HALBANK         = $C0           ; HAL code lives here (long-addressed)
HALFAR          = HALBANK * $10000
CHUNK0          = $A1           ; PBR for NES bank $00; NES bank N -> CHUNK0+N
                                ;
                                ; $A1 rather than $81 on purpose.  A HiROM cart
                                ; is only guaranteed to decode its SRAM at
                                ; $6000-$7FFF in banks $20-$3F and $A0-$BF;
                                ; $80-$9F is open bus on many boards.  In a 2MB
                                ; image bank $A0+n mirrors $80+n exactly, so
                                ; running up there costs nothing and puts the
                                ; NES's PRG-RAM somewhere it certainly exists.

;  Chunk numbers above the NES's sixteen.  Chunk N runs at PBR CHUNK0+N, and
;  in a 2MB image that masks to ROM image bank 1+N, so the usable range is
;  chunks $00..$1E (PBR $A1..$BF).  $00..$0F are the NES's own banks; chunk $10
;  is spoken for because image bank 17 is the altar beam's HDMA tables
;  (BEAMBANK), which is why the first bank this project adds is $11 rather than
;  $10.  mkrom stamps the fixed bank into $C000-$FFFF of every one of them, so
;  a routine here sees the same address space the game's own banks do and
;  reaches the fixed bank with a plain 16-bit JSR.
CHUNK_OPT       = $11           ; the options bank: menu, presets, option block
OPTFAR          = (CHUNK0 + CHUNK_OPT) * $10000
CHUNK_CREDITS   = $12           ; the credits screen, native code and mode 7
CREDITSFAR      = (CHUNK0 + CHUNK_CREDITS) * $10000
CHUNK_RANDO     = $13           ; the randomizer: PRNG, generator, its hooks
RANDOFAR        = (CHUNK0 + CHUNK_RANDO) * $10000
CHUNK_OPTTEXT   = $14           ; the settings screen's descriptions; data only
CHUNK_LOGIC     = $15           ; the vanilla world's logic, for placement; data only
LOGICFAR        = (CHUNK0 + CHUNK_LOGIC) * $10000
CHUNK_WORLD     = $16           ; entrance shuffle: the shuffle and the seed's logic
WORLDFAR        = (CHUNK0 + CHUNK_WORLD) * $10000
CHUNK_ROLL      = $17           ; New Game's roll screen: picture, bleeps, fanfare
ROLLFAR         = (CHUNK0 + CHUNK_ROLL) * $10000

;  The credits screen's variables and HDMA buffers.  The game's RAM, the
;  HAL's and every shadow are in bank $7E; the one thing in $7F is the ending
;  scene's draw buffer at THEENDBUF, $6800-$6EFF, which is never live while the
;  title screen is.  The credits keep to the bottom of the bank regardless.
;  Reset zeroes it with the rest of WRAM.
CREDITSRAM      = $7F0000

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The ending scene's draw buffer, moved out of PRG-RAM
;;
;;  'The End' plots itself a pixel at a time and needs a RAM shadow of the CHR
;;  it is drawing into, because it read-modify-writes each byte.  On the NES
;;  that shadow sat at $6800 for $700 bytes, overlaid on the battle RAM -- the
;;  two are never live at once, so the overlap costs nothing.
;;
;;  It is moved here so the 256 bytes at $6E00-$6EFF come free.  That page is
;;  the only part of the 8KB the ending buffer claims *alone*: everything below
;;  it is also battle RAM or the lineup menu's stat copies (lutmp_ch_magic is a
;;  full page at $6D00, so $6DB2 is NOT free -- rearranging the party would
;;  overwrite anything put there).  $6E00 is what the option block uses.
;;
;;  EVERY PATCH TO A GAME BANK MUST BE BYTE-NEUTRAL.  The banks position their
;;  data by sequential assembly -- there is no .org and no .res -- and other
;;  banks reach that data through absolute addresses baked into Constants.inc
;;  (lut_OrbCHR = $B600 in this very bank) and through pointer tables inside
;;  the data itself.  Shrinking this scene's clear loop by 24 bytes moved the
;;  orb CHR, the story text and the credits, which showed up as wrong orb
;;  graphics and text strings missing their first 24 characters.  convert.py
;;  now asserts every .INCBIN lands on the address its filename states, so a
;;  size change is a build error rather than a corrupted image.
THEENDBANK      = $7F
THEENDBUF       = $6800         ; same 16-bit address as before, but in bank
                                ; $7F.  Keeping the offset identical is what
                                ; lets TheEnd_SetPixel's "+ $6000" stand and
                                ; keeps both patches byte-for-byte the same
                                ; size as the code they replace -- see below.

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The option block
;;
;;  Battery-backed, global, and deliberately outside the save block at
;;  $6400-$67FF: SaveGame copies that range wholesale out of unsram and
;;  VerifyChecksum sums exactly those $400 bytes, so anything living there
;;  would be per-save and would fight the game's own checksum.  Options are
;;  global and survive starting a new game.
;;
;;  Integrity is the game's own scheme -- two assertion bytes and a sum forced
;;  to $FF -- plus a format version, because an option block changes shape
;;  between builds and a stale block that still checksums is worse than one
;;  that is obviously absent.  A version mismatch falls back to a preset.
OPTBLOCK        = $6E00
OPT_MAGIC0      = OPTBLOCK+$00  ; $53 'S'
OPT_MAGIC1      = OPTBLOCK+$01  ; $46 'F'
OPT_VERSION     = OPTBLOCK+$02  ; OPT_FORMAT below
OPT_PRESET      = OPTBLOCK+$03  ; 0..2 preset, 3 = custom
OPT_FLAGS       = OPTBLOCK+$04  ; 6 bytes: one bit per checkbox.  Four was
                                ; enough until the Treasures section took bits
                                ; 26-30 and the free key items 31-33; five
                                ; until TRANCE's took bit 40.
OPT_FLAGBYTES   = 6
OPT_GOLDXP      = OPTBLOCK+$0A  ; step indices into the value-row tables
OPT_ENCOUNTER   = OPTBLOCK+$0B
OPT_ENEMY       = OPTBLOCK+$0C
OPT_BOSS        = OPTBLOCK+$0D
OPT_ELEMDMG     = OPTBLOCK+$0E  ; ...and the fifth, which is why the format
                                ;   went to 4
OPT_THIEFHIT    = OPTBLOCK+$0F  ; the sixth: Thief and Ninja hit growth, which
                                ;   was bit 21 until it took a third value.
                                ;   The scalars are in the block, rather than
                                ;   with the new-game rows, because a preset
                                ;   writes them: opt_loadpreset copies from
                                ;   OPT_FLAGS up to OPT_RESPOND.
OPT_STARTITEMS  = OPTBLOCK+$10  ; the seventh: which of FFR's starting sets
OPT_RESPOND     = OPTBLOCK+$11  ; 0-based, so the default 8 is stored as 7
OPT_CKSUM       = OPTBLOCK+$12
OPT_SIZE        = $13

OPT_MAGIC0_VAL  = $53
OPT_MAGIC1_VAL  = $46
OPT_FORMAT      = $09           ; bumped from $08: the Free items left the
                                ; flag word for the new-game rows, which grew
                                ; by the key item rows, packed (RANDO_KEYITEMS).
                                ; Bumped from $07: the flag word took a
                                ; sixth byte, for TRANCE's element, so every
                                ; scalar moved.
                                ; Bumped from $06: the starting items took
                                ; a seventh scalar, and the respond rate and
                                ; checksum moved up a byte again.
                                ; Bumped from $05: Thief and Ninja hit
                                ; growth became a scalar, so the respond rate
                                ; and the checksum moved up a byte.
                                ; Bumped from $04: the checksum now covers
                                ; the new-game rows at OPT_NG, so a block
                                ; written before them would fail anyway --
                                ; the bump says why.
                                ; Bumped from $03: the elemental bonus
                                ; became a dial and needed a fifth scalar.
                                ; Bumped from $02 before that: the flag word grew a
                                ; fifth byte, so every field after it moved.
                                ; A block written by an older build would read
                                ; its value rows out of the flags.
;  Previously, bumped from $01: blocks written before the
                                ; options bank set its data bank correctly hold
                                ; garbage flags behind a valid checksum, so the
                                ; version is what retires them.  Bump this
                                ; whenever the block's meaning changes, not
                                ; just its layout.
OPT_RESPOND_DEFAULT = 7         ; 0-based, so this is the 8 the menu shows

;  The option flags, one bit each.  Here rather than in optbank.asm because a
;  feature's hook is wherever the feature lives -- the fixed bank and the game
;  banks test these too, not just the options bank.
;
;  Bits 0..7 are in OPT_FLAGS+0, 8..15 in +1, and so on, so a test is
;  "LDA OPT_FLAGS+n / AND #mask".  The OPTFB_/OPTFM_ pairs below give the
;  byte and the mask for the ones that have hooks so far.
;  Flag bits, low byte first.  These are the first 32; the Treasures bits
;  past them are in the fifth byte and are named OPTFB_/OPTFM_ only.
OPTF_SPEEDHACKS   = $00000001
OPTF_FASTWALK     = $00000002
OPTF_FASTSHIP     = $00000004
OPTF_NOSHUFFLE    = $00000008
OPTF_IDTREASURE   = $00000010
OPTF_OPENCHESTS   = $00000020
OPTF_BUYQTY       = $00000040
OPTF_RUNWAIT      = $00000080
OPTF_MAGICWRAP    = $00000100
OPTF_AUTORETARGET = $00000200
OPTF_AUTOSORT     = $00000400
OPTF_REPEATPOTION = $00000800
OPTF_SHOPINFO     = $00001000
OPTF_CHESTINFO    = $00002000
OPTF_GUILLOTINE   = $00004000
OPTF_HOUSEMP      = $00008000
OPTF_WEAPONSTATS  = $00010000
OPTF_SPELLFIXES   = $00020000
OPTF_STATUSATK    = $00040000
OPTF_THIEFNINJA   = $00080000
OPTF_CRITRATE     = $00100000
OPTF_SOFTBTL      = $00200000   ; was the elemental bonus, then Thief hit
OPTF_IMPCURE      = $00400000
OPTF_IMPFIRE      = $00800000
OPTF_CASTLIFE     = $01000000
OPTF_LOK2         = $02000000

;  The three groups, as the menu lists them.  ca65 has no line continuation,
;  so these are built up a group at a time rather than written as one run-on.

;  Byte and mask for each flag that something outside the options bank tests.
;  Derived bytes, recomputed by opt_derive whenever the block changes.
;
;  A feature whose only effect is a constant is cheapest to implement by
;  turning that constant into a load -- but the constants live in code that is
;  reached far too often to test a flag at.  So the flags are cooked down once,
;  here, and the use site just loads a byte.
OPTD            = OPTBLOCK+$13  ; the derived block, just above the option block
OPTD_WIPEOPEN_U = OPTD+$00      ; ScreenWipe_Open's two step sizes...
OPTD_WIPEOPEN_D = OPTD+$01
OPTD_WIPECLOSE_D= OPTD+$02      ; ...and ScreenWipe_Close's
OPTD_WIPECLOSE_U= OPTD+$03
OPTD_DLGOPEN    = OPTD+$04      ; the dialogue box's two step sizes
OPTD_DLGCLOSE   = OPTD+$05
OPTD_BTLTRANS   = OPTD+$06      ; how long the battle transition runs
OPTD_LINEUP     = OPTD+$07      ; pixels per frame in the lineup menu
OPTD_PALCYC     = OPTD+$08      ; frame mask for the palette cycle
OPTD_MSGROWS    = OPTD+$09      ; message rows drawn per frame, opening
OPTD_MSGROWSREV = OPTD+$0A      ; ...and closing
OPTSCRATCH      = OPTBLOCK+$20  ; a byte the option code may use freely

;  A derived byte that did not fit in the block above.  OPTD's sixteen run to
;  OPTBLOCK+$1F and the settings screen took the last five for its own scratch
;  before this was needed, so the derived block continues on the far side of
;  OPTSCRATCH.  Contiguity buys nothing -- every use site names the byte.
OPTD_ELEMDMG    = OPTBLOCK+$21  ; base-damage bonus for hitting a weakness
OPTFIXSP        = OPTBLOCK+$22  ; opt_spellfixed: the spell it was asked about
OPTFIXFD        = OPTBLOCK+$23  ; ...and the field

;  opt_scalereward's accumulator: the reward times up to ten, which needs a
;  byte past the reward's three.  It used OPTSCRATCH and the three bytes after
;  it, and the first of those is OPTD_ELEMDMG -- so every battle that ended
;  with Gold/XP off 100% left the weakness bonus at a byte of the reward until
;  the options were next committed (found 2026-10-09).  Its own four now.
OPTREWARD       = OPTBLOCK+$24  ; 4 bytes, low byte first

;  The three spell flags.
OPTFB_SPELLFIX  = OPT_FLAGS+2
OPTFM_SPELLFIX  = $02    ; bit 17
OPTFB_CASTLIFE  = OPT_FLAGS+3
OPTFM_CASTLIFE  = $01    ; bit 24

;  How FFR's replacement BtlMag_Effect_CureAilment tells the two Life spells
;  apart, and we follow it: the effectivity byte, which for every other
;  CureAilment spell is a real ailment mask.  Vanilla's three are LAMP ($08),
;  PURE ($04) and AMUT ($40), so neither value can collide.
CASTLIFE_LIFE   = $01           ; ...which is AIL_DEAD, and also the mask
CASTLIFE_LIF2   = $81           ; ...and this is not a mask at all, just a tag
CASTLIFE_HP     = $10           ; what LIFE leaves them standing with
BTLMAG_CUREAILMENT = $08        ; the effect id both Life spells borrow
OPTFB_LOK2      = OPT_FLAGS+3
OPTFM_LOK2      = $02    ; bit 25

;  SOFT in battle, FFR's EnableSoftInBattle: the SOFT spell and the SOFT
;  potion both work in battle.  The spell is Cast Life's pattern again --
;  FFR's record, cure ailment on AIL_STONE, plus the message and targeting
;  hooks Life already has.  The potion is a third row in the DRINK box,
;  which in vanilla knows of exactly two.  Bit 21: no row or preset has set
;  it since Thief hit became a scalar, so a block that predates it reads off.
OPTFB_SOFTBTL   = OPT_FLAGS+2
OPTFM_SOFTBTL   = $20    ; bit 21
SOFTBTL_MASK    = $02           ; AIL_STONE: the record's effectivity
DRINK_SOFT      = 2             ; the SOFT row: 0 HEAL, 1 PURE, 3 empty
DRINK_ROWS      = 3
ITEM_HEAL       = $19           ; item ids: item_heal - items, and the next two
OPTBTLSOFT      = OPTBLOCK+$1E  ; the battle's SOFT count, beside btl_potion_heal
                                ;   and _pure, which have $6BB1 (battle_bank)
                                ;   after them; set at every battle's start
OPTDRINKROW     = OPTBLOCK+$1F  ; which DRINK row opt_drinkrow builds next
.assert OPTD + $0B <= OPTBTLSOFT, error, "the derived block runs into the battle's SOFT count"
.assert OPTDRINKROW < OPTSCRATCH, error, "the DRINK row counter runs into OPTSCRATCH"
.assert OPT_SIZE <= OPTD - OPTBLOCK, error, "the option block runs into the derived block"

;  White Mage HARM, FFR's WhiteMageHarmEveryone: HARM spells cast or used by
;  a White Mage or White Wizard damage anything, not only the undead.  Bit 37,
;  in the fifth byte with the free key items; nothing set it before, so a
;  block that predates it reads off.
OPTFB_WMHARM    = OPT_FLAGS+4
OPTFM_WMHARM    = $20    ; bit 37

;  Run chance fix, FFR's ChanceToRun "Corrected": running is luck against
;  rand[0, level + 15], and the original reads the level through the in-battle
;  stat pointer, where that offset is not the level -- Disch: "the ailment
;  byte for 2 players after this one (for top 2 slots) or other garbage".
;  The flag reads it through the out-of-battle one, as FFR's one-byte patch
;  does.  Bit 38; nothing set it before.
OPTFB_RUNFIX    = OPT_FLAGS+4
OPTFM_RUNFIX    = $40    ; bit 38

;  Turn order fix, FFR's ImproveTurnOrderRandomization: DoBattleRound shuffles
;  the turn order by swapping two random entries seventeen times, which leaves
;  each entry where it started more often than chance -- and the list starts
;  enemies first, party last.  The flag makes it a Fisher-Yates walk, as FFR's
;  rewrite does, so every order is equally likely.  Bit 39.
OPTFB_TURNFIX   = OPT_FLAGS+4
OPTFM_TURNFIX   = $80    ; bit 39

;  TRANCE status element, FFR's TranceHasStatusElement: the enemy skill TRANCE
;  (attack $51), which paralyzes the whole party, gets the status element, so
;  a Ribbon resists it.  Its record has no element; the flag supplies FFR's
;  one byte through opt_magicdata, as the spell flags supply theirs.  Bit 40,
;  the sixth flag byte's first.
OPTFB_TRANCE    = OPT_FLAGS+5
OPTFM_TRANCE    = $01    ; bit 40
ATTACK_TRANCE   = $51
ELEM_STATUS     = $01           ; FFR's SpellElement.Status

;  Asshole Kraken (user, 2026-10-14; not FFR's): Kraken and Kraken 2 spend
;  every turn hitting a White Mage or White Wizard, while one can be hit
;  (opt_kraken).  Bit 43, in the sixth byte after the Lefein edits; no build
;  has set it before, so every saved block reads off.
OPTFB_KRAKEN    = OPT_FLAGS+5
OPTFM_KRAKEN    = $08    ; bit 43
ENEMY_KRAKEN    = $7B           ; the Sea Shrine's fiend
ENEMY_KRAKEN2   = $7C           ; ...and its return in the Temple of Fiends

;  Standard map edits: tiles written over a map as it loads, when a flag asks
;  (opt_mapedits, lut_MapEdits).  The first two are FFR's Lefein shops, both
;  quality of life here (user, 2026-10-13): Lefeinish Hospitality, Crescent
;  Lake's Inn and Clinic doors on two of Lefein's houses, and Add Lefein
;  SuperStore, its magic shop widened to the doors of every town's white and
;  black magic shops but Gaia's.  Bits 41 and 42.
;  Ordeals pillars, FFR's OrdealsPillars: a RANDOMIZATION row, dealt from the
;  seed (rando.asm, deal_ordeals) and written over Castle of Ordeals 2F as it
;  loads.  Each pillar pad's tile is its destination -- $4C-$54 land in one
;  room each, $55 leads on -- so dealing tiles to the fifteen pads rewires the
;  maze.  FFR also moves teleport $3C, tile $54's, to land in the room that
;  vanilla never reaches, so that room can join the chain.
ORDEALS_OFF     = 0
ORDEALS_SHUFFLE = 1
ORDEALS_MODES   = 2

;  Key items (RANDO_KEYITEMS): where they stay, or which incentive spots they
;  go to -- Standard, FFR's default: the 13 reward NPCs, the caravan and the
;  seven *Major chests but Volcano's; Wide, Free Enterprise's 25.
KEYITEMS_VANILLA  = 0
KEYITEMS_STANDARD = 1
KEYITEMS_WIDE     = 2
KEYITEMS_MODES    = 3
;  Map shuffle (RANDO_ENTRANCES), under Key items Standard or Wide only, as in
;  FFR: rando_place clears it under Vanilla, or when no wiring places.
ENTRANCES_OFF   = 0               ; vanilla wiring
ENTRANCES_ONLY  = 1               ; FFR's entrance shuffle, floors kept
ENTRANCES_FLOORS = 2              ; ...and its floor shuffle
ENTRANCES_MODES = 3
;  Each item row (RANDO_ITEMS): an incentive, loose, or given at the start.
;  Other items, the nine with no Free, has the first two only.
ITEM_INCENTIVE  = 0
ITEM_LOOSE      = 1
ITEM_FREE       = 2
ITEM_MODES      = 3
ITEMOTHER_MODES = 2
ITEMROW_SHIP    = 0
ITEMROW_AIRSHIP = 1               ; its item is the FLOATER
ITEMROW_BRIDGE  = 2
ITEMROW_CANAL   = 3
ITEMROW_CANOE   = 4
ITEMROW_KEY     = 5
ITEMROW_CHIME   = 6
ITEMROW_CROWN   = 7
ITEMROW_LUTE    = 8
ITEMROW_TAIL    = 9
ITEMROW_ROD     = 10
ITEMROW_OTHER   = 11
ITEMROWS        = 12
;  Gear rows (RANDO_GEAR): Treasure, or an incentive.
GEAR_TREASURE   = 0
GEAR_INCENTIVE  = 1
GEAR_MODES      = 2
GEARROW_MASMUNE = 0
GEARROW_KATANA  = 1
GEARROW_VORPAL  = 2
GEARROW_DEFENSE = 3
GEARROW_OPAL    = 4               ; the Opal Bracelet
GEARROW_POWER   = 5               ; the Power Gauntlet
GEARROW_WHITE   = 6               ; the White Shirt
GEARROW_RIBBON  = 7
GEARROW_XCALBER = 8
GEARROWS        = 9
;  The Early flags (RANDO_EARLY): the King, Sarda and the Canoe Sage give
;  without the event they wait for, and the Ordeals' thrones need no CROWN.
EARLY_KING      = $01
EARLY_SARDA     = $02
EARLY_SAGE      = $04
EARLY_ORDEALS   = $08
EARLY_MODES     = 2               ; each a row, Off / On
;  Early Ordeals' two tiles: the thrones, in the Castle tileset.
TS_CASTLE       = 1
THRONE_TILE1    = $61
THRONE_TILE2    = $62
MAP_ORDEALS2F   = 25
ORD_ROOMS       = 9             ; the start room and the eight it shuffles
ORD_PADS        = 15
ORD_EXIT        = $55           ; the tile that leads on to the stairs
ORD_LOST_TELE   = $3C           ; tile $54's teleport...
ORD_LOST_X      = $10           ; ...and where FFR has it land
ORD_LOST_Y      = $12

OPTFB_LEFEINSHOPS = OPT_FLAGS+5
OPTFM_LEFEINSHOPS = $02  ; bit 41
OPTFB_SUPERSTORE  = OPT_FLAGS+5
OPTFM_SUPERSTORE  = $04  ; bit 42
MAP_LEFEIN        = 7
DRINK_SEL       = $6B7D         ; vanilla's two temporaries for the DRINK
DRINK_ID        = $6856         ;   choice, unnamed in variables.inc

;  Spell indices, as FFR's enum numbers them.
SPELL_LOCK      = 6
SPELL_LOK2      = 23
SPELL_HEL2      = 35
SPELL_CUR4      = 48
SPELL_SABR      = 54
SPELL_LIFE      = 33
SPELL_SOFT      = 40
SPELL_LIF2      = 56

;  The defender's hit rate during a magic attack.  variables.inc never named
;  it, because nothing ever loaded or saved it -- which is the TMPR/SABR bug:
;  BtlMag_Effect_AttackUp2 adds the spell's hit bonus to this address and
;  BtlMag_Effect_AttackUp adds its effectivity to the strength beside it, and
;  neither value arrives or leaves.
BTLMAG_DEFHIT   = $6884

;  Increase Elemental and Type Bonus.
;
;  A physical attack that matches the defender's elemental weakness or its
;  category gets two bonuses: +40 hit chance on a base of 168, and +4 base
;  damage on a base of the attacker's strength.  The first is a quarter of the
;  base and lands hard.  The second is nearly nothing -- a mid-game weapon
;  swings for forty or more, so four is under a tenth, and an elemental weapon
;  feels no different from an ordinary one of the same attack.
;
;  So this dial sets the damage half and leaves the hit half alone, which is
;  what FFR does too: IncreaseWeaponBonus in FF1Lib/Balances.cs is a single
;  byte write over the same immediate, and FFR exposes the number as a slider
;  rather than fixing it -- Items & Equipment, "Damage Bonus", 1 to 50, greyed
;  out until the checkbox above it is ticked.
;
;  This is a dial and not a checkbox for that reason.  FFR needs both because
;  it can grey a slider out; a list of rows cannot, and a checkbox that has to
;  be on for a dial elsewhere to mean anything is the sort of interaction this
;  menu has been avoiding.  Zero is the off position, which no checkbox could
;  reach -- vanilla is four, not nothing.
;
;  The step is two, so the stored index doubles into the derived byte and
;  opt_derive needs a shift rather than a table.
ELEMDMG_STEP    = 2
ELEMDMG_STEPS   = 26            ; +0 to +50
ELEM_VANILLA    = 2             ; +4, what the cartridge does
ELEM_FFR_DEF    = 15            ; +30, FFR's default preset and most others

;  Vanilla steps, and the speed-hack ones.  Open must divide 224 and close 220,
;  or the wipe overshoots its end condition and runs off.
WIPE_OPEN_U_SLOW  = 2
WIPE_OPEN_D_SLOW  = 4
WIPE_OPEN_U_FAST  = 8
WIPE_OPEN_D_FAST  = 16
WIPE_CLOSE_D_SLOW = 2
WIPE_CLOSE_U_SLOW = 4
WIPE_CLOSE_D_FAST = 10
WIPE_CLOSE_U_FAST = 20

;  The dialogue box grows from scanline 8 to $60 and retracts to below $12.
;  Both loops compare with BCC/BCS rather than for equality, so any step
;  terminates -- unlike the closing wipe, which tests CMP #1 exactly.
DLG_OPEN_SLOW   = 2
DLG_CLOSE_SLOW  = 3
DLG_OPEN_FAST   = 11
DLG_CLOSE_FAST  = 11

;  The battle transition runs a counter to this.  The noise sweep it plays
;  lasts $20, so below that the sound outlives the picture.
BTLTRANS_SLOW   = $41
BTLTRANS_FAST   = $11

;  Explosions per enemy, and the delay after running.  These live in banks
;  $0B and $0C, which have no free bytes, so the sites pass the vanilla value
;  in A and a stand-in in the fixed bank decides -- which keeps every call
;  site exactly the size of the "LDA #n / STA x" pair it replaces.
EXPLODE_FAST    = 4
RUNDELAY_FAST   = 4

;  The lineup menu slides characters between slots a pixel at a time.  Four of
;  the six sites compare for equality, so the step has to divide the distances
;  exactly or the sprite oscillates past its target forever.  The slots sit at
;  Y $38/$58/$78/$98 -- 32 apart -- and the horizontal moves cover 16, so 4
;  divides every one of them.  tools/test_options.py runs the animation to
;  convergence rather than taking that on trust.
LINEUP_SLOW     = 1
LINEUP_FAST     = 4

;  CyclePalettes ANDs a frame counter with this and steps the cycle when the
;  result is zero, so 3 is every fourth frame and 0 is every frame.
PALCYC_SLOW     = $03
PALCYC_FAST     = $00

;  The battle message buffer is twelve rows.  Opening draws one per frame and
;  closing two, so twelve frames and six; Speed Hacks makes it two and three,
;  for six and four.  Rows per frame rather than a frame count, because the
;  twelve rows have to be drawn either way -- shortening the count alone would
;  leave the box half drawn.
MSGROWS_TOTAL   = 12
MSGROWS_SLOW    = 1
MSGROWS_FAST    = 2
MSGROWSREV_SLOW = 2
MSGROWSREV_FAST = 3

;  Behaviour flags for a repositioned NPC: not in a room, and stationary.
;  ($80 is inroom, $40 is don't move -- see mapobj_flgs in variables.inc.)
NPCMOVE_FLAGS   = $40

OPTFB_SPEEDHACKS = OPT_FLAGS+0
OPTFM_SPEEDHACKS = $01

OPTFB_GUILLOTINE = OPT_FLAGS+1
OPTFM_GUILLOTINE = $40   ; bit 14

OPTFB_NOSHUFFLE = OPT_FLAGS+0
OPTFM_NOSHUFFLE = $08

OPTFB_MAGICWRAP = OPT_FLAGS+1
OPTFM_MAGICWRAP = $01    ; bit 8

OPTFB_AUTOSORT  = OPT_FLAGS+1
OPTFM_AUTOSORT  = $04    ; bit 10

OPTFB_AUTORETARGET = OPT_FLAGS+1
OPTFM_AUTORETARGET = $02 ; bit 9

OPTFB_RUNWAIT   = OPT_FLAGS+0
OPTFM_RUNWAIT   = $80    ; bit 7

OPTFB_IDTREASURE = OPT_FLAGS+0
OPTFM_IDTREASURE = $10   ; bit 4

OPTFB_STATUSATK = OPT_FLAGS+2
OPTFM_STATUSATK = $04    ; bit 18

OPTFB_HOUSEMP   = OPT_FLAGS+1
OPTFM_HOUSEMP   = $80    ; bit 15

;  Thief and Ninja hit-rate growth.
;
;  Every level adds a per-class constant to hit rate, from lut_LvlUpHitRateBonus
;  in bank $0B -- 3 for the Fighter, 2 for the Thief and Ninja, 1 for the mages.
;  FFR's ThiefHitBuff replaces the Thief's and the Ninja's, offering 1 through
;  5 from a dropdown; its names for them are "Useless", "Vanilla", "Moderate",
;  "Double" and "Ridiculous".  This row offers the middle three, as +2, +3 and
;  +4 a level: its Improved Vanilla preset uses Moderate and every other
;  preset of its own Double.  The step is what the hook adds on top of the
;  table's 2, so the table stays the only place the vanilla number lives.
;
;  It was a checkbox, bit 21, doing Double; bit 21 is unused again.
THIEFHIT_STEPS    = 3
THIEFHIT_VANILLA  = 0           ; +2 a level, the table's
THIEFHIT_MODERATE = 1           ; +3, FFR's Improved Vanilla
THIEFHIT_DOUBLE   = 2           ; +4, FFR's other presets
THIEF_HIT_VANILLA = 2           ; what lut_LvlUpHitRateBonus holds for TH and NJ

;  Starting items: FFR's StartingItemSet, its nine fixed sets.  Each sets the
;  counts of the six consumables, item_tent through item_soft, which a new
;  game otherwise starts at zero; so a set is a six-byte row copied over them
;  (lut_StartItems, optbank.asm).  FFR's six randomized sets are left out:
;  none of its presets uses one, and each would need a seeded roll at New
;  Game.  Its presets but Improved Vanilla use the Explorer Pack.
STARTITEMS_SETS     = 9
STARTITEMS_NONE     = 0
STARTITEMS_EXPLORER = 4

OPTFB_THIEFNINJA = OPT_FLAGS+2
OPTFM_THIEFNINJA = $08   ; bit 19

;  Better Thief and Ninja.
;
;  FFR's BuffThiefAGI raises the Thief's starting agility, makes agility go up
;  at every level rather than one time in four, and sets starting evade to
;  agility + 48 -- "to make it more viable as a first-slot character", says the
;  comment.  Vanilla is agility 10 and evade 58, and 58 is 10 + 48, so the
;  formula is the game's own relationship rather than FFR's invention.
;
;  FFR offers 30, 50, 80, 100 and 120 from a dropdown and its advanced default
;  is 80.  A checkbox here, at 80: unlike the elemental bonus there is no run
;  of values anyone tunes between, and the point of the flag is one decision.
;
;  It touches the Thief and not the Ninja, and so does FFR, because promotion
;  keeps the character's accumulated stats -- a Ninja is a Thief that grew.
;  The growth half does name both, since a promoted character levels on the
;  Thief's data but carries the Ninja's class id.
;
;  Not ported: FFR's separate ThiefHitBuff, which raises hit-rate growth for
;  both classes.  Different flag, different dropdown, and this checkbox is the
;  agility one.
THIEF_AGI_VANILLA = 10
THIEF_AGI_BUFFED  = 80
THIEF_EVA_BONUS   = 48          ; evade is agility plus this, in both cases

;  Where the level-up code keeps the stat-gain byte while it works on it.
;  bank $0B calls it @statbyte, which a cheap local cannot be imported by
;  name; after the three shifts the agility bit is $40.
LVLUP_STATBYTE    = $688E
LVLUP_AGI_BIT     = $40

OPTFB_REPEATPOTION = OPT_FLAGS+1
OPTFM_REPEATPOTION = $08 ; bit 11

OPTFB_BUYQTY    = OPT_FLAGS+0
OPTFM_BUYQTY    = $40    ; bit 6

;  Buy Quantity's working bytes, in the option block's spare page.  None of
;  them outlive a single purchase; they are here rather than in zero page
;  because the shop already uses most of it.
OPTSHOPQTY      = OPTBLOCK+$28  ; how many the player has dialled up
OPTSHOPPREV     = OPTBLOCK+$29  ; the d-pad last frame, for edge detection
OPTSHOPMAX      = OPTBLOCK+$2A  ; most we can charge for without overflowing
OPTSHOPUNIT     = OPTBLOCK+$2B  ; 2 bytes: the price of one
;  Where each number goes, so that changing the quantity redraws the digits
;  and not the boxes around them.
OPTSHOPTX       = OPTBLOCK+$2D  ; the total, in the message box
OPTSHOPTY       = OPTBLOCK+$2E
OPTSHOPQX       = OPTBLOCK+$2F  ; the count, in the command box
OPTSHOPQY       = OPTBLOCK+$30

;  Enemy/boss stat scaling.  FFR's RangeScale, with one percentage rather than
;  a range, reduces to  value * (1 + (p-1)*adj)  -- the random exponent drops
;  out when low and high are equal.  Our steps are 25% apart, so p = n/4 and
;  every scale is an exact fraction:
;
;      adjustment 1.00 (HP, evade, hit%)          n / 4
;      adjustment 0.50 (absorb, hits, crit%)    (n+4) / 8
;      adjustment 0.25 (damage)                (n+12) / 16
;
;  n is the step index plus one, so STAT_100 (3) gives n=4 and every fraction
;  is 1 -- which is FFR's "100% changes nothing" early exit, for free.
OPTSTATV        = OPTBLOCK+$32  ; 2 bytes: the value being scaled
OPTSTATNUM      = OPTBLOCK+$34  ; numerator
OPTSTATSH       = OPTBLOCK+$35  ; log2 of the denominator
OPTSTATACC      = OPTBLOCK+$36  ; 3 bytes of accumulator
OPTSTATN        = OPTBLOCK+$39  ; n for whichever of the two settings applies
OPTSTATSLOT     = OPTBLOCK+$3A  ; which enemy slot the scaling loop is on
OPTSTATREM      = OPTBLOCK+$3B  ; remainder, for rounding half to even
OPTSTATHALF     = OPTBLOCK+$3C
OPTSTATMASK     = OPTBLOCK+$3D
OPTFB_OPENCHESTS = OPT_FLAGS+0
OPTFM_OPENCHESTS = $20   ; bit 5

;  The lid drawn over an opened chest.  CHR $7E/$7F are referenced by no TSA
;  entry in any tileset, so mkrom lays the art there and this points at it.
OPENCHEST_UL    = $7E
OPENCHEST_UR    = $7F
;  Where on screen the chest being opened is.  Not doorppuaddr: the door code
;  deliberately leaves that standing between frames, and a chest opened during
;  a room transition would tread on it.
OPTCHESTADDR    = OPTBLOCK+$48  ; 2 bytes

OPTFB_IMPCURE   = OPT_FLAGS+2
OPTFM_IMPCURE   = $40    ; bit 22
OPTFB_IMPFIRE   = OPT_FLAGS+2
OPTFM_IMPFIRE   = $80    ; bit 23

;  Eight bytes of magic data, copied out of ROM so the buffs can edit it.
;  Battle_PrepareMagic hands everything downstream a pointer, so repointing it
;  here reaches every field without touching a single reader.
OPTMAGSHADOW    = OPTBLOCK+$40

;  opt_spellfixed's "did any of the eight fixes change the record?" -- which
;  record is OPTMAGSHADOW, beside it.  Moved from OPTBLOCK+$24 to make room
;  for OPTREWARD.
OPTFIXANY       = OPTBLOCK+$3F

;  The spell the magic menu is offering, 0-based.  The selection code
;  keeps it here while it works out what to prompt for.
btlmag_spellindex = $6B7D

OPTSTATOVF      = OPTBLOCK+$3E  ; bits 16-23 of the product: HP can
                                ;   exceed 16 bits before it is clamped

;  Which page of the battle magic list is showing, 0 or 1.  The disassembly
;  writes it as a bare address; it is named here because the option code needs
;  it too and a second bare $6AF8 would be unsearchable.
btl_magicpage   = $6AF8

PRESET_VANILLA  = 0
PRESET_IMPROVED = 1
PRESET_SUPER    = 2
PRESET_CUSTOM   = 3


; --- SNES PPU registers -------------------------------------------------
INIDISP         = $2100
OBSEL           = $2101
OAMADDL         = $2102
OAMADDH         = $2103
OAMDATA         = $2104
BGMODE          = $2105
MOSAIC          = $2106
BG1SC           = $2107
BG2SC           = $2108
BG3SC           = $2109
BG4SC           = $210A
BG12NBA         = $210B
BG34NBA         = $210C
BG1HOFS         = $210D
BG1VOFS         = $210E
BG2HOFS         = $210F
BG2VOFS         = $2110
BG3HOFS         = $2111
BG3VOFS         = $2112
M7SEL           = $211A         ; mode 7: the plane's wrap and flip
M7A             = $211B         ; mode 7 matrix, each written twice, low then
M7B             = $211C         ;   high.  BG1HOFS and BG1VOFS double as the
M7C             = $211D         ;   plane's scroll
M7D             = $211E
M7X             = $211F         ; centre of the transform, also written twice
M7Y             = $2120
VMAIN           = $2115
VMADDL          = $2116
RDVRAML         = $2139         ; VRAM read port, low / high
RDVRAMH         = $213A
VMADDH          = $2117
VMDATAL         = $2118
VMDATAH         = $2119
CGADD           = $2121
CGDATA          = $2122
W12SEL          = $2123
W34SEL          = $2124
WH0             = $2126
WH1             = $2127
WH2             = $2128
WH3             = $2129
WBGLOG          = $212A
WOBJLOG         = $212B
TM              = $212C
TS              = $212D
TMW             = $212E
TSW             = $212F
WOBJSEL         = $2125         ; OBJ and colour window enables
CGWSEL          = $2130
CGADSUB         = $2131
COLDATA         = $2132
SETINI          = $2133
APUIO0          = $2140         ; the four SPC700 I/O ports
APUIO1          = $2141
APUIO2          = $2142
APUIO3          = $2143


RDNMI           = $4210         ; bit 7 latches "a vblank has begun", set
                                ; whether or not NMI is enabled, and cleared by
                                ; reading it.  Clearing it at the end of a flush
                                ; and testing it on the next entry says whether a
                                ; whole hardware frame passed while the game was
                                ; working -- one the game never got to update,
                                ; which no counter indexed by WaitForVBlank
                                ; calls can see.
TIMEUP          = $4211
HVBJOY          = $4212
RDIO            = $4213

WRMPYA          = $4202         ; 8x8 -> 16 multiply: A x B lands in
WRMPYB          = $4203         ;   RDMPYL/H eight CPU cycles later
RDMPYL          = $4216
RDMPYH          = $4217

NMITIMEN        = $4200
WRIO            = $4201
MEMSEL          = $420D
MDMAEN          = $420B
HDMAEN          = $420C
JOY1L           = $4218
JOY1H           = $4219

; DMA channel 0
DMAP0           = $4300
BBAD0           = $4301
A1T0L           = $4302
A1T0H           = $4303
A1B0            = $4304
DAS0L           = $4305
DAS0H           = $4306

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  WRAM layout
;;
;;  $7E:0000-$07FF  NES RAM (also visible as $00:0000-$07FF -- the game's own)
;;  $7E:0800-$0FFF  free (NES never touches it; visible in bank $00 too)
;;  $7E:1000-$1FFF  free
;;  $7E:2000+       HAL private -- only reachable via long addressing / DBR=$7E
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

; ------------------------------------------------------------------------
;  HAL RAM.  $0800-$1FFF is WRAM that the NES game never touches, and it is
;  absolutely addressable from every bank we ever run code in (DBR is always
;  one of $81..$90, all of which expose the standard low-bank I/O map).
;  Anything bigger lives at $7E:2000+ and is reached with long addressing.
; ------------------------------------------------------------------------

HAL_VARS        = $0800         ; scalars, see halvars below
APUSHADOW       = $0900         ; $20 bytes: last value written to $4000-$401F
NTCOLLO         = $0940         ; $20 bytes: per-row dirty column low water mark
NTCOLHI         = $0960         ; $20 bytes: per-row dirty column high water mark
OAMSHADOW       = $0A00         ; 544 bytes: SNES OAM image (512 low + 32 high)
NTSHADOW        = $1000         ; 4KB: 64x32 tilemap words (NES rows 0..29 used)

;  Which altar the player stepped on, kept for the duration of the altar
;  effect.  It holds the tile's special code -- $18/$1A/$1C/$1E for
;  earth/fire/water/air -- captured from altareffect before DoAltarEffect
;  clears it.  $6D..$7B is a genuine hole in the NES variable map: nothing in
;  variables.inc names it and no instruction in any bank addresses it.
altarorb        = $006D

;  The altar beam, as the flush needs it: which scanline it starts on, how many
;  it covers, and whether it is running at all.  hal_altarband records these
;  once a frame from the game's own loop; flush_altar turns them into spans.
h_altaron       = HAL_VARS+$AB

;  The four altars' tile special codes, as altarorb carries them.  Named
;  separately from Constants.inc's TP_SPEC_*ORB because the generated banks
;  include both that and this, and ca65 will not have a symbol defined twice.
;  These are frozen NES data, so the two cannot drift apart in practice.
ORB_EARTH       = $18
ORB_FIRE        = $1A
ORB_WATER       = $1C
ORB_AIR         = $1E

;  How hard the beam adds light, as COLDATA's five-bit level.  Half is a
;  starting point to look at, not a tuned value.
ALTARLEVEL      = 16

;  What the two channels a tint does not own are lifted to.  Keeps a coloured
;  beam brightening rather than merely tinting; white ignores it, being all
;  three channels at ALTARLEVEL already.
ALTARFLOOR      = 6

;  The water orb's green, lifted above the floor to carry it from flat blue
;  toward cyan.  Its own constant rather than a shared one: the other three
;  tints read correctly with the floor alone, and blue is the one that needs
;  help, being the darkest channel to begin with.
ALTARWATERG     = 11

;  The same trick for the other two tints, each with its own step because each
;  wants a different amount.  Cyan wants its green close to its blue; orange
;  wants green at roughly half its red; a warmer green wants rather less red
;  than that.  One constant apiece, so none of them has to be a compromise.
ALTARFIREG      = 9
ALTAREARTHR     = 10

;  Half-width of the cone at its apex, and the table its edges are built in.
;  The apex sits under the player, who is always centred in this game, so the
;  beam is symmetric about x=128 and widens by one pixel each side every two
;  scanlines above that.  Two bytes a line, repeat-mode, so the worst case is
;  the tallest band the effect reaches -- 108 lines -- plus the spans above and
;  below it: well under the 240 bytes reserved before NTSHADOW at $1000.

;  How many scanlines share one half-width.  The table is built once a frame in
;  vblank, so its cost is the number of runs, not the height of the band: at one
;  run per two lines the flush overran vblank and put a black band across the
;  top of the picture, sliding down as the beam grew and back up as it shrank.
;  Eight lines a step makes the edge a staircase of four-pixel treads, which on
;  a beam this size reads as an edge rather than as steps -- and the original
;  was a hard-edged rectangle, so the aesthetic has room for it.

;  How far the whole band is lifted from where the NES put it.  The NES counts
;  its delay from the top of the frame and lands the bottom edge around
;  scanline 140, which is some 28 lines below the centre of the screen -- and
;  the player, who this game always keeps centred, is what the light is meant
;  to be rising out of.  Lifting the band by that much puts the apex under the
;  sprite, where a narrow tip disappears behind it.

;  Where the apex sits horizontally.  Not 128: the picture the port puts on
;  screen is not centred on the player quite the way a bare 256-pixel frame
;  would be, and 120 is what actually lines the tip up under the sprite.

;  Pulls the left edge in by this much without moving the right, so the cone
;  can sit on a half pixel.  120 read a shade right and 119 a shade left, and
;  there is nothing between them: trimming one side is the only way to split
;  the difference when the apex is an integer.

;  A band whose top lands within this many scanlines of the top of the screen
;  is taken all the way there, the band growing downward-fixed so its bottom
;  does not move.  Full expansion leaves the top around scanline 2, close
;  enough that whether it reached the edge looked inconsistent; this removes
;  the question rather than relying on the arithmetic landing on zero.
;  The beam's HDMA tables live in ROM, one per frame of the animation, built
;  by tools/genbeam.py and placed by mkrom.py at its own image bank.  HiROM
;  maps image bank N to SNES bank $C0+N.
BEAMBANK        = $D1
BEAMFAR         = $D10000

;  Where each variant's per-frame index array starts inside that bank.  Fixed
;  rather than packed so the HAL reaches either with one long-indexed load and
;  an eight-bit frame index.  Variant 0 is the plain beam; variant 1 is the
;  water orb's, which sways.  genbeam.py asserts the frame count still fits.
BEAMOFF0        = $0004         ; plain: earth and fire
BEAMOFF1        = $0100         ; water: a long, slow ripple
BEAMOFF2        = $0200         ; air: short crests, reading as rising smoke

h_altarframe    = HAL_VARS+$B4  ; which frame of the animation is showing
                                ; game's own height even when the band is not

;  A staging buffer for hal_ntblit, in the free WRAM below NESNT.  Callers
;  build a row of nametable bytes here and hand the whole run to the HAL at
;  once, instead of paying the thunk and the full $2007 conversion per tile --
;  which is the difference between a menu row costing a couple of hundred
;  cycles and costing several thousand.
NTSTAGE         = $7E3F00       ; 64 bytes, two more than a row needs
NTSTAGE_A       = $3F00         ; ...as seen with DBR = $7E, which is how the
                                ; blit reaches it, NESNT and NTSHADOW with
                                ; ordinary absolute addressing and both index
                                ; registers free

NESNT           = $7E4000       ; 2KB: raw NES nametable RAM (readback+attribs)
NESPAL          = $7E4800       ; $20 bytes: raw NES palette RAM
CGSHADOW        = $7E4900       ; 512 bytes: CGRAM image

CHRSHADOW       = $7E8000       ; 16KB: 512 tiles in SNES 4bpp order

; ------------------------------------------------------------------------
;  Graphics format
;
;  The NES stores a tile as eight bytes of bitplane 0 followed by eight bytes
;  of bitplane 1.  The SNES interleaves the planes by row.  Byte i of a NES
;  tile therefore lands at 2i for i < 8 and at 2i-15 for i >= 8 -- the same
;  permutation for 2bpp and 4bpp, only the tile stride differs.
;
;  The shadow keeps every tile in *4bpp* form, with bitplanes 2 and 3 left
;  permanently zero.  That costs 16KB of WRAM and 16KB of VRAM, and buys a
;  single copy of the pattern data that BG1 and the sprites can share: the NES
;  has 2bpp backgrounds and 2bpp sprites, the SNES has 4bpp for both in mode 1,
;  and the low two planes of a 4bpp tile are bit-for-bit a 2bpp tile.
; ------------------------------------------------------------------------

; --- SNES VRAM layout (word addresses) ----------------------------------
VRAM_BG1MAP     = $0000         ; $0000-$0FFF  64x64 tilemap, 4 x $400 words
VRAM_BG3MAP     = $1000         ; $1000-$13FF  32x32 tilemap (dialog window)
VRAM_CHR        = $2000         ; $2000-$3FFF  512 tiles, 4bpp (16KB)
                                ;   BG1 char base  = $2000  (tiles 0-255)
                                ;   OBJ name base  = $2000, gap 0
                                ;     -> OBJ tiles 0-255 at $2000 (NES table 0)
                                ;        OBJ tiles 256-511 at $3000 (table 1)

; ------------------------------------------------------------------------
;  CGRAM
;    BG palette p, colour c  ->  entry p*16 + c        (p = 0..3, c = 0..3)
;    OBJ palette p, colour c ->  entry 128 + p*16 + c
;    Entry 0 doubles as the backdrop, which is what NES $3F00 means.
; ------------------------------------------------------------------------

; ------------------------------------------------------------------------
;  HAL scalars
; ------------------------------------------------------------------------
h_ppuctrl       = HAL_VARS+$00  ; soft $2000
h_ppumask       = HAL_VARS+$01  ; soft $2001
h_addr          = HAL_VARS+$02  ; 2 bytes: PPU address, as set through $2006
h_latch         = HAL_VARS+$04  ; $2005/$2006 first-or-second write toggle
h_scrollx       = HAL_VARS+$05
h_scrolly       = HAL_VARS+$06
h_readbuf       = HAL_VARS+$07  ; the PPU's one-byte $2007 read delay
h_data          = HAL_VARS+$08  ; 2 bytes: the byte currently being written
h_t0            = HAL_VARS+$0A  ; 2-byte scratch
h_t1            = HAL_VARS+$0C
h_t2            = HAL_VARS+$0E
h_chrlo         = HAL_VARS+$10  ; 2 bytes: dirty span in the pattern shadow
h_chrhi         = HAL_VARS+$12
h_t6            = HAL_VARS+$14  ; 2-byte scratch (nt_attr's row offset)
h_ntdirty       = HAL_VARS+$16  ; nonzero if any tilemap row changed
h_oamdirty      = HAL_VARS+$18
h_curbank       = HAL_VARS+$19  ; the NES PRG bank currently selected
h_frame         = HAL_VARS+$1A  ; 2 bytes
h_spr0hit       = HAL_VARS+$1C  ; synthesised $2002 bit 6

; ------------------------------------------------------------------------
;  HAL scalars (continued)
; ------------------------------------------------------------------------
h_t3            = HAL_VARS+$20  ; 2-byte scratch
h_t4            = HAL_VARS+$22
h_t5            = HAL_VARS+$24
h_paldirty      = HAL_VARS+$26  ; nonzero when NES palette RAM has changed
h_sprtable      = HAL_VARS+$27  ; 0 or 1: OBJ tile-number high bit
h_pal           = HAL_VARS+$2A  ; 4 bytes: expanded attribute palette bytes
h_row           = HAL_VARS+$2E  ; 2 bytes
h_col           = HAL_VARS+$30  ; 2 bytes
h_c0            = HAL_VARS+$34  ; 2 bytes: dirty span, first column
h_c1            = HAL_VARS+$36  ; 2 bytes: dirty span, last column
h_joyshift      = HAL_VARS+$3A  ; serial shift register for raw $4016 reads

WRAMBANK        = $7E           ; DMA source bank for anything in WRAM

; Scanlines cropped from the top of the NES's 240-line picture, matching what a
; television hid.  The SNES's 224 lines then show NES lines 8..231.
NES_TOP_CROP    = 8

h_emphasis      = HAL_VARS+$3B  ; $2001 bits 7-5, as R/G/B in bits 2-0
h_greyscale     = HAL_VARS+$3C  ; $2001 bit 0


; DMA channel 1, used for the raster-split HDMA
DMAP1           = $4310
BBAD1           = $4311
A1T1L           = $4312
A1B1            = $4314

; DMA channel 4, used for the altar beam's window edges
DMAP4           = $4340
BBAD4           = $4341
A1T4L           = $4342
A1B4            = $4344

SLHV            = $2137         ; reading it latches the H/V counters
OPVCT           = $213D         ; vertical counter
STAT78          = $213F         ; reading it resets the counter read toggle

;  The last scanline at which hal_waitvbl will still serve a vblank it arrived
;  inside of, rather than waiting for the next one.  Vblank runs to line 261,
;  so this leaves 17 lines; a walking frame's flush measures about 15, and the
;  arrivals this is meant to catch land around 237.  Raising it risks a flush
;  running past the end of vblank and writing VRAM into the live picture, so
;  the flush's finishing line is worth re-measuring after any change to it.
LATE_FLUSH_LAST = 244

h_rastercount   = HAL_VARS+$3D  ; mid-frame $2001 writes recorded this frame
h_tmcur         = HAL_VARS+$3E  ; TM as of the most recent $2001 write
RASTERLINE      = $0980         ; 16 entries: scanline of each split
RASTERTM        = $0990         ; 16 entries: TM value from that split
HDMATAB         = $09A0         ; the HDMA table we build from them
                                ; channel so the two can be live together.
                                ; $0C20 is past OAMSHADOW's 544 bytes at $0A00
                                ; and short of NTSHADOW at $1000.
h_prevmask      = HAL_VARS+$3F  ; $2001 as it was before the current write
h_tmframestart  = HAL_VARS+$40  ; TM in force at the top of the frame

; The game's zero-page scratch (variables.inc calls it tmp, 16 bytes).  The
; screen-wipe band is described by tmp+4 and tmp+5, which hal_wipewindow reads.
NES_mapflags    = $002D         ; bit 1 set means a column is being drawn

; The game's attribute draw buffers (variables.inc puts draw_buf at $0780).
; DrawMapAttributes walks these, and hal_drawattr walks them in its place.
DRAW_ATTR       = $07C0         ; the attribute bits wanted
DRAW_AT_HI      = $07D0         ; destination address, high byte...
DRAW_AT_LO      = $07E0         ; ...and low
DRAW_AT_MSK     = $07F0         ; which bits of the byte to replace

NES_tmp         = $0010

; How far below tmp+4 the wipe band's first visible line sits.  The game counts
; tmp+4 from roughly eleven scanlines before its picture begins -- that is what
; the "122+11" in ScreenWipe_Open is for -- and this port crops the NES's top
; eight lines, so the band starts WIPE_LEAD lines further down in SNES terms.
WIPE_LEAD       = 11 + NES_TOP_CROP

; The game's own soft copy of $2000, at zero page $FF (variables.inc calls it
; soft2000).  The NES build's NMI handler pushed this to the PPU every frame.
NES_soft2000    = $00FF

; Raster splits: record mid-frame $2001 writes, replay them as an HDMA table.
;
; This does NOT reproduce the map-transition wipe, whatever an earlier version of
; this comment claimed.  It never did: when it was last on, the effect was
; flickery and opened from the wrong place on the screen, and measurement since
; says why.  The game brackets its visible window with three $2001 writes a
; frame -- off, on, off -- and only one of them lands during active display, at
; scanline 7, reading "background on".  The other two fall in vblank and are
; skipped, correctly.  A table built from that can never turn the background off,
; so the screen stays lit; and the one split it does catch is nowhere near where
; the game means it to be.
;
; The cause is geometry, not a coding slip.  The game counts its waits from where
; its own WaitForVBlank returned, on a 240-line picture, after a prep step
; calibrated to about eleven scanlines -- which is what the "122+11" in
; ScreenWipe_Open is for.  Here the wait returns at a different raster position,
; the flush has eaten a variable slice of vblank first, and the picture is
; cropped to 224 lines.  The counts cannot land where the game intends.
;
; So the split positions are not recoverable from the game's cycle-counted
; waits, and no amount of fixing would change that.  The wipe is drawn instead
; from the two variables the game already keeps -- see hal_wipewindow.

; DMA channel 2, used for the dialogue box's nametable split
DMAP2           = $4320
BBAD2           = $4321
A1T2L           = $4322
A1B2            = $4324

;  HDMA channels 5, 6 and 7 belong to the credits screen, which drives the
;  text's colour and the mode 7 matrix with them.  The HAL uses 1, 2 and 4,
;  and turns HDMAEN over every frame from its own channels alone, so the two
;  never meet.
DMAP5           = $4350
BBAD5           = $4351
A1T5L           = $4352
A1T5H           = $4353
A1B5            = $4354
DMAP6           = $4360
BBAD6           = $4361
A1T6L           = $4362
A1T6H           = $4363
A1B6            = $4364
DMAP7           = $4370
BBAD7           = $4371
A1T7L           = $4372
A1T7H           = $4373
A1B7            = $4374
DASB7           = $4377         ; indirect HDMA: the bank its data comes from

; A mid-frame $2000 write swaps which nametable is on screen.  With vertical
; mirroring the two nametables sit side by side in one 64-wide tilemap, so the
; SNES equivalent is simply adding 256 to the horizontal scroll -- which HDMA
; can do per scanline.
NTSPLITLINE     = $0920         ; 8 entries: scanline of each split
NTSPLITLO       = $0928         ; 8 entries: horizontal scroll, low byte
NTSPLITHI       = $0930         ; 8 entries: ...and high byte
HOFSTAB         = $0C20         ; the HDMA table built from them

h_ntsplits      = HAL_VARS+$41  ; mid-frame $2000 writes recorded this frame
h_prevctrl      = HAL_VARS+$42  ; $2000 as it was before the current write
h_hofsframestart = HAL_VARS+$43 ; 2 bytes: scroll in force at the top of frame
h_rasterwin     = HAL_VARS+$46  ; nonzero while a deliberate raster split is due
h_ntsrc         = HAL_VARS+$47  ; 2 bytes: tilemap shadow address being sent
h_vdst          = HAL_VARS+$49  ; 2 bytes: tilemap row base being written
h_vdst0         = HAL_VARS+$4B  ; 2 bytes: ...for the copy at row r
h_vdst1         = HAL_VARS+$4D  ; 2 bytes: ...and the copy at row r+30
h_ntsrc2        = HAL_VARS+$4F  ; 2 bytes: source address of the span in flight
NESPALPREV      = $7E4820       ; 32 bytes: palette as CGRAM last saw it
h_palforce      = HAL_VARS+$51  ; rewrite every CGRAM entry, not just changes
GATHERBUF       = $0C80         ; 128 bytes: one tilemap column, made contiguous
h_gcol          = HAL_VARS+$53  ; 2 bytes: column being sent
h_gcount        = HAL_VARS+$55  ; 2 bytes: loop counter / dirty row tally
h_ncols         = HAL_VARS+$57  ; 2 bytes: columns left to send

h_apuseq        = HAL_VARS+$6E  ; audio packet sequence number
h_apuok         = HAL_VARS+$6F  ; nonzero once the SPC700 program answered
h_swpcnt        = HAL_VARS+$B6  ; TRISWEEP: frames the current pitch has held
h_swptimer      = HAL_VARS+$B7  ; TRISWEEP: the NES timer being swept (2 bytes)
h_apustatcnt    = HAL_VARS+$B5  ; APUSTAT: consecutive frames the fault has held
h_joyaux        = HAL_VARS+$B9  ; the pad buttons the NES never had: see
                                ;   readpad_nes and JOYAUX_ below
h_joyauxprev    = HAL_VARS+$BA  ; ...as they read on the previous frame, for the
                                ;   release edge
h_padreset      = HAL_VARS+$BB  ; nonzero when a reset combo has been let go of:
                                ;   which one, as PADRESET_SOFT or _HARD
h_apuon         = HAL_VARS+$71  ; bit per voice: was it sounding last frame?
h_apumask       = HAL_VARS+$72  ; 1<<voice for the channel being translated
h_apuvoice      = HAL_VARS+$73  ; voice<<4, ready for the packet's cmd byte
h_apuvol        = HAL_VARS+$74  ; its NES volume nibble
h_apupitch      = HAL_VARS+$75  ; 2 bytes: its S-DSP pitch
h_apuwait       = HAL_VARS+$77  ; apu_send's bounded-wait counter
h_apuwaithi     = HAL_VARS+$CB  ; ...and its high byte
h_apuwave       = HAL_VARS+$78  ; waveform index, pre-shifted into the sequence
                                ;   byte's bits 7-3: duty and cycle length
;  The pulses' sweep units run on the SPC700 (see genspc.py).  What is kept
;  here is what it takes to tell it when one starts over, and what its
;  register says.  Two bytes per pulse channel so one index serves both:
;  X = 0 for pulse 1, 2 for pulse 2.
h_swseen        = HAL_VARS+$7E  ; the period the CPU last wrote, to spot writes
h_sqrst         = HAL_VARS+$C4  ; set by a $4003/$4007 write: the sweep starts
                                ;   over from the period just written, even if
                                ;   the bytes were the same as last time
h_swsent        = HAL_VARS+$BF  ; the sweep register last sent to the SPC700;
                                ;   indexed by Y = 0 or 4, so pulse 2's is +$C3
h_pkrst         = HAL_VARS+$C9  ; scratch: $80 if this packet restarts the sweep
h_hfacc         = HAL_VARS+$96  ; fractional half-frame accumulator
h_hftickn       = HAL_VARS+$98  ; half-frames falling in this video frame
h_apufull       = HAL_VARS+$9A  ; set by hal_waitvbl: this call is the frame's
                                ;   own, so it may advance the half-frame clock
;  The noise channel's NES envelope and length counter.  It is the only
;  channel this game drives with them: its $400C writes clear the
;  constant-volume bit, so the low nibble is a decay rate and the level comes
;  from the envelope.
h_nzdecay       = HAL_VARS+$9C  ; envelope level, 15 down to 0
h_nzdiv         = HAL_VARS+$9D  ; quarter-frames until the level steps
h_nzstart       = HAL_VARS+$9E  ; a $400F write restarts the envelope
h_nzlen         = HAL_VARS+$9F  ; length counter; at zero the channel is silent
h_nztick        = HAL_VARS+$A0  ; half-frames left to clock this video frame

;  The triangle's linear counter.  The channel has no volume register, so the
;  driver silences it by writing $4008 with the control bit clear and a reload
;  value in the low seven bits -- $30 when a new song starts, $70 when one
;  ends -- and letting the counter run down to zero at the quarter-frame rate.
;  The disassembly says so in as many words at each of those writes ("this
;  will silence the tri on the next linear counter clock").  Treating a
;  nonzero reload value as "sounding", which is what this did before, means
;  that countdown never happens and the voice drones on for ever: audible at
;  the end of the epilogue, where the music stops and no later note re-keys it.
h_trilin        = HAL_VARS+$A8  ; the counter itself; at zero the channel is mute
h_trirel        = HAL_VARS+$A9  ; reload flag, set by a write to $400B
h_trtick        = HAL_VARS+$AA  ; half-frames left to clock this video frame

;  The pulse channels' NES envelopes.  Everything the music driver plays is
;  constant volume, but PlaySFX_Error writes $8C to $4004: the constant bit
;  clear, so its low nibble is a decay period and the level comes from here.
;  Interleaved four bytes apart, so the shadow's own offset for the channel --
;  Y = 0 or 4 -- indexes them too.
h_pestart       = HAL_VARS+$BC  ; a $4003/$4007 write restarts the envelope
h_pediv         = HAL_VARS+$BD  ; quarter-frames until the level steps
h_pedecay       = HAL_VARS+$BE  ; envelope level, 15 down to 0
                                ;   (pulse 2's three are at +$C0..+$C2)
h_petick        = HAL_VARS+$C8  ; half-frames left to clock this video frame
;  The tilemap word ClearNT leaves everywhere: tile 0, and the palette number
;  from an attribute byte of $FF, which is 3 in each quadrant.  nt_attr stores
;  a palette as (bits & 3) << 2 in the high byte, so that is $0C.
h_fillcnt       = HAL_VARS+$A4  ; hal_ntfill: bytes left to write
h_fillcol       = HAL_VARS+$A6  ; ...and the column the run started at

NT_CLEARWORD    = $0C00

h_tintbase      = HAL_VARS+$A2  ; 2 bytes: emphasis<<7, the offset of this
                                ;   emphasis mode's block in nespal_snes
h_dacount       = HAL_VARS+$6C  ; hal_drawattr: attribute bytes to update
h_clcnt         = HAL_VARS+$66  ; hal_chrload: bytes still to move...
h_clidx         = HAL_VARS+$68  ; ...where it is reading from...
h_clrows        = HAL_VARS+$6A  ; ...and how far to advance the caller's pointer.
                                ; Kept apart from h_t0..h_t8 because the slow
                                ; path calls w2007_core, which uses those freely.
h_wipetop       = HAL_VARS+$63  ; first lit line of the transition band...
h_wipebot       = HAL_VARS+$64  ; ...and the first dark line below it
h_wipeon        = HAL_VARS+$65  ; nonzero while a transition wipe is running
h_hdmaen        = HAL_VARS+$62  ; which HDMA channels this frame wants.  Two
                                ; separate flushes drive HDMA -- flush_raster on
                                ; TM, flush_ntsplit on BG1HOFS -- and each used
                                ; to store HDMAEN outright, so whichever ran last
                                ; switched the other one off.
h_rowlo         = HAL_VARS+$AC  ; flush_nt: first dirty row, and one past
h_rowend        = HAL_VARS+$AE  ; the last, so the row loop walks only those
h_t8            = HAL_VARS+$60  ; 2 bytes: nt_attr's per-row "quadrant changed"
                                ; flags, one byte each, indexed left/right

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Shop Information
;;
;;  The description box reads the weapon and armour tables, which live in bank
;;  $0C.  Chunk CHUNK0+$0C carries that bank at $8000, so a long read reaches
;;  them from the options chunk without swapping anything.
BANK00FAR       = (CHUNK0 + $00) * $10000
BANK0BFAR       = (CHUNK0 + $0B) * $10000
BANK0CFAR       = (CHUNK0 + $0C) * $10000
BANK0DFAR       = (CHUNK0 + $0D) * $10000
;  The item names, lut_ItemNamePtrTbl and what it points at: BANK_ITEMS.
BANK0AFAR       = (CHUNK0 + $0A) * $10000
;  The equip permission words live in bank $0E, reached the same way.
BANK0EFAR       = (CHUNK0 + $0E) * $10000

;  Offsets into a weapon record (8 bytes) and an armour record (4).
WEAPON_HIT      = 0
WEAPON_DMG      = 1
WEAPON_CRIT     = 2
WEAPON_SPELL    = 3
WEAPON_ELEM     = 4
WEAPON_CAT      = 5
WEAPON_SIZE     = 8
ARMOR_EVADE     = 0
ARMOR_ABSORB    = 1
ARMOR_RESIST    = 2
ARMOR_SPELL     = 3
ARMOR_SIZE      = 4

;  The two characters the number formatter needs by name.
CHR_ZERO        = $80
CHR_SPACE       = $FF
CHR_PCT         = $E0
;  mkrom draws a plus into this slot; see overlay_plus there for why it is
;  not $7B, which is where FFR's character table puts one.
CHR_COMMA       = $BF
CHR_MINUS       = $C2
CHR_PLUS        = $C1

;  Where the box goes: the bottom-left corner, over the command box, which
;  the equipment shop erases before it runs the item list.  Fourteen wide
;  leaves twelve columns of text, and DrawBox leaves the cursor two rows down
;  and one column in, so seven rows are writable before the bottom border.
OPTINFO_X       = $01
OPTINFO_Y       = $12
OPTINFO_W       = $0E
OPTINFO_H       = $0A
OPTINFO_COLS    = OPTINFO_W - 2

;  The shop cursor's X when it is in the left-hand command column rather than
;  over the item list.  No description there.
SHOPCURS_LEFT   = $28

;  Working bytes, in the option block's spare page.  Nothing here outlives a
;  single press of Select.
OPTDESCI        = OPTBLOCK+$4A  ; write index into OPTDESC
OPTWORD         = OPTBLOCK+$4B  ; offset into lut_Words while emitting one
OPTWORDN        = OPTBLOCK+$4C  ; characters of it left to go
OPTNUMV         = OPTBLOCK+$4D  ; the value being converted to decimal
OPTNUMP         = OPTBLOCK+$4E  ; the place value, 100 then 10
OPTNUMSEEN      = OPTBLOCK+$4F  ; nonzero once a digit has been emitted
OPTDESC         = OPTBLOCK+$50  ; $50 bytes: the string being built
OPTGEARX        = OPTBLOCK+$A0  ; scratch for the record offset
OPTGEAR         = OPTBLOCK+$AD  ; the item id being described
OPTGEARI        = OPTBLOCK+$AE  ; its 0-based index into the weapon or
                                ;   armour table
OPTPERMLO       = OPTBLOCK+$A1  ; the equip permission word
OPTPERMHI       = OPTBLOCK+$A2
OPTPERMN        = OPTBLOCK+$A3  ; how many class names will print
OPTPERMFIRST    = OPTBLOCK+$A4  ; nonzero once one has
OPTPERMSLOT     = OPTBLOCK+$A5  ; which of a pair can use the item
OPTBITS         = OPTBLOCK+$A6  ; the element or category byte being listed
OPTBITN         = OPTBLOCK+$A7  ; how many of its bits are set
OPTBITLO        = OPTBLOCK+$A9  ; the lowest set bit's index, 8 for none
OPTBITM         = OPTBLOCK+$AA  ; the mask walking across it
OPTBITSTART     = OPTBLOCK+$AF  ; where opt_bitnext was told to start
;  The victory poses, one per character, live only for the length of a single
;  ShopFrame call -- the main menu and the lineup draw their sprites with the
;  same routine and must not inherit them.
OPTPOSE         = OPTBLOCK+$B0  ; 4 bytes
OPTPOSEI        = OPTBLOCK+$B4  ; which character is being judged
OPTPOSEIT       = OPTBLOCK+$B5  ; the item the cursor is on
OPTPOSECL       = OPTBLOCK+$B6  ; that character's class
OPTPOSEBIT      = OPTBLOCK+$B7  ; which bit of a magic permission byte
OPTWSIDX        = OPTBLOCK+$B8  ; Weapon Stats: the equipped weapon's 1-based id

;  The word table outgrew a byte offset, so opt_word walks it with a 24-bit
;  pointer, which has to live in the direct page.  tmp is the game's own
;  scratch and is free while the description is being built: the string is
;  finished before anything that draws is called.
OPTWPTR         = $001D         ; 3 bytes -- tmp+13, but snesmap.inc is
                                ;   included before variables.inc

;  Spell descriptions.  Some of the numbers -- a damage spell's weakness
;  figure is six times its effectivity -- do not fit in a byte.
OPTN16          = OPTBLOCK+$B9  ; 2 bytes: the value being printed
OPTNUMP16       = OPTBLOCK+$BB  ; 2 bytes: the place value
OPTSPIDX        = OPTBLOCK+$BD  ; the spell being described
OPTSPEFF        = OPTBLOCK+$BE  ; its effectivity, after any buff
OPTSPROUT       = OPTBLOCK+$BF  ; its routine
OPTSPRAW        = OPTBLOCK+$C0  ; a record byte before any buff is applied
OPTCTX          = OPTBLOCK+$C1  ; which screen the description box is over
OPTCTX_SHOP     = 0
OPTCTX_EQUIP    = 1
OPTCTX_MAGIC    = 2
OPTCTX_CHEST    = 3

;  Where OptCallFar reads the address to jump to.  It has to be somewhere
;  bank $00 can see, because JMP (abs) fetches its pointer from there, and
;  $00's low pages mirror WRAM.  tmp_hi sits at $0110 on the assumption that
;  the stack never reaches down this far; this rides the same assumption.
OPTCALLV        = $0113         ; 2 bytes, just above tmp_hi

;  The tile offset of the cheering pose within a character's battle sprites.
POSE_VICTORY    = $0E
OPTSAVEPTR      = OPTBLOCK+$AB  ; 2 bytes: text_ptr, which the shop loop owns
OPTDESC_MAX     = $50

;  Flags this file reads.  The bit numbers are the menu's row order, which is
;  what lut_OptRows in optmenu.asm already assigns.
OPTFB_SHOPINFO    = OPT_FLAGS+1 ; bit 12
OPTFM_SHOPINFO    = $10
OPTFB_CHESTINFO   = OPT_FLAGS+1 ; bit 13
OPTFM_CHESTINFO   = $20

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Treasures
;;
;;  The Free items, ITEM_FREE in the key item rows, change what a new game
;;  starts with.  Each of the four vehicles is a byte in the first page of unsram saying whether it exists,
;;  and coordinates that lut_InitUnsramFirstPage has already filled in -- so
;;  granting one is a single store.  The canal is the odd one: it starts set,
;;  meaning the waterway is still blocked, and Nerrick's TNT clears it.
;;
;;  They apply to a new game only.  Continue copies SRAM over the whole of
;;  unsram, so a saved game keeps whatever it saved.
;  Where the two free vehicles are put, which is not where the game leaves
;  them.  The ship's own start is Pravoka's harbour, on the far side of a
;  bridge you would not have, so FFR moves it to Coneria's dock; the airship
;  goes where the party starts.  Both are FFR's numbers -- its table gives
;  Pravoka as (210,153), which is exactly what lut_InitUnsramFirstPage holds,
;  so the two coordinate systems are the same one.
;
;  The starting tile is the stored scroll plus seven, which is how the game
;  centres the party on screen -- (146,158) + 7.
FREESHIP_X        = 152
FREESHIP_Y        = 169
FREEAIRSHIP_X     = 153
FREEAIRSHIP_Y     = 165

;  The Free items were flag bits 26-36 until format 9; they are now the
;  ITEM_FREE value of the key item rows, saved with the game (RANDO_ITEMS), and
;  those bits are spare.
;  Controller Reset is unconditional -- no flag.  L with X or Y is a combo no
;  NES-era code can express, so there is nothing for a player to turn off: it
;  cannot collide with anything the game does, and a cartridge that shipped
;  without these buttons cannot miss them.
;
;  The three pad buttons the NES never had, as readpad_nes files them into
;  h_joyaux.  L and X keep their own places in JOY1L; Y lives in JOY1H, and is
;  parked in bit 0, which JOY1L's signature nibble never sets.
;
;  Nothing in the game can see these -- joy is eight bits wide and every one of
;  them is spoken for -- so a combo built from them cannot collide with anything
;  the game does, which is the point of choosing them.
JOYAUX_L          = $20
JOYAUX_X          = $40
JOYAUX_Y          = $01

;  The controller reset combos.  Tested against the masked byte with CMP rather
;  than with AND, so L with both X and Y is neither combo rather than
;  ambiguously one of them.
PADRESET_MASK     = JOYAUX_L | JOYAUX_X | JOYAUX_Y
PADRESET_SOFT     = JOYAUX_L | JOYAUX_X  ; L + X: the ordinary reset path
PADRESET_HARD     = JOYAUX_L | JOYAUX_Y  ; L + Y: ...with zero page wiped first

;  How far below the dialogue's own text the chest description starts, which is
;  to say the first row the message above does not occupy.
;
;  This was 3, for the cartridge's three-line "In the treasure box," / "you
;  found.." / name.  Chest Information now swaps that for the one-line
;  lut_YouFound, so the first free row is the next one -- and leaving this at 3
;  cost both a blank line and the row the longest items needed.  The two are
;  always consistent, because opt_chestinfo and the pointer swap are gated on the
;  same flag; change one and this has to move with it.
OPTCHEST_DY       = 1

;  Spell names are four characters each, every one of them, which is what lets
;  lut_SpellNames be a flat table indexed by slot*4.  gen/spellnames.inc asserts
;  its own size against this, and the generator fails outright if any name in
;  the cartridge is a different length.
SPELLNAME_WIDTH   = 4
OPTLINEI          = OPTBLOCK+$C2  ; where the line being drawn starts
OPTLINEE          = OPTBLOCK+$C3  ; and where its line break was

;  The battle magic menu's scratch, named rather than left as bare addresses.
;  opt_magicgfx fills the first two; the third is what the menu is pointing at.
BTLCMD_MAGGFX     = $68B3       ; the graphic the selection recorded...
BTLCMD_MAGPAL     = $68B4       ; ...and its palette
BTLCMD_SPELLSEL   = $6B7D       ; the selected spell, zero based by this point
OPTFB_WEAPONSTATS = OPT_FLAGS+2 ; bit 16
OPTFM_WEAPONSTATS = $01
;  Enemy ROM record byte $0E, which Constants.inc calls ENROMSTAT_UNKNOWN_E:
;  the element of the enemy's touch, as FFR reads it.  It pairs with $0F, the
;  touch's ailment -- every poisoner's is poison, every stunner's status.
ENROMSTAT_TOUCHELEM = $0E
OPTFB_CRITRATE    = OPT_FLAGS+2 ; bit 20
OPTFM_CRITRATE    = $10

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The randomizer
;;
;;  A randomized world belongs to a save, not to the cartridge.  Its inputs --
;;  the seed and the new-game settings it was started with -- live in the save
;;  itself, in page 0 of unsram, so SaveGame, Continue and VerifyChecksum carry
;;  them with no code of their own.  The settings screen only describes the
;;  *next* new game: rando_newgame copies them into the save when that game
;;  starts, and nothing reads them from the option block after that.
;;
;;  Everything generated from those inputs is a cache in WRAM bank $7F, rebuilt
;;  whenever its tag does not match the save.  See src/rando.asm.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  The save block.  $603C-$60FC is named by nothing in variables.inc and
;  addressed by no instruction in any bank, and $60A0 up is filled with zero
;  from lut_InitUnsramFirstPage on every boot -- so every save made before
;  this block existed reads as seed 0 with every setting off, which is the
;  vanilla world.  That is why introducing it needed no SAVEVER bump.  Never
;  $60FD-$60FF: in the saved copy those are the checksum and the asserts.
;
;  Layout v1.  It grows by appending, with a SAVEVER bump if an old save
;  would mean something different under the new reading.  An appended byte
;  whose zero means "off" needs no bump: every older save has a zero there.
RANDO_SAVE      = $60A0
RANDO_SEED      = RANDO_SAVE+$00  ; 4 bytes, little-endian
RANDO_TRAPS     = RANDO_SAVE+$04  ; TRAPS_* below
RANDO_SHOPS     = RANDO_SAVE+$05  ; SHOPS_* below
RANDO_CHESTS    = RANDO_SAVE+$06  ; CHESTS_* below
RANDO_MAGIC     = RANDO_SAVE+$07  ; MAGIC_* below
RANDO_BLESS     = RANDO_SAVE+$08  ; the best a piece of gear may roll, 0..5
RANDO_CURSE     = RANDO_SAVE+$09  ; the worst, as a magnitude, 0..5
RANDO_FORMS     = RANDO_SAVE+$0A  ; FORMS_* below: formation rarity
RANDO_ZONES     = RANDO_SAVE+$0B  ; ZONES_* below: formations across zones
RANDO_NORUN     = RANDO_SAVE+$0C  ; RUNS_* below: which fights cannot be run from
RANDO_SURPRISE  = RANDO_SAVE+$0D  ; SURPRISE_* below: the fights' surprise rates
RANDO_STATUS    = RANDO_SAVE+$0E  ; STATUS_* below: enemies' touches
RANDO_SCRIPTS   = RANDO_SAVE+$0F  ; AI_* below: which enemy has which script
RANDO_SKILLS    = RANDO_SAVE+$10  ; AI_* below: what the scripts hold
RANDO_RNG       = RANDO_SAVE+$11  ; RNG_* below: the encounter and battle tables
RANDO_ORDEALS   = RANDO_SAVE+$12  ; ORDEALS_* below: the Castle of Ordeals' pillars
;  The key item rows (randomization-notes.md section 12), packed: they are 26
;  rows and the option page had nine bytes left.  The settings screen reads
;  each as a field, lut_ValBit and lut_ValMask.  Zero is vanilla throughout:
;  no key item moves, nothing is free, no gear is an incentive, nothing early.
RANDO_KEYITEMS  = RANDO_SAVE+$13  ; KEYITEMS_* below: whether key items move, and into which spots
RANDO_ITEMS     = RANDO_SAVE+$14  ; 3 bytes, two bits per row, ITEM_* below, rows ITEMROW_* in
                                  ;   order from bit 0 of the first byte
RANDO_GEAR      = RANDO_SAVE+$17  ; 2 bytes, a bit per gear row, GEARROW_* in order: set, an incentive
RANDO_EARLY     = RANDO_SAVE+$19  ; EARLY_* bits below: FFR's four Early flags
RANDO_ENTRANCES = RANDO_SAVE+$1A  ; ENTRANCES_* below: entrance shuffle's mode
;  What New Game made of the settings, under entrance shuffle (rando_place):
;  which attempt's wiring the game has, so the cache can draw it again, and
;  where a found ship is moored.  In the block, so the cache's tag sees them;
;  after the settings, so the settings screen's copy leaves them alone.  Zero
;  in every save made before them.
RANDO_ESK       = RANDO_SAVE+$1B  ; the attempt k whose wiring placed
RANDO_SHIPDOCK  = RANDO_SAVE+$1C  ; the ship's dock, 0..4 (es_dock)
RANDO_SETTINGS_SIZE = $1B
RANDO_SAVE_SIZE = $1D
.assert RANDO_SAVE + RANDO_SAVE_SIZE <= $60FD, error, "rando block runs into the checksum"
RANDO_SAVEFAR   = (CHUNK0 * $10000) + RANDO_SAVE   ; SRAM, from any data bank

;  The reward NPCs (rando_talk).  Kept apart from RANDO_SAVE, so the cache's
;  tag never sees them: the given bits change as the game is played.  Zero in
;  every save made before them, which keeps that save on the vanilla talk
;  routines: rando_newgame sets RANDO_TALK, so only a game begun since runs its
;  reward NPCs from the table.  Each NPC's own record of having given, whatever
;  it gives, is its bit in RANDO_GIVEN, not the vanilla "does the party hold
;  the item": once rewards move, the Princess may be holding the SHIP.
;  Incentive placement's result, written at New Game (rando_place) when Key
;  items is Standard or Wide.  $6040-$609F is a dead copy of the class starting
;  stats that the game never reads (randomization-notes.md section 1.1), saved
;  with page 0; junk in older saves, which is why RANDO_PLACED, not the bytes
;  themselves, says whether there is a placement.
RANDO_PLACED    = $6040     ; 1: RANDO_PLACE holds this game's placement
RANDO_PLACE     = $6041     ; PLACE_ITEMS bytes: each item's location, or $FF
PLACE_ITEMS     = 29        ; nineteen key items, the TAIL, nine gear rows
PLACE_KEYS      = 19
PLACE_TAIL      = 19
PLACE_GEAR      = 20
PLACE_ATTEMPTS  = 32
RANDO_PLACEDFAR = (CHUNK0 * $10000) + RANDO_PLACED
RANDO_PLACEFAR  = (CHUNK0 * $10000) + RANDO_PLACE
.assert RANDO_PLACE + PLACE_ITEMS <= $60A0, error, "RANDO_PLACE runs into RANDO_SAVE"
RANDO_TALK      = $60F0     ; nonzero: the reward NPCs run from rando_talk's table
RANDO_GIVEN     = $60F1     ; 2 bytes: bit n set once table entry n has given
RANDO_TALKFAR   = (CHUNK0 * $10000) + RANDO_TALK
RANDO_GIVENFAR  = (CHUNK0 * $10000) + RANDO_GIVEN
.assert RANDO_SAVE + RANDO_SAVE_SIZE <= RANDO_TALK, error, "rando block runs into RANDO_TALK"
.assert RANDO_GIVEN + 2 <= $60FD, error, "RANDO_GIVEN runs into the checksum"

;  The settings screen's copy: one byte per setting, in the same order as the
;  save block's from RANDO_TRAPS on, so starting a game is a straight copy.
;  Above the scratch the screens use, below nothing; opt_sum covers it, which
;  is what took OPT_FORMAT to 5.
OPT_NG          = OPTBLOCK+$C8
RANDO_NGOFF     = RANDO_TRAPS - RANDO_SAVE  ; where the settings start in the save
OPT_NG_SIZE     = RANDO_SETTINGS_SIZE - RANDO_NGOFF
OPT_NGFAR       = (CHUNK0 * $10000) + OPT_NG
OPT_NG_TRAPS    = OPT_NG + (RANDO_TRAPS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_SHOPS    = OPT_NG + (RANDO_SHOPS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_CHESTS   = OPT_NG + (RANDO_CHESTS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_MAGIC    = OPT_NG + (RANDO_MAGIC - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_BLESS    = OPT_NG + (RANDO_BLESS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_CURSE    = OPT_NG + (RANDO_CURSE - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_FORMS    = OPT_NG + (RANDO_FORMS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_ZONES    = OPT_NG + (RANDO_ZONES - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_NORUN    = OPT_NG + (RANDO_NORUN - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_SURPRISE = OPT_NG + (RANDO_SURPRISE - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_STATUS   = OPT_NG + (RANDO_STATUS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_SCRIPTS  = OPT_NG + (RANDO_SCRIPTS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_SKILLS   = OPT_NG + (RANDO_SKILLS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_RNG      = OPT_NG + (RANDO_RNG - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_ORDEALS  = OPT_NG + (RANDO_ORDEALS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_KEYITEMS = OPT_NG + (RANDO_KEYITEMS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_ITEMS    = OPT_NG + (RANDO_ITEMS - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_GEAR     = OPT_NG + (RANDO_GEAR - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_EARLY    = OPT_NG + (RANDO_EARLY - RANDO_SAVE) - RANDO_NGOFF
OPT_NG_ENTRANCES = OPT_NG + (RANDO_ENTRANCES - RANDO_SAVE) - RANDO_NGOFF

;  "None", a party slot left empty (nones.asm): the class byte of slots 2-4
;  may be this, with the character dead from the start.  FFR's value.
CLS_NONE        = $FF

;  Two buffers the randomizer hands to game code, in SRAM because every chunk
;  sees it and none sees WRAM above $2000.  Written before every read.
OPTAISHADOW     = OPTBLOCK+$E0  ; 16 bytes: the script an enemy is choosing by
OPTGEARSHADOW   = OPTBLOCK+$F0  ; 8 bytes: a blursed weapon or armour record
OPTNAMEBUF      = OPTBLOCK+$F8  ; 8 bytes: a blursed name and its terminator
.assert OPT_NG + OPT_NG_SIZE <= OPTAISHADOW, error, "new-game settings run into the shadows"
.assert OPT_NG + OPT_NG_SIZE <= OPTBLOCK + $100, error, "new-game settings run off the option page"

;  Entropy for the seed.  Every frame, rando_stir folds the pad into it and
;  steps it, so the value at New Game depends on every button press since the
;  cartridge was first switched on.  Battery-backed and outside any checksum:
;  a fresh cartridge's noise is welcome here.
RANDO_POOL      = OPTBLOCK+$C4  ; 4 bytes
RANDO_POOLFAR   = (CHUNK0 * $10000) + RANDO_POOL

;  Trap tile modes, FFR's TrapTileMode in its own order, minus the five this
;  port does not carry (Local, Remove, Undead, Curated, Overpowered).
TRAPS_OFF       = 0
TRAPS_SHUFFLE   = 1             ; the 34 trap tiles trade their formations
TRAPS_ASIDE     = 2             ; each draws from every A-side formation...
TRAPS_BSIDE     = 3             ; ...every B-side...
TRAPS_BOTH      = 4             ; ...or both
TRAPS_MODES     = 5

;  Shop modes.  FFR's Shops flag; Random Wares, which FFR applies only on top
;  of it, would be the next value.
SHOPS_OFF       = 0
SHOPS_SHUFFLE   = 1             ; weapons, armor and items dealt out again
SHOPS_MODES     = 2

;  Chest modes.  Tier 1 of randomization-notes.md: every chest's contents but
;  the seven key items, which stay where they are until there is logic to
;  move them.
CHESTS_OFF      = 0
CHESTS_SHUFFLE  = 1
CHESTS_MODES    = 2

;  Magic level modes.  FFR's MagicLevels as its presets use it: white spells
;  among white slots, black among black, and a class's permissions staying
;  with the slot.  Tiered, mixed spellbooks and permissions that follow the
;  spell are FFR flags of their own, off in every FFR preset.
MAGIC_OFF       = 0
MAGIC_SHUFFLE   = 1
MAGIC_MODES     = 2

;  Blursings: FFR's RandomWeaponBonus and RandomArmorBonus, one range for both.
;  Each piece of gear rolls a bonus from -curse to +blessing, so a plain piece
;  is always possible, which FFR's sliders need not allow.
BLURSE_STEPS    = 6             ; 0..5 for each of the two rows

;  Formations: two passes over lut_Domains's 128 zones of 8 slots, where FFR
;  has one mode.  Rarity moves formations between the slots of a zone, so how
;  often each is met changes; zones moves them between zones, each keeping its
;  slot's rarity.  Both on is FFR's tooltip, "any encounter can appear
;  anywhere regardless of zone or rarity".  FFR's own Shuffle Across Zones
;  permutes whole zones since a 2024 cleanup, and pooled single slots before
;  it, which moves rarity too; enemy-shuffle-notes.md has the history.
FORMS_OFF       = 0
FORMS_SHUFFLE   = 1             ; FFR's Shuffle Rarity: slots 0-3, then 2-7
FORMS_TIERED    = 2             ; FFR's Tiered: a weighted deal by original slot
FORMS_MODES     = 3
ZONES_OFF       = 0
ZONES_LIGHT     = 1             ; slots 0, 3, 5 and 6, each pooled across zones
ZONES_SHUFFLE   = 2             ; each rarity class pooled across zones and dealt
ZONES_RANDOM    = 3             ; FFR's Totally Random: any formation but a boss
ZONES_MODES     = 4

;  Unrunnable fights: FFR's Shuffle Unrunnable Encounters at vanilla's count.
;  The cartridge's 13 unrunnable normal formations are 26 sides, since its
;  no-run bit covers both; Shuffle marks 26 sides of FFR's 233 instead, each
;  side on its own.  Surprise rates: FFR's Shuffle Surprise Bonus, the rate
;  dealt out again among the 115 normal formations.
RUNS_OFF        = 0
RUNS_SHUFFLE    = 1
RUNS_MODES      = 2
RUNS_COUNT      = 26
SURPRISE_OFF    = 0
SURPRISE_SHUFFLE = 1
SURPRISE_MODES  = 2

;  Status attacks: FFR's Enemy Status Attacks in Shuffle mode.  Every enemy's
;  touch -- the ailment (record byte $0F) and its element ($0E), together --
;  dealt out again among all 128 but the pirates, bosses included.
STATUS_OFF      = 0
STATUS_SHUFFLE  = 1
STATUS_MODES    = 2

;  Enemy scripts and Enemy skills: bit 0 the normal enemies, bit 1 the bosses.
;  Scripts are FFR's Shuffle Scripts: which enemy has which script.  Skills
;  are its Shuffle Skills & Spells: what each script holds.
AI_OFF          = 0
AI_ENEMIES      = 1
AI_BOSSES       = 2
AI_BOTH         = 3
AI_MODES        = 4

;  RNG tables: FFR's flag of that name.  The encounter table (lut_RNG, which
;  decides whether a step fights and from which slot) and the battle table
;  (lut_BattleScramble) each shuffled: every probability the same, the order
;  and the spacing of encounters not.  FFR's Fix Missing Battle RNG Entry,
;  Set RNG and Advanced Encounter RNG are left out.
RNG_OFF         = 0
RNG_SHUFFLE     = 1
RNG_MODES       = 2

;  The save checksum's version.  SaveGame seeds its sum with SAVEVER where the
;  game seeded it with 0, and VerifyChecksum expects SAVEK where the game
;  expected $FF.  The sum is an add-with-carry chain, which is ones'-complement
;  arithmetic, and that is why the constant moves by 2*V mod 255 rather than by
;  V.  A save made under one version fails under every other, so Continue falls
;  through to New Game exactly as it does for a corrupt file.
;
;  Bump it when a change would give an existing save a different world.  0 is
;  the game's own scheme, and $FF would alias it; stay within 1..$FE.
;  randomization-notes.md section 1.5 has the derivation.
SAVEVER         = 0
SAVEK           = $FF - ((2 * SAVEVER) .MOD 255)

;  The cache, at the top half of bank $7F: clear of CREDITSRAM at the bottom
;  and THEENDBUF at $6800, both of which can be live with a save loaded.
;  hal_reset zeroes it on power-on with the rest of WRAM; L+X and L+Y do not
;  touch it, which is what keeps those resets instant.
RANDOWRAM       = $7F8000
RW_TAG          = RANDOWRAM+$0000 ; RW_TAG_VAL once the cache below is whole
RW_TAGBLK       = RANDOWRAM+$00C0 ; the save block the cache was built from
RW_RNG          = RANDOWRAM+$0010 ; 4 bytes: the stream being drawn from
RW_T            = RANDOWRAM+$0014 ; 2 bytes of scratch for the PRNG
RW_LEN          = RANDOWRAM+$0016 ; 2 bytes: entries left in RW_LIST
RW_MASK         = RANDOWRAM+$0018 ; rando_below's rejection mask...
RW_BOUND        = RANDOWRAM+$0019 ; ...and its bound
RW_R            = RANDOWRAM+$001A ; 2 bytes: the entry just drawn
RW_MODE         = RANDOWRAM+$001C ; the trap mode being dealt
;  The deals' counters are words whose high byte stays zero, so each loads
;  straight into a sixteen-bit X or Y; they are only ever stored eight bits
;  wide.  build zeroes RW_WORDS..RW_WORDSEND before anything deals.
RW_WORDS        = RANDOWRAM+$001E
RW_I            = RANDOWRAM+$001E ; a Fisher-Yates index
RW_E            = RANDOWRAM+$0020 ; shops: entries dealt so far
RW_P            = RANDOWRAM+$0022 ; shops: a position in the type's list
RW_Q            = RANDOWRAM+$0024 ; shops: the shop put and has_item act on
RW_FIRST        = RANDOWRAM+$0026 ; shops: the type's first shop_id
RW_NSHOPS       = RANDOWRAM+$0028 ; shops: how many the type has
RW_NENT         = RANDOWRAM+$002A ; shops: how many entries between them
RW_NELIG        = RANDOWRAM+$002C ; shops: how many could take this entry
RW_T2           = RANDOWRAM+$002E ; scratch
RW_WORDSEND     = RANDOWRAM+$0030
RW_ITEM         = RANDOWRAM+$0030 ; shops: the entry being placed
RW_K            = RANDOWRAM+$0031 ; shops: a count down
RW_SHOPID       = RANDOWRAM+$0032 ; shops: the type's shop_ids, up to 10
RW_CNT          = RANDOWRAM+$0040 ; shops: entries in each so far
RW_ELIG         = RANDOWRAM+$0050 ; shops: positions that could take this entry
RW_LIST         = RANDOWRAM+$0100 ; what is being dealt, up to 256 entries
RW_ORIG         = RANDOWRAM+$0200 ; shops: the type's entries as the cart has them
RW_LOCS         = RANDOWRAM+$0300 ; chests: the chest ids whose contents move
RW_UNUSED       = RANDOWRAM+$0400 ; chests: nonzero for an id no map places
RW_PROPS        = RANDOWRAM+$0800 ; every tileset's property table, $800 bytes
RW_SHOPS        = RANDOWRAM+$1000 ; every shop's item_box, 8 bytes per shop_id
RW_SHOPROWS     = 71              ; shop_id 0..70; 70 is the Caravan
RW_CHESTS       = RANDOWRAM+$1400 ; every chest's contents, by chest id
RW_PERM         = RANDOWRAM+$1500 ; magic: the spell in each slot, 64 bytes
RW_INV          = RANDOWRAM+$1540 ; magic: the slot each spell is in
RW_WEAPONS      = RANDOWRAM+$1600 ; gear: 40 weapons x 8, as blursed...
RW_ARMOR        = RANDOWRAM+$1740 ; ...then 40 armour x 4, contiguous as in ROM
RW_BONUS        = RANDOWRAM+$17E0 ; gear: each piece's bonus, signed, 80 bytes
RW_NAMEID       = RANDOWRAM+$0060 ; a name lookup: the item id...
RW_NAMEPTR      = RANDOWRAM+$0062 ; ...its name's ROM pointer, 2 bytes...
RW_NAMEB        = RANDOWRAM+$0064 ; ...and its bonus
RW_GI           = RANDOWRAM+$0065 ; gear: which of the 80 is being blursed
RW_GN           = RANDOWRAM+$0066 ; gear: how many values the roll has
RW_D2           = RANDOWRAM+$0068 ; gear: the bonus times two, a word
RW_D3           = RANDOWRAM+$006A ; ...and times three
RW_FLOOR        = RANDOWRAM+$006C ; gear: the clamp's floor, a word...
RW_CEIL         = RANDOWRAM+$006E ; ...and its ceiling
RW_FN           = RANDOWRAM+$0070 ; formations: entries in the pool, a word
RW_FK           = RANDOWRAM+$0072 ; formations: a position in it, a word
RW_FD           = RANDOWRAM+$0074 ; formations: the zone's offset, a word
RW_FS           = RANDOWRAM+$0076 ; formations: the class's first slot...
RW_FC           = RANDOWRAM+$0077 ; ...and how many slots it has
RW_FW           = RANDOWRAM+$0078 ; tiered: the weights still in the deal, 8
RW_FV           = RANDOWRAM+$0080 ; tiered: their formations, 8
RW_FT           = RANDOWRAM+$0088 ; tiered: the weights' total
RW_B16          = RANDOWRAM+$008A ; rando_below16's bound, a word...
RW_M16          = RANDOWRAM+$008C ; ...and its rejection mask
RW_ZONEOK       = RANDOWRAM+$0500 ; zones: nonzero for a zone the pass may touch
RW_DOMAINS      = RANDOWRAM+$1C00 ; every zone's 8 formations, as lut_Domains
RW_POS          = RANDOWRAM+$2000 ; zones: one rarity class's slots, words, 512 max
RW_NORUN        = RANDOWRAM+$2400 ; 1 for a side that cannot be run from, by
                                  ; formation id with the side in bit 7
RW_SURPRISE     = RANDOWRAM+$2500 ; each formation's surprise rate, 128 bytes
RW_TOUCH        = RANDOWRAM+$2600 ; each enemy's touch: element, ailment; 256
RW_ESCRIPT      = RANDOWRAM+$2700 ; each enemy's script id, $FF none; 128
RW_SCRIPTS      = RANDOWRAM+$2800 ; the 44 scripts, 16 bytes each, as lut_EnemyAi
;  Skills & spells: one group of scripts at a time.
RW_SPL          = RANDOWRAM+$2B00 ; the group's spells, pooled, 255 max
RW_SPLB         = RANDOWRAM+$2C00 ; ...and the script each is dealt to
RW_SKL          = RANDOWRAM+$2D00 ; the group's skills, pooled
RW_SKLB         = RANDOWRAM+$2E00 ; ...and the script each is dealt to
RW_SCH          = RANDOWRAM+$2F00 ; the group's spell chances, by position
RW_KCH          = RANDOWRAM+$2F40 ; ...and skill chances
RW_BCNT         = RANDOWRAM+$2F80 ; how many each bucket holds so far
RW_GRP          = RANDOWRAM+$2FC0 ; the group's script ids, in order
RW_ENCRNG       = RANDOWRAM+$3000 ; the encounter table, as lut_RNG, 256
RW_BATRNG       = RANDOWRAM+$3100 ; the battle table, as lut_BattleScramble, 256
RW_ORDPADS      = RANDOWRAM+$3200 ; the Ordeals' fifteen pillar pads' tiles
RW_TALKREW      = RANDOWRAM+$3220 ; 13: what each reward NPC gives, once placement is in
RW_CARAVAN      = RANDOWRAM+$3230 ; the caravan's one item, once placement is in
RW_DLGNPC       = RANDOWRAM+$3231 ; a reward NPC's entry + 1, its line next (rando_dlgtext)
;  The teleport tables the game reads (rando_entrdest, rando_teledest,
;  rando_exitdest), as bank $00 holds them: vanilla's, or the save's wiring
;  under entrance shuffle (es_tables).
RW_ENTRX        = RANDOWRAM+$3240 ; 32: each entrance's landing x...
RW_ENTRY        = RANDOWRAM+$3260 ; ...y...
RW_ENTRMAP      = RANDOWRAM+$3280 ; ...and map
RW_NORMX        = RANDOWRAM+$32A0 ; 64: each normal teleport's
RW_NORMY        = RANDOWRAM+$32E0
RW_NORMMAP      = RANDOWRAM+$3320
RW_EXITX        = RANDOWRAM+$3360 ; 16: each exit's overworld x and y
RW_EXITY        = RANDOWRAM+$3370
.assert RW_EXITY + 16 <= RP_BASE, error, "the teleport tables run into placement's memory"

;  New Game's roll screen (roll.asm): up while rando_newgame works, ticked from
;  the randomizer's yields (rando_yield).  Beside the cache, which never
;  writes here, so ROLL_ON is zero but while the screen is up: power-on
;  zeroes it and roll_end clears it.  Two bytes a variable, so a store from
;  sixteen-bit code cannot reach the next.  The randomizer writes ROLL_STAGE
;  and ROLL_YREQ; the rest is the screen's.
ROLL_ON         = RANDOWRAM+$3380 ; 1: the roll screen is up and ticking
ROLL_T          = RANDOWRAM+$3382 ; ticks since it came up
ROLL_FRAME      = RANDOWRAM+$3384 ; the step shown: 0 or 1
ROLL_BRIGHT     = RANDOWRAM+$3386 ; INIDISP's brightness, fading in
ROLL_STAGE      = RANDOWRAM+$3388 ; ROLLSTAGE_*: whose pitches the notes take
ROLL_NEXT       = RANDOWRAM+$338A ; ticks to the next note
ROLL_GATE       = RANDOWRAM+$338C ; ticks the note sounds yet
ROLL_IDX        = RANDOWRAM+$338E ; the note, 0-7 in its stage's scale
ROLL_YELP       = RANDOWRAM+$3390 ; ticks of the yelp left
ROLL_YPER       = RANDOWRAM+$3392 ; the yelp's period, falling
ROLL_YREQ       = RANDOWRAM+$3394 ; 1: something was thrown away, yelp
ROLL_PICK       = RANDOWRAM+$3396 ; which picture
ROLL_BUF        = RANDOWRAM+$33A0 ; 16 words: a row of the picture, being built
ROLL_ROW        = RANDOWRAM+$33C0 ; roll_row's: the row...
ROLL_PALHI      = RANDOWRAM+$33C2 ; ...its half's palette, as the word's high byte
ROLL_OFF        = RANDOWRAM+$33C4 ; ...the tile's row, in lut_RollChr
ROLL_P0         = RANDOWRAM+$33C6 ; ...its two planes, shifting out
ROLL_P1         = RANDOWRAM+$33C7
ROLL_HI         = RANDOWRAM+$33C8 ; ...a pixel's plane 1 bit, as the colour's 2
ROLL_N          = RANDOWRAM+$33C9 ; ...pixels left of the half
ROLL_CGOFF      = RANDOWRAM+$33CA ; roll_build's: the pick's colours, in lut_RollPal
ROLL_FX         = RANDOWRAM+$33CC ; the pick's effect (lut_RollFx): walk, hop, throb
ROLL_AFTER      = RANDOWRAM+$33CE ; the track roll_end starts, or 0
ROLL_YNUM       = RANDOWRAM+$33D0 ; yelps so far: which note the next starts on
ROLL_END        = RANDOWRAM+$33D2
.assert ROLL_ON >= RW_EXITY + 16, error, "the roll screen's variables overlap the cache"
.assert ROLL_END <= RP_BASE, error, "the roll screen's variables run into placement's memory"
ROLLSTAGE_PLACE   = 0           ; placing the key items (and before)
ROLLSTAGE_WIRING  = 1           ; entrance shuffle: dealing the doors
ROLLSTAGE_LOGIC   = 2           ; ...and working out what they open
ROLLSTAGE_BUILD   = 3           ; building the world: the cache

;  deal_rewards' working memory, in placement's: the two never run together.
;  A slot is a chest id, 256 + a reward NPC's entry, or SLOT_CARAVAN.
RV_VAN          = RP_BASE+$1000   ; 270: each slot's vanilla contents
RV_OUT          = RP_BASE+$1200   ; 270: and what it gives now
RV_PM           = RP_BASE+$1400   ; 270: set if placement put something there
RV_HM           = RP_BASE+$1600   ; 270: set if its vanilla contents left (a home)
RV_POOL         = RP_BASE+$1800   ; 255: the contents to deal
RV_DEST         = RP_BASE+$1A00   ; 255 words: the slots they go to
RV_GOLD         = RP_BASE+$1C00   ; 11: the Free items' gold, row order
RV_NPOOL        = RP_BASE+$1C10
RV_NDEST        = RP_BASE+$1C12
RV_NGOLD        = RP_BASE+$1C14
RV_S            = RP_BASE+$1C16   ; a slot
RV_K            = RP_BASE+$1C18
RV_CODE         = RP_BASE+$1C1A
SLOT_NPC        = 256
SLOT_CARAVAN    = 269
SLOTS           = 270
SHOP_CARAVAN    = 70

;  Incentive placement's working memory (place.inc).  It runs once, at New
;  Game, before the cache is built, so nothing here outlives it; the result
;  goes to RANDO_PLACE in the save.  Above the cache, which ends below $B380.
RP_BASE         = RANDOWRAM+$4000
RP_BYBITOFF     = RP_BASE+$0000   ; 33 words: where each bit's list of locations starts
RP_BYBIT        = RP_BASE+$0042   ; RP_BYBITMAX: the locations whose masks name each bit
RP_BYBITMAX     = 1536
RP_PLACED       = RP_BASE+$0700   ; 256: the item placed at each location, or $FF
RP_REACH        = RP_BASE+$0800   ; 256: reached with what is placed so far
RP_SEEN         = RP_BASE+$0900   ; 256: reached in the candidate being asked about
RP_WW           = RP_BASE+$0A00   ; 32 words: the draw's weights...
RP_WI           = RP_BASE+$0A40   ; 32 bytes: ...and its items
RP_NI           = RP_BASE+$0A60   ; 19 words: each key item's new incentive places
RP_NN           = RP_BASE+$0A88   ; 19 words: ...and new other places
RP_B3           = RP_BASE+$0AB0   ; 32 bytes: in the bin past the edges
RP_OWNED        = RP_BASE+$0B00   ; 4: owned, events and items both
RP_NOTOWN       = RP_BASE+$0B04   ; 4: its complement, for the mask tests
RP_FREE         = RP_BASE+$0B08   ; 4: what the party starts with
RP_PEND         = RP_BASE+$0B0C   ; 4: bits gained and not yet asked about
RP_SAVE         = RP_BASE+$0B10   ; 4: owned, kept across a candidate
RP_REM          = RP_BASE+$0B14   ; 4: the items still to place, a bit each
RP_INC          = RP_BASE+$0B18   ; 4: the items that are incentives, this attempt
RP_INC0         = RP_BASE+$0B1C   ; 4: ...as the settings have them
RP_ITEMS        = RP_BASE+$0B20   ; 4: every item to place
RP_WORDS        = RP_BASE+$0B24   ; the words below, zeroed with the rest
RP_NREM         = RP_BASE+$0B24   ; items still to place
RP_INCSRC       = RP_BASE+$0B26   ; incentive places reached and empty
RP_NONSRC       = RP_BASE+$0B28   ; other places reached and empty
RP_CI           = RP_BASE+$0B2A   ; a candidate's new incentive places
RP_CN           = RP_BASE+$0B2C   ; ...and new other places
RP_CYCLE        = RP_BASE+$0B2E
RP_STATE        = RP_BASE+$0B30   ; PSTATE_* below
RP_GEN          = RP_BASE+$0B32   ; RP_SEEN's marker for this candidate
RP_MODE         = RP_BASE+$0B34   ; 0: placing for good; 1: asking about a candidate
RP_SPOT         = RP_BASE+$0B36   ; LOGIC_STANDARD or LOGIC_WIDE
RP_NINCPOOL     = RP_BASE+$0B38   ; how many incentive spots there are
RP_ACCESS       = RP_BASE+$0B3A   ; places reached and empty, both kinds
RP_WN           = RP_BASE+$0B3C   ; entries in the draw
RP_TOTAL        = RP_BASE+$0B3E   ; their weights' sum
RP_W            = RP_BASE+$0B40   ; bin weights and scratch
RP_B0           = RP_BASE+$0B42
RP_B1           = RP_BASE+$0B44
RP_B2           = RP_BASE+$0B46
RP_RED          = RP_BASE+$0B48   ; how far the last bin's weight shifts down
RP_LO           = RP_BASE+$0B4A   ; the bins' edges
RP_HI           = RP_BASE+$0B4C
RP_BRANCH       = RP_BASE+$0B4E   ; 0 other items' draw, 1 incentives'
RP_NINCI        = RP_BASE+$0B50   ; incentives still to place
RP_ITEM         = RP_BASE+$0B52
RP_LOC          = RP_BASE+$0B54
RP_T            = RP_BASE+$0B56
RP_T2           = RP_BASE+$0B58
RP_ATT          = RP_BASE+$0B5A   ; attempts left
RP_K            = RP_BASE+$0B5C   ; the item being weighed
RP_WCUR         = RP_BASE+$0B5E   ; the last bin's weight, as it falls
RP_BIT          = RP_BASE+$0B60   ; the bit being asked about
RP_LI           = RP_BASE+$0B62   ; its list: where in it...
RP_LE           = RP_BASE+$0B64   ; ...and its end
RP_END          = RP_BASE+$0B66   ; a location's masks' end
RP_CNT          = RP_BASE+$0B68   ; scratch for counting bits
RP_BEST         = RP_BASE+$0B6A   ; the last bin: the least count kept...
RP_BESTI        = RP_BASE+$0B6C   ; ...and its item
RP_WANT         = RP_BASE+$0B6E   ; 1: an incentive spot wanted
RP_CLR0         = RP_BASE+$0B70   ; an Early waiver: what of each word to keep
RP_CLR2         = RP_BASE+$0B72
RP_ESK          = RP_BASE+$0B74   ; entrance shuffle: the attempt being tried
RP_TUNE         = RP_BASE+$0B76   ; 0, FFR's safe tables; TUNE_LOOSE, its unsafe
RP_FRESH        = RP_BASE+$0B78   ; 1: RP_NI and RP_NN are this cycle's already
RP_WORDSEND     = RP_BASE+$0B7A
RP_GRP          = RP_BASE+$0B80   ; the spread group of forward placement's draw
RP_MOFF         = RP_BASE+$0C00   ; 257 words: each location's masks' offset in RP_MASK
RP_FWD          = RP_BASE+$0E04   ; 248 words: each pool place's forward weight (pl_forward)
;  Entrance shuffle's (entrance.inc), in the same memory: it runs at New Game
;  before placement, and in the cache build, where only the rewards' RV_ area
;  below $2000 is in use.  The fixpoint's regions borrow that area at New Game.
ES_REQ          = RP_BASE+$1000   ; GR_NODES x ES_NODEMAX masks: each region's
ES_NODEMAX      = 6
ES_NREQ         = RP_BASE+$2400   ; how many each region has
ES_QUEUE        = RP_BASE+$2500   ; the fixpoint's regions to visit, a ring of 256
ES_QD           = RP_BASE+$2600   ; 1 for a region in the ring
ES_ROOTS        = RP_BASE+$2700   ; GR_NODES x 4: each region's entrances, a bit each
ES_ENT          = RP_BASE+$2B00   ; the wiring: each entrance's landing index...
ES_NORM         = RP_BASE+$2B20   ; ...each normal teleport's...
ES_EXIT         = RP_BASE+$2B60   ; ...and each exit's overworld coordinate index
ES_PMAP         = RP_BASE+$2D00   ; 32: the shuffle's pinned entrances, record or $FF
ES_PFLOOR       = RP_BASE+$2D20   ; 64: its pinned floors
ES_SHUF         = RP_BASE+$2D60   ; 32: the record each entrance leads to
ES_FOUT         = RP_BASE+$2D80   ; 64: the record each teleport leads to, $FF unchanged
ES_XOUT         = RP_BASE+$2DC0   ; 16: each exit's coordinate index, $FF unchanged
ES_PDEST        = RP_BASE+$2DD0   ; 16: the pinned destinations, a bit per location id
ES_DESTS        = RP_BASE+$2E00   ; 128: what is dealt, in order
ES_TL           = RP_BASE+$2E80   ; 16: towns to deal
ES_TOP          = RP_BASE+$2E90   ; 16: forced top floors
ES_SUB          = RP_BASE+$2EA0   ; 80: free floors...
ES_DEAD         = RP_BASE+$2F00   ; 32: ...and the dead ends set aside from them
ES_ORDER        = RP_BASE+$2F20   ; 32: the entrances, in the order they are filled
ES_PEND         = RP_BASE+$2F40   ; 32: teleports still to fill
ES_TMP          = RP_BASE+$2A80   ; 32 masks: a set being merged
ES_GREP         = RP_BASE+$2D00   ; ES_GROUPMAX: each spread group's first chest (over the shuffle's)
ES_GENTS        = RP_BASE+$2D40   ; ES_GROUPMAX x 4: its entrances
ES_GROUPMAX     = 64
ES_TMPMAX       = 32
ES_VARS         = RP_BASE+$2F80   ; the words below
ES_WORDSEND     = RP_BASE+$3000
RP_CHAOS        = RP_BASE+$2B70   ; Chaos's masks, RP_CHAOSMAX of them...
RP_NCHAOS       = RP_BASE+$2B88   ; ...and how many, a word
RP_CHAOSMAX     = 6
RP_GROUP        = RP_BASE+$2C00   ; 248: each pool place's spread group
RP_MASK         = RP_BASE+$3000   ; RP_MASKMAX x 4: each location's masks, Early waivers applied
RP_MASKMAX      = 1024
.assert RP_BYBIT + RP_BYBITMAX <= RP_PLACED, error, "RP_BYBIT runs into RP_PLACED"
.assert RP_MASK + RP_MASKMAX * 4 <= RP_BASE + $4000, error, "RP_MASK runs off the bank"
.assert RP_B3 + 32 <= RP_OWNED, error, "RP_B3 runs into RP_OWNED"
.assert RP_NN + 2 * 19 <= RP_B3, error, "RP_NN runs into RP_B3"
.assert RP_NI + 2 * 19 <= RP_NN, error, "RP_NI runs into RP_NN"
PSTATE_NORMAL      = 0
PSTATE_INCENTIVE   = 1
PSTATE_NONINCENTIVE = 2
RW_AGN          = RANDOWRAM+$00A0 ; scripts in the group
RW_ANSP         = RANDOWRAM+$00A1 ; spells in the pool
RW_ANSK         = RANDOWRAM+$00A2 ; skills in the pool
RW_ASB          = RANDOWRAM+$00A3 ; scripts that cast: spell buckets
RW_AKB          = RANDOWRAM+$00A4 ; scripts that use skills: skill buckets
RW_AREROLL      = RANDOWRAM+$00A5 ; nonzero to deal the group again
RW_ASI          = RANDOWRAM+$00A6 ; the next spell bucket
RW_AKI          = RANDOWRAM+$00A7 ; the next skill bucket
RW_AGI          = RANDOWRAM+$00A8 ; the group position being written
RW_APREV        = RANDOWRAM+$00A9 ; was the last list entry a nuke?
RW_ASTART       = RANDOWRAM+$00AA ; bit 0: list opens with NUKE, bit 1: NUCLEAR
RW_AJ           = RANDOWRAM+$00AB ; a list slot
RW_AREC         = RANDOWRAM+$00AC ; the script's offset in RW_SCRIPTS, a word
RW_AK           = RANDOWRAM+$00AE ; a pool position
RW_ACAP         = RANDOWRAM+$00AF ; a bucket's capacity
RW_AN           = RANDOWRAM+$00B0 ; a pool's length, for bucketize
RW_ABK          = RANDOWRAM+$00B1 ; ...and its bucket count
RW_TAG_VAL      = $A5             ; anything but 0, which is what reset leaves
.assert RANDO_SAVE_SIZE <= $40, error, "the tag copy runs into RW_LIST"
