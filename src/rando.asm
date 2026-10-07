; ---------------------------------------------------------------------------
;  rando.asm -- the randomizer: seed, PRNG, generator and the hooks that read
;  what it generates.
;
;  Chunk CHUNK_RANDO.  The design is in randomization-notes.md; in brief:
;
;    - A world is a seed and the new-game settings, both stored in the save at
;      RANDO_SAVE.  rando_newgame writes them when a game starts.  Nothing else
;      writes them, and nothing reads the settings screen's copy afterwards.
;
;    - Everything generated from them is a cache in WRAM bank $7F, rebuilt
;      whenever its tag disagrees with the save.  Every consumer calls ensure
;      first, so there is no "load" step to forget: New Game, Continue, a
;      Continue of a different file, and power-on all come out right because
;      the tag cannot match a world it was not built from.  L+X and L+Y leave
;      WRAM alone, so the instant resets stay instant.
;
;    - The PRNG is xorshift32 (13, 17, 5), and each feature draws from its
;      own stream, the seed XORed with a constant of its own.  Turning one
;      feature on therefore cannot reshuffle another.  tools/randoref.py is the
;      same generator in Python, and tools/test_options.py holds the two to
;      byte-identical output.  Seeds are this port's own: FFR uses MT19937 and
;      a different order of draws, so its seeds and flag strings do not carry.
;
;  The data bank inside this chunk is $7F, the cache's bank, so the cache is
;  plain absolute.  Everything else -- the save and option block in SRAM, the
;  ROM's tables, low WRAM -- is reached with long addresses.  Every entry
;  point sets DBR and puts the caller's back.
;
;  No interrupt is ever enabled in this port (see header.asm), so native mode
;  is safe anywhere; the entry points come in from emulation mode and go back
;  to it.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.export rando_newgame, rando_stir, rando_tileprop, rando_shopinv, rando_caravan
.export rando_chest
;  For tools/test_options.py.
.export rando_ensure, rando_xs

.segment "BANK_RANDO"

;  The cache's addresses as DBR = $7F sees them.
wTAG     = .LOWORD(RW_TAG)
wTAGBLK  = .LOWORD(RW_TAGBLK)
wRNG     = .LOWORD(RW_RNG)
wT       = .LOWORD(RW_T)
wLEN     = .LOWORD(RW_LEN)
wMASK    = .LOWORD(RW_MASK)
wBOUND   = .LOWORD(RW_BOUND)
wR       = .LOWORD(RW_R)
wMODE    = .LOWORD(RW_MODE)
wLIST    = .LOWORD(RW_LIST)
wPROPS   = .LOWORD(RW_PROPS)
wWORDS   = .LOWORD(RW_WORDS)
wWORDSEND = .LOWORD(RW_WORDSEND)
wI       = .LOWORD(RW_I)
wE       = .LOWORD(RW_E)
wP       = .LOWORD(RW_P)
wQ       = .LOWORD(RW_Q)
wFIRST   = .LOWORD(RW_FIRST)
wNSHOPS  = .LOWORD(RW_NSHOPS)
wNENT    = .LOWORD(RW_NENT)
wNELIG   = .LOWORD(RW_NELIG)
wT2      = .LOWORD(RW_T2)
wITEM    = .LOWORD(RW_ITEM)
wK       = .LOWORD(RW_K)
wSHOPID  = .LOWORD(RW_SHOPID)
wCNT     = .LOWORD(RW_CNT)
wELIG    = .LOWORD(RW_ELIG)
wORIG    = .LOWORD(RW_ORIG)
wSHOPS   = .LOWORD(RW_SHOPS)
wLOCS    = .LOWORD(RW_LOCS)
wUNUSED  = .LOWORD(RW_UNUSED)
wCHESTS  = .LOWORD(RW_CHESTS)

;  The cartridge's own tile property tables: eight tilesets, 128 tiles each,
;  two bytes a tile -- the function, then a parameter (for a battle tile, its
;  formation).  Read where LoadSMTilesetData reads them, with long addresses
;  so no bank has to be switched in.
ROMPROPS   = BANK00FAR + lut_SMTilesetProp
PROPS_SIZE = 8 * 256

;  The shop lists: lut_ShopData in bank $0E, a pointer per shop_id into
;  zero-terminated lists in the same bank.  Shop 0's pointer is the empty list
;  that every unused shop_id shares.
.import lut_ShopData
ROMSHOPS   = BANK0EFAR + lut_ShopData

;  lut_Treasure: a chest id's contents, in bank $00.
ROMCHESTS  = BANK00FAR + $B100

;  Each feature's stream: the seed XORed with this, then warmed up.
STREAM_TRAPS  = $54524150       ; "TRAP"
STREAM_SHOPS  = $53484F50       ; "SHOP"
STREAM_CHESTS = $43485354       ; "CHST"

;  Steps discarded from a fresh stream.  xorshift diffuses a one-bit change
;  in the state slowly, and a seed typed in by hand -- 1, 2, 3 -- would
;  otherwise start its streams nearly alike.
WARMUP = 8


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_xs -- one xorshift32 step, for the harness
;;
;;  In:  RW_RNG.  Out: RW_RNG stepped.  Emulation mode in and out.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_xs:
    PHB
    JSR enter
    REP #$20
    .a16
    JSR xs_step
    SEP #$20
    .a8
    JMP leave


;;  Native mode, DBR = $7F.  Callers do PHB first; leave undoes both.
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


;;  x ^= x << 13;  x ^= x >> 17;  x ^= x << 5
;;
;;  In halves: L is bits 0-15, H bits 16-31.  A shift by 13 or 5 moves bits
;;  from L into H, and the shift by 17 is H alone moved into L.
;;
;;  In: A16, DBR = $7F.  Out: RW_RNG stepped, A = its new low half.  X and Y
;;  are not touched.
xs_step:
    .a16
    ;  x ^= x << 13: H gains (H << 13) | (L >> 3), L gains L << 13.
    LDA a:wRNG
    LSR A
    LSR A
    LSR A
    STA a:wT                    ; L >> 3
    LDA a:wRNG+2
    XBA
    AND #$FF00
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; H << 13
    ORA a:wT
    EOR a:wRNG+2
    STA a:wRNG+2
    LDA a:wRNG
    XBA
    AND #$FF00
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; L << 13
    EOR a:wRNG
    STA a:wRNG

    ;  x ^= x >> 17: L gains H >> 1.
    LDA a:wRNG+2
    LSR A
    EOR a:wRNG
    STA a:wRNG

    ;  x ^= x << 5: H gains (H << 5) | (L >> 11), L gains L << 5.
    XBA
    AND #$00FF
    LSR A
    LSR A
    LSR A
    STA a:wT                    ; L >> 11
    LDA a:wRNG+2
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; H << 5
    ORA a:wT
    EOR a:wRNG+2
    STA a:wRNG+2
    LDA a:wRNG
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; L << 5
    EOR a:wRNG
    STA a:wRNG
    RTS


;;  Start a stream: RW_RNG = seed ^ (the feature's constant), then WARMUP
;;  steps.  xorshift has one state it never leaves, zero, so a seed that
;;  cancels the constant exactly is nudged off it.
;;
;;  In: A16, DBR = $7F, wRNG already the XOR.  Out: A16.
rando_warm:
    .a16
    LDA a:wRNG
    ORA a:wRNG+2
    BNE :+
    INC a:wRNG
:
  .repeat WARMUP
    JSR xs_step
  .endrep
    RTS


;;  A number below A, uniformly: draw, mask to the smallest power of two that
;;  covers A-1, and draw again if it is not below A.  Never a modulo -- the
;;  Python reference has to land on the same number by the same route, and
;;  rejection is the version of that with nothing left to interpret.
;;
;;  In: A8 = the bound, 1..255; DBR = $7F.  Out: A8 = the number.
rando_below:
    .a8
    STA a:wBOUND
    DEC A
    STA a:wMASK
    LSR A
    ORA a:wMASK
    STA a:wMASK
    LSR A
    LSR A
    ORA a:wMASK
    STA a:wMASK
    LSR A
    LSR A
    LSR A
    LSR A
    ORA a:wMASK
    STA a:wMASK
  @draw:
    REP #$20
    .a16
    JSR xs_step
    SEP #$20
    .a8
    AND a:wMASK                 ; from the low byte of the new state
    CMP a:wBOUND
    BCS @draw
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_stir -- fold this frame's pad into the entropy pool
;;
;;  Called once a frame from opt_padreset, which every frame loop reaches
;;  through WaitForVBlank.  The pool is battery-backed, so the seed a new game
;;  takes from it depends on every button pressed since the cartridge was first
;;  switched on, not only on how long the title screen was up.
;;
;;  The pad is read from the auto-joypad registers, which the HAL has already
;;  waited out by the time WaitForVBlank returns.
;;
;;  Out: everything as it was -- A whole, X, Y, P, DBR.  WaitForVBlank's
;;  callers own them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_stir:
    PHP
    PHB
    CLC
    XCE
    REP #$20
    .a16
    PHA                         ; all sixteen bits
    SEP #$20
    .a8
    LDA #^RANDOWRAM
    PHA
    PLB
    REP #$20
    .a16
    LDA f:RANDO_POOLFAR
    EOR f:JOY1L                 ; both pad bytes, JOY1L and JOY1H
    STA a:wRNG
    LDA f:RANDO_POOLFAR+2
    STA a:wRNG+2
    JSR xs_step
    LDA a:wRNG
    STA f:RANDO_POOLFAR
    LDA a:wRNG+2
    STA f:RANDO_POOLFAR+2
    PLA
    SEP #$20
    .a8
    SEC
    XCE
    PLB
    PLP
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_newgame -- give the game being started its world
;;
;;  Called from opt_freestuff, at the top of NewGamePartyGeneration, after
;;  page 0 of unsram has been filled from lut_InitUnsramFirstPage.  Takes the
;;  seed from the pool (or from FFSEED, in a debug build) and copies the
;;  settings screen's new-game rows in beside it.  The cache is left to the
;;  first consumer: its tag no longer matches the save, so it will rebuild.
;;
;;  Out: X and P as they were.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_newgame:
    PHP
    PHX
.ifdef FORCE_SEED
    ;  FFSEED=xxxxxxxx ./build.sh: every new game gets this seed, so a world
    ;  can be reproduced on a console without a battery file.
    LDA #<(FORCE_SEED)
    STA f:RANDO_SAVEFAR+0
    LDA #>(FORCE_SEED)
    STA f:RANDO_SAVEFAR+1
    LDA #^(FORCE_SEED)
    STA f:RANDO_SAVEFAR+2
    LDA #<((FORCE_SEED) >> 24)
    STA f:RANDO_SAVEFAR+3
.else
    LDX #$03
  @seed:
    LDA f:RANDO_POOLFAR, X
    STA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE), X
    DEX
    BPL @seed
.endif
    LDX #OPT_NG_SIZE - 1
  @ng:
    LDA f:OPT_NGFAR, X
    STA f:RANDO_SAVEFAR + RANDO_NGOFF, X
    DEX
    BPL @ng
    PLX
    PLP
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_ensure -- make the cache match the save
;;
;;  The tag is RW_TAG_VAL followed by a copy of the save block the cache was
;;  built from.  If both match, nothing happens: a few dozen cycles, which is
;;  what every map load pays.  Otherwise the tag is cleared *first* and written
;;  *last*, so a reset pressed mid-build leaves a cache that reads as invalid
;;  rather than as finished.
;;
;;  rando_ensure is the JSL entry for the harness; consumers JSR ensure.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_ensure:
    PHB
    JSR enter
    JSR ensure
    JMP leave

;;  Native mode, DBR = $7F.  Out: A8, I8.
ensure:
    SEP #$30
    .a8
    .i8
    LDA a:wTAG
    CMP #RW_TAG_VAL
    BNE @build
    LDX #RANDO_SAVE_SIZE - 1
  @cmp:
    LDA f:RANDO_SAVEFAR, X
    CMP a:wTAGBLK, X
    BNE @build
    DEX
    BPL @cmp
    RTS

  @build:
    STZ a:wTAG                  ; not valid until the very last store
    JSR build
    LDX #RANDO_SAVE_SIZE - 1
  @copy:
    LDA f:RANDO_SAVEFAR, X
    STA a:wTAGBLK, X
    DEX
    BPL @copy
    LDA #RW_TAG_VAL
    STA a:wTAG                  ; ...which is this one
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  build -- generate everything from the save block
;;
;;  Native mode, DBR = $7F, either register width.  Out: as it came in.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

build:
    PHP
    REP #$30
    .a16
    .i16

    ;  The deals' counters are words read whole into X and Y and only ever
    ;  stored a byte at a time, so their high bytes are zeroed here, once.
    LDX #wWORDS
  @words:
    STZ a:0, X
    INX
    INX
    CPX #wWORDSEND
    BCC @words

    ;  All eight property tables, with every random-encounter tile's formation
    ;  byte rewritten from $80 to $00.  SMMove_Battle tests that byte with BNE
    ;  where the game used BPL, which is FFR's UpdateTrapTilesCode: zero means
    ;  a random encounter, and anything else is a full formation number, so a
    ;  trap can hold a B-side.  FFR applies both halves whatever its trap mode,
    ;  and so does this -- the rewrite runs with the randomizer off too.  The
    ;  one behaviour BNE could change is a trap on formation 0, which would
    ;  turn into a random tile; five tile types are that, and no map places
    ;  any of them.
    LDX #$0000
  @copy:
    LDA f:ROMPROPS, X           ; function low, formation high
    AND #$80FF
    CMP #$8000 | TP_SPEC_BATTLE
    BEQ @random
    LDA f:ROMPROPS, X
    BRA @store
  @random:
    LDA f:ROMPROPS, X
    AND #$00FF                  ; the formation byte becomes zero
  @store:
    STA a:wPROPS, X
    INX
    INX
    CPX #PROPS_SIZE
    BCC @copy

    SEP #$20
    .a8
    LDA f:RANDO_SAVEFAR + (RANDO_TRAPS - RANDO_SAVE)
    BEQ @shops                  ; TRAPS_OFF
    CMP #TRAPS_MODES
    BCS @shops                  ; a mode this build does not know: as off
    JSR deal_traps

  @shops:
    JSR copy_shops
    LDA f:RANDO_SAVEFAR + (RANDO_SHOPS - RANDO_SAVE)
    BEQ @chests                 ; SHOPS_OFF
    CMP #SHOPS_MODES
    BCS @chests
    JSR deal_shops

  @chests:
    JSR copy_chests
    LDA f:RANDO_SAVEFAR + (RANDO_CHESTS - RANDO_SAVE)
    BEQ @done                   ; CHESTS_OFF
    CMP #CHESTS_MODES
    BCS @done
    JSR deal_chests
  @done:
    PLP
    RTS


;;  Is the tile at X a trap -- one FFR's Trap Tiles may move?
;;
;;  FFR's IsNonBossTrapTile: a battle tile whose formation is 1..$72.  Zero is
;;  excluded, and $73 up is either a boss ($73-$7F, which stay put) or, from
;;  $80, a random-encounter tile.  Read from the ROM, not the cache, so the
;;  answer does not change as the cache is dealt into.  The cartridge has 34.
;;
;;  In: A8, I16, X = the tile's offset.  Out: C set and A = the formation if it
;;  is one, C clear if not.
is_trap:
    .a8
    .i16
    LDA f:ROMPROPS, X
    CMP #TP_SPEC_BATTLE
    BNE @no
    LDA f:ROMPROPS + 1, X
    BEQ @no                     ; formation 0
    CMP #$73
    BCS @no                     ; bosses, and random encounters
    SEC
    RTS
  @no:
    CLC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_traps -- FFR's ShuffleTrapTiles, for its first five modes
;;
;;  Build a list of formations, then walk the trap tiles in table order and
;;  give each one a formation drawn from the list without replacement -- FFR's
;;  SpliceRandom.  The list is:
;;
;;    Shuffle   the trap tiles' own 34 formations
;;    A-side    every formation 1..$72 but WarMECH's $56       (113)
;;    B-side    every formation $80..$F2, and $FF              (116)
;;    Both      the A-side list, then the B-side list          (229)
;;
;;  $80 is formation 0's B-side and $FF is $7F's; FFR's list has both, and so
;;  this one does.  It also leaves out FFR's Fight Bahamut adjustment, because
;;  the port has no Fight Bahamut.
;;
;;  A drawn entry is replaced by the list's last, which is not FFR's
;;  RemoveAt but is just as uniform, and is what tools/randoref.py does.
;;
;;  In: A8 = the mode, 1..TRAPS_MODES-1; I16; DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_traps:
    .a8
    .i16
    STA a:wMODE

    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_TRAPS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_TRAPS)
    STA a:wRNG+2
    JSR rando_warm
    STZ a:wLEN                  ; both bytes: LDY reads it as a word
    SEP #$20
    .a8

    LDA a:wMODE
    CMP #TRAPS_SHUFFLE
    BNE @lists
    LDX #$0000
  @collect:
    JSR is_trap
    BCC @cnext
    LDY a:wLEN
    STA a:wLIST, Y
    INC a:wLEN
  @cnext:
    INX
    INX
    CPX #PROPS_SIZE
    BCC @collect
    BRA @deal

  @lists:
    CMP #TRAPS_BSIDE
    BEQ @bside
    JSR add_aside               ; A-side, and the first half of Both
    LDA a:wMODE
    CMP #TRAPS_BOTH
    BNE @deal
  @bside:
    JSR add_bside

  @deal:
    LDX #$0000
  @dloop:
    JSR is_trap
    BCC @dnext
    LDA a:wLEN
    BEQ @dnext                  ; the list ran dry; cannot, with these lists
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF                  ; TAY takes all sixteen bits of A
    TAY
    SEP #$20
    .a8
    LDA a:wLIST, Y
    STA a:wPROPS + 1, X         ; this trap's formation
    STY a:wR
    DEC a:wLEN
    LDY a:wLEN
    LDA a:wLIST, Y              ; the last entry...
    LDY a:wR
    STA a:wLIST, Y              ; ...fills the hole
  @dnext:
    INX
    INX
    CPX #PROPS_SIZE
    BCC @dloop
    RTS


;;  Append 1..$72 but $56.  A8, I16, DBR = $7F.
add_aside:
    LDA #$01
  @loop:
    CMP #$56                    ; WarMECH
    BEQ @skip
    LDY a:wLEN
    STA a:wLIST, Y
    INC a:wLEN
  @skip:
    INC A
    CMP #$73
    BCC @loop
    RTS

;;  Append $80..$F2, then $FF.  A8, I16, DBR = $7F.
add_bside:
    LDA #$80
  @loop:
    LDY a:wLEN
    STA a:wLIST, Y
    INC a:wLEN
    INC A
    CMP #$F3
    BCC @loop
    LDA #$FF
    LDY a:wLEN
    STA a:wLIST, Y
    INC a:wLEN
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_shops -- every shop's five bytes, as LoadShopInventory took them
;;
;;  The game copied five bytes from wherever a shop's pointer led, whatever
;;  followed the list's terminator: a three-item shop's item_box ends in the
;;  start of the next shop's list.  Each row here is those five bytes exactly,
;;  so with shops off item_box is what it always was, inns' and clinics'
;;  prices included.  Bytes 5-7 of a row are zero.
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_shops:
    .a8
    .i16
    LDY #$0000                  ; shop_id * 8
  @shop:
    REP #$20
    .a16
    TYA
    LSR A
    LSR A                       ; shop_id * 2
    TAX
    LDA f:ROMSHOPS, X
    TAX                         ; where its list is, in bank $0E
    SEP #$20
    .a8
    LDA f:BANK0EFAR + 0, X
    STA a:wSHOPS + 0, Y
    LDA f:BANK0EFAR + 1, X
    STA a:wSHOPS + 1, Y
    LDA f:BANK0EFAR + 2, X
    STA a:wSHOPS + 2, Y
    LDA f:BANK0EFAR + 3, X
    STA a:wSHOPS + 3, Y
    LDA f:BANK0EFAR + 4, X
    STA a:wSHOPS + 4, Y
    LDA #$00
    STA a:wSHOPS + 5, Y
    STA a:wSHOPS + 6, Y
    STA a:wSHOPS + 7, Y
    REP #$20
    .a16
    TYA
    CLC
    ADC #8
    TAY
    SEP #$20
    .a8
    CPY #RW_SHOPROWS * 8
    BCC @shop
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_shops -- FFR's ShuffleShops
;;
;;  Weapons, then armor, then items, from one stream, each by FFR's
;;  ShuffleShopType: pool the type's entries and shuffle them, give every shop
;;  one, then give each of the rest to a shop picked at random from those that
;;  have fewer than five and do not already sell it.  If an entry fits
;;  nowhere, start the type over.  Shops change size; an entry keeps its price,
;;  because prices are the item's, not the shop's.
;;
;;  The Caravan is an item shop to FFR, so the BOTTLE is in the pool and can
;;  land in any town, and rando_caravan keeps the Caravan open as FFR's
;;  PermanentCaravan does, so whatever lands there can still be bought after
;;  the fairy is out.  The BOTTLE is always buyable before it is needed: the
;;  fairy is at Gaia, which needs the airship, and by then every item shop is
;;  in reach.
;;
;;  Not ported: FFR's ImmediatePureAndSoftRequired, PURE and SOFT in the first
;;  town's item shop, and the reshuffle of that shop that goes with it.  FFR
;;  does not offer it as a flag; it turns itself on with status-touch changes,
;;  entrance shuffle and Enemizer, none of which exist here yet.
;;
;;  A restart is rare -- 26 seeds in 20,000 for the item shops, never more
;;  than one, and never for weapons or armor -- so the retry is unbounded, as
;;  FFR's is.
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_shops:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_SHOPS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_SHOPS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDA #1                      ; weapons: shop_id 1..10
    JSR deal_type
    LDA #11                     ; armor: 11..20
    JSR deal_type
    LDA #61                     ; items: 61..70, the Caravan last
    ;  fall through


;;  Deal the type whose ten shop_ids start at A.  Those whose pointer is shop
;;  0's are unused and take no part.
deal_type:
    .a8
    .i16
    STA a:wFIRST

    ;  The type's shops, in shop_id order, and their entries as the cartridge
    ;  has them -- read from the rows copy_shops made, up to each terminator.
    STZ a:wNSHOPS
    STZ a:wNENT
    STZ a:wP                    ; 0..9
  @gather:
    LDA a:wFIRST
    CLC
    ADC a:wP
    STA a:wQ                    ; the shop_id
    JSR is_used
    BCC @gnext
    LDY a:wNSHOPS
    LDA a:wQ
    STA a:wSHOPID, Y
    INC a:wNSHOPS
    JSR row_x                   ; X = its row
    LDA #5
    STA a:wK
  @entries:
    LDA a:wSHOPS, X
    BEQ @gnext
    LDY a:wNENT
    STA a:wORIG, Y
    INC a:wNENT
    INX
    DEC a:wK
    BNE @entries
  @gnext:
    INC a:wP
    LDA a:wP
    CMP #10
    BCC @gather

  @attempt:
    ;  Empty the type's rows, and shuffle a fresh copy of its entries.
    STZ a:wP
  @clr:
    LDY a:wP
    LDA #$00
    STA a:wCNT, Y
    LDA a:wSHOPID, Y
    JSR row_x
    LDA #$00
    STA a:wSHOPS + 0, X
    STA a:wSHOPS + 1, X
    STA a:wSHOPS + 2, X
    STA a:wSHOPS + 3, X
    STA a:wSHOPS + 4, X
    INC a:wP
    LDA a:wP
    CMP a:wNSHOPS
    BCC @clr

    LDX #$0000
  @copy:
    LDA a:wORIG, X
    STA a:wLIST, X
    INX
    CPX a:wNENT
    BCC @copy

    ;  Fisher-Yates, from the top: swap entry i with one drawn below i+1.
    LDA a:wNENT
    DEC A
    STA a:wI
  @fy:
    LDA a:wI
    BEQ @first
    INC A
    JSR rando_below
    STA a:wT2
    LDX a:wI
    LDY a:wT2
    LDA a:wLIST, X
    PHA
    LDA a:wLIST, Y
    STA a:wLIST, X
    PLA
    STA a:wLIST, Y
    DEC a:wI
    BRA @fy

    ;  One for every shop, in order.
  @first:
    STZ a:wE
    STZ a:wP
  @one:
    LDX a:wE
    LDA a:wLIST, X
    STA a:wITEM
    LDA a:wP
    JSR put
    INC a:wE
    INC a:wP
    LDA a:wP
    CMP a:wNSHOPS
    BCC @one

    ;  The rest, each to a random shop with room that lacks it.
  @rest:
    LDA a:wE
    CMP a:wNENT
    BCS @done
    LDX a:wE
    LDA a:wLIST, X
    STA a:wITEM
    STZ a:wNELIG
    STZ a:wP
  @elig:
    LDY a:wP
    LDA a:wCNT, Y
    CMP #5
    BCS @enext
    LDA a:wP
    JSR has_item
    BCS @enext
    LDY a:wNELIG
    LDA a:wP
    STA a:wELIG, Y
    INC a:wNELIG
  @enext:
    INC a:wP
    LDA a:wP
    CMP a:wNSHOPS
    BCC @elig
    LDA a:wNELIG
    BNE @place
    JMP @attempt                ; nowhere for it: start the type over
  @place:
    JSR rando_below
    STA a:wT2
    LDX a:wT2
    LDA a:wELIG, X
    JSR put
    INC a:wE
    BRA @rest
  @done:
    RTS


;;  C set if shop_id A is in use: its pointer is not shop 0's.  Keeps X, Y.
is_used:
    .a8
    .i16
    PHX
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:ROMSHOPS, X
    CMP f:ROMSHOPS              ; shop 0: the empty list
    SEP #$20
    .a8
    BEQ @no
    PLX
    SEC
    RTS
  @no:
    PLX
    CLC
    RTS

;;  X = the cache row of shop_id A.  Keeps Y.
row_x:
    .a8
    .i16
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAX
    SEP #$20
    .a8
    RTS

;;  Shop A (a position in the type's list) gets wITEM, at the end of its row.
put:
    .a8
    .i16
    STA a:wQ
    LDY a:wQ
    LDA a:wSHOPID, Y
    JSR row_x
    LDA a:wCNT, Y
    STA a:wT2
    REP #$20
    .a16
    TXA
    CLC
    ADC a:wT2
    TAX                         ; the row's next free byte
    SEP #$20
    .a8
    LDA a:wITEM
    STA a:wSHOPS, X
    LDA a:wCNT, Y
    INC A
    STA a:wCNT, Y
    RTS

;;  C set if shop A (a position in the type's list) already sells wITEM.
has_item:
    .a8
    .i16
    STA a:wQ
    LDY a:wQ
    LDA a:wSHOPID, Y
    JSR row_x
    LDA a:wCNT, Y
    BEQ @no
    STA a:wK
  @loop:
    LDA a:wSHOPS, X
    CMP a:wITEM
    BEQ @yes
    INX
    DEC a:wK
    BNE @loop
  @no:
    CLC
    RTS
  @yes:
    SEC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_shopinv -- LoadShopInventory
;;
;;  The game's routine copied five bytes from lut_ShopData into item_box and
;;  terminated it.  This copies them from the cache instead: as the cartridge
;;  had them with shops off, dealt with shops on.  Every shop comes through
;;  here, inns and clinics too, whose rows are their prices, untouched.
;;
;;  In: shop_id.  Out: item_box.  A, X, Y, P clobbered; DBR as it was.  The
;;  game's version also left a pointer in tmp; neither caller reads it.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_shopinv:
    PHB
    JSR enter
    JSR ensure
    REP #$30
    .a16
    .i16
    LDA z:shop_id
    AND #$00FF                  ; the byte after it is not ours
    ASL A
    ASL A
    ASL A
    CLC
    ADC #wSHOPS
    TAX
    LDY #item_box
    LDA #5 - 1
    MVN #^RANDOWRAM, #$7E       ; leaves DBR = $7E, which leave puts back
    SEP #$20
    .a8
    LDA #$00
    STA f:$7E0000 + item_box + 5  ; the terminator, as the game wrote it
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_caravan -- may the party walk into the Caravan?
;;
;;  The game shuts the Caravan once the fairy is out of the BOTTLE.  FFR never
;;  does (PermanentCaravan, one of its unconditional global hacks), and with
;;  the shops dealt that matters: the Caravan may hold anything.  So with
;;  shops shuffled it stays open; with shops off it is the game's rule.
;;
;;  Out: Z clear if the Caravan is shut.  A clobbered; X, Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

FAIRYFLAG = CHUNK0 * $10000 + game_flags + OBJID_FAIRY

rando_caravan:
    .a8
    .i8
    LDA f:RANDO_SAVEFAR + (RANDO_SHOPS - RANDO_SAVE)
    BEQ @game                   ; SHOPS_OFF
    CMP #SHOPS_MODES
    BCS @game                   ; a mode this build does not know: as off
    LDA #$00                    ; open
    RTL
  @game:
    LDA f:FAIRYFLAG
    AND #$01                    ; is the fairy out?
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_chests -- every chest's contents, as lut_Treasure has them
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_chests:
    .a8
    .i16
    LDX #$0000
  @copy:
    LDA f:ROMCHESTS, X
    STA a:wCHESTS, X
    INX
    CPX #256
    BCC @copy
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_chests -- FFR's treasure shuffle, without its logic
;;
;;  FFR places the key items by logic and then shuffles everything else into
;;  the chests that are left -- the treasure pool shuffled, zipped onto the
;;  locations.  Tier 1 has no logic, so the key items stay where the game put
;;  them, and this is that second step alone: every chest that holds no key
;;  item trades contents with the rest.  234 of them.
;;
;;  Which chests: the 241 that FFR does not mark unused.  Those are exactly
;;  the chest ids some map places, checked against the maps; the 14 unused
;;  ones, and id 0, hold items no one can reach -- a Zeus Gauntlet among them
;;  -- and dealing them in would lose whatever landed there.  A chest whose
;;  contents are below item_qty_start holds a key item: TNT, CROWN, RUBY,
;;  FLOATER, TAIL, SLAB and ADAMANT, one each.
;;
;;  Gold moves like anything else; a chest of gold is an id like any item.
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ITEM_QTY_START = item_qty_start - items

deal_chests:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_CHESTS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_CHESTS)
    STA a:wRNG+2
    JSR rando_warm
    STZ a:wLEN                  ; both bytes: LDY reads it as a word
    SEP #$20
    .a8

    ;  A flag per chest id for the unused ones, so the walk below is a load
    ;  rather than a search of the list for each of 256 ids.
    LDX #$0000
  @clear:
    STZ a:wUNUSED, X
    INX
    CPX #256
    BCC @clear
    LDY #$0000
  @mark:
    TYX
    LDA f:RANDOFAR + lut_UnusedChests, X   ; this chunk's: a label's bank is not known
    STA a:wT2
    LDX a:wT2
    LDA #$01
    STA a:wUNUSED, X
    INY
    CPY #UNUSED_CHESTS
    BCC @mark

    ;  The chests that move, in id order, and what is in them.
    LDX #$0000
  @gather:
    LDA a:wUNUSED, X
    BNE @next
    LDA a:wCHESTS, X
    CMP #ITEM_QTY_START
    BCC @next                   ; a key item, or nothing at all: stays
    LDY a:wLEN
    STA a:wLIST, Y
    TXA
    STA a:wLOCS, Y
    INC a:wLEN
  @next:
    INX
    CPX #256
    BCC @gather

    ;  Fisher-Yates over the contents, from the top.
    LDA a:wLEN
    DEC A
    STA a:wI
  @fy:
    LDA a:wI
    BEQ @place
    INC A
    JSR rando_below
    STA a:wT2
    LDX a:wI
    LDY a:wT2
    LDA a:wLIST, X
    PHA
    LDA a:wLIST, Y
    STA a:wLIST, X
    PLA
    STA a:wLIST, Y
    DEC a:wI
    BRA @fy

    ;  ...and back into the chests, in the same id order.
  @place:
    LDY #$0000
  @put:
    LDA a:wLOCS, Y
    STA a:wT2
    LDX a:wT2
    LDA a:wLIST, Y
    STA a:wCHESTS, X
    INY
    CPY a:wLEN
    BCC @put
    RTS


;;  FFR's ItemLocations, the ones marked isUnused, and chest 0, which it does
;;  not list.  No map places any of them.
lut_UnusedChests:
    .BYTE $00, $91, $92, $93, $94, $BB, $BC, $BD, $BE, $BF, $C0, $C1, $C2, $C3, $FF
UNUSED_CHESTS = * - lut_UnusedChests


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_chest -- what is in chest X
;;
;;  The read OpenTreasureChest made of lut_Treasure, from the cache instead.
;;  Its only read: Chest Information and Identify Treasures work from the
;;  item the dialogue is given, so they follow the shuffle unchanged.
;;
;;  In: X = chest id.  Out: A = its contents; X kept.  Y and P clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_chest:
    .a8
    .i8
    PHB
    PHX
    JSR enter
    JSR ensure                  ; leaves eight-bit registers
    PLX
    LDA a:wCHESTS, X
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_tileprop -- the property copy at the top of LoadSMTilesetData
;;
;;  The game copied the tileset's 256 property bytes out of bank $00 with
;;  Copy256.  This copies them out of the cache instead, which holds them
;;  re-encoded for the BNE test and with the traps dealt.  It runs on every
;;  map load, so the cache is checked on every map load, and turning a world
;;  on or off needs nothing more than a different save.
;;
;;  It leaves the pointers as Copy256 would have, for the TSA copies after
;;  it: tmp and tmp+2 zero, and tmp+3 one page past tileset_data.
;;
;;  In: cur_tileset.  Out: A, X, Y, P clobbered; DBR as it was.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_tileprop:
    PHB
    JSR enter
    JSR ensure
    REP #$30
    .a16
    .i16
    LDA z:cur_tileset
    AND #$0007                  ; eight tilesets; the high byte is not ours
    XBA                         ; 256 bytes each
    CLC
    ADC #wPROPS
    TAX
    LDY #tileset_prop
    LDA #256 - 1
    MVN #^RANDOWRAM, #$7E       ; leaves DBR = $7E, which leave puts back
    SEP #$20
    .a8
    STZ z:tmp
    STZ z:tmp+2
    LDA #>tileset_prop + 1
    STA z:tmp+3
    JMP leave
