"""Conservative projection of stored detector evidence into TOML timing.

No playback and no database migration: the command reads a single SQLite
snapshot and reviews changes by default. Only script entries without an
existing end/ending may be enriched with --write. Area remains independent.
"""

import json
import math
import pathlib
import sqlite3

from .. import merge
from ..core import gatelog
from . import config, replay

# A classification is not enough: leave time to observe what follows it.
TAIL = 30
MIN_END = 10
_KINDS = {"exits": "exit", "stops": "still",
          "loops": "loop", "end-loop": "loop"}
_FLAGS = ("text_after_trace", "swap_after_trace", "end_before_swap", "alert")


def _time(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def fields(verdict):
    """Confident end/ending fields, or {} when the evidence needs review.

    Restart periods are durations, not power-on timestamps. Open and held
    screens do not prove that input is needed. None of those are exported.
    The detector has no reliable production-start observation yet.
    """
    kind = _KINDS.get(verdict.get("ending"))
    end, trace, after = (verdict.get(k) for k in ("end", "trace", "after"))
    if not kind or any(verdict.get(k) for k in _FLAGS):
        return {}
    if not all(_time(v) for v in (end, trace, after)):
        return {}
    if end < MIN_END or trace - end < TAIL or after < TAIL:
        return {}
    # Do not export an end contradicted by known text, data, or swaps.
    for key in ("text_end", "last_data"):
        value = verdict.get(key)
        if value is not None and (not _time(value) or value > end):
            return {}
    swaps = verdict.get("swaps", [])
    if not isinstance(swaps, list) or any(not _time(v) or v > end for v in swaps):
        return {}
    if kind == "loop":
        # A period alone is a duration. Known power-on completion anchors
        # must already fit inside the claimed end, including a delayed boot.
        for key in ("song_second_pass", "video_shown"):
            value = verdict.get(key)
            if value is not None and (not _time(value) or value > end):
                return {}
    if kind == "loop" and not any(
            _time(verdict.get(k)) and verdict[k] > 0
            for k in ("video_period", "song_period", "landmark_period")):
        return {}
    return {"end": end, "ending": kind}


def proposals(entries, held, ids=None, log=print):
    """New script entries; report every withheld result and hand disagreement."""
    out = []
    for prod, entry in sorted(entries.items()):
        if ids is not None and prod not in ids:
            continue
        record = held.get(prod)
        why = None
        if entry.get("result"):
            why = "entry does not simply work"
        elif not record:
            why = "no stored ending"
        elif record[0] != gatelog.name(entry):
            why = "stored ending is of different playback settings"
        else:
            timing = fields(record[1])
            if not timing:
                why = "detector evidence needs review"
            elif any(k in entry for k in ("end", "ending")):
                why = "existing timing kept"
            elif "start" in entry and (not _time(entry["start"])
                                        or entry["start"] >= timing["end"]):
                why = "end does not follow existing start"
            elif entry.get("source") != "script":
                why = f"{entry.get('source')} entry kept; detector proposes {timing}"
            else:
                out.append(("demozoo", prod, {**entry, **timing}))
                log(f"{prod}: proposes end={timing['end']} ending={timing['ending']}")
        if why:
            log(f"{prod}: {why}")
    return out


def read(path):
    """The stored verdicts from a read-only connection (including WAL)."""
    uri = pathlib.Path(path).resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        return {prod: (entry, json.loads(detail))
                for prod, entry, detail in db.execute(
                    "select prod_id, entry, detail from ending")}
    finally:
        db.close()


def run(ids=None, data=None, db_path=None, write=False, log=print):
    """Review or merge confident endings; never open the writable Store."""
    data = data or config.DATA_DIR
    held = read(db_path or config.RESULTS_DB)
    changes = proposals(replay.all_entries(data), held, ids=ids, log=log)
    report = merge.merge(data, changes) if write and changes else None
    log(f"{len(changes)} proposed; {report.replaced if report else 0} written")
    return 0
