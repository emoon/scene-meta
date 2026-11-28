import pathlib
import unittest

from scenemeta.c64 import config, expected
from scenemeta.core import expected as core

DATA = pathlib.Path(__file__).resolve().parents[3] / "data/c64"


class CheckedInTest(unittest.TestCase):
    def test_corpus_has_plain_and_swap_entries(self):
        cases, entries = expected.load(config.EXPECTED, DATA)
        self.assertTrue(cases)
        self.assertTrue(any(e.get("events") for e in entries.values()))
        self.assertTrue(any(not e.get("events") for e in entries.values()))
        self.assertEqual(set(cases), set(entries))

    def test_scoreboard_covers_every_corpus_entry(self):
        cases, _ = expected.load(config.EXPECTED, DATA)
        lines = config.EXPECTED_SCORE.read_text().splitlines()
        rows = {int(p): seen for line in lines if len(words := line.split()) == 3
                and words[0].isdigit() for p, expect, seen in [words]}
        self.assertEqual(set(rows), set(cases))
        self.assertEqual(config.EXPECTED_SCORE.read_text(), core.scoreboard(cases, rows))
