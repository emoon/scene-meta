"""Keyboard and joystick presses for one running emulator, as X events.

VICE's monitor cannot press the keyboard matrix or the joystick, so the press
goes to the emulator's X window through the XTest extension (libX11 and
libXtst via ctypes: no xdotool needed). The display of the emulator is read
from its environment, since many Xvfb servers run side by side.
"""

import ctypes
import ctypes.util
import os
import subprocess
import sys
import time

_x = ctypes.CDLL(ctypes.util.find_library("X11"))
_t = ctypes.CDLL(ctypes.util.find_library("Xtst"))
_x.XOpenDisplay.restype = ctypes.c_void_p
_x.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x.XStringToKeysym.restype = ctypes.c_ulong
_x.XStringToKeysym.argtypes = [ctypes.c_char_p]
_x.XKeysymToKeycode.restype = ctypes.c_ubyte
_x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
_x.XCloseDisplay.argtypes = [ctypes.c_void_p]
_t.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                 ctypes.c_int, ctypes.c_ulong]
_t.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_ulong]

HOLD = 0.4        # wall seconds a key stays down (the emulator is running)
SETTLE = 0.3      # wall seconds to run on after the release


def _environ_of(pid):
    with open(f"/proc/{pid}/environ", "rb") as f:
        return dict(kv.split(b"=", 1) for kv in f.read().split(b"\0") if b"=" in kv)


def _emulator_env(pgid):
    """(DISPLAY, XAUTHORITY) of the x64sc in process group ``pgid``."""
    out = subprocess.run(["ps", "-o", "pid=,comm=", "-g", str(pgid)],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        pid, comm = line.split(None, 1)
        if comm.strip().startswith("x64sc"):
            env = _environ_of(pid)
            return env[b"DISPLAY"].decode(), env.get(b"XAUTHORITY", b"").decode()
    raise RuntimeError("no x64sc process to press keys for")


def _send(display, keysym, numlock):
    """Child process: tap ``keysym`` on ``display`` (XAUTHORITY in the env)."""
    d = _x.XOpenDisplay(display.encode())
    if not d:
        raise SystemExit(f"cannot open display {display}")

    def tap(sym, hold):
        code = _x.XKeysymToKeycode(d, _x.XStringToKeysym(sym.encode()))
        if not code:
            raise SystemExit(f"no keycode for {sym}")
        _t.XTestFakeKeyEvent(d, code, 1, 0)
        _x.XSync(d, 0)
        time.sleep(hold)
        _t.XTestFakeKeyEvent(d, code, 0, 0)
        _x.XSync(d, 0)

    # No window manager: keyboard focus follows the pointer.
    _t.XTestFakeMotionEvent(d, 0, 100, 100, 0)
    if numlock:
        tap("Num_Lock", 0.05)     # the numpad joystick needs NumLock on
    tap(keysym, HOLD)
    _x.XCloseDisplay(d)


class Keys:
    """Presses for the emulator ``vice`` (a running ``vice.Vice``)."""

    JOYSTICK = {"p1fire": 1, "p2fire": 2}      # key name -> joystick port
    SYMS = {"space": "space", "Return": "Return", "Left": "Left",
            "p1fire": "KP_0", "p2fire": "KP_0",
            **{k: k for k in "0123456789abcdefghijklmnopqrstuvwxyz"},
            **{f"F{n}": f"F{n}" for n in range(1, 9)}}

    def __init__(self, vice):
        self.vice = vice
        self.display, self.auth = _emulator_env(vice.proc.pid)
        self.numlock_set = False
        self.joy_port = None

    def close(self):
        pass

    def _select_port(self, port):
        if self.joy_port != port:
            self.vice.cmd(f'resourceset "JoyDevice1" "{int(port == 1)}"')
            self.vice.cmd(f'resourceset "JoyDevice2" "{int(port == 2)}"')
            self.joy_port = port

    def press(self, key):
        """Press ``key`` (a ``SYMS`` name) with the emulator running, then
        stop it again. Returns ``(cycles, pc)``."""
        if key in self.JOYSTICK:
            self._select_port(self.JOYSTICK[key])
        env = dict(os.environ)
        if self.auth:
            env["XAUTHORITY"] = self.auth
        self.vice.resume()
        time.sleep(0.1)
        subprocess.run([sys.executable, "-m", "scenemeta.xinput", self.display,
                        self.SYMS[key], "" if self.numlock_set else "numlock"],
                       env=env, cwd=os.path.dirname(os.path.dirname(__file__)),
                       check=False, capture_output=True)
        self.numlock_set = True
        time.sleep(SETTLE)    # the release has to be processed before a sample
        return self.vice.stop()


if __name__ == "__main__":
    _send(sys.argv[1], sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "numlock")
