; ---------------------------------------------------------------------------
;  roll.asm -- New Game's roll screen.
;
;  While rando_newgame rolls the world -- placement, the entrance shuffle, the
;  cache -- the screen shows one of the game's map sprites scaled up eight
;  times, every pixel a character cell, walking in place, and the triangle
;  plays a little tune the roll itself writes: each stage its own scale, each
;  note a step of a walk the seed's draws choose, and a yelp from the first
;  pulse whenever a placement or a wiring is thrown away.  When the roll is
;  done the sprite goes on walking through the key item fanfare, fades, and
;  party creation follows (user, 2026-10-14).  The seed picks the sprite, from
;  every creature a map stands up and the twelve classes (tools/genroll.py).
;  Each drawn as the game draws it facing down -- a bat facing left, whose
;  frames flap.  One whose frames are the same hops instead; Garland and the
;  Vampire are on black; and the sleeping Elf Prince stands while the
;  backdrop breathes black to blue -- the fixed colour, added to a black
;  backdrop, being a register a tick may write mid-picture where CGRAM is
;  not.
;
;  Continue builds the cache the same way when it has to -- the first after
;  power-on (rando_coldbuild) -- the same seed, so the same sprite.
;
;  There are no interrupts in this port, and the randomizer has no frame
;  loop.  So the randomizer yields, often -- every draw, every ask the logic
;  makes (rando_yield) -- and a yield ticks this screen when a vblank has
;  begun since the last one, which RDNMI latches: a steady sixty a second for
;  as long as no stretch between yields runs past a frame.  A tick changes
;  only what is safe to change in the middle of a picture -- the brightness,
;  and the scroll, which is how the sprite steps: both frames are drawn side
;  by side in one 64x32 tilemap, and the step is BG1HOFS, 0 or 256 -- and
;  sends a frame of sound (hal_audioframe).  Nothing a tick does touches the
;  randomizer's memory but ROLL_*, and it reads the PRNG's state without
;  drawing, so the world rolled is the same with the screen up or not.
;
;  Like the credits screen, it takes the PPU from the HAL and gives it back
;  through hal_ppureclaim; VRAM is written by the CPU, not DMA, being small.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nescol.inc"

.export roll_begin, roll_tick, roll_end
;  For tools/test_options.py.
.export lut_RollChr, lut_RollPal, lut_RollPitch, lut_RollFx, roll_pick

.import CallMusicPlay
.import hal_vblaudio, hal_audioframe, hal_ppureclaim, hal_w400b

.segment "BANK_ROLL"

.include "roll.inc"

ROLL_MAP        = $1000         ; BG1's tilemap, 64x32: a frame in each half
ROLL_BG1SC      = (ROLL_MAP >> 8) | $01
ROLL_TOP        = 6             ; the picture's 16x16 cells, centred
ROLL_LEFT       = 8
ROLL_STEPTICKS  = 8             ; a step every eight frames
ROLL_NOTETICKS  = 6             ; a note every six...
ROLL_GATETICKS  = 4             ; ...sounding for four
ROLL_YELPTICKS  = 8
ROLL_YELPSTART  = $0040         ; the yelp's first period: high, then falling
ROLL_BACKDROP   = NESCOL_01     ; the game's window blue
FANFARE         = $54           ; the key item fanfare (DialogueBox_Sfx's)
MUSIC_DONE      = $81           ; music_track once a fanfare has finished
ROLLFX_WALK     = 0             ; lut_RollFx: the frames swap...
ROLLFX_HOP      = 1             ; ...it hops, having no second frame...
ROLLFX_THROB    = 2             ; ...or the backdrop throbs: COLDATA's channels
ROLLFX_SLOW     = 1             ;   in bits 7-5, and this for slow and dim
ROLLFX_BLACK    = $10           ; any of them on black
ROLL_HOPVOFS    = $003          ; BG1VOFS half a cell up from $3FF

;;  In emulation mode, by JSL from rando_newgame or rando_coldbuild, the seed
;;  in the save.  Out: the screen up, dark, fading in as it ticks; the music
;;  the title left already silenced (DisableAPU).
roll_begin:
    PHP
    PHB
    PHK
    PLB                         ; this chunk's low half is the I/O map
    SEP #$30
    ;  The top of a vblank to go dark at, so nothing of the title tears.
    JSL hal_vblaudio + HALFAR
    LDA #$80
    STA a:INIDISP
    STZ a:HDMAEN                ; the HAL's own channels: no flush comes now
    LDA #0
    LDX #ROLL_END - ROLL_T - 1
  @zero:
    STA f:ROLL_T, X
    DEX
    BPL @zero
    LDA #3
    STA f:ROLL_IDX              ; the walk starts mid-scale
    CLC
    XCE
    JSR roll_pick
    LDA f:ROLL_PICK
    TAX
    LDA lut_RollFx, X
    STA f:ROLL_FX
    JSR roll_build
    SEC
    XCE
    LDA #$01
    STA a:BGMODE                ; mode 1, BG1 alone
    STZ a:MOSAIC
    LDA #ROLL_BG1SC
    STA a:BG1SC
    STZ a:BG12NBA               ; its characters at VRAM 0
    LDA #$01
    STA a:TM
    STZ a:TS
    STZ a:TMW
    STZ a:TSW
    STZ a:W12SEL
    STZ a:CGWSEL                ; colour math everywhere, with the fixed colour
    LDA #$E0
    STA a:COLDATA               ; ...which is black, to start
    LDA f:ROLL_FX
    AND #ROLLFX_THROB
    BEQ :+
    LDA #$20                    ; a throb: added to the backdrop
:   STA a:CGADSUB
    STZ a:BG1HOFS
    STZ a:BG1HOFS
    LDA #$FF                    ; -1: the picture's first line is the tilemap's
    STA a:BG1VOFS
    LDA #$03
    STA a:BG1VOFS
    STZ a:INIDISP               ; on, at brightness 0
    LDA #1
    STA f:ROLL_ON
    PLB
    PLP
    RTL


;;  The seed's picture: its halves XORed, a sixteen-bit v, scaled to the
;;  choices -- (v * ROLL_SPRITES) >> 16, from two 8x8 products, the high
;;  byte's plus the carry out of the low byte's -- so each is 1724 or 1725 of
;;  the 65536.  (The four bytes summed in a byte, modulo the choices, gave
;;  the first 28 seven chances in 256 and the last ten six.)  Native, A8,
;;  DBR this chunk, whose low half is the I/O map.
SEEDFAR = RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
roll_pick:
    .a8
    LDA f:SEEDFAR
    EOR f:SEEDFAR + 2
    STA a:WRMPYA                ; v's low byte...
    LDA #ROLL_SPRITES
    STA a:WRMPYB                ; ...times the choices
    NOP
    NOP
    NOP
    NOP                         ; eight cycles
    LDA a:RDMPYH
    STA f:ROLL_PICK             ; what it carries
    LDA f:SEEDFAR + 1
    EOR f:SEEDFAR + 3
    STA a:WRMPYA                ; v's high byte...
    LDA #ROLL_SPRITES
    STA a:WRMPYB
    NOP
    NOP
    NOP
    NOP
    LDA a:RDMPYL
    CLC
    ADC f:ROLL_PICK             ; ...its product, the carry added...
    LDA a:RDMPYH
    ADC #0                      ; ...and the top byte the pick
    STA f:ROLL_PICK
    RTS


;;  VRAM and CGRAM for the picture.  Native, A8, in forced blank.
;;
;;  Characters 0-3 are solid colours 0-3, so a cell's character is its
;;  pixel's colour; the top half's cells take BG palette 1 and the legs' 2,
;;  as the sprite's halves take two sprite palettes.  Both frames, each in
;;  its half of the tilemap.
roll_build:
    .a8
    REP #$10
    .i16
    LDA #$80
    STA a:VMAIN                 ; a word: $2118, then $2119 and the step
    REP #$20
    .a16
    STZ a:VMADDL
    LDX #$0000
  @tiles:
    LDA lut_RollTiles, X
    STA a:VMDATAL
    INX
    INX
    CPX #4 * 32
    BCC @tiles

    LDA #ROLL_MAP
    STA a:VMADDL
    SEP #$20
    .a8
    LDA #0
    STA f:ROLL_FRAME
  @frame:
    LDY #$0000                  ; the tilemap row
  @row:
    TYA
    SEC
    SBC #ROLL_TOP
    CMP #16
    BCS @blankrow
    JSR roll_row                ; ROLL_BUF: the picture's row A, this frame
    REP #$20
    .a16
    LDX #ROLL_LEFT
  @lpad:
    STZ a:VMDATAL
    DEX
    BNE @lpad
  @cells:
    LDA f:ROLL_BUF, X
    STA a:VMDATAL
    INX
    INX
    CPX #32
    BCC @cells
    LDX #32 - ROLL_LEFT - 16
  @rpad:
    STZ a:VMDATAL
    DEX
    BNE @rpad
    SEP #$20
    .a8
    BRA @next
  @blankrow:
    REP #$20
    .a16
    LDX #32
  @blank:
    STZ a:VMDATAL
    DEX
    BNE @blank
    SEP #$20
    .a8
  @next:
    INY
    CPY #32
    BCC @row
    LDA f:ROLL_FRAME
    INC A
    STA f:ROLL_FRAME
    CMP #2
    BCC @frame
    LDA #0
    STA f:ROLL_FRAME            ; the first frame is the one shown

    ;  The colours: the backdrop -- black under a throb, which adds its colour,
    ;  or where asked -- then the halves' three each.
    STZ a:CGADD
    LDA f:ROLL_FX
    AND #ROLLFX_THROB | ROLLFX_BLACK
    BEQ :+
    STZ a:CGDATA
    STZ a:CGDATA
    BRA :++
:   LDA #<ROLL_BACKDROP
    STA a:CGDATA
    LDA #>ROLL_BACKDROP
    STA a:CGDATA
:
    REP #$20
    .a16
    LDA f:ROLL_PICK
    AND #$00FF
    STA f:ROLL_CGOFF            ; pick * 12, the colours' offset
    ASL A
    CLC
    ADC f:ROLL_CGOFF
    ASL A
    ASL A
    TAX
    SEP #$20
    .a8
    LDA #16 + 1
    JSR @three
    LDA #32 + 1
    JSR @three
    SEP #$10
    .i8
    RTS
  @three:
    .i16
    STA a:CGADD
    LDY #3
  @colour:
    LDA lut_RollPal, X
    STA a:CGDATA
    LDA lut_RollPal + 1, X
    STA a:CGDATA
    INX
    INX
    DEY
    BNE @colour
    RTS


;;  ROLL_BUF: row A (0-15) of the picture, in frame ROLL_FRAME, as tilemap
;;  words.  The frames are resolved already (tools/genroll.py): eight tiles a
;;  sprite, UL UR DL DR and again, mirrored as the game's table mirrors them.
;;  Native, A8, I16; Y kept.
roll_row:
    .a8
    .i16
    PHY
    STA f:ROLL_ROW
    ;  The palette: the top half's 1, the legs' 2, in the high byte's bits 2-4.
    CMP #8
    LDA #$04
    BCC :+
    LDA #$08
:   STA f:ROLL_PALHI
    LDY #$0000                  ; the half: 0 left, 1 right
  @half:
    ;  X = the pick's 128 bytes + (frame * 4 + the row's half * 2 + this half)
    ;  * 16 + the row within the tile.
    LDA f:ROLL_ROW
    AND #$08
    LSR A
    LSR A                       ; the bottom half: 2
    STA f:ROLL_OFF
    TYA
    ORA f:ROLL_OFF
    STA f:ROLL_OFF
    LDA f:ROLL_FRAME
    ASL A
    ASL A
    ORA f:ROLL_OFF              ; the tile, 0-7
    REP #$20
    .a16
    AND #$0007
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:ROLL_OFF
    LDA f:ROLL_PICK
    AND #$00FF
    XBA                         ; * 256...
    LSR A                       ; ...and back to * 128
    CLC
    ADC f:ROLL_OFF
    STA f:ROLL_OFF
    LDA f:ROLL_ROW
    AND #$0007
    CLC
    ADC f:ROLL_OFF
    TAX
    SEP #$20
    .a8
    LDA lut_RollChr, X          ; plane 0...
    STA f:ROLL_P0
    LDA lut_RollChr + 8, X      ; ...and plane 1
    STA f:ROLL_P1
    ;  Eight cells, left to right: the planes' high bits first.
    TYA
    ASL A
    ASL A
    ASL A
    ASL A                       ; the half's first word, in ROLL_BUF
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA #8
    STA f:ROLL_N
  @pixel:
    LDA f:ROLL_P1
    ASL A
    STA f:ROLL_P1
    LDA #0
    ROL A
    ASL A
    STA f:ROLL_HI
    LDA f:ROLL_P0
    ASL A
    STA f:ROLL_P0
    LDA #0
    ROL A                       ; plane 0's bit, from the carry
    ORA f:ROLL_HI               ; ...and plane 1's above it: the colour
    STA f:ROLL_BUF, X           ; its character, the colour itself...
    BEQ @clear
    LDA f:ROLL_PALHI            ; ...and the half's palette
  @clear:
    STA f:ROLL_BUF + 1, X       ; (colour 0: the backdrop, a blank cell)
    INX
    INX
    LDA f:ROLL_N
    DEC A
    STA f:ROLL_N
    BNE @pixel
    INY
    CPY #2
    BCS :+
    JMP @half
:   PLY
    RTS


;;  Characters 0-3: solid colours 0-3, 4bpp.  Words 0-7 are planes 0 and 1
;;  of each line, 8-15 planes 2 and 3.
lut_RollTiles:
  .repeat 16
    .word $0000
  .endrep
  .repeat 8
    .word $00FF
  .endrep
  .repeat 8
    .word $0000
  .endrep
  .repeat 8
    .word $FF00
  .endrep
  .repeat 8
    .word $0000
  .endrep
  .repeat 8
    .word $FFFF
  .endrep
  .repeat 8
    .word $0000
  .endrep


;;  One tick: from rando_yield, by JSL, when the screen is up and a vblank has
;;  begun since the last.  Any mode and widths; everything kept.
roll_tick:
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
    JSR roll_frame
    JSR roll_sound
    SEC
    XCE                         ; the HAL wants emulation mode
    JSL hal_audioframe + HALFAR
    CLC
    XCE
    REP #$30
    PLD
    PLB
    PLY
    PLX
    PLA
    PLP
    RTL


;;  The picture's frame: a little brighter, until full; and its effect --
;;  every ROLL_STEPTICKS a step, the other half of the tilemap, or a hop; or
;;  the throb, a triangle wave of the fixed colour.  Only registers, which a
;;  tick may write mid-picture.  A8 X8, either mode, DBR this chunk.
roll_frame:
    .a8
    LDA f:ROLL_T
    INC A
    STA f:ROLL_T
    LDA f:ROLL_BRIGHT
    CMP #15
    BCS :+
    INC A
    STA f:ROLL_BRIGHT
    STA a:INIDISP
:   LDA f:ROLL_FX
    AND #ROLLFX_THROB
    BNE @throb
    LDA f:ROLL_T
    AND #ROLL_STEPTICKS - 1
    BNE @out
    LDA f:ROLL_FRAME
    EOR #1
    STA f:ROLL_FRAME
    TAX
    LDA f:ROLL_FX
    AND #ROLLFX_HOP
    BNE @hop
    STZ a:BG1HOFS               ; low, then high: 0 or 256
    STX a:BG1HOFS
  @out:
    RTS
  @hop:
    LDA #<$3FF                  ; down, or half a cell up
    LDY #>$3FF
    CPX #0
    BEQ :+
    LDA #<ROLL_HOPVOFS
    LDY #>ROLL_HOPVOFS
:   STA a:BG1VOFS
    STY a:BG1VOFS
    RTS
  @throb:
    LDA f:ROLL_FX
    AND #ROLLFX_SLOW
    TAX
    LDA f:ROLL_T
    CPX #0
    BEQ :+
    LSR A                       ; slow: half the speed...
:   AND #63
    CMP #32
    BCC :+
    EOR #63                     ; 32..63 -> 31..0: up, then down
:   CPX #0
    BEQ :+
    LSR A                       ; ...and half as bright
:   STA f:ROLL_HI
    LDA #$E0
    STA a:COLDATA               ; every channel to zero...
    LDA f:ROLL_FX
    AND #$E0
    ORA f:ROLL_HI
    STA a:COLDATA               ; ...then the throb's to the wave
    RTS


;;  The tick's sound, into the APU's shadow: the yelp on the first pulse, and
;;  the triangle's tune.  Native, A8 I8, DBR this chunk.
roll_sound:
    .a8
    .i8
    LDA f:ROLL_YREQ
    BEQ @noreq
    LDA #0
    STA f:ROLL_YREQ
    LDA #ROLL_YELPTICKS
    STA f:ROLL_YELP
    LDA #<ROLL_YELPSTART
    STA f:ROLL_YPER
    LDA #>ROLL_YELPSTART
    STA f:ROLL_YPER + 1
  @noreq:
    LDA f:ROLL_YELP
    BEQ @gate
    DEC A
    STA f:ROLL_YELP
    BNE :+
    LDA a:APUSHADOW + $15       ; done: the first pulse off
    AND #$FE
    STA a:APUSHADOW + $15
    BRA @gate
:   ASL A                       ; louder the earlier: 14 down to 2
    ORA #$70                    ; a quarter duty, held, constant volume
    STA a:APUSHADOW + 0
    LDA #$08
    STA a:APUSHADOW + 1         ; no sweep: the tick falls it
    LDA f:ROLL_YPER
    STA a:APUSHADOW + 2
    LDA f:ROLL_YPER + 1
    STA a:APUSHADOW + 3
    REP #$20
    .a16
    LDA f:ROLL_YPER             ; a quarter longer each tick: the pitch falls
    LSR A
    LSR A
    CLC
    ADC f:ROLL_YPER
    STA f:ROLL_YPER
    SEP #$20
    .a8
    LDA a:APUSHADOW + $15
    ORA #$01
    STA a:APUSHADOW + $15

  @gate:
    LDA f:ROLL_GATE
    BEQ @next
    DEC A
    STA f:ROLL_GATE
    BNE @next
    LDA a:APUSHADOW + $15       ; the note's end: a key-off, so the next is
    AND #$FB                    ;   a key-on of its own
    STA a:APUSHADOW + $15
  @next:
    LDA f:ROLL_NEXT
    BEQ @note
    DEC A
    STA f:ROLL_NEXT
    RTS
  @note:
    LDA #ROLL_NOTETICKS
    STA f:ROLL_NEXT
    LDA #ROLL_GATETICKS
    STA f:ROLL_GATE
    ;  A step of the walk, two of the PRNG's state's bits choosing it -- so
    ;  the tune is the roll's own -- reflected back inside the scale.
    LDA f:RW_RNG
    AND #$03
    TAX
    LDA f:ROLL_IDX
    CLC
    ADC lut_RollWalk, X
    BPL :+
    EOR #$FF                    ; -1 -> 0, -2 -> 1
:   CMP #8
    BCC :+
    EOR #$FF                    ; 8 -> 7 ($F7 + 16), 9 -> 6
    CLC
    ADC #16
:   STA f:ROLL_IDX
    LDA f:ROLL_STAGE
    AND #$03
    ASL A
    ASL A
    ASL A
    ORA f:ROLL_IDX
    ASL A
    TAX
    LDA #$FF                    ; the linear counter held open: the gate is
    STA a:APUSHADOW + 8         ;   $4015's bit
    LDA lut_RollPitch, X
    STA a:APUSHADOW + $0A
    LDA lut_RollPitch + 1, X
    SEC
    XCE
    JSL hal_w400b + HALFAR      ; the timer's top, and the counter's reload
    CLC
    XCE
    LDA a:APUSHADOW + $15
    ORA #$04
    STA a:APUSHADOW + $15
    RTS

lut_RollWalk:
  .byte <-2, <-1, 1, 2

;;  Each stage's scale, as triangle periods (1789773 / (32 f) - 1), low to
;;  high: ROLLSTAGE_PLACE whole-tone D4-E5, _WIRING C major pentatonic C5-E6,
;;  _LOGIC A minor pentatonic A3-D5, _BUILD a G major arpeggio G4-B6.
lut_RollPitch:
  .word $0BD, $0A9, $096, $086, $077, $06A, $05E, $054
  .word $06A, $05E, $054, $046, $03F, $034, $02F, $029
  .word $0FD, $0D5, $0BD, $0A9, $08E, $07E, $06A, $05E
  .word $08E, $070, $05E, $046, $038, $02F, $023, $01B


;;  In emulation mode, by JSL from rando_newgame or rando_coldbuild, the
;;  world rolled; A = the track to start after, or 0 for none.  The sprite
;;  walks on through the key item fanfare -- also the screen's least time up,
;;  however quick the roll -- then fades; the track starts, and the PPU goes
;;  back to the HAL, dark.
roll_end:
    PHP
    PHB
    PHK
    PLB
    SEP #$30
    STA f:ROLL_AFTER
    LDA #0
    STA f:ROLL_ON               ; no more ticks: the frames are this loop's
    LDA #FANFARE
    STA music_track             ; the driver halts the tune's channels
  @fanfare:
    JSR roll_wait
    JSR roll_frame
    LDA music_track
    CMP #MUSIC_DONE
    BNE @fanfare
  @fade:
    JSR roll_wait
    LDA f:ROLL_BRIGHT
    BEQ @dark
    DEC A
    STA f:ROLL_BRIGHT
    STA a:INIDISP
    BRA @fade
  @dark:
    LDA #$80
    STA a:INIDISP
    STZ a:CGADSUB               ; the throb's colour math off again
    LDA f:ROLL_AFTER
    BEQ :+
    STA music_track
:
    JSL hal_ppureclaim + HALFAR
    PLB
    PLP
    RTL

;;  A frame of the game's music driver, then the top of the next vblank.
;;  cur_bank is where CallMusicPlay swaps back to.  Emulation mode.
roll_wait:
    LDA #CHUNK_ROLL
    STA cur_bank
    JSR CallMusicPlay
    JSL hal_vblaudio + HALFAR
    RTS
