import pathlib
import tempfile
import unittest

from scenemeta.amiga import machines


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
        self.assertEqual(n[:2], ["a500", "a500_1mb"])

    def test_required_machines_never_depend_on_the_rom_dir(self):
        n = names(machines.ladder_for(False, self.roms()))
        self.assertEqual(n, [m.name for m in machines.LADDER
                             if m.name != "a500_ks12"])

    def test_aga_only_tries_aga_first_then_the_a500s(self):
        n = names(machines.ladder_for(True, self.roms("kick12.rom")))
        self.assertEqual(n[0], "a1200")
        self.assertEqual(n[-2:], ["a500_ks12", "a500_512k"])

    def test_chip_only_a500_comes_after_the_slow_ram_ones(self):
        # A new rung must not change what already works further down.
        n = names(machines.ladder_for(False, self.roms("kick12.rom")))
        self.assertEqual(n[:4], ["a500", "a500_1mb", "a500_ks12", "a500_512k"])

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
