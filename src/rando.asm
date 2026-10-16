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
;      whenever its tag disagrees with the save.  GameStart's @Begin, where
;      New Game and Continue meet, builds it before any game code runs, so
;      the build's pause falls in the transition into the game.  Every
;      consumer still calls ensure first, as a safety net: a Continue of a
;      different file or power-on would come out right even without @Begin,
;      because the tag cannot match a world it was not built from.  L+X and
;      L+Y leave WRAM alone, so the instant resets only compare the tag.
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
.include "fftext.inc"

.export rando_newgame, rando_stir, rando_tileprop, rando_shopinv, rando_caravan
.export rando_chest
.export rando_spell, rando_slot, rando_ibspell, rando_obspell, rando_oobspell
.export rando_menuspell, rando_shopspell, rando_shopmagic
.export rando_weaprec, rando_armrec, rando_weapbyte, rando_armbyte
.export rando_nameptr, rando_battlesubsrc
.export rando_formation, rando_formdata, rando_touch, rando_enemyai
.export rando_steprng, rando_mapedits, rando_teledest, rando_talk, rando_place
.export rando_entrdest, rando_exitdest, rando_princesswarp
.import es_tables
.export rando_price, rando_dlgtext
;  For tools/test_options.py.
.export rando_ensure, rando_stale, rando_xs, give_vehicle, rando_yield
.export rando_coldbuild
.export rando_caster
.export rando_belowfar, rando_warmfar, rando_yieldfar
;  New Game's roll screen (roll.asm), up while rando_newgame works.
.import roll_begin, roll_tick, roll_end

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
wPERM    = .LOWORD(RW_PERM)
wINV     = .LOWORD(RW_INV)
wWEAPONS = .LOWORD(RW_WEAPONS)
wARMOR   = .LOWORD(RW_ARMOR)
wBONUS   = .LOWORD(RW_BONUS)
wNAMEID  = .LOWORD(RW_NAMEID)
wNAMEPTR = .LOWORD(RW_NAMEPTR)
wNAMEB   = .LOWORD(RW_NAMEB)
wGI      = .LOWORD(RW_GI)
wGN      = .LOWORD(RW_GN)
wD2      = .LOWORD(RW_D2)
wD3      = .LOWORD(RW_D3)
wFLOOR   = .LOWORD(RW_FLOOR)
wCEIL    = .LOWORD(RW_CEIL)
wFN      = .LOWORD(RW_FN)
wFK      = .LOWORD(RW_FK)
wFD      = .LOWORD(RW_FD)
wFS      = .LOWORD(RW_FS)
wFC      = .LOWORD(RW_FC)
wFW      = .LOWORD(RW_FW)
wFV      = .LOWORD(RW_FV)
wFT      = .LOWORD(RW_FT)
wB16     = .LOWORD(RW_B16)
wM16     = .LOWORD(RW_M16)
wZONEOK  = .LOWORD(RW_ZONEOK)
wDOMAINS = .LOWORD(RW_DOMAINS)
wPOS     = .LOWORD(RW_POS)
wNORUN   = .LOWORD(RW_NORUN)
wSURPRISE = .LOWORD(RW_SURPRISE)
wTOUCH   = .LOWORD(RW_TOUCH)
wESCRIPT = .LOWORD(RW_ESCRIPT)
wSCRIPTS = .LOWORD(RW_SCRIPTS)
wSPL     = .LOWORD(RW_SPL)
wSPLB    = .LOWORD(RW_SPLB)
wSKL     = .LOWORD(RW_SKL)
wSKLB    = .LOWORD(RW_SKLB)
wSCH     = .LOWORD(RW_SCH)
wKCH     = .LOWORD(RW_KCH)
wBCNT    = .LOWORD(RW_BCNT)
wGRP     = .LOWORD(RW_GRP)
wAGN     = .LOWORD(RW_AGN)
wANSP    = .LOWORD(RW_ANSP)
wANSK    = .LOWORD(RW_ANSK)
wASB     = .LOWORD(RW_ASB)
wAKB     = .LOWORD(RW_AKB)
wAREROLL = .LOWORD(RW_AREROLL)
wASI     = .LOWORD(RW_ASI)
wAKI     = .LOWORD(RW_AKI)
wAGI     = .LOWORD(RW_AGI)
wAPREV   = .LOWORD(RW_APREV)
wASTART  = .LOWORD(RW_ASTART)
wAJ      = .LOWORD(RW_AJ)
wAREC    = .LOWORD(RW_AREC)
wAK      = .LOWORD(RW_AK)
wACAP    = .LOWORD(RW_ACAP)
wAN      = .LOWORD(RW_AN)
wABK     = .LOWORD(RW_ABK)
wENCRNG  = .LOWORD(RW_ENCRNG)
wBATRNG  = .LOWORD(RW_BATRNG)

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
STREAM_MAGIC  = $4D414743       ; "MAGC"
STREAM_GEAR   = $424C5253       ; "BLRS"
STREAM_ZONES  = $5A4F4E45       ; "ZONE"
STREAM_RARITY = $52415245       ; "RARE": its own, so zones cannot reshuffle it

;  lut_Domains: 128 zones of 8 formation ids, bank $0B.  Zones 0-63 are the
;  overworld's 8x8 grid, 64 up the standard maps by cur_map.  A battle picks a
;  slot by lut_FormationWeight from the fixed bank, indexed by the battle
;  counter's byte of lut_RNG.
ROMDOMAINS   = BANK0BFAR + lut_Domains
DOMAINS_SIZE = 128 * 8
WARMECH_FORM = $56              ; Sky Palace 5F's slot 6; Light and Shuffle pin it
.import lut_RNG, lut_FormationWeight

;  lut_BattleFormations, bank $0B: 128 records of 16 bytes.  Byte $0C is the
;  surprise rate, bit 0 of $0D the no-run flag, for both sides.  0-114 are the
;  normal formations; 115-123 the fiends, twice each, and Chaos; 124-127
;  Vampire, Astos, the pirates and Garland, whose B-sides are ordinary fights.
.import lut_BattleFormations
ROMFORMS     = BANK0BFAR + lut_BattleFormations
NORMAL_FORMS = 115
CHAOS_FORM   = 123
STREAM_RUNS     = $52554E53     ; "RUNS"
STREAM_SURPRISE = $53555250     ; "SURP"

;  data_EnemyStats, bank $0C: 128 records of 20 bytes.  Byte 7 is the script
;  id ($FF for none), $0E the touch's element and $0F its ailment.  Enemies
;  0-117 are normal, 15 the pirates; 118 WarMECH, 119-126 the four fiends and
;  their refights alternately, 127 Chaos.  lut_EnemyAi, bank $0C: 44 scripts
;  of 16 bytes -- spell chance, skill chance, 8 spells, $FF, 4 skills, $FF.
.import data_EnemyStats, lut_EnemyAi
ROMENEMIES   = BANK0CFAR + data_EnemyStats
ROMENEMYAI   = BANK0CFAR + lut_EnemyAi
SCRIPTS_SIZE = 44 * 16
PIRATES      = 15
FADE_SPELL   = 57               ; FFR's nukes: all-enemy, non-elemental, 80 up
NUKE_SPELL   = 60
NUCLEAR      = $14              ; the skill
CRACK_SCRIPT = 7                ; FFR takes two CRACKs and two TOXICs out
TOXIC_SCRIPT = 27
STREAM_TOUCH    = $54554348     ; "TUCH"
STREAM_SCRIPTS  = $53435250     ; "SCRP"
STREAM_BSCRIPTS = $42534352     ; "BSCR"
STREAM_SKILLS   = $534B494C     ; "SKIL"
STREAM_BSKILLS  = $42534B4C     ; "BSKL"
STREAM_RNG      = $524E4754     ; "RNGT"
STREAM_ORDEALS  = $4F52444C     ; "ORDL"
STREAM_KEYS     = $4B455953     ; "KEYS"
STREAM_CASTER   = $43415354     ; "CAST": the starting caster item's one draw
STREAM_ITEMMAGIC = $494D4147    ; "IMAG"

;  The battle table moved to the options chunk; the encounter table is in the
;  fixed bank, and so in this chunk too.
.import lut_BattleScramble
ROMBATRNG    = OPTFAR + lut_BattleScramble
ROMENCRNG    = RANDOFAR + lut_RNG

;  The weapon and armour tables, contiguous in bank $0C: 40 x 8, then 40 x 4.
.import lut_WeaponData, lut_ArmorData
.import lut_SpellNames              ; the options chunk's, four letters each
ROMGEAR    = BANK0CFAR + lut_WeaponData
.assert lut_ArmorData = lut_WeaponData + 40 * 8, lderror, "armour no longer follows the weapons"

;  Item names: lut_ItemNamePtrTbl in bank $0A, a pointer per item id into the
;  same bank.  Gear is item ids $1C up, weapons then armour.
.assert BANK0AFAR = (CHUNK0 + BANK_ITEMS) * $10000, error, "BANK0AFAR is not BANK_ITEMS"
SRAMFAR    = CHUNK0 * $10000    ; SRAM, from a bank that decodes it

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
    JSR rando_yield             ; every draw: the roll screen's tick, if due
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


;;  rando_caster -- the starting caster item's draw, for opt_casteritem
;;
;;  One number below A from the game's own stream, so a seed always starts
;;  with the same item, and no other feature's draws move with it.  Called by
;;  New Game after rando_newgame has written the seed, and only then.
;;
;;  In: A = the pool's size, 1..255.  Out: A = 0..A-1; X and Y kept.
;;  Emulation mode in and out.
rando_caster:
    .a8
    .i8
    PHB
    PHX
    PHY
    PHA
    JSR enter
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_CASTER)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_CASTER)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    PLA
    JSR rando_below
    PLY
    PLX
    JMP leave


;;  The PRNG for entrance shuffle's chunk (world.asm), as long calls: the
;;  same draws, from one copy of the code.  DBR = $7F, as within this chunk.
rando_belowfar:
    .a8
    JSR rando_below
    RTL

;;  New Game's roll screen ticks from here (roll.asm): called often -- every
;;  draw, every ask the logic makes, every visit of entrance shuffle's
;;  fixpoint -- it ticks the screen when the screen is up and a vblank has
;;  begun since the last tick, which RDNMI latches; otherwise it is nine
;;  instructions.  ROLL_ON is zero but while the screen is up, so the cache
;;  build at @Begin, and the harness, never tick.  Native, any widths;
;;  everything kept.
rando_yield:
    PHP
    SEP #$20
    .a8
    PHA
    LDA f:ROLL_ON
    BEQ @out
    LDA f:RDNMI
    BPL @out
    JSL roll_tick + ROLLFAR
  @out:
    PLA
    PLP
    RTS
rando_yieldfar:
    JSR rando_yield
    RTL
rando_warmfar:
    .a16
    JSR rando_warm
    RTL


;;  rando_below for bounds past 255: the same mask-and-reject, sixteen bits
;;  wide, from the low half of the new state.
;;
;;  In: A16 = the bound, 1..$FFFF; DBR = $7F.  Out: A16 = the number.  X and
;;  Y are not touched.
rando_below16:
    .a16
    JSR rando_yield             ; every draw: the roll screen's tick, if due
    STA a:wB16
    DEC A
    STA a:wM16
    LSR A
    ORA a:wM16
    STA a:wM16
    LSR A
    LSR A
    ORA a:wM16
    STA a:wM16
    LSR A
    LSR A
    LSR A
    LSR A
    ORA a:wM16
    STA a:wM16
    XBA                         ; and the high byte smeared into the low
    AND #$00FF
    ORA a:wM16
    STA a:wM16
  @draw:
    JSR xs_step
    AND a:wM16
    CMP a:wB16
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
;;  settings screen's new-game rows in beside it, places the key items, and
;;  builds the cache: all of New Game's work in one pause, before the party
;;  is rolled.  Party creation touches neither page 0 nor the cache, so
;;  GameStart's @Begin, which follows it, finds the cache whole and only
;;  compares the tag.
;;
;;  Nothing calls the music driver meanwhile, and the SPC700 would hold the
;;  title's last note through it: silence first, as @Begin does.  Party
;;  creation turns the channels back on as it starts (its LDA #$0F, $4015).
;;
;;  Out: X and P as they were.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.import DisableAPU
rando_newgame:
    PHP
    PHX
    JSR DisableAPU              ; the fixed bank's, stamped into this chunk
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
    ;  This game's reward NPCs run from rando_talk's table, and none has given.
    LDA #1
    STA f:RANDO_TALKFAR
    LDA #0
    STA f:RANDO_GIVENFAR
    STA f:RANDO_GIVENFAR + 1
    ;  The roll screen comes up for the work, the seed choosing its picture.
    JSL roll_begin + ROLLFAR
    ;  ...and where its key items are, under Key items Standard or Wide.
    JSL rando_place + RANDOFAR
    ;  ...and the world itself, now rather than at @Begin.
    JSL rando_ensure + RANDOFAR
    ;  The fanfare, the fade, the title's music again for party creation, and
    ;  the PPU back to the HAL.
    LDA #TITLEMUSIC
    JSL roll_end + ROLLFAR
    PLX
    PLP
    RTL

TITLEMUSIC = $41                ; IntroTitlePrepare's, which party creation hears

;;  A cold cache at @Begin -- a Continue the first after power-on, the save's
;;  world not in WRAM -- built as New Game builds it, the roll screen up and
;;  the same seed's sprite on it (user, 2026-10-15); but no track after,
;;  since PrepOverworld starts the overworld's.  From @Begin when rando_stale
;;  says so, in emulation mode, by JSL.
rando_coldbuild:
    PHP
    JSR DisableAPU              ; the title's music: nothing drives it meanwhile
    JSL roll_begin + ROLLFAR
    JSL rando_ensure + RANDOFAR
    LDA #0
    JSL roll_end + ROLLFAR
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
;;  rando_ensure is the JSL entry for New Game, @Begin and the harness;
;;  consumers JSR ensure.  rando_stale asks without building: @Begin silences the music
;;  first when the answer is yes, since nothing calls the driver during a
;;  build.  Out: C set if ensure would build.  A is zero, X is clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_ensure:
    PHB
    JSR enter
    JSR ensure
    JMP leave

rando_stale:
    PHB
    JSR enter
    JSR stale                   ; leaves eight-bit registers
    LDA #0
    ROL A                       ; the answer, kept through XCE and PLB...
    SEC
    XCE
    PLB
    LSR A                       ; ...and back in C
    RTL

;;  Native mode, DBR = $7F.  Out: A8, I8.
ensure:
    JSR stale
    BCS @build
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

;;  Native mode, DBR = $7F.  Out: A8, I8; C set if the cache does not match
;;  the save.
stale:
    SEP #$30
    .a8
    .i8
    LDA a:wTAG
    CMP #RW_TAG_VAL
    BNE @stale
    LDX #RANDO_SAVE_SIZE - 1
  @cmp:
    LDA f:RANDO_SAVEFAR, X
    CMP a:wTAGBLK, X
    BNE @stale
    DEX
    BPL @cmp
    CLC
    RTS
  @stale:
    SEC
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
    LDA #ROLLSTAGE_BUILD        ; the roll screen's tune, while New Game's
    STA f:ROLL_STAGE

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
    ;  Early Ordeals: FFR's EnableEarlyOrdeals clears the special code of the
    ;  Castle tileset's two thrones, the only crown tiles, so each is a plain
    ;  teleport and the CROWN is not asked for.
    LDA f:RANDO_SAVEFAR + (RANDO_EARLY - RANDO_SAVE)
    AND #EARLY_ORDEALS
    BEQ @traps
    LDA a:wPROPS + TS_CASTLE * 256 + THRONE_TILE1 * 2
    AND #<~TP_SPEC_MASK
    STA a:wPROPS + TS_CASTLE * 256 + THRONE_TILE1 * 2
    LDA a:wPROPS + TS_CASTLE * 256 + THRONE_TILE2 * 2
    AND #<~TP_SPEC_MASK
    STA a:wPROPS + TS_CASTLE * 256 + THRONE_TILE2 * 2
  @traps:
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
    LDA f:RANDO_PLACEDFAR       ; key items placed: the rewards deal it all
    CMP #1
    BNE @tier1
    JSR deal_rewards
    BRA @magic
  @tier1:
    LDA f:RANDO_SAVEFAR + (RANDO_CHESTS - RANDO_SAVE)
    BEQ @magic                  ; CHESTS_OFF
    CMP #CHESTS_MODES
    BCS @magic
    JSR deal_chests

  @magic:
    JSR copy_magic
    LDA f:RANDO_SAVEFAR + (RANDO_MAGIC - RANDO_SAVE)
    AND #MAGIC_FIELD            ; item magic's field is above it
    BEQ @inverse                ; MAGIC_OFF
    CMP #MAGIC_MODES
    BCS @inverse
    JSR deal_magic
  @inverse:
    JSR make_inverse

  @gear:
    JSR copy_gear
    LDA f:RANDO_SAVEFAR + (RANDO_BLESS - RANDO_SAVE)
    CMP #BLURSE_STEPS
    BCS @itemmagic              ; out of range: as none
    LDA f:RANDO_SAVEFAR + (RANDO_CURSE - RANDO_SAVE)
    CMP #BLURSE_STEPS
    BCS @itemmagic
    ORA f:RANDO_SAVEFAR + (RANDO_BLESS - RANDO_SAVE)
    BEQ @itemmagic              ; both nothing: off
    JSR deal_gear
    ;  Item magic after the bonuses, which never touch the spell byte.
  @itemmagic:
    LDA f:RANDO_SAVEFAR + (RANDO_MAGIC - RANDO_SAVE)
    AND #ITEMMAGIC_FIELD
    BEQ @forms                  ; ITEMMAGIC_OFF
    CMP #ITEMMAGIC_MODES << ITEMMAGIC_SHIFT
    BCS @forms                  ; a mode this build does not know: as off
    JSR deal_itemmagic

    ;  Formations: zones first, then rarity, each its own pass and stream.
  @forms:
    JSR copy_domains
    LDA f:RANDO_SAVEFAR + (RANDO_ZONES - RANDO_SAVE)
    BEQ @rarity                 ; ZONES_OFF
    CMP #ZONES_MODES
    BCS @rarity
    JSR deal_zones
  @rarity:
    LDA f:RANDO_SAVEFAR + (RANDO_FORMS - RANDO_SAVE)
    BEQ @runs                   ; FORMS_OFF
    CMP #FORMS_MODES
    BCS @runs
    JSR deal_rarity

  @runs:
    JSR copy_runs
    LDA f:RANDO_SAVEFAR + (RANDO_NORUN - RANDO_SAVE)
    BEQ @surprise               ; RUNS_OFF
    CMP #RUNS_MODES
    BCS @surprise
    JSR deal_runs
  @surprise:
    LDA f:RANDO_SAVEFAR + (RANDO_SURPRISE - RANDO_SAVE)
    BEQ @touch                  ; SURPRISE_OFF
    CMP #SURPRISE_MODES
    BCS @touch
    JSR deal_surprise

  @touch:
    JSR copy_touch
    LDA f:RANDO_SAVEFAR + (RANDO_STATUS - RANDO_SAVE)
    BEQ @ai                     ; STATUS_OFF
    CMP #STATUS_MODES
    BCS @ai
    JSR deal_touch

    ;  Scripts, then what is in them; each half of each row its own stream.
  @ai:
    JSR copy_ai
    LDA f:RANDO_SAVEFAR + (RANDO_SCRIPTS - RANDO_SAVE)
    CMP #AI_MODES
    BCS @skills                 ; no mode: as off
    AND #AI_ENEMIES
    BEQ @bscripts
    JSR deal_escripts
  @bscripts:
    LDA f:RANDO_SAVEFAR + (RANDO_SCRIPTS - RANDO_SAVE)
    AND #AI_BOSSES
    BEQ @skills
    JSR deal_bscripts
  @skills:
    LDA f:RANDO_SAVEFAR + (RANDO_SKILLS - RANDO_SAVE)
    CMP #AI_MODES
    BCS @done
    AND #AI_ENEMIES
    BEQ @bskills
    JSR deal_eskills
  @bskills:
    LDA f:RANDO_SAVEFAR + (RANDO_SKILLS - RANDO_SAVE)
    AND #AI_BOSSES
    BEQ @rng
    JSR deal_bskills

  @rng:
    JSR copy_rng
    LDA f:RANDO_SAVEFAR + (RANDO_RNG - RANDO_SAVE)
    BEQ @ordeals                ; RNG_OFF
    CMP #RNG_MODES
    BCS @ordeals
    JSR deal_rng
  @ordeals:
    LDA f:RANDO_SAVEFAR + (RANDO_ORDEALS - RANDO_SAVE)
    BEQ @wiring                 ; ORDEALS_OFF
    CMP #ORDEALS_MODES
    BCS @wiring
    JSR deal_ordeals
  @wiring:
    ;  The teleport tables the game reads: the save's wiring under entrance
    ;  shuffle, else vanilla's (entrance shuffle's chunk).
    JSL es_tables + WORLDFAR
  @done:
    PLP
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_ordeals -- the Castle of Ordeals' pillars
;;
;;  FFR's ShuffleOrdeals (StandardMaps/ShuffleOrdeals.cs), as randoref.py's
;;  build_ordeals, draw for draw.  The eight rooms are shuffled until the
;;  four-pad room is not first, and follow the start room in a chain: one pad
;;  of each room, picked at random, leads to the next, the last one's out.
;;  Every other pad leads back to the same room or an earlier one, except in
;;  the four-pad room, whose three spare pads -- shuffled -- go back two
;;  different ways and one anywhere but onward.  Every room is on the chain,
;;  so there is always a way through.
;;
;;  In: A8, I16, DBR = $7F.  Out: RW_ORDPADS, the pads' tiles in lut_OrdPad
;;  order; A8, I16.  The working lists are in RW_LIST, free between deals.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

wORD    = .LOWORD(RW_ORDPADS)
wOSEQ   = wLIST                 ; the chain, room ids by position, 9
wOLEFT  = wLIST + $10           ; pads left in each position's room, 9
wOPADS  = wLIST + $20           ; ...which, four slots a position, 36
wOI     = wLIST + $50           ; the position being worked on
wOK     = wLIST + $51           ; a pick, or a count down
wOCNT   = wLIST + $52           ; a room's pad count
wOFIRST = wLIST + $53           ; ...and its first pad
wOEND   = wLIST + $54           ; one past a position's last live slot
wOPAD   = wLIST + $55           ; the pad the chain takes
wOBASE  = wLIST + $56           ; a position's first slot
wOBACK  = wLIST + $57           ; the four-pad room's three destinations
wOOTHER = wLIST + $58
wOANY   = wLIST + $59

deal_ordeals:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_ORDEALS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_ORDEALS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$30                    ; eight-bit indices: everything here is small,
    .a8                         ;   and TAY then carries no stray high byte
    .i8

    ;  The eight rooms, shuffled afresh until the four-pad room is not first.
  @shuffle:
    STZ a:wOSEQ                 ; position 0: the start room
    LDX #$01
  @fill:
    TXA
    STA a:wOSEQ, X
    INX
    CPX #ORD_ROOMS
    BCC @fill
    LDX #$07                    ; Fisher-Yates over positions 1-8
  @fy:
    TXA
    INC A
    JSR rando_below             ; j <= i
    TAY
    LDA a:wOSEQ + 1, X
    PHA
    LDA a:wOSEQ + 1, Y
    STA a:wOSEQ + 1, X
    PLA
    STA a:wOSEQ + 1, Y
    DEX
    BNE @fy
    LDX a:wOSEQ + 1
    LDA f:RANDOFAR + lut_OrdRoomCount, X
    CMP #$04
    BEQ @shuffle

    ;  Each position's pads, in its room's order.
    LDX #$00
  @lists:
    STX a:wOI
    LDA a:wOSEQ, X
    TAX
    LDA f:RANDOFAR + lut_OrdRoomCount, X
    STA a:wOCNT
    LDA f:RANDOFAR + lut_OrdRoomFirst, X
    STA a:wOFIRST
    LDX a:wOI
    LDA a:wOCNT
    STA a:wOLEFT, X
    TXA
    ASL A
    ASL A
    TAY
    LDX #$00
  @pads:
    TXA
    CLC
    ADC a:wOFIRST
    STA a:wOPADS, Y
    INY
    INX
    CPX a:wOCNT
    BCC @pads
    LDX a:wOI
    INX
    CPX #ORD_ROOMS
    BCC @lists

    ;  The chain: a pad of each position, taken out of its list as Python's
    ;  pop() takes it, to the next room, or out.
    LDX #$00
  @chain:
    STX a:wOI
    TXA
    ASL A
    ASL A
    CLC
    ADC a:wOLEFT, X
    STA a:wOEND
    LDA a:wOLEFT, X
    JSR rando_below             ; which of the pads left
    STA a:wOK
    LDA a:wOI
    ASL A
    ASL A
    CLC
    ADC a:wOK
    TAY
    LDA a:wOPADS, Y
    STA a:wOPAD
  @shift:
    INY
    CPY a:wOEND
    BCS @shifted
    LDA a:wOPADS, Y
    STA a:wOPADS - 1, Y
    BRA @shift
  @shifted:
    LDX a:wOI
    DEC a:wOLEFT, X
    CPX #ORD_ROOMS - 1
    BCS @out
    LDA a:wOSEQ + 1, X
    TAX
    LDA f:RANDOFAR + lut_OrdRoomTile, X
    BRA @put
  @out:
    LDA #ORD_EXIT
  @put:
    LDX a:wOPAD
    STA a:wORD, X
    LDX a:wOI
    INX
    CPX #ORD_ROOMS
    BCC @chain

    ;  The rest.
    LDX #$00
  @rest:
    STX a:wOI
    TXA
    ASL A
    ASL A
    STA a:wOBASE
    LDA a:wOLEFT, X
    CMP #$01
    BEQ @one
    CMP #$03
    BEQ @three
    JMP @next
  @one:
    TXA
    INC A
    JSR rando_below             ; back to this room or an earlier one
    LDY a:wOBASE
    JSR ord_put
    JMP @next
  @three:
    LDA #$02                    ; its three spare pads, shuffled
    STA a:wOK
  @fy3:
    LDA a:wOK
    INC A
    JSR rando_below
    CLC
    ADC a:wOBASE
    TAY
    LDA a:wOK
    CLC
    ADC a:wOBASE
    TAX
    LDA a:wOPADS, X
    PHA
    LDA a:wOPADS, Y
    STA a:wOPADS, X
    PLA
    STA a:wOPADS, Y
    DEC a:wOK
    BNE @fy3
  @back:
    LDA a:wOI
    INC A
    JSR rando_below
    STA a:wOBACK
  @other:
    LDA a:wOI
    INC A
    JSR rando_below
    CMP a:wOBACK
    BEQ @other
    STA a:wOOTHER
  @any:                         ; anywhere but those two, or onward
    LDA #ORD_ROOMS
    JSR rando_below
    STA a:wOANY
    CMP a:wOBACK
    BEQ @any
    CMP a:wOOTHER
    BEQ @any
    DEC A
    CMP a:wOI
    BEQ @any
    LDA a:wOBACK
    LDY a:wOBASE
    JSR ord_put
    LDA a:wOOTHER
    LDY a:wOBASE
    INY
    JSR ord_put
    LDA a:wOANY
    LDY a:wOBASE
    INY
    INY
    JSR ord_put
  @next:
    LDX a:wOI
    INX
    CPX #ORD_ROOMS
    BCS @dealt
    JMP @rest
  @dealt:
    REP #$10
    .i16
    RTS

;;  The pad in slot Y of wOPADS leads to the room at chain position A.
;;  In: A8, I8.
ord_put:
    .a8
    .i8
    TAX
    LDA a:wOSEQ, X
    TAX
    LDA f:RANDOFAR + lut_OrdRoomTile, X
    PHA
    LDA a:wOPADS, Y
    TAX
    PLA
    STA a:wORD, X
    RTS

;;  The pads, in FFR's order: the start room's, then the rooms' (x, y on
;;  Castle of Ordeals 2F).  The rooms: the start room's index is 0, and each
;;  room has the tile that lands in it, its first pad, and how many.
lut_OrdPadX:      .BYTE $10, $0F, $08, $08, $09, $04, $04, $04, $01, $03, $06, $14, $14, $12, $08
lut_OrdPadY:      .BYTE $0F, $09, $08, $0A, $0F, $14, $16, $12, $01, $02, $08, $0B, $0D, $10, $12
lut_OrdRoomTile:  .BYTE $4E, $4C, $4D, $4F, $50, $51, $52, $53, $54
lut_OrdRoomFirst: .BYTE 0,   1,   2,   4,   5,   7,   8,   10,  14
lut_OrdRoomCount: .BYTE 1,   1,   2,   1,   2,   1,   2,   4,   1
.assert * - lut_OrdRoomCount = ORD_ROOMS, error, "one count per room"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_mapedits -- the dealt pads, written over Castle of Ordeals 2F
;;
;;  From opt_mapedits, which LoadStandardMapAndObjects calls once the map is
;;  decompressed into mapdata.  Emulation mode in and out.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_mapedits:
    .a8
    .i8
    LDA cur_map
    CMP #MAP_ORDEALS2F
    BNE @none
    LDA f:RANDO_SAVEFAR + (RANDO_ORDEALS - RANDO_SAVE)
    BEQ @none
    CMP #ORDEALS_MODES
    BCS @none
    PHB
    JSR enter
    JSR ensure
    REP #$10
    .i16
    LDY #ORD_PADS - 1
  @pad:
    TYX
    REP #$20
    .a16
    LDA f:RANDOFAR + lut_OrdPadY, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:wT
    LDA f:RANDOFAR + lut_OrdPadX, X
    AND #$00FF
    CLC
    ADC a:wT
    TAX                         ; the pad's offset in the map
    SEP #$20
    .a8
    LDA a:wORD, Y
    STA f:SRAMFAR + mapdata, X
    DEY
    BPL @pad
    JMP leave
  @none:
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_teledest -- where a normal teleport lands
;;
;;  From @NormalTeleport in the fixed bank, which read lut_NormTele_X and _Y
;;  itself until the Ordeals pillars needed one of them moved: with the shuffle
;;  on, teleport $3C, tile $54's, lands at FFR's (16, 18) rather than (14, 20).
;;
;;  In: X = the teleport.  Out: sm_scroll_x and _y, each the landing less 7
;;  and wrapped, as the code this replaced made them; X kept.  Emulation mode.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_teledest:
    .a8
    .i8
    PHB
    PHX
    JSR enter
    JSR ensure                  ; leaves A8, I8
    PLX
    CPX #ORD_LOST_TELE
    BNE @table
    LDA f:RANDO_SAVEFAR + (RANDO_ORDEALS - RANDO_SAVE)
    BEQ @table
    CMP #ORDEALS_MODES
    BCS @table
    LDA #ORD_LOST_X
    JSR tele_scroll
    STA sm_scroll_x
    LDA #ORD_LOST_Y
    JSR tele_scroll
    STA sm_scroll_y
    BRA @map
  @table:
    LDA f:RW_NORMX, X
    JSR tele_scroll
    STA sm_scroll_x
    LDA f:RW_NORMY, X
    JSR tele_scroll
    STA sm_scroll_y
  @map:
    LDA f:RW_NORMMAP, X         ; the map, in A
    JMP leave

;;  An overworld entrance's landing, as rando_teledest's: X = its id.  Out:
;;  the scroll set, A = the map, X kept.  From the cache's table, the save's
;;  wiring under entrance shuffle.
rando_entrdest:
    .a8
    .i8
    PHB
    PHX
    JSR enter
    JSR ensure
    PLX
    LDA f:RW_ENTRX, X
    JSR tele_scroll
    STA sm_scroll_x
    LDA f:RW_ENTRY, X
    JSR tele_scroll
    STA sm_scroll_y
    LDA f:RW_ENTRMAP, X
    JMP leave

;;  An exit's overworld landing: X = its id.  Out: the overworld scroll set.
rando_exitdest:
    .a8
    .i8
    PHB
    PHX
    JSR enter
    JSR ensure
    PLX
    LDA f:RW_EXITX, X
    SEC
    SBC #7
    STA ow_scroll_x
    LDA f:RW_EXITY, X
    SEC
    SBC #7
    STA ow_scroll_y
    JMP leave

;;  A landing coordinate's scroll: 7 back, wrapped to the map.
tele_scroll:
    SEC
    SBC #7
    AND #$3F
    RTS

;;  The rescued Princess's teleport back to Coneria Castle, set up as
;;  Talk_Princess1's TalkNormTeleport did -- except under entrance shuffle,
;;  where FFR drops it (Dialogues.cs, "Disable the Princess Warp back to
;;  Castle Coneria"): the castle need not be beside the Temple, nor its
;;  floors where they were, and a party set down in it can be stranded.  The
;;  logic never counted on it: the world graph has the party walk out of the
;;  Temple.  From Talk_Princess1 (randoprincess.patch), emulation mode, the
;;  game's data bank.  A clobbered; X and Y kept.
rando_princesswarp:
    LDA f:RANDO_SAVEFAR + (RANDO_ENTRANCES - RANDO_SAVE)
    BNE :+
    LDA #NORMTELE_SAVEDPRINCESS
    STA tileprop+1
    LDA #TP_TELE_NORM           ; taken as the dialogue box closes
    STA tileprop
:   RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_talk -- the reward NPCs, and NPC Guillotine
;;
;;  From OptGuillotine, the funnel every talk dispatch in bank $0E ends in.
;;  The thirteen NPCs that give a key item, a vehicle or the Xcalber are run
;;  here from a table -- what each wants first, what it gives, which of its
;;  three lines it says when -- once a new game has set RANDO_TALK.  The table
;;  holds the vanilla rewards for now; it is what incentive placement will
;;  change (randomization-notes.md section 3).  A save from before RANDO_TALK
;;  keeps the vanilla handlers, so its NPCs' state is never read two ways.
;;
;;  Every other object goes on to its handler, which NPC Guillotine may first
;;  swap: Talk_norm for Talk_CoOGuy when the option is on, except for the two
;;  plates, which hold the Rod and the Lute's way forward.
;;
;;  The order of the tests reproduces every vanilla handler, Free items
;;  included: given before, then the event the NPC waits for, then whether the
;;  party already holds what it gives (the vanilla handlers' own test, which
;;  is what keeps a Free LUTE from bringing a second one), then the item it
;;  wants.  Nerrick, Astos and the Smith never asked what the party holds, so
;;  they have no TALKF_HELD.
;;
;;  DBR is the caller's, a game bank, so the game's variables are plain
;;  absolute here as in bank $0E's routines; the tables are long.
;;
;;  In: X = the map object's offset in mapobj, tmp..tmp+3 its talk data,
;;      (tmp+6) the handler TalkToObject resolved.  Emulation mode.
;;  Out: C set and A = the dialogue id, the NPC handled here; or C clear, and
;;       the funnel jumps to (tmp+6).  X kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  The reward NPCs.  RANDO_GIVEN's bit n is entry n.
TALK_COUNT    = 13

;  What an NPC waits for (lut_TalkReq), with lut_TalkArg as its operand.
TREQ_NONE     = 0         ; nothing
TREQ_VISIBLE  = 1         ; object Arg shown: the King, the rescued Princess
TREQ_HIDDEN   = 2         ; object Arg gone: Sarda, the Vampire beaten
TREQ_EVENT    = 3         ; object Arg's event flag: the Elf Prince awake; Unne
TREQ_HAVE     = 4         ; the party holds item Arg: Astos, the CROWN
TREQ_TRADE    = 5         ; as TREQ_HAVE, and the item is taken in exchange

;  lut_TalkFlags.
TALKF_FIGHT   = $01       ; Bikke: the first talk fights (lut_TalkBattle) and
                          ;   sets his event flag; the reward is the next, and
                          ;   shows the townsfolk his pirates were terrorizing
TALKF_HIDE    = $02       ; gone once it has given: Astos, Nerrick
TALKF_BATTLE  = $04       ; and fights lut_TalkBattle as it gives: Astos
TALKF_GREEDY  = $08       ; a full bag is "Don't be greedy": the Smith
TALKF_HELD    = $10       ; holding the reward already counts as given
TALKF_WAIVED  = $80       ; not in the table: an Early flag has waived what it
                          ;   waits for, this talk (tmp+6 only)

;  Rewards: what a chest holds ($01-$1B items, $1C-$43 weapons, $44-$6B
;  armor), and the vehicles, which no chest holds.
REWARD_SHIP   = $F0
REWARD_BRIDGE = $F1
REWARD_CANAL  = $F2
REWARD_CANOE  = $F3
REWARD_XCALBER = TCITYPE_WEPSTART - 1 + WPNID_XCALBUR
;  The ids the dialogue names a vehicle by (give_vehicle, rando_nameptr).
NAME_CANOE    = $11       ; the game's own CANOE
NAME_SHIP     = $12       ; the orbs' ids: empty names, never drawn
NAME_BRIDGE   = $13
NAME_CANAL    = $14

.import Talk_norm, Talk_CoOGuy
.import FindEmptyWeaponSlot, FindEmptyArmorSlot, ShowMapObject, OptCallFar, AddGPToParty
.include "optcall.inc"

rando_talk:
    .a8
    .i8
    PHX
    LDA f:RANDO_TALKFAR
    BEQ @other
    LDA mapobj_id, X
    LDX #TALK_COUNT - 1
  @find:
    CMP f:RANDOFAR + lut_TalkObj, X
    BEQ @ours
    DEX
    BPL @find
  @other:
    PLX
    ;  NPC Guillotine.  The id is mapobj_id's, not temp RAM's: tmp..tmp+3 is
    ;  the talk data, and TalkToObject's backup of the id in tmp+6 is already
    ;  the handler (test_guillotine puts a decoy in tmp).
    LDA OPTFB_GUILLOTINE
    AND #OPTFM_GUILLOTINE
    BEQ @dispatch
    LDA mapobj_id, X
    CMP #OBJID_RODPLATE
    BEQ @dispatch
    CMP #OBJID_LUTEPLATE
    BEQ @dispatch
    LDA tmp+6
    CMP #<Talk_norm
    BNE @dispatch
    LDA tmp+7
    CMP #>Talk_norm
    BNE @dispatch
    LDA #<Talk_CoOGuy
    STA tmp+6
    LDA #>Talk_CoOGuy
    STA tmp+7
  @dispatch:
    CLC
    RTL
  @ours:
    PLA                         ; the map object, kept where talk_npc wants it
    PHA
    STA tmp+5
    JSR talk_npc
    PLX
    SEC
    RTL


;  One reward NPC.  In: X = its entry, tmp+5 = its map object.  Out: A = the
;  dialogue id.  tmp+4 holds the entry and tmp+6 its flags throughout; neither
;  is anything to the funnel once the NPC is handled here.
talk_npc:
    STX tmp+4
    LDA f:RANDOFAR + lut_TalkFlags, X
    STA tmp+6
    LDA f:RANDOFAR + lut_TalkObj, X
    TAY
    LDA tmp+6
    AND #TALKF_FIGHT
    BEQ @given
    LDA game_flags, Y           ; Bikke, the first time: mark him fought, fight
    AND #GMFLG_EVENT
    BNE @given
    LDA game_flags, Y
    ORA #GMFLG_EVENT
    STA game_flags, Y
    LDA f:RANDOFAR + lut_TalkBattle, X
    JSR talk_battle
    LDA tmp+1
    RTS

  @given:
    JSR talk_bit                ; Y = its byte, A = its bit
    AND RANDO_GIVEN, Y
    BNE @said

    ;  An Early flag waives what the King, Sarda or the Canoe Sage waits for:
    ;  straight to the held test, and past the item it would want.
    LDA f:RANDOFAR + lut_TalkEarly, X
    AND RANDO_EARLY
    BEQ @waits
    LDA tmp+6
    ORA #TALKF_WAIVED
    STA tmp+6
    BNE @held                   ; always

    ;  What it waits for, the events first.
  @waits:
    LDA f:RANDOFAR + lut_TalkArg, X
    TAY
    LDA f:RANDOFAR + lut_TalkReq, X
    CMP #TREQ_VISIBLE
    BEQ @visible
    CMP #TREQ_HIDDEN
    BEQ @hidden
    CMP #TREQ_EVENT
    BNE @held
    LDA game_flags, Y
    AND #GMFLG_EVENT
    BNE @held
    BEQ @notyet
  @visible:
    LDA game_flags, Y
    LSR A
    BCS @held
    BCC @notyet
  @hidden:
    LDA game_flags, Y
    LSR A
    BCS @notyet

  @held:
    LDA tmp+6
    AND #TALKF_HELD
    BEQ @items
    LDA f:RANDO_PLACEDFAR       ; placed: what the party holds came from
    CMP #1                      ;   anywhere, and proves nothing
    BEQ @items
    JSR talk_reward
    JSR talk_holds
    BNE @said

  @items:
    BIT tmp+6
    BMI @give                   ; TALKF_WAIVED
    LDA f:RANDOFAR + lut_TalkReq, X
    CMP #TREQ_HAVE
    BCC @give
    LDA f:RANDOFAR + lut_TalkArg, X
    TAY
    LDA items, Y
    BNE @give
  @notyet:
    LDA f:RANDOFAR + lut_TalkNotYet, X
    JMP talk_line

  @said:
    LDA f:RANDOFAR + lut_TalkGiven, X
    JMP talk_line

  @give:
    JSR talk_reward
    JSR talk_give
    LDX tmp+4
    BCC @gave
    LDA tmp+6                   ; it does not fit: nothing taken, nothing given
    AND #TALKF_GREEDY
    BEQ :+
    LDA #DLGID_DONTBEGREEDY
    RTS
:   LDA #DLGID_CANTCARRY
    RTS

  @gave:
    LDA f:RANDO_PLACEDFAR       ; placed: the giving line is replaced, naming
    CMP #1                      ;   what was given (rando_dlgtext)
    BNE :+
    TXA
    INC A
    STA f:RW_DLGNPC
:   LDA f:RANDOFAR + lut_TalkReq, X
    CMP #TREQ_TRADE
    BNE :+
    LDA f:RANDOFAR + lut_TalkArg, X
    TAY
    LDA items, Y                ; the exchange: what it wanted is taken
    SEC
    SBC #1
    STA items, Y
:   JSR talk_bit
    ORA RANDO_GIVEN, Y
    STA RANDO_GIVEN, Y

    LDA tmp+6
    AND #TALKF_HIDE
    BEQ :+
    LDA f:RANDOFAR + lut_TalkObj, X
    TAY                         ; HideThisMapObject's work
    LDA game_flags, Y
    AND #<~GMFLG_OBJVISIBLE
    STA game_flags, Y
    LDX tmp+5
    LDA #0
    STA mapobj_id, X
    LDX tmp+4
:   LDA tmp+6
    AND #TALKF_BATTLE
    BEQ :+
    LDA f:RANDOFAR + lut_TalkBattle, X
    JSR talk_battle
:   LDA tmp+6
    AND #TALKF_FIGHT
    BEQ :+
    LDY #OBJID_PIRATETERR_1     ; ShowMapObject writes tmp, not tmp+1..3
    CALL0E ShowMapObject
    LDY #OBJID_PIRATETERR_2
    CALL0E ShowMapObject
    LDY #OBJID_PIRATETERR_3
    CALL0E ShowMapObject
    LDX tmp+4
:   INC dlgsfx                  ; the fanfare
    LDA f:RANDOFAR + lut_TalkGiving, X
    ;  fall through

;  A = which of the talk data's lines (1-3); out A = that line's dialogue id.
talk_line:
    TAY
    LDA tmp, Y
    RTS

;  TalkBattle's work: the battle in A, fought once the dialogue box closes.
talk_battle:
    STA btlformation
    LDA #TP_BATTLEMARKER
    STA tileprop
    RTS

;  Entry X's bit in RANDO_GIVEN: Y = its byte, A = the bit.  X kept.
talk_bit:
    TXA
    LSR A
    LSR A
    LSR A
    TAY
    TXA
    PHX
    AND #$07
    TAX
    LDA f:RANDOFAR + lut_Bit8, X
    PLX
    RTS

;  Does the party hold reward A?  Out: Z clear if so.  Y clobbered.
talk_holds:
    CMP #REWARD_SHIP
    BEQ @ship
    CMP #REWARD_BRIDGE
    BEQ @bridge
    CMP #REWARD_CANOE
    BEQ @canoe
    CMP #REWARD_CANAL
    BEQ @canal
    CMP #TCITYPE_WEPSTART
    BCS @no                     ; gear: two Xcalbers would be no harm
    TAY
    LDA items, Y
    RTS
  @ship:
    LDA ship_vis
    RTS
  @bridge:
    LDA bridge_vis
    RTS
  @canoe:
    LDA has_canoe
    RTS
  @canal:
    LDA canal_vis               ; held once it is gone
    EOR #$01
    RTS
  @no:
    LDA #0
    RTS

;  Give reward A.  Out: C set if it does not fit, and then nothing is given.
;  X and Y clobbered.  The chest's own rules (OpenTreasureChest): an item
;  stops at 99, gear wants an empty slot.  No reward is gold yet.
talk_give:
    STA dlg_itemid              ; what the line names, if it is replaced
    CMP #REWARD_SHIP
    BCS @vehicle
    CMP #TCITYPE_WEPSTART
    BCS @gear
    TAY
    LDA items, Y
    CMP #99
    BCS @full
    ADC #1                      ; C is clear
    STA items, Y
    RTS
  @gear:
    CMP #TCITYPE_ARMSTART
    BCS @armor
    SBC #TCITYPE_WEPSTART - 2   ; C is clear: less $1B, the 1-based id a slot holds
    PHA
    JSR FindEmptyWeaponSlot
    BCS @nofit
  @put:
    PLA
    STA ch_stats, X
    CLC
    RTS
  @armor:
    CMP #TCITYPE_GPSTART
    BCS @gold
    SEC
    SBC #TCITYPE_ARMSTART - 1   ; the 1-based id a slot holds
    PHA
    JSR FindEmptyArmorSlot
    BCC @put
  @nofit:
    PLA
  @full:
    SEC
    RTS
  @vehicle:
    JSR give_vehicle
    STA dlg_itemid              ; a vehicle by the id that names it
    CLC
    RTS
  @gold:
    JSR give_gold
    CLC
    RTS


;;  Entry X's reward: placement's (the cache's) once it is in, the table's
;;  when it is not.  X kept.
talk_reward:
    LDA f:RANDO_PLACEDFAR
    CMP #1
    BNE :+
    LDA f:RW_TALKREW, X
    RTS
:   LDA f:RANDOFAR + lut_TalkReward, X
    RTS

;;  Vehicle A (REWARD_SHIP..REWARD_CANOE), given -- by an NPC or, once key
;;  items are placed, a chest.  A ship found under placement is moored at the
;;  dock nearest the map it was found on, of those the party can reach from
;;  there without it (lut_ShipDock, genlogic.py's ship_docks, which proves each
;;  is reached and on the inner sea the logic has it sail).  Out: A = the id
;;  the dialogue names it by -- CANOE's own, $11, and the orbs' $12-$14, whose
;;  names are empty and never drawn, for the others (rando_nameptr).  X kept.
;;  Emulation mode, the game's data bank.
.import lut_DockX, lut_DockY, lut_ShipDock
give_vehicle:
    CMP #REWARD_BRIDGE
    BCC @ship
    BEQ @bridge
    CMP #REWARD_CANAL
    BEQ @canal
    INC has_canoe               ; REWARD_CANOE
    LDA #NAME_CANOE
    RTS
  @bridge:
    INC bridge_vis
    LDA #NAME_BRIDGE
    RTS
  @canal:
    LDA #0                      ; Nerrick's work: the canal is the land he blasts
    STA canal_vis
    LDA #NAME_CANAL
    RTS
  @ship:
    INC ship_vis
    LDA f:RANDO_PLACEDFAR
    CMP #1
    BNE :+
    PHX
    LDA f:RANDO_SAVEFAR + (RANDO_ENTRANCES - RANDO_SAVE)
    BEQ @bymap
    ;  Under entrance shuffle the dock New Game chose for the wiring
    ;  (es_dock): no map is where it was.
    LDA f:RANDO_SAVEFAR + (RANDO_SHIPDOCK - RANDO_SAVE)
    BRA @dock
  @bymap:
    LDX cur_map                 ; where it was found: a chest or an NPC
    LDA f:LOGICFAR + lut_ShipDock, X
  @dock:
    TAX
    LDA f:LOGICFAR + lut_DockX, X
    STA ship_x
    LDA f:LOGICFAR + lut_DockY, X
    STA ship_y
    PLX
:   LDA #NAME_SHIP
    RTS

;;  Gold A ($6C-$AF), given as a chest gives it: its price added with the
;;  game's AddGPToParty, which takes the amount in tmp..tmp+2 -- the talk
;;  data, kept round it.  X clobbered.
give_gold:
    ASL A
    TAX
    LDA tmp
    PHA
    LDA tmp+1
    PHA
    LDA tmp+2
    PHA
    BCS @hi
    LDA f:BANK0DFAR + lut_ItemPrices, X
    STA tmp
    LDA f:BANK0DFAR + lut_ItemPrices + 1, X
    BRA @have
  @hi:
    LDA f:BANK0DFAR + lut_ItemPrices + $100, X
    STA tmp
    LDA f:BANK0DFAR + lut_ItemPrices + $101, X
  @have:
    STA tmp+1
    LDA #0
    STA tmp+2
    JSR AddGPToParty
    PLA
    STA tmp+2
    PLA
    STA tmp+1
    PLA
    STA tmp
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_price -- LoadPrice
;;
;;  The game read an item's price out of bank $0D's lut_ItemPrices; this
;;  reads it the same way, except that every key item costs what the BOTTLE
;;  does.  That is FFR's ScalePrices, and it is what keeps whatever placement
;;  stocks the caravan with from being free: the table has them all at 0.
;;  Vanilla never sells a key item but the BOTTLE, at its own price.
;;
;;  In: A = the item.  Out: tmp, tmp+1 = the price, tmp+2 = 0, tmp+3 and Y as
;;  the game's left them; X kept.  Emulation mode.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_price:
    .a8
    .i8
    PHX
    PHA
    ASL A                       ; the game's pointer's high byte, kept in tmp+3
    LDA #>(lut_ItemPrices >> 1)
    ROL A
    STA tmp+3
    PLA
    CMP #$01
    BCC :+
    CMP #item_qty_start - items
    BCS :+
    LDA #item_bottle - items    ; a key item: the BOTTLE's price
:   ASL A
    TAX
    BCS @hi
    LDA f:BANK0DFAR + lut_ItemPrices, X
    STA tmp
    LDA f:BANK0DFAR + lut_ItemPrices + 1, X
    BRA @have
  @hi:
    LDA f:BANK0DFAR + lut_ItemPrices + $100, X
    STA tmp
    LDA f:BANK0DFAR + lut_ItemPrices + $101, X
  @have:
    STA tmp+1
    LDA #0
    STA tmp+2
    LDY #1
    PLX
    RTL

;  The table, one column per field, entries in RANDO_GIVEN's order.
lut_TalkObj:
  .BYTE $01, OBJID_PRINCESS_2, OBJID_BIKKE, OBJID_ELFPRINCE, OBJID_ASTOS
  .BYTE OBJID_MATOYA, OBJID_NERRICK, OBJID_SMITH, OBJID_SARDA, $15
  .BYTE $11, OBJID_FAIRY, $BB
  ;     King, Princess, Bikke, Elf Prince, Astos, Matoya, Nerrick, Smith,
  ;     Sarda, Canoe Sage, CubeBot, Fairy, Lefein's Chime
lut_TalkReq:
  .BYTE TREQ_VISIBLE, TREQ_NONE, TREQ_NONE, TREQ_EVENT, TREQ_HAVE
  .BYTE TREQ_TRADE, TREQ_TRADE, TREQ_TRADE, TREQ_HIDDEN, TREQ_HAVE
  .BYTE TREQ_NONE, TREQ_NONE, TREQ_EVENT
lut_TalkArg:
  .BYTE OBJID_PRINCESS_2, 0, 0, OBJID_ELFPRINCE, item_crown - items
  .BYTE item_crystal - items, item_tnt - items, item_adamant - items, OBJID_VAMPIRE, orb_earth - items
  .BYTE 0, 0, OBJID_UNNE
lut_TalkReward:
  .BYTE REWARD_BRIDGE, item_lute - items, REWARD_SHIP, item_mystickey - items, item_crystal - items
  .BYTE item_herb - items, REWARD_CANAL, REWARD_XCALBER, item_rod - items, REWARD_CANOE
  .BYTE item_cube - items, item_oxyale - items, item_chime - items
lut_TalkFlags:
  .BYTE TALKF_HELD, TALKF_HELD, TALKF_FIGHT | TALKF_HELD, TALKF_HELD, TALKF_HIDE | TALKF_BATTLE
  .BYTE TALKF_HELD, TALKF_HIDE, TALKF_GREEDY, TALKF_HELD, TALKF_HELD
  .BYTE TALKF_HELD, TALKF_HELD, TALKF_HELD
lut_TalkBattle:
  .BYTE 0, 0, BTL_BIKKE, 0, BTL_ASTOS
  .BYTE 0, 0, 0, 0, 0
  .BYTE 0, 0, 0
;  The RANDO_EARLY bit that waives what it waits for: FFR's Early King, Sarda
;  and Sage.  (Early Ordeals is a tile change, in build.)
lut_TalkEarly:
  .BYTE EARLY_KING, 0, 0, 0, 0
  .BYTE 0, 0, 0, EARLY_SARDA, EARLY_SAGE
  .BYTE 0, 0, 0
;  Which line each says: waiting, giving, and once given (or holding it).
;  The line for a state the NPC cannot be in is the given one.
lut_TalkNotYet:
  .BYTE 1, 2, 1, 3, 1
  .BYTE 1, 1, 1, 2, 2
  .BYTE 2, 2, 3
lut_TalkGiving:
  .BYTE 2, 1, 2, 1, 2
  .BYTE 2, 2, 2, 1, 1
  .BYTE 1, 1, 1
lut_TalkGiven:
  .BYTE 3, 2, 3, 2, 2
  .BYTE 3, 2, 3, 2, 2
  .BYTE 2, 2, 2
.assert * - lut_TalkGiven = TALK_COUNT, error, "lut_TalkGiven is not TALK_COUNT long"
.assert lut_TalkGiven - lut_TalkGiving = TALK_COUNT, error, "lut_TalkGiving is not TALK_COUNT long"
.assert lut_TalkGiving - lut_TalkNotYet = TALK_COUNT, error, "lut_TalkNotYet is not TALK_COUNT long"
.assert lut_TalkNotYet - lut_TalkEarly = TALK_COUNT, error, "lut_TalkEarly is not TALK_COUNT long"
.assert lut_TalkEarly - lut_TalkBattle = TALK_COUNT, error, "lut_TalkBattle is not TALK_COUNT long"
.assert lut_TalkBattle - lut_TalkFlags = TALK_COUNT, error, "lut_TalkFlags is not TALK_COUNT long"
.assert lut_TalkFlags - lut_TalkReward = TALK_COUNT, error, "lut_TalkReward is not TALK_COUNT long"
.assert lut_TalkReward - lut_TalkArg = TALK_COUNT, error, "lut_TalkArg is not TALK_COUNT long"
.assert lut_TalkArg - lut_TalkReq = TALK_COUNT, error, "lut_TalkReq is not TALK_COUNT long"
.assert lut_TalkReq - lut_TalkObj = TALK_COUNT, error, "lut_TalkObj is not TALK_COUNT long"
lut_Bit8:
  .BYTE $01, $02, $04, $08, $10, $20, $40, $80

;  The vehicles' names, for NAME_SHIP, NAME_BRIDGE and NAME_CANAL, eight bytes
;  each: the letters, the terminator, padding.
lut_VehicleNames:
  .BYTE $9C, $91, $92, $99, $00, $00, $00, $00   ; SHIP
  .BYTE $8B, $9B, $92, $8D, $90, $8E, $00, $00   ; BRIDGE
  .BYTE $8C, $8A, $97, $8A, $95, $00, $00, $00   ; CANAL

;;  The RUSE Staff's name (OPTFM_RUSESTAFF) and the NUKE Stick's
;;  (OPTFM_NUKESTICK): the spell's, padded to six, and the staff's own icon,
;;  as FFR writes it.
lut_StaffNames:
  .BYTE $9B, $9E, $9C, $8E, $FF, $FF, $D8, $00   ; RUSE, the staff
  .BYTE $97, $9E, $94, $8E, $FF, $FF, $D8, $00   ; NUKE, the staff


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
    LDA a:wQ                    ; the caravan, when placement stocks it, is
    CMP #SHOP_CARAVAN           ;   not dealt: deal_rewards gives its row
    BNE :+
    LDA f:RANDO_PLACEDFAR
    CMP #1
    BEQ @gnext
:   LDY a:wNSHOPS
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
    LDA f:RANDO_PLACEDFAR       ; placement stocks it: open, or its one item
    CMP #1                      ;   could be shut away with the fairy out
    BEQ @open
    LDA f:RANDO_SAVEFAR + (RANDO_SHOPS - RANDO_SAVE)
    BEQ @game                   ; SHOPS_OFF
    CMP #SHOPS_MODES
    BCS @game                   ; a mode this build does not know: as off
  @open:
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
    JSR mark_unused

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
    CMP #REWARD_SHIP
    BCS @vehicle
    JMP leave                   ; C clear: OpenTreasureChest goes on

    ;  A vehicle, which only placement puts in a chest and no chest code
    ;  gives: given here, in the game's mode and data bank, and the chest
    ;  opened as the game opens one, with a key item's fanfare.  C set: the
    ;  chest is done, and A is the dialogue.
  @vehicle:
    SEP #$30
    SEC
    XCE
    PLB
    JSR give_vehicle
    STA dlg_itemid
    LDA game_flags, X
    ORA #GMFLG_TCOPEN
    STA game_flags, X
    LDA #1
    STA dlgsfx
    LDA #DLGID_TCGET
    SEC
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The magic levels
;;
;;  FFR's ShuffleMagicLevels permutes the spell tables in ROM and then mends
;;  everything that names a spell by its old index: enemy AI, the equipment
;;  cast byte, the out-of-battle table, the confused enemy's FIRE.  Nothing
;;  here moves.  The cache holds which spell each slot now holds, RW_PERM,
;;  and its inverse, and the slot is turned into its spell at the few places
;;  a character's slot becomes one: the conversion to the in-battle spell list
;;  and back, the out-of-battle dispatch, the magic menu's names, the magic
;;  shops' names, and the spell descriptions.  Everything downstream sees the
;;  spell itself, as the game always did -- records, battle messages, enemy
;;  casts, equipment, and every option that asks which spell it is.
;;
;;  What stays with the slot, as in FFR: the MP pool a cast spends (its
;;  level), the price and the shop, and who may learn it -- FFR's presets all
;;  leave MagicPermissions off, so a class learns slots, whatever lands in them.
;;
;;  Slots and spells are both 0..63, level * 8 + position.  Positions 0-3 of
;;  a level are white and 4-7 black, and white stays white.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  Every slot holds its own spell.  A8, I16, DBR = $7F.
copy_magic:
    .a8
    .i16
    LDX #$0000
  @copy:
    TXA
    STA a:wPERM, X
    INX
    CPX #64
    BCC @copy
    RTS

;;  FFR un-interleaves the white and black spells, shuffles each list, and
;;  interleaves them again.  The same thing in place: Fisher-Yates over the
;;  32 white slots in order, then the 32 black ones.  A8, I16, DBR = $7F.
deal_magic:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_MAGIC)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_MAGIC)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDA #$00                    ; white: positions 0-3
    JSR deal_book
    LDA #$04                    ; black: positions 4-7
    ;  fall through

;;  Fisher-Yates over one book's 32 slots.  In: A = 0 for white, 4 for black.
deal_book:
    .a8
    .i16
    STA a:wK
    LDA #31
    STA a:wI
  @fy:
    LDA a:wI
    BEQ @done
    INC A
    JSR rando_below             ; j, below i+1
    JSR book_slot
    STA a:wT2                   ; ...as a slot
    LDA a:wI
    JSR book_slot
    STA a:wQ                    ; i, as a slot
    LDX a:wQ
    LDY a:wT2
    LDA a:wPERM, X
    PHA
    LDA a:wPERM, Y
    STA a:wPERM, X
    PLA
    STA a:wPERM, Y
    DEC a:wI
    BRA @fy
  @done:
    RTS

;;  The book's k-th slot, 0..31: four to a level, at position wK on.
book_slot:
    .a8
    PHA
    AND #$1C                    ; the level, times four...
    ASL A                       ; ...times eight
    STA a:wP
    PLA
    AND #$03
    ORA a:wP
    ORA a:wK                    ; bit 2 is free for the book's offset
    RTS

;;  RW_INV[RW_PERM[s]] = s.  A8, I16, DBR = $7F.
make_inverse:
    .a8
    .i16
    LDY #$0000
  @inv:
    LDA a:wPERM, Y
    STA a:wT2
    LDX a:wT2
    TYA
    STA a:wINV, X
    INY
    CPY #64
    BCC @inv
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_spell -- the spell in slot A.  rando_slot -- the slot spell A is in.
;;
;;  In: A = 0..63.  Out: A = 0..63; X and Y kept.  The cache is ensured, so
;;  either may be the first thing a loaded game asks.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_spell:
    .a8
    .i8
    PHB
    PHX
    PHY
    PHA
    JSR enter
    JSR ensure
    PLA
    AND #$3F
    TAX
    LDA a:wPERM, X
    PLY
    PLX
    JMP leave

rando_slot:
    .a8
    .i8
    PHB
    PHX
    PHY
    PHA
    JSR enter
    JSR ensure
    PLA
    AND #$3F
    TAX
    LDA a:wINV, X
    PLY
    PLX
    JMP leave


;;  ConvertOBStatsToIB, per spell: the game turned a level's 1-based position
;;  into a 1-based slot by adding the level's base.  This goes on to the spell
;;  in that slot, so the battle -- its magic box, the selection, the attack id
;;  -- deals in spells, as it always did.
;;
;;  In: A = the position, 1..8; Y = the index; btl_tmpindex = the level * 8,
;;  which lives in battle RAM at $68B3.
;;  Writes (btlptr),Y.  X and Y kept.
rando_ibspell:
    .a8
    .i8
    CLC
    ADC a:btl_tmpindex          ; the 1-based slot, as the game had it; the
                                ;   caller's data bank, which reaches $68B3
    DEC A
    JSL rando_spell + RANDOFAR
    INC A                       ; 1-based again
    STA (btlptr), Y             ; the caller's data bank: SRAM
    RTL

;;  ConvertIBStatsToOB, per spell: back from the spell to its slot's position
;;  in the level.  In: A = the spell, 1-based.  Out: A = the position, 1..8.
rando_obspell:
    .a8
    .i8
    DEC A
    JSL rando_slot + RANDOFAR
    AND #$07
    INC A
    RTL

;;  The out-of-battle dispatch.  The game built the spell id with ORA where it
;;  needed ADC, which made the 8th spell of a level the 1st of the next; no
;;  castable spell was ever 8th, until EXIT and WARP can land anywhere in the
;;  black book.  The position is made 0-based first here, so the OR is sound.
;;  An empty slot, which the game made into the level before's 8th spell,
;;  comes back 0: no spell, so "can't cast that here".
;;
;;  In: X = the index into ch_spells, A the same.  Out: A = MG_START + the
;;  spell, or 0.  X kept.
rando_oobspell:
    .a8
    .i8
    LDA ch_spells, X            ; the caller's data bank: SRAM
    BEQ @empty
    DEC A
    STA f:RW_T
    TXA
    ASL A
    AND #$38                    ; the level's first slot
    ORA f:RW_T
    JSL rando_spell + RANDOFAR
    CLC
    ADC #MG_START
    RTL
  @empty:
    LDA #$00
    RTL

;;  The magic menu's list.  In: A = the position, 1..8; tmp = $AF + the
;;  level * 8, which the game added to make the item id.  Out: A = the item id
;;  of the spell in that slot.  X kept.
rando_menuspell:
    .a8
    .i8
    CLC
    ADC z:tmp
    SEC
    SBC #MG_START
    JSL rando_spell + RANDOFAR
    CLC
    ADC #MG_START
    RTL

;;  A magic shop's list.  ShopSelectBuyMagic writes each entry's item id
;;  twice: at $11 for its name and at $16 for its price.  A magic shop sells
;;  slots -- the price, the purchase and the learning all go by the slot -- so
;;  $16 keeps the slot's id and $11 gets its spell's.
;;
;;  In: A = the entry's item id, Y = its string index.  X and Y kept.
rando_shopmagic:
    .a8
    .i8
    STA a:str_buf + $16, Y      ; the caller's data bank: low WRAM
    JSL rando_shopspell + RANDOFAR
    STA a:str_buf + $11, Y
    RTL

;;  An item id, with a slot's turned into its spell's.  In: A = an item id.
;;  Out: A = the item id whose name to draw.  X kept.
rando_shopspell:
    .a8
    .i8
    CMP #MG_START
    BCC @out
    CMP #MG_START + 64
    BCS @out
    SEC
    SBC #MG_START
    JSL rando_spell + RANDOFAR
    CLC
    ADC #MG_START
  @out:
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Blursings -- FFR's RandomWeaponBonus and RandomArmorBonus
;;
;;  Every weapon and every piece of armour rolls a bonus from -curse to
;;  +blessing, one stream, weapons first.  A nonzero bonus changes the record
;;  as FFR does:
;;
;;    weapon   hit + 3b (0..50), damage + 2b (at least 1), crit + 3b (at least 1)
;;    armour   absorb + kb (at least 1), evade penalty - kb (at least 0), where k is
;;             2 for body armour, the first 16, and 1 for the rest
;;
;;  and the name's last two letters before its icon become the sign and the
;;  digit.  Prices stay as they are, as in FFR.  FFR casts each result to a
;;  byte; nothing here gets near 255, so the ceiling is written as a clamp.
;;
;;  Where it is read: the out-of-battle stat adjusters through rando_weaprec
;;  and rando_armrec, which is where a character's damage, hit, evade and
;;  absorb come from, battle included; the options chunk's opt_weapbyte and
;;  opt_armbyte, for crit and the descriptions; and the names, through
;;  rando_nameptr and rando_battlesubsrc.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  Both tables as the cartridge has them, and no bonuses.  A8, I16, DBR $7F.
copy_gear:
    .a8
    .i16
    LDX #$0000
  @copy:
    LDA f:ROMGEAR, X
    STA a:wWEAPONS, X
    INX
    CPX #40 * 8 + 40 * 4
    BCC @copy
    LDX #$0000
  @zero:
    STZ a:wBONUS, X
    INX
    CPX #80
    BCC @zero
    RTS

;;  A8, I16, DBR $7F.
deal_gear:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_GEAR)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_GEAR)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDA f:RANDO_SAVEFAR + (RANDO_BLESS - RANDO_SAVE)
    CLC
    ADC f:RANDO_SAVEFAR + (RANDO_CURSE - RANDO_SAVE)
    INC A
    STA a:wGN                   ; how many values: -curse..+bless
    STZ a:wGI
  @each:
    LDA a:wGN
    JSR rando_below
    SEC
    SBC f:RANDO_SAVEFAR + (RANDO_CURSE - RANDO_SAVE)
    PHA                         ; the bonus
    LDA a:wGI
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    PLA
    STA a:wBONUS, X
    BEQ @next
    JSR blurse_one
  @next:
    INC a:wGI
    LDA a:wGI
    CMP #80
    BCC @each
    RTS

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Item magic -- FFR's ShuffleItemMagic, its All and Balanced pools
;;
;;  Every item that casts a spell on the cartridge -- weapons first, then
;;  armour, as FFR concatenates them -- casts another, dealt from the pool:
;;  Fisher-Yates over it as far as the items go, so no two share a spell, as
;;  FFR's shuffle-and-zip has it.  The spell goes into the gear cache's
;;  record, byte 3, which every reader asks: the descriptions and the
;;  starting caster item through opt_weapbyte and opt_armbyte, battle's Use
;;  through opt_itemspell, the names through rando_nameptr.  The pools are
;;  worked out at build time (genitemmagic.py) from the cartridge's records.
;;
;;  The RUSE Staff and the NUKE Stick are options, not settings of the world,
;;  so the deal never sees them: opt_weapbyte puts them over it as it reads,
;;  and the Wizard Staff's dealt spell waits under the NUKE Stick.  Turning
;;  either on mid-game moves nothing else.
;;
;;  In: A = the field, still shifted.  A8, I16, DBR $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.include "itemmagic.inc"
.export lut_IMAll, lut_IMBal, IM_ALL_N, IM_BAL_N   ; for tools/test_options.py

deal_itemmagic:
    .a8
    .i16
    PHA
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_ITEMMAGIC)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_ITEMMAGIC)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    PLA
    LDX #$0000
    CMP #ITEMMAGIC_BALANCED << ITEMMAGIC_SHIFT
    BEQ @bal
  @all:
    LDA f:RANDOFAR + lut_IMAll, X
    STA a:wLIST, X
    INX
    CPX #IM_ALL_N
    BCC @all
    BRA @dealt
  @bal:
    LDA f:RANDOFAR + lut_IMBal, X
    STA a:wLIST, X
    INX
    CPX #IM_BAL_N
    BCC @bal
  @dealt:
    TXA
    STA a:wLEN                  ; the pool's size
    STZ a:wK                    ; the next of it to deal
    STZ a:wGI
  @each:
    LDA a:wGI
    JSR gear_spellat
    LDA f:ROMGEAR, X
    BEQ @next                   ; casts nothing on the cartridge
    LDA a:wK
    CMP a:wLEN
    BCS @out                    ; the pool spent, as FFR's Zip stops
    PHX
    LDA a:wLEN
    SEC
    SBC a:wK
    JSR rando_below             ; j - k, below what is left
    CLC
    ADC a:wK
    REP #$20
    .a16
    AND #$00FF
    TAX                         ; j
    LDA a:wK
    AND #$00FF
    TAY                         ; k
    SEP #$20
    .a8
    LDA a:wLIST, X              ; swap them
    PHA
    LDA a:wLIST, Y
    STA a:wLIST, X
    PLA
    STA a:wLIST, Y
    INC A                       ; 1-based, as a record holds it
    PLX
    STA a:wWEAPONS, X
    INC a:wK
  @next:
    INC a:wGI
    LDA a:wGI
    CMP #80
    BCC @each
  @out:
    RTS

;;  In: A8 = gear 0..79, weapons then armour.  Out: X16 = where its spell
;;  byte is in the tables, ROMGEAR's or the cache's.  A8, I16.
gear_spellat:
    .a8
    .i16
    REP #$20
    .a16
    AND #$00FF
    CMP #40
    BCS @armour
    ASL A
    ASL A
    ASL A                       ; eight bytes a weapon
    BRA @byte
  @armour:
    ASL A
    ASL A                       ; four an armour, after the 320: 4g + 160
    CLC
    ADC #40 * 8 - 40 * 4
  @byte:
    CLC
    ADC #WEAPON_SPELL
    TAX
    SEP #$20
    .a8
    RTS
.assert WEAPON_SPELL = ARMOR_SPELL, error, "gear_spellat: one byte for both"


;;  Apply bonus A (nonzero) to piece X, 0..79.  A8, I16, DBR $7F.
blurse_one:
    .a8
    .i16
    REP #$20
    .a16
    AND #$00FF
    CMP #$0080
    BCC :+
    ORA #$FF00                  ; signed
:   STA a:wT                    ; b
    ASL A
    STA a:wD2                   ; 2b
    CLC
    ADC a:wT
    STA a:wD3                   ; 3b
    TXA
    CMP #40
    BCS @armor

    ASL A
    ASL A
    ASL A
    TAX                         ; the weapon's record
    LDA #50
    STA a:wCEIL
    LDY #$0000
    LDA a:wWEAPONS + 0, X       ; hit + 3b, 0..50
    AND #$00FF
    CLC
    ADC a:wD3
    JSR clamp
    SEP #$20
    .a8
    STA a:wWEAPONS + 0, X
    REP #$20
    .a16
    LDA #$00FF
    STA a:wCEIL
    LDY #$0001
    LDA a:wWEAPONS + 1, X       ; damage + 2b, at least 1
    AND #$00FF
    CLC
    ADC a:wD2
    JSR clamp
    SEP #$20
    .a8
    STA a:wWEAPONS + 1, X
    REP #$20
    .a16
    LDA a:wWEAPONS + 2, X       ; crit + 3b, at least 1
    AND #$00FF
    CLC
    ADC a:wD3
    JSR clamp
    SEP #$20
    .a8
    STA a:wWEAPONS + 2, X
    RTS

  @armor:
    .a16
    SEC
    SBC #40
    CMP #16                     ; body armour: twice the step
    BCS :+
    PHA
    LDA a:wD2
    STA a:wT
    PLA
:   ASL A
    ASL A
    TAX                         ; the armour's record
    LDA #$00FF
    STA a:wCEIL
    LDY #$0000
    LDA a:wARMOR + 0, X         ; evade penalty (FFR's weight) - kb, at least 0
    AND #$00FF
    SEC
    SBC a:wT
    JSR clamp
    SEP #$20
    .a8
    STA a:wARMOR + 0, X
    REP #$20
    .a16
    LDY #$0001
    LDA a:wARMOR + 1, X         ; absorb + kb, at least 1
    AND #$00FF
    CLC
    ADC a:wT
    JSR clamp
    SEP #$20
    .a8
    STA a:wARMOR + 1, X
    RTS

;;  A16 = a value, signed; Y16 = its floor; RW_CEIL = its ceiling.
;;  Out: A16 within them.  X kept.
clamp:
    .a16
    .i16
    STY a:wFLOOR
    CMP #$0000
    BMI @floor
    CMP a:wFLOOR
    BCC @floor
    CMP a:wCEIL
    BCC @ok
    BEQ @ok
    LDA a:wCEIL
  @ok:
    RTS
  @floor:
    LDA a:wFLOOR
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_weaprec, rando_armrec -- the stat adjusters' record pointer
;;
;;  UnadjustEquipStats and ReadjustEquipStats pointed (tmp) into lut_Weapons
;;  or lut_Armor in bank $0C and read the record through it.  These copy the
;;  record as blursed into OPTGEARSHADOW, in SRAM, which every bank sees, and
;;  point (tmp) there instead.
;;
;;  In: A = (equipment id - 1) * 4, as the adjuster had it.  Out: tmp,
;;  tmp+1.  A, X, Y clobbered; the adjuster reloads X and Y after.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

GEARSHADOWFAR = SRAMFAR + OPTGEARSHADOW
NAMEBUFFAR    = SRAMFAR + OPTNAMEBUF

rando_weaprec:
    .a8
    .i8
    PHB
    PHA
    JSR enter
    JSR ensure
    PLA
    REP #$30
    .a16
    .i16
    AND #$00FF
    ASL A                       ; eight bytes a weapon
    TAX
    LDA a:wWEAPONS + 0, X
    STA f:GEARSHADOWFAR + 0
    LDA a:wWEAPONS + 2, X
    STA f:GEARSHADOWFAR + 2
    LDA a:wWEAPONS + 4, X
    STA f:GEARSHADOWFAR + 4
    LDA a:wWEAPONS + 6, X
    STA f:GEARSHADOWFAR + 6
    BRA gearpoint

rando_armrec:
    .a8
    .i8
    PHB
    PHA
    JSR enter
    JSR ensure
    PLA
    REP #$30
    .a16
    .i16
    AND #$00FF                  ; four bytes an armour: already the offset
    TAX
    LDA a:wARMOR + 0, X
    STA f:GEARSHADOWFAR + 0
    LDA a:wARMOR + 2, X
    STA f:GEARSHADOWFAR + 2
gearpoint:
    .a16
    SEP #$20
    .a8
    LDA #<OPTGEARSHADOW
    STA z:tmp
    LDA #>OPTGEARSHADOW
    STA z:tmp+1
    JMP leave


;;  opt_weapbyte and opt_armbyte, for the options chunk: byte Y of weapon or
;;  armour X, as blursed.  Out: A; X and Y kept.
rando_weapbyte:
    .a8
    .i8
    PHB
    PHX
    PHY
    JSR enter
    JSR ensure
    PLY
    PLX
    PHX
    PHY
    REP #$30
    .a16
    .i16
    TXA
    AND #$00FF
    ASL A
    ASL A
    ASL A
    BRA gearbyte

rando_armbyte:
    .a8
    .i8
    PHB
    PHX
    PHY
    JSR enter
    JSR ensure
    PLY
    PLX
    PHX
    PHY
    REP #$30
    .a16
    .i16
    TXA
    AND #$00FF
    ASL A
    ASL A
    CLC
    ADC #wARMOR - wWEAPONS
gearbyte:
    .a16
    .i16
    STA a:wT
    TYA
    AND #$00FF
    CLC
    ADC a:wT
    TAX
    SEP #$20
    .a8
    LDA a:wWEAPONS, X
    SEP #$10
    .i8
    PLY
    PLX
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_nameptr -- where to draw item A's name from
;;
;;  The ROM's pointer, unless A is a piece of gear with a bonus: then its seven
;;  letters, with the last two before the icon made the sign and the digit,
;;  in OPTNAMEBUF.  Only gear consults -- or builds -- the cache.  FFR's rule for the icon: a seventh byte above 200 that is
;;  not a space.  The name readers draw from wherever this points with the
;;  items bank mapped, and SRAM is visible from it.
;;
;;  In: A = item id.  Out: A = the pointer's low byte, X its high.  Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_nameptr:
    .a8
    .i8
    PHB
    PHY
    PHA
    JSR enter
    ;  Only gear's names come from the cache, so only gear asks for it.  The
    ;  lookup is the game's one table of short names -- items, spells, class
    ;  names, status words -- and party creation draws class names through it
    ;  right after New Game has written a new seed: asking there built the
    ;  whole world on that screen, under its music.  Now the first build
    ;  after New Game is GameStart's @Begin, with the party confirmed.
    PLA
    PHA
    SEC
    SBC #TCITYPE_WEPSTART
    CMP #80
    BCS :+                      ; not gear: no cache wanted
    JSR ensure
:   PLA
    STA a:wNAMEID
    REP #$30
    .a16
    .i16
    AND #$00FF
    ASL A
    TAX
    LDA f:BANK0AFAR + lut_ItemNamePtrTbl, X
    STA a:wNAMEPTR
    SEP #$20
    .a8
    ;  A vehicle given (give_vehicle) is named by $12-$14, the orbs' ids,
    ;  whose own names are empty and never drawn: its name, into the buffer.
    LDA a:wNAMEID
    CMP #NAME_SHIP
    BCC @notvehicle
    CMP #NAME_CANAL + 1
    BCS @notvehicle
    SEC
    SBC #NAME_SHIP
    ASL A
    ASL A
    ASL A                       ; eight bytes a name
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDY #$0000
  @vname:
    LDA f:RANDOFAR + lut_VehicleNames, X
    PHX
    TYX
    STA f:NAMEBUFFAR, X
    PLX
    INX
    INY
    CPY #8
    BCC @vname
    LDA #<OPTNAMEBUF
    STA a:wNAMEPTR
    LDA #>OPTNAMEBUF
    STA a:wNAMEPTR + 1
    JMP @rom
  @notvehicle:
    LDA a:wNAMEID
    SEC
    SBC #TCITYPE_WEPSTART
    BCC @notgear
    CMP #80
    BCC @gear
  @notgear:
    JMP @rom
  @gear:
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:wBONUS, X
    STA a:wNAMEB
    ;  The RUSE Staff and the NUKE Stick: a staff named for its spell, as
    ;  FFR names it, into the buffer -- a bonus's digits go on it as on any
    ;  name.  X, the name's place in lut_StaffNames.
    LDA a:wNAMEID
    LDX #$0000
    CMP #ITEM_POWERSTAFF
    BNE :+
    LDA f:SRAMFAR + OPTFB_RUSESTAFF
    AND #OPTFM_RUSESTAFF
    BEQ @plain
    BRA @staff
:   CMP #ITEM_WIZARDSTAFF
    BNE @plain
    LDA f:SRAMFAR + OPTFB_NUKESTICK
    AND #OPTFM_NUKESTICK
    BEQ @plain
    LDX #$0008
  @staff:
    LDY #$0000
  @ruse:
    LDA f:RANDOFAR + lut_StaffNames, X
    PHX
    TYX
    STA f:NAMEBUFFAR, X
    PLX
    INX
    INY
    CPY #8
    BCC @ruse
    LDA a:wNAMEB
    BEQ :+
    JMP @digits
:   JMP @buffer
  @plain:
    ;  Item magic: a casting item named for the spell it was dealt, as FFR's
    ;  WriteItemSpellData names it -- the spell's four letters padded to
    ;  six, then the item's own icon; one without an icon is padded to
    ;  seven.  A bonus's digits go on it as on any name.
    LDA f:RANDO_SAVEFAR + (RANDO_MAGIC - RANDO_SAVE)
    AND #ITEMMAGIC_FIELD
    BEQ @named                  ; off
    CMP #ITEMMAGIC_MODES << ITEMMAGIC_SHIFT
    BCS @named                  ; as the build reads it: off
    LDA a:wNAMEID
    SEC
    SBC #TCITYPE_WEPSTART
    JSR gear_spellat
    LDA f:ROMGEAR, X
    BEQ @named                  ; casts nothing on the cartridge: not dealt
    LDA a:wWEAPONS, X           ; the dealt spell, 1-based
    DEC A
    REP #$20
    .a16
    AND #$003F
    ASL A
    ASL A
    TAX                         ; its four letters
    SEP #$20
    .a8
    LDY #$0000
  @letter:
    LDA f:OPTFAR + lut_SpellNames, X
    PHX
    TYX
    STA f:NAMEBUFFAR, X
    PLX
    INX
    INY
    CPY #4
    BCC @letter
    LDA #$FF
    STA f:NAMEBUFFAR + 4
    STA f:NAMEBUFFAR + 5
    LDX a:wNAMEPTR
    LDA f:BANK0AFAR + 6, X      ; the cartridge name's seventh byte
    CMP #201
    BCS @icon                   ; FFR's icon: above 200 (a space, $FF, is
    LDA #$FF                    ;   itself either way)
  @icon:
    STA f:NAMEBUFFAR + 6
    LDA #$00
    STA f:NAMEBUFFAR + 7
    LDA a:wNAMEB
    BEQ :+
    JMP @digits
:   JMP @buffer
  @named:
    LDA a:wNAMEB
    BNE :+
    JMP @rom
:
    LDX a:wNAMEPTR
    LDY #$0000
  @copy:
    LDA f:BANK0AFAR, X
    PHX
    TYX
    STA f:NAMEBUFFAR, X
    PLX
    INX
    INY
    CPY #7
    BCC @copy
    LDA #$00
    STA f:NAMEBUFFAR + 7        ; the terminator

  @digits:
    LDX #$0006                  ; the last letter, or the one before an icon
    LDA f:NAMEBUFFAR + 6
    CMP #$FF
    BEQ @place
    CMP #201
    BCC @place
    DEX
  @place:
    LDA a:wNAMEB
    BMI @minus
    CLC
    ADC #$80                    ; the digit
    STA f:NAMEBUFFAR, X
    LDA #CHR_PLUS
    BRA @sign
  @minus:
    EOR #$FF
    INC A
    CLC
    ADC #$80
    STA f:NAMEBUFFAR, X
    LDA #$C2                    ; "-"
  @sign:
    DEX
    STA f:NAMEBUFFAR, X
  @buffer:
    LDA #<OPTNAMEBUF
    STA a:wNAMEPTR
    LDA #>OPTNAMEBUF
    STA a:wNAMEPTR + 1

  @rom:
    .a8
    SEP #$30
    .i8
    LDA a:wNAMEPTR
    LDX a:wNAMEPTR + 1
    PLY
    JMP leave


;;  The tail of BattleDrawLoadSubSrcPtr, which every battle substring goes
;;  through: names, attacks, messages.  It read the pointer at ($96); this
;;  reads it the same way, then, if the table was the item names -- the items
;;  bank mapped and ($96) inside lut_ItemNamePtrTbl -- asks rando_nameptr.
;;  Battle messages and enemy names come from bank $0B, and the enemy attack
;;  names end below $B700.
;;
;;  Out: btldraw_subsrc.  Y = 1, as the game left it; X kept.
rando_battlesubsrc:
    .a8
    .i8
    LDY #$00
    LDA ($96), Y                ; the caller's data bank
    STA z:btldraw_subsrc
    INY
    LDA ($96), Y
    STA z:btldraw_subsrc+1
    PHB
    PLA
    CMP #CHUNK0 + BANK_ITEMS
    BNE @out
    LDA z:$97
    CMP #>lut_ItemNamePtrTbl
    BCC @out
    CMP #>lut_ItemNamePtrTbl + 2
    BCS @out
    SEC
    SBC #>lut_ItemNamePtrTbl    ; 0 or 1: bit 8 of the offset
    LSR A
    LDA z:$96
    ROR A                       ; the item id
    PHX
    JSL rando_nameptr + RANDOFAR
    STA z:btldraw_subsrc
    TXA
    STA z:btldraw_subsrc+1
    PLX
  @out:
    LDY #$01
    RTL


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


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_domains -- lut_Domains into the cache, as the cartridge has it
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_domains:
    .a8
    .i16
    REP #$20
    .a16
    LDX #$0000
  @copy:
    LDA f:ROMDOMAINS, X
    STA a:wDOMAINS, X
    INX
    INX
    CPX #DOMAINS_SIZE
    BCC @copy
    SEP #$20
    .a8
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_zones -- move formations between zones
;;
;;  Shuffle: lut_FormationWeight gives slots 0-3 12/64 each, 4-5 6/64, 6 3/64
;;  and 7 1/64, so those four classes are the rarities.  Each class is pooled
;;  across the zones the pass may touch, in zone order, shuffled and dealt
;;  back in the same order: a formation lands in another zone as often met as
;;  it was.  The zones left alone are FFR's -- the four around Coneria and
;;  every zone that is all zero (towns, and overworld squares that never
;;  fight) -- settled before anything moves.  FFR's Shuffle Across Zones has
;;  done this a different way in each of its versions; see snesmap.inc.
;;
;;  Light: the same, for slots 0, 3, 5 and 6 only, each pooled on its own --
;;  two common fights, an uncommon and a rare in every zone come from
;;  elsewhere, and the other four stay, so a zone is still recognisably
;;  itself.
;;
;;  In both, WarMECH stays where it is: a slot holding its formation is left
;;  out of the pool, so it neither moves nor takes anything in.
;;
;;  Random: FFR's Totally Random.  Every slot of every zone but the four
;;  around Coneria is drawn from the 232 formations that are not a boss's:
;;  $00-$72, $80-$F2, $FE and $FF.  The all-zero zones too, as FFR does; they
;;  never fight.
;;
;;  In: A8 = the mode, 1..ZONES_MODES-1; I16; DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_zones:
    .a8
    .i16
    STA a:wMODE
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_ZONES)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_ZONES)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8

    ;  Which zones the pass may touch: not the four around Coneria, and for
    ;  Shuffle not one that is all zero.
    LDX #$0000                  ; the zone's first slot, zone * 8
    LDY #$0000                  ; the zone
  @which:
    CPY #$001B
    BEQ @no
    CPY #$001C
    BEQ @no
    CPY #$0024
    BEQ @no
    CPY #$002C
    BEQ @no
    LDA a:wMODE
    CMP #ZONES_RANDOM
    BEQ @yes
    REP #$20
    .a16
    LDA a:wDOMAINS, X
    ORA a:wDOMAINS+2, X
    ORA a:wDOMAINS+4, X
    ORA a:wDOMAINS+6, X
    SEP #$20                    ; leaves Z as the sixteen-bit ORs set it
    .a8
    BEQ @no
  @yes:
    LDA #$01
    BRA @put
  @no:
    LDA #$00
  @put:
    STA a:wZONEOK, Y
    REP #$20
    .a16
    TXA
    CLC
    ADC #8
    TAX
    SEP #$20
    .a8
    INY
    CPY #128
    BCC @which

    LDA a:wMODE
    CMP #ZONES_RANDOM
    BEQ @random
    CMP #ZONES_LIGHT
    BEQ @light

    ;  The four rarity classes, each a first slot and a count.
    LDA #0
    LDY #4
    JSR deal_class
    LDA #4
    LDY #2
    JSR deal_class
    LDA #6
    LDY #1
    JSR deal_class
    LDA #7
    LDY #1
    JMP deal_class

    ;  Two common slots, one uncommon and one rare, each a class of its own.
  @light:
    LDA #0
    LDY #1
    JSR deal_class
    LDA #3
    LDY #1
    JSR deal_class
    LDA #5
    LDY #1
    JSR deal_class
    LDA #6
    LDY #1
    JMP deal_class

  @random:
    LDX #$0000                  ; the slot
    LDY #$0000                  ; the zone
  @zone:
    LDA a:wZONEOK, Y
    BNE @draw8
    REP #$20                    ; left alone: past its eight slots
    .a16
    TXA
    CLC
    ADC #8
    TAX
    SEP #$20
    .a8
    BRA @next
  @draw8:
    LDA #8
    STA a:wFC
  @slot:
    LDA #232
    JSR rando_below
    CMP #$73
    BCC @store                  ; $00-$72 as drawn
    CMP #$73 + $73
    BCS @top
    ADC #$80 - $73              ; C clear: $80-$F2
    BRA @store
  @top:
    ADC #$FE - ($73 + $73) - 1  ; C set: $FE, $FF
  @store:
    STA a:wDOMAINS, X
    INX
    DEC a:wFC
    BNE @slot
  @next:
    INY
    CPY #128
    BCC @zone
    RTS


;;  One rarity class across the zones: list its slots in every zone the pass
;;  may touch, but not one holding WarMECH, then Fisher-Yates over the list
;;  from the top, exchanging the formations the slots hold.  That is the same
;;  as pooling the formations, shuffling the pool and dealing it back in
;;  order, without the pool.
;;
;;  In: A8 = the class's first slot, Y = how many slots it has; A8, I16.
deal_class:
    .a8
    .i16
    STA a:wFS
    TYA
    STA a:wFC
    LDX #$0000                  ; two bytes per slot listed
    LDY #$0000                  ; the zone
  @zone:
    LDA a:wZONEOK, Y
    BEQ @next
    REP #$20
    .a16
    TYA
    ASL A
    ASL A
    ASL A
    STA a:wFD
    LDA a:wFS
    AND #$00FF
    CLC
    ADC a:wFD
    STA a:wFK                   ; the class's first slot in this zone
    SEP #$20
    .a8
    LDA a:wFC
    STA a:wT2                   ; a count down
  @slot:
    PHY
    LDY a:wFK                   ; I16: the whole word
    LDA a:wDOMAINS, Y
    PLY
    CMP #WARMECH_FORM
    BEQ @pinned
    REP #$20
    .a16
    LDA a:wFK
    STA a:wPOS, X
    SEP #$20
    .a8
    INX
    INX
  @pinned:
    REP #$20
    .a16
    INC a:wFK
    SEP #$20
    .a8
    DEC a:wT2
    BNE @slot
  @next:
    INY
    CPY #128
    BCC @zone

    REP #$20
    .a16
    TXA
    LSR A
    STA a:wFK                   ; i + 1, from the list's length down
  @shuffle:
    LDA a:wFK
    CMP #2
    BCC @done                   ; down to i = 0: nothing left to exchange
    JSR rando_below16           ; j, 0..i
    ASL A
    TAX
    LDA a:wFK
    DEC A
    ASL A
    TAY
    LDA a:wPOS, X               ; slot j...
    TAX
    LDA a:wPOS, Y               ; ...and slot i
    TAY
    SEP #$20
    .a8
    LDA a:wDOMAINS, X
    PHA
    LDA a:wDOMAINS, Y
    STA a:wDOMAINS, X
    PLA
    STA a:wDOMAINS, Y
    REP #$20
    .a16
    DEC a:wFK
    BRA @shuffle
  @done:
    SEP #$20
    .a8
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_rarity -- move formations between the slots of each zone
;;
;;  Every zone, the four around Coneria and the all-zero ones included, as
;;  FFR does:
;;
;;    Shuffle  FFR's Shuffle Rarity: shuffle slots 0-3, then slots 2-7.  The
;;             two commonest slots keep a formation that was common.
;;    Tiered   FFR's Shuffle Rarity Tiered: deal the eight slots in order, each
;;             drawn from those left with weights 48, 48, 48, 48, 24, 24, 8, 8
;;             by the slot it came from -- 6, 6, 6, 6, 3, 3, 1, 1 here, the
;;             same odds, so the total fits a byte.  Weights are walked from
;;             the lightest, as FFR's SpliceRandomItemWeighted orders them.
;;
;;  In: A8 = the mode, 1..FORMS_MODES-1; I16; DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_rarity:
    .a8
    .i16
    STA a:wMODE
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_RARITY)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_RARITY)
    STA a:wRNG+2
    JSR rando_warm
    STZ a:wFD                   ; the zone's first slot
  @zone:
    SEP #$20
    .a8
    LDA a:wMODE
    CMP #FORMS_TIERED
    BEQ @tiered
    REP #$20
    .a16
    LDA a:wFD
    STA a:wFK
    SEP #$20
    .a8
    LDA #4
    JSR shuffle_run             ; slots 0-3
    REP #$20
    .a16
    LDA a:wFD
    CLC
    ADC #2
    STA a:wFK
    SEP #$20
    .a8
    LDA #6
    JSR shuffle_run             ; then 2-7
    BRA @next
  @tiered:
    JSR tiered_zone
  @next:
    REP #$20
    .a16
    LDA a:wFD
    CLC
    ADC #8
    STA a:wFD
    CMP #DOMAINS_SIZE
    BCC @zone
    SEP #$20
    .a8
    RTS


;;  Fisher-Yates over A slots from wFK, from the top.  A8 = the count, 1..255;
;;  wFK the first slot, a word; A8, I16.
shuffle_run:
    .a8
    .i16
    STA a:wFC                   ; i + 1
  @loop:
    LDA a:wFC
    CMP #2
    BCC @done
    JSR rando_below             ; j, 0..i
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:wFK
    TAX
    LDA a:wFC
    AND #$00FF
    DEC A
    CLC
    ADC a:wFK
    TAY
    SEP #$20
    .a8
    LDA a:wDOMAINS, X
    PHA
    LDA a:wDOMAINS, Y
    STA a:wDOMAINS, X
    PLA
    STA a:wDOMAINS, Y
    DEC a:wFC
    BRA @loop
  @done:
    RTS


;;  The tiered deal of one zone, wFD's.  The slots in the order the weights
;;  are walked, lightest first, and each one's weight.
lut_TierSlot:   .BYTE 6, 7, 4, 5, 0, 1, 2, 3
lut_TierWeight: .BYTE 1, 1, 3, 3, 6, 6, 6, 6
TIER_TOTAL = 6 * 4 + 3 * 2 + 1 * 2

tiered_zone:
    .a8
    .i16
    LDY #$0000
  @load:
    TYX
    LDA f:RANDOFAR + lut_TierSlot, X
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:wFD
    TAX
    SEP #$20
    .a8
    LDA a:wDOMAINS, X
    STA a:wFV, Y
    TYX
    LDA f:RANDOFAR + lut_TierWeight, X
    STA a:wFW, Y
    INY
    CPY #8
    BCC @load
    LDA #TIER_TOTAL
    STA a:wFT
    LDA #8
    STA a:wFC                   ; entries left
    REP #$20
    .a16
    LDA a:wFD
    STA a:wFK                   ; the slot being dealt
    SEP #$20
    .a8
  @deal:
    LDA a:wFT
    JSR rando_below             ; r, 0..total-1
    LDY #$0000
  @walk:
    SEC
    SBC a:wFW, Y
    BCC @pick                   ; r fell inside this entry's weight
    INY
    BRA @walk
  @pick:
    LDA a:wFT
    SEC
    SBC a:wFW, Y
    STA a:wFT
    LDX a:wFK                   ; I16: wFK is a word
    LDA a:wFV, Y
    STA a:wDOMAINS, X
  @close:                       ; close the gap: entries past it move down
    INY
    CPY #8
    BCS @closed
    LDA a:wFW, Y
    STA a:wFW-1, Y
    LDA a:wFV, Y
    STA a:wFV-1, Y
    BRA @close
  @closed:
    REP #$20
    .a16
    INC a:wFK
    SEP #$20
    .a8
    DEC a:wFC
    BNE @deal
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_formation -- the body of GetBattleFormation, from the cache
;;
;;  The fixed bank's GetBattleFormation stepped the battle counter, took its
;;  byte of lut_RNG, picked a slot by lut_FormationWeight and read the zone's
;;  formation out of lut_Domains.  This is the same, reading the cache's copy:
;;  with formations off, the cartridge's own table.  The fixed bank keeps the
;;  swap to BANK_DOMAINS, so the bank mapped on the way out is what it was.
;;
;;  In: A = the zone, 0..127.  Out: btlformation set, battlecounter stepped;
;;  A, X and Y not kept -- GetBattleFormation's callers return straight away.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_formation:
    .a8
    .i8
    PHB
    PHA
    JSR enter
    JSR ensure                  ; leaves eight-bit registers
    PLA
    AND #$7F                    ; past 127 would read the cache beyond the table
    REP #$30
    .a16
    .i16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    STA a:wFD                   ; the zone's first slot
    SEP #$20
    .a8
    INC z:battlecounter
    LDA z:battlecounter
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:wENCRNG, X            ; the cache's: RNG tables may have shuffled it
    AND #$3F
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:RANDOFAR + lut_FormationWeight, X
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:wFD
    TAX
    SEP #$20
    .a8
    LDA a:wDOMAINS, X
    STA z:btlformation
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_runs -- the no-run flags and surprise rates as the cartridge has them
;;
;;  Each formation's no-run bit for both its sides, and its surprise rate.
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_runs:
    .a8
    .i16
    LDX #$0000                  ; the record
    LDY #$0000                  ; the formation
  @copy:
    LDA f:ROMFORMS + $0D, X
    AND #$01
    STA a:wNORUN, Y
    STA a:wNORUN + $80, Y
    LDA f:ROMFORMS + $0C, X
    STA a:wSURPRISE, Y
    REP #$20
    .a16
    TXA
    CLC
    ADC #16
    TAX
    SEP #$20
    .a8
    INY
    CPY #128
    BCC @copy
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_runs -- FFR's ShuffleUnrunnable, at vanilla's count
;;
;;  Every side FFR may mark becomes runnable, then RUNS_COUNT of them are
;;  drawn, without replacement, and marked.  FFR's pool, 233 sides: the
;;  A-sides of formations 1-114, the B-sides of 0-114, and the B-sides of the
;;  last four, 124-127.  Never the imps' A-side, the fiends or Chaos, or the
;;  A-sides of the last four, which keep the cartridge's flags.  A drawn entry
;;  is replaced by the list's last, as deal_traps does.
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_runs:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_RUNS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_RUNS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8

    ;  The pool, built as it is cleared: A-sides 1-114, then B-sides 0-114,
    ;  then the last four's B-sides.
    LDY #$0000                  ; entries
    LDX #$0000                  ; the formation
  @normal:
    STZ a:wNORUN, X
    STZ a:wNORUN + $80, X
    TXA
    BEQ @bside                  ; not the imps' A-side
    STA a:wLIST, Y
    INY
  @bside:
    INX
    CPX #NORMAL_FORMS
    BCC @normal
    LDX #$0000
  @bpool:
    TXA
    ORA #$80
    STA a:wLIST, Y
    INY
    INX
    CPX #NORMAL_FORMS
    BCC @bpool
    LDX #CHAOS_FORM + 1
  @last4:
    STZ a:wNORUN + $80, X
    TXA
    ORA #$80
    STA a:wLIST, Y
    INY
    INX
    CPX #128
    BCC @last4
    TYA
    STA a:wLEN                  ; 233

    LDA #RUNS_COUNT
    STA a:wFC
  @draw:
    LDA a:wLEN
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    TAY
    SEP #$20
    .a8
    LDA a:wLIST, Y
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA #$01
    STA a:wNORUN, X             ; that side cannot be run from
    DEC a:wLEN
    LDA a:wLEN
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:wLIST, X              ; the last entry fills the gap
    STA a:wLIST, Y
    DEC a:wFC
    BNE @draw
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_surprise -- FFR's ShuffleSurpriseBonus
;;
;;  The surprise rates of the 115 normal formations, Fisher-Yates from the
;;  top.  Like FFR's, it does not care which fights cannot be run from, which
;;  never ambush whatever their rate -- as in the cartridge.
;;
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_surprise:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_SURPRISE)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_SURPRISE)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDA #NORMAL_FORMS
    STA a:wFC                   ; i + 1
  @loop:
    LDA a:wFC
    CMP #2
    BCC @done
    JSR rando_below             ; j, 0..i
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA a:wFC
    AND #$00FF
    DEC A
    TAY
    SEP #$20
    .a8
    LDA a:wSURPRISE, X
    PHA
    LDA a:wSURPRISE, Y
    STA a:wSURPRISE, X
    PLA
    STA a:wSURPRISE, Y
    DEC a:wFC
    BRA @loop
  @done:
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_formdata -- EnterBattle's copy of the formation record
;;
;;  EnterBattle copied btlformation's sixteen bytes out of lut_BattleFormations
;;  into btl_formdata.  This copies them the same way and then writes two of
;;  them from the cache: the surprise rate, and bit 0 of byte $0D as the
;;  no-run flag of the side being fought.  Every reader -- the first-strike
;;  check and RUN in bank $0C, and Run -> Wait -- asks bit 0 of that copy, so
;;  none of them changes, and a side gets its own flag without FFR's second
;;  bit.  With both rows off, the cache holds the record's own bit for both
;;  sides and its own rate, so the copy is the cartridge's.
;;
;;  The fixed bank keeps its swap to BANK_BTLDATA.  In: btlformation.  Out:
;;  btl_formdata; A, X and Y not kept, as EnterBattle's loop did not keep them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_formdata:
    .a8
    .i8
    PHB
    JSR enter
    JSR ensure                  ; leaves eight-bit registers
    REP #$30
    .a16
    .i16
    LDA z:btlformation
    AND #$007F
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC #.LOWORD(ROMFORMS)
    TAX
    LDY #btl_formdata
    LDA #16 - 1
    MVN #^ROMFORMS, #^SRAMFAR   ; leaves DBR = SRAM's bank, which leave puts back
    LDA z:btlformation
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:btl_formdata + $0D
    AND #$FE
    ORA f:RW_NORUN, X           ; this side's flag
    STA a:btl_formdata + $0D
    REP #$20
    .a16
    TXA
    AND #$007F
    TAX
    SEP #$20
    .a8
    LDA f:RW_SURPRISE, X
    STA a:btl_formdata + $0C
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_touch -- every enemy's touch, element then ailment, as the cartridge
;;  has them.  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_touch:
    .a8
    .i16
    LDX #$0000                  ; the record
    LDY #$0000                  ; the touch
  @copy:
    LDA f:ROMENEMIES + $0E, X
    STA a:wTOUCH, Y
    LDA f:ROMENEMIES + $0F, X
    STA a:wTOUCH + 1, Y
    REP #$20
    .a16
    TXA
    CLC
    ADC #20
    TAX
    SEP #$20
    .a8
    INY
    INY
    CPY #256
    BCC @copy
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_touch -- FFR's ShuffleEnemyStatusAttacks, made a permutation
;;
;;  The touches of every enemy but the pirates, bosses included, Fisher-Yates
;;  from the top, element and ailment moving together.  FFR shuffles all 128
;;  and then skips the pirates' slot as it writes back, which can hand the
;;  pirates' touch to a second enemy and drop another's; this is the
;;  permutation that was meant.  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_touch:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_TOUCH)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_TOUCH)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDA #128
    JSR list_but_pirates        ; wLIST = 0..127 but 15, A = 127
    STA a:wFC                   ; i + 1
  @loop:
    LDA a:wFC
    CMP #2
    BCC @done
    JSR rando_below             ; j, 0..i
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA a:wFC
    AND #$00FF
    DEC A
    TAY
    SEP #$20
    .a8
    LDA a:wLIST, X              ; enemy j, and its touch
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    SEP #$20
    .a8
    LDA a:wLIST, Y              ; enemy i, and its
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAY
    LDA a:wTOUCH, X             ; the two bytes together
    PHA
    LDA a:wTOUCH, Y
    STA a:wTOUCH, X
    PLA
    STA a:wTOUCH, Y
    SEP #$20
    .a8
    DEC a:wFC
    BRA @loop
  @done:
    RTS


;;  wLIST = 0..A-1 without the pirates, and A = how many that is.  A8, I16.
list_but_pirates:
    .a8
    .i16
    STA a:wT2
    LDX #$0000                  ; the enemy
    LDY #$0000                  ; entries
  @fill:
    CPX #PIRATES
    BEQ @skip
    TXA
    STA a:wLIST, Y
    INY
  @skip:
    INX
    TXA
    CMP a:wT2
    BCC @fill
    TYA
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_ai -- every enemy's script id and the 44 scripts, as the cartridge
;;  has them.  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_ai:
    .a8
    .i16
    LDX #$0000                  ; the record
    LDY #$0000                  ; the enemy
  @ids:
    LDA f:ROMENEMIES + 7, X
    STA a:wESCRIPT, Y
    REP #$20
    .a16
    TXA
    CLC
    ADC #20
    TAX
    SEP #$20
    .a8
    INY
    CPY #128
    BCC @ids
    REP #$20
    .a16
    LDX #$0000
  @scripts:
    LDA f:ROMENEMYAI, X
    STA a:wSCRIPTS, X
    INX
    INX
    CPX #SCRIPTS_SIZE
    BCC @scripts
    SEP #$20
    .a8
    RTS


;;  Fisher-Yates over the script ids of the A8 enemies listed in wLIST, from
;;  the top: FFR's shuffle of a list of enemies, written back by position.
;;  A8, I16.
shuffle_ids:
    .a8
    .i16
    STA a:wFC                   ; i + 1
  @loop:
    LDA a:wFC
    CMP #2
    BCC @done
    JSR rando_below             ; j, 0..i
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA a:wFC
    AND #$00FF
    DEC A
    TAY
    SEP #$20
    .a8
    LDA a:wLIST, X
    REP #$20
    .a16
    AND #$00FF
    TAX                         ; enemy j
    SEP #$20
    .a8
    LDA a:wLIST, Y
    REP #$20
    .a16
    AND #$00FF
    TAY                         ; enemy i
    SEP #$20
    .a8
    LDA a:wESCRIPT, X
    PHA
    LDA a:wESCRIPT, Y
    STA a:wESCRIPT, X
    PLA
    STA a:wESCRIPT, Y
    DEC a:wFC
    BRA @loop
  @done:
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_escripts -- FFR's Shuffle Scripts for the normal enemies
;;
;;  The 118 normal enemies but the pirates trade script ids, so the 36 that
;;  have one still number 36, and the pirates keep theirs (none).  FFR's
;;  Everything has a Script at Vanilla, and its safe pirates.
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_escripts:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_SCRIPTS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_SCRIPTS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDA #118
    JSR list_but_pirates
    JMP shuffle_ids


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_bscripts -- FFR's Shuffle Scripts for the bosses
;;
;;  The four overworld fiends trade among themselves, then WarMECH, the four
;;  refights and Chaos among themselves.  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_Fiends:    .BYTE 119, 121, 123, 125
lut_BigBosses: .BYTE 118, 120, 122, 124, 126, 127

deal_bscripts:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_BSCRIPTS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_BSCRIPTS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDX #$0000
  @fiends:
    LDA f:RANDOFAR + lut_Fiends, X
    STA a:wLIST, X
    INX
    CPX #4
    BCC @fiends
    LDA #4
    JSR shuffle_ids
    LDX #$0000
  @big:
    LDA f:RANDOFAR + lut_BigBosses, X
    STA a:wLIST, X
    INX
    CPX #6
    BCC @big
    LDA #6
    JMP shuffle_ids


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_eskills, deal_bskills -- FFR's Shuffle Skills & Spells
;;
;;  Three groups of scripts, each dealt on its own by deal_group: the normal
;;  enemies' 34, the fiends' four, and the six of WarMECH, the refights and
;;  Chaos.  Before the normal group, two CRACKs and two TOXICs come out, as in
;;  FFR -- which takes them out whichever groups are dealt; here only when
;;  theirs is, since it is the pool they would otherwise spread through.
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_NormalScripts:
  .BYTE 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15
  .BYTE 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31
  .BYTE 33, 43
lut_NormalScriptsEnd:
lut_FiendScripts: .BYTE 34, 36, 38, 40
lut_BigScripts:   .BYTE 32, 35, 37, 39, 41, 42

deal_eskills:
    .a8
    .i16
    LDA #$FF
    STA a:wSCRIPTS + CRACK_SCRIPT * 16 + 13
    STA a:wSCRIPTS + CRACK_SCRIPT * 16 + 14
    STA a:wSCRIPTS + TOXIC_SCRIPT * 16 + 13
    STA a:wSCRIPTS + TOXIC_SCRIPT * 16 + 14
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_SKILLS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_SKILLS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDX #$0000
  @grp:
    LDA f:RANDOFAR + lut_NormalScripts, X
    STA a:wGRP, X
    INX
    CPX #lut_NormalScriptsEnd - lut_NormalScripts
    BCC @grp
    TXA
    STA a:wAGN
    JMP deal_group

deal_bskills:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_BSKILLS)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_BSKILLS)
    STA a:wRNG+2
    JSR rando_warm
    SEP #$20
    .a8
    LDX #$0000
  @fiends:
    LDA f:RANDOFAR + lut_FiendScripts, X
    STA a:wGRP, X
    INX
    CPX #4
    BCC @fiends
    LDA #4
    STA a:wAGN
    JSR deal_group
    LDX #$0000
  @big:
    LDA f:RANDOFAR + lut_BigScripts, X
    STA a:wGRP, X
    INX
    CPX #6
    BCC @big
    LDA #6
    STA a:wAGN
    JMP deal_group


;;  X = the offset in wSCRIPTS of the group's script wAGI, kept in wAREC, and
;;  Y = wAGI.  A8, I16.
rec_of_gi:
    .a8
    .i16
    REP #$20
    .a16
    LDA a:wAGI
    AND #$00FF
    TAY
    LDA a:wGRP, Y
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:wAREC
    TAX
    SEP #$20
    .a8
    RTS


;;  Fisher-Yates over A8 bytes from wFK, an address in bank $7F, from the
;;  top.  A8, I16.
fy_bytes:
    .a8
    .i16
    STA a:wFC                   ; i + 1
  @loop:
    LDA a:wFC
    CMP #2
    BCC @done
    JSR rando_below             ; j, 0..i
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:wFK
    TAX
    LDA a:wFC
    AND #$00FF
    DEC A
    CLC
    ADC a:wFK
    TAY
    SEP #$20
    .a8
    LDA a:$0000, X
    PHA
    LDA a:$0000, Y
    STA a:$0000, X
    PLA
    STA a:$0000, Y
    DEC a:wFC
    BRA @loop
  @done:
    RTS


;;  FFR's Bucketize without its min2: the wAN entries of a pool get bucket
;;  numbers at wFD (an address in bank $7F) -- entry k < wABK bucket k, each
;;  later one a bucket drawn below wABK, again if that one holds wACAP.  A
;;  bucket's entries, walked in pool order, are then its list in the order
;;  FFR's bucket gets them.  A8, I16.
bucketize:
    .a8
    .i16
    LDX #$0000
  @zero:
    STZ a:wBCNT, X
    INX
    CPX #64
    BCC @zero
    STZ a:wAK
  @next:
    LDA a:wAK
    CMP a:wAN
    BCS @done
    CMP a:wABK
    BCC @put                    ; one each to begin: entry k to bucket k
  @draw:
    LDA a:wABK
    JSR rando_below
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA a:wBCNT, X
    CMP a:wACAP
    BCS @draw                   ; full: draw again
    TXA
  @put:
    PHA
    REP #$20
    .a16
    LDA a:wAK
    AND #$00FF
    CLC
    ADC a:wFD
    TAY
    SEP #$20
    .a8
    PLA
    STA a:$0000, Y
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    INC a:wBCNT, X
    INC a:wAK
    BRA @next
  @done:
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_group -- FFR's ShuffleIndexedSkillsSpells for the scripts in wGRP
;;
;;  No Consecutive Nukes on, No Empty Scripts off.  Pool every spell and every
;;  skill of the group; then, over and over: shuffle both pools, bucket them
;;  into the scripts that cast spells (8 a script) and those that use skills
;;  (4), shuffle the two chance lists, and write the scripts out -- each a
;;  spell chance, a skill chance and, if it casts, its bucket in order.  Deal
;;  again while any list has two nukes running (FADE or NUKE; NUCLEAR among
;;  skills) or a script opens with NUKE and NUCLEAR both.  Nothing is
;;  re-pooled between deals: the pools and the chances shuffle in place, as
;;  FFR's do.
;;
;;  In: wGRP[0..wAGN).  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_group:
    .a8
    .i16
    STZ a:wANSP
    STZ a:wANSK
    STZ a:wASB
    STZ a:wAKB
    STZ a:wAGI
  @pool:
    JSR rec_of_gi
    LDA a:wSCRIPTS, X           ; the spell chance...
    STA a:wSCH, Y
    BEQ :+
    INC a:wASB
:   LDA a:wSCRIPTS + 1, X       ; ...and the skill chance
    STA a:wKCH, Y
    BEQ :+
    INC a:wAKB
:   LDY #$0000
  @spells:
    LDA a:wSCRIPTS + 2, X
    CMP #$FF
    BEQ :+
    JSR @addspell
:   INX
    INY
    CPY #8
    BCC @spells
    LDX a:wAREC
    LDY #$0000
  @skills:
    LDA a:wSCRIPTS + 11, X
    CMP #$FF
    BEQ :+
    JSR @addskill
:   INX
    INY
    CPY #4
    BCC @skills
    INC a:wAGI
    LDA a:wAGI
    CMP a:wAGN
    BCC @pool
    BRA @deal

  @addspell:                    ; A to the spell pool; X and Y kept
    PHX
    PHA
    LDA a:wANSP
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    PLA
    STA a:wSPL, X
    INC a:wANSP
    PLX
    RTS
  @addskill:
    PHX
    PHA
    LDA a:wANSK
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    PLA
    STA a:wSKL, X
    INC a:wANSK
    PLX
    RTS

  @deal:
    REP #$20
    .a16
    LDA #wSPL
    STA a:wFK
    SEP #$20
    .a8
    LDA a:wANSP
    JSR fy_bytes
    REP #$20
    .a16
    LDA #wSKL
    STA a:wFK
    SEP #$20
    .a8
    LDA a:wANSK
    JSR fy_bytes
    REP #$20
    .a16
    LDA #wSPLB
    STA a:wFD
    SEP #$20
    .a8
    LDA a:wANSP
    STA a:wAN
    LDA a:wASB
    STA a:wABK
    LDA #8
    STA a:wACAP
    JSR bucketize
    REP #$20
    .a16
    LDA #wSKLB
    STA a:wFD
    SEP #$20
    .a8
    LDA a:wANSK
    STA a:wAN
    LDA a:wAKB
    STA a:wABK
    LDA #4
    STA a:wACAP
    JSR bucketize
    REP #$20
    .a16
    LDA #wSCH
    STA a:wFK
    SEP #$20
    .a8
    LDA a:wAGN
    JSR fy_bytes
    REP #$20
    .a16
    LDA #wKCH
    STA a:wFK
    SEP #$20
    .a8
    LDA a:wAGN
    JSR fy_bytes

    STZ a:wAREROLL
    STZ a:wASI
    STZ a:wAKI
    STZ a:wAGI
  @write:
    JSR rec_of_gi
    LDA a:wSCH, Y
    STA a:wSCRIPTS, X
    LDA a:wKCH, Y
    STA a:wSCRIPTS + 1, X
    LDA #$FF
    LDY #14
  @clear:
    STA a:wSCRIPTS + 2, X
    INX
    DEY
    BNE @clear
    STZ a:wASTART

    JSR rec_of_gi               ; Y = the position again
    LDA a:wSCH, Y
    BEQ @nospells
    STZ a:wAPREV
    LDA #2
    STA a:wAJ                   ; the list's first slot
    LDY #$0000
  @spw:
    TYA
    CMP a:wANSP
    BCS @spdone
    LDA a:wSPLB, Y
    CMP a:wASI
    BNE @spskip
    STZ a:wT2                   ; is it a nuke?
    LDA a:wSPL, Y
    CMP #FADE_SPELL
    BEQ @spnuke
    CMP #NUKE_SPELL
    BNE @spput
  @spnuke:
    INC a:wT2
  @spput:
    JSR @put                    ; A at slot wAJ, the nuke rules applied
    LDA a:wAJ
    CMP #2 + 1
    BNE @spskip                 ; only the first entry opens the list
    LDA a:wT2
    ORA a:wASTART
    STA a:wASTART
  @spskip:
    INY
    BRA @spw
  @spdone:
    INC a:wASI
  @nospells:

    JSR rec_of_gi
    LDA a:wKCH, Y
    BEQ @noskills
    STZ a:wAPREV
    LDA #11
    STA a:wAJ
    LDY #$0000
  @skw:
    TYA
    CMP a:wANSK
    BCS @skdone
    LDA a:wSKLB, Y
    CMP a:wAKI
    BNE @skskip
    STZ a:wT2
    LDA a:wSKL, Y
    CMP #NUCLEAR
    BNE @skput
    INC a:wT2
  @skput:
    JSR @put
    LDA a:wAJ
    CMP #11 + 1
    BNE @skskip
    LDA a:wT2
    ASL A
    ORA a:wASTART
    STA a:wASTART
  @skskip:
    INY
    BRA @skw
  @skdone:
    INC a:wAKI
  @noskills:

    LDA a:wASTART
    CMP #3
    BNE :+
    STA a:wAREROLL              ; NUKE and NUCLEAR to open with
:   INC a:wAGI
    LDA a:wAGI
    CMP a:wAGN
    BCS :+
    JMP @write
:   LDA a:wAREROLL
    BEQ @done
    JMP @deal
  @done:
    RTS

    ;  A (an entry, its nuke flag in wT2) to slot wAJ of the script at wAREC,
    ;  then wAJ + 1.  Two nukes running set wAREROLL.  Y kept.
  @put:
    PHA
    LDA a:wT2
    AND a:wAPREV
    ORA a:wAREROLL
    STA a:wAREROLL
    LDA a:wT2
    STA a:wAPREV
    REP #$20
    .a16
    LDA a:wAJ
    AND #$00FF
    CLC
    ADC a:wAREC
    TAX
    SEP #$20
    .a8
    PLA
    STA a:wSCRIPTS, X
    INC a:wAJ
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_touch -- an enemy's touch, from the cache
;;
;;  Called by opt_scaleatk as an enemy attacks, which stores the ailment where
;;  bank $0C's attack setup took it from ROM, and under Weapon Stats the
;;  element.  With Status attacks off, the cartridge's own.
;;
;;  In: A = the enemy.  Out: A = its touch's ailment, Y = the element.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_touch:
    .a8
    .i8
    PHB
    PHA
    JSR enter
    JSR ensure                  ; leaves eight-bit registers
    PLA
    ASL A
    TAX
    LDY a:wTOUCH, X
    LDA a:wTOUCH + 1, X
    JMP leave


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_enemyai -- Enemy_DoAi's script lookup, from the cache
;;
;;  The enemy's script id comes from the cache by its id in battle RAM, not
;;  from its ROM record, and the script is copied to OPTAISHADOW in SRAM, which
;;  bank $0C's reads through @aiptr see.  So every later read is the game's
;;  own, and the per-enemy AI positions index the shadow as they indexed ROM.
;;  The shadow lives only while this enemy chooses.
;;
;;  In: ($9A) = the enemy's RAM stats, read with the caller's data bank.
;;  Out: carry set if it has no script; else clear, with @aiptr ($9E) at the
;;  shadow.  A, X, Y not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_enemyai:
    .a8
    .i8
    LDY #en_enemyid
    LDA ($9A), Y                ; battle RAM, which the caller's bank sees
    PHB
    PHA
    JSR enter
    JSR ensure                  ; leaves eight-bit registers
    PLA
    TAX
    LDA a:wESCRIPT, X
    CMP #$FF
    BEQ @none
    REP #$30
    .a16
    .i16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC #wSCRIPTS
    TAX
    LDY #OPTAISHADOW
    LDA #16 - 1
    MVN #^RANDOWRAM, #^SRAMFAR  ; leaves DBR = SRAM's bank, which PLB puts back
    SEP #$30
    .a8
    .i8
    LDA #<OPTAISHADOW
    STA z:$9E
    LDA #>OPTAISHADOW
    STA z:$9F
    SEC
    XCE
    CLC                         ; a script
    PLB
    RTL
  @none:
    SEP #$30
    SEC
    XCE
    SEC                         ; none: attack a random player
    PLB
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  copy_rng -- the encounter and battle tables, as the cartridge has them.
;;  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

copy_rng:
    .a8
    .i16
    REP #$20
    .a16
    LDX #$0000
  @copy:
    LDA f:ROMENCRNG, X
    STA a:wENCRNG, X
    LDA f:ROMBATRNG, X
    STA a:wBATRNG, X
    INX
    INX
    CPX #256
    BCC @copy
    SEP #$20
    .a8
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  deal_rng -- FFR's RNG Tables
;;
;;  The battle table, then the encounter table, each Fisher-Yates from the
;;  top, from one stream, in FFR's order.  A table of 256 needs a bound of
;;  256, so the draws are rando_below16's.  A8, I16, DBR = $7F.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

deal_rng:
    .a8
    .i16
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_RNG)
    STA a:wRNG
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_RNG)
    STA a:wRNG+2
    JSR rando_warm
    LDA #wBATRNG
    JSR fy256
    LDA #wENCRNG
    JSR fy256
    SEP #$20
    .a8
    RTS


;;  Fisher-Yates over the 256 bytes at A16 (an address in bank $7F), from the
;;  top.  A16, I16 in and out.
fy256:
    .a16
    .i16
    STA a:wFK
    LDA #256
    STA a:wFN                   ; i + 1
  @loop:
    LDA a:wFN
    CMP #2
    BCC @done
    JSR rando_below16           ; j, 0..i
    CLC
    ADC a:wFK
    TAX
    LDA a:wFN
    DEC A
    CLC
    ADC a:wFK
    TAY
    SEP #$20
    .a8
    LDA a:$0000, X
    PHA
    LDA a:$0000, Y
    STA a:$0000, X
    PLA
    STA a:$0000, Y
    REP #$20
    .a16
    DEC a:wFN
    BRA @loop
  @done:
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  rando_steprng -- BattleStepRNG's read of the encounter table
;;
;;  The step's byte, from the cache's copy of lut_RNG: the cartridge's with RNG
;;  tables off.  It runs every step, and ensures like every consumer, though
;;  @Begin has built the cache already.  BattleRNG reads the battle table from
;;  the cache with no ensure at all, because of @Begin and because every
;;  battle comes through rando_formdata besides.
;;
;;  In: X = battlestep.  Out: A = the table's byte, N and Z from it, as the
;;  LDA it replaces left them; X and Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

rando_steprng:
    .a8
    .i8
    PHB
    PHX
    PHY
    JSR enter
    JSR ensure                  ; leaves eight-bit registers
    PLY
    PLX
    LDA a:wENCRNG, X
    SEP #$30
    SEC
    XCE
    PLB
    ORA #$00                    ; N and Z from the byte, not from the bank
    RTL


.include "place.inc"
.include "rewards.inc"
.include "dlgtext.inc"
