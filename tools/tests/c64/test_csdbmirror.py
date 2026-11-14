import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.c64 import config, csdbmirror

CATALOGUE = [
    '{"category":26,"id":"782","name":"Fun Dice","siteCategory":0}',
    '{"category":1,"id":"782","name":"Coma Light 11","siteCategory":1}',
    '{"category":1,"id":"902","name":"Triage","siteCategory":1}',
    '{"category":16,"id":"902","name":"Glurk","siteCategory":0}',
    '{"category":7,"id":"264482","name":"Enterprise Computing","siteCategory":17}',
]


class TakenTest(unittest.TestCase):
    def test_the_first_item_of_an_id_has_the_directory(self):
        self.assertEqual(csdbmirror.taken(CATALOGUE), {"782"})


class DirectoryTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        (self.root / "catalogue.jsonl").write_text("\n".join(CATALOGUE))
        for id_ in ("782", "902"):
            (self.root / id_).mkdir()
        for name, value in (("CSDB_DIR", self.root),
                            ("ASSEMBLY64_CATALOGUE", self.root / "catalogue.jsonl")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        csdbmirror._taken.cache_clear()
        self.addCleanup(csdbmirror._taken.cache_clear)

    def test_release_directory(self):
        self.assertEqual(csdbmirror.directory(902), self.root / "902")

    def test_directory_of_another_collections_item_is_not_the_release(self):
        self.assertIsNone(csdbmirror.directory("782"))

    def test_release_the_mirror_lacks(self):
        self.assertIsNone(csdbmirror.directory(264482))


if __name__ == "__main__":
    unittest.main()
