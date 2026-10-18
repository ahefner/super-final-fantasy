; ---------------------------------------------------------------------------
;  entrance.inc -- entrance shuffle on the cart
;
;  Included by world.asm, in a chunk of its own (CHUNK_WORLD); the PRNG is
;  the randomizer's, by long calls.  tools/randoref.py's es_* routines are
;  the same in Python, and the tests hold the two to the same result: the
;  shuffle (es_shuffle -> es_wiring), the seed's requirement masks (es_masks
;  -> es_fixpoint and es_locmasks), placement's index of them, the spread
;  groups and the ship's dock.  The data is tools/gengraph.py's (graph.inc,
;  graphdata.inc, in the logic chunk): the world graph without its wiring, and
;  FFR's records and lists for ShuffleEntrancesAndFloors.
;
;  A wiring is three tables of indices: each entrance's landing and each
;  normal teleport's (into lut_GrLand*), each exit's overworld coordinate
;  (into lut_GrExit*).  The game's own teleport tables are built from it in
;  the cache; the logic reads it directly.
;
;  Native mode, DBR = $7F, unless a routine says otherwise.
; ---------------------------------------------------------------------------

.include "graph.inc"

;  The shuffle's words (ES_VARS).
esMODE  = .LOWORD(ES_VARS) + $00
esP     = .LOWORD(ES_VARS) + $02    ; a list's address, for es_fy
esIDX   = .LOWORD(ES_VARS) + $04
esI     = .LOWORD(ES_VARS) + $06    ; the next of the dealt for an entrance...
esJ     = .LOWORD(ES_VARS) + $08    ; ...and for a floor
esOWC   = .LOWORD(ES_VARS) + $0A    ; how many entrances are dealt, not pinned
esTRY   = .LOWORD(ES_VARS) + $0C
esFORKS = .LOWORD(ES_VARS) + $0E
esNTL   = .LOWORD(ES_VARS) + $10
esNTOP  = .LOWORD(ES_VARS) + $12
esNSUB  = .LOWORD(ES_VARS) + $14
esNDEAD = .LOWORD(ES_VARS) + $16
esNPEND = .LOWORD(ES_VARS) + $18
esO     = .LOWORD(ES_VARS) + $1A    ; the entrance being filled
esR     = .LOWORD(ES_VARS) + $1C    ; a record
esT     = .LOWORD(ES_VARS) + $1E    ; a teleport
esE     = .LOWORD(ES_VARS) + $20    ; a list's end
esN     = .LOWORD(ES_VARS) + $22    ; a count
esSTART = .LOWORD(ES_VARS) + $24    ; the sanity check's findings
esTE    = .LOWORD(ES_VARS) + $26
esTW    = .LOWORD(ES_VARS) + $28
esSAFE  = .LOWORD(ES_VARS) + $2A
esX     = .LOWORD(ES_VARS) + $2C    ; an exit id
esEND   = .LOWORD(ES_VARS) + $2E    ; a record's teleports' end
;  The fixpoint's.
esEARLY = .LOWORD(ES_VARS) + $30    ; RANDO_EARLY
esNODE  = .LOWORD(ES_VARS) + $32    ; the region being relaxed from
esD     = .LOWORD(ES_VARS) + $34    ; the region being relaxed to
esRM    = .LOWORD(ES_VARS) + $36    ; 4: the edge's requirement
esC     = .LOWORD(ES_VARS) + $3A    ; 4: a candidate mask
esNT    = .LOWORD(ES_VARS) + $3E    ; masks in ES_TMP
esCHG   = .LOWORD(ES_VARS) + $40    ; 1 once a candidate went in
esHEAD  = .LOWORD(ES_VARS) + $42    ; the ring's head and tail
esTAIL  = .LOWORD(ES_VARS) + $44
esEI    = .LOWORD(ES_VARS) + $46    ; an index into an edge or source list...
esEE    = .LOWORD(ES_VARS) + $48    ; ...and its end
esSI    = .LOWORD(ES_VARS) + $4A
esSE    = .LOWORD(ES_VARS) + $4C
esLI    = .LOWORD(ES_VARS) + $4E    ; an index into a landing's regions...
esLE    = .LOWORD(ES_VARS) + $50    ; ...and its end
esTOT   = .LOWORD(ES_VARS) + $52    ; RP_MASK's bytes so far
esLOC   = .LOWORD(ES_VARS) + $54
esOWN   = .LOWORD(ES_VARS) + $56    ; 4: a location's own requirement
esQ     = .LOWORD(ES_VARS) + $5A    ; a region's masks' address
esK     = .LOWORD(ES_VARS) + $5C    ; a count down
esBIT   = .LOWORD(ES_VARS) + $5E
esOWE   = .LOWORD(ES_VARS) + $60    ; RANDO_OWEDITS, the map edits the logic is of
.assert esOWE + 2 <= .LOWORD(ES_WORDSEND), error, "entrance shuffle's words run past ES_VARS"

ePMAP   = .LOWORD(ES_PMAP)
ePFLOOR = .LOWORD(ES_PFLOOR)
eSHUF   = .LOWORD(ES_SHUF)
eFOUT   = .LOWORD(ES_FOUT)
eXOUT   = .LOWORD(ES_XOUT)
ePDEST  = .LOWORD(ES_PDEST)
eDESTS  = .LOWORD(ES_DESTS)
eTL     = .LOWORD(ES_TL)
eTOP    = .LOWORD(ES_TOP)
eSUB    = .LOWORD(ES_SUB)
eDEAD   = .LOWORD(ES_DEAD)
eORDER  = .LOWORD(ES_ORDER)
ePEND   = .LOWORD(ES_PEND)
eENT    = .LOWORD(ES_ENT)
eREQ    = .LOWORD(ES_REQ)
eNREQ   = .LOWORD(ES_NREQ)
eQUEUE  = .LOWORD(ES_QUEUE)
eQD     = .LOWORD(ES_QD)
eTMP    = .LOWORD(ES_TMP)
eMASK   = .LOWORD(RP_MASK)
eMOFF   = .LOWORD(RP_MOFF)
eCHAOS  = .LOWORD(RP_CHAOS)
eNCHAOS = .LOWORD(RP_NCHAOS)
eBYOFF  = .LOWORD(RP_BYBITOFF)
eBYBIT  = .LOWORD(RP_BYBIT)
eROOTS  = .LOWORD(ES_ROOTS)
eGREP   = .LOWORD(ES_GREP)
eGENTS  = .LOWORD(ES_GENTS)
eGROUP  = .LOWORD(RP_GROUP)
.assert ES_ROOTS + GR_NODES * 4 <= ES_TMP, error, "ES_ROOTS runs into ES_TMP"
.assert ES_REQ + GR_NODES * ES_NODEMAX * 4 <= ES_NREQ, error, "ES_REQ runs into ES_NREQ"
.assert GR_NODES <= 256, error, "a region is a byte"
eNORM   = .LOWORD(ES_NORM)
eEXIT   = .LOWORD(ES_EXIT)

ES_SANITY = 100                 ; FFR's: the sanity check's tries
STREAM_ENTR = $454E5452          ; "ENTR", as randoref.py's
.assert ES_RECORDS < $FF, error, "a record index is a byte, $FF none"
.assert ES_LOCATIONS <= 128, error, "ES_PDEST holds 128 location bits"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_start -- start attempt k's stream: RW_RNG = the seed ^ (STREAM_ENTR +
;;  k), warmed.  In: A16 = k.  Out: A16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_start:
    .a16
    CLC
    ADC #.LOWORD(STREAM_ENTR)
    EOR f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    STA a:wRNG
    LDA #.HIWORD(STREAM_ENTR)
    ADC #0
    EOR f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    STA a:wRNG+2
    JSL rando_warmfar + RANDOFAR
    RTS

;;  For the harness: es_wiring from a JSL in emulation mode.  In: A = the
;;  mode, X = the attempt k.  Out: the tables, and esTRY's high byte 1 if the
;;  shuffle failed (leave cannot return the carry).
rando_eswire:
    .a8
    .i8
    PHB
    PHA                         ; the mode
    PHX                         ; k
    JSR enter
    REP #$10
    .i16
    SEP #$20
    .a8
    PLA                         ; k, a byte
    REP #$20
    .a16
    AND #$00FF
    JSR es_start
    SEP #$20
    .a8
    PLA                         ; the mode
    JSR es_wiring
    LDA #0
    ROL A
    STA a:esTRY + 1
    JMP leave


;;  Entrance X pinned to where it leads in the vanilla game.  A8, I16.
es_keep:
    .a8
    .i16
    LDA f:LOGICFAR + lut_EsEnter, X
    STA a:ePMAP, X
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_vanilla -- the vanilla wiring, as indices.  A8, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_vanilla:
    .a8
    .i16
    LDX #$0000
  @ent:
    LDA f:LOGICFAR + lut_EsVanEnt, X
    STA a:eENT, X
    INX
    CPX #32
    BCC @ent
    LDX #$0000
  @norm:
    LDA f:LOGICFAR + lut_EsVanNorm, X
    STA a:eNORM, X
    INX
    CPX #64
    BCC @norm
    LDX #$0000
  @exit:
    LDA f:LOGICFAR + lut_EsVanExit, X
    STA a:eEXIT, X
    INX
    CPX #16
    BCC @exit
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_wiring -- FFR's ShuffleEntrancesAndFloors (randoref.es_shuffle)
;;
;;  In: A8 = the mode, ENTRANCES_ONLY or ENTRANCES_FLOORS; RW_RNG the
;;  stream, started.  Out: C clear and ES_ENT, ES_NORM and ES_EXIT the
;;  wiring; C set if FFR's sanity check failed ES_SANITY times.  A8, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_wiring:
    .a8
    .i16
    STA a:esMODE
    ;  Pinned: the towns' entrances, and the floors the mode keeps.
    LDA #$FF
    LDX #$0000
  @clrmap:
    STA a:ePMAP, X
    INX
    CPX #32
    BCC @clrmap
    LDX #$0000
  @clrfloor:
    STA a:ePFLOOR, X
    INX
    CPX #64
    BCC @clrfloor
    LDY #$0000
  @pinmap:
    TYX
    LDA f:LOGICFAR + lut_EsVanillaOw, X
    BEQ :+                      ; Coneria..Lefein: 1..8
    CMP #9
    BCS :+
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsEnter, X
    STA a:ePMAP, X
:   INY
    CPY #ES_VANILLA_OW_N
    BCC @pinmap
    ;  FFR, the FLOATER removed: the doors only the airship reaches stay put
    ;  (randoref.es_shuffle) -- Titan's Tunnel's west end; Cardia's but under
    ;  the land bridge, which walks to them; and of those the first and
    ;  Bahamut's but under Bahamut's dock, which sails there.
    LDA f:RANDO_SAVEFAR + (RANDO_ITEMS - RANDO_SAVE)
    AND #3 << (2 * ITEMROW_AIRSHIP)
    CMP #ITEM_REMOVE << (2 * ITEMROW_AIRSHIP)
    BNE @kept
    LDX #ES_KEEP_TITAN
    JSR es_keep
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    AND #>OWEDIT_CARDIABRIDGE
    BNE @kept
    LDY #4                      ; Cardia's four...
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    AND #OWEDIT_BAHAMUTDOCK
    BNE :+
    LDY #6                      ; ...and the first and Bahamut's
:   STY a:esN
    LDY #$0000
  @keep:
    TYX
    LDA f:LOGICFAR + lut_EsKeepCardia, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    JSR es_keep
    INY
    CPY a:esN
    BCC @keep
  @kept:
    LDA a:esMODE
    CMP #ENTRANCES_FLOORS
    BEQ @icecave
    LDY #$0000                  ; entrances alone: every vanilla floor...
  @pinfloor:
    TYX
    LDA f:LOGICFAR + lut_EsVanillaSm, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsTele, X
    STA a:ePFLOOR, X
    INY
    CPY #ES_VANILLA_SM_N
    BCC @pinfloor
    LDA #$FF                    ; ...but the Sea Shrine's from Onrac
    STA a:ePFLOOR + ES_SEASHRINE1
    BRA @pinned
  @icecave:
    LDY #$0000                  ; with floors: the Ice Cave's loop alone
  @pinloop:
    TYX
    LDA f:LOGICFAR + lut_EsIcecaveLoop, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsTele, X
    STA a:ePFLOOR, X
    INY
    CPY #ES_ICECAVE_LOOP_N
    BCC @pinloop
  @pinned:
    ;  The pinned destinations' locations, which nothing else may lead to;
    ;  and how many entrances are dealt.
    LDX #$0000
    LDA #0
  @clrdest:
    STA a:ePDEST, X
    INX
    CPX #16
    BCC @clrdest
    REP #$20
    .a16
    STZ a:esOWC
    SEP #$20
    .a8
    LDX #$0000
  @destmap:
    LDA a:ePMAP, X
    CMP #$FF
    BNE :+
    CPX #ES_UNUSED1
    BCS @nextmap
    REP #$20
    .a16
    INC a:esOWC
    SEP #$20
    .a8
    BRA @nextmap
:   JSR es_pin
  @nextmap:
    INX
    CPX #32
    BCC @destmap
    LDX #$0000
  @destfloor:
    LDA a:ePFLOOR, X
    CMP #$FF
    BEQ :+
    JSR es_pin
:   INX
    CPX #64
    BCC @destfloor

    ;  The lists, as FFR draws them: towns, forced top floors, free floors.
    LDX #.LOWORD(lut_EsTowns)
    LDY #ES_TOWNS_N
    LDA #0                      ; entrances
    JSR es_gather
    LDX #eTL
    JSR es_gathered
    STY a:esNTL
    LDX #.LOWORD(lut_EsTop)
    LDY #ES_TOP_N
    LDA #0
    JSR es_gather
    LDX #eTOP
    JSR es_gathered
    STY a:esNTOP
    LDX #.LOWORD(lut_EsFreeOw)
    LDY #ES_FREE_OW_N
    LDA #0
    JSR es_gather
    LDX #eSUB
    JSR es_gathered
    STY a:esNSUB
    LDX #.LOWORD(lut_EsFreeSm)
    LDY #ES_FREE_SM_N
    LDA #1                      ; teleports
    JSR es_gather
    REP #$20
    .a16
    LDA a:esNSUB                ; appended to the free floors
    CLC
    ADC #eSUB
    TAX
    SEP #$20
    .a8
    JSR es_gathered
    REP #$20
    .a16
    TYA
    CLC
    ADC a:esNSUB
    STA a:esNSUB
    SEP #$20
    .a8

    LDX #eTL
    LDY a:esNTL
    JSR es_fy
    ;  No town first that has no item shop: Lefein and Melmond go to the back.
    LDY a:esNTL
  @rotate:
    CPY #0
    BEQ @rotated
    LDX a:eTL
    REP #$20
    .a16
    TXA
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecFlags, X
    AND #1
    BEQ @rotated
    LDA a:eTL                   ; the first to the back
    PHA
    LDX #$0000
  @shift:
    INX
    CPX a:esNTL
    BCS :+
    LDA a:eTL, X
    STA a:eTL - 1, X
    BRA @shift
:   PLA
    STA a:eTL - 1, X
    DEY
    BRA @rotate
  @rotated:
    LDX #eTOP
    LDY a:esNTOP
    JSR es_fy
    LDX #eSUB
    LDY a:esNSUB
    JSR es_fy

    ;  Dead ends set aside, one for each fork beyond the first branch, and
    ;  one more if there are free floors at all.
    REP #$20
    .a16
    STZ a:esFORKS
    STZ a:esNDEAD
    LDA a:esNSUB
    BEQ @counted
    INC a:esFORKS
    SEP #$20
    .a8
    LDY #$0000
  @fork:
    TYX
    LDA a:eSUB, X
    JSR es_nteles               ; A16 = how many teleports out of it
    .a16
    CMP #2
    BCC :+
    DEC A
    CLC
    ADC a:esFORKS
    STA a:esFORKS
:   SEP #$20
    .a8
    INY
    CPY a:esNSUB
    BCC @fork
    REP #$20
    .a16
  @counted:
  @setaside:
    LDA a:esFORKS
    BEQ @asideok
    DEC a:esFORKS
    SEP #$20
    .a8
    LDY #$0000                  ; the first free floor with nowhere onward
  @findend:
    CPY a:esNSUB
    BCC :+
    SEC                         ; none left: FFR's code assumes there is one
    RTS
:   TYX
    LDA a:eSUB, X
    JSR es_nteles
    .a16
    BEQ @end
    SEP #$20
    .a8
    INY
    BRA @findend
  @end:
    SEP #$20
    .a8
    TYX
    LDA a:eSUB, X
    LDX a:esNDEAD
    STA a:eDEAD, X
    INX
    STX a:esNDEAD
  @close:                       ; and out of the free floors
    INY
    CPY a:esNSUB
    BCS :+
    TYX
    LDA a:eSUB, X
    STA a:eSUB - 1, X
    BRA @close
:   LDX a:esNSUB
    DEX
    STX a:esNSUB
    REP #$20
    .a16
    BRA @setaside
  @asideok:
    SEP #$20
    .a8
    LDX #eSUB
    LDY a:esNSUB
    JSR es_fy
    LDX #eDEAD
    LDY a:esNDEAD
    JSR es_fy

    ;  What is dealt, in order: towns, top floors, free floors, dead ends.
    LDY #$0000
    LDX #eTL
    LDA a:esNTL
    JSR es_append
    LDX #eTOP
    LDA a:esNTOP
    JSR es_append
    LDX #eSUB
    LDA a:esNSUB
    JSR es_append
    LDX #eDEAD
    LDA a:esNDEAD
    JSR es_append

    REP #$20
    .a16
    LDA #ES_SANITY
    STA a:esTRY
    SEP #$20
    .a8
  @try:
    JSR es_fill
    JSR es_sane
    BCS @sane
    REP #$20
    .a16
    DEC a:esTRY
    SEP #$20
    .a8
    BNE @try
    SEC
    RTS
  @sane:
    ;  The tables: vanilla, with what was dealt over it.
    JSR es_vanilla
    LDX #$0000
  @went:
    LDA a:eSHUF, X
    CMP #$FF
    BEQ :+
    JSR es_land
    STA a:eENT, X
:   INX
    CPX #32
    BCC @went
    LDX #$0000
  @floors:
    LDA a:eFOUT, X
    CMP #$FF
    BEQ :+
    JSR es_land
    STA a:eNORM, X
:   INX
    CPX #64
    BCC @floors
    LDX #$0000
  @exits:
    LDA a:eXOUT, X
    CMP #$FF
    BEQ :+
    STA a:eEXIT, X
:   INX
    CPX #16
    BCC @exits
    CLC
    RTS


;;  Record A's location set in ES_PDEST.  A8; X kept.
es_pin:
    .a8
    PHX
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecLoc, X
    JSR es_locbit
    ORA a:ePDEST, X
    STA a:ePDEST, X
    PLX
    RTS

;;  Location A: X = its byte in a location bitset, A = its bit.  A8.
es_locbit:
    .a8
    PHA
    LSR A
    LSR A
    LSR A
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    PLA
    AND #$07
    PHX
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:WORLDFAR + esBit8, X
    PLX
    RTS

;;  Records reached from a list of FFR's ids, those whose location is not
;;  pinned, in the list's order, into ES_DESTS (as scratch).  In: X = the
;;  list in the logic chunk, Y = its length, A = 0 for entrance ids (via
;;  lut_EsEnter), 1 for teleport ids (lut_EsTele).  Out: Y = how many.
es_gather:
    .a8
    STA a:esMODE + 1            ; (the mode's high byte, free as scratch)
    STX a:esP
    STY a:esE
    LDY #$0000
    STZ a:esN
    STZ a:esN + 1
  @each:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tick, if due
    CPY a:esE
    BCS @done
    REP #$20
    .a16
    TYA
    CLC
    ADC a:esP
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR, X           ; the id
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:esMODE + 1
    BNE :+
    LDA f:LOGICFAR + lut_EsEnter, X
    BRA :++
:   LDA f:LOGICFAR + lut_EsTele, X
:   STA a:esR
    PHY
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecLoc, X
    JSR es_locbit
    PLY                         ; (before the test: PLY sets the flags)
    AND a:ePDEST, X
    BNE @next                   ; pinned: not dealt
    LDA a:esR
    LDX a:esN
    STA a:eDESTS, X
    INX
    STX a:esN
  @next:
    INY
    BRA @each
  @done:
    LDA #0
    STA a:esMODE + 1
    LDY a:esN
    RTS

;;  The Y gathered, copied from ES_DESTS to X.  Y kept.
es_gathered:
    .a8
    STX a:esP
    PHY
    LDY #$0000
  @copy:
    CPY a:esN
    BCS @done
    TYX
    LDA a:eDESTS, X
    PHA
    REP #$20
    .a16
    TYA
    CLC
    ADC a:esP
    TAX
    SEP #$20
    .a8
    PLA
    STA a:0, X
    INY
    BRA @copy
  @done:
    PLY
    RTS

;;  Append A8 entries of the list at X to ES_DESTS at Y.  Out: Y past them.
es_append:
    .a8
    STX a:esP
    REP #$20
    .a16
    AND #$00FF
    STA a:esE
    SEP #$20
    .a8
    LDX #$0000
  @copy:
    CPX a:esE
    BCS @done
    PHX
    REP #$20
    .a16
    TXA
    CLC
    ADC a:esP
    TAX
    SEP #$20
    .a8
    LDA a:0, X
    TYX
    STA a:eDESTS, X
    PLX
    INX
    INY
    BRA @copy
  @done:
    RTS

;;  Record A: A16 = how many teleports lead out of it.  Y kept.
es_nteles:
    .a8
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:LOGICFAR + lut_EsRecTeleOff + 2, X
    SEC
    SBC f:LOGICFAR + lut_EsRecTeleOff, X
    RTS

;;  Record A: A8 = the landing it leads to.  X kept.
es_land:
    .a8
    PHX
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecLand, X
    PLX
    RTS

;;  Fisher-Yates, as Python's random.shuffle draws: for i from the top down
;;  to 1, a pick j below i + 1, and i and j swapped.  X = the list, Y = its
;;  length.  A8, I16.
es_fy:
    .a8
    STX a:esP
    CPY #2
    BCS :+
    RTS
:   DEY
    STY a:esIDX
  @each:
    LDA a:esIDX
    INC A
    JSL rando_belowfar + RANDOFAR
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:esP
    TAY                         ; j
    LDA a:esIDX
    CLC
    ADC a:esP
    TAX                         ; i
    SEP #$20
    .a8
    LDA a:0, X
    PHA
    LDA a:0, Y
    STA a:0, X
    PLA
    STA a:0, Y
    REP #$20
    .a16
    DEC a:esIDX
    SEP #$20
    .a8
    BNE @each
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_fill -- one try of the shuffle's filling: every entrance, in an order
;;  drawn afresh, gets its pinned destination or the next dealt one, and then
;;  every teleport out of it, picked at random from those still to fill, its
;;  pinned floor or the next dealt floor.  Exits go back to the entrance.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_fill:
    .a8
    LDA #$FF
    LDX #$0000
  @clr:
    STA a:eSHUF, X
    STA a:eFOUT, X
    STA a:eFOUT + 32, X
    INX
    CPX #32
    BCC @clr
    LDX #$0000
  @clrx:
    STA a:eXOUT, X
    INX
    CPX #16
    BCC @clrx
    REP #$20
    .a16
    STZ a:esI
    STZ a:esJ
    SEP #$20
    .a8
    ;  The order: the towns' entrances shuffled, then the others'.
    LDX #$0000
  @towns:
    LDA f:LOGICFAR + lut_EsTowns, X
    STA a:eORDER, X
    INX
    CPX #ES_TOWNS_N
    BCC @towns
    LDY #$0000                  ; then 0..ES_UNUSED1-1 that are not towns
  @others:
    TYA
    JSR es_istown
    BCS :+
    TYA
    STA a:eORDER, X
    INX
:   INY
    CPY #ES_UNUSED1
    BCC @others
    STX a:esE                   ; how many in all
    LDX #eORDER
    LDY #ES_TOWNS_N
    JSR es_fy
    REP #$20
    .a16
    LDA a:esE
    SEC
    SBC #ES_TOWNS_N
    TAY
    LDX #eORDER + ES_TOWNS_N
    SEP #$20
    .a8
    JSR es_fy

    LDY #$0000
  @entrance:
    CPY a:esE
    BCC :+
    RTS
:   PHY
    TYX
    LDA a:eORDER, X
    STA a:esO
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:ePMAP, X
    CMP #$FF
    BNE :+
    PHX
    LDX a:esI
    LDA a:eDESTS, X
    INX
    STX a:esI
    PLX
:   STA a:eSHUF, X
    JSR es_exitback
    ;  Its teleports, picked at random from those still to fill.
    STZ a:esNPEND
    STZ a:esNPEND + 1
    LDA a:eSHUF, X
    JSR es_pending
  @teleport:
    LDA a:esNPEND
    BEQ @filled
    JSL rando_belowfar + RANDOFAR
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:ePEND, X
    STA a:esT
  @close:                       ; spliced out
    INX
    CPX a:esNPEND
    BCS :+
    LDA a:ePEND, X
    STA a:ePEND - 1, X
    BRA @close
:   DEC a:esNPEND
    LDA a:esT
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:ePFLOOR, X
    CMP #$FF
    BNE :+
    PHX
    REP #$20
    .a16
    LDA a:esOWC
    CLC
    ADC a:esJ
    INC a:esJ
    TAX
    SEP #$20
    .a8
    LDA a:eDESTS, X
    PLX
:   STA a:eFOUT, X
    PHA
    JSR es_exitback
    PLA
    JSR es_pending
    BRA @teleport
  @filled:
    PLY
    INY
    JMP @entrance

;;  Record A dealt behind the entrance in esO: its exit, if it has one, goes
;;  back to that entrance's overworld coordinate.  X kept.
es_exitback:
    .a8
    PHX
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecExit, X
    CMP #$FF
    BEQ @none
    STA a:esX
    LDA a:esO
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    ;  Its entrance's overworld coordinate, which the Cardia Land Bridge
    ;  moves for six (randoref.es_shuffle).
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    AND #>OWEDIT_CARDIABRIDGE
    BEQ @owcoord
    LDA f:LOGICFAR + lut_EsOwCoordCardia, X
    BRA @owcoorded
  @owcoord:
    LDA f:LOGICFAR + lut_EsOwCoord, X
  @owcoorded:
    PHA
    LDA a:esX
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    PLA
    STA a:eXOUT, X
  @none:
    PLX
    RTS

;;  Record A's teleports appended to ES_PEND.  X kept.
es_pending:
    .a8
    PHX
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:LOGICFAR + lut_EsRecTeleOff + 2, X
    STA a:esEND
    LDA f:LOGICFAR + lut_EsRecTeleOff, X
    TAX
  @each:
    CPX a:esEND
    BCS @done
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecTeles, X
    PHX
    LDX a:esNPEND
    STA a:ePEND, X
    INC a:esNPEND
    PLX
    REP #$20
    .a16
    INX
    BRA @each
  @done:
    SEP #$20
    .a8
    PLX
    RTS

;;  Is entrance A one of the towns'?  C set if so.  X kept.
es_istown:
    .a8
    PHX
    LDX #$0000
  @each:
    CMP f:LOGICFAR + lut_EsTowns, X
    BEQ @yes
    INX
    CPX #ES_TOWNS_N
    BCC @each
    PLX
    CLC
    RTS
  @yes:
    PLX
    SEC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_sane -- FFR's CheckEntranceSanity, an unsafe start not allowed: one of
;;  the starting entrances leads to a starter destination, both ends of
;;  Titan's Tunnel are behind connected entrances, and at least three of the
;;  six near the start lead somewhere safe.  C set if sane.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_sane:
    .a8
    REP #$20
    .a16
    STZ a:esSTART
    STZ a:esTE
    STZ a:esTW
    STZ a:esSAFE
    SEP #$20
    .a8
    LDY #$0000
  @each:
    TYX
    LDA a:eSHUF, X
    CMP #$FF
    BEQ @next
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecLoc, X
    STA a:esR                   ; its location
    TYA
    LDX #.LOWORD(lut_EsStarting)
    JSR es_entbit
    BEQ :+
    LDA a:esR
    JSR es_locbit
    LDA f:LOGICFAR + lut_EsStarter, X
    PHA
    LDA a:esR
    JSR es_locbit
    STA a:esN
    PLA
    AND a:esN
    BEQ :+
    INC a:esSTART
:   TYA
    LDX #.LOWORD(lut_EsConnected)
    JSR es_entbit
    BEQ @next
    LDA a:esR
    CMP #ES_LOC_TITANEAST
    BNE :+
    INC a:esTE
:   CMP #ES_LOC_TITANWEST
    BNE @next
    INC a:esTW
  @next:
    INY
    CPY #32
    BCC @each
    LDY #$0000                  ; the six near the start
  @danger:
    TYX
    LDA f:LOGICFAR + lut_EsDanger, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:eSHUF, X
    CMP #$FF
    BEQ @dnext
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_EsRecLoc, X
    STA a:esR
    JSR es_locbit
    STA a:esN
    LDA f:LOGICFAR + lut_EsSafe, X
    AND a:esN
    BEQ @dnext
    INC a:esSAFE
  @dnext:
    INY
    CPY #6
    BCC @danger
    LDA a:esTE
    BEQ @no
    LDA a:esTW
    BEQ @no
    LDA a:esSTART
    BEQ @no
    LDA a:esSAFE
    CMP #3                      ; danger, 6 - safe, at most 3
    BCC @no
    SEC
    RTS
  @no:
    CLC
    RTS

;;  Entrance A's bit in the 32-bit mask at X in the logic chunk: Z clear if
;;  set.  Y kept.
es_entbit:
    .a8
    STX a:esP
    PHA
    LSR A
    LSR A
    LSR A
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:esP
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR, X
    STA a:esN
    PLA
    AND #$07
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:WORLDFAR + esBit8, X
    AND a:esN
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_fixpoint -- each region's minimal requirement masks on the wiring
;;  (randoref.es_masks), by relaxation: a ring of regions to visit, first in
;;  first out as the reference's list, and for each edge out of the one
;;  visited, its masks with the edge's requirement merged into the far
;;  region's.  The static edges first, then the wired sources, as the
;;  reference adds them.  A merge works in ES_TMP, so a set larger than
;;  ES_NODEMAX before its last candidate does not count; one larger after it
;;  refuses the wiring, as the reference does.
;;
;;  The graph is the one for every combination of the map edits
;;  (worldgraph/edited.py): an edge or a source whose requirement's cube of
;;  settings the save's RANDO_OWEDITS does not meet is not there (es_reqmask).
;;
;;  In: A16 = RANDO_EARLY (Early Ordeals waives the thrones' CROWN).  Out: C
;;  set if a region needed more than ES_NODEMAX.  A16, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_fixpoint:
    .a16
    .i16
    STA a:esEARLY
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    STA a:esOWE
    LDX #$0000
  @clr:
    STZ a:eNREQ, X
    STZ a:eQD, X
    INX
    INX
    CPX #256
    BCC @clr
    STZ a:eREQ                  ; the start: one mask, nothing needed
    STZ a:eREQ + 2
    SEP #$20
    .a8
    LDA #1
    STA a:eNREQ
    STA a:eQD
    STZ a:eQUEUE
    REP #$20
    .a16
    STZ a:esHEAD
    LDA #1
    STA a:esTAIL
  @visit:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tick, if due
    LDA a:esHEAD
    CMP a:esTAIL
    BNE :+
    CLC                         ; the ring empty: done
    RTS
:   TAX
    LDA a:eQUEUE, X
    AND #$00FF
    STA a:esNODE
    TXA
    INC A
    AND #$00FF
    STA a:esHEAD
    LDX a:esNODE
    SEP #$20
    .a8
    STZ a:eQD, X
    REP #$20
    .a16
    ;  The static edges.
    TXA
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrEdgeOff + 2, X
    STA a:esEE
    LDA f:LOGICFAR + lut_GrEdgeOff, X
    STA a:esEI
  @edge:
    LDA a:esEI
    CMP a:esEE
    BCS @sources
    TAX
    LDA f:LOGICFAR + lut_GrEdgeDst, X
    AND #$00FF
    STA a:esD
    LDA f:LOGICFAR + lut_GrEdgeReq, X
    JSR es_reqmask
    BCS @nextedge               ; not with these map edits
    JSR es_relax
    BCC @nextedge
    RTS
  @nextedge:
    INC a:esEI
    BRA @edge
  @sources:
    LDA a:esNODE
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrSrcOff + 2, X
    STA a:esSE
    LDA f:LOGICFAR + lut_GrSrcOff, X
    STA a:esSI
  @source:
    LDA a:esSI
    CMP a:esSE
    BCC :+
    JMP @visit
:   TAX
    LDA f:LOGICFAR + lut_GrSrcReq, X
    JSR es_reqmask
    BCC :+
    JMP @nextsrc                ; not with these map edits
:   LDX a:esSI
    LDA f:LOGICFAR + lut_GrSrcKind, X
    BIT #$0080
    BEQ @kind
    LDA a:esEARLY               ; a throne: no CROWN with Early Ordeals
    AND #EARLY_ORDEALS
    BEQ :+
    STZ a:esRM
    STZ a:esRM + 2
:   LDX a:esSI
    LDA f:LOGICFAR + lut_GrSrcKind, X
  @kind:
    AND #$0003
    PHA
    LDA f:LOGICFAR + lut_GrSrcId, X
    AND #$00FF
    TAX
    PLA
    BEQ @entrance
    CMP #1
    BEQ @teleport
    LDA a:eEXIT, X              ; an exit: the coordinate's regions
    AND #$00FF
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrExitOff + 2, X
    STA a:esLE
    LDA f:LOGICFAR + lut_GrExitOff, X
    STA a:esLI
  @exitto:
    LDA a:esLI
    CMP a:esLE
    BCS @nextsrc
    TAX
    LDA f:LOGICFAR + lut_GrExitNodes, X
    AND #$00FF
    STA a:esD
    JSR es_relax
    BCC :+
    RTS
:   INC a:esLI
    BRA @exitto
  @entrance:
    LDA a:eENT, X
    BRA @landing
  @teleport:
    LDA a:eNORM, X
  @landing:
    AND #$00FF
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrLandOff + 2, X
    STA a:esLE
    LDA f:LOGICFAR + lut_GrLandOff, X
    STA a:esLI
  @landto:
    LDA a:esLI
    CMP a:esLE
    BCS @nextsrc
    TAX
    LDA f:LOGICFAR + lut_GrLandNodes, X
    AND #$00FF
    STA a:esD
    JSR es_relax
    BCC :+
    RTS
:   INC a:esLI
    BRA @landto
  @nextsrc:
    INC a:esSI
    JMP @source

;;  Requirement index A (its low byte): esRM = its mask.  Out: C set when
;;  its cube of map edit settings (lut_GrCondOn, lut_GrCondOff) does not
;;  hold for esOWE -- every bit of the first, none of the second.  A16.
es_reqmask:
    .a16
    AND #$00FF
    PHA
    ASL A
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrMask, X
    STA a:esRM
    LDA f:LOGICFAR + lut_GrMask + 2, X
    STA a:esRM + 2
    PLA
    ASL A
    TAX
    LDA a:esOWE
    AND f:LOGICFAR + lut_GrCondOn, X
    CMP f:LOGICFAR + lut_GrCondOn, X
    BNE @no
    LDA a:esOWE
    AND f:LOGICFAR + lut_GrCondOff, X
    BNE @no
    CLC
    RTS
  @no:
    SEC
    RTS

;;  Region A16's masks' address in ES_REQ: A16 = it.  A region is 24 bytes.
es_reqaddr:
    .a16
    STA a:esQ
    ASL A                       ; x2
    CLC
    ADC a:esQ                   ; x3
    ASL A
    ASL A
    ASL A                       ; x24
    CLC
    ADC #eREQ
    RTS

;;  The edge esNODE -> esD, requirement esRM: esNODE's masks with esRM
;;  merged into esD's.  Out: C set if esD's set would be too large.  A16.
es_relax:
    .a16
    ;  esD's set into ES_TMP.
    LDA a:esD
    TAX
    LDA a:eNREQ, X
    AND #$00FF
    STA a:esNT
    LDA a:esD
    JSR es_reqaddr
    TAY
    LDX #$0000
  @copy:
    TXA
    LSR A
    LSR A
    CMP a:esNT
    BCS @copied
    LDA a:0, Y
    STA a:eTMP, X
    LDA a:2, Y
    STA a:eTMP + 2, X
    INY
    INY
    INY
    INY
    INX
    INX
    INX
    INX
    BRA @copy
  @copied:
    STZ a:esCHG
    ;  Each of esNODE's masks, with the requirement, in.
    LDA a:esNODE
    TAX
    LDA a:eNREQ, X
    AND #$00FF
    STA a:esK
    LDA a:esNODE
    JSR es_reqaddr
    STA a:esQ
  @each:
    LDA a:esK
    BEQ @merged
    DEC a:esK
    LDX a:esQ
    LDA a:0, X
    ORA a:esRM
    STA a:esC
    LDA a:2, X
    ORA a:esRM + 2
    STA a:esC + 2
    TXA
    CLC
    ADC #4
    STA a:esQ
    JSR es_insert
    BRA @each
  @merged:
    LDA a:esCHG
    BNE :+
    CLC                         ; nothing new
    RTS
:   LDA a:esNT
    CMP #ES_NODEMAX + 1
    BCC :+
    RTS                         ; too many: C set
:   LDA a:esD                   ; the set back
    JSR es_reqaddr
    TAY
    LDX #$0000
  @back:
    TXA
    LSR A
    LSR A
    CMP a:esNT
    BCS @stored
    LDA a:eTMP, X
    STA a:0, Y
    LDA a:eTMP + 2, X
    STA a:2, Y
    INY
    INY
    INY
    INY
    INX
    INX
    INX
    INX
    BRA @back
  @stored:
    LDX a:esD
    SEP #$20
    .a8
    LDA a:esNT
    STA a:eNREQ, X
    LDA a:eQD, X                ; to visit, unless it already is
    BNE :+
    LDA #1
    STA a:eQD, X
    TXA
    LDX a:esTAIL
    STA a:eQUEUE, X
    REP #$20
    .a16
    TXA
    INC A
    AND #$00FF
    STA a:esTAIL
:   REP #$20
    .a16
    CLC
    RTS

;;  esC into the set in ES_TMP (esNT masks): nothing if one there needs no
;;  more than it; otherwise those that need more go, and it goes in, and
;;  esCHG is set.  A16.
es_insert:
    .a16
    LDX #$0000
  @dominated:
    TXA
    LSR A
    LSR A
    CMP a:esNT
    BCS @free
    LDA a:esC                   ; T[j] & ~C == 0: C needs all T[j] does
    EOR #$FFFF
    AND a:eTMP, X
    BNE :+
    LDA a:esC + 2
    EOR #$FFFF
    AND a:eTMP + 2, X
    BNE :+
    RTS                         ; dominated: nothing
:   INX
    INX
    INX
    INX
    BRA @dominated
  @free:
    LDX #$0000                  ; those needing all C does, and more, go
  @sweep:
    TXA
    LSR A
    LSR A
    CMP a:esNT
    BCS @add
    LDA a:eTMP, X               ; C & ~T[j] == 0
    EOR #$FFFF
    AND a:esC
    BNE @keep
    LDA a:eTMP + 2, X
    EOR #$FFFF
    AND a:esC + 2
    BNE @keep
    DEC a:esNT                  ; the last into its place, and look again
    LDA a:esNT
    ASL A
    ASL A
    TAY
    LDA a:eTMP, Y
    STA a:eTMP, X
    LDA a:eTMP + 2, Y
    STA a:eTMP + 2, X
    BRA @sweep
  @keep:
    INX
    INX
    INX
    INX
    BRA @sweep
  @add:
    LDA a:esNT
    ASL A
    ASL A
    TAX
    LDA a:esC
    STA a:eTMP, X
    LDA a:esC + 2
    STA a:eTMP + 2, X
    INC a:esNT
    LDA #1
    STA a:esCHG
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_locmasks -- each location's masks from its regions' (es_fixpoint),
;;  with its own requirement, less the NPC waivers of Early King, Sarda and
;;  the Sage, as RP_MASK and RP_MOFF have them for placement; and Chaos's as
;;  RP_CHAOS.  In: esEARLY.  Out: C set if they do not fit.  A16, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_locmasks:
    .a16
    .i16
    STZ a:esTOT
    STZ a:esLOC
  @loc:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tick, if due
    LDX a:esLOC
    LDA f:LOGICFAR + lut_GrLocReq, X
    JSR es_reqmask
    LDA a:esRM
    STA a:esOWN
    LDA a:esRM + 2
    STA a:esOWN + 2
    LDA a:esLOC
    CMP #GR_LOCS - 1
    BCS @own                    ; Chaos has no Early flag
    TAX
    LDA f:LOGICFAR + lut_LogicFlags, X
    AND #$0070
    BEQ @own
    LSR A
    LSR A
    LSR A
    LSR A
    DEC A                       ; its RANDO_EARLY bit
    CMP #3
    BCS @own                    ; Ordeals: in the graph
    TAX
    LDA a:esEARLY
    AND f:WORLDFAR + esBit8, X
    AND #$00FF
    BEQ @own
    LDA f:WORLDFAR + esEarlyLBit, X
    AND #$00FF
    CMP #16
    BCS @hi
    ASL A
    TAX
    LDA f:WORLDFAR + esBit16, X
    EOR #$FFFF
    AND a:esOWN
    STA a:esOWN
    BRA @own
  @hi:
    SEC
    SBC #16
    ASL A
    TAX
    LDA f:WORLDFAR + esBit16, X
    EOR #$FFFF
    AND a:esOWN + 2
    STA a:esOWN + 2
  @own:
    ;  Its regions' masks, each with its own, merged.
    STZ a:esNT
    LDA a:esLOC
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrLocOff + 2, X
    STA a:esLE
    LDA f:LOGICFAR + lut_GrLocOff, X
    STA a:esLI
  @node:
    LDA a:esLI
    CMP a:esLE
    BCS @gathered
    TAX
    LDA f:LOGICFAR + lut_GrLocNodes, X
    AND #$00FF
    TAX
    LDA a:eNREQ, X
    AND #$00FF
    STA a:esK
    TXA
    JSR es_reqaddr
    STA a:esQ
  @mask:
    LDA a:esK
    BEQ @nextnode
    DEC a:esK
    LDX a:esQ
    LDA a:0, X
    ORA a:esOWN
    STA a:esC
    LDA a:2, X
    ORA a:esOWN + 2
    STA a:esC + 2
    TXA
    CLC
    ADC #4
    STA a:esQ
    JSR es_insert
    BRA @mask
  @nextnode:
    INC a:esLI
    JMP @node
  @gathered:
    LDA a:esLOC
    CMP #GR_LOCS - 1
    BCC @place
    LDA a:esNT                  ; Chaos
    CMP #RP_CHAOSMAX + 1
    BCC :+
    RTS
:   STA a:eNCHAOS
    LDX #$0000
  @chaos:
    TXA
    LSR A
    LSR A
    CMP a:esNT
    BCS @done
    LDA a:eTMP, X
    STA a:eCHAOS, X
    LDA a:eTMP + 2, X
    STA a:eCHAOS + 2, X
    INX
    INX
    INX
    INX
    BRA @chaos
  @done:
    LDA a:esTOT                 ; the last location's end
    STA a:eMOFF + 2 * (GR_LOCS - 1)
    CLC
    RTS
  @place:
    ASL A
    TAX
    LDA a:esTOT
    STA a:eMOFF, X
    LSR A
    LSR A
    CLC
    ADC a:esNT
    CMP #RP_MASKMAX + 1
    BCC :+
    RTS                         ; RP_MASK full: C set
:   LDY a:esTOT
    LDX #$0000
  @store:
    TXA
    LSR A
    LSR A
    CMP a:esNT
    BCS @stored
    LDA a:eTMP, X
    STA a:eMASK, Y
    LDA a:eTMP + 2, X
    STA a:eMASK + 2, Y
    INY
    INY
    INY
    INY
    INX
    INX
    INX
    INX
    BRA @store
  @stored:
    STY a:esTOT
    INC a:esLOC
    JMP @loc


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_bybit -- placement's index of the masks: for each bit, the locations
;;  whose masks name it, in order.  Out: C set if it does not fit
;;  RP_BYBITMAX.  A16, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_bybit:
    .a16
    .i16
    STZ a:esTOT                 ; entries so far
    STZ a:esBIT
  @bit:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tick, if due
    LDA a:esBIT
    ASL A
    TAX
    LDA a:esTOT
    STA a:eBYOFF, X
    LDA a:esBIT
    CMP #32
    BCC :+
    CLC
    RTS
:   AND #$000F
    ASL A
    TAX
    LDA f:WORLDFAR + esBit16, X
    STA a:esC                   ; the bit, in its word
    LDA a:esBIT
    AND #$0010
    LSR A
    LSR A
    LSR A
    STA a:esC + 2               ; its word's offset, 0 or 2
    STZ a:esLOC
  @loc:
    LDA a:esLOC
    ASL A
    TAX
    LDA a:eMOFF + 2, X
    STA a:esLE
    LDA a:eMOFF, X
    CLC
    ADC a:esC + 2
    TAX
  @mask:
    TXA
    SEC
    SBC a:esC + 2
    CMP a:esLE
    BCS @nextloc
    LDA a:eMASK, X
    AND a:esC
    BNE @names
    INX
    INX
    INX
    INX
    BRA @mask
  @names:
    LDX a:esTOT
    CPX #RP_BYBITMAX
    BCC :+
    RTS                         ; full: C set
:   SEP #$20
    .a8
    LDA a:esLOC
    STA a:eBYBIT, X
    REP #$20
    .a16
    INC a:esTOT
  @nextloc:
    INC a:esLOC
    LDA a:esLOC
    CMP #GR_LOCS - 1
    BCC @loc
    INC a:esBIT
    JMP @bit


;;  For the harness: the wiring and then the logic, from a JSL in emulation
;;  mode.  In: A = the mode (ENTRANCES_OFF: the vanilla wiring), X = k, Y =
;;  RANDO_EARLY.  Out: esTRY's high byte: 0, or the stage that refused --
;;  1 the shuffle, 2 the fixpoint, 3 the masks, 4 the index, 5 the groups.
rando_esmasks:
    .a8
    .i8
    PHB
    PHY
    PHA
    PHX
    JSR enter
    REP #$10
    .i16
    SEP #$20
    .a8
    PLA                         ; k
    REP #$20
    .a16
    AND #$00FF
    STA a:esK
    SEP #$20
    .a8
    PLA                         ; the mode
    BNE @shuffle
    JSR es_vanilla
    BRA @logic
  @shuffle:
    PHA
    REP #$20
    .a16
    LDA a:esK
    JSR es_start
    SEP #$20
    .a8
    PLA
    JSR es_wiring
    LDA #1
    BCS @out
  @logic:
    PLA                         ; RANDO_EARLY
    REP #$20
    .a16
    AND #$00FF
    JSR es_fixpoint
    SEP #$20
    .a8
    LDA #2
    BCS @out2
    REP #$20
    .a16
    JSR es_locmasks
    SEP #$20
    .a8
    LDA #3
    BCS @out2
    REP #$20
    .a16
    JSR es_bybit
    SEP #$20
    .a8
    LDA #4
    BCS @out2
    REP #$20
    .a16
    JSR es_roots
    JSR es_groups
    SEP #$20
    .a8
    LDA #5
    BCS @out2
    LDA #0
    BRA @out2
  @out:
    STA a:esTRY + 1
    PLA                         ; the early byte, unread (A8: one byte)
    JMP leave
  @out2:
    STA a:esTRY + 1
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_roots -- each region's entrances: those whose landing reaches it
;;  without leaving the maps (randoref.es_roots), a bit each in ES_ROOTS.  A
;;  walk from each entrance's landing over the edges between regions of the
;;  maps, static and wired teleports alike.  A16, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_roots:
    .a16
    .i16
    LDX #$0000
  @clr:
    STZ a:eROOTS, X
    INX
    INX
    CPX #GR_NODES * 4
    BCC @clr
    STZ a:esEI
  @ent:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tick, if due
    LDA a:esEI
    CMP #GR_ENTIDS
    BCC :+
    RTS
:   TAX
    LDA f:LOGICFAR + lut_GrEntIds, X
    AND #$00FF
    STA a:esBIT
    AND #$000F                  ; its bit: esC low word, esC+2 high
    ASL A
    TAX
    LDA f:WORLDFAR + esBit16, X
    STZ a:esC
    STZ a:esC + 2
    LDX a:esBIT
    CPX #16
    BCS :+
    STA a:esC
    BRA :++
:   STA a:esC + 2
:   STZ a:esK                   ; the walk's stack, in ES_QUEUE
    LDA a:eENT, X               ; its landing's regions
    AND #$00FF
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrLandOff + 2, X
    STA a:esLE
    LDA f:LOGICFAR + lut_GrLandOff, X
    STA a:esLI
  @land:
    LDA a:esLI
    CMP a:esLE
    BCS @walk
    TAX
    LDA f:LOGICFAR + lut_GrLandNodes, X
    AND #$00FF
    JSR es_rootmark
    INC a:esLI
    BRA @land
  @walk:
    LDA a:esK
    BNE :+
    INC a:esEI
    BRA @ent
:   DEC a:esK
    LDX a:esK
    LDA a:eQUEUE, X
    AND #$00FF
    STA a:esNODE
    TAX
    LDA f:LOGICFAR + lut_GrOwNode, X
    AND #$00FF
    BNE @walk                   ; the overworld: no way on from here
    TXA
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrEdgeOff + 2, X
    STA a:esSE
    LDA f:LOGICFAR + lut_GrEdgeOff, X
    STA a:esSI                  ; (the edge index; esEI is the entrance's)
  @edge:
    LDA a:esSI
    CMP a:esSE
    BCS @tele
    TAX
    LDA f:LOGICFAR + lut_GrEdgeDst, X
    AND #$00FF
    JSR es_rootinside
    INC a:esSI
    BRA @edge
  @tele:
    LDA a:esNODE
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrSrcOff + 2, X
    STA a:esSE
    LDA f:LOGICFAR + lut_GrSrcOff, X
    STA a:esSI
  @src:
    LDA a:esSI
    CMP a:esSE
    BCC :+
    JMP @walk
:   TAX
    LDA f:LOGICFAR + lut_GrSrcKind, X
    AND #$0003
    CMP #1
    BNE @nextsrc
    LDA f:LOGICFAR + lut_GrSrcId, X
    AND #$00FF
    TAX
    LDA a:eNORM, X
    AND #$00FF
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrLandOff + 2, X
    STA a:esLE
    LDA f:LOGICFAR + lut_GrLandOff, X
    STA a:esLI
  @to:
    LDA a:esLI
    CMP a:esLE
    BCS @nextsrc
    TAX
    LDA f:LOGICFAR + lut_GrLandNodes, X
    AND #$00FF
    JSR es_rootinside
    INC a:esLI
    BRA @to
  @nextsrc:
    INC a:esSI
    BRA @src

;;  Region A, reached inside the maps: marked, unless it is the overworld's.
es_rootinside:
    .a16
    TAX
    LDA f:LOGICFAR + lut_GrOwNode, X
    AND #$00FF
    BEQ :+
    RTS
:   TXA
    ;  fall through

;;  Region A: esC's bit set in its roots, and onto the stack, unless it was.
es_rootmark:
    .a16
    STA a:esD
    ASL A
    ASL A
    TAX
    LDA a:eROOTS, X
    AND a:esC
    BNE @had
    LDA a:eROOTS + 2, X
    AND a:esC + 2
    BNE @had
    LDA a:eROOTS, X
    ORA a:esC
    STA a:eROOTS, X
    LDA a:eROOTS + 2, X
    ORA a:esC + 2
    STA a:eROOTS + 2, X
    LDX a:esK
    SEP #$20
    .a8
    LDA a:esD
    STA a:eQUEUE, X
    REP #$20
    .a16
    INC a:esK
  @had:
    RTS


;;  Location esLOC's entrances: its regions' roots together, in esRM.
es_locents:
    .a16
    STZ a:esRM
    STZ a:esRM + 2
    LDA a:esLOC
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrLocOff + 2, X
    STA a:esLE
    LDA f:LOGICFAR + lut_GrLocOff, X
  @node:
    CMP a:esLE
    BCS @done
    PHA
    TAX
    LDA f:LOGICFAR + lut_GrLocNodes, X
    AND #$00FF
    ASL A
    ASL A
    TAX
    LDA a:eROOTS, X
    ORA a:esRM
    STA a:esRM
    LDA a:eROOTS + 2, X
    ORA a:esRM + 2
    STA a:esRM + 2
    PLA
    INC A
    BRA @node
  @done:
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_groups -- the spread groups (randoref.es_groups): a number per pool
;;  chest, the chests with the same entrances and the same masks sharing one,
;;  numbered as they first come; $FF for an NPC or the caravan.  Each group's
;;  first chest and entrances are kept to compare against.  Out: C set if
;;  there are more than ES_GROUPMAX.  A16, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_groups:
    .a16
    .i16
    STZ a:esNT                  ; groups so far
    STZ a:esLOC
  @loc:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tick, if due
    LDX a:esLOC
    LDA f:LOGICFAR + lut_LogicKind, X
    AND #$00FF
    BEQ @chest
    LDA #$00FF
    BRA @set
  @chest:
    JSR es_locents
    STZ a:esK
  @group:
    LDA a:esK
    CMP a:esNT
    BCS @new
    ASL A
    ASL A
    TAX
    LDA a:eGENTS, X
    CMP a:esRM
    BNE @other
    LDA a:eGENTS + 2, X
    CMP a:esRM + 2
    BNE @other
    LDX a:esK
    LDA a:eGREP, X
    AND #$00FF
    JSR es_samemasks
    BCC @other
    LDA a:esK
    BRA @set
  @other:
    INC a:esK
    BRA @group
  @new:
    CMP #ES_GROUPMAX
    BCC :+
    RTS                         ; too many: C set
:   TAX
    SEP #$20
    .a8
    LDA a:esLOC
    STA a:eGREP, X
    REP #$20
    .a16
    TXA
    ASL A
    ASL A
    TAX
    LDA a:esRM
    STA a:eGENTS, X
    LDA a:esRM + 2
    STA a:eGENTS + 2, X
    LDA a:esNT
    INC a:esNT
  @set:
    LDX a:esLOC
    SEP #$20
    .a8
    STA a:eGROUP, X
    REP #$20
    .a16
    INC a:esLOC
    LDA a:esLOC
    CMP #LOGIC_POOL
    BCS :+
    JMP @loc
:   CLC
    RTS

;;  Have location esLOC and location A the same masks?  C set if so.  Each
;;  is an antichain with no mask twice, so the same count and each of
;;  esLOC's among A's will do.
es_samemasks:
    .a16
    ASL A
    TAX
    LDA a:eMOFF, X
    STA a:esLI                  ; A's first mask...
    LDA a:eMOFF + 2, X
    STA a:esLE                  ; ...and end
    SEC
    SBC a:esLI
    STA a:esQ                   ; its bytes
    LDA a:esLOC
    ASL A
    TAX
    LDA a:eMOFF + 2, X
    STA a:esSE
    SEC
    SBC a:eMOFF, X
    CMP a:esQ
    BNE @no
    LDA a:eMOFF, X
    STA a:esSI
  @mine:
    LDA a:esSI
    CMP a:esSE
    BCS @yes
    TAY
    LDX a:esLI
  @theirs:
    CPX a:esLE
    BCS @no
    LDA a:eMASK, X
    CMP a:eMASK, Y
    BNE :+
    LDA a:eMASK + 2, X
    CMP a:eMASK + 2, Y
    BEQ @found
:   INX
    INX
    INX
    INX
    BRA @theirs
  @found:
    LDA a:esSI
    CLC
    ADC #4
    STA a:esSI
    BRA @mine
  @yes:
    SEC
    RTS
  @no:
    CLC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_dock -- where a ship found at location A is moored, on a shuffled
;;  wiring (randoref.es_dock): of FFR's five docks, those the party reaches
;;  whenever it reaches A -- each of A's masks that does not need the ship
;;  covers a mask of a boarding region's -- the nearest to A's entrances,
;;  walking if any can be walked to, else flying.  Coneria's always counts.
;;  In: A16 = the location.  Out: A16 = the dock.  A16, I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_dock:
    .a16
    .i16
    STA a:esLOC
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    STA a:esOWE
    AND #OWEDIT_DRYDOCK
    BEQ :+
    LDA #DOCK_DRYDOCK           ; Ship in Drydock: every ship is moored there
    RTS
:   JSR es_locents              ; esRM: its entrances
    LDA #$FFFF                  ; the best so far: kind (0 walk, 1 fly), its
    STA a:esOWN                 ;   distance, the dock
    STA a:esOWN + 2
    STZ a:esBIT                 ; the best dock
    STZ a:esD                   ; the dock asked about
  @dock:
    LDA a:esD
    CMP #GR_DOCKS
    BCC :+
    LDA a:esBIT
    RTS
:   LDA a:esD                   ; a dock under these map edits (Bridge to
    ASL A                       ;   Lefein deletes Matoya's)
    TAX
    LDA a:esOWE
    AND f:LOGICFAR + lut_GrDockCondOn, X
    CMP f:LOGICFAR + lut_GrDockCondOn, X
    BNE @nodock
    LDA a:esOWE
    AND f:LOGICFAR + lut_GrDockCondOff, X
    BNE @nodock
    JSR es_dockok
    BCS :+
  @nodock:
    JMP @next
:   ;  Its distance: the least walk from any of the entrances, else the
    ;  least flight.
    LDA #$FFFF
    STA a:esC                   ; walk
    LDA #$7FFF
    STA a:esC + 2               ; fly
    STZ a:esK                   ; the entrance
  @ent:
    LDA a:esK
    CMP #32
    BCS @have
    CMP #16
    BCS @hi
    ASL A
    TAX
    LDA f:WORLDFAR + esBit16, X
    AND a:esRM
    BRA :+
  @hi:
    SEC
    SBC #16
    ASL A
    TAX
    LDA f:WORLDFAR + esBit16, X
    AND a:esRM + 2
:   BEQ @nextent
    LDA a:esK                   ; entrance * GR_DOCKS + dock, in words
    ASL A
    ASL A
    CLC
    ADC a:esK
    CLC
    ADC a:esD
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrEntWalk, X
    CMP a:esC
    BCS :+
    STA a:esC
:   LDA f:LOGICFAR + lut_GrEntFly, X
    CMP a:esC + 2
    BCS @nextent
    STA a:esC + 2
  @nextent:
    INC a:esK
    BRA @ent
  @have:
    LDA a:esC                   ; (kind, distance): walking if any walk
    CMP #$FFFF
    BEQ @fly
    LDY #0
    BRA @key
  @fly:
    LDA a:esC + 2
    LDY #1
  @key:
    STA a:esQ
    CPY a:esOWN                 ; better than the best?  Kind first...
    BCC @better
    BNE @next
    LDA a:esQ                   ; ...then distance; the lower dock on a tie
    CMP a:esOWN + 2
    BCS @next
  @better:
    STY a:esOWN
    LDA a:esQ
    STA a:esOWN + 2
    LDA a:esD
    STA a:esBIT
  @next:
    INC a:esD
    JMP @dock

;;  Does dock esD qualify for location esLOC: does each of its masks without
;;  the ship cover some mask of one of the dock's boarding regions?  C set if
;;  so.
es_dockok:
    .a16
    LDA a:esLOC
    ASL A
    TAX
    LDA a:eMOFF + 2, X
    STA a:esLE
    LDA a:eMOFF, X
    STA a:esLI
  @mask:
    LDA a:esLI
    CMP a:esLE
    BCC :+
    SEC                         ; every one covered
    RTS
:   TAX
    LDA a:eMASK + (LBIT_SHIP / 16) * 2, X
    AND #1 << (LBIT_SHIP .MOD 16)
    BNE @nextmask               ; it needs the ship: no matter
    LDA a:eMASK, X
    STA a:esC
    LDA a:eMASK + 2, X
    STA a:esC + 2
    JSR es_boardcovers
    BCS @nextmask
    CLC
    RTS
  @nextmask:
    LDA a:esLI
    CLC
    ADC #4
    STA a:esLI
    BRA @mask

;;  Is some mask of dock esD's boarding regions within esC?  C set if so.
es_boardcovers:
    .a16
    LDA a:esD
    ASL A
    TAX
    LDA f:LOGICFAR + lut_GrDockOff + 2, X
    STA a:esSE
    LDA f:LOGICFAR + lut_GrDockOff, X
    STA a:esSI
  @node:
    LDA a:esSI
    CMP a:esSE
    BCC :+
    CLC
    RTS
:   TAX
    LDA f:LOGICFAR + lut_GrDockNodes, X
    AND #$00FF
    TAX
    LDA a:eNREQ, X
    AND #$00FF
    STA a:esNT
    TXA
    JSR es_reqaddr
    TAX
  @req:
    LDA a:esNT
    BEQ @nextnode
    DEC a:esNT
    LDA a:esC                   ; b & ~C == 0
    EOR #$FFFF
    AND a:0, X
    BNE :+
    LDA a:esC + 2
    EOR #$FFFF
    AND a:2, X
    BNE :+
    SEC
    RTS
:   INX
    INX
    INX
    INX
    BRA @req
  @nextnode:
    INC a:esSI
    BRA @node


;;  For the harness, after rando_esmasks: the dock for a ship at location A.
;;  Out: esTRY's high byte.
rando_esdock:
    .a8
    .i8
    PHB
    PHA
    JSR enter
    REP #$10
    .i16
    SEP #$20
    .a8
    PLA
    REP #$20
    .a16
    AND #$00FF
    JSR es_dock
    SEP #$20
    .a8
    STA a:esTRY + 1
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_build -- attempt k's world, for placement (place.inc, pl_shuffled):
;;  the wiring in the save's mode, its masks under the save's Early flags
;;  and map edits, placement's index of them, the roots and the spread
;;  groups.  With the mode Off, the vanilla wiring, for map edits without
;;  the shuffle (pl_edited).  In: A16 = k;
;;  native, DBR = $7F, from a JSL.  Out: C set if the attempt is refused.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_build:
    .a16
    .i16
    PHA
    LDA #ROLLSTAGE_WIRING       ; the roll screen's tune
    STA f:ROLL_STAGE
    PLA                         ; the attempt, es_start's
    JSR es_start
    SEP #$20
    .a8
    LDA f:RANDO_SAVEFAR + (RANDO_ENTRANCES - RANDO_SAVE)
    BNE @shuffle
    JSR es_vanilla              ; map edits without the shuffle: the vanilla
    CLC                         ;   wiring, its logic the seed's (pl_edited)
    BRA @wired
  @shuffle:
    JSR es_wiring
  @wired:
    REP #$20
    .a16
    BCS @out
    LDA #ROLLSTAGE_LOGIC
    STA f:ROLL_STAGE
    LDA f:RANDO_SAVEFAR + (RANDO_EARLY - RANDO_SAVE)
    AND #$00FF
    JSR es_fixpoint
    BCS @out
    JSR es_locmasks
    BCS @out
    JSR es_bybit
    BCS @out
    JSR es_roots
    JSR es_groups
  @out:
    RTL

;;  es_dock from a JSL: A16 = the location, out A16 = the dock.
es_dockfar:
    .a16
    .i16
    JSR es_dock
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  es_tables -- the teleport tables the game reads, in the cache: the save's
;;  wiring (attempt RANDO_ESK in its mode) when it has one -- the mode set and
;;  the key items placed, as New Game leaves them -- else vanilla.  From the
;;  cache build (rando.asm), native, DBR = $7F, by JSL.  Registers clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

es_tables:
    PHP
    SEP #$20
    .a8
    REP #$10
    .i16
    LDA f:RANDO_PLACEDFAR
    CMP #1
    BNE @vanilla
    LDA f:RANDO_SAVEFAR + (RANDO_ENTRANCES - RANDO_SAVE)
    BEQ @vanilla
    PHA
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_ESK - RANDO_SAVE)
    AND #$00FF
    JSR es_start
    SEP #$20
    .a8
    PLA
    JSR es_wiring
    BCC @tables
  @vanilla:
    JSR es_vanilla
  @tables:
    LDY #$0000
  @ent:
    TYX
    LDA a:eENT, X
    JSR es_landbytes
    TYX
    STA f:RW_ENTRMAP, X
    XBA
    STA f:RW_ENTRY, X
    LDA a:esLOC
    STA f:RW_ENTRX, X
    INY
    CPY #32
    BCC @ent
    LDY #$0000
  @norm:
    TYX
    LDA a:eNORM, X
    JSR es_landbytes
    TYX
    STA f:RW_NORMMAP, X
    XBA
    STA f:RW_NORMY, X
    LDA a:esLOC
    STA f:RW_NORMX, X
    INY
    CPY #64
    BCC @norm
    LDY #$0000
  @exit:
    TYX
    LDA a:eEXIT, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_GrExitX, X
    XBA
    LDA f:LOGICFAR + lut_GrExitY, X
    TYX
    STA f:RW_EXITY, X
    XBA
    STA f:RW_EXITX, X
    INY
    CPY #16
    BCC @exit
    PLP
    RTL

;;  Landing A8: A = its map, B (XBA) its y, esLOC its x -- with bit 7 set for
;;  a landing inside a room, FFR's StandardInRoom, which rando_entrdest and
;;  rando_teledest turn into inroom.  A8, I16.  Y kept.
es_landbytes:
    .a8
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_GrLandX, X
    ORA f:LOGICFAR + lut_GrLandRoom, X
    STA a:esLOC
    LDA f:LOGICFAR + lut_GrLandY, X
    XBA
    LDA f:LOGICFAR + lut_GrLandMap, X
    RTS
