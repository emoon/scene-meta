"""The area a production draws into (docs/DESIGN.md, ``area``), from what the
emulator's ``display measure`` counted of a run: in how many frames each
line and each column showed bitplanes, by the registers. The area is those
shown in SHARE of the frames or more, in lores pixels and lines.

Empty bitplanes count as shown and a picture the copper makes alone does
not, so what the run's pictures show drawn is measured the same way and
kept with the area.
"""

from .. import schema
from ..core.result import Area

# A line or column is of the area when this much of the run showed it.
SHARE = 0.25
# A screenshot has this many pixels to a lores pixel, and rows to a line.
SCREEN_SCALE = 2
ASPECTS = {(320, 180): schema.ASPECT_16_9}


def _extent(runs, least):
    """``(from, to)`` over the stretches of ``runs`` (``[from, to, count]``,
    ``to`` not included) with a count of ``least`` or more; None with none."""
    kept = [(a, b) for a, b, n in runs if n >= least]
    return (min(a for a, _ in kept), max(b for _, b in kept)) if kept else None


def _size(cols, rows, of):
    """``(width, height)`` of the columns and rows (see ``_extent``) counted
    in SHARE of ``of`` or more, from the first to the last of them: two
    parts at different places give the box around both. None with none."""
    if not of:
        return None
    cols, rows = (_extent(runs, of * SHARE) for runs in (cols, rows))
    if not cols or not rows:
        return None
    return cols[1] - cols[0], rows[1] - rows[0]


def shown(display):
    """``(width, height)`` of the area by the registers; None when the run
    showed no bitplanes. ``display`` is the emulator's ``display status``."""
    return _size(display["cols"], display["rows"], display["frames"])


def _covered(spans):
    """``spans`` (``(from, to)``, ``to`` not included) as stretches ``[from,
    to, count]``: how many of them cover each."""
    edges = sorted({edge for span in spans for edge in span})
    return [[a, b, sum(lo <= a and b <= hi for lo, hi in spans)]
            for a, b in zip(edges, edges[1:])]


def drawn(boxes):
    """``(width, height)`` of what the pictures of a run show drawn: the
    columns and rows inside the box of SHARE of the pictures or more.
    ``boxes``: ``[x0, y0, x1, y1]`` of each picture that shows something,
    in its own pixels. ``(0, 0)`` with none."""
    size = _size(_covered([(b[0], b[2]) for b in boxes]),
                 _covered([(b[1], b[3]) for b in boxes]), len(boxes))
    return tuple(round(n / SCREEN_SCALE) for n in size or (0, 0))


def measured(log):
    """The Area of the run of ``log``, an emulator.RunLog; None when it was
    not measured or showed no bitplanes."""
    size = shown(log.display) if log.display else None
    return Area(*size, *drawn([b for b in log.boxes if b])) if size else None


def fields(area):
    """What an entry says of ``area``."""
    size = (area.width, area.height)
    out = {"area": list(size)}
    if size in ASPECTS:
        out["aspect"] = ASPECTS[size]
    return out
