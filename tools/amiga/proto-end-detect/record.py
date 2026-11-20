#!/usr/bin/env python3
"""PROTOTYPE (throwaway): record a per-frame trace of one Amiga production.

    python3 amiga/proto-end-detect/record.py 142 --frames 60000 [--save-at 30000]
    python3 amiga/proto-end-detect/record.py 142 --frames 8000 --state 30000

Run from tools/. Plays the data-file entry (machine, disks, swaps) with the
emulator's `trace` command on; the trace lands in $OUT/<id>/trace.csv
(`--state F`: trace-from-F.csv, restored from the state saved at frame F).
Question: which signals say a demo has ended, and when its end part began?
"""
import argparse, os, pathlib, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scenemeta.amiga import config, emulator, player, replay   # noqa: E402
from scenemeta.core.errors import CannotPlay                   # noqa: E402
from scenemeta.core.export import default_machine              # noqa: E402

OUT = pathlib.Path(os.environ.get("PROTO_OUT", "/tmp/proto-end-detect"))


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
    out = OUT / str(a.prod)
    out.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.rmtree(out / "hd", ignore_errors=True)
    text, swaps = emulator._uae_config(machine, v, out, e.get("drives", 1))
    text = text.replace("sound_output=none", f"sound_output={a.sound}")
    (out / "machine.uae").write_text(text)

    start = a.state or 0
    trace = out / (f"trace-from-{start}.csv" if start else "trace.csv")
    # (frame, command) relative to power-on
    acts = [(f, f"disk insert 0 {swaps[arg]}" if what == "insert"
             else f"input mouse click {arg}")
            for f, what, arg in player.actions(e)]
    acts += [(f, f"state save {out / f'state-{f}.uss'}") for f in a.save_at]
    acts += [(f, f"screenshot {out / f'shot-{f}.png'}") for f in a.shots]
    acts = sorted(x for x in acts if x[0] > start)
    cmds, at = ["warp on", "disk autoswap off", f"trace {trace}"], start
    end = start + a.frames
    for f, c in acts:
        if f >= end:
            break
        cmds += [f"run frames={f - at}", c]
        at = f
    cmds += [f"run frames={end - at}", f"screenshot {out / f'end-{end}.png'}"]
    argv = [str(config.AMIBERRY), "-f", str(out / "machine.uae")]
    if start:
        argv += ["--statefile", str(out / f"state-{start}.uss")]
    for c in cmds:
        argv += ["--dbg", c]
    t = time.time()
    so, se, rc, to = emulator._invoke(argv, out, 3600)
    (out / "stdout.log").write_text(so)
    (out / "stderr.log").write_text(se[-20000:])
    n = sum(1 for _ in open(trace)) - 1
    print(f"{a.prod} {e['title']}: {machine.name} {v.label}; rc={rc} "
          f"{n} frames in {time.time() - t:.0f}s -> {trace}")


if __name__ == "__main__":
    main()
