; ---------------------------------------------------------------------------
;  entrance.inc -- entrance shuffle on the cart
;
;  Included by rando.asm, in its chunk.  tools/randoref.py's es_* routines are
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
.assert esEND + 2 <= .LOWORD(ES_WORDSEND), error, "the shuffle's words run past ES_VARS"

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
    JMP rando_warm

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
    LDA f:RANDOFAR + lut_Bit8, X
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
    JSR rando_below
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
    JSR rando_below
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
    LDA f:LOGICFAR + lut_EsOwCoord, X
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
    LDA f:RANDOFAR + lut_Bit8, X
    AND a:esN
    RTS
