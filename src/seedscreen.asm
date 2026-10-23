; ---------------------------------------------------------------------------
;  seedscreen.asm -- New Game's seed screen (menus.txt), in the settings
;  screen's chunk (CHUNK_OPTMENU): its chirps, release wait and frame are
;  that engine's.
;
;  Drawn from the 15-puzzle minigame's art (user, 2026-10-22): its pieces,
;  0-F, as the sixteen buttons and as the read-out of the seed, in one black
;  box over the bridge scene it is played on, the story box taken out --
;  tools/genseedart.py makes the tiles, the nametable and the palette
;  (gen/seedart.inc).  The pieces are background tiles over the menu font's
;  slots, which the screen puts back as it leaves, with the palette.
;
;  The seed the world will be built from, and a grid of the sixteen hex
;  digits to type another, as the game's name input has its letters (user):
;
;    - It shows the seed it is given, NGF_SEED -- latched from the pool by
;      the flow on the way in, or, back from party creation, the one chosen.
;    - A on a digit types it.  The first blanks the seed shown, the digits
;      not yet typed showing as blank pieces; the eighth hides the hand.
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
.export lut_SeedCHR, lut_SeedNT, lut_SeedPal    ; for tools/test_options.py
.import opt_menu_breathe
.import opt_sfx_move, opt_sfx_sel, opt_waitrelease
.import DrawCursor, ClearOAM, CallMusicPlay, UpdateJoy, WaitForVBlank_L, DrawPalette_L
.import hal_chrload
.import data_BridgeCHR          ; bank $0B's

.segment "BANK_OPTMENU"

;  The art: the tiles, the nametable, the palette and the layout.
.include "seedart.inc"
.assert SEEDART_GRIDDC = 3 && SEEDART_GRIDDR = 2, error, "seed_cursor multiplies by the grid's pitch"

;  The menu font, where LoadMenuCHR takes it from (bank $09's $8800), to put
;  back over the pieces as the screen leaves.
MENUCHR_BANK = CHUNK0 + BANK_MENUCHR
MENUCHR_AT   = $8800
BRIDGE_BANK  = CHUNK0 + BANK_BRIDGEGFX
;  The hand's four tiles, sprite $F0-$F3, where LoadBatSprCHRPalettes takes
;  them from (lut_BatObjCHR's last rows, at PPU $1800).
HANDCHR      = (CHUNK0 + BANK_BTLCHR) * $10000 + lut_BatObjCHR + $700
HAND_PPU     = $1F00

;  The screen's scratch, in the engine's (MENURAM), past the flow's.
SEED_SEL   = MENURAM + $20      ; the digit the hand is on, 0-15
SEED_N     = MENURAM + $21      ; how many are typed, 0-8, or SEED_SHOWN
SEED_ERR   = MENURAM + $22      ; the error sound's frames still to strike
SEED_DIG   = MENURAM + $23      ; 8 bytes: the digits, a nibble each, high first
SEED_PAL   = MENURAM + $30      ; 32 bytes: cur_pal as the screen found it
SEED_SHOWN = $FF                ; nothing typed: the seed as given, shown
SEED_DIGITS = 8
.assert SEED_DIG + SEED_DIGITS <= SEED_PAL, error, "the seed screen's scratch overlaps itself"
.assert SEED_PAL + 32 <= MENURAM_END, error, "the seed screen's scratch runs past the engine's"


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
    JSR seed_build
    JSR seed_drawread

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
    JSR seed_drawread
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
    JSR seed_drawread
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
    JSR seed_restore            ; the font and the palette, for the next
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


;;  The hand beside its piece, as the settings screen's stands beside its
;;  box: two cells before it, a pixel above its row -- in front, over the
;;  right half of the piece before it, as the name input's hand stands over
;;  the letter before (user, 2026-10-22: the pieces a cell apart, the box
;;  kept tight).  None with all eight in.
seed_cursor:
    JSR ClearOAM
    LDA f:SEED_N
    CMP #SEED_DIGITS
    BEQ @hidden
    LDA f:SEED_SEL
    AND #3                      ; the column...
    STA tmp
    ASL A
    ADC tmp                     ; ...times SEEDART_GRIDDC (3; C clear)...
    ASL A
    ASL A
    ASL A                       ; ...cells of 8 pixels
    CLC
    ADC #SEEDART_GRIDCOL * 8 - 16
    STA spr_x
    LDA f:SEED_SEL
    AND #$0C                    ; the row times 4...
    ASL A
    ASL A                       ; ...times 4 again: SEEDART_GRIDDR cells of 8
    CLC
    ADC #SEEDART_GRIDROW * 8 - 1
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


;;  The screen's art, the screen off: the bridge scene's tiles, the screen's
;;  over the menu font's, the nametable with its box, grid and "Seed Entry"
;;  already in it, and the palette -- cur_pal kept to put back.  Each load
;;  through hal_chrload, the game's own bulk path, a breath after each for
;;  the music.
seed_build:
    LDX #31
  : LDA cur_pal, X
    STA f:SEED_PAL, X
    DEX
    BPL :-
    LDA #BRIDGE_BANK
    LDX #>data_BridgeCHR
    LDY #$00                    ; the bridge scene's tiles, to $0000
    JSR seed_load8
    PHK
    PLA                         ; this chunk's own
    LDX #<lut_SeedCHR
    STX tmp
    LDX #>lut_SeedCHR
    STX tmp + 1
    LDY #>(SEEDART_BASE * 16)
    LDX #SEEDART_ROWS
    JSR seed_load               ; the screen's tiles, over the font's
    PHK
    PLA
    LDX #<lut_SeedNT
    STX tmp
    LDX #>lut_SeedNT
    STX tmp + 1
    LDY #$20
    LDX #4
    JSR seed_load               ; the nametable and its attributes, to $2000
    LDA #1
    JSR seed_hand               ; the hand without its shadow
    LDX #15
  : LDA lut_SeedPal, X
    STA cur_pal, X
    DEX
    BPL :-
    JMP DrawPalette_L

;;  ...and back: the menu font, as LoadMenuCHR loads it, the hand whole, and
;;  the palette.
seed_restore:
    LDA #MENUCHR_BANK
    LDX #>MENUCHR_AT
    LDY #$08
    JSR seed_load8
    LDA #0
    JSR seed_hand
    LDX #31
  : LDA f:SEED_PAL, X
    STA cur_pal, X
    DEX
    BPL :-
    JMP DrawPalette_L

;;  The hand's tiles, from where the game loads them -- without its shadow
;;  if A is nonzero (user, 2026-10-22: the hand stands over the pieces here,
;;  and its shadow, unseen on the black, is a dark smear on their white).
;;  The shadow is the slab under the hand, the bottom four rows of its two
;;  lower tiles: in each plane, the bytes whose index has $24 set.
seed_hand:
    STA tmp + 3
    bPPUSTATUS
    LDA #>HAND_PPU
    wPPUADDR
    LDA #<HAND_PPU
    wPPUADDR
    LDX #0
  @byte:
    TXA
    AND #$24
    CMP #$24
    BNE @keep
    LDA tmp + 3
    BEQ @keep
    LDA #0                      ; the shadow's rows: nothing
    BRA @put
  @keep:
    LDA f:HANDCHR, X
  @put:
    wPPUDATA
    INX
    CPX #64
    BCC @byte
    RTS

;;  Eight rows of 256 bytes from bank A, page X, to PPU page Y.
seed_load8:
    STZ tmp
    STX tmp + 1
    LDX #8
    ;  ...and on into seed_load.

;;  X rows of 256 bytes from bank A at (tmp) to PPU page Y, through
;;  hal_chrload with the data bank the source's; then a breath.
seed_load:
    PHB
    PHA
    PLB
    bPPUSTATUS
    TYA
    wPPUADDR
    LDA #$00
    wPPUADDR
    LDY #$00
    JSL hal_chrload + HALFAR
    PLB
    JMP opt_menu_breathe


;;  The read-out: the digits typed, then blank pieces for the rest -- or,
;;  nothing typed, the seed given, all eight (SEED_SHOWN is past every
;;  index).  Two rows of four pieces, so four rows of the nametable, each a
;;  run of eight tiles: a piece's top or bottom half, its left and right.
seed_drawread:
    LDA #0
    STA tmp + 1                 ; the nametable row, 0-3
  @row:
    CLC
    ADC #SEEDART_READROW
    LDX #SEEDART_READCOL
    JSR seed_ppu
    LDX #0                      ; the run's cell, 0-7
  @cell:
    LDA tmp + 1
    AND #2
    ASL A                       ; the row of pieces's first digit, 0 or 4
    STA tmp + 2
    TXA
    LSR A
    ORA tmp + 2                 ; the digit's place
    CMP f:SEED_N
    BCS @blank
    PHX
    TAX
    LDA f:SEED_DIG, X
    PLX
    BRA @piece
  @blank:
    LDA #SEEDART_BLANK
  @piece:
    ASL A
    ASL A                       ; its four tiles...
    STA tmp + 2
    LDA tmp + 1
    AND #1
    ASL A                       ; ...the bottom two on the second row...
    ORA tmp + 2
    STA tmp + 2
    TXA
    AND #1                      ; ...the right one on the odd cell
    ORA tmp + 2
    CLC
    ADC #SEEDART_PIECE
    STA f:NTSTAGE, X
    INX
    CPX #8
    BCC @cell
    JSL hal_ntblit + HALFAR     ; X is the count
    LDA tmp + 1
    INC A
    STA tmp + 1
    CMP #4
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
