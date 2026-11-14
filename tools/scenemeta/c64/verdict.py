"""Classify one run from its samples: did the demo work on this machine?

A sample is *alive* when the screen changed since the previous one and the
C64 is not sitting at the BASIC prompt (whose cursor blinks). A run *works*
when it collects WORKS_ALIVE cycles of alive time before any crash.
"""

import dataclasses

WORKS_ALIVE = 20_000_000   # about 20 s of C64 time with a moving screen
ENDED_QUIET = 20_000_000   # trailing static time that means the demo stopped


@dataclasses.dataclass
class Verdict:
    verdict: str          # works | works-then-crash | crash | no-activity | error
    alive: int            # alive cycles
    crash: str = None     # jam | emulator-exit | timeout
    crash_cycles: int = None
    ended_cycles: int = None   # last alive point when the run ends static
    wants_disk: bool = False   # asked for a disk beyond the set

    @property
    def works(self):
        return self.verdict == "works"


def alive_flags(samples, basic):
    """Per sample: moved on screen and not at BASIC. ``basic`` is the set of
    sample indexes whose screen showed the BASIC prompt."""
    flags, prev = [], None
    for i, s in enumerate(samples):
        changed = prev is not None and s.shot and s.shot != prev
        flags.append(bool(changed) and i not in basic)
        prev = s.shot or prev
    return flags


def _alive_cycles(samples, flags, limit=None):
    total, prev = 0, 0
    for s, f in zip(samples, flags):
        if f and (limit is None or s.cycles <= limit):
            total += s.cycles - prev
        prev = s.cycles
    return total


def classify(samples, basic, crash=None, crash_cycles=None, wants_disk=False):
    if not samples:
        return Verdict("error", 0, crash=crash or "no-samples")
    flags = alive_flags(samples, basic)
    alive = _alive_cycles(samples, flags, crash_cycles)
    if alive >= WORKS_ALIVE:
        v = "works" if crash is None else "works-then-crash"
    else:
        v = "crash" if crash else "no-activity"
    ended = None
    last = max((i for i, f in enumerate(flags) if f), default=None)
    if last is not None and samples[-1].cycles - samples[last].cycles >= ENDED_QUIET:
        ended = samples[last].cycles
    return Verdict(v, alive, crash, crash_cycles, ended, wants_disk)
