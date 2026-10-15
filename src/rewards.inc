; ---------------------------------------------------------------------------
;  rewards.inc -- what chests, reward NPCs and the caravan give once placement
;  is in
;
;  Included by rando.asm.  deal_rewards runs in the cache build when the save
;  holds a placement (RANDO_PLACED), and is tools/randoref.py's
;  build_rewards, which test_rando_rewards holds it to: see there for the
;  rules.  The game reads the result through rando_chest (the chests),
;  rando_talk (the NPCs) and the caravan's shop row.
; ---------------------------------------------------------------------------

rvVAN    = .LOWORD(RV_VAN)
rvOUT    = .LOWORD(RV_OUT)
rvPM     = .LOWORD(RV_PM)
rvHM     = .LOWORD(RV_HM)
rvPOOL   = .LOWORD(RV_POOL)
rvDEST   = .LOWORD(RV_DEST)
rvGOLD   = .LOWORD(RV_GOLD)
rvNPOOL  = .LOWORD(RV_NPOOL)
rvNDEST  = .LOWORD(RV_NDEST)
rvNGOLD  = .LOWORD(RV_NGOLD)
rvS      = .LOWORD(RV_S)
rvK      = .LOWORD(RV_K)
rvCODE   = .LOWORD(RV_CODE)
wTALKREW = .LOWORD(RW_TALKREW)
wCARAVAN = .LOWORD(RW_CARAVAN)

STREAM_GOLD = $474F4C44         ; "GOLD"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_rewards -- the chests, the NPCs and the caravan, from the placement
;;
;;  After copy_chests, in place of deal_chests.  A placed item takes its place;
;;  every item placement moved, and every Free item, leaves its vanilla home,
;;  and a Free item's home becomes one of FFR's spare amounts of gold.  The rest
;;  goes where the Chests row sends it: shuffled, every slot not placed is dealt
;;  from them all; off, the contents a placed item pushed out, and the gold,
;;  are dealt into the homes left empty.  The caravan, a shop, is stocked first
;;  if placement left it to treasure.
;;
;;  A8, I16, DBR = $7F.  Out: wCHESTS, wTALKREW, wCARAVAN and the caravan's
;;  shop row.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_rewards:
    .a8
    .i16
    JSR mark_unused
    ;  Each slot's vanilla contents: the chests as copy_chests left them, the
    ;  NPCs' rewards, the caravan's BOTTLE.  To start, each gives that.
    LDX #$0000
  @van:
    LDA a:wCHESTS, X
    STA a:rvVAN, X
    INX
    CPX #256
    BCC @van
    LDX #$0000
  @npc:
    LDA f:RANDOFAR + lut_TalkReward, X
    STA a:rvVAN + SLOT_NPC, X
    INX
    CPX #TALK_COUNT
    BCC @npc
    LDA #item_bottle - items
    STA a:rvVAN + SLOT_CARAVAN
    LDX #$0000
  @init:
    LDA a:rvVAN, X
    STA a:rvOUT, X
    STZ a:rvPM, X
    STZ a:rvHM, X
    INX
    CPX #SLOTS
    BCC @init

    ;  What placement put where, and the homes those items left.
    LDX #$0000
  @placed:
    JSR rando_yield             ; the roll screen's tick, if due
    LDA f:RANDO_PLACEFAR, X
    CMP #LOGIC_POOL
    BCS @pnext
    PHX
    JSR rv_slot                 ; rvS = its slot
    PLX
    LDA f:RANDOFAR + lut_PlaceCode, X
    STA a:rvCODE
    PHX
    LDX a:rvS
    STA a:rvOUT, X
    LDA #1
    STA a:rvPM, X
    LDA a:rvCODE
    JSR rv_home                 ; X = where it was
    LDA #1
    STA a:rvHM, X
    PLX
  @pnext:
    INX
    CPX #PLACE_ITEMS
    BCC @placed

    ;  The Free items' homes, which become gold.
    REP #$20
    .a16
    STZ a:rvNGOLD
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_GOLD)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_GOLD)
    STA a:wRNG + 2
    JSR rando_warm
    SEP #$20
    .a8
    LDX #$0000
  @free:
    PHX
    JSR rv_rowval               ; A = row X's value
    PLX
    CMP #ITEM_FREE
    BNE @fnext
    PHX
    LDA f:RANDOFAR + lut_ItemRowItem, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:RANDOFAR + lut_PlaceCode, X
    JSR rv_home
    LDA #1
    STA a:rvHM, X
    LDA #SPARE_GOLDS
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:RANDOFAR + lut_SpareGold, X
    LDX a:rvNGOLD
    STA a:rvGOLD, X
    INC a:rvNGOLD
    PLX
  @fnext:
    INX
    CPX #ITEMROW_OTHER
    BCC @free

    ;  The contents to deal, and where they go.
    REP #$20
    .a16
    STZ a:rvNPOOL
    STZ a:rvNDEST
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_CHESTS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_CHESTS)
    STA a:wRNG + 2
    JSR rando_warm
    SEP #$20
    .a8
    LDX #$0000
  @gather:
    JSR rando_yield             ; the roll screen's tick, if due
    JSR rv_valid
    BCC @gnext
    LDA f:RANDO_SAVEFAR + (RANDO_CHESTS - RANDO_SAVE)
    BEQ @off
    CMP #CHESTS_MODES
    BCS @off
    LDA a:rvHM, X               ; shuffled: every content but the homes'...
    BNE :+
    LDA a:rvVAN, X
    JSR rv_pool
:   LDA a:rvPM, X               ; ...into every slot not placed
    BNE @gnext
    JSR rv_dest
    BRA @gnext
  @off:
    LDA a:rvPM, X               ; off: what a placed item pushed out...
    BEQ :+
    LDA a:rvHM, X
    BNE @gnext
    LDA a:rvVAN, X
    JSR rv_pool
    BRA @gnext
:   LDA a:rvHM, X               ; ...into the homes left empty
    BEQ @gnext
    JSR rv_dest
  @gnext:
    INX
    CPX #SLOTS
    BCC @gather
    LDX #$0000                  ; and the gold
  @golds:
    CPX a:rvNGOLD
    BCS @caravan
    LDA a:rvGOLD, X
    PHX
    JSR rv_pool
    PLX
    INX
    BRA @golds

    ;  The caravan, if it is to be dealt into: first, and only what a shop
    ;  can sell.
  @caravan:
    LDX a:rvNDEST
    BEQ @fy
    DEX
    REP #$20
    .a16
    TXA                         ; rvDEST is words
    ASL A
    TAX
    LDA a:rvDEST, X
    CMP #SLOT_CARAVAN
    SEP #$20
    .a8
    BNE @fy
    DEC a:rvNDEST
    STZ a:rvK                   ; how many sellable
    LDX #$0000
  @count:
    CPX a:rvNPOOL
    BCS @counted
    LDA a:rvPOOL, X
    JSR rv_sellable
    BCC :+
    INC a:rvK
:   INX
    BRA @count
  @counted:
    LDA a:rvK
    BNE @sell
    LDA #item_cabin - items     ; none: a CABIN, and the last left over
    STA a:rvOUT + SLOT_CARAVAN
    DEC a:rvNPOOL
    BRA @fy
  @sell:
    JSR rando_below
    STA a:rvK                   ; the rvK'th sellable
    LDX #$0000
  @find:
    LDA a:rvPOOL, X
    JSR rv_sellable
    BCC @fnot
    LDA a:rvK
    BEQ @take
    DEC a:rvK
  @fnot:
    INX
    BRA @find
  @take:
    LDA a:rvPOOL, X
    STA a:rvOUT + SLOT_CARAVAN
  @shiftdown:                   ; out of the pool, the rest moved down
    INX
    CPX a:rvNPOOL
    BCS @shifted
    LDA a:rvPOOL, X
    STA a:rvPOOL - 1, X
    BRA @shiftdown
  @shifted:
    DEC a:rvNPOOL

    ;  Fisher-Yates over the pool, from the top...
  @fy:
    REP #$20
    .a16
    LDA a:rvNPOOL
    AND #$00FF
    TAX
    SEP #$20
    .a8
    BEQ @put
    DEX                         ; i, from the top
  @swap:
    BEQ @put
    TXA
    INC A
    JSR rando_below             ; j <= i
    REP #$20
    .a16
    AND #$00FF
    TAY
    SEP #$20
    .a8
    LDA a:rvPOOL, X
    PHA
    LDA a:rvPOOL, Y
    STA a:rvPOOL, X
    PLA
    STA a:rvPOOL, Y
    DEX
    BRA @swap

    ;  ...and into the slots, in their order.
  @put:
    LDY #$0000
  @putone:
    CPY a:rvNPOOL
    BCS @back
    REP #$20
    .a16
    TYA
    ASL A
    TAX
    LDA a:rvDEST, X
    TAX
    SEP #$20
    .a8
    LDA a:rvPOOL, Y
    STA a:rvOUT, X
    INY
    BRA @putone

    ;  Back to where the game reads them.
  @back:
    LDX #$0000
  @chest:
    LDA a:rvOUT, X
    STA a:wCHESTS, X
    INX
    CPX #256
    BCC @chest
    LDX #$0000
  @talk:
    LDA a:rvOUT + SLOT_NPC, X
    STA a:wTALKREW, X
    INX
    CPX #TALK_COUNT
    BCC @talk
    LDA a:rvOUT + SLOT_CARAVAN
    STA a:wCARAVAN
    LDX #SHOP_CARAVAN * 8       ; the caravan's shop row: that, and nothing more
    STA a:wSHOPS, X
    LDA #$00
    STA a:wSHOPS + 1, X
    STA a:wSHOPS + 2, X
    STA a:wSHOPS + 3, X
    STA a:wSHOPS + 4, X
    RTS

;;  Pool location A (0..LOGIC_POOL-1) as a slot, in rvS.  A8, I16.
rv_slot:
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA f:LOGICFAR + lut_LogicIdent, X
    AND #$00FF
    STA a:rvS
    LDA f:LOGICFAR + lut_LogicKind, X
    AND #$00FF
    BEQ @done                   ; a chest: its id
    CMP #1
    BNE @caravan
    LDA a:rvS                   ; a reward NPC
    CLC
    ADC #SLOT_NPC
    STA a:rvS
    BRA @done
  @caravan:
    LDA #SLOT_CARAVAN
    STA a:rvS
  @done:
    SEP #$20
    .a8
    RTS

;;  The first valid slot whose vanilla contents are A: X.  A8, I16.
rv_home:
    STA a:rvCODE
    LDX #$0000
  @slot:
    JSR rv_valid
    BCC @next
    LDA a:rvVAN, X
    CMP a:rvCODE
    BEQ @found
  @next:
    INX
    BRA @slot
  @found:
    RTS

;;  Is slot X one a map places?  C set if so: every NPC and the caravan, and
;;  the chests that are not unused (wUNUSED, from mark_unused).
rv_valid:
    CPX #256
    BCS @yes
    LDA a:wUNUSED, X
    BNE @no
  @yes:
    SEC
    RTS
  @no:
    CLC
    RTS

;;  A onto the pool.  X kept.
rv_pool:
    PHX
    LDX a:rvNPOOL
    STA a:rvPOOL, X
    INC a:rvNPOOL
    PLX
    RTS

;;  Slot X onto the destinations.  X kept.
rv_dest:
    PHX
    REP #$20
    .a16
    LDA a:rvNDEST
    ASL A
    TAX
    LDA 1, S
    STA a:rvDEST, X
    SEP #$20
    .a8
    INC a:rvNDEST
    PLX
    RTS

;;  Can a shop sell content A?  C set if so: an item, not gear, gold or a
;;  vehicle.
rv_sellable:
    CMP #$01
    BCC @no
    CMP #TCITYPE_WEPSTART
    BCS @no
    SEC
    RTS
  @no:
    CLC
    RTS

;;  Item row X's value, two bits of RANDO_ITEMS.  A8, I16; X kept.
rv_rowval:
    PHX
    REP #$20
    .a16
    TXA
    LSR A
    LSR A
    TAX
    SEP #$20
    .a8
    LDA f:RANDO_SAVEFAR + (RANDO_ITEMS - RANDO_SAVE), X
    STA a:rvK
    REP #$20
    .a16
    LDA 1, S
    AND #$0003
    TAX
    SEP #$20
    .a8
    LDA a:rvK
  @shift:
    DEX
    BMI @field
    LSR A
    LSR A
    BRA @shift
  @field:
    AND #$03
    PLX
    RTS

;;  wUNUSED: a flag per chest id that no map places.
mark_unused:
    .a8
    .i16
    LDX #$0000
  @clear:
    STZ a:wUNUSED, X
    INX
    CPX #256
    BCC @clear
    LDY #$0000
  @mark:
    TYX
    LDA f:RANDOFAR + lut_UnusedChests, X
    STA a:wT2
    LDX a:wT2
    LDA #$01
    STA a:wUNUSED, X
    INY
    CPY #UNUSED_CHESTS
    BCC @mark
    RTS

;;  What each PLACE_ITEMS item is, given: its chest code, or a vehicle's.
lut_PlaceCode:
  .BYTE item_lute - items, item_crown - items, item_crystal - items, item_herb - items
  .BYTE item_mystickey - items, item_tnt - items, item_adamant - items, item_slab - items
  .BYTE item_ruby - items, item_rod - items, item_floater - items, item_chime - items
  .BYTE item_cube - items, item_bottle - items, item_oxyale - items
  .BYTE REWARD_CANOE, REWARD_SHIP, REWARD_BRIDGE, REWARD_CANAL, item_tail - items
  .BYTE $43, $41, $3D, $3B, $51, $69, $52, $63, REWARD_XCALBER
  ;     Masmune, Katana, Vorpal, Defense, Opal Bracelet, Power Gauntlet,
  ;     White Shirt, Ribbon, Xcalber
.assert * - lut_PlaceCode = PLACE_ITEMS, error, "lut_PlaceCode: one per item"

;;  FFR's ItemLists.UnusedGoldItems: gold amounts no vanilla chest holds, but
;;  for one, 530.  A Free item's home gets one of these.
lut_SpareGold:
  .BYTE $6E, $6F, $70, $71, $72, $74, $78, $79, $7A, $7C, $7D, $7F, $84, $9E
  .BYTE $A5, $A6, $A7, $A8, $AA, $AB, $AC
SPARE_GOLDS = * - lut_SpareGold
