"""Regression checks for manual media, keyboard input and library staging."""
import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta import validate
from scenemeta.amiga import emulator, machines, media, player, workbench
from scenemeta.amiga.enddetect import runner
from scenemeta.core.errors import BadEntry


class SystemInputsTest(unittest.TestCase):
    def test_disk_one_can_return_after_disk_two(self):
        entry = {"disks": ["one.adf", "two.adf"], "events": [
            {"at": 10, "disk": 2}, {"at": 20, "disk": 1},
            {"at": 30, "disk": 2}]}
        self.assertEqual(player.actions(entry), [
            (500, "insert", (1, 0)), (1000, "insert", (0, 0)),
            (1500, "insert", (1, 0))])

    def test_any_initial_disk_can_be_inserted_into_any_available_drive(self):
        entry = {"drives": 2, "disks": ["one", "two", "three"],
                 "events": [{"at": 10, "disk": 1, "drive": 2},
                            {"at": 20, "disk": 2}]}
        self.assertEqual(player.actions(entry), [
            (500, "insert", (0, 1)), (1000, "insert", (1, 0))])

    def test_single_disk_reinsertion_and_range_errors(self):
        self.assertEqual(player.actions({"disks": ["one"], "events": [
            {"at": 1, "disk": 1}]}), [(50, "insert", (0, 0))])
        for disk in [0, -1, 3]:
            with self.subTest(disk=disk), self.assertRaises(BadEntry):
                player.actions({"disks": ["one", "two"], "events": [
                    {"at": 1, "disk": disk}]})
        with self.assertRaises(BadEntry):
            player.actions({"disks": ["one"], "events": [
                {"at": 1, "disk": 1, "drive": 0}]})

    def test_copied_disk_catalog_includes_boot_disks(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            originals = [root / f"d{i}.adf" for i in range(3)]
            for i, path in enumerate(originals):
                path.write_bytes(bytes([i]))
            _, disks = emulator._uae_config(machines.BY_NAME["a500"],
                media.Variant("floppy", originals), root / "run", drives=2)
            self.assertEqual([p.read_bytes() for p in disks],
                             [b"\0", b"\1", b"\2"])
            self.assertTrue(all(p not in originals for p in disks))

    def test_manual_reinsertion_reaches_original_image(self):
        entry = {"disks": ["one", "two"], "events": [
            {"at": 1, "disk": 2}, {"at": 2, "disk": 1}]}
        cmds = emulator._play(250, 250, "peek 0 4", pathlib.Path("/shots"),
            ["/copies/one", "/copies/two"],
            emulator.Options(play=player.actions(entry)))
        self.assertEqual([c for c in cmds if c.startswith("disk insert")],
            ["disk insert 0 /copies/two", "disk insert 0 /copies/one"])

    def test_enddetect_record_maps_disk_one_to_boot_copy(self):
        entry = {"title": "test", "disks": ["one", "two"], "events": [
            {"at": 1, "disk": 2}, {"at": 2, "disk": 1}]}
        ready = player.Ready(entry, machines.BY_NAME["a500"],
                             media.Variant("floppy", ["one", "two"]))
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(player, "ready", return_value=ready), \
                mock.patch.object(emulator, "system_copper", return_value=0), \
                mock.patch.object(emulator, "_uae_config", return_value=(
                    "sound_output=none\n", ["/copies/one", "/copies/two"])), \
                mock.patch.object(emulator, "_invoke", return_value=(
                    "", "", 0, False)) as invoke:
            runner.record(1, entry, "a500", t, frames=250)
        argv = invoke.call_args.args[0]
        self.assertIn("disk insert 0 /copies/two", argv)
        self.assertIn("disk insert 0 /copies/one", argv)
        self.assertLess(argv.index("disk insert 0 /copies/two"),
                        argv.index("disk insert 0 /copies/one"))

    def test_new_keys_use_exact_amiga_rawcodes_and_release(self):
        expected = dict(zip("1234567890", range(1, 11)))
        expected.update(dict(zip("qwertyuiop", range(0x10, 0x1a))))
        expected.update(dict(zip("asdfghjkl", range(0x20, 0x29))))
        expected.update(dict(zip("zxcvbnm", range(0x31, 0x38))))
        expected.update({f"f{i}": 0x4f + i for i in range(6, 11)})
        for key, code in expected.items():
            with self.subTest(key=key):
                self.assertEqual(player.actions({"events": [
                    {"at": 1, "key": key}]}), [(50, "press", key)])
                self.assertEqual(emulator._press(key), ([
                    f"input key {code} down", "run frames=3",
                    f"input key {code} up"], 3))

    def test_validator_accepts_reinsertion_and_new_keys(self):
        for key in ["1", "0", "f6", "f10", "a", "z"]:
            self.assertIsNone(validate._events([
                {"at": 1, "disk": 2}, {"at": 2, "disk": 1},
                {"at": 3, "key": key}]))
        self.assertIsNotNone(validate._events([{"at": 1, "disk": 0}]))

    def test_root_libraries_work_without_system_library_directory(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            (root / "hippie.LIBRARY").write_bytes(b"bundled")
            (root / "fake.library").mkdir()
            workbench.prepare(root, "demo\n", libs_dir=root / "missing")
            self.assertEqual((root / "libs/hippie.LIBRARY").read_bytes(), b"bundled")
            self.assertEqual((root / "hippie.LIBRARY").read_bytes(), b"bundled")
            self.assertFalse((root / "libs/fake.library").exists())

    def test_root_libraries_preserve_bundled_precedence_and_system_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            root, system = pathlib.Path(t) / "demo", pathlib.Path(t) / "wb"
            root.mkdir()
            system.mkdir()
            (root / "Libs").mkdir()
            (root / "hippie.library").write_bytes(b"root")
            (root / "iff.LIBRARY").write_bytes(b"root iff")
            (root / "Libs/HIPPIE.library").write_bytes(b"libs wins")
            (system / "iff.library").write_bytes(b"system iff")
            (system / "mathtrans.library").write_bytes(b"system math")
            workbench.prepare(root, "demo\n", libs_dir=system, all_libs=True)
            self.assertEqual((root / "Libs/HIPPIE.library").read_bytes(), b"libs wins")
            self.assertEqual((root / "Libs/iff.LIBRARY").read_bytes(), b"root iff")
            self.assertEqual((root / "Libs/mathtrans.library").read_bytes(), b"system math")
            self.assertFalse((root / "libs").exists())

    def test_root_library_does_not_hide_system_iff(self):
        with tempfile.TemporaryDirectory() as t:
            root, system = pathlib.Path(t) / "demo", pathlib.Path(t) / "wb"
            root.mkdir()
            system.mkdir()
            (root / "hippie.library").write_bytes(b"bundled")
            (system / "iff.library").write_bytes(b"system")
            workbench.prepare(root, "demo\n", libs_dir=system, all_libs=True)
            self.assertEqual((root / "libs/hippie.library").read_bytes(), b"bundled")
            self.assertEqual((root / "libs/iff.library").read_bytes(), b"system")

    def test_automatic_swapper_keeps_only_future_disks_and_original_numbers(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            disks = [root / f"d{i}.adf" for i in range(3)]
            for p in disks:
                p.write_bytes(b"disk")
            v = media.Variant("floppy", disks)
            captured = []
            def invoke(argv, tmp, timeout):
                captured.extend(argv)
                future = next(a.split("=", 1)[1] for a in argv
                              if a.startswith("-diskswapper="))
                import json
                return json.dumps({"event": "autoswap", "inserted": future}), "", 0, False
            with mock.patch.object(machines, "require_rom"), \
                    mock.patch.object(emulator, "execbase", return_value=0), \
                    mock.patch.object(emulator, "system_copper", return_value=0), \
                    mock.patch.object(emulator, "_invoke", side_effect=invoke):
                log = emulator.run(machines.BY_NAME["a500"], v, 250,
                                    emulator.Options(drives=2))
            future = [a for a in captured if a.startswith("-diskswapper=")]
            self.assertEqual(len(future), 1)
            self.assertTrue(future[0].endswith("2-d2.adf"))
            self.assertEqual(log.events[0]["disk"], 3)

    def test_manual_player_reports_disk_one_after_reinsertion(self):
        entry = {"title": "test", "disks": ["one", "two"], "events": [
            {"at": 1, "disk": 2}, {"at": 2, "disk": 1}]}
        samples = [emulator.Sample(75, 0, 0, 0, 0, "", "", last_dma=70,
                                   cyls=[20]),
                   emulator.Sample(125, 0, 0, 0, 0, "", "", last_dma=120,
                                   cyls=[30])]
        ready = player.Ready(entry, machines.BY_NAME["a500"],
                             media.Variant("floppy", ["one", "two"]))
        with mock.patch.object(emulator, "run", return_value=emulator.RunLog(
                samples, [], 0, False, "")):
            out = ready.play()
        self.assertEqual([(s.disk, s.loaded) for s in out.record.swaps],
                         [(2, True), (1, True)])

    def test_libraries_are_staged_when_download_has_own_startup(self):
        with tempfile.TemporaryDirectory() as t:
            root, tmp = pathlib.Path(t) / "tree", pathlib.Path(t) / "run"
            root.mkdir()
            tmp.mkdir()
            (root / "hippie.library").write_bytes(b"library")
            (root / "s").mkdir()
            (root / "s/startup-sequence").write_text("own\n")
            with mock.patch.object(emulator.config, "LIBS_DIR", root / "none"):
                emulator._uae_config(machines.BY_NAME["a500"],
                    media.Variant("hd", [], root=root), tmp)
            self.assertEqual((tmp / "hd/libs/hippie.library").read_bytes(), b"library")
            self.assertEqual((tmp / "hd/s/startup-sequence").read_text(), "own\n")

    def test_wb_boot_stages_root_libraries_without_writing_system_links(self):
        with tempfile.TemporaryDirectory() as t:
            root, tmp, boot = (pathlib.Path(t) / d for d in ("tree", "run", "wb"))
            root.mkdir()
            tmp.mkdir()
            boot.mkdir()
            (boot / "Libs").mkdir()
            (boot / "Libs/iff.library").write_bytes(b"system")
            (root / "hippie.library").write_bytes(b"bundled")
            with mock.patch.object(emulator.config, "A1200_BOOT", boot), \
                    mock.patch.object(emulator.config, "LIBS_DIR", root / "none"):
                emulator._uae_config(machines.BY_NAME["a1200_060"],
                    media.Variant("hd", [], root=root, command="demo\n"), tmp)
            self.assertEqual((tmp / "hd/libs/hippie.library").read_bytes(), b"bundled")
            self.assertEqual(list((boot / "Libs").iterdir()), [boot / "Libs/iff.library"])
            self.assertIn("SYS:Libs ADD", (tmp / "sys/S/Startup-Sequence").read_text())

    def test_root_packer_library_uses_compressors_without_clobbering(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            (root / "xpkSQSH.library").write_bytes(b"packer")
            (root / "LIBS").write_bytes(b"data")
            workbench.prepare_libraries(root, root / "none")
            self.assertEqual((root / "LIBS").read_bytes(), b"data")
            (root / "LIBS").unlink()
            workbench.prepare_libraries(root, root / "none")
            self.assertEqual((root / "libs/compressors/xpkSQSH.library").read_bytes(), b"packer")
