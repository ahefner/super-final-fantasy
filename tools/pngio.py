"""pngio.py -- PNGs read and written with zlib alone (no PIL here), for art
kept in art/ and retouched by hand.

png_read reads what an editor saves: 8-bit grey, grey with alpha, RGB,
RGBA, and palette (1-8 bits, with tRNS), not interlaced.  Each pixel comes
back as (r, g, b, a), a 255 where the file has no alpha; and for a palette
PNG the indices too, so art kept indexed is read by index.
"""
import os, struct, sys, zlib


def _chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def png_write_indexed(path, idx, pal):
    """idx: rows of palette indices; pal: (r, g, b) each."""
    h, w = len(idx), len(idx[0])
    raw = b"".join(b"\0" + bytes(row) for row in idx)
    data = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)) +
            _chunk(b"PLTE", bytes(c for rgb in pal for c in rgb)) +
            _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def png_read(path):
    """-> (w, h, rows of (r, g, b, a), rows of palette indices or None)."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit("%s: not a PNG" % path)
    at, idat, plte, trns = 8, b"", None, b""
    while at < len(d):
        n, = struct.unpack(">I", d[at:at + 4])
        t, body = d[at + 4:at + 8], d[at + 8:at + 8 + n]
        at += 12 + n
        if t == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
        elif t == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif t == b"tRNS":
            trns = body
        elif t == b"IDAT":
            idat += body
    if inter:
        sys.exit("%s: interlaced PNGs are not read; save it without" % path)
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    if ctype != 3 and depth != 8:
        sys.exit("%s: %d-bit channels are not read; save it as 8-bit" % (path, depth))
    bpp = max(1, chans * depth // 8)
    stride = (w * chans * depth + 7) // 8
    raw = zlib.decompress(idat)
    rows, prev, p = [], bytearray(stride), 0
    indices = [] if ctype == 3 else None
    for _ in range(h):
        f, line = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        if ctype == 3:
            per = 8 // depth
            idx = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(w)]
            rows.append([plte[i] + ((trns[i] if i < len(trns) else 255),) for i in idx])
            indices.append(idx)
        elif chans >= 3:
            rows.append([tuple(line[x * chans:x * chans + 3]) +
                         ((line[x * chans + 3],) if chans == 4 else (255,)) for x in range(w)])
        else:
            rows.append([(line[x * chans],) * 3 + ((line[x * chans + 1],) if chans == 2 else (255,))
                         for x in range(w)])
    return w, h, rows, indices
