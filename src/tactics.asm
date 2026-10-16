; ---------------------------------------------------------------------------
;  tactics.asm -- Boss tactics: a boss that plays to win (user, 2026-10-15).
;
;  Every enemy in the cartridge runs its script: a roll against its magic
;  rate, then its skill rate, else a swing; the next spell or skill in turn,
;  whatever it is; and GetRandomPlayerTarget's half, quarter, eighth, eighth
;  for the aim, whoever stands there.  With the Boss tactics dial on, a boss
;  (opt_isboss: FFR's list) weighs every action it has -- the swing, each
;  spell and each skill of its script, at each target -- and takes the one
;  worth most.  Ruthless decides everything.  Clever keeps the script's own
;  rhythm -- its rates still say when it casts, uses a skill or swings -- and
;  decides what and at whom.
;
;  The worth of an action is a number of rounds: the race between the party
;  killing the boss and the boss killing the party, and how far the action
;  moves it.  tools/tacref.py has the reckoning in full; in short --
;
;    the party's damage a round to the boss, Dp: each member's best, a swing
;    by DoPhysicalAttack's own rules or a spell it has the MP for; and so the
;    boss's rounds left, Rb, its HP over Dp;
;    the boss's best damage a turn, Db, and HP off the party worth that many
;    of its turns;
;    a kill, the HP and the rounds Rb grows when Dp loses that member, and
;    its healing over Rb, and the whole fight if it was the last;
;    stun four turns of a member's worth (a stunned player recovers one turn
;    in four), sleep one (Battle_PlayerTryWakeup), confusion two; MUTE a
;    caster's spells for good, DARK and SLOW a fighter's swing;
;    a heal of its own HP over Dp, and FAST its damage going up for good.
;
;  Damage is reckoned from the dice: a swing's mean and variance summed
;  exactly over the 256 values of the battle's dice as RandAX turns them into
;  rolls -- hit, crit, absorb, DARK, a sleeper's quarter, FAST -- and a
;  spell's from its roll; then the chance of a kill and the HP short of
;  overkill from the normal tail (gentactics.py's tables).
;
;  Thinking takes some frames, and the game's own calls each frame drive the
;  music: so the thinking yields -- whenever RDNMI says a vblank has begun
;  it runs the battle's own frame of music (tac_yield), and the music plays
;  on while the boss decides.
;
;  Entered by JSL from bank $0C: tac_turn from Enemy_DoAi once its script is
;  known, tac_swing from EnemyAttackPlayer_Physical, tac_cast from
;  Battle_CastMagicOnRandomPlayer -- in emulation mode with the battle's data
;  bank, which maps SRAM, the NES RAM and the multiplier.  The work is native
;  and sixteen bits wide; the scratch is TC_ in bank $7F, read and written
;  long.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.export tac_turn, tac_swing, tac_cast
.export lut_TacHits, lut_TacQ, lut_TacL, lut_TacSleep     ; for the tests
.export tac_moments, tac_mean, tac_meansq, tac_spellmom, tac_tail, tac_sqrt
.export tac_div, tac_divl, tac_mul, tac_f, tac_hits, tac_aim, tac_var
.import BattleRNG_L, CallMusicPlay
.import opt_isbossfar, opt_scaleatk, opt_spellbytefar
.import hal_audioframe
.import lut_MagicData, Enemy_DoMagicEffect, EnemyAttackPlayer_Physical

CAP             = 64 * 256      ; 64 rounds: the most anything is worth
HPCAP           = 4095          ; so sixteenths of HP stay in a word
MAGEFF_DAMAGE   = $01
MAGEFF_UNDEAD   = $02
MAGEFF_AILMENT  = $03
MAGEFF_SLOW     = $04
MAGEFF_HEAL     = $06           ; BtlMag_Effect_RecoverHP...
MAGEFF_HEAL2    = $07           ; ...which the jump table has twice: CURE,
                                ;   CUR2, CUR3 and HEAL are this one
MAGEFF_FAST     = $0C
MAGEFF_CUREALL  = $0F
MAGEFF_AILMENT2 = $12
TGT_ALL         = $01           ; all opponents
TGT_ONE         = $02           ; one opponent
TGT_ALLIES      = $08
TGT_ALLY        = $10
SWING           = $FFFF
LATCH_MARK      = $A0
SUM_A           = TC_A1Y - TC_S1Y   ; tac_addn's: the once-a-share sums...
SUM_E           = TC_E1Y - TC_S1Y   ; ...the extra dice's

.segment "BANK_TACTICS"
.include "tactics.inc"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_turn -- a boss's turn, from Enemy_DoAi once the script is known
;;
;;  ($9A) the enemy's RAM stats, ($9E) its script.  Not thinking -- the dial
;;  off, or not a boss: RTL, and the script runs.  Else this does not come
;;  back: it drops its own return and jumps into the game's
;;  EnemyAttackPlayer_Physical or Enemy_DoMagicEffect, as Enemy_DoAi would
;;  have, with the aim left in the latch for the hooks there.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_turn:
    .a8
    .i8
    LDA #$00
    STA f:TC_LATCH
    STA f:TC_LATCH + 1
    STA f:TC_LATCH + 2
    LDY #en_enemyid
    LDA ($9A), Y
    JSR tac_mode
    BCS :+
    RTL                         ; the script's own way
:   LDY #15                     ; the script, as @UseAi would read it
  : LDA ($9E), Y
    TYX
    STA f:TC_SCRIPT, X
    DEY
    BPL :-
    JSR tac_party
    JSR tac_boss
    JSR tac_bossatk
    JSR tac_script
    JSR tac_think
    JSR tac_decide

    LDA f:TC_CHOICE
    ASL A
    TAX
    LDA f:TC_CTGT + 1, X
    BMI :+                      ; no one in particular
    LDA f:TC_CTGT, X
    ORA #LATCH_MARK
    STA f:TC_LATCH
    EOR #$FF
    STA f:TC_LATCH + 1
    LDA btl_attacker
    STA f:TC_LATCH + 2
:   LDA f:TC_CID + 1, X
    BMI @swing
    LDA f:TC_CID, X
    PLY                         ; our own return: this turn ends where
    PLY                         ;   the game's attack does
    PLY
    JML Enemy_DoMagicEffect + BANK0CFAR
  @swing:
    LDA f:TC_CTGT, X
    PLY
    PLY
    PLY
    LDX btl_attacker
    JML EnemyAttackPlayer_Physical + BANK0CFAR


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_swing -- a swing's aim, from EnemyAttackPlayer_Physical
;;
;;  With the attacker's numbers loaded and scaled, and battle_defender_index
;;  the roll's choice.  A decision's latch for this attacker stands; else a
;;  boss with no script -- Garland, the Pirates -- weighs the swing at each
;;  target; Asshat Octopus's own aim stands.  Out: A = the slot, in
;;  battle_defender_index too; the patch's JSR PrepCharStatPointers follows
;;  it.  X kept, Y clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_swing:
    .a8
    .i8
    PHX
    JSR tac_latch
    BCC :+
    STA battle_defender_index
    PLX
    RTL
:   LDY #en_enemyid
    LDA ($84), Y
    JSR tac_mode
    BCC @keep
    LDY #en_enemyid
    LDA ($84), Y
    JSR tac_octopus
    BCS @keep
    LDA battle_defender_index
    STA f:TC_VAN
    JSR tac_party
    JSR tac_boss
    LDA btl_attacker_strength   ; the swing as it is loaded, scaled already
    STA f:TC_B0
    LDA btl_attacker_hitrate
    STA f:TC_HR
    LDA btl_attacker_critrate
    STA f:TC_CR
    LDA btl_attacker_numhits
    STA f:TC_BNH
    LDA btl_attacker_numhitsmult
    STA f:TC_BMULT
    LDA #1                      ; one candidate: the swing
    STA f:TC_NCAND
    LDA #<SWING
    STA f:TC_CID
    STA f:TC_CID + 1
    JSR tac_think
    LDA f:TC_CTGT + 1
    BMI @keep
    LDA f:TC_CTGT
    STA battle_defender_index
    PLX
    RTL
  @keep:
    LDA battle_defender_index
    PLX
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_cast -- a spell's aim, from Battle_CastMagicOnRandomPlayer
;;
;;  A decision's latch for this attacker stands; else the roll's.  Out: A =
;;  the slot with bit 7, as btl_defender takes it; btl_randomplayer the slot.
;;  X and Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_cast:
    .a8
    .i8
    PHX
    PHY
    JSR tac_latch
    BCC :+
    STA btl_randomplayer
:   LDA btl_randomplayer
    ORA #$80
    PLY
    PLX
    RTL


;;  The latch, if a decision left it for this attacker and its slot can still
;;  be hit: C set, A = the slot.  Cleared either way, so nothing reads it
;;  twice and a power-on's leftovers go at the first look.  X clobbered.
tac_latch:
    .a8
    .i8
    LDA f:TC_LATCH + 2
    CMP btl_attacker
    BNE @no
    LDA f:TC_LATCH
    EOR #$FF
    CMP f:TC_LATCH + 1
    BNE @no
    LDA f:TC_LATCH
    AND #$FC
    CMP #LATCH_MARK
    BNE @no
    LDA f:TC_LATCH
    AND #$03
    TAX
    LDA btl_drawflagsA          ; dead or stone since: the roll's, then
    ORA btl_drawflagsB
    AND f:TACTICSFAR + lut_TacBit, X
    BNE @no
    JSR @clear
    TXA
    SEC
    RTS
  @no:
    JSR @clear
    CLC
    RTS
  @clear:
    LDA #$00
    STA f:TC_LATCH
    STA f:TC_LATCH + 1
    STA f:TC_LATCH + 2
    RTS

lut_TacBit:  .BYTE $01, $02, $04, $08


;;  Whether to think at all.  In: A = the enemy's id.  Out: C set if the
;;  dial is on and the enemy is a boss -- and then the scratch is cleared and
;;  TC_MODE set.  A, X clobbered.
tac_mode:
    .a8
    .i8
    JSL opt_isbossfar + OPTFAR  ; C set: FFR counts it a boss
    BCC @out
    LDA OPTFB_BOSSAI
    AND #OPTFM_BOSSAI
    BEQ @no
    .repeat BOSSAI_SHIFT
    LSR A
    .endrep
    CMP #BOSSAI_MODES           ; the menu stops at Ruthless; a stray 3 is Off
    BCS @no
    PHA
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDX #TC_END - TC_BASE - 2
    LDA #0
  : STA f:TC_BASE, X
    DEX
    DEX
    BPL :-
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    PLA
    STA f:TC_MODE
    SEC
    RTS
  @no:
    CLC
  @out:
    RTS


;;  Asshat Octopus aims Kraken at a White Mage or Wizard whenever one can be
;;  hit, and that aim stands.  In: A = the enemy's id.  Out: C set if this
;;  swing is that one.  X clobbered.
tac_octopus:
    .a8
    .i8
    CMP #ENEMY_KRAKEN
    BEQ :+
    CMP #ENEMY_KRAKEN2
    BNE @no
:   LDA OPTFB_KRAKEN
    AND #OPTFM_KRAKEN
    BEQ @no
    LDA battle_defender_index
    AND #$03
    ASL A
    TAX
    LDA f:TACTICSFAR + lut_TacOB, X
    TAX
    LDA ch_class, X
    CMP #CLS_WM
    BEQ @yes
    CMP #CLS_WW
    BEQ @yes
  @no:
    CLC
    RTS
  @yes:
    SEC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Gathering.  Emulation mode, the battle's data bank.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  Each slot's numbers, a word each: ailments, HP and class from the
;;  out-of-battle record, the rest from the in-battle one; alive if neither
;;  dead nor stone.  And the options a reckoning needs.  X, Y clobbered.
tac_party:
    .a8
    .i8
    LDX #0                      ; a slot's word
  @slot:
    LDA f:TACTICSFAR + lut_TacOB, X
    TAY
    LDA ch_class, Y
    STA f:TC_CLS, X
    LDA ch_ailments, Y
    STA f:TC_AIL, X
    LDA ch_curhp, Y
    STA f:TC_HP, X
    LDA ch_curhp + 1, Y
    STA f:TC_HP + 1, X
    LDA ch_maxhp, Y
    STA f:TC_MAXHP, X
    LDA ch_maxhp + 1, Y
    STA f:TC_MAXHP + 1, X
    LDA f:TACTICSFAR + lut_TacIB, X
    TAY
    LDA btl_chstats + btlch_evade, Y
    STA f:TC_EV, X
    LDA btl_chstats + btlch_absorb, Y
    STA f:TC_ABSS, X
    LDA btl_chstats + btlch_magdef, Y
    STA f:TC_MD, X
    LDA btl_chstats + btlch_elemresist, Y
    STA f:TC_RES, X
    LDA btl_chstats + btlch_numhitsmult, Y
    STA f:TC_MULT, X
    LDA btl_chstats + btlch_dmg, Y
    STA f:TC_PDMG, X
    LDA btl_chstats + btlch_hitrate, Y
    STA f:TC_PHR, X
    LDA btl_chstats + btlch_numhits, Y
    STA f:TC_PNH, X
    LDA btl_chstats + btlch_critrate, Y
    STA f:TC_PCR, X
    LDA btl_chstats + btlch_category, Y     ; the weapon's, under Weapon Stats
    STA f:TC_WCAT, X
    LDA btl_chstats + btlch_elemweak, Y     ; ...and its element
    STA f:TC_WELEM, X
    LDA f:TC_AIL, X
    AND #AIL_DEAD | AIL_STONE
    BNE :+
    LDA #1
    STA f:TC_LIVE, X
:   INX
    INX
    CPX #8
    BEQ :+
    JMP @slot
:   LDA OPTD_ELEMDMG
    STA f:TC_ELEMDMG
    LDA OPTFB_WMHARM
    AND #OPTFM_WMHARM
    STA f:TC_WMHARM
    RTS

;  Each slot's records, at a slot's word: the out-of-battle record's offset
;  from ch_stats, and the in-battle one's from btl_chstats.
lut_TacOB:  .BYTE $00, 0, $40, 0, $80, 0, $C0, 0
lut_TacIB:  .BYTE 0, 0, $12, 0, 2 * $12, 0, 3 * $12, 0


;;  The boss: from its RAM stats, ($9A) -- HP, ailments, evade, absorb,
;;  multiplier, strength -- and its ROM record, through en_romptr -- max HP,
;;  magic defense, category, weakness, resistance, and the swing's hit rate,
;;  hits and crit rate as the ROM has them.  X, Y clobbered.
tac_boss:
    .a8
    .i8
    LDY #en_hp
    LDA ($9A), Y
    STA f:TC_BHP
    INY
    LDA ($9A), Y
    STA f:TC_BHP + 1
    LDY #en_ailments
    LDA ($9A), Y
    STA f:TC_BAIL
    LDY #en_evade
    LDA ($9A), Y
    STA f:TC_BEV
    LDY #en_defense
    LDA ($9A), Y
    STA f:TC_BABS
    LDY #en_numhitsmult
    LDA ($9A), Y
    STA f:TC_BMULT
    LDY #en_strength
    LDA ($9A), Y
    STA f:TC_B0
    LDY #en_romptr
    LDA ($9A), Y
    STA f:TC_T
    INY
    LDA ($9A), Y
    STA f:TC_T + 1
    CLC
    XCE
    REP #$10
    .i16
    LDA f:TC_T + 1
    XBA
    LDA f:TC_T
    TAX                         ; X = the ROM record, as the data bank sees it
    LDA a:ENROMSTAT_HPMAX, X
    STA f:TC_BMAXHP
    LDA a:ENROMSTAT_HPMAX + 1, X
    STA f:TC_BMAXHP + 1
    LDA a:ENROMSTAT_MAGDEF, X
    STA f:TC_BMD
    LDA a:ENROMSTAT_CATEGORY, X
    STA f:TC_BCAT
    LDA a:ENROMSTAT_ELEMWEAK, X
    STA f:TC_BWEAK
    LDA a:ENROMSTAT_ELEMRESIST, X
    STA f:TC_BRES
    LDA a:ENROMSTAT_HITRATE, X
    STA f:TC_HR
    LDA a:ENROMSTAT_NUMHITS, X
    STA f:TC_BNH
    LDA a:ENROMSTAT_CRITRATE, X
    STA f:TC_CR
    SEP #$10
    .i8
    SEC
    XCE
    RTS


;;  The swing's hit rate, hits and crit rate scaled as EnemyAttackPlayer_
;;  Physical will scale them: its places borrowed -- $84 at the RAM stats,
;;  the eight attacker bytes -- for opt_scaleatk, and put back.  X, Y
;;  clobbered.
tac_bossatk:
    .a8
    .i8
    LDA $84
    STA f:TC_SAVE
    LDA $85
    STA f:TC_SAVE + 1
    LDX #7
  : LDA btl_attacker_strength, X
    STA f:TC_SAVE + 2, X
    DEX
    BPL :-
    LDA $9A
    STA $84
    LDA $9B
    STA $85
    LDA f:TC_B0
    STA btl_attacker_strength
    LDA f:TC_HR
    STA btl_attacker_hitrate
    LDA f:TC_BMULT
    STA btl_attacker_numhitsmult
    LDA f:TC_BNH
    STA btl_attacker_numhits
    LDA f:TC_CR
    STA btl_attacker_critrate   ; as OptScaleEnemyAttack stores it, then
    JSL opt_scaleatk + OPTFAR   ;   asks
    LDA btl_attacker_hitrate
    STA f:TC_HR
    LDA btl_attacker_numhits
    STA f:TC_BNH
    LDA btl_attacker_critrate
    STA f:TC_CR
    LDX #7
  : LDA f:TC_SAVE + 2, X
    STA btl_attacker_strength, X
    DEX
    BPL :-
    LDA f:TC_SAVE
    STA $84
    LDA f:TC_SAVE + 1
    STA $85
    RTS


;;  The candidates: the swing, then each spell of the script once, then each
;;  skill once (its id + $42, as Enemy_DoAi casts it).  Native inside.
tac_script:
    .a8
    .i8
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA #SWING
    STA f:TC_CID
    LDA #1
    STA f:TC_NCAND
    LDY #2
  @spell:
    TYX
    LDA f:TC_SCRIPT, X
    AND #$00FF
    CMP #$00FF
    BEQ :+
    JSR @add
:   INY
    CPY #10
    BNE @spell
    LDY #11
  @skill:
    TYX
    LDA f:TC_SCRIPT, X
    AND #$00FF
    CMP #$00FF
    BEQ :+
    CLC
    ADC #$42
    JSR @add
:   INY
    CPY #15
    BNE @skill
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS
  @add:                         ; A = the id: once
    .a16
    .i16
    STA f:TC_T
    LDA f:TC_NCAND
    ASL A
    TAX
  : DEX
    DEX
    BMI :+
    LDA f:TC_CID, X
    CMP f:TC_T
    BNE :-
    RTS                         ; had it
:   LDA f:TC_NCAND
    ASL A
    TAX
    LDA f:TC_T
    STA f:TC_CID, X
    LDA f:TC_NCAND
    INC A
    STA f:TC_NCAND
    RTS


;;  A spell's or skill's record, as the battle casts it: spells through
;;  opt_spellbyte, the shop's rule and the battle's (Improved spells, Spell
;;  Fixes); skills from the ROM, TRANCE's element as its flag has it.  In: A
;;  = the attack id.  Out: TC_SHR..TC_EFF, TC_AID.  A16 X16; X kept.
tac_rec:
    .a16
    .i16
    STA f:TC_AID
    PHX
    CMP #$40
    BCC :+
    JMP @rom
:   TAX
    SEP #$20
    .a8
    LDA f:TC_SPV, X
    BEQ @ask
    JSR @at                     ; kept: X at its five
    LDA f:TC_SPREC, X
    STA f:TC_SHR
    LDA f:TC_SPREC + 1, X
    STA f:TC_EFV
    LDA f:TC_SPREC + 2, X
    STA f:TC_ELEM
    LDA f:TC_SPREC + 3, X
    STA f:TC_TGT
    LDA f:TC_SPREC + 4, X
    STA f:TC_EFF
    REP #$20
    .a16
    PLX
    RTS
  @at:                          ; X = the spell's five, from TC_AID
    .a8
    REP #$20
    .a16
    LDA f:TC_AID
    ASL A
    ASL A
    CLC
    ADC f:TC_AID
    TAX
    SEP #$20
    .a8
    RTS
  @ask:
    .a8
    LDA #1
    STA f:TC_SPV, X
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    LDY #MAGDATA_HITRATE
    JSL opt_spellbytefar + OPTFAR
    STA f:TC_SHR
    LDY #MAGDATA_EFFECTIVITY
    JSL opt_spellbytefar + OPTFAR
    STA f:TC_EFV
    LDY #MAGDATA_ELEMENT
    JSL opt_spellbytefar + OPTFAR
    STA f:TC_ELEM
    LDY #MAGDATA_TARGET
    JSL opt_spellbytefar + OPTFAR
    STA f:TC_TGT
    LDY #MAGDATA_EFFECT
    JSL opt_spellbytefar + OPTFAR
    STA f:TC_EFF
    CLC
    XCE
    REP #$10
    .i16
    JSR @at                     ; and keep it
    LDA f:TC_SHR
    STA f:TC_SPREC, X
    LDA f:TC_EFV
    STA f:TC_SPREC + 1, X
    LDA f:TC_ELEM
    STA f:TC_SPREC + 2, X
    LDA f:TC_TGT
    STA f:TC_SPREC + 3, X
    LDA f:TC_EFF
    STA f:TC_SPREC + 4, X
    REP #$30
    .a16
    .i16
    PLX
    RTS
  @rom:
    .a16
    .i16
    ASL A
    ASL A
    ASL A
    TAX
    SEP #$20
    .a8
    LDA f:lut_MagicData + BANK0CFAR + MAGDATA_HITRATE, X
    STA f:TC_SHR
    LDA f:lut_MagicData + BANK0CFAR + MAGDATA_EFFECTIVITY, X
    STA f:TC_EFV
    LDA f:lut_MagicData + BANK0CFAR + MAGDATA_ELEMENT, X
    STA f:TC_ELEM
    LDA f:lut_MagicData + BANK0CFAR + MAGDATA_TARGET, X
    STA f:TC_TGT
    LDA f:lut_MagicData + BANK0CFAR + MAGDATA_EFFECT, X
    STA f:TC_EFF
    LDA f:TC_AID
    CMP #ATTACK_TRANCE
    BNE :+
    LDA OPTFB_TRANCE
    AND #OPTFM_TRANCE
    BEQ :+
    LDA #ELEM_STATUS
    STA f:TC_ELEM
:   REP #$20
    .a16
    PLX
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_think -- the reckoning: threat, the race, each candidate's damage,
;;  what kills and disables are worth, and each candidate's worth and aim.
;;  Entered and left in emulation.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_think:
    .a8
    .i8
    CLC
    XCE
    REP #$30
    .a16
    .i16
    JSR tac_threat
    JSR tac_race
    JSR tac_pass1
    JSR tac_gains
    JSR tac_pass2
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS


;;  Each living member's damage a round to the boss: a swing -- as it is,
;;  in the dark, slowed -- and its best damage spell, and its best heal.
;;  First the living, and the most HP any of them is missing (CUR4's heal).
tac_threat:
    .a16
    .i16
    LDA #0
    STA f:TC_NALIVE
    STA f:TC_MAXMISS
    LDX #0
  : LDA f:TC_LIVE, X
    BEQ :+
    LDA f:TC_NALIVE
    INC A
    STA f:TC_NALIVE
    LDA f:TC_MAXHP, X
    SEC
    SBC f:TC_HP, X
    BCC :+
    CMP f:TC_MAXMISS
    BCC :+
    STA f:TC_MAXMISS
:   INX
    INX
    CPX #8
    BNE :--
    LDX #0
  @slot:
    JSR tac_yield
    LDA f:TC_LIVE, X
    BNE :+
    JMP @next
:   ;  The swing at the boss: a weakness hit if its weapon's category or
    ;  element meets the boss's.
    LDA f:TC_WCAT, X
    AND f:TC_BCAT
    STA f:TC_BON
    LDA f:TC_WELEM, X
    AND f:TC_BWEAK
    ORA f:TC_BON
    STA f:TC_BON
    LDA f:TC_AIL, X
    AND #AIL_DARK
    STA f:TC_AD
    LDA f:TC_BAIL
    STA f:TC_DA
    LDA f:TC_PHR, X
    STA f:TC_AHR
    LDA f:TC_BEV
    STA f:TC_DEV
    LDA f:TC_PCR, X
    STA f:TC_ACR
    LDA f:TC_PNH, X
    STA f:TC_ANH
    LDA f:TC_MULT, X
    STA f:TC_AMU
    LDA f:TC_PDMG, X
    STA f:TC_AB0
    JSR tac_aim
    LDA f:TC_BABS
    STA f:TC_ABS
    JSR tac_means
    JSR tac_mean                ; a hit, sixteenths
    JSR tac_timesn
    STA f:TC_PHYS, X
    STA f:TC_PDARK, X
    STA f:TC_PSLOW, X
    LDA f:TC_AD                 ; in the dark: 40 less
    BNE @dark
    LDA #1
    STA f:TC_AD
    JSR tac_aim
    JSR tac_mean
    JSR tac_timesn
    STA f:TC_PDARK, X
    LDA #0
    STA f:TC_AD
  @dark:
    LDA f:TC_MULT, X            ; slowed: one multiplier less
    BEQ @slow
    DEC A
    STA f:TC_AMU
    JSR tac_aim
    JSR tac_mean
    JSR tac_timesn
    STA f:TC_PSLOW, X
  @slow:
    JSR tac_spells
    LDA f:TC_PHYS, X
    CMP f:TC_MAG, X
    BCS :+
    LDA f:TC_MAG, X
:   STA f:TC_D, X
  @next:
    INX
    INX
    CPX #8
    BEQ :+
    JMP @slot
:   RTS

;;  A = TC_N times A, at most 65535.
tac_timesn:
    .a16
    STA f:TC_MY
    LDA f:TC_N
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    LDA f:TC_PR + 2
    BEQ :+
    LDA #$FFFF
    RTS
:   LDA f:TC_PR
    RTS


;;  Slot X's spells, for its threat: the best damage spell it has the MP for
;;  -- at the boss: resisted, halved and no base chance; weak, half again and
;;  40 more; HARM against the undead, or anything with White Mage HARM and a
;;  white mage casting -- its mean, a crit doubling, in sixteenths; and its
;;  best heal, HP back a cast in sixteenths.  Nothing if it is mute.
tac_spells:
    .a16
    .i16
    LDA f:TC_AIL, X
    AND #AIL_MUTE
    BEQ :+
    RTS
:   TXA
    XBA
    LSR A
    LSR A
    LSR A                       ; slot * $40
    STA f:TC_PB
    LDA #0
    STA f:TC_LV
  @level:
    JSR tac_yield
    PHX
    LDA f:TC_PB
    CLC
    ADC f:TC_LV
    TAX
    LDA a:ch_curmp, X
    PLX
    AND #$00FF
    BNE :+
    JMP @nextlevel
:   LDA #0
    STA f:TC_SL
  @slotspell:
    PHX
    LDA f:TC_LV
    ASL A
    ASL A
    CLC
    ADC f:TC_SL
    CLC
    ADC f:TC_PB
    TAX
    LDA a:ch_spells, X
    PLX
    AND #$00FF
    BNE :+
    JMP @nextspell
:   DEC A
    JSR tac_rec
    LDA f:TC_TGT
    CMP #TGT_ALL
    BEQ :+
    CMP #TGT_ONE
    BNE :++
:   JMP @harmful
:   CMP #TGT_ALLIES
    BEQ @healing
    CMP #TGT_ALLY
    BEQ @healing
    JMP @nextspell
  @healing:
    LDA f:TC_EFF
    CMP #MAGEFF_HEAL
    BEQ @heal
    CMP #MAGEFF_HEAL2
    BEQ @heal
    CMP #MAGEFF_CUREALL
    BEQ :+
    JMP @nextspell
:   LDA f:TC_MAXMISS            ; CUR4: the worst hurt, made whole
    CMP #HPCAP + 1
    BCC :+
    LDA #$FFFF
    BRA @healamt
:   ASL A
    ASL A
    ASL A
    ASL A
    BRA @healamt
  @heal:
    LDA f:TC_EFV
    INC A
    AND #$00FF
    JSR tac_f                   ; the roll's shares, summed
    LSR A
    LSR A
    LSR A
    LSR A
    STA f:TC_T
    LDA f:TC_EFV
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC f:TC_T
    CMP #4080
    BCC :+
    LDA #4080
:   STA f:TC_T
    LDA f:TC_TGT
    CMP #TGT_ALLIES
    BNE @one
    LDA f:TC_T                  ; the whole party: each one living
    STA f:TC_MY
    LDA f:TC_NALIVE
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    LDA f:TC_PR + 2
    BEQ :+
    LDA #$FFFF
    BRA @healamt
:   LDA f:TC_PR
    BRA @healamt
  @one:
    LDA f:TC_T
  @healamt:
    CMP f:TC_HEAL, X
    BCC :+
    STA f:TC_HEAL, X
:   JMP @nextspell

  @harmful:
    LDA f:TC_EFF
    CMP #MAGEFF_DAMAGE
    BEQ @damage
    CMP #MAGEFF_UNDEAD
    BEQ :+
    JMP @nextspell
:   LDA f:TC_BCAT               ; HARM: the undead...
    AND #CATEGORY_UNDEAD
    BNE @harm
    LDA f:TC_WMHARM             ; ...or anything, from a white mage
    BNE :+
    JMP @nextspell
:   LDA f:TC_CLS, X
    CMP #CLS_WM
    BEQ @harm
    CMP #CLS_WW
    BEQ @harm
    JMP @nextspell
  @harm:
    LDA f:TC_EFV
    STA f:TC_B
    LDA #148
    STA f:TC_H
    BRA @mean
  @damage:
    LDA f:TC_EFV
    STA f:TC_B
    LDA #148
    STA f:TC_H
    LDA f:TC_BRES
    AND f:TC_ELEM
    BEQ :+
    LDA f:TC_B                  ; resisted
    LSR A
    STA f:TC_B
    LDA #0
    STA f:TC_H
:   LDA f:TC_BWEAK
    AND f:TC_ELEM
    BEQ @mean
    LDA f:TC_B                  ; weak
    LSR A
    CLC
    ADC f:TC_B
    STA f:TC_B
    LDA f:TC_H
    CLC
    ADC #40
    STA f:TC_H
  @mean:
    LDA f:TC_H
    CLC
    ADC f:TC_SHR
    SEC
    SBC f:TC_BMD
    BCS :+
    LDA #0
:   JSR tac_hits
    STA f:TC_CC
    LDA f:TC_B
    INC A
    AND #$00FF
    JSR tac_f
    STA f:TC_T                  ; 256 E + F(k): the rolls summed
    LDA f:TC_B
    STA f:TC_MY
    LDA #256
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_T
    STA f:TC_MX
    LDA f:TC_PR + 2
    ADC #0
    STA f:TC_MX + 2
    LDA f:TC_CC                 ; ...times 256 + CC, over 4096
    CLC
    ADC #256
    STA f:TC_MY
    JSR tac_mul
    JSR tac_pr12
    CMP f:TC_MAG, X
    BCC @nextspell
    STA f:TC_MAG, X
  @nextspell:
    LDA f:TC_SL
    INC A
    STA f:TC_SL
    CMP #4
    BEQ :+
    JMP @slotspell
:
  @nextlevel:
    LDA f:TC_LV
    INC A
    STA f:TC_LV
    CMP #8
    BEQ :+
    JMP @level
:   RTS


;;  A = TC_PR >> 12, at most 65535.
tac_pr12:
    .a16
    LDA f:TC_PR + 2
    CMP #$1000
    BCC :+
    LDA #$FFFF
    RTS
:   ASL A
    ASL A
    ASL A
    ASL A
    STA f:TC_P12
    LDA f:TC_PR + 1
    LSR A
    LSR A
    LSR A
    LSR A
    AND #$0FFF
    ORA f:TC_P12
    RTS

;;  A = TC_PR >> 8, at most 65535.
tac_pr8:
    .a16
    LDA f:TC_PR + 3
    AND #$00FF
    BEQ :+
    LDA #$FFFF
    RTS
:   LDA f:TC_PR + 1
    RTS


;;  The race: Dp, the party's HP in sixteenths, and the boss's rounds left.
tac_race:
    .a16
    .i16
    LDA #0
    STA f:TC_T                  ; Dp's sum, saturating
    STA f:TC_HPP16
    LDX #0
  @slot:
    LDA f:TC_LIVE, X
    BEQ @next
    LDA f:TC_D, X
    CLC
    ADC f:TC_T
    BCC :+
    LDA #$FFFF
:   STA f:TC_T
    LDA f:TC_HP, X
    CMP #HPCAP + 1
    BCC :+
    LDA #HPCAP
:   ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC f:TC_HPP16
    BCC :+
    LDA #$FFFF
:   STA f:TC_HPP16
  @next:
    INX
    INX
    CPX #8
    BNE @slot
    LDA f:TC_T
    CMP #16
    BCS :+
    LDA #16
:   STA f:TC_DP
    LDA f:TC_BHP                ; Rb = HP * 4096 / Dp
    JSR tac_hp4096
    LDA f:TC_DP
    STA f:TC_DEN
    JSR tac_div
    JSR tac_cap
    STA f:TC_RB
    RTS

;;  TC_NUM = A * 4096.
tac_hp4096:
    .a16
    STA f:TC_NUM + 1            ; * 256...
    SEP #$20
    .a8
    LDA #0
    STA f:TC_NUM
    STA f:TC_NUM + 3
    REP #$20
    .a16
    PHX
    LDX #4                      ; ...* 16
  : LDA f:TC_NUM
    ASL A
    STA f:TC_NUM
    LDA f:TC_NUM + 2
    ROL A
    STA f:TC_NUM + 2
    DEX
    BNE :-
    PLX
    RTS

;;  TC_NUM = A * 256.
tac_x256:
    .a16
    STA f:TC_NUM + 1
    SEP #$20
    .a8
    LDA #0
    STA f:TC_NUM
    STA f:TC_NUM + 3
    REP #$20
    .a16
    RTS

;;  A = min(A, CAP).
tac_cap:
    .a16
    CMP #CAP + 1
    BCC :+
    LDA #CAP
:   RTS


;;  Pass 1: each candidate's damage at each living slot, and so Db -- the most
;;  any of them takes off the party.  A swing: its mean and variance, the
;;  tail; a damage spell at one or all: its roll's.
tac_pass1:
    .a16
    .i16
    LDA #0
    STA f:TC_BEST
    STA f:TC_CAND
  @cand:
    LDA f:TC_CAND
    ASL A
    TAX
    LDA f:TC_CID, X
    CMP #SWING
    BNE @spell
    LDX #0
  @swingslot:
    LDA f:TC_LIVE, X
    BEQ :+
    LDA f:TC_BMULT
    JSR tac_swingat
    LDA f:TC_EM
    STA f:TC_SEM, X
    LDA f:TC_PK
    STA f:TC_SPK, X
    LDA f:TC_EM
    CMP f:TC_BEST
    BCC :+
    STA f:TC_BEST
:   INX
    INX
    CPX #8
    BNE @swingslot
    JMP @nextcand
  @spell:
    JSR tac_rec
    LDA f:TC_EFF
    CMP #MAGEFF_DAMAGE
    BEQ :+
    JMP @nextcand
:   LDA f:TC_TGT
    CMP #TGT_ALL
    BEQ :+
    CMP #TGT_ONE
    BEQ :+
    JMP @nextcand
:   LDA #0
    STA f:TC_SUM
    LDX #0
  @spellslot:
    LDA f:TC_LIVE, X
    BEQ @nextslot
    JSR tac_spellat
    PHX
    LDA f:TC_CAND
    ASL A
    ASL A
    ASL A
    STA f:TC_T
    TXA
    CLC
    ADC f:TC_T
    TAX
    LDA f:TC_EM
    STA f:TC_XEM, X
    LDA f:TC_PK
    STA f:TC_XPK, X
    PLX
    LDA f:TC_TGT
    CMP #TGT_ALL
    BNE @one
    LDA f:TC_EM
    CLC
    ADC f:TC_SUM
    BCC :+
    LDA #$FFFF
:   STA f:TC_SUM
    BRA @nextslot
  @one:
    LDA f:TC_EM
    CMP f:TC_SUM
    BCC @nextslot
    STA f:TC_SUM
  @nextslot:
    INX
    INX
    CPX #8
    BNE @spellslot
    LDA f:TC_SUM
    CMP f:TC_BEST
    BCC @nextcand
    STA f:TC_BEST
  @nextcand:
    LDA f:TC_CAND
    INC A
    STA f:TC_CAND
    CMP f:TC_NCAND
    BEQ :+
    JMP @cand
:   LDA f:TC_BEST
    CMP #16
    BCS :+
    LDA #16
:   STA f:TC_DB
    RTS


;;  The boss's swing at slot X with multiplier A: TC_EM, TC_PK, and the hit's
;;  mean and variance kept in TC_SM16, TC_SVX for FAST's look.  X kept.
tac_swingat:
    .a16
    .i16
    STA f:TC_AMU
    JSR tac_yield
    LDA f:TC_BAIL
    AND #AIL_DARK
    STA f:TC_AD
    LDA f:TC_AIL, X
    STA f:TC_DA
    LDA f:TC_HR
    STA f:TC_AHR
    LDA f:TC_EV, X
    STA f:TC_DEV
    LDA #0
    STA f:TC_BON
    LDA f:TC_CR
    STA f:TC_ACR
    LDA f:TC_BNH
    STA f:TC_ANH
    LDA f:TC_B0
    STA f:TC_AB0
    JSR tac_aim
    LDA f:TC_ABSS, X
    STA f:TC_ABS
    JSR tac_moments
    JSR tac_mean
    STA f:TC_SM16, X
    JSR tac_meansq              ; TC_V32 = the hit's variance
    PHX
    TXA
    ASL A
    TAX
    LDA f:TC_V32
    STA f:TC_SVX, X
    LDA f:TC_V32 + 2
    STA f:TC_SVX + 2, X
    PLX
    ;  ...then N hits: fall into tac_nhits

;;  N hits of slot X's kept hit: TC_EM, TC_PK.  TC_N set.  X kept.
tac_nhits:
    .a16
    .i16
    LDA f:TC_SM16, X
    STA f:TC_MY
    LDA f:TC_N
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_M32
    LDA f:TC_PR + 2
    STA f:TC_M32 + 2
    PHX
    TXA
    ASL A
    TAX
    LDA f:TC_SVX, X
    STA f:TC_MX
    LDA f:TC_SVX + 2, X
    STA f:TC_MX + 2
    PLX
    LDA f:TC_N
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_V32
    LDA f:TC_PR + 2
    STA f:TC_V32 + 2
    LDA f:TC_HP, X
    JMP tac_tail


;;  A damage spell (the record loaded) at slot X: TC_EM, TC_PK.  X kept.
tac_spellat:
    .a16
    .i16
    JSR tac_yield
    LDA f:TC_EFV
    STA f:TC_B
    LDA #148
    STA f:TC_H
    LDA f:TC_RES, X
    AND f:TC_ELEM
    BEQ :+
    LDA f:TC_B
    LSR A
    STA f:TC_B
    LDA #0
    STA f:TC_H
:   LDA f:TC_H
    CLC
    ADC f:TC_SHR
    SEC
    SBC f:TC_MD, X
    BCS :+
    LDA #0
:   JSR tac_hits
    STA f:TC_CC
    JSR tac_spellmom            ; TC_M16, TC_V32
    LDA f:TC_M16
    STA f:TC_M32
    LDA #0
    STA f:TC_M32 + 2
    LDA f:TC_HP, X
    JMP tac_tail


;;  What killing each living member is worth, and a round of it out of
;;  action: KG = Rg(its damage) + its healing over Rb + the fight if it is
;;  the last; DG = its damage over Dp + its healing over Db.
tac_gains:
    .a16
    .i16
    LDX #0
  @slot:
    LDA f:TC_LIVE, X
    BNE :+
    JMP @next
:   LDA f:TC_D, X
    JSR tac_rg
    STA f:TC_T2
    LDA f:TC_HEAL, X
    JSR tac_overrb
    CLC
    ADC f:TC_T2
    BCC :+
    LDA #$FFFF
:   JSR tac_cap
    STA f:TC_T2
    LDA f:TC_NALIVE
    CMP #1
    BNE :+
    LDA #CAP
    STA f:TC_T2
:   LDA f:TC_T2
    STA f:TC_KG, X
    LDA f:TC_D, X               ; DG
    JSR tac_x256
    LDA f:TC_DP
    STA f:TC_DEN
    JSR tac_div
    STA f:TC_T2
    LDA f:TC_HEAL, X
    JSR tac_x256
    LDA f:TC_DB
    STA f:TC_DEN
    JSR tac_div
    CLC
    ADC f:TC_T2
    BCC :+
    LDA #$FFFF
:   JSR tac_cap
    STA f:TC_DG, X
  @next:
    INX
    INX
    CPX #8
    BEQ :+
    JMP @slot
:   RTS

;;  A = Rb * A / Db: a heal a round over the rounds left.
tac_overrb:
    .a16
    STA f:TC_MY
    LDA f:TC_RB
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_NUM
    LDA f:TC_PR + 2
    STA f:TC_NUM + 2
    LDA f:TC_DB
    STA f:TC_DEN
    JMP tac_div

;;  A = Rg(A): the rounds Rb grows when Dp loses A.  Nothing for nothing;
;;  all of CAP's rest when under 16 of Dp would be left.
tac_rg:
    .a16
    CMP #0
    BNE :+
    RTS
:   STA f:TC_RGT
    LDA f:TC_DP
    SEC
    SBC f:TC_RGT
    BCC @all                    ; more than Dp
    CMP #16
    BCC @all
    STA f:TC_DEN
    LDA f:TC_BHP
    JSR tac_hp4096
    JSR tac_div
    JSR tac_cap
    SEC
    SBC f:TC_RB
    RTS
  @all:
    LDA #CAP
    SEC
    SBC f:TC_RB
    RTS


;;  Pass 2: each candidate's worth, and its target.
tac_pass2:
    .a16
    .i16
    LDA #0
    STA f:TC_CAND
  @cand:
    JSR tac_yield
    LDA #SWING
    STA f:TC_BESTI              ; no target yet
    LDA #0
    STA f:TC_BEST
    LDA f:TC_CAND
    ASL A
    TAX
    LDA f:TC_CID, X
    CMP #SWING
    BNE @spell
    LDX #0                      ; the swing: its best target
  @swingslot:
    LDA f:TC_LIVE, X
    BEQ :+
    LDA f:TC_SEM, X
    STA f:TC_EM
    LDA f:TC_SPK, X
    STA f:TC_PK
    JSR tac_dmgval
    JSR tac_better
:   INX
    INX
    CPX #8
    BNE @swingslot
    JMP @store
  @spell:
    JSR tac_rec
    LDA f:TC_BAIL               ; a mute boss's spells and skills fail
    AND #AIL_MUTE
    BEQ :+
    JMP @store
:   LDA f:TC_TGT
    CMP #TGT_ALL
    BEQ @party
    CMP #TGT_ONE
    BEQ @party
    JSR tac_self
    STA f:TC_BEST
    JMP @store
  @party:
    LDX #0
  @slot:
    LDA #0
    STA f:TC_VAL, X
    LDA f:TC_LIVE, X
    BEQ @nextslot
    JSR tac_at
    STA f:TC_VAL, X
    LDA f:TC_TGT
    CMP #TGT_ONE
    BNE @sum
    LDA f:TC_VAL, X
    JSR tac_better
    BRA @nextslot
  @sum:
    LDA f:TC_VAL, X
    CLC
    ADC f:TC_BEST
    BCC :+
    LDA #$FFFF
:   JSR tac_cap
    STA f:TC_BEST
  @nextslot:
    INX
    INX
    CPX #8
    BNE @slot
  @store:
    LDA f:TC_CAND
    ASL A
    TAX
    LDA f:TC_BEST
    STA f:TC_CVAL, X
    LDA f:TC_BESTI
    STA f:TC_CTGT, X
    LDA f:TC_CAND
    INC A
    STA f:TC_CAND
    CMP f:TC_NCAND
    BEQ :+
    JMP @cand
:   RTS

;;  A is slot X's worth: if over TC_BEST, or the first, it is the best and
;;  slot X the target.  X kept.
tac_better:
    .a16
    .i16
    PHA
    LDA f:TC_BESTI
    CMP #SWING
    BEQ @take
    PLA
    CMP f:TC_BEST
    BEQ :+
    BCS @taken
:   RTS
  @take:
    PLA
  @taken:
    STA f:TC_BEST
    TXA
    LSR A
    STA f:TC_BESTI
    RTS

;;  A = damage worth: TC_EM over Db, and the kill chance's share of KG.
tac_dmgval:
    .a16
    .i16
    LDA f:TC_EM
    JSR tac_x256
    LDA f:TC_DB
    STA f:TC_DEN
    JSR tac_div
    STA f:TC_T2
    LDA f:TC_PK
    STA f:TC_MY
    LDA f:TC_KG, X
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    JSR tac_pr8
    CLC
    ADC f:TC_T2
    BCC :+
    LDA #$FFFF
:   JMP tac_cap


;;  A = the loaded spell's worth at slot X (one target's share).
tac_at:
    .a16
    .i16
    LDA f:TC_EFF
    CMP #MAGEFF_DAMAGE
    BNE @land
    PHX                         ; the damage pass 1 kept
    LDA f:TC_CAND
    ASL A
    ASL A
    ASL A
    STA f:TC_T
    TXA
    CLC
    ADC f:TC_T
    TAX
    LDA f:TC_XEM, X
    STA f:TC_EM
    LDA f:TC_XPK, X
    STA f:TC_PK
    PLX
    JMP tac_dmgval
  @land:
    JSR tac_landat              ; the dice that land, 0-255
    STA f:TC_CC
    LDA f:TC_EFF
    CMP #MAGEFF_AILMENT
    BEQ @ailment
    CMP #MAGEFF_SLOW
    BEQ @slow
    CMP #MAGEFF_AILMENT2
    BEQ @ailment2
    LDA #0
    RTS
  @ailment:
    JSR tac_new
    BNE :+
    RTS
:   JSR tac_status
    BRA @times
  @slow:
    LDA f:TC_MULT, X
    BNE :+
    RTS
:   LDA f:TC_PSLOW, X
    CMP f:TC_MAG, X
    BCS :+
    LDA f:TC_MAG, X
:   STA f:TC_T
    LDA f:TC_D, X
    SEC
    SBC f:TC_T
    BCS :+
    LDA #0
:   JSR tac_rg
  @times:                       ; A * the landing dice / 256
    STA f:TC_MY
    LDA f:TC_CC
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    JMP tac_pr8
  @ailment2:
    LDA f:TC_RES, X
    AND f:TC_ELEM
    BNE @none
    LDA f:TC_HP, X
    CMP #301
    BCS @none
    JSR tac_new
    BEQ @none
    JMP tac_status
  @none:
    LDA #0
    RTS

;;  A = the effectivity's ailments slot X has not got; Z set if none.
tac_new:
    .a16
    LDA f:TC_AIL, X
    EOR #$FFFF
    AND f:TC_EFV
    AND #$00FF
    RTS

;;  A = the spell's chance at slot X: 148, nothing if resisted, plus its hit
;;  rate, less magic defense, in landing dice.
tac_landat:
    .a16
    .i16
    LDA f:TC_RES, X
    AND f:TC_ELEM
    BEQ :+
    LDA #0
    BRA :++
:   LDA #148
:   CLC
    ADC f:TC_SHR
    SEC
    SBC f:TC_MD, X
    BCS :+
    LDA #0
:   JMP tac_hits


;;  A = what new ailments A do to slot X.
tac_status:
    .a16
    .i16
    STA f:TC_NEW
    AND #AIL_DEAD | AIL_STONE
    BEQ @lesser
    LDA f:TC_HP, X              ; a kill
    CMP #HPCAP + 1
    BCC :+
    LDA #HPCAP
:   ASL A
    ASL A
    ASL A
    ASL A
    JSR tac_x256
    LDA f:TC_DB
    STA f:TC_DEN
    JSR tac_div
    CLC
    ADC f:TC_KG, X
    BCC :+
    LDA #$FFFF
:   JMP tac_cap
  @lesser:
    LDA #0
    STA f:TC_SUM
    LDA f:TC_AIL, X             ; out of action already: no more out
    AND #AIL_STUN | AIL_SLEEP
    BNE @mute
    LDA f:TC_NEW
    AND #AIL_STUN
    BEQ :+
    LDA f:TC_DG, X              ; four turns
    ASL A
    ASL A
    JSR @addc
:   LDA f:TC_NEW
    AND #AIL_SLEEP
    BEQ @conf
    LDA f:TC_MAXHP, X           ; Battle_PlayerTryWakeup's turns
    CMP #81
    BCC :+
    LDA f:TC_DG, X
    BRA @sleep
:   ASL A
    PHX
    TAX
    LDA f:TACTICSFAR + lut_TacSleep, X
    PLX
    STA f:TC_MY
    LDA f:TC_DG, X
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    JSR tac_pr8
  @sleep:
    JSR @add
  @conf:
    LDA f:TC_NEW
    AND #AIL_CONF
    BEQ @mute
    LDA f:TC_DG, X              ; two turns
    ASL A
    JSR @addc
  @mute:
    LDA f:TC_NEW
    AND #AIL_MUTE
    BEQ @dark
    LDA f:TC_D, X
    SEC
    SBC f:TC_PHYS, X
    JSR tac_rg
    JSR @add
    LDA f:TC_HEAL, X
    JSR tac_overrb
    JSR @add
  @dark:
    LDA f:TC_NEW
    AND #AIL_DARK
    BEQ @poison
    LDA f:TC_PDARK, X
    CMP f:TC_MAG, X
    BCS :+
    LDA f:TC_MAG, X
:   STA f:TC_T2
    LDA f:TC_D, X
    SEC
    SBC f:TC_T2
    BCS :+
    LDA #0
:   JSR tac_rg
    JSR @add
  @poison:
    LDA f:TC_NEW
    AND #AIL_POISON
    BEQ @done
    LDA #32                     ; two HP a round, Rb rounds
    JSR tac_overrb
    JSR @add
  @done:
    LDA f:TC_SUM
    RTS
  @addc:                        ; A shifted, a carry out meaning past CAP
    BCC @add
    LDA #CAP
  @add:
    CLC
    ADC f:TC_SUM
    BCC :+
    LDA #$FFFF
:   JSR tac_cap
    STA f:TC_SUM
    RTS


;;  A = the loaded spell's worth on the boss itself: a heal of its HP over Dp,
;;  CUR4's full, FAST's swing going up for good.  0 for anything else.
tac_self:
    .a16
    .i16
    LDA f:TC_BMAXHP
    SEC
    SBC f:TC_BHP
    BCS :+
    LDA #0                      ; over its max already
:   STA f:TC_T2                 ; its missing HP
    LDA f:TC_EFF
    CMP #MAGEFF_HEAL
    BEQ @heal
    CMP #MAGEFF_HEAL2
    BEQ @heal
    CMP #MAGEFF_CUREALL
    BEQ @cureall
    CMP #MAGEFF_FAST
    BNE :+
    JMP tac_fastval
:   LDA #0
    RTS
  @heal:
    LDA f:TC_EFV
    INC A
    AND #$00FF
    JSR tac_f
    LSR A
    LSR A
    LSR A
    LSR A
    STA f:TC_T
    LDA f:TC_EFV
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC f:TC_T
    CMP #4080
    BCC :+
    LDA #4080
:   STA f:TC_T
    LDA f:TC_T2                 ; no more than it is missing
    CMP #255
    BCS @amt
    ASL A
    ASL A
    ASL A
    ASL A
    CMP f:TC_T
    BCS @amt
    STA f:TC_T
  @amt:
    LDA f:TC_T
    JSR tac_x256
    BRA @overdp
  @cureall:
    LDA f:TC_T2                 ; all of it: 16 * 256 = 4096 times
    JSR tac_hp4096
  @overdp:
    LDA f:TC_DP
    STA f:TC_DEN
    JSR tac_div
    JMP tac_cap


;;  FAST: nothing at a multiplier of 2 already; else its swing's best with one
;;  more, Db2, and A = the party's HP over Db, less over Db2.
tac_fastval:
    .a16
    .i16
    LDA f:TC_BMULT
    CMP #2
    BCC :+
    LDA #0
    RTS
:   INC A
    STA f:TC_AMU                ; the hits with it
    LDA f:TC_BNH
    STA f:TC_ANH
    JSR tac_n
    LDA #0
    STA f:TC_FAST
    LDX #0
  @slot:
    LDA f:TC_LIVE, X
    BEQ :+
    JSR tac_nhits
    LDA f:TC_EM
    CMP f:TC_FAST
    BCC :+
    STA f:TC_FAST
:   INX
    INX
    CPX #8
    BNE @slot
    LDA f:TC_HPP16
    JSR tac_x256
    LDA f:TC_DB
    STA f:TC_DEN
    JSR tac_div
    STA f:TC_T2
    LDA f:TC_FAST
    CMP f:TC_DB
    BCS :+
    LDA f:TC_DB
:   STA f:TC_DEN
    LDA f:TC_HPP16
    JSR tac_x256
    JSR tac_div
    STA f:TC_T
    LDA f:TC_T2
    SEC
    SBC f:TC_T
    JMP tac_cap


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_decide -- the candidate.  Ruthless: the one worth most, the first of
;;  equals.  Clever: the script's rates roll as Enemy_DoAi rolls them --
;;  RandAX(0, 128) under the magic rate, a spell; else under the skill rate,
;;  a skill; else the swing -- and of that kind the one worth most, or the
;;  swing if none is worth anything.  Emulation; dice for Clever only.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_decide:
    .a8
    .i8
    LDA f:TC_MODE
    CMP #BOSSAI_RUTHLESS
    BNE :+
    JMP @all
:   JSR @roll
    CMP f:TC_SCRIPT
    BCS :+
    LDA #$00                    ; a spell: ids under $42
    BRA @kind
:   JSR @roll
    CMP f:TC_SCRIPT + 1
    BCS @swing
    LDA #$01                    ; a skill
  @kind:
    STA f:TC_T
    LDA #$00
    STA f:TC_T + 1              ; compared sixteen bits wide below
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA #0
    STA f:TC_BEST
    LDA #SWING
    STA f:TC_BESTI
    LDX #2
  @k:
    TXA
    LSR A
    CMP f:TC_NCAND
    BCS @kdone
    LDA f:TC_CID, X
    CMP #$42
    LDA #0
    ROL A                       ; 1: a skill
    CMP f:TC_T
    BNE @knext
    LDA f:TC_CVAL, X
    CMP f:TC_BEST
    BEQ @knext
    BCC @knext
    STA f:TC_BEST
    TXA
    LSR A
    STA f:TC_BESTI
  @knext:
    INX
    INX
    BRA @k
  @kdone:
    LDA f:TC_BESTI
    CMP #SWING
    BNE :+
    LDA #0                      ; nothing of the kind worth anything
:   STA f:TC_CHOICE
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS
  @swing:
    LDA #$00
    STA f:TC_CHOICE
    STA f:TC_CHOICE + 1
    RTS
  @all:
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA #0
    STA f:TC_CHOICE
    LDA f:TC_CVAL
    STA f:TC_BEST
    LDX #2
  @a:
    TXA
    LSR A
    CMP f:TC_NCAND
    BCS @adone
    LDA f:TC_CVAL, X
    CMP f:TC_BEST
    BEQ :+
    BCC :+
    STA f:TC_BEST
    TXA
    LSR A
    STA f:TC_CHOICE
:   INX
    INX
    BRA @a
  @adone:
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS
  @roll:                        ; A = RandAX(0, 128), as EnemyAi_ShouldPerformAction
    .a8
    .i8
    JSR BattleRNG_L
    STA a:WRMPYA
    LDA #129
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYH
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Swings.  A16 X16 throughout, X kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  DoPhysicalAttack's numbers for TC_AD..TC_AB0: TC_H, TC_C, TC_B, TC_N.
;;  168, 40 less for an attacker in the dark, 40 more against a defender in
;;  it; a weakness hit 40 more (at most 255) and the bonus on the damage;
;;  against one asleep or stunned a quarter more damage, else the hit rate
;;  in (at most 255) and evade out (at least 0); at least 1.  The crit chance
;;  no more than the hit chance; hits times the multiplier, the low byte, at
;;  least 1.
tac_aim:
    .a16
    .i16
    LDA #168
    STA f:TC_H
    LDA f:TC_AD
    BEQ :+
    LDA #168 - 40
    STA f:TC_H
:   LDA f:TC_DA
    AND #AIL_DARK
    BEQ :+
    LDA f:TC_H
    CLC
    ADC #40
    STA f:TC_H
:   LDA f:TC_AB0
    STA f:TC_B
    LDA f:TC_BON
    BEQ @bonusless
    LDA f:TC_H
    CLC
    ADC #40
    CMP #256
    BCC :+
    LDA #255
:   STA f:TC_H
    LDA f:TC_B
    CLC
    ADC f:TC_ELEMDMG
    CMP #256
    BCC :+
    LDA #255
:   STA f:TC_B
  @bonusless:
    LDA f:TC_DA
    AND #AIL_STUN | AIL_SLEEP
    BEQ @mobile
    LDA f:TC_B
    LSR A
    LSR A
    CLC
    ADC f:TC_B
    CMP #256
    BCC :+
    LDA #255
:   STA f:TC_B
    BRA @aimed
  @mobile:
    LDA f:TC_H
    CLC
    ADC f:TC_AHR
    CMP #256
    BCC :+
    LDA #255
:   SEC
    SBC f:TC_DEV
    BCS :+
    LDA #0
:   STA f:TC_H
  @aimed:
    LDA f:TC_H
    BNE :+
    LDA #1
    STA f:TC_H
:   LDA f:TC_ACR
    CMP f:TC_H
    BCC :+
    LDA f:TC_H
:   STA f:TC_C
    ;  ...and fall into tac_n

;;  TC_N = TC_ANH * TC_AMU, the low byte, at least 1.
tac_n:
    .a16
    SEP #$20
    .a8
    LDA f:TC_ANH
    STA a:WRMPYA
    LDA f:TC_AMU
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    BNE :+
    LDA #1
:   STA f:TC_N
    LDA #0
    STA f:TC_N + 1
    REP #$20
    .a16
    RTS


;;  Over the 256 dice of TC_B's damage roll -- B + die * (B+1) / 256, at most
;;  255, and B 255 always 255 (RandAX's range wraps) -- the sums of what gets
;;  past TC_ABS (max(1, roll - absorb)) and of the roll, their squares and
;;  their product: TC_S1Y, TC_S1V, TC_S2Y, TC_S2V, TC_SYV.
;;
;;  Share by share rather than die by die: the dice whose share is m run from
;;  ceil(256 m / k) to ceil(256 (m+1) / k), k = B + 1, and with 256 = Q k + R
;;  there are Q of them or Q + 1 -- Q + 1 when the overshoot so far is under
;;  R, and it goes up by k - R; else down by R.  So each share's five are
;;  summed once, those with an extra die again, and Q multiplies the first
;;  sums at the end.  The roll is B + m until it caps at 255, and every die
;;  past that rolls 255: at most min(B, 255 - B) + 1 steps.
tac_moments:
    .a16
    .i16
    PHX
    LDA f:TC_ABS                ; absorb under B: the five follow from the
    CMP f:TC_B                  ;   rolls' sums alone, kept for two Bs
    BCS @count
    LDA f:TC_B
    INC A
    LDX #0
    CMP f:TC_MCB
    BEQ @derive
    LDX #2
    CMP f:TC_MCB + 2
    BEQ @derive
  @count:
    JSR @full
    LDA f:TC_ABS
    CMP f:TC_B
    BCS :+
    LDA f:TC_MCB                ; keep these: the older out
    STA f:TC_MCB + 2
    LDA f:TC_MC1
    STA f:TC_MC1 + 2
    LDA f:TC_MC2
    STA f:TC_MC2 + 4
    LDA f:TC_MC2 + 2
    STA f:TC_MC2 + 6
    LDA f:TC_B
    INC A
    STA f:TC_MCB
    LDA f:TC_S1V
    STA f:TC_MC1
    LDA f:TC_S2V
    STA f:TC_MC2
    LDA f:TC_S2V + 2
    STA f:TC_MC2 + 2
:   PLX
    RTS
  @derive:                      ; y = v - a for every die: S1Y = S1V - 256 a,
    LDA f:TC_MC1, X             ;   SYV = S2V - a S1V, S2Y = SYV - a S1V + 256 a^2
    STA f:TC_S1V
    TXA
    ASL A
    TAX
    LDA f:TC_MC2, X
    STA f:TC_S2V
    LDA f:TC_MC2 + 2, X
    STA f:TC_S2V + 2
    LDA f:TC_ABS
    XBA
    AND #$FF00
    EOR #$FFFF
    SEC
    ADC f:TC_S1V
    STA f:TC_S1Y
    LDA f:TC_S1V                ; a S1V
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_ABS
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_S2V
    SEC
    SBC f:TC_PR
    STA f:TC_SYV
    LDA f:TC_S2V + 2
    SBC f:TC_PR + 2
    STA f:TC_SYV + 2
    LDA f:TC_SYV
    SEC
    SBC f:TC_PR
    STA f:TC_S2Y
    LDA f:TC_SYV + 2
    SBC f:TC_PR + 2
    STA f:TC_S2Y + 2
    LDA f:TC_ABS                ; + 256 a^2
    XBA
    ORA f:TC_ABS
    STA a:WRMPYA
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    XBA
    PHA
    AND #$FF00
    CLC
    ADC f:TC_S2Y
    STA f:TC_S2Y
    PLA
    AND #$00FF
    ADC f:TC_S2Y + 2
    STA f:TC_S2Y + 2
    PLX
    RTS

  @full:
    LDX #TC_EYV + 2 - TC_S1Y
    LDA #0
  : STA f:TC_S1Y, X
    DEX
    DEX
    BPL :-
    LDA f:TC_B
    BNE :+
    LDA #0                      ; B 0: the roll 0, 1 through, every die
    JSR tac_vy
    LDX #0
    LDA #255
    JSR tac_addn
    LDA #1
    JSR tac_addn
    RTS
:   CMP #255
    BNE :+
    LDA #255                    ; B 255: 255 every die
    JSR tac_vy
    LDX #0
    LDA #255
    JSR tac_addn
    LDA #1
    JSR tac_addn
    RTS
:   INC A
    STA f:TC_K                  ; 2 to 255
    LDA #256                    ; 256 = Q k + R
    LDX #0
  : CMP f:TC_K
    BCC :+
    SBC f:TC_K
    INX
    BRA :-
:   STA f:TC_RR
    TXA
    STA f:TC_QQ
    LDA f:TC_K
    SEC
    SBC f:TC_RR
    STA f:TC_KR
    LDA #255                    ; the last share under the cap
    SEC
    SBC f:TC_B
    CMP f:TC_B
    BCC :+
    LDA f:TC_B
:   STA f:TC_LAST
    LDA #0
    STA f:TC_RN
    STA f:TC_EXTRA
    STA f:TC_SLOT               ; the share
  @share:
    JSR tac_yield
    LDA f:TC_SLOT
    CLC
    ADC f:TC_B
    JSR tac_vy
    LDX #SUM_A                  ; once, into the A sums
    LDA #1
    JSR tac_addn
    LDA f:TC_RN
    CMP f:TC_RR
    BCC @extra
    SBC f:TC_RR                 ; Q dice
    STA f:TC_RN
    BRA @next
  @extra:
    ADC f:TC_KR                 ; Q + 1 (the carry is clear)
    STA f:TC_RN
    LDA f:TC_EXTRA
    INC A
    STA f:TC_EXTRA
    LDX #SUM_E                  ; and into the E sums
    LDA #1
    JSR tac_addn
  @next:
    LDA f:TC_SLOT
    INC A
    STA f:TC_SLOT
    CMP f:TC_LAST
    BEQ @share
    BCC @share
    ;  S = Q A + E, for each of the five.
    LDX #0
  @combine:
    LDA f:TC_A1Y, X             ; the word ones, X 0 and 2
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_QQ
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_E1Y, X
    STA f:TC_S1Y, X
    INX
    INX
    CPX #4
    BNE @combine
  @combine32:
    LDA f:TC_A1Y, X             ; the long ones, X 4, 8, 12
    STA f:TC_MX
    LDA f:TC_A1Y + 2, X
    STA f:TC_MX + 2
    LDA f:TC_QQ
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_E1Y, X
    STA f:TC_S1Y, X
    LDA f:TC_PR + 2
    ADC f:TC_E1Y + 2, X
    STA f:TC_S1Y + 2, X
    INX
    INX
    INX
    INX
    CPX #16
    BNE @combine32
    ;  The dice past the last share roll 255.
    LDA f:TC_LAST
    INC A
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_QQ
    STA f:TC_MY
    JSR tac_mul
    LDA #256
    SEC
    SBC f:TC_PR
    SEC
    SBC f:TC_EXTRA
    BEQ @done
    PHA
    LDA #255
    JSR tac_vy
    LDX #0
    PLA
    JSR tac_addn
  @done:
    RTS

;;  TC_S1Y and TC_S1V alone, for a mean, the quick way where there is one:
;;  under 128 no roll caps, so the rolls sum to 256 B + F(B + 1); absorb
;;  under B clamps none of them, so what gets past is that less 256 times
;;  absorb; absorb within one of the most a roll can be, 2B, lets 1 through
;;  every die.  Anything else is counted (tac_moments).
tac_means:
    .a16
    .i16
    LDA f:TC_B
    CMP #128
    BCC :+
    JMP tac_moments
:   INC A
    JSR tac_f
    STA f:TC_S1V
    LDA f:TC_B
    XBA
    AND #$FF00
    CLC
    ADC f:TC_S1V
    STA f:TC_S1V
    LDA f:TC_ABS
    CMP f:TC_B
    BCS :+
    XBA
    AND #$FF00
    EOR #$FFFF
    SEC
    ADC f:TC_S1V                ; less 256 absorb
    STA f:TC_S1Y
    RTS
:   INC A
    STA f:TC_T
    LDA f:TC_B
    ASL A
    CMP f:TC_T
    BEQ :+
    BCC :+
    JMP tac_moments
:   LDA #256                    ; 2B no more than absorb + 1: 1 a die
    STA f:TC_S1Y
    RTS


;;  TC_V = A, a roll; TC_Y = max(1, A - absorb).
tac_vy:
    .a16
    STA f:TC_V
    SEC
    SBC f:TC_ABS
    BEQ :+
    BPL :++
:   LDA #1
:   STA f:TC_Y
    RTS

;;  Adds A (1-255) times TC_Y, TC_V, TC_Y^2, TC_V^2, TC_Y TC_V into the five
;;  sums at TC_S1Y + X: X 0 the totals, SUM_A the once-a-share sums, SUM_E
;;  the extra dice's.  X kept.
tac_addn:
    .a16
    .i16
    CMP #1
    BNE @times
    LDA f:TC_Y                  ; once: no multiplying but the squares
    CLC
    ADC f:TC_S1Y, X
    STA f:TC_S1Y, X
    LDA f:TC_V
    CLC
    ADC f:TC_S1V, X
    STA f:TC_S1V, X
    LDA f:TC_Y
    XBA
    ORA f:TC_Y
    JSR @product
    CLC
    ADC f:TC_S2Y, X
    STA f:TC_S2Y, X
    LDA f:TC_S2Y + 2, X
    ADC #0
    STA f:TC_S2Y + 2, X
    LDA f:TC_V
    XBA
    ORA f:TC_V
    JSR @product
    CLC
    ADC f:TC_S2V, X
    STA f:TC_S2V, X
    LDA f:TC_S2V + 2, X
    ADC #0
    STA f:TC_S2V + 2, X
    LDA f:TC_Y
    XBA
    ORA f:TC_V
    JSR @product
    CLC
    ADC f:TC_SYV, X
    STA f:TC_SYV, X
    LDA f:TC_SYV + 2, X
    ADC #0
    STA f:TC_SYV + 2, X
    RTS
  @times:
    STA f:TC_MY
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_Y
    STA f:TC_MX
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_S1Y, X
    STA f:TC_S1Y, X
    LDA f:TC_V
    STA f:TC_MX
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_S1V, X
    STA f:TC_S1V, X
    LDA f:TC_Y
    XBA
    ORA f:TC_Y
    JSR @product
    STA f:TC_MX
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_S2Y, X
    STA f:TC_S2Y, X
    LDA f:TC_PR + 2
    ADC f:TC_S2Y + 2, X
    STA f:TC_S2Y + 2, X
    LDA f:TC_V
    XBA
    ORA f:TC_V
    JSR @product
    STA f:TC_MX
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_S2V, X
    STA f:TC_S2V, X
    LDA f:TC_PR + 2
    ADC f:TC_S2V + 2, X
    STA f:TC_S2V + 2, X
    LDA f:TC_Y
    XBA
    ORA f:TC_V
    JSR @product
    STA f:TC_MX
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_SYV, X
    STA f:TC_SYV, X
    LDA f:TC_PR + 2
    ADC f:TC_SYV + 2, X
    STA f:TC_SYV + 2, X
    RTS
  @product:                     ; A's two bytes, multiplied: A
    STA a:WRMPYA
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    RTS


;;  A = a hit's mean, sixteenths: (CH SY + CC SV) >> 12, CH and CC the dice
;;  that hit and crit (TC_H, TC_C).  TC_CH, TC_CC, TC_M16 set.
tac_mean:
    .a16
    .i16
    LDA f:TC_H
    JSR tac_hits
    STA f:TC_CH
    LDA f:TC_C
    JSR tac_hits
    STA f:TC_CC
    LDA f:TC_S1Y
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_CH
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_X32
    LDA f:TC_PR + 2
    STA f:TC_X32 + 2
    LDA f:TC_S1V
    STA f:TC_MX
    LDA f:TC_CC
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_X32
    STA f:TC_PR
    LDA f:TC_PR + 2
    ADC f:TC_X32 + 2
    STA f:TC_PR + 2
    JSR tac_pr12
    STA f:TC_M16
    RTS


;;  TC_V32 = a hit's variance, HP squared: its mean square, (CH (S2Y >> 8) +
;;  CC ((2 SYV + S2V) >> 8)) >> 8, less the mean's square (TC_M16^2 >> 8),
;;  at least 0.  After tac_mean.
tac_meansq:
    .a16
    .i16
    LDA f:TC_S2Y + 1            ; S2Y >> 8
    STA f:TC_MX
    LDA f:TC_S2Y + 3
    AND #$00FF
    STA f:TC_MX + 2
    LDA f:TC_CH
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_Y32
    LDA f:TC_PR + 2
    STA f:TC_Y32 + 2
    LDA f:TC_SYV                ; 2 SYV + S2V
    ASL A
    STA f:TC_X32
    LDA f:TC_SYV + 2
    ROL A
    STA f:TC_X32 + 2
    LDA f:TC_X32
    CLC
    ADC f:TC_S2V
    STA f:TC_X32
    LDA f:TC_X32 + 2
    ADC f:TC_S2V + 2
    STA f:TC_X32 + 2
    LDA f:TC_X32 + 1            ; >> 8
    STA f:TC_MX
    LDA f:TC_X32 + 3
    AND #$00FF
    STA f:TC_MX + 2
    LDA f:TC_CC
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_Y32
    STA f:TC_PR
    LDA f:TC_PR + 2
    ADC f:TC_Y32 + 2
    STA f:TC_PR + 2
    LDA f:TC_PR + 1             ; >> 8: the mean square
    STA f:TC_Y32
    LDA f:TC_PR + 3
    AND #$00FF
    STA f:TC_Y32 + 2
    ;  ...less the mean's square: fall into tac_var

;;  TC_V32 = TC_Y32 - TC_M16^2 >> 8, at least 0.
tac_var:
    .a16
    LDA f:TC_M16
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_M16
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR + 1
    STA f:TC_X32
    LDA f:TC_PR + 3
    AND #$00FF
    STA f:TC_X32 + 2
    LDA f:TC_Y32
    SEC
    SBC f:TC_X32
    STA f:TC_V32
    LDA f:TC_Y32 + 2
    SBC f:TC_X32 + 2
    STA f:TC_V32 + 2
    BCS :+
    LDA #0
    STA f:TC_V32
    STA f:TC_V32 + 2
:   RTS


;;  A damage spell's roll: E (TC_B) + RandAX(0, E's low byte), doubled on
;;  TC_CC dice of 256.  TC_M16, its mean in sixteenths, and TC_V32, its
;;  variance: sd1 = 256 E + F(k), sd2 = 256 E^2 + 2 E F(k) + 256 (k-1)(2k-1)
;;  / 6 -- each share counted as if it held 256 / k dice -- with k = E's low
;;  byte + 1 in a byte; m16 = (sd1 (256 + CC)) >> 12, the mean square
;;  ((sd2 >> 8)(256 + 3 CC)) >> 8.
tac_spellmom:
    .a16
    .i16
    LDA f:TC_B
    INC A
    AND #$00FF
    STA f:TC_K
    JSR tac_f
    STA f:TC_T                  ; F(k)
    LDA f:TC_B                  ; sd1 = 256 E + F
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA #256
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_T
    STA f:TC_MX
    LDA f:TC_PR + 2
    ADC #0
    STA f:TC_MX + 2
    LDA f:TC_CC                 ; mean: sd1 (256 + CC) >> 12
    CLC
    ADC #256
    STA f:TC_MY
    JSR tac_mul
    JSR tac_pr12
    STA f:TC_M16
    LDA #0                      ; sd2: g2 first
    STA f:TC_X32
    STA f:TC_X32 + 2
    LDA f:TC_K
    BEQ @g2
    DEC A                       ; (k - 1)(2k - 1)
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_K
    ASL A
    DEC A
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR                 ; * 256 / 6
    STA f:TC_NUM + 1
    LDA f:TC_PR + 2
    SEP #$20
    .a8
    STA f:TC_NUM + 3
    LDA #0
    STA f:TC_NUM
    REP #$20
    .a16
    LDA #6
    STA f:TC_DEN
    JSR tac_divl
    LDA f:TC_NUM
    STA f:TC_X32
    LDA f:TC_NUM + 2
    STA f:TC_X32 + 2
  @g2:
    LDA f:TC_B                  ; + 2 E F
    ASL A
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_T
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_X32
    CLC
    ADC f:TC_PR
    STA f:TC_X32
    LDA f:TC_X32 + 2
    ADC f:TC_PR + 2
    STA f:TC_X32 + 2
    LDA f:TC_B                  ; + 256 E^2
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA f:TC_B
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR                 ; E^2 << 8: its low byte to the second
    XBA
    AND #$FF00
    CLC
    ADC f:TC_X32
    STA f:TC_X32
    LDA f:TC_PR + 1
    ADC f:TC_X32 + 2
    STA f:TC_X32 + 2
    LDA f:TC_X32 + 1            ; sd2 >> 8
    STA f:TC_MX
    LDA f:TC_X32 + 3
    AND #$00FF
    STA f:TC_MX + 2
    LDA f:TC_CC                 ; * (256 + 3 CC)
    ASL A
    CLC
    ADC f:TC_CC
    CLC
    ADC #256
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_PR + 1             ; >> 8
    STA f:TC_Y32
    LDA f:TC_PR + 3
    AND #$00FF
    STA f:TC_Y32 + 2
    JMP tac_var


;;  From a mean (TC_M32, sixteenths) and variance (TC_V32, HP squared) and an
;;  HP (A): TC_EM, the sixteenths short of overkill it can expect to take, and
;;  TC_PK, its chance of reaching the HP, in 256ths -- the normal tail at z =
;;  (16 HP - 8 - mean) / sd, in sixteenths, from -4 to 4.  HP 1 to HPCAP.
;;  X kept.
tac_tail:
    .a16
    .i16
    CMP #HPCAP + 1
    BCC :+
    LDA #HPCAP
:   CMP #0
    BNE :+
    LDA #1
:   ASL A
    ASL A
    ASL A
    ASL A
    STA f:TC_HPX                ; 16 HP
    LDA f:TC_V32
    STA f:TC_SQ
    LDA f:TC_V32 + 2
    STA f:TC_SQ + 2
    JSR tac_sqrt
    STA f:TC_DEN                ; the sd
    BNE @spread
    LDA #0                      ; no spread: it reaches the HP, or not
    STA f:TC_PK
    LDA f:TC_M32 + 2
    BNE @sure
    LDA f:TC_HPX
    SEC
    SBC #8
    CMP f:TC_M32
    BEQ @sure
    BCS :+
  @sure:
    LDA #256
    STA f:TC_PK
:   LDA f:TC_M32 + 2
    BNE @whole
    LDA f:TC_M32
    CMP f:TC_HPX
    BCC :+
  @whole:
    LDA f:TC_HPX
:   STA f:TC_EM
    RTS
  @spread:
    LDA f:TC_HPX                ; diff = 16 HP - 8 - mean
    SEC
    SBC #8
    SEC
    SBC f:TC_M32
    STA f:TC_DIFF
    LDA #0
    SBC f:TC_M32 + 2
    STA f:TC_DIFF + 2
    BPL :+
    LDA #0                      ; negative: its size
    SEC
    SBC f:TC_DIFF
    STA f:TC_NUM
    LDA #0
    SBC f:TC_DIFF + 2
    STA f:TC_NUM + 2
    BRA :++
:   LDA f:TC_DIFF
    STA f:TC_NUM
    LDA f:TC_DIFF + 2
    STA f:TC_NUM + 2
:   LDA f:TC_DEN                ; 64 sd or more: the end of the table
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    LDA #64
    STA f:TC_MY
    JSR tac_mul
    LDA f:TC_NUM + 2
    CMP f:TC_PR + 2
    BCC @under
    BNE @far
    LDA f:TC_NUM
    CMP f:TC_PR
    BCC @under
  @far:
    LDA #64
    BRA @q
  @under:
    JSR tac_div                 ; under 64
  @q:
    STA f:TC_TQ
    LDA f:TC_DIFF + 2
    BPL :+
    LDA #64
    SEC
    SBC f:TC_TQ
    BRA :++
:   LDA #64
    CLC
    ADC f:TC_TQ
:   ASL A                       ; j, a word's
    PHX
    TAX
    LDA f:TACTICSFAR + lut_TacQ, X
    STA f:TC_PK
    LDA f:TACTICSFAR + lut_TacL, X
    PLX
    STA f:TC_MY                 ; the excess: sd L >> 4
    LDA f:TC_DEN
    STA f:TC_MX
    LDA #0
    STA f:TC_MX + 2
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_X32
    LDA f:TC_PR + 2
    STA f:TC_X32 + 2
    LDY #4
  : LDA f:TC_X32 + 2
    LSR A
    STA f:TC_X32 + 2
    LDA f:TC_X32
    ROR A
    STA f:TC_X32
    DEY
    BNE :-
    LDA f:TC_M32                ; mean - excess, 0 to 16 HP
    SEC
    SBC f:TC_X32
    STA f:TC_X32
    LDA f:TC_M32 + 2
    SBC f:TC_X32 + 2
    BCS :+
    LDA #0
    STA f:TC_EM
    RTS
:   BNE @cap
    LDA f:TC_X32
    CMP f:TC_HPX
    BCC :+
  @cap:
    LDA f:TC_HPX
:   STA f:TC_EM
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Arithmetic.  A16 X16 throughout, X kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  A = the dice of 256 whose roll 0-200 (RandAX's, die * 201 / 256) is at
;;  or under A; 200 is a miss.
tac_hits:
    .a16
    .i16
    CMP #199
    BCC :+
    LDA #255
    RTS
:   PHX
    TAX
    LDA f:TACTICSFAR + lut_TacHits, X
    AND #$00FF
    PLX
    RTS

;;  A = F(A): the sum over the 256 dice of die * k / 256, k = A, 0-255:
;;  ((k - 1) 255 + gcd(k, 256) - 1) / 2, the gcd k's lowest set bit.
tac_f:
    .a16
    CMP #0
    BNE :+
    RTS
:   STA f:TC_FK
    EOR #$FFFF
    INC A
    AND f:TC_FK
    DEC A
    STA f:TC_FG                ; gcd - 1
    LDA f:TC_FK
    DEC A
    XBA
    AND #$FF00
    SEC
    SBC f:TC_FK
    INC A                       ; (k - 1) 256 - (k - 1)
    CLC
    ADC f:TC_FG
    LSR A
    RTS

;;  TC_PR = TC_MX (32 bits) * TC_MY (16), the low 32 bits.
tac_mul:
    .a16
    LDA f:TC_MY
    AND #$00FF
    JSR tac_mul8
    LDA f:TC_P8
    STA f:TC_PR
    LDA f:TC_P8 + 2
    STA f:TC_PR + 2
    LDA f:TC_MY + 1
    AND #$00FF
    BEQ :+
    JSR tac_mul8
    LDA f:TC_P8
    CLC
    ADC f:TC_PR + 1
    STA f:TC_PR + 1
    SEP #$20
    .a8
    LDA f:TC_P8 + 2
    ADC f:TC_PR + 3
    STA f:TC_PR + 3
    REP #$20
    .a16
:   RTS

;;  TC_P8 = TC_MX * A (a byte), the low 32 bits: its own scratch, so a
;;  caller's TC_X32 survives tac_mul.
tac_mul8:
    .a16
    SEP #$20
    .a8
    STA a:WRMPYA
    LDA f:TC_MX
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    REP #$20
    .a16
    LDA a:RDMPYL
    STA f:TC_P8
    LDA #0
    STA f:TC_P8 + 2
    SEP #$20
    .a8
    LDA f:TC_MX + 1
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    REP #$20
    .a16
    LDA a:RDMPYL
    CLC
    ADC f:TC_P8 + 1
    STA f:TC_P8 + 1
    SEP #$20
    .a8
    LDA f:TC_P8 + 3
    ADC #0
    STA f:TC_P8 + 3
    LDA f:TC_MX + 2
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    REP #$20
    .a16
    LDA a:RDMPYL
    CLC
    ADC f:TC_P8 + 2
    STA f:TC_P8 + 2
    SEP #$20
    .a8
    LDA f:TC_MX + 3
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    CLC
    ADC f:TC_P8 + 3
    STA f:TC_P8 + 3
    REP #$20
    .a16
    RTS

;;  A = min(65535, TC_NUM / TC_DEN), TC_DEN 1 or more.  TC_NUM used up.
tac_div:
    .a16
    .i16
    PHX
    LDA f:TC_NUM + 2
    CMP f:TC_DEN
    BCC :+
    LDA #$FFFF
    PLX
    RTS
:   LDX #16
  @bit:
    LDA f:TC_NUM
    ASL A
    STA f:TC_NUM
    LDA f:TC_NUM + 2
    ROL A
    BCS @sub                    ; seventeen bits: past the divisor
    CMP f:TC_DEN
    BCC @keep
  @sub:
    SBC f:TC_DEN
    STA f:TC_NUM + 2
    LDA f:TC_NUM
    ORA #1
    STA f:TC_NUM
    BRA @next
  @keep:
    STA f:TC_NUM + 2
  @next:
    DEX
    BNE @bit
    LDA f:TC_NUM
    PLX
    RTS

;;  TC_NUM = TC_NUM / TC_DEN, all 32 bits of it.
tac_divl:
    .a16
    .i16
    PHX
    LDA #0
    STA f:TC_REM
    LDX #32
  @bit:
    LDA f:TC_NUM
    ASL A
    STA f:TC_NUM
    LDA f:TC_NUM + 2
    ROL A
    STA f:TC_NUM + 2
    LDA f:TC_REM
    ROL A
    BCS @sub
    CMP f:TC_DEN
    BCC @keep
  @sub:
    SBC f:TC_DEN
    STA f:TC_REM
    LDA f:TC_NUM
    ORA #1
    STA f:TC_NUM
    BRA @next
  @keep:
    STA f:TC_REM
  @next:
    DEX
    BNE @bit
    PLX
    RTS

;;  A = floor(sqrt(TC_SQ)), 32 bits in.  Bit by bit, no multiplying.
tac_sqrt:
    .a16
    .i16
    LDA #0
    STA f:TC_SQR
    STA f:TC_SQR + 2
    STA f:TC_SQB
    STA f:TC_SQB + 2
    LDA f:TC_SQ + 2
    BNE :+
    LDA #$4000                  ; a word: one = 1 << 14
    STA f:TC_SQB
    BRA @down
:   LDA #$4000
    STA f:TC_SQB + 2            ; one = 1 << 30
  @down:                        ; while one > op, one >>= 2
    LDA f:TC_SQB + 2
    CMP f:TC_SQ + 2
    BCC @loop
    BNE :+
    LDA f:TC_SQB
    CMP f:TC_SQ
    BCC @loop
    BEQ @loop
:   JSR @quarter
    LDA f:TC_SQB
    ORA f:TC_SQB + 2
    BNE @down
    LDA #0
    RTS
  @loop:
    LDA f:TC_SQR                ; t = res + one
    CLC
    ADC f:TC_SQB
    STA f:TC_X32
    LDA f:TC_SQR + 2
    ADC f:TC_SQB + 2
    STA f:TC_X32 + 2
    LDA f:TC_SQ + 2             ; op >= t?
    CMP f:TC_X32 + 2
    BCC @smaller
    BNE @bigger
    LDA f:TC_SQ
    CMP f:TC_X32
    BCC @smaller
  @bigger:
    LDA f:TC_SQ                 ; op -= t
    SEC
    SBC f:TC_X32
    STA f:TC_SQ
    LDA f:TC_SQ + 2
    SBC f:TC_X32 + 2
    STA f:TC_SQ + 2
    JSR @half                   ; res = res / 2 + one
    LDA f:TC_SQR
    CLC
    ADC f:TC_SQB
    STA f:TC_SQR
    LDA f:TC_SQR + 2
    ADC f:TC_SQB + 2
    STA f:TC_SQR + 2
    BRA @step
  @smaller:
    JSR @half
  @step:
    JSR @quarter
    LDA f:TC_SQB
    ORA f:TC_SQB + 2
    BNE @loop
    LDA f:TC_SQR
    RTS
  @half:
    LDA f:TC_SQR + 2
    LSR A
    STA f:TC_SQR + 2
    LDA f:TC_SQR
    ROR A
    STA f:TC_SQR
    RTS
  @quarter:
    LDA f:TC_SQB + 2
    LSR A
    STA f:TC_SQB + 2
    LDA f:TC_SQB
    ROR A
    STA f:TC_SQB
    LDA f:TC_SQB + 2
    LSR A
    STA f:TC_SQB + 2
    LDA f:TC_SQB
    ROR A
    STA f:TC_SQB
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_yield -- a frame of music, if a vblank has begun since the last look
;;
;;  RDNMI latches at the top of every vblank and clears when read, so one
;;  read says whether a frame has gone by, however long since.  If one has:
;;  the battle's own frame of music -- BattleUpdateAudio's follow-up track,
;;  then CallMusicPlay, swapping back to this chunk -- and the HAL's frame of
;;  sound.  Nothing on screen moves while a boss thinks, so nothing else of
;;  the frame is owed.  A16 X16; every register, the data bank and the mode
;;  as they were.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_yield:
    .a16
    .i16
    PHP
    SEP #$20
    .a8
    LDA a:RDNMI
    BMI :+
    PLP
    RTS
:   REP #$30
    .a16
    .i16
    PHA
    PHX
    PHY
    PHB
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    LDA cur_bank
    PHA
    LDA #CHUNK_TACTICS
    STA cur_bank
    LDA a:music_track
    BPL :+
    LDA btl_followupmusic
    STA a:music_track
:   JSR CallMusicPlay
    PLA
    STA cur_bank
    JSL hal_audioframe + HALFAR
    CLC
    XCE
    REP #$30
    .a16
    .i16
    PLB
    PLY
    PLX
    PLA
    PLP
    RTS
