; ---------------------------------------------------------------------------
;  optmenu.asm -- the settings screen.
;
;  Split out of optbank.asm, which had grown past the point where editing it by
;  text substitution was safe.  Both files assemble into BANK_OPT and are
;  linked together, so nothing about the bank layout changes.
;
;  optbank.asm owns the option block, the presets and the per-feature hooks;
;  this file owns the screen that edits them.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nesio.inc"

.export opt_settings
.import opt_commit_body

.import DrawBox, DrawCursor, ClearOAM, CallMusicPlay, UpdateJoy
.import WaitForVBlank_L

.segment "BANK_OPT"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  The settings screen
;;
;;  One scrolling list rather than columns or category pages: 33 rows against
;;  20 visible, so scrolling is light, labels get 22 characters, and there is
;;  no paging UI to build.  The bottom of the screen is a description pane.
;;
;;  Entered by pressing A on the title screen's mode row, which also switches
;;  the mode to Custom -- editing anything means you are no longer on a preset,
;;  and seeding Custom from whatever preset was showing is what makes "start
;;  from Deluxe and change two things" work.
;;
;;  Leaving re-enters EnterTitleScreen from the top rather than returning into
;;  its loop, because TitleScreen_Copyright calls IntroTitlePrepare, which
;;  reloads the menu CHR and clears the nametable -- so this screen is free to
;;  overwrite both.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

OPTLIST_TOP    = 1              ; first visible row (row 0 is cropped away)
OPTLIST_ROWS   = 20
OPTLIST_COL    = 2              ; the checkbox column
OPTDESC_Y      = 21             ; description box: rows 21-28
OPTDESC_H      = 8

CHKTILE_OFF    = $02            ; two tiles the settings screen loads over the
CHKTILE_ON     = $03            ;   battle backdrop, which it never draws
CHKTILE_PPU    = CHKTILE_OFF * 16

;  The box body tile.  DrawBoxRow_Mid calls it "inner box body"; it is solid
;  colour 2, which palette 3 makes blue, and it doubles as the space character
;  -- which is why blanking a row with it restores the background rather than
;  punching a hole in it.
NT_BOXBODY     = $FF

;  Scratch, in zero page -- it has to be, because the row pointer is used with
;  indirect indexed addressing and that mode only reaches the direct page.
;  $6D..$7B is the hole snesmap.inc describes: nothing in variables.inc names
;  it and no instruction in any bank addresses it.  altarorb has $6D; these
;  take seven of the fourteen bytes below it.
OPTMENU_SEL    = $6E            ; which list row the cursor is on
OPTMENU_TOP    = $6F            ; which list row is drawn at the top
OPTMENU_ROWPTR = $70            ; 2 bytes: into lut_OptRows
OPTMENU_ROWNUM = $72            ; which on-screen row is being drawn
OPTMENU_ADDR   = $73            ; 2 bytes: nametable address being built
OPTMENU_SCAN   = $75            ; row index while walking a section
OPTMENU_ALLSET = $76            ; was every checkbox in the section already on?

opt_settings:
    LDA #PRESET_CUSTOM
    STA OPT_PRESET
    JSR opt_commit_body

    PHB
    PHK
    PLB

    LDA #$00
    STA OPTMENU_SEL             ; row 0 is a heading; step onto the first
    STA OPTMENU_TOP             ;   real setting below
    JSR opt_menu_nextsel

    LDA #$00
    wPPUMASK                    ; screen off while it is built
    JSL hal_clearnt + HALFAR
    JSR opt_menu_fillbg
    JSR opt_menu_loadchr
    JSR opt_menu_drawall

    LDA #$08
    STA soft2000                ; sprites from the right pattern table
    LDA #$1E
    wPPUMASK                    ; ...and back on

    LDA #$00                    ; the A or Start that opened this screen is
    STA joy_a                   ;   still latched; without clearing it the
    STA joy_start               ;   first frame would act on it
    STA joy_b
    STA joy_prevdir

  @loop:
    ;  cur_bank is where CallMusicPlay swaps *back* to.  It has to name this
    ;  bank, not the one the title screen left in it: the music call switches
    ;  to BANK_MUSIC and returns through SwapPRG, so with a stale value the
    ;  program bank comes back pointing at bank $0E and the next instruction
    ;  at $8xxx is whatever that bank happens to hold.  Set every pass rather
    ;  than once, so anything else that touches it cannot strand us either.
    LDA #CHUNK_OPT
    STA cur_bank

    JSR ClearOAM
    LDA OPTMENU_SEL
    SEC
    SBC OPTMENU_TOP
    ASL A
    ASL A
    ASL A
    CLC
    ADC #(OPTLIST_TOP * 8) - 1
    STA spr_y
    LDA #(OPTLIST_COL * 8) - 16
    STA spr_x
    JSR DrawCursor

    JSR WaitForVBlank_L
    LDA #>oam
    wOAMDMA
    JSR CallMusicPlay
    JSR UpdateJoy

    LDA joy_b
    BNE @done
    LDA joy_a
    ORA joy_start
    BNE @act

    LDA joy
    AND #$0F
    CMP joy_prevdir
    BEQ @loop
    STA joy_prevdir
    BEQ @loop                   ; buttons released, not pressed

    CMP #DOWN
    BEQ @down
    CMP #UP
    BEQ @up
    JMP @loop

  @done:
    LDA #$00
    wPPUMASK
    PLB
    RTL

  @act:
    LDA #$00
    STA joy_a
    STA joy_start
    JSR opt_menu_toggle
    JMP @loop

  @down:
    LDX OPTMENU_SEL
  : INX
    CPX #OPTROW_COUNT
    BCS @loop                   ; nothing selectable below; stay put
    TXA
    JSR opt_row_selectable
    BEQ :-
    STX OPTMENU_SEL
    JSR opt_menu_scroll
    JMP @loop

  @up:
    LDX OPTMENU_SEL
  : CPX #$00
    BEQ @loop                   ; nothing selectable above; stay put
    DEX
    TXA
    JSR opt_row_selectable
    BEQ :-
    STX OPTMENU_SEL
    JSR opt_menu_scroll
    JMP @loop


;;  In: A = row index.  Z set if the cursor may not rest there.  Only the blank
;;  separators are excluded: a heading is selectable because pressing A on it
;;  toggles its whole section.
opt_row_selectable:
    PHX
    JSR opt_menu_ptrfor
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    PLX
    CMP #OPTROW_BLANK
    BEQ @no                     ; blanks are pure separators; headings are not
    LDA #$01                    ; selectable: Z clear
    RTS
  @no:
    LDA #$00                    ; not selectable: Z set
    RTS


;;  Step OPTMENU_SEL forward to the first row the cursor may rest on,
;;  including where it already is.
opt_menu_nextsel:
    LDX OPTMENU_SEL
  : CPX #OPTROW_COUNT
    BCS @out
    TXA
    JSR opt_row_selectable
    BNE @found
    INX
    JMP :-
  @found:
    STX OPTMENU_SEL
  @out:
    RTS


;;  Keep the selection inside the visible window, redrawing if it moved.
;;
;;  The window keeps OPTLIST_MARGIN rows of context above the cursor rather
;;  than pinning the top row to the selection.  Without that the first
;;  selectable row is row 2, so scrolling back up stops with the QUALITY OF
;;  LIFE heading and its blank line permanently off the top of the screen --
;;  the list appears to begin mid-section.  Two rows of margin is exactly the
;;  heading plus its separator, so scrolling to the top shows the top.
OPTLIST_MARGIN = 2

opt_menu_scroll:
    LDA OPTMENU_SEL             ; the highest row we are willing to have as TOP
    SEC
    SBC #OPTLIST_MARGIN
    BCS @havemin
    LDA #$00                    ; ...clamped at the start of the list
  @havemin:
    CMP OPTMENU_TOP
    BCS @bottom                 ; already showing enough above the cursor
    STA OPTMENU_TOP
    JMP opt_menu_drawall

  @bottom:
    LDA OPTMENU_SEL
    SEC
    SBC OPTMENU_TOP
    CMP #OPTLIST_ROWS
    BCC @out                    ; still inside the window
    LDA OPTMENU_SEL             ; scrolled off the bottom
    SEC
    SBC #OPTLIST_ROWS - 1
    STA OPTMENU_TOP
    JMP opt_menu_drawall
  @out:
    RTS


;;  Act on the row under the cursor: a checkbox toggles, a heading toggles its
;;  whole section, a value row does nothing yet.
opt_menu_toggle:
    JSR opt_menu_rowptr
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_HDR
    BEQ opt_section_toggle
    CMP #OPTROW_CHK
    BEQ @single
    RTS
  @single:
    INY
    LDA (OPTMENU_ROWPTR), Y     ; the flag's bit number
    JSR opt_flagbit             ; -> X = byte index, A = mask
    EOR OPT_FLAGS, X
    STA OPT_FLAGS, X
    JSR opt_commit_body
    JMP opt_menu_drawall


;;  Turn a whole section on or off.
;;
;;  Two passes over the rows between this heading and the next.  The first asks
;;  whether every checkbox is already set, because that is what decides the
;;  direction: a section that is entirely on turns off, and anything else turns
;;  fully on.  Toggling each box independently would make a half-set section
;;  invert rather than settle, which is not what "toggle the section" means.
;;
;;  The scan index lives in zero page rather than X because opt_menu_ptrfor
;;  needs X for its shift.
opt_section_toggle:
    LDA OPTMENU_SEL
    STA OPTMENU_SCAN
    LDA #$01
    STA OPTMENU_ALLSET

  @scan:
    INC OPTMENU_SCAN
    LDA OPTMENU_SCAN
    CMP #OPTROW_COUNT
    BCS @decide
    JSR opt_menu_ptrfor
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_HDR
    BEQ @decide                 ; the next section starts here
    CMP #OPTROW_CHK
    BNE @scan                   ; blanks and value rows are not part of this
    INY
    LDA (OPTMENU_ROWPTR), Y
    JSR opt_flagbit
    AND OPT_FLAGS, X
    BNE @scan                   ; still all-set so far
    LDA #$00
    STA OPTMENU_ALLSET
    JMP @scan

  @decide:
    LDA OPTMENU_SEL
    STA OPTMENU_SCAN
  @apply:
    INC OPTMENU_SCAN
    LDA OPTMENU_SCAN
    CMP #OPTROW_COUNT
    BCS @finish
    JSR opt_menu_ptrfor
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_HDR
    BEQ @finish
    CMP #OPTROW_CHK
    BNE @apply
    INY
    LDA (OPTMENU_ROWPTR), Y
    JSR opt_flagbit             ; -> X = byte index, A = mask
    LDY OPTMENU_ALLSET
    BNE @clear
    ORA OPT_FLAGS, X            ; not all were set, so set every one
    STA OPT_FLAGS, X
    JMP @apply
  @clear:
    EOR #$FF                    ; all were set, so clear every one
    AND OPT_FLAGS, X
    STA OPT_FLAGS, X
    JMP @apply

  @finish:
    JSR opt_commit_body
    JMP opt_menu_drawall


;;  In: A = bit number 0..31.  Out: X = byte index, A = mask.
opt_flagbit:
    PHA
    LSR A
    LSR A
    LSR A
    TAX                         ; byte index
    PLA
    AND #$07
    TAY
    LDA #$01
  : CPY #$00
    BEQ :+
    ASL A
    DEY
    JMP :-
  : RTS


;;  Point OPTMENU_ROWPTR at the selected row's record.
opt_menu_rowptr:
    LDA OPTMENU_SEL
    JMP opt_menu_ptrfor

;;  In: A = row index.  Sets OPTMENU_ROWPTR.
opt_menu_ptrfor:
    STA OPTMENU_ROWPTR
    LDA #$00
    STA OPTMENU_ROWPTR + 1
    LDX #$05                    ; * 32
  : ASL OPTMENU_ROWPTR
    ROL OPTMENU_ROWPTR + 1
    DEX
    BNE :-
    LDA OPTMENU_ROWPTR
    CLC
    ADC #<lut_OptRows
    STA OPTMENU_ROWPTR
    LDA OPTMENU_ROWPTR + 1
    ADC #>lut_OptRows
    STA OPTMENU_ROWPTR + 1
    RTS


;


;;  The two checkbox tiles, straight into the BG pattern table.
opt_menu_loadchr:
    bPPUSTATUS
    LDA #>CHKTILE_PPU
    wPPUADDR
    LDA #<CHKTILE_PPU
    wPPUADDR
    LDX #$00
  : LDA lut_CheckboxCHR, X
    wPPUDATA
    INX
    CPX #32
    BCC :-
    RTS


;;  The description box.  Empty for now; the text comes next.
opt_menu_drawdesc:
    LDA #$00
    STA box_x
    LDA #OPTDESC_Y
    STA box_y
    LDA #OPTDESC_H
    STA box_ht
    LDA #32
    STA box_wd
    LDA #$00
    STA menustall
    JMP DrawBox


;;  Redraw the whole visible window.
opt_menu_drawall:
    LDA #$00
    STA OPTMENU_ROWNUM
  @row:
    LDA OPTMENU_ROWNUM
    CLC
    ADC OPTMENU_TOP
    CMP #OPTROW_COUNT
    BCS @blank
    JSR opt_menu_drawrow
    JMP @next
  @blank:
    JSR opt_menu_blankrow
  @next:
    INC OPTMENU_ROWNUM
    LDA OPTMENU_ROWNUM
    CMP #OPTLIST_ROWS
    BCC @row
    JMP opt_menu_drawdesc


;;  Point the PPU at the start of on-screen row OPTMENU_ROWNUM.
opt_menu_ppuaddr:
    LDA OPTMENU_ROWNUM
    CLC
    ADC #OPTLIST_TOP
    STA OPTMENU_ADDR
    LDA #$00
    STA OPTMENU_ADDR + 1
    LDX #$05                    ; * 32, the nametable row stride
  : ASL OPTMENU_ADDR
    ROL OPTMENU_ADDR + 1
    DEX
    BNE :-
    LDA OPTMENU_ADDR
    CLC
    ADC #OPTLIST_COL
    STA OPTMENU_ADDR
    LDA OPTMENU_ADDR + 1
    ADC #>$2000                 ; carry from the low byte rides along
    STA OPTMENU_ADDR + 1
    bPPUSTATUS
    LDA OPTMENU_ADDR + 1
    wPPUADDR
    LDA OPTMENU_ADDR
    wPPUADDR
    RTS


;;  In: A = the list index to draw, OPTMENU_ROWNUM = where.
opt_menu_drawrow:
    JSR opt_menu_ptrfor
    JSR opt_menu_ppuaddr

    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_CHK
    BNE @nobox
    INY
    LDA (OPTMENU_ROWPTR), Y     ; the flag's bit number
    JSR opt_flagbit
    AND OPT_FLAGS, X
    BEQ @off
    LDA #CHKTILE_ON
    JMP @emit
  @off:
    LDA #CHKTILE_OFF
    JMP @emit
  @nobox:
    LDA #$FF                    ; headers and value rows have no checkbox
  @emit:
    wPPUDATA
    LDA #$FF
    wPPUDATA                    ; the gap column

    LDY #OPTROW_LABEL
  @label:
    LDA (OPTMENU_ROWPTR), Y
    wPPUDATA
    INY
    CPY #OPTROW_LABEL + OPTROW_LABELW
    BCC @label
    RTS


;;  Wipe an on-screen row that has no list entry behind it.
opt_menu_blankrow:
    JSR opt_menu_ppuaddr
    LDX #OPTROW_LABELW + 2
    LDA #$FF
  : wPPUDATA
    DEX
    BNE :-
    RTS


;;  Lay the blue background across the whole screen.
;;
;;  hal_clearnt leaves the tilemap full of tile $00 -- which after the menu CHR
;;  load is part of the battle backdrop -- and sets every attribute byte to
;;  $FF, so all four quadrants of every block already select palette 3.  The
;;  colour is therefore only a question of which tile is underneath, and the
;;  box body tile is solid blue.  Filling all thirty rows with it puts the same
;;  blue behind the list that the description box has inside it, edge to edge.
opt_menu_fillbg:
    LDA #$00
    STA OPTMENU_ROWNUM
  @row:
    JSR opt_menu_rowppu
    LDA #NT_BOXBODY
    LDX #32                     ; a whole row, which keeps hal_ntfill on its
    JSL hal_ntfill + HALFAR     ;   fast path: the run never leaves the row
    INC OPTMENU_ROWNUM
    LDA OPTMENU_ROWNUM
    CMP #30                     ; the nametable is 30 rows; the crop hides two
    BCC @row
    RTS


;;  Point the PPU at column 0 of on-screen row OPTMENU_ROWNUM.
opt_menu_rowppu:
    LDA OPTMENU_ROWNUM
    STA OPTMENU_ADDR
    LDA #$00
    STA OPTMENU_ADDR + 1
    LDX #$05                    ; * 32, the nametable row stride
  : ASL OPTMENU_ADDR
    ROL OPTMENU_ADDR + 1
    DEX
    BNE :-
    LDA OPTMENU_ADDR + 1
    CLC
    ADC #>$2000
    STA OPTMENU_ADDR + 1
    bPPUSTATUS
    LDA OPTMENU_ADDR + 1
    wPPUADDR
    LDA OPTMENU_ADDR
    wPPUADDR
    RTS


;  Generated: the settings list.  byte 0 = kind, byte 1 = flag bit or
;  scalar index, bytes 2..23 = the label.  Section headings stay in capitals;
;  the settings themselves are sentence case, which needs the lowercase run
;  at $A4..$BD.  Blank rows exist only to separate the sections, and the
;  cursor skips them along with the headings.
OPTROW_HDR   = 0
OPTROW_CHK   = 1
OPTROW_VAL   = 2
OPTROW_BLANK = 3
OPTROW_STRIDE = 32
OPTROW_LABEL  = 2
OPTROW_LABELW = 22
OPTROW_COUNT  = 38

lut_OptRows:
  .BYTE $00, $00   ; QUALITY OF LIFE
  .BYTE $9A, $9E, $8A, $95, $92, $9D, $A2, $FF, $98, $8F
  .BYTE $FF, $95, $92, $8F, $8E, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $03, $00   ; (blank)
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $00   ; Speed hacks
  .BYTE $9C, $B3, $A8, $A8, $A7, $FF, $AB, $A4, $A6, $AE
  .BYTE $B6, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $01   ; Faster walking
  .BYTE $8F, $A4, $B6, $B7, $A8, $B5, $FF, $BA, $A4, $AF
  .BYTE $AE, $AC, $B1, $AA, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $02   ; Faster ship
  .BYTE $8F, $A4, $B6, $B7, $A8, $B5, $FF, $B6, $AB, $AC
  .BYTE $B3, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $03   ; No party shuffle
  .BYTE $97, $B2, $FF, $B3, $A4, $B5, $B7, $BC, $FF, $B6
  .BYTE $AB, $B8, $A9, $A9, $AF, $A8, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $04   ; Identify treasures
  .BYTE $92, $A7, $A8, $B1, $B7, $AC, $A9, $BC, $FF, $B7
  .BYTE $B5, $A8, $A4, $B6, $B8, $B5, $A8, $B6, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $05   ; Chests appear opened
  .BYTE $8C, $AB, $A8, $B6, $B7, $B6, $FF, $A4, $B3, $B3
  .BYTE $A8, $A4, $B5, $FF, $B2, $B3, $A8, $B1, $A8, $A7
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $06   ; Buy quantity
  .BYTE $8B, $B8, $BC, $FF, $B4, $B8, $A4, $B1, $B7, $AC
  .BYTE $B7, $BC, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $07   ; Run becomes Wait
  .BYTE $9B, $B8, $B1, $FF, $A5, $A8, $A6, $B2, $B0, $A8
  .BYTE $B6, $FF, $A0, $A4, $AC, $B7, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $08   ; Magic menu wraparound
  .BYTE $96, $A4, $AA, $AC, $A6, $FF, $B0, $A8, $B1, $B8
  .BYTE $FF, $BA, $B5, $A4, $B3, $A4, $B5, $B2, $B8, $B1
  .BYTE $A7, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $09   ; Auto retargeting
  .BYTE $8A, $B8, $B7, $B2, $FF, $B5, $A8, $B7, $A4, $B5
  .BYTE $AA, $A8, $B7, $AC, $B1, $AA, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $0A   ; Autosort inventory
  .BYTE $8A, $B8, $B7, $B2, $B6, $B2, $B5, $B7, $FF, $AC
  .BYTE $B1, $B9, $A8, $B1, $B7, $B2, $B5, $BC, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $0B   ; Repeated potion use
  .BYTE $9B, $A8, $B3, $A8, $A4, $B7, $A8, $A7, $FF, $B3
  .BYTE $B2, $B7, $AC, $B2, $B1, $FF, $B8, $B6, $A8, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $0C   ; Shop information
  .BYTE $9C, $AB, $B2, $B3, $FF, $AC, $B1, $A9, $B2, $B5
  .BYTE $B0, $A4, $B7, $AC, $B2, $B1, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $0D   ; Chest information
  .BYTE $8C, $AB, $A8, $B6, $B7, $FF, $AC, $B1, $A9, $B2
  .BYTE $B5, $B0, $A4, $B7, $AC, $B2, $B1, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $0E   ; NPC guillotine
  .BYTE $97, $99, $8C, $FF, $AA, $B8, $AC, $AF, $AF, $B2
  .BYTE $B7, $AC, $B1, $A8, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $03, $00   ; (blank)
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $00, $00   ; BUGFIXES
  .BYTE $8B, $9E, $90, $8F, $92, $A1, $8E, $9C, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $03, $00   ; (blank)
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $0F   ; House MP restoration
  .BYTE $91, $B2, $B8, $B6, $A8, $FF, $96, $99, $FF, $B5
  .BYTE $A8, $B6, $B7, $B2, $B5, $A4, $B7, $AC, $B2, $B1
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $10   ; Weapon stats
  .BYTE $A0, $A8, $A4, $B3, $B2, $B1, $FF, $B6, $B7, $A4
  .BYTE $B7, $B6, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $11   ; Spell fixes
  .BYTE $9C, $B3, $A8, $AF, $AF, $FF, $A9, $AC, $BB, $A8
  .BYTE $B6, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $12   ; Enemy status attacks
  .BYTE $8E, $B1, $A8, $B0, $BC, $FF, $B6, $B7, $A4, $B7
  .BYTE $B8, $B6, $FF, $A4, $B7, $B7, $A4, $A6, $AE, $B6
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $03, $00   ; (blank)
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $00, $00   ; VARIATIONS
  .BYTE $9F, $8A, $9B, $92, $8A, $9D, $92, $98, $97, $9C
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $03, $00   ; (blank)
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $02, $00   ; Gold and XP
  .BYTE $90, $B2, $AF, $A7, $FF, $A4, $B1, $A7, $FF, $A1
  .BYTE $99, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $02, $01   ; Encounter rate
  .BYTE $8E, $B1, $A6, $B2, $B8, $B1, $B7, $A8, $B5, $FF
  .BYTE $B5, $A4, $B7, $A8, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $02, $02   ; Enemy stats
  .BYTE $8E, $B1, $A8, $B0, $BC, $FF, $B6, $B7, $A4, $B7
  .BYTE $B6, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $02, $03   ; Boss stats
  .BYTE $8B, $B2, $B6, $B6, $FF, $B6, $B7, $A4, $B7, $B6
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $13   ; Better Thief and Ninja
  .BYTE $8B, $A8, $B7, $B7, $A8, $B5, $FF, $9D, $AB, $AC
  .BYTE $A8, $A9, $FF, $A4, $B1, $A7, $FF, $97, $AC, $B1
  .BYTE $AD, $A4, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $14   ; Double weapon crit
  .BYTE $8D, $B2, $B8, $A5, $AF, $A8, $FF, $BA, $A8, $A4
  .BYTE $B3, $B2, $B1, $FF, $A6, $B5, $AC, $B7, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $15   ; Elemental bonus
  .BYTE $8E, $AF, $A8, $B0, $A8, $B1, $B7, $A4, $AF, $FF
  .BYTE $A5, $B2, $B1, $B8, $B6, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $16   ; Improved Cure spells
  .BYTE $92, $B0, $B3, $B5, $B2, $B9, $A8, $A7, $FF, $8C
  .BYTE $B8, $B5, $A8, $FF, $B6, $B3, $A8, $AF, $AF, $B6
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $17   ; Improved Fire spells
  .BYTE $92, $B0, $B3, $B5, $B2, $B9, $A8, $A7, $FF, $8F
  .BYTE $AC, $B5, $A8, $FF, $B6, $B3, $A8, $AF, $AF, $B6
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $18   ; Cast Life in battle
  .BYTE $8C, $A4, $B6, $B7, $FF, $95, $AC, $A9, $A8, $FF
  .BYTE $AC, $B1, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $19   ; LOK2 accuracy
  .BYTE $95, $98, $94, $82, $FF, $A4, $A6, $A6, $B8, $B5
  .BYTE $A4, $A6, $BC, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

;  The two checkbox tiles, in NES 2bpp -- eight bytes of plane 0 then eight
;  of plane 1, which is what the HAL's $2007 path expects.  Palette 3 is
;  already black / grey / blue / white (LoadBorderPalette_Blue), so neither
;  needs any palette work.
;
;  Unchecked is hollow: the interior is the same blue as the background, so
;  the tile reads as an empty grey ring.  Checked fills it white.  Filled
;  versus empty carries at this resolution in a way that two filled colours
;  did not -- there is no room for a tick inside a six-pixel interior.
lut_CheckboxCHR:
  ; unchecked -- hollow, background shows through
  .BYTE $00, $7E, $42, $42, $42, $42, $7E, $00
  .BYTE $FF, $81, $BD, $BD, $BD, $BD, $81, $FF
  ; checked -- filled white
  .BYTE $00, $7E, $7E, $7E, $7E, $7E, $7E, $00
  .BYTE $FF, $81, $BD, $BD, $BD, $BD, $81, $FF
