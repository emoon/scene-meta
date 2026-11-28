"""Real direct-color output must not be confused with an idle OS screen."""

import pathlib
import tempfile
import unittest

from scenemeta.amiga import emulator, rastershot, verdict
from .test_verdict import log, shown
from .test_alertshot import black

DATA = pathlib.Path(__file__).parent / "data"


class ColorRasterTest(unittest.TestCase):
    def test_real_rgb_effect_is_measured_when_display_dma_is_off(self):
        image = DATA / "radio_gargaj_1.png"
        self.assertTrue(rastershot.multicolor(image.read_bytes()))
        self.assertTrue(rastershot.multicolor((DATA / "radio_gargaj_2.png").read_bytes()))
        self.assertTrue(emulator._color_raster(image, {"dmacon": 0x250}))
        self.assertTrue(emulator._color_raster(image, {"dmacon": 0x2D0}))
        # Paskahor is a thin color-only line, retaining the OS copper.
        self.assertTrue(emulator._color_raster(DATA / "paskahor_line.png", {"dmacon": 0x22D0}))
        # OS bitplanes, sprites, or latched mid-frame bitplanes
        # prevent pixel diversity from being taken as CPU color writes.
        for status in ({"dmacon": 0x350},
                       {"dmacon": 0x270},
                       {"dmacon": 0x250, "bpl_active": True}):
            self.assertFalse(emulator._color_raster(image, status))

    def test_blank_output_and_missing_image_supply_no_evidence(self):
        self.assertFalse(rastershot.multicolor((DATA / "blank_white.png").read_bytes()))
        self.assertFalse(rastershot.multicolor(b""))
        self.assertFalse(rastershot.multicolor(black(752, 574)))
        self.assertFalse(emulator._color_raster(DATA / "absent.png", {"dmacon": 0x250}))

    def test_reader_preserves_raster_evidence_and_existing_os_copper(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = pathlib.Path(tmp)
            (shots / "0000.png").write_bytes((DATA / "radio_gargaj_1.png").read_bytes())
            reader = emulator._Reader(shots, {}, 0xC00276, "peek c00478 4")
            reader.read({"cmd": "status", "result": {
                "frame": 751, "pc": "fe5854", "dmacon": 0x250,
                "bplcon0": 0xA200, "cop1lc": "420", "bpl_active": False}})
            self.assertTrue(reader.samples[0].color_raster)
            self.assertEqual(reader.samples[0].cop1lc, 0x420)

    def effect(self, count=14, still=False):
        lg = log("." * count)
        lg.system_copper = 0x420
        for i, s in enumerate(lg.samples):
            s.pc = 0xFE5854  # IRQ-boundary ROM snapshot in the real trace
            s.dmacon = 0x250
            s.cop1lc = 0x420
            s.color_raster = True
            s.shot = "same" if still else f"raster{i % 2}"
        return lg

    def test_sustained_direct_color_animation_is_alive_even_on_os_copper(self):
        got = verdict.classify(self.effect(), 14)
        self.assertEqual((got.verdict, got.alive, got.crash), ("works", 13, None))

    def test_static_raster_or_short_color_flicker_is_not_promoted(self):
        self.assertEqual(verdict.classify(self.effect(still=True), 14).verdict, "no-activity")
        self.assertEqual(verdict.classify(self.effect(3), 3).verdict, "no-activity")
        lg = self.effect()
        for s in lg.samples[3:]:
            s.shot = lg.samples[2].shot
            s.color_raster = False
        self.assertEqual(verdict.classify(lg, 14).verdict, "no-activity")

    def test_crash_signals_take_precedence_over_color_output(self):
        for signal in ("guru", "task-held"):
            lg = self.effect()
            for s in lg.samples:
                s.box = signal
            got = verdict.classify(lg, 14)
            self.assertEqual((got.verdict, got.alive, got.crash), ("crash", 0, signal))
        lg = self.effect()
        lg.events = [{"event": "halt", "frame": 500}]
        self.assertEqual(verdict.classify(lg, 14).verdict, "crash")

    def test_cli_workbench_and_silent_error_output_are_not_promoted(self):
        # Existing rejection cases: startup screens, OS error messages,
        # isolated key echoes, and a changing black capture with no evidence.
        for spec in ("cc............", ".ccc..........", "." * 14):
            lg = shown(spec)
            lg.system_copper = 0x420
            for s in lg.samples:
                s.pc, s.cop1lc = 0xF80100, 0x420
            self.assertEqual(verdict.classify(lg, 14).verdict, "no-activity")
        lg = log("c" * 14)
        for s in lg.samples:
            s.dmacon = 0x200
        self.assertEqual(verdict.classify(lg, 14).verdict, "no-activity")


class StaticCopperGuardTest(unittest.TestCase):
    def boot_then_failed_os_screen(self, spec):
        lg = shown(spec)
        lg.system_copper = 0x420
        for i, s in enumerate(lg.samples):
            s.pc = 0xF84C7C
            s.cop1lc = 0xD016 if i < 8 else 0x420
            s.dmacon |= 0x80
        return lg

    def test_boot_copper_before_silent_os_failure_is_not_a_short_intro(self):
        # Remarkable Intro's KS3.0 trace: OS's initial boot copper differs
        # from the bare probe, then the DOS task-failed requester appears.
        lg = self.boot_then_failed_os_screen("." * 9 + "cc" + "." * 25)
        self.assertEqual(verdict.classify(lg, 36).verdict, "no-activity")

    def test_static_boot_copper_cannot_promote_later_failed_os_screen(self):
        # a1200_fast: eight boot snapshots, no alive samples, then an
        # unrecognized but static task-failed requester on the OS copper.
        lg = self.boot_then_failed_os_screen("." * 8 + "c" + "." * 27)
        self.assertEqual(verdict.classify(lg, 36).verdict, "no-activity")
