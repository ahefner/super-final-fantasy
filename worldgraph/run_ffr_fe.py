#!/usr/bin/env python3
"""
run_ffr_fe.py -- FFR's own entrance and floor shuffles beside the port's.

    python3 run_ffr_fe.py BASE.nes [seeds] [preset.json]

BASE.nes is the original game: ../ff1e.nes (outside the repository, and to
stay so), whose PRG and CHR are byte for byte what the disassembly builds.

Generates `seeds` ROMs with FFR's command-line tool (FF1R, built under
../FF1Randomizer) from BASE.nes, the original game, using FFR's Entrance and
Floor Shuffle preset unless another is named; reads each back (ffr_rom.py);
and runs the same checks (fecheck.py) on it as on the port's shuffles
(wiring.fe_shuffle) for the same number of seeds.

Item placement is not compared: the graph's locations hand out vanilla's
items, not FFR's, so "winnable" means nothing here.  What is compared is the
wiring: strands, shared landings, floors dealt without a warp back, nesting
depth, how much moves, and whether Titan's Tunnel opens new ground -- on the
vanilla overworld for both, so only the wiring differs, and on FFR's own
overworld (its preset edits the map) as a second column.
"""
import os
import subprocess
import sys
import tempfile
from collections import Counter

import build
import fecheck
import ffr_rom
import wiring

import romdata as rd

HERE = os.path.dirname(os.path.abspath(__file__))
FFR = os.path.join(rd.ROOT, "FF1Randomizer")
FF1R = os.path.join(FFR, "FF1R", "bin", "Release", "net10.0", "FF1R.dll")
PRESET = os.path.join(FFR, "FF1Blazorizer", "wwwroot", "presets", "Entrance_Floor_Shuffle.json")


def summarise(rows):
    n = len(rows)
    out = {}
    for key in ("strands", "shared landings", "dealt without a warp back"):
        out["no " + key] = "%d/%d" % (sum(1 for r in rows if not r[key]), n)
    out["titan opens (vanilla map)"] = "%d/%d" % (sum(1 for r in rows if r["titan opens"]), n)
    if "titan opens (own map)" in rows[0]:
        out["titan opens (own map)"] = "%d/%d" % (sum(1 for r in rows if r["titan opens (own map)"]), n)
    out["deepest level"] = dict(sorted(Counter(r["deepest level"] for r in rows).items()))
    out["entrances moved"] = dict(sorted(Counter(r["entrances moved"] for r in rows).items()))
    out["teleports moved"] = "%d-%d" % (min(r["teleports moved"] for r in rows),
                                        max(r["teleports moved"] for r in rows))
    return out


def check(w, ow_tiles=None):
    van = wiring.Wiring.vanilla()
    #  What the floor shuffle dealt: teleports that now land elsewhere --
    #  except those that land in their own map, which are other flags' work
    #  (OrdealsPillars rearranges the Ordeals maze, landing on floor by design).
    own = {t for t, d in van.normal.items() if d[0] == w.normal[t][0] == van.normal[t][0]}
    w.dealt = {d for t, d in w.normal.items() if d != van.normal[t] and t not in own}
    g, *_ = build.build(wiring=w)
    r = fecheck.report(g, w)
    r["entrances moved"] = sum(1 for e in range(30) if w.entrance[e] != van.entrance[e])
    r["teleports moved"] = sum(1 for t in range(64) if w.normal[t] != van.normal[t])
    if ow_tiles is not None:
        g2, *_ = build.build(ow_tiles=ow_tiles, wiring=w)
        r["titan opens (own map)"] = fecheck.titan_opens(g2)
    return r


def main():
    base = os.path.abspath(sys.argv[1])       # FF1R runs from its own directory
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    preset = sys.argv[3] if len(sys.argv) > 3 else PRESET
    ffr_rows, port_rows = [], []
    failures = Counter()
    #  The port shuffles with the preset's own settings.
    import json
    f = json.load(open(preset))["Flags"]
    opts = dict(towns=bool(f.get("Towns")), entrances=bool(f.get("Entrances")),
                floors=bool(f.get("Floors")), mixed=bool(f.get("EntrancesMixedWithTowns")),
                dead_ends=bool(f.get("EntrancesIncludesDeadEnds")),
                include_coneria=bool(f.get("IncludeConeria")),
                unsafe_start=bool(f.get("AllowUnsafeStartArea")))
    print("port settings from the preset:", opts)
    with tempfile.TemporaryDirectory() as tmp:
        for seed in range(1, n + 1):
            out = os.path.join(tmp, "s%08X.nes" % seed)
            res = subprocess.run(["dotnet", FF1R, "generate", base, "--seed", "%08X" % seed,
                                  "-j", preset, "-o", out], capture_output=True, text=True,
                                 cwd=os.path.dirname(FF1R))
            port_rows.append(check(wiring.fe_shuffle(seed, **opts)))
            if res.returncode:
                #  FFR's own placement can give up ("could not meet
                #  incentivization requirements") and the command line tool
                #  then dies; the web version would roll another seed.
                why = [l for l in res.stdout.splitlines() + res.stderr.splitlines() if "Exception" in l]
                failures[(why[0].split(": ", 1)[-1] if why else "exit %d" % res.returncode)] += 1
                continue
            ffr_rows.append(check(ffr_rom.wiring(out), ffr_rom.overworld(out)))
    print("FFR generated %d of %d seeds; failures: %s" % (len(ffr_rows), n, dict(failures) or "none"))
    for name, rows in (("FFR (%s)" % os.path.basename(preset), ffr_rows), ("port (wiring.fe_shuffle)", port_rows)):
        print("== %s, %d seeds" % (name, len(rows)))
        for k, v in (summarise(rows) if rows else {}).items():
            print("   %-28s %s" % (k, v))


if __name__ == "__main__":
    main()
