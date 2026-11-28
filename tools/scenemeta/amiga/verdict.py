"""Classify one run from its samples: did the demo work on this machine?

A sample is *alive* when audio DMA is on, or the screen changed since the
previous sample and bitplane DMA is on. Kickstart's own screens (insert-disk,
a CLI saying "not enough memory") are static and silent, so a failed start
never stays alive; a running demo does. A Guru Meditation box blinks, which
changes the screen: it is never alive. A run *works* when it collects
WORKS_ALIVE alive samples before any crash signal. A run that played
SHORT_ALIVE to WORKS_ALIVE-1, with sound in it, and then ended quiet is
*works-short*: a short tune or intro, not a failed start. Without sound it
is one: Kickstart's screen changes for as long while the Workbench opens or
a program prints why it cannot run.
"""

import dataclasses
import os

DMA_MASTER, DMA_AUDIO = 0x200, 0x00F
DMA_COPPER = 0x280       # DMAEN + COPEN
DMA_BITPLANES = 0x300   # DMAEN + BPLEN
WORKS_ALIVE = 8      # alive samples (x 250 frames = 40 s of activity)
SHORT_ALIVE = 3      # alive samples that make a short run more than a flicker
ENDED_QUIET = 8      # trailing quiet samples that mean the demo stopped
REBOOTS = 2          # RESETs that may mean a reboot loop


@dataclasses.dataclass
class Verdict:
    verdict: str          # works | works-short | works-then-crash | crash | no-activity | error
    alive: int            # alive samples before the crash (all if none)
    crash: str = None     # halt | alert:XXXXXXXX | guru | task-held | reboot | emulator-exit:N
    crash_frame: int = None
    ended_frame: int = None   # last alive frame when the run ends quiet
    wants_disk: bool = False  # asked for a disk beyond the set

    @property
    def works(self):
        return self.verdict == "works"


def audio_on(dmacon):
    return bool(dmacon & DMA_MASTER) and bool(dmacon & DMA_AUDIO)


def bitplane_dma(dmacon, bpl_active=False):
    """Bitplane DMA is on, either at the frame-boundary snapshot or on an
    active scanline during the frame (copper-gated AMOS Pro / mid-frame
    BPLEN). Not bplcon0: the snapshot is taken before the copper loads it."""
    return bpl_active or (dmacon & DMA_BITPLANES == DMA_BITPLANES)


DISPLAY_DMA = 0x300      # DMAEN | BPLEN
ROM_START = 0xE00000     # extended ROM and Kickstart; the CLI idles in here
ROM_END = 0xFFFFFF       # above this is Zorro III Fast RAM (0x40000000+)


def _in_rom(pc):
    return ROM_START <= pc <= ROM_END


def _custom_copper(s, system_copper):
    """True when the production replaced Kickstart's copper list (COP1LC):
    CLI, Workbench, EasyRequest, and ASL screens all keep COP1LC at
    GfxBase->copinit (``system_copper``), whereas custom-copper intros write
    $dff080 directly (and may call WaitTOF(), leaving PC in ROM at VBLANK)."""
    return (bool(system_copper)
            and s.cop1lc not in (0, system_copper)
            and not s.box
            and (s.dmacon & DMA_COPPER) == DMA_COPPER)


def alive_flags(samples, system_copper=0):
    flags, prev = [], None
    os_silent = []
    for s in samples:
        changed = prev is not None and s.shot and s.shot != prev
        audio = audio_on(s.dmacon)
        alive = not s.box and (audio or bool(
            changed and (bitplane_dma(s.dmacon, s.bpl_active)
                         or _custom_copper(s, system_copper))))
        flags.append(alive)
        # Silent screen change on Kickstart's own copper list: isolated
        # single-sample blips are CLI key-nudge echoes (1> v). Do not gate on
        # _in_rom(s.pc) because SetPatch/68060.library relocates Exec's idle
        # loop into Zorro III Fast RAM on wb_boot rungs.
        os_silent.append(bool(
            alive and not audio and system_copper
            and s.cop1lc == system_copper))
        prev = s.shot or prev
    orig = list(flags)
    for i, is_os in enumerate(os_silent):
        if is_os:
            prev_alive = i > 0 and orig[i - 1]
            next_alive = i + 1 < len(orig) and orig[i + 1]
            if not prev_alive and not next_alive:
                flags[i] = False
    return flags


def progress(samples):
    """How far a run that never came alive got, as a tuple to rank by: was
    the CPU still running outside the ROM at the end (a program that got
    going and hangs or waits, not a CLI that printed an error and went back
    to its prompt), then was the display on."""
    if not samples:
        return 0, 0
    last = samples[-1]
    return (int(not _in_rom(last.pc)),
            int((last.dmacon & DISPLAY_DMA) == DISPLAY_DMA))


def quiet_tail(log):
    """True when the run ends silent and still: finished, or waiting at a
    prompt (which may be its very first screen)."""
    flags = alive_flags(log.samples, log.system_copper)
    return len(flags) >= ENDED_QUIET and not any(flags[-ENDED_QUIET:])


def is_alert(code):
    """An alert exec could have raised. LastAlert is read from RAM a demo may
    have reused, so a value only counts if it decodes: a subsystem id exec
    knows (0x00-0x3F) and a non-zero code. Recoverable alerts count too: a
    "Software Failure" (CPU trap, 0000000x) ends the demo just the same."""
    return (code is not None and code != 0xFFFFFFFF
            and code & 0x7FFFFFFF != 0 and ((code >> 24) & 0x7F) <= 0x3F)


def alive_after(samples, flags, i):
    """Is any later sample of the same boot alive? A Guru Meditation ends the
    boot: whatever plays after the machine restarts (a click on the alert, or
    the dead-end alert's own reboot) is the demo starting over, not the demo
    surviving its crash. Kickstart 2+ shows a dead-end alert after the
    reset, so the sample that first sees it can already be the new boot:
    then nothing after it is the crashed boot's."""
    if i and samples[i].resets != samples[i - 1].resets:
        return False
    return any(f for f, s in zip(flags[i + 1:], samples[i + 1:])
               if s.resets == samples[i].resets)


def alert_onset(samples, flags, i):
    """Is sample ``i`` where an alert was raised? Only where LastAlert takes
    its value: a demo that keeps data at ExecBase+$202 leaves a value there
    while it plays (Elysion's BBS-Fax Trackmo, Exile), and judged later
    that stale value is "confirmed" by the run simply ending. On the last
    sample there is no later one to judge by: playing audio there is not a
    Guru Meditation."""
    s = samples[i]
    if not is_alert(s.alert) or (i and samples[i - 1].alert == s.alert):
        return False
    if i == len(samples) - 1:
        return not audio_on(s.dmacon)
    return not alive_after(samples, flags, i)


def box_onset(samples, flags, i):
    """Is sample ``i`` where a Guru Meditation box first shows? The box
    is also evidence when LastAlert's onset was followed by activity:
    without recognizing the box, its blinks look like recovery. A demo
    that goes on playing after its own alert box (a prompt it draws with
    DisplayAlert) did not crash."""
    if not samples[i].box or (i and samples[i - 1].box == samples[i].box):
        return False
    return not alive_after(samples, flags, i)


def restarted_after_playing(samples, flags, i):
    """Did the boot before sample ``i`` play the demo in full (WORKS_ALIVE
    alive samples), and the boot from ``i`` play it again? Then the reset
    was the demo's own ending, not a crash: a crash shows as an alert, and
    a crashing demo does not play for 40 s every time it is started."""
    before = samples[i - 1].resets if i else None
    played = sum(f for f, s in zip(flags[:i], samples[:i])
                 if s.resets == before)
    return played >= WORKS_ALIVE and any(
        f for f, s in zip(flags[i:], samples[i:]) if s.resets == samples[i].resets)


def crash_signal(log):
    """``(signal, frame)`` of the first crash, or ``(None, None)``."""
    for e in log.events:
        if e.get("event") == "halt":
            return "halt", e.get("frame")
    flags = alive_flags(log.samples, log.system_copper)
    rebooted = False
    first = {}   # (alert, boot) -> sample index it first showed up at
    for i, s in enumerate(log.samples):
        if alert_onset(log.samples, flags, i):
            return f"alert:{s.alert:08x}", s.frame
        if box_onset(log.samples, flags, i):
            return s.box, s.frame
        # A reboot loop keeps resetting, or never comes back to life. A
        # demo may reset the machine itself while it boots (Cubic Dream),
        # or at its end, and then plays again (Podtekst).
        if s.resets >= REBOOTS and not rebooted:
            rebooted = True
            if restarted_after_playing(log.samples, flags, i):
                continue
            if log.samples[-1].resets > s.resets or not any(flags[i + 1:]):
                return "reboot", s.frame
    if log.returncode not in (0, 2) and not log.timed_out:
        last = log.samples[-1].frame if log.samples else 0
        return f"emulator-exit:{log.returncode}", last
    return None, None


def classify(log, expected_samples):
    if not log.samples:
        why = "timeout" if log.timed_out else f"exit {log.returncode}"
        return Verdict("error", 0, crash=f"no-samples ({why})")
    flags = alive_flags(log.samples, log.system_copper)
    crash, crash_frame = crash_signal(log)
    if crash is None and len(log.samples) < expected_samples and log.timed_out:
        crash, crash_frame = "timeout", log.samples[-1].frame

    alive_before = sum(f for f, s in zip(flags, log.samples)
                       if crash_frame is None or s.frame <= crash_frame)
    if alive_before >= WORKS_ALIVE:
        v = "works" if crash is None else "works-then-crash"
    else:
        v = "crash" if crash else "no-activity"

    ended = None
    if len(flags) > ENDED_QUIET and not any(flags[-ENDED_QUIET:]) and any(flags):
        last = max(i for i, f in enumerate(flags) if f)
        ended = log.samples[last].frame
        if v == "no-activity" and alive_before >= SHORT_ALIVE and (
                any(audio_on(s.dmacon) for s in log.samples)
                or any(_custom_copper(s, log.system_copper)
                       for f, s in zip(flags, log.samples) if f)):
            v = "works-short"
    if v == "no-activity" and crash is None and log.system_copper:
        # Ultra-short silent custom-copper intro that exited cleanly back to ROM/CLI.
        if (alive_before >= 1
                and any(_custom_copper(s, log.system_copper) for s in log.samples)
                and _in_rom(log.samples[-1].pc)
                and log.samples[-1].cop1lc == log.system_copper):
            v = "works-short"
        # Sustained silent static custom-copper display (CPU running in RAM
        # with bitplanes on a non-OS copper list after changing from boot).
        elif (sum(_custom_copper(s, log.system_copper)
                  and bitplane_dma(s.dmacon, s.bpl_active)
                  for s in log.samples) >= WORKS_ALIVE
              and len({s.shot for s in log.samples if s.shot}) >= 2):
            v = "works-short"
    wants = any(e.get("event") == "autoswap-exhausted" for e in log.events)
    return Verdict(v, alive_before, crash, crash_frame, ended, wants)


def _accepted(log, frame, disk):
    """A scheduled insert counts when the demo read the drive with that disk
    in it, at any time after (Absolute Inebriation plays 9000 frames before
    it reads disk 2). An insert the demo was not ready for is followed by
    nothing, or by a disk change that takes the disk out again."""
    name = os.path.basename(disk or "")
    return any(frame < sm.last_dma and sm.df0 == name for sm in log.samples)


def played_swaps(log, swaps, v):
    """The swaps the demo went on to play after: in a run that crashed, a
    disk only counts when WORKS_ALIVE alive samples follow its insert before
    the crash. A disk forced in where the demo did not want one (a click or
    a scheduled insert into a megademo that loops on disk 1) crashes it
    within seconds, or goes in after the crash; that run must not outrank
    a clean one for "reaching" the disk. Also in a clean run a disk only
    counts when the drive was read after its insert: a detector firing on a
    demo that had loaded everything (Guignols Dance 2) inserted a disk
    nobody wanted."""
    swaps = [sw for sw in swaps
             if any(s.last_dma > sw[0] for s in log.samples)]
    if v.crash is None:
        return swaps
    flags = alive_flags(log.samples, log.system_copper)
    return [sw for sw in swaps
            if sum(f for f, s in zip(flags, log.samples)
                   if sw[0] < s.frame <= v.crash_frame) >= WORKS_ALIVE]


READ_CYL = 10   # a drive seen this far in was read, not just ID-checked


def disks_reached(log, swaps, drives, n):
    """How many disks of an n-disk set the demo got to: disk 1, plus each
    extra drive it read from, plus each disk swapped in."""
    if n <= 1:
        return n
    read = sum(1 for c in log.max_cyl[1:drives] if c >= READ_CYL)
    return min(n, 1 + read + len(swaps))


def swaps(log):
    """The disk changes the run performed, in order: ``[(frame, disk, how)]``
    where ``how`` is the detector trigger (poll | idle | reread), or
    "scheduled" for an insert at a fixed frame that the demo then read, plus
    ``+click`` when the detector clicked the left mouse button for the demo
    to take the disk, and ``+rclick`` when it then clicked the right one.
    Inserts the demo refused (rolled back) are dropped."""
    out, trigger = [], "poll"
    for e in log.events:
        ev = e.get("event")
        if ev == "swap-poll":
            trigger = "poll"
        elif ev == "swap-idle":
            trigger = "idle"
        elif ev == "swap-reread":
            trigger = "reread"
        elif ev == "autoswap":
            out.append([e.get("frame"), e.get("disk"), trigger])
        elif ev == "scheduled-swap" and _accepted(log, e.get("frame"), e.get("inserted")):
            # Pulses re-insert the same disk: the first insert the demo
            # took is the one that matters.
            if not any(x[1] == e.get("disk") for x in out):
                out.append([e.get("frame"), e.get("disk"), "scheduled"])
        elif ev == "autoswap-click" and out:
            out[-1][2] += "+click"
        elif ev == "autoswap-click-right" and out:
            out[-1][2] += "+rclick"
        elif ev == "autoswap-rollback" and out:
            # The demo refused the disk and got its old one back.
            out.pop()
    return [tuple(x) for x in out]
