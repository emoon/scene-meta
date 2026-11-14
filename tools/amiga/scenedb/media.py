"""Turn a production's NAS files into bootable variants.

A variant is either a set of floppy images (booted from DF0, later disks on
the swap list) or a directory booted as a hard drive whose startup-sequence
runs one executable. A disk set whose first disk cannot boot (made to be
started from Workbench) gets a patched copy of disk 1 that boots into the
demo. Archives are unpacked under WORK; NAS files are read only.
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

from . import config, diskset, workbench

HUNK_MAGIC = b"\x00\x00\x03\xf3"
ARCHIVE_EXTS = (".zip", ".lha", ".lzh", ".lzx")
MAX_VARIANTS = 3
# Extensions of files that are loaded, not started, even with a hunk header.
_DATA_EXTS = {".dat", ".data", ".bin", ".ovl"}
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
        return "exe"
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


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def variants(prod_id, title=""):
    """``(variants, problems)`` for one production. Problems are short
    reason strings for files that produced nothing. ``title`` picks the
    executable named after the production in an unpacked archive."""
    src = config.prod_dir(prod_id)
    if not src.is_dir():
        return [], ["no-files-on-nas"]
    work = config.WORK / "media" / str(prod_id)
    problems, disks, exes, trees = [], {}, [], []

    def take(path, depth, parts=()):
        kind = sniff(path)
        if kind == "disk":
            bad = image_problem(path)
            if bad:
                problems.append(f"{path.name}: {bad}")
                return
            disks.setdefault(path.name, (_sha1(path), path))
        elif kind == "exe":
            exes.append(path)
        elif kind == "archive" and depth < 2:
            out = work / "x" / f"{depth}-{path.name}"
            if out.exists():
                _rmtree(out)
            for a in (path, *parts):
                err = unpack_into(a, out)
                if err:
                    problems.append(f"{a.name}: {err}")
                    return
            trees.append(out)
            for f in sorted(_walk_files(out)):
                if sniff(f) != "exe":
                    take(f, depth + 1)

    files = [f for f in sorted(src.iterdir())
             if f.is_file() and not f.name.endswith(".part")]
    # A release split over numbered archives (pwl-rpg1.lha .. pwl-rpg3.lha)
    # unpacks into one tree: the first holds the demo, the others its data.
    parts = {}
    for group in diskset.group([f.name for f in files if sniff(f) == "archive"]):
        parts[group[0]] = [src / n for n in group[1:]]
        parts.update((n, None) for n in group[1:])
    for f in files:
        if parts.get(f.name, ()) is not None:
            take(f, 0, parts.get(f.name, ()))

    # Group by name first, then drop byte-identical repeats: the same disk is
    # often mirrored under two names (Oxygene-ControlA = control1), and only
    # one of them may belong to a complete set.
    out, seen = [], set()
    for group in diskset.group(list(disks)):
        shas = tuple(disks[n][0] for n in group)
        if shas in seen or (len(group) == 1 and any(shas[0] in s for s in seen)):
            continue
        seen.add(shas)
        paths = [str(disks[n][1]) for n in group]
        joined = _join_dms_parts(paths, work)
        if joined:
            paths = [joined]
        out.append(flag_ffs(launch_variant(paths, prod_id, only_unbootable=True)
                            or Variant("floppy", paths), work))

    for tree in trees:
        v = _tree_variant(tree, title)
        if v:
            out.append(v)
    for exe in exes:
        out.append(_exe_variant(exe, work))
    if not out and not problems:
        problems.append("no-bootable-media")
    return out[:MAX_VARIANTS], problems


def _tree_variant(tree, title=""):
    """A hard-drive variant for an unpacked archive, or None when it holds no
    executable of its own (disk-image-only archives)."""
    boot = next((p.parent.parent for p in _walk_files(tree)
                 if p.name.lower() == "startup-sequence"
                 and p.parent.name.lower() == "s"), None)
    exe, note = _pick_exe(tree, title)
    if exe is None:
        if boot is not None:
            return Variant("hd", [], root=str(boot), command=None,
                           note="own startup-sequence")
        return None
    return Variant("hd", [], root=str(exe.parent),
                   command=f'"{exe.name}"\n', note=note)


def _norm(name):
    return "".join(c for c in name.lower() if c.isalnum())


def _pick_exe(tree, title=""):
    """The executable a user would start in an unpacked tree, plus a note
    when there was a choice: ``(path | None, note)``."""
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
    # Shallowest first, then one named after the production, then one with
    # an icon (what a user double-clicks), then one not named like data (an
    # overlay the loader reads: Hardcore's hc.2xy-ko.dat beside the
    # hc.1ph-pip.exe that loads it), then the biggest.
    cands.sort(key=lambda p: (len(p.relative_to(tree).parts),
                              not _named_after(p.stem, title),
                              not p.with_name(p.name + ".info").exists(),
                              p.suffix.lower() in _DATA_EXTS,
                              -p.stat().st_size))
    exe = cands[0]
    note = f"{len(cands)} executables, picked {exe.name}" if len(cands) > 1 else ""
    return exe, note


def _exe_variant(exe, work):
    root = work / "exe" / exe.name
    root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exe, root / exe.name)
    return Variant("hd", [], root=str(root), command=f'"{exe.name}"\n')


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
    em1.exe, em2.exe, em3.exe; Stag: intro.exe then stag.ht), or None. A
    small text file outside the system directories, not an installer, with
    a line naming an executable beside it. One named after the production
    or with an icon wins."""
    cands = []
    for p in _walk_files(tree):
        rel = p.relative_to(tree).parts
        if any(part.lower() in _SYSTEM_DIRS | {"s"} for part in rel[:-1]) \
                or "install" in p.name.lower() or p.suffix.lower() == ".info" \
                or p.stat().st_size > 16384:
            continue
        data = p.read_bytes()
        if not data or data[:4] == HUNK_MAGIC or b"\0" in data:
            continue
        exes = {q.name.lower() for q in p.parent.iterdir()
                if q.is_file() and sniff(q) == "exe"}
        lines = data.decode("latin-1").splitlines()
        if any(ln.split()[0].strip('"').lower() in exes
               for ln in lines if ln.strip() and not ln.startswith(";")):
            cands.append(p)
    cands.sort(key=lambda p: (not _named_after(p.name, title),
                              not p.with_name(p.name + ".info").exists()))
    return cands[0] if cands else None


MERGED_NOTE = "set merged into one directory"
LAUNCH_NOTE = "patched disk 1 runs"


def merged_variant(disks, prod_id, title):
    """A hard-drive variant holding the files of every disk of a set in one
    directory, with split archives joined and archives unpacked: what the
    set's installer, or its readme ("copy all files from the three disks to
    the same directory"), leaves on a hard drive. None when that holds no
    executable."""
    work = config.WORK / "media" / str(prod_id)
    root = work / "merged"
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
    script = _launch_script(root, title)
    if script:
        rel = "/".join(script.relative_to(root).parts)
        return Variant("hd", [], root=str(script.parent),
                       command=script.read_text("latin-1"),
                       note=f"{MERGED_NOTE}; runs script {rel}")
    exe, note = _pick_exe(root, title)
    if exe is None:
        return None
    rel = "/".join(exe.relative_to(root).parts)
    return Variant("hd", [], root=str(exe.parent), command=f'"{exe.name}"\n',
                   note=f"{MERGED_NOTE}; runs {rel}" + (f" ({note})" if note else ""))


def launch_variant(disks, prod_id, only_unbootable=False):
    """A floppy variant whose disk 1 is a patched copy that boots straight
    into the demo: a bootblock plus an s/startup-sequence running the
    executable a user would start. For sets whose first disk cannot boot
    (made for Workbench or installing) and for bootable disks that stop at
    a Workbench waiting for an icon to be opened. Booting from the disk
    keeps the demo's current directory right on every Kickstart (1.3 has no
    resident cd). None when disk 1 holds no DOS filesystem or executable,
    or is full (or boots, with ``only_unbootable``)."""
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
    exe, note = _pick_exe(tree)
    if exe is None:
        return None
    rel = "/".join(exe.relative_to(tree).parts)
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
                        + (f" ({note})" if note else ""))


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
    box = config.WORK / "media" / str(prod_id) / "fd" / root.name
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
    return Variant("floppy", [str(adf)], note=f"{TREE_NOTE}; {v.label}")
