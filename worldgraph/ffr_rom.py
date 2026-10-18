"""
ffr_rom.py -- read a ROM FFR generated back into the graph's inputs, to set
FFR's own shuffles beside the port's (run_ffr_fe.py).

  wiring(path)     its three teleport tables as a wiring.Wiring.  Normal
                   teleports are wherever FFR left them: the vanilla $2D00
                   tables, or $3F000 once FFR expanded them (it does for its
                   in-room patch); the X byte's high bit is FFR's in-room flag.
  overworld(path)  its overworld tiles, decoded as the game decodes them, or
                   None if FFR moved the map out of bank $01.

Offsets are into the iNES file's PRG, after the 16-byte header.
"""
import romdata as rd
from wiring import Wiring

HDR = 16


def _prg(path):
    return open(path, "rb").read()[HDR:]


def wiring(path):
    p = _prg(path)
    ent = {e: (p[0x2C40 + e], p[0x2C00 + e] & 0x3F, p[0x2C20 + e] & 0x3F) for e in range(32)}
    #  FFR expands every ROM it writes to 512KB and moves the normal teleports
    #  to $3F000 (GlobalHacks -> ExpandNormalTeleporters); in a 256KB ROM that
    #  offset is the fixed bank's code.
    base = 0x3F000 if len(p) >= 0x80000 else 0x2D00
    step = 0x100 if base == 0x3F000 else 0x40
    norm = {t: (p[base + 2 * step + t], p[base + t] & 0x3F, p[base + step + t] & 0x3F) for t in range(64)}
    exits = {x: (p[0x2C60 + x], p[0x2C70 + x]) for x in range(16)}
    w = Wiring(ent, norm, exits)
    w.expanded = base == 0x3F000
    return w


def overworld(path):
    p = _prg(path)
    b1 = p[0x4000:0x8000]
    try:
        tiles = []
        for r in range(256):
            ptr = b1[r * 2] | (b1[r * 2 + 1] << 8)
            tiles += rd.decode_rle(b1, ptr - 0x8000, 256)
        return bytes(tiles)
    except (ValueError, IndexError):
        return None
