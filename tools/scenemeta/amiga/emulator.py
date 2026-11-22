"""Boot one variant on one machine headless and collect what happened.

Drives the patched Amiberry's batch ``--dbg`` protocol (amiberry/SNAPSHOT.md):
every ``interval`` frames a ``status`` and a screenshot, with the swap-wait
detector inserting the next disk on its own when the demo asks for it.
"""

import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

from . import alertshot, config, machines, workbench

# Idle trigger for "press mouse button / insert disk" prompts that never touch
# the drive (seconds without disk activity with the head parked).
AUTOSWAP_IDLE_SECONDS = 30
# Frames to keep running once the last disk is in, then stop the batch early:
# enough to see the last part play, without running out the whole budget.
AUTOSWAP_TAIL_FRAMES = 15000
# A run where nothing happens this long (no display change, audio or disk
# DMA) has crashed or frozen: stop it instead of running out the budget.
# Not for scheduled-swap runs, whose inserts can come later than that.
DEAD_FRAMES = 6000
# A scheduled swap is repeated (re-insert + click) this many times, this far
# apart: the demo may only show its prompt, and wait for a disk change, after
# the first insert.
SCHEDULE_PULSES = 6
SCHEDULE_PULSE_FRAMES = 1500
# The keys a run can press, by their names in the data files, as the input
# command takes them: a mouse button is clicked; a key (its rawkey code, in
# decimal) or the fire button of a port (the Amiga's port 1 is port 0) is
# held a few frames so a poll sees it.
KEYS = {"lmb": "mouse click 0", "rmb": "mouse click 1",
        "return": "key 68", "space": "key 64",
        "p1fire": "joy 0 fire", "p2fire": "joy 1 fire"}
KEY_HOLD_FRAMES = 3
# What a key retry presses, one per nudge in turn.
NUDGE_KEYS = ("return", "space", "p2fire")


@dataclasses.dataclass
class Sample:
    frame: int
    pc: int
    dmacon: int
    bplcon0: int
    resets: int
    df0: str
    shot: str       # md5 of the screenshot PNG ("" when missing)
    alert: int = None  # exec's LastAlert when exec is still in place
    last_dma: int = -1  # frame of the last disk DMA start so far
    box: str = ""  # what alertshot sees on screen: guru | task-held | ""
    # Head cylinder of each drive (runs that ask for "disk status" only).
    cyls: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class RunLog:
    samples: list
    events: list            # emulator events: halt, autoswap, swap-poll, ...
    returncode: int
    timed_out: bool
    stderr_tail: str
    last_shot: bytes = b""  # PNG of the final screenshot
    # Highest cylinder each drive was seen at with its motor on, sampled at
    # the status points (multi-drive runs only): shows a disk was read.
    max_cyl: list = dataclasses.field(default_factory=list)


MAX_DRIVES = 4

# Amiberry seeds its RNG from the wall clock (the second the run started):
# the CPU's start delay and the floppy rotation phase then differ run to run,
# and a loader that races (5316) works or stalls by luck. Runs pin the seed;
# a retry with another seed is a different, reproducible roll of the dice.
DEFAULT_SEED = 1

# A tool the startup-sequence runs first on a machine whose FPU is off: in
# Supervisor() it clears the 68060 PCR's disable-FPU bit, the part of
# 68060.library a demo cannot do without (else every FPU instruction is a
# line-F Guru, 8000000B).
FPU_ON = "r2-fpu-on"
FPU_ON_EXE = bytes.fromhex(
    "000003f3 00000000 00000001 00000000 00000000 00000008"
    "000003e9 00000008"
    "2c780004 4bfa000a 4eaeffe2 7000 4e75"  # move.l 4.w,a6; lea 16(pc),a5;
                                            # jsr Supervisor(a6); moveq #0,d0; rts
    "4e7a0808 08800001 4e7b0808 4e73 4e71"  # movec pcr,d0; bclr #1,d0;
                                            # movec d0,pcr; rte; nop
    "000003f2")


def _uae_config(machine, variant, tmp, drives=1, seed=DEFAULT_SEED):
    """The .uae text and the swap list. With ``drives`` > 1 the first disks
    of a set sit in DF0..DF<drives-1> from boot, as on a multi-drive Amiga."""
    lines = [machines.uae_text(machine),
             f"kickstart_rom_file={machines.rom_path(machine)}\n",
             f"rndseed={seed}\n"]
    swaps = []
    if variant.kind == "floppy":
        # The emulator writes floppy changes back to the image: use copies.
        copies = []
        for i, d in enumerate(variant.disks):
            dst = tmp / "df" / f"{i}-{os.path.basename(d)}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(d, dst)
            copies.append(dst)
        drives = max(1, min(drives, MAX_DRIVES, len(copies)))
        # Write-protected, as a demo disk sat in the drive: some loaders
        # read nothing from a writable disk (Spinotic checks
        # TD_PROTSTATUS and falls through to a Guru).
        lines.append("floppy_write_protect=true\n")
        lines.append(f"nr_floppies={drives}\n")
        for i in range(drives):
            lines.append(f"floppy{i}={copies[i]}\n")
        swaps = copies[drives:]
    else:
        lines.append("nr_floppies=0\n")
    if variant.kind == "hd":
        root = tmp / "hd"
        shutil.copytree(variant.root, root, symlinks=False)
        if variant.command is not None:
            command = variant.command
            if machine.fpu_off:
                (root / FPU_ON).write_bytes(FPU_ON_EXE)
                command = f"{FPU_ON}\n{command}"
            workbench.prepare(root, command)
        lines.append(f"filesystem2=rw,DH0:Demo:{root},0\n")
    return "".join(lines), swaps


LAST_ALERT = 0x202   # ExecBase->LastAlert
NO_ALERT = 0xFFFFFFFF
_execbase_cache = {}


def execbase(machine, kind="floppy"):
    """Where this machine's Kickstart puts ExecBase. Fixed for a given ROM and
    memory layout, so it is measured once by booting with no demo. The boot
    media matter: with Z3 fast RAM, KS3.0 puts it $20 higher when the
    hard drive is mounted."""
    key = (machine.name, kind == "hd")
    if key not in _execbase_cache:
        with tempfile.TemporaryDirectory(prefix="scenemeta-eb-") as t:
            tmp = pathlib.Path(t)
            media = "nr_floppies=1\n"
            if kind == "hd":
                (tmp / "hd").mkdir()
                media = f"nr_floppies=0\nfilesystem2=rw,DH0:Demo:{tmp / 'hd'},0\n"
            cfg = tmp / "machine.uae"
            cfg.write_text(machines.uae_text(machine)
                           + f"kickstart_rom_file={machines.rom_path(machine)}\n"
                           + media)
            out = _invoke([str(config.AMIBERRY), "-f", str(cfg),
                           "--dbg", "warp on", "--dbg", "run frames=300",
                           "--dbg", "peek 4 4"], tmp, 120)[0]
            hexval = next((r["result"].get("hex", "") for r in _records(out)
                           if r.get("cmd") == "peek 4 4"), "")
            _execbase_cache[key] = int(hexval[:8], 16)
    return _execbase_cache[key]


@dataclasses.dataclass(frozen=True)
class Options:
    """How a run is driven: what is mounted, pressed and swapped, and when.

    ``triggers`` arms riskier swap triggers on top of the default ones:
    "reread" (Iso re-reads one track while it waits) and "anycyl" (the idle
    trigger wherever the head is parked; Soul Kitchen's prompt leaves it
    mid-disk). Both can fire in a quiet or looping stretch mid-demo, so they
    are retries, not the default. "rampolls" ignores disk-change polls made
    from Kickstart ROM: the OS's own trackdisk polling, which looks like a
    wait while a DOS-loaded demo plays from RAM.

    ``drives`` mounts that many disks of the set at boot (DF0..), for demos
    that want disk 2 in an external drive. ``unit`` is the drive the rest
    of the set is swapped into (Soho: disks 2 and 3 both go in DF1); the
    inserts of ``play`` name their own.

    ``click_every`` presses the left mouse button every that many frames,
    for "click to continue" screens (right clicks too would leave some
    demos' parts early: RAF's Megademo). ``max_clicks`` stops them after
    that many: an intro that waits for a click to start may quit on the
    next one (Nice).

    ``key_every`` presses Return, Space and fire in turn that often, for
    screens that wait for a key (Megademo 2's credits take Return only).

    ``schedule`` swaps disks at fixed frames instead of on detection: at
    each frame the next disk goes in, then is re-inserted SCHEDULE_PULSES
    times SCHEDULE_PULSE_FRAMES apart, each insert followed by a click one
    sample later (left and right in turn). The detector is off for such a
    run, and with ``detect=False``: a run that only shows where the demo
    stops reading.

    ``play`` does fixed things at exact frames and nothing else, the
    detector off: ``(frame, "insert", (k, unit))`` puts disk ``k`` of the
    swap list in drive ``unit``, ``(frame, "press", key)`` presses a key of
    KEYS.

    ``keep`` is a directory that gets a ``NNNN.png`` of each sample (``NNNN``
    its index) whose picture differs from the last one kept in more than
    ``keep_permille`` of every thousand pixels: the emulator does the
    comparing, so the run's samples still say which of them were kept.
    """
    triggers: str = ""
    drives: int = 1
    click_every: int = 0
    schedule: tuple = ()
    unit: int = 0
    detect: bool = True
    max_clicks: int = 0
    key_every: int = 0
    seed: int = DEFAULT_SEED
    play: tuple = ()
    keep: pathlib.Path = None
    keep_permille: int = 20

    @property
    def detects(self):
        """Is the swap-wait detector on for this run?"""
        return bool(self.detect and not self.schedule and not self.play)


def run(machine, variant, frames, opts=Options(), interval=250, timeout=None):
    """Run ``variant`` on ``machine`` for ``frames`` frames, sampling every
    ``interval``. Returns a RunLog. Raises errors.CannotPlay, before
    anything is started, when the machine's ROM is missing."""
    machines.require_rom(machine)
    # Warp runs well ahead of real time; slower than that means stuck, but
    # leave room for a loaded box (retries run several emulators at once).
    timeout = timeout or 60 + frames // 50
    eb = execbase(machine, variant.kind)
    alert_peek = f"peek {eb + LAST_ALERT:x} 4"
    with tempfile.TemporaryDirectory(prefix="scenemeta-") as t:
        tmp = pathlib.Path(t)
        text, swaps = _uae_config(machine, variant, tmp, opts.drives,
                                  opts.seed)
        cfg = tmp / "machine.uae"
        cfg.write_text(text)
        shots = tmp / "shots"
        shots.mkdir()

        script = _play if opts.play else _script
        cmds = ["warp on", _autoswap(opts)]
        cmds += script(frames, interval, alert_peek, shots, swaps, opts)
        argv = [str(config.AMIBERRY), "-f", str(cfg)]
        argv += [f"-diskswapper={d}" for d in swaps]
        for c in cmds:
            argv += ["--dbg", c]
        ran = _invoke(argv, tmp, timeout)
        # Swap-list path -> 1-based disk number of the set.
        first_swap = len(variant.disks) - len(swaps) + 1
        names = {str(d): first_swap + i for i, d in enumerate(swaps)}
        return _parse(ran, shots, names, eb, alert_peek)


def _autoswap(opts):
    """The command that sets the swap-wait detector up for a run. It is
    armed even with one disk: its "exhausted" event is how a demo that asks
    for a disk we do not have shows up."""
    if not opts.detects:
        return "disk autoswap off"
    cmd = (f"disk autoswap click idle={AUTOSWAP_IDLE_SECONDS}"
           f" tail={AUTOSWAP_TAIL_FRAMES} dead={DEAD_FRAMES}")
    if opts.unit:
        cmd += f" unit={opts.unit}"
    return f"{cmd} {opts.triggers}".strip()


def _script(frames, interval, alert_peek, shots, swaps, opts):
    """The batch commands of a run: per sample interval a status and a
    screenshot, plus the scheduled inserts and the input nudges."""
    cmds, held = [], 0
    for i, (key, _, inserts) in enumerate(_inputs(frames, interval, opts)):
        cmds += [f"run frames={interval - held}"] + _sample(
            i, alert_peek, shots, opts.drives > 1, opts)
        press, held = _press(key) if key else ([], 0)
        cmds += press + [f"disk insert {opts.unit} {swaps[k]}"
                         for k in inserts if k < len(swaps)]
    return cmds


def _inputs(frames, interval, opts):
    """What such a run does after each of its samples: ``(key, k, inserts)``,
    the key it presses or None, the disk of the swap list a scheduled
    insert's click follows (None of a nudge), and the disks it puts in."""
    # (frame, swap list index): each scheduled disk goes in, then the
    # pulses re-insert it.
    pending = []
    for k, f in enumerate(sorted(opts.schedule)):
        pending += [(f + p * SCHEDULE_PULSE_FRAMES, k)
                    for p in range(SCHEDULE_PULSES + 1)]
    pending.sort(key=lambda x: x[0])
    put_in, clicks, periodic, keys = None, 0, 0, 0   # put_in: at the last sample
    for i in range(max(1, frames // interval)):
        frame = (i + 1) * interval
        key, k = None, None
        if put_in is not None:
            # After a scheduled insert: left and right in turn (Lethal
            # Dose 2 takes its disk on the right button only).
            key, k = ("lmb", "rmb")[clicks % 2], put_in
            clicks += 1
        elif opts.click_every and frame % opts.click_every == 0 \
                and not (opts.max_clicks and periodic >= opts.max_clicks):
            key = "lmb"
            periodic += 1
        elif opts.key_every and frame % opts.key_every == 0:
            key = NUDGE_KEYS[keys % len(NUDGE_KEYS)]
            keys += 1
        inserts = []
        while pending and frame >= pending[0][0]:
            inserts.append(pending.pop(0)[1])
        put_in = inserts[-1] if inserts else None
        yield key, k, inserts


def pressed(frames, opts, interval=250):
    """``(frame, key, k)`` of each press a run with no ``play`` makes of
    itself (not the detector's click): ``k`` as in ``_inputs``."""
    return [((i + 1) * interval, key, k) for i, (key, k, _) in enumerate(
        _inputs(frames, interval, opts)) if key]


def _play(frames, interval, alert_peek, shots, swaps, opts):
    """The batch commands of a run that does ``opts.play`` at its frames: a
    sample every ``interval`` as in any run, the frames between split
    where an action falls."""
    pending = sorted(opts.play)
    cmds, at = [], 0
    for i in range(max(1, frames // interval)):
        end = (i + 1) * interval
        while pending and pending[0][0] <= end:
            frame, what, arg = pending.pop(0)
            if frame > at:
                cmds.append(f"run frames={frame - at}")
                at = frame
            if what == "insert":
                k, unit = arg
                cmds.append(f"disk insert {unit} {swaps[k]}")
            else:
                press, held = _press(arg)
                cmds += press
                at += held
        if end > at:
            cmds.append(f"run frames={end - at}")
            at = end
        cmds += _sample(i, alert_peek, shots, True, opts)
    return cmds


def _sample(i, alert_peek, shots, disk_status, opts):
    """The commands that record sample ``i`` of a run."""
    cmds = ["status", "peek 4 4", alert_peek,
            f"screenshot {shots / f'{i:04d}.png'}", "disk autoswap status"]
    if opts.keep:
        cmds.append(f"shot-new {opts.keep_permille} {opts.keep / f'{i:04d}.png'}")
    return cmds + ["disk status"] if disk_status else cmds


def _press(key):
    """``(commands, frames)``: what presses ``key`` of KEYS, and the frames
    the run goes on while it is held."""
    what = KEYS[key]
    if what.startswith("mouse"):
        return [f"input {what}"], 0
    return [f"input {what} down", f"run frames={KEY_HOLD_FRAMES}",
            f"input {what} up"], KEY_HOLD_FRAMES


def _invoke(argv, tmp, timeout):
    env = dict(os.environ)
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        env[k] = str(tmp / "xdg")
    # The real SDL video driver aborts when many instances start at once;
    # dummy video still renders screenshots. Audio stays real: a dummy audio
    # driver changes emulation timing.
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    try:
        proc = subprocess.run(argv, env=env, cwd=tmp, capture_output=True,
                              text=True, timeout=timeout)
        return proc.stdout, proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as e:
        return _text(e.stdout), _text(e.stderr), -9, True


def _records(stdout):
    for line in stdout.splitlines():
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _text(b):
    if b is None:
        return ""
    return b.decode(errors="replace") if isinstance(b, bytes) else b


class _Reader:
    """Builds a run's samples and events from the emulator's records."""

    def __init__(self, shots, names, eb, alert_peek):
        self.samples, self.events = [], []
        self.max_cyl = [-1] * MAX_DRIVES
        self._shots, self._names, self._eb = shots, names, eb
        self._eb_ok = False
        self._box_cache = {}
        self._commands = {"status": self._status,
                          "disk autoswap status": self._last_dma,
                          "disk status": self._disk_status,
                          "peek 4 4": self._execbase,
                          alert_peek: self._alert}

    def read(self, rec):
        if "event" in rec:
            if "inserted" in rec:
                rec["disk"] = self._names.get(rec["inserted"])
            self.events.append(rec)
            return
        cmd, res = rec.get("cmd") or "", rec.get("result") or {}
        if cmd.startswith("disk insert"):
            self._inserted(res)
        elif cmd in self._commands:
            self._commands[cmd](res)

    def _status(self, res):
        if not res:
            return
        png = self._shots / f"{len(self.samples):04d}.png"
        shot = hashlib.md5(png.read_bytes()).hexdigest() if png.exists() else ""
        self.samples.append(Sample(res["frame"], int(res["pc"], 16),
                                   res["dmacon"], res["bplcon0"],
                                   res.get("resets", 0),
                                   os.path.basename(res.get("df0", "")), shot,
                                   box=_box(png, shot, self._box_cache)))

    def _last_dma(self, res):
        if self.samples:
            self.samples[-1].last_dma = res.get("last_dma", -1)

    def _inserted(self, res):
        if res.get("ok"):
            self.events.append({
                "event": "scheduled-swap",
                "frame": self.samples[-1].frame if self.samples else 0,
                "inserted": res.get("inserted"),
                "disk": self._names.get(res.get("inserted"))})

    def _disk_status(self, res):
        units = res.get("units", [])
        if self.samples:
            self.samples[-1].cyls = [d.get("cyl", -1) for d in units]
        for u, d in enumerate(units[:MAX_DRIVES]):
            if d.get("motor"):
                self.max_cyl[u] = max(self.max_cyl[u], d.get("cyl", -1))

    def _execbase(self, res):
        self._eb_ok = _peek_long(res) == self._eb

    def _alert(self, res):
        # Only trusted while $4 still points at the ExecBase the ROM
        # built; a demo that took the machine over owns that memory.
        if self.samples and self._eb_ok:
            self.samples[-1].alert = _peek_long(res)


def _parse(ran, shots, names, eb, alert_peek):
    """The RunLog of a finished run. ``ran`` is what _invoke returned,
    ``names`` the disk number of each swap-list path."""
    stdout, stderr, rc, timed_out = ran
    reader = _Reader(shots, names, eb, alert_peek)
    for rec in _records(stdout):
        reader.read(rec)
    pngs = sorted(shots.glob("*.png"))
    last = pngs[-1].read_bytes() if pngs else b""
    return RunLog(reader.samples, reader.events, rc, timed_out, stderr[-600:],
                  last, reader.max_cyl)


# An alert box is mostly black: its PNG is a few KB, a demo's screen is not.
BOX_MAX_PNG = 20000


def _box(png, shot, cache):
    """Is the screenshot a Guru Meditation or a task-held requester? Decoded
    once per distinct screen (the Guru blinks between two), and only the
    small PNGs."""
    if shot not in cache:
        data = png.read_bytes() if png.exists() else b""
        cache[shot] = (alertshot.box(data)
                       if 0 < len(data) <= BOX_MAX_PNG else "")
    return cache[shot]


def _peek_long(res):
    h = res.get("hex") or ""
    return int(h[:8], 16) if len(h) >= 8 else None
