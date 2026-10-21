# New Game's presets

One file per entry of the New Game list, in filename order -- rename to
reorder.  `tools/genpresets.py` reads them at build time; a mistake stops
the build and says where.

```toml
name = "Beginner"                 # what the list shows, up to 28 characters
inherit = "Improved Vanilla"      # optional: the preset to start from
title = "Improved"                # optional: the title screen's preset this is
description = """
Up to five lines of 28 once wrapped, in the game's font: letters, digits,
space and ' , . - ! ? % + -- no colon.
"""

[settings]
"Gold and XP" = "250%"            # a value row: its readout, as the screen shows it
"Speed hacks" = true              # a checkbox: true or false
```

Keys are the settings screen's labels and values its readouts, so a preset
can be written by looking at the screen.  Improved Vanilla is the base
(`base = true`): it sets every setting, and every other preset starts from
it, or from the preset it `inherit`s, and sets only what differs.  A new
row on the settings screen needs its default in the base, or the build
stops.  The respond rate is never a preset's.

Design: `docs/options-design.md`, "New Game's presets".
