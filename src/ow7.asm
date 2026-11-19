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
;                drawn (m7_sync), R stepping the angle (for now), and
;                the landmarks stood up, into OAM (m7_lands): from here,
;                as every overworld frame sets its scroll, the frames the
;                game draws no sprites in among them.
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

.import ow_rowring, hal_m7sendq, lut_OWObjectSprTbl
.export m7_rowcol, m7_scroll, m7_enter, m7_objpos, m7_flatobjs, m7_ship
.export lut_M7Row, lut_M7Col, lut_M7LFrame, lut_M7LMaps   ; for tools/test_options.py
.export lut_M7PA, lut_M7PD, lut_M7PRG, lut_M7PB, lut_M7PS, lut_M7PY, lut_M7ShipSize, lut_M7BFrame

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

SRAMFAR7  = CHUNK0 * $10000             ; the game's SRAM, long from any bank
.assert canal_vis - bridge_vis = 4 && bridge_x = bridge_vis + 1 && bridge_y = bridge_vis + 2, error, "the bridge's and the canal's records, four bytes apart"
M7_ROW    = $00                         ; VMAIN: a byte a word along
M7_COL    = $02                         ; VMAIN: a byte 128 words down
RING      = M7RING & $FFFF              ; the ring and the queue, by DBR $7E
RINGEND   = RING + M7RING_ROWS * $100
QUEUE     = M7QUEUE & $FFFF
.assert ^M7RING = ^M7QUEUE, error, "the ring and the queue share a bank"
M7LSPRFAR = $C00000 + (1 + M7L_SPRCHUNK) * $10000 ; the landmarks' sprite lists, long
.assert M7L_SPRITES <= 64 - M7C_FIRST, error, "a landmark frame's sprites past the extras' 64"
.assert M7UPQ_MAX >= 5, error, "the queue: a landmark's frame and a 32x32 frame's four rows a flush"
.assert M7L_SLOT <= M7L_SLOTW && M7L_SLOT0 + 3 * M7L_SLOTW <= $100, error, "the landmarks' three slots past the sprite table"


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
;;  plane up, R, the rows and columns, and the landmarks, placed by the
;;  same scroll the flush gives the plane.  Everything kept.
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
    JSR m7_lands
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
    LDA f:OW7FAR + lut_M7PS, X
    STA a:h_m7slope
    LDA f:OW7FAR + lut_M7PY, X
    STA a:h_m7tabY
    SEP #$20
    .a8
  .if M7P_FOGSUB
    LDA #$B1                    ; subtract the fixed colour from BG1, the sprites
  .else                         ;   in OBJ palettes 4-7 (all of them, here:
    LDA #$31                    ;   h_m7oampal) and the backdrop; or add it
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
    ;  The bridge and the canal's land, if this row has them showing: their
    ;  metatiles, $80 and $81, whose characters are the sprite over the map.
    LDX #0
@obj:
    LDA f:SRAMFAR7 + bridge_vis, X      ; vis, then x
    AND #$00FF
    BEQ @next
    LDA f:SRAMFAR7 + bridge_y, X
    EOR a:h_m7row
    AND #$00FF
    BNE @next
    PHX
    LDA f:SRAMFAR7 + bridge_x, X
    AND #$00FF
    STA a:h_m7n                 ; its column
    TXA
    LSR A
    LSR A
    ORA #$0080                  ; $80 the bridge, $81 the canal
    PHA
    LDA a:h_m7row
    AND #M7RING_ROWS - 1
    CLC
    ADC #>RING
    XBA                         ; the row's page
    ORA a:h_m7n
    TAX
    PLA
    SEP #$20
    .a8
    STA f:M7RING & $FF0000, X
    REP #$20
    .a16
    PLX
@next:
    INX
    INX
    INX
    INX
    CPX #8
    BCC @obj
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
    LDA a:$0000, X              ; the metatile, from the ring ($80 and $81 the
    AND #$00FF                  ;   bridge and the canal's land, m7_decode's)
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
    AND #$00FF
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
    JSR m7_objchars
    ;  The landmarks: no slot or block holds a frame, nothing waits, no
    ;  extras yet -- every OAMSHADOW entry off the bottom, the high table
    ;  zero, the halves the NES's way round (the game's next transfer
    ;  fills the game's range).
    REP #$20
    .a16
    LDA #$FFFF
    STA a:h_m7lkey
    STA a:h_m7lkey + 1
    LDX #16 - 2
:   STA a:h_m7bkey, X
    DEX
    DEX
    BPL :-
    LDA #0
    LDX #256 - 2
:   STA f:M7BREV, X
    DEX
    DEX
    BPL :-
    LDA #$FFFF
    STZ a:h_m7oux
    STZ a:h_m7ouy
    LDA #$FFFF
    STA a:h_m7gtile             ; the groups near: none worked out yet
    SEP #$20
    .a8
    STZ a:h_m7upon
    STZ a:h_m7bupon
    STZ a:h_m7upn
    STZ a:h_m7xfront
    STZ a:h_m7ccount
    LDX #0
    LDA #$F0
:   STA a:OAMSHADOW + 1, X
    INX
    INX
    INX
    INX
    CPX #512
    BCC :-
:   STZ a:OAMSHADOW, X
    INX
    CPX #512 + 32
    BCC :-
    ;  The sprites into OBJ palettes 4-7, where the haze reaches them: their
    ;  colours re-sent there, and OAM's palettes moved up (hal_oamdma), until
    ;  rendering goes off (hal_w2001).
    REP #$20
    .a16
    LDA #64
    STA a:h_m7objoff
    SEP #$20
    .a8
    LDA #$08
    STA a:h_m7oampal
    LDA #1
    STA a:h_paldirty
    STA a:h_palforce
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
.i16
;;  The bridge's and the canal's characters, M7_SPECIAL on: each of their
;;  2x2 sprites' quarters (lut_OWObjectSprTbl, the tiles + $10, from the
;;  pattern table soft2000 gives sprites, as CHRSHADOW holds it -- a horizontal
;;  bridge's overlay included) over the map's metatile under it, a pixel
;;  of the sprite where it has colour, of the map's character where not.
;;  The sprite's colour c of palette p is CGRAM 192 + p * 16 + c, where
;;  the overworld keeps the sprite palettes.  Then all eight to VRAM, the
;;  screen being dark.  A8 I16 in and out.
m7_objchars:
    PHB
    LDA #^M7OBJBUF
    PHA
    PLB
    LDX #0
    JSR m7_objchar
    LDX #4
    JSR m7_objchar
    PLB
    LDA #$80
    STA a:VMAIN                 ; a word on after each high byte
    REP #$20
    .a16
    LDA #M7_SPECIAL * 64
    STA a:VMADDL
    LDA #.loword(M7OBJBUF)
    STA a:A1T0L
    LDA #$0200
    STA a:DAS0L
    SEP #$20
    .a8
    STZ a:DMAP0
    LDA #<VMDATAH
    STA a:BBAD0
    LDA #^M7OBJBUF
    STA a:A1B0
    LDA #$01
    STA a:MDMAEN
    RTS

;;  Object X (0 the bridge, 4 the canal: their records' offsets), if it
;;  shows, into M7OBJBUF + X * 64.  DBR $7E.  A8 I16.
m7_objchar:
    LDA f:SRAMFAR7 + bridge_vis, X
    BNE :+
    RTS
:   STX a:h_m7x                 ; (the object)
    ;  The map's metatile under it: its row decoded into M7OBJROW.
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
    LDA f:SRAMFAR7 + bridge_y, X
    LDX #>(M7OBJROW & $FFFF)
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
    LDX a:h_m7x
    LDA f:SRAMFAR7 + bridge_x, X
    AND #$00FF
    TAX
    LDA a:M7OBJROW & $FFFF, X
    AND #$007F
    ASL A
    ASL A
    STA a:h_m7row               ; its corners in lut_M7Row
    ;  Its four quarters, UL, UR, DL, DR as the characters go.
    STZ a:h_m7line
@quarter:
    LDX a:h_m7line
    LDA f:OW7FAR + m7_quarter, X ; the sprite table's order: UL, DL, UR, DR
    AND #$00FF
    STA a:h_m7n
    LDA a:h_m7x
    ASL A                       ; the object's 8 bytes: X * 2 (bridge 8, canal 16)
    CLC
    ADC #8
    ADC a:h_m7n
    TAX
    LDA f:OW7FAR + lut_OWObjectSprTbl, X    ; the tile, then its attributes
    STA a:h_m7cnt
    ;  The sprite tile's 32 bytes in CHRSHADOW: + $10, in the pattern table
    ;  soft2000 gives the sprites (bit 3: the second, 256 on).  Not
    ;  h_sprtable, the HAL's copy, which the next OAM transfer sets.
    AND #$00FF
    CLC
    ADC #$0010
    STA a:h_m7n
    LDA z:soft2000
    AND #$0008
    LSR A
    LSR A
    LSR A
    XBA
    ORA a:h_m7n
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7addr              ; the tile's offset in CHRSHADOW
    ;  The map's character under this quarter.
    LDA a:h_m7row
    ORA a:h_m7line
    TAX
    LDA f:OW7FAR + lut_M7Row, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    STA a:h_m7left              ; its 64 pixels in the chunk's low half
    ;  Out: object, quarter, 64 bytes each.
    LDA a:h_m7x
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A                       ; X * 64: the object's four characters, 256
    STA a:h_m7pc
    LDA a:h_m7line
    XBA
    LSR A
    LSR A                       ; quarter * 64
    CLC
    ADC a:h_m7pc
    ADC #.loword(M7OBJBUF)
    TAY
    ;  Eight rows of eight.
    STZ a:h_m7pc                ; the row, 0-7
@row:
    LDA a:h_m7pc
    BIT a:h_m7cnt               ; (sixteen bits: the attributes' 7 into N, a vertical flip)
    BPL :+
    EOR #$0007
:   ASL A
    CLC
    ADC a:h_m7addr
    TAX
    LDA a:CHRSHADOW & $FFFF, X  ; planes 0 and 1 of the row
    STA a:h_m7tx                ; (h_m7tx, h_m7ty: borrowed, the way in sets them after)
    LDX #0                      ; the column, 0-7
@pix:
    PHX
    TXA
    BIT a:h_m7cnt               ; the attributes' 6 into V: a horizontal flip
    BVC :+
    EOR #$0007
:   TAX
    LDA f:OW7FAR + m7_bits, X   ; that pixel's bit
    AND #$00FF
    STA a:h_m7n
    AND a:h_m7tx                ; plane 0
    BEQ :+
    LDA #1
:   STA a:h_m7save              ; (the colour so far: the decode is done with it)
    LDA a:h_m7n
    XBA
    AND a:h_m7tx                ; plane 1
    BEQ :+
    LDA #2
:   ORA a:h_m7save
    AND #$0003
    BEQ @map
    STA a:h_m7n
    LDA a:h_m7cnt + 1           ; the attributes: palette in bits 1-0
    AND #$0003
    ASL A
    ASL A
    ASL A
    ASL A
    ORA a:h_m7n
    ORA #192                    ; OBJ palettes 4-7, as the overworld has them
    BRA @put
@map:
    LDA a:h_m7pc
    ASL A
    ASL A
    ASL A
    ORA 1, S                    ; the column
    ORA a:h_m7left
    TAX
    LDA f:OW7DATAFAR, X         ; the map character's pixel
@put:
    SEP #$20
    .a8
    STA a:$0000, Y
    REP #$20
    .a16
    INY
    PLX
    INX
    CPX #8
    BCC @pix
    INC a:h_m7pc
    LDA a:h_m7pc
    CMP #8
    BCS :+
    JMP @row
:
    LDA a:h_m7line
    INC A
    STA a:h_m7line
    CMP #4
    BCS :+
    JMP @quarter
:   SEP #$20
    .a8
    RTS

m7_quarter:
    .BYTE 0, 4, 2, 6            ; UL, UR, DL, DR in lut_OWObjectSprTbl's UL, DL, UR, DR
m7_bits:
    .BYTE $80, $40, $20, $10, $08, $04, $02, $01

.a8
.i8
;;  From DrawOWObj_BridgeCanal (ow7_flatobjs.patch), emulation mode: C set
;;  with the plane up, the bridge and the canal's land being in it.
m7_flatobjs:
    LDA a:h_m7on
    CMP #1
    RTL

.a8
.i8
;;  Map tile (h_m7ox, h_m7oy) of an object, where the plane shows its
;;  centre.  The centre is u pixels east and v south of the pivot's, as the
;;  NES draws it: v = (Y - ow_scroll_y - 7) * 16 - move_ctr_y, and u the
;;  same across.  genm7.py's table gives the screen line v lands on, signed
;;  ($8000 for none) -- south past the screen's bottom, for an object
;;  standing there whose top shows -- and the line's inverse scale k is
;;  linear in it, 1 at the pivot's: k = 256 + (line - 112) * h_m7slope /
;;  256.  The centre is at x 120 + u * k / 256.  Out: C clear with
;;  h_m7oline the line, h_m7ocx the x (signed), h_m7cnt the k; C set past
;;  the table's rows or the columns kept.  A8 I16.
m7_project:
    LDA a:h_m7oy
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
    ADC a:h_m7n                 ; v (the tile's centre)
    CLC
    ADC a:h_m7ouy               ; + the point's offset south of it
    CLC
    ADC #-M7P_VMIN              ; v - M7P_VMIN, the table's index
    CMP #M7P_VMAX - M7P_VMIN + 1
    BCC :+
    JMP m7_projout
:   ASL A                       ; (a word each)
    ADC a:h_m7tabY
    TAX
    LDA f:OW7DATAFAR, X         ; the line, signed; $8000 none
    CMP #$8000
    BNE :+
    JMP m7_projout
:   STA a:h_m7oline
    SEC
    SBC #M7P_PIVOTLINE
    STA a:h_m7x                 ; (its sign)
    BPL :+
    EOR #$FFFF
    INC A
:   STA a:h_m7n                 ; |line - 112|: under 512, the lines kept
    LDA a:h_m7slope
    STA a:h_m7cnt
    JSR m7_scale                ; * the slope / 256
    BIT a:h_m7x
    BPL :+
    EOR #$FFFF
    INC A
:   CLC
    ADC #256
    STA a:h_m7cnt               ; k, 8.8
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
    ADC a:h_m7n                 ; u (the tile's centre)
    CLC
    ADC a:h_m7oux               ; + the point's offset east of it
    STA a:h_m7x                 ; (its sign)
    BPL :+
    EOR #$FFFF
    INC A
:   CMP #$0200
    BCS m7_projout                    ; past the columns kept, and the multiply's reach
    STA a:h_m7n                 ; |u|, nine bits
    JSR m7_scale                ; |u| * k / 256
    BIT a:h_m7x
    BPL :+
    EOR #$FFFF
    INC A
:   CLC
    ADC #M7P_PIVOTX
    STA a:h_m7ocx
    SEP #$20
    .a8
    CLC
    RTS
m7_projout:
    SEP #$20
    .a8
    SEC
    RTS


.a8
.i8
;;  From ConvertOWToSprite (ow7_objpos.patch), emulation mode: map tile
;;  (X, Y) of an object -- the airship parked -- as a sprite position.  At
;;  the flat angle, or with the plane off, V clear and the game's routine
;;  places it.  Else V set, and C clear with spr_x and spr_y the 16x16
;;  sprite's corner, its centre where the plane shows the tile's centre
;;  (m7_project); C set if that is off the screen (the NES's bounds) or past
;;  the rows kept.  X and Y kept.
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
    STY a:h_m7oy
    STZ a:h_m7oux               ; the tile's centre itself
    STZ a:h_m7oux + 1
    STZ a:h_m7ouy
    STZ a:h_m7ouy + 1
    CLC
    XCE
    REP #$10
    .i16
    JSR m7_project
    BCS @off
    REP #$20
    .a16
    LDA a:h_m7oline
    DEC A                       ; the sprite's top: the centre - 8, less the
                                ;   NES's one, and the crop's 8 back
    CMP #$EC
    BCS @off                    ; above the screen, or ConvertOWToSprite's bottom
    SEP #$20
    .a8
    STA z:spr_y
    REP #$20
    .a16
    LDA a:h_m7ocx
    SEC
    SBC #8                      ; the sprite's left: the centre - 8
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


.a8
.i8
;;  From DrawOWObj_Ship (ow7_ship.patch), emulation mode.  At the flat
;;  angle, or with the plane off, C clear and the game draws the ship.  Else
;;  C set and the game draws nothing: the docked ship is m7_lands', one
;;  32x32 sprite at its line's size, drawn every overworld frame with the
;;  landmarks.
m7_ship:
    LDA a:h_m7on
    BEQ :+
    LDA a:h_m7lvl
    CMP #2                      ; (the angle + 1: 1 the flat)
    BCS @tilted
:   CLC
    RTL
@tilted:
    SEC
    RTL


.a8
.i16
;;  The landmarks stood up -- the castles, the Temple of Fiends, the Mirage
;;  Tower and the volcano (user, 2026-11-18) -- with the towns' houses and
;;  the docked ship: those on the map in play (genm7.py's list for
;;  RANDO_MAP, in groups culled whole, each group's the southmost first;
;;  past the list, the game's map's) near the pivot's tile, each placed by
;;  its base as any object (m7_project; the members of a row share its
;;  line) -- its base below the screen while its top shows -- and drawn at
;;  genm7.py's frame for its line's inverse scale, k in sixteenths, into
;;  OAMSHADOW's extras: the ship and the houses first, one 32x32 sprite
;;  each, as the list has them (M7HBUF); then the landmarks, M7L_VIS at
;;  most, the nearest first (M7LVIS), each upwards from its base as 8x8
;;  sprites.  A first is in front.  From m7_scroll, by the scroll the flush
;;  gives the plane with them, every overworld frame -- the airship's
;;  take-off and landing and a menu's palette cycle, which draw none of the
;;  game's sprites, among them.  A landmark's frame is drawn from whichever
;;  of three slots in the sprite table holds it, a 32x32 frame from
;;  whichever of sixteen blocks in the other (h_m7lkey; h_m7bkey and
;;  M7BREV); if none does, it is uploaded -- into a slot no other landmark
;;  takes this frame, or a block no house took this frame or the last
;;  (m7_lupload, m7_bupload) -- at the flush that sends these sprites,
;;  before them.  One landmark's frame and one 32x32 frame a flush: with
;;  one waiting, or none free, one holding the same art at another size
;;  stands in, and with none it waits a frame.  They stand in front of the
;;  party when it is north of one's base row, tilted and not in the air:
;;  OAMSHADOW's halves swapped when that changes (m7_front).  Entries the
;;  last frame held and this one does not, off the bottom (h_m7ccount).
;;  A8 I16.
m7_lands:
    LDA f:RANDO_SAVEFAR + (RANDO_MAP - RANDO_SAVE)
    CMP #M7L_MAPS
    BCC :+
    LDA #0                      ; a map past the list: the game's, as map_id has it
:   REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA f:OW7FAR + lut_M7LMaps, X
    STA a:h_m7lptr
    STZ a:h_m7bused
    SEP #$20
    .a8
    STZ a:h_m7lnvis
    STZ a:h_m7hn
    STZ a:h_m7lfront
    JSR m7_lship
    JSR m7_gnear                ; the groups near, worked out again if due
    STZ a:h_m7gi
@near:
    LDA a:h_m7gi
    CMP a:h_m7gnn
    BCC :+
    JMP @listed
:   REP #$20
    .a16
    AND #$00FF
    ASL A
    TAX
    LDA a:M7GNEAR, X
    TAX                         ; its header
    CLC
    ADC #M7L_GROUP
    STA a:h_m7lptr              ; its records
    SEP #$20
    .a8
    INC a:h_m7gi
    LDA f:OW7FAR, X
    STA a:h_m7gn
@member:
    LDX a:h_m7lptr
    LDA f:OW7FAR, X
    BMI @row
    JSR m7_lmember              ; a landmark
    LDA #M7L_REC
    BRA @advance
@row:
    JSR m7_lrow                 ; a row of houses
    LDX a:h_m7lptr
    LDA f:OW7FAR + 4, X
    CLC
    ADC #M7L_ROW
@advance:
    REP #$20
    .a16
    AND #$00FF
    CLC
    ADC a:h_m7lptr
    STA a:h_m7lptr
    SEP #$20
    .a8
    DEC a:h_m7gn
    BNE @member
    BRA @near

@listed:
    REP #$20
    .a16
    STZ a:h_m7oux               ; (m7_objpos places tiles' centres)
    STZ a:h_m7ouy
    LDA a:h_m7bused
    STA a:h_m7bprev             ; the blocks this frame's took, for the next
    LDA a:h_m7lnvis
    AND #$00FF
    ASL A
    ASL A
    ASL A
    STA a:h_m7pc                ; past the landmarks
    SEP #$20
    .a8
    STZ a:h_m7lused
    ;  Each landmark its frame from the slot that holds it...
    LDY #0
@exact:
    CPY a:h_m7pc
    BCS @exacted
    LDA #$FF
    STA a:M7LVIS + 5, Y
    LDA a:M7LVIS + 4, Y
    LDX #0
:   CMP a:h_m7lkey, X
    BEQ :+
    INX
    CPX #3
    BCC :-
    BRA @exnext
:   TXA
    STA a:M7LVIS + 5, Y
    LDA f:OW7FAR + lut_M7LBit, X
    ORA a:h_m7lused
    STA a:h_m7lused
@exnext:
    REP #$20
    .a16
    TYA
    CLC
    ADC #8
    TAY
    SEP #$20
    .a8
    BRA @exact
@exacted:
    LDY #0
@other:
    CPY a:h_m7pc
    BCS @slotted
    LDA a:M7LVIS + 5, Y
    CMP #$FF
    BNE @onext
    ;  ...or uploaded into a slot no other takes this frame (the flush
    ;  sends the tiles before the sprites, so the last frame's never show
    ;  the new ones)...
    LDA a:h_m7upon
    BNE @borrow
    LDX #0
:   LDA f:OW7FAR + lut_M7LBit, X
    AND a:h_m7lused
    BEQ @free
    INX
    CPX #3
    BCC :-
@borrow:
    ;  ...or, with an upload waiting or none free, drawn at the size a slot
    ;  holding its art has, till its frame comes; with none, not drawn.
    LDA a:M7LVIS + 4, Y
    AND #$F0
    STA a:h_m7save + 3
    LDX #0
:   LDA a:h_m7lkey, X
    CMP #$FF
    BEQ :+
    AND #$F0
    CMP a:h_m7save + 3
    BEQ @lend
:   INX
    CPX #3
    BCC :--
    BRA @onext
@lend:
    LDA a:h_m7lkey, X
    STA a:M7LVIS + 4, Y
    BRA @take
@free:
    LDA a:M7LVIS + 4, Y
    STA a:h_m7lkey, X
    JSR m7_lupload              ; (X and Y kept)
@take:
    TXA
    STA a:M7LVIS + 5, Y
    LDA f:OW7FAR + lut_M7LBit, X
    ORA a:h_m7lused
    STA a:h_m7lused
@onext:
    REP #$20
    .a16
    TYA
    CLC
    ADC #8
    TAY
    SEP #$20
    .a8
    BRA @other

@slotted:
    ;  In front of the party, or behind?
    LDA a:h_m7lvl
    CMP #2
    BCC @behind                 ; flat, the NES's way: the party over all
    LDA z:vehicle
    CMP #$08
    BEQ @behind                 ; the airship flies over them
    LDA a:h_m7lfront
    BEQ @behind
    LDA #1
    BRA @front
@behind:
    LDA #0
@front:
    JSR m7_front
    ;  The ship's and the houses' sprites, as placed, into the extras from
    ;  M7C_FIRST on: Y walks OAMSHADOW.
    REP #$20
    .a16
    LDA a:h_m7save + 4
    CLC
    ADC #M7C_FIRST * 4
    TAY
    LDX #0
    SEP #$20
    .a8
    LDA a:h_m7hn
    BEQ @houses
    STA a:h_m7gn                ; (the extras' first entry starts a high-table byte)
    STZ a:h_m7save + 3          ; the high-table byte so far
    STZ a:h_m7gw                ; the entry's place in it, times 4
@hcopy:
    REP #$20
    .a16
    LDA a:M7HBUF + 0, X         ; x, line
    STA a:OAMSHADOW + 0, Y
    LDA a:M7HBUF + 2, X         ; tile, attributes
    STA a:OAMSHADOW + 2, Y
    LDA a:M7HBUF + 4, X         ; x's ninth bit, the size
    PHX
    ORA a:h_m7gw
    AND #$000F
    TAX
    SEP #$20
    .a8
    LDA f:OW7FAR + lut_M7XB, X  ; at its place
    ORA a:h_m7save + 3
    STA a:h_m7save + 3
    PLX
    INX
    INX
    INX
    INX
    INX
    INY
    INY
    INY
    INY
    LDA a:h_m7gw
    CLC
    ADC #4
    AND #$0F
    STA a:h_m7gw
    BNE :+
    JSR m7_hbyte                ; four done: their byte
:   DEC a:h_m7gn
    BNE @hcopy
    LDA a:h_m7gw
    BEQ @houses
    JSR m7_hbyte                ; the last, part filled
@houses:
    ;  Then the landmarks', the nearest's first.
    REP #$20
    .a16
    STZ a:h_m7lptr              ; (M7LVIS's entry now)
@land:
    LDX a:h_m7lptr
    CPX a:h_m7pc
    BCC :+
    JMP @rest
:   LDA a:M7LVIS + 5, X
    AND #$00FF
    CMP #$00FF
    BNE :+
    JMP @nextland               ; no slot this frame
:   ASL A
    TAX
    LDA f:OW7FAR + lut_M7LTile, X
    STA a:h_m7line              ; (borrowed: the slot's first tile)
    LDX a:h_m7lptr
    LDA a:M7LVIS, X
    STA a:h_m7row               ; (borrowed: the base's screen line)
    LDA a:M7LVIS + 2, X
    STA a:h_m7ocx
    LDA a:M7LVIS + 4, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAX                         ; its frame's record
    LDA f:OW7FAR + lut_M7LFrame + 3, X
    STA a:h_m7addr              ; its sprite list
    LDA f:OW7FAR + lut_M7LFrame + 6, X
    AND #$00FF
    STA a:h_m7left              ; how many
    TYA                         ; room for them all in the extras, or
    SEC                         ;   none of it drawn
    SBC a:h_m7save + 4
    LSR A
    LSR A
    CLC
    ADC a:h_m7left
    CMP #64 + 1
    BCC :+
    JMP @nextland
    ;  Its corner and its last sprite's, from the list's head (signed
    ;  bytes): x0, x1, y0, y1.
:   LDX a:h_m7addr
    LDA f:M7LSPRFAR, X          ; x0
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    CLC
    ADC a:h_m7ocx
    STA a:h_m7x                 ; (borrowed: its left)
    LDA f:M7LSPRFAR + 2, X      ; y0
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    CLC
    ADC a:h_m7row
    STA a:h_m7cnt               ; (borrowed: its top)
    TXA
    CLC
    ADC #4
    STA a:h_m7addr              ; its sprites
    ;  On the screen across, the common case: no sprite to clip across,
    ;  none with x's ninth bit -- x and line, tile and attributes, a word
    ;  each; the rows below the screen and above it passed by whole (a
    ;  frame's sprites are listed row by row, the top's first).
    LDA a:h_m7x
    BPL :+
    JMP @slow
:   LDA f:M7LSPRFAR + 1, X      ; x1
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    CLC
    ADC a:h_m7ocx
    CMP #256
    BCC :+
    JMP @slow
:   LDA #223
    SEC
    SBC a:h_m7cnt               ; the last row shown, from the corner:
    BPL :+                      ;   223 - top
    JMP @nextland               ; (all of it below)
:   CMP #256
    BCS @kept                   ; (none of it below)
    STA a:h_m7n                 ; (borrowed)
    LDA a:h_m7left
    DEC A
    ASL A
    ASL A
    CLC
    ADC a:h_m7addr
    TAX                         ; the last sprite
    SEP #$20
    .a8
@under:
    LDA f:M7LSPRFAR + 1, X      ; its row from the corner
    CMP a:h_m7n
    BCC @kept8
    BEQ @kept8
    DEX
    DEX
    DEX
    DEX
    DEC a:h_m7left
    BNE @under
    REP #$20
    .a16
    JMP @nextland
@kept8:
    REP #$20
    .a16
@kept:
    LDA #$FFF9                  ; (-7)
    SEC
    SBC a:h_m7cnt               ; the first row shown: -7 - top, at least 0
    BPL :+
    LDA #0
:   STA a:h_m7n                 ; (borrowed)
    LDA a:h_m7cnt
    XBA
    AND #$FF00
    ORA a:h_m7x
    STA a:h_m7fbase             ; line, x (the line's low byte: a top above
    LDA a:h_m7line              ;   the screen wraps, as the SNES draws it)
    ORA #($20 | (4 << 1) | 1) << 8  ; in front of the plane; OBJ palette 4; the sprite table
    STA a:h_m7ftile
    LDX a:h_m7addr
    SEP #$20
    .a8
@above:
    LDA f:M7LSPRFAR + 1, X      ; its row from the corner
    CMP a:h_m7n
    BCS @fast8
    INX
    INX
    INX
    INX
    DEC a:h_m7left
    BNE @above
    REP #$20
    .a16
    JMP @nextland
@fast8:
    REP #$20
    .a16
@fast:
    LDA f:M7LSPRFAR, X          ; x and line from the corner
    CLC
    ADC a:h_m7fbase
    STA a:OAMSHADOW + 0, Y
    LDA f:M7LSPRFAR + 2, X      ; the tile in the frame
    CLC
    ADC a:h_m7ftile
    STA a:OAMSHADOW + 2, Y
    INX
    INX
    INX
    INX
    INY
    INY
    INY
    INY
    DEC a:h_m7left
    BNE @fast
    JMP @nextland
@slow:
    ;  Part of it off the screen: each sprite clipped, x's ninth bit set
    ;  where it is past the left.
    LDA a:h_m7left
    BNE :+
    JMP @nextland
:   DEC a:h_m7left
    LDX a:h_m7addr
    LDA f:M7LSPRFAR + 2, X      ; the tile in the frame
    AND #$00FF
    CLC
    ADC a:h_m7line
    STA a:h_m7n
    LDA f:M7LSPRFAR + 1, X      ; its line from the corner
    AND #$00FF
    CLC
    ADC a:h_m7cnt
    CLC
    ADC #7                      ; on screen from -7 to 223
    CMP #224 + 7
    BCS @skip
    SEC
    SBC #7
    STA a:h_m7save + 2          ; (a top above the screen wraps, as the SNES draws it)
    LDA f:M7LSPRFAR, X          ; its x from the corner
    AND #$00FF
    CLC
    ADC a:h_m7x
    CLC
    ADC #7                      ; on screen from -7 to 255
    CMP #256 + 7
    BCS @skip
    SEC
    SBC #7
    SEP #$20
    .a8
    STA a:OAMSHADOW + 0, Y
    LDA a:h_m7save + 2
    STA a:OAMSHADOW + 1, Y
    LDA a:h_m7n
    STA a:OAMSHADOW + 2, Y
    LDA #$20 | (4 << 1) | 1     ; in front of the plane; OBJ palette 4; the sprite table
    STA a:OAMSHADOW + 3, Y
    XBA
    BEQ @put                    ; x's ninth bit, into the high table
    LDA #$01
    JSR m7_xbits
@put:
    REP #$20
    .a16
    INY
    INY
    INY
    INY
@skip:
    .a16
    LDA a:h_m7addr
    CLC
    ADC #4
    STA a:h_m7addr
    JMP @slow
@nextland:
    .a16
    LDA a:h_m7lptr
    CLC
    ADC #8
    STA a:h_m7lptr
    JMP @land
@rest:
    ;  This frame's count; the last one's entries past it off the bottom.
    TYA
    SEC
    SBC a:h_m7save + 4
    LSR A
    LSR A
    SEC
    SBC #M7C_FIRST
    STA a:h_m7pc                ; this frame's
    SEP #$20
    .a8
    LDA a:h_m7ccount
    SEC
    SBC a:h_m7pc
    BCC @counted
    BEQ @counted
    STA a:h_m7cnt
    LDA #$F0
:   STA a:OAMSHADOW + 1, Y
    INY
    INY
    INY
    INY
    DEC a:h_m7cnt
    BNE :-
@counted:
    LDA a:h_m7pc
    STA a:h_m7ccount
    LDA #1
    STA a:h_oamdirty
    RTS


.a8
.i16
;;  The high-table byte the house copy has built (h_m7save + 3), for the
;;  four entries before Y; then a new one.  A8 I16; X and Y kept.
m7_hbyte:
    PHX
    REP #$20
    .a16
    TYA
    DEC A
    LSR A
    LSR A
    LSR A
    LSR A
    TAX                         ; their high-table byte
    SEP #$20
    .a8
    LDA a:h_m7save + 3
    ORA a:OAMSHADOW + 512, X
    STA a:OAMSHADOW + 512, X
    STZ a:h_m7save + 3
    PLX
    RTS

;;  The map's groups near the pivot's tile (genm7.py's windows, each its
;;  last row and column within them) into M7GNEAR, from the list at
;;  h_m7lptr: worked out again when the scroll has moved a tile, on a frame
;;  m7_sync has queued no row or column for (the windows' margin covers
;;  the tile the list may lag by); at once with none yet (h_m7gtile $FFFF,
;;  m7_enter's).  A8 I16.
m7_gnear:
    REP #$20
    .a16
    LDA z:ow_scroll_x           ; (and ow_scroll_y, the byte after)
    CMP a:h_m7gtile
    BEQ @kept
    LDX a:h_m7gtile
    INX
    BEQ @work                   ; none yet
    LDX a:h_m7qlen
    BNE @kept                   ; a row or column queued: the next frame
@work:
    STA a:h_m7gtile
    SEP #$20
    .a8
    STZ a:h_m7gnn
@group:
    LDX a:h_m7lptr
    LDA f:OW7FAR, X             ; its records; 0 past the last
    BEQ @kept
    ;  Near: its rows' last from 22 north of the pivot's (scroll + 7) to
    ;  12 south, widened by the rows it spans; its columns' last within 18,
    ;  so (genm7.py's windows).
    LDA f:OW7FAR + 1, X
    SEC
    SBC z:ow_scroll_y
    CLC
    ADC #22 - 7
    CMP f:OW7FAR + 2, X
    BCS @far
    LDA f:OW7FAR + 3, X
    SEC
    SBC z:ow_scroll_x
    CLC
    ADC #18 - 7
    CMP f:OW7FAR + 4, X
    BCS @far
    LDA a:h_m7gnn
    CMP #M7G_MAX
    BCS @far
    INC a:h_m7gnn
    REP #$20
    .a16
    AND #$00FF
    ASL A
    TAY
    TXA
    STA a:M7GNEAR, Y
    SEP #$20
    .a8
@far:
    LDA f:OW7FAR + 5, X         ; past its header and its records
    CLC
    ADC #M7L_GROUP
    REP #$20
    .a16
    AND #$00FF
    ADC a:h_m7lptr
    STA a:h_m7lptr
    SEP #$20
    .a8
    BRA @group
@kept:
    SEP #$20
    .a8
    RTS

;;  A's two bits -- x's ninth, the size -- into the high table at entry Y's
;;  place.  A8 I16; X changed, Y kept.
m7_xbits:
    STA a:h_m7save + 3
    REP #$20
    .a16
    TYA
    AND #$000C                  ; the entry's place in its byte, times 4
    ORA a:h_m7save + 3
    AND #$000F
    TAX
    SEP #$20
    .a8
    LDA f:OW7FAR + lut_M7XB, X
    STA a:h_m7save + 3
    REP #$20
    .a16
    TYA
    LSR A
    LSR A
    LSR A
    LSR A
    TAX                         ; the entry's high-table byte
    SEP #$20
    .a8
    LDA a:h_m7save + 3
    ORA a:OAMSHADOW + 512, X
    STA a:OAMSHADOW + 512, X
    RTS

lut_M7XB:                       ; two bits b at place p (p * 4 + b): b << 2p
    .REPEAT 16, i
    .BYTE (i .MOD 4) << (2 * (i / 4))
    .ENDREP


.a8
.i16
;;  The landmark at h_m7lptr: placed (m7_project), and if it shows, a
;;  candidate (m7_lvisadd).  A8 I16.
m7_lmember:
    LDX a:h_m7lptr
    ;  Near: its bottom row from 22 north of the pivot's to 12 south, its
    ;  column within 18 (m7_project has the exact bounds).
    LDA f:OW7FAR + 2, X
    SEC
    SBC z:ow_scroll_y
    SEC
    SBC #7
    CLC
    ADC #22
    CMP #22 + 13
    BCS @out
    LDA f:OW7FAR + 1, X
    SEC
    SBC z:ow_scroll_x
    SEC
    SBC #7
    CLC
    ADC #18
    CMP #18 + 19
    BCC :+
@out:
    RTS
:   LDA f:OW7FAR + 1, X
    STA a:h_m7ox
    LDA f:OW7FAR + 2, X
    STA a:h_m7oy
    REP #$20
    .a16
    LDA f:OW7FAR + 4, X         ; its base: pixels east of its left
    AND #$00FF                  ;   column's centre, and south of its
    EOR #$0080                  ;   bottom row's, signed bytes
    SEC
    SBC #$0080
    STA a:h_m7oux
    LDA f:OW7FAR + 5, X
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    STA a:h_m7ouy
    SEP #$20
    .a8
    JSR m7_project
    BCS @out
    JSR m7_lsize
    BCS @out
    LDX a:h_m7lptr
    LDA a:h_m7ty
    SEC
    SBC f:OW7FAR + 3, X         ; the party north of its row: in front
    BPL :+
    STA a:h_m7lfront
:   LDA f:OW7FAR, X             ; its art
    ASL A
    ASL A
    ASL A
    ASL A
    ORA a:h_m7n
    STA a:h_m7n                 ; the frame wanted: art * 16 + size
    JMP m7_lvisadd


.a8
.i16
;;  The row of houses at h_m7lptr: the row placed once -- m7_project at
;;  its first column: the line, k and that one's x -- its frame and its
;;  block once (m7_hblock), and each house's x from the first one's, k
;;  times the columns between, over 16; each that shows a 32x32 sprite into
;;  M7HBUF, its box standing on its base.  A8 I16.
m7_lrow:
    LDX a:h_m7lptr
    LDA f:OW7FAR + 1, X         ; near: the row from 22 north of the
    SEC                         ;   pivot's to 12 south
    SBC z:ow_scroll_y
    SEC
    SBC #7
    CLC
    ADC #22
    CMP #22 + 13
    BCC :+
@out:
    RTS
:   LDA f:OW7FAR + 1, X
    STA a:h_m7oy
    LDA f:OW7FAR + 5, X         ; its first column
    STA a:h_m7ox
    REP #$20
    .a16
    STZ a:h_m7oux               ; (a house's base is its tile's middle)
    LDA f:OW7FAR + 3, X
    AND #$00FF
    EOR #$0080
    SEC
    SBC #$0080
    STA a:h_m7ouy
    SEP #$20
    .a8
    JSR m7_project
    BCS @out
    REP #$20
    .a16
    LDA a:h_m7oline
    BPL :+
    JMP @out16                  ; its base above the top: none of it shows
:
    SEC
    SBC #32                     ; its boxes' top
    CLC
    ADC #31                     ; on screen from -31 to 223
    CMP #224 + 31
    BCC :+
    JMP @out16
:   SEC
    SBC #31
    STA a:h_m7fbase
    LDA a:h_m7cnt
    CLC
    ADC #8
    LSR A
    LSR A
    LSR A
    LSR A                       ; k in sixteenths, rounded
    SEC
    SBC #M7L_K0
    BPL :+
    LDA #0
:   CMP #M7L_FRAMES
    BCC :+
    LDA #M7L_FRAMES - 1
:   SEP #$20
    .a8
    STA a:h_m7n
    LDX a:h_m7lptr
    LDA a:h_m7ty
    SEC
    SBC f:OW7FAR + 2, X         ; the party north of its row: in front
    BPL :+
    STA a:h_m7lfront
:   LDA f:OW7FAR, X             ; $80 + its art
    ASL A
    ASL A
    ASL A
    ASL A
    ORA a:h_m7n
    STA a:h_m7n                 ; the frame wanted: art * 16 + size
    JSR m7_hblock
    BCC :+
    RTS
:
    LDA f:OW7FAR + lut_M7BTile, X
    STA a:h_m7ftile             ; its tile in table 0
    LDX a:h_m7lptr
    LDA f:OW7FAR + 4, X
    STA a:h_m7gw                ; how many
    REP #$20
    .a16
    TXA
    CLC
    ADC #M7L_ROW
    STA a:h_m7addr              ; their columns
    SEP #$20
    .a8
@house:
    LDA a:h_m7hn
    CMP #M7H_MAX
    BCC :+
    RTS
:
    LDX a:h_m7addr
    LDA f:OW7FAR, X
    SEC
    SBC a:h_m7ox                ; columns from the first
    STA a:WRMPYA
    STA a:h_m7save + 2
    LDA a:h_m7cnt
    STA a:WRMPYB                ; * k's low byte (eight cycles)
    REP #$20
    .a16
    LDA a:h_m7cnt
    AND #$0100
    BEQ :+
    LDA a:h_m7save + 2          ; + its high bit's
    AND #$00FF
    XBA
:   CLC
    ADC a:RDMPYL
    CLC
    ADC #8
    LSR A
    LSR A
    LSR A
    LSR A                       ; (the columns * 16) * k / 256, rounded
    CLC
    ADC a:h_m7ocx
    SEC
    SBC #16                     ; its box's left
    CLC
    ADC #31                     ; on screen from -31 to 255
    CMP #256 + 31
    BCS @next16
    SEC
    SBC #31
    STA a:h_m7x
    LDA a:h_m7hn
    AND #$00FF
    STA a:h_m7pc
    ASL A
    ASL A
    ADC a:h_m7pc
    TAY                         ; five bytes each
    SEP #$20
    .a8
    LDA a:h_m7x
    STA a:M7HBUF + 0, Y
    LDA a:h_m7fbase             ; (a top above the screen wraps, as the SNES draws it)
    STA a:M7HBUF + 1, Y
    LDA a:h_m7ftile
    STA a:M7HBUF + 2, Y
    LDA #$20 | (4 << 1)         ; in front of the plane; OBJ palette 4; table 0
    STA a:M7HBUF + 3, Y
    LDA a:h_m7x + 1
    AND #$01                    ; x's ninth bit
    ORA #$02                    ; the large size, 32x32
    STA a:M7HBUF + 4, Y
    INC a:h_m7hn
@next:
    REP #$20
    .a16
@next16:
    INC a:h_m7addr
    SEP #$20
    .a8
    DEC a:h_m7gw
    BEQ :+
    JMP @house
:   RTS
@out16:
    SEP #$20
    .a8
    RTS


.a8
.i16
;;  After m7_project: on the screen enough to keep -- its base's x within
;;  64 of the screen, its base not above the top -- C clear, and its size,
;;  k in sixteenths from M7L_K0, in h_m7n; C set if not.  A8 I16.
m7_lsize:
    REP #$20
    .a16
    LDA a:h_m7ocx
    CLC
    ADC #64
    CMP #256 + 128
    BCS @off
    LDA a:h_m7oline
    BMI @off
    LDA a:h_m7cnt
    CLC
    ADC #8
    LSR A
    LSR A
    LSR A
    LSR A                       ; k in sixteenths, rounded
    SEC
    SBC #M7L_K0
    BPL :+
    LDA #0
:   CMP #M7L_FRAMES
    BCC :+
    LDA #M7L_FRAMES - 1
:   SEP #$20
    .a8
    STA a:h_m7n
    CLC
    RTS
@off:
    SEP #$20
    .a8
    SEC
    RTS


.a8
.i16
;;  The docked ship, tilted (at the flat angle the game draws it): when the
;;  party has it and is not aboard (the party's sprite is the ship
;;  then), placed at its tile's centre at the frame nearest its line's size
;;  -- 16 pixels times k, rounded, 8 to 24 -- 32x32 art 0 (m7_hput).  A8
;;  I16.
m7_lship:
    LDA a:h_m7lvl
    CMP #2
    BCC @out                    ; flat: the game's
    LDA f:SRAMFAR7 + ship_vis
    BEQ @out                    ; not the party's yet
    LDA z:vehicle
    CMP #$04
    BNE :+
@out:
    RTS                         ; (aboard)
:   LDA f:SRAMFAR7 + ship_x
    STA a:h_m7ox
    LDA f:SRAMFAR7 + ship_y
    STA a:h_m7oy
    REP #$20
    .a16
    STZ a:h_m7oux
    STZ a:h_m7ouy
    SEP #$20
    .a8
    JSR m7_project
    BCS @out
    REP #$20
    .a16
    LDA a:h_m7ocx
    CLC
    ADC #64
    CMP #256 + 128
    BCS @no16
    LDA a:h_m7cnt
    CLC
    ADC #8
    LSR A
    LSR A
    LSR A
    LSR A                       ; 16 * k / 256, rounded
    CMP #8
    BCS :+
    LDA #8
:   CMP #25
    BCC :+
    LDA #24
:   SEC
    SBC #8
    TAX
    SEP #$20
    .a8
    LDA f:OW7FAR + lut_M7ShipSize, X
    STA a:h_m7n                 ; art 0: its frame is its name
    LDA a:h_m7ty
    SEC
    SBC f:SRAMFAR7 + ship_y     ; the party north of its row: in front
    BPL :+
    STA a:h_m7lfront
:   JMP m7_hput
@no16:
    SEP #$20
    .a8
    RTS


.a8
.i16
;;  The block for 32x32 frame h_m7n: the one holding it (M7BREV); or one no
;;  house took this frame or the last, the frame uploaded there, if no 32x32
;;  upload waits; or one holding its art at another size, till its frame
;;  comes.  -> C clear, X the block, taken this frame (h_m7bused); C set
;;  none.  A8 I16; Y kept.
m7_hblock:
    REP #$20
    .a16
    LDA a:h_m7n
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA f:M7BREV, X             ; its block + 1, 0 none
    BEQ @new
    DEC A
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    BRA @have
@new:
    LDA a:h_m7bupon
    BNE @borrow
    REP #$20
    .a16
    LDA a:h_m7bused
    ORA a:h_m7bprev
    STA a:h_m7pc                ; taken this frame or the last
    LDX #0
:   LDA f:OW7FAR + lut_M7BBit, X
    AND a:h_m7pc
    BEQ @free
    INX
    INX
    CPX #32
    BCC :-
    SEP #$20
    .a8
    BRA @borrow
@free:
    .a16
    TXA
    LSR A
    TAX                         ; the block
    SEP #$20
    .a8
    JSR m7_bkeep                ; it holds this frame now
    JSR m7_bupload              ; (X and Y kept)
    BRA @have
@borrow:
    LDA a:h_m7n
    AND #$F0
    STA a:h_m7save + 3
    LDX #0
:   LDA a:h_m7bkey, X
    CMP #$FF
    BEQ :+
    AND #$F0
    CMP a:h_m7save + 3
    BEQ @have
:   INX
    CPX #16
    BCC :--
    SEC                         ; none: not drawn
    RTS
@have:
    JSR m7_bmark
    CLC
    RTS


.a8
.i16
;;  The docked ship at h_m7oline, h_m7ocx, frame h_m7n: its block
;;  (m7_hblock), and its 32x32 sprite into M7HBUF if it shows, its box
;;  centred on its tile's centre.  A8 I16.
m7_hput:
    LDA a:h_m7hn
    CMP #M7H_MAX
    BCS @out
    JSR m7_hblock
    BCS @out
    REP #$20
    .a16
    LDA a:h_m7ocx
    SEC
    SBC #16
    STA a:h_m7ftile             ; its box's left
    LDA a:h_m7oline
    SEC
    SBC #16                     ; its box's top
    CLC
    ADC #31                     ; on screen from -31 to 223
    CMP #224 + 31
    BCS @off
    SEC
    SBC #31
    STA a:h_m7fbase
    LDA a:h_m7ftile
    CLC
    ADC #31                     ; on screen from -31 to 255
    CMP #256 + 31
    BCS @off
    LDA a:h_m7hn
    AND #$00FF
    STA a:h_m7pc
    ASL A
    ASL A
    ADC a:h_m7pc
    TAY                         ; five bytes each
    SEP #$20
    .a8
    LDA a:h_m7ftile
    STA a:M7HBUF + 0, Y
    LDA a:h_m7fbase             ; (a top above the screen wraps, as the SNES draws it)
    STA a:M7HBUF + 1, Y
    LDA f:OW7FAR + lut_M7BTile, X
    STA a:M7HBUF + 2, Y
    LDA #$20 | ((M7SHIP_PAL + 4) << 1)  ; its palette in OBJ 4-7; table 0
    STA a:M7HBUF + 3, Y
    LDA a:h_m7ftile + 1
    AND #$01                    ; x's ninth bit
    ORA #$02                    ; the large size, 32x32
    STA a:M7HBUF + 4, Y
    INC a:h_m7hn
@out:
    RTS
@off:
    SEP #$20
    .a8
    RTS


.a8
.i16
;;  The candidate -- h_m7oline, h_m7ocx, frame h_m7n -- into M7LVIS, the
;;  nearest (the greatest line) first; past M7L_VIS, the farthest left out.
;;  A8 I16.
m7_lvisadd:
    REP #$20
    .a16
    LDA a:h_m7lnvis
    AND #$00FF
    ASL A
    ASL A
    ASL A
    STA a:h_m7pc                ; past the entries
    TAY
    ;  No nearer than the last kept, the common case (a group's members
    ;  come the nearest first): after it, if there is room.
    BEQ @find0
    CPY #8 * M7L_VIS
    BCS @find0
    LDA a:h_m7oline
    CMP a:M7LVIS - 8, Y         ; (both 0-400 here)
    BCC @put
    BEQ @put
@find0:
    LDY #0
@find:
    CPY a:h_m7pc
    BCS @insert
    LDA a:h_m7oline
    CMP a:M7LVIS, Y
    BCS @insert                 ; as near or nearer
    TYA
    CLC
    ADC #8
    TAY
    BRA @find
@insert:
    CPY #8 * M7L_VIS
    BCS @full                   ; farther than every one kept
    LDX a:h_m7pc
    CPX #8 * M7L_VIS
    BCC :+
    LDX #8 * (M7L_VIS - 1)      ; all kept: the farthest falls off
:   STY a:h_m7left
@shift:
    CPX a:h_m7left
    BEQ @put
    LDA a:M7LVIS - 8, X
    STA a:M7LVIS, X
    LDA a:M7LVIS - 6, X
    STA a:M7LVIS + 2, X
    LDA a:M7LVIS - 4, X
    STA a:M7LVIS + 4, X
    LDA a:M7LVIS - 2, X
    STA a:M7LVIS + 6, X
    TXA
    SEC
    SBC #8
    TAX
    BRA @shift
@put:
    LDA a:h_m7oline
    STA a:M7LVIS, Y
    LDA a:h_m7ocx
    STA a:M7LVIS + 2, Y
    SEP #$20
    .a8
    LDA a:h_m7n
    STA a:M7LVIS + 4, Y
    LDA a:h_m7lnvis
    CMP #M7L_VIS
    BCS :+
    INC a:h_m7lnvis
:   RTS
@full:
    SEP #$20
    .a8
    RTS


.a8
.i16
;;  Block X to hold frame h_m7n: h_m7bkey and M7BREV so, the frame it held
;;  no longer there.  A8 I16; X and Y kept.
m7_bkeep:
    PHX
    LDA a:h_m7bkey, X
    CMP #$FF
    BEQ @new
    REP #$20
    .a16
    AND #$00FF
    TAX
    SEP #$20
    .a8
    LDA #0
    STA f:M7BREV, X             ; the frame it held: in no block now
@new:
    PLX
    PHX
    LDA a:h_m7n
    STA a:h_m7bkey, X
    REP #$20
    .a16
    AND #$00FF
    TAX                         ; the frame it holds
    SEP #$20
    .a8
    LDA 1, S                    ; the block
    INC A
    STA f:M7BREV, X
    PLX
    RTS

.a8
.i16
;;  Block X taken this frame: its bit in h_m7bused.  A8 I16; X and Y kept.
m7_bmark:
    PHX
    REP #$20
    .a16
    TXA
    ASL A
    TAX
    LDA f:OW7FAR + lut_M7BBit, X
    ORA a:h_m7bused
    STA a:h_m7bused
    SEP #$20
    .a8
    PLX
    RTS


.a8
.i16
;;  Frame A (art * 16 + size) of a landmark into slot X, at the next flush:
;;  queued (M7UPQ).  A8 I16; X and Y kept.
m7_lupload:
    PHX
    PHY
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAX                         ; its record
    LDA a:h_m7upn
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAY                         ; the queue's next
    LDA f:OW7FAR + lut_M7LFrame, X      ; its tiles
    STA a:M7UPQ + 2, Y
    LDA f:OW7FAR + lut_M7LFrame + 5, X  ; how many
    AND #$00FF
    XBA
    LSR A
    LSR A
    LSR A                       ; 32 bytes each
    STA a:M7UPQ + 4, Y
    SEP #$20
    .a8
    LDA f:OW7FAR + lut_M7LFrame + 2, X  ; their bank
    STA a:M7UPQ + 6, Y
    LDA #$01                    ; read along
    STA a:M7UPQ + 7, Y
    REP #$20
    .a16
    LDA 3, S                    ; the slot
    ASL A
    TAX
    LDA f:OW7FAR + lut_M7LDst, X
    STA a:M7UPQ + 0, Y
    SEP #$20
    .a8
    INC a:h_m7upn
    LDA #1
    STA a:h_m7upon
    PLY
    PLX
    RTS

.a8
.i16
;;  32x32 frame h_m7n into block X, at the next flush: its four
;;  rows of four tiles queued (M7UPQ), each 16 tiles below the last, a row
;;  the frame has nothing in written from one zero byte.  A8 I16; X and Y
;;  kept.
m7_bupload:
    PHX
    PHY
    LDA a:h_m7n
    REP #$20
    .a16
    AND #$00FF
    ASL A
    ASL A
    TAX                         ; its record, four bytes
    LDA f:OW7FAR + lut_M7BFrame, X      ; its rows
    STA a:h_m7addr
    SEP #$20
    .a8
    LDA f:OW7FAR + lut_M7BFrame + 2, X  ; their bank
    STA a:h_m7save + 2
    LDA f:OW7FAR + lut_M7BFrame + 3, X  ; which rows it has
    STA a:h_m7save + 3
    REP #$20
    .a16
    LDA 3, S                    ; the block
    TAX
    LDA f:OW7FAR + lut_M7BTile, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC #VRAM_CHR               ; its first tile's word address
    STA a:h_m7save
    LDA a:h_m7upn
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAY                         ; the queue's next
    LDX #4
@row:
    SEP #$20
    .a8
    LSR a:h_m7save + 3          ; this row's bit
    BCC @zero
    LDA a:h_m7save + 2
    STA a:M7UPQ + 6, Y
    LDA #$01                    ; read along
    STA a:M7UPQ + 7, Y
    REP #$20
    .a16
    LDA a:h_m7addr
    STA a:M7UPQ + 2, Y
    CLC
    ADC #128
    STA a:h_m7addr
    BRA @dst
@zero:
    .a8
    LDA #^OW7FAR
    STA a:M7UPQ + 6, Y
    LDA #$09                    ; one byte read over and over
    STA a:M7UPQ + 7, Y
    REP #$20
    .a16
    LDA #.loword(m7_zero)
    STA a:M7UPQ + 2, Y
@dst:
    LDA a:h_m7save
    STA a:M7UPQ + 0, Y
    CLC
    ADC #16 * 16                ; the next row of tiles
    STA a:h_m7save
    LDA #4 * 32
    STA a:M7UPQ + 4, Y
    TYA
    CLC
    ADC #8
    TAY
    SEP #$20
    .a8
    INC a:h_m7upn
    DEX
    BNE @row
    LDA #1
    STA a:h_m7bupon
    PLY
    PLX
    RTS

;;  The slots: each one's first tile in the sprite table, its VRAM word
;;  address, its bit in h_m7lused.  The blocks: each one's first tile in
;;  table 0, its bit in h_m7bused.
lut_M7LTile:
    .WORD M7L_SLOT0, M7L_SLOT0 + M7L_SLOTW, M7L_SLOT0 + 2 * M7L_SLOTW
lut_M7LDst:
    .WORD VRAM_CHR + $1000 + M7L_SLOT0 * 16
    .WORD VRAM_CHR + $1000 + (M7L_SLOT0 + M7L_SLOTW) * 16
    .WORD VRAM_CHR + $1000 + (M7L_SLOT0 + 2 * M7L_SLOTW) * 16
lut_M7LBit:
    .BYTE $01, $02, $04
lut_M7BTile:
    .REPEAT 16, b
    .BYTE (b .MOD 4) * 4 + (b / 4) * 64
    .ENDREP
lut_M7BBit:
    .REPEAT 16, b
    .WORD 1 << b
    .ENDREP
m7_zero:
    .BYTE 0


;;  The extras in front of the party (A 1) or behind it (0): h_m7xfront so,
;;  for the flush, which turns OAM's priority round to start at the extras,
;;  entry 64, when they are in front (flush_oam); they stay at 64-127 and
;;  the game's at 0-63 either way.  Then the extras' first byte in
;;  OAMSHADOW at h_m7save + 4, and their high-table bytes zero.  A8 I16.
m7_front:
    STA a:h_m7xfront
    REP #$20
    .a16
    LDA #256
    STA a:h_m7save + 4          ; the extras' first byte
    LDX #16 - 2
:   STZ a:OAMSHADOW + 512 + 16, X
    DEX
    DEX
    BPL :-
    SEP #$20
    .a8
    RTS


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
