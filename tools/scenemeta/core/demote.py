"""What a gate pass over every entry means for the data files
(docs/DESIGN.md, Provenance): a ``script`` entry that says the production
runs and failed the gate is demoted to ``unknown``; a failing entry
somebody worked on is only listed, and so is what the gate could not play.
"""

import dataclasses

from . import gatelog

_SAYS_IT_RUNS = (None, "crashes-later")
# What an entry says of a run: not kept by one that does not say it runs.
_OF_A_RUN = ("machine", "drives", "events")


@dataclasses.dataclass
class Review:
    """The entries by what the gate saw of them as they stand. The lists
    are ``(prod, reason)``, by id."""
    passed: int = 0
    failed: int = 0    # ``demote`` and ``kept`` among them
    demote: list = dataclasses.field(default_factory=list)
    kept: list = dataclasses.field(default_factory=list)    # failed, not script
    errors: list = dataclasses.field(default_factory=list)
    ungated: list = dataclasses.field(default_factory=list)  # prod alone


def review(entries, records, errors):
    """The Review of ``entries`` (``{prod: entry}``) from the gate's log:
    its ``records`` (gatelog.Record) and ``errors`` (gatelog.Error). Only
    what the log says of an entry as it is now counts."""
    of = {}
    for r in records:
        of.setdefault(r.prod, []).append(r)
    unplayed = {e.prod: e for e in errors}
    out = Review()
    for prod, entry in sorted(entries.items()):
        error = unplayed.get(prod)
        if error and error.entry == gatelog.name(entry):
            out.errors.append((prod, error.reason))
        elif not gatelog.held(of.get(prod), entry):
            out.ungated.append(prod)
        elif (fault := gatelog.fault(of[prod])) is None:
            out.passed += 1
        else:
            out.failed += 1
            if entry.get("source") != "script":
                out.kept.append((prod, fault))
            elif entry.get("result") in _SAYS_IT_RUNS:
                out.demote.append((prod, fault))
    return out


def demoted(entry, fault):
    """``entry`` as one the gate failed with ``fault``."""
    out = {k: v for k, v in entry.items() if k not in _OF_A_RUN}
    return {**out, "result": "unknown", "note": f"failed the gate: {fault}"}
