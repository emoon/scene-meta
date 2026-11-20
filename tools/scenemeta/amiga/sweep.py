"""Run every production's variants up the machine ladder."""

import concurrent.futures as cf
import dataclasses
import functools

from ..core import result, sweep as driver
from . import catalog, config, emulator, machines, media, verdict
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
    clicks: tuple = ()    # frames of the clicks a run with no swap made

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
            {"returncode": log.returncode, "events": log.events}, log.last_shot,
            [result.Key(seconds(f), "lmb") for f in self.clicks])


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


def attempt(m, variant, frames, **kw):
    """One run and what it showed. ``kw`` are emulator.Options fields."""
    opts = emulator.Options(**kw)
    log = emulator.run(m, variant, frames, opts)
    log.events.append({"event": "seed", "seed": opts.seed})
    v = verdict.classify(log, frames // 250)
    sw = verdict.swaps(log)
    reached = verdict.disks_reached(log, verdict.played_swaps(log, sw, v),
                                    opts.drives, len(variant.disks))
    return Attempt(m.name, frames, v, log, sw, opts.drives, reached,
                   opts.unit, opts.click_every, opts.key_every, opts.seed)


class _Tries:
    """The attempts made on one machine, and the way to make more."""

    def __init__(self, m, variant, frames):
        self._run = (m, variant, frames)
        self.n = len(variant.disks)
        self.tries = [attempt(m, variant, frames)]
        self.asked = [{}]    # the arguments of each attempt, to run one again

    def short(self):
        """Is the set's last disk still out of reach?"""
        # Swaps in runs that never got going are the OS mounting disks.
        return self.n > 1 and max((a.reached for a in self.tries if a.ran),
                                  default=0) < self.n

    def stalled(self):
        return waits_for_click(self.tries)

    def once(self, frames, **kw):
        """One more attempt, for ``frames``: not one of the waves."""
        got = attempt(self._run[0], self._run[1], frames, **kw)
        self.tries.append(got)
        self.asked.append(kw)
        return got

    def wave(self, *kws):
        """Run one attempt per set of arguments, all at once."""
        # Every attempt rolls its own seed, as the wall clock did before
        # runs were pinned: a demo that races may get going on another.
        # Retries that continue a base run say its seed.
        kws = [{"seed": emulator.DEFAULT_SEED + len(self.tries) + i, **kw}
               for i, kw in enumerate(kws)]
        with cf.ThreadPoolExecutor(len(kws) or 1) as pool:
            got = list(pool.map(lambda kw: attempt(*self._run, **kw), kws))
        self.tries.extend(got)
        self.asked.extend(kws)
        return got


def try_machine(m, variant, frames):
    """One machine, plus the retries a demo may need to get going or to
    reach the last disk of its set. Retries that do not depend on each
    other run at once, in waves. Every attempt is returned; the last one
    is the best."""
    t = _Tries(m, variant, frames)
    _try_external_drives(t, _try_triggers_and_nudges(t))
    _try_clicks_only(t)
    _try_scheduled_swaps(t)
    best = _best(t)
    return [a for a in t.tries if a is not best] + [best]


def _try_triggers_and_nudges(t):
    """The first retries: riskier swap triggers for a set that stopped
    short, clicks and keys for a demo that waits. Returns each retry as
    ``(arguments, attempt)``."""
    first = []
    if t.short():
        # Waits the default detector cannot see: re-reading one track
        # until the disk changes, then a prompt with the head parked
        # mid-disk (the idle trigger can also fire in a quiet stretch).
        first += [dict(triggers="reread"),
                  dict(triggers="reread anycyl static")]
        # Early swaps on the OS's own drive polling (a DOS-loaded demo
        # playing from RAM) broke the demo: Dark Ages, the AMOS megademos.
        if verdict.swaps(t.tries[0].log):
            first += [dict(triggers="rampolls"),
                      dict(triggers="rampolls", click_every=CLICK_EVERY)]
    if t.short() or t.stalled():
        # "Click mouse button to continue" (AMOS PD intros, "HIT MOUSE!").
        first.append(dict(triggers="reread", click_every=CLICK_EVERY))
        # Return, Space and fire in turn (Megademo 2's credits page).
        first.append(dict(triggers="reread", key_every=CLICK_EVERY))
    got = t.wave(*first)
    if not any(a.verdict.works for a in t.tries):
        t.wave(*[dict(kw, max_clicks=limit, seed=a.seed)
                 for kw, a in zip(first, got) if (limit := clicks_to_start(a))])
    return list(zip(first, got))


def _nudge_that_helped(t, got, field):
    """CLICK_EVERY when the attempts among ``got`` that pressed ``field``
    (click_every or key_every) got further than every attempt without."""
    pressed = [a for a in got if getattr(a, field)]
    if not pressed:
        return 0
    without = max(a.rank for a in t.tries if not getattr(a, field))
    return CLICK_EVERY if max(a.rank for a in pressed) > without else 0


def _try_external_drives(t, first):
    """A set that is still short gets its disks in the external drives.
    ``first`` is what _try_triggers_and_nudges returned."""
    got = [a for _, a in first]
    # When clicking is what got the demo going, the later attempts click
    # too (The Wall: its intro waits for a button, then it wants the
    # external drive).
    clicks = _nudge_that_helped(t, got, "click_every")
    # Likewise for the keys (Megademo 2: Return, then it wants disk 2).
    keys = _nudge_that_helped(t, got, "key_every")
    triggers = "reread rampolls" if any(
        "rampolls" in kw.get("triggers", "") and a.rank > t.tries[0].rank
        for kw, a in first) else "reread"
    second = []
    if t.short():
        # "Insert disk 2 in any external drive": the set in DF0-DF3.
        second.append(dict(triggers=triggers, click_every=clicks,
                           key_every=keys,
                           drives=min(t.n, emulator.MAX_DRIVES)))
        # Every later disk in the external drive, one after another (Soho
        # reads disk 2 from DF1, then waits for disk 3 there too).
        if t.n > 2:
            second.append(dict(triggers=triggers, click_every=clicks,
                               key_every=keys, drives=2, unit=1))
    t.wave(*second)


def _try_scheduled_swaps(t):
    """The last resort for a set that is still short: prompts no detector
    sees (a still or animated picture, motor left on, no polling). Swap
    where the demo stops reading the disk that is in, one disk per round,
    keeping the swaps that worked."""
    # Nothing ran without the detector getting in the way: run with it off
    # to see where the demo really stops reading, for the swaps below.
    if t.short() and not any(a.ran for a in t.tries if a.drives < t.n):
        t.wave(dict(detect=False), dict(detect=False, click_every=CLICK_EVERY))
    while t.short():
        base = max((a for a in t.tries if a.drives < t.n),
                   key=lambda a: a.rank)
        got = t.wave(*[dict(schedule=[f for f, _, _ in base.swaps] + [at],
                            drives=base.drives, unit=base.unit,
                            click_every=base.click_every,
                            key_every=base.key_every, seed=base.seed)
                       for at in swap_frames(base)])
        # Only a running attempt can be the next base: anything else
        # would be retried for ever.
        if not any(a.ran and a.reached > base.reached for a in got):
            break


def _best(t):
    """The best attempt, run once more without its swap click when it had
    one, to see whether the click was needed."""
    best, kw = max(zip(t.tries, t.asked), key=lambda x: x[0].rank)
    at = clicked_swap(best)
    if at is None:
        return best
    # The detector clicks whenever a new disk is not loaded from within
    # 5 s, and a slow start then looks like the click's doing (Desert
    # Dream). Only the same run without the click shows it was needed:
    # with nothing pressed at all once that disk is in, a retry's own
    # clicks included (Megademo III).
    plain = t.wave(dict(kw, seed=best.seed, swap_click=False,
                        nudge_until=at))[0]
    return plain if as_far(plain, best) else best


SWAP_CLICK_FRAMES = 250   # the detector clicks this long after an insert


def _try_clicks_only(t):
    """A set no run has got through, with a run that put a disk in, clicked
    and crashed: that run again with the clicks and no disk. The detector also
    takes a wait for a click for a wait for a disk (Megademo: "press the
    button" at 81 s, and the part it then loads is on disk 1; with disk 2 in,
    it jumps into a scrambled load). When that run plays without a crash,
    the swap was false and the production only wants the clicks."""
    # A run with nudge clicks too is fine: the replay has only the swap
    # clicks, so a production that needed the nudges stalls and stays.
    crashed = [a for a in t.tries
               if a.verdict.crash is not None and a.drives == 1
               and any("click" in how for _, _, how in a.swaps)]
    # Not short(): the crashed run itself read the disk it was given, so it
    # counts as having reached the last one. Only a run that got there and
    # lived makes the swap proven.
    proven = any(a.ran and a.reached >= t.n and a.verdict.crash is None
                 for a in t.tries)
    if t.n < 2 or proven or not crashed:
        return
    base = max(crashed, key=lambda a: a.rank)
    clicks = tuple(f + SWAP_CLICK_FRAMES for f, _, how in base.swaps
                   if "click" in how)
    got = t.once(clicks[-1] + emulator.AUTOSWAP_TAIL_FRAMES, seed=base.seed,
                 play=tuple((f, "click", 0) for f in clicks))
    if got.verdict.works and got.verdict.crash is None:
        # The set is not short of a disk the production does not ask for.
        t.tries[-1] = dataclasses.replace(got, reached=t.n, clicks=clicks)


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


def rungs(variant, aga_only, release_date=None, start=None):
    """The machines to try ``variant`` on. A disk that boots from the Fast
    File System cannot be mounted by Kickstart 1.x: only the KS3 rungs."""
    ladder = machines.ladder_for(aga_only, release_date=release_date, start=start)
    return [m for m in ladder if m.aga] if variant.ffs else ladder


def climb(variant, aga_only, release_date=None, start=None):
    """Run ``variant`` up the ladder until a machine works (and, for a disk
    set, reaches every disk).

    Returns ``(attempts, best)``: every Attempt made, and the chosen one.
    """
    frames = budget(variant)
    attempts, chosen = [], []
    n = len(variant.disks)
    for m in rungs(variant, aga_only, release_date, start):
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


def _record(v, attempts, best):
    """Variant ``v`` and its runs as the store keeps them."""
    return result.Variant(
        v.kind, v.disks, v.note,
        {"root": v.root, "command": v.command, "complete": v.complete,
         "run": v.run, "choice": v.choice},
        [a.record() for a in attempts],
        next(i for i, a in enumerate(attempts) if a is best))


def _job(prod, multi_only=False, known=None):
    """Worker: build the production's variants and climb each one."""
    variants, problems = media.variants(prod.id, prod.title)
    if multi_only:
        variants = [v for v in variants if len(v.disks) > 1]
    aga_only = catalog.is_aga(prod)
    start = (known or {}).get(prod.id)
    results = [climb(v, aga_only, prod.release_date, start) for v in variants]
    for v, (_, best) in list(zip(variants, results)):
        if best.verdict.works:
            continue
        for _, make in media.fallbacks(v, prod.id, prod.title):
            fv = make()
            if fv:
                variants.append(fv)
                results.append(climb(fv, aga_only, prod.release_date, start))
                if results[-1][1].verdict.works:
                    break
    return problems, [_record(v, *r) for v, r in zip(variants, results)]


def run_all(prods, store, jobs=None, multi_only=False, log=print):
    # Before any production: a run without its ROM would be stored as one
    # where nothing happened, a production without the mirror as one with
    # no files.
    machines.require_roms()
    media.require_mirror()
    known = catalog.known_machines(config.DATA_DIR)
    driver.run_all(prods, store, functools.partial(
        _job, multi_only=multi_only, known=known), jobs, log)
