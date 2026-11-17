; ---------------------------------------------------------------------------
;  dlggrave.inc -- the epitaphs on Elfland's gravestones (user, 2026-11-16:
;  "not a flag, an unconditional tribute").  rando_dlgtext asks grave_line
;  before drawing any line, whatever the options.  Included by world.asm,
;  for room.
; ---------------------------------------------------------------------------

DLG_GRAVE     = $DB             ; "Here lies Erdrick", the town tileset's tile $7F
DLG_TOMB      = $EE             ; "This is a tomb.", its tile $2F
MAP_ELFLAND   = $02             ; cur_map's (FFR's MapIndex)
GRAVE_DLGPTR  = (CHUNK0 + BANK_DIALOGUE) * $10000 + lut_DialoguePtrTbl

;;  grave_line -- the epitaph of the gravestone the party faces, if it does
;;
;;  FFR's TombstoneDialogue puts one of four epitaphs, for members of its
;;  community who have died, on Elfland's one named stone; here each has a
;;  stone of the four in a row (genepitaphs.py; mkrom's overlay_elfgrave
;;  adds the fourth), left to right in FFR's order.  The game
;;  gives the first "Here lies Erdrick" and the rest "This is a tomb.", which
;;  every tomb in Melmond, Crescent Lake and Onrac says too, so the line
;;  alone does not say which stone: the tile does, the one in front of the
;;  party, as GetSMTargetCoords finds it (the scroll + 7, a step the way it
;;  faces).  The epitaphs are longer than the game's lines and bank $0A has
;;  no room for them, so they are swapped in here.
;;
;;  In: text_ptr, the line about to be drawn.  Out: C set, text_ptr's low
;;  byte the epitaph's, in this chunk, and A its high byte, for
;;  rando_dlgtext's @worldline (dlgtext.inc); else C clear and text_ptr as it
;;  was.  X clobbered; Y kept.  Emulation mode, A8 I8, by JSL.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

grave_line:
    .a8
    .i8
    LDA cur_map
    CMP #MAP_ELFLAND
    BNE @no
    LDA f:GRAVE_DLGPTR + DLG_GRAVE * 2 + 1
    CMP text_ptr+1
    BNE @tomb
    LDA f:GRAVE_DLGPTR + DLG_GRAVE * 2
    CMP text_ptr
    BEQ @stone
  @tomb:
    LDA f:GRAVE_DLGPTR + DLG_TOMB * 2 + 1
    CMP text_ptr+1
    BNE @no
    LDA f:GRAVE_DLGPTR + DLG_TOMB * 2
    CMP text_ptr
    BNE @no
  @stone:                       ; the tile faced: the scroll + 7, a step on
    PHY
    LDX #7
    LDY #7
    LDA facing                  ; 1 right, 2 left, 4 down, else up
    LSR A
    BCC :+
    INX
    BRA @at
:   LSR A
    BCC :+
    DEX
    BRA @at
:   LSR A
    BCC :+
    INY
    BRA @at
:   DEY
  @at:
    TYA
    CLC
    ADC sm_scroll_y
    AND #$3F
    CMP #GRAVE_ROW
    BNE @none
    TXA
    CLC
    ADC sm_scroll_x
    AND #$3F
    SEC
    SBC #GRAVE_X0
    CMP #GRAVE_N
    BCS @none
    TAX                         ; which stone, from the left
    LDA f:WORLDFAR + lut_EpitaphLo, X
    STA text_ptr
    LDA f:WORLDFAR + lut_EpitaphHi, X
    PLY
    SEC
    RTL
  @none:
    PLY
  @no:
    CLC
    RTL

.include "epitaphs.inc"
.assert GRAVE_X0 + GRAVE_N <= 64 && GRAVE_ROW < 64, error, "the stones are off the map"
