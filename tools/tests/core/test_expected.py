import unittest

from scenemeta.core import expected
from scenemeta.core.expected import Case
from scenemeta.core.gate import Judgement

KNOWN = {7: {}, 8: {}}


def problems(text, known=KNOWN):
    try:
        expected.parse(text, known)
    except expected.Invalid as e:
        return str(e).split("\n")
    return []


class ParseTest(unittest.TestCase):
    def test_a_case_of_each_production(self):
        got = expected.parse('[demozoo.7]  # X\nexpect = "plays"\n'
                           'cause = "swap-time"\nnote = "n"\nvideo = [90, 120]\n'
                           '[demozoo.8]\nexpect = "broken"\nwhy = "bad disk"\n',
                           KNOWN)
        self.assertEqual(got, {
            7: Case("plays", cause="swap-time", note="n", video=(90, 120)),
            8: Case("broken", why="bad disk")})

    def test_an_empty_file_has_no_cases(self):
        self.assertEqual(expected.parse("", KNOWN), {})

    def test_an_id_that_is_not_in_the_data_files(self):
        self.assertEqual(problems('[demozoo.9]\nexpect = "plays"\n'),
                         ["[demozoo.9] is not in the data files"])

    def test_every_problem_is_listed(self):
        self.assertEqual(
            problems('[demozoo.7]\nexpect = "works"\n[demozoo.9]\n'),
            ["[demozoo.7] expect must be one of plays, broken",
             "[demozoo.9] needs expect",
             "[demozoo.9] is not in the data files"])

    def test_what_a_case_may_say(self):
        for body, problem in (
                ('expect = "plays"\ntitle = "x"', "unknown field title"),
                ('expect = "broken"', "why goes with broken, and only with it"),
                ('expect = "plays"\nwhy = "x"',
                 "why goes with broken, and only with it"),
                ('expect = "broken"\nwhy = ""', "why must be a non-empty string"),
                ('expect = "plays"\nnote = 3', "note must be a non-empty string"),
                ('expect = "plays"\ncause = "Swap time"',
                 "cause must be a lowercase label"),
                ('expect = "plays"\nvideo = 90',
                 "video must be [shortest, longest] in whole seconds"),
                ('expect = "plays"\nvideo = [120, 90]',
                 "video must be [shortest, longest] in whole seconds"),
                ('expect = "plays"\nvideo = [90.5, 120]',
                 "video must be [shortest, longest] in whole seconds"),
                ('expect = "plays"\nvideo = [0, 120]',
                 "video must be [shortest, longest] in whole seconds"),
                ('expect = "plays"\nvideo = [90, 120, 150]',
                 "video must be [shortest, longest] in whole seconds")):
            with self.subTest(body):
                self.assertEqual(problems(f"[demozoo.7]\n{body}\n"),
                                 [f"[demozoo.7] {problem}"])

    def test_what_is_not_a_table_per_demozoo_id(self):
        self.assertEqual(problems('[csdb.7]\nexpect = "plays"\n'),
                         ["unknown top-level csdb"])
        self.assertEqual(problems('[demozoo.07]\nexpect = "plays"\n'),
                         ["[demozoo.07] must have a numeric ID"])
        self.assertEqual(problems("[demozoo]\n7 = 1\n"),
                         ["[demozoo.7] must be a table"])
        self.assertEqual(problems("demozoo = 1\n"),
                         ["demozoo must hold a table per production"])

    def test_text_that_is_not_toml(self):
        self.assertTrue(problems("[demozoo.7\n"))


class ScoreboardTest(unittest.TestCase):
    CASES = {8: Case("broken", why="bad disk"), 7: Case("plays"),
             30: Case("plays", video=(90, 120))}

    def test_the_gates_word_of_a_judgement(self):
        self.assertEqual(expected.seen(Judgement(True, "x")), "pass")
        self.assertEqual(expected.seen(Judgement(False, "x")), "fail")

    def test_plays_is_a_pass_and_broken_a_fail(self):
        for saw, hits in (({7: "pass", 8: "fail", 30: "pass"}, 3),
                          ({7: "fail", 8: "pass", 30: "pass"}, 1),
                          ({7: "error", 8: "error", 30: "error"}, 0)):
            self.assertEqual(expected.total(self.CASES, saw),
                             f"as expected {hits} of 3")

    def test_the_total_then_a_line_per_production_by_id(self):
        text = expected.scoreboard(self.CASES,
                                 {30: "error", 7: "pass", 8: "pass"})
        self.assertEqual(text.split("\n\n")[1:], [
            "as expected 1 of 3",
            "      7 plays  pass\n      8 broken pass\n     30 plays  error\n"])

    def test_it_changes_with_a_result(self):
        saw = {7: "pass", 8: "fail", 30: "pass"}
        self.assertNotEqual(expected.scoreboard(self.CASES, saw),
                            expected.scoreboard(self.CASES, {**saw, 30: "fail"}))

    def test_two_results_changing_places_change_it(self):
        self.assertNotEqual(
            expected.scoreboard(self.CASES, {7: "pass", 8: "fail", 30: "fail"}),
            expected.scoreboard(self.CASES, {7: "fail", 8: "fail", 30: "pass"}))

    def test_the_video_is_not_in_it(self):
        saw = {7: "pass", 8: "fail", 30: "pass"}
        other = {**self.CASES, 30: Case("plays", video=(1, 2))}
        self.assertEqual(expected.scoreboard(self.CASES, saw),
                         expected.scoreboard(other, saw))


if __name__ == "__main__":
    unittest.main()
