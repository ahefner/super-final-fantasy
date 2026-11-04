; ---------------------------------------------------------------------------
;  dlgtext.inc -- the reward NPCs' giving lines, once placement is in, and
;  the game's lines that say where a key item or a dungeon is
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
;  builds the replacement in OPTDESC (low WRAM, which the drawer reads from any
;  chunk bank) and points text_ptr at it.  The flag is spent there, so nothing
;  after it is touched.  $02 in a line is the item's name; any other code
;  below $1A breaks the line.
;
;  With nothing armed, the same hook swaps a hint: a line of the game's that
;  says where a key item or a dungeon is, wrong once the key items or the
;  entrances are shuffled, for one that isn't.  Those lines are
;  dlghint.inc's, in the world chunk, for room.
; ---------------------------------------------------------------------------

DLG_ITEM = $02                  ; the name of dlg_itemid; DLG_NL, fftext.inc
DLG_GARLAND   = $04             ; Garland's line, and the kidnapped princess's
DLG_PRINCESS1 = $05             ;   (lut_MapObjTalkData)

;  The game's dialogue pointers, NES bank $0A's first $200 bytes.
DLGPTRFAR = (CHUNK0 + BANK_DIALOGUE) * $10000 + lut_DialoguePtrTbl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_dlgtext -- a reward NPC's line, if one has just given
;;
;;  In: text_ptr, the string about to be drawn.  Out: text_ptr, OPTDESC if
;;  RW_DLGNPC was set, which it clears.  A, X clobbered; Y kept.  Emulation
;;  mode.  RW_DLGNPC from DLG_ORB0 on is the Black Orb's (opt_orbgoal), its
;;  line rando_dlgorb's.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_dlgtext:
    .a8
    .i8
    LDA f:RW_DLGNPC
    BEQ @sara
    CMP #DLG_ORB0
    BCC :+
    JMP rando_dlgorb
:   DEC A
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
    ;  the line's chunk, (text_ptr) reads the line, and OPTDESC is still
    ;  low WRAM, which every bank $80-$BF mirrors at $0000-$1FFF.
    PHB
    PHK
    PLB
  @copyin:                      ; DBR the line's chunk, the caller's pushed
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

    ;  Nothing armed.  Rebellious Princess, with her moved (user,
    ;  2026-11-02): the kidnapped princess's line, dialogue $05, is her
    ;  spot's, and Garland's, $04, protests (dlgsara.inc, the world chunk's).
  @sara:
    JSL fun_dwarfline + FUNFAR  ; FUN%'s Exploding Dwarf: his last words?
    BCS @worldline
    JSR sara_moved              ; X = her spot
    BCC @hint
    LDA f:DLGPTRFAR + DLG_PRINCESS1 * 2
    CMP text_ptr
    BNE @garland
    LDA f:DLGPTRFAR + DLG_PRINCESS1 * 2 + 1
    CMP text_ptr+1
    BNE @garland
    LDA f:WORLDFAR + lut_SaraLineLo, X
    STA text_ptr
    LDA f:WORLDFAR + lut_SaraLineHi, X
    BRA @worldline
  @garland:
    LDA f:DLGPTRFAR + DLG_GARLAND * 2
    CMP text_ptr
    BNE @hint
    LDA f:DLGPTRFAR + DLG_GARLAND * 2 + 1
    CMP text_ptr+1
    BNE @hint
    LDA #<lut_GarlandLine
    STA text_ptr
    LDA #>lut_GarlandLine
  @worldline:
    STA text_ptr+1
    PHB
    LDA #^WORLDFAR
    PHA
    PLB
    JMP @copyin

    ;  Nothing armed.  With the key items shuffled, a line that says where
    ;  one is -- the CROWN in the Cave of Marsh, the KEY with the Elf
    ;  Prince -- is wrong, so it gives way to one that isn't (user,
    ;  2026-10-28: "I'd instead neutralize the dialog"); under Key items
    ;  Vanilla the game's own.  So, with the entrances shuffled, does one
    ;  that says where a dungeon is, and with the floors, one that says the
    ;  way through it.  The string is known by its pointer in the game's
    ;  table, the dialogue number being gone by here.
  @hint:
    LDA f:RANDO_SAVEFAR + (RANDO_KEYITEMS - RANDO_SAVE)
    CMP #KEYITEMS_STANDARD
    BEQ :+
    CMP #KEYITEMS_WIDE
    BNE @out
:   LDX #DLG_NHINT - 1
  @look:
    PHX
    LDA f:WORLDFAR + lut_DlgHintId, X
    ASL A
    TAX
    BCS @high                   ; $80 on: the table's second page
    LDA f:DLGPTRFAR, X
    CMP text_ptr
    BNE @next
    LDA f:DLGPTRFAR + 1, X
    BRA @page
  @high:
    LDA f:DLGPTRFAR + $100, X
    CMP text_ptr
    BNE @next
    LDA f:DLGPTRFAR + $101, X
  @page:
    CMP text_ptr+1
    BEQ @hit
  @next:
    PLX
    DEX
    BPL @look
    RTL
  @hit:
    PLX
    LDA f:RANDO_SAVEFAR + (RANDO_ENTRANCES - RANDO_SAVE)
    CMP f:WORLDFAR + lut_DlgHintMap, X
    BCS :+
    RTL                         ; its Map shuffle isn't on: the game's line
:   LDA f:WORLDFAR + lut_DlgHintLo, X
    STA text_ptr
    LDA f:WORLDFAR + lut_DlgHintHi, X
    STA text_ptr+1
    PHB
    LDA #^WORLDFAR
    PHA
    PLB
    JMP @copyin
.assert ^WORLDFAR >= $A0 && ^WORLDFAR <= $BF, error, "OPTDESC isn't low WRAM from the world chunk"

;;  The Black Orb giving way with fewer than four lit (opt_orbgoal): the
;;  game's line, dialogue $21, its first line by the orbs the party carries
;;  (user, 2026-10-27) -- plural, singular, or none and the party's hands on
;;  it -- and the rest as the game has it, copied from the line being drawn
;;  (DTE: written out it would not fit OPTDESC).  The rest goes in first,
;;  from the caller's bank, after where the first line will end; then the
;;  first line from this chunk.  A line with no break is drawn as it is.
;;  In: A = RW_DLGNPC, DLG_ORB0 or more.  Out as rando_dlgtext.
rando_dlgorb:
    SEC
    SBC #DLG_ORB0
    TAX                         ; 0 none lit, 1 one, 2 more
    LDA #$00
    STA f:RW_DLGNPC
    PHY
    PHX
    LDA f:RANDOFAR + lut_DlgOrbLen, X
    TAX                         ; where the rest goes
    LDY #$00
  @find:                        ; the game's first line break
    LDA (text_ptr), Y
    BEQ @asis
    CMP #$1A
    BCC @rest
    INY
    BNE @find
  @asis:
    PLX
    PLY
    RTL
  @rest:                        ; from the break, terminator and all
    LDA (text_ptr), Y
    STA OPTDESC, X
    BEQ @first
    INX
    INY
    BNE @rest
  @first:
    PLX
    PHB
    PHK
    PLB
    LDA lut_DlgOrbLo, X
    STA text_ptr
    LDA lut_DlgOrbHi, X
    STA text_ptr+1
    LDA lut_DlgOrbLen, X
    TAY
  @copy:                        ; ...and ours before it
    DEY
    LDA (text_ptr), Y
    STA OPTDESC, Y
    TYA
    BNE @copy
    PLB
    PLY
    LDA #<OPTDESC
    STA text_ptr
    LDA #>OPTDESC
    STA text_ptr+1
    RTL

lut_DlgOrb0:  FFTEXT "You lay your hands upon"     ; none lit (the user's)
lut_DlgOrb1:  FFTEXT "The ORB now covers"          ; one
lut_DlgOrbN:  FFTEXT "The ORBS now cover"          ; two or three
lut_DlgOrbEnd:
lut_DlgOrbLo:  .BYTE <lut_DlgOrb0, <lut_DlgOrb1, <lut_DlgOrbN
lut_DlgOrbHi:  .BYTE >lut_DlgOrb0, >lut_DlgOrb1, >lut_DlgOrbN
lut_DlgOrbLen: .BYTE lut_DlgOrb1 - lut_DlgOrb0, lut_DlgOrbN - lut_DlgOrb1, lut_DlgOrbEnd - lut_DlgOrbN
;  The game's rest of the line is 55 bytes, terminator and all
;  (test_goal checks it, and the whole line, against OPTDESC).
.assert lut_DlgOrb1 - lut_DlgOrb0 + 55 <= OPTDESC_MAX, error, "the Black Orb's line overflows OPTDESC"
.assert DLG_ORB0 = 14 && DLG_ORB0 > 13, error, "the Black Orb's entries follow the thirteen NPCs'"

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
lut_Dlg2:   ; Bikke (user, 2026-10-27)
  FFTEXT "Arrrr, you got me."
  .BYTE DLG_NL
  FFTEXT "Take this and go."
  DLGTEXT_END
lut_Dlg3:   ; the Elf Prince
  FFTEXT "Are you the LIGHT"
  .BYTE DLG_NL
  FFTEXT "WARRIORS? As legend"
  .BYTE DLG_NL
  FFTEXT "says, I give you this."
  DLGTEXT_END
lut_Dlg4:   ; Astos, who gives and then fights (user, 2026-10-27)
  ;  The item ends its line: a name is drawn with its padding (TNT is
  ;  "TNT    "), and "I have the TNT    ." showed it.
  FFTEXT "HA, HA, HA! I am Astos!"
  .BYTE DLG_NL
  FFTEXT "I possess the "
  .BYTE DLG_ITEM
  .BYTE DLG_NL
  FFTEXT "Soon I'll have the CROWN!"
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
