"""Checks the data files against docs/DESIGN.md, one line per problem.

    python3 -m scenemeta.validate [data-dir]
"""

import math
import pathlib
import re
import sys
import tomllib

from . import events, machines, schema

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
MACHINES = machines.FILE

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _text(v):
    if not isinstance(v, str) or not v:
        return "must be a non-empty string"


def _seconds(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not v >= 0:
        return "must be a time in seconds"


def _finite_seconds(v):
    if _seconds(v) or not math.isfinite(v):
        return "must be a finite time in seconds"


def _timing(table):
    """Relations between valid timing fields, after variant inheritance."""
    if any(k in table and SETTINGS[k](table[k]) for k in schema.TIMING_FIELDS):
        return
    end, ending = table.get("end"), table.get("ending")
    if ending == "interactive":
        if end is not None:
            yield "interactive ending must not have end"
    elif (end is None) != (ending is None):
        yield "end and ending must be given together"
    if end is not None and end <= table.get("start", 0):
        yield "end must be after start (or power-on)"


def _one_of(names):
    def check(v):
        if v not in names:
            return "must be one of " + ", ".join(names)
    return check


def _number_from(low):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, int) or v < low:
            return f"must be a whole number, {low} or more"
    return check


def _texts(v):
    if not isinstance(v, list) or not v or any(_text(x) for x in v):
        return "must be a list of non-empty strings"


def _assign(v):
    if not isinstance(v, dict) or not v or any(_text(x) for x in v.values()):
        return "must be a table of name = path"


def _pixels(v):
    if not isinstance(v, list) or len(v) != 2 \
            or any(_number_from(1)(x) for x in v):
        return "must be [width, height] in pixels"


def _rows(required, optional=()):
    """A list of inline tables with these fields (name -> check)."""
    fields = {**dict(required), **dict(optional)}

    def check(v):
        if not isinstance(v, list) or not v:
            return "must be a list of tables"
        for row in v:
            if not isinstance(row, dict):
                return "must be a list of tables"
            for name, _ in required:
                if name not in row:
                    return f"needs {name}"
            for name, value in row.items():
                if name not in fields:
                    return f"unknown field {name}"
                if problem := fields[name](value):
                    return f"{name} {problem}"
    return check


def _sha256(v):
    if not isinstance(v, str) or not _SHA256.fullmatch(v):
        return "must be 64 lowercase hex digits"


def _coords(v):
    if not isinstance(v, list) or len(v) != 2 \
            or any(_number_from(0)(x) for x in v):
        return "must be [x, y] pointer coordinates"


def _events(v):
    if problem := _EVENT_ROWS(v):
        return problem
    for event in v:
        if ("disk" in event) == ("key" in event):
            return "an event is a disk or a key, one of them"
        if "drive" in event and "disk" not in event:
            return "drive is of a disk"
        if "pos" in event and "key" not in event:
            return "pos is of a key"
        if "until" in event and event["until"] < event["at"]:
            return "until is before at"
    if v != events.ordered(v):
        return ("must be in the order they happen, a disk before a key of"
                " the same moment")


# Every production disk can be reinserted, including those mounted at boot.
# Key names remain platform-specific; the player checks its input vocabulary.
_EVENT_ROWS = _rows((("at", _seconds),),
                    (("disk", _number_from(1)), ("drive", _number_from(2)),
                     ("until", _seconds), ("key", _text), ("pos", _coords)))

# What a production needs to run. A variant may restate any of them.
SETTINGS = {
    "boot": _one_of(schema.BOOTS),
    "result": _one_of(schema.RESULTS),
    "kind": _one_of(schema.KINDS),
    "disks": _texts,
    "events": _events,
    "run": _text,   # an executable, or a script that runs the parts
    "boot_disk": _number_from(1),
    "boot_file": _text,
    "assign": _assign,
    "start": _finite_seconds,
    "end": _finite_seconds,
    "ending": _one_of(schema.ENDINGS),
    "area": _pixels,
    "aspect": _one_of(schema.ASPECTS),
    "note": _text,
}

VARIANT = {"file": _text, "sha256": _sha256}

PRODUCTION = {
    "title": _text,
    "group": _text,
    "source": _one_of(schema.SOURCES),
    **{ns: _number_from(1) for ns in schema.NAMESPACES},
}


def _settings(table, known, presets):
    """Problems in the settings fields of a production or a variant."""
    hardware = machines.hardware_fields(presets)
    for name, value in table.items():
        if name in known:
            continue
        if name == "machine":
            if value not in presets:
                yield f"machine {value!r} is not in {MACHINES}"
        elif name in hardware:
            if not machines.hardware_value(value):
                yield f"{name} must be a string or a whole number"
        elif name in SETTINGS:
            if problem := SETTINGS[name](value):
                yield f"{name} {problem}"
        else:
            yield f"unknown field {name}"


def _production(namespace, entry, presets):
    for name in ("title", "source"):
        if name not in entry:
            yield f"needs {name}"
    for name, check in PRODUCTION.items():
        if name in entry and (problem := check(entry[name])):
            yield f"{name} {problem}"
    if namespace in entry:
        yield f"{namespace} repeats the key"
    yield from _settings(entry, PRODUCTION.keys() | {"variant"}, presets)

    yield from _timing(entry)

    variants = entry.get("variant", [])
    if not isinstance(variants, list) or \
            any(not isinstance(v, dict) for v in variants):
        yield "variant must be [[...variant]] tables"
        return
    for variant in variants:
        for name, check in VARIANT.items():
            if name not in variant:
                yield f"variant needs {name}"
            elif problem := check(variant[name]):
                yield f"variant {name} {problem}"
        for problem in _settings(variant, VARIANT.keys(), presets):
            yield f"variant {problem}"
        for problem in _timing({**entry, **variant}):
            yield f"variant {problem}"


def _file(path, presets, seen):
    """Problems in one production file. ``seen`` maps every ID met so far in
    the platform to where it was."""
    try:
        doc = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        yield str(e)
        return
    for namespace, entries in doc.items():
        if namespace not in schema.NAMESPACES or not isinstance(entries, dict):
            yield f"unknown top-level {namespace}"
            continue
        previous = None
        for key, entry in entries.items():
            where = f"[{namespace}.{key}]"
            if not key.isdecimal() or str(int(key)) != key \
                    or not isinstance(entry, dict):
                yield f"{where} must be a table with a numeric ID"
                continue
            for problem in _production(namespace, entry, presets):
                yield f"{where} {problem}"

            ids = [(namespace, int(key))] + \
                [(ns, entry[ns]) for ns in schema.NAMESPACES if ns in entry]
            for id_ in ids:
                if id_ in seen:
                    yield f"{where} {id_[0]}.{id_[1]} is already in {seen[id_]}"
                seen.setdefault(id_, f"{path.name} {where}")

            title = entry.get("title")
            if not isinstance(title, str):
                continue
            if schema.bucket(title) != path.stem:
                yield f"{where} belongs in {schema.bucket(title)}.toml"
            order = (title.casefold(), int(key))
            if previous and order < previous:
                yield f"{where} is out of order (sorted by title, then ID)"
            previous = order


def check_platform(directory):
    """Problems in one platform's directory, as printable lines."""
    _, presets, problems = machines.load(directory / MACHINES)
    out = [f"{directory / MACHINES}: {p}" for p in problems]
    seen = {}
    for path in sorted(directory.glob("*.toml")):
        if path.name != MACHINES:
            out += [f"{path}: {p}" for p in _file(path, presets, seen)]
    return out


def check(data):
    out = []
    for directory in sorted(p for p in data.iterdir() if p.is_dir()):
        out += check_platform(directory)
    return out


def main(argv):
    problems = check(pathlib.Path(argv[1]) if len(argv) > 1 else DATA)
    for line in problems:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
