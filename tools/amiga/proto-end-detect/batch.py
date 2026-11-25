#!/usr/bin/env python3
"""PROTOTYPE (throwaway): record many productions, N at a time.

    PROTO_OUT=/tmp/batch python3 amiga/proto-end-detect/batch.py IDS.txt [--jobs 32] [--frames 45000]

Run from tools/. One production id per line. A production whose trace.csv
already has its last frame is skipped, so a killed batch can be rerun.
"""
import argparse, json, os, pathlib, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("PROTO_OUT", "/tmp/proto-end-detect"))


def finished(prod, frames):
    d = OUT / str(prod)
    t = d / "trace.csv"
    m = d / "meta.json"
    if not t.exists() or not m.exists():
        return False
    try:
        meta = json.loads(m.read_text())
    except (OSError, ValueError):
        return False
    if meta.get("rc") == 2:
        return True
    with open(t, "rb") as f:
        return sum(1 for _ in f) > frames


def record(prod, frames):
    if finished(prod, frames):
        return prod, "skip", 0
    t = time.time()
    r = subprocess.run([sys.executable, str(HERE / "record.py"), str(prod),
                        "--frames", str(frames)], capture_output=True, text=True)
    (OUT / str(prod)).mkdir(parents=True, exist_ok=True)
    (OUT / str(prod) / "batch.log").write_text(r.stdout + r.stderr[-5000:])
    return prod, "ok" if r.returncode == 0 and finished(prod, frames) else "FAIL", time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids")
    ap.add_argument("--jobs", type=int, default=32)
    ap.add_argument("--frames", type=int, default=45000)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    ids = [int(x) for x in open(a.ids).read().split()][:a.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        for i, (p, st, s) in enumerate(ex.map(lambda p: record(p, a.frames), ids), 1):
            print(f"{i}/{len(ids)} {p} {st} {s:.0f}s", flush=True)


if __name__ == "__main__":
    main()
