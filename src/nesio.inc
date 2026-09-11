;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;
;;  nesio.inc -- stand-ins for the NES hardware registers.
;;
;;  tools/convert.py rewrites every access to $2000-$2007 / $4000-$4017 in the
;;  original source into one of these macros.
;;
;;  Each one is a three-byte JSR, exactly the size of the store or load it
;;  replaces.  That matters: the sixteen NES banks are 16KB and full, so a
;;  four-byte JSL straight into the HAL bank would push several of them over.
;;  The JSR goes to a thunk in the fixed bank -- which every chunk carries a
;;  copy of -- and the thunk makes the long call.  See nesio_thunks.inc.
;;
;;  The write macros are completely transparent: A, X, Y and P come back
;;  exactly as they went in, so the surrounding 6502 code needs no other
;;  changes.  The read macros behave like the load they replace -- value in the
;;  named register, N and Z set from it, nothing else touched.
;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.ifndef NESIO_HOME              ; the fixed bank defines these rather than
;  Called straight from a patched routine rather than through a thunk, because
;  each replaces a whole loop rather than a single register access.  This block
;  is skipped in the fixed bank, which defines the thunks rather than importing
;  them, so anything the fixed bank's own patches call is imported in
;  nesio_thunks.inc instead -- hal_ntfill is, for the box rows.
.import hal_clearnt, hal_ntfill

.import nesio_w2000, nesio_w2001, nesio_w2001y                  ; importing them
.import nesio_r2002, nesio_r2002x, nesio_r2002y, nesio_b2002
.import nesio_w2005, nesio_w2006, nesio_w2006x, nesio_w2006y
.import nesio_w2007, nesio_w2007x, nesio_w2007y, nesio_r2007
.import nesio_oamdma, nesio_joystrobe, nesio_joyread, nesio_r4015
.import nesio_w4015, nesio_w4003, nesio_w4007, nesio_w400b, nesio_w400f
.import nesio_joystrobey, nesio_joystrobex
.endif

; ---- $2000 PPUCTRL / $2001 PPUMASK -------------------------------------
.macro wPPUCTRL
    jsr nesio_w2000
.endmacro
.macro wPPUMASK
    jsr nesio_w2001
.endmacro
.macro wPPUMASK_Y
    jsr nesio_w2001y
.endmacro

; ---- $2002 PPUSTATUS ---------------------------------------------------
.macro rPPUSTATUS
    jsr nesio_r2002
.endmacro
.macro rPPUSTATUS_X
    jsr nesio_r2002x
.endmacro
.macro rPPUSTATUS_Y
    jsr nesio_r2002y
.endmacro
.macro bPPUSTATUS
    jsr nesio_b2002
.endmacro

; ---- $2005 PPUSCROLL / $2006 PPUADDR -----------------------------------
.macro wPPUSCROLL
    jsr nesio_w2005
.endmacro
.macro wPPUADDR
    jsr nesio_w2006
.endmacro
.macro wPPUADDR_X
    jsr nesio_w2006x
.endmacro
.macro wPPUADDR_Y
    jsr nesio_w2006y
.endmacro

; ---- $2007 PPUDATA -----------------------------------------------------
.macro wPPUDATA
    jsr nesio_w2007
.endmacro
.macro wPPUDATA_X
    jsr nesio_w2007x
.endmacro
.macro wPPUDATA_Y
    jsr nesio_w2007y
.endmacro
.macro rPPUDATA
    jsr nesio_r2007
.endmacro

; ---- $4014 OAM DMA -----------------------------------------------------
.macro wOAMDMA
    jsr nesio_oamdma
.endmacro

; ---- $4000-$4013, $4015, $4017 pAPU ------------------------------------
;  Audio is not wired up yet.  Every write is recorded in a shadow copy of the
;  pAPU register file, so the eventual SPC700 driver has something to read and
;  nothing here can disturb CPU state: a plain absolute store touches no flags
;  and no registers, which is exactly what the original STA did.
;  $4015 turns channels on and off, and a transition writes it once to silence
;  everything before spending a dozen frames redrawing with no vblank wait in
;  them.  Send it to the SPC700 there and then; every other register can wait
;  for the frame, as the music driver rewrites those constantly.  The call to
;  the thunk is a JSR, exactly the size of the store it replaces, so none of
;  these banks -- which have almost no room -- grows by a byte.
.macro wAPU reg
    .if (reg) = $15
      jsr nesio_w4015
    .elseif (reg) = $03
      jsr nesio_w4003
    .elseif (reg) = $07
      jsr nesio_w4007
    .elseif (reg) = $0B
      jsr nesio_w400b
    .elseif (reg) = $0F
      jsr nesio_w400f
    .else
      sta a:APUSHADOW + (reg)
    .endif
.endmacro
.macro wAPU_X reg
    stx a:APUSHADOW + (reg)
.endmacro
.macro wAPU_Y reg
    sty a:APUSHADOW + (reg)
.endmacro
.macro rAPUSTATUS
    jsr nesio_r4015
.endmacro

; ---- $4016/$4017 controller ports --------------------------------------
.macro wJOYSTROBE
    jsr nesio_joystrobe
.endmacro
.macro wJOYSTROBE_Y
    jsr nesio_joystrobey
.endmacro
.macro wJOYSTROBE_X
    jsr nesio_joystrobex
.endmacro
.macro rJOYPAD
    jsr nesio_joyread
.endmacro
