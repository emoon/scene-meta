"""Run every production's variants up the machine ladder."""

import concurrent.futures as cf
import dataclasses
import functools
import itertools

from .. import events
from ..core import gate, result, sweep as driver
from . import (catalog, config, emulator, machines, media, player, verdict,
               workbench)
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


@dataclasses.dataclass(frozen=True)
class Press:
    """A key a run pressed."""
    frame: int
    key: str
    swap: int = None    # index of the swap whose disk it follows; None: on its own


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
    presses: tuple = ()   # the Press an entry of it needs
    untils: tuple = ()    # per swap: the latest frame it was seen to go in
    play: gate.Play = None  # of a run through the player

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
        keyed = {p.swap: p for p in self.presses}
        return result.Run(
            self.machine, seconds(self.frames), v.verdict,
            seconds(v.alive * SAMPLE_FRAMES), v.crash, seconds(v.crash_frame),
            seconds(v.ended_frame), v.wants_disk, self.drives, self.reached,
            [result.Swap(disk, seconds(frame), how,
                         key=keyed[i].key if i in keyed else None,
                         key_at=seconds(keyed[i].frame) if i in keyed else None,
                         drive=self.unit + 1,
                         until=seconds(dict(enumerate(self.untils)).get(i)))
             for i, (frame, disk, how) in enumerate(self.swaps)],
            {"returncode": log.returncode, "events": log.events}, log.last_shot,
            [result.Key(seconds(p.frame), p.key) for p in self.presses
             if p.swap is None])


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
    if variant.assign and "assign" not in kw:
        kw["assign"] = tuple(variant.assign.items())
    opts = emulator.Options(**kw)
    log = emulator.run(m, variant, frames, opts)
    return _seen(m, variant, frames, opts, log,
                 verdict.classify(log, frames // 250))


def played(m, variant, entry, seed, patient=False):
    """One run of ``entry`` as written, through the player, and what it
    showed."""
    ran = player.Ready(entry, m, variant).play(seed=seed, patient=patient)
    opts = emulator.Options(drives=entry.get("drives", 1), seed=seed)
    return dataclasses.replace(
        _seen(m, variant, player.frames_of(entry, patient), opts, ran.log,
              ran.verdict),
        play=ran.record)


# A disk is tried as much later as a patient player waits at most.
WINDOW_FRAMES = round(player.PATIENCE * FPS)


def windows(m, variant, a):
    """The latest frame each disk of attempt ``a`` is seen to go in, from
    one patient run of its entry with every disk WINDOW_FRAMES late: of the
    swaps up to the first whose disk did not load, of none when that run
    crashed or never came alive."""
    if not a.swaps or not a.ran:
        return ()
    entry = _entry(variant, a, a.presses)
    for event in entry["events"]:
        if "disk" in event:
            event["until"] = event["at"] + WINDOW_FRAMES / FPS
    play = played(m, variant, entry, a.seed, patient=True).play
    if play.crash or not play.ran:
        return ()
    loaded = itertools.takewhile(lambda s: s.loaded, play.swaps)
    return tuple(swap[0] + WINDOW_FRAMES for swap, _ in zip(a.swaps, loaded))


def _entry(variant, a, presses):
    """The entry of attempt ``a`` with ``presses``, as far as the player
    reads one."""
    does = [{"at": p.frame / FPS, "key": p.key} for p in presses]
    for frame, disk, _ in a.swaps:
        does.append({"at": frame / FPS, "disk": disk})
        if a.unit:
            does[-1]["drive"] = a.unit + 1
    e = {"drives": a.drives, "disks": variant.disks,
         "events": events.ordered(does)}
    if variant.assign:
        e["assign"] = dict(variant.assign)
    return e


def _seen(m, variant, frames, opts, log, v):
    """The Attempt of a finished run."""
    log.events.append({"event": "seed", "seed": opts.seed})
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

    def played(self, a, presses):
        """One more attempt, not one of the waves: the entry of attempt
        ``a`` with ``presses``, played as written."""
        m, variant, _ = self._run
        got = dataclasses.replace(
            played(m, variant, _entry(variant, a, presses), a.seed),
            unit=a.unit)
        self.tries.append(got)
        self.asked.append(dict(seed=a.seed))
        return got

    def replace(self, a, **changes):
        """Attempt ``a`` with ``changes``, in its place."""
        i = next(i for i, x in enumerate(self.tries) if x is a)
        self.tries[i] = dataclasses.replace(a, **changes)
        return self.tries[i]

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


SWAP_CLICK_FRAMES = 250   # the detector clicks this long after an insert


def detector_clicks(a):
    """The Press of each click the detector made in attempt ``a`` for a
    disk it put in to be taken."""
    out = []
    for i, (frame, _, how) in enumerate(a.swaps):
        if "+click" in how:
            out.append(Press(frame + SWAP_CLICK_FRAMES, "lmb", i))
        if "+rclick" in how:
            out.append(Press(frame + 2 * SWAP_CLICK_FRAMES, "rmb", i))
    return out


def presses_made(a, kw):
    """The Press of every key pressed in attempt ``a``, asked for with the
    emulator.Options fields ``kw``, in time order."""
    index = {disk: i for i, (_, disk, _) in enumerate(a.swaps)}
    own = [Press(frame, key, None if k is None else index.get(a.drives + 1 + k))
           for frame, key, k in emulator.pressed(a.frames,
                                                 emulator.Options(**kw))]
    return sorted(own + detector_clicks(a), key=lambda p: p.frame)


# The most runs made to find the presses one attempt needs.
NEEDED_RUNS = 12


def _best(t):
    """The best attempt, with the presses it needs. A run presses keys
    nobody asked for (the detector clicks a disk that is only slow to load:
    Desert Dream), so the player plays the entry of it with no key, then
    with one more press at a time, kept when the run without it got less
    far. That run is the best one when it passes the gate's judgement."""
    i = max(range(len(t.tries)), key=lambda i: t.tries[i].rank)
    best = t.tries[i]
    left = presses_made(best, t.asked[i])
    if not left or not best.ran:
        return best
    kept, got = [], t.played(best, [])
    for _ in range(NEEDED_RUNS):
        press = _next_press(best, got, kept, left)
        if press is None:
            break
        left.remove(press)
        more = t.played(best, kept + [press])
        if gate.far(more.play) > gate.far(got.play):
            kept, got = kept + [press], more
    if gate.judge(got.play).passed and got.ran >= best.ran:
        return t.replace(got, swaps=best.swaps, reached=best.reached,
                         presses=tuple(kept))
    return t.replace(best, presses=tuple(kept))


def _next_press(best, got, kept, left):
    """The press of ``left`` to try next, for the player's run ``got`` of
    ``best`` with the presses ``kept`` to get further; None when it is not
    short of anything a press is known to give. For a disk that did not
    load: its own key first, then the nearest press since the disk before
    it. For a run that never came alive: the last press before ``best``
    did."""
    short = next((i for i, s in enumerate(got.play.swaps) if not s.loaded),
                 None)
    if short is not None:
        frames = [f for f, _, _ in best.swaps]
        at = frames[short]
        since, until = ([0] + frames)[short], (frames + [float("inf")])[short + 1]
        keyed = any(p.swap == short for p in kept)
        near = [p for p in left if since < p.frame < until
                and (p.swap is None or p.swap == short and not keyed)]
        return min(near, key=lambda p: (p.swap is None, abs(p.frame - at)),
                   default=None)
    if got.play.ran:
        return None
    flags = verdict.alive_flags(best.log.samples)
    alive = next((s.frame for f, s in zip(flags, best.log.samples) if f), 0)
    return max((p for p in left if p.swap is None and p.frame < alive),
               key=lambda p: p.frame, default=None)


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
    clicks = tuple(Press(p.frame, p.key) for p in detector_clicks(base))
    # As the entry an export would write of it, the disk in from the start.
    got = t.played(dataclasses.replace(base, swaps=[]), clicks)
    if got.verdict.works and got.verdict.crash is None:
        # The set is not short of a disk the production does not ask for.
        t.replace(got, reached=t.n, presses=clicks)


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


def rungs(variant, aga_only, release_date=None, start=None, only=None):
    """The machines to try ``variant`` on: the one named ``only``, else the
    ladder. A disk that boots from the Fast File System cannot be mounted
    by Kickstart 1.x: only the KS3 rungs."""
    if only:
        return [machines.BY_NAME[only]]
    ladder = machines.ladder_for(aga_only, release_date=release_date, start=start)
    return [m for m in ladder if m.aga] if variant.ffs else ladder


def climb(variant, aga_only, release_date=None, start=None, only=None):
    """Run ``variant`` up the ladder until a machine works (and, for a disk
    set, reaches every disk).

    Returns ``(attempts, best)``: every Attempt made, and the chosen one,
    which says until when each of its disks can go in (see ``windows``).
    """
    attempts, best = _climb(variant, aga_only, release_date, start, only)
    known = dataclasses.replace(best, untils=windows(
        machines.BY_NAME[best.machine], variant, best))
    return [known if a is best else a for a in attempts], known


def _climb(variant, aga_only, release_date, start, only=None):
    frames = budget(variant)
    attempts, chosen = [], []
    n = len(variant.disks)
    for m in rungs(variant, aga_only, release_date, start, only):
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
    detail = {"root": v.root, "command": v.command, "complete": v.complete,
              "run": v.run, "choice": v.choice}
    if v.assign:
        detail["assign"] = dict(v.assign)
    return result.Variant(
        v.kind, v.disks, v.note, detail,
        [a.record() for a in attempts],
        next(i for i, a in enumerate(attempts) if a is best))


def _climbed(prod, variants, start=None, only=None):
    """``(variants, results)``: each of ``variants`` climbed, and after one
    that does not work its fallbacks, as far as one that does."""
    aga_only = catalog.is_aga(prod)
    variants = list(variants)
    results = [climb(v, aga_only, prod.release_date, start, only)
               for v in variants]
    for v, (_, best) in list(zip(variants, results)):
        if best.verdict.works:
            continue
        for _, make in media.fallbacks(v, prod.id, prod.title):
            fv = make()
            if fv:
                variants.append(fv)
                results.append(climb(fv, aga_only, prod.release_date, start,
                                     only))
                if results[-1][1].verdict.works:
                    break
    return variants, results


def _job(prod, multi_only=False, known=None, only=None):
    """Worker: build the production's variants and climb each one. With
    ``only``, a machine's name, the production is left out unless a variant
    works on that machine; one that does is climbed like any other, so it
    is filed under the first machine it works on (and is run on the named
    machine a second time)."""
    variants, problems = media.variants(prod.id, prod.title)
    if multi_only:
        variants = [v for v in variants if len(v.disks) > 1]
    if only and not any(best.verdict.works for _, best in
                        _climbed(prod, variants, only=only)[1]):
        return None
    variants, results = _climbed(prod, variants, (known or {}).get(prod.id))
    return problems, [_record(v, *r) for v, r in zip(variants, results)]


def run_all(prods, store, jobs=None, multi_only=False, log=print,
            machine=None, again=False):
    """Sweep ``prods`` the store does not hold yet up the ladder, each from
    the machine the data files file it under; or, with ``again``, every one
    of them, and with ``machine`` those that work on that machine, held or
    not, in place of what was held. A production swept again climbs the
    whole ladder: the machine it is filed under may be what is wrong."""
    # Before any production: a run without its ROM or the libraries would
    # be stored as one where nothing happened, a production without the mirror as one with
    # no files.
    machines.require_roms()
    if machine:
        machines.require_rom(machines.BY_NAME[machine])
    workbench.require_libs()
    media.require_mirror()
    again = again or bool(machine)
    known = {} if again else catalog.known_machines(config.DATA_DIR)
    driver.run_all(prods, store, functools.partial(
        _job, multi_only=multi_only, known=known, only=machine), jobs, log,
        again=again)
