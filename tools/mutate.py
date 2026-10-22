#!/usr/bin/env python3
"""
mutate.py -- does each test notice the bug it exists to catch?

A mutation is a deliberate bug: a replacement in one source file, and the test
that should fail because of it.  Each is applied, built and tested in a private
copy of this tree, as many at once as there are cores.  The tree itself is
only ever read -- rsync'd into the copies at the start -- so an interrupted run
cannot leave a mutated source behind, and a playtest ROM built here survives.

Every test named also runs once against the unmutated build first.  A test
that already fails would "catch" every mutation aimed at it, so its mutations
are reported INVALID rather than CAUGHT.

    python3 tools/mutate.py LIST.py [-j N] [name ...]

LIST.py is a Python file defining M, a list of (name, file, old, new, test):

    M = [
     ("element from weakness", "src/optbank.asm",
      "    LDY #ENROMSTAT_TOUCHELEM\\n", "    LDY #ENROMSTAT_ELEMWEAK\\n",
      "test_enemyelement"),
    ]

file is relative to this tree; old must occur in it exactly once; old and new
may be lists, applied together.  Naming mutations runs just those.  The lists
are written per change and thrown away, so they do not live here.

A MISSED mutation is not yet a weak test: first check the mutant behaves
differently at all (options-design.md, "A mutation can be a no-op").

The copies are kept in $TMPDIR/sff-mutate between runs, so the next run's
rsync moves only what changed; MUTATE_WORK names somewhere else.  Builds there
strip FFSEED and FFDEBUG from the environment, whatever this shell exports.
"""
import fcntl, os, queue, runpy, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = os.environ.get("MUTATE_WORK") or os.path.join(tempfile.gettempdir(), "sff-mutate")


def sync(d):
    os.makedirs(d, exist_ok=True)
    subprocess.run(["rsync", "-a", "--delete", "--exclude=.git",
                    "--exclude=*.sfc", "--exclude=*.ram", "--exclude=*.ram.*",
                    "--exclude=__pycache__", ROOT + "/", d + "/"], check=True)


def build(d):
    env = {k: v for k, v in os.environ.items() if k not in ("FFSEED", "FFDEBUG")}
    return subprocess.run(["./build.sh"], cwd=d, capture_output=True, text=True, env=env)


#  A mutation that loops the game forever hangs its test; that is a catch, but
#  it has to end.  The slowest test passes in a few minutes.
TEST_TIMEOUT = 900


def attempt(d, f, old, new, test):
    """Build the copy d with one mutation applied (none if old is None) and
    run test there.  The verdict and the line that explains it.  The file is
    put back byte for byte whatever happens, so the copy is clean for the next
    mutation this worker takes."""
    path = os.path.join(d, f)
    pristine = open(path, "rb").read()
    try:
        if old is not None:
            s = pristine.decode("utf-8")
            olds, news = (old, new) if isinstance(old, list) else ([old], [new])
            bad = [o for o in olds if s.count(o) != 1]
            if bad:
                return "PATTERN", "not exactly once in %s: %r" % (f, bad[0][:50])
            for o, n in zip(olds, news):
                s = s.replace(o, n)
            open(path, "wb").write(s.encode("utf-8"))
        b = build(d)
        if b.returncode:
            tail = (b.stdout + b.stderr).strip().splitlines()
            return "BUILD", tail[-1] if tail else "build failed"
        try:
            t = subprocess.run([sys.executable, "tools/test_options.py", test],
                               cwd=d, capture_output=True, text=True, timeout=TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return "FAILS", "hung: no verdict in %ds" % TEST_TIMEOUT
        out = (t.stdout + t.stderr).strip().splitlines() or ["no output"]
        #  A failing test prints "FAIL (n)" and then the failures.
        why = out[1].strip() if t.returncode == 1 and len(out) > 1 else out[0]
        return ("FAILS" if t.returncode else "PASSES"), why[:90]
    finally:
        open(path, "wb").write(pristine)
        if open(path, "rb").read() != pristine:
            raise SystemExit("restore failed in the copy: " + path)


def main():
    args, only, jobs, listfile = sys.argv[1:], [], os.cpu_count() or 1, None
    while args:
        a = args.pop(0)
        if a == "-j" and args:
            jobs = max(1, int(args.pop(0)))
        elif listfile is None:
            listfile = a
        else:
            only.append(a)
    if listfile is None:
        print(__doc__.strip())
        return 2
    M = runpy.run_path(listfile)["M"]
    unknown = [n for n in only if n not in {m[0] for m in M}]
    if unknown:
        print("no such mutation: %s" % ", ".join(unknown))
        return 2
    muts = [m for m in M if not only or m[0] in only]

    #  One run at a time per set of copies: two would build in the same ones.
    os.makedirs(WORK, exist_ok=True)
    lock = open(os.path.join(WORK, "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another mutate.py is using %s" % WORK)
        return 2

    #  The controls go first, so their verdicts are in early.
    tests = sorted({m[4] for m in muts})
    work = [("control " + t, None, None, None, t) for t in tests] + list(muts)
    n = min(jobs, len(work))
    dirs = [os.path.join(WORK, "w%d" % k) for k in range(n)]
    t0 = time.time()
    syncs = [threading.Thread(target=sync, args=(d,)) for d in dirs]
    for th in syncs: th.start()
    for th in syncs: th.join()

    q = queue.Queue()
    for i, w in enumerate(work):
        q.put((i, w))
    verdicts, say = {}, threading.Lock()

    def worker(d):
        while True:
            try:
                i, (name, f, old, new, test) = q.get_nowait()
            except queue.Empty:
                return
            #  A control mutates nothing; any file will do for the restore.
            v = attempt(d, f or "build.sh", old, new, test)
            with say:
                verdicts[i] = v
                print("  [%d/%d %3.0fs] %-28s %-7s %s" % (len(verdicts), len(work),
                      time.time() - t0, name, v[0], v[1]), flush=True)

    workers = [threading.Thread(target=worker, args=(d,)) for d in dirs]
    for th in workers: th.start()
    for th in workers: th.join()

    #  The report, in list order.  A mutation is caught when its test fails.
    print()
    control = {w[4]: verdicts[i][0] for i, w in enumerate(work) if w[1] is None}
    bad = 0
    for i, (name, f, old, new, test) in enumerate(work):
        v, why = verdicts[i]
        if f is None:
            word = "ok" if v == "PASSES" else "CONTROL FAILS"
        elif control[test] != "PASSES":
            word = "INVALID"
        else:
            word = {"FAILS": "CAUGHT", "PASSES": "MISSED"}.get(v, v)
        bad += word not in ("ok", "CAUGHT")
        print("%-28s %-13s %s" % (name, word, why))
    print("\n%d mutations, %d controls, %d not caught or not run; %d copies, %.0fs"
          % (len(muts), len(tests), bad, n, time.time() - t0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
