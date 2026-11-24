"""What a platform reports of its runs: the records the store keeps and the
export reads.

All times are seconds of emulated time since power-on, as in the data
files. How a platform counts time inside a run (frames, CPU cycles) is its
own business; it converts when it fills these in.
"""

import dataclasses


@dataclasses.dataclass
class Swap:
    """One disk change a run made."""
    disk: int                    # 1-based number of the disk that went in
    at: float                    # when it went in
    trigger: str = ""            # what made the sweep put it in
    accepted: bool = True        # the production went on to use the disk
    waiting_since: float = None  # when the production started to wait for it
    key: str = None              # pressed after the insert to have it taken
    key_at: float = None
    screenshot: bytes = b""      # the screen when the swap was decided
    drive: int = 1               # 1-based number of the drive it went into
    until: float = None          # the latest time it was seen to go in


@dataclasses.dataclass
class Key:
    """A key press the production needs that no disk change goes with."""
    at: float
    key: str


@dataclasses.dataclass
class Run:
    """One boot of one variant on one machine."""
    machine: str
    budget: float                # how long the run was allowed to go on
    verdict: str                 # works | works-then-crash | crash | ...
    alive: float                 # time the production was seen playing
    crash: str = None
    crash_at: float = None
    ended_at: float = None       # last sign of life when the run ends quiet
    wants_disk: bool = False     # asked for a disk beyond the set
    drives: int = 1              # drives that held a disk from the start
    reached: int = 1             # disks of the set the production got to
    swaps: list = dataclasses.field(default_factory=list)
    detail: dict = dataclasses.field(default_factory=dict)  # the platform's own
    screenshot: bytes = b""      # the last screen
    keys: list = dataclasses.field(default_factory=list)   # result.Key


@dataclasses.dataclass
class Variant:
    """One bootable thing found for a production, and its runs."""
    kind: str
    disks: list                  # image paths, in disk order
    note: str = ""
    detail: dict = dataclasses.field(default_factory=dict)  # the platform's own
    runs: list = dataclasses.field(default_factory=list)
    best: int = 0                # index of the chosen run

    @property
    def chosen(self):
        return self.runs[self.best]
