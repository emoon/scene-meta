import pathlib
import tempfile
import unittest

from scenedb import emulator, machines, media, workbench


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
                                1, [], **kw)

    def test_no_nudge_by_default(self):
        self.assertFalse([c for c in self.script() if c.startswith("input")])

    def test_click_every(self):
        cmds = self.script(click_every=500)
        self.assertEqual([c for c in cmds if c.startswith("input")],
                         ["input mouse click 0"] * 2)

    def test_no_nudges_from_a_given_frame_on(self):
        # The run that shows whether a swap's click was needed must not
        # press anything once that disk is in.
        cmds = self.script(frames=2000, click_every=500, nudge_until=1000)
        self.assertEqual([c for c in cmds if c.startswith("input")],
                         ["input mouse click 0"])
        cmds = self.script(frames=2000, key_every=500, nudge_until=1000)
        self.assertEqual([c for c in cmds if c.startswith("input")],
                         ["input key 68 down", "input key 68 up"])

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


class AutoswapTest(unittest.TestCase):
    def test_clicks_when_a_new_disk_is_not_picked_up(self):
        self.assertTrue(emulator._autoswap().startswith("disk autoswap click "))

    def test_without_the_click(self):
        # The run that shows whether a swap's click was needed.
        cmd = emulator._autoswap("reread", unit=1, swap_click=False)
        self.assertTrue(cmd.startswith("disk autoswap on "))
        self.assertTrue(cmd.endswith(" unit=1 reread"))

    def test_detector_off(self):
        self.assertEqual(emulator._autoswap("reread", detect=False),
                         "disk autoswap off")


if __name__ == "__main__":
    unittest.main()
