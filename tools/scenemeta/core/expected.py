"""A platform's expected outcomes (docs/DESIGN.md, Replay): productions with
the outcome expected of them, kept beside its tools as TOML, a ``[demozoo.N]`` table of
each. The gate is run over them and the scoreboard, which is checked in,
says how many it saw as expected.
"""

import dataclasses
import re
import tomllib

# What is expected of a production, and what the gate says of one that is so.
EXPECTED = {"plays": "pass", "broken": "fail"}
ERROR = "error"    # in place of the gate's word: it could not be played

_CAUSE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


class Invalid(Exception):
    """The expected file does not hold: a line per problem."""


@dataclasses.dataclass(frozen=True)
class Case:
    expect: str          # one of EXPECTED
    why: str = None      # of a broken one
    cause: str = None    # a label: what a known miss was traced to
    note: str = None
    video: tuple = None  # the shortest and longest capture, seconds; not used yet


def _text(v):
    return isinstance(v, str) and v != ""


def _video(v):
    return isinstance(v, list) and len(v) == 2 and v[0] <= v[1] and all(
        isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in v)


_FIELDS = {
    "expect": (EXPECTED.__contains__, "must be one of " + ", ".join(EXPECTED)),
    "why": (_text, "must be a non-empty string"),
    "cause": (lambda v: _text(v) and _CAUSE.fullmatch(v),
              "must be a lowercase label"),
    "note": (_text, "must be a non-empty string"),
    "video": (_video, "must be [shortest, longest] in whole seconds"),
}


def _case(table):
    """Problems of one production's table."""
    if not isinstance(table, dict):
        yield "must be a table"
        return
    for name, value in table.items():
        if name not in _FIELDS:
            yield f"unknown field {name}"
        elif not _FIELDS[name][0](value):
            yield f"{name} {_FIELDS[name][1]}"
    if "expect" not in table:
        yield "needs expect"
    elif (table["expect"] == "broken") != ("why" in table):
        yield "why goes with broken, and only with it"


def parse(text, known):
    """``{prod: Case}`` of the expected file ``text``. Raises Invalid when it
    does not hold, or names a production that is not in ``known``, the ids
    of the data files."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Invalid(str(e))
    problems = [f"unknown top-level {name}" for name in doc if name != "demozoo"]
    tables = doc.get("demozoo", {})
    if not isinstance(tables, dict):
        raise Invalid("demozoo must hold a table per production")
    for key, table in tables.items():
        where = f"[demozoo.{key}]"
        if not key.isdecimal() or str(int(key)) != key:
            problems.append(f"{where} must have a numeric ID")
            continue
        problems += [f"{where} {p}" for p in _case(table)]
        if int(key) not in known:
            problems.append(f"{where} is not in the data files")
    if problems:
        raise Invalid("\n".join(problems))
    return {int(key): Case(**dict(table, video=tuple(table["video"]))
                           if "video" in table else table)
            for key, table in tables.items()}


def seen(said):
    """The gate's word of an entry, from its gate.Judgement ``said``."""
    return "pass" if said.passed else "fail"


def total(cases, saw):
    """The line that says how many productions of ``cases`` the gate saw
    as expected; ``saw`` as for ``scoreboard``."""
    hits = sum(EXPECTED[c.expect] == saw[p] for p, c in cases.items())
    return f"as expected {hits} of {len(cases)}"


def scoreboard(cases, saw):
    """The text of the scoreboard file: the total, and of each production
    of ``cases`` what was expected and what the gate saw, ``saw[prod]``:
    ``seen`` of its judgement, or ERROR. Nothing else of a run is in it, so
    it changes only when a result does."""
    return ("The expected productions by what the gate last saw of them: per"
            " production what is expected, then what was seen.\n\n"
            f"{total(cases, saw)}\n\n" +
            "".join(f"{p:>7} {c.expect:6} {saw[p]}\n"
                    for p, c in sorted(cases.items())))
