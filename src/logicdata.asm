; ---------------------------------------------------------------------------
;  logicdata.asm -- the vanilla world's logic, for incentive placement
;
;  Chunk CHUNK_LOGIC, data only: logicdata.inc, which tools/genlogic.py writes
;  from ../worldgraph, and the world graph, the game's map's (graphdata.inc,
;  gen/logic_0/).  The build also links it alone once for each other map of
;  Map Select, with that map's graph (build.sh, gen/logic_N/), and
;  logic_ensure copies the save's map's into WRAM, where place.inc and the
;  rest read it with long addresses (LOGICFAR).
;  Its own chunk because the randomizer's had 3KB left once placement's code
;  was in, and the rewards still to come want that.
; ---------------------------------------------------------------------------
.p816
.include "snesmap.inc"

.export lut_LogicKind, lut_LogicIdent, lut_LogicFlags, lut_LogicMaskLo, lut_LogicMaskHi
.export lut_LogicMasks, lut_LogicByBitLo, lut_LogicByBitHi, lut_LogicByBit, lut_LogicChaos
.export lut_DockX, lut_DockY, lut_ShipDock, lut_LogicGroup, lut_LogicVanBit, lut_ShardCommon
.export lut_LogicSaraLo, lut_LogicSaraHi      ; Rebellious Princess (place.inc)

.include "graph.inc"            ; .global: exports what graphdata.inc defines

.segment "BANK_LOGIC"

.include "logicdata.inc"
.include "graphdata.inc"

;  The end, for logic_ensure's copy (altmaps.inc): this chunk -- or another
;  map's, laid out alike (genmaps.py) -- into WRAM, where LOGICFAR reads.
lut_LogicEnd:
.export lut_LogicEnd
