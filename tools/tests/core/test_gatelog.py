import dataclasses
import unittest

from scenemeta.core import gatelog
from scenemeta.core.gatelog import Record


def rec(prod, seed, passed=True, sha256="aa", player="1", entry=None):
    return Record(prod, seed, passed, "why", sha256, player,
                  "2026-11-20T10:00:00", entry)


class NameTest(unittest.TestCase):
    ENTRY = {"title": "x", "source": "script", "machine": "a1200",
             "swaps": [{"disk": 2, "at": 800.0, "key": "lmb"}]}

    def test_two_entries_that_set_the_same_have_one_name(self):
        other = {"swaps": [{"key": "lmb", "at": 800, "disk": 2}],
                 "machine": "a1200", "title": "y", "group": "g",
                 "source": "ai", "note": "seen"}
        self.assertEqual(gatelog.name(other), gatelog.name(self.ENTRY))

    def test_another_setting_is_another_name(self):
        for change in ({"machine": "a500"}, {"result": "crashes-later"},
                       {"swaps": [{"disk": 2, "at": 800.1, "key": "lmb"}]},
                       {"swaps": [{"disk": 2, "at": 800.0}]}):
            self.assertNotEqual(gatelog.name({**self.ENTRY, **change}),
                                gatelog.name(self.ENTRY), change)

    def test_a_pass_is_every_record_passed_and_of_the_entry(self):
        mine, other = gatelog.name(self.ENTRY), gatelog.name({"title": "x"})
        self.assertTrue(gatelog.passes(
            [rec(7, 1, entry=mine), rec(7, 2, entry=mine)], self.ENTRY))
        for records in ([], [rec(7, 1, entry=mine), rec(7, 2, False, entry=mine)],
                        [rec(7, 1, entry=other)], [rec(7, 1)]):
            self.assertFalse(gatelog.passes(records, self.ENTRY), records)


class SummaryTest(unittest.TestCase):
    def test_an_entry_passes_when_every_seed_of_it_did(self):
        records = [rec(7, 1), rec(7, 2), rec(8, 1), rec(8, 2, False),
                   rec(9, 1, False), rec(9, 2)]
        self.assertEqual(gatelog.outcomes(records),
                         {7: True, 8: False, 9: False})

    def test_the_summary_counts_entries_per_outcome(self):
        records = [rec(7, 1), rec(7, 2), rec(8, 1), rec(8, 2, False),
                   rec(9, 1)]
        self.assertEqual(gatelog.summary(records),
                         "Entries by what the gate last saw of them.\n\n"
                         "pass      2\nfail      1\n")

    def test_an_empty_log_counts_nothing(self):
        self.assertTrue(gatelog.summary([]).endswith(
            "pass      0\nfail      0\n"))

    def test_when_an_entry_was_gated_is_not_in_the_summary(self):
        later = dataclasses.replace(rec(7, 1), at="2027-01-01T00:00:00")
        self.assertEqual(gatelog.summary([rec(7, 1)]), gatelog.summary([later]))


class StaleTest(unittest.TestCase):
    RECORDS = [rec(7, 1), rec(7, 2), rec(8, 1, sha256="bb"),
               rec(9, 1, player="0")]

    def test_the_same_download_and_player_is_not_stale(self):
        self.assertEqual(
            gatelog.stale(self.RECORDS[:3], {7: "aa", 8: "bb"}.get, "1"), [])

    def test_every_entry_of_another_player_is_stale_once(self):
        self.assertEqual(
            gatelog.stale(self.RECORDS[:3], {7: "aa", 8: "bb"}.get, "2"),
            [(7, "gated by player 1, now 2"), (8, "gated by player 1, now 2")])

    def test_a_changed_download_is_stale(self):
        self.assertEqual(
            gatelog.stale(self.RECORDS[:3], {7: "aa", 8: "cc"}.get, "1"),
            [(8, "download changed")])

    def test_a_download_that_is_gone_is_stale(self):
        self.assertEqual(gatelog.stale(self.RECORDS[:2], {}.get, "1"),
                         [(7, "download changed")])

    def test_another_player_is_stale_and_its_download_not_looked_at(self):
        def sha256_of(prod):
            self.assertNotEqual(prod, 9)
            return {7: "aa", 8: "bb"}[prod]
        self.assertEqual(gatelog.stale(self.RECORDS, sha256_of, "1"),
                         [(9, "gated by player 0, now 1")])


if __name__ == "__main__":
    unittest.main()
