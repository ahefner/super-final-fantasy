; ---------------------------------------------------------------------------
;  place.inc -- incentive placement: FFR's PredictivePlacement on the cart
;
;  Included by rando.asm, in its chunk.  tools/randoref.py's build_placement
;  is the same placement in Python, and test_rando_place holds the two to the
;  same result for every seed it tries; randoref.py's comment says where both
;  differ from FFR.
;
;  The logic is logic.inc's (tools/genlogic.py): 256 locations, each with the
;  minimal sets of key items and events that reach it.  Reaching is asked
;  incrementally.  What is reached with the items placed so far is kept, in
;  RP_REACH, and grows as items are placed; a bit gained asks again only of
;  the locations whose masks name it (lut_LogicByBit), and a location reached
;  that gives a bit -- an event, or a key item placed there -- gains that one
;  in turn.  To ask what one more item would open, the same walk runs from its
;  bit with its marks in RP_SEEN under a fresh RP_GEN, so nothing it marks
;  outlives the asking.  The sets are the ones the reference's plain fixpoint
;  finds, so the counts and the draws are too.
;
;  Native mode, DBR = $7F, A16 and I16 unless a routine says otherwise.
; ---------------------------------------------------------------------------

pMASK    = .LOWORD(RP_MASK)
pPLACED  = .LOWORD(RP_PLACED)
pREACH   = .LOWORD(RP_REACH)
pSEEN    = .LOWORD(RP_SEEN)
pWW      = .LOWORD(RP_WW)
pWI      = .LOWORD(RP_WI)
pNI      = .LOWORD(RP_NI)
pNN      = .LOWORD(RP_NN)
pB3      = .LOWORD(RP_B3)
pOWNED   = .LOWORD(RP_OWNED)
pNOTOWN  = .LOWORD(RP_NOTOWN)
pFREE    = .LOWORD(RP_FREE)
pPEND    = .LOWORD(RP_PEND)
pSAVE    = .LOWORD(RP_SAVE)
pREM     = .LOWORD(RP_REM)
pINC     = .LOWORD(RP_INC)
pINC0    = .LOWORD(RP_INC0)
pITEMS   = .LOWORD(RP_ITEMS)
pNREM    = .LOWORD(RP_NREM)
pINCSRC  = .LOWORD(RP_INCSRC)
pNONSRC  = .LOWORD(RP_NONSRC)
pCI      = .LOWORD(RP_CI)
pCN      = .LOWORD(RP_CN)
pCYCLE   = .LOWORD(RP_CYCLE)
pSTATE   = .LOWORD(RP_STATE)
pGEN     = .LOWORD(RP_GEN)
pMODE    = .LOWORD(RP_MODE)
pSPOT    = .LOWORD(RP_SPOT)
pNINCPOOL = .LOWORD(RP_NINCPOOL)
pACCESS  = .LOWORD(RP_ACCESS)
pWN      = .LOWORD(RP_WN)
pTOTAL   = .LOWORD(RP_TOTAL)
pW       = .LOWORD(RP_W)
pB0      = .LOWORD(RP_B0)
pB1      = .LOWORD(RP_B1)
pB2      = .LOWORD(RP_B2)
pRED     = .LOWORD(RP_RED)
pLO      = .LOWORD(RP_LO)
pHI      = .LOWORD(RP_HI)
pBRANCH  = .LOWORD(RP_BRANCH)
pNINCI   = .LOWORD(RP_NINCI)
pITEM    = .LOWORD(RP_ITEM)
pLOC     = .LOWORD(RP_LOC)
pT       = .LOWORD(RP_T)
pT2      = .LOWORD(RP_T2)
pATT     = .LOWORD(RP_ATT)
pK       = .LOWORD(RP_K)
pWCUR    = .LOWORD(RP_WCUR)
pBIT     = .LOWORD(RP_BIT)
pLI      = .LOWORD(RP_LI)
pLE      = .LOWORD(RP_LE)
pEND     = .LOWORD(RP_END)
pCNT     = .LOWORD(RP_CNT)
pBEST    = .LOWORD(RP_BEST)
pBESTI   = .LOWORD(RP_BESTI)
pWANT    = .LOWORD(RP_WANT)
pCLR0    = .LOWORD(RP_CLR0)
pCLR2    = .LOWORD(RP_CLR2)
pMOFF    = .LOWORD(RP_MOFF)
pBYOFF   = .LOWORD(RP_BYBITOFF)
pBYBIT   = .LOWORD(RP_BYBIT)
pCHAOS   = .LOWORD(RP_CHAOS)
pNCHAOS  = .LOWORD(RP_NCHAOS)
pGROUP   = .LOWORD(RP_GROUP)
pFWD     = .LOWORD(RP_FWD)
pGRP     = .LOWORD(RP_GRP)

W1             = 1024          ; a weight of 1.0
FWD_ONE        = 256           ; a place's forward weight, new (pl_forward)
NONKEY_MIN_CYCLE = 10
CRIT_NON       = 5
SAFE_NON       = 20
CRIT_INC       = 2
SAFE_INC       = 3
PI_CANOE       = 15            ; PLACE_ITEMS indices the loop names
PI_SHIP        = 16
PI_CANAL       = 18
;  The caravan, the last pool location; and what a shop can sell: key items
;  that are items, and the TAIL -- PLACE_ITEMS 0-14 and 19.
CARAVAN        = 247
CARAVAN_TREASURE = $FE
SHOPPABLE      = $00087FFF

.include "logic.inc"
.import lut_LogicKind, lut_LogicIdent, lut_LogicFlags, lut_LogicMaskLo, lut_LogicMaskHi
.import lut_LogicMasks, lut_LogicByBitLo, lut_LogicByBitHi, lut_LogicByBit, lut_LogicChaos
.import lut_LogicGroup

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_place -- place the key items for the new game in the save
;;
;;  From rando_newgame, once the settings are in the save.  Under Key items
;;  Standard or Wide, draws the placement and writes it to RANDO_PLACE with
;;  RANDO_PLACED set; under Vanilla, or if PLACE_ATTEMPTS tries all fail,
;;  clears RANDO_PLACED, and the key items stay where they are.
;;
;;  In: emulation mode, from a JSL.  Out: the same; A, X, Y clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_place:
    PHB
    JSR enter
    REP #$30
    .a16
    .i16
    LDX #pB3                    ; the last bin's marks, every word and mask
  @zero:                        ;   of the state
    STZ a:0, X
    INX
    INX
    CPX #.LOWORD(RP_WORDSEND)
    BCC @zero
    SEP #$20
    .a8
    LDA #$00
    STA f:RANDO_PLACEDFAR
    LDA f:RANDO_SAVEFAR + (RANDO_KEYITEMS - RANDO_SAVE)
    LDX #LOGIC_STANDARD
    LDY #LOGIC_NSTANDARD
    CMP #KEYITEMS_STANDARD
    BEQ @go
    LDX #LOGIC_WIDE
    LDY #LOGIC_NWIDE
    CMP #KEYITEMS_WIDE
    BEQ @go
    JMP leave
  @go:
    REP #$20
    .a16
    STX a:pSPOT
    STY a:pNINCPOOL
    JSR pl_masks
    JSR pl_vanilla
    JSR pl_items
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_KEYS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_KEYS)
    STA a:wRNG+2
    JSR rando_warm
    LDA #PLACE_ATTEMPTS
    STA a:pATT
  @try:
    JSR pl_attempt
    BCS @won
    DEC a:pATT
    BNE @try
    JMP leave                   ; none: key items stay where they are
  @won:
    JSR pl_store
    JMP leave


;;  The vanilla world's bit index, Chaos's masks and spread groups, copied
;;  into RAM, where placement reads them; under entrance shuffle the same
;;  tables are worked out for the seed instead (entrance.inc).
pl_vanilla:
    LDX #$0000
  @off:
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_LogicByBitHi, X
    XBA
    LDA f:LOGICFAR + lut_LogicByBitLo, X
    REP #$20
    .a16
    PHA
    TXA
    ASL A
    TAY
    PLA
    STA a:pBYOFF, Y
    INX
    CPX #33
    BCC @off
    LDX #$0000
  @entry:
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_LogicByBit, X
    STA a:pBYBIT, X
    REP #$20
    .a16
    INX
    CPX #LOGIC_BYBIT
    BCC @entry
    LDX #$0000
  @chaos:
    LDA f:LOGICFAR + lut_LogicChaos, X
    STA a:pCHAOS, X
    INX
    INX
    CPX #LOGIC_CHAOSMASKS * 4
    BCC @chaos
    LDA #LOGIC_CHAOSMASKS
    STA a:pNCHAOS
    LDX #$0000
  @group:
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_LogicGroup, X
    STA a:pGROUP, X
    REP #$20
    .a16
    INX
    CPX #LOGIC_POOL
    BCC @group
    RTS
.assert LOGIC_BYBIT <= RP_BYBITMAX, error, "the vanilla bit index does not fit RP_BYBIT"
.assert LOGIC_CHAOSMASKS <= RP_CHAOSMAX, error, "Chaos's vanilla masks do not fit RP_CHAOS"
.assert LOGIC_MASKS <= RP_MASKMAX, error, "the vanilla masks do not fit RP_MASK"


;;  RP_MASK: logic.inc's masks, with each location's Early waiver applied
;;  when its flag is on in the save.
pl_masks:
    STZ a:pLOC
  @loc:
    LDA #$FFFF                  ; what to keep of each word: everything...
    STA a:pCLR0
    STA a:pCLR2
    LDX a:pLOC
    LDA f:LOGICFAR + lut_LogicFlags, X
    AND #$0070
    BEQ @copy                   ; ...unless an Early flag waives something here
    LSR A
    LSR A
    LSR A
    LSR A
    DEC A
    TAX                         ; its RANDO_EARLY bit number
    LDA f:RANDO_SAVEFAR + (RANDO_EARLY - RANDO_SAVE)
    AND f:RANDOFAR + lut_Bit8, X
    AND #$00FF
    BEQ @copy                   ; not on
    LDA f:RANDOFAR + lut_EarlyLBit, X
    AND #$00FF
    JSR pl_bitword
    EOR #$FFFF
    CPY #$0000
    BNE @hi
    STA a:pCLR0
    BRA @copy
  @hi:
    STA a:pCLR2
  @copy:
    LDX a:pLOC
    JSR pl_maskrange
    STY a:pEND
    LDA a:pLOC                  ; where its masks start, for pl_sat
    ASL A
    TAY
    TXA
    STA a:pMOFF, Y
    LDA a:pEND
    STA a:pMOFF + 2, Y          ; (the last location's end too)
  @mask:
    CPX a:pEND
    BCS @next
    LDA f:LOGICFAR + lut_LogicMasks, X
    AND a:pCLR0
    STA a:pMASK, X
    LDA f:LOGICFAR + lut_LogicMasks + 2, X
    AND a:pCLR2
    STA a:pMASK + 2, X
    INX
    INX
    INX
    INX
    BRA @mask
  @next:
    INC a:pLOC
    LDA a:pLOC
    CMP #LOGIC_LOCS
    BCS :+
    JMP @loc
:   RTS


;;  RP_FREE, RP_ITEMS and RP_INC0 from the key item rows in the save: a Free
;;  row's bit is owned from the start (AIRSHIP's the airship's too), every
;;  other row's item is placed, an incentive unless it is Loose.  Other items
;;  is nine items at once; a gear row is placed only as an incentive.
pl_items:
    STZ a:pT
  @row:
    JSR pl_rowval
    CMP #ITEM_MODES
    BCC :+
    LDA #ITEM_INCENTIVE         ; a value this build does not know
:   STA a:pT2
    LDX a:pT
    LDA f:RANDOFAR + lut_ItemRowItem, X
    AND #$00FF
    STA a:pITEM
    LDA a:pT2
    CMP #ITEM_FREE
    BNE @place
    LDA a:pITEM
    CMP #PLACE_KEYS
    BCS @airship                ; the TAIL opens nothing
    TAX
    LDA f:RANDOFAR + lut_PlaceLBit, X
    AND #$00FF
    JSR pl_bitword
    ORA a:pFREE, Y
    STA a:pFREE, Y
  @airship:
    LDA a:pT
    CMP #ITEMROW_AIRSHIP
    BNE @next
    LDA #LBIT_AIRSHIP
    JSR pl_bitword
    ORA a:pFREE, Y
    STA a:pFREE, Y
    BRA @next
  @place:
    LDA a:pITEM
    JSR pl_additem
  @next:
    INC a:pT
    LDA a:pT
    CMP #ITEMROW_OTHER
    BCC @row

    JSR pl_rowval               ; Other items
    CMP #ITEMOTHER_MODES
    BCC :+
    LDA #ITEM_INCENTIVE
:   STA a:pT2
    LDX #$0000
  @other:
    STX a:pK
    LDA f:RANDOFAR + lut_OtherItems, X
    AND #$00FF
    JSR pl_additem
    LDX a:pK
    INX
    CPX #9
    BCC @other

    ;  The gear rows' bits are items PLACE_GEAR up, in order: the high word's
    ;  bits 4-12.
    LDA f:RANDO_SAVEFAR + (RANDO_GEAR - RANDO_SAVE)
    AND #$01FF
    ASL A
    ASL A
    ASL A
    ASL A
    PHA
    ORA a:pITEMS + 2
    STA a:pITEMS + 2
    PLA
    ORA a:pINC0 + 2
    STA a:pINC0 + 2
    RTS

;;  Item A is placed, an incentive unless pT2 says Loose.
pl_additem:
    JSR pl_bitword
    PHA
    ORA a:pITEMS, Y
    STA a:pITEMS, Y
    PLA
    LDX a:pT2
    BNE :+
    ORA a:pINC0, Y
    STA a:pINC0, Y
:   RTS

;;  Row pT's value: two bits of RANDO_ITEMS, four rows to a byte.
pl_rowval:
    LDA a:pT
    LSR A
    LSR A
    TAX
    LDA f:RANDO_SAVEFAR + (RANDO_ITEMS - RANDO_SAVE), X
    AND #$00FF
    STA a:pW
    LDA a:pT
    AND #$0003
    TAX
    LDA a:pW
  @shift:
    DEX
    BMI @field
    LSR A
    LSR A
    BRA @shift
  @field:
    AND #$0003
    RTS


;;  One attempt.  Out: C set if every item was placed and the seed is won.
pl_attempt:
    LDA a:pINC0
    STA a:pINC
    LDA a:pINC0 + 2
    STA a:pINC + 2
  @trim:                        ; more incentives than spots: a random one goes
    LDX #pINC                   ;   loose, until they fit
    JSR pl_count
    CMP a:pNINCPOOL
    BEQ @fits
    BCC @fits
    SEP #$20
    .a8
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    LDX #pINC
    JSR pl_dropnth
    BRA @trim
  @fits:
    LDA a:pITEMS
    STA a:pREM
    LDA a:pITEMS + 2
    STA a:pREM + 2
    LDX #pREM
    JSR pl_count
    STA a:pNREM
    LDX #$0000
  @clear:
    LDA #$FFFF
    STA a:pPLACED, X
    STZ a:pREACH, X
    STZ a:pSEEN, X
    INX
    INX
    CPX #256
    BCC @clear
    LDA #FWD_ONE                ; every place's forward weight, new
    LDX #$0000
  @fwd:
    STA a:pFWD, X
    INX
    INX
    CPX #LOGIC_POOL * 2
    BCC @fwd
    JSR pl_vendor
    STZ a:pGEN
    STZ a:pINCSRC
    STZ a:pNONSRC
    STZ a:pMODE
    STZ a:pPEND
    STZ a:pPEND + 2
    LDA a:pFREE
    STA a:pOWNED
    LDA a:pFREE + 2
    STA a:pOWNED + 2
    JSR pl_notown
    STZ a:pLOC                  ; what the start reaches
  @scan:
    LDX a:pLOC
    JSR pl_sat
    BCC :+
    JSR pl_mark
:   INC a:pLOC
    LDA a:pLOC
    CMP #LOGIC_LOCS
    BCC @scan
    JSR pl_propagate
    LDA #PSTATE_NORMAL
    STA a:pSTATE
    LDA #1
    STA a:pCYCLE

  @cycle:
    LDA a:pINCSRC
    CLC
    ADC a:pNONSRC
    STA a:pACCESS

    ;  What each key item still to place would open: its new incentive and
    ;  other places, less the one it would take itself.
    STZ a:pK
  @cand:
    LDA a:pK
    JSR pl_inrem
    BEQ @candnext
    LDX a:pK
    LDA f:RANDOFAR + lut_PlaceLBit, X
    AND #$00FF
    JSR pl_bitword
    STA a:pPEND, Y
    JSR pl_ask
    LDA a:pK
    JSR pl_owncount
    LDA a:pK
    ASL A
    TAX
    LDA a:pCI
    STA a:pNI, X
    LDA a:pCN
    STA a:pNN, X
  @candnext:
    INC a:pK
    LDA a:pK
    CMP #PLACE_KEYS
    BCC @cand

    ;  The ship and the canal may open nothing alone and much together: each
    ;  is credited with half of what both open, if that is more.
    LDA #PI_SHIP
    JSR pl_inrem
    BEQ @noboth
    LDA #PI_CANAL
    JSR pl_inrem
    BEQ @noboth
    LDA #LBIT_SHIP
    JSR pl_bitword
    ORA a:pPEND, Y
    STA a:pPEND, Y
    LDA #LBIT_CANAL
    JSR pl_bitword
    ORA a:pPEND, Y
    STA a:pPEND, Y
    JSR pl_ask
    LDA #PI_SHIP
    JSR pl_owncount
    LDA #PI_CANAL
    JSR pl_owncount
    LDA a:pCI
    CMP #$8000                  ; halved, rounding down, as Python's //
    ROR A
    STA a:pCI
    LDA a:pCN
    CMP #$8000
    ROR A
    STA a:pCN
    LDX #PI_SHIP * 2
    JSR pl_raise
    LDX #PI_CANAL * 2
    JSR pl_raise
  @noboth:

    ;  Incentives still to place.
    LDA a:pREM
    AND a:pINC
    STA a:pSAVE
    LDA a:pREM + 2
    AND a:pINC + 2
    STA a:pSAVE + 2
    LDX #pSAVE
    JSR pl_count
    STA a:pNINCI

    ;  Which draw: incentives or the rest.
    LDA a:pSTATE
    CMP #PSTATE_INCENTIVE
    BEQ @incdraw
    CMP #PSTATE_NORMAL
    BEQ :+
    JMP @nondraw
:   SEP #$20
    .a8
    LDA a:pNREM
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    CMP a:pNINCI
    BCC @incdraw
    JMP @nondraw

  @incdraw:
    LDA #1
    STA a:pBRANCH
    STZ a:pWN
    LDA a:pINCSRC
    CMP #2
    BCC @inccrit                ; one place or none
    BNE @incmore
    LDA #PI_SHIP                ; two, and both the ship and the canal to come
    JSR pl_inrem
    BEQ @incsafe
    LDA #PI_CANAL
    JSR pl_inrem
    BNE @inccrit
    BRA @incsafe
  @incmore:
    CMP #SAFE_INC + 1
    BCC @incsafe
    LDA #W1                     ; plenty
    LDX #W1
    LDY #W1
    JSR pl_setbins
    LDA #W1 / 4
    LDX #2
    JSR pl_setlast
    LDA #1
    LDX #2
    JSR pl_setedges
    JSR pl_bins
    LDA #W1
    JSR pl_nonkey
    BRA @inctotal
  @inccrit:
    LDA #0
    LDX #W1 / 2
    LDY #W1
    JSR pl_setbins
    LDA #W1
    LDX #1
    JSR pl_setlast
    LDA #1
    LDX #2
    JSR pl_setedges
    JSR pl_bins
    BRA @inctotal
  @incsafe:
    LDA #W1 / 2
    LDX #W1 / 2
    LDY #W1
    JSR pl_setbins
    LDA #W1 / 2
    LDX #2
    JSR pl_setlast
    LDA #1
    LDX #2
    JSR pl_setedges
    JSR pl_bins
    LDA #W1 / 2
    JSR pl_nonkey
  @inctotal:
    JSR pl_total
    BEQ :+
    JMP @draw
:
    LDA a:pNINCI                ; nothing weighs anything: any incentive, if
    CMP a:pINCSRC               ;   there are places enough for all of them
    BEQ :+
    BCS @incnone
:   STZ a:pK
  @every:
    LDA a:pK
    JSR pl_inrem
    BEQ :+
    LDA a:pK
    JSR pl_isinc
    BEQ :+
    LDA #W1
    JSR pl_append
:   INC a:pK
    LDA a:pK
    CMP #PLACE_ITEMS
    BCC @every
    JSR pl_total
    BEQ @incnone
    JMP @draw
  @incnone:
    LDA #PSTATE_NONINCENTIVE
    JMP @stuck

  @nondraw:
    STZ a:pBRANCH
    STZ a:pWN
    LDA a:pNONSRC
    CMP #CRIT_NON + 1
    BCS @nonmore
    LDA #0
    LDX #W1 / 2
    LDY #W1
    JSR pl_setbins
    LDA #W1
    LDX #1
    JSR pl_setlast
    LDA #5
    LDX #20
    JSR pl_setedges
    JSR pl_bins
    BRA @nontotal
  @nonmore:
    CMP #SAFE_NON + 1
    BCS @nonplenty
    LDA #W1 / 2
    LDX #W1 / 2
    LDY #W1
    JSR pl_setbins
    LDA #W1 / 2
    LDX #2
    JSR pl_setlast
    LDA #5
    LDX #20
    JSR pl_setedges
    JSR pl_bins
    LDA #W1 / 2
    JSR pl_nonkey
    BRA @nontotal
  @nonplenty:
    LDA #W1
    LDX #W1
    LDY #W1
    JSR pl_setbins
    LDA #W1 / 4
    LDX #2
    JSR pl_setlast
    LDA #5
    LDX #20
    JSR pl_setedges
    JSR pl_bins
    LDA #W1
    JSR pl_nonkey
  @nontotal:
    JSR pl_first
    JSR pl_total
    BNE @draw
    LDA #PSTATE_INCENTIVE

    ;  Neither draw has anything: try the other one next cycle, unless both
    ;  have come up empty this late.
  @stuck:
    TAX
    LDA a:pCYCLE
    CMP #15
    BCC :+
    LDA a:pSTATE
    CMP #PSTATE_NORMAL
    BEQ :+
    CLC
    RTS
:   STX a:pSTATE
    JMP @nextcycle

  @draw:
    JSR rando_below16
    LDX #$0000                  ; walk the weights to it
  @walk:
    CMP a:pWW, X
    BCC @drawn
    SEC
    SBC a:pWW, X
    INX
    INX
    BRA @walk
  @drawn:
    TXA
    LSR A
    TAX
    LDA a:pWI, X
    AND #$00FF
    STA a:pITEM

    ;  And where: an empty place reached, a spot for an incentive and not for
    ;  anything else.
    JSR pl_isinc
    BEQ :+
    LDA #1
:   STA a:pWANT
    BEQ @wantnon
    LDA a:pINCSRC
    BRA @where
  @wantnon:
    LDA a:pNONSRC
  @where:
    BNE :+
    JMP @nextcycle              ; nowhere: the cycle is spent
:   LDA a:pWANT
    BNE @uniform
    JSR pl_forward              ; not an incentive: forward placement's draw
    BRA @found
  @uniform:                     ; an incentive: any spot alike
    LDA a:pINCSRC               ; the bound, which pWANT's test took from A
    SEP #$20
    .a8
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    STA a:pK
    LDX #$0000
  @find:
    LDA a:pREACH, X
    AND #$00FF
    BEQ @findnext
    LDA a:pPLACED, X
    AND #$00FF
    CMP #$00FF
    BNE @findnext
    JSR pl_isspot
    CMP a:pWANT
    BNE @findnext
    LDA a:pK
    BEQ @found
    DEC a:pK
  @findnext:
    INX
    BRA @find
  @found:
    STX a:pLOC
    SEP #$20
    .a8
    LDA a:pITEM
    STA a:pPLACED, X
    REP #$20
    .a16
    LDA a:pWANT
    BEQ :+
    DEC a:pINCSRC
    BRA :++
:   DEC a:pNONSRC
:   DEC a:pNREM
    LDA a:pITEM
    JSR pl_bitword
    EOR #$FFFF
    AND a:pREM, Y
    STA a:pREM, Y
    LDA a:pITEM
    CMP #PLACE_KEYS
    BCS :+
    TAX
    LDA f:RANDOFAR + lut_PlaceLBit, X
    AND #$00FF
    JSR pl_gain
    JSR pl_propagate
:   LDA #PSTATE_NORMAL
    STA a:pSTATE
    LDA a:pNREM
    BEQ @placed

  @nextcycle:
    INC a:pCYCLE
    LDA a:pCYCLE
    CMP #101
    BCS :+
    JMP @cycle
:   CLC                         ; a hundred cycles and items still to place
    RTS

  @placed:
    LDX #$0000                  ; and the seed is won: Chaos reached
  @chaos:
    TXA                         ; (none of Chaos's masks met, or none at all:
    LSR A                       ;   a wiring nothing reaches Chaos in)
    LSR A
    CMP a:pNCHAOS
    BCS @lost
    LDA a:pCHAOS, X
    AND a:pNOTOWN
    BNE :+
    LDA a:pCHAOS + 2, X
    AND a:pNOTOWN + 2
    BEQ @won
:   INX
    INX
    INX
    INX
    BRA @chaos
  @lost:
    CLC
    RTS
  @won:
    SEC
    RTS


;;  FFR's SelectVendorItem: the caravan stocked before the loop, which never
;;  places there -- a random one of the incentives a shop can sell, or, with
;;  none of those, ordinary treasure, which the rewards deal.
pl_vendor:
    LDA a:pINC
    AND #.LOWORD(SHOPPABLE)
    STA a:pSAVE
    LDA a:pINC + 2
    AND #.HIWORD(SHOPPABLE)
    STA a:pSAVE + 2
    LDX #pSAVE
    JSR pl_count
    BNE @stock
    SEP #$20
    .a8
    LDA #CARAVAN_TREASURE
    STA a:pPLACED + CARAVAN
    REP #$20
    .a16
    RTS
  @stock:
    SEP #$20
    .a8
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    STA a:pT                    ; the A'th of them, in item order
    STZ a:pBIT
  @bit:
    LDA a:pBIT
    JSR pl_bitword
    AND a:pSAVE, Y
    BEQ @next
    LDA a:pT
    BEQ @found
    DEC a:pT
  @next:
    INC a:pBIT
    BRA @bit
  @found:
    LDA a:pBIT
    SEP #$20
    .a8
    STA a:pPLACED + CARAVAN
    REP #$20
    .a16
    DEC a:pNREM
    LDA a:pBIT
    JSR pl_bitword
    EOR #$FFFF
    AND a:pREM, Y
    STA a:pREM, Y
    RTS

;;  Item A's own place, out of what it would open: an incentive spot if it is
;;  one, another place if not.
pl_owncount:
    JSR pl_isinc
    BEQ :+
    DEC a:pCI
    RTS
:   DEC a:pCN
    RTS

;;  The ship's or the canal's counts at X (item * 2) raised to pCI and pCN,
;;  where those are more and there is more than one place of the kind.
pl_raise:
    LDA a:pINCSRC
    CMP #2
    BCC @non
    LDA a:pNI, X
    SEC
    SBC a:pCI
    BVC :+
    EOR #$8000
:   BPL @non                    ; already at least as many
    LDA a:pCI
    STA a:pNI, X
  @non:
    LDA a:pNONSRC
    CMP #2
    BCC @out
    LDA a:pNN, X
    SEC
    SBC a:pCN
    BVC :+
    EOR #$8000
:   BPL @out
    LDA a:pCN
    STA a:pNN, X
  @out:
    RTS


;;  The bins' weights: A for a negative count, X below the low edge, Y below
;;  the high.
pl_setbins:
    STA a:pB0
    STX a:pB1
    STY a:pB2
    RTS

;;  The last bin's first weight, A, and how far each next one shifts down, X.
pl_setlast:
    STA a:pW
    STX a:pRED
    RTS

;;  The edges: A the low, X the high.
pl_setedges:
    STA a:pLO
    STX a:pHI
    RTS

;;  The draw's key items: each still to place, of the draw's kind, weighted by
;;  its bin -- in item order, then those past the high edge in order of how
;;  much they open, each weighing less than the one before.
pl_bins:
    STZ a:pK
  @item:
    JSR pl_mine
    BEQ @skip
    LDA a:pK
    ASL A
    TAX
    LDA a:pBRANCH
    BEQ :+
    LDA a:pNI, X
    BRA :++
:   LDA a:pNN, X
:   BMI @b0
    CMP a:pLO
    BCC @b1
    CMP a:pHI
    BCC @b2
    LDX a:pK                    ; past both edges: kept for the last bin
    SEP #$20
    .a8
    LDA #1
    STA a:pB3, X
    REP #$20
    .a16
    BRA @skip
  @b0:
    LDA a:pB0
    BRA @add
  @b1:
    LDA a:pB1
    BRA @add
  @b2:
    LDA a:pB2
  @add:
    JSR pl_weight
    JSR pl_append
  @skip:
    INC a:pK
    LDA a:pK
    CMP #PLACE_KEYS
    BCC @item

    LDA a:pW
    STA a:pWCUR
  @last:
    LDA #$FFFF                  ; the least count kept, the lowest item on a tie
    STA a:pBEST
    STA a:pBESTI
    LDX #$0000
  @scan:
    LDA a:pB3, X
    AND #$00FF
    BEQ @scannext
    TXA
    ASL A
    TAY
    LDA a:pBRANCH
    BEQ :+
    LDA a:pNI, Y
    BRA :++
:   LDA a:pNN, Y
:   CMP a:pBEST
    BCS @scannext
    STA a:pBEST
    STX a:pBESTI
  @scannext:
    INX
    CPX #PLACE_KEYS
    BCC @scan
    LDX a:pBESTI
    BMI @done
    SEP #$20
    .a8
    STZ a:pB3, X
    REP #$20
    .a16
    STX a:pK
    LDA a:pWCUR
    JSR pl_weight
    JSR pl_append
    LDX a:pRED
    LDA a:pWCUR
  @shift:
    LSR A
    DEX
    BNE @shift
    STA a:pWCUR
    BRA @last
  @done:
    RTS

;;  The draw's other entries: the TAIL and gear still to place, of its kind,
;;  each at A.
pl_nonkey:
    STA a:pWCUR
    LDA #PLACE_KEYS
    STA a:pK
  @item:
    JSR pl_mine
    BEQ :+
    LDA a:pWCUR
    JSR pl_weight
    JSR pl_append
:   INC a:pK
    LDA a:pK
    CMP #PLACE_ITEMS
    BCC @item
    RTS

;;  Is item pK still to place, and of this draw's kind?  Z clear if so.
pl_mine:
    LDA a:pK
    JSR pl_inrem
    BEQ @no
    LDA a:pK
    JSR pl_isinc
    BEQ :+
    LDA #1
:   EOR a:pBRANCH
    BEQ @yes
  @no:
    LDA #0
    RTS
  @yes:
    LDA #1
    RTS

;;  Item pK's weight at bin weight A: none before its cycle or with too few
;;  places reached; the TAIL and gear at half, from cycle ten; a key item at
;;  its share, in quarters.
pl_weight:
    STA a:pT
    LDX a:pK
    LDA f:RANDOFAR + lut_PlaceMinAccess, X
    AND #$00FF
    STA a:pT2
    LDA a:pACCESS
    CMP a:pT2
    BCC @none
    LDA f:RANDOFAR + lut_PlaceMinCycle, X
    AND #$00FF
    STA a:pT2
    LDA a:pCYCLE
    CMP a:pT2
    BCC @none
    CPX #PLACE_KEYS
    BCS @nonkey
    LDA f:RANDOFAR + lut_PlaceQ, X
    AND #$00FF
    TAY
    LDA #0
  @mul:
    CLC
    ADC a:pT
    DEY
    BNE @mul
    LSR A
    LSR A
    RTS
  @nonkey:
    LDA a:pCYCLE
    CMP #NONKEY_MIN_CYCLE
    BCC @none
    LDA a:pT
    LSR A
    RTS
  @none:
    LDA #0
    RTS

;;  The draw gains item pK at weight A.
pl_append:
    PHA
    LDA a:pWN
    ASL A
    TAX
    PLA
    STA a:pWW, X
    LDX a:pWN
    SEP #$20
    .a8
    LDA a:pK
    STA a:pWI, X
    REP #$20
    .a16
    INC a:pWN
    RTS

;;  The draw's weights' sum, in A and pTOTAL; Z set if nothing weighs.
pl_total:
    LDA #0
    LDX #$0000
  @sum:
    CPX a:pWN
    BCS @out
    PHX
    PHA
    TXA
    ASL A
    TAX
    PLA
    CLC
    ADC a:pWW, X
    PLX
    INX
    BRA @sum
  @out:
    STA a:pTOTAL
    CMP #$0000                  ; Z set if nothing weighs
    RTS


;;  Location X: is it a spot of the setting's kind?  A = 1 if so, else 0.
pl_isspot:
    LDA f:LOGICFAR + lut_LogicFlags, X
    AND a:pSPOT
    AND #$00FF
    BEQ :+
    LDA #1
:   RTS

;;  Progression first (user, 2026-10-14; randoref.py's _first): in the
;;  loose draw, while any loose key item that weighs something would open a
;;  place -- pNN 0 or more, its own place taken off -- the entries that would
;;  open none, and loose gear, are made to weigh nothing.  Held back, they are
;;  placed once nothing would open anything, rather than filling the few
;;  places reached at the start.  Not FFR's.
pl_first:
    LDX #$0000
  @any:
    CPX a:pWN
    BCS @out                    ; nothing opens anything: the draw as it is
    JSR pl_opens
    BCC @next
    TXA
    ASL A
    TAY
    LDA a:pWW, Y
    BNE @hold
  @next:
    INX
    BRA @any
  @hold:
    LDX #$0000
  @each:
    CPX a:pWN
    BCS @out
    JSR pl_opens
    BCS :+
    TXA
    ASL A
    TAY
    LDA #0
    STA a:pWW, Y
:   INX
    BRA @each
  @out:
    RTS

;;  Does draw entry X's item open a place: a key item whose pNN is 0 or more?
;;  C set if so.  X kept.
pl_opens:
    LDA a:pWI, X
    AND #$00FF
    CMP #PLACE_KEYS
    BCS @no                     ; gear opens nothing
    ASL A
    TAY
    LDA a:pNN, Y
    BMI @no
    SEC
    RTS
  @no:
    CLC
    RTS

;;  Forward placement (user, 2026-10-14; randoref.py's _forward): an item
;;  that is not an incentive goes to a place drawn by weight, and every place
;;  that could have taken it then has its weight halved, to no less than 1.
;;  A place reached from the start has lost most of its weight by the time a
;;  new area opens, so the new area's places are the likelier.  Then the
;;  chests in the drawn one's spread group -- one dungeon, one set of
;;  requirements (lut_LogicGroup) -- are quartered, to no less than 1, so the
;;  next item likelier goes to another dungeon.  FFR's forward and spread
;;  placement.  The weights start each attempt at FWD_ONE; 248 of them come
;;  to under $10000, so one word holds the sum.
;;
;;  Out: X = the place.  pTOTAL, pK and pW clobbered: the item's draw is done.
pl_forward:
    STZ a:pTOTAL
    LDX #$0000
  @sum:
    JSR pl_fwdok
    BCC :+
    TXA
    ASL A
    TAY
    LDA a:pFWD, Y
    CLC
    ADC a:pTOTAL
    STA a:pTOTAL
:   INX
    CPX #LOGIC_POOL
    BCC @sum
    LDA a:pTOTAL
    JSR rando_below16
    STA a:pK                    ; how far into the weights the draw lands
    LDA #$FFFF
    STA a:pLOC                  ; nowhere yet
    LDX #$0000
  @walk:
    JSR pl_fwdok
    BCC @next
    TXA
    ASL A
    TAY
    LDA a:pFWD, Y
    STA a:pW
    LDA a:pLOC
    BPL @halve                  ; drawn already: only the halving
    LDA a:pK
    CMP a:pW
    BCS @past
    STX a:pLOC                  ; the draw lands here
    BRA @halve
  @past:
    SBC a:pW                    ; C set
    STA a:pK
  @halve:
    LDA a:pW
    CMP #2
    BCC @next                   ; 1 stays 1
    LSR A
    STA a:pFWD, Y
  @next:
    INX
    CPX #LOGIC_POOL
    BCC @walk
    LDX a:pLOC                  ; spread: its group, quartered
    LDA a:pGROUP, X
    AND #$00FF
    CMP #LOGIC_NOGROUP
    BEQ @done
    STA a:pGRP
    LDX #$0000
  @spread:
    JSR pl_fwdok
    BCC @snext
    LDA a:pGROUP, X
    AND #$00FF
    CMP a:pGRP
    BNE @snext
    TXA
    ASL A
    TAY
    LDA a:pFWD, Y
    LSR A
    LSR A
    BNE :+
    LDA #1                      ; no less than 1
:   STA a:pFWD, Y
  @snext:
    INX
    CPX #LOGIC_POOL
    BCC @spread
  @done:
    LDX a:pLOC
    RTS

;;  Is place X one forward placement draws from: reached, empty, and not an
;;  incentive spot?  C set if so.  X kept.
pl_fwdok:
    LDA a:pREACH, X
    AND #$00FF
    BEQ @no
    LDA a:pPLACED, X
    AND #$00FF
    CMP #$00FF
    BNE @no
    JSR pl_isspot
    BNE @no
    SEC
    RTS
  @no:
    CLC
    RTS

;;  Is item A still to place?  Z clear if so.  X kept.
pl_inrem:
    JSR pl_bitword
    AND a:pREM, Y
    RTS

;;  Is item A an incentive, this attempt?  Z clear if so.  X kept.
pl_isinc:
    JSR pl_bitword
    AND a:pINC, Y
    RTS

;;  Bit A (0-31) of a four-byte mask: A = its word's mask, Y = the word's
;;  offset, 0 or 2.  X kept.
pl_bitword:
    PHX
    PHA
    AND #$0010
    LSR A
    LSR A
    LSR A
    TAY
    PLA
    AND #$000F
    ASL A
    TAX
    LDA f:RANDOFAR + lut_Bit16, X
    PLX
    RTS

;;  The set bits of the four-byte mask at X.  Out: A; Y clobbered.
pl_count:
    STZ a:pCNT
    LDA a:0, X
    JSR @word
    LDA a:2, X
  @word:
    STA a:pT2
    LDY #16
  @bit:
    LSR a:pT2
    BCC :+
    INC a:pCNT
:   DEY
    BNE @bit
    LDA a:pCNT
    RTS

;;  Clear the A'th set bit, counting from bit 0, of the four-byte mask at X.
pl_dropnth:
    STA a:pT                    ; how many set bits to pass
    STX a:pT2                   ; the mask
    STZ a:pBIT
  @bit:
    LDA a:pBIT
    JSR pl_bitword
    STA a:pCNT                  ; the bit, in its word...
    TYA
    CLC
    ADC a:pT2
    TAX                         ; ...and the word
    LDA a:pCNT
    AND a:0, X
    BEQ @next
    LDA a:pT
    BEQ @drop
    DEC a:pT
  @next:
    INC a:pBIT
    BRA @bit
  @drop:
    LDA a:pCNT
    EOR #$FFFF
    AND a:0, X
    STA a:0, X
    RTS

;;  RP_NOTOWN from RP_OWNED.
pl_notown:
    LDA a:pOWNED
    EOR #$FFFF
    STA a:pNOTOWN
    LDA a:pOWNED + 2
    EOR #$FFFF
    STA a:pNOTOWN + 2
    RTS

;;  Location X: where its masks are in RP_MASK.  Out: X the first's offset,
;;  Y past the last.
pl_maskrange:
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_LogicMaskHi + 1, X
    XBA
    LDA f:LOGICFAR + lut_LogicMaskLo + 1, X
    REP #$20
    .a16
    ASL A
    ASL A
    TAY
    SEP #$20
    .a8
    LDA f:LOGICFAR + lut_LogicMaskHi, X
    XBA
    LDA f:LOGICFAR + lut_LogicMaskLo, X
    REP #$20
    .a16
    ASL A
    ASL A
    TAX
    RTS

;;  Is location X reached with what is owned: is one of its masks inside it?
;;  Out: C.  X, Y clobbered.
pl_sat:
    TXA
    ASL A
    TAY
    LDA a:pMOFF + 2, Y
    STA a:pEND
    LDX a:pMOFF, Y
  @mask:
    CPX a:pEND
    BCS @no
    LDA a:pMASK, X
    AND a:pNOTOWN
    BNE @next
    LDA a:pMASK + 2, X
    AND a:pNOTOWN + 2
    BEQ @yes
  @next:
    INX
    INX
    INX
    INX
    BRA @mask
  @yes:
    SEC
    RTS
  @no:
    CLC
    RTS

;;  Location pLOC is reached: marked -- for good, or for this candidate -- and
;;  counted if it is an empty place, or what it gives gained: an event's bit,
;;  or a key item placed there.
pl_mark:
    LDX a:pLOC
    SEP #$20
    .a8
    LDA a:pMODE
    BNE @asking
    LDA #1
    STA a:pREACH, X
    BRA @marked
  @asking:
    LDA a:pGEN
    STA a:pSEEN, X
  @marked:
    REP #$20
    .a16
    CPX #LOGIC_POOL
    BCS @event
    LDA a:pPLACED, X
    AND #$00FF
    CMP #$00FF
    BEQ @empty
    CMP #PLACE_KEYS
    BCS @out                    ; the TAIL and gear open nothing
    TAX
    LDA f:RANDOFAR + lut_PlaceLBit, X
    AND #$00FF
    JMP pl_gain
  @event:
    LDA f:LOGICFAR + lut_LogicIdent, X
    AND #$00FF
    JMP pl_gain
  @empty:
    JSR pl_isspot
    BEQ @other
    LDA a:pMODE
    BNE :+
    INC a:pINCSRC
    RTS
:   INC a:pCI
    RTS
  @other:
    LDA a:pMODE
    BNE :+
    INC a:pNONSRC
    RTS
:   INC a:pCN
  @out:
    RTS

;;  Bit A gained: owned, and to be asked about, unless it already was.
pl_gain:
    JSR pl_bitword
    STA a:pT
    AND a:pOWNED, Y
    BNE @had
    LDA a:pT
    ORA a:pOWNED, Y
    STA a:pOWNED, Y
    EOR #$FFFF
    STA a:pNOTOWN, Y
    LDA a:pT
    ORA a:pPEND, Y
    STA a:pPEND, Y
  @had:
    RTS

;;  Until no bit gained is left to ask about: take the lowest, and ask again of
;;  each location its list names that is not yet reached.
pl_propagate:
  @next:
    LDX #$0000
    LDA a:pPEND
    BNE @find
    LDX #16
    LDA a:pPEND + 2
    BNE @find
    RTS
  @find:
    LSR A
    BCS @got
    INX
    BRA @find
  @got:
    STX a:pBIT
    TXA
    JSR pl_bitword
    EOR #$FFFF
    AND a:pPEND, Y
    STA a:pPEND, Y
    LDA a:pBIT
    ASL A
    TAX
    LDA a:pBYOFF + 2, X
    STA a:pLE
    LDA a:pBYOFF, X
    STA a:pLI
  @list:
    LDA a:pLI
    CMP a:pLE
    BCS @next
    INC a:pLI
    TAX
    LDA a:pBYBIT, X
    AND #$00FF
    STA a:pLOC
    TAX
    LDA a:pREACH, X
    AND #$00FF
    BNE @list
    LDA a:pMODE
    BEQ @test
    LDA a:pSEEN, X
    AND #$00FF
    CMP a:pGEN
    BEQ @list
  @test:
    JSR pl_sat
    BCC @list
    JSR pl_mark
    BRA @list

;;  What the bits in RP_PEND would open: pCI new incentive places, pCN others.
;;  Owned is as it was afterwards, and nothing marked in RP_REACH.
pl_ask:
    INC a:pGEN
    LDA a:pGEN
    CMP #$0100
    BCC @gen
    LDX #$0000                  ; RP_GEN wrapped: start RP_SEEN afresh
  @clear:
    STZ a:pSEEN, X
    INX
    INX
    CPX #256
    BCC @clear
    LDA #1
    STA a:pGEN
  @gen:
    LDA a:pOWNED
    STA a:pSAVE
    LDA a:pOWNED + 2
    STA a:pSAVE + 2
    LDA a:pPEND
    ORA a:pOWNED
    STA a:pOWNED
    LDA a:pPEND + 2
    ORA a:pOWNED + 2
    STA a:pOWNED + 2
    JSR pl_notown
    STZ a:pCI
    STZ a:pCN
    LDA #1
    STA a:pMODE
    JSR pl_propagate
    STZ a:pMODE
    LDA a:pSAVE
    STA a:pOWNED
    LDA a:pSAVE + 2
    STA a:pOWNED + 2
    JMP pl_notown


;;  The placement, into the save: each item's location, or $FF.
pl_store:
    SEP #$20
    .a8
    LDX #PLACE_ITEMS - 1
    LDA #$FF
  @none:
    STA f:RANDO_PLACEFAR, X
    DEX
    BPL @none
    LDX #$0000
  @loc:
    LDA a:pPLACED, X
    CMP #PLACE_ITEMS
    BCS :+                      ; nothing, or the caravan's ordinary treasure
    PHX
    REP #$20
    .a16
    AND #$00FF
    TAY
    TXA
    TYX
    SEP #$20
    .a8
    STA f:RANDO_PLACEFAR, X
    PLX
:   INX
    CPX #LOGIC_POOL
    BCC @loc
    LDA #1
    STA f:RANDO_PLACEDFAR
    REP #$20
    .a16
    RTS


;;  The items' properties, PLACE_ITEMS order: the nineteen key items, the
;;  TAIL, the nine gear rows (randoref.py's PLACE_ITEMS).
lut_PlaceLBit:                  ; each key item's bit in the logic
  .BYTE LBIT_LUTE, LBIT_CROWN, LBIT_CRYSTAL, LBIT_HERB, LBIT_KEY, LBIT_TNT
  .BYTE LBIT_ADAMANT, LBIT_SLAB, LBIT_RUBY, LBIT_ROD, LBIT_FLOATER, LBIT_CHIME
  .BYTE LBIT_CUBE, LBIT_BOTTLE, LBIT_OXYALE, LBIT_CANOE, LBIT_SHIP, LBIT_BRIDGE
  .BYTE LBIT_CANAL
lut_PlaceQ:                     ; FFR's safe weights, in quarters; BRIDGE 2.0
  .BYTE 1, 3, 3, 3, 1, 3, 3, 3, 4, 4, 1, 1, 1, 3, 1, 3, 4, 8, 4
lut_PlaceMinCycle:              ; FFR's safe minimum cycles
  .BYTE 0, 0, 0, 0, 5, 0, 0, 0, 0, 0, 10, 5, 7, 0, 5, 3, 2, 0, 0
  .BYTE 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
lut_PlaceMinAccess:             ; ...and fewest places reached
  .BYTE 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 60, 75, 0, 50, 0, 0, 0, 0
  .BYTE 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
.assert lut_PlaceQ - lut_PlaceLBit = PLACE_KEYS, error, "lut_PlaceLBit: one per key item"
.assert lut_PlaceMinCycle - lut_PlaceQ = PLACE_KEYS, error, "lut_PlaceQ: one per key item"
.assert lut_PlaceMinAccess - lut_PlaceMinCycle = PLACE_ITEMS, error, "lut_PlaceMinCycle: one per item"
;  Which item each key item row governs (ITEMROW_*), and the nine of Other
;  items.
lut_ItemRowItem:
  .BYTE 16, 10, 17, 18, 15, 4, 11, 1, 0, 19, 9
lut_OtherItems:
  .BYTE 2, 3, 5, 6, 7, 8, 12, 13, 14
;  The bit each Early flag waives (genlogic.py's EARLY_BIT).
lut_EarlyLBit:
  .BYTE LBIT_PRINCESS, LBIT_VAMPIRE, LBIT_ORB_EARTH, LBIT_CROWN
lut_Bit16:
  .WORD $0001, $0002, $0004, $0008, $0010, $0020, $0040, $0080
  .WORD $0100, $0200, $0400, $0800, $1000, $2000, $4000, $8000
