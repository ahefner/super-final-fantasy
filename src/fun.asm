; ---------------------------------------------------------------------------
;  fun.asm -- the FUN% section's code (user, 2026-11-03, fun-percent.txt:
;  "goofy flags that don't change anything about gameplay").  In Taverns'
;  chunk (CHUNK_TAVERN), which has the room.  Stereo Sound is the HAL's and
;  the SPC700's (apu_pan); this is Palette swap and the Exploding Dwarf.
;
;  Palette swap (user: one On/Off, "Fixed per seed", the overworld too;
;  "enemy colors are fine too", and "some artistic license to tint the
;  background grass color toward blue or brown"):
;
;    deal_palswap  the seed's tables, into the cache with the rest of it:
;                  the 64 battle palettes shuffled, as FFR's PaletteSwap
;                  (Fun.cs) shuffles them, and a tint for every map, the
;                  overworld and each battle backdrop (randoref.build_palswap)
;    fun_smpal     a standard map's palettes tinted as they load -- its
;                  three background palettes and its three in rooms, the
;                  fourth of each the dialogue box's -- then Short ToFR's
;    fun_owpal     the overworld's four, likewise
;    fun_bdpal     a battle backdrop's three colours
;    fun_btlpal     an enemy palette's number, through the shuffle
;
;  A tint moves a colour's hue a few steps round the NES's twelve, the
;  same for every colour of the map, and keeps its brightness: greens go
;  toward teal and blue one way, olive and brown the other, and black,
;  white and the greys stay.  Each is a no-op with the row Off.  From the
;  fixed bank, by JSL, emulation mode, A8 X8, the caller's DBR (which
;  decodes low WRAM); deal_palswap from the build, native.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"

.import rando_warmfar, rando_belowfar, rando_fyfar, rando_smpal
.import hal_chrdirty, lut_DwarfLine
.export deal_palswap, fun_smpal, fun_owpal, fun_bdpal, fun_btlpal
.export fun_dwarfline, fun_spared, fun_exit, fun_smframe, fun_frame, fun_init
.export fun_cover
.export lut_DwarfGibs, lut_DwarfPals     ; for tools/test_options.py

.segment "BANK_TAVERN"

STREAM_PALSWAP  = $50414C53     ; "PALS": Palette swap's tables (deal_palswap)
PALSWAP_PALS    = 64            ; lut_BattlePalettes' four-colour palettes
TINT_STEPS      = 7             ; -3..+3
SRAMFAR_FUN     = CHUNK0 * $10000 + OPT_FUN

;;  deal_palswap -- Palette swap's tables for the seed: RW_PALPERM a
;;  Fisher-Yates of 0..63, then RW_TINT a draw below TINT_STEPS each, all on
;;  STREAM_PALSWAP.  From build (rando.asm): native, DBR = $7F, A8 I16.
;;  Out: the same.
deal_palswap:
    REP #$30
    .a16
    .i16
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE)
    EOR #.LOWORD(STREAM_PALSWAP)
    STA a:.LOWORD(RW_RNG)
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE) + 2
    EOR #.HIWORD(STREAM_PALSWAP)
    STA a:.LOWORD(RW_RNG) + 2
    JSL rando_warmfar + RANDOFAR
    LDA #.LOWORD(RW_PALPERM)
    STA a:.LOWORD(RW_FK)
    SEP #$20
    .a8
    LDX #$0000
  @fill:
    TXA
    STA a:.LOWORD(RW_PALPERM), X
    INX
    CPX #PALSWAP_PALS
    BCC @fill
    LDA #PALSWAP_PALS
    JSL rando_fyfar + RANDOFAR
    LDX #$0000
  @tint:
    PHX
    LDA #TINT_STEPS
    JSL rando_belowfar + RANDOFAR
    PLX
    STA a:.LOWORD(RW_TINT), X
    INX
    CPX #PALSWAP_TINTS
    BCC @tint
    RTL

.a8
.i8                             ; the rest: from the fixed bank, emulation mode

;;  Z clear when Palette swap is on.  A clobbered.
palswap_on:
    LDA f:SRAMFAR_FUN
    AND #FUN_PALSWAP
    RTS

;;  The colour in A tinted by FUN_CODE: a hue of 1-12 moved by FUN_CODE - 3
;;  round the twelve, the brightness bits kept; hues 0 and 13-15, the greys
;;  and black, as they are.  X and Y kept.
tint_one:
    PHA
    AND #$0F
    BEQ @keep
    CMP #$0D
    BCS @keep
    CLC
    ADC f:FUN_CODE              ; hue + code, 1..18
    SEC
    SBC #3                      ; hue + the shift, -2..15
    BEQ @under
    BMI @under
    CMP #13
    BCC @have
    SBC #12                     ; (C set)
    BRA @have
  @under:
    CLC
    ADC #12
  @have:
    STA f:FUN_HUE
    PLA
    AND #$F0
    ORA f:FUN_HUE
    RTS
  @keep:
    PLA
    RTS

;;  load_map_pal from Y up to FUN_END, each colour tinted.  Y moved.
tint_lmp:
    LDA load_map_pal, Y
    JSR tint_one
    STA load_map_pal, Y
    INY
    TYA
    CMP f:FUN_END
    BCC tint_lmp
    RTS

;;  The end of LoadSMTilesetData (optopenchests.patch): this map's tint over
;;  its three background palettes and its three in rooms -- each set's fourth
;;  is the dialogue box's, $0F $00 $01 $30 on every map -- then Short ToFR's
;;  colour, as before.
fun_smpal:
    JSR palswap_on
    BEQ @out
    LDX cur_map
    LDA f:RW_TINT, X
    STA f:FUN_CODE
    LDA #$0C
    STA f:FUN_END
    LDY #$00
    JSR tint_lmp
    LDA #$2C
    STA f:FUN_END
    LDY #$20
    JSR tint_lmp
  @out:
    JML rando_smpal + RANDOFAR

;;  The end of LoadOWTilesetData (palswap.patch): the overworld's tint over
;;  its four background palettes, all of them land, and sprite palette 3,
;;  which the land over the canal, the bridge and the airship's shadow are
;;  drawn in to sit on the grass (user, 2026-11-04: the land bridge before
;;  the canal "needs to match"): its green moves with the map's, its black
;;  and white stay.
fun_owpal:
    JSR palswap_on
    BEQ @out
    LDA f:RW_TINT + TINT_OW
    STA f:FUN_CODE
    LDA #$10
    STA f:FUN_END
    LDY #$00
    JSR tint_lmp
    LDA #$20
    STA f:FUN_END
    LDY #$1C
    JSR tint_lmp
  @out:
    RTL

;;  After LoadBattleBackdropPalette's copy (palswap.patch): X = the backdrop
;;  times four, cur_pal 0-3 its colours; colours 1-3 tinted, 0 the black
;;  behind.  X not kept.
fun_bdpal:
    JSR palswap_on
    BEQ @out
    TXA
    LSR A
    LSR A
    TAX
    LDA f:RW_TINT + TINT_BACKDROP, X
    STA f:FUN_CODE
    LDX #1
  @colour:
    LDA cur_pal, X
    JSR tint_one
    STA cur_pal, X
    INX
    CPX #4
    BCC @colour
  @out:
    RTL

;;  The top of LoadBattlePalette (palswap.patch): A = a formation's palette
;;  number, through the shuffle.  Y kept, X not.
fun_btlpal:
    PHA
    JSR palswap_on
    BEQ @off
    PLA
    AND #PALSWAP_PALS - 1
    TAX
    LDA f:RW_PALPERM, X
    RTL
  @off:
    PLA
    RTL


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The Exploding Dwarf (user, 2026-11-03: "Hurray dwarf only"; "Keep the
;;  Hurray text" then "he should exclaim 'Oh shit!'"; "let him respawn"):
;;  talk to the Hurray dwarf in the Dwarf Cave and he says so, and when the
;;  box closes he bursts -- tenes's 2021 hack (commit 72995c0) for the SNES,
;;  as sprites: DWARF_PARTICLES gibs in OAM entries 64 up, which the NES
;;  never uses, their tiles object slot 14's row (empty on that map), their
;;  colours OBJ palettes 4 and 5 (the HAL's h_xpal).  tools/dwarfref.py is
;;  the model, and dwarfgibs.inc its tables: the cartridge is it frame for
;;  frame (test_dwarf).
;;
;;    fun_dwarfline  his line, from rando_dlgtext, and the burst armed
;;    fun_spared     NPC Guillotine leaves him be (rando_talk), so he is
;;                   back on the next visit
;;    fun_smframe    each frame of the standard map loop, the sprites drawn:
;;                   the burst, then the gibs flying, falling and lying
;;    fun_cover      each frame of a dialogue box, as the game's own sprites
;;                   are covered: the gibs behind the box hidden, the rest
;;                   held where they were
;;    fun_frame      each frame wait, before it: with the sprites off -- a
;;                   menu, a shop or a battle on the way -- they are hidden
;;                   until the map is back
;;    fun_exit       leaving the map, at the screen wipe every way off it
;;                   starts with (the user's, 2026-11-03): they are gone
;;    fun_init       and every boot, a soft reset's too
;;
;;  He is taken out of the map's objects for the visit, his game flag left
;;  as it is, so the next load of the map brings him back to burst again.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.include "dwarfgibs.inc"
.assert DWARF_PARTICLES = GIB_N, error, "dwarfref.py's particles are not snesmap.inc's"
DLGPTRFAR_HURRAY = (CHUNK0 + BANK_DIALOGUE) * $10000 + lut_DialoguePtrTbl + DLG_HURRAY * 2
GIB_SHADOW = (256 + DWARF_GIB_FIRST) * 32   ; the gibs' tiles in CHRSHADOW: NES $1F00
GIB_OAM    = OAMSHADOW + 64 * 4             ; the first gib's sprite
GIB_HIDDEN = $F0                            ; a sprite's Y off the screen, as the HAL parks them
.assert GIB_OAM + GIB_N * 4 <= OAMSHADOW + 512, error, "the gibs run past OAM"

.a8
.i8

;;  Z clear when the Exploding Dwarf is on.  A clobbered.
dwarf_on:
    LDA f:SRAMFAR_FUN
    AND #FUN_DWARF
    RTS

;;  From rando_dlgtext with nothing armed: his line, dialogue DLG_HURRAY, the
;;  row on -- his last words instead (lut_DwarfLine, the world chunk's), and
;;  the burst for when the box closes.  Out: C set, text_ptr's low byte his
;;  line's and A its high; else C clear.  A8 X8.
fun_dwarfline:
    JSR dwarf_on
    BEQ @no
    LDA f:DLGPTRFAR_HURRAY
    CMP text_ptr
    BNE @no
    LDA f:DLGPTRFAR_HURRAY + 1
    CMP text_ptr+1
    BNE @no
    LDA #1
    STA f:FUN_PENDING
    LDA #<lut_DwarfLine
    STA text_ptr
    LDA #>lut_DwarfLine
    SEC
    RTL
  @no:
    CLC
    RTL

;;  From rando_talk's NPC Guillotine: C set when the object X talks to is the
;;  Hurray dwarf and the row is on -- the guillotine would hide him for good.
;;  A clobbered, X kept.  A8 X8.
fun_spared:
    JSR dwarf_on
    BEQ @no
    LDA mapobj_id, X
    CMP #OBJID_HURRAY
    BNE @no
    SEC
    RTL
  @no:
    CLC
    RTL

;;  The gibs off the screen.  Long stores: a caller's DBR need not decode
;;  low WRAM.  A8 X8; A, X clobbered.
dwarf_park:
    LDX #0
  @gib:
    LDA #GIB_HIDDEN
    STA f:GIB_OAM + 1, X
    INX
    INX
    INX
    INX
    CPX #GIB_N * 4
    BCC @gib
    LDA #1
    STA f:h_oamdirty
    RTS

;;  From StartScreenWipe, as the map is left: whatever burst is gone, and
;;  the next load of the map has him back where he stands.  And from
;;  opt_init, every boot: FUNRAM is WRAM the console does not clear, and
;;  fun_frame reads it from the first frame; a soft reset leaves the gibs
;;  in OAM, and the title would show them.  A8 X8; A, X clobbered.
fun_exit:
fun_init:
    JSR dwarf_park
    LDA #0
    STA f:FUN_ACTIVE
    STA f:FUN_PENDING
    STA f:FUN_PARKED
    RTL

;;  From WaitForVBlank, before the wait: with the sprites switched off the
;;  map is going -- every menu, shop and battle waits a frame so before it
;;  shows -- and the gibs go with it, once.  A frame of the map's that only
;;  waits (a box being drawn) leaves them where they are, as the game's own
;;  sprites stay.  A8 X8.
fun_frame:
    LDA f:FUN_ACTIVE
    BEQ @out
    LDA f:FUN_PARKED
    BNE @out
    LDA f:h_ppumask
    AND #$10                    ; the NES's sprites-on bit
    BNE @out
    JSR dwarf_park
    LDA #1
    STA f:FUN_PARKED
  @out:
    RTL

;;  From Dialogue_CoverSprites_VBl, before its wait, as the game gives its
;;  sprites behind the box the background's priority: the gibs as last drawn
;;  (GIB_SPR), less those behind the box -- a sprite whose NES Y is above the
;;  box's bottom, tmp+11 (dwarfref.cover).  They do not move while it is
;;  open.  A box's frame has the least time of any (user, 2026-11-04: the
;;  burst's remains slowed "opening a dialog box"), so a frame whose box is
;;  the size it was does nothing, and one that grew is a compare a gib.  Put
;;  away (FUN_PARKED), they stay so.  A8 X8.
fun_cover:
    LDA f:FUN_ACTIVE
    BEQ @out
    LDA f:FUN_PARKED
    BNE @out
    LDA tmp+11
    CMP f:FUN_CUT
    BEQ @out
    STA f:FUN_CUT
    PHB
    LDA #^FUNRAM
    PHA
    PLB                         ; FUNRAM's bank; OAM through the direct page
    CLC
    XCE
    REP #$30
    .a16
    .i16
    PHD
    LDA #GIB_OAM
    TCD
    LDA a:.loword(FUN_CUT)      ; tmp+11, as stored above
    AND #$00FF
    SEC
    SBC #NES_TOP_CROP - 1       ; the box's bottom as a SNES Y...
    BCS :+
    LDA #0
:   XBA                         ; ...against the sprite word's high byte
    STA a:.loword(FUN_T)
    LDX #0
  @gib:
    LDA a:.loword(GIB_SPR), X
    CMP a:.loword(FUN_T)
    BCS :+
    LDA #GIB_HIDDEN << 8        ; behind the box
:   STA z:0, X
    INX
    INX
    INX
    INX
    CPX #GIB_N * 4
    BCC @gib
    LDA #1
    STA a:.loword(FUN_REDRAW)   ; the map's next frame puts them all back
    PLD
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    PLB
    LDA #1
    STA f:h_oamdirty
  @out:
    RTL


;;  From the standard map loop, the frame's sprites drawn: the burst, if his
;;  line has just closed, then the gibs' frame -- which costs next to nothing
;;  once they lie still and the screen does too (user, 2026-11-04: they
;;  slowed the game "when walking around in its vicinity").  A8 X8.
fun_smframe:
    LDA f:FUN_PENDING
    BEQ :+
    JSR dwarf_burst
:   LDA f:FUN_ACTIVE
    BNE :+
    RTL
:   PHB
    PHK
    PLB                         ; this chunk: its tables; low WRAM and the
    CLC                         ;   NES's RAM decode here as in any chunk
    XCE
    REP #$30
    .a16
    .i16
    JSR dwarf_heal              ; back from hiding: tiles and colours
    JSR dwarf_step              ; while any gib moves
    JSR dwarf_scroll            ; a new scroll redraws
    LDA f:FUN_REDRAW
    BEQ :+
    JSR dwarf_draw
:   SEP #$30
    .a8
    .i8
    SEC
    XCE
    PLB
    RTL

;;  The burst: find him among the map's objects, take him out of them, and
;;  set the gibs off from his feet (dwarfref.burst), their tiles and colours
;;  in.  A8 X8; out the same.
dwarf_burst:
    LDA #0
    STA f:FUN_PENDING
    LDX #0
  @find:
    LDA mapobj_id, X
    CMP #OBJID_HURRAY
    BEQ @found
    TXA
    CLC
    ADC #16
    TAX
    BNE @find
    RTS                         ; not on this map: nothing to burst
  @found:
    LDA #0
    STA mapobj_id, X            ; gone for the visit; his game flag stands
    PHB
    PHK
    PLB
    CLC
    XCE
    REP #$30
    .a16
    .i16
    ;  His feet, where his sprite has them: 16 per tile with the movement
    ;  counter, and the sprite drawn two above its tile and 16 tall.  Kept
    ;  as a gib sprite's corner, 4 up and left, and the crop off.
    LDA mapobj_gfxX, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:FUN_T
    LDA mapobj_ctrX, X
    AND #$00FF
    CLC
    ADC f:FUN_T
    CLC
    ADC #8 - 4
    STA f:FUN_OX
    LDA mapobj_gfxY, X
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:FUN_T
    LDA mapobj_ctrY, X
    AND #$00FF
    CLC
    ADC f:FUN_T
    CLC
    ADC #13 - 4 - NES_TOP_CROP
    STA f:FUN_OY
    LDA framecounter            ; the draws: a new burst every time
    BNE :+
    INC A
:   STA f:FUN_RNG
    LDX #0
  @gib:
    JSR gib_rnd                 ; the tile
    AND lut_DwarfTMask, X
    CLC
    ADC lut_DwarfTile, X
    STA f:GIB_TILE, X
    JSR gib_rnd                 ; x, across his width
    AND #DWARF_BODY_X
    SEC
    SBC #(DWARF_BODY_X + 1) / 2
    STA f:GIB_X, X
    JSR gib_rnd                 ; y
    AND #DWARF_BODY_Y
    SEC
    SBC #(DWARF_BODY_Y + 1) / 2
    STA f:GIB_Y, X
    JSR gib_rnd                 ; z
    AND lut_DwarfZM, X
    CLC
    ADC lut_DwarfZB, X
    STA f:GIB_Z, X
    JSR gib_rnd                 ; vx, pushed outward by x / 16
    AND lut_DwarfVXM, X
    SEC
    SBC lut_DwarfVXC, X
    STA f:FUN_T
    LDA f:GIB_X, X
    JSR asr4
    CLC
    ADC f:FUN_T
    STA f:GIB_VX, X
    JSR gib_rnd                 ; vy
    AND lut_DwarfVYM, X
    SEC
    SBC lut_DwarfVYC, X
    STA f:GIB_VY, X
    JSR gib_rnd                 ; vz
    AND lut_DwarfVZM, X
    CLC
    ADC lut_DwarfVZB, X
    STA f:GIB_VZ, X
    LDA #0
    STA f:GIB_REST, X
    JSR gib_place
    JSR gib_sprite
    INX
    INX
    CPX #GIB_N * 2
    BCS :+
    JMP @gib
:   LDA #1
    STA f:FUN_MOVING
    JSR dwarf_tiles             ; the tiles and colours in, whatever is there
    SEP #$30
    .a8
    .i8
    SEC
    XCE
    PLB
    LDA #1
    STA f:FUN_ACTIVE
    RTS

.a16
.i16

;;  dwarfref.xs16: the next draw.  Out: A16.  X, Y kept.
gib_rnd:
    LDA f:FUN_RNG
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A
    EOR f:FUN_RNG
    STA f:FUN_RNG               ; s ^= s << 7
    LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    LSR A
    EOR f:FUN_RNG
    STA f:FUN_RNG               ; s ^= s >> 9
    XBA
    AND #$FF00
    EOR f:FUN_RNG
    STA f:FUN_RNG               ; s ^= s << 8
    RTS

;;  A16 shifted right four, its sign kept (the floor, as Python's >>).
asr4:
    CMP #$8000
    ROR A
    CMP #$8000
    ROR A
    CMP #$8000
    ROR A
    CMP #$8000
    ROR A
    RTS

;;  Back from hiding -- a menu, a shop, a battle, any of which may have
;;  loaded the pattern table over them and the palette: the gibs' tiles
;;  again if the cranium's is not as it should be, their colours, and a
;;  redraw.  Nothing else loads CHR while the map's sprites are on, so a
;;  frame that has not hidden them checks nothing.  A16 I16, DBR this chunk.
dwarf_heal:
    LDA f:FUN_PARKED
    AND #$00FF
    BEQ @out
    LDX #32 * $C
  @check:
    LDA f:CHRSHADOW + GIB_SHADOW, X
    CMP lut_DwarfGibs, X
    BNE dwarf_tiles
    INX
    INX
    CPX #32 * $D
    BCC @check
    BRA dwarf_colours
  @out:
    RTS

;;  The gibs' tiles into object slot 14's row of the shadow, then their
;;  colours.  A16 I16, DBR this chunk.
dwarf_tiles:
    LDX #0
  @copy:
    LDA lut_DwarfGibs, X
    STA f:CHRSHADOW + GIB_SHADOW, X
    INX
    INX
    CPX #16 * 32
    BCC @copy
    LDA #GIB_SHADOW
    LDX #GIB_SHADOW + 16 * 32 - 1
    JSL hal_chrdirty + HALFAR
;;  Their colours to the HAL, and every gib drawn again.
dwarf_colours:
    SEP #$20
    .a8
    LDX #7
  @pal:
    LDA lut_DwarfPals, X
    STA h_xpal, X
    DEX
    BPL @pal
    LDA #1
    STA h_xpaldirty
    LDA #0
    STA f:FUN_PARKED
    REP #$20
    .a16
    LDA #1
    STA f:FUN_REDRAW
    RTS

;;  Gib X's sprite's corner in map pixels, from its place: dwarf_draw's
;;  part that does not change with the scroll.  A16 I16; X kept.
gib_place:
    LDA f:GIB_X, X
    JSR hibyte
    CLC
    ADC f:FUN_OX
    STA f:FUN_T2
    LDA f:GIB_Z, X
    JSR hibyte
    STA f:FUN_T
    LDA f:GIB_Y, X
    JSR hibyte
    SEC
    SBC f:FUN_T
    CLC
    ADC f:FUN_OY
    PHX
    PHA
    TXA
    ASL A                       ; four bytes a gib
    TAX
    PLA
    STA f:GIB_MXY + 2, X
    LDA f:FUN_T2
    STA f:GIB_MXY, X
    PLX
    RTS

;;  Gib X's sprite's tile and attributes, which change only as it pools.
;;  A16 I16, DBR this chunk; X kept, Y clobbered.
gib_sprite:
    TXA
    ASL A
    TAY
    SEP #$20
    .a8
    LDA f:GIB_TILE, X
    CLC
    ADC #DWARF_GIB_FIRST
    STA GIB_OAM + 2, Y
    LDA lut_DwarfAttr, X
    STA GIB_OAM + 3, Y
    REP #$20
    .a16
    RTS

;;  dwarfref.step: each gib's frame -- it flies and falls; on the floor a
;;  bouncer bounces back up slower, a drop of blood pools, and a gib too slow
;;  to bounce lies still -- while any does.  A16 I16, DBR this chunk.
dwarf_step:
    LDA f:FUN_MOVING
    BNE :+
    RTS
:   LDA #1
    STA f:FUN_REDRAW
    LDA #0
    STA f:FUN_MOVING
    LDX #0
  @gib:
    LDA f:GIB_REST, X
    BEQ :+
    JMP @next
:   LDA f:GIB_X, X
    CLC
    ADC f:GIB_VX, X
    STA f:GIB_X, X
    LDA f:GIB_Y, X
    CLC
    ADC f:GIB_VY, X
    STA f:GIB_Y, X
    LDA f:GIB_Z, X
    CLC
    ADC f:GIB_VZ, X
    STA f:GIB_Z, X
    LDA f:GIB_VZ, X
    SEC
    SBC #DWARF_GRAVITY
    STA f:GIB_VZ, X
    LDA f:GIB_Z, X
    BMI :+
    JMP @moving                 ; still in the air
:   LDA #0
    STA f:GIB_Z, X
    LDA f:GIB_VZ, X             ; down: (-vz * 5) / 8 back up
    EOR #$FFFF
    INC A
    STA f:FUN_T
    ASL A
    ASL A
    CLC
    ADC f:FUN_T
    LSR A
    LSR A
    LSR A
    STA f:FUN_T
    LDA lut_DwarfBounce, X
    BEQ @settle
    LDA f:FUN_T
    CMP #DWARF_REST_VZ
    BCC @settle
    STA f:GIB_VZ, X
    LDA f:GIB_VX, X             ; vx * 3 / 4
    ASL A
    CLC
    ADC f:GIB_VX, X
    CMP #$8000
    ROR A
    CMP #$8000
    ROR A
    STA f:GIB_VX, X
    LDA f:GIB_VY, X             ; vy / 2
    CMP #$8000
    ROR A
    STA f:GIB_VY, X
  @moving:
    LDA #1
    STA f:FUN_MOVING
    JSR gib_place
    BRA @next
  @settle:
    LDA #1
    STA f:GIB_REST, X
    LDA #0
    STA f:GIB_VX, X
    STA f:GIB_VY, X
    STA f:GIB_VZ, X
    LDA lut_DwarfRest, X
    CMP #$FFFF
    BEQ :+                      ; it keeps its tile
    STA f:FUN_T
    LDA f:GIB_TILE, X           ; a drop pools: the pools, by its own
    AND #$0001
    CLC
    ADC f:FUN_T
    STA f:GIB_TILE, X
:   JSR gib_place
    JSR gib_sprite
  @next:
    INX
    INX
    CPX #GIB_N * 2
    BCS :+
    JMP @gib
:   RTS

;;  The A16 word's high byte, sign extended: its whole pixels, the floor.
hibyte:
    XBA
    AND #$00FF
    CMP #$0080
    BCC :+
    ORA #$FF00
:   RTS

;;  This frame's scroll, as the map objects take it (map pixels: 16 a tile
;;  with the movement counter); a new one redraws.  A16 I16.
dwarf_scroll:
    LDA sm_scroll_x
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:FUN_T
    LDA move_ctr_x
    AND #$00FF
    CLC
    ADC f:FUN_T
    STA f:FUN_SX
    LDA sm_scroll_y
    AND #$00FF
    ASL A
    ASL A
    ASL A
    ASL A
    STA f:FUN_T
    LDA move_ctr_y
    AND #$00FF
    CLC
    ADC f:FUN_T
    STA f:FUN_SY
    CMP f:FUN_LSY
    BNE @new
    LDA f:FUN_SX
    CMP f:FUN_LSX
    BNE @new
    RTS
  @new:
    LDA #1
    STA f:FUN_REDRAW
    RTS

;;  dwarfref.oam: each gib's sprite from its corner in map pixels less the
;;  scroll, the screen 1024 pixels round; off the screen, hidden.  The
;;  position alone, X and Y in a word: the tiles and attributes are
;;  gib_sprite's.  Every frame the screen moves near them, so a tight loop:
;;  the scroll added negated, the carry clear at each add without a CLC (the
;;  loop's BCC and each BCS before leave it so), one index for the corners,
;;  OAM through the direct page and the sprites as drawn.  A16 I16, DBR this
;;  chunk.
dwarf_draw:
    PHB
    PHD
    SEP #$20
    .a8
    LDA #^FUNRAM
    PHA
    PLB                         ; FUNRAM's bank; OAM through the direct page
    REP #$20
    .a16
    LDA #GIB_OAM
    TCD
    LDA a:.loword(FUN_SX)
    STA a:.loword(FUN_LSX)
    EOR #$FFFF
    INC A
    STA a:.loword(FUN_NSX)
    LDA a:.loword(FUN_SY)
    STA a:.loword(FUN_LSY)
    EOR #$FFFF
    INC A
    STA a:.loword(FUN_NSY)
    LDX #0                      ; four bytes a gib, in all three
    CLC
  @gib:
    LDA a:.loword(GIB_MXY), X
    ADC a:.loword(FUN_NSX)
    AND #$03FF
    CMP #252 - 4                ; dwarfref.oam: 4 <= px < 252
    BCS @hide
    STA a:.loword(FUN_T)
    LDA a:.loword(GIB_MXY) + 2, X
    ADC a:.loword(FUN_NSY)
    AND #$03FF
    CMP #220 - 4                ; ...and the crop + 4 <= py < the crop + 220
    BCS @hide
    XBA
    ORA a:.loword(FUN_T)
    STA z:0, X
    STA a:.loword(GIB_SPR), X
    INX
    INX
    INX
    INX
    CPX #GIB_N * 4
    BCC @gib
    BRA @done
  @hide:
    LDA #GIB_HIDDEN << 8
    STA z:0, X
    STA a:.loword(GIB_SPR), X
    INX
    INX
    INX
    INX
    CPX #GIB_N * 4
    BCC @gib
  @done:
    LDA #0
    STA a:.loword(FUN_REDRAW)
    PLD
    PLB
    SEP #$20
    .a8
    LDA #$FF
    STA f:FUN_CUT               ; a box's cover starts again from these
    LDA #1
    STA f:h_oamdirty
    REP #$20
    .a16
    RTS
