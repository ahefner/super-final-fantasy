; ---------------------------------------------------------------------------
;  credits.asm -- the credits screen.
;
;  Reached from the title screen's Credits row, through opt_titlechoose.
;
;  Unlike everything else the port runs, this is not the game.  It is SNES
;  code written for the SNES: it takes the PPU away from the translation layer
;  for as long as it is up, runs mode 7, and gives it back through
;  hal_ppureclaim on the way out, which rebuilds the picture from the shadows.
;  So nothing here has to put VRAM back the way it found it -- the screen is
;  free to use all of it -- and the title screen, which is rebuilt from the top
;  afterwards anyway, never knows it was gone.
;
;  What it still borrows from the game is the music driver and the joypad
;  reader, both of which are game code in emulation mode.  cr_frame is that
;  borrowing, once a frame; everything else is the screen's own.
;
;  The text lies on a plane tilted back from the screen, drawn by two HDMA
;  channels: one sets each line's horizontal scale (M7A) and the other which
;  row of the text the line shows (M7Y).  A third fades the text's colour
;  into the background over the top of the screen, as it recedes.  tools/gencrawl.py works out the
;  geometry at build time, and its parameters are where the angle and the
;  zoom are tuned.  The scale table goes into ROM as it is.  The rows move
;  with the scroll, so once a frame cr_fill subtracts each line's distance up
;  the plane from the scroll into a WRAM buffer -- two of them, so the one
;  being written is never the one on screen.
;
;  The text itself is still a placeholder.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "fftext.inc"
.include "Constants.inc"
.include "variables.inc"
;  CALL0E, for the menu chirp in bank $0E.
.include "optcall.inc"
;  NESCOL_xx, the NES's colours in SNES form.
.include "nescol.inc"

.export credits_screen

.import CallMusicPlay, UpdateJoy
.import OptCallFar, PlaySFX_MenuSel
.import hal_vblaudio, hal_ppureclaim

.segment "BANK_CREDITS"

;  The perspective, from tools/gencrawl.py: constants, the scale table and the
;  distance table, so it has to be inside the segment.
.include "crawl.inc"

CR_BANK      = CHUNK0 + CHUNK_CREDITS

;  The game's font, read where LoadMenuCHR reads it: eight rows of NES CHR at
;  $8800 of the menu CHR bank, which is tiles $80-$FF -- the whole font, in the
;  game's own text encoding.  The tiles keep their numbers here, so text
;  written with fftext.inc is also its own tilemap.
MENUCHR      = (CHUNK0 + BANK_MENUCHR) * $10000 + $8800
CR_FONTFIRST = $80
CR_FONTCOUNT = $80

;  A mode 7 plane is 128 cells wide, and a flat one shows 32 of them.
CR_STRIDE    = 128
CR_COLUMNS   = 32

;  Colours.  Index 0 is the backdrop, and the expanded font uses 1.  The
;  prologue's: white text on its blue.
COL_BACK     = NESCOL_01
COL_INK      = NESCOL_30

;  The scroll is in the same units as the generator's distances, 1/8 texel.
;  At 0 the first row of the text is on the bottom line of the screen.
CR_START     = 0
CR_SPEED     = 2                ; per frame: half a texel
CR_OFFPLANE  = -512             ; a row above the plane, for the blank lines

;  The game's joy bits, as ProcessJoyButtons masks for them.
PAD_START    = $10
PAD_B        = $40
PAD_A        = $80

CR_SCROLL    = CREDITSRAM+$00   ; 2 bytes: how far the text has moved
CR_WRAP      = CREDITSRAM+$02   ; 2 bytes: ...and how far it goes before restarting
CR_ROW       = CREDITSRAM+$04   ; 2 bytes: the plane row being written
CR_COL       = CREDITSRAM+$06   ; 2 bytes: ...and its first column
CR_FONTSRC   = CREDITSRAM+$08   ; 2 bytes: how far into the font
CR_BACK      = CREDITSRAM+$0A   ; which row buffer cr_fill writes next, 0 or 1
CR_PREV      = CREDITSRAM+$0B   ; the pad last frame
CR_EDGE      = CREDITSRAM+$0C   ; buttons that went down this frame
CR_YBLANK    = CREDITSRAM+$10   ; 2 bytes: CR_OFFPLANE, for the blank lines
CR_YBUF0     = CREDITSRAM+$100  ; the two row buffers, a word per line --
CR_YBUF1     = CREDITSRAM+$300  ;   at most 224 lines, so $1C0 bytes each
.assert CR_YBUF1 + $1C0 <= CREDITSRAM_END, error, "the credits' WRAM runs past CREDITSRAM_END"

;  One line of the text: a length and then the characters, in the game's
;  encoding.  A line of nothing is a blank row.
;
;  Three characters beyond the game's font are allowed, written as
;  themselves, each the crawl's own glyph: a colon and a slash, for a URL
;  (user, 2026-10-19), and the copyright sign -- the source is UTF-8, so a
;  (c) arrives as the two bytes $C2 $A9.  The font has the dash and the
;  period (fftext.inc).  Anything else outside it is still an error.
.macro CRLINE txt
  .local n
  n .set 0
  .repeat .strlen(txt), i
    .if .strat(txt, i) <> $C2
      n .set n + 1
    .endif
  .endrep
  .if n > CR_COLUMNS
    .error "credits line wider than the screen"
  .endif
  .byte n
  .repeat .strlen(txt), i
    .if .strat(txt, i) = $C2
      .if .strat(txt, i + 1) <> $A9
        .error "the only two-byte character the crawl adds to the font is the copyright sign"
      .endif
    .elseif .strat(txt, i) = $A9
      .byte CR_GLYPH_COPYRIGHT
    .elseif .strat(txt, i) = ':'
      .byte CR_GLYPH_COLON
    .elseif .strat(txt, i) = '/'
      .byte CR_GLYPH_SLASH
    .else
      FFCHAR {.strat(txt, i)}
    .endif
  .endrep
.endmacro

;;  In emulation mode, from the title screen, by JSL.  Returns by RTL with the
;;  PPU in forced blank and handed back to the HAL.
credits_screen:
    PHB
    PHK
    PLB                         ; this chunk's low half is the I/O map

    ;  No chirp for appearing: the title's press chirped as it was heard
    ;  (opt_titlechirp).

    ;  Dark from the top of a vblank, so nothing of the title screen tears.
    JSR cr_frame
    LDA #$80
    STA a:INIDISP
    STZ a:HDMAEN                ; any channel the HAL left running is its own

    JSR cr_build

    LDA #<CR_START
    STA f:CR_SCROLL
    LDA #>CR_START
    STA f:CR_SCROLL+1
    LDA #$00
    STA f:CR_BACK
    JSR cr_fill                 ; the first frame's rows

    ;  HDMA comes on inside a vblank, so the first frame it sees is a whole
    ;  one: a channel enabled mid-picture starts from a table it never loaded.
    JSR cr_frame
    JSR cr_vblank
    LDA #$E0
    STA a:HDMAEN                ; channels 5, 6 and 7
    LDA #$0F
    STA a:INIDISP               ; ...and on

    ;  ...and the other buffer, before the loop's first vblank shows it.  The
    ;  loop fills after it flips, so without this its first frame is whatever
    ;  that buffer held from the last visit -- a flash of the crawl where it
    ;  was left.  (On a first visit it is zeros, every line on the text's top
    ;  pixel row, which is blank, so the bug hid until a second visit.)
    JSR cr_fill

    JSR cr_waitrelease          ; the A that brought us here

  @loop:
    JSR cr_frame
    JSR cr_vblank
    JSR cr_advance
    JSR cr_fill

    LDA joy                     ; down now and not down last frame
    EOR f:CR_PREV
    AND joy
    STA f:CR_EDGE
    LDA joy
    STA f:CR_PREV

    LDA f:CR_EDGE
    AND #PAD_A | PAD_B | PAD_START
    BEQ @loop

    ;  Backing out is a choice, and the game chirps for B as for A.
    CALL0E PlaySFX_MenuSel
    JSR cr_waitrelease          ; returns at the top of a vblank...
    LDA #$80
    STA a:INIDISP               ; ...so this blanks between pictures
    STZ a:HDMAEN
    JSL hal_ppureclaim + HALFAR
    PLB
    RTL


;;  One frame of the game's services, and then the top of the next vblank.
;;
;;  The music driver and the pad reader are the game's code and want
;;  emulation mode, so this is called in it.  The sound goes out and the wait
;;  happens in hal_vblaudio, which leaves the PPU alone; what the caller does
;;  next is the first thing to happen in the vblank.
cr_frame:
    ;  cur_bank is where CallMusicPlay swaps back to.  The settings screen
    ;  explains why it is set every time rather than once.
    LDA #CHUNK_CREDITS
    STA cur_bank
    JSR CallMusicPlay
    JSR UpdateJoy
    JSL hal_vblaudio + HALFAR
    RTS


;;  Wait for the pad to read zero, then start from a clean slate.  See
;;  opt_waitrelease, which this is, but for the frame it breathes with.
cr_waitrelease:
  @wait:
    JSR cr_frame
    LDA joy
    BNE @wait
    STA f:CR_PREV
    STA f:CR_EDGE
    STA joy_a
    STA joy_b
    STA joy_start
    STA joy_select
    STA joy_prevdir
    STA joy_ignore
    RTS


;;  This frame's register writes.  Called first thing in the vblank.
;;
;;  Points the row channel at the buffer cr_fill wrote last, and makes the
;;  other one next to be written.  The address takes effect when HDMA reloads
;;  it at the top of the coming frame, so the picture never sees a buffer
;;  half-written.
cr_vblank:
    LDA f:CR_BACK
    BNE @one
    LDA #<lut_CrawlY0
    STA a:A1T7L
    LDA #>lut_CrawlY0
    STA a:A1T7H
    LDA #1
    STA f:CR_BACK
    RTS
  @one:
    LDA #<lut_CrawlY1
    STA a:A1T7L
    LDA #>lut_CrawlY1
    STA a:A1T7H
    LDA #0
    STA f:CR_BACK
    RTS


;;  Move the plane on, and start the text over once it has gone off the top.
cr_advance:
    CLC
    XCE
    REP #$20
    .a16
    LDA f:CR_SCROLL
    CLC
    ADC #CR_SPEED
    STA f:CR_SCROLL
    SEC
    SBC f:CR_WRAP
    BMI @keep                   ; small numbers both: the sign is the answer
    LDA #.loword(CR_START)
    STA f:CR_SCROLL
  @keep:
    SEP #$20
    .a8
    SEC
    XCE
    RTS


;;  Each visible line's row of the text, into the buffer CR_BACK names: the
;;  scroll less the line's distance up the plane, in whole texels.  The
;;  distance is larger the higher the line, so the top of the screen shows
;;  text that went by earlier -- the crawl moves away from the eye.
;;
;;  Called in emulation mode, during the picture; returns in it.
cr_fill:
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA f:CR_BACK
    AND #$00FF
    BEQ @first
    LDA #CR_YBUF1 - CR_YBUF0
  @first:
    TAX
    LDY #$0000
  @line:
    LDA f:CR_SCROLL
    SEC
    SBC lut_CrawlV, Y
  .repeat CRAWL_SUBBITS
    CMP #$8000                  ; an arithmetic shift: a row can be negative,
    ROR A                       ;   while the text has yet to reach the line
  .endrepeat
    STA f:CR_YBUF0, X
    INX
    INX
    INY
    INY
    CPY #CRAWL_LINES * 2
    BNE @line
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    RTS


;;  Everything the screen shows, built under forced blank.
cr_build:
    CLC
    XCE
    REP #$10
    .i16

    ;  Both bytes of the first 16K words of VRAM to zero, which is the whole
    ;  of what mode 7 reads.  That leaves every cell of the plane on tile 0 and
    ;  every character transparent, so tile 0 is a blank, and so is anything
    ;  the font below does not cover.
    LDA #$80
    STA a:VMAIN                 ; step after each $2119 write
    LDX #$0000
    STX a:VMADDL
    LDA #$09                    ; fixed source, two registers
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDX #.loword(cr_zero)
    STX a:A1T0L
    LDA #CR_BANK
    STA a:A1B0
    LDX #$8000                  ; 32KB
    STX a:DAS0L
    LDA #$01
    STA a:MDMAEN

    STZ a:CGADD
    LDX #$0000
  @pal:
    LDA lut_CreditsPalette, X
    STA a:CGDATA
    INX
    CPX #4
    BNE @pal

    JSR cr_drawtext
    JSR cr_drawglyphs

    SEP #$10
    .i8
    SEC
    XCE

    JSR cr_loadfont

    LDA #$07
    STA a:BGMODE
    LDA #$80                    ; outside the plane is transparent, so the
    STA a:M7SEL                 ;   text has nothing above or below it
    LDA #$01
    STA a:TM                    ; the plane, and no sprites
    STZ a:TS
    STZ a:TMW
    STZ a:CGADSUB

    ;  B, C and D stay at zero, which is what makes a line's texture row M7Y
    ;  alone and its horizontal scale M7A alone.  Each entry is written low
    ;  byte then high; A and the row come from HDMA.
    STZ a:M7B
    STZ a:M7B
    STZ a:M7C
    STZ a:M7C
    STZ a:M7D
    STZ a:M7D
    LDA #<CRAWL_CENTRE          ; scaled about the text's centre column
    STA a:M7X
    LDA #>CRAWL_CENTRE
    STA a:M7X
    STZ a:BG1HOFS
    STZ a:BG1HOFS
    STZ a:BG1VOFS
    STZ a:BG1VOFS

    LDA #<CR_OFFPLANE
    STA f:CR_YBLANK
    LDA #>CR_OFFPLANE
    STA f:CR_YBLANK+1

    ;  Channel 5: the text's colour, a line at a time over the top of the
    ;  screen.  Mode 3 writes CGADD twice and CGDATA twice, so each line's
    ;  four bytes are the entry, the entry again, and the colour.
    LDA #$03
    STA a:DMAP5
    LDA #<CGADD
    STA a:BBAD5
    LDA #<lut_CrawlFade
    STA a:A1T5L
    LDA #>lut_CrawlFade
    STA a:A1T5H
    LDA #CR_BANK
    STA a:A1B5

    ;  Channel 6: M7A, two bytes to the one register, straight from ROM.
    LDA #$02
    STA a:DMAP6
    LDA #<M7A
    STA a:BBAD6
    LDA #<lut_CrawlA
    STA a:A1T6L
    LDA #>lut_CrawlA
    STA a:A1T6H
    LDA #CR_BANK
    STA a:A1B6
    ;  Channel 7: M7Y, the same but indirect -- the table is in ROM and its
    ;  entries point into the row buffers.  cr_vblank chooses the table.
    LDA #$42
    STA a:DMAP7
    LDA #<M7Y
    STA a:BBAD7
    LDA #CR_BANK
    STA a:A1B7
    LDA #^CREDITSRAM
    STA a:DASB7
    RTS


;;  The text, into the low bytes of the plane, one line to a row and each one
;;  centred.  Leaves in CR_WRAP how far the scroll goes before the text has
;;  all gone by.  Native, X and Y 16-bit.
.a8
.i16
cr_drawtext:
    STZ a:VMAIN                 ; step after each $2118 write: the cells
    LDA #$00
    STA f:CR_ROW
    STA f:CR_ROW+1
    LDY #$0000
  @line:
    ;  Bounded by the table's size rather than a terminator, so a dropped end
    ;  marker cannot send it reading into whatever follows.
    CPY #CR_TEXTSIZE
    BCS @done
    LDA lut_CreditsText, Y
    INY
    REP #$20
    .a16
    AND #$00FF
    BEQ @next                   ; a blank row
    TAX                         ; X = the characters to write
    EOR #$FFFF
    INC A
    CLC
    ADC #CR_COLUMNS
    LSR A                       ; (32 - length) / 2, the column that centres it
    STA f:CR_COL
    LDA f:CR_ROW
    XBA                         ; row * 256...
    LSR A                       ; ...halved, is the plane's stride of 128
    CLC
    ADC f:CR_COL
    STA a:VMADDL
    SEP #$20
    .a8
  @char:
    LDA lut_CreditsText, Y
    STA a:VMDATAL
    INY
    DEX
    BNE @char
    REP #$20
    .a16
  @next:
    LDA f:CR_ROW
    INC A
    STA f:CR_ROW
    SEP #$20
    .a8
    BRA @line
  @done:
    ;  The text has gone when the top visible line is past its last row:
    ;  eight texels a row, in eighths, plus the top line's own distance.
    REP #$20
    .a16
    LDA f:CR_ROW
  .repeat 3 + CRAWL_SUBBITS
    ASL A
  .endrepeat
    CLC
    ADC #CRAWL_VMAX
    STA f:CR_WRAP
    SEP #$20
    .a8
    RTS


;;  The crawl's own glyphs, from one bit a pixel to mode 7's eight, into the
;;  tiles below the font that nothing else uses.  Native, X and Y 16-bit.
.a8
.i16
cr_drawglyphs:
    LDA #$80
    STA a:VMAIN                 ; the characters are the high bytes
    LDX #CR_GLYPHFIRST * 64     ; 64 words to a tile
    STX a:VMADDL
    LDX #$0000
  @row:
    LDA lut_CrawlGlyphs, X
  .repeat 8                     ; as in cr_loadfont: carry is the pixel
    ASL A
    XBA
    LDA #$00
    ROL A
    STA a:VMDATAH
    XBA
  .endrepeat
    INX
    CPX #CR_GLYPHSIZE
    BNE @row
    RTS


;;  The font, from two bits a pixel to mode 7's eight.
;;
;;  A glyph is ink (colour 3) on the box's own blue (colour 2), so the ink is
;;  exactly where both planes are set and the rest is background: one AND
;;  makes the row, and each pixel is a bit shifted out of it.  Colour 1 is the
;;  only one the expanded font uses.
;;
;;  Sixteen tiles to a frame, with the game's services in between, so the
;;  music does not stall while the whole font goes through.  The breath comes
;;  before each slice rather than after it, because the VRAM clear ahead of the
;;  first one is most of a frame by itself.  The screen is in forced blank
;;  throughout, so VRAM is open at any point in the frame, and nothing between
;;  slices touches the address the slice left behind.
;;
;;  Called in emulation mode; returns in it.
.a8
.i8
cr_loadfont:
    LDA #$80
    STA a:VMAIN                 ; the characters are the high bytes
    LDA #<(CR_FONTFIRST * 64)   ; 64 words to a tile
    STA a:VMADDL
    LDA #>(CR_FONTFIRST * 64)
    STA a:VMADDH
    LDA #$00
    STA f:CR_FONTSRC
    STA f:CR_FONTSRC+1

  @slice:
    JSR cr_frame                ; a breath
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA f:CR_FONTSRC
    TAX
    SEP #$20
    .a8
  @tile:
    LDY #8
  @row:
    LDA f:MENUCHR, X
    AND f:MENUCHR + 8, X
    ;  B holds the row while A builds each pixel: the shift puts the
    ;  leftmost pixel in carry, and the swap keeps the rest of the row.
  .repeat 8
    ASL A
    XBA
    LDA #$00
    ROL A
    STA a:VMDATAH
    XBA
  .endrepeat
    INX
    DEY
    BNE @row
    REP #$20
    .a16
    TXA
    CLC
    ADC #8                      ; past the second plane
    TAX
    SEP #$20
    .a8
    TXA                         ; the low byte alone: sixteen tiles are 256
    BNE @tile                   ;   bytes, so it is zero at the end of a slice
    REP #$20
    .a16
    TXA
    STA f:CR_FONTSRC
    SEP #$30
    .a8
    .i8
    SEC
    XCE

    LDA f:CR_FONTSRC+1
    CMP #>(CR_FONTCOUNT * 16)
    BCS @done
    JMP @slice                  ; the unrolled row is past a branch's reach
  @done:
    RTS


cr_zero:
  .word $0000

;  The row channel's two tables, one per buffer.
lut_CrawlY0:
  CRAWL_YTABLE CR_YBUF0, CR_YBLANK
lut_CrawlY1:
  CRAWL_YTABLE CR_YBUF1, CR_YBLANK

lut_CreditsPalette:
  .word COL_BACK, COL_INK

;  Placeholder.  The plane is 128 rows deep, which is room for that many
;  lines before the table has to be drawn in pieces.
;  Glyphs the game's font does not have, one bit a pixel, starting at tile
;  CR_GLYPHFIRST.  Drawn the way the font is: the top row blank and the left
;  column blank, so it spaces like any other letter.
CR_GLYPHFIRST = $01             ; tile 0 is the blank every empty cell shows
lut_CrawlGlyphs:
CR_GLYPH_COPYRIGHT = CR_GLYPHFIRST + (* - lut_CrawlGlyphs) / 8
  .byte %00000000
  .byte %00011100
  .byte %00100010
  .byte %01011101
  .byte %01010001
  .byte %01011101
  .byte %00100010
  .byte %00011100
;  The colon and the slash in the font's two-pixel strokes: the colon's dots
;  at the lowercase letters' top and on the line, as the period's is; the
;  slash the capitals' height.
CR_GLYPH_COLON = CR_GLYPHFIRST + (* - lut_CrawlGlyphs) / 8
  .byte %00000000
  .byte %00000000
  .byte %00000000
  .byte %00011000
  .byte %00011000
  .byte %00000000
  .byte %00011000
  .byte %00011000
CR_GLYPH_SLASH = CR_GLYPHFIRST + (* - lut_CrawlGlyphs) / 8
  .byte %00000000
  .byte %00000110
  .byte %00001100
  .byte %00001100
  .byte %00011000
  .byte %00110000
  .byte %00110000
  .byte %01100000
CR_GLYPHSIZE = * - lut_CrawlGlyphs
.assert CR_GLYPHFIRST + CR_GLYPHSIZE / 8 <= CR_FONTFIRST, error, "the crawl's glyphs run into the font"

lut_CreditsText:
  CRLINE ""
  CRLINE "SUPER FINAL FANTASY"
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE "A GOATSPIRATE Joint"
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE "Based on"
  CRLINE "FINAL FANTASY"
  CRLINE ""
  CRLINE "© 1987 Square  "
  CRLINE "© 1990 Nintendo"
  CRLINE ""
  CRLINE "Square A-Team"
  CRLINE ""
  CRLINE "Programmed By"
  CRLINE "N A S I R"
  CRLINE ""
  CRLINE "Concept"
  CRLINE "Hironobu Sakaguchi"
  CRLINE ""
  CRLINE "Characters"
  CRLINE "Yoshitaka Amano"
  CRLINE ""
  CRLINE "Scenario"
  CRLINE "Kenji Terada"
  CRLINE ""
  CRLINE "Music"
  CRLINE "Nobuo Uematsu"
  CRLINE ""
  CRLINE "Translation"
  CRLINE "Phil Sandhop"
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE "FF1 DISASSEMBLY"
  CRLINE ""
  CRLINE "by Disch"
  CRLINE ""
  CRLINE ""
  CRLINE ""
  CRLINE "FINAL FANTASY RANDOMIZER"
  CRLINE ""
  CRLINE "Created by ENTROPER"
  CRLINE ""
  CRLINE ""
  CRLINE "DEVELOPERS"
  CRLINE ""
  CRLINE "Entroper               "
  CRLINE "MeridianBC     nitz    "
  CRLINE "Septimus       tartopan"
  CRLINE "RetroFanMan    wildham "
  CRLINE "MadMartin      tetron  "
  CRLINE "liferboot      Twinge  "
  CRLINE "    "
  CRLINE "    "
  CRLINE "CONTRIBUTORS"
  CRLINE "    "
  CRLINE "  artea         drcatdoctor  "
  CRLINE "  nic0lette     splitpunched "
  CRLINE "  onefineday    Darkmoon     "
  CRLINE "  pinkpuff      bdjeffyp     "
  CRLINE "  jat2980       Chronometrics"
  CRLINE "  Oslodo        Barber       "
  CRLINE "  FranklinRN    Inferna      "
  CRLINE "  xxxxxxxxxxxxxxx            "
  CRLINE "    "
  CRLINE "    "
  CRLINE "PLAYTESTING"
  CRLINE "    "
  CRLINE "  jkoper         Kababesh   "
  CRLINE "  Miaut          Ayntlerz   "
  CRLINE "  gameboy9       sbq92      "
  CRLINE "  EunosXX        Xarnax42   "
  CRLINE "  theCubeMiser   Beefucurry "
  CRLINE "  Jaylow7        Ategenos   "
  CRLINE "  TristalMTG     PanzerDave "
  CRLINE "  Buffalax       crimsonavix"
  CRLINE "  VampireKnight  Angelique  "
  CRLINE "  DarkwingDuck.sda          "
  CRLINE ""
  CRLINE ""
  CRLINE "Special Thanks"
  CRLINE ""
  CRLINE "fcoughlin      Gyre  "
  CRLINE "Paulygon       anomie"
  CRLINE "Derangedsquirrel"
  CRLINE "AstralEsper"
  CRLINE ""
  CRLINE "and"
  CRLINE ""
  CRLINE "The Entire FFR"
  CRLINE "Community"
  CRLINE ""
  CRLINE ""
  CRLINE "For the full FFR"
  CRLINE "experience, visit:"
  CRLINE ""
  CRLINE "finalfantasyrandomizer.com"
CR_TEXTSIZE = * - lut_CreditsText
