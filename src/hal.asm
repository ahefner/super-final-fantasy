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
.export hal_wipewindow, hal_chrload, hal_drawattr
.export hal_oamdma, hal_joystrobe, hal_joyread, hal_r4015
.export hal_swapprg, hal_waitvbl, hal_joyupdate, hal_waitscanline
.export hal_waitline9

.import OnReset

;; Flip to native mode with 16-bit registers, and back again.
;  Record the scanline reached, for the per-stage flush timing.  Costs four
;  instructions and only exists in a SCROLLSTAT build.
.macro STAGE slot
  .ifdef SCROLLSTAT
    lda a:STAT78                ; reset the counter read toggle first
    lda a:SLHV                  ; latch H/V
    lda a:OPVCT                 ; low 8 bits, halved to leave room for the 9th
    lsr a
    sta a:h_stage+slot
    lda a:OPVCT                 ; second read: bit 0 is counter bit 8.  Without
    lsr a                       ; it, vblank lines 256-261 alias onto display
    bcc :+                      ; lines 0-5 -- exactly the range in question
    lda a:h_stage+slot
    ora #$80
    sta a:h_stage+slot
:
  .endif
.endmacro

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
    ;  A write inside the raster window is only a split if it actually moves the
    ;  nametable selection.  The map's row/column draw writes $2000 twice every
    ;  step -- setting the +32 stride to write a column, then restoring
    ;  soft2000 -- and those change bit 2, not bits 0-1.  Recording them built
    ;  an HDMA table over BG1HOFS once per step, overriding the scroll that
    ;  flush_scroll had just written correctly and snapping the map sideways for
    ;  a frame.  Horizontal only, because the table drives the horizontal
    ;  register alone, which is why vertical scrolling never showed it.
    lda a:h_ppuctrl
    eor a:h_prevctrl
    and #$03                    ; did the nametable selection really change?
    beq @done
    lda a:h_ppumask
    and #$18                    ; is anything actually being displayed?
    beq @done
    lda a:HVBJOY
    bmi @done                   ; a vblank write is still just a setting
    ldx a:h_ntsplits
    cpx #8
    bcs @done
    lda a:STAT78                ; reset the counter's own read toggle
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
    lda a:STAT78                ; reset the counter's own read toggle
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
:   lda a:h_wipeon              ; the game is driving rendering again
    beq @notwipe
    stz a:h_wipeon
    ;  A wipe has just ended, and this is the last chance to leave the screen in
    ;  a sane state for a while.  The map load that follows a close runs for the
    ;  better part of a second without ever reaching WaitForVBlank -- measured,
    ;  46 frames with the game's own frame counter frozen on 45 of them -- so no
    ;  flush will come round to act on the write being made here.  INIDISP, TM
    ;  and HDMAEN would all keep whatever the wipe's last frame left them
    ;  holding, which means its final band, a few rows of map, sitting on screen
    ;  for the whole load instead of the black the game asked for.
    lda a:h_hdmaen              ; the wipe's channel goes now, not at the flush
    and #$FD
    sta a:h_hdmaen
    sta a:HDMAEN
    lda a:h_ppumask
    and #$18                    ; is the game asking for any rendering at all?
    bne @notwipe
    lda #$80
    sta a:INIDISP               ; no: blank it here and now
@notwipe:
    lda a:h_ppumask
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
    lda a:STAT78                ; reset the counter's own read toggle
    lda a:SLHV
    lda a:OPVCT
    sta a:h_t0
@wait:
    lda a:STAT78                ; reset the counter's own read toggle
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
  .if .defined(PROBE_HI) .or .defined(PROBE_ADDR)
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
  .ifdef PROBE_ADDR
    cmp #$1000                  ; every crest and logo destination is below this
    bcc @addrok
      pha
      lda #1
      sta a:h_addrhigh
      pla
@addrok:
  .endif
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
    lda f:NESNT,x               ; the byte the shadow was built from
    sta a:h_t3                  ;   -- nt_attr wants to know which bits changed
    cmp a:h_data                ; is the new byte already that one?
    beq @unchanged
    lda a:h_data
    sta f:NESNT,x               ; keep the raw bytes for readback and attributes
    rep #$20
    .a16
    lda a:h_t1
    and #$03FF
    cmp #$03C0
    bcc @tile
    jmp nt_attr

@unchanged:
    ;  Everything the shadow holds for this address was derived from the byte
    ;  already sitting here: the tilemap's tile number for a name byte, and the
    ;  sixteen palette high bytes for an attribute byte.  Writing the same value
    ;  again cannot change any of them, so the whole conversion is skipped.
    ;
    ;  This is sound only because those shadow bytes have exactly one author
    ;  each -- nt_write for the low byte of a tilemap word, nt_attr for the high
    ;  byte -- and because reset zeroes all of WRAM in one DMA, so NESNT and
    ;  NTSHADOW start out agreeing.  Nothing else ever writes either.
    ;
    ;  It matters because the game redraws a whole column as the map scrolls,
    ;  and over the overworld's large uniform stretches most of that column is
    ;  the same data that was already there.
    rep #$20
    .a16
    jmp bump_addr

@tile:
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
    lda a:h_data                ; which palette bits differ from what was here
    eor a:h_t3
    sta a:h_t3
    rep #$20
    .a16
    lda a:h_t2                  ; top-left tile of the 4x4 block
    lsr a
    lsr a
    lsr a
    asl a
    asl a
    sta a:h_row                 ; the row being written; starts at the block top
    lda a:h_t2
    and #$0007
    asl a
    asl a
    sta a:h_t4                  ; base column
    lda a:h_t1
    and #$0400                  ; right-hand nametable?
    beq :+
      lda a:h_t4
      clc
      adc #32
      sta a:h_t4
:
    ;  The tilemap offset of the block's top-left cell: row*128 + col*2, +1 to
    ;  reach the high byte, which is where the palette number lives.
    ;
    ;  This is computed once per attribute byte.  It used to be recomputed for
    ;  each of the sixteen cells -- seven shifts and half a dozen absolute
    ;  loads apiece -- and that arithmetic dominated the frame: measured
    ;  against the raster, nt_attr was 141 of the 238 scanlines the guest spent
    ;  on the frames where the main loop overran, which is the per-step stutter
    ;  while walking.  The loop below walks the offset instead: +2 along a row,
    ;  +128 down to the next.
    lda a:h_row
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta a:h_t1
    lda a:h_t4
    asl a
    clc
    adc a:h_t1
    inc a
    sta a:h_t6                  ; offset of this row's leftmost cell
    stz a:h_t2                  ; h_t2 = dy
@rowloop:
    lda a:h_row
    cmp #30                     ; the last attribute row covers only two rows,
    bcc :+                      ;   and the row only grows, so that is the end
    jmp @done                   ; (the loop body is past a branch's reach)
:
    ;  Rows 0 and 1 of the block take palettes 0 and 1, rows 2 and 3 take 2 and
    ;  3.  The pair is fixed for the whole row, so choose it once here rather
    ;  than rebuilding a quadrant index per cell.
    lda a:h_t2
    and #$0002
    tax
    sep #$20
    .a8
    lda a:h_pal+0,x
    sta a:h_t5+0                ; palette for the row's left-hand two cells
    lda a:h_pal+1,x
    sta a:h_t5+1                ;   ...and for its right-hand two
    ;  ...and which of the row's two quadrants actually changed.  A quadrant
    ;  whose two palette bits match the byte that was here before already has
    ;  its four cells right -- the same argument that lets nt_write skip an
    ;  unchanged byte outright, applied a quarter of a byte at a time.  A step
    ;  reveals one tile column, which lies in one of the two quadrant columns,
    ;  so half the block is typically untouched.
    lda a:h_t3                  ; old XOR new
    cpx #$0000
    beq :+
      lsr a
      lsr a
      lsr a
      lsr a                     ; rows 2 and 3 are described by the high nibble
:   sta a:h_t8+1
    and #$03
    sta a:h_t8+0                ; did the left-hand quadrant change?
    lda a:h_t8+1
    and #$0C
    sta a:h_t8+1                ;   ...and the right-hand one?
    ora a:h_t8+0
    bne :+
      rep #$20
      .a16
      jmp @nextrow              ; neither: past a branch's reach
:   rep #$20
    .a16
    lda a:h_t6
    sta a:h_t0                  ; h_t0 = running cell offset
    stz a:h_t7                  ; h_t7 = dx
@colloop:
    lda a:h_t7
    lsr a                       ; dx >> 1 selects the left or right palette
    tax
    sep #$20
    .a8
    lda a:h_t8,x                ; did this cell's quadrant change at all?
    bne @docell
      rep #$20
      .a16
      bra @advance
@docell:
    ldy a:h_t0
    lda a:h_t5,x
    ;  Only the newly revealed column actually changes palette; the other three
    ;  already hold this value.  Marking them dirty anyway would widen a step's
    ;  update to four columns, and column_flush would then run four times:
    ;  twelve transfers and 47 scanlines against a vblank of about 37.
    cmp a:NTSHADOW,y
    beq @same
    sta a:NTSHADOW,y
    rep #$20
    .a16
    lda a:h_t4                  ; mark_dirty wants the cell's own column, so
    clc                         ;   only a cell that changed pays for it
    adc a:h_t7
    sta a:h_col
    jsr mark_dirty
    bra @advance
@same:
    rep #$20
    .a16
@advance:
    lda a:h_t0
    clc
    adc #2                      ; next cell along the row
    sta a:h_t0
    lda a:h_t7
    inc a
    sta a:h_t7
    cmp #4
    bcc @colloop
@nextrow:
    lda a:h_t6
    clc
    adc #128                    ; next row of the tilemap
    sta a:h_t6
    lda a:h_row
    inc a
    sta a:h_row
    lda a:h_t2
    inc a
    sta a:h_t2
    cmp #4
    bcs @done                   ; the loop body is past a branch's reach
    jmp @rowloop
@done:
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
    jsr hal_apu_frame           ; this frame's sound, sent before the wait so
                                ;   it costs idle time rather than vblank
  .ifdef SCROLLSTAT
    lda a:RDNMI                 ; did a whole vblank pass while the game worked?
    bpl :+                      ; then the display advanced a frame and the game
    inc a:h_missed              ; did not.  This is the blind spot in h_late,
    bne :+                      ; which only sees arrivals *during* vblank
    inc a:h_missed+1
:   lda a:STAT78                ; reset the counter's own read toggle
    lda a:SLHV                  ; latch the counters: how much of the frame did
    lda a:OPVCT                 ; the game's own work just use?
    sta a:h_arrive
    lda a:HVBJOY                ; arriving here already inside vblank means this
    bpl @notlate                ; call is for the next frame, not the one just
    inc a:h_late                ; ending -- a whole frame is about to be lost
    bne @inside
    inc a:h_late+1
    bra @inside
@notlate:
  .endif
    ;  Arriving here already inside vblank used to cost a whole frame: the
    ;  code spun out the rest of that vblank and then waited for the next one,
    ;  on the reasoning that the call belonged to the frame about to start.
    ;  Measured against the raster that spin is 246 scanlines, and it is the
    ;  whole of the remaining per-step stutter.  A step's burst of $2007 writes
    ;  finishes around line 237 -- just inside vblank -- and the frame was then
    ;  thrown away even though the flush needs about fifteen lines and
    ;  twenty-four were left.
    ;
    ;  So serve this vblank instead, when there is demonstrably room in what is
    ;  left of it.  Two things have to be true, and both are cheap to ask:
    ;
    ;    RDNMI bit 7 latches "a vblank has begun" and clears on read, and the
    ;    two serving paths below are its only readers.  Set means this is a
    ;    vblank nothing has flushed into yet.  Clear means we already served it
    ;    and the game has come round again inside the same one, which must wait
    ;    -- otherwise a fast pass would run twice in one frame.
    ;
    ;    The V counter says how much is left.  Read as eight bits it is
    ;    unambiguous here, because HVBJOY has already established that we are in
    ;    vblank: lines 224..255 read as themselves, and 256..261 read as 0..5.
    ;    That is why a value below 224 at this point means the vblank is nearly
    ;    over, not that the picture has started.
    ;
    ;  (A SCROLLSTAT build reads RDNMI above for its own diagnostic and takes
    ;  the latch with it, so it never serves early.  That build is already
    ;  documented as unusable for other reasons.)
    lda a:HVBJOY
    bpl @wait                   ; not in vblank yet: the ordinary path
    lda a:RDNMI
    bpl @inside                 ; already flushed into this one: take the next
    lda a:STAT78                ; reset the counter's own read toggle
    lda a:SLHV                  ; latch H and V
    lda a:OPVCT
    cmp #224
    bcc @inside                 ; lines 256..261: too little of it left
    cmp #LATE_FLUSH_LAST+1
    bcs @inside                 ; too close to the end to fit a flush
    bra @serve                  ; room enough -- save the frame

@inside:                        ; wait out the rest of this vblank...
    lda a:HVBJOY
    bmi @inside
@wait:                          ; ...then for the next one to begin
    lda a:HVBJOY
    bpl @wait
    lda a:RDNMI                 ; consume the latch for the vblank we now serve
@serve:
    STAGE 5                     ; the instant the wait returned, before anything
                                ; else runs: separates "the wait came back late"
                                ; from "something between the wait and the flush
                                ; ate the time"

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
  .ifdef PROBE_ADDR
    ;  A frame with 40+ address pairs is the crest loop.  If any of its CHR
    ;  writes reached $1000 or above, the address the HAL reconstructed is not
    ;  the one the game asked for -- the fault would be on this side.
    lda a:APUSHADOW+$1F         ; set only by the crest loop's own frame
    beq @adone
    lda a:h_addrhigh
    beq @adone
      DIAG16 $001F              ; red: reconstructed address out of range
      .a8
@adone:
    stz a:h_addrhigh
    stz a:APUSHADOW+$1F
    stz a:h_hicount
  .endif
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
    ;  Scroll first.  While walking, the transfers below fill the whole of
    ;  vblank and spill a few lines into the display, and flush_scroll used to
    ;  run sixth of seven -- so the scroll reached the PPU at scanline 1 on most
    ;  walking frames, after the picture had already begun.  It costs nothing to
    ;  set it before the transfers, and then it always lands in vblank however
    ;  long they take.  flush_ntsplit still runs last, since its HDMA table
    ;  deliberately overrides BG1HOFS for the dialogue window.
    STAGE 0
    jsr flush_scroll
    jsr flush_pal
    STAGE 1
    jsr flush_chr
    STAGE 2
    jsr flush_nt
    STAGE 3
    jsr flush_oam
    STAGE 4
    stz a:h_hdmaen              ; each of the two below asks for its own channel
    jsr flush_raster
    jsr flush_ntsplit
    lda a:h_hdmaen              ; ...and only now does the register hear about it
    sta a:HDMAEN
  .ifdef SCROLLSTAT
    ;  Write the trace straight into SRAM, on the page the game cannot reach
    ;  (see TRACEFAR).  No ring in WRAM, no periodic copy, no trigger, and
    ;  nothing of the game's own memory touched -- the bytes are simply there in
    ;  the .ram file whenever the emulator exits.  2600 frames is ~43 seconds.
    lda a:HVBJOY                ; still inside vblank at the end of the flush?
    bmi @invbl
    inc a:h_over
    bne @invbl
    inc a:h_over+1
@invbl:
    lda a:RDNMI                 ; clear the latch: any vblank seen on the next
                                ; entry is then one the game genuinely missed
    lda a:STAT78                ; reset the counter's own read toggle
    lda a:SLHV                  ; latch H/V: how far into the frame are we now?
    lda a:OPVCT
    sta a:h_flushend
    ENTER16
    lda a:h_ringidx
    tax
    sep #$20
    .a8
    lda a:h_frame               ; sequence marker: consecutive proves it is ours
    sta f:TRACEFAR+$100, x
    lda a:h_lastx
    sta f:TRACEFAR+$101, x
    lda a:h_stage+0             ; scanline at each stage boundary
    sta f:TRACEFAR+$102, x
    lda a:h_stage+1
    sta f:TRACEFAR+$103, x
    lda a:h_stage+2             ; after flush_chr
    sta f:TRACEFAR+$104, x
    lda a:h_stage+3             ; after flush_nt
    sta f:TRACEFAR+$105, x
    lda a:h_stage+4             ; after flush_oam
    sta f:TRACEFAR+$106, x
    lda a:h_stage+5             ; where the vblank wait returned
    sta f:TRACEFAR+$107, x
    rep #$20
    .a16
    txa
    clc
    adc #8
    cmp #7808
    bcc :+
    lda #0
:   sta a:h_ringidx
    sta f:TRACEFAR+8
    lda #$5A5A
    sta f:TRACEFAR+0
    lda a:h_frame
    sta f:TRACEFAR+2
    lda a:h_late
    sta f:TRACEFAR+4
    lda a:h_over
    sta f:TRACEFAR+6
    LEAVE16
  .endif
    ;  A transition wipe decides visibility through TM, band by band, and its
    ;  frames carry no $2001 write at all -- ScreenWipeFrame's were removed when
    ;  the effect moved to HDMA.  So during a wipe h_ppumask still holds whatever
    ;  the game last set, and after ScreenWipe_Close finishes that is $00, with
    ;  the matching "rendering on" write not arriving until the opening half has
    ;  already run.  Blanking on it here put the whole opening half behind a
    ;  forced blank: the bands were built and drawn correctly and never seen.
    lda a:h_wipeon
    bne @lit
    lda a:h_ppumask
    and #$18                    ; is the NES rendering either layer?
    beq @dark
@lit:
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
  .ifdef CHRDUMP
    jsr chrdump_quiet           ; a frame that wrote no CHR at all
  .endif
    LEAVE16
    rts
@dirty:
    ;  The early-out above ends in LEAVE16, which leaves the assembler tracking
    ;  8-bit A.  Execution reaches here in 16-bit mode, so say so again -- with
    ;  --feature force_range a 16-bit immediate would otherwise be truncated to
    ;  a byte, silently, and the rounding below would be skipped entirely.
    .a16
    .i16
  .ifdef CHRDUMP
    jsr chrdump_busy
  .endif
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

.ifdef CHRDUMP
; --- diagnostic capture (CHRDUMP) ---------------------------------------
;  The minimap draws its crest and logo tiles one byte at a time over 32
;  consecutive frames, each frame dirtying a span that runs from tile $01 to
;  tile $FC.  Nothing else in the game does that, so 14 consecutive wide-span
;  frames followed by a frame that writes no CHR at all is the moment the
;  drawing has just finished -- exactly when the corruption is on screen.
;
;  At that moment, capture both sides of the transfer for tiles $D0-$FF: the
;  HAL's shadow, and what VRAM actually holds.  They go to the minimap's SRAM
;  scratch, which is dead by this point, so the host can read them straight
;  out of the .ram file.  Whichever side is wrong says where the bug lives.
.a16
.i16
;  Base tile of the 48-tile capture window; override with -D DUMPTILE=$nn
.ifndef DUMPTILE
DUMPTILE = $D0
.endif

chrdump_busy:
    rts

;  Bank $09 holds the minimap and nothing else -- its one entry point is
;  EnterMinimap -- so the NES bank being $09 is an exact test for "the minimap
;  is on screen".  Capture on every frame there that writes no CHR, rather than
;  latching a single shot: the drawing loops all write CHR, so a quiet frame is
;  one where the crests and logo are already up, and the last capture before
;  the emulator quits is the one that reaches the .ram file.
chrdump_quiet:
    sep #$20
    .a8
    lda a:h_curbank             ; a byte: a 16-bit load here would pick up
    cmp #$09                    ; h_frame's low byte along with it
    rep #$20
    .a16
    beq :+
    rts
:   lda #$5A5A
    sta f:$A17C00
    ldx #0
@shadow:
    lda f:CHRSHADOW+DUMPTILE*32, x
    sta f:$A17000, x
    inx
    inx
    cpx #$0600
    bcc @shadow
    sep #$20
    .a8
    lda #$80
    sta a:VMAIN                 ; step one word after each high-byte read
    rep #$20
    .a16
    ;  Validate the reader before trusting it: push a known pattern into unused
    ;  VRAM and pull it back through this very same read path.  If it returns
    ;  displaced, the displacement is in the reader, not in the DMA.
    lda #$6000
    sta a:VMADDL
    sep #$20
    .a8
    ldx #0
@sentwr:
    lda f:chrdump_sentinel, x
    sta a:VMDATAL
    inx
    lda f:chrdump_sentinel, x
    sta a:VMDATAH
    inx
    cpx #16
    bcc @sentwr
    rep #$20
    .a16
    lda #$6000
    sta a:VMADDL
    sep #$20
    .a8
    lda a:RDVRAML               ; discard a whole word: the read latch reloads
    lda a:RDVRAMH               ; from the pre-increment address, so the first
    ldx #0                      ; word is otherwise served twice
@sentrd:
    lda a:RDVRAML
    sta f:$A17C10, x
    lda a:RDVRAMH
    sta f:$A17C11, x
    inx
    inx
    cpx #16
    bcc @sentrd
    rep #$20
    .a16

    lda #VRAM_CHR+DUMPTILE*16
    sta a:VMADDL
    sep #$20
    .a8
    lda a:RDVRAML               ; discard a whole word (see the sentinel above)
    lda a:RDVRAMH
    ldx #0
@vram:
    lda a:RDVRAML
    sta f:$A17600, x
    lda a:RDVRAMH
    sta f:$A17601, x
    inx
    inx
    cpx #$0600
    bcc @vram
    rep #$20
    .a16

    ;  End-to-end test of the flush itself.  Plant a known pattern in the
    ;  shadow at tile $2F and mark just that tile dirty; the next frame's
    ;  ordinary DMA carries it to VRAM, and the capture after that reads back
    ;  what actually landed.  Faithful means the DMA is exonerated.
    ldx #0
@dmapat:
    lda f:chrdump_dmapat, x
    sta f:CHRSHADOW+$2F*32, x
    inx
    inx
    cpx #16
    bcc @dmapat
    lda #$2F*32
    sta a:h_chrlo
    lda #$2F*32+15
    sta a:h_chrhi
    rts

chrdump_dmapat:
    .byte $01,$02,$03,$04,$05,$06,$07,$08
    .byte $09,$0A,$0B,$0C,$0D,$0E,$0F,$10

chrdump_sentinel:
    .byte $11,$22,$33,$44,$55,$66,$77,$88
    .byte $99,$AA,$BB,$CC,$DD,$EE,$FF,$01
.endif

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
    lda a:h_wipeon              ; a transition wipe owns the screen while it runs
    beq @nowipe
    jmp wipe_table
@nowipe:
    lda a:h_rastercount
    bne @build
                                ; no splits: one setting for the whole frame,
                                ; and this frame wants no channel of its own
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
    lda a:h_hdmaen
    ora #$02                    ; channel 1 -- see h_hdmaen
    sta a:h_hdmaen
    lda a:h_tmcur               ; next frame opens on this frame's last value
    sta a:h_tmframestart
    stz a:h_rastercount
    stz a:h_ntsplits
    rts

;;  Three spans -- dark, lit, dark -- from the band hal_wipewindow recorded.
;;  Built here rather than where it was recorded so that both the table and the
;;  channel are settled during vblank, before HDMA is armed at the top of the
;;  frame.
wipe_table:
    ldy #0
    lda #$10                    ; TM: sprites only -- the background is off
    sta a:h_t0
    lda a:h_wipetop
    beq :+
      jsr emit_span
:   lda #$11                    ; TM: background and sprites
    sta a:h_t0
    lda a:h_wipebot
    sec
    sbc a:h_wipetop
    beq :+
      jsr emit_span
:   lda #$10
    sta a:h_t0
    lda #224
    sec
    sbc a:h_wipebot
    beq :+
      jsr emit_span
:   lda #$00
    sta a:HDMATAB,y             ; a zero line count ends the table
    lda #$10                    ; what stands above the first span
    sta a:TM
    sta a:h_tmframestart
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
    lda a:h_hdmaen
    ora #$02                    ; channel 1
    sta a:h_hdmaen
    stz a:h_rastercount
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
  .ifdef SCROLLSTAT
    stz a:h_hdmaon              ; no table: flush_scroll's value stands
  .endif
    rts                         ; nothing to split: no channel of its own
@build:
  .ifdef SCROLLSTAT
    lda #1                      ; an HDMA table is about to drive BG1HOFS,
    sta a:h_hdmaon              ; overriding whatever flush_scroll wrote
    lda a:h_ntsplits
  .endif
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
    lda a:h_hdmaen
    ora #$04                    ; channel 2 -- see h_hdmaen
    sta a:h_hdmaen
    stz a:h_ntsplits
    rts

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The map's attribute update
;;
;;  DrawMapAttributes reads back each attribute byte, rewrites the bits it owns
;;  and puts it back -- and on the NES that read-modify-write costs four writes
;;  to $2006 and three accesses to $2007 for every byte.  Through the HAL that
;;  is seven call chains apiece before any conversion happens, and measured
;;  against the raster it was better than a third of what the map load spent.
;;
;;  None of the ceremony is needed here: the byte it wants to read back is
;;  already in NESNT, so the whole row is done in one call, and the smear across
;;  the sixteen tilemap cells goes through nt_attr exactly as a $2007 write
;;  would have done.
.a8
.i8
hal_drawattr:
    php
    clc
    xce                         ; native mode for the whole run: the index into
    rep #$10                    ;   NESNT needs sixteen bits, and dropping back
    sep #$20                    ;   to emulation mode would truncate it to eight
    .a8
    .i16
    lda a:NES_mapflags          ; a column is one byte shorter than a row
    and #$02
    beq :+
      lda #$0F
      bra :++
:   lda #$10
:   sta a:h_dacount
    ldy #0
@loop:
    cpy a:h_dacount
    bcc :+
    jmp @done
:   lda a:DRAW_AT_HI,y          ; the address the game would have set
    sta a:h_addr+1
    lda a:DRAW_AT_LO,y
    sta a:h_addr
    rep #$20
    .a16
    lda a:h_addr
    and #$07FF                  ; the two nametables sit side by side
    sta a:h_t1
    tax
    sep #$20
    .a8
    lda f:NESNT,x               ; what the game would have read back
    sta a:h_t3                  ; nt_attr wants the old byte, to see what moved
    eor a:DRAW_ATTR,y           ; invert the bits being replaced...
    and a:DRAW_AT_MSK,y         ;   ...keep only those...
    eor a:h_t3                  ;   ...and put the rest back as it was
    sta f:NESNT,x
    sta a:h_data
    phy                         ; nt_attr uses both index registers
    rep #$20
    .a16
    lda a:h_t1
    and #$03FF
    jsr nt_attr                 ; the same smear a $2007 write would have done
    sep #$20
    .a8
    ply
    iny
    jmp @loop
@done:
    sep #$30
    .i8
    sec
    xce                         ; back to emulation mode for the caller
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Bulk upload through $2007
;;
;;  CHRLoad_Cont is patched to call this rather than pushing a run of bytes
;;  through $2007 one at a time.  Same contract as the loop it replaces: X rows
;;  of 256 bytes from (tmp)+Y, and on return tmp+1 has advanced by X with X and
;;  Y both zero.
;;
;;  The saving is not the conversion but everything wrapped around it.  Per byte
;;  the old path paid a JSR to a thunk, a JSL into this bank, four pushes, a
;;  mode switch, a dispatch and the whole lot again in reverse; here that
;;  happens once for the run.  Measured, the tileset load in the middle of a map
;;  transition had the CPU busy 209 of 262 lines, and 94 of those lines were
;;  that overhead rather than work.
;;
;;  Despite the name the routine is not only used for CHR: several callers fill
;;  a nametable through it.  So the destination decides which path is taken --
;;  getting that wrong scrambles nametable data into the pattern shadow, which
;;  is exactly what a first version of this did.
.a8
.i8
hal_chrload:
    php
    ENTER16
    txa
    and #$00FF
    sta a:h_clrows              ; rows
    tya
    and #$00FF
    sta a:h_clidx               ; where in the first row to start
    lda a:h_clrows
    xba                         ; rows * 256
    sec
    sbc a:h_clidx
    sta a:h_clcnt               ; bytes to move
    bne :+
    jmp @finish                 ; nothing to move (past a branch's reach)
:

    ;  Take the fast path only if the whole run lands in pattern space.  A run
    ;  that would cross out of it goes byte by byte instead; that is rare, and
    ;  correctness is worth more than the few frames.
    lda a:h_addr
    and #$3FFF
    clc
    adc a:h_clcnt
    cmp #$2001
    bcc :+
    jmp @slow                   ; past a branch's reach, like the two below
:   lda a:h_addr
    and #$3FFF
    cmp #$2000
    bcc :+
    jmp @slow
:

    lda a:h_addr                ; widen the dirty span once, not per byte
    and #$1FF0
    asl a
    cmp a:h_chrlo
    bcs :+
      sta a:h_chrlo
:
    ;  Whole aligned tiles take a much shorter path.  The sixteen bytes of a
    ;  tile land at fixed offsets from that tile's base in the shadow -- the
    ;  even ones for plane 0, the odd for plane 1 -- so with the base in X there
    ;  is no address arithmetic left in the loop at all, and A can stay eight
    ;  bits throughout, which takes the mode switches out too.  What remains per
    ;  byte is a load, a store and an index bump.
    lda a:h_addr
    and #$000F
    beq :+
    jmp @bytes                  ; not tile-aligned (past a branch's reach)
:   lda a:h_clcnt
    and #$000F
    beq :+
    jmp @bytes                  ; not a whole number of tiles
:   lda a:h_addr
    and #$1FF0
    asl a
    tax                         ; X = this tile's base in the shadow
    ldy a:h_clidx
    sep #$20
    .a8
@tile:
  .repeat 8, i
    lda (NES_tmp),y
    sta f:CHRSHADOW+(i*2),x     ; plane 0 rows land on even offsets
    iny
  .endrepeat
  .repeat 8, i
    lda (NES_tmp),y
    sta f:CHRSHADOW+(i*2)+1,x   ;   ...and plane 1 rows on odd ones
    iny
  .endrepeat
    rep #$20
    .a16
    txa
    clc
    adc #32                     ; a 4bpp tile is 32 bytes, not 16
    tax
    lda a:h_addr
    clc
    adc #16
    sta a:h_addr
    lda a:h_clcnt
    sec
    sbc #16
    sta a:h_clcnt
    beq @spanhi
    sep #$20
    .a8
    jmp @tile                   ; the unrolled body is past a branch's reach

@bytes:
    ;  Reached only by branches taken in 16-bit mode, but the code above ends in
    ;  an 8-bit stretch, so the assembler needs telling -- otherwise the 16-bit
    ;  immediates below are quietly assembled as bytes.
    .a16
    .i16
    ldy a:h_clidx
@fast:
    lda (NES_tmp),y             ; the low byte is the one wanted; the high byte
    sta a:h_data                ;   is just the next source byte, unused here
    lda a:h_addr                ; which byte of the tile?
    and #$000F
    asl a                       ;   plane 0 rows land on even offsets...
    sta a:h_t1
    and #$0010                  ;   ...and plane 1 rows (i >= 8) on odd ones
    beq :+
      lda a:h_t1
      sec
      sbc #15
      sta a:h_t1
:   lda a:h_addr
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
    lda a:h_addr
    inc a
    sta a:h_addr
    iny
    dec a:h_clcnt
    bne @fast

@spanhi:
    lda a:h_addr                ; the last byte written closes the dirty span
    dec a
    and #$1FF0
    asl a
    ora #$001F
    cmp a:h_chrhi
    bcc :+
      sta a:h_chrhi
:   jmp @finish                 ; over the slow path, which is out of reach

    ;  Anything not bound for pattern space goes through the ordinary
    ;  conversion, which handles nametables, attributes and palette alike and
    ;  bumps the address itself.  It uses both index registers and h_t0..h_t8,
    ;  so the loop keeps its own state in memory.
@slow:
    lda a:h_clidx
    tay
    lda (NES_tmp),y
    sta a:h_data
    jsr w2007_core
    lda a:h_clidx
    inc a
    sta a:h_clidx
    dec a:h_clcnt
    bne @slow

@finish:
    lda a:h_clrows              ; the caller expects tmp+1 to have advanced once
    xba                         ;   per row, which is rows * 256 on the pointer
    clc                         ;   taken as a whole
    adc a:NES_tmp
    sta a:NES_tmp
    LEAVE16
    ldx #0                      ; the loop this replaces exited with both zeroed
    ldy #0
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The map transition wipe
;;
;;  The game opens and shuts a horizontal band across the screen, a little more
;;  of it each frame.  On the NES it drew that band by hand: background off,
;;  on again tmp+4 scanlines later, off again after tmp+5 more, with each switch
;;  timed by burning exactly one scanline per call to WaitScanline.
;;
;;  None of that timing survives here -- see the note beside ENABLE_RASTER_SPLITS
;;  for why the writes cannot be caught where the game means them -- so
;;  ScreenWipeFrame is patched to call this instead.  Nothing has to be inferred:
;;  tmp+4 and tmp+5 describe the band exactly, and three spans of an HDMA table
;;  over TM draw it in hardware, for nothing, every scanline of the frame.
;;
;;  Sprites stay on throughout, as the NES left them.  The game hides them for
;;  the duration by parking OAM off-screen before the wipe starts, so "background
;;  off" really does mean a black band.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
.a8
.i8
hal_wipewindow:
    php
    pha
    phx
    phy
    sep #$30
    .a8
    .i8
    ;  Record the band; the flush builds the table from it.  Nothing is
    ;  programmed here on purpose.  This runs after ScreenWipeFrame_Prep, which
    ;  does an OAM DMA and a palette draw -- and a palette draw is $2007 traffic,
    ;  which is dear in this port -- so by now the raster is quite often past the
    ;  end of vblank and into the picture.  Enabling HDMA there starts it
    ;  mid-frame with a stale pointer, which paints scattered single scanlines,
    ;  and rewriting the table there hands HDMA a table it is already reading.
    ;
    ;  First lit line, in SNES picture lines.  tmp+4 is measured from before the
    ;  picture starts, so the band sits WIPE_LEAD further down; a band beginning
    ;  above the top of the picture starts at zero and loses that much height.
    lda a:NES_tmp+5             ; height
    sta a:h_wipebot
    lda a:NES_tmp+4
    sec
    sbc #WIPE_LEAD
    bcs @haveTop
      eor #$FF
      inc a                     ; how far above the picture it began
      sta a:h_wipetop
      lda a:h_wipebot
      sec
      sbc a:h_wipetop
      bcs :+
        lda #0                  ; entirely above the picture: nothing lit
:     sta a:h_wipebot
      lda #0
@haveTop:
    sta a:h_wipetop
    clc
    adc a:h_wipebot
    bcs @full                   ; past 255: lit all the way down
    cmp #224
    bcc :+
@full:
      lda #224
:   sta a:h_wipebot             ; first dark line below the band
    lda #1
    sta a:h_wipeon
    ply
    plx
    pla
    plp
    rtl

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
  .ifdef SCROLLSTAT
    lda a:STAT78                ; when does the scroll actually reach the PPU?
    lda a:SLHV
    lda a:OPVCT
    sta a:h_scrollline
  .endif
:   lda a:h_t0
    sta a:BG1HOFS               ; write-twice 16-bit register
  .ifdef SCROLLSTAT
    sta a:h_lastx               ; ...and keep it for the scroll trace
  .endif
    lda a:h_t0+1
    sta a:BG1HOFS
  .ifdef SCROLLSTAT
    sta a:h_lastxhi             ; the half a low-byte trace cannot see
  .endif
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
  .ifdef SCROLLSTAT
    sta a:h_lasty               ; ...and keep it for the scroll trace
  .endif
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
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Audio: the SPC700 side
;;
;;  The SPC700 runs a small fixed program (tools/genspc.py) that does nothing
;;  but apply what it is told to the S-DSP.  All the thinking happens over
;;  here, where it can be traced.  Two pieces: getting that program into the
;;  SPC700 at reset through its boot ROM, and one packet per voice per frame.
;;
;;  Packet, three data ports then the sequence number last:
;;      APUIO1  bit 7 key-off, bit 6 key-on, bits 5-4 voice, bits 3-0 volume
;;      APUIO2  pitch low        APUIO3  pitch high
;;      APUIO0  sequence number; the SPC700 acts when it changes and echoes it
;;
;;  Every wait on the SPC700 is bounded.  If it never answers -- a failed upload,
;;  a cartridge without one -- the game runs silent rather than hanging.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  The IPL boot ROM protocol.  On power-up the SPC700 sits in its boot ROM
;;  with $AA/$BB on ports 0/1; a transfer is "nonzero on port 1, address on
;;  2/3, $CC on port 0", then each byte is "data on port 1, running index on
;;  port 0" with the index echoed back as the acknowledgement; and a zero on
;;  port 1 with an index that has jumped by at least two makes it jump to the
;;  address on 2/3.
.a8
.i8
spc_upload:
    clc
    xce                         ; native mode: the byte index needs 16 bits
    rep #$10
    sep #$20
    .a8
    .i16
    ldx #$FFFF                  ; how long to wait for the boot ROM's greeting
@ready:
    lda a:APUIO0
    cmp #$AA
    bne @notyet
    lda a:APUIO1
    cmp #$BB
    beq @go
@notyet:
    dex
    bne @ready
    bra @out                    ; nobody home
@go:
    lda #$01
    sta a:APUIO1                ; a transfer follows...
    lda #<SPCPROG_LOAD
    sta a:APUIO2                ; ...to this address
    lda #>SPCPROG_LOAD
    sta a:APUIO3
    lda #$CC
    sta a:APUIO0
    jsr spc_ack                 ; every wait on the boot ROM is bounded: a real
    bcs @out                    ;   SPC700 that does not answer as the emulator's
    ldx #0                      ;   did must leave a silent game, not a hung one
@byte:
    lda f:spcprog + HALFAR,x
    sta a:APUIO1
    txa                         ; the low byte of the index is the handshake
    sta a:APUIO0
    jsr spc_ack
    bcs @out
    inx
    cpx #SPCPROG_LEN
    bne @byte
    lda #$00
    sta a:APUIO1                ; no more data: jump...
    lda #<SPCPROG_ENTRY
    sta a:APUIO2                ; ...here
    lda #>SPCPROG_ENTRY
    sta a:APUIO3
    txa
    clc
    adc #2                      ; the index must move on by two or more,
    bne :+                      ;   and must not be zero
      inc a
:   sta a:APUIO0
    jsr spc_ack
    bcs @out
    sta a:h_apuseq              ; the program takes this as its baseline, so the
                                ;   first real packet must count on from it
    ;  The program announces itself by writing zero to port 0.
    ldx #$FFFF
@alive:
    lda a:APUIO0
    beq @running
    dex
    bne @alive
    bra @out
@running:
    lda #1
    sta a:h_apuok
@out:
    sep #$30
    .i8
    sec
    xce
    rts

;;  Wait for the boot ROM to echo the value in A on port 0.  Carry set on
;;  timeout.  Preserves A and X; uses Y as the counter.
.a8
.i16
spc_ack:
    ldy #$4000
@poll:
    cmp a:APUIO0
    beq @got
    dey
    bne @poll
    sec
    rts
@got:
    clc
    rts

;;  One frame of sound.  Called with the game's registers already saved.
;;
;;  What the driver asks of the APU was measured before any of this was
;;  designed (see the audio commits): constant volume and halted length
;;  counters throughout, amplitude done in software in the low nibble of the
;;  control register every frame, $4015 used to gate channels for sound
;;  effects.  So per pulse channel, per frame: it sounds if $4015 enables it,
;;  its volume nibble is nonzero and its timer is 8 or more (the NES mutes a
;;  pulse below that); its pitch is the timer through the table; its duty is
;;  the top two control bits.  A voice going from silent to sounding is a
;;  key-on, sounding to silent a key-off, and nothing else is -- the driver's
;;  volume-0 rest is the note boundary, and a same-pitch $4003 rewrite mid-note
;;  is a phase restart the ear cannot hear on a constant-volume square.
.a8
.i8
hal_apu_frame:
    lda a:h_apuok
    bne :+
    rts
:
  .if AUDIO_TEST_TONE
    lda #<TEST_TONE_PITCH
    sta a:APUIO2
    lda #>TEST_TONE_PITCH
    sta a:APUIO3
    lda a:h_tonekon
    bne @hold
      inc a:h_tonekon
      lda #$4F                  ; key-on, voice 0, volume 15
      bra @cmd
@hold:
    lda #$0F                    ; voice 0, volume 15, no key event
@cmd:
    sta a:APUIO1
    jsr apu_send
    rts
  .endif
    clc
    xce                         ; native: the timer and the table index are 16-bit
    rep #$30
    .a16
    .i16
    ;  How many half-frame clocks fall in this video frame.  The game writes
    ;  $C0 to $4017 (bank_0F: "alternative pAPU frame counter method"), which
    ;  selects the five-step sequence, and that clocks the sweep at 96Hz where
    ;  the four-step mode would give 120Hz.  96 does not divide 60, so carry
    ;  the remainder between frames and the ticks fall 1,2,1,2,2 -- eight every
    ;  five frames.  Running two a frame, as this first did, sweeps a quarter
    ;  too fast, which is audible beside a console.
    lda a:h_swacc
    clc
    adc #96
    ldx #0
@acctick:
    cmp #60
    bcc @accdone
    sbc #60                     ; carry is set: the cmp above said A was larger
    inx
    bra @acctick
@accdone:
    sta a:h_swacc
    stx a:h_swtickn
    sep #$20
    .a8
    .i16
    ldy #0                      ; Y = the channel's register base in the shadow
    lda #$01
    sta a:h_apumask             ; pulse 1 is voice 0: bit 0 of $4015 and of h_apuon
    stz a:h_apuvoice
@pulse:
    lda a:APUSHADOW+$15
    and a:h_apumask             ; enabled?
    beq @silent
    lda a:APUSHADOW+0,y
    and #$0F                    ; sounding?
    beq @silent
    sta a:h_apuvol
    rep #$20
    .a16
    ;  The sweep unit owns this channel's period once the driver has set it,
    ;  so the note comes from there rather than straight from the shadow.  It
    ;  also decides when the period has run past either end and the channel
    ;  falls silent.
    tya                         ; Y is 0 or 4; the sweep state is two bytes wide
    lsr a
    tax                         ; X = 0 for pulse 1, 2 for pulse 2
    jsr apu_sweep
    lda a:h_swmute,x
    bne @silent16
    lda a:h_swper,x
    pha                         ; keep the timer: the size table indexes by it
    asl a                       ; word index
    tax                         ; (long addressing indexes by X only)
    lda f:apupitch_pulse + HALFAR,x
    sta a:h_apupitch
    pla
    tax                         ; X = timer, for the byte-wide size table
    sep #$20
    .a8
    ;  The waveform this pitch was computed for.  Duty and cycle length travel
    ;  together in the sequence byte's top five bits: the duty bits are already
    ;  in position 7-6 in the control register, and the table's size index is
    ;  pre-shifted to 5-3, so this is two loads and an OR.
    lda f:apusize_pulse + HALFAR,x
    sta a:h_apuwave
    lda a:APUSHADOW+0,y
    and #$C0                    ; duty
    ora a:h_apuwave
    sta a:h_apuwave
    lda a:h_apupitch+1          ; PITCH_H alone now: the duty has its own field
    sta a:APUIO3
    lda a:h_apupitch
    sta a:APUIO2
    lda a:h_apuvol
    ora a:h_apuvoice
    pha
    lda a:h_apuon
    and a:h_apumask
    bne @sounding               ; already sounding: pitch and volume only
      pla
      ora #$40                  ; silent last frame: key-on
      pha
      lda a:h_apuon
      ora a:h_apumask
      sta a:h_apuon
@sounding:
    pla
    sta a:APUIO1
    jsr apu_send
    bra @next
@silent16:
    sep #$20
    .a8
@silent:
    lda a:h_apuon
    and a:h_apumask
    beq @next                   ; was silent already: nothing to send
    lda a:h_apuon
    eor a:h_apumask
    sta a:h_apuon
    lda #$80                    ; key-off
    ora a:h_apuvoice
    sta a:APUIO1
    jsr apu_send
    ;  Every voice's paths, sounding and silent alike, come back here, so this
    ;  has to dispatch on all four and stop after the last.  An earlier version
    ;  only knew how to follow pulse 1, and after the noise voice went silent it
    ;  read the voice number as "not pulse 1" and restarted the triangle --
    ;  triangle, noise, silent, triangle, for ever.  The frame loop never
    ;  returned, which is a black screen at boot.
@next:
    lda a:h_apuvoice
    beq @topulse2               ; pulse 1 done
    cmp #$10
    beq @tri                    ; pulse 2 done
    cmp #$20
    beq @tonoise                ; triangle done
    jmp @done                   ; noise done: the frame is finished
@topulse2:
    lda #$10
    sta a:h_apuvoice            ; pulse 2 is voice 1
    lda #$02
    sta a:h_apumask
    ldy #4
    jmp @pulse                  ; the body is past a branch's reach
@tonoise:
    jmp @noise

    ;  The triangle.  With the control bit set -- which is all but eight of the
    ;  writes ever seen -- the linear counter reloads every quarter-frame from
    ;  the low seven bits of $4008, so the voice sounds exactly when that value
    ;  is nonzero: $8F is on, $80 is off.  The rare control-clear write is a
    ;  timed note, approximated here as "on while nonzero".  No volume on the
    ;  NES, so a fixed one here, balanced against the pulses by ear later.
@trisilent:
    sep #$20
    .a8
    bra @silent
@tri:
    lda #$20
    sta a:h_apuvoice            ; voice 2
    lda #$04
    sta a:h_apumask
    lda a:APUSHADOW+$15
    and #$04
    beq @silent
    lda a:APUSHADOW+8
    and #$7F                    ; linear counter reload value
    beq @silent
    lda #15
    sta a:h_apuvol
    rep #$20
    .a16
    lda a:APUSHADOW+$A          ; timer
    and #$07FF
    cmp #2                      ; below this the NES triangle is not a tone
    bcc @trisilent
    pha
    asl a
    tax
    lda f:apupitch_tri + HALFAR,x
    sta a:h_apupitch
    pla
    tax
    sep #$20
    .a8
    lda f:apusize_tri + HALFAR,x  ; cycle length; no duty on the triangle, so
    sta a:h_apuwave               ;   the SPC700 reads this as the size alone
    lda a:h_apupitch+1
    sta a:APUIO3
    lda a:h_apupitch
    sta a:APUIO2
    lda a:h_apuvol
    ora a:h_apuvoice
    pha
    lda a:h_apuon
    and a:h_apumask
    bne @trisounding
      pla
      ora #$40                  ; key-on
      pha
      lda a:h_apuon
      ora a:h_apumask
      sta a:h_apuon
@trisounding:
    pla
    sta a:APUIO1
    jsr apu_send
    jmp @noise

    ;  Noise, voice 3.  It sounds when $4015 enables it and $400C's volume
    ;  nibble is nonzero; its rate is $400E's period through the table; it has
    ;  no pitch, so the packet's pitch-low byte carries the rate instead.
@noise:
    lda #$30
    sta a:h_apuvoice            ; voice 3
    lda #$08
    sta a:h_apumask
    lda a:APUSHADOW+$15
    and #$08
    beq @noisesilent
    lda a:APUSHADOW+$C
    and #$0F
    bne @noiseon
@noisesilent:
    jmp @silent                 ; the shared key-off path is out of branch reach
@noiseon:
    sta a:h_apuvol              ; the raw nibble: the packet carries four bits
                                ;   of volume and the SPC700 does the scaling,
                                ;   as it does for every other voice
    lda a:APUSHADOW+$E
    and #$0F                    ; period index
    ;  Widen deliberately before indexing.  TAX with an eight-bit accumulator
    ;  and sixteen-bit index registers moves all sixteen bits, hidden high byte
    ;  included, so the index would carry rubbish above the period and the
    ;  table read would land anywhere.  The pulse and triangle paths compute
    ;  their index in real sixteen-bit mode and are not exposed to this.
    rep #$20
    .a16
    and #$00FF
    tax
    sep #$20
    .a8
    lda f:apunoise + HALFAR,x
    sta a:APUIO2                ; the rate rides where pitch would
    stz a:APUIO3
    stz a:h_apuwave             ; the noise voice plays no waveform
    lda a:h_apuvol
    ora a:h_apuvoice
    pha
    lda a:h_apuon
    and a:h_apumask
    bne @noisesounding
      pla
      ora #$40
      pha
      lda a:h_apuon
      ora a:h_apumask
      sta a:h_apuon
@noisesounding:
    pla
    sta a:APUIO1
    jsr apu_send
    bra @done
@done:
    sep #$30
    .i8
    sec
    xce
    rts

;;  One video frame of a pulse channel's sweep unit.
;;
;;  The sweep bends a note's period while it sounds: every half-frame it adds
;;  or subtracts period>>shift, and the channel goes silent when the period
;;  falls below 8 or the target passes $7FF.  The game drives three effects
;;  with it -- the menu chirp, the dialogue box opening and closing, and the
;;  minigame error tone -- and all of them run the period down to the mute
;;  threshold.  The chirp travels from timer 32 to 8, which is 3.4kHz to
;;  12.4kHz.  With no sweep it was one flat tone, which is what was reported.
;;
;;  Two ticks a frame: the game never writes $4017, so the frame counter stays
;;  in its power-on four-step mode and the half-frame clock is 120Hz.
;;
;;  Nothing records which register the CPU wrote -- the shadow keeps values,
;;  not events -- so a write is inferred from the period differing from the one
;;  last seen.  That is sound here rather than merely convenient: the driver
;;  will not rewrite a frequency that has not changed, because writing $4003
;;  would reset the duty, so a period that changes is always a real write and
;;  one that holds still belongs to the sweep.
;;
;;  Entry: native, A and index registers 16 bits, X = 0 for pulse 1 or 2 for
;;  pulse 2, Y = that channel's base in the shadow (0 or 4).
.a16
.i16
apu_sweep:
    lda a:APUSHADOW+1,y
    and #$00FF
    sta a:h_swreg               ; EPPP NSSS
    ;  Has the CPU set this channel going again?
    ;
    ;  A period differing from the one last seen is one answer, but not a
    ;  complete one: an effect replayed before it has finished writes the very
    ;  same register bytes, and a shadow that keeps values cannot tell that
    ;  from no write at all.  The menu chirp does exactly this -- it sounded
    ;  once and then stayed quiet however fast the cursor moved.
    ;
    ;  The game keeps its own record though.  Everything that takes pulse 2
    ;  loads sq2_sfx with its length in frames and the music driver counts it
    ;  down, so a value that has gone *up* since last frame is a new effect.
    ;  Reading it here costs nothing, where detecting the register write would
    ;  have meant extra code at every write site in banks that have no room.
    ;  Every sweep in this game is on pulse 2; there is no sq1_sfx.
    cpx #2
    bne @byperiod
    lda a:NESZP_SQ2SFX
    and #$00FF
    cmp a:h_sfxlast
    beq @samesfx
    bcc @samesfx
      sta a:h_sfxlast
      bra @reload
@samesfx:
    sta a:h_sfxlast
@byperiod:
    lda a:APUSHADOW+2,y
    and #$07FF
    cmp a:h_swseen,x
    beq @running
@reload:
    lda a:APUSHADOW+2,y
    and #$07FF
    sta a:h_swseen,x
    sta a:h_swper,x
    jsr apu_swdiv
@running:
    lda a:h_swtickn             ; one frame counter serves both channels, so
    sta a:h_swticks             ;   the tick count is worked out once a frame
    bne @tick
    jmp @noticks                ; out of a branch's reach past the tick body
@tick:
    ;  Target and mute are recomputed every half-frame, whether or not the
    ;  divider fires and whether or not the sweep is enabled.  Silencing a
    ;  pulse whose period is under 8, or whose target has run past $7FF, is a
    ;  property of the channel rather than of the sweep being switched on --
    ;  and a muted channel does not update its period even when the divider
    ;  does fire, which is what stops a rising sweep dead at the top.
    lda a:h_swper,x
    sta a:h_swtmp
    lda a:h_swreg
    and #$0007
    beq @haschange              ; a shift of zero makes the change the period
@shift:
    lsr a:h_swtmp
    dec a
    bne @shift
@haschange:
    lda a:h_swreg
    and #$0008
    bne @up
      lda a:h_swper,x           ; falling pitch: the period grows
      clc
      adc a:h_swtmp
      bra @target
@up:
    lda a:h_swper,x             ; rising pitch: the period shrinks
    sec
    sbc a:h_swtmp
    bcc @zero
    cpx #0
    bne @target                 ; pulse 2 subtracts the change; pulse 1 negates
    cmp #0                      ;   with ones' complement, so it takes one more
    beq @target
    dec a
    bra @target
@zero:
    lda #0
@target:
    sta a:h_swtgt
    stz a:h_swmute,x
    lda a:h_swper,x
    cmp #8
    bcc @domute
    lda a:h_swtgt
    cmp #$0800
    bcc @divider
@domute:
    lda #1
    sta a:h_swmute,x
@divider:
    lda a:h_swdiv,x
    beq @update
      dec a
      sta a:h_swdiv,x
      bra @next
@update:
    jsr apu_swdiv
    lda a:h_swreg
    and #$0080
    beq @next                   ; disabled -- the driver writes $7F -- so the
    lda a:h_swreg               ;   divider still runs but the period holds
    and #$0007
    beq @next                   ; a shift of zero never updates the period
    lda a:h_swmute,x
    bne @next                   ; muted: the period is not updated either
    lda a:h_swtgt
    sta a:h_swper,x
@next:
    dec a:h_swticks
    beq @out
    jmp @tick                   ; the tick body is past a branch's reach
@out:
    rts
@noticks:
    ;  No half-frame fell in this video frame.  The period stays put, but the
    ;  channel is still silent if it has already run past either end.
    stz a:h_swmute,x
    lda a:h_swper,x
    cmp #8
    bcs :+
      lda #1
      sta a:h_swmute,x
:   rts

;;  Reload the sweep divider from the register's period field.
.a16
.i16
apu_swdiv:
    lda a:h_swreg
    lsr a
    lsr a
    lsr a
    lsr a
    and #$0007
    sta a:h_swdiv,x
    rts

.a8
.i8
;;  Hand the packet on the data ports to the SPC700 and wait for it to be
;;  taken.  Called with A eight bits wide and in either index width, so the
;;  bounded-wait counter lives in memory rather than an index register.
apu_send:
    ;  Port 0 is the handshake: the SPC700 acts when it changes and echoes it
    ;  back.  Only enough of it has to change to be noticed, so three bits are
    ;  the sequence and the top five carry the waveform index -- which saves a
    ;  second packet per note, and there was nowhere left in ports 1-3 anyway.
    inc a:h_apuseq
    lda a:h_apuseq
    and #$07
    ora a:h_apuwave
    sta a:APUIO0
    stz a:h_apuwait             ; 256 polls: a few thousand cycles, against the
@wait:                          ;   few dozen the SPC700 takes to answer
    cmp a:APUIO0
    beq @ok
    dec a:h_apuwait
    bne @wait
    stz a:h_apuok               ; it stopped answering: go silent, not dead
@ok:
    rts

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
    jsr clear_cgram
    jsr init_ppu
    jsr init_halvars
    jsr spc_upload              ; audio: get the SPC700 running

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

;  CGRAM powers up arbitrary on real hardware, and the port only ever writes
;  four entries of each sixteen-colour palette -- an NES tile is two bits deep,
;  so colours 4..15 are never referenced and never written.  "Never referenced"
;  is not a reason to leave them holding random colours, and it costs one DMA
;  to make the whole of CGRAM defined before anything looks at it.
clear_cgram:
    stz a:CGADD
    lda #$08                    ; fixed source, one destination register
    sta a:DMAP0
    lda #$22                    ; $2122, the CGRAM data port
    sta a:BBAD0
    lda #HALBANK
    sta a:A1B0
    ENTER16
    lda #.loword(zerobyte)
    sta a:A1T0L
    lda #512                    ; 256 entries, two bytes each
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

    ;  No palette entry has reached CGRAM yet, and the comparison in flush_pal
    ;  has to be told so.  Both NESPAL and NESPALPREV live in WRAM, which reset
    ;  zeroes, so left alone they start out *equal* -- and flush_pal reads that
    ;  as "unchanged, nothing to send".  The first flush then sent nothing at
    ;  all, and an entry the game writes as colour $00 was never sent even
    ;  after that, because it always compared equal to the zero it started as.
    ;  CGRAM kept its power-on contents for those entries: zeroes under an
    ;  emulator, which reads as black and hides the bug, but arbitrary colours
    ;  on a real console.
    ;
    ;  $FF is not a colour the NES can hold -- its palette is six bits -- so
    ;  seeding with it makes the first write of any entry differ, zero included.
    ldx #0
:   lda #$FF
    sta f:NESPALPREV,x
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

; NES timer -> S-DSP pitch (tools/genapu.py) and the SPC700 program with its
; sample data (tools/genspc.py).
.include "apupitch.inc"
.include "spcprog.inc"
