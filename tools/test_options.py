#!/usr/bin/env python3
"""
test_options.py -- run the option hooks and check what they answer.

The option code is mostly arithmetic over the option block and a few game
variables: which speed this step uses, what a map's encounter rate scales to,
which bit a flag lives in, whether a block checksums.  None of it draws
anything, so none of it needs a console -- it needs a 65816 and the built ROM,
which is what tools/cpu65816.py provides.

This does not test the menu, the drawing or anything that touches the PPU.  It
tests the part where a mistake is silent, which is the part that is otherwise
only found by playing far enough to notice.

    ./build.sh && python3 tools/test_options.py

To check the tests still bite, corrupt a table in the loaded image and confirm
a failure appears.  Search the *upper* half of a chunk when you do: mkrom
mirrors $8000-$FFFF into the low half of every chunk, and that copy is never
addressed, so mutating it proves nothing.  Changing lut_EncDungeonN's vanilla
numerator from 16 to 15 should fail four of the five live base rates.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from cpu65816 import Bus, CPU

ROM = os.path.join(ROOT, "SuperFinalFantasy.sfc")
LABELS = os.path.join(ROOT, "out", "labels.txt")

OPTBLOCK = 0x6E00
OPT_MAGIC0, OPT_MAGIC1, OPT_VERSION, OPT_PRESET = 0, 1, 2, 3
OPT_FLAGS, OPT_GOLDXP, OPT_ENCOUNTER = 4, 8, 9
OPT_ENEMY, OPT_BOSS, OPT_RESPOND, OPT_CKSUM = 10, 11, 12, 13
OPT_SIZE = 14
CHUNK_OPT_BANK = 0xA1 + 0x11
BANK_0E = 0xA1 + 0x0E          # chunk N runs at PBR $A1+N, so NES bank $0E is $AF
CUR_BANK = 0x57                # the bank SwapPRG returns to

fails = []


def labels():
    #  Regenerate whenever the ROM is newer.  A stale label file does not fail
    #  cleanly: every address is slightly wrong and the tests report a dozen
    #  unrelated crashes in banks that were never touched.
    if (not os.path.exists(LABELS)
            or os.path.getmtime(LABELS) < os.path.getmtime(ROM)):
        subprocess.run(["ld65", "-C", "snes.cfg", "-o", "/dev/null", "-Ln", LABELS]
                       + [os.path.join("out", f) for f in sorted(os.listdir("out"))
                          if f.endswith(".o")], cwd=ROOT, check=True)
    out = {}
    for line in open(LABELS):
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "al":
            out[parts[2].lstrip(".")] = int(parts[1], 16)
    return out


SYM = labels()
ROMDATA = open(ROM, "rb").read()


def machine():
    bus = Bus(ROMDATA)
    cpu = CPU(bus)
    cpu.dbr = 0xA7                  # a game chunk, as GameStart leaves it
    return bus, cpu


def call(cpu, name, bank=None, dbr=None):
    """Run a routine.  dbr matters: a routine that reads a table in the options
    bank needs DBR pointing there, which is the rule optbank.asm states and
    which opt_init observes with PHB / PHK / PLB.  Routines reached by JSR from
    the fixed bank run with whatever the game left."""
    addr = SYM[name]
    if bank is None:
        bank = CHUNK_OPT_BANK if addr < 0xC000 else 0xA7
    if dbr is not None:
        cpu.dbr = dbr
    cpu.run(bank, addr)


def check(what, got, want):
    if got != want:
        fails.append("%-46s got %r, want %r" % (what, got, want))


def blk(bus, off):
    return bus.sram[OPTBLOCK - 0x6000 + off]


def setblk(bus, off, v):
    bus.sram[OPTBLOCK - 0x6000 + off] = v


def flags(bus):
    return int.from_bytes(bus.sram[OPTBLOCK - 0x6000 + OPT_FLAGS:][:4], "little")


# --- the option block -------------------------------------------------------
def test_block():
    #  A cartridge with nothing in it comes up on the default preset, sealed.
    bus, cpu = machine()
    call(cpu, "opt_init")
    check("fresh cart: magic", (blk(bus, OPT_MAGIC0), blk(bus, OPT_MAGIC1)), (0x53, 0x46))
    check("fresh cart: version", blk(bus, OPT_VERSION), 0x02)
    check("fresh cart: preset is Improved", blk(bus, OPT_PRESET), 1)
    check("fresh cart: respond rate 8 (0-based)", blk(bus, OPT_RESPOND), 7)

    #  ...and a sealed block is left alone on the next boot.
    before = bytes(bus.sram[OPTBLOCK - 0x6000:][:OPT_SIZE])
    setblk(bus, OPT_PRESET, 2)              # something only a rewrite would undo
    bus2, cpu2 = machine()
    bus2.sram[:] = bus.sram
    call(cpu2, "opt_commit")                # reseal after our edit
    cpu3 = CPU(bus2); cpu3.dbr = 0xA7
    call(cpu3, "opt_init")
    check("valid block is not overwritten", blk(bus2, OPT_PRESET), 2)

    #  A single flipped bit must fail the checksum and reset to the default.
    bus3, cpu4 = machine()
    bus3.sram[:] = bus2.sram
    setblk(bus3, OPT_FLAGS, blk(bus3, OPT_FLAGS) ^ 0x01)
    cpu5 = CPU(bus3); cpu5.dbr = 0xA7
    call(cpu5, "opt_init")
    check("corrupt block resets to default", blk(bus3, OPT_PRESET), 1)

    #  A stale format is treated as absent even though it checksums.
    bus4, cpu6 = machine()
    bus4.sram[:] = bus2.sram
    setblk(bus4, OPT_VERSION, 0x01)
    cpu7 = CPU(bus4); cpu7.dbr = 0xA7
    call(cpu7, "opt_commit")                # valid checksum, old version
    cpu8 = CPU(bus4); cpu8.dbr = 0xA7
    call(cpu8, "opt_init")
    check("stale version is retired", blk(bus4, OPT_VERSION), 0x02)
    check("stale version resets preset", blk(bus4, OPT_PRESET), 1)


def test_presets():
    want = {0: (0x00000000, 2, 10, 3, 3),
            1: (0x0007BFFF, 2, 10, 3, 3),
            2: (0x03FFFFFF, 5, 6, 3, 3)}
    for preset, (f, g, e, en, bo) in want.items():
        bus, cpu = machine()
        cpu.a = preset
        #  as opt_init leaves it before its JSR to this routine
        call(cpu, "opt_loadpreset", dbr=CHUNK_OPT_BANK)
        name = ("Vanilla", "Improved", "Deluxe")[preset]
        check("%s: flags" % name, "$%08X" % flags(bus), "$%08X" % f)
        check("%s: gold/xp step" % name, blk(bus, OPT_GOLDXP), g)
        check("%s: encounter step" % name, blk(bus, OPT_ENCOUNTER), e)
        check("%s: enemy step" % name, blk(bus, OPT_ENEMY), en)
        check("%s: boss step" % name, blk(bus, OPT_BOSS), bo)
        #  loadpreset seals as it goes, so init must accept what it wrote
        cpu2 = CPU(bus); cpu2.dbr = 0xA7
        call(cpu2, "opt_init")
        check("%s: seals a valid block" % name, blk(bus, OPT_PRESET), preset)


# --- the feature hooks ------------------------------------------------------
OPTF_FASTWALK, OPTF_FASTSHIP = 0x02, 0x04
PAD_B = 0x40
MAPFLAGS, VEHICLE, JOY = 0x2D, 0x42, 0x20      # from game/variables.inc


def movespeed(flagbyte, mapflags, vehicle, joy=0):
    bus, cpu = machine()
    setblk(bus, OPT_FLAGS, flagbyte)
    bus.wram[MAPFLAGS] = mapflags
    bus.wram[VEHICLE] = vehicle
    bus.wram[JOY] = joy
    call(cpu, "opt_movespeed")
    return cpu.a & 0xFF


def test_movespeed():
    #  Vanilla: walking 1, canoe 1, ship 2, airship 4; standard maps always 1.
    for veh, want in ((1, 1), (2, 1), (4, 2), (8, 4)):
        check("vanilla speed, vehicle %d" % veh, movespeed(0, 0, veh), want)
    check("vanilla speed in a standard map", movespeed(0, 1, 8), 1)

    #  Faster Walking doubles anything that moved at walking pace.
    for veh, want in ((1, 2), (2, 2), (4, 2), (8, 4)):
        check("fast walk, vehicle %d" % veh, movespeed(OPTF_FASTWALK, 0, veh), want)
    check("fast walk in a standard map", movespeed(OPTF_FASTWALK, 1, 8), 2)

    #  Faster Ship raises only the ship.
    for veh, want in ((1, 1), (2, 1), (4, 4), (8, 4)):
        check("fast ship, vehicle %d" % veh, movespeed(OPTF_FASTSHIP, 0, veh), want)

    #  Holding B halves it, and never below one.
    check("B halves the airship", movespeed(0, 0, 8, PAD_B), 2)
    check("B halves a fast walk", movespeed(OPTF_FASTWALK, 0, 1, PAD_B), 1)
    check("B cannot take walking below 1", movespeed(0, 0, 1, PAD_B), 1)


def test_encounter():
    OW = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30]
    OC = [0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 5, 6, 9]
    for step in range(14):
        for veh, want in ((1, OW[step]), (4, OC[step]), (8, OW[step])):
            bus, cpu = machine()
            setblk(bus, OPT_ENCOUNTER, step)
            bus.wram[VEHICLE] = veh
            call(cpu, "opt_owrate")
            check("owrate step %d vehicle %d" % (step, veh), cpu.a & 0xFF, want)

    #  Step 10 is vanilla and must reproduce the original bytes exactly, for
    #  every base rate the game actually uses.
    BATTLERATE = 0xF8
    for base in (8, 9, 10, 11, 12, 24):
        bus, cpu = machine()
        setblk(bus, OPT_ENCOUNTER, 10)
        cpu.a = base
        call(cpu, "opt_setbattlerate")
        check("step 10 leaves base %d alone" % base, bus.wram[BATTLERATE], base)

    #  And nothing live is scaled to zero at the lowest nonzero setting.
    for base in (8, 9, 10, 11, 12, 24):
        bus, cpu = machine()
        setblk(bus, OPT_ENCOUNTER, 1)
        cpu.a = base
        call(cpu, "opt_setbattlerate")
        got = bus.wram[BATTLERATE]
        if got < 1:
            fails.append("step 1 zeroed base %d" % base)
    #  Off really is off.
    bus, cpu = machine()
    setblk(bus, OPT_ENCOUNTER, 0)
    cpu.a = 8
    call(cpu, "opt_setbattlerate")
    check("step 0 is off", bus.wram[BATTLERATE], 0)


OPTF_NOSHUFFLE = 0x08
STR_BUF = 0x0300


EXPLODE_COUNT, BTL_RESPONDDELAY = 0x6D18, 0x6BAC


def test_battlespeed():
    """The two setters take the vanilla value in A and either keep it or
    substitute the fast one."""
    for name, addr, vanilla, fast in (("opt_explodecount", EXPLODE_COUNT, (6, 8, 15), 4),
                                      ("opt_responddelay", BTL_RESPONDDELAY, (15,), 4)):
        for v in vanilla:
            for flag, want in ((0, v), (OPTF_SPEEDHACKS, fast)):
                bus, cpu = machine()
                setblk(bus, OPT_FLAGS, flag)
                cpu.a = v
                call(cpu, name, dbr=CHUNK_OPT_BANK)
                got = bus.sram[addr - 0x6000] if addr >= 0x6000 else bus.wram[addr]
                check("%s in=%d speedhacks=%d" % (name, v, flag), got, want)


def test_noshuffle():
    #  ChkAliveX/Y report the real value when the flag is clear, and "alive"
    #  when it is set -- which is what lets the lineup menu allow the swap.
    for name, reg in (("opt_chkalivex", "x"), ("opt_chkalivey", "y")):
        for flag, stored, want in ((0, 0x11, 0x11), (0, 0, 0),
                                   (OPTF_NOSHUFFLE, 0x11, 0)):
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.wram[STR_BUF + 3] = stored
            setattr(cpu, reg, 3)
            call(cpu, name, dbr=CHUNK_OPT_BANK)
            check("%s flag=%d stored=$%02X" % (name, flag, stored), cpu.a & 0xFF, want)
            check("%s sets Z for the branch" % name,
                  bool(cpu.p & 0x02), want == 0)


OPTF_SPEEDHACKS, OPTF_GUILLOTINE_HI = 0x01, 0x40
OPTD = 0x10                                  # derived bytes, just past the block
TMP = 0x10                                   # game's tmp, from variables.inc


def test_derive():
    """The cooked wipe steps, and that they still divide their totals."""
    for flag, want in ((0, (2, 4, 2, 4, 2, 3, 0x41, 1, 3, 1, 2)),
                       (OPTF_SPEEDHACKS, (8, 16, 10, 20, 11, 11, 0x11, 4, 0, 2, 3))):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS, flag)
        call(cpu, "opt_derive", dbr=CHUNK_OPT_BANK)
        got = tuple(blk(bus, OPTD + i) for i in range(11))
        check("derived constants, speedhacks=%d" % flag, got, want)
        #  The battle transition plays a $20-frame noise sweep; a transition
        #  shorter than that leaves the sound running past the picture, which
        #  is deliberate, but it must not be zero or the effect never draws.
        check("battle transition is nonzero, speedhacks=%d" % flag,
              got[6] > 0, True)
        #  The dialogue box grows from 8 to $60 and retracts past $12; a step
        #  larger than the span would skip the animation entirely.
        check("dialogue open step fits the span, speedhacks=%d" % flag,
              got[4] <= 0x60 - 0x08, True)
        check("dialogue close step fits the span, speedhacks=%d" % flag,
              got[5] <= 0x60 - 0x12, True)
        #  The open wipe runs to 224 and the close one down from 220; a step
        #  that does not divide its total overshoots and the wipe runs away.
        check("open step divides 224, speedhacks=%d" % flag, 224 % got[1], 0)
        check("close step divides 220, speedhacks=%d" % flag, 220 % got[3], 0)

    #  opt_commit must refresh them, since that is what every edit goes through
    bus, cpu = machine()
    setblk(bus, OPT_FLAGS, OPTF_SPEEDHACKS)
    call(cpu, "opt_commit", dbr=CHUNK_OPT_BANK)
    check("commit refreshes the derived bytes", blk(bus, OPTD), 8)


def test_guillotine():
    """Talk_norm is redirected only when the flag is on and the object is not
    one of the two plates."""
    talk_norm, coo = SYM["Talk_norm"], SYM["Talk_CoOGuy"]
    RODPLATE, LUTEPLATE, ORDINARY, OTHER = 0x16, 0x17, 0x20, 0x30
    for flag, objid, handler, want in (
            (0, ORDINARY, talk_norm, talk_norm),                 # flag off
            (OPTF_GUILLOTINE_HI, ORDINARY, talk_norm, coo),      # the whole point
            (OPTF_GUILLOTINE_HI, RODPLATE, talk_norm, talk_norm),
            (OPTF_GUILLOTINE_HI, LUTEPLATE, talk_norm, talk_norm),
            (OPTF_GUILLOTINE_HI, ORDINARY, coo, coo)):           # other handlers alone
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 1, flag)
        bus.wram[TMP] = objid
        bus.wram[TMP + 6] = handler & 0xFF
        bus.wram[TMP + 7] = handler >> 8
        #  it ends in JMP (tmp+6), so point that at the sentinel-friendly stub:
        #  run it and see where it lands rather than where it returns
        cpu.pbr, cpu.pc = 0xA7, SYM["OptGuillotine"]
        try:
            for _ in range(200):
                if cpu.pc in (talk_norm, coo) and cpu.pbr == 0xA7:
                    break
                cpu.step()
        except Exception as e:
            fails.append("OptGuillotine raised %s" % e)
            continue
        got = cpu.pc
        check("guillotine flag=%d obj=$%02X handler=$%04X" % (flag, objid, handler),
              "$%04X" % got, "$%04X" % want)


MSGROWS_TOTAL = 12


def test_msgdraw():
    """Both message routines must draw all twelve rows and stop, whatever the
    rows-per-frame setting.  A miscounted inner loop would either leave the box
    half drawn or run off the end of the buffer, and neither shows up as a
    crash -- so count the row writes and check the pointers land where the
    twelfth row ends."""
    for name, flag, per_frame, start_ppu, step in (
            ("opt_msgdraw", 0, 1, 0x2240, +1), ("opt_msgdraw", OPTF_SPEEDHACKS, 2, 0x2240, +1),
            ("opt_msgdraw_rev", 0, 2, 0x23A0, -1),
            ("opt_msgdraw_rev", OPTF_SPEEDHACKS, 3, 0x23A0, -1)):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS, flag)
        call(cpu, "opt_derive", dbr=CHUNK_OPT_BANK)
        rows = []
        bus.wram[CUR_BANK] = 0x0C          # the battle bank, as in play
        cpu2 = CPU(bus); cpu2.dbr = CHUNK_OPT_BANK
        cpu2.pbr, cpu2.pc = CHUNK_OPT_BANK, SYM[name]
        cpu2.push(0xFF); cpu2.push(0xFF); cpu2.push(0xFD)
        draw = (SYM["Battle_DrawMessageRow"], SYM["Battle_DrawMessageRow_VBlank"])
        guard = 0
        while cpu2.pc != 0xFFFE and guard < 200000:
            guard += 1
            #  count each entry to a row writer, then return from it immediately
            if cpu2.pbr != CHUNK_OPT_BANK and cpu2.pc < 0xC000:
                fails.append("%s speedhacks=%d lost the program bank: running "
                             "$%02X:%04X" % (name, flag, cpu2.pbr, cpu2.pc))
                break
            if cpu2.pc in draw and cpu2.pbr in (CHUNK_OPT_BANK, 0xA1 + 0x0C):
                rows.append(bus.wram[0x8A] | (bus.wram[0x8B] << 8))
                lo, hi = cpu2.pull(), cpu2.pull()
                cpu2.pc = (((hi << 8) | lo) + 1) & 0xFFFF
                continue
            if cpu2.pc == SYM["Battle_UpdatePPU_UpdateAudio_FixedBank"]:
                #  Do not simply return: this routine ends in CallMusicPlay,
                #  which swaps to the music bank and comes back to whichever
                #  bank cur_bank names.  Model that, or the harness cannot see
                #  a caller that forgot to point cur_bank at itself -- which is
                #  a freeze on hardware and invisible here.
                lo, hi = cpu2.pull(), cpu2.pull()
                cpu2.pc = (((hi << 8) | lo) + 1) & 0xFFFF
                cpu2.pbr = 0xA1 + bus.wram[CUR_BANK]
                continue
            cpu2.step()
        check("%s speedhacks=%d draws 12 rows" % (name, flag), len(rows), MSGROWS_TOTAL)
        want = [start_ppu + step * 0x20 * i for i in range(MSGROWS_TOTAL)]
        check("%s speedhacks=%d covers every row once" % (name, flag), rows, want)


def test_respondtable():
    """The lookup picks a table from the flag, and both are monotonic -- a
    higher respond rate setting must never wait longer."""
    slow = (0x78, 0x50, 0x3C, 0x2D, 0x1E, 0x0F, 0x05, 0x01)
    fast = (0x30, 0x20, 0x18, 0x10, 0x08, 0x04, 0x02, 0x01)
    for flag, table in ((0, slow), (OPTF_SPEEDHACKS, fast)):
        got = []
        for rate in range(8):
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            cpu.y = rate
            call(cpu, "opt_respondlookup", dbr=CHUNK_OPT_BANK)
            got.append(cpu.a & 0xFF)
        check("respond table, speedhacks=%d" % flag, tuple(got), table)
        check("respond table descends, speedhacks=%d" % flag,
              all(got[i] >= got[i + 1] for i in range(7)), True)
        check("respond table is never zero, speedhacks=%d" % flag, min(got) > 0, True)


def test_lineup():
    """Run the lineup animation to convergence.

    The four AnimStep cases move until the coordinate *equals* its target, so
    a step that does not divide the distance makes the sprite circle forever.
    Rather than reason about it, drive the routine and see whether it stops.
    """
    SLOT_Y = (0x38, 0x58, 0x78, 0x98)
    for flag, step in ((0, 1), (OPTF_SPEEDHACKS, 4)):
        for a in range(4):
            for b in range(4):
                if a == b:
                    continue
                for startx, destx in ((0x88, 0x98), (0xA8, 0x98)):
                    bus, cpu = machine()
                    setblk(bus, OPT_FLAGS, flag)
                    call(cpu, "opt_derive", dbr=CHUNK_OPT_BANK)
                    check("lineup step, speedhacks=%d" % flag, blk(bus, OPTD + 7), step)
                    #  slot 0's record: +2 X, +3 Y, +4 destX, +5 destY
                    bus.wram[STR_BUF + 2] = startx
                    bus.wram[STR_BUF + 3] = SLOT_Y[a]
                    bus.wram[STR_BUF + 4] = destx
                    bus.wram[STR_BUF + 5] = SLOT_Y[b]
                    moved = 0
                    while moved < 400:
                        c = CPU(bus); c.dbr = BANK_0E; c.y = 0
                        c.run(BANK_0E, SYM["LineupMenu_AnimStep"])
                        moved += 1
                        if not (c.p & 0x01):            # C clear: it says it is done
                            break
                    else:
                        fails.append("lineup %d->%d x%02X never converged at step %d"
                                     % (a, b, startx, step))
                        continue
                    check("lineup %d->%d x$%02X lands exactly (step %d)"
                          % (a, b, startx, step),
                          (bus.wram[STR_BUF + 2], bus.wram[STR_BUF + 3]),
                          (destx, SLOT_Y[b]))


MAPOBJ = 0x6F00                # $100 bytes, sixteen to an object

#  map, slot, x, y -- FFR's list, which lut_NpcMoves has to agree with.
NPC_MOVES = ((0, 0, 0x11, 0x02), (0, 4, 0x12, 0x14), (0, 7, 0x1E, 0x0B),
             (1, 4, 0x1F, 0x05), (1, 5, 0x08, 0x0E), (2, 0, 0x24, 0x19),
             (6, 13, 0x29, 0x1B), (7, 3, 0x21, 0x07), (8, 5, 0x07, 0x0F))


def test_npcmove():
    """Move the townspeople who stand in doorways.

    Three things can go wrong silently: the slot arithmetic can land on the
    wrong object (a shift too few and everyone shuffles up), the routine can
    move objects belonging to some other map, and it can set the physical
    position without the graphical one, which makes the sprite slide back.
    So: run it on every map that has an entry, and on one that has none, and
    compare the whole page against what should have changed.
    """
    for flag in (0, OPTF_SPEEDHACKS):
        for cur in range(10):
            want = {}
            for (m, slot, x, y) in NPC_MOVES:
                if m == cur and flag:
                    base = slot * 16
                    want[base + 1] = 0x40           # not in a room, stationary
                    want[base + 2] = want[base + 4] = x
                    want[base + 3] = want[base + 5] = y

            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.wram[0x48] = cur                    # cur_map
            for i in range(0x100):
                bus.sram[MAPOBJ - 0x6000 + i] = 0xA5
            call(cpu, "opt_movenpcs", dbr=0xA7)     # as the JSL in bank $0F leaves it

            got = {i: bus.sram[MAPOBJ - 0x6000 + i]
                   for i in range(0x100)
                   if bus.sram[MAPOBJ - 0x6000 + i] != 0xA5}
            check("npc moves, map %d, speedhacks=%d" % (cur, bool(flag)), got, want)

    #  Nine entries and no more: a terminator left off would walk into whatever
    #  follows the table and scribble on objects from garbage coordinates.
    total = 0
    for cur in range(64):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS, OPTF_SPEEDHACKS)
        bus.wram[0x48] = cur
        for i in range(0x100):
            bus.sram[MAPOBJ - 0x6000 + i] = 0xA5
        call(cpu, "opt_movenpcs", dbr=0xA7)
        total += sum(1 for i in range(0x100)
                     if bus.sram[MAPOBJ - 0x6000 + i] != 0xA5)
    check("npc moves touch 9 objects across all 64 maps", total, 9 * 5)


MAGICPAGE = 0x6AF8
BANK_0C = 0xA1 + 0x0C
OPTF_MAGICWRAP = 0x00000100


def test_magicwrap():
    """Down off the bottom of the magic list, and up off the top.

    The two routines only answer "may the cursor leave this page", and when
    the wrap is what allows it they leave a value in the page byte that the
    caller's own INC or DEC turns into the page across the seam.  So the test
    has to do the caller's half too, or it proves nothing: what matters is the
    page that ends up in $6AF8 after the INC/DEC, not the one the routine
    wrote.
    """
    #  flag, entry, starting page -> (may move, page after the caller's step)
    cases = (
        (0, "opt_magicpgdn", 0, (True, 1)),     # vanilla: page 0 -> page 1
        (0, "opt_magicpgdn", 1, (False, 1)),    # vanilla: bottom of the list
        (0, "opt_magicpgup", 1, (True, 0)),     # vanilla: page 1 -> page 0
        (0, "opt_magicpgup", 0, (False, 0)),    # vanilla: top of the list
        (OPTF_MAGICWRAP, "opt_magicpgdn", 0, (True, 1)),
        (OPTF_MAGICWRAP, "opt_magicpgdn", 1, (True, 0)),   # wraps to the top
        (OPTF_MAGICWRAP, "opt_magicpgup", 1, (True, 0)),
        (OPTF_MAGICWRAP, "opt_magicpgup", 0, (True, 1)),   # wraps to the bottom
    )
    for flag, entry, page, want in cases:
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 1, flag >> 8)
        bus.sram[MAGICPAGE - 0x6000] = page
        call(cpu, entry, dbr=BANK_0C)       # JSL from bank $0C leaves DBR alone
        moved = bool(cpu.p & 0x01)          # carry
        after = bus.sram[MAGICPAGE - 0x6000]
        if moved:                           # the caller's own INC or DEC
            after = (after + (1 if entry.endswith("dn") else -1)) & 0xFF
        check("%s page %d, wrap=%d" % (entry[-2:], page, bool(flag)),
              (moved, after), want)

    #  Vanilla must be bit-for-bit vanilla: the flag off may never move the
    #  page byte on a refusal.
    for entry, page in (("opt_magicpgdn", 1), ("opt_magicpgup", 0)):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 1, 0)
        bus.sram[MAGICPAGE - 0x6000] = page
        call(cpu, entry, dbr=BANK_0C)
        check("%s leaves the page alone when it refuses" % entry,
              bus.sram[MAGICPAGE - 0x6000], page)


ITEMS = 0x6020                 # unsram + $20
ITEM_BOX = 0x0300
CURSOR_MAX = 0x63
BANK_FIXED = 0xA7              # DrawItemBox runs with whatever the menu left
OPTF_AUTOSORT = 0x00000400


def test_autosort():
    """Reorder the item list, and prove it is a reordering.

    The risk here is not the order -- that is a matter of taste -- but that
    the rebuilt list is not the same *set* as the one DrawItemBox just filled
    in.  An item dropped or a count that disagrees with the list would show up
    as an inventory entry the cursor cannot reach, or a blank row past the end
    of the list, and neither is obvious until it happens to you.
    """
    import random
    rng = random.Random(1234)

    def vanilla(inv):
        #  What DrawItemBox's own loop produces: $01 upward, orbs skipped.
        out = []
        for i in list(range(1, 0x12)) + list(range(0x16, 0x1C)):
            if inv[i]:
                out.append(i)
        return out

    def sorted_order(inv):
        out = []
        for grp in (range(0x19, 0x1C), range(0x16, 0x19), range(0x01, 0x12)):
            for i in grp:
                if inv[i]:
                    out.append(i)
        return out

    for trial in range(60):
        inv = [0] * 0x1C
        for i in range(1, 0x1C):
            if 0x12 <= i <= 0x15:
                continue                       # orbs; the menu never lists them
            inv[i] = rng.choice((0, 0, 1, 5, 99))
        want = sorted_order(inv)
        van = vanilla(inv)
        check("trial %d: the sort is a permutation" % trial,
              sorted(want), sorted(van))

        for flag in (0, OPTF_AUTOSORT):
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS + 1, flag >> 8)
            for i, q in enumerate(inv):
                bus.sram[ITEMS - 0x6000 + i] = q
            #  leave the buffer as DrawItemBox leaves it
            for i, v in enumerate(van + [0]):
                bus.wram[ITEM_BOX + i] = v
            bus.wram[CURSOR_MAX] = len(van)
            #  a sentinel past the terminator: nothing may write there
            bus.wram[ITEM_BOX + len(van) + 1] = 0x5A

            call(cpu, "opt_sortinv", dbr=BANK_FIXED)

            expect = want if flag else van
            got = [bus.wram[ITEM_BOX + i] for i in range(len(expect))]
            check("trial %d autosort=%d: list" % (trial, bool(flag)), got, expect)
            check("trial %d autosort=%d: terminator" % (trial, bool(flag)),
                  bus.wram[ITEM_BOX + len(expect)], 0)
            check("trial %d autosort=%d: count" % (trial, bool(flag)),
                  bus.wram[CURSOR_MAX], len(expect))
            check("trial %d autosort=%d: nothing past the terminator" % (trial, bool(flag)),
                  bus.wram[ITEM_BOX + len(expect) + 1], 0x5A)

    #  An empty inventory never reaches this routine -- DrawItemBox exits early
    #  -- but it must not run off if it ever does.
    bus, cpu = machine()
    setblk(bus, OPT_FLAGS + 1, OPTF_AUTOSORT >> 8)
    bus.wram[ITEM_BOX] = 0x5A
    call(cpu, "opt_sortinv", dbr=BANK_FIXED)
    check("empty inventory: empty list", bus.wram[ITEM_BOX], 0)
    check("empty inventory: count 0", bus.wram[CURSOR_MAX], 0)

    #  The orbs have no menu entry, and picking them up must not create one.
    bus, cpu = machine()
    setblk(bus, OPT_FLAGS + 1, OPTF_AUTOSORT >> 8)
    for i in range(0x12, 0x16):
        bus.sram[ITEMS - 0x6000 + i] = 1
    bus.sram[ITEMS - 0x6000 + 0x19] = 1
    call(cpu, "opt_sortinv", dbr=BANK_FIXED)
    check("orbs stay out of the list",
          [bus.wram[ITEM_BOX + i] for i in range(2)], [0x19, 0])


ENEMY_IDS = 0x6BB7             # nine slots; $FF means the slot is empty
BTL_DEFENDER = 0x6C8A
DEFENDER_INDEX = 0x6885        # in SRAM, like the rest of the battle block
OPTF_AUTORETARGET = 0x00000200


def test_retarget():
    """Move an attack off an enemy that died earlier in the round.

    Both entry points have to agree with the call sites they replaced: the
    physical one writes two variables and the magic one writes one, and the
    magic one must leave a party member -- slot 9 and up -- alone, or healing
    a character turns into hitting an enemy.
    """
    def setup(flag, lineup, target):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 1, flag >> 8)
        for i in range(9):
            bus.sram[ENEMY_IDS - 0x6000 + i] = lineup[i]
        bus.sram[BTL_DEFENDER - 0x6000] = 0xA5
        bus.sram[DEFENDER_INDEX - 0x6000] = 0xA5
        cpu.x = target
        return bus, cpu

    DEAD = 0xFF
    full = [3] * 9
    only4 = [DEAD] * 9
    only4[4] = 7
    gone = [DEAD] * 9
    top = [DEAD] * 9
    top[0] = 1
    top[8] = 2

    cases = (
        #  lineup,  target, autoretarget -> slot the attack lands on
        (full,  2, False, 2),
        (full,  2, True,  2),      # alive: never moved
        (only4, 2, False, 2),      # vanilla swings at the empty slot
        (only4, 2, True,  4),      # the only one left
        (top,   3, True,  8),      # highest slot first, as FFR picks it
        (gone,  3, True,  3),      # nobody left: leave it, do not invent $FF
    )
    for lineup, target, on, want in cases:
        flag = OPTF_AUTORETARGET if on else 0
        bus, cpu = setup(flag, lineup, target)
        call(cpu, "opt_retarget", dbr=BANK_0C)
        check("melee target %d, on=%d" % (target, on), cpu.x & 0xFF, want)
        check("melee writes the index", bus.sram[DEFENDER_INDEX - 0x6000], want)
        check("melee writes btl_defender", bus.sram[BTL_DEFENDER - 0x6000], want)

        bus, cpu = setup(flag, lineup, target)
        call(cpu, "opt_retarget_mag", dbr=BANK_0C)
        check("magic target %d, on=%d" % (target, on), cpu.x & 0xFF, want)
        check("magic writes btl_defender", bus.sram[BTL_DEFENDER - 0x6000], want)
        check("magic leaves the index alone", bus.sram[DEFENDER_INDEX - 0x6000], 0xA5)

    #  A spell aimed at a party member is slot 9..12, and must survive
    #  unchanged.  The slot guard is the only thing protecting it: reading
    #  btl_enemyIDs at index 9 walks into btl_enemygfxplt, and a $FF there
    #  would send the spell to an enemy instead of the character it was cast
    #  on.  So the hostile case is a live lineup with $FF in those four bytes.
    for target in range(9, 13):
        for lineup, label in ((gone, "no enemies"), (full, "a full lineup")):
            bus, cpu = setup(OPTF_AUTORETARGET, lineup, target)
            for i in range(9, 13):
                bus.sram[ENEMY_IDS - 0x6000 + i] = 0xFF
            call(cpu, "opt_retarget_mag", dbr=BANK_0C)
            check("magic on party member %d, %s" % (target, label),
                  cpu.x & 0xFF, target)
            check("magic on party member %d, %s: btl_defender" % (target, label),
                  bus.sram[BTL_DEFENDER - 0x6000], target)


MSGDRAW_HDR = 0x6A9E
BTLFORM_NORUN = None           # filled in from the label file below
OPTF_RUNWAIT = 0x00000080
BTLMSG_CANTRUN = 0x24
BTLMSG_NOTHINGHAPPENS = 0x4E


def test_runwait():
    """Label the command WAIT, and answer with something that is not a failure.

    Both halves read the same two conditions, so they are driven through the
    same four combinations.  The label half also has to leave A holding the
    table byte: vanilla falls into AddBlockToBuffer with it still there, and a
    routine inserted in front of that call is exactly the kind of thing that
    quietly clobbers it.
    """
    norun_addr = 0x6D91                  # btlform_norun, the formation's low bit
    for flag in (0, OPTF_RUNWAIT):
        for norun in (0x00, 0x01, 0x02, 0x30, 0x31, 0x32):  # the rest is palette
            wait = bool(flag) and (norun & 1)

            #  the label: Y on the last byte of the last block
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.sram[norun_addr - 0x6000] = norun
            for i in range(5):
                bus.sram[MSGDRAW_HDR - 0x6000 + i] = 0x11 + i
            cpu.y = 29
            cpu.a = 0x5C
            call(cpu, "OptRunLabel", bank=BANK_0C, dbr=BANK_0C)
            ptr = (bus.sram[MSGDRAW_HDR - 0x6000 + 3],
                   bus.sram[MSGDRAW_HDR - 0x6000 + 4])
            want = (SYM["lut_WaitString"] & 0xFF, SYM["lut_WaitString"] >> 8) \
                   if wait else (0x14, 0x15)
            check("run label, flag=%d norun=$%02X" % (bool(flag), norun), ptr, want)
            check("run label preserves A", cpu.a & 0xFF, 0x5C)
            check("run label leaves the block alone",
                  [bus.sram[MSGDRAW_HDR - 0x6000 + i] for i in range(3)],
                  [0x11, 0x12, 0x13])

            #  ...and not on any other block
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.sram[norun_addr - 0x6000] = norun
            for i in range(5):
                bus.sram[MSGDRAW_HDR - 0x6000 + i] = 0x11 + i
            for y in (4, 9, 14, 19, 24):
                cpu.y = y
                call(cpu, "OptRunLabel", bank=BANK_0C, dbr=BANK_0C)
            check("run label only touches the last block",
                  [bus.sram[MSGDRAW_HDR - 0x6000 + i] for i in range(5)],
                  [0x11, 0x12, 0x13, 0x14, 0x15])

            #  the message
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.sram[norun_addr - 0x6000] = norun
            #  Step up to the jump rather than through it: past that point is
            #  the real message drawer, which wants a battle in progress.
            cpu.pbr, cpu.pc = BANK_0C, SYM["OptRunFail"]
            target = SYM["DrawBtlMsg_ClearCombatBoxes"]
            for _ in range(200):
                if cpu.pc == target and cpu.pbr == BANK_0C:
                    break
                cpu.step()
            else:
                fails.append("OptRunFail never reached the message drawer")
                continue
            check("run message, flag=%d norun=$%02X" % (bool(flag), norun),
                  cpu.a & 0xFF,
                  BTLMSG_NOTHINGHAPPENS if wait else BTLMSG_CANTRUN)


TEXT_PTR = 0x3E
OPTF_IDTREASURE = 0x00000010
DLGID_CANTCARRY = 0xF1


def test_idtreasure():
    """Swap the "Can't hold anymore." string for one that says what.

    The hook sits in the upper half of DrawDialogueString's pointer lookup,
    where the id has already been doubled.  Doubling collides across the two
    halves but not within one, so the test walks every id the upper half can
    carry and checks that exactly one of them is redirected.
    """
    for flag in (0, OPTF_IDTREASURE):
        for dlgid in range(0x80, 0x100):
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.wram[TEXT_PTR] = 0x34           # as the table lookup left it
            bus.wram[TEXT_PTR + 1] = 0x12
            cpu.x = (dlgid * 2) & 0xFF
            call(cpu, "opt_dlgident", dbr=0xA7)
            got = bus.wram[TEXT_PTR] | (bus.wram[TEXT_PTR + 1] << 8)
            want = SYM["lut_CantHoldWhat"] \
                   if (flag and dlgid == DLGID_CANTCARRY) else 0x1234
            if got != want:
                check("dialogue $%02X, identify=%d" % (dlgid, bool(flag)),
                      "$%04X" % got, "$%04X" % want)
            check("dialogue $%02X leaves X alone" % dlgid, cpu.x & 0xFF,
                  (dlgid * 2) & 0xFF)

    #  The string itself: it has to end, name the item, and stay inside the
    #  dialogue drawer's idea of a control code.
    addr = SYM["lut_CantHoldWhat"]
    rom = chunkbyte
    text = []
    for i in range(32):
        b = rom(0x0F, addr + i)
        text.append(b)
        if b == 0:
            break
    else:
        fails.append("lut_CantHoldWhat is not terminated within 32 bytes")
        text = []
    check("the string prints the item name", 0x02 in text, True)
    check("the string has one line break", text.count(0x01), 1)
    check("the string is not longer than the box is wide",
          sum(1 for b in text if b >= 0x7A), 10)


def chunkbyte(bank, addr):
    """One byte of a NES bank as the SNES image holds it.

    Chunk N lives in ROM bank 1+N, and the fixed bank is stamped at $C000 of
    every one of them, so bank $0F is read out of any chunk.
    """
    chunk = 1 + (bank if addr < 0xC000 else 0x0F)
    return ROMDATA[chunk * 0x10000 + addr]


def main():
    for t in (test_block, test_presets, test_movespeed, test_encounter,
              test_noshuffle, test_derive, test_guillotine,
              test_battlespeed, test_lineup, test_respondtable, test_msgdraw,
              test_npcmove, test_magicwrap, test_autosort, test_retarget,
              test_runwait, test_idtreasure):
        try:
            t()
        except Exception as e:
            fails.append("%s raised %s: %s" % (t.__name__, type(e).__name__, e))
    if fails:
        print("FAIL (%d)" % len(fails))
        for f in fails:
            print("   " + f)
        return 1
    print("option hooks: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
