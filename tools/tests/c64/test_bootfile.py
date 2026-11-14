import unittest

from scenedb.c64 import bootfile


class PickTest(unittest.TestCase):
    def test_exact_beats_contains(self):
        disks = [["galaworm intro", "menu"], ["galaworm"]]
        self.assertEqual(bootfile.pick("Galaworm", disks), (1, "galaworm"))

    def test_ignores_punctuation_and_case(self):
        self.assertEqual(bootfile.pick("2 Planeten", [["2-planeten"]]), (0, "2-planeten"))

    def test_short_names_never_match(self):
        self.assertIsNone(bootfile.pick("Pi", [["pi"]]))

    def test_the_group_after_a_slash_is_not_part_of_the_name(self):
        self.assertEqual(bootfile.pick("Artillery 85%", [["artillery /shape"]]),
                         (0, "artillery /shape"))

    def test_no_match(self):
        self.assertIsNone(bootfile.pick("Storebror", [["firsttry"], ["-----"]]))

    def test_earliest_wins_a_tie(self):
        self.assertEqual(bootfile.pick("Mist", [["mist"], ["mist"]]), (0, "mist"))


if __name__ == "__main__":
    unittest.main()
