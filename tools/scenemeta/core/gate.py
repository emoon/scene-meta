"""The gate: is an entry of the data files correct? (docs/DESIGN.md, Replay)

A platform's player plays the entry as written and returns a ``Play``, the
same record on every platform; ``judge`` turns one into pass or fail with a
reason.
"""

import dataclasses


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
    keys: tuple = ()     # the keys shown to be needed
    end: float = None    # when it had shown everything; None: not known


@dataclasses.dataclass(frozen=True)
class Judgement:
    passed: bool
    reason: str

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
