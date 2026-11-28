"""C64 adapters for the platform-neutral gate runner."""

import dataclasses
import functools

from ..core import export, gate, gaterunner, gatelog
from ..core.entries import all_entries
from . import config, media, player


def _play(ready, run):
    changed = gate.as_played(ready.entry, run)
    seconds = max(player.seconds_of(e, run.patient) for e in (ready.entry, changed))
    return dataclasses.replace(ready, entry=changed).play(
        seed=run.seed, seconds=seconds, patient=run.patient)


def _one(prod, entry, default, each=map, areas=None, presets=None):
    ready = player.ready(prod, entry, default, presets)
    sha256 = media.download_sha256(prod)
    return gate.check(entry, lambda run: _play(ready, run), each), sha256


def _runner(data):
    # Presets come from the same directory as the entries, including callers'
    # temporary data directories, rather than a process-global default.
    default, presets = export.presets(data)

    return gaterunner.Runner(functools.partial(_one, presets=presets),
                             player.each_played, media.download_sha256,
                             player.VERSION, default)


def each(todo, db, data, jobs=None, again=True, areas=None):
    yield from _runner(data).each(todo, db, jobs or 1, again)


def first(todo, db, data, jobs=None):
    if todo:
        yield from _runner(data).first(todo, db, jobs or 1)


def run(ids, db, data=None, jobs=None, log=print):
    data = data or config.DATA_DIR
    return gaterunner.run(ids, db, data, all_entries(data), each, jobs or 1, log)


def write_summary(db, path=None):
    return gaterunner.write_summary(db, path or config.GATE_SUMMARY)


def stale(db, data=None, log=print):
    found = all_entries(data or config.DATA_DIR)
    media.require_mirror()
    for prod, why in gatelog.stale([r for r in db.gated() if r.prod in found],
                                   media.download_sha256, player.VERSION):
        log(f"{prod} {found[prod]['title']}: {why}")
