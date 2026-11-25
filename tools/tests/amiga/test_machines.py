import pathlib
import tempfile
import unittest

from scenemeta.amiga import config, machines
from scenemeta.core.errors import CannotPlay
from scenemeta.machines import load


def names(ms):
    return [m.name for m in ms]


class LadderTest(unittest.TestCase):
    def roms(self, *files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        for f in files:
            (d / f).touch()
        return d

    def test_ks12_comes_after_the_ks13_a500s(self):
        d = self.roms("kick12.rom")
        n = names(machines.ladder_for(False, d))
        self.assertEqual(n[:3], ["a500", "a500_1mb", "a500_ks12"])

    def test_ks12_is_skipped_without_its_rom(self):
        n = names(machines.ladder_for(False, self.roms()))
        self.assertNotIn("a500_ks12", n)
        self.assertNotIn("a500_ks12_512k", n)
        self.assertEqual(n[:2], ["a500", "a500_1mb"])

    def test_required_machines_never_depend_on_the_rom_dir(self):
        n = names(machines.ladder_for(False, self.roms()))
        self.assertEqual(n, [m.name for m in machines.LADDER
                             if not m.optional])

    def test_aga_only_tries_aga_first_then_the_a500s(self):
        n = names(machines.ladder_for(True, self.roms("kick12.rom")))
        self.assertEqual(n[0], "a1200")
        self.assertEqual(n[-4:], ["a500_512k", "a500_ks12_512k",
                                  "a500_1mb_chip", "a500_2mb_chip"])

    def test_chip_only_a500_comes_after_the_slow_ram_ones(self):
        # A new rung must not change what already works further down.
        n = names(machines.ladder_for(False, self.roms("kick12.rom")))
        self.assertEqual(n[:5], ["a500", "a500_1mb", "a500_ks12",
                                 "a500_512k", "a500_ks12_512k"])
        text = machines.uae_text(machines.BY_NAME["a500_ks12_512k"])
        self.assertIn("chipmem_size=1\n", text)
        self.assertIn("bogomem_size=0\n", text)
        self.assertEqual(machines.BY_NAME["a500_ks12_512k"].rom, "kick12.rom")

    def test_2m_chip_a500_is_the_last_before_the_a1200s(self):
        n = names(machines.ladder_for(False, self.roms()))
        i = n.index("a500_2mb_chip")
        self.assertEqual(n[i - 1:i + 2], ["a500_1mb_chip", "a500_2mb_chip",
                                          "a1200"])
        text = machines.uae_text(machines.BY_NAME["a500_2mb_chip"])
        self.assertIn("chipmem_size=4\n", text)
        self.assertIn("bogomem_size=0\n", text)
        self.assertIn("cpu_type=68000\n", text)

    def test_every_rung_is_a_preset_an_entry_can_name(self):
        _, presets, problems = load(config.DATA_DIR / "machines.toml")
        self.assertEqual(problems, [])
        self.assertEqual(list(presets), [m.name for m in machines.LADDER])

    def test_pre_aga_productions_skip_the_fast_cpu_rungs(self):
        # 8 of 10,962 pre-AGA variants worked only on the 030/060 rungs; the
        # cost of trying them on the ~1650 that fail everywhere is not worth it.
        d = self.roms("kick12.rom")
        for date in ("1990-05-01", "1992-09-30", "1989"):
            n = names(machines.ladder_for(False, d, date))
            self.assertEqual(n[-2:], ["a1200", "a1200_fast"], date)

    def test_aga_era_and_undated_productions_get_the_whole_ladder(self):
        d = self.roms("kick12.rom")
        full = names(machines.ladder_for(False, d))
        for date in ("1992-10-01", "1992", "1995-01-01", "", None):
            self.assertEqual(names(machines.ladder_for(False, d, date)), full,
                             date)

    def test_aga_only_stays_aga_first(self):
        n = names(machines.ladder_for(True, self.roms(), "1993-01-01"))
        self.assertEqual(n[0], "a1200")


if __name__ == "__main__":
    unittest.main()


class ConfigTest(unittest.TestCase):
    def test_fast_cpus_emulate_unimplemented_instructions(self):
        # Without a 68040/68060.library, instructions the CPU lacks must be
        # emulated, not trap (Step By Step: FPU ops Guru 8000000B).
        for m in machines.LADDER:
            text = machines.uae_text(m)
            self.assertNotIn("no_unimplemented=true", text, m.name)


class StartTest(LadderTest):
    def test_a_known_machine_skips_the_rungs_below_it(self):
        n = names(machines.ladder_for(False, self.roms(), start="a500_512k"))
        self.assertEqual(n[0], "a500_512k")
        self.assertNotIn("a500", n)

    def test_the_rungs_above_a_known_machine_stay(self):
        n = names(machines.ladder_for(False, self.roms(), start="a1200"))
        self.assertEqual(n, ["a1200", "a1200_fast", "a1200_030", "a1200_060"])

    def test_start_follows_the_aga_only_order(self):
        n = names(machines.ladder_for(True, self.roms(), start="a1200_fast"))
        self.assertEqual(n[0], "a1200_fast")
        self.assertIn("a500", n)

    def test_an_unknown_start_changes_nothing(self):
        d = self.roms()
        self.assertEqual(names(machines.ladder_for(False, d, start="nope")),
                         names(machines.ladder_for(False, d)))


class RomTest(unittest.TestCase):
    def roms(self, *files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        for f in files:
            (d / f).touch()
        return d

    def test_a_missing_rom_is_an_error_naming_it_and_where_it_was_sought(self):
        d = self.roms("kick30.rom")
        with self.assertRaises(CannotPlay) as e:
            machines.require_rom(machines.BY_NAME["a500"], d)
        self.assertIn("kick13.rom", str(e.exception))
        self.assertIn(str(d), str(e.exception))

    def test_a_rom_that_is_there_is_fine(self):
        machines.require_rom(machines.BY_NAME["a500"], self.roms("kick13.rom"))

    def test_the_ladder_needs_every_rom_but_the_optional_ones(self):
        machines.require_roms(self.roms("kick13.rom", "kick30.rom"))
        with self.assertRaisesRegex(CannotPlay, "kick30.rom"):
            machines.require_roms(self.roms("kick13.rom", "kick12.rom"))
