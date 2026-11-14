"""Filesystem locations every platform shares. One place, overridable from
the environment."""

import collections
import os
import pathlib

TOOLS = pathlib.Path(__file__).resolve().parents[2]
# Everything that is built (a platform's emulator), git-ignored.
BUILD = TOOLS.parent / "build"

NAS = pathlib.Path(os.environ.get("SCENEMETA_NAS", "/mnt/nas/demoscene/demoscene"))
INDEX_DB = NAS / "meta" / "index.sqlite"

# root: what a platform keeps outside the code (its emulator, its notes).
# roms: git-ignored. work: derived data (unpacked media, screenshots),
# rebuildable from the NAS. db: the sweep's own log. data: the shared data
# files `scenemeta <platform> export` merges the results into.
Home = collections.namedtuple("Home", "root roms work db data")


def home(platform):
    """Where ``platform`` keeps its files."""
    root = TOOLS / platform

    def path(env, default):
        return pathlib.Path(os.environ.get(env, default))

    return Home(root, path("SCENEMETA_ROMS", root / "roms"),
                path("SCENEMETA_WORK", root / "work"),
                path("SCENEMETA_DB", root / "scene.db"),
                path("SCENEMETA_DATA", TOOLS.parent / "data" / platform))
