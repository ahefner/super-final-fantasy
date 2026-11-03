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

.export lut_Desc_109

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
