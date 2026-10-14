; ---------------------------------------------------------------------------
;  dlgtext.inc -- the reward NPCs' giving lines, once placement is in
;
;  Included by rando.asm.  A reward NPC's vanilla giving line names its
;  vanilla reward ("Take my SHIP."), which is wrong once placement moves it.
;  FFR replaces those lines (Dialogues.cs, UpdateNPCDialogues), each ending
;  "Received" and the item; these are its lines, cut to fit OPTDESC, the
;  buffer they are built in, where FFR's run to ninety bytes.
;
;  rando_talk sets RW_DLGNPC when an NPC gives under placement, and names
;  what it gave in dlg_itemid; the next string DrawDialogueString draws is
;  that NPC's line, and rando_dlgtext, at DrawDialogueString_PtrLoaded,
;  builds the replacement in OPTDESC (SRAM, which the drawer reads from any
;  bank) and points text_ptr at it.  The flag is spent there, so nothing
;  after it is touched.  $02 in a line is the item's name; any other code
;  below $1A breaks the line.
; ---------------------------------------------------------------------------

DLG_NL   = $01                  ; a line break
DLG_ITEM = $02                  ; the name of dlg_itemid

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_dlgtext -- a reward NPC's line, if one has just given
;;
;;  In: text_ptr, the string about to be drawn.  Out: text_ptr, OPTDESC if
;;  RW_DLGNPC was set, which it clears.  A, X clobbered; Y kept.  Emulation
;;  mode.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_dlgtext:
    .a8
    .i8
    LDA f:RW_DLGNPC
    BEQ @out
    DEC A
    TAX                         ; the NPC's entry
    LDA #$00
    STA f:RW_DLGNPC
    ;  The King's and the Sage's lines speak of the event they waited for,
    ;  so with its Early flag on each has another, as in FFR.  Sarda's
    ;  doesn't (lut_DlgEarly has no line for him), so Early Sarda is not one.
    LDA f:RANDOFAR + lut_DlgEarly, X
    BEQ @plain
    AND f:RANDO_SAVEFAR + (RANDO_EARLY - RANDO_SAVE)
    BEQ @plain
    LDA f:RANDOFAR + lut_DlgEarlyLo, X
    STA text_ptr
    LDA f:RANDOFAR + lut_DlgEarlyHi, X
    BRA @have
  @plain:
    LDA f:RANDOFAR + lut_DlgLo, X
    STA text_ptr
    LDA f:RANDOFAR + lut_DlgHi, X
  @have:
    STA text_ptr+1
    ;  Copy it, terminator and all, from this chunk into OPTDESC.  With DBR
    ;  this chunk, (text_ptr) reads the line, and OPTDESC is still SRAM: a
    ;  HiROM cart decodes $6000-$7FFF in every bank $A0-$BF.
    PHB
    PHK
    PLB
    PHY
    LDY #$00
  @copy:
    LDA (text_ptr), Y
    STA OPTDESC, Y
    BEQ @done
    INY
    BNE @copy
  @done:
    PLY
    PLB
    LDA #<OPTDESC
    STA text_ptr
    LDA #>OPTDESC
    STA text_ptr+1
  @out:
    RTL

.macro DLGTEXT_END
  .BYTE DLG_NL, DLG_NL
  FFTEXT "Received "
  .BYTE DLG_ITEM, $00
.endmacro

lut_Dlg0:   ; the King
  FFTEXT "Thank you for saving the"
  .BYTE DLG_NL
  FFTEXT "Princess. Please take"
  .BYTE DLG_NL
  FFTEXT "this."
  DLGTEXT_END
lut_DlgEarly0:   ; the King, Early King
  FFTEXT "To aid you on your"
  .BYTE DLG_NL
  FFTEXT "quest, please take this."
  DLGTEXT_END
lut_Dlg1:   ; the Princess
  FFTEXT "An heirloom of the"
  .BYTE DLG_NL
  FFTEXT "Queens of Coneria."
  .BYTE DLG_NL
  FFTEXT "Please take it."
  DLGTEXT_END
lut_Dlg2:   ; Bikke
  FFTEXT "Okay, you got me."
  .BYTE DLG_NL
  FFTEXT "Take this."
  DLGTEXT_END
lut_Dlg3:   ; the Elf Prince
  FFTEXT "Are you the LIGHT"
  .BYTE DLG_NL
  FFTEXT "WARRIORS? As legend"
  .BYTE DLG_NL
  FFTEXT "says, I give you this."
  DLGTEXT_END
lut_Dlg4:   ; Astos, who gives and then fights
  FFTEXT "HA, HA, HA! I am Astos!"
  .BYTE DLG_NL
  FFTEXT "I have the "
  .BYTE DLG_ITEM
  FFTEXT "."
  .BYTE DLG_NL
  FFTEXT "Now give me that"
  .BYTE DLG_NL
  FFTEXT "CROWN!!!"
  .BYTE $00
lut_Dlg5:   ; Matoya
  FFTEXT "My CRYSTAL! I can see!"
  .BYTE DLG_NL
  FFTEXT "Take this in trade."
  DLGTEXT_END
lut_Dlg6:   ; Nerrick
  FFTEXT "Yes, yes indeed, this"
  .BYTE DLG_NL
  FFTEXT "TNT is just what I"
  .BYTE DLG_NL
  FFTEXT "need. Take this!"
  DLGTEXT_END
lut_Dlg7:   ; the Smith
  FFTEXT "ADAMANT!! Let me forge"
  .BYTE DLG_NL
  FFTEXT "this for you. My best"
  .BYTE DLG_NL
  FFTEXT "work yet!"
  DLGTEXT_END
lut_Dlg8:   ; Sarda
  FFTEXT "Take this. It will help"
  .BYTE DLG_NL
  FFTEXT "you fight the source of"
  .BYTE DLG_NL
  FFTEXT "the earth's rot."
  DLGTEXT_END
lut_Dlg9:   ; the Canoe Sage
  FFTEXT "Great job vanquishing"
  .BYTE DLG_NL
  FFTEXT "the Earth FIEND. With"
  .BYTE DLG_NL
  FFTEXT "this, defeat the rest!"
  DLGTEXT_END
lut_DlgEarly9:   ; the Canoe Sage, Early Sage
  FFTEXT "The FIENDS are waking."
  .BYTE DLG_NL
  FFTEXT "Take this and go defeat"
  .BYTE DLG_NL
  FFTEXT "them!"
  DLGTEXT_END
lut_Dlg10:  ; CubeBot
  FFTEXT "Take this."
  DLGTEXT_END
lut_Dlg11:  ; the Fairy
  FFTEXT "That pirate trapped me"
  .BYTE DLG_NL
  FFTEXT "in the BOTTLE. Take"
  .BYTE DLG_NL
  FFTEXT "this from the spring."
  DLGTEXT_END
lut_Dlg12:  ; Lefein's Chime
  FFTEXT "With this, you can"
  .BYTE DLG_NL
  FFTEXT "avenge the SKY WARRIORS."
  DLGTEXT_END
lut_DlgEnd:

;  Each fits OPTDESC, terminator included.
.assert lut_DlgEarly0 - lut_Dlg0 <= OPTDESC_MAX, error, "the King's line is too long"
.assert lut_Dlg1 - lut_DlgEarly0 <= OPTDESC_MAX, error, "the King's Early line is too long"
.assert lut_Dlg2 - lut_Dlg1 <= OPTDESC_MAX, error, "the Princess's line is too long"
.assert lut_Dlg3 - lut_Dlg2 <= OPTDESC_MAX, error, "Bikke's line is too long"
.assert lut_Dlg4 - lut_Dlg3 <= OPTDESC_MAX, error, "the Elf Prince's line is too long"
.assert lut_Dlg5 - lut_Dlg4 <= OPTDESC_MAX, error, "Astos's line is too long"
.assert lut_Dlg6 - lut_Dlg5 <= OPTDESC_MAX, error, "Matoya's line is too long"
.assert lut_Dlg7 - lut_Dlg6 <= OPTDESC_MAX, error, "Nerrick's line is too long"
.assert lut_Dlg8 - lut_Dlg7 <= OPTDESC_MAX, error, "the Smith's line is too long"
.assert lut_Dlg9 - lut_Dlg8 <= OPTDESC_MAX, error, "Sarda's line is too long"
.assert lut_DlgEarly9 - lut_Dlg9 <= OPTDESC_MAX, error, "the Sage's line is too long"
.assert lut_Dlg10 - lut_DlgEarly9 <= OPTDESC_MAX, error, "the Sage's Early line is too long"
.assert lut_Dlg11 - lut_Dlg10 <= OPTDESC_MAX, error, "CubeBot's line is too long"
.assert lut_Dlg12 - lut_Dlg11 <= OPTDESC_MAX, error, "the Fairy's line is too long"
.assert lut_DlgEnd - lut_Dlg12 <= OPTDESC_MAX, error, "the Chime's line is too long"

lut_DlgLo:
  .BYTE <lut_Dlg0, <lut_Dlg1, <lut_Dlg2, <lut_Dlg3, <lut_Dlg4, <lut_Dlg5, <lut_Dlg6
  .BYTE <lut_Dlg7, <lut_Dlg8, <lut_Dlg9, <lut_Dlg10, <lut_Dlg11, <lut_Dlg12
lut_DlgHi:
  .BYTE >lut_Dlg0, >lut_Dlg1, >lut_Dlg2, >lut_Dlg3, >lut_Dlg4, >lut_Dlg5, >lut_Dlg6
  .BYTE >lut_Dlg7, >lut_Dlg8, >lut_Dlg9, >lut_Dlg10, >lut_Dlg11, >lut_Dlg12
;  Which Early flag gives an entry its other line, and the line.
lut_DlgEarly:
  .BYTE EARLY_KING, 0, 0, 0, 0, 0, 0, 0, 0, EARLY_SAGE, 0, 0, 0
lut_DlgEarlyLo:
  .BYTE <lut_DlgEarly0, 0, 0, 0, 0, 0, 0, 0, 0, <lut_DlgEarly9, 0, 0, 0
lut_DlgEarlyHi:
  .BYTE >lut_DlgEarly0, 0, 0, 0, 0, 0, 0, 0, 0, >lut_DlgEarly9, 0, 0, 0
