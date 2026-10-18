# worldgraph -- the world as a graph, from the tiles

A prototype of the logic tooling in `randomization-notes.md` §4.  It builds the
region graph the cart's item placer would search, from the game's own map and
tile data, and checks it against FFR's independent model.  Vanilla only, so
far.

    python3 run_vanilla.py      # build, check, write out/
    python3 selftest.py         # the checks, plus mutations proving they bite

Standard library only.  Reads the built port (`SuperFinalFantasy.sfc` in the
tree this is in -- it moved into the repository, `snes/worldgraph/`, on
2026-10-18), the vanilla source for the talk-routine table, and, for the
cross-check only, FFR's source (`FF1Randomizer/` beside the repository, or
under `FFR_ROOT`).

## The model

**Nodes** are regions a party can move around freely in one mode:

  - `ow-foot`, `ow-river`, `ow-sea`: connected overworld tiles on foot, by
    canoe, by ship
  - `sky`: the airship
  - `sm`: connected floor in one standard map

**Edges** carry a requirement mask: vehicles, map changes, key items, events
(`model.py`).  **Locations** hand something out: chests, NPC rewards, the
four altars, the caravan, raising the airship, and Chaos.  Each has a
requirement of its own (Matoya wants the CRYSTAL).

Everything comes from tile and table data except two short lists in
`build.py`: what each reward NPC gives and wants, keyed by talk routine, and
which object is the goal.  The movement rules each module encodes, with the
routine each comes from:

| module | rules | from (bank `$0F`) |
|---|---|---|
| `overworld.py` | the four forbid bits, docks, canoe and ship boarding, the bridge and canal sprites, chime tiles, airship landing and the floater | `ProcessOWInput`, `OWCanMove`, `BoardCanoe`, `BoardShip`, `UnboardBoat`, `LandAirship`, `FlyAirship` |
| `standard.py` | walls, chests, locked doors, the crown/cube/four-orb tiles, altars, teleports, and blocking objects | `CanPlayerMoveSM`, `IsObjectInPath`, `lut_SMMoveJmpTbl` |

Blocking objects are stationary objects visible at the start.  How each is
treated depends on its talk routine:

  - **Gate**: it hides once the party has an item.  The Titan (RUBY), the sub
    engineer (OXYALE), the black orb (all four orbs), Astos (CROWN) and
    Nerrick (TNT); also the rod and lute plates, by item use.
  - **No obstacle**: it hides after a fight or a word.
  - **Wall**: it never moves.

Two things are deliberately left out:

  - **Warp tiles.**  A warp only returns the party somewhere it has already
    been, so it adds no reachability.
  - **Re-boarding the ship at an arbitrary dock.**  The ship is boarded where
    it starts; everything it can then reach is reached from the sea.

## Results on vanilla

See `out/vanilla-report.md`.

  - **Winnable, in 22 spheres, in exactly the order everyone knows.**
    Princess; bridge and lute; ship; Crown; Crystal; Herb; Key; TNT; Canal;
    Ruby and Vampire; Rod; Earth orb; Canoe; Floater, Tail and Fire orb;
    airship; Cube and Bottle; Oxyale; Slab and Water orb; translation; Chime;
    Adamant and Air orb; Chaos.
  - **All 260 locations agree with FFR's hand-kept model**: 241 chests, 13
    NPCs, 4 altars, Chaos and the caravan, compared as minimal requirement
    sets.  This holds once FFR's reading of SHIP and AIRSHIP is applied; see
    the first finding.
  - **FFR's 13 unused chest ids** are placed in no map.
  - **Size.**  654 nodes and 328 edges raw.  Pruned to what can reach a
    location, it is 161 nodes, 287 edges and 26 distinct requirement masks:
    about **1.3KB** of cart tables.  One BFS over 287 edges is a few
    milliseconds on the 65816.
  - **The self-test** confirms the comparison notices a broken rule: locked
    doors without the KEY, the Titan without the RUBY, an open canal, the
    crown tile without the CROWN.

`out/overworld-spheres.png` and `out/maps-spheres.png` colour every region by
the sphere in which it becomes reachable.

## Findings

  - **FFR reads SHIP and AIRSHIP as "can use it", not "owns it".**  Taken
    literally against the tiles, 238 of the 260 locations disagree.  With
    FFR's airship reading added, 129 still disagree.  With both readings,
    none do.  Each reading is one extra edge in `run_vanilla.py`.
  - **The airship reading is safe as it stands.**  Raising the airship means
    standing on a floater tile, and the airship waits in the same desert
    region, so owning AIRSHIP implies whatever it took to get there.
  - **The ship reading needs a mechanism.**  Literally, the ship waits at
    Pravoka, so everything reached by sea also needs the way to Pravoka
    (the BRIDGE in vanilla).  FFR makes SHIP alone sufficient with
    `ItemLocations.ShipLocations`: the ship spawns at whichever of five
    inner-sea docks is nearest the location that gave it.  A shuffled cart
    needs that table, or SHIP found in a Coneria chest would leave the ship
    stranded at Pravoka.
  - **Two stray objects in vanilla's tables.**  Both are inert, and the cart
    removes both since 2026-10-14 (mkrom.py, `overlay_strays`); this reads the
    cart, so it no longer sees them:
      - **The rod plate** (`$16`) is listed again in Sky Palace 2F, at the
        same coordinates as in Earth B3 but with the in-room flag set.  It
        stands inside a solid wall.  Visibility is per id, so it shows until
        the ROD is used anywhere.  In vanilla the ROD is always used before
        Sky Palace can be reached, so it can never be seen.  In a shuffled
        seed the order is not guaranteed, so at worst a plate sprite might be
        drawn in a wall.  That is worth one look.
      - **The fairy** (`$13`) is listed in Ice Cave B1 as well as Gaia, on
        floor.  The floor is the map's outer void, a region joined to
        nothing, so she appears there after the bottle is opened and no one
        can reach her.
    Each map's table holds only that single entry.  The tool now counts every
    copy of a reward NPC and lists all duplicates in the report, so a copy
    that *is* reachable on another map, or after an edit, cannot be dropped
    silently.
  - **Most overworld regions do not matter.**  300 walkable regions, almost
    all islets nobody lands on, prune to 35.

## Not yet

  - **Map edits.**  The plan is a bit per edit, treated as an owned item, on
    edges derived from the edited tiles.  The tool needs a tile-patch input
    and the oracle needs a per-combination check.
  - **Entrance and floor shuffle: prototyped.**  `wiring.py` holds the
    three teleport tables and ports FFR's shuffle onto them (`fe_shuffle`,
    over FFR's records from `ffr_teleports.py`); `build.build(wiring=...)`
    builds on any wiring, with warp-back and vehicle returns in `g.returns`;
    `fecheck.py` checks stranding, shared landings, dealt floors' warps
    back, nesting depth and whether Titan's Tunnel opens ground
    (`fe_selftest.py` shows each check biting).  `run_fe.py 200` runs them
    over FFR-style seeds.  See `snes/docs/randomization-notes.md` §4.6, §9.3.
  - **The ship-spawn table**, derived from the graph rather than copied from
    FFR.
  - **Alternate maps, beyond the check below.**  `run_ffr_map.py` runs FFR's
    maps through the graph (`ffr_maps.py` reads the tiles, positions, moved
    exits and ship docks).  With the vanilla item placement, as of 2026-10-07:

    | maps | winnable as placed | every location reachable with everything owned |
    |---|---|---|
    | `procgen1-3` | 3 / 3 | 3 / 3 |
    | `crescent/elfland/melmond_start` | 0 / 3 | -- |
    | `normal256` | 245 / 256 | 256 / 256 |
    | `shuffled256` | 24 / 256 | 256 / 256 |
    | `unsafe256` | 22 / 256 | 256 / 256 |

    So the maps are sound, but most of FFR's pools are built for its
    placement rather than vanilla's order.  The shuffled pools scatter
    towns and dungeons: in `shuffled256/00000505` the Temple of Fiends is not
    on the starting continent.  Even `normal256` has maps like `2142F7BE`,
    whose bridge crosses to a bare islet two tiles of sea short of Pravoka.
    The last column needs FFR's ship spawn table: read literally, with the
    ship waiting at Pravoka, 176 of them fail.
  - **A placer: prototyped.**  `placement.py` is FFR's
    `PredictivePlacement` over the `reach()` primitive; `run_fe.py --place`
    places and re-checks every seed.  `placement.setup` turns the cart's
    incentive rows into FFR's flags, `build.build(early=...)` takes FFR's
    four Early flags, and `run_incentives.py` sweeps settings of the rows,
    on the vanilla world or (`--efs`) under FFR's Entrance and Floor
    preset.  On FFR's own overworld it places FFR's default pool 192 times
    in 200, against FFR's 49 in 50 (`snes/docs/randomization-notes.md`
    §4.6).  Still missing: FFR's balanced location picker.
