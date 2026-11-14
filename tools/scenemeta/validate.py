"""Checks the data files against docs/DESIGN.md, one line per problem.

    python3 -m scenemeta.validate [data-dir]
"""

import pathlib
import re
import sys
import tomllib

from . import machines, schema

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
MACHINES = machines.FILE

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _text(v):
    if not isinstance(v, str) or not v:
        return "must be a non-empty string"


def _seconds(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        return "must be a time in seconds"


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


def _swaps(v):
    if problem := _SWAP_ROWS(v):
        return problem
    for swap in v:
        if "until" in swap and swap["until"] < swap["at"]:
            return "until is before at"
        if "key_delay" in swap and "key" not in swap:
            return "key_delay without key"


_SWAP_ROWS = _rows((("disk", _number_from(2)), ("at", _seconds)),
                   (("until", _seconds), ("key", _text), ("key_delay", _seconds)))

# What a production needs to run. A variant may restate any of them.
SETTINGS = {
    "boot": _one_of(schema.BOOTS),
    "result": _one_of(schema.RESULTS),
    "kind": _one_of(schema.KINDS),
    "disks": _texts,
    "swaps": _swaps,
    "keys": _rows((("at", _seconds), ("key", _text))),
    "run": _text,
    "boot_disk": _number_from(1),
    "boot_file": _text,
    "assign": _assign,
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
