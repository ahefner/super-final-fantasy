; ---------------------------------------------------------------------------
;  opttext2.asm -- the settings screen's descriptions, past the first bank's
;
;  Chunk CHUNK_OPTTEXT2, data only: opttext.asm's bank filled with Party's
;  (2026-11-02).  A row's pointer in lut_DescHi is DESC_SECOND over its
;  record's to send opt_menu_descptr here, which then reads with DBR = this
;  chunk; a DESC_BYVALUE table here points at records here.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "fftext.inc"
.include "optmenu.inc"

.export lut_Desc_109, lut_Desc_110, lut_Desc_111, lut_Desc_112, lut_Desc_113
.export lut_Desc_114

.segment "BANK_OPTTEXT2"

lut_Desc_109:  ; Taverns, by value (the user's words, 2026-11-02)
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_109_0, lut_Desc_109_1, lut_Desc_109_2
  .assert * - lut_Desc_109 = 1 + 2 * TAVERNS_MODES, error, "one description per Taverns mode"

lut_Desc_109_0:  ; Taverns: Off
  FFLINES 2
  FFPAD {"Clinics revive fallen party"}, 28
  FFPAD {"members."}, 28

lut_Desc_109_1:  ; Taverns: Recruit
  FFLINES 3
  FFPAD {"Clinics become pubs, where"}, 28
  FFPAD {"new party members can be"}, 28
  FFPAD {"recruited."}, 28

lut_Desc_109_2:  ; Taverns: Replace
  FFLINES 2
  FFPAD {"Recruits may replace"}, 28
  FFPAD {"existing party members."}, 28

lut_Desc_110:  ; Rebellious Princess, by value (drafts, 2026-11-02)
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_110_0, lut_Desc_110_1
  .assert * - lut_Desc_110 = 1 + 2 * PRINCESS_MODES, error, "one description per Rebellious Princess mode"

lut_Desc_110_0:  ; Rebellious Princess: Off
  FFLINES 2
  FFPAD {"Garland holds the princess"}, 28
  FFPAD {"in the Temple of Fiends."}, 28

lut_Desc_110_1:  ; Rebellious Princess: On
  FFLINES 3
  FFPAD {"The princess has run away"}, 28
  FFPAD {"from home. She may be found"}, 28
  FFPAD {"in one of several places."}, 28

lut_Desc_111:  ; FUN%: the user's words for the section (fun-percent.txt)
  FFLINES 3
  FFPAD {"Goofy settings that don't"}, 28
  FFPAD {"change anything about"}, 28
  FFPAD {"gameplay."}, 28

lut_Desc_112:  ; Stereo Sound: the user's words
  FFLINES 1
  FFPAD {"In Stereo For Her Pleasure"}, 28

lut_Desc_113:  ; Palette swap (draft, 2026-11-03)
  FFLINES 3
  FFPAD {"Maps take on new colors,"}, 28
  FFPAD {"and enemies trade colors."}, 28
  FFPAD {"Each seed has its own."}, 28

lut_Desc_114:  ; Exploding Dwarf (draft, 2026-11-03)
  FFLINES 3
  FFPAD {"The Hurray dwarf in the"}, 28
  FFPAD {"Dwarf Cave explodes when"}, 28
  FFPAD {"you talk to him."}, 28
