"""Record per-frame Amiberry traces, classify endings, and store results.

Supports two workflows:
- ``run(...)``: play entries from ``data/amiga`` via ``player.ready``, record
  per-frame traces (into a temporary directory, or ``--out DIR`` to keep and
  reuse them), run ``analyze_trace``, and persist verdicts into ``scene.db``.
- ``judge_dir(...)``: re-analyze an existing directory of ``<id>/trace.csv``
  recordings in parallel (optionally caching ``.songs.json`` and writing JSON).
"""

import dataclasses
import json
import multiprocessing
import os
import pathlib
import shutil
import tempfile
import threading
import time

from ...core import gatelog, result
from ...core.errors import CannotPlay
from ...core.export import default_machine
from .. import alertshot, area as areas, config, emulator, media, player, replay
from . import analyze, notes

DEFAULT_FRAMES = 45000   # 15 minutes at 50 Hz PAL
AREA_STEP = 1000         # sample display status every 20 s for drawn box


def build_commands(acts, start, end, trace, out, os_cop=None, area_step=0):
    """Build ``--dbg`` commands for actions at frames ``start < f < end``."""
    cmds, at = ["warp on", "disk autoswap off"], start
    if os_cop is not None:
        cmds.append(f"display measure on os={os_cop:x}")
    cmds.append(f"trace {trace}")
    all_acts = list(acts)
    if os_cop is not None and area_step > 0:
        all_acts += [(f, "cmd", "display status")
                     for f in range(start + area_step, end, area_step)]
    for f, kind, arg in sorted(all_acts, key=lambda x: x[0]):
        if f <= start:
            continue
        if f >= end:
            break
        if f > at:
            cmds.append(f"run frames={f - at}")
            at = f
        if kind == "cmd":
            cmds.append(arg)
        elif kind == "click":
            key, pos = arg
            press, held = emulator._press(key, pos=pos)
            cmds += press
            at += held
        elif kind == "press":
            press, held = emulator._press(arg)
            cmds += press
            at += held
    if end > at:
        cmds.append(f"run frames={end - at}")
    if os_cop is not None:
        cmds.append("display status")
    cmds.append(f"screenshot {pathlib.Path(out) / f'end-{end}.png'}")
    return cmds


def _measured_area(stdout):
    """Parse ``display status`` JSON records from ``stdout`` into result.Area."""
    display, boxes = None, []
    for rec in emulator._records(stdout):
        if rec.get("cmd") == "display status":
            res = rec.get("result") or {}
            if "modes" in res:
                display = res
                boxes.append(res.get("screen", {}).get("box"))
    found = areas.shown(display) if display else None
    if not found:
        return None
    size, scale = found
    return result.Area(*size, *areas.drawn([b for b in boxes if b], scale))


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
           seed=emulator.DEFAULT_SEED, patient=False, area=False):
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
    assign = tuple((entry.get("assign") or {}).items())
    text, disks = emulator._uae_config(
        machine, v, out, entry.get("drives", 1), seed, assign=assign)
    # Per-frame tracing forces the interpreter (dbgproto_instr_gate), which
    # hangs if JIT (cachesize/comp*) stays enabled in the UAE config.
    text = "\n".join(
        line for line in text.splitlines()
        if not line.startswith(("cachesize=", "comp"))
    ) + "\n"
    text = text.replace("sound_output=none", f"sound_output={sound}")
    (out / "machine.uae").write_text(text)

    start = state or 0
    trace = out / (f"trace-from-{start}.csv" if start else "trace.csv")
    acts = []
    for f, what, arg in player.actions(entry, patient=patient):
        if what == "insert":
            k, unit = arg
            acts.append((f, "cmd", f"disk insert {unit} {disks[k]}"))
        elif what == "click":
            acts.append((f, "click", arg))
        else:
            acts.append((f, "press", arg))
    acts += [(f, "cmd", f"state save {out / f'state-{f}.uss'}") for f in save_at]
    acts += [(f, "cmd", f"screenshot {out / f'shot-{f}.png'}") for f in shots]
    end = start + frames
    if not start and acts:
        end = max(end, max(f for f, _, _ in acts) + player.TAIL_FRAMES)
    cmds = build_commands(
        acts, start, end, trace, out,
        os_cop=os_cop if area else None,
        area_step=AREA_STEP if area else 0,
    )

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
    measured = _measured_area(so) if area else None
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
    if measured is not None:
        meta["area"] = dataclasses.asdict(measured)
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return trace, meta


def detect(prod, entry, default, out_dir=None, frames=DEFAULT_FRAMES,
           patient=False, seed=emulator.DEFAULT_SEED, area=False):
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
                                 frames=frames, patient=patient, seed=seed,
                                 area=area)
        v = analyze.analyze_trace(str(trace), swaps=swaps, meta=meta)
    else:
        with tempfile.TemporaryDirectory(prefix=f"enddetect-{prod}-") as tmp:
            trace, meta = record(prod, entry, default, tmp,
                                 frames=frames, patient=patient, seed=seed,
                                 area=area)
            v = analyze.analyze_trace(str(trace), swaps=swaps, meta=meta)
    v["id"] = prod
    if meta.get("area"):
        v["area"] = meta["area"]
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
    a = v.get("area")
    area_s = f"; area {a['width']}x{a['height']}" if a else ""
    wall = f" ({elapsed:.0f}s)" if elapsed is not None else ""
    return f"{prod} {title}: {ending}{end_s}{extra}{area_s}{wall}"


def run(db, ids=None, data=None, jobs=None, frames=DEFAULT_FRAMES,
        out=None, again=False, machine=None, patient=False, area=False,
        log=print):
    """Detect endings for entries in ``data/amiga`` and store in ``db``.

    Skips entries that do not play (``result`` set) unless explicitly named in
    ``ids``, and skips entries already stored in ``db`` for the same entry text
    unless ``again`` is True (or ``area`` is requested and missing). Returns
    how many entries could not be played.
    """
    data = data or config.DATA_DIR
    found = replay.all_entries(data)
    for p in sorted(set(ids or ()) - set(found)):
        log(f"{p}: no entry in the data files", flush=True)
    existing = {} if again else db.endings()
    existing_areas = {} if (again or not area) else db.areas()
    selected = sorted(p for p in (ids if ids is not None else found) if p in found)
    todo = []
    for p in selected:
        e = dict(found[p], machine=machine) if machine else found[p]
        if ids is None and e.get("result"):
            continue
        name = gatelog.name(e)
        held = existing.get(p)
        has_end = bool(held and held[0] == name)
        has_area = (not area) or (
            existing_areas.get(p) is not None and existing_areas[p][0] == name)
        if has_end and has_area:
            continue
        todo.append((p, e))
    if not todo:
        return 0
    default = default_machine(data)
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    entries = dict(todo)

    def _one(prod, entry):
        t0 = time.time()
        try:
            v = detect(prod, entry, default, out_dir=out, frames=frames,
                       patient=patient, area=area)
            sha256 = media.download_sha256(prod) if (area and v.get("area")) else None
            return v, sha256, time.time() - t0
        except CannotPlay:
            raise
        except Exception as e:
            raise CannotPlay(f"{type(e).__name__}: {e}") from e

    errors = 0
    for prod, ok, got in player.each_played(todo, _one, jobs):
        if not ok:
            errors += 1
            log(got, flush=True)
            continue
        v, sha256, elapsed = got
        entry = entries[prod]
        db.put_ending(prod, entry, v)
        if area and v.get("area"):
            db.put_area(prod, entry, result.Area(**v["area"]),
                        sha256, player.VERSION)
        log(format_result(prod, entry["title"], v, elapsed), flush=True)
    return errors


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
