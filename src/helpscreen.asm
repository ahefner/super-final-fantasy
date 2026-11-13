; ---------------------------------------------------------------------------
;  helpscreen.asm -- the title's Help page (user, 2026-11-12), in the
;  settings screen's chunk (CHUNK_OPTMENU): its background, chirps and text
;  routines are that engine's, as the Seed Summary's are.
;
;  A PLACEHOLDER for now: the page will be "a simple text page display that
;  explains the new controls (left trigger + x/y, select button in menus,
;  etc.)" -- the user's text, when it comes, goes in lut_HelpLines.
;
;  A, B or START goes back to the title.  No hand: nothing to choose.  The
;  title's music plays on, and L + X / L + Y reset from it, through
;  WaitForVBlank_L as on the settings screen.
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

.export help_show
.export help_draw, lut_HelpLines    ; for the tests
.import opt_menu_breathe, opt_menu_fillbg, opt_menu_descppu
.import opt_sfx_sel, opt_waitrelease
.import ClearOAM, CallMusicPlay, UpdateJoy, WaitForVBlank_L
.import hal_clearnt, hal_ntblit

.segment "BANK_OPTMENU"

HELP_LINEW = DESC_W             ; a line, from DESC_COL, as the descriptions

;;  By JSL, emulation mode, from the title (opt_titlechoose), with the screen
;;  the title's; out with it off, for the title to rebuild.
help_show:
    PHB
    PHK
    PLB
    LDA #$00
    wPPUMASK                    ; screen off while it is built
    JSL hal_clearnt + HALFAR
    JSR opt_menu_fillbg
    JSR help_draw
    JSR ClearOAM                ; no hand
    LDA #>oam
    wOAMDMA
    JSR opt_menu_breathe        ; ...sent
    LDA #$1E
    wPPUMASK                    ; ...and on
    JSR opt_waitrelease         ; the A that brought it carries no further

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
    AND #PAD_A | PAD_B | PAD_START
    BEQ @loop
    JSR opt_sfx_sel             ; the game's sound for a choice, B's too
    JSR opt_waitrelease         ; nothing carries on to the title
    LDA #$00
    wPPUMASK
    PLB
    RTL

;;  Each line of lut_HelpLines at its row.  A pointer walks the table a line
;;  at a time (the description's, unused here): an 8-bit index ran out in the
;;  ninth line, wrapped to the title's text, and stopped at its first space.
help_draw:
    LDA #<lut_HelpLines
    STA OPTMENU_DESC
    LDA #>lut_HelpLines
    STA OPTMENU_DESC + 1
  @line:
    LDY #0
    LDA (OPTMENU_DESC), Y       ; its row, or $FF at the end
    CMP #$FF
    BEQ @done
    STA OPTMENU_ROWNUM
    INY
    LDX #0
  @c:
    LDA (OPTMENU_DESC), Y
    STA f:NTSTAGE, X
    INY
    INX
    CPX #HELP_LINEW
    BCC @c
    JSR opt_menu_descppu
    LDX #HELP_LINEW
    JSL hal_ntblit + HALFAR
    LDA OPTMENU_DESC            ; on to the next line
    CLC
    ADC #HELP_LINEW + 1
    STA OPTMENU_DESC
    BCC @line
    INC OPTMENU_DESC + 1
    BRA @line
  @done:
    RTS

;  The page: each line its nametable row, then its text padded to the line.
;  Rows 2-27 are what a CRT shows.
.macro HELPLINE row, txt
  .BYTE row
  FFPAD txt, HELP_LINEW
.endmacro
lut_HelpLines:
  HELPLINE  2, "            HELP"
  HELPLINE  6, "  Instructions will go here."
  .BYTE $FF
