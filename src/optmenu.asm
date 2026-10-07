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
;  Descriptions written as text rather than hand-encoded bytes.
.include "fftext.inc"
.include "Constants.inc"
.include "variables.inc"
.include "nesio.inc"
;  SET0E, the way into bank $0E -- where the menu sound effects live.
.include "optcall.inc"

.export opt_settings
;  Reached by tools/test_options.py.
.export opt_sfx_move, opt_sfx_sel, opt_value_adjust

;  Exported for tools/test_options.py, which checks every label against the
;  width the menu actually draws.  Nothing in the game reaches it by name.
.export lut_OptRows

;  Likewise: the dial value tables, so the harness can confirm every byte they
;  draw is a digit, a space, CHR_PLUS or CHR_PCT.  A sign written as a literal
;  here goes on drawing the old tile after the glyph moves, which is how the
;  elemental dial came to read "S50".
.export lut_ValTabLo, lut_ValTabHi, lut_ValCount, lut_ValOff
.import opt_commit_body

.import DrawBox, DrawCursor, ClearOAM, CallMusicPlay, UpdateJoy
.import WaitForVBlank_L
.import OptCallFar, PlaySFX_MenuSel, PlaySFX_MenuMove

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
OPTMENU_VALPTR = $77            ; 2 bytes: into a value-readout table
OPTMENU_DESC   = $7A            ; 2 bytes: into the description text
OPTMENU_DLINES = $79            ; ...and how many of its lines are left

;  This screen does its own edge detection rather than using joy_a, joy_start
;  and joy_ignore.  Those are a counter per button plus a shared mask, updated
;  by ProcessJoyButtons and owned across screen transitions by whoever ran
;  last, and a held A was reaching this loop as a fresh press every frame.
;  Keeping the previous pad state here makes "newly pressed" a property of two
;  bytes this screen owns outright, and makes waiting for release trivial.
;  They are flags, not pointers, so they need no direct-page addressing --
;  which is just as well, as zero page $6E..$7B is now full.
OPTMENU_PREV   = OPTBLOCK + $1E ; the pad as it read last frame
OPTMENU_EDGE   = OPTBLOCK + $1F ; buttons that went down this frame
OPTMENU_WAS    = OPTBLOCK + $1D ; the row a left/right page started on
OPTMENU_LEFT   = OPTBLOCK + $1C ; rows still to draw before the next breath
OPTMENU_ANY    = OPTBLOCK + $1B ; did a section toggle find a checkbox at all?

;  joy's bit order, which ProcessJoyButtons documents by masking for it.
PAD_RIGHT = $01
PAD_LEFT  = $02
PAD_DOWN  = $04
PAD_UP    = $08
PAD_START = $10
PAD_B     = $40
PAD_A     = $80

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
    JSR opt_menu_drawdesc       ; the box frame, once: it never changes
    JSR opt_menu_drawall

    LDA #$08
    STA soft2000                ; sprites from the right pattern table

    ;  Put the hand where it belongs before the screen comes on.  OAM still
    ;  holds the title screen's cursor, at the Y of whichever row was chosen
    ;  there, and nothing between here and the first pass of the loop replaces
    ;  it: opt_waitrelease flushes for as many frames as the button is held,
    ;  every one of them uploading that stale sprite.  So the hand appeared at
    ;  the title screen's position -- for a tap, about a frame -- and only
    ;  jumped to the list once the loop began.
    ;
    ;  Two breaths, because both halves of the path are deferred and in this
    ;  order.  soft2000 is a plain RAM write that the vblank service copies
    ;  into h_ppuctrl, and hal_oamdma reads h_ppuctrl to choose the sprite
    ;  pattern table; then the DMA only fills OAMSHADOW, which the *next*
    ;  flush uploads.  With the screen still off the two frames cost nothing,
    ;  and breathing rather than plain waiting keeps the music driver fed the
    ;  way the rest of the build path does.
    JSR opt_menu_breathe        ; soft2000 -> h_ppuctrl
    JSR opt_menu_cursor
    LDA #>oam
    wOAMDMA                     ; oam -> OAMSHADOW
    JSR opt_menu_breathe        ; ...and OAMSHADOW -> the hardware

    LDA #$1E
    wPPUMASK                    ; ...and back on

    ;  The press that opened this screen belongs to the title screen's loop,
    ;  which does not chirp for it -- it has no way to know whether the mode
    ;  row leads anywhere.  So answer it here, as the list appears.
    JSR opt_sfx_sel

    JSR opt_waitrelease         ; nothing the title screen was holding carries in

  @loop:
    JSR opt_menu_cursor

    JSR WaitForVBlank_L
    LDA #>oam
    wOAMDMA

    ;  cur_bank is where CallMusicPlay swaps *back* to.  It has to name this
    ;  bank, not the one the title screen left in it: the music call switches
    ;  to BANK_MUSIC and returns through SwapPRG, so with a stale value the
    ;  program bank comes back elsewhere and the next instruction at $8xxx is
    ;  whatever that bank happens to hold.  Kept next to the call it guards,
    ;  and set every pass, so nothing else touching it can strand us.
    LDA #CHUNK_OPT
    STA cur_bank
    JSR CallMusicPlay

    JSR UpdateJoy

    ;  Edge detection: down now and not down last frame.
    LDA joy
    EOR OPTMENU_PREV
    AND joy
    STA OPTMENU_EDGE
    LDA joy
    STA OPTMENU_PREV

    LDA OPTMENU_EDGE
    AND #PAD_B | PAD_START
    BNE @done
    LDA OPTMENU_EDGE
    AND #PAD_A
    BNE @act
    LDA OPTMENU_EDGE
    AND #PAD_DOWN
    BNE @down
    LDA OPTMENU_EDGE
    AND #PAD_UP
    BNE @up
    LDA OPTMENU_EDGE
    AND #PAD_LEFT | PAD_RIGHT
    BEQ @loop

    LDA OPTMENU_EDGE            ; left or right: step a value row
    AND #PAD_RIGHT
    BNE @right
    LDA #LEFT
    BNE @sideways               ; always
  @right:
    LDA #RIGHT
  @sideways:
    JSR opt_sideways
    JMP @loop

  @done:
    ;  Start leaves rather than toggling.  The title screen treats A and Start
    ;  as the same button, so arriving here Start already means "yes" -- but on
    ;  a list of switches the useful sense of "yes, done" is to leave, and a
    ;  second way to flip the row under the cursor is no use at all.
    ;
    ;  Nothing has to put the title cursor back on Continue: the way out is
    ;  JMP EnterTitleScreen, and IntroTitlePrepare along that path already
    ;  stores zero to cursor along with the button catchers.
    ;
    ;  The game plays the selection effect for B as well as A -- backing out
    ;  of a menu is a choice.  LineupMenu_UpdateJoy ORs the two catchers
    ;  together and plays the one sound for either.
    JSR opt_sfx_sel
    JSR opt_waitrelease         ; ...and nothing carries back out either
    LDA #$00
    wPPUMASK
    PLB
    RTL

  @act:
    JSR opt_menu_toggle
    JMP @loop

  ;  Named labels, not anonymous ones.  An earlier version used ":" here and a
  ;  later edit inserted another one between the loop top and the branch back,
  ;  which silently retargeted "BEQ :-" to the wrong place -- the index stopped
  ;  advancing and the first press onto a blank row hung the menu.
  @down:
    LDX OPTMENU_SEL
  @dnext:
    INX
    CPX #OPTROW_COUNT
    BCC @dtest
    JMP @loop                   ; nothing selectable below; stay put
  @dtest:
    TXA
    JSR opt_row_selectable
    BEQ @dnext
    STX OPTMENU_SEL
    JSR opt_sfx_move
    JSR opt_menu_scroll
    BCS @dpainted               ; the repaint put the description back
    JSR opt_menu_desc
  @dpainted:
    JMP @loop

  @up:
    LDX OPTMENU_SEL
  @unext:
    CPX #$00
    BNE @udec
    JMP @loop                   ; nothing selectable above; stay put
  @udec:
    DEX
    TXA
    JSR opt_row_selectable
    BEQ @unext
    STX OPTMENU_SEL
    JSR opt_sfx_move
    JSR opt_menu_scroll
    BCS @upainted
    JSR opt_menu_desc
  @upainted:
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


;;  Seek from row X to the first the cursor may rest on, X included.  Sets
;;  OPTMENU_SEL and returns C set if one was found, C clear if the scan ran
;;  off the end without finding one.
opt_seek_fwd:
  @loop:
    CPX #OPTROW_COUNT
    BCS @none
    TXA
    JSR opt_row_selectable
    BNE @found
    INX
    JMP @loop
  @found:
    STX OPTMENU_SEL
    SEC
    RTS
  @none:
    CLC
    RTS

;;  The same, walking backwards.
opt_seek_back:
  @loop:
    TXA
    JSR opt_row_selectable
    BNE @found
    CPX #$00
    BEQ @none
    DEX
    JMP @loop
  @found:
    STX OPTMENU_SEL
    SEC
    RTS
  @none:
    CLC
    RTS

;;  Step OPTMENU_SEL forward to the first row the cursor may rest on,
;;  including where it already is.
opt_menu_nextsel:
    LDX OPTMENU_SEL
    JMP opt_seek_fwd


;;  Keep the selection inside the visible window, redrawing if it moved.
;;
;;  The window keeps OPTLIST_MARGIN rows of context above the cursor rather
;;  than pinning the top row to the selection.  Without that the first
;;  selectable row is row 2, so scrolling back up stops with the QUALITY OF
;;  LIFE heading and its blank line permanently off the top of the screen --
;;  the list appears to begin mid-section.  Two rows of margin is exactly the
;;  heading plus its separator, so scrolling to the top shows the top.
OPTLIST_MARGIN = 2
OPTLIST_PAGE   = OPTLIST_ROWS / 2   ; how far left and right jump

;;  Out: C set if the window moved and the whole screen was repainted, which
;;  includes the description -- so a caller that would otherwise put the
;;  description back must not.  It was doing exactly that: every scroll drew
;;  the pane twice, once at the end of the repaint and once on the way back,
;;  and the second one was five more blits on the frame that could least
;;  afford them.
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
    JSR opt_menu_drawall
    SEC
    RTS

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
    JSR opt_menu_drawall
    SEC
    RTS
  @out:
    CLC
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
    JSR opt_sfx_sel
    JSR opt_commit_body
    JMP opt_menu_drawsel


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
    LDA #$00
    STA OPTMENU_ANY             ; SCALE is four dials and no boxes at all

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
    INC OPTMENU_ANY
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
    LDA OPTMENU_ANY
    BEQ @nothing                ; a section of value rows has nothing to toggle
    JSR opt_sfx_sel
    JSR opt_commit_body
    JMP opt_menu_drawall
  @nothing:
    RTS


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


;;  Write the description for the selected row into the pane.  Five fixed
;;  blits: the text is wrapped at build time, so there is nothing to measure
;;  here and nothing to decide.
DESC_COL = 2
DESC_ROW = OPTDESC_Y + 2

;;  A description record is a line count and then that many lines, rather than
;;  five lines padded with spaces.  Most of them are two or three, and the
;;  padding came to 2.8KB in a bank that had none left -- this screen's own
;;  section would not fit until it went.  opt_menu_desc blanks the rest of the
;;  pane itself, which is a fill rather than a blit and so slightly cheaper
;;  than writing the spaces was.
.macro FFLINES n
    .byte n
.endmacro


opt_menu_desc:
    LDX OPTMENU_SEL
    LDA lut_DescLo, X
    STA OPTMENU_DESC
    LDA lut_DescHi, X
    STA OPTMENU_DESC + 1

    LDY #$00
    LDA (OPTMENU_DESC), Y       ; how many lines this one actually has
    STA OPTMENU_DLINES
    INC OPTMENU_DESC            ; ...and the text begins after it
    BNE @haveptr
    INC OPTMENU_DESC + 1
  @haveptr:

    LDA #DESC_ROW
    STA OPTMENU_ROWNUM
  @line:
    JSR opt_menu_descppu
    LDA OPTMENU_DLINES
    BEQ @blank                  ; past the end of the text: clear the row
    DEC OPTMENU_DLINES

    ;  Two cursors that count together: Y reads the wrapped line, X stages it.
    ;  They cannot be the same register -- the source needs (dp),y and the
    ;  staging buffer is long-addressed, and the 65816 has "long,x" but no
    ;  "long,y".
    LDX #$00
    LDY #$00
  @char:
    LDA (OPTMENU_DESC), Y
    STA f:NTSTAGE, X
    INX
    INY
    CPY #DESC_W
    BCC @char
    JSL hal_ntblit + HALFAR     ; X is already the count

    LDA OPTMENU_DESC            ; on to the next wrapped line
    CLC
    ADC #DESC_W
    STA OPTMENU_DESC
    LDA OPTMENU_DESC + 1
    ADC #$00
    STA OPTMENU_DESC + 1
    BRA @next

  @blank:
    LDA #NT_BOXBODY
    LDX #DESC_W
    JSL hal_ntfill + HALFAR

  @next:
    INC OPTMENU_ROWNUM
    LDA OPTMENU_ROWNUM
    CMP #DESC_ROW + DESC_LINES
    BCC @line
    RTS


;;  PPU address for the description line at OPTMENU_ROWNUM, inset by DESC_COL.
opt_menu_descppu:
    LDA OPTMENU_ROWNUM
    STA OPTMENU_ADDR
    LDA #$00
    STA OPTMENU_ADDR + 1
    LDX #$05                    ; * 32, the nametable row stride
  @sh:
    ASL OPTMENU_ADDR
    ROL OPTMENU_ADDR + 1
    DEX
    BNE @sh
    LDA OPTMENU_ADDR
    CLC
    ADC #DESC_COL
    STA OPTMENU_ADDR
    LDA OPTMENU_ADDR + 1
    ADC #>$2000
    STA OPTMENU_ADDR + 1
    bPPUSTATUS
    LDA OPTMENU_ADDR + 1
    wPPUADDR
    LDA OPTMENU_ADDR
    wPPUADDR
    RTS


;;  The description box.
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
    STA menustall               ; no stall, so DrawBox will not reach the music
    LDA #CHUNK_OPT              ;   call -- but name this bank anyway, so the
    STA cur_bank                ;   safety does not rest on a flag elsewhere
    JMP DrawBox


;;  Redraw the whole visible window.
;;  How many rows one frame's worth of repaint is.
;;
;;  Set by what a *vblank* holds rather than by what a frame's drawing holds,
;;  because that is the tighter of the two: a dirty row costs the flush about
;;  four scanlines -- two nt_piece transfers, each with more setup than
;;  transfer -- against the thirty-seven a vblank has.  Ten rows ran eleven
;;  lines into the picture; seven fitted, but with three lines to spare on the
;;  frames where the sprite flush also had work, which is not margin.
;;
;;  Five, and not six, because twenty divides by it: six gives 6-6-6-2 and five
;;  gives 5-5-5-5, which is the same number of frames with a smaller worst
;;  case.  The description is a fifth piece either way.
OPTLIST_CHUNK  = 5

opt_menu_drawall:
    LDA #$00
    STA OPTMENU_ROWNUM
    LDA #OPTLIST_CHUNK
    STA OPTMENU_LEFT
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
    DEC OPTMENU_LEFT
    BNE @more                   ; ...a chunk's worth, so give the frame back
    JSR opt_menu_breathe
    LDA #OPTLIST_CHUNK
    STA OPTMENU_LEFT
  @more:
    LDA OPTMENU_ROWNUM
    CMP #OPTLIST_ROWS
    BCC @row
    ;  ...and once more before the description, which is five rows of its own
    ;  -- unless the last row completed a chunk and has just been given one,
    ;  which would otherwise spend a whole frame drawing nothing.
    LDA OPTMENU_LEFT
    CMP #OPTLIST_CHUNK
    BEQ @justbreathed
    JSR opt_menu_breathe
  @justbreathed:
    ;  The description text, but not the box around it.  The box is rows 21-28
    ;  and the list is rows 1-20, so a repaint of the list cannot damage it --
    ;  and redrawing it anyway was the single most expensive thing a scroll
    ;  did: eight more rows through DrawBox, and eight more rows for the flush
    ;  to carry.  It is drawn once, on the way in.
    JMP opt_menu_desc


;;  Repaint just the row the cursor is on.
;;
;;  A checkbox toggle changes one tile and a value row changes four, and both
;;  used to repaint the whole visible window -- twenty rows through the blit
;;  path for a single character.  Nothing else on screen depends on a flag's
;;  value, not even the description, so one row is the whole update.
opt_menu_drawsel:
    LDA OPTMENU_SEL
    SEC
    SBC OPTMENU_TOP
    STA OPTMENU_ROWNUM
    LDA OPTMENU_SEL
    JMP opt_menu_drawrow


;;  One frame, in the middle of a repaint.
;;
;;  Twenty rows is more drawing than a frame holds, and the loop above is the
;;  one place in this screen that does not come back to the main loop while it
;;  works.  Without this the music driver goes uncalled for a frame and a
;;  quarter -- an audible stall, and a chirp that starts and then sits on one
;;  pitch -- and the whole repaint arrives as one flush, which is far too much
;;  for a vblank and paints a black band a third of the screen deep.
;;
;;  Split in half it is two ordinary frames: each half is comfortably inside a
;;  frame's worth of drawing, each flush is comfortably inside a vblank, and
;;  the music is called as often as it always was.  What it costs is that the
;;  list arrives in two pieces one frame apart, which at a single keypress is
;;  not something the eye has time to find.
;;
;;  DrawBox has the same shape for the same reason and calls it a stall.
opt_menu_breathe:
    LDA #CHUNK_OPT              ; where CallMusicPlay has to come back to
    STA cur_bank
    JSR WaitForVBlank_L         ; ...which is also where the flush happens
    JMP CallMusicPlay


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


;;  Place the hand beside the selected row, in the OAM buffer.
;;
;;  Split out of the loop so the entry path can use it too: the cursor has to
;;  be in OAM before the screen is revealed, not a frame or more after.
opt_menu_cursor:
    JSR ClearOAM
    LDA OPTMENU_SEL
    SEC
    SBC OPTMENU_TOP             ; rows down from the top of the visible list
    ASL A
    ASL A
    ASL A                       ; ...times eight scanlines
    CLC
    ADC #(OPTLIST_TOP * 8) - 1
    STA spr_y
    LDA #(OPTLIST_COL * 8) - 16
    STA spr_x
    JMP DrawCursor


;;  The two menu chirps.
;;
;;  They are the game's own, in bank $0E with the rest of the menu sound, so
;;  they are reached through the trampoline rather than with a JSR.  Calling
;;  them rather than writing the six APU stores out again is the same argument
;;  the shop description box makes about weapon fields: one rule, one place.
;;
;;  Transparent, like the nesio thunks.  A chirp is feedback about something
;;  that has already been decided, so dropping one into an existing path
;;  should not make that path rearrange itself around it.  X and Y pass
;;  through OptCallFar untouched; A and the flags are what need saving.
opt_sfx_move:
    PHP
    PHA
    CALL0E PlaySFX_MenuMove
    PLA
    PLP
    RTS

opt_sfx_sel:
    PHP
    PHA
    CALL0E PlaySFX_MenuSel
    PLA
    PLP
    RTS


;;  Hold here until the player is not touching anything, then start from a
;;  clean slate.
;;
;;  This is what a screen transition needs, and the reason is structural rather
;;  than incidental: the button that got us here is still down, and the catchers
;;  are edge-triggered against joy_ignore, which is state the previous screen
;;  owned.  Clearing the catchers is not enough, because the release that comes
;;  a frame or two later is itself a transition.  Waiting for the pad to read
;;  zero makes the new screen's first press unambiguously a new press.
;;
;;  Both ends of the transition want it: on the way in so the A that opened the
;;  screen is not read as a toggle, and on the way out so the B that closed it
;;  does not reach the title screen.
opt_waitrelease:
    LDA #CHUNK_OPT
    STA cur_bank                ; CallMusicPlay returns through this
  @wait:
    JSR WaitForVBlank_L
    JSR CallMusicPlay           ; the music should not stop while we wait
    JSR UpdateJoy
    LDA joy
    BNE @wait
    STA OPTMENU_PREV            ; A is zero here, so nothing reads as newly
    STA OPTMENU_EDGE            ;   pressed on the frame after this
    ;  The game's own catchers belong to whichever screen runs next, and with
    ;  nothing held there is no transition pending for them to lose.
    STA joy_a
    STA joy_b
    STA joy_start
    STA joy_select
    STA joy_prevdir
    STA joy_ignore
    RTS


;;  In: A = the list index to draw, OPTMENU_ROWNUM = where.
;;
;;  X is the staging cursor from @emit onwards and Y indexes whatever is being
;;  copied from, so every byte is a store and an increment rather than a call.
;;  The checkbox is worked out first, because opt_flagbit wants X for its own
;;  shift; opt_value_ptr wants it too, and is bracketed.
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
    BRA @emit
  @off:
    LDA #CHKTILE_OFF
    BRA @emit
  @nobox:
    LDA #$FF                    ; headers and value rows have no checkbox
  @emit:
    LDX #$00
    STA f:NTSTAGE, X
    INX
    LDA #$FF
    STA f:NTSTAGE, X            ; the gap column
    INX

    LDY #OPTROW_LABEL
  @label:
    LDA (OPTMENU_ROWPTR), Y
    STA f:NTSTAGE, X
    INX
    INY
    CPY #OPTROW_LABEL + OPTROW_LABELW
    BCC @label

    ;  The readout field closes every row, blank on the ones that have no
    ;  value.  Writing it unconditionally is what stops a value left behind by
    ;  a scrolled-away row showing up beside an unrelated label.
    LDA #$FF
    STA f:NTSTAGE, X            ; the gap column
    INX
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_VAL
    BEQ @value
    LDY #VALFIELD
  @pad:
    LDA #$FF
    STA f:NTSTAGE, X
    INX
    DEY
    BNE @pad
    BRA @blit
  @value:
    PHX                         ; opt_value_ptr shifts through X
    JSR opt_value_ptr           ; -> OPTMENU_VALPTR at this row's readout
    PLX
    LDY #$00
  @vloop:
    LDA (OPTMENU_VALPTR), Y
    STA f:NTSTAGE, X
    INX
    INY
    CPY #VALFIELD
    BCC @vloop
  @blit:
    JSL hal_ntblit + HALFAR     ; X is already the count
    RTS


;;  Point OPTMENU_VALPTR at the readout for the value row OPTMENU_ROWPTR
;;  describes -- table base plus the current step times four.
opt_value_ptr:
    LDY #$01
    LDA (OPTMENU_ROWPTR), Y     ; which scalar
    TAX
    LDA lut_ValTabLo, X
    STA OPTMENU_VALPTR
    LDA lut_ValTabHi, X
    STA OPTMENU_VALPTR + 1
    LDY lut_ValOff, X           ; where in the option page it is stored
    LDA OPTBLOCK, Y
    ASL A                       ; four bytes per readout
    ASL A
    CLC
    ADC OPTMENU_VALPTR
    STA OPTMENU_VALPTR
    LDA OPTMENU_VALPTR + 1
    ADC #$00
    STA OPTMENU_VALPTR + 1
    RTS


;;  In: A = RIGHT or LEFT.
;;
;;  On a value row the press adjusts the value, which is the only thing left
;;  and right can sensibly mean there.  Everywhere else it pages the list by
;;  half a screen, so getting from Quality of Life to the variations is two
;;  presses rather than twenty.  Contextual in the same way the title screen's
;;  left and right already are.
opt_sideways:
    PHA
    JSR opt_menu_rowptr
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_VAL
    BEQ @value
    LDA OPTMENU_SEL             ; paging half a screen from the first or last
    STA OPTMENU_WAS             ;   selectable row lands back on it; see @moved
    PLA
    CMP #RIGHT
    BEQ @fwd

    LDA OPTMENU_SEL             ; back half a screen, floored at the top
    SEC
    SBC #OPTLIST_PAGE
    BCS @haveback
    LDA #$00
  @haveback:
    TAX
    JSR opt_seek_back
    BCS @moved
    LDX #$00                    ; nothing selectable above; take the first
    JSR opt_seek_fwd
    BRA @moved

  @fwd:
    LDA OPTMENU_SEL             ; on half a screen, capped at the bottom
    CLC
    ADC #OPTLIST_PAGE
    CMP #OPTROW_COUNT
    BCC @havefwd
    LDA #OPTROW_COUNT - 1
  @havefwd:
    TAX
    JSR opt_seek_fwd
    BCS @moved
    LDX #OPTROW_COUNT - 1       ; nothing selectable below; take the last
    JSR opt_seek_back

  @moved:
    LDA OPTMENU_SEL
    CMP OPTMENU_WAS
    BEQ @quiet                  ; the page had nowhere to go
    JSR opt_sfx_move
  @quiet:
    JSR opt_menu_scroll
    BCS @painted                ; ...otherwise the repaint has done it
    JSR opt_menu_desc
  @painted:
    RTS

  @value:
    PLA
    ;  fall through


;;  In: A = RIGHT or LEFT.  Steps a value row, clamped at both ends.
;;
;;  Clamped rather than wrapped: these are magnitudes, and running off 500%
;;  back to 0% is the kind of thing you do by accident and do not notice.
opt_value_adjust:
    PHA
    JSR opt_menu_rowptr
    LDY #$00
    LDA (OPTMENU_ROWPTR), Y
    CMP #OPTROW_VAL
    BEQ :+
    PLA
    RTS                         ; not a value row
:   LDY #$01
    LDA (OPTMENU_ROWPTR), Y
    TAX                         ; X = which scalar
    LDY lut_ValOff, X           ; Y = where it is stored
    PLA
    CMP #RIGHT
    BNE @left

    LDA OPTBLOCK, Y
    CLC
    ADC #$01
    CMP lut_ValCount, X         ; the top step is count-1
    BCS @done                   ; clamped: the readout does not move, so
    STA OPTBLOCK, Y             ;   neither does the sound
    JSR opt_sfx_move
    JMP @done

  @left:
    LDA OPTBLOCK, Y
    BEQ @done                   ; at the bottom already
    SEC
    SBC #$01
    STA OPTBLOCK, Y
    JSR opt_sfx_move

  @done:
    JSR opt_commit_body
    JMP opt_menu_drawsel


;;  Wipe an on-screen row that has no list entry behind it.
opt_menu_blankrow:
    JSR opt_menu_ppuaddr
    LDA #$FF
    LDX #OPTROW_LABELW + 2 + 1 + VALFIELD
    JSL hal_ntfill + HALFAR     ; one identical run; ntfill's own fast path
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
OPTROW_COUNT  = 61

;  A row's label.  The row stores thirty bytes after its two header bytes but
;  only OPTROW_LABELW of them are drawn, so padding to thirty proves nothing --
;  FFPAD to 30 accepted "House restores HP and MP" and the menu showed "House
;  restores HP and".  This checks the width that matters and pads out the rest.
.macro OPTLABEL txt
  FFPAD txt, OPTROW_LABELW
  .repeat OPTROW_STRIDE - OPTROW_LABEL - OPTROW_LABELW
    .byte $FF
  .endrep
.endmacro

lut_OptRows:
  ;  A blank first row, because OPTLIST_TOP only accounts for nametable row 0
  ;  being cropped.  On a CRT row 1 is still half inside the overscan, so a
  ;  heading there is clipped.  Spending a list row rather than raising
  ;  OPTLIST_TOP keeps all twenty visible rows: this one occupies a slot only
  ;  while the list is scrolled to the very top, and costs nothing after that.
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30

  ;  The four dials come first, and the reason is the paging.  Left and right
  ;  page the list by half a screen everywhere except on a value row, where
  ;  they belong to the value -- so a cursor sitting among the dials cannot
  ;  page at all.  At the top of the list that costs nothing: the cursor
  ;  starts on this heading, where left and right still page, and the first
  ;  page lands well below them.  Anywhere else in the list it would be a
  ;  hole in the middle of the scrolling, in a position that moved every time
  ;  a flag was added above it.
  .BYTE $00, $00   ; SCALE
  FFPAD "SCALE", 30
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30
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
  .BYTE $02, $04   ; Elemental bonus
  FFPAD "Elemental bonus", 30
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30
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
  .BYTE $01, $0F   ; House restoration
  OPTLABEL {"House MP and HP fix"}
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
  .BYTE $01, $13   ; Better Thief and Ninja
  .BYTE $8B, $A8, $B7, $B7, $A8, $B5, $FF, $9D, $AB, $AC
  .BYTE $A8, $A9, $FF, $A4, $B1, $A7, $FF, $97, $AC, $B1
  .BYTE $AD, $A4, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $15   ; Thief and Ninja hit%   (bit 21, which the dial vacated)
  FFPAD "Thief and Ninja hit%", 30
  .BYTE $01, $14   ; Double weapon crit
  .BYTE $8D, $B2, $B8, $A5, $AF, $A8, $FF, $BA, $A8, $A4
  .BYTE $B3, $B2, $B1, $FF, $A6, $B5, $AC, $B7, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $16   ; Improved Cure spells
  .BYTE $92, $B0, $B3, $B5, $B2, $B9, $A8, $A7, $FF, $8C
  .BYTE $9E, $9B, $8E, $FF, $A4, $B1, $A7, $FF, $91, $8E
  .BYTE $8A, $95, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  ;  Written as "Improve FIRE, LIT, ICE, HARM" and twenty-eight columns of it,
  ;  against a row that draws twenty-two -- so HARM has never been on screen,
  ;  and no description mentions it either.  The cut lands on the comma and
  ;  reads cleanly, so the bytes now say what they draw and HARM stays in this
  ;  comment.  Not one tile changes.
  .BYTE $01, $17   ; Improved Fire spells -- and HARM, which will not fit
  OPTLABEL {"Improve FIRE, LIT, ICE"}
  .BYTE $01, $18   ; Cast Life in battle
  .BYTE $8C, $A4, $B6, $B7, $FF, $95, $AC, $A9, $A8, $FF
  .BYTE $AC, $B1, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $01, $19   ; LOK2 accuracy
  .BYTE $95, $98, $94, $82, $FF, $A4, $A6, $A6, $B8, $B5
  .BYTE $A4, $A6, $BC, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30
  .BYTE $00, $00   ; TREASURES
  FFPAD "TREASURES", 30
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30
  .BYTE $01, $1A   ; Free SHIP
  FFPAD "Free SHIP", 30
  .BYTE $01, $1B   ; Free AIRSHIP
  FFPAD "Free AIRSHIP", 30
  .BYTE $01, $1C   ; Free BRIDGE
  FFPAD "Free BRIDGE", 30
  .BYTE $01, $1D   ; Free CANAL
  FFPAD "Free CANAL", 30
  .BYTE $01, $1E   ; Free CANOE
  FFPAD "Free CANOE", 30
  .BYTE $01, $1F   ; Free KEY
  FFPAD "Free KEY", 30
  .BYTE $01, $20   ; Free CHIME
  FFPAD "Free CHIME", 30
  .BYTE $01, $21   ; Free CROWN
  FFPAD "Free CROWN", 30
  .BYTE $01, $22   ; Free LUTE
  FFPAD "Free LUTE", 30
  .BYTE $01, $23   ; Free TAIL
  FFPAD "Free TAIL", 30
  .BYTE $01, $24   ; Free ROD
  FFPAD "Free ROD", 30
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30
  .BYTE $00, $00   ; NEW GAME
  FFPAD "NEW GAME", 30
  .BYTE $03, $00   ; (blank)
  FFPAD "", 30
  .BYTE $02, $05   ; Trap tiles
  OPTLABEL {"Trap tiles"}

lut_OptRowsEnd:

;  A row table that disagrees with OPTROW_COUNT walks off the end of itself,
;  and so does a description table with the wrong number of pointers.  Both
;  are edited by hand every time a flag is added.
.assert lut_OptRowsEnd - lut_OptRows = OPTROW_COUNT * OPTROW_STRIDE, error, "row table is the wrong length"

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

;  Generated: the value-row readouts, four characters right-aligned.
VALFIELD = 4

;  Gold and XP: 0%% to 500%% in 50%% steps
lut_ValGoldXP:
  .BYTE $FF, $FF, $80, CHR_PCT   ;   0%
  .BYTE $FF, $85, $80, CHR_PCT   ;  50%
  .BYTE $81, $80, $80, CHR_PCT   ; 100%
  .BYTE $81, $85, $80, CHR_PCT   ; 150%
  .BYTE $82, $80, $80, CHR_PCT   ; 200%
  .BYTE $82, $85, $80, CHR_PCT   ; 250%
  .BYTE $83, $80, $80, CHR_PCT   ; 300%
  .BYTE $83, $85, $80, CHR_PCT   ; 350%
  .BYTE $84, $80, $80, CHR_PCT   ; 400%
  .BYTE $84, $85, $80, CHR_PCT   ; 450%
  .BYTE $85, $80, $80, CHR_PCT   ; 500%

;  Encounter rate: labelled by its effect on the overworld
lut_ValEncounter:
  .BYTE $FF, $98, $A9, $A9   ;  Off
  .BYTE $FF, $81, $80, CHR_PCT   ;  10%
  .BYTE $FF, $82, $80, CHR_PCT   ;  20%
  .BYTE $FF, $83, $80, CHR_PCT   ;  30%
  .BYTE $FF, $84, $80, CHR_PCT   ;  40%
  .BYTE $FF, $85, $80, CHR_PCT   ;  50%
  .BYTE $FF, $86, $80, CHR_PCT   ;  60%
  .BYTE $FF, $87, $80, CHR_PCT   ;  70%
  .BYTE $FF, $88, $80, CHR_PCT   ;  80%
  .BYTE $FF, $89, $80, CHR_PCT   ;  90%
  .BYTE $81, $80, $80, CHR_PCT   ; 100%
  .BYTE $81, $85, $80, CHR_PCT   ; 150%
  .BYTE $82, $80, $80, CHR_PCT   ; 200%
  .BYTE $83, $80, $80, CHR_PCT   ; 300%

;  Enemy and boss stats: 25%% to 500%% in 25%% steps
lut_ValStat:
  .BYTE $FF, $82, $85, CHR_PCT   ;  25%
  .BYTE $FF, $85, $80, CHR_PCT   ;  50%
  .BYTE $FF, $87, $85, CHR_PCT   ;  75%
  .BYTE $81, $80, $80, CHR_PCT   ; 100%
  .BYTE $81, $82, $85, CHR_PCT   ; 125%
  .BYTE $81, $85, $80, CHR_PCT   ; 150%
  .BYTE $81, $87, $85, CHR_PCT   ; 175%
  .BYTE $82, $80, $80, CHR_PCT   ; 200%
  .BYTE $82, $82, $85, CHR_PCT   ; 225%
  .BYTE $82, $85, $80, CHR_PCT   ; 250%
  .BYTE $82, $87, $85, CHR_PCT   ; 275%
  .BYTE $83, $80, $80, CHR_PCT   ; 300%
  .BYTE $83, $82, $85, CHR_PCT   ; 325%
  .BYTE $83, $85, $80, CHR_PCT   ; 350%
  .BYTE $83, $87, $85, CHR_PCT   ; 375%
  .BYTE $84, $80, $80, CHR_PCT   ; 400%
  .BYTE $84, $82, $85, CHR_PCT   ; 425%
  .BYTE $84, $85, $80, CHR_PCT   ; 450%
  .BYTE $84, $87, $85, CHR_PCT   ; 475%
  .BYTE $85, $80, $80, CHR_PCT   ; 500%

;  Elemental and type damage bonus: +0 to +50 in twos.  The game's own
;  value is +4, and every other dial on this screen can go below its
;  vanilla setting too, so this one starts at nothing rather than at
;  four.  FFR's slider is 1 to 50 and its presets sit at 10, 30 and 42.
;
;  Laid out one column left of the others: the percentage rows spend their
;  last column on the "%", so right-aligning this one would put its digits
;  under that sign instead of under their digits.  Aligning the numbers to
;  each other reads better than aligning the fields.
lut_ValElem:
  ;  The sign is CHR_PLUS, not a literal.  Written as $E6 it survived the
  ;  glyph moving twice and went on drawing whatever art was left behind --
  ;  the second move put the "S" of the battle panel's "Stone" in front of
  ;  every number in this table.
  .BYTE $FF, CHR_PLUS, $80, $FF   ;  +0
  .BYTE $FF, CHR_PLUS, $82, $FF   ;  +2
  .BYTE $FF, CHR_PLUS, $84, $FF   ;  +4   <- vanilla
  .BYTE $FF, CHR_PLUS, $86, $FF   ;  +6
  .BYTE $FF, CHR_PLUS, $88, $FF   ;  +8
  .BYTE CHR_PLUS, $81, $80, $FF   ; +10   <- FFR Improved Vanilla
  .BYTE CHR_PLUS, $81, $82, $FF   ; +12
  .BYTE CHR_PLUS, $81, $84, $FF   ; +14
  .BYTE CHR_PLUS, $81, $86, $FF   ; +16
  .BYTE CHR_PLUS, $81, $88, $FF   ; +18
  .BYTE CHR_PLUS, $82, $80, $FF   ; +20
  .BYTE CHR_PLUS, $82, $82, $FF   ; +22
  .BYTE CHR_PLUS, $82, $84, $FF   ; +24
  .BYTE CHR_PLUS, $82, $86, $FF   ; +26
  .BYTE CHR_PLUS, $82, $88, $FF   ; +28
  .BYTE CHR_PLUS, $83, $80, $FF   ; +30   <- FFR default
  .BYTE CHR_PLUS, $83, $82, $FF   ; +32
  .BYTE CHR_PLUS, $83, $84, $FF   ; +34
  .BYTE CHR_PLUS, $83, $86, $FF   ; +36
  .BYTE CHR_PLUS, $83, $88, $FF   ; +38
  .BYTE CHR_PLUS, $84, $80, $FF   ; +40
  .BYTE CHR_PLUS, $84, $82, $FF   ; +42   <- FFR 2025 tournament
  .BYTE CHR_PLUS, $84, $84, $FF   ; +44
  .BYTE CHR_PLUS, $84, $86, $FF   ; +46
  .BYTE CHR_PLUS, $84, $88, $FF   ; +48
  .BYTE CHR_PLUS, $85, $80, $FF   ; +50

;  Trap tiles: FFR's first five modes.  See deal_traps in rando.asm.
lut_ValTraps:
  FFPAD " Off", 4               ; TRAPS_OFF
  FFPAD "Shuf", 4               ; TRAPS_SHUFFLE
  FFPAD "   A", 4               ; TRAPS_ASIDE
  FFPAD "   B", 4               ; TRAPS_BSIDE
  FFPAD " A+B", 4               ; TRAPS_BOTH

;  Per-scalar: where its readouts are, how many there are, and where its
;  byte is.
lut_ValTabLo: .BYTE <lut_ValGoldXP, <lut_ValEncounter, <lut_ValStat, <lut_ValStat, <lut_ValElem, <lut_ValTraps
lut_ValTabHi: .BYTE >lut_ValGoldXP, >lut_ValEncounter, >lut_ValStat, >lut_ValStat, >lut_ValElem, >lut_ValTraps
lut_ValCount: .BYTE 11, 14, 20, 20, ELEMDMG_STEPS, TRAPS_MODES
;  Where each scalar lives, as an offset into the option page.  The five
;  dials are consecutive in the checksummed block; the new-game rows are
;  higher up, beside the settings they are copied into the save with.
lut_ValOff:   .BYTE <OPT_GOLDXP, <OPT_ENCOUNTER, <OPT_ENEMY, <OPT_BOSS, <OPT_ELEMDMG
              .BYTE <OPT_NG_TRAPS
.assert <OPTBLOCK = 0, error, "lut_ValOff holds offsets into a page-aligned option block"

;  Generated: the description pane text, pre-wrapped to 28 columns and 5
;  lines.  Wrapping at build time rather than at runtime keeps the draw to
;  five fixed blits and keeps the wording under review in the source.
DESC_W = 28
DESC_LINES = 5
DESC_SIZE = 140

lut_DescBlank:
  FFLINES 0


lut_Desc_0:  ; QUALITY OF LIFE
  FFLINES 3
  .BYTE $8C, $B2, $B1, $B9, $A8, $B1, $AC, $A8, $B1, $A6, $A8, $FF, $A6, $AB, $A4, $B1, $AA, $A8, $B6, $C0, $FF, $97, $B2, $B1, $A8, $FF, $B2, $A9
  .BYTE $B7, $AB, $A8, $B6, $A8, $FF, $A4, $AF, $B7, $A8, $B5, $FF, $AB, $B2, $BA, $FF, $B7, $AB, $A8, $FF, $AA, $A4, $B0, $A8, $FF, $FF, $FF, $FF
  .BYTE $B3, $AF, $A4, $BC, $B6, $FF, $B2, $B8, $B7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_1:  ; BUGFIXES
  FFLINES 2
  .BYTE $8C, $B2, $B5, $B5, $A8, $A6, $B7, $AC, $B2, $B1, $B6, $FF, $B7, $B2, $FF, $B0, $AC, $B6, $B7, $A4, $AE, $A8, $B6, $FF, $AC, $B1, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $B2, $B5, $AC, $AA, $AC, $B1, $A4, $AF, $FF, $AA, $A4, $B0, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_2:  ; VARIATIONS
  FFLINES 2
  .BYTE $8C, $AB, $A4, $B1, $AA, $A8, $B6, $FF, $B7, $AB, $A4, $B7, $FF, $A7, $A8, $AF, $AC, $A5, $A8, $B5, $A4, $B7, $A8, $AF, $BC, $FF, $FF, $FF
  .BYTE $A4, $AF, $B7, $A8, $B5, $FF, $AB, $B2, $BA, $FF, $B7, $AB, $A8, $FF, $AA, $A4, $B0, $A8, $FF, $B3, $AF, $A4, $BC, $B6, $C0, $FF, $FF, $FF

lut_Desc_3:  ; Speed hacks
  FFLINES 3
  .BYTE $8A, $B5, $A8, $A4, $FF, $B7, $B5, $A4, $B1, $B6, $AC, $B7, $AC, $B2, $B1, $B6, $BF, $FF, $B0, $A8, $B1, $B8, $B6, $BF, $FF, $FF, $FF, $FF
  .BYTE $A5, $A4, $B7, $B7, $AF, $A8, $FF, $A5, $B2, $BB, $A8, $B6, $FF, $A4, $B1, $A7, $FF, $A4, $B1, $AC, $B0, $A4, $B7, $AC, $B2, $B1, $B6, $FF
  .BYTE $A4, $AF, $AF, $FF, $B5, $B8, $B1, $FF, $A9, $A4, $B6, $B7, $A8, $B5, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_4:  ; Faster walking
  FFLINES 3
  .BYTE $A0, $A4, $AF, $AE, $AC, $B1, $AA, $FF, $A4, $B1, $A7, $FF, $A6, $A4, $B1, $B2, $A8, $FF, $B6, $B3, $A8, $A8, $A7, $FF, $AC, $B6, $FF, $FF
  .BYTE $A7, $B2, $B8, $A5, $AF, $A8, $A7, $C0, $FF, $91, $B2, $AF, $A7, $FF, $8B, $FF, $B7, $B2, $FF, $B0, $B2, $B9, $A8, $FF, $A4, $B7, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $B2, $B5, $AC, $AA, $AC, $B1, $A4, $AF, $FF, $B3, $A4, $A6, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_5:  ; Faster ship
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $B6, $AB, $AC, $B3, $FF, $B6, $A4, $AC, $AF, $B6, $FF, $A4, $B6, $FF, $A9, $A4, $B6, $B7, $FF, $A4, $B6, $FF, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $A4, $AC, $B5, $B6, $AB, $AC, $B3, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_6:  ; No party shuffle
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $B3, $A4, $B5, $B7, $BC, $FF, $AC, $B6, $FF, $B1, $B2, $B7, $FF, $B5, $A8, $A4, $B5, $B5, $A4, $B1, $AA, $A8, $A7, $FF
  .BYTE $BA, $AB, $A8, $B1, $FF, $A4, $FF, $A6, $AB, $A4, $B5, $A4, $A6, $B7, $A8, $B5, $FF, $A9, $A4, $AF, $AF, $B6, $C0, $FF, $FF, $FF, $FF, $FF

lut_Desc_7:  ; Identify treasures
  FFLINES 2
  .BYTE $8A, $FF, $A9, $B8, $AF, $AF, $FF, $AC, $B1, $B9, $A8, $B1, $B7, $B2, $B5, $BC, $FF, $B6, $B7, $AC, $AF, $AF, $FF, $B7, $A8, $AF, $AF, $B6
  .BYTE $BC, $B2, $B8, $FF, $BA, $AB, $A4, $B7, $FF, $BA, $A4, $B6, $FF, $AC, $B1, $FF, $B7, $AB, $A8, $FF, $A6, $AB, $A8, $B6, $B7, $C0, $FF, $FF

lut_Desc_8:  ; Chests appear opened
  FFLINES 3
  .BYTE $8C, $AB, $A8, $B6, $B7, $B6, $FF, $BC, $B2, $B8, $FF, $AB, $A4, $B9, $A8, $FF, $A4, $AF, $B5, $A8, $A4, $A7, $BC, $FF, $FF, $FF, $FF, $FF
  .BYTE $AF, $B2, $B2, $B7, $A8, $A7, $FF, $AF, $B2, $B2, $AE, $FF, $B2, $B3, $A8, $B1, $C0, $FF, $8A, $B3, $B3, $AF, $AC, $A8, $B6, $FF, $FF, $FF
  .BYTE $B7, $B2, $FF, $A4, $B1, $FF, $A8, $BB, $AC, $B6, $B7, $AC, $B1, $AA, $FF, $B6, $A4, $B9, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_9:  ; Buy quantity
  FFLINES 3
  .BYTE $8C, $AB, $B2, $B2, $B6, $A8, $FF, $AB, $B2, $BA, $FF, $B0, $A4, $B1, $BC, $FF, $B2, $A9, $FF, $A4, $B1, $FF, $AC, $B7, $A8, $B0, $FF, $FF
  .BYTE $B7, $B2, $FF, $A5, $B8, $BC, $BF, $FF, $AC, $B1, $B6, $B7, $A8, $A4, $A7, $FF, $B2, $A9, $FF, $B2, $B1, $A8, $FF, $A4, $B7, $FF, $FF, $FF
  .BYTE $A4, $FF, $B7, $AC, $B0, $A8, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_10:  ; Run becomes Wait
  FFLINES 3
  .BYTE $A0, $AB, $A8, $B1, $FF, $A4, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $FF, $A6, $A4, $B1, $B1, $B2, $B7, $FF, $A5, $A8, $FF, $FF, $FF, $FF, $FF
  .BYTE $A8, $B6, $A6, $A4, $B3, $A8, $A7, $BF, $FF, $9B, $9E, $97, $FF, $B5, $A8, $A4, $A7, $B6, $FF, $A0, $8A, $92, $9D, $FF, $A4, $B1, $A7, $FF
  .BYTE $B6, $A4, $BC, $B6, $FF, $B6, $B2, $FF, $B3, $AF, $A4, $AC, $B1, $AF, $BC, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_11:  ; Magic menu wraparound
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $FF, $B0, $A4, $AA, $AC, $A6, $FF, $A6, $B8, $B5, $B6, $B2, $B5, $FF, $FF, $FF, $FF, $FF
  .BYTE $BA, $B5, $A4, $B3, $B6, $FF, $A9, $B5, $B2, $B0, $FF, $A5, $B2, $B7, $B7, $B2, $B0, $FF, $B7, $B2, $FF, $B7, $B2, $B3, $C0, $FF, $FF, $FF

lut_Desc_12:  ; Auto retargeting
  FFLINES 3
  .BYTE $8A, $B7, $B7, $A4, $A6, $AE, $B6, $FF, $A4, $B1, $A7, $FF, $B6, $B3, $A8, $AF, $AF, $B6, $FF, $A4, $AC, $B0, $A8, $A7, $FF, $A4, $B7, $FF
  .BYTE $A4, $FF, $A7, $A8, $A4, $A7, $FF, $A8, $B1, $A8, $B0, $BC, $FF, $B3, $AC, $A6, $AE, $FF, $A4, $FF, $AF, $AC, $B9, $AC, $B1, $AA, $FF, $FF
  .BYTE $B2, $B1, $A8, $FF, $AC, $B1, $B6, $B7, $A8, $A4, $A7, $FF, $B2, $A9, $FF, $A5, $A8, $AC, $B1, $AA, $FF, $BA, $A4, $B6, $B7, $A8, $A7, $C0

lut_Desc_13:  ; Autosort inventory
  FFLINES 3
  .BYTE $91, $8E, $8A, $95, $BF, $FF, $99, $9E, $9B, $8E, $FF, $A4, $B1, $A7, $FF, $9C, $98, $8F, $9D, $FF, $B3, $B2, $B7, $AC, $B2, $B1, $B6, $FF
  .BYTE $A4, $B5, $A8, $FF, $AE, $A8, $B3, $B7, $FF, $A4, $B7, $FF, $B7, $AB, $A8, $FF, $B7, $B2, $B3, $FF, $B2, $A9, $FF, $B7, $AB, $A8, $FF, $FF
  .BYTE $AC, $B7, $A8, $B0, $FF, $AF, $AC, $B6, $B7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_14:  ; Repeated potion use
  FFLINES 2
  .BYTE $9E, $B6, $A8, $FF, $B6, $A8, $B9, $A8, $B5, $A4, $AF, $FF, $B3, $B2, $B7, $AC, $B2, $B1, $B6, $FF, $AC, $B1, $FF, $A4, $FF, $B5, $B2, $BA
  .BYTE $BA, $AC, $B7, $AB, $B2, $B8, $B7, $FF, $B5, $A8, $B2, $B3, $A8, $B1, $AC, $B1, $AA, $FF, $B7, $AB, $A8, $FF, $B0, $A8, $B1, $B8, $C0, $FF

lut_Desc_15:  ; Shop information
  FFLINES 3
  .BYTE $9C, $AB, $B2, $B3, $B6, $FF, $B6, $AB, $B2, $BA, $FF, $BA, $AB, $A8, $B7, $AB, $A8, $B5, $FF, $A8, $A4, $A6, $AB, $FF, $FF, $FF, $FF, $FF
  .BYTE $A6, $AB, $A4, $B5, $A4, $A6, $B7, $A8, $B5, $FF, $A6, $A4, $B1, $FF, $A8, $B4, $B8, $AC, $B3, $FF, $A4, $B1, $FF, $AC, $B7, $A8, $B0, $FF
  .BYTE $A4, $B1, $A7, $FF, $BA, $AB, $A4, $B7, $FF, $AC, $B7, $FF, $BA, $B2, $B8, $AF, $A7, $FF, $A7, $B2, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_16:  ; Chest information
  FFLINES 2
  .BYTE $98, $B3, $A8, $B1, $AC, $B1, $AA, $FF, $A4, $FF, $A6, $AB, $A8, $B6, $B7, $FF, $A7, $A8, $B6, $A6, $B5, $AC, $A5, $A8, $B6, $FF, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $BA, $A8, $A4, $B3, $B2, $B1, $FF, $B2, $B5, $FF, $A4, $B5, $B0, $B2, $B8, $B5, $FF, $AC, $B1, $FF, $AC, $B7, $C0, $FF

lut_Desc_17:  ; NPC guillotine
  FFLINES 2
  .BYTE $9D, $A4, $AF, $AE, $AC, $B1, $AA, $FF, $B7, $B2, $FF, $A4, $B1, $FF, $B2, $B5, $A7, $AC, $B1, $A4, $B5, $BC, $FF, $97, $99, $8C, $FF, $FF
  .BYTE $B5, $A8, $B0, $B2, $B9, $A8, $B6, $FF, $AC, $B7, $FF, $A9, $B5, $B2, $B0, $FF, $B7, $AB, $A8, $FF, $B0, $A4, $B3, $C0, $FF, $FF, $FF, $FF

lut_Desc_18:  ; House restoration
  FFLINES 4
  FFPAD {"HOUSEs restore all HP, not"}, 28
  FFPAD {"120, and restore MP whether"}, 28
  FFPAD {"or not you save -- which the"}, 28
  FFPAD {"save then records."}, 28

lut_Desc_19:  ; Weapon stats
  FFLINES 5
  FFPAD {"Fixes critical hit rates,"}, 28
  FFPAD {"which vanilla reads from a"}, 28
  FFPAD {"weapon's place in the list,"}, 28
  FFPAD {"and elemental and creature"}, 28
  FFPAD {"bonuses that never applied."}, 28

lut_Desc_20:  ; Spell fixes
  FFLINES 3
  .BYTE $8C, $B2, $B5, $B5, $A8, $A6, $B7, $B6, $FF, $95, $98, $8C, $94, $BF, $FF, $95, $98, $94, $82, $BF, $FF, $91, $8E, $95, $82, $BF, $FF, $FF
  .BYTE $9D, $96, $99, $9B, $BF, $FF, $9C, $8A, $8B, $9B, $FF, $A4, $B1, $A7, $FF, $8C, $9E, $9B, $84, $BF, $FF, $BA, $AB, $AC, $A6, $AB, $FF, $FF
  .BYTE $A7, $AC, $A7, $FF, $B1, $B2, $B7, $FF, $BA, $B2, $B5, $AE, $FF, $A4, $B6, $FF, $A7, $A8, $B6, $A6, $B5, $AC, $A5, $A8, $A7, $C0, $FF, $FF

lut_Desc_21:  ; Enemy status attacks
  FFLINES 3
  .BYTE $8F, $AC, $BB, $A8, $B6, $FF, $A8, $B1, $A8, $B0, $AC, $A8, $B6, $FF, $AC, $B1, $A9, $AF, $AC, $A6, $B7, $AC, $B1, $AA, $FF, $A4, $FF, $FF
  .BYTE $B6, $B7, $A4, $B7, $B8, $B6, $FF, $A4, $AC, $AF, $B0, $A8, $B1, $B7, $FF, $BA, $AC, $B7, $AB, $FF, $A4, $B7, $B7, $A4, $A6, $AE, $B6, $FF
  .BYTE $B7, $AB, $A4, $B7, $FF, $B6, $AB, $B2, $B8, $AF, $A7, $FF, $B1, $B2, $B7, $FF, $A6, $A4, $B5, $B5, $BC, $FF, $B2, $B1, $A8, $C0, $FF, $FF

lut_Desc_22:  ; Gold and XP
  FFLINES 3
  .BYTE $9C, $A6, $A4, $AF, $A8, $B6, $FF, $B7, $AB, $A8, $FF, $AA, $B2, $AF, $A7, $FF, $A4, $B1, $A7, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF
  .BYTE $A8, $BB, $B3, $A8, $B5, $AC, $A8, $B1, $A6, $A8, $FF, $B7, $AB, $A4, $B7, $FF, $A8, $B9, $A8, $B5, $BC, $FF, $A5, $A4, $B7, $B7, $AF, $A8
  .BYTE $A4, $BA, $A4, $B5, $A7, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_23:  ; Encounter rate
  FFLINES 3
  .BYTE $91, $B2, $BA, $FF, $B2, $A9, $B7, $A8, $B1, $FF, $B5, $A4, $B1, $A7, $B2, $B0, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $B6, $FF, $FF, $FF, $FF
  .BYTE $AB, $A4, $B3, $B3, $A8, $B1, $BF, $FF, $A4, $B6, $FF, $A4, $FF, $B6, $AB, $A4, $B5, $A8, $FF, $B2, $A9, $FF, $B7, $AB, $A8, $FF, $FF, $FF
  .BYTE $B2, $B5, $AC, $AA, $AC, $B1, $A4, $AF, $FF, $B2, $B9, $A8, $B5, $BA, $B2, $B5, $AF, $A7, $FF, $B5, $A4, $B7, $A8, $C0, $FF, $FF, $FF, $FF

lut_Desc_24:  ; Enemy stats
  FFLINES 3
  .BYTE $9C, $A6, $A4, $AF, $A8, $B6, $FF, $91, $99, $BF, $FF, $A7, $A4, $B0, $A4, $AA, $A8, $BF, $FF, $A7, $A8, $A9, $A8, $B1, $A6, $A8, $FF, $FF
  .BYTE $A4, $B1, $A7, $FF, $A4, $A6, $A6, $B8, $B5, $A4, $A6, $BC, $FF, $A9, $B2, $B5, $FF, $B2, $B5, $A7, $AC, $B1, $A4, $B5, $BC, $FF, $FF, $FF
  .BYTE $A8, $B1, $A8, $B0, $AC, $A8, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_25:  ; Boss stats
  FFLINES 2
  .BYTE $9D, $AB, $A8, $FF, $B6, $A4, $B0, $A8, $BF, $FF, $A9, $B2, $B5, $FF, $B7, $AB, $A8, $FF, $B7, $AB, $AC, $B5, $B7, $A8, $A8, $B1, $FF, $FF
  .BYTE $A5, $B2, $B6, $B6, $A8, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_26:  ; Better Thief and Ninja
  FFLINES 4
  FFPAD {"The Thief starts with 80"}, 28
  FFPAD {"agility, not 10, and gains"}, 28
  FFPAD {"it every level, not one in"}, 28
  FFPAD {"four. A Ninja keeps both."}, 28

lut_Desc_27:  ; Double weapon crit
  FFLINES 5
  FFPAD {"Doubles every weapon's"}, 28
  FFPAD {"critical hit rate.  Needs"}, 28
  FFPAD {"Weapon Stats, without which"}, 28
  FFPAD {"the game never reads that"}, 28
  FFPAD {"number at all."}, 28

lut_Desc_28:  ; Elemental bonus
  FFLINES 5
  FFPAD {"Damage added when an attack"}, 28
  FFPAD {"matches a weakness. Vanilla"}, 28
  FFPAD {"is +4. Needs Weapon stats on"}, 28
  FFPAD {"or only monsters get it -"}, 28
  FFPAD {"party weapon element is 0."}, 28

lut_Desc_29:  ; Improved Cure spells
  FFLINES 4
  .BYTE $8C, $9E, $9B, $8E, $B6, $FF, $B5, $A8, $B6, $B7, $B2, $B5, $A8, $FF, $B7, $BA, $AC, $A6, $A8, $FF, $A4, $B6, $FF, $B0, $B8, $A6, $AB, $FF
  .BYTE $A4, $B1, $A7, $FF, $91, $8E, $8A, $95, $B6, $FF, $A6, $B2, $B9, $A8, $B5, $FF, $A4, $FF, $BA, $AC, $A7, $A8, $B5, $FF, $FF, $FF, $FF, $FF
  .BYTE $B5, $A4, $B1, $AA, $A8, $C0, $FF, $FF, $95, $8A, $96, $99, $FF, $A4, $B1, $A7, $FF, $8A, $96, $9E, $9D, $FF, $A4, $AF, $B6, $B2, $FF, $FF
  .BYTE $A6, $B8, $B5, $A8, $FF, $B3, $A4, $B5, $A4, $AF, $BC, $B6, $AC, $B6, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_30:  ; Improved Fire spells
  FFLINES 4
  .BYTE $8F, $92, $9B, $8E, $BF, $FF, $95, $92, $9D, $FF, $A4, $B1, $A7, $FF, $92, $8C, $8E, $FF, $AB, $AC, $B7, $FF, $A4, $B6, $FF, $FF, $FF, $FF
  .BYTE $AB, $A4, $B5, $A7, $FF, $A4, $B6, $FF, $B7, $AB, $A8, $AC, $B5, $FF, $B7, $AC, $A8, $B5, $C2, $83, $FF, $A9, $B2, $B5, $B0, $B6, $C0, $FF
  .BYTE $91, $8A, $9B, $96, $FF, $AB, $AC, $B7, $B6, $FF, $AB, $A4, $B5, $A7, $A8, $B5, $FF, $A4, $B1, $A7, $FF, $B6, $B7, $B5, $AC, $AE, $A8, $B6
  .BYTE $A4, $FF, $B6, $AC, $B1, $AA, $AF, $A8, $FF, $B7, $A4, $B5, $AA, $A8, $B7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_31:  ; Cast Life in battle
  FFLINES 3
  .BYTE $95, $92, $8F, $8E, $FF, $A4, $B1, $A7, $FF, $95, $92, $8F, $82, $FF, $A6, $A4, $B1, $FF, $A5, $A8, $FF, $B8, $B6, $A8, $A7, $FF, $FF, $FF
  .BYTE $A7, $B8, $B5, $AC, $B1, $AA, $FF, $A5, $A4, $B7, $B7, $AF, $A8, $BF, $FF, $B1, $B2, $B7, $FF, $B2, $B1, $AF, $BC, $FF, $B2, $B1, $FF, $FF
  .BYTE $B7, $AB, $A8, $FF, $B0, $A4, $B3, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF

lut_Desc_32:  ; LOK2 accuracy
  FFLINES 3
  .BYTE $95, $98, $8C, $94, $FF, $A4, $B1, $A7, $FF, $95, $98, $94, $82, $FF, $AB, $AC, $B7, $FF, $A9, $A4, $B5, $FF, $B0, $B2, $B5, $A8, $FF, $FF
  .BYTE $B2, $A9, $B7, $A8, $B1, $BF, $FF, $A4, $B6, $FF, $B7, $AB, $A8, $FF, $B0, $A4, $B1, $B8, $A4, $AF, $FF, $A4, $AF, $BA, $A4, $BC, $B6, $FF
  .BYTE $A6, $AF, $A4, $AC, $B0, $A8, $A7, $FF, $B7, $AB, $A8, $BC, $FF, $A7, $AC, $A7, $C0, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF


lut_Desc_33:  ; TREASURES
  FFLINES 3
  FFPAD {"Changes what a new game"}, 28
  FFPAD {"starts out with.  Saved"}, 28
  FFPAD {"games are not affected."}, 28

lut_Desc_46:  ; Thief and Ninja hit%
  FFLINES 4
  FFPAD {"Hit rate grows twice as fast"}, 28
  FFPAD {"for the Thief and the Ninja."}, 28
  FFPAD {"Separate from the agility"}, 28
  FFPAD {"buff above."}, 28

lut_Desc_45:  ; SCALE
  FFLINES 3
  FFPAD {"Adjustments to the game"}, 28
  FFPAD {"difficulty. Press left and"}, 28
  FFPAD {"right to change the value."}, 28

lut_Desc_34:  ; Free SHIP
  FFLINES 3
  FFPAD {"The ship is moored beside"}, 28
  FFPAD {"Coneria from the start,"}, 28
  FFPAD {"without beating the pirates."}, 28

lut_Desc_35:  ; Free AIRSHIP
  FFLINES 3
  FFPAD {"The airship is parked where"}, 28
  FFPAD {"the party starts, with no"}, 28
  FFPAD {"need for the FLOATER."}, 28

lut_Desc_36:  ; Free BRIDGE
  FFLINES 3
  FFPAD {"The bridge east of Coneria"}, 28
  FFPAD {"is already built, without"}, 28
  FFPAD {"rescuing the princess."}, 28

lut_Desc_37:  ; Free CANAL
  FFLINES 2
  FFPAD {"The canal is already open,"}, 28
  FFPAD {"without Nerrick and the TNT."}, 28

lut_Desc_38:  ; Free CANOE
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"CANOE, without the sage at"}, 28
  FFPAD {"Crescent Lake."}, 28


lut_Desc_39:  ; Free KEY
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"mystic KEY, which opens"}, 28
  FFPAD {"every locked door there is."}, 28

lut_Desc_40:  ; Free CHIME
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"CHIME, which opens the way"}, 28
  FFPAD {"into the Mirage Tower."}, 28

lut_Desc_41:  ; Free CROWN
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"CROWN, so the Marsh Cave"}, 28
  FFPAD {"need not be searched for it."}, 28


lut_Desc_42:  ; Free LUTE
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"LUTE, without rescuing the"}, 28
  FFPAD {"princess."}, 28

lut_Desc_43:  ; Free TAIL
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"TAIL, without searching the"}, 28
  FFPAD {"Ice Cave for it."}, 28

lut_Desc_44:  ; Free ROD
  FFLINES 3
  FFPAD {"The party starts with the"}, 28
  FFPAD {"ROD, which opens the way"}, 28
  FFPAD {"down through the Earth Cave."}, 28

lut_Desc_47:  ; NEW GAME
  FFLINES 4
  FFPAD {"Randomizes the next new"}, 28
  FFPAD {"game.  A saved game keeps"}, 28
  FFPAD {"the world it was started"}, 28
  FFPAD {"with, whatever is set here."}, 28

lut_Desc_48:  ; Trap tiles
  FFLINES 5
  FFPAD {"Shuf trades the 34 trap"}, 28
  FFPAD {"tiles' fights among them."}, 28
  FFPAD {"A, B and A+B give each trap"}, 28
  FFPAD {"a fight drawn from every"}, 28
  FFPAD {"A-side, B-side or both."}, 28

;  One pointer per list row, so a blank row needs no special case.
lut_DescLo:
  .BYTE <lut_DescBlank, <lut_Desc_45, <lut_DescBlank, <lut_Desc_22, <lut_Desc_23
  .BYTE <lut_Desc_24, <lut_Desc_25, <lut_Desc_28, <lut_DescBlank, <lut_Desc_0
  .BYTE <lut_DescBlank, <lut_Desc_3, <lut_Desc_4, <lut_Desc_5, <lut_Desc_6
  .BYTE <lut_Desc_7, <lut_Desc_8, <lut_Desc_9, <lut_Desc_10, <lut_Desc_11
  .BYTE <lut_Desc_12, <lut_Desc_13, <lut_Desc_14, <lut_Desc_15, <lut_Desc_16
  .BYTE <lut_Desc_17, <lut_DescBlank, <lut_Desc_1, <lut_DescBlank, <lut_Desc_18
  .BYTE <lut_Desc_19, <lut_Desc_20, <lut_Desc_21, <lut_DescBlank, <lut_Desc_2
  .BYTE <lut_DescBlank, <lut_Desc_26, <lut_Desc_46, <lut_Desc_27, <lut_Desc_29
  .BYTE <lut_Desc_30, <lut_Desc_31, <lut_Desc_32, <lut_DescBlank, <lut_Desc_33
  .BYTE <lut_DescBlank, <lut_Desc_34, <lut_Desc_35, <lut_Desc_36, <lut_Desc_37
  .BYTE <lut_Desc_38, <lut_Desc_39, <lut_Desc_40, <lut_Desc_41, <lut_Desc_42
  .BYTE <lut_Desc_43, <lut_Desc_44, <lut_DescBlank, <lut_Desc_47, <lut_DescBlank
  .BYTE <lut_Desc_48
lut_DescLoEnd:
.assert lut_DescLoEnd - lut_DescLo = OPTROW_COUNT, error, "one description pointer per row"
lut_DescHi:
  .BYTE >lut_DescBlank, >lut_Desc_45, >lut_DescBlank, >lut_Desc_22, >lut_Desc_23
  .BYTE >lut_Desc_24, >lut_Desc_25, >lut_Desc_28, >lut_DescBlank, >lut_Desc_0
  .BYTE >lut_DescBlank, >lut_Desc_3, >lut_Desc_4, >lut_Desc_5, >lut_Desc_6
  .BYTE >lut_Desc_7, >lut_Desc_8, >lut_Desc_9, >lut_Desc_10, >lut_Desc_11
  .BYTE >lut_Desc_12, >lut_Desc_13, >lut_Desc_14, >lut_Desc_15, >lut_Desc_16
  .BYTE >lut_Desc_17, >lut_DescBlank, >lut_Desc_1, >lut_DescBlank, >lut_Desc_18
  .BYTE >lut_Desc_19, >lut_Desc_20, >lut_Desc_21, >lut_DescBlank, >lut_Desc_2
  .BYTE >lut_DescBlank, >lut_Desc_26, >lut_Desc_46, >lut_Desc_27, >lut_Desc_29
  .BYTE >lut_Desc_30, >lut_Desc_31, >lut_Desc_32, >lut_DescBlank, >lut_Desc_33
  .BYTE >lut_DescBlank, >lut_Desc_34, >lut_Desc_35, >lut_Desc_36, >lut_Desc_37
  .BYTE >lut_Desc_38, >lut_Desc_39, >lut_Desc_40, >lut_Desc_41, >lut_Desc_42
  .BYTE >lut_Desc_43, >lut_Desc_44, >lut_DescBlank, >lut_Desc_47, >lut_DescBlank
  .BYTE >lut_Desc_48
lut_DescHiEnd:
.assert lut_DescHiEnd - lut_DescHi = OPTROW_COUNT, error, "one description pointer per row"
