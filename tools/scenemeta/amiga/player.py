"""The Amiga player: the only way from an entry of the data files
(``data/amiga``, see docs/DESIGN.md) to an emulator run. ``play`` resolves the
entry's machine and media, puts each disk in at its time, presses each key
after its insert and each key of ``keys`` at its time, and returns what
happened. Nothing is detected and nothing retried, so a run shows what the
entry says, not what a sweep can find.
"""

import concurrent.futures as cf
import dataclasses

from ..core import gate
from ..core.errors import BadEntry, CannotPlay
from . import emulator, machines, media, verdict
from .machines import FPS

# Raised with every change to what a run of an entry shows: what the gate
# saw by another version is seen again (see core.gatelog.stale).
VERSION = "2"
KEY_DELAY = 5.0      # seconds from an insert to its key, when not given
# Keep going this long after the last insert or key, to see the disk load.
TAIL_FRAMES = emulator.AUTOSWAP_TAIL_FRAMES
# An entry with no swaps or keys is watched this long.
PLAIN_FRAMES = 9000
# A disk is loaded when it was read with the head past its first cylinders:
# cylinders 0 and 1 are where a demo checks which disk is in.
LOADED_CYL = 2
# The verdicts of a production that came alive.
RAN = ("works", "works-short", "works-then-crash")


@dataclasses.dataclass(frozen=True)
class Outcome:
    """What a run of an entry showed."""
    machine: str                # the preset it ran on
    verdict: verdict.Verdict
    loaded: list                # per swap that went in: was that disk loaded?
    log: emulator.RunLog
    record: gate.Play = None    # the same, as every platform reports it


@dataclasses.dataclass(frozen=True)
class Ready:
    """An entry with its machine and media found: ``play`` runs it, as
    often as wanted."""
    entry: dict
    machine: machines.Machine
    variant: media.Variant

    def play(self, keys=True, keep=None, seed=emulator.DEFAULT_SEED,
             frames=None):
        """Play the entry as written. Without ``keys`` the disks go in and
        nothing is pressed, in a run as long. ``keep`` is a directory for
        the pictures of the run, ``seed`` the emulator's (see
        emulator.Options), ``frames`` how long when not the entry's own
        time (see ``frames_of``)."""
        acts = actions(self.entry, keys)
        frames = frames or frames_of(self.entry)
        log = emulator.run(self.machine, self.variant, frames, emulator.Options(
            drives=self.entry.get("drives", 1), play=tuple(acts), detect=False,
            keep=keep, seed=seed))
        inserts = [(f, i) for f, what, i in acts if what == "insert"]
        v = verdict.classify(log, frames // 250)
        took = loaded(log.samples, [f for f, _ in inserts])
        first = self.entry.get("drives", 1) + 1
        return Outcome(self.machine.name, v, took, log, gate.Play(
            v.verdict in RAN, v.crash,
            tuple(gate.SwapTaken(first + i, ok)
                  for (_, i), ok in zip(inserts, took)),
            last_read(log.samples)))


def ready(prod, entry, default):
    """``entry`` of production ``prod`` ready to play, on machine
    ``default`` when it names none. Raises CannotPlay, before any emulator
    starts, when something its run needs is missing."""
    name = entry.get("machine", default)
    if name not in machines.BY_NAME:
        raise BadEntry(f"no machine {name!r}")
    machine = machines.BY_NAME[name]
    if not 1 <= entry.get("drives", 1) <= emulator.MAX_DRIVES:
        raise BadEntry(f"no machine with {entry['drives']} drives")
    # What costs nothing to find missing, before the download is unpacked.
    machines.require_rom(machine)
    actions(entry)
    return Ready(entry, machine, _variant_of(prod, entry))


def play(prod, entry, default, keys=True, keep=None):
    """Play ``entry`` of production ``prod`` once: see ``ready`` and
    ``Ready.play``."""
    return ready(prod, entry, default).play(keys, keep)


def each_played(todo, one, jobs):
    """Play every ``(prod, entry)`` of ``todo``, ``jobs`` at a time. Yields
    of each, in order, ``(prod, True, one(prod, entry))``, or ``(prod,
    False, line)`` with the line that reports why it cannot be played.
    Raises CannotPlay when there is no mirror to play any of them from."""
    media.require_mirror()

    def report(prod, entry):
        try:
            return prod, True, one(prod, entry)
        except CannotPlay as e:
            return prod, False, f"{prod} {entry['title']}: error: {e}"

    with cf.ThreadPoolExecutor(jobs) as pool:
        yield from pool.map(lambda pe: report(*pe), todo)


def play_each(todo, one, jobs, log=print):
    """Log the report line ``one(prod, entry)`` returns of each entry
    played (see ``each_played``). Returns how many could not be played."""
    errors = 0
    for _, ok, line in each_played(todo, one, jobs):
        errors += not ok
        log(line, flush=True)
    return errors


def actions(entry, keys=True):
    """What to do when, for emulator.Options' ``play``. Without ``keys`` the
    disks go in and nothing is pressed. Raises BadEntry for a key that
    cannot be pressed and for a swap of a disk that cannot go in."""
    out = []
    first = entry.get("drives", 1) + 1      # the first disk that is swapped in
    last = len(entry.get("disks", ()))
    for swap in entry.get("swaps", []):
        if not first <= swap["disk"] <= last:
            # A disk that sits in a drive from the start is not swapped in.
            raise BadEntry(
                f"no way to put in disk {swap['disk']}: " + (
                    f"the disks to put in are {first} to {last}"
                    if first <= last else "there is none to put in"))
        frame = round(swap["at"] * FPS)
        out.append((frame, "insert", swap["disk"] - first))
        if "key" in swap and keys:
            delay = swap.get("key_delay", KEY_DELAY)
            out.append((frame + round(delay * FPS), "press",
                        _key(swap["key"])))
    if keys:
        out += [(round(k["at"] * FPS), "press", _key(k["key"]))
                for k in entry.get("keys", [])]
    return sorted(out)


def _key(key):
    if key not in emulator.KEYS:
        raise BadEntry(f"no way to press key {key!r}: the keys are "
                       + ", ".join(emulator.KEYS))
    return key


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


def last_read(samples):
    """When a disk was last read, in seconds: how far a run got, for the
    gate. A production that goes on after a key reads later than one left
    waiting for it."""
    return max((s.last_dma for s in samples), default=-1) / FPS


def _variant_of(prod, entry):
    """The media of the entry: the one variant of the download that the
    ``boot``, ``disks`` and ``run`` the entry has describe (see media.fits).
    Raises CannotPlay when the download has no media, BadEntry when no
    variant fits or more than one does: never another variant in the
    entry's place. No variant fitting is a BadEntry only when all of the
    download was there to look at; when some of it gave nothing it is a
    CannotPlay that says what."""
    said = {k: entry[k] for k in ("boot", "disks", "run") if entry.get(k)}
    # As the media picks today first. Asked to start the entry's ``run``,
    # every tree that holds the file starts it, and two that were told
    # apart by what they pick are the same: only when nothing fits.
    for run in dict.fromkeys((None, said.get("run"))):
        found, problems = _fitting(prod, entry["title"], said, run)
        if found:
            break
    if len(found) == 1:
        return found[0]
    wanted = " and ".join(f"{k} {v!r}" for k, v in said.items()) \
        or "an entry with no boot, disks or run"
    if found:
        raise BadEntry(f"{wanted} fits {len(found)} of the download's variants"
                       f" ({', '.join(v.label for v in found)}): its disks or"
                       " run have to say which")
    if problems:
        raise CannotPlay(f"{wanted} fits none of the download's variants, and"
                         " not all of it gave one: " + "; ".join(problems))
    raise BadEntry(f"{wanted} fits none of the download's variants")


def _fitting(prod, title, said, run):
    """``(found, problems)``: the variants of the download that fit what
    the entry says, the media asked to start ``run``, and what of the
    download gave no variant. The download's own variants are looked at
    first; the other ways to run them (see media.fallbacks) when none of
    those fits, and of them only the kind the entry is of."""
    variants, problems = media.variants(prod, title, run)
    if not variants:
        raise CannotPlay("no media: " + "; ".join(problems))
    first = variants[0].kind
    found = [v for v in variants if media.fits(v, said, first)]
    if not found:
        for v in variants:
            for kind, make in media.fallbacks(v, prod, title, run):
                if kind != said.get("boot", first):
                    continue
                made = make()
                if made is None:
                    problems.append(f"{v.label}: no other {kind} to run it from")
                elif media.fits(made, said, first):
                    found.append(made)
    return found, problems
