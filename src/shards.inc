; ---------------------------------------------------------------------------
;  shards.inc -- Shard Hunt (user, 2026-11-06): FFR's, the Black Orb waiting
;  for SHARDs, the Goal's count of them (goal.inc), and no orbs.
;
;  Included by world.asm: the randomizer's chunk is full.  Three things:
;
;    goal_won     Chaos reached, the Goal counted -- placement's last test
;                 (pl_goalwon, by JSL from place.inc) and the map edit
;                 screen's (rando_winnable), so the two agree
;    the room     how many shards the logic counts on: the chests of common
;                 treasure reached that no placed item holds (randoref's
;                 shard_room); under the screen's check, less every item
;                 placement could put in one
;    shards_deal  the shards themselves, after the Chests row's deal in the
;                 cache build (randoref.shard_post): SHARDS_DEALT of the
;                 places reached, drawn on the seed's own stream -- shuffled,
;                 any but the caravan (under Key items Vanilla, the chests
;                 whose contents move); off, the chests of common treasure --
;                 and what a shard pushes out, if it is not common, moved
;                 into another of them that is, so the shards take the room
;                 of common treasure as FFR's do (RemoveRandomWeightedItem)
;
;  The count is item SHARD_CODE's byte, $6031, the game's CANOE, which no one
;  holds: a chest or an NPC giving SHARD_CODE adds one (OpenTreasureChest,
;  talk_give), and each fiend's orb, as it lights, FFR's 2, 2, 4 or 4
;  (opt_orbshards).
; ---------------------------------------------------------------------------

gwOWN   = .LOWORD(ES_VARS) + $70    ; 4: what is held, for goal_won
gwROOM  = .LOWORD(ES_VARS) + $74    ; the shards' room (goal.inc's GOAL_HELD)
gwK     = .LOWORD(ES_VARS) + $76    ; a location; a count
gwT     = .LOWORD(ES_VARS) + $78    ; a masks' end; a slot's address
gwCHG   = .LOWORD(ES_VARS) + $7A    ; something reached this pass
gwI     = .LOWORD(ES_VARS) + $7C    ; the shard being dealt
gwV     = .LOWORD(ES_VARS) + $7E    ; what it pushed out
.assert gwV + 2 <= .LOWORD(ES_WORDSEND), error, "shards.inc's words run past ES_VARS"
.assert gwOWN >= esS + 2, error, "shards.inc's words overlap entrance shuffle's"
gREACH  = .LOWORD(RP_REACH)
gPLACED = .LOWORD(RP_PLACED)
gNOTOWN = .LOWORD(RP_NOTOWN)
gFREE   = .LOWORD(RP_FREE)
gNCAND  = .LOWORD(RV_NCAND)
gDROP   = .LOWORD(RV_DROP)
gCAND   = .LOWORD(RV_CAND)
.assert RV_CAND + LOGIC_POOL <= RP_BASE + $2000, error, "RV_CAND runs past the rewards' area"
.assert RV_SPOT + SLOTS <= RV_CAND, error, "RV_SPOT runs into RV_CAND"
STREAM_SHARDS = $53485244       ; "SHRD"

;;  C set under Shard Hunt.  A16 or A8, kept; X and Y kept.
shard_on:
    PHP
    SEP #$20
    .a8
    LDA f:RANDO_SAVEFAR + (RANDO_GOAL - RANDO_SAVE)
    CMP #GOAL_SHARD0
    BCS :+
    PLP
    CLC
    RTS
:   PLP
    SEC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  goal_won -- is Chaos reached, holding gwOWN?  One of its masks met (the
;;  Chaos masks in RP_CHAOS, the world's), one holding all four orbs met with
;;  the orbs aside once the Goal is held (goal.inc's GOAL_HELD, the shards'
;;  room gwROOM), one without them as it is.  A16 I16, DBR $7F.  Out: C set
;;  if so.  X and Y clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

goal_won:
    .a16
    .i16
    LDA a:gwOWN + 2
    GOAL_HELD WORLDFAR, gwROOM  ; Y = 1 if the Goal is held
    LDX #$0000
    STZ a:gwK
  @chaos:
    LDA a:gwK
    CMP a:eNCHAOS
    BCS @lost                   ; (none met, or none at all: a wiring
    LDA a:gwOWN                 ;   nothing reaches Chaos in)
    EOR #$FFFF
    AND a:eCHAOS, X
    BNE @next
    LDA a:eCHAOS + 2, X
    AND #LOGIC_ORBS_HI
    CMP #LOGIC_ORBS_HI
    BNE @asis                   ; not through the Black Orb: as it is
    CPY #0
    BEQ @next                   ; through it, short of the Goal
    LDA a:eCHAOS + 2, X
    AND #.LOWORD(~LOGIC_ORBS_HI)
    BRA @rest
  @asis:
    LDA a:eCHAOS + 2, X
  @rest:
    ORA a:gwOWN + 2             ; its high word less what is held
    EOR a:gwOWN + 2
    BEQ @won
  @next:
    INX
    INX
    INX
    INX
    INC a:gwK
    BRA @chaos
  @lost:
    CLC
    RTS
  @won:
    SEC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  pl_goalwon -- placement's last test (place.inc's pl_attempt, every item
;;  placed): Chaos reached with what the placement gives (RP_NOTOWN's
;;  complement), the room the places reached and left empty (RP_REACH,
;;  RP_PLACED).  By JSL, A16 I16, DBR $7F.  Out: C set if the seed is won.
;;  X and Y clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

pl_goalwon:
    .a16
    .i16
    LDA a:gNOTOWN
    EOR #$FFFF
    STA a:gwOWN
    LDA a:gNOTOWN + 2
    EOR #$FFFF
    STA a:gwOWN + 2
    STZ a:gwROOM
    JSR shard_on
    BCC @test
    LDX #$0000
  @room:
    LDA a:gREACH, X
    AND #$00FF
    BEQ @next
    LDA a:gPLACED, X
    AND #$00FF
    CMP #$00FF
    BNE @next                   ; a placed item there
    LDA f:LOGICFAR + lut_LogicFlags, X
    AND #LOGIC_SHARD
    BEQ @next
    INC a:gwROOM
  @next:
    INX
    CPX #LOGIC_POOL
    BCC @room
  @test:
    JSR goal_won
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  shard_vanroom -- rando_winnable's room, holding esHAVE: each pool place
;;  reached marked in RP_REACH (shards_deal's, under Key items Vanilla), and
;;  the chests of common treasure among them counted -- less, under Standard
;;  or Wide, every item placement could put in one (PLACE_ITEMS), as the
;;  screen does not know where it will.  Nothing without Shard Hunt.  Out:
;;  gwROOM.  A16 I16.  X and Y clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

shard_vanroom:
    .a16
    .i16
    STZ a:gwROOM
    JSR shard_on
    BCS :+
    RTS
:   STZ a:gwK
  @loc:
    LDX a:gwK
    SEP #$20
    .a8
    STZ a:gREACH, X
    REP #$20
    .a16
    TXA
    ASL A
    TAX
    LDA a:eMOFF + 2, X
    STA a:gwT
    LDA a:eMOFF, X
  @mask:
    CMP a:gwT
    BCS @next
    TAX
    LDA a:esHAVE
    EOR #$FFFF
    AND a:eMASK, X
    BNE @nomask
    LDA a:esHAVE + 2
    EOR #$FFFF
    AND a:eMASK + 2, X
    BEQ @reached
  @nomask:
    TXA
    CLC
    ADC #4
    BRA @mask
  @reached:
    LDX a:gwK
    SEP #$20
    .a8
    LDA #1
    STA a:gREACH, X
    REP #$20
    .a16
    LDA f:LOGICFAR + lut_LogicFlags, X
    AND #LOGIC_SHARD
    BEQ @next
    INC a:gwROOM
  @next:
    INC a:gwK
    LDA a:gwK
    CMP #LOGIC_POOL
    BCC @loc
    LDA a:esPLCD
    BEQ @out
    LDA a:gwROOM
    SEC
    SBC #PLACE_ITEMS
    BCS :+
    LDA #0
:   STA a:gwROOM
  @out:
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  shards_deal -- the SHARDs, after the Chests row's deal (build, by JSL):
;;  randoref.shard_post.  The places reached first: under Standard or Wide
;;  the placement swept from what is free on the world's masks (RP_MASK, as
;;  placement left them; shard_sweep); under Vanilla rando_winnable's sweep,
;;  the princess at her spot (shard_vanroom).  Nothing without Shard Hunt.
;;  Native mode, either width, DBR $7F; out as it came in.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

shards_deal:
    PHP
    JSR shard_on
    BCS :+
    PLP
    RTL
:   SEP #$20
    .a8
    REP #$10
    .i16
    LDA f:RW_PLACED
    CMP #1
    BNE @vanilla
    JSR shard_sweep
    BRA @reached
  @vanilla:
    LDA f:RW_SARA               ; the princess where the build put her
    STA f:RW_SARALOG
    SEC
    XCE
    JSL rando_winnable + WORLDFAR
    CLC
    XCE
    SEP #$20
    .a8
    REP #$10
    .i16
    LDA #0
    STA f:RW_SARALOG
  @reached:
    REP #$30
    .a16
    .i16

    ;  The places that can take one, in order.
    STZ a:gNCAND
    LDX #$0000
  @cand:
    LDA a:gREACH, X
    AND #$00FF
    BEQ @cnext
    LDA f:LOGICFAR + lut_LogicKind, X
    AND #$00FF
    CMP #2
    BEQ @cnext                  ; the caravan: a shop
    STA a:gwK                   ; the kind
    SEP #$20
    .a8
    LDA f:RW_PLACED
    CMP #1
    BNE :+
    LDA a:gPLACED, X
    CMP #$FF
    BNE @cnext8                 ; a placed item there
:   LDA f:RANDO_SAVEFAR + (RANDO_CHESTS - RANDO_SAVE)
    BEQ @off
    CMP #CHESTS_MODES
    BCS @off
    LDA f:RW_PLACED             ; shuffled: placed, any place; Vanilla, a
    CMP #1                      ;   chest whose contents move
    BEQ @take
    LDA a:gwK
    BNE @cnext8
    PHX
    LDA f:LOGICFAR + lut_LogicIdent, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:BANK00FAR + $B100, X  ; ROMCHESTS: its vanilla contents
    PLX
    CMP #item_qty_start - items
    BCC @cnext8
    BRA @take
  @off:
    LDA f:LOGICFAR + lut_LogicFlags, X
    AND #LOGIC_SHARD
    BEQ @cnext8
  @take:
    TXA
    LDY a:gNCAND
    STA a:gCAND, Y
    INY
    STY a:gNCAND
  @cnext8:
    REP #$20
    .a16
  @cnext:
    INX
    CPX #LOGIC_POOL
    BCC @cand

    ;  The first k of them, Fisher-Yates from the bottom on the seed's
    ;  stream: the spots.
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_SHARDS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_SHARDS)
    STA a:wRNG+2
    JSL rando_warmfar + RANDOFAR
    LDA a:gNCAND
    CMP #SHARDS_DEALT
    BCC :+
    LDA #SHARDS_DEALT
:   STA a:gwK                   ; k
    STZ a:gwI
  @fy:
    LDA a:gwI
    CMP a:gwK
    BCS @counted
    LDA a:gNCAND
    SEC
    SBC a:gwI
    SEP #$20
    .a8
    JSL rando_belowfar + RANDOFAR
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:gwI
    TAY                         ; j
    LDX a:gwI
    SEP #$20
    .a8
    LDA a:gCAND, X
    PHA
    LDA a:gCAND, Y
    STA a:gCAND, X
    PLA
    STA a:gCAND, Y
    REP #$20
    .a16
    INC a:gwI
    BRA @fy

    ;  The commons among the rest, to take what the shards push out.
  @counted:
    STZ a:gDROP
    LDY a:gwK
  @common:
    CPY a:gNCAND
    BCS @deal
    JSR shard_get
    JSR shard_common
    BCC :+
    INC a:gDROP
:   INY
    BRA @common

    ;  Each spot: a SHARD, and what it held, if it is not common, into one
    ;  of the rest that holds common treasure, drawn until one does.
  @deal:
    STZ a:gwI
  @spot:
    LDY a:gwI
    CPY a:gwK
    BCS @done
    JSR shard_get
    STA a:gwV
    SEP #$20
    .a8
    LDA #SHARD_CODE
    STA a:0, X
    REP #$20
    .a16
    LDA a:gwV
    JSR shard_common
    BCS @nextspot               ; common: it goes
    LDA a:gDROP
    BEQ @nextspot               ; none left: it goes (never)
  @draw:
    LDA a:gNCAND
    SEC
    SBC a:gwK
    SEP #$20
    .a8
    JSL rando_belowfar + RANDOFAR
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:gwK
    TAY
    JSR shard_get
    JSR shard_common
    BCC @draw
    SEP #$20
    .a8
    LDA a:gwV
    STA a:0, X
    REP #$20
    .a16
    DEC a:gDROP
  @nextspot:
    INC a:gwI
    BRA @spot
  @done:
    PLP
    RTL

;;  Candidate Y's contents: A16 = the byte, X = its address (bank $7F) -- a
;;  chest's in RW_CHESTS, an NPC's in RW_TALKREW.  Y kept.
shard_get:
    .a16
    LDA a:gCAND, Y
    AND #$00FF
    TAX
    LDA f:LOGICFAR + lut_LogicKind, X
    AND #$00FF
    PHA
    LDA f:LOGICFAR + lut_LogicIdent, X
    AND #$00FF
    TAX
    PLA
    BEQ @chest
    TXA
    CLC
    ADC #.LOWORD(RW_TALKREW)
    BRA @at
  @chest:
    TXA
    CLC
    ADC #.LOWORD(RW_CHESTS)
  @at:
    TAX
    LDA a:0, X
    AND #$00FF
    RTS

;;  Is A16, a chest code, FFR's common treasure (lut_ShardCommon)?  C set
;;  if so.  A, X and Y kept.
shard_common:
    .a16
    PHX
    PHY
    PHA
    AND #$00FF
    PHA
    LSR A
    LSR A
    LSR A
    TAY                         ; its byte
    PLA
    AND #$0007
    TAX                         ; its bit
    SEP #$20
    .a8
    LDA f:WORLDFAR + esBit8, X
    TYX
    AND f:LOGICFAR + lut_ShardCommon, X
    CMP #1                      ; C set if nonzero
    REP #$20
    .a16
    PLA
    PLY
    PLX
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  shard_sweep -- the places reached on the world placement built: RP_PLACED
;;  from RW_PLACE, and from what is free (RP_FREE) every place whose masks
;;  (RP_MASK, RP_MOFF, as placement left them) are met marked in RP_REACH,
;;  gaining an event's bit or a key item placed there, until a pass gains
;;  nothing: randoref.place_accessible.  A8 I16 in; A16 I16 out.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

shard_sweep:
    .a8
    .i16
    LDX #$0000
  @clear:
    LDA #$FF
    STA a:gPLACED, X
    STZ a:gREACH, X
    INX
    CPX #256
    BCC @clear
    LDX #$0000
  @place:
    LDA f:RW_PLACE, X
    CMP #$FF
    BEQ @pnext
    REP #$20
    .a16
    AND #$00FF
    TAY
    SEP #$20
    .a8
    TXA
    STA a:gPLACED, Y
  @pnext:
    INX
    CPX #PLACE_ITEMS
    BCC @place
    REP #$20
    .a16
    LDA a:gFREE
    STA a:gwOWN
    LDA a:gFREE + 2
    STA a:gwOWN + 2
  @pass:
    JSL rando_yieldfar + RANDOFAR   ; the roll screen's tune, if due
    STZ a:gwCHG
    STZ a:gwK
  @loc:
    LDX a:gwK
    LDA a:gREACH, X
    AND #$00FF
    BNE @next
    TXA
    ASL A
    TAX
    LDA a:eMOFF + 2, X
    STA a:gwT
    LDA a:eMOFF, X
  @mask:
    CMP a:gwT
    BCS @next
    TAX
    LDA a:gwOWN
    EOR #$FFFF
    AND a:eMASK, X
    BNE @nomask
    LDA a:gwOWN + 2
    EOR #$FFFF
    AND a:eMASK + 2, X
    BEQ @reached
  @nomask:
    TXA
    CLC
    ADC #4
    BRA @mask
  @reached:
    LDX a:gwK
    SEP #$20
    .a8
    LDA #1
    STA a:gREACH, X
    REP #$20
    .a16
    INC a:gwCHG
    LDA f:LOGICFAR + lut_LogicKind, X
    AND #$00FF
    CMP #LOGIC_EVENT
    BNE @item
    LDA f:LOGICFAR + lut_LogicIdent, X
    AND #$00FF
    BRA @gain
  @item:
    LDA a:gPLACED, X
    AND #$00FF
    CMP #PLACE_KEYS
    BCS @next
    TAX
    LDA f:RANDOFAR + lut_PlaceLBit, X
    AND #$00FF
  @gain:
    LDY #gwOWN
    JSR es_setbit
  @next:
    INC a:gwK
    LDA a:gwK
    CMP #LOGIC_LOCS
    BCS :+
    JMP @loc
:   LDA a:gwCHG
    BEQ :+
    JMP @pass
:   RTS
