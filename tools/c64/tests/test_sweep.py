import unittest
from unittest import mock

from scenedb import machines, runner, sweep, verdict


class Variant:
    disks = ["a.d64"]


def fake_attempt(results):
    """``results``: machine name -> (verdict string, needs_reu)."""
    ran = []

    def attempt(machine, variant, cycles):
        ran.append(machine.name)
        v, reu = results[machine.name]
        log = runner.RunLog([], set(), [])
        log.needs_reu = reu
        return sweep.Attempt(machine.name, cycles,
                             verdict.Verdict(v, 0), log)
    return attempt, ran


class Climb(unittest.TestCase):
    def climb(self, results):
        attempt, ran = fake_attempt(results)
        with mock.patch.object(sweep, "attempt", attempt):
            _, best = sweep.climb(Variant())
        return best.machine, ran

    def test_a_working_machine_stops_the_climb(self):
        best, ran = self.climb({"pal_1541": ("works", False)})
        self.assertEqual((best, ran), ("pal_1541", ["pal_1541"]))

    def test_reu_machine_is_never_tried_unprompted(self):
        _, ran = self.climb({"pal_1541": ("no-activity", False),
                             "ntsc_1541": ("no-activity", False)})
        self.assertEqual(ran, ["pal_1541", "ntsc_1541"])

    def test_a_demo_that_asks_for_a_reu_jumps_to_the_reu_machine(self):
        best, ran = self.climb({"pal_1541": ("works", True),
                                "pal_1541_reu": ("works", False)})
        self.assertEqual((best, ran), ("pal_1541_reu", ["pal_1541", "pal_1541_reu"]))


    def test_the_word_reu_on_the_reu_machine_does_not_block_a_working_demo(self):
        best, _ = self.climb({"pal_1541": ("works", True),
                              "pal_1541_reu": ("works", True)})
        self.assertEqual(best, "pal_1541_reu")


class ClimbVariant(unittest.TestCase):
    """A failing variant is retried with the title-matched file."""

    class Variant:
        disks = ["a.d64"]
        boot_disk, boot_file = 0, ""

    def run_with(self, matched_works):
        def choose(prod, variant):
            variant.boot_disk, variant.boot_file = 0, "demo /grp"

        def climb(variant):
            works = bool(variant.boot_file) and matched_works
            a, _ = fake_attempt({"pal_1541": ("works" if works else "no-activity", False)})
            att = a(machines.BY_NAME["pal_1541"], variant, 1)
            return [att], att
        v = self.Variant()
        with mock.patch.object(sweep, "choose_boot", choose), \
                mock.patch.object(sweep, "climb", climb):
            attempts, best = sweep.climb_variant(None, v)
        return v, len(attempts), best

    def test_the_matched_file_is_kept_when_it_works(self):
        v, n, best = self.run_with(True)
        self.assertEqual((v.boot_file, n, best.verdict.works), ("demo /grp", 2, True))

    def test_autostart_is_restored_when_the_matched_file_does_not_help(self):
        v, n, _ = self.run_with(False)
        self.assertEqual((v.boot_file, n), ("", 2))


class ReuText(unittest.TestCase):
    def screen(self, text):
        """``text`` as screen codes (uppercase letters are 1-26)."""
        codes = [ord(c) - 64 if "A" <= c <= "Z" else ord(c) for c in text]
        return bytes(codes).ljust(1000, b"\x20")

    def test_the_word_reu_is_found(self):
        self.assertTrue(runner.wants_reu(self.screen("THIS DEMO REQUIRES A REU WITH 512KB")))

    def test_uppercase_in_the_lowercase_charset_is_found(self):
        s = bytes([32, 82, 69, 85, 32]).ljust(1000, b"\x20")
        self.assertTrue(runner.wants_reu(s))

    def test_a_word_containing_reu_is_not(self):
        self.assertFalse(runner.wants_reu(self.screen("PREUSS AND REUSE")))


if __name__ == "__main__":
    unittest.main()
