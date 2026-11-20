import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from scenemeta.amiga import gate, player
from scenemeta.amiga.verdict import Verdict
from scenemeta.core.errors import CannotPlay
from scenemeta.core import gate as core
from scenemeta.core.gate import Play, Run, SwapTaken


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
                mock.patch.object(gate, "_play", side_effect=play) as self.play:
            return gate._one(7, self.ENTRY, "a500", each)

    def test_the_line_is_the_gates_judgement_of_the_entrys_runs(self):
        line = self.one(lambda ready, run: Play(
            True, swaps=(SwapTaken(2, run.seed != 2),)))
        self.assertEqual(line, "7 x: fail (seed 2: disk 2 never loaded)")
        self.ready.assert_called_once_with(7, self.ENTRY, "a500")
        self.assertEqual(
            self.play.call_args_list,
            [mock.call(self.ready.return_value, r)
             for r in core.runs(self.ENTRY)])

    def test_a_pass(self):
        line = self.one(lambda ready, run: Play(True, swaps=(SwapTaken(2, True),)))
        self.assertEqual(line, "7 x: pass (3 seeds: came alive, no crash, every"
                         " disk loaded; disk 2 until 40.0)")

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


class RunTest(unittest.TestCase):
    def run_gate(self, ids, lines_of):
        lines = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(gate.replay, "all_entries",
                                  return_value={7: {"title": "x"},
                                                8: {"title": "y"}}), \
                mock.patch.object(gate, "default_machine",
                                  return_value="a500"), \
                mock.patch.object(player.media, "require_mirror"), \
                mock.patch.object(gate, "_one", side_effect=lines_of):
            errors = gate.run(ids, data=pathlib.Path(d), jobs=1,
                              log=lambda line, **kw: lines.append(line))
        return errors, lines

    def test_one_line_per_production(self):
        errors, lines = self.run_gate(
            [8, 7], lambda p, e, default, each: f"{p} {e['title']}: pass ({default})")
        self.assertEqual(errors, 0)
        self.assertEqual(lines, ["7 x: pass (a500)", "8 y: pass (a500)"])

    def test_the_runs_of_one_entry_are_made_in_parallel(self):
        # Passes only when two runs of the entry are in flight at once.
        together = threading.Barrier(2, timeout=10)

        def play(ready, run):
            together.wait()
            return Play(True)
        lines = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(gate.replay, "all_entries",
                                  return_value={7: {"title": "x"}}), \
                mock.patch.object(gate, "default_machine",
                                  return_value="a500"), \
                mock.patch.object(player.media, "require_mirror"), \
                mock.patch.object(player, "ready"), \
                mock.patch.object(gate, "_play", side_effect=play):
            gate.run([7], data=pathlib.Path(d), jobs=2,
                     log=lambda line, **kw: lines.append(line))
        self.assertEqual(lines, ["7 x: pass (2 seeds: came alive, no crash)"])

    def test_an_id_with_no_entry_is_said_and_not_played(self):
        errors, lines = self.run_gate([9], lambda *a: self.fail("played"))
        self.assertEqual((errors, lines), (0, ["9: no entry in the data files"]))

    def test_what_cannot_be_played_is_counted(self):
        def cannot(*a):
            raise CannotPlay("no Kickstart ROM")
        errors, lines = self.run_gate([7], cannot)
        self.assertEqual(errors, 1)
        self.assertEqual(lines, ["7 x: error: no Kickstart ROM"])


if __name__ == "__main__":
    unittest.main()
