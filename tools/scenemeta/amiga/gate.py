"""The gate over entries of the data files (``data/amiga``): the core's gate
says which runs to make of each and whether it passes (see core.gate); the
player makes them. What it saw is kept in the sweep's log, from which come
the summary and the entries to gate again (see core.gatelog), and the
entries a pass over all of them demotes (see core.demote).

``first`` is the gate of the export: of the entries a production may be
written as, the first that passes.
"""

import concurrent.futures as cf
import dataclasses
import os

from ..core import demote as core_demote
from ..core import export, gate, gatelog
from ..core.errors import BadEntry, CannotPlay
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


def _by_prod(records):
    out = {}
    for r in records:
        out.setdefault(r.prod, []).append(r)
    return out


def each(todo, db, data, jobs=None, again=True):
    """Gate every ``(prod, entry)`` of ``todo``, entries of the data files
    ``data``, ``jobs`` emulators at a time. Yields of each, in order,
    ``(prod, True, judgement)``, what the gate saw then being in the store
    ``db``, or ``(prod, False, line)`` with the line that reports why it
    could not be played, which is stored as its error. Without ``again``
    an entry the log holds a judgement of is not played, and not
    yielded."""
    default = export.default_machine(data)
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    todo = list(todo)
    entries = dict(todo)
    records = {} if again else _by_prod(db.gated())
    why = {}

    def one(prod, entry):
        if _judged(records.get(prod), entry):
            return None
        try:
            return _one(prod, entry, default, pool.map)
        except CannotPlay as e:
            why[prod] = str(e)
            raise

    # The runs of every entry share one pool; an entry's thread only waits.
    with cf.ThreadPoolExecutor(jobs) as pool:
        for prod, ok, got in player.each_played(todo, one, jobs):
            if ok and got is None:
                continue
            if ok:
                got, sha256 = got
                db.put_gate(prod, entries[prod], got, sha256, player.VERSION)
            else:
                db.put_gate_error(prod, entries[prod], why[prod])
            yield prod, ok, got


def _judged(records, entry):
    """Do ``records``, the log of one production, hold a judgement of
    ``entry`` by today's player from today's download?"""
    return gatelog.held(records, entry) and not gatelog.stale(
        records, media.download_sha256, player.VERSION)


def _stands(records, entry):
    """Do ``records`` hold a pass of ``entry`` (see ``_judged``)?"""
    return gatelog.passes(records, entry) and _judged(records, entry)


def _first(prod, entries, default, records, each=map):
    """``(entry, seen)``: the first of ``entries`` that passes, or None,
    and ``(entry, judgement, sha256)`` of each one played. A pass the log
    holds is taken with nothing seen, so the log stays of that entry; a
    BadEntry is a fail with no SHA-256."""
    seen = []
    for entry in entries:
        if _stands(records, entry):
            return entry, []
        try:
            said, sha256 = _one(prod, entry, default, each)
        except BadEntry as e:
            said, sha256 = gate.Judgement(False, f"cannot be played: {e}"), None
        seen.append((entry, said, sha256))
        if said.passed:
            return entry, seen
    return None, seen


def first(todo, db, data, jobs=None):
    """Of every ``(prod, entries)`` of ``todo``, entries best first and
    not empty: ``(prod, True, (entry, said))``, the first entry that passes
    (or None) and the judgement of each one played, now in ``db``; or
    ``(prod, False, line)`` when it could not be played."""
    if not todo:
        return
    default = export.default_machine(data)
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    records = _by_prod(db.gated())
    entries = dict(todo)
    with cf.ThreadPoolExecutor(jobs) as pool:
        for prod, ok, got in player.each_played(
                [(p, es[0]) for p, es in todo],
                lambda p, _: _first(p, entries[p], default, records.get(p),
                                    pool.map), jobs):
            if ok:
                entry, seen = got
                for played, said, sha256 in seen:
                    if sha256:
                        db.put_gate(prod, played, said, sha256, player.VERSION)
                got = entry, [said for _, said, _ in seen]
            yield prod, ok, got


def run(ids, db, data=None, jobs=None, log=print):
    """Gate the productions ``ids`` (see ``each``): a line of each. With
    None, every entry the log holds no judgement of. Returns how many could
    not be played."""
    data = data or config.DATA_DIR
    found = replay.all_entries(data)
    for p in sorted(set(ids or ()) - set(found)):
        log(f"{p}: no entry in the data files")
    todo = sorted((p, e) for p, e in found.items() if ids is None or p in ids)
    errors = 0
    for prod, ok, got in each(todo, db, data, jobs, again=ids is not None):
        errors += not ok
        log(f"{prod} {found[prod]['title']}: {got}" if ok else got, flush=True)
    return errors


def write_summary(db, path=None):
    """Write the counts of what the gate saw to the summary file."""
    path = path or config.GATE_SUMMARY
    path.write_text(gatelog.summary(db.gated(), db.gate_errors()), "utf-8")
    return path


def demote(db, data=None, write=False, log=print):
    """What the gate's log says of the entries as they stand: the counts,
    the ``script`` entries to demote, the failing ones somebody worked on,
    and those it could not play or has not played. A record to gate
    again (see ``stale``) is none. With ``write`` the demotions go into the
    data files."""
    data = data or config.DATA_DIR
    found = replay.all_entries(data)
    again = {prod for prod, _ in _stale(db, found)}
    seen = core_demote.review(
        found, [r for r in db.gated() if r.prod not in again],
        db.gate_errors())
    log(f"{len(found)} entries: {seen.passed} pass, {seen.failed} fail,"
        f" {len(seen.errors)} could not be played, {len(seen.ungated)} not"
        " gated as they stand")
    for title, rows in (("to demote", seen.demote),
                        ("failed, kept as edited", seen.kept),
                        ("could not be played", seen.errors),
                        ("not gated", [(p, None) for p in seen.ungated])):
        log(f"\n{title}: {len(rows)}")
        for prod, why in rows:
            log(f"{prod} {found[prod]['title']}" + (f": {why}" if why else ""))
    if write:
        log("")
        export.run(data, [("demozoo", p, core_demote.demoted(found[p], why))
                          for p, why in seen.demote])


def _stale(db, found):
    """``(prod, why)`` of each of the entries ``found`` to gate again."""
    media.require_mirror()
    return gatelog.stale([r for r in db.gated() if r.prod in found],
                         media.download_sha256, player.VERSION)


def stale(db, data=None, log=print):
    """A line of each entry to gate again: its download, or the player, is
    not the one the gate saw it with."""
    found = replay.all_entries(data or config.DATA_DIR)
    for prod, why in _stale(db, found):
        log(f"{prod} {found[prod]['title']}: {why}")
