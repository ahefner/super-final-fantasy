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
.export opt_explodecount, opt_responddelay, opt_chkalivex, opt_chkalivey
.export opt_respondlookup, opt_msgdraw, opt_msgdraw_rev, opt_movenpcs
.export opt_magicpgdn, opt_magicpgup, opt_sortinv
.export opt_retarget, opt_retarget_mag, opt_dlgident, opt_thishit
.export opt_runlabel, opt_runiswait, opt_scalereward
.import lut_WaitString
.import lut_CantHoldWhat
.export opt_drawpresetbox, opt_drawpresetname, opt_titlecursor
.export opt_titleupdown, opt_titleleftright
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
    CPX #(DLGID_CANTCARRY * 2) .MOD $100
    BNE @out
    LDA OPTFB_IDTREASURE
    AND #OPTFM_IDTREASURE
    BEQ @out
    LDA #<lut_CantHoldWhat
    STA text_ptr
    LDA #>lut_CantHoldWhat
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
    STA OPTSCRATCH              ;   ten times a 24-bit value still fits
    STA OPTSCRATCH+1
    STA OPTSCRATCH+2
    STA OPTSCRATCH+3
    CPY #$00
    BEQ @store                  ; 0%: the zeroed accumulator is the answer

  @add:
    CLC
    LDA OPTSCRATCH
    ADC battlereward
    STA OPTSCRATCH
    LDA OPTSCRATCH+1
    ADC battlereward+1
    STA OPTSCRATCH+1
    LDA OPTSCRATCH+2
    ADC battlereward+2
    STA OPTSCRATCH+2
    LDA OPTSCRATCH+3
    ADC #$00
    STA OPTSCRATCH+3
    DEY
    BNE @add

    LSR OPTSCRATCH+3            ; halve, because the step counts 50% units
    ROR OPTSCRATCH+2
    ROR OPTSCRATCH+1
    ROR OPTSCRATCH

    LDA OPTSCRATCH+3            ; battlereward is three bytes and the game has
    BEQ @store                  ;   nowhere to put a fourth, so peg it
    LDA #$FF
    STA OPTSCRATCH
    STA OPTSCRATCH+1
    STA OPTSCRATCH+2

  @store:
    LDA OPTSCRATCH
    STA battlereward
    LDA OPTSCRATCH+1
    STA battlereward+1
    LDA OPTSCRATCH+2
    STA battlereward+2
  @out:
    RTL
