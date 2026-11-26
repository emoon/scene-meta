"""Turn a production's NAS files into bootable variants.

A variant is either a set of floppy images (booted from DF0, later disks on
the swap list) or a directory booted as a hard drive whose startup-sequence
runs one executable, or is the download's own launcher script. A disk set
whose first disk cannot boot (made to be started from Workbench) gets a
patched copy of disk 1 that boots into the demo. Archives are unpacked under
WORK; NAS files are read only.
"""

import dataclasses
import hashlib
import os
import pathlib
import re
import shutil
import struct
import subprocess
import zipfile

from ..core.errors import CannotPlay
from . import config, diskset, workbench

HUNK_MAGIC = b"\x00\x00\x03\xf3"
ARCHIVE_EXTS = (".zip", ".lha", ".lzh", ".lzx")
MAX_VARIANTS = 3
# Extensions of files that are loaded, not started, even with a hunk header.
_DATA_EXTS = {".dat", ".data", ".bin", ".ovl"}
# Numbered sub-part executables (tbl-cd.e01..e04, part.p02) and backups:
# deprioritized below main launchers, never dropped if sole candidate.
_SUBPART_EXT = re.compile(r"^\.(?:[a-z]\d{2,3}|bak|old)$", re.I)
# Documentation files that may mention an executable name on a line.
_DOC_EXTS = {".readme", ".txt", ".nfo", ".diz", ".doc", ".guide", ".man",
             ".asc", ".ans", ".html", ".htm", ".md"}
# Directories that hold system files, never the demo's own executable.
_SYSTEM_DIRS = {"c", "l", "libs", "devs", "fonts", "system", "prefs",
                "utilities", "tools", "expansion", "storage", "classes"}


@dataclasses.dataclass
class Variant:
    kind: str           # "floppy" | "hd"
    disks: list         # floppy: ordered disk image paths
    root: str = None    # hd: directory mounted as the boot volume
    command: str = None  # hd: startup-sequence text (None: the tree's own)
    note: str = ""
    ffs: bool = False   # floppy: disk 1 is Fast File System (needs KS2+)
    run: str = None     # the file it starts, as an entry names it
    choice: bool = False  # the media left a choice of it: an entry names it
    assign: dict = None  # hd: AmigaDOS assigns (name -> path) to set before run

    @property
    def label(self):
        if self.kind == "floppy":
            return " + ".join(os.path.basename(d) for d in self.disks)
        return f"hd:{(self.command or 'own startup-sequence').strip()}"

    @property
    def complete(self):
        return not self.disks or diskset.is_complete(self.disks)


def _is_apple_double(path):
    """Resource-fork droppings of a Mac archiver (``__MACOSX/._demo.adf``):
    named like the file they shadow, but not a disk."""
    return path.name.startswith("._") or "__MACOSX" in path.parts


_HTML_HEADS = (b"<html", b"<!do", b"<head", b"<?xml")


def image_problem(path):
    """Why a disk-image file is no Amiga disk, or None: an HTML error page
    saved under the disk's name, an image of the wrong size, a disk from an
    Atari ST. DMS and ADZ carry their own framing, so they are not sized."""
    with open(path, "rb") as f:
        head = f.read(1024)
    if head.lstrip()[:5].lower().startswith(_HTML_HEADS):
        return "html-not-a-disk"
    if path.suffix.lower() != ".adf":
        return None
    size = path.stat().st_size
    # Atari ST boot sectors start with a 68000 BRA and a PC-style BPB with
    # 512-byte sectors. Short images (down to one cylinder) and long ones
    # still run: trackloaders read only what they need. Under one cylinder
    # is a stub or an error message.
    if head[:1] == b"\x60" and head[11:13] == b"\x00\x02":
        return "atari-st-disk"
    if size < CYL_BYTES:
        return "bad-image-size"
    return None


def is_ffs(boot):
    """True for a DOS bootblock of the Fast File System (flags bit 0):
    Kickstart 1.x cannot mount those."""
    return boot[:3] == b"DOS" and len(boot) > 3 and boot[3] & 1 == 1


def flag_ffs(v, work):
    """``v`` with ``ffs`` set when its first disk boots only on Kickstart 2+."""
    if v.kind == "floppy" and v.disks:
        adf = _as_adf(v.disks[0], work)
        if adf is not None:
            with open(adf, "rb") as f:
                v.ffs = is_ffs(f.read(4))
    return v


def sniff(path):
    """'disk' | 'archive' | 'exe' | None for one file."""
    name = path.name.lower()
    if name.endswith(".info") or _is_apple_double(path):
        return None
    if diskset.is_disk_image(name):
        return "disk"
    if name.endswith(ARCHIVE_EXTS):
        return "archive"
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    if head[:4] == HUNK_MAGIC:
        size = path.stat().st_size
        return "exe" if size >= 28 and size % 4 == 0 else None
    if head[:4] == b"DMS!":
        return "disk"
    if head[:2] == b"PK" or head[2:5] in (b"-lh", b"-lz"):
        return "archive"
    if head[:3] == b"DOS" and path.stat().st_size in (901120, 1802240):
        return "disk"
    return None


def _make_owner_rwx(top):
    """Give the owner full access to ``top`` and everything below it. Amiga
    protection bits come out of the unpackers as odd modes."""
    def grant(p):
        try:
            os.chmod(p, os.stat(p).st_mode | 0o700)
        except OSError:
            pass

    grant(top)
    # Top-down and lazy: each directory is opened up before walk enters it.
    for root, dirs, files in os.walk(top):
        for n in dirs + files:
            grant(os.path.join(root, n))


def _rmtree(top):
    """``shutil.rmtree`` for a tree an interrupted unpack left unreadable."""
    _make_owner_rwx(top)
    shutil.rmtree(top)


def unpack(archive, dest):
    """Extract an archive into ``dest``. Returns an error string or None."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        # Amiga archives name files in Latin-1, not DOS cp437 or a guess.
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive, metadata_encoding="latin-1") as z:
                z.extractall(dest)
        else:
            try:
                subprocess.run(["unar", "-q", "-f", "-D", "-e", "latin1",
                                "-o", str(dest),
                                str(archive)], check=True,
                               capture_output=True, timeout=120)
            except subprocess.CalledProcessError:
                # unar rejects some good -lh5- members; lha checks CRCs.
                if archive.suffix.lower() not in (".lha", ".lzh"):
                    raise
                _rmtree(dest)   # drop unar's partial tree
                dest.mkdir(parents=True)
                subprocess.run(["lha", f"xqfw={dest}", str(archive)],
                               check=True, capture_output=True, timeout=120)
    except Exception as e:  # noqa: BLE001 - reported per archive
        return f"unpack-error:{type(e).__name__}"
    _latin1_names_to_utf8(dest)
    _make_owner_rwx(dest)
    return None


def unpack_into(archive, dest):
    """``unpack`` that adds to what ``dest`` already holds: the parts of a
    release split over several archives. Returns an error string or None."""
    if not dest.exists():
        return unpack(archive, dest)
    part = dest.with_name(dest.name + ".part")
    if part.exists():
        _rmtree(part)
    err = unpack(archive, part)
    if err is None:
        shutil.copytree(part, dest, dirs_exist_ok=True)
    _rmtree(part)
    return err


def _latin1_names_to_utf8(top):
    """Rename raw Latin-1 (Amiga) names to UTF-8, as Amiberry expects."""
    for root, dirs, files in os.walk(bytes(top), topdown=False):
        for n in dirs + files:
            try:
                n.decode("utf-8")
            except UnicodeDecodeError:
                os.rename(os.path.join(root, n),
                          os.path.join(root, n.decode("latin-1").encode()))


def _walk_files(top):
    for root, _, files in os.walk(top):
        for n in files:
            yield pathlib.Path(root) / n


def _digest(path, algorithm):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _sha1(path):
    return _digest(path, "sha1")


@dataclasses.dataclass
class _Found:
    """What a production's files hold, its archives unpacked under ``work``."""
    work: pathlib.Path
    problems: list = dataclasses.field(default_factory=list)
    disks: dict = dataclasses.field(default_factory=dict)  # name: (sha1, path)
    exes: list = dataclasses.field(default_factory=list)
    trees: list = dataclasses.field(default_factory=list)  # unpacked archives

    def take(self, path, depth=0, parts=()):
        """Sort one file in. An archive is unpacked, together with the other
        ``parts`` of its release, and what it holds is taken in turn."""
        kind = sniff(path)
        if kind == "disk":
            self._disk(path)
        elif kind == "exe":
            self.exes.append(path)
        elif kind == "archive" and depth < 2:
            self._archive(path, depth, parts)

    def _disk(self, path):
        bad = image_problem(path)
        if bad:
            self.problems.append(f"{path.name}: {bad}")
            return
        self.disks.setdefault(path.name, (_sha1(path), path))

    def _archive(self, path, depth, parts):
        out = self.work / "x" / f"{depth}-{path.name}"
        if out.exists():
            _rmtree(out)
        for a in (path, *parts):
            err = unpack_into(a, out)
            if err:
                self.problems.append(f"{a.name}: {err}")
                return
        self.trees.append(out)
        for f in sorted(_walk_files(out)):
            if sniff(f) != "exe":
                self.take(f, depth + 1)


def _download(src):
    """The files of a production's download, by name."""
    return [f for f in sorted(src.iterdir())
            if f.is_file() and not f.name.endswith(".part")]


def download_sha256(prod_id):
    """The SHA-256 of the production's download: of its file, or, when it
    has several, of the name and SHA-256 of each. None when it has none."""
    src = config.prod_dir(prod_id)
    files = _download(src) if src.is_dir() else []
    if len(files) == 1:
        return _digest(files[0], "sha256")
    if not files:
        return None
    return hashlib.sha256("".join(
        f"{_digest(f, 'sha256')}  {f.name}\n" for f in files).encode()).hexdigest()


def _release_files(src):
    """``(file, parts)`` for each of a production's files to take. A release
    split over numbered archives (pwl-rpg1.lha .. pwl-rpg3.lha) unpacks into
    one tree: the first holds the demo, the others, its ``parts``, the data."""
    files = _download(src)
    parts = {}
    for group in diskset.group([f.name for f in files if sniff(f) == "archive"]):
        parts[group[0]] = [src / n for n in group[1:]]
        parts.update((n, None) for n in group[1:])
    return [(f, parts.get(f.name, ())) for f in files
            if parts.get(f.name, ()) is not None]


def _seen_before(shas, seen):
    """Is the disk set with these hashes a repeat of one in ``seen``? A
    single disk also when it is part of a set."""
    return shas in seen or (len(shas) == 1 and any(shas[0] in s for s in seen))


def _disk_variants(disks, prod_id, work, run=None):
    """A floppy variant for each disk set among ``disks``."""
    # Group by name first, then drop byte-identical repeats: the same disk is
    # often mirrored under two names (Oxygene-ControlA = control1), and only
    # one of them may belong to a complete set.
    out, seen = [], set()
    for group in diskset.group(list(disks)):
        shas = tuple(disks[n][0] for n in group)
        if _seen_before(shas, seen):
            continue
        seen.add(shas)
        paths = [str(disks[n][1]) for n in group]
        joined = _join_dms_parts(paths, work)
        if joined:
            paths = [joined]
        out.append(flag_ffs(launch_variant(paths, prod_id, only_unbootable=True,
                                           run=run)
                            or Variant("floppy", paths), work))
    return out


def require_mirror():
    """Raise unless the Demozoo mirror is there: without it every production
    reads as one that has no files."""
    if not config.DEMOZOO_DIR.is_dir():
        raise CannotPlay(f"no Demozoo mirror at {config.DEMOZOO_DIR}"
                         " (is the share mounted?)")


def variants(prod_id, title="", run=None):
    """``(variants, problems)`` for one production. Problems are short
    reason strings for files that produced nothing. ``title`` picks the
    executable named after the production in an unpacked archive; ``run``
    is the file an entry says to start, which goes before any pick."""
    src = config.prod_dir(prod_id)
    if not src.is_dir():
        return [], ["no-files-on-nas"]
    work = config.WORK / "media" / str(prod_id)
    found = _Found(work)
    for f, parts in _release_files(src):
        found.take(f, 0, parts)

    out = _disk_variants(found.disks, prod_id, work, run)
    out += [v for v in (_tree_variant(t, title, run) for t in found.trees) if v]
    out += [_exe_variant(exe, work) for exe in found.exes]
    if not out and not found.problems:
        found.problems.append("no-bootable-media")
    return out[:MAX_VARIANTS], found.problems


def _tree_variant(tree, title="", run=None):
    """A hard-drive variant for an unpacked archive, or None when it holds no
    executable of its own (disk-image-only archives). An entry's ``run``
    may name a Workbench project icon or a script of the tree in place of an
    executable."""
    if run:
        proj = _named_project(tree, run)
        if proj is not None:
            return proj
        script = _named_script(tree, run)
        if script is not None:
            return _script_variant(script, run)
    boot = next((p.parent.parent for p in _walk_files(tree)
                 if p.name.lower() == "startup-sequence"
                 and p.parent.name.lower() == "s"), None)
    exe, note = _pick_exe(tree, title, run)
    if exe is None:
        if boot is not None:
            return Variant("hd", [], root=str(boot), command=None,
                           note="own startup-sequence")
        return None
    return Variant("hd", [], root=str(exe.parent), command=f'"{exe.name}"\n',
                   note=note, run=exe.name, choice=bool(note))


def _is_script(path):
    """Is ``path`` a small text file, as an AmigaDOS script is?"""
    if path.stat().st_size > 16384:
        return False
    data = path.read_bytes()
    return bool(data) and data[:4] != HUNK_MAGIC and b"\0" not in data


def _named_script(tree, run):
    """The script an entry names in ``tree`` by its name or its path, or
    None."""
    return next((p for p in sorted(_walk_files(tree))
                 if run in (p.name, _rel(p, tree)) and _is_script(p)), None)


def _script_variant(script, run, note=""):
    """A hard-drive variant that executes ``script`` from its directory:
    its text is the startup-sequence, so its ``cd`` and assigns hold for
    the parts it runs."""
    body = script.read_text("latin-1").rstrip("\r\n") + "\n"
    return Variant("hd", [], root=str(script.parent),
                   command=f"{workbench.GO_ON}\n" + body,
                   note=note, run=run, choice=True)


def _norm(name):
    return "".join(c for c in name.lower() if c.isalnum())


def _is_bbs_ad(path):
    """True for SpeedHunk/Exe-Ad BBS advert stubs bundled in archive roots
    (``_negerkuß!!.exe``, ``WHEREFUNROLEZ.EXE``, ``LE-win1196.exe``,
    ``friendsonly.exe``): every one begins with a HUNK_DEBUG block tagged
    ``HEADDBGV01``. Deprioritized below real executables, never dropped if
    it is the sole executable in the archive."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    return b"HEADDBGV01" in head[24:64]


def _pick_exe(tree, title="", run=None):
    """The executable a user would start in an unpacked tree, plus a note
    when there was a choice: ``(path | None, note)``. ``run`` is the one
    an entry names, by its name or its path in the tree: it is the one
    started when it is there."""
    cands = []
    for p in _walk_files(tree):
        rel = p.relative_to(tree).parts
        if any(part.lower() in _SYSTEM_DIRS for part in rel[:-1]):
            continue
        if p.suffix.lower() in (".library", ".device", ".info"):
            continue
        if "install" in p.name.lower() or p.name.lower().endswith("-handler"):
            continue
        if sniff(p) == "exe":
            cands.append(p)
    if not cands:
        return None, ""
    # Explicit ``run`` first, then non-BBS-ad and non-data executables, then
    # one named after the production (even inside a subdirectory of a party
    # pack), then shallowest, then one with an icon (what a user
    # double-clicks), then the biggest.
    cands.sort(key=lambda p: (run not in (p.name, _rel(p, tree)),
                              _is_bbs_ad(p),
                              p.suffix.lower() in _DATA_EXTS
                              or bool(_SUBPART_EXT.match(p.suffix)),
                              not _named_after(p.stem, title),
                              len(p.relative_to(tree).parts),
                              not p.with_name(p.name + ".info").exists(),
                              -p.stat().st_size))
    exe = cands[0]
    note = f"{len(cands)} executables, picked {exe.name}" if len(cands) > 1 else ""
    return exe, note


def _rel(path, tree):
    """``path`` as an Amiga path within ``tree``."""
    return "/".join(path.relative_to(tree).parts)


def _exe_variant(exe, work):
    root = work / "exe" / exe.name
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exe, root / exe.name)
    return Variant("hd", [], root=str(root), command=f'"{exe.name}"\n',
                   run=exe.name)


CYLINDERS, CYL_BYTES = 80, 11264


def dms_cylinders(path):
    """``(lowest, highest)`` cylinder a DMS archive holds, or None when it is
    not a DMS file."""
    with open(path, "rb") as f:
        head = f.read(20)
    if head[:4] != b"DMS!" or len(head) < 20:
        return None
    return struct.unpack(">HH", head[16:20])


def _join_dms_parts(paths, work):
    """One ADF from DMS archives that each hold part of the same disk
    (Ilex: ilex-a.dms is cylinders 0-39, ilex-b.dms 40-79), or None when
    ``paths`` are whole disks."""
    ranges = [dms_cylinders(p) for p in paths]
    if len(paths) < 2 or None in ranges \
            or any(r == (0, CYLINDERS - 1) for r in ranges):
        return None
    data = bytearray(CYLINDERS * CYL_BYTES)
    for p, (low, high) in zip(paths, ranges):
        adf = _as_adf(p, work)
        if adf is None:
            return None
        part = adf.read_bytes()[:(high - low + 1) * CYL_BYTES]
        data[low * CYL_BYTES:low * CYL_BYTES + len(part)] = part
    out = work / "adf" / (pathlib.Path(paths[0]).stem + "-joined.adf")
    out.write_bytes(data)
    return str(out)


def _as_adf(disk, work):
    """A plain ADF for ``disk`` (DMS/ADZ are decoded into WORK), or None."""
    disk = pathlib.Path(disk)
    suffix = disk.suffix.lower()
    if suffix == ".adf":
        return disk
    out = work / "adf" / (disk.stem + ".adf")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if suffix == ".adz":
                import gzip
                out.write_bytes(gzip.decompress(disk.read_bytes()))
            else:
                subprocess.run(["xdms", "-q", "u", str(disk), "+" + str(out)],
                               capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError, EOFError):
            return None
    return out if out.exists() else None


def bootable(adf_bytes):
    """True when Kickstart would boot the disk: a DOS bootblock with a valid
    checksum."""
    block = adf_bytes[:1024]
    if len(block) < 1024 or block[:3] != b"DOS":
        return False
    total = 0
    for (word,) in struct.iter_unpack(">I", block):
        total += word
        if total > 0xFFFFFFFF:
            total = (total + 1) & 0xFFFFFFFF
    return total == 0xFFFFFFFF


def volume_name(adf_bytes):
    """The DOS volume name from the root block, or None (not a DOS disk)."""
    root = adf_bytes[880 * 512:881 * 512]
    if len(root) < 512 or root[:4] != b"\0\0\0\x02":
        return None
    n = root[432]
    return root[433:433 + n].decode("latin-1") or None


def _unpack_disk(adf, box):
    """The files of a DOS disk image, unpacked into ``box``/files (wiped
    first), or None. xdftool also writes .xdfmeta/.bootcode/.blkdev next to
    the tree and refuses to overwrite them, hence a folder of its own."""
    if box.exists():
        shutil.rmtree(box)
    box.mkdir(parents=True)
    tree = box / "files"
    try:
        subprocess.run(["xdftool", str(adf), "unpack", str(tree)],
                       capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return tree


# x.001, x.lzx.002, EM.1, M.data2
_PART = re.compile(r"^(.+?\.(?:[a-z]+)?)(\d{1,3})$", re.I)


def _split_body(data):
    """The payload of one split part: a joinz part (IFF FORM SPLT) carries
    it in its BODY chunk, a plain cut is all payload."""
    if data[:4] != b"FORM" or data[8:12] != b"SPLT":
        return data
    i = 12
    while i + 8 <= len(data):
        size = int.from_bytes(data[i + 4:i + 8], "big")
        if data[i:i + 4] == b"BODY":
            return data[i + 8:i + 8 + size]
        i += 8 + size + (size & 1)
    return data


def _join_split_parts(tree):
    """Join files split across disks (``x.lzx.001`` + ``x.lzx.002``, or
    ``EM.1`` + ``em.2``) back into one file, named after the first part,
    with ``.exe`` added when a file of that name is already there (Flowers:
    the parts join to Flowers.exe beside the Flowers script)."""
    groups = {}
    for p in _walk_files(tree):
        m = _PART.match(p.name)
        if m:
            groups.setdefault((p.parent, m.group(1).lower()), []).append(
                (int(m.group(2)), p))
    for (parent, _), parts in groups.items():
        parts.sort()
        # Only the first piece of a split executable carries a hunk header.
        if len(parts) < 2 or any(sniff(p) == "exe" for _, p in parts[1:]):
            continue
        dest = parent / _PART.match(parts[0][1].name).group(1).rstrip(".")
        if dest.exists():
            dest = dest.with_name(dest.name + ".exe")
        with open(dest, "wb") as out:
            for _, p in parts:
                out.write(_split_body(p.read_bytes()))
                p.unlink()


def _named_after(name, title):
    n, t = _norm(name), _norm(title)
    return bool(t and n) and (n in t or t in n)


def _launch_script(tree, title=""):
    """A script that runs the demo's executables in turn (Eternal Madness:
    em1.exe, em2.exe, em3.exe; Stag: intro.exe then stag.ht; MindWalker:
    ``mw:data/mindwalker.exe``), or None. A small text file outside the system
    directories, not an installer or doc file, with a line naming an executable
    in ``tree``. One named after the production or with an icon wins."""
    exes = {q.name.lower() for q in _walk_files(tree)
            if not any(part.lower() in _SYSTEM_DIRS
                       for part in q.relative_to(tree).parts[:-1])
            and sniff(q) == "exe"}
    if not exes:
        return None
    cands = []
    for p in _walk_files(tree):
        rel = p.relative_to(tree).parts
        if any(part.lower() in _SYSTEM_DIRS | {"s"} for part in rel[:-1]) \
                or "install" in p.name.lower() \
                or p.suffix.lower() in _DOC_EXTS | {".info"}:
            continue
        if not _is_script(p):
            continue
        lines = p.read_text("latin-1").splitlines()
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith(";"):
                continue
            tok = s.split()[0].strip('"').lower()
            base = tok.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
            if base in exes:
                cands.append(p)
                break
    cands.sort(key=lambda p: (not _named_after(p.name, title),
                              not p.with_name(p.name + ".info").exists(),
                              len(p.relative_to(tree).parts)))
    return cands[0] if cands else None


def _info_default_tool(info_path):
    """Default Tool string of an Amiga Workbench Project icon (``WBPROJECT``,
    do_Type == 4), or None."""
    try:
        data = info_path.read_bytes()
    except OSError:
        return None
    if len(data) < 78 or data[:2] != b"\xe3\x10" or data[48] != 4:
        return None
    if struct.unpack(">I", data[50:54])[0] == 0:
        return None
    off = 78 + (56 if struct.unpack(">I", data[66:70])[0] else 0)
    for ptr_off in (22, 26):
        if struct.unpack(">I", data[ptr_off:ptr_off + 4])[0]:
            if off + 20 > len(data):
                return None
            _, _, w, h, depth = struct.unpack(">hhhhh", data[off:off + 10])
            if w <= 0 or h <= 0 or depth <= 0 or depth > 8:
                return None
            off += 20 + ((w + 15) // 16) * 2 * h * depth
    if off + 4 > len(data):
        return None
    slen = struct.unpack(">I", data[off:off + 4])[0]
    if slen == 0 or off + 4 + slen > len(data):
        return None
    return data[off + 4:off + 4 + slen].rstrip(b"\0").decode("latin-1", "replace").strip() or None


def _resolve_project_icon(info_path, tree, run=None):
    """A hard-drive variant for a Workbench Project ``.info`` icon whose
    Default Tool is ``IconX`` or an executable in ``tree``, or None."""
    proj = info_path.with_name(info_path.name[:-5])
    if not proj.is_file() or proj.suffix.lower() in _DOC_EXTS:
        return None
    tool_raw = _info_default_tool(info_path)
    if not tool_raw:
        return None
    tool_base = tool_raw.replace("\\", "/").rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    rel = _rel(proj, tree)
    if tool_base.lower() == "iconx" and _is_script(proj):
        return _script_variant(proj, run or rel, f"IconX script {rel}")
    # Match an executable in the project's dir first, then anywhere in tree.
    matches = [q for q in sorted(_walk_files(tree))
               if q.name.lower() == tool_base.lower() and sniff(q) == "exe"]
    if not matches:
        return None
    matches.sort(key=lambda q: (q.parent != proj.parent, len(q.relative_to(tree).parts)))
    tool = matches[0]
    if tool.parent == proj.parent:
        root, cmd = proj.parent, f'"{tool.name}" "{proj.name}"\n'
    else:
        root, cmd = tree, f'"{_rel(tool, tree)}" "{rel}"\n'
    return Variant("hd", [], root=str(root), command=cmd,
                   note=f"project icon {rel} -> {tool.name}",
                   run=run or rel, choice=True)


def _named_project(tree, run):
    """The Workbench Project icon variant ``run`` names in ``tree``, or None."""
    for p in sorted(_walk_files(tree)):
        if p.name.lower().endswith(".info"):
            proj = p.with_name(p.name[:-5])
            if run in (proj.name, _rel(proj, tree)):
                v = _resolve_project_icon(p, tree, run=run)
                if v is not None:
                    return v
    return None


def _project_icon(tree, title=""):
    """A Workbench Project icon variant in ``tree`` (ScalaMMPlayer, MoviePlayer,
    MainActor, IconX), preferring one named after ``title``, or None."""
    cands = []
    for p in sorted(_walk_files(tree)):
        rel = p.relative_to(tree).parts
        if any(part.lower() in _SYSTEM_DIRS | {"s"} for part in rel[:-1]):
            continue
        if not p.name.lower().endswith(".info") or "install" in p.name.lower():
            continue
        v = _resolve_project_icon(p, tree)
        if v is not None:
            proj = p.with_name(p.name[:-5])
            cands.append((not _named_after(proj.stem, title),
                          len(rel), proj.name.lower(), v))
    cands.sort(key=lambda x: x[:3])
    return cands[0][3] if cands else None


_STD_VOLS = {
    "ram", "sys", "s", "c", "l", "libs", "devs", "fonts", "env", "envarc",
    "t", "clips", "rexx", "locale", "prefs", "printers", "keymaps", "help",
    "nil", "con", "raw", "prt", "ser", "par", "speak", "pipe", "audio", "aux",
    "df0", "df1", "df2", "df3", "dh0", "dh1", "dh2", "dh3", "rad", "pc0",
    "pc1", "progdir", "demo", "work", "workbench", "hd0", "hd1",
    "http", "https", "ftp", "mailto",
}
_BIN_VOL_RE = re.compile(rb"([A-Za-z][A-Za-z0-9_.-]{1,20}):([A-Za-z0-9_./+-]{2,40})")
_TXT_ASSIGN_LINE_RE = re.compile(r"(?im)^\s*(?:c:)?assign\b[^\n]*")
_TXT_VOL_RE = re.compile(r'"?([A-Za-z][A-Za-z0-9_.-]{1,20}):"?')
_TXT_ASSIGN_PROSE_RE = re.compile(r'(?i)\bassign(?:ez)?\b[^:\n]{0,40}?"?([A-Za-z][A-Za-z0-9_.-]{1,20}):"?')


def _inferred_assigns(root):
    """Infer non-standard AmigaDOS volume assigns a demo in ``root`` expects
    (e.g. ``Hate2:PV.exe`` in a binary or ``assign CNCD:`` in a readme),
    mapped to ``Demo:``. Returns ``{vol: "Demo:"}`` (empty when none found)."""
    entries = {p.name.lower() for p in root.iterdir()} if root.is_dir() else set()
    vols = {}
    for p in sorted(_walk_files(root)):
        rel = p.relative_to(root).parts
        if any(part.lower() in _SYSTEM_DIRS | {"s"} for part in rel[:-1]):
            continue
        if p.suffix.lower() == ".info":
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0 or size > 2_000_000:
            continue
        data = p.read_bytes()
        if b"\0" not in data and size <= 32768:
            text = data.decode("latin-1", "replace")
            for m in _TXT_ASSIGN_LINE_RE.finditer(text):
                for vm in _TXT_VOL_RE.finditer(m.group(0)):
                    vol = vm.group(1)
                    if vol.lower() not in _STD_VOLS:
                        vols.setdefault(vol.lower(), vol)
            if p.suffix.lower() in _DOC_EXTS or "install" in p.name.lower():
                for m in _TXT_ASSIGN_PROSE_RE.finditer(text):
                    vol = m.group(1)
                    if vol.lower() not in _STD_VOLS:
                        vols.setdefault(vol.lower(), vol)
        else:
            for m in _BIN_VOL_RE.finditer(data):
                vol = m.group(1).decode("latin-1")
                if vol.lower() in _STD_VOLS:
                    continue
                target_first = m.group(2).decode("latin-1").split("/", 1)[0].lower()
                if target_first in entries:
                    vols.setdefault(vol.lower(), vol)
    if not vols or len(vols) > 8:
        return {}
    return {v: "Demo:" for _, v in sorted(vols.items())}


def _archive_root(root):
    """The top-level unpacked archive directory containing ``root`` (under
    ``work/media/<id>/x/<archive>``), or ``root`` itself."""
    cur = pathlib.Path(root)
    for parent in (cur, *cur.parents):
        if parent.parent.name == "x":
            return parent
    return cur


MERGED_NOTE = "set merged into one directory"
LAUNCH_NOTE = "patched disk 1 runs"


def _disk_names(v):
    return [os.path.basename(d) for d in v.disks]


def fits(v, said, first_kind):
    """Is ``v`` the variant an entry describes that says ``said`` of it
    (the ``boot``, ``disks`` and ``run`` it has)? What it says is so, and
    what it leaves out is as usual: the kind of the download's first
    variant, no set of disks, no file there was a choice of."""
    return (said.get("boot", first_kind) == v.kind
            and (said["disks"] == _disk_names(v) if "disks" in said
                 else len(v.disks) < 2)
            and (said["run"] == v.run if "run" in said else not v.choice))


def named(v, variants):
    """What an entry says of variant ``v``, of all the download offers
    (``variants``, ``v`` among them): its ``boot`` when that is not the
    kind of the first variant, its ``disks`` when it is a set, the file it
    ``run``s when the media left a choice. Where that fits another variant
    too, the file it starts is named all the same, or else its one disk."""
    first = variants[0].kind
    out = {}
    if v.kind != first:
        out["boot"] = v.kind
    if len(v.disks) > 1:
        out["disks"] = _disk_names(v)
    if v.choice:
        out["run"] = v.run
    if sum(fits(o, out, first) for o in variants) > 1:
        if v.run:
            out["run"] = v.run
        elif v.disks:
            out["disks"] = _disk_names(v)
    return out


def merged_variant(disks, prod_id, title, run=None):
    """A hard-drive variant holding the files of every disk of a set in one
    directory, with split archives joined and archives unpacked: what the
    set's installer, or its readme ("copy all files from the three disks to
    the same directory"), leaves on a hard drive. None when that holds no
    executable. ``run`` is the script or executable an entry names."""
    work = config.WORK / "media" / str(prod_id)
    # A directory per set: the variant of one outlives the making of another.
    root = work / "merged" / pathlib.Path(disks[0]).stem
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for i, d in enumerate(disks):
        adf = _as_adf(d, work)
        tree = adf and _unpack_disk(adf, work / "merged-disk" / str(i))
        if tree:
            shutil.copytree(tree, root, dirs_exist_ok=True)
    # Archives can hold split files and archives of their own (Flowers:
    # three LHAs holding the three parts of the executable).
    for _ in range(2):
        _join_split_parts(root)
        for p in list(_walk_files(root)):
            if sniff(p) == "archive" and unpack(p, p.parent) is None:
                p.unlink()
    # Booted from the directory of what runs, as _tree_variant does:
    # Kickstart 1.3 has no resident cd.
    script = _launch_script(root, title) if run is None \
        else _named_script(root, run)
    if script:
        rel = _rel(script, root)
        return _script_variant(script, run or rel,
                               f"{MERGED_NOTE}; runs script {rel}")
    exe, note = _pick_exe(root, title, run)
    if exe is None:
        return None
    rel = _rel(exe, root)
    return Variant("hd", [], root=str(exe.parent), command=f'"{exe.name}"\n',
                   note=f"{MERGED_NOTE}; runs {rel}" + (f" ({note})" if note else ""),
                   run=rel, choice=True)


def launch_variant(disks, prod_id, only_unbootable=False, run=None):
    """A floppy variant whose disk 1 is a patched copy that boots straight
    into the demo: a bootblock plus an s/startup-sequence running the
    executable a user would start. For sets whose first disk cannot boot
    (made for Workbench or installing) and for bootable disks that stop at
    a Workbench waiting for an icon to be opened. Booting from the disk
    keeps the demo's current directory right on every Kickstart (1.3 has no
    resident cd). None when disk 1 holds no DOS filesystem or executable,
    or is full (or boots, with ``only_unbootable``). ``run`` is the
    executable an entry names."""
    work = config.WORK / "media" / str(prod_id)
    adf = _as_adf(disks[0], work)
    if adf is None:
        return None
    data = adf.read_bytes()
    vol = volume_name(data)
    if vol is None or (only_unbootable and bootable(data)):
        return None
    box = work / "disk" / adf.stem
    tree = _unpack_disk(adf, box)
    if tree is None:
        return None
    exe, note = _pick_exe(tree, run=run)
    if exe is None:
        return None
    rel = _rel(exe, tree)
    patched = work / "launch" / f"{adf.stem}-launch.adf"
    patched.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(adf, patched)
    script = box / "startup-sequence"
    script.write_text(f'"{rel}"\n', encoding="latin-1")

    def xdf(*args, check=True):
        subprocess.run(["xdftool", str(patched), *args], capture_output=True,
                       timeout=60, check=check)

    try:
        xdf("makedir", "s", check=False)        # may already exist
        xdf("delete", "s/startup-sequence", check=False)
        xdf("write", str(script), "s/startup-sequence")
        xdf("boot", "install")
    except (OSError, subprocess.SubprocessError):
        return None                             # disk full
    why = "disk 1 not bootable" if not bootable(data) else "launched"
    return Variant("floppy", [str(patched)] + list(disks[1:]),
                   note=f"{why}; {LAUNCH_NOTE} {vol}:{rel}"
                        + (f" ({note})" if note else ""),
                   run=rel, choice=True)


TREE_NOTE = "files on a floppy"
OFS_BYTES = 1758 * 488   # payload of an OFS floppy, less root and bitmap


def floppy_variant(v, prod_id):
    """A floppy holding hard-drive variant ``v``'s files, booting into its
    command: for demos that load their files from DF0: rather than from
    the current directory (Hardcore asks for the disk in unit 0). None
    when the files do not fit."""
    root = pathlib.Path(v.root)
    if sum(p.stat().st_size for p in _walk_files(root)) > OFS_BYTES:
        return None
    # A box per tree, two of which may end in the same directory name.
    box = config.WORK / "media" / str(prod_id) / "fd" / \
        f"{root.name}-{hashlib.sha1(str(root).encode()).hexdigest()[:8]}"
    if box.exists():
        _rmtree(box)
    tree = box / "files"
    shutil.copytree(root, tree)
    workbench.prepare(tree, v.command)
    adf = box / "disk.adf"
    args = ["create", "+", "format", "Demo", "ofs"]
    for d, dirs, files in os.walk(tree):
        rel = pathlib.Path(d).relative_to(tree)
        args += [x for n in dirs for x in ("+", "makedir", str(rel / n))]
        args += [x for n in files
                 for x in ("+", "write", os.path.join(d, n), str(rel / n))]
    try:
        subprocess.run(["xdftool", str(adf), *args, "+", "boot", "install"],
                       capture_output=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError):
        return None                             # does not fit after all
    # Named by its boot alone, whatever choice the tree left.
    return Variant("floppy", [str(adf)], note=f"{TREE_NOTE}; {v.label}",
                   run=v.run)


def fallbacks(v, prod_id, title="", run=None):
    """Other ways to run variant ``v``, in the order a sweep tries them when
    it did not work: ``(kind, make)`` each, where ``make()`` gives a variant
    of that kind, or None. ``run`` is the file an entry says to start."""
    if v.kind == "hd":
        if v.command is None:
            return []
        out = []
        if v.root:
            root = pathlib.Path(v.root)
            tree = _archive_root(root)
            proj = _named_project(tree, run) if run \
                else _project_icon(tree, title)
            if proj is not None:
                out.append(("hd", lambda p=proj: p))
            script = _named_script(tree, run) if run \
                else _launch_script(tree, title)
            if script is not None and (proj is None or _rel(script, tree) != proj.run):
                rel = _rel(script, tree)
                out.append(("hd", lambda s=script, r=rel: _script_variant(
                    s, run or r, f"runs script {r}")))
            if not v.assign:
                inferred = _inferred_assigns(root)
                if inferred:
                    tag = "assign " + ", ".join(f"{k}:" for k in inferred)
                    out.append(("hd", lambda a=inferred, t=tag: dataclasses.replace(
                        v, assign=a,
                        note=f"{v.note}; {t}" if v.note else t)))
        # Files a demo loads from DF0: rather than from its directory.
        out.append(("floppy", lambda: floppy_variant(v, prod_id)))
        return out
    # A floppy set that never got going may be a Workbench disk: run its
    # demo directly instead. A set that still does not may be meant to be
    # installed: run it from one directory holding every disk.
    work = config.WORK / "media" / str(prod_id)
    out = [] if LAUNCH_NOTE in v.note else [
        ("floppy", lambda: (
            (m := launch_variant(v.disks, prod_id, run=run))
            and flag_ffs(m, work)))]
    if len(v.disks) > 1:
        out.append(("hd", lambda: merged_variant(v.disks, prod_id, title, run)))
    return out
