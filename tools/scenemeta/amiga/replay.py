"""Plays entries of the data files (``data/amiga``, see docs/DESIGN.md) exactly as
written: the entry's machine, each disk put in at its time, each key pressed
after its insert, each key of ``keys`` at its time. Nothing is detected and nothing retried, so this shows
what the entry says, not what a sweep can find.

An entry with keys, on its swaps or of its own, is played a second time without
them: a key is needed only when the production does not run without it.
"""

import concurrent.futures as cf
import os
import tomllib

from .. import machines as presets

from ..core.export import default_machine
from . import config, emulator, machines, media, verdict
from .errors import CannotPlay
from .machines import FPS

KEY_DELAY = 5.0      # seconds from an insert to its key, when not given
BUTTONS = {"lmb": 0}
# Keep going this long after the last insert, to see the disk load.
TAIL_FRAMES = emulator.AUTOSWAP_TAIL_FRAMES
# A disk is loaded when it was read with the head past its first cylinders:
# cylinders 0 and 1 are where a demo checks which disk is in.
LOADED_CYL = 2


def actions(entry, keys=True):
    """What to do when, for emulator.Options' ``play``. Without ``keys`` the
    disks go in and nothing is pressed."""
    out = []
    first = entry.get("drives", 1) + 1      # the first disk that is swapped in
    for swap in entry.get("swaps", []):
        frame = round(swap["at"] * FPS)
        out.append((frame, "insert", swap["disk"] - first))
        if "key" in swap and keys:
            delay = swap.get("key_delay", KEY_DELAY)
            out.append((frame + round(delay * FPS), "click",
                        _button(swap["key"])))
    if keys:
        out += [(round(k["at"] * FPS), "click", _button(k["key"]))
                for k in entry.get("keys", [])]
    return sorted(out)


def _button(key):
    if key not in BUTTONS:
        raise CannotPlay(f"no way to press key {key!r}")
    return BUTTONS[key]


def loaded(samples, inserts, unit=0):
    """For each insert frame: was that disk loaded before the next one went
    in? Read after its insert, and the head then past LOADED_CYL."""
    out = []
    for i, frame in enumerate(inserts):
        until = inserts[i + 1] if i + 1 < len(inserts) else float("inf")
        out.append(any(frame < s.frame <= until and s.last_dma > frame
                       and s.cyls[unit] >= LOADED_CYL for s in samples))
    return out


def judge(written, plain):
    """What two runs say about an entry: ``written`` and ``plain`` are the
    loaded() of the run as written and of the run without the keys (None
    when the entry has no keys)."""
    if plain is not None and all(plain):
        return "keys not needed"
    if not all(written):
        return "does not replay"
    return "replays" if plain is None else "keys needed"


def variant_of(prod, entry):
    """The media of the entry: the first of the download's variants with
    the disk file names and the ``run`` file it names. An entry that names
    neither is the first variant of its ``boot`` kind (the kind of the
    production's first variant when it does not say). Raises CannotPlay
    when there is none: never another variant in its place."""
    variants, problems = media.variants(prod, entry["title"])
    if not variants:
        raise CannotPlay("no media: " + "; ".join(problems))
    named = {k: entry[k] for k in ("disks", "run") if entry.get(k)}
    if named:
        wanted = " and ".join(f"{k} {v!r}" for k, v in named.items())
        fits = [v for v in variants
                if all(_names(v)[k] == name for k, name in named.items())]
    else:
        kind = entry.get("boot", variants[0].kind)
        wanted = f"a {kind} boot"
        fits = [v for v in variants if v.kind == kind]
    if not fits:
        raise CannotPlay(f"{wanted} is not among the download's variants")
    return fits[0]


def _names(variant):
    """What an entry can name of ``variant``, as the export writes it."""
    return {"disks": [os.path.basename(d) for d in variant.disks],
            "run": media.run_file(variant.note, variant.command)}


def play(machine, variant, entry, keys):
    """One run. Returns ``(verdict name, loaded per swap)``."""
    acts = actions(entry, keys)
    inserts = [f for f, what, _ in acts if what == "insert"]
    # As long as the run as written, keys or not.
    frames = actions(entry)[-1][0] + TAIL_FRAMES
    log = emulator.run(machine, variant, frames, emulator.Options(
        drives=entry.get("drives", 1), play=acts))
    v = verdict.classify(log, frames // 250)
    # With no disk to put in, the run itself is the evidence.
    return v.verdict, loaded(log.samples, inserts) or [v.verdict == "works"]


def all_entries(data):
    """``{id: entry}`` of every Demozoo production in the data files."""
    out = {}
    for path in sorted(data.glob("*.toml")):
        if path.name != presets.FILE:
            for key, e in tomllib.loads(path.read_text("utf-8")) \
                    .get("demozoo", {}).items():
                out[int(key)] = e
    return out


def entries(data):
    """``{id: entry}`` of the Demozoo productions that have swaps or keys."""
    return {p: e for p, e in all_entries(data).items()
            if e.get("swaps") or e.get("keys")}


def _has_keys(entry):
    return bool(entry.get("keys")) or \
        any("key" in s for s in entry.get("swaps", []))


def _one(prod, entry, default):
    """``(ok, report line)`` of one production: not ok when something it
    needs is missing, and the line says what."""
    try:
        machine = machines.BY_NAME[entry.get("machine", default)]
        variant = variant_of(prod, entry)
        runs = [("as written", play(machine, variant, entry, True))]
        if _has_keys(entry):
            runs.append(("without keys", play(machine, variant, entry, False)))
    except CannotPlay as e:
        return False, f"{prod} {entry['title']}: error: {e}"
    said = judge(runs[0][1][1], runs[1][1][1] if len(runs) > 1 else None)
    detail = "; ".join(
        f"{name}: {v}, disks loaded "
        + "".join("y" if ok else "n" for ok in got) for name, (v, got) in runs)
    return True, f"{prod} {entry['title']}: {said} ({detail})"


def run(ids=None, data=None, jobs=None, log=print):
    """Replay the productions ``ids``; without ids, every entry that has a
    key, on a swap or of its own. Returns how many could not be played."""
    data = data or config.DATA_DIR
    default = default_machine(data)
    found = entries(data)
    todo = {p: e for p, e in found.items()
            if (p in ids if ids else _has_keys(e))}
    for p in sorted(set(ids or ()) - set(found)):
        log(f"{p}: no entry with swaps or keys")
    # Two emulators per production, each about two cores.
    jobs = jobs or max(1, (os.cpu_count() or 4) // 4)
    errors = 0
    with cf.ThreadPoolExecutor(jobs) as pool:
        for ok, line in pool.map(lambda pe: _one(*pe, default),
                                 sorted(todo.items())):
            errors += not ok
            log(line, flush=True)
    return errors
