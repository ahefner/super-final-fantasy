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
.include "variables.inc"

.import rando_belowfar, rando_warmfar, rando_yieldfar
.import lut_LogicKind, lut_LogicFlags
;  For tools/test_options.py.
.export es_build, es_dockfar, es_tables
.export rando_eswire, rando_esmasks, rando_esdock
;  The overworld's edits, for the fixed bank.
.export ow_editrow, mm_editrows

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


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The overworld's edits -- FFR's map edit flags (RANDO_OWEDITS), written
;;  into each row of the overworld as the game unpacks it: into the window of
;;  sixteen rows the party walks on, and into the minimap's two at a time.
;;  The map stays as the cartridge has it; gen/owedits.inc lists each row's
;;  edits, in FFR's order, so writing a row's active ones in turn leaves what
;;  FFR's edited map has there (tools/owedits.py).
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.include "owedits.inc"

    .a8
    .i8

;;  Row mapdraw_y, just unpacked into its slot of the window at mapdata,
;;  edited.  From LoadOWMapRow, by JSL: emulation mode, DBR the map's bank,
;;  whose $6000-$7FFF is the cartridge's SRAM as every chunk's is.  A, X, Y
;;  and tmp..tmp+1 clobbered; LoadOWMapRow's own use of them is over.
ow_editrow:
    LDA #<mapdata
    STA tmp
    LDA mapdraw_y
    AND #$0F
    ORA #>mapdata
    STA tmp+1
    LDA mapdraw_y
    JSR ow_edit
    RTL
.assert <mapdata = 0, error, "a window row is a page"

;;  The minimap's rows mm_maprow and mm_maprow + 1, just unpacked into
;;  mm_mapbuf and mm_mapbuf2, edited.  From CallMinimapDecompress, by JSL:
;;  emulation mode.  A, X, Y and tmp..tmp+1 clobbered, which MinimapDecompress
;;  clobbers too.
mm_editrows:
    LDA #<mm_mapbuf
    STA tmp
    LDA #>mm_mapbuf
    STA tmp+1
    LDA mm_maprow
    JSR ow_edit
    LDA #>mm_mapbuf2
    STA tmp+1
    LDA mm_maprow
    INC A
    JSR ow_edit
    RTL
.assert <mm_mapbuf2 = <mm_mapbuf, error, "the minimap's second row a page on from its first"

;;  Row A's active edits, written into its 256 tiles at (tmp).  Nothing to do
;;  for a save without edits, every save made before them included, which
;;  costs a few dozen cycles.  Emulation mode in and out.  A, X, Y clobbered.
ow_edit:
    TAY                         ; the row, while A asks whether there is work
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    ORA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    BNE :+
    RTS
:   CLC
    XCE                         ; native: the entries run past 256 bytes
    REP #$30
    .a16
    .i16
    TYA
    AND #$00FF
    ASL A
    TAX
    LDA f:WORLDFAR + lut_OweRow + 2, X
    PHA                         ; 3,S: where the row's entries end...
    LDA f:WORLDFAR + lut_OweRow, X
    TAX                         ; ...and X where they start
    JSR ow_lists
    PHA                         ; 1,S: the lists that apply
  @entry:
    TXA
    CMP 3,S
    BCS @done
    LDA f:WORLDFAR + lut_OweEnt, X          ; the entry's list
    AND 1,S
    BEQ @next
    LDA f:WORLDFAR + lut_OweEnt + 2, X      ; its x...
    AND #$00FF
    TAY
    SEP #$20
    .a8
    LDA f:WORLDFAR + lut_OweEnt + 3, X      ; ...and its tile
    STA (tmp), Y
    REP #$20
    .a16
  @next:
    TXA
    CLC
    ADC #OWE_ENTRY
    TAX
    BRA @entry
  @done:
    PLA
    PLA
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS

;;  The lists that apply, as a mask of their gates (owedits.py's
;;  active_lists): RANDO_OWEDITS' flags, but for FFR's two Cardia rules --
;;  BahamutCardiaDock only without the land bridge, and with both flags
;;  CardiaLandBridgeBahamutDock instead.  Out: A16.
ow_lists:
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    AND #OWEDIT_FLAGS
    BIT #OWEDIT_CARDIABRIDGE
    BEQ :+
    BIT #OWEDIT_BAHAMUTDOCK
    BEQ :+
    EOR #OWEDIT_BAHAMUTDOCK | OWE_BAHAMUTBRIDGE
:   RTS
    .a8
