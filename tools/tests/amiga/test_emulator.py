import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.amiga import emulator, machines, media, workbench
from scenemeta.core.errors import CannotPlay


class MissingRomTest(unittest.TestCase):
    def test_a_run_without_its_rom_never_starts_the_emulator(self):
        with tempfile.TemporaryDirectory() as empty, \
                mock.patch.object(emulator.config, "ROM_DIR",
                                  pathlib.Path(empty)), \
                mock.patch.object(emulator, "_invoke") as invoke:
            with self.assertRaisesRegex(CannotPlay, "kick13.rom") as e:
                emulator.run(machines.BY_NAME["a500"],
                             media.Variant("floppy", ["a.adf"]), 250)
        self.assertIn(empty, str(e.exception))
        invoke.assert_not_called()


class UaeConfigTest(unittest.TestCase):
    def config(self, variant):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        text, _ = emulator._uae_config(machines.BY_NAME["a500"], variant,
                                       pathlib.Path(tmp.name))
        return text

    def test_floppies_are_write_protected(self):
        # Spinotic only loads from a write-protected disk.
        with tempfile.NamedTemporaryFile(suffix=".adf") as adf:
            adf.write(b"\0" * 901120)
            adf.flush()
            text = self.config(media.Variant("floppy", [adf.name]))
        self.assertIn("floppy_write_protect=true\n", text)

    def test_random_seed_is_pinned(self):
        # Amiberry seeds its RNG (CPU start delay, floppy rotation phase)
        # from the wall clock: 5316 stalls or works depending on the second
        # it was started in. A fixed seed makes a run reproducible.
        with tempfile.NamedTemporaryFile(suffix=".adf") as adf:
            adf.write(b"\0" * 901120)
            adf.flush()
            v = media.Variant("floppy", [adf.name])
            self.assertIn(f"rndseed={emulator.DEFAULT_SEED}\n", self.config(v))
            with tempfile.TemporaryDirectory() as t:
                text, _ = emulator._uae_config(machines.BY_NAME["a500"], v,
                                               pathlib.Path(t), seed=7)
        self.assertIn("rndseed=7\n", text)
        self.assertNotIn("rndseed=1\n", text)

    def test_hard_drive_stays_writable(self):
        with tempfile.TemporaryDirectory() as root:
            text = self.config(media.Variant("hd", [], root=root,
                                             command='"demo"\n'))
        self.assertNotIn("floppy_write_protect", text)
        self.assertIn("filesystem2=rw,", text)


class HdConfigTest(unittest.TestCase):
    def startup(self, machine):
        with tempfile.TemporaryDirectory() as t:
            tree, tmp = pathlib.Path(t) / "tree", pathlib.Path(t) / "run"
            tree.mkdir()
            tmp.mkdir()
            (tree / "demo").write_bytes(b"\0\0\3\xf3")
            v = media.Variant("hd", [], root=str(tree), command='"demo"\n')
            emulator._uae_config(machines.BY_NAME[machine], v, tmp)
            tool = tmp / "hd" / emulator.FPU_ON
            return ((tmp / "hd" / "s" / "startup-sequence").read_text(),
                    tool.read_bytes() if tool.exists() else None)

    def test_060_switches_its_fpu_on_before_the_demo(self):
        # Step By Step, Metatag Lock: FPU code Gurus 8000000B on a 060 whose
        # FPU is still off (no 68060.library).
        text, tool = self.startup("a1200_060")
        self.assertEqual(text, f'{workbench.SETUP}\n{emulator.FPU_ON}\n"demo"\n')
        self.assertEqual(tool[:4], b"\0\0\3\xf3")
        self.assertEqual(len(tool) % 4, 0)

    def test_other_machines_skip_the_fpu_tool(self):
        text, tool = self.startup("a1200_030")
        self.assertEqual((text, tool), (f'{workbench.SETUP}\n"demo"\n', None))


class ScriptTest(unittest.TestCase):
    def script(self, frames=1000, **kw):
        return emulator._script(frames, 250, "peek x 4", pathlib.Path("/s"),
                                [], emulator.Options(**kw))

    def test_no_nudge_by_default(self):
        self.assertFalse([c for c in self.script() if c.startswith("input")])

    def test_click_every(self):
        cmds = self.script(click_every=500)
        self.assertEqual([c for c in cmds if c.startswith("input")],
                         ["input mouse click 0"] * 2)

    def test_keys_cycle_every_period(self):
        # 257354's credits page only moves on Return; others want Space or
        # the fire button: one retry tries each in turn.
        cmds = self.script(frames=2000, key_every=500)
        presses = [c for c in cmds if c.startswith("input")]
        self.assertEqual(presses, [
            "input key 68 down", "input key 68 up",
            "input key 64 down", "input key 64 up",
            "input joy 1 fire down", "input joy 1 fire up",
            "input key 68 down", "input key 68 up"])

    def test_key_is_held_across_a_few_frames(self):
        cmds = self.script(frames=500, key_every=500)
        i = cmds.index("input key 68 down")
        self.assertEqual(cmds[i + 1], f"run frames={emulator.KEY_HOLD_FRAMES}")
        self.assertEqual(cmds[i + 2], "input key 68 up")

    def test_the_frames_a_key_is_held_come_off_the_next_interval(self):
        cmds = self.script(frames=750, key_every=500)
        self.assertEqual([c for c in cmds if c.startswith("run")], [
            "run frames=250", "run frames=250",
            f"run frames={emulator.KEY_HOLD_FRAMES}",
            f"run frames={250 - emulator.KEY_HOLD_FRAMES}"])

    def test_a_scheduled_insert_is_clicked_a_sample_later(self):
        cmds = emulator._script(1000, 250, "peek x 4", pathlib.Path("/s"),
                                ["/d/b.adf"], emulator.Options(schedule=(500,)))
        i = cmds.index("disk insert 0 /d/b.adf")
        self.assertEqual(cmds[i + 1], "run frames=250")
        self.assertEqual([c for c in cmds if c.startswith("input")],
                         ["input mouse click 0"])


class PressedTest(unittest.TestCase):
    def test_nudges_at_their_frames(self):
        self.assertEqual(
            emulator.pressed(1000, emulator.Options(click_every=500,
                                                    max_clicks=1)),
            [(500, "lmb", None)])
        self.assertEqual(
            emulator.pressed(2000, emulator.Options(key_every=500)),
            [(500, "return", None), (1000, "space", None),
             (1500, "p2fire", None), (2000, "return", None)])

    def test_a_pulse_s_click_names_its_disk_left_and_right_in_turn(self):
        got = emulator.pressed(4500, emulator.Options(schedule=(500, 1000)))
        self.assertEqual(got[:4], [(750, "lmb", 0), (1250, "rmb", 1),
                                   (2250, "lmb", 0), (2750, "rmb", 1)])

    def test_a_played_run_presses_nothing_of_itself(self):
        self.assertEqual(emulator.pressed(1000, emulator.Options()), [])


class PlayTest(unittest.TestCase):
    """A run that does fixed things at exact frames and nothing else."""

    def play(self, actions, frames=1000):
        return emulator._play(frames, 250, "peek x 4", pathlib.Path("/s"),
                              ["/d/1-b.adf"], emulator.Options(play=actions))

    def test_insert_and_click_at_their_frames(self):
        cmds = self.play([(300, "insert", (0, 0)), (550, "press", "lmb")])
        moves = [c for c in cmds if c.startswith(("run", "disk insert", "input"))]
        self.assertEqual(moves, [
            "run frames=250", "run frames=50", "disk insert 0 /d/1-b.adf",
            "run frames=200", "run frames=50", "input mouse click 0",
            "run frames=200", "run frames=250"])

    def test_an_insert_goes_into_the_drive_it_names(self):
        cmds = self.play([(300, "insert", (0, 1))])
        self.assertIn("disk insert 1 /d/1-b.adf", cmds)

    def test_each_key_by_its_name(self):
        def inputs(key):
            return [c for c in self.play([(100, "press", key)])
                    if c.startswith("input")]
        self.assertEqual(inputs("rmb"), ["input mouse click 1"])
        for key, what in (("return", "key 68"), ("space", "key 64"),
                          ("p1fire", "joy 0 fire"), ("p2fire", "joy 1 fire")):
            self.assertEqual(inputs(key), [f"input {what} down",
                                           f"input {what} up"])
        self.assertEqual(set(emulator.KEYS),
                         {"lmb", "rmb", "return", "space", "p1fire", "p2fire"})

    def test_a_held_key_does_not_move_what_comes_after(self):
        cmds = self.play([(100, "press", "return"), (101, "press", "space"),
                          (300, "insert", (0, 0))], frames=500)
        moves = [c for c in cmds if c.startswith(("run", "disk insert", "input"))]
        self.assertEqual(moves, [
            "run frames=100", "input key 68 down", "run frames=3",
            "input key 68 up", "input key 64 down", "run frames=3",
            "input key 64 up", "run frames=144", "run frames=50",
            "disk insert 0 /d/1-b.adf", "run frames=200"])

    def test_every_sample_reports_the_drives(self):
        cmds = self.play([])
        self.assertEqual(cmds.count("status"), 4)
        self.assertEqual(cmds.count("disk status"), 4)


class ParseTest(unittest.TestCase):
    def test_head_cylinders_of_a_sample(self):
        out = "\n".join([
            '{"cmd": "status", "result": {"frame": 250, "pc": "0", "dmacon": 0,'
            ' "bplcon0": 0}}',
            '{"cmd": "disk status", "result": {"units": [{"cyl": 12, "motor": 1},'
            ' {"cyl": 0, "motor": 0}]}}'])
        log = emulator._parse((out, "", 0, False), pathlib.Path("/none"), {},
                              0, "peek x 4")
        self.assertEqual(log.samples[0].cyls, [12, 0])


class AutoswapTest(unittest.TestCase):
    def test_clicks_when_a_new_disk_is_not_picked_up(self):
        self.assertTrue(emulator._autoswap(emulator.Options()).startswith("disk autoswap click "))

    def test_triggers_and_unit(self):
        cmd = emulator._autoswap(emulator.Options(triggers="reread", unit=1))
        self.assertTrue(cmd.endswith(" unit=1 reread"))

    def test_detector_off(self):
        opts = emulator.Options(triggers="reread", detect=False)
        self.assertEqual(emulator._autoswap(opts), "disk autoswap off")


if __name__ == "__main__":
    unittest.main()


class SampleCommandsTest(unittest.TestCase):
    def cmds(self, **kw):
        return emulator._sample(3, "peek 4 4", pathlib.Path("/s"), False,
                                emulator.Options(**kw))

    def test_no_kept_shot_unless_asked(self):
        self.assertFalse([c for c in self.cmds() if c.startswith("shot-new")])

    def test_kept_shot_is_named_after_its_sample(self):
        self.assertIn("shot-new 20 /keep/0003.png",
                      self.cmds(keep=pathlib.Path("/keep")))
