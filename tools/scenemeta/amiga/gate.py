"""The gate over entries of the data files (``data/amiga``): each is played
once as written, through the player, and the core's gate says pass or fail
(see core.gate).
"""

import os

from ..core import gate
from ..core.errors import CannotPlay
from ..core.export import default_machine
from . import config, player, replay


def _one(prod, entry, default):
    """The report line of one production. Raises CannotPlay when something
    it needs is missing, or the emulator showed nothing of the run."""
    ran = player.play(prod, entry, default)
    if ran.verdict.verdict == "error":
        raise CannotPlay(f"the emulator gave nothing: {ran.verdict.crash}")
    return f"{prod} {entry['title']}: {gate.judge(ran.record)}"


def run(ids, data=None, jobs=None, log=print):
    """Gate the productions ``ids``. Returns how many could not be played."""
    data = data or config.DATA_DIR
    default = default_machine(data)
    found = replay.all_entries(data)
    for p in sorted(set(ids) - set(found)):
        log(f"{p}: no entry in the data files")
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    return player.play_each(sorted((p, found[p]) for p in set(ids) & set(found)),
                            lambda p, e: _one(p, e, default), jobs, log)
