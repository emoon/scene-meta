import os
import pathlib
import struct
import subprocess
import tempfile
import unittest
import unittest.mock
import zipfile

from scenedb import media

EXE = media.HUNK_MAGIC + b"\0" * 60


class PickExeTest(unittest.TestCase):
    def tree(self, files):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        for name, data in files.items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_bytes(data)
        return d

    def test_prefers_the_title(self):
        # High Anxiety: two icon-backed executables; the demo is the one
        # named after it, not the bigger one.
        d = self.tree({"WinQube": EXE * 4, "WinQube.info": b"",
                       "High-Anx": EXE, "High-Anx.info": b""})
        self.assertEqual(media._pick_exe(d, "High Anxiety")[0].name, "High-Anx")

    def test_data_named_overlay_is_not_the_start(self):
        # Hardcore: the big hunk file is an overlay its 1K loader reads.
        d = self.tree({"hc.2xy-ko.dat": EXE * 100, "hc.1ph-pip.exe": EXE})
        self.assertEqual(media._pick_exe(d)[0].name, "hc.1ph-pip.exe")

    def test_tree_variant_runs_the_title(self):
        # Deep: "start the demo with the command dEEP", not the biggest part.
        d = self.tree({"keppi": EXE * 100, "dEEP": EXE, "tarra": EXE * 90})
        self.assertEqual(media._tree_variant(d, "Deep").command, '"dEEP"\n')

    def test_skips_handlers(self):
        d = self.tree({"RAM-Handler": EXE, "C/BLISS-OUT": EXE})
        self.assertIsNone(media._pick_exe(d)[0])

    def test_join_split_parts(self):
        d = self.tree({"ht-stag.lzx.001": b"ab", "ht-stag.lzx.002": b"cd",
                       "EM.1": b"x", "em.2": b"y", "keep.1": b"k"})
        media._join_split_parts(d)
        self.assertEqual((d / "ht-stag.lzx").read_bytes(), b"abcd")
        self.assertEqual((d / "EM").read_bytes(), b"xy")
        self.assertTrue((d / "keep.1").exists())

    def test_join_digit_suffixed_extension(self):
        # Manipulations: .data1 + .data2 join to .data. Executables that
        # only share a name stem are separate parts of a demo, not halves.
        d = self.tree({"M.data1": b"a", "M.data2": b"b",
                       "part1": EXE, "part2": EXE})
        media._join_split_parts(d)
        self.assertEqual((d / "M.data").read_bytes(), b"ab")
        self.assertTrue((d / "part2").exists())

    def test_join_joinz_bodies(self):
        # Stag's joinz parts: IFF FORM SPLT, the data in each BODY chunk.
        def part(body):
            chunks = b"INFO" + (4).to_bytes(4, "big") + b"\0" * 4 \
                + b"BODY" + len(body).to_bytes(4, "big") + body
            return b"FORM" + (4 + len(chunks)).to_bytes(4, "big") + b"SPLT" + chunks
        d = self.tree({"x.lzx.001": part(b"LZX"), "x.lzx.002": part(b"!!")})
        media._join_split_parts(d)
        self.assertEqual((d / "x.lzx").read_bytes(), b"LZX!!")

    def test_join_keeps_existing_file(self):
        # Flowers: the parts join to Flowers.exe; Flowers is the script.
        d = self.tree({"Flowers": b"Flowers.exe\n", "Flowers.000": b"a",
                       "flowers.001": b"b"})
        media._join_split_parts(d)
        self.assertEqual((d / "Flowers").read_bytes(), b"Flowers.exe\n")
        self.assertEqual((d / "Flowers.exe").read_bytes(), b"ab")

    def test_launch_script_prefers_the_title(self):
        # Eternal Madness: the icon the user opens is a script running the
        # three parts in turn.
        d = self.tree({"Eternal Madness": b"em1.exe\nem2.exe\n",
                       "Eternal Madness.info": b"", "EM1.exe": EXE,
                       "ReadMe": b"text", "ReadMe.info": b""})
        self.assertEqual(media._launch_script(d, "Eternal Madness").name,
                         "Eternal Madness")

    def test_launch_script_needs_an_executable(self):
        d = self.tree({"ht-stag": b";hack\nintro.exe\nstag.ht\n",
                       "intro.exe": EXE, "stag.ht": EXE,
                       "readme.txt": b"use joinz to merge\n",
                       "s/startup-sequence": b"intro.exe\n"})
        self.assertEqual(media._launch_script(d).name, "ht-stag")
        (d / "ht-stag").unlink()
        self.assertIsNone(media._launch_script(d))


if __name__ == "__main__":
    unittest.main()


class UnpackTest(unittest.TestCase):
    def test_lha_that_unar_rejects(self):
        # Creep: unar 1.10 fails some -lh5- members ("read more data than
        # was available"); lha extracts them with good CRCs.
        archive = pathlib.Path(__file__).parent / "data" / "atw_creep.lha"
        dest = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(dest))
        self.assertIsNone(media.unpack(archive, dest))
        self.assertTrue((dest / "Creep.exe").is_file())
        # Nothing left over from unar's partial run (Støy På Larvefødder:
        # its UTF-8 dir collided with lha's Latin-1 one).
        self.assertEqual(sorted(n.name for n in dest.iterdir()),
                         ["Creep.exe", "creep.txt", "file_id.diz", "readit",
                          "tHE-dUNGEON"])

    def test_latin1_names_become_utf8(self):
        # Prince Dakkar: lha writes the Amiga's Latin-1 "tlu-pdva.exé" as a
        # raw 0xE9 byte; Amiberry expects UTF-8 host names.
        dest = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(dest))
        os.makedirs(os.path.join(bytes(dest), b"d\xe9mo"))
        open(os.path.join(bytes(dest), b"d\xe9mo", b"ex\xe9"), "wb").close()
        media._latin1_names_to_utf8(dest)
        self.assertTrue((dest / "démo" / "exé").is_file())

    def test_zip_names_are_latin1(self):
        # Petcity: an Amiga zip stores "é" as byte 0xE9 without the UTF-8
        # flag; read as DOS cp437 it became "Θ", which AmigaDOS can't name.
        dest = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(dest))
        archive = dest / "a.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("pXtcity", b"demo")
        archive.write_bytes(archive.read_bytes().replace(b"pXtcity",
                                                         b"p\xe9tcity"))
        self.assertIsNone(media.unpack(archive, dest / "out"))
        self.assertTrue((dest / "out" / "pétcity").is_file())


class RmtreeTest(unittest.TestCase):
    def test_removes_a_tree_with_amiga_protection_bits(self):
        # Landscape of Hope: an unpack that died partway left a directory
        # without the execute bit, which shutil.rmtree cannot enter.
        top = pathlib.Path(tempfile.mkdtemp())
        sub = top / "x" / "d"
        sub.mkdir(parents=True)
        (sub / "f").write_bytes(b"1")
        os.chmod(sub, 0o644)
        media._rmtree(top)
        self.assertFalse(top.exists())

    def test_removes_a_tree_whose_top_is_read_only(self):
        # Brown Elephant Never Again: the unpack target itself came out
        # r-x, so its files could not be unlinked.
        top = pathlib.Path(tempfile.mkdtemp())
        (top / "nfo.lha").write_bytes(b"1")
        os.chmod(top, 0o555)
        media._rmtree(top)
        self.assertFalse(top.exists())


class RmtreeNestedTest(unittest.TestCase):
    def test_removes_files_below_an_unenterable_directory(self):
        # Grogon Meets uN aMOr: ReadMe.txt sat two levels below a directory
        # without the execute bit; it must be opened up before walking in.
        top = pathlib.Path(tempfile.mkdtemp())
        deep = top / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "ReadMe.txt").write_bytes(b"1")
        os.chmod(deep, 0o555)
        os.chmod(top / "a", 0o600)
        media._rmtree(top)
        self.assertFalse(top.exists())


class FloppyVariantTest(unittest.TestCase):
    def setUp(self):
        self.top = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, self.top)
        patch = unittest.mock.patch.object(media.config, "WORK", self.top / "work")
        patch.start()
        self.addCleanup(patch.stop)

    def hd(self, files):
        root = self.top / "tree"
        for name, data in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(data)
        return media.Variant("hd", [], root=str(root), command='"hc.exe"\n')

    def test_files_and_startup_on_a_boot_disk(self):
        # Hardcore: the loader asks for its files in unit 0.
        fv = media.floppy_variant(self.hd({"hc.exe": EXE, "d/hc.dat": b"x"}), 1)
        self.assertEqual(fv.kind, "floppy")
        adf = pathlib.Path(fv.disks[0]).read_bytes()
        self.assertTrue(media.bootable(adf))
        listing = subprocess.run(["xdftool", fv.disks[0], "list"],
                                 capture_output=True, text=True).stdout
        for name in ("hc.exe", "hc.dat", "startup-sequence", "scenedb-setup"):
            self.assertIn(name, listing)

    def test_too_big(self):
        v = self.hd({"hc.exe": EXE, "big": b"\0" * (media.OFS_BYTES + 1)})
        self.assertIsNone(media.floppy_variant(v, 1))


class ArchiveSetTest(unittest.TestCase):
    def test_numbered_archives_unpack_into_one_tree(self):
        # Repugnance: pwl-rpg1.lha holds the demo, rpg2 and rpg3 its data.
        top = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, top)
        for k, v in {"DEMOZOO_DIR": top / "nas", "WORK": top / "work"}.items():
            patch = unittest.mock.patch.object(media.config, k, v)
            patch.start()
            self.addCleanup(patch.stop)
        src = media.config.prod_dir(35337)
        src.mkdir(parents=True)
        for name, files in {"pwl-rpg1.zip": {"Repugnance": EXE,
                                             "data/rep-001.data": b"1"},
                            "pwl-rpg2.zip": {"data/rep-002.data": b"2"}}.items():
            with zipfile.ZipFile(src / name, "w") as z:
                for n, data in files.items():
                    z.writestr(n, data)
        vs, problems = media.variants(35337, "Repugnance")
        self.assertEqual(problems, [])
        self.assertEqual(len(vs), 1)
        root = pathlib.Path(vs[0].root)
        self.assertEqual(sorted(p.name for p in (root / "data").iterdir()),
                         ["rep-001.data", "rep-002.data"])


class DmsPartsTest(unittest.TestCase):
    def test_halves_of_one_disk_join(self):
        # Ilex: ilex-a.dms holds cylinders 0-39, ilex-b.dms 40-79.
        top = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, top)
        (top / "adf").mkdir()
        half = 40 * media.CYL_BYTES
        parts = {}
        for name, low, high, fill in (("x-a", 0, 39, b"A"), ("x-b", 40, 79, b"B")):
            p = top / f"{name}.dms"
            p.write_bytes(b"DMS!" + b"\0" * 12 + struct.pack(">HH", low, high))
            self.assertEqual(media.dms_cylinders(p), (low, high))
            parts[str(p)] = top / f"{name}.adf"
            parts[str(p)].write_bytes(fill * half)
        with unittest.mock.patch.object(
                media, "_as_adf", lambda d, w: parts[str(d)]):
            joined = media._join_dms_parts(list(parts), top)
        data = pathlib.Path(joined).read_bytes()
        self.assertEqual(data, b"A" * half + b"B" * half)

    def test_whole_disks_stay_a_set(self):
        top = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, top)
        paths = []
        for name in ("d1", "d2"):
            p = top / f"{name}.dms"
            p.write_bytes(b"DMS!" + b"\0" * 12 + struct.pack(">HH", 0, 79))
            paths.append(str(p))
        self.assertIsNone(media._join_dms_parts(paths, top))


ADF = 901120


class DiskImageSanityTest(unittest.TestCase):
    def file(self, name, data):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, d)
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def test_apple_double_is_not_a_disk(self):
        p = self.file("__MACOSX/x/._demo.adf", b"\0\5\x16\7" + b"\0" * 200)
        self.assertIsNone(media.sniff(p))
        q = self.file("._demo.adf", b"\0" * ADF)
        self.assertIsNone(media.sniff(q))

    def test_good_adf(self):
        p = self.file("a.adf", b"DOS\0" + b"\0" * (ADF - 4))
        self.assertIsNone(media.image_problem(p))

    def test_html_saved_as_adf(self):
        for head in (b"<html>", b"<!DOCTYPE html>", b"\n<!doctype"):
            p = self.file("a.adf", head + b" 404 Not Found")
            self.assertEqual(media.image_problem(p), "html-not-a-disk")

    def test_stub_size(self):
        p = self.file("a.adf", b"DOS\0" + b"\0" * 1000)
        self.assertEqual(media.image_problem(p), "bad-image-size")

    def test_truncated_trackloader_image_is_kept(self):
        # 14 of the 31 short or long images in the sweep work.
        for size in (media.CYL_BYTES, 495616, 2124148):
            p = self.file("a.adf", b"\0" * size)
            self.assertIsNone(media.image_problem(p))

    def test_atari_st_disk(self):
        boot = bytearray(737280)
        boot[0] = 0x60
        boot[11:13] = (512).to_bytes(2, "little")
        p = self.file("a.adf", bytes(boot))
        self.assertEqual(media.image_problem(p), "atari-st-disk")

    def test_html_dms_and_adz(self):
        self.assertEqual(media.image_problem(
            self.file("a.dms", b"<HTML>x")), "html-not-a-disk")
        self.assertEqual(media.image_problem(
            self.file("a.adz", b"<HTML>x")), "html-not-a-disk")

    def test_dms_and_adz_are_not_size_checked(self):
        self.assertIsNone(media.image_problem(self.file("a.dms", b"DMS!" + b"\0" * 40)))

    def test_ffs_flag(self):
        self.assertTrue(media.is_ffs(b"DOS\1" + b"\0" * 1020))
        self.assertTrue(media.is_ffs(b"DOS\3"))
        self.assertFalse(media.is_ffs(b"DOS\0"))
        self.assertFalse(media.is_ffs(b"KICK"))


class FfsVariantTest(unittest.TestCase):
    def test_ffs_dms_variant_is_flagged(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, d)
        ffs, ofs = d / "f.adf", d / "o.adf"
        ffs.write_bytes(b"DOS\1" + b"\0" * (ADF - 4))
        ofs.write_bytes(b"DOS\0" + b"\0" * (ADF - 4))
        self.assertTrue(media.flag_ffs(media.Variant("floppy", [str(ffs)]), d).ffs)
        self.assertFalse(media.flag_ffs(media.Variant("floppy", [str(ofs)]), d).ffs)
        self.assertFalse(media.flag_ffs(media.Variant("hd", [], root="x"), d).ffs)
