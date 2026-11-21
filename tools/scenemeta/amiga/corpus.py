"""The gate over the corpus (``amiga/corpus.toml``, see core.corpus): the
productions with the outcome expected of them, and the scoreboard of how
many the gate saw so.
"""

from ..core import corpus
from . import config, gate, replay


def load(path=None, data=None):
    """``({prod: corpus.Case}, {prod: entry})`` of the corpus file. Raises
    corpus.Invalid when it does not hold, or names a production with no
    entry in the data files."""
    found = replay.all_entries(data or config.DATA_DIR)
    cases = corpus.parse((path or config.CORPUS).read_text("utf-8"), found)
    return cases, {p: found[p] for p in sorted(cases)}


def run(db, path=None, board=None, data=None, jobs=None, log=print):
    """Gate every production of the corpus (see gate.each): a line of each
    with what was expected, the total, and the scoreboard file. Returns
    how many could not be played."""
    data = data or config.DATA_DIR
    cases, entries = load(path, data)
    saw = {}
    for prod, ok, got in gate.each(entries.items(), db, data, jobs):
        saw[prod] = corpus.seen(got) if ok else corpus.ERROR
        line = f"{prod} {entries[prod]['title']}: {got}" if ok else got
        log(f"{line}; expected {cases[prod].expect}", flush=True)
    log(corpus.total(cases, saw))
    board = board or config.CORPUS_SCORE
    board.write_text(corpus.scoreboard(cases, saw), "utf-8")
    log(f"wrote {board}")
    return sum(s == corpus.ERROR for s in saw.values())
