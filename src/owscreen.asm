; ---------------------------------------------------------------------------
;  owscreen.asm -- New Game's map edit screen (CHUNK_OWS).
;
;  Each of FFR's fourteen overworld edits a checkbox, and the world's minimap
;  above or beside them as the boxes ticked would make it (user, 2026-10-18).
;  A prototype, built in the four layouts the user is comparing
;  (owslayout.inc): the minimap above a grid or beside a column, with or
;  without a zoom of the selected edit.
;
;  From rando_newgame when the Map edits row is not Off, which then writes
;  the row's flags into RANDO_OWEDITS.  The screen starts from the saved
;  game's, when Continue would load it and it has any -- so the choice
;  carries from game to game without a byte of the option block -- else the
;  row's.  START ends it, and RANDO_OWEDITS is what is ticked, but for the
;  three the logic cannot take yet (Sarda's Forest, the Cardia Land Bridge,
;  Ship in Drydock): those are on the screen to judge it whole, and preview,
;  but New Game drops them.
;
;  The minimap is the world's, decoded here from the game's own RLE rows and
;  edited from world.asm's tables as ow_edit edits the game's, so it shows
;  what the game will: two map rows a pixel row, each pixel the game's
;  minimap colour for the four tiles (lut_OwsTiles, bank $09's).  A pixel row
;  the selected edit writes is drawn with its pixels in the flashing colours,
;  and rings mark each of its places.  It draws two pixel rows a frame, top
;  to bottom, and a tick redraws only the rows its edit writes.
;
;  Like the credits and the roll screen it takes the PPU from the HAL and
;  gives it back through hal_ppureclaim: mode 1, the minimap and the inset on
;  BG1, the text on BG3 in the game's font, the rings as sprites.
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

.export ows_choose
;  For tools/test_options.py.
.export ows_testprow, ows_testinset, lut_OwsTiles

.import UpdateJoy
.import hal_vblaudio, hal_ppureclaim
.import opt_savevalidfar
.import lut_OweRow, lut_OweEnt
.importzp OWE_ENTRY

.segment "BANK_OWS"

.include "owscreen.inc"

MENUCHR   = (CHUNK0 + BANK_MENUCHR) * $10000 + $8800    ; the font, tiles $80-$FF
OWMAP     = (CHUNK0 + BANK_OWMAP) * $10000             ; its $8000: the rows' pointers
SAVEDOWE  = (CHUNK0 * $10000) + sram + (RANDO_OWEDITS - unsram)   ; the saved game's

;  VRAM, in words.
VR_BG1CHR = $0000               ; the minimap's 256 characters, then the inset's 49
VR_BG3CHR = $2000               ; the font at its own numbers, the boxes at 1 and 2
VR_BG1MAP = $3000
VR_BG3MAP = $3400
VR_OBJCHR = $4000
BG1_BLANK = 511                 ; a character nothing writes
INSET_CHR = 256

;  Where things are, in BG cells, inside the 30x26 that a CRT shows.
.if OWS_SIDE
MAP_COL   = 1
MAP_ROW   = 1
INSET_COL = 1
INSET_ROW = 18
  .if OWS_INSET
HINT_COL  = 10
  .else
HINT_COL  = 1
  .endif
HINT_ROW  = 19
.else
MAP_COL   = 8
MAP_ROW   = 1
INSET_COL = 1
INSET_ROW = 5
HINT_COL  = 24
HINT_ROW  = 6
.endif
DESC_ROW  = 25
DESC_COL  = 1
INSET_W   = 7                   ; cells
INSET_PX  = INSET_W * 8

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
V_HLMASK  = OWV+$04             ; 2: the selected setting's gates
V_SEL     = OWV+$06             ; the selected setting, 0-13
V_PREV    = OWV+$07             ; the pad last frame
V_T       = OWV+$09             ; frames
V_SITE    = OWV+$0A             ; which of its places the inset shows
V_INSET   = OWV+$0B             ; nonzero: draw the inset
V_INSETD  = OWV+$0C             ; nonzero: send it
V_NTD     = OWV+$0D             ; nonzero: send BG3's tilemap
V_QUEUE   = OWV+$10             ; 16: pixel rows to draw, a bit each
V_DIRTY   = OWV+$20             ; 2: character rows to send, a bit each
V_V       = OWV+$22
V_P0      = OWV+$23             ; ...$26: a character row's four planes
V_COL     = OWV+$27
V_TILE    = OWV+$28             ; 2
V_X0      = OWV+$2A
V_Y0      = OWV+$2B
V_SCALE   = OWV+$2C
V_SPAN    = OWV+$2D
V_I       = OWV+$2E
V_XJ      = OWV+$2F
V_ROWNUM  = OWV+$30
V_N       = OWV+$31
V_T8      = OWV+$32
V_DST     = OWV+$34             ; 2
V_END     = OWV+$36             ; 2
V_EEND    = OWV+$38             ; 2
V_GATE    = OWV+$3A             ; 2
V_PROW    = OWV+$3C
V_PAL     = OWV+$3D
V_R       = OWV+$3F
V_VADDR   = OWV+$40             ; 2
V_K       = OWV+$42
.assert V_K < OWS_VARS + $100, error, "the screen's variables outgrow their page"

;  The same, with DBR = $7F.
aACTIVE   = .LOWORD(V_ACTIVE)
aHLMASK   = .LOWORD(V_HLMASK)
aV        = .LOWORD(V_V)
aP0       = .LOWORD(V_P0)
aCOL      = .LOWORD(V_COL)
aTILE     = .LOWORD(V_TILE)
aROWNUM   = .LOWORD(V_ROWNUM)
aN        = .LOWORD(V_N)
aT8       = .LOWORD(V_T8)
aDST      = .LOWORD(V_DST)
aEND      = .LOWORD(V_END)
aEEND     = .LOWORD(V_EEND)
aGATE     = .LOWORD(V_GATE)
aXJ       = .LOWORD(V_XJ)
aSPAN     = .LOWORD(V_SPAN)
aSCALE    = .LOWORD(V_SCALE)
aI        = .LOWORD(V_I)
aR        = .LOWORD(V_R)
aK        = .LOWORD(V_K)
aROW      = .LOWORD(OWS_ROW)
aROW1     = .LOWORD(OWS_ROW1)
aHL       = .LOWORD(OWS_HL)
aHL1      = .LOWORD(OWS_HL1)
aCHR      = .LOWORD(OWS_CHR)
aINSETCHR = .LOWORD(OWS_INSETCHR)
.assert OWS_HL - OWS_ROW = $200 && OWS_HL1 - OWS_ROW1 = $200, error, "ows_decode: a row's flags $200 after it"

.macro DB_RAM
    LDA #^OWSRAM
    PHA
    PLB
.endmacro


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_choose -- the screen.  In: RANDO_OWEDITS the row's flags.  Out:
;;  RANDO_OWEDITS as ticked, less the three the logic cannot take.  From
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
    AND #OWEDIT_SAFE
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


;;  For the harness: ows_prow, pixel row A, and ows_inset, from emulation
;;  mode by JSL, V_FLAGS, V_SEL and V_SITE as it set them.
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
    JSR ows_select
    JSR ows_inset
ows_testout:
    SEP #$30
    .i8
    SEC
    XCE
    PLB
    RTL

;;  The lists V_FLAGS applies, as owedits.py's active_lists.  A8 I16 in and
;;  out.
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
;;  Setup: in forced blank, VRAM, CGRAM, OAM and the registers; the text
;;  drawn, the minimap queued, the display on.  Native, A8 I16, DBR this
;;  chunk.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_setup:
    JSR ows_wait                ; the top of a vblank, so nothing tears
    LDA #$80
    STA a:INIDISP
    STZ a:HDMAEN
    ;  VRAM all zero: every character blank, every map entry character 0.
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
    ;  The font: NES CHR, a plane then the other, its glyphs colour 3 on 2.
    ;  As SNES 2bpp, a row's two planes a word: the glyph colour 1, the rest
    ;  0 and so clear, whatever is behind it.
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
    JSR ows_ringchr             ; the ring, OBJ characters 0, 1, 16 and 17
    REP #$20
    .a16
    ;  BG1's map: blank everywhere but the minimap's 16x16 and the inset's.
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
    LDY #$0000                  ; the inset's cell, 0-48
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
    CPX #8
    BCC @objpal
    ;  OAM: every sprite below the picture; the first four large.
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
    LDX #$0001
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
    ;  The state: the first setting selected, the whole minimap to draw.
    LDA #0
    STA f:V_SEL
    STA f:V_SITE
    STA f:V_T
    STA f:V_INSETD
    REP #$20
    .a16
    LDA #0
    STA f:V_DIRTY
    LDA #$FFFF
    LDX #14
  @q:
    STA f:V_QUEUE, X
    DEX
    DEX
    BPL @q
    SEP #$20
    .a8
    JSR ows_actives
    JSR ows_select              ; V_HLMASK, the inset asked for
    LDA #$FF
    STA f:V_PREV                ; nothing counts as pressed until let go
    ;  BG3's tilemap: blank, then every line.
    REP #$20
    .a16
    LDA #0
    LDX #0
  @nt:
    STA f:OWS_NT3, X
    INX
    INX
    CPX #28 * 64
    BCC @nt
    SEP #$20
    .a8
    JSR ows_drawall
    JSR ows_vblank              ; the tilemap out, in forced blank
    LDA #$0F
    STA a:INIDISP
    RTS

;;  The ring's four characters.  A8 I16.
    .a8
    .i16
ows_ringchr:
    LDY #$0000
  @tile:
    REP #$20
    .a16
    TYA
    AND #$0002                  ; the second pair is 16 characters on
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 128 words... (16 characters x 8)
    STA f:V_VADDR
    TYA
    AND #$0001
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 16 words, a character
    CLC
    ADC f:V_VADDR
    ADC #VR_OBJCHR
    STA a:VMADDL
    TYA
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; its 32 bytes
    TAX
    SEP #$20
    .a8
    LDA #16
    STA f:V_K
  @word:
    REP #$20
    .a16
    LDA f:OWSFAR + lut_OwsRingChr, X
    STA a:VMDATAL
    INX
    INX
    SEP #$20
    .a8
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @word
    INY
    CPY #4
    BCC @tile
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The loop: a frame, its vblank's transfers, the pad, and then as much
;;  drawing as a frame holds.  Out when START is pressed.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_loop:
  @frame:
    JSR ows_wait
    JSR ows_vblank
    LDA f:V_T
    INC A
    STA f:V_T
    JSR ows_input
    BCS @done
    JSR ows_work
    BRA @frame
  @done:
    RTS

;;  The game's pad reader, then the top of the next vblank: both game code in
;;  emulation mode.  A8 I16 in and out.
    .a8
    .i16
ows_wait:
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

;;  The vblank's work: the flash, the tilemap, the inset, character rows of
;;  the minimap as many as fit, the rings.  A8 I16, DBR this chunk.
    .a8
    .i16
ows_vblank:
    ;  The selected edit's pixels flash, sixteen frames each way.
    LDA #40
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
    BRA @rings                  ; that is the vblank's worth
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
  @rings:
    JSR ows_rings
    RTS

;;  Character row X of the minimap to VRAM, and its dirty bit cleared.  A8
;;  I16.
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

;;  X bytes at bank $7F's Y... rather: Y bytes from bank $7F's X, to VRAM
;;  V_VADDR.  A8 I16.
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

;;  The selected edit's places ringed, blinking.  A8 I16.
    .a8
    .i16
ows_rings:
    STZ a:OAMADDL
    STZ a:OAMADDH
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    TAX                         ; the setting
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_OwsSiteN, X
    STA f:V_N                   ; its places
    REP #$20
    .a16
    TXA
    ASL A
    ASL A
    TAX                         ; its first
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
    LDA #0
    STA a:OAMDATA               ; character 0
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
;;  The pad.  C set when START ends the screen.  A8 I16.
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
    SEC
    RTS
:   BIT #PAD_A
    BEQ @move
    PHA
    JSR ows_toggle
    PLA
  @move:
    AND #PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT
    BEQ @out
    JSR ows_dir                 ; A = the new selection
    CMP f:V_SEL
    BEQ @out
    PHA
    LDA f:V_SEL
    JSR ows_queuerows           ; its highlight off...
    PLA
    STA f:V_SEL
    LDA #0
    STA f:V_SITE
    JSR ows_select              ; ...and the new one's on
    LDA f:V_SEL
    JSR ows_queuerows
    JSR ows_drawall
  @out:
    CLC
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

;;  A ticks or unticks the selected box; its rows drawn again.  A8 I16.
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
    JSR ows_queuerows
    ;  The land bridge decides which of Bahamut's docks there is.
    LDA f:V_SEL
    CMP #OWEDIT_CARDIABRIDGE_BIT
    BNE :+
    LDA #OWEDIT_BAHAMUTDOCK_BIT
    JSR ows_queuerows
:   LDA #1
    STA f:V_INSET
    JMP ows_drawall

OWEDIT_CARDIABRIDGE_BIT = 12
OWEDIT_BAHAMUTDOCK_BIT  = 4
.assert OWEDIT_CARDIABRIDGE = 1 << OWEDIT_CARDIABRIDGE_BIT, error, "the land bridge's bit"
.assert OWEDIT_BAHAMUTDOCK = 1 << OWEDIT_BAHAMUTDOCK_BIT, error, "Bahamut's dock's bit"

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

;;  The selection's gates for the highlight, and its inset asked for.  A8
;;  I16.
    .a8
    .i16
ows_select:
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:OWSFAR + lut_OwsGates, X
    STA f:V_HLMASK
    SEP #$20
    .a8
    LDA #1
    STA f:V_INSET
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The frame's drawing: the inset when asked, else two queued pixel rows;
;;  and the inset's places taken in turn.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_work:
.if OWS_INSET
    ;  A setting with more than one place shows each in turn.
    LDA f:V_T
    AND #$7F
    BNE @asked
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_OwsSiteN, X
    CMP #2
    BCC @asked
    STA f:V_K
    LDA f:V_SITE
    INC A
    CMP f:V_K
    BCC :+
    LDA #0
:   STA f:V_SITE
    LDA #1
    STA f:V_INSET
  @asked:
    LDA f:V_INSET
    BEQ @rows
    LDA #0
    STA f:V_INSET
    JSR ows_inset
    LDA #1
    STA f:V_INSETD
    RTS
.endif
  @rows:
    LDA #2
    STA f:V_K
  @next:
    LDX #$0000
  @byte:
    LDA f:V_QUEUE, X
    BNE @found
    INX
    CPX #16
    BCC @byte
    RTS                         ; nothing queued
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
    LDA f:V_PROW                ; its character row: the pixel row's top four bits
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
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @next
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_decode -- map row A, from the game's RLE rows, into the 256 bytes at
;;  bank $7F's X, edited by V_ACTIVE's lists; and at X + $200 a nonzero byte
;;  for each tile a list of V_HLMASK's writes, applied or not.  A8 I16.
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
    TXA
    CLC
    ADC #256
    STA a:aEND
    LDA a:aROWNUM
    AND #$00FF
    ASL A
    TAX
    LDA f:OWMAP + $8000, X      ; the row's pointer, an address in the bank
    TAX
    LDY a:aDST
    SEP #$20
    .a8
  @next:
    CPY a:aEND
    BCS @flags
    LDA f:OWMAP, X
    INX
    CMP #$80
    BCC @single
    CMP #$FF
    BEQ @flags
    AND #$7F
    STA a:aT8
    LDA f:OWMAP, X              ; the run's length, 0 for 256
    INX
    STA a:aN
  @run:
    LDA a:aT8
    STA a:0, Y
    INY
    CPY a:aEND
    BCS @flags
    DEC a:aN
    BNE @run
    BRA @next
  @single:
    STA a:0, Y
    INY
    BRA @next
  @flags:
    LDY a:aDST
    LDA #0
  @clr:
    STA a:$200, Y
    INY
    CPY a:aEND
    BCC @clr
    ;  The row's edits.
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
    LDA f:WORLDFAR + lut_OweEnt, X
    STA a:aGATE
    LDA f:WORLDFAR + lut_OweEnt + 2, X  ; its x
    AND #$00FF
    CLC
    ADC a:aDST
    TAY
    LDA a:aGATE
    AND a:aACTIVE
    BEQ @hl
    SEP #$20
    .a8
    LDA f:WORLDFAR + lut_OweEnt + 3, X  ; its tile
    STA a:0, Y
    REP #$20
    .a16
  @hl:
    LDA a:aGATE
    AND a:aHLMASK
    BEQ @nx
    SEP #$20
    .a8
    LDA #1
    STA a:$200, Y
    REP #$20
    .a16
  @nx:
    TXA
    CLC
    ADC #OWE_ENTRY
    TAX
    BRA @ent
  @done:
    SEP #$20
    .a8
    PLB
    RTS


;;  A tile's colour into A: lut_OwsTiles' two bits, a marker 4 for the
;;  marker bit; nothing touches B, which is zero.  In: A the four tiles' ORed
;;  table bytes.  A8.
.macro COLOUR
    BIT #4
    BEQ :+
    LDA #4
    BRA :++
:   AND #3
:
.endmacro


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_prow -- the minimap's pixel row A into OWS_CHR: map rows 2A and
;;  2A + 1, a pixel the four tiles' colour, plus 8 where the selected edit
;;  writes one of them.  A8 I16.
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
    LDA #0                      ; B zero, for TAX below
    SEP #$20
    .a8
    LDY #$0000                  ; two map tiles a pixel
  @char:
    LDA #8
    STA a:aCOL
  @px:
    LDA a:aROW, Y
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    STA a:aV
    LDA a:aROW + 1, Y
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    ORA a:aV
    STA a:aV
    LDA a:aROW1, Y
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    ORA a:aV
    STA a:aV
    LDA a:aROW1 + 1, Y
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    ORA a:aV
    COLOUR
    STA a:aV
    LDA a:aHL, Y
    ORA a:aHL + 1, Y
    ORA a:aHL1, Y
    ORA a:aHL1 + 1, Y
    BEQ :+
    LDA a:aV
    ORA #8
    STA a:aV
:   LDA a:aV
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
    BCC :+
    INC a:aTILE + 1
:   CPY #256
    BCS :+
    JMP @char
:   PLB
    RTS


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ows_inset -- the selected edit's place V_SITE, around its middle: 28
;;  tiles across at two pixels a tile, or 56 at one where the place is wider
;;  than 28.  A8 I16.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i16
ows_inset:
    LDA f:V_SEL
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
    STA f:V_I                   ; the map row of the span
    STA f:V_R                   ; the inset's pixel row
  @row:
    LDA f:V_Y0
    CLC
    ADC f:V_I
    LDX #.LOWORD(OWS_ROW)
    JSR ows_decode
    PHB
    DB_RAM
    ;  The line: each tile's colour, V_SCALE times, into OWS_ROW1.
    REP #$20
    .a16
    LDA #0
    SEP #$20
    .a8
    LDA f:V_X0
    STA a:aXJ
    LDY #$0000
  @tile:
    LDA a:aXJ
    TAX
    LDA a:aROW, X
    PHX
    TAX
    LDA f:OWSFAR + lut_OwsTiles, X
    PLX
    COLOUR
    STA a:aV
    LDA a:aHL, X
    BEQ :+
    LDA a:aV
    ORA #8
    STA a:aV
:   LDA a:aV
    STA a:aROW1, Y
    INY
    LDA a:aSCALE
    CMP #2
    BNE :+
    LDA a:aV
    STA a:aROW1, Y
    INY
:   INC a:aXJ
    CPY #INSET_PX
    BCC @tile
    ;  ...packed into the inset's characters at pixel row V_R, twice at two.
    JSR ows_packline
    LDA a:aSCALE
    CMP #2
    BNE :+
    INC a:aR
    JSR ows_packline
:   INC a:aR
    PLB
    LDA f:V_I
    INC A
    STA f:V_I
    CMP f:V_SPAN
    BCS :+
    JMP @row
:   RTS

;;  OWS_ROW1's 56 colours into the inset's pixel row V_R.  DBR $7F, A8 I16,
;;  B zero.
    .a8
    .i16
ows_packline:
    ;  (V_R >> 3) * 7 * 32 + (V_R & 7) * 2
    LDA a:aR
    LSR A
    LSR A
    LSR A
    STA a:aK
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
;;  The text, into BG3's tilemap in WRAM: the fourteen, the selected one's
;;  description, the hints.  Sent next vblank.  A8 I16.
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
    ;  The description: two lines of the selected one's.
    LDA f:V_SEL
    REP #$20
    .a16
    AND #$00FF
    STA f:V_VADDR
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 60: x 64 less x 4
    ASL A
    ASL A
    STA f:V_DST
    LDA f:V_VADDR
    ASL A
    ASL A
    EOR #$FFFF
    SEC
    ADC f:V_DST
    CLC
    ADC #.LOWORD(lut_OwsDesc)
    TAX                         ; the string
    LDY #(DESC_ROW * 32 + DESC_COL) * 2
    SEP #$20
    .a8
    LDA #0
    STA f:V_PAL
    LDA #30
    JSR ows_text
    REP #$20
    .a16
    TXA
    LDY #((DESC_ROW + 1) * 32 + DESC_COL) * 2
    SEP #$20
    .a8
    LDA #30
    JSR ows_text
    ;  The hints.
    LDX #.LOWORD(lut_OwsHint)
    LDY #(HINT_ROW * 32 + HINT_COL) * 2
    LDA #7
    JSR ows_text
    LDY #((HINT_ROW + 1) * 32 + HINT_COL) * 2
    LDA #7
    JSR ows_text
    LDY #((HINT_ROW + 3) * 32 + HINT_COL) * 2
    LDA #7
    JSR ows_text
    LDY #((HINT_ROW + 4) * 32 + HINT_COL) * 2
    LDA #7
    JSR ows_text
    LDY #((HINT_ROW + 5) * 32 + HINT_COL) * 2
    LDA #7
    JSR ows_text
    LDA #1
    STA f:V_NTD
    RTS

;;  Setting V_K's line: its box and its name, in its colours.  A8 I16.
    .a8
    .i16
ows_item:
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX                         ; its word
    LDA #OWEDIT_SAFE
    AND f:OWSFAR + lut_OwsBit16, X
    SEP #$20
    .a8
    BNE :+
    LDA #2                      ; a held-back one, grey
    BRA :++
:   LDA #0
:   STA f:V_PAL
    LDA f:V_K
    CMP f:V_SEL
    BNE :+
    LDA f:V_PAL
    ORA #1                      ; selected
    STA f:V_PAL
:   REP #$20
    .a16
    LDA f:OWSFAR + lut_OwsBit16, X
    AND f:V_FLAGS
    PHP                         ; Z: not ticked
    LDA f:OWSFAR + lut_OwsCell, X
    TAX                         ; the cell
    PLP
    SEP #$20
    .a8
    BEQ :+
    LDA #2                      ; ticked
    BRA :++
:   LDA #1
:   PHX
    JSR ows_putch
    PLY
    INY
    INY                         ; the name, the cell after
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    STA f:V_VADDR
    ASL A
    ASL A
    ASL A
    ASL A
    SEC
    SBC f:V_VADDR
    SBC f:V_VADDR
    SBC f:V_VADDR
    CLC
    ADC #.LOWORD(lut_OwsName)   ; x 13
    TAX
    SEP #$20
    .a8
    LDA #13
    JMP ows_text

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

;;  Box A at the tilemap's byte X.  A8 I16.
    .a8
    .i16
ows_putcell:
    JMP ows_putch


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Tables
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_Zero:
  .BYTE 0

lut_OwsBit16:
  .WORD $0001, $0002, $0004, $0008, $0010, $0020, $0040, $0080
  .WORD $0100, $0200, $0400, $0800, $1000, $2000, $4000, $8000

;  Each setting's box, as a byte of BG3's tilemap.
.macro CELL r, c
  .WORD ((r) * 32 + (c)) * 2
.endmacro
lut_OwsCell:
.if OWS_SIDE
  .repeat OWS_SETTINGS, i
    CELL 1 + i, 17
  .endrep
.else
  .repeat OWS_SETTINGS, i
    CELL 18 + i .MOD 7, 1 + 15 * (i / 7)
  .endrep
.endif

;  CGRAM 0-15: the backdrop and BG3's four palettes -- the text, the
;  selected, the held-back, the held-back selected.  32-47: the minimap's, BG1
;  palette 2: its four colours as the game's minimap has them (bank $09's
;  lut_MinimapBGPal), the marker, and at 40-44 the flashing ones, which
;  ows_vblank writes from lut_OwsFlash's two sets.
lut_OwsPal:
  .WORD NESCOL_02, NESCOL_30, NESCOL_0F, NESCOL_0F
  .WORD NESCOL_02, NESCOL_28, NESCOL_0F, NESCOL_0F
  .WORD NESCOL_02, NESCOL_00, NESCOL_0F, NESCOL_0F
  .WORD NESCOL_02, NESCOL_37, NESCOL_0F, NESCOL_0F
  .RES 32, 0
  .WORD NESCOL_02, NESCOL_1B, NESCOL_38, NESCOL_2B, NESCOL_16, 0, 0, 0
  .WORD NESCOL_02, NESCOL_1B, NESCOL_38, NESCOL_2B, NESCOL_16
lut_OwsPalEnd:
.assert lut_OwsPalEnd - lut_OwsPal = 2 * 45, error, "the palette runs to CGRAM 44"
lut_OwsFlash:
  .WORD NESCOL_21, NESCOL_30, NESCOL_30, NESCOL_30, NESCOL_27
.assert lut_OwsFlash - (lut_OwsPal + 80) = 10, error, "ows_vblank: the flash's two sets ten bytes apart"
lut_OwsObjPal:
  .WORD NESCOL_0F, NESCOL_30, NESCOL_16, NESCOL_0F

lut_OwsName:
  FFPAD "Early Open", 13
  FFPAD "Extended Open", 13
  FFPAD "North Docks", 13
  FFPAD "Desert Dock", 13
  FFPAD "Bahamut Dock", 13
  FFPAD "Lefein River", 13
  FFPAD "Lefein Bridge", 13
  FFPAD "Gaia Pass", 13
  FFPAD "Ordeals Road", 13
  FFPAD "Melmond River", 13
  FFPAD "Sarda Forest", 13
  FFPAD "Airship Trail", 13
  FFPAD "Cardia Bridge", 13
  FFPAD "Ship Drydock", 13

lut_OwsDesc:
  FFPAD "Walk Coneria to the Dwarves,", 30
  FFPAD "canoe Pravoka to Crescent.", 30
  FFPAD "Walk the Dwarf Cave's lands", 30
  FFPAD "to Northwest Castle.", 30
  FFPAD "Docks by Onrac and by the", 30
  FFPAD "Mirage Tower.", 30
  FFPAD "A dock by the Ryukahn Desert,", 30
  FFPAD "where the AIRSHIP rises.", 30
  FFPAD "A dock on Bahamut's island,", 30
  FFPAD "no AIRSHIP to his cave.", 30
  FFPAD "A river dock reaching Lefein", 30
  FFPAD "without the AIRSHIP.", 30
  FFPAD "The BRIDGE joins Pravoka and", 30
  FFPAD "Lefein, Coneria's is land.", 30
  FFPAD "A pass through the mountains", 30
  FFPAD "to Gaia from Lefein's side.", 30
  FFPAD "Roads from Lefein to Mirage's", 30
  FFPAD "desert, and on to Ordeals.", 30
  FFPAD "A river from the Dwarf Cave", 30
  FFPAD "to Melmond, no CANAL.", 30
  FFPAD "A forest walls Sarda off.", 30
  FFPAD "Preview only -- not in play.", 30
  FFPAD "Walk to the AIRSHIP's desert", 30
  FFPAD "without the CANOE.", 30
  FFPAD "Land from Ordeals through", 30
  FFPAD "Cardia.  Preview only.", 30
  FFPAD "The SHIP waits in Gaia's", 30
  FFPAD "drydock.  Preview only.", 30
.assert * - lut_OwsDesc = 60 * OWS_SETTINGS, error, "two lines a setting"

lut_OwsHint:
  FFPAD "MAP", 7
  FFPAD "EDITS", 7
  FFPAD "A  Tick", 7
  FFPAD "START", 7
  FFPAD " Done", 7
