"""The sweepers: which machine each production works on and when it asks for
its next disk, one subpackage per platform.

    python3 -m scenedb <platform> <command> ...
"""

import pathlib
import sys

# scenemeta (the data files' reader, writer and validator) is a package of
# its own in tools/common, so that checking the data needs nothing from here.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "common"))
