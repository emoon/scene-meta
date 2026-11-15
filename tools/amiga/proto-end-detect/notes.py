#!/usr/bin/env python3
"""PROTOTYPE (throwaway): does the song loop? Matches the note events (Paula
pointer, length and period writes, in order) of each channel, not frames.

    python3 amiga/proto-end-detect/notes.py TRACE.csv.notes
"""
import collections, sys

K = 16        # consecutive events of one channel that make a run to match
FPS = 50
BIN = 10      # frames: candidate periods are counted in bins this wide
MIN_PERIOD = 250
TAIL = 3000    # frames at the end of the trace the loop is looked for in


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


def main():
    chans, cur = collections.defaultdict(list), {}
    for line in open(sys.argv[1]):
        f, ch, reg, v = line.rstrip().split(",")
        # A period written again with the value it has is not a note
        # (Desert Dream's player rewrites all four every frame).
        if reg == "2":
            if cur.get(ch) == v:
                continue
            cur[ch] = v
        chans[ch].append((int(f), (reg, v)))
    data = {ch: channel(ev) for ch, ev in sorted(chans.items())}
    end = max(fr[-1] for fr, _, _ in data.values())
    print(f"{sum(len(d[0]) for d in data.values())} events, to {end / FPS:.0f}s")
    t0 = end - TAIL
    hist = collections.Counter()
    for fr, keys, where in data.values():
        for i in range(K - 1, len(fr)):
            if fr[i] >= t0:
                for f in where[keys[i]]:
                    if fr[i] - f >= MIN_PERIOD:
                        hist[(fr[i] - f) // BIN] += 1
    best = None
    for b, _ in hist.most_common(20):
        p = b * BIN + BIN // 2
        tol = max(BIN, p // 100)
        shares = []
        for fr, keys, where in data.values():
            idx = [i for i in range(K - 1, len(fr)) if fr[i] >= t0]
            hit = sum(any(abs(fr[i] - f - p) <= tol for f in where[keys[i]]) for i in idx)
            shares.append(hit / len(idx) if len(idx) > 20 else None)
        txt = " ".join("  - " if s is None else f"{s:4.0%}" for s in shares)
        print(f"  candidate {p / FPS:6.1f}s: per channel {txt}")
        live = [s for s in shares if s is not None]
        score = round(min(live), 2) if live else 0
        if score >= 0.8 and (best is None or (-score, p) < best):
            best = (-score, p)
    best = best and best[1]
    if best is None:
        print("no loop found")
        return
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
    print(f"SONG LOOPS: period ~{p / FPS:.1f}s; second pass from {at / FPS:.0f}s, "
          f"so the loop began ~{(at - p) / FPS:.0f}s")


if __name__ == "__main__":
    main()
