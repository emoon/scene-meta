import unittest

from scenemeta.c64 import verdict
from scenemeta.c64.swapwait import Sample

SEC = 1_000_000


def samples(shots):
    return [Sample((i + 1) * SEC, 0, 0xF0, s) for i, s in enumerate(shots)]


class Classify(unittest.TestCase):
    def test_moving_screen_works(self):
        v = verdict.classify(samples(str(i) for i in range(40)), set())
        self.assertEqual(v.verdict, "works")

    def test_static_screen_is_no_activity(self):
        self.assertEqual(verdict.classify(samples(["a"] * 40), set()).verdict,
                         "no-activity")

    def test_blinking_basic_prompt_does_not_count(self):
        s = samples("ab" * 20)
        v = verdict.classify(s, set(range(40)))
        self.assertEqual(v.verdict, "no-activity")

    def test_crash_after_activity(self):
        v = verdict.classify(samples(str(i) for i in range(40)), set(),
                             crash="emulator-exit", crash_cycles=39 * SEC)
        self.assertEqual(v.verdict, "works-then-crash")

    def test_crash_before_activity(self):
        v = verdict.classify(samples(str(i) for i in range(5)), set(),
                             crash="emulator-exit", crash_cycles=5 * SEC)
        self.assertEqual(v.verdict, "crash")

    def test_demo_that_stops_moving_reports_when(self):
        shots = [str(i) for i in range(30)] + ["end"] * 30
        v = verdict.classify(samples(shots), set())
        self.assertEqual(v.ended_cycles, 31 * SEC)


if __name__ == "__main__":
    unittest.main()
