import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.amiga import replay
from scenemeta.amiga.emulator import Sample
from scenemeta.amiga.errors import CannotPlay


def samples(spec):
    """spec: ``(frame, last_dma, head cylinder of DF0)`` per sample."""
    return [Sample(frame=f, pc=0, dmacon=0, bplcon0=0, resets=0, df0="",
                   shot="", last_dma=dma, cyls=[cyl]) for f, dma, cyl in spec]


class ActionsTest(unittest.TestCase):
    ENTRY = {"disks": ["a.adf", "b.adf", "c.adf"],
             "swaps": [{"disk": 2, "at": 66.1, "key": "lmb"},
                       {"disk": 3, "at": 120.0}]}

    def test_as_written(self):
        # The key goes down 5 s after its insert.
        self.assertEqual(replay.actions(self.ENTRY), [
            (3305, "insert", 0), (3555, "click", 0), (6000, "insert", 1)])

    def test_without_the_keys(self):
        self.assertEqual(replay.actions(self.ENTRY, keys=False),
                         [(3305, "insert", 0), (6000, "insert", 1)])

    def test_key_delay(self):
        entry = {"swaps": [{"disk": 2, "at": 10, "key": "lmb", "key_delay": 1.5}]}
        self.assertEqual(replay.actions(entry),
                         [(500, "insert", 0), (575, "click", 0)])

    def test_disks_in_the_other_drives_are_not_on_the_swap_list(self):
        # With two drives disk 3 is the first one swapped in.
        entry = {"drives": 2, "swaps": [{"disk": 3, "at": 10}]}
        self.assertEqual(replay.actions(entry), [(500, "insert", 0)])

    def test_keys_of_their_own(self):
        # No disk goes in; the entry's keys come in time order.
        entry = {"keys": [{"at": 90, "key": "lmb"}, {"at": 10, "key": "lmb"}]}
        self.assertEqual(replay.actions(entry),
                         [(500, "click", 0), (4500, "click", 0)])
        self.assertEqual(replay.actions(entry, keys=False), [])

    def test_a_key_it_cannot_press_is_an_error_naming_the_key(self):
        entry = {"swaps": [{"disk": 2, "at": 10, "key": "space"}]}
        with self.assertRaisesRegex(CannotPlay, "'space'"):
            replay.actions(entry)
        entry = {"keys": [{"at": 10, "key": "return"}]}
        with self.assertRaisesRegex(CannotPlay, "'return'"):
            replay.actions(entry)


class LoadedTest(unittest.TestCase):
    def test_disk_read_past_its_first_cylinders(self):
        s = samples([(3251, 2834, 40), (3501, 3400, 0), (3751, 3700, 12)])
        self.assertEqual(replay.loaded(s, [3305]), [True])

    def test_id_check_alone_is_not_a_load(self):
        # Odyssey reads the new disk's ID at cylinder 0, then waits for the
        # mouse button.
        s = samples([(3251, 2834, 40), (3501, 3400, 0), (3751, 3400, 0)])
        self.assertEqual(replay.loaded(s, [3305]), [False])

    def test_disk_nobody_looked_at(self):
        # The head still sits where disk 1 left it.
        s = samples([(3251, 2834, 40), (3501, 2834, 40), (3751, 2834, 40)])
        self.assertEqual(replay.loaded(s, [3305]), [False])

    def test_each_disk_is_judged_until_the_next_goes_in(self):
        s = samples([(1001, 900, 30), (1251, 900, 30),      # disk 2: ignored
                     (2001, 1900, 0), (2251, 2200, 20)])    # disk 3: loaded
        self.assertEqual(replay.loaded(s, [1000, 1500]), [False, True])


class JudgeTest(unittest.TestCase):
    def test_loads_without_its_keys(self):
        self.assertEqual(replay.judge([True], [True]), "keys not needed")

    def test_loads_only_with_its_keys(self):
        self.assertEqual(replay.judge([True, True], [False, True]), "keys needed")

    def test_does_not_load_as_written(self):
        self.assertEqual(replay.judge([False], [False]), "does not replay")

    def test_entry_without_keys(self):
        self.assertEqual(replay.judge([True], None), "replays")
        self.assertEqual(replay.judge([False], None), "does not replay")


class VariantOfTest(unittest.TestCase):
    HD = replay.media.Variant("hd", [], root="/r", command='"demo.exe"\n',
                              note="2 executables, picked demo.exe")
    PLAIN = replay.media.Variant("hd", [], root="/p", command='"only"\n')
    ADF = replay.media.Variant("floppy", ["/d/a.adf"])
    SET = replay.media.Variant("floppy", ["/d/a.adf", "/d/b.adf"])

    def pick(self, variants, entry, problems=()):
        with mock.patch.object(replay.media, "variants",
                               return_value=(variants, list(problems))):
            return replay.variant_of(1, {"title": "x", **entry})

    def test_an_entry_naming_its_disks_gets_that_set(self):
        got = self.pick([self.ADF, self.SET], {"disks": ["a.adf", "b.adf"]})
        self.assertIs(got, self.SET)

    def test_an_entry_naming_its_run_file_gets_the_variant_that_runs_it(self):
        # As the export writes it: the picked executable, unquoted.
        self.assertIs(self.pick([self.ADF, self.PLAIN, self.HD],
                                {"run": "demo.exe"}), self.HD)

    def test_an_entry_naming_nothing_gets_the_first_variant(self):
        self.assertIs(self.pick([self.HD, self.ADF], {}), self.HD)

    def test_boot_names_the_kind_when_it_is_not_the_first(self):
        self.assertIs(self.pick([self.HD, self.ADF], {"boot": "floppy"}),
                      self.ADF)

    def test_disks_that_match_no_variant_are_an_error_not_another_variant(self):
        with self.assertRaisesRegex(CannotPlay, "c.adf"):
            self.pick([self.ADF, self.SET, self.HD],
                      {"disks": ["a.adf", "c.adf"]})

    def test_a_run_that_matches_no_variant_is_an_error_not_another_variant(self):
        with self.assertRaisesRegex(CannotPlay, "other.exe"):
            self.pick([self.HD, self.PLAIN, self.ADF], {"run": "other.exe"})

    def test_a_boot_kind_the_download_has_none_of_is_an_error(self):
        with self.assertRaisesRegex(CannotPlay, "floppy"):
            self.pick([self.HD], {"boot": "floppy"})

    def test_no_media_is_its_own_error(self):
        with self.assertRaisesRegex(CannotPlay, "no media: no-files-on-nas"):
            self.pick([], {"disks": ["a.adf"]}, ["no-files-on-nas"])


class ReportTest(unittest.TestCase):
    ENTRY = {"title": "x", "swaps": [{"disk": 2, "at": 10, "key": "space"}]}

    def test_an_entry_that_cannot_be_played_is_an_error_and_nothing_runs(self):
        with mock.patch.object(replay, "variant_of"), \
                mock.patch.object(replay.emulator, "run") as run:
            ok, line = replay._one(7, self.ENTRY, "a500")
        self.assertFalse(ok)
        self.assertEqual(line, "7 x: error: no way to press key 'space'")
        run.assert_not_called()

    def test_the_run_counts_its_errors(self):
        lines = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(replay, "entries",
                                  return_value={7: self.ENTRY}), \
                mock.patch.object(replay, "default_machine",
                                  return_value="a500"), \
                mock.patch.object(replay, "variant_of"), \
                mock.patch.object(replay.emulator, "run") as run:
            errors = replay.run(data=pathlib.Path(d), jobs=1,
                                log=lambda line, **kw: lines.append(line))
        self.assertEqual(errors, 1)
        self.assertEqual(len(lines), 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
