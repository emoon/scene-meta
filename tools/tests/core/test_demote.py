import unittest

from scenemeta.core import demote, gatelog
from scenemeta.core.gatelog import Error, Record


def recs(prod, entry, *passed):
    return [Record(prod, seed, ok, f"why {seed}", "aa", "1", "t",
                   gatelog.name(entry))
            for seed, ok in enumerate(passed, 1)]


class ReviewTest(unittest.TestCase):
    RUNS = {"title": "x", "source": "script", "machine": "a1200"}

    def review(self, entries, records=(), errors=()):
        return demote.review(entries, records, errors)

    def test_a_script_entry_that_says_it_runs_and_failed_is_demoted(self):
        later = {**self.RUNS, "result": "crashes-later"}
        got = self.review({8: later, 7: self.RUNS},
                          recs(7, self.RUNS, True, False)
                          + recs(8, later, False, False))
        self.assertEqual(got.demote, [(7, "seed 2: why 2"), (8, "seed 1: why 1")])
        self.assertEqual((got.passed, got.failed, got.kept), (0, 2, []))

    def test_a_script_entry_that_does_not_say_it_runs_only_counts(self):
        entries = {7: {**self.RUNS, "result": "unknown"},
                   8: {**self.RUNS, "result": "broken"}}
        got = self.review(entries, recs(7, entries[7], False)
                          + recs(8, entries[8], False))
        self.assertEqual((got.failed, got.demote, got.kept), (2, [], []))

    def test_a_failing_entry_somebody_worked_on_is_kept_and_listed(self):
        entries = {7: {**self.RUNS, "source": "ai"},
                   8: {**self.RUNS, "source": "verified", "result": "broken"}}
        got = self.review(entries, recs(7, entries[7], False)
                          + recs(8, entries[8], True, False))
        self.assertEqual(got.kept, [(7, "seed 1: why 1"), (8, "seed 2: why 2")])
        self.assertEqual((got.failed, got.demote), (2, []))

    def test_a_pass_is_counted_whatever_the_entry_says(self):
        entries = {7: self.RUNS, 8: {**self.RUNS, "source": "ai"},
                   9: {**self.RUNS, "result": "unknown"}}
        got = self.review(entries, [r for p, e in entries.items()
                                    for r in recs(p, e, True, True)])
        self.assertEqual((got.passed, got.failed), (3, 0))
        self.assertEqual(got.demote + got.kept + got.errors + got.ungated, [])

    def test_what_could_not_be_played_is_apart_from_the_failures(self):
        got = self.review(
            {7: self.RUNS}, recs(7, self.RUNS, False),
            [Error(7, "no ROM", "t", gatelog.name(self.RUNS))])
        self.assertEqual(got.errors, [(7, "no ROM")])
        self.assertEqual((got.failed, got.demote), (0, []))

    def test_an_entry_with_no_record_or_changed_since_is_not_gated(self):
        was = {**self.RUNS, "machine": "a500"}
        got = self.review({7: self.RUNS, 8: self.RUNS, 9: self.RUNS},
                          recs(8, was, False),
                          [Error(9, "no ROM", "t", gatelog.name(was))])
        self.assertEqual(got.ungated, [7, 8, 9])
        self.assertEqual((got.failed, got.demote, got.errors), (0, [], []))

    def test_a_record_of_no_entry_in_the_files_is_left_out(self):
        got = self.review({}, recs(7, self.RUNS, False))
        self.assertEqual((got.failed, got.ungated), (0, []))


class DemotedTest(unittest.TestCase):
    def test_it_is_unknown_with_the_fault_and_says_nothing_of_a_run(self):
        entry = {"title": "x", "group": "g", "source": "script",
                 "machine": "a1200", "drives": 2, "boot": "floppy",
                 "result": "crashes-later", "disks": ["a.adf", "b.adf"],
                 "swaps": [{"disk": 2, "at": 10.0}],
                 "keys": [{"at": 5.0, "key": "lmb"}], "run": "demo.exe",
                 "note": "the sweep only reached disk 1 of 2"}
        self.assertEqual(demote.demoted(entry, "seed 1: never came alive"), {
            "title": "x", "group": "g", "source": "script", "boot": "floppy",
            "result": "unknown", "disks": ["a.adf", "b.adf"],
            "run": "demo.exe",
            "note": "failed the gate: seed 1: never came alive"})
        self.assertIn("swaps", entry)


if __name__ == "__main__":
    unittest.main()
