"""Shared gate orchestration, with platform playback supplied as callbacks.

A single run pool bounds emulator concurrency across productions. The runner
owns cache identity, first-passing export selection and gate persistence;
players own media, hardware and observations.
"""

import concurrent.futures as cf
import os

from . import gate, gatelog
from .errors import BadEntry, CannotPlay


class Runner:
    def __init__(self, one, each_played, sha256_of, version, default):
        self.one = one
        self.each_played = each_played
        self.sha256_of = sha256_of
        self.version = version
        self.default = default

    def each(self, todo, db, jobs=None, again=True, areas=None):
        """Gate every ``(prod, entry)`` of ``todo``, ``jobs`` emulators at a time. Yields of each, as it ends,
        ``(prod, True, judgement)``, what the gate saw then being in the store
        ``db``, or ``(prod, False, line)`` with the line that reports why it
        could not be played, which is stored as its error. Without ``again``
        an entry the log holds a judgement of is not played, and not
        yielded. ``areas``: a dict that gets the area measured of each entry
        that passes, by id, which is stored too; None, and none is measured."""
        default = self.default
        jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
        todo = list(todo)
        entries = dict(todo)
        records = {} if again else _by_prod(db.gated())
        held = {} if areas is None else db.areas()
        why, seen = {}, {}

        def one(prod, entry):
            try:
                if self.judged(records.get(prod), entry) and not _wants_area(
                        records[prod], entry, held.get(prod), areas is not None):
                    return None
                seen[prod] = None if areas is None else []
                return self.one(prod, entry, default, pool.map, seen[prod])
            except CannotPlay as e:
                why[prod] = str(e)
                raise

        # The runs of every entry share one pool; an entry's thread only waits.
        with cf.ThreadPoolExecutor(jobs) as pool:
            for prod, ok, got in self.each_played(todo, one, jobs):
                if ok and got is None:
                    continue
                if ok:
                    got, sha256 = got
                    db.put_gate(prod, entries[prod], got, sha256, self.version)
                    if got.passed and seen.get(prod):
                        areas[prod] = seen[prod][0]
                        db.put_area(prod, entries[prod], areas[prod], sha256,
                                    self.version)
                else:
                    db.put_gate_error(prod, entries[prod], why[prod])
                yield prod, ok, got

    def judged(self, records, entry):
        """Do ``records``, the log of one production, hold a judgement of
        ``entry`` by today's player from today's download?"""
        return gatelog.held(records, entry) and not gatelog.stale(
            records, self.sha256_of, self.version)

    def stands(self, records, entry):
        """Do ``records`` hold a pass of ``entry`` (see ``judged``)?"""
        return gatelog.passes(records, entry) and self.judged(records, entry)

    def _first(self, prod, entries, default, records, each=map):
        """``(entry, seen)``: the first of ``entries`` that passes, or None,
        and ``(entry, judgement, sha256)`` of each one played. A pass the log
        holds is taken with nothing seen, so the log stays of that entry; a
        BadEntry is a fail with no SHA-256."""
        seen = []
        for entry in entries:
            if self.stands(records, entry):
                return entry, []
            try:
                said, sha256 = self.one(prod, entry, default, each)
            except BadEntry as e:
                said, sha256 = gate.Judgement(False, f"cannot be played: {e}"), None
            seen.append((entry, said, sha256))
            if said.passed:
                return entry, seen
        return None, seen

    def first(self, todo, db, jobs=None):
        """Of every ``(prod, entries)`` of ``todo``, entries best first and
        not empty: ``(prod, True, (entry, said))``, the first entry that passes
        (or None) and the judgement of each one played, now in ``db``; or
        ``(prod, False, line)`` when it could not be played."""
        if not todo:
            return
        default = self.default
        jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
        records = _by_prod(db.gated())
        entries = dict(todo)
        with cf.ThreadPoolExecutor(jobs) as pool:
            for prod, ok, got in self.each_played(
                    [(p, es[0]) for p, es in todo],
                    lambda p, _: self._first(p, entries[p], default, records.get(p),
                                        pool.map), jobs):
                if ok:
                    entry, seen = got
                    for played, said, sha256 in seen:
                        if sha256:
                            db.put_gate(prod, played, said, sha256, self.version)
                    got = entry, [said for _, said, _ in seen]
                yield prod, ok, got


def _by_prod(records):
    out = {}
    for r in records:
        out.setdefault(r.prod, []).append(r)
    return out


def _wants_area(records, entry, held, asked):
    """Is the area asked for of ``entry``, which ``records`` say passed,
    and not held of it? ``held``: ``(entry, Area)`` or None."""
    return asked and gatelog.passes(records, entry) and (
        not held or held[0] != gatelog.name(entry))


def run(ids, db, data, found, each, jobs=None, log=print, areas=None,
        describe=lambda prod: ""):
    """Gate selected entries and report results; None resumes all entries."""
    for prod in sorted(set(ids or ()) - set(found)):
        log(f"{prod}: no entry in the data files")
    todo = sorted((p, e) for p, e in found.items() if ids is None or p in ids)
    errors = 0
    for prod, ok, got in each(todo, db, data, jobs, again=ids is not None,
                              areas=areas):
        errors += not ok
        line = f"{prod} {found[prod]['title']}: {got}{describe(prod)}" if ok else got
        log(line, flush=True)
    return errors


def write_summary(db, path):
    path.write_text(gatelog.summary(db.gated(), db.gate_errors()), "utf-8")
    return path
