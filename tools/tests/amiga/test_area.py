import unittest

from scenemeta.amiga import area
from scenemeta.amiga.emulator import RunLog
from scenemeta.core.result import Area


def display(rows, cols, frames=1000):
    """A ``display status``: ``rows`` and ``cols`` are ``[from, to, frames]``
    stretches."""
    return {"frames": frames, "rows": rows, "cols": cols}


COLS = [[129, 449, 1000]]


class ShownTest(unittest.TestCase):
    def test_the_lines_and_columns_that_showed_bitplanes(self):
        # Eon: DIWSTRT $5281, DIWSTOP $06c1.
        self.assertEqual(area.shown(display([[83, 263, 1000]], COLS)),
                         (320, 180))

    def test_a_full_frame_loader_before_a_smaller_main_part_is_not_the_area(self):
        rows = [[45, 83, 100], [83, 263, 1000], [263, 301, 100]]
        self.assertEqual(area.shown(display(rows, COLS)), (320, 180))

    def test_a_part_drawn_into_less_does_not_change_it(self):
        rows = [[45, 83, 600], [83, 263, 1000], [263, 301, 600]]
        self.assertEqual(area.shown(display(rows, COLS)), (320, 256))

    def test_a_share_of_the_run_is_of_the_area(self):
        rows = [[45, 83, 250], [83, 263, 1000]]
        self.assertEqual(area.shown(display(rows, COLS)), (320, 218))

    def test_a_gap_between_two_shown_stretches_is_inside_the_area(self):
        rows = [[45, 100, 1000], [200, 301, 1000]]
        self.assertEqual(area.shown(display(rows, COLS)), (320, 256))

    def test_one_frame_short_of_the_share_is_not_of_the_area(self):
        rows = [[45, 83, 249], [83, 263, 1000]]
        self.assertEqual(area.shown(display(rows, COLS)), (320, 180))

    def test_two_parts_at_different_places_give_the_box_around_both(self):
        rows = [[40, 60, 500], [60, 220, 1000], [220, 240, 500]]
        self.assertEqual(area.shown(display(rows, COLS)), (320, 200))

    def test_columns_as_lines(self):
        cols = [[113, 129, 100], [129, 449, 1000], [449, 465, 100]]
        self.assertEqual(area.shown(display([[45, 245, 1000]], cols)),
                         (320, 200))

    def test_a_run_that_showed_no_bitplanes_has_none(self):
        self.assertIsNone(area.shown(display([], [], frames=0)))


class DrawnTest(unittest.TestCase):
    def test_a_picture_has_two_pixels_to_a_lores_pixel_and_a_line(self):
        self.assertEqual(area.drawn([[76, 114, 716, 474]]), (320, 180))

    def test_what_a_share_of_the_pictures_show(self):
        full, small = [8, 24, 744, 566], [76, 114, 716, 474]
        self.assertEqual(area.drawn([full] + [small] * 4), (320, 180))
        self.assertEqual(area.drawn([full] * 2 + [small] * 3), (368, 271))

    def test_pictures_that_share_nothing(self):
        boxes = [[i * 10, 0, i * 10 + 10, 10] for i in range(5)]
        self.assertEqual(area.drawn(boxes), (0, 0))

    def test_no_picture(self):
        self.assertEqual(area.drawn([]), (0, 0))


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

    def test_a_run_not_asked_to_measure_has_none(self):
        self.assertIsNone(area.measured(self.log()))

    def test_a_run_that_showed_no_bitplanes_has_none(self):
        self.assertIsNone(area.measured(self.log(
            display=display([], [], frames=0), boxes=[[8, 8, 700, 500]])))


class FieldsTest(unittest.TestCase):
    def test_320_by_180_is_tagged_16_9(self):
        self.assertEqual(area.fields(Area(320, 180)),
                         {"area": [320, 180], "aspect": "16:9"})

    def test_any_other_area_is_recorded_alone(self):
        self.assertEqual(area.fields(Area(320, 200, 320, 200)),
                         {"area": [320, 200]})
