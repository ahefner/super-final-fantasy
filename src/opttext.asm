; ---------------------------------------------------------------------------
;  opttext.asm -- the settings screen's descriptions.
;
;  Chunk CHUNK_OPTTEXT, data only.  The text was 53% of the options chunk and
;  the rest of it was running out; the menu code stays there and
;  opt_menu_desc points the data bank here while it reads.  Everything in this
;  file is reached that way, by absolute address with DBR = this chunk, so it
;  must hold nothing that is reached any other way.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "fftext.inc"
.include "optmenu.inc"

.export lut_DescLo, lut_DescHi

.segment "BANK_OPTTEXT"

;  The description pane text, pre-wrapped to 28 columns and 5 lines.
;  Wrapping at build time rather than at runtime keeps the draw to five fixed
;  blits and keeps the wording under review in the source.

lut_DescBlank:
  FFLINES 0


lut_Desc_0:  ; QUALITY OF LIFE
  FFLINES 3
  .BYTE $8C, $B2, $B1, $B9, $A8, $B1, $AC, $A8, $B1, $A6, $A8, $FF, $A6, $AB, $A4, $B1, $AA, $A8, $B6, $C0, $FF, $97, $B2, $B1, $A8, $FF, $B2, $A9
  .BYTE $B7, $AB, $A8, $B6, $A8, $FF, $A4, $AF, $B7, $A8, $B5, $FF, $AB, $B2, $BA, $FF, $B7, $AB, $A8, $FF, $AA, $A4, $B0, $A8, $FF, $FF, $FF, $FF
  .BYTE $B3, $AF, $A4, $BC, $B6, $FF, $B2, $B8, $B7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_1:  ; BUGFIXES
  FFLINES 2
  .BYTE $8C, $B2, $B5, $B5, $A8, $A6, $B7, $AC, $B2, $B1, $B6, $FF, $B7, $B2, $FF, $B0, $AC, $B6, $B7, $A4, $AE, $A8, $B6, $FF, $AC, $B1, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $B2, $B5, $AC, $AA, $AC, $B1, $A4, $AF, $FF, $AA, $A4, $B0, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_2:  ; VARIATIONS
  FFLINES 2
  .BYTE $8C, $AB, $A4, $B1, $AA, $A8, $B6, $FF, $B7, $AB, $A4, $B7, $FF, $A7, $A8, $AF, $AC, $A5, $A8, $B5, $A4, $B7, $A8, $AF, $BC, $FF, $FF, $FF
  .BYTE $A4, $AF, $B7, $A8, $B5, $FF, $AB, $B2, $BA, $FF, $B7, $AB, $A8, $FF, $AA, $A4, $B0, $A8, $FF, $B3, $AF, $A4, $BC, $B6, $C0, $FF, $FF, $FF

lut_Desc_3:  ; Speed hacks
  FFLINES 3
  .BYTE $8A, $B5, $A8, $A4, $FF, $B7, $B5, $A4, $B1, $B6, $AC, $B7, $AC, $B2, $B1, $B6, $BF, $FF, $B0, $A8, $B1, $B8, $B6, $BF, $FF, $FF, $FF, $FF
  .BYTE $A5, $A4, $B7, $B7, $AF, $A8, $FF, $A5, $B2, $BB, $A8, $B6, $FF, $A4, $B1, $A7, $FF, $A4, $B1, $AC, $B0, $A4, $B7, $AC, $B2, $B1, $B6, $FF
  .BYTE $A4, $AF, $AF, $FF, $B5, $B8, $B1, $FF, $A9, $A4, $B6, $B7, $A8, $B5, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_4:  ; Faster walking
  FFLINES 3
  .BYTE $A0, $A4, $AF, $AE, $AC, $B1, $AA, $FF, $A4, $B1, $A7, $FF, $A6, $A4, $B1, $B2, $A8, $FF, $B6, $B3, $A8, $A8, $A7, $FF, $AC, $B6, $FF, $FF
  .BYTE $A7, $B2, $B8, $A5, $AF, $A8, $A7, $C0, $FF, $91, $B2, $AF, $A7, $FF, $8B, $FF, $B7, $B2, $FF, $B0, $B2, $B9, $A8, $FF, $A4, $B7, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $B2, $B5, $AC, $AA, $AC, $B1, $A4, $AF, $FF, $B3, $A4, $A6, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_5:  ; Faster ship
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $B6, $AB, $AC, $B3, $FF, $B6, $A4, $AC, $AF, $B6, $FF, $A4, $B6, $FF, $A9, $A4, $B6, $B7, $FF, $A4, $B6, $FF, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $A4, $AC, $B5, $B6, $AB, $AC, $B3, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_6:  ; No party shuffle
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $B3, $A4, $B5, $B7, $BC, $FF, $AC, $B6, $FF, $B1, $B2, $B7, $FF, $B5, $A8, $A4, $B5, $B5, $A4, $B1, $AA, $A8, $A7, $FF
  .BYTE $BA, $AB, $A8, $B1, $FF, $A4, $FF, $A6, $AB, $A4, $B5, $A4, $A6, $B7, $A8, $B5, $FF, $A9, $A4, $AF, $AF, $B6, $C0, $FF, $FF, $FF, $FF, $FF

lut_Desc_7:  ; Identify treasures
  FFLINES 2
  .BYTE $8A, $FF, $A9, $B8, $AF, $AF, $FF, $AC, $B1, $B9, $A8, $B1, $B7, $B2, $B5, $BC, $FF, $B6, $B7, $AC, $AF, $AF, $FF, $B7, $A8, $AF, $AF, $B6
  .BYTE $BC, $B2, $B8, $FF, $BA, $AB, $A4, $B7, $FF, $BA, $A4, $B6, $FF, $AC, $B1, $FF, $B7, $AB, $A8, $FF, $A6, $AB, $A8, $B6, $B7, $C0, $FF, $FF

lut_Desc_8:  ; Chests appear opened
  FFLINES 3
  .BYTE $8C, $AB, $A8, $B6, $B7, $B6, $FF, $BC, $B2, $B8, $FF, $AB, $A4, $B9, $A8, $FF, $A4, $AF, $B5, $A8, $A4, $A7, $BC, $FF, $FF, $FF, $FF, $FF
  .BYTE $AF, $B2, $B2, $B7, $A8, $A7, $FF, $AF, $B2, $B2, $AE, $FF, $B2, $B3, $A8, $B1, $C0, $FF, $8A, $B3, $B3, $AF, $AC, $A8, $B6, $FF, $FF, $FF
  .BYTE $B7, $B2, $FF, $A4, $B1, $FF, $A8, $BB, $AC, $B6, $B7, $AC, $B1, $AA, $FF, $B6, $A4, $B9, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_9:  ; Buy quantity
  FFLINES 3
  .BYTE $8C, $AB, $B2, $B2, $B6, $A8, $FF, $AB, $B2, $BA, $FF, $B0, $A4, $B1, $BC, $FF, $B2, $A9, $FF, $A4, $B1, $FF, $AC, $B7, $A8, $B0, $FF, $FF
  .BYTE $B7, $B2, $FF, $A5, $B8, $BC, $BF, $FF, $AC, $B1, $B6, $B7, $A8, $A4, $A7, $FF, $B2, $A9, $FF, $B2, $B1, $A8, $FF, $A4, $B7, $FF, $FF, $FF
  .BYTE $A4, $FF, $B7, $AC, $B0, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_10:  ; Run becomes Wait
  FFLINES 3
  .BYTE $A0, $AB, $A8, $B1, $FF, $A4, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $FF, $A6, $A4, $B1, $B1, $B2, $B7, $FF, $A5, $A8, $FF, $FF, $FF, $FF, $FF
  .BYTE $A8, $B6, $A6, $A4, $B3, $A8, $A7, $BF, $FF, $9B, $9E, $97, $FF, $B5, $A8, $A4, $A7, $B6, $FF, $A0, $8A, $92, $9D, $FF, $A4, $B1, $A7, $FF
  .BYTE $B6, $A4, $BC, $B6, $FF, $B6, $B2, $FF, $B3, $AF, $A4, $AC, $B1, $AF, $BC, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_11:  ; Magic menu wraparound
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $FF, $B0, $A4, $AA, $AC, $A6, $FF, $A6, $B8, $B5, $B6, $B2, $B5, $FF, $FF, $FF, $FF, $FF
  .BYTE $BA, $B5, $A4, $B3, $B6, $FF, $A9, $B5, $B2, $B0, $FF, $A5, $B2, $B7, $B7, $B2, $B0, $FF, $B7, $B2, $FF, $B7, $B2, $B3, $C0, $FF, $FF, $FF

lut_Desc_12:  ; Auto retargeting
  FFLINES 3
  .BYTE $8A, $B7, $B7, $A4, $A6, $AE, $B6, $FF, $A4, $B1, $A7, $FF, $B6, $B3, $A8, $AF, $AF, $B6, $FF, $A4, $AC, $B0, $A8, $A7, $FF, $A4, $B7, $FF
  .BYTE $A4, $FF, $A7, $A8, $A4, $A7, $FF, $A8, $B1, $A8, $B0, $BC, $FF, $B3, $AC, $A6, $AE, $FF, $A4, $FF, $AF, $AC, $B9, $AC, $B1, $AA, $FF, $FF
  .BYTE $B2, $B1, $A8, $FF, $AC, $B1, $B6, $B7, $A8, $A4, $A7, $FF, $B2, $A9, $FF, $A5, $A8, $AC, $B1, $AA, $FF, $BA, $A4, $B6, $B7, $A8, $A7, $C0

lut_Desc_13:  ; Autosort inventory
  FFLINES 3
  .BYTE $91, $8E, $8A, $95, $BF, $FF, $99, $9E, $9B, $8E, $FF, $A4, $B1, $A7, $FF, $9C, $98, $8F, $9D, $FF, $B3, $B2, $B7, $AC, $B2, $B1, $B6, $FF
  .BYTE $A4, $B5, $A8, $FF, $AE, $A8, $B3, $B7, $FF, $A4, $B7, $FF, $B7, $AB, $A8, $FF, $B7, $B2, $B3, $FF, $B2, $A9, $FF, $B7, $AB, $A8, $FF, $FF
  .BYTE $AC, $B7, $A8, $B0, $FF, $AF, $AC, $B6, $B7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_14:  ; Repeated potion use
  FFLINES 2
  .BYTE $9E, $B6, $A8, $FF, $B6, $A8, $B9, $A8, $B5, $A4, $AF, $FF, $B3, $B2, $B7, $AC, $B2, $B1, $B6, $FF, $AC, $B1, $FF, $A4, $FF, $B5, $B2, $BA
  .BYTE $BA, $AC, $B7, $AB, $B2, $B8, $B7, $FF, $B5, $A8, $B2, $B3, $A8, $B1, $AC, $B1, $AA, $FF, $B7, $AB, $A8, $FF, $B0, $A8, $B1, $B8, $C0, $FF

lut_Desc_15:  ; Shop information
  FFLINES 3
  .BYTE $9C, $AB, $B2, $B3, $B6, $FF, $B6, $AB, $B2, $BA, $FF, $BA, $AB, $A8, $B7, $AB, $A8, $B5, $FF, $A8, $A4, $A6, $AB, $FF, $FF, $FF, $FF, $FF
  .BYTE $A6, $AB, $A4, $B5, $A4, $A6, $B7, $A8, $B5, $FF, $A6, $A4, $B1, $FF, $A8, $B4, $B8, $AC, $B3, $FF, $A4, $B1, $FF, $AC, $B7, $A8, $B0, $FF
  .BYTE $A4, $B1, $A7, $FF, $BA, $AB, $A4, $B7, $FF, $AC, $B7, $FF, $BA, $B2, $B8, $AF, $A7, $FF, $A7, $B2, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_16:  ; Chest information
  FFLINES 2
  .BYTE $98, $B3, $A8, $B1, $AC, $B1, $AA, $FF, $A4, $FF, $A6, $AB, $A8, $B6, $B7, $FF, $A7, $A8, $B6, $A6, $B5, $AC, $A5, $A8, $B6, $FF, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $BA, $A8, $A4, $B3, $B2, $B1, $FF, $B2, $B5, $FF, $A4, $B5, $B0, $B2, $B8, $B5, $FF, $AC, $B1, $FF, $AC, $B7, $C0, $FF

lut_Desc_17:  ; NPC guillotine
  FFLINES 2
  .BYTE $9D, $A4, $AF, $AE, $AC, $B1, $AA, $FF, $B7, $B2, $FF, $A4, $B1, $FF, $B2, $B5, $A7, $AC, $B1, $A4, $B5, $BC, $FF, $97, $99, $8C, $FF, $FF
  .BYTE $B5, $A8, $B0, $B2, $B9, $A8, $B6, $FF, $AC, $B7, $FF, $A9, $B5, $B2, $B0, $FF, $B7, $AB, $A8, $FF, $B0, $A4, $B3, $C0, $FF, $FF, $FF, $FF

lut_Desc_18:  ; House restoration
  FFLINES 4
  FFPAD {"HOUSEs restore all HP, not"}, 28
  FFPAD {"120, and restore MP whether"}, 28
  FFPAD {"or not you save -- which the"}, 28
  FFPAD {"save then records."}, 28

lut_Desc_19:  ; Weapon stats
  FFLINES 5
  FFPAD {"Fixes critical hit rates,"}, 28
  FFPAD {"which vanilla reads from a"}, 28
  FFPAD {"weapon's place in the list,"}, 28
  FFPAD {"and elemental and creature"}, 28
  FFPAD {"bonuses that never applied."}, 28

lut_Desc_20:  ; Spell fixes
  FFLINES 3
  .BYTE $8C, $B2, $B5, $B5, $A8, $A6, $B7, $B6, $FF, $95, $98, $8C, $94, $BF, $FF, $95, $98, $94, $82, $BF, $FF, $91, $8E, $95, $82, $BF, $FF, $FF
  .BYTE $9D, $96, $99, $9B, $BF, $FF, $9C, $8A, $8B, $9B, $FF, $A4, $B1, $A7, $FF, $8C, $9E, $9B, $84, $BF, $FF, $BA, $AB, $AC, $A6, $AB, $FF, $FF
  .BYTE $A7, $AC, $A7, $FF, $B1, $B2, $B7, $FF, $BA, $B2, $B5, $AE, $FF, $A4, $B6, $FF, $A7, $A8, $B6, $A6, $B5, $AC, $A5, $A8, $A7, $C0, $FF, $FF

lut_Desc_21:  ; Enemy status attacks
  FFLINES 3
  .BYTE $8F, $AC, $BB, $A8, $B6, $FF, $A8, $B1, $A8, $B0, $AC, $A8, $B6, $FF, $AC, $B1, $A9, $AF, $AC, $A6, $B7, $AC, $B1, $AA, $FF, $A4, $FF, $FF
  .BYTE $B6, $B7, $A4, $B7, $B8, $B6, $FF, $A4, $AC, $AF, $B0, $A8, $B1, $B7, $FF, $BA, $AC, $B7, $AB, $FF, $A4, $B7, $B7, $A4, $A6, $AE, $B6, $FF
  .BYTE $B7, $AB, $A4, $B7, $FF, $B6, $AB, $B2, $B8, $AF, $A7, $FF, $B1, $B2, $B7, $FF, $A6, $A4, $B5, $B5, $BC, $FF, $B2, $B1, $A8, $C0, $FF, $FF

lut_Desc_22:  ; Gold and XP
  FFLINES 3
  .BYTE $9C, $A6, $A4, $AF, $A8, $B6, $FF, $B7, $AB, $A8, $FF, $AA, $B2, $AF, $A7, $FF, $A4, $B1, $A7, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $A8, $BB, $B3, $A8, $B5, $AC, $A8, $B1, $A6, $A8, $FF, $B7, $AB, $A4, $B7, $FF, $A8, $B9, $A8, $B5, $BC, $FF, $A5, $A4, $B7, $B7, $AF, $A8
  .BYTE $A4, $BA, $A4, $B5, $A7, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_23:  ; Encounter rate
  FFLINES 3
  .BYTE $91, $B2, $BA, $FF, $B2, $A9, $B7, $A8, $B1, $FF, $B5, $A4, $B1, $A7, $B2, $B0, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $B6, $FF, $FF, $FF, $FF
  .BYTE $AB, $A4, $B3, $B3, $A8, $B1, $BF, $FF, $A4, $B6, $FF, $A4, $FF, $B6, $AB, $A4, $B5, $A8, $FF, $B2, $A9, $FF, $B7, $AB, $A8, $FF, $FF, $FF
  .BYTE $B2, $B5, $AC, $AA, $AC, $B1, $A4, $AF, $FF, $B2, $B9, $A8, $B5, $BA, $B2, $B5, $AF, $A7, $FF, $B5, $A4, $B7, $A8, $C0, $FF, $FF, $FF, $FF

lut_Desc_24:  ; Enemy stats
  FFLINES 3
  .BYTE $9C, $A6, $A4, $AF, $A8, $B6, $FF, $91, $99, $BF, $FF, $A7, $A4, $B0, $A4, $AA, $A8, $BF, $FF, $A7, $A8, $A9, $A8, $B1, $A6, $A8, $FF, $FF
  .BYTE $A4, $B1, $A7, $FF, $A4, $A6, $A6, $B8, $B5, $A4, $A6, $BC, $FF, $A9, $B2, $B5, $FF, $B2, $B5, $A7, $AC, $B1, $A4, $B5, $BC, $FF, $FF, $FF
  .BYTE $A8, $B1, $A8, $B0, $AC, $A8, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_25:  ; Boss stats
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $B6, $A4, $B0, $A8, $BF, $FF, $A9, $B2, $B5, $FF, $B7, $AB, $A8, $FF, $B7, $AB, $AC, $B5, $B7, $A8, $A8, $B1, $FF, $FF
  .BYTE $A5, $B2, $B6, $B6, $A8, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_26:  ; Better Thief and Ninja
  FFLINES 4
  FFPAD {"The Thief starts with 80"}, 28
  FFPAD {"agility, not 10, and gains"}, 28
  FFPAD {"it every level, not one in"}, 28
  FFPAD {"four. A Ninja keeps both."}, 28

lut_Desc_27:  ; Double weapon crit
  FFLINES 5
  FFPAD {"Doubles every weapon's"}, 28
  FFPAD {"critical hit rate.  Needs"}, 28
  FFPAD {"Weapon Stats, without which"}, 28
  FFPAD {"the game never reads that"}, 28
  FFPAD {"number at all."}, 28

lut_Desc_28:  ; Elemental bonus
  FFLINES 5
  FFPAD {"Damage added when an attack"}, 28
  FFPAD {"matches a weakness. Vanilla"}, 28
  FFPAD {"is +4. Needs Weapon stats on"}, 28
  FFPAD {"or only monsters get it -"}, 28
  FFPAD {"party weapon element is 0."}, 28

lut_Desc_29:  ; Improved Cure spells
  FFLINES 4
  .BYTE $8C, $9E, $9B, $8E, $B6, $FF, $B5, $A8, $B6, $B7, $B2, $B5, $A8, $FF, $B7, $BA, $AC, $A6, $A8, $FF, $A4, $B6, $FF, $B0, $B8, $A6, $AB, $FF
  .BYTE $A4, $B1, $A7, $FF, $91, $8E, $8A, $95, $B6, $FF, $A6, $B2, $B9, $A8, $B5, $FF, $A4, $FF, $BA, $AC, $A7, $A8, $B5, $FF, $FF, $FF, $FF, $FF
  .BYTE $B5, $A4, $B1, $AA, $A8, $C0, $FF, $FF, $95, $8A, $96, $99, $FF, $A4, $B1, $A7, $FF, $8A, $96, $9E, $9D, $FF, $A4, $AF, $B6, $B2, $FF, $FF
  .BYTE $A6, $B8, $B5, $A8, $FF, $B3, $A4, $B5, $A4, $AF, $BC, $B6, $AC, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_30:  ; Improved Fire spells
  FFLINES 4
  .BYTE $8F, $92, $9B, $8E, $BF, $FF, $95, $92, $9D, $FF, $A4, $B1, $A7, $FF, $92, $8C, $8E, $FF, $AB, $AC, $B7, $FF, $A4, $B6, $FF, $FF, $FF, $FF
  .BYTE $AB, $A4, $B5, $A7, $FF, $A4, $B6, $FF, $B7, $AB, $A8, $AC, $B5, $FF, $B7, $AC, $A8, $B5, $C2, $83, $FF, $A9, $B2, $B5, $B0, $B6, $C0, $FF
  .BYTE $91, $8A, $9B, $96, $FF, $AB, $AC, $B7, $B6, $FF, $AB, $A4, $B5, $A7, $A8, $B5, $FF, $A4, $B1, $A7, $FF, $B6, $B7, $B5, $AC, $AE, $A8, $B6
  .BYTE $A4, $FF, $B6, $AC, $B1, $AA, $AF, $A8, $FF, $B7, $A4, $B5, $AA, $A8, $B7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_63:  ; SOFT in battle
  FFLINES 4
  FFPAD {"The SOFT spell and the SOFT"}, 28
  FFPAD {"potion cure stone in battle."}, 28
  FFPAD {"DRINK offers SOFT as a third"}, 28
  FFPAD {"potion."}, 28

lut_Desc_64:  ; White Mage HARM
  FFLINES 5
  FFPAD {"A White Mage's or Wizard's"}, 28
  FFPAD {"HARM spells hurt anything,"}, 28
  FFPAD {"not only the undead, though"}, 28
  FFPAD {"the living almost never take"}, 28
  FFPAD {"double."}, 28

lut_Desc_65:  ; Run chance fix
  FFLINES 5
  FFPAD {"Running away weighs luck"}, 28
  FFPAD {"against the runner's level,"}, 28
  FFPAD {"as the game meant to.  The"}, 28
  FFPAD {"original read a stray byte"}, 28
  FFPAD {"instead."}, 28

lut_Desc_66:  ; Turn order fix
  FFLINES 5
  FFPAD {"Each round's turn order is"}, 28
  FFPAD {"shuffled fairly.  The"}, 28
  FFPAD {"original's swaps left a"}, 28
  FFPAD {"party member last in over"}, 28
  FFPAD {"half the rounds."}, 28

lut_Desc_67:  ; TRANCE status element
  FFLINES 4
  FFPAD {"TRANCE, the enemy skill that"}, 28
  FFPAD {"paralyzes the whole party,"}, 28
  FFPAD {"has the status element, so a"}, 28
  FFPAD {"Ribbon resists it."}, 28

lut_Desc_97:  ; NUKE Stick
  FFLINES 4
  FFPAD {"The Wizard Staff becomes the"}, 28
  FFPAD {"NUKE Stick, casting NUKE"}, 28
  FFPAD {"when used in battle instead"}, 28
  FFPAD {"of CONF."}, 28

lut_Desc_95:  ; RUSE Staff
  FFLINES 4
  FFPAD {"The Power Staff becomes the"}, 28
  FFPAD {"Ruse Staff, casting RUSE"}, 28
  FFPAD {"when used in battle like the"}, 28
  FFPAD {"Defense sword."}, 28

lut_Desc_96:  ; Boss tactics, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_96_0, lut_Desc_96_1, lut_Desc_96_2
  .assert * - lut_Desc_96 = 1 + 2 * BOSSAI_MODES, error, "one Boss tactics description per mode"

lut_Desc_96_0:  ; Boss tactics: Off
  FFLINES 5
  FFPAD {"Bosses aim as any enemy"}, 28
  FFPAD {"does, at the first in line"}, 28
  FFPAD {"half the time, the second a"}, 28
  FFPAD {"quarter, the last two an"}, 28
  FFPAD {"eighth each."}, 28

lut_Desc_96_1:  ; Boss tactics: Clever
  FFLINES 5
  FFPAD {"Bosses keep their script's"}, 28
  FFPAD {"pace, but pick the spell or"}, 28
  FFPAD {"skill, and the target, that"}, 28
  FFPAD {"hurts most, each slot of it"}, 28
  FFPAD {"once in eight turns."}, 28

lut_Desc_96_2:  ; Boss tactics: Ruthless
  FFLINES 5
  FFPAD {"Bosses weigh every action"}, 28
  FFPAD {"they have, every turn, and"}, 28
  FFPAD {"take the best, each slot of"}, 28
  FFPAD {"their script once in eight"}, 28
  FFPAD {"turns."}, 28

lut_Desc_92:  ; Asshat Octopus
  FFLINES 3
  FFPAD {"Kraken always targets your"}, 28
  FFPAD {"White Mage or White Wizard"}, 28
  FFPAD {"before other party members."}, 28

lut_Desc_69:  ; Lefein Inn and Clinic
  FFLINES 2
  FFPAD {"Lefein gets an Inn and a"}, 28
  FFPAD {"Clinic."}, 28

lut_Desc_70:  ; Lefein SuperStore
  FFLINES 4
  FFPAD {"Lefein's magic shop grows a"}, 28
  FFPAD {"door to every town's white"}, 28
  FFPAD {"and black magic shops, but"}, 28
  FFPAD {"Gaia's next door."}, 28

lut_Desc_31:  ; Cast Life in battle
  FFLINES 3
  .BYTE $95, $92, $8F, $8E, $FF, $A4, $B1, $A7, $FF, $95, $92, $8F, $82, $FF, $A6, $A4, $B1, $FF, $A5, $A8, $FF, $B8, $B6, $A8, $A7, $FF, $FF, $FF
  .BYTE $A7, $B8, $B5, $AC, $B1, $AA, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $BF, $FF, $B1, $B2, $B7, $FF, $B2, $B1, $AF, $BC, $FF, $B2, $B1, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $B0, $A4, $B3, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_32:  ; LOK2 accuracy
  FFLINES 3
  .BYTE $95, $98, $8C, $94, $FF, $A4, $B1, $A7, $FF, $95, $98, $94, $82, $FF, $AB, $AC, $B7, $FF, $A9, $A4, $B5, $FF, $B0, $B2, $B5, $A8, $FF, $FF
  .BYTE $B2, $A9, $B7, $A8, $B1, $BF, $FF, $A4, $B6, $FF, $B7, $AB, $A8, $FF, $B0, $A4, $B1, $B8, $A4, $AF, $FF, $A4, $AF, $BA, $A4, $BC, $B6, $FF
  .BYTE $A6, $AF, $A4, $AC, $B0, $A8, $A7, $FF, $B7, $AB, $A8, $BC, $FF, $A7, $AC, $A7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF


lut_Desc_33:  ; TREASURES
  FFLINES 3
  FFPAD {"Changes what a new game"}, 28
  FFPAD {"starts out with.  Saved"}, 28
  FFPAD {"games are not affected."}, 28

lut_Desc_100:  ; Item magic
  FFLINES 4
  FFPAD {"Each item that casts a spell"}, 28
  FFPAD {"casts another, and is named"}, 28
  FFPAD {"for it.  Balanced leaves out"}, 28
  FFPAD {"the strongest and weakest."}, 28

lut_Desc_99:  ; Thief lockpicking
  FFLINES 4
  FFPAD {"A Thief or Ninja at this"}, 28
  FFPAD {"level or above opens locked"}, 28
  FFPAD {"doors without the KEY.  Off,"}, 28
  FFPAD {"only the KEY does."}, 28

lut_Desc_98:  ; Starting caster item
  FFLINES 4
  FFPAD {"A new game starts with one"}, 28
  FFPAD {"random weapon or armor that"}, 28
  FFPAD {"casts a spell, held by the"}, 28
  FFPAD {"first character."}, 28

lut_Desc_62:  ; Starting items
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_62_0, lut_Desc_62_1, lut_Desc_62_2, lut_Desc_62_3, lut_Desc_62_4
  .WORD lut_Desc_62_5, lut_Desc_62_6, lut_Desc_62_7, lut_Desc_62_8
  .assert * - lut_Desc_62 = 1 + 2 * STARTITEMS_SETS, error, "one description per starting set"

lut_Desc_62_0:  ; Starting items: None
  FFLINES 2
  FFPAD {"A new game starts with no"}, 28
  FFPAD {"items, as it always has."}, 28

lut_Desc_62_1:  ; Safety Bit
  FFLINES 2
  FFPAD {"Safety Bit gives a TENT, a"}, 28
  FFPAD {"PURE and a SOFT."}, 28

lut_Desc_62_2:  ; Beggar's Choice
  FFLINES 3
  FFPAD {"Beggar's Choice gives 5"}, 28
  FFPAD {"TENTs, 20 HEALs, 2 PUREs and"}, 28
  FFPAD {"a SOFT."}, 28

lut_Desc_62_3:  ; Just Tents
  FFLINES 1
  FFPAD {"Just Tents gives 10 TENTs."}, 28

lut_Desc_62_4:  ; Explorer Pack
  FFLINES 4
  FFPAD {"Explorer Pack gives 10"}, 28
  FFPAD {"TENTs, 50 HEALs, 4 PUREs and"}, 28
  FFPAD {"2 SOFTs.  Most of FFR's"}, 28
  FFPAD {"presets start with this one."}, 28

lut_Desc_62_5:  ; Real Estate
  FFLINES 2
  FFPAD {"Real Estate gives 15 TENTs,"}, 28
  FFPAD {"5 CABINs and a HOUSE."}, 28

lut_Desc_62_6:  ; Warrior's Standard
  FFLINES 3
  FFPAD {"Warrior's Standard gives 15"}, 28
  FFPAD {"TENTs, 5 CABINs, a HOUSE, 50"}, 28
  FFPAD {"HEALs, 6 PUREs and 3 SOFTs."}, 28

lut_Desc_62_7:  ; Royal Packmule
  FFLINES 4
  FFPAD {"Royal Packmule gives 50"}, 28
  FFPAD {"TENTs, 15 CABINs, 5 HOUSEs,"}, 28
  FFPAD {"99 HEALs, 10 PUREs and 5"}, 28
  FFPAD {"SOFTs."}, 28

lut_Desc_62_8:  ; Duckling Boon
  FFLINES 3
  FFPAD {"Duckling Boon gives 99 of"}, 28
  FFPAD {"every TENT, CABIN, HOUSE,"}, 28
  FFPAD {"HEAL, PURE and SOFT."}, 28

lut_Desc_46:  ; Thief and Ninja hit%
  FFLINES 5
  FFPAD {"Hit% the Thief and the Ninja"}, 28
  FFPAD {"gain each level.  +2 is the"}, 28
  FFPAD {"original, +3 the Fighter's,"}, 28
  FFPAD {"+4 twice the original.  Not"}, 28
  FFPAD {"the agility buff above."}, 28

lut_Desc_45:  ; SCALE
  FFLINES 3
  FFPAD {"Adjustments to the game"}, 28
  FFPAD {"difficulty. Press left and"}, 28
  FFPAD {"right to change the value."}, 28

lut_Desc_34:  ; Free SHIP
  FFLINES 3
  FFPAD {"The ship is moored beside"}, 28
  FFPAD {"Coneria from the start,"}, 28
  FFPAD {"without beating the pirates."}, 28

lut_Desc_35:  ; Free AIRSHIP
  FFLINES 3
  FFPAD {"The airship is parked where"}, 28
  FFPAD {"the party starts, with no"}, 28
  FFPAD {"need for the FLOATER."}, 28

lut_Desc_36:  ; Free BRIDGE
  FFLINES 3
  FFPAD {"The bridge east of Coneria"}, 28
  FFPAD {"is already built, without"}, 28
  FFPAD {"rescuing the princess."}, 28

lut_Desc_37:  ; Free CANAL
  FFLINES 2
  FFPAD {"The canal is already open,"}, 28
  FFPAD {"without Nerrick and the TNT."}, 28

lut_Desc_38:  ; Free CANOE
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"CANOE, without the sage at"}, 28
  FFPAD {"Crescent Lake."}, 28


lut_Desc_39:  ; Free KEY
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"mystic KEY, which opens"}, 28
  FFPAD {"every locked door there is."}, 28

lut_Desc_40:  ; Free CHIME
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"CHIME, which opens the way"}, 28
  FFPAD {"into the Mirage Tower."}, 28

lut_Desc_41:  ; Free CROWN
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"CROWN, so the Marsh Cave"}, 28
  FFPAD {"need not be searched for it."}, 28


lut_Desc_42:  ; Free LUTE
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"LUTE, without rescuing the"}, 28
  FFPAD {"princess."}, 28

lut_Desc_43:  ; Free TAIL
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"TAIL, without searching the"}, 28
  FFPAD {"Ice Cave for it."}, 28

lut_Desc_44:  ; Free ROD
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"ROD, which opens the way"}, 28
  FFPAD {"down through the Earth Cave."}, 28

lut_Desc_47:  ; RANDOMIZATION
  FFLINES 4
  FFPAD {"Randomizes the next new"}, 28
  FFPAD {"game.  A saved game keeps"}, 28
  FFPAD {"the world it was started"}, 28
  FFPAD {"with, whatever is set here."}, 28

;  The RANDOMIZATION rows describe the value they are set to, one record each.
;  Each table is checked against its row's value count, so a value added
;  without its text is a build error.
lut_Desc_48:  ; Trap tiles, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_48_0, lut_Desc_48_1, lut_Desc_48_2, lut_Desc_48_3, lut_Desc_48_4
  .assert * - lut_Desc_48 = 1 + 2 * TRAPS_MODES, error, "one trap description per mode"

lut_Desc_48_0:  ; Trap tiles: Off
  FFLINES 2
  FFPAD {"Each trap tile springs the"}, 28
  FFPAD {"fight it always has."}, 28

lut_Desc_48_1:  ; Trap tiles: Shuffle
  FFLINES 2
  FFPAD {"The 34 trap tiles trade"}, 28
  FFPAD {"fights among themselves."}, 28

lut_Desc_48_2:  ; Trap tiles: A
  FFLINES 4
  FFPAD {"Each trap tile springs a"}, 28
  FFPAD {"fight drawn from every"}, 28
  FFPAD {"regular formation's A-side."}, 28
  FFPAD {"No two traps share one."}, 28

lut_Desc_48_3:  ; Trap tiles: B
  FFLINES 4
  FFPAD {"Each trap tile springs a"}, 28
  FFPAD {"fight drawn from every"}, 28
  FFPAD {"regular formation's B-side."}, 28
  FFPAD {"No two traps share one."}, 28

lut_Desc_48_4:  ; Trap tiles: A+B
  FFLINES 5
  FFPAD {"Each trap tile springs a"}, 28
  FFPAD {"fight drawn from every"}, 28
  FFPAD {"regular formation, A-side"}, 28
  FFPAD {"or B-side.  No two traps"}, 28
  FFPAD {"share one."}, 28

lut_Desc_49:  ; Shops, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_49_0, lut_Desc_49_1
  .assert * - lut_Desc_49 = 1 + 2 * SHOPS_MODES, error, "one shop description per mode"

lut_Desc_49_0:  ; Shops: Off
  FFLINES 2
  FFPAD {"Every shop sells what it"}, 28
  FFPAD {"always has."}, 28

lut_Desc_49_1:  ; Shops: Shuffle
  FFLINES 5
  FFPAD {"Weapons, armor and items are"}, 28
  FFPAD {"dealt out again among shops"}, 28
  FFPAD {"of their kind, the Caravan's"}, 28
  FFPAD {"BOTTLE included.  The"}, 28
  FFPAD {"Caravan stays open."}, 28

lut_Desc_50:  ; Chests, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_50_0, lut_Desc_50_1
  .assert * - lut_Desc_50 = 1 + 2 * CHESTS_MODES, error, "one chest description per mode"

lut_Desc_50_0:  ; Chests: Off
  FFLINES 5
  FFPAD {"Every chest holds what it"}, 28
  FFPAD {"always has -- unless Key"}, 28
  FFPAD {"items moves things.  Then"}, 28
  FFPAD {"what they push out fills the"}, 28
  FFPAD {"places they left."}, 28

lut_Desc_51:  ; Magic levels, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_51_0, lut_Desc_51_1
  .assert * - lut_Desc_51 = 1 + 2 * MAGIC_MODES, error, "one magic description per mode"

lut_Desc_51_0:  ; Magic levels: Off
  FFLINES 2
  FFPAD {"Every spell is the level it"}, 28
  FFPAD {"always is."}, 28

lut_Desc_51_1:  ; Magic levels: Shuffle
  FFLINES 5
  FFPAD {"White spells trade levels"}, 28
  FFPAD {"with white ones, and black"}, 28
  FFPAD {"with black.  A spell costs,"}, 28
  FFPAD {"sells and is learned at the"}, 28
  FFPAD {"level it lands on."}, 28

lut_Desc_52:  ; Max gear blessing
  FFLINES 5
  FFPAD {"Every weapon and armor rolls"}, 28
  FFPAD {"a bonus between the curse"}, 28
  FFPAD {"below and this, shown in its"}, 28
  FFPAD {"name.  On a weapon, each +1"}, 28
  FFPAD {"is 3 hit, 2 damage, 3 crit."}, 28

lut_Desc_53:  ; Min gear curse
  FFLINES 5
  FFPAD {"The worst a piece of gear"}, 28
  FFPAD {"may roll.  On armor, each +1"}, 28
  FFPAD {"is 1 absorb and 1 less evade"}, 28
  FFPAD {"penalty, twice that on body"}, 28
  FFPAD {"armor.  Each -1 takes away."}, 28

lut_Desc_54:  ; Formation rarity, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_54_0, lut_Desc_54_1, lut_Desc_54_2
  .assert * - lut_Desc_54 = 1 + 2 * FORMS_MODES, error, "one rarity description per mode"

lut_Desc_54_0:  ; Formation rarity: Off
  FFLINES 2
  FFPAD {"Each zone's fights are as"}, 28
  FFPAD {"common as they always are."}, 28

lut_Desc_54_1:  ; Formation rarity: Shuffle
  FFLINES 5
  FFPAD {"Each zone's fights trade"}, 28
  FFPAD {"places, so a common fight"}, 28
  FFPAD {"can turn rare and a rare one"}, 28
  FFPAD {"common.  Every zone keeps"}, 28
  FFPAD {"the fights it had."}, 28

lut_Desc_54_2:  ; Formation rarity: Tiered
  FFLINES 5
  FFPAD {"Each zone's fights trade"}, 28
  FFPAD {"places, mostly with fights"}, 28
  FFPAD {"about as common.  A common"}, 28
  FFPAD {"one seldom turns rare, or a"}, 28
  FFPAD {"rare one common."}, 28

lut_Desc_55:  ; Formation zones, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_55_0, lut_Desc_55_1, lut_Desc_55_2, lut_Desc_55_3
  .assert * - lut_Desc_55 = 1 + 2 * ZONES_MODES, error, "one zones description per mode"

lut_Desc_55_0:  ; Formation zones: Off
  FFLINES 2
  FFPAD {"Every zone has the fights it"}, 28
  FFPAD {"always has."}, 28

lut_Desc_55_1:  ; Formation zones: Shaken (ZONES_LIGHT)
  FFLINES 5
  FFPAD {"Four slots in each zone"}, 28
  FFPAD {"trade with other zones, so"}, 28
  FFPAD {"zones stay recognizable with"}, 28
  FFPAD {"a few strangers.  Coneria's"}, 28
  FFPAD {"land and WarMECH stay put."}, 28

lut_Desc_55_2:  ; Formation zones: Stirred (ZONES_SHUFFLE)
  FFLINES 5
  FFPAD {"Fights move between zones,"}, 28
  FFPAD {"dungeon floors and overworld"}, 28
  FFPAD {"alike, each as common as it"}, 28
  FFPAD {"was.  Coneria's land and"}, 28
  FFPAD {"WarMECH stay where they are."}, 28

lut_Desc_55_3:  ; Formation zones: Random
  FFLINES 5
  FFPAD {"Every zone's fights are"}, 28
  FFPAD {"drawn at random from all but"}, 28
  FFPAD {"the bosses', B-sides the"}, 28
  FFPAD {"game never uses included."}, 28
  FFPAD {"The land by Coneria stays."}, 28

lut_Desc_56:  ; Unrunnable fights, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_56_0, lut_Desc_56_1
  .assert * - lut_Desc_56 = 1 + 2 * RUNS_MODES, error, "one unrunnable description per mode"

lut_Desc_56_0:  ; Unrunnable fights: Off
  FFLINES 2
  FFPAD {"The fights you cannot run"}, 28
  FFPAD {"from are the usual ones."}, 28

lut_Desc_56_1:  ; Unrunnable fights: Shuffle
  FFLINES 5
  FFPAD {"As many fights as before"}, 28
  FFPAD {"cannot be run from, but"}, 28
  FFPAD {"which ones is dealt anew,"}, 28
  FFPAD {"each side on its own.  The"}, 28
  FFPAD {"bosses stay as they are."}, 28

lut_Desc_57:  ; Surprise rates, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_57_0, lut_Desc_57_1
  .assert * - lut_Desc_57 = 1 + 2 * SURPRISE_MODES, error, "one surprise description per mode"

lut_Desc_57_0:  ; Surprise rates: Off
  FFLINES 2
  FFPAD {"Each fight is as likely to"}, 28
  FFPAD {"ambush you as it always is."}, 28

lut_Desc_57_1:  ; Surprise rates: Shuffle
  FFLINES 5
  FFPAD {"How likely each fight is to"}, 28
  FFPAD {"ambush you, and you it, is"}, 28
  FFPAD {"dealt out again among the"}, 28
  FFPAD {"fights.  One you cannot run"}, 28
  FFPAD {"from never ambushes."}, 28

lut_Desc_58:  ; Status attacks, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_58_0, lut_Desc_58_1
  .assert * - lut_Desc_58 = 1 + 2 * STATUS_MODES, error, "one status description per mode"

lut_Desc_58_0:  ; Status attacks: Off
  FFLINES 2
  FFPAD {"Each enemy's touch does what"}, 28
  FFPAD {"it always does."}, 28

lut_Desc_58_1:  ; Status attacks: Shuffle
  FFLINES 4
  FFPAD {"Enemies trade touches, the"}, 28
  FFPAD {"ailment and its element"}, 28
  FFPAD {"together, bosses included."}, 28
  FFPAD {"The pirates keep theirs."}, 28

lut_Desc_59:  ; Enemy scripts, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_59_0, lut_Desc_59_1, lut_Desc_59_2, lut_Desc_59_3
  .assert * - lut_Desc_59 = 1 + 2 * AI_MODES, error, "one scripts description per mode"

lut_Desc_59_0:  ; Enemy scripts: Off
  FFLINES 2
  FFPAD {"Every enemy fights the way"}, 28
  FFPAD {"it always does."}, 28

lut_Desc_59_1:  ; Enemy scripts: Enemies
  FFLINES 5
  FFPAD {"Normal enemies trade their"}, 28
  FFPAD {"spell and skill lists, so"}, 28
  FFPAD {"one that never cast may,"}, 28
  FFPAD {"and a caster may not.  The"}, 28
  FFPAD {"pirates keep theirs."}, 28

lut_Desc_59_2:  ; Enemy scripts: Bosses
  FFLINES 4
  FFPAD {"The four fiends trade lists,"}, 28
  FFPAD {"and so do WarMECH, the"}, 28
  FFPAD {"Temple's fiends and Chaos"}, 28
  FFPAD {"among themselves."}, 28

lut_Desc_59_3:  ; Enemy scripts: Both
  FFLINES 5
  FFPAD {"Normal enemies trade spell"}, 28
  FFPAD {"and skill lists, the four"}, 28
  FFPAD {"fiends trade theirs, and"}, 28
  FFPAD {"WarMECH, the Temple's fiends"}, 28
  FFPAD {"and Chaos trade theirs."}, 28

lut_Desc_60:  ; Enemy skills, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_60_0, lut_Desc_60_1, lut_Desc_60_2, lut_Desc_60_3
  .assert * - lut_Desc_60 = 1 + 2 * AI_MODES, error, "one skills description per mode"

lut_Desc_60_0:  ; Enemy skills: Off
  FFLINES 2
  FFPAD {"Every list holds the spells"}, 28
  FFPAD {"and skills it always does."}, 28

lut_Desc_60_1:  ; Enemy skills: Enemies
  FFLINES 5
  FFPAD {"The spells and skills in"}, 28
  FFPAD {"normal enemies' lists are"}, 28
  FFPAD {"dealt out again, and how"}, 28
  FFPAD {"often each casts.  Never"}, 28
  FFPAD {"two NUKEs in a row."}, 28

lut_Desc_60_2:  ; Enemy skills: Bosses
  FFLINES 5
  FFPAD {"The same among the fiends'"}, 28
  FFPAD {"lists, and among WarMECH's,"}, 28
  FFPAD {"the Temple fiends' and"}, 28
  FFPAD {"Chaos's.  Never two NUKEs"}, 28
  FFPAD {"or NUCLEARs in a row."}, 28

lut_Desc_60_3:  ; Enemy skills: Both
  FFLINES 5
  FFPAD {"Spells and skills dealt out"}, 28
  FFPAD {"again among normal enemies,"}, 28
  FFPAD {"among the fiends, and among"}, 28
  FFPAD {"the last bosses.  Never two"}, 28
  FFPAD {"NUKEs or NUCLEARs in a row."}, 28

lut_Desc_71:  ; Ordeals pillars, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_71_0, lut_Desc_71_1
  .assert * - lut_Desc_71 = 1 + 2 * ORDEALS_MODES, error, "one Ordeals description per mode"

lut_Desc_71_0:  ; Ordeals pillars: Off
  FFLINES 3
  FFPAD {"The pillars in the Castle of"}, 28
  FFPAD {"Ordeals lead where they"}, 28
  FFPAD {"always do."}, 28

lut_Desc_71_1:  ; Ordeals pillars: Shuffle
  FFLINES 4
  FFPAD {"The teleporting pillars in"}, 28
  FFPAD {"the Castle of Ordeals go to"}, 28
  FFPAD {"new places.  There is always"}, 28
  FFPAD {"a way through."}, 28

lut_Desc_61:  ; RNG tables, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_61_0, lut_Desc_61_1
  .assert * - lut_Desc_61 = 1 + 2 * RNG_MODES, error, "one RNG description per mode"

lut_Desc_61_0:  ; RNG tables: Off
  FFLINES 2
  FFPAD {"Fights and battle rolls come"}, 28
  FFPAD {"in the order they always do."}, 28

lut_Desc_61_1:  ; RNG tables: Shuffle
  FFLINES 5
  FFPAD {"The tables that decide when"}, 28
  FFPAD {"fights come, and which, and"}, 28
  FFPAD {"how battle rolls go, are"}, 28
  FFPAD {"shuffled.  The odds stay the"}, 28
  FFPAD {"same, the order does not."}, 28

lut_Desc_50_1:  ; Chests: Shuffle
  FFLINES 5
  FFPAD {"The 234 chests that hold no"}, 28
  FFPAD {"key item trade contents, and"}, 28
  FFPAD {"the seven keep theirs.  If"}, 28
  FFPAD {"Key items moves them, NPCs"}, 28
  FFPAD {"join the trade as well."}, 28

;  The key item rows (randomization-notes.md section 12).
lut_Desc_72:  ; KEY ITEMS
  FFLINES 4
  FFPAD {"Where the key items are, for"}, 28
  FFPAD {"the next new game.  A saved"}, 28
  FFPAD {"game keeps the placement it"}, 28
  FFPAD {"was started with."}, 28

lut_Desc_73:  ; Key items, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_73_0, lut_Desc_73_1, lut_Desc_73_2
  .assert * - lut_Desc_73 = 1 + 2 * KEYITEMS_MODES, error, "one Key items description per mode"

lut_Desc_73_0:  ; Key items: Vanilla
  FFLINES 4
  FFPAD {"Key items stay where they"}, 28
  FFPAD {"always are.  Of the rows"}, 28
  FFPAD {"below, only Free and the"}, 28
  FFPAD {"Early ones change anything."}, 28

lut_Desc_73_1:  ; Key items: Standard
  FFLINES 5
  FFPAD {"Key items move.  Incentives"}, 28
  FFPAD {"go to the 13 NPCs who give"}, 28
  FFPAD {"one, the caravan and seven"}, 28
  FFPAD {"dungeon prize chests, as in"}, 28
  FFPAD {"FFR's default."}, 28

lut_Desc_73_2:  ; Key items: Wide
  FFLINES 5
  FFPAD {"As Standard, and four more"}, 28
  FFPAD {"prize chests -- the Volcano,"}, 28
  FFPAD {"Marsh Cave's locked room,"}, 28
  FFPAD {"Titan's Tunnel and Cardia --"}, 28
  FFPAD {"Free Enterprise's 25 spots."}, 28

lut_Desc_93:  ; Map shuffle, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_93_0, lut_Desc_93_1, lut_Desc_93_2
  .assert * - lut_Desc_93 = 1 + 2 * ENTRANCES_MODES, error, "one Map shuffle description per mode"

lut_Desc_93_0:  ; Map shuffle: Off
  FFLINES 3
  FFPAD {"Every entrance, stair and"}, 28
  FFPAD {"teleport leads where it"}, 28
  FFPAD {"always does."}, 28

lut_Desc_93_1:  ; Map shuffle: Entrances
  FFLINES 5
  FFPAD {"The overworld's dungeon and"}, 28
  FFPAD {"castle entrances lead into"}, 28
  FFPAD {"other ones.  Towns stay put."}, 28
  FFPAD {"Only with Key items Standard"}, 28
  FFPAD {"or Wide.  FFR's."}, 28

lut_Desc_93_2:  ; Map shuffle: Floors
  FFLINES 5
  FFPAD {"As Entrances, and the stairs"}, 28
  FFPAD {"and teleports inside lead to"}, 28
  FFPAD {"other floors.  Only with Key"}, 28
  FFPAD {"items Standard or Wide."}, 28
  FFPAD {"FFR's."}, 28

lut_Desc_101:  ; Map edits, by value
  .BYTE DESC_BYVALUE
  .WORD lut_Desc_101_0, lut_Desc_101_1, lut_Desc_101_2
  .assert * - lut_Desc_101 = 1 + 2 * OWEDITS_MODES, error, "one Map edits description per mode"

lut_Desc_101_0:  ; Map edits: Off
  FFLINES 2
  FFPAD {"The overworld is as it"}, 28
  FFPAD {"always is."}, 28

lut_Desc_101_1:  ; Map edits: Open
  FFLINES 5
  FFPAD {"Early Open Progression, as"}, 28
  FFPAD {"FFR's presets have it.  Walk"}, 28
  FFPAD {"from Coneria to the Dwarf"}, 28
  FFPAD {"Cave, and canoe from Pravoka"}, 28
  FFPAD {"to Crescent Lake."}, 28

lut_Desc_101_2:  ; Map edits: All
  FFLINES 5
  FFPAD {"Every FFR map edit that only"}, 28
  FFPAD {"adds a way through -- docks,"}, 28
  FFPAD {"rivers and passes, and the"}, 28
  FFPAD {"BRIDGE between Pravoka and"}, 28
  FFPAD {"Lefein."}, 28

;  Each item row by value: the first two shared, Free the item's own.
lut_DescItemInc:  ; an item row: Incentive
  FFLINES 4
  FFPAD {"Incentive puts it in one of"}, 28
  FFPAD {"the Key items spots, unless"}, 28
  FFPAD {"they run out.  Under Vanilla"}, 28
  FFPAD {"it stays where it always is."}, 28

lut_DescItemLoose:  ; an item row: Loose
  FFLINES 4
  FFPAD {"Loose puts it in any chest"}, 28
  FFPAD {"or with any NPC that gives"}, 28
  FFPAD {"something.  Under Vanilla it"}, 28
  FFPAD {"stays where it always is."}, 28

lut_Desc_74:  ; SHIP, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_34, lut_DescRemoveShip
  .assert * - lut_Desc_74 = 1 + 2 * ITEMVEHICLE_MODES, error, "one SHIP description per value"

lut_Desc_75:  ; AIRSHIP, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_35, lut_DescRemoveFloater
  .assert * - lut_Desc_75 = 1 + 2 * ITEMVEHICLE_MODES, error, "one AIRSHIP description per value"

lut_DescRemoveShip:  ; SHIP: Remove
  FFLINES 3
  FFPAD {"There is no ship.  Where it"}, 28
  FFPAD {"would be found there is gold"}, 28
  FFPAD {"instead.  Bikke keeps his."}, 28

lut_DescRemoveFloater:  ; AIRSHIP: Remove, the FLOATER
  FFLINES 4
  FFPAD {"There is no FLOATER, so the"}, 28
  FFPAD {"airship never rises.  Where"}, 28
  FFPAD {"it would be found there is"}, 28
  FFPAD {"gold instead."}, 28

lut_Desc_76:  ; BRIDGE, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_36
  .assert * - lut_Desc_76 = 1 + 2 * ITEM_MODES, error, "one BRIDGE description per value"

lut_Desc_77:  ; CANAL, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_37
  .assert * - lut_Desc_77 = 1 + 2 * ITEM_MODES, error, "one CANAL description per value"

lut_Desc_78:  ; CANOE, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_38
  .assert * - lut_Desc_78 = 1 + 2 * ITEM_MODES, error, "one CANOE description per value"

lut_Desc_79:  ; KEY, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_39
  .assert * - lut_Desc_79 = 1 + 2 * ITEM_MODES, error, "one KEY description per value"

lut_Desc_80:  ; CHIME, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_40
  .assert * - lut_Desc_80 = 1 + 2 * ITEM_MODES, error, "one CHIME description per value"

lut_Desc_81:  ; CROWN, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_41
  .assert * - lut_Desc_81 = 1 + 2 * ITEM_MODES, error, "one CROWN description per value"

lut_Desc_82:  ; LUTE, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_42
  .assert * - lut_Desc_82 = 1 + 2 * ITEM_MODES, error, "one LUTE description per value"

lut_Desc_83:  ; TAIL, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_43
  .assert * - lut_Desc_83 = 1 + 2 * ITEM_MODES, error, "one TAIL description per value"

lut_Desc_84:  ; ROD, by value
  .BYTE DESC_BYVALUE
  .WORD lut_DescItemInc, lut_DescItemLoose, lut_Desc_44
  .assert * - lut_Desc_84 = 1 + 2 * ITEM_MODES, error, "one ROD description per value"

lut_Desc_85:  ; Other items
  FFLINES 5
  FFPAD {"The other nine key items --"}, 28
  FFPAD {"CRYSTAL, HERB, TNT, ADAMANT,"}, 28
  FFPAD {"SLAB, RUBY, CUBE, BOTTLE and"}, 28
  FFPAD {"OXYALE -- as an incentive or"}, 28
  FFPAD {"loose, like the rows above."}, 28

lut_Desc_86:  ; a gear row
  FFLINES 5
  FFPAD {"Incentive puts this piece in"}, 28
  FFPAD {"a Key items spot when key"}, 28
  FFPAD {"items move, if one is left."}, 28
  FFPAD {"Treasure leaves it to the"}, 28
  FFPAD {"Chests row, like the rest."}, 28

lut_Desc_87:  ; Xcalber
  FFLINES 5
  FFPAD {"The Smith's sword for the"}, 28
  FFPAD {"ADAMANT.  Incentive puts it"}, 28
  FFPAD {"in a Key items spot, and"}, 28
  FFPAD {"Treasure among the chests,"}, 28
  FFPAD {"once key items move."}, 28

lut_Desc_88:  ; Early King
  FFLINES 3
  FFPAD {"The King gives his reward"}, 28
  FFPAD {"without waiting for the"}, 28
  FFPAD {"princess to be rescued."}, 28

lut_Desc_89:  ; Early Sarda
  FFLINES 3
  FFPAD {"Sarda gives his reward"}, 28
  FFPAD {"without waiting for the"}, 28
  FFPAD {"Vampire to be beaten."}, 28

lut_Desc_90:  ; Early Sage
  FFLINES 3
  FFPAD {"The sage at Crescent Lake"}, 28
  FFPAD {"gives his reward without"}, 28
  FFPAD {"waiting for the Earth Orb."}, 28

lut_Desc_91:  ; Early Ordeals
  FFLINES 3
  FFPAD {"The thrones in the Castle of"}, 28
  FFPAD {"Ordeals send the party on"}, 28
  FFPAD {"without the CROWN."}, 28

;  One pointer per list row, so a blank row needs no special case.
lut_DescLo:
  .BYTE <lut_DescBlank, <lut_Desc_45, <lut_DescBlank, <lut_Desc_22, <lut_Desc_23, <lut_Desc_24
  .BYTE <lut_Desc_25, <lut_Desc_28, <lut_DescBlank, <lut_Desc_0, <lut_DescBlank, <lut_Desc_3
  .BYTE <lut_Desc_4, <lut_Desc_5, <lut_Desc_6, <lut_Desc_7, <lut_Desc_8, <lut_Desc_9
  .BYTE <lut_Desc_10, <lut_Desc_11, <lut_Desc_12, <lut_Desc_13, <lut_Desc_14, <lut_Desc_15
  .BYTE <lut_Desc_16, <lut_Desc_17, <lut_Desc_69, <lut_Desc_70, <lut_DescBlank, <lut_Desc_1
  .BYTE <lut_DescBlank, <lut_Desc_18, <lut_Desc_19, <lut_Desc_20, <lut_Desc_21, <lut_Desc_65
  .BYTE <lut_Desc_66, <lut_DescBlank, <lut_Desc_2, <lut_DescBlank, <lut_Desc_26, <lut_Desc_46, <lut_Desc_99
  .BYTE <lut_Desc_27, <lut_Desc_29, <lut_Desc_30, <lut_Desc_31, <lut_Desc_63, <lut_Desc_64
  .BYTE <lut_Desc_32, <lut_Desc_67, <lut_Desc_92, <lut_Desc_96, <lut_Desc_95, <lut_Desc_97, <lut_DescBlank, <lut_Desc_33, <lut_DescBlank, <lut_Desc_62, <lut_Desc_98
  .BYTE <lut_DescBlank, <lut_Desc_47, <lut_DescBlank, <lut_Desc_48, <lut_Desc_49, <lut_Desc_50
  .BYTE <lut_Desc_51, <lut_Desc_100, <lut_Desc_52, <lut_Desc_53, <lut_Desc_54, <lut_Desc_55, <lut_Desc_56
  .BYTE <lut_Desc_57, <lut_Desc_58, <lut_Desc_59, <lut_Desc_60, <lut_Desc_61, <lut_Desc_71
  .BYTE <lut_DescBlank, <lut_Desc_72, <lut_DescBlank, <lut_Desc_73, <lut_Desc_93, <lut_Desc_101, <lut_Desc_74, <lut_Desc_75
  .BYTE <lut_Desc_76, <lut_Desc_77, <lut_Desc_78, <lut_Desc_79, <lut_Desc_80, <lut_Desc_81
  .BYTE <lut_Desc_82, <lut_Desc_83, <lut_Desc_84, <lut_Desc_85, <lut_DescBlank, <lut_Desc_86
  .BYTE <lut_Desc_86, <lut_Desc_86, <lut_Desc_86, <lut_Desc_86, <lut_Desc_86, <lut_Desc_86
  .BYTE <lut_Desc_86, <lut_Desc_87, <lut_DescBlank, <lut_Desc_88, <lut_Desc_89, <lut_Desc_90
  .BYTE <lut_Desc_91
lut_DescLoEnd:
.assert lut_DescLoEnd - lut_DescLo = OPTROW_COUNT, error, "one description pointer per row"
lut_DescHi:
  .BYTE >lut_DescBlank, >lut_Desc_45, >lut_DescBlank, >lut_Desc_22, >lut_Desc_23, >lut_Desc_24
  .BYTE >lut_Desc_25, >lut_Desc_28, >lut_DescBlank, >lut_Desc_0, >lut_DescBlank, >lut_Desc_3
  .BYTE >lut_Desc_4, >lut_Desc_5, >lut_Desc_6, >lut_Desc_7, >lut_Desc_8, >lut_Desc_9
  .BYTE >lut_Desc_10, >lut_Desc_11, >lut_Desc_12, >lut_Desc_13, >lut_Desc_14, >lut_Desc_15
  .BYTE >lut_Desc_16, >lut_Desc_17, >lut_Desc_69, >lut_Desc_70, >lut_DescBlank, >lut_Desc_1
  .BYTE >lut_DescBlank, >lut_Desc_18, >lut_Desc_19, >lut_Desc_20, >lut_Desc_21, >lut_Desc_65
  .BYTE >lut_Desc_66, >lut_DescBlank, >lut_Desc_2, >lut_DescBlank, >lut_Desc_26, >lut_Desc_46, >lut_Desc_99
  .BYTE >lut_Desc_27, >lut_Desc_29, >lut_Desc_30, >lut_Desc_31, >lut_Desc_63, >lut_Desc_64
  .BYTE >lut_Desc_32, >lut_Desc_67, >lut_Desc_92, >lut_Desc_96, >lut_Desc_95, >lut_Desc_97, >lut_DescBlank, >lut_Desc_33, >lut_DescBlank, >lut_Desc_62, >lut_Desc_98
  .BYTE >lut_DescBlank, >lut_Desc_47, >lut_DescBlank, >lut_Desc_48, >lut_Desc_49, >lut_Desc_50
  .BYTE >lut_Desc_51, >lut_Desc_100, >lut_Desc_52, >lut_Desc_53, >lut_Desc_54, >lut_Desc_55, >lut_Desc_56
  .BYTE >lut_Desc_57, >lut_Desc_58, >lut_Desc_59, >lut_Desc_60, >lut_Desc_61, >lut_Desc_71
  .BYTE >lut_DescBlank, >lut_Desc_72, >lut_DescBlank, >lut_Desc_73, >lut_Desc_93, >lut_Desc_101, >lut_Desc_74, >lut_Desc_75
  .BYTE >lut_Desc_76, >lut_Desc_77, >lut_Desc_78, >lut_Desc_79, >lut_Desc_80, >lut_Desc_81
  .BYTE >lut_Desc_82, >lut_Desc_83, >lut_Desc_84, >lut_Desc_85, >lut_DescBlank, >lut_Desc_86
  .BYTE >lut_Desc_86, >lut_Desc_86, >lut_Desc_86, >lut_Desc_86, >lut_Desc_86, >lut_Desc_86
  .BYTE >lut_Desc_86, >lut_Desc_87, >lut_DescBlank, >lut_Desc_88, >lut_Desc_89, >lut_Desc_90
  .BYTE >lut_Desc_91
lut_DescHiEnd:
.assert lut_DescHiEnd - lut_DescHi = OPTROW_COUNT, error, "one description pointer per row"
