#!/usr/bin/env python3
"""PROTOTYPE (throwaway): does the song loop? Matches the note events (Paula
pointer and period writes, in order) of each channel, not frames.

    python3 amiga/proto-end-detect/notes.py TRACE.csv.notes
"""
import bisect, collections, sys

K = 16        # consecutive events of one channel that make a run to match
FPS = 50
BIN = 10      # frames: candidate periods are counted in bins this wide
MIN_PERIOD = 250
TAIL = 3000    # frames at the end of the trace the loop is looked for in
BEND = 0.03    # share a period may move from the last note's and not be a note
QUIET_TAIL = 500  # frames: if last note is older than this before trace_end, music stopped
MAX_LAG_SAMPLES = 64  # cap backward occurrences per event to keep histogram O(N)


def channel(ev):
    """ev: [(frame, key)] of one channel -> (frames, keys, where) with ``where``
    mapping each run of K events to the sorted frames it ended at."""
    frames = [f for f, _ in ev]
    h = [hash(k) for _, k in ev]
    keys = [None] * len(ev)
    where = collections.defaultdict(list)
    for i in range(K - 1, len(ev)):
        keys[i] = hash(tuple(h[i - K + 1:i + 1]))
        where[keys[i]].append(frames[i])
    return frames, keys, where


def _has_match(occ, target, tol):
    """Is any sorted frame in ``occ`` within ``tol`` of ``target``? O(log n)."""
    j = bisect.bisect_left(occ, target - tol)
    return j < len(occ) and occ[j] <= target + tol


def song_loop(path, log=lambda *a: None, trace_end=None):
    """``(period, second_pass_from)`` in frames, or None.

    When ``trace_end`` is given, only notes before ``trace_end`` are
    considered, and if no note occurred within QUIET_TAIL frames of
    ``trace_end``, returns None (music stopped before trace_end).
    """
    chans, cur = collections.defaultdict(list), {}
    with open(path) as fh:
        for line in fh:
            parts = line.rstrip().split(",")
            if len(parts) != 4:
                continue
            f_s, ch, reg, v = parts
            try:
                f_i = int(f_s)
            except ValueError:
                continue
            if trace_end is not None and f_i >= trace_end:
                break
            # A length write is not a note: The Chaos Engine's player writes
            # lengths that differ from one pass of the song to the next.
            if reg == "3":
                continue
            # A period within a quarter tone of the last note's is not a note:
            # the value it has written again (Desert Dream's player rewrites
            # all four every frame), or a vibrato, which need not keep step
            # with the song (Assemblers of Infinity 3).
            if reg == "2":
                try:
                    per = int(v, 16)
                except ValueError:
                    continue
                if abs(per - cur.get(ch, 0)) <= BEND * per:
                    continue
                cur[ch] = per
            chans[ch].append((f_i, (reg, v)))
    data = {ch: channel(ev) for ch, ev in sorted(chans.items()) if len(ev) >= K}
    if not data:
        return None
    end = max(fr[-1] for fr, _, _ in data.values())
    if trace_end is not None and end < trace_end - QUIET_TAIL:
        log(f"last note at {end / FPS:.1f}s, trace ended at {trace_end / FPS:.1f}s: music stopped")
        return None
    log(f"{sum(len(d[0]) for d in data.values())} events, to {end / FPS:.0f}s")
    t0 = end - TAIL
    hist = collections.Counter()
    for fr, keys, where in data.values():
        i0 = bisect.bisect_left(fr, t0)
        for i in range(max(K - 1, i0), len(fr)):
            occ = where[keys[i]]
            hi = bisect.bisect_right(occ, fr[i] - MIN_PERIOD)
            if hi == 0:
                continue
            lo = max(0, hi - MAX_LAG_SAMPLES)
            w = 1.0 / len(occ)
            for f in occ[lo:hi]:
                hist[(fr[i] - f) // BIN] += w
    def _score_period(p, tol_override=None):
        tol = tol_override if tol_override is not None else max(BIN, p // 100)
        shares = []
        for fr, keys, where in data.values():
            i0 = max(K - 1, bisect.bisect_left(fr, t0))
            n_idx = len(fr) - i0
            if n_idx <= 20:
                shares.append(None)
                continue
            hit = sum(_has_match(where[keys[i]], fr[i] - p, tol)
                      for i in range(i0, len(fr)))
            shares.append(hit / n_idx)
        live = [s for s in shares if s is not None]
        return (round(min(live), 2) if live else 0), shares

    best, passed = None, []
    # Break vote ties in favour of shorter lags so harmonics cannot crowd out
    # the fundamental period.
    top = sorted(hist.items(), key=lambda kv: (-round(kv[1], 4), kv[0]))[:40]
    for b, _ in top:
        p = b * BIN + BIN // 2
        score, shares = _score_period(p)
        txt = " ".join("  - " if s is None else f"{s:4.0%}" for s in shares)
        log(f"  candidate {p / FPS:6.1f}s: per channel {txt}")
        if score >= 0.8:
            passed.append((-score, p))
            if best is None or (-score, p) < best:
                best = (-score, p)
    best_score = -best[0] if best else 0
    best = best and best[1]
    if best:
        # Reject degenerate constant register streams (e.g. a software mixer
        # rewriting the same DMA buffer pointer every frame), which match at
        # every arbitrary lag including non-harmonics (+1s, +2s).
        if (_score_period(best + 50, tol_override=BIN)[0] >= 0.8
                and _score_period(best + 100, tol_override=BIN)[0] >= 0.8):
            log("degenerate constant Paula register stream; ignoring")
            return None
        # A multiple of the period matches as well or better (its tolerance
        # is wider): take the passing period the best is the highest multiple
        # of, and also test integer divisors directly in case the fundamental
        # was crowded out of the top-40 histogram bins. Require a divisor to
        # match nearly as well as best so a chorus/verse doesn't chop a song.
        tol = max(BIN, best // 100)
        subs = [(-round(best / p), s, p) for s, p in passed
                if abs(best - round(best / p) * p) <= tol and -s >= best_score - 0.03]
        if subs:
            best = min(subs)[2]
            best_score = _score_period(best)[0]
        for k in range(best // MIN_PERIOD, 1, -1):
            sub_p = round(best / k)
            if sub_p >= MIN_PERIOD and _score_period(sub_p)[0] >= best_score - 0.03:
                best = sub_p
                break
    if best is None:
        log("no loop found")
        return None
    p, tol = best, max(BIN, best // 100)
    # per 5 s: is the music a replay of one period before? walk back.
    step = 250
    ok = {}
    for fr, keys, where in data.values():
        tot, hit = collections.Counter(), collections.Counter()
        for i in range(K - 1, len(fr)):
            b = fr[i] // step
            tot[b] += 1
            if _has_match(where[keys[i]], fr[i] - p, tol):
                hit[b] += 1
        for b in tot:
            ok.setdefault(b, []).append(hit[b] / tot[b])
    b = end // step - 1
    best_b = b
    miss = 0
    while b > 0:
        prev = b - 1
        if prev in ok:
            if min(ok[prev]) >= 0.6:
                best_b = prev
                miss = 0
            else:
                miss += 1
                if miss >= 2:
                    break
        else:
            # Empty 5s bucket (silent pause inside song): don't require phase
            # alignment with a 5s grid one period earlier; allow up to 4 empty
            # buckets as long as matching resumes before them.
            miss += 1
            if miss >= 5:
                break
        b = prev
    at = best_b * step
    log(f"SONG LOOPS: period ~{p / FPS:.1f}s; second pass from {at / FPS:.0f}s, "
          f"so the loop began ~{(at - p) / FPS:.0f}s")
    return p, at


if __name__ == "__main__":
    song_loop(sys.argv[1], print)
