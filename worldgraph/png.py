"""png.py -- a minimal RGB image with PNG output and the game's own font."""
import struct
import zlib

import romdata as rd

_FONT = rd.nesbank(9)[0x0800:0x1000]       # menu font, codes $80-$FF


class Image:
    def __init__(self, w, h, fill=(0, 0, 0)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(fill) * (w * h))

    def put(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 3
            self.px[o:o + 3] = bytes(c)

    def rect(self, x0, y0, w, h, c):
        row = bytes(c) * w
        for y in range(max(0, y0), min(self.h, y0 + h)):
            x1 = max(0, x0)
            n = min(self.w, x0 + w) - x1
            if n > 0:
                o = (y * self.w + x1) * 3
                self.px[o:o + n * 3] = row[:n * 3]

    def save(self, path):
        stride = self.w * 3
        raw = b"".join(b"\x00" + bytes(self.px[y * stride:(y + 1) * stride])
                       for y in range(self.h))

        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)))
            f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
            f.write(chunk(b"IEND", b""))


def _code(ch):
    if "0" <= ch <= "9":
        return 0x80 + ord(ch) - 48
    if "A" <= ch <= "Z":
        return 0x8A + ord(ch) - 65
    if "a" <= ch <= "z":
        return 0xA4 + ord(ch) - 97
    return None


def text(img, x0, y0, s, colour=(255, 255, 255), outline=(0, 0, 0)):
    ink = set()
    for i, ch in enumerate(s):
        c = _code(ch)
        if c is None:
            continue
        g = _FONT[(c - 0x80) * 16:(c - 0x80) * 16 + 8]
        for y in range(8):
            for x in range(8):
                if (g[y] >> (7 - x)) & 1:
                    ink.add((i * 8 + x, y))
    for x, y in ink:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (x + dx, y + dy) not in ink:
                    img.put(x0 + x + dx, y0 + y + dy, outline)
    for x, y in ink:
        img.put(x0 + x, y0 + y, colour)
