import pathlib
import unittest

from scenedb import alertshot

DATA = pathlib.Path(__file__).parent / "data"


def png(name):
    return (DATA / name).read_bytes()


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

    def test_other_requester_is_not_it(self):
        self.assertEqual("", alertshot.box(png("asl_requester.png")))
