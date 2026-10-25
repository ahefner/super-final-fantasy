; ---------------------------------------------------------------------------
;  goal.inc -- the Goal in the logic: Chaos reached with as many orbs as the
;  Goal asks (RANDO_GOAL).  For both checks that ask whether Chaos is
;  reached, placement's (pl_attempt, place.inc) and the map edit screen's
;  (rando_winnable, entrance.inc), so that neither finds a world won that the
;  other finds lost (user, 2026-10-24: "it's easy to remove the airship ...
;  have the game claim the flagset is unwinnable, and then complain that it's
;  a bug (which it is)").
;
;  The orbs come into Chaos's masks all four together, from the one thing in
;  the world that asks for them: the Black Orb and the tile beneath it
;  (worldgraph's GATE_ROUTINE and GATE_TILE), which ask the Goal's orbs now
;  (opt_orbgoal, orbportal.patch).  So a mask holding all four is a way in
;  through the Black Orb, met with its orbs aside once enough are held --
;  lit + waived >= GOAL_ORBS, opt_orbgoal's own test -- and a mask without
;  them, a way round the orb that a shuffle may make, is met as it is.  The
;  game's four orbs give the answer they always gave.  Places beyond the
;  Black Orb still count all four in their own masks: a little strict for a
;  smaller Goal, never wrong.
; ---------------------------------------------------------------------------

LOGIC_ORBS_HI = ((1 << LBIT_ORB_EARTH) | (1 << LBIT_ORB_FIRE) | (1 << LBIT_ORB_WATER) | (1 << LBIT_ORB_AIR)) >> 16
.assert LOGIC_ORBS_HI = $0F00, error, "goal.inc takes the orbs as bits 8-11 of a mask's high word"
.assert GOAL_MODES = GOAL_ORBS + 1, error, "goal.inc counts orbs only: a goal past them needs its own test"

;;  Y = 1 if A, the high word of what is held (bits 16-31), has the Goal's
;;  orbs; else 0.  far is the including chunk's own, for lut_OrbCount (put
;;  there with GOAL_TABLE).  X clobbered.  A16 I16, out the same.
.macro GOAL_HELD far
    AND #LOGIC_ORBS_HI
    XBA                         ; the four, bits 0-3
    TAX
    SEP #$20
    .a8
    LDA f:far + lut_OrbCount, X ; lit...
    CLC
    ADC f:RANDO_SAVEFAR + (RANDO_GOAL - RANDO_SAVE)   ; ...and waived
    CMP #GOAL_ORBS
    REP #$20
    .a16
    LDA #0
    ROL A
    TAY
.endmacro

;;  How many bits of a nybble are set.
.macro GOAL_TABLE
lut_OrbCount:
  .BYTE 0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4
.endmacro
