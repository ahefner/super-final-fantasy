# The overworld map -- notes for a future feature

Parked exploration, 2026-09-22.  Nothing here is implemented.  The question
was whether the port could offer alternate overworld maps, and whether the map
could live in work RAM so it could be generated, edited or swapped.

Everything below was measured against the built ROM, not read off a wiki.  The
numbers are reproducible: the scripts were one-offs, but every figure names the
label or file it came from.

## 1. What it occupies today

The overworld is **all of NES bank `$01`**, 98% full:

    row pointer table      512 bytes   $8000-$81FF   256 rows x 2
    compressed map      15,529 bytes   $8200-$BEA8
    MinimapDecompress      313 bytes
    free                    30 bytes

256x256 tiles, run-length encoded **per row**, each row terminated by `$FF`.
Uncompressed that is 65,536 bytes, so the encoding is doing real work -- 23.7%.
Rows run 3 to 108 bytes, mean 60.7.

Only sixteen rows are ever decompressed.  `mapdata = $7000`, `$1000` bytes,
slot chosen by `row & $0F`: a sliding window, one row decompressed per vertical
tile step by `LoadOWMapRow` (`game/bank_0F.asm`).

The RLE, from `DecompressMap`:

  - `$00-$7F` -- one tile, that value
  - `$80-$FE` -- a run; low seven bits are the tile, the **next** byte is the
    length, and a length of `0` means 256
  - `$FF` -- end of row

Only two files read the compressed map: `game/bank_0F.asm` (`LoadOWMapRow`,
`LoadStandardMap`) and `game/bank_01.asm` (`MinimapDecompress`).

## 2. The connection layer

In bank `$00` (189 bytes free), 384 bytes all told:

| table | address | size | what it is |
|---|---|---|---|
| `lut_EntrTele_X/Y/Map` | `$AC00/$AC20/$AC40` | 96 (32 slots, 30 used) | where an overworld entrance lands: in-map x, y and map id |
| `lut_ExitTele_X/Y` | `$AC60/$AC70` | 32 (16 slots, 9 used) | where an exit teleport drops you, in overworld coordinates |
| `lut_NormTele_X/Y/Map` | `$AD00/$AD40/$AD80` | 192 (64) | map-to-map; nothing to do with the overworld |
| `lut_Tilesets` | `$ACC0` | 64 | tileset per map |

Three things that are **not** tables, and that shape the whole design:

  - **Entrance positions are in the map tiles.**  A tile carries a 6-bit
    teleport id in its properties; `lut_EntrTele_*` only says where that id
    goes.  Placing an entrance is a map edit, not a table edit.
  - **The minimap is generated**, not stored.  `MinimapDecompress` reads
    `lut_OWPtrTbl` directly, so a new map gets its minimap for free.
  - **Encounter domains are positional** -- an 8x8 grid of 32x32-tile regions
    computed from the coordinates, not a lookup.  A new map inherits a grid
    that has nothing to do with its geography.  Worth checking what FFR does.

## 3. Warp versus exit teleport

This distinction is the important one and it is easy to get backwards.

**Warp is stack unwinding and carries no coordinates.**  The handler is:

    @TeleOrWarp:
        BNE @Teleport
          JSR ScreenWipe_Close
          RTS

That `RTS` escapes one level of the recursive `DoStandardMap` call.  The
overworld's entrance path is `JSR DoStandardMap` / `JMP DoOverworld`, and
`ow_scroll_x/y` is never touched anywhere along it -- so warping out of a first
floor returns you exactly where you went in.  **On any map, automatically**,
because the entrance tile's own position *is* the exit position.  The WARP
spell is the same mechanism, reached by adding 6 to the stack pointer.

**Exit teleport is the one with coordinates.**  It loads `lut_ExitTele_X/Y`
into the overworld scroll and then `JMP DoOverworld`, which wipes the warp
chain -- a one-way jump to a fixed point.

Scanning `lut_SMTilesetProp` (`$8800` in `BANK_SMINFO`, 8 tilesets x 128 tiles
x 2 bytes) for the property bits gives the live counts:

    warp tiles          8 distinct
    normal teleports   63 distinct
    exit teleports      9 distinct   ids 0-8; slots 9-15 are zeroed

The nine, by (tileset, id): (1,3) (1,4) (2,0) (2,1) (2,5) (2,6) (3,2) (5,7)
(6,8) -- tileset 2 carries four.  Their overworld coordinates:

    id 0 ( 42,174)   id 3 (130, 45)   id 6 (188,205)
    id 1 ( 30,175)   id 4 (153,159)   id 7 ( 62, 56)
    id 2 (197,183)   id 5 ( 65,187)   id 8 (194, 59)

**So the per-map coordinate burden is 18 bytes**, and the constraint is one of
consistency rather than volume: a warp exit cannot disagree with the map, an
exit teleport can, and silently -- change the world and you walk out of a cave
into the sea.

**Design default that falls out of this:** make every dungeon exit a Warp and a
generated map is self-consistent by construction.  The only overworld
coordinates left anywhere are the party start (`lut_InitUnsramFirstPage`) and
the vehicle spawns, which the Free SHIP / AIRSHIP flags already parameterise.
The nine exit teleports are exactly the places where the original deliberately
spits you out somewhere other than the door; a generator has to have an opinion
about those, and an edit flag has to avoid moving them or the entrance each one
pairs with.

## 4. A bug in MinimapDecompress

`MinimapDecompress` is a copy/paste of `DecompressMap` -- Disch's own comment
calls it "the stupidest, biggest waste of code and space I can think of" -- and
the copy is not faithful.  Its run loop:

    LDA (tmp), Y     ; run length
    TAY
    DEY              ; length - 1; @SingleTile below writes the last one
    LDA tmp+2        ; the tile
  @RunLoop:
    STA mm_mapbuf, X
    INX
    DEY
    BNE @RunLoop

A do-while where it needed a while.  **A run of length 1 makes `DEY` produce 0,
the loop is entered anyway, `DEY` wraps to `$FF`, and it writes 257 tiles
instead of one.**  `DecompressMap` gets the same case right -- its `DEX / BNE`
exits immediately -- so the map draws correctly and only the minimap is wrong.

It survives on the original cartridge because **the shipped map contains no run
of length 1**; decoding all 256 rows, the smallest run present is 2, since an
encoder naturally emits a single tile as a single byte rather than as a run.
The bug can therefore only fire on re-encoded data, which is what a map editor
produces.  Reported symptom: a glitched minimap against an edited map, with the
map itself fine.

Damage is confined to the row -- `X` is eight bits and `mm_mapbuf` is 256 bytes
(`$0600`, with `mm_mapbuf2` at `$0700`), so the writes wrap inside the row
rather than spilling.  A scrambled row, not a crash.

**Fixed (2026-10-17, `patches/bank_01/minimap_run1.patch` and `_run2`, one
for each half):** the tile is loaded before the count, and a `BEQ
@SingleTile` follows the `DEY`, so a length of 1 goes straight to the single
tile.  Byte-neutral: the loop leaves `Y` at 0 whichever way it exits, so the
`LDY #0` after it was redundant and gives its two bytes to the branch; the 30
unused bytes below are untouched.  A length of 0 still means 256, as in
`DecompressMap`.  `test_minimap` points a private copy's `lut_OWPtrTbl` at
rows made in RAM -- every run length 0-255 among them, all-singles, all
length-1 runs -- and holds both halves (`mm_mapbuf`, `mm_mapbuf2`) to the
game's own `DecompressMap` on the same bytes, in both halves of the pointer
table and across the row-255 wrap; and all 256 shipped rows, through their
own pointers, as they were.  Restoring the bug in either half fails it.

**The encoder rule is now about size, not safety.**  There is no encoder in
the tree yet; the overworld edits will need one.  A length-1 run costs two
bytes where the tile alone costs one, so the encoder should still never emit
one -- but a map that has them now decodes correctly everywhere.  One rule
it must keep for correctness: **a run of tile `$7F` cannot be written**, since
`$80 | $7F` is `$FF`, the row's end; `$7F` must go out as single tiles.

## 5. Alternate maps, if we want them

Cheap.  The map is reached through exactly **two** `LDA #BANK_OWMAP` sites,
both in the fixed bank -- `LoadOWMapRow` and `CallMinimapDecompress`.  Turning
that constant into a load is the move every other flag in this project has
made.  `LDA a:opt_owbank` is one byte more than the immediate at each site, and
the fixed bank has exactly three free: it fits, with one to spare.

Space is a non-issue -- 832KB of the image is unused, thirteen more 64KB
chunks, and a map needs one chunk's low half.

Two constraints on the ROM-resident form:

  - **15.5KB of RLE is the budget** and it is 98% spent.  A map with more
    detail and fewer runs will not fit.  `DecompressMap` does handle crossing
    into the next bank (`@NextBank`), but the pointer table is 16-bit, so a
    crossing only works if the rows are laid out in order.
  - **`MinimapDecompress` lives in the map's own bank** (313 bytes), so each
    alternate map chunk needs its own copy.

## 6. The map in work RAM

The point of this is not speed.  It is that a **writable** map makes three
things possible at once: decompressing a preset, patching the vanilla map from
a list of edits (FFR has several such flags), and generating one outright.

**Keep the `$7000` window; change only where it gets its bytes.**  Hold the map
flat and uncompressed at `$7F0000`, 256 bytes per row, and `LoadOWMapRow`
becomes a 256-byte `MVN` from `$7F0000 + row*256`.  Then:

  - the twelve `ORA #>mapdata` sites do not change at all -- `mapdata` is still
    `$7000`, still `row & $0F`.  (Tearing the window out instead is the
    expensive version: twelve sites that would each need to grow, in a bank
    with three bytes free.  Don't.)
  - `LoadOWMapRow` gets *smaller*, which is a gain in the bank that needs one
  - `MinimapDecompress` reads the same flat copy, so it gets smaller too, and
    deleting its RLE deletes the bug in section 4
  - tile properties, the scroll code, the domain grid: untouched

Filling it is 65,536 WRAM writes, roughly 520K master cycles -- a frame and a
half behind the screen wipe, invisible.

Once the authoritative copy is in WRAM the ROM form no longer has to be row
RLE, no longer has to fit one bank, and for a generated map there is no ROM
form at all.  One bank per preset map becomes a convenience rather than a
ceiling.

**The ending buffer does not need relocating.**  `THEENDBANK = $7F`,
`THEENDBUF = $6800`, `$700` bytes, so it overlaps.  But the ending scene loops
forever and the only way back to the overworld is a reset through the title,
so as long as the WRAM map is built on the way in rather than held from boot,
the two can share the page.  This is the same mutually-exclusive-scenes
argument the port already makes elsewhere -- but note `analysis.md`'s warning
that coverage by a single name is the test, not absence of a name.

## 7. Order, if this is picked up

1. Fix `MinimapDecompress` (section 4).  Independent of everything else, four
   bytes, and it makes any map editing downstream trustworthy.
2. Alternate maps (section 5) if preset worlds are the goal.  It is a flag.
3. The WRAM copy (section 6) only when a feature actually needs the map to be
   writable.  It is not a prerequisite for 2.
