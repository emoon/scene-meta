import subprocess
import unittest

from scenemeta.c64 import xinput
from scenemeta.c64.xinput import Keys


class Syms(unittest.TestCase):
    def test_menu_keys_have_x_keysyms(self):
        for key in ("1", "y", "F1", "Left", "p"):
            self.assertIn(key, Keys.SYMS)

    def test_letter_p_is_not_a_joystick(self):
        self.assertNotIn("p", Keys.JOYSTICK)
        self.assertEqual(Keys.JOYSTICK["p2fire"], 2)


class Helper(unittest.TestCase):
    def test_the_press_helper_can_be_started(self):
        # Without arguments it fails, but only after Python has found it.
        r = subprocess.run(xinput.HELPER, cwd=xinput.HELPER_CWD, capture_output=True)
        self.assertNotIn(b"No module named", r.stderr)
        self.assertIn(b"IndexError", r.stderr)
