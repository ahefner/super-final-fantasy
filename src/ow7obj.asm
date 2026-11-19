; ---------------------------------------------------------------------------
;  ow7obj.asm -- Coneria's castle stood up on the Mode 7 overworld: its
;  frames, tools/genm7.py's, in the settings' second text chunk's free space
;  (BANK_OW7OBJ after BANK_OPTTEXT2), read long by ow7.asm (OW7OBJFAR) and
;  DMA'd from here into the sprite table a size at a time.
; ---------------------------------------------------------------------------
.export lut_M7CFrame

.segment "BANK_OW7OBJ"

.include "ow7obj.inc"
