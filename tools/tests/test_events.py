import unittest

from scenemeta import events


class OrderedTest(unittest.TestCase):
    def test_by_time_a_disk_before_a_key_of_the_same_moment(self):
        key, disk, early = ({"at": 10.0, "key": "lmb"}, {"at": 10.0, "disk": 2},
                            {"at": 3.0, "key": "space"})
        self.assertEqual(events.ordered([key, disk, early]), [early, disk, key])


if __name__ == "__main__":
    unittest.main()
