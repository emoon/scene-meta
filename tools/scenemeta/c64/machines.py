"""The machine ladder, cheapest first. A demo is filed under the first
machine it works on. The REU machine is only tried for a demo that asks for
one (``runner.wants_reu``)."""

import dataclasses


SYSTEM_DATA = "/usr/share/vice"


@dataclasses.dataclass(frozen=True)
class Machine:
    name: str
    description: str
    flags: tuple          # VICE options beyond the ROM set
    cycles_per_frame: int
    hz: int               # CPU cycles per second: cycles of a run to seconds

    @property
    def reu(self):
        return "-reu" in self.flags

    def args(self, rom_dir):
        # VICE looks in <dir>/C64 and <dir>/DRIVES; the system data dir stays
        # on the path for the GL shaders and the like.
        return ["-directory", f"{rom_dir}:{SYSTEM_DATA}", "+sound", "-warp",
                *self.flags]


# jamaction 5: a CPU JAM ends the process, which the run reports as a crash.
_COMMON = ("-drive8type", "1541", "-jamaction", "5")

PAL_HZ, NTSC_HZ = 985_248, 1_022_727

LADDER = (
    Machine("pal_1541", "C64 PAL (6569), 1541, true drive emulation",
            ("-model", "c64", *_COMMON), 19656, PAL_HZ),
    Machine("ntsc_1541", "C64 NTSC (6567R8), 1541, true drive emulation",
            ("-model", "ntsc", *_COMMON), 17095, NTSC_HZ),
    # 16 MB covers every size a demo asks for (512 KB is the usual minimum).
    Machine("pal_1541_reu", "C64 PAL (6569), 1541, 16 MB REU",
            ("-model", "c64", *_COMMON, "-reu", "-reusize", "16384"), 19656,
            PAL_HZ),
)

BY_NAME = {m.name: m for m in LADDER}


def hz(name):
    """The clock of the machine called ``name``; PAL when it is not known."""
    return BY_NAME[name].hz if name in BY_NAME else PAL_HZ


def resolve(entry, default, presets):
    """Translate the entry's hardware facts, without falling back to a ladder."""
    from ..core.errors import BadEntry
    name = entry.get("machine", default)
    if name not in presets:
        raise BadEntry(f"no machine {name!r}")
    hardware = {k: v for k, v in presets[name].items() if k != "description"}
    hardware.update({k: entry[k] for k in ("video", "sid", "drive", "reu")
                     if k in entry})
    if hardware.get("video") not in ("pal", "ntsc"):
        raise BadEntry(f"unsupported video {hardware.get('video')!r}")
    if hardware.get("sid") not in ("6581", "8580"):
        raise BadEntry(f"unsupported SID {hardware.get('sid')!r}")
    if hardware.get("drive") != "1541" or entry.get("drives", 1) != 1:
        raise BadEntry("the C64 player supports one 1541 drive")
    base = BY_NAME["pal_1541" if hardware["video"] == "pal" else "ntsc_1541"]
    flags = (*base.flags, "-sidenginemodel", "256" if hardware["sid"] == "6581" else "257")
    if reu := hardware.get("reu"):
        import re
        m = re.fullmatch(r"(\d+)(K|M)", str(reu))
        size = int(m[1]) * (1024 if m[2] == "M" else 1) if m else 0
        if size not in (128, 256, 512, 1024, 2048, 4096, 8192, 16384):
            raise BadEntry(f"unsupported REU {reu!r}")
        flags += ("-reu", "-reusize", str(size))
    return dataclasses.replace(base, name=name, flags=flags)


def require_roms(rom_dir):
    """Fail before a run when the configured ROM set is incomplete."""
    from ..core.errors import CannotPlay
    from .tools.extract_roms import WANTED
    for name in WANTED.values():
        # Only the configured 1541 is used, not the 1541-II.
        if "d1541II" not in name and not (rom_dir / name).is_file():
            raise CannotPlay(f"missing VICE ROM: {rom_dir / name}")
