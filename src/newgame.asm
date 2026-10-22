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
.import opt_newgamelist, opt_randoscreen, opt_settings, ows_choose, lut_OwEditsMode
.import opt_needseed, seed_choose
.import OptCallFar, NewGamePartyUI
.export ngp_apply, ng_flow
.export lut_NgpTitle, lut_NgpDataPtr, lut_NgpFlow   ; for tools/test_options.py

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
;;      Vanilla and Improved Vanilla go straight on to party creation
;;    the randomization screen -- TREASURES, RANDOMIZATION, KEY ITEMS
;;    the map edits (owscreen.asm) -- the vanilla overworld's, overworld
;;      select being still to come (user: as if the vanilla map were
;;      chosen); winnable, or START is refused
;;    the options -- the rest of the settings
;;    the seed (seedscreen.asm) -- when anything on the randomization
;;      screen is set (opt_needseed); latched from the pool on the way in
;;    party creation (bank $0E's) -- after the seed, so that a seeded
;;      feature could show there what the party is choosing between (user)
;;
;;  START goes on to the next, B back to the one before -- party creation's
;;  B on its first character -- and B on the list back to the title.  Still
;;  to come: overworld select.  New Game's seed is NGF_SEED, which
;;  rando_newgame takes as it takes the edits: latched from the pool, as New
;;  Game always took it, whether or not the seed screen came up.  The world
;;  is built after all of this, from GameStart (NewGamePartyGeneration).  Each screen takes the PPU and leaves it
;;  off, and the title or party creation builds its own after.
;;
;;  The map edits ticked are kept in NGF_OWEDITS, which rando_newgame takes
;;  for New Game's (NGF_ACTIVE): the save's first page, where RANDO_OWEDITS
;;  is, is set afresh by New Game before then.  The screen starts from the
;;  edits last ticked in this pass; first, after a preset, from its Map
;;  edits row's; after Custom Game, as it always has, from the saved game's
;;  if Continue would load one with any, else the row's.
;;
;;  From opt_titlechoose, by JSL, emulation mode.  Out: A = NGNAV_FORWARD to
;;  start the game (party creation), NGNAV_BACK to go back to the title.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

ng_flow:
  @list:
    LDA #0
    STA f:NGF_HAVE              ; a choice here starts the map edits afresh
    STA f:NGF_ACTIVE
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
    JSR ng_rowedits             ; nothing randomized: its row's edits (none,
    JSR ng_keepedits            ;   for Vanilla and Improved Vanilla), and
    JSR ng_latch                ;   on to party creation, with the pool's seed
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
    JSR ng_rowedits
    LDA f:NGF_PICK
    CMP #NGPICK_CUSTOM
    BNE @keep                   ; a preset: its row's, as given
    LDA #OWS_CANBACK            ; Custom Game: the saved game's, else the row's
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
    JSR ng_latch                ; a seed, shown to keep or type over --
    JSL opt_needseed + OPTMENUFAR
    BCC @party                  ;   or, nothing randomized, kept unseen
  @seed:
    JSL seed_choose + OPTMENUFAR
    CMP #NGNAV_BACK
    BEQ @options
    JSR ng_party
    BCS @seed                   ; back: the seed as chosen, typed or not
    BRA @go
  @party:
    JSR ng_party
    BCS @options
  @go:
    LDA #1
    STA f:NGF_ACTIVE            ; rando_newgame's to take
    LDA #NGNAV_FORWARD
    RTL

;;  Party creation: the game's own screens (NewGamePartyUI), their CHR and
;;  palettes their own, the title's music played on by their frames.  Out:
;;  C clear, the party recorded; C set, B on the first character.
ng_party:
    CALL0E NewGamePartyUI
    RTS

;;  New Game's seed, NGF_SEED, from the pool -- or, in a build with FFSEED
;;  set, that seed -- not typed.
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
    LDA #0
    STA f:NGF_TYPED
    RTS

;;  The options' new-game rows into the save's settings, as rando_newgame
;;  copies them: rando_winnable, the map edit screen's check, reads them
;;  there.  New Game copies them again after setting the save's first page.
ng_settings:
    LDX #OPT_NG_SIZE - 1
  @ng:
    LDA f:OPT_NGFAR, X
    STA f:RANDO_SAVEFAR + RANDO_NGOFF, X
    DEX
    BPL @ng
    RTS

;;  RANDO_OWEDITS: the Map edits row's mode as the flags it stands for, as
;;  rando_newgame makes them (lut_OwEditsMode).
ng_rowedits:
    LDA f:OPT_NGFAR + (OPT_NG_EARLY - OPT_NG)
    AND #OWEDITS_FIELD
    LSR A
    LSR A
    LSR A                       ; the mode, in words
    TAX
    LDA f:RANDOFAR + lut_OwEditsMode, X
    STA f:RANDO_SAVEFAR + (RANDO_OWEDITS - RANDO_SAVE)
    LDA f:RANDOFAR + lut_OwEditsMode + 1, X
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
