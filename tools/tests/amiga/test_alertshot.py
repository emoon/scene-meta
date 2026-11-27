import pathlib
import struct
import unittest
import zlib

from scenemeta.amiga import alertshot

DATA = pathlib.Path(__file__).parent / "data"


def png(name):
    return (DATA / name).read_bytes()


def make_rgb(width, height, draw):
    """Build an 8-bit RGB PNG calling ``draw(x, y) -> (r, g, b)`` or sparse rows."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + b"\0\0\0\0"
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(draw(y))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw))))


def black(width, height):
    """A black 8-bit RGB PNG."""
    return make_rgb(width, height, lambda y: bytes(3 * width))


class AlertScreenTest(unittest.TestCase):
    def test_software_failure_box(self):
        # Incal Breakdown on KS1.3, the box's text with the border blinked off.
        self.assertEqual("guru", alertshot.box(png("guru_software_failure.png")))

    def test_box_with_border(self):
        self.assertEqual("guru", alertshot.box(png("guru_blink_on.png")))

    def test_box_above_the_screen_it_pushed_down(self):
        # Colour Me AGA on KS1.3: a recoverable alert, the AmigaDOS window
        # still showing above and below it.
        self.assertEqual("guru", alertshot.box(png("guru_over_cli.png")))

    def test_box_above_the_screen_with_the_border_blinked_off(self):
        self.assertEqual("guru",
                         alertshot.box(png("guru_over_cli_blink_off.png")))

    def test_text_a_demo_shows_with_display_alert_is_not_a_guru(self):
        # Tankstellenbande!: its credits, taller than exec's box.
        self.assertEqual("", alertshot.box(png("display_alert_text.png")))

    def test_demo_screen_is_not_an_alert(self):
        self.assertEqual("", alertshot.box(png("demo_screen.png")))

    def test_unreadable_png_is_not_an_alert(self):
        self.assertEqual("", alertshot.box(b""))
        self.assertEqual("", alertshot.box(b"\x89PNG\r\n\x1a\nxx"))

    def test_solid_red_intuition_title_bar_is_not_a_guru(self):
        # Colour Me AGA exits to a black Intuition screen with a solid red title bar.
        w, h = 320, 256
        red_row = bytes([200, 0, 0]) * w
        blk_row = bytes(3 * w)
        img = make_rgb(w, h, lambda y: red_row if 10 <= y < 30 else blk_row)
        self.assertEqual("", alertshot.box(img))

    def test_red_top_box_with_bottom_half_scroller_is_not_a_guru(self):
        # Parody Guru box in top quarter + animated scroller in bottom half.
        w, h = 320, 256
        blk_row = bytes(3 * w)
        red_text = bytes([0, 0, 0]) * 80 + bytes([200, 0, 0]) * 100 + bytes([0, 0, 0]) * 140
        img = make_rgb(w, h, lambda y: red_text if (20 <= y < 24 or 200 <= y < 205) else blk_row)
        self.assertEqual("", alertshot.box(img))

    def test_red_text_on_dark_night_sky_is_not_a_guru(self):
        # Xmas Lights: bright red text in top band over dark teal (r+g+b=20) sky.
        w, h = 320, 256
        sky_row = bytes([0, 10, 10]) * w
        red_text = bytes([0, 10, 10]) * 80 + bytes([200, 0, 0]) * 100 + bytes([0, 10, 10]) * 140
        img = make_rgb(w, h, lambda y: red_text if 20 <= y < 25 else sky_row)
        self.assertEqual("", alertshot.box(img))


class TaskHeldTest(unittest.TestCase):
    def test_requester_on_the_wb_palette(self):
        self.assertEqual("task-held", alertshot.box(png("task_held.png")))

    def test_requester_in_another_palette(self):
        self.assertEqual("task-held", alertshot.box(png("task_held_blue.png")))

    def test_the_alert_above_the_screen_it_pushed_down(self):
        # Journey to VIP on KS1.3: the same words as an alert, not a
        # requester, over the AmigaDOS window.
        self.assertEqual("task-held",
                         alertshot.box(png("task_held_alert_over_cli.png")))

    def test_requester_over_a_demo_screen(self):
        self.assertEqual("task-held", alertshot.box(png("task_held_demo_bg.png")))

    def test_a_screen_too_small_for_the_requester_is_not_it(self):
        x0, _, x1, y1 = alertshot.HELD_BOX
        for width, height in ((x0, 2 * y1), (x0 + 100, 2 * y1), (x1 - 1, 2 * y1),
                              (x1, 2 * y1 - 2)):
            self.assertEqual("", alertshot.box(black(width, height)),
                             (width, height))
        self.assertEqual("", alertshot.box(black(x1, 2 * y1)))

    def test_other_requester_is_not_it(self):
        self.assertEqual("", alertshot.box(png("asl_requester.png")))
