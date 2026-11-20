"""The Amiga player: the only way from an entry of the data files
(``data/amiga``, see docs/DESIGN.md) to an emulator run. ``play`` resolves the
entry's machine and media, puts each disk in at its time, presses each key
after its insert and each key of ``keys`` at its time, and returns what
happened. Nothing is detected and nothing retried, so a run shows what the
entry says, not what a sweep can find.
"""

import concurrent.futures as cf
import dataclasses
import os

from . import emulator, machines, media, verdict
from ..core.errors import CannotPlay
from .machines import FPS

KEY_DELAY = 5.0      # seconds from an insert to its key, when not given
BUTTONS = {"lmb": 0}
# Keep going this long after the last insert or key, to see the disk load.
TAIL_FRAMES = emulator.AUTOSWAP_TAIL_FRAMES
# An entry with no swaps or keys is watched this long.
PLAIN_FRAMES = 9000
# A disk is loaded when it was read with the head past its first cylinders:
# cylinders 0 and 1 are where a demo checks which disk is in.
LOADED_CYL = 2


@dataclasses.dataclass(frozen=True)
class Outcome:
    """What a run of an entry showed."""
    machine: str                # the preset it ran on
    verdict: verdict.Verdict
    loaded: list                # per swap that went in: was that disk loaded?
    log: emulator.RunLog


def play(prod, entry, default, keys=True, keep=None):
    """Play ``entry`` of production ``prod`` as written, on machine
    ``default`` when it names none. Without ``keys`` the disks go in and
    nothing is pressed, in a run as long. ``keep`` is a directory for the
    pictures of the run (see emulator.Options). Raises CannotPlay, before
    the emulator starts, when something the run needs is missing."""
    name = entry.get("machine", default)
    machine = machines.BY_NAME[name]
    variant = _variant_of(prod, entry)
    acts = actions(entry, keys)
    frames = frames_of(entry)
    log = emulator.run(machine, variant, frames, emulator.Options(
        drives=entry.get("drives", 1), play=tuple(acts), detect=False,
        keep=keep))
    inserts = [f for f, what, _ in acts if what == "insert"]
    return Outcome(name, verdict.classify(log, frames // 250),
                   loaded(log.samples, inserts), log)


def play_each(todo, one, jobs, log=print):
    """Play every ``(prod, entry)`` of ``todo``, ``jobs`` at a time:
    ``one(prod, entry)`` plays it and returns its report line. An entry that
    cannot be played is reported as an error. Returns how many were."""
    def report(prod, entry):
        try:
            return True, one(prod, entry)
        except CannotPlay as e:
            return False, f"{prod} {entry['title']}: error: {e}"

    errors = 0
    with cf.ThreadPoolExecutor(jobs) as pool:
        for ok, line in pool.map(lambda pe: report(*pe), todo):
            errors += not ok
            log(line, flush=True)
    return errors


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


def frames_of(entry):
    """How long ``entry`` is played: until the last disk of the entry as
    written, keys and all, has had time to load; else the time an entry
    with nothing to do gets."""
    acts = actions(entry)
    return acts[-1][0] + TAIL_FRAMES if acts else PLAIN_FRAMES


def loaded(samples, inserts, unit=0):
    """For each insert frame: was that disk loaded before the next one went
    in? Read after its insert, and the head then past LOADED_CYL."""
    out = []
    for i, frame in enumerate(inserts):
        until = inserts[i + 1] if i + 1 < len(inserts) else float("inf")
        out.append(any(frame < s.frame <= until and s.last_dma > frame
                       and s.cyls[unit] >= LOADED_CYL for s in samples))
    return out


def _variant_of(prod, entry):
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
