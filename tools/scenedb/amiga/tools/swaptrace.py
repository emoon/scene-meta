#!/usr/bin/env python3
"""Trace the swap-wait detector on multi-disk variants, for diagnosing sets
that never reach their last disk.

    python3 -m scenedb.amiga.tools.swaptrace --db work/multi.db --out work/trace --jobs 20 [IDS...]

Per production: <out>/<id>/trace.txt (status + detector state every 250
frames, events) and a screenshot every 2000 frames. Runs on the machine the
sweep chose, with autoswap armed exactly as the sweep arms it.
"""

import argparse
import concurrent.futures as cf
import json
import pathlib
import sqlite3
import subprocess
import tempfile

from .. import config, emulator, machines, media


def trace(job):
    pid, machine, disks, frames, out, extra = job
    out = pathlib.Path(out).resolve() / str(pid)
    out.mkdir(parents=True, exist_ok=True)
    m = machines.BY_NAME[machine]
    v = media.Variant("floppy", disks)
    with tempfile.TemporaryDirectory(prefix="swaptrace-") as t:
        tmp = pathlib.Path(t)
        text, swaps = emulator._uae_config(m, v, tmp)
        (tmp / "m.uae").write_text(text)
        cmds = ["warp on", f"disk autoswap click idle={emulator.AUTOSWAP_IDLE_SECONDS} {extra}".strip()]
        for i in range(frames // 250):
            cmds += ["run frames=250", "status", "disk autoswap status"]
            if i % 8 == 7:
                cmds.append(f"screenshot {out / f'{(i + 1) * 250:06d}.png'}")
        argv = [str(config.AMIBERRY), "-f", str(tmp / "m.uae")]
        argv += [f"-diskswapper={d}" for d in swaps]
        for c in cmds:
            argv += ["--dbg", c]
        stdout = emulator._invoke(argv, tmp, 60 + frames // 60)[0]
    lines = []
    for r in emulator._records(stdout):
        res = r.get("result") or {}
        if "event" in r:
            lines.append(f"EVENT {r['event']} frame={r.get('frame')} "
                         f"{pathlib.Path(r.get('inserted', '')).name}")
        elif r.get("cmd") == "status":
            st = (f"{res['frame']:6d} pc={res['pc']:>8} dmacon={res['dmacon']:04x} "
                  f"motor={res['motor']} cyl={res['cyl']:2d} "
                  f"df0={pathlib.Path(res.get('df0', '')).name}")
        elif r.get("cmd") == "disk autoswap status":
            lines.append(f"{st} polls={res.get('total_polls')} "
                         f"last_poll={res.get('last_poll')} last_dma={res.get('last_dma')} "
                         f"max_cyl={res.get('max_dma_cyl')} win={res.get('window_start')}")
    (out / "trace.txt").write_text("\n".join(lines) + "\n")
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", type=int, nargs="*")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--frames", type=int, default=60000)
    ap.add_argument("--machine", help="override the sweep's chosen machine")
    ap.add_argument("--extra", default="", help="extra autoswap tokens")
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    q = """select b.prod_id, b.machine, v.disks from best b join variant v
           on v.prod_id = b.prod_id and v.idx = b.variant where b.disk_count > 1"""
    jobs = [(pid, a.machine or m, json.loads(d), a.frames, a.out, a.extra)
            for pid, m, d in db.execute(q) if not a.ids or pid in a.ids]
    with cf.ProcessPoolExecutor(a.jobs) as pool:
        for pid in pool.map(trace, jobs):
            print("traced", pid, flush=True)


if __name__ == "__main__":
    main()
