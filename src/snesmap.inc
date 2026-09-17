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
TRACEFAR        = $A06000       ; NO LONGER A PRIVATE PAGE.  With 8KB of SRAM
                                ; every bank aliases the same 8KB, so this is
                                ; the game's own PRG-RAM and writing here
                                ; corrupts it.  The SCROLLSTAT trace that used
                                ; this is therefore unusable; instrument the
                                ; emulator instead, which is what actually found
                                ; the last two bugs.
CHUNK0          = $A1           ; PBR for NES bank $00; NES bank N -> CHUNK0+N
                                ;
                                ; $A1 rather than $81 on purpose.  A HiROM cart
                                ; is only guaranteed to decode its SRAM at
                                ; $6000-$7FFF in banks $20-$3F and $A0-$BF;
                                ; $80-$9F is open bus on many boards.  In a 2MB
                                ; image bank $A0+n mirrors $80+n exactly, so
                                ; running up there costs nothing and puts the
                                ; NES's PRG-RAM somewhere it certainly exists.

;  Chunk numbers above the NES's sixteen.  Chunk N runs at PBR CHUNK0+N, and
;  in a 2MB image that masks to ROM image bank 1+N, so the usable range is
;  chunks $00..$1E (PBR $A1..$BF).  $00..$0F are the NES's own banks; chunk $10
;  is spoken for because image bank 17 is the altar beam's HDMA tables
;  (BEAMBANK), which is why the first bank this project adds is $11 rather than
;  $10.  mkrom stamps the fixed bank into $C000-$FFFF of every one of them, so
;  a routine here sees the same address space the game's own banks do and
;  reaches the fixed bank with a plain 16-bit JSR.
CHUNK_OPT       = $11           ; the options bank: menu, presets, option block
OPTFAR          = (CHUNK0 + CHUNK_OPT) * $10000

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The ending scene's draw buffer, moved out of PRG-RAM
;;
;;  'The End' plots itself a pixel at a time and needs a RAM shadow of the CHR
;;  it is drawing into, because it read-modify-writes each byte.  On the NES
;;  that shadow sat at $6800 for $700 bytes, overlaid on the battle RAM -- the
;;  two are never live at once, so the overlap costs nothing.
;;
;;  It is moved here so the 256 bytes at $6E00-$6EFF come free.  That page is
;;  the only part of the 8KB the ending buffer claims *alone*: everything below
;;  it is also battle RAM or the lineup menu's stat copies (lutmp_ch_magic is a
;;  full page at $6D00, so $6DB2 is NOT free -- rearranging the party would
;;  overwrite anything put there).  $6E00 is what the option block uses.
;;
;;  EVERY PATCH TO A GAME BANK MUST BE BYTE-NEUTRAL.  The banks position their
;;  data by sequential assembly -- there is no .org and no .res -- and other
;;  banks reach that data through absolute addresses baked into Constants.inc
;;  (lut_OrbCHR = $B600 in this very bank) and through pointer tables inside
;;  the data itself.  Shrinking this scene's clear loop by 24 bytes moved the
;;  orb CHR, the story text and the credits, which showed up as wrong orb
;;  graphics and text strings missing their first 24 characters.  convert.py
;;  now asserts every .INCBIN lands on the address its filename states, so a
;;  size change is a build error rather than a corrupted image.
THEENDBANK      = $7F
THEENDBUF       = $6800         ; same 16-bit address as before, but in bank
                                ; $7F.  Keeping the offset identical is what
                                ; lets TheEnd_SetPixel's "+ $6000" stand and
                                ; keeps both patches byte-for-byte the same
                                ; size as the code they replace -- see below.

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The option block
;;
;;  Battery-backed, global, and deliberately outside the save block at
;;  $6400-$67FF: SaveGame copies that range wholesale out of unsram and
;;  VerifyChecksum sums exactly those $400 bytes, so anything living there
;;  would be per-save and would fight the game's own checksum.  Options are
;;  global and survive starting a new game.
;;
;;  Integrity is the game's own scheme -- two assertion bytes and a sum forced
;;  to $FF -- plus a format version, because an option block changes shape
;;  between builds and a stale block that still checksums is worse than one
;;  that is obviously absent.  A version mismatch falls back to a preset.
OPTBLOCK        = $6E00
OPT_MAGIC0      = OPTBLOCK+$00  ; $53 'S'
OPT_MAGIC1      = OPTBLOCK+$01  ; $46 'F'
OPT_VERSION     = OPTBLOCK+$02  ; OPT_FORMAT below
OPT_PRESET      = OPTBLOCK+$03  ; 0..2 preset, 3 = custom
OPT_FLAGS       = OPTBLOCK+$04  ; 4 bytes: 26 checkbox bits
OPT_GOLDXP      = OPTBLOCK+$08  ; step indices into the value-row tables
OPT_ENCOUNTER   = OPTBLOCK+$09
OPT_ENEMY       = OPTBLOCK+$0A
OPT_BOSS        = OPTBLOCK+$0B
OPT_RESPOND     = OPTBLOCK+$0C  ; 0-based, so the default 8 is stored as 7
OPT_CKSUM       = OPTBLOCK+$0D
OPT_SIZE        = $0E

OPT_MAGIC0_VAL  = $53
OPT_MAGIC1_VAL  = $46
OPT_FORMAT      = $02           ; bumped from $01: blocks written before the
                                ; options bank set its data bank correctly hold
                                ; garbage flags behind a valid checksum, so the
                                ; version is what retires them.  Bump this
                                ; whenever the block's meaning changes, not
                                ; just its layout.
OPT_RESPOND_DEFAULT = 7         ; 0-based, so this is the 8 the menu shows

;  The option flags, one bit each.  Here rather than in optbank.asm because a
;  feature's hook is wherever the feature lives -- the fixed bank and the game
;  banks test these too, not just the options bank.
;
;  Bits 0..7 are in OPT_FLAGS+0, 8..15 in +1, and so on, so a test is
;  "LDA OPT_FLAGS+n / AND #mask".  The OPTFB_/OPTFM_ pairs below give the
;  byte and the mask for the ones that have hooks so far.
;  Flag bits, low byte first.  26 of the 32 are spoken for.
OPTF_SPEEDHACKS   = $00000001
OPTF_FASTWALK     = $00000002
OPTF_FASTSHIP     = $00000004
OPTF_NOSHUFFLE    = $00000008
OPTF_IDTREASURE   = $00000010
OPTF_OPENCHESTS   = $00000020
OPTF_BUYQTY       = $00000040
OPTF_RUNWAIT      = $00000080
OPTF_MAGICWRAP    = $00000100
OPTF_AUTORETARGET = $00000200
OPTF_AUTOSORT     = $00000400
OPTF_REPEATPOTION = $00000800
OPTF_SHOPINFO     = $00001000
OPTF_CHESTINFO    = $00002000
OPTF_GUILLOTINE   = $00004000
OPTF_HOUSEMP      = $00008000
OPTF_WEAPONSTATS  = $00010000
OPTF_SPELLFIXES   = $00020000
OPTF_STATUSATK    = $00040000
OPTF_THIEFNINJA   = $00080000
OPTF_CRITRATE     = $00100000
OPTF_ELEMBONUS    = $00200000
OPTF_IMPCURE      = $00400000
OPTF_IMPFIRE      = $00800000
OPTF_CASTLIFE     = $01000000
OPTF_LOK2         = $02000000

;  The three groups, as the menu lists them.  ca65 has no line continuation,
;  so these are built up a group at a time rather than written as one run-on.

;  Byte and mask for each flag that something outside the options bank tests.
;  Derived bytes, recomputed by opt_derive whenever the block changes.
;
;  A feature whose only effect is a constant is cheapest to implement by
;  turning that constant into a load -- but the constants live in code that is
;  reached far too often to test a flag at.  So the flags are cooked down once,
;  here, and the use site just loads a byte.
OPTD            = OPTBLOCK+$10  ; the derived block, below the option block
OPTD_WIPEOPEN_U = OPTD+$00      ; ScreenWipe_Open's two step sizes...
OPTD_WIPEOPEN_D = OPTD+$01
OPTD_WIPECLOSE_D= OPTD+$02      ; ...and ScreenWipe_Close's
OPTD_WIPECLOSE_U= OPTD+$03
OPTD_DLGOPEN    = OPTD+$04      ; the dialogue box's two step sizes
OPTD_DLGCLOSE   = OPTD+$05
OPTD_BTLTRANS   = OPTD+$06      ; how long the battle transition runs
OPTD_LINEUP     = OPTD+$07      ; pixels per frame in the lineup menu
OPTD_PALCYC     = OPTD+$08      ; frame mask for the palette cycle
OPTD_MSGROWS    = OPTD+$09      ; message rows drawn per frame, opening
OPTD_MSGROWSREV = OPTD+$0A      ; ...and closing
OPTSCRATCH      = OPTBLOCK+$20  ; a byte the option code may use freely

;  Vanilla steps, and the speed-hack ones.  Open must divide 224 and close 220,
;  or the wipe overshoots its end condition and runs off.
WIPE_OPEN_U_SLOW  = 2
WIPE_OPEN_D_SLOW  = 4
WIPE_OPEN_U_FAST  = 8
WIPE_OPEN_D_FAST  = 16
WIPE_CLOSE_D_SLOW = 2
WIPE_CLOSE_U_SLOW = 4
WIPE_CLOSE_D_FAST = 10
WIPE_CLOSE_U_FAST = 20

;  The dialogue box grows from scanline 8 to $60 and retracts to below $12.
;  Both loops compare with BCC/BCS rather than for equality, so any step
;  terminates -- unlike the closing wipe, which tests CMP #1 exactly.
DLG_OPEN_SLOW   = 2
DLG_CLOSE_SLOW  = 3
DLG_OPEN_FAST   = 11
DLG_CLOSE_FAST  = 11

;  The battle transition runs a counter to this.  The noise sweep it plays
;  lasts $20, so below that the sound outlives the picture.
BTLTRANS_SLOW   = $41
BTLTRANS_FAST   = $11

;  Explosions per enemy, and the delay after running.  These live in banks
;  $0B and $0C, which have no free bytes, so the sites pass the vanilla value
;  in A and a stand-in in the fixed bank decides -- which keeps every call
;  site exactly the size of the "LDA #n / STA x" pair it replaces.
EXPLODE_FAST    = 4
RUNDELAY_FAST   = 4

;  The lineup menu slides characters between slots a pixel at a time.  Four of
;  the six sites compare for equality, so the step has to divide the distances
;  exactly or the sprite oscillates past its target forever.  The slots sit at
;  Y $38/$58/$78/$98 -- 32 apart -- and the horizontal moves cover 16, so 4
;  divides every one of them.  tools/test_options.py runs the animation to
;  convergence rather than taking that on trust.
LINEUP_SLOW     = 1
LINEUP_FAST     = 4

;  CyclePalettes ANDs a frame counter with this and steps the cycle when the
;  result is zero, so 3 is every fourth frame and 0 is every frame.
PALCYC_SLOW     = $03
PALCYC_FAST     = $00

;  The battle message buffer is twelve rows.  Opening draws one per frame and
;  closing two, so twelve frames and six; Speed Hacks makes it two and three,
;  for six and four.  Rows per frame rather than a frame count, because the
;  twelve rows have to be drawn either way -- shortening the count alone would
;  leave the box half drawn.
MSGROWS_TOTAL   = 12
MSGROWS_SLOW    = 1
MSGROWS_FAST    = 2
MSGROWSREV_SLOW = 2
MSGROWSREV_FAST = 3

;  Behaviour flags for a repositioned NPC: not in a room, and stationary.
;  ($80 is inroom, $40 is don't move -- see mapobj_flgs in variables.inc.)
NPCMOVE_FLAGS   = $40

OPTFB_SPEEDHACKS = OPT_FLAGS+0
OPTFM_SPEEDHACKS = $01

OPTFB_GUILLOTINE = OPT_FLAGS+1
OPTFM_GUILLOTINE = $40   ; bit 14

OPTFB_NOSHUFFLE = OPT_FLAGS+0
OPTFM_NOSHUFFLE = $08

OPTFB_MAGICWRAP = OPT_FLAGS+1
OPTFM_MAGICWRAP = $01    ; bit 8

OPTFB_AUTOSORT  = OPT_FLAGS+1
OPTFM_AUTOSORT  = $04    ; bit 10

OPTFB_AUTORETARGET = OPT_FLAGS+1
OPTFM_AUTORETARGET = $02 ; bit 9

;  Which page of the battle magic list is showing, 0 or 1.  The disassembly
;  writes it as a bare address; it is named here because the option code needs
;  it too and a second bare $6AF8 would be unsearchable.
btl_magicpage   = $6AF8

PRESET_VANILLA  = 0
PRESET_IMPROVED = 1
PRESET_DELUXE   = 2
PRESET_CUSTOM   = 3


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
WOBJSEL         = $2125         ; OBJ and colour window enables
CGWSEL          = $2130
CGADSUB         = $2131
COLDATA         = $2132
SETINI          = $2133
APUIO0          = $2140         ; the four SPC700 I/O ports
APUIO1          = $2141
APUIO2          = $2142
APUIO3          = $2143


RDNMI           = $4210         ; bit 7 latches "a vblank has begun", set
                                ; whether or not NMI is enabled, and cleared by
                                ; reading it.  Clearing it at the end of a flush
                                ; and testing it on the next entry says whether a
                                ; whole hardware frame passed while the game was
                                ; working -- one the game never got to update,
                                ; which no counter indexed by WaitForVBlank
                                ; calls can see.
TIMEUP          = $4211
HVBJOY          = $4212
RDIO            = $4213

WRMPYA          = $4202         ; 8x8 -> 16 multiply: A x B lands in
WRMPYB          = $4203         ;   RDMPYL/H eight CPU cycles later
RDMPYL          = $4216
RDMPYH          = $4217

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

;  Which altar the player stepped on, kept for the duration of the altar
;  effect.  It holds the tile's special code -- $18/$1A/$1C/$1E for
;  earth/fire/water/air -- captured from altareffect before DoAltarEffect
;  clears it.  $6D..$7B is a genuine hole in the NES variable map: nothing in
;  variables.inc names it and no instruction in any bank addresses it.
altarorb        = $006D

;  The altar beam, as the flush needs it: which scanline it starts on, how many
;  it covers, and whether it is running at all.  hal_altarband records these
;  once a frame from the game's own loop; flush_altar turns them into spans.
h_altaron       = HAL_VARS+$AB

;  The four altars' tile special codes, as altarorb carries them.  Named
;  separately from Constants.inc's TP_SPEC_*ORB because the generated banks
;  include both that and this, and ca65 will not have a symbol defined twice.
;  These are frozen NES data, so the two cannot drift apart in practice.
ORB_EARTH       = $18
ORB_FIRE        = $1A
ORB_WATER       = $1C
ORB_AIR         = $1E

;  How hard the beam adds light, as COLDATA's five-bit level.  Half is a
;  starting point to look at, not a tuned value.
ALTARLEVEL      = 16

;  What the two channels a tint does not own are lifted to.  Keeps a coloured
;  beam brightening rather than merely tinting; white ignores it, being all
;  three channels at ALTARLEVEL already.
ALTARFLOOR      = 6

;  The water orb's green, lifted above the floor to carry it from flat blue
;  toward cyan.  Its own constant rather than a shared one: the other three
;  tints read correctly with the floor alone, and blue is the one that needs
;  help, being the darkest channel to begin with.
ALTARWATERG     = 11

;  The same trick for the other two tints, each with its own step because each
;  wants a different amount.  Cyan wants its green close to its blue; orange
;  wants green at roughly half its red; a warmer green wants rather less red
;  than that.  One constant apiece, so none of them has to be a compromise.
ALTARFIREG      = 9
ALTAREARTHR     = 10

;  Half-width of the cone at its apex, and the table its edges are built in.
;  The apex sits under the player, who is always centred in this game, so the
;  beam is symmetric about x=128 and widens by one pixel each side every two
;  scanlines above that.  Two bytes a line, repeat-mode, so the worst case is
;  the tallest band the effect reaches -- 108 lines -- plus the spans above and
;  below it: well under the 240 bytes reserved before NTSHADOW at $1000.

;  How many scanlines share one half-width.  The table is built once a frame in
;  vblank, so its cost is the number of runs, not the height of the band: at one
;  run per two lines the flush overran vblank and put a black band across the
;  top of the picture, sliding down as the beam grew and back up as it shrank.
;  Eight lines a step makes the edge a staircase of four-pixel treads, which on
;  a beam this size reads as an edge rather than as steps -- and the original
;  was a hard-edged rectangle, so the aesthetic has room for it.

;  How far the whole band is lifted from where the NES put it.  The NES counts
;  its delay from the top of the frame and lands the bottom edge around
;  scanline 140, which is some 28 lines below the centre of the screen -- and
;  the player, who this game always keeps centred, is what the light is meant
;  to be rising out of.  Lifting the band by that much puts the apex under the
;  sprite, where a narrow tip disappears behind it.

;  Where the apex sits horizontally.  Not 128: the picture the port puts on
;  screen is not centred on the player quite the way a bare 256-pixel frame
;  would be, and 120 is what actually lines the tip up under the sprite.

;  Pulls the left edge in by this much without moving the right, so the cone
;  can sit on a half pixel.  120 read a shade right and 119 a shade left, and
;  there is nothing between them: trimming one side is the only way to split
;  the difference when the apex is an integer.

;  A band whose top lands within this many scanlines of the top of the screen
;  is taken all the way there, the band growing downward-fixed so its bottom
;  does not move.  Full expansion leaves the top around scanline 2, close
;  enough that whether it reached the edge looked inconsistent; this removes
;  the question rather than relying on the arithmetic landing on zero.
;  The beam's HDMA tables live in ROM, one per frame of the animation, built
;  by tools/genbeam.py and placed by mkrom.py at its own image bank.  HiROM
;  maps image bank N to SNES bank $C0+N.
BEAMBANK        = $D1
BEAMFAR         = $D10000

;  Where each variant's per-frame index array starts inside that bank.  Fixed
;  rather than packed so the HAL reaches either with one long-indexed load and
;  an eight-bit frame index.  Variant 0 is the plain beam; variant 1 is the
;  water orb's, which sways.  genbeam.py asserts the frame count still fits.
BEAMOFF0        = $0004         ; plain: earth and fire
BEAMOFF1        = $0100         ; water: a long, slow ripple
BEAMOFF2        = $0200         ; air: short crests, reading as rising smoke

h_altarframe    = HAL_VARS+$B4  ; which frame of the animation is showing
                                ; game's own height even when the band is not

;  A staging buffer for hal_ntblit, in the free WRAM below NESNT.  Callers
;  build a row of nametable bytes here and hand the whole run to the HAL at
;  once, instead of paying the thunk and the full $2007 conversion per tile --
;  which is the difference between a menu row costing a couple of hundred
;  cycles and costing several thousand.
NTSTAGE         = $7E3F00       ; 64 bytes, two more than a row needs
NTSTAGE_A       = $3F00         ; ...as seen with DBR = $7E, which is how the
                                ; blit reaches it, NESNT and NTSHADOW with
                                ; ordinary absolute addressing and both index
                                ; registers free

NESNT           = $7E4000       ; 2KB: raw NES nametable RAM (readback+attribs)
NESPAL          = $7E4800       ; $20 bytes: raw NES palette RAM
CGSHADOW        = $7E4900       ; 512 bytes: CGRAM image

; Frame at which SCROLLSTAT copies its ring out to SRAM; -D DUMPFRAME=n to move
.ifndef DUMPFRAME
DUMPFRAME       = 1800
.endif
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
h_t6            = HAL_VARS+$14  ; 2-byte scratch (nt_attr's row offset)
h_ntdirty       = HAL_VARS+$16  ; nonzero if any tilemap row changed
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
h_pal           = HAL_VARS+$2A  ; 4 bytes: expanded attribute palette bytes
h_row           = HAL_VARS+$2E  ; 2 bytes
h_col           = HAL_VARS+$30  ; 2 bytes
h_c0            = HAL_VARS+$34  ; 2 bytes: dirty span, first column
h_c1            = HAL_VARS+$36  ; 2 bytes: dirty span, last column
h_joyshift      = HAL_VARS+$3A  ; serial shift register for raw $4016 reads

WRAMBANK        = $7E           ; DMA source bank for anything in WRAM

; Scanlines cropped from the top of the NES's 240-line picture, matching what a
; television hid.  The SNES's 224 lines then show NES lines 8..231.
NES_TOP_CROP    = 8

h_emphasis      = HAL_VARS+$3B  ; $2001 bits 7-5, as R/G/B in bits 2-0
h_greyscale     = HAL_VARS+$3C  ; $2001 bit 0

; Diagnostic (SCROLLSTAT): frames that arrived at WaitForVBlank already inside
; vblank -- i.e. too late for it, so the game waits out a whole extra frame --
; and frames whose flush ran past the end of vblank.
h_ringidx       = HAL_VARS+$48
h_lastx         = HAL_VARS+$4A   ; final BG1HOFS, as the PPU sees it
h_arrive        = HAL_VARS+$4C   ; scanline the game reached WaitForVBlank on
h_lasty         = HAL_VARS+$4E   ; final BG1VOFS, as the PPU sees it
h_lastxhi       = HAL_VARS+$50   ; BG1HOFS high byte: the nametable-select bit
h_flushend      = HAL_VARS+$52   ; scanline the flush finished on
h_stage         = HAL_VARS+$54   ; 6 bytes: scanline after each flush stage,
                                ; slot 5 = the moment the vblank wait returned
h_missed        = HAL_VARS+$5A   ; 2 bytes: hardware frames the game never saw
h_hdmaon        = HAL_VARS+$5C   ; nonzero if HDMA drove BG1HOFS this frame
h_scrollline    = HAL_VARS+$5D   ; scanline at which BG1HOFS was actually written
h_late          = HAL_VARS+$44
h_over          = HAL_VARS+$46


; DMA channel 1, used for the raster-split HDMA
DMAP1           = $4310
BBAD1           = $4311
A1T1L           = $4312
A1B1            = $4314

; DMA channel 4, used for the altar beam's window edges
DMAP4           = $4340
BBAD4           = $4341
A1T4L           = $4342
A1B4            = $4344

SLHV            = $2137         ; reading it latches the H/V counters
OPVCT           = $213D         ; vertical counter
STAT78          = $213F         ; reading it resets the counter read toggle

;  The last scanline at which hal_waitvbl will still serve a vblank it arrived
;  inside of, rather than waiting for the next one.  Vblank runs to line 261,
;  so this leaves 17 lines; a walking frame's flush measures about 15, and the
;  arrivals this is meant to catch land around 237.  Raising it risks a flush
;  running past the end of vblank and writing VRAM into the live picture, so
;  the flush's finishing line is worth re-measuring after any change to it.
LATE_FLUSH_LAST = 244

h_rastercount   = HAL_VARS+$3D  ; mid-frame $2001 writes recorded this frame
h_tmcur         = HAL_VARS+$3E  ; TM as of the most recent $2001 write
RASTERLINE      = $0980         ; 16 entries: scanline of each split
RASTERTM        = $0990         ; 16 entries: TM value from that split
HDMATAB         = $09A0         ; the HDMA table we build from them
                                ; channel so the two can be live together.
                                ; $0C20 is past OAMSHADOW's 544 bytes at $0A00
                                ; and short of NTSHADOW at $1000.
h_prevmask      = HAL_VARS+$3F  ; $2001 as it was before the current write
h_tmframestart  = HAL_VARS+$40  ; TM in force at the top of the frame

; The game's zero-page scratch (variables.inc calls it tmp, 16 bytes).  The
; screen-wipe band is described by tmp+4 and tmp+5, which hal_wipewindow reads.
NES_mapflags    = $002D         ; bit 1 set means a column is being drawn

; The game's attribute draw buffers (variables.inc puts draw_buf at $0780).
; DrawMapAttributes walks these, and hal_drawattr walks them in its place.
DRAW_ATTR       = $07C0         ; the attribute bits wanted
DRAW_AT_HI      = $07D0         ; destination address, high byte...
DRAW_AT_LO      = $07E0         ; ...and low
DRAW_AT_MSK     = $07F0         ; which bits of the byte to replace

NES_tmp         = $0010

; How far below tmp+4 the wipe band's first visible line sits.  The game counts
; tmp+4 from roughly eleven scanlines before its picture begins -- that is what
; the "122+11" in ScreenWipe_Open is for -- and this port crops the NES's top
; eight lines, so the band starts WIPE_LEAD lines further down in SNES terms.
WIPE_LEAD       = 11 + NES_TOP_CROP

; The game's own soft copy of $2000, at zero page $FF (variables.inc calls it
; soft2000).  The NES build's NMI handler pushed this to the PPU every frame.
NES_soft2000    = $00FF

; Raster splits: record mid-frame $2001 writes, replay them as an HDMA table.
;
; This does NOT reproduce the map-transition wipe, whatever an earlier version of
; this comment claimed.  It never did: when it was last on, the effect was
; flickery and opened from the wrong place on the screen, and measurement since
; says why.  The game brackets its visible window with three $2001 writes a
; frame -- off, on, off -- and only one of them lands during active display, at
; scanline 7, reading "background on".  The other two fall in vblank and are
; skipped, correctly.  A table built from that can never turn the background off,
; so the screen stays lit; and the one split it does catch is nowhere near where
; the game means it to be.
;
; The cause is geometry, not a coding slip.  The game counts its waits from where
; its own WaitForVBlank returned, on a 240-line picture, after a prep step
; calibrated to about eleven scanlines -- which is what the "122+11" in
; ScreenWipe_Open is for.  Here the wait returns at a different raster position,
; the flush has eaten a variable slice of vblank first, and the picture is
; cropped to 224 lines.  The counts cannot land where the game intends.
;
; So the split positions are not recoverable from the game's cycle-counted
; waits, and no amount of fixing would change that.  The wipe is drawn instead
; from the two variables the game already keeps -- see hal_wipewindow.

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

h_apuseq        = HAL_VARS+$6E  ; audio packet sequence number
h_apuok         = HAL_VARS+$6F  ; nonzero once the SPC700 program answered
h_apuon         = HAL_VARS+$71  ; bit per voice: was it sounding last frame?
h_apumask       = HAL_VARS+$72  ; 1<<voice for the channel being translated
h_apuvoice      = HAL_VARS+$73  ; voice<<4, ready for the packet's cmd byte
h_apuvol        = HAL_VARS+$74  ; its NES volume nibble
h_apupitch      = HAL_VARS+$75  ; 2 bytes: its S-DSP pitch
h_apuwait       = HAL_VARS+$77  ; apu_send's bounded-wait counter
h_apuwave       = HAL_VARS+$78  ; waveform index, pre-shifted into the sequence
                                ;   byte's bits 7-3: duty and cycle length
;  Sweep unit state, two bytes per pulse channel so one index serves both:
;  X = 0 for pulse 1, 2 for pulse 2.
h_swper         = HAL_VARS+$7A  ; the period the sweep now owns
h_swseen        = HAL_VARS+$7E  ; the period the CPU last wrote, to spot writes
h_swdiv         = HAL_VARS+$82  ; half-frames left before the next update
h_swmute        = HAL_VARS+$86  ; nonzero while the sweep is silencing it
h_swreg         = HAL_VARS+$8A  ; scratch: the sweep register, EPPP NSSS
h_swtmp         = HAL_VARS+$8C  ; scratch: period >> shift
h_swticks       = HAL_VARS+$8E  ; scratch: half-frames left this video frame
h_swtgt         = HAL_VARS+$90  ; scratch: the period the sweep is heading to
h_sfxlast       = HAL_VARS+$92  ; last frame's sq2_sfx, to spot an effect
                                ;   starting again with identical register bytes
NESZP_SQ2SFX    = $007E         ; the game's own "pulse 2 is busy with a sound
                                ;   effect for N more frames" countdown
h_swacc         = HAL_VARS+$96  ; fractional half-frame accumulator
h_swtickn       = HAL_VARS+$98  ; half-frames falling in this video frame
h_apufull       = HAL_VARS+$9A  ; set by hal_waitvbl: this call is the frame's
                                ;   own, so it may advance the sweep clock
;  The noise channel's NES envelope and length counter.  It is the only
;  channel this game drives with them: its $400C writes clear the
;  constant-volume bit, so the low nibble is a decay rate and the level comes
;  from the envelope.
h_nzdecay       = HAL_VARS+$9C  ; envelope level, 15 down to 0
h_nzdiv         = HAL_VARS+$9D  ; quarter-frames until the level steps
h_nzstart       = HAL_VARS+$9E  ; a $400F write restarts the envelope
h_nzlen         = HAL_VARS+$9F  ; length counter; at zero the channel is silent
h_nztick        = HAL_VARS+$A0  ; half-frames left to clock this video frame

;  The triangle's linear counter.  The channel has no volume register, so the
;  driver silences it by writing $4008 with the control bit clear and a reload
;  value in the low seven bits -- $30 when a new song starts, $70 when one
;  ends -- and letting the counter run down to zero at the quarter-frame rate.
;  The disassembly says so in as many words at each of those writes ("this
;  will silence the tri on the next linear counter clock").  Treating a
;  nonzero reload value as "sounding", which is what this did before, means
;  that countdown never happens and the voice drones on for ever: audible at
;  the end of the epilogue, where the music stops and no later note re-keys it.
h_trilin        = HAL_VARS+$A8  ; the counter itself; at zero the channel is mute
h_trirel        = HAL_VARS+$A9  ; reload flag, set by a write to $400B
h_trtick        = HAL_VARS+$AA  ; half-frames left to clock this video frame
;  The tilemap word ClearNT leaves everywhere: tile 0, and the palette number
;  from an attribute byte of $FF, which is 3 in each quadrant.  nt_attr stores
;  a palette as (bits & 3) << 2 in the high byte, so that is $0C.
h_fillcnt       = HAL_VARS+$A4  ; hal_ntfill: bytes left to write
h_fillcol       = HAL_VARS+$A6  ; ...and the column the run started at

NT_CLEARWORD    = $0C00

h_tintbase      = HAL_VARS+$A2  ; 2 bytes: emphasis<<7, the offset of this
                                ;   emphasis mode's block in nespal_snes
h_dacount       = HAL_VARS+$6C  ; hal_drawattr: attribute bytes to update
h_clcnt         = HAL_VARS+$66  ; hal_chrload: bytes still to move...
h_clidx         = HAL_VARS+$68  ; ...where it is reading from...
h_clrows        = HAL_VARS+$6A  ; ...and how far to advance the caller's pointer.
                                ; Kept apart from h_t0..h_t8 because the slow
                                ; path calls w2007_core, which uses those freely.
h_wipetop       = HAL_VARS+$63  ; first lit line of the transition band...
h_wipebot       = HAL_VARS+$64  ; ...and the first dark line below it
h_wipeon        = HAL_VARS+$65  ; nonzero while a transition wipe is running
h_hdmaen        = HAL_VARS+$62  ; which HDMA channels this frame wants.  Two
                                ; separate flushes drive HDMA -- flush_raster on
                                ; TM, flush_ntsplit on BG1HOFS -- and each used
                                ; to store HDMAEN outright, so whichever ran last
                                ; switched the other one off.
h_t8            = HAL_VARS+$60  ; 2 bytes: nt_attr's per-row "quadrant changed"
                                ; flags, one byte each, indexed left/right
