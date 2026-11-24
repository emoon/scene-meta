import unittest

from scenemeta import events


class OrderedTest(unittest.TestCase):
    def test_by_time_a_disk_before_a_key_of_the_same_moment(self):
        key, disk, early = ({"at": 10.0, "key": "lmb"}, {"at": 10.0, "disk": 2},
                            {"at": 3.0, "key": "space"})
        self.assertEqual(events.ordered([key, disk, early]), [early, disk, key])


class PatientTest(unittest.TestCase):
    def test_an_event_is_done_at_its_until(self):
        self.assertEqual(
            events.patient([{"at": 10.0, "until": 40.0, "disk": 2}], 30.0),
            [{"at": 40.0, "disk": 2}])

    def test_every_later_event_is_moved_by_as_much_as_it_waited(self):
        does = [{"at": 5.0, "key": "space"},
                {"at": 10.0, "until": 40.0, "disk": 2},
                {"at": 15.0, "key": "lmb"},
                {"at": 100.0, "until": 105.0, "disk": 3, "drive": 2},
                {"at": 200.0, "key": "lmb"}]
        self.assertEqual(events.patient(does, 30.0), [
            {"at": 5.0, "key": "space"}, {"at": 40.0, "disk": 2},
            {"at": 45.0, "key": "lmb"}, {"at": 135.0, "disk": 3, "drive": 2},
            {"at": 235.0, "key": "lmb"}])

    def test_one_that_may_wait_for_ever_is_given_the_players_patience(self):
        does = [{"at": 10.0, "until": float("inf"), "key": "lmb"},
                {"at": 20.0, "disk": 2}]
        self.assertEqual(events.patient(does, 7.0),
                         [{"at": 17.0, "key": "lmb"}, {"at": 27.0, "disk": 2}])

    def test_no_window_nothing_moves_and_the_events_are_left_as_they_were(self):
        does = [{"at": 10.0, "disk": 2}, {"at": 15.0, "until": 20.0, "key": "lmb"}]
        before = repr(does)
        self.assertEqual(events.patient(does[:1], 30.0), does[:1])
        events.patient(does, 30.0)
        self.assertEqual(repr(does), before)


if __name__ == "__main__":
    unittest.main()
