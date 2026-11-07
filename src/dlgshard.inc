;  dlgshard.inc -- Shard Hunt's lines (user, 2026-11-06: the Black Orb's and
;  Chaos's, FFR's, BlackOrb.cs's EnableShardHunt; the opening story left as
;  it is).  Under a shard Goal, rando_dlgtext asks shard_line before drawing
;  a line: the Black Orb's giving way ($21) and Chaos's three ($2E-$30) are
;  swapped for these, built in OPTDESC like the princess's.  Included by
;  world.asm.

SHARD_DLGPTR = (CHUNK0 + BANK_DIALOGUE) * $10000 + lut_DialoguePtrTbl

;;  Is text_ptr one of the lines Shard Hunt rewrites?  Under a shard Goal, C
;;  set, text_ptr's low byte this chunk's line and A its high byte, for
;;  rando_dlgtext's @worldline; else C clear.  Emulation mode, A8 I8, by JSL.
;;  X clobbered; Y kept.
shard_line:
    .a8
    .i8
    LDA f:RANDO_SAVEFAR + (RANDO_GOAL - RANDO_SAVE)
    CMP #GOAL_SHARD0
    BCC @no
    PHY
    LDY #SHARD_NLINES - 1
  @look:
    TYX
    LDA f:WORLDFAR + lut_ShardDlgId, X
    ASL A
    TAX
    LDA f:SHARD_DLGPTR, X
    CMP text_ptr
    BNE @next
    LDA f:SHARD_DLGPTR + 1, X
    CMP text_ptr+1
    BEQ @hit
  @next:
    DEY
    BPL @look
    PLY
  @no:
    CLC
    RTL
  @hit:
    TYX
    PLY
    LDA f:WORLDFAR + lut_ShardDlgLo, X
    STA text_ptr
    LDA f:WORLDFAR + lut_ShardDlgHi, X
    SEC
    RTL

lut_ShardDlgId: .BYTE $21, $2E, $2F, $30
SHARD_NLINES = * - lut_ShardDlgId
.assert $30 < $80, error, "shard_line reads the pointer table's first page"
lut_ShardDlgLo: .BYTE <lut_ShardOrbLine, <lut_ShardChaos1, <lut_ShardChaos2, <lut_ShardChaos3
lut_ShardDlgHi: .BYTE >lut_ShardOrbLine, >lut_ShardChaos1, >lut_ShardChaos2, >lut_ShardChaos3

lut_ShardOrbLine:  ; $21, the Black Orb giving way
  FFTEXT "The SHARDS coalesce to"
  .BYTE DLG_NL
  FFTEXT "restore the Black ORB."
  .BYTE DLG_NL, DLG_NL
  FFTEXT "Brave Light Warriors...."
  .BYTE DLG_NL
  FFTEXT "Destroy the Evil within!"
  .BYTE $00
lut_ShardChaos1:  ; $2E
  FFTEXT "Ah, the Light Warriors!"
  .BYTE DLG_NL, DLG_NL
  FFTEXT "So you have collected"
  .BYTE DLG_NL
  FFTEXT "the SHARDS and restored"
  .BYTE DLG_NL
  FFTEXT "the BLACK ORB."
  .BYTE $00
lut_ShardChaos2:  ; $2F
  FFTEXT "Thus you've travelled"
  .BYTE DLG_NL
  FFTEXT "2000 years into the past"
  .BYTE DLG_NL
  FFTEXT "to try to stop me?"
  .BYTE DLG_NL, DLG_NL
  FFTEXT "Step forward then,"
  .BYTE DLG_NL
  FFTEXT "to your peril!"
  .BYTE $00
lut_ShardChaos3:  ; $30
  FFTEXT "Oh, Light Warriors!"
  .BYTE DLG_NL
  FFTEXT "Such arrogant bravery."
  .BYTE DLG_NL, DLG_NL
  FFTEXT "Let us see whom history"
  .BYTE DLG_NL
  FFTEXT "remembers. En Garde!"
  .BYTE $00
lut_ShardDlgEnd:
.assert lut_ShardChaos1 - lut_ShardOrbLine <= OPTDLG_MAX, error, "a Shard Hunt line overflows OPTDESC"
.assert lut_ShardChaos2 - lut_ShardChaos1 <= OPTDLG_MAX, error, "a Shard Hunt line overflows OPTDESC"
.assert lut_ShardChaos3 - lut_ShardChaos2 <= OPTDLG_MAX, error, "a Shard Hunt line overflows OPTDESC"
.assert lut_ShardDlgEnd - lut_ShardChaos3 <= OPTDLG_MAX, error, "a Shard Hunt line overflows OPTDESC"
