;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  header.asm -- SNES cartridge header and vectors, at $C0:FFC0.
;;
;;  No interrupt is ever enabled in this port: the game's WaitForVBlank polls
;;  $4212 instead, which sidesteps the fact that a 65816 in emulation mode
;;  loses the program bank when it takes an interrupt.  Every vector but RESET
;;  therefore points at an RTI that should never run.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.p816
.include "snesmap.inc"

.import hal_reset
.export hal_stub

.segment "HALCODE"
hal_stub:
    rti

.segment "SNESHDR"
;;  $FFB0: the extended header.  Setting the developer ID at $FFDA to $33 is
;;  what declares it present, and emulators lean on these fields when they are
;;  deciding whether an image is LoROM or HiROM -- a bare $FFC0 header leaves
;;  the guess closer than it needs to be.
    .byte "01"                  ; $FFB0 maker code
    .byte "FFSN"                ; $FFB2 game code
    .byte $00, $00, $00, $00, $00, $00      ; $FFB6 reserved
    .byte $00                   ; $FFBC expansion flash size
    .byte $00                   ; $FFBD expansion RAM size
    .byte $00                   ; $FFBE special version
    .byte $00                   ; $FFBF cartridge sub-type

    .byte "FINAL FANTASY SNES   "   ; $FFC0 title, 21 bytes
    .byte $31                   ; $FFD5 HiROM, FastROM
    .byte $02                   ; $FFD6 ROM + RAM + battery
    .byte $0B                   ; $FFD7 2048 KB
    .byte $04                   ; $FFD8 16 KB of SRAM
    .byte $01                   ; $FFD9 NTSC / North America
    .byte $33                   ; $FFDA developer: extended header present
    .byte $00                   ; $FFDB version
    .word $0000                 ; $FFDC checksum complement, filled by build.sh
    .word $0000                 ; $FFDE checksum

                                ; $FFE0: native mode vectors
    .word hal_stub, hal_stub    ;   -     -
    .word hal_stub              ;   COP
    .word hal_stub              ;   BRK
    .word hal_stub              ;   ABORT
    .word hal_stub              ;   NMI
    .word hal_stub              ;   RESET (unused in native mode)
    .word hal_stub              ;   IRQ

                                ; $FFF0: emulation mode vectors
    .word hal_stub, hal_stub    ;   -     -
    .word hal_stub              ;   COP
    .word hal_stub              ;   -
    .word hal_stub              ;   ABORT
    .word hal_stub              ;   NMI
    .word hal_reset             ;   RESET
    .word hal_stub              ;   IRQ
