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
events = [{ at = 536.9, disk = 2 }, { at = 541.9, key = "lmb" }]

[demozoo.4321]
title = "Dream On"
source = "ai"
csdb = 77
machine = "a1200"
fast = "4M"
assign = { Killer = "SYS:" }
events = [{ at = 60.9, key = "space" }]
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

    def test_run_may_name_a_launcher_script(self):
        for run in ("Megademo$C.bat", "Scum/Utmost.exe", "RunMe"):
            self.assertEqual(self.one(
                f'[demozoo.5]\ntitle = "Dz"\nsource = "ai"\nrun = "{run}"\n'), [])

    def test_missing_title_and_source(self):
        self.assertEqual(self.problems({"d.toml": "[demozoo.1]\n"}),
                         ["[demozoo.1] needs title", "[demozoo.1] needs source"])

    def test_bad_source(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "human"\n')
        self.assertEqual(got, ["[demozoo.5] source must be one of script, ai, verified"])

    def test_an_area_is_a_width_and_a_height(self):
        entry = '[demozoo.5]\ntitle = "Dz"\nsource = "ai"\narea = %s\n'
        self.assertEqual(self.one(entry % "[320, 180]" + 'aspect = "16:9"\n'), [])
        for bad in ("[320]", "[320, 0]", '"320x180"', "[320.0, 180]"):
            self.assertEqual(self.one(entry % bad), [
                "[demozoo.5] area must be [width, height] in pixels"], bad)

    def test_an_aspect_is_one_of_the_known(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\n'
                       'area = [320, 200]\naspect = "4:3"\n')
        self.assertEqual(got, ["[demozoo.5] aspect must be one of 16:9"])

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

    def event(self, events):
        return self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\n'
                        f'events = [{events}]\n')

    def test_event_needs_time(self):
        self.assertEqual(self.event("{ disk = 2 }"),
                         ["[demozoo.5] events needs at"])

    def test_event_is_a_disk_or_a_key(self):
        said = ["[demozoo.5] events an event is a disk or a key, one of them"]
        self.assertEqual(self.event("{ at = 9.0 }"), said)
        self.assertEqual(self.event('{ at = 9.0, disk = 2, key = "lmb" }'), said)

    def test_only_a_disk_has_a_drive(self):
        self.assertEqual(self.event('{ at = 9.0, key = "lmb", drive = 2 }'),
                         ["[demozoo.5] events drive is of a disk"])

    def test_a_key_has_a_window_as_a_disk_has(self):
        self.assertEqual(self.event('{ at = 9.0, until = 12.0, key = "lmb" }'),
                         [])
        self.assertEqual(self.event('{ at = 9.0, until = 3.0, key = "lmb" }'),
                         ["[demozoo.5] events until is before at"])

    def test_an_event_may_wait_for_ever(self):
        self.assertEqual(self.event("{ at = 9.0, until = inf, disk = 2 }"), [])
        self.assertEqual(self.event("{ at = 9.0, until = nan, disk = 2 }"),
                         ["[demozoo.5] events until must be a time in seconds"])

    def test_events_are_in_the_order_they_happen(self):
        self.assertEqual(
            self.event('{ at = 9.0, disk = 2 }, { at = 9.0, key = "lmb" }'), [])
        said = ["[demozoo.5] events must be in the order they happen, a disk"
                " before a key of the same moment"]
        self.assertEqual(
            self.event('{ at = 9.0, key = "lmb" }, { at = 8.9, disk = 2 }'),
            said)
        self.assertEqual(
            self.event('{ at = 9.0, key = "lmb" }, { at = 9.0, disk = 2 }'),
            said)

    def test_a_key_has_no_delay(self):
        self.assertEqual(self.event('{ at = 9.0, key = "lmb", key_delay = 2 }'),
                         ["[demozoo.5] events unknown field key_delay"])

    def test_swaps_and_keys_are_not_fields(self):
        got = self.one('[demozoo.5]\ntitle = "Dz"\nsource = "ai"\n'
                       'swaps = [{ disk = 2, at = 9.0 }]\n'
                       'keys = [{ at = 3.0, key = "lmb" }]\n')
        self.assertEqual(sorted(got), ["[demozoo.5] unknown field keys",
                                       "[demozoo.5] unknown field swaps"])

    def test_swap_drive_is_a_later_drive(self):
        def one(drive):
            return self.event(f"{{ at = 9.0, disk = 3, drive = {drive} }}")
        self.assertEqual(one(2), [])
        self.assertEqual(one(1), ["[demozoo.5] events drive must be a whole"
                                  " number, 2 or more"])

    def test_swap_window_backwards(self):
        got = self.event("{ at = 9.0, disk = 2, until = 3.0 }")
        self.assertEqual(got, ["[demozoo.5] events until is before at"])

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
