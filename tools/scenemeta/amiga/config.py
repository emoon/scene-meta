"""Filesystem locations. One place, overridable from the environment."""

import os
import pathlib

from ..core.config import BUILD, NAS, home

ROOT, ROM_DIR, WORK, RESULTS_DB, DATA_DIR = home("amiga")

GATE_SUMMARY = ROOT / "gate-summary.txt"    # checked in
EXPECTED = ROOT / "expected.toml"
EXPECTED_SCORE = ROOT / "expected-score.txt"    # checked in
STATE_DB = NAS / "meta" / "state.sqlite"
DEMOZOO_DIR = NAS / "demozoo"

AMIBERRY = BUILD / "amiberry" / "amiberry"
# Libraries from a Workbench disk, put in LIBS: of hard-drive boots (optional).
LIBS_DIR = pathlib.Path(os.environ.get("SCENEMETA_LIBS", ROOT / "libs"))
# Standard A1200 Workbench boot partition for 68060 HD boots (optional).
A1200_BOOT = pathlib.Path(os.environ.get("SCENEMETA_A1200_BOOT", ROOT / "a1200.boot"))


def prod_dir(prod_id):
    """The NAS mirror directory of one Demozoo production."""
    return DEMOZOO_DIR / f"{prod_id // 1000:03d}" / str(prod_id)
