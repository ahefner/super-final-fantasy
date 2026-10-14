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

To check the tests still bite, break the source and confirm a failure appears:
tools/mutate.py does that for a list of mutations at once, each in its own
copy of the tree.  Or corrupt a table in the loaded image.  Search the *upper* half of a chunk when you do: mkrom
mirrors $8000-$FFFF into the low half of every chunk, and that copy is never
addressed, so mutating it proves nothing.  Changing lut_EncDungeonN's vanilla
numerator from 16 to 15 should fail four of the five live base rates.
"""
import os, re, shutil, subprocess, sys

#  Under PyPy the suite takes fifteen seconds where CPython takes seventy: its
#  JIT runs cpu65816's interpreter loop fifteen to twenty-five times faster.
#  So run as a script, this hands itself to pypy3 when it is installed, before
#  loading anything; a light test starts a few tenths of a second slower
#  there.  FFNOPYPY=1 keeps the interpreter it was started with.  pmap's
#  workers import this file under another name and never come through here;
#  they, and run_apart's processes, use whatever this one ended up running on.
if (__name__ == "__main__" and sys.implementation.name != "pypy"
        and not os.environ.get("FFNOPYPY")):
    _pypy = shutil.which("pypy3")
    if _pypy:
        os.execv(_pypy, [_pypy, os.path.abspath(__file__)] + sys.argv[1:])

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from cpu65816 import Bus, CPU, C
#  warm() hashes machines.  Imported here, at startup, and not in warm():
#  under PyPy 8.0.0 importing hashlib pulls in socket, whose IntEnum setup
#  iterates a module dict that PyPy can grow under it, and partway through a
#  long run about half the time it did -- "dictionary changed size during
#  iteration", out of test_rando_chestload.  A fresh interpreter never has.
import hashlib

ROM = os.path.join(ROOT, "SuperFinalFantasy.sfc")
LABELS = os.path.join(ROOT, "out", "labels.txt")

OPTBLOCK = 0x6E00
OPT_MAGIC0, OPT_MAGIC1, OPT_VERSION, OPT_PRESET = 0, 1, 2, 3
#  The flag word is five bytes; everything after it moved when the
#  Treasures section and the free key items took bits 26-33.
OPT_FLAGS, OPT_GOLDXP, OPT_ENCOUNTER = 4, 10, 11
OPT_ENEMY, OPT_BOSS, OPT_ELEMDMG = 12, 13, 14
OPT_THIEFHIT = 15       # the sixth scalar; bit 21 until it took a third value
OPT_STARTITEMS = 16     # the seventh: FFR's starting item set
OPT_RESPOND, OPT_CKSUM = 17, 18
OPT_SIZE = 19
OPT_FORMAT = 9          # bumped when the Free items left the flag word for the key item rows
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

#  Processes to spread work over: the suite's tests, and within a test, a sweep
#  handed to pmap.  -j N on the command line overrides it; -j 1 is the old
#  one-process run, every test in this interpreter in turn.
JOBS = os.cpu_count() or 1


def pmap(fn, jobs):
    """map(fn, jobs), spread over JOBS processes.

    For sweeps of thousands of emulator runs, which is where the suite's time
    goes: test_descsynth was two hundred seconds on one core.  fn must be a
    module-level function, since it is pickled by name, and it must not append
    to fails -- a worker's list dies with the worker.  It returns what it found
    and the caller judges it, which keeps every check in the test itself.
    """
    jobs = list(jobs)
    if JOBS <= 1 or len(jobs) < 64:
        return [fn(j) for j in jobs]
    from concurrent.futures import ProcessPoolExecutor
    #  Small chunks, so a core that finishes early takes more rather than the
    #  sweep waiting on whichever worker was dealt the slow cases.
    with ProcessPoolExecutor(JOBS) as ex:
        return list(ex.map(fn, jobs, chunksize=max(1, len(jobs) // (JOBS * 16))))


def chr_plus():
    """The tile mkrom paints the plus sign onto, from snesmap.inc.

    Parsed rather than written down, because it has moved once already: it was
    $E6 until a character turned to stone and the battle panel read "+tone",
    $E6 being the "S" that panel draws.  Anything here that needs the code gets
    it from the one place the assembler reads.
    """
    code = None
    for line in open(os.path.join(ROOT, "src", "snesmap.inc")):
        m = re.match(r"CHR_PLUS\s*=\s*\$([0-9A-Fa-f]{2})", line.strip())
        if m:
            code = int(m.group(1), 16)
    return code


CHR_PLUS = chr_plus()


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
    #  A routine that ends in RTS leaves the bank byte of the return address
    #  behind, so a run of calls on one CPU walks the stack down a byte each.
    #  In emulation mode it wraps within page 1 harmlessly; once code switches
    #  to native mode it does not, and four hundred calls in, it fell off the
    #  bottom of the page.  The game's own stack never gets near there.
    s = cpu.s
    cpu.run(bank, addr)
    cpu.s = s


def check(what, got, want):
    if got != want:
        fails.append("%-46s got %r, want %r" % (what, got, want))


def blk(bus, off):
    return bus.sram[OPTBLOCK - 0x6000 + off]


def setblk(bus, off, v):
    bus.sram[OPTBLOCK - 0x6000 + off] = v


def flags(bus):
    return int.from_bytes(bus.sram[OPTBLOCK - 0x6000 + OPT_FLAGS:][:6], "little")


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
    #  flags, gold/xp, encounter, enemy, boss, elemental bonus, Thief hit.
    #  The bonus is a step of two, so 2 is vanilla's +4 and 15 the +30 most
    #  of FFR's own presets use.  Improved is FFR's Improved Vanilla: every
    #  quality-of-life row but Auto retargeting (bit 9, off in every preset),
    #  the bugfixes, gold and XP at 200% (step 4), the bonus at +4 -- that
    #  preset's bonus checkbox is off -- and Thief hit at Moderate.  Bit 21
    #  is SOFT in battle and bit 37 White Mage HARM, variations, so Super has
    #  them and Improved does not.  Bits 38 and 39, the Run chance and Turn
    #  order fixes, are bugfixes past the full word: both have them.  Bit 40,
    #  TRANCE's element, is a variation that FFR's Improved Vanilla has, so
    #  Improved has it as well as Super.  Bits 41 and 42, the Lefein map
    #  edits, are quality of life here but off in FFR's Improved Vanilla: Super
    #  only.
    #
    #  No preset starts with items: like the Treasures flags, they are for the
    #  New Game list's FFR presets to set.
    want = {0: (0x0000000000, 2, 10, 3, 3, 2, 0),
            1: (0x01C00007FDFF, 4, 10, 3, 3, 2, 1),
            2: (0x07E003FFFDFF, 5, 6, 3, 3, 15, 2)}
    for preset, (f, g, e, en, bo, el, th) in want.items():
        bus, cpu = machine()
        cpu.a = preset
        #  as opt_init leaves it before its JSR to this routine
        call(cpu, "opt_loadpreset", dbr=CHUNK_OPT_BANK)
        name = ("Vanilla", "Improved", "Super")[preset]
        check("%s: flags" % name, "$%012X" % flags(bus), "$%012X" % f)
        check("%s: gold/xp step" % name, blk(bus, OPT_GOLDXP), g)
        check("%s: encounter step" % name, blk(bus, OPT_ENCOUNTER), e)
        check("%s: enemy step" % name, blk(bus, OPT_ENEMY), en)
        check("%s: boss step" % name, blk(bus, OPT_BOSS), bo)
        check("%s: elemental bonus step" % name, blk(bus, OPT_ELEMDMG), el)
        check("%s: Thief hit step" % name, blk(bus, OPT_THIEFHIT), th)
        check("%s: no starting items" % name, blk(bus, OPT_STARTITEMS), 0)
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
OPTD = 0x13                                  # derived bytes, just past the block
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
    one of the two plates.

    The object id comes from mapobj_id, X -- not from temp RAM.  TalkToObject
    backs the id up into tmp+6 and then overwrites it with the resolved handler
    pointer before dispatching, and tmp through tmp+3 hold the object's four
    bytes of talk data.  An earlier version of both the code and this test read
    tmp, so the plate exemption never fired and the Earth Cave's rod plate gave
    its "nothing happens" line and vanished anyway.  Every case below therefore
    puts a *decoy* in tmp: reading temp RAM again cannot pass this.
    """
    talk_norm, coo = SYM["Talk_norm"], SYM["Talk_CoOGuy"]
    MAPOBJ_ID = 0x6F00                       # mapobj + $00, and mapobj is SRAM
    SLOT = 0x10                              # X is the struct offset, $10 each
    RODPLATE, LUTEPLATE, ORDINARY, OTHER = 0x16, 0x17, 0x20, 0x30
    for flag, objid, decoy, handler, want in (
            (0, ORDINARY, ORDINARY, talk_norm, talk_norm),          # flag off
            (OPTF_GUILLOTINE_HI, ORDINARY, OTHER, talk_norm, coo),  # the whole point
            (OPTF_GUILLOTINE_HI, RODPLATE, OTHER, talk_norm, talk_norm),
            (OPTF_GUILLOTINE_HI, LUTEPLATE, OTHER, talk_norm, talk_norm),
            (OPTF_GUILLOTINE_HI, ORDINARY, OTHER, coo, coo),        # other handlers alone
            #  The two that pin down which byte is read.  A plate with an
            #  ordinary id in tmp must still be spared, and an ordinary object
            #  with a plate id in tmp must still be taken.
            (OPTF_GUILLOTINE_HI, RODPLATE, ORDINARY, talk_norm, talk_norm),
            (OPTF_GUILLOTINE_HI, LUTEPLATE, ORDINARY, talk_norm, talk_norm),
            (OPTF_GUILLOTINE_HI, ORDINARY, RODPLATE, talk_norm, coo),
            (OPTF_GUILLOTINE_HI, ORDINARY, LUTEPLATE, talk_norm, coo)):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 1, flag)
        bus.sram[MAPOBJ_ID - 0x6000 + SLOT] = objid
        for i in range(4):                   # the talk data TalkToObject leaves
            bus.wram[TMP + i] = decoy
        bus.wram[TMP + 6] = handler & 0xFF
        bus.wram[TMP + 7] = handler >> 8
        cpu.x = SLOT
        #  it ends in JMP (tmp+6): run it and see where it lands, not where it
        #  returns
        cpu.pbr, cpu.pc = 0xA7, SYM["OptGuillotine"]
        try:
            for _ in range(200):
                if cpu.pc in (talk_norm, coo) and cpu.pbr == 0xA7:
                    break
                cpu.step()
        except Exception as e:
            fails.append("OptGuillotine raised %s" % e)
            continue
        check("guillotine flag=%d obj=$%02X tmp=$%02X handler=$%04X"
              % (flag, objid, decoy, handler), "$%04X" % cpu.pc, "$%04X" % want)


#  The thirteen reward NPCs: object id, then the state each one's handler reads,
#  as (address, value when "on", value when "off").  An object's visibility is
#  bit 0 of game_flags[id] and its event flag bit 1.
GAME_FLAGS = 0x6200
ITEMS = 0x6020
SHIP_VIS, BRIDGE_VIS, CANAL_VIS, HAS_CANOE = 0x6000, 0x6008, 0x600C, 0x6012
CH_WEAPONS = 0x6118
I_LUTE, I_CROWN, I_CRYSTAL, I_HERB, I_KEY, I_TNT, I_ADAMANT = range(1, 8)
I_ROD, I_CHIME, I_CUBE, I_OXYALE, I_ORB_EARTH = 0x0A, 0x0C, 0x0E, 0x10, 0x15


def vis(obj):
    return ("vis", obj)


def event(obj):
    return ("event", obj)


def item(i):
    return ("byte", ITEMS + i)


TALK_NPCS = {
    #  name: (object id, the state its handler reads)
    "King":       (0x01, [vis(0x12), ("byte", BRIDGE_VIS)]),
    "Princess":   (0x12, [item(I_LUTE)]),
    "Bikke":      (0x04, [event(0x04), ("byte", SHIP_VIS)]),
    "Elf Prince": (0x06, [event(0x06), item(I_KEY)]),
    "Astos":      (0x07, [item(I_CROWN), item(I_CRYSTAL)]),
    "Matoya":     (0x0A, [item(I_CRYSTAL), item(I_HERB), event(0x06)]),
    "Nerrick":    (0x08, [item(I_TNT), ("canal",)]),
    "Smith":      (0x09, [item(I_ADAMANT), ("full",)]),
    "Sarda":      (0x0D, [vis(0x0C), item(I_ROD)]),
    "Canoe Sage": (0x15, [item(I_ORB_EARTH), ("byte", HAS_CANOE)]),
    "CubeBot":    (0x11, [item(I_CUBE)]),
    "Fairy":      (0x13, [item(I_OXYALE)]),
    "Chime":      (0xBB, [event(0x0B), item(I_CHIME)]),
}
#  RANDO_GIVEN's bit n is the table's entry n, in TALK_NPCS's order.
TALK_ENTRY = {name: n for n, name in enumerate(TALK_NPCS)}
#  A state only a gift explains: the Elf Prince wakes on the HERB, and the HERB
#  is Matoya's.  Under the table such a game has her bit set already.
TALK_IMPLIES_GIVEN = {"Matoya": 2}
#  States no game reaches, left out: there is one CRYSTAL, and the HERB that
#  woke the Prince was bought with it, so he cannot be awake while it is held.
TALK_UNREACHABLE = {"Matoya": lambda bits: bits & 4 and bits & 1}


def talk_sequence(job):
    """Talk to one reward NPC three times from one starting state, under the
    vanilla handlers (RANDO_TALK clear) or rando_talk's table (set).  Returns,
    per talk, everything the game could see afterwards."""
    name, bits, generic = job[:3]
    early = job[3] if len(job) > 3 else 0
    obj, state = TALK_NPCS[name]
    bus, cpu = machine()
    s = bus.sram
    SLOT = 0x10
    s[0x6F00 - 0x6000 + SLOT] = obj              # mapobj_id
    s[0x6F01 - 0x6000 + SLOT] = obj              # mapobj_rawid
    s[GAME_FLAGS - 0x6000 + obj] = 1             # the NPC itself is there
    s[CANAL_VIS - 0x6000] = 1                    # the canal is there until Nerrick
    for k, var in enumerate(state):
        on = bits >> k & 1
        if var[0] == "vis":
            s[GAME_FLAGS - 0x6000 + var[1]] = (s[GAME_FLAGS - 0x6000 + var[1]] & ~1) | on
        elif var[0] == "event":
            s[GAME_FLAGS - 0x6000 + var[1]] = (s[GAME_FLAGS - 0x6000 + var[1]] & ~2) | on << 1
        elif var[0] == "byte":
            s[var[1] - 0x6000] = on
        elif var[0] == "canal":                  # Free CANAL: already gone
            s[CANAL_VIS - 0x6000] = 1 - on
        elif var[0] == "full":
            for c in range(4):
                for w in range(4):
                    s[CH_WEAPONS - 0x6000 + c * 0x40 + w] = 1 if on else 0
    s[K["RANDO_TALK"] - 0x6000] = 1 if generic else 0
    s[K["RANDO_EARLY"] - 0x6000] = early
    if generic and name in TALK_IMPLIES_GIVEN and bits >> TALK_IMPLIES_GIVEN[name] & 1:
        n = TALK_ENTRY[name]
        s[K["RANDO_GIVEN"] - 0x6000 + n // 8] |= 1 << n % 8
    out = []
    for _ in range(3):
        for a in (0x7D, 0x44, 0x45, 0x6A):       # dlgsfx, tileprop, btlformation
            bus.wram[a] = 0
        cpu.x = SLOT
        cpu.a = 0
        #  DBR as SwapPRG leaves it: TalkToObject reads its jump table absolute.
        call(cpu, "TalkToObject", bank=0xAF, dbr=0xAF)
        snap = bytearray(s[0:0x2000])
        for a in range(K["RANDO_TALK"], K["RANDO_GIVEN"] + 2):
            snap[a - 0x6000] = 0
        snap[K["RANDO_EARLY"] - 0x6000] = 0       # a setting, not something done
        #  The Smith's event flag: his handler's record of the Xcalber made,
        #  which no other object's dialogue reads; the table records it in
        #  RANDO_GIVEN like every other NPC's.
        snap[GAME_FLAGS - 0x6000 + 0x09] &= ~2
        out.append((cpu.a & 0xFF, bus.wram[0x7D], bus.wram[0x44], bus.wram[0x45],
                    bus.wram[0x6A], bytes(bus.wram[TMP:TMP + 4]), bytes(snap),
                    int.from_bytes(s[K["RANDO_GIVEN"] - 0x6000:][:2], "little")))
    return out


def test_rando_talk():
    """The reward NPCs run from rando_talk's table say and do exactly what the
    vanilla handlers do.  Each NPC is talked to three times from every
    combination of the state its handler reads -- the event it waits for, what
    it wants, whether the party already holds what it gives (a Free item), a
    full bag for the Smith -- once under each, and every talk must leave the
    same dialogue, fanfare, battle, items, flags and map objects behind, all
    of SRAM but the table's own bytes.  Three talks take each from waiting
    through giving to given."""
    jobs = []
    for name, (obj, state) in TALK_NPCS.items():
        for bits in range(1 << len(state)):
            if name in TALK_UNREACHABLE and TALK_UNREACHABLE[name](bits):
                continue
            jobs.append((name, bits, False))
            jobs.append((name, bits, True))
    res = dict(zip(jobs, pmap(talk_sequence, jobs)))
    gave = set()
    for name, (obj, state) in TALK_NPCS.items():
        for bits in range(1 << len(state)):
            if (name, bits, False) not in res:
                continue
            van, gen = res[(name, bits, False)], res[(name, bits, True)]
            for t in range(3):
                check("talk: %s from state %d, talk %d" % (name, bits, t + 1),
                      gen[t][:7], van[t][:7])
            #  The fanfare is something given; the bit given is the NPC's own.
            given = any(v[1] for v in van) or (
                name in TALK_IMPLIES_GIVEN and bits >> TALK_IMPLIES_GIVEN[name] & 1)
            if any(v[1] for v in van):
                gave.add(name)
            check("talk: %s from state %d, the given bits" % (name, bits),
                  "%04X" % gen[2][7], "%04X" % ((1 << TALK_ENTRY[name]) if given else 0))
    #  Wiring: every one of the thirteen gives from some state.  A table entry
    #  that never matched its object would fall through to the vanilla handler
    #  and pass every comparison above.
    check("talk: every reward NPC gives from some state", sorted(gave), sorted(TALK_NPCS))


def test_rando_early():
    """FFR's Early flags.  Early King, Sarda and Sage waive what each of those
    NPCs waits for in rando_talk's table, and nothing else; Early Ordeals is a
    tile change in the cache, the Castle tileset's two thrones losing their
    special code as the reference has it."""
    EK, ES, EG, EO = K["EARLY_KING"], K["EARLY_SARDA"], K["EARLY_SAGE"], K["EARLY_ORDEALS"]
    #  Each waits for something its state 0 lacks: the Princess not rescued,
    #  the Vampire alive, the Earth Orb dark.  Sarda's state 1 is the Vampire
    #  shown, i.e. alive.
    for name, bits, own, line, gift in (("King", 0, EK, 2, (BRIDGE_VIS, 1)),
                                        ("Sarda", 1, ES, 1, (ITEMS + I_ROD, 1)),
                                        ("Canoe Sage", 0, EG, 1, (HAS_CANOE, 1))):
        plain = talk_sequence((name, bits, True, 0))
        early = talk_sequence((name, bits, True, own))
        others = talk_sequence((name, bits, True, 0x0F & ~own))
        obj, _ = TALK_NPCS[name]
        tmp_line = early[0][5][line]
        check("%s waits without its Early flag" % name, plain[0][1], 0)
        check("%s, Early: gives at once, its giving line and the fanfare" % name,
              (early[0][0], early[0][1], early[0][6][gift[0] - 0x6000]), (tmp_line, 1, gift[1]))
        check("%s, Early: the given line after" % name,
              early[1][0], early[1][5][{"King": 3}.get(name, 2)])
        check("%s: the other Early flags change nothing" % name, others, plain)

    #  Waived is not given twice: with the reward already held -- a Free
    #  BRIDGE, ROD or CANOE -- the Early NPC says its given line, as it would
    #  once its event had come.  King state 2: the bridge built, the
    #  Princess not rescued.
    for name, bits, own, line in (("King", 2, EK, 3), ("Sarda", 3, ES, 2), ("Canoe Sage", 2, EG, 2)):
        got = talk_sequence((name, bits, True, own))
        check("%s, Early, the reward held: its given line, nothing given" % name,
              (got[0][0], got[0][1], got[0][7]), (got[0][5][line], 0, 0))

    #  Early Ordeals, in the cache and the reference alike.
    save = K["RANDO_SAVE"] - 0x6000
    for early in (0, EO, 0x0F, 0x07):
        bus, cpu = machine()
        bus.sram[save:save + 4] = (0xC0FFEE11).to_bytes(4, "little")
        bus.sram[K["RANDO_TRAPS"] - 0x6000] = 1
        bus.sram[K["RANDO_EARLY"] - 0x6000] = early
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        check("Early $%02X: the cache's properties are the reference's" % early,
              cache_props(bus), R.build_props(ROMDATA, 0xC0FFEE11, 1, early))
    off, on = R.build_props(ROMDATA, 0, 0, 0), R.build_props(ROMDATA, 0, 0, EO)
    diff = [i for i in range(len(off)) if off[i] != on[i]]
    check("Early Ordeals changes the two thrones and nothing else", diff,
          [K["TS_CASTLE"] * 256 + K["THRONE_TILE1"] * 2, K["TS_CASTLE"] * 256 + K["THRONE_TILE2"] * 2])
    check("...each a crown tile and a teleport, and a plain teleport after",
          [(off[i] & 0x1E, on[i] & 0x1E, on[i] & 0xC0 == off[i] & 0xC0 != 0) for i in diff],
          [(0x0E, 0, True)] * 2)


#  Settings for test_rando_place: Key items, the three item row bytes, the
#  two gear bytes, the Early flags.  BRIDGE free with Masamune and Ribbon is
#  FFR's Beginner; the rest reach overflow, underflow, all loose and Wide.
PLACE_CONFIGS = {
    "beginner":   (1, [0x20, 0x00, 0x00], [0x81, 0x00], 0x0F),
    "late":       (1, [0x20, 0x00, 0x00], [0x81, 0x00], 0x00),
    "bridge":     (1, [0x00, 0x00, 0x00], [0x81, 0x00], 0x0F),
    "everything": (1, [0x00, 0x00, 0x00], [0xFF, 0x01], 0x0F),
    "wide-bare":  (2, [0x00, 0x00, 0x00], [0x00, 0x00], 0x0F),
    "all-loose":  (1, [0x65, 0x55, 0x55], [0x00, 0x00], 0x0F),
    "free-ent":   (2, [0xAA, 0x02, 0x08], [0xFE, 0x01], 0x0F),
}


def place_cart(job):
    """rando_place for one seed and setting: RANDO_PLACED and RANDO_PLACE."""
    seed, (keyitems, items3, gear2, early) = job
    bus, cpu = machine()
    s = bus.sram
    at = K["RANDO_SAVE"] - 0x6000
    s[at:at + 4] = seed.to_bytes(4, "little")
    s[K["RANDO_KEYITEMS"] - 0x6000] = keyitems
    s[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(items3)
    s[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes(gear2)
    s[K["RANDO_EARLY"] - 0x6000] = early
    s[K["RANDO_PLACED"] - 0x6000] = 0x77              # anything but its answer
    call(cpu, "rando_place", bank=RANDO_BANK)
    p = K["RANDO_PLACE"] - 0x6000
    return s[K["RANDO_PLACED"] - 0x6000], list(s[p:p + K["PLACE_ITEMS"]])


def test_rando_place():
    """Incentive placement: rando_place lands every item exactly where
    randoref.build_placement does, for every setting and seed tried, and every
    placement is whole -- each item to place once, in the pool, an incentive
    in a spot unless the spots ran out, nothing else in one, and the caravan,
    a shop, selling an item if anything.  (That each is
    winnable on the world graph itself is tools/checkplace.py's, which needs
    ../worldgraph.)"""
    jobs = [(seed * 7919 + 13, cfg) for cfg in PLACE_CONFIGS.values() for seed in range(12)]
    #  ...and seeds that take a rare path, found by searching randoref with
    #  the path mutated: seed 2 under Beginner weighs the CUBE at between 70
    #  and 75 places reached, where its minimum of 75 says no.  (The halving
    #  of a negative count, the ship and canal raised with one incentive place
    #  reached, and giving up at cycle 15 change no placement in 3,000 seeds of
    #  each setting: FFR's code, kept, that the vanilla world never needs.)
    jobs += [(2, PLACE_CONFIGS["beginner"])]
    res = pmap(place_cart, jobs)
    bad, whole = [], []
    for (seed, cfg), (flag, got) in zip(jobs, res):
        want = R.build_placement(seed, *cfg)
        if (flag, got if flag == 1 else None) != (1 if want else 0, want):
            bad.append((seed, cfg, flag, got, want))
            continue
        free, items, inc, inclocs, masks = R.place_setup(*cfg)
        placed = {c: i for i, c in enumerate(got) if c != 0xFF}
        over = max(0, len(inc) - len(inclocs))
        if (sorted(placed.values()) != items or len(placed) != len(items)
                or any(c >= 248 for c in placed)
                or sum(1 for c, i in placed.items() if i in inc and c not in inclocs) != over
                or any(i not in inc and c in inclocs for c, i in placed.items())
                or any(c == R.CARAVAN and i not in R._SHOPPABLE for c, i in placed.items())):
            whole.append((seed, cfg))
    check("rando_place lands where randoref does", bad[:2], [])
    check("...and every placement is whole", whole[:2], [])
    flag, _ = place_cart((1, (0, [0x20, 0, 0], [0x81, 0], 0x0F)))
    check("Key items Vanilla: no placement", flag, 0)


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
    #  One line, not two.  Chest Information appends a description under this
    #  message when both flags are on, and OPTCHEST_DY is the message's line
    #  count, so one offset only serves both messages if both are one line.
    check("the string is one line", text.count(0x01), 0)
    check("the string's own text is 13 glyphs",
          sum(1 for b in text if b >= 0x7A), 13)

    #  ...and the name that follows it has to fit beside it.  The longest gear
    #  name in the game decides that, so measure it rather than assume: the
    #  pointer table is at $B700 of BANK_ITEMS, which is BANK_DIALOGUE.
    BOX_COLS = 28
    worst = (0, None)
    for item in range(0x1C, 0x6C):
        lo = chunkbyte(0x0A, 0xB700 + item * 2)
        hi = chunkbyte(0x0A, 0xB700 + item * 2 + 1)
        ptr = lo | (hi << 8)
        if not 0x8000 <= ptr <= 0xFFFF:
            continue
        n = 0
        while n < 24:
            b = chunkbyte(0x0A, ptr + n)
            if b in (0x00, 0x01, 0x05):
                break
            n += 1
        if n > worst[0]:
            worst = (n, item)
    check("the longest gear name was found", worst[1] is not None, True)
    for name, glyphs in (("Can't hold.. ", 13), ("You found.. ", 12)):
        check("%r plus the longest name fits %d columns" % (name, BOX_COLS),
              glyphs + worst[0] <= BOX_COLS, True)
    #  Seven, which is the shop list box's interior width and what every weapon
    #  and armour name is.  This recorded 8 until the Ribbon's stray eighth byte
    #  was trimmed -- the assertion had been measuring the bug.  See
    #  test_itemnamewidth, which asserts the rule rather than the maximum.
    check("the longest gear name is 7 glyphs", worst[0], 7)


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

    #  ...and writes nothing on the option page but its own accumulator.  It
    #  ran four bytes from OPTSCRATCH, the second of which is OPTD_ELEMDMG: a
    #  battle that ended off 100% left the weakness bonus at a byte of the
    #  reward until the options were next committed.  A property rather than
    #  that one byte, so the next neighbour is covered too.
    acc = K["OPTREWARD"] - 0x6000
    page = bytes((i * 37 + 11) & 0xFF for i in range(256))
    stray = []
    for step in range(11):
        bus, cpu = machine()
        bus.sram[0xE00:0xF00] = page
        setblk(bus, OPT_GOLDXP, step)
        before = bytes(bus.sram[0xE00:0xF00])
        for i, v in enumerate((0x2C, 0x01, 0x00)):
            bus.wram[BATTLEREWARD + i] = v
        call(cpu, "opt_scalereward", dbr=BANK_0C)
        after = bytes(bus.sram[0xE00:0xF00])
        stray += ["step %d wrote $%02X" % (step, o) for o in range(256)
                  if before[o] != after[o] and not acc - 0xE00 <= o < acc - 0xE00 + 4]
    check("the reward scaler writes only its own four bytes", stray, [])
    bus, cpu = machine()
    call(cpu, "opt_init")
    elem = bus.sram[K["OPTD_ELEMDMG"] - 0x6000]
    setblk(bus, OPT_GOLDXP, 4)
    for i, v in enumerate((0x2C, 0x01, 0x00)):          # 300, at 200%
        bus.wram[BATTLEREWARD + i] = v
    call(cpu, "opt_scalereward", dbr=BANK_0C)
    check("the weakness bonus survives a battle's reward",
          (bus.sram[K["OPTD_ELEMDMG"] - 0x6000], elem > 0), (elem, True))


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
    #  playing -- bad luck looks like bad luck.  It reads the randomizer's copy
    #  now, which copy_rng takes from this table and every battle has built
    #  before its first roll (rando_formdata ensures it); with RNG tables off
    #  that copy is these bytes.
    wrong = []
    for state in range(256):
        bus, cpu = machine()
        call(cpu, "rando_ensure", bank=RANDO_BANK)
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
    bus, cpu = machine()
    call(cpu, "rando_ensure", bank=RANDO_BANK)
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
            0xC4: "!", 0xC5: "?", 0xE0: "%", CHR_PLUS: "+"}.get(b)


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
    #  string was the right length and the right shape.  $C6/$C7 are the Level
    #  and Equip icons.  $C1 was blank and on this list until it became the
    #  plus: it is the one slot in the page with no art of its own, which is
    #  why mkrom paints there and why it is no longer a stray.
    CONTROL = {0x00, 0x02, 0x05}
    NOGLYPH = {0xC3, 0xC6, 0xC7} | ({0xC1} - {CHR_PLUS})
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
    #
    #  Three files have to agree on which kana, so read the code rather than
    #  write it down again: snesmap.inc for the assembler, mkrom.py for the
    #  tile it paints, fftext.inc for what "+" assembles to.
    code = CHR_PLUS
    check("snesmap.inc declares CHR_PLUS", code is not None, True)
    if code is None:
        return
    mk = open(os.path.join(ROOT, "tools", "mkrom.py")).read()
    check("mkrom.py paints the same tile snesmap.inc names",
          ("PLUS_CODE = 0x%02X" % code).lower() in mk.lower(), True)
    ft = open(os.path.join(ROOT, "src", "fftext.inc")).read()
    check("fftext.inc assembles '+' to that tile",
          re.search(r"c = '\+'[^\n]*\n\s*\.byte \$%02X" % code, ft,
                    re.IGNORECASE) is not None, True)

    font = (1 + 0x09) * 0x10000 + 0x8800        # BANK_MENUCHR, tiles $80-$FF
    at = font + (code - 0x80) * 16
    glyph = ["".join("X" if (ROMDATA[at + y] >> (7 - x)) & 1 else "."
                     for x in range(8)) for y in range(8)]
    check("the font has a plus sign at CHR_PLUS", glyph,
          ["........", "........", "....X...", "....X...",
           "..XXXXX.", "....X...", "....X...", "........"])
    check("its background plane is set, like every other glyph",
          set(ROMDATA[at + 8:at + 16]), {0xFF})

    #  And the tile has to be one nothing else draws.  Surveying text to prove
    #  that does not work: $E6 shipped a plus through the "S" of "Stone" and
    #  $EC through "MAGIC", because the top of the font page is battle-UI
    #  artwork -- ailment names at $E2-$EA, command labels at $EB-$F6 -- and
    #  neither is reachable by walking text.  The ailment names are raw tile
    #  bytes behind data_BattleMessages' pointer table; the command labels are
    #  .BYTE runs inside bank $0F.
    #
    #  So ask something that holds without enumerating strings: the stock font
    #  must have no ink in the tile we paint over.  Artwork has ink; a free slot
    #  does not.  $C1 and $FF are the only two blank tiles and $FF is the space.
    #  out/bank_09.bin is the font as assembled, before mkrom's overlay.
    stock = os.path.join(ROOT, "out", "bank_09.bin")
    if not os.path.exists(stock):
        skipped.append("no out/bank_09.bin -- the blank-tile check needs a build")
    else:
        art = open(stock, "rb").read()
        base = 0x0800 + (code - 0x80) * 16      # $8800 holds tiles $80-$FF
        ink = art[base:base + 8]
        check("the tile the plus replaces is blank in the stock font",
              set(ink), {0x00})

    #  Belt and braces: the battle messages are the ones that bit first.
    blob = open(os.path.join(ROOT, "game", "bin",
                             "0B_8C40_battlemessages.bin"), "rb").read()
    BASE, PTRS = 0x8C40, 0x310
    drawn, seen = set(), 0
    for i in range((len(blob) - PTRS) // 2):
        a = blob[PTRS + i*2] | (blob[PTRS + i*2 + 1] << 8)
        o = a - BASE
        if not (0 <= o < PTRS):
            continue                    # not a pointer into the text
        end = blob.find(b"\x00", o)
        if end < 0:
            continue
        seen += 1
        drawn |= {b for b in blob[o:end] if b >= 0x7A}
    check("the battle message table still reads", seen > 50, True)
    check("the plus does not sit on a tile a battle message draws",
          "$%02X" % code if code in drawn else None, None)

    #  Spot checks on the wording, which the sweep above cannot judge.
    check("an all-element weapon says so",
          describe(0x1C + 38, F_WEAPONSTATS)[5], "All Elements")
    check("armour resisting everything says so",
          describe(0x44 + 31)[3], "Resist All")
    #  The Dragon Armour, and the reason the layout changed: three elements in
    #  the two lines that used to name two and spend a third on "and 1 more".
    check("armour resisting three names all three",
          describe(0x44 + 9)[3:5], ["Resist Fire", " Ice, Lit."])
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
    #  POSE_VICTORY in one slot and zero in the others, so the value proves
    #  which byte was read rather than merely that some byte was.
    def posemachine(flagbits):
        bus, cpu = machine()
        for i in range(4):
            setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
        return bus, cpu

    for i, sx in enumerate((0x00, 0x40, 0x80, 0xC0)):
        bus, cpu = posemachine(F_SHOPINFO)
        for k in range(4):
            bus.sram[OPTPOSE - 0x6000 + k] = POSE_VICTORY if k == i else 0
        cpu.x = sx
        call(cpu, "opt_pose")
        check("stat index $%02X is character %d" % (sx, i), cpu.a, POSE_VICTORY)
        check("stat index $%02X survives the call" % sx, cpu.x, sx)

    #  DrawOBSprite adds this byte to its tile base with CLC / ADC and no range
    #  check, so a byte that is neither pose draws the character out of another
    #  class's CHR.  The poses are scratch in SRAM above the checksummed
    #  settings, so a cartridge that has never been through a shop presents
    #  whatever the battery held -- $FF on a fresh one, which made the base
    #  tmp-1.  Both locks are checked: the flag test, which also covers the
    #  hook site being an unconditional JSL, and the clamp behind it.
    for name, flag, val in (("flag off",            0,          0xFF),
                            ("flag off, zero",      0,          0x00),
                            ("flag on, fresh SRAM", F_SHOPINFO, 0xFF),
                            ("flag on, mid-range",  F_SHOPINFO, 0x7F),
                            ("flag on, just over",  F_SHOPINFO, 0x0F)):
        bus, cpu = posemachine(flag)
        for k in range(4):
            bus.sram[OPTPOSE - 0x6000 + k] = val
        cpu.x = 0x00
        call(cpu, "opt_pose")
        check("%s: no tile offset" % name, cpu.a, 0)


# --- no description line may overflow the box it is drawn in ------------------
#  The binding box is the shop's: OPTINFO_W is $0E, so twelve usable columns.
#  The chest's is full width, twenty-eight.  Nothing guarded this, which is how
#  the element words came to be cut to four characters with no record of why --
#  "<element> Element" is twelve exactly, and "Lightning Element" is seventeen.
#
#  FFR solves it the same way and keeps both forms: ShopInformation.cs carries a
#  long and a short name per element, spells the name out when an armour has
#  exactly one resistance, and uses the short forms for the lines that carry two
#  names and for the element line.
def test_descwidth():
    OPTDESC_A, OPTCTX_A, DLG_ITEMID = 0x6E50, 0x6EC1, 0x61
    NARROW, CHEST = 12, 28          # OPTINFO_W - 2, and a full-width box

    def lines(item, ctx):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, 0xFF)
        bus.sram[OPTDESC_A - 0x6000: OPTDESC_A - 0x6000 + 0x50] = bytes(0x50)
        bus.sram[OPTCTX_A - 0x6000] = ctx
        bus.wram[DLG_ITEMID] = item
        cpu.a = item
        call(cpu, "opt_descgear")
        if not (cpu.p & 0x01):
            return []
        buf = bytes(bus.sram[OPTDESC_A - 0x6000: OPTDESC_A - 0x6000 + 0x50])
        end = buf.find(0)
        #  Only $05 breaks a line; everything else is one tile or a code below
        #  $1A, and opt_emit is the only writer.
        return buf[:end].split(b"\x05")

    everything = list(range(0x1C, 0x6C)) + [0xB0 + s for s in range(64)]
    for ctx, cols, label in ((0, NARROW, "shop"), (1, NARROW, "equip"),
                             (2, NARROW, "magic"), (3, CHEST, "chest")):
        worst = (0, None, None)
        for item in everything:
            for ln in lines(item, ctx):
                if len(ln) > worst[0]:
                    worst = (len(ln), ln, item)
        check("%s: longest line within %d columns" % (label, cols),
              worst[0] <= cols, True)
        if worst[0] > cols:
            fails.append("   %s: item $%02X needs %d columns: %r"
                         % (label, worst[2], worst[0], worst[1]))

    #  And the single-resistance case spells the element out, as FFR does.
    arm = open("game/bin/0C_8140_armordata.bin", "rb").read()
    singles = [68 + i for i in range(len(arm) // 4)
               if bin(arm[i * 4 + 2]).count("1") == 1]
    check("the cartridge has armour with one resistance", len(singles), 8)
    bad = None
    for item in singles:
        body = b"\x05".join(lines(item, 3))
        #  "Resistance" is eleven glyphs where "Resist" is six, so the long
        #  header is the tell, and no four-letter abbreviation should appear.
        if len(lines(item, 3)) < 2:
            bad = ("$%02X has no resistance line" % item,); break
    check("every single-resistance armour names it on its own line", bad, None)



# --- the description fits the box for records the cartridge never had --------
_descrom = None                 # each process's own copy of the image to patch


def _descgear(job):
    """opt_descgear's buffer for one synthetic record, or None if it declines.

    test_descsynth's unit of work, at module level so pmap can send it to
    another process.  The record arrives as bytes and is put back afterwards,
    so one copy of the image per process serves every job that process gets.
    """
    global _descrom
    at, rec, item, ctx = job
    if _descrom is None:
        _descrom = bytearray(ROMDATA)
    was = bytes(_descrom[at:at + len(rec)])
    _descrom[at:at + len(rec)] = rec
    try:
        bus, cpu = machine()
        bus.rom = _descrom
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, 0xFF)
        bus.sram[0x6E50 - 0x6000: 0x6E50 - 0x6000 + 0x50] = bytes(0x50)
        bus.sram[0x6EC1 - 0x6000] = ctx
        bus.wram[0x61] = item
        cpu.a = item
        call(cpu, "opt_descgear")
        if not (cpu.p & 0x01):
            return None
        buf = bytes(bus.sram[0x6E50 - 0x6000: 0x6E50 - 0x6000 + 0x50])
        end = buf.find(0)
        return buf[:end] if end >= 0 else buf
    finally:
        _descrom[at:at + len(rec)] = was


#  test_descwidth above sweeps the fifty-two items the cartridge ships, which
#  is a regression test and nothing more: Phase 3 randomises these records, so
#  passing it says nothing about what a generator can produce.
#
#  The weapon and armour records ARE the description's only inputs, though, so
#  driving the bytes directly covers every item that could ever exist.  Each
#  byte is swept over all 256 values with the others at their worst, which
#  catches a line too wide for its box; then every axis's worst value is
#  applied at once, because the axes land on separate lines and the thing they
#  share is the eighty-byte buffer that opt_emit truncates in silence.
#
#  This found a real fault when it was written.  " Pois and 2+" is twelve
#  columns and fits; the first draft emitted a space before the word " and ",
#  which already carries its own, and thirteen columns wrote over the border.
#  No cartridge armour has four resistances, so nothing in the cartridge sweep
#  could have reached it -- and a randomiser reaches it immediately.
def test_descsynth():
    NARROW, CHEST = 12, 28          # OPTINFO_W - 2, and a full-width box
    ROWS, ROWS_CHEST = 7, 8         # OPTINFO_H leaves seven text rows

    #  NES bank $0C runs at chunk $A1+$0C, and the image wraps banks at 32.
    IMG = ((0xA1 + 0x0C) & 0x1F) * 0x10000
    WEP_OFF, ARM_OFF = IMG + 0x8000, IMG + 0x8140
    for off, name in ((WEP_OFF, "0C_8000_weapondata.bin"),
                      (ARM_OFF, "0C_8140_armordata.bin")):
        blob = open(os.path.join(ROOT, "game", "bin", name), "rb").read()
        if ROMDATA[off:off + len(blob)] != blob:
            fails.append("   the %s offset is wrong -- sweeping nothing" % name)
            return

    WEP0, ARM0 = 28, 68             # the first weapon's and armour's item ids

    #  Offset within the record, the value that makes its line longest, and the
    #  values the field can hold.  Everything is a free byte except the spell,
    #  which is 1-based into the sixty-four spells with 0 for none; the count of
    #  spells is fixed, so no index outside that can arise.
    SPELLS = range(65)
    BYTE = range(256)
    WEP = ((0, "hit", 99, BYTE), (1, "damage", 99, BYTE), (2, "crit", 99, BYTE),
           (3, "spell", 33, SPELLS), (4, "element", 0xFF, BYTE),
           (5, "category", 0xFF, BYTE))
    ARM = ((0, "evade", 99, BYTE), (1, "absorb", 99, BYTE),
           (2, "resist", 0x0F, BYTE), (3, "spell", 33, SPELLS))

    def record(stride, fields):
        rec = bytearray(stride)
        for off, val in fields:
            rec[off] = val
        return bytes(rec)

    def desc(raw):
        """The lines as the screen will show them, and the bytes they cost.

        These are two different numbers and both matter.  Control code $02 is
        two bytes in the buffer that draw a four-glyph spell name on screen, so
        counting bytes understates the width by two and counting the escape as
        text overstates it.  Spell names are exactly four glyphs -- genspellnames
        fails the build otherwise -- so the placeholder below is the true width.
        """
        if raw is None:
            return None
        out, i = [[]], 0
        while i < len(raw):
            b = raw[i]
            if b == 0x05:
                out.append([])
            elif b == 0x02:
                out[-1].append("name")          # four glyphs, as wide as it draws
                i += 1
            else:
                ch = _decode(b)
                out[-1].append(ch if ch is not None else "\\x%02X" % b)
            i += 1
        return ["".join(l) for l in out], len(raw)

    worst_line, worst_total, worst_rows = (0, None, None), (0, None), (0, None)
    over, nover = [], [0]           # a few examples, and how many there were

    def measure(raw, cols, rows, label):
        nonlocal worst_line, worst_total, worst_rows
        got = desc(raw)
        if got is None:
            return
        ls, total = got
        nover[0] += sum(1 for ln in ls if len(ln) > cols) + (len(ls) > rows)
        for ln in ls:
            if len(ln) > worst_line[0]:
                worst_line = (len(ln), ln, label)
            if len(ln) > cols and len(over) < 4:
                over.append("   %s: %d columns in a %d-column box: %r"
                            % (label, len(ln), cols, ln))
        if total > worst_total[0]:
            worst_total = (total, label)
        if len(ls) > worst_rows[0]:
            worst_rows = (len(ls), label)
        if len(ls) > rows and len(over) < 4:
            over.append("   %s: %d rows in a %d-row box" % (label, len(ls), rows))

    #  Two boxes, not four.  Inside opt_descgear the only context test is
    #  opt_castline's CPX #OPTCTX_CHEST, so the shop, equip and magic contexts
    #  generate the same bytes and sweeping all three triples the work for
    #  nothing.  That equivalence is asserted below rather than assumed.
    boxes = ((0, NARROW, ROWS, "narrow"), (3, CHEST, ROWS_CHEST, "chest"))

    #  Every value of every byte, with the rest of the record at its worst.
    #  The cases are dealt out first and run by pmap, then judged in order.
    cases = []
    for base, stride, spec, item0, kind in ((WEP_OFF, 8, WEP, WEP0, "weapon"),
                                            (ARM_OFF, 4, ARM, ARM0, "armour")):
        for off, name, _w, domain in spec:
            for val in domain:
                rec = record(stride, [(o, val if o == off else w)
                                      for o, _n, w, _d in spec])
                for ctx, cols, rows, box in boxes:
                    cases.append(((base, rec, item0, ctx), cols, rows,
                                  "%s %s=$%02X %s" % (kind, name, val, box)))

        #  and every axis at its worst at the same time, for the buffer
        rec = record(stride, [(o, w) for o, _n, w, _d in spec])
        for ctx, cols, rows, box in boxes:
            cases.append(((base, rec, item0, ctx), cols, rows,
                          "%s worst-case %s" % (kind, box)))

    for raw, (_job, cols, rows, label) in zip(pmap(_descgear, [c[0] for c in cases]),
                                              cases):
        measure(raw, cols, rows, label)

    #  The claim the sweep above rests on: the three narrow contexts agree.
    #  Checked across the records that exercise every branch of the thing that
    #  could tell them apart -- a casting item, a resistance list and neither.
    same = True
    for fields, base, stride, item0 in (
            (((0, 99), (1, 99), (2, 0x0F), (3, 33)), ARM_OFF, 4, ARM0),
            (((0, 99), (1, 99), (2, 0x0F), (3, 0)), ARM_OFF, 4, ARM0),
            (((4, 0xFF), (5, 0xFF), (3, 33)), WEP_OFF, 8, WEP0)):
        rec = record(stride, fields)
        got = [desc(_descgear((base, rec, item0, c))) for c in (0, 1, 2)]
        if got[0] != got[1] or got[1] != got[2]:
            same = False
    check("the shop, equip and magic contexts generate the same text", same, True)

    check("every generated description fits its box", nover[0], 0)
    fails.extend(over)

    #  Recorded so a change that eats the margin is visible in the diff rather
    #  than only when something finally overflows.
    check("the widest generated line", worst_line[0], 12)
    check("the longest generated description", worst_total[0], 66)
    check("the tallest generated description", worst_rows[0], 7)

# --- the "Cast" line, and the two renderers it has to satisfy ----------------
#  The renderers differ in one way that decides this.  DrawComplexString's
#  item-name code pages in BANK_ITEMS itself, so the shop, equip and magic boxes
#  can use control code $02 and not care which bank is mapped.
#  DrawDialogueString's $02 reads lut_ItemNamePtrTbl straight out of whatever
#  bank is mapped -- and its line breaks map whatever cur_bank names, which has
#  to be the options chunk or the RTS out of the renderer lands in another
#  bank's data.  Naming the dialogue bank read the table and then crashed.
#
#  So the chest path expands the name itself, out of lut_SpellNames.
def test_castline():
    OPTDESC_A, OPTCTX_A, DLG_ITEMID = 0x6E50, 0x6EC1, 0x61
    OPTCTX_SHOP, OPTCTX_CHEST = 0, 3
    CUR_BANK, CHUNK_OPT_NES = 0x57, 0x11
    MG_START, WIDTH = 0xB0, 4

    wep = open("game/bin/0C_8000_weapondata.bin", "rb").read()
    arm = open("game/bin/0C_8140_armordata.bin", "rb").read()
    casters = [(28 + i, wep[i * 8 + 3] - 1)
               for i in range(len(wep) // 8) if wep[i * 8 + 3]]
    casters += [(68 + i, arm[i * 4 + 3] - 1)
                for i in range(len(arm) // 4) if arm[i * 4 + 3]]
    check("the cartridge has gear that casts", len(casters), 12)

    def build(item, ctx):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, 0xFF)
        bus.sram[OPTDESC_A - 0x6000: OPTDESC_A - 0x6000 + 0x50] = bytes(0x50)
        bus.sram[OPTCTX_A - 0x6000] = ctx
        bus.wram[DLG_ITEMID] = item
        cpu.a = item
        call(cpu, "opt_descgear")
        buf = bytes(bus.sram[OPTDESC_A - 0x6000: OPTDESC_A - 0x6000 + 0x50])
        end = buf.find(0)
        return buf[:end], bus.wram[DLG_ITEMID]

    #  The name the cartridge holds, read through its own pointer table in the
    #  built image -- not through our copy, so the two derivations are separate.
    def cartridge_name(slot):
        item = MG_START + slot
        p = (chunkbyte(0x0A, 0xB700 + item * 2)
             | (chunkbyte(0x0A, 0xB700 + item * 2 + 1) << 8))
        return bytes(chunkbyte(0x0A, p + k) for k in range(WIDTH))

    bad = None
    for item, slot in casters:
        body, dlg = build(item, OPTCTX_CHEST)
        if not body.endswith(cartridge_name(slot)):
            bad = ("$%02X names the wrong spell" % item,); break
        if 0x02 in body:
            bad = ("$%02X still uses control code $02" % item,); break
        if dlg != item:
            bad = ("$%02X clobbered dlg_itemid" % item,); break
    check("every casting item names its spell in a chest", bad, None)

    bad = None
    for item, slot in casters:
        body, _ = build(item, OPTCTX_SHOP)
        if body[-2:] != bytes([0x02, MG_START + slot]):
            bad = ("$%02X" % item, body[-2:].hex()); break
    check("every casting item still uses $02 in a shop", bad, None)

    for item in (0x1C, 0x44):
        for ctx in (OPTCTX_SHOP, OPTCTX_CHEST):
            body, _ = build(item, ctx)
            check("item $%02X has no cast line (ctx %d)" % (item, ctx),
                  0x02 in body, False)

    #  Our copy has to agree with the cartridge for all 64.
    tbl = SYM["lut_SpellNames"]
    bad = None
    for slot in range(64):
        ours = bytes(chunkbyte(0x11, tbl + slot * WIDTH + k) for k in range(WIDTH))
        if ours != cartridge_name(slot):
            bad = (slot, ours.hex()); break
    check("lut_SpellNames matches the cartridge", bad, None)

    #  The invariant that cost a crash.
    start = SYM["opt_chestinfo"]
    body = bytes(chunkbyte(0x11, start + i) for i in range(160))
    tgt = SYM["DrawDialogueString_PtrLoaded"]
    at = body.find(bytes([0x20, tgt & 0xFF, tgt >> 8]))
    check("opt_chestinfo calls the dialogue renderer", at >= 0, True)
    if at >= 0:
        check("it names the options chunk before rendering",
              bytes([0xA9, CHUNK_OPT_NES, 0x85, CUR_BANK]) in body[:at], True)


# --- the shortened chest dialogue --------------------------------------------
#  Dialogue $F0 is three lines, and Chest Information appends up to six more, so
#  the longest items need ten rows in a box that holds nine.  Folding the three
#  into one leaves eight.  opt_dlgident swaps the pointer, the same way Identify
#  Treasures swaps $F1.
def test_youfound():
    F_IDTREASURE = (0, 0x10)                    # bit 4
    F_CHESTINFO = (1, 0x20)                     # bit 13
    DLGID_TCGET, DLGID_CANTCARRY = 0xF0, 0xF1
    TEXT_PTR = 0x3E                             # text_ptr, zero page

    def swapped(dlgid, idtreasure=False, chestinfo=False):
        bus, cpu = machine()
        for i in range(5):
            v = 0
            if idtreasure and i == F_IDTREASURE[0]: v |= F_IDTREASURE[1]
            if chestinfo and i == F_CHESTINFO[0]: v |= F_CHESTINFO[1]
            setblk(bus, OPT_FLAGS + i, v)
        bus.wram[TEXT_PTR] = 0xAA               # poison: untouched means no swap
        bus.wram[TEXT_PTR + 1] = 0xAA
        cpu.x = (dlgid * 2) & 0xFF              # as DrawDialogueString leaves it
        call(cpu, "opt_dlgident")
        got = bus.wram[TEXT_PTR] | (bus.wram[TEXT_PTR + 1] << 8)
        return got

    UNTOUCHED = 0xAAAA
    youfound, canthold = SYM["lut_YouFound"], SYM["lut_CantHoldWhat"]

    #  The chest get, which is the overflow being fixed.
    check("TCGET with Chest Information on",
          swapped(DLGID_TCGET, chestinfo=True), youfound)
    check("TCGET with it off keeps the cartridge wording",
          swapped(DLGID_TCGET), UNTOUCHED)
    #  Identify Treasures is a different flag and must not stand in for it.
    check("TCGET with only Identify Treasures on",
          swapped(DLGID_TCGET, idtreasure=True), UNTOUCHED)

    #  The full-inventory message still belongs to Identify Treasures alone.
    check("CANTCARRY with Identify Treasures on",
          swapped(DLGID_CANTCARRY, idtreasure=True), canthold)
    check("CANTCARRY with only Chest Information on",
          swapped(DLGID_CANTCARRY, chestinfo=True), UNTOUCHED)
    check("CANTCARRY with both on", 
          swapped(DLGID_CANTCARRY, idtreasure=True, chestinfo=True), canthold)
    check("TCGET with both on", 
          swapped(DLGID_TCGET, idtreasure=True, chestinfo=True), youfound)

    #  Every other dialogue in the game is left alone, both flags on.
    bad = None
    for dlgid in range(0x80, 0x100):
        if dlgid in (DLGID_TCGET, DLGID_CANTCARRY):
            continue
        if swapped(dlgid, idtreasure=True, chestinfo=True) != UNTOUCHED:
            bad = dlgid; break
    check("no other dialogue is swapped", bad, None)

    #  And the string really is one line: no break code before the name.
    off = youfound - 0xC000
    #  walk it out of the image via the fixed bank's copy in chunk 0
    base = ROMDATA.find(bytes([0xA2, 0xB2, 0xB8, 0xFF, 0xA9, 0xB2, 0xB8, 0xB1, 0xA7]))
    check("lut_YouFound is in the image", base >= 0, True)
    if base >= 0:
        body = ROMDATA[base:base + 16]
        end = body.find(0x00)
        lines = body[:end].count(0x01) + 1
        check("one line, no break code", lines, 1)
        check("ends with the item-name code", body[end - 1], 0x02)

        #  The invariant the two halves share: the description starts on the
        #  first row the message does not occupy, so the offset is the message's
        #  line count.  Leaving it at the cartridge's 3 after shortening the
        #  string to 1 left a blank line and still overran the box.
        import re as _re
        dy = int(_re.search(r'^OPTCHEST_DY\s*=\s*(\d+)',
                            open('src/snesmap.inc').read(), _re.M).group(1))
        check("OPTCHEST_DY matches the message's line count", dy, lines)


# --- Cast Life in Battle, the two messages -----------------------------------
#  With the spell working it narrated itself wrongly twice.  Both are vanilla
#  data that only had to make sense for a spell that could not be cast.
def test_lifemessages():
    F_CASTLIFE = (3, 0x01)
    SPELL_CURE, SPELL_LAMP, SPELL_PURE = 0, 8, 24
    SPELL_LIFE, SPELL_LIF2 = 33, 56
    INEFFECTIVENOW, CURED_1, SLAIN = 0x4A, 0x0D, 0x14

    def flags_on(bus, on):
        for i in range(5):
            setblk(bus, OPT_FLAGS + i,
                   F_CASTLIFE[1] if (on and i == F_CASTLIFE[0]) else 0)

    def msg(spell, castlife):
        bus, cpu = machine()
        flags_on(bus, castlife)
        cpu.x = spell
        call(cpu, "opt_magicmsg")
        return cpu.a, bool(cpu.p & 0x02)        # value, Z

    def cured(counter, castlife):
        bus, cpu = machine()
        flags_on(bus, castlife)
        cpu.x = counter
        call(cpu, "opt_curedmsg")
        return cpu.a, bool(cpu.p & 0x02)

    #  Vanilla really does hand LIFE the "ineffective" message, and really does
    #  hand PURE and LAMP nothing -- which is the convention being copied.
    check("LIFE's cartridge message is INEFFECTIVENOW",
          msg(SPELL_LIFE, False)[0], INEFFECTIVENOW)
    check("LIF2's too", msg(SPELL_LIF2, False)[0], INEFFECTIVENOW)
    check("PURE carries none", msg(SPELL_PURE, False), (0x00, True))
    check("LAMP carries none", msg(SPELL_LAMP, False), (0x00, True))

    #  With the flag on, the two Life spells say nothing, and Z is set so the
    #  caller's BEQ skips the message box.
    check("LIFE silent with the flag on", msg(SPELL_LIFE, True), (0x00, True))
    check("LIF2 silent with the flag on", msg(SPELL_LIF2, True), (0x00, True))
    #  Everything else keeps its own, flag either way.
    for name, spell in (("CURE", SPELL_CURE), ("PURE", SPELL_PURE),
                        ("LAMP", SPELL_LAMP)):
        check("%s unchanged by the flag" % name,
              msg(spell, True)[0], msg(spell, False)[0])

    #  The cured-ailment message.  Counter 8 is AIL_DEAD, bit 0; 6 is POISON.
    check("DEAD cured, flag off: SLAIN", cured(8, False)[0], SLAIN)
    check("DEAD cured, flag on: CURED", cured(8, True)[0], CURED_1)
    for counter in range(1, 8):
        want = CURED_1 - 1 + counter
        check("counter %d unchanged, flag off" % counter, cured(counter, False)[0], want)
        check("counter %d unchanged, flag on" % counter, cured(counter, True)[0], want)
    #  ...and never zero, since the caller branches on BNE.
    for counter in range(1, 9):
        for on in (False, True):
            check("counter %d nonzero, flag %s" % (counter, "on" if on else "off"),
                  cured(counter, on)[1], False)

    #  The wiring for both.
    for name in ("opt_magicmsg", "opt_curedmsg"):
        tgt = SYM[name]
        jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
        check("the battle calls %s" % name, jsl in ROMDATA, True)


# --- Cast Life in Battle, reaching a corpse at all ---------------------------
#  Battle_PlMag_TargetOnePlayer refuses a dead or stoned target before the spell
#  effect is reached, which is why the record and the HP were both beside the
#  point on their own: the only party member LIFE is for is the one the
#  targeting rejects.  Z set means valid.
def test_playervalid():
    F_CASTLIFE = (3, 0x01)
    LIFE, LIF2 = 0x01, 0x81
    CUREAILMENT = 0x08
    AIL_DEAD, AIL_STONE, AIL_POISON = 0x01, 0x02, 0x04
    OBROM = 0x92                                # btl_entityptr_obrom, zero page
    STATS = 0x0400                              # somewhere in low RAM for the stats

    def valid(ailments, effect, effectivity, castlife=True):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i,
                   F_CASTLIFE[1] if (castlife and i == F_CASTLIFE[0]) else 0)
        bus.wram[OBROM] = STATS & 0xFF
        bus.wram[OBROM + 1] = STATS >> 8
        bus.wram[STATS + 1] = ailments          # ch_ailments is ch_stats + 1
        bus.sram[0x686E - 0x6000] = effect      # btlmag_effect
        bus.sram[0x6874 - 0x6000] = effectivity # btlmag_effectivity
        call(cpu, "opt_playervalid")
        return "valid" if cpu.p & 0x02 else "refused"     # Z

    #  The whole point: a dead target, for the two Life spells, with the flag on.
    check("dead, LIFE", valid(AIL_DEAD, CUREAILMENT, LIFE), "valid")
    check("dead, LIF2", valid(AIL_DEAD, CUREAILMENT, LIF2), "valid")

    #  With the flag off it refuses, as the cartridge does.
    check("dead, LIFE, flag off",
          valid(AIL_DEAD, CUREAILMENT, LIFE, castlife=False), "refused")

    #  And the relaxation is narrower than FFR's, which passes any CureAilment
    #  spell: PURE, LAMP and AMUT still cannot be pointed at a corpse.
    for name, mask in (("PURE", 0x04), ("LAMP", 0x08), ("AMUT", 0x40)):
        check("dead, %s, flag on" % name,
              valid(AIL_DEAD, CUREAILMENT, mask), "refused")

    #  Everything else answers exactly as the vanilla test did.
    for name, ail, want in (("healthy", 0x00, "valid"),
                            ("poisoned", AIL_POISON, "valid"),
                            ("stoned", AIL_STONE, "refused"),
                            ("dead and stoned", AIL_DEAD | AIL_STONE, "refused")):
        for on in (False, True):
            check("%s, CURE, flag %s" % (name, "on" if on else "off"),
                  valid(ail, 0x07, 0x10, castlife=on), want)

    #  A Life tag on a spell that is not CureAilment is not a Life spell.
    check("dead, effect 7 with the LIFE tag",
          valid(AIL_DEAD, 0x07, LIFE), "refused")

    #  The wiring.
    tgt = SYM["opt_playervalid"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    check("TargetOnePlayer calls opt_playervalid", jsl in ROMDATA, True)


# --- Cast Life in Battle, the half that makes it stick -----------------------
#  The record alone never worked: CureAilment clears AIL_DEAD and then
#  PerformSpellEffect puts it back because HP is still zero, so the bit nets to
#  no change and the spell reads as ineffective.  FFR's LIFE works only because
#  ExtConsumables replaces CureAilment wholesale.  opt_castlife replaces the
#  JSR BtlMag_MarkSpellConnected at that routine's tail and supplies the HP.
def test_castlife():
    F_CASTLIFE = (3, 0x01)                      # bit 24
    LIFE, LIF2 = 0x01, 0x81
    CASTLIFE_HP = 0x10
    SPELLCONNECTED = 0x685C
    HP, HPMAX = 0x687A, 0x6880                  # math buffer slots

    def cast(effectivity, maxhp, castlife=True, hp=0):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i,
                   F_CASTLIFE[1] if (castlife and i == F_CASTLIFE[0]) else 0)
        bus.sram[0x6874 - 0x6000] = effectivity          # btlmag_effectivity
        bus.sram[HPMAX - 0x6000] = maxhp & 0xFF
        bus.sram[HPMAX + 1 - 0x6000] = maxhp >> 8
        bus.sram[HP - 0x6000] = hp & 0xFF
        bus.sram[HP + 1 - 0x6000] = hp >> 8
        bus.sram[SPELLCONNECTED - 0x6000] = 0
        call(cpu, "opt_castlife")
        got = bus.sram[HP - 0x6000] | (bus.sram[HP + 1 - 0x6000] << 8)
        return got, bus.sram[SPELLCONNECTED - 0x6000]

    #  Whatever else happens, the store it replaced still happens.
    for name, eff, on in (("LIFE", LIFE, True), ("LIF2", LIF2, True),
                          ("LIFE, flag off", LIFE, False),
                          ("PURE", 0x04, True), ("LAMP", 0x08, True),
                          ("AMUT", 0x40, True)):
        check("%s: still marks the spell connected" % name,
              cast(eff, 400, castlife=on)[1], 1)

    #  LIFE stands them up with a flat 16; LIF2 refills.
    check("LIFE: 16 HP", cast(LIFE, 400)[0], CASTLIFE_HP)
    check("LIF2: max HP", cast(LIF2, 400)[0], 400)
    #  ...and LIFE never exceeds what they have, however small that is.
    check("LIFE with max 9: all of it", cast(LIFE, 9)[0], 9)
    check("LIFE with max 16: exactly it", cast(LIFE, 16)[0], 16)
    check("LIFE with max 17: the flat value", cast(LIFE, 17)[0], CASTLIFE_HP)
    check("LIF2 with max 9: all of it", cast(LIF2, 9)[0], 9)

    #  Flag off, no HP at all -- which is vanilla, and is the bug the flag fixes.
    check("LIFE with the flag off: no HP", cast(LIFE, 400, castlife=False)[0], 0)
    check("LIF2 with the flag off: no HP", cast(LIF2, 400, castlife=False)[0], 0)

    #  And the three real CureAilment spells are untouched, flag either way.
    for name, eff in (("PURE", 0x04), ("LAMP", 0x08), ("AMUT", 0x40)):
        for on in (False, True):
            check("%s untouched, flag %s" % (name, "on" if on else "off"),
                  cast(eff, 400, castlife=on, hp=123)[0], 123)

    #  The wiring, which the routine's own behaviour cannot show: CureAilment
    #  calls it, and the JSR it replaced is gone from that tail.
    tgt = SYM["opt_castlife"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    check("CureAilment calls opt_castlife", jsl in ROMDATA, True)


# --- SOFT in battle ----------------------------------------------------------
#  FFR's EnableSoftInBattle: the SOFT spell and the SOFT potion work in battle.
#  The spell is Cast Life's pattern -- FFR's record, cure ailment on AIL_STONE,
#  through the same override, message and targeting hooks.  The potion is a
#  third row in the DRINK box, which vanilla builds for exactly two, so each
#  place that knew that asks the options bank instead.  Expectations come from
#  FFR (SpellBalance.EnableSoftInBattle, ExtConsumables' DRINK tables) and the
#  disassembly, not from lut_SoftRecord or the hooks.
def test_softbattle():
    F_SOFT = (2, 0x20)                          # bit 21
    SPELL_SOFT, SPELL_LIFE, SPELL_PURE = 40, 33, 24
    INEFFECTIVENOW_MSG, CURED_1, INEFFNOW_ALT = 0x4A, 0x0D, 0x13
    HEAL_ID, PURE_ID, SOFT_ID = 0x19, 0x1A, 0x1B
    POT_HEAL, POT_PURE, BATTLE_BANK = 0x6BAF, 0x6BB0, 0x6BB1
    BTLSOFT = K["OPTBTLSOFT"]
    ITEM_HEAL_AT = 0x6039                       # item_heal: unsram + $20 + $19
    CURS_Y, CURS_POS = 0x6AAB, 0x6AAC
    SEL, ID = 0x6B7D, 0x6856
    CONSUMEID = 0x68A7
    ATTACKID = 0x6C8C
    HDR, MSGY, SRCPTR, BUF = 0x6A9E, 0x6AA0, 0x6AA1, 0x6AFA

    def m(soft):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, F_SOFT[1] if (soft and i == F_SOFT[0]) else 0)
        return bus, cpu
    def sr(bus, a):
        return bus.sram[a - 0x6000]
    def sw(bus, a, v):
        bus.sram[a - 0x6000] = v

    # -- the spell --------------------------------------------------------
    #  FFR's record: routine $08 cure ailment, effect $02, target $10, hit 0,
    #  element 0, graphic 184, palette 40.  Our field order is hit,
    #  effectivity, element, target, effect, graphic, palette, unused.
    want = [0, 0x02, 0, 0x10, 0x08, 184, 40, 0]
    def field(spell, f, soft):
        bus, cpu = m(soft)
        cpu.x, cpu.y = spell, f
        call(cpu, "opt_spellfixed")
        return (cpu.a & 0xFF) if cpu.p & 0x01 else None
    check("SOFT's record with the flag on", [field(SPELL_SOFT, f, True) for f in range(8)], want)
    check("SOFT's record with the flag off: the cartridge's",
          [field(SPELL_SOFT, f, False) for f in range(8)], [None] * 8)
    check("LIFE is not SOFT's", [field(SPELL_LIFE, f, True) for f in range(8)], [None] * 8)

    def msg(spell, soft):
        bus, cpu = m(soft)
        cpu.x = spell
        call(cpu, "opt_magicmsg")
        return cpu.a & 0xFF, bool(cpu.p & 0x02)
    check("SOFT's cartridge message is INEFFECTIVENOW", msg(SPELL_SOFT, False)[0], INEFFECTIVENOW_MSG)
    check("SOFT silent with the flag on", msg(SPELL_SOFT, True), (0, True))
    check("LIFE keeps its own with only SOFT on", msg(SPELL_LIFE, True)[0], INEFFECTIVENOW_MSG)

    def cured(counter, soft):
        bus, cpu = m(soft)
        cpu.x = counter
        call(cpu, "opt_curedmsg")
        return cpu.a & 0xFF, bool(cpu.p & 0x02)
    check("STONE cured, flag off: INEFFECTIVENOW", cured(7, False), (INEFFNOW_ALT, False))
    check("STONE cured, flag on: CURED", cured(7, True), (CURED_1, False))
    for counter in (1, 2, 3, 4, 5, 6, 8):
        check("counter %d untouched by SOFT" % counter, cured(counter, True), cured(counter, False))

    def valid(ailments, effectivity, soft, effect=0x08):
        bus, cpu = m(soft)
        bus.wram[0x92], bus.wram[0x93] = 0x00, 0x04
        bus.wram[0x0401] = ailments
        sw(bus, 0x686E, effect)
        sw(bus, 0x6874, effectivity)
        call(cpu, "opt_playervalid")
        return "valid" if cpu.p & 0x02 else "refused"
    check("stoned, SOFT, flag on", valid(0x02, 0x02, True), "valid")
    check("stoned, SOFT, flag off", valid(0x02, 0x02, False), "refused")
    check("healthy, SOFT, flag on", valid(0x00, 0x02, True), "valid")
    check("dead, SOFT, flag on", valid(0x01, 0x02, True), "refused")
    check("dead and stoned, SOFT, flag on", valid(0x03, 0x02, True), "refused")
    check("stoned, PURE, flag on", valid(0x02, 0x04, True), "refused")
    check("stoned, effect 7 with SOFT's mask", valid(0x02, 0x02, True, effect=0x07), "refused")

    # -- the potion --------------------------------------------------------
    def drink(soft, heal=0, pure=0, softn=0):
        bus, cpu = m(soft)
        bus.wram[0x10:0x13] = bytes((0xA1, 0xB2, 0xC3))   # the game's tmp, borrowed
        sw(bus, POT_HEAL, heal); sw(bus, POT_PURE, pure); sw(bus, BTLSOFT, softn)
        sw(bus, BATTLE_BANK, 0x5A)                  # the decoys after the two:
        sw(bus, BATTLE_BANK + 1, 0x77)              #   what row 3 would read past
        return bus, cpu

    bus, cpu = m(True)
    for i, v in enumerate((11, 22, 33)):
        sw(bus, ITEM_HEAL_AT + i, v)
    call(cpu, "opt_drinkinit")
    check("init: the battle's three counts",
          (sr(bus, POT_HEAL), sr(bus, POT_PURE), sr(bus, BTLSOFT)), (11, 22, 33))

    def anyp(soft, h, p, s):
        bus, cpu = drink(soft, h, p, s)
        call(cpu, "opt_drinkany")
        return not (cpu.p & 0x02)
    check("any: nothing at all", anyp(True, 0, 0, 0), False)
    check("any: only SOFT, flag on", anyp(True, 0, 0, 1), True)
    check("any: only SOFT, flag off", anyp(False, 0, 0, 1), False)
    check("any: HEAL, flag off", anyp(False, 1, 0, 0), True)
    check("any: PURE, flag on", anyp(True, 0, 1, 0), True)

    def pick(soft, row, counts=(5, 5, 5)):
        bus, cpu = drink(soft, *counts)
        sw(bus, CURS_Y, row)
        call(cpu, "opt_drinkpick")
        return (sr(bus, SEL), sr(bus, ID), "nothing" if cpu.p & 0x01 else "ok")
    for row in range(4):
        check("pick, flag off, row %d: vanilla's mirror" % row,
              pick(False, row), (row & 1, row & 1, "ok"))
    check("pick, flag on, HEAL", pick(True, 0), (0, 0, "ok"))
    check("pick, flag on, PURE", pick(True, 1), (1, 1, "ok"))
    check("pick, flag on, SOFT", pick(True, 2), (2, 2, "ok"))
    check("pick, flag on, the empty row", pick(True, 3)[2], "nothing")
    check("pick, SOFT with none left", pick(True, 2, (5, 5, 0))[2], "nothing")
    check("pick, HEAL with none left", pick(True, 0, (0, 5, 5))[2], "nothing")
    check("pick, PURE with none left, flag off", pick(False, 1, (5, 0, 5))[2], "nothing")

    def dec(soft, which):
        bus, cpu = drink(soft, 5, 6, 7)
        sw(bus, ID, which)
        call(cpu, "opt_drinkdec")
        return (sr(bus, POT_HEAL), sr(bus, POT_PURE), sr(bus, BTLSOFT), sr(bus, BATTLE_BANK))
    check("dec HEAL", dec(True, 0), (4, 6, 7, 0x5A))
    check("dec PURE", dec(True, 1), (5, 5, 7, 0x5A))
    check("dec SOFT: its own count, not battle_bank", dec(True, 2), (5, 6, 6, 0x5A))

    def undo(which):
        bus, cpu = drink(True, 5, 6, 7)
        sw(bus, CONSUMEID + 2, which)               # character 2's choice
        cpu.y = 2
        call(cpu, "opt_drinkundo")
        return (sr(bus, POT_HEAL), sr(bus, POT_PURE), sr(bus, BTLSOFT), sr(bus, BATTLE_BANK), cpu.y)
    check("undo HEAL", undo(0), (6, 6, 7, 0x5A, 2))
    check("undo PURE", undo(1), (5, 7, 7, 0x5A, 2))
    check("undo SOFT: its own count, not battle_bank", undo(2), (5, 6, 8, 0x5A, 2))

    def effect(row):
        bus, cpu = m(True)
        sw(bus, SEL, row)
        call(cpu, "opt_drinkeffect")
        return cpu.a & 0xFF
    check("effects: $40, $41 and the SOFT spell", [effect(r) for r in range(3)], [0x40, 0x41, SPELL_SOFT])

    def name(attack):
        bus, cpu = m(True)
        sw(bus, ATTACKID, attack)
        call(cpu, "opt_drinkname")
        return cpu.a & 0xFF, bool(cpu.p & 0x02)
    check("names: HEAL, PURE, SOFT, all nonzero",
          [name(a) for a in (0x40, 0x41, SPELL_SOFT)],
          [(HEAL_ID, False), (PURE_ID, False), (SOFT_ID, False)])

    def cursor(soft):
        bus, cpu = m(soft)
        call(cpu, "opt_drinkcursor")
        return [sr(bus, CURS_POS + i) for i in range(16)]
    van = list(ROMDATA[(BANK_0C & 0x1F) * 0x10000 + SYM["lut_DrinkCursorPos"]:][:16])
    check("cursor, flag off: the cartridge's table", cursor(False), van)
    check("...which mirrors two rows", van[:4] * 4, van)
    check("cursor, flag on: four rows, both columns",
          cursor(True), [0x18, 0xA6, 0x18, 0xB6, 0x18, 0xC6, 0x18, 0xD6] * 2)

    #  The box, then rows until C: what DrawDrinkBox's loop now asks for.
    def box(soft, counts):
        bus, cpu = drink(soft, *counts)
        for i in range(0x80):
            sw(bus, BUF + i, 0xFF)                  # as ClearUnformattedCombatBoxBuffer
        call(cpu, "opt_drinkbox")
        spec = [sr(bus, HDR + i) for i in range(5)]
        sw(bus, HDR, spec[0] + 1); sw(bus, MSGY, spec[2] + 1)   # the INCs after it
        rows = []
        for _ in range(6):
            c = CPU(bus); c.dbr = 0xA7
            call(c, "opt_drinkrow")
            if c.p & 0x01:
                break
            ptr = sr(bus, SRCPTR) | sr(bus, SRCPTR + 1) << 8
            raw = []
            while len(raw) < 16 and not (len(raw) >= 2 and raw[-2:] == [0, 0]
                                         and (len(raw) < 3 or raw[-3] != 0x11)):
                raw.append(sr(bus, ptr + len(raw)))
            rows.append((sr(bus, MSGY), ptr - BUF, tuple(raw)))
        return spec, rows, tuple(bus.wram[0x10:0x13])
    vspec = list(ROMDATA[(0xA7 & 0x1F) * 0x10000 + SYM["lut_CombatDrinkBox"]:][:5])
    check("the cartridge's box is six high", vspec[4], 6)
    #  The cartridge's names: HEAL and PURE are four letters and the potion
    #  icon; SOFT has two spaces after the icon, the width of the item lists.
    def itemname(item):
        b = (1 + 0x0A) * 0x10000
        p = b + 0xB700 + item * 2
        at = b + (ROMDATA[p] | ROMDATA[p + 1] << 8) - 0x8000
        return ROMDATA[at:ROMDATA.find(b"\x00", at)]
    softname = itemname(SOFT_ID).rstrip(b"\xFF")
    check("SOFT's stored name is padded past HEAL's",
          (len(itemname(SOFT_ID)) > len(itemname(HEAL_ID)), len(softname)), (True, len(itemname(HEAL_ID))))
    spec, rows, tmpbytes = box(False, (3, 4, 9))
    check("flag off: the cartridge's spec", spec, vspec)
    check("flag off: two rows, as vanilla wrote them", rows,
          [(vspec[2] + 1, 0x00, (0xFF, 0x0E, HEAL_ID, 0xFF, 0x11, 3, 0, 0)),
           (vspec[2] + 3, 0x20, (0xFF, 0x0E, PURE_ID, 0xFF, 0x11, 4, 0, 0))])
    spec, rows, tmpbytes = box(True, (3, 0, 9))
    check("flag on: ten high", spec, vspec[:4] + [10])
    check("flag on: three rows, PURE's blank, SOFT's name spelled out", rows,
          [(vspec[2] + 1, 0x00, (0xFF, 0x0E, HEAL_ID, 0xFF, 0x11, 3, 0, 0)),
           (vspec[2] + 3, 0x20, (0xFF,) * 6 + (0, 0)),
           (vspec[2] + 5, 0x40, (0xFF,) + tuple(softname) + (0xFF, 0x11, 9, 0, 0))])
    #  The property the user saw broken: every count in the same column.  An
    #  escape prints the cartridge's name in full; a spelled-out name is what
    #  it is.  The column is everything printed before the number code.
    def column(row):
        out, i = 0, 0
        while row[i] != 0x11:
            if row[i] == 0x0E:
                out += len(itemname(row[i + 1])); i += 2
            else:
                out += 1; i += 1
        return out
    spec, rows, tmpbytes = box(True, (3, 4, 9))
    check("flag on: HEAL's, PURE's and SOFT's counts in one column",
          [column(r[2]) for r in rows], [column(rows[0][2])] * 3)
    check("...and inside the box", column(rows[0][2]) + 2 <= vspec[3] - 2, True)
    check("SOFT's row gives tmp back", tmpbytes, (0xA1, 0xB2, 0xC3))

    #  ...and the fixed bank's own loop, run for real: DrawDrinkBox stopped
    #  where it hands the queue to DrawBlockBuffer, which talks to the PPU.
    #  Each queued block is five bytes: the box's spec, then per row the
    #  text header, x, y and the row's pointer.
    QUEUE = 0x0500
    def queued(soft, counts):
        bus, cpu = drink(soft, *counts)
        bus.wram[0x8C], bus.wram[0x8D] = QUEUE & 0xFF, QUEUE >> 8   # blockptrstart
        bus.wram[0x8E], bus.wram[0x8F] = QUEUE & 0xFF, QUEUE >> 8   # blockptrend
        cpu.run(0xA7, SYM["DrawDrinkBox"], stop=SYM["DrawBlockBuffer"])
        if cpu.pc != SYM["DrawBlockBuffer"]:
            return None
        n = ((bus.wram[0x8E] | bus.wram[0x8F] << 8) - QUEUE) // 5
        return [tuple(bus.wram[QUEUE + 5 * i + k] for k in range(5)) for i in range(n)]
    def textblock(y, row):
        p = BUF + 0x20 * row
        return (1, vspec[1] + 1, y, p & 0xFF, p >> 8)
    check("DrawDrinkBox, flag off: the box and two rows",
          queued(False, (3, 4, 9)),
          [tuple(vspec), textblock(vspec[2] + 1, 0), textblock(vspec[2] + 3, 1)])
    check("DrawDrinkBox, flag on: the tall box and three rows",
          queued(True, (3, 4, 9)),
          [tuple(vspec[:4] + [10]), textblock(vspec[2] + 1, 0),
           textblock(vspec[2] + 3, 1), textblock(vspec[2] + 5, 2)])

    #  The wiring: every hook is called once, from the bank it belongs in --
    #  bank $0C's half of its chunk, or the fixed bank, which every chunk
    #  carries a copy of at $C000.
    for name_, bank, base in (("opt_drinkinit", BANK_0C, 0x8000), ("opt_drinkany", BANK_0C, 0x8000),
                              ("opt_drinkpick", BANK_0C, 0x8000), ("opt_drinkdec", BANK_0C, 0x8000),
                              ("opt_drinkundo", BANK_0C, 0x8000), ("opt_drinkeffect", BANK_0C, 0x8000),
                              ("opt_drinkname", BANK_0C, 0x8000), ("opt_drinkcursor", BANK_0C, 0x8000),
                              ("opt_drinkbox", 0xA7, 0xC000), ("opt_drinkrow", 0xA7, 0xC000)):
        tgt = SYM[name_]
        jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
        img = ROMDATA[(bank & 0x1F) * 0x10000 + base:][:0x4000]
        check("%s is called once, from its bank" % name_, img.count(jsl), 1)


# --- Run chance fix -------------------------------------------------------------
#  FFR's ChanceToRun "Corrected".  Running is luck against rand[0, level + 15],
#  and the original reads the level through btl_ib_charstat_ptr, where offset
#  $26 is not the level -- Disch: "the ailment byte for 2 players after this
#  one".  FFR's fix is one byte, the out-of-battle pointer instead.
def test_runfix():
    IB, OB = 0x80, 0x82                         # btl_ib_ / btl_ob_charstat_ptr
    def level(on, lv, stray):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 4, 0x40 if on else 0)
        bus.wram[OB], bus.wram[OB + 1] = 0x00, 0x05     # the saved stats, at $0500
        bus.wram[IB], bus.wram[IB + 1] = 0x00, 0x06     # the battle's, at $0600
        bus.wram[0x0526] = lv                   # ch_level, 0-based
        bus.wram[0x0626] = stray                # what the original reads instead
        call(cpu, "opt_runlevel")
        return cpu.a & 0xFF, cpu.y
    check("flag off: the original's stray byte + 15", level(False, 29, 0x40), (0x40 + 15, 0x26))
    check("flag on: the level + 15", level(True, 29, 0x40), (29 + 15, 0x26))
    check("flag on, level 1: 15", level(True, 0, 0x40)[0], 15)
    check("flag on, level 50: 64", level(True, 49, 0x40)[0], 64)

    tgt = SYM["opt_runlevel"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    img = ROMDATA[(BANK_0C & 0x1F) * 0x10000 + 0x8000:][:0x4000]
    check("Battle_PlayerTryRun calls opt_runlevel, once", img.count(jsl), 1)


# --- Turn order fix -------------------------------------------------------------
#  FFR's ImproveTurnOrderRandomization.  DoBattleRound starts the turn order
#  enemies first, party last, and shuffles it by swapping two random picks
#  seventeen times; the fix is FFR's Fisher-Yates walk.  The models here are
#  written from the disassembly and FFR's patch, with RandAX as it is:
#  lo + (BattleRNG * (hi + 1 - lo)) >> 8.
def test_turnfix():
    RNGTAB = open(os.path.join(ROOT, "game", "bin", "0F_FCF1_rngtable.bin"), "rb").read()
    CURTURN, ORDER = 0x688E, 0x6848
    START = list(range(9)) + [0x80, 0x81, 0x82, 0x83]

    def model(fix, state):
        order, s = list(START), state
        def randax(lo, hi):
            nonlocal s
            r = RNGTAB[s & 0xFF]; s += 1
            return lo + (r * (hi + 1 - lo) >> 8)
        if fix:
            for i in range(12, 0, -1):
                j = randax(0, i)
                order[i], order[j] = order[j], order[i]
        else:
            for _ in range(17):
                x = randax(0, 12); y = randax(0, 12)
                order[x], order[y] = order[y], order[x]
        return order, (s - state) & 0xFF

    #  The shuffle's end: the DEC btl_curturn / BNE after the swap, found from
    #  the hook rather than by address.
    img = ROMDATA[(BANK_0C & 0x1F) * 0x10000:]
    tgt = SYM["opt_turncount"]
    hook = img.find(bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK]), 0x8000)
    dec = img.find(bytes([0xCE, CURTURN & 0xFF, CURTURN >> 8, 0xD0]), hook)
    STOP = dec + 5

    def real(fix, state):
        bus, cpu = machine()
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        setblk(bus, OPT_FLAGS + 4, 0x80 if fix else 0)
        bus.sram[BTL_RNGSTATE - 0x6000] = state
        c = CPU(bus); c.dbr = BANK_0C
        c.run(BANK_0C, SYM["DoBattleRound"], stop=STOP)
        if c.pc != STOP:
            return None
        return ([bus.sram[ORDER - 0x6000 + i] for i in range(13)],
                (bus.sram[BTL_RNGSTATE - 0x6000] - state) & 0xFF)

    check("the shuffle's end was found after the hook", 0 < hook < dec < hook + 40, True)
    for fix in (False, True):
        wrong = [s for s in range(0, 256, 5) if real(fix, s) != model(fix, s)]
        check("%s: the cartridge's shuffle is the model's, every state" %
              ("fix" if fix else "original"), wrong, [])
    check("original: 34 rolls a round", real(False, 0)[1], 34)
    check("fix: 12 rolls a round", real(True, 0)[1], 12)

    #  Fairness, over every state: where the party ends up.  Thirteen slots,
    #  four of them the party's, so a fair shuffle puts a party member last
    #  4 times in 13.
    def lastparty(fix):
        return sum(1 for s in range(256) if model(fix, s)[0][12] & 0x80) / 256
    check("fix: a party member last about 4 times in 13",
          abs(lastparty(True) - 4 / 13) < 0.08, True)
    #  ...where the original's swaps leave one last in over half the rounds,
    #  which is what the row's description says (57% when measured).
    check("original: a party member last in over half the rounds",
          lastparty(False) > 0.5, True)

    #  The three helpers alone.
    def helper(name, fix, curturn=7):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 4, 0x80 if fix else 0)
        bus.sram[CURTURN - 0x6000] = curturn
        cpu.y = 0x5A
        call(cpu, name)
        return cpu.a & 0xFF, cpu.x, cpu.y, bool(cpu.p & 1), bus.sram[CURTURN - 0x6000]
    check("count, original", helper("opt_turncount", False)[4], 17)
    check("count, fix", helper("opt_turncount", True)[4], 12)
    check("first pick, original: 0 to 12, Y kept", helper("opt_turnhi", False)[:3], (0, 12, 0x5A))
    check("first pick, fix: 0 to i, Y kept", helper("opt_turnhi", True)[:3], (0, 7, 0x5A))
    check("second, original: another pick", helper("opt_turnsecond", False)[:4], (0, 12, 0x5A, False))
    check("second, fix: i itself", helper("opt_turnsecond", True)[1:4], (7, 0x5A, True))


# --- TRANCE status element --------------------------------------------------------
#  FFR's TranceHasStatusElement: the enemy skill TRANCE, record 81, attack
#  $51, gets the status element ($01), so a Ribbon resists it.  FFR asserts
#  the record's other fields before it edits: hit 0, stun, no element, all
#  targets, inflict ailment.
def test_trance():
    MAGDATA = open('game/bin/0C_81E0_magicdata.bin', 'rb').read()
    rec = list(MAGDATA[81 * 8:81 * 8 + 8])
    check("TRANCE is what FFR asserts it is",
          (rec[0], rec[1], rec[2], rec[3], rec[4]), (0, 0x10, 0, 0x01, 0x03))
    ATTACKER = 0x6C89
    EFFECT, ELEMENT, HITRATE, EFFY = 0x686E, 0x6878, 0x6870, 0x6874   # btlmag_*

    def prepare(on, attack):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 5, 0x01 if on else 0)
        bus.sram[0x6C8C - 0x6000] = attack       # btl_attackid
        bus.sram[ATTACKER - 0x6000] = 0x02       # an enemy
        c = CPU(bus); c.dbr = BANK_0C
        c.run(BANK_0C, SYM["Battle_PrepareMagic"])
        return tuple(bus.sram[a - 0x6000] for a in (EFFECT, ELEMENT, HITRATE, EFFY))

    check("TRANCE, flag off: no element", prepare(False, 0x51), (3, 0x00, 0, 0x10))
    check("TRANCE, flag on: the status element", prepare(True, 0x51), (3, 0x01, 0, 0x10))
    for attack in (0x50, 0x52, 0x42):
        check("attack $%02X untouched by the flag" % attack,
              prepare(True, attack), prepare(False, attack))
    #  ...and a spell still goes the spell flags' way: FIRE, with none on.
    check("FIRE untouched by the flag", prepare(True, 4), prepare(False, 4))


# --- Critical hit count ---------------------------------------------------------
#  FFR's EnableCritNumberDisplay, unconditional here (user): several criticals
#  in one attack read "N Critical hits!" where the original says "Critical
#  hit!!".  The hook hands
#  PrepareAndDrawSimpleCombatBox its two codes; for a count it writes FFR's
#  words after the three bytes that routine writes, and the routine draws the
#  lot.  Run through the real routine, stopped where it calls the drawing.
def test_critcount():
    CRITS = 0x686B                              # battle_critsconnected
    BOX4 = 0x6AFA + 0x40                        # combat box 4's buffer
    CRITICALHIT = 0x2C

    def box(n):
        bus, cpu = machine()
        bus.sram[CRITS - 0x6000] = n
        for i in range(0x20):
            bus.sram[BOX4 - 0x6000 + i] = 0xEE  # what was there before
        call(cpu, "opt_critbox")
        if cpu.p & 0x02:
            return None
        a, x, y = cpu.a & 0xFF, cpu.x, cpu.y
        c = CPU(bus); c.dbr = BANK_0C
        c.a, c.x, c.y = a, x, y
        c.run(BANK_0C, SYM["PrepareAndDrawSimpleCombatBox"], stop=SYM["DrawCombatBox_L"])
        ptr = c.x | c.y << 8
        raw = bytes(bus.sram[ptr - 0x6000 + i] for i in range(0x20))
        #  what the box prints: $0F is a battle message, $11 a two-byte number
        out, i = "", 0
        while raw[i] != 0:
            if raw[i] == 0x0F:
                out += "<msg %02X>" % raw[i + 1]; i += 2
            elif raw[i] == 0x11:
                out += str(raw[i + 1] | raw[i + 2] << 8); i += 3
            else:
                out += _decode(raw[i]) or "?"; i += 1
        return c.a & 0xFF, ptr, out, i + 1

    check("no criticals: no box", box(0), None)
    check("one critical: the original's message",
          box(1), (4, BOX4, "<msg %02X>" % CRITICALHIT, 3))
    check("two: FFR's count", box(2), (4, BOX4, "2 Critical hits!", 19))
    check("twelve", box(12)[2], "12 Critical hits!")
    #  Whatever the flags say: there are none for it.
    bus, cpu = machine()
    for i in range(6):
        setblk(bus, OPT_FLAGS + i, 0)
    bus.sram[CRITS - 0x6000] = 3
    call(cpu, "opt_critbox")
    check("all flags off: still counted", (cpu.y, cpu.x), (0x11, 3))
    #  ...nineteen bytes, three past box 4's sixteen, as FFR's own are.

    tgt = SYM["opt_critbox"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    img = ROMDATA[(BANK_0C & 0x1F) * 0x10000 + 0x8000:][:0x4000]
    check("the attack report calls opt_critbox, once", img.count(jsl), 1)


# --- Standard map edits: the Lefein shops -------------------------------------
#  FFR's Lefeinish Hospitality and Add Lefein SuperStore, written over Lefein
#  as it loads.  The expected tiles are FFR's own, from SMUpdates.cs
#  (EnableLefeinShops, EnableLefeinSuperStore), not lut_MapEdits.
MAP_LEFEIN = 7
MAPDATA = 0x7000
LEFEIN_SHOPS = {(0x11, 5): 0x25, (0x11, 6): 0x71, (0x15, 5): 0x1A, (0x15, 6): 0x65}
_STORE = ["171717171717171717171700171717171717171717171700",
          "181818181823181818181801181818181824181818181801",
          "1D4F5051541D525357581D021D595A5B5E1D5C5D61621D02"]
LEFEIN_STORE = {(0x28 + j, 1 + i): int(row[2 * j:2 * j + 2], 16)
                for i, row in enumerate(_STORE) for j in range(24)}
LEFEIN_STORE[(0x34, 0)] = 0x00                  # the tree, to TownGrass


def test_mapedits():
    def flagbyte(shops, store):
        return (0x02 if shops else 0) | (0x04 if store else 0)

    #  The routine alone, over a patterned map: exactly FFR's tiles change.
    def edited(shops, store, mapid=MAP_LEFEIN):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 5, flagbyte(shops, store))
        pattern = bytes((i * 7 + 3) & 0xFF for i in range(0x1000))
        bus.sram[MAPDATA - 0x6000:MAPDATA - 0x6000 + 0x1000] = pattern
        bus.wram[0x48] = mapid                  # cur_map
        call(cpu, "opt_mapedits")
        after = bus.sram[MAPDATA - 0x6000:MAPDATA - 0x6000 + 0x1000]
        return {(i % 64, i // 64): after[i] for i in range(0x1000) if after[i] != pattern[i]}
    def want(shops, store):
        pattern = bytes((i * 7 + 3) & 0xFF for i in range(0x1000))
        out = {}
        for on, edits in ((shops, LEFEIN_SHOPS), (store, LEFEIN_STORE)):
            if on:
                out.update({k: v for k, v in edits.items() if pattern[k[1] * 64 + k[0]] != v})
        return out
    for shops in (False, True):
        for store in (False, True):
            check("Lefein, inn %s, store %s: FFR's tiles and no others" % (shops, store),
                  edited(shops, store), want(shops, store))
    check("another map, both on: untouched", edited(True, True, mapid=4), {})

    #  The real load, through LoadStandardMapAndObjects: what the flags change
    #  in the map as decompressed is FFR's edits, nothing more.
    def loaded(shops, store):
        bus, cpu = machine()
        setblk(bus, OPT_FLAGS + 5, flagbyte(shops, store))
        bus.wram[0x48] = MAP_LEFEIN
        c = CPU(bus); c.dbr = 0xA7
        c.run(0xA7, SYM["LoadStandardMapAndObjects"])
        return bytes(bus.sram[MAPDATA - 0x6000:MAPDATA - 0x6000 + 0x1000])
    plain, both = loaded(False, False), loaded(True, True)
    diff = {(i % 64, i // 64): both[i] for i in range(0x1000) if both[i] != plain[i]}
    expect = {k: v for k, v in {**LEFEIN_SHOPS, **LEFEIN_STORE}.items()
              if plain[k[1] * 64 + k[0]] != v}
    check("loading Lefein with both on: FFR's edits over the real map", diff, expect)
    check("...which do change it", len(expect) > 30, True)

    #  The tiles mean what FFR says, in this ROM: Lefein's tileset is the town
    #  one, the doors are shop doors to the shops named, the signs are solid.
    ts = ROMDATA[(0xA1 & 0x1F) * 0x10000 + 0xACC0 + MAP_LEFEIN]
    def prop(t):
        o = (0xA1 & 0x1F) * 0x10000 + 0x8800 + ts * 256 + (t & 0x7F) * 2
        return ROMDATA[o], ROMDATA[o + 1]
    check("Lefein uses the town tileset", ts, 0)
    check("the Inn and Clinic doors: Crescent Lake's, shops 55 and 43",
          (prop(0x71)[1], prop(0x65)[1]), (55, 43))
    doors = [int(_STORE[2][2 * j:2 * j + 2], 16) for j in range(24)]
    check("the SuperStore's doors: every magic shop but Gaia's 27, 28, 37, 38",
          sorted(prop(d)[1] for d in doors if prop(d)[1]),
          [21, 22, 23, 24, 25, 26, 29, 30, 31, 32, 33, 34, 35, 36, 39, 40])
    check("the signs are solid, not doors",
          [prop(s) for s in (0x25, 0x1A, 0x23, 0x24)], [(1, 0)] * 4)

    #  No one in Lefein stands where a tile changes.
    objs = ROMDATA[(0xA1 & 0x1F) * 0x10000 + 0xB400 + MAP_LEFEIN * 0x30:][:0x30]
    standing = {(objs[i + 1] & 0x3F, objs[i + 2] & 0x3F) for i in range(0, 0x30, 3) if objs[i]}
    check("no NPC stands on an edited tile",
          sorted(standing & (set(LEFEIN_SHOPS) | set(LEFEIN_STORE))), [])

    #  The wiring: between the decompression and the objects, once.
    tgt = SYM["opt_mapedits"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    img = ROMDATA[(0xA7 & 0x1F) * 0x10000 + 0xC000:][:0x4000]
    at = img.find(jsl)
    check("LoadStandardMapAndObjects calls opt_mapedits once, between two JSRs",
          (img.count(jsl), img[at - 3], img[at + 4]), (1, 0x20, 0x20))


# --- White Mage HARM ---------------------------------------------------------
#  FFR's WhiteMageHarmEveryone: HARM cast or used by a White Mage or White
#  Wizard damages anything.  FFR's tooltip: on the living it "will not crit
#  (will not deal double damage except on a 3/256), averaging 30/60/90/120
#  damage" -- the effectivity and up to twice it, never the undead's double.
def test_wmharm():
    F_WMHARM = (4, 0x20)                        # bit 37
    CATEGORY = 0x6886                           # btlmag_defender_category
    UNDEAD = 0x08
    ATTACKER = 0x6C89
    HITCHANCE = 0x6856
    CLS = {"FT": 0, "TH": 1, "BB": 2, "RM": 3, "WM": 4, "BM": 5,
           "KN": 6, "NJ": 7, "MA": 8, "RW": 9, "WW": 10, "BW": 11}

    def setup(on, cls, slot=2, undead=False, attacker=None):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, F_WMHARM[1] if (on and i == F_WMHARM[0]) else 0)
        for s in range(4):                      # decoys: White Mages everywhere else
            bus.sram[0x6100 + s * 0x40 - 0x6000] = CLS["WM"] if s != slot else cls
        bus.sram[ATTACKER - 0x6000] = (0x80 | slot) if attacker is None else attacker
        bus.sram[CATEGORY - 0x6000] = UNDEAD if undead else 0x01
        return bus, cpu

    def hook(on, cls, **kw):
        bus, cpu = setup(on, cls, **kw)
        bus.sram[HITCHANCE - 0x6000], bus.sram[HITCHANCE + 1 - 0x6000] = 0x99, 0x01
        call(cpu, "opt_harmundead")
        hc = bus.sram[HITCHANCE - 0x6000] | bus.sram[HITCHANCE + 1 - 0x6000] << 8
        return ("damage" if not cpu.p & 0x02 else "ineffective"), hc

    #  The undead, flag either way, any caster: as ever, hit chance untouched.
    for on in (False, True):
        for name in ("FT", "WM", "BM"):
            check("undead, %s, flag %s" % (name, on), hook(on, CLS[name], slot=1, undead=True), ("damage", 0x199))
    #  The living, flag off: ineffective, whoever casts.
    for name in ("WM", "WW", "RM"):
        check("living, %s, flag off" % name, hook(False, CLS[name])[0], "ineffective")
    #  The living, flag on: White Mages and Wizards in every slot, with no
    #  double to roll for; everyone else, as ever.
    for slot in range(4):
        for name in ("WM", "WW"):
            check("living, %s in slot %d, flag on" % (name, slot),
                  hook(True, CLS[name], slot=slot), ("damage", 0))
    for name in ("FT", "TH", "BB", "RM", "BM", "KN", "NJ", "MA", "RW", "BW"):
        check("living, %s, flag on" % name, hook(True, CLS[name])[0], "ineffective")
    #  No enemy casts HARM -- no vanilla script lists one and Enemy skills
    #  only redeals what the scripts hold -- but if one did, it would not be
    #  a White Mage, whatever sits in the party slot its low bits name.
    check("living, an enemy caster, flag on", hook(True, CLS["WM"], attacker=0x02)[0], "ineffective")

    #  The whole effect, run for real: BtlMag_Effect_DamageUndead stopped where
    #  it draws the damage, over every battle RNG state.  HARM's effectivity is
    #  20, so a hit is 20 to 40 and a double up to 80.
    HP = 0x687A
    def cast(on, cls, undead, state):
        bus, cpu = setup(on, cls, undead=undead)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        bus.sram[0x6874 - 0x6000] = 20          # btlmag_effectivity
        bus.sram[0x6870 - 0x6000] = 24          # btlmag_hitrate, HARM's
        bus.sram[0x6872 - 0x6000] = 0           # btlmag_defender_magdef
        bus.sram[0x685C - 0x6000] = 0           # btlmag_spellconnected
        bus.sram[HP - 0x6000], bus.sram[HP + 1 - 0x6000] = 0xF4, 0x01   # 500
        bus.sram[BTL_RNGSTATE - 0x6000] = state
        c = CPU(bus); c.dbr = BANK_0C
        c.run(BANK_0C, SYM["BtlMag_Effect_DamageUndead"], stop=SYM["DrawDamageCombatBox"])
        hp = bus.sram[HP - 0x6000] | bus.sram[HP + 1 - 0x6000] << 8
        return 500 - hp, bus.sram[0x685C - 0x6000], c.pc == SYM["DrawDamageCombatBox"]
    def survey(on, cls, undead):
        hits = [cast(on, cls, undead, s) for s in range(256)]
        return (sum(1 for d, conn, drew in hits if conn and drew),
                min(d for d, _, _ in hits), max(d for d, _, _ in hits),
                sum(1 for d, _, _ in hits if d > 40))
    n, lo, hi, doubles = survey(True, CLS["WM"], False)
    check("living, WM: every cast connects", n, 256)
    check("living, WM: 20 to 40, as FFR's average says", (lo >= 20, hi <= 80), (True, True))
    check("living, WM: almost never doubled", doubles <= 4, True)
    n, lo, hi, udoubles = survey(True, CLS["WM"], True)
    check("undead, WM: every cast connects", n, 256)
    check("undead: doubled as often as ever", udoubles > 128, True)
    check("undead: the flag changes nothing",
          [cast(True, CLS["WM"], True, s) for s in range(0, 256, 17)],
          [cast(False, CLS["WM"], True, s) for s in range(0, 256, 17)])
    n, lo, hi, _ = survey(True, CLS["BM"], False)
    check("living, BM, flag on: never connects, no damage", (n, hi), (0, 0))
    n, lo, hi, _ = survey(False, CLS["WM"], False)
    check("living, WM, flag off: never connects, no damage", (n, hi), (0, 0))

    tgt = SYM["opt_harmundead"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    img = ROMDATA[(BANK_0C & 0x1F) * 0x10000 + 0x8000:][:0x4000]
    check("DamageUndead calls opt_harmundead, once", img.count(jsl), 1)


# --- the selection menu's graphic and palette --------------------------------
#  Read through the selection pointer, not the casting one -- the same split
#  OptMagicTarget exists for.  Cast Life is where it showed: vanilla LIFE and
#  LIF2 are blank stubs, so the menu recorded graphic 0, which is not one of the
#  eight any spell uses, and the animation drew out of the caster's own CHR.
def test_magicgfx():
    MAGDATA = open('game/bin/0C_81E0_magicdata.bin','rb').read()
    SPELL_LIFE, SPELL_LIF2, SPELL_CURE, SPELL_HARM = 33, 56, 0, 10
    F_CASTLIFE = (3, 0x01)                      # bit 24
    BTLCMD_MAGGFX, BTLCMD_MAGPAL, BTLCMD_SPELLSEL = 0x68B3, 0x68B4, 0x6B7D

    def gfx(spell, castlife):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i,
                   F_CASTLIFE[1] if (castlife and i == F_CASTLIFE[0]) else 0)
        rec = MAGDATA[spell * 8: spell * 8 + 8]
        for k, b in enumerate(rec):             # ($80) -> the cartridge's record
            bus.wram[0x0500 + k] = b
        bus.wram[0x80], bus.wram[0x81] = 0x00, 0x05
        bus.sram[BTLCMD_SPELLSEL - 0x6000] = spell
        call(cpu, "opt_magicgfx")
        return (bus.sram[BTLCMD_MAGGFX - 0x6000],
                bus.sram[BTLCMD_MAGPAL - 0x6000]), (rec[5], rec[6])

    #  FFR's own values for the two spells, from SpellBalance.EnableLifeInBattle.
    check("LIFE with Cast Life on", gfx(SPELL_LIFE, True)[0], (224, 43))
    check("LIF2 with Cast Life on", gfx(SPELL_LIF2, True)[0], (224, 44))

    #  Off, they stay the blank stubs the cartridge ships, graphic 0 and all --
    #  which is exactly why the flag has to supply them.
    for name, spell in (("LIFE", SPELL_LIFE), ("LIF2", SPELL_LIF2)):
        got, van = gfx(spell, False)
        check("%s with Cast Life off is vanilla" % name, got, van)
        check("%s vanilla really is a blank stub" % name, van, (0, 0))

    #  And nothing else is disturbed, flag either way.
    for name, spell in (("CURE", SPELL_CURE), ("HARM", SPELL_HARM)):
        for on in (False, True):
            got, van = gfx(spell, on)
            check("%s untouched, Cast Life %s" % (name, "on" if on else "off"),
                  got, van)

    #  ...and that the game actually calls it.  Everything above passes with the
    #  routine present and the patch site reverted, which is how the bug got in:
    #  the reads are the wiring, not the routine.  So assert the wiring -- the
    #  JSL is there, and the unhooked sequence it replaced is not.
    rom = ROMDATA
    tgt = SYM["opt_magicgfx"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, CHUNK_OPT_BANK])
    check("the selection menu calls opt_magicgfx", jsl in rom, True)
    #  LDY #$05 / LDA ($80),Y / STA $68B3 -- the read it replaced
    unhooked = bytes([0xA0, 0x05, 0xB1, 0x80, 0x8D, 0xB3, 0x68])
    check("the unhooked graphic read is gone", unhooked in rom, False)


# --- Controller Reset -------------------------------------------------------
#  Two halves.  aux_detect in the HAL watches the pad once a frame and leaves
#  the combo it saw released in h_padreset; opt_padreset, called from
#  WaitForVBlank, acts on it.  Both are exercised here.
#
#  L + X restarts with work RAM intact so battlestep and battlestep_sign at $F5
#  and $F6 survive; that pair is the index into lut_RNG that decides whether a
#  step produces an encounter, and GameStart's ClearZeroPage stops at $EF.
#  L + Y clears zero page first, which takes them with it.
#
#  The edge is the press: the combo bits changed, and what they changed to is a
#  whole combo.
def test_padreset():
    JOYAUX_L, JOYAUX_X, JOYAUX_Y = 0x20, 0x40, 0x01
    SOFT = JOYAUX_L | JOYAUX_X
    HARD = JOYAUX_L | JOYAUX_Y
    MASK = SOFT | HARD
    H_AUX, H_PREV, H_FIRE = 0x08B9, 0x08BA, 0x08BB
    CHUNK0_BANK = 0xA1

    # --- the acting half ----------------------------------------------------
    def act(fire):
        bus, cpu = machine()
        for a in range(0x00, 0x100):        # recognisable in zero page...
            bus.wram[a] = 0xA5
        for a in range(0x200, 0x800):       # ...and past it, to catch a spill
            bus.wram[a] = 0x5E
        bus.wram[H_FIRE] = fire
        sram_before = bytes(bus.sram)
        cpu.a, cpu.x, cpu.y = 0x77, 0x5A, 0x3C
        cpu.pbr, cpu.pc = CHUNK_OPT_BANK, SYM["opt_padreset"]
        cpu.push(0xFF); cpu.push(0xFF); cpu.push(0xFD)
        what = "ran away at $%02X:%04X" % (cpu.pbr, cpu.pc)
        for _ in range(4000):
            if cpu.pc == 0xFFFE:
                what = "returned"; break
            if cpu.pbr == CHUNK0_BANK and cpu.pc == SYM["OnReset"]:
                what = "reset"; break
            cpu.step()
        return what, bus, cpu, sram_before

    #  Nothing pending is the common case -- this runs every frame of the game.
    what, bus, cpu, _ = act(0x00)
    check("nothing pending: returns", what, "returned")
    check("nothing pending: A preserved", cpu.a, 0x77)
    check("nothing pending: X preserved", cpu.x, 0x5A)
    check("nothing pending: zero page untouched", bus.wram[0x80], 0xA5)

    what, bus, _, sram = act(SOFT)
    check("soft pending: resets", what, "reset")
    check("soft pending: battlestep survives", bus.wram[0xF5], 0xA5)
    check("soft pending: battlestep_sign survives", bus.wram[0xF6], 0xA5)
    check("soft pending: zero page untouched", bus.wram[0x80], 0xA5)
    check("soft pending: flag cleared so it cannot re-fire", bus.wram[H_FIRE], 0x00)
    check("soft pending: SRAM untouched", bytes(bus.sram), sram)

    what, bus, _, sram = act(HARD)
    check("hard pending: resets", what, "reset")
    check("hard pending: battlestep cleared", bus.wram[0xF5], 0x00)
    check("hard pending: battlestep_sign cleared", bus.wram[0xF6], 0x00)
    check("hard pending: zero page cleared", sum(bus.wram[0x01:0x100]), 0)
    check("hard pending: $00 left alone", bus.wram[0x00], 0xA5)
    check("hard pending: flag cleared so it cannot re-fire", bus.wram[H_FIRE], 0x00)
    #  The one that matters most: a hard reset must not cost the save file or the
    #  settings.  unsram is $6000, the saved file $6400-$67FF and the option
    #  block $6E00, all SRAM -- and the wipe is direct-page, so it cannot reach
    #  them whatever DBR holds.  The stack page is skipped below because this
    #  harness's own pushes live there.
    check("hard pending: SRAM untouched", bytes(bus.sram), sram)
    check("hard pending: WRAM past zero page untouched",
          set(bus.wram[0x0200:0x0800]), {0x5E})

    # --- the detecting half -------------------------------------------------
    #  aux_detect reads the pad itself, so drive h_joyaux and call the part
    #  below the capture.  Feeding one reading per call is one frame per call.
    if "aux_edge" not in SYM:
        skipped.append("aux_detect's edge: no aux_edge symbol to call")
        return

    def detect(seq, prev=0x00):
        bus, cpu = machine()
        bus.wram[H_PREV] = prev
        bus.wram[H_FIRE] = 0x00
        fired = []
        for i, aux in enumerate(seq):
            bus.wram[H_AUX] = aux
            cpu.pbr, cpu.pc = 0xC0, SYM["aux_edge"]   # HALBANK
            cpu.push(0xFF); cpu.push(0xFF); cpu.push(0xFD)
            for _ in range(400):
                if cpu.pc == 0xFFFE:
                    break
                cpu.step()
            if bus.wram[H_FIRE]:
                fired.append((i, bus.wram[H_FIRE]))
                bus.wram[H_FIRE] = 0x00
        return fired

    #  The press is the edge, and only the press: holding fires once, on the
    #  first frame, and never again however long it is held.
    check("soft pressed and held: fires once, on the first frame",
          detect([SOFT] * 8), [(0, SOFT)])
    check("hard pressed and held: fires once, on the first frame",
          detect([HARD] * 8), [(0, HARD)])
    check("soft pressed a frame in", detect([0x00, SOFT, SOFT]), [(1, SOFT)])

    #  Releasing is not an edge -- that is the whole change from the previous
    #  arrangement, and the reason the reset cannot go round again: the buttons
    #  are still held when the title screen comes up, prev already holds the
    #  combo, so there is nothing for the next frame to see.
    check("released again: no second fire",
          detect([SOFT, SOFT, 0x00, 0x00]), [(0, SOFT)])
    check("still held after a reset: no second fire", detect([SOFT], prev=SOFT), [])

    #  Arriving at a combo from a partial press counts, since the bits changed
    #  and what they changed to is a combo.
    check("L first, then X", detect([JOYAUX_L, SOFT]), [(1, SOFT)])
    check("Y first, then L", detect([JOYAUX_Y, HARD]), [(1, HARD)])

    #  L with X and Y together is neither combo -- the decode is CPX on the
    #  masked byte, not AND -- and rolling off it into one is.
    check("L with both X and Y", detect([MASK] * 4), [])
    check("all three, then X released", detect([MASK, HARD]), [(1, HARD)])

    #  A combo left in h_joyauxprev by power-on WRAM cannot fire on a press
    #  edge: the first frame can only clear it.  hal_reset zeroes it anyway.
    check("stale combo remembered, nothing held: never fires",
          detect([0x00] * 4, prev=SOFT), [])

    #  No other reading fires.
    bad = None
    for aux in range(0x100):
        got = detect([aux])
        want = [(0, aux & MASK)] if (aux & MASK) in (SOFT, HARD) else []
        if got != want:
            bad = (aux, got, want); break
    check("every aux reading, pressed from nothing", bad, None)


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
F_IDTREASURE = 1 << 4


DLGID_TCGET, DLGID_CANTCARRY = 0xF0, 0xF1


def _chestinfo(flagbits, dlgid, itemid, dlgsfx=2):
    bus, cpu = machine()
    for i in range(4):
        setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
    bus.wram[0x61] = itemid             # dlg_itemid
    bus.wram[0x7D] = dlgsfx             # dlgsfx -- deliberately NOT the tell
    bus.sram[OPTDESC - 0x6000] = 0xAA   # poison: untouched means no description
    cpu.a = dlgid                       # the dialogue being drawn, the real tell
    try:
        call(cpu, "opt_chestinfo")
    except Exception:
        return "drew"                   # got past the gate, into the PPU
    return "drew" if bus.sram[OPTDESC - 0x6000] != 0xAA else "skipped"


def test_chestinfo():
    #  What tells a chest from a conversation is the dialogue id, and only that.
    #  This used to read dlgsfx, which is not a chest flag but which sound to
    #  play: every NPC who hands over an item sets it for the fanfare, so Sarda
    #  giving up the Rod drew the stats of the last weapon out of a chest across
    #  his line.  Every case below therefore leaves dlgsfx at 2 -- the chest
    #  jingle, the most misleading value there is -- so reading it again cannot
    #  pass this.
    check("a conversation draws nothing, whatever was last in a chest",
          _chestinfo(F_CHESTINFO, 0x00, 0x1C), "skipped")
    check("the flag off draws nothing",
          _chestinfo(0, DLGID_TCGET, 0x1C), "skipped")

    #  The three that pin down the regression.  Sarda's dialogue is an ordinary
    #  id with the fanfare set; the Black Orb's plays the chest jingle outright,
    #  which is why narrowing to dlgsfx = 2 would not have been enough; and
    #  "you can't carry anymore" is a chest but not a chest *get*, and has its
    #  own handling in opt_dlgident.
    check("an item-giving NPC draws nothing", _chestinfo(F_CHESTINFO, 0x2A, 0x1C, dlgsfx=1), "skipped")
    check("the Black Orb draws nothing", _chestinfo(F_CHESTINFO, 0x31, 0x1C, dlgsfx=2), "skipped")
    #  The full-inventory message gets the description too, but only with
    #  Identify Treasures also on -- that is what makes it a one-line message
    #  naming the item, which is what OPTCHEST_DY assumes.
    check("a full inventory, Chest Information alone",
          _chestinfo(F_CHESTINFO, DLGID_CANTCARRY, 0x1C), "skipped")
    check("a full inventory, both flags",
          _chestinfo(F_CHESTINFO | F_IDTREASURE, DLGID_CANTCARRY, 0x1C), "drew")
    check("a full inventory, Identify Treasures alone",
          _chestinfo(F_IDTREASURE, DLGID_CANTCARRY, 0x1C), "skipped")
    check("a full inventory holding a potion still draws nothing",
          _chestinfo(F_CHESTINFO | F_IDTREASURE, DLGID_CANTCARRY, 0x19), "skipped")

    #  Potions and key items have no description; only gear does.
    for itemid in (0x00, 0x01, 0x19, 0x1B, 0x6C):
        check("a chest holding item $%02X draws nothing" % itemid,
              _chestinfo(F_CHESTINFO, DLGID_TCGET, itemid), "skipped")
    for itemid in (0x1C, 0x2F, 0x43, 0x44, 0x6B):
        check("a chest holding item $%02X describes it" % itemid,
              _chestinfo(F_CHESTINFO, DLGID_TCGET, itemid), "drew")
    #  The renderer is shared with the shops, so a spell id would describe
    #  itself too -- no chest in the game contains one.
    check("the renderer is the shops own",
          _chestinfo(F_CHESTINFO, DLGID_TCGET, 0xB0), "drew")


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
#  Each is now the Free value of its key item row (ITEMROW_*), two bits of
#  RANDO_ITEMS; the settings' copy is OPT_NG_ITEMS, which rando_newgame copies
#  into the save opt_freestuff then reads.  "Bits" below are row numbers.
FREE_BIT = {"ship_vis": 0, "airship_vis": 1, "bridge_vis": 2,
            "canal_vis": 3, "has_canoe": 4}
#  The three key items are plain inventory entries in the same page.
FREE_ITEM = {"item_mystickey": (0x25, 5), "item_chime": (0x2C, 6),
             "item_crown": (0x22, 7), "item_lute": (0x21, 8),
             "item_tail": (0x2D, 9), "item_rod": (0x2A, 10)}


def set_free(bus, rows, value=2):
    """Set each ITEMROW_* in rows (a mask) to value in the settings' copy --
    ITEM_FREE by default -- and every other row to Incentive."""
    at = K["OPT_NG_ITEMS"] - 0x6000
    for b in range(3):
        bus.sram[at + b] = 0
    for k in range(12):
        if rows >> k & 1:
            bus.sram[at + k // 4] |= value << (2 * (k % 4))


def _freestuff(flagbits):
    bus, cpu = machine()
    set_free(bus, flagbits)
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
        set_free(bus, flagbits)
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
        set_free(bus, flagbits)
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

    #  Only Free gives: Incentive and Loose say where an item is placed, and
    #  every row at either leaves a new game as it always was.
    for value, name in ((0, "Incentive"), (1, "Loose")):
        bus, cpu = machine()
        set_free(bus, (1 << 12) - 1, value)
        for n, off in FREE_VEHICLE.items():
            bus.sram[FREE_UNSRAM - 0x6000 + off] = FREE_DEFAULT[n]
        for off, _ in FREE_ITEM.values():
            bus.sram[off] = 0
        call(cpu, "opt_freestuff")
        check("every row %s: no vehicle given" % name,
              {n: bus.sram[FREE_UNSRAM - 0x6000 + off] for n, off in FREE_VEHICLE.items()},
              FREE_DEFAULT)
        check("every row %s: no key item given" % name,
              {n: bus.sram[off] for n, (off, _) in FREE_ITEM.items()}, {n: 0 for n in FREE_ITEM})

    #  The starting items: FFR's nine fixed sets, StartingInventory.cs, as
    #  counts of TENT, CABIN, HOUSE, HEAL, PURE and SOFT.  Transcribed from
    #  FFR's table, not from lut_StartItems.  The counts start at zero, as
    #  lut_InitUnsramFirstPage leaves them; anything else is kept off them
    #  by the set's own row, zeros included.
    SETS = [(0, 0, 0, 0, 0, 0), (1, 0, 0, 0, 1, 1), (5, 0, 0, 20, 2, 1),
            (10, 0, 0, 0, 0, 0), (10, 0, 0, 50, 4, 2), (15, 5, 1, 0, 0, 0),
            (15, 5, 1, 50, 6, 3), (50, 15, 5, 99, 10, 5), (99,) * 6]
    TENT = 0x36                         # unsram + $20 + $16, item_tent
    def consumables(step, flagbits=0):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
        setblk(bus, OPT_STARTITEMS, step)
        for i in range(-2, 8):                  # a decoy byte either side
            bus.sram[TENT + i] = 0
        call(cpu, "opt_freestuff")
        return tuple(bus.sram[TENT - 2:TENT + 8])
    for step, want in enumerate(SETS):
        check("starting set %d" % step, consumables(step), (0, 0) + want + (0, 0))
    check("a step past the table gives nothing", consumables(9), (0,) * 10)
    check("...nor does $FF", consumables(0xFF), (0,) * 10)
    check("the Explorer Pack beside every Treasures flag",
          consumables(4, sum(1 << b for b in list(FREE_BIT.values())
                             + [b for _, b in FREE_ITEM.values()])),
          (0, 0) + SETS[4] + (0, 0))

    #  Bits 32 and 33 live in the fifth flag byte, which only exists because
    #  the block grew; a four-byte word would drop them silently.
    check("the flag word is wide enough to hold them",
          OPT_GOLDXP - OPT_FLAGS, 6)


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
CH_CURHP = 0x610A                # ch_stats + $0A, 2 bytes
CH_MAXHP = 0x610C                # ch_stats + $0C, 2 bytes
CH_CURMP = 0x6320
CH_MAXMP = 0x6328
CH_STRIDE = 0x40
OPTF_HOUSEMP_BIT = 15


def test_housemp():
    #  A late-game party has several hundred HP, so the vanilla 120 is a
    #  fraction of a rest; the flag fills it.  Max HP here is 999 to make a
    #  partial restore distinguishable -- on an early party 120 saturates
    #  against a lower maximum and the two cannot be told apart, which is why
    #  this went unnoticed through a whole playthrough.
    MAXHP = 999

    #  opt_housemp now ends in a repaint, and the repaint reaches the HAL's
    #  PPU shims, which this machine does not implement and has no business
    #  implementing.  Stub it with an RTS so the arithmetic stays runnable; the
    #  call itself is checked below against the untouched image.
    draw = (((0xA1 + 0x0E) & 0x1F) * 0x10000) + SYM["DrawItemTargetMenu"]
    stubbed = bytearray(ROMDATA)
    stubbed[draw] = 0x60

    def run(flagged, ailments=(0, 0, 0, 0), curhp=0):
        bus, cpu = machine()
        bus.rom = stubbed
        if flagged:
            setblk(bus, OPT_FLAGS + OPTF_HOUSEMP_BIT // 8, 1 << (OPTF_HOUSEMP_BIT % 8))
        for c in range(4):
            bus.sram[CH_AILMENTS + c * CH_STRIDE - 0x6000] = ailments[c]
            for lvl in range(8):
                bus.sram[CH_MAXMP + c * CH_STRIDE + lvl - 0x6000] = 9
                bus.sram[CH_CURMP + c * CH_STRIDE + lvl - 0x6000] = 0
            for off, v in ((CH_MAXHP, MAXHP), (CH_CURHP, curhp)):
                bus.sram[off + c * CH_STRIDE - 0x6000] = v & 0xFF
                bus.sram[off + c * CH_STRIDE + 1 - 0x6000] = v >> 8
        call(cpu, "opt_housemp")
        mp = [bus.sram[CH_CURMP + c * CH_STRIDE - 0x6000] for c in range(4)]
        hp = [bus.sram[CH_CURHP + c * CH_STRIDE - 0x6000]
              | bus.sram[CH_CURHP + c * CH_STRIDE + 1 - 0x6000] << 8
              for c in range(4)]
        return mp, hp

    check("flag clear: a HOUSE does not touch MP here", run(False)[0], [0, 0, 0, 0])
    check("flag clear: nor HP -- the call site's 120 is all of it",
          run(False)[1], [0, 0, 0, 0])
    check("flag set: every living character is refilled", run(True)[0], [9, 9, 9, 9])
    check("flag set: and filled to maximum HP, not by 120",
          run(True)[1], [MAXHP] * 4)
    #  The routines it reaches are the game's own, which skip the dead and the
    #  stoned.  Checking that is how we know the trampoline landed on them and
    #  not on whatever else is at those addresses.
    check("the dead and the stoned are skipped",
          run(True, ailments=(0, 0x01, 0x02, 0))[0], [9, 0, 0, 9])
    check("...for HP as well",
          run(True, ailments=(0, 0x01, 0x02, 0))[1], [MAXHP, 0, 0, MAXHP])

    #  The numbers being right is not enough: neither MenuFillPartyHP nor
    #  MenuRecoverPartyMP repaints, and the MenuRecoverPartyHP the call site
    #  uses ends in a JMP to DrawItemTargetMenu.  Porting the fills without
    #  that redraw left them correct and invisible -- the save prompt sat over
    #  the pre-fill figures.  Nothing here can run the draw, so look for the
    #  call: all three go out through OptCallFar, so find the routine's own
    #  bytes and require the redraw among the addresses it hands over.
    #  CALL0E hands the target to OptCallFar as two immediates -- "LDA #<addr"
    #  then "LDA #>addr" into OPTCALLV -- so there is no 16-bit address in the
    #  instruction stream to look for, only that pair in that order.
    body = ROMDATA[(CHUNK_OPT_BANK & 0x1F) * 0x10000 + SYM["opt_housemp"]:][:96]
    missing = []
    for name in ("MenuFillPartyHP", "MenuRecoverPartyMP", "DrawItemTargetMenu"):
        a = SYM[name]
        #  The high byte has to follow this call's own low byte, not whichever
        #  came first: MenuFillPartyHP and MenuRecoverPartyMP share $AB, and a
        #  plain find for the high byte matches the earlier call every time.
        #  SET0E puts the pair six bytes apart, so allow a little slack.
        lo = body.find(bytes([0xA9, a & 0xFF]))
        hi = body.find(bytes([0xA9, a >> 8]), lo + 1) if lo >= 0 else -1
        if lo < 0 or hi < 0 or hi - lo > 8:
            missing.append(name)
    check("the fills and the repaint are all reached from opt_housemp",
          sorted(missing), [])

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

    #  The control, exhaustively.  With the flag off this hook has to leave
    #  the byte exactly as the three ASLs it replaced left it, for every
    #  possible input -- and that is the half a playthrough cannot check,
    #  because vanilla's agility gain is a 25% roll per level rather than
    #  every fourth, so watching three level-ups proves nothing either way.
    drift = [b for b in range(256) if growth(CLS_TH, False, b) != (b << 3) & 0xFF]
    check("flag clear: the byte is what three ASLs made of it", drift, [])


#  ...and the separate setting on the same two classes: hit rate grows by a
#  per-class constant each level -- 3 for the Fighter, 2 for these two, 1 for
#  the mages -- and this raises theirs to FFR's Vanilla, Moderate or Double:
#  2, 3 or 4.  It was a checkbox doing Double until Improved took Moderate.
#  The table is the original game's, from the disassembly, not the hook's.
VANILLA_HITBONUS = (3, 2, 3, 2, 1, 1, 3, 2, 3, 2, 1, 1)
CLASS_NAMES = ("FT", "TH", "BB", "RM", "WM", "BM", "KN", "NJ", "MA", "RW", "WW", "BW")
LVLUP_CHMAGIC = 0x84
CH_LEVEL_OFF, CH_STR_OFF, CH_AGIL_OFF = 0x26, 0x10, 0x11
CH_DMG_OFF, CH_HIT_OFF, CH_EVADE_OFF = 0x20, 0x21, 0x23
BANK_0B = 0xA1 + 0x0B
STARTSTATS = 0xB040                 # lut_ClassStartingStats, in chunk 0


def test_thiefhit():
    def grow(cls, step, before=50):
        bus, cpu = machine()
        setblk(bus, OPT_THIEFHIT, step)
        cpu.a = before
        cpu.x = cls
        cpu.p &= ~0x01                      # carry clear, as the CLC before it
        call(cpu, "opt_hitgrowth")
        return cpu.a & 0xFF

    wrong = []
    for step in range(3):
        for cls in range(12):
            want = 50 + VANILLA_HITBONUS[cls] + (step if cls in (CLS_TH, CLS_NJ) else 0)
            if grow(cls, step) != want:
                wrong.append((CLASS_NAMES[cls], step, grow(cls, step), want))
    check("hit growth: the table's, plus the step for TH and NJ only", wrong, [])

    #  The whole of it, end to end: a Thief or Ninja levelled from 1 to 50
    #  through the cartridge's own LvlUp_LevelUp, stopped where it starts
    #  drawing the level-up boxes, every stat applied by then.  Held against
    #  FFR's rules rather than anything in the hooks:
    #    - hit rate is the class's start plus 2, 3 or 4 a level, capped at 200;
    #    - with Better Thief and Ninja, agility is 80 plus one a level, held
    #      at 99, and evade 128 plus one a level -- the original code grants
    #      the evade point even when agility is capped, in FFR as here.
    #  The 25% rolls for strength and the rest come from BattleRNG, which
    #  reads the randomizer's cache; rando_ensure builds it, or every roll
    #  would succeed.  A promoted Ninja levels on the Thief's data.
    def levels(cls, step, agibuff):
        bus, cpu = machine()
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        setblk(bus, OPT_THIEFHIT, step)
        if agibuff:
            setblk(bus, OPT_FLAGS + OPTF_THIEFNINJA_BIT // 8,
                   1 << (OPTF_THIEFNINJA_BIT % 8))
        s = bus.sram
        base = CH_CLASS - 0x6000
        start = [bus.read(0xA1, STARTSTATS + CLS_TH * 16 + i) for i in range(11)]
        s[base] = cls
        s[base + CH_STR_OFF:base + CH_STR_OFF + 5] = bytes(start[2:7])
        s[base + CH_DMG_OFF] = start[7]
        s[base + CH_HIT_OFF] = start[8]
        s[base + CH_EVADE_OFF] = start[9]
        if agibuff:                         # the new-game hooks, for a Thief
            for name in ("opt_startagi", "opt_startevade"):
                c = CPU(bus); c.dbr = 0xA7; c.x = 0; c.y = CLS_TH * 16
                s[base] = CLS_TH
                call(c, name)
            s[base] = cls
        bus.wram[LVLUP_CHSTATS] = CH_CLASS & 0xFF
        bus.wram[LVLUP_CHSTATS + 1] = CH_CLASS >> 8
        bus.wram[LVLUP_CHMAGIC] = CH_MAGICDATA & 0xFF
        bus.wram[LVLUP_CHMAGIC + 1] = CH_MAGICDATA >> 8
        got = {}
        for _ in range(49):
            c = CPU(bus); c.dbr = BANK_0B
            c.run(BANK_0B, SYM["LvlUp_LevelUp"], stop=SYM["Draw4EobBoxes"])
            if c.pc != SYM["Draw4EobBoxes"]:
                return None
            lv = s[base + CH_LEVEL_OFF] + 1
            got[lv] = (s[base + CH_HIT_OFF], s[base + CH_AGIL_OFF], s[base + CH_EVADE_OFF])
        return got, start[8]

    for cls in (CLS_TH, CLS_NJ):
        for step in range(3):
            for agibuff in (False, True):
                what = "%s step %d%s" % (CLASS_NAMES[cls], step, ", agility buff" if agibuff else "")
                r = levels(cls, step, agibuff)
                if r is None:
                    check(what + ": reaches the level-up boxes", False, True)
                    continue
                got, hit0 = r
                check(what + ": reaches level 50", sorted(got)[-1], 50)
                check(what + ": hit rate every level",
                      [got[lv][0] for lv in range(2, 51)],
                      [min(200, hit0 + (2 + step) * (lv - 1)) for lv in range(2, 51)])
                if agibuff:
                    check(what + ": agility every level",
                          [got[lv][1] for lv in range(2, 51)],
                          [min(99, 80 + lv - 1) for lv in range(2, 51)])
                    check(what + ": evade every level",
                          [got[lv][2] for lv in range(2, 51)],
                          [min(200, 128 + lv - 1) for lv in range(2, 51)])


# --- the spell data flags ---------------------------------------------------
#  Spell Fixes, Cast Life in battle and the LOCK/LOK2 toggle all replace bytes
#  of a spell's record.  They go through one accessor, opt_spelloverride, that
#  the battle and the shop's description box both ask -- so what the box says
#  and what gets cast cannot drift.
F_SPELLFIX = 1 << 17
F_CASTLIFE = 1 << 24
F_LOK2 = 1 << 25
MATH_MAGRANDHIT = 0x685A
SPELL_LOCK, SPELL_LOK2, SPELL_HEL2 = 6, 23, 35
SPELL_SABR, SPELL_LIFE, SPELL_LIF2 = 54, 33, 56
FLD_HIT, FLD_EFFY, FLD_ELEM, FLD_TGT, FLD_EFFECT, FLD_GFX, FLD_PAL = range(7)


def _spellbyte(spell, field, flagbits):
    bus, cpu = machine()
    for i in range(5):
        setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
    cpu.x, cpu.y = spell, field
    call(cpu, "opt_spellbyte", dbr=0xA7)
    return cpu.a & 0xFF


def test_spellflags():
    mag = open(os.path.join(ROOT, "game", "bin", "0C_81E0_magicdata.bin"), "rb").read()
    def rom(spell, field):
        return mag[spell * 8 + field]

    #  Nothing on: every byte of every record is the cartridge's.
    drift = [(sp, f) for sp in range(64) for f in range(8)
             if _spellbyte(sp, f, 0) != rom(sp, f)]
    check("no flags: the accessor is the record", drift, [])

    #  Spell Fixes, the four data corrections FFR makes plus the accuracy the
    #  LOCK dropdown makes, which is a flag here instead.
    for spell, field, want, what in (
            (SPELL_LOK2, FLD_EFFECT, 0x0E, "LOK2 ran the wrong routine"),
            (SPELL_HEL2, FLD_EFFY,     24, "HEL2 healed for less than it said"),
            (SPELL_SABR, FLD_HIT,      10, "SABR had no hit% bonus"),
            (SPELL_LOCK, FLD_HIT,     162, "LOCK never landed at 64"),
            (SPELL_LOK2, FLD_HIT,     162, "LOK2 likewise")):
        check("spell fixes: %s" % what,
              _spellbyte(spell, field, F_SPELLFIX), want)

    #  ...and the ordering question.  Both flags want HEL2's effectivity;
    #  the deliberate buff wins over a correction that only lowers it.
    check("HEL2 with spell fixes alone", _spellbyte(SPELL_HEL2, FLD_EFFY, F_SPELLFIX), 24)
    check("HEL2 with improved cure alone",
          _spellbyte(SPELL_HEL2, FLD_EFFY, F_IMPCURE), 0x20)
    check("HEL2 with both: the buff wins",
          _spellbyte(SPELL_HEL2, FLD_EFFY, F_SPELLFIX | F_IMPCURE), 0x20)

    #  Cast Life rewrites both records outright: routine $08, cure ailment,
    #  with the death element, which is what revives.
    want = {SPELL_LIFE: (0, 0x01, 0, 0x10, 0x08, 224, 43),
            SPELL_LIF2: (0, 0x81, 0, 0x10, 0x08, 224, 44)}
    for spell, rec in want.items():
        got = tuple(_spellbyte(spell, f, F_CASTLIFE) for f in range(7))
        check("cast life: spell %d's record" % spell, got, rec)
    #  The LOK2 toggle beats Spell Fixes' 162 with an accuracy of 255: the
    #  roll is [0,200] and BtlMag_DidSpellConnect only compares the two.
    for spell in (SPELL_LOCK, SPELL_LOK2):
        check("always-hit: spell %d accuracy" % spell,
              _spellbyte(spell, FLD_HIT, F_LOK2), 255)
        check("always-hit beats spell fixes' 162",
              _spellbyte(spell, FLD_HIT, F_LOK2 | F_SPELLFIX), 255)

    #  ...and the roll vanilla never takes.  Z set means go on to the connect
    #  check; 200 is a guaranteed miss everywhere else in that bank.
    def roll(flagbits, r):
        bus, cpu = machine()
        for i in range(5):
            setblk(bus, OPT_FLAGS + i, (flagbits >> (8 * i)) & 0xFF)
        bus.sram[MATH_MAGRANDHIT - 0x6000] = r
        call(cpu, "opt_lockroll", dbr=0xA7)
        return bool(cpu.p & 0x02)       # Z

    check("no flags: LOCK still does nothing", roll(0, 100), False)
    check("spell fixes: an ordinary roll goes on", roll(F_SPELLFIX, 100), True)
    check("spell fixes: 200 is the guaranteed miss", roll(F_SPELLFIX, 200), False)
    check("always-hit: 200 does not stop it", roll(F_LOK2, 200), True)
    check("always-hit alone is enough", roll(F_LOK2, 100), True)

    #  ...and leaves everything else alone.
    drift = [(sp, f) for sp in range(64) for f in range(8)
             if sp not in want and _spellbyte(sp, f, F_CASTLIFE) != rom(sp, f)]
    check("cast life touches only LIFE and LIF2", drift, [])


# --- TMPR and SABR on a player ----------------------------------------------
#  Both raise the target's attack, SABR its hit rate too, and neither has ever
#  worked on a player: BtlMag_LoadPlayerDefenderStats never loaded the
#  defender's strength or hit rate and the save routine never wrote them back,
#  so the spell added its effectivity to whatever happened to be there.
IB_PTR, OB_PTR = 0x90, 0x92
IB_BASE, OB_BASE = 0x6800, 0x6900          # anywhere in SRAM will do
BTLCH_HITRATE, BTLCH_MAGDEF, BTLCH_EVADE, BTLCH_DMG = 5, 6, 7, 9
MAG_MAGDEF, MAG_STRENGTH, MAG_DEFHIT = 0x6872, 0x6882, 0x6884
MAG_EVADE = 0x6885
CH_MAGDEF_OFF = 0x25                        # ch_magdef - ch_stats = $20 + $05


def _entity(bus):
    for ptr, base in ((IB_PTR, IB_BASE), (OB_PTR, OB_BASE)):
        bus.wram[ptr] = base & 0xFF
        bus.wram[ptr + 1] = base >> 8


def test_tmprsabr():
    def load(flagged):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + 2, 0x02)        # bit 17
        _entity(bus)
        for off, v in ((BTLCH_MAGDEF, 11), (BTLCH_DMG, 22), (BTLCH_HITRATE, 33)):
            bus.sram[IB_BASE + off - 0x6000] = v
        for a in (MAG_MAGDEF, MAG_STRENGTH, MAG_DEFHIT):
            bus.sram[a - 0x6000] = 0
        call(cpu, "opt_magloaddef")
        return tuple(bus.sram[a - 0x6000]
                     for a in (MAG_MAGDEF, MAG_STRENGTH, MAG_DEFHIT))

    check("load, flag clear: magdef only, as vanilla", load(False), (11, 0, 0))
    check("load, flag set: strength and hit rate too", load(True), (11, 22, 33))

    def save(flagged):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + 2, 0x02)
        _entity(bus)
        for a, v in ((MAG_EVADE, 44), (MAG_STRENGTH, 55), (MAG_DEFHIT, 66)):
            bus.sram[a - 0x6000] = v
        for off in (BTLCH_EVADE, BTLCH_DMG, BTLCH_HITRATE):
            bus.sram[IB_BASE + off - 0x6000] = 0
        call(cpu, "opt_magsavedef")
        return tuple(bus.sram[IB_BASE + off - 0x6000]
                     for off in (BTLCH_EVADE, BTLCH_DMG, BTLCH_HITRATE))

    check("save, flag clear: evade only, as vanilla", save(False), (44, 0, 0))
    check("save, flag set: strength and hit rate go back", save(True), (44, 55, 66))

    #  ...and magic defence, which vanilla writes to the out-of-battle record
    #  where the change would outlast the fight.
    def magdef(flagged):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + 2, 0x02)
        _entity(bus)
        bus.sram[IB_BASE + BTLCH_MAGDEF - 0x6000] = 0
        bus.sram[OB_BASE + CH_MAGDEF_OFF - 0x6000] = 0
        cpu.a = 77
        call(cpu, "opt_magsavemagdef")
        return (bus.sram[IB_BASE + BTLCH_MAGDEF - 0x6000],
                bus.sram[OB_BASE + CH_MAGDEF_OFF - 0x6000])

    check("magdef, flag clear: to the permanent record", magdef(False), (0, 77))
    check("magdef, flag set: to the in-battle one", magdef(True), (77, 0))


# --- CUR4 out of battle -----------------------------------------------------
#  Every spell in that menu refuses a dead or stoned target and comes back for
#  another.  CUR4 never did, so it would refill a corpse's HP -- and the
#  corpse stayed dead, because it still had the ailment.  Spell and MP gone.
CH_CURHP, CH_MAXHP = 0x610A, 0x610C


def test_cur4():
    def cast(ailment, flagged, who=0):
        bus, cpu = machine()
        if flagged:
            setblk(bus, OPT_FLAGS + 2, 0x02)        # bit 17
        base = who * 0x40
        bus.sram[CH_AILMENTS + base - 0x6000] = ailment
        bus.sram[CH_MAXHP + base - 0x6000] = 200
        bus.sram[CH_MAXHP + 1 + base - 0x6000] = 1  # 456 max
        bus.sram[CH_CURHP + base - 0x6000] = 7
        bus.sram[CH_CURHP + 1 + base - 0x6000] = 0
        cpu.x = base
        call(cpu, "opt_cur4")
        hp = (bus.sram[CH_CURHP + base - 0x6000]
              | bus.sram[CH_CURHP + 1 + base - 0x6000] << 8)
        return hp, bool(cpu.p & 0x01)               # HP, carry


    check("flag clear: a corpse is healed anyway", cast(1, False), (456, True))
    check("flag set: the dead are refused", cast(1, True), (7, False))
    check("flag set: the stoned are refused", cast(2, True), (7, False))
    check("flag set: the living are healed", cast(0, True), (456, True))
    #  ...and it is the cursor's character that gets it, not always the first.
    check("the target is the one the cursor picked",
          cast(0, True, who=2), (456, True))


# --- the title screen's rows -------------------------------------------------
#  Four rows now: Continue, New Game, the mode, and Credits.  Up and down wrap
#  over all four, and left and right are the preset on the mode row and the
#  respond rate everywhere else -- Credits included, which has nothing of its
#  own to the side.  A wrap still sized for three rows sends Down from the
#  mode row back to Continue, and Credits can never be reached.
TITLE_CURSOR, RESPONDRATE = 0x62, 0xFA
DIR_RIGHT, DIR_DOWN, DIR_UP = 0x01, 0x04, 0x08


def test_titlerows():
    for row in range(4):
        for name, d, want in (("down", DIR_DOWN, (row + 1) % 4),
                              ("up", DIR_UP, (row - 1) % 4)):
            bus, cpu = machine()
            bus.wram[TITLE_CURSOR] = row
            cpu.a = d
            call(cpu, "opt_titleupdown")
            check("title row %d, %s" % (row, name), bus.wram[TITLE_CURSOR], want)

    for row, rate_moves in ((0, True), (1, True), (2, False), (3, True)):
        bus, cpu = machine()
        call(cpu, "opt_init")
        bus.wram[TITLE_CURSOR] = row
        bus.wram[RESPONDRATE] = 3
        setblk(bus, OPT_RESPOND, 3)
        preset = blk(bus, OPT_PRESET)
        cpu.a = DIR_RIGHT
        call(cpu, "opt_titleleftright")
        check("title row %d, right: respond rate" % row,
              bus.wram[RESPONDRATE], 4 if rate_moves else 3)
        check("title row %d, right: preset" % row,
              blk(bus, OPT_PRESET), preset if rate_moves else (preset + 1) % 4)


# --- the equip box takes the cursor off the screen -------------------------
#  The hand cursor in the weapon and armour screens sits over the area the
#  description box covers, so opt_showbox clears OAM before drawing it -- but
#  only for the equip menu, since the shop's box and cursor do not overlap and
#  clearing there would cost the victory poses.  FFR does the same, in the same
#  place.
#
#  opt_showbox is not exported, so this looks for the instructions themselves
#  in the options chunk.  A wiring assertion rather than a behavioural one:
#  nothing here can run opt_showbox, since it ends in a wait for a button, and
#  the way this breaks is that the cursor is simply still there -- invisible to
#  every other test and visible only to someone playing.
def test_equipcursor():
    OPTCTX_A, OPTCTX_EQUIP, TEXT_PTR = 0x6EC1, 1, 0x3E
    clearoam = SYM.get("ClearOAM")
    check("ClearOAM is in the fixed bank, so a JSR reaches it from any chunk",
          clearoam is not None and clearoam >= 0xC000, True)
    if clearoam is None:
        return

    #  ClearOAM only fills the staging page; the DMA that follows is what puts
    #  the blank in OAMSHADOW, so the flush during DrawBox's stall shows it.
    #  Without the DMA the cursor stays up until the menu's next frame, which is
    #  after the box rather than before it -- so the pair is the assertion, not
    #  the clear alone.
    oamdma = SYM.get("nesio_oamdma")
    check("nesio_oamdma is reachable by JSR from the options chunk",
          oamdma is not None and oamdma >= 0xC000, True)
    if oamdma is None:
        return
    gate = bytes([0xAD, OPTCTX_A & 0xFF, OPTCTX_A >> 8,   # LDA OPTCTX
                  0xC9, OPTCTX_EQUIP,                     # CMP #OPTCTX_EQUIP
                  0xD0, 0x08,                             # BNE over both calls
                  0x20, clearoam & 0xFF, clearoam >> 8,   # JSR ClearOAM
                  0xA9, 0x02,                             # LDA #>oam
                  0x20, oamdma & 0xFF, oamdma >> 8])      # JSR nesio_oamdma
    base = (CHUNK_OPT_BANK & 0x1F) * 0x10000
    chunk = ROMDATA[base + 0x8000: base + 0x10000]

    at, hits = chunk.find(gate), []
    while at >= 0:
        hits.append(at)
        at = chunk.find(gate, at + 1)
    check("the equip box clears OAM exactly once", len(hits), 1)
    if len(hits) != 1:
        return

    #  At the head of opt_showbox, not somewhere that merely looks alike: the
    #  routine opens by saving text_ptr, which the shop keeps its own pointer in.
    follows = chunk[hits[0] + len(gate): hits[0] + len(gate) + 2]
    check("it sits at the top of opt_showbox, before text_ptr is saved",
          follows, bytes([0xA5, TEXT_PTR]))

    #  And the shop must not be caught by it: it needs no clear, and one would
    #  take the victory poses with it.
    check("the clear is gated, not unconditional",
          chunk[hits[0] + 3], 0xC9)


# --- menu row labels fit the columns the menu draws ------------------------
#  A row stores thirty bytes of label after its two header bytes, and the menu
#  draws OPTROW_LABELW of them.  Padding to thirty therefore proves nothing:
#  FFPAD accepted "House restores HP and MP" and the screen showed "House
#  restores HP and".  The spill is detectable in the data -- a label that runs
#  past the drawn width leaves a glyph in the bytes beyond it, where a short
#  one leaves spaces -- so check every row rather than the one that was noticed.
#
#  src/optmenu.asm has an OPTLABEL macro that fails the assembly instead, which
#  is the better guard; this covers the rows that predate it.
def test_rowlabels():
    STRIDE, LBL, W, COUNT = 32, 2, 22, 66
    at = SYM.get("lut_OptRows")
    check("lut_OptRows is exported for this check", at is not None, True)
    if at is None:
        return
    base = (CHUNK_OPT_BANK & 0x1F) * 0x10000 + at
    #  A value row with a wide readout gives its label fewer columns: the
    #  field starts 1 << shift - 4 columns early.
    shift = (CHUNK_OPT_BANK & 0x1F) * 0x10000 + SYM["lut_ValShift"]
    over = []
    for i in range(COUNT):
        row = ROMDATA[base + i * STRIDE: base + (i + 1) * STRIDE]
        if len(row) < STRIDE:
            break
        width = W
        if row[0] == 2:
            width = W + 4 - (1 << ROMDATA[shift + row[1]])
        spill = row[LBL + width: STRIDE]
        if any(b != 0xFF for b in spill):
            drawn = "".join(_decode(b) or "?" for b in row[LBL:LBL + W])
            lost = "".join(_decode(b) or "?" for b in spill)
            over.append("   row %d draws %r and loses %r" % (i, drawn, lost.rstrip()))
    check("every row label fits the columns the menu draws", len(over), 0)
    fails.extend(over)

    #  And the rows are where they are thought to be, so a pass means something.
    first = ROMDATA[base: base + STRIDE]
    check("the table starts on a blank row", first[0], 3)


# --- the dial value tables draw only what they mean to ----------------------
#  Each scalar row draws a four-byte string from one of five tables.  They were
#  written with the signs as literals -- $E6 for "+", $E0 for "%" -- and $E6 is
#  where the plus glyph used to live.  Moving the glyph left twenty-six entries
#  pointing at whatever art remained, and the elemental dial read "S50": the
#  tile is the "S" of the battle panel's "Stone".
#
#  The source now uses CHR_PLUS and CHR_PCT, and this is the check that holds
#  it: every byte these tables draw must be a digit, a space, or one of those
#  two signs.  A literal left behind falls outside that set as soon as the
#  glyph it names moves, which is exactly when it starts drawing the wrong
#  thing.
def test_dialvalues():
    #  The glyph set FFCHAR maps, and nothing else.  Letters and digits because
    #  some dials read "Off" or "Fast"; the punctuation we actually encode; the
    #  two signs.  Everything above that in the page is battle-UI artwork, which
    #  is what a stale sign literal ends up pointing at -- the rule catches it
    #  not because the byte is unknown but because it is not text.
    TEXT = (set(range(0x80, 0x8A))              # 0-9
            | set(range(0x8A, 0xA4))            # A-Z
            | set(range(0xA4, 0xBE))            # a-z
            | {0xBE, 0xBF, 0xC0, 0xC2, 0xC4, 0xC5}   # ' , . - ! ?
            | {0xE0, 0xFF})                     # CHR_PCT, space
    lo, hi, cnt = (SYM.get("lut_ValTabLo"), SYM.get("lut_ValTabHi"),
                   SYM.get("lut_ValCount"))
    check("the dial value tables are exported", None not in (lo, hi, cnt), True)
    if None in (lo, hi, cnt):
        return
    bank = (CHUNK_OPT_BANK & 0x1F) * 0x10000
    allowed = TEXT | {CHR_PLUS}
    stray, seen = [], 0
    for t in range(21):
        addr = ROMDATA[bank + lo + t] | ROMDATA[bank + hi + t] << 8
        n = ROMDATA[bank + cnt + t]
        STRIDE = 1 << ROMDATA[bank + SYM["lut_ValShift"] + t]
        if not (0x8000 <= addr < 0x10000) or not (0 < n < 64):
            stray.append("   table %d looks wrong: addr $%04X count %d"
                         % (t, addr, n))
            continue
        for i in range(n):
            row = ROMDATA[bank + addr + i * STRIDE:][:STRIDE]
            seen += 1
            for b in row:
                if b not in allowed:
                    stray.append("   table %d entry %d draws $%02X in %r"
                                 % (t, i, b, "".join(_decode(x) or "?" for x in row)))
    check("the 21 tables hold the expected number of entries", seen, 149)
    check("every byte a dial draws is text, not artwork", len(stray), 0)
    fails.extend(stray[:4])


# --- weapon and armour names fit the shop's list box ------------------------
#  The shop's inventory list is box 2, nine columns wide, so seven between the
#  borders -- which is why every weapon and armour name in the cartridge is
#  exactly seven bytes, padded with spaces or ending in an icon tile.  Exactly
#  one is not: the Ribbon is "Ribbon" and two spaces, and the eighth byte draws
#  a blank over the right border.  Only visible when selling armour to someone
#  carrying one, which is why it survived the cartridge -- though not FFR, whose
#  ItemNames.Write calls a FixRibbonSpace() that drops character 7 when it is a
#  space.  The same fix at the same byte, arrived at independently.
#
#  mkrom trims the terminator back by one.  This checks the whole table, since
#  the rule is the table's and not that one item's -- and Phase 3 renames these.
def test_itemnamewidth():
    WIDTH = 7                   # lut_ShopBox_Wd[2] = $09, less two borders
    PTR = 0xB700                # lut_ItemNamePtrTbl, in BANK_ITEMS
    bank = (1 + 0x0A) * 0x10000
    wrong = []
    for item in range(28, 108):             # weapons then armour
        p = bank + PTR + item * 2
        addr = ROMDATA[p] | ROMDATA[p + 1] << 8
        if not (0x8000 <= addr < 0xC000):
            wrong.append("   $%02X has a nonsense pointer $%04X" % (item, addr))
            continue
        at = bank + addr - 0x8000
        end = ROMDATA.find(b"\x00", at)
        if end < 0 or end - at > 16:
            wrong.append("   $%02X is unterminated" % item)
            continue
        n = end - at
        if n != WIDTH:
            text = "".join(_decode(b) or "<%02X>" % b for b in ROMDATA[at:end])
            wrong.append("   $%02X is %d bytes, not %d: %r" % (item, n, WIDTH, text))
    check("every weapon and armour name is as wide as the box", len(wrong), 0)
    fails.extend(wrong[:6])

    #  And the box really is nine wide, so WIDTH above is not folklore.
    dims = SYM.get("lut_ShopBox_Wd")
    if dims is not None:
        at = (1 + 0x0E) * 0x10000 + dims
        check("the shop's list box is nine columns wide", ROMDATA[at + 2], 0x09)


# --- the randomizer ---------------------------------------------------------
#  src/rando.asm against tools/randoref.py, which is the same generator in
#  Python.  Byte-identical output from both is the contract: it is what lets
#  the Python print a world from a battery file and be believed.  Every check
#  below that compares against the reference is paired with one that does not,
#  so the two cannot agree on a mistake unnoticed -- the trap lists are checked
#  against FFR's definitions, the PRNG against Marsaglia's published value,
#  the cache against the cartridge's own tables.
import randoref as R

def source_consts():
    """name -> value for every plain equate in the sources this port reads.

    Parsed rather than copied, so a layout change cannot leave the tests
    checking the old addresses.  Lines this cannot evaluate -- ca65's byte
    operators, strings, macros -- are skipped, not guessed at."""
    env = {}
    files = [os.path.join(ROOT, "game", "Constants.inc"),
             os.path.join(ROOT, "game", "variables.inc"),
             os.path.join(ROOT, "src", "snesmap.inc")]
    for f in files:
        for line in open(f, encoding="latin-1"):
            #  Indented too: variables.inc indents the record offsets (en_*,
            #  btlform_*), and no name is defined two ways across the three.
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+)", line)
            if not m:
                continue
            expr = m.group(2).strip()
            expr = re.sub(r"\$([0-9A-Fa-f]+)", r"0x\1", expr)
            expr = re.sub(r"%([01]+)", r"0b\1", expr)
            expr = expr.replace(".MOD", "%")
            if re.search(r"[.<>^'\"]", expr.replace("<<", "").replace(">>", "")):
                continue
            try:
                env[m.group(1)] = eval(expr, {"__builtins__": {}}, dict(env))
            except Exception:
                pass
    return env


K = source_consts()
RANDO_BANK = 0xA1 + K["CHUNK_RANDO"]
RW_BASE = 0x7E0000                       # bus.wram index 0 is $7E:0000


def rw(name):
    return K[name] - RW_BASE


def setsave(bus, seed, traps, shops=0, chests=0, magic=0, forms=0, zones=0):
    at = K["RANDO_SAVE"] - 0x6000
    bus.sram[at:at + 4] = seed.to_bytes(4, "little")
    bus.sram[K["RANDO_TRAPS"] - 0x6000] = traps
    bus.sram[K["RANDO_SHOPS"] - 0x6000] = shops
    bus.sram[K["RANDO_CHESTS"] - 0x6000] = chests
    bus.sram[K["RANDO_MAGIC"] - 0x6000] = magic
    bus.sram[K["RANDO_FORMS"] - 0x6000] = forms
    bus.sram[K["RANDO_ZONES"] - 0x6000] = zones


_warm = {}          # machine state -> the last case left cold, or the state built


def warm(bus):
    """Make this machine as if the cartridge had already built the world its
    save names -- as on a console, where the first map load builds it and
    everything after only reads it.

    The consumer tests ask hundreds of times of a handful of worlds, and a
    build from cold is a hundred milliseconds of emulation where a read of a
    built cache is half of one: test_rando_chestload was thirty-seven seconds,
    all but a fraction of it the same build 469 times.

    Call it once the save is set and before anything that differs from case to
    case, so the cases of one world share a key.  Each world's cases run cold
    until one of them has built the cache through the consumer's own call to
    ensure, so a consumer that forgot the call still fails.  "The first case"
    would not do: test_rando_oobspell's first is an empty slot, which returns
    before it asks, and with it warm a missing ensure went unnoticed.  After
    that, the machine gets the memory rando_ensure leaves when run on a copy of
    it.  The key is the whole machine, so a case that differs in any byte is
    never handed another's world; it only runs cold.
    """
    if bus.rom is not ROMDATA:
        return
    key = hashlib.blake2b(bytes(bus.wram) + bytes(bus.sram)
                          + repr((sorted(bus.io.items()), bus.mul_a, bus.mul_b)).encode()).digest()
    was = _warm.get(key)
    if not isinstance(was, tuple):
        if was is None or was.wram[rw("RW_TAG")] != K["RW_TAG_VAL"]:
            _warm[key] = bus                    # this case runs cold, and is watched
            return
        b = Bus(ROMDATA)
        b.wram[:], b.sram[:], b.io = bus.wram, bus.sram, dict(bus.io)
        b.mul_a, b.mul_b = bus.mul_a, bus.mul_b
        c = CPU(b)
        c.dbr = 0xA7
        call(c, "rando_ensure", bank=RANDO_BANK)
        was = _warm[key] = (bytes(b.wram), bytes(b.sram), dict(b.io), b.mul_a, b.mul_b)
    bus.wram[:], bus.sram[:], bus.io = was[0], was[1], dict(was[2])
    bus.mul_a, bus.mul_b = was[3], was[4]


def cache_props(bus):
    at = rw("RW_PROPS")
    return bytes(bus.wram[at:at + R.PROPS_SIZE])


#  FFR's lists, from FF1Lib/Formations.cs, written out here independently of
#  randoref.py: A-side is Range(1, 0x72) less WarMECH (86), B-side is
#  Range(128, 0x73) plus IronGol (0xFF).
FFR_ASIDE = set(range(1, 1 + 0x72)) - {86}
FFR_BSIDE = set(range(128, 128 + 0x73)) | {0xFF}
SEEDS = (0, 1, 2, 0x12345678, 0xDEADBEEF, R.STREAM_TRAPS, 0xFFFFFFFF)


def test_rando_prng():
    #  The reference itself, against the value Marsaglia's paper gives.
    check("xorshift32 from 1 is 270369", R.xs32(1), 270369)
    import random
    rnd = random.Random(1)
    states = [1, 0x80000000, 0xFFFFFFFF, 0x0000FFFF, 0xFFFF0000, 0x00010000,
              0x00008000, 0x00000007, 0x0001FFFF]
    states += [rnd.getrandbits(32) or 1 for _ in range(300)]
    bus, cpu = machine()
    at = rw("RW_RNG")
    bad = []
    for x in states:
        bus.wram[at:at + 4] = x.to_bytes(4, "little")
        call(cpu, "rando_xs", bank=RANDO_BANK)
        got = int.from_bytes(bus.wram[at:at + 4], "little")
        if got != R.xs32(x):
            bad.append("   $%08X stepped to $%08X, want $%08X" % (x, got, R.xs32(x)))
    check("rando_xs is xorshift32 on %d states" % len(states), len(bad), 0)
    fails.extend(bad[:4])
    check("rando_xs comes back in emulation mode", cpu.e, True)


def test_rando_traps():
    vanilla = R.rom_props(ROMDATA)
    traps = R.trap_offsets(vanilla)
    randoms = [i for i in range(0, R.PROPS_SIZE, 2)
               if vanilla[i] == 0x0A and vanilla[i + 1] & 0x80]
    check("the cartridge has FFR's 34 trap tiles", len(traps), 34)
    check("...and 15 random-encounter tiles", len(randoms), 15)

    off = None
    for mode in (0, 1, 2, 3, 4, 5, 0xFF):
        seen = set()
        for seed in SEEDS:
            bus, cpu = machine()
            setsave(bus, seed, mode)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            got = cache_props(bus)
            want = R.build_props(ROMDATA, seed, mode)
            name = "traps mode %d seed $%08X" % (mode, seed)
            if got != want:
                diff = [i for i in range(R.PROPS_SIZE) if got[i] != want[i]]
                fails.append("%-46s differs from randoref at %d bytes, first $%03X"
                             % (name, len(diff), diff[0]))
            if mode == 0 and seed == 0:
                off = got
            seen.add(got)

            #  Independent of the reference: what may differ, and what from.
            moved = [i for i in range(R.PROPS_SIZE) if got[i] != vanilla[i]]
            allowed = set(i + 1 for i in traps) | set(i + 1 for i in randoms)
            check(name + ": only formation bytes change",
                  [i for i in moved if i not in allowed], [])
            check(name + ": random tiles read zero",
                  [got[i + 1] for i in randoms], [0] * len(randoms))
            dealt = [got[i + 1] for i in traps]
            if mode in (0, 5, 0xFF):
                check(name + ": traps as the cartridge has them",
                      dealt, [vanilla[i + 1] for i in traps])
            elif mode == 1:
                check(name + ": the same 34 formations",
                      sorted(dealt), sorted(vanilla[i + 1] for i in traps))
            else:
                pool = {2: FFR_ASIDE, 3: FFR_BSIDE, 4: FFR_ASIDE | FFR_BSIDE}[mode]
                check(name + ": every formation from the list",
                      [f for f in dealt if f not in pool], [])
                check(name + ": none dealt twice", len(set(dealt)), len(dealt))
        if mode in (1, 2, 3, 4):
            check("traps mode %d: every seed a different world" % mode,
                  len(seen), len(SEEDS))
        else:
            check("traps mode %d: one world whatever the seed" % mode, len(seen), 1)

    #  Over many seeds, B-sides do turn up in mode 3 (all of them) and both
    #  halves in mode 4; and Shuffle does move things.
    bus, cpu = machine()
    setsave(bus, 0x0BADF00D, 4)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    dealt = [cache_props(bus)[i + 1] for i in traps]
    check("A+B deals some of each side",
          (any(f < 0x80 for f in dealt), any(f >= 0x80 for f in dealt)), (True, True))
    setsave(bus, 0x0BADF00D, 1)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    dealt = [cache_props(bus)[i + 1] for i in traps]
    check("Shuffle moves most traps",
          sum(d != vanilla[i + 1] for d, i in zip(dealt, traps)) > 17, True)


def test_rando_cache():
    tag, blk = rw("RW_TAG"), rw("RW_TAGBLK")
    props = rw("RW_PROPS")
    size = K["RANDO_SAVE_SIZE"]
    save = K["RANDO_SAVE"] - 0x6000

    #  Power-on: WRAM all zero, and a save made before the randomizer existed
    #  is all zero too.  The tag's marker byte is what stops those two zeros
    #  matching -- without it the cache would be taken as built and every map
    #  would load a table of zeros.
    bus, cpu = machine()
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    check("power-on: tag set", bus.wram[tag], K["RW_TAG_VAL"])
    check("power-on: built, not taken from zeroed WRAM",
          cache_props(bus), R.build_props(ROMDATA, 0, 0))

    #  A matching tag is trusted: nothing is rebuilt, which is what makes the
    #  per-map check cheap.  A poke in the cache survives to prove it.
    setsave(bus, 0x12345678, 3)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    bus.wram[props + 0x101] ^= 0xFF
    poked = cache_props(bus)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    check("matching tag: not rebuilt", cache_props(bus), poked)
    check("the tag holds the save block",
          bytes(bus.wram[blk:blk + size]), bytes(bus.sram[save:save + size]))

    #  A different seed, then a different mode: each one a rebuild.
    for seed, mode in ((0x12345679, 3), (0x12345679, 1)):
        setsave(bus, seed, mode)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        check("seed $%08X mode %d: rebuilt" % (seed, mode),
              cache_props(bus), R.build_props(ROMDATA, seed, mode))

    #  ...and every byte of the block counts, the last one too: a tag that
    #  stopped short of one would keep the old world when only it changed.
    setsave(bus, 0x12345679, 1, 1)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    check("the shops byte alone: rebuilt",
          shop_cache(bus), R.build_shops(ROMDATA, 0x12345679, 1))
    for i in range(size):
        bus.sram[save + i] ^= 0x01
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        check("save byte %d alone: the tag follows it" % i,
              bytes(bus.wram[blk:blk + size]), bytes(bus.sram[save:save + size]))

    #  The build depends on the save and nothing else: scratch full of junk --
    #  which WRAM never holds after hal_reset, but a bug elsewhere could leave
    #  -- must not change the world.  Everything but the tag, from the PRNG's
    #  state to the end of the chest table.
    for seed in (0x31415926, 1082):
        bus2, cpu2 = machine()
        lo, hi = rw("RW_RNG"), rw("RW_BONUS") + 80
        bus2.wram[lo:hi] = b"\xFF" * (hi - lo)
        setsave(bus2, seed, 4, 1, 1, 1)
        bus2.sram[K["RANDO_BLESS"] - 0x6000] = 5
        bus2.sram[K["RANDO_CURSE"] - 0x6000] = 5
        call(cpu2, "rando_ensure", bank=RANDO_BANK)
        check("seed $%08X over junk: the reference's world" % seed,
              (cache_props(bus2), shop_cache(bus2), chest_cache(bus2), magic_cache(bus2),
               gear_cache(bus2)),
              (R.build_props(ROMDATA, seed, 4), R.build_shops(ROMDATA, seed, 1),
               R.build_chests(ROMDATA, seed, 1), R.build_magic(seed, 1),
               R.build_gear(ROMDATA, seed, 5, 5)))

    #  A reset in the middle of a rebuild must leave the cache invalid, not
    #  finished: clear the tag first, write it last.
    setsave(bus, 0xCAFEF00D, 4)
    cpu2 = CPU(bus)
    cpu2.dbr = 0xA7
    try:
        cpu2.run(RANDO_BANK, SYM["rando_ensure"], limit=3000)
        check("the build is long enough to interrupt", "finished", "interrupted")
    except RuntimeError:
        pass
    check("interrupted build: tag reads invalid",
          bus.wram[tag] == K["RW_TAG_VAL"], False)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    check("...and the next ensure finishes it",
          cache_props(bus), R.build_props(ROMDATA, 0xCAFEF00D, 4))


def test_rando_mapload():
    """The hook in place: LoadSMTilesetData, start to finish.

    rando_tileprop has to leave tmp and tmp+2 zero and tmp+3 one page past
    tileset_data, or the TSA copies after it land in the wrong place.  Running
    the routine whole checks that against the code that relies on it, rather
    than against a list of post-conditions written down here."""
    bank0 = 0x10000                      # NES bank $00's image, at $8000
    TSA, ATTR = 0x9000, 0x8400
    for t in range(8):
        bus, cpu = machine()
        setsave(bus, 0x600DCAFE, 3)
        bus.wram[K["cur_tileset"]] = t
        bus.wram[K["cur_tileset"] + 1] = 0xFF        # not ours to read
        bus.wram[K["cur_map"]] = 0
        bus.wram[K["tmp"]:K["tmp"] + 4] = b"\xAA\xBB\xCC\xDD"
        call(cpu, "LoadSMTilesetData")
        ts = K["tileset_data"]
        want = R.build_props(ROMDATA, 0x600DCAFE, 3)[t * 256:(t + 1) * 256]
        check("tileset %d: properties from the cache" % t,
              bytes(bus.wram[ts:ts + 256]), want)
        tsa = ROMDATA[bank0 + TSA + t * 0x200 - 0x8000:][:0x200]
        check("tileset %d: TSA where Copy256 puts it" % t,
              bytes(bus.wram[ts + 0x100:ts + 0x300]), tsa)
        attr = ROMDATA[bank0 + ATTR + t * 0x80 - 0x8000:][:0x80]
        check("tileset %d: attributes" % t,
              bytes(bus.wram[ts + 0x300:ts + 0x380]), attr)


def test_rando_battle():
    """SMMove_Battle tests the formation byte with BNE now: zero is random,
    and anything else, $80 up included, is a fixed fight."""
    TP_BATTLEMARKER = K["TP_BATTLEMARKER"]
    for f in (0x01, 0x46, 0x80, 0x85, 0xFF):
        bus, cpu = machine()
        bus.wram[K["tileprop"]] = K["TP_SPEC_BATTLE"]
        bus.wram[K["tileprop"] + 1] = f
        call(cpu, "SMMove_Battle")
        check("formation $%02X: fought" % f, bus.wram[K["btlformation"]], f)
        check("formation $%02X: battle marked" % f,
              bus.wram[K["tileprop"]], TP_BATTLEMARKER)
        check("formation $%02X: may move" % f, cpu.p & C, 0)
    #  Zero: a random encounter, so at rate zero nothing happens.
    bus, cpu = machine()
    bus.wram[K["tileprop"]] = K["TP_SPEC_BATTLE"]
    bus.wram[K["tileprop"] + 1] = 0
    bus.wram[K["battlerate"]] = 0
    bus.wram[K["btlformation"]] = 0x77
    call(cpu, "SMMove_Battle")
    check("formation 0 at rate 0: no fight", bus.wram[K["btlformation"]], 0x77)
    check("formation 0 at rate 0: no marker",
          bus.wram[K["tileprop"]], K["TP_SPEC_BATTLE"])


def test_rando_newgame():
    pool = K["RANDO_POOL"] - 0x6000
    ng = K["OPT_NG"] - 0x6000
    save = K["RANDO_SAVE"] - 0x6000
    bus, cpu = machine()
    bus.sram[pool:pool + 4] = (0xDEADBEEF).to_bytes(4, "little")
    bus.sram[K["OPT_NG_TRAPS"] - 0x6000] = 3
    bus.sram[K["OPT_NG_SHOPS"] - 0x6000] = 1
    bus.sram[K["OPT_NG_CHESTS"] - 0x6000] = 1
    bus.sram[K["OPT_NG_MAGIC"] - 0x6000] = 1
    cpu.x = 0x42
    call(cpu, "rando_newgame", bank=RANDO_BANK)
    check("new game: the seed is the pool", bytes(bus.sram[save:save + 4]),
          (0xDEADBEEF).to_bytes(4, "little"))
    check("new game: the trap row copied", bus.sram[K["RANDO_TRAPS"] - 0x6000], 3)
    check("new game: the shops row copied", bus.sram[K["RANDO_SHOPS"] - 0x6000], 1)
    check("new game: the chests row copied", bus.sram[K["RANDO_CHESTS"] - 0x6000], 1)
    check("new game: the magic row copied", bus.sram[K["RANDO_MAGIC"] - 0x6000], 1)
    check("new game: X kept", cpu.x, 0x42)
    #  rando_talk's table from now on, and none of its NPCs has given -- even
    #  when the save in SRAM before was a game whose NPCs had.
    bus, cpu = machine()
    bus.sram[K["RANDO_GIVEN"] - 0x6000] = 0xFF
    bus.sram[K["RANDO_GIVEN"] - 0x6000 + 1] = 0x1F
    call(cpu, "rando_newgame", bank=RANDO_BANK)
    check("new game: the reward NPCs run from the table",
          bus.sram[K["RANDO_TALK"] - 0x6000], 1)
    check("new game: no reward NPC has given",
          bytes(bus.sram[K["RANDO_GIVEN"] - 0x6000:][:2]), b"\0\0")

    #  ...and the hook is wired: opt_freestuff is what New Game calls.
    bus, cpu = machine()
    bus.sram[pool:pool + 4] = (0x0F1E2D3C).to_bytes(4, "little")
    bus.sram[K["OPT_NG_TRAPS"] - 0x6000] = 2
    bus.sram[K["OPT_NG_SHOPS"] - 0x6000] = 1
    bus.sram[K["OPT_NG_CHESTS"] - 0x6000] = 1
    bus.sram[K["OPT_NG_MAGIC"] - 0x6000] = 1
    bus.sram[K["OPT_NG_BLESS"] - 0x6000] = 4
    bus.sram[K["OPT_NG_CURSE"] - 0x6000] = 3
    call(cpu, "opt_freestuff")
    check("opt_freestuff seeds the save", bytes(bus.sram[save:save + 10]),
          (0x0F1E2D3C).to_bytes(4, "little") + b"\x02\x01\x01\x01\x04\x03")


def test_rando_stir():
    pool = K["RANDO_POOL"] - 0x6000
    bus, cpu = machine()
    bus.sram[pool:pool + 4] = (0x13579BDF).to_bytes(4, "little")
    bus.io[0x4218], bus.io[0x4219] = 0x80, 0x01
    cpu.a, cpu.x, cpu.y, cpu.dbr = 0xBEEF, 0x12, 0x34, 0xA7
    p = cpu.p
    call(cpu, "rando_stir", bank=RANDO_BANK)
    got = int.from_bytes(bus.sram[pool:pool + 4], "little")
    check("stir: pool steps with the pad folded in",
          got, R.xs32(0x13579BDF ^ 0x0180))
    check("stir: registers kept", (cpu.a, cpu.x, cpu.y, cpu.dbr, cpu.p, cpu.e),
          (0xBEEF, 0x12, 0x34, 0xA7, p, True))

    #  Wired into the per-frame hook.
    bus.sram[pool:pool + 4] = (0x2468ACE0).to_bytes(4, "little")
    bus.io[0x4218] = bus.io[0x4219] = 0
    call(cpu, "opt_padreset")
    got = int.from_bytes(bus.sram[pool:pool + 4], "little")
    check("opt_padreset stirs once a frame", got, R.xs32(0x2468ACE0))


def test_rando_options():
    ng = K["OPT_NG"] - OPTBLOCK
    #  Presets randomize nothing.
    bus, cpu = machine()
    setblk(bus, ng, 4)
    call(cpu, "opt_init")
    check("a fresh cart has the trap row off", blk(bus, ng), 0)

    #  The checksum covers the new-game rows.
    bus, cpu = machine()
    call(cpu, "opt_init")
    setblk(bus, OPT_PRESET, 3)
    setblk(bus, ng, 2)
    call(cpu, "opt_commit")
    call(cpu, "opt_init")
    check("a sealed trap setting survives boot", blk(bus, ng), 2)
    setblk(bus, ng, 1)
    call(cpu, "opt_init")
    check("an unsealed one does not", blk(bus, ng), 0)

    #  The value rows find their bytes through lut_ValOff.
    at = (CHUNK_OPT_BANK & 0x1F) * 0x10000 + SYM["lut_ValOff"]
    check("lut_ValOff: the five dials, the new-game rows, Thief hit, items",
          list(ROMDATA[at:at + 21]),
          [OPT_GOLDXP, OPT_GOLDXP + 1, OPT_GOLDXP + 2, OPT_GOLDXP + 3,
           OPT_GOLDXP + 4, K["OPT_NG_TRAPS"] - OPTBLOCK,
           K["OPT_NG_SHOPS"] - OPTBLOCK, K["OPT_NG_CHESTS"] - OPTBLOCK,
           K["OPT_NG_MAGIC"] - OPTBLOCK, K["OPT_NG_BLESS"] - OPTBLOCK,
           K["OPT_NG_CURSE"] - OPTBLOCK, K["OPT_NG_FORMS"] - OPTBLOCK,
           K["OPT_NG_ZONES"] - OPTBLOCK, K["OPT_NG_NORUN"] - OPTBLOCK,
           K["OPT_NG_SURPRISE"] - OPTBLOCK, K["OPT_NG_STATUS"] - OPTBLOCK,
           K["OPT_NG_SCRIPTS"] - OPTBLOCK, K["OPT_NG_SKILLS"] - OPTBLOCK,
           K["OPT_NG_RNG"] - OPTBLOCK, OPT_THIEFHIT, OPT_STARTITEMS])

    #  Every randomization row's first value reads Off -- under the
    #  RANDOMIZATION heading, the randomization off -- so that a Shuffle
    #  stands out (user, 2026-10-09; Vanilla was tried and was a wall of it).
    #  The blessing and the curse read 0, a number in their range.
    img = (CHUNK_OPT_BANK & 0x1F) * 0x10000
    lo, hi = img + SYM["lut_ValTabLo"], img + SYM["lut_ValTabHi"]
    shift = img + SYM["lut_ValShift"]
    first = []
    for v in range(5, 19):
        at = img + (ROMDATA[lo + v] | ROMDATA[hi + v] << 8)
        first.append("".join(_decode(b) or "?" for b in ROMDATA[at:at + (1 << ROMDATA[shift + v])]).strip())
    check("every randomization row starts at Off", first,
          ["Off"] * 4 + ["0", "0"] + ["Off"] * 8)

    #  Driving the row itself, through the menu's own adjuster: right steps
    #  it up to the last mode and stops; left steps it down to Off and stops.
    SEL, TOP = 0x6E, 0x6F
    bus, cpu = machine()
    in_vblank(bus)                       # these rows redraw their description
    call(cpu, "opt_init")
    for row, byte, presses, want in (
            (optrow("Trap tiles"), K["OPT_NG_TRAPS"], 6, [1, 2, 3, 4, 4, 4, 3, 2, 1, 0, 0, 0]),
            (optrow("Shops"), K["OPT_NG_SHOPS"], 3, [1, 1, 1, 0, 0, 0]),
            (optrow("Formation rarity"), K["OPT_NG_FORMS"], 4, [1, 2, 2, 2, 1, 0, 0, 0]),
            (optrow("Formation zones"), K["OPT_NG_ZONES"], 5, [1, 2, 3, 3, 3, 2, 1, 0, 0, 0]),
            (optrow("Unrunnable fights"), K["OPT_NG_NORUN"], 3, [1, 1, 1, 0, 0, 0]),
            (optrow("Surprise rates"), K["OPT_NG_SURPRISE"], 3, [1, 1, 1, 0, 0, 0]),
            (optrow("Status attacks"), K["OPT_NG_STATUS"], 3, [1, 1, 1, 0, 0, 0]),
            (optrow("Enemy skills"), K["OPT_NG_SKILLS"], 5, [1, 2, 3, 3, 3, 2, 1, 0, 0, 0]),
            (optrow("RNG tables"), K["OPT_NG_RNG"], 3, [1, 1, 1, 0, 0, 0]),
            #  Not a randomization row, but the same adjuster: Thief hit,
            #  from Improved's Moderate up to Double and down to the +2.
            (optrow("Thief and Ninja hit%"), OPTBLOCK + OPT_THIEFHIT, 3, [2, 2, 2, 1, 0, 0]),
            #  ...and the starting items, from None to Duckling Boon and back.
            (optrow("Starting items"), OPTBLOCK + OPT_STARTITEMS, 9,
             [1, 2, 3, 4, 5, 6, 7, 8, 8, 7, 6, 5, 4, 3, 2, 1, 0, 0])):
        steps = []
        for d in (1,) * presses + (2,) * presses:   # RIGHT, then LEFT
            bus.wram[SEL], bus.wram[TOP] = row, row - 19
            cpu.a = d
            call(cpu, "opt_value_adjust", dbr=CHUNK_OPT_BANK)
            steps.append(bus.sram[byte - 0x6000])
        check("row %d steps and clamps" % row, steps, want)
    #  The key item rows are fields packed into bytes.  Each steps through its
    #  own values and clamps there, and leaves the rest of its byte alone: the
    #  byte starts with every other bit set, which a whole-byte step, a wrong
    #  shift or a wrong mask would disturb.
    for name, byte, shift, width, count in (
            ("Key items", "OPT_NG_KEYITEMS", 0, 8, 3),
            ("SHIP", "OPT_NG_ITEMS", 0, 2, 3),
            ("CHIME", "OPT_NG_ITEMS", 4, 2, 3),          # ITEMROW_CHIME 6: byte 1, bits 4-5
            ("ROD", "OPT_NG_ITEMS", 4, 2, 3),            # ITEMROW_ROD 10: byte 2, bits 4-5
            ("Other items", "OPT_NG_ITEMS", 6, 2, 2),    # byte 2, bits 6-7, two values
            ("Masmune", "OPT_NG_GEAR", 0, 1, 2),
            ("Ribbon", "OPT_NG_GEAR", 7, 1, 2),
            ("Xcalber", "OPT_NG_GEAR", 0, 1, 2),         # the second gear byte
            ("Early Ordeals", "OPT_NG_EARLY", 3, 1, 2)):
        at = K[byte] - 0x6000 + {"CHIME": 1, "ROD": 2, "Other items": 2, "Xcalber": 1}.get(name, 0)
        mask = ((1 << width) - 1) << shift if width < 8 else 0xFF
        row = optrow(name)
        bus, cpu = machine()
        in_vblank(bus)
        call(cpu, "opt_init")
        bus.sram[at] = 0xFF & ~mask
        steps, rest = [], set()
        for d in (1,) * count + (2,) * count:
            bus.wram[SEL], bus.wram[TOP] = row, row - 19
            cpu.a = d
            call(cpu, "opt_value_adjust", dbr=CHUNK_OPT_BANK)
            steps.append((bus.sram[at] & mask) >> shift)
            rest.add(bus.sram[at] & ~mask & 0xFF)
        want = list(range(1, count)) + [count - 1] + list(range(count - 2, -1, -1)) + [0]
        check("%s steps and clamps in its field" % name, steps, want)
        check("...and leaves the rest of its byte", rest, {0xFF & ~mask})

    #  ...and each reads its own field and no other's, in the settings and in
    #  the save the view reads.  The fields are placed from snesmap.inc's
    #  layout -- the one the randomizer reads -- not from the menu's tables,
    #  and one at a time: two rows aliasing one field would read each other.
    spec = {22: ("OPT_NG_KEYITEMS", 0, 0, 3)}
    for k in range(12):
        spec[23 + k] = ("OPT_NG_ITEMS", k // 4, 2 * (k % 4), 3 if k < 11 else 2)
    for g in range(9):
        spec[35 + g] = ("OPT_NG_GEAR", g // 8, g % 8, 2)
    for e in range(4):
        spec[44 + e] = ("OPT_NG_EARLY", 0, e, 2)
    view_at = 0x6400 - 0x6000 + (K["RANDO_SAVE"] - 0x6000) + K["RANDO_NGOFF"]
    ng0 = K["OPT_NG"] - 0x6000
    bad = []
    for view, start in ((0, ng0), (1, view_at)):
        for s, (name, plus, shift, count) in spec.items():
            vbus, vcpu = machine()
            vbus.sram[OPTBLOCK - 0x6000 + 0x31] = view         # OPTMENU_VIEW
            vbus.sram[K[name] - K["OPT_NG"] + start + plus] = (count - 1) << shift
            for u in spec:
                vcpu.x = u
                call(vcpu, "opt_menu_valbyte", dbr=CHUNK_OPT_BANK)
                if (vcpu.a & 0xFF) != (count - 1 if u == s else 0):
                    bad.append((view, s, u, vcpu.a & 0xFF))
    check("each key item row reads its own field alone", bad[:4], [])

    ngat = K["OPT_NG"] - 0x6000
    check("...and leaves the block sealed", blk(bus, OPT_CKSUM),
          (sum(bus.sram[OPTBLOCK - 0x6000:][:OPT_SIZE - 1])
           + sum(bus.sram[ngat:ngat + K["OPT_NG_SIZE"]])) & 0xFF ^ 0xFF)


def test_savever():
    """SaveGame seeds its checksum with SAVEVER and VerifyChecksum expects
    SAVEK.  Run the game's own two loops, with the operands patched to each
    version in turn: a save verifies under its own version and no other.

    The save's last byte is kept zero, because the game's checksum only works
    when it is -- see randomization-notes.md section 1.5."""
    import random
    rnd = random.Random(5)
    sv, vc = SYM["SaveGame"], SYM["VerifyChecksum"]
    b0e = 1 + 0x0E
    fixed = 0xA7 & 0x1F
    rom = bytearray(ROMDATA)
    #  The operands, found by instruction rather than by offset.
    chk = K["sram_checksum"]
    i = bytes(rom[b0e * 0x10000 + sv:][:64]).find(bytes([0xA9, K["SAVEVER"], 0x8D, chk & 0xFF, chk >> 8]))
    j = bytes(rom[fixed * 0x10000 + vc:][:32]).find(bytes([0xC9, K["SAVEK"]]))
    check("SaveGame's version operand is SAVEVER", i >= 0, True)
    check("VerifyChecksum's operand is SAVEK", j >= 0, True)
    if i < 0 or j < 0:
        return
    vop = b0e * 0x10000 + sv + i + 1
    kop = fixed * 0x10000 + vc + j + 1

    def savek(v):
        return 0xFF - (2 * v) % 255

    def run(v_save, v_verify, image):
        rom[vop], rom[kop] = v_save, savek(v_verify)
        bus = Bus(bytes(rom))
        cpu = CPU(bus)
        bus.sram[0:0x400] = image
        cpu.dbr = BANK_0E
        cpu.run(BANK_0E, sv)
        cpu.dbr = 0xA7
        cpu.run(0xA7, vc)
        return not (cpu.p & C), bus

    for v in (0, 1, 2, 3, 0x10, 0x7F, 0x80, 0xAA, 0xFE):
        for n in range(3):
            image = bytearray(rnd.getrandbits(8) for _ in range(0x400))
            image[0x3FF] = 0
            ok, bus = run(v, v, image)
            check("version $%02X save %d: verifies" % (v, n), ok, True)
            other = (v + 1) % 0xFF
            check("version $%02X save %d: fails as $%02X" % (v, n, other),
                  run(v, other, image)[0], False)
    #  snesmap.inc's SAVEK has only ever been evaluated at the SAVEVER it is
    #  built with, where any formula gives $FF.  Evaluate its text at every
    #  version, against the constant the loops above just accepted.
    text = None
    for line in open(os.path.join(ROOT, "src", "snesmap.inc")):
        m = re.match(r"^SAVEK\s*=\s*([^;]+)", line)
        if m:
            text = m.group(1).strip().replace("$", "0x").replace(".MOD", "%")
    check("snesmap.inc defines SAVEK", text is not None, True)
    if text:
        wrong = [v for v in range(1, 0xFF)
                 if eval(text, {"__builtins__": {}}, {"SAVEVER": v}) != savek(v)]
        check("SAVEK in snesmap.inc is right at every version", wrong, [])

    image = bytearray(rnd.getrandbits(8) for _ in range(0x400))
    image[0x3FF] = 0
    ok, bus = run(K["SAVEVER"], K["SAVEVER"], image)
    bus.sram[0x400 + 0x123] ^= 0x10
    cpu = CPU(bus)
    cpu.dbr = 0xA7
    cpu.run(0xA7, vc)
    check("a corrupted save still fails", bool(cpu.p & C), True)


# --- shop shuffle -----------------------------------------------------------
#  The vanilla shop lists, read here straight from lut_ShopData rather than
#  through randoref, so the invariants below do not lean on the reference.
def vanilla_shops():
    base = (1 + 0x0E) * 0x10000
    ptr = lambda s: ROMDATA[base + 0x8300 + 2 * s] | ROMDATA[base + 0x8301 + 2 * s] << 8
    five = {s: bytes(ROMDATA[base + ptr(s):][:5]) for s in range(71)}
    used = {s for s in range(71) if ptr(s) != ptr(0)}
    return five, used


def shop_cache(bus):
    at = rw("RW_SHOPS")
    return bytes(bus.wram[at:at + 71 * 8])


def as_list(row):
    out = []
    for b in row[:5]:
        if b == 0:
            break
        out.append(b)
    return out


def test_rando_shops():
    five, used = vanilla_shops()
    types = {"weapon": range(1, 11), "armor": range(11, 21), "item": range(61, 71)}
    dealt = {s for t in types.values() for s in t if s in used}
    check("the cartridge's shops: 6 weapon, 6 armor, 7 item",
          [len([s for s in t if s in used]) for t in types.values()], [6, 6, 7])
    check("...the Caravan among the item shops, selling the BOTTLE",
          (70 in used, as_list(five[70])), (True, [0x0F]))

    for mode in (0, 1, 2, 0xFF):
        seen = set()
        for seed in SEEDS:
            bus, cpu = machine()
            setsave(bus, seed, 0, mode)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            got = shop_cache(bus)
            name = "shops mode %d seed $%08X" % (mode, seed)
            check(name + ": as randoref deals it", got, R.build_shops(ROMDATA, seed, mode))
            seen.add(got)
            rows = {s: got[s * 8:s * 8 + 8] for s in range(71)}
            check(name + ": bytes 5-7 zero",
                  [s for s in rows if rows[s][5:] != b"\0\0\0"], [])
            if mode != 1:
                check(name + ": every row as the game copied it",
                      [s for s in rows if rows[s][:5] != five[s]], [])
                continue
            #  Shuffled: the shops it does not deal are the game's, and the ones
            #  it does are FFR's rules.
            check(name + ": magic, inns, clinics untouched",
                  [s for s in rows if s not in dealt and rows[s][:5] != five[s]], [])
            for kind, ids in types.items():
                mine = [s for s in ids if s in used]
                lists = {s: as_list(rows[s]) for s in mine}
                check("%s %s: the same entries" % (name, kind),
                      sorted(x for l in lists.values() for x in l),
                      sorted(x for s in mine for x in as_list(five[s])))
                check("%s %s: one to five each" % (name, kind),
                      [s for s in mine if not 1 <= len(lists[s]) <= 5], [])
                check("%s %s: none twice in a shop" % (name, kind),
                      [s for s in mine if len(set(lists[s])) != len(lists[s])], [])
                check("%s %s: zero past the list" % (name, kind),
                      [s for s in mine if rows[s][len(lists[s]):5] != bytes(5 - len(lists[s]))], [])
        check("shops mode %d: %s" % (mode, "every seed its own" if mode == 1 else "one world"),
              len(seen), len(SEEDS) if mode == 1 else 1)

    #  The restart: an entry that fits no shop starts its type over.  About
    #  one item deal in 750 does, so the seeds above never reach it; these
    #  three do, once each, on the item shops.
    for seed in (1082, 1168, 1734):
        tries = []
        want = R.build_shops(ROMDATA, seed, 1, tries)
        check("seed %d restarts the item deal" % seed, tries, [1, 1, 2])
        bus, cpu = machine()
        setsave(bus, seed, 0, 1)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        check("seed %d: the restarted deal as randoref's" % seed, shop_cache(bus), want)

    #  Each feature draws from its own stream: turning one on must not move
    #  anything the other made.
    for seed in SEEDS[:4]:
        tables = {}
        for traps, shops in ((3, 0), (3, 1), (0, 1)):
            bus, cpu = machine()
            setsave(bus, seed, traps, shops)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            tables[traps, shops] = (cache_props(bus), shop_cache(bus))
        check("seed $%08X: shops leave the traps alone" % seed,
              tables[3, 0][0], tables[3, 1][0])
        check("seed $%08X: traps leave the shops alone" % seed,
              tables[0, 1][1], tables[3, 1][1])


def test_rando_shopload():
    """LoadShopInventory in place: what reaches item_box."""
    five, used = vanilla_shops()
    ib = K["item_box"]
    for mode, seed in ((0, 0x600DCAFE), (1, 0x600DCAFE), (1, 7)):
        want = R.build_shops(ROMDATA, seed, mode)
        bad = []
        for s in range(1, 71):
            bus, cpu = machine()
            setsave(bus, seed, 0, mode)
            warm(bus)
            bus.wram[K["shop_id"]] = s
            bus.wram[K["shop_id"] + 1] = 0xFF        # not ours to read
            bus.wram[ib:ib + 8] = b"\xEE" * 8
            cpu.dbr = BANK_0E
            cpu.run(BANK_0E, SYM["LoadShopInventory"])
            box = bytes(bus.wram[ib:ib + 6])
            expect = (five[s] if mode == 0 else want[s * 8:s * 8 + 5]) + b"\0"
            if box != expect:
                bad.append("   shop %d: %s, want %s" % (s, box.hex(), expect.hex()))
            if bus.wram[ib + 6] != 0xEE:
                bad.append("   shop %d: wrote past the terminator" % s)
            if cpu.dbr != BANK_0E:
                bad.append("   shop %d: came back with DBR $%02X" % (s, cpu.dbr))
        check("mode %d seed $%08X: item_box for all 70 shops" % (mode, seed), len(bad), 0)
        fails.extend(bad[:4])


def test_rando_caravan():
    """OWCanMove on the Caravan's tile: shut once the fairy is out, unless
    the save's shops are shuffled (FFR's PermanentCaravan)."""
    TILE = 0x36
    for shops, fairy, opened in ((0, 0, True), (0, 1, False),
                                 (1, 0, True), (1, 1, True), (0xFF, 1, False)):
        bus, cpu = machine()
        setsave(bus, 0, 0, shops)
        bus.wram[K["ow_scroll_x"]] = bus.wram[K["ow_scroll_y"]] = 0
        bus.sram[K["mapdata"] - 0x6000 + 0x0700 + 8] = TILE   # right of the party
        bus.wram[K["tileset_data"] + TILE * 2] = K["OWTP_SPEC_CARAVAN"]
        bus.wram[K["tileset_data"] + TILE * 2 + 1] = 0
        bus.wram[K["vehicle"]] = 1
        bus.wram[K["entering_shop"]] = 0
        bus.sram[K["game_flags"] - 0x6000 + K["OBJID_FAIRY"]] = fairy
        cpu.a = K["RIGHT"]
        call(cpu, "OWCanMove")
        got = (bus.wram[K["entering_shop"]] != 0,
               bus.wram[K["shop_id"]] if bus.wram[K["entering_shop"]] else None)
        check("shops %d, fairy %s: Caravan %s" % (shops, "out" if fairy else "in",
                                                    "open" if opened else "shut"),
              got, (True, 70) if opened else (False, None))


# --- descriptions that follow the value -------------------------------------
#  The NEW GAME rows describe the setting they hold, not every setting they
#  could hold.  This reads the pane back out of the raw nametable, so it checks
#  what is drawn rather than which pointer was taken.
def in_vblank(bus):
    """Make hal_waitvbl return at once: in vblank (HVBJOY bit 7), its latch
    unread (RDNMI bit 7), and early enough in it to flush (OPVCT between 224
    and LATE_FLUSH_LAST).  The harness does not model time, so a routine
    that waits a frame -- opt_menu_breathe -- needs this to get past it."""
    bus.io[K["HVBJOY"]] = 0x80
    bus.io[K["RDNMI"]] = 0x80
    bus.io[K["OPVCT"]] = 230


def pane(bus):
    at = K["NESNT"] - 0x7E0000 + (21 + 2) * 32 + 2     # OPTDESC_Y + 2, col 2
    lines = []
    for r in range(5):
        row = bus.wram[at + r * 32:at + r * 32 + 28]
        lines.append("".join(_decode(b) or "?" for b in row).rstrip())
    return [l for l in lines if l]


def optrow(label):
    """The row of lut_OptRows that carries this label.  Tests find rows this
    way rather than by number, which every row added above them changed."""
    base = (CHUNK_OPT_BANK & 0x1F) * 0x10000 + SYM["lut_OptRows"]
    for r in range(128):
        raw = ROMDATA[base + r * 32 + 2:][:22]
        if "".join(_decode(b) or "?" for b in raw).strip() == label:
            return r
    raise KeyError(label)


def test_menudesc():
    SEL, TOP = 0x6E, 0x6F
    TRAPS, SHOPS = optrow("Trap tiles"), optrow("Shops")
    CHESTS, MAGIC = optrow("Chests"), optrow("Magic levels")
    #  A phrase only that value's text has: A and B share their first line.
    cases = [(TRAPS, K["OPT_NG_TRAPS"], v, phrase) for v, phrase in enumerate((
                 "fight it always has", "trap tiles trade",
                 "formation's A-side", "formation's B-side",
                 "A-side or B-side"))]
    cases += [(SHOPS, K["OPT_NG_SHOPS"], v, phrase) for v, phrase in enumerate((
                 "sells what it always has", "dealt out again"))]
    cases += [(CHESTS, K["OPT_NG_CHESTS"], v, phrase) for v, phrase in enumerate((
                 "holds what it always has", "trade contents"))]
    cases += [(MAGIC, K["OPT_NG_MAGIC"], v, phrase) for v, phrase in enumerate((
                 "level it always is", "trade levels"))]
    cases += [(optrow("Starting items"), OPTBLOCK + OPT_STARTITEMS, v, phrase)
              for v, phrase in enumerate((
                 "starts with no items", "Safety Bit gives", "Beggar's Choice gives",
                 "Just Tents gives", "Explorer Pack gives", "Real Estate gives",
                 "Warrior's Standard gives", "Royal Packmule gives",
                 "Duckling Boon gives"))]
    seen = {}
    for row, byte, value, phrase in cases:
        bus, cpu = machine()
        call(cpu, "opt_init")
        bus.sram[byte - 0x6000] = value
        bus.wram[SEL], bus.wram[TOP] = row, row - 19
        call(cpu, "opt_menu_desc", dbr=CHUNK_OPT_BANK)
        text = pane(bus)
        seen[row, value] = tuple(text)
        check("row %d value %d: its own description" % (row, value),
              phrase in " ".join(text), True)
        check("row %d value %d: the data bank put back" % (row, value),
              cpu.dbr, CHUNK_OPT_BANK)
    check("each trap mode reads differently",
          len({seen[TRAPS, v] for v in range(5)}), 5)

    #  A value out of range takes the first value's text rather than reading
    #  past the table.
    bus, cpu = machine()
    call(cpu, "opt_init")
    bus.sram[K["OPT_NG_TRAPS"] - 0x6000] = 9
    bus.wram[SEL], bus.wram[TOP] = TRAPS, TRAPS - 19
    call(cpu, "opt_menu_desc", dbr=CHUNK_OPT_BANK)
    check("an out-of-range trap value reads as Off", tuple(pane(bus)), seen[TRAPS, 0])

    #  An ordinary row is unchanged: one record whatever its value.
    for row, first in ((1, "Adjustments to the game"), (3, None)):
        bus, cpu = machine()
        call(cpu, "opt_init")
        bus.wram[SEL], bus.wram[TOP] = row, 0
        call(cpu, "opt_menu_desc", dbr=CHUNK_OPT_BANK)
        if first:
            check("row %d: its one description" % row, pane(bus)[:1], [first])
        else:
            gold = pane(bus)
    for step in (0, 5):
        bus, cpu = machine()
        call(cpu, "opt_init")
        setblk(bus, OPT_GOLDXP, step)
        bus.wram[SEL], bus.wram[TOP] = 3, 0
        call(cpu, "opt_menu_desc", dbr=CHUNK_OPT_BANK)
        check("Gold and XP at step %d: the same description" % step, pane(bus), gold)

    #  Changing the value redraws the pane, through the menu's own adjuster.
    bus, cpu = machine()
    in_vblank(bus)
    call(cpu, "opt_init")
    bus.wram[SEL], bus.wram[TOP] = TRAPS, TRAPS - 19
    call(cpu, "opt_menu_desc", dbr=CHUNK_OPT_BANK)
    cpu.a = K["RIGHT"]
    call(cpu, "opt_value_adjust", dbr=CHUNK_OPT_BANK)
    check("right on Trap tiles: the pane follows", tuple(pane(bus)), seen[TRAPS, 1])

    #  ...and the row itself: the label whole, and the eight-wide readout
    #  ending in the same column as a four-wide dial's.
    def screen_row(text):
        nt = K["NESNT"] - 0x7E0000
        for r in range(30):
            #  Columns 2-30: the row's own; the rest is background the
            #  harness never fills.
            line = "".join(_decode(b) or "?" for b in bus.wram[nt + r * 32 + 2:nt + r * 32 + 31])
            if text in line:
                return line
        return ""
    trap = screen_row("Trap tiles")
    check("the Trap tiles row reads label then value",
          " ".join(trap.split()), "Trap tiles Shuffle")
    bus.wram[SEL], bus.wram[TOP] = 3, 0
    cpu.a = K["RIGHT"]
    call(cpu, "opt_value_adjust", dbr=CHUNK_OPT_BANK)
    gold = screen_row("Gold and XP")
    check("the wide readout ends where a dial's does",
          len(trap.rstrip()), len(gold.rstrip()))


# --- chest shuffle ----------------------------------------------------------
def chest_cache(bus):
    at = rw("RW_CHESTS")
    return bytes(bus.wram[at:at + 256])


def test_rando_chests():
    vanilla = bytes(ROMDATA[0x10000 + 0xB100:0x10000 + 0xB200])
    #  Which chests may move, worked out here rather than taken from randoref:
    #  the ids some standard map places, less those holding a key item.  The
    #  maps are decoded the way worldgraph does it.
    keys = [c for c in range(256) if 0 < vanilla[c] < 0x16]
    check("seven chests hold key items", len(keys), 7)
    moving = [c for c in R.moving_chests(vanilla)]
    check("234 chests move", len(moving), 234)
    check("...none of them a key item's",
          [c for c in moving if c in keys], [])

    for mode in (0, 1, 2, 0xFF):
        seen = set()
        for seed in SEEDS:
            bus, cpu = machine()
            setsave(bus, seed, 0, 0, mode)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            got = chest_cache(bus)
            name = "chests mode %d seed $%08X" % (mode, seed)
            check(name + ": as randoref deals it", got, R.build_chests(ROMDATA, seed, mode))
            seen.add(got)
            if mode != 1:
                check(name + ": as the cartridge has them", got, vanilla)
                continue
            check(name + ": the key items where they were",
                  [got[c] for c in keys], [vanilla[c] for c in keys])
            check(name + ": the rest of the chests untouched",
                  [c for c in range(256) if c not in moving and got[c] != vanilla[c]], [])
            check(name + ": the same contents, moved",
                  sorted(got[c] for c in moving), sorted(vanilla[c] for c in moving))
            check(name + ": most of them moved",
                  sum(got[c] != vanilla[c] for c in moving) > 150, True)
        check("chests mode %d: %s" % (mode, "every seed its own" if mode == 1 else "one world"),
              len(seen), len(SEEDS) if mode == 1 else 1)

    #  Independent streams: chests on or off leaves the others alone, and the
    #  others leave the chests alone.
    for seed in SEEDS[:3]:
        a, b = machine(), machine()
        setsave(a[0], seed, 3, 1, 0)
        setsave(b[0], seed, 3, 1, 1)
        call(a[1], "rando_ensure", bank=RANDO_BANK)
        call(b[1], "rando_ensure", bank=RANDO_BANK)
        check("seed $%08X: chests leave traps and shops alone" % seed,
              (cache_props(a[0]), shop_cache(a[0])), (cache_props(b[0]), shop_cache(b[0])))
        c = machine()
        setsave(c[0], seed, 0, 0, 1)
        call(c[1], "rando_ensure", bank=RANDO_BANK)
        check("seed $%08X: traps and shops leave the chests alone" % seed,
              chest_cache(b[0]), chest_cache(c[0]))


def test_rando_chestload():
    """OpenTreasureChest in place: what the chest gives is the cache's."""
    seed = 0x600DCAFE
    for mode in (0, 1):
        want = R.build_chests(ROMDATA, seed, mode)
        bad = []
        for c in R.moving_chests(ROMDATA[0x10000 + 0xB100:0x10000 + 0xB200]):
            bus, cpu = machine()
            setsave(bus, seed, 0, 0, mode)
            warm(bus)
            bus.wram[K["tileprop"] + 1] = c
            bus.wram[K["dlgsfx"]] = 0
            call(cpu, "OpenTreasureChest")
            if bus.wram[K["dlg_itemid"]] != want[c]:
                bad.append("   chest $%02X gave $%02X, want $%02X"
                           % (c, bus.wram[K["dlg_itemid"]], want[c]))
            elif not bus.sram[K["game_flags"] - 0x6000 + c] & K["GMFLG_TCOPEN"]:
                bad.append("   chest $%02X was not marked open" % c)
        check("chests mode %d: all 234 give the cache's contents" % mode, len(bad), 0)
        fails.extend(bad[:4])

    #  An item lands in the inventory: the first shuffled chest holding one.
    want = R.build_chests(ROMDATA, seed, 1)
    c = next(c for c in R.moving_chests(ROMDATA[0x10000 + 0xB100:0x10000 + 0xB200])
             if 0x16 <= want[c] < 0x1C)
    bus, cpu = machine()
    setsave(bus, seed, 0, 0, 1)
    warm(bus)
    bus.wram[K["tileprop"] + 1] = c
    call(cpu, "OpenTreasureChest")
    check("chest $%02X: one more of its item" % c,
          bus.sram[K["items"] - 0x6000 + want[c]], 1)


# --- magic levels -----------------------------------------------------------
def magic_cache(bus):
    p, i = rw("RW_PERM"), rw("RW_INV")
    return bytes(bus.wram[p:p + 64]), bytes(bus.wram[i:i + 64])


def jsl_count(image_bank, name, bank=None):
    """How many times the image's 16KB at $8000 (or $C000) holds a JSL to name
    in the randomizer's chunk, or in bank -- the wiring of a patch, found by
    its bytes."""
    a = SYM[name]
    op = bytes([0x22, a & 0xFF, a >> 8, RANDO_BANK if bank is None else bank])
    lo = image_bank * 0x10000 + 0x8000
    return ROMDATA[lo:lo + 0x8000].count(op)


def test_rando_magic():
    white = lambda s: (s & 7) < 4
    for mode in (0, 1, 2, 0xFF):
        seen = set()
        for seed in SEEDS:
            bus, cpu = machine()
            setsave(bus, seed, 0, 0, 0, mode)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            perm, inv = magic_cache(bus)
            name = "magic mode %d seed $%08X" % (mode, seed)
            check(name + ": as randoref deals it", (perm, inv), R.build_magic(seed, mode))
            check(name + ": a permutation", sorted(perm), list(range(64)))
            check(name + ": the inverse", [inv[perm[s]] for s in range(64)], list(range(64)))
            check(name + ": white stays white",
                  [s for s in range(64) if white(s) != white(perm[s])], [])
            if mode != 1:
                check(name + ": every spell in its own slot", list(perm), list(range(64)))
            seen.add(perm)
        check("magic mode %d: %s" % (mode, "every seed its own" if mode == 1 else "one world"),
              len(seen), len(SEEDS) if mode == 1 else 1)

    #  Its own stream: magic on or off leaves the other three alone, and they
    #  leave it alone.
    for seed in SEEDS[:3]:
        a, b, c = machine(), machine(), machine()
        setsave(a[0], seed, 3, 1, 1, 0)
        setsave(b[0], seed, 3, 1, 1, 1)
        setsave(c[0], seed, 0, 0, 0, 1)
        for m in (a, b, c):
            call(m[1], "rando_ensure", bank=RANDO_BANK)
        check("seed $%08X: magic leaves the others alone" % seed,
              (cache_props(a[0]), shop_cache(a[0]), chest_cache(a[0])),
              (cache_props(b[0]), shop_cache(b[0]), chest_cache(b[0])))
        check("seed $%08X: the others leave magic alone" % seed,
              magic_cache(b[0]), magic_cache(c[0]))


def test_rando_spellconv():
    """The battle's spell list, in place: ConvertOBStatsToIB turns each slot
    into its spell, and ConvertIBStatsToOB turns it back."""
    import random
    rnd = random.Random(9)
    sp = K["ch_magicdata"] - 0x6000
    for seed, mode in ((0x600DCAFE, 1), (0x600DCAFE, 0), (77, 1)):
        perm, _ = R.build_magic(seed, mode)
        bus, cpu = machine()
        setsave(bus, seed, 0, 0, 0, mode)
        ob = bytearray(4 * 0x40)
        for c in range(4):
            for level in range(8):
                for k in range(3):                 # the 4th byte of a level is padding
                    ob[c * 0x40 + level * 4 + k] = rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 8])
        bus.sram[sp:sp + 0x100] = ob
        before = bytes(bus.sram[0x100:0x400])
        cpu.dbr = 0xA1 + 0x0B
        cpu.run(0xA1 + 0x0B, SYM["ConvertOBStatsToIB"])
        want, got = [], []
        for c in range(4):
            for level in range(8):
                for k in range(4):
                    v = ob[c * 0x40 + level * 4 + k]
                    want.append(perm[level * 8 + v - 1] + 1 if v else 0)
                    got.append(bus.sram[sp + c * 0x40 + level * 4 + k])
        name = "seed $%08X mode %d" % (seed, mode)
        check(name + ": in battle, each slot is its spell", got, want)
        cpu.dbr = 0xA1 + 0x0B
        cpu.run(0xA1 + 0x0B, SYM["ConvertIBStatsToOB"])
        check(name + ": and back again, exactly", bytes(bus.sram[0x100:0x400]), before)


def test_rando_oobspell():
    """The out-of-battle dispatch: the slot's spell, an 8th spell where the
    game's ORA went wrong, and nothing for an empty slot."""
    sp = K["ch_magicdata"] - 0x6000
    MG = 0xB0
    for seed, mode in ((0x600DCAFE, 1), (0x600DCAFE, 0)):
        perm, _ = R.build_magic(seed, mode)
        bad = []
        for char in range(4):
            for level in range(8):
                for k in range(3):
                    for v in (0, 1, 8):
                        bus, cpu = machine()
                        setsave(bus, seed, 0, 0, 0, mode)
                        warm(bus)
                        x = char * 0x40 + level * 4 + k
                        bus.sram[sp + x] = v
                        cpu.x = x
                        cpu.a = x
                        call(cpu, "rando_oobspell", bank=RANDO_BANK)
                        want = MG + perm[level * 8 + v - 1] if v else 0
                        if cpu.a & 0xFF != want or cpu.x != x:
                            bad.append("   char %d L%d slot %d pos %d: $%02X, want $%02X"
                                       % (char, level + 1, k, v, cpu.a & 0xFF, want))
        check("mode %d: every slot dispatches its spell" % mode, len(bad), 0)
        fails.extend(bad[:4])
    check("the dispatch calls it, once", jsl_count(1 + 0x0E, "rando_oobspell"), 1)


def test_rando_spellnames():
    """The names a slot is drawn under: the magic menu's list, the magic
    shops' list, and the spell descriptions."""
    for seed, mode in ((0x600DCAFE, 1), (0x600DCAFE, 0)):
        perm, _ = R.build_magic(seed, mode)
        bad = []
        for s in range(64):
            level, v = s >> 3, (s & 7) + 1
            bus, cpu = machine()
            setsave(bus, seed, 0, 0, 0, mode)
            warm(bus)
            bus.wram[K["tmp"]] = 0xAF + level * 8
            cpu.a = v
            call(cpu, "rando_menuspell", bank=RANDO_BANK)
            if cpu.a & 0xFF != 0xB0 + perm[s]:
                bad.append("   menu slot %d: $%02X" % (s, cpu.a & 0xFF))
            cpu.a = 0xB0 + s
            call(cpu, "rando_shopspell", bank=RANDO_BANK)
            if cpu.a & 0xFF != 0xB0 + perm[s]:
                bad.append("   shop slot %d: $%02X" % (s, cpu.a & 0xFF))
            setblk(bus, 0, 0)
            cpu.a = 0xB0 + s
            call(cpu, "opt_descgear", dbr=CHUNK_OPT_BANK)
            if bus.sram[K["OPTGEARI"] - 0x6000] != perm[s]:
                bad.append("   description of slot %d: spell %d"
                           % (s, bus.sram[K["OPTGEARI"] - 0x6000]))
        check("mode %d: all 64 slots named and described as their spell" % mode, len(bad), 0)
        fails.extend(bad[:4])
        #  Anything not a spell goes through the shop list untouched.
        for item in (0x01, 0x1C, 0x6B, 0xAF, 0xF0, 0xFF):
            bus, cpu = machine()
            setsave(bus, seed, 0, 0, 0, mode)
            warm(bus)
            cpu.a = item
            call(cpu, "rando_shopspell", bank=RANDO_BANK)
            check("mode %d: item $%02X is not a spell" % (mode, item), cpu.a & 0xFF, item)
    fixed = 0xA7 & 0x1F
    check("the magic menu's list calls it, once", jsl_count(fixed, "rando_menuspell"), 1)
    check("battle start calls it, once", jsl_count(1 + 0x0B, "rando_ibspell"), 1)
    check("battle end calls it, once", jsl_count(1 + 0x0B, "rando_obspell"), 1)


def test_rando_magicshop():
    """A magic shop's list, drawn by the game's own ShopSelectBuyMagic and read
    back off the nametable: each slot under its spell's name, at the slot's
    level, and the slot's item id kept for the price and the purchase."""
    base = (1 + 0x0E) * 0x10000
    ptr = lambda s: ROMDATA[base + 0x8300 + 2 * s] | ROMDATA[base + 0x8301 + 2 * s] << 8
    sb, ib = K["str_buf"], K["item_box"]
    nt = K["NESNT"] - 0x7E0000
    for seed, mode in ((0x0BADF00D, 1), (77, 1), (0x0BADF00D, 0)):
        perm, _ = R.build_magic(seed, mode)
        for shop in (21, 31, 26, 37):            # white and black, low and high
            wares = as_list(ROMDATA[base + ptr(shop):][:5])
            bus, cpu = machine()
            in_vblank(bus)
            call(cpu, "opt_init")
            setsave(bus, seed, 0, 0, 0, mode)
            warm(bus)
            bus.wram[ib:ib + 6] = bytes(wares + [0] * (6 - len(wares)))
            cpu.dbr = BANK_0E
            #  Drawn by the time it first asks for input.  Run on, it would
            #  spin there until the step limit, six times as long as the draw.
            waited = cpu.run(BANK_0E, SYM["ShopSelectBuyMagic"], stop=SYM["UpdateJoy"])
            name = "seed $%08X mode %d shop %d" % (seed, mode, shop)
            check(name + ": the shop draws and waits for the player", waited, True)
            slots = [w - 0xB0 for w in wares]
            check(name + ": the price and purchase keep the slot",
                  [bus.wram[sb + 0x16 + 8 * i] for i in range(len(wares))], wares)
            rows = []
            for r in range(30):
                line = "".join(_decode(b) or " " for b in bus.wram[nt + r * 32:nt + r * 32 + 32]).strip()
                if line:
                    rows.append(line)
            names = [r for r in rows if not r[0].isdigit()]
            levels = [int(r[0]) for r in rows if r[0].isdigit()]
            check(name + ": each slot named for its spell", names,
                  [R.item_name(ROMDATA, 0xB0 + perm[s]) for s in slots])
            check(name + ": at the slot's level", levels, [(s >> 3) + 1 for s in slots])


# --- blursings ----------------------------------------------------------------
def gear_cache(bus):
    t, b = rw("RW_WEAPONS"), rw("RW_BONUS")
    return bytes(bus.wram[t:t + 480]), [x - 256 if x > 127 else x for x in bus.wram[b:b + 80]]


def setgear(bus, seed, bless, curse):
    setsave(bus, seed, 0)
    bus.sram[K["RANDO_BLESS"] - 0x6000] = bless
    bus.sram[K["RANDO_CURSE"] - 0x6000] = curse


GEAR_ROM = (1 + 0x0C) * 0x10000 + 0x8000


def test_rando_gear():
    rom = bytes(ROMDATA[GEAR_ROM:GEAR_ROM + 480])
    for bless, curse in ((0, 0), (5, 5), (3, 0), (0, 2), (1, 1), (6, 0), (0, 9)):
        seen = set()
        for seed in SEEDS:
            bus, cpu = machine()
            setgear(bus, seed, bless, curse)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            table, bonus = gear_cache(bus)
            name = "+%d/-%d seed $%08X" % (bless, curse, seed)
            check(name + ": as randoref blurses", (table, bonus),
                  R.build_gear(ROMDATA, seed, bless, curse))
            live = 0 <= bless < 6 and 0 <= curse < 6 and (bless or curse)
            if not live:
                check(name + ": the cartridge's tables", (table, bonus), (rom, [0] * 80))
                seen.add(table)
                continue
            check(name + ": every bonus in range",
                  [b for b in bonus if not -curse <= b <= bless], [])
            #  Only the fields FFR touches move, and each the way it should.
            bad = []
            for i in range(40):
                w, v, b = rom[i * 8:i * 8 + 8], table[i * 8:i * 8 + 8], bonus[i]
                if w[3:] != v[3:]:
                    bad.append("weapon %d: spell, element, type or look" % i)
                if b and not (v[0] == min(50, max(0, w[0] + 3 * b)) and
                              v[1] == max(1, w[1] + 2 * b) and v[2] == max(1, w[2] + 3 * b)):
                    bad.append("weapon %d: %s from %s at %+d" % (i, list(v[:3]), list(w[:3]), b))
                if not b and w != v:
                    bad.append("weapon %d moved with no bonus" % i)
            for j in range(40):
                a, v, b = rom[320 + j * 4:324 + j * 4], table[320 + j * 4:324 + j * 4], bonus[40 + j]
                k = 2 if j < 16 else 1
                if a[2:] != v[2:]:
                    bad.append("armor %d: resistance or spell" % j)
                if b and not (v[0] == max(0, a[0] - k * b) and v[1] == max(1, a[1] + k * b)):
                    bad.append("armor %d: %s from %s at %+d" % (j, list(v[:2]), list(a[:2]), b))
                if not b and a != v:
                    bad.append("armor %d moved with no bonus" % j)
            check(name + ": FFR's rules, field by field", bad, [])
            seen.add(table)
        if 0 <= bless < 6 and 0 <= curse < 6 and (bless or curse):
            check("+%d/-%d: every seed its own" % (bless, curse), len(seen), len(SEEDS))

    #  Over a wide roll, plain gear still happens: zero is always in range.
    bus, cpu = machine()
    setgear(bus, 0x31337, 5, 5)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    _, bonus = gear_cache(bus)
    check("+5/-5: some gear plain, some blessed, some cursed",
          (0 in bonus, max(bonus) > 0, min(bonus) < 0), (True, True, True))

    #  The options chunk's readers see the same tables.
    bus, cpu = machine()
    setgear(bus, 0x600DCAFE, 4, 2)
    want, _ = R.build_gear(ROMDATA, 0x600DCAFE, 4, 2)
    bad = []
    for i in range(40):
        for y in range(8):
            cpu.x, cpu.y = i, y
            call(cpu, "opt_weapbyte", dbr=CHUNK_OPT_BANK)
            if (cpu.a & 0xFF, cpu.x, cpu.y) != (want[i * 8 + y], i, y):
                bad.append("weapon %d byte %d" % (i, y))
        for y in range(4):
            cpu.x, cpu.y = i, y
            call(cpu, "opt_armbyte", dbr=CHUNK_OPT_BANK)
            if (cpu.a & 0xFF, cpu.x, cpu.y) != (want[320 + i * 4 + y], i, y):
                bad.append("armor %d byte %d" % (i, y))
    check("opt_weapbyte and opt_armbyte read the blursed tables", bad[:4], [])

    #  Its own stream: blursings leave the others alone, and they it.
    for seed in SEEDS[:3]:
        a, b, c = machine(), machine(), machine()
        for m, on, g in ((a, 1, 0), (b, 1, 3), (c, 0, 3)):
            setsave(m[0], seed, 3 if on else 0, on, on, on)
            m[0].sram[K["RANDO_BLESS"] - 0x6000] = g
            m[0].sram[K["RANDO_CURSE"] - 0x6000] = g
            call(m[1], "rando_ensure", bank=RANDO_BANK)
        check("seed $%08X: blursings leave the others alone" % seed,
              (cache_props(a[0]), shop_cache(a[0]), chest_cache(a[0]), magic_cache(a[0])),
              (cache_props(b[0]), shop_cache(b[0]), chest_cache(b[0]), magic_cache(b[0])))
        check("seed $%08X: the others leave blursings alone" % seed,
              gear_cache(b[0]), gear_cache(c[0]))


def test_rando_gearstats():
    """ReadjustEquipStats and UnadjustEquipStats in place: what a blursed piece
    adds to a character is what the blursed table says, against the same run
    with blursings off."""
    seed = 0x600DCAFE
    table, bonus = R.build_gear(ROMDATA, seed, 5, 5)
    rom = bytes(ROMDATA[GEAR_ROM:GEAR_ROM + 480])
    st = lambda f: K[f] - 0x6000
    def run(bless, curse, slot, item, routine):
        bus, cpu = machine()
        setgear(bus, seed, bless, curse)
        warm(bus)
        bus.sram[st("ch_class")] = 0                        # a Fighter
        for f, v in (("ch_dmg", 20), ("ch_hitrate", 20), ("ch_absorb", 20), ("ch_evade", 60)):
            bus.sram[st(f)] = v
        bus.sram[st(slot)] = 0x80 | (item + 1)
        bus.wram[K["equipoffset"]] = K[slot] - K["ch_stats"]
        call(cpu, routine)
        return [bus.sram[st(f)] for f in ("ch_dmg", "ch_hitrate", "ch_absorb", "ch_evade")]
    bad = []
    for i in range(40):
        on, off = run(5, 5, "ch_weapons", i, "ReadjustEquipStats"), run(0, 0, "ch_weapons", i, "ReadjustEquipStats")
        want = [table[i * 8 + 1] - rom[i * 8 + 1], table[i * 8] - rom[i * 8], 0, 0]
        if [a - b for a, b in zip(on, off)] != want:
            bad.append("weapon %d (%+d): %s" % (i, bonus[i], [a - b for a, b in zip(on, off)]))
        on, off = run(5, 5, "ch_armor", i, "ReadjustEquipStats"), run(0, 0, "ch_armor", i, "ReadjustEquipStats")
        a = 320 + i * 4
        want = [0, 0, table[a + 1] - rom[a + 1], -(table[a] - rom[a])]
        if [x - y for x, y in zip(on, off)] != want:
            bad.append("armor %d (%+d): %s" % (i, bonus[40 + i], [x - y for x, y in zip(on, off)]))
        #  ...and taking it off gives back exactly what putting it on gave.
        bus, cpu = machine()
        setgear(bus, seed, 5, 5)
        warm(bus)
        bus.sram[st("ch_weapons")] = 0x80 | (i + 1)
        bus.wram[K["equipoffset"]] = K["ch_weapons"] - K["ch_stats"]
        before = bytes(bus.sram[st("ch_dmg"):st("ch_dmg") + 2])
        call(cpu, "ReadjustEquipStats")
        call(cpu, "UnadjustEquipStats")
        if bytes(bus.sram[st("ch_dmg"):st("ch_dmg") + 2]) != before:
            bad.append("weapon %d: off again is not where it started" % i)
    check("all 80 pieces adjust a character by their blursed stats", bad[:6], [])
    fixed = 0xA7 & 0x1F
    check("both adjusters read weapons through it", jsl_count(fixed, "rando_weaprec"), 2)
    check("...and armor", jsl_count(fixed, "rando_armrec"), 2)


def test_rando_gearnames():
    """The names, three ways the game reaches them: a weapon shop's list drawn
    by ShopSelectBuyItem, battle's BattleDrawLoadSubSrcPtr, and rando_nameptr
    itself for all 80 under several rolls."""
    nt = K["NESNT"] - 0x7E0000
    for seed, bless, curse in ((0x0BADF00D, 5, 5), (0x0BADF00D, 0, 0), (77, 3, 0)):
        _, bonus = R.build_gear(ROMDATA, seed, bless, curse)
        name = "seed $%08X +%d/-%d" % (seed, bless, curse)
        #  rando_nameptr, every piece: the bytes it points at.
        bad = []
        for i in range(80):
            bus, cpu = machine()
            setgear(bus, seed, bless, curse)
            warm(bus)
            cpu.a = 0x1C + i
            cpu.y = 0x5A
            call(cpu, "rando_nameptr", bank=RANDO_BANK)
            p = (cpu.a & 0xFF) | cpu.x << 8
            got = bytes(bus.read(0xA1 + 0x0A, p + k) for k in range(7))
            if got != R.blursed_name_bytes(ROMDATA, 0x1C + i, bonus[i]) or cpu.y != 0x5A:
                bad.append("item $%02X: %s" % (0x1C + i, got.hex()))
        check(name + ": all 80 names", bad[:4], [])
        #  Not gear: the ROM's own pointer, untouched.
        for item in (0x00, 0x19, 0x1B, 0x6C, 0xB0):
            bus, cpu = machine()
            setgear(bus, seed, bless, curse)
            warm(bus)
            cpu.a = item
            call(cpu, "rando_nameptr", bank=RANDO_BANK)
            at = (1 + 0x0A) * 0x10000 + 0xB700 + item * 2
            check(name + ": item $%02X keeps the ROM's name" % item,
                  (cpu.a & 0xFF) | cpu.x << 8, ROMDATA[at] | ROMDATA[at + 1] << 8)
        #  A weapon shop's list, as drawn.
        base = (1 + 0x0E) * 0x10000
        ptr = ROMDATA[base + 0x8300 + 2 * 2] | ROMDATA[base + 0x8301 + 2 * 2] << 8
        wares = as_list(ROMDATA[base + ptr:][:5])          # Pravoka's weapons
        bus, cpu = machine()
        in_vblank(bus)
        call(cpu, "opt_init")
        setgear(bus, seed, bless, curse)
        warm(bus)
        bus.wram[K["item_box"]:K["item_box"] + 6] = bytes(wares + [0] * (6 - len(wares)))
        cpu.dbr = BANK_0E
        waited = cpu.run(BANK_0E, SYM["ShopSelectBuyItem"], stop=SYM["UpdateJoy"])
        check(name + ": Pravoka's weapon shop draws and waits for the player", waited, True)
        drawn = []
        for r in range(30):
            row = bytes(bus.wram[nt + r * 32:nt + r * 32 + 32])
            for item in wares:
                if R.blursed_name_bytes(ROMDATA, item, bonus[item - 0x1C]) in row:
                    drawn.append(item)
        check(name + ": Pravoka's weapons drawn by their blursed names", sorted(drawn), sorted(wares))
        #  Battle: the item-name table through BattleDrawLoadSubSrcPtr, with the
        #  items bank mapped -- and the same address from another bank, untouched.
        for i in (0, 7, 25, 39, 40, 55, 79):
            for dbr, blursed in ((0xA1 + 0x0A, True), (0xA1 + 0x0B, False)):
                bus, cpu = machine()
                setgear(bus, seed, bless, curse)
                warm(bus)
                bus.wram[0x0500:0x0502] = bytes([0, 0x1C + i])
                bus.wram[0x90], bus.wram[0x91] = 0x00, 0x05
                cpu.a, cpu.x, cpu.y, cpu.dbr = 0xB7, 0x00, 0, dbr
                call(cpu, "BattleDrawLoadSubSrcPtr")
                p = bus.wram[K["btldraw_subsrc"]] | bus.wram[K["btldraw_subsrc"] + 1] << 8
                if blursed:
                    got = bytes(bus.read(dbr, p + k) for k in range(7))
                    check(name + ": battle names piece %d" % i, got,
                          R.blursed_name_bytes(ROMDATA, 0x1C + i, bonus[i]))
                else:
                    at = (dbr & 0x1F) * 0x10000 + 0xB700 + (0x1C + i) * 2
                    check(name + ": another bank's table at $B7xx is left alone",
                          p, ROMDATA[at] | ROMDATA[at + 1] << 8)
        #  The equip menu, as DrawEquipMenuStrings draws it from item_box.
        bus, cpu = machine()
        in_vblank(bus)
        call(cpu, "opt_init")
        setgear(bus, seed, bless, curse)
        warm(bus)
        for slot in ("ch_weapons", "ch_armor"):
            first = 0x1C if slot == "ch_weapons" else 0x44
            ids = list(range(1, 17))                       # 16 of them, 4 a character
            bus.wram[K["item_box"]:K["item_box"] + 16] = bytes(ids)
            bus.wram[K["equipoffset"]] = K[slot] - K["ch_stats"]
            bus.wram[nt:nt + 0x800] = bytes(0x800)
            call(cpu, "DrawEquipMenuStrings")
            screen = bytes(bus.wram[nt:nt + 0x800])
            missing = [first + i - 1 for i in ids
                       if R.blursed_name_bytes(ROMDATA, first + i - 1, bonus[first + i - 1 - 0x1C]) not in screen]
            check(name + ": the equip menu's %s, as blursed" % slot[3:], missing, [])
        #  A chest's message, drawn by DrawDialogueBox.
        for item in (0x1C + 3, 0x44 + 1, 0x1C + 39):
            bus, cpu = machine()
            in_vblank(bus)
            call(cpu, "opt_init")
            setgear(bus, seed, bless, curse)
            warm(bus)
            bus.wram[K["dlg_itemid"]] = item
            cpu.a = 0xF0                                   # DLGID_TCGET
            try:
                cpu.run(0xA7, SYM["DrawDialogueBox"], limit=600000)
            except RuntimeError:
                pass
            screen = bytes(bus.wram[nt:nt + 0x800])
            check(name + ": a chest of item $%02X names it as blursed" % item,
                  R.blursed_name_bytes(ROMDATA, item, bonus[item - 0x1C]) in screen, True)
    fixed = 0xA7 & 0x1F
    check("three menu readers ask rando_nameptr", jsl_count(fixed, "rando_nameptr"), 3)
    check("battle asks rando_battlesubsrc", jsl_count(fixed, "rando_battlesubsrc"), 1)


# --- formations ----------------------------------------------------------------
#  lut_Domains read here straight from the image, and the facts the passes
#  must keep stated without randoref, so the reference and the cartridge
#  cannot agree on a mistake unnoticed.
DOMAINS_ROM = (1 + 0x0B) * 0x10000 + 0x8000
START_ZONES = (0x1B, 0x1C, 0x24, 0x2C)
NOT_BOSS = set(range(256)) - set(range(0x73, 0x80)) - set(range(0xF3, 0xFE))
CLASSES = ((0, 4), (4, 2), (6, 1), (7, 1))      # lut_FormationWeight's rarities
LIGHT = ((0, 1), (3, 1), (5, 1), (6, 1))        # two common, an uncommon, a rare
WARMECH_FORM = 0x56


def form_cache(bus):
    at = rw("RW_DOMAINS")
    return bytes(bus.wram[at:at + 1024])


def test_rando_formations():
    vanilla = bytes(ROMDATA[DOMAINS_ROM:DOMAINS_ROM + 1024])
    zone = lambda t, z: t[z * 8:z * 8 + 8]
    zero = [z for z in range(128) if not any(zone(vanilla, z))]
    live = [z for z in range(128) if z not in START_ZONES and z not in zero]
    check("the cartridge has 31 all-zero zones", len(zero), 31)
    check("...one of them $2C, by Coneria", [z for z in START_ZONES if z in zero], [0x2C])
    check("...so the zones pass moves 94", len(live), 94)
    weight = bytes(ROMDATA[(0xA7 & 0x1F) * 0x10000 + SYM["lut_FormationWeight"]:][:64])
    check("lut_FormationWeight's classes are 12, 12, 12, 12, 6, 6, 3, 1",
          [weight.count(k) for k in range(8)], [12, 12, 12, 12, 6, 6, 3, 1])

    mech = [i for i in range(1024) if vanilla[i] == WARMECH_FORM]
    check("WarMECH is in one slot, Sky Palace 5F's 6", mech, [(64 + 51) * 8 + 6])
    ZL, ZS, ZR = K["ZONES_LIGHT"], K["ZONES_SHUFFLE"], K["ZONES_RANDOM"]
    seeds = (0x600DCAFE, 7, 0x0BADF00D, 0xFFFFFFFF)
    seen = {}
    for rarity in range(4):                     # 3 is no mode: as off
        for zones in range(5):                  # and 4
            for seed in seeds:
                bus, cpu = machine()
                setsave(bus, seed, 0, forms=rarity, zones=zones)
                call(cpu, "rando_ensure", bank=RANDO_BANK)
                got = form_cache(bus)
                r, zn = rarity % 3, zones % 4
                name = "rarity %d zones %d seed $%08X" % (rarity, zones, seed)
                check(name + ": the reference's world", got,
                      R.build_domains(ROMDATA, seed, r, zn))
                seen.setdefault((r, zn), set()).add(got)
                if r == 0 and zn == 0:
                    check(name + ": the cartridge's own table", got, vanilla)
                if zn == 0 and r:
                    check(name + ": every zone keeps its own fights",
                          [z for z in range(128) if sorted(zone(got, z)) != sorted(zone(vanilla, z))], [])
                if zn == 0 and r == 1:
                    #  Slots 0-3 shuffled, then 2-7: the commonest two were common.
                    check(name + ": slots 0 and 1 hold what slots 0-3 held",
                          [z for z in range(128) for k in (0, 1)
                           if got[z * 8 + k] not in zone(vanilla, z)[:4]], [])
                if zn in (ZL, ZS) and r == 0:
                    check(name + ": the zones around Coneria and the empty ones stay",
                          [z for z in range(128) if z not in live and zone(got, z) != zone(vanilla, z)], [])
                    for first, count in (LIGHT if zn == ZL else CLASSES):
                        pick = lambda t: sorted(t[z * 8 + k] for z in live
                                                for k in range(first, first + count))
                        check(name + ": slots %d-%d keep their formations between them"
                              % (first, first + count - 1), pick(got), pick(vanilla))
                    if zn == ZL:
                        check(name + ": slots 1, 2, 4 and 7 stay",
                              [i for i in range(1024) if i % 8 in (1, 2, 4, 7) and got[i] != vanilla[i]], [])
                #  Only Random moves WarMECH out of Sky Palace 5F.  Rarity may
                #  move it within the floor, as FFR's does.
                if zn != ZR and r == 0:
                    check(name + ": WarMECH stays", [got[i] for i in mech], [WARMECH_FORM])
                elif zn != ZR:
                    check(name + ": WarMECH stays on Sky Palace 5F",
                          [f for f in got if f == WARMECH_FORM], [WARMECH_FORM])
                    check(name + ": ...in some slot of it", WARMECH_FORM in zone(got, mech[0] // 8), True)
                if zn == ZR:
                    check(name + ": no zone draws a boss",
                          [z for z in range(128) if z not in START_ZONES
                           and not set(zone(got, z)) <= NOT_BOSS], [])
                    if r == 0:
                        check(name + ": the zones around Coneria stay",
                              [zone(got, z) for z in START_ZONES],
                              [zone(vanilla, z) for z in START_ZONES])
    check("every mode pair was seen", len(seen), 12)
    for (r, zn), worlds in sorted(seen.items()):
        check("rarity %d zones %d: four seeds, %s worlds" % (r, zn, "one" if r == zn == 0 else "four"),
              len(worlds), 1 if r == zn == 0 else 4)


def test_rando_formload():
    """GetBattleFormation in place: the slot lut_FormationWeight picks, out of
    the cache's zone, for every zone and every slot, with btlformation holding
    the cartridge's answer as a decoy wherever the world differs.  One machine
    per world, called over and over as the game calls it, so the first call
    builds the cache through the hook's own ensure."""
    fixed = (0xA7 & 0x1F) * 0x10000
    weight = ROMDATA[fixed + SYM["lut_FormationWeight"]:][:64]
    rng = ROMDATA[fixed + SYM["lut_RNG"]:][:256]
    vanilla = bytes(ROMDATA[DOMAINS_ROM:DOMAINS_ROM + 1024])
    #  A battle counter for each slot: the one whose next lut_RNG byte picks it.
    counter = {}
    for bc in range(256):
        counter.setdefault(weight[rng[(bc + 1) & 0xFF] & 0x3F], bc)
    check("every slot is reachable from some battle counter", sorted(counter), list(range(8)))
    for rarity, zones, seed in ((0, 0, 0x600DCAFE), (1, K["ZONES_SHUFFLE"], 0x600DCAFE),
                                (2, K["ZONES_RANDOM"], 77), (0, K["ZONES_LIGHT"], 9)):
        want = R.build_domains(ROMDATA, seed, rarity, zones)
        bad, odd = [], []
        bus, cpu = machine()
        setsave(bus, seed, 0, forms=rarity, zones=zones)
        for z in range(128):
            for slot, bc in sorted(counter.items()):
                bus.wram[K["battlecounter"]] = bc
                decoy = vanilla[z * 8 + slot]
                bus.wram[K["btlformation"]] = decoy if decoy != want[z * 8 + slot] else 0xEE
                cpu.a = z
                call(cpu, "GetBattleFormation")
                if bus.wram[K["btlformation"]] != want[z * 8 + slot]:
                    bad.append("zone $%02X slot %d: $%02X, want $%02X"
                               % (z, slot, bus.wram[K["btlformation"]], want[z * 8 + slot]))
                #  SwapPRG maps a bank by DBR here; cur_bank is the caller's.
                if (bus.wram[K["battlecounter"]] != (bc + 1) & 0xFF or cpu.p & 0x01
                        or cpu.dbr != 0xA1 + K["BANK_DOMAINS"]):
                    odd.append("zone $%02X slot %d" % (z, slot))
        name = "rarity %d zones %d" % (rarity, zones)
        check(name + ": every zone's every slot fights its formation", bad[:3], [])
        check(name + ": the counter steps, carry clears, BANK_DOMAINS is mapped", odd[:3], [])
    fixedimg = 0xA7 & 0x1F
    check("GetBattleFormation asks rando_formation", jsl_count(fixedimg, "rando_formation"), 1)


# --- unrunnable fights and surprise rates ----------------------------------------
FORMS_ROM = (1 + 0x0B) * 0x10000 + 0x8400        # lut_BattleFormations


def runs_cache(bus):
    a, b = rw("RW_NORUN"), rw("RW_SURPRISE")
    return bytes(bus.wram[a:a + 256]), bytes(bus.wram[b:b + 128])


def setruns(bus, seed, runs, surprise):
    setsave(bus, seed, 0)
    bus.sram[K["RANDO_NORUN"] - 0x6000] = runs
    bus.sram[K["RANDO_SURPRISE"] - 0x6000] = surprise


def test_rando_runs():
    rec = lambda f: ROMDATA[FORMS_ROM + f * 16:][:16]
    flag = [rec(f)[0x0D] & 1 for f in range(128)]
    rate = [rec(f)[0x0C] for f in range(128)]
    check("13 of the 115 normal formations cannot be run from", sum(flag[:115]), 13)
    check("...and every fiend, Chaos and the last four", flag[115:], [1] * 13)
    #  FFR's pool, stated here rather than taken from randoref.
    pool = set(range(1, 115)) | set(range(0x80, 0x80 + 115)) | set(range(0xFC, 0x100))
    check("FFR's pool is 233 sides", len(pool), 233)
    vanilla = bytes(flag + flag), bytes(rate)
    seen = {}
    for runs in range(3):                       # 2 is no mode: as off
        for surprise in range(3):
            for seed in (0x600DCAFE, 7, 0x0BADF00D):
                bus, cpu = machine()
                setruns(bus, seed, runs, surprise)
                call(cpu, "rando_ensure", bank=RANDO_BANK)
                norun, rates = runs_cache(bus)
                rn, sp = runs % 2, surprise % 2
                name = "runs %d surprise %d seed $%08X" % (runs, surprise, seed)
                check(name + ": the reference's flags", norun, R.build_runs(ROMDATA, seed, rn))
                check(name + ": the reference's rates", rates, R.build_surprise(ROMDATA, seed, sp))
                seen.setdefault((rn, sp), set()).add((norun, rates))
                if not rn:
                    check(name + ": the cartridge's flags, both sides alike", norun, vanilla[0])
                else:
                    check(name + ": 26 sides of the pool cannot be run from",
                          sum(norun[f] for f in pool), 26)
                    check(name + ": the imps' A-side, the fiends, Chaos and the last four's"
                          " A-sides keep theirs",
                          [f for f in range(256) if f not in pool and norun[f] != vanilla[0][f]], [])
                if not sp:
                    check(name + ": the cartridge's rates", rates, vanilla[1])
                else:
                    check(name + ": the normal formations' rates, among themselves",
                          sorted(rates[:115]), sorted(vanilla[1][:115]))
                    check(name + ": the bosses' rates stay", rates[115:], vanilla[1][115:])
    for (rn, sp), worlds in sorted(seen.items()):
        check("runs %d surprise %d: three seeds, %s worlds" % (rn, sp, "one" if rn == sp == 0 else "three"),
              len(worlds), 1 if rn == sp == 0 else 3)


def test_rando_formdata():
    """EnterBattle's copy, through rando_formdata: every side of every
    formation, with btl_formdata full of junk first.  The record as the ROM
    has it but for the surprise rate and the side's no-run bit, which are the
    cache's.  One machine per world, so the first call builds it."""
    at = K["btl_formdata"] - 0x6000
    for runs, surprise, seed in ((0, 0, 0x600DCAFE), (1, 1, 0x600DCAFE), (1, 0, 9), (0, 1, 9)):
        norun = R.build_runs(ROMDATA, seed, runs)
        rates = R.build_surprise(ROMDATA, seed, surprise)
        bus, cpu = machine()
        setruns(bus, seed, runs, surprise)
        bad = []
        for f in range(256):
            want = bytearray(ROMDATA[FORMS_ROM + (f & 0x7F) * 16:][:16])
            want[0x0C] = rates[f & 0x7F]
            want[0x0D] = (want[0x0D] & 0xFE) | norun[f]
            bus.sram[at:at + 16] = bytes((0xA5 + i) & 0xFF for i in range(16))
            bus.wram[K["btlformation"]] = f
            call(cpu, "rando_formdata", bank=RANDO_BANK)
            if bytes(bus.sram[at:at + 16]) != bytes(want):
                bad.append("$%02X" % f)
        check("runs %d surprise %d: every side's copy" % (runs, surprise), bad[:4], [])
    check("EnterBattle asks rando_formdata", jsl_count(0xA7 & 0x1F, "rando_formdata"), 1)


# --- enemies: touches, scripts, skills & spells -------------------------------------
ENEMIES_ROM = (1 + 0x0C) * 0x10000 + 0x8520     # data_EnemyStats, 20 bytes each
ENEMYAI_ROM = (1 + 0x0C) * 0x10000 + 0x9020     # lut_EnemyAi, 16 bytes each


def enram(bus, e, slot=0):
    """($84) and ($9A) at an enemy's RAM stats in btl_enemystats, holding
    its id, as the battle points them."""
    at = K["btl_enemystats"] + slot * 0x14
    bus.sram[at - 0x6000 + K["en_enemyid"]] = e
    for zp in (0x84, 0x9A):
        bus.wram[zp], bus.wram[zp + 1] = at & 0xFF, at >> 8


def setai(bus, seed, status=0, scripts=0, skills=0):
    setsave(bus, seed, 0)
    bus.sram[K["RANDO_STATUS"] - 0x6000] = status
    bus.sram[K["RANDO_SCRIPTS"] - 0x6000] = scripts
    bus.sram[K["RANDO_SKILLS"] - 0x6000] = skills


def ai_cache(bus):
    t, e, s_ = rw("RW_TOUCH"), rw("RW_ESCRIPT"), rw("RW_SCRIPTS")
    return bytes(bus.wram[t:t + 256]), bytes(bus.wram[e:e + 128]), bytes(bus.wram[s_:s_ + 704])


def test_rando_touch():
    touch = lambda e: bytes(ROMDATA[ENEMIES_ROM + e * 20 + 0x0E:][:2])
    vanilla = b"".join(touch(e) for e in range(128))
    check("16 enemies poison, 16 stun", (sum(1 for e in range(128) if touch(e)[1] == 0x04),
                                        sum(1 for e in range(128) if touch(e)[1] == 0x10)), (16, 16))
    seen = set()
    for status in range(3):                     # 2 is no mode: as off
        for seed in (0x600DCAFE, 7, 0x0BADF00D):
            bus, cpu = machine()
            setai(bus, seed, status)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            got = ai_cache(bus)[0]
            st = status % 2
            name = "status %d seed $%08X" % (status, seed)
            check(name + ": the reference's touches", got, R.build_touch(ROMDATA, seed, st))
            if not st:
                check(name + ": the cartridge's", got, vanilla)
            else:
                pairs = lambda t: sorted(t[2 * e:2 * e + 2] for e in range(128) if e != 15)
                check(name + ": the touches, ailment and element together, among themselves",
                      pairs(got), pairs(vanilla))
                check(name + ": the pirates keep theirs", got[30:32], vanilla[30:32])
                seen.add(got)
    check("three seeds, three shuffles", len(seen), 3)


def test_rando_touchload():
    """OptScaleEnemyAttack as bank $0C calls it, for all 128 enemies: the
    ailment always, and the element under Weapon Stats, are the cache's, with
    the cartridge's in the fields first as a decoy.  And bank $0C's load of
    the ailment from ROM is gone, or it would overwrite the cache's."""
    ail, elem = K["btl_attacker_attackailment"] - 0x6000, K["btl_attacker_element"] - 0x6000
    for status, flagbits, seed in ((0, F_WEAPONSTATS, 1), (1, F_WEAPONSTATS, 0x600DCAFE), (1, 0, 9)):
        want = R.build_touch(ROMDATA, seed, status)
        bus, cpu = machine()
        setai(bus, seed, status)
        for k in range(4):
            setblk(bus, OPT_FLAGS + k, (flagbits >> (8 * k)) & 0xFF)
        bad = []
        for e in range(128):
            rec = ROMDATA[ENEMIES_ROM + e * 20:][:20]
            addr = 0x8520 + e * 20
            bus.wram[0x86], bus.wram[0x87] = addr & 0xFF, addr >> 8
            enram(bus, e)
            bus.sram[ail] = rec[0x0F] if rec[0x0F] != want[2 * e + 1] else 0xEE
            bus.sram[elem] = rec[0x12]
            cpu.a = rec[0x0D]
            call(cpu, "OptScaleEnemyAttack", dbr=0xA1 + 0x0C)
            got = (bus.sram[ail], bus.sram[elem])
            if got != (want[2 * e + 1], want[2 * e] if flagbits else rec[0x12]):
                bad.append("enemy %d: %s" % (e, got))
        check("status %d flags %06X: every enemy's touch" % (status, flagbits), bad[:3], [])
    check("opt_scaleatk asks rando_touch", jsl_count(CHUNK_OPT_BANK & 0x1F, "rando_touch"), 1)
    b0c = (1 + 0x0C) * 0x10000
    check("bank $0C no longer loads the ailment from ROM",
          bytes([0xA0, 0x0F, 0xB1, 0x86]) in ROMDATA[b0c + 0x8000:b0c + 0x10000], False)


def test_rando_ai():
    eai0 = bytes(ROMDATA[ENEMIES_ROM + e * 20 + 7] for e in range(128))
    tab0 = bytes(ROMDATA[ENEMYAI_ROM:ENEMYAI_ROM + 704])
    rec = lambda t, i: t[i * 16:i * 16 + 16]
    normal = list(range(32)) + [33, 43]
    fiends, big = [34, 36, 38, 40], [32, 35, 37, 39, 41, 42]
    check("36 normal enemies have a script", sum(1 for e in range(118) if eai0[e] != 0xFF), 36)
    check("the bosses' scripts", list(eai0[118:]), [32, 34, 35, 36, 37, 38, 39, 40, 41, 42])
    #  FFR's nukes, found the way FFR finds them, from the cartridge's magic.
    md = (0xA1 + 0x0C & 0x1F) * 0x10000 + SYM["lut_MagicData"]
    nukes = [s_ for s_ in range(64) if ROMDATA[md + s_ * 8 + 4] == 1 and ROMDATA[md + s_ * 8 + 3] == 1
             and ROMDATA[md + s_ * 8 + 2] == 0 and ROMDATA[md + s_ * 8 + 1] >= 80]
    check("FFR's nukes are FADE and NUKE", nukes, [57, 60])
    pool = lambda t, grp, lo, n: sorted(x for g in grp for x in rec(t, g)[lo:lo + n] if x != 0xFF)
    chances = lambda t, grp, k: sorted(rec(t, g)[k] for g in grp)
    seen = {}
    for scripts in range(5):                    # 4 is no mode: as off
        for skills in range(5):
            for seed in (0x600DCAFE, 0x0BADF00D):
                bus, cpu = machine()
                setai(bus, seed, 0, scripts, skills)
                call(cpu, "rando_ensure", bank=RANDO_BANK)
                _, eai, tab = ai_cache(bus)
                sc, sk = scripts % 4, skills % 4
                name = "scripts %d skills %d seed $%08X" % (scripts, skills, seed)
                check(name + ": the reference's", (eai, tab), R.build_ai(ROMDATA, seed, sc, sk))
                seen.setdefault((sc, sk), set()).add((eai, tab))
                #  Who has which script.
                check(name + ": normal enemies' ids among themselves, pirates none",
                      (sorted(eai[:118]), eai[15]), (sorted(eai0[:118]), 0xFF))
                if not sc & 1:
                    check(name + ": normal enemies keep theirs", eai[:118], eai0[:118])
                if sc & 2:
                    check(name + ": fiends' among fiends, the rest among the rest",
                          (sorted(eai[e] for e in (119, 121, 123, 125)),
                           sorted(eai[e] for e in (118, 120, 122, 124, 126, 127))),
                          ([34, 36, 38, 40], [32, 35, 37, 39, 41, 42]))
                else:
                    check(name + ": the bosses keep theirs", eai[118:], eai0[118:])
                #  What the scripts hold.
                van = bytearray(tab0)
                if sk & 1:
                    for c in (7, 27):
                        van[c * 16 + 13] = van[c * 16 + 14] = 0xFF
                for grp, bit in ((normal, 1), (fiends, 2), (big, 2)):
                    if not sk & bit:
                        check(name + ": an undealt group is the cartridge's",
                              [rec(tab, g) for g in grp], [rec(tab0, g) for g in grp])
                        continue
                    check(name + ": a group keeps its spells, skills and chances",
                          (pool(tab, grp, 2, 8), pool(tab, grp, 11, 4), chances(tab, grp, 0), chances(tab, grp, 1)),
                          (pool(van, grp, 2, 8), pool(van, grp, 11, 4), chances(van, grp, 0), chances(van, grp, 1)))
                    for g in grp:
                        r = rec(tab, g)
                        sp, kl = r[2:10], r[11:15]
                        bad = ((r[0] == 0) != (sp[0] == 0xFF) or (r[1] == 0) != (kl[0] == 0xFF)
                               or any(a in nukes and b in nukes for a, b in zip(sp, sp[1:]))
                               or any(a == 0x14 and b == 0x14 for a, b in zip(kl, kl[1:]))
                               or (sp[0] in nukes and kl[0] == 0x14)
                               or r[10] != 0xFF or r[15] != 0xFF)
                        if bad:
                            check(name + ": script %d breaks a rule" % g, r.hex(), "")
    check("every mode pair was seen", len(seen), 16)
    for (sc, sk), worlds in sorted(seen.items()):
        check("scripts %d skills %d: two seeds, %s" % (sc, sk, "one world" if sc == sk == 0 else "two"),
              len(worlds), 1 if sc == sk == 0 else 2)


def test_rando_enemyai():
    """Enemy_DoAi's lookup, through rando_enemyai, for every enemy: carry set
    for one without a script, and otherwise the cache's script in the shadow
    and @aiptr at it -- with the shadow full of junk and @aiptr at the ROM
    script first, as decoys."""
    shadow = K["OPTAISHADOW"]
    for scripts, skills, seed in ((0, 0, 1), (3, 3, 0x600DCAFE), (1, 2, 9)):
        eai, tab = R.build_ai(ROMDATA, seed, scripts, skills)
        bus, cpu = machine()
        setai(bus, seed, 0, scripts, skills)
        bad = []
        for e in range(128):
            enram(bus, e, e % 9)
            bus.sram[shadow - 0x6000:shadow - 0x6000 + 16] = bytes(range(0xA0, 0xB0))
            bus.wram[0x9E], bus.wram[0x9F] = 0x20, 0x90
            call(cpu, "rando_enemyai", bank=RANDO_BANK, dbr=0xA1 + 0x0C)
            if eai[e] == 0xFF:
                ok = cpu.p & 0x01 == 1
            else:
                ok = (cpu.p & 0x01 == 0
                      and bus.sram[shadow - 0x6000:shadow - 0x6000 + 16] == tab[eai[e] * 16:eai[e] * 16 + 16]
                      and bus.wram[0x9E] | bus.wram[0x9F] << 8 == shadow)
            if not ok:
                bad.append(e)
        check("scripts %d skills %d: every enemy's script" % (scripts, skills), bad[:4], [])
    check("Enemy_DoAi asks rando_enemyai", jsl_count((0xA1 + 0x0C) & 0x1F, "rando_enemyai"), 1)


def test_rando_aisynth():
    """The deal's rules on scripts made to trip them.  The cartridge's own
    never would: no enemy casts FADE, no script opens with NUKE and NUCLEAR
    both, and every pad byte is already $FF -- so a dropped rule is invisible
    to test_rando_ai.  Here lut_EnemyAi is doctored: NUKEs and FADEs among the
    normal and boss spells, NUCLEARs among the skills, a script that opens
    with both, and pads that are not $FF.  The cartridge's deal must match
    the reference's over it, and no dealt list may break a rule."""
    rom = bytearray(ROMDATA)
    tab = lambda i, k: ENEMYAI_ROM + i * 16 + k
    for i in range(44):
        rom[tab(i, 10)] = rom[tab(i, 15)] = 0x00
    #  Nukes into casting scripts, NUCLEARs into skill users, by position, so
    #  the counts stay within what the buckets hold.
    casters = [i for i in range(44) if rom[tab(i, 0)] and rom[tab(i, 2)] != 0xFF]
    users = [i for i in range(44) if rom[tab(i, 1)] and rom[tab(i, 11)] != 0xFF]
    for n, i in enumerate(casters[::2]):        # half: enough to collide, not to
        rom[tab(i, 2)] = 60 if n % 2 else 57    # reroll for ever
    for i in users[::3]:
        rom[tab(i, 11)] = 0x14
    rom = bytes(rom)
    check("the doctored table has nukes in every group, and NUCLEARs",
          (len(casters[::2]) > 6, len(users[::3]) > 6), (True, True))
    nukes = (57, 60)
    seen = 0
    for skills in (1, 2, 3):
        for seed in (0x600DCAFE, 7, 0x0BADF00D, 0x31415926):
            bus, cpu = machine()
            bus.rom = rom
            setai(bus, seed, 0, 0, skills)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            _, eai, got = ai_cache(bus)
            name = "doctored, skills %d seed $%08X" % (skills, seed)
            check(name + ": the reference's", got, R.build_ai(rom, seed, 0, skills)[1])
            for i in range(44):
                r = got[i * 16:i * 16 + 16]
                if r == rom[ENEMYAI_ROM + i * 16:][:16]:
                    continue                    # a group not dealt
                seen += 1
                sp, kl = r[2:10], r[11:15]
                bad = (any(a in nukes and b in nukes for a, b in zip(sp, sp[1:]))
                       or any(a == 0x14 and b == 0x14 for a, b in zip(kl, kl[1:]))
                       or (sp[0] in nukes and kl[0] == 0x14) or r[10] != 0xFF or r[15] != 0xFF)
                if bad:
                    check(name + ": script %d breaks a rule" % i, r.hex(), "")
    check("the doctored deals were checked", seen > 100, True)

    #  The opening rule bites rarely, so find a seed where it changes the deal
    #  -- the reference with the rule dropped disagrees with itself -- and hold
    #  the cartridge to the reference there.
    seed = next((x for x in range(400) if R.build_ai(rom, x, 0, 3)
                 != R.build_ai(rom, x, 0, 3, opening=False)), None)
    check("some seed's deal turns on the NUKE-and-NUCLEAR opening", seed is not None, True)
    if seed is not None:
        bus, cpu = machine()
        bus.rom = rom
        setai(bus, seed, 0, 0, 3)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        check("doctored seed %d: the opening rule as the reference has it" % seed,
              ai_cache(bus)[2], R.build_ai(rom, seed, 0, 3)[1])


# --- RNG tables ----------------------------------------------------------------------
def rng_cache(bus):
    e, b = rw("RW_ENCRNG"), rw("RW_BATRNG")
    return bytes(bus.wram[e:e + 256]), bytes(bus.wram[b:b + 256])


def setrng(bus, seed, mode):
    setsave(bus, seed, 0)
    bus.sram[K["RANDO_RNG"] - 0x6000] = mode


def test_rando_rng():
    enc0 = bytes(ROMDATA[(0xA7 & 0x1F) * 0x10000 + SYM["lut_RNG"]:][:256])
    bat0 = bytes(ROMDATA[(CHUNK_OPT_BANK & 0x1F) * 0x10000 + SYM["lut_BattleScramble"]:][:256])
    check("the image's encounter table is the cartridge's file", enc0, open(R.ENCRNG_BIN, "rb").read())
    check("the image's battle table is the cartridge's file", bat0, open(R.BATRNG_BIN, "rb").read())
    check("the battle table's famous gap: two $00s, no $95", (bat0.count(0), 0x95 in bat0), (2, False))
    seen = set()
    for mode in range(3):                       # 2 is no mode: as off
        for seed in (0x600DCAFE, 7, 0x0BADF00D):
            bus, cpu = machine()
            setrng(bus, seed, mode)
            call(cpu, "rando_ensure", bank=RANDO_BANK)
            got = rng_cache(bus)
            name = "RNG %d seed $%08X" % (mode, seed)
            check(name + ": the reference's tables", got, R.build_rng(seed, mode % 2))
            if mode % 2 == 0:
                check(name + ": the cartridge's", got, (enc0, bat0))
            else:
                check(name + ": each table's bytes, among themselves",
                      (sorted(got[0]), sorted(got[1])), (sorted(enc0), sorted(bat0)))
                check(name + ": both moved", (got[0] != enc0, got[1] != bat0), (True, True))
                seen.add(got)
    check("three seeds, three shuffles", len(seen), 3)


# --- Ordeals pillars --------------------------------------------------------
#  FFR's ShuffleOrdeals.  Castle of Ordeals 2F's fifteen pillar pads are
#  dealt tiles -- a pad's tile is where it leads -- from the seed, into the
#  cache, and written over the map as it loads; and teleport $3C, tile $54's,
#  lands where FFR moves it.  The pads, rooms and landing are FFR's, in
#  randoref.py; the checks below hold them to this ROM as well.
def _ordeals_solvable(tiles):
    land = {tile: r for r, (tile, _) in enumerate(R.ORDEALS_ROOMS)}
    seen, todo, out = {0}, [0], False
    while todo:
        r = todo.pop()
        for p in R.ORDEALS_ROOMS[r][1]:
            if tiles[p] == R.ORDEALS_EXIT:
                out = True
            elif tiles[p] not in land:
                return False, 0                 # not a pad tile at all
            elif land[tiles[p]] not in seen:
                seen.add(land[tiles[p]])
                todo.append(land[tiles[p]])
    return out, len(seen)


def test_rando_ordeals():
    W = rw("RW_ORDPADS")
    O2F = K["MAP_ORDEALS2F"]
    base = (0xA1 & 0x1F) * 0x10000
    def prop(tileset, tile):
        o = base + 0x8800 + tileset * 256 + (tile & 0x7F) * 2
        return ROMDATA[o], ROMDATA[o + 1]
    def tele(i):
        return tuple(ROMDATA[base + a + i] for a in (0xAD00, 0xAD40, 0xAD80))

    #  FFR's data against this ROM: the pad tiles are normal teleports into
    #  2F; $55 is the way on; tile $54's is teleport $3C, landing at (14, 20)
    #  until FFR moves it.
    ts = ROMDATA[base + 0xACC0 + O2F]
    kinds = {t: prop(ts, t) for t in range(0x4C, 0x56)}
    check("every pad tile is a normal teleport", {k: v[0] for k, v in kinds.items()},
          {t: 0x80 for t in range(0x4C, 0x56)})
    check("...into 2F", {tele(v[1])[2] for v in kinds.values()}, {O2F})
    check("tile $54 is teleport $3C, landing at (14, 20)",
          (kinds[0x54][1], tele(0x3C)[:2]), (R.ORDEALS_LOST_TELE, (14, 20)))

    def setordeals(bus, seed, mode):
        setsave(bus, seed, 0)
        bus.sram[K["RANDO_ORDEALS"] - 0x6000] = mode

    #  The deal: the reference's, byte for byte, and always a way through
    #  every room.
    wrong, stuck = [], []
    for seed in list(range(1, 40)) + [0x0BADF00D, 0xFFFFFFFF, 0x4F52444C]:
        bus, cpu = machine()
        setordeals(bus, seed, 1)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        got = bytes(bus.wram[W:W + 15])
        if got != R.build_ordeals(seed, 1):
            wrong.append(seed)
        if _ordeals_solvable(got) != (True, 9):
            stuck.append(seed)
    check("the deal is the reference's", wrong, [])
    check("...and every room is on a way through", stuck, [])
    check("the reference's own, two thousand seeds",
          [s for s in range(2000) if _ordeals_solvable(R.build_ordeals(s, 1)) != (True, 9)], [])

    #  The real load of 2F: with the shuffle on, the pads and nothing else
    #  differ from the map as it ships, and they hold the deal.
    def load(seed, mode):
        bus, cpu = machine()
        setordeals(bus, seed, mode)
        bus.wram[0x48] = O2F                    # cur_map
        c = CPU(bus); c.dbr = 0xA7
        c.run(0xA7, SYM["LoadStandardMapAndObjects"])
        return bytes(bus.sram[0x1000:0x2000]), bytes(bus.wram[W:W + 15])
    plain, _ = load(5, 0)
    check("off: the pads as they ship", [plain[y * 64 + x] for x, y in R.ORDEALS_PADS],
          [0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x4F, 0x51, 0x52, 0x4D, 0x53, 0x4C, 0x50, 0x4C, 0x55, 0x54])
    check("an unknown mode: as off", load(5, 2)[0], plain)
    dealt, cache = load(5, 1)
    diff = {(i % 64, i // 64): dealt[i] for i in range(0x1000) if dealt[i] != plain[i]}
    want = {xy: cache[k] for k, xy in enumerate(R.ORDEALS_PADS) if cache[k] != plain[xy[1] * 64 + xy[0]]}
    check("on: only the pads change, to the deal", diff, want)
    check("...which does rewire them", len(want) >= 5, True)
    def other(mode):
        bus, cpu = machine()
        setordeals(bus, 5, mode)
        bus.wram[0x48] = K["MAP_LEFEIN"]
        c = CPU(bus); c.dbr = 0xA7
        c.run(0xA7, SYM["LoadStandardMapAndObjects"])
        return bytes(bus.sram[0x1000:0x2000])
    check("another map, shuffle on: untouched", other(1), other(0))

    #  The lost teleport: FFR's landing with the shuffle on, the table's off,
    #  and no other teleport touched.  X comes back for the map's lookup.
    def dest(mode, t):
        bus, cpu = machine()
        bus.sram[K["RANDO_ORDEALS"] - 0x6000] = mode
        cpu.x = t
        call(cpu, "rando_teledest", bank=RANDO_BANK)
        return bus.wram[0x29], bus.wram[0x2A], cpu.x
    lost = R.ORDEALS_LOST_TELE
    check("teleport $3C, on: FFR's (16, 18)", dest(1, lost), (16 - 7, 18 - 7, lost))
    check("teleport $3C, off: the table's (14, 20)", dest(0, lost), (14 - 7, 20 - 7, lost))
    for i in (0x00, 0x1A, 0x3B, 0x3D):
        x, y, _ = tele(i)
        check("teleport $%02X, on: the table's" % i, dest(1, i), ((x - 7) & 0x3F, (y - 7) & 0x3F, i))

    #  The reference reads a battery file's world from the save block, so
    #  its idea of the block's size has to be the build's.
    check("randoref's save block is the build's size",
          R.RANDO_SAVE_SIZE, K["RANDO_SAVE_SIZE"])
    srm = bytearray(0x8000)
    at = R.SRAM_SAVE - 0x6000 + (K["RANDO_SAVE"] - 0x6000)
    srm[at:at + 4] = (0x0BADF00D).to_bytes(4, "little")
    srm[at + (K["RANDO_ORDEALS"] - K["RANDO_SAVE"])] = 1
    block = R.block_from_srm(bytes(srm))
    #  block[0] is the four-byte seed, so a byte at offset n is block[n - 3].
    check("...and reads Ordeals pillars from a battery file",
          (block[0], block[K["RANDO_ORDEALS"] - K["RANDO_SAVE"] - 3]), (0x0BADF00D, 1))
    check("...whose spoiler finds the way through",
          "way through" in R.ordeals_text(R.build_ordeals(0x0BADF00D, 1)), True)

    #  The wiring.
    tgt = SYM["rando_teledest"]
    jsl = bytes([0x22, tgt & 0xFF, tgt >> 8, RANDO_BANK])
    fixed = ROMDATA[(0xA7 & 0x1F) * 0x10000 + 0xC000:][:0x4000]
    check("@NormalTeleport calls rando_teledest, once", fixed.count(jsl), 1)


def test_rando_rngload():
    """The three readers, in place, with the tables shuffled: BattleStepRNG
    for every battlestep both ways, against the cartridge's own stepping;
    BattleRNG for every state; GetBattleFormation's slot by the cache's
    encounter table.  The first call of all is cold, so BattleStepRNG's
    ensure is what builds the cache."""
    seed = 0x600DCAFE
    enc, bat = R.build_rng(seed, 1)
    bus, cpu = machine()
    setrng(bus, seed, 1)
    step, sign = K["battlestep"], K["battlestep_sign"]
    bad = []
    for sg in (0x00, 0x80, 0x20, 0xE0):
        for bs in range(256):
            bus.wram[step], bus.wram[sign] = bs, sg
            cpu.x = 0x5A
            call(cpu, "BattleStepRNG")
            #  The cartridge's stepping, written out: down if the sign's top
            #  bit is set, up if not, and $A0 onto the sign at zero.
            n = (bs - 1) & 0xFF if sg & 0x80 else (bs + 1) & 0xFF
            s2 = (sg + 0xA0) & 0xFF if n == 0 else sg
            got = (bus.wram[step], bus.wram[sign], cpu.a & 0xFF, cpu.x & 0xFF, bool(cpu.p & 0x02))
            if got != (n, s2, enc[n], n, enc[n] == 0):
                bad.append("step %d sign $%02X: %s" % (bs, sg, got))
    check("BattleStepRNG walks the cache's encounter table", bad[:3], [])
    state = K["btl_rngstate"] - 0x6000
    bad = []
    for k in range(256):
        bus.sram[state] = k
        call(cpu, "BattleRNG_L")
        if (cpu.a & 0xFF, bus.sram[state]) != (bat[k], (k + 1) & 0xFF):
            bad.append(k)
    check("BattleRNG reads the cache's battle table", bad[:4], [])
    fixed = (0xA7 & 0x1F) * 0x10000
    weight = ROMDATA[fixed + SYM["lut_FormationWeight"]:][:64]
    dom = R.build_domains(ROMDATA, seed, 0, 0)
    bad = []
    for bc in range(256):
        bus.wram[K["battlecounter"]] = bc
        cpu.a = 0x24
        call(cpu, "GetBattleFormation")
        if bus.wram[K["btlformation"]] != dom[0x24 * 8 + weight[enc[(bc + 1) & 0xFF] & 0x3F]]:
            bad.append(bc)
    check("GetBattleFormation picks its slot by the cache's table", bad[:4], [])
    check("BattleStepRNG asks rando_steprng", jsl_count(0xA7 & 0x1F, "rando_steprng"), 1)


def test_rando_begin():
    """GameStart's @Begin builds the world before any game code runs -- for
    New Game and Continue alike, which meet there -- and on a second pass,
    as after a soft reset with WRAM intact, only compares the tag.  It
    silences the music before a build, since nothing calls the driver
    during one, and only then: a warm Continue keeps its music.  The code is
    found by its bytes and run alone, from where it sits."""
    fixed = (0xA7 & 0x1F) * 0x10000
    a, e, d = SYM["rando_stale"], SYM["rando_ensure"], SYM["DisableAPU"]
    op = bytes([0x22, a & 0xFF, a >> 8, RANDO_BANK])
    img = ROMDATA[fixed + 0xC000:fixed + 0x10000]
    at = [i for i in range(len(img) - 3) if img[i:i + 4] == op]
    check("the fixed bank asks rando_stale once", len(at), 1)
    if len(at) != 1:
        return
    pc = 0xC000 + at[0]
    scroll = K["unsram_ow_scroll_x"]
    check("...at @Begin: if stale, mute and build, then fetch the overworld scroll",
          bytes(img[at[0] + 4:at[0] + 16]),
          bytes([0x90, 0x07, 0x20, d & 0xFF, d >> 8, 0x22, e & 0xFF, e >> 8, RANDO_BANK,
                 0xAD, scroll & 0xFF, scroll >> 8]))
    end = pc + 13

    def playing(bus):
        bus.wram[APUSHADOW:APUSHADOW + 16] = bytes([0xBF, 0, 0x40, 0x02, 0xBF, 0, 0x60, 0x03,
                                                    0xFF, 0, 0x80, 0x01, 0x3F, 0, 0, 0])
        bus.wram[APUSHADOW + 0x15] = 0x0F

    def apu(bus):
        return (bus.wram[APUSHADOW + 0x15],
                tuple(bus.wram[APUSHADOW + r] for r in (0x00, 0x04, 0x08, 0x0C)))

    bus, cpu = machine()
    seed = 0x600DCAFE
    setsave(bus, seed, 4, 1, 1, 1, 2, 2)
    for k, v in (("RANDO_BLESS", 5), ("RANDO_CURSE", 5), ("RANDO_NORUN", 1), ("RANDO_SURPRISE", 1),
                 ("RANDO_STATUS", 1), ("RANDO_SCRIPTS", 3), ("RANDO_SKILLS", 3), ("RANDO_RNG", 1)):
        bus.sram[K[k] - 0x6000] = v
    playing(bus)
    check("@Begin, stale: reaches rando_ensure", cpu.run(0xA7, pc, stop=e), True)
    check("...the music silenced before it starts",
          (apu(bus), bus.wram[rw("RW_TAG")]), ((0, (0x30, 0x30, 0x30, 0x30)), 0))
    n = 0                               # run on from there: run() would call it afresh
    while (cpu.pbr, cpu.pc) != (0xA7, end) and n < 2_000_000:
        cpu.step()
        n += 1
    check("...and runs on to the next instruction", (cpu.pbr, cpu.pc), (0xA7, end))
    check("...having built the save's world",
          (bus.wram[rw("RW_TAG")] == K["RW_TAG_VAL"], form_cache(bus), rng_cache(bus), ai_cache(bus)[1:]),
          (True, R.build_domains(ROMDATA, seed, 2, 2), R.build_rng(seed, 1), R.build_ai(ROMDATA, seed, 3, 3)))
    #  A soft reset keeps WRAM: the next Continue must cost next to nothing,
    #  and leave the title's music alone.
    playing(bus)
    s0 = cpu.steps
    check("a second pass runs through", cpu.run(0xA7, pc, stop=end), True)
    check("...only comparing the tag (under 300 instructions)", cpu.steps - s0 < 300, True)
    check("...with the music left playing", apu(bus), (0x0F, (0xBF, 0xBF, 0xFF, 0x3F)))

    #  rando_stale on its own: the answer in C, the cache untouched.
    for tag, want in ((K["RW_TAG_VAL"], False), (0, True)):
        bus.wram[rw("RW_TAG")] = tag
        call(cpu, "rando_stale", bank=RANDO_BANK)
        check("rando_stale, tag %02X" % tag, (bool(cpu.p & 1), bus.wram[rw("RW_TAG")], cpu.e),
              (want, tag, True))
    bus.wram[rw("RW_TAG")] = K["RW_TAG_VAL"]
    bus.sram[K["RANDO_RNG"] - 0x6000] ^= 1
    call(cpu, "rando_stale", bank=RANDO_BANK)
    check("rando_stale, the tag right and the save changed", bool(cpu.p & 1), True)


# --- the stack-depth fix ------------------------------------------------------
def test_stackshift():
    """FFR's "Softlock fix": a normal teleport nests another DoStandardMap,
    seven bytes of page 1 that only a warp gives back, so stairs that lead
    back by teleport can be walked round until the stack runs out.  Before
    the pushes, opt_stackshift forgets the oldest level once S is under $80.

    Run as the cartridge runs it: the fixed bank's own @NormalTeleport, from
    its JSL to just before its first call, over a page 1 laid out the way
    the overworld and every teleport before it leave it."""
    FLOOR, OLDEST = 0x80, 0xF5
    fixed = (0xA7 & 0x1F) * 0x10000
    img = bytes(ROMDATA[fixed + 0xC000:fixed + 0x10000])
    a = SYM["opt_stackshift"]
    at = [i for i in range(len(img) - 3) if img[i:i + 4] == bytes([0x22, a & 0xFF, a >> 8, CHUNK_OPT_BANK])]
    check("one normal teleport asks opt_stackshift", len(at), 1)
    if len(at) != 1:
        return
    site = 0xC000 + at[0]
    #  Then the five pushes, as the game wrote them, and its first call.
    zp = [K[n] for n in ("sm_scroll_x", "sm_scroll_y", "inroom", "cur_map", "cur_tileset")]
    pushes = b"".join(bytes([0xA5, z, 0x48]) for z in zp)
    check("...right before its five pushes", img[at[0] + 4:at[0] + 19], pushes)
    stop = site + 19
    check("...and then a call", img[at[0] + 19], 0x20)
    #  The JSR DoStandardMap that makes the frame: the call followed by PLA,
    #  STA cur_tileset.  What it pushes is its own last byte.
    j = img.find(bytes([0x68, 0x85, K["cur_tileset"]]), at[0]) - 3
    check("...the nesting call found", img[j], 0x20)
    ret = 0xC000 + j + 2
    OWRET = [0x12, 0x34, 0x56, 0x78]                    # $01FC-$01FF: the overworld's

    def frame(k):
        """Level k's teleport frame, top byte first: the five pushes, then
        the JSR's return, high byte above low."""
        return [k, 0x40 | k & 0x3F, k & 1, 0x10 + (k & 0x3F), k & 7, ret >> 8, ret & 0xFF]

    def layout(levels, oldest_ret=None):
        """Page 1 as the party leaves it at the given depth: the overworld's
        four bytes, then one frame per teleport taken."""
        page = bytearray(0x100)
        page[0xFC:0x100] = bytes(reversed(OWRET))
        top = 0xFB
        for k in range(1, levels):
            page[top - 6:top + 1] = bytes(reversed(frame(k)))
            top -= 7
        if oldest_ret is not None:
            page[OLDEST], page[OLDEST + 1] = oldest_ret & 0xFF, oldest_ret >> 8
        return page, top

    def teleport(bus, cpu, s):
        cpu.pbr, cpu.pc, cpu.s, cpu.dbr = 0xA7, site, 0x100 | s, 0xA7
        for n in range(200_000):
            if cpu.pc == stop:
                return cpu.s & 0xFF
            cpu.step()
        raise RuntimeError("the teleport ran away at $%02X:%04X" % (cpu.pbr, cpu.pc))

    def frames_from(page, s):
        """The frames between S and the overworld's four bytes, oldest first,
        as each level's first push -- or None if anything there is not a
        teleport frame, so warps would not unwind back to the overworld."""
        if (0xFB - s) % 7 or list(page[0xFC:0x100]) != list(reversed(OWRET)):
            return None
        out = []
        for top in range(0xFB, s, -7):
            f = list(reversed(page[top - 6:top + 1]))
            if f[5:] != [ret >> 8, ret & 0xFF]:
                return None
            out.append(f[0])
        return out

    def run(levels, oldest_ret=None, here=0x5A):
        bus, cpu = machine()
        page, s = layout(levels, oldest_ret)
        bus.wram[0x100:0x200] = page
        for z in zp:
            bus.wram[z] = here
        after = teleport(bus, cpu, s)
        return s, after, bytes(bus.wram[0x100:0x200])

    #  Shallow: S at $84 after seventeen teleports, nothing moves.
    s, after, page = run(18)
    check("17 levels deep, S $%02X: no shift" % s, (s, after), (0x84, 0x84 - 5))
    want, _ = layout(18)
    check("...page 1 as it was, with the five new pushes",
          (page[after + 1:], page[s + 1:]), (bytes([0x5A] * 5) + want[s + 1:], want[s + 1:]))

    #  Deep: S at $7D after eighteen, under $80: the oldest level goes.
    s, after, page = run(19)
    check("18 levels deep, S $%02X: shifted seven, then pushed five" % s, (s, after), (0x7D, 0x7D + 7 - 5))
    shallower, _ = layout(18)
    moved = bytearray(shallower)
    for k in range(2, 19):          # level k's frame, one slot higher
        top = 0xFB - 7 * (k - 2)
        moved[top - 6:top + 1] = bytes(reversed(frame(k)))
    check("...the oldest frame gone, the rest one frame higher, the overworld's untouched",
          page[after + 1 + 5:], bytes(moved[after + 1 + 5:]))
    check("...and every frame still a teleport's, down to the overworld",
          frames_from(page, after + 5), list(range(2, 19)))

    #  A stack this does not recognise is left alone -- off in either byte.
    for bad in (ret ^ 0x0100, ret ^ 0x0001):
        s, after, page = run(19, oldest_ret=bad)
        want, _ = layout(19, bad)
        check("deep, but the oldest frame returns to $%04X, not a teleport: no shift" % bad,
              (after, page[s + 1:]), (s - 5, want[s + 1:]))

    #  Coneria Castle's stairs, walked up and down sixty times.  Each pass
    #  is the real code to its first call; the JSR DoStandardMap that would
    #  follow is done here, pushing what it pushes.
    bus, cpu = machine()
    page, s = layout(1)
    bus.wram[0x100:0x200] = page
    lowest, deepest = s, 0
    for trip in range(60):
        for z in zp:
            bus.wram[z] = trip
        s = teleport(bus, cpu, s)
        bus.wram[0x100 + s], bus.wram[0x100 + s - 1] = ret >> 8, ret & 0xFF
        s -= 2
        lowest = min(lowest, s)
    chain = frames_from(bytearray(bus.wram[0x100:0x200]), s)
    check("sixty trips down Coneria's stairs: never a frame past $80", lowest >= FLOOR - 7, True)
    check("...the stack still unwinds frame by frame to the overworld", chain is not None, True)
    check("...holding the last eighteen levels, the earlier ones forgotten",
          chain, list(range(60 - len(chain or []), 60)) if chain else None)
    check("...eighteen of them", len(chain or []), 18)


# --- the save view ------------------------------------------------------------
def test_saveview():
    """Select on Continue shows the saved game's seed and RANDOMIZATION rows:
    the settings screen held to that section and read-only, its values read
    from the battery copy Continue would load.  The screen is run whole, a
    frame at a time, with the pad pressed as a player would."""
    OPT = CHUNK_OPT_BANK
    OPTLIST_ROWS = 20                    # the window, optmenu.asm
    SEL, TOP, VIEW = 0x6E, 0x6F, OPTBLOCK + 0x31 - 0x6000
    COUNT = int(re.search(r"^OPTROW_COUNT\s*=\s*(\d+)", open(os.path.join(ROOT, "src", "optmenu.inc")).read(),
                          re.M).group(1))
    A_, B_, SELECT, START, UP, DOWN, LEFT, RIGHT = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
    UJ = SYM["UpdateJoy"]
    optimg = (OPT & 0x1F) * 0x10000

    #  The rows, found by reading the table rather than taken from the asm.
    rows = [ROMDATA[optimg + SYM["lut_OptRows"] + i * 32:][:32] for i in range(COUNT)]
    head = next(i for i, r in enumerate(rows) if r[0] == 0 and "RANDOMIZATION" in
                "".join(_decode(b) or "?" for b in r[2:24]))
    first, top = head + 2, head - 1
    #  The section ends the list: its heading, the seed's blank, then the
    #  randomization rows, and the key item rows under a heading of their own.
    check("the section ends the list, its heading and the seed's row first",
          [r[0] for r in rows[head:head + 2]], [0, 3])
    check("...the rest value rows, blanks and one more heading",
          sorted(set(r[0] for r in rows[first:])), [0, 2, 3])
    vrows = [i for i in range(first, COUNT) if rows[i][0] == 2]

    def readout(scalar, step):
        lo = ROMDATA[optimg + SYM["lut_ValTabLo"] + scalar]
        hi = ROMDATA[optimg + SYM["lut_ValTabHi"] + scalar]
        w = 1 << ROMDATA[optimg + SYM["lut_ValShift"] + scalar]
        at = optimg + (lo | hi << 8) + step * w
        return "".join(_decode(b) or "?" for b in ROMDATA[at:at + w])

    def label(i):
        return "".join(_decode(b) or "?" for b in rows[i][2:24])

    def saved(bus, cpu, seed, ng):
        """A save Continue would load, made by the game's own SaveGame."""
        at = K["RANDO_SAVE"] - 0x6000
        bus.sram[at:at + 4] = seed.to_bytes(4, "little")
        bus.sram[at + 4:at + 4 + len(ng)] = bytes(ng)
        cpu.dbr = BANK_0E
        cpu.run(BANK_0E, SYM["SaveGame"])
        cpu.dbr = 0xA7

    def screen(bus, i):
        """List row i as drawn, the window's top being TOP."""
        nt = K["NESNT"] - 0x7E0000 + (1 + i - bus.wram[TOP]) * 32
        return " ".join("".join(_decode(b) or "?" for b in bus.wram[nt + 2:nt + 31]).split())

    def pad(bus, nes):
        bus.io[0x4218] = nes & 0x80
        bus.io[0x4219] = (nes & 0x3F) | (0x80 if nes & 0x40 else 0)

    def frame(bus, cpu, nes):
        """Hold the pad as given for the UpdateJoy the screen is stopped at,
        and run to the next.  False once the screen has returned."""
        pad(bus, nes)
        cpu.step()
        for _ in range(3_000_000):
            if cpu.pc in (UJ, 0xFFFE):
                return cpu.pc == UJ
            cpu.step()
        raise RuntimeError("a frame ran away at $%02X:%04X" % (cpu.pbr, cpu.pc))

    def press(bus, cpu, nes):
        return frame(bus, cpu, nes) and frame(bus, cpu, 0)

    #  --- opt_savevalid: the game's own tests, in its order.
    bus, cpu = machine()
    call(cpu, "opt_savevalid")
    check("no save: not valid", cpu.p & C, C)
    saved(bus, cpu, 1, [0] * K["OPT_NG_SIZE"])
    call(cpu, "opt_savevalid")
    check("a save SaveGame made: valid", cpu.p & C, 0)
    bus.sram[0x450] ^= 1
    call(cpu, "opt_savevalid")
    check("...a byte changed: the checksum fails it", cpu.p & C, C)
    bus.sram[0x450] ^= 1

    #  An assertion byte wrong under a checksum that still passes, so it is the
    #  assertion that fails it: the sum VerifyChecksum makes, and the checksum
    #  byte found that brings it back to SAVEK.
    def vsum(sram):
        a = c = 0
        for x in range(256):
            for page in range(4):
                v = a + sram[0x400 + page * 256 + x] + c
                a, c = v & 0xFF, v >> 8
        return a
    good = bytes(bus.sram[0x400:0x800])
    for name, bad in (("sram_assert_55", 0x56), ("sram_assert_AA", 0xAB)):
        bus.sram[0x400:0x800] = good
        bus.sram[K[name] - 0x6000] = bad
        ck = K["sram_checksum"] - 0x6000
        bus.sram[ck] = next(v for v in range(256)
                            if vsum(bus.sram[:ck] + bytes([v]) + bus.sram[ck + 1:]) == K["SAVEK"])
        call(cpu, "VerifyChecksum")
        sums = not cpu.p & C
        call(cpu, "opt_savevalid")
        check("...%s wrong under a good checksum: not valid" % name, (sums, cpu.p & C), (True, C))

    #  --- the view itself.  Every row a value other than what the settings
    #  hold, so a readout from the wrong place shows.  The key item rows are
    #  fields packed into bytes (lut_ValBit, lut_ValMask), so the save is built
    #  field by field: alternating from row to row, so two rows that alias one
    #  field cannot agree, and the settings a different value in every field.
    def tbl(name, s):
        return ROMDATA[optimg + SYM[name] + s]
    OLD = [3, 1, 1, 1, 4, 2, 2, 1, 1, 1, 1, 3, 2, 1, 1]  # Trap tiles .. Ordeals pillars
    base = K["OPT_NG"] - OPTBLOCK
    step = {}
    ngb, decoy = bytearray(K["OPT_NG_SIZE"]), bytearray(K["OPT_NG_SIZE"])
    for n, i in enumerate(vrows):
        s = rows[i][1]
        count = tbl("lut_ValCount", s)
        step[i] = OLD[n] if n < len(OLD) else n % count
        put = lambda b, v: b.__setitem__(tbl("lut_ValOff", s) - base, b[tbl("lut_ValOff", s) - base]
                                         | (v << tbl("lut_ValBit", s)) & tbl("lut_ValMask", s))
        put(ngb, step[i])
        put(decoy, (step[i] + 1) % count if n >= len(OLD) else 0)
    check("every saved row's field inside the saved block",
          all(0 <= tbl("lut_ValOff", rows[i][1]) - base < K["OPT_NG_SIZE"] for i in vrows), True)
    NG = list(ngb)
    bus, cpu = machine()
    in_vblank(bus)
    call(cpu, "opt_init")
    ngat = K["OPT_NG"] - 0x6000
    bus.sram[ngat:ngat + len(decoy)] = decoy     # the settings: never the save's value
    saved(bus, cpu, 0x0BADF00D, NG)
    kept = lambda: (bytes(bus.sram[0xE00:0xE10]), bytes(bus.sram[0xEC8:0xEC8 + len(NG)]))
    before = kept()
    check("the save view draws and asks for the pad",
          cpu.run(OPT, SYM["opt_saveview"], stop=UJ), True)
    check("...the window: the section, from the blank above its heading",
          (bus.wram[TOP], bus.wram[SEL]), (top, first))
    check("...the heading", screen(bus, head), "SAVED GAME")
    #  The hand: twelve pixels nearer its row than on the settings screen,
    #  since a save view row has no checkbox for it to point at (user).
    check("...the hand, nearer its label", (bus.wram[0x203], bus.wram[0x20B]), (12, 20))
    check("...the seed", screen(bus, head + 1), "Seed 0BADF00D")

    def shown():
        """Each value row in the window, as drawn and as the save has it."""
        rows_in = [i for i in vrows if bus.wram[TOP] <= i < bus.wram[TOP] + OPTLIST_ROWS]
        return ([screen(bus, i) for i in rows_in],
                [" ".join((label(i) + " " + readout(rows[i][1], step[i])).split()) for i in rows_in])
    got, want = shown()
    check("...each row in the window, the save's value", got, want)
    check("...Trap tiles described as saved", "formation's B-side" in " ".join(pane(bus)), True)
    check("...and nothing written", kept(), before)
    check("...the settings are not switched to Custom", bus.sram[K["OPT_PRESET"] - 0x6000],
          before[0][K["OPT_PRESET"] - OPTBLOCK])

    frame(bus, cpu, 0)                          # out of the entry's wait for release
    press(bus, cpu, DOWN)
    check("down: Shops", bus.wram[SEL], first + 1)
    check("...described as saved", "dealt out again" in " ".join(pane(bus)), True)
    shops = screen(bus, first + 1)
    #  One at a time: right then left would step a value and step it back.
    #  (A is masked too, though on a value row the settings ignore it anyway.)
    for name, b in (("right", RIGHT), ("left", LEFT), ("A", A_), ("Select", SELECT)):
        press(bus, cpu, b)
        check("%s changes nothing" % name,
              (bus.wram[SEL], bus.wram[TOP], screen(bus, first + 1), kept()),
              (first + 1, top, shops, before))
    press(bus, cpu, UP)
    press(bus, cpu, UP)
    check("up stops at Trap tiles: the seed and heading are not settings", bus.wram[SEL], first)
    #  Down through the whole section: the cursor rests on value rows only --
    #  not the key item rows' heading or the blanks -- and the window scrolls,
    #  every row it brings in reading its saved value.
    rested = []
    for _ in range(COUNT):
        press(bus, cpu, DOWN)
        rested.append(bus.wram[SEL])
        got, want = shown()
        if got != want:
            check("scrolled to row %d, each row in the window as saved" % bus.wram[SEL], got, want)
            break
    check("down rests on value rows only", sorted(set(rested)), sorted(set(vrows) - {first}))
    check("...and stops at the last, the window scrolled to show it",
          (bus.wram[SEL], bus.wram[TOP]), (COUNT - 1, COUNT - OPTLIST_ROWS))
    check("...the Early flags described as saved", "without the CROWN" in " ".join(pane(bus)), True)
    for _ in range(COUNT):
        press(bus, cpu, UP)
    check("up again to Trap tiles, the window back at the section's top",
          (bus.wram[SEL], bus.wram[TOP]), (first, top))
    check("...the heading drawn again", screen(bus, head), "SAVED GAME")
    check("B leaves", frame(bus, cpu, B_) and frame(bus, cpu, 0), False)
    check("...the view's flag down, and nothing written", (bus.sram[VIEW], kept()), (0, before))

    #  The settings screen, after it, reads the settings again -- even with the
    #  view's flag left up, as a soft reset in the middle of the view leaves it.
    bus.wram[SEL], bus.wram[TOP] = first, top
    call(cpu, "opt_menu_desc", dbr=OPT)
    check("the settings describe their own Trap tiles afterwards",
          "fight it always has" in " ".join(pane(bus)), True)
    bus, cpu = machine()
    in_vblank(bus)
    call(cpu, "opt_init")
    saved(bus, cpu, 0x0BADF00D, NG)
    bus.sram[VIEW] = 1
    cpu.run(OPT, SYM["opt_settings"], stop=UJ)
    check("the settings after a view cut short: the settings' own, editable",
          (bus.sram[VIEW], screen(bus, 1)), (0, " ".join(label(1).split())))

    #  A saved step past its row's count reads as the first, row and pane --
    #  never past the end of the readouts.
    bus, cpu = machine()
    in_vblank(bus)
    call(cpu, "opt_init")
    saved(bus, cpu, 0x0BADF00D, [9] + NG[1:])
    cpu.run(OPT, SYM["opt_saveview"], stop=UJ)
    check("a saved Trap tiles of 9 reads as the first value",
          (screen(bus, first), "fight it always has" in " ".join(pane(bus))),
          (" ".join((label(first) + " " + readout(rows[first][1], 0)).split()), True))

    #  --- opt_titlechoose, with the three screens stubbed to say which ran.
    stubbed = bytearray(ROMDATA)
    MARK = 0x1FF0
    for name, bank, v in (("opt_saveview", OPT, 0x11), ("opt_settings", OPT, 0x22),
                          ("credits_screen", K["CHUNK0"] + K["CHUNK_CREDITS"], 0x33)):
        at = (bank & 0x1F) * 0x10000 + SYM[name]
        stubbed[at:at + 7] = bytes([0xA9, v, 0x8F, MARK & 0xFF, MARK >> 8, 0x7E, 0x6B])

    def title(cur, buttons, save=True, at=None, stop=None):
        bus, cpu = machine()
        bus.rom = stubbed
        if save:
            saved(bus, cpu, 1, [0] * K["OPT_NG_SIZE"])
        bus.wram[K["cursor"]] = cur
        for b, name in ((A_, "joy_a"), (START, "joy_start"), (SELECT, "joy_select")):
            bus.wram[K[name]] = 1 if buttons & b else 0
        cpu.dbr = BANK_0E
        if at is None:
            got = cpu.run(OPT, SYM["opt_titlechoose"])
        else:
            got = cpu.run(BANK_0E, at, stop=stop)
        p = cpu.p
        return dict(shown=bus.wram[MARK], N=bool(p & 0x80), Z=bool(p & 0x02), C=bool(p & C),
                    select=bus.wram[K["joy_select"]], stopped=got)

    def flags(r, *keys):
        return tuple(r[k] for k in keys)

    r = title(0, SELECT)
    check("Select on Continue: the save view, then rebuild",
          flags(r, "shown", "Z", "N", "select"), (0x11, True, False, 0))
    r = title(0, SELECT, save=False)
    check("...with no save: nothing, back to the loop, the press used up",
          flags(r, "shown", "N", "select"), (0, True, 0))
    for cur in (1, 2, 3):
        r = title(cur, SELECT)
        check("Select on row %d: nothing" % cur, flags(r, "shown", "N", "select"), (0, True, 0))
    for cur, b, want in ((0, A_, False), (0, START, False), (1, A_, True), (1, START, True)):
        r = title(cur, b)
        check("row %d, button $%02X: leave, New Game %s" % (cur, b, want),
              flags(r, "shown", "N", "Z", "C"), (0, False, False, want))
    check("A on the mode row: the settings, then rebuild",
          flags(title(2, A_), "shown", "Z", "N"), (0x22, True, False))
    check("A on Credits: the credits, then rebuild",
          flags(title(3, START), "shown", "Z", "N"), (0x33, True, False))
    check("A with Select on Continue: Continue",
          flags(title(0, A_ | SELECT), "shown", "N", "Z", "C"), (0, False, False, False))

    #  --- the call site in bank $0E, run from where it sits.
    img0e = (BANK_0E & 0x1F) * 0x10000
    a = SYM["opt_titlechoose"]
    site = bytes(ROMDATA[img0e + 0x8000:img0e + 0xC000]).find(bytes([0x22, a & 0xFF, a >> 8, OPT]))
    check("the title screen asks opt_titlechoose once",
          jsl_count((BANK_0E & 0x1F), "opt_titlechoose", OPT), 1)
    if site >= 0:
        site += 0x8000
        #  Its loop's top: the first JSR ClearOAM in the title screen.
        co, ets = SYM["ClearOAM"], SYM["EnterTitleScreen"]
        body = bytes(ROMDATA[img0e + ets:img0e + site])
        loop = ets + body.find(bytes([0x20, co & 0xFF, co >> 8]))
        check("...and the loop is found", ets < loop < site, True)
        check("Select off Continue: back into the loop",
              title(1, SELECT, at=site, stop=loop)["stopped"], True)
        check("Select on Continue: the title screen from the top",
              title(0, SELECT, at=site, stop=ets)["stopped"], True)
        for cur in (0, 1):
            r = title(cur, A_, at=site, stop=ets)
            check("A on row %d: out of the title screen, New Game %s" % (cur, bool(cur)),
                  flags(r, "stopped", "C"), (None, bool(cur)))

    #  ...and the loop hears Select: TitleScreen_Music answers it with A.
    for a_, sel, want in ((0, 0, 0), (1, 0, 1), (0, 1, 1)):
        bus, cpu = machine()
        bus.wram[K["joy_a"]], bus.wram[K["joy_select"]] = a_, sel
        bus.wram[K["cur_bank"]] = 0x0E
        cpu.dbr = BANK_0E
        cpu.run(BANK_0E, SYM["TitleScreen_Music"])
        check("TitleScreen_Music, A %d Select %d" % (a_, sel), cpu.a & 0xFF, want)


# --- None, a party slot left empty ------------------------------------------------
def test_nones():
    """None: party creation offers it for slots 2-4, and every place the class
    byte would index past a table, or something could raise the dead, does the
    right thing with it.  Each check is run on the routine itself, with a None
    beside an ordinary class so the guard is seen to bite."""
    NONE, OPT = K["CLS_NONE"], CHUNK_OPT_BANK
    page = lambda e: K["ch_stats"] - 0x6000 + e * 0x40       # a character, in SRAM
    img0e, img0c, fixed = (0xA1 + 0x0E) & 0x1F, (0xA1 + 0x0C) & 0x1F, 0xA7 & 0x1F

    def party(bus, classes, ailments=(0, 0, 0, 0)):
        for e, (c, a) in enumerate(zip(classes, ailments)):
            bus.sram[page(e)], bus.sram[page(e) + 1] = c, a

    #  Party creation: the cycle, slot by slot.
    PG = K["ptygen_class"]
    bus, cpu = machine()
    for slot in range(4):
        x = slot * 0x10
        bus.wram[PG + x] = 0
        seen = []
        for _ in range(7):
            cpu.x = x
            call(cpu, "none_nextclass")
            seen.append(bus.wram[PG + x])
        check("slot %d's choices" % (slot + 1), seen,
              [1, 2, 3, 4, 5, 0, 1] if slot == 0 else [1, 2, 3, 4, 5, NONE, 0])

    #  ...its name: an item name for a class, "None" spelled out for a None,
    #  padded to seven as the class names are.
    nb = K["OPTNAMEBUF"]
    bus.wram[PG + 0x20] = 3
    cpu.x = 0x20
    call(cpu, "none_classtext")
    check("party creation's name for a Red Mage",
          (list(bus.wram[0x5E:0x60]), bus.wram[0x3E] | bus.wram[0x3F] << 8), ([0x02, 0xF3], 0x5E))
    bus.wram[PG + 0x20] = NONE
    call(cpu, "none_classtext")
    check("party creation's name for a None",
          (bytes(bus.sram[nb - 0x6000:nb - 0x6000 + 8]), bus.wram[0x3E] | bus.wram[0x3F] << 8),
          (bytes([0x97, 0xB2, 0xB1, 0xA8, 0xFF, 0xFF, 0xFF, 0x00]), nb))

    #  ...and drawn where Bl.MAGE was, it leaves nothing of Bl.MAGE behind:
    #  "NoneAGE" was the first try.  The party creation screen redraws the
    #  class name in place as the choice changes.
    nt = K["NESNT"] - 0x7E0000
    bus, cpu = machine()
    in_vblank(bus)
    bus.wram[nt:nt + 0x800] = bytes(0x800)
    bus.wram[0x60] = 0                          # format_buf's terminator
    for cls in (5, NONE):
        bus.wram[PG + 0x20] = cls
        cpu.x = 0x20
        call(cpu, "none_classtext")
        bus.wram[K["dest_x"]], bus.wram[K["dest_y"]] = 3, 5
        bus.wram[K["cur_bank"]] = bus.wram[K["ret_bank"]] = 0x0E
        call(cpu, "DrawComplexString")
    row = bytes(bus.wram[nt + 5 * 32 + 3:nt + 5 * 32 + 10])
    check("None drawn over Bl.MAGE", row, bytes([0x97, 0xB2, 0xB1, 0xA8, 0xFF, 0xFF, 0xFF]))

    #  ...its sprite: none for a None.
    for cls in (2, NONE):
        bus.wram[PG + 0x10] = cls
        bus.wram[0x10], bus.wram[0x11] = 0xEE, 0xEE
        cpu.x = 0x10
        call(cpu, "none_ptygenspr")
        if cls == NONE:
            check("party creation draws no sprite for a None", cpu.p & 1, 1)
        else:
            pal = ROMDATA[(0xA7 & 0x1F) * 0x10000 + SYM["lutClassBatSprPalette"] + 2]
            check("...and a class's as it did", (cpu.p & 1, bus.wram[0x10], bus.wram[0x11]),
                  (0, 2 * 0x20, pal))

    #  ...and A: a class goes to name input; a None is done, its name blank.
    #  A stub at $AF:1F00 stands in for DoPartyGen_OnCharacter's loop: JSR
    #  PtyGen_A, then mark $1F10 -- which only a return into the loop reaches.
    a = SYM["PtyGen_A"]
    stub = bytes([0x20, a & 0xFF, a >> 8, 0xA9, 0x77, 0x8D, 0x10, 0x1F, 0x60])
    for cls, pressed, want in ((0, 0, "loop"), (0, 1, "name input"), (NONE, 1, "done")):
        bus, cpu = machine()
        bus.wram[0x1F00:0x1F00 + len(stub)] = stub
        bus.wram[K["char_index"]] = 0x30
        bus.wram[PG + 0x30] = cls
        bus.wram[K["ptygen_name"] + 0x30:K["ptygen_name"] + 0x34] = b"\x8a\x8b\x8c\x8d"
        bus.wram[K["joy_a"]] = pressed
        stopped = cpu.run(0xAF, 0x1F00, stop=SYM["DoNameInput"])
        got = ("name input" if stopped else "loop" if bus.wram[0x1F10] == 0x77
               else "done" if not cpu.p & 1 else "?")
        check("A on class $%02X (pressed %d)" % (cls, pressed), got, want)
        if cls == NONE:
            check("...its name blanked", bytes(bus.wram[K["ptygen_name"] + 0x30:][:4]), b"\xff" * 4)

    #  Starting stats: a None is dead, and has nothing.
    bus, cpu = machine()
    party(bus, (0, NONE, 4, NONE))
    for e in range(4):
        bus.sram[page(e) + 0x16] = 40
    call(cpu, "NewGame_LoadStartingStats")
    rec = lambda e: bytes(bus.sram[page(e):page(e) + 0x40])
    check("a None starts dead with an empty page",
          [rec(e)[1:] == bytes([1]) + bytes(0x3E) for e in (1, 3)], [True, True])
    check("...and a class starts alive with its stats",
          [(rec(e)[1], rec(e)[0x0C] > 0) for e in (0, 2)], [(0, True), (0, True)])

    #  The class name in the menus: stat code $01, drawn.
    nt = K["NESNT"] - 0x7E0000
    for cls, want in ((NONE, "None"), (0, "FIGHTER")):
        bus, cpu = machine()
        in_vblank(bus)
        party(bus, (0, cls, 0, 0))
        bus.wram[0x1F20:0x1F23] = bytes([0x11, 0x01, 0x00])      # char 1, its class
        bus.wram[K["text_ptr"]], bus.wram[K["text_ptr"] + 1] = 0x20, 0x1F
        bus.wram[K["dest_x"]], bus.wram[K["dest_y"]] = 2, 2
        bus.wram[K["cur_bank"]] = bus.wram[K["ret_bank"]] = 0x0E
        bus.wram[nt:nt + 0x800] = bytes(0x800)
        call(cpu, "DrawComplexString")
        drawn = "".join(_decode(b) or "" for b in bus.wram[nt + 2 * 32 + 2:nt + 2 * 32 + 2 + len(want)])
        check("the menus name class $%02X" % cls, drawn, want)

    #  The walking sprite and its palette: the first who is not a None.
    pals = {}
    for classes in ((4, 1, 0, 0), (NONE, NONE, 4, 1)):
        bus, cpu = machine()
        party(bus, classes)
        call(cpu, "LeadClass")
        lead = cpu.a & 0xFF
        call(cpu, "LoadPlayerMapmanCHR")
        call(cpu, "LoadMapPalettes")
        pals[classes] = (lead, bus.wram[0x11], bus.wram[K["cur_pal"] + 0x12], bus.wram[K["cur_pal"] + 0x16])
    check("Nones first in line walk as the first who is not one",
          pals[(NONE, NONE, 4, 1)], pals[(4, 1, 0, 0)])
    check("...the lead is the Black Mage", pals[(NONE, NONE, 4, 1)][0], 4)

    #  Class change passes a None by.
    bus, cpu = machine()
    party(bus, (0, NONE, 3, NONE))
    call(cpu, "DoClassChange", bank=0xAF, dbr=0xAF)
    check("class change promotes all but a None", [bus.sram[page(e)] for e in range(4)], [6, NONE, 9, NONE])
    check("...and asks for the map again", bus.wram[K["dlgflg_reentermap"]], 1)

    #  Gear: a None wears nothing, whatever the item.
    bad = []
    for cls in (NONE,):
        for kind, first, n in (("weapons", 1, 40), ("armor", 1, 40)):
            for item in range(first, first + n):
                bus, cpu = machine()
                party(bus, (cls, cls, cls, cls))
                bus.wram[K["cursor"]] = 1 << 2
                bus.wram[K["equipoffset"]] = K["ch_" + kind] - K["ch_stats"]
                cpu.a = item
                call(cpu, "IsEquipLegal_N", bank=0xAF, dbr=0xAF)
                if cls == NONE and not cpu.p & 1:
                    bad.append("None %s %d" % (kind, item))
    check("a None can equip nothing", bad[:3], [])
    reds = []
    for item in range(1, 41):
        bus, cpu = machine()
        party(bus, (3, 3, 3, 3))
        bus.wram[K["cursor"]] = 1 << 2
        bus.wram[K["equipoffset"]] = K["ch_weapons"] - K["ch_stats"]
        cpu.a = item
        call(cpu, "IsEquipLegal_N", bank=0xAF, dbr=0xAF)
        reds.append(not cpu.p & 1)
    check("...where a Red Mage can still equip what it could", (any(reds), all(reds)), (True, False))

    #  Spells: a None learns nothing -- "You can't learn that", dialogue $19.
    for cls, want in ((NONE, 0x19), (4, None)):
        bus, cpu = machine()
        party(bus, (cls, cls, cls, cls))
        bus.wram[K["shop_charindex"]] = 0x40
        bus.wram[K["shop_curitem"]] = 0xB0          # CURE
        bus.sram[K["ch_spells"] - 0x6000:K["ch_spells"] - 0x6000 + 0x100] = bytes(0x100)
        stopped = cpu.run(0xAF, SYM["MagicShop_AssertLearn"], stop=SYM["DrawShopDialogueBox"])
        check("the magic shop and class $%02X" % cls, (cpu.a & 0xFF) if stopped else None, want)

    #  The clinic does not offer to raise a None.
    for classes, ailments, want in (((0, NONE, 3, 0), (0, 1, 1, 0), (1, [0x12, 0, 1])),
                                    ((0, NONE, 3, 0), (0, 1, 0, 0), (0, []))):
        bus, cpu = machine()
        party(bus, classes, ailments)
        call(cpu, "ClinicBuildNameString", bank=0xAF, dbr=0xAF)
        sb = K["str_buf"] + 0x10
        check("the clinic, ailments %s" % (ailments,),
              (bus.wram[K["cursor_max"]], list(bus.wram[sb:sb + 3 * want[0]])), want)

    #  ...nor LIFE from the menu.
    for cls, want in ((NONE, (1, 1)), (3, (0, 0))):
        bus, cpu = machine()
        party(bus, (0, cls, 0, 0), (0, 1, 0, 0))
        bus.wram[K["cursor"]] = 1
        bus.wram[K["tmp"]] = 1                      # death
        cpu.p &= ~1
        call(cpu, "CureOBAilment", bank=0xAF, dbr=0xAF)
        check("CureOBAilment's death cure on class $%02X: fails, still dead" % cls,
              (cpu.p & 1, bus.sram[page(1) + 1]), want)

    #  ...nor Cast Life in Battle.
    for cls, want in ((NONE, (K["AIL_DEAD"], 0)), (3, (0, 1))):
        bus, cpu = machine()
        party(bus, (0, cls, 0, 0))
        bus.sram[K["btl_defender"] - 0x6000] = 0x81
        bus.sram[K["btlmag_defender_ailments"] - 0x6000] = 0     # the cure took the bit off
        call(cpu, "opt_castlife", dbr=0xA1 + 0x0C)
        check("Cast Life in Battle on class $%02X" % cls,
              (bus.sram[K["btlmag_defender_ailments"] - 0x6000] & K["AIL_DEAD"],
               bus.sram[K["btlmag_spellconnected"] - 0x6000]), want)

    #  Battle: a None is not drawn.  btl8x8spr_a is the decoy: DrawCharacter's
    #  first act for anyone it draws is to set it.
    for cls, want in ((NONE, 0xEE), (0, 0x21)):
        bus, cpu = machine()
        party(bus, (0, cls, 0, 0))
        bus.sram[K["btl_charattrib"] + 1 - 0x6000] = 0x21
        bus.sram[K["btl8x8spr_a"] - 0x6000] = 0xEE
        cpu.a = 1
        try:
            call(cpu, "DrawCharacter", bank=0xA1 + 0x0C, dbr=0xA1 + 0x0C)
        except RuntimeError:
            pass
        check("DrawCharacter and class $%02X" % cls, bus.sram[K["btl8x8spr_a"] - 0x6000], want)

    #  Battle CHR: a None's slot loads tiles from inside the table -- the
    #  Fighter's, never drawn -- so with a None there the loader reads exactly
    #  what it reads with a Fighter there.  Reads of the swapped-in bank only
    #  ($8000-$BFFF), logged in order: the fixed bank's are the code itself,
    #  and the None's path through it is an instruction longer.
    def chr_reads(classes):
        bus, cpu = machine()
        party(bus, classes)
        log, read = [], bus.read
        def logged(bank, addr):
            if 0x8000 <= addr & 0xFFFF < 0xC000:
                log.append((bank & 0xFF, addr & 0xFFFF))
            return read(bank, addr)
        bus.read = logged
        call(cpu, "LoadBatSprCHRPalettes")
        return log
    check("battle CHR for a None reads the Fighter's tiles",
          chr_reads((0, NONE, 3, NONE)) == chr_reads((0, 0, 3, 0)), True)

    #  Shop Information: a None can use nothing.
    for cls in (NONE, 3):
        yes = 0
        for item in list(range(0x1C, 0x6C)) + list(range(0xB0, 0xF0)):
            bus, cpu = machine()
            party(bus, (cls, cls, cls, cls))
            bus.sram[K["OPTPOSEIT"] - 0x6000] = item
            cpu.x = 1
            call(cpu, "opt_canuseit", dbr=CHUNK_OPT_BANK)
            yes += cpu.p & 1
        check("Shop Information: what class $%02X can use" % cls, yes > 0, cls != NONE)

    #  A spell on the whole party passes over a None -- no box, no
    #  "Ineffective", no pause -- where the dead and stoned still read
    #  "Ineffective" (playtest: INV2 read it for both Nones).  The loop runs
    #  for real; what it calls is found from its own JSRs and replaced by
    #  recorders in low WRAM, which log the defender each box is drawn for,
    #  then $CC for a cast, $EE for "Ineffective" and $DD for the pause.
    b0c = 0xA1 + 0x0C
    top = SYM["Battle_PlMag_TargetAllPlayers"]
    base = img0c * 0x10000
    code = ROMDATA[base + top:base + top + 0x40]
    a = SYM["none_aoetarget"]
    at = code.find(bytes([0x22, a & 0xFF, a >> 8, OPT]))
    check("the all-party loop asks none_aoetarget", at >= 0, True)
    if at >= 0:
        def jsr(o):
            return code[o + 1] | code[o + 2] << 8 if code[o] == 0x20 else None
        o = at + 8
        callee = dict(box=jsr(o), load=jsr(o + 3), valid=jsr(o + 6), ineff=jsr(o + 11),
                      cast=jsr(o + 17), pause=jsr(o + 20), status=jsr(o + 23))
        check("...and the loop is laid out as it was", None in callee.values(), False)
        LOG, DEF = 0x1FE0, K["btl_defender"]
        rec = lambda v: bytes([0xAE, LOG & 0xFF, LOG >> 8, 0xA9, v,
                               0x9D, (LOG + 1) & 0xFF, (LOG + 1) >> 8, 0xEE, LOG & 0xFF, LOG >> 8, 0x60])
        ail = K["ch_ailments"]
        stubs = dict(
            box=bytes([0xAE, LOG & 0xFF, LOG >> 8, 0xAD, DEF & 0xFF, DEF >> 8,
                       0x9D, (LOG + 1) & 0xFF, (LOG + 1) >> 8, 0xEE, LOG & 0xFF, LOG >> 8, 0x60]),
            load=b"\x60", status=b"\x60",
            valid=bytes([0xAD, DEF & 0xFF, DEF >> 8]) + b"\x0A" * 6 +            # the slot's page
                  bytes([0xAA, 0xBD, ail & 0xFF, ail >> 8, 0x29, K["AIL_DEAD"] | K["AIL_STONE"], 0x60]),
            ineff=rec(0xEE), cast=rec(0xCC), pause=rec(0xDD))
        stubbed, at_wram = bytearray(ROMDATA), 0x1F00
        where = {}
        for k in stubs:
            where[k] = at_wram
            stubbed[base + callee[k]:base + callee[k] + 3] = bytes([0x4C, at_wram & 0xFF, at_wram >> 8])
            at_wram += len(stubs[k])
        check("...its callees far enough apart to stub", min(abs(x - y) for x in callee.values()
              for y in callee.values() if x != y) >= 3, True)

        def aoe(classes, ailments):
            bus, cpu = machine()
            bus.rom = stubbed
            for k in stubs:
                bus.wram[where[k]:where[k] + len(stubs[k])] = stubs[k]
            bus.wram[LOG] = 0
            party(bus, classes, ailments)
            call(cpu, "Battle_PlMag_TargetAllPlayers", bank=b0c, dbr=b0c)
            return list(bus.wram[LOG + 1:LOG + 1 + bus.wram[LOG]]), bus.sram[DEF - 0x6000]

        check("an all-party spell, Fighter / None / dead Bl.MAGE / None",
              aoe((0, NONE, 5, NONE), (0, 1, 1, 1)),
              ([0x80, 0xCC, 0xDD, 0x82, 0xEE, 0xDD], 0x83))
        check("...and with no None, as it always was",
              aoe((0, 1, 5, 2), (0, 0, 2, 0)),
              ([0x80, 0xCC, 0xDD, 0x81, 0xCC, 0xDD, 0x82, 0xEE, 0xDD, 0x83, 0xCC, 0xDD], 0x83))
        check("...and a None in slot 4 with the rest alive",
              aoe((3, 4, 1, NONE), (0, 0, 0, 1)),
              ([0x80, 0xCC, 0xDD, 0x81, 0xCC, 0xDD, 0x82, 0xCC, 0xDD], 0x83))

    #  The wiring: each patched site calls its routine, once.
    for img, name in ((img0e, "none_nextclass"), (img0e, "none_classtext"), (img0e, "none_ptygenspr"),
                      (img0e, "none_ptygena"), (img0e, "none_classchange"), (img0e, "none_cursornone"),
                      (img0e, "none_magperm"), (img0e, "none_isdead"), (img0e, "none_obailment"),
                      (img0c, "none_drawchar"), (img0c, "none_aoetarget")):
        check("%s is called once" % name, jsl_count(img, name, OPT), 1)
    for name in ("PtyGen_A", "IsEquipLegal_N"):
        a = SYM[name]
        lo = img0e * 0x10000 + 0x8000
        check("%s is JSR'd once" % name, ROMDATA[lo:lo + 0x4000].count(bytes([0x20, a & 0xFF, a >> 8])), 1)


def test_rando_namelazy():
    """The name lookup builds the cache only for gear.  It is the game's one
    table of short names, and party creation draws class names through it
    right after New Game writes a new seed: asking the cache there built the
    whole world on that screen, a pause under its music.  A class, spell or
    item name now leaves a stale cache stale, and a gear name still builds
    it -- blursed, here, with a curse and a blessing of five."""
    tag = rw("RW_TAG")
    b0a = (1 + 0x0A) * 0x10000
    bus, cpu = machine()
    setgear(bus, 0x0BADF00D, 5, 5)
    got, want = [], []
    for item in range(256):
        if 0x1C <= item < 0x6C:
            continue
        s0 = cpu.steps
        cpu.a = item
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        got.append((item, (cpu.a & 0xFF) | (cpu.x & 0xFF) << 8, bus.wram[tag], cpu.steps - s0 < 200))
        want.append((item, ROMDATA[b0a + 0xB700 + 2 * item] | ROMDATA[b0a + 0xB701 + 2 * item] << 8, 0, True))
    check("every name but gear's: the ROM's pointer, the cache not built, cheaply", got, want)
    for item in (0x1C, 0x6B):
        bus, cpu = machine()
        setgear(bus, 0x0BADF00D, 5, 5)
        cpu.a = item
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        check("gear $%02X's name builds the cache" % item, bus.wram[tag], K["RW_TAG_VAL"])
    _, bonus = R.build_gear(ROMDATA, 0x0BADF00D, 5, 5)
    g = next(i for i, b in enumerate(bonus) if b)
    bus, cpu = machine()
    setgear(bus, 0x0BADF00D, 5, 5)
    cpu.a = 0x1C + g
    call(cpu, "rando_nameptr", bank=RANDO_BANK)
    check("a gear name builds the cache, and comes back blursed",
          (bus.wram[tag], (cpu.a & 0xFF) | (cpu.x & 0xFF) << 8), (K["RW_TAG_VAL"], K["OPTNAMEBUF"]))

    #  And on the party creation screen itself: a class name drawn the way
    #  PtyGen_DrawOneText draws it, through DrawComplexString's $02.
    nt = K["NESNT"] - 0x7E0000
    bus, cpu = machine()
    in_vblank(bus)
    setgear(bus, 0x0BADF00D, 5, 5)
    bus.wram[0x60] = 0
    bus.wram[K["ptygen_class"]] = 3
    cpu.x = 0
    call(cpu, "none_classtext")
    bus.wram[K["dest_x"]], bus.wram[K["dest_y"]] = 3, 5
    bus.wram[K["cur_bank"]] = bus.wram[K["ret_bank"]] = 0x0E
    call(cpu, "DrawComplexString")
    check("party creation draws a class name without building the world",
          (bus.wram[tag], "".join(_decode(b) or "?" for b in bus.wram[nt + 5 * 32 + 3:nt + 5 * 32 + 10])),
          (0, "RedMAGE"))


# --- Weapon Stats: the enemy's attack element --------------------------------
#  FFR's FixWeaponStats write at $325B0: with the flag on, an enemy's physical
#  attack has category 0 and the element of its touch (ROM byte $0E), not its
#  weakness ($12).  Driven through OptScaleEnemyAttack, the trampoline bank $0C
#  calls, with the two fields preloaded as the caller loads them -- so a flag
#  that did nothing would leave the weakness standing and fail.
def test_enemyelement():
    b0c = (1 + 0x0C) * 0x10000
    cat, elem = K["btl_attacker_category"] - 0x6000, K["btl_attacker_element"] - 0x6000
    bad = []
    for flagbits in (0, F_WEAPONSTATS):
        for i in range(128):
            rec = ROMDATA[b0c + 0x8520 + i * 20:][:20]
            bus, cpu = machine()
            for k in range(4):
                setblk(bus, OPT_FLAGS + k, (flagbits >> (8 * k)) & 0xFF)
            addr = 0x8520 + i * 20
            bus.wram[0x86], bus.wram[0x87] = addr & 0xFF, addr >> 8
            enram(bus, i)
            bus.sram[cat], bus.sram[elem] = rec[0x10], rec[0x12]   # as loaded
            cpu.a = rec[0x0D]                                      # the crit rate
            call(cpu, "OptScaleEnemyAttack", dbr=0xA1 + 0x0C)
            want = (0, rec[0x0E]) if flagbits else (rec[0x10], rec[0x12])
            if (bus.sram[cat], bus.sram[elem]) != want:
                bad.append("enemy %d flags %06X: category/element %s, want %s"
                           % (i, flagbits, (bus.sram[cat], bus.sram[elem]), want))
    check("an enemy attacks with its touch's element under Weapon Stats only", bad[:4], [])

    #  The difference it makes, in the data: a stunning undead is weak to fire,
    #  so its touch used to count as fire and an Ice Shield (which resists
    #  fire) stopped it; now its touch is status, which only the Ribbon resists.
    ghoul = None
    for i in range(128):
        rec = ROMDATA[b0c + 0x8520 + i * 20:][:20]
        if rec[0x0F] == 0x10 and rec[0x12] == 0x10:      # stun, weak to fire
            ghoul = rec
            break
    check("a stunner weak to fire exists, with a status touch",
          ghoul is not None and ghoul[0x0E] == 0x01, True)


#  The tests that take longest, longest first, measured on one core.  Only a
#  scheduling hint for run_apart: started first, they are not left running
#  alone at the end.  A stale entry costs wall time, never a result.
SLOW = ("test_descsynth", "test_shopinfo", "test_chestinfo", "test_descwidth",
        "test_weaponstats", "test_spellinfo", "test_rando_gear",
        "test_rando_gearnames", "test_rando_shops", "test_rando_traps",
        "test_rando_chests", "test_rando_magic", "test_rando_cache")


def run_apart(names):
    """Run each named test in a process of its own, JOBS at a time.

    A process per test rather than a pool of them, so the tests stay as
    isolated from each other as they are when run one by one -- which is how
    a mutation run calls them -- and a test with a sweep can still start a
    pool of its own.  The answer is each failing test's lines, in suite order;
    the skips land in skipped, as if the tests had run here.
    """
    from concurrent.futures import ThreadPoolExecutor
    order = sorted(names, key=lambda n: SLOW.index(n) if n in SLOW else len(SLOW))

    def one(name):
        return name, subprocess.run(
            [sys.executable, os.path.abspath(__file__), "-j", str(JOBS), name],
            capture_output=True, text=True)

    with ThreadPoolExecutor(JOBS) as ex:
        done = dict(ex.map(one, order))
    failed = []
    for name in names:
        r = done[name]
        lines = r.stdout.splitlines()
        if r.returncode == 0:
            skipped.extend(l.strip()[len("skipped: "):] for l in lines
                           if l.strip().startswith("skipped: "))
        elif r.returncode == 1 and lines and lines[0].startswith("FAIL ("):
            failed.append((name, [l[3:] for l in lines[1:]]))
        else:
            #  Not the test failing but the process: an import error, a stale
            #  label file.  Say so rather than count it as a pass.
            tail = (r.stdout + r.stderr).strip().splitlines()
            failed.append((name, ["exited %d: %s" % (r.returncode,
                                  tail[-1] if tail else "no output")]))
    return failed


def main():
    """Every test, or just the ones named on the command line.

    The suite is five and a half minutes of one core's time under CPython,
    most of it the description sweeps driving the 65816 over thousands of
    cases, and about twenty seconds under PyPy, which this runs itself on when
    it is installed (see the top of the file).  More than one test runs as a
    process per test, JOBS at a time, slowest first: about fifteen seconds on
    eight cores, or seventy under CPython.  -j 1 runs them here in turn as it
    always did.  A single test
    runs here, and a sweep inside it still spreads over the cores through
    pmap.  Most single tests are a tenth of a second, and a build is two, so
    checking that one assertion bites is a two-second job:

        ./build.sh && python3 tools/test_options.py test_housemp

    Run the suite before committing, not between edits.
    """
    tests = (test_block, test_presets, test_movespeed, test_encounter,
              test_noshuffle, test_derive, test_guillotine, test_rando_talk, test_rando_early, test_rando_place,
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
              test_elembonus, test_thiefninja, test_thiefhit, test_softbattle, test_wmharm, test_runfix, test_turnfix, test_trance, test_critcount, test_mapedits, test_rando_ordeals,
              test_spellflags, test_tmprsabr, test_cur4,
              test_padreset, test_magicgfx, test_castlife,
              test_playervalid, test_lifemessages,
              test_youfound, test_castline,
              test_descwidth, test_descsynth, test_rowlabels,
             test_dialvalues, test_itemnamewidth,
             test_equipcursor, test_titlerows,
             test_rando_prng, test_rando_traps, test_rando_cache,
             test_rando_mapload, test_rando_battle, test_rando_newgame,
             test_rando_stir, test_rando_options, test_savever,
             test_rando_shops, test_rando_shopload, test_rando_caravan,
             test_menudesc, test_rando_chests, test_rando_chestload,
             test_rando_magic, test_rando_spellconv, test_rando_oobspell,
             test_rando_spellnames, test_rando_magicshop,
             test_rando_gear, test_rando_gearstats, test_rando_gearnames,
             test_enemyelement, test_rando_formations, test_rando_formload,
             test_rando_runs, test_rando_formdata, test_rando_touch,
             test_rando_touchload, test_rando_ai, test_rando_enemyai,
             test_rando_aisynth, test_rando_rng, test_rando_rngload,
             test_rando_begin, test_nones, test_rando_namelazy, test_saveview,
             test_stackshift)

    global JOBS
    args, want = sys.argv[1:], []
    while args:
        a = args.pop(0)
        if a == "-j" and args:
            JOBS = max(1, int(args.pop(0)))
        elif a.startswith("-j") and a[2:].isdigit():
            JOBS = max(1, int(a[2:]))
        else:
            want.append(a)

    #  A misspelled name must not look like a pass -- that is the whole failure
    #  mode this file exists to catch, and it would be galling to ship it here.
    known = {t.__name__ for t in tests}
    unknown = [a for a in want if a not in known]
    if unknown:
        print("no such test: %s" % ", ".join(unknown))
        return 2

    run = [t.__name__ for t in tests if not want or t.__name__ in want]
    if JOBS > 1 and len(run) > 1:
        failed = run_apart(run)
        if failed:
            print("FAIL (%d)" % sum(len(f) for _n, f in failed))
            for name, fs in failed:
                print("   %s:" % name)
                for f in fs:
                    print("      " + f)
            return 1
    else:
        for t in tests:
            if t.__name__ not in run:
                continue
            _warm.clear()               # each test's worlds start cold
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
    if want:
        print("option hooks: %s passed" % ", ".join(want))
    else:
        print("option hooks: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
