"""Observe literal C64 playback. Never infer swaps, answers or retries."""

import pathlib
import shutil
import tempfile
import time

from ..core.errors import CannotPlay
from ..core.gate import Play, SwapTaken
from . import runner, swapwait, verdict, vice
from .keymap import NAMES as KEYS


def record(log, inserts, hz):
    """A swap needs stepper activity after insertion, before its replacement."""
    said = verdict.classify(log.samples, log.basic, log.crash, log.crash_cycles)
    if said.verdict == "error":
        raise CannotPlay(f"the emulator gave nothing: {said.crash}")
    swaps = []
    for i, (disk, at) in enumerate(inserts):
        until = inserts[i + 1][1] if i + 1 < len(inserts) else float("inf")
        samples = [s for s in log.samples if s.cycles <= until]
        # A stepper change is read activity; sensor and motor-only
        # presence polling cannot make a disk pass.
        before = [s for s in samples if s.cycles <= at]
        baseline = before[-1] if before else next(iter(samples), None)
        loaded = baseline is not None and any(
            at < s.cycles <= until and (s.drive ^ baseline.drive) & 0x03
            for s in samples)
        swaps.append(SwapTaken(disk, loaded))
    # Alive time excludes the BASIC cursor. More animation means more progress
    # even in a PRG that does no disk reads after a necessary key.
    return Play(said.verdict in ("works", "works-then-crash"), said.crash,
                tuple(swaps), said.alive / hz,
                None if said.ended_cycles is None else said.ended_cycles / hz)


def run(machine, variant, actions, seconds, seed):
    with tempfile.TemporaryDirectory(prefix="scenemeta-c64-play-") as temp:
        tmp = pathlib.Path(temp)
        disks = []
        for i, src in enumerate(variant.disks):
            dst = tmp / f"{i}{pathlib.Path(src).suffix.lower()}"
            shutil.copyfile(src, dst)
            disks.append(dst)
        log = runner.RunLog([], set(), [])
        inserts = []
        try:
            with vice.Vice(machine, disks[variant.boot_disk:], tmp,
                           vice.free_port(), variant.boot_file, seed=seed) as v:
                _drive(v, disks, actions, seconds, machine.hz, tmp, log, inserts)
        except vice.ViceError as error:
            logfile = tmp / "vice.log"
            log.crash, log.detail = runner.crash_cause(
                str(error), logfile.read_text(errors="replace") if logfile.exists() else "")
            log.crash_cycles = log.samples[-1].cycles if log.samples else 0
        # Include unperformed swaps after an early crash in the core record.
        swaps = [e["disk"] for e in actions if "disk" in e]
        got = record(log, inserts, machine.hz)
        return Play(got.ran, got.crash, got.swaps + tuple(
            SwapTaken(disk, False) for disk in swaps[len(inserts):]), got.far, got.end)


def _drive(v, disks, actions, seconds, hz, tmp, log, inserts):
    end = round(seconds * hz)
    deadline = time.monotonic() + 120 + end / runner.CYCLES_PER_WALL_SECOND
    pending = iter(actions)
    event = next(pending, None)
    while True:
        now, _ = v.stop()
        while event is not None and round(event["at"] * hz) <= now:
            if "disk" in event:
                # Event time is when the disk goes in. Open the drive gap
                # before that time, below, rather than shifting the schedule.
                v.cmd(f'attach "{disks[event["disk"] - 1]}" 8')
                inserts.append((event["disk"], now))
            else:
                v.press(KEYS[event["key"]])
            event = next(pending, None)
            now, _ = v.stop()
        if now >= end:
            return
        if time.monotonic() > deadline:
            raise vice.ViceError("wall-clock budget exceeded (timeout)")
        target = min(end, now + hz)
        if event is not None:
            at = round(event["at"] * hz)
            if "disk" in event and now >= at - vice.GAP_CYCLES:
                v.cmd("detach 8")
                v.run_until(at, step=0.005)
                continue
            if "disk" in event:
                target = min(target, max(now, at - vice.GAP_CYCLES))
            else:
                target = min(target, at)
        v.run_until(target, step=0.005)
        runner.observe(v, tmp / "shot.png", log, v.stop())
