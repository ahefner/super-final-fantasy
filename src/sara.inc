;  sara.inc -- Rebellious Princess on the maps (user, 2026-11-02,
;  rebellious-princess.txt): the kidnapped princess at pl_sara's spot,
;  RW_SARA, 0 being Garland's, where the game has her.  Included by
;  world.asm, out of the randomizer's chunk, which is full.  Her graphic
;  needs nothing: the free slot she takes loads object 0's, which is the
;  kidnapped princess's (lut_MapObjGfx; test_princess).
;
;  Each spot's map, her x with her flags (standing; in a room where the room
;  is one), her y, and a slot the map leaves empty (worldgraph/romdata.py's
;  PRINCESS_SPOTS, graphdata.SARA_AT; test_princess).

MAP_TOF          = 12
MAP_CRESCENT     = 4
SARA_TOFSLOT     = 1            ; hers in the Temple of Fiends' list
lut_SaraMap:  .BYTE MAP_TOF, 19, 9, MAP_CRESCENT, 21, 16, 1, 3
lut_SaraXF:   .BYTE 20 | $C0, 8 | $C0, 6 | $C0, 39 | $40, 8 | $C0, 28 | $40, 6 | $40, 17 | $40
lut_SaraY:    .BYTE 18, 2, 5, 7, 2, 16, 7, 12
lut_SaraSlot: .BYTE SARA_TOFSLOT, 13, 8, 14, 1, 9, 8, 14
.assert * - lut_SaraSlot = SARA_SPOTS, error, "a slot per spot"
;  Crescent Lake's sages, by slot: the circle, the Canoe Sage among them
;  (FFR's ConfusedOldMen's: slots 0-10 and 12).
lut_SaraSage: .BYTE 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0

;;  After LoadMapObjects, from rando_tofrplate: in the Temple of Fiends her
;;  slot emptied; on her spot's map she is loaded into her slot through the
;;  game's own LoadSingleMapObject, so she is there exactly while her game
;;  flag says -- until she is found; and at Crescent Lake the sages set
;;  loose (user: "just set them loose"), standing no more.  Emulation mode,
;;  A8 X8, by JSL.  A, X, Y clobbered.
rando_saraobjects:
    .a8
    .i8
    LDA f:RANDO_SAVEFAR + (RANDO_RNG - RANDO_SAVE)
    AND #PRINCESS_FIELD
    BEQ @out
    LDA f:RW_SARA
    BEQ @out
    TAX                         ; X = her spot
    PHB
    LDA #CHUNK0                 ; a bank that decodes the zero page and mapobj
    PHA
    PLB
    LDA cur_map
    CMP #MAP_TOF
    BNE @there
    LDA #$00
    STA mapobj + SARA_TOFSLOT * 16
  @there:
    LDA cur_map
    CMP f:WORLDFAR + lut_SaraMap, X
    BNE @done
    LDA #OBJID_PRINCESS_1
    STA tmp+8
    LDA f:WORLDFAR + lut_SaraXF, X
    STA tmp+9
    LDA f:WORLDFAR + lut_SaraY, X
    STA tmp+10
    LDA #<(tmp+8)
    STA tmp+12
    LDA #>(tmp+8)
    STA tmp+13
    LDA f:WORLDFAR + lut_SaraSlot, X
    ASL A
    ASL A
    ASL A
    ASL A
    CLC
    ADC #<mapobj
    STA tmp+14
    LDA #>mapobj
    ADC #$00
    STA tmp+15
    LDA #OBJID_PRINCESS_1
    JSR LoadSingleMapObject     ; the fixed bank's, in every chunk
    LDA cur_map
    CMP #MAP_CRESCENT
    BNE @done
    LDX #$00                    ; X = the slot
    LDY #$00                    ; Y = its record
  @sage:
    LDA f:WORLDFAR + lut_SaraSage, X
    BEQ @next
    LDA mapobj + 1, Y
    AND #<~$40                  ; standing no more
    STA mapobj + 1, Y
  @next:
    TYA
    CLC
    ADC #16
    TAY
    INX
    CPX #15
    BCC @sage
  @done:
    PLB
  @out:
    RTL
