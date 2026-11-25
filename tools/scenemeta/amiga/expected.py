"""The gate over the expected outcomes (``amiga/expected.toml``, see core.expected): the
productions with the outcome expected of them, and the scoreboard of how
many the gate saw so.
"""

from ..core import expected
from . import config, gate, replay


def load(path=None, data=None):
    """``({prod: expected.Case}, {prod: entry})`` of the expected file. Raises
    expected.Invalid when it does not hold, or names a production with no
    entry in the data files."""
    found = replay.all_entries(data or config.DATA_DIR)
    cases = expected.parse((path or config.EXPECTED).read_text("utf-8"), found)
    return cases, {p: found[p] for p in sorted(cases)}


def run(db, path=None, board=None, data=None, jobs=None, log=print):
    """Gate every production of the expected file (see gate.each): a line of each
    with what was expected, the total, and the scoreboard file. Returns
    how many could not be played."""
    data = data or config.DATA_DIR
    cases, entries = load(path, data)
    saw = {}
    for prod, ok, got in gate.each(entries.items(), db, data, jobs):
        saw[prod] = expected.seen(got) if ok else expected.ERROR
        line = f"{prod} {entries[prod]['title']}: {got}" if ok else got
        log(f"{line}; expected {cases[prod].expect}", flush=True)
    log(expected.total(cases, saw))
    board = board or config.EXPECTED_SCORE
    board.write_text(expected.scoreboard(cases, saw), "utf-8")
    log(f"wrote {board}")
    return sum(s == expected.ERROR for s in saw.values())
