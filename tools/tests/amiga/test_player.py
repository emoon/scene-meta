import pathlib
import unittest
from unittest import mock

from scenemeta.amiga import machines, player
from scenemeta.amiga.emulator import RunLog, Sample
from scenemeta.core.errors import CannotPlay


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
        self.assertEqual(player.actions(self.ENTRY), [
            (3305, "insert", 0), (3555, "click", 0), (6000, "insert", 1)])

    def test_without_the_keys(self):
        self.assertEqual(player.actions(self.ENTRY, keys=False),
                         [(3305, "insert", 0), (6000, "insert", 1)])

    def test_key_delay(self):
        entry = {"swaps": [{"disk": 2, "at": 10, "key": "lmb", "key_delay": 1.5}]}
        self.assertEqual(player.actions(entry),
                         [(500, "insert", 0), (575, "click", 0)])

    def test_disks_in_the_other_drives_are_not_on_the_swap_list(self):
        # With two drives disk 3 is the first one swapped in.
        entry = {"drives": 2, "swaps": [{"disk": 3, "at": 10}]}
        self.assertEqual(player.actions(entry), [(500, "insert", 0)])

    def test_keys_of_their_own(self):
        # No disk goes in; the entry's keys come in time order.
        entry = {"keys": [{"at": 90, "key": "lmb"}, {"at": 10, "key": "lmb"}]}
        self.assertEqual(player.actions(entry),
                         [(500, "click", 0), (4500, "click", 0)])
        self.assertEqual(player.actions(entry, keys=False), [])

    def test_a_key_it_cannot_press_is_an_error_naming_the_key(self):
        entry = {"swaps": [{"disk": 2, "at": 10, "key": "space"}]}
        with self.assertRaisesRegex(CannotPlay, "'space'"):
            player.actions(entry)
        entry = {"keys": [{"at": 10, "key": "return"}]}
        with self.assertRaisesRegex(CannotPlay, "'return'"):
            player.actions(entry)


class LoadedTest(unittest.TestCase):
    def test_disk_read_past_its_first_cylinders(self):
        s = samples([(3251, 2834, 40), (3501, 3400, 0), (3751, 3700, 12)])
        self.assertEqual(player.loaded(s, [3305]), [True])

    def test_id_check_alone_is_not_a_load(self):
        # Odyssey reads the new disk's ID at cylinder 0, then waits for the
        # mouse button.
        s = samples([(3251, 2834, 40), (3501, 3400, 0), (3751, 3400, 0)])
        self.assertEqual(player.loaded(s, [3305]), [False])

    def test_disk_nobody_looked_at(self):
        # The head still sits where disk 1 left it.
        s = samples([(3251, 2834, 40), (3501, 2834, 40), (3751, 2834, 40)])
        self.assertEqual(player.loaded(s, [3305]), [False])

    def test_each_disk_is_judged_until_the_next_goes_in(self):
        s = samples([(1001, 900, 30), (1251, 900, 30),      # disk 2: ignored
                     (2001, 1900, 0), (2251, 2200, 20)])    # disk 3: loaded
        self.assertEqual(player.loaded(s, [1000, 1500]), [False, True])


class VariantOfTest(unittest.TestCase):
    HD = player.media.Variant("hd", [], root="/r", command='"demo.exe"\n',
                              note="2 executables, picked demo.exe")
    PLAIN = player.media.Variant("hd", [], root="/p", command='"only"\n')
    ADF = player.media.Variant("floppy", ["/d/a.adf"])
    SET = player.media.Variant("floppy", ["/d/a.adf", "/d/b.adf"])

    def pick(self, variants, entry, problems=()):
        with mock.patch.object(player.media, "variants",
                               return_value=(variants, list(problems))):
            return player._variant_of(1, {"title": "x", **entry})

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


class FramesTest(unittest.TestCase):
    def test_an_entry_with_nothing_to_do_gets_the_fixed_time(self):
        self.assertEqual(player.frames_of({"title": "x"}), player.PLAIN_FRAMES)

    def test_a_set_plays_until_its_last_disk_has_loaded(self):
        entry = {"swaps": [{"disk": 2, "at": 100}]}
        self.assertEqual(player.frames_of(entry), 5000 + player.TAIL_FRAMES)


class PlayTest(unittest.TestCase):
    SET = player.media.Variant("floppy", ["/d/a.adf", "/d/b.adf"])
    ENTRY = {"title": "x", "machine": "a1200", "drives": 1,
             "disks": ["a.adf", "b.adf"],
             "swaps": [{"disk": 2, "at": 20, "key": "lmb"}]}
    # Disk 2 goes in at frame 1000 and is read past its first cylinders.
    LOG = RunLog(samples([(750, 700, 40), (1250, 1100, 12)]), [], 0, False, "")

    def play(self, entry, default="a500", **kw):
        with mock.patch.object(player.media, "variants",
                               return_value=([self.SET], [])), \
                mock.patch.object(player.emulator, "run",
                                  return_value=self.LOG) as run:
            return player.play(7, entry, default, **kw), run

    def test_the_entry_is_played_as_written_with_the_detector_off(self):
        out, run = self.play(self.ENTRY)
        machine, variant, frames, opts = run.call_args.args
        self.assertIs(machine, machines.BY_NAME["a1200"])
        self.assertIs(variant, self.SET)
        self.assertEqual(frames, 1250 + player.TAIL_FRAMES)
        self.assertEqual(opts.play, ((1000, "insert", 0), (1250, "click", 0)))
        self.assertFalse(opts.detects)
        self.assertEqual((out.machine, out.loaded), ("a1200", [True]))
        self.assertIs(out.log, self.LOG)
        self.assertEqual(out.verdict.verdict, "no-activity")

    def test_without_keys_runs_as_long_and_presses_nothing(self):
        _, run = self.play(self.ENTRY, keys=False)
        _, _, frames, opts = run.call_args.args
        self.assertEqual(frames, 1250 + player.TAIL_FRAMES)
        self.assertEqual(opts.play, ((1000, "insert", 0),))

    def test_an_entry_with_nothing_to_do_still_runs_undetected(self):
        out, run = self.play({"title": "x", "disks": ["a.adf", "b.adf"]})
        machine, _, frames, opts = run.call_args.args
        self.assertIs(machine, machines.BY_NAME["a500"])   # the default
        self.assertEqual(frames, player.PLAIN_FRAMES)
        self.assertFalse(opts.detects)
        self.assertEqual(out.loaded, [])

    def test_the_pictures_go_where_the_caller_keeps_them(self):
        keep = pathlib.Path("/shots")
        _, run = self.play(self.ENTRY, keep=keep)
        self.assertEqual(run.call_args.args[3].keep, keep)

    def test_what_cannot_be_played_is_an_error_and_nothing_runs(self):
        entry = {**self.ENTRY, "swaps": [{"disk": 2, "at": 10, "key": "space"}]}
        with mock.patch.object(player.media, "variants",
                               return_value=([self.SET], [])), \
                mock.patch.object(player.emulator, "run") as run:
            with self.assertRaisesRegex(CannotPlay, "'space'"):
                player.play(7, entry, "a500")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
