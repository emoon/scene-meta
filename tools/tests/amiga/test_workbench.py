import pathlib
import shutil
import struct
import tempfile
import unittest

from scenemeta.amiga import workbench
from scenemeta.core.errors import CannotPlay


class WorkbenchTest(unittest.TestCase):
    def dir(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_setup_exe_is_one_code_hunk(self):
        exe = workbench.setup_exe()
        self.assertEqual(struct.unpack(">6I", exe[:24]),
                         (0x3F3, 0, 1, 0, 0, (len(exe) - 36) // 4))
        self.assertEqual(struct.unpack(">I", exe[24:28])[0], 0x3E9)
        self.assertEqual(exe[-4:], b"\0\0\x03\xf2")

    def test_assign_exe_is_one_code_hunk(self):
        exe = workbench.assign_exe()
        self.assertEqual(struct.unpack(">6I", exe[:24]),
                         (0x3F3, 0, 1, 0, 0, (len(exe) - 36) // 4))
        self.assertEqual(exe[-4:], b"\0\0\x03\xf2")
        self.assertIn(b"dos.library\0", exe)

    def test_assign_branches_land_on_instructions(self):
        # Every short branch of the hand-assembled code, by its offset.
        code = workbench._ASSIGN_CODE
        want = {0x12: 0x8e, 0x1a: 0x16, 0x26: 0x7a, 0x2c: 0x20, 0x36: 0x32,
                0x3e: 0x54, 0x4a: 0x5c, 0x50: 0x44, 0x52: 0x5c, 0x5a: 0x56,
                0x68: 0x7a, 0x72: 0x7e, 0x7c: 0x80}
        got = {at: at + 2 + struct.unpack(">b", code[at + 1:at + 2])[0]
               for at in want}
        self.assertEqual(got, want)
        # lea dosname(pc),a1
        at = 0x06 + 2 + struct.unpack(">h", code[0x08:0x0a])[0]
        self.assertEqual(code[at:], b"dos.library\0")

    def test_a_script_can_be_told_to_go_on(self):
        root = self.dir()
        workbench.prepare(root, f"{workbench.GO_ON}\nx\n", libs_dir=root / "none")
        exe = (root / workbench.GO_ON).read_bytes()
        self.assertEqual(exe, workbench.go_on_exe())
        self.assertEqual(struct.unpack(">6I", exe[:24]),
                         (0x3F3, 0, 1, 0, 0, (len(exe) - 36) // 4))
        # beq.s out, past the write of cli_FailLevel
        code = workbench._GO_ON_CODE
        self.assertEqual(0x10 + 2 + code[0x11], 0x1c)

    def test_a_tree_without_assign_gets_ours(self):
        root = self.dir()
        workbench.prepare(root, "x\n", libs_dir=root / "none")
        self.assertEqual((root / "c" / "Assign").read_bytes(),
                         workbench.assign_exe())

    def test_a_trees_own_assign_is_kept(self):
        root = self.dir()
        (root / "C").mkdir()
        (root / "C" / "ASSIGN").write_bytes(b"own")
        workbench.prepare(root, "x\n", libs_dir=root / "none")
        self.assertEqual([p.name for p in (root / "C").iterdir()], ["ASSIGN"])
        self.assertFalse((root / "c").exists())

    def test_a_file_named_c_leaves_no_place_for_assign(self):
        # The Prey (6952): its data files are 0, a, b, c, d, e.
        for name in ("c", "C"):
            root = self.dir()
            (root / name).write_bytes(b"data")
            workbench.prepare(root, "x\n", libs_dir=root / "none")
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             sorted([name, "s"]))
            self.assertEqual((root / name).read_bytes(), b"data")

    def test_a_run_needs_the_math_libraries(self):
        libs = self.dir()
        with self.assertRaisesRegex(CannotPlay, "no mathieeedoubbas.library"):
            workbench.require_libs(libs / "none")
        for name in workbench.ALWAYS_LIBS - {"mathtrans.library"}:
            (libs / name).write_bytes(b"wb")
        with self.assertRaisesRegex(CannotPlay,
                                    f"no mathtrans.library in {libs}"):
            workbench.require_libs(libs)
        (libs / "MathTrans.library").write_bytes(b"wb")
        workbench.require_libs(libs)

    def test_a_file_named_libs_gets_no_libraries(self):
        root, libs = self.dir(), self.dir()
        (root / "LIBS").write_bytes(b"x mathtrans.library\0")
        (libs / "mathtrans.library").write_bytes(b"wb")
        workbench.prepare(root, "x\n", libs_dir=libs)
        self.assertEqual((root / "LIBS").read_bytes(), b"x mathtrans.library\0")
        self.assertFalse((root / "libs").exists())

    def test_a_file_named_s_cannot_be_booted(self):
        root = self.dir()
        (root / "S").write_bytes(b"data")
        with self.assertRaisesRegex(CannotPlay, "a file named S"):
            workbench.prepare(root, "x\n", libs_dir=root / "none")
        self.assertEqual([p.name for p in root.iterdir()], ["S"])

    def test_setup_assigns_env_to_ram(self):
        exe = workbench.setup_exe()
        self.assertIn(b"dos.library\0RAM:ENV\0ENV\0", exe)

    def test_startup_runs_setup_first(self):
        root = self.dir()
        workbench.prepare(root, '"demo"\n', libs_dir=root / "none")
        self.assertEqual((root / "s" / "startup-sequence").read_text(),
                         f'{workbench.SETUP}\n"demo"\n')
        self.assertTrue((root / workbench.SETUP).exists())

    def test_startup_is_latin1(self):
        root = self.dir()
        workbench.prepare(root, '"tlu-pdva.ex\u00e9"\n', libs_dir=root / "none")
        self.assertIn(b'"tlu-pdva.ex\xe9"',
                      (root / "s" / "startup-sequence").read_bytes())

    def test_libs_fill_in_without_replacing(self):
        root, libs = self.dir(), self.dir()
        (root / "Libs").mkdir()
        (root / "demo").write_bytes(b"x mathtrans.library\0")
        (root / "Libs" / "Mathtrans.library").write_bytes(b"own")
        (libs / "mathtrans.library").write_bytes(b"wb")
        (libs / "mathieeedoubbas.library").write_bytes(b"wb")
        workbench.prepare(root, "x\n", libs_dir=libs)
        self.assertEqual(sorted(p.name for p in (root / "Libs").iterdir()),
                         ["Mathtrans.library", "mathieeedoubbas.library"])
        self.assertEqual((root / "Libs" / "Mathtrans.library").read_bytes(), b"own")
        self.assertFalse((root / "libs").exists())

    def test_only_libs_a_file_names_are_copied(self):
        root, libs = self.dir(), self.dir()
        for n in ("CrM.library", "asl.library", "mathtrans.library"):
            (libs / n).write_bytes(b"wb")
        (root / "demo").write_bytes(b"\0OpenLibrary crm.LIBRARY\0")
        workbench.prepare(root, "demo\n", libs_dir=libs)
        self.assertEqual(sorted(p.name for p in (root / "libs").iterdir()),
                         ["CrM.library", "mathtrans.library"])

    def test_packer_libs_follow_xpkmaster(self):
        root, libs = self.dir(), self.dir()
        for n in ("xpkmaster.library", "xpkSQSH.library", "asl.library"):
            (libs / n).write_bytes(b"wb")
        (root / "demo").write_bytes(b"xpkmaster.library\0")
        workbench.prepare(root, "demo\n", libs_dir=libs)
        self.assertEqual(sorted(p.name for p in (root / "libs").iterdir()),
                         ["xpkSQSH.library", "xpkmaster.library"])
