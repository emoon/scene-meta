"""Filesystem locations. One place, overridable from the environment."""

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

NAS = pathlib.Path(os.environ.get("SCENEDB_NAS", "/mnt/nas/demoscene/demoscene"))
INDEX_DB = NAS / "meta" / "index.sqlite"
STATE_DB = NAS / "meta" / "state.sqlite"
DEMOZOO_DIR = NAS / "demozoo"

AMIBERRY = pathlib.Path(os.environ.get(
    "SCENEDB_AMIBERRY", ROOT / "amiberry" / "build" / "amiberry"))
ROM_DIR = pathlib.Path(os.environ.get("SCENEDB_ROMS", ROOT / "roms"))
# Libraries from a Workbench disk, put in LIBS: of hard-drive boots (optional).
LIBS_DIR = pathlib.Path(os.environ.get("SCENEDB_LIBS", ROOT / "libs"))

# Derived data (unpacked media, screenshots). Rebuildable from the NAS.
WORK = pathlib.Path(os.environ.get("SCENEDB_WORK", ROOT / "work"))
RESULTS_DB = pathlib.Path(os.environ.get("SCENEDB_DB", ROOT / "scene.db"))


def prod_dir(prod_id):
    """The NAS mirror directory of one Demozoo production."""
    return DEMOZOO_DIR / f"{prod_id // 1000:03d}" / str(prod_id)
