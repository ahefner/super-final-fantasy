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
import os, random, re, shutil, subprocess, sys

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
from cpu65816 import Bus, CPU, C, M as FLAG_M, X as FLAG_X
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
    #  New Game puts up its roll screen (roll.asm), which waits on vblanks:
    #  give those waits a clock to see.
    if name in ("rando_newgame", "opt_freestuff") and cpu.bus.clock is None:
        cpu.bus.frames()
    cpu.run(bank, addr, limit=8_000_000 if cpu.bus.clock else 2_000_000)
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
    #  only.  Bit 44, the Ruse Staff, a variation: Super only.
    #
    #  No preset starts with items: like the Treasures flags, they are for the
    #  New Game list's FFR presets to set.
    want = {0: (0x0000000000, 2, 10, 3, 3, 2, 0, 0),
            1: (0x01C00007FDFF, 4, 10, 3, 3, 2, 1, 0),
            2: (0x17E003FFFDFF, 5, 6, 3, 3, 15, 2, 4)}
    for preset, (f, g, e, en, bo, el, th, lp) in want.items():
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
        check("%s: Thief hit step" % name, blk(bus, OPT_THIEFHIT) & 0x0F, th)
        #  Thief lockpicking, in the same byte: FFR's randomized presets have
        #  it at level 15 and its Improved Vanilla does not, so Super only.
        check("%s: Thief lockpicking step" % name, blk(bus, OPT_THIEFHIT) >> 4, lp)
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
    items3 = job[4] if len(job) > 4 else (0, 0, 0)
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
    s[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(items3)
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


def test_rando_remove():
    """The SHIP and AIRSHIP rows' Remove (user): the SHIP, or the FLOATER, in
    no place and never held.  rando_place takes randoref.new_world's
    placement -- on the vanilla tables, and on the seed's own logic with map
    edits, the shuffle among them, which pins FFR's keepers when the FLOATER
    is gone -- and neither item is placed; alone each leaves no world on the
    unedited map, which is the unwinnable warning's.  Its home turns to gold
    with placement (deal_rewards); without it, under Key items Vanilla, the
    FLOATER's chest holds gold before the Chests row deals, and Bikke keeps
    his ship -- the removed one reads as held."""
    SHIP, FLOATER = (R._NAME.index(n) for n in ("SHIP", "FLOATER"))
    def cfg(b0, keyitems=1):
        return (keyitems, [b0, 0, 0], [0x81, 0], 0x0F)
    WALK = 0x1341               # FFR's walking and canoeing edits, the land bridge among them
    jobs = [(seed * 7919 + 3, cfg(0x2B), R.ENTRANCES_OFF, 0) for seed in range(3)]      # no SHIP, AIRSHIP free
    jobs += [(seed * 7919 + 3, cfg(0x2C), R.ENTRANCES_OFF, WALK) for seed in range(2)]  # no FLOATER
    jobs += [(seed * 7919 + 3, cfg(0x2F), R.ENTRANCES_OFF, WALK) for seed in range(2)]  # neither
    jobs += [(seed * 7919 + 3, cfg(0x2C), R.ENTRANCES_ONLY, 0x1FFF) for seed in range(2)]
    jobs += [(seed * 7919 + 3, cfg(0x2C), R.ENTRANCES_FLOORS, 0x0BFF) for seed in range(2)]
    #  ...and with neither the land bridge nor Bahamut's dock, so every keeper
    #  is kept.
    jobs += [(seed * 7919 + 3, cfg(0x2C), R.ENTRANCES_ONLY, 0x0BEF) for seed in range(2)]
    jobs += [(5, cfg(0x23), R.ENTRANCES_OFF, 0), (5, cfg(0x2C), R.ENTRANCES_OFF, 0)]
    got = pmap(es_place_cart, jobs)
    bad, none = [], []
    for (seed, c, mode, f), cart in zip(jobs, got):
        mode_after, k, out, dock = R.new_world(seed, *c, mode, f)
        want = (1 if out else 0, out, k, dock, mode_after)
        if (cart[0], cart[1] if cart[0] else None, cart[2], cart[3], cart[4]) != \
                (want[0], want[1] if want[0] else None, want[2], want[3], want[4]):
            bad.append((seed, c[1][0], mode, f))
        if out is None:
            none.append((c[1][0], f))
        elif (c[1][0] & 3 == 3 and out[SHIP] != 0xFF) or (c[1][0] >> 2 & 3 == 3 and out[FLOATER] != 0xFF):
            bad.append((seed, c[1][0], mode, f, "a removed item placed"))
    check("rando_place with the SHIP or the FLOATER removed: randoref's, neither placed", bad, [])
    check("...each alone, on the unedited map, no world", none, [(0x23, 0), (0x2C, 0)])

    #  FFR's keepers: with the FLOATER gone the doors only the airship reaches
    #  lead where they always did -- and under the land bridge Cardia's are
    #  dealt, which it walks to.
    import graphdata as GD
    keep = GD.NOFLOATER_KEEP
    bad = []
    for seed in range(1, 9):
        for f, kept in ((0, keep["titan"] + keep["cardia"] + keep["cardia_dock"]),
                        (K["OWEDIT_BAHAMUTDOCK"], keep["titan"] + keep["cardia"]),
                        (K["OWEDIT_CARDIABRIDGE"], keep["titan"])):
            w = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR)), R.ENTRANCES_ONLY, f, True)
            if w and any(w[0][o] != GD.VANILLA_ENTRANCE[o] for o in kept):
                bad.append((seed, f))
    check("the FLOATER removed: FFR's keepers lead where they always did", bad, [])

    #  The homes: with placement, gold (randoref.build_rewards).
    bad = []
    for seed in range(2):
        out = R.new_world(seed, *cfg(0x2F), R.ENTRANCES_OFF, WALK)[2]
        bus, cpu = machine()
        sv = bus.sram
        sv[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = seed.to_bytes(4, "little")
        sv[K["RANDO_KEYITEMS"] - 0x6000] = 1
        sv[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes([0x2F, 0, 0])
        sv[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes([0x81, 0])
        sv[K["RANDO_EARLY"] - 0x6000] = 0x0F
        sv[K["RANDO_OWEDITS"] - 0x6000:K["RANDO_OWEDITS"] - 0x6000 + 2] = WALK.to_bytes(2, "little")
        sv[K["RANDO_PLACED"] - 0x6000] = 1
        p = K["RANDO_PLACE"] - 0x6000
        sv[p:p + K["PLACE_ITEMS"]] = bytes(out)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        w = lambda name, n: bytes(bus.wram[rw(name):rw(name) + n])
        want_c, want_t, _ = R.build_rewards(ROMDATA, seed, 0, out, [0x2F, 0, 0])
        if (w("RW_CHESTS", 256), w("RW_TALKREW", 13)) != (want_c, want_t):
            bad.append(seed)
        if {R.PLACE_CODE[SHIP], R.PLACE_CODE[FLOATER]} & (set(want_c) | set(want_t)):
            bad.append((seed, "a removed item given somewhere"))
    check("...with placement, the rewards as randoref deals them, neither item anywhere", bad, [])

    #  Without placement: the FLOATER's chest gold, before the Chests row.
    bad = []
    for seed, chests in ((3, 0), (4, 1), (5, 1)):
        bus, cpu = machine()
        sv = bus.sram
        sv[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = seed.to_bytes(4, "little")
        sv[K["RANDO_CHESTS"] - 0x6000] = chests
        sv[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes([0x0C, 0, 0])
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        got = bytes(bus.wram[rw("RW_CHESTS"):rw("RW_CHESTS") + 256])
        want = R.build_chests(ROMDATA, seed, chests, [0x0C, 0, 0])
        if got != want or R.PLACE_CODE[FLOATER] in want:
            bad.append((seed, chests))
    check("Key items Vanilla, the FLOATER removed: no FLOATER, gold, as randoref has it", bad, [])

    #  ...and Bikke, beaten: with the SHIP removed he talks as to a party that
    #  holds it, and gives nothing; without, he gives it.
    gone = talk_sequence(("Bikke", 1, True, 0, (0x03, 0, 0)))
    held = talk_sequence(("Bikke", 3, True, 0))
    plain = talk_sequence(("Bikke", 1, True, 0))
    check("Key items Vanilla, the SHIP removed: Bikke's lines as when it is held, the ship not given",
          ([t[0] for t in gone], gone[2][6][0]), ([t[0] for t in held], 0))
    check("...and given without it", plain[2][6][0], 1)


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
    #  The first playtest's (seed D1625106): Wide, every key item loose but
    #  the free BRIDGE and KEY, four gear incentives, Early King.
    "wide-loose": (2, [0x65, 0x59, 0x55], [0x39, 0x00], 0x01),
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


def test_es_reference():
    """Entrance shuffle's reference (randoref.es_*), against what the vanilla
    world already has: on the vanilla wiring, es_masks gives logicdata's
    masks in every Early combination, es_groups logicdata's spread groups,
    and the shuffle in both modes deals a wiring that keeps the towns and the
    tables' shapes.  That the shuffle is FFR's, wiring for wiring, and the
    masks the world graph's, is tools/checkentrance.py's; that the worlds it
    builds are winnable, tools/checkplace.py's -- both need worldgraph/."""
    import graphdata as GD
    van = (GD.VANILLA_ENTRANCE, GD.VANILLA_NORMAL, GD.VANILLA_EXIT)
    bad = []
    for early in range(16):
        masks, chaos, req = R.es_masks(*van, early)
        want = R.place_setup(R.KEYITEMS_STANDARD, [0, 0, 0], [0, 0], early)[4]
        bad += [(early, c) for c in range(256) if masks[c] != R._minimal(want[c])]
        if chaos != sorted(R._L.CHAOS_MASKS):
            bad.append((early, "chaos"))
    check("es_masks on the vanilla wiring: logicdata's", bad[:4], [])
    masks = R.es_masks(*van, 0)[0]
    check("es_groups on the vanilla wiring: logicdata's",
          R.es_groups(R.es_roots(van[0], van[1]), masks) == R._L.SPREAD, True)
    towns = [e for e in range(1, 9)]
    for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS):
        for seed in (1, 2, 0xD1625106):
            w = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR)), mode)
            check("mode %d seed %X: a wiring" % (mode, seed), w is not None, True)
            if w is None:
                continue
            entrance, normal, exits, roots = w
            check("mode %d seed %X: the towns stay" % (mode, seed),
                  [entrance[e] for e in towns], [GD.VANILLA_ENTRANCE[e] for e in towns])
            moved = sum(1 for e in range(30) if entrance[e] != GD.VANILLA_ENTRANCE[e])
            check("mode %d seed %X: entrances moved" % (mode, seed), moved > 10, True)
            check("mode %d seed %X: the tables' shapes" % (mode, seed),
                  (len(entrance), len(normal), len(exits)), (32, 64, 16))
            if mode == R.ENTRANCES_ONLY:
                check("mode 1 seed %X: only the Sea Shrine's floor link" % seed,
                      [t for t in range(64) if normal[t] != GD.VANILLA_NORMAL[t]] in ([], [GD.SEASHRINE1]), True)

def es_indices():
    """graphdata's landings and exit coordinates, as the cart numbers them."""
    import graphdata as GD
    lands = sorted(GD.LAND)
    exits = sorted(GD.EXIT_TO)
    return {c: i for i, c in enumerate(lands)}, {c: i for i, c in enumerate(exits)}


def es_cart_wiring(seed, mode, k):
    bus, cpu = machine()
    at = K["RANDO_SAVE"] - 0x6000
    bus.sram[at:at + 4] = seed.to_bytes(4, "little")
    cpu.a, cpu.x = mode, k
    call(cpu, "rando_eswire", bank=WORLD_BANK)
    failed = bus.wram[rw("ES_VARS") + 0x0D]
    e, n, x = rw("ES_ENT"), rw("ES_NORM"), rw("ES_EXIT")
    return failed, list(bus.wram[e:e + 32]), list(bus.wram[n:n + 64]), list(bus.wram[x:x + 16])


def es_wiring_job(job):
    seed, mode, k = job
    return es_cart_wiring(seed, mode, k)


def test_es_wiring():
    """es_wiring deals randoref.es_shuffle's wiring, table for table: each
    entrance's landing, each teleport's, each exit's coordinate, in both
    modes and for more than one attempt's stream."""
    lidx, xidx = es_indices()
    jobs = [(seed, mode, k) for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS)
            for seed in list(range(1, 41)) + [0x600DCAFE, 0xD1625106] for k in (0, 1)]
    got = pmap(es_wiring_job, jobs)
    bad = []
    for (seed, mode, k), cart in zip(jobs, got):
        w = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR + k)), mode)
        if w is None:
            want = (1,)
        else:
            want = (0, [lidx[tuple(c)] for c in w[0]], [lidx[tuple(c)] for c in w[1]],
                    [xidx[tuple(c)] for c in w[2]])
        if (cart[0],) + (tuple(cart[1:]) if not cart[0] else ()) != (want[0],) + (tuple(want[1:]) if not want[0] else ()):
            bad.append((seed, mode, k))
    check("es_wiring deals es_shuffle's wiring", bad[:4], [])

def es_cart_masks(job):
    """rando_esmasks: (stage refused, each location's masks as a sorted list,
    Chaos's, the bit index's lists).  A fifth member, the map edits."""
    seed, mode, k, early, *owe = job
    bus, cpu = machine()
    at = K["RANDO_SAVE"] - 0x6000
    bus.sram[at:at + 4] = seed.to_bytes(4, "little")
    ow = K["RANDO_OWEDITS"] - 0x6000
    bus.sram[ow:ow + 2] = (owe[0] if owe else 0).to_bytes(2, "little")
    cpu.a, cpu.x, cpu.y = mode, k, early
    call(cpu, "rando_esmasks", bank=WORLD_BANK)
    stage = bus.wram[rw("ES_VARS") + 0x0D]
    if stage:
        return stage, None, None, None
    mo, mk = rw("RP_MOFF"), rw("RP_MASK")
    word = lambda a: bus.wram[a] | bus.wram[a + 1] << 8
    masks = []
    for c in range(256):
        lo, hi = word(mo + 2 * c), word(mo + 2 * c + 2)
        masks.append(sorted(int.from_bytes(bus.wram[mk + o:mk + o + 4], "little") for o in range(lo, hi, 4)))
    n = word(rw("RP_NCHAOS"))
    ch = rw("RP_CHAOS")
    chaos = sorted(int.from_bytes(bus.wram[ch + 4 * i:ch + 4 * i + 4], "little") for i in range(n))
    bo, bb = rw("RP_BYBITOFF"), rw("RP_BYBIT")
    bybit = [list(bus.wram[bb + word(bo + 2 * b):bb + word(bo + 2 * b + 2)]) for b in range(32)]
    return 0, masks, chaos, bybit


def test_es_masks():
    """es_fixpoint, es_locmasks and es_bybit give randoref.es_masks's masks,
    location for location, and Chaos's, with placement's index of them --
    on the vanilla wiring in every Early combination (logicdata's own), and
    on shuffled wirings in both modes; and with map edits, on both, the
    graph's conditions (graphdata.CONDS) taken as the reference takes them."""
    jobs = [(1, R.ENTRANCES_OFF, 0, e) for e in range(16)]
    jobs += [(seed, mode, k, e) for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS)
             for seed in (1, 2, 3, 0xD1625106) for k in (0, 1) for e in (0, 0x0F, 0x01)]
    #  ...and wirings with a region needing five masks, one under the limit:
    #  about one in a hundred has one (found by searching the reference).
    jobs += [(9, R.ENTRANCES_ONLY, 0, 0x0F), (55, R.ENTRANCES_ONLY, 0, 0x0F),
             (342, R.ENTRANCES_FLOORS, 0, 0x0F), (452, R.ENTRANCES_FLOORS, 0, 0x0F)]
    #  Map edits: the three the logic once held back in every combination
    #  with Bahamut's dock, the row's All, every edit, on the vanilla wiring;
    #  and on shuffled wirings, the land bridge's moved doors among them.
    held = [K["OWEDIT_SARDAS"], K["OWEDIT_CARDIABRIDGE"], K["OWEDIT_DRYDOCK"], K["OWEDIT_BAHAMUTDOCK"]]
    combos = sorted({sum(b for j, b in enumerate(held) if n >> j & 1) for n in range(16)} |
                    {K["OWEDIT_SAFE"], K["OWEDIT_FLAGS"], 0x0001, 0x0041})
    jobs += [(1, R.ENTRANCES_OFF, 0, e, f) for f in combos for e in (0, 0x0F)]
    jobs += [(seed, mode, 0, 0x0F, f) for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS)
             for seed in (1, 2) for f in (K["OWEDIT_CARDIABRIDGE"], K["OWEDIT_FLAGS"], 0x1410)]
    got = pmap(es_cart_masks, jobs)
    import graphdata as GD
    bad = []
    for (seed, mode, k, early, *owe), cart in zip(jobs, got):
        f = owe[0] if owe else 0
        if mode == R.ENTRANCES_OFF:
            w = (GD.VANILLA_ENTRANCE, GD.VANILLA_NORMAL, GD.VANILLA_EXIT)
        else:
            w = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR + k)), mode, f)
        mm = R.es_masks(w[0], w[1], w[2], early, f) if w else None
        if mm is None:
            if cart[0] == 0:
                bad.append((seed, mode, k, early, "the cart did not refuse"))
            continue
        masks, chaos, _ = mm
        bybit = [[c for c in range(256) if any(m >> b & 1 for m in masks[c])] for b in range(32)]
        if cart[0]:
            bad.append((seed, mode, k, early, "refused at stage %d" % cart[0]))
        elif (cart[1], cart[2], cart[3]) != (masks, chaos, bybit):
            which = [c for c in range(256) if cart[1][c] != masks[c]][:3]
            bad.append((seed, mode, k, early, "locations %s" % which if which else
                        "Chaos" if cart[2] != chaos else "the index"))
    check("es_masks on the cart", bad[:4], [])

def es_cart_world(job):
    """rando_esmasks then rando_esdock for each pool location: (stage refused,
    each region's roots, the groups, each location's dock).  A fifth member,
    the map edits."""
    seed, mode, k, early, *owe = job
    bus, cpu = machine()
    at = K["RANDO_SAVE"] - 0x6000
    bus.sram[at:at + 4] = seed.to_bytes(4, "little")
    ow = K["RANDO_OWEDITS"] - 0x6000
    bus.sram[ow:ow + 2] = (owe[0] if owe else 0).to_bytes(2, "little")
    cpu.a, cpu.x, cpu.y = mode, k, early
    call(cpu, "rando_esmasks", bank=WORLD_BANK)
    stage = bus.wram[rw("ES_VARS") + 0x0D]
    if stage:
        return stage, None, None, None
    import graphdata as GD
    ro = rw("ES_ROOTS")
    roots = [int.from_bytes(bus.wram[ro + 4 * n:ro + 4 * n + 4], "little") for n in range(GD.NODES)]
    gr = rw("RP_GROUP")
    groups = list(bus.wram[gr:gr + 248])
    docks = []
    for c in range(248):
        cpu.a = c
        call(cpu, "rando_esdock", bank=WORLD_BANK)
        docks.append(bus.wram[rw("ES_VARS") + 0x0D])
    return 0, roots, groups, docks


def test_es_world():
    """es_roots, es_groups and es_dock give randoref's: each region's
    entrances, the spread groups (logicdata's on the vanilla wiring), and for
    a ship at each pool location, its dock -- and with map edits, no dock
    Bridge to Lefein deletes, and only Gaia's under Ship in Drydock."""
    import graphdata as GD
    jobs = [(1, R.ENTRANCES_OFF, 0, 0)]
    jobs += [(seed, mode, 0, e) for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS)
             for seed in (1, 2, 0xD1625106) for e in (0, 0x0F)]
    BL, DRY = K["OWEDIT_BRIDGELEFEIN"], K["OWEDIT_DRYDOCK"]
    jobs += [(1, R.ENTRANCES_OFF, 0, 0, f) for f in (BL, K["OWEDIT_SAFE"], 0x1410, DRY)]
    jobs += [(seed, R.ENTRANCES_ONLY, 0, 0x0F, f) for seed in (1, 2) for f in (BL, K["OWEDIT_FLAGS"])]
    got = pmap(es_cart_world, jobs)
    bad = []
    for (seed, mode, k, early, *owe), cart in zip(jobs, got):
        f = owe[0] if owe else 0
        if mode == R.ENTRANCES_OFF:
            w = (GD.VANILLA_ENTRANCE, GD.VANILLA_NORMAL, GD.VANILLA_EXIT)
        else:
            w = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR + k)), mode, f)
        masks, chaos, req = R.es_masks(w[0], w[1], w[2], early, f)
        roots = R.es_roots(w[0], w[1])
        groups = R.es_groups(roots, masks)
        if cart[0]:
            bad.append((seed, mode, early, "refused at stage %d" % cart[0]))
            continue
        if cart[1] != roots:
            bad.append((seed, mode, early, "roots", [n for n in range(GD.NODES) if cart[1][n] != roots[n]][:3]))
        if cart[2] != groups:
            bad.append((seed, mode, early, "groups", [c for c in range(248) if cart[2][c] != groups[c]][:3]))
        docks = [R.es_dock(c, masks, req, roots, f) for c in range(248)]
        if cart[3] != docks:
            bad.append((seed, mode, early, "docks", [c for c in range(248) if cart[3][c] != docks[c]][:3]))
        if f & BL and 4 in docks or f & DRY and set(docks) != {5}:
            bad.append((seed, mode, early, "edits $%04X: docks %s" % (f, sorted(set(docks)))))
    check("es_roots, es_groups and es_dock on the cart", bad[:4], [])
    check("the vanilla wiring's groups are logicdata's", got[0][2] == R._L.SPREAD, True)

def es_place_cart(job):
    """rando_place with entrance shuffle: (placed, placement, k, dock, the
    mode the save is left with).  A fourth member, the map edits."""
    seed, (keyitems, items3, gear2, early), mode, *owe = job
    bus, cpu = machine()
    s = bus.sram
    s[K["RANDO_OWEDITS"] - 0x6000:K["RANDO_OWEDITS"] - 0x6000 + 2] = (owe[0] if owe else 0).to_bytes(2, "little")
    at = K["RANDO_SAVE"] - 0x6000
    s[at:at + 4] = seed.to_bytes(4, "little")
    s[K["RANDO_KEYITEMS"] - 0x6000] = keyitems
    s[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(items3)
    s[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes(gear2)
    s[K["RANDO_EARLY"] - 0x6000] = early
    s[K["RANDO_ENTRANCES"] - 0x6000] = mode
    s[K["RANDO_ESK"] - 0x6000] = 0x55              # decoys
    s[K["RANDO_SHIPDOCK"] - 0x6000] = 0x66
    #  Several wirings and their placements can run past call()'s limit.
    cpu.run(RANDO_BANK, SYM["rando_place"], limit=60_000_000)
    p = K["RANDO_PLACE"] - 0x6000
    return (s[K["RANDO_PLACED"] - 0x6000], list(s[p:p + K["PLACE_ITEMS"]]),
            s[K["RANDO_ESK"] - 0x6000], s[K["RANDO_SHIPDOCK"] - 0x6000], s[K["RANDO_ENTRANCES"] - 0x6000])


def test_es_place():
    """New Game under entrance shuffle: rando_place takes randoref.build_world's
    attempt, placement and dock, and keeps them in the save; with no world it
    falls back to Off's placement and clears the mode.  With map edits, with
    the shuffle or without, randoref.new_world's: the vanilla wiring's logic
    the seed's, not the unedited map's tables."""
    cfgs = [PLACE_CONFIGS[n] for n in ("beginner", "wide-loose", "bridge", "all-loose")]
    jobs = [(seed * 7919 + 13, cfg, mode) for cfg in cfgs for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS)
            for seed in range(3)]
    jobs += [(0xD1625106, PLACE_CONFIGS["wide-loose"], R.ENTRANCES_FLOORS)]
    edits = [K["OWEDIT_SAFE"], K["OWEDIT_FLAGS"], 0x1410, K["OWEDIT_SARDAS"], 0x2041]
    jobs += [(seed * 104729 + 7, cfg, mode, f) for cfg in cfgs[:2] for f in edits
             for mode in (R.ENTRANCES_OFF, R.ENTRANCES_ONLY) for seed in range(2)]
    got = pmap(es_place_cart, jobs)
    bad = []
    for (seed, cfg, mode, *owe), cart in zip(jobs, got):
        mode_after, k, out, dock = R.new_world(seed, *cfg, mode, owe[0] if owe else 0)
        want = (1 if out else 0, out, k, dock, mode_after)
        if (cart[0], cart[1] if cart[0] else None, cart[2], cart[3], cart[4]) != \
                (want[0], want[1] if want[0] else None, want[2], want[3], want[4]):
            bad.append((seed, cfg[0], mode, cart[2:], want[2:]))
    check("rando_place under entrance shuffle: build_world's", bad[:4], [])
    cart = es_place_cart((5, (0, [0x20, 0, 0], [0x81, 0], 0x0F), R.ENTRANCES_FLOORS))
    check("Key items Vanilla: no placement, and the entrances stay put",
          (cart[0], cart[2], cart[3], cart[4]), (0, 0, 0, R.ENTRANCES_OFF))

    #  A wiring whose start reaches no incentive spot, with every item an
    #  incentive, can place nothing: each attempt gives up as stuck at cycle
    #  15, its wasted cycles reusing their counts -- not drawing an incentive
    #  with nowhere to put it to cycle 100 (13 million instructions for this
    #  New Game before).  The placement is the same either way -- the next
    #  wiring has a stream of its own -- so only the cost can tell.
    cfg = PLACE_CONFIGS["wide-bare"]
    check("wide-bare seed 23762, Entrances: its first wiring places nothing",
          R.build_world(23762, *cfg, R.ENTRANCES_ONLY)[0], 1)
    bus, cpu = machine()
    sv = bus.sram
    sv[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = (23762).to_bytes(4, "little")
    sv[K["RANDO_KEYITEMS"] - 0x6000] = cfg[0]
    sv[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(cfg[1])
    sv[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes(cfg[2])
    sv[K["RANDO_EARLY"] - 0x6000] = cfg[3]
    sv[K["RANDO_ENTRANCES"] - 0x6000] = R.ENTRANCES_ONLY
    n0 = cpu.steps
    cpu.run(RANDO_BANK, SYM["rando_place"], limit=60_000_000)
    check("...so its four attempts cost next to nothing (New Game under 3M instructions)",
          (sv[K["RANDO_ESK"] - 0x6000], cpu.steps - n0 < 3_000_000), (1, True))
    #  And a cycle that places nothing reuses the last one's counts: Key items
    #  Standard with no Early flags, seed 158397, whose New Game gives up as
    #  stuck at cycle 15 on six wirings before the seventh places (15.4 million
    #  instructions when every cycle counted afresh; 7.5 since).
    cfg = PLACE_CONFIGS["late"]
    check("late seed 158397, Entrances: the seventh wiring places",
          R.build_world(158397, *cfg, R.ENTRANCES_ONLY)[0], 6)
    bus, cpu = machine()
    sv = bus.sram
    sv[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = (158397).to_bytes(4, "little")
    sv[K["RANDO_KEYITEMS"] - 0x6000] = cfg[0]
    sv[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(cfg[1])
    sv[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes(cfg[2])
    sv[K["RANDO_EARLY"] - 0x6000] = cfg[3]
    sv[K["RANDO_ENTRANCES"] - 0x6000] = R.ENTRANCES_ONLY
    n0 = cpu.steps
    cpu.run(RANDO_BANK, SYM["rando_place"], limit=60_000_000)
    check("...its wasted cycles reusing their counts (New Game under 10M instructions)",
          (sv[K["RANDO_ESK"] - 0x6000], cpu.steps - n0 < 10_000_000), (6, True))

    #  ...and the fallback, which no seed tried has needed: a cart whose
    #  New Game has no attempts places the vanilla world's way, on FFR's safe
    #  tables -- the shuffle's loose ones put back -- and clears the mode.
    rom = bytearray(ROMDATA)
    esk = K["RP_ESK"] & 0xFFFF
    at = (RANDO_BANK - 0xA0) * 0x10000
    op = bytes([0xAD, esk & 0xFF, esk >> 8, 0xC9, R.ES_ATTEMPTS, 0x00, 0xB0])
    i = bytes(rom[at + 0x8000:at + 0xC000]).find(op)
    check("pl_shuffled's attempt count found", i >= 0, True)
    rom[at + 0x8000 + i + 4] = 0                        # CMP #0: no attempts
    cfg = PLACE_CONFIGS["beginner"]
    bus = Bus(bytes(rom))
    cpu = CPU(bus)
    cpu.dbr = 0xA7
    sv = bus.sram
    seed = 3
    sv[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = seed.to_bytes(4, "little")
    sv[K["RANDO_KEYITEMS"] - 0x6000] = cfg[0]
    sv[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(cfg[1])
    sv[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes(cfg[2])
    sv[K["RANDO_EARLY"] - 0x6000] = cfg[3]
    sv[K["RANDO_ENTRANCES"] - 0x6000] = R.ENTRANCES_FLOORS
    cpu.run(RANDO_BANK, SYM["rando_place"], limit=60_000_000)
    p = K["RANDO_PLACE"] - 0x6000
    check("...the safe tables' placement, not the loose ones' (which differ here)",
          (list(sv[p:p + K["PLACE_ITEMS"]]) == R.build_placement(seed, *cfg),
           R.build_placement(seed, *cfg) != R.build_placement(seed, *cfg, tune=R.TUNE_LOOSE),
           sv[K["RANDO_ENTRANCES"] - 0x6000]), (True, True, R.ENTRANCES_OFF))

def land_in_room(m, x, y):
    """Whether a party set down at (x, y) on standard map m is inside a room:
    walking from there, it meets a door (or a locked one) before any way out --
    a room's closing tile, or the edge of the map, which only the open air
    reaches.  Every room's floor is under 80 tiles; a town's open ground,
    whose shops have doors and no closing tile, runs to its edge."""
    banks = b"".join(R.nesbank(ROMDATA, n) for n in (4, 5, 6, 7))
    p = banks[m * 2] | banks[m * 2 + 1] << 8
    tiles = R.decode_rle(banks, p, 4096)
    props, ts = R.rom_props(ROMDATA), ROMDATA[R.TILESETS + m]
    seen, todo, door, out = {(x, y)}, [(x, y)], False, False
    while todo:
        cx, cy = todo.pop()
        out |= cx in (0, 63) or cy in (0, 63)
        for nx, ny in ((cx + 1) & 63, cy), ((cx - 1) & 63, cy), (cx, (cy + 1) & 63), (cx, (cy - 1) & 63):
            if (nx, ny) in seen:
                continue
            p0 = props[ts * 256 + tiles[ny * 64 + nx] * 2]
            if p0 & 0x1E in (0x02, 0x04):       # a door, open or locked
                door = True
            elif p0 & 0x1E == 0x06:             # a room's closing tile: the way out
                out = True
            elif not p0 & 0x01:                 # walkable
                seen.add((nx, ny))
                todo.append((nx, ny))
    return door and not out


def newgame_pressing(bus, cpu, presses=(), entry="rando_newgame"):
    """rando_newgame -- or `entry`, opt_freestuff, which runs it -- with the
    map edit screen's pad (owscreen.asm) held as presses says, one a frame,
    then START.  Out: how many frames the screen read the pad, 0 if it never
    came up.  A screen still up after 400 frames is a failure the caller sees
    as the screen's result never written."""
    UJ = SYM["UpdateJoy"]
    if bus.clock is None:
        bus.frames()

    def pad(nes):
        bus.io[0x4218] = nes & 0x80
        bus.io[0x4219] = (nes & 0x3F) | (0x80 if nes & 0x40 else 0)
    pad(0)
    reads = 0
    stopped = cpu.run(RANDO_BANK if entry == "rando_newgame" else CHUNK_OPT_BANK, SYM[entry],
                      stop=UJ, limit=60_000_000)
    while stopped:
        #  Then START, let go between: the screen counts a press only from
        #  a pad that was let go, so one held as it comes up never ends it.
        pad(presses[reads] if reads < len(presses) else (0x10 if (reads - len(presses)) & 1 else 0))
        reads += 1
        cpu.step()
        for _ in range(60_000_000):
            if cpu.pc in (UJ, 0xFFFE):
                break
            cpu.step()
        stopped = cpu.pc == UJ and reads < 400
    pad(0)
    return reads


def owedits_ffr_source():
    """FFR's two edit files and its OverworldMap constructor, comments
    stripped, or None when FFR's source is not beside the tree."""
    ffr = os.path.join(os.path.dirname(ROOT), "FF1Randomizer", "FF1Lib")
    names = ("OverworldMapEdits.cs", "OverworldCardiaLandBridge.cs", "OverworldMap.cs")
    if not all(os.path.exists(os.path.join(ffr, n)) for n in names):
        return None
    def strip(t):
        t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
        return re.sub(r"//[^\n]*", "", t)
    return [strip(open(os.path.join(ffr, n), encoding="utf-8-sig").read()) for n in names]


def test_owedits():
    """FFR's overworld map edits (owedits.py; world.asm's ow_edit): the
    transcription held to FFR's source when it is beside the tree -- every
    list's writes in order, the order FFR applies the lists in, and the flags
    each is applied under; the cart's rows, as LoadOWMapRow leaves them in the
    window and CallMinimapDecompress in the minimap's two buffers, the map as
    owedits.apply edits it, flag by flag and together; and New Game, which
    expands the Map edits row into RANDO_OWEDITS and moves the BRIDGE under
    Bridge to Lefein."""
    import owedits as O
    src = owedits_ffr_source()
    if src is None:
        print("   (FFR's source is not beside the tree: the transcription is not checked)")
    else:
        edits, _, ctor = src
        e0 = edits.index("enum OwTiles")
        enum = {m.group(1): int(m.group(2), 0) for m in
                re.finditer(r"(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)", edits[e0:edits.index("}", e0)])}
        lists = {}
        for text in src[:2]:
            for m in re.finditer(r"List<MapEdit>\s+(\w+)\s*=\s*new List<MapEdit>\s*\{(.*?)\};", text, re.S):
                out = []
                for it in re.findall(r"new MapEdit\s*\{(.*?)\}", m.group(2), re.S):
                    f = dict(re.findall(r"(X|Y|Tile)\s*=\s*([^,]+?)\s*(?:,|$)", it.strip()))
                    val = lambda v: (enum[v.split(".")[-1]] if "OwTiles." in v else int(v, 0))
                    out.append((val(f["X"]), val(f["Y"]), val(f["Tile"].strip())))
                lists[m.group(1)] = out
        check("owedits.py: every list FFR defines, each write as FFR has it, in order",
              lists, O.LISTS)
        body = ctor[ctor.index("if (!flags.DisableOWMapModifications)") + 38:]
        body = body[:body.index("public static Dictionary<Palette")]
        stack, pending, adds = [], None, []
        for m in re.finditer(r"if\s*\(((?:[^()]|\([^()]*\))*)\)|\{|\}|MapEditsToApply\.Add\((\w+)\)", body):
            t = m.group(0)
            if t.startswith("if"):
                pending = m.group(1)
            elif t == "{":
                stack.append(pending)
                pending = None
            elif t == "}":
                if stack:
                    stack.pop()
            else:
                conds = " ".join(c for c in stack + [pending] if c)
                adds.append((m.group(2), set(re.findall(r"(?<!!)\(bool\)flags\.(\w+)", conds)),
                             set(re.findall(r"!\(bool\)flags\.(\w+)", conds))))
                pending = None
        check("...the lists in the order FFR applies them",
              [n for n, _, _ in adds], [n for n, g in O.ORDER if g != O.LIST_NONE])
        want = []
        for n, g in O.ORDER:
            if g == O.BAHAMUT_DOCK:
                want.append((n, {"MapBahamutCardiaDock"}, {"MapCardiaLandBridge"}))
            elif g == O.LIST_BAHAMUT_BRIDGE:
                want.append((n, {"MapCardiaLandBridge", "MapBahamutCardiaDock"}, set()))
            elif g != O.LIST_NONE:
                want.append((n, {O.SETTINGS[g]}, set()))
        check("...each under the flags its gate says", adds, want)
    check("the cart's flag bits are owedits.py's",
          [K["OWEDIT_" + n] for n in ("OPENPROG", "EXTENDED", "DOCKS", "AIRSHIPDOCK", "BAHAMUTDOCK",
                                      "LEFEINRIVER", "BRIDGELEFEIN", "GAIAPASS", "HIGHWAY",
                                      "RIVERMELMOND", "SARDAS", "HIKE", "CARDIABRIDGE", "DRYDOCK")],
          [1 << i for i in range(len(O.SETTINGS))])
    check("...and the Cardia rule's bit", K["OWE_BAHAMUTBRIDGE"], 1 << O.LIST_BAHAMUT_BRIDGE)
    SAFE = K["OWEDIT_SAFE"]
    check("All: every flag but Sarda's Forest, the Cardia land bridge and drydock",
          [O.SETTINGS[i] for i in range(len(O.SETTINGS)) if not SAFE >> i & 1],
          ["MapSardasForest", "MapCardiaLandBridge", "ShipDrydock"])

    #  The shipped map, decoded here from bank $01's pointers.
    b1 = R.nesbank(ROMDATA, 1)
    van = []
    for r in range(256):
        ptr = b1[2 * r] | b1[2 * r + 1] << 8
        van += R.decode_rle(b1, ptr - 0x8000, 256)
    check("the shipped map: 256 rows of 256", len(van), 65536)
    touched = {y for lst in O.LISTS.values() for _, y, _ in lst}
    for i in range(len(O.SETTINGS)):
        check("flag %s edits the map" % O.SETTINGS[i], O.apply(van, 1 << i) != van, True)
    check("Cardia's two rules: the dock without the land bridge, its variant with it",
          (O.active_lists(0x1010), O.active_lists(0x0010), O.active_lists(0x1000), O.active_lists(0xFFFF)),
          (0x5000, 0x0010, 0x1000, 0x7FEF))

    #  The minimap: its nametable shows a block of the map only where vanilla
    #  has land in it, and lends 88 of the 89 others' pattern tiles to the
    #  crests and the logo -- so land an edit puts in one of those is never
    #  drawn on the map, and shows in the logo until the logo covers it.  No
    #  flag a mode offers may: each alone and all eleven together (the lists
    #  touch no tile in common, so any of them together is covered).  Sarda's
    #  Forest and the Cardia Land Bridge do, in two of the logo's (user,
    #  2026-10-18, with every edit forced on): the New Game screen that offers
    #  them has to move the logo, as FFR's QuickMiniMap does, or do without.
    b9 = ROMDATA[(1 + 0x09) * 0x10000 + 0x8000:][:0x4000]
    mmnt = b9[0x3000:0x3000 + 960]                                  # lut_MinimapNT, $B000
    src9 = open(os.path.join(ROOT, "game", "bank_09.asm"), encoding="latin-1").read()
    at = src9.index("lut_MinimapTileset:")
    tl = bytes(int(v) for l in src9[at:].split("\n")[1:9]
               for v in re.findall(r"\b\d+\b", l.split(";")[0].replace(".BYTE", "")))
    check("lut_MinimapTileset: 128 bytes, once in bank $09", (len(tl), b9.count(tl)), (128, 1))
    hidden = {b for b in range(256) if mmnt[32 * (6 + b // 16) + 8 + b % 16] != b}
    def landblocks(t):
        return {(x // 16) + 16 * (y // 16) for y in range(0, 256, 2) for x in range(0, 256, 2)
                if (tl[t[y * 256 + x]] | tl[t[y * 256 + x + 1]] | tl[t[(y + 1) * 256 + x]]
                    | tl[t[(y + 1) * 256 + x + 1]]) & 3}
    vanland = landblocks(van) & hidden
    check("the minimap hides 89 blocks", len(hidden), 89)
    offered = [1 << i for i in range(len(O.SETTINGS)) if SAFE >> i & 1] + [SAFE]
    check("no mode's edits put land in a block the minimap hides",
          [hex(f) for f in offered if landblocks(O.apply(van, f)) & hidden - vanland], [])
    check("...as Sarda's Forest and the Cardia Land Bridge do, one of the logo's each",
          [sorted(landblocks(O.apply(van, 1 << b)) & hidden - vanland) for b in (O.SARDAS_FOREST, O.CARDIA_BRIDGE)],
          [[0xC2], [0x26]])

    MAPFLAGS, MAPDRAW_Y, MAPROW = K["mapflags"], K["mapdraw_y"], K["mm_maprow"]
    WIN, BUF, BUF2 = 0x7000, 0x0600, 0x0700
    at = K["RANDO_OWEDITS"] - 0x6000
    singles = [1 << i for i in range(len(O.SETTINGS))]
    cases = [(0, range(256)), (K["OWEDIT_OPENPROG"], range(256)), (SAFE, range(256)),
             (0xFFFF, range(256)), (0x1010, sorted(touched))] + [(b, sorted(touched)) for b in singles]
    bus, cpu = machine()
    bad = []
    for flags, rows in cases:
        bus.sram[at:at + 2] = flags.to_bytes(2, "little")
        want = O.apply(van, flags)
        for r in rows:
            bus.wram[MAPFLAGS] = 0                          # the overworld
            bus.wram[MAPDRAW_Y] = r
            slot = WIN - 0x6000 + (r & 15) * 256
            bus.sram[WIN - 0x6000:WIN - 0x6000 + 4096] = b"\xee" * 4096   # decoys
            call(cpu, "LoadOWMapRow")
            got = list(bus.sram[slot:slot + 256])
            others = bytes(bus.sram[WIN - 0x6000:slot]) + bytes(bus.sram[slot + 256:WIN - 0x6000 + 4096])
            if got != want[r * 256:r * 256 + 256] or others.strip(b"\xee"):
                bad.append("flags $%04X row %d%s" % (flags, r, "" if got != want[r * 256:r * 256 + 256]
                                                    else ": another slot written"))
    check("the window: each row as owedits.apply edits it, and only its slot", bad[:4], [])
    bus.sram[at:at + 2] = b"\0\0"
    bus.wram[MAPFLAGS] = 1                                  # a standard map: untouched
    bus.sram[WIN - 0x6000:WIN - 0x6000 + 4096] = b"\xee" * 4096
    call(cpu, "LoadOWMapRow")
    check("...and nothing on a standard map", bytes(bus.sram[WIN - 0x6000:WIN - 0x6000 + 4096]).strip(b"\xee"), b"")

    bad = []
    for flags in (0, SAFE, 0xFFFF):
        bus.sram[at:at + 2] = flags.to_bytes(2, "little")
        want = O.apply(van, flags)
        for r in range(0, 256, 2):
            bus.wram[MAPROW] = r
            call(cpu, "CallMinimapDecompress", bank=0xA1 + 0x09)
            got = list(bus.wram[BUF:BUF + 256]) + list(bus.wram[BUF2:BUF2 + 256])
            if got != want[r * 256:r * 256 + 512]:
                bad.append("flags $%04X rows %d,%d" % (flags, r, r + 1))
    check("the minimap: both rows as owedits.apply edits them", bad[:4], [])

    #  New Game: the row's mode, in RANDO_EARLY above the Early flags, as
    #  the flags it stands for; the Early flags copied as they were.
    BX, BY = K["bridge_x"] - 0x6000, K["bridge_y"] - 0x6000
    early_at = K["OPT_NG_EARLY"] - 0x6000
    modes = {K["OWEDITS_OFF"]: 0, K["OWEDITS_OPEN"]: K["OWEDIT_OPENPROG"], K["OWEDITS_ALL"]: SAFE, 3: 0}
    got, want = [], []
    for mode, flags in sorted(modes.items()):
        for early in (0, K["EARLY_KING"] | K["EARLY_ORDEALS"]):
            bus, cpu = machine()
            bus.sram[early_at] = early | mode << K["OWEDITS_SHIFT"]
            bus.sram[at:at + 2] = b"\xa5\x5a"                # decoys
            bus.sram[BX], bus.sram[BY] = 0x11, 0x22
            newgame_pressing(bus, cpu)          # the map edit screen, START at once
            got.append((int.from_bytes(bus.sram[at:at + 2], "little"), bus.sram[K["RANDO_EARLY"] - 0x6000],
                        (bus.sram[BX], bus.sram[BY])))
            lefein = flags & K["OWEDIT_BRIDGELEFEIN"]
            want.append((flags, early | mode << K["OWEDITS_SHIFT"],
                         (O.BRIDGE_LEFEIN_XY if lefein else (0x11, 0x22))))
    check("New Game: each mode's flags, the Early byte as set, the BRIDGE moved under All only", got, want)
    #  Ship in Drydock, ticked on the map edit screen (up from the first line
    #  is the last): the ship moored at Gaia's drydock before anyone has it --
    #  Bikke's, under Key items Vanilla, only shows it where it is.
    SX = K["ship_x"] - 0x6000
    bus, cpu = machine()
    bus.sram[early_at] = K["OWEDITS_OPEN"] << K["OWEDITS_SHIFT"]
    bus.sram[SX], bus.sram[SX + 1] = 0x11, 0x22
    newgame_pressing(bus, cpu, [0, 0, 0x08, 0, 0x80, 0])
    check("New Game, Ship in Drydock ticked: the ship at Gaia's drydock",
          (int.from_bytes(bus.sram[at:at + 2], "little"), (bus.sram[SX], bus.sram[SX + 1])),
          (K["OWEDIT_OPENPROG"] | K["OWEDIT_DRYDOCK"], O.DRYDOCK_XY))

    #  The row: a field of OPT_NG_EARLY above the four Early flags, which
    #  share the byte -- and no two of the page's fields overlap, read from
    #  the tables rather than from what this row should be.
    optimg = (CHUNK_OPT_BANK & 0x1F) * 0x10000
    tbl = lambda name, i: ROMDATA[optimg + SYM[name] + i]
    n = (SYM["lut_ValTabHi"] - SYM["lut_ValTabLo"])
    fields = [(tbl("lut_ValOff", i), tbl("lut_ValMask", i), tbl("lut_ValBit", i), tbl("lut_ValCount", i))
              for i in range(n)]
    me = [i for i, f in enumerate(fields) if f[0] == (K["OPT_NG_EARLY"] & 0xFF) and f[2] == K["OWEDITS_SHIFT"]]
    check("Map edits: one scalar, bits 4-5 of the Early byte, three modes",
          [fields[i][1:] for i in me], [(K["OWEDITS_FIELD"], 4, 3)])
    clash = [(i, j) for i in range(n) for j in range(i) if fields[i][0] == fields[j][0]
             and fields[i][1] & fields[j][1]]
    check("no two of the page's fields share a bit", clash, [])
    check("...each mode fits its field",
          [i for i, (_, mask, bit, count) in enumerate(fields) if (count - 1) << bit & ~mask & 0xFF], [])


def test_owscreen():
    """New Game's map edit screen (owscreen.asm).  The minimap it draws,
    every pixel row under the boxes ticked and the selection's flashing
    pixels, held to a rendering here of owedits.apply's map in the game's
    minimap colours -- Bahamut's dock's and the land bridge's as the other
    box makes them; the inset, a place of the selection's; the screen as it
    comes up, the minimap and the zoom whole before the display goes on,
    from the baked minimap, the music kept going; and the screen from
    rando_newgame, the row at All: its first choice the saved game's, A
    ticking the selected box, START keeping what is ticked, the chirps,
    and L + X resetting from it."""
    import owedits as O
    OWS = 0xA1 + K["CHUNK_OWS"]
    W = lambda name: K[name] - 0x7E0000
    b1 = R.nesbank(ROMDATA, 1)
    van = []
    for r in range(256):
        ptr = b1[2 * r] | b1[2 * r + 1] << 8
        van += R.decode_rle(b1, ptr - 0x8000, 256)
    img = (OWS & 0x1F) * 0x10000
    TS = ROMDATA[img + SYM["lut_OwsTiles"]:][:128]
    src9 = open(os.path.join(ROOT, "game", "bank_09.asm"), encoding="latin-1").read()
    at = src9.index("lut_MinimapTileset:")
    tl = bytes(int(v) for l in src9[at:].split("\n")[1:9]
               for v in re.findall(r"\b\d+\b", l.split(";")[0].replace(".BYTE", "")))
    check("its colours are the game's minimap's", bytes(TS), tl)

    def lists(*names):
        return {(x, y) for n in names for x, y, _ in O.LISTS[n]}

    def colour(t, hl):
        v = TS[t]
        c = 4 if v & 4 else v & 3
        return c | (8 if hl else 0)

    def pack(px, width):
        """Rows of colours, width wide, as 4bpp characters, width / 8 across."""
        out = bytearray(len(px) // 8 * (width // 8) * 32)
        for r, row in enumerate(px):
            for x, c in enumerate(row):
                t = (r // 8) * (width // 8) + x // 8
                for plane in range(4):
                    if c >> plane & 1:
                        out[t * 32 + (16 if plane >= 2 else 0) + (r % 8) * 2 + (plane & 1)] |= 0x80 >> (x % 8)
        return bytes(out)

    import genows as GO

    def hls(sel, flags):
        g = GO.view_gates(GO.view(sel, flags))
        return {(x, y) for name, gate in O.ORDER if gate != O.LIST_NONE and g >> gate & 1
                for x, y, _ in O.LISTS[name]}

    #  Which tiles the selection flags, said here by name rather than
    #  through genows: Bahamut's dock is its own list, or the variant alone
    #  under the land bridge.  The land bridge is its own either way, which
    #  takes in the variant's tiles -- the reason it has no second view.
    want = [(0, 0, lists("VolcanoIceRiver", "ConeriaToDwarves")),
            (0x0010, O.BAHAMUT_DOCK, lists("BahamutCardiaDock")),
            (0x1000, O.BAHAMUT_DOCK, lists("CardiaLandBridgeBahamutDock")),
            (0x1000, O.CARDIA_BRIDGE, lists("CardiaLandBridge")),
            (0x0010, O.CARDIA_BRIDGE, lists("CardiaLandBridge"))]
    check("the selection's tiles: Bahamut's dock as the land bridge's box makes it",
          [(f, sel) for f, sel, hl in want if hls(sel, f) != hl], [])
    check("...the land bridge's tiles take in the variant's",
          lists("CardiaLandBridgeBahamutDock") <= lists("CardiaLandBridge"), True)

    def expect_minimap(flags, sel):
        t, hl = O.apply(van, flags), hls(sel, flags)
        rows = []
        for p in range(128):
            row = []
            for cx in range(128):
                cells = ((2 * cx, 2 * p), (2 * cx + 1, 2 * p), (2 * cx, 2 * p + 1), (2 * cx + 1, 2 * p + 1))
                v = 0
                for x, y in cells:
                    v |= TS[t[x + 256 * y]]
                c = 4 if v & 4 else v & 3
                row.append(c | (8 if any(cl in hl for cl in cells) else 0))
            rows.append(row)
        return pack(rows, 128)

    BAKED = ROMDATA[img + SYM["lut_OwsBaked"]:][:8192]

    def setup(bus, flags, sel, site=0):
        #  OWS_CHR as ows_first leaves it, which ows_prow draws over.
        bus.wram[W("OWS_CHR"):W("OWS_CHR") + 8192] = BAKED
        bus.wram[W("OWS_VARS"):W("OWS_VARS") + 2] = flags.to_bytes(2, "little")
        bus.wram[W("OWS_VARS") + 6] = sel
        bus.wram[W("OWS_VARS") + 9] = 0         # the frame: the rings shown
        bus.wram[W("OWS_VARS") + 10] = site

    SAFE = K["OWEDIT_SAFE"]
    bus, cpu = machine()
    bad = []
    for flags, sel in ((0, 0), (SAFE, 6), (0x3FFF, O.CARDIA_BRIDGE), (0x1010, O.BAHAMUT_DOCK),
                       (0x0010, O.BAHAMUT_DOCK), (0x0010, O.CARDIA_BRIDGE)):
        setup(bus, flags, sel)
        for p in range(128):
            cpu.a = p
            call(cpu, "ows_testprow", bank=OWS)
        got = bytes(bus.wram[W("OWS_CHR"):W("OWS_CHR") + 8192])
        if got != expect_minimap(flags, sel):
            bad.append("flags $%04X selection %d" % (flags, sel))
    check("the minimap: owedits.apply's map, the selection's pixels flagged", bad, [])

    def expect_inset(flags, sel, site):
        cx, cy, w = GO.sites(GO.view(sel, flags))[site]
        scale = 1 if w > 28 else 2
        span = 56 // scale
        x0, y0 = (cx - span // 2) & 255, (cy - span // 2) & 255
        t, hl = O.apply(van, flags), hls(sel, flags)
        rows = []
        for i in range(span):
            y = (y0 + i) & 255
            row = []
            for j in range(span):
                x = (x0 + j) & 255
                row += [colour(t[x + 256 * y], (x, y) in hl)] * scale
            rows += [row] * scale
        return pack(rows, 56)

    bad = []
    for flags, sel, site in ((SAFE, 6, 0), (SAFE, 6, 2), (0x3FFF, O.CARDIA_BRIDGE, 0), (0, 2, 1),
                             (0x1010, O.BAHAMUT_DOCK, 0)):
        setup(bus, flags, sel, site)
        call(cpu, "ows_testinset", bank=OWS)
        got = bytes(bus.wram[W("OWS_INSETCHR"):W("OWS_INSETCHR") + 49 * 32])
        if got != expect_inset(flags, sel, site):
            bad.append("flags $%04X selection %d place %d" % (flags, sel, site))
    check("the inset: a place of the selection's, at its scale", bad, [])
    vx = [x for x, _, _ in O.LISTS["CardiaLandBridgeBahamutDock"]]
    vy = [y for _, y, _ in O.LISTS["CardiaLandBridgeBahamutDock"]]
    check("...Bahamut's dock under the land bridge: the variant's, alone",
          GO.sites(GO.view(O.BAHAMUT_DOCK, 0x1000)),
          [((min(vx) + max(vx)) // 2, (min(vy) + max(vy)) // 2, max(max(vx) - min(vx), max(vy) - min(vy)) + 1)])
    #  ...and ringed there, one ring, on the minimap at half scale.
    side = int(re.search(r"^OWS_SIDE\s*=\s*(\d)", open(os.path.join(ROOT, "src", "owslayout.inc")).read(), re.M).group(1))
    bus, cpu = machine()
    bus.ppu()
    setup(bus, 0x1010, O.BAHAMUT_DOCK)
    call(cpu, "ows_testinset", bank=OWS)
    mc = 1 if side else 10
    check("...its ring at the variant, the rest hidden",
          [tuple(bus.oam[4 * k + 4:4 * k + 6]) for k in range(4)],
          [((min(vx) + max(vx)) // 2 // 2 + mc * 8 - 8, (min(vy) + max(vy)) // 2 // 2 + 8 - 9)] + [(0, 224)] * 3)

    #  The screen as it comes up: VRAM holds the minimap and the zoom whole
    #  when the display goes on, the unedited rows from lut_OwsBaked, and a
    #  frame of the music for each vblank the drawing takes.
    inset = int(re.search(r"^OWS_INSET\s*=\s*(\d)", open(os.path.join(ROOT, "src", "owslayout.inc")).read(), re.M).group(1))
    CMP = SYM["CallMusicPlay"]
    bad, music = [], []
    for flags in (0, SAFE, 0x3FFF):
        bus, cpu = machine()
        bus.frames()
        bus.ppu()
        bus.dma = True
        setup(bus, flags, 0)
        h0 = bus.wram[K["h_frame"]] | bus.wram[K["h_frame"] + 1] << 8
        cpu.pbr, cpu.pc = OWS, SYM["ows_testsetup"]
        cpu.push(0xFF); cpu.push(0xFF); cpu.push(0xFD)
        plays = 0
        for _ in range(8_000_000):
            if cpu.pc == 0xFFFE:
                break
            if cpu.pc == CMP:
                plays += 1
            cpu.step()
        frames = (bus.wram[K["h_frame"]] | bus.wram[K["h_frame"] + 1] << 8) - h0
        if bytes(bus.vram[0:8192]) != expect_minimap(flags, 0):
            bad.append("flags $%04X: the minimap" % flags)
        if inset and bytes(bus.vram[8192:8192 + 49 * 32]) != expect_inset(flags, 0, 0):
            bad.append("flags $%04X: the zoom" % flags)
        if bus.io[0x2100] != 0x0F:
            bad.append("flags $%04X: the display left off" % flags)
        music.append((frames, plays))
    check("the screen up whole: the minimap and the zoom in VRAM as the display goes on", bad, [])
    check("...a frame of music for every frame sent, more than the first's with much to draw",
          [f == p for f, p in music] + [music[2][0] > 1], [True] * 4)

    #  The screen itself, from New Game.
    UJ = SYM["UpdateJoy"]

    def pad(bus, nes):
        bus.io[0x4218] = nes & 0x80
        bus.io[0x4219] = (nes & 0x3F) | (0x80 if nes & 0x40 else 0)

    def newgame(saved_flags, presses, row=K["OWEDITS_ALL"]):
        bus, cpu = machine()
        bus.frames()
        ow = K["RANDO_OWEDITS"] - 0x6000
        if saved_flags is not None:
            bus.sram[ow:ow + 2] = saved_flags.to_bytes(2, "little")
            cpu.dbr = BANK_0E
            cpu.run(BANK_0E, SYM["SaveGame"])
            cpu.dbr = 0xA7
        bus.sram[K["OPT_NG_EARLY"] - 0x6000] = row << K["OWEDITS_SHIFT"]
        reads = newgame_pressing(bus, cpu, presses)
        return int.from_bytes(bytes(bus.sram[ow:ow + 2]), "little"), reads

    got = newgame(0x0402, [0, 0, 0, 0x10])
    check("the saved game's: Extended Open and Sarda's Forest", got[0], 0x0402)
    got = newgame(0x0002, [0, 0, 0x80, 0, 0x10])
    check("A ticks the selected, Early Open", got[0], 0x0003)
    got = newgame(None, [0, 0, 0x10])
    check("no save: the row's, All", got[0], SAFE)
    check("...the screen up for it", got[1] > 0, True)
    got = newgame(None, [], row=K["OWEDITS_OFF"])
    check("the row Off: no screen, no edits", got, (0, 0))
    got = newgame(None, [0, 0, 0x04, 0, 0x80, 0, 0x10], row=K["OWEDITS_OPEN"])
    check("Open, the selection down one, Extended ticked", got[0], 0x0003)
    got = newgame(None, [0, 0, 0x01, 0, 0x80, 0, 0x10], row=K["OWEDITS_OPEN"])
    check("...right: the next in the column, or across the grid",
          got[0], 0x0003 if side else 0x0081)

    #  A frame at a time from the screen's first pad read -- setup's, which
    #  the loop does not answer -- then DOWN, A, and L + X.  The move chirps, the tick chirps the other way, and the reset is
    #  taken from the screen's own loop, the PPU handed back to the HAL first.
    bus, cpu = machine()
    bus.frames()
    bus.sram[K["OPT_NG_EARLY"] - 0x6000] = K["OWEDITS_OPEN"] << K["OWEDITS_SHIFT"]
    pad(bus, 0)
    cpu.run(RANDO_BANK, SYM["rando_newgame"], stop=UJ, limit=60_000_000)
    MOVE, SEL = SYM["PlaySFX_MenuMove"], SYM["PlaySFX_MenuSel"]
    CLAIM, RESET = SYM["hal_ppureclaim"], SYM["OnReset"]
    events = []
    for frame, (nes, aux) in enumerate(((0, 0), (0, 0), (0x04, 0), (0, 0), (0x80, 0), (0, 0), (0, 0x60), (0, 0))):
        pad(bus, nes)
        bus.io[0x4218] |= aux
        cpu.step()
        for _ in range(2_000_000):
            if cpu.pc == UJ:
                break
            if cpu.pbr == BANK_0E and cpu.pc in (MOVE, SEL):
                events.append((frame, "move" if cpu.pc == MOVE else "tick"))
            if cpu.pbr == 0xC0 and cpu.pc == CLAIM:
                events.append((frame, "claim"))
            if cpu.pbr == 0xA1 and cpu.pc == RESET:      # CHUNK0, as opt_padreset enters it
                events.append((frame, "reset"))
                break
            cpu.step()
        if events and events[-1][1] == "reset":
            break
    pad(bus, 0)
    check("the chirps on a move and a tick, and L + X resetting, the PPU back first",
          events, [(2, "move"), (4, "tick"), (6, "claim"), (6, "reset")])


def test_es_tree():
    """randoref's wiring dump (es_tree, randoref.py SRM --map): each floor once,
    under the entrance the shuffle hung it from, and every floor a wiring
    lands on in it -- for the vanilla wiring and both modes' first attempts."""
    import graphdata as GD
    wirings = [("vanilla", GD.VANILLA_ENTRANCE, GD.VANILLA_NORMAL, None)]
    for seed in SEEDS[:3]:
        for mode in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS):
            w = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR)), mode)
            if w is not None:
                wirings.append(("seed $%08X mode %d" % (seed, mode), w[0], w[1], w[3]))
    check("a shuffled wiring in each mode", len(wirings) > 4, True)
    at = {tuple(v): r for r, v in GD.LANDED.items()}
    for name, ent, norm, roots in wirings:
        tree = R.es_tree(ent, norm)
        seen = [r for _, _, floors in tree for _, r, _, _ in floors]
        check(name + ": each floor once", len(seen), len(set(seen)))
        landed = {at[tuple(ent[o])] for o in GD.OW_COORDS if tuple(ent[o]) in at}
        check(name + ": every entrance's floor at the top of its own tree",
              sorted(f[0][1] for _, _, f in tree if f), sorted(landed))
        if roots is not None:
            check(name + ": every floor the shuffle dealt, in the dump",
                  sorted(set(roots) - set(seen)), [])
            check(name + ": each floor under the entrance its chain hangs from",
                  [(r, o) for o, _, floors in tree for _, r, _, _ in floors if roots.get(r, o) != o], [])
    lines = R.es_tree_text(wirings[-1][1], wirings[-1][2])
    check("the text: an entrance line per overworld entrance",
          sum(1 for l in lines if l.endswith(":")), len(GD.OW_COORDS))


def test_es_tables():
    """The teleport tables the game reads come from the cache: bank $00's own
    with entrance shuffle off, the save's wiring -- attempt RANDO_ESK in its
    mode -- with it on and the key items placed; and the three hooks read
    them: an entrance's landing, a normal teleport's (the Ordeals pillars'
    one moved teleport still moved) and an exit's."""
    import graphdata as GD
    b0 = (1 + 0x00) * 0x10000
    rom = lambda a, n: list(ROMDATA[b0 + a:b0 + a + n])
    #  Bit 7 of a landing's x is its room, which the game's own tables never
    #  marked (it carried inroom over).  Which landings are in rooms is worked
    #  out here from the cartridge's maps, not taken from FFR's lists: FFR's
    #  StandardInRoom destinations were seven, missing the two in the Temple
    #  of Fiends Revisited, and the party was set down on 1F's room mask after
    #  the Black Orb (user, 2026-10-17).
    ROOM = set(map(tuple, GD.LAND_ROOM))
    check("the rooms: every landing the maps put inside a room, and no other",
          sorted(ROOM), sorted(c for c in GD.LAND if c[0] < len(R.MAP_NAMES) and land_in_room(*c)))
    check("...nine of them, the Black Orb's onto Temple of Fiends (past) 1F among them",
          (len(ROOM), (52, 20, 17) in ROOM), (9, True))
    roomx = lambda xs, ys, ms: [x | (0x80 if (m, x, y) in ROOM else 0) for x, y, m in zip(xs, ys, ms)]
    van = (rom(0xAC00, 32), rom(0xAC20, 32), rom(0xAC40, 32), rom(0xAD00, 64), rom(0xAD40, 64),
           rom(0xAD80, 64), rom(0xAC60, 16), rom(0xAC70, 16))
    van = (roomx(van[0], van[1], van[2]),) + van[1:3] + (roomx(van[3], van[4], van[5]),) + van[4:]
    check("...each a landing of the vanilla wiring's normal teleports, none an entrance's",
          (sum(x >> 7 for x in van[0]), sum(x >> 7 for x in van[3])), (0, 9))

    def tables(seed, mode, k, placed=1, ordeals=0, owedits=0):
        bus, cpu = machine()
        s = bus.sram
        at = K["RANDO_SAVE"] - 0x6000
        s[at:at + 4] = seed.to_bytes(4, "little")
        s[K["RANDO_OWEDITS"] - 0x6000:K["RANDO_OWEDITS"] - 0x6000 + 2] = owedits.to_bytes(2, "little")
        s[K["RANDO_ENTRANCES"] - 0x6000] = mode
        s[K["RANDO_ESK"] - 0x6000] = k
        s[K["RANDO_PLACED"] - 0x6000] = placed
        s[K["RANDO_ORDEALS"] - 0x6000] = ordeals
        for name, n in (("RW_ENTRX", 32), ("RW_ENTRY", 32), ("RW_ENTRMAP", 32), ("RW_NORMX", 64),
                        ("RW_NORMY", 64), ("RW_NORMMAP", 64), ("RW_EXITX", 16), ("RW_EXITY", 16)):
            bus.wram[rw(name):rw(name) + n] = bytes([0xA5]) * n      # decoys
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        get = lambda name, n: list(bus.wram[rw(name):rw(name) + n])
        return bus, cpu, (get("RW_ENTRX", 32), get("RW_ENTRY", 32), get("RW_ENTRMAP", 32),
                          get("RW_NORMX", 64), get("RW_NORMY", 64), get("RW_NORMMAP", 64),
                          get("RW_EXITX", 16), get("RW_EXITY", 16))

    check("Off: bank $00's tables", tables(1, R.ENTRANCES_OFF, 0)[2], van)
    check("a mode without a placement: bank $00's tables", tables(1, R.ENTRANCES_FLOORS, 0, placed=0)[2], van)
    for seed, mode, k in ((1, R.ENTRANCES_ONLY, 0), (2, R.ENTRANCES_FLOORS, 1), (0xD1625106, R.ENTRANCES_FLOORS, 0)):
        entrance, normal, exits, _ = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR + k)), mode)
        want = ([c[1] | (0x80 if tuple(c) in ROOM else 0) for c in entrance], [c[2] for c in entrance],
                [c[0] for c in entrance],
                [c[1] | (0x80 if tuple(c) in ROOM else 0) for c in normal], [c[2] for c in normal],
                [c[0] for c in normal], [c[0] for c in exits], [c[1] for c in exits])
        check("mode %d seed %X attempt %d: the save's wiring" % (mode, seed, k), tables(seed, mode, k)[2], want)
    #  The Cardia Land Bridge moves six entrances, and an exit wired to one
    #  sets the party down where it is now (FFR's OverworldMap.ApplyMapEdits):
    #  the first seed whose wiring has such an exit, with the bridge and
    #  without it.
    CB = K["OWEDIT_CARDIABRIDGE"]
    for seed in range(1, 400):
        a = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR)), R.ENTRANCES_FLOORS, CB)
        b = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR)), R.ENTRANCES_FLOORS)
        if a and b and a[2] != b[2]:
            break
    check("the land bridge: a seed whose exits it moves", a[2] != b[2], True)
    got = tables(seed, R.ENTRANCES_FLOORS, 0, owedits=CB)[2]
    check("...the exits where the reference has them, the moved ones the bridge's",
          (got[6], got[7]), ([c[0] for c in a[2]], [c[1] for c in a[2]]))
    check("...a moved one among them",
          any((x, y) in set(GD.OW_COORDS_CARDIA.values()) - set(GD.OW_COORDS.values())
              for x, y in zip(got[6], got[7])), True)

    #  The hooks, on a shuffled world: each landing's scroll and map.
    bus, cpu, t = tables(2, R.ENTRANCES_FLOORS, 1)
    sx, sy, ox, oy = K["sm_scroll_x"], K["sm_scroll_y"], K["ow_scroll_x"], K["ow_scroll_y"]
    bad = []
    IR = K["inroom"]
    rooms = 0
    for e in range(32):
        for before in (0x00, 0x81, 0x84):          # outside, inside, leaving a room
            bus.wram[IR] = before
            cpu.x = e
            call(cpu, "rando_entrdest", bank=RANDO_BANK)
            if (bus.wram[sx], bus.wram[sy], cpu.a & 0xFF, cpu.x & 0xFF, bus.wram[IR]) != \
                    ((t[0][e] - 7) & 0x3F, (t[1][e] - 7) & 0x3F, t[2][e], e, 0x81 if t[0][e] & 0x80 else 0):
                bad.append(("entrance", e, before))
        rooms += t[0][e] >> 7
    for tid in range(64):
        for before in (0x00, 0x81, 0x84):
            bus.wram[IR] = before
            cpu.x = tid
            call(cpu, "rando_teledest", bank=RANDO_BANK)
            if (bus.wram[sx], bus.wram[sy], cpu.a & 0xFF, cpu.x & 0xFF, bus.wram[IR]) != \
                    ((t[3][tid] - 7) & 0x3F, (t[4][tid] - 7) & 0x3F, t[5][tid], tid,
                     0x81 if t[3][tid] & 0x80 else 0):
                bad.append(("teleport", tid, before))
        rooms += t[3][tid] >> 7
    for x in range(16):
        cpu.x = x
        call(cpu, "rando_exitdest", bank=RANDO_BANK)
        if (bus.wram[ox], bus.wram[oy]) != ((t[6][x] - 7) & 0xFF, (t[7][x] - 7) & 0xFF):
            bad.append(("exit", x))
    check("the hooks read the cache's tables, and set inroom from the landing", bad[:4], [])
    check("...in rooms and out of them, both", 0 < rooms < 96, True)
    #  ...and build it first, when nothing else has since power-on.
    cold = []
    for hook, x, want in (("rando_entrdest", 5, lambda b, c: (b.wram[sx], c.a & 0xFF)),
                          ("rando_teledest", 9, lambda b, c: (b.wram[sx], c.a & 0xFF)),
                          ("rando_exitdest", 3, lambda b, c: (b.wram[ox], b.wram[oy]))):
        bus2, cpu2 = machine()
        bus2.sram[:] = bus.sram
        cpu2.x = x
        call(cpu2, hook, bank=RANDO_BANK)
        cold.append(want(bus2, cpu2))
    check("a hook on a cold cache builds it", cold,
          [((t[0][5] - 7) & 0x3F, t[2][5]), ((t[3][9] - 7) & 0x3F, t[5][9]),
           ((t[6][3] - 7) & 0xFF, (t[7][3] - 7) & 0xFF)])
    bus, cpu, t = tables(2, R.ENTRANCES_FLOORS, 1, ordeals=1)
    cpu.x = K["ORD_LOST_TELE"]
    call(cpu, "rando_teledest", bank=RANDO_BANK)
    bus.wram[K["inroom"]] = 0x81
    call(cpu, "rando_teledest", bank=RANDO_BANK)
    check("the Ordeals pillars' teleport still moved, its map the table's, in the open",
          (bus.wram[sx], bus.wram[sy], cpu.a & 0xFF, bus.wram[K["inroom"]]),
          ((K["ORD_LOST_X"] - 7) & 0x3F, (K["ORD_LOST_Y"] - 7) & 0x3F, t[5][K["ORD_LOST_TELE"]], 0))
    #  And the fixed bank asks them, rather than bank $00.
    fixed = (1 + 0x0F) * 0x10000 + 0xC000
    body = ROMDATA[fixed:fixed + 0x4000]
    for name in ("rando_entrdest", "rando_exitdest", "rando_teledest"):
        a = SYM[name]
        check("the fixed bank calls %s" % name, body.count(bytes([0x22, a & 0xFF, a >> 8, RANDO_BANK])), 1)
    #  The entrance path's own "LDA #0 / STA inroom" is gone after the call:
    #  JSL, STA cur_map, TAX, LDA lut_Tilesets,X, STA cur_tileset, then on.
    a = SYM["rando_entrdest"]
    at = body.find(bytes([0x22, a & 0xFF, a >> 8, RANDO_BANK]))
    check("...and the entrance path clears inroom no more",
          (body[at + 4:at + 7], body[at + 10:at + 12], body[at + 12:at + 16] != bytes([0xA9, 0x00, 0x85, 0x0D])),
          (bytes([0x85, 0x48, 0xAA]), bytes([0x85, 0x49]), True))
    for tbl, addr in (("lut_EntrTele", 0xAC00), ("lut_NormTele", 0xAD00), ("lut_ExitTele", 0xAC60)):
        reads = sum(body.count(bytes([0xBD, (addr + o) & 0xFF, (addr + o) >> 8])) for o in (0, 0x20, 0x40, 0x10, 0x80))
        check("the fixed bank reads %s no more" % tbl, reads, 0)

def test_rando_place():
    """Incentive placement: rando_place lands every item exactly where
    randoref.build_placement does, for every setting and seed tried, and every
    placement is whole -- each item to place once, in the pool, an incentive
    in a spot unless the spots ran out, nothing else in one, and the caravan,
    a shop, selling an item if anything.  (That each is
    winnable on the world graph itself is tools/checkplace.py's, which needs
    worldgraph/.)"""
    jobs = [(seed * 7919 + 13, cfg) for cfg in PLACE_CONFIGS.values() for seed in range(12)]
    #  ...and seeds that take a rare path, found by searching randoref with
    #  the path mutated: seed 2 under Beginner weighs the CUBE at between 70
    #  and 75 places reached, where its minimum of 75 says no.  (The halving
    #  of a negative count, the ship and canal raised with one incentive place
    #  reached, and giving up at cycle 15 change no placement in 3,000 seeds of
    #  each setting: FFR's code, kept, that the vanilla world never needs.
    #  Nor does progression first holding back an item that opens exactly one
    #  place, its count 0, in 1,500 seeds of each.)
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


def rewards_cart(job):
    """The cache built from a save that holds randoref's placement: the chests,
    the NPC rewards, the caravan, and every shop row."""
    seed, cfg, chests, shops = job
    keyitems, items3, gear2, early = cfg
    place = R.build_placement(seed, *cfg)
    bus, cpu = machine()
    s = bus.sram
    at = K["RANDO_SAVE"] - 0x6000
    s[at:at + 4] = seed.to_bytes(4, "little")
    s[K["RANDO_CHESTS"] - 0x6000] = chests
    s[K["RANDO_SHOPS"] - 0x6000] = shops
    s[K["RANDO_KEYITEMS"] - 0x6000] = keyitems
    s[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(items3)
    s[K["RANDO_GEAR"] - 0x6000:K["RANDO_GEAR"] - 0x6000 + 2] = bytes(gear2)
    s[K["RANDO_EARLY"] - 0x6000] = early
    s[K["RANDO_PLACED"] - 0x6000] = 1
    p = K["RANDO_PLACE"] - 0x6000
    s[p:p + K["PLACE_ITEMS"]] = bytes(place)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    w = lambda name, n: bytes(bus.wram[rw(name):rw(name) + n])
    return place, w("RW_CHESTS", 256), w("RW_TALKREW", 13), w("RW_CARAVAN", 1)[0], w("RW_SHOPS", 71 * 8)


def test_rando_rewards():
    """Once placement is in, the cache's chests, reward NPCs, caravan and
    shops are randoref.build_rewards' and build_shops', for each setting,
    with the Chests and Shops rows off and shuffled: a placed item where it
    was placed, every moved or Free item's home dealt into or turned to gold,
    the caravan selling one item and left out of the shop deal."""
    jobs = [(seed * 104729 + 7, cfg, chests, shops)
            for cfg in PLACE_CONFIGS.values() for seed in range(3)
            for chests in (0, 1) for shops in (0, 1)]
    res = pmap(rewards_cart, jobs)
    bad = []
    for (seed, cfg, chests, shops), (place, got_c, got_t, got_v, got_s) in zip(jobs, res):
        want_c, want_t, want_v = R.build_rewards(ROMDATA, seed, chests, place, cfg[1])
        want_s = R.build_shops(ROMDATA, seed, shops, caravan=want_v)
        for what, got, want in (("chests", got_c, want_c), ("NPCs", got_t, want_t),
                                ("caravan", got_v, want_v), ("shops", got_s, want_s)):
            if got != want:
                bad.append((seed, cfg, chests, shops, what))
    check("the cache's rewards are randoref's", bad[:3], [])


def test_rando_giving():
    """With placement in, the game hands out what the rewards dealt.  A chest
    holding a vehicle gives it -- a ship moored at the dock of the map it is
    found on (test_rando_shipdock) -- opens as a chest opens, and names it.  A reward NPC
    gives the cache's reward, gold and gear included, with no held test: what
    the party holds proves nothing once items move.  Every key item costs the
    BOTTLE's price, and the caravan stays open."""
    SHIP_VIS, SHIP_X, SHIP_Y = 0x6000, 0x6001, 0x6002
    FREESHIP = (K["FREESHIP_X"], K["FREESHIP_Y"])
    TCOPEN = 0x04
    #  A vehicle in a chest, from a placement where one landed in a chest.
    cfg = PLACE_CONFIGS["all-loose"]
    found = None
    for seed in range(1, 200):
        place = R.build_placement(seed, *cfg)
        table, _, _ = R.build_rewards(ROMDATA, seed, 0, place, cfg[1])
        for c in range(256):
            if table[c] in (0xF0, 0xF1, 0xF2, 0xF3) and c not in R.UNUSED_CHESTS:
                found = (seed, place, c, table[c])
                break
        if found:
            break
    check("a seed puts a vehicle in a chest", found is not None, True)
    if found:
        seed, place, chest, code = found
        bus, cpu = machine()
        s = bus.sram
        at = K["RANDO_SAVE"] - 0x6000
        s[at:at + 4] = seed.to_bytes(4, "little")
        s[K["RANDO_KEYITEMS"] - 0x6000] = cfg[0]
        s[K["RANDO_ITEMS"] - 0x6000:K["RANDO_ITEMS"] - 0x6000 + 3] = bytes(cfg[1])
        s[K["RANDO_EARLY"] - 0x6000] = cfg[3]
        s[K["RANDO_PLACED"] - 0x6000] = 1
        p = K["RANDO_PLACE"] - 0x6000
        s[p:p + K["PLACE_ITEMS"]] = bytes(place)
        s[SHIP_X - 0x6000], s[SHIP_Y - 0x6000] = 0xD2, 0x99        # Pravoka, as a new game has it
        bus.wram[K["tileprop"] + 1] = chest
        bus.wram[K["cur_map"]] = 8                                  # Coneria Castle 1F
        call(cpu, "OpenTreasureChest")
        vis = {0xF0: 0x6000, 0xF1: 0x6008, 0xF2: 0x600C, 0xF3: 0x6012}[code]
        name = {0xF0: 0x12, 0xF1: 0x13, 0xF2: 0x14, 0xF3: 0x11}[code]
        check("chest $%02X's vehicle $%02X: given, opened, fanfare, named, the found line" % (chest, code),
              (s[vis - 0x6000] if code != 0xF2 else 1 - s[vis - 0x6000],
               s[0x6200 - 0x6000 + chest] & TCOPEN, bus.wram[K["dlgsfx"]],
               bus.wram[K["dlg_itemid"]], cpu.a & 0xFF),
              (1, TCOPEN, 1, name, K["DLGID_TCGET"]))
        if code == 0xF0:
            check("...the ship moored at the castle's dock, Coneria's",
                  (s[SHIP_X - 0x6000], s[SHIP_Y - 0x6000]), FREESHIP)

    #  The NPCs: the cache's rewards, poked as deal_rewards would leave them.
    def npc(name, reward, setup=None):
        obj, _ = TALK_NPCS[name]
        bus, cpu = machine()
        s = bus.sram
        SLOT = 0x10
        s[0x6F00 - 0x6000 + SLOT] = obj
        s[GAME_FLAGS - 0x6000 + obj] = 1
        s[GAME_FLAGS - 0x6000 + 0x12] = 1            # the Princess rescued
        s[K["RANDO_TALK"] - 0x6000] = 1
        s[K["RANDO_PLACED"] - 0x6000] = 1
        bus.wram[rw("RW_TALKREW") + TALK_ENTRY[name]] = reward
        if setup:
            setup(s)
        cpu.x = SLOT
        call(cpu, "TalkToObject", bank=0xAF, dbr=0xAF)
        return bus, cpu, s
    bus, cpu, s = npc("King", 0x6E)                      # 25 G, one of the spare amounts
    check("the King's gold", (int.from_bytes(s[0x601C - 0x6000:0x601F - 0x6000], "little"),
                              bus.wram[TMP:TMP + 4] == bytes([0, 1, 2, 3])), (25, True))
    bus, cpu, s = npc("Princess", 0xF0, lambda s: s.__setitem__(SHIP_X - 0x6000, 0xD2))
    check("the Princess gives the ship, moored at Coneria's dock",
          (s[SHIP_VIS - 0x6000], s[SHIP_X - 0x6000], s[SHIP_Y - 0x6000]), (1,) + FREESHIP)
    bus, cpu, s = npc("CubeBot", 0x41)                   # a Katana
    check("CubeBot gives a Katana, in the first weapon slot",
          s[0x6118 - 0x6000], 0x41 - 0x1B)
    bus, cpu, s = npc("Fairy", 0x01, lambda s: s.__setitem__(ITEMS + 1 - 0x6000, 1))
    check("the Fairy gives a LUTE though one is held: no held test once placed",
          s[ITEMS + 1 - 0x6000], 2)

    #  Prices: every key item the BOTTLE's, the rest the table's.
    pb = (1 + 0x0D) * 0x10000 + 0xBC00
    price = lambda i: ROMDATA[pb + 2 * i] | ROMDATA[pb + 2 * i + 1] << 8
    got, want = [], []
    for item in list(range(0x00, 0x1C)) + [0x41, 0x6E, 0xAC]:
        bus, cpu = machine()
        cpu.a, cpu.x = item, 0x5A
        call(cpu, "LoadPrice")
        got.append((item, bus.wram[TMP] | bus.wram[TMP + 1] << 8, bus.wram[TMP + 2],
                    cpu.y & 0xFF, cpu.x & 0xFF))
        want.append((item, price(0x0F) if 0x01 <= item < 0x16 else price(item), 0, 1, 0x5A))
    check("LoadPrice: key items at the BOTTLE's price, X kept", got, want)

    #  The caravan, open with the fairy out.
    bus, cpu = machine()
    bus.sram[GAME_FLAGS - 0x6000 + 0x13] = 1             # the fairy out
    call(cpu, "rando_caravan", bank=RANDO_BANK)
    shut = cpu.a & 0xFF
    bus.sram[K["RANDO_PLACED"] - 0x6000] = 1
    call(cpu, "rando_caravan", bank=RANDO_BANK)
    check("the caravan: shut with the fairy out, open once placement stocks it",
          (shut != 0, cpu.a & 0xFF), (True, 0))


def test_rando_princess():
    """Rescuing the Princess teleports the party back to Coneria Castle, as in
    vanilla -- but not under entrance shuffle, where FFR drops the warp
    (Dialogues.cs): the castle need not be beside the Temple, and the logic
    never counted on it.  Either way she is hidden and her rescued self
    shown, and her line printed.  The game's own Talk_Princess1 is run, found
    in bank $0E by its bytes."""
    b0e = (1 + 0x0E) * 0x10000
    w, show = SYM["rando_princesswarp"], SYM["ShowMapObject"]
    jsl = bytes([0x22, w & 0xFF, w >> 8, RANDO_BANK, 0xEA])
    body = ROMDATA[b0e + 0x8000:b0e + 0xC000]
    at = [i for i in range(len(body) - 5) if body[i:i + 5] == jsl]
    check("bank $0E calls rando_princesswarp once, in five bytes", len(at), 1)
    if len(at) != 1:
        return
    start = 0x8000 + at[0] - 10
    check("...in Talk_Princess1: hide her, show her rescued self, then the warp",
          (bytes(body[at[0] - 10:at[0] - 8]), bytes(body[at[0] - 5:at[0]]), bytes(body[at[0] + 5:at[0] + 8])),
          (bytes([0xA0, K["OBJID_PRINCESS_1"]]), bytes([0xA0, K["OBJID_PRINCESS_2"], 0x20, show & 0xFF, show >> 8]),
           bytes([0xA5, K["tmp"] + 1, 0x60])))
    flags = K["game_flags"] - 0x6000
    P1, P2, VIS = K["OBJID_PRINCESS_1"], K["OBJID_PRINCESS_2"], K["GMFLG_OBJVISIBLE"]
    got = {}
    for mode in (R.ENTRANCES_OFF, R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS):
        bus, cpu = machine()
        bus.sram[K["RANDO_ENTRANCES"] - 0x6000] = mode
        bus.wram[K["tileprop"]], bus.wram[K["tileprop"] + 1] = 0x11, 0x22     # decoys
        bus.sram[flags + P1], bus.sram[flags + P2] = VIS, 0
        bus.wram[K["tmp"] + 1] = 0x5A                                         # her line
        cpu.x = 0x30                                                          # her map object
        bus.sram[K["mapobj_id"] - 0x6000 + 0x30] = P1
        cpu.dbr = BANK_0E
        cpu.run(BANK_0E, start)
        got[mode] = ((bus.wram[K["tileprop"]], bus.wram[K["tileprop"] + 1]),
                     (bus.sram[flags + P1] & VIS, bus.sram[flags + P2] & VIS,
                      bus.sram[K["mapobj_id"] - 0x6000 + 0x30], cpu.a & 0xFF))
    check("Off: the warp to Coneria Castle, as vanilla",
          got[R.ENTRANCES_OFF][0], (K["TP_TELE_NORM"], K["NORMTELE_SAVEDPRINCESS"]))
    check("entrance shuffle, either mode: no warp",
          [got[m][0] for m in (R.ENTRANCES_ONLY, R.ENTRANCES_FLOORS)], [(0x11, 0x22)] * 2)
    check("...and every mode rescues her and prints her line",
          {got[m][1] for m in got}, {(0, VIS, 0, 0x5A)})
    #  The hook alone keeps X and Y, as TalkNormTeleport did.
    bus, cpu = machine()
    cpu.x, cpu.y = 0x5A, 0xA5
    call(cpu, "rando_princesswarp", bank=RANDO_BANK)
    check("rando_princesswarp keeps X and Y", (cpu.x & 0xFF, cpu.y & 0xFF), (0x5A, 0xA5))


def test_rando_shipdock():
    """A ship found under placement is moored at the dock nearest the map it
    was found on, of those the party can reach from there without it
    (lut_ShipDock; genlogic.py proves each reached, and on the inner sea).
    Held to FFR's ShipLocations (FF1Lib/maps/default.json, by overworld
    entrance) wherever FFR names a dock, Ice Cave to Pravoka among them; the
    Temple of Fiends Revisited to Coneria's, since nothing there can hold the
    ship; every map to one of FFR's five; and without placement, untouched.
    With map edits, whose logic is the seed's (pl_edited), the dock New Game
    chose, whatever the map, as under entrance shuffle -- and a dock 4 under
    Bridge to Lefein, whose edits delete Matoya's, Coneria's, as FFR's
    UpdateDocks has it.  Under Ship in Drydock, Gaia's drydock, on every map,
    placed or not."""
    SHIP_VIS, SHIP_X, SHIP_Y = 0x6000, 0x6001, 0x6002
    CONERIA, PRAVOKA, ELFLAND = (152, 169), (210, 153), (141, 211)
    DWARF, MATOYA = (121, 139), (158, 142)
    FFR = {1: PRAVOKA,                              # Pravoka (entrance 2)
           15: PRAVOKA, 37: PRAVOKA, 38: PRAVOKA,   # Ice Cave B1-B3 (16)
           9: ELFLAND, 10: ELFLAND,                 # Elfland and Northwest Castles (10, 11)
           27: ELFLAND, 28: ELFLAND,                # Marsh Cave B2, B3 (23)
           4: ELFLAND,                              # Crescent Lake (5)
           33: ELFLAND, 35: ELFLAND, 36: ELFLAND,   # Gurgu Volcano B2, B4, B5 (15)
           19: DWARF,                               # the Dwarf Cave (20)
           20: MATOYA,                              # Matoya's Cave (21)
           8: CONERIA, 24: CONERIA, 12: CONERIA}    # Coneria Castle, the Temple: FFR's default

    def give(m, placed=1, edits=0, dock=0):
        bus, cpu = machine()
        s = bus.sram
        s[K["RANDO_PLACED"] - 0x6000] = placed
        s[K["RANDO_SHIPDOCK"] - 0x6000] = dock
        s[K["RANDO_OWEDITS"] - 0x6000:K["RANDO_OWEDITS"] - 0x6000 + 2] = edits.to_bytes(2, "little")
        s[SHIP_X - 0x6000], s[SHIP_Y - 0x6000] = 0x11, 0x22      # decoys
        bus.wram[K["cur_map"]] = m
        cpu.a, cpu.x = 0xF0, 0x5A                               # REWARD_SHIP
        call(cpu, "give_vehicle", bank=RANDO_BANK)
        return ((s[SHIP_X - 0x6000], s[SHIP_Y - 0x6000]), s[SHIP_VIS - 0x6000],
                cpu.a & 0xFF, cpu.x & 0xFF)

    docks = {CONERIA, PRAVOKA, ELFLAND, DWARF, MATOYA}
    got = {m: give(m) for m in range(61)}
    check("FFR's docks, map by map", {m: got[m][0] for m in FFR}, FFR)
    check("the Temple of Fiends Revisited: Coneria's",
          {got[m][0] for m in range(52, 60)}, {CONERIA})
    check("every map one of the five docks", [m for m in got if got[m][0] not in docks], [])
    check("given, named SHIP, X kept, on every map",
          {got[m][1:] for m in got}, {(1, 0x12, 0x5A)})
    check("unplaced: the ship left where it is", give(15, placed=0)[:2], ((0x11, 0x22), 1))
    #  Under entrance shuffle, the dock New Game chose (es_dock), whatever the map.
    def shuffled(m, dock, edits=0):
        bus, cpu = machine()
        s = bus.sram
        s[K["RANDO_PLACED"] - 0x6000] = 1
        s[K["RANDO_OWEDITS"] - 0x6000:K["RANDO_OWEDITS"] - 0x6000 + 2] = edits.to_bytes(2, "little")
        s[K["RANDO_ENTRANCES"] - 0x6000] = R.ENTRANCES_ONLY
        s[K["RANDO_SHIPDOCK"] - 0x6000] = dock
        bus.wram[K["cur_map"]] = m
        cpu.a, cpu.x = 0xF0, 0x5A
        call(cpu, "give_vehicle", bank=RANDO_BANK)
        return (s[SHIP_X - 0x6000], s[SHIP_Y - 0x6000]), cpu.x & 0xFF
    order = [CONERIA, PRAVOKA, ELFLAND, DWARF, MATOYA]
    check("entrance shuffle: the save's dock", [shuffled(m, d) for d, m in enumerate((15, 1, 20, 4, 8))],
          [(order[d], 0x5A) for d in range(5)])
    #  Map edits: the save's dock.  Bridge to Lefein: Matoya's is gone.
    BRIDGE, DRY = K["OWEDIT_BRIDGELEFEIN"], K["OWEDIT_DRYDOCK"]
    others = 0xFFFF & ~BRIDGE & ~DRY
    matoya = [m for m in got if got[m][0] == MATOYA]
    check("Matoya's dock: Matoya's Cave's alone", matoya, [20])
    check("map edits: the save's dock, whatever the map",
          [give(m, edits=others, dock=d)[0] for d, m in enumerate((15, 1, 20, 4, 8))], order)
    check("...Bridge to Lefein: dock 4 is Coneria's, the rest their own",
          [give(m, edits=BRIDGE, dock=d)[0] for d, m in enumerate((15, 1, 20, 4, 8))],
          [order[d] if d != 4 else CONERIA for d in range(5)])
    check("entrance shuffle, Bridge to Lefein: dock 4 is Coneria's, the rest their own",
          [shuffled(m, d, edits=BRIDGE) for d, m in enumerate((15, 1, 20, 4, 8))],
          [(order[d] if d != 4 else CONERIA, 0x5A) for d in range(5)])
    check("entrance shuffle, every other edit: Matoya's still",
          shuffled(8, 4, edits=others), (MATOYA, 0x5A))
    DRYDOCK = (211, 31)
    check("Ship in Drydock: Gaia's, on every map, placed or not, shuffled or not",
          {give(m, edits=DRY, dock=2)[0] for m in range(61)} | {give(15, placed=0, edits=DRY)[0]} |
          {shuffled(8, 2, edits=DRY)[0]} | {give(20, edits=0xFFFF)[0]}, {DRYDOCK})


def ff_decode(body):
    """The game's text as a string: the glyphs back to letters, a line break
    as a newline, the item name ($02) as '#', the way FFR's lines write it."""
    out = []
    for b in body:
        if b == 0x02:
            out.append("#")
        elif b < 0x1A:
            out.append("\n")
        elif b == 0xFF:
            out.append(" ")
        elif 0x80 <= b <= 0x89:
            out.append(chr(ord("0") + b - 0x80))
        elif 0x8A <= b <= 0xA3:
            out.append(chr(ord("A") + b - 0x8A))
        elif 0xA4 <= b <= 0xBD:
            out.append(chr(ord("a") + b - 0xA4))
        else:
            out.append({0xBE: "'", 0xBF: ",", 0xC0: ".", 0xC2: "-", 0xC4: "!",
                        0xC5: "?"}.get(b, "<%02X>" % b))
    return "".join(out)


def test_rando_dialogue():
    """With placement in, a reward NPC's giving line names what it gave.
    rando_talk arms RW_DLGNPC and names the reward in dlg_itemid; the next
    string drawn is that line, and rando_dlgtext, at the drawer's
    DrawDialogueString_PtrLoaded, builds the NPC's own line in OPTDESC and
    spends the flag.  The King and the Sage have FFR's other line under their
    Early flags; Sarda, whose FFR line is one, does not.  Nothing is armed
    without placement, or when the gift does not fit."""
    OPTDESC_A = K["OPTDESC"]
    DLGNPC = rw("RW_DLGNPC")
    EARLY = K["RANDO_EARLY"] - 0x6000
    #  A phrase only that NPC's line has, to tell the lines apart.
    WORDS = ["saving the\nPrincess", "Queens of Coneria", "you got me",
             "LIGHT\nWARRIORS", "I am Astos", "My CRYSTAL", "TNT is just",
             "ADAMANT!!", "earth's rot", "Earth FIEND", None, "BOTTLE",
             "SKY WARRIORS"]
    EARLY_WORDS = {0: (K["EARLY_KING"], "To aid you"),
                   9: (K["EARLY_SAGE"], "FIENDS are waking")}
    BOX_COLS, BOX_LINES, NAME_MAX = 24, 6, 8      # FFR's own lines' limits

    #  The hook: at the label, so the dialogue's two pointer lookups and Chest
    #  Information's direct entry all pass it.
    at = SYM["DrawDialogueString_PtrLoaded"]
    want = SYM["rando_dlgtext"]
    check("DrawDialogueString_PtrLoaded begins JSL rando_dlgtext",
          [chunkbyte(0x0F, at + i) for i in range(4)],
          [0x22, want & 0xFF, want >> 8, RANDO_BANK])

    def line(entry, early):
        bus, cpu = machine()
        bus.wram[DLGNPC] = entry + 1
        bus.sram[EARLY] = early
        bus.sram[OPTDESC_A - 0x6000:OPTDESC_A - 0x6000 + 0x50] = bytes([0xEE]) * 0x50
        bus.wram[TEXT_PTR], bus.wram[TEXT_PTR + 1] = 0xAA, 0xAA
        cpu.y = 0x5A
        dbr = cpu.dbr
        call(cpu, "rando_dlgtext", bank=RANDO_BANK)
        buf = bytes(bus.sram[OPTDESC_A - 0x6000:OPTDESC_A - 0x6000 + 0x50])
        end = buf.find(0)
        ptr = bus.wram[TEXT_PTR] | bus.wram[TEXT_PTR + 1] << 8
        kept = (bus.wram[DLGNPC], ptr, cpu.y & 0xFF, cpu.dbr == dbr)
        return (ff_decode(buf[:end]) if end >= 0 else None), kept

    allbits = K["EARLY_KING"] | K["EARLY_SARDA"] | K["EARLY_SAGE"] | K["EARLY_ORDEALS"]
    seen = set()
    for entry in range(13):
        for early in sorted({0, allbits} | {b for b, _ in EARLY_WORDS.values()}):
            text, kept = line(entry, early)
            name = "entry %d, Early $%02X" % (entry, early)
            check(name + ": flag spent, OPTDESC drawn, Y and DBR kept",
                  kept, (0, OPTDESC_A, 0x5A, True))
            if text is None:
                fails.append(name + ": no terminator within OPTDESC")
                continue
            flag, eword = EARLY_WORDS.get(entry, (0, None))
            word = eword if early & flag else WORDS[entry]
            if word is None:
                check(name + ": the line", text, "Take this.\n\nReceived #")
            else:
                check(name + ": its own line (%r)" % word, word in text, True)
            check(name + ": names the gift once", text.count("#"), 1)
            if entry != TALK_ENTRY["Astos"]:
                check(name + ": ends Received #", text.endswith("\n\nReceived #"), True)
            rows = text.split("\n")
            wide = max(len(r.replace("#", "")) + NAME_MAX * r.count("#") for r in rows)
            check(name + ": fits the box", (len(rows) <= BOX_LINES, wide <= BOX_COLS),
                  (True, True))
            seen.add(text)
    #  Thirteen lines and two Early ones, all different.
    check("fifteen different lines", len(seen), 15)

    #  Unarmed: nothing touched.
    bus, cpu = machine()
    bus.sram[OPTDESC_A - 0x6000] = 0xEE
    bus.wram[TEXT_PTR], bus.wram[TEXT_PTR + 1] = 0xAA, 0xAA
    call(cpu, "rando_dlgtext", bank=RANDO_BANK)
    check("unarmed: text_ptr and OPTDESC untouched",
          (bus.wram[TEXT_PTR], bus.wram[TEXT_PTR + 1], bus.sram[OPTDESC_A - 0x6000]),
          (0xAA, 0xAA, 0xEE))

    #  Arming, through TalkToObject.
    def talk(name, reward, placed=1, setup=None):
        obj, _ = TALK_NPCS[name]
        bus, cpu = machine()
        s = bus.sram
        SLOT = 0x10
        s[0x6F00 - 0x6000 + SLOT] = obj
        s[GAME_FLAGS - 0x6000 + obj] = 1
        s[GAME_FLAGS - 0x6000 + 0x12] = 1            # the Princess rescued
        s[K["RANDO_TALK"] - 0x6000] = 1
        s[K["RANDO_PLACED"] - 0x6000] = placed
        bus.wram[rw("RW_TALKREW") + TALK_ENTRY[name]] = reward
        if setup:
            setup(s)
        cpu.x = SLOT
        call(cpu, "TalkToObject", bank=0xAF, dbr=0xAF)
        return bus, cpu
    bus, cpu = talk("King", 0x6E)
    check("the King, placed: armed, the gold named",
          (bus.wram[DLGNPC], bus.wram[K["dlg_itemid"]]), (TALK_ENTRY["King"] + 1, 0x6E))
    call(cpu, "rando_dlgtext", bank=RANDO_BANK)
    buf = bytes(bus.sram[OPTDESC_A - 0x6000:OPTDESC_A - 0x6000 + 0x50])
    check("...and the line drawn is his", WORDS[0] in ff_decode(buf[:buf.find(0)]), True)
    bus, cpu = talk("Princess", 0xF0)
    check("the Princess, placed, the ship: armed, named as SHIP",
          (bus.wram[DLGNPC], bus.wram[K["dlg_itemid"]]), (TALK_ENTRY["Princess"] + 1, 0x12))
    bus, cpu = talk("King", 0x6E, placed=0)
    check("the King, unplaced: not armed", bus.wram[DLGNPC], 0)
    def full(s):                                    # four weapons each
        for c in range(4):
            s[0x6118 + 0x40 * c - 0x6000:0x611C + 0x40 * c - 0x6000] = bytes([1]) * 4
    bus, cpu = talk("CubeBot", 0x41, setup=full)
    check("CubeBot, a Katana, no room: not armed, can't carry",
          (bus.wram[DLGNPC], cpu.a & 0xFF), (0, DLGID_CANTCARRY))


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
def kraken_turn(base, rngstate):
    """Enemy_DoAi, run on a copy of base from one battle RNG state to where
    the turn is decided: ("hit", party slot, attacker) at
    EnemyAttackPlayer_Physical, or ("magic", attack) at Enemy_DoMagicEffect."""
    bus = Bus(ROMDATA)
    bus.wram[:], bus.sram[:] = base.wram, base.sram
    bus.sram[BTL_RNGSTATE - 0x6000] = rngstate
    cpu = CPU(bus)
    cpu.dbr = BANK_0C
    cpu.pbr, cpu.pc = BANK_0C, SYM["Enemy_DoAi"]
    cpu.push(0xFF); cpu.push(0xFD)
    for _ in range(20000):
        if cpu.pbr == BANK_0C and cpu.pc == SYM["EnemyAttackPlayer_Physical"]:
            return ("hit", cpu.a & 0x03, cpu.x & 0xFF)
        if cpu.pbr == BANK_0C and cpu.pc == SYM["Enemy_DoMagicEffect"]:
            return ("magic", cpu.a & 0xFF)
        cpu.step()
    return ("lost", cpu.pbr, cpu.pc)


def test_kraken():
    """Asshat Octopus: Kraken and Kraken 2 spend every turn on a White Mage or
    White Wizard while one can be hit -- the melee attack, no INK, no LIT2.
    The real Enemy_DoAi, from all 256 battle RNG states, to where the turn is
    decided.  Off, and on with nothing to hit, the turn is the enemy's own,
    roll for roll; the control shows that is not always the melee.  With two
    to choose from, the pick is GetRandomPlayerTarget's weighting, modelled
    here from its comments, rerolled until it lands on one."""
    KRAKEN, KRAKEN2 = 0x7B, 0x7C
    FI, TH, BB, RM, WM, BM = 0, 1, 2, 3, 4, 5
    WW, NONE = 10, 0xFF
    ATTACKER, DEAD, STONE, CLASS = 0x6C89, 0x6AD1, 0x6AD2, 0x6100
    for e, hp in ((KRAKEN, 800), (KRAKEN2, 900)):
        st = ROMDATA[ENEMIES_ROM + e * 20:][:20]
        check("enemy $%02X is a Kraken: its HP and eight hits" % e,
              (st[4] | st[5] << 8, st[10]), (hp, 8))

    def base(enemy, party, on=True, dead=0, stone=0):
        bus, cpu = machine()
        setsave(bus, 1, 0)
        call(cpu, "rando_ensure", bank=RANDO_BANK)  # the battle RNG table
        setblk(bus, OPT_FLAGS + 5, 0x08 if on else 0)
        for n, c in enumerate(party):
            bus.sram[CLASS + 0x40 * n - 0x6000] = c
        bus.sram[DEAD - 0x6000], bus.sram[STONE - 0x6000] = dead, stone
        enram(bus, enemy, 2)
        bus.sram[ATTACKER - 0x6000] = 2
        return bus

    def turns(*a, **k):
        b = base(*a, **k)
        return [kraken_turn(b, s) for s in range(256)]

    party = (FI, WM, BM, TH)
    for e in (KRAKEN, KRAKEN2):
        own = turns(e, party, on=False)
        check("$%02X, flag off: its own turns, INK among them" % e,
              (sum(t[0] == "magic" for t in own) > 0, sum(t[0] == "hit" for t in own) > 0),
              (True, True))
        check("$%02X, flag off: no turn lost" % e,
              [t for t in own if t[0] not in ("hit", "magic")][:1], [])
        check("$%02X: the White Mage, every turn, by this enemy" % e,
              set(turns(e, party)), {("hit", 1, 2)})
        check("$%02X: a White Wizard in the last slot" % e,
              set(turns(e, (FI, TH, BB, WW))), {("hit", 3, 2)})
        #  Nothing to hit: the enemy's own turn, the RNG untouched.
        for name, kw in (("dead", dict(dead=0x02)), ("stone", dict(stone=0x02))):
            check("$%02X: the White Mage %s, its own turns" % (e, name),
                  turns(e, party, **kw), turns(e, party, on=False, **kw))
        check("$%02X: no white mage, its own turns" % e,
              turns(e, (FI, TH, BB, RM)), turns(e, (FI, TH, BB, RM), on=False))
    #  Only these two.
    for e in (0x7A, 0x7D, 0x7F, 0x00):
        check("enemy $%02X: its own turns" % e,
              turns(e, party), turns(e, party, on=False))
    #  Only these two classes; the None is not one.
    bad = [c for c in [c for c in range(12) if c not in (WM, WW)] + [NONE]
           if turns(KRAKEN, (FI, TH, c, BB)) != turns(KRAKEN, (FI, TH, c, BB), on=False)]
    check("no other class is a white mage", bad, [])

    #  Two of them, slots 0 and 2, and one of them stone: the pick is the
    #  game's weighting over the cartridge's table, rerolled past the rest.
    b = base(KRAKEN, (WM, FI, WW, TH))
    rng = bytes(b.wram[rw("RW_BATRNG"):rw("RW_BATRNG") + 256])
    bucket = lambda r: 0 if r >= 0x80 else 1 if r >= 0x40 else 2 if r >= 0x20 else 3
    def model(s, ok):
        while bucket(rng[s & 0xFF]) not in ok:
            s += 1
        return ("hit", bucket(rng[s & 0xFF]), 2)
    got = [kraken_turn(b, s) for s in range(256)]
    check("two: the game's weighting, rerolled past the others",
          got, [model(s, (0, 2)) for s in range(256)])
    check("...and both are picked", {t[1] for t in got}, {0, 2})
    b = base(KRAKEN, (WM, FI, WW, TH), stone=0x01)
    check("two, the first stone: always the other",
          set(kraken_turn(b, s) for s in range(256)), {("hit", 2, 2)})

# --- Boss tactics ------------------------------------------------------------
#  tools/tacref.py is the reckoning; these hold the cart to it, and it to the
#  game's own routines where it reads them.
import tacref as TR

TAC_OB, TAC_IB, TAC_DRAWN = 0x6100, 0x6800, 0x6AD1
TAC_SPELLS, TAC_MP = 0x6300, 0x6320
STAT_100 = 3
TAC_ENEMYSLOT = 2


def tac_roll(B, die):
    """RandAX(0, B) + B, at most 255: its range is B + 1 in a byte, so B 255
    rolls 0."""
    return min(255, B + ((die * ((B + 1) & 0xFF)) >> 8))


def tac_swing_die(H, C, B, ab, rdie, ddie):
    """One hit's damage from its two dice, as the hit loop reads them."""
    r = (rdie * 201) >> 8
    if r == 200 or r > H:
        return 0
    d = tac_roll(B, ddie)
    return max(1, d - ab) + (d if r <= C else 0)


def tac_rng(bus, table, state):
    at = rw("RW_BATRNG")
    bus.wram[at:at + 256] = bytes(table)
    bus.sram[BTL_RNGSTATE - 0x6000] = state


def tac_dial(bus, mode, other=0):
    setblk(bus, OPT_FLAGS + 5, (mode << 5) | other)


def tac_junk(bus):
    """The scratch as a console might leave it: nothing is cleared at power
    on, so a decision must not lean on a zero it did not write."""
    bus.wram[rw("TC_BASE"):rw("TC_END")] = bytes((0xA5 + 7 * i) & 0xFF for i in range(rw("TC_END") - rw("TC_BASE")))


def tac_w(bus, name, i=0, size=2):
    at = rw(name) + i
    return int.from_bytes(bus.wram[at:at + size], "little")


_tac_base = []


def tac_base():
    """A machine with the randomizer's cache built (the battle's dice, the
    enemies' scripts and touches), every stat at 100%."""
    if not _tac_base:
        bus, cpu = machine()
        setsave(bus, 1, 0)
        call(cpu, "rando_ensure", bank=RANDO_BANK)
        setblk(bus, OPT_ENEMY, STAT_100)
        setblk(bus, OPT_BOSS, STAT_100)
        _tac_base.append((bytes(bus.wram), bytes(bus.sram)))
    bus = Bus(ROMDATA)
    bus.wram[:], bus.sram[:] = _tac_base[0]
    return bus


def tac_rec_of(bus):
    """The record each attack id is cast with, asked of the cart's own rule
    (spells) and the ROM (skills; TRANCE's element by its flag)."""
    cache = {}
    magic = (1 + 0x0C) * 0x10000 + SYM["lut_MagicData"]
    trance = blk(bus, OPT_FLAGS + 5) & 0x01

    def rec(aid):
        if aid not in cache:
            if aid < 0x40:
                v = []
                for y in range(5):
                    cpu = CPU(bus)
                    cpu.x, cpu.y = aid, y
                    call(cpu, "opt_spellbytefar", bank=CHUNK_OPT_BANK, dbr=BANK_0C)
                    v.append(cpu.a & 0xFF)
            else:
                v = list(ROMDATA[magic + aid * 8:][:5])
                if aid == 0x51 and trance:
                    v[2] = 0x01
            cache[aid] = v
        return cache[aid]
    return rec


def tac_write_party(bus, party):
    dead = stone = 0
    for n, m in enumerate(party):
        ob, ib = TAC_OB + 0x40 * n - 0x6000, TAC_IB + 0x12 * n - 0x6000
        bus.sram[ob], bus.sram[ob + 1] = m.cls, m.ail
        bus.sram[ob + 0x0A:ob + 0x0C] = m.hp.to_bytes(2, "little")
        bus.sram[ob + 0x0C:ob + 0x0E] = m.maxhp.to_bytes(2, "little")
        for off, v in ((5, m.hitrate), (6, m.magdef), (7, m.evade), (8, m.absorb), (9, m.dmg), (0x0A, m.res),
                       (0x0B, m.mult), (0x0C, m.numhits), (0x0D, m.wcat), (0x0E, m.welem), (0x0F, m.crit)):
            bus.sram[ib + off] = v
        sp = TAC_SPELLS + 0x40 * n - 0x6000
        bus.sram[sp:sp + 32] = bytes(m.spells)
        bus.sram[sp + 0x20:sp + 0x28] = bytes(m.mp)
        dead |= (1 << n) if m.ail & 0x01 else 0
        stone |= (1 << n) if m.ail & 0x02 else 0
    bus.sram[TAC_DRAWN - 0x6000], bus.sram[TAC_DRAWN + 1 - 0x6000] = dead, stone


def tac_write_boss(bus, enemy, hp, ail=0, evade=None, absorb=None, mult=1, strength=None):
    """The enemy in battle slot 2, its RAM stats from its ROM record unless
    given; ($9A) at them, ($84) too."""
    rom = ROMDATA[ENEMIES_ROM + enemy * 20:][:20]
    at = K["btl_enemystats"] + TAC_ENEMYSLOT * 0x14 - 0x6000
    ptr = 0x8520 + enemy * 20
    bus.sram[at:at + 2] = ptr.to_bytes(2, "little")
    bus.sram[at + K["en_hp"]:at + K["en_hp"] + 2] = hp.to_bytes(2, "little")
    bus.sram[at + K["en_ailments"]] = ail
    bus.sram[at + K["en_evade"]] = rom[8] if evade is None else evade
    bus.sram[at + K["en_defense"]] = rom[9] if absorb is None else absorb
    bus.sram[at + K["en_numhitsmult"]] = mult
    bus.sram[at + K["en_strength"]] = rom[12] if strength is None else strength
    bus.sram[at + K["en_enemyid"]] = enemy
    ram = K["btl_enemystats"] + TAC_ENEMYSLOT * 0x14
    for zp in (0x9A, 0x84):
        bus.wram[zp], bus.wram[zp + 1] = ram & 0xFF, ram >> 8
    bus.wram[0x9C], bus.wram[0x9D] = ptr & 0xFF, ptr >> 8
    bus.sram[K["btl_attacker"] - 0x6000] = TAC_ENEMYSLOT


def tac_boss_of(bus, enemy):
    """The reference's Boss, from what the cart gathered: its RAM and ROM
    stats, and the swing as opt_scaleatk scaled it."""
    rom = ROMDATA[ENEMIES_ROM + enemy * 20:][:20]
    at = K["btl_enemystats"] + TAC_ENEMYSLOT * 0x14 - 0x6000
    s = bus.sram
    return TR.Boss(hp=s[at + 2] | s[at + 3] << 8, maxhp=rom[4] | rom[5] << 8, ail=s[at + K["en_ailments"]],
                   mult=s[at + K["en_numhitsmult"]], strength=s[at + K["en_strength"]],
                   hitrate=tac_w(bus, "TC_HR"), numhits=tac_w(bus, "TC_BNH"), crit=tac_w(bus, "TC_CR"),
                   evade=s[at + K["en_evade"]], absorb=s[at + K["en_defense"]], magdef=rom[0x11],
                   cat=rom[0x10], weak=rom[0x12], res=rom[0x13])


def tac_run(bus, entry="tac_turn"):
    """tac_turn from Enemy_DoAi's hook, to where it ends: ("swing", slot),
    ("magic", attack id), or ("script",) if it came back."""
    cpu = CPU(bus)
    cpu.dbr = BANK_0C
    cpu.pbr, cpu.pc = TACTICS_BANK, SYM[entry]
    cpu.push(BANK_0C); cpu.push(0xFF); cpu.push(0xFD)
    phys, magic = SYM["EnemyAttackPlayer_Physical"], SYM["Enemy_DoMagicEffect"]
    for _ in range(3_000_000):
        if cpu.pbr == BANK_0C:
            if cpu.pc == phys:
                return ("swing", cpu.a & 0xFF, cpu.x & 0xFF), cpu
            if cpu.pc == magic:
                return ("magic", cpu.a & 0xFF), cpu
            if cpu.pc == 0xFFFE:
                return ("script",), cpu
        cpu.step()
    return ("lost", cpu.pbr, cpu.pc), cpu


def tac_script_bytes(magic_rate, skill_rate, spells, skills):
    s = [magic_rate, skill_rate] + list(spells) + [0xFF] * (8 - len(spells)) + [0xFF]
    s += list(skills) + [0xFF] * (4 - len(skills)) + [0xFF]
    return s


def tac_setup(party, enemy, hp, script, mode, state, ail=0, mult=1, flags5=0, elemdmg=4, deck=(0, 0), **boss):
    bus = tac_base()
    tac_junk(bus)
    tac_dial(bus, mode, flags5)
    setblk(bus, K["OPTD_ELEMDMG"] - OPTBLOCK, elemdmg)
    tac_write_party(bus, party)
    tac_write_boss(bus, enemy, hp, ail=ail, mult=mult, **boss)
    en = K["btl_enemystats"] + TAC_ENEMYSLOT * 0x14 - 0x6000
    bus.sram[en + K["en_aimagpos"]], bus.sram[en + K["en_aiatkpos"]] = deck
    at = K["OPTAISHADOW"] - 0x6000
    bus.sram[at:at + 16] = bytes(script)
    bus.wram[0x9E], bus.wram[0x9F] = K["OPTAISHADOW"] & 0xFF, K["OPTAISHADOW"] >> 8
    bus.sram[BTL_RNGSTATE - 0x6000] = state
    return bus


def tac_compare(bus, party, enemy, script, mode, state, where):
    """Run tac_turn on bus and hold every intermediate to the reference.
    Out: a list of what disagreed, and the reference's Mind."""
    table = bytes(bus.wram[rw("RW_BATRNG"):rw("RW_BATRNG") + 256])
    rec = tac_rec_of(bus)
    elemdmg = blk(bus, K["OPTD_ELEMDMG"] - OPTBLOCK)
    wmharm = bool(blk(bus, K["OPTFB_WMHARM"] - OPTBLOCK) & K["OPTFM_WMHARM"])
    borrowed = bytes(bus.sram[0x686C - 0x6000:0x6874 - 0x6000]) + bytes(bus.wram[0x84:0x86])
    en = K["btl_enemystats"] + TAC_ENEMYSLOT * 0x14 - 0x6000
    deck = (bus.sram[en + K["en_aimagpos"]], bus.sram[en + K["en_aiatkpos"]])
    got, cpu = tac_run(bus)
    if bytes(bus.sram[0x686C - 0x6000:0x6874 - 0x6000]) + bytes(bus.wram[0x84:0x86]) != borrowed:
        bad = ["%s: the attacker's bytes or $84 not put back" % where]
    else:
        bad = []
    boss = tac_boss_of(bus, enemy)
    flat = list(script[0:2]) + list(script[2:10]) + list(script[11:15])
    M = TR.Mind(party, boss, flat, rec, elemdmg, wmharm, deck)
    words = lambda name, n=4: [tac_w(bus, name, 2 * i) for i in range(n)]
    for name, want in (("TC_PHYS", M.phys), ("TC_PDARK", M.pdark), ("TC_PSLOW", M.pslow), ("TC_MAG", M.mag),
                       ("TC_HEAL", M.heal), ("TC_D", M.d), ("TC_KG", M.KG), ("TC_DG", M.DG)):
        if words(name) != want:
            bad.append("%s %s: %s, want %s" % (where, name, words(name), want))
    for name, want in (("TC_DP", M.Dp), ("TC_RB", M.Rb), ("TC_DB", M.Db), ("TC_HPP16", M.hpp16)):
        if tac_w(bus, name) != want:
            bad.append("%s %s: %d, want %d" % (where, name, tac_w(bus, name), want))
    live = [i for i in range(4) if M.alive[i]]
    sem = [tac_w(bus, "TC_SEM", 2 * i) for i in live], [tac_w(bus, "TC_SPK", 2 * i) for i in live]
    if sem != ([M.swings[i][0] for i in live], [M.swings[i][1] for i in live]):
        bad.append("%s swings: %s, want %s" % (where, sem, [M.swings[i] for i in live]))
    n = tac_w(bus, "TC_NCAND")
    ids = [tac_w(bus, "TC_CID", 2 * k) for k in range(n)]
    want_ids = [0xFFFF if a is None else a for a, _ in M.cands]
    if ids != want_ids:
        bad.append("%s candidates: %s, want %s" % (where, ids, want_ids))
    else:
        vals = [(tac_w(bus, "TC_CVAL", 2 * k), tac_w(bus, "TC_CTGT", 2 * k)) for k in range(n)]
        want_vals = [(v, 0xFFFF if t is None else t) for v, t in M.value]
        if vals != want_vals:
            bad.append("%s worth: %s, want %s" % (where, vals, want_vals))
    aid, tgt, used = M.choose(mode, [table[state & 0xFF], table[(state + 1) & 0xFF]])
    want = ("swing", tgt, TAC_ENEMYSLOT) if aid is None else ("magic", aid)
    after = bus.sram[BTL_RNGSTATE - 0x6000]
    if (got, after) != (want, (state + used) & 0xFF):
        bad.append("%s chose %s (dice to %d), want %s (dice to %d)" % (where, got, after, want, (state + used) & 0xFF))
    left = (bus.sram[en + K["en_aimagpos"]], bus.sram[en + K["en_aiatkpos"]])
    if got[0] in ("swing", "magic") and left != M.after(aid):
        bad.append("%s deck %s after %s, want %s" % (where, left, got, M.after(aid)))
    if (got, after) != (want, (state + used) & 0xFF):
        pass
    elif tgt is not None and aid is not None or aid is None:
        latch = bytes(bus.wram[rw("TC_LATCH"):rw("TC_LATCH") + 3])
        if tgt is not None and latch != bytes([0xA0 | tgt, (0xA0 | tgt) ^ 0xFF, TAC_ENEMYSLOT]):
            bad.append("%s latch %s for %s" % (where, latch.hex(), got))
    return bad, M


def tac_party_draw(rnd, n_casters=None):
    out = []
    for k in range(4):
        cls = rnd.choice((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))
        ail = rnd.choice((0, 0, 0, 0, 0x08, 0x10, 0x20, 0x40, 0x04, 0x01, 0x02, 0x30, 0x80))
        maxhp = rnd.choice((rnd.randrange(30, 120), rnd.randrange(100, 1000), rnd.randrange(280, 330)))
        hp = 0 if ail & 0x01 else rnd.randrange(1, maxhp + 1)
        spells = [0] * 32
        mp = [0] * 8
        if rnd.random() < 0.6:
            for lv in range(8):
                for sl in range(4):
                    if rnd.random() < 0.35:
                        spells[lv * 4 + sl] = rnd.randrange(1, 65)
                mp[lv] = rnd.choice((0, 0, 1, 3, 9))
        out.append(TR.Member(cls=cls, ail=ail, hp=hp, maxhp=maxhp, dmg=rnd.choice((5, 20, 45, 80, 140, 200, 255)),
                             hitrate=rnd.choice((0, 10, 48, 100, 180)), numhits=rnd.choice((1, 2, 4, 8)),
                             mult=rnd.choice((0, 1, 1, 2)), crit=rnd.choice((0, 1, 10, 50, 200)),
                             evade=rnd.choice((0, 20, 48, 100, 200)), absorb=rnd.choice((0, 5, 20, 60, 120, 255)),
                             magdef=rnd.choice((0, 30, 80, 150, 255)), res=rnd.choice((0, 0, 0x10, 0x20, 0xFF, 0x01)),
                             wcat=rnd.choice((0, 0, 0x08, 0xFF)), welem=rnd.choice((0, 0, 0x10, 0x20)),
                             spells=spells, mp=mp))
    if not any(m.alive for m in out):
        out[0].ail, out[0].hp = 0, max(1, out[0].maxhp)
    return out


TAC_BOSSES = (15, 105, 113) + tuple(range(118, 128))


def test_bosstactics():
    """Boss tactics: a boss weighs every action it has and takes the best.

    First the game's own rules, as the reckoning reads them: one swing
    through the real hit loop for chosen dice; each spell effect through the
    real BtlMag_Effect_* for every roll.  Then tac_turn against tacref.py,
    every intermediate -- threat, the race, kill and disable worth, each
    candidate's worth and aim, the choice and the dice it used -- over drawn
    parties with spell lists and MP, against the bosses' own records with
    drawn scripts; Enemy_DoAi itself, in place, for each boss; the hooks;
    cases a player knows; the music yielding; the dial."""
    rnd = random.Random(0xB055)
    img = BANK_0C & 0x1F
    lo = img * 0x10000 + 0x8000
    bank = bytes(ROMDATA[lo:lo + 0x8000])
    for name in ("tac_turn", "tac_swing", "tac_cast"):
        check("%s is called once" % name, jsl_count(img, name, TACTICS_BANK), 1)
    check("the bosses are opt_isboss's: one list",
          jsl_count(TACTICS_BANK & 0x1F, "opt_isbossfar", CHUNK_OPT_BANK), 1)
    gen = {"lut_TacHits": (TR.HITS, 1), "lut_TacQ": (TR.TQ, 2), "lut_TacL": (TR.TL, 2),
           "lut_TacSleep": (TR.SLEEP, 2)}
    for name, (want, size) in gen.items():
        at = (TACTICS_BANK & 0x1F) * 0x10000 + SYM[name]
        got = [int.from_bytes(ROMDATA[at + size * i:at + size * i + size], "little") for i in range(len(want))]
        check("%s is gentactics.py's" % name, got, want)
    check("lut_TacHits counts the dice", TR.HITS, [sum(1 for b in range(256) if (b * 201) >> 8 <= h
                                                        and (b * 201) >> 8 != 200) for h in range(199)])
    check("the dice's shares in closed form",
          [sum((d * k) >> 8 for d in range(256)) for k in range(256)], [TR.F(k) for k in range(256)])
    import math
    zs = [(j - 64) / 16 for j in range(129)]
    q = [256 * 0.5 * math.erfc(z / math.sqrt(2)) for z in zs]
    l = [256 * (math.exp(-z * z / 2) / math.sqrt(2 * math.pi)) - z * qq for z, qq in zip(zs, q)]
    check("the normal tables: the tail and the loss, from erf here", (
        max(abs(a - b) for a, b in zip(TR.TQ, q)) <= 0.5, max(abs(a - b) for a, b in zip(TR.TL, l)) <= 0.5,
        TR.TQ[0], TR.TQ[128], TR.TL[64]), (True, True, 256, 0, 102))

    #  The arithmetic, called as the reckoning calls it: native, sixteen bits.
    def native(fn, **vals):
        bus, _ = machine()
        tac_junk(bus)
        for name, (v, size) in vals.items():
            at = rw(name)
            bus.wram[at:at + size] = v.to_bytes(size, "little")
        cpu = CPU(bus)
        cpu.e = False
        cpu.p &= ~(FLAG_M | FLAG_X)
        cpu.dbr = BANK_0C
        call(cpu, fn, bank=TACTICS_BANK)
        return cpu, bus
    bad = []
    for x, y in [(0, 0), (0xFFFFFFFF, 0xFFFF), (1, 1), (0x12345678, 0x9ABC)] + \
            [(rnd.randrange(1 << 32), rnd.randrange(1 << 16)) for _ in range(150)]:
        _, bus = native("tac_mul", TC_MX=(x, 4), TC_MY=(y, 2))
        if tac_w(bus, "TC_PR", 0, 4) != (x * y) & 0xFFFFFFFF:
            bad.append(("mul", x, y))
    for n, d in [(0, 1), (0xFFFFFFFF, 1), (0xFFFF0000, 0xFFFF), (0x7FFFFFFF, 0x8000), (65535 * 40000, 40000),
                 (5, 0xFFFF)] + [(rnd.randrange(1 << 32), rnd.randrange(1, 1 << 16)) for _ in range(150)]:
        cpu, bus = native("tac_div", TC_NUM=(n, 4), TC_DEN=(d, 2))
        if cpu.a & 0xFFFF != min(0xFFFF, n // d):
            bad.append(("div", n, d, cpu.a))
        _, bus = native("tac_divl", TC_NUM=(n, 4), TC_DEN=(d, 2))
        if (tac_w(bus, "TC_NUM", 0, 4), tac_w(bus, "TC_REM")) != (n // d, n % d):
            bad.append(("divl", n, d))
    for v in [0, 1, 2, 3, 4, 15, 16, 17, 65535, 65536, 0xFFFFFFFF, 0xFFFE0001] + \
            [rnd.randrange(1 << rnd.randrange(1, 33)) for _ in range(150)]:
        cpu, bus = native("tac_sqrt", TC_SQ=(v, 4))
        if cpu.a & 0xFFFF != TR.isqrt(v):
            bad.append(("sqrt", v, cpu.a))
    for k in range(256):
        cpu, _ = native("tac_f", TC_T=(0, 2))
        cpu2 = CPU(cpu.bus)
        cpu2.e = False
        cpu2.p &= ~(FLAG_M | FLAG_X)
        cpu2.a = k
        call(cpu2, "tac_f", bank=TACTICS_BANK)
        if cpu2.a & 0xFFFF != TR.F(k):
            bad.append(("F", k, cpu2.a))
    for y32, m16 in [(0, 5000), (100, 200), (2 ** 20, 16), (65536 * 3, 65535)]:
        _, bus = native("tac_var", TC_Y32=(y32, 4), TC_M16=(m16, 2))
        if tac_w(bus, "TC_V32", 0, 4) != max(0, y32 - ((m16 * m16) >> 8)):
            bad.append(("var", y32, m16))
    check("the arithmetic: products, quotients, roots, the dice's shares, variance's floor", bad[:4], [])

    #  --- The game's hit loop, one swing at a time ---
    k = bank.find(bytes([0xA2, 0xC8, 0x20]))
    while k >= 0 and bank[k + 5:k + 13] != bytes([0x8D, 0x5E, 0x68, 0xAD, 0x5E, 0x68, 0xC9, 0xC8]):
        k = bank.find(bytes([0xA2, 0xC8, 0x20]), k + 1)
    hitloop = 0x8000 + k - 6
    tail = bytes([0xCE, 0x5A, 0x68, 0xF0, 0x03, 0x4C, hitloop & 0xFF, hitloop >> 8])
    check("the hit loop, found by its bytes", (k > 0, bank.count(tail)), (True, 1))
    after = 0x8000 + bank.find(tail) + len(tail)

    def real_swing(H, C, B, ab, rdie, ddie):
        bus, cpu = machine()
        ram = lambda name, v: bus.sram.__setitem__(K[name] - 0x6000, v)
        ram("math_hitchance", H)
        ram("math_critchance", C)
        ram("math_numhits", 1)
        bus.sram[0x6BAD - 0x6000] = B
        ram("btl_defender_absorb", ab)
        ram("battle_defenderisplayer", 1)
        ram("btl_attacker_attackailment", 0)
        for name in ("battle_totaldamage", "battle_hitsconnected", "battle_critsconnected"):
            ram(name, 0)
        bus.sram[K["battle_totaldamage"] + 1 - 0x6000] = 0
        tab = [0] * 256
        tab[40], tab[41] = rdie, ddie
        tac_rng(bus, tab, 40)
        cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, hitloop
        for _ in range(3000):
            if cpu.pbr == BANK_0C and cpu.pc == after:
                at = K["battle_totaldamage"] - 0x6000
                return bus.sram[at] | bus.sram[at + 1] << 8
            cpu.step()
        return None
    bad = []
    for H, C, B, ab in ((168, 1, 40, 10), (255, 255, 8, 30), (90, 60, 255, 0), (1, 1, 0, 0),
                        (200, 3, 128, 127), (199, 199, 70, 200)):
        dice = [(r, d) for r in (0, 1, 2, 127, 128, 254, 255) + tuple(range(0, 256, 9))
                for d in (0, 1, 128, 255)]
        dice += [(rnd.randrange(256), rnd.randrange(256)) for _ in range(40)]
        for r in range(256):
            if abs(((r * 201) >> 8) - H) <= 1 or abs(((r * 201) >> 8) - C) <= 1:
                dice.append((r, rnd.randrange(256)))
        for r, d in dice:
            got, want = real_swing(H, C, B, ab, r, d), tac_swing_die(H, C, B, ab, r, d)
            if got != want:
                bad.append("H %d C %d B %d abs %d dice %d,%d: %s, model %s" % (H, C, B, ab, r, d, got, want))
    check("one swing, die by die: the game's hit loop is the reckoning's", bad[:3], [])
    bad = []
    for B, ab, H, C in ((40, 10, 168, 1), (8, 30, 255, 255), (255, 0, 90, 60), (0, 0, 1, 1), (128, 127, 200, 3),
                        (200, 220, 160, 20)):
        s = TR.dice(B, ab)
        lhs = sum(tac_swing_die(H, C, B, ab, r, d) for r in range(256) for d in range(256))
        lhs2 = sum(tac_swing_die(H, C, B, ab, r, d) ** 2 for r in range(256) for d in range(256))
        ch, cc = TR.hits(H), TR.hits(C)
        if (lhs, lhs2) != (ch * s[0] + cc * s[1], ch * s[2] + cc * (2 * s[4] + s[3])):
            bad.append((B, ab, H, C))
    check("a hit's sums are its dice's damage and its square, all 65536 pairs", bad, [])

    #  --- The game's spell effects, every roll ---
    dmgundead = SYM["BtlMag_Effect_DamageUndead"]
    k = bank.find(bytes([dmgundead & 0xFF, dmgundead >> 8]))
    while k >= 0 and bank[k - 1] in (0x20, 0x4C):
        k = bank.find(bytes([dmgundead & 0xFF, dmgundead >> 8]), k + 1)
    jt = k - 4
    effect = lambda n: bank[jt + 2 * n] | bank[jt + 2 * n + 1] << 8

    def real_spell(eff, efv, elem, shr, md, res, ail, hp, mult, dice, maxhp=2000):
        bus, cpu = machine()
        ram = lambda name, v: bus.sram.__setitem__(K[name] - 0x6000, v)
        ram("btlmag_effectivity", efv)
        ram("btlmag_element", elem)
        ram("btlmag_hitrate", shr)
        ram("btlmag_defender_magdef", md)
        ram("btlmag_defender_elemresist", res)
        ram("btlmag_defender_elemweakness", 0)
        ram("btlmag_defender_ailments", ail)
        ram("btlmag_defender_numhitsmult", mult)
        at = K["btlmag_defender_hp"] - 0x6000
        bus.sram[at], bus.sram[at + 1] = hp & 0xFF, hp >> 8
        mx = K["btlmag_defender_hpmax"] - 0x6000
        bus.sram[mx], bus.sram[mx + 1] = maxhp & 0xFF, maxhp >> 8
        ram("btlmag_spellconnected", 0)
        tab = [0] * 256
        tab[40:40 + len(dice)] = dice
        tac_rng(bus, tab, 40)
        cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, effect(eff)
        cpu.push(0xFF); cpu.push(0xFD)
        for _ in range(5000):
            if cpu.pbr == BANK_0C and cpu.pc in (0xFFFE, SYM["DrawDamageCombatBox"]):
                hp2 = bus.sram[at] | bus.sram[at + 1] << 8
                return (bus.sram[K["btlmag_spellconnected"] - 0x6000],
                        bus.sram[K["btlmag_defender_numhitsmult"] - 0x6000], hp2)
            cpu.step()
        return None
    check("the magic jump table, found", all(0x8000 <= effect(n) < 0xC000 for n in range(19)), True)
    bad = []
    for shr, md, res in ((24, 0, 0), (40, 140, 0), (0, 255, 0), (64, 30, 0x10), (200, 10, 0x10), (107, 100, 0)):
        H = max(0, (0 if res else 148) + shr - md)
        for die in range(256):
            land = TR.hits(H) > 0 and ((die * 201) >> 8) != 200 and H >= ((die * 201) >> 8)
            got = real_spell(0x03, 0x20, 0x10, shr, md, res, 0, 500, 1, [0x80, die])
            if got[0] != land:
                bad.append("ailment %d/%d/%d die %d: %s" % (shr, md, res, die, got))
            for mult in (1, 0):
                got = real_spell(0x04, 0, 0x10, shr, md, res, 0, 500, mult, [0x80, die])
                if got[1] != (0 if land else mult):
                    bad.append("slow %d/%d/%d die %d mult %d: %s" % (shr, md, res, die, mult, got))
            for E in (30, 255, 1):
                dd = rnd.randrange(256)
                got = real_spell(0x01, E, 0x10, shr, md, res, 0, 3000, 1, [dd, die])
                E2 = E >> 1 if res else E
                dmg = E2 + ((dd * ((E2 + 1) & 0xFF)) >> 8)
                if land:
                    dmg *= 2
                if 3000 - got[2] != dmg:
                    bad.append("damage %d %d/%d/%d dice %d,%d: %s, want %d" % (E, shr, md, res, dd, die, got, dmg))
        for d in range(256):
            land = TR.hits(H) and H >= ((d * 201) >> 8) and ((d * 201) >> 8) != 200
            if bool(land) != (d < TR.hits(H)):
                bad.append("hits(%d) is not the first dice that land, at %d" % (H, d))
                break
    check("spells, every roll: the game's effects are the reckoning's", bad[:3], [])
    bad = []
    for hp in (1, 299, 300, 301, 999):
        for res in (0, 0x10):
            got = real_spell(0x12, 0x01, 0x10, 0, 0, res, 0, hp, 1, [0, 0])
            if got is None or bool(got[0]) != (not res and hp <= 300):
                bad.append((hp, res, got))
    check("XXXX: at or under 300 HP, not resisted", bad, [])
    bad = []
    for E, hp, maxhp in ((16, 100, 500), (200, 100, 150), (255, 10, 900), (1, 5, 5)):
        for die in range(0, 256, 15):
            got = real_spell(0x06, E, 0, 0, 0, 0, 0, hp, 1, [die], maxhp=maxhp)
            want = min(maxhp, hp + min(255, E + ((die * ((E + 1) & 0xFF)) >> 8)))
            if got[2] != want:
                bad.append((E, hp, maxhp, die, got[2], want))
    check("a heal: E + RandAX(0, E), at most 255, at most the max", bad[:3], [])

    #  --- tac_turn against the reckoning, every intermediate ---
    bad = []
    for n in range(160):
        party = tac_party_draw(rnd)
        enemy = rnd.choice(TAC_BOSSES)
        rom = ROMDATA[ENEMIES_ROM + enemy * 20:][:20]
        maxhp = rom[4] | rom[5] << 8
        spells = [rnd.randrange(64) for _ in range(rnd.randrange(0, 9))]
        skills = [rnd.randrange(0x26) for _ in range(rnd.randrange(0, 5))]
        script = tac_script_bytes(rnd.choice((0, 30, 64, 128)), rnd.choice((0, 30, 64, 128)), spells, skills)
        mode, state = 1 + n % 2, rnd.randrange(256)
        deck = rnd.choice(((0, 0), (rnd.randrange(256), rnd.randrange(16) | rnd.randrange(8) << 4),
                           (rnd.randrange(256), rnd.randrange(16) | 8 << 4), (0xFF, 0x7F)))
        bus = tac_setup(party, enemy, rnd.choice((maxhp, max(1, maxhp // 3), 7, maxhp + 100)), script, mode, state,
                        ail=rnd.choice((0, 0, 0, 0x08, 0x40)), mult=rnd.choice((1, 1, 2, 0)),
                        flags5=rnd.choice((0, 0x01)), elemdmg=rnd.choice((4, 30)), deck=deck)
        if rnd.random() < 0.3:
            setblk(bus, K["OPTFB_WMHARM"] - OPTBLOCK, blk(bus, K["OPTFB_WMHARM"] - OPTBLOCK) | K["OPTFM_WMHARM"])
        if rnd.random() < 0.5:                   # spells as the buffs and fixes write them
            setblk(bus, OPT_FLAGS + 2, rnd.choice((0x40, 0x80, 0x02, 0xC2)))
        b, _ = tac_compare(bus, party, enemy, script, mode, state, "#%d" % n)
        bad += b
    #  ...and parties at the edges: one that cannot touch the boss (Dp's
    #  floor), one with a single damage dealer (losing it leaves under 16),
    #  HP past HPCAP, XXXX's line.
    nobody = lambda **k: TR.Member(dmg=0, hitrate=0, numhits=1, **k)
    edges = [[nobody(hp=50), nobody(hp=60), nobody(hp=70), nobody(hp=80)],
             [TR.Member(dmg=200, hitrate=200, numhits=4, hp=500), nobody(hp=60), nobody(hp=300), nobody(hp=301)],
             [TR.Member(hp=5000, maxhp=6000), TR.Member(hp=4096, maxhp=4100), nobody(hp=301), TR.Member(hp=300)],
             [TR.Member(hp=1, maxhp=1), nobody(ail=0x01, hp=0), nobody(ail=0x02, hp=9), nobody(hp=299)]]
    #  A boss that cannot hurt anyone: Db's floor.
    harmless = [TR.Member(hp=300, evade=255, absorb=255) for _ in range(4)]
    bus = tac_setup(harmless, 127, 2000, tac_script_bytes(0, 0, [], []), 2, 5, strength=0)
    b, M = tac_compare(bus, harmless, 127, tac_script_bytes(0, 0, [], []), 2, 5, "harmless")
    bad += b
    check("a boss that cannot hurt anyone: Db at its floor", M.Db, 16)
    for n, party in enumerate(edges):
        for mode in (1, 2):
            spells = [rnd.randrange(64) for _ in range(6)]
            script = tac_script_bytes(64, 64, spells + [0x37], [rnd.randrange(0x26) for _ in range(3)])
            bus = tac_setup(party, 127, 2000, script, mode, 31, evade=255, absorb=255)
            b, _ = tac_compare(bus, party, 127, script, mode, 31, "edge %d" % n)
            bad += b
    #  A boss of 7 HP, one member's spells its whole danger and another's 15
    #  sixteenths a round the rest: losing the first leaves under 16 of Dp.
    fir3 = next(i for i in range(64) if tac_rec_of(tac_base())(i)[1] > 70 and tac_rec_of(tac_base())(i)[4] == 1)
    lone = [TR.Member(cls=5, hp=200, dmg=0, spells=[fir3 + 1] + [0] * 31, mp=[2] * 8),
            TR.Member(dmg=0, hitrate=200, numhits=1, hp=90),
            TR.Member(ail=0x01, hp=0), TR.Member(ail=0x02, hp=40)]
    for mode in (1, 2):
        script = tac_script_bytes(64, 64, [rnd.randrange(64) for _ in range(5)], [0x16])
        bus = tac_setup(lone, 127, 7, script, mode, 3, evade=0, absorb=255)
        b, M = tac_compare(bus, lone, 127, script, mode, 3, "lone")
        bad += b
    check("...the lone danger: the rest of Dp under 16", (M.Dp - M.d[0] < 16, M.d[1]), (True, 15))
    check("tac_turn, 160 drawn turns: every number the reckoning's", bad[:3], [])
    check("...(how many turns disagreed)", len(bad), 0)

    #  --- Enemy_DoAi itself, each boss, its own script as rando_enemyai deals it ---
    a = SYM["tac_swing"]
    k = bank.find(bytes([0x22, a & 0xFF, a >> 8, TACTICS_BANK, 0x20]))
    swing_back = 0x8000 + k + 7

    def in_place(party, enemy, hp, mode, state, follow=True, boss_step=STAT_100, flags5=0):
        bus = tac_setup(party, enemy, hp, [0xFF] * 16, mode, state, flags5=flags5)
        setblk(bus, OPT_BOSS, boss_step)
        cpu = CPU(bus)
        cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, SYM["Enemy_DoAi"]
        cpu.push(0xFF); cpu.push(0xFD)
        phys, magic = SYM["EnemyAttackPlayer_Physical"], SYM["Enemy_DoMagicEffect"]
        out = None
        for _ in range(3_000_000):
            if cpu.pbr == BANK_0C and out is None and cpu.pc == phys:
                out = ("swing", cpu.a & 0x03)
                if not follow:
                    break
            elif cpu.pbr == BANK_0C and out is None and cpu.pc == magic:
                out = ("magic", cpu.a & 0xFF)
                break
            elif cpu.pbr == BANK_0C and out is not None and cpu.pc == swing_back:
                out += (bus.sram[K["battle_defender_index"] - 0x6000], bus.wram[0x80] | bus.wram[0x81] << 8)
                loaded = tuple(bus.sram[K[n] - 0x6000] for n in ("btl_attacker_hitrate", "btl_attacker_numhits",
                                                                    "btl_attacker_critrate"))
                if bus.wram[rw("TC_MODE")] and loaded != (tac_w(bus, "TC_HR"), tac_w(bus, "TC_BNH"), tac_w(bus, "TC_CR")):
                    out += ("weighed %s, swung %s" % ((tac_w(bus, "TC_HR"), tac_w(bus, "TC_BNH"), tac_w(bus, "TC_CR")),
                                                       loaded),)
                break
            cpu.step()
        return out, bus
    bad = []
    for enemy in TAC_BOSSES:
        rom = ROMDATA[ENEMIES_ROM + enemy * 20:][:20]
        maxhp = rom[4] | rom[5] << 8
        for n in range(4):
            party = tac_party_draw(rnd)
            state = rnd.randrange(256)
            hp = rnd.choice((maxhp, max(1, maxhp // 5)))
            step = (STAT_100, 7, 1, STAT_100)[n]         # 100%, 200%, 50%: as the swing will be scaled
            off, _ = in_place(party, enemy, hp, 0, state, follow=False)
            for mode in (1, 2):
                got, bus = in_place(party, enemy, hp, mode, state, boss_step=step)
                at = K["OPTAISHADOW"] - 0x6000
                script = list(bus.sram[at:at + 16])
                scripted = script != [0xFF] * 16 and rom[7] != 0xFF
                if not scripted:
                    flat = [0, 0] + [0xFF] * 12
                else:
                    flat = script[0:2] + script[2:10] + script[11:15]
                table = bytes(bus.wram[rw("RW_BATRNG"):rw("RW_BATRNG") + 256])
                M = TR.Mind(party, tac_boss_of(bus, enemy), flat, tac_rec_of(bus), 4)
                if scripted:
                    aid, tgt, used = M.choose(mode, [table[state], table[(state + 1) & 0xFF]])
                else:
                    aid, tgt = None, M.value[0][1]
                if aid is None:
                    want = ("swing", tgt, tgt, 0x6800 + 0x12 * tgt)
                    if not scripted:            # the roll's slot, then the hook's
                        got, want = got[2:], want[2:]
                else:
                    want = ("magic", aid)
                if got != want:
                    bad.append("$%02X %s: %s, want %s" % (enemy, ("Clever", "Ruthless")[mode - 1], got, want))
    check("Enemy_DoAi in place, every boss: the reckoning's turn, the swing's aim through its hook",
          bad[:3], [])
    #  Asshat Octopus with the dial: Kraken still hits its White Mage.
    bad = []
    for kraken in (0x7B, 0x7C):
        for mode in (1, 2):
            for wm in range(4):
                #  The white mage the worst target there is: its own choice
                #  would be anyone else.
                party = [TR.Member(cls=0, hp=40, maxhp=400, absorb=0, evade=0) for _ in range(4)]
                party[wm] = TR.Member(cls=(4, 10)[wm % 2], hp=900, maxhp=900, absorb=255, evade=255)
                got, _ = in_place(party, kraken, 800, mode, rnd.randrange(256), flags5=0x08)
                if got[0] != "swing" or got[2] != wm:
                    bad.append((kraken, mode, wm, got))
    check("Asshat Octopus and Boss tactics: Kraken at the white mage, the easy kills left", bad[:3], [])

    #  Off, or not a boss: tac_turn comes back at once, the dice and scratch untouched.
    bad = []
    for mode, enemy in ((0, 127), (0, 105), (1, 0x2A), (2, 0x10), (3, 127)):
        party = tac_party_draw(rnd)
        bus = tac_setup(party, enemy, 500, tac_script_bytes(64, 64, [1, 2], [3]), mode, 77)
        junk = bytes(bus.wram[rw("TC_BASE"):rw("TC_END")])
        got, _ = tac_run(bus)
        if (got, bus.sram[BTL_RNGSTATE - 0x6000], bytes(bus.wram[rw("TC_BASE"):rw("TC_END")])) != (("script",), 77, junk):
            bad.append((mode, enemy, got))
    check("off, a stray 3, or not a boss: the script's own turn, nothing touched", bad, [])

    #  --- The hooks: the latch is for one attacker, one live slot, once ---
    def latched(latch, attacker=TAC_ENEMYSLOT, drawn=(0, 0), entry="tac_cast"):
        bus = tac_base()
        tac_write_party(bus, tac_party_draw(random.Random(5)))
        bus.sram[TAC_DRAWN - 0x6000], bus.sram[TAC_DRAWN + 1 - 0x6000] = drawn
        bus.wram[rw("TC_LATCH"):rw("TC_LATCH") + 3] = bytes(latch)
        bus.sram[K["btl_attacker"] - 0x6000] = attacker
        bus.sram[K["btl_randomplayer"] - 0x6000] = 1
        cpu = CPU(bus)
        cpu.x, cpu.y = 0x5A, 0xA5
        call(cpu, entry, bank=TACTICS_BANK, dbr=BANK_0C)
        return cpu.a & 0xFF, bytes(bus.wram[rw("TC_LATCH"):rw("TC_LATCH") + 3]), (cpu.x & 0xFF, cpu.y & 0xFF)
    good = [0xA3, 0xA3 ^ 0xFF, TAC_ENEMYSLOT]
    check("tac_cast: the latch's slot, the latch cleared, X and Y kept", latched(good), (0x83, bytes(3), (0x5A, 0xA5)))
    check("...another attacker's: the roll's", latched(good, attacker=3)[0], 0x81)
    check("...its slot dead since: the roll's", latched(good, drawn=(0x08, 0))[0], 0x81)
    check("...stone since: the roll's", latched(good, drawn=(0, 0x08))[0], 0x81)
    check("...junk: the roll's, and cleared",
          [latched(j)[:2] for j in ([0xA3, 0xA3, 2], [0x53, 0xAC, 2], [0, 0xFF, 2], [0xFF, 0x00, 2])],
          [(0x81, bytes(3))] * 4)

    #  Garland and the Pirates have no script: their swing weighs its aim.
    bad = []
    for enemy in (105, 15):
        for n in range(12):
            party = tac_party_draw(rnd)
            got, bus = in_place(party, enemy, 300, 2, rnd.randrange(256))
            M = TR.Mind(party, tac_boss_of(bus, enemy), [0, 0] + [0xFF] * 12, tac_rec_of(bus), 4)
            t = M.value[0][1]
            if got != ("swing", t, t, 0x6800 + 0x12 * t) and got[0] == "swing" and got[1] != got[2]:
                pass
            if got[2:] != (t, 0x6800 + 0x12 * t):
                bad.append(("$%02X" % enemy, got, t))
    check("Garland and the Pirates: the swing's aim weighed at its hook", bad[:3], [])

    #  --- What the worth means, in cases a player knows ---
    def turn(party, enemy, hp, mode=2, state=0, ail=0, mult=1, script=None):
        rom = ROMDATA[ENEMIES_ROM + enemy * 20:][:20]
        bus = tac_setup(party, enemy, hp, [0xFF] * 16, mode, state, ail=ail, mult=mult)
        cpu = CPU(bus)
        cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, SYM["Enemy_DoAi"]
        cpu.push(0xFF); cpu.push(0xFD)
        for _ in range(3_000_000):
            if cpu.pbr == BANK_0C and cpu.pc in (SYM["EnemyAttackPlayer_Physical"], SYM["Enemy_DoMagicEffect"]):
                break
            cpu.step()
        n = tac_w(bus, "TC_NCAND")
        return {tac_w(bus, "TC_CID", 2 * k): (tac_w(bus, "TC_CVAL", 2 * k), tac_w(bus, "TC_CTGT", 2 * k))
                for k in range(n)}, (cpu.pc == SYM["Enemy_DoMagicEffect"], cpu.a & 0xFF), bus
    FI, TH, BB, RM, WM, BM = 0, 1, 2, 3, 4, 5

    def spell(name):
        """A spell's id, by the name the cartridge gives it."""
        b0a = (1 + 0x0A) * 0x10000
        for i in range(64):
            p = ROMDATA[b0a + 0xB700 + 2 * (0xB0 + i)] | ROMDATA[b0a + 0xB701 + 2 * (0xB0 + i)] << 8
            if "".join(_decode(c) or "" for c in ROMDATA[b0a + p:b0a + p + 4]).strip() == name:
                return i
        raise KeyError(name)
    ribboned = [TR.Member(cls=c, hp=400, maxhp=400, res=0xFF, magdef=120, absorb=40, evade=40) for c in (FI, TH, WM, BM)]
    #  SLEP and HOLD are the status element, which a Ribbon resists; SLP2 has
    #  no element at all in the cartridge, and a Ribbon does nothing for it.
    sleepers = [spell(n) for n in ("SLEP", "HOLD")]
    worth, act, _ = turn(ribboned, 119, 2000)      # Lich
    check("Lich at a party in Ribbons: SLEP and HOLD in its script, and SLP2",
          all(s in worth for s in sleepers + [spell("SLP2")]), True)
    check("...SLEP and HOLD each worth under a twentieth of its best",
          [worth[s][0] * 20 < max(v for v, _ in worth.values()) for s in sleepers], [True] * 2)
    check("...SLP2 worth more than either", worth[spell("SLP2")][0] > max(worth[s][0] for s in sleepers), True)
    check("...and its turn is neither", act[0] and act[1] in sleepers, False)
    party = [TR.Member(cls=c, hp=600, maxhp=600, absorb=50, evade=40) for c in (FI, FI, WM, BM)]
    full, _, _ = turn(party, 127, 2000)            # Chaos
    hurt, act, _ = turn(party, 127, 300)
    cur4 = spell("CUR4")
    check("Chaos at full HP: CUR4 worth nothing", full[cur4][0], 0)
    check("...hurt, CUR4 worth more than any of its damage", hurt[cur4][0] > max(v for k, (v, _) in hurt.items() if k != cur4 and k != 0x0C), True)
    check("...and it casts it", act, (True, cur4))
    check("Chaos, FAST in its script", spell("FAST") in full, True)
    check("...already fast: FAST worth nothing", turn(party, 127, 2000, mult=2)[0][spell("FAST")][0], 0)
    weak = [TR.Member(cls=FI, hp=600, maxhp=600, absorb=50), TR.Member(cls=TH, hp=250, maxhp=600, absorb=20),
            TR.Member(cls=WM, hp=310, maxhp=400), TR.Member(cls=BM, hp=290, maxhp=400)]
    worth, act, _ = turn(weak, 120, 2000)          # Lich 2
    check("Lich 2's XXXX: at the one at 290 HP, not 310 or 600", worth[spell("XXXX")][1], 3)
    def custom(party, names, hp=2000, mult=1, enemy=127):
        """A boss's worths for a script of these spells alone, and the swing."""
        bus = tac_setup(party, enemy, hp, tac_script_bytes(128, 0, [spell(n) for n in names], []), 2, 0, mult=mult)
        tac_run(bus)
        return {tac_w(bus, "TC_CID", 2 * k): (tac_w(bus, "TC_CVAL", 2 * k), tac_w(bus, "TC_CTGT", 2 * k))
                for k in range(tac_w(bus, "TC_NCAND"))}
    xx = [TR.Member(cls=FI, hp=301, maxhp=500), TR.Member(cls=FI, hp=300, maxhp=500),
          TR.Member(cls=FI, hp=302, maxhp=500), TR.Member(cls=FI, hp=500, maxhp=500)]
    check("XXXX's line: 300 is in, 301 is out", custom(xx, ["XXXX"])[spell("XXXX")][1], 1)
    nuker = TR.Member(cls=BM, hp=300, maxhp=300, dmg=5, spells=[spell("FIR3") + 1] + [0] * 31, mp=[3] * 8)
    blades = [TR.Member(cls=FI, hp=600, maxhp=600, dmg=60) for _ in range(3)]
    #  MUTE hits the whole party in this cartridge (its target is $01).
    w = custom(blades[:2] + [nuker, blades[2]], ["MUTE"])
    check("MUTE: worth something with a black mage there with FIR3 to cast", w[spell("MUTE")][0] > 0, True)
    check("...and nothing against a party of blades", custom(blades + [blades[0]], ["MUTE"])[spell("MUTE")][0], 0)
    rom = ROMDATA[ENEMIES_ROM + 127 * 20:][:20]
    chaosmax = rom[4] | rom[5] << 8
    cure = spell("CURE")
    full, hurt, little = (custom(blades + [nuker], ["CURE"], hp=h)[cure][0] for h in (chaosmax, 100, chaosmax - 2))
    check("CURE on itself: nothing at full HP, more hurt than barely", (full, hurt > little > 0), (0, True))
    weakspells = [TR.Member(cls=FI, hp=900, maxhp=900, absorb=10, evade=0) for _ in range(4)]
    fast = spell("FAST")
    bus = tac_setup(blades + [nuker], 127, 2000, tac_script_bytes(0, 128, [], [0x16]), 2, 0)
    tac_run(bus)
    #  Two HP a round from each of four, for the whole of a fight the party
    #  is losing slowly: in the race that can outweigh a swing.
    check("the poison skill: worth something, two HP a round for the fight", tac_w(bus, "TC_CVAL", 2) > 0, True)
    check("FAST alone: worth something to a boss not yet fast", custom(weakspells, ["FAST"], mult=1)[fast][0] > 0, True)
    check("...and nothing once it is", custom(weakspells, ["FAST"], mult=2)[fast][0], 0)
    last = [TR.Member(ail=0x01, hp=0, maxhp=300)] * 3 + [TR.Member(cls=FI, hp=500, maxhp=500)]
    worth, act, bus = turn(last, 127, 2000)
    check("the last one standing: a kill is the fight", tac_w(bus, "TC_KG", 6), TR.CAP)

    #  --- The deck: a fight of sixteen of Chaos's turns, in place ---
    #  The dice and the rotation bytes carried from turn to turn, and the
    #  party hurting it between: no slot of its script twice in a pass of
    #  eight, its CUR4 once a pass however hurt it is.
    rom = ROMDATA[ENEMIES_ROM + 127 * 20:][:20]
    chaosmax = rom[4] | rom[5] << 8
    party = [TR.Member(cls=c, hp=900, maxhp=900, dmg=110, hitrate=150, numhits=2, absorb=60, evade=60, magdef=110)
             for c in (6, 7, 9, 10)]
    for mode in (1, 2):
        state, deck, hp, plays = 17, (0, 0), chaosmax, []
        for turn_no in range(16):
            bus = tac_setup(party, 127, hp, [0xFF] * 16, mode, state, deck=deck)
            cpu = CPU(bus)
            cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, SYM["Enemy_DoAi"]
            cpu.push(0xFF); cpu.push(0xFD)
            while not (cpu.pbr == BANK_0C and cpu.pc in (SYM["EnemyAttackPlayer_Physical"], SYM["Enemy_DoMagicEffect"])):
                cpu.step()
            act = "swing" if cpu.pc == SYM["EnemyAttackPlayer_Physical"] else cpu.a & 0xFF
            plays.append(act)
            en = K["btl_enemystats"] + TAC_ENEMYSLOT * 0x14 - 0x6000
            deck = (bus.sram[en + K["en_aimagpos"]], bus.sram[en + K["en_aiatkpos"]])
            state = bus.sram[BTL_RNGSTATE - 0x6000]
            hp = cur = chaosmax if act == cur4 else max(1, hp - 400)
        at = K["OPTAISHADOW"] - 0x6000
        script = list(tac_base().sram[at:at + 16])
        bus = tac_setup(party, 127, chaosmax, [0xFF] * 16, mode, 0)
        cpu = CPU(bus)
        cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, SYM["Enemy_DoAi"]
        cpu.push(0xFF); cpu.push(0xFD)
        while not (cpu.pbr == BANK_0C and cpu.pc in (SYM["EnemyAttackPlayer_Physical"], SYM["Enemy_DoMagicEffect"])):
            cpu.step()
        script = list(bus.sram[at:at + 16])
        slots = [x for x in script[2:10] if x != 0xFF] + [x + 0x42 for x in script[11:15] if x != 0xFF]
        over = [(w, a) for w in (0, 8) for a in set(plays[w:w + 8]) if a != "swing"
                and plays[w:w + 8].count(a) > slots.count(a)]
        name = ("Clever", "Ruthless")[mode - 1]
        check("%s Chaos, sixteen turns: no slot played twice in a pass of eight" % name, over, [])
        check("...CUR4 at most once a pass, hurt as it is", [plays[w:w + 8].count(cur4) <= 1 for w in (0, 8)],
              [True, True])
        check("...and it casts something", any(a != "swing" for a in plays), True)
        print("    boss tactics: %s Chaos, sixteen turns: %s" % (name, " ".join(
            "-" if a == "swing" else ("%02X" % a) for a in plays)))

    #  --- The music plays while it thinks ---
    party = [TR.Member(cls=c, hp=700, maxhp=700, absorb=30, spells=[rnd.randrange(1, 65) for _ in range(32)],
                       mp=[9] * 8) for c in (BM, WM, RM, BM)]
    bus = tac_setup(party, 127, 1500, tac_script_bytes(64, 64, list(range(8)), [0, 1, 2, 3]), 2, 9)
    quiet, _ = tac_run(bus)
    steps = []
    for every in (None, 30):
        bus = tac_setup(party, 127, 1500, tac_script_bytes(64, 64, list(range(8)), [0, 1, 2, 3]), 2, 9)
        if every:
            bus.frames(every)
        cpu = CPU(bus)
        cpu.dbr = BANK_0C
        cpu.pbr, cpu.pc = TACTICS_BANK, SYM["tac_turn"]
        cpu.push(BANK_0C); cpu.push(0xFF); cpu.push(0xFD)
        music = 0
        for n in range(5_000_000):
            if cpu.pc == SYM["CallMusicPlay"] and cpu.pbr == TACTICS_BANK:
                music += 1
            if cpu.pbr == BANK_0C:
                break
            cpu.step()
        steps.append((n, music, bus.sram[BTL_RNGSTATE - 0x6000], cpu.pc, cpu.a & 0xFF))
    print("    boss tactics: Chaos against four casters took %d instructions" % steps[0][0])
    check("with vblanks coming, it runs the music between thoughts", steps[1][1] > 3, True)
    check("...and decides the same", steps[1][2:], steps[0][2:])
    check("...none without them", steps[0][1], 0)
    check("Chaos against four casters: a few tenths of a second at most (150000 instructions)",
          steps[0][0] < 150000, True)

    #  --- The dial: bits 45 and 46, the rest of the byte kept ---
    SEL, TOP = 0x6E, 0x6F
    bus, cpu = machine()
    in_vblank(bus)
    call(cpu, "opt_init")
    keep = blk(bus, OPT_FLAGS + 5)
    bus.wram[SEL], bus.wram[TOP] = optrow("Boss tactics"), optrow("Boss tactics") - 10
    got = []
    for key in ("RIGHT", "RIGHT", "RIGHT", "LEFT", "LEFT", "LEFT"):
        cpu.a = K[key]
        call(cpu, "opt_value_adjust", dbr=CHUNK_OPT_BANK)
        text = " ".join(pane(bus))
        got.append((blk(bus, OPT_FLAGS + 5),
                    [w for w in ("eighth each", "script's", "every action") if w in text]))
    check("the dial: Clever, Ruthless, held there, and back, each with its words, the byte's other bits kept",
          got, [(keep | 0x20, ["script's"]), (keep | 0x40, ["every action"]), (keep | 0x40, ["every action"]),
                (keep | 0x20, ["script's"]), (keep, ["eighth each"]), (keep, ["eighth each"])])
    check("...with the Improved preset's TRANCE bit there to keep", keep & 0x01, 1)


def test_staffspells():
    """RUSE Staff and NUKE Stick: the Power Staff casts RUSE and the Wizard
    Staff NUKE when used in battle, their equipment text says so, and each is
    named for its spell and the staff.  Each of the three readers, over every
    pair of the two flags and the byte's other bits, against both off, over
    everything it could touch: only the flagged staff moves.  Battle's Use is
    the game's own item path, weapon and armour, every index, from the menu's
    choice to SetCharacterBattleCommand, the other characters' items all decoy
    staves."""
    FB, RUSE, NUKE = OPT_FLAGS + 5, K["OPTFM_RUSESTAFF"], K["OPTFM_NUKESTICK"]
    check("the RUSE Staff is bit 44, the NUKE Stick bit 47",
          (K["OPTFB_RUSESTAFF"] - OPTBLOCK, RUSE, K["OPTFB_NUKESTICK"] - OPTBLOCK, NUKE),
          (OPT_FLAGS + 5, 0x10, OPT_FLAGS + 5, 0x80))
    #  flag, item, weapon index, spell byte, the name it takes
    STAVES = ((RUSE, 0x37, 27, 4, bytes([0x9B, 0x9E, 0x9C, 0x8E, 0xFF, 0xFF, 0xD8])),
              (NUKE, 0x3C, 32, 0x3D, bytes([0x97, 0x9E, 0x94, 0x8E, 0xFF, 0xFF, 0xD8])))
    BITS = (RUSE, NUKE, RUSE | NUKE, 0xFF & ~(RUSE | NUKE), 0xFF)
    CURCHAR, CMDITEM, CMDBUF = 0x6B7A, 0x689F, 0x688F
    img = BANK_0C & 0x1F
    check("@GetSpellCast asks opt_itemspell", jsl_count(img, "opt_itemspell", CHUNK_OPT_BANK), 1)
    lo = img * 0x10000 + 0x8000
    bank = bytes(ROMDATA[lo:lo + 0x8000])
    #  The hook in the patched bytes: five where TAX DEX LDY btlcmd_curchar
    #  were, between the record's LDA ($88),Y and LDA #$10, JMP onward.
    a = SYM["opt_itemspell"]
    k = bank.find(bytes([0xB1, 0x88, 0x22, a & 0xFF, a >> 8, CHUNK_OPT_BANK, 0xEA, 0xA9, 0x10, 0x4C]))
    check("the hook: JSL and NOP between the spell byte and LDA #$10", k >= 0, True)
    target = bank[k + 10] | bank[k + 11] << 8

    def path(start):
        """The menu's choice, from LDA $89: index to item to record pointer."""
        k = bank.find(bytes([0xA5, 0x89, 0xAC, 0x7A, 0x6B, 0x18, 0x69, start, 0x99, 0x9F, 0x68, 0xA5, 0x89, 0x20]))
        check("the item path for $%02X, found once" % start,
              (k >= 0, bank.find(bytes([0xA5, 0x89, 0xAC, 0x7A, 0x6B, 0x18, 0x69, start]), k + 1)), (True, -1))
        return 0x8000 + k

    #  One machine, its world built, as a battle's always is: Use reads the
    #  spell through the gear cache now (item magic), and a cold cache is a
    #  build inside the step budget.  Warming one machine per call was two
    #  thousand builds' worth of snapshots, and PyPy's ARM64 JIT fell over on
    #  the trace.  Each call resets what it reads.
    wbus, wcpu = machine()
    fresh = (wcpu.s, wcpu.p, wcpu.e, wcpu.d)
    call(wcpu, "rando_ensure", bank=RANDO_BANK)

    def use(start, i, bits, char):
        bus, cpu = wbus, wcpu
        cpu.s, cpu.p, cpu.e, cpu.d = fresh
        setblk(bus, FB, bits)
        bus.sram[CURCHAR - 0x6000] = char
        for c in range(4):
            bus.sram[CMDITEM - 0x6000 + c] = STAVES[c & 1][1]      # decoys
        bus.wram[0x89] = i
        cpu.dbr, cpu.pbr, cpu.pc = BANK_0C, BANK_0C, path(start)
        for _ in range(400):
            if cpu.pbr == BANK_0C and cpu.pc == target:
                return (cpu.a & 0xFF, cpu.x & 0xFF, cpu.y & 0xFF, bus.sram[CMDITEM - 0x6000 + char])
            cpu.step()
        return "never reached SetCharacterBattleCommand"

    for start, n in ((0x1C, 40), (0x44, 40)):
        bad = []
        for i in range(n):
            for char in range(4):
                off = use(start, i, 0, char)
                for bits in BITS:
                    want = off
                    for fm, item, idx, byte, _ in STAVES:
                        if (start, i) == (0x1C, idx) and bits & fm:
                            want = (0x10, byte - 1, char, item)
                    got = use(start, i, bits, char)
                    if got != want:
                        bad.append("item $%02X char %d bits $%02X: %s, off %s" % (start + i, char, bits, got, off))
        check("Use, items $%02X-: only a flagged staff casts its spell" % start, bad[:4], [])
    check("...and off, the Power Staff casts nothing, the Wizard Staff CONF",
          (use(0x1C, 27, 0, 2), use(0x1C, 32, 0, 1)), ((0x10, 0xFF, 2, 0x37), (0x10, 0x1E, 1, 0x3C)))
    check("...on, RUSE (spell 3) and NUKE (spell $3C)",
          (use(0x1C, 27, RUSE, 2), use(0x1C, 32, NUKE, 1)), ((0x10, 3, 2, 0x37), (0x10, 0x3C, 1, 0x3C)))
    check("...as the Defense sword casts RUSE either way",
          [use(0x1C, 31, bits, 1)[1] for bits in (0,) + BITS], [3] * (1 + len(BITS)))

    #  The equipment text's reader: byte 3 of weapons 27 and 32, and nothing else.
    bad = []
    for i in range(40):
        for y in range(8):
            got = []
            for bits in (0,) + BITS:
                bus, cpu = machine()
                setblk(bus, FB, bits)
                cpu.a, cpu.x, cpu.y = 0x5A00, i, y
                call(cpu, "opt_weapbyte", dbr=CHUNK_OPT_BANK)
                got.append((cpu.a, cpu.x, cpu.y, bool(cpu.p & 0x02)))
            a0 = got[0][0] & 0xFF
            if got[0] != (0x5A00 | a0, i, y, a0 == 0):
                bad.append("weapon %d byte %d off: %s" % (i, y, got[0]))
            for bits, g in zip(BITS, got[1:]):
                want = got[0]
                for fm, item, idx, byte, _ in STAVES:
                    if (i, y) == (idx, 3) and bits & fm:
                        want = (0x5A00 | byte, i, y, False)
                if g != want:
                    bad.append("weapon %d byte %d bits $%02X: %s, off %s" % (i, y, bits, g, got[0]))
    check("opt_weapbyte: only a flagged staff's spell byte, RUSE's 4 and NUKE's $3D", bad[:4], [])
    #  And as the text reads in a chest's box, the spell's name spelled out.
    OPTDESC_A, OPTCTX_A, DLG_ITEMID, OPTCTX_CHEST = 0x6E50, 0x6EC1, 0x61, 3

    def text(item, bits):
        bus, cpu = machine()
        setblk(bus, FB, bits)
        bus.sram[OPTCTX_A - 0x6000] = OPTCTX_CHEST
        bus.wram[DLG_ITEMID] = item
        cpu.a = item
        call(cpu, "opt_descgear")
        buf = bytes(bus.sram[OPTDESC_A - 0x6000: OPTDESC_A - 0x6000 + 0x50])
        return buf[:buf.find(0)]
    ruse, nuke, conf = bytes([0x9B, 0x9E, 0x9C, 0x8E]), bytes([0x97, 0x9E, 0x94, 0x8E]), bytes([0x8C, 0x98, 0x97, 0x8F])
    on, off, defense = text(0x37, RUSE), text(0x37, 0), text(0x3B, RUSE)
    check("the Power Staff's text: off, no spell", ruse in off, False)
    tail = on[len(off):]
    check("...on, the same text and the Defense sword's cast line, RUSE",
          (on.startswith(off), len(tail) > len(ruse), tail.endswith(ruse), defense.endswith(tail)),
          (True, True, True, True))
    on, off = text(0x3C, NUKE), text(0x3C, 0)
    check("the Wizard Staff's text: off, CONF and no NUKE", (off.count(conf), nuke in off), (1, False))
    check("...on, the same text, NUKE for CONF", on, off.replace(conf, nuke))
    check("...each staff's text deaf to the other's flag and the byte's other bits",
          [text(item, bits) == text(item, 0) for fm, item, _, _, _ in STAVES for bits in BITS if not bits & fm],
          [True] * 4)

    #  The name: the spell, two spaces, the staff, a bonus's digits on it as
    #  on any name; everything else, gear or not, as with the flag off.
    nb = K["OPTNAMEBUF"] - 0x6000

    def name(item, bits, seed=0x0BADF00D, bless=0, curse=0):
        bus, cpu = machine()
        setgear(bus, seed, bless, curse)
        warm(bus)
        setblk(bus, FB, bits)
        bus.sram[nb:nb + 8] = b"\x9a" * 8       # a decoy: the last name built
        cpu.a, cpu.y = item, 0x5A
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        p = (cpu.a & 0xFF) | (cpu.x & 0xFF) << 8
        return p, bytes(bus.read(0xA1 + 0x0A, p + k) for k in range(8)), cpu.y
    bad = [i for i in range(256) if i not in (0x37, 0x3C)
           and name(i, RUSE | NUKE, 77, 3, 3) != name(i, 0, 77, 3, 3)]
    check("every other name the same with the flags on", bad, [])
    for (fm, item, idx, byte, want_name), rom in zip(STAVES, (
            bytes([0x99, 0xB2, 0xBA, 0xA8, 0xB5, 0xFF, 0xD8, 0x00]),     # Power
            bytes([0xA0, 0xAC, 0xBD, 0xA4, 0xB5, 0xA7, 0xD8, 0x00]))):   # Wizard
        at = (1 + 0x0A) * 0x10000 + 0xB700 + item * 2
        plain = (ROMDATA[at] | ROMDATA[at + 1] << 8, rom, 0x5A)
        check("item $%02X, off: the ROM's name and the staff, through its pointer" % item,
              [name(item, bits) for bits in (0,) + BITS if not bits & fm], [plain] * 3)
        check("...on: its spell and the staff, in the buffer, Y kept",
              [name(item, bits) for bits in BITS if bits & fm],
              [(K["OPTNAMEBUF"], want_name + b"\0", 0x5A)] * 3)
        for sign in (1, -1):
            seed = next(sd for sd in range(1, 4000)
                        if R.build_gear(ROMDATA, sd, 4, 4)[1][idx] * sign > 0)
            b = R.build_gear(ROMDATA, seed, 4, 4)[1][idx]
            w = bytearray(want_name)
            w[5], w[4] = 0x80 + abs(b), 0xC1 if b > 0 else 0xC2
            check("...blursed %+d: the sign and digit before the staff" % b,
                  name(item, fm, seed, 4, 4), (K["OPTNAMEBUF"], bytes(w) + b"\0", 0x5A))


def test_casteritem():
    """Starting caster item: FFR's StartingEquipmentRandomCasterItem.  New
    Game gives the first character one weapon or armour, unequipped, dealt
    evenly from those whose spell GetCasterItemPool keeps, weapons first, by
    the seed's own stream.  The pool is transcribed from FFR's rule and the
    ROM's tables; the rule itself is swept over every spell byte, under the
    flags off and every flag on, through the gear cache."""
    CH, WEAP, ARM = 0x100, 0x118, 0x11C          # ch_stats, ch_weapons, ch_armor
    FB, RUSE, NUKE = OPT_FLAGS + 5, K["OPTFM_RUSESTAFF"], K["OPTFM_NUKESTICK"]
    check("the caster item is OPT_STARTITEMS's top bit, the set below it",
          (K["STARTITEMS_CASTER"], K["STARTITEMS_SET"], K["CASTER_SHIFT"]), (0x80, 0x0F, 7))
    check("...and its own stream", R.STREAM_CASTER, 0x43415354)
    MAGIC_ROM = GEAR_ROM + 40 * 8 + 40 * 4

    def ffr_good(routine, eff):
        """GetCasterItemPool: Damage, DamageUndead, Fast, FullHeal, Heal,
        InflictStatus with exactly Death, Confuse or Stone, Lock, PowerWord,
        Ruse, Sabr -- FFR's SpellRoutine values, Magic.cs."""
        return (routine in (0x01, 0x02, 0x0C, 0x0F, 0x07, 0x0E, 0x12, 0x10, 0x0D)
                or routine == 0x03 and eff in (0x01, 0x80, 0x02))

    def rom_byte(g):
        """The spell byte of gear g, 0-39 weapons and 40-79 armour, from ROM."""
        return ROMDATA[GEAR_ROM + g * 8 + 3] if g < 40 else ROMDATA[GEAR_ROM + 320 + (g - 40) * 4 + 3]

    def pool(bits):
        out = []
        for g in range(80):
            b = rom_byte(g)
            if g == 27 and bits & RUSE:
                b = 4
            if g == 32 and bits & NUKE:
                b = 0x3D
            if 1 <= b <= 64:
                rec = ROMDATA[MAGIC_ROM + (b - 1) * 8: MAGIC_ROM + b * 8]
                if ffr_good(rec[4], rec[1]):
                    out.append(g)
        return out
    VANILLA = [28, 29, 30, 31, 32, 35, 36, 40 + 14, 40 + 15, 40 + 30, 40 + 36, 40 + 37]
    check("the vanilla pool: Light Axe to Bane Sword, White and Black Shirts, "
          "Heal Helm, Zeus and Power Gauntlets", pool(0), VANILLA)
    check("...the RUSE Staff joins it; the NUKE Stick was in it as the Wizard Staff",
          (pool(RUSE), pool(NUKE)), (sorted(VANILLA + [27]), VANILLA))

    #  The draw: one number below n from the seed's CAST stream, X and Y kept.
    bad = []
    for seed in SEEDS + (R.STREAM_CASTER,):
        for n in (1, 2, 3, 12, 13, 80, 128, 255):
            bus, cpu = machine()
            setsave(bus, seed, 0)
            cpu.a, cpu.x, cpu.y = n, 0x5A, 0xA5
            call(cpu, "rando_caster", bank=RANDO_BANK)
            got = (cpu.a & 0xFF, cpu.x & 0xFF, cpu.y & 0xFF)
            want = (R.Stream(seed, R.STREAM_CASTER).below(n), 0x5A, 0xA5)
            if got != want:
                bad.append("seed %08X n %d: %s, want %s" % (seed, n, got, want))
    check("rando_caster: the CAST stream's draw", bad[:4], [])

    #  The rule, over every spell byte, in a weapon's place and an armour's,
    #  first and last: the cache's byte poked, the spell's record as the
    #  battle has it (opt_spellbyte) put to FFR's rule.
    WC = rw("RW_WEAPONS")
    for flags in (0, 0xFF):
        bus, cpu = machine()
        setsave(bus, 0x12345678, 0)
        warm(bus)
        for i in range(6):
            setblk(bus, OPT_FLAGS + i, flags)
        rec = {}
        for sp in range(64):
            for y in (1, 4):
                cpu.x, cpu.y = sp, y
                call(cpu, "opt_spellbyte", dbr=CHUNK_OPT_BANK)
                rec[sp, y] = cpu.a & 0xFF
        bad = []
        for g, at in ((0, WC + 3), (39, WC + 39 * 8 + 3), (40, WC + 320 + 3), (79, WC + 320 + 39 * 4 + 3)):
            keep = bus.wram[at]
            for b in range(256):
                if g == 27 or g == 32:
                    continue
                bus.wram[at] = b
                cpu.x, cpu.y = g, 0x77
                call(cpu, "opt_castergood")
                got = (bool(cpu.p & 1), cpu.x & 0xFF, cpu.y & 0xFF)
                want = (1 <= b <= 64 and ffr_good(rec[b - 1, 4], rec[b - 1, 1]), g, 0x77)
                if got != want:
                    bad.append("gear %d byte $%02X: %s, want %s" % (g, b, got, want))
            bus.wram[at] = keep
        check("opt_castergood, flags $%02X: FFR's rule over every byte" % flags, bad[:4], [])
        check("...and the sweep met both answers",
              len({ffr_good(rec[sp, 4], rec[sp, 1]) for sp in range(64)}), 2)

    def ch_page(bus):
        return bytes(bus.sram[CH:CH + 0x100])

    #  The deal, from a warm cache: the stat page empty but for the one slot.
    def deal(seed, bits=0, poke=None):
        bus, cpu = machine()
        setsave(bus, seed, 0)
        warm(bus)
        setblk(bus, FB, bits)
        if poke is not None:
            for g in range(80):
                at = WC + g * 8 + 3 if g < 40 else WC + 320 + (g - 40) * 4 + 3
                bus.wram[at] = poke.get(g, 0)
        bus.sram[CH:CH + 0x100] = bytes(0x100)
        call(cpu, "opt_casteritem")
        return ch_page(bus)

    def want_page(g):
        page = bytearray(0x100)
        if g is not None:
            if g < 40:
                page[WEAP - CH] = g + 1
            else:
                page[ARM - CH] = g - 40 + 1
        return bytes(page)
    bad = []
    for seed in SEEDS + tuple(range(3, 40)):
        for bits in (0, RUSE, NUKE):
            pl = pool(bits)
            g = pl[R.Stream(seed, R.STREAM_CASTER).below(len(pl))]
            if deal(seed, bits) != want_page(g):
                bad.append("seed %08X bits $%02X: want gear %d" % (seed, bits, g))
    check("opt_casteritem: the seed's draw from the pool, in its slot", bad[:4], [])
    #  The ends of the walk and the armour's arithmetic: a pool of one, at
    #  each end of each table; and none, which gives nothing.
    for g in (0, 39, 40, 79):
        check("a pool of gear %d alone" % g, deal(7, 0, {g: 0x01}), want_page(g))
    check("an empty pool gives nothing", deal(7, 0, {}), want_page(None))
    #  ...and pools of two across the ends, so a walk begun late or counted
    #  in the wrong order deals the other one.
    bad = []
    for pair in ((0, 40), (39, 79), (0, 79), (0, 1)):
        for seed in range(8):
            g = pair[R.Stream(seed, R.STREAM_CASTER).below(2)]
            if deal(seed, 0, {pair[0]: 0x01, pair[1]: 0x01}) != want_page(g):
                bad.append("gear %d and %d, seed %d: want %d" % (pair + (seed, g)))
    check("pools of two: the draw's one", bad, [])
    check("...nor does a pool of spells FFR leaves out (SLEP, SLOW, LIFE)",
          deal(7, 0, {3: 0x06, 44: 0x10, 77: 0x22}), want_page(None))

    #  New Game itself: the flag on, the set beside it untouched; off, nothing;
    #  and the slot outlives the class's starting stats.
    TENT = 0x36
    pool_at = K["RANDO_POOL"] - 0x6000

    def newgame(seed, items, bits=0):
        bus, cpu = machine()
        bus.sram[pool_at:pool_at + 4] = seed.to_bytes(4, "little")
        setblk(bus, FB, bits)
        setblk(bus, OPT_STARTITEMS, items)
        bus.sram[CH:CH + 0x100] = bytes(0x100)
        call(cpu, "opt_freestuff")
        return bus, cpu
    for seed, items, bits in ((0x12345678, 0x80, 0), (0xDEADBEEF, 0x84, RUSE), (5, 0x88, RUSE | NUKE),
                              (6, 0x8F, 0), (9, 0xFF, NUKE)):
        bus, cpu = newgame(seed, items, bits)
        pl = pool(bits)
        g = pl[R.Stream(seed, R.STREAM_CASTER).below(len(pl))]
        set_ = items & 0x0F
        check("New Game, seed %08X, items $%02X: the caster item" % (seed, items), ch_page(bus), want_page(g))
        sets = [(0,) * 6, None, None, None, (10, 0, 0, 50, 4, 2), None, None, None, (99,) * 6]
        want = sets[set_] if set_ < 9 else (0,) * 6
        check("...and the starting set beside it", tuple(bus.sram[TENT:TENT + 6]), want)
        for c in range(4):
            bus.sram[CH + c * 0x40] = c                  # Fighter, Thief, BB, RM
        call(cpu, "NewGame_LoadStartingStats")
        check("...still there after the starting stats",
              (bus.sram[WEAP], bus.sram[ARM]), (want_page(g)[WEAP - CH], want_page(g)[ARM - CH]))
    for items in (0x00, 0x04, 0x7F):
        bus, cpu = newgame(0x12345678, items, RUSE | NUKE)
        check("New Game, items $%02X: no caster item" % items, ch_page(bus), want_page(None))


def test_lockpick():
    """Thief lockpicking: FFR's Lockpicking (1B_9300_LockpickDoors).  A locked
    door opens without the KEY if any character is a Thief or Ninja whose
    level is the setting's or above -- class and level only, as FFR checks.
    opt_lockpick swept over every setting, every slot, every class and the
    levels about each threshold, the other characters decoys; then the door
    itself, through SMMove_Door's patched bytes in the fixed bank."""
    TH, NJ, NONE = 1, 7, K["CLS_NONE"]
    LEVELS = (None, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50)
    check("lockpicking is OPT_THIEFHIT's top four bits, Thief hit the bottom two",
          (K["LOCKPICK_FIELD"], K["LOCKPICK_SHIFT"], K["THIEFHIT_FIELD"], K["LOCKPICK_STEPS"]),
          (0xF0, 4, 0x03, 12))
    KEY, CH, CLASS, LEVEL = 0x25, 0x100, 0x00, 0x26     # item_mystickey; ch_stats
    TILEPROP1, INROOM, SHOP, ENTERING = 0x45, 0x0D, 0x62, 0x50

    bus, cpu = machine()

    def pick(setting, party, key=0, hit=2):
        setblk(bus, OPT_THIEFHIT, setting << 4 | hit)
        bus.sram[KEY] = key
        for c, (cls, lvl) in enumerate(party):
            bus.sram[CH + c * 0x40 + CLASS] = cls
            bus.sram[CH + c * 0x40 + LEVEL] = lvl
        bus.wram[TILEPROP1] = 0x33
        cpu.a, cpu.x, cpu.y = 0x02, 0x99, 0x77
        call(cpu, "opt_lockpick")
        x = cpu.x & 0xFF
        return (x != 0, bool(cpu.p & 0x02) == (x == 0), cpu.a & 0xFF, cpu.y & 0xFF, bus.wram[TILEPROP1])

    def ffr(setting, party, key=0):
        if key:
            return True
        if not 1 <= setting < len(LEVELS):
            return False
        return any(cls in (TH, NJ) and lvl + 1 >= LEVELS[setting] for cls, lvl in party)

    bad = []
    for setting in range(16):
        thr = LEVELS[setting] - 1 if 1 <= setting < len(LEVELS) else 20
        decoys = [(0, 255),
                  (TH, thr - 1) if thr > 0 else (6, 255),
                  (NJ, thr - 1) if thr > 0 else (8, 255)]
        for slot in range(4):
            for cls in list(range(12)) + [NONE]:
                for lvl in sorted({max(thr - 2, 0), max(thr - 1, 0), thr, thr + 1, 0, 49, 255}):
                    party = decoys[:slot] + [(cls, lvl)] + decoys[slot:]
                    got = pick(setting, party)
                    want = (ffr(setting, party), True, 0x02, 0x77, 0)
                    if got != want:
                        bad.append("setting %d slot %d class %d level %d: %s, want %s"
                                   % (setting, slot, cls, lvl, got, want))
    check("opt_lockpick: a Thief or Ninja of the level, anywhere in the party", bad[:4], [])
    nobody = [(0, 255), (2, 255), (3, 255), (5, 255)]
    check("...and the KEY opens any door, at every setting, a Thief or not",
          [pick(s, nobody, key)[0] for s in range(16) for key in (1, 0xFF)], [True] * 32)
    check("...the Thief hit step beside it changes nothing",
          [pick(4, [(TH, 14)] + nobody[1:], 0, hit)[0] for hit in range(4)]
          + [pick(4, [(TH, 13)] + nobody[1:], 0, hit)[0] for hit in range(4)], [True] * 4 + [False] * 4)
    check("...a dead Thief still knows how, as in FFR",
          pick(1, [(TH, 0)] + nobody[1:]), (True, True, 0x02, 0x77, 0))

    #  The door: SMMove_Door's seven bytes from LDX #0 to LDX item_mystickey
    #  are the JSL and three NOPs, and the rest is the game's own.
    door = SYM["SMMove_Door"]
    a = SYM["opt_lockpick"]
    got = bytes(bus.read(0xA7, door + k) for k in range(16))
    check("SMMove_Door: LSR, AND, CMP, BNE, then the JSL, three NOPs and the BNE",
          (got[:5], got[5], got[7:14], got[14], got[6] - got[15]),
          (bytes([0x4A, 0x29, 0x03, 0xC9, 0x02]), 0xD0,
           bytes([0x22, a & 0xFF, a >> 8, CHUNK_OPT_BANK, 0xEA, 0xEA, 0xEA]), 0xD0,
           16 - 7))                             # both BNEs land on @OpenDoor

    def walk(tp, setting, party, key=0):
        dbus, dcpu = machine()
        setblk(dbus, OPT_THIEFHIT, setting << 4)
        dbus.sram[KEY] = key
        for c, (cls, lvl) in enumerate(party):
            dbus.sram[CH + c * 0x40 + CLASS] = cls
            dbus.sram[CH + c * 0x40 + LEVEL] = lvl
        for z, v in ((TILEPROP1, 0x33), (INROOM, 0), (ENTERING, 0), (0x20, 0), (0x2F, 0), (0x14, 0)):
            dbus.wram[z] = v
        dcpu.a = tp
        call(dcpu, "SMMove_Door")
        return (not dcpu.p & 1, dbus.wram[INROOM], dbus.wram[ENTERING])
    LOCKED, DOOR = 0x04, 0x02
    thief15, thief14 = [(TH, 14)] + nobody[1:], [(TH, 13)] + nobody[1:]
    check("a locked door, Lv15, a level-15 Thief: in, no shop", walk(LOCKED, 4, thief15), (True, 2, 0))
    check("...a level-14 Thief: not", walk(LOCKED, 4, thief14), (False, 0, 0))
    check("...a level-15 Ninja last in line: in", walk(LOCKED, 4, nobody[1:] + [(NJ, 14)]), (True, 2, 0))
    check("...Off, a level-50 Thief: not", walk(LOCKED, 0, [(TH, 49)] + nobody[1:]), (False, 0, 0))
    check("...Off, the KEY: in", walk(LOCKED, 0, nobody, 1), (True, 2, 0))
    check("an open door, Off: in, and a shop behind it still a shop",
          walk(DOOR, 0, nobody), (True, 1, 1))


def test_itemmagic():
    """Item magic: FFR's ShuffleItemMagic with its All and Balanced pools.
    Every item that casts a spell on the cartridge casts another, dealt
    without repeats from the pool, weapons first, and is named for it; the
    RUSE Staff and the NUKE Stick stand over the deal.  The pools are held
    to a transcription of FFR's rules here, the deal to randoref's, and every
    reader -- the records, the names, battle's Use, the caster pool -- to
    the deal."""
    FIELD, SHIFT = K["ITEMMAGIC_FIELD"], K["ITEMMAGIC_SHIFT"]
    check("item magic is RANDO_MAGIC's bits 4-5, the levels shuffle bits 0-1",
          (FIELD, SHIFT, K["MAGIC_FIELD"], K["ITEMMAGIC_MODES"]), (0x30, 4, 0x03, 3))
    check("...its own stream", R.STREAM_ITEMMAGIC, 0x494D4147)
    MAGIC_ROM = GEAR_ROM + 480
    recs = [ROMDATA[MAGIC_ROM + i * 8:MAGIC_ROM + i * 8 + 8] for i in range(64)]

    def balanced_ok(d):
        """GetBalancedSpells, ItemMagic.cs, rule by rule: d[1] effectivity,
        d[2] element, d[3] target, d[4] routine."""
        e, el, t, rt = d[1], d[2], d[3], d[4]
        drops = [rt == 0x0D and t != 0x04,                 # attack up, not on self
                 rt == 0x0C,                                # doubles hit rate
                 rt == 0x01 and e > 55 and el == 0,        # strong, non-elemental
                 rt == 0x01 and e > 70 and t == 0x01,      # strong, every enemy
                 rt == 0x01 and e > 100,
                 rt == 0x01 and e < 20,
                 rt == 0x08 and (e & 0b01010000) == 0,     # cures neither stun nor mute
                 rt == 0x0F,                                # HP max
                 rt == 0x02 and e > 120,
                 rt == 0x12 and (e & 0b11) != 0 and el == 0,
                 rt == 0x03 and (e & 0b11010011) == 0,
                 rt == 0x12 and (e & 0b11010011) == 0,
                 rt == 0x10 and e > 80,
                 rt == 0x09 and e > 32,
                 rt == 0x0A and e == 0xFF]
        return not any(drops)
    want_all = [i for i in range(64) if recs[i][4] != 0]
    want_bal = [i for i in want_all if balanced_ok(recs[i])]
    #  The generator's rule (randoref's) against this one, over records the
    #  cartridge does not have: most of FFR's removals touch none of its 64.
    bad = []
    for rt in range(0x14):
        for tgt in (0x01, 0x02, 0x04, 0x08, 0x10):
            for el in (0x00, 0x01, 0x10):
                for e in range(256):
                    d = bytes([0, e, el, tgt, rt, 0, 0, 0])
                    if rt and R.balanced_drops(d) == balanced_ok(d):
                        bad.append("routine $%02X target $%02X element $%02X eff %d" % (rt, tgt, el, e))
    check("randoref's Balanced rule is FFR's, over every synthetic record", bad[:4], [])
    bus, cpu = machine()

    def table(name, n):
        a = SYM[name]
        return [bus.read(RANDO_BANK, a + k) for k in range(n)]
    check("the All pool: every spell with a battle routine, and no more",
          (table("lut_IMAll", len(want_all)), SYM["lut_IMBal"] - SYM["lut_IMAll"]), (want_all, len(want_all)))
    check("the Balanced pool: FFR's removals", table("lut_IMBal", len(want_bal)), want_bal)
    check("...and no more", (SYM["IM_ALL_N"], SYM["IM_BAL_N"]), (len(want_all), len(want_bal)))

    def names(ids):
        return sorted(R.item_name(ROMDATA, 0xB0 + i).strip() for i in ids)
    check("...All leaves out the five spells for the field",
          names(set(range(64)) - set(want_all)), sorted(["LIFE", "LIF2", "WARP", "EXIT", "SOFT"]))
    check("...Balanced, NUKE and FADE, CUR4 and FAST, among others; BANE and XXXX stay",
          ({"NUKE", "FADE", "CUR4", "FAST", "WALL", "FIRE"} <= set(names(set(want_all) - set(want_bal))),
           {"BANE", "XXXX", "FIR2", "HEAL"} <= set(names(want_bal))), (True, True))

    def rom_byte(g):
        return ROMDATA[GEAR_ROM + R.gear_spell_at(g)]
    CASTERS = [g for g in range(80) if rom_byte(g)]
    check("the dealt: the cartridge's twelve casting items", len(CASTERS), 12)

    #  The deal, in the cache, beside blursings and the levels shuffle.
    bad = []
    for seed in SEEDS:
        for mode in (0, 1, 2, 3):
            for levels, bless, curse in ((0, 0, 0), (1, 3, 2)):
                bus, cpu = machine()
                setgear(bus, seed, bless, curse)
                bus.sram[K["RANDO_MAGIC"] - 0x6000] = mode << SHIFT | levels
                call(cpu, "rando_ensure", bank=RANDO_BANK)
                got, bonus = gear_cache(bus)
                t, wb = R.build_gear(ROMDATA, seed, bless, curse)
                t = bytearray(t)
                deal = R.build_itemmagic(ROMDATA, seed, mode)
                for g, b in deal.items():
                    t[R.gear_spell_at(g)] = b
                pool = {1: want_all, 2: want_bal}.get(mode, [])
                spells = [b - 1 for b in deal.values()]
                ok = (got == bytes(t) and bonus == wb and sorted(deal) == (CASTERS if pool else [])
                      and len(set(spells)) == len(spells) and set(spells) <= set(pool))
                p = rw("RW_PERM")
                perm = list(bus.wram[p:p + 64])
                if not ok or perm != list(R.build_magic(seed, levels)[0]):
                    bad.append("seed %08X mode %d levels %d blurse %d/%d" % (seed, mode, levels, bless, curse))
    check("the gear cache: each casting item's spell dealt, distinct, from the pool", bad[:4], [])
    #  The walk's two ends, which cast nothing on the cartridge: a copy in
    #  which the first weapon and the last armour cast CURE.
    rom = bytearray(ROMDATA)
    for g in (0, 79):
        rom[GEAR_ROM + R.gear_spell_at(g)] = 0x01
    bus, cpu = machine()
    bus.rom = rom
    setgear(bus, 0x12345678, 0, 0)
    bus.sram[K["RANDO_MAGIC"] - 0x6000] = 1 << SHIFT
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    deal = R.build_itemmagic(rom, 0x12345678, 1)
    got = gear_cache(bus)[0]
    check("...the first and the last piece of gear dealt, when they cast",
          (sorted(deal)[0], sorted(deal)[-1], {g: got[R.gear_spell_at(g)] for g in deal}), (0, 79, deal))

    #  The readers, from one warm world: the record bytes, battle's Use, the
    #  names, the caster pool.  The staves over the deal.
    FB, RUSE, NUKE = OPT_FLAGS + 5, K["OPTFM_RUSESTAFF"], K["OPTFM_NUKESTICK"]
    seed, mode, bless, curse = 0x0BADF00D, 2, 3, 3
    deal = R.build_itemmagic(ROMDATA, seed, mode)
    bonus = R.build_gear(ROMDATA, seed, bless, curse)[1]

    def world(m=mode, rom=None):
        bus, cpu = machine()
        if rom is not None:
            bus.rom = rom
        setgear(bus, seed, bless, curse)
        bus.sram[K["RANDO_MAGIC"] - 0x6000] = m << SHIFT
        if rom is None:
            warm(bus)
        return bus, cpu

    def effective(g, bits):
        if g == 27 and bits & RUSE:
            return 4
        if g == 32 and bits & NUKE:
            return 0x3D
        return deal.get(g, rom_byte(g))
    bad = []
    for bits in (0, RUSE | NUKE):
        bus, cpu = world()
        setblk(bus, FB, bits)
        for g in range(80):
            cpu.a, cpu.x, cpu.y = 0, g if g < 40 else g - 40, 3
            call(cpu, "opt_weapbyte" if g < 40 else "opt_armbyte", dbr=CHUNK_OPT_BANK)
            rec = cpu.a & 0xFF
            for char in (0, 3):
                bus.sram[0x6B7A - 0x6000] = char
                bus.sram[0x689F - 0x6000 + char] = 0x1C + g
                cpu.y = 0x55
                call(cpu, "opt_itemspell")
                use = (cpu.x & 0xFF, cpu.y & 0xFF)
                if (rec, use) != (effective(g, bits), ((effective(g, bits) - 1) & 0xFF, char)):
                    bad.append("gear %d bits $%02X char %d: record %d, use %s" % (g, bits, char, rec, use))
    check("the record and battle's Use: the deal, the staves over it", bad[:4], [])

    def spell_bytes(sp):
        bank = (1 + 0x0A) * 0x10000
        q = bank + 0xB700 + (0xB0 + sp) * 2
        at = bank + (ROMDATA[q] | ROMDATA[q + 1] << 8)
        nm = bytes(ROMDATA[at:at + 4])
        return nm[:nm.index(0)] + b"\xff" * (4 - nm.index(0)) if 0 in nm else nm

    def want_name(item, bits):
        g = item - 0x1C
        rom_name = R.blursed_name_bytes(ROMDATA, item, 0)
        if not 0 <= g < 80:
            return None
        if (g == 27 and bits & RUSE) or (g == 32 and bits & NUKE):
            base = bytearray((b"RUSE" if g == 27 else b"NUKE").translate(
                bytes.maketrans(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ", bytes(range(0x8A, 0xA4))))
                + b"\xff\xff\xd8")
        elif g in deal:
            icon = rom_name[6] if rom_name[6] > 200 and rom_name[6] != 0xFF else 0xFF
            base = bytearray(spell_bytes(deal[g] - 1) + b"\xff\xff" + bytes([icon]))
        else:
            return None
        b = bonus[g]
        if b:
            i = 5 if (base[6] > 200 and base[6] != 0xFF) else 6
            base[i] = 0x80 + abs(b)
            base[i - 1] = 0xC1 if b > 0 else 0xC2
        return bytes(base) + b"\0"
    nb = K["OPTNAMEBUF"] - 0x6000

    def drawn(bits, m):
        bus, cpu = world(m)
        setblk(bus, FB, bits)
        out = []
        for item in range(256):
            bus.sram[nb:nb + 8] = b"\x9a" * 8           # a decoy: the last name built
            cpu.a, cpu.y = item, 0x5A
            call(cpu, "rando_nameptr", bank=RANDO_BANK)
            p = (cpu.a & 0xFF) | (cpu.x & 0xFF) << 8
            out.append((p, bytes(bus.read(0xA1 + 0x0A, p + k) for k in range(8)), cpu.y & 0xFF))
        return out
    bad = []
    for bits in (0, RUSE | NUKE):
        on, off = drawn(bits, mode), drawn(bits, 0)
        for item in range(256):
            w = want_name(item, bits)
            want = (K["OPTNAMEBUF"], w, 0x5A) if w is not None else off[item]
            if on[item] != want:
                bad.append("item $%02X bits $%02X: %s, want %s" % (item, bits, on[item], want))
    check("the names: each dealt item its spell's, the staves theirs, the rest as with it off",
          bad[:4], [])
    #  Off, every casting item its own name, blursed as it is.
    off = drawn(0, 0)
    check("off, each casting item named as the cartridge has it",
          [off[0x1C + g][1][:7] for g in CASTERS],
          [R.blursed_name_bytes(ROMDATA, 0x1C + g, bonus[g]) for g in CASTERS])
    #  ...and with no bonuses, the padding bare.
    bless, curse = 0, 0
    bonus = [0] * 80
    on = drawn(0, mode)
    check("no bonuses: each dealt name its spell, two spaces and the icon",
          [on[0x1C + g] for g in CASTERS], [(K["OPTNAMEBUF"], want_name(0x1C + g, 0), 0x5A) for g in CASTERS])
    #  The icon rule over every byte the name's seventh could be: the Defense
    #  sword's, which has none, in a private copy of the cartridge.
    DEFENSE = 0x3B
    q = (1 + 0x0A) * 0x10000 + 0xB700 + DEFENSE * 2
    at7 = (1 + 0x0A) * 0x10000 + (ROMDATA[q] | ROMDATA[q + 1] << 8) + 6
    rom = bytearray(ROMDATA)
    bus, cpu = world(mode, rom)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    bad = []
    for v in range(256):
        rom[at7] = v
        cpu.a, cpu.y = DEFENSE, 0x5A
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        got = bus.sram[nb + 6]
        if got != (v if v > 200 else 0xFF):
            bad.append("seventh byte $%02X: drawn $%02X" % (v, got))
    check("the icon kept above 200, a letter padded over", bad[:4], [])
    bless, curse = 3, 3
    bonus = R.build_gear(ROMDATA, seed, bless, curse)[1]
    check("...a dealt name with a bonus, and one without an icon, among them",
          (any(bonus[g] for g in deal), any(not 200 < R.blursed_name_bytes(ROMDATA, 0x1C + g, 0)[6] < 0xFF
                                            for g in deal)), (True, True))

    #  The starting caster item deals from what the items really cast.
    def caster_good(sb):
        if not 1 <= sb <= 64:
            return False
        d = recs[sb - 1]
        return (d[4] in (0x01, 0x02, 0x0C, 0x0F, 0x07, 0x0E, 0x12, 0x10, 0x0D)
                or d[4] == 0x03 and d[1] in (0x01, 0x80, 0x02))
    bad = []
    for bits in (0, RUSE | NUKE):
        pl = [g for g in range(80) if caster_good(effective(g, bits))]
        bus, cpu = world()
        setblk(bus, FB, bits)
        bus.sram[0x100:0x200] = bytes(0x100)
        call(cpu, "opt_casteritem")
        g = pl[R.Stream(seed, R.STREAM_CASTER).below(len(pl))]
        got = (bus.sram[0x118], bus.sram[0x11C])
        want = (g + 1, 0) if g < 40 else (0, g - 39)
        if got != want:
            bad.append("bits $%02X: %s, want gear %d" % (bits, got, g))
    check("the caster pool: the dealt spells, under FFR's caster rule", bad, [])


def test_palflush():
    """The palette in two halves: pal_prep converts what moved before the
    frame wait, flush_pal sends it in vblank as one DMA (mode 3: CGADD twice,
    CGDATA twice a record).  Each NES entry lands at its CGRAM entry in the
    colour the cartridge's table gives for that emphasis, greyed to the grey
    column under greyscale; nothing else in CGRAM moves; only the entries that
    changed are sent unless everything must be; and a whole palette costs the
    vblank flush a DMA's setup, not two thousand instructions -- the black
    band a damage tile's greyscale flicker ran into the picture."""
    HV, PAL, PREV = 0x0800, 0x4800, 0x4820
    DIRTY, FORCE, EMPH, GREY, SENDN = 0x26, 0x51, 0x3B, 0x3C, 0xCE
    table = SYM["nespal_snes"]

    def cg_entry(y):
        return (y >> 2) * 16 + (y & 3) if y < 16 else 128 + ((y >> 2) - 4) * 16 + (y & 3)

    def colour(bus, c, emph, grey):
        c = c & 0x30 if grey else c & 0x3F
        at = table + (emph * 64 + c) * 2
        return bus.read(0xC0, at) | bus.read(0xC0, at + 1) << 8

    def fresh():
        bus, cpu = machine()
        bus.ppu()
        bus.dma = True
        bus.frames()
        bus.cgram[:] = b"\x5a" * 0x200            # decoys
        return bus, cpu

    def cgram(bus, e):
        return bus.cgram[e * 2] | bus.cgram[e * 2 + 1] << 8
    entries = {cg_entry(y) for y in range(32)}
    check("the 32 NES entries land on 32 CGRAM entries", len(entries), 32)
    import random
    rnd = random.Random(16)
    bad = []
    for emph in range(8):
        for grey in (0, 1):
            bus, cpu = fresh()
            pal = [rnd.randrange(64) for _ in range(32)]
            for y in range(32):
                bus.wram[PAL + y] = pal[y]
                bus.wram[PREV + y] = pal[y]          # as last sent: only force sends
            bus.wram[HV + DIRTY], bus.wram[HV + FORCE] = 1, 1
            bus.wram[HV + EMPH], bus.wram[HV + GREY] = emph, grey
            call(cpu, "hal_waitvbl", bank=0xC0)
            got = [cgram(bus, cg_entry(y)) for y in range(32)]
            want = [colour(bus, pal[y], emph, grey) for y in range(32)]
            rest = {cgram(bus, e) for e in range(256) if e not in entries}
            if got != want or rest != {0x5A5A} or bus.wram[HV + SENDN] or bus.wram[HV + FORCE]:
                bad.append("emphasis %d grey %d" % (emph, grey))
    check("a forced palette: every entry, tinted and greyed, nothing else", bad[:4], [])

    #  Only what moved: two entries changed, a background and a sprite one;
    #  everything else in CGRAM a decoy that must stay.
    bus, cpu = fresh()
    for y in range(32):
        bus.wram[PAL + y] = bus.wram[PREV + y] = y
    bus.wram[PAL + 5], bus.wram[PAL + 22] = 0x30, 0x2A
    bus.wram[HV + DIRTY] = 1
    call(cpu, "hal_waitvbl", bank=0xC0)
    moved = {e for e in range(256) if cgram(bus, e) != 0x5A5A}
    check("unforced: only the two that moved are sent",
          (moved, cgram(bus, cg_entry(5)), cgram(bus, cg_entry(22)), bytes(bus.wram[PREV:PREV + 32])),
          ({cg_entry(5), cg_entry(22)}, colour(bus, 0x30, 0, 0), colour(bus, 0x2A, 0, 0),
           bytes(bus.wram[PAL:PAL + 32])))
    bus.cgram[:] = b"\x5a" * 0x200
    call(cpu, "hal_waitvbl", bank=0xC0)
    check("...and the next frame, nothing", {cgram(bus, e) for e in range(256)}, {0x5A5A})

    #  MapTileDamage's flicker: $2001 written $1E then $1F, frame by frame.
    bus, cpu = fresh()
    pal = [rnd.randrange(64) for _ in range(32)]
    for y in range(32):
        bus.wram[PAL + y] = pal[y]
    bad = []
    for frame in range(6):
        cpu.a = 0x1E | frame & 1
        call(cpu, "hal_w2001", bank=0xC0)
        bus.wram[HV + DIRTY] = 1 if frame == 0 else bus.wram[HV + DIRTY]
        call(cpu, "hal_waitvbl", bank=0xC0)
        if [cgram(bus, cg_entry(y)) for y in range(32)] != [colour(bus, pal[y], 0, frame & 1) for y in range(32)]:
            bad.append(frame)
    check("the damage tile's flicker: grey and back, each frame whole", bad, [])

    #  What it costs the flush in vblank: a whole palette against none.
    def flush_cost(full):
        bus, cpu = fresh()
        for y in range(32):
            bus.wram[PAL + y] = y
        bus.wram[HV + DIRTY], bus.wram[HV + FORCE] = int(full), int(full)
        call(cpu, "pal_prep", bank=0xC0)
        n = [0]
        step = cpu.step

        def counted():
            n[0] += 1
            step()
        cpu.step = counted
        call(cpu, "hal_flush", bank=0xC0)
        return n[0], [cgram(bus, cg_entry(y)) for y in range(32)] == [colour(bus, y, 0, 0) for y in range(32)] if full else True
    (none, _), (whole, landed) = flush_cost(False), flush_cost(True)
    check("a whole palette costs the vblank flush a DMA's setup, and lands",
          (whole - none <= 25, landed), (True, True))


def test_ntflush():
    """The tilemap in VRAM is the HAL's shadow after every flush.  The game's
    own map draws -- DrawMapRowCol's rows and columns, hal_drawattr's
    attributes -- and scattered $2007 writes, frame after frame, each flushed
    by hal_waitvbl with its DMAs run (bus.dma); then every NES row, both
    halves, checked word for word at its own tilemap row and at its duplicate
    thirty below.  And what a walking frame's flush costs, bounded."""
    import random, re as _re
    NTSHADOW, VRAMMAP = 0x1000, 0x0000
    img = 0xA7 & 0x1F
    fixed = bytes(ROMDATA[img * 0x10000 + 0xC000:img * 0x10000 + 0x10000])
    m = list(_re.finditer(rb"\xA6\x30\xBD..\x85\x10\xBD..\x85\x11\xA5\x31\xC9\x10", fixed, _re.S))
    check("DrawMapRowCol found once in the fixed bank", len(m), 1)
    ROWCOL = 0xC000 + m[0].start()

    def clean(bus):
        for r in range(32):
            bus.wram[0x0940 + r], bus.wram[0x0960 + r] = 0xFF, 0x00
        for k, v in ((0x10, 0xFF), (0x11, 0xFF), (0x12, 0), (0x13, 0), (0x16, 0), (0x18, 0), (0x26, 0)):
            bus.wram[0x0800 + k] = v

    def where(r, c):
        """The tilemap words NES row r, column c lands on: itself, and its
        duplicate thirty rows down (rows 30-31 above, then the lower pair of
        quadrants); the right half a quadrant over."""
        half = 0x400 if c >= 32 else 0
        c &= 31
        dup = (30 + r) * 32 if r < 2 else 0x800 + (r - 2) * 32
        return VRAMMAP + half + r * 32 + c, VRAMMAP + half + dup + c

    def mismatches(bus):
        bad = []
        for r in range(30):
            for c in range(64):
                want = bus.wram[NTSHADOW + r * 128 + c * 2] | bus.wram[NTSHADOW + r * 128 + c * 2 + 1] << 8
                for a in where(r, c):
                    got = bus.vram[a * 2] | bus.vram[a * 2 + 1] << 8
                    if got != want:
                        bad.append((r, c, a, got, want))
        return bad

    rnd = random.Random(1016)
    bad = []
    for seed in range(3):
        bus, cpu = machine()
        bus.ppu()
        bus.dma = True
        bus.frames()
        clean(bus)
        for frame in range(40):
            kind = rnd.choice(("row", "col", "col", "attr", "writes"))
            for i in range(0x40):
                bus.wram[0x0780 + i] = rnd.randrange(256)
            bus.wram[0x30], bus.wram[0x31] = rnd.randrange(15), rnd.randrange(32)
            bus.wram[0x2D] = 1 | (2 if kind == "col" else 0)
            if kind in ("row", "col"):
                cpu.dbr = 0xA7
                cpu.run(0xA7, ROWCOL, limit=2_000_000)
            elif kind == "attr":
                for i in range(16):
                    bus.wram[0x07C0 + i] = rnd.randrange(256)
                    bus.wram[0x07D0 + i] = rnd.choice((0x23, 0x27))
                    bus.wram[0x07E0 + i] = 0xC0 + rnd.randrange(60)
                    bus.wram[0x07F0 + i] = 0x03 << 2 * rnd.randrange(4)
                bus.wram[0x2D] = 1 | (2 if rnd.randrange(2) else 0)
                call(cpu, "hal_drawattr", bank=0xC0)
            else:
                for _ in range(rnd.randrange(1, 12)):
                    a = rnd.choice((0x2000, 0x2400)) + rnd.randrange(0x3C0)
                    cpu.a = a >> 8
                    call(cpu, "hal_w2006", bank=0xC0)
                    cpu.a = a & 0xFF
                    call(cpu, "hal_w2006", bank=0xC0)
                    cpu.a = rnd.randrange(256)
                    call(cpu, "hal_w2007", bank=0xC0)
            call(cpu, "hal_waitvbl", bank=0xC0)
            mm = mismatches(bus)
            dirty = [r for r in range(32) if (bus.wram[0x0940 + r], bus.wram[0x0960 + r]) != (0xFF, 0x00)]
            if dirty:
                bad.append("seed %d frame %d (%s): rows still dirty %s" % (seed, frame, kind, dirty[:6]))
                break
            if mm:
                bad.append("seed %d frame %d (%s): %d words, first %s" % (seed, frame, kind, len(mm), mm[0]))
                break
    check("after every flush, VRAM's tilemap is the shadow, and every row clean", bad[:4], [])

    #  What a walking frame's flush costs in vblank, sprites included: a
    #  sideways step's column was 1713 instructions and a row 700-1060 before
    #  the scan stopped switching widths a row and the gather was unrolled
    #  (2026-10-16), and a late-served frame has only 17 lines for it.
    def cost(kind, x, y):
        bus, cpu = machine()
        bus.ppu()
        bus.frames()
        clean(bus)
        for i in range(0x40):
            bus.wram[0x0780 + i] = rnd.randrange(256)
        bus.wram[0x30], bus.wram[0x31], bus.wram[0x2D] = y, x, 1 | (2 if kind == "col" else 0)
        cpu.dbr = 0xA7
        cpu.run(0xA7, ROWCOL, limit=2_000_000)
        bus.wram[0x0818] = 1                    # h_oamdirty: the party moved
        bus.dma = True
        n = [0]
        step = cpu.step

        def counted():
            n[0] += 1
            step()
        cpu.step = counted
        call(cpu, "hal_flush", bank=0xC0)
        return n[0]
    worst = {k: max(cost(k, x, y) for x, y in ((0, 4), (13, 14), (25, 9), (31, 0))) for k in ("row", "col")}
    check("a walking frame's flush: a column under 1150 instructions, a row under 1000",
          (worst["col"] < 1150, worst["row"] < 1000, worst), (True, True, worst))


def test_minimap():
    """MinimapDecompress decodes every row as the map does.  Its run loop was a
    do-while copied from DecompressMap's while: a run of length 1 counted DEY
    to 0, wrapped, and laid 257 tiles (overworld-notes.md section 4) -- never
    on the shipped map, which has no such run, but on any edited one.  Rows
    made here, every run length 0-255 among them, are pointed at through a
    private copy's lut_OWPtrTbl; both of the routine's halves (the row, into
    mm_mapbuf, and the next, into mm_mapbuf2) are held to the game's own
    DecompressMap on the same bytes."""
    import random, re as _re
    MAPROW, BUF, BUF2, MAPDATA = 0x41, 0x0600, 0x0700, 0x7000
    OWBANK = 0xA1 + 0x01                       # BANK_OWMAP's chunk: the table, and the routine
    PTRS = (OWBANK & 0x1F) * 0x10000 + 0x8000  # lut_OWPtrTbl
    img = 0xA7 & 0x1F
    fixed = bytes(ROMDATA[img * 0x10000 + 0xC000:img * 0x10000 + 0x10000])
    m = list(_re.finditer(rb"\xA0\x00\xB1\x10\x10.\xC9\xFF\xF0.\x29\x7F\x85\x14", fixed, _re.S))
    check("DecompressMap found once in the fixed bank", len(m), 1)
    DECOMP = 0xC000 + m[0].start()

    def encode(items):
        out = bytearray()
        for kind, tile, n in items:
            out += bytes([tile]) if kind == "one" else bytes([0x80 | tile, n & 0xFF])
        return bytes(out + b"\xff")

    def tiles(items):
        out = []
        for kind, tile, n in items:
            out += [tile] if kind == "one" else [tile] * (n or 256)
        return out

    rnd = random.Random(1017)

    def rowof(lengths):
        """A row of runs of these lengths, singles filling the rest."""
        items, left = [], 256
        for n in lengths:
            if n > left:
                break
            #  $7E at most: a run of $7F would be $FF, the row's end.
            items.append(("run", rnd.randrange(0x7F) if rnd.randrange(8) else 0x7E, n))
            left -= n
            while left and rnd.randrange(3) == 0:
                items.append(("one", rnd.randrange(0x80), 1))
                left -= 1
        items += [("one", rnd.randrange(0x80), 1) for _ in range(left)]
        return items
    rows = [rowof([1] * 256), [("run", 5, 0)], rowof([255, 1]), rowof([1, 255]),
            [("one", t & 0x7F, 1) for t in range(256)], rowof(list(range(1, 23)))]
    rows += [rowof([rnd.choice((1, 1, 2, 3, rnd.randrange(1, 40))) for _ in range(120)]) for _ in range(40)]
    check("the rows: every one 256 tiles, the length-1 runs and a length-0 among them",
          ({len(tiles(r)) for r in rows}, any(k == "run" and n == 1 for r in rows for k, _, n in r),
           any(k == "run" and n == 0 for r in rows for k, _, n in r)), ({256}, True, True))

    rom = bytearray(ROMDATA)
    SRC = (0x0A00, 0x0D00)                     # bit 6 clear: DecompressMap's bank test

    def decomp(bus, cpu, at):
        """The game's own decoder, as LoadOWMapRow runs it into one row."""
        bus.wram[0x10], bus.wram[0x11] = at & 0xFF, at >> 8
        bus.wram[0x12], bus.wram[0x13] = MAPDATA & 0xFF, MAPDATA >> 8
        cpu.dbr = OWBANK
        cpu.run(0xA7, DECOMP, limit=2_000_000)
        return list(bus.sram[MAPDATA - 0x6000:MAPDATA - 0x6000 + 256])
    bad = []
    for i in range(0, len(rows) - 1):
        for maprow in (5, 127, 255):           # each half of the table, and the wrap
            a, b = rows[i], rows[i + 1]
            bus, cpu = machine()
            bus.rom = rom
            for k, (row, at) in enumerate(((maprow, SRC[0]), ((maprow + 1) & 0xFF, SRC[1]))):
                rom[PTRS + row * 2], rom[PTRS + row * 2 + 1] = at & 0xFF, at >> 8
            ea, eb = encode(a), encode(b)
            bus.wram[SRC[0]:SRC[0] + len(ea)] = ea
            bus.wram[SRC[1]:SRC[1] + len(eb)] = eb
            for z in range(BUF, BUF2 + 256):
                bus.wram[z] = 0xEE                 # decoys
            bus.wram[MAPROW] = maprow
            call(cpu, "MinimapDecompress", bank=OWBANK, dbr=OWBANK)
            got = (list(bus.wram[BUF:BUF + 256]), list(bus.wram[BUF2:BUF2 + 256]))
            want = (decomp(bus, cpu, SRC[0]), decomp(bus, cpu, SRC[1]))
            if got != want or want != (tiles(a), tiles(b)):
                bad.append("rows %d,%d at map row %d: %s" % (i, i + 1, maprow,
                           "mm_mapbuf" if got[0] != want[0] else "mm_mapbuf2"))
    check("each half decodes as DecompressMap, run lengths 0-255", bad[:4], [])

    #  ...and the shipped map, every row, through its own pointers: as it was.
    bus, cpu = machine()
    bad = []
    for maprow in range(0, 256, 2):
        bus.wram[MAPROW] = maprow
        call(cpu, "MinimapDecompress", bank=OWBANK, dbr=OWBANK)
        got = (list(bus.wram[BUF:BUF + 256]), list(bus.wram[BUF2:BUF2 + 256]))
        want = []
        for row in (maprow, maprow + 1):
            ptr = ROMDATA[PTRS + row * 2] | ROMDATA[PTRS + row * 2 + 1] << 8
            want.append(decomp(bus, cpu, ptr))
        if got != tuple(want):
            bad.append(maprow)
    check("the shipped map's 256 rows, as DecompressMap has them", bad[:4], [])


def test_chrflush():
    """The pattern tables in VRAM are the HAL's CHR shadow after every flush.
    A frame that wrote a few words over a wide span sends them through the
    port, one address each; anything else -- many words, a bulk load through
    hal_chrload -- sends the span by DMA.  Frames as the minimap's crests and
    title write them (one byte to each of forty-odd scattered tiles), as its
    rows do, scattered at random, past what the list holds, and bulk, each
    flushed with its DMAs run: VRAM's 16KB of CHR word for word, the list
    empty after.  And a crest frame's flush costs no DMA and a few hundred
    instructions, where the span was 8KB -- 47 scanlines, past vblank."""
    import random
    CREST = [0x0010, 0x0020, 0x0030, 0x0040, 0x0050, 0x0060, 0x0070, 0x0080, 0x00B0, 0x00C0, 0x00D0,
             0x00E0, 0x00F0, 0x0700, 0x0710, 0x0720, 0x0730, 0x0740, 0x0750, 0x0760, 0x0800, 0x0810,
             0x0820, 0x0830, 0x0840, 0x0D00, 0x0D10, 0x0D20, 0x0D30, 0x0D40, 0x0E00, 0x0E10, 0x0E20,
             0x0E30, 0x0E40, 0x0F00, 0x0F10, 0x0F20, 0x0F30, 0x0F40, 0x0F50, 0x0F60, 0x0F70, 0x0F80,
             0x0F90, 0x0FA0, 0x0FB0, 0x0FC0]                    # lut_MinimapDecorCHRDest
    TITLE = [0x0160, 0x0260, 0x02F0, 0x0400, 0x0450, 0x0480, 0x0490, 0x0500, 0x0540, 0x0550, 0x0560,
             0x0570, 0x0580, 0x0590, 0x0600, 0x0610, 0x0640, 0x0650, 0x0660, 0x0670, 0x0680, 0x0690,
             0x06A0, 0x07B0, 0x07C0, 0x07F0, 0x08F0, 0x0900, 0x0910, 0x0A00, 0x0A70, 0x0AA0, 0x0B00,
             0x0B80, 0x0B90, 0x0BA0, 0x0C00, 0x0C20, 0x0C90, 0x0EF0]  # lut_MinimapTitleCHRDest
    HV, QN, CHRSH, VCHR = 0x0800, K["h_chrqn"] - 0x0800, 0x8000, K["VRAM_CHR"] * 2
    check("the list: 64 words at $0D00", (K["CHRQUEUE"], K["CHRQ_CAP"]), (0x0D00, 64))

    def clean(bus):
        for r in range(32):
            bus.wram[0x0940 + r], bus.wram[0x0960 + r] = 0xFF, 0x00
        for k, v in ((0x10, 0xFF), (0x11, 0xFF), (0x12, 0), (0x13, 0), (0x16, 0), (0x18, 0), (0x26, 0)):
            bus.wram[HV + k] = v
        bus.wram[HV + QN] = 0

    def put(bus, cpu, addr, val):
        for v in (addr >> 8, addr & 0xFF):
            cpu.a = v
            call(cpu, "hal_w2006", bank=0xC0)
        cpu.a = val
        call(cpu, "hal_w2007", bank=0xC0)

    rnd = random.Random(1017)
    bus, cpu = machine()
    bus.ppu()
    bus.dma = True
    bus.frames()
    clean(bus)
    END = K["CHRQUEUE"] + 2 * K["CHRQ_CAP"]
    bus.wram[END:END + 2] = b"\xa5\xa5"            # a decoy just past the list
    bad = []
    for frame in range(48):
        kind = rnd.choice(("crest", "title", "row", "scatter", "many", "bulk", "bulk+few"))
        if kind in ("crest", "title"):
            plane = rnd.randrange(16)
            for d in (CREST if kind == "crest" else TITLE):
                put(bus, cpu, rnd.choice((0, 0x1000)) + d + plane, rnd.randrange(256))
        elif kind == "row":
            page, row = rnd.randrange(16), rnd.randrange(8)
            for x in range(row, 256, 8):
                put(bus, cpu, page * 256 + x, rnd.randrange(256))
        elif kind in ("scatter", "many"):
            for _ in range(rnd.randrange(1, 20) if kind == "scatter" else rnd.randrange(60, 120)):
                put(bus, cpu, rnd.randrange(0x2000), rnd.randrange(256))
        else:
            if kind == "bulk+few":                 # a few listed words beside it
                for _ in range(3):
                    put(bus, cpu, rnd.randrange(0x2000), rnd.randrange(256))
            src = 0x0300
            bus.wram[src:src + 256] = bytes(rnd.randrange(256) for _ in range(256))
            at = rnd.randrange(32) * 256
            for v in (at >> 8, at & 0xFF):
                cpu.a = v
                call(cpu, "hal_w2006", bank=0xC0)
            bus.wram[0x10], bus.wram[0x11] = src & 0xFF, src >> 8
            cpu.x, cpu.y = 1, 0
            call(cpu, "hal_chrload", bank=0xC0)
        call(cpu, "hal_waitvbl", bank=0xC0)
        if bytes(bus.vram[VCHR:VCHR + 0x4000]) != bytes(bus.wram[CHRSH:CHRSH + 0x4000]) or bus.wram[HV + QN]:
            diff = next((i for i in range(0x4000) if bus.vram[VCHR + i] != bus.wram[CHRSH + i]), None)
            bad.append("frame %d (%s): first differing shadow byte %s, list %d" % (frame, kind, diff, bus.wram[HV + QN]))
            break
    check("after every flush, VRAM's CHR is the shadow, and the list empty", bad, [])
    check("...and nothing written past the list's 64 words", bytes(bus.wram[END:END + 2]), b"\xa5\xa5")

    #  A crest frame's flush, and a title frame's: no DMA, a few hundred
    #  instructions; a minimap row's, a span short enough to DMA.
    def cost(dests, plane=5):
        bus, cpu = machine()
        bus.ppu()
        bus.frames()
        clean(bus)
        for d in dests:
            put(bus, cpu, d + plane, 0x5A)
        bus.dma = True
        dma, n = [0], [0]
        io, write, step = bus.io, bus.write, cpu.step

        def w(bank, addr, val):
            if (addr & 0xFFFF) == 0x420B and val & 1:
                dma[0] += (io.get(0x4305, 0) | io.get(0x4306, 0) << 8) or 0x10000
            write(bank, addr, val)

        def c():
            n[0] += 1
            step()
        bus.write, cpu.step = w, c
        call(cpu, "hal_flush", bank=0xC0)
        return n[0], dma[0]
    crest, title, row = cost(CREST), cost(TITLE), cost(list(range(0x0500, 0x0600, 8)), 0)
    check("a crest frame: no DMA, under 800 instructions (706); a title frame the same (610)",
          (crest[0] < 800, crest[1], title[0] < 800, title[1]), (True, 0, True, 0))
    check("...a minimap row: its span, by DMA", (row[1] > 0, row[0] < 300), (True, True))


def test_strayobjects():
    """The two stray map objects are gone from the cart, and nothing else in
    bank $00 moved: the fairy ($13) only in Gaia, the rod plate ($16) only in
    Earth Cave B3, as the game uses them."""
    vendored = open(os.path.join(ROOT, "game", "bank_00.dat"), "rb").read()
    cart = ROMDATA[(1 + 0x00) * 0x10000 + 0x8000:][:0x4000]
    changed = [o for o in range(0x4000) if cart[o] != vendored[o]]
    want = list(range(0x3400 + 15 * 0x30, 0x3400 + 15 * 0x30 + 3)) \
        + list(range(0x3400 + 48 * 0x30, 0x3400 + 48 * 0x30 + 3))
    check("bank $00: only the two strays' six bytes", changed, want)
    where = lambda oid: [m for m in range(61) for s in range(15)
                         if cart[0x3400 + m * 0x30 + s * 3] == oid]
    check("the fairy: Gaia only", where(0x13), [5])
    check("the rod plate: Earth Cave B3 only", where(0x16), [30])

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
    #  ...but under Ship in Drydock, ticked on the map edit screen, to Gaia's
    #  drydock: FFR's UpdateDocks moves the free ship's place with the rest.
    bus, cpu = machine()
    set_free(bus, 1 << FREE_BIT["ship_vis"])
    bus.sram[K["OPT_NG_EARLY"] - 0x6000] = K["OWEDITS_OPEN"] << K["OWEDITS_SHIFT"]
    newgame_pressing(bus, cpu, [0, 0, 0x08, 0, 0x80, 0], entry="opt_freestuff")
    check("...and under Ship in Drydock to Gaia's drydock", (bus.sram[1], bus.sram[2], bus.sram[0]),
          (211, 31, 1))
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
    def grow(cls, step, before=50, lock=0):
        bus, cpu = machine()
        setblk(bus, OPT_THIEFHIT, step | lock << 4)    # lockpicking above it
        cpu.a = before
        cpu.x = cls
        cpu.p &= ~0x01                      # carry clear, as the CLC before it
        call(cpu, "opt_hitgrowth")
        return cpu.a & 0xFF

    wrong = []
    for step in range(3):
        for cls in range(12):
            want = 50 + VANILLA_HITBONUS[cls] + (step if cls in (CLS_TH, CLS_NJ) else 0)
            for lock in (0, 4, 11, 15):
                if grow(cls, step, 50, lock) != want:
                    wrong.append((CLASS_NAMES[cls], step, lock, grow(cls, step, 50, lock), want))
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
    STRIDE, LBL, W, COUNT = K["OPTROW_STRIDE"], 2, 22, K["OPTROW_COUNT"]
    at = SYM.get("lut_OptRows")
    check("lut_OptRows is exported for this check", at is not None, True)
    if at is None:
        return
    base = (CHUNK_OPT_BANK & 0x1F) * 0x10000 + at
    #  A value row with a wide readout gives its label fewer columns: the
    #  field starts 1 << shift - 4 columns early, over the gap column first.
    shift = (CHUNK_OPT_BANK & 0x1F) * 0x10000 + SYM["lut_ValShift"]
    over = []
    for i in range(COUNT):
        row = ROMDATA[base + i * STRIDE: base + (i + 1) * STRIDE]
        if len(row) < STRIDE:
            break
        width = W
        if row[0] == 2:
            #  The readout ends VALFIELD (4) past the gap column after the
            #  label's 22, so a field of w columns covers the gap and the
            #  label's last w - 5: 11 left beside a sixteen, 19 beside an eight.
            width = min(W, W + 1 + 4 - (1 << ROMDATA[shift + row[1]]))
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
             os.path.join(ROOT, "src", "snesmap.inc"),
             os.path.join(ROOT, "src", "optmenu.inc")]
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
WORLD_BANK = 0xA1 + K["CHUNK_WORLD"]
ROLL_BANK = 0xA1 + K["CHUNK_ROLL"]
TACTICS_BANK = 0xA1 + K["CHUNK_TACTICS"]
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

    #  ...and builds the world there, before the party is rolled, so that
    #  @Begin after it finds the cache whole: one pause, not two.  The title's
    #  music silenced before any of the work.  Entrance shuffle on, so the
    #  cache has to read the attempt the placement just kept.
    seed = 0x0BADF00D
    keyitems, items3, gear2, early = PLACE_CONFIGS["beginner"]

    def newgame():
        bus, cpu = machine()
        bus.frames()
        bus.sram[pool:pool + 4] = seed.to_bytes(4, "little")
        for name, v in (("OPT_NG_KEYITEMS", keyitems), ("OPT_NG_EARLY", early),
                        ("OPT_NG_ENTRANCES", R.ENTRANCES_FLOORS), ("OPT_NG_RNG", 1)):
            bus.sram[K[name] - 0x6000] = v
        bus.sram[K["OPT_NG_ITEMS"] - 0x6000:K["OPT_NG_ITEMS"] - 0x6000 + 3] = bytes(items3)
        bus.sram[K["OPT_NG_GEAR"] - 0x6000:K["OPT_NG_GEAR"] - 0x6000 + 2] = bytes(gear2)
        bus.wram[APUSHADOW + 0x15] = 0x0F                # the title's music
        bus.wram[APUSHADOW:APUSHADOW + 16:4] = bytes([0xBF, 0xBF, 0xFF, 0x3F])
        return bus, cpu

    bus, cpu = newgame()
    check("New Game silences the music before placing",
          cpu.run(RANDO_BANK, SYM["rando_newgame"], stop=SYM["rando_place"]), True)
    check("...all four channels", (bus.wram[APUSHADOW + 0x15], bytes(bus.wram[APUSHADOW:APUSHADOW + 16:4])),
          (0, bytes([0x30] * 4)))
    bus, cpu = newgame()
    cpu.run(RANDO_BANK, SYM["rando_newgame"], limit=60_000_000)
    k = bus.sram[K["RANDO_ESK"] - 0x6000]
    entrance = R.es_shuffle(R.ShuffleRng(R.Stream(seed, R.STREAM_ENTR + k)), R.ENTRANCES_FLOORS)[0]
    check("...and leaves the cache built from the save it made",
          (bus.sram[K["RANDO_PLACED"] - 0x6000], bus.wram[rw("RW_TAG")] == K["RW_TAG_VAL"],
           rng_cache(bus) == R.build_rng(seed, 1),
           list(bus.wram[rw("RW_ENTRMAP"):rw("RW_ENTRMAP") + 32]) == [c[0] for c in entrance]),
          (1, True, True, True))
    call(cpu, "rando_stale", bank=RANDO_BANK)
    check("...so @Begin will not build it again", bool(cpu.p & 1), False)


def test_roll():
    """New Game's roll screen (roll.asm): a map sprite scaled up eight times,
    walking in place, while the world rolls; the triangle's tune; the yelp;
    the fanfare after.  Every choice's picture against one drawn here from
    the game's own data -- the sprite's CHR in bank $02, and the fixed bank's
    lut_2x2MapObj_Down (or _Left, for the bat), which says which tiles and
    flips make each frame -- and the world rolled with the screen ticking at
    every yield against one rolled with it never ticking."""
    import re
    MUSIC_DONE = 0x81                   # music_track once a fanfare is over
    roll = (ROLL_BANK & 0x1F) * 0x10000
    rd = lambda a, n: ROMDATA[roll + a:roll + a + n]
    chr0, pal0, pitch0 = SYM["lut_RollChr"], SYM["lut_RollPal"], SYM["lut_RollPitch"]
    n = (pal0 - chr0) // 128
    b0, b2 = (1 + 0x00) * 0x10000, (1 + 0x02) * 0x10000
    nescol = {int(m.group(1), 16): int(m.group(2), 16) for m in re.finditer(
        r"NESCOL_([0-9A-F]{2}) = \$([0-9A-F]{4})", open(os.path.join(ROOT, "src", "nescol.inc")).read())}

    #  The frames, from the game's own 2x2 tables: UL, DL, UR, DR, each a tile
    #  and its attributes ($40 mirrors; the low bits the palette: 2 the top,
    #  3 the legs).  The bat faces left, where its frames flap.
    fixed = ROMDATA[(0xA7 & 0x1F) * 0x10000 + 0xC000:(0xA7 & 0x1F) * 0x10000 + 0x10000]
    down = bytes([0x00, 0x02, 0x02, 0x03, 0x01, 0x02, 0x03, 0x03, 0x00, 0x02, 0x03, 0x43, 0x01, 0x02, 0x02, 0x43])
    left = bytes([0x08, 0x02, 0x0A, 0x03, 0x09, 0x02, 0x0B, 0x03, 0x0C, 0x02, 0x0E, 0x03, 0x0D, 0x02, 0x0F, 0x03])
    check("lut_2x2MapObj_Down and _Left found, once each", (fixed.count(down), fixed.count(left)), (1, 1))

    def picture(chr256, table, frame):
        tbl = table[frame * 8:frame * 8 + 8]
        out = [[0] * 16 for _ in range(16)]
        for q, (qx, qy) in enumerate(((0, 0), (0, 8), (8, 0), (8, 8))):
            tile, attr = tbl[q * 2], tbl[q * 2 + 1]
            chr16 = chr256[tile * 16:tile * 16 + 16]
            pal = (attr & 3) - 1
            for y in range(8):
                for x in range(8):
                    bx = x if attr & 0x40 else 7 - x
                    c = (chr16[y] >> bx & 1) | (chr16[y + 8] >> bx & 1) << 1
                    out[qy + y][qx + x] = c | pal << 10 if c else 0
        return out

    #  The choices: every map object graphic a map stands up but the Black
    #  Orb, the plates and Bahamut, in order, then the twelve classes'
    #  mapmen; each object's colours its first map's sprite palettes 2 and 3,
    #  each class's the overworld's 0 and 1 with its own second colours.  The
    #  effects: a hop where the two frames are the same; Garland and the
    #  Vampire on black; the Elf Prince's slow blue throb.
    gfx = ROMDATA[b0 + 0xAE00:b0 + 0xAE00 + 0xD0]
    first = {}
    for m in range(61):
        for o in range(15):
            oid = ROMDATA[b0 + 0xB400 + m * 0x30 + o * 3]
            if oid:
                first.setdefault(gfx[oid], m)
    smpal = lambda m: ROMDATA[b0 + 0xA000 + m * 0x30:b0 + 0xA000 + m * 0x30 + 0x30]
    want = []                           # (graphic or None, both frames, colours, effect)
    for g in sorted(first):
        if g in (0x04, 0x1B, 0x17):
            continue
        chr256 = bytes(ROMDATA[b2 + 0xA200 + g * 0x100:][:256])
        frames = [picture(chr256, left if g == 0x11 else down, f) for f in (0, 1)]
        p = smpal(20 if g == 0x05 else first[g])    # Matoya in her cave's colours
        fxw = 0x83 if g == 0x1A else (1 if frames[0] == frames[1] else 0) | (0x10 if g in (0x12, 0x1D) else 0)
        want.append((g, frames, [nescol[p[0x18 + i] & 0x3F] for i in (1, 2, 3)] +
                     [nescol[p[0x1C + i] & 0x3F] for i in (1, 2, 3)], fxw))
    ow = smpal(0)
    for c in range(12):
        chr256 = bytes(ROMDATA[b2 + 0x9000 + c * 0x100:][:256])
        frames = [picture(chr256, down, f) for f in (0, 1)]
        top, bot = list(ow[0x10:0x14]), list(ow[0x14:0x18])
        top[2], bot[2] = ROMDATA[b0 + 0x83A0 + c * 2], ROMDATA[b0 + 0x83A0 + c * 2 + 1]
        want.append((None, frames, [nescol[top[i] & 0x3F] for i in (1, 2, 3)] +
                     [nescol[bot[i] & 0x3F] for i in (1, 2, 3)], 1 if frames[0] == frames[1] else 0))
    fx = list(rd(SYM["lut_RollFx"], n))
    graphics = [g for g, _, _, _ in want if g is not None]
    check("the choices: 26 creatures, Garland and the bats among them, and 12 classes",
          (n, 0x12 in graphics, 0x11 in graphics, 0x04 in graphics), (38, True, True, False))
    check("...their effects: a hop for the still, Garland and the Vampire on black, the Elf Prince's throb",
          fx, [w[3] for w in want])
    check("...the bat flaps: its frames differ", fx[graphics.index(0x11)], 0)

    def begin(seed):
        bus, cpu = machine()
        bus.frames()
        bus.ppu()
        bus.sram[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = seed.to_bytes(4, "little")
        cpu.run(ROLL_BANK, SYM["roll_begin"])
        return bus, cpu

    #  The pick: the seed's halves XORed, v, scaled -- (v * n) >> 16 -- so
    #  every choice is 1724 or 1725 of the 65536.  The cart's at every
    #  boundary, v from either half of the seed.
    pick_of = lambda seed: (((seed & 0xFFFF) ^ (seed >> 16)) * n) >> 16
    seed_for = lambda k: (k * 65536 + n - 1) // n
    sizes = [sum(1 for v in range(65536) if (v * n) >> 16 == k) for k in range(n)]
    check("the picks even: each 1724 or 1725 of the 65536", sorted(set(sizes)), [1724, 1725])
    bad = []
    for k in range(1, n):
        b = seed_for(k)
        for seed, expect in ((b - 1, k - 1), (b, k), ((b - 1) << 16, k - 1), (b << 16 | 0x5A5A, pick_of(b << 16 | 0x5A5A)),
                             ((b ^ 0x1234) | 0x1234 << 16, k)):
            bus, cpu = machine()
            bus.sram[K["RANDO_SAVE"] - 0x6000:K["RANDO_SAVE"] - 0x6000 + 4] = seed.to_bytes(4, "little")
            cpu.e = False
            cpu.dbr = ROLL_BANK
            cpu.run(ROLL_BANK, SYM["roll_pick"])
            if bus.wram[rw("ROLL_PICK")] != expect or expect != pick_of(seed):
                bad.append((hex(seed), bus.wram[rw("ROLL_PICK")], expect))
    check("...the cart's pick, at every boundary", bad[:4], [])

    bad = []
    for seed in [seed_for(k) for k in range(n)] + [0x01020304, 0xDEADBEEF, 0xFFFFFFFF]:
        bus, cpu = begin(seed)
        pick = pick_of(seed)
        if bus.wram[rw("ROLL_PICK")] != pick:
            bad.append(("pick", seed))
            continue
        vw = lambda w: bus.vram[w * 2] | bus.vram[w * 2 + 1] << 8
        for frame in (0, 1):
            pic = want[pick][1][frame]
            for r in range(32):
                for c in range(32):
                    cell = pic[r - 6][c - 8] if 6 <= r < 22 and 8 <= c < 24 else 0
                    if vw(0x1000 + frame * 0x400 + r * 32 + c) != cell:
                        bad.append(("cell", seed, frame, r, c))
        tiles = [vw(w) for w in range(64)]
        if tiles != [0] * 16 + [0x00FF] * 8 + [0] * 8 + [0xFF00] * 8 + [0] * 8 + [0xFFFF] * 8 + [0] * 8:
            bad.append(("tiles", seed))
        cg = lambda e: bus.cgram[e * 2] | bus.cgram[e * 2 + 1] << 8
        throb = fx[pick] & 2
        black = fx[pick] & 0x12
        if [cg(0)] + [cg(e) for e in (17, 18, 19, 33, 34, 35)] != [0 if black else nescol[0x01]] + want[pick][2]:
            bad.append(("colours", seed))
        if (bus.io.get(K["INIDISP"]), bus.io.get(K["TM"]), bus.io.get(K["BGMODE"]), bus.wram[rw("ROLL_ON")],
                bus.io.get(K["CGADSUB"])) != (0x00, 0x01, 0x01, 1, 0x20 if throb else 0):
            bad.append(("registers", seed))
    check("every picture: its sprite, both frames, as the game draws it, and its colours", bad[:4], [])

    #  The effects, tick by tick: a hop is BG1VOFS half a cell up and back on
    #  the step's beat, the frames left alone; a throb is the fixed colour, a
    #  triangle wave on its channels -- the Elf Prince's half as fast and half
    #  as bright.
    def ticks(pick, count):
        bus, cpu = begin(seed_for(pick))
        log = []
        write = bus.write

        def w(bank, addr, val):
            if addr in (K["BG1HOFS"], K["BG1VOFS"], K["COLDATA"]) and (bank & 0xFF) not in (0x7E, 0x7F):
                log.append((bus.wram[rw("ROLL_T")], addr, val & 0xFF))
            write(bank, addr, val)
        bus.write = w
        cpu.e = False
        for _ in range(count):
            cpu.run(ROLL_BANK, SYM["roll_tick"])
        return log

    wave = lambda t: (t & 63) if (t & 63) < 32 else 63 - (t & 63)
    log = ticks(fx.index(0), 16)
    check("a step: the other frame, 256 across, and back, every eight ticks", log,
          [(8, K["BG1HOFS"], 0x00), (8, K["BG1HOFS"], 0x01), (16, K["BG1HOFS"], 0x00), (16, K["BG1HOFS"], 0x00)])
    log = ticks(fx.index(1), 24)
    check("a hop: half a cell up and back every eight ticks, the frames untouched", log,
          [(8, K["BG1VOFS"], 0x03), (8, K["BG1VOFS"], 0x00), (16, K["BG1VOFS"], 0xFF), (16, K["BG1VOFS"], 0x03),
           (24, K["BG1VOFS"], 0x03), (24, K["BG1VOFS"], 0x00)])
    check("the Vampire hops too, on black, with no throb", ticks(fx.index(0x11), 24), log)
    log = ticks(fx.index(0x83), 70)
    check("the Elf Prince's: black to a dim blue, slowly",
          log, [x for t in range(1, 71) for x in ((t, K["COLDATA"], 0xE0), (t, K["COLDATA"], 0x80 | wave(t >> 1) >> 1))])

    #  A tick: a step every eight, a brighter frame until full, and a note every
    #  six: its stage's scale, the walk's step from the PRNG's low bits,
    #  reflected inside the scale.
    pitch = [rd(pitch0 + i * 2, 2)[0] | rd(pitch0 + i * 2, 2)[1] << 8 for i in range(32)]
    walk = (-2, -1, 1, 2)
    bad = []
    for stage in range(4):
        for idx in range(8):
            for bits in range(4):
                bus, cpu = machine()
                bus.wram[rw("ROLL_STAGE")] = stage
                bus.wram[rw("ROLL_IDX")] = idx
                bus.wram[rw("RW_RNG")] = 0xA4 | bits
                cpu.e = False
                cpu.run(ROLL_BANK, SYM["roll_tick"])
                j = idx + walk[bits]
                j = -j - 1 if j < 0 else 15 - j if j > 7 else j
                period = bus.wram[0x900 + 0x0A] | bus.wram[0x900 + 0x0B] << 8
                if (bus.wram[rw("ROLL_IDX")], period, bus.wram[0x900 + 0x15] & 0x04, bus.wram[0x900 + 8]) != \
                        (j, pitch[stage * 8 + j], 0x04, 0xFF):
                    bad.append((stage, idx, bits))
    check("a note: its stage's scale, a step of the walk, reflected", bad[:4], [])
    check("...the scales in order: placing, the doors, the logic, the world",
          [pitch[k * 8:k * 8 + 8] for k in range(4)],
          [[0x0BD, 0x0A9, 0x096, 0x086, 0x077, 0x06A, 0x05E, 0x054],
           [0x06A, 0x05E, 0x054, 0x046, 0x03F, 0x034, 0x02F, 0x029],
           [0x0FD, 0x0D5, 0x0BD, 0x0A9, 0x08E, 0x07E, 0x06A, 0x05E],
           [0x08E, 0x070, 0x05E, 0x046, 0x038, 0x02F, 0x023, 0x01B]])
    #  The pulse's answer, against a model.  Asked for, it waits for the
    #  triangle's next note -- every six ticks, from the first -- and starts
    #  with it; asked for while one waits or plays, the asking is dropped.
    #  Its phrase in turn: a pair, a pair, a run, round again.  A pair is two
    #  notes of two beats: the sprite's step, then 1 + the PRNG state's third
    #  byte modulo the room within a fifth, up as its second byte's low bit
    #  says unless there is no room that way.  A run is four notes, a beat
    #  each and the last held three, each a step or two (a bit of the third
    #  byte apiece) the same way, as room allows, turning where there is
    #  none.  The notes at the triangle's periods; each fades from 8, one
    #  with another after it ending early.
    roll_rd = lambda a, n: ROMDATA[roll + a:roll + a + n]
    reach = list(roll_rd(SYM["lut_RollReach"], 32))
    voice = list(roll_rd(SYM["lut_RollVoice"], n))
    ON, LAST = [8, 8, 7, 7, 6, 6, 5, 5, 4, 4, 0, 0], [8, 8, 7, 7, 6, 6, 5, 5, 4, 3, 2, 1]
    SHORT, HOLD = [8, 7, 6, 5, 4, 0], [8, 8, 8, 7, 7, 7, 6, 6, 6, 5, 5, 5, 4, 4, 3, 3, 2, 1]
    ENVS = ([ON, LAST], [SHORT, SHORT, SHORT, HOLD])

    def room(x, up):
        u, d = reach[x] >> 4, reach[x] & 15
        if up:
            return (u, True) if u else (d, False)
        return (d, False) if d else (u, True)

    def phrase(stage, pick, r1, r2, run):
        x = stage * 8 + voice[pick]
        notes, up = [x], bool(r1 & 1)
        if not run:
            rm, up = room(x, up)
            return notes + [x + (1 + r2 % rm) * (1 if up else -1)]
        bits = r2
        for _ in range(3):
            rm, up = room(x, up)
            x += min(1 + (bits & 1), rm) * (1 if up else -1)
            bits >>= 1
            notes.append(x)
        return notes

    def model(stage, pick, r1, r2, asks, count):
        armed, left, num, out = False, 0, 0, []
        for t in range(count):
            if t in asks and not armed and not left:
                armed = True
            if armed and t % 6 == 0:
                run = num == 2
                num = (num + 1) % 3
                armed, env, notes, k, tt = False, ENVS[run], phrase(stage, pick, r1, r2, run), 0, 0
                left = len(notes)
            if left:
                out.append((0xB0 | env[k][tt], pitch[notes[k]], 1))
                tt += 1
                if tt == len(env[k]):
                    k, tt, left = k + 1, 0, left - 1
            else:
                out.append(None)
        return out

    by_voice = {v: voice.index(v) for v in range(8)}
    for stage, pick, r1, r2, asks in ((0, by_voice[0], 0x01, 2, set(range(130))),
                                      (3, by_voice[7], 0x00, 5, {2, 9, 31, 33, 50, 75, 100})):
        bus, cpu = machine()
        bus.wram[rw("ROLL_STAGE")] = stage
        bus.wram[rw("ROLL_PICK")] = pick
        bus.wram[rw("RW_RNG") + 1], bus.wram[rw("RW_RNG") + 2] = r1, r2
        cpu.e = False
        seen, notes = [], []
        for t in range(130):
            if t in asks:
                bus.wram[rw("ROLL_YREQ")] = 1
            cpu.run(ROLL_BANK, SYM["roll_tick"])
            sh = bus.wram[0x900:0x916]
            seen.append((sh[0], sh[2] | sh[3] << 8, 1) if sh[0x15] & 1 else None)
            notes.append(bus.wram[rw("ROLL_GATE")])
        check("stage %d: pair, pair, run, each with the tune's next note; none asked for while one plays"
              % stage, seen, model(stage, pick, r1, r2, asks, 130))

    #  Every phrase's notes, every stage, voice and choice: in the scale, and
    #  no leap more than a fifth -- a frequency ratio within 1.5, give or take
    #  the periods' rounding (frequency goes as 1 / (period + 1); A5 to E6 is
    #  1.524) where a minor sixth would be 1.587.
    bad = []
    for stage in range(4):
        for v in range(8):
            for r1 in (0, 1):
                for r2 in range(8):
                    for num, run in ((0, False), (2, True)):
                        bus, cpu = machine()
                        bus.wram[rw("ROLL_STAGE")] = stage
                        bus.wram[rw("ROLL_PICK")] = by_voice[v]
                        bus.wram[rw("RW_RNG") + 1], bus.wram[rw("RW_RNG") + 2] = r1, r2
                        bus.wram[rw("ROLL_YNUM")] = num
                        bus.wram[rw("ROLL_YREQ")] = 1
                        cpu.e = False
                        cpu.run(ROLL_BANK, SYM["roll_tick"])
                        got = list(bus.wram[rw("ROLL_YNOTES"):rw("ROLL_YNOTES") + (4 if run else 2)])
                        ps = [pitch[x] for x in got]
                        if got != phrase(stage, by_voice[v], r1, r2, run) or \
                                any(not stage * 8 <= x < stage * 8 + 8 for x in got) or \
                                any(a == b or (max(a, b) + 1) / (min(a, b) + 1) > 1.53 for a, b in zip(ps, ps[1:])):
                            bad.append((stage, v, r1, r2, run, got))
    check("...every phrase's notes in its scale, no leap past a fifth", bad[:4], [])
    check("...a note every six ticks (it was seven), sounding four",
          [t for t, g in enumerate(notes) if g == 4], list(range(0, 130, 6)))
    bus, cpu = machine()
    cpu.e = False
    seen = []
    for t in range(12):
        cpu.run(ROLL_BANK, SYM["roll_tick"])
        seen.append((bus.wram[rw("ROLL_FRAME")], bus.wram[rw("ROLL_BRIGHT")]))
    check("...the step every eight ticks, the fade in over fifteen",
          ([x[0] for x in seen], [x[1] for x in seen]),
          ([0] * 7 + [1] * 5, list(range(1, 13))))
    check("...and every tick a frame of sound sent (hal_audioframe)",
          bus.wram[K["h_frame"]] | bus.wram[K["h_frame"] + 1] << 8, 12)

    #  The world rolled is the same ticked at every yield as never ticked; and
    #  the tune heard, a yelp among it, and the fanfare after, then the title's
    #  music for party creation, the screen dark and back with the HAL.
    def newgame(every):
        bus, cpu = machine()
        bus.frames(every=every)
        cfg = PLACE_CONFIGS["late"]
        pool = K["RANDO_POOL"] - 0x6000
        bus.sram[pool:pool + 4] = (158397).to_bytes(4, "little")
        for name, v in (("OPT_NG_KEYITEMS", cfg[0]), ("OPT_NG_EARLY", cfg[3]),
                        ("OPT_NG_ENTRANCES", R.ENTRANCES_ONLY), ("OPT_NG_RNG", 1), ("OPT_NG_CHESTS", 1)):
            bus.sram[K[name] - 0x6000] = v
        bus.sram[K["OPT_NG_ITEMS"] - 0x6000:K["OPT_NG_ITEMS"] - 0x6000 + 3] = bytes(cfg[1])
        bus.sram[K["OPT_NG_GEAR"] - 0x6000:K["OPT_NG_GEAR"] - 0x6000 + 2] = bytes(cfg[2])
        log = []
        write = bus.write

        def w(bank, addr, val):
            if addr in (0x900 + 0x0B, 0x900, K["music_track"], K["INIDISP"]) and (bank & 0xFF) not in (0x7E, 0x7F):
                log.append((addr, val & 0xFF, bus.wram[0x900 + 0x0A]))
            write(bank, addr, val)
        bus.write = w
        cpu.run(RANDO_BANK, SYM["rando_newgame"], limit=100_000_000)
        save = bytes(bus.sram[K["RANDO_SAVE"] - 0x6000:][:K["RANDO_SAVE_SIZE"]])
        place = bytes(bus.sram[K["RANDO_PLACE"] - 0x6000:][:K["PLACE_ITEMS"]])
        cache = bytes(bus.wram[rw("RANDOWRAM"):rw("ROLL_ON")])
        return (save, place, cache), log, bus

    def roll_only(log):                 # up to the fanfare, whose driver plays too
        k = next(i for i, (a, val, _) in enumerate(log) if a == K["music_track"] and val == 0x54)
        return log[:k]

    ticked, log, bus = newgame(1)
    still, quiet, _ = newgame(10 ** 9)
    check("the world the same ticked at every yield as never ticked", ticked == still, True)
    periods = {lo | val << 8 for a, val, lo in roll_only(log) if a == 0x90B}
    unique = [{0x096, 0x086, 0x077}, {0x03F, 0x034, 0x029}, {0x0FD, 0x0D5, 0x07E}, {0x070, 0x038, 0x023, 0x01B}]
    check("the tune: every note from a scale, every stage's scale heard",
          (periods <= set(pitch), [bool(u & periods) for u in unique]), (True, [True] * 4))
    check("...an answer among it (this seed throws six wirings away)",
          any(a == 0x900 and val & 0xF0 == 0xB0 for a, val, _ in roll_only(log)), True)
    mus = [val for a, val, _ in log if a == K["music_track"]]
    check("...the key item fanfare, played out, then the title's music again",
          (mus[0], MUSIC_DONE in mus, mus[-1], bus.wram[K["music_track"]], bus.wram[rw("ROLL_ON")]),
          (0x54, True, 0x41, 0x41, 0))
    check("...the screen dark, the PPU the HAL's again",
          ([val for a, val, _ in log if a == K["INIDISP"]][-1], bus.wram[K["h_paldirty"]]), (0x80, 1))
    check("never ticked: no note", [a for a, _, _ in roll_only(quiet) if a == 0x90B], [])

    #  Off the roll screen a yield is nine instructions and never ticks: the
    #  cache build at @Begin, a Continue's, leaves the screen alone.
    bus, cpu = machine()
    bus.frames(every=1)
    cpu.e = False
    s0 = cpu.steps
    cpu.run(RANDO_BANK, SYM["rando_yield"])
    check("a yield with the screen down: nine instructions", cpu.steps - s0 <= 10, True)
    setsave(bus, 0x600DCAFE, 4, 1, 1, 1, 2, 2)
    call(cpu, "rando_ensure", bank=RANDO_BANK)
    check("...and a cache build then never ticks", bus.wram[rw("ROLL_T")], 0)


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
            ("SHIP", "OPT_NG_ITEMS", 0, 2, 4),           # the SHIP and AIRSHIP rows to Remove
            ("AIRSHIP", "OPT_NG_ITEMS", 2, 2, 4),
            ("BRIDGE", "OPT_NG_ITEMS", 4, 2, 3),
            ("CHIME", "OPT_NG_ITEMS", 4, 2, 3),          # ITEMROW_CHIME 6: byte 1, bits 4-5
            ("ROD", "OPT_NG_ITEMS", 4, 2, 3),            # ITEMROW_ROD 10: byte 2, bits 4-5
            ("Other items", "OPT_NG_ITEMS", 6, 2, 2),    # byte 2, bits 6-7, two values
            ("Masmune", "OPT_NG_GEAR", 0, 1, 2),
            ("Ribbon", "OPT_NG_GEAR", 7, 1, 2),
            ("Xcalber", "OPT_NG_GEAR", 0, 1, 2),         # the second gear byte
            ("Early Ordeals", "OPT_NG_EARLY", 3, 1, 2),
            ("Map shuffle", "OPT_NG_ENTRANCES", 0, 8, 3),
            ("Starting items", "OPT_STARTITEMS", 0, 4, 9),
            ("Thief and Ninja hit%", "OPT_THIEFHIT", 0, 2, 3),
            ("Thief lockpicking", "OPT_THIEFHIT", 4, 4, 12),
            ("Magic levels", "OPT_NG_MAGIC", 0, 2, 2),
            ("Item magic", "OPT_NG_MAGIC", 4, 2, 3),
            ("Starting caster item", "OPT_STARTITEMS", 7, 1, 2)):
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
        spec[23 + k] = ("OPT_NG_ITEMS", k // 4, 2 * (k % 4), 4 if k < 2 else 3 if k < 11 else 2)
    for g in range(9):
        spec[35 + g] = ("OPT_NG_GEAR", g // 8, g % 8, 2)
    for e in range(4):
        spec[44 + e] = ("OPT_NG_EARLY", 0, e, 2)
    spec[48] = ("OPT_NG_ENTRANCES", 0, 0, 3)
    spec[8] = ("OPT_NG_MAGIC", 0, 0, 2)          # Magic levels, under...
    spec[52] = ("OPT_NG_MAGIC", 0, 4, 3)         # ...Item magic, one byte
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
    check("each key item row, and Map shuffle, reads its own field alone", bad[:4], [])

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
        raw = ROMDATA[base + r * K["OPTROW_STRIDE"] + 2:][:22]
        if "".join(_decode(b) or "?" for b in raw).strip() == label:
            return r
    raise KeyError(label)


def test_shoulders():
    """L and R page the settings list, up and down half a screen, as SNES
    menus do -- on any row, a value row too, where left and right step the
    value.  A press pages once; held, it does not repeat.  R joins h_joyaux
    in its own JOY1L bit, and the reset combos (L|X|Y) do not see it."""
    SEL, TOP = 0x6E, 0x6F
    AUX, SHPREV = K["h_joyaux"], K["OPTBLOCK"] + 0x1A - 0x6000
    L, R = K["JOYAUX_L"], K["JOYAUX_R"]
    check("R is JOY1L's own bit, apart from the reset combos'", (R, R & K["PADRESET_MASK"]), (0x10, 0))
    gold = optrow("Gold and XP")

    def press(sel, aux, prev=0, entry="opt_shoulders", a=None):
        bus, cpu = machine()
        in_vblank(bus)
        call(cpu, "opt_init")
        bus.wram[SEL], bus.wram[TOP] = sel, max(0, sel - 10)
        bus.wram[AUX] = aux
        bus.sram[SHPREV] = prev
        if a is not None:
            cpu.a = a
        call(cpu, entry, dbr=CHUNK_OPT_BANK)
        return bus.wram[SEL], bool(cpu.p & C), blk(bus, OPT_GOLDXP), bus.sram[SHPREV]
    sel0, _, gold0, _ = press(gold, 0)
    down = press(gold, R)
    check("R on a value row: pages down, the value untouched, R remembered",
          (down[0] > gold + 4, down[1], down[2], down[3]), (True, True, gold0, R))
    up = press(down[0], L)
    check("...L pages back up", (up[0] < down[0] - 4, up[1]), (True, True))
    check("R held from last frame: no second page", press(gold, R, prev=R)[:2], (gold, False))
    check("nothing pressed: nothing", press(gold, 0)[:2], (gold, False))
    check("the d-pad on the value row still steps the value, not the page",
          press(gold, 0, entry="opt_sideways", a=K["RIGHT"])[0::2], (gold, gold0 + 1))
    #  The pad as the HAL reads it: L, X and R from JOY1L, Y from JOY1H.
    got = []
    for lo, hi in ((0x10, 0), (0x20, 0), (0x30, 0x40), (0x8F, 0xBF)):
        bus, cpu = machine()
        bus.io[K["JOY1L"]], bus.io[K["JOY1H"]] = lo, hi
        call(cpu, "aux_capture", bank=0xC0)
        got.append(bus.wram[AUX])
    check("aux_capture: R, L, L+R+Y, and nothing from A, B or the d-pad", got, [0x10, 0x20, 0x31, 0x00])
    #  The reset combos are L with X or Y; R with them is neither.
    bad = []
    for aux, want in ((L | K["JOYAUX_X"], K["PADRESET_SOFT"]), (R | K["JOYAUX_X"], 0), (R, 0), (L | R, 0)):
        bus, cpu = machine()
        bus.wram[AUX] = aux
        bus.wram[K["h_joyauxprev"]] = 0
        bus.wram[K["h_padreset"]] = 0
        call(cpu, "aux_edge", bank=0xC0)
        if bus.wram[K["h_padreset"]] != want:
            bad.append((hex(aux), bus.wram[K["h_padreset"]]))
    check("R is no part of a reset", bad, [])


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
    cases += [(optrow("Map shuffle"), K["OPT_NG_ENTRANCES"], v, phrase) for v, phrase in enumerate((
                 "leads where it always does", "Towns stay put", "As Entrances, and the stairs"))]
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

    #  The Masmune, blursed, is Masa: Masa+2, Masa-3 (user, 2026-10-17) --
    #  written out here, not taken from randoref, which has the same rule.
    MAS = 0x43 - 0x1C
    seen = {}
    for seed in range(1, 600):
        b = R.build_gear(ROMDATA, seed, 5, 5)[1][MAS]
        if b in (2, -3, 0) and b not in seen:
            seen[b] = seed
        if len(seen) == 3:
            break
    got = {}
    for b, seed in seen.items():
        bus, cpu = machine()
        setgear(bus, seed, 5, 5)
        warm(bus)
        cpu.a, cpu.y = 0x43, 0x5A
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        p = (cpu.a & 0xFF) | cpu.x << 8
        got[b] = bytes(bus.read(0xA1 + 0x0A, p + k) for k in range(8))
    text = lambda t: bytes({"+": 0xC1, "-": 0xC2, " ": 0xFF}.get(c, 0x80 + int(c)) if not c.isalpha()
                           else (0x8A + ord(c) - 65 if c.isupper() else 0xA4 + ord(c) - 97) for c in t)
    check("the Masmune: Masa+2, Masa-3, and Masmune unblursed",
          (got[2], got[-3], got[0][:7]), (text("Masa+2 ") + b"\0", text("Masa-3 ") + b"\0", text("Masmune")))

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
    cb = SYM["rando_coldbuild"]
    op = bytes([0x22, a & 0xFF, a >> 8, RANDO_BANK])
    img = ROMDATA[fixed + 0xC000:fixed + 0x10000]
    at = [i for i in range(len(img) - 3) if img[i:i + 4] == op]
    check("the fixed bank asks rando_stale once", len(at), 1)
    if len(at) != 1:
        return
    pc = 0xC000 + at[0]
    scroll = K["unsram_ow_scroll_x"]
    check("...at @Begin: if stale, the cold build, then fetch the overworld scroll",
          bytes(img[at[0] + 4:at[0] + 13]),
          bytes([0x90, 0x04, 0x22, cb & 0xFF, cb >> 8, RANDO_BANK,
                 0xAD, scroll & 0xFF, scroll >> 8]))
    end = pc + 10

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
    bus.frames()                        # the roll screen waits on vblanks
    cpu.pbr, cpu.pc = 0xA7, pc
    n = 0
    while (cpu.pbr, cpu.pc) != (RANDO_BANK, e) and n < 2_000_000:
        cpu.step()
        n += 1
    check("@Begin, stale: reaches rando_ensure", (cpu.pbr, cpu.pc), (RANDO_BANK, e))
    check("...the music silenced before it starts, the roll screen up",
          (apu(bus), bus.wram[rw("RW_TAG")], bus.wram[rw("ROLL_ON")]), ((0, (0x30, 0x30, 0x30, 0x30)), 0, 1))
    n = 0
    while (cpu.pbr, cpu.pc) != (0xA7, end) and n < 8_000_000:
        cpu.step()
        n += 1
    check("...and runs on to the next instruction", (cpu.pbr, cpu.pc), (0xA7, end))
    check("...the roll screen down, its fanfare over, no track started after",
          (bus.wram[rw("ROLL_ON")], bus.wram[K["music_track"]]), (0, 0x81))
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
    ST = K["OPTROW_STRIDE"]
    rows = [ROMDATA[optimg + SYM["lut_OptRows"] + i * ST:][:ST] for i in range(COUNT)]
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

    def pad(bus, nes, lo=0):
        """The NES buttons as JOY1L/H carry them; lo, JOY1L's own bits -- the
        shoulders, L $20 and R $10, which the NES pad never had."""
        bus.io[0x4218] = (nes & 0x80) | lo
        bus.io[0x4219] = (nes & 0x3F) | (0x80 if nes & 0x40 else 0)

    def frame(bus, cpu, nes, lo=0):
        """Hold the pad as given for the UpdateJoy the screen is stopped at,
        and run to the next.  False once the screen has returned."""
        pad(bus, nes, lo)
        cpu.step()
        for _ in range(3_000_000):
            if cpu.pc in (UJ, 0xFFFE):
                return cpu.pc == UJ
            cpu.step()
        raise RuntimeError("a frame ran away at $%02X:%04X" % (cpu.pbr, cpu.pc))

    def press(bus, cpu, nes, lo=0):
        return frame(bus, cpu, nes, lo) and frame(bus, cpu, 0)

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
    OLD = [3, 1, 1, 1, 2, 4, 2, 2, 1, 1, 1, 1, 3, 2, 1, 1]  # Trap tiles .. Ordeals pillars;
    #  the fifth Item magic's Balanced, beside Magic levels' Shuffle in one byte
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
    #  A and Select do nothing here.  (A is masked, though on a value row the
    #  settings ignore it anyway.)  Left and right page: below.
    for name, b in (("A", A_), ("Select", SELECT)):
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

    #  The shoulders page the view as they page the settings (user,
    #  2026-10-16): R down half a screen, L up, landing only where the cursor
    #  may rest, the window reading as saved, nothing written; held, once.
    SH_L, SH_R = K["JOYAUX_L"], K["JOYAUX_R"]
    pages = []
    for _ in range(12):
        press(bus, cpu, 0, SH_R)
        pages.append(bus.wram[SEL])
        got, want = shown()
        if got != want:
            check("R to row %d, each row in the window as saved" % bus.wram[SEL], got, want)
            break
    steps = [b - a for a, b in zip([first] + pages, pages) if b != a]
    check("R pages down to the last row and stays, on value rows only",
          (pages[-1], pages[-2], set(pages) <= set(vrows), min(steps) > 4, kept()),
          (COUNT - 1, COUNT - 1, True, True, before))
    back = []
    for _ in range(12):
        press(bus, cpu, 0, SH_L)
        back.append(bus.wram[SEL])
    check("L pages back up to Trap tiles and stays, the window at the section's top",
          (back[-1], back[-2], set(back) <= set(vrows), bus.wram[TOP], kept()), (first, first, True, top, before))

    #  ...and the hand moves with the page, not after it: every vblank of the
    #  repaint shows it where the loop leaves it, never a frame or more at its
    #  old screen row -- which, with the window snapping back to the view's
    #  top, was the Seed or the heading (user, 2026-10-16).
    OAMDMA, WAIT, OAM = SYM["hal_oamdma"], SYM["hal_waitvbl"], K["oam"]

    def watch(lo, nes=0):
        seen, last = [], [bus.wram[OAM]]
        step = cpu.step

        def spy():
            if cpu.pbr == 0xC0 and cpu.pc == OAMDMA:
                last[0] = bus.wram[OAM]
            elif cpu.pbr == 0xC0 and cpu.pc == WAIT:
                seen.append(last[0])
            step()
        cpu.step = spy
        press(bus, cpu, nes, lo)
        frame(bus, cpu, 0)
        cpu.step = step
        return seen
    hands = []
    while bus.wram[SEL] != COUNT - 1:                # down in pages, then back up
        hands.append(watch(SH_R))
    while bus.wram[SEL] != first:
        hands.append(watch(SH_L))
    check("the hand never shows off its row while a page repaints",
          [sorted(set(h[1:])) for h in hands], [[h[-1]] for h in hands])
    #  (h[0] is the vblank whose frame wait files the press into h_joyaux:
    #  the shoulder has not been heard yet, and the hand is rightly where it was.)

    #  The d-pad's left and right page the view as well (user, 2026-10-16):
    #  every row is read-only, so there is no value for them to step.
    pages, hands = [], []
    while bus.wram[SEL] != COUNT - 1 and len(pages) < 12:
        hands.append(watch(0, RIGHT))
        pages.append(bus.wram[SEL])
    while bus.wram[SEL] != first and len(pages) < 24:
        hands.append(watch(0, LEFT))
        pages.append(bus.wram[SEL])
    check("right pages down to the last row, left back to Trap tiles, on value rows only",
          (COUNT - 1 in pages, pages[-1], set(pages) <= set(vrows), bus.wram[TOP], kept()),
          (True, first, True, top, before))
    check("...the hand with each page", [sorted(set(h)) for h in hands], [[h[-1]] for h in hands])
    #  (The HAL files the shoulders in the frame wait, so they are heard a
    #  frame after the d-pad would be.)
    for _ in range(6):
        frame(bus, cpu, 0, SH_R)
    frame(bus, cpu, 0)
    check("R held for six frames pages once", bus.wram[SEL], pages[0])
    for _ in range(4):
        press(bus, cpu, 0, SH_L)
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
        if 0x1C <= item < 0x6C or 0x12 <= item <= 0x14:
            continue
        s0 = cpu.steps
        cpu.a = item
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        got.append((item, (cpu.a & 0xFF) | (cpu.x & 0xFF) << 8, bus.wram[tag], cpu.steps - s0 < 200))
        want.append((item, ROMDATA[b0a + 0xB700 + 2 * item] | ROMDATA[b0a + 0xB701 + 2 * item] << 8, 0, True))
    check("every name but gear's: the ROM's pointer, the cache not built, cheaply", got, want)
    #  $12-$14 are the orbs' ids, whose names are empty and never drawn; a
    #  vehicle given is named by them (give_vehicle), so they come back as the
    #  vehicle's name, built in the buffer -- cheaply, and the cache unbuilt.
    for item, name in ((0x12, "SHIP"), (0x13, "BRIDGE"), (0x14, "CANAL")):
        bus, cpu = machine()
        s0 = cpu.steps
        cpu.a = item
        call(cpu, "rando_nameptr", bank=RANDO_BANK)
        at = K["OPTNAMEBUF"] - 0x6000
        check("$%02X: the vehicle's name" % item,
              ((cpu.a & 0xFF) | (cpu.x & 0xFF) << 8, bytes(bus.sram[at:at + 8]).split(b"\0")[0] != b"",
               bus.wram[tag], cpu.steps - s0 < 200),
              (K["OPTNAMEBUF"], True, 0, True))
        check("$%02X reads %s" % (item, name), "".join(
            _decode(b) or "" for b in bytes(bus.sram[at:at + 8]).split(b"\0")[0]), name)
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
              test_noshuffle, test_derive, test_guillotine, test_rando_talk, test_rando_remove, test_rando_early, test_es_reference, test_es_wiring, test_es_masks, test_es_world, test_es_place, test_es_tables, test_es_tree, test_owedits, test_owscreen, test_rando_place, test_rando_rewards, test_rando_giving, test_rando_shipdock, test_rando_princess, test_roll, test_rando_dialogue,
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
              test_elembonus, test_thiefninja, test_thiefhit, test_softbattle, test_wmharm, test_kraken, test_bosstactics, test_staffspells, test_casteritem, test_lockpick, test_itemmagic, test_palflush, test_ntflush, test_minimap, test_chrflush, test_shoulders, test_strayobjects, test_runfix, test_turnfix, test_trance, test_critcount, test_mapedits, test_rando_ordeals,
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
