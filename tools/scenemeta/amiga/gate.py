"""The gate over entries of the data files (``data/amiga``): the core's gate
says which runs to make of each and whether it passes (see core.gate); the
player makes them.
"""

import concurrent.futures as cf
import dataclasses
import os

from ..core import gate
from ..core.errors import CannotPlay
from ..core.export import default_machine
from . import config, player, replay


def _play(ready, run):
    """The record of ``run`` of the entry of ``ready``, as long as the
    longer of the entry and what is played of it. Raises CannotPlay when
    the emulator showed nothing."""
    changed = gate.as_played(ready.entry, run)
    frames = max(player.frames_of(e) for e in (ready.entry, changed))
    ran = dataclasses.replace(ready, entry=changed).play(seed=run.seed,
                                                         frames=frames)
    if ran.verdict.verdict == "error":
        raise CannotPlay(f"the emulator gave nothing: {ran.verdict.crash}")
    return ran.record


def _one(prod, entry, default, each=map):
    """The report line of one production, its runs made through ``each``
    (see core.gate.check). Raises CannotPlay when something it needs is
    missing, or the emulator showed nothing of a run."""
    ready = player.ready(prod, entry, default)
    said = gate.check(entry, lambda run: _play(ready, run), each)
    return f"{prod} {entry['title']}: {said}"


def run(ids, data=None, jobs=None, log=print):
    """Gate the productions ``ids``, ``jobs`` emulators at a time. Returns
    how many could not be played."""
    data = data or config.DATA_DIR
    default = default_machine(data)
    found = replay.all_entries(data)
    for p in sorted(set(ids) - set(found)):
        log(f"{p}: no entry in the data files")
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    todo = sorted((p, found[p]) for p in set(ids) & set(found))
    # The runs of every entry share one pool; an entry's thread only waits.
    with cf.ThreadPoolExecutor(jobs) as pool:
        return player.play_each(
            todo, lambda p, e: _one(p, e, default, pool.map), jobs, log)
