import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.amiga import player, replay
from scenemeta.core.errors import CannotPlay
from scenemeta.amiga.verdict import Verdict


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


class ReportTest(unittest.TestCase):
    ENTRY = {"title": "x", "swaps": [{"disk": 2, "at": 10, "key": "space"}]}
    ADF = player.media.Variant("floppy", ["/d/a.adf", "/d/b.adf"])

    def setUp(self):
        for needed in ((player.machines, "require_rom"),
                       (player.media, "require_mirror")):
            patch = mock.patch.object(*needed)
            patch.start()
            self.addCleanup(patch.stop)

    def test_an_entry_that_cannot_be_played_is_an_error_and_nothing_runs(self):
        with mock.patch.object(player.media, "variants",
                                  return_value=([self.ADF], [])), \
                mock.patch.object(player.emulator, "run") as run:
            with self.assertRaisesRegex(CannotPlay, "'space'"):
                replay._one(7, self.ENTRY, "a500")
        run.assert_not_called()

    def outcome(self, verdict, loaded):
        return player.Outcome("a500", Verdict(verdict, 0), loaded, None)

    def test_an_entry_with_keys_is_played_again_without_them(self):
        entry = {"title": "x", "swaps": [{"disk": 2, "at": 10, "key": "lmb"}]}
        with mock.patch.object(player, "play", side_effect=[
                self.outcome("works", [True]),
                self.outcome("works", [False])]) as play:
            line = replay._one(7, entry, "a500")
        self.assertEqual(line, "7 x: keys needed (as written: works, disks"
                         " loaded y; without keys: works, disks loaded n)")
        self.assertEqual([c.kwargs for c in play.call_args_list],
                         [{}, {"keys": False}])

    def test_with_no_disk_to_put_in_the_run_itself_is_the_evidence(self):
        entry = {"title": "x", "keys": [{"at": 10, "key": "lmb"}]}
        with mock.patch.object(player, "play", side_effect=[
                self.outcome("works", []), self.outcome("crash", [])]):
            line = replay._one(7, entry, "a500")
        self.assertEqual(line, "7 x: keys needed (as written: works, disks"
                         " loaded y; without keys: crash, disks loaded n)")

    def test_an_entry_without_keys_is_played_once(self):
        entry = {"title": "x", "swaps": [{"disk": 2, "at": 10}]}
        with mock.patch.object(player, "play", return_value=self.outcome(
                "works-then-crash", [False])) as play:
            line = replay._one(7, entry, "a500")
        self.assertEqual(line, "7 x: does not replay (as written:"
                         " works-then-crash, disks loaded n)")
        play.assert_called_once_with(7, entry, "a500")

    def test_the_run_counts_its_errors(self):
        lines = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(replay, "entries",
                                  return_value={7: self.ENTRY}), \
                mock.patch.object(replay, "default_machine",
                                  return_value="a500"), \
                mock.patch.object(player.media, "variants",
                                  return_value=([self.ADF], [])), \
                mock.patch.object(player.emulator, "run") as run:
            errors = replay.run(data=pathlib.Path(d), jobs=1,
                                log=lambda line, **kw: lines.append(line))
        self.assertEqual(errors, 1)
        self.assertEqual(lines, ["7 x: error: no way to press key 'space'"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
