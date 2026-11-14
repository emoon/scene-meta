import unittest

from scenedb.emulator import NO_ALERT, RunLog, Sample
from scenedb import verdict

AUDIO = 0x20F    # master + all audio channels
SILENT = 0x200
PLANES = 0x5200  # 5 bitplanes


def samples(spec, alert=None):
    """spec: one char per sample: 'a' audio, 'c' screen change, '.' static,
    'g' a blinking Guru box (silent, the screen flips between two images),
    't' the static "task held" requester."""
    out = []
    for i, c in enumerate(spec):
        shot = {"c": f"s{i}", "g": f"guru{i % 2}"}.get(c, "same")
        out.append(Sample(frame=(i + 1) * 250, pc=0x1000,
                          dmacon=AUDIO if c == "a" else SILENT,
                          bplcon0=PLANES, resets=0, df0="d.adf",
                          shot=shot, alert=alert,
                          box={"g": "guru", "t": "task-held"}.get(c, "")))
    return out


def log(spec, events=(), rc=0, alert=None):
    return RunLog(samples(spec, alert), list(events), rc, False, "")


def raised(spec, alert, at):
    """A log whose LastAlert is ``alert`` from sample ``at`` on."""
    lg = log(spec, alert=NO_ALERT)
    for s in lg.samples[at:]:
        s.alert = alert
    return lg


def classify_verdict(lg):
    return verdict.classify(lg, len(lg.samples)).verdict


class ClassifyTest(unittest.TestCase):
    def test_resets_at_boot_then_running_works(self):
        # Cubic Dream resets the machine twice while it boots, then plays.
        lg = log("..aaaaaaaaaaaa")
        for s in lg.samples[1:]:
            s.resets = 2
        self.assertEqual(classify_verdict(lg), "works")

    def test_reboot_loop_is_crash(self):
        lg = log("cccccccccccccc")
        for i, s in enumerate(lg.samples):
            s.resets = i
        v = verdict.classify(lg, 14)
        self.assertEqual((v.verdict, v.crash), ("crash", "reboot"))

    def test_demo_that_restarts_itself_after_playing_works(self):
        # Podtekst resets the machine at its end and plays again.
        lg = log("a" * 30)
        for i, s in enumerate(lg.samples):
            s.resets = 2 * (i // 12)
        v = verdict.classify(lg, 30)
        self.assertEqual((v.verdict, v.crash), ("works", None))

    def test_short_lived_boots_that_keep_resetting_are_a_reboot(self):
        lg = log("a" * 30)
        for i, s in enumerate(lg.samples):
            s.resets = 2 * (i // 5)
        v = verdict.classify(lg, 30)
        self.assertEqual(v.crash, "reboot")

    def test_guru_then_restart_is_the_alert_not_a_reboot(self):
        # Two Stages: a Guru Meditation, then a click on it (or the dead-end
        # alert's own reboot) restarts the machine and the intro plays again.
        # The crash is the Guru; the replay after it must not hide it.
        lg = log("..aaaaaaaa")
        for s in lg.samples[:2]:
            s.alert = 0x4
        for s in lg.samples[2:]:
            s.resets = 2
        v = verdict.classify(lg, 10)
        self.assertEqual((v.verdict, v.crash, v.crash_frame),
                         ("crash", "alert:00000004", 250))

    def test_alert_shown_after_the_reset_is_the_crash(self):
        # KS3.0: the dead-end alert resets first; the first sample to see
        # LastAlert is already the new boot, which plays the intro again
        # (RAF Party Intro on the A1200).
        lg = raised("aaaaaaaaaa.aaaaaaaa", 0x80000003, 10)
        for s in lg.samples[10:]:
            s.resets = 2
        v = verdict.classify(lg, 19)
        self.assertEqual((v.crash, v.crash_frame), ("alert:80000003", 2750))

    def test_guru_shown_after_the_restart_then_replay(self):
        # Walec on KS3.0: the alert only shows once the machine restarted,
        # then the hard drive's startup-sequence runs the intro again.
        lg = log("aaaaaaaaa" + "." + "aaaa")
        lg.samples[9].alert = 0x81000005
        for s in lg.samples[9:]:
            s.resets = 2
        v = verdict.classify(lg, 14)
        self.assertEqual((v.verdict, v.crash, v.crash_frame),
                         ("works-then-crash", "alert:81000005", 2500))

    def test_alive_counts_before_the_crash_only(self):
        # The replay after a restart must not make a crashed run look lively
        # (the sweep ranks crashed machines by it).
        lg = log("..aaaaaaaa")
        for s in lg.samples[:2]:
            s.alert = 0x4
        for s in lg.samples[2:]:
            s.resets = 2
        self.assertEqual(verdict.classify(lg, 10).alive, 0)

    def test_audio_demo_works(self):
        v = verdict.classify(log("..aaaaaaaaaaaa"), 14)
        self.assertEqual(v.verdict, "works")

    def test_static_cli_is_no_activity(self):
        v = verdict.classify(log("cc............"), 14)
        self.assertEqual(v.verdict, "no-activity")

    def test_halt_before_alive_is_crash(self):
        ev = [{"event": "halt", "frame": 600}]
        v = verdict.classify(log("aa", ev, rc=2), 14)
        self.assertEqual((v.verdict, v.crash), ("crash", "halt"))

    def test_late_crash_after_running(self):
        ev = [{"event": "halt", "frame": 3000}]
        v = verdict.classify(log("aaaaaaaaaaaa", ev, rc=2), 20)
        self.assertEqual(v.verdict, "works-then-crash")

    def test_software_failure_is_crash(self):
        v = verdict.classify(raised("cccc..", 0x00000004, 4), 6)
        self.assertEqual(v.crash, "alert:00000004")

    def test_deadend_alert_is_crash(self):
        v = verdict.classify(raised("cccc..", 0x8100000C, 4), 6)
        self.assertEqual(v.crash, "alert:8100000c")

    def test_alert_raised_on_the_last_sample_is_crash(self):
        v = verdict.classify(raised("cccc.", 0x00000004, 4), 5)
        self.assertEqual((v.crash, v.crash_frame), ("alert:00000004", 1250))

    def test_blinking_guru_without_last_alert_is_crash(self):
        # Incal Breakdown on KS1.3: the "Software Failure" box blinks, which
        # looks like a changing screen, and LastAlert stays -1.
        v = verdict.classify(log("a" * 10 + "gggggggg", alert=NO_ALERT), 18)
        self.assertEqual((v.verdict, v.crash, v.crash_frame),
                         ("works-then-crash", "guru", 2750))
        self.assertEqual(v.alive, 10)

    def test_blinking_guru_never_counts_as_alive(self):
        v = verdict.classify(log("aaa" + "g" * 20, alert=NO_ALERT), 23)
        self.assertEqual((v.verdict, v.alive), ("crash", 3))

    def test_alert_box_the_demo_plays_on_after_is_not_a_crash(self):
        # A demo's own "press left button for 1MB" prompt.
        v = verdict.classify(log("gggaaaaaaaaaa", alert=NO_ALERT), 13)
        self.assertEqual((v.verdict, v.crash), ("works", None))

    def test_task_held_requester_is_a_crash(self):
        # KS1.x: Intuition's requester for a crashed task; LastAlert stays -1.
        v = verdict.classify(log("aaaaaaaa" + "t" * 6, alert=NO_ALERT), 14)
        self.assertEqual((v.verdict, v.crash, v.crash_frame),
                         ("works-then-crash", "task-held", 2250))
        v = verdict.classify(log("t" * 8, alert=NO_ALERT), 8)
        self.assertEqual((v.verdict, v.crash), ("crash", "task-held"))

    def test_task_held_requester_never_counts_as_alive(self):
        v = verdict.classify(log("aaa" + "t" * 8, alert=NO_ALERT), 11)
        self.assertEqual(v.alive, 3)

    def test_stale_alert_while_playing_is_ignored(self):
        # Exile: a value that decodes sits in LastAlert from early on while
        # the demo plays to the end of the run. The run ending does not
        # make it a crash.
        v = verdict.classify(raised("..aaaaaaaaaa", 0x0C400002, 2), 12)
        self.assertEqual((v.verdict, v.crash), ("works", None))

    def test_data_in_last_alert_on_the_last_sample_is_ignored(self):
        # BBS-Fax Trackmo keeps changing data at ExecBase+$202; one value
        # lands on the last sample while the music plays.
        v = verdict.classify(raised("aaaaaaaaaa", 0x22841368, 9), 10)
        self.assertEqual((v.verdict, v.crash), ("works", None))

    def test_garbage_alert_on_running_demo_is_ignored(self):
        v = verdict.classify(log("a" * 12, alert=0xE6001300), 12)
        self.assertEqual((v.verdict, v.crash), ("works", None))

    def test_ended_demo(self):
        v = verdict.classify(log("aaaaaaaaaa" + "." * 10), 20)
        self.assertEqual((v.verdict, v.ended_frame), ("works", 2500))

    def test_copper_driven_demo_with_bplcon0_zero_at_the_snapshot_works(self):
        # The snapshot is taken before the copper loads bplcon0: a demo
        # that sets it from the copper list reads 0 there for its whole run.
        lg = log("c" * 14)
        for s in lg.samples:
            s.bplcon0, s.dmacon = 0, 0x3F0
        self.assertEqual(classify_verdict(lg), "works")

    def test_changing_screen_without_bitplane_dma_is_no_activity(self):
        lg = log("c" * 14)
        for s in lg.samples:
            s.dmacon = 0x200
        self.assertEqual(classify_verdict(lg), "no-activity")

    def test_static_screen_with_bitplane_dma_is_no_activity(self):
        lg = log("." * 14)
        for s in lg.samples:
            s.dmacon = 0x3F0
        self.assertEqual(classify_verdict(lg), "no-activity")

    def test_short_tune_that_ends_at_a_prompt_is_works_short(self):
        v = verdict.classify(log("aaaa" + "." * 10), 14)
        self.assertEqual((v.verdict, v.alive, v.ended_frame),
                         ("works-short", 4, 1000))
        self.assertFalse(v.works)

    def test_a_flicker_before_a_prompt_is_not_works_short(self):
        v = verdict.classify(log("c" + "." * 13), 14)
        self.assertEqual(v.verdict, "no-activity")

    def test_short_run_still_going_is_no_activity(self):
        v = verdict.classify(log("." * 8 + "aaaa"), 12)
        self.assertEqual(v.verdict, "no-activity")

    def test_short_run_that_crashed_is_crash(self):
        v = verdict.classify(raised("aaaa" + "." * 10, 0x8000000B, 5), 14)
        self.assertEqual(v.verdict, "crash")

    def test_swaps(self):
        ev = [{"event": "swap-poll", "frame": 4727},
              {"event": "autoswap", "frame": 4727, "disk": 2},
              {"event": "autoswap-click", "frame": 4987},
              {"event": "swap-idle", "frame": 9000},
              {"event": "autoswap", "frame": 9000, "disk": 3}]
        self.assertEqual(verdict.swaps(RunLog([], ev, 0, False, "")),
                         [(4727, 2, "poll+click"), (9000, 3, "idle")])


class SwapsTest(unittest.TestCase):
    def test_rolled_back_insert_is_dropped(self):
        ev = [{"event": "swap-reread", "frame": 100},
              {"event": "autoswap", "frame": 100, "disk": 2},
              {"event": "autoswap-rollback", "frame": 1200},
              {"event": "swap-reread", "frame": 5000},
              {"event": "autoswap", "frame": 5000, "disk": 2}]
        self.assertEqual(verdict.swaps(RunLog([], ev, 0, False, "")),
                         [(5000, 2, "reread")])

    def test_swap_the_demo_crashed_on_is_not_played(self):
        # Predators' Megademo loops on disk 1; disk 2 forced in at a poll
        # halts it two samples later.
        lg = log("a" * 20, [{"event": "halt", "frame": 4000}], rc=2)
        sw = [(3500, 2, "poll+click")]
        v = verdict.classify(lg, 20)
        self.assertEqual(verdict.played_swaps(lg, sw, v), [])

    def test_swap_played_before_the_end_crash_counts(self):
        # RAF's Megademo plays disk 2, then reboots at its end.
        lg = log("a" * 20, [{"event": "halt", "frame": 4750}], rc=2)
        for sm in lg.samples:
            sm.last_dma = 1200 if sm.frame > 1200 else -1
        sw = [(1000, 2, "poll")]
        v = verdict.classify(lg, 20)
        self.assertEqual(verdict.played_swaps(lg, sw, v), sw)

    def test_swap_nobody_read_is_not_played(self):
        # Guignols Dance 2: disk 1 loads everything by frame 5261, the
        # detector then inserts disk 3 into a demo that never reads it.
        lg = log("a" * 20)
        for sm in lg.samples:
            sm.last_dma = 5261
        sw = [(6768, 3, "idle")]
        v = verdict.classify(lg, 20)
        self.assertEqual(verdict.played_swaps(lg, sw, v), [])
        self.assertEqual(verdict.disks_reached(lg, [], 1, 3), 1)

    def test_swap_read_after_the_insert_is_played(self):
        lg = log("a" * 40)
        for sm in lg.samples:
            sm.last_dma = 7000 if sm.frame > 7000 else 5261
        sw = [(6768, 3, "idle")]
        v = verdict.classify(lg, 40)
        self.assertEqual(verdict.played_swaps(lg, sw, v), sw)

    def test_disks_reached_counts_read_drives(self):
        lg = RunLog([], [], 0, False, "", max_cyl=[40, 30, 2, -1])
        self.assertEqual(verdict.disks_reached(lg, [], 3, 3), 2)



class ScheduledSwapAcceptedTest(unittest.TestCase):
    def swapped(self, last_dma_at, df0="2-b.adf"):
        lg = log("." * 60, [{"event": "scheduled-swap", "frame": 3001,
                             "inserted": "/tmp/x/df/2-b.adf", "disk": 2}])
        for s in lg.samples:
            s.df0 = "d.adf" if s.frame <= 3001 else df0
            s.last_dma = 2700 if s.frame < last_dma_at else last_dma_at
        return verdict.swaps(lg)

    def test_read_long_after_the_insert(self):
        # The demo plays 9000 frames before it reads the disk it asked for.
        self.assertEqual(self.swapped(12236), [(3001, 2, "scheduled")])

    def test_no_read_with_the_disk_in(self):
        self.assertEqual(self.swapped(2700), [])

    def test_disk_taken_out_again(self):
        self.assertEqual(self.swapped(4500, df0="d.adf"), [])


if __name__ == "__main__":
    unittest.main()
