; ---------------------------------------------------------------------------
;  nones.asm -- "None", a party slot left empty
;
;  Slots 2-4 on the party creation screen may be None as well as a class, for
;  solo and small-party runs: before it, a solo run meant making four and
;  killing three.  Unconditional, not a setting.
;
;  A None is FFR's model: class CLS_NONE, out-of-battle ailment 1 (dead) from
;  the start, and a page of zeros.  The game already does nearly everything a
;  None needs because it is dead -- it takes no turn, enemies do not target
;  it, their area spells skip it, the inn and tents do not raise it, experience is
;  shared among the living, and the party falls when its last living member
;  does.  What is left is what the class byte would index out of range, and
;  what could bring it back:
;
;    - party creation: the class cycle, its name, its sprite, its name input
;    - a class name of "None" in the menus           (fixed bank)
;    - no sprite in battle (DrawCharacter); menus already draw no dead one
;    - a spell on the whole party passes over it, where the dead and stoned
;      read "Ineffective"
;    - the walking sprite and its palette from the first who is not a None
;    - class change leaves it a None
;    - it holds gear from shops and trades, as a dead character can -- extra
;      bag space, as in FFR -- but cannot equip it or learn spells
;    - the clinic, LIFE and LIF2 from the menu, and Cast Life in Battle do
;      not raise it
;
;  Every routine here is reached by JSL from a game bank, in emulation mode,
;  with the caller's data bank -- which sees low RAM and SRAM -- and returns
;  with RTL.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.export none_nextclass, none_classtext, none_ptygenspr, none_ptygena
.export none_classchange, none_cursornone, none_magperm, none_isdead
.export none_obailment, none_drawchar, none_nametext, none_aoetarget

.import lutClassBatSprPalette, lut_MagicPermisPtr

.segment "BANK_OPT"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_nextclass -- the next choice on the party creation screen
;;
;;  Fighter through Black Mage, then None for every slot but the first, then
;;  round to Fighter.  The game went 0-5 and wrapped.
;;
;;  In: X = char_index ($00, $10, $20, $30).  Out: ptygen_class, X stepped.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_nextclass:
    LDA ptygen_class, X
    CLC
    ADC #1                      ; CLS_NONE + 1 is Fighter
    CMP #6
    BCC @store
    LDA #CLS_NONE
    CPX #$00
    BNE @store                  ; slots 2-4: None after Black Mage
    LDA #0                      ; the first: back to Fighter
  @store:
    STA ptygen_class, X
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_nametext -- "None", as a class name, in OPTNAMEBUF
;;
;;  There is no item name to borrow, $FC-$FF being the battle status words, so
;;  it is spelled out.  Seven glyphs and a terminator, like every class name:
;;  they are padded with spaces to seven, so that drawn over another one --
;;  the party creation screen redraws in place as the choice changes -- it
;;  leaves nothing of it behind.  "None" alone left "NoneAGE" after Bl.MAGE.
;;  OPTNAMEBUF is SRAM, which every bank sees, and is only ever a scratch copy.
;;
;;  Out: OPTNAMEBUF; A and X not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

NAMEBUFFAR = (CHUNK0 * $10000) + OPTNAMEBUF

lut_NoneName:  .BYTE $97, $B2, $B1, $A8, $FF, $FF, $FF, $00     ; "None   "

none_nametext:
    LDX #7
  @copy:
    LDA f:OPTFAR + lut_NoneName, X
    STA f:NAMEBUFFAR, X
    DEX
    BPL @copy
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_classtext -- the party creation screen's class name
;;
;;  The game built "$02, $F0 + class" at format_buf-2 -- the class names sit
;;  with the item names -- and pointed text_ptr at it.  The same, except for a
;;  None, whose name none_nametext puts in OPTNAMEBUF.
;;
;;  In: X = char_index.  Out: format_buf or OPTNAMEBUF, text_ptr; X kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_classtext:
    LDA ptygen_class, X
    CMP #CLS_NONE
    BEQ @none
    CLC
    ADC #$F0
    STA z:format_buf-1
    LDA #$02                    ; draw an item name
    STA z:format_buf-2
    LDA #<(format_buf-2)
    STA z:text_ptr
    LDA #>(format_buf-2)
    STA z:text_ptr+1
    RTL
  @none:
    PHX
    JSL none_nametext + OPTFAR  ; a label's bank is not known: this chunk's
    PLX
    LDA #<OPTNAMEBUF
    STA z:text_ptr
    LDA #>OPTNAMEBUF
    STA z:text_ptr+1
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_ptygenspr -- PtyGen_DrawChars' setup for one character's sprite
;;
;;  Where it goes, its class's palette and its tiles, as the game set them up
;;  for DrawSimple2x3Sprite -- or carry set for a None, which has no sprite.
;;
;;  In: X = char_index.  Out: spr_x, spr_y, tmp (tiles), tmp+1 (palette) and
;;  carry clear; or carry set.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_ptygenspr:
    LDA ptygen_spr_x, X
    STA z:spr_x
    LDA ptygen_spr_y, X
    STA z:spr_y
    LDA ptygen_class, X
    CMP #CLS_NONE
    BEQ @none
    PHX
    TAX
    LDA lutClassBatSprPalette, X    ; the fixed bank, in the caller's chunk too
    STA z:tmp+1
    TXA                         ; $20 tiles a class
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA z:tmp
    PLX
    CLC
    RTL
  @none:
    SEC
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_ptygena -- A on the party creation screen: a name, or not
;;
;;  A None has no name to enter, so A confirms it as it stands, with its name
;;  blanked in case the slot had one before it became a None.
;;
;;  In: char_index.  Out: carry set for a None (name blanked); clear for a
;;  class, whose name input follows.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_ptygena:
    LDX z:char_index
    LDA ptygen_class, X
    CMP #CLS_NONE
    BNE @class
    LDA #$FF                    ; spaces
    STA ptygen_name, X
    STA ptygen_name+1, X
    STA ptygen_name+2, X
    STA ptygen_name+3, X
    SEC
    RTL
  @class:
    CLC
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_classchange -- DoClassChange's promotion, which a None sits out
;;
;;  The game added 6 to all four class bytes.  A None plus 6 is a Black Mage.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_classchange:
    LDX #$00
  @each:
    LDA ch_class, X
    CMP #CLS_NONE
    BEQ @next
    CLC
    ADC #6
    STA ch_class, X
  @next:
    TXA
    CLC
    ADC #$40
    TAX
    BNE @each
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_cursornone -- is the equip menu's character a None?
;;
;;  For IsEquipLegal_N, before IsEquipLegal: a None holds gear but wears none,
;;  whatever the item.  IsEquipLegal finds the character the same way.
;;
;;  In: cursor.  Out: carry set for a None.  A, X and Y not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_cursornone:
    LDA z:cursor
    ASL A
    ASL A
    ASL A
    ASL A
    AND #$C0
    TAX
    LDA ch_class, X
    CMP #CLS_NONE               ; C set exactly when it is CLS_NONE, the top
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_magperm -- MagicShop_AssertLearn's permissions table
;;
;;  (tmp) at the class's table of eight bytes, a bit set for each spell it
;;  may not learn.  A None's would be read from beyond lut_MagicPermisPtr, so
;;  it gets eight $FF in OPTNAMEBUF -- nothing learnable -- and the shop says
;;  so as it would for any class.
;;
;;  In: X = class * 2.  Out: tmp, tmp+1; X kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_magperm:
    CPX #(CLS_NONE * 2) & $FF
    BEQ @none
    LDA lut_MagicPermisPtr, X   ; bank $0E, the caller's
    STA z:tmp
    LDA lut_MagicPermisPtr+1, X
    STA z:tmp+1
    RTL
  @none:
    LDA #$FF
    LDY #7
  @fill:
    STA OPTNAMEBUF, Y           ; SRAM, which the caller's bank sees
    DEY
    BPL @fill
    LDA #<OPTNAMEBUF
    STA z:tmp
    LDA #>OPTNAMEBUF
    STA z:tmp+1
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_isdead -- the clinic's "is this one dead?"
;;
;;  LDA ch_ailments, X / CMP #$01, which it replaces -- with a None never
;;  dead, so the clinic does not offer to raise it.
;;
;;  In: X = the character's $40.  Out: A, and flags as that CMP left them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_isdead:
    LDA ch_class, X
    CMP #CLS_NONE
    BEQ @none
    LDA ch_ailments, X
    CMP #$01
    RTL
  @none:
    LDA #$00
    CMP #$01
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_obailment -- CureOBAilment's "has it this ailment?"
;;
;;  LDA ch_ailments, X / CMP tmp, which it replaces -- with a None having no
;;  ailment to cure, so LIFE and LIF2 from the menu cannot raise it.
;;
;;  In: X = the character's $40, tmp = the ailment.  Out: A and flags.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_obailment:
    LDA ch_class, X
    CMP #CLS_NONE
    BEQ @none
    LDA ch_ailments, X
    CMP z:tmp
    RTL
  @none:
    LDA #$00
    CMP z:tmp
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_drawchar -- the head of DrawCharacter, in battle
;;
;;  Its attribute, and A and X the character, as the game left them -- or
;;  carry set for a None, which DrawCharacter then does not draw.  A dead
;;  character lies on the ground; a None is not there at all.
;;
;;  In: A = the character, 0-3.  Out: carry clear, A = X = Y = the
;;  character, btl8x8spr_a set; or carry set.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

none_drawchar:
    PHA
    ASL A                       ; $40 a character
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    LDA ch_class, X
    CMP #CLS_NONE
    BEQ @none
    PLA
    TAY
    LDA btl_charattrib, Y
    STA btl8x8spr_a
    TYA
    TAX
    CLC
    RTL
  @none:
    PLA
    SEC
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  none_aoetarget -- the head of the loop casting a spell on the whole party
;;
;;  The defender set, as the loop always set it -- and carry set for a None,
;;  which Battle_PlMag_TargetAllPlayers then passes over.  That loop shows
;;  "Ineffective" for a member dead or stoned, which a None is too, so INV2 or
;;  HEAL read "Ineffective" once for every None (playtest, 2026-10-09).
;;  FFR's patch skips the None's box and message but still waits out the
;;  respond-rate delay, a beat with nothing new on screen; this skips that
;;  too, as the enemies' loop over the party passes the dead.
;;
;;  In: BTL_PARTYLOOP = the slot, 0-3.  Out: btl_defender = $80 + the slot;
;;  carry set for a None.  X clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

BTL_PARTYLOOP = $6BCE               ; the disassembly's bare loop counter

.assert CLS_NONE = $FF, error, "none_aoetarget's CMP sets carry for $FF alone"

none_aoetarget:
    LDA BTL_PARTYLOOP
    ORA #$80                        ; a player
    STA btl_defender
    LDA BTL_PARTYLOOP
    LSR A
    ROR A
    ROR A                           ; the slot times $40, its page
    TAX
    LDA ch_class, X
    CMP #CLS_NONE                   ; carry set for a None, and only a None
    RTL
