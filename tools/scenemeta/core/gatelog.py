"""What the gate saw of each entry (docs/DESIGN.md, Replay): a record per
entry and seed, kept in the sweep's log (core.store, table ``gate``) and
never in the data files. From the records, the summary that is checked in
and the entries to gate again.
"""

import dataclasses
import hashlib
import json

from .. import merge


@dataclasses.dataclass(frozen=True)
class Record:
    prod: int
    seed: int
    passed: bool
    reason: str
    sha256: str    # of the download it was played from
    player: str    # the version of the player that played it
    at: str        # the wall clock
    entry: str = None    # ``name`` of the entry played; None: not recorded


@dataclasses.dataclass(frozen=True)
class Error:
    """An entry the gate could not play: nothing is known of it."""
    prod: int
    reason: str
    at: str
    entry: str    # ``name`` of the entry


def _plain(value):
    """``value`` with every number a float: 800 in a file is 800.0."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return value


def name(entry):
    """What a record calls the entry it is of: a digest of what the entry
    sets (see merge.settings), so the same for two that play the same."""
    return hashlib.sha256(json.dumps(
        _plain(merge.settings(entry)), sort_keys=True).encode()).hexdigest()


def held(records, entry):
    """Are ``records``, those of one production, of ``entry``?"""
    return bool(records) and all(r.entry == name(entry) for r in records)


def passes(records, entry):
    """Do ``records``, those of one production, say that ``entry`` passed?"""
    return held(records, entry) and all(r.passed for r in records)


def fault(records):
    """Why the entry of ``records`` failed, on the first seed it did; None
    when it passed."""
    return next((f"seed {r.seed}: {r.reason}" for r in records
                 if not r.passed), None)


def outcomes(records):
    """``{prod: passed}``: an entry passed when it did on every seed."""
    out = {}
    for r in records:
        out[r.prod] = out.get(r.prod, True) and r.passed
    return out


def summary(records, errors=()):
    """The text of the summary file: how many entries of each outcome. One
    of ``errors``, which could not be played, is neither pass nor fail."""
    unplayed = {e.prod for e in errors}
    passed = [ok for prod, ok in outcomes(records).items()
              if prod not in unplayed]
    return ("Entries by what the gate last saw of them.\n\n"
            f"pass {sum(passed):6}\nfail {len(passed) - sum(passed):6}\n"
            f"error{len(unplayed):6}\n")


def stale(records, sha256_of, player):
    """``(prod, why)`` of each entry to gate again, by id: its record is of
    another version of the player than ``player``, or of another download
    than the one of today, whose SHA-256 is ``sha256_of(prod)``."""
    out = []
    for prod, r in sorted({r.prod: r for r in records}.items()):
        if r.player != player:
            out.append((prod, f"gated by player {r.player}, now {player}"))
        elif r.sha256 != sha256_of(prod):
            out.append((prod, "download changed"))
    return out
