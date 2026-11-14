"""Writes the sweep's results into the shared data files (``data/amiga``,
see DESIGN.md at the top of the repo): one entry per production, from the
variant that got furthest.

A production the sweep found is ``script``; one with a hand classification
(classes.tsv) is ``ai``. The merge replaces only ``script`` entries, so
whatever somebody edited in the data files stays.
"""

import dataclasses
import json
import os
import sys

from . import classes, config, media

sys.path.insert(0, str(config.COMMON))
from scenemeta import machines as presets, merge  # noqa: E402

FPS = 50   # PAL: the sweep's frames to the data files' seconds

_RUNS = ("works", "works-short")
_RESULT = {"works-then-crash": "crashes-later", "crash": "broken"}
_KIND = ("menu", "separate-disks")
_BROKEN = ("install-only", "crash", "broken-media")


@dataclasses.dataclass
class Variant:
    idx: int
    kind: str           # "floppy" | "hd"
    disks: list
    command: str
    note: str
    machine: str
    verdict: str
    drives: int
    reached: int
    swaps: list         # [(frame, disk, trigger)] of the best run

    @property
    def rank(self):
        """How far it got: runs, runs then crashes, does not run; then the
        share of its disks it reached; then the first one found."""
        running = 2 if self.verdict in _RUNS else self.verdict == "works-then-crash"
        share = self.reached / len(self.disks) if self.disks else 1
        return running, share, -self.idx


def _variants(db):
    """``{prod_id: [Variant]}``, each list in the order the media gave."""
    swaps = {}
    for run, frame, disk, trigger in db.execute(
            "select s.run_id, s.frame, s.disk, s.trigger from swap s"
            " join variant v on v.best_run_id = s.run_id order by s.run_id, s.seq"):
        swaps.setdefault(run, []).append((frame, disk, trigger))
    out = {}
    for prod, idx, kind, disks, command, note, machine, verdict, run, drives, reached \
            in db.execute(
                "select v.prod_id, v.idx, v.kind, v.disks, v.command, v.note,"
                " v.best_machine, v.best_verdict, r.id, r.drives, r.disks_reached"
                " from variant v left join run r on r.id = v.best_run_id"
                " where v.done_at is not null order by v.prod_id, v.idx"):
        out.setdefault(prod, []).append(Variant(
            idx, kind, json.loads(disks or "[]"), command or "", note or "",
            machine, verdict, drives or 1, reached or 0, swaps.get(run, [])))
    return out


def _run_file(v):
    """The file the variant starts, when the media left a choice."""
    def after(marker):
        return v.note.split(marker, 1)[1].split(" (")[0].strip()
    if media.LAUNCH_NOTE in v.note:          # "<volume>:<path>"
        return after(media.LAUNCH_NOTE).split(":", 1)[-1]
    if media.MERGED_NOTE in v.note:
        return after("; runs ").removeprefix("script ")
    if "executables, picked" in v.note and v.command.count("\n") == 1:
        return v.command.strip().strip('"')
    return None


def entry(title, groups, variants, cls, default):
    """The data-file entry of one production. ``cls``: its ``(kind, note)``
    of classes.tsv, or None."""
    kind, note = cls or (None, None)
    hd = [v for v in variants if v.kind == "hd"]
    v = max(hd if kind == "use-hd" and hd else variants, key=lambda v: v.rank)

    if kind in _BROKEN:
        result = "broken"
    elif v.verdict in _RUNS:
        result = None
    else:
        result = _RESULT.get(v.verdict, "unknown")
    runs = result in (None, "crashes-later")

    e = {"title": title}
    if groups:
        e["group"] = groups
    e["source"] = "ai" if cls else "script"
    if runs and v.machine != default:
        e["machine"] = v.machine
    if runs and v.drives > 1:
        e["drives"] = v.drives
    if v.kind != variants[0].kind:
        e["boot"] = v.kind
    if kind in _KIND:
        e["kind"] = kind
    if result:
        e["result"] = result
    if len(v.disks) > 1:
        e["disks"] = [os.path.basename(d) for d in v.disks]
    if runs and v.swaps:
        e["swaps"] = [{"disk": disk, "at": round(frame / FPS, 1),
                       **({"key": "lmb"} if "click" in trigger else {})}
                      for frame, disk, trigger in v.swaps]
    if run := _run_file(v):
        e["run"] = run
    if note:
        e["note"] = note
    elif runs and v.reached < len(v.disks):
        e["note"] = f"the sweep only reached disk {max(v.reached, 1)} of {len(v.disks)}"
    return e


def entries(db, cls, default):
    """``(namespace, id, entry)`` of every production with a finished
    variant."""
    variants = _variants(db)
    for prod, title, groups in db.execute(
            "select id, title, groups from production order by id"):
        if prod in variants:
            yield "demozoo", prod, entry(title, groups, variants[prod],
                                         cls.get(prod), default)


def run(db, data=None):
    data = data or config.DATA_DIR
    default, _, problems = presets.load(data / presets.FILE)
    if problems:
        sys.exit(f"{data / presets.FILE}: {problems[0]}")
    report = merge.merge(data, entries(db.db, classes.load(), default))
    print(f"{report.added} added, {report.replaced} replaced, {report.kept} kept"
          f" as edited; {report.files} files written")
    for line in report.disagreements:
        print("differs:", line)
