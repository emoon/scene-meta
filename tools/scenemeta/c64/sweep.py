"""Run every production's variants up the machine ladder."""

import dataclasses
import functools

from ..core import result, sweep as driver
from . import bootfile, machines, media, runner, verdict
from .machines import PAL_HZ

SINGLE_DISK_CYCLES = 3 * 60 * PAL_HZ     # 3 minutes of a demo
# A disk can play for a long time before asking for the next one. Runs stop
# early once the last disk has been in for runner.TAIL cycles.
PER_DISK_CYCLES = 12 * 60 * PAL_HZ
MAX_CYCLES = 45 * 60 * PAL_HZ


def budget(variant):
    n = len(variant.disks)
    return SINGLE_DISK_CYCLES if n <= 1 else min(PER_DISK_CYCLES * n, MAX_CYCLES)


@dataclasses.dataclass
class Attempt:
    machine: str
    budget: int
    verdict: verdict.Verdict
    log: runner.RunLog

    @property
    def reached(self):
        """Disks of the set the demo got to: disk 1 plus each accepted flip."""
        return 1 + len(self.log.accepted)

    @property
    def rank(self):
        # Disks reached first: a flip only counts once the demo read the new
        # disk, so a run that got further found the real schedule, even if
        # something later (often the end of the demo) looks like a crash.
        return (self.reached, self.verdict.verdict == "works", self.verdict.alive)

    def record(self):
        """The run as the store keeps it: cycles to seconds."""
        hz = machines.hz(self.machine)

        def seconds(cycles):
            return None if cycles is None else cycles / hz
        v, log = self.verdict, self.log
        return result.Run(
            self.machine, seconds(self.budget), v.verdict, seconds(v.alive),
            v.crash, seconds(v.crash_cycles), seconds(v.ended_cycles),
            v.wants_disk, 1, self.reached,
            [result.Swap(f.disk, seconds(f.inserted), f.trigger, f.accepted,
                         seconds(f.waiting_since), f.key, seconds(f.key_at),
                         f.shot)
             for f in log.flips],
            {"log": log.detail, "asked_disk": seconds(log.asked_disk)},
            log.last_shot)


def attempt(machine, variant, cycles):
    log = runner.run(machine, variant, cycles)
    v = verdict.classify(log.samples, log.basic, log.crash, log.crash_cycles,
                         log.wants_disk)
    return Attempt(machine.name, cycles, v, log)


def climb(variant):
    """Run ``variant`` up the ladder until a machine works.

    Returns ``(attempts, best)``: every Attempt made, and the chosen one.
    """
    cycles = budget(variant)
    attempts = []
    reu_asked = False
    for m in machines.LADDER:
        if m.reu and not reu_asked:
            continue          # only for a demo that said it needs one
        if reu_asked and not m.reu:
            continue          # a demo that needs a REU fails on the others
        attempts.append(attempt(m, variant, cycles))
        if attempts[-1].log.needs_reu and not m.reu:
            reu_asked = True
        elif attempts[-1].verdict.works:
            return attempts, attempts[-1]
    # Nothing worked cleanly: the cheapest machine that ran for a while before
    # crashing, else the one that got furthest.
    for a in attempts:
        if a.verdict.verdict == "works-then-crash":
            return attempts, a
    return attempts, max(attempts, key=lambda a: a.rank)


def choose_boot(prod, variant):
    """Point a compilation variant at the file that holds ``prod``, if any."""
    listings = [bootfile.listing(d) for d in variant.disks]
    found = bootfile.pick(prod.title, listings)
    if found and found != (0, next(iter(listings[0]), None)):      # not what autostart runs anyway
        variant.boot_disk, variant.boot_file = found


def climb_variant(prod, variant, pick_boot=False):
    """``climb`` ``variant``; a variant that did not work is tried again with
    the file named like the production when that differs from autostart's."""
    if pick_boot:
        choose_boot(prod, variant)
    attempts, best = climb(variant)
    if not best.verdict.works and not variant.boot_file:
        choose_boot(prod, variant)
        if variant.boot_file:
            more, again = climb(variant)
            attempts += more
            if again.rank > best.rank:
                best = again
            else:
                variant.boot_disk, variant.boot_file = 0, ""
    return attempts, best


def _record(v, attempts, best):
    """Variant ``v`` and its runs as the store keeps them."""
    return result.Variant(
        v.kind, v.disks, v.note,
        {"boot_disk": v.boot_disk, "boot_file": v.boot_file},
        [a.record() for a in attempts],
        next(i for i, a in enumerate(attempts) if a is best))


def _job(prod, multi_only=False, pick_boot=False):
    """Worker: build the production's variants and climb each one."""
    variants, problems = media.variants(prod)
    if multi_only:
        variants = [v for v in variants if len(v.disks) > 1]
    # The record is made after the climb: it settles the variant's boot file.
    return problems, [_record(v, *climb_variant(prod, v, pick_boot))
                      for v in variants]


def run_all(prods, store, jobs=None, multi_only=False, pick_boot=False,
            log=print):
    driver.run_all(prods, store, functools.partial(
        _job, multi_only=multi_only, pick_boot=pick_boot), jobs, log)
