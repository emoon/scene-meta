"""C64 corpus and scoreboard, using the same gate as exported entries."""

from ..core import corpus
from . import config, gate


def load(path=None, data=None):
    return corpus.load(path or config.EXPECTED, data or config.DATA_DIR)


def run(db, path=None, board=None, data=None, jobs=None, log=print):
    return corpus.run(db, path or config.EXPECTED, board or config.EXPECTED_SCORE,
                      data or config.DATA_DIR, gate.each, jobs or 1, log)
