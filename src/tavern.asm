; ---------------------------------------------------------------------------
;  tavern.asm -- Taverns: a town's clinic as a tavern, and its hire
;
;  FFR's Tavern Recruitment (Party.cs PubReplaceClinic; asm/0E Tavern
;  Mode.asm) as the Taverns row has it (user, 2026-11-02): Off; Recruit, a
;  hire takes a None's place; Replace, a None's or a party member's.  Each
;  town with a clinic hires out one class, the seed's (rando.asm's
;  deal_taverns).  The tavern asks Revive or Hire: Revive is the clinic as
;  it was; Hire takes the clinic's price for a new member of the town's
;  class, who comes up to the party's lowest level (user: "fun arbitrary
;  divergence from FFR behavior") and is named on the party creation
;  screen's name screen (user).  As FFR's: the old member's gear stays in
;  the slot, unequipped, the spells go, the class is promoted if Bahamut has
;  promoted the party, and the hire arrives with 1 HP, as a revive does.
;
;  The clinic is redecorated as FFR's tavern (user: full): its title reads
;  TAVERN, a table, barrels and a barkeeper are laid over its tiles from the
;  caravan's, the item shop's and the armour shop's, with the item shop's
;  colours, and the towns' clinic signs are pub signs (rando_mapedits).
;
;  Reached by JSL from bank $0E's shop and the fixed bank's shop loading,
;  emulation mode.  The shop's own routines are called back through
;  OptCallFar.  RAM and SRAM look the same from this chunk as from the
;  game's, so the visit runs with DBR = this chunk and reads its own tables
;  and the game's variables alike by absolute address.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nesio.inc"
.include "optcall.inc"
.include "fftext.inc"

.export tavern_clinic, tavern_title, tavern_shoppal
.export tav_make, tav_levelup           ; for tools/test_options.py

.import OptCallFar, DoNameInput, DrawShopBox, DrawShopComplexString
.import DrawShopDialogueBox, ShopFrameNoCursor, CommonShopLoop_Cmd
.import DrawInnClinicConfirm, ShopLoop_YesNo, DrawShopGoldBox, DrawShop
.import DrawShopString
.import LoadShopCHRPal, LoadMenuCHRPal, BattleRNG_L, StartingStatsOne
.import lut_LevelUpDataPtrs, lut_LvlUpMagDefBonus, lut_ExpToAdvance
.import opt_hitgrowth, opt_thiefgrowth
.import rando_tavern

.segment "BANK_TAVERN"

TAVBUF      = str_buf + $10         ; the strings drawn, as the clinic's list is
SHOPBOX_TALK = 0                    ; the shop's dialogue box...
SHOPBOX_CMD  = 3                    ; ...and its command box
SHOPSTR_POOR = $10                  ; "You can't afford that."
TAV_NAMEREC  = $30                  ; the ptygen record the name screen fills

;  Bank $09's shop tiles, 14 to a shop type, loaded at PPU $0000.
SHOPCHR      = (CHUNK0 + BANK_MENUCHR) * $10000 + lut_ShopCHR
SHOPTILES    = 14


;;  Z clear if Taverns is on; A = its field.
tav_on:
    LDA f:RANDO_SAVEFAR + (RANDO_NORUN - RANDO_SAVE)
    AND #TAVERNS_FIELD
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tavern_clinic -- EnterShop_Clinic's first instruction
;;
;;  Off, the clinic as it was: its first instruction, which this replaced,
;;  and C clear to go on.  On, the tavern: C set when the party leaves, so
;;  the clinic exits; C clear for Revive, which is the clinic from there.
;;  Revive's ends JMP back to EnterShop_Clinic, which brings the tavern up
;;  again.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

tavern_clinic:
    JSR tav_on
    BNE @tavern
    STA joy_a                   ; (A = 0) clear A and B, as the clinic did
    STA joy_b
    CLC
    RTL
  @tavern:
    PHB
    PHK
    PLB
    JSR tav_visit
    PLB                         ; leaves C alone
    RTL


;;  The menu: "Hire a <class>", and Revive or Hire.  Out: C set to leave,
;;  clear to revive.
tav_visit:
    LDA #0
    STA joy_a
    STA joy_b
    LDA cur_map
    JSL rando_tavern + RANDOFAR ; this town's class
    STA TAVCLS
    LDA #<str_Greet
    LDX #>str_Greet
    JSR tav_copy
    LDA #$02                    ; ...and its class's name, as the party
    STA TAVBUF, Y               ;   creation screen draws it
    INY
    LDA TAVCLS
    CLC
    ADC #$F0
    STA TAVBUF, Y
    INY
    LDA #$00
    STA TAVBUF, Y
    LDA #SHOPBOX_TALK
    JSR tav_box
    LDA #<str_Commands
    LDX #>str_Commands
    JSR tav_copy
    LDA #SHOPBOX_CMD
    JSR tav_box
    LDA #2
    STA cursor_max
    CALL0E CommonShopLoop_Cmd
    BCS @leave                  ; B
    LDA cursor
    BNE @hire
    LDA #0                      ; Revive: the clinic's, as it was
    STA joy_a
    STA joy_b
    CLC
    RTS
  @hire:
    JSR tav_hire
    JMP tav_visit
  @leave:
    SEC
    RTS


;;  Hire: whose place, the price, the new member, a name.
tav_hire:
    ;  The slots it may take: every None, and under Replace every member.
    JSR tav_on
    CMP #TAVERNS_REPLACE << TAVERNS_SHIFT
    PHP                         ; Z: Replace
    LDX #$00                    ; X = the slot
    LDY #$00                    ; Y = into the list
    STY TAVN
  @slot:
    TXA
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA TAVK                    ; its record
    PLP
    PHP
    BEQ @may                    ; Replace: anyone
    STX TAVSLOT
    LDX TAVK
    LDA ch_class, X
    LDX TAVSLOT
    CMP #CLS_NONE
    BNE @next
  @may:
    TXA
    PHX
    LDX TAVN
    STA TAVSLOTS, X
    INC TAVN
    PLX
    TXA
    CLC
    ADC #$10                    ; the slot's stat code: its name, or "None"
    STA TAVBUF, Y
    INY
    STX TAVSLOT
    LDX TAVK
    LDA ch_class, X
    LDX TAVSLOT
    CMP #CLS_NONE
    LDA #$00                    ; the name
    BCC :+
    LDA #$01                    ; a None's: its class, which reads "None"
:   STA TAVBUF, Y
    INY
    LDA #$01                    ; a blank line between
    STA TAVBUF, Y
    INY
  @next:
    INX
    CPX #4
    BCC @slot
    PLP
    LDA TAVN
    BNE @list
    LDA #<str_Full              ; Recruit with no None: no room
    LDX #>str_Full
    JSR tav_say
    JMP tav_wait
  @list:
    DEY
    LDA #$00
    STA TAVBUF, Y               ; the last blank line ends it
    LDA #SHOPBOX_CMD
    JSR tav_box
    LDA #<str_Who
    LDX #>str_Who
    JSR tav_say
    LDA TAVN
    STA cursor_max
    CALL0E CommonShopLoop_Cmd
    BCC :+
    RTS                         ; B: the menu again
:   LDX cursor
    LDA TAVSLOTS, X
    STA TAVSLOT

    CALL0E DrawInnClinicConfirm ; the clinic's price
    CALL0E ShopLoop_YesNo
    BCS @back
    LDA cursor
    BNE @back                   ; No
    JSR tav_afford
    BCC @back

    JSR tav_make
    JSR tav_name
    LDA #<str_Welcome
    LDX #>str_Welcome
    JSR tav_say
    JMP tav_wait
  @back:
    RTS


;;  The price against the party's gold: C set and paid, the gold box
;;  redrawn; or C clear, the shop's "You can't afford that." said.  The
;;  clinic's own check (InnClinic_CanAfford) leaves its caller's caller when
;;  it says no, so it is not called here.
tav_afford:
    LDA gold + 2
    BNE @yes
    LDA gold + 1
    CMP item_box + 1
    BCC @no
    BNE @yes
    LDA gold
    CMP item_box
    BCC @no
  @yes:
    LDA gold
    SEC
    SBC item_box
    STA gold
    LDA gold + 1
    SBC item_box + 1
    STA gold + 1
    LDA gold + 2
    SBC #0
    STA gold + 2
    CALL0E DrawShopGoldBox
    SEC
    RTS
  @no:
    SET0E DrawShopDialogueBox
    LDA #SHOPSTR_POOR
    JSL OptCallFar + BANK0EFAR
    JSR tav_wait
    CLC
    RTS


;;  Frames until A or B.
tav_wait:
    LDA #0
    STA joy_a
    STA joy_b
  @frame:
    CALL0E ShopFrameNoCursor
    LDA joy_a
    ORA joy_b
    BEQ @frame
    RTS


;;  Copy the string at A (low) / X (high), in this chunk, to TAVBUF.  Out:
;;  Y = its terminator's index.
tav_copy:
    STA text_ptr
    STX text_ptr + 1
    LDY #$FF
  @char:
    INY
    LDA (text_ptr), Y
    STA TAVBUF, Y
    BNE @char
    RTS

;;  The string at A / X said in the dialogue box.
tav_say:
    JSR tav_copy
    LDA #SHOPBOX_TALK
    ;  fall into tav_box

;;  Box A drawn, and TAVBUF in it.
tav_box:
    PHA
    SET0E DrawShopBox
    PLA
    JSL OptCallFar + BANK0EFAR
    LDA #<TAVBUF
    STA text_ptr
    LDA #>TAVBUF
    STA text_ptr + 1
    CALL0E DrawShopComplexString
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tav_make -- the hire, in TAVSLOT's place, of TAVCLS
;;
;;  Its level is the party's lowest, Nones aside, as the party stood (the
;;  member it replaces counts).  The class's starting stats, as New Game
;;  loads them -- Better Thief and Ninja's agility included -- then a level
;;  up at a time to there, as a battle's would (tav_levelup), and the
;;  experience that level takes.  The slot's gear stays, unequipped; its
;;  spells and MP go; its name is the name screen's (tav_name).
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

tav_make:
    LDA #50 - 1
    STA TAVLOW
    LDX #$C0
  @low:
    LDA ch_class, X
    CMP #CLS_NONE
    BEQ :+
    LDA ch_level, X
    CMP TAVLOW
    BCS :+
    STA TAVLOW
:   TXA
    SEC
    SBC #$40
    TAX
    BCS @low

    LDA TAVSLOT
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX                         ; X = its record, all the way down
    STA lvlup_chstats
    STA lvlup_chmagic
    LDA #>ch_stats
    STA lvlup_chstats + 1
    LDA #>ch_magicdata
    STA lvlup_chmagic + 1

    LDA TAVCLS
    STA ch_class, X
    LDA #$00
    STA ch_ailments, X
    LDY #ch_weapons - ch_stats  ; its gear kept, none of it equipped
  @gear:
    LDA (lvlup_chstats), Y
    AND #$7F
    STA (lvlup_chstats), Y
    INY
    CPY #ch_weapons - ch_stats + 8
    BCC @gear
    LDA #$00
    LDY #ch_substats - ch_stats ; damage .. magic defense, as no gear makes them
  @sub:
    STA (lvlup_chstats), Y
    INY
    CPY #ch_magdef - ch_stats + 1
    BCC @sub
    LDY #$3F                    ; no spells, no MP
  @magic:
    STA (lvlup_chmagic), Y
    DEY
    BPL @magic
    STA ch_exp, X
    STA ch_exp + 1, X
    STA ch_exp + 2, X
    STA ch_level, X

    PHB                         ; New Game's starting stats, from bank $00's
    LDA #CHUNK0 + BANK_STARTINGSTATS
    PHA
    PLB
    JSR StartingStatsOne
    PLB

    LDA game_flags + OBJID_BAHAMUT
    AND #GMFLG_EVENT
    BEQ :+
    LDA ch_class, X             ; promoted, as the party has been
    CLC
    ADC #6
    STA ch_class, X
:
    LDA TAVLOW
    STA TAVK
  @up:
    LDA TAVK
    BEQ @exp
    JSR tav_levelup
    DEC TAVK
    BRA @up

  @exp:
    ;  The experience its level takes, lut_ExpToAdvance[level - 1] -- none
    ;  at level 1 -- in TAVSLOTS, done with...
    LDA #$00
    STA TAVSLOTS
    STA TAVSLOTS + 1
    STA TAVSLOTS + 2
    LDA TAVLOW
    BEQ @have
    PHX
    ASL A
    CLC
    ADC TAVLOW                  ; three bytes a level
    TAX
    LDA f:BANK0BFAR + lut_ExpToAdvance - 3, X
    STA TAVSLOTS
    LDA f:BANK0BFAR + lut_ExpToAdvance - 2, X
    STA TAVSLOTS + 1
    LDA f:BANK0BFAR + lut_ExpToAdvance - 1, X
    STA TAVSLOTS + 2
    PLX
  @have:
    LDA TAVSLOTS
    STA ch_exp, X
    LDA TAVSLOTS + 1
    STA ch_exp + 1, X
    LDA TAVSLOTS + 2
    STA ch_exp + 2, X
    ;  ...and what the next level takes beyond it, as the status screen
    ;  shows; none at 50.
    LDA #$00
    STA TAVK
    STA TAVN
    LDA TAVLOW
    CMP #50 - 1
    BCS @tonext
    PHX
    ASL A
    CLC
    ADC TAVLOW
    TAX
    LDA f:BANK0BFAR + lut_ExpToAdvance, X
    SEC
    SBC TAVSLOTS
    STA TAVK
    LDA f:BANK0BFAR + lut_ExpToAdvance + 1, X
    SBC TAVSLOTS + 1
    STA TAVN
    PLX
  @tonext:
    LDA TAVK
    STA ch_exptonext, X
    LDA TAVN
    STA ch_exptonext + 1, X

  @hp:
    LDA #1                      ; 1 HP, as FFR's hire and a revive
    STA ch_curhp, X
    LDA #0
    STA ch_curhp + 1, X
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tav_levelup -- one level up, as a battle's, without its report
;;
;;  Bank $0B's LvlUp_LevelUp, line for line up to where it draws the report
;;  (Draw4EobBoxes) -- which outside a battle has nothing to draw on -- with
;;  its tables read from bank $0B and the cartridge's hooks into it called
;;  the same way: Thief and Ninja hit% (opt_hitgrowth) and Better Thief's
;;  agility (opt_thiefgrowth).  Its locals are the battle's scratch, as the
;;  original's are; nothing else is using them out of battle.
;;  test_taverns holds it to the original, draw for draw.
;;
;;  In: lvlup_chstats, lvlup_chmagic.  X kept; A and Y not.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

LV_LEVIDX   = $6BAD                 ; the original's locals
LV_CLASS    = $6BAE                 ;   (its class sits in $688E, which the
LV_MPBITS   = $6BAF                 ;   stat byte then takes; apart here)
LV_STRONG   = $68B3
LV_LOOP     = $6856
LV_STATIDX  = $6858
LV_STATUP   = $6AAC                 ; 5
LV_PTR      = tmp + 13              ; 3: the class's level-up data, long

tav_levelup:
    PHX
    LDY #ch_level - ch_stats
    LDA (lvlup_chstats), Y
    CMP #50 - 1
    BCC :+
    JMP @out                    ; level 50: no more
:   STA LV_LEVIDX
    CLC
    ADC #1
    STA (lvlup_chstats), Y
    LDY #ch_class - ch_stats
    LDA (lvlup_chstats), Y
    STA LV_CLASS
    ASL A
    TAX
    ASL LV_LEVIDX               ; two bytes per level
    LDA f:BANK0BFAR + lut_LevelUpDataPtrs, X
    CLC
    ADC LV_LEVIDX
    STA LV_PTR
    LDA f:BANK0BFAR + lut_LevelUpDataPtrs + 1, X
    ADC #$00
    STA LV_PTR + 1
    LDA #^BANK0BFAR
    STA LV_PTR + 2
    LDY #$00
    LDA [LV_PTR], Y
    STA LVLUP_STATBYTE
    INY
    LDA [LV_PTR], Y
    STA LV_MPBITS

    LDX LV_CLASS
    LDY #ch_hitrate - ch_stats  ; hit rate
    LDA (lvlup_chstats), Y
    JSL opt_hitgrowth + OPTFAR
    JSR tav_cap200
    STA (lvlup_chstats), Y
    LDY #ch_magdef - ch_stats   ; magic defense
    LDA (lvlup_chstats), Y
    CLC
    ADC f:BANK0BFAR + lut_LvlUpMagDefBonus, X
    JSR tav_cap200
    STA (lvlup_chstats), Y

    LDA LV_CLASS                ; MP, but not for Fighters and Thieves
    BEQ @nomp
    CMP #CLS_TH
    BEQ @nomp
    LDA LV_MPBITS
    LDY #ch_maxmp - ch_magicdata
  @mpup:
    LSR A
    BCC :+
    PHA
    LDA (lvlup_chmagic), Y
    CLC
    ADC #$01
    STA (lvlup_chmagic), Y
    PLA
:   INY
    CPY #ch_maxmp - ch_magicdata + 8
    BNE @mpup
    LDA LV_CLASS
    CMP #CLS_KN
    BEQ :+
    CMP #CLS_NJ
    BEQ :+
    LDA #9 + 1
    BNE :++
:   LDA #4 + 1
:   LDY #ch_maxmp - ch_magicdata
  @mpcap:
    CMP (lvlup_chmagic), Y
    BNE :+
    PHA
    LDA (lvlup_chmagic), Y
    SEC
    SBC #$01
    STA (lvlup_chmagic), Y
    PLA
:   INY
    CPY #ch_maxmp - ch_magicdata + 8
    BNE @mpcap
  @nomp:

    LDY #ch_vit - ch_stats      ; HP: Vit/4 + 1, and 20-25 more on a
    LDA (lvlup_chstats), Y      ;   strong level
    LSR A
    LSR A
    CLC
    ADC #$01
    PHA
    LDA LVLUP_STATBYTE
    AND #$20
    BEQ @weak
    JSR BattleRNG_L             ; RandAX(20, 25): 20 + (r * 6) / 256
    STA LV_STRONG
    LDA #$00
    STA LV_LOOP                 ; (the product's high byte)
    LDY #6
    LDA #$00
  @times:
    CLC
    ADC LV_STRONG
    BCC :+
    INC LV_LOOP
:   DEY
    BNE @times
    LDA LV_LOOP
    CLC
    ADC #20
    JMP :+
  @weak:
    LDA #$00
:   STA LV_STRONG
    PLA
    CLC
    ADC LV_STRONG
    LDY #ch_maxhp - ch_stats    ; onto max HP, held under 1000
    CLC
    ADC (lvlup_chstats), Y
    STA (lvlup_chstats), Y
    INY
    LDA (lvlup_chstats), Y
    ADC #$00
    STA (lvlup_chstats), Y
    CMP #>1000
    BCC @hpok
    BNE @hpcap
    DEY
    LDA (lvlup_chstats), Y
    INY
    CMP #<1000
    BCC @hpok
  @hpcap:
    LDA #>999
    STA (lvlup_chstats), Y
    DEY
    LDA #<999
    STA (lvlup_chstats), Y
  @hpok:

    JSL opt_thiefgrowth + OPTFAR    ; the three ASLs, and Better Thief's agility
    LDA #$00
    STA LV_LOOP
    LDA #ch_str - ch_stats
    STA LV_STATIDX
  @stat:
    ASL LVLUP_STATBYTE
    BCC @chance
  @inc:
    LDA #$01
    BNE @apply
  @chance:
    JSR BattleRNG_L
    AND #$03
    BEQ @inc
    LDA #$00
  @apply:
    LDY LV_LOOP
    STA LV_STATUP, Y
    LDY LV_STATIDX
    CLC
    ADC (lvlup_chstats), Y
    CMP #100
    BEQ :+
    STA (lvlup_chstats), Y
:   INC LV_STATIDX
    INC LV_LOOP
    LDA LV_LOOP
    CMP #$05
    BNE @stat

    LDY #ch_str - ch_stats      ; damage: one for each two of strength
    LDA LV_STATUP + 0
    BEQ :+
    LDA (lvlup_chstats), Y
    LSR A
    BCS :+
    LDY #ch_dmg - ch_stats
    LDA (lvlup_chstats), Y
    CLC
    ADC #$01
    CMP #201
    BEQ :+
    STA (lvlup_chstats), Y
:   LDY #ch_evade - ch_stats    ; evade: one for each of agility
    LDA LV_STATUP + 1
    BEQ :+
    LDA (lvlup_chstats), Y
    CLC
    ADC #$01
    CMP #201
    BEQ :+
    STA (lvlup_chstats), Y
:
    ;  LvlUp_AdjustBBSubStats: a Black Belt or Master with no weapon has
    ;  absorb of their level and twice it in damage.
    LDY #ch_class - ch_stats
    LDA (lvlup_chstats), Y
    CMP #CLS_BB
    BEQ :+
    CMP #CLS_MA
    BNE @out
:   LDY #ch_weapons - ch_stats
  @armed:
    LDA (lvlup_chstats), Y
    BMI @out
    INY
    CPY #ch_weapons - ch_stats + 4
    BCC @armed
    LDY #ch_level - ch_stats
    LDA (lvlup_chstats), Y
    CLC
    ADC #$01
    LDY #ch_absorb - ch_stats
    STA (lvlup_chstats), Y
    ASL A
    LDY #ch_dmg - ch_stats
    STA (lvlup_chstats), Y
  @out:
    PLX
    RTS

tav_cap200:
    CMP #201
    BCC :+
    LDA #200
:   RTS


;;  The name screen for the hire (user: "since we can't name NONEs
;;  presently"), party creation's own, on ptygen's fourth record -- above
;;  the strings in str_buf, and the price is paid -- and the shop drawn
;;  again after it.
tav_name:
    LDA char_index
    PHA
    LDA #TAV_NAMEREC
    STA char_index
    LDA #$00
    wPPUMASK
    ;  The CHR loaders end by swapping to bank $0E whatever called them
    ;  (LoadBatSprCHRPalettes: "swap to bank E on exit"), so they are called
    ;  from there, through the trampoline, like the shop's own routines.
    CALL0E LoadMenuCHRPal
    CALL0E DoNameInput
    LDA TAVSLOT
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    LDY #$00
  @name:
    LDA ptygen_name + TAV_NAMEREC, Y
    STA ch_name, X
    INX
    INY
    CPY #4
    BCC @name
    PLA
    STA char_index
    LDA #$00
    wPPUMASK
    CALL0E LoadShopCHRPal
    CALL0E DrawShop
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tavern_title -- the shop's title, TAVERN for a tavern
;;
;;  DrawShop's "LDA shop_type / JSR DrawShopString", which this replaced.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

tavern_title:
    LDA shop_type
    CMP #SHOPTYPE_CLINIC
    BNE @plain
    JSR tav_on
    BEQ @plain
    PHB
    PHK
    PLB
    LDA #<str_Title
    LDX #>str_Title
    JSR tav_copy
    LDA #<TAVBUF
    STA text_ptr
    LDA #>TAVBUF
    STA text_ptr + 1
    CALL0E DrawShopComplexString
    PLB
    RTL
  @plain:
    SET0E DrawShopString
    LDA shop_type
    JSL OptCallFar + BANK0EFAR
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  tavern_shoppal -- a shop type's backdrop palette, and a tavern's tiles
;;
;;  LoadShopTypeAndPalette's "ASL A / ASL A / ORA #$40", which this
;;  replaced: the palette's offset for shop type A.  A tavern takes the item
;;  shop's, and FFR's three borrowings go over the clinic's tiles, the shop
;;  CHR having just loaded: the caravan's first four (a tablecloth), the
;;  item shop's next four (barrels) and the armour shop's last six (its
;;  armourer, tending bar).  The PPU is off, as it is for the shop's load.
;;  DBR is bank $00's and stays it.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

tavern_shoppal:
    CMP #SHOPTYPE_CLINIC
    BNE @plain
    JSR tav_on
    BEQ @clinic
    JSR tav_art
    LDA #SHOPTYPE_ITEM * 4 | $40
    RTL
  @clinic:
    LDA #SHOPTYPE_CLINIC
  @plain:
    ASL A
    ASL A
    ORA #$40
    RTL

tav_art:
    rPPUSTATUS
    LDA #>(SHOPTYPE_CLINIC * SHOPTILES * 16)
    wPPUADDR
    LDA #<(SHOPTYPE_CLINIC * SHOPTILES * 16)
    wPPUADDR
    LDX #$00
  @cloth:
    LDA f:SHOPCHR + SHOPTYPE_CARAVAN * SHOPTILES * 16, X
    wPPUDATA
    INX
    CPX #4 * 16
    BCC @cloth
    LDX #$00
  @barrels:
    LDA f:SHOPCHR + (SHOPTYPE_ITEM * SHOPTILES + 4) * 16, X
    wPPUDATA
    INX
    CPX #4 * 16
    BCC @barrels
    LDX #$00
  @keeper:
    LDA f:SHOPCHR + (SHOPTYPE_ARMOR * SHOPTILES + 8) * 16, X
    wPPUDATA
    INX
    CPX #6 * 16
    BCC @keeper
    RTS


;;  The tavern's words (drafts for the user, 2026-11-02).  The shop's boxes
;;  are seven columns inside.
str_Title:     FFTEXT "TAVERN"
               .BYTE $00
str_Greet:     FFTEXT "Hire a"
               .BYTE $05, $00           ; then the class's name
str_Commands:  FFTEXT "Revive"
               .BYTE $01
               FFTEXT "Hire"
               .BYTE $00
str_Who:       FFTEXT "Who"
               .BYTE $05
               FFTEXT "makes"
               .BYTE $05
               FFTEXT "room?"
               .BYTE $00
str_Full:      FFTEXT "Your"
               .BYTE $05
               FFTEXT "party"
               .BYTE $05
               FFTEXT "is"
               .BYTE $05
               FFTEXT "full."
               .BYTE $00
str_Welcome:   FFTEXT "Welcome"
               .BYTE $05
               FFTEXT "aboard!"
               .BYTE $00
