"""Writes the sweep's results into the shared data files (``data/amiga``,
see docs/DESIGN.md): one entry per production, from the run that got
furthest.

A production the sweep found is ``script``; one with a hand classification
(classes.tsv) is ``ai``. The merge replaces only ``script`` entries, so
whatever somebody edited in the data files stays.

A ``script`` entry that says the production runs is put to the gate first.
When it fails, the entries of the next best runs are, core.export.TRIES in
all; when none passes the production is written as ``unknown``.
"""

from .. import events
from ..core import export
from . import classes, config, gate, media, replay

_RUNS = ("works", "works-short")
_ALIVE = _RUNS + ("works-then-crash",)
_RESULT = {"works-then-crash": "crashes-later", "crash": "broken"}
_KIND = ("menu", "separate-disks")
_BROKEN = ("install-only", "crash", "broken-media")
# Seconds from an insert to its key where the sweep did not keep when: the
# detector clicks that long after it puts a disk in.
KEY_DELAY = 5.0


def _rank(v):
    """A variant's chosen run before its others; then runs, runs then
    crashes, does not run; then the share of its disks it reached; then the
    first variant found."""
    running = 2 if v.verdict in _RUNS else v.verdict == "works-then-crash"
    share = v.reached / len(v.disks) if v.disks else 1
    return v.chosen, running, share, -v.idx


def _ranked(variants, kind=None):
    """The runs, best first. ``kind``: the production's of classes.tsv."""
    hd = [v for v in variants if v.kind == "hd"]
    return sorted(hd if kind == "use-hd" and hd else variants, key=_rank,
                  reverse=True)


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


def _events(swaps, keys):
    """The result.Swap and result.Key of a run as an entry says them: a
    swap's key is an event of its own, after its disk."""
    out = [{"at": round(k.at, 1), "key": k.key} for k in keys]
    for s in swaps:
        at = round(s.at, 1)
        out.append({"at": at, "disk": s.disk})
        if s.drive > 1:
            out[-1]["drive"] = s.drive
        if s.until is not None:
            out[-1]["until"] = round(s.until, 1)
        if s.key:
            delay = (KEY_DELAY if s.key_at is None
                     else round(s.key_at - s.at, 1))
            out.append({"at": round(at + delay, 1), "key": s.key})
    return events.ordered(out)


def entry(title, groups, variants, cls, default):
    """The data-file entry of one production from its export.Variant list,
    of the run that got furthest. ``cls``: its ``(kind, note)`` of
    classes.tsv, or None."""
    v = _ranked(variants, cls and cls[0])[0]
    return _entry(title, groups, v, variants, cls, default)


def alive(title, groups, variants, default):
    """The ``script`` entries that say the production runs, one of each run
    it came alive in, best first."""
    return [_entry(title, groups, v, variants, None, default)
            for v in _ranked(variants) if v.verdict in _ALIVE]


def failed(title, groups, variants, default):
    """The entry of a production none of whose entries passed the gate."""
    return _entry(title, groups, _ranked(variants)[0], variants, None, default,
                  failed=True)


def _entry(title, groups, v, variants, cls, default, failed=False):
    """The entry of run ``v`` of ``variants``; ``failed``: as one that the
    gate let no entry of pass."""
    kind, note = cls or (None, None)
    if failed:
        result = "unknown"
    elif kind in _BROKEN:
        result = "broken"
    elif v.verdict in _RUNS:
        result = None
    else:
        result = _RESULT.get(v.verdict, "unknown")
    runs = result in (None, "crashes-later")
    named = media.named(_media(v), [_media(o) for o in variants if o.chosen])

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
    if runs and (does := _events(v.swaps, v.keys)):
        e["events"] = does
    if "run" in named:
        e["run"] = named["run"]
    if note:
        e["note"] = note
    elif failed:
        e["note"] = (f"the sweep saw {v.verdict} on {v.machine};"
                     " no entry of it passed the gate")
    elif runs and v.reached < len(v.disks):
        e["note"] = f"the sweep only reached disk {max(v.reached, 1)} of {len(v.disks)}"
    return e


def proposals(store, cls, default, kept, ids=None):
    """``({id: entry}, {id: (tries, failed)})``: the productions written as
    the sweep saw them (not running, classified by hand, or in ``kept``),
    and the others' entries to gate with the one to write when none
    passes."""
    as_seen, to_gate = {}, {}
    for prod, title, groups, variants in export.productions(store, every=True):
        if ids and prod not in ids:
            continue
        hand = prod in cls or prod in kept
        tries = [] if hand else export.tries(
            alive(title, groups, variants, default))
        if tries:
            to_gate[prod] = tries, failed(title, groups, variants, default)
        else:
            as_seen[prod] = entry(title, groups, variants, cls.get(prod),
                                  default)
    return as_seen, to_gate


def run(store, data=None, ids=None, jobs=None, log=print):
    """Merge the sweep's results into the data files. Returns how many
    productions could not be played; their entries stay."""
    data = data or config.DATA_DIR
    kept = {p for p, e in replay.all_entries(data).items()
            if e.get("source") != "script"}
    entries, to_gate = proposals(store, classes.load(),
                                 export.default_machine(data), kept, ids)
    errors = 0
    for prod, ok, got in gate.first(
            [(p, tries) for p, (tries, _) in sorted(to_gate.items())],
            store, data, jobs):
        if not ok:
            errors += 1
            log(got, flush=True)
            continue
        passed, said = got
        entries[prod] = passed or to_gate[prod][1]
        if said:
            log(f"{prod} {entries[prod]['title']}: "
                + ", then ".join(map(str, said)), flush=True)
    export.run(data, (("demozoo", p, e) for p, e in sorted(entries.items())))
    return errors
