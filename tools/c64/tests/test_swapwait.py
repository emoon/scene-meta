import json
import pathlib
import unittest

from scenedb import swapwait
from scenedb.swapwait import Sample

SEC = 1_000_000


def series(seconds, drive, shot=lambda i: "x", start=0):
    """One sample per second of C64 time with a constant drive port."""
    return [Sample(start + i * SEC, 0x0400, drive, shot(i))
            for i in range(seconds)]


class Trigger(unittest.TestCase):
    def test_spinning_frozen_drive_under_a_still_prompt_is_a_poll(self):
        self.assertEqual(swapwait.trigger(series(30, 0xD6)), "poll")

    def test_spinning_drive_under_animation_needs_a_long_quiet(self):
        moving = lambda i: str(i)
        self.assertIsNone(swapwait.trigger(series(60, 0xD6, shot=moving)))
        self.assertEqual(swapwait.trigger(series(80, 0xD6, shot=moving)), "poll")

    def test_short_poll_is_not_enough(self):
        self.assertIsNone(swapwait.trigger(series(10, 0xD6)))

    def test_sync_bit_flipping_does_not_unfreeze(self):
        s = series(30, 0xDE)
        for i, x in enumerate(s):
            x.drive = 0xDE if i % 2 else 0x5E        # error LED, sync toggling
        self.assertEqual(swapwait.trigger(s), "poll")

    def test_working_drive_is_not_waiting(self):
        s = series(40, 0xD6)
        for i, x in enumerate(s):
            x.drive = 0xD6 if i % 2 else 0xD4        # head stepping
        self.assertIsNone(swapwait.trigger(s))

    def test_stopped_drive_with_still_screen_is_idle(self):
        self.assertEqual(swapwait.trigger(series(40, 0xF0)), "idle")

    def test_stopped_drive_with_looping_prompt_is_idle(self):
        s = series(40, 0xD2, shot=lambda i: str(i % 4))   # spinning disk icon
        self.assertEqual(swapwait.trigger(s), "idle")

    def test_stopped_drive_under_a_playing_part_is_not(self):
        s = series(60, 0xF0, shot=lambda i: str(i))
        self.assertIsNone(swapwait.trigger(s))

    def test_long_stopped_drive_under_animation_is_a_probe(self):
        s = series(160, 0xF0, shot=lambda i: str(i))
        self.assertEqual(swapwait.trigger(s), "probe")

    def test_probe_needs_the_long_quiet(self):
        s = series(100, 0xF0, shot=lambda i: str(i))
        self.assertIsNone(swapwait.trigger(s))

    def test_probe_backs_off_longer(self):
        self.assertGreater(swapwait.backoff("probe"), swapwait.backoff("idle"))

    def test_blinking_led_does_not_unfreeze_a_prompt(self):
        s = series(40, 0x70)
        for i, x in enumerate(s):
            x.drive = 0x78 if i % 2 else 0x70        # LED blinks, motor off
        self.assertEqual(swapwait.trigger(s), "idle")

    def test_short_rare_blips_do_not_restart_the_quiet(self):
        s = series(200, 0x52, shot=lambda i: str(i))
        for i in (60, 150):
            s[i].drive = 0x56                        # one-sample motor pulse
        self.assertEqual(swapwait.trigger(s), "probe")

    def test_dense_activity_still_restarts_the_quiet(self):
        s = series(200, 0x52, shot=lambda i: str(i))
        for i in range(0, 200, 10):
            s[i].drive = 0x56                        # a pulse every 10 s
        self.assertIsNone(swapwait.trigger(s))

    def test_a_lasting_change_restarts_the_quiet(self):
        s = series(200, 0x52, shot=lambda i: str(i))
        for x in s[100:]:
            x.drive = 0x56
        self.assertEqual(swapwait.quiet_since(s), 100 * SEC)

    def test_floor_hides_earlier_quiet(self):
        s = series(30, 0xD6)
        self.assertIsNone(swapwait.trigger(s, floor=25 * SEC))


def pulsing(seconds, base=0xD2, first=0):
    """Motor bit only, on 2 s / off 3 s, from ``first``: a loader asking the
    drive whether a disk is there."""
    s = series(seconds, base)
    for i, x in enumerate(s):
        if i >= first and (i - first) % 5 < 2:
            x.drive = base | 0x04
    return s


class Pulse(unittest.TestCase):
    def test_motor_pulse_train_under_animation_is_a_poll(self):
        moving = lambda i: str(i)
        s = pulsing(100, first=10)
        for x in s:
            x.shot = moving(x.cycles)
        self.assertEqual(swapwait.pulse_since(s), 10 * SEC)
        self.assertEqual(swapwait.trigger(s), "poll")

    def test_pulses_need_to_come_fast_and_often(self):
        s = series(100, 0x52)
        for i in (30, 60, 90):
            s[i].drive = 0x56
        self.assertIsNone(swapwait.pulse_since(s))
        s = pulsing(14, first=10)                     # two pulses only
        self.assertIsNone(swapwait.pulse_since(s))

    def test_stepper_move_ends_the_train(self):
        s = pulsing(100)
        for x in s[50:]:
            x.drive ^= 0x01
        self.assertEqual(swapwait.pulse_since(s), 50 * SEC)

    def test_floor_hides_earlier_pulses(self):
        self.assertIsNone(swapwait.pulse_since(pulsing(100), floor=98 * SEC))

    def test_pulses_after_an_insert_are_not_a_read(self):
        s = pulsing(100)
        self.assertTrue(swapwait.read_after(s, 20 * SEC))
        self.assertFalse(swapwait.read_after(s, 20 * SEC, pulsing=True))
        s[80].drive ^= 0x01                           # but the stepper moves
        self.assertTrue(swapwait.read_after(s, 20 * SEC, pulsing=True))


class ReadAfter(unittest.TestCase):
    def test_write_protect_sensor_alone_is_not_a_read(self):
        s = series(20, 0xD6)
        s[12].drive = 0xC6                           # bit 4 only
        self.assertFalse(swapwait.read_after(s, insert_cycles=2 * SEC))

    def test_a_reaction_inside_the_old_settle_time_counts(self):
        s = series(20, 0xDE)
        for x in s[4:]:
            x.drive = 0xD2                           # motor off, 2 s after insert
        self.assertTrue(swapwait.read_after(s, insert_cycles=2 * SEC))

    def test_drive_moved_since_ignores_what_came_before(self):
        s = series(20, 0xD6)
        s[3].drive = 0xD4
        self.assertFalse(swapwait.drive_moved_since(s, 10 * SEC))

    def test_moved_on_needs_new_screens_after_a_still_prompt(self):
        s = series(30, 0xD6, shot=lambda i: "p" if i < 10 else str(i))
        self.assertTrue(swapwait.moved_on(s, 2 * SEC, {"p"}))
        self.assertFalse(swapwait.moved_on(s, 2 * SEC, None))
        self.assertFalse(swapwait.moved_on(series(30, 0xD6, lambda i: "p"),
                                           2 * SEC, {"p"}))

    def test_screens_after_our_own_key_press_are_the_key_not_the_disk(self):
        # A menu that waits for a key moves on when the key comes, from memory:
        # that says nothing about the disk (Summer Games menu + p2fire).
        s = series(30, 0xD6, shot=lambda i: "p" if i < 10 else str(i))
        self.assertFalse(swapwait.moved_on(s, 2 * SEC, {"p"}, until=10 * SEC))
        self.assertTrue(swapwait.moved_on(s, 2 * SEC, {"p"}, until=40 * SEC))

    def test_summer_games_menu_is_not_a_flip(self):
        # Real run (pilot 345987, disk 2 inserted at 122M): the drive never read
        # after the insert; space/fire at the menu made the flags screen appear.
        d = json.loads((pathlib.Path(__file__).parent / "data/summer_games_flip2.json").read_text())
        s = [swapwait.Sample(*x) for x in d["samples"]]
        prompt = set(d["prompt"])
        self.assertFalse(swapwait.read_after(s, d["inserted"]))
        self.assertTrue(swapwait.moved_on(s, d["inserted"], prompt))
        self.assertFalse(swapwait.moved_on(s, d["inserted"], prompt, d["first_key"]))

    def test_port_moving_after_settle_counts(self):
        s = series(20, 0xD6)
        s[12].drive = 0xD4
        self.assertTrue(swapwait.read_after(s, insert_cycles=2 * SEC))

    def test_sensor_noise_right_after_the_insert_does_not(self):
        s = series(20, 0xD6)
        s[3].drive = 0xC6
        self.assertFalse(swapwait.read_after(s, insert_cycles=2 * SEC))

    def test_frozen_port_means_refused(self):
        self.assertFalse(swapwait.read_after(series(20, 0xD6), 2 * SEC))


if __name__ == "__main__":
    unittest.main()
