"""The CSDb mirror: ``mirrors/csdb/<id>/``, a release's files as downloaded.

The mirror was filled from the Assembly64 catalogue, where every collection
numbers its own items: CSDb release 782 (Coma Light 11) shares its id with a
game of another collection, and the directory holds whichever the catalogue
lists first, here the game. Such a directory is not the release.
"""

import functools
import json

from . import config


def taken(catalogue):
    """The ids whose directory holds an item of another collection.
    ``catalogue``: the lines of catalogue.jsonl."""
    first = {}
    for line in catalogue:
        item = json.loads(line)
        # Only CSDb's items have a category on the site.
        first.setdefault(str(item["id"]), bool(item.get("siteCategory")))
    return frozenset(id_ for id_, release in first.items() if not release)


@functools.lru_cache(maxsize=None)
def _taken():
    with open(config.ASSEMBLY64_CATALOGUE) as f:
        return taken(f)


def directory(release_id):
    """Where the files of CSDb release ``release_id`` are, or None when the
    mirror does not hold them."""
    path = config.CSDB_DIR / str(release_id)
    if not path.exists() or str(release_id) in _taken():
        return None
    return path
