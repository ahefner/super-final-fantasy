;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  fftext.inc -- write the game's text encoding as readable strings.
;;
;;  The game's character set is not ASCII: digits start at $80, capitals at
;;  $8A, lowercase at $A4, and space is $FF.  The options menu's labels were
;;  hand-encoded a byte at a time with the English in a comment, which is
;;  fine for thirty-eight rows written once and awful for a table that gets
;;  edited.  These macros do the conversion at assembly time.
;;
;;  Only the characters the game actually has glyphs for are accepted; a
;;  stray one is an assembly error rather than a wrong tile on screen.
;;
;;  That list is shorter than it looks.  LoadMenuCHR loads eight rows to PPU
;;  $0800, which is tiles $80-$FF, so the font IS $80-$FF and nothing else.
;;  FFR's table has "/" at $7A and "+" at $7B, and both are drawn literally
;;  by DrawComplexString -- but they are below the loaded range and come out
;;  as whatever else is in the pattern table, which is kana.  The stock font
;;  has no plus sign at all, so mkrom draws one over an unused kana at $E6
;;  and "+" maps there.  $C1 is in range but blank, and $C6/$C7 are the
;;  Level and Equip icons rather than letters.
;;
;;  Everything emitted lands at $80 or above, which matters: DrawComplexString
;;  reads $01-$19 as control codes and $1A-$79 as DTE pairs, so text that
;;  strays below $7A draws something other than itself.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.macro FFCHAR c
  .if c = ' '
    .byte $FF
  .elseif (c >= '0') .and (c <= '9')
    .byte c + ($80 - '0')
  .elseif (c >= 'A') .and (c <= 'Z')
    .byte c + ($8A - 'A')
  .elseif (c >= 'a') .and (c <= 'z')
    .byte c + ($A4 - 'a')
  .elseif c = 39            ; apostrophe
    .byte $BE
  .elseif c = ','
    .byte $BF
  .elseif c = '.'
    .byte $C0
  .elseif c = '-'
    .byte $C2
  .elseif c = '!'
    .byte $C4
  .elseif c = '?'
    .byte $C5
  .elseif c = '%'
    .byte $E0
  .elseif c = '+'           ; not in the stock font; mkrom draws one here
    .byte $E6
  .else
    .error "no glyph for this character"
  .endif
.endmacro

;  The string, with no terminator.  Callers that need one add it, because
;  most of these strings are fragments joined at run time.
.macro FFTEXT txt
  .repeat .strlen(txt), i
    FFCHAR {.strat(txt, i)}
  .endrep
.endmacro

;  The string padded with spaces to a fixed width, for tables indexed by
;  arithmetic.  Assembling is the only place the width can be checked.
.macro FFPAD txt, wid
  .if .strlen(txt) > wid
    .error "string longer than its field"
  .endif
  FFTEXT txt
  .repeat wid - .strlen(txt)
    .byte $FF
  .endrep
.endmacro

;  Note on parameter names: 'S' is the stack-relative register designator in
;  65816 mode, so a macro parameter called 's' makes ca65 reject the .macro
;  line itself with a message that points nowhere useful.

;  A length-prefixed word, for tables the renderer walks at run time.
.macro FFWORD txt
  .byte .strlen(txt)
  FFTEXT txt
.endmacro
