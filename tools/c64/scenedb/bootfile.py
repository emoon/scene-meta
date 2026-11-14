"""Pick the file of a compilation disk set that holds one production.

Party and compo disks carry dozens of unrelated productions; autostart boots
whatever comes first. The directory entry whose name matches the title is the
one to boot instead.
"""

import re
import subprocess

MIN_NAME = 3        # shorter names match too many titles by accident


def listing(image):
    """File names in the directory of a disk image, in directory order."""
    out = subprocess.run(["c1541", "-attach", str(image), "-list"],
                         capture_output=True, text=True).stdout.splitlines()
    return [m.group(1) for line in out[1:]
            if "blocks free" not in line and (m := re.search(r'"([^"]*)"', line))]


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _rank(title, name):
    """0 equal, 1 one starts the other, 2 one contains the other, else None."""
    t, n = _norm(title), _norm(name.split("/")[0])   # "title /group" entries
    if len(n) < MIN_NAME:
        return None
    if t == n:
        return 0
    if t.startswith(n) or n.startswith(t):
        return 1
    if n in t or t in n:
        return 2
    return None


def pick(title, listings):
    """``(disk index, file name)`` of the best match among ``listings`` (one
    list of names per disk), or None. Ties go to the earliest disk and file."""
    best = None
    for disk, names in enumerate(listings):
        for name in names:
            r = _rank(title, name)
            if r is not None and (best is None or r < best[0]):
                best = (r, disk, name)
    return best[1:] if best else None
