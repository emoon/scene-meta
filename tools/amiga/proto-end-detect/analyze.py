#!/usr/bin/env python3
"""PROTOTYPE (throwaway): what do the per-frame signals of a trace say?

    python3 amiga/proto-end-detect/analyze.py TRACE.csv [--bucket 500]

Prints one row per bucket (the state, to eyeball), then the events derived.
"""
import argparse, csv, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notes import song_loop  # noqa: E402
from video import cell_periods, chain_period, landmark, load_cells, onsets, MIN_LANDMARK  # noqa: E402

K = 100       # frames of Paula writes that make one "bar" of music to match
FPS = 50


def load(path):
    """``(rows, cells)``: the per-frame signals, and the screen-cell hashes
    as an array [frame, cell]."""
    rows = []
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        for x in r:
            rows.append(dict(
                frame=int(x[0]), dmacon=int(x[1], 16), aw=x[2], awrites=int(x[3]),
                aenergy=int(x[4]), apeak=int(x[5]), newpc=int(x[7]),
                instr=int(x[8]), rom=int(x[9]), lastdma=int(x[10]),
                resets=int(x[11]), chan=x[13]))
    return rows, load_cells(path)


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
DRONE = 1500  # frames without a Paula write that make a sound still playing a drone
SPARSE = 0.01 # share of frames with Paula writes below which they carry no music


def video_loop(cells, t0):
    """``(period, shown, kinds)``: the picture loops when every cell that
    still changes has a period of its own, cells that are fresh at every
    change aside. ``period`` is the longest, ``shown`` the frame by which
    every cell has been through its loop once; 0 when it does not loop."""
    kinds = cell_periods(cells, t0)
    loops = [k for k in kinds if k[0] == "loop"]
    if not loops or any(k[0] == "open" for k in kinds):
        return 0, 0, kinds
    return max(k[1] for k in loops), max(k[2] for k in kinds), kinds


def silence_landmark(rows, new):
    """Period at which all channels fall silent together, for music that
    writes no notes to Paula (a software mixer restarting its song)."""
    if sum(r["awrites"] > 0 for r in rows[new:]) > SPARSE * (len(rows) - new):
        return 0
    silent = [r["chan"] == "SSSS" for r in rows]
    return chain_period(onsets(silent), new, len(rows), MIN_LANDMARK)


def verdict(rows, cells, song):
    """The model: nothing new runs after the last burst of new code. What
    the demo does from there says how it ends. ``song`` is what
    ``song_loop`` found. Returns a dict, times in s."""
    n = len(rows)
    sec = lambda i: round(rows[min(i, n - 1)]["frame"] / FPS, 1)
    new = max((i for i in range(n) if rows[i]["newpc"] >= BURST), default=0)
    sil = n   # no channel plays anything but silence or one unchanged loop
    while sil > 0 and "P" not in rows[sil - 1]["chan"]:
        sil -= 1
    quiet = n  # nothing is written to Paula
    while quiet > 0 and not rows[quiet - 1]["awrites"]:
        quiet -= 1
    moved = (cells[1:] != cells[:-1]).any(axis=1).nonzero()[0]
    still = int(moved[-1]) + 2 if len(moved) else 0
    tail = range(max(0, n - 1000), n)
    rom = sum(rows[i]["rom"] for i in tail) / (sum(rows[i]["instr"] for i in tail) or 1)
    vp, vshown, kinds = video_loop(cells, new + (n - new) // 2)
    lp = 0 if vp or song else landmark(cells, kinds, new) or silence_landmark(rows, new)
    played = rows[new]["frame"]
    out = dict(trace=sec(n - 1), last_new=sec(new), sound=sil > 0,
               resets=rows[-1]["resets"],
               reset_after=rows[-1]["resets"] > rows[new]["resets"],
               disk_after=rows[-1]["lastdma"] > rows[new]["frame"] + 250,
               video_period=round(vp / FPS, 1) if vp else None,
               video_shown=sec(vshown) if vp else None,
               cells={k: sum(x[0] == k for x in kinds) for k in ("still", "loop", "noisy", "open")},
               song_period=round(song[0] / FPS, 1) if song else None,
               song_second_pass=round(song[1] / FPS, 1) if song else None,
               landmark_period=round(lp / FPS, 1) if lp else None,
               music_over=sec(sil) if 0 < sil < n - 500 else None,
               drone="R" in rows[-1]["chan"] or 0 < quiet < n - DRONE <= sil)
    # the sound is over: silent, one loop unchanged, or left playing unwritten
    over = sil if sil < n - 500 else quiet if quiet < n - DRONE else n
    stopped = still < n - 500 and over < n
    period = max(vp, song[0] if song else 0, lp)
    if stopped:
        out["ending"] = "exits" if rom > 0.5 else "stops"
        out["end"] = sec(max(still, over))
    elif out["reset_after"] or (period and period >= 0.6 * played):
        # the loop holds the whole production: a demo that starts over, or
        # one screen whose song comes round
        out["ending"] = "restarts" if out["reset_after"] or out["disk_after"] else "loops"
        # (a restart is the end itself: the second boot differs from the first)
        shown = rows[vshown]["frame"] if vp and out["ending"] == "loops" else 0
        out["end"] = round(max(played, period, shown) / FPS, 1)
    elif period:
        out["ending"] = "end-loop"
        out["end_part"] = sec(new)
        # all shown once: the picture through its loop, the song into its
        # second pass, or one landmark period into the end part
        done = [rows[vshown]["frame"]] if vp else []
        done += [song[1]] if song else []
        done += [played + lp] if lp else []
        out["end"] = round(max(done + [played]) / FPS, 1)
    else:
        out["ending"] = "open"
        out["end_part"] = sec(new)
        if out["music_over"]:
            out["end"] = max(out["music_over"], out["last_new"])
    # how sure: the trace must run on well past the last new code
    out["after"] = round((n - new) / FPS)
    return out


def song_of(trace):
    notes = trace + ".notes"
    return song_loop(notes) if os.path.exists(notes) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--bucket", type=int, default=1000)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows, cells = load(a.trace)
    n = len(rows)
    f0 = rows[0]["frame"]
    t = lambda i: f"{(rows[i]['frame']) / FPS:7.1f}s"

    vkeys = [c.tobytes() for c in cells]
    vlag = lags(vkeys)
    # music: K consecutive frames of register writes
    akeys = [hash(tuple(r["aw"] for r in rows[max(0, i - K + 1):i + 1])) for i in range(n)]
    alag = lags(akeys)
    changed = [0] + (cells[1:] != cells[:-1]).sum(axis=1).tolist()

    if a.json:
        print(json.dumps(verdict(rows, cells, song_of(a.trace))))
        return
    if not a.quiet:
        print("   time  vchg  cells vnew%  vlag(mode)  aenergy  awr  anew% alag(mode) newpc rom% dma")
        for b in range(0, n, a.bucket):
            sl = range(b, min(n, b + a.bucket))
            m = len(sl)
            vch = sum(changed[i] > 0 for i in sl) / m
            vcells = sum(changed[i] for i in sl) / m
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
            print(f"{t(b)} {vch:5.0%} {vcells:5.1f} {vnew:5.0%} {vmode:7d}    "
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
    print("  VERDICT:", json.dumps(verdict(rows, cells, song_of(a.trace))))
    tail = range(max(0, n - 1000), n)
    ins = sum(rows[i]["instr"] for i in tail) or 1
    print(f"  ROM share of the last 1000 frames: {sum(rows[i]['rom'] for i in tail) / ins:.0%}; resets {rows[-1]['resets']}")


if __name__ == "__main__":
    main()
