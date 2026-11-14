"""Find the bootable media of a production: the disk set of its release.

Sources, in order: the CSDb mirror (csdbmirror.py, the release's files as
downloaded) and the scene.org mirror (zips, unpacked
into the work dir). The first source with disk images wins. Disk images
linked one by one on scene.org form a set when no source has any.
"""

import dataclasses
import os
import pathlib
import zipfile

from . import config, csdbmirror, diskset


@dataclasses.dataclass
class Variant:
    kind: str            # floppy
    disks: list          # image paths, in disk order
    note: str = ""
    boot_disk: int = 0   # index of the disk that holds the production
    boot_file: str = ""  # its directory entry; empty = autostart the first file


def variants(prod):
    """``(variants, problems)`` for a catalog.Production."""
    problems = []
    bare = []
    for cls, param in prod.links:
        src = None
        if cls == "CsdbRelease":
            src = csdbmirror.directory(param)
        elif cls == "SceneOrgFile" and str(param).lower().endswith(".zip"):
            src = _unzip(prod.id, config.SCENEORG_DIR / str(param).lstrip("/"))
        if cls == "SceneOrgFile" and diskset.is_disk_image(str(param)):
            src = config.SCENEORG_DIR / str(param).lstrip("/")
            if src.is_file():
                bare.append(str(src))
            continue
        if src is None or not src.exists():
            continue
        disks = diskset.distinct(diskset.order(_walk(src)))
        if disks:
            return [Variant("floppy", disks, note=f"{cls} {param}")], problems
    if bare:          # every disk side linked on its own, not in a zip
        return [Variant("floppy", diskset.distinct(diskset.order(bare)),
                         note="SceneOrgFile disks")], problems
    problems.append("no-disk-images")
    return [], problems


def _walk(root):
    for dirpath, _, files in os.walk(root):
        for f in files:
            yield os.path.join(dirpath, f)


def _unzip(prod_id, zip_path):
    """Unpack the disk images of a zip into the work dir. None if unreadable."""
    if not zip_path.exists():
        return None
    dest = config.WORK / "media" / str(prod_id) / zip_path.stem
    if not dest.exists():
        try:
            with zipfile.ZipFile(zip_path) as z:
                for info in z.infolist():
                    name = pathlib.PurePosixPath(info.filename)
                    if (info.is_dir() or name.is_absolute() or ".." in name.parts
                            or not diskset.is_disk_image(info.filename)):
                        continue
                    out = dest / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(info))
        except (zipfile.BadZipFile, OSError):
            return None
        dest.mkdir(parents=True, exist_ok=True)
    return dest
