"""Screenshots of the productions Demozoo has none of, for uploading there
later. Each entry of the data files is played as written (see replay); the
emulator keeps a picture every few seconds that differs from the last one
kept, and an even spread of the ones taken while the production was alive is
filed under ``<root>/<id>/``:

    <root>/<id>/01.png ...   what the emulator wrote, unscaled
    <root>/<id>/meta.json    where each came from, or why there are none

A production with a ``meta.json`` is done and is not played again.
"""

import concurrent.futures as cf
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import struct
import tempfile

from ..core import catalog as demozoo
from ..core.export import default_machine
from . import config, emulator, machines, replay, verdict
from .errors import CannotPlay
from .machines import FPS

SCHEMA = 1
MAX_SHOTS = 12
# A production that does not end in a set of disks plays this long.
SINGLE_DISK_FRAMES = 9000
ROM_END = 0x1000000  # the 24-bit address space ends here
AUDIO_DMA = 0xF     # Paula's four channels in DMACON
META = "meta.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def spread(items, n):
    """At most ``n`` of ``items``, evenly spaced, first and last included."""
    if len(items) <= n:
        return list(items)
    return [items[i * (len(items) - 1) // (n - 1)] for i in range(n)]


def png_size(path):
    """``(width, height)`` of a PNG, from its header."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != PNG_SIGNATURE:
        raise ValueError(f"{path}: not a PNG")
    return struct.unpack(">II", head[16:24])


def in_rom(sample):
    """Is the CPU in the Kickstart? (Fast RAM sits above it on the A1200s.)"""
    return verdict.ROM_START <= sample.pc < ROM_END


def running(samples):
    """How many of the leading ``samples`` are the production: the trailing
    run with the CPU in the Kickstart and no sound is the CLI after the
    production exited. A run that never left the ROM (a demo that waits in
    exec) has no such tail."""
    n = len(samples)
    while n and in_rom(samples[n - 1]) \
            and not samples[n - 1].dmacon & AUDIO_DMA:
        n -= 1
    return n if not all(in_rom(s) for s in samples[:n]) else len(samples)


def chosen(samples, alive, kept, n=MAX_SHOTS):
    """``[(sample index, frame)]`` of up to ``n`` kept pictures of the samples
    where the production was alive. ``kept`` is the set of sample indexes the
    emulator kept a picture of."""
    pool = [(i, s.frame) for i, (s, ok) in
            enumerate(zip(samples[:running(samples)], alive)) if ok and i in kept]
    return spread(pool, n)


def frames_of(entry):
    """How long to play ``entry``: until its last disk has loaded, else the
    time a production on one disk gets."""
    acts = replay.actions(entry)
    return acts[-1][0] + replay.TAIL_FRAMES if acts else SINGLE_DISK_FRAMES


def entry_digest(entry):
    """A short name for the entry as written, to tell later which entry the
    pictures were made from."""
    return hashlib.sha1(json.dumps(entry, sort_keys=True, default=str)
                        .encode()).hexdigest()[:12]


def meta(prod, entry, machine, shots, status, reason=""):
    """The ``meta.json`` of a production. ``shots`` is ``[(file, frame,
    (width, height))]``."""
    return {"schema": SCHEMA, "id": prod, "status": status, "reason": reason,
            "source": "entry", "entry": entry_digest(entry), "machine": machine,
            "captured": datetime.date.today().isoformat(),
            "shots": [{"file": f, "frame": frame, "seconds": round(frame / FPS, 1),
                       "width": w, "height": h}
                      for f, frame, (w, h) in shots]}


def capture(prod, entry, default, out):
    """Play ``entry`` and file what the emulator kept under ``out/<prod>``.
    Returns the production's meta."""
    name = entry.get("machine", default)
    try:
        machine = machines.BY_NAME[name]
        variant = replay.variant_of(prod, entry)
        acts = replay.actions(entry)
    except CannotPlay as e:
        return meta(prod, entry, name, [], "none", f"cannot replay: {e}")
    frames = frames_of(entry)
    with tempfile.TemporaryDirectory(prefix=f"shots-{prod}-", dir=out) as t:
        keep = pathlib.Path(t)
        log = emulator.run(machine, variant, frames, emulator.Options(
            drives=entry.get("drives", 1), play=tuple(acts), detect=False,
            keep=keep))
        v = verdict.classify(log, frames // 250)
        if v.verdict != "works":
            return meta(prod, entry, name, [], "none", f"did not run: {v.verdict}")
        kept = {int(p.stem) for p in keep.glob("*.png")}
        picked = chosen(log.samples, verdict.alive_flags(log.samples), kept)
        if not picked:
            return meta(prod, entry, name, [], "none", "no picture worth keeping")
        dest = out / str(prod)
        dest.mkdir(exist_ok=True)
        shots = []
        for n, (i, frame) in enumerate(picked, 1):
            target = dest / f"{n:02d}.png"
            shutil.copyfile(keep / f"{i:04d}.png", target)
            shots.append((target.name, frame, png_size(target)))
    return meta(prod, entry, name, shots, "shots")


def _one(prod, entry, default, out):
    result = capture(prod, entry, default, out)
    dest = out / str(prod)
    dest.mkdir(exist_ok=True)
    (dest / META).write_text(json.dumps(result, indent=1) + "\n")
    return f"{prod} {entry['title']}: {result['status']}" + \
        (f" ({len(result['shots'])})" if result["shots"] else f" ({result['reason']})")


def todo(found, wanted, without, done):
    """The ids to play: ``wanted`` (or all with an entry) that have no
    screenshot on Demozoo unless named, and no ``meta.json`` yet."""
    ids = set(wanted) if wanted else without & set(found)
    return sorted(p for p in ids if p in found and p not in done)


def run(out, ids=None, data=None, jobs=None, log=print):
    out = pathlib.Path(out)
    if not out.is_dir():
        raise SystemExit(f"{out}: no such directory (is the share mounted?)")
    data = data or config.DATA_DIR
    found = replay.all_entries(data)
    done = {int(p.parent.name) for p in out.glob(f"*/{META}")}
    for p in sorted(set(ids or ()) - set(found)):
        log(f"{p}: no entry in the data files")
    default = default_machine(data)
    prods = todo(found, ids, demozoo.ids_without_screenshots(), done)
    jobs = jobs or max(1, (os.cpu_count() or 4) // 2)
    with cf.ThreadPoolExecutor(jobs) as pool:
        for line in pool.map(lambda p: _one(p, found[p], default, out), prods):
            log(line, flush=True)
