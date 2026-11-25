import unittest

from scenemeta.core import export


class TriesTest(unittest.TestCase):
    def test_the_first_three_in_the_order_given(self):
        entries = [{"title": "x", "machine": m} for m in "abcd"]
        self.assertEqual(export.tries(entries), entries[:3])

    def test_two_that_set_the_same_are_one_try(self):
        a = {"title": "x", "machine": "a"}
        b = {"title": "x", "machine": "b"}
        again = {"title": "x", "machine": "a", "note": "another run"}
        self.assertEqual(export.tries([a, again, a, b]), [a, b])

    def test_none(self):
        self.assertEqual(export.tries([]), [])


if __name__ == "__main__":
    unittest.main()
