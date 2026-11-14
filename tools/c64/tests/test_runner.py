import unittest

from scenedb import runner, vice


def log(crash_cycles, inserted=100, crash="emulator-exit"):
    return runner.RunLog([], set(), [runner.Flip(2, "probe", 50, inserted)],
                         crash=crash, crash_cycles=crash_cycles)


def _screen(text, lower=False):
    """``text`` as screen codes (upper-case charset, or the lower-case one)."""
    if not lower:
        return bytes(ord(c) - 64 if c.isalpha() else ord(c) for c in text.upper())
    return bytes((ord(c) if c.isupper() else ord(c) - 96) if c.isalpha() else ord(c)
                 for c in text)


class AsksForDisk(unittest.TestCase):
    def test_flip_turn_insert_requests_in_either_charset(self):
        for text in ("FLIP DISK * PRESS SPACE !", "PLEASE TURN THE DISK", "INSERT SIDE B",
                     "BITTE DISKETTE:C", "DISK OVER"):
            self.assertTrue(runner.asks_for_disk(_screen(text)), text)
        self.assertTrue(runner.asks_for_disk(_screen("Insert Side B And Press Space", lower=True)))

    def test_ordinary_text_does_not(self):
        for text in ("PRESS SPACE TO START", "THE DISKETTE BOX", "TURN UP THE VOLUME"):
            self.assertFalse(runner.asks_for_disk(_screen(text)), text)


class AnswerKey(unittest.TestCase):
    def test_yes_no_question_gets_no(self):
        self.assertEqual(runner.answer_key(_screen("DO YOU WANT TO TRAINER (Y/N)?")), "n")
        self.assertEqual(runner.answer_key(_screen("Cheat mode? (y/n)", lower=True)), "n")

    def test_answered_question_with_press_space_below_gets_space(self):
        self.assertEqual(runner.answer_key(_screen("TRAINER (Y/N)? NO?! PRESS 'SPACE' TO CONTINUE!")), "space")

    def test_press_space_text_gets_space(self):
        for text in ("PRESS SPACE TO START", "HIT SPACE", "PRESS ANY KEY", "SPACE TO CONTINUE"):
            self.assertEqual(runner.answer_key(_screen(text)), "space", text)

    def test_a_disk_request_is_never_answered(self):
        self.assertIsNone(runner.answer_key(_screen("FLIP DISK * PRESS SPACE !")))
        self.assertIsNone(runner.answer_key(_screen("INSERT SIDE B AND PRESS ANY KEY")))

    def test_other_text_gets_nothing(self):
        for text in ("READY.", "GREETINGS TO ALL", "PRESS FIRE TO PLAY", "YES AND NO"):
            self.assertIsNone(runner.answer_key(_screen(text)), text)


class CrashingFlip(unittest.TestCase):
    def test_crash_soon_after_an_insert_blames_the_flip(self):
        self.assertIsNotNone(runner.crashing_flip(log(100 + 5_000_000)))

    def test_late_crash_is_not_the_flips_fault(self):
        late = 100 + runner.CRASH_AFTER_INSERT + 1
        self.assertIsNone(runner.crashing_flip(log(late)))

    def test_no_crash_no_blame(self):
        self.assertIsNone(runner.crashing_flip(log(None, crash=None)))


if __name__ == "__main__":
    unittest.main()


class FakeViceMemory:
    """Monitor stand-in: C64 RAM plus the VIC bank / screen registers."""
    def __init__(self, dd00, d018, ram):
        self.io = {0xDD00: dd00, 0xD018: d018}
        self.ram = ram
        self.bank = "default"

    def peek(self, space, addr, length=1, bank=None):
        if bank == "io":
            return [self.io[addr]]
        return list(self.ram[addr:addr + length])


class ScreenRam(unittest.TestCase):
    def test_base_follows_vic_bank_and_d018(self):
        # CIA2 low bits are inverted: 3 is bank 0, 2 is bank 1 ($4000)
        self.assertEqual(vice.vic_screen_base(0x03, 0x15), 0x0400)
        self.assertEqual(vice.vic_screen_base(0x42, 0x7F), 0x5C00)     # Dodger story pages
        self.assertEqual(vice.vic_screen_base(0x82, 0xE7), 0x7800)     # Dodger BITTE DISKETTE
        self.assertEqual(vice.vic_screen_base(0x00, 0x10), 0xC400)

    def test_reads_the_screen_the_vic_shows_not_0400(self):
        ram = bytearray(0x10000)
        text = _screen("FLIP DISK * PRESS SPACE !")
        ram[0x7B20:0x7B20 + len(text)] = text
        screen = vice.Vice.screen_ram(FakeViceMemory(0x82, 0xE7, ram))
        self.assertTrue(runner.asks_for_disk(screen))
        self.assertFalse(runner.asks_for_disk(bytes(ram[0x400:0x400 + 1000])))

    def test_inverse_video_text_still_reads(self):
        text = bytes(c | 0x80 for c in _screen("BITTE DISKETTE:C"))
        self.assertTrue(runner.asks_for_disk(text))


class CrashCause(unittest.TestCase):
    LOG = ("Drive: Warning - ambiguous step count (2)\n"
           "***   1541 (8) CPU: JAM at $0029  \n"
           "VICE thread initiating shutdown\n" + "Resources with non default values:\n" * 40)

    def test_jam_is_named_even_when_the_log_tail_has_moved_on(self):
        crash, detail = runner.crash_cause("monitor closed (emulator died)", self.LOG)
        self.assertEqual(crash, "jam")
        self.assertIn("1541 (8) CPU: JAM at $0029", detail)

    def test_death_without_jam_stays_emulator_exit_with_log_tail(self):
        crash, detail = runner.crash_cause("monitor closed (emulator died)", "bye\n")
        self.assertEqual((crash, detail), ("emulator-exit", "bye\n"))

    def test_monitor_timeout(self):
        self.assertEqual(runner.crash_cause("monitor timeout; got ''", "")[0], "timeout")


def chain_log(*flips):
    """A RunLog with (disk, inserted, accepted) flips."""
    return runner.RunLog([], set(), [runner.Flip(d, "poll", i - 80, i, accepted=a)
                                     for d, i, a in flips])


class RefusedFlip(unittest.TestCase):
    def test_first_refused_flip_of_a_chain_that_already_flipped(self):
        log = chain_log((2, 100, True), (3, 200, True), (4, 300, False), (4, 900, False))
        self.assertEqual(runner.refused_flip(log).inserted, 300)

    def test_nothing_accepted_is_not_a_chain(self):
        self.assertIsNone(runner.refused_flip(chain_log((2, 100, False))))

    def test_all_accepted_or_no_flips(self):
        self.assertIsNone(runner.refused_flip(chain_log((2, 100, True))))
        self.assertIsNone(runner.refused_flip(chain_log()))


class RunRetries(unittest.TestCase):
    def run_with(self, logs):
        """runner.run with _run_once returning ``logs`` in turn; returns
        (result, the veto dict of every call)."""
        vetoes, it = [], iter(logs)
        orig = runner._run_once
        runner._run_once = lambda m, v, b, veto: (vetoes.append(dict(veto)), next(it))[1]
        try:
            return runner.run(None, None, 0), vetoes
        finally:
            runner._run_once = orig

    def test_refused_chain_flip_is_retried_without_that_early_insert(self):
        first = chain_log((2, 100, True), (3, 300, False))
        second = chain_log((2, 100, True), (3, 900, True))
        best, vetoes = self.run_with([first, second])
        self.assertIs(best, second)
        self.assertEqual(vetoes, [{}, {3: 300 + runner.swapwait.ACCEPT_WITHIN}])

    def test_refusal_is_retried_once_per_disk(self):
        same = lambda: chain_log((2, 100, True), (3, 300, False))
        best, vetoes = self.run_with([same(), same()])
        self.assertEqual(len(vetoes), 2)

    def test_plain_run_is_not_repeated(self):
        best, vetoes = self.run_with([chain_log((2, 100, True))])
        self.assertEqual(vetoes, [{}])
