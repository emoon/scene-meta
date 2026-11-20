"""The Amiga player: the only way from an entry of the data files
(``data/amiga``, see docs/DESIGN.md) to an emulator run. ``play`` resolves the
entry's machine and media, puts each disk in at its time, presses each key
after its insert and each key of ``keys`` at its time, and returns what
happened. Nothing is detected and nothing retried, so a run shows what the
entry says, not what a sweep can find.
"""

import concurrent.futures as cf
import dataclasses

from ..core.errors import BadEntry, CannotPlay
from . import emulator, machines, media, verdict
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


@dataclasses.dataclass(frozen=True)
class Ready:
    """An entry with its machine and media found: ``play`` runs it, as
    often as wanted."""
    entry: dict
    machine: machines.Machine
    variant: media.Variant

    def play(self, keys=True, keep=None):
        """Play the entry as written. Without ``keys`` the disks go in and
        nothing is pressed, in a run as long. ``keep`` is a directory for
        the pictures of the run (see emulator.Options)."""
        acts = actions(self.entry, keys)
        frames = frames_of(self.entry)
        log = emulator.run(self.machine, self.variant, frames, emulator.Options(
            drives=self.entry.get("drives", 1), play=tuple(acts), detect=False,
            keep=keep))
        inserts = [f for f, what, _ in acts if what == "insert"]
        return Outcome(self.machine.name, verdict.classify(log, frames // 250),
                       loaded(log.samples, inserts), log)


def ready(prod, entry, default):
    """``entry`` of production ``prod`` ready to play, on machine
    ``default`` when it names none. Raises CannotPlay, before any emulator
    starts, when something its run needs is missing."""
    name = entry.get("machine", default)
    if name not in machines.BY_NAME:
        raise BadEntry(f"no machine {name!r}")
    machine = machines.BY_NAME[name]
    # What costs nothing to find missing, before the download is unpacked.
    machines.require_rom(machine)
    actions(entry)
    return Ready(entry, machine, _variant_of(prod, entry))


def play(prod, entry, default, keys=True, keep=None):
    """Play ``entry`` of production ``prod`` once: see ``ready`` and
    ``Ready.play``."""
    return ready(prod, entry, default).play(keys, keep)


def play_each(todo, one, jobs, log=print):
    """Play every ``(prod, entry)`` of ``todo``, ``jobs`` at a time:
    ``one(prod, entry)`` plays it and returns its report line. An entry that
    cannot be played is reported as an error. Returns how many were.
    Raises CannotPlay when there is no mirror to play any of them from."""
    media.require_mirror()

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
        raise BadEntry(f"no way to press key {key!r}")
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
    """The media of the entry: the one variant of the download an export
    describes by the ``boot``, ``disks`` and ``run`` the entry has (see
    media.named). The download's own variants are looked at first; the
    other ways to run them, which a sweep tries when they do not work,
    when none of those fits. Raises CannotPlay when the download has no
    media, BadEntry when no variant fits or more than one does: never
    another variant in the entry's place."""
    title, run = entry["title"], entry.get("run")
    variants, problems = media.variants(prod, title, run)
    if not variants:
        raise CannotPlay("no media: " + "; ".join(problems))
    said = {k: entry[k] for k in ("boot", "disks", "run") if entry.get(k)}
    first = variants[0].kind

    def fits(found):
        return [v for v in found if media.named(v, first) == said]

    found = fits(variants) or fits(
        made for v in variants
        for make in media.fallbacks(v, prod, title, run) if (made := make()))
    if len(found) == 1:
        return found[0]
    wanted = " and ".join(f"{k} {v!r}" for k, v in said.items()) \
        or "an entry with no boot, disks or run"
    if not found:
        raise BadEntry(f"{wanted} fits none of the download's variants")
    raise BadEntry(f"{wanted} fits {len(found)} of the download's variants ("
                   + ", ".join(v.label for v in found)
                   + "): it does not say which")
