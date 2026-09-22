;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  optcall.inc -- calling a routine in bank $0E from the options chunk.
;;
;;  A chunk sees its own NES bank at $8000, so a routine in bank $0E cannot be
;;  reached with a JSR from here.  OptCallFar is a trampoline in that bank:
;;  the JSL lands with the program bank set to it, the JSR inside reaches the
;;  routine normally, and the RTL comes back.  The address to jump to is left
;;  in OPTCALLV, so one trampoline serves every routine rather than needing a
;;  table of them -- which matters, as bank $0E has ten bytes left.
;;
;;  OptCallFar passes A, X and Y through, but setting the address needs A, so
;;  a routine that takes a parameter in A has to be called with CALL0EA, which
;;  loads it afterwards.
;;
;;  Both files that assemble into BANK_OPT use these, so they live here rather
;;  than in whichever one happened to need them first.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.macro SET0E addr
    LDA #<addr
    STA OPTCALLV
    LDA #>addr
    STA OPTCALLV+1
.endmacro

.macro CALL0E addr
    SET0E addr
    JSL OptCallFar + BANK0EFAR
.endmacro

.macro CALL0EA addr, val
    SET0E addr
    LDA #val
    JSL OptCallFar + BANK0EFAR
.endmacro
