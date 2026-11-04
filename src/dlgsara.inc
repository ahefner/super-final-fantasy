;  dlgsara.inc -- Rebellious Princess's lines (user, 2026-11-02,
;  rebellious-princess.txt): the kidnapped princess's at each of her spots
;  but Garland's, and Garland's when she is not there.  rando_dlgtext swaps
;  them in for dialogue $05 and $04, built in OPTDESC; Garland's runs past
;  its $50, into the description scratch after it, which nothing uses on a
;  map (OPTDLG_MAX).  Included by world.asm; in its chunk, for room.

lut_SaraLineLo: .BYTE 0, <lut_SaraLine1, <lut_SaraLine2, <lut_SaraLine3, <lut_SaraLine4, <lut_SaraLine5, <lut_SaraLine6, <lut_SaraLine7
lut_SaraLineHi: .BYTE 0, >lut_SaraLine1, >lut_SaraLine2, >lut_SaraLine3, >lut_SaraLine4, >lut_SaraLine5, >lut_SaraLine6, >lut_SaraLine7

lut_SaraLine1:  ; Dwarf Cave
  FFTEXT "Aww, daddy doesn't let"
  .BYTE DLG_NL
  FFTEXT "me have any fun!"
  .BYTE $00
lut_SaraLine2:  ; Elfland Castle
  FFTEXT "I came to care for the"
  .BYTE DLG_NL
  FFTEXT "Elven prince. Must I"
  .BYTE DLG_NL
  FFTEXT "return home?"
  .BYTE $00
lut_SaraLine3:  ; Crescent Lake
  FFTEXT "That old castle is so"
  .BYTE DLG_NL
  FFTEXT "boring! Let's dance!"
  .BYTE $00
lut_SaraLine4:  ; Sarda's Cave
  FFTEXT "Uncle Sarda tells the"
  .BYTE DLG_NL
  FFTEXT "best stories!"
  .BYTE $00
lut_SaraLine5:  ; Cardia
  FFTEXT "Please, I don't want to"
  .BYTE DLG_NL
  FFTEXT "go home! I like it here!"
  .BYTE $00
lut_SaraLine6:  ; Pravoka
  FFTEXT "Mr. Bikke was teaching"
  .BYTE DLG_NL
  FFTEXT "me to play the LUTE!"
  .BYTE $00
lut_SaraLine7:  ; Melmond
  FFTEXT "Am I needed at home? I"
  .BYTE DLG_NL
  FFTEXT "came to help the people"
  .BYTE DLG_NL
  FFTEXT "of Melmond rebuild."
  .BYTE $00
lut_GarlandLine:  ; Garland, with the princess elsewhere
  FFTEXT "The king is a fool! I"
  .BYTE DLG_NL
  FFTEXT "would never lay a hand"
  .BYTE DLG_NL
  FFTEXT "upon the young lady. How"
  .BYTE DLG_NL
  FFTEXT "dare you besmirch my"
  .BYTE DLG_NL
  FFTEXT "honor!"
  .BYTE $00
lut_SaraLineEnd:

.assert lut_SaraLine2 - lut_SaraLine1 <= OPTDLG_MAX, error, "a princess's line overflows OPTDESC"
.assert lut_GarlandLine - lut_SaraLine7 <= OPTDLG_MAX, error, "a princess's line overflows OPTDESC"
.assert lut_SaraLineEnd - lut_GarlandLine <= OPTDLG_MAX, error, "Garland's line overflows OPTDESC"
