"""Play one C64 entry literally; no discovery, automatic answers or retries.

Hardware translation, event validation and media selection happen before VICE
starts. The observation runner returns the same core Play as the Amiga.
"""

import dataclasses
import math
import pathlib
import shutil

from .. import events
from ..core import export, playback
from ..core.errors import BadEntry, CannotPlay
from . import bootfile, config, machines, media
from .keymap import NAMES as KEYS

VERSION = "1"
PLAIN_SECONDS = 180
TAIL_SECONDS = 150
PATIENCE = 30


def actions(entry, patient=False):
    """Validated events in emulated seconds, with patient windows applied."""
    out = []
    does = entry.get("events", ())
    for e in does:
        at, until = e.get("at"), e.get("until", e.get("at"))
        if (not isinstance(at, (int, float)) or isinstance(at, bool)
                or not math.isfinite(at) or at < 0
                or not isinstance(until, (int, float)) or isinstance(until, bool)
                or math.isnan(until) or until < at):
            raise BadEntry("event times must be nonnegative, with until >= at")
    for e in events.patient(does, PATIENCE) if patient else events.ordered(does):
        if "key" in e and "disk" not in e:
            if e["key"] not in KEYS or "pos" in e:
                raise BadEntry(f"no way to press key {e['key']!r}")
        elif "disk" in e and "key" not in e:
            if e.get("drive", 1) != 1:
                raise BadEntry(f"no C64 drive {e['drive']}")
            if (not isinstance(e["disk"], int) or isinstance(e["disk"], bool)
                    or not 1 <= e["disk"] <= len(entry.get("disks", ()))):
                raise BadEntry(f"no disk {e['disk']} in the entry")
        else:
            raise BadEntry("an event must be a disk or a key")
        out.append(dict(e))
    return out


def seconds_of(entry, patient=False):
    acts = actions(entry, patient)
    return acts[-1]["at"] + TAIL_SECONDS if acts else PLAIN_SECONDS


@dataclasses.dataclass(frozen=True)
class Ready:
    entry: dict
    machine: machines.Machine
    variant: media.Variant

    def play(self, seed=1, seconds=None, patient=False):
        from . import entryrunner
        return entryrunner.run(self.machine, self.variant,
                               actions(self.entry, patient),
                               seconds or seconds_of(self.entry, patient), seed)


def ready(prod, entry, default, presets=None):
    if presets is None:
        _, presets = export.presets(config.DATA_DIR)
    machine = machines.resolve(entry, default, presets)
    actions(entry)
    first = entry.get("boot_disk", 1)
    if not isinstance(first, int) or isinstance(first, bool) or first < 1:
        raise BadEntry("boot_disk must be a positive integer")
    for field in ("boot_file", "run"):
        if field in entry and any(c in entry[field] for c in ('"', "\n", "\r")):
            raise BadEntry(f"invalid {field}")
    for field in ("boot", "assign"):
        if field in entry:
            raise BadEntry(f"C64 playback does not support {field}")
    machines.require_roms(config.ROM_DIR)
    if not shutil.which(config.VICE) or not shutil.which("xvfb-run"):
        raise CannotPlay("C64 playback needs x64sc and xvfb-run")
    return Ready(entry, machine, _variant_of(prod, entry))


def _variant_of(prod, entry):
    variants, problems = media.playables(media.production(prod))
    if not variants:
        raise CannotPlay("no C64 media: " + "; ".join(problems))
    matches = []
    for variant in variants:
        paths = list(variant.disks)
        names = entry.get("disks")
        if names:
            ordered = []
            for name in names:
                fits = [p for p in paths if pathlib.Path(p).name == name]
                if len(fits) != 1:
                    break
                ordered.append(fits[0])
            else:
                paths = ordered
            if len(ordered) != len(names):
                continue
        if run := entry.get("run"):
            if variant.kind in ("prg", "crt"):
                if pathlib.Path(paths[0]).name != run:
                    continue
            elif entry.get("boot_file", run) != run:
                raise BadEntry("run and boot_file disagree")
        first = entry.get("boot_disk", 1) - 1
        if not 0 <= first < len(paths):
            raise BadEntry("boot_disk is outside the entry's media")
        file = entry.get("boot_file", entry.get("run", "")) if variant.kind == "floppy" else ""
        if variant.kind != "floppy" and (any(
                "disk" in e for e in entry.get("events", ())) or entry.get("boot_file")):
            continue
        if file and file not in bootfile.listing(paths[first]):
            continue
        matches.append(dataclasses.replace(variant, disks=paths,
                                            boot_disk=first, boot_file=file))
    if len(matches) != 1:
        raise BadEntry(f"entry fits {len(matches)} C64 media variants; name disks or run")
    return matches[0]


def play(prod, entry, default, **kwargs):
    return ready(prod, entry, default).play(**kwargs)


def each_played(todo, one, jobs):
    media.require_mirror()
    yield from playback.each_played(todo, one, jobs)
