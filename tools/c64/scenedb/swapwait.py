"""Decide from drive samples when a demo is waiting for its next disk.

A sample is the 1541's VIA2 port B (``drive``): bit 2 motor, bit 3 LED,
bits 0-1 stepper phase, bit 4 write-protect sensor, bit 7 sync. A drive that
is working shows a changing port (bits 0-6: the sync bit flips on any data
that goes by, even when nothing is progressing); a drive nobody is talking to
holds one value, with the motor spinning or stopped and the LED off, or
solid on after an error. A demo that wants a disk it does not have leaves the drive that way
for a long time, either spinning (it polls for the disk change: ``poll``) or
stopped behind a prompt (``idle``).

Cycle counts are exact (the emulator's stopwatch), so thresholds are in C64
time: a million cycles is about a second.
"""

import dataclasses

MOTOR = 0x04
PORT = 0x77               # port bits that mean something: all but sync and LED
SENSOR = 0x10             # write-protect sensor: flickers when a disk goes in
LED = 0x08
MOVED_ON_SHOTS = 5        # new distinct screens that mean the demo went on

POLL_QUIET = 20_000_000   # motor on, port frozen, screen still
POLL_ANIMATED_QUIET = 75_000_000   # ... screen animated: a part that loads nothing
IDLE_QUIET = 30_000_000   # motor off, port and screen frozen
MAX_PROMPT_SHOTS = 8      # distinct screens in IDLE_QUIET for a still prompt
PROBE_QUIET = 100_000_000 # motor off, port frozen, screen animated
SETTLE = 4_000_000        # after an insert: the sensor changes, not the demo
ACCEPT_WITHIN = 120_000_000
BLIP = 3_000_000          # a pulse this short does not end a quiet stretch ...
BLIP_GAP = 20_000_000     # ... unless another one follows within this long
PULSE_GAP = 8_000_000     # motor on/off this fast ...
PULSE_MIN = 4             # ... at least this many times in a row is a presence poll
BACKOFF = 30_000_000      # after a refused disk: no new trigger for this long
PROBE_BACKOFF = 100_000_000   # a refused probe is likely a demo that is just playing


def backoff(trig):
    return PROBE_BACKOFF if trig == "probe" else BACKOFF


@dataclasses.dataclass
class Sample:
    cycles: int
    pc: int
    drive: int      # VIA2 port B
    shot: str       # md5 of the screenshot ("" when missing)


def _port_frozen(a, b):
    return (a.drive ^ b.drive) & PORT == 0


def quiet_since(samples, floor=0):
    """Cycles where the drive port last started to hold still (not before
    ``floor``), or None when it is moving.

    A "turn disk" sign can blip the motor for a second every minute; such a
    short, rare pulse (``BLIP``, ``BLIP_GAP``) that returns to the same value
    does not end the quiet stretch. Any other change does.
    """
    run = base = off = last_blip = None
    for prev, cur in zip(samples, samples[1:]):
        if cur.cycles <= floor:
            continue
        if run is None:
            run, base, off, last_blip = prev.cycles, prev.drive & PORT, None, None
        if cur.drive & PORT == base:
            if off is not None:
                last_blip, off = off, None
            continue
        if off is None:
            if last_blip is not None and cur.cycles - last_blip < BLIP_GAP:
                run = None
                continue
            off = cur.cycles
        elif cur.cycles - off >= BLIP:
            run, base, off, last_blip = off, cur.drive & PORT, None, None
    if run is None or off is not None:
        return None
    return max(run, floor)


def pulse_since(samples, floor=0):
    """Cycles where a train of motor-only pulses began, or None. A loader
    that keeps asking the drive whether a disk is there spins the motor up
    and down every few million cycles and moves nothing else: ``quiet_since``
    sees an active drive, but the demo is waiting. Needs ``PULSE_MIN`` flips,
    none more than ``PULSE_GAP`` apart, up to the last sample."""
    start = last = None
    flips = 0
    for prev, cur in zip(samples, samples[1:]):
        if cur.cycles <= floor:
            continue
        if (cur.drive ^ prev.drive) & PORT & ~MOTOR:
            start = last = None
            flips = 0
        if (cur.drive ^ prev.drive) & MOTOR:
            if last is None or cur.cycles - last >= PULSE_GAP:
                start, flips = cur.cycles, 0
            flips += 1
            last = cur.cycles
    if last is None or flips < PULSE_MIN or samples[-1].cycles - last >= PULSE_GAP:
        return None
    return start


def trigger(samples, floor=0):
    """``"poll"`` or ``"idle"`` when the demo looks to be waiting for a disk
    (and has been for long enough), else None. Nothing before ``floor``.

    ``poll``: the motor spins and the port is frozen (the loader polls for a
    disk change). ``idle``: the drive is stopped and the screen is a still
    prompt, or loops through a few frames (a spinning disk icon). A stopped
    drive alone is not enough: demo parts that load nothing for a minute look
    the same, but they show many different screens. ``probe``: the drive has
    been stopped for minutes under an animated screen (an endless greetings
    loop with a "turn disk" sign); the disk is offered as a cheap bet.
    """
    start = waiting_since(samples, floor)
    if start is None:
        return None
    now = samples[-1]
    quiet = now.cycles - start
    if now.drive & MOTOR or start == pulse_since(samples, floor):
        # A loader that idles under an animated screen is a demo part that
        # loads nothing for a while: only a still prompt is a sure poll.
        need = POLL_QUIET if prompt_shots(samples, POLL_QUIET) is not None \
            else POLL_ANIMATED_QUIET
        return "poll" if quiet >= need else None
    if quiet < IDLE_QUIET:
        return None
    if prompt_shots(samples, IDLE_QUIET) is not None:
        return "idle"
    return "probe" if now.cycles - start >= PROBE_QUIET else None


def prompt_shots(samples, window):
    """The distinct screens of the last ``window`` cycles when that is a still
    or tightly looping prompt (few of them), else None."""
    now = samples[-1].cycles
    shots = {s.shot for s in samples if s.cycles >= now - window}
    return shots if len(shots) <= MAX_PROMPT_SHOTS else None


def waiting_since(samples, floor=0):
    """Where the drive went quiet, as the point the demo asked for a disk."""
    quiet, pulses = quiet_since(samples, floor), pulse_since(samples, floor)
    return quiet if pulses is None or quiet is not None and quiet <= pulses else pulses


def drive_moved_since(samples, start, mask=PORT & ~SENSOR):
    """True when the motor, stepper or density bits changed after ``start``
    from what they were at ``start``. The write-protect sensor, LED and sync
    bits do not count: they flicker when a disk goes in or data goes by."""
    before = [x for x in samples if x.cycles <= start]
    base = before[-1] if before else samples[0]
    return any((base.drive ^ x.drive) & mask
               for x in samples if x.cycles > start)


def read_after(samples, insert_cycles, pulsing=False):
    """True when the demo used the drive after an insert. ``pulsing``: the
    demo was polling with motor pulses, which go on until it reads, so the
    motor bit says nothing."""
    return drive_moved_since(samples, insert_cycles,
                             PORT & ~SENSOR & ~(MOTOR if pulsing else 0))


def moved_on(samples, insert_cycles, prompt, until=None):
    """True when the screen left a still ``prompt`` (its set of screens) for
    new, changing ones: a demo that took the disk but plays on from memory
    before it reads anything. Screens from ``until`` on (our first key press)
    do not count: a menu that waits for a key moves on because of the key."""
    after = {s.shot for s in samples
             if s.cycles > insert_cycles + SETTLE and (until is None or s.cycles < until)}
    return prompt is not None and len(after - prompt) >= MOVED_ON_SHOTS
