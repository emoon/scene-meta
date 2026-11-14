"""From the sweep's log into the shared data files (``data/<platform>``, see
docs/DESIGN.md).

The core reads what the sweep chose for each variant and merges the
platform's entries into the files; what an entry says is the platform's
part. The merge replaces only ``script`` entries, so whatever somebody
edited in the data files stays.
"""

import dataclasses
import json
import sys

from .. import machines, merge


@dataclasses.dataclass
class Variant:
    """A finished variant and its chosen run."""
    idx: int
    kind: str
    disks: list
    note: str
    detail: dict        # the platform's own
    machine: str
    verdict: str
    drives: int
    reached: int
    swaps: list         # the result.Swap the chosen run's production used


def variants(store):
    """``{prod_id: [Variant]}``, each list in the order the media gave."""
    out = {}
    for prod, idx, kind, disks, note, detail, machine, verdict, run, drives, \
            reached in store.db.execute(
                "select v.prod_id, v.idx, v.kind, v.disks, v.note, v.detail,"
                " v.best_machine, v.best_verdict, r.id, r.drives, r.disks_reached"
                " from variant v left join run r on r.id = v.best_run_id"
                " where v.done_at is not null order by v.prod_id, v.idx").fetchall():
        swaps = [s for s in store.swaps(run) if s.accepted] if run else []
        out.setdefault(prod, []).append(Variant(
            idx, kind, json.loads(disks or "[]"), note or "",
            json.loads(detail or "{}"), machine, verdict, drives or 1,
            reached or 0, swaps))
    return out


def productions(store):
    """``(id, title, groups, [Variant])`` of every production with a
    finished variant, by id."""
    found = variants(store)
    for prod, title, groups in store.db.execute(
            "select id, title, groups from production order by id").fetchall():
        if prod in found:
            yield prod, title, groups, found[prod]


def presets(data):
    """``(default, presets)`` of the platform's machines.toml, or exit when
    the file is broken."""
    default, found, problems = machines.load(data / machines.FILE)
    if problems:
        sys.exit(f"{data / machines.FILE}: {problems[0]}")
    return default, found


def default_machine(data):
    """The platform's default preset, or exit when its file is broken."""
    return presets(data)[0]


def run(data, entries):
    """Merge ``entries`` (``(namespace, id, entry)`` triples) into the data
    files in ``data`` and print what changed."""
    report = merge.merge(data, entries)
    print(f"{report.added} added, {report.replaced} replaced, {report.kept} kept"
          f" as edited; {report.files} files written")
    for line in report.disagreements:
        print("differs:", line)
