"""Writes the sweep's results into the shared data files (``data/amiga``,
see docs/DESIGN.md): one entry per production, from the
variant that got furthest.

A production the sweep found is ``script``; one with a hand classification
(classes.tsv) is ``ai``. The merge replaces only ``script`` entries, so
whatever somebody edited in the data files stays.
"""

from ..core import export
from . import classes, config, media, player

_RUNS = ("works", "works-short")
_RESULT = {"works-then-crash": "crashes-later", "crash": "broken"}
_KIND = ("menu", "separate-disks")
_BROKEN = ("install-only", "crash", "broken-media")


def _rank(v):
    """How far a variant got: runs, runs then crashes, does not run; then
    the share of its disks it reached; then the first one found."""
    running = 2 if v.verdict in _RUNS else v.verdict == "works-then-crash"
    share = v.reached / len(v.disks) if v.disks else 1
    return running, share, -v.idx


def _media(v):
    """What the media made of a stored variant, as far as an entry names
    it."""
    d = v.detail
    if "run" in d:
        return media.Variant(v.kind, v.disks, run=d["run"], choice=d["choice"])
    run = _run_of_note(v.note, d.get("command"))
    return media.Variant(v.kind, v.disks, run=run, choice=run is not None)


def _run_of_note(note, command):
    """The file an entry names of a variant stored before its ``detail``
    said: read out of its note."""
    def after(marker):
        return note.split(marker, 1)[1].split(" (")[0].strip()
    if media.LAUNCH_NOTE in note:          # "<volume>:<path>"
        return after(media.LAUNCH_NOTE).split(":", 1)[-1]
    if media.MERGED_NOTE in note:
        return after("; runs ").removeprefix("script ")
    command = command or ""
    if "executables, picked" in note and command.count("\n") == 1:
        return command.strip().strip('"')
    return None


def _swap(s):
    """A result.Swap as an entry says it."""
    row = {"disk": s.disk, "at": round(s.at, 1)}
    if s.key:
        row["key"] = s.key
        if s.key_at is not None \
                and (delay := round(s.key_at - s.at, 1)) != player.KEY_DELAY:
            row["key_delay"] = delay
    return row


def entry(title, groups, variants, cls, default):
    """The data-file entry of one production from its export.Variant list.
    ``cls``: its ``(kind, note)`` of classes.tsv, or None."""
    kind, note = cls or (None, None)
    hd = [v for v in variants if v.kind == "hd"]
    v = max(hd if kind == "use-hd" and hd else variants, key=_rank)

    if kind in _BROKEN:
        result = "broken"
    elif v.verdict in _RUNS:
        result = None
    else:
        result = _RESULT.get(v.verdict, "unknown")
    runs = result in (None, "crashes-later")
    named = media.named(_media(v), [_media(o) for o in variants])

    e = {"title": title}
    if groups:
        e["group"] = groups
    e["source"] = "ai" if cls else "script"
    if runs and v.machine != default:
        e["machine"] = v.machine
    if runs and v.drives > 1:
        e["drives"] = v.drives
    if "boot" in named:
        e["boot"] = named["boot"]
    if kind in _KIND:
        e["kind"] = kind
    if result:
        e["result"] = result
    if "disks" in named:
        e["disks"] = named["disks"]
    if runs and v.swaps:
        e["swaps"] = [_swap(s) for s in v.swaps]
    if runs and v.keys:
        e["keys"] = [{"at": round(k.at, 1), "key": k.key} for k in v.keys]
    if "run" in named:
        e["run"] = named["run"]
    if note:
        e["note"] = note
    elif runs and v.reached < len(v.disks):
        e["note"] = f"the sweep only reached disk {max(v.reached, 1)} of {len(v.disks)}"
    return e


def entries(store, cls, default):
    """``(namespace, id, entry)`` of every production with a finished
    variant."""
    for prod, title, groups, variants in export.productions(store):
        yield "demozoo", prod, entry(title, groups, variants, cls.get(prod),
                                     default)


def run(store, data=None):
    data = data or config.DATA_DIR
    export.run(data, entries(store, classes.load(),
                             export.default_machine(data)))
