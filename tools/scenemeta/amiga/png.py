"""Decode the emulator's RGB screenshots for visual measurements."""

import struct
import zlib


def rows(png):
    """The height of an 8-bit RGB non-interlaced PNG, then its unfiltered
    rows."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr = 8, [], None
    while pos < len(png):
        n, kind = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + n
    w, h, depth, color, _, _, interlace = ihdr
    if (depth, color, interlace) != (8, 2, 0):
        raise ValueError("only 8-bit RGB PNGs")
    yield h
    stride = w * 3
    data = zlib.decompressobj().decompress(b"".join(idat))
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        ft, row = data[base], bytearray(data[base + 1:base + 1 + stride])
        for x in range(stride):
            a = row[x - 3] if x >= 3 else 0
            b, c = prev[x], (prev[x - 3] if x >= 3 else 0)
            if ft == 1:
                row[x] = (row[x] + a) & 255
            elif ft == 2:
                row[x] = (row[x] + b) & 255
            elif ft == 3:
                row[x] = (row[x] + (a + b) // 2) & 255
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else b if pb <= pc else c
                row[x] = (row[x] + pr) & 255
        yield row
        prev = row
