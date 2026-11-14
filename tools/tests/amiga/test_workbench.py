import pathlib
import shutil
import struct
import tempfile
import unittest

from scenemeta.amiga import workbench


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
