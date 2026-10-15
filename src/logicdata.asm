; ---------------------------------------------------------------------------
;  logicdata.asm -- the vanilla world's logic, for incentive placement
;
;  Chunk CHUNK_LOGIC, data only: logicdata.inc, which tools/genlogic.py writes
;  from ../worldgraph.  place.inc reads it with long addresses (LOGICFAR).
;  Its own chunk because the randomizer's had 3KB left once placement's code
;  was in, and the rewards still to come want that.
; ---------------------------------------------------------------------------
.p816
.include "snesmap.inc"

.export lut_LogicKind, lut_LogicIdent, lut_LogicFlags, lut_LogicMaskLo, lut_LogicMaskHi
.export lut_LogicMasks, lut_LogicByBitLo, lut_LogicByBitHi, lut_LogicByBit, lut_LogicChaos
.export lut_DockX, lut_DockY, lut_ShipDock, lut_LogicGroup

.include "graph.inc"            ; .global: exports what graphdata.inc defines

.segment "BANK_LOGIC"

.include "logicdata.inc"
.include "graphdata.inc"
