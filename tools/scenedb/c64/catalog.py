"""The C64 productions in scope: demos, intros and music disks.

A CSDb release link is not flagged as a download link in demozoo, but the
mirror holds that release's files, so it counts as one.
"""

from ..core import catalog

PLATFORMS = {"Commodore 64": "c64"}
TYPES = ("Demo", "Intro", "Musicdisk")


def productions(ids=None):
    """All C64 demos, intros and music disks, ordered by id."""
    return catalog.productions(PLATFORMS, TYPES, ids, link_classes=("CsdbRelease",))
