"""Unit tests for proto-end-detect: recorder commands, notes, video, streams, analyze."""
import pathlib, sys, tempfile, unittest

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import analyze, notes, record, streams, video  # noqa: E402


def _make_rows(n, *, newpc_at=(), newram_at=(), aenergy_fn=None, awrites_fn=None,
               chan_fn=None, rom_fn=None, cop1lc_fn=None, solid_fn=None,
               alert_at=None, lastdma=-1, resets_at=()):
    rows = []
    resets = 0
    for i in range(n):
        if i in resets_at:
            resets += 1
        rows.append(dict(
            frame=i + 2,
            dmacon=0x820f,
            aw="0",
            awrites=awrites_fn(i) if awrites_fn else 0,
            aenergy=aenergy_fn(i) if aenergy_fn else 0,
            apeak=0,
            newpc=newpc_at.get(i, 0) if isinstance(newpc_at, dict) else (10 if i in newpc_at else 0),
            instr=1000,
            rom=rom_fn(i) if rom_fn else 0,
            lastdma=lastdma,
            resets=resets,
            chan=chan_fn(i) if chan_fn else "SSSS",
            alert=0x80000004 if alert_at == i else 0,
            newram=newram_at.get(i, 1 if i == 10 else 0) if isinstance(newram_at, dict)
            else (10 if i in newram_at else (1 if i == 10 else 0)),
            solid=solid_fn(i) if solid_fn else 0,
            bplcon0=0x4200,
            cop1lc=cop1lc_fn(i) if cop1lc_fn else 0x10000,
        ))
    return rows


class TestRecordCommands(unittest.TestCase):
    def test_same_frame_actions_no_zero_run_and_all_keys(self):
        out = pathlib.Path("/tmp/test-out")
        acts = [
            (500, "cmd", "disk insert 1 /tmp/d2.adf"),
            (500, "press", "return"),
            (500, "cmd", "screenshot /tmp/s.png"),
            (600, "press", "lmb"),
        ]
        cmds = record._build_commands(acts, 0, 1000, out / "trace.csv", out)
        self.assertNotIn("run frames=0", cmds)
        self.assertIn("disk insert 1 /tmp/d2.adf", cmds)
        self.assertIn("input key 68 down", cmds)
        self.assertIn("input key 68 up", cmds)
        self.assertIn("input mouse click 0", cmds)
        # Total run frames should equal 1000
        total = sum(int(c.split("=")[1]) for c in cmds if c.startswith("run frames="))
        self.assertEqual(total, 1000)


class TestNotes(unittest.TestCase):
    def test_short_repeating_loop_not_dropped_and_respects_trace_end(self):
        # 6-second loop repeating 140 times (would be dropped by old MAX_OCCUR=128)
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.notes"
            lines = []
            for rep in range(140):
                base = 1000 + rep * 300
                for step in range(30):
                    lines.append(f"{base + step * 10},0,2,{100 + (step * 17) % 300:x}\n")
            p.write_text("".join(lines))
            # Active at end of trace -> detects 300-frame (6s) loop
            res = notes.song_loop(str(p), trace_end=43200)
            self.assertIsNotNone(res)
            self.assertAlmostEqual(res[0], 300, delta=15)
            # Music stopped long before trace_end -> returns None
            self.assertIsNone(notes.song_loop(str(p), trace_end=50000))

    def test_degenerate_constant_paula_stream_rejected(self):
        # Software mixer writing the exact same buffer pointer every frame
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.notes"
            lines = [f"{f},0,0,1000\n{f},0,1,2000\n" for f in range(100, 10000, 2)]
            p.write_text("".join(lines))
            self.assertIsNone(notes.song_loop(str(p), trace_end=10000))

    def test_walkback_crosses_unaligned_silent_pause(self):
        # 95.7s period (4785 frames) with a 5.5s silent pause that falls cleanly
        # inside one 5s bucket on pass 4 without aligning on pass 3.
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.notes"
            lines = []
            period = 4785
            for rep in range(5):
                base = 500 + rep * period
                for step in range(440):  # 4400 frames of notes, then 385f pause
                    f = base + step * 10
                    if f >= 24500:
                        break
                    lines.append(f"{f},0,2,{100 + (step * 23) % 300:x}\n")
            p.write_text("".join(lines))
            res = notes.song_loop(str(p), trace_end=24500)
            self.assertIsNotNone(res)
            self.assertAlmostEqual(res[0], period, delta=25)
            # Second pass starts around 500 + 4785 = 5285, NOT stuck at ~20000
            self.assertLess(res[1], 7000)

    def test_aba_subperiod_rejected_for_true_full_period(self):
        # Like 295201 / 270755: song structure A-B-A-C where section A (3500f)
        # fills the 60s TAIL and also occurred 4500f earlier, while the true
        # period is 8000f (160s). Must pick 8000f, not 4500f.
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.notes"
            lines = []
            # Build distinct 500f/3500f sections: A (0..3500), B (3500..4500),
            # A (4500..8000) -> wait: make period=8000: B(0..1000) A(1000..4500) C(4500..5500) A'(5500..8000)...
            # Simpler: period=8000, [0..4000]=A, [4000..5000]=B, [5000..8000]=A[:3000]
            # Wait: at end=40000, [37000..40000] is A[:3000], which ALSO appeared
            # at [32000..35000] (lag 5000!) AND at [29000..32000] (lag 8000!).
            # Lag 5000 fails before 37000 (hits B vs A); lag 8000 matches all the way back!
            period = 8000
            for rep in range(5):
                base = rep * period
                for step in range(0, 800):  # 10f per step = 8000f
                    f = base + step * 10
                    if step < 300:
                        val = 100 + (step * 17) % 300       # A1 (0..3000)
                    elif step < 500:
                        val = 450 + ((step - 300) * 19) % 300  # B (3000..5000)
                    else:
                        val = 100 + ((step - 500) * 17) % 300  # A1 again (5000..8000)
                    lines.append(f"{f},0,2,{val:x}\n")
            p.write_text("".join(lines))
            res = notes.song_loop(str(p), trace_end=40000)
            self.assertIsNotNone(res)
            self.assertAlmostEqual(res[0], period, delta=50)
            self.assertLess(res[1], 10000)

    def test_walkback_crosses_long_matching_silence(self):
        # Like 310464: 8000f (160s) period with a 35s (1750f) quiet breakdown
        # every pass (7 empty 5s buckets, > old limit of 4).
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.notes"
            lines = []
            period = 8000
            for rep in range(5):
                base = 500 + rep * period
                for step in range(0, 625):  # 6250f notes, 1750f silence
                    f = base + step * 10
                    lines.append(f"{f},0,2,{100 + (step * 29) % 997:x}\n")
            p.write_text("".join(lines))
            # Trace ends during active notes (38750), with 35s silent breakdowns inside
            res = notes.song_loop(str(p), trace_end=38800)
            self.assertIsNotNone(res)
            self.assertAlmostEqual(res[0], period, delta=50)
            self.assertLess(res[1], 10000)


class TestVideo(unittest.TestCase):
    def test_chain_period_fast_on_blinking_screen(self):
        # 2000 onsets used to hang O(N^4); must return instantly
        ev = list(range(0, 40000, 20))
        self.assertEqual(video.chain_period(ev, 100, 45000, 1500), 0)

    def test_landmark_empty_slice_safe(self):
        cells = np.zeros((100, 4), dtype=np.uint64)
        kinds = [("open", 0, 0)] * 4
        self.assertEqual(video.landmark(cells, kinds, 100), 0)

    def test_long_video_loop_and_still_tail(self):
        # 45000 frames: cell 0 loops with period 18000 (360s) starting at 5000
        # cell 1 animates until 25000 then goes still (STILL_TAIL=1500)
        n = 45000
        a0 = np.arange(n, dtype=np.uint64)
        # repeat pattern of length 18000 from frame 5000
        pat = np.arange(100000, 118000, dtype=np.uint64)
        for i in range(5000, n):
            a0[i] = pat[(i - 5000) % 18000]
        kind0, p0, shown0 = video.cell_period(a0, 20000)
        self.assertEqual(kind0, "loop")
        self.assertEqual(p0, 18000)
        self.assertAlmostEqual(shown0, 23000, delta=25)

        a1 = np.arange(n, dtype=np.uint64)
        a1[25000:] = 999
        kind1, _, _ = video.cell_period(a1, 20000)
        self.assertEqual(kind1, "still")

    def test_sparse_cell_tolerates_single_frame_jitter(self):
        # Like 185204 / 89549: sparse 130-frame (2.6s) loop with one stray
        # glitch frame at frame 20000 must not push shown to 20000.
        n = 30000
        a = np.zeros(n, dtype=np.uint64)
        for base in range(500, n, 130):
            a[base:min(n, base + 65)] = 1
            a[min(n, base + 65):min(n, base + 130)] = 2
        a[20000] = 999  # single stray jitter frame
        kind, p, shown = video.cell_period(a, 15000)
        self.assertEqual(kind, "loop")
        self.assertEqual(p, 130)
        self.assertLess(shown, 1500)

    def test_repeats_from_tolerates_one_frame_period_drift(self):
        # Like 89549 (5539/5540) and 24435 (1168/1169): loop passes drift by
        # 1 frame partway through the trace; shown must still walk all the way
        # back to the start of the second pass.
        n = 20000
        pat = np.arange(1, 1170, dtype=np.uint64)
        a = np.zeros(n, dtype=np.uint64)
        pos = 1000
        pass_lens = [1169, 1169, 1168, 1168, 1168, 1168, 1168, 1168, 1168, 1168,
                     1168, 1168, 1168, 1168, 1168, 1168, 1168]
        for L in pass_lens:
            if pos >= n:
                break
            end = min(n, pos + L)
            a[pos:end] = pat[:end - pos]
            pos = end
        kind, p, shown = video.cell_period(a, 10000)
        self.assertEqual(kind, "loop")
        self.assertIn(p, (1168, 1169))
        self.assertLess(shown, 2500)


class TestStreams(unittest.TestCase):
    def test_filters_rom_pc(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.reads"
            lines = [f"{100 + i * 10},S,fc1234,{0x1000 + i:x}\n" for i in range(20)]
            p.write_text("".join(lines))
            self.assertEqual(streams.stream_end(str(p)), 0)

    def test_text_stream_separates_scrolltext_from_struct_reads(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.reads"
            # PC 0x10000 reads a 1-byte scrolltext (120 events up to frame 12000)
            # PC 0x20000 reads a mixed-stride struct (steps 6 and 8 up to frame 30000)
            lines = [f"{100 + i * 100},S,10000,{0x50000 + i:x}\n" for i in range(120)]
            addr = 0x60000
            for i in range(120):
                addr += 6 if i % 2 == 0 else 8
                lines.append(f"{18000 + i * 100},S,20000,{addr:x}\n")
            p.write_text("".join(lines))
            any_end, text_end = streams.stream_ends(str(p))
            self.assertEqual(any_end, 18000 + 119 * 100)
            self.assertEqual(text_end, 100 + 119 * 100)

    def test_2d_scanline_jumps_and_single_frame_burst_not_text_stream(self):
        # Like 23458: a 320-wide chunky buffer reader makes +1 byte reads
        # mixed with +320 scanline jumps (50% overall sequential purity), plus
        # an isolated 12-read burst in a single frame after a 150s gap.
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.reads"
            lines = []
            for row in range(100):
                base = 0x40036000 + row * 0x140
                f = 10000 + row * 10
                lines.append(f"{f},S,40021b4e,{base:x}\n")
                lines.append(f"{f},S,40021b4e,{base + 1:x}\n")
            # Isolated single-frame burst at frame 40520
            for row in range(12):
                base = 0x40043000 + row * 0x140
                lines.append(f"40520,S,40021b4e,{base:x}\n")
                lines.append(f"40520,S,40021b4e,{base + 1:x}\n")
            p.write_text("".join(lines))
            _, text_end = streams.stream_ends(str(p))
            self.assertEqual(text_end, 0)


class TestAnalyze(unittest.TestCase):
    def test_runaway_burst_after_still_screen_ignored(self):
        # Like .plong: screen goes still at 5000 (100s), runaway 50000 newpc at 44900
        n = 20000
        cells = np.zeros((n, 4), dtype=np.uint64)
        cells[:5000, 0] = np.arange(5000, dtype=np.uint64)
        rows = _make_rows(
            n,
            newpc_at={1000: 50, 4900: 20, 19950: 50000},
            newram_at={1000: 50, 4900: 20, 19950: 50000},
            aenergy_fn=lambda i: int(50000 + 40000 * np.sin(2 * np.pi * i / 3000)),
            awrites_fn=lambda i: 5,
            chan_fn=lambda i: "PPPP",
        )
        v = analyze.verdict(rows, cells, song=(3000, 6000))
        self.assertLess(v["last_new"], 110.0)
        self.assertLess(v["end"], 150.0)

    def test_pre_exit_still_screen_detected(self):
        # Like Greenday: active until 5000 (100s), still until 12000 (240s), then OS exit
        n = 15000
        cells = np.zeros((n, 4), dtype=np.uint64)
        cells[:5000, 0] = np.arange(5000, dtype=np.uint64)
        cells[12000:, 0] = 999999  # shell prompt drawn at exit
        rows = _make_rows(
            n,
            newpc_at={4900: 50, 12000: 500},
            newram_at={4900: 50},
            aenergy_fn=lambda i: 10000 if i < 12000 else 0,
            awrites_fn=lambda i: 5 if i < 12000 else 0,
            chan_fn=lambda i: "PPPP" if i < 12000 else "SSSS",
            rom_fn=lambda i: 900 if i >= 12000 else 0,
            cop1lc_fn=lambda i: 0x420 if i >= 12000 else 0x10000,
        )
        v = analyze.verdict(rows, cells, song=None, meta={"os_cop": 0x420})
        self.assertEqual(v["ending"], "exits")
        self.assertAlmostEqual(v["end"], 100.0, delta=2.0)

    def test_audio_loop_fallback_for_software_mixer(self):
        # Software mixer: zero Paula writes, periodic aenergy with period 1000 (20s)
        n = 15000
        cells = np.arange(n * 4, dtype=np.uint64).reshape(n, 4)
        # Distinct asymmetric waveform per 1000-frame period
        pat = np.array([
            int(50000 + 30000 * np.sin(2 * np.pi * k / 1000)
                + 15000 * np.cos(6 * np.pi * k / 1000)
                + 10000 * np.sin(10 * np.pi * k / 1000))
            for k in range(1000)
        ])
        rows = _make_rows(
            n,
            newpc_at={2000: 50},
            newram_at={2000: 50},
            aenergy_fn=lambda i: int(pat[(i - 2000) % 1000]) if i >= 2000 else i * 10,
            chan_fn=lambda i: "PPPP",
        )
        res = analyze.audio_loop(rows)
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[0], 1000, delta=15)

    def test_silent_paula_writes_ignored_as_song_loop(self):
        n = 15000
        cells = np.arange(n * 4, dtype=np.uint64).reshape(n, 4)
        rows = _make_rows(
            n,
            newpc_at={6000: 50},
            newram_at={6000: 50},
            aenergy_fn=lambda i: 50000 if i < 5500 else 0,
            awrites_fn=lambda i: 5,
            chan_fn=lambda i: "PPPP" if i < 5500 else "SSSS",
        )
        v = analyze.verdict(rows, cells, song=(250, 6000))
        self.assertIsNone(v["song_period"])
        self.assertAlmostEqual(v["end"], 120.0, delta=2.0)

    def test_empty_trace_safe(self):
        v = analyze.verdict([], np.zeros((0, 4), dtype=np.uint64), song=None)
        self.assertEqual(v["ending"], "not-started")

    def test_normal_exit_after_two_short_passes_not_cut_early(self):
        # Like Bonus Stage #75: 134s demo exits cleanly after playing a 60s song twice
        n = 10000
        cells = np.zeros((n, 4), dtype=np.uint64)
        cells[:6700, 0] = np.arange(6700, dtype=np.uint64)
        rows = _make_rows(
            n,
            newpc_at={6690: 100},
            newram_at={500: 100, 6690: 100},
            aenergy_fn=lambda i: int(50000 + 30000 * np.sin(2 * np.pi * i / 3000)) if i < 6700 else 0,
            awrites_fn=lambda i: 5 if i < 6700 else 0,
            chan_fn=lambda i: "PPPP" if i < 6700 else "SSSS",
            rom_fn=lambda i: 900 if i >= 6700 else 0,
            cop1lc_fn=lambda i: 0x420 if i >= 6700 else 0x10000,
        )
        v = analyze.verdict(rows, cells, song=None, meta={"os_cop": 0x420})
        self.assertEqual(v["ending"], "exits")
        self.assertAlmostEqual(v["end"], 134.0, delta=2.0)

    def test_slow_silent_slideshow_not_classified_as_stopped(self):
        # Like Rayworld: silent slideshow changing every 3700 frames (74s)
        n = 45000
        cells = np.zeros((n, 4), dtype=np.uint64)
        val = 1
        for base in range(12000, n, 3700):
            cells[base:, 0] = val
            val += 1
            if base + 700 < n:
                cells[base + 700:, 0] = val
                val += 1
        rows = _make_rows(n, newram_at={11500: 500})
        v = analyze.verdict(rows, cells, song=None)
        self.assertNotEqual(v["ending"], "stops")

    def test_nonfatal_exec_alert_ignored_when_demo_keeps_playing(self):
        # Like 8991 / 156134: demo overwrites ExecBase+$202 early then keeps
        # playing music & visuals for hundreds of seconds.
        n = 15000
        cells = np.arange(n * 4, dtype=np.uint64).reshape(n, 4)
        rows = _make_rows(
            n,
            newram_at={1000: 100, 6000: 100},
            alert_at=900,
            aenergy_fn=lambda i: 50000 if i < 6500 else 0,
            awrites_fn=lambda i: 5 if i < 6500 else 0,
            chan_fn=lambda i: "PPPP" if i < 6500 else "SSSS",
        )
        v = analyze.verdict(rows, cells, song=None)
        self.assertNotEqual(v["ending"], "crashed")

    def test_scrolltext_extends_looping_intro_when_screen_open(self):
        # Classic single-screen scrolltext intro: 90s song loops while a 240s
        # byte/word scrolltext feeds open screen cells and finishes well before 900s.
        n = 45000
        # Open cells (non-looping values that repeat enough not to be "noisy")
        rng = np.random.default_rng(7)
        cells = rng.integers(0, 500, size=(n, 4), dtype=np.uint64)
        rows = _make_rows(
            n,
            newram_at={1500: 100},
            aenergy_fn=lambda i: 50000,
            awrites_fn=lambda i: 5,
            chan_fn=lambda i: "PPPP",
        )
        v = analyze.verdict(rows, cells, song=(4500, 5000), data=12000, text_data=12000)
        self.assertEqual(v["ending"], "loops")
        self.assertAlmostEqual(v["end"], 240.0, delta=1.0)
        self.assertAlmostEqual(v["text_end"], 240.0, delta=1.0)

    def test_still_screen_after_song_loop_extends_end(self):
        # Like 90008: song loops at 72s, code stops at 106s, visuals keep moving
        # until 186s and then go completely still while music keeps looping.
        n = 45000
        cells = np.zeros((n, 4), dtype=np.uint64)
        cells[:9300, 0] = np.arange(9300, dtype=np.uint64)
        cells[9300:, 0] = 9300
        rows = _make_rows(
            n,
            newram_at={5300: 100},
            aenergy_fn=lambda i: 50000,
            awrites_fn=lambda i: 5,
            chan_fn=lambda i: "PPPP",
        )
        v = analyze.verdict(rows, cells, song=(3600, 4750))
        self.assertEqual(v["ending"], "loops")
        self.assertAlmostEqual(v["end"], 186.0, delta=1.0)

    def test_unfinished_scrolltext_flagged_as_text_after_trace(self):
        n = 45000
        rng = np.random.default_rng(11)
        cells = rng.integers(0, 500, size=(n, 4), dtype=np.uint64)
        rows = _make_rows(
            n,
            newram_at={1500: 100},
            aenergy_fn=lambda i: 50000,
            awrites_fn=lambda i: 5,
            chan_fn=lambda i: "PPPP",
        )
        v = analyze.verdict(rows, cells, song=(4500, 5000), data=44950, text_data=44950)
        self.assertTrue(v.get("text_after_trace"))

    def test_sustained_post_new_silence_before_mod_wraparound(self):
        # Like 281473: music ends at 7000 (140s), silent for 600s, then wraps
        # around at 37000..42800. Must detect music_over=140s, not 856s.
        n = 45000
        rng = np.random.default_rng(13)
        cells = rng.integers(0, 500, size=(n, 4), dtype=np.uint64)
        rows = _make_rows(
            n,
            newram_at={6600: 100},
            aenergy_fn=lambda i: 50000 if (i < 7000 or 37000 <= i < 42800) else 0,
            awrites_fn=lambda i: 16,
            chan_fn=lambda i: "PPPP" if (i < 7000 or 37000 <= i < 42800) else "SSSS",
        )
        v = analyze.verdict(rows, cells, song=None)
        self.assertAlmostEqual(v["music_over"], 140.0, delta=2.0)
        self.assertAlmostEqual(v["end"], 140.0, delta=2.0)

    def test_rom_trapped_crash_with_surviving_vblank_music_is_crashed(self):
        # Like 250551: real crash at 2850 traps CPU in Kickstart Idle (rom=99%,
        # frozen screen) while a VBlank interrupt keeps playing periodic audio.
        n = 20000
        cells = np.zeros((n, 4), dtype=np.uint64)
        cells[:2300, 0] = np.arange(2300, dtype=np.uint64)
        cells[2300:, 0] = 2300
        rows = _make_rows(
            n,
            newram_at={2300: 100},
            alert_at=2850,
            aenergy_fn=lambda i: 50000 if (i % 5000) < 1500 else 0,
            awrites_fn=lambda i: 16,
            chan_fn=lambda i: "PPPP" if (i % 5000) < 1500 else "SSSS",
            rom_fn=lambda i: 995 if i >= 2850 else 0,
        )
        # Keep alert latched after crash (as Kickstart does)
        for i in range(2850, n):
            rows[i]["alert"] = 0x00000004
        v = analyze.verdict(rows, cells, song=None)
        self.assertEqual(v["ending"], "crashed")

    def test_noisy_scrolltext_with_looping_borders_uses_text_end(self):
        # Like 166282: border cell loops every 320f (6.4s) while center cells
        # are "noisy" (unique per frame) with a scrolltext ending at 871s.
        n = 45000
        cells = np.zeros((n, 4), dtype=np.uint64)
        cells[:, 0] = np.arange(n, dtype=np.uint64) % 320  # looping border
        cells[:, 1] = np.arange(100000, 100000 + n, dtype=np.uint64)  # noisy center
        rows = _make_rows(
            n,
            newram_at={1500: 100},
            aenergy_fn=lambda i: 50000,
            awrites_fn=lambda i: 5,
            chan_fn=lambda i: "PPPP",
        )
        v = analyze.verdict(rows, cells, song=(9200, 10000), data=43560, text_data=43560)
        self.assertEqual(v["ending"], "loops")
        self.assertAlmostEqual(v["end"], 871.2, delta=1.0)

    def test_rom_trapped_crash_with_free_running_bitplane_dma_is_crashed(self):
        # Like 90583: crash at frame 870 leaves CPU in Kickstart ROM (99.9%)
        # with 0 newram, while orphaned bitplane DMA keeps changing screen cells.
        n = 15000
        cells = np.arange(n * 4, dtype=np.uint64).reshape(n, 4)
        rows = _make_rows(
            n,
            newram_at={200: 50, 869: 5},
            alert_at=870,
            rom_fn=lambda i: 999 if i >= 870 else 0,
        )
        for i in range(870, n):
            rows[i]["alert"] = 0x0000000b
        v = analyze.verdict(rows, cells, song=None)
        self.assertEqual(v["ending"], "crashed")


if __name__ == "__main__":
    unittest.main()
