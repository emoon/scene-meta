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


_PROGRAMS = (".prg", ".crt")


def require_mirror():
    """A gate must have a catalog and at least one media mirror."""
    from ..core.config import INDEX_DB
    from ..core.errors import CannotPlay
    if not INDEX_DB.is_file():
        raise CannotPlay(f"no Demozoo index: {INDEX_DB}")
    if not any(p.is_dir() for p in (config.CSDB_DIR, config.SCENEORG_DIR)):
        raise CannotPlay("no C64 media mirror")


def _downloads(prod):
    """Existing source downloads, in catalog order; never unpacked work files."""
    for cls, param in prod.links:
        if cls == "CsdbRelease":
            path = csdbmirror.directory(param)
        elif cls == "SceneOrgFile":
            path = config.SCENEORG_DIR / str(param).lstrip("/")
        else:
            continue
        if path is not None and path.exists():
            yield path


def playables(prod):
    """Disk sets and standalone programs/cartridges available to the player.

    Keep the sweep's disk-only selection intact. Explicit entries may select
    a program or cartridge alongside the disk set, without guessing a file.
    """
    found, problems = variants(prod)
    for src in _downloads(prod):
        if src.is_dir():
            paths = sorted(pathlib.Path(f) for f in _walk(src))
        elif src.suffix.lower() == ".zip":
            dest = config.WORK / "programs" / str(prod.id) / src.stem
            try:
                with zipfile.ZipFile(src) as z:
                    paths = []
                    for info in z.infolist():
                        name = pathlib.PurePosixPath(info.filename)
                        if (info.is_dir() or name.is_absolute() or ".." in name.parts
                                or name.suffix.lower() not in _PROGRAMS):
                            continue
                        out = dest / name
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(info))
                        paths.append(out)
            except (zipfile.BadZipFile, OSError):
                continue
        else:
            paths = [src]
        for path in paths:
            if path.suffix.lower() in _PROGRAMS:
                found.append(Variant(path.suffix.lower()[1:], [str(path)]))
    return found, [] if found else problems


def production(prod):
    from ..core.errors import CannotPlay
    from . import catalog
    found = catalog.productions({prod})
    if not found:
        raise CannotPlay(f"no C64 production {prod} in the catalog")
    return found[0]


def download_sha256(prod):
    """Digest source download names and bytes, independent of unpack paths."""
    import hashlib
    from ..core.errors import CannotPlay
    digest = hashlib.sha256()
    count = 0
    for source in _downloads(production(prod)):
        paths = sorted(pathlib.Path(f) for f in _walk(source)) if source.is_dir() else [source]
        for path in paths:
            name = str(path.relative_to(source)) if source.is_dir() else path.name
            digest.update(name.encode() + b"\0")
            file_hash = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    file_hash.update(chunk)
            digest.update(file_hash.digest())
            count += 1
    if not count:
        raise CannotPlay(f"no mirrored download for {prod}")
    return digest.hexdigest()
