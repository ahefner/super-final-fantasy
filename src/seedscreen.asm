; ---------------------------------------------------------------------------
;  seedscreen.asm -- New Game's seed screen (menus.txt), in the settings
;  screen's chunk (CHUNK_OPTMENU): its background, description box, chirps,
;  release wait and frame are that engine's.
;
;  The seed the world will be built from, and a grid of the sixteen hex
;  digits to type another, as the game's name input has its letters (user):
;
;    - It shows the seed it is given, NGF_SEED -- latched from the pool by
;      the flow on the way in, or, back from party creation, the one chosen.
;    - A on a digit types it.  The first blanks the seed shown, the digits
;      not yet typed showing as dashes; the eighth hides the hand.
;    - B takes the last digit typed back, the hand showing again.  B on the
;      seed as given, or with nothing typed, goes back a screen.
;    - START goes on with the seed shown, or the one typed once all eight
;      are in; before then it plays the game's error sound.  With all eight
;      in, A goes on as well.
;
;  The hand moves as the name input's does, wrapping at each edge, with the
;  settings screen's chirps; A and B chirp as the game's menus do.  The
;  title's music plays on, and L + X / L + Y reset from it, through
;  WaitForVBlank_L as on the settings screen.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "fftext.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nesio.inc"
.include "optmenu.inc"

.export seed_choose
.import opt_menu_fillbg, opt_menu_drawdesc, opt_menu_desctext, opt_menu_breathe
.import opt_sfx_move, opt_sfx_sel, opt_waitrelease
.import lut_DescSeed
.import DrawCursor, ClearOAM, CallMusicPlay, UpdateJoy, WaitForVBlank_L

.segment "BANK_OPTMENU"

;  Where things are, in nametable cells: the heading, the seed centred
;  under it, and the grid, the three centred down the space above the
;  description box (user, 2026-10-22: the heading two rows down, the seed
;  and the grid one); the grid's digits four columns apart, so the hand,
;  two cells before its digit, stands clear of the one to its left.
SEED_HEADROW = OPTLIST_TOP + 2
SEED_HEADCOL = OPTLIST_COL + 2
SEED_ROW     = 5
SEED_COL     = 12               ; eight digits, columns 12-19
GRID_ROW     = 9                ; the grid's rows 9, 11, 13, 15
GRID_COL     = 10               ; ...and its columns 10, 14, 18, 22
GRID_DX      = 4
GRID_DY      = 2
.assert GRID_DX = 4 && GRID_DY = 2, error, "seed_cursor and seed_drawgrid multiply by shifting"

;  The screen's scratch, in the engine's (MENURAM), past the flow's.
SEED_SEL   = MENURAM + $20      ; the digit the hand is on, 0-15
SEED_N     = MENURAM + $21      ; how many are typed, 0-8, or SEED_SHOWN
SEED_ERR   = MENURAM + $22      ; the error sound's frames still to strike
SEED_DIG   = MENURAM + $23      ; 8 bytes: the digits, a nibble each, high first
SEED_SHOWN = $FF                ; nothing typed: the seed as given, shown
SEED_DIGITS = 8
.assert SEED_DIG + SEED_DIGITS <= MENURAM_END, error, "the seed screen's scratch runs past the engine's"

CHR_DASH = $C2                  ; fftext.inc's '-'


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  seed_choose -- the screen.  In: NGF_SEED the seed to show; NGF_TYPED
;;  nonzero if it was typed here before, when it comes back with all eight
;;  in and the hand hidden.  Out: A = NGNAV_FORWARD, NGF_SEED the seed chosen
;;  and NGF_TYPED set if it was typed; or NGNAV_BACK, NGF_SEED as it was.  The
;;  screen off, as the settings screen leaves it.  From the New Game flow, by
;;  JSL, emulation mode; X and Y not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

seed_choose:
    PHB
    PHK
    PLB
    JSR seed_unpack             ; the seed given, as digits
    LDA f:NGF_TYPED
    BEQ :+
    LDA #SEED_DIGITS            ; typed before: all eight in, the hand hidden
    BRA :++
:   LDA #SEED_SHOWN
:   STA f:SEED_N
    LDA #0
    STA f:SEED_SEL
    STA f:SEED_ERR

    LDA #$00
    wPPUMASK                    ; screen off while it is built
    JSL hal_clearnt + HALFAR
    JSR opt_menu_fillbg
    JSR seed_drawhead
    JSR seed_drawseed
    JSR seed_drawgrid
    JSR opt_menu_drawdesc       ; the description box, as the settings'
    LDA #<lut_DescSeed
    STA OPTMENU_DESC
    LDA #>lut_DescSeed
    STA OPTMENU_DESC + 1
    JSR opt_menu_desctext

    ;  The hand in place before the screen comes on, as opt_menu_screen
    ;  puts it, and for the same two breaths.
    LDA #$08
    STA soft2000                ; sprites from the right pattern table
    JSR opt_menu_breathe
    JSR seed_cursor
    LDA #>oam
    wOAMDMA
    JSR opt_menu_breathe
    LDA #$1E
    wPPUMASK                    ; ...and on
    JSR opt_waitrelease         ; the START that brought it carries no further

  @loop:
    JSR seed_cursor
    LDA #>oam
    wOAMDMA                     ; into the shadow before the flush, as the
    JSR WaitForVBlank_L         ;   settings screen sends its hand
    LDA #CHUNK_OPTMENU
    STA cur_bank                ; CallMusicPlay comes back through this
    JSR seed_music
    JSR UpdateJoy
    LDA joy                     ; down now and not down last frame
    EOR f:OPTMENU_PREV
    AND joy
    STA f:OPTMENU_EDGE
    LDA joy
    STA f:OPTMENU_PREV

    LDA f:OPTMENU_EDGE
    AND #PAD_B
    BNE @b
    LDA f:OPTMENU_EDGE
    AND #PAD_START
    BNE @start
    LDA f:OPTMENU_EDGE
    AND #PAD_A
    BNE @a
    LDA f:SEED_N
    CMP #SEED_DIGITS
    BEQ @loop                   ; the hand hidden: nothing to move
    LDA f:OPTMENU_EDGE
    AND #PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT
    BEQ @loop
    JSR seed_move
    BRA @loop

  @b:
    LDA f:SEED_N
    CMP #SEED_SHOWN
    BEQ @back                   ; the seed as given: back a screen
    CMP #0
    BEQ @back                   ; nothing typed: back a screen
    DEC A                       ; else the last digit taken back
    STA f:SEED_N
    JSR seed_drawseed
    JSR opt_sfx_sel
    BRA @loop

  @start:
    LDA f:SEED_N
    CMP #SEED_SHOWN
    BEQ @on
    CMP #SEED_DIGITS
    BEQ @on
    JSR seed_sfxerr             ; part of a seed: refused
    BRA @loop

  @a:
    LDA f:SEED_N
    CMP #SEED_DIGITS
    BEQ @on                     ; all eight in, the hand hidden: on
    CMP #SEED_SHOWN
    BNE :+
    LDA #0                      ; the first typed: the seed given blanked
:   TAX
    LDA f:SEED_SEL
    STA f:SEED_DIG, X
    INX
    TXA
    STA f:SEED_N
    JSR seed_drawseed
    JSR opt_sfx_sel
    JMP @loop

  @on:
    LDA f:SEED_N
    CMP #SEED_DIGITS
    BNE :+
    JSR seed_pack               ; typed: the eight digits are the seed
    LDA #1
    STA f:NGF_TYPED
:   LDA #NGNAV_FORWARD
    BRA @leave
  @back:
    LDA #NGNAV_BACK
  @leave:
    PHA
    JSR opt_sfx_sel             ; the game's sound for a choice, B's too
    JSR opt_waitrelease         ; nothing carries on to the next screen
    LDA #$00
    wPPUMASK
    PLA
    PLB
    RTL


;;  The hand to the next digit the d-pad points at, wrapping at each edge as
;;  the name input's does.  Up first if several are pressed at once.
seed_move:
    LDA f:OPTMENU_EDGE
    AND #PAD_UP
    BEQ :+
    LDA f:SEED_SEL
    SEC
    SBC #4                      ; a row up, the top to the bottom
    AND #$0F
    BRA @set
:   LDA f:OPTMENU_EDGE
    AND #PAD_DOWN
    BEQ :+
    LDA f:SEED_SEL
    CLC
    ADC #4                      ; a row down, the bottom to the top
    AND #$0F
    BRA @set
:   LDA f:OPTMENU_EDGE
    AND #PAD_LEFT
    BEQ :+
    LDA f:SEED_SEL
    DEC A                       ; a column left, within its row
    BRA @col
:   LDA f:SEED_SEL
    INC A                       ; a column right, within its row
  @col:
    AND #3
    STA tmp
    LDA f:SEED_SEL
    AND #$0C
    ORA tmp
  @set:
    STA f:SEED_SEL
    JMP opt_sfx_move


;;  The hand beside its digit, as the settings screen's stands beside its
;;  box: two cells before it, a pixel above its row.  None with all eight in.
seed_cursor:
    JSR ClearOAM
    LDA f:SEED_N
    CMP #SEED_DIGITS
    BEQ @hidden
    LDA f:SEED_SEL
    AND #3                      ; the column...
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; ...times GRID_DX cells of 8 pixels
    CLC
    ADC #GRID_COL * 8 - 16
    STA spr_x
    LDA f:SEED_SEL
    AND #$0C                    ; the row times 4...
    ASL A
    ASL A                       ; ...times 4 again: GRID_DY cells of 8 pixels
    CLC
    ADC #GRID_ROW * 8 - 1
    STA spr_y
    JMP DrawCursor
  @hidden:
    RTS


;;  The PPU at row A, column X.  X clobbered.
seed_ppu:
    STA OPTMENU_ADDR
    LDA #$00
    STA OPTMENU_ADDR + 1
    TXA
    LDX #$05                    ; * 32, the nametable row stride
  : ASL OPTMENU_ADDR
    ROL OPTMENU_ADDR + 1
    DEX
    BNE :-
    CLC
    ADC OPTMENU_ADDR            ; ...plus the column
    STA OPTMENU_ADDR
    LDA OPTMENU_ADDR + 1
    ADC #>$2000
    STA OPTMENU_ADDR + 1
    bPPUSTATUS
    LDA OPTMENU_ADDR + 1
    wPPUADDR
    LDA OPTMENU_ADDR
    wPPUADDR
    RTS


seed_drawhead:
    LDA #SEED_HEADROW
    LDX #SEED_HEADCOL
    JSR seed_ppu
    LDX #0
  : LDA lut_SeedHead, X
    STA f:NTSTAGE, X
    INX
    CPX #lut_SeedHead_end - lut_SeedHead
    BCC :-
    JSL hal_ntblit + HALFAR     ; X is the count
    RTS

lut_SeedHead:
  FFTEXT "Seed Entry"
lut_SeedHead_end:


;;  The seed: the digits typed, then dashes for the rest -- or, nothing
;;  typed, the seed given, all eight (SEED_SHOWN is past every index).
seed_drawseed:
    LDA #SEED_ROW
    LDX #SEED_COL
    JSR seed_ppu
    LDX #0
  @dig:
    TXA
    CMP f:SEED_N
    BCS @dash
    LDA f:SEED_DIG, X
    ORA #$80                    ; a nibble is its own tile from $80: the
    BRA @put                    ;   digits run on into the capitals
  @dash:
    LDA #CHR_DASH
  @put:
    STA f:NTSTAGE, X
    INX
    CPX #SEED_DIGITS
    BCC @dig
    JSL hal_ntblit + HALFAR
    RTS


;;  The grid, a row at a time: a digit every GRID_DX cells, blank between.
seed_drawgrid:
    LDA #0
    STA tmp + 1                 ; the row's first digit: 0, 4, 8, 12
  @row:
    LSR A                       ; the row times GRID_DY
    CLC
    ADC #GRID_ROW
    LDX #GRID_COL
    JSR seed_ppu
    LDX #0
  @cell:
    TXA
    AND #GRID_DX - 1
    BEQ @digit
    LDA #NT_BOXBODY
    BRA @put
  @digit:
    TXA
    LSR A
    LSR A                       ; the column
    ORA tmp + 1
    ORA #$80
  @put:
    STA f:NTSTAGE, X
    INX
    CPX #3 * GRID_DX + 1
    BCC @cell
    JSL hal_ntblit + HALFAR
    LDA tmp + 1
    CLC
    ADC #4
    STA tmp + 1
    CMP #16
    BCC @row
    RTS


;;  NGF_SEED as SEED_DIG's eight digits, the high byte's high nibble first,
;;  as the save view shows a seed; and back.  tmp clobbered.
seed_unpack:
    LDX #0
  @dig:
    TXA
    LSR A
    EOR #3                      ; the byte: 3, 3, 2, 2, 1, 1, 0, 0
    STA tmp
    PHX
    LDX tmp
    LDA f:NGF_SEED, X
    PLX
    STA tmp
    TXA
    LSR A                       ; C: an odd digit, the byte's low nibble
    LDA tmp
    BCS :+
    LSR A
    LSR A
    LSR A
    LSR A
:   AND #$0F
    STA f:SEED_DIG, X
    INX
    CPX #SEED_DIGITS
    BCC @dig
    RTS

seed_pack:
    LDX #0
  @pair:
    TXA
    LSR A
    EOR #3
    STA tmp                     ; the byte
    LDA f:SEED_DIG, X
    ASL A
    ASL A
    ASL A
    ASL A
    ORA f:SEED_DIG + 1, X
    PHX
    LDX tmp
    STA f:NGF_SEED, X
    PLX
    INX
    INX
    CPX #SEED_DIGITS
    BCC @pair
    RTS


;;  The game's error sound, as the map edit screen plays it (owscreen.asm's
;;  ows_sfxerr and ows_music, whose notes say why): PlaySFX_Error's writes,
;;  its sixteen frames this screen's own rather than its WaitForVBlank_L
;;  loop, so the screen goes on meanwhile.  The two are in different chunks
;;  and modes, so the writes are here again.
SEED_ERRFRAMES = 16
seed_sfxerr:
    LDA #1
    STA sq2_sfx                 ; square 2 the sound's, as PlaySFX_Error marks it
    LDA #$30
    wAPU $00                    ; square 1 silenced
    wAPU $08                    ; the triangle's linear reload, as the game writes it
    wAPU $0C                    ; the noise silenced
    LDA #SEED_ERRFRAMES
    STA f:SEED_ERR
    RTS

;;  A frame of the music, or of the error sound while SEED_ERR counts.
seed_music:
    LDA f:SEED_ERR
    BNE @err
    JMP CallMusicPlay
  @err:
    DEC A
    STA f:SEED_ERR
    LDA #%10001100              ; 50% duty, decaying, length on...
    wAPU $04
    LDA #%10001001              ; ...sweeping up, fast, in large steps...
    wAPU $05
    LDA #$80
    wAPU $06                    ; ...from $080...
    LDA #$00
    wAPU $07                    ; ...struck again
    LDA f:SEED_ERR
    BNE @out
    LDA #$30                    ; the last: square 2 silenced, its period zeroed
    wAPU $04
    LDA #$00
    wAPU $06
  @out:
    RTS
