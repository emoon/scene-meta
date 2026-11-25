#!/usr/bin/env python3
"""PROTOTYPE (throwaway): does the picture loop? Each cell of the screen grid
is tested for its own period, so two effects with unrelated periods (a
scroller over a bob object) still count as a loop.

    python3 amiga/proto-end-detect/video.py TRACE.csv
"""
import bisect, csv, sys

import numpy as np

FPS = 50
WINDOW = 1000     # frames a period is first looked for in, and judged over
STILL_TAIL = 1500 # frames of stillness at the end that make a cell still
TOL = 0.02        # share of a cell's changes allowed to differ one period on
NOISY = 0.9       # share of changes to a never-seen value: fresh every time
MIN_LANDMARK = 1500   # frames: a shorter landmark period may be a slide show
LANDMARK_RUN = 5  # frames a picture must stay to make a landmark


def load_cells(path):
    """The screen-cell hashes of a trace: array [frame, cell]."""
    with open(path) as f:
        r = csv.reader(f)
        at = next(r).index("v0")
        return np.array([[int(x, 16) for x in row[at:]] for row in r], dtype=np.uint64)


def candidates(a, changes, end):
    """Periods worth testing, shortest first: the lags at which the WINDOW
    frames up to ``end`` match what was shown that long before."""
    past = np.lib.stride_tricks.sliding_window_view(a[:end - 2], WINDOW)
    miss = (past != a[end - WINDOW:end]).sum(axis=1)
    ok = miss <= TOL * changes[end - WINDOW:end].sum()
    return sorted(int(end - WINDOW - j) for j in np.nonzero(ok)[0])


def repeats_from(a, changes, p):
    """First frame from which ``a`` replays what it showed ``p`` frames
    before, to the end. Only frames where it changes (now or a period ago)
    count, so a cell that mostly rests does not match at any lag."""
    event = changes[p:] | changes[:-p]
    bad = event & (a[p:] != a[:-p])
    # Absorb +-1 frame period drift on non-trivial loops (e.g. fractional-frame
    # CIA/VBlank cadences like 5539/5540 in 89549 or 1168/1169 in 24435).
    if p >= 100 and len(bad) > 2:
        bad[:-1] &= (a[p:-1] != a[1:-p])
        bad[1:] &= (a[p + 1:] != a[:-p - 1])

    def ahead(x):   # per frame, over the WINDOW frames from it on
        total = np.concatenate(([0], np.cumsum(x), np.full(WINDOW, x.sum())))
        return total[WINDOW:WINDOW + len(x)] - total[:len(x)]
    ev_w = ahead(event)
    # In sparse cells (few changes per 20 s window), tolerate 1-2 stray
    # single-frame jitter glitches while still failing genuine mismatches.
    allow = np.maximum(np.minimum(2, (ev_w + 1) // 3), TOL * ev_w)
    fails = np.nonzero(ahead(bad) > allow)[0]
    return p + (int(fails[-1]) + 1 if len(fails) else 0)


def cell_period(a, t0):
    """What one cell does from ``t0`` to the end of the trace: ``(kind,
    period, shown)``. ``shown`` is the frame by which it has shown all it
    will: where it went still, or where the second pass of its loop began
    (a loop counts when at least WINDOW frames of its second pass run to
    the end of the trace)."""
    n = len(a)
    changes = np.zeros(n, dtype=bool)
    changes[1:] = a[1:] != a[:-1]
    at = np.nonzero(changes)[0]
    last = int(at[-1]) if len(at) else 0
    if last < t0:
        return "still", 1, last + 1
    # Check if the cell stopped moving for STILL_TAIL frames at the end,
    # unless it's a slow slideshow whose own inter-slide gap is comparable.
    if last < n - STILL_TAIL:
        gaps = np.diff(at)
        big = gaps[gaps >= 250]
        slow_gap = int(big[-4:].max()) if len(big) else 0
        if n - last >= max(STILL_TAIL, int(1.5 * slow_gap)):
            return "still", 1, last + 1
    if last + 1 >= WINDOW + 2:
        for p in candidates(a, changes, last + 1):
            shown = repeats_from(a, changes, p)
            max_shown = max(t0, n - max(3000, p // 3))
            if shown <= max_shown:
                return "loop", p, shown
    tail = at[at >= t0]
    if not len(tail):
        return "still", 1, last + 1
    _, first = np.unique(a, return_index=True)
    return ("noisy" if np.isin(tail, first).mean() >= NOISY else "open"), 0, 0


def cell_periods(cells, t0):
    """``cell_period`` of every cell, judged on the frames from ``t0``."""
    return [cell_period(cells[:, c].copy(), t0) for c in range(cells.shape[1])]


def chain_period(events, start, n, min_period):
    """Smallest period of a chain of events that runs to the end of the
    trace: three or more, each one period after the one before, the first
    within a period of ``start``, and half of all the events from there on
    (the rest are strays)."""
    ev = sorted(events)
    if len(ev) < 3 or len(ev) > 400:
        return 0
    periods = sorted({b - a for a in ev for b in ev if b - a >= min_period})
    for p in periods:
        tol = max(8, p // 500)
        # Only events within (p + tol) of n can be the last in a chain running to n
        i_min = bisect.bisect_left(ev, n - p - tol)
        for last in ev[i_min:]:
            chain = [last]
            while True:
                target = chain[-1] - p
                j = bisect.bisect_left(ev, target - tol)
                if j < len(ev) and ev[j] <= target + tol:
                    chain.append(ev[j])
                else:
                    break
            if len(chain) >= 3 and chain[-1] <= start + p:
                later = len(ev) - bisect.bisect_left(ev, chain[-1])
                if 2 * len(chain) >= later:
                    return p
    return 0


def onsets(flag, min_run=1):
    """Frames where a run of at least ``min_run`` set flags begins."""
    f = np.concatenate(([False], flag, [False]))
    d = np.diff(f.astype(np.int8))
    up, down = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return [int(u) for u, e in zip(up, down) if e - u >= min_run]


def landmark(cells, kinds, start):
    """Period at which the cells no loop explains return together to their
    commonest picture (a scroller's gap, a black frame between pages)."""
    idx = [c for c, k in enumerate(kinds) if k[0] in ("noisy", "open")]
    if not idx or start >= len(cells):
        return 0
    mul = np.arange(1, 2 * len(idx), 2, dtype=np.uint64) * np.uint64(0x9e3779b97f4a7c15)
    key = (cells[:, idx] * mul).sum(axis=1)
    vals, counts = np.unique(key[start:], return_counts=True)
    at = onsets(key == vals[counts.argmax()], LANDMARK_RUN)
    return chain_period(at, start, len(cells), MIN_LANDMARK)


if __name__ == "__main__":
    cells = load_cells(sys.argv[1])
    t0 = int(sys.argv[2]) if len(sys.argv) > 2 else len(cells) // 2
    kinds = cell_periods(cells, t0)
    for c, (kind, p, shown) in enumerate(kinds):
        print(f"v{c:<2d} {kind:5s} period {p:6d}  shown by {shown / FPS:6.1f}s")
    print("landmark period:", landmark(cells, kinds, t0))
