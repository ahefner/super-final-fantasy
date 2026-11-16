; ---------------------------------------------------------------------------
;  altmaps.inc -- the game played on the map Map Select chose (RANDO_MAP),
;  included by world.asm
;
;  Map 0 is the game's map, and every routine here leaves the game to it:
;  bank $01's rows, the game's tables.  Any other is genmaps.py's, from
;  maps/custom-maps.txt: its rows and its record (gen/mapdata.inc, MI_*) in
;  chunks' low halves, reached long.  What the record sets, and where:
;
;    the rows        ow_altrow, the window LoadOWMapRow fills as the party
;                    walks; mm_altrows, the minimap's two at a time
;    the start, the ship Bikke gives, the airship, the bridge, the canal
;                    map_newgame, into the first page as New Game's build
;                    fills it (rando_build)
;    a Free SHIP's berth, a Free AIRSHIP at the start
;                    map_freeship, map_freeairship (opt_freestuff)
;    a found ship's mooring, by the map it is found on
;                    map_shipdock (rando.asm's give_vehicle)
;    the exits' landings
;                    map_exits, into the cache (es_tables)
;    the zones' formations
;                    map_domains, into the cache (build_forms)
;    the bridge across a horizontal strait
;                    map_flags, for fun_chrload's overlay
;    Mirror World's lines that say east or west
;                    dlg_lines, with the hint lines, for rando_dlgtext
;
;  Map shuffle and the key items' placement are the game's map's still:
;  their logic is its (options-design.md, "Map Select").
; ---------------------------------------------------------------------------

.include "mapdata.inc"
.include "mapdlg.inc"

ALTWIN    = (CHUNK0 * $10000) + mapdata       ; the window's sixteen rows, SRAM
ALTMM     = (CHUNK0 * $10000) + mm_mapbuf     ; the minimap's two, low WRAM
ALTSAVE   = (CHUNK0 * $10000)                 ; + a first page address
ALTDOMAINS = BANK0BFAR + lut_Domains
.assert mm_mapbuf2 = mm_mapbuf + $100, error, "mm_altrows decodes the minimap's two rows end to end"
.assert <mapdata = 0, error, "a window row is a page"

;;  RANDO_MAP, or 0 for a map past the list -- a save from a build whose list
;;  was longer.  A8 in and out, Z set for the game's map; X and Y kept.
    .a8
map_id:
    LDA f:RANDO_SAVEFAR + (RANDO_MAP - RANDO_SAVE)
    CMP #MAPINFO_N
    BCC :+
    LDA #0
:   CMP #0
    RTS

;;  The record of map A (nonzero) into X, in native mode, A8 I16; from
;;  emulation mode, the caller having pushed P.  Its return is the caller's:
;;  alt_out puts emulation mode back.
    .a8
alt_in:
    CLC
    XCE
    REP #$10
    .i16
    XBA
    LDA #0
    XBA
    REP #$20
    .a16
    XBA
    TAX                         ; map * MI_SIZE
    SEP #$20
    .a8
    RTS
.assert MI_SIZE = $100, error, "alt_in's record is a page"

;;  The decoder: the row at [tmp] into f:BASE + X on.  The game's format
;;  (DecompressMap): a tile below $80, $80 + a tile then its count (0 for
;;  256), $FF the end.  A8 I16; Y the row's first byte.  Out: X past it.
.macro ALTDECODE base
    .local tile, run, one, done
  tile:
    LDA [tmp], Y
    INY
    CMP #$80
    BCC one
    CMP #$FF
    BEQ done
    AND #$7F
    STA z:tmp+4
    LDA [tmp], Y                ; the count
    INY
    STA z:tmp+5
    LDA z:tmp+4
  run:
    STA f:base, X
    INX
    DEC z:tmp+5
    BNE run
    BRA tile
  one:
    STA f:base, X
    INX
    BRA tile
  done:
.endmacro

;;  [tmp] the map's row A16 (0-255).  A16 I16, X the map's record.  Y, A
;;  clobbered; X kept.
    .a16
    .i16
alt_rowptr:
    ASL A
    TAY
    LDA f:MAPINFOFAR + MI_ROWLO, X
    STA z:tmp
    SEP #$20
    .a8
    LDA f:MAPINFOFAR + MI_ROWBANK, X
    STA z:tmp+2
    REP #$20
    .a16
    LDA [tmp], Y
    STA z:tmp
    RTS
    .a8


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ow_altrow -- another map's row mapdraw_y, into its slot of the window,
;;  from LoadOWMapRow (owedits_row.patch) in place of bank $01's, by JSL,
;;  emulation mode.  Out: C set, done; C clear for the game's map, whose
;;  row LoadOWMapRow unpacks as ever.  A, X, Y and tmp..tmp+5 clobbered, as
;;  DecompressMap clobbers them.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i8
ow_altrow:
    JSR map_id
    BNE :+
    CLC
    RTL
:   PHP
    JSR alt_in
    .i16
    REP #$20
    .a16
    LDA z:mapdraw_y
    AND #$00FF
    JSR alt_rowptr
    LDA z:mapdraw_y
    AND #$000F
    XBA
    TAX                         ; its slot: a page each
    SEP #$20
    .a8
    LDY #$0000
    ALTDECODE ALTWIN
    JMP alt_done

;;  The minimap's rows mm_maprow and the next, into mm_mapbuf and mm_mapbuf2,
;;  from CallMinimapDecompress (owedits_minimap.patch) in place of bank
;;  $01's: as ow_altrow, but tmp+3 to tmp+5 kept, as MinimapDecompress keeps
;;  them (the HAL's screen wipe reads tmp+4 and tmp+5).
    .a8
    .i8
mm_altrows:
    JSR map_id
    BNE :+
    CLC
    RTL
:   LDA z:tmp+3
    PHA
    LDA z:tmp+4
    PHA
    LDA z:tmp+5
    PHA
    PHP
    JSR map_id                  ; (A again: the saving took it)
    JSR alt_in
    .i16
    PHX
    REP #$20
    .a16
    LDA z:mm_maprow
    AND #$00FF
    JSR alt_rowptr
    SEP #$20
    .a8
    LDX #$0000
    LDY #$0000
    ALTDECODE ALTMM             ; leaves X at mm_mapbuf2's
    REP #$20
    .a16
    PLY                         ; the record...
    PHX
    TYX
    LDA z:mm_maprow
    INC A
    AND #$00FF
    JSR alt_rowptr
    PLX
    SEP #$20
    .a8
    LDY #$0000
    ALTDECODE ALTMM
    SEP #$30
    .i8
    SEC
    XCE
    PLP
    PLA
    STA z:tmp+5
    PLA
    STA z:tmp+4
    PLA
    STA z:tmp+3
    SEC
    RTL
alt_done:
    SEP #$30
    .i8
    SEC
    XCE
    PLP
    SEC
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The minimap's layout, every map's its record's (MI_MM; genmaps.py): the
;;  nametable, and the tiles the logo and the crests are drawn into -- tiles
;;  of blocks that are open sea on that map, so the drawing leaves them
;;  blank, and each block of land shown with its tile (user, 2026-11-15:
;;  the game's layout on another map put land in the logo's tiles and hid
;;  land).  The game's map's is tools/genowedits.py's, with the map edits.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  [tmp] the map's layout.  Emulation mode; A clobbered, X and Y kept.
    .a8
    .i8
mm_layout:
    PHX
    PHY
    PHP
    JSR map_id
    JSR alt_in
    .i16
    LDA f:MAPINFOFAR + MI_MM, X
    STA z:tmp
    LDA f:MAPINFOFAR + MI_MM + 1, X
    STA z:tmp+1
    LDA f:MAPINFOFAR + MI_MM + 2, X
    STA z:tmp+2
    SEP #$30
    .i8
    SEC
    XCE
    PLP
    PLY
    PLX
    RTS

;;  The nametable, $400 bytes to the PPU from where Minimap_FillNTPal has
;;  set its address (minimap_fillnt.patch), as its loop wrote lut_MinimapNT.
;;  By JSL, emulation mode; A, X, Y and tmp..tmp+2 clobbered, as the loop
;;  clobbered them.
    .a8
    .i8
mm_fillnt:
    JSR mm_layout
    LDX #$04
    LDY #$00
  @nt:
    LDA [tmp], Y
    JSR nesio_w2007             ; wPPUDATA
    INY
    BNE @nt
    INC z:tmp+1
    DEX
    BNE @nt
    RTL

;;  The logo's (mm_titledest) or the crests' (mm_decordest) destinations:
;;  [tmp+8] their tiles' addresses' high bytes and [tmp+11] their low, for
;;  Minimap_DrawTitleCHR's and _DrawDecorCHR's loops (minimap_titleread.patch,
;;  _decorread.patch), set each frame after its wait.  By JSL, emulation
;;  mode; A and tmp..tmp+2 clobbered, X and Y kept.
    .a8
    .i8
mm_titledest:
    PHX
    LDX #0
    BRA mm_dest
mm_decordest:
    PHX
    LDX #2
mm_dest:
    JSR mm_layout
    LDA z:tmp+2
    STA z:tmp+10
    STA z:tmp+13
    LDA z:tmp
    CLC
    ADC f:WORLDFAR + lut_MmDest, X
    STA z:tmp+8
    LDA z:tmp+1
    ADC f:WORLDFAR + lut_MmDest + 1, X
    STA z:tmp+9
    LDA z:tmp
    CLC
    ADC f:WORLDFAR + lut_MmDest + 4, X
    STA z:tmp+11
    LDA z:tmp+1
    ADC f:WORLDFAR + lut_MmDest + 5, X
    STA z:tmp+12
    PLX
    RTL
lut_MmDest:
  .WORD MM_TITLEHI, MM_DECORHI, MM_TITLELO, MM_DECORLO


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  map_newgame -- New Game's map: NGF_MAP into the save (RANDO_MAP), and for
;;  another than the game's, its start, Bikke's ship, the airship, the bridge
;;  and the canal over lut_InitUnsramFirstPage's.  From rando_build, the
;;  page just filled, by JSL, emulation mode.  A, X clobbered; Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    .a8
    .i8
map_newgame:
    LDA f:NGF_MAP
    STA f:RANDO_SAVEFAR + (RANDO_MAP - RANDO_SAVE)
    JSR map_id
    STA f:RANDO_SAVEFAR + (RANDO_MAP - RANDO_SAVE)  ; (one past the list: the game's)
    BNE :+
    RTL
:   PHP
    JSR alt_in
    .i16
    LDA f:MAPINFOFAR + MI_START, X
    SEC
    SBC #7                      ; the scroll: the party's tile, less 7
    STA f:ALTSAVE + unsram_ow_scroll_x
    LDA f:MAPINFOFAR + MI_START + 1, X
    SEC
    SBC #7
    STA f:ALTSAVE + unsram_ow_scroll_y
    LDA f:MAPINFOFAR + MI_SHIP, X
    STA f:ALTSAVE + ship_x
    LDA f:MAPINFOFAR + MI_SHIP + 1, X
    STA f:ALTSAVE + ship_y
    LDA f:MAPINFOFAR + MI_AIRSHIP, X
    STA f:ALTSAVE + airship_x
    LDA f:MAPINFOFAR + MI_AIRSHIP + 1, X
    STA f:ALTSAVE + airship_y
    LDA f:MAPINFOFAR + MI_BRIDGE, X
    STA f:ALTSAVE + bridge_x
    LDA f:MAPINFOFAR + MI_BRIDGE + 1, X
    STA f:ALTSAVE + bridge_y
    LDA f:MAPINFOFAR + MI_CANAL, X
    STA f:ALTSAVE + canal_x
    LDA f:MAPINFOFAR + MI_CANAL + 1, X
    STA f:ALTSAVE + canal_y
alt_out:
    SEP #$30
    .i8
    SEC
    XCE
    PLP
    RTL

;;  A Free SHIP at the map's berth, and a Free AIRSHIP where the party
;;  starts, after opt_freestuff has put them at the game's.  By JSL,
;;  emulation mode; A, X clobbered.
    .a8
    .i8
map_freeship:
    JSR map_id
    BNE :+
    RTL
:   PHP
    JSR alt_in
    .i16
    LDA f:MAPINFOFAR + MI_FREESHIP, X
    STA f:ALTSAVE + ship_x
    LDA f:MAPINFOFAR + MI_FREESHIP + 1, X
    STA f:ALTSAVE + ship_y
    BRA alt_out
map_freeairship:
    JSR map_id
    BNE :+
    RTL
:   PHP
    JSR alt_in
    .i16
    LDA f:MAPINFOFAR + MI_START, X
    STA f:ALTSAVE + airship_x
    LDA f:MAPINFOFAR + MI_START + 1, X
    STA f:ALTSAVE + airship_y
    BRA alt_out

;;  A found ship's mooring on another map: the dock FFR gives the entrance
;;  the map it is found on is behind (MI_DOCKX, by cur_map), into ship_x
;;  and ship_y.  From give_vehicle, by JSL, emulation mode.  Out: C set,
;;  moored; C clear for the game's map, whose docks give_vehicle has.  A,
;;  X clobbered.
    .a8
    .i8
map_shipdock:
    JSR map_id
    BNE :+
    CLC
    RTL
:   PHP
    JSR alt_in
    .i16
    REP #$20
    .a16
    LDA z:cur_map
    AND #$00FF
    PHA                         ; (not tmp: rando_talk's data is there)
    TXA
    CLC
    ADC 1,S
    TAX                         ; the record, at cur_map
    PLA
    SEP #$20
    .a8
    LDA f:MAPINFOFAR + MI_DOCKX, X
    STA f:ALTSAVE + ship_x
    LDA f:MAPINFOFAR + MI_DOCKY, X
    STA f:ALTSAVE + ship_y
    SEP #$30
    .i8
    SEC
    XCE
    PLP
    SEC
    RTL
.assert MI_DOCKY - MI_DOCKX >= 64, error, "a map past the dock table"

;;  The map's MIF_* flags into A, 0 for the game's.  By JSL, emulation
;;  mode; X and Y kept.
    .a8
    .i8
map_flags:
    JSR map_id
    BNE :+
    RTL
:   PHX
    PHY
    PHP
    JSR alt_in
    .i16
    LDA f:MAPINFOFAR + MI_FLAGS, X
    SEP #$30
    .i8
    SEC
    XCE
    PLP
    PLY
    PLX
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The cache's: the zones' formations (map_domains, build_forms' first
;;  step, replacing its copy_domains) and the exits' landings (map_exits,
;;  es_tables' last).  Native, DBR = $7F; A8 I16 in and out.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;  lut_Domains into the cache, as the cartridge has it; then for another
;;  map each overworld zone's eight from the zone its record names (FFR's
;;  DomainUpdates: a zone's fights where its land now is).  By JSL.
    .a8
    .i16
map_domains:
    REP #$20
    .a16
    LDX #$0000
  @copy:
    LDA f:ALTDOMAINS, X
    STA f:RW_DOMAINS, X
    INX
    INX
    CPX #128 * 8
    BCC @copy
    SEP #$20
    .a8
    JSR map_id
    BEQ @out
    REP #$20
    .a16
    AND #$00FF
    XBA
    PHA                         ; 1,S: its record
    LDY #$0000                  ; the zone, times 8
  @zone:
    TYA
    LSR A
    LSR A
    LSR A
    CLC
    ADC 1,S
    TAX
    LDA f:MAPINFOFAR + MI_DOMAIN, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    TAX                         ; the zone it takes from, times 8
    LDA f:ALTDOMAINS, X
    STA a:.LOWORD(RW_DOMAINS), Y
    LDA f:ALTDOMAINS + 2, X
    STA a:.LOWORD(RW_DOMAINS) + 2, Y
    LDA f:ALTDOMAINS + 4, X
    STA a:.LOWORD(RW_DOMAINS) + 4, Y
    LDA f:ALTDOMAINS + 6, X
    STA a:.LOWORD(RW_DOMAINS) + 6, Y
    TYA
    CLC
    ADC #8
    TAY
    CPY #64 * 8
    BCC @zone
    PLA
    SEP #$20
    .a8
  @out:
    RTL
.assert ^RW_DOMAINS = ^RANDOWRAM, error, "map_domains writes the zones with DBR the cache's"

;;  Another map's sixteen exits' landings over the wiring's.  By JSR, from
;;  es_tables.
    .a8
    .i16
map_exits:
    JSR map_id
    BEQ @out
    REP #$20
    .a16
    AND #$00FF
    XBA
    TAX
    SEP #$20
    .a8
    LDY #$0000
  @exit:
    LDA f:MAPINFOFAR + MI_EXITX, X
    STA a:.LOWORD(RW_EXITX), Y
    LDA f:MAPINFOFAR + MI_EXITY, X
    STA a:.LOWORD(RW_EXITY), Y
    INX
    INY
    CPY #16
    BCC @exit
  @out:
    RTS
.assert ^RW_EXITX = ^RANDOWRAM && ^RW_EXITY = ^RANDOWRAM, error, "map_exits writes with DBR the cache's"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  dlg_lines -- a line of the game's that gives way, by its pointer
;;  (text_ptr): with the key items shuffled, one that says where a key item
;;  or -- Map shuffle on -- a dungeon is, or the way through one, for one
;;  that doesn't (dlghint.inc); else on Mirror World, one that says east or
;;  west for the other (mapdata.inc).  From rando_dlgtext with nothing
;;  armed, by JSL, emulation mode.  Out: C set, text_ptr's low byte this
;;  chunk's line and A its high byte; else C clear.  A, X clobbered; Y kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

DLGPTRS = (CHUNK0 + BANK_DIALOGUE) * $10000 + lut_DialoguePtrTbl

    .a8
    .i8
dlg_lines:
    LDA f:RANDO_SAVEFAR + (RANDO_KEYITEMS - RANDO_SAVE)
    CMP #KEYITEMS_STANDARD
    BEQ :+
    CMP #KEYITEMS_WIDE
    BNE @mirror
:   LDX #DLG_NHINT - 1
  @look:
    LDA f:WORLDFAR + lut_DlgHintId, X
    JSR dlg_is
    BEQ @hit
    DEX
    BPL @look
    BRA @mirror
  @hit:
    LDA f:RANDO_SAVEFAR + (RANDO_ENTRANCES - RANDO_SAVE)
    CMP f:WORLDFAR + lut_DlgHintMap, X
    BCC @mirror                 ; its Map shuffle isn't on: the game's line
    JSL map_flags + WORLDFAR
    AND #MIF_MIRROR
    BEQ @hint
    LDA f:WORLDFAR + lut_DlgHintId, X
    CMP #DLG_HINTMIRROR
    BNE @hint
    LDA #<lut_DlgHintMirror     ; the hint turned round
    STA text_ptr
    LDA #>lut_DlgHintMirror
    SEC
    RTL
  @hint:
    LDA f:WORLDFAR + lut_DlgHintLo, X
    STA text_ptr
    LDA f:WORLDFAR + lut_DlgHintHi, X
    SEC
    RTL
  @mirror:
    JSL map_flags + WORLDFAR
    AND #MIF_MIRROR
    BEQ @none
    LDX #DLG_NMIRROR - 1
  @mlook:
    LDA f:WORLDFAR + lut_DlgMirrorId, X
    JSR dlg_is
    BEQ @mhit
    DEX
    BPL @mlook
  @none:
    CLC
    RTL
  @mhit:
    LDA f:WORLDFAR + lut_DlgMirrorLo, X
    STA text_ptr
    LDA f:WORLDFAR + lut_DlgMirrorHi, X
    SEC
    RTL

;;  Z set if text_ptr is dialogue A's string, by the game's table: the
;;  number being gone by DrawDialogueString_PtrLoaded.  X kept.
    .a8
    .i8
dlg_is:
    PHX
    ASL A
    TAX
    BCS @high                   ; $80 on: the table's second page
    LDA f:DLGPTRS, X
    CMP text_ptr
    BNE @no
    LDA f:DLGPTRS + 1, X
    BRA @page
  @high:
    LDA f:DLGPTRS + $100, X
    CMP text_ptr
    BNE @no
    LDA f:DLGPTRS + $101, X
  @page:
    CMP text_ptr+1
    BNE @no
    PLX                         ; (PLX sets Z by X: the answer after it)
    LDA #0
    RTS
  @no:
    PLX
    LDA #1
    RTS
