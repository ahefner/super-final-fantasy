; ---------------------------------------------------------------------------
;  mapselect.inc -- New Game's Map Select (user, 2026-11-15), included in
;  owscreen.asm (CHUNK_OWS): its PPU setup (ows_ppu), sound, frame wait,
;  reset, text and chirps are the map edit screen's.
;
;  After the randomization screen, the maps of maps/custom-maps.txt
;  (genmaps.py), the game's first: choosing it goes on to the map edit
;  screen, any other to the options, with no map edits.  The selected
;  map's minimap centred at the top, its start ringed; "MAP" and "SELECT"
;  at its left; below, in the game's dialog box frame, the names in two
;  columns, the first half (rounded up) on the left -- the hand over the
;  frame there, so a name on the left may be 13 letters (the user's "Final
;  Fantasy").  Up and down step through the list, down the left column and
;  on down the right, round from either end; left and right cross between
;  the columns, to the same row or the right column's last.  A or START
;  chooses, B goes back to the randomization screen, either with the
;  select's chirp, and the map the hand is on is NGF_MAP.  The hand moves
;  and chirps at once; the minimap follows a few frames after.
;
;  A minimap is 8KB of characters in a chunk's low half, sent straight from
;  ROM into whichever of two sets of BG1 characters is not on screen, 2KB a
;  vblank; the vblank that sends the last piece switches BG1 to that set's
;  tilemap -- BG1SC, one write -- and the ring goes to that map's start, so
;  no frame shows half of one map and half of another.  A move while one is
;  on its way starts the new one in its place.  The screen comes up with
;  the minimap whole.  The title's music plays on; L + X and L + Y reset.
; ---------------------------------------------------------------------------

;  VRAM, in words, past the map edit screen's (owscreen.asm).
MS_SETB   = $1000               ; the second set of BG1 characters: 256 on
MS_MAPB   = $3800               ; ...and its tilemap; the first set's VR_BG1MAP
MS_BLANK  = 767                 ; a BG1 character nothing writes: $2FF0, past the font
MS_PIECE  = $800                ; a minimap's bytes sent a vblank
MS_PIC    = 256 * 32
.assert MS_SETB = VR_BG1CHR + 256 * 16, error, "the second set straight after the first"
.assert MS_MAPB >= VR_BG3MAP + $400 && MS_MAPB + $400 <= VR_OBJCHR, error, "the second tilemap overlaps"
.assert MS_BLANK * 16 >= VR_BG3CHR + 256 * 8 && MS_BLANK * 16 + 16 <= VR_BG1MAP, error, "the blank character is written"
.assert (MS_PIC .MOD MS_PIECE) = 0, error, "a minimap in whole pieces"

;  Where things are, in BG cells, inside the 30 x 26 a CRT shows.
MS_MAPCOL   = 8                 ; the minimap, 16 x 16, centred
MS_MAPROW   = 1
MS_TITLECOL = 1                 ; "MAP", and "SELECT" under it
MS_TITLEROW = 1
MS_BOXL     = 1                 ; the names' frame
MS_BOXR     = 30
MS_BOXTOP   = 17
MS_BOXBOT   = 26
MS_NAMEROW  = 18
MS_LEFTCOL  = 3                 ; the hand two cells before: over the frame
MS_RIGHTCOL = 18
.assert MS_RIGHTCOL - 2 >= MS_LEFTCOL + MAPS_LEFTW, error, "the right column's hand over a left name"
.assert MS_RIGHTCOL + MAPS_RIGHTW <= MS_BOXR, error, "a right name over the frame"
.assert MS_NAMEROW + MAPS_ROWS <= MS_BOXBOT, error, "the names past the frame"
.assert MS_TITLECOL + 6 <= MS_MAPCOL, error, "the title over the minimap"

;  The screen's variables, past the map edit screen's in its page; V_T, V_PREV,
;  V_ERR, V_PAL, V_K, V_N, V_TILE and V_VADDR shared.
M_SEL     = OWV+$60             ; the map the hand is on
M_SHOWN   = OWV+$61             ; the map on screen
M_LOAD    = OWV+$62             ; the map on its way to the set not shown, or $FF
M_FRONT   = OWV+$63             ; the set on screen: 0 the first, 1 the second
M_OFF     = OWV+$64             ; 2: the bytes of M_LOAD's sent
M_BACK    = OWV+$66             ; nonzero: B ended it
.assert V_INCLOOSE < M_SEL && M_BACK < OWS_VARS + $100, error, "Map Select's variables"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ms_choose -- the screen.  In: NGF_MAP the map to start on.  Out: NGF_MAP
;;  the map the hand is on; A = NGNAV_BACK if B ended it, else
;;  NGNAV_FORWARD; the display off, the PPU the HAL's.  From the New Game
;;  flow, by JSL, in emulation mode; out the same, X and Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ms_choose:
    PHP
    PHX
    PHY
    PHB
    PHK
    PLB                         ; this chunk's low half is the I/O map
    SEP #$30
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    LDA #0
    STA f:M_BACK
    JSR ms_start
    JSR ms_setup
    JSR ms_loop
    LDA f:M_SEL
    STA f:NGF_MAP
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    LDA #$80
    STA a:INIDISP
    JSL hal_ppureclaim + HALFAR
    LDA f:M_BACK
    BEQ :+
    LDA #NGNAV_BACK - NGNAV_FORWARD
:   CLC
    ADC #NGNAV_FORWARD          ; NGNAV_BACK if B ended it, else NGNAV_FORWARD
    PLB
    PLY
    PLX
    PLP
    RTL

;;  For the harness: the screen's setup, as far as the display going on,
;;  from NGF_MAP; from emulation mode by JSL.
ms_testsetup:
    PHB
    PHK
    PLB
    CLC
    XCE
    REP #$10
    .i16
    SEP #$20
    .a8
    JSR ms_start
    JSR ms_setup
    JMP ows_testout

;;  The selection NGF_MAP's -- the first, for a map past the list's end --
;;  and the frame's music, not the error sound (ows_music).  A8 I16.
    .a8
    .i16
ms_start:
    LDA #0
    STA f:V_ERR
    LDA f:NGF_MAP
    CMP #MAPS_N
    BCC :+
    LDA #0
:   STA f:M_SEL
    RTS


;;  Setup: the map edit screen's VRAM, CGRAM, OAM and registers; the two
;;  tilemaps; the text; the selected map's minimap whole, its set on
;;  screen; the hand and the ring; the display on.  A8 I16, DBR this chunk.
    .a8
    .i16
ms_setup:
    JSR ows_ppu
    JSR ms_bg1maps
    JSR ows_audio
    LDA #0
    STA f:V_T                   ; the ring shown
    LDA #$FF
    STA f:V_PREV                ; nothing counts as pressed until let go
    LDA f:M_SEL
    STA f:M_SHOWN
    JSR ms_text
    REP #$20
    .a16
    LDA #VR_BG3MAP
    STA f:V_VADDR
    LDX #.LOWORD(OWS_NT3)
    LDY #28 * 64
    SEP #$20
    .a8
    JSR ows_dma
    ;  The minimap, into the first set as if the second were up -- so its
    ;  last piece puts the first on screen -- in pieces, the music's chance
    ;  before each.
    LDA #1
    STA f:M_FRONT
    LDA f:M_SEL
    STA f:M_LOAD
    REP #$20
    .a16
    LDA #0
    STA f:M_OFF
    SEP #$20
    .a8
  @pic:
    JSR ows_audio
    JSR ms_piece
    LDA f:M_LOAD
    CMP #$FF
    BNE @pic
    JSR ms_sprites
    LDA #$0F
    STA a:INIDISP
    RTS

;;  BG1's two tilemaps, blank but for the minimap's 16 x 16: the first's
;;  characters 0-255, the second's 256-511, palette 2.  A8 I16.
    .a8
    .i16
ms_bg1maps:
    LDA #$80
    STA a:VMAIN
    REP #$20
    .a16
    LDA #VR_BG1MAP
    LDY #$0000
    JSR @one
    LDA #MS_MAPB
    LDY #$0100
    JSR @one
    SEP #$20
    .a8
    RTS
    .a16
  @one:                         ; A the tilemap, Y its first character
    STA f:V_VADDR
    STA a:VMADDL
    LDX #32 * 32
    LDA #MS_BLANK
  @blank:
    STA a:VMDATAL
    DEX
    BNE @blank
    TYA
    ORA #$0800                  ; palette 2
    STA f:V_TILE                ; the next cell's entry
    LDA f:V_VADDR
    CLC
    ADC #MS_MAPROW * 32 + MS_MAPCOL
    STA f:V_VADDR
    LDY #16
  @row:
    LDA f:V_VADDR
    STA a:VMADDL
    CLC
    ADC #32
    STA f:V_VADDR
    LDX #16
  @cell:
    LDA f:V_TILE
    STA a:VMDATAL
    INC A
    STA f:V_TILE
    DEX
    BNE @cell
    DEY
    BNE @row
    RTS
    .a8

;;  BG3's tilemap in WRAM (OWS_NT3): the title, the frame and the names.
;;  A8 I16.
    .a8
    .i16
ms_text:
    REP #$20
    .a16
    LDA #0
    LDX #0
  @clear:
    STA f:OWS_NT3, X
    INX
    INX
    CPX #28 * 64
    BCC @clear
    SEP #$20
    .a8
    LDA #0
    STA f:V_PAL
    LDX #.LOWORD(lut_MsTitle)
    LDY #(MS_TITLEROW * 32 + MS_TITLECOL) * 2
    LDA #3                      ; "MAP"...
    JSR ows_text
    LDY #((MS_TITLEROW + 1) * 32 + MS_TITLECOL) * 2
    LDA #6                      ; ..."SELECT"
    JSR ows_text
    JSR ms_frame
    ;  The names, each at its row of its column: the left column's
    ;  MAPS_LEFTW letters, the right's MAPS_RIGHTW, their padding's last
    ;  left off, the frame there.
    LDA #0
    STA f:V_PAL
    STA f:V_K
    LDX #.LOWORD(lut_MapName)
  @name:
    PHX                         ; the name
    LDA f:V_K
    REP #$20
    .a16
    AND #$00FF
    CMP #MAPS_ROWS
    BCC @left
    SBC #MAPS_ROWS              ; (C set)
    XBA
    LSR A
    LSR A                       ; its row, times 64
    ADC #(MS_NAMEROW * 32 + MS_RIGHTCOL) * 2
    TAY
    SEP #$20
    .a8
    LDA #MAPS_RIGHTW
    BRA @draw
    .a16
  @left:
    XBA
    LSR A
    LSR A
    ADC #(MS_NAMEROW * 32 + MS_LEFTCOL) * 2     ; (C clear)
    TAY
    SEP #$20
    .a8
    LDA #MAPS_LEFTW
  @draw:
    JSR ows_text
    REP #$20
    .a16
    PLA
    CLC
    ADC #MAPS_LEFTW             ; the next name
    TAX
    SEP #$20
    .a8
    LDA f:V_K
    INC A
    STA f:V_K
    CMP #MAPS_N
    BCC @name
    RTS

;;  The names' frame, rows MS_BOXTOP-MS_BOXBOT, columns MS_BOXL-MS_BOXR, in
;;  the game's dialog box tiles.  A8 I16.
    .a8
    .i16
ms_frame:
    LDA #FRAME_PAL
    STA f:V_PAL
    LDX #(MS_BOXTOP * 32 + MS_BOXL) * 2
    LDA #FRAME_CHR + 0          ; the top: its corner, edge and corner
    JSR @line
    LDA #MS_BOXBOT - MS_BOXTOP - 1
    STA f:V_K
    LDX #((MS_BOXTOP + 1) * 32 + MS_BOXL) * 2
  @side:
    LDA #FRAME_CHR + 3          ; the left...
    JSR ows_putch
    LDA f:OWS_NT3 - 1, X        ; ...below the sprites, BG3's priority off:
    AND #<~$20                  ;   the left column's hand is over it (with
    STA f:OWS_NT3 - 1, X        ;   it, BG3 above everything, BGMODE)
    REP #$20
    .a16
    TXA
    CLC
    ADC #(MS_BOXR - MS_BOXL - 1) * 2
    TAX
    SEP #$20
    .a8
    LDA #FRAME_CHR + 4          ; ...and the right
    JSR ows_putch
    REP #$20
    .a16
    TXA
    CLC
    ADC #64 - (MS_BOXR - MS_BOXL + 1) * 2
    TAX
    SEP #$20
    .a8
    LDA f:V_K
    DEC A
    STA f:V_K
    BNE @side
    LDA #FRAME_CHR + 5          ; the bottom
  @line:
    ;  A line from X: A, then A + 1 across, then A + 2.
    PHA
    JSR ows_putch
    LDA #MS_BOXR - MS_BOXL - 1
    STA f:V_N
    PLA
    INC A
    PHA
  @mid:
    LDA 1, S
    JSR ows_putch
    LDA f:V_N
    DEC A
    STA f:V_N
    BNE @mid
    PLA
    INC A
    JMP ows_putch


;;  The loop: a frame, its vblank's transfers, the music, the pad.  Out when
;;  A, START or B is pressed.  A8 I16.
    .a8
    .i16
ms_loop:
  @frame:
    JSR ows_wait
    JSR ms_vblank
    JSR ows_playframe
    JSR ows_reset
    LDA f:V_T
    INC A
    STA f:V_T
    JSR ms_input
    BCC @frame
    RTS

;;  The vblank's work: a piece of the minimap on its way, the sprites.  A8
;;  I16, DBR this chunk.
    .a8
    .i16
ms_vblank:
    LDA f:M_LOAD
    CMP #$FF
    BEQ :+
    JSR ms_piece
:   JMP ms_sprites

;;  The next MS_PIECE bytes of M_LOAD's minimap, from ROM into the set not on
;;  screen; with the last, that set on screen (BG1SC) and M_SHOWN the map.
;;  In a vblank or forced blank.  A8 I16.
    .a8
    .i16
ms_piece:
    LDA #$80
    STA a:VMAIN
    LDA f:M_LOAD
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_MapPicBank, X
    STA a:A1B0
    REP #$20
    .a16
    TXA
    ASL A
    TAX
    LDA f:OWSFAR + lut_MapPicLo, X
    CLC
    ADC f:M_OFF
    STA a:A1T0L
    LDA #MS_PIECE
    STA a:DAS0L
    LDA f:M_FRONT               ; the set not on screen
    AND #$00FF
    BEQ :+
    LDA #.LOWORD(VR_BG1CHR - MS_SETB)   ; the first, the second being up
:   CLC
    ADC #MS_SETB
    STA f:V_VADDR
    LDA f:M_OFF
    LSR A                       ; in words
    CLC
    ADC f:V_VADDR
    STA a:VMADDL
    LDA f:M_OFF
    CLC
    ADC #MS_PIECE
    STA f:M_OFF
    SEP #$20
    .a8
    LDA #$01                    ; two registers, from ROM
    STA a:DMAP0
    LDA #<VMDATAL
    STA a:BBAD0
    LDA #$01
    STA a:MDMAEN
    REP #$20
    .a16
    LDA f:M_OFF
    CMP #MS_PIC
    SEP #$20
    .a8
    BCC @out
    ;  The last: that set on screen.
    LDA f:M_FRONT
    EOR #1
    STA f:M_FRONT
    BEQ :+
    LDA #(MS_MAPB >> 8)
    BRA :++
:   LDA #(VR_BG1MAP >> 8)
:   STA a:BG1SC
    LDA f:M_LOAD
    STA f:M_SHOWN
    LDA #$FF
    STA f:M_LOAD
  @out:
    RTS

;;  OAM: the hand at the selected name, two cells before it; the ring at
;;  the start of the map on screen, blinking as the map edit screen's.
;;  A8 I16.
    .a8
    .i16
ms_sprites:
    STZ a:OAMADDL
    STZ a:OAMADDH
    LDA f:M_SEL
    CMP #MAPS_ROWS
    BCS @right
    PHA
    LDA #MS_LEFTCOL * 8 - 16
    BRA @x
  @right:
    SBC #MAPS_ROWS              ; (C set): its row
    PHA
    LDA #MS_RIGHTCOL * 8 - 16
  @x:
    STA a:OAMDATA
    PLA
    ASL A
    ASL A
    ASL A
    CLC
    ADC #MS_NAMEROW * 8 - 1
    STA a:OAMDATA               ; y: the line's top, less one
    LDA #OBJ_HAND
    STA a:OAMDATA
    LDA #$32                    ; above everything, palette 1
    STA a:OAMDATA
    LDA f:V_T
    AND #$20
    BNE @hide
    LDA f:M_SHOWN
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:OWSFAR + lut_MapStartX, X
    LSR A
    CLC
    ADC #<(MS_MAPCOL * 8 - 8)
    STA a:OAMDATA
    LDA f:OWSFAR + lut_MapStartY, X
    LSR A
    CLC
    ADC #<(MS_MAPROW * 8 - 8 - 1)
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
    RTS


;;  The pad, answered at once.  C set when A, START or B ends the screen.
;;  A8 I16.
    .a8
    .i16
ms_input:
    JSR ows_edge                ; pressed this frame
    BIT #PAD_A | PAD_START
    BNE @end
    BIT #PAD_B
    BEQ @move
    LDA #1
    STA f:M_BACK
  @end:
    JSR ows_sfxsel              ; the game's sound for a choice, B's too
    SEC
    RTS
  @move:
    JSR ms_dir
    CMP f:M_SEL
    BEQ @stay
    STA f:M_SEL
    CMP f:M_SHOWN
    BNE @load
    LDA #$FF                    ; back to the map on screen: none on its way
    STA f:M_LOAD
    BRA @chirp
  @load:
    STA f:M_LOAD                ; on its way, from its first piece
    REP #$20
    .a16
    LDA #0
    STA f:M_OFF
    SEP #$20
    .a8
  @chirp:
    JSR ows_sfxmove
  @stay:
    CLC
    RTS

;;  The selection presses A take it to: up and down a step, round from
;;  either end; left and right across, to the same row, or the right
;;  column's last when it is shorter.  A8 I16.
    .a8
    .i16
ms_dir:
    BIT #PAD_UP
    BEQ @down
    LDA f:M_SEL
    BNE :+
    LDA #MAPS_N
:   DEC A
    RTS
  @down:
    BIT #PAD_DOWN
    BEQ @across
    LDA f:M_SEL
    INC A
    CMP #MAPS_N
    BCC :+
    LDA #0
:   RTS
  @across:
    BIT #PAD_LEFT | PAD_RIGHT
    BEQ @same
    LDA f:M_SEL
    CMP #MAPS_ROWS
    BCC @toright
    SBC #MAPS_ROWS              ; (C set)
    RTS
  @toright:
    ADC #MAPS_ROWS              ; (C clear)
    CMP #MAPS_N
    BCC :+
    LDA #MAPS_N - 1
:   RTS
  @same:
    LDA f:M_SEL
    RTS


lut_MsTitle:
  FFTEXT "MAP"
  FFTEXT "SELECT"
