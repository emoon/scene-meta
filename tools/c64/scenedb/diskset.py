"""Order the disk images of one release into a set.

C64 releases name their disks ``Mojo_Side1``, ``EdgeOfDisgrace_1a``,
``demo-disk2``, ``part A``. Images that sit together in one release are one
set; the natural order of their names is the disk order (digits compare as
numbers, so ``disk2`` comes before ``disk10``).
"""

import hashlib
import os
import re

DISK_EXTS = (".d64", ".g64")
# Preferred format when the same disk exists twice (d64 + g64 of one disk).
_FORMAT_RANK = {".d64": 0, ".g64": 1}


def is_disk_image(name):
    """A real disk image: not macOS archive junk (``__MACOSX/``, ``._x.d64``)."""
    parts = re.split(r"[\\/]", name)
    if "__MACOSX" in parts or parts[-1].startswith("._"):
        return False
    return os.path.splitext(name)[1].lower() in DISK_EXTS


def natural_key(name):
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", stem)]


def order(names):
    """The disk images among ``names`` as one ordered set, one file per disk."""
    best = {}
    for n in names:
        if not is_disk_image(n):
            continue
        stem = os.path.splitext(n)[0].lower()
        if stem not in best or _fmt_rank(n) < _fmt_rank(best[stem]):
            best[stem] = n
    return sorted(best.values(), key=natural_key)


def _fmt_rank(name):
    return _FORMAT_RANK.get(os.path.splitext(name)[1].lower(), 9)


def distinct(paths):
    """``paths`` (existing files) without later copies of an image already seen.

    A copy is a byte-identical image, or a d64 that holds the same files
    (same data, however the disk is labelled or laid out): releases ship a
    demo twice, once per wrapper (``Revolution_SA`` and ``... Revolution-s1``).
    """
    seen, kept = set(), []
    for p in paths:
        with open(p, "rb") as f:
            data = f.read()
        keys = {hashlib.md5(data).digest()}
        payload = _payload(data)
        if payload:
            keys.add(payload)
        if seen.isdisjoint(keys):
            kept.append(p)
        seen |= keys
    return kept


_ZONES = ((17, 21), (7, 19), (6, 18), (5, 17))      # (tracks, sectors) from track 1
_D64_SIZES = (174848, 175531)


def _sector_offset(track, sector):
    offset = 0
    for tracks, sectors in _ZONES:
        if track <= tracks:
            return (offset + (track - 1) * sectors + sector) * 256
        offset += tracks * sectors
        track -= tracks
    return None


def _chain(data, track, sector):
    """``(payload bytes, sectors)`` of the chain starting at ``track``/``sector``."""
    out, seen = bytearray(), set()
    while track and (track, sector) not in seen:
        seen.add((track, sector))
        at = _sector_offset(track, sector)
        if at is None or at + 256 > len(data):
            break
        nxt_t, nxt_s = data[at], data[at + 1]
        out += data[at + 2:at + (256 if nxt_t else nxt_s + 1)]
        track, sector = nxt_t, nxt_s
    return bytes(out), len(seen)


def _used_sectors(data):
    """Sectors the BAM marks as in use, the directory track left out."""
    bam = _sector_offset(18, 0)
    free = sum(data[bam + 4 * t] for t in range(1, 36) if t != 18)
    return 664 - free


def _payload(data):
    """Fingerprint of the file contents of a d64. Names, disk header and
    sector layout are left out. ``b""`` if it is not a d64, holds no files, or
    the files do not account for the sectors in use (a fake directory in front
    of raw tracks says nothing about the data)."""
    if len(data) not in _D64_SIZES:
        return b""
    files, blocks, track, sector, seen = [], 0, 18, 1, set()
    while track and (track, sector) not in seen:
        seen.add((track, sector))
        at = _sector_offset(track, sector)
        if at is None:
            break
        for e in range(at, at + 256, 32):
            if data[e + 2] & 0x07 in (1, 2, 3):      # SEQ, PRG, USR
                body, n = _chain(data, data[e + 3], data[e + 4])
                files.append(hashlib.md5(body).digest())
                blocks += n
        track, sector = data[at], data[at + 1]
    used = _used_sectors(data)
    if not files or abs(blocks - used) > max(2, used // 10):
        return b""
    return hashlib.md5(b"".join(sorted(files))).digest()
