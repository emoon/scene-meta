"""Measure visible color-register output without bitplane or sprite DMA."""

import collections
import struct
import zlib

from .png import rows


def multicolor(png):
    """At least two bright colors cover a visible part of the raster.

    Sample every interior scanline, ignoring the capture border, so a
    one-line effect is not missed. Color-register effects need no bitplanes
    or sprites; uniform blank frames are not evidence of those effects. This is a measurement, not a verdict.
    """
    colors = collections.Counter()
    try:
        decoded = rows(png)
        height = next(decoded)
        for y, row in enumerate(decoded):
            if y < 24 or y >= height - 24:
                continue
            for x in range(24 * 3, len(row) - 24 * 3, 8 * 3):
                rgb = tuple(row[x:x + 3])
                if max(rgb) >= 128:
                    colors[rgb] += 1
            if sum(n >= 8 for n in colors.values()) >= 2:
                return True
    except (ValueError, TypeError, struct.error, zlib.error, StopIteration):
        return False
    return False
