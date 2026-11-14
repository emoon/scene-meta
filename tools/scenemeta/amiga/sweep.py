"""Run every production's variants up the machine ladder."""

import concurrent.futures as cf
import dataclasses
import functools

from ..core import result, sweep as driver
from . import catalog, emulator, machines, media, verdict
from .machines import FPS

SINGLE_DISK_FRAMES = 9000       # 3 minutes of a demo
# Disks of a set can play for a long time before asking for the next one
# (Desert Dream's disk A: 9 minutes). Runs stop early once the last disk has
# been in for emulator.AUTOSWAP_TAIL_FRAMES.
PER_DISK_FRAMES = 36000         # 12 minutes per disk
MAX_FRAMES = 180000


def budget(variant):
    n = len(variant.disks)
    return SINGLE_DISK_FRAMES if n <= 1 else min(PER_DISK_FRAMES * n, MAX_FRAMES)


@dataclasses.dataclass
class Attempt:
    machine: str
    frames: int
    verdict: verdict.Verdict
    log: emulator.RunLog
    swaps: list
    drives: int = 1
    reached: int = 1      # disks of the set the demo got to
    unit: int = 0         # the drive the rest of the set went into
    click_every: int = 0
    key_every: int = 0
    seed: int = emulator.DEFAULT_SEED

    @property
    def ran(self):
        return self.verdict.verdict in ("works", "works-then-crash")

    @property
    def rank(self):
        # Then disks reached: swaps only count once the demo read the new
        # disk, so a run that got further found the real schedule, even if
        # something later (often the end of the demo) looks like a crash.
        # But only among runs where the demo got going: at a Workbench or
        # CLI the OS itself polls the drive and mounts whatever goes in,
        # which looks like an accepted swap.
        crashed = self.verdict.crash is not None
        # Last, among runs that got equally far: a rung with fast RAM, which
        # a hunk wanting MEMF_FAST needs ("not enough memory" on an a1200),
        # over the rungs that stop at the same screen for lack of it.
        return (self.ran, self.reached, not crashed, self.verdict.alive,
                verdict.progress(self.log.samples),
                machines.BY_NAME[self.machine].fast_ram)

    def record(self):
        """The run as the store keeps it: frames and samples to seconds."""
        def seconds(frames):
            return None if frames is None else frames / FPS
        v, log = self.verdict, self.log
        return result.Run(
            self.machine, seconds(self.frames), v.verdict,
            seconds(v.alive * SAMPLE_FRAMES), v.crash, seconds(v.crash_frame),
            seconds(v.ended_frame), v.wants_disk, self.drives, self.reached,
            [result.Swap(disk, seconds(frame), how,
                         key="lmb" if "click" in how else None)
             for frame, disk, how in self.swaps],
            {"returncode": log.returncode, "events": log.events}, log.last_shot)


CLICK_EVERY = 1500    # 30 s between nudges on the click retry


def waits_for_click(tries):
    """Did the first attempt stop at a screen a mouse click might get past?
    Not after a crash: the quiet screen is then a Guru Meditation, and the
    click restarts the machine (the retry would only show the demo's start
    again, as a reboot)."""
    first = tries[0]
    return (not any(a.verdict.works for a in tries)
            and first.verdict.crash is None
            and verdict.quiet_tail(first.log))


SAMPLE_FRAMES = 250        # emulator.run's sampling interval
QUIET_BEFORE_SWAP = 1500   # a scheduled insert goes in 30 s after the last read


def clicks_to_start(a):
    """How many of ``a``'s clicks it took to get the demo going, when it
    then crashed; else 0. An intro that waits for a click to start may
    quit on the next one, into a Guru (Nice): clicking that many times
    and no more lets it play."""
    if not a.click_every or a.verdict.crash is None:
        return 0
    flags = verdict.alive_flags(a.log.samples)
    first = next((s.frame for f, s in zip(flags, a.log.samples) if f), None)
    return 0 if first is None else (first - 1) // a.click_every


def attempt(m, variant, frames, drives=1, triggers="", click_every=0,
            schedule=(), unit=0, detect=True, max_clicks=0, key_every=0,
            seed=emulator.DEFAULT_SEED, swap_click=True, nudge_until=0):
    log = emulator.run(m, variant, frames, drives=drives, triggers=triggers,
                       click_every=click_every, schedule=schedule, unit=unit,
                       detect=detect, max_clicks=max_clicks,
                       key_every=key_every, seed=seed, swap_click=swap_click,
                       nudge_until=nudge_until)
    log.events.append({"event": "seed", "seed": seed})
    v = verdict.classify(log, frames // 250)
    sw = verdict.swaps(log)
    reached = verdict.disks_reached(log, verdict.played_swaps(log, sw, v),
                                    drives, len(variant.disks))
    return Attempt(m.name, frames, v, log, sw, drives, reached, unit,
                   click_every, key_every, seed)


def try_machine(m, variant, frames):
    """One machine, plus the retries a demo may need to get going or to
    reach the last disk of its set. Retries that do not depend on each
    other run at once, in waves. Every attempt is returned; the last one
    is the best."""
    n = len(variant.disks)
    tries = [attempt(m, variant, frames)]
    asked = [{}]    # the arguments of each attempt, to run one again

    def short():
        # Swaps in runs that never got going are the OS mounting disks.
        return n > 1 and max((a.reached for a in tries if a.ran), default=0) < n

    def stalled():
        return waits_for_click(tries)

    def wave(*kws):
        # Every attempt rolls its own seed, as the wall clock did before
        # runs were pinned: a demo that races may get going on another.
        # Retries that continue a base run say its seed.
        kws = [{"seed": emulator.DEFAULT_SEED + len(tries) + i, **kw}
               for i, kw in enumerate(kws)]
        with cf.ThreadPoolExecutor(len(kws) or 1) as pool:
            got = list(pool.map(
                lambda kw: attempt(m, variant, frames, **kw), kws))
        tries.extend(got)
        asked.extend(kws)
        return got

    first = []
    if short():
        # Waits the default detector cannot see: re-reading one track
        # until the disk changes, then a prompt with the head parked
        # mid-disk (the idle trigger can also fire in a quiet stretch).
        first += [dict(triggers="reread"),
                  dict(triggers="reread anycyl static")]
        # Early swaps on the OS's own drive polling (a DOS-loaded demo
        # playing from RAM) broke the demo: Dark Ages, the AMOS megademos.
        if verdict.swaps(tries[0].log):
            first += [dict(triggers="rampolls"),
                      dict(triggers="rampolls", click_every=CLICK_EVERY)]
    if short() or stalled():
        # "Click mouse button to continue" (AMOS PD intros, "HIT MOUSE!").
        first.append(dict(triggers="reread", click_every=CLICK_EVERY))
    if short() or stalled():
        # Return, Space and fire in turn (Megademo 2's credits page).
        first.append(dict(triggers="reread", key_every=CLICK_EVERY))
    got = wave(*first)
    if not any(a.verdict.works for a in tries):
        wave(*[dict(kw, max_clicks=limit, seed=a.seed) for kw, a in zip(first, got)
               if (limit := clicks_to_start(a))])
    # When clicking is what got the demo going, the later attempts click
    # too (The Wall: its intro waits for a button, then it wants the
    # external drive).
    clicked = [a for a in got if a.click_every]
    clicks = CLICK_EVERY if clicked and \
        max(a.rank for a in clicked) > max(a.rank for a in tries
                                           if not a.click_every) else 0
    # Likewise for the keys (Megademo 2: Return, then it wants disk 2).
    keyed = [a for a in got if a.key_every]
    keys = CLICK_EVERY if keyed and \
        max(a.rank for a in keyed) > max(a.rank for a in tries
                                         if not a.key_every) else 0
    triggers = "reread rampolls" if any(
        "rampolls" in kw.get("triggers", "") and a.rank > tries[0].rank
        for kw, a in zip(first, got)) else "reread"
    second = []
    if short():
        # "Insert disk 2 in any external drive": the set in DF0-DF3.
        second.append(dict(triggers=triggers, click_every=clicks,
                           key_every=keys,
                           drives=min(n, emulator.MAX_DRIVES)))
        # Every later disk in the external drive, one after another (Soho
        # reads disk 2 from DF1, then waits for disk 3 there too).
        if n > 2:
            second.append(dict(triggers=triggers, click_every=clicks,
                               key_every=keys, drives=2, unit=1))
    wave(*second)
    # Nothing ran without the detector getting in the way: run with it off
    # to see where the demo really stops reading, for the swaps below.
    if short() and not any(a.ran for a in tries if a.drives < n):
        wave(dict(detect=False), dict(detect=False, click_every=CLICK_EVERY))
    # Last resort: prompts no detector sees (a still or animated picture,
    # motor left on, no polling). Swap where the demo stops reading the
    # disk that is in, one disk per round, keeping the swaps that worked.
    while short():
        base = max((a for a in tries if a.drives < n), key=lambda a: a.rank)
        got = wave(*[dict(schedule=[f for f, _, _ in base.swaps] + [at],
                          drives=base.drives, unit=base.unit,
                          click_every=base.click_every,
                          key_every=base.key_every, seed=base.seed)
                     for at in swap_frames(base)])
        # Only a running attempt can be the next base: anything else
        # would be retried for ever.
        if not any(a.ran and a.reached > base.reached for a in got):
            break
    best, kw = max(zip(tries, asked), key=lambda t: t[0].rank)
    at = clicked_swap(best)
    if at is not None:
        # The detector clicks whenever a new disk is not loaded from within
        # 5 s, and a slow start then looks like the click's doing (Desert
        # Dream). Only the same run without the click shows it was needed:
        # with nothing pressed at all once that disk is in, a retry's own
        # clicks included (Megademo III).
        plain = wave(dict(kw, seed=best.seed, swap_click=False,
                          nudge_until=at))[0]
        if as_far(plain, best):
            best = plain
    tries = [a for a in tries if a is not best]
    return tries + [best]


def clicked_swap(a):
    """The insert frame of ``a``'s first swap that got a click, or None."""
    return next((f for f, _, how in a.swaps if "click" in how), None)


def as_far(a, b):
    """Did ``a`` get as far as ``b``: running, the same disks, no new crash."""
    return a.rank[:3] >= b.rank[:3]


def swap_frames(a):
    """Where to try putting the next disk in, for attempt ``a``, best guess
    first: 30 s after the last read of the disk that is in now (if the run
    then stays off the drive that long), then the first real pause in
    reading it (The Prey wants disk 2 in "as soon as music starts" and only
    reads it much later, without asking). A run that crashed asking for the
    disk has its last read (that very request) right before the crash, so
    there only the first pause counts, and nothing at or past the crash
    (Absolute Inebriation: loads to 2700, plays, wants disk 2 at 12200)."""
    after = a.swaps[-1][0] if a.swaps else 0
    samples = [s for s in a.log.samples if s.frame > after]
    crash = a.verdict.crash_frame if a.verdict else None
    last_read = max((s.last_dma for s in samples), default=-1)
    end = samples[-1].frame if samples else 0
    out = []
    if last_read > after and end - last_read >= 2 * QUIET_BEFORE_SWAP:
        out.append(last_read + QUIET_BEFORE_SWAP)
    # A pause is QUIET_BEFORE_SWAP frames without a read: a gap between two
    # reads of a part loading is not.
    need = QUIET_BEFORE_SWAP // SAMPLE_FRAMES
    pause = next((s.frame for i, s in enumerate(samples[1:], 1)
                  if s.last_dma > after and all(
                      t.last_dma == s.last_dma for t in samples[i - 1:i + need])
                  and len(samples) > i + need), None)
    if pause is not None and pause not in out:
        out.append(pause)
    return [f for f in out if crash is None or f < crash]


def rungs(variant, aga_only, release_date=None):
    """The machines to try ``variant`` on. A disk that boots from the Fast
    File System cannot be mounted by Kickstart 1.x: only the KS3 rungs."""
    ladder = machines.ladder_for(aga_only, release_date=release_date)
    return [m for m in ladder if m.aga] if variant.ffs else ladder


def climb(variant, aga_only, release_date=None):
    """Run ``variant`` up the ladder until a machine works (and, for a disk
    set, reaches every disk).

    Returns ``(attempts, best)``: every Attempt made, and the chosen one.
    """
    frames = budget(variant)
    attempts, chosen = [], []
    n = len(variant.disks)
    for m in rungs(variant, aga_only, release_date):
        tries = try_machine(m, variant, frames)
        attempts += tries
        chosen.append(tries[-1])
        if tries[-1].verdict.works and tries[-1].reached >= n:
            return attempts, tries[-1]
    # A set that falls short of a clean run with every disk: the cheapest
    # machine that got furthest (Twisted reaches disk 4 only on the 68030;
    # RAF's Megademo reboots at its end, after reaching disk 2).
    ran = [a for a in chosen if a.ran]
    if n > 1 and ran:
        return attempts, max(ran, key=lambda a: (a.reached, a.verdict.works))
    # Nothing worked cleanly: the cheapest machine that ran for a while before
    # crashing, else the one that got furthest.
    for a in chosen:
        if a.verdict.verdict == "works-then-crash":
            return attempts, a
    return attempts, max(chosen, key=lambda a: a.rank)


def fallbacks(v, prod):
    """Other ways to run variant ``v`` when it did not work, in order: each
    makes a variant, or None."""
    if v.kind == "hd":
        # Files a demo loads from DF0: rather than from its directory.
        return [] if v.command is None else \
            [lambda: media.floppy_variant(v, prod.id)]
    # A floppy set that never got going may be a Workbench disk: run its
    # demo directly instead. A set that still does not may be meant to be
    # installed: run it from one directory holding every disk.
    out = [] if media.LAUNCH_NOTE in v.note else \
        [lambda: media.launch_variant(v.disks, prod.id)]
    if len(v.disks) > 1:
        out.append(lambda: media.merged_variant(v.disks, prod.id, prod.title))
    return out


def _record(v, attempts, best):
    """Variant ``v`` and its runs as the store keeps them."""
    return result.Variant(
        v.kind, v.disks, v.note,
        {"root": v.root, "command": v.command, "complete": v.complete},
        [a.record() for a in attempts],
        next(i for i, a in enumerate(attempts) if a is best))


def _job(prod, multi_only=False):
    """Worker: build the production's variants and climb each one."""
    variants, problems = media.variants(prod.id, prod.title)
    if multi_only:
        variants = [v for v in variants if len(v.disks) > 1]
    aga_only = catalog.is_aga(prod)
    results = [climb(v, aga_only, prod.release_date) for v in variants]
    for v, (_, best) in list(zip(variants, results)):
        if best.verdict.works:
            continue
        for make in fallbacks(v, prod):
            fv = make()
            if fv:
                variants.append(fv)
                results.append(climb(fv, aga_only, prod.release_date))
                if results[-1][1].verdict.works:
                    break
    return problems, [_record(v, *r) for v, r in zip(variants, results)]


def run_all(prods, store, jobs=None, multi_only=False, log=print):
    driver.run_all(prods, store, functools.partial(_job, multi_only=multi_only),
                   jobs, log)
