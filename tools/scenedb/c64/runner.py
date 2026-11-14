"""Boot one variant on one machine and find when it asks for its next disk.

Disk 1 is autostarted. The run is sampled every ``STEP`` seconds of wall time
(drive port, PC, screenshot, all stamped with exact cycles). When the demo
looks to be waiting for a disk (``swapwait.trigger``) the next disk is flipped
in, the way a person does it. The flip counts once the drive is used again; a
disk the demo ignores is taken back out and the trigger backs off.
"""

import dataclasses
import hashlib
import os
import pathlib
import re
import shutil
import tempfile
import time

from . import swapwait, verdict, vice

STEP = 0.1            # wall seconds between samples
TAIL = 150_000_000    # cycles to keep running once the last disk is in
CYCLES_PER_WALL_SECOND = 4_000_000   # slowest warp speed we budget for
START_TRIES = 3
CRASH_AFTER_INSERT = 60_000_000   # a crash this soon after an insert is blamed on it
RETRIES = 2           # re-runs with a flip vetoed after it killed the emulator
KEYS = ("space", "p1fire", "p2fire")   # tried in turn on a new disk
LED_WAITS = 40        # samples to wait for the drive LED to go dark before a flip
KEY_GAP = 5_000_000   # cycles between presses
ANSWER_AFTER = 25_000_000   # no answers before the autostart load is over
ANSWER_GAP = 20_000_000     # cycles between answers to text screens
ANSWERS = 40                # most answers in one run

REU_CHECK_EVERY = 10     # samples between looks at the screen for "REU"
_REU_WORD = (bytes([32, 18, 5, 21, 32]),    # " REU ", uppercase charset
             bytes([32, 82, 69, 85, 32]))   # " REU ", lowercase charset

ASK_CHECK_EVERY = 5      # samples between looks at the screen for a disk request
_ASK = re.compile(r"(FLIP|TURN|CHANGE|SWAP|INSERT|NEXT|OTHER)\W+(THE\W+|YOUR\W+)?"
                  r"(DISK|DISC|DISKETTE|SIDE)|BITTE\W+DISK|(DISK|DISC|SIDE)\W+(OVER|TWO|2|B)\b")

# A text screen that waits for a key before the demo goes on: (regex, key).
_ANSWERS = ((re.compile(r"(PRESS|HIT)\W+(THE\W+)?(SPACE|ANY\W*KEY)|SPACE\W+TO\W+(CONTINUE|START)"),
             "space"),
            (re.compile(r"\bY\W+N\b"), "n"))   # an answered question stays on screen

_READY = bytes([0x12, 0x05, 0x01, 0x04, 0x19, 0x2E])   # "READY." in screen codes
SCREEN_RAM, SCREEN_LEN = 0x0400, 1000


@dataclasses.dataclass
class Flip:
    disk: int              # 1-based disk number inserted
    trigger: str           # poll | idle | probe
    waiting_since: int     # cycles: when the drive went quiet
    inserted: int          # cycles: when the new disk went in
    accepted: bool = False
    shot: bytes = b""      # screenshot when the flip was decided
    key: str = None        # last key pressed after the insert, if any
    key_at: int = None     # cycles of that press
    prompt: set = None     # screens of the prompt when it was a still one
    pulsing: bool = False  # the demo was polling with motor pulses


@dataclasses.dataclass
class RunLog:
    samples: list
    basic: set             # sample indexes showing the BASIC prompt
    flips: list
    crash: str = None
    crash_cycles: int = None
    wants_disk: bool = False
    needs_reu: bool = False   # the screen said the demo needs a REU
    asked_disk: int = None    # cycles when the screen first asked for a disk
    last_shot: bytes = b""
    detail: str = ""       # tail of the emulator log when the run crashed

    @property
    def accepted(self):
        return [f for f in self.flips if f.accepted]


def crashing_flip(log):
    """The flip the emulator died soon after, or None. A disk pulled while the
    demo is still reading kills it, so such a flip was a false trigger."""
    if log.crash and log.flips and log.crash_cycles is not None:
        last = log.flips[-1]
        if 0 <= log.crash_cycles - last.inserted <= CRASH_AFTER_INSERT:
            return last
    return None


def refused_flip(log):
    """The first flip the demo ignored on the way to the next disk of a chain
    that already flipped for real, or None. Such a flip was an early guess
    (a part that polls the drive or plays on under a still drive); pulling the
    disk back out can leave the real prompt later on garbled."""
    done = len(log.accepted)
    if not done:
        return None
    return next((f for f in log.flips if not f.accepted and f.disk == done + 2), None)


def run(machine, variant, budget):
    """Run ``variant`` on ``machine`` for up to ``budget`` cycles.

    When a flip kills the emulator the run is repeated with that disk vetoed
    until the cycle the flip was made at; when a flip deep in a chain was
    ignored, until it would have been taken back out (once per disk). The run
    that got furthest wins.
    """
    veto = {}                # disk number -> no flip to it before this cycle
    best = None
    for _ in range(RETRIES + 1):
        log = _run_once(machine, variant, budget, veto)
        if best is None or len(log.accepted) >= len(best.accepted):
            best = log
        flip = crashing_flip(log)
        if flip:
            veto[flip.disk] = flip.inserted
            continue
        flip = refused_flip(log)
        if not flip or flip.disk in veto:
            break
        veto[flip.disk] = flip.inserted + swapwait.ACCEPT_WITHIN
    return best


def _run_once(machine, variant, budget, veto):
    with tempfile.TemporaryDirectory(prefix="scenedb-") as t:
        tmp = pathlib.Path(t)
        # The emulator writes disk changes back to the image: use copies.
        disks = []
        for i, src in enumerate(variant.disks):
            dst = tmp / "disks" / f"{i}{os.path.splitext(src)[1].lower()}"
            dst.parent.mkdir(exist_ok=True)
            shutil.copyfile(src, dst)
            disks.append(dst)
        log = RunLog([], set(), [])
        try:
            for attempt in range(START_TRIES):
                try:
                    with vice.Vice(machine, disks[variant.boot_disk:], tmp, vice.free_port(),
                                   variant.boot_file) as v:
                        _drive(v, disks, variant.boot_disk, budget, tmp, log, veto)
                    break
                except vice.StartError:
                    # Many instances starting at once can lose the race for
                    # an X display or a port.
                    if attempt == START_TRIES - 1:
                        raise
                    time.sleep(1 + attempt)
        except vice.ViceError as e:
            last = log.samples[-1].cycles if log.samples else 0
            logfile = tmp / "vice.log"
            log.crash, log.detail = crash_cause(
                str(e), logfile.read_text(errors="replace") if logfile.exists() else "")
            log.crash_cycles = last
        return log


_JAM = re.compile(r"^\*+\s+(.*JAM at \$[0-9A-Fa-f]+)", re.M)


def crash_cause(error, vice_log):
    """``(crash, detail)`` for a run the emulator died in. A CPU JAM (main or
    drive; ``-jamaction 5`` turns it into an exit) is named "jam" with its log
    line, since the 600-char log tail is mostly the shutdown resource dump."""
    m = _JAM.search(vice_log)
    if m:
        return "jam", m.group(1).strip() + "\n" + vice_log[-600:]
    return ("emulator-exit" if "closed" in error else "timeout"), vice_log[-600:]


def wants_reu(screen):
    """True when the screen text (screen codes) names a REU as a requirement."""
    return any(w in screen for w in _REU_WORD)


def screen_text(screen):
    """Upper-case text of a text screen given as screen codes (either
    charset: letters are 1-26 or 65-90, inverse video adds 128); anything else
    becomes a space."""
    return "".join(chr(64 + c) if 1 <= c <= 26 else
                   chr(c) if 65 <= c <= 90 or 48 <= c <= 57 else " "
                   for c in (b & 0x7F for b in screen))


def asks_for_disk(screen):
    """True when the screen text (screen codes) asks to flip, turn or insert a
    disk. Only text screens show up: a picture saying so reads as no."""
    return bool(_ASK.search(screen_text(screen)))


def answer_key(screen):
    """The key a text screen waits for ("(Y/N)" gets n, "press space" gets
    space), or None. A screen that asks for a disk is left to the flip logic."""
    text = screen_text(screen)
    if _ASK.search(text):
        return None
    return next((key for rx, key in _ANSWERS if rx.search(text)), None)


def _sample(v, shot_path, log):
    cycles, pc = v.run_for(STEP)
    drive = v.peek("8", 0x1C00)[0]
    v.screenshot(shot_path)
    data = shot_path.read_bytes() if shot_path.exists() else b""
    s = swapwait.Sample(cycles, pc, drive,
                        hashlib.md5(data).hexdigest() if data else "")
    if pc >= 0xA000 and _READY in bytes(v.peek("", SCREEN_RAM, SCREEN_LEN)):
        log.basic.add(len(log.samples))
    n = len(log.samples)
    check_reu = not log.needs_reu and n % REU_CHECK_EVERY == 0
    check_ask = log.asked_disk is None and n % ASK_CHECK_EVERY == 0
    if check_reu or check_ask:
        screen = v.screen_ram()
        if check_reu and wants_reu(screen):
            log.needs_reu = True
        if check_ask and asks_for_disk(screen):
            log.asked_disk = cycles
    log.samples.append(s)
    log.last_shot = data
    return s, data


def _drive(v, disks, first, budget, tmp, log, veto):
    shot_path = tmp / "shot.png"
    deadline = time.time() + 120 + budget / CYCLES_PER_WALL_SECOND
    cur = first              # index of the disk in the drive
    pending = None           # (Flip, disk index before the flip)
    keys = []                # keys left to try on this insert, in order
    last_key = 0             # cycles of the last press
    first_key = None         # cycles of the first press after this insert
    led_waits = 0            # samples spent waiting for the LED to go dark
    floor = 0                # no trigger before this many cycles
    done_at = None           # cycles at which to stop (last disk is in)
    answered = set()         # text screens already answered
    last_answer = 0
    while True:
        s, data = _sample(v, shot_path, log)
        if s.cycles >= budget or (done_at and s.cycles >= done_at):
            return
        if time.time() > deadline:
            raise vice.ViceError("wall-clock budget exceeded (timeout)")
        if pending:
            flip, before = pending
            if (swapwait.read_after(log.samples, flip.inserted, flip.pulsing)
                    or swapwait.moved_on(log.samples, flip.inserted, flip.prompt, first_key)):
                flip.accepted, cur, pending = True, flip.disk - 1, None
                floor = s.cycles
                if cur == len(disks) - 1:
                    done_at = s.cycles + TAIL
            elif (keys and s.cycles > flip.inserted + swapwait.SETTLE
                  and s.cycles >= last_key + KEY_GAP):
                # "Insert disk and press a key": the demo may be waiting for one.
                flip.key = keys.pop(0)
                last_key = flip.key_at = v.press(flip.key)[0]
                first_key = first_key or last_key
            elif s.cycles > flip.inserted + swapwait.ACCEPT_WITHIN:
                # The demo ignored it: put the old disk back.
                v.change_disk(disks[before])
                pending, floor = None, v.stop()[0] + swapwait.backoff(flip.trigger)
            continue
        if (s.cycles >= max(ANSWER_AFTER, last_answer + ANSWER_GAP)
                and len(answered) < ANSWERS
                and len(log.samples) % ASK_CHECK_EVERY == 0):
            screen = bytes(v.peek("", SCREEN_RAM, SCREEN_LEN))
            key = answer_key(screen)
            if key and screen not in answered:
                answered.add(screen)
                last_answer = floor = v.press(key)[0]
                continue
        lo = max(floor, veto.get(cur + 2, 0))
        trig = swapwait.trigger(log.samples, lo)
        if not trig:
            continue
        if cur + 1 >= len(disks):
            log.wants_disk = len(disks) > 1
            floor = s.cycles + swapwait.backoff(trig)
            continue
        if s.drive & swapwait.LED and led_waits < LED_WAITS:
            # Pulling the disk while the LED is lit can wedge the 1541 for good.
            led_waits += 1
            continue
        led_waits = 0
        since = swapwait.waiting_since(log.samples, floor)
        inserted = v.change_disk(disks[cur + 1])
        prompt = swapwait.prompt_shots(log.samples, swapwait.IDLE_QUIET)
        pending = (Flip(cur + 2, trig, since, inserted, shot=data, prompt=prompt,
                        pulsing=since == swapwait.pulse_since(log.samples, floor)), cur)
        keys, last_key, first_key = list(KEYS), inserted, None
        log.flips.append(pending[0])
