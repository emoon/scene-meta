import unittest

from scenemeta.amiga import diskset


class GroupTest(unittest.TestCase):
    def check(self, names, want):
        self.assertEqual(diskset.group(names), want)

    def test_letter_suffix(self):
        self.check(["Kefrens-DesertDreamB.dms", "Kefrens-DesertDreamA.adf"],
                   [["Kefrens-DesertDreamA.adf", "Kefrens-DesertDreamB.dms"]])

    def test_dash_letter(self):
        self.check(["Spaceballs-9Fingers-A.dms", "Spaceballs-9Fingers-B.dms"],
                   [["Spaceballs-9Fingers-A.dms", "Spaceballs-9Fingers-B.dms"]])

    def test_disk_n_of_m(self):
        self.check(["reel-disk-2-of-2.adf", "reel-disk-1-of-2.adf"],
                   [["reel-disk-1-of-2.adf", "reel-disk-2-of-2.adf"]])

    def test_unmarked_first_disk(self):
        self.check(["demo-d2.adf", "demo.adf"], [["demo.adf", "demo-d2.adf"]])

    def test_lone_marker_is_not_a_set(self):
        self.check(["Sanity-Arte.dms"], [["Sanity-Arte.dms"]])

    def test_machine_versions_are_not_a_set(self):
        self.check(["at1200.adf", "at500.adf"], [["at1200.adf"], ["at500.adf"]])

    def test_duplicate_disk_prefers_adf(self):
        self.check(["demo-A.dms", "demo-A.adf", "demo-B.adf"],
                   [["demo-A.adf", "demo-B.adf"]])

    def test_gap_is_incomplete(self):
        s = diskset.group(["tbl-tt01.dms", "tbl-tt02.dms", "tbl-tt04.dms"])[0]
        self.assertFalse(diskset.is_complete(s))
        self.assertTrue(diskset.is_complete(["demo-1.adf", "demo-2.adf"]))


if __name__ == "__main__":
    unittest.main()
