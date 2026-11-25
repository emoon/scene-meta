"""The Amiga productions in scope: OCS/ECS and AGA demos and intros."""

import tomllib

from .. import machines as presets
from ..core import catalog
from ..core.export import default_machine

PLATFORMS = {"Amiga OCS/ECS": "ocs", "Amiga AGA": "aga"}
# Executable demo/intro types only; music, packs, cracktros, diskmags etc. are out.
TYPES = ("Demo", "Intro", "32b Intro", "64b Intro", "128b Intro", "256b Intro",
         "512b Intro", "1K Intro", "2K Intro", "4K Intro", "8K Intro",
         "16K Intro", "32K Intro", "40k Intro", "64K Intro", "96K Intro",
         "100K Intro", "Executable Music", "32K Executable Music",
         "64K Executable Music", "Executable Graphics",
         "4K Executable Graphics")


def productions(ids=None):
    """All Amiga OCS/ECS + AGA demos and intros, ordered by id."""
    return catalog.productions(PLATFORMS, TYPES, ids)


def is_aga(prod):
    """Is ``prod`` tagged for AGA machines only?"""
    return "aga" in prod.platforms and "ocs" not in prod.platforms


def known_machines(data):
    """``{id: machine name}`` of the productions the data files say run,
    and so file under a machine: a sweep starts there, not at the bottom.
    Not one whose entry says it does not run: starting at the default would
    cut the AGA rungs off an AGA-only production's ladder."""
    default = default_machine(data)
    out = {}
    for path in sorted(data.glob("*.toml")):
        if path.name != presets.FILE:
            for key, e in tomllib.loads(path.read_text("utf-8")) \
                    .get("demozoo", {}).items():
                if e.get("result") in (None, "crashes-later"):
                    out[int(key)] = e.get("machine", default)
    return out
