"""The gate over entries of the data files (``data/amiga``): the core's gate
says which runs to make of each and whether it passes (see core.gate); the
player makes them. What it saw is kept in the sweep's log, from which come
the summary and the entries to gate again (see core.gatelog).
"""

import concurrent.futures as cf
import dataclasses
import os

from ..core import gate, gatelog
from ..core.errors import CannotPlay
from ..core.export import default_machine
from . import config, media, player, replay


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
    """``(judgement, sha256)`` of one production: the gate's judgement, its
    runs made through ``each`` (see core.gate.check), and the SHA-256 of
    the download they were played from. Raises CannotPlay when something
    it needs is missing, or the emulator showed nothing of a run."""
    ready = player.ready(prod, entry, default)
    sha256 = media.download_sha256(prod)
    return gate.check(entry, lambda run: _play(ready, run), each), sha256


def each(todo, db, data, jobs=None):
    """Gate every ``(prod, entry)`` of ``todo``, entries of the data files
    ``data``, ``jobs`` emulators at a time. Yields of each, in order,
    ``(prod, True, judgement)``, what the gate saw then being in the store
    ``db``, or ``(prod, False, line)`` with the line that reports why it
    could not be played; nothing is stored of those."""
    default = default_machine(data)
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    # The runs of every entry share one pool; an entry's thread only waits.
    with cf.ThreadPoolExecutor(jobs) as pool:
        for prod, ok, got in player.each_played(
                todo, lambda p, e: _one(p, e, default, pool.map), jobs):
            if ok:
                got, sha256 = got
                db.put_gate(prod, got, sha256, player.VERSION)
            yield prod, ok, got


def run(ids, db, data=None, jobs=None, log=print):
    """Gate the productions ``ids`` (see ``each``): a line of each. Returns
    how many could not be played."""
    data = data or config.DATA_DIR
    found = replay.all_entries(data)
    for p in sorted(set(ids) - set(found)):
        log(f"{p}: no entry in the data files")
    todo = sorted((p, found[p]) for p in set(ids) & set(found))
    errors = 0
    for prod, ok, got in each(todo, db, data, jobs):
        errors += not ok
        log(f"{prod} {found[prod]['title']}: {got}" if ok else got, flush=True)
    return errors


def write_summary(db, path=None):
    """Write the counts of what the gate saw to the summary file."""
    path = path or config.GATE_SUMMARY
    path.write_text(gatelog.summary(db.gated()), "utf-8")
    return path


def stale(db, data=None, log=print):
    """A line of each entry to gate again: its download, or the player, is
    not the one the gate saw it with."""
    media.require_mirror()
    found = replay.all_entries(data or config.DATA_DIR)
    again = gatelog.stale([r for r in db.gated() if r.prod in found],
                          media.download_sha256, player.VERSION)
    for prod, why in again:
        log(f"{prod} {found[prod]['title']}: {why}")
