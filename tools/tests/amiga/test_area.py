import unittest

from scenemeta.amiga import area
from scenemeta.amiga.emulator import RunLog
from scenemeta.core.result import Area


def mode(rows, cols, frames=1000, res=0, lace=False, os=False):
    """One mode of a ``display status``: ``rows`` and ``cols`` are ``[from,
    to, frames]`` stretches."""
    return {"res": res, "lace": lace, "os": os, "frames": frames,
            "rows": rows, "cols": cols}


def display(rows, cols, frames=1000):
    """A ``display status`` of a run in lores alone."""
    return {"modes": [mode(rows, cols, frames)] if frames else []}


def size(*modes):
    found = area.shown({"modes": list(modes)})
    return found and found[0]


COLS = [[129, 449, 1000]]


class ShownTest(unittest.TestCase):
    def test_the_lines_and_columns_that_showed_bitplanes(self):
        # Eon: DIWSTRT $5281, DIWSTOP $06c1.
        self.assertEqual(size(mode([[83, 263, 1000]], COLS)), (320, 180))

    def test_a_full_frame_title_before_a_smaller_main_part_is_of_the_area(self):
        # Two seconds of it: a player that cuts to the area must show it whole.
        rows = [[45, 83, 100], [83, 263, 1000], [263, 301, 100]]
        self.assertEqual(size(mode(rows, COLS)), (320, 256))

    def test_a_part_drawn_into_less_does_not_change_it(self):
        rows = [[45, 83, 600], [83, 263, 1000], [263, 301, 600]]
        self.assertEqual(size(mode(rows, COLS)), (320, 256))

    def test_what_was_shown_for_a_second_is_of_the_area(self):
        rows = [[45, 83, 50], [83, 263, 1000]]
        self.assertEqual(size(mode(rows, COLS)), (320, 218))

    def test_a_gap_between_two_shown_stretches_is_inside_the_area(self):
        rows = [[45, 100, 1000], [200, 301, 1000]]
        self.assertEqual(size(mode(rows, COLS)), (320, 256))

    def test_one_frame_short_of_a_second_is_not_of_the_area(self):
        # The frames in which a production takes the screen over.
        rows = [[45, 83, 49], [83, 263, 1000]]
        self.assertEqual(size(mode(rows, COLS)), (320, 180))

    def test_two_parts_at_different_places_give_the_box_around_both(self):
        rows = [[40, 60, 500], [60, 220, 1000], [220, 240, 500]]
        self.assertEqual(size(mode(rows, COLS)), (320, 200))

    def test_columns_as_lines(self):
        cols = [[113, 129, 49], [129, 449, 1000], [449, 465, 49]]
        self.assertEqual(size(mode([[45, 245, 1000]], cols)), (320, 200))
        cols = [[113, 129, 50], [129, 449, 1000], [449, 465, 50]]
        self.assertEqual(size(mode([[45, 245, 1000]], cols)), (352, 200))

    def test_a_run_that_showed_no_bitplanes_has_none(self):
        self.assertIsNone(size())


class ModesTest(unittest.TestCase):
    ROWS = [[45, 301, 1000]]
    LORES = mode(ROWS, COLS)

    def test_a_mode_is_in_its_own_pixels(self):
        self.assertEqual(size(mode(self.ROWS, COLS, res=1)), (640, 256))
        self.assertEqual(size(mode(self.ROWS, COLS, res=1, lace=True)),
                         (640, 512))
        self.assertEqual(size(mode(self.ROWS, COLS, lace=True)), (320, 512))
        self.assertEqual(size(mode(self.ROWS, COLS, res=2)), (1280, 256))

    def test_the_pixels_of_the_finest_mode_however_short_its_part(self):
        # 3D Demo II: lores but for half a minute of hires interlace.
        pictures = mode([[45, 301, 60]], [[129, 449, 60]], 60, res=1,
                        lace=True)
        self.assertEqual(size(self.LORES, pictures), (640, 512))

    def test_the_box_around_what_every_mode_showed(self):
        # In its first three minutes 3D Demo II's hires interlaced picture
        # is a small one: the area is still the screen the lores parts fill.
        small = mode([[82, 264, 60]], [[209, 369, 60]], 60, res=1, lace=True)
        self.assertEqual(size(self.LORES, small), (640, 512))
        wide = mode([[45, 245, 500]], [[113, 465, 500]], 500, res=1)
        self.assertEqual(size(self.LORES, wide), (704, 256))

    def test_the_systems_own_screen_is_not_the_productions(self):
        # AmigaDOS's window while the production loads.
        dos = mode(self.ROWS, COLS, 3449, res=1, os=True)
        self.assertEqual(size(self.LORES, dos), (320, 256))

    def test_a_production_that_only_draws_through_the_system(self):
        dos = mode(self.ROWS, COLS, 300, res=1, os=True)
        self.assertEqual(size(dos), (640, 256))

    def test_a_mode_shown_under_a_second_is_none(self):
        # 6114 Fascism Sucks: one hires frame as it takes the screen over.
        flash = mode([[45, 301, 49]], [[129, 449, 49]], 49, res=1)
        self.assertEqual(size(self.LORES, flash), (320, 256))
        second = mode([[45, 301, 50]], [[129, 449, 50]], 50, res=1)
        self.assertEqual(size(self.LORES, second), (640, 256))


class DrawnTest(unittest.TestCase):
    def test_a_picture_has_two_pixels_to_a_lores_pixel_and_a_line(self):
        self.assertEqual(area.drawn([[76, 114, 716, 474]], (1, 1)), (320, 180))

    def test_what_a_share_of_the_pictures_show(self):
        full, small = [8, 24, 744, 566], [76, 114, 716, 474]
        self.assertEqual(area.drawn([full] + [small] * 4, (1, 1)), (320, 180))
        self.assertEqual(area.drawn([full] * 2 + [small] * 3, (1, 1)), (368, 271))

    def test_pictures_that_share_nothing(self):
        boxes = [[i * 10, 0, i * 10 + 10, 10] for i in range(5)]
        self.assertEqual(area.drawn(boxes, (1, 1)), (0, 0))

    def test_in_the_pixels_of_the_areas_mode(self):
        self.assertEqual(area.drawn([[76, 38, 716, 550]], (2, 2)), (640, 512))

    def test_no_picture(self):
        self.assertEqual(area.drawn([], (1, 1)), (0, 0))


class MeasuredTest(unittest.TestCase):
    def log(self, **kw):
        return RunLog([], [], 0, False, "", **kw)

    def test_the_area_and_what_the_pictures_show(self):
        log = self.log(display=display([[83, 263, 1000]], COLS),
                       boxes=[None, [76, 114, 716, 474], None])
        self.assertEqual(area.measured(log), Area(320, 180, 320, 180))

    def test_dark_top_and_bottom_rows_do_not_make_a_full_frame_smaller(self):
        # The planes are on for all 256 lines; in every scene, or in some,
        # the picture is black above and below the middle 180.
        full, dark = [76, 38, 716, 550], [76, 114, 716, 474]
        for boxes, drawn in (([dark] * 4, (320, 180)),
                             ([full] * 3 + [dark], (320, 256))):
            log = self.log(display=display([[45, 301, 1000]], COLS),
                           boxes=boxes)
            self.assertEqual(area.measured(log), Area(320, 256, *drawn))

    def test_what_the_pictures_show_is_in_the_areas_pixels(self):
        log = self.log(boxes=[[76, 38, 716, 550]], display={"modes": [
            mode([[45, 301, 1000]], COLS, res=1, lace=True)]})
        self.assertEqual(area.measured(log), Area(640, 512, 640, 512))

    def test_a_run_not_asked_to_measure_has_none(self):
        self.assertIsNone(area.measured(self.log()))

    def test_a_run_that_showed_no_bitplanes_has_none(self):
        self.assertIsNone(area.measured(self.log(
            display=display([], [], frames=0), boxes=[[8, 8, 700, 500]])))


class FieldsTest(unittest.TestCase):
    def test_320_by_180_is_tagged_16_9(self):
        self.assertEqual(area.fields(Area(320, 180)),
                         {"area": [320, 180], "aspect": "16:9"})

    def test_the_same_part_of_the_screen_in_finer_pixels_is_16_9_too(self):
        # A hires pixel is half as wide, an interlaced line half as high.
        for size in ((640, 180), (320, 360), (640, 360), (1280, 180),
                     (1280, 360)):
            self.assertEqual(area.fields(Area(*size)),
                             {"area": list(size), "aspect": "16:9"}, size)

    def test_any_other_area_is_recorded_alone(self):
        for size in ((320, 200), (640, 200), (640, 512), (352, 180)):
            self.assertEqual(area.fields(Area(*size)), {"area": list(size)},
                             size)
