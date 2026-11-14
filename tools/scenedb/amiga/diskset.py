"""Group disk-image file names into ordered multi-disk sets.

Multi-disk releases name their disks with a trailing marker: ``DesertDreamA``,
``9Fingers-B``, ``tbl-tt03``, ``batman-disk2``, ``reel-disk-2-of-2``,
``demo`` + ``demo-d2``. A set is the files that share a stem and carry
distinct markers; the marker gives the disk order.
"""

import os
import re

DISK_EXTS = (".adf", ".adz", ".dms")
# Preferred format when the same disk exists twice (adf + dms of one disk).
_FORMAT_RANK = {".adf": 0, ".adz": 1, ".dms": 2}

_SEP = r"[-_ .]*"
_PATTERNS = (
    re.compile(rf"^(.*?){_SEP}(?:disk|disc){_SEP}0?([1-9])(?:{_SEP}of{_SEP}\d)?$"),
    re.compile(rf"^(.*?){_SEP}side{_SEP}([a-d1-4])$"),
    re.compile(r"^(.*?)[-_ .]d([1-9])$"),
    re.compile(rf"^(.*?){_SEP}0?([1-9])(?:{_SEP}of{_SEP}\d)?$"),
    re.compile(r"^(.*?[^a-z])([a-f])$"),       # ...-A, ...-a
    re.compile(r"^(.*?)([a-f])$"),             # ...DreamA (needs set agreement)
)


def _norm(stem):
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def parse(name):
    """``(stem_key, disk_number)`` for a file name; number is None when the
    name carries no marker. Letters map to numbers (a=1)."""
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    for pat in _PATTERNS:
        m = pat.match(stem)
        if m and len(_norm(m.group(1))) >= 2:
            mark = m.group(2)
            num = ord(mark) - ord("a") + 1 if mark.isalpha() else int(mark)
            return _norm(m.group(1)), num
    return _norm(stem), None


def is_disk_image(name):
    return os.path.splitext(name)[1].lower() in DISK_EXTS


def group(names):
    """Split disk-image names into ordered sets.

    Returns a list of lists of names; each inner list is one release in disk
    order (a single-disk release is a list of one). Sets come first, largest
    first. Duplicated disks (same marker) keep the preferred format.
    """
    by_stem = {}
    unmarked = []
    for n in names:
        key, num = parse(n)
        if num is None:
            unmarked.append((key, n))
        else:
            by_stem.setdefault(key, {}).setdefault(num, []).append(n)

    sets, singles = [], []
    for key, disks in by_stem.items():
        # An unmarked file with the set's stem is its first disk
        # (``demo.adf`` + ``demo-d2.adf``).
        for k, n in list(unmarked):
            if k == key and 1 not in disks:
                disks[1] = [n]
                unmarked.remove((k, n))
        if len(disks) < 2:
            # A lone marker is not a set: ``Sanity-Arte`` is not disk "e".
            singles.extend(n for ns in disks.values() for n in ns)
            continue
        ordered = [min(disks[num], key=_fmt_rank) for num in sorted(disks)]
        sets.append(ordered)
    singles.extend(n for _, n in unmarked)
    sets.sort(key=len, reverse=True)
    return sets + [[n] for n in sorted(singles)]


def numbers(disk_set):
    """The disk numbers of an ordered set, for a completeness check."""
    return [parse(n)[1] or 1 for n in disk_set]


def is_complete(disk_set):
    """True when the set's markers run 1..n without a gap."""
    nums = numbers(disk_set)
    return len(disk_set) == 1 or nums == list(range(1, len(nums) + 1))


def _fmt_rank(name):
    return _FORMAT_RANK.get(os.path.splitext(name)[1].lower(), 9)
