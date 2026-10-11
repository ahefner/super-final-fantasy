;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  optbank.asm -- the options bank.
;;
;;  Chunk CHUNK_OPT, a code bank the NES never had.  mkrom stamps the fixed
;;  bank into its $C000-$FFFF exactly as it does for the game's own sixteen, so
;;  code here reaches DrawBox, DrawComplexString and the rest with a plain
;;  16-bit JSR, and JSL/RTL gets in and out without disturbing the data bank --
;;  absolute addressing still finds NES RAM, the option block in SRAM, and the
;;  I/O map.
;;
;;  ONE RULE FOR EVERY ROUTINE HERE: if it reads a table in this bank, it must
;;  set the data bank first, with PHB / PHK / PLB.  JSL changes PBR and leaves
;;  DBR alone, so absolute addressing still points at whichever chunk the
;;  caller was running in -- which is what you want for RAM and SRAM, and
;;  exactly wrong for this bank's own ROM.  Setting DBR = PBR fixes the ROM
;;  reads and costs nothing elsewhere, because this chunk carries the same
;;  low-bank map as the game's: WRAM at $0000, I/O at $2100, SRAM at $6000.
;;
;;  This file holds the option block: validate it, fall back to a preset when
;;  it is absent or stale, and write it back.  The menu that edits it comes
;;  later and lives here too.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
.p816
.a8
.i8
.include "snesmap.inc"
;  CALL0E, for the one hook that has to reach back into bank $0E.
.include "optcall.inc"
;  FFTEXT, for the Credits label.
.include "fftext.inc"
;  The game's own variable names, from the generated tree.  build.sh puts
;  gen/ on the include path for this file so the options bank can name RAM
;  the way the rest of the port does.
.include "Constants.inc"      ; direction bits, bank numbers, tile properties
.include "variables.inc"
;  The PPU macros, so this bank reaches the HAL the same way a converted
;  game bank does.  convert.py never sees this file, so the rewrites it
;  performs on $2006/$2007 have to be written out by hand here.
.include "nesio.inc"

.export opt_init, opt_commit, opt_movespeed, opt_owrate, opt_setbattlerate
;  Reached by tools/test_options.py, which runs them under a 65816
;  interpreter and asserts on what comes back.
.export opt_loadpreset, opt_sum, lut_Presets, opt_derive
.export opt_explodecount, opt_responddelay, opt_chkalivex, opt_chkalivey
.export opt_respondlookup, opt_msgdraw, opt_msgdraw_rev, opt_movenpcs
.export opt_magicpgdn, opt_magicpgup, opt_sortinv
.export opt_retarget, opt_retarget_mag, opt_dlgident, opt_thishit
.export opt_runlabel, opt_runiswait, opt_scalereward, opt_usedpotion
.export opt_shopmax, opt_shopscale
.export opt_scaleenemies, opt_scaleatk
.export opt_statmul, opt_isboss, opt_statn   ; for the tests
.export opt_magicdata, opt_healroll, opt_magictarget
.export opt_spellbuffed, opt_spelltarget, opt_spellfixed, opt_lockroll
.export opt_magloaddef, opt_magsavedef, opt_magsavemagdef, opt_cur4
.export opt_openchests
.export opt_freestuff, opt_housemp
.export opt_padreset
.export opt_magicgfx, opt_castlife, opt_playervalid
.export opt_magicmsg, opt_curedmsg
.export opt_startagi, opt_startevade, opt_thiefgrowth, opt_hitgrowth
.export opt_stackshift
.import OptCallFar, MenuRecoverPartyMP, MenuFillPartyHP
.import rando_stir, rando_newgame
.import DrawItemTargetMenu
;  The game's own reset entry, for Controller Reset.
.import OnReset
.import lut_MagicBattleMessages
.import lut_LvlUpHitRateBonus
.import opt_spelloverride
.import lut_WaitString
.import lut_CantHoldWhat
.import lut_YouFound
.export opt_drawpresetbox, opt_drawpresetname, opt_titlecursor
.export opt_titleupdown, opt_titleleftright, opt_titlechoose, opt_savevalid
.import opt_settings, opt_saveview, credits_screen, VerifyChecksum
.export opt_commit_body

.import DrawBox
;  Row writers in the fixed bank, which every chunk carries, so the message
;  routines below reach them with a plain JSR even from here.
.import Battle_DrawMessageRow, Battle_DrawMessageRow_VBlank
.import Battle_UpdatePPU_UpdateAudio_FixedBank

.segment "BANK_OPT"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Presets
;;
;;  One row per preset, and one named constant per setting, so retuning a
;;  preset is editing a line rather than counting bits.  The Super values are
;;  a starting point and are expected to change.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

OPTF_QOL      = OPTF_SPEEDHACKS | OPTF_FASTWALK | OPTF_FASTSHIP | OPTF_NOSHUFFLE
OPTF_QOL2     = OPTF_IDTREASURE | OPTF_OPENCHESTS | OPTF_BUYQTY | OPTF_RUNWAIT
OPTF_QOL3     = OPTF_MAGICWRAP | OPTF_AUTORETARGET | OPTF_AUTOSORT | OPTF_REPEATPOTION
OPTF_QOL4     = OPTF_SHOPINFO | OPTF_CHESTINFO | OPTF_GUILLOTINE
OPTF_ALLQOL   = OPTF_QOL | OPTF_QOL2 | OPTF_QOL3 | OPTF_QOL4

OPTF_BUGFIX   = OPTF_HOUSEMP | OPTF_WEAPONSTATS | OPTF_SPELLFIXES | OPTF_STATUSATK

;  Bit 21 is unused.  It was the elemental and type bonus until that became a
;  dial, then Thief and Ninja hit growth until that became one too.
OPTF_VAR1     = OPTF_THIEFNINJA | OPTF_CRITRATE | OPTF_IMPCURE
OPTF_VAR2     = OPTF_IMPFIRE | OPTF_CASTLIFE | OPTF_LOK2
OPTF_VARIATION= OPTF_VAR1 | OPTF_VAR2

;  Value-row step indices.  See options-design.md for the step tables.
GOLDXP_100    = 2       ; 0%,50%,100%..500% in 50% steps
GOLDXP_200    = 4
GOLDXP_250    = 5
ENC_60        = 6       ; Off,10%..100%,150%,200%,300%
ENC_100       = 10
STAT_100      = 3       ; 25%..500% in 25% steps

;  Which preset a cartridge with no valid block comes up in.
OPT_DEFAULT_PRESET = PRESET_IMPROVED

;  Testing aid, until the menu exists.  FFDEBUG=vanilla|improved|super builds
;  a ROM that forces that preset on every boot instead of honouring whatever is
;  in SRAM -- otherwise a block written once keeps its settings across builds
;  and there is no way to exercise a different preset.  A normal build never
;  defines this and reads SRAM as it should.
.ifdef OPT_FORCE
OPT_FORCED_PRESET = OPT_FORCE
.endif

lut_Presets:
    ;  Five bytes of flags, low byte first, then the seven scalars.  The fifth
    ;  flag byte holds the bits past 31, and is zero in every preset:
    ;  Treasures and the free key items skip content rather than improve it,
    ;  so none of them belongs in a preset.
    ;
    ;  Auto retargeting is off in all three, for the player to turn on (user,
    ;  2026-10-11): it takes strategy out of a fight.
    ;
    ;  Rows sit sixteen bytes apart so the index stays a shift rather than a
    ;  multiply.  The padding costs 12 bytes and buys that.
    .DWORD  0                                                              ; Vanilla
    .BYTE   0
    .BYTE   GOLDXP_100, ENC_100, STAT_100, STAT_100, ELEM_VANILLA, THIEFHIT_VANILLA
    .BYTE   STARTITEMS_NONE
    .RES    4, $00
    ;  Improved is FFR's Improved Vanilla (user, 2026-10-11): the quality of
    ;  life and the bugfixes, gold and XP doubled, Thief and Ninja hit growth
    ;  at Moderate, and the elemental bonus left at the cartridge's +4 --
    ;  that preset's bonus checkbox is off, so the 10 on its slider never
    ;  applies.
    .DWORD  (OPTF_ALLQOL & ~OPTF_AUTORETARGET) | OPTF_BUGFIX               ; Improved
    .BYTE   0
    .BYTE   GOLDXP_200, ENC_100, STAT_100, STAT_100, ELEM_VANILLA, THIEFHIT_MODERATE
    .BYTE   STARTITEMS_NONE
    .RES    4, $00
    .DWORD  (OPTF_ALLQOL & ~OPTF_AUTORETARGET) | OPTF_BUGFIX | OPTF_VARIATION ; Super
    .BYTE   0
    .BYTE   GOLDXP_250, ENC_60,  STAT_100, STAT_100, ELEM_FFR_DEF, THIEFHIT_DOUBLE
    .BYTE   STARTITEMS_NONE
    .RES    4, $00

;  What a row actually carries, and how far apart the rows are.  The fields
;  run from the flags up to but not including OPT_RESPOND, which
;  opt_loadpreset writes itself.
PRESET_FIELDS = OPT_RESPOND - OPT_FLAGS
PRESET_STRIDE = 16
.assert PRESET_FIELDS = OPT_FLAGBYTES + 7, error, "preset row does not match the option block"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  opt_init -- make the option block trustworthy
;;
;;  Called from GameStart, so it runs on a cold boot and on every soft reset.
;;  If the block in SRAM is present, current and intact it is left alone;
;;  otherwise the default preset is written over it.  A version mismatch counts
;;  as absent on purpose: a stale block that still checksums is worse than one
;;  that is obviously missing, because its fields have moved.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_init:
    PHB
    PHK
    PLB                         ; DBR = this bank, for lut_Presets below

    ;  Clear the victory poses before anything can read them.  They are scratch
    ;  at OPTBLOCK+$B0, above the settings the checksum covers, and until now
    ;  only the shop path ever wrote them -- so on a cartridge that had not been
    ;  through a shop they were whatever the battery held.  DrawOBSprite adds
    ;  the byte to its tile base with no range check, so $FF from a fresh
    ;  cartridge drew the whole party one tile into the previous class's CHR.
    ;
    ;  This runs before the magic and checksum tests rather than inside @reset,
    ;  because a block that validates perfectly says nothing about the bytes
    ;  above it: the settings can be intact and the scratch still arbitrary.
    ;  Every boot, unconditionally, is the only version of this that holds.
    LDA #$00
    STA OPTPOSE+0
    STA OPTPOSE+1
    STA OPTPOSE+2
    STA OPTPOSE+3

.ifdef OPT_FORCE
    LDA #OPT_FORCED_PRESET      ; FFDEBUG build: ignore SRAM, always this preset
    JSR opt_loadpreset
    PLB
    RTL
.endif
    LDA OPT_MAGIC0
    CMP #OPT_MAGIC0_VAL
    BNE @reset
    LDA OPT_MAGIC1
    CMP #OPT_MAGIC1_VAL
    BNE @reset
    LDA OPT_VERSION
    CMP #OPT_FORMAT
    BNE @reset

    JSR opt_sum                 ; A = sum of everything but the checksum byte
    EOR #$FF
    CMP OPT_CKSUM
    BEQ @good

  @reset:
    LDA #OPT_DEFAULT_PRESET
    JSR opt_loadpreset
  @good:
    PLB
    RTL


;;  Write preset A over the block, then seal it.
opt_loadpreset:
    STA OPT_PRESET
    ASL A                       ; index * PRESET_STRIDE
    ASL A
    ASL A
    ASL A
    TAX
    LDY #$00
  @copy:
    LDA lut_Presets, X
    STA OPT_FLAGS, Y
    INX
    INY
    CPY #PRESET_FIELDS
    BCC @copy

    ;  No preset randomizes anything, as none gives away a key item: the
    ;  new-game rows are off in all of them.
    LDA #$00
    LDX #OPT_NG_SIZE - 1
  @ng:
    STA OPT_NG, X
    DEX
    BPL @ng

    LDA #OPT_MAGIC0_VAL
    STA OPT_MAGIC0
    LDA #OPT_MAGIC1_VAL
    STA OPT_MAGIC1
    LDA #OPT_FORMAT
    STA OPT_VERSION
    LDA #OPT_RESPOND_DEFAULT
    STA OPT_RESPOND
                                ; flow into opt_commit's body


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  opt_commit -- recompute the checksum after the block has been edited
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_commit_body:
    JSR opt_derive              ; the cooked bytes follow the block
    JSR opt_sum
    EOR #$FF
    STA OPT_CKSUM
    RTS

opt_commit:
    JSR opt_commit_body
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  opt_derive -- cook the flags down into the constants the game reads
;;
;;  Runs from opt_commit_body, so after anything that changes the block: a
;;  preset load, a checkbox, a value row.  The derived bytes are outside the
;;  checksummed block on purpose -- they are a cache of it, not part of it, and
;;  recomputing them is cheaper than deciding whether they are stale.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_derive:
    ;  The elemental and type damage bonus.  The dial stores a step and the
    ;  step is worth two, so the derived byte is a shift -- and the use site
    ;  in bank $0C, where a load costs one byte more than the immediate it
    ;  replaces, gets a plain byte to add.
    LDA OPT_ELEMDMG
    ASL A
    STA OPTD_ELEMDMG

    ;  ...and the speed hacks, which are eleven of them.
    LDA OPTFB_SPEEDHACKS
    AND #OPTFM_SPEEDHACKS
    BNE @fast

    LDA #WIPE_OPEN_U_SLOW
    STA OPTD_WIPEOPEN_U
    LDA #WIPE_OPEN_D_SLOW
    STA OPTD_WIPEOPEN_D
    LDA #WIPE_CLOSE_D_SLOW
    STA OPTD_WIPECLOSE_D
    LDA #WIPE_CLOSE_U_SLOW
    STA OPTD_WIPECLOSE_U
    LDA #DLG_OPEN_SLOW
    STA OPTD_DLGOPEN
    LDA #DLG_CLOSE_SLOW
    STA OPTD_DLGCLOSE
    LDA #BTLTRANS_SLOW
    STA OPTD_BTLTRANS
    LDA #LINEUP_SLOW
    STA OPTD_LINEUP
    LDA #PALCYC_SLOW
    STA OPTD_PALCYC
    LDA #MSGROWS_SLOW
    STA OPTD_MSGROWS
    LDA #MSGROWSREV_SLOW
    STA OPTD_MSGROWSREV
    RTS

  @fast:
    LDA #WIPE_OPEN_U_FAST
    STA OPTD_WIPEOPEN_U
    LDA #WIPE_OPEN_D_FAST
    STA OPTD_WIPEOPEN_D
    LDA #WIPE_CLOSE_D_FAST
    STA OPTD_WIPECLOSE_D
    LDA #WIPE_CLOSE_U_FAST
    STA OPTD_WIPECLOSE_U
    LDA #DLG_OPEN_FAST
    STA OPTD_DLGOPEN
    LDA #DLG_CLOSE_FAST
    STA OPTD_DLGCLOSE
    LDA #BTLTRANS_FAST
    STA OPTD_BTLTRANS
    LDA #LINEUP_FAST
    STA OPTD_LINEUP
    LDA #PALCYC_FAST
    STA OPTD_PALCYC
    LDA #MSGROWS_FAST
    STA OPTD_MSGROWS
    LDA #MSGROWSREV_FAST
    STA OPTD_MSGROWSREV
    RTS


;;  Sum every byte of the block except the checksum itself, and the new-game
;;  rows, which sit apart from it higher up the page.  Plain 8-bit addition
;;  with the carry dropped -- the game's own save checksum lets carry run
;;  between bytes, which is harder to reason about and buys nothing here.
opt_sum:
    LDA #$00
    LDX #$00
  @loop:
    CLC
    ADC OPTBLOCK, X
    INX
    CPX #OPT_SIZE - 1           ; stop before OPT_CKSUM
    BCC @loop
    LDX #$00
  @ng:
    CLC
    ADC OPT_NG, X
    INX
    CPX #OPT_NG_SIZE
    BCC @ng
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  opt_movespeed -- how far the party moves this step
;;
;;  Replaces the tail of the map-movement routine in the fixed bank, which
;;  worked out walking = 1, canoe = 1, ship = 2, airship = 4 and had no room to
;;  grow.  Moving the whole calculation here gives the flags somewhere to live
;;  and hands twelve bytes back to the fixed bank.
;;
;;  Out: A = the speed, which the caller stores to move_speed.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  Bit 6 of joy.  Constants.inc names the directions and Start but not these;
;  the joypad reader shifts B into bit 6 and A into bit 7.
BTN_B  = $40

opt_movespeed:
    ;  The vanilla speed first, in X.
    LDX #$01                    ; walking pace
    LDA mapflags
    LSR A                       ; standard-map flag into C
    BCS @flags                  ; in a standard map it is always walking pace
    LDA vehicle
    CMP #$02
    BCC @flags                  ; on foot
    LSR A                       ; canoe = 1, ship = 2, airship = 4
    TAX

  @flags:
    CPX #$02
    BCS @ship

    ;  Faster Walking doubles anything that moves at walking pace -- on foot,
    ;  inside a standard map, and the canoe, which vanilla also runs at 1.
    LDA OPT_FLAGS
    AND #<OPTF_FASTWALK
    BEQ @modifier
    LDX #$02
    BRA @modifier

  @ship:
    BNE @modifier               ; X = 4, the airship, already fast
    LDA OPT_FLAGS
    AND #<OPTF_FASTSHIP
    BEQ @modifier
    LDX #$04                    ; the ship keeps up with the airship

  @modifier:
    ;  Holding B steps at the old pace, so a player who wants to line up on a
    ;  single tile still can.  Never below 1, or the party would not move.
    LDA joy
    AND #BTN_B
    BEQ @out
    CPX #$02
    BCC @out
    TXA
    LSR A
    TAX
  @out:
    TXA
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Encounter rate
;;
;;  Three inputs, not one.  The per-map table in bank $0B feeds battlerate, but
;;  the overworld and the ocean are hardcoded immediates in the fixed bank
;;  (10/256 and 3/256).  All three come from here now.
;;
;;  The steps are labelled by their effect on the overworld, because that is
;;  what players tune and because the overworld base is 10 -- so 10% steps are
;;  exactly the integers 1..10, with no rounding at all.  The overworld and
;;  ocean bytes are therefore tabulated outright; only the per-map rate is
;;  computed, as (rate * N + 8) >> 4, which is exact-to-rounding on the 8 that
;;  57 of the 63 maps use.
;;
;;  The ocean column is floored at 1: its base is 3, so honest scaling would
;;  round to zero below about 17%, and a setting labelled 10% turning sea
;;  encounters off altogether is a surprise rather than a feature.
;;
;;  Step 10 is vanilla and reproduces the original bytes exactly.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;                   Off  10%  20%  30%  40%  50%  60%  70%  80%  90% 100% 150% 200% 300%
lut_EncOverworld: .BYTE   0,   1,   2,   3,   4,   5,   6,   7,   8,   9,  10,  15,  20,  30
lut_EncOcean:     .BYTE   0,   1,   1,   1,   1,   2,   2,   2,   2,   3,   3,   5,   6,   9
lut_EncDungeonN:  .BYTE   0,   2,   3,   5,   6,   8,  10,  11,  13,  14,  16,  24,  32,  48
ENC_STEPS = 14

;;  Out: A = the overworld or ocean rate, whichever the current vehicle wants.
;;  Replaces the two immediates and the vehicle test that chose between them.
opt_owrate:
    PHB
    PHK
    PLB
    LDX OPT_ENCOUNTER
    LDA vehicle
    CMP #$04                    ; the ship, and only the ship, uses the ocean rate
    BNE @land
    LDA lut_EncOcean, X
    BRA @out
  @land:
    LDA lut_EncOverworld, X
  @out:
    PLB
    RTL

;;  In: A = the map's rate from lut_BattleRates.  Scales it and stores it.
;;  The multiply is the S-PPU's: $4202 x $4203 lands in $4216 eight cycles
;;  later, which beats writing a shift-and-add loop into a bank with no room.
opt_setbattlerate:
    PHB
    PHK
    PLB
    PHX
    STA a:WRMPYA
    LDX OPT_ENCOUNTER
    LDA lut_EncDungeonN, X
    STA a:WRMPYB                ; the product is ready 8 cycles from here
    CLC                         ; 2
    XCE                         ; 2  -- native mode
    REP #$20                    ; 3
    .A16
    NOP                         ; 2  -- 9 cycles, one clear of the requirement
    LDA a:RDMPYL                ; the full 16-bit product
    CLC
    ADC #8                      ; round to nearest rather than truncating
    LSR A
    LSR A
    LSR A
    LSR A                       ; ... >> 4
    SEP #$20
    .A8
    SEC
    XCE                         ; back to emulation mode
    STA battlerate
    PLX
    PLB
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The title screen's preset and credits rows
;;
;;  Two boxes between "New Game" and "Respond Rate": the mode at (8,16) and
;;  Credits at (8,20), each four rows tall, with the respond rate below them
;;  at (8,24) ending on row 27 -- the last of the 28 rows the 224-line crop
;;  actually shows.  Continue and New Game moved up four rows to make room
;;  (the two optcredits patches), keeping their one-row gaps.
;;
;;  The cursor has four positions.  Left and right cycle the preset on the
;;  mode row and go on adjusting the respond rate everywhere else, which
;;  leaves the existing controls exactly as they were for anyone who never
;;  moves down.  A on either new row opens a screen; see opt_titlechoose.
;;
;;  The name is redrawn every frame from a fixed nametable address, the way
;;  TitleScreen_DrawRespondRate redraws its digit, rather than through
;;  DrawComplexString -- it is eight tiles, it has to happen inside vblank, and
;;  this way it needs no cur_bank juggling.  All four names are padded to eight
;;  characters so a shorter one cannot leave the tail of a longer one behind.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  The respond rate moved down to 24 to make room, so the mode box and the
;  credits box sit where it used to be -- see the patches in patches/bank_0E.
PRESETBOX_X  = 8
PRESETBOX_Y  = 16
CREDITSBOX_Y = PRESETBOX_Y + 4          ; directly below, sharing an edge row
CREDITSTEXT_PPU = $2000 + (CREDITSBOX_Y + 2) * 32 + PRESETBOX_X + 1 + 3

;  The title screen's cursor rows.  0 and 1 are the game's own, Continue and
;  New Game, and the game's code knows them by number.
TITLEROW_MODE    = 2
TITLEROW_CREDITS = 3
TITLE_ROWS       = 4
PRESETTEXT_ROW = PRESETBOX_Y + 2        ; DrawBox puts its text two rows down
PRESETNAME_PPU = $2000 + PRESETTEXT_ROW * 32 + PRESETBOX_X + 1
PRESETNAME_LEN = 14                     ; the box's whole interior
PRESETNAME_STRIDE = 16                  ; ...padded to a shift, not a multiply

;  Each row is the box's full 14-column interior, with the name centred in the
;  table rather than by arithmetic -- so adjusting the wording or the spacing
;  is editing the strings, and a shorter name cannot leave part of a longer one
;  behind.  Padded to 16 so the index is a shift.
lut_PresetNames:
  .BYTE $FF, $9F, $8A, $97, $92, $95, $95, $8A   ; " VANILLA MODE "
  .BYTE $FF, $96, $98, $8D, $8E, $FF, $FF, $FF
  .BYTE $92, $96, $99, $9B, $98, $9F, $8E, $8D   ; "IMPROVED MODE "
  .BYTE $FF, $96, $98, $8D, $8E, $FF, $FF, $FF
  .BYTE $FF, $FF, $9C, $9E, $99, $8E, $9B, $FF   ; "  SUPER MODE  "
  .BYTE $96, $98, $8D, $8E, $FF, $FF, $FF, $FF
  .BYTE $FF, $8C, $9E, $9C, $9D, $98, $96, $FF   ; " CUSTOM MODE  "
  .BYTE $96, $98, $8D, $8E, $FF, $FF, $FF, $FF

;  Cursor sprite position per row.  Y is one tile row below the box's top, as
;  the game's own two entries were.  X has to vary now: the first two boxes
;  start at column 11 and the two below them at column 8, so a single fixed X
;  either sits too far from one or overlaps the other.  Sixteen pixels clear
;  of the box edge in both cases.
lut_TitleCursorY:
  .BYTE $38, $60, (PRESETBOX_Y + 1) * 8, (CREDITSBOX_Y + 1) * 8
lut_TitleCursorX:
  .BYTE $48, $48, $30, $30

;  Centred in the box's fourteen columns as nearly as seven letters can be,
;  leaning left by the half column the way the mode names do.
lut_CreditsLabel:
  FFTEXT "CREDITS"
CREDITSLABEL_LEN = * - lut_CreditsLabel

;;  Drawn once, with the PPU off, alongside the other three boxes -- and the
;;  credits box with it, whose label never changes and so is written here
;;  rather than every frame.
opt_drawpresetbox:
    ;  DrawBox can stall a frame, and a stall calls CallMusicPlay, which comes
    ;  back through cur_bank.  It happens not to stall here, because the title
    ;  screen leaves menustall clear -- but that is the caller's state, not
    ;  ours, so name this bank and zero the flag rather than rely on it.
    LDA cur_bank
    PHA
    LDA #CHUNK_OPT
    STA cur_bank
    LDA #$00
    STA menustall

    LDA #PRESETBOX_X
    STA box_x
    LDA #PRESETBOX_Y
    STA box_y
    LDA #4
    STA box_ht
    LDA #16
    STA box_wd
    JSR DrawBox

    LDA #CREDITSBOX_Y           ; same x and size, four rows down
    STA box_y
    LDA #CHUNK_OPT              ; still this bank, said again where the
    STA cur_bank                ;   bank-swap check can see it
    JSR DrawBox

    PHB
    PHK
    PLB
    bPPUSTATUS                  ; reset the $2006 write toggle
    LDA #>CREDITSTEXT_PPU
    wPPUADDR
    LDA #<CREDITSTEXT_PPU
    wPPUADDR
    LDX #0
  @label:
    LDA lut_CreditsLabel, X
    wPPUDATA
    INX
    CPX #CREDITSLABEL_LEN
    BNE @label
    PLB

    PLA
    STA cur_bank                ; the title screen wants its own value back
    RTL

;;  Redrawn every frame, in vblank, immediately before the respond rate -- so
;;  that routine's scroll reset covers this one too.
opt_drawpresetname:
    PHB
    PHK
    PLB
    bPPUSTATUS                  ; reset the $2006 write toggle
    LDA #>PRESETNAME_PPU
    wPPUADDR
    LDA #<PRESETNAME_PPU
    wPPUADDR
    LDA OPT_PRESET
    ASL A                       ; sixteen bytes per row
    ASL A
    ASL A
    ASL A
    TAX
    LDY #PRESETNAME_LEN
  @loop:
    LDA lut_PresetNames, X
    wPPUDATA
    INX
    DEY
    BNE @loop
    PLB
    RTL

;;  In: X = cursor.  Sets both cursor sprite coordinates.
opt_titlecursor:
    PHB
    PHK
    PLB
    LDA lut_TitleCursorX, X
    STA spr_x
    LDA lut_TitleCursorY, X
    STA spr_y
    PLB
    RTL

;;  In: A = the direction bits.  Moves the cursor between the rows, wrapping.
opt_titleupdown:
    LDX cursor
    CMP #DOWN
    BNE @up
    INX
    CPX #TITLE_ROWS
    BCC @set
    LDX #0
    BRA @set
  @up:
    DEX
    BPL @set
    LDX #TITLE_ROWS - 1
  @set:
    STX cursor
    RTL

;;  A, Start or Select on the title screen: every decision the title loop
;;  makes about a button, so that its call site in bank $0E, which has no
;;  bytes to spare, is a call and three branches.
;;
;;    A or Start on Continue or New Game leaves the title screen, as ever.
;;    A or Start on the mode row opens the settings, and on Credits the
;;      credits.
;;    Select on Continue opens the save view (opt_saveview), if there is a
;;      save Continue would load; anywhere else, or with none, it does
;;      nothing.
;;
;;  A screen of ours overwrites the CHR and the nametable, so the title screen
;;  is then rebuilt from the top.  Each is called rather than jumped to, so
;;  the answer below is ours and not whatever its RTL left in the flags.
;;
;;  Out: N set -- nothing happened, back to the loop.  Z set -- a screen was
;;  shown, rebuild the title screen.  Neither -- leave it, with C set for New
;;  Game and clear for Continue, which is what the game's CMP #1 gave.
opt_titlechoose:
    LDA joy_a
    ORA joy_start
    BNE @chosen

    ;  Select alone.  The press is used up whatever comes of it, or the loop
    ;  would find it again next frame.
    STA joy_select              ; A is zero
    LDA cursor
    BNE @nothing                ; only Continue has a save behind it
    JSR opt_savevalid
    BCS @nothing
    JSL opt_saveview + OPTFAR
    BRA @shown
  @nothing:
    LDA #$FF                    ; N set
    RTL

  @chosen:
    LDA cursor
    CMP #TITLEROW_MODE
    BCS @screen
    CMP #1                      ; C: New Game
    LDA #$01                    ; ...and Z and N clear
    RTL
  @screen:
    CMP #TITLEROW_CREDITS
    BEQ @credits
    JSL opt_settings + OPTFAR
    BRA @shown
  @credits:
    JSL credits_screen + CREDITSFAR
  @shown:
    LDA #$00                    ; Z set
    RTL

;;  C clear if the battery holds a save Continue would load: the game's own
;;  tests, in its order -- the two assertion bytes, then the checksum, which
;;  also fails a save from another SAVEVER.
opt_savevalid:
    LDA sram_assert_55
    CMP #$55
    BNE @no
    LDA sram_assert_AA
    CMP #$AA
    BNE @no
    JMP VerifyChecksum          ; its carry is the answer
  @no:
    SEC
    RTS

;;  In: A = the direction bits.  On the preset row this cycles the preset and
;;  reseals the block; anywhere else it is the respond rate, as before -- and
;;  that now writes through to the block so the setting survives a power cycle.
;;  "Anywhere else" includes the Credits row, which has nothing to the side.
opt_titleleftright:
    PHB
    PHK
    PLB
    LDX cursor
    CPX #TITLEROW_MODE
    BEQ @preset

    CMP #RIGHT
    BNE @rateleft
    LDA #1
    BRA @rateadd
  @rateleft:
    LDA #$FF
  @rateadd:
    CLC
    ADC respondrate
    AND #7                      ; wraps 0<->7, as the original did
    STA respondrate
    STA OPT_RESPOND
    JSR opt_commit_body
    BRA @out

  @preset:
    CMP #RIGHT
    BNE @presetleft
    LDA OPT_PRESET
    INC A
    CMP #4
    BCC @presetset
    LDA #0
    BRA @presetset
  @presetleft:
    LDA OPT_PRESET
    BNE @presetdec
    LDA #4
  @presetdec:
    DEC A
  @presetset:
    CMP #PRESET_CUSTOM
    BEQ @custom
    JSR opt_loadpreset          ; writes the flags and scalars, and reseals
    BRA @out
  @custom:
    ;  Custom keeps whatever flags are in the block -- it is seeded by
    ;  whichever preset was last active, which is what the design asks for.
    STA OPT_PRESET
    JSR opt_commit_body
  @out:
    PLB
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Helpers for hooks in banks that have no room
;;
;;  Each of these is reached through a five-byte trampoline in the fixed bank
;;  -- a JSL here and an RTS -- because the call sites are in banks with no
;;  free bytes and can only afford a three-byte JSR.  The trampoline is what
;;  has to be in the fixed bank; the thinking does not, and the fixed bank is
;;  stamped into every chunk, so it is the one budget that never recovers.
;;
;;  Routines that finish by jumping back into a swappable bank cannot live
;;  here, because a JSL leaves the program bank pointing at this one.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  In: A = the count this formation would normally use.
opt_explodecount:
    PHA
    LDA OPTFB_SPEEDHACKS
    AND #OPTFM_SPEEDHACKS
    BEQ :+
      PLA
      LDA #EXPLODE_FAST
      STA explode_count
      RTL
:   PLA
    STA explode_count
    RTL

;;  In: A = the delay in frames the game would normally wait.
opt_responddelay:
    PHA
    LDA OPTFB_SPEEDHACKS
    AND #OPTFM_SPEEDHACKS
    BEQ :+
      PLA
      LDA #RUNDELAY_FAST
      STA btl_responddelay
      RTL
:   PLA
    STA btl_responddelay
    RTL

;;  The lineup menu's "is the character in this slot alive?" reads.  Reporting
;;  zero means alive, which is what lets No Party Shuffle allow the swap.  Both
;;  leave Z set from the value, because the call site branches on it.
opt_chkalivex:
    LDA OPTFB_NOSHUFFLE
    AND #OPTFM_NOSHUFFLE
    BNE :+
      LDA str_buf, X
      RTL
:   LDA #$00
    RTL

opt_chkalivey:
    LDA OPTFB_NOSHUFFLE
    AND #OPTFM_NOSHUFFLE
    BNE :+
      LDA str_buf, Y
      RTL
:   LDA #$00
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The respond-rate table
;;
;;  How long the battle pauses between messages, indexed by the respond rate
;;  the title screen sets.  Vanilla starts at two full seconds and only reaches
;;  something brisk at the very top of the range; the Speed Hacks table is the
;;  one FFR ships, which spreads useful values across all eight settings.
;;
;;  A table rather than a constant, so the hook redirects the lookup instead of
;;  substituting a value.  Both tables live here, which is why this is a
;;  routine and not two bytes: the call site in bank $0B can only afford the
;;  three bytes its "LDA lut_RespondDelay, Y" already cost.
;;
;;  In: Y = respondrate, 0..7.  Out: A = frames to wait.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_RespondSlow:  .BYTE $78, $50, $3C, $2D, $1E, $0F, $05, $01
lut_RespondFast:  .BYTE $30, $20, $18, $10, $08, $04, $02, $01

opt_respondlookup:
    PHB
    PHK
    PLB
    LDA OPTFB_SPEEDHACKS
    AND #OPTFM_SPEEDHACKS
    BEQ @slow
    LDA lut_RespondFast, Y
    PLB
    RTL
  @slow:
    LDA lut_RespondSlow, Y
    PLB
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The battle message box, drawn and undrawn
;;
;;  Twelve rows either way.  What the flag changes is how many go out per
;;  frame, not how many frames there are -- the rows all have to be drawn, so
;;  cutting the frame count alone would leave the box half finished.
;;
;;  The whole routines moved here rather than being edited in place.  They are
;;  forty-odd bytes each in a fixed bank with sixty to its name, and the row
;;  writers they call are in the fixed bank, which every chunk carries, so a
;;  plain JSR still reaches them from here.
;;
;;  The audio update does NOT tolerate being called from here directly.  It
;;  ends in CallMusicPlay, which swaps to the music bank and comes back to
;;  whichever bank cur_bank names -- the battle bank, in battle.  That was
;;  harmless while this code lived in the fixed bank, which every chunk carries
;;  identically; from here it would return with the program bank pointing
;;  somewhere else and the next instruction would be another bank's bytes.
;;  opt_msgaudio points cur_bank at this bank for the duration and puts it
;;  back, because the battle code still expects its own value afterwards.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_msgdraw:
    LDA #<$2240                 ; bottom row of the enemy bounding box
    STA $8A
    LDA #>$2240
    STA $8B
    LDA #<btl_msgbuffer
    STA $88
    LDA #>btl_msgbuffer
    STA $89
    LDA #MSGROWS_TOTAL
    STA $68B9
    LDA OPTD_MSGROWS
    STA OPTSCRATCH
  @frame:
    JSR Battle_DrawMessageRow_VBlank    ; waits for vblank, then draws
    JSR @advance
    DEC $68B9
    BEQ @done
    DEC OPTSCRATCH
    BEQ @nextframe
  @extra:
    JSR Battle_DrawMessageRow           ; more rows in the same frame
    JSR @advance
    DEC $68B9
    BEQ @done
    DEC OPTSCRATCH
    BNE @extra
  @nextframe:
    LDA OPTD_MSGROWS
    STA OPTSCRATCH
    JSR opt_msgaudio
    JMP @frame
  @done:
    JSR opt_msgaudio
    RTL

  @advance:
    LDA $88
    CLC
    ADC #$20
    STA $88
    LDA $89
    ADC #$00
    STA $89
    LDA $8A
    CLC
    ADC #$20
    STA $8A
    LDA $8B
    ADC #$00
    STA $8B
    RTS


opt_msgdraw_rev:
    LDA #<$23A0                 ; the bottom row, drawn upward
    STA $8A
    LDA #>$23A0
    STA $8B
    LDA #<(btl_msgbuffer + $B*$20)
    STA $88
    LDA #>(btl_msgbuffer + $B*$20)
    STA $89
    LDA #MSGROWS_TOTAL
    STA $68B9
    LDA OPTD_MSGROWSREV
    STA OPTSCRATCH
  @frame:
    JSR Battle_DrawMessageRow_VBlank
    JSR @retreat
    DEC $68B9
    BEQ @done
    DEC OPTSCRATCH
    BEQ @nextframe
  @extra:
    JSR Battle_DrawMessageRow
    JSR @retreat
    DEC $68B9
    BEQ @done
    DEC OPTSCRATCH
    BNE @extra
  @nextframe:
    LDA OPTD_MSGROWSREV
    STA OPTSCRATCH
    JSR opt_msgaudio
    JMP @frame
  @done:
    JSR opt_msgaudio
    RTL

  @retreat:
    LDA $88
    SEC
    SBC #$20
    STA $88
    LDA $89
    SBC #$00
    STA $89
    LDA $8A
    SEC
    SBC #$20
    STA $8A
    LDA $8B
    SBC #$00
    STA $8B
    RTS

;;  Update the picture and the music without losing the program bank.  See the
;;  note above opt_msgdraw: the audio path returns through cur_bank.
opt_msgaudio:
    LDA cur_bank
    PHA
    LDA #CHUNK_OPT
    STA cur_bank
    JSR Battle_UpdatePPU_UpdateAudio_FixedBank
    PLA
    STA cur_bank        ; the battle code still expects its own value
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Speed Hacks: move the NPCs who stand in doorways
;;
;;  The last piece of the bundle, and the only one that is not a timing change:
;;  a handful of townspeople stand where the player has to walk round them, and
;;  FFR shifts them aside.
;;
;;  A patch list applied after the map's objects are loaded, rather than a
;;  second copy of the object table.  The table is $30 bytes for each of 64
;;  maps; this is nine entries of four bytes, and it costs nothing when the
;;  flag is off.  Only EnterStandardMap reloads objects -- ReenterStandardMap,
;;  which is the path back from a battle or the menu, does not -- so toggling
;;  the flag takes effect the next time the player enters or changes a map.
;;
;;  Each entry is map, slot, x, y.  Every one of them ends up stationary and
;;  outside a room, so the flags are a constant rather than a fifth byte.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_NpcMoves:
  .BYTE  0,  0, $11, $02        ; Coneria, north soldier
  .BYTE  0,  4, $12, $14        ; Coneria, south gal
  .BYTE  0,  7, $1E, $0B        ; Coneria, east guy
  .BYTE  1,  4, $1F, $05        ; Pravoka, old man
  .BYTE  1,  5, $08, $0E        ; Pravoka, woman
  .BYTE  2,  0, $24, $19        ; Elfland, entrance elf
  .BYTE  6, 13, $29, $1B        ; Onrac guy
  .BYTE  7,  3, $21, $07        ; Lefein guy
  .BYTE  8,  5, $07, $0F        ; Coneria Castle, ghost lady
lut_NpcMovesEnd:

opt_movenpcs:
    LDA OPTFB_SPEEDHACKS
    AND #OPTFM_SPEEDHACKS
    BEQ @out
    PHB
    PHK
    PLB
    LDX #$00
  @loop:
    CPX #lut_NpcMovesEnd - lut_NpcMoves   ; bounded by the table's length; a
    BEQ @done                             ;   sentinel that went missing would
    LDA lut_NpcMoves, X                   ;   walk into the code behind it and
    CMP cur_map                           ;   move objects from nonsense
    BNE @next

    LDA lut_NpcMoves+1, X       ; the slot, as an offset into mapobj
    ASL A                       ;   -- sixteen bytes per object
    ASL A
    ASL A
    ASL A
    TAY
    LDA #NPCMOVE_FLAGS
    STA mapobj_flgs, Y
    LDA lut_NpcMoves+2, X
    STA mapobj_physX, Y         ; the physical and graphical positions have to
    STA mapobj_gfxX, Y          ;   agree, or the sprite slides to its old spot
    LDA lut_NpcMoves+3, X
    STA mapobj_physY, Y
    STA mapobj_gfxY, Y

  @next:
    TXA
    CLC
    ADC #4
    TAX
    JMP @loop
  @done:
    PLB
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Battle Magic Menu Wraparound
;;
;;  Two entry points, one per direction, each answering one question: the
;;  cursor is on the last row of the page it can move off -- may it?
;;
;;  Vanilla says yes only when the page it would land on exists, which is page
;;  1 going down and page 0 going up.  The flag says yes always, and in the two
;;  cases vanilla refuses, leaves $6AF8 holding a value the caller's own INC or
;;  DEC turns into the page across the seam.  The caller does the drawing; all
;;  that happens here is the decision.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_magicpgdn:
    LDA btl_magicpage
    BEQ opt_magicyes            ; on page 0: vanilla turns to page 1 unaided
    JSR opt_magicwrapon
    BCC opt_magicno
    LDA #$FF                    ; the caller's INC makes this page 0
    STA btl_magicpage
    BRA opt_magicyes

opt_magicpgup:
    LDA btl_magicpage
    BNE opt_magicyes            ; on page 1: vanilla turns to page 0 unaided
    JSR opt_magicwrapon
    BCC opt_magicno
    LDA #$02                    ; the caller's DEC makes this page 1
    STA btl_magicpage

opt_magicyes:
    SEC
    RTL
opt_magicno:
    CLC
    RTL

;  Carry set if the wraparound flag is on.  A subroutine rather than six bytes
;  written twice, because both entry points want the same answer.
opt_magicwrapon:
    LDA OPTFB_MAGICWRAP
    AND #OPTFM_MAGICWRAP
    BEQ @off
    SEC
    RTS
  @off:
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Autosort Inventory
;;
;;  DrawItemBox walks the items buffer from one end to the other, so the list
;;  comes out in item-number order: sixteen key items the player will touch
;;  once each, and only then the tents and potions they open the menu for.
;;
;;  This rebuilds the same list grouped by what it is -- potions, lodgings,
;;  key items -- which is the order FFR uses.  It runs after the vanilla fill
;;  rather than in place of it, so with the flag off nothing here executes at
;;  all, and it enumerates exactly the set the vanilla loop does: $01-$11 and
;;  $16-$1B, skipping the orbs at $12-$15, which have no menu entries.
;;
;;  Because the set is the same, the count cannot change; it is written again
;;  anyway, along with the terminator, so that a future edit to one loop
;;  cannot leave the list and the cursor limit disagreeing.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_sortinv:
    LDA OPTFB_AUTOSORT
    AND #OPTFM_AUTOSORT
    BEQ @out

    LDY #$00                    ; Y walks the list being built

    LDX #$19                    ; HEAL, PURE, SOFT
  @potions:
    JSR opt_sortinv_one
    CPX #$1C
    BNE @potions

    LDX #$16                    ; TENT, CABIN, HOUSE
  @lodgings:
    JSR opt_sortinv_one
    CPX #$19
    BNE @lodgings

    LDX #$01                    ; the key items, in their own order; $00 is
  @unique:                      ;   unused and $12-$15 are the orbs
    JSR opt_sortinv_one
    CPX #$12
    BNE @unique

    STY cursor_max
    LDA #$00
    STA item_box, Y
  @out:
    RTL

;  One item: add its number to the list if the player has any, then step X.
opt_sortinv_one:
    LDA items, X
    BEQ @none
    TXA
    STA item_box, Y
    INY
  @none:
    INX
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Auto Retargeting
;;
;;  Commands are chosen for the whole party before the round runs, so an enemy
;;  can die between the moment a character is told to hit it and the moment
;;  they swing.  Vanilla swings anyway and the turn is wasted.  This moves the
;;  target to a slot that still holds something.
;;
;;  Two entry points, because the two callers record the defender differently:
;;  the physical attack writes both the index and btl_defender, and magic
;;  writes only btl_defender and may be aimed at a party member.  Doing the
;;  stores here is what lets the physical call site stay the same size as the
;;  pair of stores it replaces.
;;
;;  Where FFR hands back slot $FF when every enemy is gone, this leaves the
;;  target alone.  CheckForBattleEnd runs after every turn and breaks out of
;;  the round once the last slot empties, so the case should be unreachable --
;;  but if it ever is reached, swinging at an empty slot is what vanilla does,
;;  and $FF is a slot number the caller would turn straight into a stat
;;  pointer.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_retarget:
    JSR opt_retarget_pick
    STX battle_defender_index
    STX btl_defender
    RTL

opt_retarget_mag:
    CPX #$09                    ; 9 and up is a party member -- healing, and
    BCS @store                  ;   not something to second-guess
    JSR opt_retarget_pick
  @store:
    STX btl_defender
    RTL

;  X = the chosen enemy slot, in and out.
opt_retarget_pick:
    LDA OPTFB_AUTORETARGET
    AND #OPTFM_AUTORETARGET
    BEQ @keep
    LDA btl_enemyIDs, X
    CMP #$FF                    ; $FF is how a defeated enemy leaves the lineup
    BNE @keep                   ;   -- see CheckForBattleEnd
    LDY #$08                    ; highest slot first, as FFR picks it
  @scan:
    LDA btl_enemyIDs, Y
    CMP #$FF
    BNE @take
    DEY
    BPL @scan
  @keep:
    RTS
  @take:
    TYA
    TAX
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Identify Treasures
;;
;;  Called from DrawDialogueString once the pointer for a string in the upper
;;  half of the table has been loaded, with X still holding the doubled id.
;;  Doubling is only ambiguous across the two halves, and this is the upper
;;  one, so $E2 here means $F1 and nothing else.
;;
;;  The vanilla string says "Can't hold anymore." and leaves the player to
;;  guess what; ours names it.  Swapping the pointer rather than the id keeps
;;  this out of the dialogue bank, which is a raw blob with its own pointer
;;  table and no room to grow.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_dlgident:
    CPX #(DLGID_TCGET * 2) .MOD $100
    BEQ @found
    CPX #(DLGID_CANTCARRY * 2) .MOD $100
    BNE @out
    LDA OPTFB_IDTREASURE
    AND #OPTFM_IDTREASURE
    BEQ @out
    LDA #<lut_CantHoldWhat
    STA text_ptr
    LDA #>lut_CantHoldWhat
    STA text_ptr+1
    RTL

    ;  The chest's own dialogue, shortened from three lines to one -- but only
    ;  when Chest Information is appending its six, which is what makes the
    ;  longest items overflow the box.  With the flag off the cartridge's
    ;  wording stands, because there is nothing wrong with it.
  @found:
    LDA OPTFB_CHESTINFO
    AND #OPTFM_CHESTINFO
    BEQ @out
    LDA #<lut_YouFound
    STA text_ptr
    LDA #>lut_YouFound
    STA text_ptr+1
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Enemy Status Attacks
;;
;;  An enemy whose attack carries an ailment rolls for it once per swing, and
;;  the roll is gated on "have any hits connected" rather than "did this one".
;;  So once the enemy lands a single hit, every miss for the rest of the
;;  attack still gets a chance to poison or stone you.  The disassembly says
;;  as much at the call site.
;;
;;  Answer the question the code meant to ask.  A miss leaves math_dmgcalc at
;;  zero: the hit loop zeroes it each iteration, and only the hit path writes
;;  it -- with a floor of one, so a fully absorbed hit still reads as a hit.
;;  The crit block that runs in between can add to it, but a crit needs
;;  critchance >= randhit while a miss needs randhit > hitchance, and the game
;;  takes it for granted that crit chance never exceeds hit chance; Disch's
;;  comment on the crit test says it outright.
;;
;;  Both bytes have to be read.  Damage is clipped to 255 before absorb comes
;;  off it, so a hit alone cannot exceed the low byte -- but the crit block
;;  runs between the miss branch and this check and adds base damage on top,
;;  which can total exactly 256 and read as a miss.  FFR never has to think
;;  about this: it retargets the miss branch to skip the whole iteration, which
;;  costs a byte bank $0C does not have.
;;
;;  FFR instead retargets the miss branch to skip the rest of the iteration
;;  outright, which also stops a miss counting toward crits and total damage.
;;  That needs a spare byte in bank $0C, which there is not; this is the same
;;  fix aimed only at the bug the comment describes.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_thishit:
    LDA OPTFB_STATUSATK
    AND #OPTFM_STATUSATK
    BEQ @vanilla
    LDA math_dmgcalc            ; nonzero exactly when this swing landed
    ORA math_dmgcalc+1          ;   -- both bytes: a crit adds base damage on
    RTL                         ;   top, so the total can reach 256 and leave
                                ;   the low byte reading as a miss
  @vanilla:
    LDA battle_hitsconnected
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Run -> Wait
;;
;;  Some formations cannot be run from at all and vanilla gives no sign of it
;;  until a turn has been spent finding out.  With the flag on those fights
;;  label the command WAIT and answer it with "Nothing happens" -- the same
;;  turn is spent, but it reads as a choice rather than a failure.
;;
;;  The body is here rather than in the fixed bank, which has 28 bytes left.
;;  Only OptRunFail and the string itself stay there, and for reasons: see the
;;  note beside them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  Called for each block of the command box, with Y on the block's last byte.
opt_runlabel:
    CPY #6*5-1                  ; only the last block, whose text is "RUN"
    BNE @out
    PHA                         ; vanilla reaches AddBlockToBuffer with the
    JSR opt_iswait              ;   table byte still in A; leave it that way
    BCC @keep
      LDA #<lut_WaitString      ; the block's last two bytes are its text
      STA btl_msgdraw_hdr+3     ;   pointer -- see lua_BattleCommandBoxInfo
      LDA #>lut_WaitString
      STA btl_msgdraw_hdr+4
  @keep:
    PLA
  @out:
    RTL

;  The same question, for OptRunFail over in the fixed bank.  Carry survives
;  RTL, which touches no flags.
opt_runiswait:
    JSR opt_iswait
    RTL

;  Carry set when this fight should say WAIT: the flag is on and the formation
;  is one that can never be run from.  Reaching Battle_PlayerTryRun's failure
;  exit with the no-run bit still set means the fight was never runnable --
;  when it is set the luck roll is skipped entirely -- so reading it a second
;  time is enough to tell the two failures apart.
opt_iswait:
    LDA OPTFB_RUNWAIT
    AND #OPTFM_RUNWAIT
    BEQ @no
    LDA btlform_norun
    LSR A                       ; the no-run flag is bit 0; straight to carry
    RTS
  @no:
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Gold and XP scaling
;;
;;  SumBattleReward adds up one field across the nine enemy slots and leaves
;;  the total in battlereward.  It is called twice at the end of a battle,
;;  once for experience and once for gold, so scaling its result covers both
;;  -- and covers the figures the end-of-battle boxes print as well as the
;;  amounts actually awarded, which would otherwise disagree.
;;
;;  The setting counts halves: 2 is 100%, 5 is 250%, 0 is nothing at all.  So
;;  the arithmetic is "add the total to itself <step> times, then halve".
;;  Repeated addition rather than the S-PPU multiplier because the step is at
;;  most ten and this runs once per battle, which makes the multiplier's
;;  eight-cycle window a hazard bought for no gain.
;;
;;  FFR does this by scaling every enemy's reward in the ROM when it builds a
;;  seed.  That is not open to a runtime flag, so this scales the sum instead.
;;  The two differ in rounding: per-enemy scaling rounds nine times and this
;;  rounds once, so this is very slightly the more generous of the two.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_scalereward:
    LDA OPT_GOLDXP
    CMP #GOLDXP_100
    BEQ @out                    ; 100%: exactly what the game just computed
    TAY                         ; Y = the number of halves to add up

    LDA #$00                    ; a 32-bit accumulator; the reward is 24, and
    STA OPTREWARD               ;   ten times a 24-bit value still fits
    STA OPTREWARD+1
    STA OPTREWARD+2
    STA OPTREWARD+3
    CPY #$00
    BEQ @store                  ; 0%: the zeroed accumulator is the answer

  @add:
    CLC
    LDA OPTREWARD
    ADC battlereward
    STA OPTREWARD
    LDA OPTREWARD+1
    ADC battlereward+1
    STA OPTREWARD+1
    LDA OPTREWARD+2
    ADC battlereward+2
    STA OPTREWARD+2
    LDA OPTREWARD+3
    ADC #$00
    STA OPTREWARD+3
    DEY
    BNE @add

    LSR OPTREWARD+3             ; halve, because the step counts 50% units
    ROR OPTREWARD+2
    ROR OPTREWARD+1
    ROR OPTREWARD

    LDA OPTREWARD+3             ; battlereward is three bytes and the game has
    BEQ @store                  ;   nowhere to put a fourth, so peg it
    LDA #$FF
    STA OPTREWARD
    STA OPTREWARD+1
    STA OPTREWARD+2

  @store:
    LDA OPTREWARD
    STA battlereward
    LDA OPTREWARD+1
    STA battlereward+1
    LDA OPTREWARD+2
    STA battlereward+2
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Repeated Potion Use
;;
;;  Vanilla drops back to the item menu after every potion, so healing a party
;;  of four is four trips through it.  With the flag on the target menu stays
;;  up while any of that potion remain.
;;
;;  In: X = the item's offset from items.  Out: carry set to offer another.
;;  The potion is spent either way -- the decrement is the caller's old
;;  instruction, moved in here so the call site stays small.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_usedpotion:
    DEC items, X
    LDA OPTFB_REPEATPOTION
    AND #OPTFM_REPEATPOTION
    BEQ @no
    LDA items, X                ; none left is the end of it either way
    BEQ @no
    SEC
    RTL
  @no:
    CLC
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Buy Quantity: the arithmetic
;;
;;  shop_curprice is two bytes and both Shop_CanAfford and ShopPayPrice treat
;;  it as sixteen bits, so a total has to fit there.  Rather than widen those
;;  -- they are shared with every other shop -- the quantity is capped so the
;;  total cannot overflow.  FFR instead carries a three-byte price and pegs it
;;  at $FFFFFF, which makes an over-large order simply unaffordable; capping
;;  lets the player still buy as many as the money could ever cover, and never
;;  undercharges.
;;
;;  For potions, which is what anyone wants this for, the cap is 99 anyway.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  In: OPTSHOPUNIT.  Out: OPTSHOPMAX, the largest 1..99 whose total fits.
opt_shopmax:
    LDA #$01
    STA OPTSHOPMAX
    LDA OPTSHOPUNIT
    STA OPTSCRATCH
    LDA OPTSHOPUNIT+1
    STA OPTSCRATCH+1
  @try:
    LDA OPTSHOPMAX
    CMP #99
    BCS @done
    CLC
    LDA OPTSCRATCH
    ADC OPTSHOPUNIT
    TAX
    LDA OPTSCRATCH+1
    ADC OPTSHOPUNIT+1
    BCS @done                   ; one more would pass $FFFF
    STA OPTSCRATCH+1
    STX OPTSCRATCH
    INC OPTSHOPMAX
    BNE @try                    ; always: OPTSHOPMAX stops at 99
  @done:
    RTL

;  shop_curprice = OPTSHOPUNIT * OPTSHOPQTY.  Cannot overflow: the quantity
;  was held to OPTSHOPMAX while it was being chosen.
opt_shopscale:
    LDA #$00
    STA shop_curprice
    STA shop_curprice+1
    LDY OPTSHOPQTY
    BEQ @out
  @add:
    CLC
    LDA shop_curprice
    ADC OPTSHOPUNIT
    STA shop_curprice
    LDA shop_curprice+1
    ADC OPTSHOPUNIT+1
    STA shop_curprice+1
    DEY
    BNE @add
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Enemy and boss stat scaling
;;
;;  FFR scales the enemy table in the ROM when it builds a seed.  A runtime
;;  flag cannot, so this scales the copy the battle makes -- and, for the three
;;  stats the battle reads straight out of ROM rather than that copy, the
;;  values after they are loaded.  Same stats, same factors, same clamps.
;;
;;  Which stats, and with which of FFR's adjustment factors:
;;
;;      HP        1.00      absorb   0.50      damage   0.25
;;      evade     1.00      hits     0.50      crit%    0.50
;;      hit%      1.00
;;
;;  Morale is not scaled: FFR only touches it when IncludeMorale is set, and
;;  that flag defaults off.  Evade is clamped to $F0, which is FFR's default
;;  EvadeCap of "medium".  Neither has a control of its own here.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

BOSS_PIRATE  = 15
BOSS_GARLAND = 105
BOSS_ASTOS   = 113
BOSS_FIRST   = 118             ; WarMech through Chaos are contiguous

;  Carry set if the enemy id in A is one FFR counts as a boss.
opt_isboss:
    CMP #BOSS_FIRST
    BCS @yes
    CMP #BOSS_PIRATE
    BEQ @yes
    CMP #BOSS_GARLAND
    BEQ @yes
    CMP #BOSS_ASTOS
    BEQ @yes
    CLC
    RTS
  @yes:
    SEC
    RTS

;  A = enemy id.  Picks the setting that applies and leaves n in OPTSTATN.
opt_statn:
    JSR opt_isboss
    LDA OPT_ENEMY
    BCC @got
    LDA OPT_BOSS
  @got:
    CLC
    ADC #$01                    ; step 3 is 100%, so n = step + 1
    STA OPTSTATN
    RTS

;  OPTSTATV *= OPTSTATNUM / (1 << OPTSTATSH), rounded to nearest.
opt_statmul:
    LDA #$00
    STA OPTSTATACC
    STA OPTSTATACC+1
    STA OPTSTATACC+2
    LDY OPTSTATNUM
    BEQ @round
  @add:
    CLC
    LDA OPTSTATACC
    ADC OPTSTATV
    STA OPTSTATACC
    LDA OPTSTATACC+1
    ADC OPTSTATV+1
    STA OPTSTATACC+1
    LDA OPTSTATACC+2
    ADC #$00
    STA OPTSTATACC+2
    DEY
    BNE @add
  @round:
    ;  C# rounds a double half to even, and Math.Round's default is what FFR
    ;  gets, so halves go to the even neighbour rather than always up.
    LDA #$01                    ; den = 1 << shift
    LDY OPTSTATSH
  @den:
    ASL A
    DEY
    BNE @den
    STA OPTSTATMASK
    LSR A
    STA OPTSTATHALF
    DEC OPTSTATMASK             ; mask = den - 1

    LDA OPTSTATACC
    AND OPTSTATMASK
    STA OPTSTATREM              ; what the shift is about to throw away

    LDY OPTSTATSH
  @shift:
    LSR OPTSTATACC+2
    ROR OPTSTATACC+1
    ROR OPTSTATACC
    DEY
    BNE @shift

    LDA OPTSTATREM
    CMP OPTSTATHALF
    BCC @keep                   ; below half: down
    BNE @bump                   ; above half: up
    LDA OPTSTATACC
    AND #$01
    BEQ @keep                   ; exactly half: only bump an odd result
  @bump:
    INC OPTSTATACC
    BNE @keep
    INC OPTSTATACC+1
  @keep:
    LDA OPTSTATACC
    STA OPTSTATV
    LDA OPTSTATACC+1
    STA OPTSTATV+1
    LDA OPTSTATACC+2            ; FFR scales into an int and clamps after, so
    STA OPTSTATOVF              ;   the callers need what did not fit
    RTS

;  Set up OPTSTATNUM/OPTSTATSH for each of FFR's three adjustments.
opt_adj100:
    LDA OPTSTATN                ; n / 4
    STA OPTSTATNUM
    LDA #$02
    STA OPTSTATSH
    RTS
opt_adj50:
    LDA OPTSTATN                ; (n + 4) / 8
    CLC
    ADC #$04
    STA OPTSTATNUM
    LDA #$03
    STA OPTSTATSH
    RTS
opt_adj25:
    LDA OPTSTATN                ; (n + 12) / 16
    CLC
    ADC #$0C
    STA OPTSTATNUM
    LDA #$04
    STA OPTSTATSH
    RTS

;  Scale one byte through the adjustment already set up, clamping at A's
;  value on entry to @clamp.  In: OPTSTATV low byte.  Out: A.
opt_statbyte:
    LDA #$00
    STA OPTSTATV+1
    JSR opt_statmul
    LDA OPTSTATV+1              ; anything above the low byte is over 255
    ORA OPTSTATOVF
    BEQ @fits
    LDA #$FF
    RTS
  @fits:
    LDA OPTSTATV
    RTS

;  Nothing to do when both settings are 100%: that is FFR's early return, and
;  every fraction above would be 1 anyway.
opt_statoff:
    LDA OPT_ENEMY
    CMP #STAT_100
    BNE @on
    LDA OPT_BOSS
    CMP #STAT_100
    BNE @on
    SEC
    RTS
  @on:
    CLC
    RTS

;  The four stats the battle keeps in its RAM copy, scaled once per battle.
opt_scaleenemies:
    JSR opt_statoff
    BCC @go
    RTL                         ; the loop below is too long to branch over
  @go:
    LDA #$00
    STA OPTSTATSLOT
    LDX #$00                    ; X walks the records, $14 bytes each
  @slot:
    LDY OPTSTATSLOT
    LDA btl_enemyIDs, Y
    CMP #$FF
    BNE @live
    JMP @next                   ; empty slot; too far to branch
  @live:
    LDA btl_enemystats + en_enemyid, X
    JSR opt_statn

    LDA btl_enemystats + en_hp, X       ; HP, adjustment 1.00, capped $7FFF
    STA OPTSTATV
    LDA btl_enemystats + en_hp + 1, X
    STA OPTSTATV+1
    JSR opt_adj100
    JSR opt_statmul
    LDA OPTSTATOVF              ; past 16 bits, or past $7FFF: peg it
    BNE @hpcap
    LDA OPTSTATV+1
    CMP #$80
    BCC @hpok
  @hpcap:
    LDA #$FF
    STA OPTSTATV
    LDA #$7F
    STA OPTSTATV+1
  @hpok:
    LDA OPTSTATV
    STA btl_enemystats + en_hp, X
    LDA OPTSTATV+1
    STA btl_enemystats + en_hp + 1, X

    LDA btl_enemystats + en_defense, X  ; absorb, adjustment 0.50
    STA OPTSTATV
    JSR opt_adj50
    JSR opt_statbyte
    STA btl_enemystats + en_defense, X

    LDA btl_enemystats + en_evade, X    ; evade, 1.00, capped at FFR's
    STA OPTSTATV                        ;   default EvadeCap of "medium"
    JSR opt_adj100
    JSR opt_statbyte
    CMP #$F0
    BCC @evok
    LDA #$F0
  @evok:
    STA btl_enemystats + en_evade, X

    LDA btl_enemystats + en_strength, X ; damage, adjustment 0.25
    STA OPTSTATV
    JSR opt_adj25
    JSR opt_statbyte
    STA btl_enemystats + en_strength, X

  @next:
    TXA
    CLC
    ADC #$14
    TAX
    INC OPTSTATSLOT
    LDA OPTSTATSLOT
    CMP #$09
    BEQ @done
    JMP @slot
  @done:
    RTL

;  The three the battle reads straight out of ROM each time an enemy attacks,
;  scaled after they are loaded.  $84 still points at that enemy's RAM stats.
;
;  First, Weapon Stats' enemy half: FFR's FixWeaponStats write at $325B0, the
;  one the port first left out.  The caller has just loaded the attacker's
;  category from ROM byte $10 and its element from $12 -- its WEAKNESS, which
;  Disch marks "BUGGED ?", and which is why frost wolves bite with fire.  FFR
;  makes the category 0 and takes the element from $0E, the element of the
;  enemy's touch: poison for a poisoner, status for a stunner.  Against a
;  player the element does one thing, decide whether armour that resists it
;  stops the touch's ailment, so this is what makes an Aegis Shield stop a
;  scorpion and an Ice Shield stop nothing a ghoul does.  ($86) points at
;  the enemy's ROM record in bank $0C, which is the data bank we were called
;  with.  Y is the caller's to reload, and it does.
;
;  The touch comes from the randomizer's cache, by the enemy id in RAM, since
;  Status attacks may have moved it: the ailment always -- bank $0C's load of
;  it from ROM is gone -- and the element under Weapon Stats.  With Status
;  attacks off, both are the record's own, as before.
.import rando_touch
opt_scaleatk:
    LDY #en_enemyid
    LDA ($84), Y
    JSL rando_touch + RANDOFAR      ; A = the ailment, Y = the element
    STA btl_attacker_attackailment
    LDA OPTFB_WEAPONSTATS
    AND #OPTFM_WEAPONSTATS
    BEQ @scale
    LDA #$00
    STA btl_attacker_category
    STY btl_attacker_element
  @scale:
    JSR opt_statoff
    BCS @out
    LDY #en_enemyid
    LDA ($84), Y
    JSR opt_statn

    LDA btl_attacker_hitrate            ; hit%, adjustment 1.00
    STA OPTSTATV
    JSR opt_adj100
    JSR opt_statbyte
    STA btl_attacker_hitrate

    LDA btl_attacker_numhits            ; hits, adjustment 0.50, floored at 1
    STA OPTSTATV
    JSR opt_adj50
    JSR opt_statbyte
    BNE @hitsok
    LDA #$01
  @hitsok:
    STA btl_attacker_numhits

    LDA btl_attacker_critrate           ; crit%, adjustment 0.50
    STA OPTSTATV
    JSR opt_adj50
    JSR opt_statbyte
    STA btl_attacker_critrate
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Improved CURE/HEAL/LAMP/AMUT and FIRE/LIT/ICE/HARM
;;
;;  FFR edits the magic table in the ROM when it builds a seed.  Every one of
;;  its changes is a single byte of a spell's eight-byte record -- effectivity,
;;  or in LAMP and AMUT's case the ailment mask, plus HARM's target byte.
;;
;;  Battle_PrepareMagic works out a pointer to that record and everything
;;  downstream reads through it, so copying the record, editing the copy and
;;  repointing covers every reader in battle without touching any of them.
;;
;;  Out of battle the healing spells do not use the table at all: each has its
;;  own inline "framecounter AND mask, plus base".  Those are handled by
;;  opt_healroll below.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  These tables are read long.  A JSL leaves DBR pointing at the caller's
;  chunk, and opt_magicdata also reads the magic record through
;  (btl_magdataptr),Y, which needs exactly that bank -- so switching DBR to
;  reach our own tables would break the copy.  Naming the bank per access
;  costs a byte each and sidesteps it.
;
;  spell index, the byte FFR writes to MAGDATA_EFFECTIVITY, which flag
SPB_CURE = 0
SPB_FIRE = 1

lut_SpellBuff:
  .BYTE  0, $20, SPB_CURE       ; CURE   16 -> 32
  .BYTE 16, $40, SPB_CURE       ; CUR2   32 -> 64
  .BYTE 32, $80, SPB_CURE       ; CUR3   64 -> 128
  .BYTE 19, $10, SPB_CURE       ; HEAL   12 -> 16
  .BYTE 35, $20, SPB_CURE       ; HEL2   24 -> 32
  .BYTE 51, $40, SPB_CURE       ; HEL3   48 -> 64
  .BYTE  8, $18, SPB_CURE       ; LAMP   cures paralysis as well as darkness
  .BYTE 27, $50, SPB_CURE       ; AMUT   cures paralysis as well as silence
  .BYTE  4,   50, SPB_FIRE      ; FIRE   up to tier-3 effectivity
  .BYTE  7,   60, SPB_FIRE      ; LIT
  .BYTE 12,   70, SPB_FIRE      ; ICE
  .BYTE  1,   60, SPB_FIRE      ; HARM, and single-target below
lut_SpellBuffEnd:

SPELL_HARM = 1


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Spell records that a flag replaces outright
;;
;;  Spell Fixes is five bytes of data and a pile of code; this is the data.
;;  Four of the five are FFR's FixSpellBugs verbatim.  The fifth pair is ours:
;;  FFR raises LOCK and LOK2's accuracy from a separate dropdown, and here that
;;  dropdown is two flags instead -- Spell Fixes takes them to 162, which is
;;  what FFR's own Improved Vanilla preset uses, and the LOK2 flag overrides
;;  that to always hit, which is what its other presets do.  Layered rather
;;  than a dial, so neither flag has to know the other exists.
;;
;;  All of these are gated by Spell Fixes alone, so there is no selector
;;  column; Cast Life replaces whole records and has its own table below.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_SpellFix:
  .BYTE SPELL_LOK2, MAGDATA_EFFECT,      $0E   ; ran the wrong routine
  .BYTE SPELL_HEL2, MAGDATA_EFFECTIVITY,  24   ; healed for less than it claimed
  .BYTE SPELL_SABR, MAGDATA_HITRATE,      10   ; its hit% bonus was nothing
  .BYTE SPELL_LOCK, MAGDATA_HITRATE,     162   ; 64 is why it never landed
  .BYTE SPELL_LOK2, MAGDATA_HITRATE,     162
lut_SpellFixEnd:

;;  Cast Life in battle.  FFR does not write a battle routine for LIFE and
;;  LIF2 -- it rewrites their records to use routine $08, cure ailment, with
;;  the death element, and curing death is revival.  So this is two records,
;;  not a list of fields.  FFR's names map to ours the other way round: its
;;  "routine" is MAGDATA_EFFECT and its "effect" is MAGDATA_EFFECTIVITY.
;;
;;    hit, effectivity, element, target, effect, graphic, palette, unused
lut_LifeRecord:
  .BYTE   0, $01, 0, $10, $08, 224, 43, 0      ; LIFE
  .BYTE   0, $81, 0, $10, $08, 224, 44, 0      ; LIF2


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Cast Life in Battle -- the two messages
;;
;;  With the spell working, it narrated itself wrongly twice: "Ineffective now",
;;  and then "Slain" as it stood the character back up.  Both are vanilla data
;;  that only ever had to make sense for a spell that could not be cast.
;;
;;  The first is lut_MagicBattleMessages, one byte per spell.  LIFE and LIF2
;;  carry $4A, BTLMSG_INEFFECTIVENOW, and BtlMag_PrintMagicMessage prints it
;;  unconditionally for a spell that connected.  The fix is the convention the
;;  game already uses for a cure: PURE and LAMP both carry 0, print nothing, and
;;  let the ailment message speak.  So these two carry 0 as well, while the flag
;;  is on.
;;
;;  The second is arithmetic.  HandleAilmentChanges walks the eight ailment bits
;;  low first, with X counting 8 down to 1, and a cured bit takes
;;  ALTBTLMSG_CURED_1 - 1 + X.  POISON lands on NEUTRALIZED and SLEEP on WOKEUP,
;;  but AIL_DEAD is bit 0, so X is 8 and it lands on ALTBTLMSG_SLAIN -- the
;;  wording for inflicting death, because vanilla never cures it in battle.  Its
;;  neighbour is the same kind of placeholder: the table's entry for curing
;;  STONE is INEFFECTIVENOW, and the comment in Constants.inc says why.
;;
;;  ALTBTLMSG_CURED_1 is the generic "cured", which is what PURE's own cure of
;;  CONF prints.  Reusing it costs nothing; a word of its own would mean growing
;;  the alt-message table, which is a bigger change than this is worth.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  Replaces the LDA lut_MagicBattleMessages, X in BtlMag_PrintMagicMessage.
;  In: X = the spell.  Out: A = the message, Z set if there is none -- which is
;  the flag the BEQ after the call reads, and RTL does not disturb it.
opt_magicmsg:
    LDA OPTFB_CASTLIFE
    AND #OPTFM_CASTLIFE
    BEQ @vanilla
    CPX #SPELL_LIFE
    BEQ @silent
    CPX #SPELL_LIF2
    BNE @vanilla
  @silent:
    LDA #$00                    ; as PURE and LAMP do
    RTL
  @vanilla:
    LDA f:lut_MagicBattleMessages + BANK0CFAR, X
    RTL

;  Replaces the TXA / CLC / ADC at @AilmentCured, four bytes for four.
;  In: X = the ailment loop counter, 8 down to 1.  Out: A = the message, and
;  nonzero, which the BNE after the call depends on.
opt_curedmsg:
    LDA OPTFB_CASTLIFE
    AND #OPTFM_CASTLIFE
    BEQ @vanilla
    CPX #$08                    ; the counter when the bit is AIL_DEAD
    BNE @vanilla
    LDA #ALTBTLMSG_CURED_1      ; ...rather than the wording for dying
    RTL
  @vanilla:
    TXA
    CLC
    ADC #ALTBTLMSG_CURED_1 - 1
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Cast Life in Battle -- letting the spell reach a corpse at all
;;
;;  Battle_PlMag_TargetOnePlayer asks Battle_PlMag_IsPlayerValid whether the
;;  chosen party member can be targeted, and that routine answers "no" for
;;  anyone dead or stoned -- so the caller jumps to Battle_ShowIneffective
;;  before the spell effect is ever reached.  Which is to say the record and the
;;  HP were both beside the point until this: the only party member LIFE is for
;;  is the one the targeting refuses.
;;
;;  This replaces the JSR, so it has to answer the same question the same way:
;;  Z set for a valid target, clear for an invalid one, and the vanilla test is
;;  reproduced below rather than called, there being no path into bank $0C.
;;
;;  FFR passes any CureAilment spell, effect $08, whatever its mask.  This asks
;;  for the two Life tags as well, so PURE, LAMP and AMUT keep refusing a corpse
;;  exactly as they do on the cartridge -- there is no reason for this flag to
;;  change where they can be pointed.
;;
;;  In:  btl_entityptr_obrom points at the target's out-of-battle stats.
;;  Out: Z set if the target is valid.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_playervalid:
    LDA OPTFB_CASTLIFE
    AND #OPTFM_CASTLIFE
    BEQ @vanilla
    LDA btlmag_effect
    CMP #BTLMAG_CUREAILMENT
    BNE @vanilla
    LDA btlmag_effectivity
    CMP #CASTLIFE_LIFE
    BEQ @valid
    CMP #CASTLIFE_LIF2
    BNE @vanilla
  @valid:
    LDA #$00                    ; Z set -- a corpse is precisely the target
    RTL

  @vanilla:
    LDY #ch_ailments - ch_stats
    LDA (btl_entityptr_obrom), Y
    AND #AIL_DEAD | AIL_STONE
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Cast Life in Battle -- the half that makes it stick
;;
;;  BtlMag_Effect_CureAilment clears AIL_DEAD happily enough, and then
;;  BtlMag_PerformSpellEffect puts it straight back, because the defender's HP
;;  is still zero.  HandleAilmentChanges compares the bit before and after, sees
;;  no net change, and the spell reads as ineffective.  Disch's comment on the
;;  routine says it outright: "it does not set the HP to a nonzero value, so
;;  they'll just die again."
;;
;;  So the record alone was never going to be enough, which is the thing worth
;;  recording here: FFR's EnableLifeInBattle writes the same eight bytes we do,
;;  and the reason its LIFE works is that ExtConsumables replaces the whole of
;;  CureAilment in bank $1C -- unconditionally, with no flag of its own -- and
;;  that replacement checks the effectivity for $01 and $81 and diverts to
;;  RecoverHP and SetHPToMax.  The $81 is not an ailment mask with AIL_CONF
;;  along for the ride; it is FFR's tag for LIF2.
;;
;;  This replaces the JSR BtlMag_MarkSpellConnected at the tail of CureAilment,
;;  so the mark is done here too.  One byte at the call site, and no need to
;;  call back into bank $0C -- which there is no path for.
;;
;;  Two deliberate differences from FFR.  It reaches RecoverHP, which rolls
;;  rand[16,32] from the effectivity it sets to $10; this writes the $10 flat.
;;  That keeps the battle RNG untouched, which matters more here than it does in
;;  FFR: Controller Reset exists so the player can re-enter the game at a chosen
;;  RNG index, and a spell that draws a random number only when a flag is on
;;  would make that flag change the sequence.  And FFR's LIF2 path never marks
;;  the spell connected, so it heals without saying it worked; this marks both.
;;
;;  In:  btlmag_effectivity, as CureAilment left it.
;;  Out: nothing.  HP is written straight into the defender's math buffer slot.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_castlife:
    LDA #$01
    STA btlmag_spellconnected   ; what the JSR this replaced did

    ;  A None (nones.asm) stays dead.  The cure above has already taken its
    ;  dead bit off, so put it back, and let the spell not connect.  Only a
    ;  cure with the dead bit in it can reach a None -- its ailments are that
    ;  bit alone -- so this is LIFE and LIF2, flag or no flag.
    LDA btl_defender
    BPL @alive                  ; an enemy
    AND #$03
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    LDA ch_class, X
    CMP #CLS_NONE
    BNE @alive
    LDA btlmag_defender_ailments
    ORA #AIL_DEAD
    STA btlmag_defender_ailments
    STZ btlmag_spellconnected
    RTL
  @alive:

    LDA OPTFB_CASTLIFE
    AND #OPTFM_CASTLIFE
    BEQ @out
    LDA btlmag_effectivity
    CMP #CASTLIFE_LIF2
    BEQ @full
    CMP #CASTLIFE_LIFE
    BNE @out

    ;  LIFE: on their feet with CASTLIFE_HP, or everything they have if that is
    ;  somehow less.  A dead character's HP is zero, so writing is the same as
    ;  adding, and it cannot be the high byte that decides.
    LDA btlmag_defender_hpmax+1
    BNE @flat                   ; max HP >= 256, so the flat value is safe
    LDA btlmag_defender_hpmax
    CMP #CASTLIFE_HP
    BCC @full                   ; max HP below it: give them all of it
  @flat:
    LDA #CASTLIFE_HP
    STA btlmag_defender_hp
    STZ btlmag_defender_hp+1
    RTL

    ;  LIF2: what BtlMag_SetHPToMax would have done.
  @full:
    LDA btlmag_defender_hpmax
    STA btlmag_defender_hp
    LDA btlmag_defender_hpmax+1
    STA btlmag_defender_hp+1
  @out:
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The graphic and palette the selection menu records
;;
;;  Two more bytes read through the *selection* pointer rather than the casting
;;  one, which is the split OptMagicTarget already exists for.  The target byte
;;  was told about overrides; these two were not, so a spell whose record the
;;  options bank replaces got the cartridge's graphic and palette instead.
;;
;;  Cast Life in Battle is where that showed.  Vanilla LIFE and LIF2 are blank
;;  stubs -- hit rate 255, target 16, and zero in every other field -- because
;;  vanilla has no in-battle effect for them, so the menu recorded graphic 0 and
;;  palette 0.  Zero is not one of the eight graphics any spell uses, so the
;;  animation drew out of whatever was at the bottom of the sprite CHR: bits of
;;  the caster.  Our record carries FFR's own 224 and 43/44, and now they arrive.
;;
;;  In:  ($80) = the record GetPointerToMagicData returned, $6B7D = the spell.
;;  Out: $68B3 = graphic, $68B4 = palette, after any override.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_magicgfx:
    LDY #MAGDATA_GRAPHIC
    JSR @field
    STA BTLCMD_MAGGFX
    LDY #MAGDATA_PALETTE
    JSR @field
    STA BTLCMD_MAGPAL
    RTL

  @field:
    LDX BTLCMD_SPELLSEL         ; the spell the menu is on, already zero based
    JSR opt_spelloverride       ; C set and A = the replacement, if there is one
    BCS @out
    LDA ($80), Y                ; ...otherwise the cartridge's own byte
  @out:
    RTS


;;  Does a flag replace this byte of this spell's record?
;;
;;  In: X = spell index, Y = field.  Out: C set and A = the replacement.
;;  X and Y come back untouched, because both callers are mid-loop.
opt_spellfixed:
    STX OPTFIXSP
    STY OPTFIXFD

    LDA OPTFB_CASTLIFE
    AND #OPTFM_CASTLIFE
    BEQ @lock
    CPX #SPELL_LIFE
    BEQ @life
    CPX #SPELL_LIF2
    BNE @lock
    LDA OPTFIXFD                ; LIF2's record is the second of the two
    CLC
    ADC #8
    BRA @record
  @life:
    LDA OPTFIXFD
  @record:
    PHX
    TAX
    LDA f:lut_LifeRecord + OPTFAR, X
    PLX
    SEC
    RTS

  @lock:
    ;  Always-hit beats Spell Fixes' 162, so it is asked first.  It is an
    ;  accuracy of 255 rather than a code path: the roll is [0,200] and
    ;  BtlMag_DidSpellConnect only compares the two, so 255 always connects.
    ;  The one case that is not accuracy is the guaranteed miss on a roll of
    ;  exactly 200, and opt_lockroll below declines to take it.
    LDA OPTFB_LOK2
    AND #OPTFM_LOK2
    BEQ @fixes
    CPY #MAGDATA_HITRATE
    BNE @fixes
    CPX #SPELL_LOCK
    BEQ @always
    CPX #SPELL_LOK2
    BNE @fixes
  @always:
    LDA #255
    SEC
    RTS

  @fixes:
    LDA OPTFB_SPELLFIX
    AND #OPTFM_SPELLFIX
    BEQ @none
    PHX
    LDX #$00
  @scan:
    CPX #lut_SpellFixEnd - lut_SpellFix
    BEQ @gone
    LDA f:lut_SpellFix + OPTFAR, X
    CMP OPTFIXSP
    BNE @next
    LDA f:lut_SpellFix + 1 + OPTFAR, X
    CMP OPTFIXFD
    BEQ @found
  @next:
    INX
    INX
    INX
    BRA @scan
  @found:
    LDA f:lut_SpellFix + 2 + OPTFAR, X
    PLX
    SEC
    RTS
  @gone:
    PLX
  @none:
    CLC
    RTS

;  Does a buff apply to this spell, and what does it change the effectivity
;  to?  Split out of opt_magicdata so the shop's description box asks the
;  same question -- the box has to say what the spell will actually do, and
;  the only way to keep those two answers together is to have one of them.
;
;  In: A = spell index.  Out: C set and A = the new effectivity.
opt_spellbuffed:
    STA OPTSPIDX
    LDX #$00
  @scan:
    CPX #lut_SpellBuffEnd - lut_SpellBuff
    BEQ @none
    LDA f:lut_SpellBuff+OPTFAR, X
    CMP OPTSPIDX
    BEQ @found
    INX
    INX
    INX
    BRA @scan
  @found:
    LDA f:lut_SpellBuff+2+OPTFAR, X      ; is that flag on?
    BNE @fire
    LDA OPTFB_IMPCURE
    AND #OPTFM_IMPCURE
    BRA @test
  @fire:
    LDA OPTFB_IMPFIRE
    AND #OPTFM_IMPFIRE
  @test:
    BEQ @none
    LDA f:lut_SpellBuff+1+OPTFAR, X
    SEC
    RTS
  @none:
    CLC
    RTS

;  Does a buff change this spell's target?  Only HARM's, which stops hitting
;  the whole party.  That rides on Improved FIRE, which is the flag that
;  buffs HARM -- lut_SpellBuff lists it under SPB_FIRE.
;  In: A = spell index.  Out: C set and A = the new target.
opt_spelltarget:
    STA OPTSPIDX
    CMP #SPELL_HARM
    BNE @no
    LDA OPTFB_IMPFIRE
    AND #OPTFM_IMPFIRE
    BEQ @no
    LDA #$02
    SEC
    RTS
  @no:
    LDA OPTSPIDX
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  LOCK and LOK2: the roll that vanilla never takes
;;
;;    BtlMag_Effect_EvadeDown prepares a hit roll, compares it with 200, and
;;  then unconditionally JMPs past everything it just prepared.  Disch's note
;;  says it plainly: "BUGGED -- this should be BEQ, not JMP.  Since it always
;;  jumps, this means the spell never has any effect and always misses."
;;
;;    His comment on the line above says a roll of 200 is an automatic hit.
;;  It is not -- every other spell in the bank treats 200 as a guaranteed
;;  miss and branches to its miss path, BtlMag_Effect_InflictAilment and
;;  BtlMag_Effect_Slow among them.  So the BEQ skips, which is what FFR
;;  writes too.
;;
;;    Out: Z set if the spell should go on to the connect check.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_lockroll:
    LDA OPTFB_LOK2
    AND #OPTFM_LOK2
    BNE @go                     ; always-hit does not take the 200 miss either
    LDA OPTFB_SPELLFIX
    AND #OPTFM_SPELLFIX
    BEQ @skip                   ; vanilla: the JMP, and the spell does nothing
    LDA math_magrandhit
    CMP #200
    BEQ @skip
  @go:
    LDA #$00                    ; Z set: on to the connect check
    RTL
  @skip:
    LDA #$01
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  CUR4, out of battle
;;
;;    Disch again: "BUGGED: game does not check ailments.  So you can cast
;;  this on a stoned or even a dead character!  but while it will refill a
;;  dead character's HP, he will stay dead because he'll still have the 'dead'
;;  ailment."  So the spell and the MP are spent on nothing.
;;
;;    Every other spell in that menu refuses those two targets and loops back
;;  for another -- CureFamily_CantUse plays the error sound and jumps to
;;  CureFamily_Loop.  This is that rule, for the one spell that skipped it.
;;
;;    In: X = the character index the cursor landed on.  Out: C set if the
;;  target was healed, C clear if it was refused.  The error sound and the
;;  loop stay at the call site: a routine that decides can be run by the test
;;  harness, and PlaySFX_Error cannot, because it ends up spinning on an SPC
;;  handshake the harness does not model.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_cur4:
    LDA OPTFB_SPELLFIX
    AND #OPTFM_SPELLFIX
    BEQ @heal                   ; vanilla: heal anyone, dead or stone
    LDA ch_ailments, X
    CMP #$01
    BEQ @refuse
    CMP #$02
    BEQ @refuse
  @heal:
    LDA ch_maxhp+1, X           ; what the site did, unchanged
    STA ch_curhp+1, X
    LDA ch_maxhp, X
    STA ch_curhp, X
    SEC
    RTL
  @refuse:
    CLC                         ; the caller sounds the error and comes back
    RTL                         ;   for another target


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  TMPR and SABR, cast on a player
;;
;;    Both spells raise the target's attack, and SABR its hit rate as well.
;;  Neither has ever worked on a player, and Disch marks both ends of why:
;;  BtlMag_LoadPlayerDefenderStats "does not load btlmag_defender_strength",
;;  and BtlMag_SavePlayerDefenderStats "does not save" it either.  So the
;;  spell adds its effectivity to whatever happened to be at $6882 and the
;;  result goes nowhere.  The hit rate beside it is worse -- nothing in the
;;  game ever named $6884.
;;
;;    Three hooks, each replacing exactly the bytes it needs, which is what
;;  FFR does too; it writes its new loader over PrepareEnemyMagAttack, a
;;  routine Disch calls "never used!  Pointless!", and has to stop calling it.
;;  Ours lives here, so that call can stay where it is and do nothing, as it
;;  always has.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  Replaces the magdef load at the end of BtlMag_LoadPlayerDefenderStats.
opt_magloaddef:
    LDY #btlch_magdef           ; what it did, and must go on doing
    LDA (btl_entityptr_ibram), Y
    STA btlmag_defender_magdef

    LDA OPTFB_SPELLFIX
    AND #OPTFM_SPELLFIX
    BEQ @out
    LDY #btlch_dmg              ; FFR calls this strength; the in-battle
    LDA (btl_entityptr_ibram), Y ;   record calls it dmg, and it is the same
    STA btlmag_defender_strength ;   offset either way
    LDY #btlch_hitrate
    LDA (btl_entityptr_ibram), Y
    STA BTLMAG_DEFHIT
  @out:
    RTL


;;  ...and the evade save at the end of BtlMag_SavePlayerDefenderStats, which
;;  is where the two new values have to go back.
opt_magsavedef:
    LDY #btlch_evade
    LDA btlmag_defender_evade
    STA (btl_entityptr_ibram), Y

    LDA OPTFB_SPELLFIX
    AND #OPTFM_SPELLFIX
    BEQ @out
    LDY #btlch_dmg
    LDA btlmag_defender_strength
    STA (btl_entityptr_ibram), Y
    LDY #btlch_hitrate
    LDA BTLMAG_DEFHIT
    STA (btl_entityptr_ibram), Y
  @out:
    RTL


;;  The same routine writes the defender's magic defence back to the *OB*
;;  record, which would make any change permanent -- Disch says so and calls
;;  it arguably bugged.  Nothing in the game changes magdef during a spell, so
;;  it is inert either way, but FFR moves it to the in-battle record and so
;;  does this.  In: A = the value, already loaded by the line above.
opt_magsavemagdef:
    PHA
    LDA OPTFB_SPELLFIX
    AND #OPTFM_SPELLFIX
    BEQ @ob
    PLA
    LDY #btlch_magdef
    STA (btl_entityptr_ibram), Y
    RTL
  @ob:
    PLA
    LDY #ch_magdef - ch_stats
    STA (btl_entityptr_obrom), Y
    RTL


opt_magicdata:
    LDA btl_attackid
    CMP #$40                    ; $40 and up is an enemy attack, not a spell
    BCS @out
    PHX
    PHY
    TAX                         ; X = the spell, for the accessor
    LDA #$00
    STA OPTFIXANY

    LDY #$07                    ; copy the record, so the edit is ours alone
  @copy:
    LDA (btl_magdataptr), Y
    STA OPTMAGSHADOW, Y
    DEY
    BPL @copy

    ;  ...then ask, for each of the eight bytes, whether a flag replaces it.
    ;  It used to overwrite the two a buff could move; there are more of them
    ;  now -- Spell Fixes rewrites four and Cast Life replaces a record
    ;  outright -- and asking the shop's own rule is the only way the box and
    ;  the spell that gets cast cannot drift apart.
    LDY #$07
  @field:
    JSR opt_spelloverride
    BCC @next
    STA OPTMAGSHADOW, Y
    INC OPTFIXANY
  @next:
    DEY
    BPL @field

    PLY
    PLX
    LDA OPTFIXANY               ; nothing applied: leave the pointer alone
    BEQ @out
    LDA #<OPTMAGSHADOW
    STA btl_magdataptr
    LDA #>OPTMAGSHADOW
    STA btl_magdataptr+1
  @out:
    RTL

;;  The six out-of-battle heal rolls.  Each spell's own code was
;;  "framecounter AND mask, plus base"; FFR widens every mask to twice its
;;  span and doubles the CURE bases, leaving the HEAL bases alone.  Mask and
;;  base never share a bit, so one add serves where vanilla used ORA for one
;;  family and ADC for the other.
;;
;;  In: X = 0..5 for CURE, CUR2, CUR3, HEAL, HEL2, HEL3.  Out: A, Z clear.
lut_HealMask:   .BYTE $0F, $1F, $3F, $07, $0F, $1F
lut_HealBase:   .BYTE $10, $20, $40, $10, $20, $40
lut_HealMaskB:  .BYTE $1F, $3F, $7F, $0F, $1F, $3F
lut_HealBaseB:  .BYTE $20, $40, $80, $10, $20, $40

opt_healroll:
    LDA OPTFB_IMPCURE
    AND #OPTFM_IMPCURE
    BEQ @vanilla
    LDA framecounter
    AND f:lut_HealMaskB+OPTFAR, X
    CLC
    ADC f:lut_HealBaseB+OPTFAR, X
    RTL
  @vanilla:
    LDA framecounter
    AND f:lut_HealMask+OPTFAR, X
    CLC
    ADC f:lut_HealBase+OPTFAR, X
    RTL

;;  In: A = the target byte from the spell's record.  Out: A, possibly HARM's.
;;
;;  The selection menu reads the record through its own pointer, not the one
;;  Battle_PrepareMagic sets up, so the shadow above never reaches it.  Left
;;  alone, HARM would prompt as an all-enemies spell and then be cast as a
;;  single-target one: no prompt, the animation on the wrong side of the
;;  screen, and damage delivered nowhere.
opt_magictarget:
    LDX a:btlmag_spellindex
    CPX #SPELL_HARM
    BNE @out
    PHA                         ; the record's own target, if the flag is off
    LDA OPTFB_IMPFIRE
    AND #OPTFM_IMPFIRE
    BEQ @keep
    PLA
    LDA #$02                    ; one enemy, as FFR sets it
    RTL
  @keep:
    PLA
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Chests Appear Opened
;;
;;  The tileset's property and TSA tables are loaded into RAM on every map
;;  entry, so editing the copy costs nothing permanent and turning the flag
;;  off restores everything on the next map.
;;
;;  Each tile has two property bytes and one byte in each TSA table, so the
;;  TSA index is half the property index.  A chest tile carries its treasure
;;  number in its second property byte, which is the same number the opened
;;  flag is stored under.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_openchests:
    LDA OPTFB_OPENCHESTS
    AND #OPTFM_OPENCHESTS
    BEQ @out
    LDY #$00
  @tile:
    LDA tileset_prop, Y
    AND #TP_SPEC_MASK
    CMP #TP_SPEC_TREASURE
    BNE @next
    LDX tileset_prop+1, Y       ; which chest this tile is
    LDA game_flags, X
    AND #GMFLG_TCOPEN
    BEQ @next                   ; still shut
    TYA
    LSR A                       ; two property bytes per tile, one TSA byte
    TAX
    LDA #OPENCHEST_UL
    STA tsa_ul, X
    LDA #OPENCHEST_UR
    STA tsa_ur, X
  @next:
    INY
    INY
    BNE @tile                   ; 128 tiles, two bytes each
  @out:
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Treasures -- what a new game starts with
;;
;;  Called from NewGamePartyGeneration, so only a new game is affected; a
;;  saved game keeps whatever it saved, because Continue copies SRAM over the
;;  whole of unsram afterwards.
;;
;;  Each vehicle is a "does this exist" byte, and the coordinates beside it
;;  are already filled in by lut_InitUnsramFirstPage -- so granting the bridge
;;  or the canoe is the same single store the game makes when you earn it.
;;
;;  The ship and the airship also move.  The ship's berth is Pravoka, across
;;  a bridge a new party has no way to reach, and the airship's is the desert
;;  a long way south; FFR puts them by Coneria instead, and so does this.
;;
;;  The canal is inverted: it starts at 1, meaning the waterway is still
;;  blocked, and Nerrick clears it with the TNT.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  Better Thief and Ninja
;;
;;    Three changes, all of them FFR's BuffThiefAGI: the Thief starts with 80
;;  agility instead of 10, starts with evade 48 above that instead of 58, and
;;  gains agility at every level rather than one time in four.
;;
;;    The two starting stats are read out of lut_ClassStartingStats by
;;  NewGame_LoadStartingStats, one LDA/STA pair each.  A pair is six bytes and
;;  a JSL is four, so hooking them *frees* two bytes apiece in the fixed bank
;;  -- which is the bank with three.  The table is in chunk $00 and we are not,
;;  so the read is long; that needs the offset in X, because the 65816 has
;;  "long,x" and no "long,y", and the caller is holding it in Y.  TYX and back.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  In: Y = offset into lut_ClassStartingStats, X = character offset.
opt_startagi:
    JSR opt_thiefhere
    BCC @plain
    LDA #THIEF_AGI_BUFFED
    BRA @store
  @plain:
    PHX
    TYX
    LDA f:lut_ClassStartingStats + 3 + BANK00FAR, X
    PLX
  @store:
    STA ch_agil, X
    RTL


;;  The same for evade, which vanilla stores as agility plus 48 -- so the
;;  buffed value is not a second constant, it is the same relationship.
opt_startevade:
    JSR opt_thiefhere
    BCC @plain
    LDA #THIEF_AGI_BUFFED + THIEF_EVA_BONUS
    BRA @store
  @plain:
    PHX
    TYX
    LDA f:lut_ClassStartingStats + 9 + BANK00FAR, X
    PLX
  @store:
    STA ch_evade, X
    RTL


;;  C set if this character is a Thief and the flag is on.  X, Y untouched.
opt_thiefhere:
    LDA OPTFB_THIEFNINJA
    AND #OPTFM_THIEFNINJA
    BEQ @no
    LDA ch_class, X
    CMP #CLS_TH
    BNE @no
    SEC
    RTS
  @no:
    CLC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  Thief and Ninja hit-rate growth -- a value row of its own, not part of the
;;  agility buff above.  FFR keeps them apart too, one dropdown each.
;;
;;    In: A = hit rate so far with carry clear, X = class id.  Out: A = the
;;  level's bonus added, which is what the ADC this replaces left behind.
;;
;;    The step is added on top of the table's 2: none, one or two more, for
;;  FFR's Vanilla, Moderate and Double.  The vanilla number stays in the
;;  table and nowhere else.  CapAAt200 runs after, as it did after the ADC.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_hitgrowth:
    CLC
    ADC f:lut_LvlUpHitRateBonus + BANK0BFAR, X
    CPX #CLS_TH
    BEQ @thief
    CPX #CLS_NJ
    BNE @out
  @thief:
    CLC
    ADC OPT_THIEFHIT
  @out:
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  ...and the third change: agility every level rather than one in four.
;;
;;    The level-up data gives each level a byte whose bits say which stats are
;;  guaranteed to rise; a clear bit is a one-in-four roll instead.  bank $0B
;;  shifts the top three bits off that byte before walking the remaining five,
;;  which is three ASLs of an absolute address -- nine bytes, against four for
;;  a JSL.  So this does the shifting as well as the flag, and hands five bytes
;;  back to a bank that had none.
;;
;;    Both classes here, unlike the starting stats: a promoted character levels
;;  on the Thief's data but carries the Ninja's class id.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_thiefgrowth:
    ASL a:LVLUP_STATBYTE        ; what the three ASLs did
    ASL a:LVLUP_STATBYTE
    ASL a:LVLUP_STATBYTE

    LDA OPTFB_THIEFNINJA
    AND #OPTFM_THIEFNINJA
    BEQ @out
    LDY #ch_class - ch_stats
    LDA (lvlup_chstats), Y
    CMP #CLS_TH
    BEQ @force
    CMP #CLS_NJ
    BNE @out
  @force:
    LDA a:LVLUP_STATBYTE
    ORA #LVLUP_AGI_BIT
    STA a:LVLUP_STATBYTE
  @out:
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  House Restoration
;;
;;    A HOUSE takes 3000 gold, restores 120 HP, offers to save, and then --
;;  only if the player said yes -- restores MP.  Two bugs share those four
;;  lines.  Decline the save and the MP is never restored at all.  Accept it
;;  and the restore still happens *after* the write, so the file just saved
;;  holds the old MP: reload it and the 3000 gold bought 120 HP.
;;
;;    With the flag on this runs in front of the save instead, and
;;  unconditionally.  The vanilla restore after it is left exactly as it was;
;;  when this flag is on it runs a second time against full MP, which costs
;;  nothing and keeps the patch to one instruction.
;;
;;    The flag fills HP as well.  120 is the vanilla figure and it stopped
;;  being a night's rest a long time before the endgame, where a party has
;;  several hundred -- which is also why it went unnoticed: on an early party
;;  120 saturates against a max HP below it and a partial restore cannot be
;;  told from a full one.  FFR has the two as separate flags, HouseMPRestoration
;;  and HousesFillHp, both filed under bugfixes rather than variations; they are
;;  one switch here because nobody who wants either wants the other off.
;;
;;    FFR's HP patch writes JSR MenuFillPartyHP followed by a JSR to $B400,
;;  DrawItemTargetMenu.  Both are needed and the second is the less obvious:
;;  MenuFillPartyHP only writes the numbers, where the MenuRecoverPartyHP the
;;  call site uses ends in a JMP to that same redraw.  Without it the fill is
;;  correct and invisible -- the save prompt goes up over a screen still
;;  showing the pre-fill figures, and the real ones appear only when something
;;  else repaints, which is after the save.
;;
;;    The body is here rather than inline at the call site for two reasons.
;;  Bank $0E has eighteen bytes and this way it spends four of them.  And a
;;  routine can be run by the test harness, where a branch buried in a menu
;;  loop that waits on a button cannot -- so the thing the fix is actually
;;  about, the order, is asserted rather than eyeballed.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Controller Reset -- the acting half
;;
;;  L + X restarts the game with work RAM intact; L + Y wipes zero page on the
;;  way through.  The point of the first is that battlestep and battlestep_sign
;;  at $F5 and $F6 are the index into lut_RNG that decides whether a step
;;  produces an encounter, and GameStart's ClearZeroPage stops at $EF -- so they
;;  survive an ordinary reset, and re-entering from a known index is how the
;;  encounter table gets manipulated.  The second is for when that is not
;;  wanted: on a console the alternative is reaching for the console itself.
;;
;;  Unconditional, with no flag.  L, X and Y are buttons the cartridge never
;;  had, so no vanilla behaviour is displaced and there is nothing a player
;;  might want switched off.
;;
;;  aux_detect in the HAL does the looking, once a frame after the flush, and
;;  leaves the combo in h_padreset on the frame it is pressed.  This is called from WaitForVBlank and acts
;;  on it.  One call site, because every frame loop in the game waits for
;;  vblank -- which is the whole reason for the split.  FFR instead hooks the
;;  three joypad handlers, and those only run when the game reads buttons: both
;;  palette fades poll nothing, so the inn's save fade could not be reset out
;;  of, and the same is true of the battle message waits and the transitions.
;;
;;  What gets cleared is FFR's choice, unchanged: zero page $01 to $FF, by
;;  direct-page indexed store, so work RAM only.  SRAM is never written --
;;  neither the live state at unsram ($6000), nor the saved file at
;;  $6400-$67FF, nor the option block at $6E00 -- so a hard reset costs neither
;;  the save nor the settings.  Nothing has moved since FFR, so nothing about
;;  the range needed rethinking.
;;
;;  FFR's hard reset jumps straight to GameStart, where this goes through
;;  OnReset like the soft one: the hardware is already up either way, so the
;;  longer path costs a few hundred cycles and removes one thing that can be
;;  subtly wrong.
;;
;;  In:  nothing -- h_padreset is the whole input.
;;  Out: A, X and the flags unchanged -- or it never returns.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_padreset:
    ;  The seed's entropy, a frame at a time.  First, so that a frame which
    ;  resets still counts; it preserves everything.
    JSL rando_stir + RANDOFAR
    PHP
    PHX
    PHA                         ; WaitForVBlank's caller may want A
    ;  h_padreset is WRAM at $08xx, and every bank a game chunk runs in mirrors
    ;  WRAM at $0000-$1FFF, so plain absolute reaches it whichever chunk called.
    LDA h_padreset
    BEQ @out
    ;  Clear it before leaving, or the first vblank wait after the reset acts on
    ;  it again.  Neither the wipe below nor OnReset touches this byte.
    LDX #$00
    STX h_padreset
    CMP #PADRESET_HARD
    BEQ @hard
    BRA @enter
  @out:
    PLA
    PLX
    PLP
    RTL

  @hard:
    ;  $FF down to $01, so the encounter index goes with everything else.  $00
    ;  is left alone because the loop ends on it, which is what FFR does too.
    ;
    ;  Direct page, not absolute: the direct page is always bank 0, so this is
    ;  $0000-$00FF and cannot reach SRAM whatever DBR happens to hold.  That
    ;  matters because SRAM is where the save lives -- unsram at $6000, the
    ;  saved file at $6400-$67FF, the option block at $6E00 -- and a hard reset
    ;  must cost none of them.
    ;
    ;  FFR resets the stack before its wipe; no need here, because OnReset does
    ;  TXS a few instructions in.  Nothing below may depend on zero page again,
    ;  and nothing does: the only state carried from here is in the registers.
    LDX #$FF
    LDA #$00
  @wipe:
    STA $00, X
    DEX
    BNE @wipe

  @enter:
    ;  Enter the reset exactly as hal_reset does: PBR and DBR both CHUNK0.  The
    ;  fixed bank is stamped into every chunk, so a near JMP would land in a
    ;  copy of OnReset running under whichever chunk happened to call us, and
    ;  the bank the game comes back up in should not depend on that.  The stack
    ;  is left as it is -- OnReset resets it with TXS a few instructions in.
    LDA #CHUNK0
    PHA
    PLB
    JML OnReset + BANK00FAR


opt_housemp:
    LDA OPTFB_HOUSEMP
    AND #OPTFM_HOUSEMP
    BEQ @out
    CALL0E MenuFillPartyHP      ; the rest of the HP, on top of the 120 the
                                ;   call site has already given
    CALL0E MenuRecoverPartyMP   ; they live in the bank that called us, and we
                                ;   are not in that bank any more
    ;  ...and repaint, because neither of those does.  MenuRecoverPartyHP at
    ;  the call site ends in a JMP to this, which is why the vanilla 120 shows
    ;  up and the fill did not: the numbers were right from here on and the
    ;  screen went on showing the old ones until something else redrew, which
    ;  is after the save prompt.  This is the second half of FFR's patch, the
    ;  JSR $B400 beside its JSR $ABD2 -- dismissed earlier as having no
    ;  business in a HOUSE, when it is the whole reason the fill is visible.
    CALL0E DrawItemTargetMenu
  @out:
    RTL


opt_freestuff:
    ;  The world: the seed and the new-game rows, into the save.
    JSL rando_newgame + RANDOFAR
    LDA OPTFB_FREESHIP
    AND #OPTFM_FREESHIP
    BEQ @airship
    LDA #$01
    STA ship_vis
    LDA #FREESHIP_X             ; and moved: its own berth is Pravoka, which
    STA ship_x                  ;   is across a bridge you would not have
    LDA #FREESHIP_Y
    STA ship_y
  @airship:
    LDA OPTFB_FREEAIRSHIP
    AND #OPTFM_FREEAIRSHIP
    BEQ @bridge
    LDA #$01
    STA airship_vis
    LDA #FREEAIRSHIP_X          ; parked where the party starts, rather than
    STA airship_x               ;   out in the desert
    LDA #FREEAIRSHIP_Y
    STA airship_y
  @bridge:
    LDA OPTFB_FREEBRIDGE
    AND #OPTFM_FREEBRIDGE
    BEQ @canal
    LDA #$01
    STA bridge_vis
  @canal:
    LDA OPTFB_FREECANAL
    AND #OPTFM_FREECANAL
    BEQ @canoe
    LDA #$00                    ; cleared, not set: see above
    STA canal_vis
  @canoe:
    LDA OPTFB_FREECANOE
    AND #OPTFM_FREECANOE
    BEQ @key
    LDA #$01
    STA has_canoe

    ;  The three key items are plain inventory entries, so each is the same
    ;  store the chest or the NPC that holds it would make.  The whole first
    ;  page of unsram, items included, has been filled from
    ;  lut_InitUnsramFirstPage by the time this runs.
  @key:
    LDA OPTFB_FREEKEY
    AND #OPTFM_FREEKEY
    BEQ @chime
    LDA #$01
    STA item_mystickey
  @chime:
    LDA OPTFB_FREECHIME
    AND #OPTFM_FREECHIME
    BEQ @crown
    LDA #$01
    STA item_chime
  @crown:
    LDA OPTFB_FREECROWN
    AND #OPTFM_FREECROWN
    BEQ @lute
    LDA #$01
    STA item_crown
  @lute:
    LDA OPTFB_FREELUTE
    AND #OPTFM_FREELUTE
    BEQ @tail
    LDA #$01
    STA item_lute
  @tail:
    LDA OPTFB_FREETAIL
    AND #OPTFM_FREETAIL
    BEQ @rod
    LDA #$01
    STA item_tail
  @rod:
    LDA OPTFB_FREEROD
    AND #OPTFM_FREEROD
    BEQ @items
    LDA #$01
    STA item_rod

    ;  The starting items: the set's six counts over item_tent..item_soft,
    ;  which lut_InitUnsramFirstPage has left at zero.  None copies its row of
    ;  zeros like any other, so there is no special case; a step past the
    ;  table, which the checksum should have stopped, gives nothing.
  @items:
    LDA OPT_STARTITEMS
    CMP #STARTITEMS_SETS
    BCS @out
    ASL A                       ; * 8, the row stride
    ASL A
    ASL A
    TAX
    LDY #$00
  @count:
    LDA f:lut_StartItems + OPTFAR, X
    STA item_tent, Y
    INX
    INY
    CPY #STARTITEMS_ROW
    BCC @count
  @out:
    RTL


;  FFR's fixed starting sets, StartingInventory.cs, in its order: TENT, CABIN,
;  HOUSE, HEAL, PURE, SOFT, which is also the order of the inventory.  Rows
;  of eight so the index is a shift; the last two bytes are padding.
STARTITEMS_ROW = item_soft + 1 - item_tent
.assert STARTITEMS_ROW = 6, error, "the six consumables are not adjacent"
lut_StartItems:
    .BYTE  0,  0,  0,  0,  0,  0, 0, 0     ; None
    .BYTE  1,  0,  0,  0,  1,  1, 0, 0     ; Safety Bit
    .BYTE  5,  0,  0, 20,  2,  1, 0, 0     ; Beggar's Choice
    .BYTE 10,  0,  0,  0,  0,  0, 0, 0     ; Just Tents
    .BYTE 10,  0,  0, 50,  4,  2, 0, 0     ; Explorer Pack
    .BYTE 15,  5,  1,  0,  0,  0, 0, 0     ; Real Estate
    .BYTE 15,  5,  1, 50,  6,  3, 0, 0     ; Warrior's Standard
    .BYTE 50, 15,  5, 99, 10,  5, 0, 0     ; Royal Packmule
    .BYTE 99, 99, 99, 99, 99, 99, 0, 0     ; Duckling Boon
.assert * - lut_StartItems = 8 * STARTITEMS_SETS, error, "one row per starting set"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  opt_stackshift -- keep teleport nesting off the bottom of the stack
;;
;;  FFR's "Softlock fix" (asm/StackShift.asm), on every ROM as FFR has it.
;;  Every normal teleport nests another DoStandardMap: five bytes pushed and
;;  a JSR, seven bytes of page 1, and only a warp unwinds one.  Stairs that
;;  lead back by teleport (Coneria Castle's) or a loop (the Ice Cave's) can
;;  be walked round until the stack runs off the bottom of the page.  On a NES
;;  that wraps within the page and breaks the next warp.  Here it is worse:
;;  the HAL and the randomizer run native, where S is sixteen bits, and their
;;  pushes would go on down into zero page.
;;
;;  So, called before a normal teleport's pushes: with S under STACK_FLOOR,
;;  slide everything below the oldest teleport frame up over it, seven bytes,
;;  and S with it.  A warp from the second floor then returns to the
;;  overworld rather than the first floor -- the oldest level is forgotten,
;;  and nothing else changes.
;;
;;  The oldest frame is $01F5-$01FB.  The overworld loop resets S to $FF and
;;  JSRs DoOWTransitions, whose @Teleport JSRs DoStandardMap: the first map
;;  runs at S = $FB, and its teleport pushes $01FB-$01F7 and its JSR the
;;  return at $01F6/$01F5.  That is checked before anything moves.  Down here
;;  this level was itself entered by a normal teleport, whose frame sits just
;;  above our own JSL's return, so its return address is @NormalTeleport's:
;;  if the oldest frame's is not the same, the stack is not laid out as this
;;  expects, and it is left alone.  FFR's version does not check.
;;
;;  STACK_FLOOR is compared with S as this routine sees it, three bytes under
;;  the map's own for the JSL's return: so a map running under $83 makes the
;;  next teleport shift, and no map ever runs below $7D.  That leaves 125
;;  bytes under the deepest map, for native code that must never reach $0100:
;;  the harness's deepest routines use 31 (the shops), the settings screen
;;  25, a battle more.  FFR's floor is $30, some 41 bytes on a NES, where
;;  running over only wraps.  Eighteen levels fit before anything is
;;  forgotten; vanilla's deepest walk using each teleport once is 14, all but
;;  three of them the Ordeals maze.
;;
;;  Emulation mode, from the fixed bank, with the caller's data bank -- whose
;;  low 8KB is WRAM, page 1 included.  A, X and the flags are clobbered; the
;;  caller loads A next.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

STACK_FLOOR  = $80
STACK_OLDEST = $F5              ; the oldest teleport frame, $01F5-$01FB
STACK_FRAME  = 7                ; five pushes and a JSR

opt_stackshift:
    TSX
    CPX #STACK_FLOOR
    BCS @out                    ; room enough
    LDA $0104, X                ; this level's teleport frame, above our
    CMP $0100 + STACK_OLDEST    ;   three-byte return: its return address,
    BNE @out                    ;   against the oldest frame's
    LDA $0105, X
    CMP $0100 + STACK_OLDEST + 1
    BNE @out                    ; not a teleport frame: not ours to move
    STX OPTSCRATCH              ; S, where the copy stops
    LDX #STACK_OLDEST - 1       ; the byte below the oldest frame
  @copy:
    LDA $0100, X                ; up seven, highest first, so nothing is
    STA $0100 + STACK_FRAME, X  ;   read after it is written
    DEX
    CPX OPTSCRATCH
    BNE @copy
    TXA                         ; X is S again
    CLC
    ADC #STACK_FRAME
    TAX
    TXS                         ; our own return moved with the rest
  @out:
    RTL
