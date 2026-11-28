"""Plays entries of the data files (``data/amiga``, see docs/DESIGN.md) exactly as
written, through the player, and says whether every disk was loaded.

An entry with keys is played a second time without them: a key is needed only when the production does not run without it.
"""

import os

from ..core.entries import all_entries

from ..core.export import default_machine
from . import config, player


def judge(written, plain):
    """What two runs say about an entry: ``written`` and ``plain`` are the
    disks loaded of the run as written and of the run without the keys (None
    when the entry has no keys)."""
    if plain is not None and all(plain):
        return "keys not needed"
    if not all(written):
        return "does not replay"
    return "replays" if plain is None else "keys needed"


def entries(data):
    """``{id: entry}`` of the Demozoo productions that have events."""
    return {p: e for p, e in all_entries(data).items() if e.get("events")}


def _has_keys(entry):
    return any("key" in e for e in entry.get("events", []))


def _one(prod, entry, default, patient=False):
    """The report line of one production. Raises CannotPlay when something
    it needs is missing."""
    ready = player.ready(prod, entry, default)
    runs = [("patient" if patient else "as written",
             ready.play(patient=patient))]
    if _has_keys(entry):
        runs.append(("without keys", ready.play(keys=False, patient=patient)))
    # With no disk to put in, the run itself is the evidence.
    got = [(name, o.verdict.verdict, o.loaded or [o.verdict.works])
           for name, o in runs]
    said = judge(got[0][2], got[1][2] if len(got) > 1 else None)
    detail = "; ".join(
        f"{name}: {v}, disks loaded " + "".join("y" if ok else "n" for ok in ld)
        for name, v, ld in got)
    return f"{prod} {entry['title']}: {said} ({detail})"


def run(ids=None, data=None, jobs=None, log=print, patient=False):
    """Replay the productions ``ids``; without ids, every entry that has a
    key. ``patient``: see events.patient. Returns how many could not be
    played."""
    data = data or config.DATA_DIR
    default = default_machine(data)
    found = entries(data)
    todo = {p: e for p, e in found.items()
            if (p in ids if ids else _has_keys(e))}
    for p in sorted(set(ids or ()) - set(found)):
        log(f"{p}: no entry with events")
    # Two emulators per production, each about two cores.
    jobs = jobs or max(1, (os.cpu_count() or 4) // 4)
    return player.play_each(sorted(todo.items()),
                            lambda p, e: _one(p, e, default, patient),
                            jobs, log)
