import tempfile
import unittest
import pathlib

from scenemeta.amiga import shots
from scenemeta.amiga.emulator import Sample


def sample(frame):
    return Sample(frame=frame, pc=0, dmacon=0, bplcon0=0, resets=0, df0="",
                  shot="")


class SpreadTest(unittest.TestCase):
    def test_few_items_all_stay(self):
        self.assertEqual(shots.spread([1, 2, 3], 12), [1, 2, 3])

    def test_even_pick_with_both_ends(self):
        picked = shots.spread(list(range(36)), 4)
        self.assertEqual(picked, [0, 11, 23, 35])

    def test_the_count_is_capped(self):
        self.assertEqual(len(shots.spread(list(range(100)), 12)), 12)


class ChosenTest(unittest.TestCase):
    def test_only_kept_pictures_of_alive_samples(self):
        s = [sample(f) for f in (250, 500, 750, 1000)]
        alive = [False, True, True, True]
        self.assertEqual(shots.chosen(s, alive, {0, 1, 3}),
                         [(1, 500), (3, 1000)])

    def test_nothing_alive_nothing_chosen(self):
        s = [sample(250)]
        self.assertEqual(shots.chosen(s, [False], {0}), [])


class FramesTest(unittest.TestCase):
    def test_a_single_disk_gets_the_fixed_time(self):
        self.assertEqual(shots.frames_of({"title": "x"}),
                         shots.SINGLE_DISK_FRAMES)

    def test_a_set_plays_until_its_last_disk_has_loaded(self):
        entry = {"swaps": [{"disk": 2, "at": 100}]}
        self.assertEqual(shots.frames_of(entry),
                         5000 + shots.replay.TAIL_FRAMES)


class MetaTest(unittest.TestCase):
    def test_a_shot_says_where_it_came_from(self):
        m = shots.meta(7, {"title": "x"}, "a500", [("01.png", 500, (320, 256))],
                       "shots")
        self.assertEqual(m["shots"], [{"file": "01.png", "frame": 500,
                                       "seconds": 10.0, "width": 320,
                                       "height": 256}])
        self.assertEqual((m["schema"], m["id"], m["machine"]), (1, 7, "a500"))

    def test_the_entry_digest_follows_the_entry(self):
        self.assertNotEqual(shots.entry_digest({"a": 1}),
                            shots.entry_digest({"a": 2}))


class TodoTest(unittest.TestCase):
    FOUND = {1: {}, 2: {}, 3: {}}

    def test_those_without_screenshots_and_not_done(self):
        self.assertEqual(shots.todo(self.FOUND, None, {1, 2, 9}, {2}), [1])

    def test_named_ids_override_the_screenshot_filter(self):
        self.assertEqual(shots.todo(self.FOUND, [3], set(), set()), [3])

    def test_named_but_done_is_still_done(self):
        self.assertEqual(shots.todo(self.FOUND, [3], set(), {3}), [])


class PngSizeTest(unittest.TestCase):
    def test_width_and_height_from_the_header(self):
        head = shots.PNG_SIGNATURE + b"\0\0\0\rIHDR" \
            + (704).to_bytes(4, "big") + (576).to_bytes(4, "big")
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "a.png"
            p.write_bytes(head)
            self.assertEqual(shots.png_size(p), (704, 576))
