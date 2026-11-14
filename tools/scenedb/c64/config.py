"""Filesystem locations. One place, overridable from the environment."""

import os
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2] / "c64"

NAS = pathlib.Path(os.environ.get("SCENEDB_NAS", "/mnt/nas/demoscene/demoscene"))
INDEX_DB = NAS / "meta" / "index.sqlite"
CSDB_DIR = NAS / "mirrors" / "csdb"
SCENEORG_DIR = NAS / "mirrors" / "sceneorg"

VICE = os.environ.get("SCENEDB_VICE") or shutil.which("x64sc") or "x64sc"
ROM_DIR = pathlib.Path(os.environ.get("SCENEDB_ROMS", ROOT / "roms"))

# Derived data (unpacked media, screenshots). Rebuildable from the NAS.
WORK = pathlib.Path(os.environ.get("SCENEDB_WORK", ROOT / "work"))
RESULTS_DB = pathlib.Path(os.environ.get("SCENEDB_DB", ROOT / "scene.db"))
