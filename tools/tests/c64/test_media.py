import pathlib
import tempfile
import unittest
from unittest import mock

from scenedb.c64 import config, media
from scenedb.core import catalog


def _prod(links):
    return catalog.Production(1, "T", "", ("c64",), ("Demo",), "2013", links)


class BareDiskLinksTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        p = mock.patch.object(config, "SCENEORG_DIR", self.root)
        p.start()
        self.addCleanup(p.stop)

    def _touch(self, *names, content=None):
        for n in names:
            f = self.root / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content or n.encode())    # distinct disks by default

    def test_separately_linked_sides_form_one_ordered_set(self):
        self._touch("p/demo_s2.d64", "p/demo_s1.d64", "p/demo_s3.d64")
        links = [("SceneOrgFile", f"/p/demo_s{i}.d64") for i in (1, 2, 3)]
        vs, problems = media.variants(_prod(links))
        self.assertEqual([pathlib.Path(d).name for d in vs[0].disks],
                         ["demo_s1.d64", "demo_s2.d64", "demo_s3.d64"])
        self.assertEqual(problems, [])

    def test_identical_copies_under_different_names_are_one_disk(self):
        self._touch("p/Breaker_%231.d64", "p/breaker_#1.d64", content=b"same")
        links = [("SceneOrgFile", "/p/Breaker_%231.d64"),
                 ("SceneOrgFile", "/p/breaker_#1.d64")]
        vs, _ = media.variants(_prod(links))
        self.assertEqual(len(vs[0].disks), 1)

    def test_missing_files_and_non_disk_links_are_ignored(self):
        self._touch("p/demo.prg")
        links = [("SceneOrgFile", "/p/demo.prg"), ("SceneOrgFile", "/p/gone.d64"),
                 ("BaseUrl", "https://x/y.zip")]
        self.assertEqual(media.variants(_prod(links)), ([], ["no-disk-images"]))


if __name__ == "__main__":
    unittest.main()
