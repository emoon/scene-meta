"""Filesystem locations. One place, overridable from the environment."""

import os
import pathlib

from ..core.config import NAS, home

ROOT, ROM_DIR, WORK, RESULTS_DB, DATA_DIR = home("amiga")

STATE_DB = NAS / "meta" / "state.sqlite"
DEMOZOO_DIR = NAS / "demozoo"

AMIBERRY = pathlib.Path(os.environ.get(
    "SCENEDB_AMIBERRY", ROOT / "amiberry" / "build" / "amiberry"))
# Libraries from a Workbench disk, put in LIBS: of hard-drive boots (optional).
LIBS_DIR = pathlib.Path(os.environ.get("SCENEDB_LIBS", ROOT / "libs"))


def prod_dir(prod_id):
    """The NAS mirror directory of one Demozoo production."""
    return DEMOZOO_DIR / f"{prod_id // 1000:03d}" / str(prod_id)
