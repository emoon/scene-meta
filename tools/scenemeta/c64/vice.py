"""Drive one x64sc through its remote monitor.

Any line sent to the monitor port stops the emulator at the next instruction
and gives a prompt; ``x`` lets it run again. The line that stops it is
``stopwatch`` (the CPU cycle counter), which is the emulated clock: samples
are stamped with exact cycles however irregular the wall-clock pacing is.
One line per send: the monitor drops the rest of a multi-line write.
"""

import os
import pathlib
import re
import socket
import subprocess
import time

from . import config

_PROMPT = r"\(C:\$[0-9a-f]{4}\) "
_STOPPED = re.compile(rf"Stopwatch:\s+(\d+)\n\(C:\$([0-9a-f]{{4}})\) $")
_PROMPT_RE = re.compile(_PROMPT)

# How long a flipped disk stays out of the drive (about 3 s of C64 time): the
# drive's write-protect sensor must see the slot empty to notice a change.
GAP_CYCLES = 3_000_000


class ViceError(RuntimeError):
    pass


class StartError(ViceError):
    """The emulator never came up (before a single sample)."""


class Vice:
    """A running emulator. Use as a context manager."""

    def __init__(self, machine, images, workdir, port, boot_file="", seed=None):
        self.machine = machine
        self.boot_file = boot_file
        self.seed = seed
        self.images = [str(i) for i in images]
        self.workdir = pathlib.Path(workdir)
        self.port = port
        self.proc = None
        self.sock = None
        self.running = False
        self._keys = None

    # -- lifecycle -----------------------------------------------------------
    def __enter__(self):
        home = self.workdir / "home"
        for sub in (".cache/vice", ".config"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, HOME=str(home),
                   XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_CACHE_HOME=str(home / ".cache"))
        argv = ["xvfb-run", "-a", "-s", "-screen 0 640x480x24", config.VICE,
                "-default", *self.machine.args(config.ROM_DIR),
                "-remotemonitor",
                "-remotemonitoraddress", f"ip4://127.0.0.1:{self.port}",
                "-cartcrt" if pathlib.Path(self.images[0]).suffix.lower() == ".crt" else "-autostart",
                self.images[0] + (f":{self.boot_file}" if self.boot_file else "")]
        if self.seed is not None:
            argv += ["-seed", str(self.seed)]
        self.proc = subprocess.Popen(
            argv, cwd=self.workdir, env=env, stdin=subprocess.DEVNULL,
            stdout=open(self.workdir / "vice.log", "w"),
            stderr=subprocess.STDOUT, start_new_session=True)
        try:
            self.sock = self._connect()
            self.stop()
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self._keys:
                self._keys.close()
            if self.sock:
                self.sock.close()
        finally:
            if self.proc and self.proc.poll() is None:
                _kill_group(self.proc)
            if self.proc:
                self.proc.wait()

    def _connect(self):
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise StartError(f"x64sc exited early ({self.proc.returncode})")
            try:
                return socket.create_connection(("127.0.0.1", self.port))
            except OSError:
                time.sleep(0.2)
        raise StartError("remote monitor never came up")

    # -- monitor -------------------------------------------------------------
    def _read_until(self, done, timeout=60):
        self.sock.settimeout(timeout)
        buf = ""
        while True:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise ViceError(f"monitor timeout; got {buf[-200:]!r}")
            except ConnectionError:
                raise ViceError("monitor closed (emulator died)")
            if not chunk:
                raise ViceError("monitor closed (emulator died)")
            buf += chunk.decode(errors="replace")
            m = done.search(buf)
            if m:
                return buf, m

    def stop(self):
        """Halt the emulator at a prompt. Returns ``(cycles, pc)``: the cycle
        counter and where the C64 CPU stopped."""
        self.sock.sendall(b"stopwatch\n")
        self.running = False
        _, m = self._read_until(_STOPPED)
        return int(m.group(1)), int(m.group(2), 16)

    def cmd(self, text):
        """Run one monitor command while stopped. Returns its output."""
        self.sock.sendall((text + "\n").encode())
        out, _ = self._read_until(re.compile(_PROMPT + "$"))
        return _PROMPT_RE.sub("", out).strip("\n")

    def resume(self):
        self.sock.sendall(b"x\n")
        self.running = True

    def run_for(self, seconds):
        """Let the emulator run for ``seconds`` of wall time, then stop it.
        Returns ``(cycles, pc)``."""
        self.resume()
        time.sleep(seconds)
        return self.stop()

    def run_until(self, cycles, step=0.05):
        """Run in ``step`` slices until the cycle counter passes ``cycles``."""
        now = self.stop()
        while now[0] < cycles:
            now = self.run_for(step)
        return now

    def press(self, key):
        """Press a key or joystick fire (see ``xinput.Keys.SYMS``). Needs the
        emulator stopped; leaves it stopped. Returns ``(cycles, pc)``."""
        if self._keys is None:
            from . import xinput    # X libraries only when a press is needed
            self._keys = xinput.Keys(self)
        return self._keys.press(key)

    # -- state ---------------------------------------------------------------
    def peek(self, space, addr, length=1, bank=None):
        """Bytes of ``space`` ("" = C64, "8" = drive 8) at ``addr``. ``bank``
        ("ram", "io", ...) picks what the C64 CPU view hides: the default view
        shows ROM and I/O only while the program has them switched in."""
        prefix = f"{space}:" if space else ""
        if bank:
            self.cmd(f"bank {bank}")
        try:
            out = self.cmd(f"m {prefix}{addr:04x} {addr + length - 1:04x}")
        finally:
            if bank:
                self.cmd("bank default")
        data = []
        for line in out.splitlines():
            m = re.match(r">[0-9A-Za-z]*:?[0-9a-f]{4}\s+((?:[0-9a-f]{2} ?\s?)+)", line)
            if m:
                data += [int(b, 16) for b in m.group(1).split()]
        return data[:length]

    def screen_ram(self):
        """The 1000 screen codes the VIC shows now (text screen at the bank and
        offset CIA2 and $D018 select), high bit cleared: inverse text reads as text."""
        base = vic_screen_base(self.peek("", 0xDD00, bank="io")[0],
                               self.peek("", 0xD018, bank="io")[0])
        return bytes(c & 0x7F for c in self.peek("", base, 1000, bank="ram"))

    def screenshot(self, path):
        self.cmd(f'screenshot "{path}" 2')

    def change_disk(self, image, gap_cycles=GAP_CYCLES, unit=8):
        """Flip the disk in ``unit`` the way a person does: take it out, wait,
        put the other one in. Needs the emulator stopped; leaves it stopped.
        Returns the cycle counter after the insert."""
        self.cmd(f"detach {unit}")
        cycles, _ = self.stop()
        cycles, _ = self.run_until(cycles + gap_cycles)
        self.cmd(f'attach "{image}" {unit}')
        return cycles


def _kill_group(proc):
    import signal
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def vic_screen_base(dd00, d018):
    """Address of the text screen: CIA2 port A bits 0-1 (inverted) pick the
    16K VIC bank, $D018 bits 4-7 the 1K screen inside it."""
    return (3 - (dd00 & 3)) * 0x4000 + ((d018 >> 4) & 15) * 0x400
