;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  snesmap.inc -- SNES memory map for the Final Fantasy 65816 port
;;
;;  ROM is HiROM (mode 21), FastROM, 8KB SRAM.
;;
;;  ROM bank 0  (SNES $C0 / $00 hi half) ...... HAL code + SNES header
;;  ROM bank 1+N (seen as $A1+N, N = $00..$0F) ... one NES "chunk":
;;        $8000-$BFFF   NES PRG bank N
;;        $C000-$FFFF   NES PRG bank $0F  (the fixed bank -- copied 16x)
;;
;;  Game code executes with PBR = $81+N so that the low half of the bank
;;  exposes the SNES I/O map, which lines up with the NES map beautifully:
;;
;;        $0000-$1FFF   WRAM      (NES RAM lives at $0000-$07FF)
;;        $2100-$21FF   PPU regs
;;        $4200-$44FF   CPU regs / DMA
;;        $6000-$7FFF   SRAM      (NES PRG-RAM, $6000-$7FFF, verbatim)
;;        $8000-$FFFF   ROM
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

; --- Bank numbers -------------------------------------------------------
HALBANK         = $C0           ; HAL code lives here (long-addressed)
HALFAR          = HALBANK * $10000
CHUNK0          = $A1           ; PBR for NES bank $00; NES bank N -> CHUNK0+N
                                ;
                                ; $A1 rather than $81 on purpose.  A HiROM cart
                                ; is only guaranteed to decode its SRAM at
                                ; $6000-$7FFF in banks $20-$3F and $A0-$BF;
                                ; $80-$9F is open bus on many boards.  In a 2MB
                                ; image bank $A0+n mirrors $80+n exactly, so
                                ; running up there costs nothing and puts the
                                ; NES's PRG-RAM somewhere it certainly exists.

; --- SNES PPU registers -------------------------------------------------
INIDISP         = $2100
OBSEL           = $2101
OAMADDL         = $2102
OAMADDH         = $2103
OAMDATA         = $2104
BGMODE          = $2105
MOSAIC          = $2106
BG1SC           = $2107
BG2SC           = $2108
BG3SC           = $2109
BG4SC           = $210A
BG12NBA         = $210B
BG34NBA         = $210C
BG1HOFS         = $210D
BG1VOFS         = $210E
BG2HOFS         = $210F
BG2VOFS         = $2110
BG3HOFS         = $2111
BG3VOFS         = $2112
VMAIN           = $2115
VMADDL          = $2116
RDVRAML         = $2139         ; VRAM read port, low / high
RDVRAMH         = $213A
VMADDH          = $2117
VMDATAL         = $2118
VMDATAH         = $2119
CGADD           = $2121
CGDATA          = $2122
W12SEL          = $2123
WH0             = $2126
WH1             = $2127
WH2             = $2128
WH3             = $2129
WBGLOG          = $212A
TM              = $212C
TS              = $212D
TMW             = $212E
CGWSEL          = $2130
CGADSUB         = $2131
COLDATA         = $2132
SETINI          = $2133
RDNMI           = $4210
TIMEUP          = $4211
HVBJOY          = $4212
RDIO            = $4213

NMITIMEN        = $4200
WRIO            = $4201
MEMSEL          = $420D
MDMAEN          = $420B
HDMAEN          = $420C
JOY1L           = $4218
JOY1H           = $4219

; DMA channel 0
DMAP0           = $4300
BBAD0           = $4301
A1T0L           = $4302
A1T0H           = $4303
A1B0            = $4304
DAS0L           = $4305
DAS0H           = $4306

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  WRAM layout
;;
;;  $7E:0000-$07FF  NES RAM (also visible as $00:0000-$07FF -- the game's own)
;;  $7E:0800-$0FFF  free (NES never touches it; visible in bank $00 too)
;;  $7E:1000-$1FFF  free
;;  $7E:2000+       HAL private -- only reachable via long addressing / DBR=$7E
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

; ------------------------------------------------------------------------
;  HAL RAM.  $0800-$1FFF is WRAM that the NES game never touches, and it is
;  absolutely addressable from every bank we ever run code in (DBR is always
;  one of $81..$90, all of which expose the standard low-bank I/O map).
;  Anything bigger lives at $7E:2000+ and is reached with long addressing.
; ------------------------------------------------------------------------

HAL_VARS        = $0800         ; scalars, see halvars below
APUSHADOW       = $0900         ; $20 bytes: last value written to $4000-$401F
NTCOLLO         = $0940         ; $20 bytes: per-row dirty column low water mark
NTCOLHI         = $0960         ; $20 bytes: per-row dirty column high water mark
OAMSHADOW       = $0A00         ; 544 bytes: SNES OAM image (512 low + 32 high)
NTSHADOW        = $1000         ; 4KB: 64x32 tilemap words (NES rows 0..29 used)

NESNT           = $7E4000       ; 2KB: raw NES nametable RAM (readback+attribs)
NESPAL          = $7E4800       ; $20 bytes: raw NES palette RAM
CGSHADOW        = $7E4900       ; 512 bytes: CGRAM image
CHRSHADOW       = $7E8000       ; 16KB: 512 tiles in SNES 4bpp order

; ------------------------------------------------------------------------
;  Graphics format
;
;  The NES stores a tile as eight bytes of bitplane 0 followed by eight bytes
;  of bitplane 1.  The SNES interleaves the planes by row.  Byte i of a NES
;  tile therefore lands at 2i for i < 8 and at 2i-15 for i >= 8 -- the same
;  permutation for 2bpp and 4bpp, only the tile stride differs.
;
;  The shadow keeps every tile in *4bpp* form, with bitplanes 2 and 3 left
;  permanently zero.  That costs 16KB of WRAM and 16KB of VRAM, and buys a
;  single copy of the pattern data that BG1 and the sprites can share: the NES
;  has 2bpp backgrounds and 2bpp sprites, the SNES has 4bpp for both in mode 1,
;  and the low two planes of a 4bpp tile are bit-for-bit a 2bpp tile.
; ------------------------------------------------------------------------

; --- SNES VRAM layout (word addresses) ----------------------------------
VRAM_BG1MAP     = $0000         ; $0000-$0FFF  64x64 tilemap, 4 x $400 words
VRAM_BG3MAP     = $1000         ; $1000-$13FF  32x32 tilemap (dialog window)
VRAM_CHR        = $2000         ; $2000-$3FFF  512 tiles, 4bpp (16KB)
                                ;   BG1 char base  = $2000  (tiles 0-255)
                                ;   OBJ name base  = $2000, gap 0
                                ;     -> OBJ tiles 0-255 at $2000 (NES table 0)
                                ;        OBJ tiles 256-511 at $3000 (table 1)

; ------------------------------------------------------------------------
;  CGRAM
;    BG palette p, colour c  ->  entry p*16 + c        (p = 0..3, c = 0..3)
;    OBJ palette p, colour c ->  entry 128 + p*16 + c
;    Entry 0 doubles as the backdrop, which is what NES $3F00 means.
; ------------------------------------------------------------------------

; ------------------------------------------------------------------------
;  HAL scalars
; ------------------------------------------------------------------------
h_ppuctrl       = HAL_VARS+$00  ; soft $2000
h_ppumask       = HAL_VARS+$01  ; soft $2001
h_addr          = HAL_VARS+$02  ; 2 bytes: PPU address, as set through $2006
h_latch         = HAL_VARS+$04  ; $2005/$2006 first-or-second write toggle
h_scrollx       = HAL_VARS+$05
h_scrolly       = HAL_VARS+$06
h_readbuf       = HAL_VARS+$07  ; the PPU's one-byte $2007 read delay
h_data          = HAL_VARS+$08  ; 2 bytes: the byte currently being written
h_t0            = HAL_VARS+$0A  ; 2-byte scratch
h_t1            = HAL_VARS+$0C
h_t2            = HAL_VARS+$0E
h_chrlo         = HAL_VARS+$10  ; 2 bytes: dirty span in the pattern shadow
h_chrhi         = HAL_VARS+$12
h_ntdirty       = HAL_VARS+$16  ; nonzero if any tilemap row changed
h_render        = HAL_VARS+$17
h_oamdirty      = HAL_VARS+$18
h_curbank       = HAL_VARS+$19  ; the NES PRG bank currently selected
h_frame         = HAL_VARS+$1A  ; 2 bytes
h_spr0hit       = HAL_VARS+$1C  ; synthesised $2002 bit 6

; ------------------------------------------------------------------------
;  HAL scalars (continued)
; ------------------------------------------------------------------------
h_t3            = HAL_VARS+$20  ; 2-byte scratch
h_t4            = HAL_VARS+$22
h_t5            = HAL_VARS+$24
h_paldirty      = HAL_VARS+$26  ; nonzero when NES palette RAM has changed
h_sprtable      = HAL_VARS+$27  ; 0 or 1: OBJ tile-number high bit
h_oambase       = HAL_VARS+$28  ; 2 bytes: source page for the last OAM DMA
h_pal           = HAL_VARS+$2A  ; 4 bytes: expanded attribute palette bytes
h_row           = HAL_VARS+$2E  ; 2 bytes
h_col           = HAL_VARS+$30  ; 2 bytes
h_brightness    = HAL_VARS+$32  ; INIDISP value to restore after a flush
h_c0            = HAL_VARS+$34  ; 2 bytes: dirty span, first column
h_c1            = HAL_VARS+$36  ; 2 bytes: dirty span, last column
h_dstrow        = HAL_VARS+$38  ; 2 bytes: tilemap row being written
h_joyshift      = HAL_VARS+$3A  ; serial shift register for raw $4016 reads

WRAMBANK        = $7E           ; DMA source bank for anything in WRAM

; Scanlines cropped from the top of the NES's 240-line picture, matching what a
; television hid.  The SNES's 224 lines then show NES lines 8..231.
NES_TOP_CROP    = 8

h_emphasis      = HAL_VARS+$3B  ; $2001 bits 7-5, as R/G/B in bits 2-0
h_greyscale     = HAL_VARS+$3C  ; $2001 bit 0

; Diagnostic (CHRDUMP): consecutive frames whose CHR dirty span was huge, and a
; latch so the capture happens once.  Both are 2 bytes and only ever touched
; 16-bit -- a byte flag read with a 16-bit load picks up its neighbour.
h_dumpcnt       = HAL_VARS+$40
h_dumpdone      = HAL_VARS+$42

; DMA channel 1, used for the raster-split HDMA
DMAP1           = $4310
BBAD1           = $4311
A1T1L           = $4312
A1B1            = $4314
SLHV            = $2137         ; reading it latches the H/V counters
OPVCT           = $213D         ; vertical counter
STAT78          = $213F         ; reading it resets the counter read toggle

h_rastercount   = HAL_VARS+$3D  ; mid-frame $2001 writes recorded this frame
h_tmcur         = HAL_VARS+$3E  ; TM as of the most recent $2001 write
RASTERLINE      = $0980         ; 16 entries: scanline of each split
RASTERTM        = $0990         ; 16 entries: TM value from that split
HDMATAB         = $09A0         ; the HDMA table we build from them
h_prevmask      = HAL_VARS+$3F  ; $2001 as it was before the current write
h_tmframestart  = HAL_VARS+$40  ; TM in force at the top of the frame

; The game's own soft copy of $2000, at zero page $FF (variables.inc calls it
; soft2000).  The NES build's NMI handler pushed this to the PPU every frame.
NES_soft2000    = $00FF

; Raster splits: recording mid-frame $2001 writes and replaying them as an HDMA
; table reproduces the map-transition wipe, but it introduces visible glitches
; elsewhere that are more distracting than the missing effect.  Off until the
; game is properly playable; the machinery stays in place for when it is.
ENABLE_RASTER_SPLITS = 0

; DMA channel 2, used for the dialogue box's nametable split
DMAP2           = $4320
BBAD2           = $4321
A1T2L           = $4322
A1B2            = $4324

; A mid-frame $2000 write swaps which nametable is on screen.  With vertical
; mirroring the two nametables sit side by side in one 64-wide tilemap, so the
; SNES equivalent is simply adding 256 to the horizontal scroll -- which HDMA
; can do per scanline.
NTSPLITLINE     = $0920         ; 8 entries: scanline of each split
NTSPLITLO       = $0928         ; 8 entries: horizontal scroll, low byte
NTSPLITHI       = $0930         ; 8 entries: ...and high byte
HOFSTAB         = $0C20         ; the HDMA table built from them

h_ntsplits      = HAL_VARS+$41  ; mid-frame $2000 writes recorded this frame
h_prevctrl      = HAL_VARS+$42  ; $2000 as it was before the current write
h_hofsframestart = HAL_VARS+$43 ; 2 bytes: scroll in force at the top of frame
h_ctrlwrites    = HAL_VARS+$45  ; $2000 writes seen so far this frame
h_rasterwin     = HAL_VARS+$46  ; nonzero while a deliberate raster split is due
h_ntsrc         = HAL_VARS+$47  ; 2 bytes: tilemap shadow address being sent
h_vdst          = HAL_VARS+$49  ; 2 bytes: tilemap row base being written
h_vdst0         = HAL_VARS+$4B  ; 2 bytes: ...for the copy at row r
h_vdst1         = HAL_VARS+$4D  ; 2 bytes: ...and the copy at row r+30
h_ntsrc2        = HAL_VARS+$4F  ; 2 bytes: source address of the span in flight
NESPALPREV      = $7E4820       ; 32 bytes: palette as CGRAM last saw it
h_palforce      = HAL_VARS+$51  ; rewrite every CGRAM entry, not just changes
GATHERBUF       = $0C80         ; 128 bytes: one tilemap column, made contiguous
h_gcol          = HAL_VARS+$53  ; 2 bytes: column being sent
h_gcount        = HAL_VARS+$55  ; 2 bytes: loop counter / dirty row tally
h_ncols         = HAL_VARS+$57  ; 2 bytes: columns left to send

ENABLE_COLUMN_FLUSH = 1    ; single-DMA column path
h_palwrites     = HAL_VARS+$59  ; $2007 writes into palette space this frame
h_himin         = HAL_VARS+$5A  ; lowest $2006 high byte seen this frame
h_himax         = HAL_VARS+$5B  ; highest
h_hicount       = HAL_VARS+$5C  ; how many high bytes were written
h_addrhigh      = HAL_VARS+$5E  ; 2 bytes: a CHR write landed at or above $1000
