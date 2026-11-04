; ---------------------------------------------------------------------------
;  fun.asm -- the FUN% section's code (user, 2026-11-03, fun-percent.txt:
;  "goofy flags that don't change anything about gameplay").  In Taverns'
;  chunk (CHUNK_TAVERN), which has the room.  Stereo Sound is the HAL's and
;  the SPC700's (apu_pan); this is Palette swap.
;
;  Palette swap (user: one On/Off, "Fixed per seed", the overworld too;
;  "enemy colors are fine too", and "some artistic license to tint the
;  background grass color toward blue or brown"):
;
;    deal_palswap  the seed's tables, into the cache with the rest of it:
;                  the 64 battle palettes shuffled, as FFR's PaletteSwap
;                  (Fun.cs) shuffles them, and a tint for every map, the
;                  overworld and each battle backdrop (randoref.build_palswap)
;    fun_smpal     a standard map's palettes tinted as they load -- its
;                  three background palettes and its three in rooms, the
;                  fourth of each the dialogue box's -- then Short ToFR's
;    fun_owpal     the overworld's four, likewise
;    fun_bdpal     a battle backdrop's three colours
;    fun_btlpal     an enemy palette's number, through the shuffle
;
;  A tint moves a colour's hue a few steps round the NES's twelve, the
;  same for every colour of the map, and keeps its brightness: greens go
;  toward teal and blue one way, olive and brown the other, and black,
;  white and the greys stay.  Each is a no-op with the row Off.  From the
;  fixed bank, by JSL, emulation mode, A8 X8, the caller's DBR (which
;  decodes low WRAM); deal_palswap from the build, native.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.import rando_warmfar, rando_belowfar, rando_fyfar, rando_smpal
.export deal_palswap, fun_smpal, fun_owpal, fun_bdpal, fun_btlpal

.segment "BANK_TAVERN"

STREAM_PALSWAP  = $50414C53     ; "PALS": Palette swap's tables (deal_palswap)
PALSWAP_PALS    = 64            ; lut_BattlePalettes' four-colour palettes
TINT_STEPS      = 7             ; -3..+3
SRAMFAR_FUN     = CHUNK0 * $10000 + OPT_FUN

;;  deal_palswap -- Palette swap's tables for the seed: RW_PALPERM a
;;  Fisher-Yates of 0..63, then RW_TINT a draw below TINT_STEPS each, all on
;;  STREAM_PALSWAP.  From build (rando.asm): native, DBR = $7F, A8 I16.
;;  Out: the same.
deal_palswap:
    REP #$30
    .a16
    .i16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_PALSWAP)
    STA a:.LOWORD(RW_RNG)
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_PALSWAP)
    STA a:.LOWORD(RW_RNG) + 2
    JSL rando_warmfar + RANDOFAR
    LDA #.LOWORD(RW_PALPERM)
    STA a:.LOWORD(RW_FK)
    SEP #$20
    .a8
    LDX #$0000
  @fill:
    TXA
    STA a:.LOWORD(RW_PALPERM), X
    INX
    CPX #PALSWAP_PALS
    BCC @fill
    LDA #PALSWAP_PALS
    JSL rando_fyfar + RANDOFAR
    LDX #$0000
  @tint:
    PHX
    LDA #TINT_STEPS
    JSL rando_belowfar + RANDOFAR
    PLX
    STA a:.LOWORD(RW_TINT), X
    INX
    CPX #PALSWAP_TINTS
    BCC @tint
    RTL

.a8
.i8                             ; the rest: from the fixed bank, emulation mode

;;  Z clear when Palette swap is on.  A clobbered.
palswap_on:
    LDA f:SRAMFAR_FUN
    AND #FUN_PALSWAP
    RTS

;;  The colour in A tinted by FUN_CODE: a hue of 1-12 moved by FUN_CODE - 3
;;  round the twelve, the brightness bits kept; hues 0 and 13-15, the greys
;;  and black, as they are.  X and Y kept.
tint_one:
    PHA
    AND #$0F
    BEQ @keep
    CMP #$0D
    BCS @keep
    CLC
    ADC f:FUN_CODE              ; hue + code, 1..18
    SEC
    SBC #3                      ; hue + the shift, -2..15
    BEQ @under
    BMI @under
    CMP #13
    BCC @have
    SBC #12                     ; (C set)
    BRA @have
  @under:
    CLC
    ADC #12
  @have:
    STA f:FUN_HUE
    PLA
    AND #$F0
    ORA f:FUN_HUE
    RTS
  @keep:
    PLA
    RTS

;;  load_map_pal from Y up to FUN_END, each colour tinted.  Y moved.
tint_lmp:
    LDA load_map_pal, Y
    JSR tint_one
    STA load_map_pal, Y
    INY
    TYA
    CMP f:FUN_END
    BCC tint_lmp
    RTS

;;  The end of LoadSMTilesetData (optopenchests.patch): this map's tint over
;;  its three background palettes and its three in rooms -- each set's fourth
;;  is the dialogue box's, $0F $00 $01 $30 on every map -- then Short ToFR's
;;  colour, as before.
fun_smpal:
    JSR palswap_on
    BEQ @out
    LDX cur_map
    LDA f:RW_TINT, X
    STA f:FUN_CODE
    LDA #$0C
    STA f:FUN_END
    LDY #$00
    JSR tint_lmp
    LDA #$2C
    STA f:FUN_END
    LDY #$20
    JSR tint_lmp
  @out:
    JML rando_smpal + RANDOFAR

;;  The end of LoadOWTilesetData (palswap.patch): the overworld's tint over
;;  its four background palettes, all of them land.
fun_owpal:
    JSR palswap_on
    BEQ @out
    LDA f:RW_TINT + TINT_OW
    STA f:FUN_CODE
    LDA #$10
    STA f:FUN_END
    LDY #$00
    JSR tint_lmp
  @out:
    RTL

;;  After LoadBattleBackdropPalette's copy (palswap.patch): X = the backdrop
;;  times four, cur_pal 0-3 its colours; colours 1-3 tinted, 0 the black
;;  behind.  X not kept.
fun_bdpal:
    JSR palswap_on
    BEQ @out
    TXA
    LSR A
    LSR A
    TAX
    LDA f:RW_TINT + TINT_BACKDROP, X
    STA f:FUN_CODE
    LDX #1
  @colour:
    LDA cur_pal, X
    JSR tint_one
    STA cur_pal, X
    INX
    CPX #4
    BCC @colour
  @out:
    RTL

;;  The top of LoadBattlePalette (palswap.patch): A = a formation's palette
;;  number, through the shuffle.  Y kept, X not.
fun_btlpal:
    PHA
    JSR palswap_on
    BEQ @off
    PLA
    AND #PALSWAP_PALS - 1
    TAX
    LDA f:RW_PALPERM, X
    RTL
  @off:
    PLA
    RTL
