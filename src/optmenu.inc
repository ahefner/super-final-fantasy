; ---------------------------------------------------------------------------
;  optmenu.inc -- what the settings screen and its text agree on.
;
;  optmenu.asm draws the screen; opttext.asm holds the descriptions, in a
;  chunk of their own.  Both need the row count and the record format.
; ---------------------------------------------------------------------------

;  The settings list.  byte 0 = kind, byte 1 = flag bit or scalar index,
;  bytes 2..23 = the label.  Section headings stay in capitals; the settings
;  themselves are sentence case, which needs the lowercase run at $A4..$BD.
;  Blank rows exist only to separate the sections, and the cursor skips them
;  along with the headings.
OPTROW_HDR    = 0
OPTROW_CHK    = 1
OPTROW_VAL    = 2
OPTROW_BLANK  = 3
OPTROW_SEED   = 4               ; the save view's seed; never in lut_OptRows
OPTROW_PICK   = 5               ; a New Game list entry: A or START chooses it,
                                ;   byte 1 the preset ($FF Custom Game), and the
                                ;   label the row's whole width
OPTROW_STRIDE = 32
OPTROW_LABEL  = 2
OPTROW_LABELW = 22
.include "presetcount.inc"      ; NGP_COUNT, from presets/*.toml
OPTROW_SETTINGS = 113           ; the settings, the randomization and the key items
NGROW_HEAD    = OPTROW_SETTINGS ; then the New Game list: its heading, a blank,
NGROW_CUSTOM  = NGROW_HEAD + 2  ;   Custom Game, and a row per preset
OPTROW_COUNT  = NGROW_CUSTOM + 1 + NGP_COUNT

;  The description pane: five lines of 28 columns.
DESC_W     = 28
DESC_LINES = 5

;  A description record is a line count and then that many lines, rather than
;  five lines padded with spaces.  Most of them are two or three, and the
;  padding came to 2.8KB in a bank that had none left -- this screen's own
;  section would not fit until it went.  opt_menu_desc blanks the rest of the
;  pane itself, which is a fill rather than a blit and so slightly cheaper
;  than writing the spaces was.
.macro FFLINES n
    .byte n
.endmacro

;  ...or, for a value row whose values mean different things, DESC_BYVALUE and
;  then a pointer to one record per value, so the pane describes the setting
;  as it stands rather than every setting it could be.  A line count is never
;  $FF, so the two cannot be confused.
DESC_BYVALUE = $FF

;  The settings screen's layout (optmenu.asm), which the seed screen's
;  description box and heading share.
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
VIEW_HAND_DX   = 12             ; the save view's hand, this much nearer its row
OPTMENU_ROWNUM = $72            ; which on-screen row is being drawn
OPTMENU_ADDR   = $73            ; 2 bytes: nametable address being built
OPTMENU_SCAN   = $75            ; row index while walking a section
OPTMENU_ALLSET = $76            ; was every checkbox in the section already on?
OPTMENU_VALPTR = $77            ; 2 bytes: into a value-readout table
OPTMENU_DESC   = $7A            ; 2 bytes: into the description text
OPTMENU_DLINES = $79            ; ...and how many of its lines are left;
                                ;   outside opt_menu_desc, scratch for
                                ;   opt_menu_descptr and opt_menu_drawrow

;  This screen does its own edge detection rather than using joy_a, joy_start
;  and joy_ignore.  Those are a counter per button plus a shared mask, updated
;  by ProcessJoyButtons and owned across screen transitions by whoever ran
;  last, and a held A was reaching this loop as a fresh press every frame.
;  Keeping the previous pad state here makes "newly pressed" a property of two
;  bytes this screen owns outright, and makes waiting for release trivial.
;  They are flags, not pointers, so they need no direct-page addressing --
;  which is just as well, as zero page $6E..$7B is now full.
;
;  In bank $7F (MENURAM), so long-addressed, since 2026-10-21.  They were in
;  the option page at $1A-$1F, and four of them, SHPREV, ANY, LEFT and WAS,
;  lay on four of the derived bytes (OPTD_LINEUP, _PALCYC, _MSGROWS and
;  _MSGROWSREV, OPTD+$07..$0A), which opt_derive writes only on a commit and
;  opt_init never: leaving this screen left them the screen's scratch,
;  in the battery, until the next commit.  OPTD_LINEUP read 0 after a visit,
;  and the lineup's slide steps by it until it passes its mark, so it would
;  never finish.  PREV and EDGE lay on the battle's OPTBTLSOFT and
;  OPTDRINKROW, which is scratch on scratch but moved all the same.
OPTMENU_PREV   = MENURAM + $00  ; the pad as it read last frame
OPTMENU_EDGE   = MENURAM + $01  ; buttons that went down this frame
OPTMENU_WAS    = MENURAM + $02  ; the row a left/right page started on
OPTMENU_LEFT   = MENURAM + $03  ; rows still to draw before the next breath
OPTMENU_ANY    = MENURAM + $04  ; did a section toggle find a checkbox at all?
OPTMENU_SHPREV = MENURAM + $05  ; L and R as they read last frame (h_joyaux's)
OPTMENU_BEGIN  = MENURAM + $06  ; the window onto lut_OptRows this screen shows:
OPTMENU_END    = MENURAM + $07  ;   its first row, and one past its last
OPTMENU_PICK   = MENURAM + $08  ; nonzero for a list of choices (the New Game
                                ;   list): only pick rows, and A or START picks
OPTMENU_VIEW   = OPTBLOCK + $31 ; nonzero while the save view runs (below)

;  joy's bit order, which ProcessJoyButtons documents by masking for it.
PAD_RIGHT = $01
PAD_LEFT  = $02
PAD_DOWN  = $04
PAD_UP    = $08
PAD_START = $10
PAD_B     = $40
PAD_A     = $80
