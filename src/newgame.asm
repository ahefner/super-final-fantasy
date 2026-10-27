; ---------------------------------------------------------------------------
;  newgame.asm -- New Game's flow (CHUNK_NEWGAME).
;
;  The New Game list's presets, from presets/*.toml by tools/genpresets.py:
;  Vanilla, Improved Vanilla, and presets adapted from FFR's (menus.txt in
;  the project directory; randomization-notes.md, 12).  A preset is every
;  setting the settings screen and the randomization screen show, as
;  (row, value) pairs, which ngp_apply writes through the settings screen's
;  own tables -- so the presets hold no second copy of the option block's
;  layout, and a row the screen gains is a row the presets set (the base
;  preset, Improved Vanilla, must name it or the build stops).
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "fftext.inc"
;  CALL0E: party creation is bank $0E's.
.include "optcall.inc"

.import lut_ValOff, lut_ValBit, lut_ValMask, opt_commit
.import opt_newgamelist, opt_randoscreen, opt_settings, ows_choose
.import opt_needseed, seed_choose, rando_build
.import OptCallFar, NewGamePartyUI
.export ngp_apply, ng_flow
.export lut_NgpTitle, lut_NgpDataPtr, lut_NgpFlow   ; for tools/test_options.py
.export lut_NgpEdits

.segment "BANK_NEWGAME"

.include "presets.inc"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ngp_apply -- write New Game preset A over the option block, and seal it
;;
;;  The flag word and the new-game bytes cleared first, as the title's
;;  presets clear the new-game bytes, then every setting written as the
;;  settings screen writes it: a checkbox's bit set or cleared, a value row's
;;  value put in its byte's bits (lut_ValOff, lut_ValBit, lut_ValMask).  So
;;  the block is the preset's alone, but for the respond rate, which no
;;  preset sets (the player's own).  OPT_PRESET names the title's preset the
;;  preset is, or Custom.  Then opt_commit: the derived bytes and the
;;  checksum.  A preset is applied when it is chosen, and backing out leaves
;;  it applied (randomization-notes.md, 12).
;;
;;  In: A = the preset.  Emulation mode, by JSL; X and Y not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ngp_apply:
    PHB
    PHK
    PLB                         ; this chunk's low half decodes SRAM
    PHA
    TAX
    LDA lut_NgpTitle, X
    STA OPT_PRESET
    LDA #0
    LDX #OPT_FLAGBYTES - 1
  @flags:
    STA OPT_FLAGS, X
    DEX
    BPL @flags
    LDX #OPT_NG_SIZE - 1
  @ng:
    STA OPT_NG, X
    DEX
    BPL @ng
    PLA
    ASL A
    TAX
    LDA lut_NgpDataPtr, X
    STA tmp
    LDA lut_NgpDataPtr + 1, X
    STA tmp + 1
    LDY #0
  @pair:
    LDA (tmp), Y                ; the row: a flag bit + $80, or a scalar
    CMP #$FF
    BEQ @done
    INY
    TAX
    BMI @flag
    ;  A value row: its value into its bits.  tmp+2 the value shifted into
    ;  place, tmp+3 the mask, X the byte's offset in the option page.
    LDA f:OPTMENUFAR + lut_ValMask, X
    STA tmp + 3
    LDA f:OPTMENUFAR + lut_ValBit, X
    PHA
    LDA f:OPTMENUFAR + lut_ValOff, X
    TAX
    LDA (tmp), Y
    STA tmp + 2
    PLA
    BEQ :++
:   ASL tmp + 2
    DEC A
    BNE :-
:   LDA tmp + 3
    EOR #$FF
    AND OPTBLOCK, X
    STA OPTBLOCK, X
    LDA tmp + 2
    AND tmp + 3
    ORA OPTBLOCK, X
    STA OPTBLOCK, X
    INY
    BRA @pair
  @flag:
    ;  A checkbox: bit X & $7F of the flag word, set when the value is.
    TXA
    AND #$07
    TAX
    LDA lut_NgpBit, X
    STA tmp + 3
    LDA (tmp), Y                ; the value...
    PHA
    DEY
    LDA (tmp), Y                ; ...and the bit again, for its byte
    INY
    AND #$7F
    LSR A
    LSR A
    LSR A
    TAX
    PLA
    BEQ :+
    LDA tmp + 3
    ORA OPT_FLAGS, X
    STA OPT_FLAGS, X
:   INY
    BRA @pair
  @done:
    JSL opt_commit + OPTFAR     ; the derived bytes, and the checksum
    PLB
    RTL

lut_NgpBit:
  .BYTE $01, $02, $04, $08, $10, $20, $40, $80


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  ng_flow -- New Game's screens, from the title's New Game (menus.txt;
;;  randomization-notes.md, 12)
;;
;;    the list -- Custom Game, or a preset, applied as it is picked;
;;      Vanilla alone goes straight on to party creation (its file's
;;      skip_to_party; user, 2026-10-22: Improved Vanilla is the baseline
;;      one might customize)
;;    the randomization screen -- TREASURES, RANDOMIZATION, KEY ITEMS
;;    the map edits (owscreen.asm) -- the vanilla overworld's, overworld
;;      select being still to come (user: as if the vanilla map were
;;      chosen); winnable, or START is refused
;;    the options -- the rest of the settings
;;    the seed (seedscreen.asm) -- when anything on the randomization
;;      screen is set (opt_needseed); a fresh one latched from the pool
;;      each time the screen comes up, forward or back (user, 2026-10-27)
;;    the world built (ng_build, rando_build), the roll screen up -- every
;;      random thing locked down before party creation (user, 2026-10-27);
;;      a seed whose placement gives up is said so there, and the seed
;;      screen comes back, with a fresh seed
;;    party creation (bank $0E's) -- after the seed, so that a seeded
;;      feature could show there what the party is choosing between (user)
;;
;;  START goes on to the next, B back to the one before -- party creation's
;;  B on its first character -- and B on the list back to the title.  Still
;;  to come: overworld select.  New Game's seed is NGF_SEED, which
;;  rando_build takes as it takes the edits: latched from the pool, as New
;;  Game always took it, whether or not the seed screen came up.  Each
;;  screen takes the PPU and leaves it off, and the title or party creation
;;  builds its own after.
;;
;;  The map edits ticked are kept in NGF_OWEDITS, which rando_build takes
;;  for New Game's: the save's first page, where RANDO_OWEDITS is, it sets
;;  afresh before.  The screen starts from the
;;  edits last ticked in this pass; first, after a preset, from its file's
;;  [map_edits] (ng_presetedits); after Custom Game from the saved game's,
;;  if Continue would load one with any, else none.
;;
;;  From opt_titlechoose, by JSL, emulation mode.  Out: A = NGNAV_FORWARD to
;;  start the game (party creation), NGNAV_BACK to go back to the title.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ng_flow:
  @list:
    LDA #0
    STA f:NGF_HAVE              ; a choice here starts the map edits afresh
    STA f:NGF_ACTIVE
    STA f:NGF_BUILT             ; ...and the world
    JSL opt_newgamelist + OPTMENUFAR
    STA f:NGF_PICK
    CMP #NGPICK_BACK
    BNE :+
    LDA #NGNAV_BACK             ; B: back to the title
    RTL
:   CMP #NGPICK_CUSTOM
    BEQ @rando
    PHA
    JSL ngp_apply + NEWGAMEFAR  ; the preset, written as it is picked
    PLA
    TAX
    LDA f:NEWGAMEFAR + lut_NgpFlow, X
    BNE @rando
    JSR ng_presetedits          ; no screens: its map edits (none, for
    JSR ng_keepedits            ;   Vanilla), and
    JSR ng_latch                ;   on to party creation, with the pool's seed
    JSR ng_build                ;   (nothing to place: always built)
    JSR ng_party
    BCS @list                   ; B on the first character: the list again
    BRA @go
  @rando:
    JSL opt_randoscreen + OPTMENUFAR
    CMP #NGNAV_BACK
    BEQ @list
    JSR ng_settings             ; the settings the map edits' check reads
  @mapedits:
    LDA f:NGF_HAVE
    BEQ @fresh
    JSR ng_restoreedits         ; back here: the edits last ticked
    BRA @keep
  @fresh:
    LDA f:NGF_PICK
    CMP #NGPICK_CUSTOM
    BEQ @custom
    JSR ng_presetedits          ; a preset: its map edits, as given
    BRA @keep
  @custom:
    LDA #0                      ; Custom Game: the saved game's, else none
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    LDA #OWS_CANBACK
    BRA @show
  @keep:
    LDA #OWS_KEEP | OWS_CANBACK
  @show:
    JSL ows_choose + OWSFAR
    PHA
    JSR ng_keepedits
    PLA
    CMP #NGNAV_BACK
    BEQ @rando
  @options:
    JSL opt_settings + OPTMENUFAR
    CMP #NGNAV_BACK
    BEQ @mapedits
    JSL opt_needseed + OPTMENUFAR
    BCS @seed
    JSR ng_latch                ; nothing randomized: a seed all the same,
    BRA @party                  ;   unseen
  @seed:
    JSR ng_latch                ; a fresh one, whichever way the screen is
    JSL seed_choose + OPTMENUFAR    ;   come to (user, 2026-10-27)
    CMP #NGNAV_BACK
    BEQ @options
    JSR ng_build
    BCS @seed                   ; no world: the seed screen again
    JSR ng_party
    BCS @seed                   ; back: the seed screen again
    BRA @go
  @party:
    JSR ng_build                ; (nothing randomized places nothing)
    BCS @options
    JSR ng_party
    BCS @options
  @go:
    LDA #1
    STA f:NGF_ACTIVE            ; rando_newgame's: the world is built
    LDA #NGNAV_FORWARD
    RTL

;;  The world, before party creation (rando_build), the roll screen up --
;;  or kept, with no roll screen, when this pass of the flow built it from
;;  the seed, the settings and the map edits it has now (user, 2026-10-27:
;;  an unchanged seed keeps the world).  The seed screen latching a fresh
;;  seed each time, that is a seed typed again.  The cache's tag is what
;;  the world was built from.  The menus' music off through the build, the
;;  roll's tune its own.  Out: C clear, the world built; C set, none, the
;;  roll screen having said so.
ng_build:
    LDA f:NGF_BUILT
    BEQ @build
    LDA f:RW_TAG
    CMP #RW_TAG_VAL
    BNE @build
    LDX #$03
  @seed:
    LDA f:NGF_SEED, X
    CMP f:RW_TAGBLK + (RANDO_SEED - RANDO_SAVE), X
    BNE @build
    DEX
    BPL @seed
    LDX #OPT_NG_SIZE - 1
  @ng:
    LDA f:OPT_NGFAR, X
    CMP f:RW_TAGBLK + RANDO_NGOFF, X
    BNE @build
    DEX
    BPL @ng
    LDA f:NGF_OWEDITS
    CMP f:RW_TAGBLK + (RANDO_OWEDITS - RANDO_SAVE)
    BNE @build
    LDA f:NGF_OWEDITS + 1
    CMP f:RW_TAGBLK + (RANDO_OWEDITS - RANDO_SAVE) + 1
    BNE @build
    CLC                         ; the world as it was built
    RTS
  @build:
    LDA #0
    STA f:NGF_BUILT
    STA f:MENU_TICKON
    JSL rando_build + RANDOFAR
    LDA #1                      ; (C kept)
    STA f:MENU_TICKON
    BCS :+
    STA f:NGF_BUILT
:   RTS

;;  Party creation: the game's own screens (NewGamePartyUI), their CHR and
;;  palettes their own, the title's music played on by their frames.  Out:
;;  C clear, the party recorded; C set, B on the first character.
ng_party:
    CALL0E NewGamePartyUI
    RTS

;;  New Game's seed, NGF_SEED, from the pool -- or, in a build with FFSEED
;;  set, that seed.
ng_latch:
.ifdef FORCE_SEED
    LDA #<(FORCE_SEED)
    STA f:NGF_SEED
    LDA #>(FORCE_SEED)
    STA f:NGF_SEED + 1
    LDA #^(FORCE_SEED)
    STA f:NGF_SEED + 2
    LDA #<((FORCE_SEED) >> 24)
    STA f:NGF_SEED + 3
.else
    LDX #$03
  @seed:
    LDA f:RANDO_POOLFAR, X
    STA f:NGF_SEED, X
    DEX
    BPL @seed
.endif
    RTS

;;  The options' new-game rows into the save's settings, as the build
;;  copies them (new_world): rando_winnable, the map edit screen's check,
;;  reads them there.  The build copies them again after setting the save's
;;  first page.
ng_settings:
    LDX #OPT_NG_SIZE - 1
  @ng:
    LDA f:OPT_NGFAR, X
    STA f:RANDO_SAVEFAR + RANDO_NGOFF, X
    DEX
    BPL @ng
    RTS

;;  RANDO_OWEDITS: a preset's map edits, its file's [map_edits] as
;;  genpresets.py makes them bits (lut_NgpEdits; user, 2026-10-24: "Presets
;;  should be able to toggle map edits individually").  NGF_PICK the preset.
ng_presetedits:
    LDA f:NGF_PICK
    ASL A
    TAX
    LDA f:NEWGAMEFAR + lut_NgpEdits, X
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    LDA f:NEWGAMEFAR + lut_NgpEdits + 1, X
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    RTS

;;  RANDO_OWEDITS kept as New Game's (NGF_OWEDITS), and back.
ng_keepedits:
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    STA f:NGF_OWEDITS
    LDA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    STA f:NGF_OWEDITS + 1
    LDA #1
    STA f:NGF_HAVE
    RTS
ng_restoreedits:
    LDA f:NGF_OWEDITS
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    LDA f:NGF_OWEDITS + 1
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE) + 1
    RTS
