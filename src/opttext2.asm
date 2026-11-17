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
.export lut_Desc_114, lut_Desc_115, lut_Desc_116
.export lut_Desc_103            ; the Goal's, moved from the first bank (2026-11-06)

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

lut_Desc_113:  ; Palette swap (draft, 2026-11-03; the user, 2026-11-05: the line "Each seed has its own." out)
  FFLINES 2
  FFPAD {"Maps take on new colors,"}, 28
  FFPAD {"and enemies trade colors."}, 28

lut_Desc_114:  ; Exploding Dwarf (draft, 2026-11-03)
  FFLINES 3
  FFPAD {"The Hurray dwarf in the"}, 28
  FFPAD {"Dwarf Cave explodes when"}, 28
  FFPAD {"you talk to him."}, 28

lut_Desc_115:  ; Graphics (draft, 2026-11-14)
  FFLINES 3
  FFPAD {"Japan shows the graphics the"}, 28
  FFPAD {"Japanese release had before"}, 28
  FFPAD {"the US release changed them."}, 28

lut_Desc_116:  ; Save on game over, by value (user, 2026-11-17)
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_116_0, lut_Desc_116_1, lut_Desc_116_2
  .assert * - lut_Desc_116 = 1 + 2 * GAMEOVER_MODES, error, "one Save on game over description per mode"

lut_Desc_116_0:  ; Save on game over: Off
  FFLINES 3
  FFPAD {"When the party falls, the"}, 28
  FFPAD {"game ends. Continue goes"}, 28
  FFPAD {"back to the last save."}, 28

lut_Desc_116_1:  ; Save on game over: On
  FFLINES 5
  FFPAD {"When the party falls, the"}, 28
  FFPAD {"game is saved with everyone"}, 28
  FFPAD {"revived and nothing lost."}, 28
  FFPAD {"The party wakes at the last"}, 28
  FFPAD {"save point."}, 28

lut_Desc_116_2:  ; Save on game over: DW
  FFLINES 5
  FFPAD {"On game over, the party"}, 28
  FFPAD {"wakes at Coneria with half"}, 28
  FFPAD {"its gold, as in Dragon"}, 28
  FFPAD {"Warrior. The ship and"}, 28
  FFPAD {"airship are brought along."}, 28

lut_Desc_103:  ; Goal, by value (here since Shard Hunt filled the first bank)
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_103_0, lut_Desc_103_1, lut_Desc_103_2, lut_Desc_103_3, lut_Desc_103_4
  .WORD lut_Desc_103_5, lut_Desc_103_6, lut_Desc_103_7, lut_Desc_103_8, lut_Desc_103_9, lut_Desc_103_10
  .assert * - lut_Desc_103 = 1 + 2 * GOAL_MODES, error, "one Goal description per goal"

lut_Desc_103_0:  ; Goal: 4 orbs
  FFLINES 3
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"all four ORBS are lit, as it"}, 28
  FFPAD {"always has."}, 28

lut_Desc_103_1:  ; Goal: 3 orbs
  FFLINES 3
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"any three ORBS are lit, so"}, 28
  FFPAD {"one fiend may be left alone."}, 28

lut_Desc_103_2:  ; Goal: 2 orbs
  FFLINES 3
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"any two ORBS are lit, so two"}, 28
  FFPAD {"fiends may be left alone."}, 28

lut_Desc_103_3:  ; Goal: 1 orb
  FFLINES 2
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"any one ORB is lit."}, 28

lut_Desc_103_4:  ; Goal: 0 orbs
  FFLINES 3
  FFPAD {"The black ORB gives way at"}, 28
  FFPAD {"once. Chaos needs only the"}, 28
  FFPAD {"KEY and the LUTE."}, 28

lut_Desc_103_5:  ; Goal: 16 shards (Shard Hunt; draft, 2026-11-06)
  FFLINES 4
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"16 SHARDS are found. 32 are"}, 28
  FFPAD {"in treasure, and each fiend"}, 28
  FFPAD {"gives 2 or 4 more."}, 28

lut_Desc_103_6:  ; Goal: 20 shards (Shard Hunt; draft, 2026-11-06)
  FFLINES 4
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"20 SHARDS are found. 32 are"}, 28
  FFPAD {"in treasure, and each fiend"}, 28
  FFPAD {"gives 2 or 4 more."}, 28

lut_Desc_103_7:  ; Goal: 24 shards (Shard Hunt; draft, 2026-11-06)
  FFLINES 4
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"24 SHARDS are found. 32 are"}, 28
  FFPAD {"in treasure, and each fiend"}, 28
  FFPAD {"gives 2 or 4 more."}, 28

lut_Desc_103_8:  ; Goal: 28 shards (Shard Hunt; draft, 2026-11-06)
  FFLINES 4
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"28 SHARDS are found. 32 are"}, 28
  FFPAD {"in treasure, and each fiend"}, 28
  FFPAD {"gives 2 or 4 more."}, 28

lut_Desc_103_9:  ; Goal: 32 shards (Shard Hunt; draft, 2026-11-06)
  FFLINES 4
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"32 SHARDS are found. 32 are"}, 28
  FFPAD {"in treasure, and each fiend"}, 28
  FFPAD {"gives 2 or 4 more."}, 28

lut_Desc_103_10:  ; Goal: 36 shards (Shard Hunt; draft, 2026-11-06)
  FFLINES 4
  FFPAD {"The black ORB gives way once"}, 28
  FFPAD {"36 SHARDS are found. 32 are"}, 28
  FFPAD {"in treasure, and each fiend"}, 28
  FFPAD {"gives 2 or 4 more."}, 28
