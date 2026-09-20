; ---------------------------------------------------------------------------
;  optdata.asm -- fixed-bank data that does not need to be in the fixed bank.
;
;  The fixed bank is stamped into all sixteen chunks, so every byte in it is
;  spent sixteen times over.  It ran down to six bytes free.
;
;  Most of what is in there is code that has to be reachable whatever bank is
;  switched in.  Some of it is only *data* that has to be readable whatever
;  bank is switched in -- which on the NES meant the same thing, because a
;  6502 load can only name an address inside the current 64K.  The 65816 can
;  name a bank as well: "lda f:addr,x" reaches any of them, in emulation mode
;  too, for one extra byte and one extra cycle.
;
;  So these tables live here, in the options chunk, and the fixed bank reads
;  them long.  Four hundred and eleven bytes come back, and the only cost is
;  one byte at each of the five sites that read them.
;
;  Nothing here is code.  Do not put code here: it would run with the options
;  chunk selected, which is not what the callers expect.
; ---------------------------------------------------------------------------
.p816
.a8
.i8
.include "snesmap.inc"

.segment "BANK_OPT"

.export lut_DTE1, lut_DTE2, lut_BattleScramble, lut_ShopTypes

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  DTE table
;;
;;  First table is the second character in a DTE pair, second is the first.
;;  Don't ask Disch why it is reversed.  Eighty entries each, covering codes
;;  $1A-$69; the drawer treats $6A-$79 as DTE too and reads past the end,
;;  which it documents as drawing crap.  Keeping the two adjacent and in this
;;  order preserves exactly which crap.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_DTE2:
  .BYTE $FF,$B7,$AB,$A8,  $FF,$B1,$A4,$FF,  $B1,$A8,$B6,$B5,  $B8,$FF,$B2,$FF
  .BYTE $AA,$A4,$B6,$AC,  $FF,$B5,$B6,$A5,  $A8,$BA,$A8,$B5,  $B2,$B7,$A6,$B7
  .BYTE $B1,$A7,$B1,$AC,  $A8,$B6,$A7,$A4,  $B0,$A9,$FF,$A8,  $BA,$FF,$A8,$B0
  .BYTE $92,$FF,$A9,$B2,  $AF,$B3,$BC,$A4,  $8A,$A8,$FF,$B5,  $B2,$AC,$FF,$AB
  .BYTE $A8,$B7,$AC,$A4,  $A6,$AF,$A8,$AF,  $A8,$B6,$FF,$AF,  $A8,$A7,$AC,$C3

lut_DTE1:
  .BYTE $A8,$FF,$B7,$AB,  $B6,$AC,$FF,$B7,  $A4,$B5,$FF,$A8,  $B2,$A7,$B7,$B1
  .BYTE $B1,$A8,$A8,$FF,  $B2,$A4,$AC,$FF,  $B9,$FF,$B0,$B2,  $FF,$B6,$FF,$A4
  .BYTE $A8,$B1,$B2,$AB,  $B6,$A4,$A8,$AB,  $FF,$FF,$B5,$AF,  $B2,$AA,$A6,$B2
  .BYTE $90,$BC,$B2,$B5,  $AF,$FF,$FF,$A6,  $96,$B7,$A9,$B8,  $BC,$B7,$AF,$FF
  .BYTE $B1,$AC,$B5,$BA,  $A4,$A4,$BA,$AC,  $A5,$B5,$B8,$FF,  $AA,$FF,$AF,$C3

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  BattleRNG's scrambling table
;;
;;  The battle RNG has its own $100-byte lut rather than sharing lut_RNG at
;;  $F100 -- Disch could not work out why either.  ChaosDeath in bank $0B
;;  depends on 256 consecutive calls producing every value once, so the
;;  contents matter and must not be touched; only where they sit changes.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_BattleScramble:
    .INCBIN "../game/bin/0F_FCF1_rngtable.bin"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;  Which kind of shop each shop id is
;;
;;  Seventy-one bytes read from exactly one instruction, which makes it the
;;  cheapest thing in the fixed bank to move: one byte back at the read site
;;  against seventy recovered.  Moved when Chests Appear Opened overran the
;;  bank by fifty-six.
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

lut_ShopTypes:
   .BYTE $00,$00,$00,$00,$00,$00,$00,$00,$00,$00      ; 10 weapon shops (but first is unused)
   .BYTE $01,$01,$01,$01,$01,$01,$01,$01,$01,$01,$01  ; 11 armor shops (to correct the off-by-1 error)
   .BYTE $02,$02,$02,$02,$02,$02,$02,$02,$02,$02      ; 10 white magic
   .BYTE $03,$03,$03,$03,$03,$03,$03,$03,$03,$03      ; 10 black magic
   .BYTE $04,$04,$04,$04,$04,$04,$04,$04,$04,$04      ; 10 clinics
   .BYTE $05,$05,$05,$05,$05,$05,$05,$05,$05,$05      ; 10 inns
   .BYTE $06,$06,$06,$06,$06,$06,$06,$06,$06,$07      ; 9 item shops + 1 caravan
 
