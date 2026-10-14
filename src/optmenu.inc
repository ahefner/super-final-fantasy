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
OPTROW_STRIDE = 32
OPTROW_LABEL  = 2
OPTROW_LABELW = 22
OPTROW_COUNT  = 104

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
