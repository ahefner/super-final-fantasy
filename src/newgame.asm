; ---------------------------------------------------------------------------
;  newgame.asm -- New Game's flow (CHUNK_NEWGAME).
;
;  The New Game list's presets, from presets/*.toml by tools/genpresets.py:
;  Vanilla, Improved Vanilla, and presets adapted from FFR's (menus.txt in
;  the project directory; randomization-notes.md, 12).  A preset is every
;  setting the settings screen and the randomization screen show, as
;  (row, value) pairs, which ngp_apply writes through the settings screen's
;  own tables -- so the presets hold no second copy of the option block's
;  layout, and a row the screen gains is a row the presets set (the base
;  preset, Improved Vanilla, must name it or the build stops).
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "fftext.inc"

.import lut_ValOff, lut_ValBit, lut_ValMask, opt_commit
.export ngp_apply
.export lut_NgpName, lut_NgpTitle, lut_NgpDescPtr, lut_NgpDataPtr   ; for tools/test_options.py

.segment "BANK_NEWGAME"

.include "presets.inc"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ngp_apply -- write New Game preset A over the option block, and seal it
;;
;;  The flag word and the new-game bytes cleared first, as the title's
;;  presets clear the new-game bytes, then every setting written as the
;;  settings screen writes it: a checkbox's bit set or cleared, a value row's
;;  value put in its byte's bits (lut_ValOff, lut_ValBit, lut_ValMask).  So
;;  the block is the preset's alone, but for the respond rate, which no
;;  preset sets (the player's own).  OPT_PRESET names the title's preset the
;;  preset is, or Custom.  Then opt_commit: the derived bytes and the
;;  checksum.  A preset is applied when it is chosen, and backing out leaves
;;  it applied (randomization-notes.md, 12).
;;
;;  In: A = the preset.  Emulation mode, by JSL; X and Y not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ngp_apply:
    PHB
    PHK
    PLB                         ; this chunk's low half decodes SRAM
    PHA
    TAX
    LDA lut_NgpTitle, X
    STA OPT_PRESET
    LDA #0
    LDX #OPT_FLAGBYTES - 1
  @flags:
    STA OPT_FLAGS, X
    DEX
    BPL @flags
    LDX #OPT_NG_SIZE - 1
  @ng:
    STA OPT_NG, X
    DEX
    BPL @ng
    PLA
    ASL A
    TAX
    LDA lut_NgpDataPtr, X
    STA tmp
    LDA lut_NgpDataPtr + 1, X
    STA tmp + 1
    LDY #0
  @pair:
    LDA (tmp), Y                ; the row: a flag bit + $80, or a scalar
    CMP #$FF
    BEQ @done
    INY
    TAX
    BMI @flag
    ;  A value row: its value into its bits.  tmp+2 the value shifted into
    ;  place, tmp+3 the mask, X the byte's offset in the option page.
    LDA f:OPTFAR + lut_ValMask, X
    STA tmp + 3
    LDA f:OPTFAR + lut_ValBit, X
    PHA
    LDA f:OPTFAR + lut_ValOff, X
    TAX
    LDA (tmp), Y
    STA tmp + 2
    PLA
    BEQ :++
:   ASL tmp + 2
    DEC A
    BNE :-
:   LDA tmp + 3
    EOR #$FF
    AND OPTBLOCK, X
    STA OPTBLOCK, X
    LDA tmp + 2
    AND tmp + 3
    ORA OPTBLOCK, X
    STA OPTBLOCK, X
    INY
    BRA @pair
  @flag:
    ;  A checkbox: bit X & $7F of the flag word, set when the value is.
    TXA
    AND #$07
    TAX
    LDA lut_NgpBit, X
    STA tmp + 3
    LDA (tmp), Y                ; the value...
    PHA
    DEY
    LDA (tmp), Y                ; ...and the bit again, for its byte
    INY
    AND #$7F
    LSR A
    LSR A
    LSR A
    TAX
    PLA
    BEQ :+
    LDA tmp + 3
    ORA OPT_FLAGS, X
    STA OPT_FLAGS, X
:   INY
    BRA @pair
  @done:
    JSL opt_commit + OPTFAR     ; the derived bytes, and the checksum
    PLB
    RTL

lut_NgpBit:
  .BYTE $01, $02, $04, $08, $10, $20, $40, $80
