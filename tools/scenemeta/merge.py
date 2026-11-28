"""Merges a sweep's results into a platform's production files.

Only entries marked ``script`` are replaced. An entry somebody worked on
(``ai``, ``verified``) is kept as written, and where the sweep disagrees
with it the difference is reported instead.
"""

import dataclasses
import tomllib

from . import document, machines, schema

# Fields that say nothing of how a production is run: a difference there is
# not a disagreement.
_NOT_COMPARED = ("title", "group", "source", "note") + schema.ANNOTATIONS


@dataclasses.dataclass
class Report:
    added: int = 0
    replaced: int = 0
    kept: int = 0                 # entries the sweep may not touch
    files: int = 0                # files written
    disagreements: list = dataclasses.field(default_factory=list)


def settings(entry):
    """What ``entry`` sets: its fields that say how the production is run."""
    return {k: [settings(row) for row in v] if k == "variant" else v
            for k, v in entry.items() if k not in _NOT_COMPARED}


def _differences(old, new):
    old, new = settings(old), settings(new)
    return [f"{k}: has {old.get(k)!r}, sweep says {new.get(k)!r}"
            for k in sorted(old.keys() | new.keys()) if old.get(k) != new.get(k)]


def _load(directory):
    """Every production of a platform: ``{key: (entry, block)}``, and each
    file's preamble and text."""
    found, preambles, texts = {}, {}, {}
    for path in sorted(directory.glob("*.toml")):
        if path.name == machines.FILE:
            continue
        texts[path.stem] = text = path.read_text()
        doc = tomllib.loads(text)
        preambles[path.stem], blocks = document.split(text)
        for key, block in blocks.items():
            found[key] = (doc[key[0]][str(key[1])], block)
    return found, preambles, texts


def merge(directory, new):
    """Merge ``new`` (``(namespace, id, entry)`` triples) into the files of
    ``directory``; returns a Report."""
    found, preambles, texts = _load(directory)
    report = Report()
    for namespace, id_, entry in new:
        key = (namespace, id_)
        old = found.get(key)
        if old and old[0].get("source") != "script":
            report.kept += 1
            report.disagreements += [f"[{namespace}.{id_}] {old[0].get('title')}: {d}"
                                     for d in _differences(old[0], entry)]
            continue
        if old and settings(old[0]) == settings(entry):
            # A fresh sweep of the same playback must keep its known timing.
            entry = {**{k: old[0][k] for k in schema.TIMING_FIELDS if k in old[0]},
                     **entry}
        block = document.render(namespace, id_, entry)
        if not old:
            report.added += 1
        elif old[1] != block:
            report.replaced += 1
        found[key] = (entry, block)

    buckets = {}
    for key, (entry, block) in found.items():
        title = entry.get("title", "")
        buckets.setdefault(schema.bucket(title), []).append(
            ((title.casefold(), key[1]), block))
    for stem in buckets.keys() | texts.keys():
        path = directory / f"{stem}.toml"
        if stem not in buckets:
            path.unlink()
            report.files += 1
            continue
        blocks = [b for _, b in sorted(buckets[stem], key=lambda x: x[0])]
        text = document.join(preambles.get(stem, ""), blocks)
        if text != texts.get(stem):
            path.write_text(text)
            report.files += 1
    return report
