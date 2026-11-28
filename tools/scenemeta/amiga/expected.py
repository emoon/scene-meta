"""The Amiga expected outcomes and their gate scoreboard (core.corpus)."""

from ..core import corpus
from . import config, gate, replay


def load(path=None, data=None):
    return corpus.load(path or config.EXPECTED, data or config.DATA_DIR, replay.all_entries)


def run(db, path=None, board=None, data=None, jobs=None, log=print):
    return corpus.run(db, path or config.EXPECTED, board or config.EXPECTED_SCORE,
                      data or config.DATA_DIR, gate.each, jobs, log, replay.all_entries)
