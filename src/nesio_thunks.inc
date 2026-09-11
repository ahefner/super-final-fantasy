;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  nesio_thunks.inc -- included once, at the end of the fixed bank.
;;
;;  A rewritten hardware access has to be three bytes, because the NES banks
;;  are exactly full.  These thunks are what makes that possible: the call site
;;  JSRs here, and here is where the four-byte long call into the HAL bank
;;  happens.  The fixed bank is copied into all sixteen chunks, so they are
;;  reachable no matter which bank is switched in.
;;
;;  Everything below is transparent -- JSL, RTL and RTS all leave the flags
;;  alone, so a write thunk disturbs nothing and a read thunk lets the HAL's
;;  final load set N and Z.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.import hal_w2000, hal_w2001, hal_r2002, hal_r2002x, hal_r2002y, hal_b2002
.import hal_w2005, hal_w2006, hal_w2007, hal_r2007
.import hal_oamdma, hal_joystrobe, hal_joyread, hal_r4015
.import hal_swapprg, hal_waitvbl, hal_joyupdate, hal_waitscanline, hal_waitline9   ; used by the patched routines
.import hal_wipewindow, hal_chrload, hal_drawattr
.import hal_ntfill                ; the box rows call it directly; see nesio.inc
.import hal_w4015, hal_w4003, hal_w4007, hal_w400b, hal_w400f ; see nesio.inc

.export nesio_w2000, nesio_w2001, nesio_w2001y
.export nesio_r2002, nesio_r2002x, nesio_r2002y, nesio_b2002
.export nesio_w2005, nesio_w2006, nesio_w2006x, nesio_w2006y
.export nesio_w2007, nesio_w2007x, nesio_w2007y, nesio_r2007
.export nesio_oamdma, nesio_joystrobe, nesio_joyread, nesio_r4015
.export nesio_w4015, nesio_w4003, nesio_w4007, nesio_w400b, nesio_w400f
.export nesio_joystrobey, nesio_joystrobex

.macro NESIO_THUNK name, target
name:
    jsl target + HALFAR
    rts
.endmacro

;;  ...and the same, for the handful of sites that stored X or Y instead of A.
.macro NESIO_THUNK_X name, target
name:
    php
    pha
    txa
    jsl target + HALFAR
    pla
    plp
    rts
.endmacro

.macro NESIO_THUNK_Y name, target
name:
    php
    pha
    tya
    jsl target + HALFAR
    pla
    plp
    rts
.endmacro

    NESIO_THUNK   nesio_w4015,     hal_w4015
    NESIO_THUNK   nesio_w4003,     hal_w4003
    NESIO_THUNK   nesio_w4007,     hal_w4007
    NESIO_THUNK   nesio_w400b,     hal_w400b
    NESIO_THUNK   nesio_w400f,     hal_w400f
    NESIO_THUNK   nesio_w2000,     hal_w2000
    NESIO_THUNK   nesio_w2001,     hal_w2001
    NESIO_THUNK_Y nesio_w2001y,    hal_w2001
    NESIO_THUNK   nesio_r2002,     hal_r2002
    NESIO_THUNK   nesio_r2002x,    hal_r2002x
    NESIO_THUNK   nesio_r2002y,    hal_r2002y
    NESIO_THUNK   nesio_b2002,     hal_b2002
    NESIO_THUNK   nesio_w2005,     hal_w2005
    NESIO_THUNK   nesio_w2006,     hal_w2006
    NESIO_THUNK_X nesio_w2006x,    hal_w2006
    NESIO_THUNK_Y nesio_w2006y,    hal_w2006
    NESIO_THUNK   nesio_w2007,     hal_w2007
    NESIO_THUNK_X nesio_w2007x,    hal_w2007
    NESIO_THUNK_Y nesio_w2007y,    hal_w2007
    NESIO_THUNK   nesio_r2007,     hal_r2007
    NESIO_THUNK   nesio_oamdma,    hal_oamdma
    NESIO_THUNK   nesio_joystrobe, hal_joystrobe
    NESIO_THUNK_Y nesio_joystrobey, hal_joystrobe
    NESIO_THUNK_X nesio_joystrobex, hal_joystrobe
    NESIO_THUNK   nesio_joyread,   hal_joyread
    NESIO_THUNK   nesio_r4015,     hal_r4015
