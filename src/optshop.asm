;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  optshop.asm -- Shop Information.
;;
;;  Press Select over an item in a weapon or armour shop and a box opens with
;;  what the thing actually does.  Select is free: the shop loop already
;;  zeroes it on every exit, with the comment "but why?  select isn't used in
;;  shops?".
;;
;;  FFR builds these descriptions in C# at generation time and bakes 144
;;  strings plus a shared word table into the ROM.  It has no choice -- its
;;  weapon and spell tables are randomised, and the text has to agree with
;;  whatever it rolled.  Here the tables are vanilla but the FLAGS are not,
;;  and baked text would be wrong the moment one was toggled.  Double Weapon
;;  Crit Rate is the plainest case: FFR implements it by rewriting the
;;  weapon's crit byte in the ROM, which is exactly what a runtime flag
;;  cannot do.
;;
;;  So the text is generated here, from the same numbers the game reads.  THE
;;  RULE THAT KEEPS IT HONEST: nothing below may read a weapon or armour field
;;  directly.  Go through the accessors at the top -- they are what a flag
;;  hooks, and they are meant to be shared with the battle code, so the box
;;  cannot drift away from what the game actually does.
;;
;;  Everything lives in this chunk rather than the fixed bank, which has
;;  fourteen bytes left.  That works because the box needs nothing from bank
;;  $0E: DrawBox, EraseBox, DrawComplexString, ClearOAM, CallMusicPlay and
;;  UpdateJoy are all in the fixed bank, which is stamped into every chunk,
;;  so a plain JSR reaches them from here.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nesio.inc"
.include "fftext.inc"

;  Call a routine in bank $0E.  OptCallFar itself passes A, X and Y through,
;  but setting the address needs A -- so a routine that takes a parameter in
;  A has to be called with CALL0EA, which loads it afterwards.
.macro SET0E addr
    LDA #<addr
    STA OPTCALLV
    LDA #>addr
    STA OPTCALLV+1
.endmacro

.macro CALL0E addr
    SET0E addr
    JSL OptCallFar + BANK0EFAR
.endmacro

.macro CALL0EA addr, val
    SET0E addr
    LDA #val
    JSL OptCallFar + BANK0EFAR
.endmacro

.export opt_shopframe, opt_pose, opt_weaponstats
.export opt_equipframe, opt_magicframe, opt_chestinfo
.export opt_equipitem, opt_magicspell, opt_shopinfo_body
.export opt_spellbyte, opt_num16
;  Reached by tools/test_options.py.
.export opt_num, opt_word, opt_bitscan, opt_permissions
.export opt_descgear, opt_weapcrit, opt_gearlive
.export opt_setposes, opt_canuseit

;  The fixed bank is stamped into every chunk, so these are a plain JSR away.
.import DrawBox, EraseBox, DrawComplexString
.import DrawDialogueString_PtrLoaded
.import ClearOAM, CallMusicPlay, UpdateJoy, WaitForVBlank_L
.import OptShopFrameFar, OptCallFar
.import EquipMenuFrame, DrawEquipMenu, TurnMenuScreenOn
.import TurnMenuScreenOn_ClearOAM, MenuFrame, ClearNT
.import DrawMagicMenuMainBox, DrawMainItemBox, DrawCharMenuString
.import DrawEquipMenuCurs, DrawMagicMenuCursor
.import DrawEquipMenuStrings
.export lut_Words, lut_WordOfs, lut_ClassHi, lut_ClassLo

;  Read with long addressing, so these banks are never swapped in and nothing
;  in them moves; all that is needed is the address.
.import lut_WeaponData, lut_ArmorData
.import lut_WeaponPermissions, lut_ArmorPermissions
.import lut_ClassEquipBit, lut_MagicPermisPtr
.import lut_MagicData
.import opt_spellbuffed, opt_spelltarget

.segment "BANK_OPT"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The words
;;
;;  Twelve columns is the whole budget, so the element names have to be the
;;  short forms; "Resist Lightning" does not fit and "Resist Lit." does.
;;  These are FFR's own abbreviations, for the sake of players who know them
;;  from there.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

WORD_ATK      = 0
WORD_HIT      = 1
WORD_CRT      = 2
WORD_DEF      = 3
WORD_EVA      = 4
WORD_HURT     = 5
WORD_CAST     = 6
WORD_RESIST   = 7
WORD_ELEMENT  = 8
WORD_ELEMENTS = 40      ; after the twelve classes, which end at 39
WORD_AND      = 41
WORD_TGT0     = 42      ; five, by the bit set in the target byte
WORD_RTN0     = 47      ; nineteen, indexed by the routine byte itself
WORD_STAT0    = 66      ; eight, by the bit set in a status mask
WORD_DMG      = 74
WORD_RES2     = 75
WORD_WEAK     = 76
WORD_PTS      = 77
WORD_HP       = 78
WORD_ATK2     = 79
WORD_HIT2     = 80
WORD_OOB0     = 81      ; five, for the spells with no battle routine
WORD_ALL      = 9
WORD_ALLCLASS = 10
WORD_MORE     = 11
WORD_ELEM0    = 12      ; eight, in bit order
WORD_TYPE0    = 20      ; eight, in bit order
WORD_CLASS0   = 28      ; twelve, base and promoted interleaved

lut_Words:
wATK:     FFWORD "ATK +"
wHIT:     FFWORD "HIT +"
wCRT:     FFWORD "CRT +"
wDEF:     FFWORD "DEF +"
wEVA:     FFWORD "EVA -"
wHURT:    FFWORD "Hurt "
wCAST:    FFWORD "Cast "
wRESIST:  FFWORD "Resist"
wELEMENT: FFWORD " Element"
wALL:     FFWORD "All"
wALLCLS:  FFWORD "All classes"
wMORE:    FFWORD " more"
;  The eight elements, in the order of the bits in an element byte.
wE0:      FFWORD "Stat"
wE1:      FFWORD "Pois"
wE2:      FFWORD "Time"
wE3:      FFWORD "Deat"
wE4:      FFWORD "Fire"
wE5:      FFWORD "Ice"
wE6:      FFWORD "Lit."
wE7:      FFWORD "Eart"
;  The eight enemy categories a weapon can be good against.
wT0:      FFWORD "Magical"
wT1:      FFWORD "Dragon"
wT2:      FFWORD "Giant"
wT3:      FFWORD "Undead"
wT4:      FFWORD "Were"
wT5:      FFWORD "Water"
wT6:      FFWORD "Mage"
wT7:      FFWORD "Regen"
;  The twelve classes, each base class followed by what it promotes into.
wC0:      FFWORD "Fi"
wC1:      FFWORD "Kn"
wC2:      FFWORD "Th"
wC3:      FFWORD "Ni"
wC4:      FFWORD "Bb"
wC5:      FFWORD "Ma"
wC6:      FFWORD "Rm"
wC7:      FFWORD "Rw"
wC8:      FFWORD "Wm"
wC9:      FFWORD "Ww"
wC10:     FFWORD "Bm"
wC11:     FFWORD "Bw"
wELEMS:   FFWORD " Elements"
wAND:     FFWORD " and "
;  Who a spell reaches, in the order of the bits in its target byte.
wG0:      FFWORD "All Enemies"
wG1:      FFWORD "Single Enemy"
wG2:      FFWORD "Caster"
wG3:      FFWORD "All Allies"
wG4:      FFWORD "One Ally"
;  What a spell does, indexed by the routine byte straight out of the record.
;  Routine 0 has no battle routine at all and is named from lut_OOBSpell
;  instead; 11 is unused.
wR00:     FFWORD ""
wR01:     FFWORD "Damage"
wR02:     FFWORD "Dmg Undead"
wR03:     FFWORD "Inflict Stat"
wR04:     FFWORD "Halve Hits"
wR05:     FFWORD "Reduce Moral"
wR06:     FFWORD "Recover HP"
wR07:     FFWORD "Recover HP"
wR08:     FFWORD "Heal Stat"
wR09:     FFWORD "Raise Def."
wR10:     FFWORD "Resist Elem."
wR11:     FFWORD ""
wR12:     FFWORD "Double Hits"
wR13:     FFWORD "Raise Attack"
wR14:     FFWORD "Reduce Evade"
wR15:     FFWORD "Full Recover"
wR16:     FFWORD "Raise Evade"
wR17:     FFWORD "Void Resist."
wR18:     FFWORD "PW Status"
;  The eight ailments, in the order of the bits in a status mask.
wS0:      FFWORD "Dead"
wS1:      FFWORD "Petrified"
wS2:      FFWORD "Poisoned"
wS3:      FFWORD "Blind"
wS4:      FFWORD "Paralyzed"
wS5:      FFWORD "Asleep"
wS6:      FFWORD "Silenced"
wS7:      FFWORD "Confused"
wDMG:     FFWORD " DMG"
wRES2:    FFWORD "Resist  "
wWEAK:    FFWORD "Weak    "
wPTS:     FFWORD " pts"
wHP:      FFWORD " HP"
wATK2:    FFWORD " ATK"
wHIT2:    FFWORD " HIT"
;  The five spells with no battle routine, named by what they do in a menu.
wO0:      FFWORD "Revive"
wO1:      FFWORD "Full Revive"
wO2:      FFWORD "Up one floor"
wO3:      FFWORD "Heal Stoned"
wO4:      FFWORD "Exit dungeon"
lut_WordsEnd:

;  Offsets, so one index reaches any word.
lut_WordOfs:
  .word wATK - lut_Words, wHIT - lut_Words, wCRT - lut_Words
  .word wDEF - lut_Words, wEVA - lut_Words, wHURT - lut_Words
  .word wCAST - lut_Words, wRESIST - lut_Words, wELEMENT - lut_Words
  .word wALL - lut_Words, wALLCLS - lut_Words, wMORE - lut_Words
  .word wE0 - lut_Words, wE1 - lut_Words, wE2 - lut_Words, wE3 - lut_Words
  .word wE4 - lut_Words, wE5 - lut_Words, wE6 - lut_Words, wE7 - lut_Words
  .word wT0 - lut_Words, wT1 - lut_Words, wT2 - lut_Words, wT3 - lut_Words
  .word wT4 - lut_Words, wT5 - lut_Words, wT6 - lut_Words, wT7 - lut_Words
  .word wC0 - lut_Words, wC1 - lut_Words, wC2 - lut_Words, wC3 - lut_Words
  .word wC4 - lut_Words, wC5 - lut_Words, wC6 - lut_Words, wC7 - lut_Words
  .word wC8 - lut_Words, wC9 - lut_Words, wC10 - lut_Words, wC11 - lut_Words
  .word wELEMS - lut_Words, wAND - lut_Words
  .word wG0 - lut_Words, wG1 - lut_Words, wG2 - lut_Words, wG3 - lut_Words
  .word wG4 - lut_Words
  .word wR00 - lut_Words, wR01 - lut_Words, wR02 - lut_Words, wR03 - lut_Words
  .word wR04 - lut_Words, wR05 - lut_Words, wR06 - lut_Words, wR07 - lut_Words
  .word wR08 - lut_Words, wR09 - lut_Words, wR10 - lut_Words, wR11 - lut_Words
  .word wR12 - lut_Words, wR13 - lut_Words, wR14 - lut_Words, wR15 - lut_Words
  .word wR16 - lut_Words, wR17 - lut_Words, wR18 - lut_Words
  .word wS0 - lut_Words, wS1 - lut_Words, wS2 - lut_Words, wS3 - lut_Words
  .word wS4 - lut_Words, wS5 - lut_Words, wS6 - lut_Words, wS7 - lut_Words
  .word wDMG - lut_Words, wRES2 - lut_Words, wWEAK - lut_Words
  .word wPTS - lut_Words, wHP - lut_Words, wATK2 - lut_Words, wHIT2 - lut_Words
  .word wO0 - lut_Words, wO1 - lut_Words, wO2 - lut_Words, wO3 - lut_Words
  .word wO4 - lut_Words
lut_WordOfsEnd:

;  Which word names each of the five routine-0 spells.  Cast Life in Battle
;  gives LIFE and LIF2 a real routine, at which point they stop coming here.
lut_OOBSpell:
  .byte 33, WORD_OOB0 + 0       ; LIFE
  .byte 56, WORD_OOB0 + 1       ; LIF2
  .byte 38, WORD_OOB0 + 2       ; WARP
  .byte 40, WORD_OOB0 + 3       ; SOFT
  .byte 41, WORD_OOB0 + 4       ; EXIT
lut_OOBSpellEnd:

;  An index that runs off the end of this table reads whatever follows it and
;  draws something arbitrary, which is how "All Elements" became "AllBw".
.assert lut_WordOfsEnd - lut_WordOfs = (WORD_OOB0 + 5) * 2, error, "word index table is the wrong length"


;  A set bit in an equip permission word means that class CANNOT use the
;  item.  The twelve bits run FT TH BB RM WM BM KN NJ MA RW WW BW from $800
;  down, which straddles the byte boundary, so each class carries its mask
;  for both halves and one of the two is always zero.  Listed in base,
;  promoted order to match the word table above.
lut_ClassHi:
  .byte $08, $00,  $04, $00,  $02, $00,  $01, $00,  $00, $00,  $00, $00
lut_ClassLo:
  .byte $00, $20,  $00, $10,  $00, $08,  $00, $04,  $80, $02,  $40, $01

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Building the string
;;
;;  The description is assembled into SRAM and handed to the game's own
;;  DrawComplexString, which is happy to read a string out of RAM.  That buys
;;  the line-break control codes and the item-name escape for nothing.
;;
;;  Every byte emitted lands at $80 or above, or is one of the control codes
;;  below $1A.  The range between is DTE, and text that strays into it draws
;;  something other than itself.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  Append A.  Everything else preserved.
opt_emit:
    PHX
    LDX OPTDESCI
    CPX #OPTDESC_MAX - 1        ; the last byte belongs to the terminator
    BCS @full
    STA OPTDESC, X
    INX
    STX OPTDESCI
  @full:
    PLX
    RTS

;  Append a word.  In: A = one of the WORD_ constants.  X and Y clobbered.
;
;  The offsets are sixteen bits because the table is bigger than a byte can
;  reach, and a long read indexed by an eight-bit register cannot get past
;  the first 256 bytes of it either -- hence the pointer.
opt_word:
    ASL A                       ; two bytes per offset
    TAX
    LDA f:lut_WordOfs + OPTFAR, X
    CLC
    ADC #<lut_Words
    STA OPTWPTR
    LDA f:lut_WordOfs + 1 + OPTFAR, X
    ADC #>lut_Words
    STA OPTWPTR+1
    LDA #^(lut_Words + OPTFAR)
    STA OPTWPTR+2
    LDY #$00
    LDA [OPTWPTR], Y            ; the length byte
    STA OPTWORDN
    BEQ @done
  @loop:
    INY
    LDA [OPTWPTR], Y
    JSR opt_emit
    DEC OPTWORDN
    BNE @loop
  @done:
    RTS

;  Append A in decimal, leading zeros suppressed.  X clobbered.
opt_num:
    STA OPTNUMV
    LDA #$00
    STA OPTNUMSEEN
    LDA #100
    JSR @place
    LDA #10
    JSR @place
    LDA OPTNUMV                 ; the ones digit always prints, so zero comes
    CLC                         ;   out as "0" rather than as nothing
    ADC #CHR_ZERO
    JMP opt_emit

  @place:
    STA OPTNUMP
    LDX #$00
  @sub:
    LDA OPTNUMV
    CMP OPTNUMP
    BCC @got
    SEC
    SBC OPTNUMP
    STA OPTNUMV
    INX
    BRA @sub
  @got:
    TXA
    BNE @print
    LDA OPTNUMSEEN              ; a zero with nothing printed yet is a
    BEQ @skip                   ;   leading zero, so drop it
  @print:
    INC OPTNUMSEEN
    TXA
    CLC
    ADC #CHR_ZERO
    JMP opt_emit
  @skip:
    RTS

;  Count the set bits of A and find the lowest.
;
;  A shifting mask rather than a table of the eight bits: long addressing
;  indexed by Y does not exist on this processor, and the table was the only
;  reason this routine wanted two index registers.
;
;  Out: OPTBITN = how many are set, OPTBITLO = the lowest one's index (8 if
;  none), OPTBITS = A.  A and X clobbered.
opt_bitscan:
    STA OPTBITS
    LDA #$00
    STA OPTBITN
    LDA #$08
    STA OPTBITLO                ; 8 means nothing is set
    LDA #$01
    STA OPTBITM
    LDX #$00
  @loop:
    LDA OPTBITM
    AND OPTBITS
    BEQ @next
    INC OPTBITN
    LDA OPTBITLO
    CMP #$08                    ; only the first one found is recorded
    BNE @next
    STX OPTBITLO
  @next:
    ASL OPTBITM
    INX
    CPX #$08
    BCC @loop
    RTS

;  The next set bit at or after index X, for listing more than one of them.
;  In: X = where to start, OPTBITS = the byte.  Out: C set and X = the bit's
;  index, or C clear if there are no more.
opt_bitnext:
    STX OPTBITSTART
    LDA #$01
    STA OPTBITM
    LDX #$00
  @align:
    CPX OPTBITSTART
    BEQ @scan
    ASL OPTBITM
    INX
    BRA @align
  @scan:
    CPX #$08
    BCS @none
    LDA OPTBITM
    AND OPTBITS
    BNE @found
    ASL OPTBITM
    INX
    BRA @scan
  @found:
    SEC
    RTS
  @none:
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  The classes that can use this piece of gear, two letters each.
;
;  A promoted class is named only where its base class cannot use the item,
;  so a line reading "Ni Bb" means "thieves can't, ninjas can, and so can
;  black belts".  Six names need all twelve columns, so the separating
;  spaces come out once there are five or more.
;
;  In: OPTPERMLO / OPTPERMHI.
opt_permissions:
    LDA #$00
    STA OPTPERMN
    LDX #$00
  @count:
    JSR opt_canuse
    BCC @next
    INC OPTPERMN
  @next:
    INX
    INX                         ; a base and its promotion are one entry
    CPX #12
    BCC @count

    LDA OPTPERMN
    CMP #6
    BNE @list
    LDA #WORD_ALLCLASS          ; all six reads better as words than as
    JMP opt_word                ;   twelve unseparated letters

  @list:
    LDA #$00
    STA OPTPERMFIRST
    LDX #$00
  @loop:
    JSR opt_canuse
    BCC @skip
    LDA OPTPERMFIRST
    BEQ @name
    LDA OPTPERMN
    CMP #5                      ; five or six only fit unseparated
    BCS @name
    LDA #CHR_SPACE
    JSR opt_emit
  @name:
    INC OPTPERMFIRST
    LDA OPTPERMSLOT             ; whichever of the pair opt_canuse settled on
    CLC
    ADC #WORD_CLASS0
    JSR opt_word
    LDX OPTPERMSLOT             ; opt_word ate X; put the pair index back
    TXA
    AND #$FE
    TAX
  @skip:
    INX
    INX
    CPX #12
    BCC @loop
    RTS

;  Can either class of the pair starting at X use this item?
;  In: X = the base class's slot, which is even.
;  Out: C set if so, and OPTPERMSLOT = the slot of whichever one can.
;  X preserved.
opt_canuse:
    JSR opt_slotfree
    BCC @promoted
    STX OPTPERMSLOT
    SEC
    RTS
  @promoted:
    INX
    JSR opt_slotfree
    BCC @no
    STX OPTPERMSLOT
    DEX
    SEC
    RTS
  @no:
    DEX
    CLC
    RTS

;  Is one class's bit clear in the permission word?
;  In: X = slot.  Out: C set if that class can equip.  X preserved.
opt_slotfree:
    LDA f:lut_ClassHi + OPTFAR, X
    AND OPTPERMHI
    STA OPTGEARX
    LDA f:lut_ClassLo + OPTFAR, X
    AND OPTPERMLO
    ORA OPTGEARX
    BNE @no
    SEC
    RTS
  @no:
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The accessors
;;
;;  One routine per property whose value -- or whose meaning -- a flag can
;;  change.  The builder below reads nothing else, so when a flag lands it
;;  changes a routine here and the box follows.  These are meant to be the
;;  same routines the battle code calls once Weapon Stats and Double Weapon
;;  Crit Rate are implemented; each will need a JSL wrapper then, since bank
;;  $0C cannot reach this chunk with a JSR.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  A byte of a weapon record that no flag touches.
;
;  Forty records of eight bytes is 320, so the offset of the last few does
;  not fit in an index register -- and the registers are eight bits wide for
;  good, because this port runs the processor in emulation mode.  Splitting
;  the table at the halfway mark keeps every offset under 256.  Getting this
;  wrong is quiet: weapon 38 read weapon 6's numbers and looked plausible.
;
;  In: X = 0-based index, Y = which byte.  Out: A, Z set from it.  X, Y kept.
opt_weapbyte:
    PHX
    TXA
    CMP #32                     ; 32 * 8 is exactly 256
    BCS @high
    JSR @offset
    LDA f:lut_WeaponData + BANK0CFAR, X
    BRA @out
  @high:
    SEC
    SBC #32
    JSR @offset
    LDA f:lut_WeaponData + 256 + BANK0CFAR, X
  @out:
    PLX
    CMP #$00                    ; PLX left the flags describing X, and the
    RTS                         ;   callers branch on the byte

  @offset:
    ASL A                       ; eight bytes per weapon, plus the field
    ASL A
    ASL A
    STA OPTGEARX
    TYA
    CLC
    ADC OPTGEARX
    TAX
    RTS

;  The same for armour.  Four bytes each, and no flag reaches any of them:
;  evade, absorb and resistance are all accumulated out of battle by
;  AdjustEquipStats, so all three are live whatever the settings say.
opt_armbyte:
    PHX
    TXA
    ASL A
    ASL A
    STA OPTGEARX
    TYA
    CLC
    ADC OPTGEARX
    TAX
    LDA f:lut_ArmorData + BANK0CFAR, X
    PLX
    CMP #$00
    RTS

;  A weapon's critical rate, as the game will actually roll it.
;
;  Vanilla never reads the crit byte.  LoadOneCharacterIBStats takes the
;  equipped slot byte, masks off the "equipped" bit and stores THAT as the
;  crit rate -- so a weapon's real crit chance is its own 1-based position in
;  the list, which is why the last weapon crits forty times as often as the
;  first and nobody noticed for thirty years.  Weapon Stats is the flag that
;  makes the byte live; Double Weapon Crit Rate then doubles it.
;
;  In: X = 0-based weapon index.  Out: A = percent.  X kept.
opt_weapcrit:
    LDA OPTFB_WEAPONSTATS
    AND #OPTFM_WEAPONSTATS
    BNE @real
    TXA                         ; the bug, reported honestly: 1-based index
    INC A
    RTS
  @real:
    LDY #WEAPON_CRIT
    JSR opt_weapbyte
    PHA
    LDA OPTFB_CRITRATE
    AND #OPTFM_CRITRATE
    BEQ @once
    PLA
    ASL A                       ; doubled, and pinned at 255 rather than
    BCC @out                    ;   wrapping round to something tiny
    LDA #$FF
    RTS
  @once:
    PLA
  @out:
    RTS

;  Do a weapon's element and category bonus do anything?
;
;  In vanilla neither byte is read by any code at all: LoadOneCharacterIBStats
;  zeroes the player's category and element, then reads only bytes 6 and 7 of
;  the record -- the graphic and the palette.  Weapon Stats is what wires them
;  up.  Listing them while they are inert would describe the item rather than
;  what it will do, so the box leaves those lines out until the flag is on.
;
;  Out: C set if the fields are live.
opt_gearlive:
    LDA OPTFB_WEAPONSTATS
    AND #OPTFM_WEAPONSTATS
    BEQ @dead
    SEC
    RTS
  @dead:
    CLC
    RTS

;  The equip permission word, into OPTPERMLO / OPTPERMHI.
;  In: X = 0-based index.
opt_weapperms:
    TXA
    ASL A                       ; one word each
    TAX
    LDA f:lut_WeaponPermissions + BANK0EFAR, X
    STA OPTPERMLO
    LDA f:lut_WeaponPermissions + 1 + BANK0EFAR, X
    STA OPTPERMHI
    RTS

opt_armperms:
    TXA
    ASL A
    TAX
    LDA f:lut_ArmorPermissions + BANK0EFAR, X
    STA OPTPERMLO
    LDA f:lut_ArmorPermissions + 1 + BANK0EFAR, X
    STA OPTPERMHI
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The descriptions
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  Start a new line.  Control code $05 is the single line break, and it
;  returns to the column DrawBox left in dest_x.
opt_nl:
    LDA #$05
    JMP opt_emit

;  Close the string off.
opt_term:
    LDA #$00
    JMP opt_emit

;  Name the spell a piece of gear casts.  Control code $02 followed by an
;  item id draws that item's name, which is how the shop's own price list is
;  built.  The spell field is 1-based and magic starts at item MG_START.
;  In: A = the spell field, already known nonzero.
opt_castline:
    PHA
    JSR opt_nl
    LDA #WORD_CAST
    JSR opt_word
    LDA #$02
    JSR opt_emit
    PLA
    CLC
    ADC #MG_START - 1
    LDX OPTCTX
    CPX #OPTCTX_CHEST
    BEQ @chest
    JMP opt_emit
  @chest:
    ;  The dialogue renderer's $02 draws whatever dlg_itemid names, and does
    ;  not take an id from the string -- so the spell goes there instead.
    ;  The chest's own item has been drawn by the time this is read.
    STA dlg_itemid
    RTS

;  One line naming the bits set in A: the lowest one, or "All" for all eight.
;  In: A = the byte, X = the word index its bit 0 maps to.
opt_bitline:
    STX OPTGEARX
    JSR opt_bitscan
    LDA OPTBITN
    CMP #$08
    BNE @one
    LDA #WORD_ALL
    RTS                         ; caller decides what follows "All"
  @one:
    LDA OPTBITLO
    CLC
    ADC OPTGEARX
    RTS

;  Build the description for an item.  In: A = item id.
;  Out: C set if one was built, and OPTDESC holds it.
opt_descgear:
    STA OPTGEAR
    LDA #$00
    STA OPTDESCI
    LDA OPTGEAR
    CMP #MG_START
    BCC @gear
    SEC                         ; a spell, if it is one of the sixty-four
    SBC #MG_START
    CMP #64
    BCS @none
    STA OPTGEARI
    JMP opt_descspell
  @gear:
    CMP #TCITYPE_WEPSTART
    BCC @none
    CMP #TCITYPE_ARMSTART
    BCC @weapon
    CMP #TCITYPE_GPSTART
    BCS @none                   ; the armour body is further off than a
    JMP @armor                  ;   conditional branch reaches
  @none:
    CLC
    RTS

  @weapon:
    LDA OPTGEAR
    SEC
    SBC #TCITYPE_WEPSTART
    STA OPTGEARI

    LDA #WORD_ATK
    JSR opt_word
    LDX OPTGEARI
    LDY #WEAPON_DMG
    JSR opt_weapbyte
    JSR opt_num
    JSR opt_nl

    LDA #WORD_HIT
    JSR opt_word
    LDX OPTGEARI
    LDY #WEAPON_HIT
    JSR opt_weapbyte
    JSR opt_num
    JSR opt_nl

    LDA #WORD_CRT
    JSR opt_word
    LDX OPTGEARI
    JSR opt_weapcrit
    JSR opt_num
    JSR opt_nl

    LDX OPTGEARI
    JSR opt_weapperms
    JSR opt_permissions

    JSR opt_gearlive            ; the two bonus lines, if the flag wires them
    BCC @wspell                 ;   up; otherwise they would be fiction

    LDX OPTGEARI
    LDY #WEAPON_CAT
    JSR opt_weapbyte
    BEQ @welem
    PHA
    JSR opt_nl
    LDA #WORD_HURT
    JSR opt_word
    PLA
    LDX #WORD_TYPE0
    JSR opt_bitline
    JSR opt_word

  @welem:
    LDX OPTGEARI
    LDY #WEAPON_ELEM
    JSR opt_weapbyte
    BEQ @wspell
    PHA                         ; opt_nl draws, and drawing goes through A
    JSR opt_nl
    PLA
    LDX #WORD_ELEM0
    JSR opt_bitline
    CMP #WORD_ALL               ; "All Elements", or "Fire Element"
    BEQ @wall
    JSR opt_word
    LDA #WORD_ELEMENT
    BRA @welemw
  @wall:
    JSR opt_word
    LDA #WORD_ELEMENTS
  @welemw:
    JSR opt_word

  @wspell:
    LDX OPTGEARI
    LDY #WEAPON_SPELL
    JSR opt_weapbyte
    BEQ @done
    JSR opt_castline
  @done:
    JSR opt_term
    SEC
    RTS

  @armor:
    LDA OPTGEAR
    SEC
    SBC #TCITYPE_ARMSTART
    STA OPTGEARI

    LDA #WORD_DEF
    JSR opt_word
    LDX OPTGEARI
    LDY #ARMOR_ABSORB
    JSR opt_armbyte
    JSR opt_num
    JSR opt_nl

    LDA #WORD_EVA
    JSR opt_word
    LDX OPTGEARI
    LDY #ARMOR_EVADE
    JSR opt_armbyte
    JSR opt_num
    JSR opt_nl

    LDX OPTGEARI
    JSR opt_armperms
    JSR opt_permissions

    LDX OPTGEARI
    LDY #ARMOR_RESIST
    JSR opt_armbyte
    BEQ @aspell
    PHA
    JSR opt_nl
    LDA #WORD_RESIST
    JSR opt_word
    PLA
    LDX #WORD_ELEM0
    JSR opt_bitline
    CMP #WORD_ALL               ; "Resist All" fits on the one line
    BNE @alist
    LDA #CHR_SPACE
    JSR opt_emit
    LDA #WORD_ALL
    JSR opt_word
    BRA @aspell

    ;  Otherwise the elements go on their own line, because "Resist" plus a
    ;  four-letter name is already eleven of the twelve columns.  Two names
    ;  fit beside each other; anything past that is counted instead, which
    ;  only one piece of armour in the game needs.
  @alist:
    JSR opt_nl
    LDA #CHR_SPACE
    JSR opt_emit
    LDX #$00
    LDA #$00
    STA OPTPERMFIRST            ; how many have been named so far
  @aloop:
    JSR opt_bitnext
    BCC @aspell
    LDA OPTPERMFIRST
    CMP #$02
    BCS @amore
    LDA OPTPERMFIRST            ; CMP above left the flags describing the
    BEQ @aname                  ;   comparison, not the count
    LDA #CHR_SPACE
    JSR opt_emit
  @aname:
    INC OPTPERMFIRST
    TXA
    PHA
    CLC
    ADC #WORD_ELEM0
    JSR opt_word
    PLA
    TAX
    INX
    BRA @aloop
  @amore:
    JSR opt_nl                  ; "and 1 more" for the ones that did not fit
    LDA #WORD_AND
    JSR opt_word
    LDA OPTBITN
    SEC
    SBC #$02
    JSR opt_num
    LDA #WORD_MORE
    JSR opt_word

  @aspell:
    LDX OPTGEARI
    LDY #ARMOR_SPELL
    JSR opt_armbyte
    BEQ @adone
    JSR opt_castline
  @adone:
    JSR opt_term
    SEC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The box
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_boxdims:
    LDA #OPTINFO_X
    STA box_x
    LDA #OPTINFO_Y
    STA box_y
    LDA #OPTINFO_W
    STA box_wd
    LDA #OPTINFO_H
    STA box_ht
    RTS

;  One frame while the box is up.
;
;  The real ShopFrame, reached through a four-byte trampoline in bank $0E,
;  rather than one assembled here out of fixed-bank pieces.  The assembled
;  one cleared OAM and drew nothing, so the hand cursor blinked out and back
;  each time the box opened; FFR keeps calling ShopFrame and the cursor never
;  moves.  It also handles the joypad and the music, so nothing else is left
;  to do here.
opt_infoframe:
    LDA OPTCTX
    BNE @menu
    JMP opt_shopdraw
  @menu:
    CMP #$01
    BEQ @equip
    CALL0E MenuFrame
    RTS
  @equip:
    CALL0E EquipMenuFrame
    RTS

;  Hold the box until the player presses something.  The button that opened
;  it has to be let go of first, or the same press closes it again.
opt_waitbtn:
  @release:
    JSR opt_infoframe
    LDA joy
    BNE @release
  @press:
    JSR opt_infoframe
    LDA joy
    BEQ @press
    LDA #$00
    STA joy_a                   ; the press that dismissed the box must not
    STA joy_b                   ;   also count as choosing the item
    STA joy_select
    ;  Nor as moving the cursor.  The shop loop set joy_prevdir before the
    ;  box opened and compares the pad against it on the way round; left
    ;  stale, a box dismissed with up or down reads as a fresh press of that
    ;  direction and the cursor jumps a slot.
    LDA joy
    AND #$0C
    STA joy_prevdir
    RTS

;  Draw the description, wait, and put the screen back as it was.
opt_showbox:
    LDA text_ptr                ; the shop loop keeps its cursor-position
    STA OPTSAVEPTR              ;   table pointer in here
    LDA text_ptr+1
    STA OPTSAVEPTR+1

    JSR opt_boxdims
    LDA #CHUNK_OPT              ; DrawBox stalls through MenuCondStall, which
    STA cur_bank                ;   swaps; this is where it comes back to
    JSR DrawBox                 ; leaves dest_x/dest_y inside the box, which
                                ;   is where the string will land
    LDA #<OPTDESC
    STA text_ptr
    LDA #>OPTDESC
    STA text_ptr+1
    LDA #CHUNK_OPT              ; the string is in SRAM, which every chunk
    STA cur_bank                ;   maps alike, so this only has to name a
    STA ret_bank                ;   bank we can come back to
    JSR DrawComplexString

    JSR opt_waitbtn

    LDA OPTCTX
    BNE @redraw                 ; a menu has live content under the box and
                                ;   has to be drawn again from scratch
    JSR opt_boxdims
    LDA #CHUNK_OPT
    STA cur_bank
    JSR EraseBox
    BRA @ptr
  @redraw:
    JSR opt_menuredraw
  @ptr:
    LDA OPTSAVEPTR
    STA text_ptr
    LDA OPTSAVEPTR+1
    STA text_ptr+1
    LDA #BANK_MENUS             ; back to what the shop loop expects
    STA cur_bank
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  Called once a frame from the shop's common loop, just after ShopFrame.
;
;  Select is free here: the loop already zeroes it on every exit, with the
;  comment "but why?  select isn't used in shops?".  Nothing else about the
;  game's input handling is touched.
opt_shopinfo_body:
    ;  Say which screen this is before anything else can return early.  The
    ;  box reads this to decide whether closing it means erasing a box or
    ;  redrawing a whole menu, and OPTCTX is battery-backed -- inheriting a
    ;  value from a previous session put the menus' full-screen redraw over
    ;  a shop, which turned the screen off and drew menu boxes on it.
    LDA #OPTCTX_SHOP
    STA OPTCTX
    LDA OPTFB_SHOPINFO
    AND #OPTFM_SHOPINFO
    BEQ @out
    LDA joy_select
    BEQ @out
    LDA #$00
    STA joy_select              ; spent, whether or not a box follows
    LDA shopcurs_x
    CMP #SHOPCURS_LEFT
    BEQ @out                    ; the command column has nothing to describe
    LDX cursor
    LDA item_box, X
    JSR opt_descgear
    BCC @out                    ; not a weapon or a piece of armour

    JMP opt_showbox
  @out:
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The victory poses
;;
;;  The other half of this flag: a character who can use whatever the cursor
;;  is on raises their arms.  It answers "can I use that?" for four people at
;;  a glance, which is the question the description box answers one line at a
;;  time -- FFR ships the two together and so do we.
;;
;;  The pose bytes are written immediately before a ShopFrame and cleared
;;  immediately after, because the main menu and the lineup draw their party
;;  with the same DrawOBSprite and would otherwise inherit them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  The twelve classes' permission tables sit right behind their pointer
;  table, contiguous and eight bytes each, so one long read reaches any of
;  them without following a pointer into another bank.  bank_0E asserts the
;  layout this depends on.
lut_MagicPermis = lut_MagicPermisPtr + 24

;  Asked by DrawOBSprite, once per character per frame.
;  In: X = the character's stat index ($00, $40, $80, $C0).
;  Out: A = the tile offset of the pose to draw.
opt_pose:
    PHX
    TXA
    LSR A                       ; the stat index is the character number
    LSR A                       ;   shifted up by six
    LSR A
    LSR A
    LSR A
    LSR A
    TAX
    LDA OPTPOSE, X
    PLX
    RTL

opt_zeroposes:
    LDA #$00
    STA OPTPOSE+0
    STA OPTPOSE+1
    STA OPTPOSE+2
    STA OPTPOSE+3
    RTS

;  Who can use what the cursor is on.  Everyone lowers their arms while the
;  cursor is in the command column, which is FFR's behaviour and reads as
;  "this question is not being asked right now".
opt_setposes:
    JSR opt_zeroposes
    LDA OPTFB_SHOPINFO
    AND #OPTFM_SHOPINFO
    BEQ @done
    LDA shopcurs_x
    CMP #SHOPCURS_LEFT
    BEQ @done
    LDX cursor
    LDA item_box, X
    BEQ @done                   ; an empty slot in the list
    STA OPTPOSEIT
    LDX #$00
  @loop:
    JSR opt_canuseit
    BCC @next
    LDA #POSE_VICTORY
    STA OPTPOSE, X
  @next:
    INX
    CPX #$04
    BCC @loop
  @done:
    RTS

;  In: X = character 0..3, OPTPOSEIT = the item.  Out: C set if they can use
;  it.  X preserved.
opt_canuseit:
    STX OPTPOSEI
    TXA
    ASL A                       ; characters are $40 bytes apart
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    LDA ch_class, X
    STA OPTPOSECL
    LDA OPTPOSEIT
    CMP #MG_START
    BCS @spell

    CMP #TCITYPE_WEPSTART       ; potions and the like: nobody poses
    BCC @no
    CMP #TCITYPE_ARMSTART
    BCC @weapon
    CMP #TCITYPE_GPSTART
    BCS @no
    SEC
    SBC #TCITYPE_ARMSTART
    TAX
    JSR opt_armperms
    BRA @equip
  @weapon:
    SEC
    SBC #TCITYPE_WEPSTART
    TAX
    JSR opt_weapperms
  @equip:
    LDA OPTPOSECL               ; a set bit means that class CANNOT use it
    ASL A
    TAX
    LDA f:lut_ClassEquipBit + BANK0EFAR, X
    AND OPTPERMLO
    STA OPTGEARX
    LDA f:lut_ClassEquipBit + 1 + BANK0EFAR, X
    AND OPTPERMHI
    ORA OPTGEARX
    BNE @no
    BRA @yes

    ;  Magic shops ask a different question -- can this character learn the
    ;  spell -- off a different table, one bit per spell with the high bit
    ;  first and, again, set meaning no.
  @spell:
    SEC
    SBC #MG_START
    STA OPTGEARX
    AND #$07
    STA OPTPOSEBIT
    LDA OPTGEARX
    LSR A                       ; eight spells to a level
    LSR A
    LSR A
    STA OPTGEARX
    LDA OPTPOSECL
    ASL A                       ; eight bytes to a class
    ASL A
    ASL A
    CLC
    ADC OPTGEARX
    TAX
    LDA f:lut_MagicPermis + BANK0EFAR, X
    STA OPTGEARX
    LDA #$80                    ; the bit for this spell, $80 >> (spell AND 7)
    LDX OPTPOSEBIT
    BEQ @test
  @shift:
    LSR A
    DEX
    BNE @shift
  @test:
    AND OPTGEARX
    BNE @no
  @yes:
    LDX OPTPOSEI
    SEC
    RTS
  @no:
    LDX OPTPOSEI
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  A shop frame with the poses applied.  They go up just before the sprites
;  are drawn and come down straight after, so nothing else that draws a party
;  can see them.
opt_shopdraw:
    JSR opt_setposes
    JSL OptShopFrameFar + BANK0EFAR
    JMP opt_zeroposes

;  Replaces the shop loop's "JSR ShopFrame".
opt_shopframe:
    PHB                         ; every routine below reaches SwapPRG, and
                                ;   hal_swapprg ends in PLB -- see opt_shopinfo
    JSR opt_shopdraw
    JSR opt_shopinfo_body
    PLB
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Weapon Stats
;;
;;  Three fields of a weapon are read by nothing at all in vanilla.
;;  LoadOneCharacterIBStats zeroes the player's category and element, then
;;  stores the equipped slot byte as the critical rate -- so a weapon's real
;;  crit chance is its own position in the list, and its element and category
;;  bonus do nothing whatever.  This fills all three in properly.
;;
;;  It runs through the same opt_weapcrit the description box asks, which is
;;  the point: the number on the shop screen and the number the battle rolls
;;  come out of one routine, and Double Weapon Crit Rate lands on both at
;;  once because it lands inside that routine.
;;
;;  The element and category go into btlch_elemweak and btlch_category, which
;;  is where the attack code already looks for them -- see the two BUGGED
;;  comments beside btl_attacker_element and btl_attacker_category.  Those
;;  two fields double as the player's own weakness and category on defence,
;;  but vanilla never sets either and nothing else writes them, so the
;;  defence side now reads a plain zero and the fields are free.
;;
;;  In: A = the equipped weapon's 1-based id, or 0 for unarmed.
;;  Out: A and Z as they came in, so the caller's BEQ still works.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_weaponstats:
    STA OPTWSIDX
    PHX
    PHY

    LDA OPTWSIDX                ; the crit rate is written either way: with
    BEQ @none                   ;   the flag off opt_weapcrit answers with the
    DEC A                       ;   weapon's index, which is what vanilla
    TAX                         ;   stored here and what the box prints
    JSR opt_weapcrit
    BRA @crit
  @none:
    LDA #$00                    ; unarmed, as vanilla's store left it
  @crit:
    LDY #btlch_critrate
    STA (btl_ib_charstat_ptr), Y

    LDA OPTFB_WEAPONSTATS
    AND #OPTFM_WEAPONSTATS
    BEQ @done                   ; off: element and category keep the zero the
    LDA OPTWSIDX                ;   caller wrote, which is vanilla exactly
    BEQ @done

    DEC A
    TAX
    LDY #WEAPON_ELEM
    JSR opt_weapbyte
    LDY #btlch_elemweak
    STA (btl_ib_charstat_ptr), Y

    LDA OPTWSIDX
    DEC A
    TAX
    LDY #WEAPON_CAT
    JSR opt_weapbyte
    LDY #btlch_category
    STA (btl_ib_charstat_ptr), Y

  @done:
    PLY
    PLX
    LDA OPTWSIDX                ; restores Z for the caller
    RTL

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Spells
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  A byte of a spell record, as the spell will actually behave.
;
;  The two fields a buff can change are asked of the same routines the battle
;  asks, so a buffed CURE reads the same here as it does when it is cast.
;
;  In: X = spell 0..63, Y = which byte.  Out: A.  X, Y kept.
opt_spellbyte:
    JSR opt_spellrom
    STA OPTSPRAW
    CPY #MAGDATA_EFFECTIVITY
    BEQ @eff
    CPY #MAGDATA_TARGET
    BEQ @tgt
    LDA OPTSPRAW
    RTS
  @eff:
    PHX
    PHY
    TXA
    JSR opt_spellbuffed         ; the rule the battle uses
    PLY
    PLX
    BCS @out
    LDA OPTSPRAW                ; no buff: the record as it stands
  @out:
    RTS
  @tgt:
    PHX
    PHY
    TXA
    JSR opt_spelltarget
    PLY
    PLX
    BCS @out
    LDA OPTSPRAW
    RTS

;  The record byte as the ROM holds it.  Sixty-four records of eight bytes is
;  512, so the table is read in halves for the same reason the weapon one is.
;  In: X = spell 0..63, Y = which byte.  Out: A.  X, Y kept.
opt_spellrom:
    PHX
    PHY
    TXA
    CMP #32                     ; 32 * 8 is exactly 256
    BCS @high
    JSR @offset
    LDA f:lut_MagicData + BANK0CFAR, X
    BRA @done
  @high:
    SEC
    SBC #32
    JSR @offset
    LDA f:lut_MagicData + 256 + BANK0CFAR, X
  @done:
    PLY
    PLX
    RTS

  @offset:
    ASL A                       ; eight bytes per spell, plus the field
    ASL A
    ASL A
    STA OPTGEARX
    TYA
    CLC
    ADC OPTGEARX
    TAX
    RTS

;  OPTN16 = A * X, by repeated addition; X is 2, 4 or 6.
opt_scale16:
    STA OPTSPEFF
    LDA #$00
    STA OPTN16
    STA OPTN16+1
  @loop:
    LDA OPTSPEFF
    CLC
    ADC OPTN16
    STA OPTN16
    BCC @nc
    INC OPTN16+1
  @nc:
    DEX
    BNE @loop
    RTS

lut_Pow10:
  .word 10000, 1000, 100, 10

;  Append OPTN16 in decimal, leading zeros suppressed.  A damage spell's
;  weakness figure is six times its effectivity, which does not fit in a byte.
opt_num16:
    LDA #$00
    STA OPTNUMSEEN
    LDX #$00
  @place:
    CPX #8
    BCS @ones
    LDA f:lut_Pow10 + OPTFAR, X
    STA OPTNUMP16
    LDA f:lut_Pow10 + 1 + OPTFAR, X
    STA OPTNUMP16+1
    LDY #$00
  @sub:
    LDA OPTN16                  ; 16-bit compare, low byte first
    CMP OPTNUMP16
    LDA OPTN16+1
    SBC OPTNUMP16+1
    BCC @digit
    LDA OPTN16
    SEC
    SBC OPTNUMP16
    STA OPTN16
    LDA OPTN16+1
    SBC OPTNUMP16+1
    STA OPTN16+1
    INY
    BRA @sub
  @digit:
    TYA
    BNE @print
    LDA OPTNUMSEEN
    BEQ @next                   ; a leading zero
    TYA
  @print:
    INC OPTNUMSEEN
    CLC
    ADC #CHR_ZERO
    JSR opt_emit
  @next:
    INX
    INX
    BRA @place
  @ones:
    LDA OPTN16
    CLC
    ADC #CHR_ZERO
    JMP opt_emit

;  Append the effectivity scaled by X, on a new line after a space.
opt_scaleline:
    PHX
    LDA #CHR_SPACE
    JSR opt_emit
    PLX
    LDA OPTSPEFF
    JSR opt_scale16
    JMP opt_num16

;  Name a routine-0 spell by what it does in a menu; it has no battle
;  routine to name it after.  In: OPTGEARI = the spell.
opt_oobword:
    LDX #$00
  @scan:
    CPX #lut_OOBSpellEnd - lut_OOBSpell
    BCS @none
    LDA f:lut_OOBSpell + OPTFAR, X
    CMP OPTGEARI
    BEQ @found
    INX
    INX
    BRA @scan
  @found:
    LDA f:lut_OOBSpell + 1 + OPTFAR, X
    JMP opt_word
  @none:
    RTS

;  " <n>", the effectivity scaled by X.
opt_spacenum:
    PHX
    LDA #CHR_SPACE
    JSR opt_emit
    PLX
    LDA OPTSPEFF
    JSR opt_scale16
    JMP opt_num16

;  A list of whatever bits are set in OPTSPEFF, naming the first and counting
;  the rest.  In: X = the word the lowest bit maps to.
opt_bitlist:
    STX OPTPOSEBIT
    LDA OPTSPEFF
    BEQ @out
    JSR opt_nl
    LDA #CHR_SPACE
    JSR opt_emit
    LDA OPTSPEFF
    LDX OPTPOSEBIT
    JSR opt_bitline
    JSR opt_word
    LDA OPTBITN
    CMP #$02
    BCC @out
    JSR opt_nl
    LDA #WORD_AND
    JSR opt_word
    LDA OPTBITN
    SEC
    SBC #$01
    JSR opt_num
    LDA #WORD_MORE
    JMP opt_word
  @out:
    RTS

;  In: OPTGEARI = spell 0..63.  Out: C set, OPTDESC holds the description.
opt_descspell:
    LDX OPTGEARI                ; the element it carries, if any
    LDY #MAGDATA_ELEMENT
    JSR opt_spellbyte
    BEQ @target
    LDX #WORD_ELEM0
    JSR opt_bitline
    CMP #WORD_ALL
    BEQ @eall
    JSR opt_word
    LDA #WORD_ELEMENT
    BRA @elemw
  @eall:
    JSR opt_word
    LDA #WORD_ELEMENTS
  @elemw:
    JSR opt_word
    JSR opt_nl

  @target:
    LDX OPTGEARI                ; who it reaches
    LDY #MAGDATA_TARGET
    JSR opt_spellbyte
    JSR opt_bitscan
    LDA OPTBITLO
    CMP #$08
    BCS @routine
    CLC
    ADC #WORD_TGT0
    JSR opt_word
    JSR opt_nl

  @routine:
    LDX OPTGEARI
    LDY #MAGDATA_EFFECT         ; the routine, which is byte 4 -- FFR calls
    JSR opt_spellbyte           ;   this one Routine and byte 1 Effect, which
    STA OPTSPROUT               ;   is the other way round from this port
    LDX OPTGEARI
    LDY #MAGDATA_EFFECTIVITY
    JSR opt_spellbyte
    STA OPTSPEFF

    LDA OPTSPROUT
    BNE @named
    JSR opt_oobword             ; no battle routine at all
    JMP @done
  @named:
    CLC
    ADC #WORD_RTN0
    JSR opt_word

    ;  What else there is to say depends on the routine.  The handlers are
    ;  further off than a conditional branch reaches, so the branches land on
    ;  jumps parked here instead.
    LDA OPTSPROUT
    CMP #$01
    BEQ @jdamage
    CMP #$02
    BEQ @jdamage
    CMP #$06
    BEQ @jheal
    CMP #$07
    BEQ @jheal
    CMP #$05
    BEQ @jminus
    CMP #$0E
    BEQ @jminus
    CMP #$09
    BEQ @jplus
    CMP #$10
    BEQ @jplus
    CMP #$0D
    BEQ @jatkhit
    CMP #$0A
    BEQ @jelem
    CMP #$03
    BEQ @jstatus
    CMP #$08
    BEQ @jstatus
    CMP #$12
    BEQ @jstatus
    JMP @done

  @jdamage: JMP @damage
  @jheal:   JMP @heal
  @jminus:  JMP @minus
  @jplus:   JMP @plus
  @jatkhit: JMP @atkhit
  @jelem:   JMP @elemlist
  @jstatus: JMP @status

  @damage:                      ; FFR's figures: twice to four times the
    JSR opt_nl                  ;   effectivity, the resisted case at face
    LDX #2                      ;   value, and six times it against a weakness
    JSR opt_spacenum
    LDA #CHR_MINUS
    JSR opt_emit
    LDX #4
    LDA OPTSPEFF
    JSR opt_scale16
    JSR opt_num16
    LDA #WORD_DMG
    JSR opt_word
    JSR opt_nl
    LDA #WORD_RES2
    JSR opt_word
    LDX #1
    LDA OPTSPEFF
    JSR opt_scale16
    JSR opt_num16
    JSR opt_nl
    LDA #WORD_WEAK
    JSR opt_word
    LDX #6
    LDA OPTSPEFF
    JSR opt_scale16
    JSR opt_num16
    JMP @done

  @heal:
    JSR opt_nl
    LDX #1
    JSR opt_spacenum
    LDA #CHR_MINUS
    JSR opt_emit
    LDX #2
    LDA OPTSPEFF
    JSR opt_scale16
    JSR opt_num16
    LDA #WORD_HP
    JSR opt_word
    JMP @done

  @minus:
    JSR opt_nl
    LDA #CHR_SPACE
    JSR opt_emit
    LDA #CHR_MINUS
    JSR opt_emit
    LDA OPTSPEFF
    JSR opt_num
    LDA #WORD_PTS
    JSR opt_word
    JMP @done

  @plus:
    JSR opt_nl
    LDA #CHR_SPACE
    JSR opt_emit
    LDA #CHR_PLUS
    JSR opt_emit
    LDA OPTSPEFF
    JSR opt_num
    LDA #WORD_PTS
    JSR opt_word
    JMP @done

  @atkhit:
    JSR opt_nl
    LDA #CHR_SPACE
    JSR opt_emit
    LDA #CHR_PLUS
    JSR opt_emit
    LDA OPTSPEFF
    JSR opt_num
    LDA #WORD_ATK2
    JSR opt_word
    JSR opt_nl
    LDA #CHR_SPACE
    JSR opt_emit
    LDA #CHR_PLUS
    JSR opt_emit
    LDX OPTGEARI
    LDY #MAGDATA_HITRATE
    JSR opt_spellbyte
    JSR opt_num
    LDA #WORD_HIT2
    JSR opt_word
    JMP @done

  @elemlist:
    LDX #WORD_ELEM0
    JSR opt_bitlist
    JMP @done

  @status:
    LDX #WORD_STAT0
    JSR opt_bitlist

  @done:
    JSR opt_term
    SEC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The equip and magic menus
;;
;;  The same box, opened with the same button.  The difference from a shop is
;;  what is underneath it: the shop draws over the command box, which the
;;  item list has already erased, so erasing the box again puts things back.
;;  Both menus have their own content there, so the screen is turned off and
;;  drawn again, which is what FFR does too.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_menuredraw:
    LDA menustall
    PHA
    LDA #$00
    wPPUMASK                    ; the screen goes off while the menu is
    LDA #$00                    ;   rebuilt -- wPPUMASK is a call, so do not
    STA menustall               ;   assume it left A alone
    LDA OPTCTX
    CMP #OPTCTX_EQUIP
    BNE @magic

    CALL0E DrawEquipMenu        ; the order FFR uses: the screen comes back
    CALL0E TurnMenuScreenOn     ;   on before the item names are drawn
    ;  Through the trampoline even though it is in the fixed bank, not bank
    ;  $0E.  It ends by swapping to BANK_MENUS whatever cur_bank says, so its
    ;  RTS lands in that chunk -- which is fine when the trampoline is what
    ;  called it, and a crash when the options chunk did.
    CALL0E DrawEquipMenuStrings
    BRA @done

  @magic:
    CALL0E ClearNT
    LDA cursor                  ; DrawMagicMenuMainBox resets the cursor
    PHA
    CALL0E DrawMagicMenuMainBox
    PLA
    STA cursor
    CALL0EA DrawMainItemBox, $07
    CALL0EA DrawCharMenuString, $29
    CALL0E TurnMenuScreenOn_ClearOAM

  @done:
    PLA
    STA menustall
    RTS

;  Shared by both menus: put the box up for the item id in A.
opt_menubox:
    JSR opt_descgear
    BCC @out
    JSR opt_showbox
  @out:
    RTS

;  Has Select been pressed, with the flag on?  Out: C set if so.
opt_wantinfo:
    LDA OPTFB_SHOPINFO
    AND #OPTFM_SHOPINFO
    BEQ @no
    LDA joy_select
    BEQ @no
    LDA #$00
    STA joy_select              ; spent, whether or not a box follows
    SEC
    RTS
  @no:
    CLC
    RTS

;  The equip menu.  item_box holds equipment slots here -- a 1-based index
;  into the weapon or armour table, with bit 7 set when it is worn -- and
;  equipoffset says which of the two menus this is.
opt_equipframe:
    PHB
    LDA #OPTCTX_EQUIP           ; see opt_shopinfo_body
    STA OPTCTX
    JSR ClearOAM                ; the three calls this replaced, then Select
    CALL0E DrawEquipMenuCurs
    CALL0E EquipMenuFrame
    JSR opt_wantinfo
    BCC @out
    JSR opt_equipitem
    BCC @out
    JSR opt_menubox
  @out:
    PLB
    RTL

;  Which item the equip menu's cursor is on.  item_box holds equipment slots
;  here -- a 1-based index into the weapon or armour table, with bit 7 set
;  when it is worn -- and equipoffset says which of the two menus this is.
;  Out: C set and A = the item id.
opt_equipitem:
    LDX cursor
    LDA item_box, X
    BEQ @none                   ; an empty slot
    AND #$7F
    STA OPTGEARX
    LDY equipoffset
    CPY #ch_weapons - ch_stats
    BNE @armor
    LDA OPTGEARX
    CLC
    ADC #TCITYPE_WEPSTART - 1   ; the index is 1-based
    SEC
    RTS
  @armor:
    LDA OPTGEARX
    CLC
    ADC #TCITYPE_ARMSTART - 1
    SEC
    RTS
  @none:
    CLC
    RTS

;  The magic menu.  A character's spell list stores, for each of the four
;  slots on each of the eight levels, which spell of that level they know --
;  1 to 8, or 0 for none.  So the spell is its level's base plus that.
opt_magicframe:
    PHB
    LDA #OPTCTX_MAGIC           ; see opt_shopinfo_body
    STA OPTCTX
    JSR ClearOAM
    CALL0E DrawMagicMenuCursor
    CALL0E MenuFrame
    JSR opt_wantinfo
    BCC @out
    JSR opt_magicspell
    BCC @out
    JSR opt_menubox
  @out:
    PLB
    RTL

;  Which spell the magic menu's cursor is on.  A character's list stores, for
;  each of the four slots on each of the eight levels, which spell of that
;  level they know -- 1 to 8, or 0 for none -- so the spell is its level's
;  base plus that.  Out: C set and A = the item id.
opt_magicspell:
    LDA submenu_targ            ; the same arithmetic UseMagic_GetRequiredMP
    ROR A                       ;   uses to find the character
    ROR A
    ROR A
    AND #$C0
    ORA cursor
    TAX
    LDA ch_spells, X
    BEQ @none                   ; a slot they have not filled
    STA OPTGEARX
    LDA cursor
    LSR A                       ; four slots to a level
    LSR A
    ASL A                       ; eight spells to a level
    ASL A
    ASL A
    CLC
    ADC OPTGEARX
    CLC
    ADC #MG_START - 1
    SEC
    RTS
  @none:
    CLC
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Chest Information
;;
;;  The same description, under the message a chest puts on screen.  It draws
;;  into the dialogue box, which is already on the offscreen nametable and
;;  about to be revealed a couple of scanlines at a time -- so there is no
;;  modal loop here and nothing to erase.  The box's own wait dismisses both.
;;
;;  DrawDialogueBox draws every dialogue in the game, so this has to know a
;;  chest from a conversation.  dlgsfx is the tell: OpenTreasureChest sets it
;;  to 1 or 2 to pick the jingle, and it is zeroed before any other dialogue.
;;  That costs nothing, which matters -- the hook is in the fixed bank.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

opt_chestinfo:
    PHB
    LDA OPTFB_CHESTINFO
    AND #OPTFM_CHESTINFO
    BEQ @out
    LDA dlgsfx                  ; a conversation, not a chest
    BEQ @out
    LDA #OPTCTX_CHEST
    STA OPTCTX
    LDA dlg_itemid
    JSR opt_descgear
    BCC @out                    ; a potion or a key item: nothing to say

    LDA box_y                   ; the renderer takes its position from box_*,
    PHA                         ;   and returns dest_x to box_x every line
    CLC
    ADC #OPTCHEST_DY
    CMP #30                     ; nametables are thirty rows tall
    BCC @row
    SEC
    SBC #30
  @row:
    STA box_y

    LDA #<OPTDESC
    STA text_ptr
    LDA #>OPTDESC
    STA text_ptr+1
    LDA #CHUNK_OPT              ; a line break calls CallMusicPlay, which
    STA cur_bank                ;   returns through this
    JSR DrawDialogueString_PtrLoaded

    PLA
    STA box_y
    LDA #BANK_DIALOGUE          ; what the unhooked tail call would have left
    STA cur_bank
  @out:
    PLB
    RTL

