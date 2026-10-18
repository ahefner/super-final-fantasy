#!/usr/bin/env python3
"""
run_vanilla.py -- build the vanilla world graph, check it three ways, and write
it out.

    python3 run_vanilla.py        # writes out/ next to this script

Checks:
  1. The vanilla playthrough: collect everything reachable, repeat.  The game
     must be winnable, and the order should be the one everybody knows.
  2. FFR's hand-kept model (ItemLocations.cs): for every chest, NPC, altar and
     the goal, the minimal sets of items needed to reach it.
  3. FFR's list of unused chests: none of them should be placed in a map.
"""
import colorsys
import json
import os
import time
from collections import Counter

import analysis
import build
import ffr_oracle as fo
import romdata as rd
from model import BIT, REQS, fmt
from png import Image, text

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def sphere_colour(s, n, dark=False):
    """Spheres that follow each other usually border each other on the map,
    so consecutive ones must look unlike each other.  The n hues are evenly
    spaced and visited with a stride near 0.38n that is coprime to n: every
    sphere gets its own hue (a plain golden-angle step wrapped the last
    sphere back onto the first's green), and consecutive ones land about
    140-150 degrees apart.  Brightness cycles through three levels on top.
    Water is the same colour, darker.  Unreachable is grey."""
    if s is None:
        return (40, 40, 60) if dark else (90, 90, 90)
    from math import gcd
    k = min((k for k in range(1, max(2, n)) if gcd(k, n) == 1),
            key=lambda k: abs(k - 0.382 * n)) if n > 2 else 1
    h = (0.33 + ((s * k) % n) / n) % 1.0
    v = (0.95, 0.70, 0.82)[s % 3]
    r, g, b = colorsys.hsv_to_rgb(h, 0.80, v * (0.6 if dark else 1.0))
    return int(r * 255), int(g * 255), int(b * 255)


def first_sphere(spheres):
    out = {}
    for i, (seen, _, _) in enumerate(spheres):
        for n in seen:
            out.setdefault(n, i)
    return out


def overworld_png(g, ow, sph, n, path, scale=3):
    img = Image(256 * scale, 256 * scale)
    for i in range(65536):
        x, y = i & 255, i >> 8
        if ow.flabel[i] >= 0:
            c = sphere_colour(sph.get(ow.fnode[ow.flabel[i]]), n)
        elif ow.slabel[i] >= 0:
            c = sphere_colour(sph.get(ow.snode[ow.slabel[i]]), n, dark=True)
        elif ow.rlabel[i] >= 0:
            c = sphere_colour(sph.get(ow.rnode[ow.rlabel[i]]), n, dark=True)
        else:
            c = (20, 20, 20)
        img.rect(x * scale, y * scale, scale, scale, c)
    sx, sy = ow.pos["start"]
    img.rect(sx * scale - 4, sy * scale - 4, scale + 8, scale + 8, (0, 0, 0))
    img.rect(sx * scale - 2, sy * scale - 2, scale + 4, scale + 4, (255, 255, 255))
    for s in range(n):
        img.rect(8, 8 + s * 11, 9, 9, sphere_colour(s, n))
        text(img, 22, 9 + s * 11, "%d" % s)
    img.save(path)


def maps_png(g, maps, sph, n, path, scale=3, cols=8):
    cw, ch = 64 * scale + 8, 64 * scale + 20
    rows = (len(maps) + cols - 1) // cols
    img = Image(cols * cw, rows * ch, (25, 25, 25))
    for k, sm in enumerate(maps):
        ox, oy = (k % cols) * cw + 4, (k // cols) * ch + 16
        text(img, ox, oy - 12, rd.MAP_NAMES[sm.m][:24])
        for i in range(4096):
            x, y = i & 63, i >> 6
            kind = sm.kind[i]
            if sm.label[i] >= 0:
                c = sphere_colour(sph.get(sm.region_nodes[sm.label[i]]), n)
            elif isinstance(kind, tuple):
                c = (255, 255, 255)
            elif sm.spec[i] == "treasure":
                c = (255, 215, 0)
            else:
                c = (45, 45, 45)
            img.rect(ox + x * scale, oy + y * scale, scale, scale, c)
    img.save(path)


def cart_estimate(g, keep, edges):
    """Bytes for the tables a cart would carry, in the simplest layout:
    one-byte node ids, edges as (src, dst, req index), requirement masks as
    four bytes, a chest table of one node per chest id, and the rest as
    (node, kind, id, reward) records."""
    reqs = sorted({e[2] for e in edges} | {l.req for l in g.locations})
    multi = sum(1 for l in g.locations if len(l.nodes) > 1)
    chests = sum(1 for l in g.locations if l.kind == "chest")
    others = len(g.locations) - chests
    b = {"nodes": len(keep), "edges": len(edges), "distinct requirement masks": len(reqs),
         "edge table": 3 * len(edges), "requirement table": 4 * len(reqs),
         "chest -> node table": 256, "other locations": 5 * others,
         "locations reachable from 2+ nodes": multi}
    b["total bytes"] = b["edge table"] + b["requirement table"] + b["chest -> node table"] + b["other locations"]
    return b


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    g, ow, maps, missing = build.build()
    t_build = time.time() - t0
    t0 = time.time()
    spheres, owned = analysis.playthrough(g)
    t_play = time.time() - t0
    sph = first_sphere(spheres)
    keep, kept_edges = analysis.prune(g)
    est = cart_estimate(g, keep, kept_edges)

    # FFR comparison, raw and with FFR's vehicle semantics.
    chests, owr, floors = fo.load()
    others = fo.load_others()
    ship_i = ow.pos["ship"][0] | (ow.pos["ship"][1] << 8)
    ship_sea = ow.snode[ow.slabel[ship_i]]
    abstraction = [(g.start, ow.sky, BIT["AIRSHIP"], "FFR: the airship flies from anywhere"),
                   (g.start, ship_sea, BIT["SHIP"], "FFR: the ship appears where it is found")]
    targets = []
    mine = {(l.kind, l.ident): l for l in g.locations}
    unused_report = []
    for cid, c in sorted(chests.items()):
        if c["unused"]:
            unused_report.append((c["name"], cid, ("chest", cid) in mine))
        else:
            targets.append((c["name"], c["maploc"], mine[("chest", cid)].nodes))
    for key, (name, maploc) in sorted(others.items()):
        targets.append((name, maploc, mine[key].nodes))

    def compare(extra):
        req = analysis.requirements(g, extra)
        agree, diffs = 0, []
        for name, maploc, nodes in targets:
            f = sorted(analysis._minimise(fo.maploc_requirements(maploc, owr, floors)))
            m = sorted(analysis._minimise([s for n in nodes for s in req.get(n, [])]))
            if f == m:
                agree += 1
            else:
                diffs.append((name, maploc, f, m))
        return agree, diffs
    raw_agree, raw_diffs = compare([])
    air_agree, _ = compare(abstraction[:1])
    abs_agree, abs_diffs = compare(abstraction)
    raw_pattern = Counter()
    for name, maploc, f, m in raw_diffs:
        added = {fmt(x & ~y) for x in m for y in f if (y & ~x) == 0} or {"other"}
        raw_pattern[", ".join(sorted(added))] += 1

    overworld_png(g, ow, sph, len(spheres), os.path.join(OUT, "overworld-spheres.png"))
    maps_png(g, maps, sph, len(spheres), os.path.join(OUT, "maps-spheres.png"))

    with open(os.path.join(OUT, "vanilla-graph.json"), "w") as f:
        json.dump({
            "requirements": REQS,
            "start": g.start,
            "nodes": [{"id": n.id, "kind": n.kind, "label": n.label, "tiles": len(n.tiles),
                       "kept": n.id in keep} for n in g.nodes],
            "edges": [{"src": s, "dst": d, "req": fmt(r), "why": w} for s, d, r, w in g.edges],
            "locations": [{"kind": l.kind, "id": l.ident, "label": l.label, "nodes": l.nodes,
                           "req": fmt(l.req), "reward": l.reward} for l in g.locations],
        }, f, indent=1)

    kinds = Counter(n.kind for n in g.nodes)
    kept_kinds = Counter(g.nodes[n].kind for n in keep)
    lines = ["# Vanilla world graph: sanity check", "",
             "Generated by `run_vanilla.py`.  Build %.2fs, playthrough %.2fs (Python)." % (t_build, t_play), "",
             "## Size", "",
             "| | all | kept (pruned) |", "|---|---|---|"]
    for k in ("ow-foot", "ow-river", "ow-sea", "sky", "sm"):
        lines.append("| %s nodes | %d | %d |" % (k, kinds[k], kept_kinds[k]))
    lines += ["| edges | %d | %d |" % (len(g.edges), len(kept_edges)),
              "| locations | %d | |" % len(g.locations), "",
              "Location kinds: " + ", ".join("%s %d" % kv for kv in sorted(Counter(l.kind for l in g.locations).items())), "",
              "Cart table estimate (pruned graph):", ""]
    lines += ["  - %s: %s" % kv for kv in est.items()]
    lines += ["", "## Vanilla playthrough", "",
              "Winnable: **%s**, in %d spheres." % ("yes" if owned & BIT["CHAOS"] else "NO", len(spheres)), "",
              "| sphere | nodes reachable | gained | from |", "|---|---|---|---|"]
    for i, (seen, new, gained) in enumerate(spheres):
        src = sorted({l.label + ("=" + l.reward if l.kind == "chest" else "")
                      for l in new if l.reward and BIT.get(l.reward, 0) & gained})
        lines.append("| %d | %d | %s | %s |" % (i, len(seen), fmt(gained), ", ".join(src)))
    lines += ["", "## Against FFR's hand-kept model", "",
              "%d locations compared: 241 used chests, 13 NPC rewards, 4 altars, Chaos and the caravan." % len(targets), "",
              "  - **With FFR's vehicle semantics: %d agree, %d differ.**  FFR's `Airship` means the airship can be"
              " flown from anywhere, and its `Ship` means the ship can be boarded -- it appears at the dock nearest"
              " where it was found (ItemLocations.ShipLocations).  Two edges express that." % (abs_agree, len(abs_diffs)),
              "  - With the airship reading alone: %d agree, %d differ -- the rest is the ship." % (air_agree, len(targets) - air_agree),
              "  - Without either (vanilla literally: the ship waits at Pravoka, the airship in the desert): %d agree,"
              " %d differ.  The extra requirement the graph asks for, by count:" % (raw_agree, len(raw_diffs)), ""]
    lines += ["    - %s: %d" % kv for kv in raw_pattern.most_common()]
    for name, maploc, f, m in abs_diffs:
        lines.append("  - DIFF %s (%s): FFR %s, graph %s" % (name, maploc, " | ".join(map(fmt, f)), " | ".join(map(fmt, m))))
    lines += ["", "FFR's unused chests (should be in no map):", ""]
    lines += ["  - %s (chest %02X): %s" % (n, c, "PLACED IN A MAP" if placed else "not placed") for n, c, placed in unused_report]
    lines += ["", "## Map objects that block a tile", "",
              "Stationary objects visible at the start.  `gate` needs the item to pass;"
              " `yields` leaves when talked to (a fight, usually) and is no obstacle; `wall` never moves.", "",
              "| map | object | routine | treated as | needs |", "|---|---|---|---|---|"]
    for sm in maps:
        for oid, routine, how, req, (x, y) in sm.blockers:
            lines.append("| %s | %02X at (%d,%d) | %s | %s | %s |" % (rd.MAP_NAMES[sm.m], oid, x, y, routine, how, fmt(req)))
    talk = rd.talk_routines()
    lines += ["", "## Objects listed in more than one map", "",
              "Visibility is per object id, so every copy appears and disappears together."
              "  The generic bat ($57), shared by every cave on purpose, is left out.", ""]
    for oid, where in sorted(g.duplicates.items()):
        if oid == 0x57:
            continue
        lines.append("  - %02X %s: %s" % (oid, talk[oid], "; ".join("%s (%d,%d)" % w for w in where)))
    lines += ["", "Reward NPCs not found in any map: %s" % (", ".join(missing) or "none"),
              "Overworld findings: %s" % ("; ".join(ow.findings) or "none"),
              "Overworld regions: %s" % ", ".join("%s %d" % kv for kv in ow.stats.items())]
    with open(os.path.join(OUT, "vanilla-report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print("winnable:", bool(owned & BIT["CHAOS"]), "spheres:", len(spheres))
    print("FFR comparison: %d/%d agree with FFR's vehicle semantics; raw %d/%d"
          % (abs_agree, len(targets), raw_agree, len(targets)))
    print("pruned: %d nodes, %d edges; cart estimate %d bytes" % (len(keep), len(kept_edges), est["total bytes"]))


if __name__ == "__main__":
    main()
