"""Record per-frame Amiberry traces, classify endings, and store results.

Supports two workflows:
- ``run(...)``: play entries from ``data/amiga`` via ``player.ready``, record
  per-frame traces (into a temporary directory, or ``--out DIR`` to keep and
  reuse them), run ``analyze_trace``, and persist verdicts into ``scene.db``.
- ``judge_dir(...)``: re-analyze an existing directory of ``<id>/trace.csv``
  recordings in parallel (optionally caching ``.songs.json`` and writing JSON).
"""

import json
import multiprocessing
import os
import pathlib
import shutil
import tempfile
import threading
import time

from ...core import gatelog
from ...core.export import default_machine
from .. import alertshot, config, emulator, player, replay
from . import analyze, notes

DEFAULT_FRAMES = 45000   # 15 minutes at 50 Hz PAL


def build_commands(acts, start, end, trace, out):
    """Build ``--dbg`` commands for actions at frames ``start < f < end``."""
    cmds, at = ["warp on", "disk autoswap off", f"trace {trace}"], start
    for f, kind, arg in sorted(acts, key=lambda x: x[0]):
        if f <= start:
            continue
        if f >= end:
            break
        if f > at:
            cmds.append(f"run frames={f - at}")
            at = f
        if kind == "cmd":
            cmds.append(arg)
        elif kind == "press":
            press, held = emulator._press(arg)
            cmds += press
            at += held
    if end > at:
        cmds.append(f"run frames={end - at}")
    cmds.append(f"screenshot {pathlib.Path(out) / f'end-{end}.png'}")
    return cmds


def is_recorded(prod_dir, frames):
    """True when ``prod_dir`` already holds a complete trace for ``frames``."""
    prod_dir = pathlib.Path(prod_dir)
    trace = prod_dir / "trace.csv"
    meta_path = prod_dir / "meta.json"
    if not trace.exists() or not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text("utf-8"))
    except (OSError, ValueError):
        return False
    if meta.get("rc") == 2:
        return True
    try:
        with open(trace, "rb") as f:
            return sum(1 for _ in f) > frames
    except OSError:
        return False


def record(prod, entry, default, out_dir, frames=DEFAULT_FRAMES,
           save_at=(), shots=(), state=None, sound="interrupts",
           seed=emulator.DEFAULT_SEED, patient=False):
    """Record a per-frame trace of ``entry`` into ``out_dir/<prod>/``.

    Returns ``(trace_path, meta)``. Raises ``CannotPlay`` when the entry or
    its media/ROM cannot be played.
    """
    ready = player.ready(prod, entry, default)
    machine, v = ready.machine, ready.variant
    os_cop = emulator.system_copper(machine, v.kind)
    out = pathlib.Path(out_dir) / str(prod)
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "hd", ignore_errors=True)
    text, swaps = emulator._uae_config(machine, v, out, entry.get("drives", 1), seed)
    text = text.replace("sound_output=none", f"sound_output={sound}")
    (out / "machine.uae").write_text(text)

    start = state or 0
    trace = out / (f"trace-from-{start}.csv" if start else "trace.csv")
    acts = []
    for f, what, arg in player.actions(entry, patient=patient):
        if what == "insert":
            k, unit = arg
            acts.append((f, "cmd", f"disk insert {unit} {swaps[k]}"))
        else:
            acts.append((f, "press", arg))
    acts += [(f, "cmd", f"state save {out / f'state-{f}.uss'}") for f in save_at]
    acts += [(f, "cmd", f"screenshot {out / f'shot-{f}.png'}") for f in shots]
    end = start + frames
    cmds = build_commands(acts, start, end, trace, out)

    argv = [str(config.AMIBERRY), "-f", str(out / "machine.uae")]
    if start:
        argv += ["--statefile", str(out / f"state-{start}.uss")]
    for c in cmds:
        argv += ["--dbg", c]
    so, se, rc, to = emulator._invoke(argv, out, 3600)
    (out / "stdout.log").write_text(so)
    (out / "stderr.log").write_text(se[-20000:])
    end_png = out / f"end-{end}.png"
    end_box = ""
    if end_png.exists() and end_png.stat().st_size <= emulator.BOX_MAX_PNG:
        end_box = alertshot.box(end_png.read_bytes())
    meta = {
        "prod": prod,
        "title": entry["title"],
        "machine": machine.name,
        "variant": v.label,
        "os_cop": os_cop,
        "rc": rc,
        "timed_out": to,
        "end_box": end_box,
        "swaps": [ev["at"] for ev in entry.get("events", []) if "disk" in ev],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return trace, meta


def detect(prod, entry, default, out_dir=None, frames=DEFAULT_FRAMES,
           patient=False, seed=emulator.DEFAULT_SEED):
    """Record (if needed) and analyze ``entry``, returning the verdict dict."""
    swaps = [ev["at"] for ev in entry.get("events", []) if "disk" in ev]
    if out_dir is not None:
        out_root = pathlib.Path(out_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        prod_dir = out_root / str(prod)
        if is_recorded(prod_dir, frames):
            trace = prod_dir / "trace.csv"
            meta = analyze.meta_of(str(trace))
        else:
            trace, meta = record(prod, entry, default, out_root,
                                 frames=frames, patient=patient, seed=seed)
        v = analyze.analyze_trace(str(trace), swaps=swaps, meta=meta)
    else:
        with tempfile.TemporaryDirectory(prefix=f"enddetect-{prod}-") as tmp:
            trace, meta = record(prod, entry, default, tmp,
                                 frames=frames, patient=patient, seed=seed)
            v = analyze.analyze_trace(str(trace), swaps=swaps, meta=meta)
    v["id"] = prod
    return v


def format_result(prod, title, v, elapsed=None):
    """One-line human-readable summary of an end-detection verdict."""
    ending = v.get("ending", "?")
    end = v.get("end")
    end_s = f" {end:.1f}s" if end is not None else ""
    flags = []
    if v.get("text_after_trace"):
        flags.append("text>trace")
    if v.get("swap_after_trace"):
        flags.append("swap>trace")
    if v.get("end_before_swap"):
        flags.append("end<swap")
    if v.get("alert"):
        flags.append(f"alert={v['alert']}")
    extra = f" [{', '.join(flags)}]" if flags else ""
    wall = f" ({elapsed:.0f}s)" if elapsed is not None else ""
    return f"{prod} {title}: {ending}{end_s}{extra}{wall}"


def run(db, ids=None, data=None, jobs=None, frames=DEFAULT_FRAMES,
        out=None, again=False, machine=None, patient=False, log=print):
    """Detect endings for entries in ``data/amiga`` and store in ``db``.

    Skips entries that do not play (``result`` set) unless explicitly named in
    ``ids``, and skips entries already stored in ``db`` for the same entry text
    unless ``again`` is True. Returns how many entries could not be played.
    """
    data = data or config.DATA_DIR
    found = replay.all_entries(data)
    for p in sorted(set(ids or ()) - set(found)):
        log(f"{p}: no entry in the data files", flush=True)
    existing = {} if again else db.endings()
    selected = sorted(p for p in (ids if ids is not None else found) if p in found)
    todo = []
    for p in selected:
        e = dict(found[p], machine=machine) if machine else found[p]
        if ids is None and e.get("result"):
            continue
        held = existing.get(p)
        if held and held[0] == gatelog.name(e):
            continue
        todo.append((p, e))
    if not todo:
        return 0
    default = default_machine(data)
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    lock = threading.Lock()

    def _one(prod, entry):
        t0 = time.time()
        v = detect(prod, entry, default, out_dir=out, frames=frames,
                   patient=patient)
        with lock:
            db.put_ending(prod, entry, v)
        return format_result(prod, entry["title"], v, time.time() - t0)

    return player.play_each(todo, _one, jobs, log)


# -- Batch re-analysis of an existing recording directory --------------------

_JUDGE_REC = None
_JUDGE_SWAPS = {}


def _trace_end(trace):
    """Last frame number in trace.csv without parsing the whole file."""
    try:
        with open(trace, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            lines = f.read().splitlines()
            for line in reversed(lines):
                if line and line[0:1].isdigit():
                    return int(line.split(b",", 1)[0])
    except (OSError, ValueError):
        pass
    return None


def _judge_song(i):
    t = f"{_JUDGE_REC}/{i}/trace.csv"
    p = t + ".notes"
    try:
        return i, (notes.song_loop(p, trace_end=_trace_end(t)) if os.path.exists(p) else None)
    except ValueError:  # a run killed mid-write ends on a cut line
        return i, None


def _judge_verdict(args):
    i, s = args
    t = f"{_JUDGE_REC}/{i}/trace.csv"
    try:
        v = analyze.analyze_trace(
            t,
            swaps=_JUDGE_SWAPS.get(int(i), ()),
            song=s and tuple(s),
            precomputed_song=True,
        )
    except Exception as e:  # one bad trace must not lose the batch
        return {"id": int(i), "ending": "error", "error": repr(e)}
    v["id"] = int(i)
    return v


def judge_dir(rec_dir, out_json=None, jobs=None, reuse_songs=False,
              data=None, log=print):
    """Run song matching and verdict analysis over every ``<id>/trace.csv`` in
    ``rec_dir``. Writes verdicts to ``out_json`` (and caches song loops in
    ``<out_json>.songs.json``) when ``out_json`` is provided. Returns the list
    of verdicts.
    """
    global _JUDGE_REC, _JUDGE_SWAPS
    rec_path = pathlib.Path(rec_dir)
    if not rec_path.is_dir():
        raise SystemExit(f"{rec_path}: no such directory")
    data = data or config.DATA_DIR
    entries = replay.all_entries(data)
    _JUDGE_REC = str(rec_path)
    _JUDGE_SWAPS = {
        pid: [ev["at"] for ev in e.get("events", []) if "disk" in ev]
        for pid, e in entries.items()
        if any("disk" in ev for ev in e.get("events", []))
    }
    ids = sorted(
        d for d in os.listdir(rec_path)
        if d.isdigit() and (rec_path / d / "trace.csv").exists()
    )
    workers = jobs or max(1, os.cpu_count() or 4)
    songs_file = (
        str(out_json).replace(".json", ".songs.json")
        if out_json and str(out_json).endswith(".json")
        else (f"{out_json}.songs.json" if out_json else None)
    )
    with multiprocessing.Pool(workers) as pool:
        if reuse_songs and songs_file and os.path.exists(songs_file):
            songs = json.load(open(songs_file))
        else:
            songs = dict(pool.imap_unordered(_judge_song, ids, chunksize=1))
            if songs_file:
                json.dump(songs, open(songs_file, "w"))
        log(f"songs done {len(songs)}", flush=True)
        out = list(pool.imap_unordered(_judge_verdict, songs.items(), chunksize=1))
    out.sort(key=lambda v: v.get("id", 0))
    if out_json:
        json.dump(out, open(out_json, "w"))
    log(f"verdicts done {len(out)}", flush=True)
    return out
