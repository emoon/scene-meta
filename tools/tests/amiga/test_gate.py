import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.amiga import gate, player
from scenemeta.amiga.verdict import Verdict
from scenemeta.core.errors import CannotPlay
from scenemeta.core.gate import Play, SwapTaken


class OneTest(unittest.TestCase):
    ENTRY = {"title": "x", "swaps": [{"disk": 2, "at": 10}]}

    def one(self, verdict, record):
        outcome = player.Outcome("a500", verdict, [], None, record)
        with mock.patch.object(player, "play", return_value=outcome) as self.play:
            return gate._one(7, self.ENTRY, "a500")

    def test_the_line_is_the_gates_judgement_of_one_run(self):
        line = self.one(Verdict("works", 9),
                        Play(True, swaps=(SwapTaken(2, False),)))
        self.assertEqual(line, "7 x: fail (disk 2 never loaded)")
        self.play.assert_called_once_with(7, self.ENTRY, "a500")

    def test_a_pass(self):
        line = self.one(Verdict("works", 9),
                        Play(True, swaps=(SwapTaken(2, True),)))
        self.assertEqual(line, "7 x: pass (came alive, no crash, every disk"
                         " loaded)")

    def test_an_emulator_that_showed_nothing_is_an_error_not_a_fail(self):
        with self.assertRaisesRegex(CannotPlay, "no-samples \\(timeout\\)"):
            self.one(Verdict("error", 0, crash="no-samples (timeout)"),
                     Play(False, "no-samples (timeout)"))


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
            [8, 7], lambda p, e, default: f"{p} {e['title']}: pass ({default})")
        self.assertEqual(errors, 0)
        self.assertEqual(lines, ["7 x: pass (a500)", "8 y: pass (a500)"])

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
