import ast
import inspect
import unittest

from scenemeta.core import gate
from scenemeta.core.gate import Play, Run, SwapTaken


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


PLAIN = {"title": "x"}
SWAP = {"title": "x", "events": [{"at": 100.0, "disk": 2}]}
# 169514 Persistence Megademo: a key after its swap. 10297 Megademo: a key
# alone.
SWAP_KEY = {"title": "x", "events": [{"at": 129.2, "disk": 2},
                                      {"at": 131.2, "key": "lmb"}]}
KEY = {"title": "x", "events": [{"at": 86.1, "key": "lmb"}]}

OK = Play(True, swaps=(SwapTaken(2, True),))
UNLOADED = Play(True, swaps=(SwapTaken(2, False),))


class RunsTest(unittest.TestCase):
    def test_an_entry_with_nothing_to_do_is_played_on_two_seeds(self):
        self.assertEqual(gate.runs(PLAIN), [Run(1), Run(2)])

    def test_swaps_make_it_three_each_with_the_disks_late_too(self):
        self.assertEqual(gate.runs(SWAP), [Run(1), Run(1, late=True),
                                           Run(2), Run(2, late=True),
                                           Run(3), Run(3, late=True)])

    def test_keys_make_it_three_each_with_a_run_without_each_key(self):
        entry = dict(KEY, events=KEY["events"] * 2)
        self.assertEqual(gate.runs(entry),
                         [Run(seed, without=k) if k is not None else Run(seed)
                          for seed in (1, 2, 3) for k in (None, 0, 1)])

    def test_a_key_after_a_swap_is_a_key(self):
        self.assertEqual(gate.runs(SWAP_KEY)[:3],
                         [Run(1), Run(1, late=True), Run(1, without=0)])


class AsPlayedTest(unittest.TestCase):
    ENTRY = {"title": "x",
             "events": [{"at": 5.0, "key": "space"},
                        {"at": 10.0, "disk": 2}, {"at": 12.0, "key": "lmb"},
                        {"at": 50.0, "disk": 3, "drive": 2},
                        {"at": 70.0, "key": "lmb"}]}

    def events(self, run):
        return gate.as_played(self.ENTRY, run)["events"]

    def test_as_written(self):
        self.assertEqual(self.events(Run(1)), self.ENTRY["events"])

    def test_late_the_first_disk_and_all_after_it_are_30_s_later(self):
        events = self.events(Run(1, late=True))
        self.assertEqual([e["at"] for e in events],
                         [5.0, 40.0, 42.0, 80.0, 100.0])
        self.assertEqual(events[3], {"at": 80.0, "disk": 3, "drive": 2})

    def test_without_a_key_everything_else_still_happens(self):
        written = self.ENTRY["events"]
        self.assertEqual(self.events(Run(1, without=0)), written[1:])
        self.assertEqual(self.events(Run(1, without=1)),
                         written[:2] + written[3:])
        self.assertEqual(self.events(Run(1, without=2)), written[:4])

    def test_the_entry_is_left_as_it_was(self):
        before = repr(self.ENTRY)
        for run in gate.runs(self.ENTRY):
            gate.as_played(self.ENTRY, run)
        self.assertEqual(repr(self.ENTRY), before)

    def test_what_else_the_entry_says_is_played_too(self):
        self.assertEqual(gate.as_played(dict(PLAIN, machine="a1200"), Run(1)),
                         {"title": "x", "machine": "a1200", "events": []})


class VerdictTest(unittest.TestCase):
    def said(self, entry, plays=None, **default):
        """The verdict with each run of ``entry`` giving ``default``'s Play
        of its kind (written, late, without), but for those of ``plays``."""
        kinds = {"written": OK, "late": OK, "without": UNLOADED, **default}
        got = {r: kinds["late" if r.late else
                        "written" if r.without is None else "without"]
               for r in gate.runs(entry)}
        got.update(plays or {})
        return gate.verdict(entry, got)

    def test_an_entry_with_nothing_to_do_passes_on_its_two_seeds(self):
        j = self.said(PLAIN, written=Play(True))
        self.assertEqual(str(j), "pass (2 seeds: came alive, no crash)")
        self.assertEqual(j.until, ())

    def test_failing_on_one_seed_fails_and_the_seed_is_named(self):
        # 169514 Persistence Megademo halts on seed 3 only.
        j = self.said(SWAP, {Run(3): Play(True, "halt", (SwapTaken(2, True),))})
        self.assertFalse(j.passed)
        self.assertEqual(str(j), "fail (seed 3: crashed: halt;"
                                 " disk 2 until 130.0)")

    def test_the_judgement_carries_that_of_each_seed(self):
        j = self.said(SWAP_KEY, {Run(2): UNLOADED, Run(3, without=0): OK})
        self.assertEqual(
            [(seed, on.passed, on.reason) for seed, on in j.seeds],
            [(1, True, "came alive, no crash, every disk loaded,"
                       " every key needed"),
             (2, False, "disk 2 never loaded"),
             (3, False, "key not needed: lmb at 131.2")])

    def test_the_first_seed_that_fails_is_the_one_named(self):
        j = self.said(PLAIN, {Run(2): Play(False)}, written=Play(True))
        self.assertEqual(str(j), "fail (seed 2: never came alive)")

    def test_a_pass_says_the_until_it_proved_of_each_swap(self):
        entry = {"title": "x", "events": [{"at": 100.0, "disk": 2},
                                          {"at": 536.9, "disk": 3}]}
        both = Play(True, swaps=(SwapTaken(2, True), SwapTaken(3, True)))
        j = self.said(entry, written=both, late=both)
        self.assertEqual(str(j), "pass (3 seeds: came alive, no crash, every"
                                 " disk loaded; disk 2 until 130.0;"
                                 " disk 3 until 566.9)")
        self.assertEqual(j.until, (130.0, 566.9))

    def test_a_disk_that_loads_at_at_but_not_30_s_later_fails(self):
        j = self.said(SWAP, {Run(2, late=True): UNLOADED})
        self.assertEqual(str(j), "fail (seed 2: with the disks put in 30 s"
                                 " later, disk 2 never loaded;"
                                 " disk 2 until 100.0)")
        self.assertEqual(j.until, (100.0,))

    def test_a_crash_with_the_disks_late_fails_though_they_loaded(self):
        late = Play(True, "guru", (SwapTaken(2, True),))
        j = self.said(SWAP, {Run(1, late=True): late})
        self.assertEqual(str(j), "fail (seed 1: with the disks put in 30 s"
                                 " later, crashed: guru; disk 2 until 130.0)")

    def test_until_is_of_each_swap_on_its_own(self):
        entry = {"title": "x", "events": [{"at": 100.0, "disk": 2},
                                          {"at": 200.0, "disk": 3}]}
        both = Play(True, swaps=(SwapTaken(2, True), SwapTaken(3, True)))
        late = Play(True, swaps=(SwapTaken(2, True), SwapTaken(3, False)))
        j = self.said(entry, {Run(3, late=True): late}, written=both, late=both)
        self.assertEqual(j.until, (130.0, 200.0))

    def test_a_disk_that_loaded_on_no_seed_has_no_until(self):
        j = self.said(SWAP, written=UNLOADED, late=UNLOADED)
        self.assertEqual(str(j), "fail (seed 1: disk 2 never loaded)")
        self.assertEqual(j.until, (None,))

    def test_a_key_without_which_the_disk_does_not_load_is_needed(self):
        j = self.said(SWAP_KEY)
        self.assertEqual(str(j), "pass (3 seeds: came alive, no crash, every"
                                 " disk loaded, every key needed;"
                                 " disk 2 until 159.2)")

    def test_a_key_that_makes_no_difference_fails_as_not_needed(self):
        j = self.said(SWAP_KEY, without=OK)
        self.assertFalse(j.passed)
        self.assertEqual(str(j), "fail (seed 1: key not needed: lmb at 131.2;"
                                 " disk 2 until 159.2)")

    def test_a_key_not_needed_on_one_seed_fails_on_that_seed(self):
        j = self.said(SWAP_KEY, {Run(2, without=0): OK})
        self.assertEqual(str(j), "fail (seed 2: key not needed: lmb at 131.2;"
                                 " disk 2 until 159.2)")

    def test_a_key_alone_is_needed_when_the_run_without_gets_less_far(self):
        # 10297 Megademo: alive at its prompt either way, reads on only
        # after the click.
        j = self.said(KEY, written=Play(True, far=91.5),
                      without=Play(True, far=51.9))
        self.assertEqual(str(j), "pass (3 seeds: came alive, no crash, every"
                                 " key needed)")

    def test_a_key_alone_that_gets_no_further_is_not_needed(self):
        j = self.said(KEY, written=Play(True, far=51.9),
                      without=Play(True, far=51.9))
        self.assertEqual(str(j), "fail (seed 1: key not needed: lmb at 86.1)")

    def test_each_key_is_judged_on_its_own(self):
        entry = dict(KEY, events=KEY["events"] + [{"at": 200, "key": "lmb"}])
        far, short = Play(True, far=250.0), Play(True, far=90.0)
        j = self.said(entry, {Run(1, without=1): far}, written=far,
                      without=short)
        self.assertEqual(str(j), "fail (seed 1: key not needed: lmb at 200)")

    def test_a_run_without_the_key_that_crashes_got_less_far(self):
        j = self.said(KEY, written=Play(True, far=50.0),
                      without=Play(True, "guru", far=50.0))
        self.assertTrue(j.passed)


class CheckTest(unittest.TestCase):
    def test_every_run_is_played_and_the_plays_judged(self):
        asked = []

        def play(run):
            asked.append(run)
            return Play(run.seed != 2)
        self.assertEqual(str(gate.check(PLAIN, play)),
                         "fail (seed 2: never came alive)")
        self.assertEqual(asked, gate.runs(PLAIN))

    def test_the_runs_are_made_through_the_callers_map(self):
        def each(play, runs):
            self.assertEqual(list(runs), gate.runs(SWAP))
            return [OK] * 6
        self.assertTrue(gate.check(SWAP, None, each).passed)


class SeamTest(unittest.TestCase):
    def test_the_gate_imports_nothing_from_a_platform(self):
        tree = ast.parse(inspect.getsource(gate))
        imported = [n for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([ast.unparse(n) for n in imported],
                         ["import dataclasses"])


if __name__ == "__main__":
    unittest.main()
