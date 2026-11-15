#!/usr/bin/env python3
"""PROTOTYPE (throwaway): does the song loop? Matches the note events (Paula
pointer and period writes, in order) of each channel, not frames.

    python3 amiga/proto-end-detect/notes.py TRACE.csv.notes
"""
import collections, sys

K = 16        # consecutive events of one channel that make a run to match
FPS = 50
BIN = 10      # frames: candidate periods are counted in bins this wide
MIN_PERIOD = 250
TAIL = 3000    # frames at the end of the trace the loop is looked for in
BEND = 0.03    # share a period may move from the last note's and not be a note


def channel(ev):
    """ev: [(frame, key)] of one channel -> (frames, where) with ``where``
    mapping each run of K events to the frames it ended at."""
    frames = [f for f, _ in ev]
    h = [hash(k) for _, k in ev]
    keys = [None] * len(ev)
    where = collections.defaultdict(list)
    for i in range(K - 1, len(ev)):
        keys[i] = hash(tuple(h[i - K + 1:i + 1]))
        where[keys[i]].append(frames[i])
    return frames, keys, where


def song_loop(path, log=lambda *a: None):
    """``(period, second_pass_from)`` in frames, or None."""
    chans, cur = collections.defaultdict(list), {}
    for line in open(path):
        f, ch, reg, v = line.rstrip().split(",")
        # A length write is not a note: The Chaos Engine's player writes
        # lengths that differ from one pass of the song to the next.
        if reg == "3":
            continue
        # A period within a quarter tone of the last note's is not a note:
        # the value it has written again (Desert Dream's player rewrites
        # all four every frame), or a vibrato, which need not keep step
        # with the song (Assemblers of Infinity 3).
        if reg == "2":
            per = int(v, 16)
            if abs(per - cur.get(ch, 0)) <= BEND * per:
                continue
            cur[ch] = per
        chans[ch].append((int(f), (reg, v)))
    data = {ch: channel(ev) for ch, ev in sorted(chans.items())}
    if not data:
        return None
    end = max(fr[-1] for fr, _, _ in data.values())
    log(f"{sum(len(d[0]) for d in data.values())} events, to {end / FPS:.0f}s")
    t0 = end - TAIL
    hist = collections.Counter()
    for fr, keys, where in data.values():
        for i in range(K - 1, len(fr)):
            if fr[i] >= t0:
                for f in where[keys[i]]:
                    if fr[i] - f >= MIN_PERIOD:
                        hist[(fr[i] - f) // BIN] += 1
    best, passed = None, []
    for b, _ in hist.most_common(20):
        p = b * BIN + BIN // 2
        tol = max(BIN, p // 100)
        shares = []
        for fr, keys, where in data.values():
            idx = [i for i in range(K - 1, len(fr)) if fr[i] >= t0]
            hit = sum(any(abs(fr[i] - f - p) <= tol for f in where[keys[i]]) for i in idx)
            shares.append(hit / len(idx) if len(idx) > 20 else None)
        txt = " ".join("  - " if s is None else f"{s:4.0%}" for s in shares)
        log(f"  candidate {p / FPS:6.1f}s: per channel {txt}")
        live = [s for s in shares if s is not None]
        score = round(min(live), 2) if live else 0
        if score >= 0.8:
            passed.append((-score, p))
            if best is None or (-score, p) < best:
                best = (-score, p)
    best = best and best[1]
    if best:
        # A multiple of the period matches as well or better (its tolerance
        # is wider): take the passing period the best is the highest multiple
        # of. Several bins pass around each such period (the tolerance spans
        # them): of those the best-scoring one, as for the best itself.
        tol = max(BIN, best // 100)
        subs = [(-round(best / p), s, p) for s, p in passed if abs(best - round(best / p) * p) <= tol]
        best = min(subs)[2]
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
            tot[fr[i] // step] += 1
            hit[fr[i] // step] += any(abs(fr[i] - f - p) <= tol for f in where[keys[i]])
        for b in tot:
            ok.setdefault(b, []).append(hit[b] / tot[b])
    b = end // step - 1
    while b - 1 in ok and min(ok[b - 1]) >= 0.6:
        b -= 1
    at = b * step
    log(f"SONG LOOPS: period ~{p / FPS:.1f}s; second pass from {at / FPS:.0f}s, "
          f"so the loop began ~{(at - p) / FPS:.0f}s")
    return p, at


if __name__ == "__main__":
    song_loop(sys.argv[1], print)
