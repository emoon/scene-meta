"""The area a production draws into (docs/DESIGN.md, ``area``), from what the
emulator's ``display measure`` counted of a run: in how many frames each
line and each column showed bitplanes, by the registers, apart for each
mode (a resolution, interlaced or not). A mode's part of the screen is the
lines and columns shown for LEAST frames or more: a title that fills the
screen for a few seconds before a smaller main part is of the area, as a
player that cuts to the area must show it whole. The area is the box around
the parts of every mode, in the pixels of the finest: a lores production
with a hires interlaced picture is 640x512.

What Kickstart's own copper list showed (AmigaDOS's hires window while the
production loads) is left out, unless nothing else was shown: a production
that draws through the system. So is what was shown for less than LEAST
frames, the frame in which a production takes the screen over.

Empty bitplanes count as shown and a picture the copper makes alone does
not, so what the run's pictures show drawn is measured the same way and
kept with the area.
"""

from .. import schema
from ..core.result import Area

# A mode counts when it was shown this many frames, and a line or column of
# it too: a second.
LEAST = 50
# A column or row is of what was drawn when this much of the pictures show it.
SHARE = 0.25
# A screenshot has this many pixels to a lores pixel, and rows to a line.
SCREEN_SCALE = 2
# The shape is that of the part of the screen, not of the pixel counts: a
# hires pixel is half as wide and an interlaced line half as high, so 320x180
# lores is the same 16:9 box as 640x180, 640x360 or 1280x180. No other part
# of a PAL screen has these sizes: it is 376 lores pixels by 287 lines at most.
ASPECTS = {(320 << res, 180 << lace): schema.ASPECT_16_9
           for res in (0, 1, 2) for lace in (0, 1)}


def _extent(runs, least):
    """``(from, to)`` over the stretches of ``runs`` (``[from, to, count]``,
    ``to`` not included) with a count of ``least`` or more; None with none."""
    kept = [(a, b) for a, b, n in runs if n >= least]
    return (min(a for a, _ in kept), max(b for _, b in kept)) if kept else None


def _box(cols, rows, least):
    """``((x0, x1), (y0, y1))`` around the columns and rows (see
    ``_extent``) counted ``least`` times or more: two parts at different
    places give the box around both. None with none."""
    cols, rows = (_extent(runs, least) for runs in (cols, rows))
    return (cols, rows) if cols and rows else None


def shown(display):
    """``((width, height), scale)`` of the area: the box around what every
    mode showed, in the pixels of the finest, ``scale`` of them to a lores
    pixel and to a line. The production's own modes when it had any. None
    when the run showed no bitplanes. ``display`` is the emulator's
    ``display status``."""
    modes = [m for m in display["modes"] if m["frames"] >= LEAST]
    modes = [m for m in modes if not m["os"]] or modes
    boxes = [(m, _box(m["cols"], m["rows"], LEAST)) for m in modes]
    boxes = [(m, box) for m, box in boxes if box]
    if not boxes:
        return None
    scale = (1 << max(m["res"] for m, _ in boxes),
             1 << max(m["lace"] for m, _ in boxes))
    size = (max(b[axis][1] for _, b in boxes)
            - min(b[axis][0] for _, b in boxes) for axis in (0, 1))
    return tuple(n * k for n, k in zip(size, scale)), scale


def _covered(spans):
    """``spans`` (``(from, to)``, ``to`` not included) as stretches ``[from,
    to, count]``: how many of them cover each."""
    edges = sorted({edge for span in spans for edge in span})
    return [[a, b, sum(lo <= a and b <= hi for lo, hi in spans)]
            for a, b in zip(edges, edges[1:])]


def drawn(boxes, scale):
    """``(width, height)`` of what the pictures of a run show drawn, in
    pixels at ``scale`` of them to a lores pixel and to a line: the columns
    and rows inside the box of SHARE of the pictures or more. ``boxes``:
    ``[x0, y0, x1, y1]`` of each picture that shows something, in its own
    pixels. ``(0, 0)`` with none."""
    box = _box(_covered([(b[0], b[2]) for b in boxes]),
               _covered([(b[1], b[3]) for b in boxes]),
               len(boxes) * SHARE)
    if not box:
        return 0, 0
    return tuple(round((hi - lo) * k / SCREEN_SCALE)
                 for (lo, hi), k in zip(box, scale))


def measured(log):
    """The Area of the run of ``log``, an emulator.RunLog; None when it was
    not measured or showed no bitplanes."""
    found = shown(log.display) if log.display else None
    if not found:
        return None
    size, scale = found
    return Area(*size, *drawn([b for b in log.boxes if b], scale))


def fields(area):
    """What an entry says of ``area``."""
    size = (area.width, area.height)
    out = {"area": list(size)}
    if size in ASPECTS:
        out["aspect"] = ASPECTS[size]
    return out
