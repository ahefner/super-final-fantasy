;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  hal.asm -- the NES hardware the SNES has to pretend to be.
;;
;;  The game's 6502 code is unmodified apart from its hardware accesses, which
;;  convert.py has turned into calls into this file.  Everything here runs from
;;  ROM bank $C0 and is reached with JSL, so it is callable from any of the
;;  sixteen chunk banks the game code executes in.
;;
;;  Two invariants make the rest of it simple:
;;
;;   * The game runs in 65816 *emulation* mode.  It is a 6502 in every way that
;;     matters -- 8-bit registers, page-1 stack, zero page at $0000 -- so the
;;     TSX/TXS stack surgery in the magic menu and everything else works as
;;     written.  Routines here that need 16-bit registers flip to native mode
;;     and back around their own bodies.
;;
;;   * DBR always names a bank in $81..$90.  Every one of those exposes the
;;     standard low-bank map, so WRAM ($0000-$1FFF), the PPU ($2100), the CPU
;;     registers ($4200) and the NES's PRG-RAM (SRAM at $6000-$7FFF) are all
;;     reachable with plain absolute addressing from in here.  Only the big
;;     shadow buffers up at $7E:2000 and beyond need long addressing.
;;
;;  The write entry points are completely transparent -- A, X, Y and P come
;;  back untouched -- and the read entry points behave exactly like the load
;;  they replaced, which they manage by restoring the other registers *first*
;;  and letting the final load set N and Z.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.p816
.include "snesmap.inc"

.export hal_reset
.export hal_w2000, hal_w2001, hal_r2002, hal_r2002x, hal_r2002y, hal_b2002
.export hal_w2005, hal_w2006, hal_w2007, hal_r2007
.export hal_oamdma, hal_joystrobe, hal_joyread, hal_r4015
.export hal_swapprg, hal_waitvbl, hal_joyupdate, hal_waitscanline
.export hal_waitline9

.import OnReset

;; Flip to native mode with 16-bit registers, and back again.
.macro ENTER16
    clc
    xce
    rep #$30
    .a16
    .i16
.endmacro

.macro LEAVE16
    sep #$30
    .a8
    .i8
    sec
    xce
.endmacro

;;  Paint the backdrop a fixed 15-bit BGR colour, force the display on and
;;  stop.  Inline 8-bit code only: a checkpoint has to be usable before the
;;  stack pointer or the register widths can be trusted.  Build with
;;  -D DIAG_STOP=n to stop at checkpoint n.
.macro DIAG_CHECKPOINT n, bgr
  .ifdef DIAG_STOP
    .if DIAG_STOP = n
      lda #$0F
      sta a:INIDISP
      stz a:CGADD
      lda #<(bgr)
      sta a:CGDATA
      lda #>(bgr)
      sta a:CGDATA
    : jmp :-
    .endif
  .endif
.endmacro


;;  Paint the backdrop and stop, from 16-bit code.  Same idea as
;;  DIAG_CHECKPOINT, but usable inside the flush where A is 16 bits wide.
.macro DIAG16 bgr
    sep #$20
    .a8
    stz a:HDMAEN
    stz a:TM                    ; backdrop only: nothing may mask the colour
    lda #$0F
    sta a:INIDISP
    stz a:CGADD
    lda #<(bgr)
    sta a:CGDATA
    lda #>(bgr)
    sta a:CGDATA
:   bra :-
    rep #$20
    .a16
.endmacro

.segment "HALCODE"
.a8
.i8

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  $2000 PPUCTRL / $2001 PPUMASK
;;
;;  Nothing to do but remember them.  Bit 2 of $2000 picks the $2007 address
;;  stride, bits 0-1 are the coarse scroll, and $2001 says whether rendering is
;;  on; all three are consulted later, by the code that actually needs them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

hal_w2000:
    php
    pha
    phx
    ldx a:h_ppuctrl
    stx a:h_prevctrl
    sta a:h_ppuctrl

    ;  The first $2000 write of a frame is that frame's own setting, not a
    ;  raster effect: the map code writes it once per frame while scrolling,
    ;  and the flush eats enough of vblank that the write frequently lands
    ;  after the display has already started.  Treating those as splits made
    ;  the wrong nametable flicker in for a frame whenever the party moved.
    ;  Only a *second* write within the same frame is a real mid-frame switch
    ;  -- which is exactly what the dialogue box does, setting the box's
    ;  nametable in vblank and restoring the map's part-way down the screen.
    ;  Counting writes per frame was too weak a test.  A split is only ever
    ;  genuine inside the dialogue box's own raster window, which hal_waitline9
    ;  opens and the flush closes -- nothing else in the game deliberately
    ;  changes nametable part-way down a frame.  Everything else is that
    ;  frame's setting, however late it happens to land.
    lda a:h_rasterwin
    bne @split
      lda a:h_ppuctrl           ; frame setting: what the frame opens on
      jsr hofs_from_ctrl
      lda a:h_t0
      sta a:h_hofsframestart
      lda a:h_t1
      sta a:h_hofsframestart+1
      bra @done
@split:
    lda a:h_ppumask
    and #$18                    ; is anything actually being displayed?
    beq @done
    lda a:HVBJOY
    bmi @done                   ; a vblank write is still just a setting
    ldx a:h_ntsplits
    cpx #8
    bcs @done
    lda a:STAT78
    lda a:SLHV
    lda a:OPVCT
    ;  The game counts in NES scanlines, and we crop NES_TOP_CROP off the top,
    ;  so the line it has just reached sits that much higher on screen.  Correct
    ;  it here rather than by moving the wait target: waiting on an earlier line
    ;  risks polling for one already gone by, since the flush can eat enough of
    ;  vblank to overshoot it, and missing costs a whole frame.
    sec
    sbc #NES_TOP_CROP
    bcs :+
      lda #0
:   sta a:NTSPLITLINE,x
    lda a:h_ppuctrl
    jsr hofs_from_ctrl
    lda a:h_t0
    sta a:NTSPLITLO,x
    lda a:h_t1
    sta a:NTSPLITHI,x
    inx
    stx a:h_ntsplits
@done:
    plx
    pla
    plp
    rtl

;;  The nametable select bit is worth exactly 256 pixels of horizontal scroll,
;;  so it lands in the high byte and the fine scroll in the low one.
hofs_from_ctrl:                 ; A = $2000 -> h_t0/h_t1
    and #$01
    sta a:h_t1
    lda a:h_scrollx
    sta a:h_t0
    rts

;;  Wait until the beam reaches scanline 9.  See the dialogue box patch.
hal_waitline9:
    php
    pha
@wait:
    lda a:STAT78
    lda a:SLHV
    lda a:OPVCT
    cmp #9
    bne @wait
    lda #1
    sta a:h_rasterwin           ; from here to the flush, splits are expected
    pla
    plp
    rtl

hal_w2001:
    php
    pha
    phx
    ldx a:h_ppumask
    stx a:h_prevmask            ; what was actually on screen until now
    sta a:h_ppumask
    lsr a                       ; bits 7-5 emphasise red, green and blue
    lsr a
    lsr a
    lsr a
    lsr a
    and #$07
    cmp a:h_emphasis
    beq :+
      sta a:h_emphasis
      lda #1
      sta a:h_paldirty          ; the whole palette has to be re-tinted
      sta a:h_palforce
:   lda a:h_ppumask
    and #$01                    ; bit 0 is the greyscale switch
    cmp a:h_greyscale
    beq :+
      sta a:h_greyscale
      lda #1
      sta a:h_paldirty
      sta a:h_palforce

    ;  A write during active display is a raster split -- the game is carving
    ;  the screen into bands, which is how the map transitions wipe open and
    ;  shut.  Record the scanline it happened on; the flush turns the list into
    ;  an HDMA table.  A write during vblank is just this frame's setting.
    ;  Keep the current layer setting up to date on *every* write, whatever
    ;  kind of write it is.  Refreshing it only during vblank left it stale for
    ;  any code that reconfigures $2001 mid-frame -- which is exactly what
    ;  battle set-up does when it turns the sprites back on after the fade-in,
    ;  so the party and the menu cursor never reappeared.
:   lda a:h_ppumask
    jsr tm_from_mask
    sta a:h_tmcur

    ;  A write while the display is actually live is a raster split.  Writes
    ;  made with rendering off are just setup and must not reach the table.
.if ENABLE_RASTER_SPLITS
    lda a:h_prevmask
    and #$18
    beq @done
    lda a:HVBJOY
    bmi @done
    ldx a:h_rastercount
    cpx #16
    bcs @done                   ; more splits than budgeted; drop the rest
    lda a:STAT78                ; reset the counter read toggle
    lda a:SLHV                  ; latch H and V
    lda a:OPVCT                 ; ...and read the scanline
    sta a:RASTERLINE,x
    lda a:h_tmcur
    sta a:RASTERTM,x
    inx
    stx a:h_rastercount
.endif
@done:
    plx
    pla
    plp
    rtl

;;  NES $2001 bit 3 shows the background and bit 4 the sprites.  TM says the
;;  same thing with bit 0 (BG1) and bit 4 (OBJ).
tm_from_mask:                   ; A = $2001 -> A = TM
    sta a:h_t1
    stz a:h_t0
    and #$08
    beq :+
      lda #$01
      sta a:h_t0
:   lda a:h_t1
    and #$10
    beq :+
      lda a:h_t0
      ora #$10
      sta a:h_t0
:   lda a:h_t0
    rts

;;  Wait for the vertical counter to move on by one line.
hal_waitscanline:
    php
    pha
    phx
    lda a:STAT78
    lda a:SLHV
    lda a:OPVCT
    sta a:h_t0
@wait:
    lda a:STAT78
    lda a:SLHV
    lda a:OPVCT
    cmp a:h_t0
    beq @wait
    plx
    pla
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  $2002 PPUSTATUS
;;
;;  Bit 7 is vblank, which $4212 tells us directly.  Bit 6 is the sprite-0 hit;
;;  the SNES has no such thing, so it comes from h_spr0hit (see the raster
;;  effects).  Reading also resets the $2005/$2006 write toggle.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

status2002:                     ; -> A, clobbers nothing else
    stz a:h_latch
    lda a:HVBJOY
    and #$80
    ora a:h_spr0hit
    rts

hal_r2002:
    jsr status2002              ; leaves the value in A with N/Z set from it
    rtl

hal_r2002x:
    sta a:h_t2                  ; STA touches no flags, so A survives intact
    jsr status2002
    sta a:h_t0
    lda a:h_t2                  ; put A back...
    ldx a:h_t0                  ; ...then load X last, so X sets the flags
    rtl

hal_r2002y:
    sta a:h_t2
    jsr status2002
    sta a:h_t0
    lda a:h_t2
    ldy a:h_t0
    rtl

hal_b2002:
    sta a:h_t2
    jsr status2002
    sta a:h_t0
    lda a:h_t2
    bit a:h_t0                  ; a real BIT: N, V and Z exactly as before
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  $2005 PPUSCROLL and $2006 PPUADDR
;;
;;  Both share one first/second-write toggle, which a read of $2002 clears.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

hal_w2005:
    php
    sta a:h_data
    pha
    lda a:h_latch
    bne @second
      lda a:h_data
      sta a:h_scrollx
      lda #1
      sta a:h_latch
      bra @done
@second:
      lda a:h_data
      sta a:h_scrolly
      stz a:h_latch
@done:
    pla
    plp
    rtl

hal_w2006:
    php
    sta a:h_data
    pha
    lda a:h_latch
    bne @low
      lda a:h_data
      and #$3F                  ; the PPU address bus is only 14 bits wide
      sta a:h_addr+1
  .ifdef PROBE_HI
      inc a:h_hicount
      cmp a:h_himin
      bcs @nomin
        sta a:h_himin
@nomin:
      cmp a:h_himax
      bcc @nomax
        sta a:h_himax
@nomax:
  .endif
      lda #1
      sta a:h_latch
      bra @done
@low:
      lda a:h_data
      sta a:h_addr
      stz a:h_latch
@done:
    pla
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  $2007 PPUDATA -- the write path
;;
;;  This is where NES video actually becomes SNES video.  Rather than keeping
;;  the NES's own VRAM around and converting it later, each byte is filed
;;  straight into a shadow that is already in the SNES's format and ready to
;;  DMA: pattern bytes get permuted into 4bpp planar order, nametable bytes
;;  become the low half of a tilemap word, attribute bytes rewrite the high
;;  half of the sixteen tilemap words they cover, and palette bytes go into a
;;  copy that the next flush turns into CGRAM.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

hal_w2007:
    php
    sta a:h_data
    pha
    phx
    phy
    ENTER16
    jsr w2007_core
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

.a16
.i16
w2007_core:
    lda a:h_addr
    and #$3FFF
    sta a:h_t0
    cmp #$2000
    bcc chr_write
    cmp #$3F00
    bcc nt_write
    jmp pal_write

; --- pattern table ------------------------------------------------------
chr_write:
    and #$000F                  ; which byte of the tile?
    asl a                       ;   plane 0 rows land on even offsets...
    sta a:h_t1
    and #$0010                  ;   ...and plane 1 rows (i >= 8) on odd ones
    beq :+
      lda a:h_t1
      sec
      sbc #15
      sta a:h_t1
:   lda a:h_t0
    and #$1FF0                  ; tile number * 16
    asl a                       ; 4bpp tiles are 32 bytes, not 16
    ora a:h_t1
    tax
    sep #$20
    .a8
    lda a:h_data
    sta f:CHRSHADOW,x
    rep #$20
    .a16
    txa                         ; widen the dirty range
    cmp a:h_chrlo
    bcs :+
      sta a:h_chrlo
:   txa
    cmp a:h_chrhi
    bcc :+
      sta a:h_chrhi
:   jmp bump_addr

; --- nametable ----------------------------------------------------------
nt_write:
    ;  Final Fantasy sets the MMC1 to vertical mirroring, so the two physical
    ;  nametables sit side by side: $2000 is the left screen and $2400 the
    ;  right, and the PPU address wraps every $800.
    lda a:h_t0
    and #$07FF
    sta a:h_t1
    tax
    sep #$20
    .a8
    lda a:h_data
    sta f:NESNT,x               ; keep the raw bytes for readback and attributes
    rep #$20
    .a16
    lda a:h_t1
    and #$03FF
    cmp #$03C0
    bcs nt_attr

    ; a tile: work out its row and column on the 64-wide SNES tilemap
    sta a:h_t2
    and #$001F
    sta a:h_col
    lda a:h_t2
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta a:h_row                 ; 0..29
    lda a:h_t1
    and #$0400                  ; right-hand nametable?
    beq :+
      lda a:h_col
      clc
      adc #32
      sta a:h_col
:   lda a:h_row                 ; offset = row*128 + col*2
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta a:h_t2
    lda a:h_col
    asl a
    clc
    adc a:h_t2
    tax
    sep #$20
    .a8
    lda a:h_data
    sta a:NTSHADOW,x            ; low byte of the tilemap word is the tile
    rep #$20
    .a16
    jsr mark_dirty
    jmp bump_addr

; --- attribute table ----------------------------------------------------
;  One NES attribute byte is four 2-bit palette numbers, one per 2x2 block of
;  tiles, covering a 4x4 block in all.  The SNES keeps the palette number in
;  the high byte of every tilemap word, so a single attribute write has to be
;  smeared across sixteen of them.
nt_attr:
    sec
    sbc #$03C0
    sta a:h_t2                  ; attribute index, 0..63
    sep #$20
    .a8
    lda a:h_data                ; unpack the four palette numbers up front
    and #$03
    asl a
    asl a
    sta a:h_pal+0
    lda a:h_data
    lsr a
    lsr a
    and #$03
    asl a
    asl a
    sta a:h_pal+1
    lda a:h_data
    lsr a
    lsr a
    lsr a
    lsr a
    and #$03
    asl a
    asl a
    sta a:h_pal+2
    lda a:h_data
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #$03
    asl a
    asl a
    sta a:h_pal+3
    rep #$20
    .a16
    lda a:h_t2                  ; top-left tile of the 4x4 block
    lsr a
    lsr a
    lsr a
    asl a
    asl a
    sta a:h_t3                  ; base row
    lda a:h_t2
    and #$0007
    asl a
    asl a
    sta a:h_t4                  ; base column
    lda a:h_t1
    and #$0400
    beq :+
      lda a:h_t4
      clc
      adc #32
      sta a:h_t4
:
    ;  dy and dx live in memory rather than in X and Y, because the body of the
    ;  loop needs both index registers for the shadow it is writing.
    stz a:h_t2                  ; h_t2 = dy
@rowloop:
    lda a:h_t2
    clc
    adc a:h_t3
    sta a:h_row
    cmp #30                     ; the last attribute row covers only two rows
    bcs @nextrow
    stz a:h_t0                  ; h_t0 = dx
@colloop:
    lda a:h_t0
    clc
    adc a:h_t4
    sta a:h_col
    ; quadrant = (dy & 2) + (dx & 2)/2
    lda a:h_t2
    and #$0002
    sta a:h_t5
    lda a:h_t0
    and #$0002
    lsr a
    clc
    adc a:h_t5
    tax
    sep #$20
    .a8
    lda a:h_pal,x               ; the palette this quarter of the block uses
    sta a:h_t5
    rep #$20
    .a16
    ; tilemap byte offset = row*128 + col*2, +1 to reach the high byte
    lda a:h_row
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta a:h_t1
    lda a:h_col
    asl a
    clc
    adc a:h_t1
    inc a
    tax
    sep #$20
    .a8
    lda a:h_t5
    sta a:NTSHADOW,x
    rep #$20
    .a16
    jsr mark_dirty
    lda a:h_t0
    inc a
    sta a:h_t0
    cmp #4
    bcc @colloop
@nextrow:
    lda a:h_t2
    inc a
    sta a:h_t2
    cmp #4
    bcc @rowloop
    jmp bump_addr

; --- palette ------------------------------------------------------------
pal_write:
  .ifdef PROBE_PAL
    sep #$20
    .a8
    inc a:h_palwrites           ; how many writes landed in palette space
    rep #$20
    .a16
  .endif
    lda a:h_t0
    and #$001F
    sta a:h_t1
    and #$0003                  ; $3F10/$14/$18/$1C are mirrors of $3F00/...
    bne :+
      lda a:h_t1
      and #$000F
      sta a:h_t1
:   ldx a:h_t1
    sep #$20
    .a8
    lda a:h_data
    and #$3F
    sta f:NESPAL,x
    lda #1
    sta a:h_paldirty
    rep #$20
    .a16
    jmp bump_addr

; --- shared tail --------------------------------------------------------
;  h_row/h_col name the tilemap cell that just changed; widen that row's dirty
;  column span.  A per-row span is the right granularity here because the game
;  updates the screen a row or a column at a time as the map scrolls, and a
;  single-column update must not cost a full-screen transfer.
mark_dirty:
    ldx a:h_row
    sep #$20
    .a8
    lda a:h_col
    cmp a:NTCOLLO,x
    bcs :+
      sta a:NTCOLLO,x
:   lda a:h_col
    cmp a:NTCOLHI,x
    bcc :+
      sta a:NTCOLHI,x
:   lda #1
    sta a:h_ntdirty
    rep #$20
    .a16
    rts

bump_addr:
    sep #$20
    .a8
    lda a:h_ppuctrl
    and #$04                    ; stride: down a column, or along a row?
    beq @by1
    rep #$20
    .a16
    lda a:h_addr
    clc
    adc #32
    bra @store
@by1:
    rep #$20
    .a16
    lda a:h_addr
    inc a
@store:
    sta a:h_addr
    rts

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  $2007 PPUDATA -- the read path
;;
;;  Reads below $3F00 come back one byte late, through the PPU's read buffer.
;;  The game relies on that, so it is modelled here rather than papered over.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_r2007:
    php
    phx
    phy
    ENTER16
    jsr r2007_core
    LEAVE16
    ply
    plx
    plp
    lda a:h_t2                  ; last, so the load sets N and Z
    rtl

.a16
.i16
r2007_core:
    lda a:h_addr
    and #$3FFF
    sta a:h_t0
    cmp #$3F00
    bcs @palette

    sep #$20
    .a8
    lda a:h_readbuf             ; the buffered byte is what the read returns
    sta a:h_t2
    rep #$20
    .a16
    lda a:h_t0
    cmp #$2000
    bcc @chr
    and #$07FF
    tax
    sep #$20
    .a8
    lda f:NESNT,x
    sta a:h_readbuf
    rep #$20
    .a16
    jmp bump_addr
@chr:
    ;  Pattern reads come back through the same permutation the writes used --
    ;  every NES byte lives at exactly one place in the 4bpp shadow, so the
    ;  address arithmetic is identical, only the direction differs.
    lda a:h_t0
    and #$000F
    asl a
    sta a:h_t1
    and #$0010
    beq :+
      lda a:h_t1
      sec
      sbc #15
      sta a:h_t1
:   lda a:h_t0
    and #$1FF0
    asl a
    ora a:h_t1
    tax
    sep #$20
    .a8
    lda f:CHRSHADOW,x
    sta a:h_readbuf
    rep #$20
    .a16
    jmp bump_addr

@palette:
    and #$001F
    sta a:h_t1
    and #$0003
    bne :+
      lda a:h_t1
      and #$000F
      sta a:h_t1
:   ldx a:h_t1
    sep #$20
    .a8
    lda f:NESPAL,x              ; palette reads are immediate, not buffered
    sta a:h_t2
    rep #$20
    .a16
    jmp bump_addr

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  $4014 OAM DMA
;;
;;  The game builds a 64-entry NES sprite table in RAM and hands the page to
;;  the PPU.  Here that becomes a translation into the SNES's own OAM layout,
;;  staged in WRAM; the real DMA happens during the next flush.  Final Fantasy
;;  never enables 8x16 sprites, so every entry is a single 8x8 SNES sprite and
;;  the two tables line up one for one.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_oamdma:
    php
    sta a:h_data
    pha
    phx
    phy
    lda a:h_ppuctrl             ; which pattern table are sprites using?
    and #$08
    beq :+
      lda #$01
:   and #$01
    sta a:h_sprtable            ; ...that is the 9th bit of the SNES tile number
    ENTER16
    lda a:h_data
    and #$00FF
    xba                         ; the DMA operand is a page number
    tax                         ; X walks the NES table
    ldy #0                      ; Y walks the SNES table
@loop:
    sep #$20
    .a8
    lda a:$0001,x               ; tile number
    sta a:OAMSHADOW+2,y
    lda a:$0003,x               ; X position (0-255, so the 9th bit stays clear)
    sta a:OAMSHADOW+0,y
    lda a:$0000,x               ; The NES draws a sprite one line below the
    sec                         ; value in OAM; the SNES does not.  Take off the
    sbc #(NES_TOP_CROP - 1)     ; cropped lines too, so sprites stay with the
    sta a:OAMSHADOW+1,y         ; background.  Anything that goes negative wraps
                                ; below the screen, which is where it belonged.
    lda a:$0002,x               ; attributes
    sta a:h_t0
    and #$C0                    ; the flip bits are in the same places
    sta a:h_t1
    lda a:h_t0
    and #$03                    ; palette: NES bits 1-0 -> SNES bits 3-1
    asl a
    ora a:h_t1
    ora a:h_sprtable
    sta a:h_t1
    lda a:h_t0
    and #$20                    ; "behind background"
    beq @front
      lda a:h_t1
      ora #$10                  ; OBJ priority 1: under BG1, over the backdrop
      bra @stattr
@front:
      lda a:h_t1
      ora #$20                  ; OBJ priority 2: over BG1
@stattr:
    sta a:OAMSHADOW+3,y
    rep #$20
    .a16
    inx
    inx
    inx
    inx
    iny
    iny
    iny
    iny
    cpy #256
    bcc @loop
    LEAVE16
    lda #1
    sta a:h_oamdirty
    ply
    plx
    pla
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Controller
;;
;;  The SNES latches the pad for us once a frame.  readpad_nes reshuffles it
;;  into the bit order the NES's shift register produced, which is what the
;;  rest of the game indexes on:
;;
;;      bit 7 6 5      4     3  2    1    0
;;          A B Select Start Up Down Left Right
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

NES_joy = $20                   ; 'joy' in variables.inc

readpad_nes:                    ; -> A
@wait:
    lda a:HVBJOY
    and #$01                    ; don't read mid auto-latch
    bne @wait
    lda a:JOY1L
    and #$80                    ; SNES A -> NES A, already in place
    sta a:h_t0
    lda a:JOY1H
    and #$80                    ; SNES B is a bit higher than the NES's
    lsr a
    ora a:h_t0
    sta a:h_t0
    lda a:JOY1H
    and #$3F                    ; Select, Start and the d-pad already line up
    ora a:h_t0
    rts

hal_joyupdate:
    php
    jsr readpad_nes
    sta a:NES_joy
    ldx #0                      ; the routine this replaces documented X = 0
    plp
    rtl

;;  The raw port is still emulated, for the few readers that drive it directly.
hal_joystrobe:
    php
    pha
    and #$01
    beq @done
      jsr readpad_nes
      sta a:h_joyshift
@done:
    pla
    plp
    rtl

hal_joyread:
    lda a:h_joyshift
    asl a                       ; the NES reports one button per read, MSB first
    sta a:h_joyshift
    lda #0
    rol a
    rtl

;;  $4015 reads back which length counters are still running.  Nothing is
;;  running yet, and the music driver only ever uses this to poll for a channel
;;  going idle, so zero is the honest answer until the SPC700 driver lands.
hal_r4015:
    lda #0
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Bank switching
;;
;;  Reached by JML from SwapPRG, with the caller's 16-bit return address still
;;  on the stack.  ROM chunk CHUNK0+A holds NES bank A at $8000-$BFFF and the
;;  fixed bank at $C000-$FFFF, so "swapping" is done by returning into a
;;  different program bank.  DBR follows PBR, because the game reads its data
;;  tables out of the bank it just selected using plain absolute addressing.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

hal_swapprg:
    sta a:h_curbank
    clc
    adc #CHUNK0
    sta a:h_t0
    ENTER16
    pla                         ; the address JSR left for us
    sta a:h_t1
    sep #$20
    .a8
    lda a:h_t0
    pha                         ; RTL pulls the address first, then the bank,
    rep #$20                    ;   so the bank has to go down first
    .a16
    lda a:h_t1
    pha
    LEAVE16
    lda a:h_t0
    pha
    plb                         ; DBR = the bank we are about to run in
    lda #0                      ; the MMC1 sequence left A = 0; so do we
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Frame sync and flush
;;
;;  The game's WaitForVBlank comes here.  Everything it drew since the last
;;  call is sitting in WRAM already in SNES format; this is where it reaches
;;  the hardware.  The transfers run under forced blank, so an update too large
;;  for one vblank costs a black frame instead of a torn one -- which is what
;;  the NES version looked like anyway, since it did its big loads with
;;  rendering switched off.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_waitvbl:
    DIAG_CHECKPOINT 2, $7C00    ; blue: the game reached WaitForVBlank
    php
    pha
    phx
    phy
@inside:                        ; already in vblank?  then this call is for the
    lda a:HVBJOY                ;   next frame, not the one just ending
    bmi @inside
@wait:
    lda a:HVBJOY
    bpl @wait

    ;  The NES build's NMI handler began every frame with
    ;      LDA soft2000 : STA $2000
    ;  and the game leans on it: code sets soft2000 (or, in battle,
    ;  btl_soft2000, which BattleWaitForVBlank copies into it) and never writes
    ;  $2000 itself.  Since this port has no interrupt handler, that push has to
    ;  happen here, or the pattern-table select, the VRAM stride and the coarse
    ;  scroll all stay stuck at whatever was last written directly.
    lda a:NES_soft2000
    sta a:h_ppuctrl

  .ifdef PROBE_LATCH
    lda a:h_latch               ; did the frame end mid address-pair?
    beq @latchok
      DIAG16 $7C00              ; blue: the $2006 write toggle is out of phase
    .a8
@latchok:
  .endif
    ;  The NES build read $2002 twice a frame -- once at the top of
    ;  WaitForVBlank and again in the NMI handler -- and each read reset the
    ;  PPU's $2005/$2006 first-or-second-write toggle.  This port replaced both,
    ;  so nothing cleared it and any imbalance persisted for good, after which
    ;  every address pair was swapped and writes landed at wild addresses.  The
    ;  minimap shows it worst: it sets a fresh address for every single byte.
    stz a:h_latch

    jsr hal_flush
    ENTER16
    inc a:h_frame
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

hal_flush:
  .ifdef PROBE_HI
    ;  A frame that writes many $2006 high bytes but only ever one distinct
    ;  value is the collapse we are looking for.  Frames writing none leave min
    ;  above max, so they cannot trip it.
    lda a:h_frame+1
    cmp #5                      ; well past boot
    bcc @hidone
    lda a:h_hicount
    cmp #40                     ; the crest loop writes 48 a frame
    bcc @hidone
    lda a:h_himin
    cmp a:h_himax
    bne @hidone
      DIAG16 $001F              ; red: every high byte this frame was identical
      .a8
@hidone:
    stz a:h_hicount
    lda #$FF
    sta a:h_himin
    stz a:h_himax
  .endif
  .ifdef PROBE_PAL
    lda a:h_palwrites
    cmp #40                     ; a real palette update is 32 bytes at most
    bcc @palok                  ; named, not anonymous: DIAG16 carries its own
      DIAG16 $001F              ; anonymous label and would capture the branch
    .a8                         ; DIAG16 leaves the assembler tracking 16-bit A
@palok:
    stz a:h_palwrites
  .endif
    lda #$80
    sta a:INIDISP               ; forced blank while VRAM is open
    jsr flush_pal
    jsr flush_chr
    jsr flush_nt
    jsr flush_oam
    jsr flush_raster
    jsr flush_scroll
    jsr flush_ntsplit
    lda a:h_ppumask
    and #$18                    ; is the NES rendering either layer?
    beq @dark
    lda #$0F
    sta a:INIDISP
    rts
@dark:
    lda #$80
    sta a:INIDISP
    rts

; --- palette ------------------------------------------------------------
flush_pal:
    lda a:h_paldirty
    bne :+
    rts
:   stz a:h_paldirty
    ENTER16
    ldy #0
@loop:
    ;  Only re-send entries that actually moved.  The intro's fade animates
    ;  four colours, but rewriting all thirty-two of them every frame was
    ;  enough on its own to push the flush past the end of vblank -- which is
    ;  why the prologue, which never scrolls, showed a black band that shrank
    ;  once the fade finished and the palette stopped changing.
    tya
    tax
    sep #$20
    .a8
    lda a:h_palforce            ; emphasis or greyscale moved: redo everything
    bne @send
    lda f:NESPAL,x
    cmp f:NESPALPREV,x
    bne @send
      rep #$20                  ; unchanged: rejoin the loop, 16-bit again
      .a16
      brl @skip
@send:
    .a8
    lda f:NESPAL,x
    sta f:NESPALPREV,x
    rep #$20
    .a16

    tya                         ; CGRAM entry for NES palette index Y:
    and #$0003                  ;   background  i      -> (i>>2)*16 + (i&3)
    sta a:h_t0                  ;   sprite      i+16   -> 128 + (i>>2)*16 + ...
    tya
    lsr a
    lsr a
    cmp #4
    bcc @bg
      sbc #4
      asl a
      asl a
      asl a
      asl a
      clc
      adc #128
      bra @entry
@bg:
    asl a
    asl a
    asl a
    asl a
@entry:
    clc
    adc a:h_t0
    sta a:h_t1
    sep #$20
    .a8
    lda a:h_t1
    sta a:CGADD
    rep #$20
    .a16
    tya
    tax
    sep #$20
    .a8
    lda f:NESPAL,x
    and #$3F
    sta a:h_t2
    rep #$20
    .a16
    lda a:h_t2
    and #$003F
    sep #$20
    .a8
    sta a:h_t4                  ; 8-bit from here: h_greyscale is a single byte,
    lda a:h_greyscale           ; and a 16-bit load would drag in its neighbour
    beq :+
      lda a:h_t4
      and #$30                  ; greyscale: snap to the grey column
      sta a:h_t4
:   lda a:h_t4
    rep #$20
    .a16
    and #$003F
    asl a
    tax
    lda f:nespal_snes + HALFAR,x
    jsr apply_tint
    sep #$20
    .a8
    sta a:CGDATA
    xba
    sta a:CGDATA
    rep #$20
    .a16
@skip:
    iny
    cpy #32
    bcs :+
    brl @loop                   ; the body is too long for a short branch now
:   sep #$20
    .a8
    stz a:h_palforce
    rep #$20
    .a16
    LEAVE16
    rts


;;  Colour emphasis.  Setting one of the NES's three emphasis bits dims the
;;  *other* two channels to roughly three quarters -- which is how the battle
;;  screen flashes.  The SNES has no equivalent switch, so the tint is baked
;;  into CGRAM instead, and the palette is marked dirty whenever the bits move.
.a16
.i16
apply_tint:                     ; A = BGR555 colour -> A, tinted
    pha
    lda a:h_emphasis
    and #$00FF                  ; mask off the neighbouring variable
    bne :+
      pla
      rts
:   pla
    sta a:h_t3

    and #$001F                  ; red, dimmed if green or blue is emphasised
    sta a:h_t4
    lda a:h_emphasis
    and #$0006
    beq :+
      jsr dim_channel
:   lda a:h_t4
    sta a:h_t5

    lda a:h_t3                  ; green, dimmed if red or blue is emphasised
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #$001F
    sta a:h_t4
    lda a:h_emphasis
    and #$0005
    beq :+
      jsr dim_channel
:   lda a:h_t4
    asl a
    asl a
    asl a
    asl a
    asl a
    ora a:h_t5
    sta a:h_t5

    lda a:h_t3                  ; blue, dimmed if red or green is emphasised
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #$001F
    sta a:h_t4
    lda a:h_emphasis
    and #$0003
    beq :+
      jsr dim_channel
:   lda a:h_t4
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    ora a:h_t5
    rts

dim_channel:                    ; h_t4 -= h_t4 >> 2
    lda a:h_t4
    lsr a
    lsr a
    sta a:h_t0
    lda a:h_t4
    sec
    sbc a:h_t0
    sta a:h_t4
    rts

; --- pattern tables -----------------------------------------------------
flush_chr:
    ENTER16
    lda a:h_chrlo
    cmp a:h_chrhi
    beq @dirty
    bcc @dirty
    LEAVE16
    rts
@dirty:
  .ifdef PROBE_SPAN
    ;  Well after boot, a frame that touches CHR at all should be the minimap's
    ;  decor stage, which spreads across tiles up to $FC.  If the highest byte
    ;  touched is inside the first sixteen tiles, the writes are collapsing.
    lda a:h_frame
    cmp #1200
    bcc @spanok
    lda a:h_chrhi
    cmp #$0200
    bcs @spanok
      sep #$20
      .a8
      DIAG16 $001F              ; red: CHR writes collapsed into a tiny range
      .a16
@spanok:
  .endif
  .ifdef CHR_FLUSH_ALL
    lda #0                      ; diagnostic: ignore the dirty span and send the
    sta a:h_chrlo               ; whole of CHR every frame
    lda #$3FFF
    sta a:h_chrhi
  .endif
    lda a:h_chrlo               ; round the span out to whole words
    and #$FFFE
    sta a:h_chrlo
    lda a:h_chrhi
    ora #$0001
    sta a:h_chrhi
    sep #$20
    .a8
    lda #$80
    sta a:VMAIN                 ; step one word after each $2119 write
    lda #$01
    sta a:DMAP0                 ; two registers: $2118 then $2119
    lda #$18
    sta a:BBAD0
    lda #WRAMBANK
    sta a:A1B0
    rep #$20
    .a16
    lda a:h_chrlo
    lsr a
    clc
    adc #VRAM_CHR
    sta a:VMADDL
    lda a:h_chrlo
    clc
    adc #.loword(CHRSHADOW)
    sta a:A1T0L
    lda a:h_chrhi
    sec
    sbc a:h_chrlo
    inc a
    sta a:DAS0L
    sep #$20
    .a8
    lda #$01
    sta a:MDMAEN
    rep #$20
    .a16
    lda #$FFFF                  ; span is clean again
    sta a:h_chrlo
    stz a:h_chrhi
    LEAVE16
    rts

; --- tilemap ------------------------------------------------------------
;  Each NES row is written to the SNES tilemap twice, at row r and at row
;  r+30.  The NES's vertical scroll wraps every 30 rows; a SNES 64-row tilemap
;  wraps every 64.  Duplicating the 30 rows makes the first 60 rows periodic
;  with period 30, and a 30-row-tall window starting anywhere in 0..29 never
;  reaches past row 58 -- so the two agree everywhere the screen can see.
flush_nt:
    lda a:h_ntdirty
    bne :+
    rts
:   stz a:h_ntdirty
    lda #$80
    sta a:VMAIN                 ; step one word per transfer
    lda #$01
    sta a:DMAP0                 ; two registers: $2118 then $2119
    lda #$18
    sta a:BBAD0
    lda #WRAMBANK
    sta a:A1B0
    ENTER16

    ;  Decide whether this frame is a column update.  Scrolling sideways
    ;  dirties the same narrow span in nearly every row, and that case has to
    ;  go down the tilemap in one transfer rather than sixty.  Writing whole
    ;  columns is safe even where only some rows changed: the shadow is
    ;  authoritative, so re-sending a clean row costs nothing but time.
    lda #$00FF
    sta a:h_c0                  ; union of the dirty spans, low water
    stz a:h_c1                  ; ...and high water
    stz a:h_gcount              ; how many rows are dirty
    ldx #0
@scan:
    sep #$20
    .a8
    lda a:NTCOLLO,x
    cmp a:NTCOLHI,x
    beq :+
    bcs @scannext               ; low above high: this row is clean
:   inc a:h_gcount
    lda a:NTCOLLO,x
    cmp a:h_c0
    bcs :+
      sta a:h_c0
:   lda a:NTCOLHI,x
    cmp a:h_c1
    bcc :+
      sta a:h_c1
:
@scannext:
    rep #$20
    .a16
    inx
    cpx #30
    bcc @scan

.if ENABLE_COLUMN_FLUSH
    lda a:h_gcount
    cmp #8                      ; enough rows to be worth it?
    bcc @byrows
    lda a:h_c1
    sec
    sbc a:h_c0
    cmp #5                      ; and a narrow enough span?
    bcs @byrows
    jsr column_flush
    ldx #0                      ; every row is clean now
    sep #$20
    .a8
:   lda #$FF
    sta a:NTCOLLO,x
    stz a:NTCOLHI,x
    inx
    cpx #32
    bcc :-
    rep #$20
    .a16
    LEAVE16
    rts
.endif
    ;  LEAVE16 above asserts .a8/.i8 for the assembler.  Execution only reaches
    ;  @byrows by branching *into* here from the scan, which is still 16-bit, so
    ;  the widths have to be restated -- otherwise the whole row path assembles
    ;  with 8-bit immediates and runs as 16-bit, which is exactly as bad as it
    ;  sounds, and only when the block above is compiled in.
    .a16
    .i16

@byrows:
    stz a:h_row
    lda #NTSHADOW               ; source of row 0
    sta a:h_ntsrc
    stz a:h_vdst0               ; tilemap row 0
    lda #(30*32)
    sta a:h_vdst1               ; ...and its duplicate, at row 30
@rowloop:
    ldx a:h_row
    sep #$20
    .a8
    lda a:NTCOLLO,x
    sta a:h_c0
    lda a:NTCOLHI,x
    sta a:h_c1
    lda #$FF
    sta a:NTCOLLO,x             ; and the row is clean again
    stz a:NTCOLHI,x
    stz a:h_c0+1
    stz a:h_c1+1
    rep #$20
    .a16
    lda a:h_c1
    cmp a:h_c0
    bcc @nextrow                ; hi < lo: this row never changed
    lda a:h_vdst0
    sta a:h_vdst
    jsr nt_put
    lda a:h_vdst1
    sta a:h_vdst
    jsr nt_put
@nextrow:
    ;  Every address here advances by a constant, so carry them along rather
    ;  than rebuilding each one out of shifts thirty times over.  Rebuilding
    ;  them was what pushed the flush past the end of vblank while scrolling
    ;  sideways, which showed as a black band across the top of the screen.
    lda a:h_ntsrc
    clc
    adc #128                    ; one row of the shadow
    sta a:h_ntsrc
    lda a:h_vdst0
    clc
    adc #32                     ; one row of the tilemap
    sta a:h_vdst0
    lda a:h_row
    inc a
    sta a:h_row
    cmp #2                      ; rows 30 and 31 share the top pair of
    bne :+                      ; quadrants; from row 32 the duplicate moves
      lda #$0800                ; to the bottom pair
      sta a:h_vdst1
      bra :++
:   lda a:h_vdst1
    clc
    adc #32
    sta a:h_vdst1
:   lda a:h_row
    cmp #30
    bcc @rowloop
    LEAVE16
    rts


.a16
.i16
;;  A horizontal scroll dirties the same narrow span in every row.  Taken row by
;;  row that is sixty transfers, each preceded by rebuilding its source and
;;  destination addresses, and it does not fit in vblank.  Taken as a column it
;;  is one gather and three transfers, because VMAIN can be told to step the
;;  VRAM address by a whole tilemap row after each write.
;;
;;  The gather is needed because DMA reads its source contiguously, and a column
;;  of the shadow is strided: consecutive rows are 128 bytes apart.
column_flush:
    lda a:h_c1
    sec
    sbc a:h_c0
    inc a
    sta a:h_ncols
    lda a:h_c0
    sta a:h_gcol
@colloop:
    lda a:h_gcol                ; --- collect the column out of the shadow ---
    asl a
    clc
    adc #NTSHADOW
    tax
    ldy #0
    lda #30
    sta a:h_gcount
@gather:
    lda a:$0000,x
    sta a:GATHERBUF,y
    iny
    iny
    txa
    clc
    adc #128                    ; the same column, one row down
    tax
    dec a:h_gcount
    bne @gather

    sep #$20                    ; --- and push it down the tilemap ---
    .a8
    lda #$81                    ; step one tilemap row per write
    sta a:VMAIN
    lda #WRAMBANK
    sta a:A1B0
    lda #$01
    sta a:DMAP0                 ; two registers: $2118 then $2119
    lda #$18
    sta a:BBAD0
    rep #$20
    .a16

    jsr col_base                ; the copy at rows 0..29
    sta a:VMADDL
    lda #GATHERBUF
    sta a:A1T0L
    lda #60
    sta a:DAS0L
    jsr col_go

    jsr col_base                ; its duplicate: rows 30 and 31 first...
    clc
    adc #(30*32)
    sta a:VMADDL
    lda #GATHERBUF
    sta a:A1T0L
    lda #4
    sta a:DAS0L
    jsr col_go

    jsr col_base                ; ...then rows 32..59, a quadrant lower
    clc
    adc #$0800
    sta a:VMADDL
    lda #(GATHERBUF+4)
    sta a:A1T0L
    lda #56
    sta a:DAS0L
    jsr col_go

    lda a:h_gcol
    inc a
    sta a:h_gcol
    dec a:h_ncols
    beq @done
    brl @colloop
@done:
    sep #$20
    .a8
    lda #$80                    ; back to stepping a single word
    sta a:VMAIN
    rep #$20
    .a16
    rts

;;  Word address of row 0 of the column in h_gcol.
col_base:
    lda a:h_gcol
    cmp #32
    bcc :+
      and #$001F
      clc
      adc #$0400                ; the right-hand pair of quadrants
:   clc
    adc #VRAM_BG1MAP
    rts

col_go:
    sep #$20
    .a8
    lda #$01
    sta a:MDMAEN
    rep #$20
    .a16
    rts

.a16
.i16
nt_put:
    ;  Send h_c0..h_c1 of this row to tilemap row h_vdst, split at the
    ;  boundary between the two 32-column halves of the 64x64 map.
    lda a:h_c0
    cmp #32
    bcs @rightonly
    lda a:h_c1
    cmp #32
    bcc :+
      lda #31
:   sta a:h_t3                  ; last column of the left-hand piece
    stz a:h_t4                  ; ...which lives in the left-hand quadrant
    lda a:h_c0
    sta a:h_t2
    jsr nt_piece
    lda a:h_c1
    cmp #32
    bcc @done
    lda #32
    sta a:h_t2
    lda a:h_c1
    sta a:h_t3
    lda #$0400
    sta a:h_t4
    jsr nt_piece
    rts
@rightonly:
    lda a:h_c0
    sta a:h_t2
    lda a:h_c1
    sta a:h_t3
    lda #$0400
    sta a:h_t4
    jsr nt_piece
@done:
    rts

nt_piece:
    ;  Columns h_t2..h_t3 of the row whose shadow begins at h_ntsrc, into
    ;  tilemap row h_vdst, quadrant offset h_t4.  Written through the port:
    ;  these spans are short -- a sideways scroll produces one or two tiles per
    ;  row -- and programming a DMA channel for them costs far more than the
    ;  writes themselves.
    lda a:h_t2
    and #$001F
    clc
    adc a:h_t4
    clc
    adc a:h_vdst
    clc
    adc #VRAM_BG1MAP
    sta a:VMADDL
    lda a:h_t2
    asl a                       ; two bytes per tilemap entry
    clc
    adc a:h_ntsrc
    tax
    stx a:h_ntsrc2              ; the address we will read from
    lda a:h_t3
    sec
    sbc a:h_t2
    inc a
    sta a:h_t5                  ; words to send
    cmp #8
    bcs @dma
    ;  Short spans -- a sideways scroll gives one or two tiles per row -- cost
    ;  less written straight through the port than programming a DMA channel.
    sep #$20
    .a8
@word:
    lda a:$0000,x
    sta a:VMDATAL
    inx
    lda a:$0000,x
    sta a:VMDATAH
    inx
    dec a:h_t5
    bne @word
    rep #$20
    .a16
    rts
@dma:
    ;  Long spans -- a vertical scroll redraws a whole 64-tile row -- are the
    ;  other way round: DMA moves them several times faster than the CPU can.
    lda a:h_ntsrc2
    sta a:A1T0L
    lda a:h_t5
    asl a                       ; two bytes per tilemap entry
    sta a:DAS0L
    sep #$20
    .a8
    lda #$01
    sta a:MDMAEN
    rep #$20
    .a16
    rts

; --- sprites ------------------------------------------------------------
.a8
.i8
flush_oam:
    lda a:h_oamdirty
    bne :+
    rts
:   stz a:h_oamdirty
    lda #$00
    sta a:DMAP0                 ; one register, $2104
    lda #$04
    sta a:BBAD0
    lda #WRAMBANK
    sta a:A1B0
    ENTER16
    stz a:OAMADDL               ; start of OAM
    lda #OAMSHADOW
    sta a:A1T0L
    lda #544                    ; 512 bytes of table, then the 32-byte high table
    sta a:DAS0L
    LEAVE16
    lda #$01
    sta a:MDMAEN
    rts


; --- raster splits ------------------------------------------------------
;  Turn the splits recorded during the last frame into an HDMA table driving
;  TM, so the SNES reproduces per-scanline layer switching in hardware rather
;  than asking the CPU to hit scanlines it cannot reliably hit.
.a8
.i8
flush_raster:
    lda a:h_rastercount
    bne @build
    stz a:HDMAEN                ; no splits: one setting for the whole frame
    lda a:h_tmcur
    sta a:TM
    sta a:h_tmframestart
    rts
@build:
    lda a:h_tmframestart        ; what was in force above the first split
    sta a:TM
    sta a:h_t0
    stz a:h_t1                  ; scanline the current span begins at
    ldy #0                      ; write cursor into the table
    ldx #0                      ; which recorded split we are on
@next:
    cpx a:h_rastercount
    bcs @tail
    lda a:RASTERLINE,x
    cmp a:h_t1
    bcc @skip                   ; out of order, or a zero-length span
    beq @skip
    sec
    sbc a:h_t1
    jsr emit_span
    lda a:RASTERLINE,x
    sta a:h_t1
@skip:
    lda a:RASTERTM,x
    sta a:h_t0
    inx
    bra @next
@tail:
    lda #224                    ; the rest of the visible frame
    sec
    sbc a:h_t1
    beq @end
    bcc @end
    jsr emit_span
@end:
    lda #$00
    sta a:HDMATAB,y             ; a zero line count ends the table
    lda #$00
    sta a:DMAP1                 ; write one byte to one register
    lda #<TM
    sta a:BBAD1
    ldx #<HDMATAB
    stx a:A1T1L
    ldx #>HDMATAB
    stx a:A1T1L+1
    lda #WRAMBANK
    sta a:A1B1
    lda #$02
    sta a:HDMAEN                ; channel 1
    lda a:h_tmcur               ; next frame opens on this frame's last value
    sta a:h_tmframestart
    stz a:h_rastercount
    stz a:h_ntsplits
    rts

;;  Emit one span of A scanlines holding the value in h_t0.  An HDMA line count
;;  is seven bits, so a long span becomes several entries.
emit_span:
    sta a:h_t2
@chunk:
    lda a:h_t2
    cmp #128
    bcc :+
      lda #127
:   sta a:h_t3
    sta a:HDMATAB,y
    iny
    lda a:h_t0
    sta a:HDMATAB,y
    iny
    lda a:h_t2
    sec
    sbc a:h_t3
    sta a:h_t2
    bne @chunk
    rts


; --- dialogue box nametable split --------------------------------------
;  Replay the mid-frame nametable switches recorded last frame as an HDMA
;  table on BG1HOFS.  Switching nametables is worth 256 pixels of horizontal
;  scroll here, so a band of scanlines taken from the other nametable is just a
;  band with a different scroll value -- which is exactly what HDMA is for.
.a8
.i8
flush_ntsplit:
    stz a:h_rasterwin
    lda a:h_ntsplits
    bne @build
    stz a:HDMAEN                ; nothing to split: one scroll for the frame
    rts
@build:
    ldy #0                      ; write cursor into the table
    ldx #0                      ; which recorded split we are on
    lda a:h_hofsframestart      ; the scroll the frame opened with
    sta a:h_t0
    lda a:h_hofsframestart+1
    sta a:h_t1
    stz a:h_t2                  ; scanline the current span begins at
@next:
    cpx a:h_ntsplits
    bcs @tail
    lda a:NTSPLITLINE,x
    cmp a:h_t2
    bcc @skip                   ; out of order, or a zero-length span
    beq @skip
    sec
    sbc a:h_t2
    jsr emit_hofs
    lda a:NTSPLITLINE,x
    sta a:h_t2
@skip:
    lda a:NTSPLITLO,x
    sta a:h_t0
    lda a:NTSPLITHI,x
    sta a:h_t1
    inx
    bra @next
@tail:
    lda #224                    ; the rest of the visible frame
    sec
    sbc a:h_t2
    beq @end
    bcc @end
    jsr emit_hofs
@end:
    lda #$00
    sta a:HOFSTAB,y             ; a zero line count ends the table
    lda #$02
    sta a:DMAP2                 ; mode 2: two bytes into one register
    lda #<BG1HOFS
    sta a:BBAD2
    ldx #<HOFSTAB
    stx a:A1T2L
    ldx #>HOFSTAB
    stx a:A1T2L+1
    lda #WRAMBANK
    sta a:A1B2
    lda #$04
    sta a:HDMAEN                ; channel 2
    stz a:h_ntsplits
    rts

;;  One span of A scanlines holding the 16-bit scroll in h_t0/h_t1.  An HDMA
;;  line count is seven bits, so a long span becomes several entries.
emit_hofs:
    sta a:h_t3
@chunk:
    lda a:h_t3
    cmp #128
    bcc :+
      lda #127
:   sta a:h_t4
    sta a:HOFSTAB,y
    iny
    lda a:h_t0
    sta a:HOFSTAB,y
    iny
    lda a:h_t1
    sta a:HOFSTAB,y
    iny
    lda a:h_t3
    sec
    sbc a:h_t4
    sta a:h_t3
    bne @chunk
    rts

; --- scroll -------------------------------------------------------------
flush_scroll:
    ENTER16
    lda a:h_scrollx
    and #$00FF
    sta a:h_t0
    sep #$20
    .a8
    lda a:h_ppuctrl
    and #$01                    ; coarse X: which nametable is on the left
    beq :+
      rep #$20
      .a16
      lda a:h_t0
      clc
      adc #256
      sta a:h_t0
      sep #$20
      .a8
:   lda a:h_t0
    sta a:BG1HOFS               ; write-twice 16-bit register
    lda a:h_t0+1
    sta a:BG1HOFS
    rep #$20
    .a16
    lda a:h_scrolly
    and #$00FF
    sta a:h_t1
    sep #$20
    .a8
    lda a:h_ppuctrl
    and #$02                    ; coarse Y
    beq :+
      rep #$20
      .a16
      lda a:h_t1
      clc
      adc #240
      sta a:h_t1
      sep #$20
      .a8
:   rep #$20
    .a16
    lda a:h_t1                  ; the SNES shows tilemap line VOFS+1, and we
    clc                         ; start eight lines down into the NES's picture
    adc #(NES_TOP_CROP - 1)
    and #$03FF
    sta a:h_t1
    sep #$20
    .a8
    lda a:h_t1
    sta a:BG1VOFS
    lda a:h_t1+1
    sta a:BG1VOFS
    LEAVE16
    rts


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Diagnostics
;;
;;  There is no debugger to hand, so the way to find out how far the machine
;;  got is to paint the backdrop and look at it.  diag_colour takes a NES
;;  palette index, puts it in CGRAM entry 0 and forces the display on.  Build
;;  with -D DIAG_STOP=n to stop at checkpoint n with its colour on screen.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Reset
;;
;;  The SNES reset vector lands here, in bank $00 with the machine in emulation
;;  mode.  Bring up the console, then hand the game its own OnReset with the
;;  program and data banks pointing at chunk $00 -- from that moment on the
;;  CPU is, for the game's purposes, a 6502 with a slightly unusual PPU.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_reset:
    sei
    clc
    xce                         ; native mode, just for the setup
    rep #$30
    .a16
    .i16
    ldx #$01FF
    txs
    lda #$0000
    tcd                         ; direct page 0, where the NES's zero page is
    sep #$30
    .a8
    .i8
    sec
    xce                         ; and straight back to emulation mode, so that
                                ; the ENTER16/LEAVE16 pairs below are balanced
    lda #$00
    pha
    plb                         ; DBR = 0: bank $00 carries the I/O map

    DIAG_CHECKPOINT 0, $001F    ; red: the CPU is executing our reset vector

    lda #$8F
    sta a:INIDISP               ; forced blank
    stz a:NMITIMEN              ; no interrupts anywhere in this port
    stz a:HDMAEN
    stz a:MDMAEN
    lda #$FF
    sta a:WRIO
    lda #$01
    sta a:MEMSEL                ; FastROM: banks $80-$FF run at 3.58MHz

    ;  Clearing WRAM has to be straight-line code, not a subroutine call: the
    ;  DMA below zeroes all 128K, and the stack lives in the first 8K of it.
    ;  A JSR here would have its own return address wiped out mid-transfer and
    ;  would RTS into nothing.  (S itself is a register, so it survives, and
    ;  every call after this point is safe.)
    stz a:$2181
    stz a:$2182
    stz a:$2183                 ; WRAM address = $7E:0000
    lda #$08                    ; fixed source address, one destination register
    sta a:DMAP0
    lda #$80                    ; $2180, the WRAM data port
    sta a:BBAD0
    lda #HALBANK
    sta a:A1B0
    ENTER16
    lda #.loword(zerobyte)
    sta a:A1T0L
    lda #0                      ; a count of zero means 65536
    sta a:DAS0L
    LEAVE16
    lda #$01
    sta a:MDMAEN
    lda #$01
    sta a:MDMAEN                ; twice over, for both 64K halves

    jsr clear_vram
    jsr init_ppu
    jsr init_halvars

    lda #$01
    sta a:NMITIMEN              ; ...except the automatic controller read

    DIAG_CHECKPOINT 1, $03E0    ; green: the console came up

    lda #CHUNK0
    pha
    plb                         ; DBR = the chunk we are about to run in
    lda #CHUNK0
    pha                         ; RTL pulls the address first, the bank second
    lda #>(OnReset-1)
    pha
    lda #<(OnReset-1)
    pha
    rtl

; --- clear all 64K of VRAM ----------------------------------------------
clear_vram:
    lda #$80
    sta a:VMAIN
    lda #$09                    ; fixed source, two registers
    sta a:DMAP0
    lda #$18
    sta a:BBAD0
    lda #HALBANK
    sta a:A1B0
    ENTER16
    stz a:VMADDL
    lda #.loword(zerobyte)
    sta a:A1T0L
    lda #0
    sta a:DAS0L
    LEAVE16
    lda #$01
    sta a:MDMAEN
    rts

zerobyte:
    .byte 0, 0

; --- PPU into the shape the translation layer expects --------------------
init_ppu:
    lda #$01
    sta a:OBSEL                 ; 8x8 sprites, characters at $2000 words
    lda #$01
    sta a:BGMODE                ; mode 1: BG1/BG2 4bpp, BG3 2bpp
    lda #$03
    sta a:BG1SC                 ; tilemap at $0000, 64x64
    lda #$10
    sta a:BG3SC                 ; tilemap at $1000, 32x32
    lda #$22
    sta a:BG12NBA               ; BG1 characters at $2000 words
    lda #$02
    sta a:BG34NBA
    lda #$11
    sta a:TM                    ; BG1 and sprites on the main screen
    stz a:TS
    stz a:SETINI                ; 224 lines, *not* 239-line overscan.
                                ;
                                ; The NES renders 240 lines and a television
                                ; crops about eight top and bottom.  Because the
                                ; vertical scroll wraps at 240, the map row the
                                ; game is redrawing sits at the top and bottom
                                ; edges simultaneously -- the same rows, seen
                                ; twice -- and the NES gets away with rebuilding
                                ; them in plain sight because no set showed
                                ; them.  Displaying all 240 lines faithfully
                                ; renders that churn visible.  So crop the way a
                                ; TV did: show NES lines 8..231, which is
                                ; exactly the SNES's 224.
    stz a:CGWSEL
    stz a:CGADSUB
    lda #$E0
    sta a:COLDATA
    rts

init_halvars:
    stz a:h_ppuctrl
    stz a:h_ppumask
    stz a:h_latch
    stz a:h_paldirty
    stz a:h_ntdirty
    stz a:h_oamdirty
    stz a:h_spr0hit
    stz a:h_scrollx
    stz a:h_scrolly
    stz a:h_readbuf
    stz a:h_curbank
    stz a:h_joyshift
    stz a:h_rastercount
    stz a:h_emphasis
    stz a:h_greyscale
    lda #$11
    sta a:h_tmcur
    sta a:h_tmframestart
    ENTER16
    lda #$FFFF                  ; an empty span: low water above high water
    sta a:h_chrlo
    stz a:h_chrhi
    stz a:h_frame
    LEAVE16
    ldx #0                      ; every tilemap row starts clean
:   lda #$FF
    sta a:NTCOLLO,x
    stz a:NTCOLHI,x
    inx
    cpx #32
    bcc :-
    ENTER16                     ; park every sprite off the bottom of the screen
    ldx #0
:   sep #$20
    .a8
    lda #$F0
    sta a:OAMSHADOW+1,x
    rep #$20
    .a16
    inx
    inx
    inx
    inx
    cpx #512
    bcc :-
    LEAVE16
    lda #1
    sta a:h_oamdirty
    lda #1
    sta a:h_paldirty
    rts

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The 2C02's colours, as 15-bit BGR
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

nespal_snes:
.include "nespal.inc"
