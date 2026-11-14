#!/usr/bin/env python3
"""Run one production's media and print the verdict and flips."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from scenedb import catalog, machines, media, runner, sweep, verdict  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("id", type=int)
ap.add_argument("--machine", default="pal_1541")
ap.add_argument("--minutes", type=float, default=10)
ap.add_argument("--shots", default=None)
ap.add_argument("--boot", action="store_true", help="boot the file matching the title")
a = ap.parse_args()
prod = catalog.productions({a.id})[0]
vs, problems = media.variants(prod)
if a.boot:
    sweep.choose_boot(prod, vs[0])
print(prod.title, [d.rsplit("/", 1)[-1] for d in vs[0].disks] if vs else problems,
      (vs[0].boot_disk + 1, vs[0].boot_file) if vs else "")
log = runner.run(machines.BY_NAME[a.machine], vs[0], int(a.minutes * 60 * 985_248))
v = verdict.classify(log.samples, log.basic, log.crash, log.crash_cycles, log.wants_disk)
print(v)
print("asked for a disk at", f"{log.asked_disk / 985248:.0f}s" if log.asked_disk else None)
if log.detail:
    print("emulator log tail:", log.detail[-400:])
if a.shots:
    p = pathlib.Path(a.shots); p.mkdir(parents=True, exist_ok=True)
    (p / f"{prod.id}-last.png").write_bytes(log.last_shot)
for f in log.flips:
    print(f"  flip -> disk {f.disk} {f.trigger} waiting_since={f.waiting_since/985248:.0f}s "
          f"inserted={f.inserted/985248:.0f}s accepted={f.accepted}")
    if a.shots:
        p = pathlib.Path(a.shots); p.mkdir(parents=True, exist_ok=True)
        (p / f"{prod.id}-disk{f.disk}.png").write_bytes(f.shot)
