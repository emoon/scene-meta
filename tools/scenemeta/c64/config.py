"""Filesystem locations. One place, overridable from the environment."""

import os
import shutil

from ..core.config import NAS, home

ROOT, ROM_DIR, WORK, RESULTS_DB, DATA_DIR = home("c64")

CSDB_DIR = NAS / "mirrors" / "csdb"
# What the CSDb mirror was filled from (csdbmirror.py).
ASSEMBLY64_CATALOGUE = NAS / "meta" / "assembly64" / "catalogue.jsonl"
SCENEORG_DIR = NAS / "mirrors" / "sceneorg"

VICE = os.environ.get("SCENEMETA_VICE") or shutil.which("x64sc") or "x64sc"
