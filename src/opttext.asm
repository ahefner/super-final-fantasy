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

lut_Desc_46:  ; Thief and Ninja hit%
  FFLINES 4
  FFPAD {"Hit rate grows twice as fast"}, 28
  FFPAD {"for the Thief and the Ninja."}, 28
  FFPAD {"Separate from the agility"}, 28
  FFPAD {"buff above."}, 28

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

lut_Desc_47:  ; NEW GAME
  FFLINES 4
  FFPAD {"Randomizes the next new"}, 28
  FFPAD {"game.  A saved game keeps"}, 28
  FFPAD {"the world it was started"}, 28
  FFPAD {"with, whatever is set here."}, 28

;  The NEW GAME rows describe the value they are set to, one record each.
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
  FFLINES 2
  FFPAD {"Every chest holds what it"}, 28
  FFPAD {"always has."}, 28

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
  FFPAD {"is 1 absorb and 1 less"}, 28
  FFPAD {"weight, twice that on body"}, 28
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
  .WORD lut_Desc_55_0, lut_Desc_55_1, lut_Desc_55_2
  .assert * - lut_Desc_55 = 1 + 2 * ZONES_MODES, error, "one zones description per mode"

lut_Desc_55_0:  ; Formation zones: Off
  FFLINES 2
  FFPAD {"Every zone has the fights it"}, 28
  FFPAD {"always has."}, 28

lut_Desc_55_1:  ; Formation zones: Shuffle
  FFLINES 5
  FFPAD {"Fights move between zones,"}, 28
  FFPAD {"dungeon floors and overworld"}, 28
  FFPAD {"alike, each as common as it"}, 28
  FFPAD {"was.  The land around"}, 28
  FFPAD {"Coneria keeps its own."}, 28

lut_Desc_55_2:  ; Formation zones: Random
  FFLINES 5
  FFPAD {"Every zone's fights are"}, 28
  FFPAD {"drawn at random from all but"}, 28
  FFPAD {"the bosses', B-sides the"}, 28
  FFPAD {"game never uses included."}, 28
  FFPAD {"The land by Coneria stays."}, 28

lut_Desc_50_1:  ; Chests: Shuffle
  FFLINES 4
  FFPAD {"The 234 chests that hold no"}, 28
  FFPAD {"key item trade contents."}, 28
  FFPAD {"The seven that do hold one"}, 28
  FFPAD {"keep it."}, 28

;  One pointer per list row, so a blank row needs no special case.
lut_DescLo:
  .BYTE <lut_DescBlank, <lut_Desc_45, <lut_DescBlank, <lut_Desc_22, <lut_Desc_23
  .BYTE <lut_Desc_24, <lut_Desc_25, <lut_Desc_28, <lut_DescBlank, <lut_Desc_0
  .BYTE <lut_DescBlank, <lut_Desc_3, <lut_Desc_4, <lut_Desc_5, <lut_Desc_6
  .BYTE <lut_Desc_7, <lut_Desc_8, <lut_Desc_9, <lut_Desc_10, <lut_Desc_11
  .BYTE <lut_Desc_12, <lut_Desc_13, <lut_Desc_14, <lut_Desc_15, <lut_Desc_16
  .BYTE <lut_Desc_17, <lut_DescBlank, <lut_Desc_1, <lut_DescBlank, <lut_Desc_18
  .BYTE <lut_Desc_19, <lut_Desc_20, <lut_Desc_21, <lut_DescBlank, <lut_Desc_2
  .BYTE <lut_DescBlank, <lut_Desc_26, <lut_Desc_46, <lut_Desc_27, <lut_Desc_29
  .BYTE <lut_Desc_30, <lut_Desc_31, <lut_Desc_32, <lut_DescBlank, <lut_Desc_33
  .BYTE <lut_DescBlank, <lut_Desc_34, <lut_Desc_35, <lut_Desc_36, <lut_Desc_37
  .BYTE <lut_Desc_38, <lut_Desc_39, <lut_Desc_40, <lut_Desc_41, <lut_Desc_42
  .BYTE <lut_Desc_43, <lut_Desc_44, <lut_DescBlank, <lut_Desc_47, <lut_DescBlank
  .BYTE <lut_Desc_48, <lut_Desc_49, <lut_Desc_50, <lut_Desc_51, <lut_Desc_52
  .BYTE <lut_Desc_53, <lut_Desc_54, <lut_Desc_55
lut_DescLoEnd:
.assert lut_DescLoEnd - lut_DescLo = OPTROW_COUNT, error, "one description pointer per row"
lut_DescHi:
  .BYTE >lut_DescBlank, >lut_Desc_45, >lut_DescBlank, >lut_Desc_22, >lut_Desc_23
  .BYTE >lut_Desc_24, >lut_Desc_25, >lut_Desc_28, >lut_DescBlank, >lut_Desc_0
  .BYTE >lut_DescBlank, >lut_Desc_3, >lut_Desc_4, >lut_Desc_5, >lut_Desc_6
  .BYTE >lut_Desc_7, >lut_Desc_8, >lut_Desc_9, >lut_Desc_10, >lut_Desc_11
  .BYTE >lut_Desc_12, >lut_Desc_13, >lut_Desc_14, >lut_Desc_15, >lut_Desc_16
  .BYTE >lut_Desc_17, >lut_DescBlank, >lut_Desc_1, >lut_DescBlank, >lut_Desc_18
  .BYTE >lut_Desc_19, >lut_Desc_20, >lut_Desc_21, >lut_DescBlank, >lut_Desc_2
  .BYTE >lut_DescBlank, >lut_Desc_26, >lut_Desc_46, >lut_Desc_27, >lut_Desc_29
  .BYTE >lut_Desc_30, >lut_Desc_31, >lut_Desc_32, >lut_DescBlank, >lut_Desc_33
  .BYTE >lut_DescBlank, >lut_Desc_34, >lut_Desc_35, >lut_Desc_36, >lut_Desc_37
  .BYTE >lut_Desc_38, >lut_Desc_39, >lut_Desc_40, >lut_Desc_41, >lut_Desc_42
  .BYTE >lut_Desc_43, >lut_Desc_44, >lut_DescBlank, >lut_Desc_47, >lut_DescBlank
  .BYTE >lut_Desc_48, >lut_Desc_49, >lut_Desc_50, >lut_Desc_51, >lut_Desc_52
  .BYTE >lut_Desc_53, >lut_Desc_54, >lut_Desc_55
lut_DescHiEnd:
.assert lut_DescHiEnd - lut_DescHi = OPTROW_COUNT, error, "one description pointer per row"
