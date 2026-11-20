import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from scenemeta.amiga import gate, player
from scenemeta.amiga.store import Store
from scenemeta.amiga.verdict import Verdict
from scenemeta.core.errors import CannotPlay
from scenemeta.core import gate as core
from scenemeta.core.gate import Judgement, Play, Run, SwapTaken


class PlayTest(unittest.TestCase):
    ENTRY = {"title": "x", "disks": ["a.adf", "b.adf"],
             "swaps": [{"disk": 2, "at": 10, "key": "lmb"}]}

    def play(self, run, verdict=Verdict("works", 9)):
        record = Play(True, swaps=(SwapTaken(2, True),))
        outcome = player.Outcome("a500", verdict, [], None, record)
        ready = player.Ready(self.ENTRY, None, None)
        with mock.patch.object(player.Ready, "play", autospec=True,
                               return_value=outcome) as self.played:
            got = gate._play(ready, run)
        self.assertIs(got, record)
        (played,), kw = self.played.call_args
        return played.entry, kw

    def test_a_run_is_the_entry_as_the_gate_changed_it_on_the_runs_seed(self):
        entry, kw = self.play(Run(3, late=True))
        self.assertEqual(entry["swaps"], [{"disk": 2, "at": 40, "key": "lmb"}])
        self.assertEqual(kw["seed"], 3)

    def test_late_runs_as_long_as_its_later_disk_needs(self):
        _, kw = self.play(Run(1, late=True))
        self.assertEqual(kw["frames"], (40 + 5) * 50 + player.TAIL_FRAMES)

    def test_without_a_key_runs_as_long_as_the_entry_as_written(self):
        entry, kw = self.play(Run(1, without=0))
        self.assertEqual(entry["swaps"], [{"disk": 2, "at": 10}])
        self.assertEqual(kw["frames"], (10 + 5) * 50 + player.TAIL_FRAMES)

    def test_an_emulator_that_showed_nothing_is_an_error_not_a_fail(self):
        with self.assertRaisesRegex(CannotPlay, "no-samples \\(timeout\\)"):
            self.play(Run(1), Verdict("error", 0, crash="no-samples (timeout)"))


class OneTest(unittest.TestCase):
    ENTRY = {"title": "x", "swaps": [{"disk": 2, "at": 10}]}

    def one(self, play, each=map):
        with mock.patch.object(player, "ready") as self.ready, \
                mock.patch.object(gate.media, "download_sha256",
                                  return_value="aa") as self.sha256, \
                mock.patch.object(gate, "_play", side_effect=play) as self.play:
            return gate._one(7, self.ENTRY, "a500", each)

    def test_the_gates_judgement_of_the_entrys_runs(self):
        said, _ = self.one(lambda ready, run: Play(
            True, swaps=(SwapTaken(2, run.seed != 2),)))
        self.assertEqual(str(said), "fail (seed 2: disk 2 never loaded)")
        self.ready.assert_called_once_with(7, self.ENTRY, "a500")
        self.assertEqual(
            self.play.call_args_list,
            [mock.call(self.ready.return_value, r)
             for r in core.runs(self.ENTRY)])

    def test_a_pass(self):
        said, _ = self.one(
            lambda ready, run: Play(True, swaps=(SwapTaken(2, True),)))
        self.assertEqual(str(said), "pass (3 seeds: came alive, no crash, every"
                         " disk loaded; disk 2 until 40.0)")

    def test_the_sha256_is_of_the_productions_download(self):
        _, sha256 = self.one(lambda ready, run: Play(True))
        self.assertEqual(sha256, "aa")
        self.sha256.assert_called_once_with(7)

    def test_a_run_that_cannot_be_played_is_the_entrys_error(self):
        def cannot(ready, run):
            raise CannotPlay("the emulator gave nothing")
        with self.assertRaisesRegex(CannotPlay, "gave nothing"):
            self.one(cannot)

    def test_the_runs_are_made_through_the_callers_map(self):
        made = []

        def each(play, runs):
            made.extend(runs)
            return map(play, runs)
        self.one(lambda ready, run: Play(True, swaps=(SwapTaken(2, True),)), each)
        self.assertEqual(made, core.runs(self.ENTRY))


def judgement(*passed):
    """A Judgement of an entry that did as ``passed`` says on seeds 1.."""
    seeds = tuple((i + 1, Judgement(p, f"on {i + 1}"))
                  for i, p in enumerate(passed))
    return Judgement(all(passed), "said", seeds=seeds)


class StoreCase(unittest.TestCase):
    """A sweep database and an empty data directory, both thrown away."""
    ENTRIES = {7: {"title": "x"}, 8: {"title": "y"}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name) / "data"
        self.data.mkdir()
        self.db = Store(pathlib.Path(tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.lines = []
        for patch in (
                mock.patch.object(gate.replay, "all_entries",
                                  return_value=self.ENTRIES),
                mock.patch.object(gate, "default_machine", return_value="a500"),
                mock.patch.object(player.media, "require_mirror")):
            patch.start()
            self.addCleanup(patch.stop)

    def log(self, line, **kw):
        self.lines.append(line)

    def run_gate(self, ids, one):
        with mock.patch.object(gate, "_one", side_effect=one):
            return gate.run(ids, self.db, data=self.data, jobs=1, log=self.log)

    def stored(self):
        return [(r.prod, r.seed, r.passed, r.reason, r.sha256, r.player)
                for r in self.db.gated()]


class RunTest(StoreCase):
    def test_one_line_per_production(self):
        said = {7: judgement(True, True), 8: judgement(True, False)}
        errors = self.run_gate([8, 7], lambda p, *a: (said[p], "aa"))
        self.assertEqual(errors, 0)
        self.assertEqual(self.lines, ["7 x: pass (said)", "8 y: fail (said)"])

    def test_a_record_is_stored_per_entry_and_seed(self):
        said = {7: judgement(True, False, True), 8: judgement(True, True)}
        with mock.patch.object(player, "VERSION", "9"):
            self.run_gate([7, 8], lambda p, e, default, each: (said[p], f"sha{p}"))
        self.assertEqual(self.stored(), [
            (7, 1, True, "on 1", "sha7", "9"), (7, 2, False, "on 2", "sha7", "9"),
            (7, 3, True, "on 3", "sha7", "9"),
            (8, 1, True, "on 1", "sha8", "9"), (8, 2, True, "on 2", "sha8", "9")])

    def test_the_runs_of_one_entry_are_made_in_parallel(self):
        # Passes only when two runs of the entry are in flight at once.
        together = threading.Barrier(2, timeout=10)

        def play(ready, run):
            together.wait()
            return Play(True)
        with mock.patch.object(player, "ready"), \
                mock.patch.object(gate.media, "download_sha256",
                                  return_value="aa"), \
                mock.patch.object(gate, "_play", side_effect=play):
            gate.run([7], self.db, data=self.data, jobs=2, log=self.log)
        self.assertEqual(self.lines, ["7 x: pass (2 seeds: came alive, no crash)"])
        self.assertEqual(self.stored(), [
            (7, 1, True, "came alive, no crash", "aa", player.VERSION),
            (7, 2, True, "came alive, no crash", "aa", player.VERSION)])

    def test_an_id_with_no_entry_is_said_and_not_played(self):
        errors = self.run_gate([9], lambda *a: self.fail("played"))
        self.assertEqual((errors, self.lines),
                         (0, ["9: no entry in the data files"]))

    def test_what_cannot_be_played_is_counted_and_not_stored(self):
        self.run_gate([7], lambda *a: (judgement(True, True), "aa"))
        del self.lines[:]

        def cannot(*a):
            raise CannotPlay("no Kickstart ROM")
        errors = self.run_gate([7, 8], cannot)
        self.assertEqual(errors, 1 + 1)
        self.assertEqual(self.lines, ["7 x: error: no Kickstart ROM",
                                      "8 y: error: no Kickstart ROM"])
        # What the gate saw of 7 before stays; nothing is made up of 8.
        self.assertEqual([r[:3] for r in self.stored()],
                         [(7, 1, True), (7, 2, True)])

    def test_nothing_is_written_into_the_data_files(self):
        self.run_gate([7, 8], lambda *a: (judgement(True, False), "aa"))
        self.assertEqual(list(self.data.iterdir()), [])


class SummaryTest(StoreCase):
    def test_the_file_counts_the_entries_per_outcome(self):
        said = {7: judgement(True, True), 8: judgement(True, False)}
        self.run_gate([7, 8], lambda p, *a: (said[p], "aa"))
        path = self.data / "summary.txt"
        self.assertEqual(gate.write_summary(self.db, path), path)
        self.assertEqual(path.read_text().splitlines()[-2:],
                         ["pass      1", "fail      1"])

    def test_written_twice_of_the_same_log_it_is_the_same_file(self):
        self.run_gate([7, 8], lambda *a: (judgement(True, True), "aa"))
        first = gate.write_summary(self.db, self.data / "a.txt").read_bytes()
        again = gate.write_summary(self.db, self.data / "a.txt").read_bytes()
        self.assertEqual(first, again)

    def test_it_goes_beside_the_tools(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
                gate.config, "GATE_SUMMARY", pathlib.Path(d) / "s.txt"):
            self.assertEqual(gate.write_summary(self.db),
                             pathlib.Path(d) / "s.txt")
            self.assertTrue((pathlib.Path(d) / "s.txt").exists())


class StaleTest(StoreCase):
    def stale(self, sha256_of, version=player.VERSION):
        with mock.patch.object(gate.media, "download_sha256",
                               side_effect=sha256_of), \
                mock.patch.object(player, "VERSION", version):
            gate.stale(self.db, data=self.data, log=self.log)
        return self.lines

    def setUp(self):
        super().setUp()
        self.run_gate([7, 8], lambda p, *a: (judgement(True, True), f"sha{p}"))
        del self.lines[:]

    def test_nothing_changed_nothing_listed(self):
        self.assertEqual(self.stale("sha{}".format), [])

    def test_a_changed_download_is_listed(self):
        self.assertEqual(self.stale({7: "sha7", 8: "new"}.get),
                         ["8 y: download changed"])

    def test_a_changed_player_lists_every_entry(self):
        self.assertEqual(self.stale("sha{}".format, version="next"), [
            f"7 x: gated by player {player.VERSION}, now next",
            f"8 y: gated by player {player.VERSION}, now next"])

    def test_gated_again_it_is_no_longer_listed(self):
        self.run_gate([8], lambda *a: (judgement(True, True), "new"))
        del self.lines[:]
        self.assertEqual(self.stale({7: "sha7", 8: "new"}.get), [])

    def test_an_entry_gone_from_the_data_files_is_not_listed(self):
        gate.replay.all_entries.return_value = {7: {"title": "x"}}
        self.assertEqual(self.stale(lambda p: "new"), ["7 x: download changed"])

    def test_without_the_mirror_nothing_is_listed(self):
        gate.media.require_mirror.side_effect = CannotPlay("no Demozoo mirror")
        with self.assertRaisesRegex(CannotPlay, "no Demozoo mirror"):
            self.stale("sha{}".format)
        self.assertEqual(self.lines, [])


if __name__ == "__main__":
    unittest.main()
