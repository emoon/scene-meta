import pathlib
import unittest
from unittest import mock

from scenemeta.amiga import config, expected, gate
from scenemeta.core import expected as core
from scenemeta.core.errors import CannotPlay
from tests.amiga.test_gate import StoreCase, judgement

DATA = pathlib.Path(__file__).resolve().parents[3] / "data" / "amiga"


class CheckedInTest(unittest.TestCase):
    def test_the_expected_file_holds_and_every_id_is_in_the_data_files(self):
        cases, entries = expected.load(config.EXPECTED, DATA)
        self.assertTrue(cases)
        self.assertEqual(list(entries), sorted(cases))
        self.assertTrue(any(c.video for c in cases.values()))


class RunTest(StoreCase):
    EXPECTED = ('[demozoo.8]\nexpect = "broken"\nwhy = "bad disk"\n'
              '[demozoo.7]\nexpect = "plays"\nvideo = [90, 120]\n')

    def setUp(self):
        super().setUp()
        self.path = self.data / "expected.toml"
        self.path.write_text(self.EXPECTED)
        self.board = self.data / "score.txt"

    def run_expected(self, one):
        with mock.patch.object(gate, "_one", side_effect=one):
            return expected.run(self.db, self.path, self.board, self.data,
                              jobs=1, log=self.log)

    def test_expected_and_seen_of_each_then_the_total(self):
        said = {7: judgement(True, True), 8: judgement(True, True)}
        errors = self.run_expected(lambda p, *a: (said[p], "aa"))
        self.assertEqual(errors, 0)
        self.assertEqual(self.lines, [
            "7 x: pass (said); expected plays",
            "8 y: pass (said); expected broken",
            "as expected 1 of 2", f"wrote {self.board}"])

    def test_the_scoreboard_is_written(self):
        said = {7: judgement(True, False), 8: judgement(False)}
        self.run_expected(lambda p, *a: (said[p], "aa"))
        self.assertEqual(self.board.read_text().split("\n\n")[1:], [
            "as expected 1 of 2", "      7 plays  fail\n      8 broken fail\n"])

    def test_what_the_gate_saw_goes_into_the_store(self):
        self.run_expected(lambda p, *a: (judgement(True), f"sha{p}"))
        self.assertEqual([r[:3] + r[4:5] for r in self.stored()],
                         [(7, 1, True, "sha7"), (8, 1, True, "sha8")])

    def test_the_same_results_for_other_reasons_leave_the_scoreboard(self):
        self.run_expected(lambda p, *a: (judgement(True, True), "aa"))
        first = self.board.read_bytes()
        self.run_expected(lambda p, *a: (judgement(True, True, True), "bb"))
        self.assertEqual(self.board.read_bytes(), first)
        self.run_expected(lambda p, *a: (judgement(p == 8, True), "aa"))
        self.assertNotEqual(self.board.read_bytes(), first)

    def test_what_cannot_be_played_is_an_error_and_counted(self):
        def one(p, *a):
            if p == 8:
                raise CannotPlay("no Kickstart ROM")
            return judgement(True), "aa"
        self.assertEqual(self.run_expected(one), 1)
        self.assertEqual(self.lines[:3], [
            "7 x: pass (said); expected plays",
            "8 y: error: no Kickstart ROM; expected broken",
            "as expected 1 of 2"])
        self.assertTrue(self.board.read_text().endswith(
            "      7 plays  pass\n      8 broken error\n"))

    def test_the_video_is_kept_and_plays_no_part(self):
        cases, _ = expected.load(self.path, self.data)
        self.assertEqual(cases[7].video, (90, 120))
        self.run_expected(lambda p, *a: (judgement(True), "aa"))
        first = self.board.read_bytes()
        self.path.write_text(self.EXPECTED.replace("[90, 120]", "[1, 2]"))
        self.run_expected(lambda p, *a: (judgement(True), "aa"))
        self.assertEqual(self.board.read_bytes(), first)

    def test_an_expected_file_that_does_not_hold_runs_nothing(self):
        self.path.write_text('[demozoo.9]\nexpect = "plays"\n')
        with self.assertRaisesRegex(core.Invalid, "not in the data files"):
            self.run_expected(lambda *a: self.fail("played"))
        self.assertFalse(self.board.exists())

    def test_the_files_are_the_ones_beside_the_tools(self):
        with mock.patch.object(config, "EXPECTED", self.path), \
                mock.patch.object(config, "EXPECTED_SCORE", self.board), \
                mock.patch.object(gate, "_one",
                                  return_value=(judgement(True), "aa")):
            expected.run(self.db, data=self.data, jobs=1, log=self.log)
        self.assertTrue(self.board.exists())


if __name__ == "__main__":
    unittest.main()
