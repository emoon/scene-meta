"""The gate over entries of the data files (``data/amiga``): the core's gate
says which runs to make of each and whether it passes (see core.gate); the
player makes them. What it saw is kept in the sweep's log, from which come
the summary and the entries to gate again (see core.gatelog), and the
entries a pass over all of them demotes (see core.demote).

``first`` is the gate of the export: of the entries a production may be
written as, the first that passes.

Asked for the area, the MEASURED run of each entry measures it (see
area.py), and that of an entry that passes is kept in the log too.
"""

import dataclasses

from ..core import demote as core_demote
from ..core import export, gate, gatelog, gaterunner
from ..core.errors import CannotPlay
from . import config, media, player, replay


# The run that measures the area: the entry as written.
MEASURED = gate.Run(gate.SEEDS[0])


def _play(ready, run, areas=None):
    """The record of ``run`` of the entry of ``ready``, as long as the
    longer of the entry and what is played of it. Raises CannotPlay when
    the emulator showed nothing. ``areas``: a list that gets the area the
    MEASURED run shows."""
    changed = gate.as_played(ready.entry, run)
    frames = max(player.frames_of(e, run.patient)
                 for e in (ready.entry, changed))
    measure = areas is not None and run == MEASURED
    ran = dataclasses.replace(ready, entry=changed).play(
        seed=run.seed, frames=frames, patient=run.patient, area=measure)
    if ran.verdict.verdict == "error":
        raise CannotPlay(f"the emulator gave nothing: {ran.verdict.crash}")
    if measure and ran.area:
        areas.append(ran.area)
    return ran.record


def _one(prod, entry, default, each=map, areas=None):
    """``(judgement, sha256)`` of one production: the gate's judgement, its
    runs made through ``each`` (see core.gate.check), and the SHA-256 of
    the download they were played from. Raises CannotPlay when something
    it needs is missing, or the emulator showed nothing of a run.
    ``areas``: see ``_play``."""
    ready = player.ready(prod, entry, default)
    sha256 = media.download_sha256(prod)
    return gate.check(entry, lambda run: _play(ready, run, areas),
                      each), sha256


def _runner(data):
    return gaterunner.Runner(_one, player.each_played, media.download_sha256,
                             player.VERSION, export.default_machine(data))


def each(todo, db, data, jobs=None, again=True, areas=None):
    """Gate entries and keep their judgements and optional measured areas."""
    yield from _runner(data).each(todo, db, jobs, again, areas)


def first(todo, db, data, jobs=None):
    """The first passing export candidate of each production, kept in db."""
    if todo:
        yield from _runner(data).first(todo, db, jobs)


def _area_said(a):
    """What a line says of the result.Area ``a``, or of none."""
    return (f"; area {a.width}x{a.height}, drawn into"
            f" {a.drawn_width}x{a.drawn_height}") if a else ""


def run(ids, db, data=None, jobs=None, log=print, area=False):
    """Gate the productions ``ids`` (see ``each``): a line of each. With
    None, every entry the log holds no judgement of. Returns how many could
    not be played. With ``area`` the area of each entry that passes is
    measured (see ``each``), and its line says it."""
    data = data or config.DATA_DIR
    areas = {} if area else None
    return gaterunner.run(ids, db, data, replay.all_entries(data), each, jobs,
                           log, areas, lambda p: _area_said(areas.get(p))
                           if area else "")


def write_summary(db, path=None):
    """Write the counts of what the gate saw to the summary file."""
    return gaterunner.write_summary(db, path or config.GATE_SUMMARY)


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
