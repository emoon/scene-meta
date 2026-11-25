"""Is a screenshot a Guru Meditation, or the "Software error - task held"
requester?

exec's alert box is red text on black in the top band of the screen, and it
blinks: the screen changes every second or so with bitplanes on, which the
verdict would otherwise count as a demo playing. LastAlert is no help on
Kickstart 1.x (it stays -1 for a "Software Failure"), so the picture is the
only evidence.

Kickstart 1.x shows a recoverable alert above the screen it found, pushed
down: the AmigaDOS window is still there. A demo's own picture can be red on
black in the same place, so that box is known by its words, "Guru
Meditation #", matched against a template mask. So is the alert it shows
there for a task that crashed, "Software error - task held".

Kickstart 1.x's "Software error - task held" requester (Intuition's
AutoRequest for a task that crashed) leaves LastAlert at -1 as well. It is
a fixed window in the top-left corner whatever the palette, so its three
lines of text are matched against a template mask.
"""

import collections
import itertools
import struct
import zlib

BAND = 0.25       # the alert sits in the top quarter of the screen
MIN_PIXELS = 150  # fewer lit pixels than a line of text is not an alert
LIT = 60          # r+g+b above this is not black


def _rows(png):
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


GURU_BOX = (216, 86, 352, 100)  # x0, y0, x1, y1 around "Guru Meditation #"
ALERT_MATCH = 0.8               # share of the template's ink the screen must reproduce
# One row per line of the words as they are above a screen (a box with
# nothing beneath is drawn wider), one bit per pixel, 1 = ink.
GURU_MASK = tuple(int(row, 16) for row in (
    "0f0000000020800386020002060000001b",
    "0f0000000020800386020002060000001b",
    "198000000031800180060006000000001b",
    "198000000031800180060006000000001b",
    "3019bb19803b8f0d8e0f8f0f8e0f1f003f",
    "3019bb19803b8f0d8e0f8f0f8e0f1f003f",
    "33999d99803f999b86060186061999801b",
    "33999d99803f999b86060186061999801b",
    "3199999980359f9986060786061999803f",
    "3199999980359f9986060786061999803f",
    "199998198031981986069986861999801b",
    "199998198031981986069986861999801b",
    "0f8efc0ec0318f0ecf030ec30f0f19801b",
    "0f8efc0ec0318f0ecf030ec30f0f19801b",
))

# Kickstart 1.x's other alert above a screen, for a task that crashed: its
# first line, "Software error - task held".
HELD_ALERT_BOX = (88, 48, 304, 62)
HELD_ALERT_MASK = tuple(int(row, 16) for row in (
    "07800381000000000000000000000000000100001c001c000701c0",
    "07800381000000000000000000000000000100001c001c000701c0",
    "0cc006c3000000000000000000000000000300000c000c000300c0",
    "0cc006c3000000000000000000000000000300000c000c000300c0",
    "0e078607cc679d8780079d9d879d80000007c787ccc00d878306c0",
    "0e078607cc679d8780079d9d879d80000007c787ccc00d878306c0",
    "070ccf030d60ceccc00ccececccec00fc00300cc0d800eccc30dc0",
    "070ccf030d60ceccc00ccececccec00fc00300cc0d800eccc30dc0",
    "01ccc6030d63cccfc00fccccccccc000000303c78f000ccfc30cc0",
    "01ccc6030d63cccfc00fccccccccc000000303c78f000ccfc30cc0",
    "0cccc60346cccc0c000c0c0c0ccc000000034cc0cd800ccc030cc0",
    "0cccc60346cccc0c000c0c0c0ccc000000034cc0cd800ccc030cc0",
    "07878f0186c77e0780079e1e079e00000001876f9cc01cc7878760",
    "07878f0186c77e0780079e1e079e00000001876f9cc01cc7878760",
))

HELD_BOX = (90, 66, 384, 134)  # x0, y0, x1, y1 around the requester's text
HELD_MATCH = 0.8               # share of the template's ink the screen must reproduce
HELD_INK = 400                 # luminance (3r+6g+b) distance from the box's background
# One row per line of the box, one bit per pixel, 1 = ink ("Software error -
# task held / Finish ALL disk activity / Select CANCEL to reset/debug" and
# the Retry and Cancel gadgets).
HELD_MASK = tuple(int(row, 16) for row in (
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "003e0001e0200000000000000000000000000000000002000000e0000e00003803800001bf",
    "003e0001e0200000000000000000000000000000000002000000e0000e00003803800001bf",
    "006300033060000000000000000000000000000000000600000060000600001801800001bf",
    "006300033060000000000000000000000000000000000600000060000600001801800001bf",
    "00700f8300f8c31f0ee0f8000f8ee3b83e3b800000000f87c0fc630006e0f8181d800001bf",
    "00700f8300f8c31f0ee0f8000f8ee3b83e3b800000000f87c0fc630006e0f8181d800001bf",
    "001c18c78060db0187318c0018c731cc631cc003fc0006006180660007318c1833800001bf",
    "001c18c78060db0187318c0018c731cc631cc003fc0006006180660007318c1833800001bf",
    "000718c30060db0f8631fc001fc6318c6318c00000000603e0f87c000631fc1831800001bf",
    "000718c30060db0f8631fc001fc6318c6318c00000000603e0f87c000631fc1831800001bf",
    "006318c3006466318601800018060180631800000000064c600c66000631801831800001bf",
    "006318c3006466318601800018060180631800000000064c600c66000631801831800001bf",
    "003e0f878038661ecf00f8000f8f03c03e3c000000000387b1f8e3000e30f83c1ec00001bf",
    "003e0f878038661ecf00f8000f8f03c03e3c000000000387b1f8e3000e30f83c1ec00001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "00003fc1800018000e0000183e0f80000e06000380000000002018000180200000000001bf",
    "00003fc1800018000e0000183e0f80000e06000380000000002018000180200000000001bf",
    "000018c0000000000600003c180600000600000180000000006000000000600000000001bf",
    "000018c0000000000600003c180600000600000180000000006000000000600000000001bf",
    "0000180381f8380fc6e0003c18060000760e03f18c001f03e0f83830c380f8c300000001bf",
    "0000180381f8380fc6e0003c18060000760e03f18c001f03e0f83830c380f8c300000001bf",
    "00001f01818c18180730006618060000ce0606019800018630601830c18060c300000001bf",
    "00001f01818c18180730006618060000ce0606019800018630601830c18060c300000001bf",
    "00001801818c180f8630007e18461000c60603e1f0000f86006018198180606600000001bf",
    "00001801818c180f8630007e18461000c60603e1f0000f86006018198180606600000001bf",
    "00001801818c1800c63000c318c63000c6060031980031863064180f0180643c00000001bf",
    "00001801818c1800c63000c318c63000c6060031980031863064180f0180643c00000001bf",
    "00003e03c18c3c1f8e3000c33fcff0007b0f07e38c001ec3e0383c0603c0381800000001bf",
    "00003e03c18c3c1f8e3000c33fcff0007b0f07e38c001ec3e0383c0603c0381800000001bf",
    "000000000000000000000000000000000000000000000000000000000000007000000001bf",
    "000000000000000000000000000000000000000000000000000000000000007000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "003e0003800000020000f81830c3e3fcf800008000000000000000020030380038000001bf",
    "003e0003800000020000f81830c3e3fcf800008000000000000000020030380038000001bf",
    "006300018000000600018c3c38c6318c6000018000000000000000060060180018000001bf",
    "006300018000000600018c3c38c6318c6000018000000000000000060060180018000001bf",
    "00700f8180f83e0f8003003c3ccc0180600003e0f8003b83e0fc3e0f80c1d83e1b8c61edbf",
    "00700f8180f83e0f8003003c3ccc0180600003e0f8003b83e0fc3e0f80c1d83e1b8c61edbf",
    "001c18c1818c63060003006636cc01f0600001818c001cc631806306018338631ccc6319bf",
    "001c18c1818c63060003006636cc01f0600001818c001cc631806306018338631ccc6319bf",
    "00071fc181fc60060003007e33cc0180610001818c0018c7f0f87f060303187f18cc6319bf",
    "00071fc181fc60060003007e33cc0180610001818c0018c7f0f87f060303187f18cc6319bf",
    "006318018180630640018cc331c6318c630001918c001806000c60064603186018cc61f1bf",
    "006318018180630640018cc331c6318c630001918c001806000c60064603186018cc61f1bf",
    "003e0f83c0f83e038000f8c330c3e3fcff0000e0f8003c03e1f83e038c01ec3e0f87b019bf",
    "003e0f83c0f83e038000f8c330c3e3fcff0000e0f8003c03e1f83e038c01ec3e0f87b019bf",
    "0000000000000000000000000000000000000000000000000000000000000000000003f1bf",
    "0000000000000000000000000000000000000000000000000000000000000000000003f1bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
    "000000000000000000000000000000000000000000000000000000000000000000000001bf",
))


def _lum(pixel):
    return 3 * pixel[0] + 6 * pixel[1] + pixel[2]


def _alert_red(r, g, b):
    return r > 150 and g < 90 and b < 60


def _crop(rows, area):
    """The pixels of ``area`` (x0, y0, x1, y1), a list per row; None when
    the screen is too small to hold it."""
    x0, y0, x1, y1 = area
    if len(rows) < y1 or len(rows[0]) < 3 * x1:
        return None
    return [[tuple(row[3 * x:3 * x + 3]) for x in range(x0, x1)]
            for row in rows[y0:y1]]


def _reads(crop, mask, ink, match):
    """True when the ink of ``crop`` is the template ``mask``'s: ``ink(px)``
    says which of its pixels are."""
    both = either = 0
    for pixels, want in zip(crop, mask):
        bits = 0
        for px in pixels:
            bits = bits << 1 | ink(px)
        both += (bits & want).bit_count()
        either += (bits | want).bit_count()
    return both >= match * either


def _task_held(rows):
    """True when the requester's text is on screen. The box's background is
    the commonest colour in the crop; ink is whatever differs from it."""
    crop = _crop(rows, HELD_BOX)
    if not crop:
        return False
    background = _lum(collections.Counter(
        itertools.chain.from_iterable(crop)).most_common(1)[0][0])
    return _reads(crop, HELD_MASK,
                  lambda px: abs(_lum(px) - background) > HELD_INK, HELD_MATCH)


def _says(rows, area, mask):
    """True when an alert's words, the template ``mask``, are in ``area``:
    where exec writes them above a screen."""
    crop = _crop(rows, area)
    return bool(crop) and _reads(crop, mask, lambda px: _alert_red(*px),
                                 ALERT_MATCH)


def _is_guru(rows, height):
    """True when everything lit in the top half of the screen is alert-red
    and sits in the top band."""
    lit = red = 0
    for y, row in enumerate(rows):
        for r, g, b in zip(row[0::3], row[1::3], row[2::3]):
            if r + g + b > LIT:
                if y >= BAND * height:
                    return False
                lit += 1
                red += _alert_red(r, g, b)
    return lit >= MIN_PIXELS and red >= 0.97 * lit


def box(png):
    """Which alert box the screenshot shows: "guru", "task-held" or "" for
    none. A png it cannot read shows none. Only the top half is decoded: it
    is all either box needs, and the check runs on every sample of a run."""
    try:
        decoded = _rows(png)
        height = next(decoded)
        rows = list(itertools.islice(decoded, height // 2))
    except (ValueError, zlib.error, struct.error, StopIteration):
        return ""
    if _is_guru(rows, height) or _says(rows, GURU_BOX, GURU_MASK):
        return "guru"
    held = _task_held(rows) or _says(rows, HELD_ALERT_BOX, HELD_ALERT_MASK)
    return "task-held" if held else ""
