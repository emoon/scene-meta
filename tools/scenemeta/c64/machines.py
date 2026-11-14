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
