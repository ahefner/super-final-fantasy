# The overworld's design rules

Analysis, 2026-11-15, for the overworld tooling: mirrored maps, maps made from
an image, and checking maps edited by hand (the user: rules "to ensure
coastlines, mountains, forests, etc. are shaped correctly along the edges to
avoid abrupt transitions, which otherwise involves tedious tile-by-tile
painting").  Everything here was measured on the vanilla map.  The scripts are
in `map-renders/rules/` and `map-renders/mirror/` (outside the repository),
and the figures are reproducible from them.

## 1. The file format

FFHackster's map export, FFR's `.ffm` and this port all use one format: 256 x
256 bytes, one byte a tile, row by row, holding the game's tile numbers
(`$00-$7F`).  FFHackster's export of the vanilla map (`vanilla.ffm`, the
user's, 2026-11-15) matches the map decoded from the ROM in all 65,536 tiles
(`map-renders/roundtrip/rawmap.py compare`).  The file holds the tiles only:
the start, airship, bridge and canal positions, the exit teleports and the
ship's docks are tables in the ROM.  Entrances are in the tiles, since each
entrance has a separate tile number.

## 2. Tile properties

`lut_OWTileset`'s two bytes a tile (bank `$00`, `$8000`):

  - **Byte 0, low four bits: who may not enter.**  Bit 0 on foot, bit 1 the
    canoe, bit 2 the ship, bit 3 the airship landing.  Grass is `0110` (walk,
    land the airship); sea `1011` (ship only); rivers and lakes `1101`
    (canoe only); mountains, walls and most of a castle or town `1111`.  The
    airship lands on grass and nowhere else.
  - **Byte 0, high bits:** `$10` the forest battle backdrop (tiles `$04` and
    `$14` only), `$20` a dock, and `$40`/`$80`/`$C0` the CHIME tower, the
    caravan and the FLOATER's spot.
  - **Byte 1:** bit 7 an entrance, its id in bits 0-5; otherwise bit 6
    random encounters (off on `$76`, the grass round castles, and on town
    ground), and the low bits the battle backdrop.

## 3. Terrain and the neighbour rule

Every terrain tile belongs to one of seven families, and **which tile of the
family is drawn depends only on which of its four neighbours (N, E, S, W)
are the same terrain**.  Diagonal neighbours do not matter: the tileset has
no inside-corner pieces.  Re-tiling the vanilla map from its terrain alone,
each tile the commonest one for its pattern, reproduces it but for 384 of
65,536 tiles (99.4%); the 384 are hand touches, below.

| same-terrain neighbours | forest | sea | mountain | desert | marsh | plains | river |
|---|---|---|---|---|---|---|---|
| all four | `14` | `17` | `21` | `45` | `55` | `54` | `44` |
| open to N | `04` | `07` | `11` | `45` | `55` | `54` | `44` |
| open to S | `24` | `27` | `31` | `45` | `55` | `54` | `44` |
| open to W | `13` | `16` | `20` | `45` | `55` | `54` | `44` |
| open to E | `15` | `18` | `22` | `45` | `55` | `54` | `44` |
| open to N and W | `03` | `06` | `10` | `42` | `62` | `60` | `40` |
| open to N and E | `05` | `08` | `12` | `43` | `63` | `61` | `41` |
| open to S and W | `23` | `26` | `30` | `52` | `72` | `70` | `50` |
| open to S and E | `25` | `28` | `33` | `53` | `73` | `71` | `51` |

("Open" is a side whose neighbour is a different terrain.)  The commonest
tile covers, per family: forest 99.3%, sea 99.5%, mountain 99.6%, desert
99.1%, marsh 97.1%, plains 92.9% (it uses its corner tiles on straight edges
too, about a third of the time), river 99.6%.

Two kinds of family:

  - **Full sets: forest, sea and mountains.**  Four edge pieces, four corner
    pieces, a centre.  The corners are diagonal: the sea's `$06` is grass in
    its upper-left half and water in its lower-right, so a staircase of
    corner pieces makes a 45-degree coast or ridge.  The edges are the centre
    with a fringe on the open side.
  - **Round corners only: desert, marsh, plains and rivers.**  Four
    quarter-round corner pieces and a centre.  A straight side is the centre
    tile against its neighbour along the tile edge; only convex corners are
    rounded.  The four families lay out their corner pieces alike (`x0`/`x1`
    over `y0`/`y1`: `$40`, `$42`, `$60`, `$62` open to N and W, and so on).

**Different terrains may touch directly.**  Every edge and corner piece
draws a grass margin on its open side, so a forest edge beside a sea edge
reads as forest, a strip of grass, then sea.  In vanilla, forest meets sea
along 911 tile edges, mountain meets sea along 926, forest meets mountain
along 703, and mountain meets river along 993.

## 4. What the tiles cannot draw

The patterns the table lacks are the shapes to avoid.  For the full sets:

  - **A strip one tile wide** (open on two opposite sides): there is no
    piece for it.  Vanilla has 12 such sea tiles, in narrow straits and the
    canal, drawn with the centre tile; no forest or mountain.
  - **A spur one tile long** (open on three sides), and **a lone tile**:
    no piece.  Vanilla has two mountain tiles open on three sides.
  - **An inside corner**: the corner where a notch is cut into the
    terrain has no piece either, but none is needed -- the neighbour rule
    draws the edges either side of it, and they meet at a point.

So **forest, sea and mountains must be at least two tiles thick
everywhere**.  The round-corner families are looser: desert has ten lone
tiles and a few spurs, drawn with a corner piece.  **Rivers are one tile
wide by design**: a straight run is `$44`, and a bend takes the round corner
on its outside (a river coming from the west and turning south is `$41`).
Branches and ends are `$44`.

## 5. Structures

Entrances and other one-off tiles keep their place and art; the terrain
rules work around them.

  - **Caves** (`$0E`, `$2B`, `$2F`, `$32`, `$34`, `$35`, `$3A`) stand in a
    mountain's south edge: mountain to the north, east and west, open ground
    to the south.  The Waterfall (`$46`) is a river tile between mountains.
  - **Castles** are 2 x 2 or 3 x 2 blocks; the door is the bottom row's
    tile with an entrance id, open ground below it.
  - **Towns** are walled blocks (`$3B-$3F`, `$4B`, `$4F`, `$5B`, `$5F`,
    `$6B`, `$6F`, `$7B-$7F`) whose houses are entrances, several to a town.
  - **The Cardia caves** (`$66-$69`, `$6A`, `$6C`, `$6E`) are single holes
    set inside a terrain.
  - **Docks** (`$0F`, `$1F`, `$77-$79`) are sea-edge pieces the ship can
    berth at, walkable.
  - **Desert specials:** the caravan (`$36`) and the FLOATER's spot (`$37`)
    are desert tiles with a flag.

## 6. The hand touches

The 384 tiles the rule does not reproduce: corner pieces in place of edges
where a coast steps (`$26`, `$06`, `$08` for `$16`/`$18`, 49 tiles); the
plains and marsh using corner pieces on straight edges (54); docks among
the sea's edges (`$78` for `$07`); and a few dozen forest and sea tiles
swapped edge-for-centre along irregular shores.  None is needed for a map
to look right; they are the designer's variation.

## 7. What this gives the tooling

  - **An autotiler.**  A map is drawn as terrain -- one of grass, forest,
    sea, mountain, desert, marsh, plains, river, a byte a tile -- with the
    structures placed whole; the tiles follow from the table.  A picture
    becomes a map by reading each pixel's terrain from its colour.
  - **A checker.**  Every forest, sea or mountain tile open on two opposite
    sides or three is a shape the tiles cannot draw, and it can say where,
    and widen or trim it.  Structures are checked against their pattern: a
    cave with mountain on three sides and open ground below, and so on.
  - **Mirrors.**  The table is symmetric -- every family has both sides of
    each piece -- so a mirrored map is the terrain mirrored and re-tiled,
    with each structure moved whole and drawn as it was.  Left-right needs
    nothing more.  Top-bottom puts a cave's mouth on its mountain's north
    side, so caves move to the new south edge; castles and towns, moved
    whole, keep their doors at the bottom.
