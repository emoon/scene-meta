import pathlib
import struct
import unittest
import zlib

from scenemeta.amiga import alertshot

DATA = pathlib.Path(__file__).parent / "data"


def png(name):
    return (DATA / name).read_bytes()


def black(width, height):
    """A black 8-bit RGB PNG."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + b"\0\0\0\0"
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(1 + 3 * width) * height)))


class AlertScreenTest(unittest.TestCase):
    def test_software_failure_box(self):
        # Incal Breakdown on KS1.3, the box's text with the border blinked off.
        self.assertEqual("guru", alertshot.box(png("guru_software_failure.png")))

    def test_box_with_border(self):
        self.assertEqual("guru", alertshot.box(png("guru_blink_on.png")))

    def test_demo_screen_is_not_an_alert(self):
        self.assertEqual("", alertshot.box(png("demo_screen.png")))

    def test_unreadable_png_is_not_an_alert(self):
        self.assertEqual("", alertshot.box(b""))
        self.assertEqual("", alertshot.box(b"\x89PNG\r\n\x1a\nxx"))


class TaskHeldTest(unittest.TestCase):
    def test_requester_on_the_wb_palette(self):
        self.assertEqual("task-held", alertshot.box(png("task_held.png")))

    def test_requester_in_another_palette(self):
        self.assertEqual("task-held", alertshot.box(png("task_held_blue.png")))

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
