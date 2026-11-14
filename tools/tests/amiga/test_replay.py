import unittest

from scenedb.amiga import replay
from scenedb.amiga.emulator import Sample


def samples(spec):
    """spec: ``(frame, last_dma, head cylinder of DF0)`` per sample."""
    return [Sample(frame=f, pc=0, dmacon=0, bplcon0=0, resets=0, df0="",
                   shot="", last_dma=dma, cyls=[cyl]) for f, dma, cyl in spec]


class ActionsTest(unittest.TestCase):
    ENTRY = {"disks": ["a.adf", "b.adf", "c.adf"],
             "swaps": [{"disk": 2, "at": 66.1, "key": "lmb"},
                       {"disk": 3, "at": 120.0}]}

    def test_as_written(self):
        # The key goes down 5 s after its insert.
        self.assertEqual(replay.actions(self.ENTRY), [
            (3305, "insert", 0), (3555, "click", 0), (6000, "insert", 1)])

    def test_without_the_keys(self):
        self.assertEqual(replay.actions(self.ENTRY, keys=False),
                         [(3305, "insert", 0), (6000, "insert", 1)])

    def test_key_delay(self):
        entry = {"swaps": [{"disk": 2, "at": 10, "key": "lmb", "key_delay": 1.5}]}
        self.assertEqual(replay.actions(entry),
                         [(500, "insert", 0), (575, "click", 0)])

    def test_disks_in_the_other_drives_are_not_on_the_swap_list(self):
        # With two drives disk 3 is the first one swapped in.
        entry = {"drives": 2, "swaps": [{"disk": 3, "at": 10}]}
        self.assertEqual(replay.actions(entry), [(500, "insert", 0)])

    def test_key_it_cannot_press(self):
        entry = {"swaps": [{"disk": 2, "at": 10, "key": "space"}]}
        with self.assertRaises(replay.CannotReplay):
            replay.actions(entry)


class LoadedTest(unittest.TestCase):
    def test_disk_read_past_its_first_cylinders(self):
        s = samples([(3251, 2834, 40), (3501, 3400, 0), (3751, 3700, 12)])
        self.assertEqual(replay.loaded(s, [3305]), [True])

    def test_id_check_alone_is_not_a_load(self):
        # Odyssey reads the new disk's ID at cylinder 0, then waits for the
        # mouse button.
        s = samples([(3251, 2834, 40), (3501, 3400, 0), (3751, 3400, 0)])
        self.assertEqual(replay.loaded(s, [3305]), [False])

    def test_disk_nobody_looked_at(self):
        # The head still sits where disk 1 left it.
        s = samples([(3251, 2834, 40), (3501, 2834, 40), (3751, 2834, 40)])
        self.assertEqual(replay.loaded(s, [3305]), [False])

    def test_each_disk_is_judged_until_the_next_goes_in(self):
        s = samples([(1001, 900, 30), (1251, 900, 30),      # disk 2: ignored
                     (2001, 1900, 0), (2251, 2200, 20)])    # disk 3: loaded
        self.assertEqual(replay.loaded(s, [1000, 1500]), [False, True])


class JudgeTest(unittest.TestCase):
    def test_loads_without_its_keys(self):
        self.assertEqual(replay.judge([True], [True]), "keys not needed")

    def test_loads_only_with_its_keys(self):
        self.assertEqual(replay.judge([True, True], [False, True]), "keys needed")

    def test_does_not_load_as_written(self):
        self.assertEqual(replay.judge([False], [False]), "does not replay")

    def test_entry_without_keys(self):
        self.assertEqual(replay.judge([True], None), "replays")
        self.assertEqual(replay.judge([False], None), "does not replay")


if __name__ == "__main__":
    unittest.main()
