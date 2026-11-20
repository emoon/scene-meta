import ast
import inspect
import unittest

from scenemeta.core import gate
from scenemeta.core.gate import Play, SwapTaken


class JudgeTest(unittest.TestCase):
    def said(self, play):
        return str(gate.judge(play))

    def test_alive_with_no_crash_passes(self):
        j = gate.judge(Play(ran=True))
        self.assertTrue(j.passed)
        self.assertEqual(str(j), "pass (came alive, no crash)")

    def test_every_swapped_disk_loaded_passes(self):
        play = Play(True, swaps=(SwapTaken(2, True), SwapTaken(3, True)))
        self.assertEqual(self.said(play),
                         "pass (came alive, no crash, every disk loaded)")

    def test_never_alive_fails(self):
        j = gate.judge(Play(ran=False))
        self.assertFalse(j.passed)
        self.assertEqual(str(j), "fail (never came alive)")

    def test_a_crash_fails_though_it_came_alive(self):
        self.assertEqual(self.said(Play(True, crash="guru")),
                         "fail (crashed: guru)")

    def test_a_crash_before_it_came_alive_is_named(self):
        self.assertEqual(self.said(Play(False, crash="alert:00000003")),
                         "fail (crashed: alert:00000003)")

    def test_working_while_a_swapped_disk_is_never_loaded_fails(self):
        # 95819 Hit The Road, 221372 Mathik: plays on, disk 2 never read.
        self.assertEqual(self.said(Play(True, swaps=(SwapTaken(2, False),))),
                         "fail (disk 2 never loaded)")

    def test_each_disk_not_loaded_is_named(self):
        play = Play(True, swaps=(SwapTaken(2, False), SwapTaken(3, True),
                                 SwapTaken(4, False)))
        self.assertEqual(self.said(play), "fail (disks 2, 4 never loaded)")


class SeamTest(unittest.TestCase):
    def test_the_gate_imports_nothing_from_a_platform(self):
        tree = ast.parse(inspect.getsource(gate))
        imported = [n for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([ast.unparse(n) for n in imported],
                         ["import dataclasses"])


if __name__ == "__main__":
    unittest.main()
