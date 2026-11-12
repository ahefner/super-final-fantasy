; ---------------------------------------------------------------------------
;  bstdetail.inc -- the Bestiary's detail view, included by bestiary.asm.
;
;  A on a defeated enemy (user, 2026-11-12): its page -- the picture full
;  size at the upper left, the name and eleven stats in a column at the
;  right, and across the bottom what it is weak to, resists and is, what
;  its hit inflicts, and its script with how often it uses each half.  B
;  goes back to the grid, the hand where it was; the music plays on
;  throughout.  A on one not defeated is the game's error sound.
;
;  The page is the world's enemy, as a battle would load it: its record,
;  touch and script from the randomizer's tables (rando_bsttables made them
;  at the screen's start if the cache was cold), scaled by the battle's own
;  code (opt_bstscale: the enemy's rolls, the dials as they are), gold and
;  experience as the end of a battle scales them.
;
;  The grid stays as it is beneath: the page is a second BG3 tilemap
;  (VR_DMAP) in the font's characters (BG3 $80-$FF, the game's own codes,
;  loaded at the start), and the picture is sprites, its characters in the
;  OBJ sheet's rows 2-13 -- so going back is three registers, three colours
;  and the sprites.  BG1 is off while the page shows.  Text colours are BG3
;  palettes 0-3, each a colour 3: palette 0's is the line's white, and
;  1-3's, CGRAM 7, 11 and 15, are the grid's (palette 0's groups 2-4) and
;  are kept and put back.
;
;  The layout is the mock-up the user passed (2026-11-12), 30 x 26 in the
;  safe area: the picture's box columns 1-14, rows 2-13; the name at column
;  16 of row 1 and the stats on rows 3-13; from row 15 a label column at 1
;  and the values from 11, wrapping by words.  The last row any enemy uses
;  is 25 (Wizard Vampire's): a script's spells and skills take two rows
;  each at most, whatever the shuffles deal.
; ---------------------------------------------------------------------------

ST_DETAIL = 4

RDCGRAM   = $213B
VR_DMAP   = $5C00               ; BG3's second tilemap, the page
VR_FONT   = VR_BG3CHR + $80 * 8 ; the font: BG3 characters $80-$FF
OBJ_PIC   = 32                  ; the picture's first OBJ character
OBJ_PICPAL = 2                  ; ...and its OBJ palette
OBJ_PICATTR = $30 | (OBJ_PICPAL << 1)
TM_GRID   = $15                 ; BG1, BG3, sprites
TM_PAGE   = $14                 ; BG3, sprites

D_ROWS    = 28
PAGE_PRI  = $2000               ; BG3 in front
PAL_VAL   = PAGE_PRI | (0 << 10)  ; the values: white
PAL_LBL   = PAGE_PRI | (1 << 10)  ; the labels
PAL_HEAD  = PAGE_PRI | (2 << 10)  ; the name
PAL_DIM   = PAGE_PRI | (3 << 10)  ; "nothing"
COL_LBL   = $76D2               ; (150, 176, 232)
COL_HEAD  = $333E               ; (240, 200, 96)
COL_DIM   = $45EF               ; (120, 120, 140)

STATCOL   = 16                  ; the column: the name and the stats' labels
STATEND   = 31                  ; ...one past the values' last column
BOTROW    = 15                  ; the bottom's first row
LBLCOL    = 1
VALCOL    = 11
VALEND    = 31                  ; the values' rows, 20 wide...
SCREND    = 30                  ; ...the script's, 19

ERR_FRAMES = 16

ITEMSFAR  = (CHUNK0 + BANK_ITEMS) * $10000
OPTWORKFAR = $7E0000 + OPTWORK
BSTSRAMFAR = CHUNK0 * $10000    ; SRAM: the option block
D_BTLREC  = OPTBTLENEMIES - OPTWORK

;  Direct page, the saved $80-$AF beside the conversion's.
DN        = $94                 ; 4: a product, a dividend, the quotient
DD        = $98                 ; 2: a multiplicand, a divisor
DR        = $9A                 ; 2: a multiplier, the remainder
DT2       = $9C                 ; 2
DMP       = $9E                 ; 2: the special's cells
DCH       = $A0                 ; a character
DCNT      = $A1
DPTR      = $A2                 ; 3: a name, long

;  The variables, beside the grid's.
V_DE      = BV+$88              ; the enemy on the page
V_WX      = BV+$89              ; the next character's column...
V_WY      = BV+$8A              ; ...and row
V_WFIRST  = BV+$8B              ; nonzero: the line has no word yet
V_WPAL    = BV+$8C              ; 2: the tilemap entries' colour bits
V_WLEN    = BV+$8E              ; BST_DWORD's length
V_ERR     = BV+$8F              ; frames of the error sound left
V_DW      = BV+$90              ; the picture's width, characters
V_DH      = BV+$91              ; ...and height
V_DSENT   = BV+$92              ; its 2KB pieces sent
V_DSPEL   = BV+$93              ; the script's spells
V_DSKIL   = BV+$94              ; ...and skills
V_DY      = BV+$95              ; the bottom's next row
V_DY0     = BV+$96              ; a script half's first row
V_WEND    = BV+$97              ; one past a line's last column
V_DI      = BV+$98
V_DBITS   = BV+$99              ; a mask being listed
V_DTX     = BV+$9A
V_DTY     = BV+$9B
V_DPX     = BV+$9C              ; the picture's x...
V_DPY     = BV+$9D              ; ...and y
V_DLEN    = BV+$9E              ; 2: its characters' bytes
V_DGAP    = BV+$A0              ; 2: the sheet's bytes past a row of it
V_DMAGP   = BV+$A2              ; 2: magic, percent of turns
V_DSKLP   = BV+$A4              ; 2: skills, percent
V_DCG     = BV+$A6              ; 6: CGRAM 7, 11 and 15, the grid's
.assert V_DCG + 6 <= V_ZPSAVE, error, "the detail view's variables run into the saved direct page"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  At the screen's start: the font, and the enemies' tables.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  The font into BG3 $80-$FF, in forced blank: each glyph's colour 3 --
;;  both planes, as the font has it -- and nothing else, so the menu box's
;;  fill round each is gone; then the three the font lacks over $F0-$F2.
;;  A8 I16.
    .a8
    .i16
bst_fontchr:
    LDA #$80
    STA a:VMAIN
    REP #$20
    .a16
    LDA #VR_FONT
    STA a:VMADDL
    SEP #$20
    .a8
    LDX #$0000
  @tile:
    LDA #8
    STA DCNT
  @row:
    LDA f:MENUCHR, X
    AND f:MENUCHR + 8, X
    STA a:VMDATAL
    STA a:VMDATAH
    INX
    DEC DCNT
    BNE @row
    REP #$20
    .a16
    TXA
    CLC
    ADC #8                      ; past the second plane
    TAX
    SEP #$20
    .a8
    PHX
    JSR bst_audio
    PLX
    CPX #128 * 16
    BCC @tile
    REP #$20
    .a16
    LDA #VR_FONT + (CH_LPAREN - $80) * 8
    STA a:VMADDL
    SEP #$20
    .a8
    LDX #$0000
  @own:
    LDA lut_BstGlyphs, X
    STA a:VMDATAL
    STA a:VMDATAH
    INX
    CPX #3 * 8
    BCC @own
    RTS

;;  The enemies' tables, if the cache does not hold this game's: the
;;  randomizer's steps, the music's turn after each.  A8 I16.
    .a8
    .i16
bst_tables:
    LDA #BST_TICKFRAME
    STA f:OWS_TICKON            ; the deals' draws tick the music (bst_tick)
    LDA #0
  @step:
    SEP #$30
    .i8
    SEC
    XCE
    JSL rando_bsttables + RANDOFAR
    CLC
    XCE
    REP #$10
    .i16
    PHA
    JSR bst_audio
    PLA
    BNE @step
    STA f:OWS_TICKON            ; (A is zero)
    RTS

;;  bst_tick -- from rando_yield when a vblank has begun while the
;;  enemies' tables build for this screen (OWS_TICKON = BST_TICKFRAME), as
;;  ows_tick is the map edit screen's: the frame's music -- or the error
;;  sound's -- and the HAL's frame of sound.  From native code, any widths,
;;  by JSL; everything kept.
bst_tick:
    PHP
    REP #$30
    .a16
    .i16
    PHA
    PHX
    PHY
    PHB
    PHD
    LDA #$0000
    TCD
    SEP #$30
    .a8
    .i8
    PHK
    PLB
    LDA cur_bank
    PHA
    SEC
    XCE
    LDA #CHUNK_BESTIARY
    STA cur_bank                ; CallMusicPlay comes back through it
    LDA f:V_ERR
    BEQ :+
    JSR bst_errframe
    BRA :++
:   JSR CallMusicPlay
:   JSL hal_audioframe + HALFAR
    PLA
    STA cur_bank
    CLC
    XCE
    REP #$30
    .a16
    .i16
    PLD
    PLB
    PLY
    PLX
    PLA
    PLP
    RTL
    .a8


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  A, B and the error sound.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  A on the grid: the page, built and sent a frame at a time -- the
;;  music's turns throughout -- and then shown at once.  A8 I16.
    .a8
    .i16
bst_detail:
    LDA f:V_SEL
    JSR bst_seen
    LDA f:V_SEEN
    BNE :+
    JMP bst_sfxerr
:   JSR bst_sfxsel
    LDA f:V_SEL
    STA f:V_DE
    JSR bst_dgather
    JSR bst_audio
    JSR bst_dtext
    JSR bst_audio
    JSR bst_dpicture
    LDA #0
    STA f:V_DSENT
  @pic:
    JSR bst_wait
    JSR bst_dsendpic
    PHP
    JSR bst_playframe
    PLP
    BCC @pic
    JSR bst_wait
    JSR bst_dsendmap
    JSR bst_playframe
    JSR bst_wait
    JSR bst_don
    JSR bst_playframe
    LDA #ST_DETAIL
    STA f:V_STATE
    RTS

;;  The page's pad: B goes back.  A8 I16.
    .a8
    .i16
bst_dinput:
    LDA f:V_PREV
    EOR #$FF
    AND joy
    STA f:V_TMP                 ; pressed since last frame
    LDA joy
    STA f:V_PREV
    LDA f:V_TMP
    AND #PAD_B
    BNE :+
    RTS
:   JSR bst_sfxsel
    JSR bst_wait
    JSR bst_doff
    JSR bst_playframe
    LDA #ST_IDLE
    STA f:V_STATE
    LDA #0
    STA f:V_HOLD
    RTS

;;  The game's error sound, as the map edit and seed screens play it
;;  (ows_sfxerr, whose note says why): PlaySFX_Error's writes, its sixteen
;;  frames struck by bst_playframe in place of the music's, the screen
;;  going on.  A8 I16 in and out.
    .a8
    .i16
bst_sfxerr:
    SEP #$30
    .i8
    SEC
    XCE
    LDA #1
    STA sq2_sfx                 ; square 2 the sound's, as PlaySFX_Error marks it
    LDA #$30
    wAPU $00                    ; square 1 silenced
    wAPU $08                    ; the triangle's linear reload, as the game writes it
    wAPU $0C                    ; the noise silenced
    LDA #ERR_FRAMES
    STA f:V_ERR
    CLC
    XCE
    REP #$10
    .i16
    RTS

;;  A frame of the error sound, in emulation mode (bst_playframe's): its
;;  @Frame, and after the last its silence.
    .a8
    .i8
bst_errframe:
    DEC A
    STA f:V_ERR
    LDA #%10001100              ; 50% duty, decaying, length on...
    wAPU $04
    LDA #%10001001              ; ...sweeping up, fast, in large steps...
    wAPU $05
    LDA #$80
    wAPU $06                    ; ...from $080...
    LDA #$00
    wAPU $07                    ; ...struck again
    LDA f:V_ERR
    BNE :+
    LDA #$30                    ; the last: square 2 silenced, its period zeroed
    wAPU $04
    LDA #$00
    wAPU $06
:   RTS
    .i16


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The enemy as the world has it, scaled.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  V_DE's record into BST_DREC, its touch over the record's -- the element
;;  the one the battle uses, the touch's under Weapon Stats and the
;;  weakness otherwise (opt_scaleatk) -- its script into BST_DSCR, the
;;  scaling, and the turns' shares.  A8 I16.
    .a8
    .i16
bst_dgather:
    LDA f:V_DE
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    STA DT2                     ; x 4
    ASL A
    ASL A
    CLC
    ADC DT2                     ; x 20
    TAX
    SEP #$20
    .a8
    LDY #$0000
  @rec:
    LDA f:RW_ENEMIES, X
    PHX
    TYX
    STA f:BST_DREC, X
    PLX
    INX
    INY
    CPY #ENEMY_RECORD
    BCC @rec
    ;  The touch.
    LDA f:V_DE
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    SEP #$20
    .a8
    LDA f:RW_TOUCH + 1, X
    STA f:BST_DREC + ENROMSTAT_ATTACKAIL
    LDA f:BSTSRAMFAR + OPTFB_WEAPONSTATS
    AND #OPTFM_WEAPONSTATS
    BEQ @weak
    LDA f:RW_TOUCH, X
    BRA :+
  @weak:
    LDA f:BST_DREC + ENROMSTAT_ELEMWEAK
:   STA f:BST_DREC + ENROMSTAT_UNKNOWN_E
    ;  The script, and how many spells and skills it holds.
    LDA #0
    STA f:V_DSPEL
    STA f:V_DSKIL
    LDA f:V_DE
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:RW_ESCRIPT, X
    CMP #$FF
    BEQ @scaled
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    SEP #$20
    .a8
    LDY #$0000
  @scr:
    LDA f:RW_SCRIPTS, X
    PHX
    TYX
    STA f:BST_DSCR, X
    PLX
    INX
    INY
    CPY #16
    BCC @scr
    LDX #$0000
  @count:
    LDA f:BST_DSCR + 2, X
    CMP #$FF
    BEQ :+
    LDA f:V_DSPEL
    INC A
    STA f:V_DSPEL
:   CPX #4
    BCS :+
    LDA f:BST_DSCR + 11, X
    CMP #$FF
    BEQ :+
    LDA f:V_DSKIL
    INC A
    STA f:V_DSKIL
:   INX
    CPX #8
    BCC @count
  @scaled:
    JSR bst_dscale
    JSR bst_audio
    JSR bst_dreward
    JMP bst_drates

;;  The battle's scaling of BST_DREC (opt_bstscale), through the battle's
;;  buffer: OPTWORK kept round it, so the title's scratch is as it was.
;;  A8 I16.
    .a8
    .i16
bst_dscale:
    LDX #$0000
  @keep:
    LDA f:OPTWORKFAR, X
    STA f:BST_DOPT, X
    INX
    CPX #$100
    BCC @keep
    LDX #$0000
  @in:
    LDA f:BST_DREC, X
    STA f:OPTWORKFAR + D_BTLREC, X
    INX
    CPX #ENEMY_RECORD
    BCC @in
    SEP #$30
    .i8
    SEC
    XCE
    LDA f:V_DE
    JSL opt_bstscale + OPTFAR
    CLC
    XCE
    REP #$10
    .i16
    LDX #$0000
  @out:
    LDA f:OPTWORKFAR + D_BTLREC, X
    STA f:BST_DREC, X
    INX
    CPX #ENEMY_RECORD
    BCC @out
    LDX #$0000
  @back:
    LDA f:BST_DOPT, X
    STA f:OPTWORKFAR, X
    INX
    CPX #$100
    BCC @back
    RTS

;;  Gold and experience as the end of a battle scales them
;;  (opt_scalereward): times the setting's halves, halved, pegged at $FFFF.
;;  A8 I16.
    .a8
    .i16
bst_dreward:
    LDX #ENROMSTAT_EXP
    JSR @one
    LDX #ENROMSTAT_GP
  @one:
    REP #$20
    .a16
    LDA f:BST_DREC, X
    STA DD
    LDA f:BSTSRAMFAR + OPT_GOLDXP
    AND #$00FF
    PHX
    JSR bst_mul
    PLX
    LSR DN + 2
    ROR DN
    LDA DN + 2
    BEQ :+
    LDA #$FFFF
    STA DN
:   LDA DN
    STA f:BST_DREC, X
    SEP #$20
    .a8
    RTS

;;  The shares of the turns: EnemyAi_ShouldPerformAction's roll is 0-128,
;;  and the rate does it when the roll is below it, so a rate r is r/129 of
;;  the turns, 129 or more every turn.  Magic is rolled first, and skills
;;  only when it fails: of the turns, magic m/129, skills (129-m)/129 *
;;  k/129 -- m 0 when the script has no spells.  Percent, rounded half up.
;;  A8 I16.
    .a8
    .i16
bst_drates:
    LDA f:V_DSPEL
    BEQ :+
    LDA f:BST_DSCR
    CMP #129
    BCC :+
    LDA #129
:   REP #$20
    .a16
    AND #$00FF
    STA DT2                     ; m, 0 without spells
    LDA #200                    ; round(100 m / 129) = (200 m + 129) / 258
    STA DD
    LDA DT2
    JSR bst_mul
    LDA #129
    JSR bst_addn
    LDA #258
    STA DD
    JSR bst_div
    LDA DN
    STA f:V_DMAGP
    LDA #129
    SEC
    SBC DT2
    STA DD                      ; (129 - m) * k ...
    SEP #$20
    .a8
    LDA f:BST_DSCR + 1
    CMP #129
    BCC :+
    LDA #129
:   REP #$20
    .a16
    AND #$00FF
    JSR bst_mul
    LDA DN
    STA DD                      ; ...and round(100 * that / 16641)
    LDA #200
    JSR bst_mul
    LDA #16641
    JSR bst_addn
    LDA #33282
    STA DD
    JSR bst_div
    LDA DN
    STA f:V_DSKLP
    SEP #$20
    .a8
    RTS

;;  DN (32 bits) = DD * A.  A16 I16; Y and DR clobbered.
    .a16
    .i16
bst_mul:
    STA DR
    STZ DN
    STZ DN + 2
    LDY #16
  @bit:
    ASL DN
    ROL DN + 2
    ASL DR
    BCC @next
    LDA DN
    CLC
    ADC DD
    STA DN
    BCC @next
    INC DN + 2
  @next:
    DEY
    BNE @bit
    RTS

;;  DN += A.  A16.
bst_addn:
    CLC
    ADC DN
    STA DN
    BCC :+
    INC DN + 2
:   RTS

;;  DN = DN / DD, 32 bits by 16, the remainder in DR.  A16 I16; Y
;;  clobbered.
bst_div:
    STZ DR
    LDY #32
  @bit:
    ASL DN
    ROL DN + 2
    ROL DR
    LDA DR
    BCS @sub                    ; past 16 bits: past the divisor
    CMP DD
    BCC @next
  @sub:
    SBC DD                      ; (C set either way)
    STA DR
    INC DN                      ; the quotient's bit
  @next:
    DEY
    BNE @bit
    RTS
    .a8


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The page's text, into BST_DMAP.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_dtext:
    REP #$20
    .a16
    LDA #0
    LDX #$0000
  @clear:
    STA f:BST_DMAP, X
    INX
    INX
    CPX #D_ROWS * 64
    BCC @clear
    SEP #$20
    .a8
    JSR bst_audio
    ;  The name.
    LDY #PAL_HEAD
    LDA #STATCOL
    LDX #1
    JSR bst_dat
    JSR bst_dname
    ;  The stats, a row each.
    LDA #0
    STA f:V_DI
  @stat:
    LDA f:V_DI
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    TAX
    LDA lut_BstDStat + 2, X     ; its place in the record, and its width
    STA f:V_DTX
    LDA lut_BstDStat, X
    PHA                         ; its label
    SEP #$20
    .a8
    LDA f:V_DI
    CLC
    ADC #3
    TAX
    LDA #STATCOL
    LDY #PAL_LBL
    JSR bst_dat
    PLX
    JSR bst_dstr
    LDA f:V_DTY                 ; nonzero: two bytes
    STA DCNT
    LDA f:V_DTX
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA f:BST_DREC, X
    STA DD
    SEP #$20
    .a8
    LDA DCNT
    REP #$20                    ; (Z kept)
    .a16
    BNE :+
    LDA DD
    AND #$00FF
    BRA :++
:   LDA DD
:   JSR bst_dnum
    SEP #$20
    .a8
    LDA f:V_DI
    CLC
    ADC #3
    TAX
    LDA #STATEND
    SEC
    SBC f:V_WLEN
    LDY #PAL_VAL
    JSR bst_dat
    JSR bst_dwordput
    JSR bst_audio
    LDA f:V_DI
    INC A
    STA f:V_DI
    CMP #DSTATS
    BCS :+
    JMP @stat
:   ;  The bottom: the elements, the kind, the touch.
    LDA #BOTROW
    STA f:V_DY
    LDX #S_WEAK
    JSR bst_dline
    LDA f:BST_DREC + ENROMSTAT_ELEMWEAK
    JSR bst_delems
    JSR bst_dlineend
    LDX #S_RESISTS
    JSR bst_dline
    LDA f:BST_DREC + ENROMSTAT_ELEMRESIST
    JSR bst_delems
    JSR bst_dlineend
    LDA f:BST_DREC + ENROMSTAT_CATEGORY
    BEQ @touch
    LDX #S_KIND
    JSR bst_dline
    LDA f:BST_DREC + ENROMSTAT_CATEGORY
    LDX #lut_BstDKinds
    JSR bst_dbits
    JSR bst_dlineend
  @touch:
    LDA f:BST_DREC + ENROMSTAT_ATTACKAIL
    BEQ @script
    LDX #S_INFLICTS
    JSR bst_dline
    LDA f:BST_DREC + ENROMSTAT_ATTACKAIL
    LDX #lut_BstDAilments
    JSR bst_dbits
    LDA f:BST_DREC + ENROMSTAT_UNKNOWN_E
    BEQ :+
    JSR bst_dbracket
:   JSR bst_dlineend
    ;  The script: a row's gap, then each half it has.
  @script:
    LDA f:V_DSPEL
    ORA f:V_DSKIL
    BNE :+
    RTS
:   LDA f:V_DY
    INC A
    STA f:V_DY
    LDA f:V_DSPEL
    BEQ @skills
    LDX #S_MAGIC
    REP #$20
    .a16
    LDA f:V_DMAGP
    SEP #$20
    .a8
    JSR bst_dscript
    LDA #2
    STA f:V_DI                  ; the slot, 2-9
  @spell:
    LDA f:V_DI
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:BST_DSCR, X
    CMP #$FF
    BEQ :+
    CLC
    ADC #$B0                    ; its name, the item names' spells
    LDX #lut_ItemNamePtrTbl
    JSR bst_dname8
    JSR bst_dword
    JSR bst_audio
:   LDA f:V_DI
    INC A
    STA f:V_DI
    CMP #10
    BCC @spell
    JSR bst_dscriptend
  @skills:
    LDA f:V_DSKIL
    BNE :+
    RTS
:   LDX #S_SKILLS
    REP #$20
    .a16
    LDA f:V_DSKLP
    SEP #$20
    .a8
    JSR bst_dscript
    LDA #11
    STA f:V_DI                  ; the slot, 11-14
  @skill:
    LDA f:V_DI
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:BST_DSCR, X
    CMP #$FF
    BEQ :+
    LDX #lut_EnemyAttack
    JSR bst_dname8
    JSR bst_dword
    JSR bst_audio
:   LDA f:V_DI
    INC A
    STA f:V_DI
    CMP #15
    BCC @skill
    JMP bst_dscriptend

;;  The writing place: column A, row X, colours Y.  A8 I16.
    .a8
    .i16
bst_dat:
    STA f:V_WX
    TXA
    STA f:V_WY
    REP #$20
    .a16
    TYA
    STA f:V_WPAL
    SEP #$20
    .a8
    RTS

;;  Character A at the writing place, which moves on.  Off the tilemap,
;;  nothing.  A8 I16; X and Y kept.
    .a8
    .i16
bst_dput:
    STA DCH
    LDA f:V_WX
    CMP #32
    BCS @next
    LDA f:V_WY
    CMP #D_ROWS
    BCS @next
    PHX
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA DT2
    LDA f:V_WX
    AND #$00FF
    CLC
    ADC DT2
    ASL A
    TAX
    LDA DCH
    AND #$00FF
    ORA f:V_WPAL
    STA f:BST_DMAP, X
    SEP #$20
    .a8
    PLX
  @next:
    LDA f:V_WX
    INC A
    STA f:V_WX
    RTS

;;  The string at X (this chunk: its length, then its characters) at the
;;  writing place.  A8 I16.
    .a8
    .i16
bst_dstr:
    LDA a:0, X
    STA DCNT
  @c:
    INX
    LDA a:0, X
    JSR bst_dput
    DEC DCNT
    BNE @c
    RTS

;;  BST_DWORD's V_WLEN characters at the writing place.  A8 I16.
    .a8
    .i16
bst_dwordput:
    LDX #$0000
  @c:
    TXA
    CMP f:V_WLEN
    BCS @done
    LDA f:BST_DWORD, X
    JSR bst_dput
    INX
    BRA @c
  @done:
    RTS

;;  BST_DWORD as the line's next word: after a space, or at the start of the
;;  next row if it would pass V_WEND.  A8 I16.
    .a8
    .i16
bst_dword:
    LDA f:V_WFIRST
    BNE @first
    LDA f:V_WX
    SEC                         ; the space
    ADC f:V_WLEN
    CMP f:V_WEND
    BEQ @fits
    BCC @fits
    LDA f:V_WY
    INC A
    STA f:V_WY
    LDA #VALCOL
    STA f:V_WX
    BRA @put
  @fits:
    LDA f:V_WX
    INC A
    STA f:V_WX
    BRA @put
  @first:
    LDA #0
    STA f:V_WFIRST
  @put:
    JMP bst_dwordput

;;  The string at X as the line's next word.  A8 I16.
    .a8
    .i16
bst_dstrword:
    LDA a:0, X
    STA f:V_WLEN
    STA DCNT
    LDY #$0000
  @c:
    INX
    LDA a:0, X
    PHX
    TYX
    STA f:BST_DWORD, X
    PLX
    INY
    DEC DCNT
    BNE @c
    JMP bst_dword

;;  A line of the bottom: its label at the left of row V_DY, the writing
;;  place at the values' column.  X the label.  A8 I16.
    .a8
    .i16
bst_dline:
    PHX
    LDA f:V_DY
    TAX
    LDA #LBLCOL
    LDY #PAL_LBL
    JSR bst_dat
    PLX
    JSR bst_dstr
    LDA f:V_DY
    TAX
    LDA #VALCOL
    LDY #PAL_VAL
    JSR bst_dat
    LDA #1
    STA f:V_WFIRST
    LDA #VALEND
    STA f:V_WEND
    RTS

;;  The next line below the one written; the music's turn.  A8 I16.
bst_dlineend:
    LDA f:V_WY
    INC A
    STA f:V_DY
    JMP bst_audio

;;  A script half: its label at row V_DY, its share under it a column in,
;;  the words from the values' column, 19 wide.  X the label, A16 = the
;;  share (A8 on entry with the high byte in B).  A8 I16.
    .a8
    .i16
bst_dscript:
    PHX
    REP #$20
    .a16
    JSR bst_dnum
    SEP #$20
    .a8
    LDA f:V_WLEN
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA #$E0                    ; %
    STA f:BST_DWORD, X
    INX
    TXA
    STA f:V_WLEN
    LDA f:V_DY
    STA f:V_DY0
    INC A
    TAX
    LDA #LBLCOL + 1
    LDY #PAL_VAL
    JSR bst_dat
    JSR bst_dwordput
    LDA f:V_DY
    TAX
    LDA #LBLCOL
    LDY #PAL_LBL
    JSR bst_dat
    PLX
    JSR bst_dstr
    LDA f:V_DY
    TAX
    LDA #VALCOL
    LDY #PAL_VAL
    JSR bst_dat
    LDA #1
    STA f:V_WFIRST
    LDA #SCREND
    STA f:V_WEND
    RTS

;;  After a script half: the next row past both its words and its share.
;;  A8.
bst_dscriptend:
    LDA f:V_WY
    INC A
    STA f:V_DY
    LDA f:V_DY0
    INC A
    INC A
    CMP f:V_DY
    BCC :+
    STA f:V_DY
:   RTS

;;  An element mask as words: "nothing" dim, "everything", six or more as
;;  "all but" the rest, else each.  A8 I16.
    .a8
    .i16
bst_delems:
    STA f:V_DBITS
    CMP #0
    BNE :+
    REP #$20
    .a16
    LDA #PAL_DIM
    STA f:V_WPAL
    SEP #$20
    .a8
    LDX #S_NOTHING
    JMP bst_dstrword
:   CMP #$FF
    BNE :+
    LDX #S_EVERYTHING
    JMP bst_dstrword
:   LDX #$0000                  ; its bits
    LDY #8
  @count:
    LSR A
    BCC :+
    INX
:   DEY
    BNE @count
    CPX #6
    BCS :+
    LDA f:V_DBITS
    LDX #lut_BstDElems
    JMP bst_dbits
:   LDX #S_ALL
    JSR bst_dstrword
    LDX #S_BUT
    JSR bst_dstrword
    LDA f:V_DBITS
    EOR #$FF
    STA f:V_DBITS
    LDA #1
    STA DCNT                    ; the first: no "and"
    LDY #$0000
  @rest:
    LDA f:V_DBITS
    LSR A
    STA f:V_DBITS
    BCC @skip
    LDA DCNT
    BNE :+
    PHY
    LDX #S_AND
    JSR bst_dstrword
    PLY
:   LDA #0
    STA DCNT
    PHY
    LDX lut_BstDElems, Y
    JSR bst_dstrword
    PLY
  @skip:
    INY
    INY
    CPY #16
    BCC @rest
    RTS

;;  Mask A's bits as words, bit 0 first, the names a table of eight string
;;  addresses at X.  A8 I16.
    .a8
    .i16
bst_dbits:
    STA f:V_DBITS
    STX DMP
    LDY #$0000
  @bit:
    LDA f:V_DBITS
    LSR A
    STA f:V_DBITS
    BCC @skip
    PHY
    REP #$20
    .a16
    LDA (DMP), Y
    TAX
    SEP #$20
    .a8
    JSR bst_dstrword
    PLY
  @skip:
    INY
    INY
    CPY #16
    BCC @bit
    RTS

;;  The touch's element after its ailment: each in words, the first with
;;  "(" before it and the last with ")" after.  A = the mask.  A8 I16.
    .a8
    .i16
bst_dbracket:
    STA f:V_DBITS
    LDA #1
    STA DCNT                    ; the first
    LDY #$0000
  @bit:
    LDA f:V_DBITS
    LSR A
    STA f:V_DBITS
    BCC @skip
    PHY
    REP #$20
    .a16
    LDA lut_BstDElems, Y
    TAX
    SEP #$20
    .a8
    LDY #$0000
    LDA DCNT
    BEQ :+
    LDA #CH_LPAREN
    STA f:BST_DWORD
    INY
:   LDA a:0, X                  ; the name, after it
    STA DT2
  @c:
    INX
    LDA a:0, X
    PHX
    TYX
    STA f:BST_DWORD, X
    PLX
    INY
    DEC DT2
    BNE @c
    LDA f:V_DBITS
    BNE :+                      ; the last
    LDA #CH_RPAREN
    TYX
    STA f:BST_DWORD, X
    INY
:   TYA
    STA f:V_WLEN
    LDA #0
    STA DCNT
    JSR bst_dword
    PLY
  @skip:
    INY
    INY
    CPY #16
    BCC @bit
    RTS

;;  The enemy's name, eight characters at most, at the writing place.  A8
;;  I16.
    .a8
    .i16
bst_dname:
    LDA f:V_DE
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:NAMESFAR, X
    STA DPTR
    SEP #$20
    .a8
    LDA #NAMEBANK
    STA DPTR + 2
    LDY #$0000
  @c:
    LDA [DPTR], Y
    BEQ @done
    JSR bst_dput
    INY
    CPY #8
    BCC @c
  @done:
    RTS

;;  Name A of the pointer table at X in the items' bank (the spells' and
;;  the skills') into BST_DWORD, eight at most, its trailing spaces off.
;;  A8 I16.
    .a8
    .i16
bst_dname8:
    REP #$20
    .a16
    AND #$00FF
    ASL A
    STX DT2
    CLC
    ADC DT2
    TAX
    LDA f:ITEMSFAR & $FF0000, X
    STA DPTR
    SEP #$20
    .a8
    LDA #^ITEMSFAR
    STA DPTR + 2
    LDY #$0000
  @c:
    LDA [DPTR], Y
    BEQ @end
    TYX
    STA f:BST_DWORD, X
    INY
    CPY #8
    BCC @c
  @end:
    DEY
    BMI @done
    TYX
    LDA f:BST_DWORD, X
    CMP #$FF
    BEQ @end
  @done:
    INY
    TYA
    STA f:V_WLEN
    RTS

;;  A16's decimal digits into BST_DWORD, no leading zeros, V_WLEN their
;;  count.  A16 I16 in, A8 out.
    .a16
    .i16
bst_dnum:
    STA DN
    LDX #$0000                  ; digits so far
    LDY #$0000                  ; the power
  @pow:
    STZ DT2
  @sub:
    LDA DN
    CMP lut_BstPow, Y
    BCC @digit
    SBC lut_BstPow, Y
    STA DN
    INC DT2
    BRA @sub
  @digit:
    LDA DT2
    BNE @put
    CPX #0
    BEQ @next                   ; a leading zero
  @put:
    SEP #$20
    .a8
    LDA DT2
    ORA #$80
    STA f:BST_DWORD, X
    REP #$20
    .a16
    INX
  @next:
    INY
    INY
    CPY #8
    BCC @pow
    SEP #$20
    .a8
    LDA DN                      ; the ones, always
    ORA #$80
    STA f:BST_DWORD, X
    INX
    TXA
    STA f:V_WLEN
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The picture: its characters into BST_CONV as the OBJ sheet's rows from
;;  2 (sixteen to a row, its cells the first of each), its colours into
;;  BST_DPCG, its sprites into BST_OAM.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_dpicture:
    LDA f:V_DE
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA #0
    STA f:BST_DPCG + 6          ; no second palette, unless a special's
    STA f:BST_DPCG + 8
    STA f:BST_DPCG + 10
    SEP #$20
    .a8
    LDA lut_BstPalA, X
    LDY #0
    JSR bst_dpal
    LDA lut_BstKind, X
    CMP #KIND_SPECIAL
    BNE :+
    JMP @big
:   CMP #KIND_SMALL
    BNE :+
    LDA #4
    BRA :++
:   LDA #6
:   STA f:V_DW
    STA f:V_DH
    JSR bst_dgap
    ;  Its characters, one after another in the CHR, each in colours 1-3.
    LDA f:V_DE
    REP #$20
    .a16
    AND #$00FF
    STA DT2
    ASL A
    ADC DT2                     ; x 3
    TAX
    LDA lut_BstSrc, X
    STA SRC
    CLC
    ADC #8
    STA SRC8
    SEP #$20
    .a8
    LDA lut_BstSrc + 2, X
    STA SRC + 2
    STA SRC8 + 2
    LDX #$0000
    LDY #$0000
    LDA f:V_DH
    STA f:V_DTY
  @row:
    LDA f:V_DW
    STA f:V_DTX
  @tile:
    JSR bst_convg0
    PHX
    PHY
    JSR bst_audio
    PLY
    PLX
    LDA f:V_DTX
    DEC A
    STA f:V_DTX
    BNE @tile
    JSR bst_dnextrow
    LDA f:V_DTY
    DEC A
    STA f:V_DTY
    BNE @row
    JMP bst_doam

    ;  A fiend or Chaos: its cells as battle's nametable has them, each in
    ;  its attribute's palette's colours, 1-3 or 4-6.
  @big:
    LDA lut_BstPalB, X
    LDY #6
    JSR bst_dpal
    LDA f:V_DE
    SEC
    SBC #BST_BIGFIRST
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstBigOf, X
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstBigW, X
    STA f:V_DW
    LDA lut_BstBigH, X
    STA f:V_DH
    REP #$20
    .a16
    TXA
    ASL A
    TAY
    LDA lut_BstBigAt, Y
    CLC
    ADC #.LOWORD(lut_BstBigMap)
    STA DMP
    TXA
    ASL A
    STA DT2
    TXA
    CLC
    ADC DT2                     ; x 3
    TAX
    LDA lut_BstBigSet, X
    STA SRC
    CLC
    ADC #8
    STA SRC8
    SEP #$20
    .a8
    LDA lut_BstBigSet + 2, X
    STA SRC + 2
    STA SRC8 + 2
    JSR bst_dgap
    LDX #$0000
    LDA f:V_DH
    STA f:V_DTY
  @brow:
    LDA f:V_DW
    STA f:V_DTX
  @btile:
    LDA (DMP)
    REP #$20
    .a16
    INC DMP
    SEP #$20
    .a8
    CMP #0
    BEQ @blank
    PHA
    REP #$20
    .a16
    AND #$007F
    ASL A
    ASL A
    ASL A
    ASL A
    TAY                         ; the tile in its set
    SEP #$20
    .a8
    PLA
    BMI :+
    JSR bst_convg0
    BRA @done
:   JSR bst_convg1
    BRA @done
  @blank:
    LDY #32
  @zero:
    STA f:BST_CONV, X
    INX
    DEY
    BNE @zero
  @done:
    PHX
    JSR bst_audio
    PLX
    LDA f:V_DTX
    DEC A
    STA f:V_DTX
    BNE @btile
    JSR bst_dnextrow
    LDA f:V_DTY
    DEC A
    STA f:V_DTY
    BNE @brow
    JMP bst_doam

;;  V_DGAP: the sheet's bytes past a row of the picture's characters;
;;  V_DLEN: the rows' bytes, sixteen characters a row.  A8 I16.
    .a8
    .i16
bst_dgap:
    LDA #16
    SEC
    SBC f:V_DW
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:V_DGAP
    LDA f:V_DH
    AND #$00FF
    XBA
    ASL A                       ; x 512
    STA f:V_DLEN
    SEP #$20
    .a8
    RTS

;;  X past the rest of the sheet's row.  A8 I16.
    .a8
    .i16
bst_dnextrow:
    REP #$20
    .a16
    TXA
    CLC
    ADC f:V_DGAP
    TAX
    SEP #$20
    .a8
    RTS

;;  Battle palette A's colours 1-3 into BST_DPCG + Y.  A8 I16; X kept.
    .a8
    .i16
bst_dpal:
    PHX
    STY DT2
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    INC A
    TAX                         ; its colour 1
    SEP #$20
    .a8
    LDA #3
    STA DCNT
  @c:
    LDA f:BTLPALFAR, X
    REP #$20
    .a16
    AND #$003F
    ASL A
    TAY
    LDA lut_BstNesCol, Y
    PHX
    LDX DT2
    STA f:BST_DPCG, X
    INX
    INX
    STX DT2
    PLX
    INX
    SEP #$20
    .a8
    DEC DCNT
    BNE @c
    PLX
    RTS

;;  BST_OAM: every sprite under the picture and large, the hand's too; then
;;  the picture's, 16 x 16 each, centred in the box of columns 1-14 and
;;  rows 2-13.  A8 I16.
    .a8
    .i16
bst_doam:
    REP #$20
    .a16
    LDX #$0000
  @hide:
    LDA #224 << 8               ; x 0, y 224
    STA f:BST_OAM, X
    LDA #0
    STA f:BST_OAM + 2, X
    INX
    INX
    INX
    INX
    CPX #512
    BCC @hide
  @large:
    LDA #$AAAA
    STA f:BST_OAM, X
    INX
    INX
    CPX #544
    BCC @large
    SEP #$20
    .a8
    LDA f:V_DW
    ASL A
    ASL A
    STA DCH
    LDA #64                     ; 8 + (112 - 8w) / 2
    SEC
    SBC DCH
    STA f:V_DPX
    LDA f:V_DH
    ASL A
    ASL A
    STA DCH
    LDA #64                     ; 16 + (96 - 8h) / 2
    SEC
    SBC DCH
    STA f:V_DPY
    LDA #OBJ_PIC
    STA DCNT                    ; the row's first character
    LDX #4                      ; sprite 1
    LDA f:V_DH
    LSR A
    STA f:V_DTY
  @row:
    LDA f:V_DW
    LSR A
    STA f:V_DTX
    LDA f:V_DPX
    STA DCH
    LDA DCNT
    STA DT2
  @spr:
    LDA DCH
    STA f:BST_OAM, X
    LDA f:V_DPY
    STA f:BST_OAM + 1, X
    LDA DT2
    STA f:BST_OAM + 2, X
    LDA #OBJ_PICATTR
    STA f:BST_OAM + 3, X
    INX
    INX
    INX
    INX
    LDA DCH
    CLC
    ADC #16
    STA DCH
    LDA DT2
    CLC
    ADC #2
    STA DT2
    LDA f:V_DTX
    DEC A
    STA f:V_DTX
    BNE @spr
    LDA f:V_DPY
    CLC
    ADC #16
    STA f:V_DPY
    LDA DCNT
    CLC
    ADC #32
    STA DCNT
    LDA f:V_DTY
    DEC A
    STA f:V_DTY
    BNE @row
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The vblanks: the picture's characters, the page's tilemap, the switch
;;  and the switch back.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  The picture's next 2KB at most into the OBJ sheet.  C set once all are.
    .a8
    .i16
bst_dsendpic:
    LDA f:V_DSENT
    REP #$20
    .a16
    AND #$00FF
    XBA
    ASL A
    ASL A
    ASL A                       ; x 2048
    STA DT2
    CLC
    ADC #.LOWORD(BST_CONV)
    STA a:A1T0L
    LDA DT2
    LSR A
    CLC
    ADC #VR_OBJCHR + OBJ_PIC * 16
    STA a:VMADDL
    LDA f:V_DLEN
    SEC
    SBC DT2
    CMP #TILES_PER_VBL
    BCC :+
    LDA #TILES_PER_VBL
:   STA a:DAS0L
    CLC
    ADC DT2
    STA DT2                     ; sent, after this
    SEP #$20
    .a8
    JSR bst_dmago
    LDA f:V_DSENT
    INC A
    STA f:V_DSENT
    REP #$20
    .a16
    LDA DT2
    CMP f:V_DLEN                ; C set: all of it
    SEP #$20
    .a8
    RTS

;;  The page's tilemap.
    .a8
    .i16
bst_dsendmap:
    REP #$20
    .a16
    LDA #VR_DMAP
    STA a:VMADDL
    LDA #.LOWORD(BST_DMAP)
    STA a:A1T0L
    LDA #D_ROWS * 64
    STA a:DAS0L
    SEP #$20
    .a8
    JMP bst_dmago

;;  The page on: the grid's three colours kept and the text's in their
;;  place, the picture's colours, the sprites, BG3 the page's, BG1 off.
    .a8
    .i16
bst_don:
    LDX #$0000
  @keep:
    LDA lut_BstDCgAt, X
    STA a:CGADD
    PHX
    REP #$20
    .a16
    TXA
    ASL A
    TAX
    SEP #$20
    .a8
    LDA a:RDCGRAM
    STA f:V_DCG, X
    LDA a:RDCGRAM
    STA f:V_DCG + 1, X
    PLX
    LDA lut_BstDCgAt, X
    STA a:CGADD
    PHX
    REP #$20
    .a16
    TXA
    ASL A
    TAX
    LDA lut_BstDCg, X
    SEP #$20
    .a8
    STA a:CGDATA
    XBA
    STA a:CGDATA
    PLX
    INX
    CPX #3
    BCC @keep
    LDA #128 + OBJ_PICPAL * 16 + 1
    STA a:CGADD
    LDX #$0000
  @pic:
    LDA f:BST_DPCG, X
    STA a:CGDATA
    INX
    CPX #12
    BCC @pic
    STZ a:OAMADDL
    STZ a:OAMADDH
    REP #$20
    .a16
    LDA #.LOWORD(BST_OAM)
    STA a:A1T0L
    LDA #544
    STA a:DAS0L
    SEP #$20
    .a8
    LDA #^BST_OAM
    STA a:A1B0
    STZ a:DMAP0                 ; a byte at a time, the one register
    LDA #<OAMDATA
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    LDA #(VR_DMAP >> 8)
    STA a:BG3SC
    LDA #TM_PAGE
    STA a:TM
    RTS

;;  The page off: BG3 the line's, BG1 on, the grid's colours back, the
;;  picture's sprites under the screen, the hand.
    .a8
    .i16
bst_doff:
    LDA #(VR_BG3MAP >> 8)
    STA a:BG3SC
    LDA #TM_GRID
    STA a:TM
    LDX #$0000
  @cg:
    LDA lut_BstDCgAt, X
    STA a:CGADD
    PHX
    REP #$20
    .a16
    TXA
    ASL A
    TAX
    SEP #$20
    .a8
    LDA f:V_DCG, X
    STA a:CGDATA
    LDA f:V_DCG + 1, X
    STA a:CGDATA
    PLX
    INX
    CPX #3
    BCC @cg
    LDA #2                      ; sprite 1 on
    STA a:OAMADDL
    STZ a:OAMADDH
    LDX #127
  @hide:
    STZ a:OAMDATA
    LDA #224
    STA a:OAMDATA
    STZ a:OAMDATA
    STZ a:OAMDATA
    DEX
    BNE @hide
    LDA #$02                    ; the high table as the grid set it: the
    STA a:OAMDATA               ;   hand large, the rest small
    LDX #31
  @hi:
    STZ a:OAMDATA
    DEX
    BNE @hi
    JMP bst_sprites


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The page's data.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;  CGRAM 7, 11 and 15 -- BG3 palettes 1-3's colour 3 -- and the page's
;  colours for them: the labels, the name, "nothing".
lut_BstDCgAt:
  .BYTE 7, 11, 15
lut_BstDCg:
  .WORD COL_LBL, COL_HEAD, COL_DIM

lut_BstPow:
  .WORD 10000, 1000, 100, 10

;  The stats, each its label, its place in the record and its width (0 a
;  byte, 1 a word).
lut_BstDStat:
  .WORD S_HP
  .BYTE ENROMSTAT_HPMAX, 1
  .WORD S_DAMAGE
  .BYTE ENROMSTAT_DAMAGE, 0
  .WORD S_HITS
  .BYTE ENROMSTAT_NUMHITS, 0
  .WORD S_ACCURACY
  .BYTE ENROMSTAT_HITRATE, 0
  .WORD S_CRITICAL
  .BYTE ENROMSTAT_CRITRATE, 0
  .WORD S_ABSORB
  .BYTE ENROMSTAT_ABSORB, 0
  .WORD S_EVADE
  .BYTE ENROMSTAT_EVADE, 0
  .WORD S_MAGICDEF
  .BYTE ENROMSTAT_MAGDEF, 0
  .WORD S_MORALE
  .BYTE ENROMSTAT_MORALE, 0
  .WORD S_EXP
  .BYTE ENROMSTAT_EXP, 1
  .WORD S_GOLD
  .BYTE ENROMSTAT_GP, 1
DSTATS = (* - lut_BstDStat) / 4

;  The element bits' names, bit 0 first (FFR's SpellElement); the
;  ailments' (SpellStatus); the categories' (MonsterType).
lut_BstDElems:
  .WORD S_STATUS, S_POISON, S_TIME, S_DEATH, S_FIRE, S_ICE, S_LIGHTNING, S_EARTH
lut_BstDAilments:
  .WORD S_DEATH, S_STONE, S_POISON, S_BLIND, S_PARALYSIS, S_SLEEP, S_SILENCE, S_CONFUSION
lut_BstDKinds:
  .WORD S_MAGICAL, S_DRAGON, S_GIANT, S_UNDEAD, S_WERE, S_AQUATIC, S_MAGE, S_REGENERATES

.macro DSTR name, txt
name:
  .BYTE .strlen(txt)
  FFTEXT txt
.endmacro

DSTR S_HP, "HP"
DSTR S_DAMAGE, "Damage"
DSTR S_HITS, "Hits"
DSTR S_ACCURACY, "Accuracy"
DSTR S_CRITICAL, "Critical"
DSTR S_ABSORB, "Absorb"
DSTR S_EVADE, "Evade"
DSTR S_MAGICDEF, "Magic def"
DSTR S_MORALE, "Morale"
DSTR S_EXP, "Exp"
DSTR S_GOLD, "Gold"
DSTR S_WEAK, "Weak to"
DSTR S_RESISTS, "Resists"
DSTR S_KIND, "Kind"
DSTR S_INFLICTS, "Inflicts"
DSTR S_MAGIC, "Magic"
DSTR S_SKILLS, "Skills"
DSTR S_NOTHING, "nothing"
DSTR S_EVERYTHING, "everything"
DSTR S_ALL, "all"
DSTR S_BUT, "but"
DSTR S_AND, "and"
DSTR S_STATUS, "Status"
DSTR S_POISON, "Poison"
DSTR S_TIME, "Time"
DSTR S_DEATH, "Death"
DSTR S_FIRE, "Fire"
DSTR S_ICE, "Ice"
DSTR S_LIGHTNING, "Lightning"
DSTR S_EARTH, "Earth"
DSTR S_STONE, "Stone"
DSTR S_BLIND, "Blind"
DSTR S_PARALYSIS, "Paralysis"
DSTR S_SLEEP, "Sleep"
DSTR S_SILENCE, "Silence"
DSTR S_CONFUSION, "Confusion"
DSTR S_MAGICAL, "Magical"
DSTR S_DRAGON, "Dragon"
DSTR S_GIANT, "Giant"
DSTR S_UNDEAD, "Undead"
DSTR S_WERE, "Were"
DSTR S_AQUATIC, "Aquatic"
DSTR S_MAGE, "Mage"
DSTR S_REGENERATES, "Regenerates"
