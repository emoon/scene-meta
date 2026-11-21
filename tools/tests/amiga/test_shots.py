import json
import tempfile
import unittest
import pathlib
from unittest import mock

from scenemeta.amiga import shots
from scenemeta.amiga.emulator import Sample
from scenemeta.core.errors import BadEntry, CannotPlay


def sample(frame, pc=0x40000000, dmacon=0x39F):
    return Sample(frame=frame, pc=pc, dmacon=dmacon, bplcon0=0, resets=0,
                  df0="", shot="")


ROM, SHELL_DMA = 0xF813A2, 0x3F0


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


class RunningTest(unittest.TestCase):
    def test_a_demo_that_exits_to_the_shell_ends_there(self):
        s = [sample(250), sample(500), sample(750, ROM, SHELL_DMA),
             sample(1000, ROM, SHELL_DMA)]
        self.assertEqual(shots.running(s), 2)

    def test_a_demo_waiting_in_rom_with_sound_is_still_running(self):
        s = [sample(250), sample(500, ROM, 0x39F)]
        self.assertEqual(shots.running(s), 2)

    def test_a_run_that_never_left_rom_is_all_kept(self):
        # An OS-friendly demo waits in exec: that is not the shell.
        s = [sample(250, ROM, SHELL_DMA), sample(500, ROM, SHELL_DMA)]
        self.assertEqual(shots.running(s), 2)

    def test_the_shell_is_not_picked_even_if_it_looks_alive(self):
        s = [sample(250), sample(500, ROM, SHELL_DMA)]
        self.assertEqual(shots.chosen(s, [True, True], {0, 1}), [(0, 250)])


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


class CannotPlayTest(unittest.TestCase):
    def one(self, entry, error, text):
        """``_one`` raises ``error``; returns the meta filed, or None."""
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(shots.player.machines, "require_rom"), \
                mock.patch.object(shots.player.media, "variants",
                                  return_value=([], ["x"])), \
                mock.patch.object(shots.player.emulator, "run") as run:
            out = pathlib.Path(d)
            with self.assertRaisesRegex(error, text):
                shots._one(7, {"title": "x", **entry}, "a500", out)
            run.assert_not_called()
            filed = out / "7" / shots.META
            return json.loads(filed.read_text()) if filed.exists() else None

    def test_an_error_is_reported_and_leaves_the_production_undone(self):
        # A meta.json would mark it done: no media is not "no shots".
        self.assertIsNone(self.one({}, CannotPlay, "no media: x"))

    def test_an_entry_that_is_the_error_is_filed_as_one(self):
        # It is not played again until somebody changes it.
        entry = {"keys": [{"at": 10, "key": "f1"}]}
        filed = self.one(entry, BadEntry, "'f1'")
        self.assertEqual(
            (filed["status"], filed["machine"], filed["shots"]),
            ("error", "a500", []))
        self.assertIn("no way to press key 'f1'", filed["reason"])
        self.assertEqual(filed["entry"],
                         shots.entry_digest({"title": "x", **entry}))
