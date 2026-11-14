"""Run every production's variants up the machine ladder."""

import concurrent.futures as cf
import dataclasses
import os
import traceback

from . import bootfile, machines, media, runner, verdict

PAL_HZ = 985_248
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


def _job(prod, multi_only=False, pick_boot=False):
    """Worker: build the production's variants and climb each one."""
    try:
        variants, problems = media.variants(prod)
        if multi_only:
            variants = [v for v in variants if len(v.disks) > 1]
        results = [climb_variant(prod, v, pick_boot) for v in variants]
        return prod, variants, problems, results, None
    except Exception:  # noqa: BLE001 - reported per production
        return prod, [], [], [], traceback.format_exc()


def run_all(prods, store, jobs=None, multi_only=False, pick_boot=False,
            log=print):
    jobs = jobs or max(1, (os.cpu_count() or 2) * 3 // 4)
    done = store.done_productions()
    todo = [p for p in prods if p.id not in done]
    log(f"{len(todo)} productions to run ({len(prods) - len(todo)} done), "
        f"{jobs} jobs")
    with cf.ProcessPoolExecutor(jobs) as pool:
        futs = [pool.submit(_job, p, multi_only, pick_boot) for p in todo]
        for n, fut in enumerate(cf.as_completed(futs), 1):
            prod, variants, problems, results, err = fut.result()
            if err:
                problems = problems + [f"internal-error: {err.splitlines()[-1]}"]
                log(err)
            store.put_production(prod, problems)
            ids = store.put_variants(prod.id, variants)
            for i, (vid, (attempts, best)) in enumerate(zip(ids, results)):
                best_id = None
                for a in attempts:
                    rid = store.put_run(vid, a)
                    if a is best:
                        best_id = rid
                store.finish_variant(vid, best_id, best.machine,
                                     best.verdict.verdict)
                store.put_windows(prod.id, i, best.log.flips)
            summary = ", ".join(
                f"{b.machine}:{b.verdict.verdict}"
                + (f" {b.reached}/{len(v.disks)} disks" if len(v.disks) > 1 else "")
                for v, (_, b) in zip(variants, results)) or \
                "; ".join(problems) or "-"
            log(f"[{n}/{len(todo)}] {prod.id} {prod.title} -> {summary}",
                flush=True)
