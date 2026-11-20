import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.amiga import machines, player
from scenemeta.amiga.emulator import RunLog, Sample
from scenemeta.amiga.verdict import Verdict
from scenemeta.core.errors import BadEntry, CannotPlay
from scenemeta.core.gate import Play, SwapTaken


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
        entry = {"disks": ["a", "b"],
                 "swaps": [{"disk": 2, "at": 10, "key": "lmb", "key_delay": 1.5}]}
        self.assertEqual(player.actions(entry),
                         [(500, "insert", 0), (575, "click", 0)])

    def test_disks_in_the_other_drives_are_not_on_the_swap_list(self):
        # With two drives disk 3 is the first one swapped in.
        entry = {"drives": 2, "disks": ["a", "b", "c"],
                 "swaps": [{"disk": 3, "at": 10}]}
        self.assertEqual(player.actions(entry), [(500, "insert", 0)])

    def test_a_disk_that_cannot_go_in_is_an_error_not_another_disk(self):
        def swap(disk, **entry):
            return {"disks": ["a", "b", "c"], **entry,
                    "swaps": [{"disk": disk, "at": 10}]}
        # Disk 1 sits in the drive, and with two drives so does disk 2.
        with self.assertRaisesRegex(BadEntry, "disk 1: .* are 2 to 3"):
            player.actions(swap(1))
        with self.assertRaisesRegex(BadEntry, "disk 2: .* are 3 to 3"):
            player.actions(swap(2, drives=2))
        with self.assertRaisesRegex(BadEntry, "disk 4: .* are 2 to 3"):
            player.actions(swap(4))
        # One disk, or a hard drive: nothing to swap.
        with self.assertRaisesRegex(BadEntry, "disk 2: there is none"):
            player.actions({"swaps": [{"disk": 2, "at": 10}]})

    def test_keys_of_their_own(self):
        # No disk goes in; the entry's keys come in time order.
        entry = {"keys": [{"at": 90, "key": "lmb"}, {"at": 10, "key": "lmb"}]}
        self.assertEqual(player.actions(entry),
                         [(500, "click", 0), (4500, "click", 0)])
        self.assertEqual(player.actions(entry, keys=False), [])

    def test_a_key_it_cannot_press_is_an_error_naming_the_key(self):
        entry = {"disks": ["a", "b"],
                 "swaps": [{"disk": 2, "at": 10, "key": "space"}]}
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
                              run="demo.exe", choice=True)
    PLAIN = player.media.Variant("hd", [], root="/p", command='"only"\n',
                                 run="only")
    ADF = player.media.Variant("floppy", ["/d/a.adf"])
    SET = player.media.Variant("floppy", ["/d/a.adf", "/d/b.adf"])
    # What a sweep makes of a variant that does not work as it is.
    LAUNCH = player.media.Variant("floppy", ["/w/a-launch.adf"],
                                  run="c/demo", choice=True)
    MERGED = player.media.Variant("hd", [], root="/m", command='"demo"\n',
                                  run="demo", choice=True)
    ON_FLOPPY = player.media.Variant("floppy", ["/w/disk.adf"], run="only")

    def pick(self, variants, entry, problems=(), fallbacks=(), forced=None):
        """The variant of ``entry``. ``fallbacks`` are the other ways to run
        the first of ``variants`` (None: one that cannot be made);
        ``forced`` is what the media gives when asked to start a file."""
        self.made = []

        def others(v, *_):
            return [(f.kind if f else "floppy",
                     lambda f=f: self.made.append(f) or f)
                    for f in fallbacks] if v is variants[0] else []

        def found(prod, title, run):
            return (forced if run and forced else variants), list(problems)

        with mock.patch.object(player.media, "variants",
                               side_effect=found) as self.found, \
                mock.patch.object(player.media, "fallbacks",
                                  side_effect=others) as self.others:
            return player._variant_of(1, {"title": "x", **entry})

    def test_an_entry_naming_its_disks_gets_that_set(self):
        got = self.pick([self.ADF, self.SET], {"disks": ["a.adf", "b.adf"]})
        self.assertIs(got, self.SET)

    def test_an_entry_naming_its_run_file_gets_the_variant_that_runs_it(self):
        # As the export writes it: the picked executable, unquoted.
        self.assertIs(self.pick([self.ADF, self.PLAIN, self.HD],
                                {"boot": "hd", "run": "demo.exe"}), self.HD)

    def test_the_run_file_is_what_the_media_is_asked_to_start(self):
        # When it is not the executable picked today.
        today = player.media.Variant("hd", [], root="/r", run="main.exe",
                                     choice=True)
        self.assertIs(self.pick([today], {"run": "demo.exe"},
                                forced=[self.HD]), self.HD)
        self.assertEqual([c.args for c in self.found.call_args_list],
                         [(1, "x", None), (1, "x", "demo.exe")])

    def test_the_media_is_not_asked_when_todays_pick_is_the_run_file(self):
        # Asked to start it, the outer archive's tree would start it too.
        outer = player.media.Variant("hd", [], root="/o", run="main.exe",
                                     choice=True)
        forced = [self.HD, player.media.Variant(
            "hd", [], root="/o", run="demo.exe", choice=True)]
        self.assertIs(self.pick([self.HD, outer], {"run": "demo.exe"},
                                forced=forced), self.HD)
        self.found.assert_called_once_with(1, "x", None)

    def test_an_entry_may_say_more_than_an_export_would(self):
        # The only executable, the kind of the first variant, the one disk.
        self.assertIs(self.pick([self.PLAIN], {"run": "only"}), self.PLAIN)
        self.assertIs(self.pick([self.PLAIN], {"boot": "hd"}), self.PLAIN)
        self.assertIs(self.pick([self.ADF], {"disks": ["a.adf"]}), self.ADF)

    def test_one_disk_of_two_is_the_one_the_entry_names(self):
        other = player.media.Variant("floppy", ["/d/b.adf"])
        self.assertIs(self.pick([self.ADF, other], {"disks": ["b.adf"]}),
                      other)

    def test_an_entry_naming_nothing_gets_the_variant_with_nothing_to_name(self):
        self.assertIs(self.pick([self.PLAIN, self.HD, self.SET], {}),
                      self.PLAIN)

    def test_boot_names_the_kind_when_it_is_not_the_first(self):
        self.assertIs(self.pick([self.PLAIN, self.ADF], {"boot": "floppy"}),
                      self.ADF)

    def test_a_run_of_another_kind_is_not_the_entrys(self):
        # The floppy that runs demo is not the hard drive that does.
        launch = player.media.Variant("floppy", ["/w/a-launch.adf"],
                                      run="demo", choice=True)
        merged = self.MERGED
        self.assertIs(self.pick([launch, merged],
                                {"boot": "hd", "run": "demo"}), merged)
        self.assertIs(self.pick([launch, merged], {"run": "demo"}), launch)

    def test_an_entry_of_a_sweeps_fallback_gets_that_fallback(self):
        every = [self.LAUNCH, self.MERGED, self.ON_FLOPPY]
        self.assertIs(self.pick([self.SET, self.PLAIN], {"run": "c/demo"},
                                fallbacks=every), self.LAUNCH)
        self.assertIs(self.pick([self.SET, self.PLAIN],
                                {"boot": "hd", "run": "demo"},
                                fallbacks=every), self.MERGED)
        self.assertIs(self.pick([self.PLAIN], {"boot": "floppy"},
                                fallbacks=every), self.ON_FLOPPY)
        self.others.assert_called_with(self.PLAIN, 1, "x", None)

    def test_only_fallbacks_of_the_entrys_kind_are_made(self):
        every = [self.LAUNCH, self.MERGED, self.ON_FLOPPY]
        self.pick([self.SET, self.PLAIN], {"boot": "hd", "run": "demo"},
                  fallbacks=every)
        self.assertEqual(self.made, [self.MERGED])

    def test_a_fallback_told_apart_by_its_file_is_not_the_disk_that_boots(self):
        # As an export writes it when both are there (see media.named).
        on_floppy = player.media.Variant("floppy", ["/w/disk.adf"],
                                         run="demo.exe")
        self.assertIs(self.pick([self.ADF, self.HD], {"run": "demo.exe"},
                                fallbacks=[on_floppy]), on_floppy)

    def test_no_fallback_is_made_when_a_variant_of_the_download_fits(self):
        self.pick([self.ADF, self.PLAIN], {}, fallbacks=[self.ON_FLOPPY])
        self.others.assert_not_called()

    def test_disks_that_match_no_variant_are_an_error_not_another_variant(self):
        with self.assertRaisesRegex(BadEntry, "c.adf.*fits none"):
            self.pick([self.ADF, self.SET, self.HD],
                      {"disks": ["a.adf", "c.adf"]})

    def test_a_run_that_matches_no_variant_is_an_error_not_another_variant(self):
        with self.assertRaisesRegex(BadEntry, "other.exe.*fits none"):
            self.pick([self.HD, self.PLAIN, self.ADF], {"run": "other.exe"})

    def test_a_boot_kind_the_download_has_none_of_is_an_error(self):
        with self.assertRaisesRegex(BadEntry, "floppy"):
            self.pick([self.HD], {"boot": "floppy"})

    def test_an_entry_that_fits_two_variants_is_an_error_not_the_first(self):
        other = player.media.Variant("floppy", ["/d/b.adf"])
        with self.assertRaisesRegex(BadEntry, "fits 2 .*a.adf, b.adf"):
            self.pick([self.ADF, other], {})

    def test_no_fit_in_a_download_that_did_not_all_unpack_is_not_the_entrys(self):
        # An archive that timed out today may hold the variant: the entry
        # is not filed as one that cannot be played.
        with self.assertRaisesRegex(
                CannotPlay, "fits none.*x.lha: unpack-error") as e:
            self.pick([self.ADF], {"boot": "hd"},
                      ["x.lha: unpack-error:TimeoutExpired"])
        self.assertNotIsInstance(e.exception, BadEntry)
        # Nor when another way to run a variant could not be made.
        with self.assertRaisesRegex(
                CannotPlay, "fits none.*a.adf: no other floppy") as e:
            self.pick([self.ADF], {"run": "demo"}, fallbacks=[None])
        self.assertNotIsInstance(e.exception, BadEntry)

    def test_no_media_is_its_own_error(self):
        with self.assertRaisesRegex(CannotPlay, "no media: no-files-on-nas") as e:
            self.pick([], {"disks": ["a.adf"]}, ["no-files-on-nas"])
        self.assertNotIsInstance(e.exception, BadEntry)


class FramesTest(unittest.TestCase):
    def test_an_entry_with_nothing_to_do_gets_the_fixed_time(self):
        self.assertEqual(player.frames_of({"title": "x"}), player.PLAIN_FRAMES)

    def test_a_set_plays_until_its_last_disk_has_loaded(self):
        entry = {"disks": ["a", "b"], "swaps": [{"disk": 2, "at": 100}]}
        self.assertEqual(player.frames_of(entry), 5000 + player.TAIL_FRAMES)


class PlayTest(unittest.TestCase):
    SET = player.media.Variant("floppy", ["/d/a.adf", "/d/b.adf"])
    ENTRY = {"title": "x", "machine": "a1200", "drives": 1,
             "disks": ["a.adf", "b.adf"],
             "swaps": [{"disk": 2, "at": 20, "key": "lmb"}]}
    # Disk 2 goes in at frame 1000 and is read past its first cylinders.
    LOG = RunLog(samples([(750, 700, 40), (1250, 1100, 12)]), [], 0, False, "")

    def setUp(self):
        rom = mock.patch.object(player.machines, "require_rom")
        self.require_rom = rom.start()
        self.addCleanup(rom.stop)

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

    def test_the_run_is_reported_as_the_record_of_every_platform(self):
        out, _ = self.play(self.ENTRY)
        self.assertEqual(out.record,
                         Play(False, None, (SwapTaken(2, True),), far=22.0))

    def test_how_far_is_the_last_read_of_a_disk(self):
        self.assertEqual(player.last_read(samples([(250, 240, 0), (500, 240, 0)])),
                         4.8)
        self.assertLess(player.last_read([]), 0)

    def test_the_record_numbers_a_disk_as_the_entry_does(self):
        entry = {**self.ENTRY, "drives": 2, "disks": ["a.adf", "b.adf", "c.adf"],
                 "swaps": [{"disk": 3, "at": 20}]}
        with mock.patch.object(player.media, "variants", return_value=(
                [player.media.Variant("floppy", ["/d/a.adf", "/d/b.adf",
                                                 "/d/c.adf"])], [])), \
                mock.patch.object(player.emulator, "run", return_value=self.LOG):
            out = player.play(7, entry, "a500")
        self.assertEqual(out.record.swaps, (SwapTaken(3, True),))

    def test_the_record_says_what_came_alive_and_what_crashed(self):
        def record(verdict, crash=None):
            with mock.patch.object(player.verdict, "classify",
                                   return_value=Verdict(verdict, 0, crash)):
                out, _ = self.play({"title": "x", "disks": ["a.adf", "b.adf"]})
            return out.record
        self.assertEqual(record("works"), Play(True, far=22.0))
        self.assertEqual(record("works-short"), Play(True, far=22.0))
        self.assertEqual(record("works-then-crash", "guru"), Play(True, "guru", far=22.0))
        self.assertEqual(record("crash", "halt"), Play(False, "halt", far=22.0))
        self.assertEqual(record("no-activity"), Play(False, far=22.0))

    def test_without_keys_runs_as_long_and_presses_nothing(self):
        _, run = self.play(self.ENTRY, keys=False)
        _, _, frames, opts = run.call_args.args
        self.assertEqual(frames, 1250 + player.TAIL_FRAMES)
        self.assertEqual(opts.play, ((1000, "insert", 0),))

    def test_a_run_is_as_long_as_the_caller_says(self):
        with mock.patch.object(player.emulator, "run",
                               return_value=self.LOG) as run:
            player.Ready(self.ENTRY, machines.BY_NAME["a500"],
                         self.SET).play(frames=40000)
        self.assertEqual(run.call_args.args[2], 40000)

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

    def test_the_seed_is_the_callers(self):
        _, run = self.play(self.ENTRY)
        self.assertEqual(run.call_args.args[3].seed, player.emulator.DEFAULT_SEED)
        with mock.patch.object(player.emulator, "run",
                               return_value=self.LOG) as run:
            player.Ready(self.ENTRY, machines.BY_NAME["a1200"],
                         self.SET).play(seed=7)
        self.assertEqual(run.call_args.args[3].seed, 7)

    def cannot(self, entry, error, text):
        """Playing ``entry`` raises ``error``; returns the media lookup."""
        with mock.patch.object(player.media, "variants",
                               return_value=([self.SET], [])) as variants, \
                mock.patch.object(player.media, "fallbacks", return_value=[]), \
                mock.patch.object(player.emulator, "run") as run:
            with self.assertRaisesRegex(error, text):
                player.play(7, entry, "a500")
        run.assert_not_called()
        return variants

    def test_what_cannot_be_played_is_an_error_and_nothing_runs(self):
        self.cannot({**self.ENTRY, "disks": ["a.adf", "c.adf"]}, BadEntry,
                    "c.adf")

    def test_a_key_it_cannot_press_is_found_before_the_download_is_unpacked(self):
        entry = {**self.ENTRY, "swaps": [{"disk": 2, "at": 10, "key": "space"}]}
        self.cannot(entry, BadEntry, "'space'").assert_not_called()

    def test_a_machine_it_does_not_have_is_an_error_naming_it(self):
        self.cannot({**self.ENTRY, "machine": "a600"}, BadEntry,
                    "no machine 'a600'").assert_not_called()
        # No default in machines.toml and none in the entry.
        with self.assertRaisesRegex(BadEntry, "no machine None"):
            player.play(7, {"title": "x"}, None)

    def test_a_missing_rom_is_found_before_the_download_is_unpacked(self):
        self.require_rom.side_effect = CannotPlay("no Kickstart ROM kick30.rom")
        self.cannot(self.ENTRY, CannotPlay, "kick30.rom").assert_not_called()
        self.require_rom.assert_called_once_with(machines.BY_NAME["a1200"])


class PlayEachTest(unittest.TestCase):
    def test_each_line_is_logged_and_the_errors_counted(self):
        def one(prod, entry):
            if prod == 2:
                raise BadEntry("no way to press key 'space'")
            return f"{prod} fine"
        lines = []
        with mock.patch.object(player.media, "require_mirror"):
            errors = player.play_each(
                [(1, {"title": "a"}), (2, {"title": "b"})], one, 1,
                lambda line, **kw: lines.append(line))
        self.assertEqual(errors, 1)
        self.assertEqual(lines, ["1 fine",
                                 "2 b: error: no way to press key 'space'"])

    def test_without_the_mirror_nothing_is_played(self):
        one = mock.Mock()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(player.media.config, "DEMOZOO_DIR",
                                  pathlib.Path(d) / "demozoo"):
            with self.assertRaisesRegex(CannotPlay, "no Demozoo mirror at .*demozoo"):
                player.play_each([(1, {"title": "a"})], one, 1)
        one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
