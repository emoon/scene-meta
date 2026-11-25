"""Production files as text: one block per production.

A file is rewritten block by block, so that the blocks nobody replaces keep
their text as written, comments included.
"""

import re

# Fields in the order they are written; any other (the hardware overrides)
# follow ``machine``.
_HEAD = ("title", "group", "source", "demozoo", "csdb", "machine")
_TAIL = ("boot", "kind", "result", "disks", "events", "run",
         "boot_disk", "boot_file", "assign", "area", "aspect", "note")
_VARIANT_HEAD = ("file", "sha256", "machine")

_HEADER = re.compile(r"\[(demozoo|csdb)\.(\d+)\]\s*(#.*)?")
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def _string(s):
    return '"' + "".join(
        _ESCAPES.get(c) or (f"\\u{ord(c):04x}" if c < " " or c == "\x7f" else c)
        for c in s) + '"'


def _key(k):
    return k if _BARE_KEY.fullmatch(k) else _string(k)


def _value(v):
    if isinstance(v, str):
        return _string(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    return repr(v)


def _fields(table, head):
    names = [n for n in head if n in table]
    names += sorted(table.keys() - set(head) - set(_TAIL) - {"variant"})
    names += [n for n in _TAIL if n in table]
    return [f"{n} = {_value(table[n])}" for n in names]


def render(namespace, id_, entry):
    """One production as a block of TOML, no trailing newline."""
    lines = [f"[{namespace}.{id_}]"] + _fields(entry, _HEAD)
    for variant in entry.get("variant", ()):
        lines += ["", f"[[{namespace}.{id_}.variant]]"] + _fields(variant, _VARIANT_HEAD)
    return "\n".join(lines)


def split(text):
    """``(preamble, {(namespace, id): block})`` of a production file. The
    comment lines right above a header belong to its block."""
    preamble, blocks, current = [], {}, None
    lines = preamble
    for line in text.splitlines():
        if m := _HEADER.fullmatch(line.rstrip()):
            lead = []
            while lines and lines[-1].startswith("#"):
                lead.insert(0, lines.pop())
            current = (m[1], int(m[2]))
            lines = blocks[current] = lead + [line]
        else:
            lines.append(line)
    return ("\n".join(preamble).strip("\n"),
            {k: "\n".join(v).strip("\n") for k, v in blocks.items()})


def join(preamble, blocks):
    """The text of a file holding ``blocks`` (in order)."""
    return "\n\n".join(([preamble] if preamble else []) + list(blocks)) + "\n"
