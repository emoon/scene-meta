#!/usr/bin/env python3
"""Watch one disk set boot: every sample prints cycles, C64 PC, drive VIA2
port B (motor/LED/stepper) and the screenshot hash. Disks are never swapped.

    tools/trace.py --out work/trace --seconds 60 disk1.d64 [disk2.d64 ...]
"""
import argparse
import hashlib
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from scenedb import machines, vice  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="pal_1541")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--step", type=float, default=0.25)
    ap.add_argument("--out", default="work/trace")
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scenedb-") as t:
        tmp = pathlib.Path(t)
        imgs = []
        for i, src in enumerate(a.images):
            dst = tmp / f"{i}.d64"
            shutil.copyfile(src, dst)
            imgs.append(dst)
        with vice.Vice(machines.BY_NAME[a.machine], imgs, tmp,
                       vice.free_port()) as v:
            end, n, prev = time.time() + a.seconds, 0, None
            while time.time() < end:
                cyc, _ = v.run_for(a.step)
                via = v.peek("8", 0x1c00)[0]
                shot = tmp / "s.png"
                v.screenshot(shot)
                h = hashlib.md5(shot.read_bytes()).hexdigest()[:6]
                if n % 8 == 0:
                    shutil.copyfile(shot, out / f"{n:04d}.png")
                print(f"{n:4d} cyc={cyc:>11} via2b={via:02x} "
                      f"shot={h}{'*' if h != prev else ' '}", flush=True)
                prev, n = h, n + 1


main()
