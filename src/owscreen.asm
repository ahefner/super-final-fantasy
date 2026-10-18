; ---------------------------------------------------------------------------
;  owscreen.asm -- New Game's map edit screen (CHUNK_OWS).
;
;  Each of FFR's fourteen overworld edits a checkbox, and the world's minimap
;  as the boxes ticked would make it (user, 2026-10-18), with a zoom of the
;  selected edit.  Two layouts, on two branches (owslayout.inc): the minimap
;  above a grid, or beside a column.
;
;  From rando_newgame when the Map edits row is not Off, which then writes
;  the row's flags into RANDO_OWEDITS.  The screen starts from the saved
;  game's, when Continue would load it and it has any -- so the choice
;  carries from game to game without a byte of the option block -- else the
;  row's.  START ends it, and RANDO_OWEDITS is what is ticked: placement's
;  logic knows every edit (worldgraph/edited.py) -- but not on edits that,
;  with the rest of the settings, make a world that cannot be won
;  (rando_winnable, user): then the description says so, and the screen
;  stays.  New Game brings it up for that alone, the row Off, when the
;  settings as they are cannot be won.  The title's music plays on
;  throughout, the check's frames too (ows_tick).
;
;  The pad is read every frame and answered at once -- the hand moves, a box
;  ticks, the description changes, the settings screen's chirp -- and the
;  pictures follow as the frames allow (user: crisp and responsive).  Each
;  frame draws at most a pixel row of the minimap and a map row of the zoom,
;  from queues a press adds to.  The screen comes up whole, though (user):
;  the unedited minimap is in ROM, drawn at build time (lut_OwsBaked), and
;  only the rows the ticked boxes change are drawn over it, with the first
;  zoom, before the display goes on.  L + X and L + Y reset from here as
;  from anywhere (user).
;
;  The minimap is the world's, decoded here from the game's own RLE rows and
;  edited from world.asm's tables as ow_edit edits the game's, so it shows
;  what the game will.  A row decodes straight to the game's minimap colours
;  (lut_OwsTiles, bank $09's), a run's colour looked up once, with bit 3 set
;  on each tile the selected setting writes; a pixel ORs its four tiles'.
;  The selection's pixels flash, and rings mark its places.  For Bahamut's
;  dock and the land bridge, which the other's box changes, what is marked
;  and zoomed follows that box (genows.py's views).
;
;  Like the credits and the roll screen it takes the PPU from the HAL and
;  gives it back through hal_ppureclaim: mode 1, the minimap and the zoom on
;  BG1, the text on BG3 in the game's font with the settings screen's
;  checkboxes, the hand and the rings as sprites.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "fftext.inc"
.include "nescol.inc"
.include "owslayout.inc"
;  CALL0E, for the menu chirps in bank $0E.
.include "optcall.inc"

.export ows_choose, ows_tick
;  For tools/test_options.py.
.export ows_testprow, ows_testinset, ows_testsetup, lut_OwsTiles, lut_OwsBaked

.import UpdateJoy, CallMusicPlay
.import hal_vblaudio, hal_audioframe, hal_auxdetect, hal_ppureclaim
.import opt_savevalidfar, opt_padreset, rando_winnable
.import OptCallFar, PlaySFX_MenuMove, PlaySFX_MenuSel
.import lut_OweRow, lut_OweEnt
.importzp OWE_ENTRY

.segment "BANK_OWS"

.include "owscreen.inc"

MENUCHR   = (CHUNK0 + BANK_MENUCHR) * $10000 + $8800    ; the font, tiles $80-$FF
HANDCHR   = (CHUNK0 + BANK_BTLCHR) * $10000 + lut_BatObjCHR + ($F0 - $80) * 16
OWMAP     = (CHUNK0 + BANK_OWMAP) * $10000             ; its $8000: the rows' pointers
SAVEDOWE  = (CHUNK0 * $10000) + sram + (RANDO_OWEDITS - unsram)   ; the saved game's

;  VRAM, in words.
VR_BG1CHR = $0000               ; the minimap's 256 characters, then the zoom's 49
VR_BG3CHR = $2000               ; the font at its own numbers, the boxes at 1 and 2
VR_BG1MAP = $3000
VR_BG3MAP = $3400
VR_OBJCHR = $4000               ; the ring at 0, the hand at 2
BG1_BLANK = 511                 ; a character nothing writes
FRAME_CHR = 3                   ; BG3: the frame's eight, $F7-$FE in order
FRAME_PAL = 2
INSET_CHR = 256
OBJ_RING  = 0
OBJ_HAND  = 2

;  Where things are, in BG cells, inside the 30x26 a CRT shows.  A
;  setting's line: the hand two cells before its box, the name straight
;  after -- the hand over the minimap's edge, or over the end of a long
;  name in the grid's left column, where the 30 run out (user: rather
;  that than shorter names).  The zoom in the game's dialog box frame, a
;  cell all round (user).
.if OWS_SIDE
MAP_COL   = 1                   ; rows 1-16, the column's 2-15 (lut_OwsCell)
MAP_ROW   = 1
INSET_COL = 2
INSET_ROW = 18
TITLE_COL = 11
TITLE_ROW = 18
DESC_COL  = 11
DESC_ROW  = 20
DESC_W    = OWS_DESCNARROW
DESC_N    = 5
.else
MAP_COL   = 10
MAP_ROW   = 1
INSET_COL = 2
INSET_ROW = 5
TITLE_COL = 26
TITLE_ROW = 6
DESC_COL  = 1
DESC_ROW  = 25
DESC_W    = OWS_DESCWIDE
DESC_N    = 2
.endif
NAME_W    = 13
INSET_W   = 7                   ; cells
INSET_PX  = INSET_W * 8
.assert INSET_COL >= 2 && INSET_COL + INSET_W <= 30, error, "the zoom's frame inside the 30 columns"

;  Work a frame, in units of about 2000 instructions: a pixel row of the
;  minimap is three, a map row of the zoom two.  Four leaves the heaviest
;  frame near three quarters of one.
BUDGET    = 4
COST_ROW  = 3
COST_ZOOM = 2

;  The game's pad bits.
PAD_A     = $80
PAD_START = $10
PAD_UP    = $08
PAD_DOWN  = $04
PAD_LEFT  = $02
PAD_RIGHT = $01

;  The variables, in bank $7F.  Long, or with DBR = $7F as their low words.
OWV       = OWS_VARS
V_FLAGS   = OWV+$00             ; 2: the boxes ticked, OWEDIT_* bits
V_ACTIVE  = OWV+$02             ; 2: the lists they apply
V_HLMASK  = OWV+$04             ; 2: the selected view's gates
V_SEL     = OWV+$06             ; the selected setting, 0-13
V_PREV    = OWV+$07             ; the pad last frame
V_T       = OWV+$09             ; frames
V_SITE    = OWV+$0A             ; which of the view's places the zoom shows
V_IACTIVE = OWV+$0B             ; nonzero: the zoom being drawn
V_INSETD  = OWV+$0C             ; nonzero: send it
V_NTD     = OWV+$0D             ; nonzero: send BG3's tilemap
V_QUEUE   = OWV+$10             ; 16: pixel rows to draw, a bit each
V_DIRTY   = OWV+$20             ; 2: character rows to send, a bit each
V_P0      = OWV+$23             ; ...$26: a character row's four planes
V_COL     = OWV+$27
V_TILE    = OWV+$28             ; 2
V_X0      = OWV+$2A
V_Y0      = OWV+$2B
V_SCALE   = OWV+$2C             ; 2: 1 or 2, its high byte zero
V_SPAN    = OWV+$2E
V_IROW    = OWV+$2F             ; the zoom's next map row
V_ROWNUM  = OWV+$30
V_N       = OWV+$31
V_T8      = OWV+$32
V_XJ      = OWV+$33
V_DST     = OWV+$34             ; 2
V_EEND    = OWV+$38             ; 2
V_PROW    = OWV+$3C
V_PAL     = OWV+$3D
V_BUDGET  = OWV+$3E
V_R       = OWV+$3F             ; the zoom's next pixel row
V_VADDR   = OWV+$40             ; 2
V_K       = OWV+$42
V_VIEW    = OWV+$43             ; what the selection shows: lut_OwsGates's, the sites'
V_MASK    = OWV+$44             ; 2: ows_prow's characters still to pack, a bit each
V_FORCED  = OWV+$46             ; ows_choose's A: OWS_FORCED and the warning's reason, or 0
.assert V_FORCED < OWS_VARS + $100, error, "the screen's variables outgrow their page"

;  The same, with DBR = $7F.
aACTIVE   = .LOWORD(V_ACTIVE)
aHLMASK   = .LOWORD(V_HLMASK)
aP0       = .LOWORD(V_P0)
aCOL      = .LOWORD(V_COL)
aTILE     = .LOWORD(V_TILE)
aROWNUM   = .LOWORD(V_ROWNUM)
aT8       = .LOWORD(V_T8)
aDST      = .LOWORD(V_DST)
aEEND     = .LOWORD(V_EEND)
aXJ       = .LOWORD(V_XJ)
aSCALE    = .LOWORD(V_SCALE)
aR        = .LOWORD(V_R)
aMASK     = .LOWORD(V_MASK)
aROW      = .LOWORD(OWS_ROW)
aROW1     = .LOWORD(OWS_ROW1)
aCHR      = .LOWORD(OWS_CHR)
aINSETCHR = .LOWORD(OWS_INSETCHR)

.macro DB_RAM
    LDA #^OWSRAM
    PHA
    PLB
.endmacro


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_choose -- the screen.  In: RANDO_OWEDITS the row's flags; A = 0, or
;;  OWS_FORCED and rando_winnable's reason, up only because the settings
;;  cannot be won: the row's flags then, not the saved game's, and the
;;  warning at once.  Out: RANDO_OWEDITS as ticked.  From
;;  rando_newgame, by JSL, in emulation mode; out the same, X and Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ows_choose:
    PHP
    PHX
    PHY
    PHB
    PHK
    PLB                         ; this chunk's low half is the I/O map
    SEP #$30
    STA f:V_FORCED
    CMP #OWS_FORCED
    BCS @forced                 ; the row's, not the saved game's
    JSL opt_savevalidfar + OPTFAR       ; C clear: a save Continue would load
    LDA #0
    ROL A
    PHA
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    PLA
    BNE @row
    LDA f:SAVEDOWE
    ORA f:SAVEDOWE + 1
    BEQ @row
    BRA @saved
  @forced:
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    BRA @row
  @saved:
    REP #$20
    .a16
    LDA f:SAVEDOWE
    BRA @have
  @row:
    REP #$20
    .a16
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
  @have:
    AND #OWEDIT_FLAGS
    STA f:V_FLAGS
    SEP #$20
    .a8
    JSR ows_setup
    JSR ows_loop
    REP #$20
    .a16
    LDA f:V_FLAGS
    AND #OWEDIT_FLAGS
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    LDA #$80
    STA a:INIDISP
    JSL hal_ppureclaim + HALFAR
    PLB
    PLY
    PLX
    PLP
    RTL


;;  For the harness: pixel row A of the minimap, and the whole zoom and the
;;  sprites, as the screen draws them, and the screen's setup, as far as the display going
;;  on; from emulation mode by JSL, V_FLAGS, V_SEL and V_SITE as it set them.
ows_testprow:
    PHB
    PHK
    PLB
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    PHA
    JSR ows_actives
    JSR ows_select
    PLA
    JSR ows_prow
    BRA ows_testout
ows_testsetup:
    PHB
    PHK
    PLB
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    LDA #0
    STA f:V_FORCED
    JSR ows_setup
    BRA ows_testout
ows_testinset:
    PHB
    PHK
    PLB
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    JSR ows_actives
    LDA f:V_SITE                ; ows_select starts at the first place
    PHA
    JSR ows_select
    PLA
    STA f:V_SITE
    JSR ows_insetstart
  @slice:
    JSR ows_insetrow
    LDA f:V_IACTIVE
    BNE @slice
    JSR ows_sprites             ; and the hand and the rings
ows_testout:
    SEP #$30
    .i8
    SEC
    XCE
    PLB
    RTL


;;  The lists V_FLAGS applies, as owedits.py's active_lists.
    .a8
    .i16
ows_actives:
    REP #$20
    .a16
    LDA f:V_FLAGS
    AND #OWEDIT_FLAGS
    BIT #OWEDIT_CARDIABRIDGE
    BEQ :+
    BIT #OWEDIT_BAHAMUTDOCK
    BEQ :+
    EOR #OWEDIT_BAHAMUTDOCK | OWE_BAHAMUTBRIDGE
:   STA f:V_ACTIVE
    SEP #$20
    .a8
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Setup: in forced blank, VRAM, CGRAM, OAM and the registers; the text,
;;  the minimap and the zoom drawn and sent, the display on.  A8 I16, DBR
;;  this chunk.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_setup:
    JSR ows_wait                ; the top of a vblank, so nothing tears
    LDA #$80
    STA a:INIDISP
    STZ a:HDMAEN
    ;  VRAM all zero: every character blank.
    LDA #$80
    STA a:VMAIN
    REP #$20
    .a16
    STZ a:VMADDL
    LDA #.LOWORD(lut_Zero)
    STA a:A1T0L
    STZ a:DAS0L                 ; 0: 64KB
    SEP #$20
    .a8
    LDA #^OWSFAR
    STA a:A1B0
    LDA #$09                    ; fixed source, two registers
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    ;  The font: NES CHR, its glyphs colour 3 on 2.  As SNES 2bpp, a row's
    ;  planes a word: the glyph colour 1, the rest 0, so clear.
    REP #$20
    .a16
    LDA #VR_BG3CHR + $80 * 8
    STA a:VMADDL
    SEP #$20
    .a8
    LDX #$0000
  @font:
    LDY #8
  @fontrow:
    LDA f:MENUCHR, X
    AND f:MENUCHR + 8, X        ; both planes: colour 3, the glyph
    STA a:VMDATAL
    STZ a:VMDATAH
    INX
    DEY
    BNE @fontrow
    REP #$20
    .a16
    TXA
    CLC
    ADC #8
    TAX
    SEP #$20
    .a8
    CPX #$80 * 16
    BCC @font
    ;  The boxes, characters 1 and 2.
    REP #$20
    .a16
    LDA #VR_BG3CHR + 8
    STA a:VMADDL
    LDX #$0000
  @box:
    LDA f:OWSFAR + lut_OwsBoxChr, X
    STA a:VMDATAL
    INX
    INX
    CPX #32
    BCC @box
    SEP #$20
    .a8
    ;  The dialog box frame, characters 3-10: the font's $F7-$FE, all four
    ;  colours, as DrawBox draws them.
    REP #$20
    .a16
    LDA #VR_BG3CHR + FRAME_CHR * 8
    STA a:VMADDL
    SEP #$20
    .a8
    LDX #($F7 - $80) * 16
  @frame:
    LDY #8
  @framerow:
    LDA f:MENUCHR, X
    STA a:VMDATAL
    LDA f:MENUCHR + 8, X
    STA a:VMDATAH
    INX
    DEY
    BNE @framerow
    REP #$20
    .a16
    TXA
    CLC
    ADC #8
    TAX
    SEP #$20
    .a8
    CPX #($FE - $80 + 1) * 16
    BCC @frame
    JSR ows_objchr
    JSR ows_bg1map
    ;  CGRAM.
    STZ a:CGADD
    LDX #$0000
  @pal:
    LDA f:OWSFAR + lut_OwsPal, X
    STA a:CGDATA
    INX
    CPX #lut_OwsPalEnd - lut_OwsPal
    BCC @pal
    LDA #128
    STA a:CGADD
    LDX #$0000
  @objpal:
    LDA f:OWSFAR + lut_OwsObjPal, X
    STA a:CGDATA
    INX
    CPX #lut_OwsObjPalEnd - lut_OwsObjPal
    BCC @objpal
    ;  OAM: every sprite below the picture; the hand and four rings large.
    STZ a:OAMADDL
    STZ a:OAMADDH
    LDX #$0000
  @oam:
    LDA #0
    STA a:OAMDATA
    LDA #224
    STA a:OAMDATA
    LDA #0
    STA a:OAMDATA
    STA a:OAMDATA
    INX
    CPX #128
    BCC @oam
    LDA #$AA                    ; sprites 0-3 large
    STA a:OAMDATA
    LDA #$02                    ; and 4
    STA a:OAMDATA
    LDX #$0002
  @oamhi:
    STZ a:OAMDATA
    INX
    CPX #32
    BCC @oamhi
    ;  The registers.
    LDA #$09
    STA a:BGMODE                ; mode 1, BG3 above
    STZ a:MOSAIC
    LDA #(VR_BG1MAP >> 8)
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
    STA a:BG1VOFS
    LDA #$03
    STA a:BG1VOFS
    LDA #$FF
    STA a:BG3VOFS
    LDA #$03
    STA a:BG3VOFS
    LDA #$15
    STA a:TM                    ; BG1, BG3, sprites
    STZ a:TS
    STZ a:TMW
    STZ a:TSW
    STZ a:W12SEL
    STZ a:CGWSEL
    STZ a:CGADSUB
    ;  The state: the first setting selected, nothing queued.
    LDA #0
    STA f:V_SEL
    STA f:V_T
    STA f:V_INSETD
    REP #$20
    .a16
    LDA #0
    STA f:V_DIRTY
    STA f:V_SCALE               ; its high byte stays zero
    LDX #14
  @q:
    STA f:V_QUEUE, X
    DEX
    DEX
    BPL @q
    LDX #0
  @nt:
    STA f:OWS_NT3, X
    INX
    INX
    CPX #28 * 64
    BCC @nt
    SEP #$20
    .a8
    JSR ows_actives
    JSR ows_select              ; V_VIEW, V_HLMASK; the zoom started
    LDA #$FF
    STA f:V_PREV                ; nothing counts as pressed until let go
    JSR ows_drawall
    LDA f:V_FORCED              ; up for the warning: it, not the description
    BPL :+
    AND #$7F
    JSR ows_warn
:   JSR ows_first
    JSR ows_vblank              ; the tilemap, the zoom and the hand out
    LDA #$0F
    STA a:INIDISP
    RTS

;;  The pictures whole before the display goes on (user: at once, not drawn
;;  while you watch).  The minimap unedited, from ROM; over it the rows the
;;  ticked boxes and the selection change; the zoom; and the minimap sent.
;;  In forced blank, a few frames of it with much ticked, the music kept
;;  going meanwhile.  A8 I16.
    .a8
    .i16
ows_first:
    PHB
    REP #$20
    .a16
    LDX #.LOWORD(lut_OwsBaked)
    LDY #.LOWORD(OWS_CHR)
    LDA #256 * 32 - 1
    MVN #^OWSFAR, #^OWSRAM      ; leaves DBR = $7F, which PLB puts back
    LDA #0                      ; B zero, as the rest expect
    SEP #$20
    .a8
    PLB
    ;  The rows each ticked box's lists write, and the selection's.
    LDA #0
    STA f:V_K
  @tick:
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsBit16, X
    AND f:V_FLAGS
    SEP #$20
    .a8
    BEQ :+
    LDA f:V_K
    JSR ows_queuerows
:   LDA f:V_K
    INC A
    STA f:V_K
    CMP #OWS_SETTINGS
    BCC @tick
    LDA f:V_SEL
    JSR ows_queuerows
  @draw:
    JSR ows_audio
    JSR ows_nextrow
    BCC @draw
.if OWS_INSET
  @zoom:
    JSR ows_audio
    JSR ows_insetrow            ; the last asks ows_vblank to send it
    LDA f:V_IACTIVE
    BNE @zoom
.endif
    REP #$20
    .a16
    LDA #0
    STA f:V_DIRTY               ; all of it, now
    LDA #VR_BG1CHR
    STA f:V_VADDR
    LDX #.LOWORD(OWS_CHR)
    LDY #256 * 32
    SEP #$20
    .a8
    JMP ows_dma

;;  A frame of the title's music, if a vblank has begun since the last look
;;  (RDNMI's latch), as roll.asm keeps its sound going while the randomizer
;;  works: for work longer than a frame.  A8 I16 in and out; X and Y not
;;  kept.
    .a8
    .i16
ows_audio:
    LDA a:RDNMI
    BPL @out
    SEP #$30
    .i8
    SEC
    XCE
    LDA #CHUNK_OWS
    STA cur_bank
    JSR CallMusicPlay
    JSL hal_audioframe + HALFAR
    CLC
    XCE
    REP #$10
    .i16
  @out:
    RTS

;;  The ring and the hand, OBJ characters 0, 1, 16, 17 and 2, 3, 18, 19: the
;;  ring from lut_OwsRingChr, 4bpp; the hand the game's (battle object CHR
;;  $F0-$F3, which DrawCursor draws), NES 2bpp as planes 0 and 1.  A8 I16.
    .a8
    .i16
ows_objchr:
    LDY #$0000
  @tile:
    REP #$20
    .a16
    TYA
    TAX
    LDA f:OWSFAR + lut_OwsObjCell, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC #VR_OBJCHR
    STA a:VMADDL
    TYA
    CMP #4
    BCS @hand
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    TAX                         ; the ring's 32 bytes
    LDA #16
    STA f:V_K
  @ring:
    LDA f:OWSFAR + lut_OwsRingChr, X
    STA a:VMDATAL
    INX
    INX
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @ring
    BRA @next
  @hand:
    SEC
    SBC #4
    ASL A
    ASL A
    ASL A
    ASL A                       ; the hand's 16 NES bytes
    TAX
    LDA #8
    STA f:V_K
  @handrow:
    SEP #$20
    .a8
    LDA f:HANDCHR, X
    STA a:VMDATAL
    LDA f:HANDCHR + 8, X
    STA a:VMDATAH
    REP #$20
    .a16
    INX
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @handrow
    LDX #8
  @zero:
    STZ a:VMDATAL
    DEX
    BNE @zero
  @next:
    SEP #$20
    .a8
    INY
    CPY #8
    BCC @tile
    RTS

;;  BG1's map: blank everywhere but the minimap's 16x16 and the zoom's 7x7.
;;  A8 I16.
    .a8
    .i16
ows_bg1map:
    REP #$20
    .a16
    LDA #VR_BG1MAP
    STA a:VMADDL
    LDX #$0000
  @bg1:
    LDA #BG1_BLANK
    STA a:VMDATAL
    INX
    CPX #32 * 32
    BCC @bg1
    LDY #$0000                  ; the minimap's cell, 0-255
  @mmrow:
    TYA
    AND #$00F0
    ASL A                       ; its row, times 32
    CLC
    ADC #VR_BG1MAP + MAP_ROW * 32 + MAP_COL
    STA a:VMADDL
    LDX #16
  @mmcell:
    TYA
    ORA #$0800                  ; palette 2
    STA a:VMDATAL
    INY
    DEX
    BNE @mmcell
    CPY #256
    BCC @mmrow
.if OWS_INSET
    LDY #$0000                  ; the zoom's cell, 0-48
    LDA #VR_BG1MAP + INSET_ROW * 32 + INSET_COL
    STA f:V_VADDR
  @inrow:
    LDA f:V_VADDR
    STA a:VMADDL
    CLC
    ADC #32
    STA f:V_VADDR
    LDX #INSET_W
  @incell:
    TYA
    CLC
    ADC #INSET_CHR | $0800
    STA a:VMDATAL
    INY
    DEX
    BNE @incell
    CPY #INSET_W * INSET_W
    BCC @inrow
.endif
    SEP #$20
    .a8
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The loop: a frame, its vblank's transfers, the pad, then this frame's
;;  share of the drawing.  Out when START is pressed.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_loop:
  @frame:
    JSR ows_wait
    JSR ows_vblank
    JSR ows_reset
    LDA f:V_T
    INC A
    STA f:V_T
    JSR ows_input
    BCS @done
    JSR ows_work
    BRA @frame
  @done:
    RTS

;;  The title's music on, the game's pad reader, then the top of the next
;;  vblank: all game code in emulation mode.  cur_bank is where
;;  CallMusicPlay swaps back to.  A8 I16 in and out.
    .a8
    .i16
ows_wait:
    SEP #$30
    .i8
    SEC
    XCE
    LDA #CHUNK_OWS
    STA cur_bank
    JSR CallMusicPlay
    JSR UpdateJoy
    JSL hal_vblaudio + HALFAR
    CLC
    XCE
    REP #$10
    .i16
    RTS

;;  Controller Reset, as WaitForVBlank takes it (waitvbl.patch): the HAL's
;;  look at L, X and Y, which hal_vblaudio leaves out, then opt_padreset to
;;  act on it, which stirs the seed's pool too, as every frame of the game's
;;  menus does.  When it is going to reset, the PPU goes back to the HAL
;;  first, as leaving the screen gives it back.  After the vblank's
;;  transfers, which the auto-read is long done by.  A8 I16 in and out; X
;;  and Y not kept.
    .a8
    .i16
ows_reset:
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

;;  The vblank's work: the flash, the tilemap, the zoom or two character rows
;;  of the minimap, the hand and the rings.  A8 I16, DBR this chunk.
    .a8
    .i16
ows_vblank:
    LDA #40                     ; the selection's pixels flash, sixteen frames each way
    STA a:CGADD
    LDX #$0000
    LDA f:V_T
    AND #$10
    BEQ :+
    LDX #lut_OwsFlash - lut_OwsPal - 80
:   LDY #10
  @flash:
    LDA f:OWSFAR + lut_OwsPal + 80, X
    STA a:CGDATA
    INX
    DEY
    BNE @flash
    LDA f:V_NTD
    BEQ @inset
    LDA #0
    STA f:V_NTD
    REP #$20
    .a16
    LDA #VR_BG3MAP
    STA f:V_VADDR
    LDX #.LOWORD(OWS_NT3)
    LDY #28 * 64
    SEP #$20
    .a8
    JSR ows_dma
  @inset:
.if OWS_INSET
    LDA f:V_INSETD
    BEQ @rows
    LDA #0
    STA f:V_INSETD
    REP #$20
    .a16
    LDA #VR_BG1CHR + INSET_CHR * 16
    STA f:V_VADDR
    LDX #.LOWORD(OWS_INSETCHR)
    LDY #INSET_W * INSET_W * 32
    SEP #$20
    .a8
    JSR ows_dma
    BRA @sprites                ; that is the vblank's worth
.endif
  @rows:
    LDA #2
    STA f:V_K
  @row:
    REP #$20
    .a16
    LDA f:V_DIRTY
    BEQ @rowsdone
    LDX #$0000
  @bit:
    LSR A
    BCS @send
    INX
    BRA @bit
  @send:
    SEP #$20
    .a8
    JSR ows_sendrow             ; character row X
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @row
  @rowsdone:
    SEP #$20
    .a8
  @sprites:
    JMP ows_sprites

;;  Character row X of the minimap to VRAM, its dirty bit cleared.  A8 I16.
    .a8
    .i16
ows_sendrow:
    REP #$20
    .a16
    TXA
    STA f:V_TILE                ; the row
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsBit16, X
    EOR #$FFFF
    AND f:V_DIRTY
    STA f:V_DIRTY
    LDA f:V_TILE
    XBA                         ; x 256 words
    CLC
    ADC #VR_BG1CHR
    STA f:V_VADDR
    LDA f:V_TILE
    XBA
    ASL A                       ; x 512 bytes
    CLC
    ADC #.LOWORD(OWS_CHR)
    TAX
    LDY #512
    SEP #$20
    .a8
    JMP ows_dma

;;  Y bytes from bank $7F's X to VRAM V_VADDR.  A8 I16.
    .a8
    .i16
ows_dma:
    LDA #$80
    STA a:VMAIN
    REP #$20
    .a16
    LDA f:V_VADDR
    STA a:VMADDL
    STX a:A1T0L
    STY a:DAS0L
    SEP #$20
    .a8
    LDA #^OWSRAM
    STA a:A1B0
    LDA #$01
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    RTS

;;  OAM: the hand at the selected line, two cells before its box, as the
;;  settings screen has it; then the selection's places ringed, blinking.
;;  A8 I16.
    .a8
    .i16
ows_sprites:
    STZ a:OAMADDL
    STZ a:OAMADDH
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsCell, X   ; the box's tilemap byte: (row * 32 + col) * 2
    LSR A
    PHA
    SEP #$20
    .a8
    AND #31                     ; its column
    ASL A
    ASL A
    ASL A
    SEC
    SBC #16
    STA a:OAMDATA               ; x: two cells before the box
    REP #$20
    .a16
    PLA
    LSR A
    LSR A
    AND #$FFF8                  ; its row, times eight
    SEP #$20
    .a8
    DEC A
    STA a:OAMDATA               ; y: the line's top, less one
    LDA #OBJ_HAND
    STA a:OAMDATA
    LDA #$32                    ; above everything, palette 1
    STA a:OAMDATA
    ;  The rings.
    LDA f:V_VIEW
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_OwsSiteN, X
    STA f:V_N
    REP #$20
    .a16
    TXA
    ASL A
    ASL A
    TAX                         ; its first place
    SEP #$20
    .a8
    LDA #0
    STA f:V_K
  @site:
    LDA f:V_K
    CMP f:V_N
    BCS @hide
    LDA f:V_T
    AND #$20
    BNE @hide
    LDA f:OWSFAR + lut_OwsSiteX, X
    LSR A
    CLC
    ADC #<(MAP_COL * 8 - 8)
    STA a:OAMDATA
    LDA f:OWSFAR + lut_OwsSiteY, X
    LSR A
    CLC
    ADC #<(MAP_ROW * 8 - 8 - 1)
    STA a:OAMDATA
    BRA @tile
  @hide:
    LDA #0
    STA a:OAMDATA
    LDA #224
    STA a:OAMDATA
  @tile:
    LDA #OBJ_RING
    STA a:OAMDATA
    LDA #$30                    ; above everything, palette 0
    STA a:OAMDATA
    INX
    LDA f:V_K
    INC A
    STA f:V_K
    CMP #OWS_SITES
    BCC @site
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The pad, answered at once: the text and the hand this frame, the
;;  pictures queued.  C set when START ends the screen.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_input:
    LDA f:V_PREV
    EOR #$FF
    AND joy
    PHA                         ; pressed this frame
    LDA joy
    STA f:V_PREV
    PLA
    BIT #PAD_START
    BEQ :+
    JSR ows_wincheck            ; the ticked edits, won?
    BCS @lost
    SEC                         ; START ends it
    RTS
  @lost:
    JSR ows_warn                ; no: why, and the screen stays
    CLC
    RTS
:   BIT #PAD_A
    BEQ @move
    PHA
    JSR ows_toggle
    JSR ows_sfxsel
    PLA
  @move:
    AND #PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT
    BEQ @out
    JSR ows_dir                 ; A = the new selection
    CMP f:V_SEL
    BEQ @out
    PHA
    LDA f:V_SEL
    JSR ows_queuerows           ; its flashing off...
    PLA
    STA f:V_SEL
    JSR ows_select              ; ...and the new one's on
    LDA f:V_SEL
    JSR ows_queuerows
    JSR ows_desc
    JSR ows_sfxmove
  @out:
    CLC
    RTS

;;  The ticked edits with the rest of the settings, checked as New Game
;;  will build the world (rando_winnable): RANDO_OWEDITS written for it --
;;  ows_choose writes it again leaving -- and the title's music kept going
;;  meanwhile, rando_yield ticking ows_tick while OWS_TICKON is set.  Out: C
;;  clear if winnable; else A = the reason.  A8 I16.
    .a8
    .i16
ows_wincheck:
    REP #$20
    .a16
    LDA f:V_FLAGS
    AND #OWEDIT_FLAGS
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    SEP #$30
    .a8
    .i8
    LDA #1
    STA f:OWS_TICKON
    SEC
    XCE
    JSL rando_winnable + WORLDFAR
    PHA                         ; the reason
    PHP                         ; C: not winnable
    LDA #0
    STA f:OWS_TICKON
    CLC
    XCE
    PLP
    PLA
    REP #$10                    ; (C kept)
    .i16
    RTS

;;  ows_tick -- a frame of the title's music, from rando_yield when a vblank
;;  has begun while rando_winnable works for this screen: as ows_wait's,
;;  CallMusicPlay then the HAL's frame of sound (hal_audioframe, as the roll
;;  screen's tick sends it).  cur_bank this chunk for the call, as it was
;;  after.  From native code, any widths, by JSL; everything kept.
ows_tick:
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
    LDA #CHUNK_OWS
    STA cur_bank
    JSR CallMusicPlay
    JSL hal_audioframe + HALFAR
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

;;  The settings screen's chirps (optmenu.asm's opt_sfx_move and _sel): the
;;  game's own, in bank $0E, through the trampoline, in emulation mode.  A8
;;  I16 in and out; X and Y not kept.
    .a8
    .i16
ows_sfxmove:
    SEP #$30
    .i8
    SEC
    XCE
    CALL0E PlaySFX_MenuMove
    BRA ows_sfxout
ows_sfxsel:
    SEP #$30
    SEC
    XCE
    CALL0E PlaySFX_MenuSel
ows_sfxout:
    CLC
    XCE
    REP #$10
    .i16
    RTS

;;  The selection a direction A takes it to.  A8 I16.
    .a8
    .i16
ows_dir:
.if OWS_SIDE
    BIT #PAD_UP | PAD_LEFT
    BEQ @down
    LDA f:V_SEL
    BNE :+
    LDA #OWS_SETTINGS
:   DEC A
    RTS
  @down:
    LDA f:V_SEL
    INC A
    CMP #OWS_SETTINGS
    BCC :+
    LDA #0
:   RTS
.else
    ;  The grid: seven rows, the first seven down the left.
    BIT #PAD_LEFT | PAD_RIGHT
    BEQ @updown
    LDA f:V_SEL
    CMP #7
    BCC :+
    SEC
    SBC #7
    RTS
:   CLC
    ADC #7
    RTS
  @updown:
    BIT #PAD_UP
    BEQ @dn
    LDA f:V_SEL
    CMP #7
    BCS @upright
    DEC A
    BPL :+
    LDA #6
:   RTS
  @upright:
    DEC A
    CMP #7
    BCS :+
    LDA #13
:   RTS
  @dn:
    LDA f:V_SEL
    CMP #7
    BCS @dnright
    INC A
    CMP #7
    BCC :+
    LDA #0
:   RTS
  @dnright:
    INC A
    CMP #14
    BCC :+
    LDA #7
:   RTS
.endif

;;  A ticks or unticks the selected box: the box at once, its rows queued,
;;  the zoom again.  A8 I16.
    .a8
    .i16
ows_toggle:
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsBit16, X
    EOR f:V_FLAGS
    STA f:V_FLAGS
    SEP #$20
    .a8
    JSR ows_actives
    LDA f:V_SEL
    STA f:V_K
    JSR ows_item
    LDA f:V_SEL
    JSR ows_queuerows
    ;  The land bridge decides which of Bahamut's docks there is.
    LDA f:V_SEL
    CMP #OWEDIT_CARDIABRIDGE_BIT
    BNE :+
    LDA #OWEDIT_BAHAMUTDOCK_BIT
    JSR ows_queuerows
:   JMP ows_insetstart

OWEDIT_CARDIABRIDGE_BIT = 12
OWEDIT_BAHAMUTDOCK_BIT  = 4
.assert OWEDIT_CARDIABRIDGE = 1 << OWEDIT_CARDIABRIDGE_BIT, error, "the land bridge's bit"
.assert OWEDIT_BAHAMUTDOCK = 1 << OWEDIT_BAHAMUTDOCK_BIT, error, "Bahamut's dock's bit"
.assert <OWEDIT_CARDIABRIDGE = 0, error, "ows_select reads the land bridge's byte"

;;  Setting A's minimap rows queued to draw.  A8 I16.
    .a8
    .i16
ows_queuerows:
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    TAX
    LDY #$0000
  @b:
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_OwsRows, X
    PHX
    TYX
    ORA f:V_QUEUE, X
    STA f:V_QUEUE, X
    PLX
    INX
    INY
    CPY #16
    BCC @b
    RTS

;;  The selection's view, its gates for the flashing, its first place for
;;  the zoom.  The view is the setting's own, but Bahamut's dock with the
;;  land bridge ticked is the two's variant alone, as ows_actives applies it
;;  -- what the game would make of it, not both docks it might mean (user).
;;  (The land bridge's own tiles take in the variant's two, so it needs no
;;  second view.)  Only the land bridge's box changes a view, and not while
;;  its own is selected, so a tick never does.  A8 I16.
    .a8
    .i16
ows_select:
    LDA f:V_SEL
    CMP #OWEDIT_BAHAMUTDOCK_BIT
    BNE @own
    LDA f:V_FLAGS + 1
    AND #>OWEDIT_CARDIABRIDGE
    BEQ @own
    LDA #OWS_VIEW_BAHAMUTBRIDGE
    BRA @view
  @own:
    LDA f:V_SEL
  @view:
    STA f:V_VIEW
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsGates, X
    STA f:V_HLMASK
    SEP #$20
    .a8
    LDA #0
    STA f:V_SITE
    JMP ows_insetstart


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The frame's drawing, BUDGET units of it: the zoom's map rows first,
;;  COST_ZOOM each, then the minimap's queued pixel rows, COST_ROW each.  And
;;  a view with more than one place shows each in turn.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_work:
    LDA #BUDGET
    STA f:V_BUDGET
.if OWS_INSET
    LDA f:V_T
    AND #$7F
    BNE @zoom
    LDA f:V_VIEW
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_OwsSiteN, X
    CMP #2
    BCC @zoom
    STA f:V_K
    LDA f:V_SITE
    INC A
    CMP f:V_K
    BCC :+
    LDA #0
:   STA f:V_SITE
    JSR ows_insetstart
  @zoom:
    LDA f:V_IACTIVE
    BEQ @rows
    LDA f:V_BUDGET
    CMP #COST_ZOOM
    BCS :+
    RTS
:   SBC #COST_ZOOM
    STA f:V_BUDGET
    JSR ows_insetrow
    BRA @zoom
.endif
  @rows:
    LDA f:V_BUDGET
    CMP #COST_ROW
    BCS :+
    RTS
:   SBC #COST_ROW
    STA f:V_BUDGET
    JSR ows_nextrow
    BCC @rows
    RTS

;;  The first queued pixel row of the minimap: drawn, unqueued, its
;;  character row marked to send.  C set when nothing is queued.  A8 I16.
    .a8
    .i16
ows_nextrow:
    LDX #$0000
  @byte:
    LDA f:V_QUEUE, X
    BNE @found
    INX
    CPX #16
    BCC @byte
    RTS                         ; C set: nothing queued
  @found:
    LDY #$0000
  @bit:
    LSR A
    BCS @have
    INY
    BRA @bit
  @have:
    ;  Pixel row X * 8 + Y: unqueued, drawn, its character row dirty.
    REP #$20
    .a16
    TYA
    ASL A
    PHX
    TAX
    LDA f:OWSFAR + lut_OwsBit16, X
    PLX
    SEP #$20
    .a8
    EOR #$FF
    AND f:V_QUEUE, X
    STA f:V_QUEUE, X
    TXA
    ASL A
    ASL A
    ASL A
    STA f:V_PROW
    TYA
    ORA f:V_PROW
    JSR ows_prow
    LDA f:V_PROW
    LSR A
    LSR A
    LSR A
    REP #$20
    .a16
    AND #$000F
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsBit16, X
    ORA f:V_DIRTY
    STA f:V_DIRTY
    SEP #$20
    .a8
    CLC
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_decode -- map row A, from the game's RLE rows, into the 256 bytes at
;;  bank $7F's X as minimap colours (lut_OwsTiles), edited by V_ACTIVE's
;;  lists, with bit 3 set on each tile a list of V_HLMASK's writes, applied
;;  or not.  A run's colour is looked up once.  A8 I16; out with B zero.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_decode:
    PHB
    PHA
    DB_RAM
    PLA
    STA a:aROWNUM
    STX a:aDST
    REP #$20
    .a16
    LDA a:aROWNUM
    AND #$00FF
    ASL A
    TAX
    LDA f:OWMAP + $8000, X      ; the row's pointer, an address in the bank
    TAX
    LDY a:aDST
    LDA #0                      ; B zero, for TAX below
    SEP #$20
    .a8
  @next:
    LDA f:OWMAP, X
    INX
    CMP #$80
    BCC @single
    CMP #$FF
    BEQ @edits
    AND #$7F
    PHX
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    STA a:aT8                   ; the run's colour
    PLX
    LDA f:OWMAP, X              ; its length, 0 for 256
    INX
    PHX
    REP #$20
    .a16
    AND #$00FF
    BNE :+
    LDA #256
:   DEC A
    BEQ @one
    ;  The first, then MVN copying each on to the next: it moves a byte in
    ;  seven cycles, a loop's store in about thirteen.
    DEC A                       ; MVN's count: the rest, less one
    PHA
    SEP #$20
    .a8
    LDA a:aT8
    STA a:0, Y
    REP #$20
    .a16
    PLA
    TYX
    INY
    MVN #^OWSRAM, #^OWSRAM      ; Y on past the run; DBR stays $7F
    LDA #0
    SEP #$20
    .a8
    PLX
    BRA @next
  @one:
    SEP #$20
    .a8
    LDA a:aT8
    STA a:0, Y
    INY
    PLX
    BRA @next
  @single:
    PHX
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    PLX
    STA a:0, Y
    INY
    BRA @next
  @edits:
    REP #$20
    .a16
    LDA a:aROWNUM
    AND #$00FF
    ASL A
    TAX
    LDA f:WORLDFAR + lut_OweRow + 2, X
    STA a:aEEND
    LDA f:WORLDFAR + lut_OweRow, X
    TAX
  @ent:
    CPX a:aEEND
    BCS @done
    LDA f:WORLDFAR + lut_OweEnt + 2, X  ; its x...
    AND #$00FF
    CLC
    ADC a:aDST
    TAY
    LDA f:WORLDFAR + lut_OweEnt, X      ; ...and its gate
    AND a:aACTIVE
    BEQ @mark
    ;  Applied: the tile's colour, the mark kept.
    LDA f:WORLDFAR + lut_OweEnt + 2, X
    XBA
    AND #$00FF
    PHX
    TAX
    SEP #$20
    .a8
    LDA a:0, Y
    AND #8
    ORA f:OWSFAR + lut_OwsTiles, X
    STA a:0, Y
    REP #$20
    .a16
    PLX
  @mark:
    LDA f:WORLDFAR + lut_OweEnt, X
    AND a:aHLMASK
    BEQ @nx
    SEP #$20
    .a8
    LDA a:0, Y
    ORA #8
    STA a:0, Y
    REP #$20
    .a16
  @nx:
    TXA
    CLC
    ADC #OWE_ENTRY
    TAX
    BRA @ent
  @done:
    LDA #0
    SEP #$20
    .a8
    PLB
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_prow -- the minimap's pixel row A into OWS_CHR: map rows 2A and
;;  2A + 1, a pixel its four tiles' colours ORed, through lut_OwsCol16.
;;  Only the characters an edit list writes in (lut_OwsCharMask): the rest
;;  are the baked minimap's, as ows_first left them, whatever is ticked.
;;  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_prow:
    STA f:V_PROW
    ASL A
    PHA
    LDX #.LOWORD(OWS_ROW)
    JSR ows_decode
    PLA
    INC A
    LDX #.LOWORD(OWS_ROW1)
    JSR ows_decode
    PHB
    DB_RAM
    ;  Its first character's row: (A >> 3) * 512 + (A & 7) * 2.
    REP #$20
    .a16
    LDA f:V_PROW
    AND #$00F8                  ; (A >> 3) * 8...
    XBA
    LSR A
    LSR A                       ; ...times 64
    STA a:aTILE
    LDA f:V_PROW
    AND #$0007
    ASL A
    ORA a:aTILE
    STA a:aTILE
    LDA f:V_PROW
    AND #$007F
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsCharMask, X
    STA a:aMASK
    LDA #0                      ; B zero, for TAX below
    SEP #$20
    .a8
    LDY #$0000                  ; two map tiles a pixel
  @char:
    REP #$20
    .a16
    LSR a:aMASK
    BCS @pack
    TYA                         ; the baked one stands: on a character
    CLC
    ADC #16
    TAY
    LDA a:aTILE
    CLC
    ADC #32
    STA a:aTILE
    LDA #0
    SEP #$20
    .a8
    BRA @next
  @pack:
    SEP #$20
    .a8
    LDA #8
    STA a:aCOL
  @px:
    LDA a:aROW, Y
    ORA a:aROW + 1, Y
    ORA a:aROW1, Y
    ORA a:aROW1 + 1, Y
    TAX
    LDA f:OWSFAR + lut_OwsCol16, X
    LSR A
    ROL a:aP0
    LSR A
    ROL a:aP0 + 1
    LSR A
    ROL a:aP0 + 2
    LSR A
    ROL a:aP0 + 3
    INY
    INY
    DEC a:aCOL
    BNE @px
    LDX a:aTILE
    LDA a:aP0
    STA a:aCHR, X
    LDA a:aP0 + 1
    STA a:aCHR + 1, X
    LDA a:aP0 + 2
    STA a:aCHR + 16, X
    LDA a:aP0 + 3
    STA a:aCHR + 17, X
    LDA a:aTILE                 ; the next character, 32 bytes on
    CLC
    ADC #32
    STA a:aTILE
    BCC @next
    INC a:aTILE + 1
  @next:
    CPY #256
    BCS :+
    JMP @char
:   PLB
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The zoom: the selected view's place V_SITE, around its middle, 28
;;  tiles across at two pixels a tile, or 56 at one where the place is wider
;;  than 28.  ows_insetstart begins it; ows_insetrow draws a map row of it,
;;  and when the last is drawn asks for it to be sent.  The zoom on screen
;;  is the last one finished.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_insetstart:
    ;  (Worked out without the zoom too, which only the drawing and the
    ;  sending of it need; so the harness can draw one in any layout.)
    LDA f:V_VIEW
    ASL A
    ASL A
    ORA f:V_SITE
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_OwsSiteW, X
    LDY #2
    CMP #INSET_PX / 2 + 1
    BCC :+
    LDY #1
:   TYA
    STA f:V_SCALE
    LDA #INSET_PX / 2
    CPY #1
    BNE :+
    LDA #INSET_PX
:   STA f:V_SPAN
    LSR A
    STA f:V_K                   ; half of it
    LDA f:OWSFAR + lut_OwsSiteX, X
    SEC
    SBC f:V_K
    STA f:V_X0
    LDA f:OWSFAR + lut_OwsSiteY, X
    SEC
    SBC f:V_K
    STA f:V_Y0
    LDA #0
    STA f:V_IROW
    STA f:V_R
    LDA #1
    STA f:V_IACTIVE
    RTS

    .a8
    .i16
ows_insetrow:
    LDA f:V_Y0
    CLC
    ADC f:V_IROW
    LDX #.LOWORD(OWS_ROW)
    JSR ows_decode              ; out with B zero
    PHB
    DB_RAM
    ;  The line: each tile's colour, V_SCALE times, into OWS_ROW1.
    LDA f:V_X0
    STA a:aXJ
    LDY #$0000
  @tile:
    LDA a:aXJ
    TAX
    LDA a:aROW, X
    AND #$0F
    TAX
    LDA f:OWSFAR + lut_OwsCol16, X
    STA a:aROW1, Y
    INY
    LDX a:aSCALE                ; 1 or 2, its high byte zero
    CPX #2
    BCC :+
    STA a:aROW1, Y
    INY
:   INC a:aXJ
    CPY #INSET_PX
    BCC @tile
    ;  ...packed into the zoom's characters at pixel row V_R, twice at two.
    JSR ows_packline
    LDA a:aSCALE
    CMP #2
    BNE :+
    INC a:aR
    JSR ows_dupline
:   INC a:aR
    PLB
    LDA f:V_IROW
    INC A
    STA f:V_IROW
    CMP f:V_SPAN
    BCC :+
    LDA #0
    STA f:V_IACTIVE
    LDA #1
    STA f:V_INSETD
:   RTS

;;  The zoom's pixel row just packed, again on the next (V_R): at two pixels
;;  a tile the pair is the same.  The packed row is even, so the next is in
;;  the same characters, a word on.  DBR $7F, A8 I16, B zero.
    .a8
    .i16
ows_dupline:
    REP #$20
    .a16
    LDA a:aTILE                 ; ows_packline's, past its last character
    SEC
    SBC #INSET_W * 32
    TAX
    LDY #INSET_W
  @char:
    LDA a:aINSETCHR, X          ; planes 0 and 1...
    STA a:aINSETCHR + 2, X
    LDA a:aINSETCHR + 16, X     ; ...and 2 and 3
    STA a:aINSETCHR + 18, X
    TXA
    CLC
    ADC #32
    TAX
    DEY
    BNE @char
    LDA #0
    SEP #$20
    .a8
    RTS

;;  OWS_ROW1's 56 colours into the zoom's pixel row V_R.  DBR $7F, A8 I16,
;;  B zero.
    .a8
    .i16
ows_packline:
    ;  (V_R >> 3) * 7 * 32 + (V_R & 7) * 2
    LDA a:aR
    LSR A
    LSR A
    LSR A
    REP #$20
    .a16
    AND #$00FF
    STA a:aTILE
    ASL A
    ASL A
    ASL A
    SEC
    SBC a:aTILE                 ; x 7
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 32
    STA a:aTILE
    LDA a:aR
    AND #$0007
    ASL A
    CLC
    ADC a:aTILE
    STA a:aTILE
    LDA #0
    SEP #$20
    .a8
    LDY #$0000
  @char:
    LDA #8
    STA a:aCOL
  @px:
    LDA a:aROW1, Y
    LSR A
    ROL a:aP0
    LSR A
    ROL a:aP0 + 1
    LSR A
    ROL a:aP0 + 2
    LSR A
    ROL a:aP0 + 3
    INY
    DEC a:aCOL
    BNE @px
    LDX a:aTILE
    LDA a:aP0
    STA a:aINSETCHR, X
    LDA a:aP0 + 1
    STA a:aINSETCHR + 1, X
    LDA a:aP0 + 2
    STA a:aINSETCHR + 16, X
    LDA a:aP0 + 3
    STA a:aINSETCHR + 17, X
    LDA a:aTILE
    CLC
    ADC #32
    STA a:aTILE
    BCC :+
    INC a:aTILE + 1
:   CPY #INSET_PX
    BCC @char
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The text, into BG3's tilemap in WRAM, sent next vblank: every line and
;;  the title at the start, then only what a press changes -- a line's box,
;;  or the description.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_drawall:
    LDA #0
    STA f:V_K
  @item:
    JSR ows_item
    LDA f:V_K
    INC A
    STA f:V_K
    CMP #OWS_SETTINGS
    BCC @item
    LDA #0
    STA f:V_PAL
    LDX #.LOWORD(lut_OwsTitle)
    LDY #(TITLE_ROW * 32 + TITLE_COL) * 2
.if OWS_SIDE
    LDA #9                      ; "MAP EDITS", a line
    JSR ows_text
.else
    LDA #3                      ; "MAP", then "EDITS" under it
    JSR ows_text
    INX                         ; past the space
    LDY #((TITLE_ROW + 1) * 32 + TITLE_COL) * 2
    LDA #5
    JSR ows_text
.endif
.if OWS_INSET
    JSR ows_frame
.endif
    JMP ows_desc

;;  The zoom's frame, round its 7x7 cells, in the game's dialog box tiles.
;;  A8 I16.
    .a8
    .i16
ows_frame:
    LDA #FRAME_PAL
    STA f:V_PAL
    LDY #((INSET_ROW - 1) * 32 + INSET_COL - 1) * 2
    LDA #FRAME_CHR + 0          ; the top: its corner, edge and corner
    JSR @line
    LDA #INSET_W
    STA f:V_K
  @side:
    REP #$20
    .a16
    TYA
    CLC
    ADC #64 - (INSET_W + 2) * 2
    TAY
    SEP #$20
    .a8
    TYX
    LDA #FRAME_CHR + 3          ; the left...
    JSR ows_putch
    REP #$20
    .a16
    TXA
    CLC
    ADC #INSET_W * 2
    TAX
    SEP #$20
    .a8
    LDA #FRAME_CHR + 4          ; ...and the right
    JSR ows_putch
    TXY
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @side
    REP #$20
    .a16
    TYA
    CLC
    ADC #64 - (INSET_W + 2) * 2
    TAY
    SEP #$20
    .a8
    LDA #FRAME_CHR + 5          ; the bottom
  @line:
    ;  A three-character line from Y: A, then A + 1 across, then A + 2.
    PHA
    TYX
    JSR ows_putch
    PLA
    INC A
    PHA
    LDA #INSET_W
    STA f:V_N
  @mid:
    LDA 1, S
    JSR ows_putch
    LDA f:V_N
    DEC A
    STA f:V_N
    BNE @mid
    PLA
    INC A
    JSR ows_putch
    TXY
    RTS

;;  The warning for rando_winnable's reason A, where the description goes,
;;  until a move puts that back.  A8 I16.
    .a8
    .i16
ows_warn:
    STA f:V_K
    LDA #0
    STA f:V_PAL
    REP #$20
    .a16
    LDA #.LOWORD(lut_OwsWarn)
    BRA ows_text_n

;;  The selected setting's description.  A8 I16.
    .a8
    .i16
ows_desc:
    LDA #0
    STA f:V_PAL
    LDA f:V_SEL
    STA f:V_K
    REP #$20
    .a16
    LDA #.LOWORD(lut_OwsDesc)
    ;  Text V_K of the table at A16, DESC_N lines of DESC_W.
ows_text_n:
    .a16
  @find:
    TAX
    SEP #$20
    .a8
    LDA f:V_K
    BEQ @have
    DEC A
    STA f:V_K
    REP #$20
    .a16
    TXA
    CLC
    ADC #DESC_W * DESC_N
    BRA @find
  @have:
    .a8                         ; (the loop above leaves the assembler at 16)
    LDY #(DESC_ROW * 32 + DESC_COL) * 2
    LDA #DESC_N
    STA f:V_K
  @line:
    PHY
    LDA #DESC_W
    JSR ows_text
    REP #$20
    .a16
    PLA
    CLC
    ADC #64
    TAY
    SEP #$20
    .a8
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @line
    LDA #1
    STA f:V_NTD
    RTS

;;  Setting V_K's line: its box and its name.  A8 I16.
    .a8
    .i16
ows_item:
    LDA #0
    STA f:V_PAL
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX                         ; its word
    LDA f:OWSFAR + lut_OwsBit16, X
    AND f:V_FLAGS
    PHP                         ; Z: not ticked
    LDA f:OWSFAR + lut_OwsCell, X
    TAX                         ; the box's cell
    PLP
    SEP #$20
    .a8
    BEQ :+
    LDA #2                      ; ticked
    BRA :++
:   LDA #1
:   JSR ows_putch               ; X on to the name's first cell
    TXY
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    STA f:V_VADDR
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 16...
    SEC
    SBC f:V_VADDR
    SEC
    SBC f:V_VADDR
    SEC
    SBC f:V_VADDR               ; ...less three, x 13
    CLC
    ADC #.LOWORD(lut_OwsName)
    TAX
    SEP #$20
    .a8
    LDA #NAME_W
    JSR ows_text
    LDA #1
    STA f:V_NTD
    RTS
.assert NAME_W = 13, error, "ows_item multiplies by thirteen"

;;  A characters from the chunk's X into the tilemap at byte Y, in V_PAL.
;;  Out: X past the string.  A8 I16.
    .a8
    .i16
ows_text:
    STA f:V_N
  @c:
    LDA f:OWSFAR, X
    PHX
    TYX
    JSR ows_putch
    TXY
    PLX
    INX
    LDA f:V_N
    DEC A
    STA f:V_N
    BNE @c
    RTS

;;  Character A at the tilemap's byte X, in V_PAL, above.  Out: X two on.
;;  A8 I16.
    .a8
    .i16
ows_putch:
    STA f:OWS_NT3, X
    LDA f:V_PAL
    ASL A
    ASL A
    ORA #$20                    ; priority
    STA f:OWS_NT3 + 1, X
    INX
    INX
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Tables
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_Zero:
  .BYTE 0

lut_OwsBit16:
  .WORD $0001, $0002, $0004, $0008, $0010, $0020, $0040, $0080
  .WORD $0100, $0200, $0400, $0800, $1000, $2000, $4000, $8000

;  Each setting's box, as a byte of BG3's tilemap: the hand two cells
;  before it, the name straight after.
.macro CELL r, c
  .WORD ((r) * 32 + (c)) * 2
.endmacro
lut_OwsCell:
.if OWS_SIDE
  .repeat OWS_SETTINGS, i
    CELL 2 + i, 17              ; the hand over the minimap's last two columns
  .endrep
.else
  .repeat OWS_SETTINGS, i
    CELL 17 + i .MOD 7, 3 + 14 * (i / 7)
  .endrep
.endif

;  OBJ characters: the ring's four, then the hand's.
lut_OwsObjCell:
  .BYTE OBJ_RING, OBJ_RING + 1, OBJ_RING + 16, OBJ_RING + 17
  .BYTE OBJ_HAND, OBJ_HAND + 1, OBJ_HAND + 16, OBJ_HAND + 17

;  CGRAM 0-11: the backdrop and BG3's three palettes -- the text, and a grey
;  one, each with the settings screen's checkbox colours, its grey ring and
;  white fill; and the frame, in the game's box colours.  32-47: the minimap's, BG1 palette 2: its four
;  colours as the game's minimap has them (bank $09's lut_MinimapBGPal), the
;  marker, and at 40-44 the flashing ones, which ows_vblank writes from
;  lut_OwsFlash's two sets.
lut_OwsPal:
  .WORD NESCOL_02, NESCOL_30, NESCOL_10, NESCOL_30
  .WORD NESCOL_02, NESCOL_00, NESCOL_10, NESCOL_30
  .WORD NESCOL_02, NESCOL_00, NESCOL_01, NESCOL_30   ; the frame, as the game's boxes
  .RES 40, 0
  .WORD NESCOL_02, NESCOL_1B, NESCOL_38, NESCOL_2B, NESCOL_16, 0, 0, 0
  .WORD NESCOL_02, NESCOL_1B, NESCOL_38, NESCOL_2B, NESCOL_16
lut_OwsPalEnd:
.assert lut_OwsPalEnd - lut_OwsPal = 2 * 45, error, "the palette runs to CGRAM 44"
lut_OwsFlash:
  .WORD NESCOL_21, NESCOL_30, NESCOL_30, NESCOL_30, NESCOL_27
.assert lut_OwsFlash - (lut_OwsPal + 80) = 10, error, "ows_vblank: the flash's two sets ten bytes apart"
;  OBJ palettes 0, the rings, and 1, the hand: the game's cursor colours
;  (sprite palette 3 of LoadBattleSpritePalettes).
lut_OwsObjPal:
  .WORD NESCOL_0F, NESCOL_30, NESCOL_16, NESCOL_0F
  .RES 24, 0
  .WORD NESCOL_0F, NESCOL_30, NESCOL_10, NESCOL_00
lut_OwsObjPalEnd:

lut_OwsName:
  FFPAD "Early Open", NAME_W
  FFPAD "Extended Open", NAME_W
  FFPAD "North Docks", NAME_W
  FFPAD "Ryukahn Dock", NAME_W
  FFPAD "Bahamut Dock", NAME_W
  FFPAD "Lefein River", NAME_W
  FFPAD "Lefein Bridge", NAME_W
  FFPAD "Gaia Pass", NAME_W
  FFPAD "Ordeals Road", NAME_W
  FFPAD "Melmond River", NAME_W
  FFPAD "Sarda Forest", NAME_W
  FFPAD "Airship Trail", NAME_W
  FFPAD "Cardia Bridge", NAME_W
  FFPAD "Ship Drydock", NAME_W

.if OWS_SIDE
lut_OwsDesc = lut_OwsDescNarrow
lut_OwsWarn = lut_OwsWarnNarrow
.else
lut_OwsDesc = lut_OwsDescWide
lut_OwsWarn = lut_OwsWarnWide
.endif

lut_OwsTitle:
  FFPAD "MAP EDITS", 9
