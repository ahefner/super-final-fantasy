# Design notes

`options-design.md` is the live one: the options menu, every shipped flag,
the randomizer as built, the bank budgets, and "Things learned the hard way".
It is updated with every commit that changes what it describes.

The rest are explorations, written before (or instead of) building something:

    analysis.md             how the feature list could fit the SNES port at all
    randomization-notes.md  save-tied shuffles on the cartridge; partly built,
                            and its status paragraphs say where the build
                            departed from the plan
    enemy-shuffle-notes.md  FFR's formation, script, skill and status shuffles
    ffr-presets.md          what each New Game preset takes from FFR's, and
                            which of its flags the cartridge still lacks
    overworld-notes.md      alternate overworld maps, and the map in WRAM
    consumables-notes.md    FFR's New Consumables; parked

Paths are relative to the repository root.  `FF1Randomizer/`,
`FF1Disassembly/`, `overview.txt`, `randomization-concepts.txt` and
`map-renders/` are the project's working directory, one level above the
repository, and are not part of it.  `worldgraph/`, the world graph the
logic is distilled from, was there too until 2026-10-18 and is in the
repository now (user); it finds FFR's source beside the repository, or at
`FFR_ROOT` for a copy made elsewhere.  Line numbers cite the
commit each note names, and may have drifted since.
