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

.export rando_newgame, rando_stir, rando_tileprop
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

;  The cartridge's own tile property tables: eight tilesets, 128 tiles each,
;  two bytes a tile -- the function, then a parameter (for a battle tile, its
;  formation).  Read where LoadSMTilesetData reads them, with long addresses
;  so no bank has to be switched in.
ROMPROPS   = BANK00FAR + lut_SMTilesetProp
PROPS_SIZE = 8 * 256

;  Each feature's stream: the seed XORed with this, then warmed up.
STREAM_TRAPS = $54524150        ; "TRAP"

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
    BEQ @done                   ; TRAPS_OFF
    CMP #TRAPS_MODES
    BCS @done                   ; a mode this build does not know: as off
    JSR deal_traps
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
