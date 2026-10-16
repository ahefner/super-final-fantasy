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
.export aux_edge, aux_capture
.export hal_wipewindow, hal_chrload, hal_drawattr
.export hal_theendclear, hal_theendplot, hal_theendand
.export hal_ntblit
.export hal_oamdma, hal_joystrobe, hal_joyread, hal_r4015
.export hal_w4015, hal_w4003, hal_w4007, hal_w400b, hal_w400f
.export hal_altarband, hal_altaroff
.export hal_clearnt, hal_ntfill
.export hal_swapprg, hal_waitvbl, hal_joyupdate, hal_waitscanline
.export hal_waitline9
.export hal_vblaudio, hal_ppureclaim, hal_audioframe

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
    jsr mark_dirty8             ; already eight bits wide, so use the entry that
    rep #$20                    ;   wants that rather than widening here only
    .a16                        ;   for mark_dirty to narrow again
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
:   ;  The row's four cells, unrolled, with the running offset in Y and the
    ;  accumulator eight bits wide from start to finish.
    ;
    ;  This used to keep the offset and the column counter in memory and flip
    ;  the accumulator's width twice per cell.  That is sixteen cells for every
    ;  attribute byte the game writes, and attribute writes turned out to be
    ;  the single largest cost in a screen redraw -- 36% of one measured at
    ;  eighteen frames, more than the tile writes themselves.  Holding the
    ;  offset in an index register costs nothing: Y is not used across this
    ;  loop, and its width is set independently of the accumulator's.
    ;
    ;  Only a cell that actually changes is marked dirty.  Marking all four
    ;  would widen a step's update to four columns, and column_flush would then
    ;  run four times: twelve transfers and 47 scanlines against a vblank of
    ;  about 37.
    rep #$10
    .i16
    ldy a:h_t6
    sep #$20
    .a8
    stz a:h_col+1               ; the column store below is eight bits wide now,
                                ;   so clear the high byte the old one wrote
  .repeat 4, dx
    lda a:h_t8 + (dx >> 1)      ; did this cell's quadrant change at all?
    beq :+
    lda a:h_t5 + (dx >> 1)
    cmp a:NTSHADOW,y            ; already this palette?
    beq :+
      sta a:NTSHADOW,y
      lda a:h_t4
      clc
      adc #dx
      sta a:h_col
      jsr mark_dirty8           ; the eight-bit entry: no width to restore
:   iny
    iny                         ; next cell along the row
  .endrepeat
    rep #$20
    .a16
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
;;  Two entry points, each with its own copy of the work rather than one
;;  calling the other.  mark_dirty takes and leaves a sixteen-bit accumulator,
;;  which is what the tile path wants; mark_dirty8 is for a caller already in
;;  eight bits, and nt_attr calls it for every cell whose palette moves.
;;
;;  The duplication is deliberate.  Written as a wrapper round the eight-bit
;;  entry it cost the tile path an extra call and return on every write, and
;;  that path runs often enough that the two together measured worse than the
;;  version with no eight-bit entry at all.  A dozen bytes is the cheaper
;;  trade.
.a16
.i16
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

.a8
.i16
mark_dirty8:
    ldx a:h_row
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
    rts

;;  Advance the PPU address after a write.
;;
;;  The directives matter as much as the code.  mark_dirty8 above is .a8, and
;;  ca65 carries that forward: without these, every sixteen-bit immediate here
;;  assembles with a one-byte operand while the processor, running with a
;;  sixteen-bit accumulator, reads two -- and the instruction stream comes
;;  apart.  force_range truncates the constants rather than complaining, so it
;;  builds clean and dies at run time.
.a16
.i16
bump_addr:
    ;  Stays sixteen bits throughout.  This used to narrow the accumulator to
    ;  test one bit of h_ppuctrl and widen it again to do the addition, two
    ;  mode switches for an increment, on a routine that runs once per byte the
    ;  game writes to $2007.  A sixteen-bit load drags in the neighbouring
    ;  variable, but the mask keeps only bit 2, which comes from the low byte.
    lda a:h_ppuctrl
    and #$0004                  ; stride: down a column, or along a row?
    beq @by1
      lda a:h_addr
      clc
      adc #32
      sta a:h_addr
      rts
@by1:
    lda a:h_addr
    inc a
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

;;  Controller Reset -- the detection half.
;;
;;  L, X and Y cannot ride in joy: it is eight bits wide and every one is spoken
;;  for.  So they are read here, once a frame, straight after the flush, and the
;;  result is left in h_padreset for the game to act on.  WaitForVBlank is what
;;  reads it, which is why this is the right cadence and the right place --
;;  every frame loop in the game waits for vblank, so there is no such thing as
;;  a loop this misses.
;;
;;  That is the whole reason it is not hooked into the joypad handlers the way
;;  FFR does it.  Those only run when the game reads buttons, and plenty of
;;  loops never do: both palette fades, so the inn's save fade could not be
;;  reset out of, and the battle message waits, and any transition.  Hooking
;;  readers means hunting them one at a time forever.
;;
;;  Detection only.  The reset itself leaves from WaitForVBlank, in game code,
;;  because that is where a reset can safely be taken.
;;
;;  Straight after the flush is also what makes the HVBJOY wait free: the
;;  auto-latch runs at the top of vblank and is long finished by the time the
;;  transfers are done, so the wait below falls through.  A read that lands mid
;;  latch can tear, and a torn reading here would be a reset nobody asked for.
aux_capture:
@wait:
    lda a:HVBJOY
    and #$01                    ; don't read mid auto-latch
    bne @wait
    lda a:JOY1L
    and #(JOYAUX_L | JOYAUX_X | JOYAUX_R)   ; L, X and R, already in their
    sta a:h_joyaux                          ;   own bits
    lda a:JOY1H
    and #$40                    ; Y lives in the high byte, and nothing in the
    lsr a                       ;   NES byte wants it -- the #$3F mask drops it
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                       ; ...parked in bit 0, where JOY1L's signature
    ora a:h_joyaux              ;   nibble never puts anything
    sta a:h_joyaux
    rts


;;  Fire on the press, which is both the faster feel and the simpler rule: the
;;  combo bits changed since last frame, and what they changed *to* is a whole
;;  combo.  Nothing else is needed.
;;
;;  A press edge is naturally one-shot, which is what keeps the reset from going
;;  round again.  The buttons are still down when the title screen comes up, but
;;  h_joyauxprev already holds the combo -- nothing in OnReset or the zero page
;;  wipe reaches $08xx -- so there is no change and no second edge.  Firing on
;;  release needed a deliberate trick to get the same property, and left a
;;  stale-prev hazard besides: a combo sitting in h_joyauxprev from power-on
;;  WRAM was a reset on the first frame that read it.  On a press edge that same
;;  garbage is harmless, because the first frame can only ever *clear* it.
;;
;;  Clobbers A and X.  Sets h_padreset to the combo pressed, which the game
;;  clears when it acts on it.
aux_detect:
    jsr aux_capture
    ;  no fallthrough guard needed -- aux_edge is the rest of this routine, split
    ;  out only so tools/test_options.py can drive the edge with a reading of its
    ;  own choosing instead of the console's pad.
aux_edge:
    lda a:h_joyaux
    and #PADRESET_MASK
    tax                         ; X = the combo bits held now
    cpx a:h_joyauxprev
    beq @done                   ; unchanged since last frame: no edge either way
    stx a:h_joyauxprev
    cpx #PADRESET_SOFT
    beq @soft
    cpx #PADRESET_HARD
    beq @hard
@done:
    rts

@soft:
    lda #PADRESET_SOFT
    sta a:h_padreset
    rts

@hard:
    lda #PADRESET_HARD
    sta a:h_padreset
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
    php
    pha
    phx
    phy
    lda #1
    sta a:h_apufull             ; this is the frame's own call: advance the
                                ;   half-frame clock
    jsr hal_apu_frame           ; this frame's sound, sent before the wait so
                                ;   it costs idle time rather than vblank
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

    ;  The NES build read $2002 twice a frame -- once at the top of
    ;  WaitForVBlank and again in the NMI handler -- and each read reset the
    ;  PPU's $2005/$2006 first-or-second-write toggle.  This port replaced both,
    ;  so nothing cleared it and any imbalance persisted for good, after which
    ;  every address pair was swapped and writes landed at wild addresses.  The
    ;  minimap shows it worst: it sets a fresh address for every single byte.
    stz a:h_latch

    jsr hal_flush
    jsr aux_detect              ; once a frame, and the only place it happens
    ENTER16
    inc a:h_frame
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Lending the PPU to a native screen
;;
;;  The credits screen is not the game.  It is SNES code written for the SNES,
;;  it runs mode 7, and while it is up it owns VRAM, CGRAM and the PPU's
;;  registers outright -- mode 7 keeps its tilemap and its characters in the
;;  first 32KB of VRAM, which is exactly where this layer keeps the tilemap and
;;  the CHR, so there is no sharing to be had.  Two entry points let it do that
;;  without knowing anything about the shadows.
;;
;;  hal_vblaudio is hal_waitvbl without the flush.  The frame's sound still
;;  goes out and the frame counter still moves, but nothing reaches the PPU: a
;;  flush would put the mode 1 picture back over the screen's own, and
;;  flush_scroll alone would move the plane, since BG1HOFS and BG1VOFS are the
;;  mode 7 scroll too.  It returns at the top of a vblank, so the caller has
;;  the whole of it for its own transfers.
;;
;;  hal_ppureclaim is the way back.  It puts the hardware where reset left it
;;  -- VRAM and CGRAM zeroed, the registers set by init_ppu -- and then has the
;;  shadows rebuild the picture, which they can do completely because nothing
;;  the screen did touched them.  The CHR is sent here and now rather than
;;  marked: we are in forced blank, and 16KB is more than a flush should carry.
;;  The tilemap goes through flush_nt, which knows the 30-row duplication; the
;;  palette and OAM are only marked, for the next flush to send.
;;
;;  Both are called in emulation mode, like every other way into this bank.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_vblaudio:
    php
    pha
    phx
    phy
    lda #1
    sta a:h_apufull             ; this frame's own call, as in hal_waitvbl
    jsr hal_apu_frame
    ;  Always a fresh vblank, never the tail of the current one.  hal_waitvbl
    ;  takes pains to rescue a late arrival because the game's frames are
    ;  heavy and a lost one is visible stutter; a native screen has no such
    ;  excuse, and starting at the top every time is what makes "the whole of
    ;  vblank is yours" true.
@inside:
    lda a:HVBJOY
    bmi @inside
@wait:
    lda a:HVBJOY
    bpl @wait
    lda a:RDNMI                 ; consume the latch, as the flush paths do
    ENTER16
    inc a:h_frame
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

;;  hal_audioframe is hal_vblaudio's first half alone: one frame of sound,
;;  sent now, with no wait.  For a screen with no frame loop to wait in --
;;  New Game's roll (roll.asm) calls it from a tick, while the randomizer
;;  works, when a vblank has begun since the last one.  Emulation mode.
hal_audioframe:
    php
    pha
    phx
    phy
    lda #1
    sta a:h_apufull
    jsr hal_apu_frame
    ENTER16
    inc a:h_frame
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

hal_ppureclaim:
    php
    pha
    phx
    phy
    lda #$80
    sta a:INIDISP               ; forced blank while VRAM is open
    stz a:HDMAEN                ; the flush builds this afresh every frame

    jsr clear_vram
    jsr clear_cgram
    jsr init_ppu

    ;  The whole of the CHR shadow, straight back.
    lda #$80
    sta a:VMAIN
    lda #$01
    sta a:DMAP0                 ; two registers: $2118 then $2119
    lda #$18
    sta a:BBAD0
    lda #WRAMBANK
    sta a:A1B0
    ENTER16
    lda #VRAM_CHR
    sta a:VMADDL
    lda #.loword(CHRSHADOW)
    sta a:A1T0L
    lda #$4000
    sta a:DAS0L
    LEAVE16
    lda #$01
    sta a:MDMAEN

    ;  Every row of both nametables is dirty end to end.
    ldx #0
@rows:
    stz a:NTCOLLO,x
    lda #63
    sta a:NTCOLHI,x
    inx
    cpx #30
    bcc @rows
    lda #1
    sta a:h_ntdirty
    sta a:h_paldirty
    sta a:h_palforce            ; every entry, not only the ones that moved
    sta a:h_oamdirty
    ply
    plx
    pla
    plp
    rtl

hal_flush:
    lda #$80
    sta a:INIDISP               ; forced blank while VRAM is open
    ;  Scroll first.  While walking, the transfers below fill the whole of
    ;  vblank and spill a few lines into the display, and flush_scroll used to
    ;  run sixth of seven -- so the scroll reached the PPU at scanline 1 on most
    ;  walking frames, after the picture had already begun.  It costs nothing to
    ;  set it before the transfers, and then it always lands in vblank however
    ;  long they take.  flush_ntsplit still runs last, since its HDMA table
    ;  deliberately overrides BG1HOFS for the dialogue window.
    jsr flush_scroll
    jsr flush_pal
    jsr flush_chr
    jsr flush_nt
    jsr flush_oam
    stz a:h_hdmaen              ; each of the three below asks for its own channel
    jsr flush_raster
    jsr flush_ntsplit
    jsr flush_altar
  .ifdef APUSTAT
    jsr flush_apustat
  .endif
    lda a:h_hdmaen              ; ...and only now does the register hear about it
    sta a:HDMAEN
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
    ;  Which of the palette's eight emphasis blocks to read from.  The tint is
    ;  a fixed function of the emphasis bits and the colour, so it is baked
    ;  into the table by tools/genpal.py rather than worked out per entry: the
    ;  arithmetic used to cost some 38000 cycles a frame during the battle
    ;  transition, over four times a vblank, and the overrun held forced blank
    ;  across the top forty-odd scanlines of the picture.
    lda a:h_emphasis
    and #$0007
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; 64 entries of two bytes each
    sta a:h_tintbase
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
  .ifdef FFDARK
    ;  DEBUG BUILD ONLY, tag "dark".  The dungeons this effect belongs in are
    ;  mostly black; Coneria is mostly grass.  Swapping the town's green for
    ;  black is the cheapest way to judge the beam against the background it
    ;  will really have.  NES $1A is the grass, in two of the four BG palettes
    ;  -- read off the hardware, not guessed.
    cmp #$1A
    bne @nodark
      lda #$0F                  ; NES black
      sta a:h_t4
  @nodark:
  .endif
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
    clc
    adc a:h_tintbase            ; this emphasis mode's block, already tinted
    tax
    lda f:nespal_snes + HALFAR,x
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


;;  Colour emphasis is not applied here any more.  Setting one of the NES's
;;  three emphasis bits dims the *other* two channels to roughly three
;;  quarters, which is how the battle screen flashes; that used to be computed
;;  for every palette entry on every frame the bits moved.  It is a fixed
;;  function of the emphasis bits and the colour index, so tools/genpal.py now
;;  bakes all eight variants into nespal_snes and the flush just reads the
;;  right block.  See h_tintbase in flush_pal.

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
    ;  The early-out above ends in LEAVE16, which leaves the assembler tracking
    ;  8-bit A.  Execution reaches here in 16-bit mode, so say so again -- with
    ;  --feature force_range a 16-bit immediate would otherwise be truncated to
    ;  a byte, silently, and the rounding below would be skipped entirely.
    .a16
    .i16
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
    beq @dirty
    bcs @scannext               ; low above high: this row is clean
@dirty:
    ;  Where the dirty rows begin and end.  The loop below used to walk all
    ;  thirty whatever was dirty, and rebuild four running addresses for each
    ;  of them; a five-row update -- which is what a menu description or a
    ;  status line is -- spent six times as long stepping over clean rows as
    ;  sending the dirty ones.
    lda a:h_gcount
    bne @seenone
      stx a:h_rowlo             ; X is sixteen bits here, so this is a word
@seenone:
    stx a:h_rowend              ; the last dirty row seen, so far
    inc a:h_gcount
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

    lda a:h_gcount
    bne @some
    LEAVE16
    rts                         ; dirty flag set, but no row is actually dirty
    ;  ...and LEAVE16 has just told the assembler the widths are eight bits,
    ;  which the CPU only believes on that one path.  Everything below is still
    ;  reached in sixteen, so say so -- the same trap @byrows carries a note
    ;  about, and it is silent: "cmp #8" assembled two bytes wide and would
    ;  have eaten the branch behind it.
    .a16
    .i16
@some:
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
    ;  LEAVE16 above asserts .a8/.i8 for the assembler.  Execution only reaches
    ;  @byrows by branching *into* here from the scan, which is still 16-bit, so
    ;  the widths have to be restated -- otherwise the whole row path assembles
    ;  with 8-bit immediates and runs as 16-bit, which is exactly as bad as it
    ;  sounds, and only when the block above is compiled in.
    .a16
    .i16

@byrows:
    inc a:h_rowend              ; the scan left the last dirty row in it
    lda a:h_rowlo
    sta a:h_row
    asl a                       ; the shadow's row stride is 128 bytes
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #NTSHADOW
    sta a:h_ntsrc
    lda a:h_rowlo               ; the tilemap's is 32 words
    asl a
    asl a
    asl a
    asl a
    asl a
    sta a:h_vdst0
    ;  ...and the duplicate, which sits above row 29 for the first two rows
    ;  and in the bottom pair of quadrants from row 2 on.  @nextrow makes the
    ;  same switch as it advances; this is that rule evaluated once, for
    ;  whichever row the walk now starts on.
    lda a:h_rowlo
    cmp #2
    bcs @duplow
    clc
    adc #30
    asl a
    asl a
    asl a
    asl a
    asl a
    sta a:h_vdst1
    bra @rowloop
@duplow:
    sec
    sbc #2
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #$0800
    sta a:h_vdst1
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
    cmp a:h_rowend
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

  .ifdef AUDIOTEST
  .ifndef TRISWEEP
;;  A known pattern on one voice, so a pop can be attributed instead of guessed
;;  at.  Music changes pitch, volume and waveform together, which is why
;;  listening to it cannot separate them.  This drives pulse 1 alone through
;;  four eight-second segments, repeating:
;;
;;    0  steady      nothing changes at all -- the control
;;    1  volume      steps every eight frames, pitch held
;;    2  pitch       alternates every sixteen frames, volume held.  The two
;;                   timers sit in different size classes, so this exercises
;;                   the directory repoint as well
;;    3  note        silenced and re-sounded every sixteen frames
;;
;;  Everything downstream is the production path: the shadow is overwritten
;;  here and the packet builder and the SPC700 program see nothing unusual.
.a8
.i16
audio_test_pattern:
    ;  Two pulses, entirely static, for ever.  No segments and no dither: the
    ;  variable is which register's write cache the *build* bypasses, chosen by
    ;  FFTONE at build time, so the tone itself never changes and any pop is
    ;  purely the write traffic.
    stz a:APUSHADOW+$01
    stz a:APUSHADOW+$05
    lda #$03                    ; both pulses, nothing else
    sta a:APUSHADOW+$15
    lda #$B8                    ; duty 2, halted, constant volume, level 8
    sta a:APUSHADOW+$00
    lda #253
    sta a:APUSHADOW+$02
    stz a:APUSHADOW+$03
    lda #$B8
    sta a:APUSHADOW+$04
    lda #169                    ; a fifth up
    sta a:APUSHADOW+$06
    stz a:APUSHADOW+$07
    rts
  .endif
  .endif

  .ifdef TRISWEEP
TRISWEEP_BOT  = 16              ; the lowest timer the pitch table calls musical
TRISWEEP_TOP  = 768             ; ...and past the highest
TRISWEEP_STEP = 1               ; every timer, not one in four
TRISWEEP_HOLD = 10              ; frames per pitch; a whole sweep is about 125s
TRISWEEP_GAP  = 3               ; ...of which the last few are silent, so each
                                ;    pitch is a note-on rather than a tone

;;  Walk the triangle through every pitch it can be given, one at a time.
;;
;;    The clicks are deterministic and pitch-dependent, so the question is
;;  which pitches.  Finding that inside the game's own music means recording it
;;  and measuring wavelengths by hand.  Playing every pitch in order instead
;;  puts each one at a known place on the timeline, so a capture can say which
;;  ones misbehave without anybody counting waveforms.
;;
;;    Nothing else sounds, so any discontinuity in the output belongs to the
;;  triangle.  The linear counter is given control and a maxed reload so the
;;  note never gates itself off mid-pitch.
audio_test_pattern:
    ;  Gate the channel off for the last TRISWEEP_GAP frames of each pitch, so
    ;  every pitch arrives as a genuine note -- key-off, silence, key-on --
    ;  rather than a steady tone.  The clicks are heard at the START of notes,
    ;  and a sweep that merely holds each pitch never starts one, so it cannot
    ;  reproduce them however many pitches it covers.
    lda a:h_swpcnt
    cmp #(TRISWEEP_HOLD - TRISWEEP_GAP)
    bcc @TriSweepOn
      stz a:APUSHADOW+$15       ; silent: the HAL sees the channel stop and
      bra @TriSweepGated        ;   sends a key-off; the next frame re-keys it
@TriSweepOn:
    lda #$04                    ; triangle alone
    sta a:APUSHADOW+$15
@TriSweepGated:
    lda #$FF                    ; linear counter: control set, reload maxed
    sta a:APUSHADOW+$08
    lda a:h_swpcnt
    inc a
    sta a:h_swpcnt
    cmp #TRISWEEP_HOLD
    bcc @TriSweepHold
      stz a:h_swpcnt
      lda a:h_swptimer          ; timer += step, carried by hand in 8 bits
      clc
      adc #TRISWEEP_STEP
      sta a:h_swptimer
      bcc @TriSweepNoCarry
        inc a:h_swptimer+1
@TriSweepNoCarry:
      lda a:h_swptimer+1        ; past the top (or uninitialised)?  start over
      cmp #>TRISWEEP_TOP
      bcc @TriSweepHold
      bne @TriSweepWrap
      lda a:h_swptimer
      cmp #<TRISWEEP_TOP
      bcc @TriSweepHold
@TriSweepWrap:
      lda #<TRISWEEP_BOT
      sta a:h_swptimer
      lda #>TRISWEEP_BOT
      sta a:h_swptimer+1
@TriSweepHold:
    lda a:h_swptimer
    sta a:APUSHADOW+$0A         ; timer low
    lda a:h_swptimer+1
    and #$07
    sta a:APUSHADOW+$0B         ; timer high
    rts
  .endif

; --- the altar beam ----------------------------------------------------
;;  The NES draws this by toggling the monochrome bit at a counted cycle offset
;;  within each scanline: 120 pixels of grey per line, drifting one dot right
;;  per line because the loop runs 114 cycles against a scanline's 113.667.
;;  None of that timing survives the port, and it was only ever imitating
;;  light -- the original shakes the screen a pixel every eight frames
;;  specifically to hide the raster jitter it could not avoid.
;;
;;  The shape is not computed here.  Every frame of the animation has its HDMA
;;  window table built at build time by tools/genbeam.py and laid in its own
;;  ROM bank, so a frame costs one pointer store and the edges can move a pixel
;;  a line without vblank paying for it.  Computing them here cost more than
;;  vblank had: per-scanline the flush overran the interval and put a black
;;  band across the top of the picture, and quantising the taper into runs
;;  bought the time back only at the price of visible stairsteps.
;;
;;  Lines outside the beam carry an empty window -- left past right -- which
;;  switches colour maths off by itself, so the window alone describes the
;;  beam and CGADSUB can stay put for the whole effect.
;;
;;  IN:  nothing.  One call is one frame of the animation.
.a8
.i8
hal_altarband:
    php
    pha
    lda a:h_altaron
    bne @running
      stz a:h_altarframe        ; the first frame of a new effect
      lda #1
      sta a:h_altaron
      bra @out
@running:
    lda a:h_altarframe
    inc a
    cmp f:BEAMFAR               ; the frame count is the blob's first word
    bcc @store
      lda f:BEAMFAR
      dec a                     ; hold the last frame rather than run off the end
@store:
    sta a:h_altarframe
@out:
    pla
    plp
    rtl

;;  The effect is over: stop asking for a channel, and put the colour maths
;;  registers back where the reset left them.
.a8
.i8
hal_altaroff:
    php
    pha
    stz a:h_altaron
    stz a:h_altarframe
    stz a:CGADSUB               ; no colour maths at all
    stz a:CGWSEL                ; ...nor any colour window to gate it
    stz a:WOBJSEL
    lda #$E0                    ; and a fixed colour of zero in all three
    sta a:COLDATA
    pla
    plp
    rtl

;;  Point the window channel at this frame's table and set the maths up.  The
;;  registers are rewritten every frame rather than once at the start because
;;  the effect shares them with nothing and this costs a dozen stores.
.a8
.i8
flush_altar:
    lda a:h_altaron
    bne @on
    rts
@on:
    lda #$31                    ; add, no halve: BG1, sprites and the backdrop.
    sta a:CGADSUB               ;  The backdrop matters: NES colour 0 converts
                                ;  to 4bpp index 0, which is transparent on BG1,
                                ;  so every pixel the NES drew in the universal
                                ;  background colour is backdrop here.  Without
                                ;  bit 5 the light stopped dead at all of them.
    lda #$10                    ; colour maths inside the colour window only;
    sta a:CGWSEL                ;  the addend stays the fixed colour
    lda #$20                    ; W1 on for the colour window, not inverted
    sta a:WOBJSEL
    jsr altar_colour

    lda a:h_altarframe          ; this frame's table, out of the beam bank
    asl a
    tax
    lda a:altarorb              ; water and air each keep a table of their own,
    cmp #ORB_WATER              ;  so their beams can behave unlike the rest
    beq @water
    cmp #ORB_AIR
    beq @air
      lda f:BEAMFAR+BEAMOFF0,x
      sta a:A1T4L
      lda f:BEAMFAR+BEAMOFF0+1,x
      sta a:A1T4L+1
      bra @armed
@water:
    lda f:BEAMFAR+BEAMOFF1,x
    sta a:A1T4L
    lda f:BEAMFAR+BEAMOFF1+1,x
    sta a:A1T4L+1
    bra @armed
@air:
    lda f:BEAMFAR+BEAMOFF2,x
    sta a:A1T4L
    lda f:BEAMFAR+BEAMOFF2+1,x
    sta a:A1T4L+1
@armed:
    lda #BEAMBANK
    sta a:A1B4
    lda #$01
    sta a:DMAP4                 ; mode 1: two bytes into two registers
    lda #<WH0                   ;  -- WH0 then WH1, which are adjacent
    sta a:BBAD4
    lda a:h_hdmaen
    ora #$10                    ; channel 4 -- see the register block
    sta a:h_hdmaen
    rts

;;  The fixed colour the band adds, chosen by which altar was lit.  COLDATA
;;  packs channel-select bits and a five-bit level into one byte and writes
;;  only the channels selected, so a tint means clearing all three and then
;;  setting the ones wanted.  White needs one write because it sets all three.
;;
;;  Additive maths is why white reads brighter than any of the tints without
;;  being special-cased: green lifts one channel, white lifts three.  The air
;;  orb is the last of the four, so the escalation comes out of the arithmetic.
.a8
.i8
altar_colour:
    lda #$E0 | ALTARFLOOR       ; a floor under all three channels first, so a
    sta a:COLDATA               ;  tint brightens as well as colours.  A pure
                                ;  single-channel add only lifts pixels that
                                ;  already have that channel, which made the
                                ;  tints read as dark and heavily saturated.
    lda a:altarorb
    cmp #ORB_FIRE
    beq @fire
    cmp #ORB_WATER
    beq @water
    cmp #ORB_AIR
    beq @air
      lda #$40 | ALTARLEVEL     ; earth: green...
      sta a:COLDATA
      lda #$20 | ALTAREARTHR    ; ...warmed with a little red
      sta a:COLDATA
      rts
@fire:
    lda #$20 | ALTARLEVEL       ; red...
    sta a:COLDATA
    lda #$40 | ALTARFIREG       ; ...with its green lifted toward orange
    sta a:COLDATA
    rts
@water:
    lda #$80 | ALTARLEVEL       ; blue...
    sta a:COLDATA
    lda #$40 | ALTARWATERG      ; ...with its green lifted toward cyan
    sta a:COLDATA
    rts
@air:
    lda #$E0 | ALTARLEVEL       ; white -- all three channels at once
    sta a:COLDATA
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
    rts                         ; nothing to split: no channel of its own
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
    lda a:h_hdmaen
    ora #$04                    ; channel 2 -- see h_hdmaen
    sta a:h_hdmaen
    stz a:h_ntsplits
    rts

.ifdef APUSTAT
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  APUSTAT -- flag the triangle cutout, and say which way it died
;;
;;    Confirmed on hardware: when the triangle cuts out, the game still has it
;;  enabled, the HAL still believes it is keyed on, and the DSP's own ENVX for
;;  that voice is zero.  The voice is dead underneath both of them, so the
;;  cause is past the packet -- in the SPC or the DSP -- and neither the music
;;  driver nor h_apuon is where to look for it.
;;
;;  h_apuon is why it is permanent rather than what causes it: while its bit is
;;  set the HAL sends pitch and volume only and never a key-on, so a voice that
;;  dies underneath is never revived.
;;
;;  Two things this now does beyond flagging it:
;;
;;  DEBOUNCE.  A staccato note-off lands on the same condition for a frame or
;;  two -- the envelope reaches zero before the HAL notices the channel has
;;  gone quiet and clears h_apuon -- which made the overworld flicker.  A real
;;  cutout never ends, so require the condition to hold STAT_DEBOUNCE frames.
;;
;;  WHICH MECHANISM.  The SPC reports KOFF's readback alongside ENVX.  A bit
;;  set there is a key-off nobody sent, which is a corrupted register write --
;;  the same hazard the popping points at, and it would make both faults one
;;  bug.  A clear bit means the voice died without a key-off, which points at
;;  the BRR END-without-LOOP kill instead, and those want different fixes.
;;
;;      green   the fault, with KOFF bit 2 SET   -- a key-off we never sent
;;      red     the fault, with KOFF bit 2 CLEAR -- died without one
;;
;;  A whole-screen tint rather than digits: readable at a glance from across a
;;  room, and it needs no font tiles, which are not in VRAM on a map screen.
;;
;;  This owns CGWSEL/CGADSUB and will fight the orb beam's colour maths.
;;  Debug builds only.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
STAT_OFF      = $E0             ; all three channels selected, intensity zero
STAT_RED      = $3F
STAT_GREEN    = $5F
STAT_BLUE     = $9F
STAT_DEBOUNCE = 12              ; frames, about a fifth of a second

flush_apustat:
    sep #$20
    .a8
    lda a:APUSHADOW+$15         ; is the game still asking for the triangle?
    and #$04
    beq @NotFaulted
    lda a:h_apuon               ; does the HAL believe it is keyed on?
    and #$04
    beq @NotFaulted
    ;  The SPC reports the DSP's ENVX for that voice back through the
    ;  acknowledge port.  The ports are bidirectional, so this is its value.
    lda a:APUIO1
    bne @NotFaulted

    lda a:h_apustatcnt          ; held long enough to not be a note-off?
    cmp #STAT_DEBOUNCE
    bcs @Show
      inc a:h_apustatcnt
      bra @Clear
@Show:
    stz a:CGWSEL                ; colour maths everywhere, unwindowed
    lda #$3F
    sta a:CGADSUB               ; add the fixed colour to every layer
    ;  bit 3, not bit 2: Release is sticky and overrides GAIN, so a key-off
    ;  only has to be sampled once to kill the voice -- and KOFF=0 before every
    ;  key-on wipes the evidence within a note or two.  The SPC latches whether
    ;  the bit was ever seen set since this voice was keyed on.
    lda a:APUIO2
    and #$08
    beq @NotKeyedOff
      lda #STAT_GREEN           ; a key-off nobody sent
      sta a:COLDATA
      rts
@NotKeyedOff:
    lda a:APUIO3                ; KON as the DSP actually holds it
    and #$04
    beq @Red
      lda #STAT_BLUE            ; pinned in key-on: re-keyed every sample
      sta a:COLDATA
      rts
@Red:
    lda #STAT_RED               ; neither -- the envelope was zeroed some
    sta a:COLDATA               ;   other way, which leaves the BRR kill
    rts

@NotFaulted:
    stz a:h_apustatcnt
@Clear:
    stz a:CGADSUB               ; no maths, so COLDATA cannot show
    lda #STAT_OFF
    sta a:COLDATA
    rts
.endif

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
;;  None of that timing survives here -- see the note in snesmap.inc on why the
;;  game's split positions cannot be recovered -- so
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
;;  The SPC700 runs a small fixed program (tools/genspc.py) that applies what
;;  it is told to the S-DSP.  Nearly all the thinking happens over here, where
;;  it can be traced; the exception is the pulses' sweep units, which move a
;;  pitch on the APU's own half-frame clock, faster than one packet a frame
;;  can follow, so the SPC700 runs them.  Two pieces here: getting that
;;  program into the SPC700 at reset, and one packet per voice per frame.
;;
;;  Packet, three data ports then the sequence number last:
;;      APUIO1  bit 7 key-off, bit 6 key-on, bits 5-4 voice, bits 3-0 volume
;;      APUIO2  triangle: pitch low; pulse: the NES period, low; noise: rate
;;      APUIO3  triangle: pitch high; pulse: the period's top three bits, and
;;              bit 7 set when the CPU wrote $4003/$4007 (the sweep restarts)
;;      APUIO0  sequence number; the SPC700 acts when it changes and echoes it
;;  A pulse's sweep register goes in a packet of its own when it changes:
;;  both key bits set on APUIO1, the register on APUIO2.
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
;;
;;  That is one byte per handshake, about 29us each, and the image is 13KB.
;;  So the boot ROM carries only a 44-byte loader (genspc.py), which then
;;  takes the image three bytes a handshake: one from each third of it on
;;  ports 1-3, with the index's low byte on port 0, echoed back.  The image
;;  sits in ROM padded to three thirds of whole pages, so one index walks all
;;  three.
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
    jmp @out                    ; nobody home (past a branch's reach now)
@go:
    lda #$01
    sta a:APUIO1                ; a transfer follows...
    lda #<SPCLDR_LOAD
    sta a:APUIO2                ; ...to this address
    lda #>SPCLDR_LOAD
    sta a:APUIO3
    lda #$CC
    sta a:APUIO0
    jsr spc_ack                 ; every wait on the boot ROM is bounded: a real
    bcs @out                    ;   SPC700 that does not answer as the emulator's
    ldx #0                      ;   did must leave a silent game, not a hung one
@byte:
    lda f:spcldr + HALFAR,x
    sta a:APUIO1
    txa                         ; the low byte of the index is the handshake
    sta a:APUIO0
    jsr spc_ack
    bcs @out
    inx
    cpx #SPCLDR_LEN
    bne @byte
    lda #$00
    sta a:APUIO1                ; no more data: jump...
    lda #<SPCLDR_LOAD
    sta a:APUIO2                ; ...to the loader
    lda #>SPCLDR_LOAD
    sta a:APUIO3
    txa
    clc
    adc #2                      ; the index must move on by two or more,
    bne :+                      ;   and must not be zero
      inc a
:   sta a:APUIO0
    jsr spc_ack
    bcs @out
    ;  The loader, three bytes a handshake.  The index is counted on before
    ;  the wait rather than after it, so the SPC700's turn hides it, and the
    ;  next three bytes go out the moment the echo arrives.
    ldx #0
@triple:
    lda f:spcprog + HALFAR,x
    sta a:APUIO1
    lda f:spcprog + HALFAR + SPCPROG_THIRD,x
    sta a:APUIO2
    lda f:spcprog + HALFAR + 2 * SPCPROG_THIRD,x
    sta a:APUIO3
    txa                         ; the low byte of the index is the handshake,
    sta a:APUIO0                ;   written last
    inx
    ldy #$4000
@echo:
    cmp a:APUIO0
    beq @got
    dey
    bne @echo
    bra @out
@got:
    cpx #SPCPROG_THIRD
    bne @triple
    ;  The first packet's port-0 byte has to differ from two things: the
    ;  program's baseline, this last index ($FF), or it is not seen at all;
    ;  and the zero the program writes to say it is alive, which is still
    ;  sitting on port 0 as the "echo" when that packet goes out -- match it
    ;  and apu_send takes the stale zero for an acknowledgement, overwrites
    ;  the packet while the SPC700 is reading it, and the voice is keyed on
    ;  twice with half of one packet and half of another.  Counting on from
    ;  the baseline gave a counter of 0, which a sweep packet (no waveform
    ;  bits) turns into a whole zero byte.  Starting the count at 1 can be
    ;  neither: its low three bits are 001.
    stz a:h_apuseq
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
;;  its volume is nonzero -- the nibble, or the envelope's level when the
;;  constant bit is clear -- and its timer is 8 or more (the NES mutes a
;;  pulse below that); the timer itself goes to the SPC700, which runs the
;;  sweep and looks up the pitch; its duty is the top two control bits.  A
;;  voice going from silent to sounding is a
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
    clc
    xce                         ; native: the timer and the table index are 16-bit
    rep #$30
    .a16
    .i16
    ;  How many half-frame clocks fall in this video frame.  The game writes
    ;  $C0 to $4017 (bank_0F: "alternative pAPU frame counter method"), which
    ;  selects the five-step sequence, and that runs the half-frame clock at
    ;  96Hz where the four-step mode would give 120Hz.  96 does not divide 60,
    ;  so carry the remainder between frames and the ticks fall 1,2,1,2,2 --
    ;  eight every five frames.  Running two a frame, as this first did, ran
    ;  the sweep a quarter too fast, which is audible beside a console.  The
    ;  sweep has since moved to the SPC700, which keeps this clock for itself;
    ;  here it paces the envelopes and the triangle's linear counter.
    ;  Only the call made once per frame by hal_waitvbl advances this.  The
    ;  register hooks below call hal_apu_frame too, to get a silence out
    ;  without waiting for the frame, and if those also ticked the clock it
    ;  would run fast -- the very fault that was just corrected.
    lda a:h_apufull
    and #$00FF
    bne @fullframe
      stz a:h_hftickn
      bra @accdone
@fullframe:
    stz a:h_apufull
    lda a:h_hfacc
    clc
    adc #96
    ldx #0
@acctick:
    cmp #60
    bcc @accstore
    sbc #60                     ; carry is set: the cmp above said A was larger
    inx
    bra @acctick
@accstore:
    sta a:h_hfacc
    stx a:h_hftickn
@accdone:
    sep #$20
    .a8
    .i16
  .ifdef AUDIOTEST
    jsr audio_test_pattern
  .endif
    jsr apu_noiseenv
    jsr apu_pulseenv
    jsr apu_trilinear
    ldy #0                      ; Y = the channel's register base in the shadow
    lda #$01
    sta a:h_apumask             ; pulse 1 is voice 0: bit 0 of $4015 and of h_apuon
    stz a:h_apuvoice
@pulse:
    lda a:APUSHADOW+$15
  .ifdef SOLOMASK
    ;  DEBUG: only the channels in SOLOMASK may sound ($01 pulse 1, $02 pulse 2,
    ;  $04 triangle, $08 noise).  Masking here rather than at the shadow keeps
    ;  the game's own $4015 intact and routes the silenced voices through the
    ;  normal silent path, so each gets a proper key-off and h_apuon stays
    ;  consistent -- they are genuinely not playing, not merely muted.
    and #SOLOMASK
  .endif
    and a:h_apumask             ; enabled?
    bne :+
@psilent:
      jmp @silent               ; the shared key-off path is out of branch reach
:   lda a:APUSHADOW+0,y
    and #$10                    ; constant volume, or the envelope's level?
    beq @penv
      lda a:APUSHADOW+0,y
      and #$0F
      bra @phavevol
@penv:
    lda a:h_pedecay,y
@phavevol:
    beq @psilent                ; sounding?
    sta a:h_apuvol
    rep #$20
    .a16
    tya                         ; Y is 0 or 4; the two-byte slots want 0 or 2
    lsr a
    tax                         ; X = 0 for pulse 1, 2 for pulse 2
    lda a:APUSHADOW+2,y
    and #$07FF                  ; the period the CPU wrote
    cmp #8
    bcs :+
      jmp @silent16             ; under 8 a NES mutes the channel outright
:   sta a:h_apupitch            ; (the packet carries the period, not a pitch)
    ;  Does the sweep start over?  When the CPU wrote $4003/$4007, which the
    ;  hook recorded, or when the period moved without that -- a write to the
    ;  low byte alone.  A key-on starts it over as well; the SPC700 sees that
    ;  for itself.
    stz a:h_pkrst
    cmp a:h_swseen,x
    beq :+
      sta a:h_swseen,x
      lda #$0080
      sta a:h_pkrst
:   lda a:h_sqrst,x
    and #$00FF
    beq :+
      stz a:h_sqrst,x
      lda #$0080
      sta a:h_pkrst
:   sep #$20
    .a8
    ;  The sweep register travels in a packet of its own, sent only when it
    ;  changes -- the music driver writes $7F to it every frame -- and ahead of
    ;  the note, so a restart in this frame's packet runs on the new setting.
    lda a:APUSHADOW+1,y
    cmp a:h_swsent,y
    beq @swsame
      sta a:h_swsent,y
      sta a:APUIO2
      stz a:APUIO3
      stz a:h_apuwave           ; nothing for the doorbell's top bits
      lda #$C0                  ; both key bits: a sweep packet
      ora a:h_apuvoice
      sta a:APUIO1
      jsr apu_send
@swsame:
    lda a:APUSHADOW+0,y
    and #$C0                    ; duty, in the doorbell's top two bits; the
    sta a:h_apuwave             ;   cycle length is the SPC700's to choose
    lda a:h_apupitch
    sta a:APUIO2
    lda a:h_apupitch+1          ; the period's top three bits
    ora a:h_pkrst               ; ...and bit 7: start the sweep over
    sta a:APUIO3
    lda a:h_apuvol
    ora a:h_apuvoice
    pha
    lda a:h_apuon
    and a:h_apumask
    bne @sounding               ; already sounding: period and volume only
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
  .ifdef SOLOMASK
    ;  DEBUG: only the channels in SOLOMASK may sound ($01 pulse 1, $02 pulse 2,
    ;  $04 triangle, $08 noise).  Masking here rather than at the shadow keeps
    ;  the game's own $4015 intact and routes the silenced voices through the
    ;  normal silent path, so each gets a proper key-off and h_apuon stays
    ;  consistent -- they are genuinely not playing, not merely muted.
    and #SOLOMASK
  .endif
    and #$04
    beq @silent
    lda a:h_trilin              ; the linear counter, clocked by apu_trilin
    beq @silent                 ;   below; at zero the NES triangle is mute
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
  .ifdef SOLOMASK
    ;  DEBUG: only the channels in SOLOMASK may sound ($01 pulse 1, $02 pulse 2,
    ;  $04 triangle, $08 noise).  Masking here rather than at the shadow keeps
    ;  the game's own $4015 intact and routes the silenced voices through the
    ;  normal silent path, so each gets a proper key-off and h_apuon stays
    ;  consistent -- they are genuinely not playing, not merely muted.
    and #SOLOMASK
  .endif
    and #$08
    beq @noisesilent
    lda a:h_nzlen               ; the length counter has run out
    beq @noisesilent
    lda a:APUSHADOW+$C
    and #$10                    ; constant volume, or the envelope's level?
    beq @nzenv
      lda a:APUSHADOW+$C
      and #$0F
      bra @nzhavevol
@nzenv:
    lda a:h_nzdecay
@nzhavevol:
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

;;  One video frame of the noise channel's envelope and length counter.
;;
;;  This is the only channel the game drives with the NES's own envelope.  Its
;;  $400C writes clear the constant-volume bit -- the battle sounds write $2F,
;;  which is halt and loop set, constant clear, and a low nibble of 15 -- so
;;  that nibble is a decay period, not a level, and the level comes from the
;;  envelope.  Reading it as a volume, which is what this did, plays a flat 15
;;  where a console fades, and never stops of its own accord.
;;
;;  Clocked off the same five-step sequence as the sweep.  In that mode the
;;  envelope runs on every quarter-frame and the length counter on every
;;  half-frame, and there are exactly two quarter-frames to each half-frame --
;;  so the tick count already worked out for the sweep serves here, doubled.
.a8
.i16
apu_noiseenv:
    lda a:h_hftickn
    beq @out                    ; no half-frame fell in this video frame
    sta a:h_nztick
@half:
    jsr apu_envclk              ; two quarter-frames to every half-frame
    jsr apu_envclk
    lda a:APUSHADOW+$C
    and #$20                    ; halt: the length counter is frozen
    bne @nolen
    lda a:h_nzlen
    beq @nolen
      dec a
      sta a:h_nzlen
@nolen:
    dec a:h_nztick
    bne @half
@out:
    rts

;;  One video frame of the pulse channels' envelopes, clocked exactly as the
;;  noise one is.  Only PlaySFX_Error uses them -- see h_pedecay -- and there
;;  a $4007 write every frame restarts the level at 15 well before the decay
;;  period of 12 lets it fall, so the error sound plays at full level, where
;;  reading that 12 as a volume played it at four fifths.
.a8
.i16
apu_pulseenv:
    lda a:h_hftickn
    beq @out                    ; no half-frame fell in this video frame
    sta a:h_petick
@half:
    ldy #0
    jsr apu_penvclk             ; two quarter-frames to every half-frame
    jsr apu_penvclk
    ldy #4
    jsr apu_penvclk
    jsr apu_penvclk
    dec a:h_petick
    bne @half
@out:
    rts

;;  One quarter-frame of a pulse envelope.  Y = the channel's base in the
;;  shadow, 0 or 4, which indexes its envelope state as well.
.a8
.i16
apu_penvclk:
    lda a:h_pestart,y
    beq @run
      lda #0
      sta a:h_pestart,y         ; a $4003/$4007 write restarts it at full level
      lda #15
      sta a:h_pedecay,y
      lda a:APUSHADOW,y
      and #$0F
      sta a:h_pediv,y           ; the divider's period is that nibble plus one
      rts
@run:
    lda a:h_pediv,y
    beq @step
      dec a
      sta a:h_pediv,y
      rts
@step:
    lda a:APUSHADOW,y
    and #$0F
    sta a:h_pediv,y
    lda a:h_pedecay,y
    beq @wrap
      dec a
      sta a:h_pedecay,y
      rts
@wrap:
    lda a:APUSHADOW,y
    and #$20                    ; the halt bit doubles as the envelope's loop
    beq @done
      lda #15
      sta a:h_pedecay,y
@done:
    rts

;;  The triangle's linear counter, clocked on the same quarter-frames as the
;;  noise envelope -- two to every half-frame the accumulator handed us.
.a8
.i16
apu_trilinear:
    lda a:h_hftickn
    beq @out                    ; no half-frame fell in this video frame
    sta a:h_trtick
@half:
    jsr apu_trilin              ; two quarter-frames to every half-frame
    jsr apu_trilin
    dec a:h_trtick
    bne @half
@out:
    rts

;;  One quarter-frame of the linear counter, in the order the hardware does it:
;;  reload if the flag is set, otherwise count down; then, if the control bit
;;  is clear, drop the flag so the next clock starts the countdown.  With the
;;  control bit set -- every ordinary note -- the flag stays set, the counter
;;  reloads every clock and never reaches zero, so this changes nothing there.
.a8
.i16
apu_trilin:
    lda a:h_trirel
    beq @run
      lda a:APUSHADOW+8
      and #$7F                  ; the reload value, low seven bits
      sta a:h_trilin
      bra @ctrl
@run:
    lda a:h_trilin
    beq @ctrl
      dec a
      sta a:h_trilin
@ctrl:
    lda a:APUSHADOW+8
    and #$80                    ; control set: the reload flag stays set
    bne @out
      stz a:h_trirel
@out:
    rts

;;  One quarter-frame of the envelope.
.a8
.i16
apu_envclk:
    lda a:h_nzstart
    beq @run
      stz a:h_nzstart           ; a $400F write restarts it at full level
      lda #15
      sta a:h_nzdecay
      lda a:APUSHADOW+$C
      and #$0F
      sta a:h_nzdiv             ; the divider's period is that nibble plus one
      rts
@run:
    lda a:h_nzdiv
    beq @step
      dec a
      sta a:h_nzdiv
      rts
@step:
    lda a:APUSHADOW+$C
    and #$0F
    sta a:h_nzdiv
    lda a:h_nzdecay
    beq @wrap
      dec a
      sta a:h_nzdecay
      rts
@wrap:
    lda a:APUSHADOW+$C
    and #$20                    ; the halt bit doubles as the envelope's loop
    beq @done
      lda #15
      sta a:h_nzdecay
@done:
    rts

.a8
.i8
;;  Write the same byte to a run of consecutive PPU addresses.
;;
;;  The menus are drawn out of boxes, and every box row is a corner tile, a run
;;  of one border or body tile, and another corner -- see DrawBoxRow_Top, _Mid
;;  and _Bot, which differ only in the tiles they use.  That run went through
;;  $2007 a byte at a time, and on a subscreen transition that path is most of
;;  the cost: nt_write and the fixed overhead around it came to some 88% of an
;;  eight-frame stall.
;;
;;  A run that stays inside one row of one nametable needs none of the per-byte
;;  work repeated.  The tilemap offset just advances by two, the row never
;;  changes, and the dirty range only needs telling where the run starts and
;;  ends.  Anything else -- crossing a row, running into the attribute table,
;;  the down-a-column stride -- falls back to the ordinary conversion once per
;;  byte, which still saves the thunk and the long call around each one.
;;
;;  Entry: A = the byte, X = how many times to write it.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  hal_ntblit -- write a prepared run of nametable bytes
;;
;;  hal_ntfill's fast path, but the bytes come from NTSTAGE instead of all
;;  being the same.  A caller that would otherwise issue a row of single $2007
;;  writes -- each one a JSR to a thunk, a JSL into here, and the whole
;;  address-decode of w2007_core -- builds the row in NTSTAGE and calls this
;;  once.  The menu's repaint went from visibly stalling the music to not.
;;
;;  Two loops rather than one because the raw bytes and the tilemap words
;;  advance at different rates and the 65816 has only two index registers: the
;;  first lays the run into NESNT, the second turns NESNT into tilemap words.
;;  Both are about as tight as the fill loop they are modelled on.
;;
;;  Entry: X = how many bytes, NTSTAGE holding them.  Same guards as ntfill --
;;  anything it would refuse falls back to the per-byte conversion.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_ntblit:
    php
    pha
    phx
    phy
    ENTER16
    txa
    and #$00FF
    sta a:h_fillcnt
    bne @guards
    jmp @out
@toslow:
    jmp @slow
@guards:
    lda a:h_ppuctrl
    and #$0004
    bne @toslow                 ; writing down a column, not along a row
    lda a:h_addr
    and #$3FFF
    cmp #$2000
    bcc @toslow
    cmp #$3F00
    bcs @toslow
    and #$07FF
    sta a:h_t1
    and #$03FF
    cmp #$03C0
    bcs @toslow                 ; attribute table
    sta a:h_t2
    and #$001F
    sta a:h_fillcol
    clc
    adc a:h_fillcnt
    cmp #33
    bcs @toslow                 ; the run would leave the row

    lda a:h_t2
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta a:h_row
    lda a:h_t1
    and #$0400
    beq :+
      lda a:h_fillcol
      clc
      adc #32
      sta a:h_fillcol
:   lda a:h_t1
    clc
    adc a:h_fillcnt
    sta a:h_t2                  ; where the raw-byte index stops


;;  the staged bytes into the raw nametable, then the raw nametable into the
;;  tilemap words.  DBR = $7E for both: low WRAM, NESNT and NTSHADOW all live
;;  in that bank, so everything is absolute and X and Y are both free.  Long
;;  indexed addressing would have pinned one of them, because the 65816 has
;;  "long,x" and no "long,y".
    phb
    ;  The staged run into the raw nametable, as a block move rather than a
    ;  loop.  Both ends are WRAM, so each byte costs two slow accesses either
    ;  way -- what MVN saves is everything around them: the compare against a
    ;  count held in WRAM, the branch, and the two increments.  Measured on a
    ;  menu scroll, the pair of loops here was the single most expensive thing
    ;  in the frame.
    ;
    ;  ca65 writes MVN source first and assembles it destination first, and
    ;  taking the operands as addresses rather than banks is silent -- "mvn
    ;  $7E, $7E" assembles to "54 00 00".  Both banks are $7E here whichever
    ;  way round it is read, which is one less thing to get wrong.
    ldx #NTSTAGE_A
    lda a:h_t1
    clc
    adc #(NESNT & $FFFF)
    tay
    lda a:h_fillcnt             ; MVN moves A+1 bytes, and the count is known
    dec a                       ;   nonzero: zero took the early exit above
    mvn #^NTSTAGE, #^NESNT

    ;  MVN leaves DBR at the destination bank, which is the $7E the loop below
    ;  wants for NESNT, NTSHADOW and the HAL's own variables alike.  It used to
    ;  be set by hand here, with a note that the push had to be eight bits wide
    ;  or it leaked a byte of stack; the block move removes the question.
    lda a:h_row
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; row * 128
    clc
    adc a:h_fillcol
    adc a:h_fillcol             ; + column * 2
    tay
    ldx a:h_t1
    sep #$20
    .a8
@word:
    lda a:NESNT & $FFFF,x
    sta a:NTSHADOW,y
    inx
    iny
    iny
    cpx a:h_t2
    bcc @word
    rep #$20
    .a16
    plb

    stz a:h_col+1
    lda a:h_fillcol
    sta a:h_col
    jsr mark_dirty8
    rep #$20
    .a16
    lda a:h_fillcol
    clc
    adc a:h_fillcnt
    dec a
    sta a:h_col
    sep #$20
    .a8
    jsr mark_dirty8
    rep #$20
    .a16
    lda a:h_addr
    clc
    adc a:h_fillcnt
    sta a:h_addr
@out:
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

@slow:
    ldy #$0000
:   sep #$20
    .a8
    phx
    tyx
    lda f:NTSTAGE,x
    plx
    sta a:h_data
    rep #$20
    .a16
    phy
    jsr w2007_core
    ply
    iny
    cpy a:h_fillcnt
    bcc :-
    LEAVE16
    ply
    plx
    pla
    plp
    rtl


.a8
.i8
hal_ntfill:
    php
    pha
    phx
    phy
    sta a:h_data
    ENTER16
    txa
    and #$00FF
    sta a:h_fillcnt             ; the count, kept for the address at the end
    bne @guards
    jmp @out
@toslow:                        ; the fast path below is past a branch's reach
    jmp @slow
@guards:
    lda a:h_ppuctrl
    and #$0004
    bne @toslow                 ; writing down a column, not along a row
    lda a:h_addr
    and #$3FFF
    cmp #$2000
    bcc @toslow                 ; pattern tables
    cmp #$3F00
    bcs @toslow                 ; palette
    and #$07FF
    sta a:h_t1                  ; index into the pair of nametables
    and #$03FF
    cmp #$03C0
    bcs @toslow                 ; attribute table
    sta a:h_t2                  ; index within this one
    and #$001F
    sta a:h_fillcol             ; column the run starts at
    clc
    adc a:h_fillcnt
    cmp #33
    bcs @toslow                 ; the run would leave the row
    ;  Fast path: work the row's place in the tilemap out once.
    lda a:h_t2
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta a:h_row                 ; 0..29
    lda a:h_t1
    and #$0400
    beq :+
      lda a:h_fillcol
      clc
      adc #32                   ; the right-hand nametable's columns
      sta a:h_fillcol
:   lda a:h_row
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                       ; row * 128
    clc
    adc a:h_fillcol
    adc a:h_fillcol             ; + column * 2
    tay                         ; Y walks the tilemap
    lda a:h_t1
    clc
    adc a:h_fillcnt
    sta a:h_t2                  ; where the raw-byte index has to stop
    ldx a:h_t1                  ; X walks the raw NES bytes
    sep #$20
    .a8
@fill:
    lda a:h_data
    sta f:NESNT,x               ; the byte, kept for readback and attributes
    sta a:NTSHADOW,y            ; and the tile number in the tilemap word
    inx
    iny
    iny
    cpx a:h_t2                  ; the index registers carry the loop, so the
    bcc @fill                   ;   accumulator never changes width in here
    ;  Both ends of the run are enough: mark_dirty keeps a low and a high water
    ;  mark for the row, so everything between them is covered.
    stz a:h_col+1
    lda a:h_fillcol
    sta a:h_col
    jsr mark_dirty8
    rep #$20
    .a16
    lda a:h_fillcol
    clc
    adc a:h_fillcnt
    dec a                       ; the last column the run touched
    sta a:h_col
    sep #$20
    .a8
    jsr mark_dirty8
    rep #$20
    .a16
@advance:
    lda a:h_addr                ; where the same number of single writes would
    clc                         ;   have left it
    adc a:h_fillcnt
    sta a:h_addr
@out:
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

@slow:
    jsr w2007_core              ; the ordinary conversion, which advances h_addr
    lda a:h_fillcnt
    dec a
    sta a:h_fillcnt
    bne @slow
    LEAVE16
    ply
    plx
    pla
    plp
    rtl

;;  Clear the left-hand nametable, as bank_0E's ClearNT does it.
;;
;;  That routine writes 1024 bytes through $2007 -- 960 zero tiles then 64
;;  attribute bytes of $FF -- and every one of them went through the whole
;;  per-write path: a thunk, a long call, five pushes, two mode flips, the
;;  address decode, the tilemap conversion and the dirty-range update, some 210
;;  cycles a byte where a NES spends four.  A screen clear on its own is more
;;  than three frames, and the menus clear the screen constantly: it is most of
;;  why confirming a name in party creation stalls for a quarter of a second
;;  with the music stopped.
;;
;;  Done in bulk it is nearly free, because the result is uniform.  Every tile
;;  byte is zero and every attribute byte is $FF, which is palette 3 in all
;;  four of its quadrants, so every tilemap word comes out the same: tile 0 in
;;  the low byte, palette 3 shifted into place in the high byte.  So there is
;;  nothing to convert -- just three fills and the dirty ranges.
;;
;;  Exit state matches the loop it replaces: the PPU address has advanced the
;;  full $400 to $2400 and the $2006 toggle is clear, which is where two
;;  address writes leave it.
.a8
.i8
hal_clearnt:
    php
    ENTER16
    ;  the raw NES bytes, kept for readback and for attribute conversion
    ldx #$0000
    lda #$0000
@zero:
    sta f:NESNT,x
    inx
    inx
    cpx #$03C0
    bcc @zero
    lda #$FFFF
@attr:
    sta f:NESNT,x
    inx
    inx
    cpx #$0400
    bcc @attr
    ;  the tilemap: rows 0..29, columns 0..31 of a 64-wide map, so a row is 64
    ;  bytes of the 128 and the right-hand nametable is left alone
    ldx #$0000
    ldy #30
@row:
    lda #NT_CLEARWORD
  .repeat 32
    sta a:NTSHADOW,x
    inx
    inx
  .endrepeat
    txa
    clc
    adc #64                     ; step over the other nametable's half of the row
    tax
    dey
    beq @rowsdone
    jmp @row                    ; the unrolled body is past a branch's reach
@rowsdone:
    ;  every row is dirty from column 0 to column 31
    sep #$20
    .a8
    ldx #$00
@dirty:
    stz a:NTCOLLO,x
    lda a:NTCOLHI,x
    cmp #31
    bcs :+
      lda #31
      sta a:NTCOLHI,x
:   inx
    cpx #30
    bcc @dirty
    lda #1
    sta a:h_ntdirty
    stz a:h_latch               ; two address writes leave the toggle clear
    rep #$20
    .a16
    lda #$2400                  ; $2000 plus the $400 bytes written
    sta a:h_addr
    LEAVE16
    plp
    rtl

;;  A write to a pulse or triangle high-timer register, pushed to the SPC700
;;  at once if it has just silenced the channel.
;;
;;  Zeroing a channel's timer is how the driver silences it -- Music_NewSong
;;  writes $4002/3, $4006/7, $400A/B and then the volumes, and its own comment
;;  says the timer writes are what "in effect silences the squares".  They do,
;;  on a NES, because the hardware mutes a pulse whose timer is under 8 the
;;  instant it is written.  Here it only took effect at the next frame, and at
;;  a transition the next frame can be twenty away, so the note hung across
;;  the black gap.  Some transitions also write $4015 and were already caught
;;  by the hook below; those that only zero timers were not, which is why the
;;  fault came and went depending on which way the screen changed.
;;
;;  The check is made here rather than in the macro: the banks have no room,
;;  and this way the expensive part runs only when a channel actually goes
;;  quiet, not on every note the driver plays.
;;
;;  The pulse hooks also record that the write happened.  On a NES, writing
;;  $4003 or $4007 restarts the channel's envelope and sets its period afresh,
;;  so a sweep starts over from the value written -- and that holds even when
;;  the bytes are the same ones as last time, which the shadow cannot show.
;;  PlaySFX_Error depends on exactly that: it writes identical bytes sixteen
;;  frames running, and on a console each write restarts the tone.
.a8
.i8
hal_w4003:
    sta a:APUSHADOW+$03
    php
    pha
    phx
    lda #1
    sta a:h_sqrst               ; the sweep starts over from this period
    sta a:h_pestart             ; ...and the envelope from full level
    lda a:APUSHADOW+$03         ; apu_ifmuted wants the value that was written
    ldx #$02
    bra apu_ifmuted
hal_w4007:
    sta a:APUSHADOW+$07
    php
    pha
    phx
    lda #1
    sta a:h_sqrst+2
    sta a:h_pestart+4
    lda a:APUSHADOW+$07
    ldx #$06
    bra apu_ifmuted
hal_w400b:
    sta a:APUSHADOW+$0B
    php
    pha
    phx
    ;  On a NES a write here also sets the triangle's linear-counter reload
    ;  flag; the countdown itself is clocked in apu_trilin.  The driver writes
    ;  $400B once per triangle note, so the flag has a source.
    lda #1
    sta a:h_trirel
    lda a:APUSHADOW+$0B         ; apu_ifmuted wants the value that was written
    ldx #$0A
apu_ifmuted:
    and #$07                    ; the high three bits of the eleven-bit timer
    bne @out                    ; set at all means 256 or more: still sounding
    lda a:APUSHADOW,x           ; low byte; under 8 a NES mutes the channel
    cmp #8
    bcs @out
      phy
      jsr hal_apu_frame
      ply
@out:
    plx
    pla
    plp
    rtl

;;  A write to $400F: the noise channel's length counter load, which on a NES
;;  also sets the envelope's start flag so the next quarter-frame restarts it
;;  at full level.  Nothing is pushed to the SPC700 from here -- this can only
;;  make the channel louder or longer, never silent, so the frame's own call
;;  is soon enough.
.a8
.i8
hal_w400f:
    sta a:APUSHADOW+$0F
    php
    pha
    phx
    lda #1
    sta a:h_nzstart
    lda a:APUSHADOW+$15
    and #$08
    beq @out                    ; the channel is disabled: the counter stays 0
    lda a:APUSHADOW+$0F
    lsr a
    lsr a
    lsr a                       ; the top five bits index the length table
    tax
    lda f:apulen + HALFAR,x
    sta a:h_nzlen
@out:
    plx
    pla
    plp
    rtl

;;  A write to $4015, the channel enable register, pushed to the SPC700 at
;;  once instead of waiting for the next frame.
;;
;;  Sound is otherwise sent from hal_waitvbl, once per frame, which is fine
;;  while the game is drawing frames.  It is not fine across a transition: the
;;  game blacks the screen, writes $4015 = 0 to silence every channel, and
;;  then spends a dozen frames loading CHR and filling nametables without
;;  asking for vblank once.  Nothing pushed the silence in all that time, so
;;  the SPC700 held the last note through the gap -- audible as a note hanging
;;  over the middle of the screen wipe, where a console is silent, because a
;;  console's APU takes the write the instant it is made.
;;
;;  Hooked here rather than at the writes to the timer or volume registers
;;  because this is the one that means "stop": it is written once at a
;;  transition, where those are written constantly by the music driver.
.a8
.i8
hal_w4015:
    sta a:APUSHADOW+$15         ; the store the macro would have done itself
    php
    pha
    and #$08
    bne :+
      stz a:h_nzlen             ; clearing a channel's bit clears its length
:   phx
    phy
    jsr hal_apu_frame
    ply
    plx
    pla
    plp
    rtl

;;  Hand the packet on the data ports to the SPC700 and wait for it to be
;;  taken.  Called with A eight bits wide and in either index width, so the
;;  bounded-wait counter lives in memory rather than an index register.
apu_send:
    ;  Port 0 is the handshake: the SPC700 acts when it changes and echoes it
    ;  back.  Only enough of it has to change to be noticed, so three bits are
    ;  the sequence and the top five carry the waveform index -- which saves a
    ;  second packet per note, and there was nowhere left in ports 1-3 anyway.
    ;
    ;  The wait is 2048 polls, about 8ms.  It was 256, against the few dozen
    ;  cycles the SPC700 then took to answer, but it now runs the pulses'
    ;  sweep units between packets, and a packet that lands during a sweep
    ;  step waits for it -- up to about a millisecond while an effect sweeps.
    ;  256 polls is a millisecond, so the first such collision read as a dead
    ;  SPC700 and the game went silent for good.  This only bounds a failure;
    ;  an answering SPC700 ends the wait as soon as it answers.
    lda #8
    sta a:h_apuwaithi
    stz a:h_apuwait
    inc a:h_apuseq
    lda a:h_apuseq
    and #$07
    ora a:h_apuwave
    sta a:APUIO0
@wait:
    cmp a:APUIO0
    beq @ok
    dec a:h_apuwait
    bne @wait
    dec a:h_apuwaithi
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
    ;  Registers nothing in the port turns on, set to off rather than left as
    ;  power-up found them, which on a console is not promised to be zero.
    ;  Mosaic would act on BG1 directly; the windows only once TMW or TSW
    ;  enables them, but those are among the unwritten too.  The credits
    ;  screen is the one thing that may change any of them, and it hands the
    ;  PPU back through here.
    stz a:MOSAIC
    stz a:W12SEL
    stz a:W34SEL
    stz a:WOBJSEL
    stz a:WBGLOG
    stz a:WOBJLOG
    stz a:TMW
    stz a:TSW
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
    ;  Both of these are read before anything writes them, and a combo left in
    ;  h_joyauxprev by power-on WRAM would reset the game during the boot that
    ;  read it.  Same trap as NESPALPREV and the OAM high table above.
    stz a:h_joyaux
    stz a:h_joyauxprev
    stz a:h_padreset
    stz a:h_rastercount
    stz a:h_emphasis
    stz a:h_greyscale
    ;  Audio state.  WRAM comes up arbitrary on a console, and these are read
    ;  before anything writes them: a stray h_nzlen would sound the noise
    ;  channel for up to two and a half seconds at boot.
    stz a:h_nzdecay
    stz a:h_nzdiv
    stz a:h_nzstart
    stz a:h_nzlen
    stz a:h_nztick
    stz a:h_trilin
    stz a:h_trirel
    stz a:h_trtick
    stz a:h_altaron
    stz a:h_altarframe
    stz a:h_apufull
    stz a:h_pestart
    stz a:h_pediv
    stz a:h_pedecay
    stz a:h_pestart+4
    stz a:h_pediv+4
    stz a:h_pedecay+4
    stz a:h_petick
    stz a:h_hfacc
    stz a:h_hfacc+1
    stz a:h_hftickn
    stz a:h_hftickn+1
    ldx #0
:   stz a:h_swseen,x            ; two bytes per pulse channel, four channels'
    stz a:h_sqrst,x             ;   worth of slots: clear the lot
    inx
    cpx #4
    bcc :-
    lda #$FF                    ; what the SPC700's sweep registers start as,
    sta a:h_swsent              ;   so the two sides agree until the first
    sta a:h_swsent+4            ;   real value goes over
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

    ;  ...and clear the 32-byte high table behind them.  flush_oam DMAs 544
    ;  bytes: the 512-byte table above, then two bits per sprite holding the
    ;  ninth bit of X and the size select.  Nothing else in the port ever
    ;  writes those 32 bytes -- hal_oamdma stops at 256, having only 64 NES
    ;  sprites to convert -- so until now they were whatever WRAM powered up
    ;  holding, DMA'd into OAM every frame.
    ;
    ;  Zero is not a compromise here, it is the right answer for both fields.
    ;  The NES's OAM X is eight bits, so the ninth is always clear -- as
    ;  hal_oamdma's own comment says -- and the game uses 8x8 sprites
    ;  throughout, which is the small size OBSEL is set up for.  A set size bit
    ;  turns a sprite into a 16x16 drawing tiles N, N+1, N+16 and N+17, which
    ;  for a menu character reaches a row further into the CHR than the pose
    ;  occupies; a set X bit moves it 256 pixels, off the screen.
    ;
    ;  This is the same trap as NESPALPREV above, and it hid the same way.
    ;  Reset does not clear a console's WRAM and power-on contents are largely
    ;  repeatable, so the fault comes back identically across resets and power
    ;  cycles; an emulator hands out zeroed WRAM, which is exactly correct, so
    ;  neither ares nor Mesen can show it.
    ldx #0
@hitable:
    stz a:OAMSHADOW+512,x
    inx
    inx
    cpx #32
    bcc @hitable

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

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Clear the ending scene's draw buffer
;;
;;  'The End' keeps a RAM shadow of the CHR it is plotting into, because each
;;  pixel is a read-modify-write.  That buffer moved to WRAM bank $7F when the
;;  page it used to sit on in PRG-RAM was wanted for the option block, and the
;;  loop that used to clear it is here rather than in bank $0D because that
;;  bank is full to the byte -- the four-byte call site replaces twenty-eight
;;  bytes of loop, which is what made the move fit at all.
;;
;;  $700 bytes, so $380 words.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_theendclear:
    php
    ENTER16
    phx
    ldx #$0700 - 2
    lda #$0000
:   sta f:THEENDBANK * $10000 + THEENDBUF, x
    dex
    dex
    bpl :-
    plx
    LEAVE16
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Set one pixel in the ending scene's draw buffer
;;
;;  The plotter's read-modify-write, which used to be an ORA/STA pair through
;;  (bufaddr),Y.  That pair resolves through the data bank, and the buffer is
;;  no longer in a bank the game runs in, so the access comes here instead.
;;
;;  Entry: A = the pixel mask, direct page $66/$67 = the buffer address.
;;  Exit:  A = the merged byte, which the caller goes on to write to $2007.
;;
;;  Long-indirect [$66],Y would have been the obvious encoding and is the same
;;  two bytes, but it needs a third direct-page byte at $68 -- and $68 is
;;  sm_player_x.  Indexing an absolute-long address by a 16-bit X avoids
;;  borrowing anything.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_theendplot:
    php
    ENTER16
    phx
    ldx $66                     ; the 16-bit buffer address from direct page
    sep #$20
    .a8                         ; A's low byte is still the caller's mask
    ora f:THEENDBANK * $10000, x
    sta f:THEENDBANK * $10000, x
    rep #$20
    .a16
    plx
    LEAVE16
    plp
    rtl

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Test a pixel in the ending scene's draw buffer
;;
;;  The fill pass walks left from the outline setting pixels until it runs into
;;  one that is already set -- the "left wall".  That test is a *read* of the
;;  buffer, which is what distinguishes this from hal_theendplot: the outline
;;  pass only ever writes, so moving the buffer to WRAM left phase one working
;;  and phase two drawing its fills through walls that were no longer there.
;;
;;  Entry: A = the pixel mask, direct page $66/$67 = the buffer address.
;;  Exit:  A = mask AND buffer, with N and Z set from it -- the caller branches
;;         on Z -- and X preserved, because the caller still needs it to index
;;         the mask table.
;;
;;  The result goes through h_t0 on the way out so that the PLX which restores
;;  the caller's X cannot be the last thing to touch the flags.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.a8
.i8
hal_theendand:
    ENTER16
    phx
    ldx $66                     ; the 16-bit buffer address from direct page
    sep #$20
    .a8
    and f:THEENDBANK * $10000, x
    sta a:h_t0
    rep #$20
    .a16
    plx
    LEAVE16
    lda a:h_t0                  ; reload, so N and Z come from the result
    rtl
