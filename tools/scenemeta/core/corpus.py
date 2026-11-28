"""Run a platform corpus through its gate and write a deterministic scoreboard."""

from . import entries, expected


def load(path, data, read=entries.all_entries):
    found = read(data)
    cases = expected.parse(path.read_text("utf-8"), found)
    return cases, {p: found[p] for p in sorted(cases)}


def run(db, path, board, data, each, jobs=None, log=print,
        read=entries.all_entries):
    cases, entries = load(path, data, read)
    saw = {}
    for prod, ok, got in each(entries.items(), db, data, jobs):
        saw[prod] = expected.seen(got) if ok else expected.ERROR
        line = f"{prod} {entries[prod]['title']}: {got}" if ok else got
        log(f"{line}; expected {cases[prod].expect}", flush=True)
    log(expected.total(cases, saw))
    board.write_text(expected.scoreboard(cases, saw), "utf-8")
    log(f"wrote {board}")
    return sum(s == expected.ERROR for s in saw.values())
