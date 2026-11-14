import unittest

from scenemeta.c64 import sid


class ModelTest(unittest.TestCase):
    def test_own_tag(self):
        self.assertEqual(sid.model({"8580"}, []), "8580")

    def test_own_tag_comes_before_the_soundtracks(self):
        self.assertEqual(sid.model({"8580"}, [{"6581"}]), "8580")

    def test_soundtracks_that_agree(self):
        self.assertEqual(sid.model((), [{"6581"}, (), {"6581"}]), "6581")

    def test_both_models_is_not_known(self):
        self.assertIsNone(sid.model((), [{"6581"}, {"8580"}]))
        self.assertIsNone(sid.model({"6581", "8580"}, []))

    def test_no_tags(self):
        self.assertIsNone(sid.model((), []))
        self.assertIsNone(sid.model((), [()]))


if __name__ == "__main__":
    unittest.main()
