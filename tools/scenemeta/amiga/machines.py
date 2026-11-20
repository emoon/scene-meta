"""The machine ladder, cheapest first. A demo is filed under the first
machine it works on."""

import dataclasses

from . import config
from ..core.errors import CannotPlay

_HEADLESS = """\
use_gui=no
headless=true
sound_output=none
show_leds=no
synchronize_clock=false
"""

_A500 = """\
cpu_type=68000
cpu_model=68000
cycle_exact=true
"""

# 68EC020 @ 14 MHz, AGA, cycle-exact. bogomem_size=0 overrides Amiberry's
# default 512K slow RAM, which no A1200 has. cpu_24bit_addressing must follow
# cpu_type or the EC is silently dropped.
_A1200 = """\
cpu_type=68ec020
cpu_model=68020
cpu_24bit_addressing=true
cpu_compatible=true
cpu_cycle_exact=true
cpu_memory_cycle_exact=true
blitter_cycle_exact=true
chipset=aga
chipmem_size=4
bogomem_size=0
"""

# Fast CPUs are not cycle exact. Unimplemented 040/060 instructions are
# emulated, standing in for the 68040/68060.library a real setup would load.
# UAE's *_no_unimplemented=true is the opposite: they trap as on a bare 060,
# and FSIN & co. end in a line-F Guru (8000000B).
_FAST_CPU = """\
cpu_24bit_addressing=false
cpu_compatible=false
cpu_cycle_exact=false
cpu_memory_cycle_exact=false
blitter_cycle_exact=false
cpu_no_unimplemented=false
fpu_no_unimplemented=false
chipset=aga
chipmem_size=4
bogomem_size=0
"""


@dataclasses.dataclass(frozen=True)
class Machine:
    name: str
    rom: str
    uae: str
    aga: bool
    description: str
    # A rung whose ROM may be missing: it is skipped, not run to fail.
    optional: bool = False
    # The machine boots with its FPU switched off, as a 68060 board's ROM
    # leaves it for 68060.library to switch on: the run does that first.
    fpu_off: bool = False
    # Only tried for productions released after the A1200 came out (see
    # ladder_for): a demo older than that works on a slower rung or on none.
    aga_era: bool = False

    @property
    def fast_ram(self):
        return "z3mem_size" in self.uae


LADDER = (
    Machine("a500", "kick13.rom", _A500 + "chipset=ocs\nchipmem_size=1\nbogomem_size=2\n",
            False, "A500 68000, OCS, KS1.3, 512K chip + 512K slow"),
    Machine("a500_1mb", "kick13.rom", _A500 + "chipset=ecs_agnus\nchipmem_size=2\nbogomem_size=2\n",
            False, "A500 68000, ECS Agnus, KS1.3, 1M chip + 512K slow"),
    # Demos from the Kickstart 1.2 era hard-code ROM addresses: Stack's and
    # X-Men's intros end their own level 3 handler with `jmp $FC0CD8`, which
    # is the 1.2 handler and lands in the middle of another routine in 1.3.
    Machine("a500_ks12", "kick12.rom",
            _A500 + "chipset=ocs\nchipmem_size=1\nbogomem_size=2\n",
            False, "A500 68000, OCS, KS1.2, 512K chip + 512K slow", True),
    # A stock A500 with no trapdoor RAM. With slow RAM present AmigaDOS
    # loads an executable there, and intros written for a bare 512K machine
    # Guru (RAF Party Intro, Guardian Snail: their CLI task at $C06670).
    Machine("a500_512k", "kick13.rom",
            _A500 + "chipset=ocs\nchipmem_size=1\nbogomem_size=0\n",
            False, "A500 68000, OCS, KS1.3, 512K chip"),
    # With slow RAM present, Kefmania's own reboot into disk 2 Gurus during
    # the boot; it also refuses to run on 512K chip ("REQUIRS 1MEG").
    Machine("a500_1mb_chip", "kick13.rom",
            _A500 + "chipset=ecs_agnus\nchipmem_size=2\nbogomem_size=0\n",
            False, "A500 68000, ECS Agnus, KS1.3, 1M chip"),
    Machine("a1200", "kick30.rom", _A1200,
            True, "A1200 68EC020, AGA, KS3.0, 2M chip"),
    Machine("a1200_fast", "kick30.rom", _A1200.replace("cpu_24bit_addressing=true",
                                                       "cpu_24bit_addressing=false")
            + "z3mem_size=8\n",
            True, "A1200 68020, AGA, KS3.0, 2M chip + 8M fast"),
    Machine("a1200_030", "kick30.rom",
            "cpu_type=68030\ncpu_model=68030\nfpu_model=68882\ncpu_speed=max\n"
            + _FAST_CPU + "z3mem_size=32\n",
            True, "A1200 68030 + 68882, AGA, KS3.0, 2M chip + 32M fast",
            aga_era=True),
    Machine("a1200_060", "kick30.rom",
            "cpu_type=68060\ncpu_model=68060\nfpu_model=68060\ncpu_speed=max\n"
            + _FAST_CPU + "z3mem_size=64\n",
            True, "A1200 68060, AGA, KS3.0, 2M chip + 64M fast", fpu_off=True, aga_era=True),
)

BY_NAME = {m.name: m for m in LADDER}

FPS = 50   # every machine is PAL: frames of a run to seconds


AGA_RELEASE = "1992-10"   # the A1200 and A4000 shipped


def predates_aga(release_date):
    """Was the production released before the AGA machines? A bare year or
    an unknown date is never judged early (1992 spans the release)."""
    if not release_date:
        return False
    if len(release_date) < 7:
        return release_date < AGA_RELEASE[:4]
    return release_date < AGA_RELEASE


def ladder_for(aga_only, rom_dir=None, release_date=None, start=None):
    """The machines to try, in order. AGA-only productions start at the AGA
    rungs and only then try the OCS ones: Demozoo's platform tag can be
    wrong (Bliss Out, tagged AGA, runs on an A500 and not under KS3.0).
    Productions that predate AGA skip the 030/060 rungs: of the ~1650 that
    fail everywhere they cost two runs each, and 8 variants only worked
    there. ``start`` names a machine already known to work: the rungs
    before it are not tried again."""
    early = predates_aga(release_date)
    rungs = [m for m in LADDER
             if (not m.optional or rom_path(m, rom_dir).is_file())
             and not (early and m.aga_era)]
    if aga_only:
        rungs = [m for m in rungs if m.aga] + [m for m in rungs if not m.aga]
    first = next((i for i, m in enumerate(rungs) if m.name == start), 0)
    return rungs[first:]


def rom_path(machine, rom_dir=None):
    """Where the machine's Kickstart ROM is kept."""
    return (rom_dir or config.ROM_DIR) / machine.rom


def require_rom(machine, rom_dir=None):
    """Raise unless the machine's Kickstart ROM is there: without one the
    emulator still starts, and the run reads as a production doing nothing."""
    path = rom_path(machine, rom_dir)
    if not path.is_file():
        raise CannotPlay(f"no Kickstart ROM {machine.rom} for {machine.name}"
                         f" in {path.parent}")


def require_roms(rom_dir=None):
    """Raise unless every ROM the ladder cannot do without is there."""
    for m in LADDER:
        if not m.optional:
            require_rom(m, rom_dir)


def uae_text(machine):
    return _HEADLESS + machine.uae
