"""The gate: is an entry of the data files correct? (docs/DESIGN.md, Replay)

A platform's player plays the entry as written and returns a ``Play``, the
same record on every platform. ``check`` has an entry played on several
seeds of the emulator's random state: as written, with its disks put in
LATE seconds later, and once without each of its keys; it passes when every
seed does.
"""

import dataclasses

SEEDS = (1, 2, 3)    # the last one only for an entry with events
LATE = 30.0          # seconds: a consumer's emulator has not the sweeper's timing


@dataclasses.dataclass(frozen=True)
class SwapTaken:
    """One swap of the entry, as the run took it."""
    disk: int       # 1-based, as the entry numbers it
    loaded: bool    # the production read the disk after its insert


@dataclasses.dataclass(frozen=True)
class Play:
    """What one run of an entry showed."""
    ran: bool            # the production came alive
    crash: str = None    # what stopped it, in the platform's words
    swaps: tuple = ()    # a SwapTaken per swap of the entry, in run order
    # How far it got, in the platform's own measure: only to set against
    # another run of the same entry.
    far: float = 0.0
    end: float = None    # when it had shown everything; None: not known


@dataclasses.dataclass(frozen=True)
class Run:
    """One run the gate asks of an entry."""
    seed: int
    late: bool = False     # every disk goes in LATE seconds after its ``at``
    without: int = None    # this one of ``keys_of`` the entry is not pressed


@dataclasses.dataclass(frozen=True)
class Judgement:
    passed: bool
    reason: str
    until: tuple = ()    # per swap: the latest insert that passed, seconds
    seeds: tuple = ()    # of an entry: ``(seed, Judgement)`` of each seed

    def __str__(self):
        return f"{'pass' if self.passed else 'fail'} ({self.reason})"


def judge(play):
    """Pass when the production came alive, did not crash and loaded every
    disk swapped in."""
    if play.crash:
        return Judgement(False, f"crashed: {play.crash}")
    if not play.ran:
        return Judgement(False, "never came alive")
    unloaded = [str(s.disk) for s in play.swaps if not s.loaded]
    if unloaded:
        return Judgement(False, f"disk{'s' * (len(unloaded) > 1)}"
                                f" {', '.join(unloaded)} never loaded")
    return Judgement(True, "came alive, no crash" +
                     (", every disk loaded" if play.swaps else ""))


def swaps_of(entry):
    """The events of ``entry`` that put a disk in."""
    return [e for e in entry.get("events", ()) if "disk" in e]


def keys_of(entry):
    """The index in its ``events`` of each key of ``entry``."""
    return [i for i, e in enumerate(entry.get("events", ())) if "key" in e]


def runs(entry):
    """The runs that show whether ``entry`` is correct."""
    keys = range(len(keys_of(entry)))
    out = []
    for seed in SEEDS if entry.get("events") else SEEDS[:2]:
        out.append(Run(seed))
        if swaps_of(entry):
            out.append(Run(seed, late=True))
        out += [Run(seed, without=k) for k in keys]
    return out


def as_played(entry, run):
    """``entry`` as ``run`` plays it. Late, the first disk and everything
    from its time on happen LATE seconds later: a key pressed for a disk
    follows it."""
    events = [dict(e) for e in entry.get("events", ())]
    if run.late:
        first = min((e["at"] for e in swaps_of(entry)), default=float("inf"))
        for event in events:
            if event["at"] >= first:
                event["at"] += LATE
    if run.without is not None:
        del events[keys_of(entry)[run.without]]
    return dict(entry, events=events)


def _key(entry, k):
    event = entry["events"][keys_of(entry)[k]]
    return f"{event['key']} at {event['at']:g}"


def far(play):
    """How far a run got, to set against another run of the same entry: a
    key is needed when the run without it got less far."""
    return (play.ran, sum(s.loaded for s in play.swaps), not play.crash,
            play.far)


def _fault(entry, plays, seed):
    """Why ``entry`` fails on ``seed``, or None."""
    written = plays[Run(seed)]
    said = judge(written)
    if not said.passed:
        return said.reason
    if swaps_of(entry):
        said = judge(plays[Run(seed, late=True)])
        if not said.passed:
            return f"with the disks put in {LATE:g} s later, {said.reason}"
    for k in range(len(keys_of(entry))):
        if far(plays[Run(seed, without=k)]) >= far(written):
            return f"key not needed: {_key(entry, k)}"
    return None


def _until(entry, plays, seeds):
    """Per swap of ``entry``: the latest insert whose disk loaded on every
    seed, None when it did on none."""
    def loaded(i, late):
        return all(i < len(p.swaps) and p.swaps[i].loaded
                   for p in (plays[Run(seed, late)] for seed in seeds))
    return tuple(swap["at"] + LATE if loaded(i, True)
                 else swap["at"] if loaded(i, False) else None
                 for i, swap in enumerate(swaps_of(entry)))


def _on_seed(entry, plays, seed):
    """The Judgement of ``entry`` on ``seed`` alone."""
    fault = _fault(entry, plays, seed)
    if fault:
        return Judgement(False, fault)
    return Judgement(True, judge(plays[Run(seed)]).reason +
                     (", every key needed" if keys_of(entry) else ""))


def verdict(entry, plays):
    """Pass when ``entry`` holds on every seed, else a fail that names the
    first seed it does not hold on. ``plays`` is the Play of each of
    ``runs(entry)``."""
    seeds = tuple((seed, _on_seed(entry, plays, seed))
                  for seed in sorted({r.seed for r in plays}))
    until = _until(entry, plays, [seed for seed, _ in seeds])
    proved = "".join(f"; disk {swap['disk']} until {u:.1f}"
                     for swap, u in zip(swaps_of(entry), until)
                     if u is not None)
    for seed, said in seeds:
        if not said.passed:
            return Judgement(False, f"seed {seed}: {said.reason}{proved}",
                             until, seeds)
    return Judgement(True, f"{len(seeds)} seeds: {seeds[0][1].reason}{proved}",
                     until, seeds)


def check(entry, play, each=map):
    """The gate's judgement of ``entry``. ``play(run)`` is the Play of
    ``entry`` as ``run`` plays it (see ``as_played``); ``each`` maps it
    over the runs, a pool's ``map`` to make them in parallel."""
    todo = runs(entry)
    return verdict(entry, dict(zip(todo, each(play, todo))))
