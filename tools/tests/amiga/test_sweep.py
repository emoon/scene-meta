import pathlib
import tempfile
import types
from unittest import mock
import unittest
from unittest import mock

from scenemeta.amiga import emulator, machines, media, player, sweep, verdict
from scenemeta.amiga.emulator import RunLog, Sample
from scenemeta.core.errors import CannotPlay


def attempt(last_dmas, swaps=(), crash_frame=None):
    """One sample per 250 frames, with the last disk read seen so far."""
    samples = [Sample(frame=(i + 1) * 250, pc=0, dmacon=0, bplcon0=0,
                      resets=0, df0="", shot="", last_dma=d)
               for i, d in enumerate(last_dmas)]
    log = RunLog(samples, [], 0, False, "")
    v = verdict.Verdict("works-then-crash", 0, "alert:0000000b", crash_frame) \
        if crash_frame else None
    return sweep.Attempt("a500", 0, v, log, list(swaps))


class SwapFramesTest(unittest.TestCase):
    def test_after_last_read_then_first_pause(self):
        # The Prey: loads to 2298, plays, one more read at 5132 (DOS
        # looking for PREY2:), then plays on. It wants disk 2 in during
        # the first pause, not after the last read.
        dmas = [240, 490, 740, 990, 1240, 1490, 1740, 1990, 2240, 2298,
                2298, 2298] + [2298] * 8 + [5132] * 40
        self.assertEqual(sweep.swap_frames(attempt(dmas)), [6632, 2750])

    def test_crash_asking_for_the_disk(self):
        # Absolute Inebriation: loads to 2701, plays, reads disk 1 again at
        # 12234 looking for disk 2 and Gurus at 13751. The 30 s after that
        # read is past the crash; the pause is where the disk goes in.
        dmas = [243 + 250 * i for i in range(10)] + [2701] * 38 + [12626] * 5
        self.assertEqual(
            sweep.swap_frames(attempt(dmas, crash_frame=13751)), [3000])

    def test_no_pause_in_a_load(self):
        # Reads 250 frames apart are one load, not a pause (Breakdown's
        # boot read at 500 once made "insert at 500" the first guess).
        dmas = [240, 500, 500, 740, 990, 1240, 1490] + [1490] * 10
        self.assertEqual(sweep.swap_frames(attempt(dmas)), [2000])

    def test_nothing_without_a_quiet_end(self):
        self.assertEqual(sweep.swap_frames(attempt([240, 490, 740])), [])

    def test_after_the_last_swap(self):
        # Disk 2 went in at 3000: only pauses after it count.
        dmas = [240, 490] + [490] * 10 + [3240, 3490] + [3490] * 20
        self.assertEqual(
            sweep.swap_frames(attempt(dmas, [(3000, 2, "poll")])),
            [4990, 3750])


class WaitsForClickTest(unittest.TestCase):
    def tries(self, crash, quiet=True):
        flags = [False] * 12 if quiet else [True] * 12
        samples = [Sample(frame=(i + 1) * 250, pc=0, dmacon=0x200 if not f
                          else 0x20F, bplcon0=0, resets=0, df0="", shot="s")
                   for i, f in enumerate(flags)]
        a = sweep.Attempt("a500", 0, verdict.Verdict("no-activity", 0, crash),
                          RunLog(samples, [], 0, False, ""), [])
        return [a]

    def test_prompt_is_worth_a_click(self):
        self.assertTrue(sweep.waits_for_click(self.tries(None)))

    def test_guru_is_not(self):
        self.assertFalse(sweep.waits_for_click(self.tries("alert:00000004")))

    def test_running_demo_is_not(self):
        self.assertFalse(sweep.waits_for_click(self.tries(None, quiet=False)))


class ClicksToStartTest(unittest.TestCase):
    def clicked(self, spec, crash):
        samples = [Sample(frame=(i + 1) * 250 + 1, pc=0,
                          dmacon=0x20F if c == "a" else 0x200, bplcon0=0,
                          resets=0, df0="", shot="s") for i, c in enumerate(spec)]
        v = verdict.Verdict("works-then-crash", spec.count("a"), crash)
        return sweep.Attempt("a500", 0, v, RunLog(samples, [], 0, False, ""),
                             [], click_every=1500)

    def test_click_that_started_a_demo_that_then_crashed(self):
        # Nice: comes alive after the click at 1500, Gurus after the next.
        a = self.clicked("......aaaaaa....", "alert:00000004")
        self.assertEqual(sweep.clicks_to_start(a), 1)

    def test_demo_alive_before_any_click(self):
        a = self.clicked("aaaaaa....", "alert:00000004")
        self.assertEqual(sweep.clicks_to_start(a), 0)

    def test_no_crash_no_retry(self):
        self.assertEqual(sweep.clicks_to_start(self.clicked("......aaaa", None)), 0)


class RankTest(unittest.TestCase):
    ROM_PC, RAM_PC = 0xF84EC6, 0x22408

    def tried(self, machine, pc=ROM_PC, dmacon=0x200, verdict_name="no-activity"):
        samples = [Sample(frame=(i + 1) * 250, pc=pc, dmacon=dmacon, bplcon0=0,
                          resets=0, df0="", shot="a") for i in range(8)]
        v = verdict.Verdict(verdict_name, 0)
        return sweep.Attempt(machine, 0, v, RunLog(samples, [], 0, False, ""), [])

    def best(self, *tries):
        return max(tries, key=lambda a: a.rank).machine

    def test_program_still_running_outranks_a_prompt(self):
        # KS1.3 CLI back at its prompt (pc in ROM) vs the program hanging.
        self.assertEqual(self.best(self.tried("a500"),
                                   self.tried("a1200", pc=self.RAM_PC)), "a1200")

    def test_display_on_beats_black_screen(self):
        self.assertEqual(self.best(self.tried("a500"),
                                   self.tried("a500_1mb", dmacon=0x300)),
                         "a500_1mb")

    def test_fast_ram_rung_wins_a_tie(self):
        # "not enough memory" on a1200, something else on a1200_fast.
        self.assertEqual(self.best(self.tried("a500"), self.tried("a1200"),
                                   self.tried("a1200_fast")), "a1200_fast")

    def test_tie_keeps_the_cheapest(self):
        self.assertEqual(self.best(self.tried("a500"), self.tried("a500_1mb")),
                         "a500")

    def test_working_still_outranks_progress(self):
        self.assertEqual(self.best(
            self.tried("a500", verdict_name="works"),
            self.tried("a1200", pc=self.RAM_PC, dmacon=0x300)), "a500")

class KeyRetryTest(unittest.TestCase):
    def run_tries(self, outcomes):
        """try_machine with attempt() stubbed: ``outcomes(kw)`` gives the
        verdict name for the attempt asked for. Returns the kwargs seen."""
        seen = []

        def fake(m, variant, frames, **kw):
            seen.append(kw)
            name = outcomes(kw)
            samples = [Sample(frame=(i + 1) * 250, pc=0, dmacon=0x200,
                              bplcon0=0, resets=0, df0="", shot="s")
                       for i in range(12)]
            return sweep.Attempt(
                "a500", frames, verdict.Verdict(name, 8 if name == "works" else 0),
                RunLog(samples, [], 0, False, ""), [],
                click_every=kw.get("click_every", 0),
                key_every=kw.get("key_every", 0))
        with mock.patch.object(sweep, "attempt", fake):
            tries = sweep.try_machine(machines.BY_NAME["a500"],
                                      media.Variant("floppy", ["a.adf"]), 9000)
        return seen, tries

    def test_stalled_screen_gets_a_key_retry(self):
        seen, tries = self.run_tries(
            lambda kw: "works" if kw.get("key_every") else "no-activity")
        self.assertTrue(any(kw.get("key_every") for kw in seen))
        self.assertTrue(tries[-1].verdict.works)

    def test_working_demo_gets_no_key_retry(self):
        seen, _ = self.run_tries(lambda kw: "works")
        self.assertEqual(seen, [{}])


if __name__ == "__main__":
    unittest.main()


class TryMachineTest(unittest.TestCase):
    """try_machine with the emulator replaced by a script of outcomes."""

    def run_try(self, fake, disks=2):
        calls = []

        def attempt(m, variant, frames, **kw):
            calls.append(kw)
            return fake(kw)

        variant = types.SimpleNamespace(disks=["d%d" % i for i in range(disks)])
        with mock.patch.object(sweep, "attempt", attempt):
            sweep.try_machine(types.SimpleNamespace(name="a500"), variant, 9000)
        return calls

    @staticmethod
    def outcome(kw, crash=None, alive_at=None):
        samples = []
        if alive_at is not None:
            samples = [Sample(frame=alive_at, pc=0, dmacon=0x20F, bplcon0=0,
                              resets=0, df0="", shot="s")]
        return sweep.Attempt("a500", 9000,
                             verdict.Verdict("no-activity", 0, crash),
                             RunLog(samples, [], 0, False, ""), [],
                             drives=kw.get("drives", 1),
                             click_every=kw.get("click_every", 0))

    def test_click_limit_retry_does_not_end_the_disk_set_retries(self):
        # Clicking got the intro going, then it crashed: the max_clicks
        # retry runs, and the set must still get its drives=2 attempt (the
        # walrus in that retry once rebound the disk count to the limit).
        def fake(kw):
            if kw.get("click_every") and not kw.get("max_clicks"):
                return self.outcome(kw, "alert:00000004", alive_at=1501)
            return self.outcome(kw)

        calls = self.run_try(fake)
        self.assertTrue(any(kw.get("max_clicks") for kw in calls))
        self.assertTrue(any(kw.get("drives") == 2 for kw in calls), calls)


class ClickNeededTest(unittest.TestCase):
    """A swap's click is only kept when the run without it falls short."""

    def run_try(self, without_click):
        calls = []

        def played(swaps, reached=2):
            return sweep.Attempt("a500", 9000, verdict.Verdict("works", 20),
                                 RunLog([], [], 0, False, ""), swaps,
                                 reached=reached)

        def fake(m, variant, frames, **kw):
            calls.append(kw)
            if kw.get("swap_click", True):
                return played([(26845, 2, "poll+click")])
            return without_click(played)

        v = media.Variant("floppy", ["a.adf", "b.adf"])
        with mock.patch.object(sweep, "attempt", fake):
            tries = sweep.try_machine(machines.BY_NAME["a500"], v, 72000)
        return calls, tries

    def test_disk_that_loads_without_the_click(self):
        # Desert Dream reads disk 2 slowly, from its low cylinders: the
        # detector clicks 5 s after the insert, and the load that follows
        # looks like the click's doing. Without the click it loads the same.
        calls, tries = self.run_try(lambda played: played([(26845, 2, "poll")]))
        self.assertEqual(calls, [{}, {"swap_click": False, "nudge_until": 26845,
                                      "seed": emulator.DEFAULT_SEED}])
        self.assertEqual(tries[-1].swaps, [(26845, 2, "poll")])

    def test_disk_that_waits_for_the_click(self):
        # Odyssey: "insert disk 2 and press left mouse button".
        _, tries = self.run_try(lambda played: played([], reached=1))
        self.assertEqual(tries[-1].swaps, [(26845, 2, "poll+click")])
        self.assertEqual(len(tries), 2)

    def test_run_that_also_clicks_every_30_s(self):
        # Megademo III only asks for disk 2 on the retry that clicks every
        # 30 s. Its disk goes in at 4028 and the next such click falls at
        # 4500: the run without the swap click must not make that one
        # either, or it shows nothing.
        calls = []

        def fake(m, variant, frames, **kw):
            calls.append(kw)
            got = kw.get("click_every") and kw.get("swap_click", True)
            return sweep.Attempt(
                "a500", 9000, verdict.Verdict("works", 20),
                RunLog([], [], 0, False, ""),
                [(4028, 2, "poll+click")] if got else [],
                reached=2 if got else 1,
                click_every=kw.get("click_every", 0))

        v = media.Variant("floppy", ["a.adf", "b.adf"])
        with mock.patch.object(sweep, "attempt", fake):
            tries = sweep.try_machine(machines.BY_NAME["a500"], v, 72000)
        again = [kw for kw in calls if not kw.get("swap_click", True)]
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["click_every"], sweep.CLICK_EVERY)
        self.assertEqual(again[0]["nudge_until"], 4028)
        self.assertEqual(tries[-1].swaps, [(4028, 2, "poll+click")])

    def test_no_click_no_second_run(self):
        calls = []

        def fake(m, variant, frames, **kw):
            calls.append(kw)
            return sweep.Attempt("a500", 9000, verdict.Verdict("works", 20),
                                 RunLog([], [], 0, False, ""),
                                 [(4000, 2, "poll")], reached=2)

        v = media.Variant("floppy", ["a.adf", "b.adf"])
        with mock.patch.object(sweep, "attempt", fake):
            sweep.try_machine(machines.BY_NAME["a500"], v, 72000)
        self.assertEqual(calls, [{}])


class ClicksOnlyTest(unittest.TestCase):
    """A crashed run's swap is false when the clicks alone play."""

    SET = media.Variant("floppy", ["a.adf", "b.adf"])

    def run_try(self, alone, **crashed):
        """try_machine with every detector run crashing after a clicked
        swap, and the player's run ending in verdict ``alone``. Returns
        ``(entry, seed)`` of each run the player made, and the tries."""
        calls = []

        def fake(m, variant, frames, **kw):
            return sweep.Attempt(
                "a500", 9000, verdict.Verdict("works-then-crash", 20,
                                              "alert:00000004", 5065),
                RunLog([], [], 0, False, ""), [(4055, 2, "poll+click")],
                **{"reached": 1, "seed": 5, **crashed})

        def play(ready, keys=True, keep=None, seed=emulator.DEFAULT_SEED):
            calls.append((ready, seed))
            return player.Outcome("a500", alone, [],
                                  RunLog([], [], 0, False, ""))

        with mock.patch.object(sweep, "attempt", fake), \
                mock.patch.object(player.Ready, "play", play):
            tries = sweep.try_machine(machines.BY_NAME["a500"], self.SET, 72000)
        return calls, tries

    def test_clicks_that_play_are_all_the_production_wants(self):
        calls, tries = self.run_try(verdict.Verdict("works", 20))
        (ready, seed), = calls
        self.assertEqual(ready.entry, {"keys": [{"at": 86.1, "key": "lmb"}]})
        self.assertEqual((ready.machine.name, ready.variant, seed),
                         ("a500", self.SET, 5))
        best = max(tries, key=lambda a: a.rank)
        self.assertEqual((best.swaps, best.clicks, best.reached),
                         ([], (4305,), 2))
        self.assertEqual(best.frames, 4305 + emulator.AUTOSWAP_TAIL_FRAMES)
        self.assertEqual((best.seed, best.log.events),
                         (5, [{"event": "seed", "seed": 5}]))
        self.assertEqual([(k.at, k.key) for k in best.record().keys],
                         [(86.1, "lmb")])

    def test_the_player_runs_the_clicks_with_the_detector_off(self):
        log = RunLog([], [], 0, False, "")
        with mock.patch.object(emulator, "run", return_value=log) as run:
            a = sweep.played(machines.BY_NAME["a500"], self.SET,
                             {"keys": [{"at": 86.1, "key": "lmb"}]}, 5)
        m, variant, frames, opts = run.call_args.args
        self.assertEqual((m.name, variant, frames),
                         ("a500", self.SET, 4305 + emulator.AUTOSWAP_TAIL_FRAMES))
        self.assertEqual((opts.play, opts.seed, opts.drives, opts.detects),
                         (((4305, "click", 0),), 5, 1, False))
        self.assertEqual((a.frames, a.seed, a.drives, a.swaps),
                         (frames, 5, 1, []))

    def test_a_crash_that_read_the_disk_is_still_a_false_swap(self):
        # Megademo III: the loader reads the scrambled disk B before it dies.
        _, tries = self.run_try(verdict.Verdict("works", 20), reached=2)
        best = max(tries, key=lambda a: a.rank)
        self.assertEqual((best.swaps, best.clicks), ([], (4305,)))

    def test_a_run_with_nudge_clicks_is_replayed_too(self):
        # Megademo III: the crashed run is the one that also nudged.
        _, tries = self.run_try(verdict.Verdict("works", 20), reached=2,
                                click_every=sweep.CLICK_EVERY)
        best = max(tries, key=lambda a: a.rank)
        self.assertEqual((best.swaps, best.clicks), ([], (4305,)))

    def test_clicks_that_crash_too_leave_the_swap(self):
        _, tries = self.run_try(verdict.Verdict(
            "works-then-crash", 20, "alert:00000004", 5000))
        self.assertTrue(all(a.record().keys == [] for a in tries))


class RungsTest(unittest.TestCase):
    def test_ffs_boot_disk_skips_kickstart_1(self):
        from scenemeta.amiga import media
        v = media.Variant("floppy", ["x.adf"], ffs=True)
        names = [m.name for m in sweep.rungs(v, False)]
        self.assertEqual(names, ["a1200", "a1200_fast", "a1200_030", "a1200_060"])

    def test_ordinary_disk_keeps_the_ladder(self):
        from scenemeta.amiga import media, machines
        v = media.Variant("floppy", ["x.adf"])
        self.assertEqual(sweep.rungs(v, False), machines.ladder_for(False))


class SeedTest(unittest.TestCase):
    """Runs are reproducible (a pinned RNG seed), so the retries of a demo
    that races (5316: its boot path depends on the seed) must each roll a
    different seed, or they would all repeat the first attempt's luck."""

    def run_try(self, n_disks, fake):
        from unittest import mock
        from scenemeta.amiga import machines, media
        v = media.Variant("floppy", [f"d{i}.adf" for i in range(n_disks)])
        with mock.patch.object(sweep, "attempt", fake):
            return sweep.try_machine(machines.BY_NAME["a500"], v, 9000)

    def test_each_attempt_has_its_own_seed(self):
        seeds = []

        # A stalled single disk: the click retry runs besides the first.
        stalled = attempt([240] * 12)
        stalled.verdict = verdict.Verdict("no-activity", 0)

        def fake_stalled(m, variant, frames, seed=emulator.DEFAULT_SEED, **kw):
            seeds.append(seed)
            stalled.seed = seed
            return stalled

        self.run_try(1, fake_stalled)
        self.assertGreater(len(seeds), 1)
        self.assertEqual(seeds[0], emulator.DEFAULT_SEED)
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_scheduled_swaps_keep_the_seed_of_their_base_run(self):
        calls = []
        # 5316 under seed 3 loads in 2700 frames and asks for disk 2; the
        # insert frame is only right for a run with that seed.
        dmas = [240, 490, 740, 990, 1240, 1490, 1740, 1990, 2240, 2490,
                2700] + [2700] * 25

        def fake(m, variant, frames, seed=emulator.DEFAULT_SEED, schedule=(), **kw):
            calls.append((seed, tuple(schedule)))
            a = attempt(dmas)
            a.seed = seed
            a.verdict = verdict.Verdict("no-activity", 3 if seed == 3 else 0)
            return a

        self.run_try(2, fake)
        scheduled = [c for c in calls if c[1]]
        self.assertTrue(scheduled)
        self.assertEqual({s for s, _ in scheduled}, {3})


class SeedIsRecordedTest(unittest.TestCase):
    def test_the_attempt_log_says_which_seed_it_ran(self):
        # A stored run can only be reproduced with its seed.
        from unittest import mock
        from scenemeta.amiga import machines, media
        log = RunLog([], [], 0, False, "")
        v = media.Variant("floppy", ["d0.adf"])
        with mock.patch.object(emulator, "run", return_value=log):
            a = sweep.attempt(machines.BY_NAME["a500"], v, 250, seed=7)
        self.assertEqual(a.seed, 7)
        self.assertIn({"event": "seed", "seed": 7}, a.log.events)


class RecordTest(unittest.TestCase):
    def test_frames_and_samples_become_seconds(self):
        log = RunLog([], [{"event": "halt"}], 3, False, "", b"png")
        v = verdict.Verdict("works-then-crash", 9, "halt", 30000, wants_disk=True)
        a = sweep.Attempt("a500", 72000, v, log,
                          [(26844, 2, "poll+click"), (40000, 3, "idle")],
                          drives=2, reached=3)
        r = a.record()
        self.assertEqual(
            (r.machine, r.budget, r.verdict, r.alive, r.crash, r.crash_at,
             r.ended_at, r.wants_disk, r.drives, r.reached, r.screenshot),
            ("a500", 1440.0, "works-then-crash", 45.0, "halt", 600.0, None,
             True, 2, 3, b"png"))
        self.assertEqual(r.detail, {"returncode": 3, "events": [{"event": "halt"}]})
        self.assertEqual([(s.disk, s.at, s.trigger, s.key, s.accepted) for s in r.swaps],
                         [(2, 536.88, "poll+click", "lmb", True),
                          (3, 800.0, "idle", None, True)])


class SetupTest(unittest.TestCase):
    def test_a_sweep_without_its_roms_stops_before_any_production(self):
        with tempfile.TemporaryDirectory() as empty, \
                mock.patch.object(sweep.config, "ROM_DIR",
                                  pathlib.Path(empty)), \
                mock.patch.object(sweep.driver, "run_all") as run_all:
            with self.assertRaisesRegex(CannotPlay, "kick13.rom"):
                sweep.run_all([], store=None)
        run_all.assert_not_called()

    def test_a_sweep_without_the_mirror_stops_before_any_production(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(machines, "require_roms"), \
                mock.patch.object(media.config, "DEMOZOO_DIR",
                                  pathlib.Path(d) / "demozoo"), \
                mock.patch.object(sweep.driver, "run_all") as run_all:
            with self.assertRaisesRegex(CannotPlay, "no Demozoo mirror"):
                sweep.run_all([], store=None)
        run_all.assert_not_called()

    def test_a_production_with_no_media_has_a_problem_and_no_run(self):
        prod = types.SimpleNamespace(id=7, title="x", release_date="",
                                     platforms=("Amiga OCS/ECS",))
        with mock.patch.object(media, "variants",
                               return_value=([], ["no-files-on-nas"])), \
                mock.patch.object(emulator, "run") as run:
            self.assertEqual(sweep._job(prod), (["no-files-on-nas"], []))
        run.assert_not_called()
