; ---------------------------------------------------------------------------
;  tactics.asm -- Boss tactics: where a boss aims (user, 2026-10-15).
;
;  Every enemy in the cartridge aims by GetRandomPlayerTarget: the first slot
;  half the time, the second a quarter, the third and fourth an eighth each,
;  rerolled past the dead and the stone -- whatever the attack, whoever
;  stands there.  With the Boss tactics dial on, a boss (opt_isboss: FFR's
;  list) scores each target first:
;
;    a physical attack, by the share of the target's HP it can expect to
;    take, to 256 for all of it: DoPhysicalAttack's own hit, crit and damage
;    rules -- evade, absorb, DARK either way, a sleeper's quarter more and no
;    dodging, FAST's hits -- summed exactly over the 256 values of the
;    battle's dice, as RandAX turns a die into a roll;
;
;    a spell or skill at one target, by its chance to work there: the hit
;    roll against magic defense with the element resisted or not, nothing
;    for an ailment already had or SLOW on one already slowed, XXXX and
;    STUN's 300 HP; a damage spell, as a physical attack, by the share of HP.
;    An effect not weighed here leaves every target alike.
;
;  Clever: vanilla's weights times the scores -- still drawn to the front,
;  but a target it can finish pulls hard.  Ruthless: the best score, and
;  vanilla's weights among equals.  Either rolls one battle die when there
;  is a choice to make, none when there is one candidate; and nothing at all
;  is touched with the dial off or an attacker that is not a boss, so those
;  turns are vanilla's, roll for roll.  Choosing the spell is the next part.
;
;  Exact sums rather than a rehearsal of the swing: the game's own calls
;  each frame drive the music, so a turn's thinking has to fit in a frame or
;  so.  The damage die is summed once per base damage, and again only for a
;  target whose absorb the weakest roll does not clear.
;
;  Entered by JSL from bank $0C's two places that aim at a random player,
;  in emulation mode with the battle's data bank, which maps SRAM, the
;  NES RAM and the multiplier alike.  The work is native and sixteen bits
;  wide; the scratch is TC_ in bank $7F, read and written long.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.export tac_swing, tac_cast
.export lut_TacHits, lut_TacSlotW           ; for the tests
.import BattleRNG_L
.import opt_isbossfar

MAGEFF_DAMAGE   = $01           ; BtlMag_Effect_Damage
MAGEFF_AILMENT  = $03           ; BtlMag_Effect_InflictAilment
MAGEFF_SLOW     = $04           ; BtlMag_Effect_Slow
MAGEFF_AILMENT2 = $12           ; BtlMag_Effect_InflictAilment2: XXXX, STUN
MAG_BASEHIT     = 148           ; BtlMag_LoadBaseHitChance
PHYS_BASEHIT    = 168           ; DoPhysicalAttack's
DARK_HIT        = 40            ; ...and DARK's, either way
AILMENT2_HP     = 300           ; at or under it, XXXX and STUN take
HP_CAP          = 2047          ; so sixteenths of HP stay under 32768

.segment "BANK_TACTICS"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_swing -- a physical attack, from EnemyAttackPlayer_Physical
;;
;;  With the attacker's numbers loaded -- strength, hit rate, hits, the
;;  multiplier, crit rate, scaled -- and battle_defender_index the roll's
;;  choice.  Out: A = the slot to hit, in battle_defender_index too; the
;;  patch's JSR PrepCharStatPointers then points the stat pointers at it.
;;  X kept, Y clobbered.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_swing:
    .a8
    .i8
    PHX
    LDY #en_enemyid
    LDA ($84), Y                ; the attacker's RAM stats, $84 here
    JSR tac_mode
    BCC @keep
    LDY #en_enemyid
    LDA ($84), Y
    JSR tac_octopus
    BCS @keep
    LDA battle_defender_index
    STA f:TC_VAN
    JSR tac_party

    LDA btl_attacker_strength
    STA f:TC_B0
    LDA btl_attacker_hitrate
    STA f:TC_HR
    LDA btl_attacker_critrate
    STA f:TC_CR
    LDA btl_attacker_numhits    ; hits times the multiplier, the low byte as
    STA a:WRMPYA                ;   MultiplyXA leaves DoPhysicalAttack...
    LDA btl_attacker_numhitsmult
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    BNE :+
    LDA #1                      ; ...and at least one
:   STA f:TC_N
    LDY #en_ailments
    LDA ($84), Y
    AND #AIL_DARK
    STA f:TC_DARK

    JSR tac_physical
    JSR tac_pick
    STA battle_defender_index
    PLX
    RTL
  @keep:
    LDA battle_defender_index
    PLX
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_cast -- a spell or skill at one player, from
;;  Battle_CastMagicOnRandomPlayer
;;
;;  With the spell's numbers loaded (Battle_PrepareMagic) and
;;  btl_randomplayer the roll's choice.  Out: A = the slot, bit 7 set, as
;;  btl_defender takes it; btl_randomplayer the slot.  X and Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_cast:
    .a8
    .i8
    PHX
    PHY
    LDA btl_attacker            ; an enemy's slot; a player's has bit 7
    BMI @keep
    STA a:WRMPYA
    LDA #$14                    ; GetEnemyStatPtr's stride
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    LDX a:RDMPYL
    LDA btl_enemystats + en_enemyid, X
    JSR tac_mode
    BCC @keep
    LDA btl_randomplayer
    STA f:TC_VAN
    JSR tac_party

    LDA btlmag_effect
    STA f:TC_EFF
    LDA btlmag_effectivity
    STA f:TC_EFV
    LDA btlmag_element
    STA f:TC_ELEM
    LDA btlmag_hitrate
    STA f:TC_SHR

    JSR tac_spell
    JSR tac_pick
    STA btl_randomplayer
  @keep:
    LDA btl_randomplayer
    ORA #$80
    PLY
    PLX
    RTL


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
    LDX #TC_END - TC_BASE
    LDA #$00
  : STA f:TC_BASE - 1, X
    DEX
    BNE :-
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
    ASL A                       ; a slot's word
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


;;  Each slot's numbers, a word each: whether it can be aimed at -- not dead
;;  and not stone, as GetRandomPlayerTarget asks btl_drawflagsA and B -- and
;;  what the attack code reads of it: ailments and HP from the out-of-battle
;;  record, the rest from the in-battle one.  X, Y clobbered.
tac_party:
    .a8
    .i8
    LDA btl_drawflagsA
    ORA btl_drawflagsB
    EOR #$FF
    PHA                         ; the slots that can be hit, slot n in bit n
    LDX #0                      ; a slot's word
  @slot:
    LDA f:TACTICSFAR + lut_TacOB, X
    TAY
    LDA ch_ailments, Y
    STA f:TC_AIL, X
    LDA ch_curhp, Y
    STA f:TC_HP, X
    LDA ch_curhp + 1, Y
    STA f:TC_HP + 1, X
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
    PLA
    LSR A                       ; this slot's bit...
    PHA
    LDA #$00
    ROL A                       ; ...as 0 or 1
    STA f:TC_LIVE, X
    INX
    INX
    CPX #8
    BNE @slot
    PLA
    RTS

;  Each slot's records, at a slot's word: the out-of-battle record's offset
;  from ch_stats, and the in-battle one's from btl_chstats.
lut_TacOB:  .BYTE $00, 0, $40, 0, $80, 0, $C0, 0
lut_TacIB:  .BYTE 0, 0, $12, 0, 2 * $12, 0, 3 * $12, 0


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_physical -- each slot's score for the swing loaded in TC_B0..TC_DARK
;;
;;  DoPhysicalAttack, enemy against player, piece by piece.  The hit chance
;;  is 168, 40 less for an attacker in the dark and 40 more against a target
;;  in it; against one awake and able to move, plus the hit rate (at most
;;  255) and less its evade (at least 0); against one asleep or stunned the
;;  base damage a quarter more (at most 255) instead; at least 1.  The crit
;;  chance is the crit rate, no more than the hit chance.  Each hit: a die
;;  for the roll, 0-200 -- 200 is no swing at all -- hitting at or under the
;;  hit chance and critting at or under the crit chance; a die for the
;;  damage, B + die * (B + 1) / 256 to at most 255, less absorb, at least 1,
;;  and a crit adds the damage roll again.
;;
;;  So over the 256 dice, with CH dice that hit and CC that crit, SD the
;;  damage rolls' sum and SX the sum of what gets past absorb, a hit is
;;  expected to do (CH * SX + CC * SD) / 65536, kept in sixteenths, and N
;;  hits N times that.  The score: 256 if that reaches the slot's HP, else
;;  256 times the share.  Native, entered and left in emulation.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_physical:
    .a8
    .i8
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA #$FFFF
    STA f:TC_SDB                ; no damage sums yet
    STA f:TC_SDB2
    LDX #0
  @slot:
    LDA f:TC_LIVE, X
    BNE :+
    JMP @next                   ; its score stays 0
:   LDA #PHYS_BASEHIT
    STA f:TC_H
    LDA f:TC_DARK
    BEQ :+
    LDA #PHYS_BASEHIT - DARK_HIT
    STA f:TC_H
:   LDA f:TC_AIL, X
    AND #AIL_DARK
    BEQ :+
    LDA f:TC_H
    CLC
    ADC #DARK_HIT
    STA f:TC_H
:   LDA f:TC_B0
    STA f:TC_B
    LDA f:TC_AIL, X
    AND #AIL_STUN | AIL_SLEEP
    BEQ @mobile
    LDA f:TC_B0                 ; a quarter more against one who cannot move
    LSR A
    LSR A
    CLC
    ADC f:TC_B0
    CMP #256
    BCC :+
    LDA #255
:   STA f:TC_B
    BRA @aimed
  @mobile:
    LDA f:TC_H
    CLC
    ADC f:TC_HR
    CMP #256
    BCC :+
    LDA #255
:   SEC
    SBC f:TC_EV, X
    BCS :+
    LDA #0
:   STA f:TC_H
  @aimed:
    LDA f:TC_H
    BNE :+
    LDA #1
    STA f:TC_H
:   LDA f:TC_CR                 ; the crit chance, no more than the hit chance
    CMP f:TC_H
    BCC :+
    LDA f:TC_H
:   JSR tac_count
    STA f:TC_CC
    LDA f:TC_H
    JSR tac_count
    STA f:TC_CH
    LDA f:TC_ABSS, X
    STA f:TC_ABS
    JSR tac_sums

    LDA f:TC_CH                 ; P = CH * SX + CC * SD
    STA f:TC_MA
    LDA f:TC_SX
    STA f:TC_MB
    JSR tac_mul
    LDA f:TC_PR
    STA f:TC_P
    LDA f:TC_PR + 2
    STA f:TC_P + 2
    LDA f:TC_CC
    STA f:TC_MA
    LDA f:TC_SD
    STA f:TC_MB
    JSR tac_mul
    LDA f:TC_P
    CLC
    ADC f:TC_PR
    STA f:TC_P
    LDA f:TC_P + 2
    ADC f:TC_PR + 2
    STA f:TC_P + 2

    LDA f:TC_P + 1              ; a hit's damage in sixteenths: P >> 12,
    LSR A                       ;   under 8192
    LSR A
    LSR A
    LSR A
    STA f:TC_MB
    LDA f:TC_P + 3
    AND #$000F
    XBA
    ASL A
    ASL A
    ASL A
    ASL A
    ORA f:TC_MB
    STA f:TC_MB
    LDA f:TC_N                  ; ...times the hits
    STA f:TC_MA
    JSR tac_mul

    LDA f:TC_HP, X              ; the HP, in sixteenths
    CMP #HP_CAP + 1
    BCC :+
    LDA #HP_CAP
:   ASL A
    ASL A
    ASL A
    ASL A
    STA f:TC_DEN
    LDA f:TC_PR + 2
    AND #$00FF
    BNE @all                    ; 4096 HP and more: past anyone's
    LDA f:TC_PR
    CMP f:TC_DEN
    BCS @all
    STA f:TC_NUM + 1            ; the share, in 256ths: T * 256...
    SEP #$20
    .a8
    LDA #0
    STA f:TC_NUM                ; ...its low byte clear...
    STA f:TC_NUM + 3            ; ...and its top
    REP #$20
    .a16
    JSR tac_div
    BRA @score
  @all:
    LDA #256
  @score:
    STA f:TC_U, X
  @next:
    INX
    INX
    CPX #8
    BEQ :+
    JMP @slot
:   SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS


;;  SD and SX for TC_B and TC_ABS -- over the 256 dice, the damage rolls and
;;  what of each gets past absorb, max(1, roll - absorb).  RandAX's roll is
;;  B + die * (B+1) / 256, at most 255: so every roll is at least B, and for
;;  absorb under B nothing is clamped and SX is SD less 256 times absorb; if
;;  no roll can be more than one past absorb, every die lets 1 through; only
;;  between are the rolls counted (tac_shares).  SD has a closed form while
;;  no roll is capped, B under 128 (tac_sd).  SD is kept for two Bs, awake
;;  and asleep.  A16 X16, X kept.
tac_sums:
    .a16
    .i16
    LDA f:TC_B
    CMP f:TC_SDB
    BEQ @have
    CMP f:TC_SDB2
    BNE @new
    LDA f:TC_SD2                ; the other one kept: swap them
    PHA
    LDA f:TC_SD
    STA f:TC_SD2
    PLA
    STA f:TC_SD
    LDA f:TC_SDB
    STA f:TC_SDB2
    LDA f:TC_B
    STA f:TC_SDB
    BRA @have
  @new:
    LDA f:TC_SDB                ; keep the one there
    STA f:TC_SDB2
    LDA f:TC_SD
    STA f:TC_SD2
    LDA f:TC_B
    CMP #128
    BCC :+
    JMP tac_shares              ; some rolls capped: count them
:   JSR tac_sd
  @have:
    LDA f:TC_ABS
    CMP f:TC_B
    BCS @armour
    XBA
    AND #$FF00                  ; absorb * 256
    STA f:TC_PR
    LDA f:TC_SD
    SEC
    SBC f:TC_PR
    STA f:TC_SX
    RTS
  @armour:
    LDA f:TC_B                  ; the most a roll can be: 2B, at most 255
    ASL A
    CMP #256
    BCC :+
    LDA #255
:   STA f:TC_PR
    LDA f:TC_ABS
    INC A
    CMP f:TC_PR
    BCS @ones                   ; none more than one past absorb
    JMP tac_shares
  @ones:
    LDA #256
    STA f:TC_SX
    RTS


;;  SD for B under 128, where no roll is capped: 256 B plus the dice's
;;  shares, the sum over b of b * k / 256 with k = B + 1, which is
;;  ((k - 1) * 255 + gcd(k, 256) - 1) / 2 -- and gcd(k, 256) is k's lowest
;;  set bit.  A16 X16.
tac_sd:
    .a16
    .i16
    LDA f:TC_B
    STA f:TC_SDB
    INC A                       ; k
    STA f:TC_PR
    EOR #$FFFF
    INC A
    AND f:TC_PR                 ; its lowest bit
    DEC A
    STA f:TC_PR                 ; gcd - 1
    LDA f:TC_B
    XBA
    AND #$FF00
    SEC
    SBC f:TC_B                  ; (k - 1) * 255
    CLC
    ADC f:TC_PR
    LSR A                       ; the shares
    STA f:TC_PR
    LDA f:TC_B
    XBA
    AND #$FF00                  ; and B a die
    CLC
    ADC f:TC_PR
    STA f:TC_SD
    RTS


;;  SD and SX counted, for TC_B and TC_ABS, and TC_SDB = TC_B.  Share by
;;  share rather than die by die: the dice whose share is m run from
;;  ceil(256 m / k) to ceil(256 (m+1) / k), with k = B + 1, and with 256 =
;;  Q k + R there are Q of them or Q + 1 -- Q + 1 when the overshoot so far,
;;  (dice so far) k - 256 m, is under R, and it goes up by k - R; else it
;;  goes down by R.  So the rolls are summed once a share, those of the
;;  shares with an extra die again, and Q multiplies the first sum at the
;;  end.  Their roll is B + m until it caps at 255, and every die past that
;;  rolls 255: so at most min(B, 255 - B) + 1 steps, never more than 128.
;;  B 0 rolls 0 always, and B 255 rolls 255 (RandAX's range wraps).
;;  A16 X16, X kept.
tac_shares:
    .a16
    .i16
    PHX
    LDA f:TC_B
    STA f:TC_SDB
    BNE :+
    LDA #0                      ; B 0: every roll 0, 1 through
    STA f:TC_SD
    LDA #256
    STA f:TC_SX
    PLX
    RTS
:   CMP #255
    BNE :+
    JMP @capped
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
    LDA #255                    ; the last share under the cap: 255 - B,
    SEC                         ;   or B itself, whichever is less
    SBC f:TC_B
    CMP f:TC_B
    BCC :+
    LDA f:TC_B
:   STA f:TC_LAST
    LDA #0
    STA f:TC_RN
    STA f:TC_SV
    STA f:TC_SXV
    STA f:TC_SD1
    STA f:TC_SX1
    TAY                         ; shares with Q + 1 dice
    LDX #0                      ; the share
  @share:
    TXA
    CLC
    ADC f:TC_B
    STA f:TC_V                  ; its roll
    CLC
    ADC f:TC_SV
    STA f:TC_SV
    LDA f:TC_V
    SEC
    SBC f:TC_ABS
    BEQ :+
    BPL :++
:   LDA #1                      ; at least 1 gets through
:   STA f:TC_X1
    CLC
    ADC f:TC_SXV
    STA f:TC_SXV
    LDA f:TC_RN
    CMP f:TC_RR
    BCC @extra
    SBC f:TC_RR                 ; Q dice
    STA f:TC_RN
    BRA @next
  @extra:
    ADC f:TC_KR                 ; Q + 1 dice (the carry is clear)
    STA f:TC_RN
    INY
    LDA f:TC_V
    CLC
    ADC f:TC_SD1
    STA f:TC_SD1
    LDA f:TC_X1
    CLC
    ADC f:TC_SX1
    STA f:TC_SX1
  @next:
    INX
    TXA
    CMP f:TC_LAST
    BEQ @share
    BCC @share
    TYA
    STA f:TC_EXTRA

    LDA f:TC_QQ                 ; SD = Q * the rolls + the extras' ...
    STA f:TC_MA
    LDA f:TC_SV
    STA f:TC_MB
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_SD1
    STA f:TC_SD
    LDA f:TC_SXV                ; ...and SX the same
    STA f:TC_MB
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_SX1
    STA f:TC_SX
    TXA                         ; the dice counted: Q a share and the extras
    STA f:TC_MB
    JSR tac_mul
    LDA #256
    SEC
    SBC f:TC_PR
    SEC
    SBC f:TC_EXTRA
    BEQ @done                   ; none left: every roll under the cap
    STA f:TC_MA                 ; the rest roll 255
    XBA
    AND #$FF00
    SEC
    SBC f:TC_MA                 ; * 255
    CLC
    ADC f:TC_SD
    STA f:TC_SD
    LDA #255
    SEC
    SBC f:TC_ABS
    BNE :+
    LDA #1
:   STA f:TC_MB
    JSR tac_mul
    LDA f:TC_PR
    CLC
    ADC f:TC_SX
    STA f:TC_SX
  @done:
    PLX
    RTS
  @capped:
    LDA #255 * 256              ; B 255: every die rolls 255
    STA f:TC_SD
    LDA #255
    SEC
    SBC f:TC_ABS
    BNE :+
    LDA #1
:   XBA
    AND #$FF00
    STA f:TC_SX
    PLX
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_spell -- each slot's score for the spell in TC_EFF..TC_SHR
;;
;;  An ailment: no use if the slot has all it gives already, else its
;;  chance -- 148, nothing if the element is resisted, plus the spell's hit
;;  rate, less magic defense, at least 0, against a roll 0-200 where 200
;;  misses.  SLOW: no use on a slot slowed already (its multiplier 0), else
;;  the same chance.  XXXX and STUN: sure on a slot at 300 HP or under that
;;  does not resist and has not got it, else no use.  A damage spell: its
;;  share of HP, as tac_damage has it.  Anything else: every slot alike.
;;  Native, entered and left in emulation.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_spell:
    .a8
    .i8
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDX #0
  @slot:
    LDA f:TC_LIVE, X
    BNE :+
    JMP @next
:   LDA f:TC_EFF
    CMP #MAGEFF_AILMENT
    BEQ @ailment
    CMP #MAGEFF_SLOW
    BEQ @slow
    CMP #MAGEFF_AILMENT2
    BEQ @ailment2
    CMP #MAGEFF_DAMAGE
    BNE @alike
    JSR tac_damage
    BRA @score
  @alike:
    LDA #256
    BRA @score
  @slow:
    LDA f:TC_MULT, X
    BEQ @score                  ; A = 0: as slow as it goes
    JSR tac_land
    BRA @score
  @ailment:
    LDA f:TC_AIL, X
    EOR #$FFFF
    AND f:TC_EFV
    BEQ @score                  ; A = 0: nothing new
    JSR tac_land
    BRA @score
  @ailment2:
    LDA f:TC_RES, X
    AND f:TC_ELEM
    BNE @none
    LDA f:TC_AIL, X
    EOR #$FFFF
    AND f:TC_EFV
    BEQ @score
    LDA f:TC_HP, X
    CMP #AILMENT2_HP + 1
    BCS @none
    LDA #256
    BRA @score
  @none:
    LDA #0
  @score:
    STA f:TC_U, X
  @next:
    INX
    INX
    CPX #8
    BEQ :+
    JMP @slot
:   SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS


;;  The spell's chance at slot X, as dice of 256: CalcElemHitChance and
;;  PrepHitAndDamage's hit chance against Random_0_200.  A16 X16, X kept.
tac_land:
    .a16
    .i16
    LDA f:TC_RES, X
    AND f:TC_ELEM
    BEQ :+
    LDA #0                      ; resisted: no base chance
    BRA :++
:   LDA #MAG_BASEHIT
:   CLC
    ADC f:TC_SHR
    SEC
    SBC f:TC_MD, X
    BCS :+
    LDA #0
:   JMP tac_count


;;  A damage spell at slot X: BtlMag_Effect_Damage's roll, E + die * (E+1)
;;  / 256 with E the effectivity, halved if the element is resisted, and
;;  doubled on a crit -- the hit chance's dice, CC.  E 255 is always 255:
;;  RandAX's range is X + 1, and 256 is 0 in a byte.  The score is 256 times
;;  the share of HP it can expect to take, a crit's share and a plain one's
;;  weighed by CC.  A16 X16, X kept.
tac_damage:
    .a16
    .i16
    LDA f:TC_HP, X
    BNE :+
    LDA #256
    RTS
:   CMP #HP_CAP + 1
    BCC :+
    LDA #HP_CAP
:   STA f:TC_DEN
    JSR tac_land
    STA f:TC_CC
    LDA f:TC_EFV
    STA f:TC_B
    LDA f:TC_RES, X
    AND f:TC_ELEM
    BEQ :+
    LDA f:TC_B
    LSR A
    STA f:TC_B
:   PHX
    LDA #0
    STA f:TC_S1
    STA f:TC_S1 + 2
    STA f:TC_S2
    STA f:TC_S2 + 2
    LDA f:TC_B
    INC A
    STA f:TC_BP1                ; 1 to 256
    LDX #0
  @die:
    LDA f:TC_BP1
    CMP #256
    BNE :+
    LDA #0                      ; E 255: RandAX's range wraps to 0
    BRA :++
:   TXA
    XBA
    ORA f:TC_BP1
    STA a:WRMPYA
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    XBA
    AND #$00FF
:   CLC
    ADC f:TC_B                  ; the roll
    TAY
    CMP f:TC_DEN                ; plain, to at most the HP...
    BCC :+
    LDA f:TC_DEN
:   CLC
    ADC f:TC_S1
    STA f:TC_S1
    LDA f:TC_S1 + 2
    ADC #0
    STA f:TC_S1 + 2
    TYA
    ASL A                       ; ...and a crit's
    CMP f:TC_DEN
    BCC :+
    LDA f:TC_DEN
:   CLC
    ADC f:TC_S2
    STA f:TC_S2
    LDA f:TC_S2 + 2
    ADC #0
    STA f:TC_S2 + 2
    INX
    CPX #256
    BNE @die
    PLX

    LDA f:TC_S1                 ; each as a score: sum / HP, 256 at most
    STA f:TC_NUM
    LDA f:TC_S1 + 2
    STA f:TC_NUM + 2
    JSR tac_ratio
    STA f:TC_U1
    LDA f:TC_S2
    STA f:TC_NUM
    LDA f:TC_S2 + 2
    STA f:TC_NUM + 2
    JSR tac_ratio
    STA f:TC_U2
    SEC                         ; plain, and CC/256 of the way to a crit's
    SBC f:TC_U1
    STA f:TC_MB
    LDA f:TC_CC
    STA f:TC_MA
    JSR tac_mul
    LDA f:TC_PR + 1
    CLC
    ADC f:TC_U1
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tac_pick -- the slot, from the scores
;;
;;  Clever weighs each slot by vanilla's weight times its score; Ruthless,
;;  by vanilla's weight if its score is the best and not 0.  Nothing weighs
;;  anything: the roll's slot.  One slot weighs: that one.  Else a battle
;;  die over the total.  Entered and left in emulation; out A = the slot.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
tac_pick:
    .a8
    .i8
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA #0
    STA f:TC_Q                  ; the best score
    LDX #0
  @best:
    LDA f:TC_U, X
    CMP f:TC_Q
    BCC :+
    STA f:TC_Q
:   INX
    INX
    CPX #8
    BNE @best

    LDA #0
    STA f:TC_TOT
    TAY                         ; slots weighed
    LDX #0
  @weigh:
    LDA f:TC_U, X
    BEQ @weight                 ; A = 0: no use, never chosen
    LDA f:TC_MODE
    CMP #BOSSAI_RUTHLESS
    BNE @clever
    LDA f:TC_U, X
    CMP f:TC_Q
    BNE @nil
    LDA f:TACTICSFAR + lut_TacSlotW, X
    BRA @counted
  @clever:
    LDA f:TACTICSFAR + lut_TacSlotW, X
    STA f:TC_MA
    LDA f:TC_U, X
    STA f:TC_MB
    JSR tac_mul
    LDA f:TC_PR                 ; 1024 at most
    BRA @counted
  @nil:
    LDA #0
    BRA @weight
  @counted:
    INY
  @weight:
    STA f:TC_W, X
    CLC
    ADC f:TC_TOT
    STA f:TC_TOT
    INX
    INX
    CPX #8
    BNE @weigh

    CPY #1
    BEQ @only
    BCS @roll
    SEP #$30                    ; nothing to weigh: the roll's own
    .a8
    .i8
    SEC
    XCE
    LDA f:TC_VAN
    RTS
  @only:
    .a16
    .i16
    LDX #0
  : LDA f:TC_W, X
    BNE @found
    INX
    INX
    BRA :-

  @roll:
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    JSR BattleRNG_L             ; the battle's own die
    CLC
    XCE
    REP #$30
    .a16
    .i16
    AND #$00FF
    STA f:TC_MA
    LDA f:TC_TOT
    STA f:TC_MB
    JSR tac_mul                 ; die * total / 256: under the total
    LDA f:TC_PR + 1
    STA f:TC_Q
    LDA #0
    LDX #0
  : CLC
    ADC f:TC_W, X
    CMP f:TC_Q
    BEQ :+
    BCS @found                  ; the first whose running total passes it
:   INX
    INX
    BRA :--
  @found:
    TXA
    LSR A
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS

;  Vanilla's weights, eighths: GetRandomPlayerTarget's four ranges.
lut_TacSlotW:  .WORD 4, 2, 1, 1


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Arithmetic.  A16 X16 throughout, X kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  A = a chance against a roll 0-200 (RandAX's, die * 201 / 256), 200 a
;;  miss.  Out: A = the dice of 256 whose roll is at or under it.
tac_count:
    .a16
    .i16
    CMP #199
    BCC :+
    LDA #255                    ; all but the 200
    RTS
:   PHX
    TAX
    LDA f:TACTICSFAR + lut_TacHits, X
    AND #$00FF
    PLX
    RTS

;  For a chance h of 0-198: the dice whose roll is at or under it, those
;  with die * 201 < (h + 1) * 256.
lut_TacHits:
  .repeat 199, h
    .BYTE ((h + 1) * 256 + 200) / 201
  .endrep

;;  TC_PR = TC_MA * TC_MB: a byte times a word, from two 8x8 products --
;;  24 bits, the fourth byte 0.
tac_mul:
    .a16
    SEP #$20
    .a8
    LDA f:TC_MA
    STA a:WRMPYA
    LDA f:TC_MB
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    REP #$20
    .a16
    LDA a:RDMPYL
    STA f:TC_PR
    LDA #0
    STA f:TC_PR + 2
    SEP #$20
    .a8
    LDA f:TC_MB + 1
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    REP #$20
    .a16
    LDA a:RDMPYL
    CLC
    ADC f:TC_PR + 1             ; no carry out: 255 * 65535 is under 2^24,
    STA f:TC_PR + 1             ;   so the top byte stays 0
    RTS

;;  A = min(256, TC_NUM / TC_DEN): TC_NUM 24 bits with its top byte clear,
;;  TC_DEN under 32768.
tac_ratio:
    .a16
    LDA f:TC_NUM + 1
    CMP f:TC_DEN
    BCC tac_div
    LDA #256
    RTS

;;  A = TC_NUM / TC_DEN, which must be under 256: TC_NUM >> 8 under TC_DEN,
;;  TC_DEN under 32768, TC_NUM's top byte clear.  Long division, a bit of
;;  the low byte at a time.  TC_NUM is used up.
tac_div:
    .a16
    .i16
    PHX
    LDA #0
    STA f:TC_Q
    LDX #8
  @bit:
    LDA f:TC_NUM
    ASL A
    STA f:TC_NUM
    LDA f:TC_NUM + 2
    ROL A
    STA f:TC_NUM + 2
    LDA f:TC_Q
    ASL A
    STA f:TC_Q
    LDA f:TC_NUM + 1
    CMP f:TC_DEN
    BCC :+
    SBC f:TC_DEN
    STA f:TC_NUM + 1
    LDA f:TC_Q
    ORA #1
    STA f:TC_Q
:   DEX
    BNE @bit
    LDA f:TC_Q
    PLX
    RTS
