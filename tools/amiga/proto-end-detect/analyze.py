#!/usr/bin/env python3
"""PROTOTYPE (throwaway): what do the per-frame signals of a trace say?

    python3 amiga/proto-end-detect/analyze.py TRACE.csv [--bucket 500]

Prints one row per bucket (the state, to eyeball), then the events derived.
"""
import argparse, csv, json, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notes import song_loop  # noqa: E402
from streams import stream_end, stream_ends  # noqa: E402
from video import cell_periods, chain_period, landmark, load_cells, onsets, MIN_LANDMARK  # noqa: E402

K = 100       # frames of Paula writes that make one "bar" of music to match
FPS = 50


def load(path):
    """``(rows, cells)``: the per-frame signals, and the screen-cell hashes
    as an array [frame, cell]."""
    rows = []
    with open(path) as f:
        r = csv.reader(f)
        # (traces recorded before the alert/newram/solid/bplcon0/cop1lc columns have none)
        head = next(r)
        alert = head.index("alert") if "alert" in head else None
        newram = head.index("newram") if "newram" in head else None
        solid = head.index("solid") if "solid" in head else None
        bplcon0 = head.index("bplcon0") if "bplcon0" in head else None
        cop1lc = head.index("cop1lc") if "cop1lc" in head else None
        for x in r:
            rows.append(dict(
                frame=int(x[0]), dmacon=int(x[1], 16), aw=x[2], awrites=int(x[3]),
                aenergy=int(x[4]), apeak=int(x[5]), newpc=int(x[7]),
                instr=int(x[8]), rom=int(x[9]), lastdma=int(x[10]),
                resets=int(x[11]), chan=x[13],
                alert=int(x[alert], 16) if alert is not None else 0,
                newram=int(x[newram]) if newram is not None else None,
                solid=int(x[solid]) if solid is not None else None,
                bplcon0=int(x[bplcon0], 16) if bplcon0 is not None else None,
                cop1lc=int(x[cop1lc], 16) if cop1lc is not None else None))
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
SHOWN = 50    # frames the picture changes in that booting to the shell alone takes
HELD = 9000   # frames a silent single screen with no end of its own is given
SPARSE = 0.01 # share of frames with Paula writes below which they carry no music
PRE_EXIT_WAIT = 3000  # frames (60s) of stillness or no-new-code before OS exit


def video_loop(cells, t0):
    """``(period, shown, kinds)``: the picture loops when every cell that
    still changes has a period of its own, cells that are fresh at every
    change aside. ``period`` is the longest, ``shown`` the frame by which
    every cell has been through its loop once; 0 when it does not loop."""
    kinds = cell_periods(cells, t0)
    loops = [k for k in kinds if k[0] == "loop"]
    if not loops or any(k[0] == "open" for k in kinds):
        return 0, 0, kinds
    # Group looping cells by period (within 2%) and take the 75th-percentile
    # shown frame for large groups (>= 10 cells) so a strip of cells with minor
    # sub-cadence tearing (e.g. v17/v18 in 89549, v00..v06 in 139138) does not
    # drag video_shown hundreds of seconds past the rest of the screen, while
    # preserving any smaller distinct-period scroller strip.
    groups = []
    for _, p, s in sorted(loops, key=lambda x: x[1]):
        if groups and abs(p - groups[-1][0]) <= max(2, groups[-1][0] // 50):
            groups[-1][1].append(s)
        else:
            groups.append((p, [s]))
    loop_shown = 0
    for _, gs in groups:
        gs.sort()
        pick = gs[int(0.75 * (len(gs) - 1))] if len(gs) >= 10 else gs[-1]
        if pick > loop_shown:
            loop_shown = pick
    still_shown = max((k[2] for k in kinds if k[0] == "still"), default=0)
    return max(k[1] for k in loops), max(loop_shown, still_shown), kinds


def kinds_open(kinds):
    """Cells that still change and no period explains."""
    return sum(k[0] in ("open", "noisy") for k in kinds)


def silence_landmark(rows, new):
    """Period at which all channels fall silent together, for music that
    writes no notes to Paula (a software mixer restarting its song)."""
    if sum(r["awrites"] > 0 for r in rows[new:]) > SPARSE * (len(rows) - new):
        return 0
    silent = [r["chan"] == "SSSS" for r in rows]
    return chain_period(onsets(silent), new, len(rows), MIN_LANDMARK)


def audio_loop(rows, limit=None):
    """Fallback song-loop detector via FFT Pearson autocorrelation of the
    per-frame audio energy envelope (handles software-mixed music like
    TFMX/PS3M/OctaMED/AHI where Paula note writes are absent).
    Returns ``(period, second_pass_from)`` in frames, or None."""
    n = len(rows) if limit is None else min(limit, len(rows))
    if n < 2500:
        return None
    ae = np.array([rows[i]["aenergy"] for i in range(n)], dtype=np.float64)
    if ae[-500:].mean() < 100:
        return None
    tail = ae[-min(n, 3000):]
    if tail.std() < 0.05 * max(tail.mean(), 1.0):
        return None
    ds = 2  # 25 Hz envelope (0.04 s resolution avoids grid-rounding jitter)
    m = n // ds
    x = ae[:m * ds].reshape(m, ds).mean(axis=1)
    w = min(3750, m // 3)  # up to 150 s reference tail
    if w < 250 or m - w < 150:
        return None
    ref = x[-w:]
    r0 = ref - ref.mean()
    r_norm = float(np.linalg.norm(r0))
    if r_norm < 1e-6:
        return None
    fft_n = 1 << (m + w).bit_length()
    dot = np.fft.irfft(np.fft.rfft(x, fft_n) * np.conj(np.fft.rfft(r0, fft_n)))[:m - w]
    cs1 = np.concatenate(([0.0], np.cumsum(x)))
    cs2 = np.concatenate(([0.0], np.cumsum(x * x)))
    s1 = cs1[w:m] - cs1[:m - w]
    s2 = cs2[w:m] - cs2[:m - w]
    var = np.maximum(0.0, s2 - (s1 * s1) / w)
    denom = np.sqrt(var) * r_norm
    corr = np.where(denom > 1e-6, dot / np.where(denom > 1e-6, denom, 1.0), 0.0)
    # lags >= 5 s (125 samples at 25 Hz)
    min_p = 125
    max_idx = m - w - min_p
    if max_idx <= 0:
        return None
    best_r = float(corr[:max_idx + 1].max())
    if best_r < 0.90:
        return None
    # Require candidate period to match close to the strongest peak so a
    # weaker repeating beat/motif (e.g. r=0.969 vs 0.989 in 9384, or r=0.90 vs
    # 0.995 in Zeon) doesn't alias the true song period.
    margin = 0.008 if best_r >= 0.98 else (0.015 if best_r >= 0.96 else 0.03)
    thresh = max(0.90, best_r - margin)
    hits = np.where(corr[:max_idx + 1] >= thresh)[0]
    if not len(hits):
        return None
    # Shortest passing period (largest index)
    j = int(hits[-1])
    lo, hi = max(0, j - 10), min(max_idx + 1, j + 11)
    j = lo + int(np.argmax(corr[lo:hi]))
    p = (m - w) - j
    # Walk backwards in 5 s blocks to find where the second pass began
    step = 125  # 5 s at 25 Hz
    b = (m - step) // step * step
    best_b = b
    miss = 0
    while b - step >= p:
        prev = b - step
        a_seg = x[prev:prev + step]
        b_seg = x[prev - p:prev - p + step]
        if a_seg.mean() < 100 and b_seg.mean() < 100:
            miss += 1
            if miss >= 5:
                break
            b = prev
            continue
        a0, b0 = a_seg - a_seg.mean(), b_seg - b_seg.mean()
        dn = float(np.linalg.norm(a0) * np.linalg.norm(b0))
        if dn > 1e-6 and float(np.dot(a0, b0)) / dn >= 0.70:
            best_b = prev
            miss = 0
        else:
            miss += 1
            if miss >= 2:
                break
        b = prev
    return p * ds, rows[min(best_b * ds, n - 1)]["frame"]


def _last_burst(rows, limit, ram_only=False):
    """Last frame index < limit with a new-code burst (>= BURST)."""
    key = "newram" if (ram_only and rows and rows[0]["newram"] is not None) else "newpc"
    for i in range(limit - 1, -1, -1):
        if (rows[i][key] or 0) >= BURST:
            return i
    return 0


def _exit_start(rows, still, over, os_cop):
    """For a run that exits to the OS, the index where the exit transition
    began (before the shell window drew)."""
    n = len(rows)
    if os_cop is not None and rows[-1]["cop1lc"] == os_cop:
        t = n
        while t > 0 and rows[t - 1]["cop1lc"] == os_cop:
            t -= 1
        if 0 < t < n:
            return t
    return min(still, over)


def _fatal_guru(rows, cells):
    """First frame index of a real Guru Meditation alert (not a demo that
    reused ExecBase+$202 for its own data/code and kept playing)."""
    n = len(rows)
    changed = np.zeros(n, dtype=bool)
    if n > 1:
        changed[1:] = (cells[1:] != cells[:-1]).any(axis=1)
    prev_alert = 0
    for i in range(n):
        a = rows[i]["alert"]
        is_valid = bool(a and a != 0xffffffff and (a & 0x7fffffff) != 0
                        and ((a >> 24) & 0x7f) <= 0x3f)
        if is_valid and a != prev_alert:
            boot = rows[i]["resets"]
            j_end = i + 50
            while j_end < n and rows[j_end]["resets"] == boot:
                j_end += 1
            if i + 50 >= j_end:
                if i >= n - 50 and "P" in rows[-1]["chan"]:
                    prev_alert = a
                    continue
                return i
            # Only count active audio ("P", not silent Paula writes), and do
            # not let a surviving VBlank music interrupt override a real crash
            # when the CPU is trapped in Kickstart ROM with a frozen screen.
            audio_active = sum(
                1 for k in range(i + 50, j_end)
                if "P" in rows[k]["chan"]
            )
            seg = changed[i + 50:j_end]
            instr_after = sum(rows[k]["instr"] for k in range(i + 50, j_end)) or 1
            rom_after = sum(rows[k]["rom"] for k in range(i + 50, j_end)) / instr_after
            alert_cleared = any(rows[k]["alert"] == 0 for k in range(i + 50, j_end))
            has_newram = rows[0]["newram"] is not None
            newram_after = (sum((rows[k]["newram"] or 0) for k in range(i + 50, j_end))
                            if has_newram else 1)
            if audio_active >= 250 and (rom_after <= 0.5 or seg.sum() >= 50 or alert_cleared):
                prev_alert = a
                continue
            # Also guard screen-change bypass against ROM-trapped crashes whose
            # orphaned Copperlist/bitplane DMA keeps scanning Chip RAM (e.g. 90583).
            if (rom_after <= 0.5 or alert_cleared or newram_after > 0) and len(seg) >= 250:
                cs = np.concatenate(([0], np.cumsum(seg)))
                if (cs[250:] - cs[:-250]).max() >= 50:
                    prev_alert = a
                    continue
            return i
        prev_alert = a
    return None


def verdict(rows, cells, song, halted=False, data=None, swaps=(), meta=None,
            notes_path=None, text_data=None):
    """The model: nothing new runs after the last burst of new code. What
    the demo does from there says how it ends. ``song`` is what
    ``song_loop`` found, ``halted`` whether the CPU halted at the end of
    the trace, ``data`` the frame of the last new data read as a stream
    (None: not recorded), ``swaps`` the s at which the entry's script puts in
    the next disk. Returns a dict, times in s."""
    n = len(rows)
    if not n:
        return {"ending": "crashed" if halted else "not-started"}
    sec = lambda i: round(rows[min(max(i, 0), n - 1)]["frame"] / FPS, 1)
    moved = (cells[1:] != cells[:-1]).any(axis=1).nonzero()[0]
    still = int(moved[-1]) + 2 if len(moved) else 0
    # If the demo actually showed visuals and then went completely still for
    # >= 30 s to the end of the trace, ignore any late runaway/garbage burst
    # after the screen froze (e.g. .plong counter overflow at 899 s).
    new_limit = min(n, still + 250) if (len(moved) >= SHOWN and still < n - 1500) else n
    new = _last_burst(rows, new_limit, ram_only=True)
    sil = n   # no channel plays anything but silence or one unchanged loop
    while sil > 0 and "P" not in rows[sil - 1]["chan"]:
        sil -= 1
    # If the music stopped for >= 60 s continuously after the last new code
    # (with no disk DMA afterward) and only replayed much later because a MOD
    # pattern table wrapped around (e.g. 281473), treat the first sustained
    # silence as the end of music rather than scanning back from trace end.
    first_sil = None
    if sil > 0 and rows[-1]["lastdma"] <= rows[new]["frame"] + 250:
        run_start = None
        seen_p = any("P" in rows[k]["chan"] for k in range(0, max(0, new - 750)))
        for k in range(max(0, new - 750), n):
            if "P" in rows[k]["chan"]:
                seen_p = True
                run_start = None
            elif seen_p:
                if run_start is None:
                    run_start = k
                elif k - run_start + 1 >= PRE_EXIT_WAIT:
                    first_sil = run_start
                    break
    if first_sil is not None and first_sil < sil:
        sil = first_sil
        song = None
    quiet = n  # nothing is written to Paula
    while quiet > 0 and not rows[quiet - 1]["awrites"]:
        quiet -= 1
    paula_used = sum(r["awrites"] for r in rows) > 100
    tail = range(max(0, n - 1000), n)
    rom = sum(rows[i]["rom"] for i in tail) / (sum(rows[i]["instr"] for i in tail) or 1)
    drone = "R" in rows[-1]["chan"] or (paula_used and 0 < quiet < n - DRONE <= sil)
    # Silent Paula register writes (volume=0) must not count as a looping song
    if sil < n - 500:
        song = None
    # Software-mixed music fallback: audio energy autocorrelation when Paula
    # note matching found nothing and music is actively playing (not a drone)
    if song is None and not drone and sil >= n - 500:
        song = audio_loop(rows)
    vp, vshown, kinds = video_loop(cells, new + (n - new) // 2)
    lp = 0 if vp or song else landmark(cells, kinds, new) or silence_landmark(rows, new)
    played = rows[new]["frame"]
    # the sound is over: silent, one loop unchanged, or Paula music left
    # playing unwritten for > DRONE frames (a drone, not a software mixer)
    over = n
    if sil < n - 500 and (paula_used or not drone):
        over = min(over, sil)
    if paula_used and quiet < n - DRONE:
        over = min(over, quiet)
    out = dict(trace=sec(n - 1), last_new=sec(new), sound=sil > 0 or paula_used,
               resets=rows[-1]["resets"],
               reset_after=rows[-1]["resets"] > rows[new]["resets"],
               disk_after=rows[-1]["lastdma"] > rows[new]["frame"] + 250,
               video_period=round(vp / FPS, 1) if vp else None,
               video_shown=sec(vshown) if vp else None,
               cells={k: sum(x[0] == k for x in kinds) for k in ("still", "loop", "noisy", "open")},
               song_period=round(song[0] / FPS, 1) if song else None,
               song_second_pass=round(song[1] / FPS, 1) if song else None,
               landmark_period=round(lp / FPS, 1) if lp else None,
               music_over=sec(over) if 0 < over < n else None,
               drone=drone)
    # A slow slideshow (e.g. a new slide every 74 s) is not "stopped" just
    # because the trace ended 58 s after its last slide.
    still_gap = 500
    if len(moved) >= 3 and still < n - 500:
        mgaps = np.diff(moved)
        big_gaps = mgaps[mgaps >= 500]
        if len(big_gaps) >= 2:
            still_gap = max(still_gap, int(1.5 * big_gaps[-4:].max()))
    stopped = still < n - still_gap and over < n
    period = max(vp, song[0] if song else 0, lp)
    guru = _fatal_guru(rows, cells)
    end_box = (meta or {}).get("end_box") or ""
    os_cop = (meta or {}).get("os_cop")
    if guru is not None or halted or end_box in ("guru", "task-held"):
        # a Guru, task-held requester, or a halted CPU: crashed
        out["ending"] = "crashed"
        out["alert"] = (f"{rows[guru]['alert']:08x}" if guru is not None
                        else end_box or "halt")
        out["crashed"] = sec(guru if guru is not None else n - 1)
    elif rows[0]["newram"] is not None and not any(r["newram"] for r in rows):
        # no code but the Kickstart's ever ran (its insert-disk screen):
        # nothing was loaded, so there is no end and no length
        out["ending"] = "not-started"
    elif stopped and not out["sound"] and len(moved) < SHOWN:
        # back at the shell (or halted) having shown and played nothing: the
        # program did not load or gave up at once
        out["ending"] = "not-started"
    elif stopped:
        out["ending"] = "exits" if rom > 0.5 else "stops"
        end_i = max(still, over)
        # Before exiting to the OS, did the demo sit on a still end-screen or
        # loop its song for a long stretch (timeout-exit, e.g. Greenday, Showstopper)?
        if out["ending"] == "exits":
            ex = _exit_start(rows, still, over, os_cop)
            if ex > PRE_EXIT_WAIT:
                pre_moved = moved[moved < ex - 50]
                pre_still = int(pre_moved[-1]) + 2 if len(pre_moved) else 0
                pre_new = _last_burst(rows, max(0, ex - 50), ram_only=True)
                pre_song = None
                if notes_path and os.path.exists(notes_path) and pre_new < ex - PRE_EXIT_WAIT:
                    try:
                        pre_song = song_loop(notes_path, trace_end=rows[ex]["frame"])
                    except ValueError:
                        pre_song = None
                if pre_song is None and pre_new < ex - PRE_EXIT_WAIT:
                    pre_song = audio_loop(rows, limit=ex)
                if pre_song and rows[ex]["frame"] - pre_song[1] >= max(6000, pre_song[0]):
                    out["song_period"] = round(pre_song[0] / FPS, 1)
                    out["song_second_pass"] = round(pre_song[1] / FPS, 1)
                    out["end_part"] = sec(pre_new)
                    out["end"] = round(max(rows[pre_new]["frame"], pre_song[1]) / FPS, 1)
                elif len(pre_moved) >= SHOWN and pre_still < ex - 6000 and pre_new <= pre_still + 250:
                    if pre_song and pre_song[1] < rows[ex]["frame"] - 1500:
                        out["song_period"] = round(pre_song[0] / FPS, 1)
                        out["song_second_pass"] = round(pre_song[1] / FPS, 1)
                        out["end"] = round(max(rows[pre_still]["frame"], pre_song[1]) / FPS, 1)
                    else:
                        out["end"] = sec(pre_still)
                else:
                    out["end"] = sec(end_i)
            else:
                out["end"] = sec(end_i)
        else:
            out["end"] = sec(end_i)
    elif out["music_over"] and not song and not vp and not out["disk_after"] and over >= new - 750:
        # The music played and ended around the last new code, leaving only a
        # silent landmark/open screen (e.g. Painted Eggs, 1% AiDS).
        out["ending"] = "end-loop" if period else "open"
        out["end_part"] = sec(new)
        out["end"] = max(out["music_over"], out["last_new"])
    elif out["reset_after"] or (period and period >= 0.6 * played and (
            not song or (song[1] - song[0]) <= max(3000, 0.4 * played)
            or (out["disk_after"] and (song[1] - song[0]) < played)
            or (played < 3000 and rows[-1]["frame"] - song[1] < song[0]))):
        # the loop holds the whole production: a demo that starts over, or
        # one screen whose song comes round
        out["ending"] = "restarts" if out["reset_after"] or out["disk_after"] else "loops"
        if out["ending"] == "restarts":
            out["end"] = round(max(played, period) / FPS, 1)
        elif song and song[0] >= 0.6 * played:
            # When the song spans the whole production, use its period unless a
            # longer full-screen video loop was observed for a full second pass
            # AND confirmed by a sequential scrolltext stream (avoids inflating
            # short tunes with LCM/rational-convergent animation periods like
            # 9384 or 18525).
            if vp and vp > song[0] and (n - vshown) >= vp and text_data and text_data >= vp - 500:
                out["end"] = round(max(played, vp) / FPS, 1)
            else:
                out["end"] = round(max(played, song[0]) / FPS, 1)
        else:
            # Ignore an unconfirmed long video_period (less than half a second
            # pass observed) when a real song loop already exists (e.g. 9384).
            if vp and song and (n - vshown) < vp // 2:
                out["end"] = round(max(played, song[0]) / FPS, 1)
            else:
                shown = rows[vshown]["frame"] if vp else 0
                out["end"] = round(max(played, period, shown) / FPS, 1)
    elif period:
        out["ending"] = "end-loop"
        out["end_part"] = sec(new)
        # If both the final video loop started AND the music died well before
        # a tiny stray late code burst (e.g. Eon), cap at max(vshown, over).
        if (vp and out["music_over"] and not song and not out["disk_after"]
                and rows[vshown]["frame"] < played and rows[over]["frame"] < played):
            tail_after = max(vshown, over) + 250
            late_ram = sum((rows[i]["newram"] or 0) for i in range(min(tail_after, n), n))
            if late_ram < 50:
                out["end"] = round(max(rows[vshown]["frame"], rows[over]["frame"]) / FPS, 1)
                done = None
            else:
                done = [rows[vshown]["frame"]]
        else:
            done = [rows[vshown]["frame"]] if vp else []
        if done is not None:
            # all shown once: the picture through its loop, the song into its
            # second pass, or one landmark period into the end part
            done += [song[1]] if song else []
            done += [played + lp] if lp else []
            out["end"] = round(max(done + [played]) / FPS, 1)
    else:
        out["ending"] = "open"
        out["end_part"] = sec(new)
        if out["music_over"]:
            out["end"] = max(out["music_over"], out["last_new"])
        elif data is not None and rows[new]["frame"] < data < rows[-1]["frame"] - 1500:
            # No video or song loop, and a data stream (scroller/script) ran
            # past the last new code and finished well before the trace ended.
            out["end"] = round(data / FPS, 1)
        elif not out["sound"] and not out["disk_after"] and n - new >= HELD:
            # one silent screen that moves for good, nothing new for as long
            # as it is given: it has no end of its own, so it gets a default
            out["ending"] = "held"
            out["end"] = max(round(HELD / FPS, 1), out["last_new"])
    if data is not None and data > 0:
        out["last_data"] = round(data / FPS, 1)
    # If the screen went completely still (all cells still) well before the
    # trace ended while music kept looping, the visuals ran until ``still``.
    if (out.get("ending") in ("loops", "end-loop")
            and out["cells"]["still"] == cells.shape[1]
            and len(moved) >= SHOWN and still < n - 1500 and "end" in out):
        still_s = sec(still)
        if still_s > out["end"]:
            out["end"] = still_s
    if text_data is not None and text_data > 0:
        td_s = round(text_data / FPS, 1)
        out["text_end"] = td_s
        # Classic scrolltext intro/demo: song loops while a sequential byte/word
        # text stream keeps feeding non-looping (open or noisy) screen cells,
        # OR all cells eventually looped and video_shown corroborates text_end.
        vis_confirmed = (
            kinds_open(kinds) > 0
            or (vp and abs(rows[vshown]["frame"] - text_data) <= 750)
        )
        if (out.get("ending") in ("loops", "end-loop")
                and vis_confirmed and "end" in out):
            if td_s > out["end"]:
                out["end"] = td_s
            if td_s >= out["trace"] - 15:
                out["text_after_trace"] = True
    # the script's disk swaps say how long the production is: the swap that
    # the trace never reached means it runs longer than the trace; an end
    # before the last swap that was made is not the end
    if swaps:
        out["swaps"] = list(swaps)
        if swaps[-1] > out["trace"]:
            out["swap_after_trace"] = True
        elif "end" in out and out["end"] < swaps[-1]:
            out["end_before_swap"] = True
    # how sure: the trace must run on well past the last new code
    out["after"] = round((n - new) / FPS)
    return out


def song_of(trace, trace_end=None):
    notes = trace + ".notes"
    return song_loop(notes, trace_end=trace_end) if os.path.exists(notes) else None


def data_of(trace):
    return stream_end(trace + ".reads")


def data_ends_of(trace):
    return stream_ends(trace + ".reads")


def meta_of(trace):
    p = os.path.join(os.path.dirname(trace), "meta.json")
    return json.load(open(p)) if os.path.exists(p) else None


def halted_of(trace):
    """Did the CPU halt in the run? The emulator says so in the run's output."""
    log = os.path.join(os.path.dirname(trace), "stdout.log")
    return os.path.exists(log) and '"event":"halt"' in open(log).read()


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

    meta = meta_of(a.trace)
    swaps = meta.get("swaps", ()) if meta else ()
    trace_end = rows[-1]["frame"] if rows else None

    if a.json:
        data, text_data = data_ends_of(a.trace)
        print(json.dumps(verdict(rows, cells, song_of(a.trace, trace_end),
                                 halted_of(a.trace), data, swaps, meta,
                                 notes_path=a.trace + ".notes",
                                 text_data=text_data)))
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
    data, text_data = data_ends_of(a.trace)
    print("  VERDICT:", json.dumps(verdict(rows, cells, song_of(a.trace, trace_end),
                                           halted_of(a.trace), data, swaps, meta,
                                           notes_path=a.trace + ".notes",
                                           text_data=text_data)))
    tail = range(max(0, n - 1000), n)
    ins = sum(rows[i]["instr"] for i in tail) or 1
    print(f"  ROM share of the last 1000 frames: {sum(rows[i]['rom'] for i in tail) / ins:.0%}; resets {rows[-1]['resets']}")


if __name__ == "__main__":
    main()
