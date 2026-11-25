#!/usr/bin/env python3
"""PROTOTYPE (throwaway): record a per-frame trace of one Amiga production.

    python3 amiga/proto-end-detect/record.py 142 --frames 60000 [--save-at 30000]
    python3 amiga/proto-end-detect/record.py 142 --frames 8000 --state 30000

Run from tools/. Plays the data-file entry (machine, disks, events) with the
emulator's `trace` command on; the trace lands in $OUT/<id>/trace.csv
(`--state F`: trace-from-F.csv, restored from the state saved at frame F).
Question: which signals say a demo has ended, and when its end part began?
"""
import argparse, json, os, pathlib, shutil, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scenemeta.amiga import alertshot, config, emulator, player, replay   # noqa: E402
from scenemeta.core.errors import CannotPlay                              # noqa: E402
from scenemeta.core.export import default_machine                         # noqa: E402

OUT = pathlib.Path(os.environ.get("PROTO_OUT", "/tmp/proto-end-detect"))


def _build_commands(acts, start, end, trace, out):
    """Build --dbg commands for actions at frames > start and < end."""
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
    cmds.append(f"screenshot {out / f'end-{end}.png'}")
    return cmds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prod", type=int)
    ap.add_argument("--frames", type=int, default=45000)
    ap.add_argument("--save-at", type=int, nargs="*", default=[])
    ap.add_argument("--shots", type=int, nargs="*", default=[],
                    help="frames to take a screenshot at (shot-<frame>.png)")
    ap.add_argument("--state", type=int, help="restore the state saved at this frame")
    ap.add_argument("--machine")
    ap.add_argument("--sound", default="interrupts")
    ap.add_argument("--seed", type=int, default=emulator.DEFAULT_SEED)
    ap.add_argument("--patient", action="store_true")
    a = ap.parse_args()

    e = replay.all_entries(config.DATA_DIR).get(a.prod)
    if not e:
        sys.exit(f"{a.prod}: not in data/amiga")
    if a.machine:
        e = dict(e, machine=a.machine)
    try:
        ready = player.ready(a.prod, e, default_machine(config.DATA_DIR))
    except CannotPlay as err:
        sys.exit(f"{a.prod} {e['title']}: {err}")
    machine, v = ready.machine, ready.variant
    os_cop = emulator.system_copper(machine, v.kind)
    out = OUT / str(a.prod)
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "hd", ignore_errors=True)
    text, swaps = emulator._uae_config(machine, v, out, e.get("drives", 1), a.seed)
    text = text.replace("sound_output=none", f"sound_output={a.sound}")
    (out / "machine.uae").write_text(text)

    start = a.state or 0
    trace = out / (f"trace-from-{start}.csv" if start else "trace.csv")
    # (frame, kind, arg) relative to power-on
    acts = []
    for f, what, arg in player.actions(e, patient=a.patient):
        if what == "insert":
            k, unit = arg
            acts.append((f, "cmd", f"disk insert {unit} {swaps[k]}"))
        else:
            acts.append((f, "press", arg))
    acts += [(f, "cmd", f"state save {out / f'state-{f}.uss'}") for f in a.save_at]
    acts += [(f, "cmd", f"screenshot {out / f'shot-{f}.png'}") for f in a.shots]
    end = start + a.frames
    cmds = _build_commands(acts, start, end, trace, out)

    argv = [str(config.AMIBERRY), "-f", str(out / "machine.uae")]
    if start:
        argv += ["--statefile", str(out / f"state-{start}.uss")]
    for c in cmds:
        argv += ["--dbg", c]
    t = time.time()
    so, se, rc, to = emulator._invoke(argv, out, 3600)
    (out / "stdout.log").write_text(so)
    (out / "stderr.log").write_text(se[-20000:])
    end_png = out / f"end-{end}.png"
    end_box = ""
    if end_png.exists() and end_png.stat().st_size <= emulator.BOX_MAX_PNG:
        end_box = alertshot.box(end_png.read_bytes())
    meta = {
        "prod": a.prod,
        "title": e["title"],
        "machine": machine.name,
        "variant": v.label,
        "os_cop": os_cop,
        "rc": rc,
        "timed_out": to,
        "end_box": end_box,
        "swaps": [ev["at"] for ev in e.get("events", []) if "disk" in ev],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    n = sum(1 for _ in open(trace)) - 1 if trace.exists() else 0
    print(f"{a.prod} {e['title']}: {machine.name} {v.label}; rc={rc} "
          f"{n} frames in {time.time() - t:.0f}s -> {trace}")


if __name__ == "__main__":
    main()
