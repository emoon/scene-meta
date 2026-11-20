"""Screenshots of the productions Demozoo has none of, for uploading there
later. Each entry of the data files is played as written (see player); the
emulator keeps a picture every few seconds that differs from the last one
kept, and an even spread of the ones taken while the production was alive is
filed under ``<root>/<id>/``:

    <root>/<id>/01.png ...   what the emulator wrote, unscaled
    <root>/<id>/meta.json    where each came from, or why there are none

A production with a ``meta.json`` is done and is not played again. One that
could not be played (a missing ROM, no media) gets none: it is an error.
"""

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
from . import config, player, replay, verdict
from .machines import FPS

SCHEMA = 1
MAX_SHOTS = 12
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
    Returns the production's meta. Raises CannotPlay when something the
    run needs is missing."""
    with tempfile.TemporaryDirectory(prefix=f"shots-{prod}-", dir=out) as t:
        keep = pathlib.Path(t)
        ran = player.play(prod, entry, default, keep=keep)
        name, log, v = ran.machine, ran.log, ran.verdict
        if not v.works:
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
    """The report line of one production, its meta filed. Raises CannotPlay
    when it could not be played, and then nothing is filed."""
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
    """File the screenshots under ``out``. Returns how many productions
    could not be played."""
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
    return player.play_each([(p, found[p]) for p in prods],
                            lambda p, e: _one(p, e, default, out), jobs, log)
