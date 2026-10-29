; ---------------------------------------------------------------------------
;  dlghint.inc -- the game's lines that give a key item's or a dungeon's
;  whereabouts, and each one's replacement once they are wrong
;
;  Included by world.asm, for room: rando_dlgtext (dlgtext.inc), in the
;  randomizer's chunk, reads these by WORLDFAR and copies the line from
;  here into OPTDESC.  Each replacement is what stays true of the line, or
;  where all of it was the hint, a line that is (user, 2026-10-28, every
;  one approved).  Under Key items Vanilla all are the game's own, Map
;  shuffle being Off there too.
; ---------------------------------------------------------------------------

;  The game's dialogue number of each.
lut_DlgHintId:
  .BYTE $11, $41, $54, $5D, $5F, $60, $69, $71, $76, $9F, $B0, $C6, $C8, $DE
  .BYTE $3F, $45, $5B, $63, $7E, $82, $C9, $E7
  .BYTE $B8, $D2
DLG_NHINT = * - lut_DlgHintId

;  The Map shuffle each needs, at least.  A key item's whereabouts are wrong
;  once Key items shuffles them, Map shuffle or not; a dungeon's only once
;  Map shuffle moves where the entrances lead (user: "Key item shuffle
;  doesn't impact where locations are, entrance shuffle does"); and the way
;  through one only once Floors rewires its stairs.
lut_DlgHintMap:
  .BYTE ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF
  .BYTE ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF
  .BYTE ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF, ENTRANCES_OFF
  .BYTE ENTRANCES_ONLY, ENTRANCES_ONLY, ENTRANCES_ONLY, ENTRANCES_ONLY
  .BYTE ENTRANCES_ONLY, ENTRANCES_ONLY, ENTRANCES_ONLY, ENTRANCES_ONLY
  .BYTE ENTRANCES_FLOORS, ENTRANCES_FLOORS
.assert * - lut_DlgHintMap = DLG_NHINT, error, "a hint without its Map shuffle"
.assert ENTRANCES_OFF < ENTRANCES_ONLY && ENTRANCES_ONLY < ENTRANCES_FLOORS, error, "the modes no longer nest"

;  A key item's whereabouts.
lut_DlgHint0:   ; $11, Astos as the King: "Go south, to the Cave of Marsh"
  FFTEXT "Astos double-crossed us."
  .BYTE DLG_NL
  FFTEXT "Find the CROWN, and"
  .BYTE DLG_NL
  FFTEXT "bring it directly back"
  .BYTE DLG_NL
  FFTEXT "to me!"
  .BYTE $00
lut_DlgHint1:   ; $41: "Our ancestors gave the KEY to the Prince of ElfLand"
  FFTEXT "400 years ago the"
  .BYTE DLG_NL
  FFTEXT "Treasury was locked by"
  .BYTE DLG_NL
  FFTEXT "the mystic KEY."
  .BYTE $00
lut_DlgHint2:   ; $54: "Matoya's HERB is the only thing"
  FFTEXT "The Elves live across"
  .BYTE DLG_NL
  FFTEXT "the sea. Only HERB"
  .BYTE DLG_NL
  FFTEXT "will wake their Prince."
  .BYTE $00
lut_DlgHint3:   ; $5D: "a witch who has HERBS"
  FFTEXT "It is said there is a"
  .BYTE DLG_NL
  FFTEXT "blind witch named"
  .BYTE DLG_DOTS, DLG_DOTS, DLG_NL
  FFTEXT "Matoya!"
  .BYTE $00
lut_DlgHint4:   ; $5F: "The Prince keeps the mystic KEY"
  FFTEXT "The Prince waits for"
  .BYTE DLG_NL
  FFTEXT "the coming of the"
  .BYTE DLG_NL
  FFTEXT "LIGHT WARRIORS."
  .BYTE $00
lut_DlgHint5:   ; $60: "the cause of all problems ... the cave of Marsh"
  FFTEXT "The Marsh Cave is a"
  .BYTE DLG_NL
  FFTEXT "festering pit of decay,"
  .BYTE DLG_NL
  FFTEXT "crawling with undead."
  .BYTE $00
lut_DlgHint6:   ; $69: "there you will find the FLOATER" (the user's line)
  FFTEXT "North of Crescent Lake,"
  .BYTE DLG_NL
  FFTEXT "through the winding"
  .BYTE DLG_NL
  FFTEXT "rivers, is a"
  .BYTE DLG_NL
  FFTEXT "mysterious cave."
  .BYTE $00
lut_DlgHint7:   ; $71: "Astos stole it from Matoya"
  FFTEXT "With the CRYSTAL, even"
  .BYTE DLG_NL
  FFTEXT "the blind can see."
  .BYTE $00
lut_DlgHint8:   ; $76: "Coneria's Treasury safeguarded the use of TNT"
  FFTEXT "Old Nerrick needs TNT"
  .BYTE DLG_NL
  FFTEXT "for his canal."
  .BYTE $00
lut_DlgHint9:   ; $9F: "CANOE north, to the Ice Cave"
  FFTEXT "For ten years I searched"
  .BYTE DLG_NL
  FFTEXT "for the FLOATER."
  .BYTE $00
lut_DlgHint10:  ; $B0: "they tell of a cryptic stone plate"
  FFTEXT "Fables say that when"
  .BYTE DLG_NL
  FFTEXT "the shrine sank, many"
  .BYTE DLG_NL
  FFTEXT "treasures were lost."
  .BYTE $00
lut_DlgHint11:  ; $C6: "Only a fairy can draw OXYALE"
  FFTEXT "Only a fairy can draw"
  .BYTE DLG_NL
  FFTEXT "from the spring."
  .BYTE $00
lut_DlgHint12:  ; $C8: "and sold her to a caravan"
  FFTEXT "Hardy har, you are too"
  .BYTE DLG_NL
  FFTEXT "late! I BOTTLED the"
  .BYTE DLG_NL
  FFTEXT "fairy."
  .BYTE $00
lut_DlgHint13:  ; $DE: "escaped with a CUBE"
  FFTEXT "One of us escaped. He"
  .BYTE DLG_NL
  FFTEXT "floated far to the west."
  .BYTE $00

;  A dungeon's.  The Mirage Tower's "Everyone thinks the tower in Yahnikurm
;  Desert is a mirage" stays: it is the tower one sees, which stays put.
lut_DlgHint14:  ; $3F: "holds the Princess in a Temple to the northwest" (the user's line)
  FFTEXT "Garland has abducted"
  .BYTE DLG_NL
  FFTEXT "the Princess!"
  .BYTE $00
lut_DlgHint15:  ; $45: "take them to the Temple north of here"; shorter, the game's would not fit OPTDESC
  FFTEXT "The ORBS shine again!!"
  .BYTE DLG_NL
  FFTEXT "Take them to the Temple"
  .BYTE DLG_NL
  FFTEXT "and stand in the center."
  .BYTE $00
lut_DlgHint16:  ; $5B: "at the west end of the Aldi Sea"
  FFTEXT "The Cave of Dwarf is"
  .BYTE DLG_NL
  FFTEXT "home to a master smith."
  .BYTE $00
lut_DlgHint17:  ; $63: "Long ago I wandered to the Northwest"
  FFTEXT "Long ago I found an"
  .BYTE DLG_NL
  FFTEXT "ancient castle that was"
  .BYTE DLG_NL
  FFTEXT "so spooky, I left"
  .BYTE DLG_NL
  FFTEXT "immediately."
  .BYTE $00
lut_DlgHint18:  ; $7E: "on the peninsula southwest of this town"
  FFTEXT "The Earth Cave is the"
  .BYTE DLG_NL
  FFTEXT "source of the rot."
  .BYTE $00
lut_DlgHint19:  ; $82: "Pass through the Titan's Tunnel, then south"
  FFTEXT "Find Sarda, the Sage."
  .BYTE $00
lut_DlgHint20:  ; $C9: "the castle in the west"
  FFTEXT "Legends say that the"
  .BYTE DLG_NL
  FFTEXT "Castle of Ordeal is a"
  .BYTE DLG_NL
  FFTEXT "place to test courage."
  .BYTE $00
lut_DlgHint21:  ; $E7: "the Castle of Ordeal to the northeast"
  FFTEXT "We are going to the"
  .BYTE DLG_NL
  FFTEXT "Castle of Ordeal, to"
  .BYTE DLG_NL
  FFTEXT "bring back proof of our"
  .BYTE DLG_NL
  FFTEXT "courage."
  .BYTE $00

;  The way through one.
lut_DlgHint22:  ; $B8: "This is the Shrine's top floor ... KRAKEN lives on the bottom floor"
  FFTEXT "The FIEND of Water,"
  .BYTE DLG_NL
  FFTEXT "KRAKEN, lives in this"
  .BYTE DLG_NL
  FFTEXT "Shrine."
  .BYTE $00
lut_DlgHint23:  ; $D2: "The Mirage Tower is the entrance"
  FFTEXT "The FLOATING CASTLE"
  .BYTE DLG_DOTS, DLG_DOTS, DLG_NL
  FFTEXT "Our ancestors lived"
  .BYTE DLG_NL
  FFTEXT "there."
  .BYTE $00
lut_DlgHintEnd:

lut_DlgHintLo:
  .BYTE <lut_DlgHint0, <lut_DlgHint1, <lut_DlgHint2, <lut_DlgHint3, <lut_DlgHint4
  .BYTE <lut_DlgHint5, <lut_DlgHint6, <lut_DlgHint7, <lut_DlgHint8, <lut_DlgHint9
  .BYTE <lut_DlgHint10, <lut_DlgHint11, <lut_DlgHint12, <lut_DlgHint13
  .BYTE <lut_DlgHint14, <lut_DlgHint15, <lut_DlgHint16, <lut_DlgHint17
  .BYTE <lut_DlgHint18, <lut_DlgHint19, <lut_DlgHint20, <lut_DlgHint21
  .BYTE <lut_DlgHint22, <lut_DlgHint23
lut_DlgHintHi:
  .BYTE >lut_DlgHint0, >lut_DlgHint1, >lut_DlgHint2, >lut_DlgHint3, >lut_DlgHint4
  .BYTE >lut_DlgHint5, >lut_DlgHint6, >lut_DlgHint7, >lut_DlgHint8, >lut_DlgHint9
  .BYTE >lut_DlgHint10, >lut_DlgHint11, >lut_DlgHint12, >lut_DlgHint13
  .BYTE >lut_DlgHint14, >lut_DlgHint15, >lut_DlgHint16, >lut_DlgHint17
  .BYTE >lut_DlgHint18, >lut_DlgHint19, >lut_DlgHint20, >lut_DlgHint21
  .BYTE >lut_DlgHint22, >lut_DlgHint23
.assert * - lut_DlgHintLo = 2 * DLG_NHINT, error, "a hint without its line"
;  The longest lines, Astos's and the spooky castle's, fit OPTDESC with
;  room (test_rando_dialogue reads every one back).
.assert lut_DlgHint1 - lut_DlgHint0 <= OPTDESC_MAX, error, "a hint's line overflows OPTDESC"
.assert lut_DlgHint18 - lut_DlgHint17 <= OPTDESC_MAX, error, "a hint's line overflows OPTDESC"
