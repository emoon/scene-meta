"""The gate: is an entry of the data files correct? (docs/DESIGN.md, Replay)

A platform's player plays the entry as written and returns a ``Play``, the
same record on every platform. ``check`` has an entry played on several
seeds of the emulator's random state: as written, with its disks put in
LATE seconds later, and once without each of its keys; it passes when every
seed does.
"""

import dataclasses

SEEDS = (1, 2, 3)    # the last one only for an entry with swaps or keys
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


def keys_of(entry):
    """``(where, i)`` of each key of ``entry``: those of its swaps, then
    its ``keys``."""
    return [("swaps", i) for i, s in enumerate(entry.get("swaps", ()))
            if "key" in s] + [("keys", i) for i in range(len(entry.get("keys", ())))]


def runs(entry):
    """The runs that show whether ``entry`` is correct."""
    keys = range(len(keys_of(entry)))
    out = []
    for seed in SEEDS if entry.get("swaps") or keys else SEEDS[:2]:
        out.append(Run(seed))
        if entry.get("swaps"):
            out.append(Run(seed, late=True))
        out += [Run(seed, without=k) for k in keys]
    return out


def as_played(entry, run):
    """``entry`` as ``run`` plays it. A swap's key follows its disk."""
    swaps = [dict(s) for s in entry.get("swaps", ())]
    keys = list(entry.get("keys", ()))
    if run.late:
        for swap in swaps:
            swap["at"] += LATE
    if run.without is not None:
        where, i = keys_of(entry)[run.without]
        if where == "keys":
            del keys[i]
        else:
            del swaps[i]["key"]
            swaps[i].pop("key_delay", None)
    return dict(entry, swaps=swaps, keys=keys)


def _key(entry, k):
    where, i = keys_of(entry)[k]
    item = entry[where][i]
    return f"{item['key']} " + (f"at {item['at']:g}" if where == "keys"
                                else f"of disk {item['disk']}")


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
    if entry.get("swaps"):
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
                 for i, swap in enumerate(entry.get("swaps", ())))


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
                     for swap, u in zip(entry.get("swaps", ()), until)
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
