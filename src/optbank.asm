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
.export opt_drawpresetbox, opt_drawpresetname, opt_titlecursor
.export opt_titleupdown, opt_titleleftright
.export opt_commit_body

.import DrawBox

.segment "BANK_OPT"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Presets
;;
;;  One row per preset, and one named constant per setting, so retuning a
;;  preset is editing a line rather than counting bits.  The Deluxe values are
;;  a starting point and are expected to change.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

OPTF_QOL      = OPTF_SPEEDHACKS | OPTF_FASTWALK | OPTF_FASTSHIP | OPTF_NOSHUFFLE
OPTF_QOL2     = OPTF_IDTREASURE | OPTF_OPENCHESTS | OPTF_BUYQTY | OPTF_RUNWAIT
OPTF_QOL3     = OPTF_MAGICWRAP | OPTF_AUTORETARGET | OPTF_AUTOSORT | OPTF_REPEATPOTION
OPTF_QOL4     = OPTF_SHOPINFO | OPTF_CHESTINFO | OPTF_GUILLOTINE
OPTF_ALLQOL   = OPTF_QOL | OPTF_QOL2 | OPTF_QOL3 | OPTF_QOL4

OPTF_BUGFIX   = OPTF_HOUSEMP | OPTF_WEAPONSTATS | OPTF_SPELLFIXES | OPTF_STATUSATK

OPTF_VAR1     = OPTF_THIEFNINJA | OPTF_CRITRATE | OPTF_ELEMBONUS | OPTF_IMPCURE
OPTF_VAR2     = OPTF_IMPFIRE | OPTF_CASTLIFE | OPTF_LOK2
OPTF_VARIATION= OPTF_VAR1 | OPTF_VAR2

;  Value-row step indices.  See options-design.md for the step tables.
GOLDXP_100    = 2       ; 0%,50%,100%..500% in 50% steps
GOLDXP_250    = 5
ENC_60        = 6       ; Off,10%..100%,150%,200%,300%
ENC_100       = 10
STAT_100      = 3       ; 25%..500% in 25% steps

;  Which preset a cartridge with no valid block comes up in.
OPT_DEFAULT_PRESET = PRESET_IMPROVED

;  Testing aid, until the menu exists.  FFDEBUG=vanilla|improved|deluxe builds
;  a ROM that forces that preset on every boot instead of honouring whatever is
;  in SRAM -- otherwise a block written once keeps its settings across builds
;  and there is no way to exercise a different preset.  A normal build never
;  defines this and reads SRAM as it should.
.ifdef OPT_FORCE
OPT_FORCED_PRESET = OPT_FORCE
.endif

lut_Presets:
    ;       flags (4, low byte first)            goldxp      encounter  enemy      boss
    .DWORD  0                                                              ; Vanilla
    .BYTE   GOLDXP_100, ENC_100, STAT_100, STAT_100
    .DWORD  (OPTF_ALLQOL & ~OPTF_GUILLOTINE) | OPTF_BUGFIX                  ; Improved
    .BYTE   GOLDXP_100, ENC_100, STAT_100, STAT_100
    .DWORD  OPTF_ALLQOL | OPTF_BUGFIX | OPTF_VARIATION                     ; Deluxe
    .BYTE   GOLDXP_250, ENC_60,  STAT_100, STAT_100
PRESET_STRIDE = 8


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
    ASL A                       ; index * 8
    ASL A
    ASL A
    TAX
    LDY #$00
  @copy:
    LDA lut_Presets, X
    STA OPT_FLAGS, Y
    INX
    INY
    CPY #PRESET_STRIDE
    BCC @copy

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
    RTS


;;  Sum every byte of the block except the checksum itself.  Plain 8-bit
;;  addition with the carry dropped -- the game's own save checksum lets carry
;;  run between bytes, which is harder to reason about and buys nothing here.
opt_sum:
    LDA #$00
    LDX #$00
  @loop:
    CLC
    ADC OPTBLOCK, X
    INX
    CPX #OPT_SIZE - 1           ; stop before OPT_CKSUM
    BCC @loop
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
;;  The title screen's preset row
;;
;;  A fourth box below "Respond Rate", at (8,24) and four rows tall, so it ends
;;  on row 27 -- inside the 28 rows the 224-line crop actually shows.  The
;;  cursor gains a third position; left and right cycle the preset while it is
;;  there and go on adjusting the respond rate everywhere else, which leaves
;;  the existing controls exactly as they were for anyone who never moves down
;;  to the new row.
;;
;;  The name is redrawn every frame from a fixed nametable address, the way
;;  TitleScreen_DrawRespondRate redraws its digit, rather than through
;;  DrawComplexString -- it is eight tiles, it has to happen inside vblank, and
;;  this way it needs no cur_bank juggling.  All four names are padded to eight
;;  characters so a shorter one cannot leave the tail of a longer one behind.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  The mode box takes the row the respond rate used to have, and the respond
;  rate moves down to 24 -- see the two patches in patches/bank_0E.
PRESETBOX_X  = 8
PRESETBOX_Y  = 20
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
  .BYTE $FF, $8D, $8E, $95, $9E, $A1, $8E, $FF   ; " DELUXE MODE  "
  .BYTE $96, $98, $8D, $8E, $FF, $FF, $FF, $FF
  .BYTE $FF, $8C, $9E, $9C, $9D, $98, $96, $FF   ; " CUSTOM MODE  "
  .BYTE $96, $98, $8D, $8E, $FF, $FF, $FF, $FF

;  Cursor sprite position per row.  Y is one tile row below the box's top, as
;  the game's own two entries were.  X has to vary now: the first two boxes
;  start at column 11 and the mode box at column 8, so a single fixed X either
;  sits too far from one or overlaps the other.  Sixteen pixels clear of the
;  box edge in both cases.
lut_TitleCursorY:
  .BYTE $58, $80, $A8
lut_TitleCursorX:
  .BYTE $48, $48, $30

;;  Drawn once, with the PPU off, alongside the other three boxes.
opt_drawpresetbox:
    LDA #PRESETBOX_X
    STA box_x
    LDA #PRESETBOX_Y
    STA box_y
    LDA #4
    STA box_ht
    LDA #16
    STA box_wd
    JSR DrawBox
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

;;  In: A = the direction bits.  Moves the cursor between three rows.
opt_titleupdown:
    LDX cursor
    CMP #DOWN
    BNE @up
    INX
    CPX #3
    BCC @set
    LDX #0
    BRA @set
  @up:
    DEX
    BPL @set
    LDX #2
  @set:
    STX cursor
    RTL

;;  In: A = the direction bits.  On the preset row this cycles the preset and
;;  reseals the block; anywhere else it is the respond rate, as before -- and
;;  that now writes through to the block so the setting survives a power cycle.
opt_titleleftright:
    PHB
    PHK
    PLB
    LDX cursor
    CPX #2
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
