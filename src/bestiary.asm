; ---------------------------------------------------------------------------
;  bestiary.asm -- the Bestiary: every enemy in a grid, the ones defeated in
;  their battle colours and the rest as silhouettes, a count across the top.
;
;  PROTOTYPE (user, 2026-11-11), on the bestiary branch: the title shows it
;  first, once a power-on (opt_drawpresetbox), the title's music playing on;
;  B or START goes on to the title.  The defeated mask is a stand-in
;  (lut_BstFakeSeen, 57 of 128), the count is out of 128 rather than out of
;  those the seed can produce, and the colours are the cartridge's rather
;  than Palette swap's.  A does nothing yet: the detail view is to come.
;
;  The grid (user): five columns of 48 x 48 cells, every enemy in its id
;  order, on black as in battle; the small ones (32 x 32) and the large (48 x
;  48) as battle draws them, read from the battle CHR, the fiends and Chaos
;  scaled down into art/bestiary/*.png (tools/genbestiary.py).  The hand
;  points at the selected cell from its left, as battle's does at an enemy.
;  The text line -- "Bestiary (57/128)" and the selected enemy's name, or
;  "?????" -- is BG3, in front, each letter outlined in black (user: "a
;  black border around the text rather than a solid black rectangle"), and
;  the grid scrolls beneath it.
;
;  The screen takes the PPU from the HAL, as the map edit screen does, and
;  gives it back through hal_ppureclaim: mode 1, the grid on BG1 (4bpp), the
;  text on BG3, the hand a sprite.
;
;  The grid's rows, 48 lines each: four in the clear (lines 18-209), the
;  row above showing 18 lines under the text and the row below 14.  Moving
;  past them scrolls a row, 8 lines a frame, at once: the incoming row's
;  characters are made as it scrolls (bst_begin, bst_work) -- converted
;  from the NES's 2bpp into the cell's colour group, see below, in what is
;  left of each frame -- the scroll waiting halfway, before the row shows,
;  only if they are not all made and sent yet.  Into a ring of BG1's 1023
;  characters, the rows on screen and the one coming in contiguous in it
;  (1000 at the worst; genbestiary.py checks it); a row leaving gives its
;  characters back and its tilemap rows are cleared.
;
;  Colours: the grid's eight palettes are five groups of three colours each
;  (CGRAM p * 16 + 3g + 1..3), an enemy's picture in one group, a fiend's or
;  Chaos's in two of one palette.  Grid row r uses slot r mod 6, and a
;  slot's cells have their groups for good (genbestiary.py works them out:
;  all 39 that are free, palette 0's first being the text's).  A row coming
;  in shares its slot with the one going out, so its colours are written at
;  the vblank where neither shows: 24 lines into the scroll, either way.
;  A character's colour bits are its group's: a pixel of value v (w for a
;  special's three planes) becomes colour 3g + v, so each of the four planes
;  is an OR of the pixels whose value has that bit (lut_BstCellSel).
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "fftext.inc"
.include "nescol.inc"
.include "optcall.inc"
.include "nesio.inc"

.export bst_show

.import UpdateJoy, CallMusicPlay
.import hal_vblaudio, hal_audioframe, hal_auxdetect, hal_ppureclaim, hal_framedue
.import opt_padreset
.import OptCallFar, PlaySFX_MenuMove, PlaySFX_MenuSel
.import lut_BattlePalettes

.segment "BANK_BESTIARY"

.include "bestiary.inc"

MENUCHR   = (CHUNK0 + BANK_MENUCHR) * $10000 + $8800    ; the font, tiles $80-$FF
HANDCHR   = (CHUNK0 + BANK_BTLCHR) * $10000 + lut_BatObjCHR + ($F0 - $80) * 16
NAMESFAR  = (CHUNK0 + BANK_ENEMYNAMES) * $10000 + $94E0  ; the enemies' names' pointers
NAMEBANK  = CHUNK0 + BANK_ENEMYNAMES
BTLPALFAR = (CHUNK0 + BANK_BTLPALETTES) * $10000 + lut_BattlePalettes

;  VRAM, in words.
VR_BG1CHR = $0000               ; 1024 characters: 0 blank, 1-1023 the ring
VR_BG1MAP = $4000               ; 32 x 64
VR_BG3CHR = $5000               ; 0 blank, 1-60 the text line
VR_BG3MAP = $5800               ; 32 x 32
VR_OBJCHR = $6000               ; the hand at 2
OBJ_HAND  = 2
HAND_X    = 4                   ; the hand from the cell's left, less 8: its
                                ;   finger 12 pixels into the cell, its wrist
                                ;   4 over the one before (the cells touch)

RING      = 1023                ; BG1 characters 1-1023
CELLPX    = 48
CLEAR_TOP = 18                  ; the clear rows' first line
TEXT_ROW  = 1                   ; BG3's, lines 8-23: the letters on 9-15
TEXT_COLS = 30
TEXT_COL  = 1
TEXT_STRIDE = 32                ; BST_G's and BST_H's rows, a row of padding each end
LINE_DMA  = TEXT_COLS * 2 * 16  ; the line's 60 characters, bytes
TILES_PER_VBL = 2048            ; a vblank's worth of a row's characters
SCROLL_STEP = 8
CG_AT     = 24                  ; lines into a scroll: the colours change
REPEAT_DELAY = 20
REPEAT_EVERY = 6
SILHOUETTE = $24C5              ; (40, 48, 72), genbestiary.py's SILHOUETTE_RGB

;  Custom glyphs, beside the font's: the font has no brackets or slash.
CH_LPAREN = $F0
CH_RPAREN = $F1
CH_SLASH  = $F2

PAD_B     = $40
PAD_START = $10
PAD_UP    = $08
PAD_DOWN  = $04
PAD_LEFT  = $02
PAD_RIGHT = $01
PAD_DIRS  = $0F

ST_IDLE   = 0
ST_SCROLL = 2                   ; a row coming in, built and sent as it comes
WORK_LAST = 200                 ; the conversion stops for the frame from this line

;  Direct page scratch, the battle's ($80-$AF), saved and put back: nothing
;  of a battle is live at the title, and the music driver keeps to tmp.
ZP0       = $80
SRC       = $80                 ; 3: the picture, long
SRC8      = $83                 ; 3: ...plus 8
SRC16     = $86                 ; 3: ...plus 16
P0        = $89
P1        = $8A
P2        = $8B
M1        = $8C                 ; ...M6, $91: the pixels of each value, 1-6
M2        = $8D
M3        = $8E
M4        = $8F
M5        = $90
M6        = $91
TT        = $92
CNT       = $93
SEL       = $94                 ; 24: plane j's mask for value w at SEL + j * 6 + w - 1
CONVVEC   = $AC                 ; 2: the cell's character conversion
ZPLEN     = $30

;  The variables, in bank $7F, long.
BV        = BST_VARS
V_SEL     = BV+$00              ; the enemy under the hand
V_TOP     = BV+$01              ; the first clear grid row
V_STATE   = BV+$02
V_DIR     = BV+$03              ; 0 down, 1 up
V_D       = BV+$04              ; lines scrolled, 0-48
V_PREV    = BV+$05              ; the pad last frame
V_HOLD    = BV+$06              ; frames a direction has been held
V_LROW    = BV+$07              ; the row being made (-1 as $FF, to 26)
V_HEAD    = BV+$08              ; 2: the ring's next free place, going down...
V_TAIL    = BV+$0A              ; 2: ...and its first used, going up
V_DMAPOS  = BV+$0C              ; 2: bytes of BST_CONV sent
V_DMALEN  = BV+$0E              ; 2: ...of how many
V_LSTART  = BV+$10              ; 2: the made row's first ring place
V_MAPPEND = BV+$12              ; nonzero: the made row's tilemap to send
V_CGPEND  = BV+$13              ; nonzero: the made row's colours to write
V_TXTPEND = BV+$14              ; nonzero: the text line's characters to send
V_CLRROW  = BV+$15              ; the row whose tilemap to clear...
V_CLRPEND = BV+$16              ; ...nonzero: due
V_COUNT   = BV+$17              ; the defeated
V_VOFS    = BV+$18              ; 2: BG1's vertical scroll
V_LEAVE   = BV+$1A
V_SAVEBANK = BV+$1B
V_N       = BV+$1C              ; 2: bytes of BST_CONV made so far
V_K       = BV+$1E              ; the slot's cell, slot * 5 + column
V_C       = BV+$1F              ; the column
V_E       = BV+$20              ; the enemy
V_KIND    = BV+$21
V_TMP     = BV+$22              ; 2
V_OUTROW  = BV+$24              ; the row a scroll leaves behind
V_TILES   = BV+$25              ; characters still to convert in a cell
V_ROWBASE = BV+$26              ; 2: the made row's first ring place
V_PLACE   = BV+$28              ; 2: a ring place
V_DST     = BV+$2A              ; 2: an offset in BST_MAPROW
V_CGO     = BV+$2C              ; 2: bytes in BST_CGBUF
V_PAL     = BV+$2E              ; 2: a tilemap entry's palette bits
V_RCOUNT  = BV+$30              ; 2 x 26: each row's characters
V_CELLPOS = BV+$68              ; 2 x 5: the made row's cells' first ring places
V_COL     = BV+$72              ; 2
V_W       = BV+$74              ; 2: cell width in characters
V_ROWS    = BV+$76              ; rows of a cell left
V_I       = BV+$77              ; a counter
V_NAMELEN = BV+$78
V_SEEN    = BV+$79
V_TR      = BV+$7A              ; the text's character row
V_TC      = BV+$7B              ; ...and column
V_C0      = BV+$7C              ; the text's first column to draw
V_TC1     = BV+$7D              ; ...and the first redrawn round it
V_PDONE   = BV+$80              ; nonzero: the made row is all converted
V_CGDONE  = BV+$81              ; nonzero: this scroll's colours are written
V_NOBUDGET = BV+$82             ; nonzero: convert without stopping (setup)
V_SRCY    = BV+$84              ; 2: the cell's picture, how far converted
V_ZPSAVE  = BV+$C0              ; ZPLEN
.assert V_ZPSAVE + ZPLEN <= BST_VARS + $100, error, "the Bestiary's variables outgrow their page"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  bst_show -- the screen, until B or START.  By JSL, emulation mode, with
;;  the PPU the HAL's; out the same, the PPU given back in forced blank, the
;;  registers, cur_bank and the direct page scratch as they were.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

bst_show:
    PHP
    PHA
    PHX
    PHY
    PHB
    PHK
    PLB                         ; this chunk's low half is the I/O map
    SEP #$30
    LDA cur_bank
    STA f:V_SAVEBANK
    LDX #ZPLEN - 1
  @save:
    LDA ZP0, X
    STA f:V_ZPSAVE, X
    DEX
    BPL @save
    CLC
    XCE
    REP #$10
    .i16
    JSR bst_setup
    JSR bst_loop
    JSR bst_release             ; nothing carries on to the title
    SEP #$30
    .i8
    SEC
    XCE
    LDA #$80
    STA a:INIDISP
    JSL hal_ppureclaim + HALFAR
    LDX #ZPLEN - 1
  @restore:
    LDA f:V_ZPSAVE, X
    STA ZP0, X
    DEX
    BPL @restore
    LDA f:V_SAVEBANK
    STA cur_bank
    PLB
    PLY
    PLX
    PLA
    PLP
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Setup, in forced blank: VRAM, CGRAM, OAM, the first rows and the text,
;;  the registers, the display on.  A8 I16, DBR this chunk.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_setup:
    JSR bst_wait                ; the top of a vblank
    LDA #$80
    STA a:INIDISP
    STZ a:HDMAEN
    JSR bst_playframe
    SEP #$30                    ; the channels on, as the title has them
    .i8
    SEC
    XCE
    LDA #$0F
    wAPU $15
    CLC
    XCE
    REP #$10
    .i16
    ;  VRAM all zero, in eight pieces, the music's chance before each.
    LDA #$80
    STA a:VMAIN
    REP #$20
    .a16
    STZ a:VMADDL
    SEP #$20
    .a8
    LDA #8
  @zero:
    PHA
    JSR bst_audio
    REP #$20
    .a16
    LDA #.LOWORD(lut_BstZero)
    STA a:A1T0L
    LDA #$10000 / 8
    STA a:DAS0L
    SEP #$20
    .a8
    LDA #^BESTIARYFAR
    STA a:A1B0
    LDA #$09                    ; fixed source, two registers
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    PLA
    DEC A
    BNE @zero
    JSR bst_handchr
    ;  CGRAM: black, then the text's and the hand's.
    STZ a:CGADD
    LDX #256
  @cg0:
    STZ a:CGDATA
    STZ a:CGDATA
    DEX
    BNE @cg0
    LDA #1
    STA a:CGADD
    LDX #$0000
  @cgtext:
    LDA lut_BstTextPal, X
    STA a:CGDATA
    INX
    CPX #6
    BCC @cgtext
    LDA #128 + 16
    STA a:CGADD
    LDX #$0000
  @cghand:
    LDA lut_BstHandPal, X
    STA a:CGDATA
    INX
    CPX #8
    BCC @cghand
    ;  OAM: every sprite below the picture, the hand (sprite 0) large.
    STZ a:OAMADDL
    STZ a:OAMADDH
    LDX #128
  @oam:
    STZ a:OAMDATA
    LDA #224
    STA a:OAMDATA
    STZ a:OAMDATA
    STZ a:OAMDATA
    DEX
    BNE @oam
    LDA #$02
    STA a:OAMDATA
    LDX #31
  @oamhi:
    STZ a:OAMDATA
    DEX
    BNE @oamhi
    ;  BG3's map: the line's 60 characters, in front.
    REP #$20
    .a16
    LDA #VR_BG3MAP + TEXT_ROW * 32 + TEXT_COL
    STA a:VMADDL
    LDA #$2001
  @nt1:
    STA a:VMDATAL
    INC A
    CMP #$2001 + TEXT_COLS
    BCC @nt1
    LDX #VR_BG3MAP + (TEXT_ROW + 1) * 32 + TEXT_COL
    STX a:VMADDL
  @nt2:
    STA a:VMDATAL
    INC A
    CMP #$2001 + 2 * TEXT_COLS
    BCC @nt2
    SEP #$20
    .a8
    ;  The state.
    LDA #0
    STA f:V_SEL
    STA f:V_TOP
    STA f:V_STATE
    STA f:V_HOLD
    STA f:V_D
    STA f:V_DIR
    STA f:V_MAPPEND
    STA f:V_CGPEND
    STA f:V_TXTPEND
    STA f:V_CLRPEND
    STA f:V_LEAVE
    LDA #$FF
    STA f:V_PREV                ; nothing counts as pressed until let go
    REP #$20
    .a16
    LDA #0
    STA f:V_HEAD
    STA f:V_TAIL
    SEP #$20
    .a8
    JSR bst_count
    ;  The rows on screen at the top: -1 (none) to 4, each made and sent.
    LDA #0
  @row:
    STA f:V_LROW
    JSR bst_begin
    LDA #1
    STA f:V_NOBUDGET            ; all of it, the music's turns between
    JSR bst_work
    LDA #0
    STA f:V_NOBUDGET
  @send:
    LDX #$FFFF
    JSR bst_dmachunk
    BCC @send
    JSR bst_sendmap
    JSR bst_sendcg
    JSR bst_audio
    LDA f:V_LROW
    INC A
    CMP #5
    BCC @row
    LDA #0
    STA f:V_MAPPEND
    ;  The text line, all of it.
    JSR bst_textclear
    LDA #0
    STA f:V_C0
    JSR bst_textline
    JSR bst_textrender
    JSR bst_sendtext
    JSR bst_audio
    JSR bst_setvofs
    ;  The registers.
    LDA #$09
    STA a:BGMODE                ; mode 1, BG3 in front
    STZ a:MOSAIC
    LDA #(VR_BG1MAP >> 8) | $02 ; 32 x 64
    STA a:BG1SC
    LDA #(VR_BG3MAP >> 8)
    STA a:BG3SC
    LDA #(VR_BG1CHR >> 12)
    STA a:BG12NBA
    LDA #(VR_BG3CHR >> 12)
    STA a:BG34NBA
    LDA #(VR_OBJCHR >> 13)
    STA a:OBSEL                 ; 8x8 and 16x16
    STZ a:BG1HOFS
    STZ a:BG1HOFS
    STZ a:BG3HOFS
    STZ a:BG3HOFS
    LDA #$FF                    ; -1: the tilemap's first row the first line
    STA a:BG3VOFS
    LDA #$03
    STA a:BG3VOFS
    LDA f:V_VOFS
    STA a:BG1VOFS
    LDA f:V_VOFS + 1
    STA a:BG1VOFS
    LDA #$15
    STA a:TM                    ; BG1, BG3, sprites
    STZ a:TS
    STZ a:TMW
    STZ a:TSW
    STZ a:W12SEL
    STZ a:CGWSEL
    STZ a:CGADSUB
    JSR bst_sprites
    LDA #$0F
    STA a:INIDISP
    RTS

;;  The hand, OBJ characters 2, 3, 18 and 19: the game's (battle object CHR
;;  $F0-$F3, which DrawCursor draws), NES 2bpp as planes 0 and 1 -- without
;;  its shadow, as the seed screen's (seed_hand; user, 2026-11-12: "That
;;  would look better here"): the slab under it, the bottom four rows of the
;;  lower two tiles, the bytes whose index has $24 set.  A8 I16.
    .a8
    .i16
bst_handchr:
    LDY #$0000
  @tile:
    REP #$20
    .a16
    LDA lut_BstHandCell, Y
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC #VR_OBJCHR
    STA a:VMADDL
    TYA
    ASL A
    ASL A
    ASL A
    ASL A
    TAX                         ; the tile's 16 NES bytes
    SEP #$20
    .a8
    LDA #8
    STA f:V_I
  @row:
    TXA
    AND #$24
    CMP #$24
    BEQ @shadow
    LDA f:HANDCHR, X
    STA a:VMDATAL
    LDA f:HANDCHR + 8, X
    STA a:VMDATAH
    BRA @rowdone
  @shadow:
    STZ a:VMDATAL               ; the shadow's rows: nothing
    STZ a:VMDATAH
  @rowdone:
    INX
    LDA f:V_I
    DEC A
    STA f:V_I
    BNE @row
    LDX #8
  @hi:
    STZ a:VMDATAL
    STZ a:VMDATAH
    DEX
    BNE @hi
    INY
    CPY #4
    BCC @tile
    RTS

;;  V_COUNT: the defeated, the mask's bits.  A8 I16.
    .a8
    .i16
bst_count:
    LDA #0
    STA f:V_COUNT
    LDX #$0000
  @byte:
    LDA lut_BstFakeSeen, X
  @bit:
    BEQ @next
    LSR A
    PHA
    LDA #0
    ADC f:V_COUNT
    STA f:V_COUNT
    PLA
    BRA @bit
  @next:
    INX
    CPX #16
    BCC @byte
    RTS

;;  V_SEEN nonzero if enemy A is defeated.  A8 I16; A, X and Y not kept.
    .a8
    .i16
bst_seen:
    REP #$20
    .a16
    AND #$00FF
    PHA
    LSR A
    LSR A
    LSR A
    TAX
    PLA
    AND #$0007
    TAY
    SEP #$20
    .a8
    LDA lut_BstFakeSeen, X
  @shift:
    DEY
    BMI @have
    LSR A
    BRA @shift
  @have:
    AND #1
    STA f:V_SEEN
    RTS

;;  Enemy A's grid row in A, its column in X.  A8 I16.
    .a8
    .i16
bst_rowcol:
    LDX #$0000
  @sub:
    CMP #BST_COLS
    BCC @have
    SBC #BST_COLS
    INX
    BRA @sub
  @have:
    STA f:V_TMP                 ; the column
    TXA                         ; the row
    PHA
    LDA f:V_TMP
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    PLA
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The loop: a frame, its vblank's transfers, its music, the reset combo,
;;  then the pad and the work.  Out when B or START is pressed.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_loop:
  @frame:
    JSR bst_wait
    JSR bst_vblank
    JSR bst_playframe
    JSR bst_reset
    JSR bst_logic
    JSR bst_work                ; the incoming row's conversion, the rest of the frame
    LDA f:V_LEAVE
    BEQ @frame
    RTS

;;  Until every button is let go, the frames going on: what ended the screen
;;  must not reach the title.  A8 I16.
    .a8
    .i16
bst_release:
  @frame:
    JSR bst_wait
    JSR bst_vblank
    JSR bst_playframe
    JSR bst_reset
    LDA joy
    BNE @frame
    RTS

;;  The game's pad reader, then the top of the next vblank -- a frame begun
;;  meanwhile whose music nobody has played first (bst_audio), as the map
;;  edit screen's ows_wait.  A8 I16 in and out.
    .a8
    .i16
bst_wait:
    JSR bst_audio
    SEP #$30
    .i8
    SEC
    XCE
    JSR UpdateJoy
    JSL hal_vblaudio + HALFAR
    CLC
    XCE
    REP #$10
    .i16
    RTS

;;  A frame of music, if one has begun that nobody has played (the HAL's
;;  framedue), with the HAL's frame of sound: for work longer than a frame.
;;  bst_playframe is the frame's music alone, the wait's caller's.  A8 I16
;;  in and out; X and Y not kept.
    .a8
    .i16
bst_audio:
    JSL hal_framedue + HALFAR
    BCC @out
    JSR bst_playframe
    SEP #$30
    .i8
    SEC
    XCE
    JSL hal_audioframe + HALFAR
    CLC
    XCE
    REP #$10
    .i16
  @out:
    RTS
bst_playframe:
    SEP #$30
    .i8
    SEC
    XCE
    LDA #CHUNK_BESTIARY
    STA cur_bank                ; CallMusicPlay comes back through it
    JSR CallMusicPlay
    CLC
    XCE
    REP #$10
    .i16
    RTS

;;  L + X and L + Y, as the map edit screen takes them (ows_reset): the PPU
;;  back to the HAL first when it is going to reset.  A8 I16 in and out.
    .a8
    .i16
bst_reset:
    SEP #$30
    .i8
    SEC
    XCE
    JSL hal_auxdetect + HALFAR
    LDA a:h_padreset
    BEQ :+
    LDA #$80
    STA a:INIDISP
    JSL hal_ppureclaim + HALFAR
:   JSL opt_padreset + OPTFAR   ; no return, if it resets
    CLC
    XCE
    REP #$10
    .i16
    RTS

;;  The menu's chirps, the game's own in bank $0E.  A8 I16 in and out; X
;;  and Y not kept.
    .a8
    .i16
bst_sfxmove:
    SEP #$30
    .i8
    SEC
    XCE
    CALL0E PlaySFX_MenuMove
    BRA bst_sfxout
bst_sfxsel:
    SEP #$30
    SEC
    XCE
    CALL0E PlaySFX_MenuSel
bst_sfxout:
    CLC
    XCE
    REP #$10
    .i16
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The vblank's work: the scroll, a row's colours, a tilemap cleared, the
;;  text or a share of a row's characters, the hand.  A8 I16, DBR this chunk.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_vblank:
    LDA f:V_VOFS
    STA a:BG1VOFS
    LDA f:V_VOFS + 1
    STA a:BG1VOFS
    LDA f:V_CGPEND
    BEQ :+
    LDA #0
    STA f:V_CGPEND
    JSR bst_sendcg
:   LDA f:V_CLRPEND
    BEQ :+
    LDA #0
    STA f:V_CLRPEND
    LDA f:V_CLRROW
    JSR bst_clearmap
:   LDA f:V_TXTPEND
    BEQ @tiles
    LDA #0
    STA f:V_TXTPEND
    JSR bst_sendtext
    BRA @hand                   ; that is the vblank's worth
  @tiles:
    LDA f:V_STATE
    CMP #ST_SCROLL
    BNE @hand
    LDX #TILES_PER_VBL
    JSR bst_dmachunk
    BCC @hand
    LDA f:V_MAPPEND             ; the characters all there: the tilemap
    BEQ @hand
    LDA #0
    STA f:V_MAPPEND
    JSR bst_sendmap
  @hand:
    JMP bst_sprites

;;  OAM: the hand, at the selected cell's left, halfway down it -- or under
;;  the picture, if the scroll has it off the screen.  A8 I16.
    .a8
    .i16
bst_sprites:
    STZ a:OAMADDL
    STZ a:OAMADDH
    LDA f:V_SEL
    JSR bst_rowcol              ; A = row, X = column
    PHA
    TXA
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:V_TMP
    ASL A                       ; column x 48: x 16 + x 32
    CLC
    ADC f:V_TMP
    CLC
    ADC #HAND_X
    STA a:OAMDATA               ; x: over the cell's left edge
    PLA
    REP #$20
    .a16
    AND #$00FF
    STA f:V_TMP
    ASL A                       ; row x 48
    ADC f:V_TMP
    ASL A
    ASL A
    ASL A
    ASL A
    SEC
    SBC f:V_VOFS
    CLC
    ADC #16 - 1                 ; halfway down; screen line = BG line - VOFS - 1
    AND #$01FF
    CMP #224
    BCC :+
    LDA #224
:   SEP #$20
    .a8
    STA a:OAMDATA
    LDA #OBJ_HAND
    STA a:OAMDATA
    LDA #$32                    ; in front, OBJ palette 1
    STA a:OAMDATA
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The frame's work: the pad while nothing moves, a row being sent, the
;;  scroll.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_logic:
    LDA f:V_STATE
    CMP #ST_SCROLL
    BNE :+
    JMP bst_scroll
:   JMP bst_input

;;  A scroll's frame: SCROLL_STEP lines further -- but at CG_AT, where
;;  neither the incoming row nor the one leaving shows, only once the
;;  incoming row is converted and sent, its colours then written with the
;;  next step (user, 2026-11-12: "some delay before initiating scrolling":
;;  the row was built first, 8-23 frames, and only then scrolled) -- and at
;;  the end the row left behind given up.  A8 I16.
    .a8
    .i16
bst_scroll:
    LDA f:V_D
    CMP #CG_AT
    BNE @step
    LDA f:V_CGDONE
    BNE @step
    JSR bst_loaded
    BCS :+
    RTS                         ; not yet: held here
:   LDA #1
    STA f:V_CGPEND
    STA f:V_CGDONE
  @step:
    LDA f:V_D
    CLC
    ADC #SCROLL_STEP
    STA f:V_D
    CMP #CELLPX
    BCS :+
    JMP bst_setvofs
:   ;  Done: the top row moves, the row left behind goes.
    LDA f:V_DIR
    BNE @up
    LDA f:V_TOP
    DEC A                       ; the row above, which leaves
    STA f:V_OUTROW
    INC A
    INC A
    STA f:V_TOP
    LDA f:V_OUTROW
    JSR bst_rowvalid
    BCC @gone
    JSR bst_rowcount            ; the ring's tail past it
    REP #$20
    .a16
    CLC
    ADC f:V_TAIL
    JSR bst_ringmod
    STA f:V_TAIL
    SEP #$20
    .a8
    BRA @clear
  @up:
    LDA f:V_TOP
    CLC
    ADC #4                      ; the row below, which leaves
    STA f:V_OUTROW
    LDA f:V_TOP
    DEC A
    STA f:V_TOP
    LDA f:V_OUTROW
    JSR bst_rowvalid
    BCC @gone
    JSR bst_rowcount            ; the ring's head back before it
    REP #$20
    .a16
    STA f:V_TMP
    LDA f:V_HEAD
    SEC
    SBC f:V_TMP
    BCS :+
    ADC #RING
:   STA f:V_HEAD
    SEP #$20
    .a8
  @clear:
    LDA f:V_OUTROW
    STA f:V_CLRROW
    LDA #1
    STA f:V_CLRPEND
  @gone:
    LDA #ST_IDLE
    STA f:V_STATE
    LDA #0
    STA f:V_D
  @move:
    JMP bst_setvofs

;;  The pad, while nothing moves: a direction moves the hand -- held, it
;;  repeats -- and scrolls when the hand leaves the clear rows; B or START
;;  ends the screen.  A8 I16.
    .a8
    .i16
bst_input:
    LDA f:V_PREV
    EOR #$FF
    AND joy
    STA f:V_TMP                 ; pressed since last frame
    LDA joy
    STA f:V_PREV
    LDA f:V_TMP
    AND #PAD_B | PAD_START
    BEQ @dirs
    JSR bst_sfxsel
    LDA #1
    STA f:V_LEAVE
    RTS
  @dirs:
    LDA joy
    AND #PAD_DIRS
    BNE :+
    STA f:V_HOLD
    RTS
:   LDA f:V_TMP
    AND #PAD_DIRS
    BEQ @held
    LDA #0
    STA f:V_HOLD
    LDA f:V_TMP
    BRA @move
  @held:
    LDA f:V_HOLD
    INC A
    CMP #REPEAT_DELAY + REPEAT_EVERY
    BCC :+
    LDA #REPEAT_DELAY
:   STA f:V_HOLD
    CMP #REPEAT_DELAY
    BNE @none
    LDA joy
  @move:
    JSR bst_dir                 ; A = the new selection
    CMP f:V_SEL
    BEQ @none
    STA f:V_SEL
    JSR bst_sfxmove
    LDA #NAME_C0                ; the name's part of the line
    STA f:V_C0
    JSR bst_textline
    JSR bst_textrender
    LDA #1
    STA f:V_TXTPEND
    ;  Out of the clear rows: a row comes in.
    LDA f:V_SEL
    JSR bst_rowcol
    CMP f:V_TOP
    BCC @scrollup
    SEC
    SBC f:V_TOP
    CMP #4
    BCC @none
    ;  Down: the row past the bottom one, which peeks, comes in.
    LDA #0
    STA f:V_DIR
    LDA f:V_TOP
    CLC
    ADC #5
    BRA @load
  @scrollup:
    LDA #1
    STA f:V_DIR
    LDA f:V_TOP
    SEC
    SBC #2
  @load:
    STA f:V_LROW
    JSR bst_begin               ; built as it scrolls (bst_work)
    LDA #0
    STA f:V_D
    STA f:V_CGDONE
    LDA #ST_SCROLL
    STA f:V_STATE
  @none:
    RTS

;;  The selection directions A take it to: up and down a row, left and
;;  right a cell, on to the next row's or the last row's.  A8 I16.
    .a8
    .i16
bst_dir:
    BIT #PAD_UP
    BEQ @down
    LDA f:V_SEL
    CMP #BST_COLS
    BCC @same
    SBC #BST_COLS
    RTS
  @down:
    BIT #PAD_DOWN
    BEQ @left
    LDA f:V_SEL
    CLC
    ADC #BST_COLS
    CMP #BST_NENEMY
    BCC @out
    LDA f:V_SEL                 ; past the end: the last, from a row above it
    JSR bst_rowcol
    CMP #BST_ROWS - 1
    BCS @same
    LDA #BST_NENEMY - 1
    RTS
  @left:
    BIT #PAD_LEFT
    BEQ @right
    LDA f:V_SEL
    BEQ @out
    DEC A
    RTS
  @right:
    LDA f:V_SEL
    CMP #BST_NENEMY - 1
    BCS @out
    INC A
    RTS
  @same:
    LDA f:V_SEL
  @out:
    RTS

;;  BG1's scroll for V_TOP and the scroll's progress: the top clear row's
;;  first line at CLEAR_TOP.  A8 I16.
    .a8
    .i16
bst_setvofs:
    LDA f:V_TOP
    REP #$20
    .a16
    AND #$00FF
    STA f:V_TMP
    ASL A
    ADC f:V_TMP
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 48
    SEC
    SBC #CLEAR_TOP + 1
    STA f:V_TMP
    SEP #$20
    .a8
    LDA f:V_DIR
    REP #$20
    .a16
    BNE @up
    LDA f:V_D
    AND #$00FF
    CLC
    ADC f:V_TMP
    BRA @set
  @up:
    LDA f:V_D
    AND #$00FF
    EOR #$FFFF
    SEC
    ADC f:V_TMP
  @set:
    AND #$03FF
    STA f:V_VOFS
    SEP #$20
    .a8
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  A grid row made: bst_begin places V_LROW's characters in the ring -- at
;;  its head going down (V_DIR 0), before its tail going up -- and sets the
;;  sending up (V_DMAPOS, V_DMALEN, V_MAPPEND); bst_work converts them into
;;  BST_CONV, a character at a time, each cell's tilemap into BST_MAPROW and
;;  its colours into BST_CGBUF as it finishes.  The vblank sends what is
;;  converted as it goes (bst_dmachunk).  A row off the grid (-1, 26) is
;;  none of it but its tilemap, blank.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_begin:
    REP #$20
    .a16
    LDA #0
    STA f:V_DMAPOS
    STA f:V_DMALEN
    STA f:V_CGO
    STA f:V_N
    LDX #$0000                  ; the tilemap blank
  @blank:
    STA f:BST_MAPROW, X
    INX
    INX
    CPX #6 * 64
    BCC @blank
    SEP #$20
    .a8
    LDA #0
    STA f:V_C
    STA f:V_TILES
    LDA #1
    STA f:V_MAPPEND
    STA f:V_PDONE
    LDA f:V_LROW
    JSR bst_rowvalid
    BCS :+
    RTS
:   LDA #0
    STA f:V_PDONE
    LDA f:V_LROW
    JSR bst_rowcount            ; A16 = its characters
    .a16
    STA f:V_TMP
    SEP #$20
    .a8
    LDA f:V_DIR
    REP #$20
    .a16
    BNE @up
    LDA f:V_HEAD                ; down: at the head
    STA f:V_LSTART
    CLC
    ADC f:V_TMP
    JSR bst_ringmod
    STA f:V_HEAD
    BRA @placed
  @up:
    LDA f:V_TAIL                ; up: before the tail
    SEC
    SBC f:V_TMP
    BCS :+
    ADC #RING
:   STA f:V_TAIL
    STA f:V_LSTART
  @placed:
    LDA f:V_TMP                 ; in bytes, 32 a character
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:V_DMALEN
    LDA f:V_LSTART
    STA f:V_ROWBASE
    SEP #$20
    .a8
    RTS

;;  The made row's conversion, from where it left off, until it is done --
;;  or, unless V_NOBUDGET, until the picture is nearly over (bst_late), so
;;  the frame's vblank is not missed; with V_NOBUDGET the music gets its
;;  turn after each character instead.  A8 I16, DBR this chunk.
    .a8
    .i16
bst_work:
    LDA f:V_PDONE
    BNE @out
    LDA f:V_TILES
    BEQ @next
    JSR bst_cellsrc             ; a cell part done: its picture and masks again
  @tile:
    REP #$20
    .a16
    LDA f:V_N
    TAX
    LDA f:V_SRCY
    TAY
    SEP #$20
    .a8
    JSR @conv
    REP #$20
    .a16
    TXA
    STA f:V_N
    TYA
    STA f:V_SRCY
    SEP #$20
    .a8
    LDA f:V_TILES
    DEC A
    STA f:V_TILES
    BNE @budget
    JSR bst_cellmap             ; the cell done: its tilemap and colours
    JSR bst_cellcg
    LDA f:V_C
    INC A
    STA f:V_C
  @budget:
    LDA f:V_NOBUDGET
    BEQ :+
    JSR bst_audio
    BRA @more
:   JSR bst_late
    BCS @out
  @more:
    LDA f:V_TILES
    BNE @tile
  @next:
    JSR bst_cellstart           ; C set: no cell left
    BCC @tile
    LDA #1
    STA f:V_PDONE
  @out:
    RTS
  @conv:
    JMP (CONVVEC)

;;  The next cell, V_C, begun: its enemy, its slot cell, its first ring
;;  place, its characters to convert; C set if the row has no more.  A8 I16.
    .a8
    .i16
bst_cellstart:
    LDA f:V_C
    CMP #BST_COLS
    BCC :+
    SEC                         ; no cell left
    RTS
:   LDA f:V_LROW                ; the enemy: row * 5 + column
    STA f:V_TMP
    ASL A
    ASL A
    CLC
    ADC f:V_TMP
    CLC
    ADC f:V_C
    CMP #BST_NENEMY
    BCS @none
    STA f:V_E
    ;  The slot's cell: (row mod 6) * 5 + column.
    LDA f:V_LROW
  @mod6:
    CMP #BST_SLOTS
    BCC :+
    SBC #BST_SLOTS
    BRA @mod6
:   STA f:V_TMP
    ASL A
    ASL A
    CLC
    ADC f:V_TMP
    CLC
    ADC f:V_C
    STA f:V_K
    ;  Its first ring place: the row's, plus the bytes so far / 32.
    REP #$20
    .a16
    LDA f:V_N
    LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    CLC
    ADC f:V_ROWBASE
    JSR bst_ringmod
    PHA
    LDA f:V_C
    AND #$00FF
    ASL A
    TAX
    PLA
    STA f:V_CELLPOS, X
    LDA #0
    STA f:V_SRCY
    LDA f:V_E
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstKind, X
    STA f:V_KIND
    BEQ :+                      ; KIND_SMALL: 16 characters, else 36
    LDA #36
    BRA :++
:   LDA #16
:   STA f:V_TILES
    JSR bst_cellsrc
    CLC
    RTS
  @none:
    SEC
    RTS

;;  The cell's picture, long, at SRC and +8 and +16 (the CHR and the
;;  specials never cross a bank); its conversion in CONVVEC: a special's
;;  with its masks (SEL), else its group's own (bst_convg0-4).  A8 I16.
    .a8
    .i16
bst_cellsrc:
    LDA f:V_E
    REP #$20
    .a16
    AND #$00FF
    STA f:V_TMP
    ASL A
    ADC f:V_TMP                 ; x 3
    TAX
    LDA lut_BstSrc, X
    STA SRC
    CLC
    ADC #8
    STA SRC8
    CLC
    ADC #8
    STA SRC16
    SEP #$20
    .a8
    LDA lut_BstSrc + 2, X
    STA SRC + 2
    STA SRC8 + 2
    STA SRC16 + 2
    LDA f:V_KIND
    CMP #KIND_SPECIAL
    BNE @group
    JSR bst_selmasks
    REP #$20
    .a16
    LDA #.LOWORD(bst_convspecial)
    STA CONVVEC
    SEP #$20
    .a8
    RTS
  @group:
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstCellGA, X
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA lut_BstConvG, X
    STA CONVVEC
    SEP #$20
    .a8
    RTS

;;  C set if the picture is near its end, lines WORK_LAST-224: time to stop
;;  the frame's work and wait for the vblank.  A8; DBR this chunk.
    .a8
bst_late:
    LDA a:STAT78                ; the counter's read toggle reset
    LDA a:SLHV                  ; H and V latched
    LDA a:OPVCT
    XBA
    LDA a:OPVCT
    AND #$01
    XBA
    REP #$20
    .a16
    CMP #WORK_LAST
    BCC @no
    CMP #225
    BCS @no
    SEP #$20
    .a8
    SEC
    RTS
  @no:
    SEP #$20
    .a8
    CLC
    RTS

;;  C set once the incoming row is in: converted, its characters and its
;;  tilemap sent.  A8 I16.
    .a8
    .i16
bst_loaded:
    LDA f:V_PDONE
    BEQ @no
    LDA f:V_MAPPEND
    BNE @no
    REP #$20
    .a16
    LDA f:V_DMAPOS
    CMP f:V_DMALEN
    SEP #$20
    .a8
    RTS                         ; C set: all sent
  @no:
    CLC
    RTS

;;  C set if row A is on the grid (0-25; -1 is $FF).  A kept.
bst_rowvalid:
    CMP #BST_ROWS
    BCC :+
    CLC
    RTS
:   SEC
    RTS

;;  Row A's characters: A16 out (A8 in), V_RCOUNT for it set.  X and Y
;;  clobbered.
    .a8
    .i16
bst_rowcount:
    PHA
    STA f:V_TMP
    ASL A
    ASL A
    CLC
    ADC f:V_TMP                 ; its first enemy
    REP #$20
    .a16
    AND #$00FF
    TAX
    LDA #0
    STA f:V_TMP
    SEP #$20
    .a8
    LDY #BST_COLS
  @cell:
    CPX #BST_NENEMY
    BCS @done
    LDA lut_BstKind, X
    REP #$20
    .a16
    BEQ @small
    LDA #36
    BRA @add
  @small:
    LDA #16
  @add:
    CLC
    ADC f:V_TMP
    STA f:V_TMP
    SEP #$20
    .a8
    INX
    DEY
    BNE @cell
  @done:
    PLA
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:V_TMP
    STA f:V_RCOUNT, X
    RTS
    .a8

;;  A16 mod the ring, for 0 to 2 * RING - 1.
    .a16
bst_ringmod:
    CMP #RING
    BCC :+
    SBC #RING
:   RTS
    .a8

;;  SEL from lut_BstCellSel for slot cell V_K: SEL + j * 6 + w - 1 is $FF
;;  where bit w of plane j's byte is set.  A8 I16.
    .a8
    .i16
bst_selmasks:
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    TAX
    SEP #$20
    .a8
    LDY #$0000
  @plane:
    LDA lut_BstCellSel, X
    LSR A                       ; bit 0: no value 0
    STA f:V_TMP + 1
    LDA #6
    STA f:V_I
  @w:
    LDA f:V_TMP + 1
    LSR A
    STA f:V_TMP + 1
    LDA #0
    BCC :+
    LDA #$FF
:   STA a:SEL, Y
    INY
    LDA f:V_I
    DEC A
    STA f:V_I
    BNE @w
    INX
    CPY #4 * 6
    BCC @plane
    RTS

;;  A plane's byte: the OR of value w's pixels where its mask says so, for
;;  values 1-3 (a small or large picture's), or 1-6 (a special's).
.macro PLANE3 j
    LDA M1
    AND SEL + j * 6 + 0
    STA TT
    LDA M2
    AND SEL + j * 6 + 1
    ORA TT
    STA TT
    LDA M3
    AND SEL + j * 6 + 2
    ORA TT
.endmacro
.macro PLANE6 j
    PLANE3 j
    STA TT
    LDA M4
    AND SEL + j * 6 + 3
    ORA TT
    STA TT
    LDA M5
    AND SEL + j * 6 + 4
    ORA TT
    STA TT
    LDA M6
    AND SEL + j * 6 + 5
    ORA TT
.endmacro

;;  One small or large character: 16 NES bytes at [SRC], Y into 32 SNES
;;  bytes at BST_CONV + X, value v's pixels colour 3g + v -- each group g
;;  its own routine, each plane of colour 3g + v a plain function of the
;;  NES's two (worked out below), the general masks' work being three times
;;  this.  Y and X move past it.  A8 I16.
.macro CONVTAIL
    REP #$20
    .a16
    TXA
    CLC
    ADC #16                     ; past planes 2 and 3
    TAX
    TYA
    CLC
    ADC #8                      ; past plane 1
    TAY
    SEP #$20
    .a8
    RTS
.endmacro

;;  g 0, colours 1-3 (01, 10, 11): planes 0 and 1 the NES's.
    .a8
    .i16
bst_convg0:
    LDA #8
    STA CNT
  @row:
    LDA [SRC], Y
    STA f:BST_CONV, X
    LDA [SRC8], Y
    STA f:BST_CONV + 1, X
    LDA #0
    STA f:BST_CONV + 16, X
    STA f:BST_CONV + 17, X
    INX
    INX
    INY
    DEC CNT
    BNE @row
    CONVTAIL

;;  g 1, colours 4-6 (0100, 0101, 0110): plane 0 value 2, plane 1 value 3,
;;  plane 2 any.
bst_convg1:
    LDA #8
    STA CNT
  @row:
    LDA [SRC], Y
    STA P0
    LDA [SRC8], Y
    STA P1
    AND P0
    STA f:BST_CONV + 1, X       ; value 3
    EOR P1
    STA f:BST_CONV, X           ; value 2: plane 1 alone
    LDA P0
    ORA P1
    STA f:BST_CONV + 16, X
    LDA #0
    STA f:BST_CONV + 17, X
    INX
    INX
    INY
    DEC CNT
    BNE @row
    CONVTAIL

;;  g 2, colours 7-9 (0111, 1000, 1001): plane 0 the NES's plane 0, planes
;;  1 and 2 value 1, plane 3 the NES's plane 1.
bst_convg2:
    LDA #8
    STA CNT
  @row:
    LDA [SRC], Y
    STA P0
    STA f:BST_CONV, X
    LDA [SRC8], Y
    STA f:BST_CONV + 17, X
    AND P0
    EOR P0                      ; value 1: plane 0 alone
    STA f:BST_CONV + 1, X
    STA f:BST_CONV + 16, X
    INX
    INX
    INY
    DEC CNT
    BNE @row
    CONVTAIL

;;  g 3, colours 10-12 (1010, 1011, 1100): plane 0 value 2, plane 1 values 1
;;  and 2, plane 2 value 3, plane 3 any.
bst_convg3:
    LDA #8
    STA CNT
  @row:
    LDA [SRC], Y
    STA P0
    LDA [SRC8], Y
    STA P1
    AND P0
    STA f:BST_CONV + 16, X      ; value 3
    EOR P1
    STA f:BST_CONV, X           ; value 2
    LDA P0
    EOR P1
    STA f:BST_CONV + 1, X       ; values 1 and 2
    LDA P0
    ORA P1
    STA f:BST_CONV + 17, X
    INX
    INX
    INY
    DEC CNT
    BNE @row
    CONVTAIL

;;  g 4, colours 13-15 (1101, 1110, 1111): planes 0 and 1 the NES's, 2 and 3
;;  any.
bst_convg4:
    LDA #8
    STA CNT
  @row:
    LDA [SRC], Y
    STA P0
    STA f:BST_CONV, X
    LDA [SRC8], Y
    STA f:BST_CONV + 1, X
    ORA P0
    STA f:BST_CONV + 16, X
    STA f:BST_CONV + 17, X
    INX
    INX
    INY
    DEC CNT
    BNE @row
    CONVTAIL

lut_BstConvG:
  .WORD bst_convg0, bst_convg1, bst_convg2, bst_convg3, bst_convg4

;;  One special character: 24 bytes at [SRC], Y -- three planes of w, 0-6 --
;;  into 32 at BST_CONV + X, w's pixels colour 3gA + w (1-3) or 3gB + w - 3
;;  (4-6).  Y and X move past it.  A8 I16.
    .a8
    .i16
bst_convspecial:
    LDA #8
    STA CNT
  @row:
    LDA [SRC16], Y
    STA P2
    LDA [SRC8], Y
    STA P1
    LDA [SRC], Y
    STA P0
    AND P1
    STA TT                      ; c: planes 0 and 1 both
    LDA P0
    EOR TT
    STA M1                      ; a: plane 0 alone
    LDA P1
    EOR TT
    STA M2                      ; b: plane 1 alone
    LDA P0
    ORA P1
    EOR #$FF
    AND P2
    STA M4                      ; 4: neither, and plane 2
    LDA M1
    AND P2
    STA M5                      ; 5: a and plane 2
    LDA M2
    AND P2
    STA M6                      ; 6: b and plane 2
    LDA P2
    EOR #$FF
    STA P2                      ; not plane 2
    AND TT
    STA M3                      ; 3: c alone
    LDA P2
    AND M1
    STA M1                      ; 1: a alone
    LDA P2
    AND M2
    STA M2                      ; 2: b alone
    PLANE6 0
    STA f:BST_CONV, X
    PLANE6 1
    STA f:BST_CONV + 1, X
    PLANE6 2
    STA f:BST_CONV + 16, X
    PLANE6 3
    STA f:BST_CONV + 17, X
    INX
    INX
    INY
    DEC CNT
    BEQ :+
    JMP @row
:   REP #$20
    .a16
    TXA
    CLC
    ADC #16
    TAX
    TYA
    CLC
    ADC #16                     ; past planes 1 and 2
    TAY
    SEP #$20
    .a8
    RTS

;;  Cell V_C's tilemap entries in BST_MAPROW: a small picture's 4 x 4 in the
;;  cell's middle, a large one's or a special's the whole 6 x 6; each
;;  character its ring place's, in the slot cell's palette.  A8 I16.
    .a8
    .i16
bst_cellmap:
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstCellPal, X
    ASL A
    ASL A                       ; palette bits 10-12: the high byte's 2-4
    STA f:V_PAL + 1
    LDA #0
    STA f:V_PAL
    LDA f:V_C
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:V_CELLPOS, X
    STA f:V_PLACE
    ;  The cell's first column: 1 + 6c, or one more for a small picture.
    LDA f:V_C
    AND #$00FF
    STA f:V_TMP
    ASL A
    ADC f:V_TMP
    ASL A                       ; 6c
    INC A
    STA f:V_COL
    SEP #$20
    .a8
    LDA f:V_KIND
    BNE @big
    REP #$20                    ; small: rows 1-4, columns 1-4 of the cell
    .a16
    LDA f:V_COL
    INC A
    ASL A
    CLC
    ADC #64
    STA f:V_DST
    LDA #4
    STA f:V_W
    BRA @go
  @big:
    REP #$20
    .a16
    LDA f:V_COL
    ASL A
    STA f:V_DST
    LDA #6
    STA f:V_W
  @go:
    SEP #$20
    .a8
    LDA f:V_W
    STA f:V_ROWS
  @row:
    REP #$20
    .a16
    LDA f:V_DST
    TAX
    LDA f:V_W
    STA f:V_TMP
  @col:
    LDA f:V_PLACE
    INC A                       ; the character: the place, plus one
    ORA f:V_PAL
    STA f:BST_MAPROW, X
    INX
    INX
    LDA f:V_PLACE
    INC A
    JSR bst_ringmod
    STA f:V_PLACE
    LDA f:V_TMP
    DEC A
    STA f:V_TMP
    BNE @col
    LDA f:V_DST
    CLC
    ADC #64
    STA f:V_DST
    SEP #$20
    .a8
    LDA f:V_ROWS
    DEC A
    STA f:V_ROWS
    BNE @row
    RTS

;;  Cell V_C's colours into BST_CGBUF: its group's three -- its palette's, or
;;  the silhouette's if not defeated -- and a special's second group's.  A8
;;  I16.
    .a8
    .i16
bst_cellcg:
    LDA f:V_E
    JSR bst_seen
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstCellCgA, X
    PHA
    LDA f:V_E
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstPalA, X
    TAY
    PLA
    JSR bst_group
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstCellCgB, X
    CMP #$FF
    BEQ @out
    PHA
    LDA f:V_E
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA lut_BstPalB, X
    TAY
    PLA
    JSR bst_group
  @out:
    RTS

;;  A group's three colours into BST_CGBUF: CGRAM A on, battle palette Y's
;;  colours 1-3 (V_SEEN), or the silhouette.  A8 I16 (Y's high byte junk).
    .a8
    .i16
bst_group:
    STA f:V_TMP                 ; the CGRAM index
    TYA
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    INC A                       ; the palette's colour 1
    STA f:V_PLACE
    SEP #$20
    .a8
    LDA #3
    STA f:V_I
  @colour:
    REP #$20
    .a16
    LDA f:V_CGO
    TAY                         ; into BST_CGBUF here
    LDA f:V_SEEN
    AND #$00FF
    BEQ @shadow
    LDA f:V_PLACE
    TAX
    LDA f:BTLPALFAR, X
    AND #$003F
    ASL A
    TAX
    LDA lut_BstNesCol, X
    BRA @have
  @shadow:
    LDA #SILHOUETTE
  @have:
    TYX
    STA f:BST_CGBUF + 1, X
    SEP #$20
    .a8
    LDA f:V_TMP
    STA f:BST_CGBUF, X
    INC A
    STA f:V_TMP
    REP #$20
    .a16
    TXA
    CLC
    ADC #3
    STA f:V_CGO
    LDA f:V_PLACE
    INC A
    STA f:V_PLACE
    SEP #$20
    .a8
    LDA f:V_I
    DEC A
    STA f:V_I
    BNE @colour
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Sending: a share of the made row's characters, its tilemap, its colours;
;;  a left row's tilemap cleared; the text line's characters.  In vblank or
;;  forced blank.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  Up to X bytes of the made row's characters, as many as are converted
;;  and as far as the ring's end at most.  C set once all are sent.
    .a8
    .i16
bst_dmachunk:
    REP #$20
    .a16
    TXA
    STA f:V_TMP                 ; the most
    LDA f:V_DMAPOS
    CMP f:V_DMALEN
    BCC :+
    SEP #$20
    .a8
    SEC
    RTS
    .a16
:   LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    CLC
    ADC f:V_LSTART
    JSR bst_ringmod
    STA f:V_PLACE               ; the next character's ring place
    LDA #RING
    SEC
    SBC f:V_PLACE
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; bytes to the ring's end
    CMP f:V_TMP
    BCS :+
    STA f:V_TMP
:   LDA f:V_N                   ; what is converted and not yet sent
    SEC
    SBC f:V_DMAPOS
    BNE :+
    SEP #$20                    ; none yet
    .a8
    CLC
    RTS
    .a16
:   CMP f:V_TMP
    BCS :+
    STA f:V_TMP
:   LDA f:V_PLACE
    INC A
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 16 words
    CLC
    ADC #VR_BG1CHR
    STA a:VMADDL
    LDA f:V_DMAPOS
    CLC
    ADC #.LOWORD(BST_CONV)
    STA a:A1T0L
    LDA f:V_TMP
    STA a:DAS0L
    CLC
    ADC f:V_DMAPOS
    STA f:V_DMAPOS
    SEP #$20
    .a8
    JSR bst_dmago
    REP #$20
    .a16
    LDA f:V_DMAPOS
    CMP f:V_DMALEN
    SEP #$20
    .a8
    RTS                         ; C set: all sent

;;  The DMA set up on channel 0 from bank $7F to VRAM, started.  A8.
    .a8
bst_dmago:
    LDA #$80
    STA a:VMAIN
    LDA #^BSTRAM
    STA a:A1B0
    LDA #$01                    ; two registers, $2118 then $2119
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    RTS

;;  The made row's six tilemap rows, from BST_MAPROW.  A8 I16.
    .a8
    .i16
bst_sendmap:
    LDA #0
    STA f:V_I
  @row:
    JSR bst_maprowaddr
    REP #$20
    .a16
    LDA f:V_I
    AND #$00FF
    XBA
    LSR A
    LSR A                       ; x 64 bytes
    CLC
    ADC #.LOWORD(BST_MAPROW)
    STA a:A1T0L
    LDA #64
    STA a:DAS0L
    SEP #$20
    .a8
    JSR bst_dmago
    LDA f:V_I
    INC A
    STA f:V_I
    CMP #6
    BCC @row
    RTS

;;  VMADDL: tilemap row (6 * V_LROW + V_I) mod 64.  A8 I16.
    .a8
    .i16
bst_maprowaddr:
    LDA f:V_LROW
    REP #$20
    .a16
    AND #$00FF
    STA f:V_TMP
    ASL A
    ADC f:V_TMP
    ASL A                       ; x 6
    STA f:V_TMP
    LDA f:V_I
    AND #$00FF
    CLC
    ADC f:V_TMP
    AND #63
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 32 words
    CLC
    ADC #VR_BG1MAP
    STA a:VMADDL
    SEP #$20
    .a8
    RTS

;;  Row V_CLRROW's six tilemap rows cleared.  A8 I16.
    .a8
    .i16
bst_clearmap:
    LDA f:V_LROW                ; V_LROW kept round it
    PHA
    LDA f:V_CLRROW
    STA f:V_LROW
    LDA #0
    STA f:V_I
  @row:
    JSR bst_maprowaddr
    REP #$20
    .a16
    LDA #.LOWORD(lut_BstZero)
    STA a:A1T0L
    LDA #64
    STA a:DAS0L
    SEP #$20
    .a8
    LDA #$80
    STA a:VMAIN
    LDA #^BESTIARYFAR
    STA a:A1B0
    LDA #$09                    ; fixed source
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    LDA f:V_I
    INC A
    STA f:V_I
    CMP #6
    BCC @row
    PLA
    STA f:V_LROW
    RTS

;;  BST_CGBUF's colours into CGRAM.  A8 I16.
    .a8
    .i16
bst_sendcg:
    LDX #$0000
  @colour:
    REP #$20
    .a16
    TXA
    CMP f:V_CGO
    SEP #$20
    .a8
    BCS @out
    LDA f:BST_CGBUF, X
    STA a:CGADD
    LDA f:BST_CGBUF + 1, X
    STA a:CGDATA
    LDA f:BST_CGBUF + 2, X
    STA a:CGDATA
    INX
    INX
    INX
    BRA @colour
  @out:
    RTS

;;  The text line's 60 characters, BG3 1-60.  A8 I16.
    .a8
    .i16
bst_sendtext:
    REP #$20
    .a16
    LDA #VR_BG3CHR + 8
    STA a:VMADDL
    LDA #.LOWORD(BST_TCHR)
    STA a:A1T0L
    LDA #LINE_DMA
    STA a:DAS0L
    SEP #$20
    .a8
    JMP bst_dmago


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The text line: "Bestiary (57/128)" at the left, the selected enemy's
;;  name at the right -- or "?????" -- drawn into BG3's 60 characters, each
;;  letter outlined.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
bst_textline:
    LDX #TEXT_COLS - 1
    LDA #$FF
  @blank:
    STA f:BST_LINE, X
    DEX
    BPL @blank
    LDX #$0000
  @title:
    LDA lut_BstTitle, X
    STA f:BST_LINE, X
    INX
    CPX #BST_TITLE_LEN
    BCC @title
    ;  The count, without leading zeros.
    LDA f:V_COUNT
    LDY #$0000                  ; hundreds
  @h:
    CMP #100
    BCC :+
    SBC #100
    INY
    BRA @h
:   PHA
    TYA
    BEQ :+
    ORA #$80
    STA f:BST_LINE, X
    INX
:   PLA
    LDY #$0000                  ; tens
  @t:
    CMP #10
    BCC :+
    SBC #10
    INY
    BRA @t
:   PHA
    CPX #BST_TITLE_LEN          ; a ten, or a zero after a hundred
    BNE @tens
    TYA
    BEQ @ones
  @tens:
    TYA
    ORA #$80
    STA f:BST_LINE, X
    INX
  @ones:
    PLA
    ORA #$80
    STA f:BST_LINE, X
    INX
    LDY #$0000
  @rest:
    LDA lut_BstOf, Y
    STA f:BST_LINE, X
    INX
    INY
    CPY #BST_OF_LEN
    BCC @rest
    ;  The name, at the right.
    LDA f:V_SEL
    JSR bst_seen
    LDA f:V_SEEN
    BNE @name
    LDX #$0000
  @q:
    LDA lut_BstUnknown, X
    STA f:BST_LINE + TEXT_COLS - BST_UNKNOWN_LEN, X
    INX
    CPX #BST_UNKNOWN_LEN
    BCC @q
    RTS
  @name:
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:NAMESFAR, X
    STA SRC
    SEP #$20
    .a8
    LDA #NAMEBANK
    STA SRC + 2
    LDY #$0000                  ; its length, eight at most
  @len:
    LDA [SRC], Y
    BEQ :+
    INY
    CPY #8
    BCC @len
:   TYA
    STA f:V_NAMELEN
    BEQ @done
    REP #$20
    .a16
    LDA #TEXT_COLS
    SEC
    SBC f:V_NAMELEN
    AND #$00FF
    TAX                         ; where it starts
    SEP #$20
    .a8
    LDY #$0000
  @copy:
    LDA [SRC], Y
    STA f:BST_LINE, X
    INX
    INY
    TYA
    CMP f:V_NAMELEN
    BCC @copy
  @done:
    RTS

;;  BST_G and BST_H blank: rows of TEXT_STRIDE, a blank row above the line's
;;  and below, a blank column either side of its 30, which nothing writes
;;  after.  A8 I16.
BST_GROWS = 18                  ; a blank row, 16, a blank row
    .a8
    .i16
bst_textclear:
    REP #$20
    .a16
    LDX #$0000
    LDA #0
  @clear:
    STA f:BST_G, X
    STA f:BST_H, X
    INX
    INX
    CPX #BST_GROWS * TEXT_STRIDE
    BCC @clear
    SEP #$20
    .a8
    RTS

;;  BST_LINE drawn, from column V_C0 on -- 0 the whole line, NAME_C0 the
;;  name's part, as a move redraws it (redrawing it all took two frames, and
;;  the music lagged on every move: user, 2026-11-11).  Its glyphs into
;;  BST_G's rows 1-8, widened a pixel each way into BST_H, then its
;;  characters: plane 0 the glyph and its outline (H, a row up and down),
;;  plane 1 the glyph -- colour 3 the letter, colour 1 the black round it.
;;  The font's glyphs are its colour 3, both planes.  A8 I16.
NAME_C0 = 20                    ; the name ends the line, 22-29 at the most
.assert BST_TITLE_LEN + 3 + BST_OF_LEN < NAME_C0 - 1, error, "the count runs into the name's columns"
    .a8
    .i16
bst_textrender:
    PHB
    LDA #^BSTRAM
    PHA
    PLB                         ; absolute = bank $7F
    ;  The glyphs: X the glyph's bytes, long; Y BST_G's place, row 1 on.
    LDA f:V_C0
    STA f:V_TC
  @col:
    LDA f:V_TC
    REP #$20
    .a16
    AND #$00FF
    TAX
    CLC
    ADC #TEXT_STRIDE
    TAY
    SEP #$20
    .a8
    LDA #8
    STA CNT
    LDA f:BST_LINE, X
    CMP #CH_LPAREN
    BCC @font
    CMP #CH_SLASH + 1
    BCS @font
    SEC                         ; a custom glyph: lut_BstGlyphs
    SBC #CH_LPAREN
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAX
    SEP #$20
    .a8
  @cust:
    LDA f:BESTIARYFAR + lut_BstGlyphs, X
    STA a:.LOWORD(BST_G), Y
    JSR @down
    BNE @cust
    BRA @next
  @font:
    CMP #$80
    BCS @fontglyph
  @nil:                         ; (nothing below the font: blank)
    LDA #0
    STA a:.LOWORD(BST_G), Y
    JSR @down
    BNE @nil
    BRA @next
  @fontglyph:
    SEC
    SBC #$80
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    TAX                         ; the glyph's 16 bytes
    SEP #$20
    .a8
  @glyph:
    LDA f:MENUCHR, X
    AND f:MENUCHR + 8, X        ; colour 3: the glyph
    STA a:.LOWORD(BST_G), Y
    JSR @down
    BNE @glyph
  @next:
    LDA f:V_TC
    INC A
    STA f:V_TC
    CMP #TEXT_COLS
    BCC @col
    BRA @widen
  ;  The glyph's next byte, a row down BST_G; Z set after the eighth.
  @down:
    INX
    REP #$20
    .a16
    TYA
    CLC
    ADC #TEXT_STRIDE
    TAY
    SEP #$20
    .a8
    DEC CNT
    RTS

  @widen:
    ;  H, rows 1-8 from a column before V_C0 (its right edge takes from
    ;  V_C0's): each byte widened a pixel left and right, carrying across
    ;  the bytes; a byte with nothing near it stays blank.
    LDA f:V_C0
    BEQ :+
    DEC A
:   STA f:V_TC1
    REP #$20
    .a16
    LDA #TEXT_STRIDE
    STA f:V_DST                 ; the row's start
  @wrow:
    REP #$20                    ; (the loop comes back 8-bit)
    .a16
    LDA f:V_TC1
    AND #$00FF
    CLC
    ADC f:V_DST
    TAX
    LDA f:V_DST
    CLC
    ADC #TEXT_COLS
    STA SRC16                   ; the row's end
    SEP #$20
    .a8
  @wb:
    LDA a:.LOWORD(BST_G) - 1, X
    ORA a:.LOWORD(BST_G), X
    ORA a:.LOWORD(BST_G) + 1, X
    BEQ @wz
    LDA a:.LOWORD(BST_G), X
    STA TT
    LSR A
    ORA TT
    STA P0
    LDA TT
    ASL A
    ORA P0
    STA P0
    LDA a:.LOWORD(BST_G) - 1, X
    LSR A                       ; its right pixel into C...
    LDA #0
    ROR A                       ; ...onto this one's left
    ORA P0
    STA P0
    LDA a:.LOWORD(BST_G) + 1, X
    ASL A                       ; its left pixel into C...
    LDA #0
    ROL A                       ; ...onto this one's right
    ORA P0
  @wz:
    STA a:.LOWORD(BST_H), X
    INX
    CPX SRC16
    BCC @wb
    REP #$20
    .a16
    LDA f:V_DST
    CLC
    ADC #TEXT_STRIDE
    STA f:V_DST
    CMP #9 * TEXT_STRIDE
    SEP #$20
    .a8
    BCC @wrow
    ;  The characters, both rows of them, from the same column: n = row *
    ;  30 + column, 16 bytes each in BST_TCHR; BST_G's and BST_H's place
    ;  (row * 8 + 1) * TEXT_STRIDE + column.
    LDA #0
    STA f:V_TR
  @trow:
    LDA f:V_TC1
    STA f:V_TC
  @tch:
    LDA f:V_TR
    BEQ :+
    LDA #TEXT_COLS
:   CLC
    ADC f:V_TC
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
    LDA f:V_TR
    REP #$20
    .a16
    AND #$00FF
    XBA                         ; x 8 x TEXT_STRIDE
    CLC
    ADC #TEXT_STRIDE
    STA SRC16
    LDA f:V_TC
    AND #$00FF
    CLC
    ADC SRC16
    TAY
    SEP #$20
    .a8
    LDA #8
    STA CNT
  @line:
    LDA a:.LOWORD(BST_H) - TEXT_STRIDE, Y
    ORA a:.LOWORD(BST_H), Y
    ORA a:.LOWORD(BST_H) + TEXT_STRIDE, Y
    STA a:.LOWORD(BST_TCHR), X
    LDA a:.LOWORD(BST_G), Y
    STA a:.LOWORD(BST_TCHR) + 1, X
    INX
    INX
    REP #$20
    .a16
    TYA
    CLC
    ADC #TEXT_STRIDE
    TAY
    SEP #$20
    .a8
    DEC CNT
    BNE @line
    LDA f:V_TC
    INC A
    STA f:V_TC
    CMP #TEXT_COLS
    BCC @tch
    LDA f:V_TR
    INC A
    STA f:V_TR
    CMP #2
    BCC @trow
    PLB
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Data.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_BstZero:
  .WORD 0

;  CGRAM 1-3, BG3's palette 0: the outline, unused, the letters.
lut_BstTextPal:
  .WORD $0000, NESCOL_00, NESCOL_30

;  OBJ palette 1, the hand: the game's cursor colours, as the map edit
;  screen's.
lut_BstHandPal:
  .WORD NESCOL_0F, NESCOL_30, NESCOL_10, NESCOL_00

lut_BstHandCell:
  .BYTE OBJ_HAND, OBJ_HAND + 1, OBJ_HAND + 16, OBJ_HAND + 17

;  NES colour -> CGRAM.
lut_BstNesCol:
  .WORD NESCOL_00, NESCOL_01, NESCOL_02, NESCOL_03, NESCOL_04, NESCOL_05, NESCOL_06, NESCOL_07
  .WORD NESCOL_08, NESCOL_09, NESCOL_0A, NESCOL_0B, NESCOL_0C, NESCOL_0D, NESCOL_0E, NESCOL_0F
  .WORD NESCOL_10, NESCOL_11, NESCOL_12, NESCOL_13, NESCOL_14, NESCOL_15, NESCOL_16, NESCOL_17
  .WORD NESCOL_18, NESCOL_19, NESCOL_1A, NESCOL_1B, NESCOL_1C, NESCOL_1D, NESCOL_1E, NESCOL_1F
  .WORD NESCOL_20, NESCOL_21, NESCOL_22, NESCOL_23, NESCOL_24, NESCOL_25, NESCOL_26, NESCOL_27
  .WORD NESCOL_28, NESCOL_29, NESCOL_2A, NESCOL_2B, NESCOL_2C, NESCOL_2D, NESCOL_2E, NESCOL_2F
  .WORD NESCOL_30, NESCOL_31, NESCOL_32, NESCOL_33, NESCOL_34, NESCOL_35, NESCOL_36, NESCOL_37
  .WORD NESCOL_38, NESCOL_39, NESCOL_3A, NESCOL_3B, NESCOL_3C, NESCOL_3D, NESCOL_3E, NESCOL_3F

lut_BstTitle:
  FFTEXT "Bestiary "
  .BYTE CH_LPAREN
BST_TITLE_LEN = * - lut_BstTitle
lut_BstOf:
  .BYTE CH_SLASH
  FFTEXT "128"
  .BYTE CH_RPAREN
BST_OF_LEN = * - lut_BstOf
lut_BstUnknown:
  FFTEXT "?????"
BST_UNKNOWN_LEN = * - lut_BstUnknown

;  The font's missing glyphs, drawn as its are: rows 1-7, columns 1-7.
lut_BstGlyphs:
  .BYTE $00, $0C, $18, $30, $30, $30, $18, $0C       ; (
  .BYTE $00, $30, $18, $0C, $0C, $0C, $18, $30       ; )
  .BYTE $00, $06, $06, $0C, $18, $30, $60, $60       ; /
