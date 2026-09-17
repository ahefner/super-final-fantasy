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

fails = []


def labels():
    if not os.path.exists(LABELS):
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


def test_noshuffle():
    #  ChkAliveX/Y report the real value when the flag is clear, and "alive"
    #  when it is set -- which is what lets the lineup menu allow the swap.
    for name, reg in (("ChkAliveX", "x"), ("ChkAliveY", "y")):
        for flag, stored, want in ((0, 0x11, 0x11), (0, 0, 0),
                                   (OPTF_NOSHUFFLE, 0x11, 0)):
            bus, cpu = machine()
            setblk(bus, OPT_FLAGS, flag)
            bus.wram[STR_BUF + 3] = stored
            setattr(cpu, reg, 3)
            call(cpu, name, bank=0xA7)
            check("%s flag=%d stored=$%02X" % (name, flag, stored), cpu.a & 0xFF, want)
            check("%s sets Z for the branch" % name,
                  bool(cpu.p & 0x02), want == 0)


def main():
    for t in (test_block, test_presets, test_movespeed, test_encounter, test_noshuffle):
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
