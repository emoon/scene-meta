import pathlib
import tempfile
import unittest

from scenemeta import machines, schema, validate

MACHINES = """\
default = "a500"

[a500]
description = "A500"
cpu = "68000"
chip = "512K"

[a1200]
description = "A1200"
cpu = "68ec020"
chip = "2M"
fast = "8M"
"""

GOOD = """\
[demozoo.142]
title = "Desert Dream"
group = "Kefrens"
source = "script"
disks = ["DesertDream-A.adf", "DesertDream-B.adf"]
swaps = [{ disk = 2, at = 536.9, key = "lmb" }]

[demozoo.4321]
title = "Dream On"
source = "ai"
csdb = 77
machine = "a1200"
fast = "4M"
assign = { Killer = "SYS:" }
keys = [{ at = 60.9, key = "space" }]
result = "crashes-later"
note = "guru after the end part"

[[demozoo.4321.variant]]
file = "dreamon-fixed.lha"
sha256 = "%s"
machine = "a500"
""" % ("ab" * 32)


class ValidateTest(unittest.TestCase):
    def problems(self, files):
        """Problems of an amiga directory holding ``files`` (name -> text)."""
        with tempfile.TemporaryDirectory() as tmp:
            amiga = pathlib.Path(tmp) / "amiga"
            amiga.mkdir()
            (amiga / "machines.toml").write_text(MACHINES)
            for name, text in files.items():
                (amiga / name).write_text(text)
            return [line.split(": ", 1)[1] for line in validate.check(amiga.parent)]

    def one(self, entry, name="d.toml"):
        """Problems of GOOD with ``entry`` appended (sorts last under d)."""
        return self.problems({name: GOOD + entry})

    def test_good_file_has_no_problems(self):
        self.assertEqual(self.problems({"d.toml": GOOD}), [])

    def test_repo_data_is_valid(self):
        self.assertEqual(validate.check(validate.DATA), [])

    def test_bucket(self):
        self.assertEqual(schema.bucket("Desert Dream"), "d")
        self.assertEqual(schema.bucket("9 Fingers"), "0-9")
        self.assertEqual(schema.bucket("...and so"), "misc")
        self.assertEqual(schema.bucket("Ärtan"), "misc")

    def test_wrong_file(self):
        self.assertEqual(self.problems({"e.toml": '[demozoo.1]\ntitle = "Dx"\nsource = "ai"\n'}),
                         ["[demozoo.1] belongs in d.toml"])

    def test_out_of_order(self):
        got = self.one('[demozoo.5]\ntitle = "Dawn"\nsource = "ai"\n')
        self.assertEqual(got, ["[demozoo.5] is out of order (sorted by title, then ID)"])

    def test_same_title_orders_by_id(self):
        self.assertEqual(self.one('[demozoo.9000]\ntitle = "Dream On"\nsource = "ai"\n'), [])

    def test_missing_title_and_source(self):
        self.assertEqual(self.problems({"d.toml": "[demozoo.1]\n"}),
                         ["[demozoo.1] needs title", "[demozoo.1] needs source"])

    def test_bad_source(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "human"\n')
        self.assertEqual(got, ["[demozoo.5] source must be one of script, ai, verified"])

    def test_unknown_field(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\nemulator = "x"\n')
        self.assertEqual(got, ["[demozoo.5] unknown field emulator"])

    def test_unknown_machine(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\nmachine = "a4000"\n')
        self.assertEqual(got, ["[demozoo.5] machine 'a4000' is not in machines.toml"])

    def test_id_used_twice_across_files(self):
        got = self.problems({"d.toml": GOOD,
                             "e.toml": '[demozoo.142]\ntitle = "Ex"\nsource = "ai"\n'})
        self.assertEqual(got, ["[demozoo.142] demozoo.142 is already in d.toml [demozoo.142]"])

    def test_cross_reference_counts_as_use(self):
        got = self.one('[csdb.77]\ntitle = "Dz"\nsource = "ai"\n')
        self.assertEqual(got, ["[csdb.77] csdb.77 is already in d.toml [demozoo.4321]"])

    def test_swap_needs_time(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\nswaps = [{ disk = 2 }]\n')
        self.assertEqual(got, ["[demozoo.5] swaps needs at"])

    def test_swap_window_backwards(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\n'
                       'swaps = [{ disk = 2, at = 9.0, until = 3.0 }]\n')
        self.assertEqual(got, ["[demozoo.5] swaps until is before at"])

    def test_variant_needs_hash(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\n'
                       '[[demozoo.5.variant]]\nfile = "a.lha"\nsha256 = "abc"\ntitle = "x"\n')
        self.assertEqual(got, ["[demozoo.5] variant sha256 must be 64 lowercase hex digits",
                               "[demozoo.5] variant unknown field title"])

    def test_broken_toml_is_reported(self):
        self.assertEqual(len(self.problems({"d.toml": "[demozoo.1\n"})), 1)

    def test_machines_default_must_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "machines.toml"
            path.write_text('default = "a600"\n[a500]\ncpu = "68000"\n')
            self.assertEqual(machines.load(path)[2], ["default must name a preset"])


if __name__ == "__main__":
    unittest.main()
