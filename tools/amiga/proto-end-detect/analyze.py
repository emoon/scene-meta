#!/usr/bin/env python3
"""PROTOTYPE (throwaway): what do the per-frame signals of a trace say?

    python3 amiga/proto-end-detect/analyze.py TRACE.csv [--bucket 500]

Prints one row per bucket (the state, to eyeball), then the events derived.
"""
import argparse, csv, sys

K = 100       # frames of Paula writes that make one "bar" of music to match
FPS = 50


def load(path):
    rows = []
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        for x in r:
            rows.append(dict(
                frame=int(x[0]), dmacon=int(x[1], 16), aw=x[2], awrites=int(x[3]),
                aenergy=int(x[4]), apeak=int(x[5]), newpc=int(x[7]),
                instr=int(x[8]), rom=int(x[9]), lastdma=int(x[10]),
                resets=int(x[11]), chan=x[13], cells=tuple(x[14:])))
    return rows


def lags(keys, min_lag=1):
    """Per position: distance back to the previous position with the same
    key (0 = never seen)."""
    seen, out = {}, []
    for i, k in enumerate(keys):
        j = seen.get(k)
        out.append(i - j if j is not None and i - j >= min_lag else 0)
        seen[k] = i
    return out


def stable_runs(lag, tol=0, min_len=200):
    """Runs where the lag stays the same non-zero value: [(start, end, lag)]."""
    out, i, n = [], 0, len(lag)
    while i < n:
        if lag[i] > 1:
            j = i
            while j + 1 < n and lag[j + 1] == lag[i]:
                j += 1
            if j - i + 1 >= min_len:
                out.append((i, j, lag[i]))
            i = j + 1
        else:
            i += 1
    return out


BURST = 5     # new instructions in a frame that mean "something new started"


def dominant(lag, start, tol=8):
    """(period, share) of the commonest lag from ``start`` on."""
    ls = [x for x in lag[start:] if x > 1]
    if not ls:
        return 0, 0.0
    p = max(set(ls), key=ls.count)
    return p, sum(abs(x - p) <= tol for x in lag[start:]) / max(1, len(lag) - start)


def verdict(rows, vlag, alag, changed, t):
    """The model: nothing new runs after the last burst of new code. What
    the demo does from there says how it ends."""
    n = len(rows)
    new = max((i for i in range(n) if rows[i]["newpc"] >= BURST), default=0)
    after = n - new
    out = [f"last new code {t(new)} ({after / FPS:.0f}s of trace after it)"]
    sil = n   # no channel plays anything but silence or one unchanged loop
    while sil > 0 and "P" not in rows[sil - 1]["chan"]:
        sil -= 1
    drone = "R" in rows[-1]["chan"]
    still = n
    while still > 0 and changed[still - 1] == 0:
        still -= 1
    reset_after = rows[-1]["resets"] > rows[new]["resets"]
    dma_after = rows[-1]["lastdma"] > rows[new]["frame"] + 250
    vp, vs = dominant(vlag, new + (n - new) // 2)
    mp, ms = dominant(alag, new + (n - new) // 2)
    played = rows[new]["frame"]
    if still < n - 500 and sil < n - 500:
        tail = range(max(0, n - 1000), n)
        rom = sum(rows[i]["rom"] for i in tail) / (sum(rows[i]["instr"] for i in tail) or 1)
        where = "EXITS to the OS" if rom > 0.5 else "STOPS inside the program (frozen or waiting)"
        kind = f"{where}: still and silent from {t(max(still, sil))}"
        if sil == 0:
            kind += "; never made a sound"
    else:
        p = vp if vs >= 0.5 else mp if ms >= 0.3 else 0
        whole = p and p >= 0.6 * played
        if whole or reset_after:
            kind = (f"RESTARTS: the whole demo plays again, length "
                    f"{(p or played) / FPS:.0f}s")
        elif p:
            kind = (f"END LOOP: period {p / FPS:.1f}s; end part from ~{t(new)}, "
                    f"all shown once by ~{(rows[new]['frame'] + p) / FPS:.0f}s")
        else:
            kind = f"END PART, open: from ~{t(new)}, no period found"
        if sil == 0:
            kind += "; never made a sound"
        elif sil < n - 500:
            kind += f"; music over at {t(sil)}" + (" (a loop drones on)" if drone else "")
    out.append(kind)
    out.append(f"evidence: video period {vp} ({vs:.0%}), music period {mp} ({ms:.0%}), "
               f"reset after {reset_after}, disk after {dma_after}")
    print("  VERDICT: " + "\n           ".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--bucket", type=int, default=1000)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    rows = load(a.trace)
    n = len(rows)
    f0 = rows[0]["frame"]
    t = lambda i: f"{(rows[i]['frame']) / FPS:7.1f}s"

    vkeys = [r["cells"] for r in rows]
    vlag = lags(vkeys)
    # music: K consecutive frames of register writes
    akeys = [hash(tuple(r["aw"] for r in rows[max(0, i - K + 1):i + 1])) for i in range(n)]
    alag = lags(akeys)
    changed = [0] + [sum(a != b for a, b in zip(vkeys[i], vkeys[i - 1])) for i in range(1, n)]

    if not a.quiet:
        print("   time  vchg  cells vnew%  vlag(mode)  aenergy  awr  anew% alag(mode) newpc rom% dma")
        for b in range(0, n, a.bucket):
            sl = range(b, min(n, b + a.bucket))
            m = len(sl)
            vch = sum(changed[i] > 0 for i in sl) / m
            cells = sum(changed[i] for i in sl) / m
            vnew = sum(vlag[i] == 0 for i in sl) / m
            vl = [vlag[i] for i in sl if vlag[i] > 1]
            vmode = max(set(vl), key=vl.count) if vl else 0
            al = [alag[i] for i in sl if alag[i] > 1]
            amode = max(set(al), key=al.count) if al else 0
            anew = sum(alag[i] == 0 for i in sl) / m
            en = sum(rows[i]["aenergy"] for i in sl) / m
            awr = sum(rows[i]["awrites"] for i in sl) / m
            npc = sum(rows[i]["newpc"] for i in sl)
            ins = sum(rows[i]["instr"] for i in sl) or 1
            rom = sum(rows[i]["rom"] for i in sl) / ins
            dma = any(rows[i]["lastdma"] >= rows[b]["frame"] for i in sl)
            print(f"{t(b)} {vch:5.0%} {cells:5.1f} {vnew:5.0%} {vmode:7d}    "
                  f"{en:8.0f} {awr:4.1f} {anew:5.0%} {amode:7d}   {npc:6d} {rom:4.0%} {'D' if dma else ''}")

    print("\nderived:")
    # last new code
    last_new = max((i for i in range(n) if rows[i]["newpc"] > 0), default=0)
    big_new = max((i for i in range(n) if rows[i]["newpc"] >= 20), default=0)
    print(f"  last new code (any): {t(last_new)}   last burst (>=20 new/frame): {t(big_new)}")
    print(f"  last disk DMA: {rows[-1]['lastdma'] / FPS:.1f}s")
    # silence
    sil = n
    while sil > 0 and rows[sil - 1]["aenergy"] == 0:
        sil -= 1
    print(f"  audio silent from: {t(sil) if sil < n else 'never'}")
    still = n
    while still > 0 and changed[still - 1] == 0:
        still -= 1
    print(f"  screen still from: {t(still) if still < n else 'never'}")
    for name, lag in (("video", vlag), ("music", alag)):
        runs = stable_runs(lag)
        if runs:
            s, e_, p = runs[-1]
            tail = "to the end" if e_ >= n - 2 else f"until {t(e_)}"
            print(f"  {name} repeats: period {p} frames ({p / FPS:.1f}s) from {t(s)} {tail}; "
                  f"first pass began {t(max(0, s - p))}  [{len(runs)} runs]")
        else:
            print(f"  {name} repeats: no")
    verdict(rows, vlag, alag, changed, t)
    tail = range(max(0, n - 1000), n)
    ins = sum(rows[i]["instr"] for i in tail) or 1
    print(f"  ROM share of the last 1000 frames: {sum(rows[i]['rom'] for i in tail) / ins:.0%}; resets {rows[-1]['resets']}")


if __name__ == "__main__":
    main()
