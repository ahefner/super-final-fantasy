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
from cpu65816 import Bus, CPU, C

ROM = os.path.join(ROOT, "SuperFinalFantasy.sfc")
LABELS = os.path.join(ROOT, "out", "labels.txt")

OPTBLOCK = 0x6E00
OPT_MAGIC0, OPT_MAGIC1, OPT_VERSION, OPT_PRESET = 0, 1, 2, 3
#  The flag word is five bytes; everything after it moved when the
#  Treasures section and the free key items took bits 26-33.
OPT_FLAGS, OPT_GOLDXP, OPT_ENCOUNTER = 4, 9, 10
OPT_ENEMY, OPT_BOSS, OPT_ELEMDMG = 11, 12, 13
OPT_RESPOND, OPT_CKSUM = 14, 15
OPT_SIZE = 16
OPT_FORMAT = 4          # bumped when the elemental bonus became a fifth dial
CHUNK_OPT_BANK = 0xA1 + 0x11
BANK_0E = 0xA1 + 0x0E          # chunk N runs at PBR $A1+N, so NES bank $0E is $AF
CUR_BANK = 0x57                # the bank SwapPRG returns to

fails = []
skipped = []


def labels():
    """The label file build.sh wrote, never one of our own making.

    ld65 writes out/bank_*.bin from the memory areas in snes.cfg, so *any*
    ld65 run rewrites them -- and the addresses it assigns depend on the order
    the object files are given.  This used to relink with the objects sorted,
    which differs from build.sh's order once a segment has three files in it.
    The result was a label file that disagreed with the ROM beside it: the
    tests read symbol addresses from one layout and instructions from another,
    and quietly checked the wrong bytes.  There is one link, in build.sh, and
    this reads what it left.
    """
    if not os.path.exists(LABELS):
        sys.exit("no %s -- run ./build.sh" % LABELS)
    #  The ROM is written after the link, so it is always the newer of the two;
    #  compare against what the link consumed instead.
    objs = [os.path.join(ROOT, "out", f) for f in os.listdir(os.path.join(ROOT, "out"))
            if f.endswith(".o")]
    if objs and os.path.getmtime(LABELS) < max(os.path.getmtime(o) for o in objs):
        sys.exit("%s is older than the objects -- run ./build.sh" % LABELS)
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
    return int.from_bytes(bus.sram[OPTBLOCK - 0x6000 + OPT_FLAGS:][:5], "little")


# --- the option block -------------------------------------------------------
def test_block():
    #  A cartridge with nothing in it comes up on the default preset, sealed.
    bus, cpu = machine()
    call(cpu, "opt_init")
    check("fresh cart: magic", (blk(bus, OPT_MAGIC0), blk(bus, OPT_MAGIC1)), (0x53, 0x46))
    check("fresh cart: version", blk(bus, OPT_VERSION), OPT_FORMAT)
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
    check("stale version is retired", blk(bus4, OPT_VERSION), OPT_FORMAT)
    check("stale version resets preset", blk(bus4, OPT_PRESET), 1)


def test_presets():
    #  flags, gold/xp, encounter, enemy, boss, elemental bonus.  The bonus is
    #  a step of two, so 2 is vanilla's +4, 5 is FFR's Improved Vanilla +10
    #  and 15 is the +30 most of FFR's own presets use.
    #  Bit 21 is Thief/Ninja hit growth, and Improved carries it -- the only
    #  variation it does, because a Thief that misses is a bug in all but name.
    want = {0: (0x00000000, 2, 10, 3, 3, 2),
            1: (0x0027BFFF, 2, 10, 3, 3, 5),
            2: (0x03FFFFFF, 5, 6, 3, 3, 15)}
    for preset, (f, g, e, en, bo, el) in want.items():
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
        check("%s: elemental bonus step" % name, blk(bus, OPT_ELEMDMG), el)
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
    if "opt_runlabel" not in SYM:
        #  The feature is switched off in the build (it lends its fixed-bank
        #  space to the vanilla message-box loops).  Say so rather than
        #  failing, so a real regression still stands out.
        skipped.append("run -> wait: not in this build")
        return

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
            call(cpu, "opt_runlabel", dbr=BANK_0C)
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
                call(cpu, "opt_runlabel", dbr=BANK_0C)
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


MATH_DMGCALC = 0x6860
HITSCONNECTED = 0x686A
OPTF_STATUSATK = 0x00040000


def test_statusatk():
    """Ask whether this swing connected, not whether any has.

    The two answers differ exactly where the bug lives: an enemy that has
    already landed one hit, swinging again and missing.  Both readings are
    driven over the same grid so the vanilla answer is pinned too -- this is a
    flag, and with it off the enemy has to keep its bug.
    """
    for flag in (0, OPTF_STATUSATK):
        for hits in (0, 1, 3):
            for dmg in (0, 1, 7, 255, 256, 257):   # 256: crit carries into
                                                   # the high byte
                bus, cpu = machine()
                setblk(bus, OPT_FLAGS + 2, (flag >> 16) & 0xFF)
                bus.sram[HITSCONNECTED - 0x6000] = hits
                bus.sram[MATH_DMGCALC - 0x6000] = dmg & 0xFF
                bus.sram[MATH_DMGCALC - 0x6000 + 1] = dmg >> 8
                call(cpu, "opt_thishit", dbr=BANK_0C)
                want = ((dmg | (dmg >> 8)) & 0xFF) if flag else hits
                check("thishit flag=%d hits=%d dmg=%d" % (bool(flag), hits, dmg),
                      cpu.a & 0xFF, want)
                #  the caller branches on Z straight after, so the flag matters
                #  as much as the value
                check("thishit flag=%d hits=%d dmg=%d: Z" % (bool(flag), hits, dmg),
                      bool(cpu.p & 0x02), (dmg == 0) if flag else (hits == 0))

    #  The case the bug is about: one hit already landed, this swing missed.
    bus, cpu = machine()
    setblk(bus, OPT_FLAGS + 2, (OPTF_STATUSATK >> 16) & 0xFF)
    bus.sram[HITSCONNECTED - 0x6000] = 1
    bus.sram[MATH_DMGCALC - 0x6000] = 0
    call(cpu, "opt_thishit", dbr=BANK_0C)
    check("a miss after a hit no longer rolls for the ailment",
          bool(cpu.p & 0x02), True)


BATTLEREWARD = 0x88            # three bytes of zero page


def test_goldxp():
    """Scale the end-of-battle reward.

    The setting counts halves -- 2 is 100% -- so the answer is
    total * step / 2, and the one case that has to be exact is step 2, where
    the routine must not touch the number at all.  The reward is three bytes
    with nowhere to put a fourth, so a total that scales past $FFFFFF pegs
    there rather than wrapping to something small, which is the failure that
    would look like a bug in the game rather than in the flag.
    """
    for step in range(11):
        #  0x300000 and 0x400000 matter: scaled up they carry into the top
        #  byte of the accumulator but come back under $FFFFFF once halved, so
        #  they are the only values that tell a halve from a double.
        for total in (0, 1, 2, 3, 1000, 0x123456, 0x300000, 0x400000, 0xFFFFFF):
            bus, cpu = machine()
            setblk(bus, OPT_GOLDXP, step)
            for i in range(3):
                bus.wram[BATTLEREWARD + i] = (total >> (8 * i)) & 0xFF
            call(cpu, "opt_scalereward", dbr=BANK_0C)
            got = sum(bus.wram[BATTLEREWARD + i] << (8 * i) for i in range(3))
            want = min((total * step) // 2, 0xFFFFFF)
            check("goldxp step %d of %d" % (step, total), got, want)

    #  100% must be bit-for-bit untouched, not merely arithmetically equal:
    #  it is the path every vanilla game takes.
    bus, cpu = machine()
    setblk(bus, OPT_GOLDXP, 2)
    for i, v in enumerate((0x9A, 0xBC, 0xDE)):
        bus.wram[BATTLEREWARD + i] = v
    call(cpu, "opt_scalereward", dbr=BANK_0C)
    check("goldxp 100% leaves the reward alone",
          [bus.wram[BATTLEREWARD + i] for i in range(3)], [0x9A, 0xBC, 0xDE])


BTL_RNGSTATE = 0x688A


def test_fardata():
    """The tables that moved out of the fixed bank, read long.

    lut_DTE1, lut_DTE2 and the battle RNG's scrambling table live in the
    options chunk now and the fixed bank reaches them with LDA f:addr,X.  Two
    things can go wrong and neither shows up as a build error: the table can
    land somewhere other than where the reading instruction names, and the
    read can assemble as a 3-byte absolute load that silently fetches from
    whatever is at that address in the current bank.  So this runs the real
    instruction and checks the value that comes back.
    """
    blob = open(os.path.join(ROOT, "game", "bin", "0F_FCF1_rngtable.bin"), "rb").read()

    #  BattleRNG is the whole path: it does nothing but the long read.  All
    #  256 entries, because a wrong table is not something anyone would notice
    #  playing -- bad luck looks like bad luck.
    wrong = []
    for state in range(256):
        bus, cpu = machine()
        bus.sram[BTL_RNGSTATE - 0x6000] = state
        call(cpu, "BattleRNG_L", bank=BANK_0C, dbr=BANK_0C)
        if (cpu.a & 0xFF) != blob[state]:
            wrong.append(state)
        check("BattleRNG state $%02X advances" % state,
              bus.sram[BTL_RNGSTATE - 0x6000], (state + 1) & 0xFF)
    check("BattleRNG returns the table for all 256 states", wrong, [])

    #  Walking the state through all 256 values must reproduce the table as a
    #  multiset -- a second, independent check that the loop reads the whole of
    #  it and nothing else.
    #
    #  Disch notes that ChaosDeath in bank $0B assumes 256 consecutive calls
    #  produce every value exactly once.  The original table does not quite
    #  manage it: 0 appears twice and 149 never appears at all.  That is
    #  vanilla's quirk, not the port's -- the bytes here are the original
    #  bytes.  FFR has a "Fix Missing Battle RNG Entry" flag for it; porting
    #  that is a decision already taken and declined, so these two assertions
    #  exist to stop anyone (including me) quietly "fixing" it later.
    bus, _ = machine()
    seen = []
    for state in range(256):
        cpu = CPU(bus); cpu.dbr = BANK_0C
        bus.sram[BTL_RNGSTATE - 0x6000] = state
        cpu.run(BANK_0C, SYM["BattleRNG_L"])
        seen.append(cpu.a & 0xFF)
    check("256 consecutive calls walk the whole table",
          sorted(seen), sorted(blob))
    check("vanilla's quirk is intact: 0 twice, 149 never",
          (seen.count(0), seen.count(149)), (2, 0))

    #  ...and the DTE tables, read the same way the drawers read them.
    bus, _ = machine()
    for name in ("lut_DTE1", "lut_DTE2"):
        got = bytes(bus.read(0xB2, SYM[name] + i) for i in range(80))
        check("%s reachable at bank $B2" % name, len(set(got)) > 1, True)
        check("%s is 80 bytes of text codes" % name,
              all(0x7A <= b <= 0xFF for b in got), True)


OPTF_REPEATPOTION = 0x00000800
POTIONS = {"heal": 0x19, "pure": 0x1A, "soft": 0x1B}


def test_repeatpotion():
    """Spend a potion, and say whether to offer another.

    The decrement is the caller's old instruction moved in here, so it has to
    happen whatever the flag says -- a flag that quietly stopped consuming
    potions would be a far worse bug than one that failed to repeat.
    """
    for name, off in POTIONS.items():
        for flag in (0, OPTF_REPEATPOTION):
            for held in (1, 2, 99):
                bus, cpu = machine()
                setblk(bus, OPT_FLAGS + 1, flag >> 8)
                bus.sram[ITEMS - 0x6000 + off] = held
                #  the other two must not move
                for other in POTIONS.values():
                    if other != off:
                        bus.sram[ITEMS - 0x6000 + other] = 7
                cpu.x = off
                call(cpu, "opt_usedpotion", dbr=BANK_0C)
                check("%s x%d flag=%d: spent" % (name, held, bool(flag)),
                      bus.sram[ITEMS - 0x6000 + off], held - 1)
                check("%s x%d flag=%d: offer another" % (name, held, bool(flag)),
                      bool(cpu.p & 0x01), bool(flag) and held - 1 > 0)
                check("%s x%d flag=%d: other potions untouched" % (name, held, bool(flag)),
                      [bus.sram[ITEMS - 0x6000 + o] for o in POTIONS.values() if o != off],
                      [7, 7])


SHOP_CURPRICE = 0x030E
OPT_SHOPQTY, OPT_SHOPMAX, OPT_SHOPUNIT = 0x28, 0x2A, 0x2B
OPTF_BUYQTY = 0x00000040


def test_buyqty():
    """The quantity cap, the total, and the inventory arithmetic.

    shop_curprice is sixteen bits and both Shop_CanAfford and ShopPayPrice
    read it that way, so the cap exists to stop a total wrapping -- which
    would charge the player almost nothing for a large order.  That is the
    failure worth pinning: undercharging looks like a gift, not a bug.
    """
    for unit in (1, 6, 60, 375, 1500, 5000, 20000, 40000, 65535):
        bus, cpu = machine()
        setblk(bus, OPT_SHOPUNIT, unit & 0xFF)
        setblk(bus, OPT_SHOPUNIT + 1, unit >> 8)
        call(cpu, "opt_shopmax", dbr=BANK_0C)
        want = min(99, 65535 // unit)
        got = blk(bus, OPT_SHOPMAX)
        check("cap for a %d gold item" % unit, got, want)
        #  the cap must be honest in both directions: one more must not fit
        check("cap for %d is the largest that fits" % unit,
              (got + 1) * unit > 0xFFFF or got == 99, True)

        #  only quantities the cap allows: opt_shopscale is documented not to
        #  handle more, which is precisely what the cap is for
        for qty in sorted({1, min(2, got), got}):
            bus2, cpu2 = machine()
            setblk(bus2, OPT_SHOPUNIT, unit & 0xFF)
            setblk(bus2, OPT_SHOPUNIT + 1, unit >> 8)
            setblk(bus2, OPT_SHOPQTY, qty)
            call(cpu2, "opt_shopscale", dbr=BANK_0C)
            total = bus2.wram[SHOP_CURPRICE] | (bus2.wram[SHOP_CURPRICE + 1] << 8)
            check("%d x %d gold" % (qty, unit), total, unit * qty)
            check("%d x %d fits in sixteen bits" % (qty, unit), unit * qty <= 0xFFFF, True)

    #  room and the purchase itself
    for held in (0, 1, 50, 98, 99):
        for qty in (1, 2, 50):
            bus, cpu = machine()
            setblk(bus, OPT_SHOPQTY, qty)
            bus.sram[ITEMS - 0x6000 + 0x19] = held
            cpu.x = 0x19
            call(cpu, "OptShopHasRoom", bank=BANK_0C, dbr=BANK_0C)
            check("room for %d when holding %d" % (qty, held),
                  not (cpu.p & 0x01), held + qty <= 99)

            bus, cpu = machine()
            setblk(bus, OPT_SHOPQTY, qty)
            bus.sram[ITEMS - 0x6000 + 0x19] = held
            cpu.x = 0x19
            call(cpu, "OptShopAddItems", bank=BANK_0C, dbr=BANK_0C)
            check("buying %d onto %d" % (qty, held),
                  bus.sram[ITEMS - 0x6000 + 0x19], (held + qty) & 0xFF)


from fractions import Fraction
OPT_STATV, OPT_STATNUM, OPT_STATSH, OPT_STATOVF = 0x32, 0x34, 0x35, 0x3E
ADJ = {"1.00": (lambda n: (n, 2)), "0.50": (lambda n: (n + 4, 3)),
       "0.25": (lambda n: (n + 12, 4))}


def ffr_scale(value, n, adj):
    """FFR's RangeScale with a single percentage, as an exact rational.

    RangeScale's random exponent drops out when low == high, leaving
    value * (1 + (p-1)*adj) with p = n/4.  C# rounds a double half to even.
    """
    p = Fraction(n, 4)
    scale = 1 + (p - 1) * Fraction(adj).limit_denominator()
    return round(value * scale)          # Python rounds half to even too


def test_statscale():
    """The scaling arithmetic, against FFR's formula."""
    for adjname, mk in ADJ.items():
        for n in range(1, 21):
            num, sh = mk(n)
            for value in (0, 1, 2, 3, 7, 10, 99, 100, 255, 1000, 32767):
                bus, cpu = machine()
                setblk(bus, OPT_STATV, value & 0xFF)
                setblk(bus, OPT_STATV + 1, value >> 8)
                setblk(bus, OPT_STATNUM, num)
                setblk(bus, OPT_STATSH, sh)
                cpu.run(CHUNK_OPT_BANK, SYM["opt_statmul"])
                got = (blk(bus, OPT_STATV) | (blk(bus, OPT_STATV + 1) << 8)
                       | (blk(bus, OPT_STATOVF) << 16))
                want = ffr_scale(value, n, adjname)
                check("scale %s n=%d of %d" % (adjname, n, value), got, want)

    #  100% must be the identity, which is FFR's early return
    for adjname, mk in ADJ.items():
        num, sh = mk(4)
        for value in (1, 7, 99, 255, 1000, 32767):
            bus, cpu = machine()
            setblk(bus, OPT_STATV, value & 0xFF)
            setblk(bus, OPT_STATV + 1, value >> 8)
            setblk(bus, OPT_STATNUM, num)
            setblk(bus, OPT_STATSH, sh)
            cpu.run(CHUNK_OPT_BANK, SYM["opt_statmul"])
            check("100%% %s leaves %d alone" % (adjname, value),
                  blk(bus, OPT_STATV) | (blk(bus, OPT_STATV + 1) << 8), value)


BOSSES = {15, 105, 113} | set(range(118, 128))


def test_isboss():
    """FFR's boss list, and nothing else."""
    wrong = []
    for eid in range(128):
        bus, cpu = machine()
        cpu.a = eid
        cpu.run(CHUNK_OPT_BANK, SYM["opt_isboss"])
        if bool(cpu.p & 0x01) != (eid in BOSSES):
            wrong.append(eid)
    check("boss list matches FFR", wrong, [])


BTL_ENEMYSTATS = 0x6BD3        # $14 bytes each, nine of them
EN_HP, EN_DEF, EN_EVADE, EN_STR, EN_ID = 0x02, 0x04, 0x0A, 0x0B, 0x11


def test_scaleenemies():
    """The pass over the battle's copy of the enemy stats.

    This is where a wrong field offset would hide: the arithmetic is already
    checked against FFR's formula, so what is left is whether each stat gets
    the adjustment FFR gives it, whether bosses take the other setting, and
    whether the clamps hold.
    """
    def setup(enemy_step, boss_step, slots):
        bus, cpu = machine()
        setblk(bus, OPT_ENEMY, enemy_step)
        setblk(bus, OPT_BOSS, boss_step)
        for i in range(9):
            bus.sram[ENEMY_IDS - 0x6000 + i] = 0xFF
        for slot, (eid, hp, dfn, ev, st) in slots.items():
            bus.sram[ENEMY_IDS - 0x6000 + slot] = eid
            b = BTL_ENEMYSTATS - 0x6000 + slot * 0x14
            bus.sram[b + EN_ID] = eid
            bus.sram[b + EN_HP] = hp & 0xFF
            bus.sram[b + EN_HP + 1] = hp >> 8
            bus.sram[b + EN_DEF] = dfn
            bus.sram[b + EN_EVADE] = ev
            bus.sram[b + EN_STR] = st
        return bus, cpu

    def read(bus, slot):
        b = BTL_ENEMYSTATS - 0x6000 + slot * 0x14
        return (bus.sram[b + EN_HP] | (bus.sram[b + EN_HP + 1] << 8),
                bus.sram[b + EN_DEF], bus.sram[b + EN_EVADE], bus.sram[b + EN_STR])

    #  slot 0 an ordinary enemy, slot 3 a boss (Lich), slot 8 empty
    slots = {0: (0x20, 500, 40, 60, 30), 3: (119, 1200, 80, 100, 90)}
    for estep, bstep in ((3, 3), (7, 3), (3, 7), (0, 19), (19, 0)):
        bus, cpu = setup(estep, bstep, slots)
        call(cpu, "opt_scaleenemies", dbr=BANK_0C)
        for slot, (eid, hp, dfn, ev, st) in slots.items():
            n = (bstep if eid in BOSSES else estep) + 1
            want = (min(ffr_scale(hp, n, "1.00"), 0x7FFF),
                    min(ffr_scale(dfn, n, "0.50"), 0xFF),
                    min(ffr_scale(ev, n, "1.00"), 0xF0),
                    min(ffr_scale(st, n, "0.25"), 0xFF))
            check("slot %d, enemy=%d boss=%d" % (slot, estep, bstep),
                  read(bus, slot), want)

    #  an empty slot must be left exactly alone
    bus, cpu = setup(19, 19, slots)
    b = BTL_ENEMYSTATS - 0x6000 + 8 * 0x14
    for i in range(0x14):
        bus.sram[b + i] = 0x5A
    call(cpu, "opt_scaleenemies", dbr=BANK_0C)
    check("empty slots untouched",
          list(bus.sram[b:b + 0x14]), [0x5A] * 0x14)

    #  and 100% on both settings must change nothing at all
    bus, cpu = setup(3, 3, slots)
    before = {s: read(bus, s) for s in slots}
    call(cpu, "opt_scaleenemies", dbr=BANK_0C)
    check("100%% is a no-op", {s: read(bus, s) for s in slots}, before)


FRAMECOUNTER = 0xF0
BTL_MAGDATAPTR = 0x98
BTL_ATTACKID = 0x6C8C
OPT_MAGSHADOW = 0x40
OPTF_IMPCURE = 0x00400000
OPTF_IMPFIRE = 0x00800000

#  FFR's six out-of-battle heal rolls: (vanilla mask, base), (buffed mask, base)
HEALROLL = [((0x0F, 0x10), (0x1F, 0x20)),   # CURE
            ((0x1F, 0x20), (0x3F, 0x40)),   # CUR2
            ((0x3F, 0x40), (0x7F, 0x80)),   # CUR3
            ((0x07, 0x10), (0x0F, 0x10)),   # HEAL
            ((0x0F, 0x20), (0x1F, 0x20)),   # HEL2
            ((0x1F, 0x40), (0x3F, 0x40))]   # HEL3


def test_healroll():
    """The out-of-battle heal amounts, buffed and not.

    Vanilla computes these inline per spell; FFR widens each mask to twice
    its span and doubles the CURE bases, leaving the HEAL bases alone.  Both
    sets are driven over every frame counter value, because the roll is the
    frame counter and a wrong mask shows up only at particular values.
    """
    for idx, (van, buf) in enumerate(HEALROLL):
        for flag, (mask, base) in ((0, van), (OPTF_IMPCURE, buf)):
            wrong = []
            for fc in range(256):
                bus, cpu = machine()
                setblk(bus, OPT_FLAGS + 2, (flag >> 16) & 0xFF)
                bus.wram[FRAMECOUNTER] = fc
                cpu.x = idx
                call(cpu, "opt_healroll", dbr=BANK_0C)
                want = (fc & mask) + base
                if (cpu.a & 0xFF) != want:
                    wrong.append((fc, cpu.a & 0xFF, want))
            check("heal roll %d, buffed=%d" % (idx, bool(flag)), wrong[:3], [])
            #  the caller branches on Z straight after, and never wants zero
            check("heal roll %d, buffed=%d: never zero" % (idx, bool(flag)),
                  base > 0, True)


#  spell -> (effectivity FFR writes, which flag)
SPELLBUFF = {0: (0x20, "cure"), 16: (0x40, "cure"), 32: (0x80, "cure"),
             19: (0x10, "cure"), 35: (0x20, "cure"), 51: (0x40, "cure"),
             8: (0x18, "cure"), 27: (0x50, "cure"),
             4: (50, "fire"), 7: (60, "fire"), 12: (70, "fire"), 1: (60, "fire")}
RECORD = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]


def test_spellbuff():
    """The in-battle half: an edited copy, and the pointer swung at it.

    Every spell is tried, not just the twelve FFR touches -- redirecting a
    spell it does not touch would be a silent change to something else.
    """
    for spell in range(0x40):
        for flags, on in ((0, None), (OPTF_IMPCURE, "cure"), (OPTF_IMPFIRE, "fire"),
                          (OPTF_IMPCURE | OPTF_IMPFIRE, "both")):
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS + 2, (flags >> 16) & 0xFF)
            bus.sram[BTL_ATTACKID - 0x6000] = spell
            for i, v in enumerate(RECORD):          # the record, in low RAM
                bus.wram[0x0400 + i] = v
            bus.wram[BTL_MAGDATAPTR] = 0x00
            bus.wram[BTL_MAGDATAPTR + 1] = 0x04
            call(cpu, "opt_magicdata", dbr=BANK_0C)
            ptr = bus.wram[BTL_MAGDATAPTR] | (bus.wram[BTL_MAGDATAPTR + 1] << 8)

            buffed = SPELLBUFF.get(spell)
            applies = buffed is not None and (on == "both" or on == buffed[1])
            if not applies:
                check("spell %d flags=%s: pointer untouched" % (spell, on), ptr, 0x0400)
                continue
            want = list(RECORD)
            want[1] = buffed[0]
            if spell == 1:                          # HARM also stops hitting all
                want[3] = 0x02
            check("spell %d flags=%s: redirected" % (spell, on), ptr != 0x0400, True)
            check("spell %d flags=%s: record" % (spell, on),
                  [blk(bus, OPT_MAGSHADOW + i) for i in range(8)], want)


BTLMAG_SPELLINDEX = 0x6B7D


def test_magictarget():
    """HARM's target, as the selection menu asks for it.

    Selection and casting read the spell record through different pointers,
    so the shadow that serves the cast never reaches the prompt.  Left alone
    HARM prompted as an all-enemies spell and was then cast as single-target,
    which put the animation on the party and delivered the damage nowhere.
    """
    for spell in range(0x40):
        for flag in (0, OPTF_IMPFIRE):
            for rom_target in (0x01, 0x02, 0x08, 0x10):
                bus, cpu = machine()
                setblk(bus, OPT_FLAGS + 2, (flag >> 16) & 0xFF)
                bus.sram[BTLMAG_SPELLINDEX - 0x6000] = spell
                cpu.a = rom_target
                call(cpu, "opt_magictarget", dbr=BANK_0C)
                want = 0x02 if (flag and spell == 1) else rom_target
                check("target: spell %d flag=%d rom=$%02X"
                      % (spell, bool(flag), rom_target), cpu.a & 0xFF, want)


TILESET_PROP, TSA_UL, TSA_UR = 0x0400, 0x0500, 0x0580
GAME_FLAGS = 0x6200
OPTF_OPENCHESTS = 0x00000020
OPENCHEST_UL, OPENCHEST_UR = 0x7E, 0x7F
TP_SPEC_TREASURE, TP_SPEC_MASK, GMFLG_TCOPEN = 0x08, 0x1E, 0x04


def test_openchests():
    """Redraw chests the party has already looted.

    The pass walks the tile property table in RAM and rewrites the top half
    of a chest tile's TSA.  Two things must hold: only chest tiles whose flag
    is set may change, and the index arithmetic must be right -- two property
    bytes per tile against one TSA byte, so an off-by-a-factor-of-two would
    open some unrelated tile in the middle of the map.
    """
    def setup(flag, tiles, opened):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS, flag)
        for i in range(0x100):
            bus.wram[TILESET_PROP + i] = 0
        for i in range(0x80):
            bus.wram[TSA_UL + i] = 0x11
            bus.wram[TSA_UR + i] = 0x22
        for i in range(0x100):
            bus.sram[GAME_FLAGS - 0x6000 + i] = 0
        for tile, chest in tiles.items():
            bus.wram[TILESET_PROP + tile * 2] = TP_SPEC_TREASURE
            bus.wram[TILESET_PROP + tile * 2 + 1] = chest
        for chest in opened:
            bus.sram[GAME_FLAGS - 0x6000 + chest] = GMFLG_TCOPEN
        return bus, cpu

    tiles = {0x42: 3, 0x50: 7, 0x7A: 9}      # three chest tiles
    for flag in (0, OPTF_OPENCHESTS):
        bus, cpu = setup(flag, tiles, opened={3, 9})
        call(cpu, "opt_openchests", dbr=BANK_0C)
        for tile, chest in tiles.items():
            want = (OPENCHEST_UL, OPENCHEST_UR) if (flag and chest in {3, 9}) \
                   else (0x11, 0x22)
            check("tile $%02X chest %d flag=%d" % (tile, chest, bool(flag)),
                  (bus.wram[TSA_UL + tile], bus.wram[TSA_UR + tile]), want)
        #  nothing else in either table may move
        moved = [i for i in range(0x80)
                 if (bus.wram[TSA_UL + i], bus.wram[TSA_UR + i]) != (0x11, 0x22)]
        want_moved = sorted(t for t, ch in tiles.items() if ch in {3, 9}) if flag else []
        check("flag=%d: only opened chest tiles touched" % bool(flag),
              sorted(moved), want_moved)

    #  a chest tile with a non-treasure property must be left alone even when
    #  its would-be chest number is flagged
    bus, cpu = setup(OPTF_OPENCHESTS, {}, opened=set(range(16)))
    for t in range(0x80):
        bus.wram[TILESET_PROP + t * 2] = TP_SPEC_MASK & ~TP_SPEC_TREASURE
        bus.wram[TILESET_PROP + t * 2 + 1] = t & 0x0F
    call(cpu, "opt_openchests", dbr=BANK_0C)
    check("non-chest tiles never change",
          [i for i in range(0x80)
           if (bus.wram[TSA_UL + i], bus.wram[TSA_UR + i]) != (0x11, 0x22)], [])


# --- Shop Information -------------------------------------------------------
#  The descriptions are generated at run time rather than baked, so the thing
#  worth testing is that they agree with the tables in every flag state and
#  that they fit the box.  Twelve columns and seven rows is the whole budget;
#  a line one character over is invisible here and wraps on the console.
OPTDESC = OPTBLOCK + 0x50
F_WEAPONSTATS = 1 << 16
F_CRITRATE = 1 << 20


def _decode(b):
    if b == 0xFF:
        return " "
    if 0x80 <= b <= 0x89:
        return chr(ord("0") + b - 0x80)
    if 0x8A <= b <= 0xA3:
        return chr(ord("A") + b - 0x8A)
    if 0xA4 <= b <= 0xBD:
        return chr(ord("a") + b - 0xA4)
    return {0xBE: "'", 0xBF: ",", 0xC0: ".", 0xC2: "-",
            0xC4: "!", 0xC5: "?", 0xE0: "%", 0xE6: "+"}.get(b)


def describe(itemid, flagbits=0):
    """The lines opt_descgear produces, with the item-name escape marked."""
    bus, cpu = machine()
    for i in range(4):
        setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
    cpu.a = itemid
    call(cpu, "opt_descgear")
    lines, i = [[]], 0
    while i < 0x50:
        b = bus.sram[OPTDESC - 0x6000 + i]
        if b == 0:
            break
        if b == 0x05:                       # single line break
            lines.append([])
        elif b == 0x02:                     # draw an item's name
            lines[-1].append("<%02X>" % bus.sram[OPTDESC - 0x6000 + i + 1])
            i += 1
        else:
            ch = _decode(b)
            if ch is None:
                lines[-1].append("\\x%02X" % b)
            else:
                lines[-1].append(ch)
        i += 1
    return ["".join(l) for l in lines]


def test_shopinfo():
    wep = open(os.path.join(ROOT, "game", "bin", "0C_8000_weapondata.bin"), "rb").read()
    arm = open(os.path.join(ROOT, "game", "bin", "0C_8140_armordata.bin"), "rb").read()

    #  Nothing outside the two ranges has a description, so Select over a
    #  potion or a spell must be a no-op rather than a box full of noise.
    for item in (0x00, 0x01, 0x1B, 0x6C, 0xF0, 0xFF):
        bus, cpu = machine()
        cpu.a = item
        call(cpu, "opt_descgear")
        check("item $%02X has no description" % item, cpu.p & 1, 0)

    over = []
    for flagbits in (0, F_WEAPONSTATS, F_WEAPONSTATS | F_CRITRATE):
        for i in range(40):
            for base in (0x1C, 0x44):
                lines = describe(base + i, flagbits)
                for l in lines:
                    #  <XX> draws as the spell's four-character name.
                    width = len(l) - 4 * l.count("<")
                    if width > 12 or len(lines) > 7:
                        over.append("$%02X/%06X %r" % (base + i, flagbits, l))
    check("every description fits 12 columns and 7 rows", over, [])

    #  The numbers, against the tables they came from.
    bad = []
    for i in range(40):
        w = wep[i * 8:i * 8 + 8]
        a = arm[i * 4:i * 4 + 4]
        on = describe(0x1C + i, F_WEAPONSTATS)
        if on[:3] != ["ATK +%d" % w[1], "HIT +%d" % w[0], "CRT +%d" % w[2]]:
            bad.append("weapon %d with the fix on: %r" % (i, on[:3]))
        #  Vanilla ignores the crit byte and uses the weapon's 1-based index,
        #  so the honest number to show is that one.
        if describe(0x1C + i)[2] != "CRT +%d" % (i + 1):
            bad.append("weapon %d vanilla crit: %r" % (i, describe(0x1C + i)[2]))
        dbl = describe(0x1C + i, F_WEAPONSTATS | F_CRITRATE)[2]
        if dbl != "CRT +%d" % min(255, w[2] * 2):
            bad.append("weapon %d doubled crit: %r" % (i, dbl))
        ar = describe(0x44 + i)
        if ar[:2] != ["DEF +%d" % a[1], "EVA -%d" % a[0]]:
            bad.append("armour %d: %r" % (i, ar[:2]))
    check("descriptions match the weapon and armour tables", bad, [])

    #  The element and category lines describe what the weapon will actually
    #  do, so they appear only once Weapon Stats has wired those bytes up.
    elemental = [i for i in range(40) if wep[i * 8 + 4] or wep[i * 8 + 5]]
    check("some weapon does have an element or a category", elemental != [], True)
    for i in elemental:
        off = describe(0x1C + i)
        on = describe(0x1C + i, F_WEAPONSTATS)
        check("weapon %d bonus lines are hidden while inert" % i,
              len(on) > len(off), True)

    #  Every byte drawn has to be a glyph the menu font actually holds.
    #  LoadMenuCHR loads tiles $80-$FF and nothing else, so FFR's "+" at $7B
    #  came out as kana -- and nothing in the build said so, because the
    #  string was the right length and the right shape.  $C1 is in range but
    #  blank, and $C6/$C7 are the Level and Equip icons.
    CONTROL = {0x00, 0x02, 0x05}
    NOGLYPH = {0xC1, 0xC3, 0xC6, 0xC7}
    stray = set()
    for flagbits in (0, F_WEAPONSTATS, F_WEAPONSTATS | F_CRITRATE):
        for i in range(40):
            for base in (0x1C, 0x44):
                bus, cpu = machine()
                for k in range(4):
                    setblk(bus, OPT_FLAGS + k, (flagbits >> (8 * k)) & 0xFF)
                cpu.a = base + i
                call(cpu, "opt_descgear")
                skip = False
                for j in range(0x50):
                    b = bus.sram[OPTDESC - 0x6000 + j]
                    if b == 0:
                        break
                    if skip:                 # the item id after an escape
                        skip = False
                        continue
                    if b == 0x02:
                        skip = True
                        continue
                    if b in CONTROL:
                        continue
                    if b < 0x80 or b in NOGLYPH:
                        stray.add(b)
    check("every byte drawn is a glyph the menu font has",
          sorted("$%02X" % b for b in stray), [])

    #  The plus is not in the stock font -- mkrom draws one over an unused
    #  kana.  Without this the text would say "+" and the screen would show
    #  a kana, which is exactly what happened the first time.
    font = (1 + 0x09) * 0x10000 + 0x8800        # BANK_MENUCHR, tiles $80-$FF
    at = font + (0xE6 - 0x80) * 16
    glyph = ["".join("X" if (ROMDATA[at + y] >> (7 - x)) & 1 else "."
                     for x in range(8)) for y in range(8)]
    check("the font has a plus sign at $E6", glyph,
          ["........", "........", "....X...", "....X...",
           "..XXXXX.", "....X...", "....X...", "........"])
    check("its background plane is set, like every other glyph",
          set(ROMDATA[at + 8:at + 16]), {0xFF})

    #  Spot checks on the wording, which the sweep above cannot judge.
    check("an all-element weapon says so",
          describe(0x1C + 38, F_WEAPONSTATS)[5], "All Elements")
    check("armour resisting everything says so",
          describe(0x44 + 31)[3], "Resist All")
    check("armour resisting three names two and counts the rest",
          describe(0x44 + 9)[4:6], [" Fire Ice", " and 1 more"])
    check("a weapon nobody can use lists nobody",
          describe(0x1C + 39)[3], "All classes")


# --- the victory poses ------------------------------------------------------
#  The other half of Shop Information: a character who can use whatever the
#  cursor is on raises their arms.  Worth testing against the permission
#  tables directly, because a wrong answer here is a sprite that looks fine
#  and means the opposite of what it says.
OPTPOSE = OPTBLOCK + 0xB0
OPTPOSEIT = OPTBLOCK + 0xB5
F_SHOPINFO = 1 << 12
POSE_VICTORY = 0x0E
CH_CLASS = 0x6100               # unsram + $0100, $40 bytes per character


def _bank0e(addr, n):
    return ROMDATA[(0xA1 + 0x0E - 0xA0) * 0x10000 + addr:][:n]


def test_shoppose():
    wperm = _bank0e(SYM["lut_WeaponPermissions"], 80)
    aperm = _bank0e(SYM["lut_ArmorPermissions"], 80)
    cbits = _bank0e(SYM["lut_ClassEquipBit"], 24)
    #  The twelve permission tables sit right behind their pointer table; the
    #  assertions in bank_0E are what hold that true.
    mperm = _bank0e(SYM["lut_MagicPermisPtr"] + 24, 96)

    def expect(cls, item):
        if item >= 0xB0:
            sp = item - 0xB0
            #  One bit per spell, high bit first, set meaning cannot learn.
            return sp < 64 and (mperm[cls * 8 + (sp >> 3)] & (0x80 >> (sp & 7))) == 0
        if 0x1C <= item < 0x44:
            p = wperm[(item - 0x1C) * 2:][:2]
        elif 0x44 <= item < 0x6C:
            p = aperm[(item - 0x44) * 2:][:2]
        else:
            return False
        cb = cbits[cls * 2:][:2]
        #  A set bit means that class CANNOT use it.
        return ((cb[0] & p[0]) | (cb[1] & p[1])) == 0

    bad = []
    for cls in range(12):
        for item in list(range(0x1C, 0x6C)) + list(range(0xB0, 0xF0)) + [0x00, 0x19, 0x6C, 0xAF]:
            bus, cpu = machine()
            for i in range(4):
                setblk(bus, OPT_FLAGS + i, 0xFF)
            bus.sram[CH_CLASS - 0x6000] = cls
            bus.sram[OPTPOSEIT - 0x6000] = item
            cpu.x = 0
            call(cpu, "opt_canuseit")
            if bool(cpu.p & 1) != expect(cls, item):
                bad.append("class %d item $%02X" % (cls, item))
            if cpu.x != 0:
                bad.append("class %d item $%02X clobbered X" % (cls, item))
    check("who can use what matches the permission tables", bad, [])

    def poses(item, party, flagbits=F_SHOPINFO, cursx=0xA8):
        bus, cpu = machine()
        for i in range(4):
            setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
        for i, c in enumerate(party):
            bus.sram[CH_CLASS - 0x6000 + i * 0x40] = c
            bus.sram[CH_CLASS - 0x6000 + i * 0x40 + 1] = 0   # no ailment
        bus.wram[0x62] = 0                  # cursor on the first item
        bus.wram[0x64] = cursx              # shopcurs_x
        bus.wram[0x300] = item              # item_box[0]
        call(cpu, "opt_setposes")
        return list(bus.sram[OPTPOSE - 0x6000:][:4])

    V, _ = POSE_VICTORY, 0
    party = [0, 1, 2, 5]                    # Fighter, Thief, BlackBelt, BlackMage
    check("a knife: the fighter, the thief and the black mage",
          poses(0x1C + 1, party), [V, V, 0, V])
    check("wooden armour: everyone but the black mage",
          poses(0x44 + 1, party), [V, V, V, 0])
    check("FIRE: only the black mage", poses(0xB0 + 4, party), [0, 0, 0, V])
    check("CURE: nobody in this party", poses(0xB0 + 0, party), [0, 0, 0, 0])
    check("a potion: nobody poses", poses(0x19, party), [0, 0, 0, 0])

    #  The poses must not appear where the flag is off or the question is not
    #  being asked, and they are cleared after every frame because the main
    #  menu and the lineup draw their party with the same DrawOBSprite.
    check("flag off: nobody poses", poses(0x1C + 1, party, flagbits=0), [0, 0, 0, 0])
    check("cursor in the command column: arms down",
          poses(0x1C + 1, party, cursx=0x28), [0, 0, 0, 0])

    #  opt_pose turns DrawOBSprite's stat index back into a character number.
    for i, sx in enumerate((0x00, 0x40, 0x80, 0xC0)):
        bus, cpu = machine()
        for k in range(4):
            bus.sram[OPTPOSE - 0x6000 + k] = 0x10 + k
        cpu.x = sx
        call(cpu, "opt_pose")
        check("stat index $%02X is character %d" % (sx, i), cpu.a, 0x10 + i)
        check("stat index $%02X survives the call" % sx, cpu.x, sx)


# --- Weapon Stats and Double Weapon Crit Rate -------------------------------
#  Vanilla reads none of the three fields this fills.  The crit rate it does
#  set is the weapon's position in the list, which is the number the shop box
#  reports until the flag is on -- and the reason both go through one routine
#  is so that the box and the battle cannot come to disagree.
IB_SCRATCH = 0x6800             # somewhere for a fake in-battle record


def _weaponstats(weapon_id, flagbits):
    bus, cpu = machine()
    for i in range(4):
        setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
    bus.wram[0x80] = IB_SCRATCH & 0xFF          # btl_ib_charstat_ptr
    bus.wram[0x81] = IB_SCRATCH >> 8
    for k in (0x0D, 0x0E, 0x0F):                # poison the three fields
        bus.sram[IB_SCRATCH - 0x6000 + k] = 0xAA
    cpu.a = weapon_id
    call(cpu, "opt_weaponstats")
    at = IB_SCRATCH - 0x6000
    return (bus.sram[at + 0x0F], bus.sram[at + 0x0E], bus.sram[at + 0x0D],
            cpu.a, bool(cpu.p & 2))


def test_weaponstats():
    wep = open(os.path.join(ROOT, "game", "bin", "0C_8000_weapondata.bin"), "rb").read()
    bad = []
    for wid in range(0, 41):
        rec = wep[(wid - 1) * 8:][:8] if wid else None
        for flagbits in (0, F_WEAPONSTATS, F_WEAPONSTATS | F_CRITRATE):
            crit, elem, cat, a, z = _weaponstats(wid, flagbits)
            if wid == 0:
                #  Unarmed: crit zeroed as vanilla's store left it, and the
                #  other two untouched -- the caller already zeroed them.
                want = (0, 0xAA, 0xAA)
            elif not flagbits & F_WEAPONSTATS:
                want = (wid, 0xAA, 0xAA)        # the bug, faithfully
            elif flagbits & F_CRITRATE:
                want = (min(255, rec[2] * 2), rec[4], rec[5])
            else:
                want = (rec[2], rec[4], rec[5])
            if (crit, elem, cat) != want:
                bad.append("weapon %d flags %06X: %r want %r"
                           % (wid, flagbits, (crit, elem, cat), want))
            #  The caller's BEQ runs on what comes back.
            if a != wid or z != (wid == 0):
                bad.append("weapon %d flags %06X: A/Z not preserved" % (wid, flagbits))
    check("the battle gets the right weapon stats", bad, [])

    #  The whole point of the shared accessor: whatever the box prints is
    #  what the battle will roll.
    drift = []
    for flagbits in (0, F_WEAPONSTATS, F_WEAPONSTATS | F_CRITRATE):
        for i in range(40):
            shown = describe(0x1C + i, flagbits)[2]
            rolled = _weaponstats(i + 1, flagbits)[0]
            if shown != "CRT +%d" % rolled:
                drift.append("weapon %d flags %06X: box says %r, battle rolls %d"
                             % (i, flagbits, shown, rolled))
    check("the box and the battle never disagree about crit", drift, [])


# --- spell descriptions -----------------------------------------------------
#  These read the record through opt_spellbyte, which asks the same two
#  routines the battle asks, so a buffed CURE has to describe itself as the
#  thing that will actually be cast.
F_IMPCURE = 1 << 22
F_IMPFIRE = 1 << 23
MAGDATA = ("hitrate", "effectivity", "element", "target",
           "effect", "graphic", "palette", "unused")


def test_spellinfo():
    mag = open(os.path.join(ROOT, "game", "bin", "0C_81E0_magicdata.bin"), "rb").read()

    #  Every spell in every buff state, inside the box.
    over = []
    for flagbits in (0, F_IMPCURE, F_IMPFIRE, F_IMPCURE | F_IMPFIRE):
        for i in range(64):
            lines = describe(0xB0 + i, flagbits)
            for l in lines:
                if len(l) - 4 * l.count("<") > 12 or len(lines) > 7:
                    over.append("spell %d flags %06X %r" % (i, flagbits, l))
    check("every spell description fits the box", over, [])

    #  Nothing past the sixty-four is a spell.
    for item in (0xF0, 0xF8, 0xFF):
        bus, cpu = machine()
        cpu.a = item
        call(cpu, "opt_descgear")
        check("item $%02X is not a spell" % item, cpu.p & 1, 0)

    #  opt_spellbyte against the raw table, and the two fields a buff moves.
    bad = []
    for i in range(64):
        for f in range(8):
            bus, cpu = machine()
            cpu.x, cpu.y = i, f
            call(cpu, "opt_spellbyte")
            if cpu.a != mag[i * 8 + f]:
                bad.append("spell %d %s: %d want %d" % (i, MAGDATA[f], cpu.a, mag[i * 8 + f]))
            if cpu.x != i or cpu.y != f:
                bad.append("spell %d %s clobbered X/Y" % (i, MAGDATA[f]))
    check("unbuffed spell bytes match the table", bad, [])

    #  The buffs, seen through the description rather than the record.
    check("CURE heals more with the flag on",
          (describe(0xB0 + 0)[2], describe(0xB0 + 0, F_IMPCURE)[2]),
          (" 16-32 HP", " 32-64 HP"))
    check("FIRE hits harder with the flag on",
          (describe(0xB0 + 4)[3], describe(0xB0 + 4, F_IMPFIRE)[3]),
          (" 20-40 DMG", " 100-200 DMG"))
    check("HARM stops hitting the whole party",
          (describe(0xB0 + 1)[0], describe(0xB0 + 1, F_IMPFIRE)[0]),
          ("All Enemies", "Single Enemy"))
    check("LAMP gains an ailment it can cure",
          len(describe(0xB0 + 8, F_IMPCURE)) - len(describe(0xB0 + 8)), 1)

    #  The five with no battle routine are named from the table instead.
    for i, want in ((33, "Revive"), (56, "Full Revive"), (38, "Up one floor"),
                    (40, "Heal Stoned"), (41, "Exit dungeon")):
        check("spell %d is named for what it does in a menu" % i,
              describe(0xB0 + i)[-1], want)


# --- the equip and magic menus ----------------------------------------------
#  Only the arithmetic that works out which item or spell the cursor is on;
#  the drawing runs through bank $0E, which this cannot execute.
CH_MAGICDATA = 0x6300           # unsram + $0300, $40 bytes per character


def test_menuinfo():
    #  The equip menu holds equipment slots, not item ids: a 1-based index
    #  with bit 7 set when the piece is worn.
    for slot, equipoff, want in ((0x01, 0x18, 0x1C), (0x28, 0x18, 0x43),
                                 (0x81, 0x18, 0x1C), (0x01, 0x1C, 0x44),
                                 (0x28, 0x1C, 0x6B), (0xA8, 0x1C, 0x6B)):
        bus, cpu = machine()
        bus.wram[0x62] = 3                          # cursor
        bus.wram[0x300 + 3] = slot                  # item_box
        bus.wram[0x66] = equipoff                   # equipoffset
        call(cpu, "opt_equipitem")
        check("equip slot $%02X in menu $%02X is item $%02X" % (slot, equipoff, want),
              (bool(cpu.p & 1), cpu.a), (True, want))
    bus, cpu = machine()
    bus.wram[0x62] = 0
    bus.wram[0x300] = 0
    call(cpu, "opt_equipitem")
    check("an empty equip slot describes nothing", cpu.p & 1, 0)

    #  The magic menu: four slots to a level, eight levels, and the stored
    #  value is which spell of that level the character knows.
    def spell(char, cursor, known):
        bus, cpu = machine()
        #  submenu_targ holds the character number; the three RORs in
        #  UseMagic_GetRequiredMP are what turn it into char << 6.
        bus.wram[0x66] = char
        bus.wram[0x62] = cursor
        bus.sram[CH_MAGICDATA - 0x6000 + (char << 6) + cursor] = known
        call(cpu, "opt_magicspell")
        return bool(cpu.p & 1), cpu.a

    check("character 0, first slot, first spell is CURE", spell(0, 0, 1), (True, 0xB0))
    check("the fourth spell of level 1 is RUSE", spell(0, 3, 4), (True, 0xB3))
    check("level 2 starts eight on", spell(0, 4, 1), (True, 0xB8))
    check("the last level's last spell", spell(0, 31, 8), (True, 0xEF))
    check("another character reads their own list", spell(2, 5, 2), (True, 0xB9))
    check("a slot they have not filled describes nothing", spell(1, 6, 0)[0], False)

    #  OPTCTX decides whether closing the box erases a box or redraws a whole
    #  menu, and it lives in the battery-backed option block.  The shop used
    #  only to clear it on the way out of a menu, so a cartridge holding a
    #  stale value put the menu redraw over a shop: screen off, menu boxes
    #  drawn on top, sprites left standing.  Every entry now says which
    #  screen it is before anything can return early.
    OPTCTX = OPTBLOCK + 0xC1
    for flagbits in (0, F_SHOPINFO):
        for poison in (1, 2, 0xFF):
            bus, cpu = machine()
            for i in range(4):
                setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
            bus.sram[OPTCTX - 0x6000] = poison
            bus.wram[0x22] = 0              # joy_select: nothing pressed
            call(cpu, "opt_shopinfo_body")
            check("a shop never inherits a menu's context ($%02X, flags %d)"
                  % (poison, flagbits), bus.sram[OPTCTX - 0x6000], 0)

    #  And the ids those produce have to be describable.
    for got in (0xB0, 0xB3, 0xEF, 0x1C, 0x43, 0x44, 0x6B):
        bus, cpu = machine()
        for i in range(4):
            setblk(bus, OPT_FLAGS + i, 0xFF)
        cpu.a = got
        call(cpu, "opt_descgear")
        check("item $%02X has a description" % got, cpu.p & 1, 1)


# --- Chest Information ------------------------------------------------------
#  DrawDialogueBox draws every dialogue in the game, so the gate matters more
#  than the drawing does: a conversation must not pick up the stats of
#  whatever was last in a chest.  Only the rejections are checked here -- past
#  them it calls DrawComplexString, which needs a PPU.
F_CHESTINFO = 1 << 13


def _chestinfo(flagbits, dlgsfx, itemid):
    bus, cpu = machine()
    for i in range(4):
        setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
    bus.wram[0x61] = itemid             # dlg_itemid
    bus.wram[0x7D] = dlgsfx             # dlgsfx
    bus.sram[OPTDESC - 0x6000] = 0xAA   # poison: untouched means no description
    try:
        call(cpu, "opt_chestinfo")
    except Exception:
        return "drew"                   # got past the gate, into the PPU
    return "drew" if bus.sram[OPTDESC - 0x6000] != 0xAA else "skipped"


def test_chestinfo():
    #  dlgsfx is what tells a chest from a conversation: OpenTreasureChest
    #  sets it to 1 or 2 for the jingle, and it is zeroed before any other
    #  dialogue.  A stale dlg_itemid must not be enough on its own.
    check("a conversation draws nothing, whatever was last in a chest",
          _chestinfo(F_CHESTINFO, 0, 0x1C), "skipped")
    check("the flag off draws nothing",
          _chestinfo(0, 2, 0x1C), "skipped")
    #  Potions and key items have no description; only gear does.
    for itemid in (0x00, 0x01, 0x19, 0x1B, 0x6C):
        check("a chest holding item $%02X draws nothing" % itemid,
              _chestinfo(F_CHESTINFO, 2, itemid), "skipped")
    for itemid in (0x1C, 0x2F, 0x43, 0x44, 0x6B):
        check("a chest holding item $%02X describes it" % itemid,
              _chestinfo(F_CHESTINFO, 2, itemid), "drew")
    #  The renderer is shared with the shops, so a spell id would describe
    #  itself too -- no chest in the game contains one.
    check("the renderer is the shops own", _chestinfo(F_CHESTINFO, 2, 0xB0), "drew")


# --- Treasures --------------------------------------------------------------
#  Each vehicle is a "does this exist" byte in the first page of unsram whose
#  coordinates lut_InitUnsramFirstPage has already filled in, so granting one
#  is the same single store the game makes when you earn it.  The canal is
#  inverted: it starts set, meaning the waterway is still blocked.
FREE_UNSRAM = 0x6000
FREE_VEHICLE = {"ship_vis": 0x00, "airship_vis": 0x04, "bridge_vis": 0x08,
           "canal_vis": 0x0C, "has_canoe": 0x12}
FREE_DEFAULT = {"ship_vis": 0, "airship_vis": 0, "bridge_vis": 0,
             "canal_vis": 1, "has_canoe": 0}
FREE_BIT = {"ship_vis": 26, "airship_vis": 27, "bridge_vis": 28,
            "canal_vis": 29, "has_canoe": 30}
#  The three key items are plain inventory entries in the same page.
FREE_ITEM = {"item_mystickey": (0x25, 31), "item_chime": (0x2C, 32),
             "item_crown": (0x22, 33), "item_lute": (0x21, 34),
             "item_tail": (0x2D, 35), "item_rod": (0x2A, 36)}


def _freestuff(flagbits):
    bus, cpu = machine()
    for i in range(4):
        setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
    for name, off in FREE_VEHICLE.items():
        bus.sram[FREE_UNSRAM - 0x6000 + off] = FREE_DEFAULT[name]
    call(cpu, "opt_freestuff")
    return {n: bus.sram[FREE_UNSRAM - 0x6000 + off] for n, off in FREE_VEHICLE.items()}


def test_treasures():
    check("with none set, a new game starts as it always did",
          _freestuff(0), FREE_DEFAULT)

    #  Each flag grants its own vehicle and leaves the others alone, which is
    #  what stops "free canal" from also handing over the ship.
    for name, bit in FREE_BIT.items():
        want = dict(FREE_DEFAULT)
        want[name] = 0 if name == "canal_vis" else 1
        check("the flag for %s grants only that" % name,
              _freestuff(1 << bit), want)

    all_on = {n: (0 if n == "canal_vis" else 1) for n in FREE_VEHICLE}
    check("all five together",
          _freestuff(sum(1 << b for b in FREE_BIT.values())), all_on)

    #  The ship and the airship also move.  The ship's own berth is Pravoka,
    #  across a bridge a new party cannot reach, and the airship's is the
    #  desert -- so both go to Coneria, at FFR's coordinates.  The airship's
    #  are the party's starting tile, which is the stored scroll plus seven.
    def coords(flagbits):
        bus, cpu = machine()
        for i in range(4):
            setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
        for off, v in ((0x01, 0xD2), (0x02, 0x99), (0x05, 0xDD), (0x06, 0xED)):
            bus.sram[off] = v               # what lut_InitUnsramFirstPage holds
        call(cpu, "opt_freestuff")
        return tuple(bus.sram[o] for o in (0x01, 0x02, 0x05, 0x06))

    check("untouched, the vehicles keep their own berths",
          coords(0), (0xD2, 0x99, 0xDD, 0xED))
    check("a free ship moves to Coneria's dock",
          coords(1 << FREE_BIT["ship_vis"])[:2], (152, 169))
    check("a free ship leaves the airship where it was",
          coords(1 << FREE_BIT["ship_vis"])[2:], (0xDD, 0xED))
    check("a free airship parks where the party starts",
          coords(1 << FREE_BIT["airship_vis"])[2:], (153, 165))
    check("a free airship leaves the ship where it was",
          coords(1 << FREE_BIT["airship_vis"])[:2], (0xD2, 0x99))

    #  The key items.  items lives at unsram + $20, so the offsets here are
    #  $20 plus each item's own -- KEY is the Mystic Key at +$05.
    def inventory(flagbits):
        bus, cpu = machine()
        for i in range(4 + 1):
            setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
        for off, _ in FREE_ITEM.values():
            bus.sram[off] = 0
        call(cpu, "opt_freestuff")
        return {n: bus.sram[off] for n, (off, _) in FREE_ITEM.items()}

    check("with none set, the party carries no key items",
          inventory(0), {n: 0 for n in FREE_ITEM})
    for name, (_, bit) in FREE_ITEM.items():
        want = {n: 0 for n in FREE_ITEM}
        want[name] = 1
        check("the flag for %s grants only that" % name,
              inventory(1 << bit), want)
    check("all of them together",
          inventory(sum(1 << b for _, b in FREE_ITEM.values())),
          {n: 1 for n in FREE_ITEM})

    #  Bits 32 and 33 live in the fifth flag byte, which only exists because
    #  the block grew; a four-byte word would drop them silently.
    check("the flag word is wide enough to hold them",
          OPT_GOLDXP - OPT_FLAGS, 5)


# --- the menu chirps --------------------------------------------------------
#  The settings screen plays the game's own menu sound effects, which live in
#  bank $0E.  Getting there is a JSL to the trampoline, a JSR inside it, and --
#  for $4007 -- a thunk in the fixed bank into the HAL.  Four banks for one
#  chirp, and the failure mode is silence, which reads as "not implemented
#  yet" rather than as a bug.  So check the registers actually land.
APUSHADOW = 0x0900
SQ2_SFX = 0x7E             # from game/variables.inc


def test_menusfx():
    #  The values PlaySFX_MenuSel and PlaySFX_MenuMove write, read off
    #  game/bank_0E.asm: duty/volume, sweep, and the two timer bytes.
    want = {"opt_sfx_sel":  ((0xBA, 0xBA, 0x40, 0x00), 0x1F),
            "opt_sfx_move": ((0x7A, 0x9B, 0x20, 0x10), 0x10)}
    for name, (regs, frames) in want.items():
        bus, cpu = machine()
        call(cpu, name)
        check("%s writes $4004-$4007" % name,
              tuple(bus.wram[APUSHADOW + 4: APUSHADOW + 8]), regs)
        #  Without this the music driver plays over the effect on the next
        #  note, and the HAL's sweep has no way to tell a replay from silence.
        check("%s claims square 2" % name, bus.wram[SQ2_SFX], frames)

    #  Transparent, as the comment above them promises: they are dropped into
    #  paths that still have a row index in X or a flag mask in A.
    bus, cpu = machine()
    cpu.a, cpu.x, cpu.y = 0x5A, 0x33, 0x77
    cpu.p |= C
    call(cpu, "opt_sfx_sel")
    check("a chirp leaves A, X and Y alone", (cpu.a, cpu.x, cpu.y),
          (0x5A, 0x33, 0x77))
    check("a chirp leaves carry alone", bool(cpu.p & C), True)


# --- House MP Restoration ---------------------------------------------------
#  Vanilla restores the party's MP *after* the save and only if the player
#  said yes, so declining loses it and saving writes a file that still holds
#  the old MP.  The flag moves the restore in front of the save and makes it
#  unconditional.  What is checked here is the hook, not the ordering -- the
#  ordering lives at the call site in bank $0E, where a menu loop waits on a
#  button and nothing can run it.  So: the hook restores when the flag is set,
#  leaves MP alone when it is clear, and skips the characters the game skips.
CH_AILMENTS = 0x6101
CH_CURMP = 0x6320
CH_MAXMP = 0x6328
CH_STRIDE = 0x40
OPTF_HOUSEMP_BIT = 15


def test_housemp():
    def run(flagged, ailments=(0, 0, 0, 0)):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + OPTF_HOUSEMP_BIT // 8, 1 << (OPTF_HOUSEMP_BIT % 8))
        for c in range(4):
            bus.sram[CH_AILMENTS + c * CH_STRIDE - 0x6000] = ailments[c]
            for lvl in range(8):
                bus.sram[CH_MAXMP + c * CH_STRIDE + lvl - 0x6000] = 9
                bus.sram[CH_CURMP + c * CH_STRIDE + lvl - 0x6000] = 0
        call(cpu, "opt_housemp")
        return [bus.sram[CH_CURMP + c * CH_STRIDE - 0x6000] for c in range(4)]

    check("flag clear: a HOUSE does not touch MP here", run(False), [0, 0, 0, 0])
    check("flag set: every living character is refilled", run(True), [9, 9, 9, 9])
    #  The routine it reaches is the game's own, which skips the dead and the
    #  stoned.  Checking that is how we know the trampoline landed on it and
    #  not on whatever else is at that address.
    check("the dead and the stoned are skipped",
          run(True, ailments=(0, 0x01, 0x02, 0)), [9, 0, 0, 9])

    #  ...and the ordering, which is the whole of the second bug: restoring
    #  after the save writes a file that still holds the old MP.  That lives
    #  at the call site, which cannot be run here, so read it instead.  The
    #  save confirmation is "LDA #$1E / JSR MenuSaveConfirm", and it has to
    #  come *after* the JSL, not before it.
    a = SYM["opt_housemp"]
    jsl = bytes([0x22, a & 0xFF, a >> 8, CHUNK_OPT_BANK])
    bank = ROMDATA[(1 + 0x0E) * 0x10000 + 0x8000:][:0x4000]
    at = [i for i in range(len(bank) - 4) if bank[i:i + 4] == jsl]
    check("the hook is called from bank $0E, once", len(at), 1)
    if at:
        after = bank[at[0] + 4: at[0] + 7]
        check("the save confirmation follows the hook",
              (after[0], after[1], after[2]), (0xA9, 0x1E, 0x20))


# --- Increase Elemental and Type Bonus --------------------------------------
#  A physical attack matching the defender's elemental weakness or category
#  gets +40 hit chance on a base of 168 and +4 base damage on a base of the
#  attacker's strength.  The hit half lands; the damage half is under a tenth
#  of a mid-game weapon and is why elemental weapons never felt different.
#  The flag raises the damage half only, through a derived byte, because the
#  use site is in bank $0C where a load costs one byte and a test would cost
#  seven.
OPTD_ELEMDMG_OFF = 0x21          # OPTBLOCK + $21


def test_elembonus():
    #  The dial stores a step worth two, so the derived byte is the step
    #  doubled: 0 is no bonus at all, 2 is vanilla's +4, 25 is the +50 top.
    for step, want in ((0, 0), (2, 4), (5, 10), (15, 30), (21, 42), (25, 50)):
        bus, cpu = machine()
        setblk(bus, OPT_ELEMDMG, step)
        call(cpu, "opt_derive", dbr=CHUNK_OPT_BANK)
        check("dial step %d derives +%d" % (step, want),
              blk(bus, OPTD_ELEMDMG_OFF), want)

    #  Deriving it is only half of it: the use site has to read the byte
    #  rather than the immediate it replaced.  ADC abs is $6D, and the operand
    #  is the derived byte's address.
    addr = OPTBLOCK + OPTD_ELEMDMG_OFF
    want = bytes([0x6D, addr & 0xFF, addr >> 8])
    bank = ROMDATA[(1 + 0x0C) * 0x10000 + 0x8000:][:0x4000]
    check("bank $0C adds the derived byte, once",
          sum(1 for i in range(len(bank) - 3) if bank[i:i + 3] == want), 1)


# --- Better Thief and Ninja -------------------------------------------------
#  FFR's BuffThiefAGI: the Thief starts with 80 agility instead of 10, starts
#  with evade 48 above that instead of 58, and gains agility at every level
#  rather than one time in four.  Only the Thief for the starting stats --
#  promotion keeps what the character grew -- but both classes for the growth,
#  since a promoted character levels on the Thief's data under the Ninja's id.
CH_CLASS = 0x6100
CH_AGIL = 0x6111                 # ch_stats + $11
CH_EVADE = 0x6123                # ch_substats + $03
LVLUP_CHSTATS = 0x86             # zero page pointer
LVLUP_STATBYTE = 0x688E
OPTF_THIEFNINJA_BIT = 19
CLS_TH, CLS_NJ, CLS_FT = 1, 7, 0


def test_thiefninja():
    def start(cls, flagged, which):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + OPTF_THIEFNINJA_BIT // 8,
                   1 << (OPTF_THIEFNINJA_BIT % 8))
        bus.sram[CH_CLASS - 0x6000] = cls
        cpu.x = 0                       # character 0
        cpu.y = cls * 16                # its row in lut_ClassStartingStats
        call(cpu, which)
        return (bus.sram[CH_AGIL - 0x6000], bus.sram[CH_EVADE - 0x6000])

    check("thief, flag clear: vanilla agility",
          start(CLS_TH, False, "opt_startagi")[0], 10)
    check("thief, flag clear: vanilla evade",
          start(CLS_TH, False, "opt_startevade")[1], 58)
    check("thief, flag set: agility 80",
          start(CLS_TH, True, "opt_startagi")[0], 80)
    check("thief, flag set: evade is agility plus 48",
          start(CLS_TH, True, "opt_startevade")[1], 128)
    #  The buff must not leak.  A Fighter reads the table whatever the flag
    #  says, and the table is what the cartridge shipped.
    check("fighter, flag set: still the table's agility",
          start(CLS_FT, True, "opt_startagi")[0], 5)
    check("fighter, flag set: still the table's evade",
          start(CLS_FT, True, "opt_startevade")[1], 53)

    #  ...and the growth byte.  Three shifts either way; the agility bit is
    #  $40 once they have happened, and only a flagged Thief or Ninja gets it.
    def growth(cls, flagged, statbyte):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + OPTF_THIEFNINJA_BIT // 8,
                   1 << (OPTF_THIEFNINJA_BIT % 8))
        bus.sram[CH_CLASS - 0x6000] = cls
        bus.wram[LVLUP_CHSTATS] = CH_CLASS & 0xFF
        bus.wram[LVLUP_CHSTATS + 1] = CH_CLASS >> 8
        bus.sram[LVLUP_STATBYTE - 0x6000] = statbyte
        call(cpu, "opt_thiefgrowth")
        return bus.sram[LVLUP_STATBYTE - 0x6000]

    check("the three shifts happen whatever the flag says",
          growth(CLS_FT, False, 0x10), 0x80)
    check("flag clear: a thief gets no guaranteed agility",
          growth(CLS_TH, False, 0x10), 0x80)
    check("flag set: a thief does", growth(CLS_TH, True, 0x10), 0xC0)
    check("flag set: so does a ninja", growth(CLS_NJ, True, 0x00), 0x40)
    check("flag set: a fighter does not", growth(CLS_FT, True, 0x10), 0x80)


#  ...and the separate flag on the same two classes: hit rate grows by a
#  per-class constant each level -- 3 for the Fighter, 2 for these two, 1 for
#  the mages -- and this doubles theirs.  FFR keeps it a second dropdown and
#  defaults it to Double; here it is a checkbox because there is one useful
#  answer.
OPTF_THIEFHIT_BIT = 21
HITBONUS = {CLS_FT: 3, CLS_TH: 2, CLS_NJ: 2}


def test_thiefhit():
    def grow(cls, flagged, before=50):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + OPTF_THIEFHIT_BIT // 8,
                   1 << (OPTF_THIEFHIT_BIT % 8))
        cpu.a = before
        cpu.x = cls
        cpu.p &= ~0x01                      # carry clear, as the CLC before it
        call(cpu, "opt_hitgrowth")
        return cpu.a & 0xFF

    for cls, name in ((CLS_FT, "fighter"), (CLS_TH, "thief"), (CLS_NJ, "ninja")):
        check("%s, flag clear: the table's bonus" % name,
              grow(cls, False), 50 + HITBONUS[cls])
    check("fighter, flag set: unchanged", grow(CLS_FT, True), 50 + 3)
    check("thief, flag set: doubled", grow(CLS_TH, True), 50 + 4)
    check("ninja, flag set: doubled", grow(CLS_NJ, True), 50 + 4)


def main():
    for t in (test_block, test_presets, test_movespeed, test_encounter,
              test_noshuffle, test_derive, test_guillotine,
              test_battlespeed, test_lineup, test_respondtable, test_msgdraw,
              test_npcmove, test_magicwrap, test_autosort, test_retarget,
              test_runwait, test_idtreasure, test_statusatk, test_goldxp,
              test_fardata, test_repeatpotion, test_buyqty,
              test_statscale, test_isboss, test_scaleenemies,
              test_healroll, test_spellbuff, test_magictarget,
              test_openchests, test_shopinfo, test_shoppose,
              test_weaponstats, test_spellinfo,
              test_menuinfo, test_chestinfo,
              test_treasures, test_menusfx, test_housemp,
              test_elembonus, test_thiefninja, test_thiefhit):
        try:
            t()
        except Exception as e:
            fails.append("%s raised %s: %s" % (t.__name__, type(e).__name__, e))
    if fails:
        print("FAIL (%d)" % len(fails))
        for f in fails:
            print("   " + f)
        return 1
    for s_ in skipped:
        print("   skipped: " + s_)
    print("option hooks: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
