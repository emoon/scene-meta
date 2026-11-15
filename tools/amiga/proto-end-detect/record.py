#!/usr/bin/env python3
"""PROTOTYPE (throwaway): record a per-frame trace of one Amiga production.

    python3 amiga/proto-end-detect/record.py 142 --frames 60000 [--save-at 30000]
    python3 amiga/proto-end-detect/record.py 142 --frames 8000 --state 30000

Run from tools/. Plays the data-file entry (machine, disks, swaps) with the
emulator's `trace` command on; the trace lands in $OUT/<id>/trace.csv
(`--state F`: trace-from-F.csv, restored from the state saved at frame F).
Question: which signals say a demo has ended, and when its end part began?
"""
import argparse, os, pathlib, sys, tomllib, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from scenemeta.amiga import config, emulator, machines, media  # noqa: E402
from scenemeta.core.export import default_machine              # noqa: E402

OUT = pathlib.Path(os.environ.get("PROTO_OUT", "/tmp/proto-end-detect"))


def entry_of(prod):
    for path in config.DATA_DIR.glob("*.toml"):
        e = tomllib.loads(path.read_text("utf-8")).get("demozoo", {}).get(str(prod))
        if e:
            return e
    sys.exit(f"{prod}: not in data/amiga")


def variant_of(prod, e):
    vs = media.variants(prod, e["title"])[0]
    for v in vs:
        if e.get("disks") and v.kind == "floppy" and \
                [os.path.basename(d) for d in v.disks] == e["disks"]:
            return v
        if e.get("run") and v.kind == "hd" and (v.command or "").strip() == e["run"]:
            return v
    if not vs:
        sys.exit(f"{prod}: no media")
    return vs[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prod", type=int)
    ap.add_argument("--frames", type=int, default=45000)
    ap.add_argument("--save-at", type=int, nargs="*", default=[])
    ap.add_argument("--state", type=int, help="restore the state saved at this frame")
    ap.add_argument("--machine")
    ap.add_argument("--variant", type=int, help="index into media.variants")
    ap.add_argument("--sound", default="interrupts")
    a = ap.parse_args()

    e = entry_of(a.prod)
    machine = machines.BY_NAME[a.machine or e.get("machine", default_machine(config.DATA_DIR))]
    v = (media.variants(a.prod, e["title"])[0][a.variant]
         if a.variant is not None else variant_of(a.prod, e))
    out = OUT / str(a.prod)
    out.mkdir(parents=True, exist_ok=True)
    text, swaps = emulator._uae_config(machine, v, out, e.get("drives", 1))
    text = text.replace("sound_output=none", f"sound_output={a.sound}")
    (out / "machine.uae").write_text(text)

    start = a.state or 0
    trace = out / (f"trace-from-{start}.csv" if start else "trace.csv")
    first = e.get("drives", 1) + 1
    # (frame, command) relative to power-on
    acts = [(round(s["at"] * machines.FPS), f"disk insert 0 {swaps[s['disk'] - first]}")
            for s in e.get("swaps", [])]
    for s in e.get("swaps", []):
        if s.get("key") == "lmb":
            acts.append((round((s["at"] + s.get("key_delay", 5.0)) * machines.FPS),
                         "input mouse click 0"))
    acts += [(f, f"state save {out / f'state-{f}.uss'}") for f in a.save_at]
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
