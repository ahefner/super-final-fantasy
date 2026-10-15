; ---------------------------------------------------------------------------
;  world.asm -- entrance shuffle's chunk (CHUNK_WORLD)
;
;  The shuffle, the seed's logic, its spread groups and the ship's dock
;  (entrance.inc), out of the randomizer's chunk, which they outgrew.  The
;  randomizer calls in (JSL ... + WORLDFAR); the PRNG stays the randomizer's,
;  lent by long calls (rando_belowfar, rando_warmfar), so there is one copy of
;  the draws.  The data is the logic chunk's (graph.inc, graphdata.inc).
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "logic.inc"

.import rando_belowfar, rando_warmfar
.import lut_LogicKind, lut_LogicFlags
;  For tools/test_options.py.
.export rando_eswire, rando_esmasks, rando_esdock

.segment "BANK_WORLD"

wRNG    = .LOWORD(RW_RNG)

;  Native mode with DBR = $7F, from emulation; and back, for an RTL.  As
;  rando.asm's.
enter:
    CLC
    XCE
    LDA #^RANDOWRAM
    PHA
    PLB
    RTS

leave:
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    PLB
    RTL

esBit8:
  .BYTE $01, $02, $04, $08, $10, $20, $40, $80
esBit16:
  .WORD $0001, $0002, $0004, $0008, $0010, $0020, $0040, $0080
  .WORD $0100, $0200, $0400, $0800, $1000, $2000, $4000, $8000
;  RANDO_EARLY's bits' logic bits, as place.inc's lut_EarlyLBit.
esEarlyLBit:
  .BYTE LBIT_PRINCESS, LBIT_VAMPIRE, LBIT_ORB_EARTH, LBIT_CROWN

.include "entrance.inc"
