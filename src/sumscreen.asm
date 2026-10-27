; ---------------------------------------------------------------------------
;  sumscreen.asm -- New Game's Seed Summary (user, 2026-10-27), in the
;  settings screen's chunk (CHUNK_OPTMENU): its frame, chirps and text
;  routines are that engine's.
;
;  After the roll screen, under Key items Standard or Wide, before party
;  creation: the world the seed built, read from it.
;
;    - The seed, across the top.
;    - The Goal; the Map shuffle mode the game has (RW_ENTRANCES -- Off when
;      no wiring placed, whatever the setting); the SHIP or AIRSHIP removed.
;    - Placement's numbers, labelled as the map edit screen's Select shows
;      them (lut_OwsIncLabel), all five here: the world is built, its
;      wiring chosen.
;    - The incentive places the party can reach, by name (user: "named
;      individually rather than people having to remember what 'Standard'
;      vs. 'Wide' means"), the people in the left column and the places in
;      the right; those it cannot reach left out (user: "Excluding
;      unreachable places and NPCs would be a nice touch").
;
;  A or START goes on to party creation, B back to the seed screen.  No
;  hand: nothing to choose.  The title's music plays on, and L + X / L + Y
;  reset from it, through WaitForVBlank_L as on the settings screen.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "fftext.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nesio.inc"
.include "optmenu.inc"
.include "logic.inc"            ; LOGIC_NSTANDARD, LOGIC_NWIDE

.export sum_show
.export lut_SumPlaces           ; for tools/test_options.py
.import opt_menu_breathe, opt_menu_fillbg, opt_menu_descppu
.import opt_sfx_sel, opt_waitrelease
.import lut_ValGoal, lut_ValMapShuffle
.import lut_OwsIncLabel         ; the map edit screen's (owscreen.asm)
.import ClearOAM, CallMusicPlay, UpdateJoy, WaitForVBlank_L
.import hal_clearnt, hal_ntblit

.segment "BANK_OPTMENU"

;  The layout, in nametable rows, within the 30 x 26 a CRT shows (rows 2-27);
;  every line starts in DESC_COL, as the descriptions do (opt_menu_descppu),
;  and is SUM_LINEW wide.
SUM_LINEW    = DESC_W
SUM_SEEDROW  = 2
SUM_SEEDCOL  = 8                ; "SEED 0BADF00D", centred
SUM_GOALROW  = 4                ; Goal, Map shuffle, Removed
SUM_NUMROW   = 8                ; the five numbers
SUM_LISTROW  = 14               ; the places, a row each, at most...
SUM_LISTROWS = 13               ; ...the people's thirteen
SUM_RIGHTCOL = 14               ; the places' column, in the line
SUM_NAMEW    = 13
SUM_LABELW   = 12               ; Goal, Map shuffle, Removed
SUM_READW    = 16               ; ...their readouts, ending the line
INCLABEL_W   = 18               ; owscreen.asm's INC_LABELW
OWS_BANK     = CHUNK0 + CHUNK_OWS
.assert SUM_LISTROW + SUM_LISTROWS <= 28, error, "the places run past what a CRT shows"
.assert SUM_LABELW + SUM_READW <= SUM_LINEW, error, "a label and its readout overlap"

;  The screen's scratch, in the engine's (MENURAM), past the flow's: the seed
;  screen's too, which is never up at the same time.
SUM_N      = MENURAM + $20      ; the five numbers, lut_OwsIncLabel's order:
SUM_LEFT   = MENURAM + $28      ; the people shown, entries of lut_SumPlaces...
SUM_RIGHT  = MENURAM + $38      ; ...and the places
SUM_NLEFT  = MENURAM + $48      ; how many of each
SUM_NRIGHT = MENURAM + $49
.assert SUM_NRIGHT < MENURAM_END, error, "the summary's scratch runs past the engine's"


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  sum_show -- the screen.  In: the world built (RW_PLACED), the save's
;;  first page its settings.  Out: A = NGNAV_FORWARD for A or START,
;;  NGNAV_BACK for B; the screen off, as the settings screen leaves it.  From
;;  the New Game flow, by JSL, emulation mode; X and Y not kept.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

sum_show:
    PHB
    PHK
    PLB
    LDA #$00
    wPPUMASK                    ; screen off while it is built
    JSL hal_clearnt + HALFAR
    JSR opt_menu_fillbg
    JSR sum_draw
    JSR ClearOAM                ; no hand, nor anything the roll left
    LDA #>oam
    wOAMDMA
    JSR opt_menu_breathe        ; ...sent
    LDA #$1E
    wPPUMASK                    ; ...and on
    JSR opt_waitrelease         ; the START that brought it carries no further

  @loop:
    JSR WaitForVBlank_L
    LDA #CHUNK_OPTMENU
    STA cur_bank                ; CallMusicPlay comes back through this
    JSR CallMusicPlay
    JSR UpdateJoy
    LDA joy                     ; down now and not down last frame
    EOR f:OPTMENU_PREV
    AND joy
    STA f:OPTMENU_EDGE
    LDA joy
    STA f:OPTMENU_PREV
    LDA f:OPTMENU_EDGE
    AND #PAD_A | PAD_START
    BNE @on
    LDA f:OPTMENU_EDGE
    AND #PAD_B
    BEQ @loop
    LDA #NGNAV_BACK
    BRA @leave
  @on:
    LDA #NGNAV_FORWARD
  @leave:
    PHA
    JSR opt_sfx_sel             ; the game's sound for a choice, B's too
    JSR opt_waitrelease         ; nothing carries on to the next screen
    LDA #$00
    wPPUMASK
    PLA
    PLB
    RTL


;;  Every line, a breath between the groups, as the settings screen draws
;;  five rows a frame (opt_menu_drawall).
sum_draw:
    JSR sum_seed
    JSR sum_settings
    JSR opt_menu_breathe
    JSR sum_numbers
    JSR opt_menu_breathe
    JSR sum_lists
    LDA #0
  @row:
    PHA
    JSR sum_listrow
    PLA
    INC A
    CMP #5
    BEQ @breathe
    CMP #10
    BNE @next
  @breathe:
    PHA
    JSR opt_menu_breathe
    PLA
  @next:
    CMP #SUM_LISTROWS
    BCC @row
    RTS

;;  "SEED" and the save's seed, eight hex digits high nibble first, as the
;;  save view shows it: the digit tiles run on into the capitals, so a
;;  nibble is its own tile from $80.
sum_seed:
    JSR sum_blank
    LDX #0
  : LDA lut_SumSeed, X
    STA f:NTSTAGE + SUM_SEEDCOL, X
    INX
    CPX #5
    BCC :-
    LDA #3
    STA tmp + 3                 ; the seed's byte, high first
    LDX #SUM_SEEDCOL + 5
  @digit:
    PHX
    LDX tmp + 3
    LDA f:RANDO_SAVEFAR + (RANDO_SEED - RANDO_SAVE), X
    PLX
    PHA
    LSR A
    LSR A
    LSR A
    LSR A
    ORA #$80
    STA f:NTSTAGE, X
    INX
    PLA
    AND #$0F
    ORA #$80
    STA f:NTSTAGE, X
    INX
    DEC tmp + 3
    BPL @digit
    LDA #SUM_SEEDROW
    JMP sum_blit

;;  Goal, Map shuffle and Removed: each a label, and its readout ending the
;;  line -- the settings screen's own for the first two (lut_ValGoal,
;;  lut_ValMapShuffle).  A step out of range reads as the first, as there.
sum_settings:
    JSR sum_blank
    LDA #0
    JSR sum_label
    LDA f:RANDO_SAVEFAR + (RANDO_GOAL - RANDO_SAVE)
    CMP #GOAL_MODES
    BCC :+
    LDA #0
:   ASL A
    ASL A
    ASL A                       ; x 8, the readout's width
    LDX #<lut_ValGoal
    LDY #>lut_ValGoal
    JSR sum_point
    LDA #8
    LDX #SUM_LINEW - 8
    JSR sum_copy
    LDA #SUM_GOALROW
    JSR sum_blit

    JSR sum_blank
    LDA #1
    JSR sum_label
    LDA f:RW_ENTRANCES          ; the mode the game has
    CMP #ENTRANCES_MODES
    BCC :+
    LDA #0
:   ASL A
    ASL A
    ASL A
    ASL A                       ; x 16
    LDX #<lut_ValMapShuffle
    LDY #>lut_ValMapShuffle
    JSR sum_readout
    LDA #SUM_GOALROW + 1
    JSR sum_blit

    JSR sum_blank
    LDA #2
    JSR sum_label
    LDA #0
    STA tmp + 3
    LDA f:RANDO_SAVEFAR + (RANDO_ITEMS - RANDO_SAVE)
    AND #3 << (2 * ITEMROW_SHIP)
    CMP #ITEM_REMOVE << (2 * ITEMROW_SHIP)
    BNE :+
    INC tmp + 3                 ; 1: the SHIP
:   LDA f:RANDO_SAVEFAR + (RANDO_ITEMS - RANDO_SAVE)
    AND #3 << (2 * ITEMROW_AIRSHIP)
    CMP #ITEM_REMOVE << (2 * ITEMROW_AIRSHIP)
    BNE :+
    INC tmp + 3                 ; 2: the AIRSHIP
    INC tmp + 3
:   LDA tmp + 3
    ASL A
    ASL A
    ASL A
    ASL A                       ; x 16
    LDX #<lut_SumRemoved
    LDY #>lut_SumRemoved
    JSR sum_readout
    LDA #SUM_GOALROW + 2
    JMP sum_blit

;;  Label A of lut_SumLabel, at the line's start.
sum_label:
    ASL A
    ASL A                       ; x 12: x 4...
    STA tmp + 3
    ASL A                       ; ...plus x 8
    CLC
    ADC tmp + 3
    LDX #<lut_SumLabel
    LDY #>lut_SumLabel
    JSR sum_point
    LDA #SUM_LABELW
    LDX #0
    JMP sum_copy

;;  A SUM_READW readout at offset A of the table at Y:X, ending the line.
sum_readout:
    JSR sum_point
    LDA #SUM_READW
    LDX #SUM_LINEW - SUM_READW
    JMP sum_copy

;;  The five numbers, worked out as the map edit screen's Select works its
;;  out (ows_incdesc), from placement's (pl_summary): the incentive items;
;;  the locations the setting names; those reached; the excess loose, past
;;  the locations; and the unreachable loose, past those reached, less the
;;  excess.  Each a line: its label, from the map edit screen's own table,
;;  and two cells.
sum_numbers:
    LDA f:RW_SUMINC
    STA f:SUM_N
    LDA f:RANDO_SAVEFAR + (RANDO_KEYITEMS - RANDO_SAVE)
    LDX #LOGIC_NSTANDARD
    CMP #KEYITEMS_WIDE
    BNE :+
    LDX #LOGIC_NWIDE
:   TXA
    STA f:SUM_N + 1
    LDA f:RW_SUMREACH
    STA f:SUM_N + 2
    LDA f:SUM_N                 ; the excess: past the locations, or none
    SEC
    SBC f:SUM_N + 1
    BCS :+
    LDA #0
:   STA f:SUM_N + 3
    LDA f:SUM_N                 ; the unreachable: past those reached, or
    SEC                         ;   none...
    SBC f:SUM_N + 2
    BCS :+
    LDA #0
:   SEC
    SBC f:SUM_N + 3             ; ...less the excess
    STA f:SUM_N + 4
    LDA #0
  @line:
    PHA
    JSR sum_blank
    PLA
    PHA
    TAX
    LDA lut_SumIncBy18, X       ; the label, from the map edit screen's chunk
    LDX #<lut_OwsIncLabel
    LDY #>lut_OwsIncLabel
    JSR sum_point
    PHB
    LDA #OWS_BANK
    PHA
    PLB
    LDA #INCLABEL_W
    LDX #0
    JSR sum_copy
    PLB
    PLA
    PHA
    TAX
    LDA f:SUM_N, X              ; ...and the number
    LDX #SUM_LINEW - 2
    JSR sum_num
    PLA
    PHA
    CLC
    ADC #SUM_NUMROW
    JSR sum_blit
    PLA
    INC A
    CMP #5
    BCC @line
    RTS

;;  The people and the places shown: those placement found reachable
;;  (RW_SUMSPOTS), of the Wide set -- which holds the Standard set, and a
;;  place of Wide's alone is never a spot under Standard.
sum_lists:
    LDX #0
    LDY #0
  @people:
    JSR sum_shown
    BCC :+
    TYA
    STA f:SUM_LEFT, X
    INX
:   INY
    CPY #SUM_NPEOPLE
    BCC @people
    TXA
    STA f:SUM_NLEFT
    LDX #0
  @places:
    JSR sum_shown
    BCC :+
    TYA
    STA f:SUM_RIGHT, X
    INX
:   INY
    CPY #SUM_NALL
    BCC @places
    TXA
    STA f:SUM_NRIGHT
    RTS

;;  Entry Y of lut_SumPlaces: shown?  C set if so.  X and Y kept.
sum_shown:
    PHX
    PHY
    TYA
    JSR sum_entry
    LDY #0
    LDA (tmp), Y                ; its place in the logic
    TAX
    LDA f:RW_SUMSPOTS, X
    PLY
    PLX
    CMP #1                      ; 1: C set
    RTS

;;  Row A of the list: the next person shown, and the next place.
sum_listrow:
    PHA
    JSR sum_blank
    PLA
    PHA
    CMP f:SUM_NLEFT
    BCS :+
    TAX
    LDA f:SUM_LEFT, X
    LDX #0
    JSR sum_name
:   PLA
    PHA
    CMP f:SUM_NRIGHT
    BCS :+
    TAX
    LDA f:SUM_RIGHT, X
    LDX #SUM_RIGHTCOL
    JSR sum_name
:   PLA
    CLC
    ADC #SUM_LISTROW
    JMP sum_blit

;;  Entry A's name, at X in the line.
sum_name:
    PHX
    JSR sum_entry
    INC tmp                     ; past its place in the logic
    BNE :+
    INC tmp + 1
:   PLX
    LDA #SUM_NAMEW
    JMP sum_copy

;;  tmp = entry A of lut_SumPlaces, sixteen bytes each.  X clobbered.
sum_entry:
    STA tmp
    LDA #0
    STA tmp + 1
    LDX #4
  : ASL tmp
    ROL tmp + 1
    DEX
    BNE :-
    LDA tmp
    CLC
    ADC #<lut_SumPlaces
    STA tmp
    LDA tmp + 1
    ADC #>lut_SumPlaces
    STA tmp + 1
    RTS

;;  tmp = Y:X plus A.
sum_point:
    STX tmp
    STY tmp + 1
    CLC
    ADC tmp
    STA tmp
    BCC :+
    INC tmp + 1
:   RTS

;;  A bytes from (tmp) -- in the data bank -- to the line at X.  Y
;;  clobbered.
sum_copy:
    STA tmp + 2
    LDY #0
  : LDA (tmp), Y
    STA f:NTSTAGE, X
    INX
    INY
    CPY tmp + 2
    BCC :-
    RTS

;;  The number A, 0-99, in the two cells at X: a blank for a leading zero.
sum_num:
    LDY #0
  @tens:
    CMP #10
    BCC @ones
    SBC #10                     ; (C set)
    INY
    BRA @tens
  @ones:
    PHA
    TYA
    BEQ :+
    ORA #$80
    BRA :++
:   LDA #$FF
:   STA f:NTSTAGE, X
    INX
    PLA
    ORA #$80
    STA f:NTSTAGE, X
    RTS

;;  A blank line staged.
sum_blank:
    LDX #SUM_LINEW - 1
    LDA #$FF
  : STA f:NTSTAGE, X
    DEX
    BPL :-
    RTS

;;  The line staged, to row A.
sum_blit:
    STA OPTMENU_ROWNUM
    JSR opt_menu_descppu
    LDX #SUM_LINEW
    JSL hal_ntblit + HALFAR
    RTS


lut_SumSeed:
  FFTEXT "SEED "
lut_SumLabel:
  FFPAD "Goal", SUM_LABELW
  FFPAD "Map shuffle", SUM_LABELW
  FFPAD "Removed", SUM_LABELW
;  The SHIP's and the AIRSHIP's Remove (RANDO_ITEMS), bit 0 and bit 1.
lut_SumRemoved:
  FFPAD "            None", SUM_READW
  FFPAD "            SHIP", SUM_READW
  FFPAD "         AIRSHIP", SUM_READW
  FFPAD "   SHIP, AIRSHIP", SUM_READW
;  lut_OwsIncLabel's labels, by number.
lut_SumIncBy18:
  .BYTE 0, INCLABEL_W, 2 * INCLABEL_W, 3 * INCLABEL_W, 4 * INCLABEL_W

;  The incentive places, Wide's 25 -- Standard's 21 among them -- in the
;  order shown: each its place in the logic (logicdata.inc, tools/genlogic.py;
;  tools/test_options.py checks them against it) and its name.  The people
;  first, in the left column, then the places.
.macro SUMPLACE loc, name
  .BYTE loc
  FFPAD name, 15
.endmacro
lut_SumPlaces:
  SUMPLACE 234, "King"
  SUMPLACE 235, "Princess"
  SUMPLACE 236, "Bikke"
  SUMPLACE 238, "Astos"
  SUMPLACE 239, "Matoya"
  SUMPLACE 237, "Elf Prince"
  SUMPLACE 240, "Nerrick"
  SUMPLACE 241, "Smith"
  SUMPLACE 242, "Sarda"
  SUMPLACE 243, "Canoe Sage"
  SUMPLACE 245, "Fairy"
  SUMPLACE 244, "Cube Robot"
  SUMPLACE 246, "Lefein"
SUM_NPEOPLE = (* - lut_SumPlaces) / 16
  SUMPLACE 2, "Coneria Vault"
  SUMPLACE 27, "Marsh Cave"
  SUMPLACE 31, "Marsh Vault"
  SUMPLACE 60, "Earth Cave"
  SUMPLACE 105, "Volcano"
  SUMPLACE 113, "Ice Cave"
  SUMPLACE 130, "Ordeals"
  SUMPLACE 175, "Sea Shrine"
  SUMPLACE 219, "Sky Palace"
  SUMPLACE 69, "Titan's Trove"
  SUMPLACE 134, "Cardia"
  SUMPLACE 247, "Caravan"
SUM_NALL = (* - lut_SumPlaces) / 16
.assert SUM_NPEOPLE = SUM_LISTROWS && SUM_NALL - SUM_NPEOPLE <= SUM_LISTROWS, error, "the lists outgrow their rows"
.assert SUM_NAMEW + 2 <= 16, error, "a name runs into the next entry"
