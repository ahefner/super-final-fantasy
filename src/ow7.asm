; ---------------------------------------------------------------------------
;  ow7.asm -- the overworld in Mode 7 (CHUNK_OW7)
;
;  The overworld's picture is a Mode 7 plane, not the NES nametables, seen
;  through a camera tilted back from the NES's straight-down view (genm7.py
;  has the geometry and the angles).  The game is unchanged: it moves the
;  party, scrolls and keeps its sixteen map rows at mapdata as ever, and
;  four hooks in the fixed bank bring its view here:
;
;    m7_rowcol   DrawMapRowCol, on the overworld: nothing.  The plane is
;                drawn here, from the rows in M7RING, and the nametables and
;                the attributes (hal_drawattr) are left alone.
;    m7_scroll   SetOWScroll: the plane's scroll, and the pivot -- the
;                centre of the player's tile, where the party and the
;                airship's shadow stand -- on the plane for M7X and M7Y.
;                Then whatever row or column the view has just come to,
;                drawn (m7_sync), and R stepping the angle (for now).
;    m7_enter    PrepOverworld's end: the plane's characters if VRAM lost
;                them, every row and column the view can see, and the
;                plane on (h_m7on).
;    m7_objpos   ConvertOWToSprite: the ship, the parked airship, the
;                bridge and the canal, placed where the tilted plane shows
;                their tiles, as far out as it sees; the game's
;                placing at the flat angle.
;
;  The plane is 128x128 characters, 64x64 metatiles: map metatile (x, y)
;  sits at plane metatile (x mod 64, y mod 64), and the plane wraps exactly
;  as the map does.  It keeps M7_NORTH rows north of the pivot's tile to
;  M7_SOUTH south, M7_WEST columns west to M7_EAST east: all any angle
;  shows, with one to spare.  They are drawn from M7RING, the map's rows
;  decoded whole (ow_rowring, the map-edit chunk), row r in page r mod 32:
;  the steepest angle sees farther north than the game's sixteen rows.  The
;  plane goes off with the first $2001 write with rendering off
;  (hal_w2001), which is how every way off the overworld begins; mode 1's
;  picture was never touched, so it is there for whatever follows.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.import ow_rowring, hal_m7sendq
.export m7_rowcol, m7_scroll, m7_enter, m7_objpos
.export lut_M7Row, lut_M7Col            ; for tools/test_options.py
.export lut_M7PA, lut_M7PD, lut_M7PRG, lut_M7PB, lut_M7PK, lut_M7PY

.segment "BANK_OW7"

.include "ow7.inc"

M7_ROWS   = M7_NORTH + M7_SOUTH + 1     ; the rows the plane keeps drawn...
M7_COLS   = M7_WEST + M7_EAST + 1       ; ...and the columns
.assert M7_ROWS <= M7RING_ROWS, error, "the plane keeps more rows than the ring"
.assert M7_COLS <= 64 && M7_ROWS <= 64, error, "the plane keeps more than it has"

;  A row's or a column's room in the queue: two lines, each split in two at
;  the plane's edge (4 bytes a record), two bytes a metatile.
M7_WORST  = 2 * (2 * 4 + 2 * 32)
.assert M7_COLS <= 32 && M7_ROWS <= 32, error, "M7_WORST counts 32 metatiles a line"

M7_ROW    = $00                         ; VMAIN: a byte a word along
M7_COL    = $02                         ; VMAIN: a byte 128 words down
RING      = M7RING & $FFFF              ; the ring and the queue, by DBR $7E
RINGEND   = RING + M7RING_ROWS * $100
QUEUE     = M7QUEUE & $FFFF
.assert ^M7RING = ^M7QUEUE, error, "the ring and the queue share a bank"


.a8
.i8
;;  From DrawMapRowCol (ow7_rowcol.patch), emulation mode.  On the
;;  overworld, carry set: nothing for the nametables, the plane being drawn
;;  by m7_sync.  In a standard map carry clear, and DrawMapRowCol draws as
;;  ever.
m7_rowcol:
    LDA z:mapflags
    LSR A
    BCC :+
    CLC
    RTL
:   SEC
    RTL


;;  From SetOWScroll's end (ow7_scroll.patch), emulation mode: the plane's
;;  scroll, the position the game just gave the PPU -- ow_scroll_x and _y
;;  in metatiles, move_ctr_x and _y the pixels between them -- as pixels on
;;  the 1024-pixel plane, down by NES_TOP_CROP - 1 as flush_scroll puts
;;  BG1VOFS; and the pivot on the plane, M7X and M7Y, at its column and
;;  line on screen (the hardware's line is the screen's + 1).  With the
;;  plane up, R and the rows and columns.  Everything kept.
m7_scroll:
    PHP
    PHA
    PHX
    PHY
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA z:ow_scroll_x
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7hofs
    LDA z:move_ctr_x
    AND #$00FF
    CLC
    ADC a:h_m7hofs
    AND #$03FF
    STA a:h_m7hofs
    CLC
    ADC #M7P_PIVOTX
    STA a:h_m7cx
    LDA z:ow_scroll_y
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7vofs
    LDA z:move_ctr_y
    AND #$00FF
    CLC
    ADC #NES_TOP_CROP - 1
    ADC a:h_m7vofs
    AND #$03FF
    STA a:h_m7vofs
    CLC
    ADC #M7P_PIVOTLINE + 1
    STA a:h_m7cy
    SEP #$20
    .a8
    LDA a:h_m7on
    BEQ :+
    JSR m7_step
    JSR m7_sync
:   SEP #$30
    .i8
    SEC
    XCE
    PLY
    PLX
    PLA
    PLP
    RTL


.a8
.i16
;;  R steps the angle, on its press (h_m7rprev a frame's R, so a second
;;  call in one frame does nothing).  A tool for choosing one, until a
;;  setting does.
m7_step:
    LDA a:h_joyaux
    AND #JOYAUX_R
    CMP a:h_m7rprev
    BEQ @same
    STA a:h_m7rprev
    CMP #0
    BEQ @same                   ; let go
    LDA a:h_m7lvl
    CMP #M7P_ANGLES             ; (the angle + 1: past the last, the first)
    BCC :+
    LDA #0
:   INC A
    STA a:h_m7lvl
    JSR m7_tables
@same:
    RTS


;;  The angle's tables, into h_m7tabA and the rest; the angle the default
;;  before the first way in has set one (h_m7lvl 0: power-on's WRAM).  A8
;;  I16 in and out.
m7_tables:
    LDA a:h_m7lvl
    BNE :+
    LDA #M7P_DEFAULT + 1
    STA a:h_m7lvl
:   REP #$20
    .a16
    AND #$00FF
    DEC A
    ASL A
    TAX
    LDA f:OW7FAR + lut_M7PA, X
    STA a:h_m7tabA
    LDA f:OW7FAR + lut_M7PD, X
    STA a:h_m7tabD
    LDA f:OW7FAR + lut_M7PRG, X
    STA a:h_m7tabRG
    LDA f:OW7FAR + lut_M7PB, X
    STA a:h_m7tabB
    LDA f:OW7FAR + lut_M7PK, X
    STA a:h_m7tabK
    LDA f:OW7FAR + lut_M7PY, X
    STA a:h_m7tabY
    SEP #$20
    .a8
  .if M7P_FOGSUB
    LDA #$A1                    ; subtract the fixed colour from BG1 and the backdrop
  .else
    LDA #$21                    ; add it
  .endif
    STA a:h_m7math
    RTS


;;  The tile the pivot is in, from the game's scroll: h_m7ntx, h_m7nty.
;;  A8 I16 in and out.
m7_pivot:
    REP #$20
    .a16
    LDA z:ow_scroll_x
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7n
    LDA z:move_ctr_x
    AND #$00FF
    CLC
    ADC a:h_m7n
    ADC #M7P_PIVOTX
    LSR A
    LSR A
    LSR A
    LSR A
    SEP #$20
    .a8
    STA a:h_m7ntx
    REP #$20
    .a16
    LDA z:ow_scroll_y
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7n
    LDA z:move_ctr_y
    AND #$00FF
    CLC
    ADC a:h_m7n
    ADC #M7P_PIVOTLINE + NES_TOP_CROP
    LSR A
    LSR A
    LSR A
    LSR A
    SEP #$20
    .a8
    STA a:h_m7nty
    RTS


;;  The plane caught up with the pivot: a step onto a new tile brings in
;;  the column M7_EAST or M7_WEST of it, or the row M7_NORTH or M7_SOUTH,
;;  into the queue for the next flush.  One at a time: the game moves a
;;  tile at a time, in one direction.  No room in the queue (frames without
;;  a flush), and it waits for the next call.  A8 I16.
m7_sync:
    JSR m7_pivot
    REP #$20
    .a16
    LDA a:h_m7qlen
    CMP #M7QUEUE_CAP - M7_WORST + 1
    SEP #$20
    .a8
    BCS @rts
    LDA a:h_m7ntx
    SEC
    SBC a:h_m7tx
    BEQ @rows
    CMP #$01
    BEQ @east
    CMP #$FF
    BEQ @west
    LDA a:h_m7ntx               ; farther: nothing moves so, but never draw
    STA a:h_m7tx                ;   from the wrong place
    BRA @rows
@east:
    LDA a:h_m7ntx
    STA a:h_m7tx
    CLC
    ADC #M7_EAST
    BRA @col
@west:
    LDA a:h_m7ntx
    STA a:h_m7tx
    SEC
    SBC #M7_WEST
@col:
    REP #$20
    .a16
    AND #$00FF
    STA a:h_m7x
    LDA a:h_m7ty
    AND #$00FF
    SEC
    SBC #M7_NORTH
    AND #$00FF
    STA a:h_m7row
    LDA #M7_ROWS
    STA a:h_m7cnt
    JSR m7_drawcol
    SEP #$20
    .a8
@rows:
    LDA a:h_m7nty
    SEC
    SBC a:h_m7ty
    BEQ @rts
    CMP #$01
    BEQ @south
    CMP #$FF
    BEQ @north
    LDA a:h_m7nty
    STA a:h_m7ty
@rts:
    RTS
@south:
    LDA a:h_m7nty
    STA a:h_m7ty
    CLC
    ADC #M7_SOUTH
    BRA m7_newrow
@north:
    LDA a:h_m7nty
    STA a:h_m7ty
    SEC
    SBC #M7_NORTH
    ;  (on into m7_newrow)

;;  Map row A, decoded into the ring and drawn across the columns kept.
;;  A8 I16.
m7_newrow:
    REP #$20
    .a16
    AND #$00FF
    STA a:h_m7row
    SEP #$20
    .a8
    JSR m7_decode
    REP #$20
    .a16
    LDA a:h_m7tx
    AND #$00FF
    SEC
    SBC #M7_WEST
    AND #$00FF
    STA a:h_m7x
    LDA #M7_COLS
    STA a:h_m7cnt
    JSR m7_drawrow
    SEP #$20
    .a8
    RTS


;;  Map row h_m7row into its page of the ring (ow_rowring, by JSL in
;;  emulation mode), the game's tmp..tmp+5 kept across it: SetOWScroll's
;;  callers may have something there.  A8 I16 in and out.
m7_decode:
    REP #$20
    .a16
    LDA z:tmp
    STA a:h_m7save
    LDA z:tmp+2
    STA a:h_m7save+2
    LDA z:tmp+4
    STA a:h_m7save+4
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    LDA a:h_m7row
    AND #M7RING_ROWS - 1
    CLC
    ADC #>RING
    TAX                         ; the row's page
    LDA a:h_m7row
    JSL ow_rowring + WORLDFAR
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA a:h_m7save
    STA z:tmp
    LDA a:h_m7save+2
    STA z:tmp+2
    LDA a:h_m7save+4
    STA z:tmp+4
    SEP #$20
    .a8
    RTS


.a16
.i16
;;  Row h_m7row, h_m7cnt metatiles from column h_m7x, into the queue: two
;;  lines of characters, the upper (UL, UR) and the lower (DL, DR) 128 words
;;  below, each split where it wraps past the plane's column 127.  A16 I16.
m7_drawrow:
    PHB
    SEP #$20
    .a8
    LDA #^M7RING
    PHA
    PLB
    REP #$20
    .a16
    STZ a:h_m7line
    JSR @line
    LDA #2
    STA a:h_m7line
    JSR @line
    PLB
    RTS
@line:
    LDA a:h_m7row
    AND #$003F
    XBA                         ; * 256 words: the plane's two rows of it
    LDX a:h_m7line
    BEQ :+
    ORA #$0080
:   STA a:h_m7addr
    LDA a:h_m7x
    STA a:h_m7left
    LDA a:h_m7cnt
    STA a:h_m7n
@piece:
    LDA a:h_m7left
    AND #$003F
    STA a:h_m7pc                ; (the plane's column, for now)
    ASL A
    ORA a:h_m7addr
    LDY a:h_m7qlen
    STA a:QUEUE, Y              ; the record: where...
    LDA a:h_m7row
    AND #M7RING_ROWS - 1
    XBA
    ORA a:h_m7left
    CLC
    ADC #RING
    TAX                         ; (the ring's byte for the first metatile)
    LDA #64
    SEC
    SBC a:h_m7pc
    CMP a:h_m7n
    BCC :+
    LDA a:h_m7n
:   STA a:h_m7pc                ; the piece: to the plane's edge, or the end
    PHA
    ASL A                       ; two characters a metatile
    XBA
    ORA #M7_ROW
    STA a:QUEUE + 2, Y          ; ...VMAIN, and how many
    INY
    INY
    INY
    INY
@meta:
    LDA a:$0000, X              ; the metatile, from the ring
    AND #$007F
    ASL A
    ASL A
    ORA a:h_m7line
    PHX
    TAX
    LDA f:OW7FAR + lut_M7Row, X ; its two characters on this line
    PLX
    STA a:QUEUE, Y
    INY
    INY
    INX                         ; (a piece ends at a multiple of 64: never
    DEC a:h_m7pc                ;   past the ring row's 256)
    BNE @meta
    STY a:h_m7qlen
    PLA
    STA a:h_m7pc
    LDA a:h_m7left
    CLC
    ADC a:h_m7pc
    AND #$00FF                  ; the map wraps at 256
    STA a:h_m7left
    LDA a:h_m7n
    SEC
    SBC a:h_m7pc
    STA a:h_m7n
    BEQ :+
    JMP @piece
:   RTS


;;  Column h_m7x, h_m7cnt metatiles from row h_m7row down, into the queue:
;;  two columns of characters, the left (UL, DL) and the right (UR, DR),
;;  each split where it wraps past the plane's row 127.  A16 I16.
m7_drawcol:
    PHB
    SEP #$20
    .a8
    LDA #^M7RING
    PHA
    PLB
    REP #$20
    .a16
    STZ a:h_m7line
    JSR @line
    LDA #2
    STA a:h_m7line
    JSR @line
    PLB
    RTS
@line:
    LDA a:h_m7x
    AND #$003F
    ASL A                       ; the plane's column: (x mod 64) * 2...
    LDX a:h_m7line
    BEQ :+
    INC A                       ; ...+ 1 the right
:   STA a:h_m7addr
    LDA a:h_m7row
    STA a:h_m7left
    LDA a:h_m7cnt
    STA a:h_m7n
@piece:
    LDA a:h_m7left
    AND #$003F
    STA a:h_m7pc                ; (the plane's metatile row, for now)
    XBA                         ; * 256 words
    ORA a:h_m7addr
    LDY a:h_m7qlen
    STA a:QUEUE, Y
    LDA a:h_m7left
    AND #M7RING_ROWS - 1
    XBA
    ORA a:h_m7x
    CLC
    ADC #RING
    TAX
    LDA #64
    SEC
    SBC a:h_m7pc
    CMP a:h_m7n
    BCC :+
    LDA a:h_m7n
:   STA a:h_m7pc
    PHA
    ASL A
    XBA
    ORA #M7_COL
    STA a:QUEUE + 2, Y
    INY
    INY
    INY
    INY
@meta:
    LDA a:$0000, X
    AND #$007F
    ASL A
    ASL A
    ORA a:h_m7line
    PHX
    TAX
    LDA f:OW7FAR + lut_M7Col, X
    PLX
    STA a:QUEUE, Y
    INY
    INY
    TXA
    CLC
    ADC #$0100                  ; the next row's page...
    CMP #RINGEND
    BCC :+
    SBC #M7RING_ROWS * $100     ; ...round the ring
:   TAX
    DEC a:h_m7pc
    BNE @meta
    STY a:h_m7qlen
    PLA
    STA a:h_m7pc
    LDA a:h_m7left
    CLC
    ADC a:h_m7pc
    AND #$00FF
    STA a:h_m7left
    LDA a:h_m7n
    SEC
    SBC a:h_m7pc
    STA a:h_m7n
    BEQ :+
    JMP @piece
:   RTS


.a8
.i8
;;  From PrepOverworld's end (ow7_enter.patch), emulation mode.  The game
;;  has the screen dark (its last $2001 write was 0, and the flush of the
;;  wait before it blanked), so VRAM is open: the plane's characters go
;;  now if VRAM has lost them (power-on, or a native screen, which clears
;;  it), and then every row the view can see, each decoded into the ring,
;;  drawn and sent at once.  Then the plane is on, for the flush.  A, X and
;;  Y kept.
m7_enter:
    PHP
    PHA
    PHX
    PHY
    LDA #$80
    STA a:INIDISP               ; forced blank, as the game has it already
    LDA a:h_m7chr
    BNE :+
    LDA #$80
    STA a:VMAIN                 ; a word on after each high byte
    STZ a:VMADDL
    STZ a:VMADDH
    STZ a:DMAP0                 ; one register...
    LDA #<VMDATAH
    STA a:BBAD0                 ; ...$2119: the characters are the high bytes
    STZ a:A1T0L
    STZ a:A1T0H
    LDA #^OW7DATAFAR
    STA a:A1B0
    STZ a:DAS0L
    LDA #$40
    STA a:DAS0H                 ; 16KB: 256 characters of 64 pixels
    LDA #$01
    STA a:MDMAEN
    STA a:h_m7chr
:   CLC
    XCE
    REP #$10
    .i16
    JSR m7_tables
    JSR m7_pivot
    LDA a:h_m7ntx
    STA a:h_m7tx
    LDA a:h_m7nty
    STA a:h_m7ty
    REP #$20
    .a16
    STZ a:h_m7qlen
    LDA a:h_m7ty
    AND #$00FF
    SEC
    SBC #M7_NORTH
    AND #$00FF
    PHA                         ; 3,S: the row
    LDA #M7_ROWS
    PHA                         ; 1,S: rows to go
@row:
    LDA 3,S
    STA a:h_m7row
    SEP #$20
    .a8
    JSR m7_decode
    REP #$20
    .a16
    LDA a:h_m7tx
    AND #$00FF
    SEC
    SBC #M7_WEST
    AND #$00FF
    STA a:h_m7x
    LDA #M7_COLS
    STA a:h_m7cnt
    JSR m7_drawrow
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    JSL hal_m7sendq + HALFAR    ; to VRAM now, with the screen dark
    CLC
    XCE
    REP #$30
    .a16
    .i16
    LDA 3,S
    INC A
    AND #$00FF
    STA 3,S
    LDA 1,S
    DEC A
    STA 1,S
    BNE @row
    PLA
    PLA
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    LDA #1
    STA a:h_m7on
    PLY
    PLX
    PLA
    PLP
    RTL


.a8
.i8
;;  From ConvertOWToSprite (ow7_objpos.patch), emulation mode: map tile
;;  (X, Y) of an object -- the ship, the airship parked, the bridge, the
;;  canal -- as a sprite position.  At the flat angle, or with the plane
;;  off, V clear and the game's routine places it.  Else V set, and C
;;  clear with spr_x and spr_y the 16x16 sprite's corner, its centre where
;;  the plane shows the tile's centre; C set if that is off the screen
;;  (the NES's bounds) or past the rows kept.  X and Y kept.
;;
;;  The tile's centre is u pixels east and v south of the pivot's, as the
;;  NES draws it: v = (Y - ow_scroll_y - 7) * 16 - move_ctr_y, and u the
;;  same across.  genm7.py's table gives the screen line v lands on (+ 16,
;;  0 for none), and the line's inverse scale k: the centre is at x 120 +
;;  u * k / 256, k from a table by the same line (genm7.py's lines -16 to
;;  239).
m7_objpos:
    LDA a:h_m7on
    BEQ @game
    LDA a:h_m7lvl
    CMP #2                      ; (the angle + 1: 1 the flat)
    BCS :+
@game:
    CLV
    RTL
:   PHX
    PHY
    STX a:h_m7ox
    CLC
    XCE
    REP #$10
    .i16
    TYA
    SEC
    SBC z:ow_scroll_y
    SEC
    SBC #7                      ; tiles south of the pivot's, -128..127
    REP #$20
    .a16
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7n
    LDA z:move_ctr_y
    AND #$00FF
    EOR #$FFFF
    SEC
    ADC a:h_m7n                 ; v
    CLC
    ADC #-M7P_VMIN              ; v - M7P_VMIN, the table's index
    CMP #M7P_VMAX - M7P_VMIN + 1
    BCC :+
    JMP @off
:   ADC a:h_m7tabY
    TAX
    SEP #$20
    .a8
    LDA f:OW7DATAFAR, X         ; the line + 16, 0 for none
    SEC
    SBC #17                     ; the sprite's top: the centre - 8, less the
    BCC @off                    ;   NES's one, and the crop's 8 back
    CMP #$EC
    BCS @off                    ; ConvertOWToSprite's bottom
    STA z:spr_y
    ;  The line's k, by the same index: the line + 16, the sprite's top + 17.
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC #17
    ASL A
    ADC a:h_m7tabK
    TAX
    LDA f:OW7DATAFAR, X
    STA a:h_m7cnt               ; k, 8.8
    ;  u
    SEP #$20
    .a8
    LDA a:h_m7ox
    SEC
    SBC z:ow_scroll_x
    SEC
    SBC #7
    REP #$20
    .a16
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7n
    LDA z:move_ctr_x
    AND #$00FF
    EOR #$FFFF
    SEC
    ADC a:h_m7n                 ; u
    STA a:h_m7x                 ; (its sign)
    BPL :+
    EOR #$FFFF
    INC A
:   CMP #$0200
    BCS @off                    ; past the columns kept, and the multiply's reach
    STA a:h_m7n                 ; |u|, nine bits
    JSR m7_scale                ; |u| * k / 256
    BIT a:h_m7x
    BPL :+
    EOR #$FFFF
    INC A
:   CLC
    ADC #M7P_PIVOTX - 8         ; the sprite's left: the centre - 8
    CMP #$00F8
    BCS @off                    ; ConvertOWToSprite's bounds: 0 to $F7
    SEP #$20
    .a8
    STA z:spr_x
    SEP #$30
    .i8
    SEC
    XCE
    PLY
    PLX
    SEP #$40                    ; placed here
    CLC                         ; on screen
    RTL
@off:
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    PLY
    PLX
    SEP #$40
    SEC
    RTL

.a16
.i16
;;  h_m7n * h_m7cnt / 256, both under 512, by the CPU's 8x8 multiplier:
;;  n * k / 256 = (nl * kl) / 256 + nl * kh + nh * k, the high bytes 0 or
;;  1.  A16 I16; out A.
m7_scale:
    SEP #$20
    .a8
    LDA a:h_m7n
    STA a:WRMPYA
    LDA a:h_m7cnt
    STA a:WRMPYB                ; eight cycles to the product
    REP #$20
    .a16
    LDA a:h_m7n
    AND #$0100
    BEQ :+
    LDA a:h_m7cnt               ; nh * k
:   STA a:h_m7pc
    LDA a:h_m7cnt
    AND #$0100
    BEQ :+
    LDA a:h_m7n                 ; + nl * kh
    AND #$00FF
    CLC
    ADC a:h_m7pc
    STA a:h_m7pc
:   LDA a:RDMPYL
    CLC
    ADC #$0080                  ; (rounded)
    XBA
    AND #$00FF                  ; + (nl * kl) / 256
    CLC
    ADC a:h_m7pc
    RTS
