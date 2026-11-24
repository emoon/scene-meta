"""From the sweep's log into the shared data files (``data/<platform>``, see
docs/DESIGN.md).

The core reads what the sweep chose for each variant and merges the
platform's entries into the files; what an entry says is the platform's
part. The merge replaces only ``script`` entries, so whatever somebody
edited in the data files stays.

A ``script`` entry that says the production runs is written only when it
passed the gate (docs/DESIGN.md, Provenance): the platform puts its
``tries`` to its gate, best first, and writes the first that passes.
"""

import dataclasses
import json
import sys

from .. import machines, merge


TRIES = 3    # the entries of one production put to the gate


# Seconds from an insert to the key that has it taken, where a sweep did not
# keep when the key went down.
KEY_DELAY = 5.0


@dataclasses.dataclass
class Variant:
    """A finished variant and one run of it."""
    idx: int
    kind: str
    disks: list
    note: str
    detail: dict        # the platform's own
    machine: str
    verdict: str
    drives: int
    reached: int
    swaps: list         # the result.Swap the run's production used
    keys: list = dataclasses.field(default_factory=list)  # presses with no swap
    chosen: bool = True  # the run is the one the sweep chose of the variant


def variants(store, every=False):
    """``{prod_id: [Variant]}``, each list in the order the media gave: the
    chosen run of each variant, or with ``every`` each of its runs, in the
    order they were made."""
    out = {}
    runs = "r.variant_id = v.id" if every else "r.id = v.best_run_id"
    # Of the chosen run, what the variant says it was chosen as.
    chosen = "case when r.id is v.best_run_id then v.best_{0} else r.{0} end"
    for prod, idx, kind, disks, note, detail, best, machine, verdict, run, \
            drives, reached in store.db.execute(
                "select v.prod_id, v.idx, v.kind, v.disks, v.note, v.detail,"
                f" v.best_run_id, {chosen.format('machine')},"
                f" {chosen.format('verdict')}, r.id, r.drives, r.disks_reached"
                f" from variant v left join run r on {runs}"
                " where v.done_at is not null"
                " order by v.prod_id, v.idx, r.id").fetchall():
        swaps = [s for s in store.swaps(run) if s.accepted] if run else []
        out.setdefault(prod, []).append(Variant(
            idx, kind, json.loads(disks or "[]"), note or "",
            json.loads(detail or "{}"), machine, verdict, drives or 1,
            reached or 0, swaps, store.keys(run) if run else [],
            run == best))
    return out


def tries(entries):
    """The entries to put to the gate, of one production's ``entries`` best
    first: the first TRIES that differ in what they set."""
    out = []
    for entry in entries:
        if all(merge.settings(entry) != merge.settings(o) for o in out):
            out.append(entry)
    return out[:TRIES]


def productions(store, every=False):
    """``(id, title, groups, [Variant])`` of every production with a
    finished variant, by id (see ``variants``)."""
    found = variants(store, every)
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
