import hashlib
import os
import pathlib
import struct
import subprocess
import tempfile
import unittest
import unittest.mock
import zipfile

from scenemeta.amiga import media

EXE = media.HUNK_MAGIC + b"\0" * 60
GO_ON = media.workbench.GO_ON + "\n"


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

    def test_the_file_an_entry_names_goes_before_any_pick(self):
        # Sheep Dictionary: the entry runs KryptoniteII.exe, not the one
        # named after the title.
        d = self.tree({"Dictionary": EXE, "KryptoniteII.exe": EXE,
                       "sub/demo": EXE * 9})
        self.assertEqual(media._pick_exe(d, "Sheep Dictionary")[0].name,
                         "Dictionary")
        v = media._tree_variant(d, "Sheep Dictionary", "KryptoniteII.exe")
        self.assertEqual((v.run, v.choice), ("KryptoniteII.exe", True))
        # By its path too, as a patched disk or a merged set is named.
        self.assertEqual(media._pick_exe(d, run="sub/demo")[0].name, "demo")
        # A file that is not there changes nothing.
        self.assertEqual(media._pick_exe(d, "Sheep Dictionary", "gone")[0].name,
                         "Dictionary")

    def test_an_entry_may_name_a_launcher_script(self):
        # Megademo $c: Megademo$C.bat runs the five parts in turn.
        bat = b"intro.exe\nmdctrad.exe\nN\xc5.exe\n"
        d = self.tree({"intro.exe": EXE, "MDCtrad.exe": EXE * 9,
                       "N\u00c5.exe": EXE, "Megademo$C.bat": bat,
                       "sub/go": b'assign dev: ""\npart1\n', "sub/part1": EXE})
        v = media._tree_variant(d, "Megademo $c", "Megademo$C.bat")
        self.assertEqual((v.kind, v.root, v.run, v.choice),
                         ("hd", str(d), "Megademo$C.bat", True))
        # Past a command the download lacks, as on its author's machine.
        self.assertEqual(v.command,
                         f"{media.workbench.GO_ON}\n" + bat.decode("latin-1"))
        self.assertTrue(media.fits(v, {"run": "Megademo$C.bat"}, "hd"))
        # Executed from its own directory, so what it names is beside it.
        # Named as the entry names it, by its path or its name alone.
        for run in ("sub/go", "go"):
            v = media._tree_variant(d, "", run)
            self.assertEqual((v.root, v.run), (str(d / "sub"), run))
            self.assertTrue(media.fits(v, {"run": run}, "hd"))

    def test_only_a_text_file_is_a_script(self):
        d = self.tree({"demo": EXE, "data": b"a\0b", "empty": b"",
                       "big": b"x" * 20000})
        for run in ("data", "empty", "big", "gone"):
            self.assertEqual(media._tree_variant(d, "", run).run, "demo")

    def test_what_an_entry_says_of_a_variant(self):
        only = media.Variant("hd", [], run="demo")
        both = media.Variant("floppy", ["/n/a.adf", "/n/b.adf"])
        picked = media.Variant("hd", [], run="other", choice=True)
        every = [only, both, picked]
        self.assertEqual(media.named(only, every), {})
        self.assertEqual(media.named(both, every),
                         {"boot": "floppy", "disks": ["a.adf", "b.adf"]})
        self.assertEqual(media.named(picked, every), {"run": "other"})

    def test_two_variants_an_entry_would_say_the_same_of_are_told_apart(self):
        # A disk that boots, and the archive's files on a floppy of their
        # own: by the file started. Two disks: by their names.
        disk = media.Variant("floppy", ["/n/demo.adf"])
        fixed = media.Variant("floppy", ["/n/demo-fixed.adf"])
        tree = media.Variant("hd", [], run="demo.exe")
        on_floppy = media.Variant("floppy", ["/w/disk.adf"], run="demo.exe")
        every = [disk, tree, on_floppy]
        self.assertEqual(media.named(on_floppy, every), {"run": "demo.exe"})
        self.assertEqual(media.named(disk, every), {"disks": ["demo.adf"]})
        self.assertEqual(media.named(tree, every), {"boot": "hd"})
        self.assertEqual(media.named(fixed, [disk, fixed]),
                         {"disks": ["demo-fixed.adf"]})
        for v in every:
            said = media.named(v, every)
            self.assertEqual([o for o in every if media.fits(o, said, "floppy")],
                             [v])

    def test_an_entry_may_say_more_than_it_has_to(self):
        only = media.Variant("hd", [], run="demo.exe")
        disk = media.Variant("floppy", ["/n/a.adf"])
        self.assertTrue(media.fits(only, {"run": "demo.exe"}, "hd"))
        self.assertTrue(media.fits(only, {"boot": "hd"}, "hd"))
        self.assertTrue(media.fits(disk, {"disks": ["a.adf"]}, "floppy"))
        self.assertFalse(media.fits(only, {"run": "other"}, "hd"))
        self.assertFalse(media.fits(disk, {"run": "demo.exe"}, "floppy"))
        self.assertFalse(media.fits(disk, {"disks": ["b.adf"]}, "floppy"))
        # What it leaves out is as usual: no set, no file there was a
        # choice of.
        picked = media.Variant("hd", [], run="demo.exe", choice=True)
        both = media.Variant("floppy", ["/n/a.adf", "/n/b.adf"])
        self.assertFalse(media.fits(picked, {}, "hd"))
        self.assertFalse(media.fits(both, {}, "floppy"))

    def test_a_variant_says_what_it_starts(self):
        d = self.tree({"demo (final)": EXE})
        v = media._tree_variant(d)
        self.assertEqual((v.run, v.choice), ("demo (final)", False))

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

    def hd(self, files, root="tree"):
        root = self.top / root
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
        for name in ("hc.exe", "hc.dat", "startup-sequence", "scenemeta-setup"):
            self.assertIn(name, listing)

    def test_too_big(self):
        v = self.hd({"hc.exe": EXE, "big": b"\0" * (media.OFS_BYTES + 1)})
        self.assertIsNone(media.floppy_variant(v, 1))

    def test_the_floppy_of_one_tree_outlives_the_making_of_anothers(self):
        # Two archives that each hold a directory of the same name.
        one = media.floppy_variant(self.hd({"hc.exe": EXE}, "a/demo"), 1)
        two = media.floppy_variant(self.hd({"hc.exe": EXE * 2}, "b/demo"), 1)
        self.assertNotEqual(one.disks, two.disks)
        self.assertNotEqual(pathlib.Path(one.disks[0]).read_bytes(),
                            pathlib.Path(two.disks[0]).read_bytes())

    def test_a_merged_set_runs_the_script_its_entry_names(self):
        def unpacked(adf, box):
            tree = box / "files"
            tree.mkdir(parents=True, exist_ok=True)
            for name, data in {"a.exe": EXE, "b.exe": EXE,
                               "start": b"a.exe\nb.exe\n",
                               "alt/other": b"cd /\nb.exe\n"}.items():
                (tree / name).parent.mkdir(exist_ok=True)
                (tree / name).write_bytes(data)
            return tree
        disks = ["/d/x-a.adf", "/d/x-b.adf"]
        with unittest.mock.patch.object(media, "_unpack_disk", unpacked):
            picked = media.merged_variant(disks, 1, "")
            self.assertEqual((picked.run, picked.command),
                             ("start", GO_ON + "a.exe\nb.exe\n"))
            named = media.merged_variant(disks, 1, "", "alt/other")
            self.assertEqual((named.run, named.command),
                             ("alt/other", GO_ON + "cd /\nb.exe\n"))
            self.assertEqual(pathlib.Path(named.root).name, "alt")
            self.assertEqual(media.merged_variant(disks, 1, "", "other").run,
                             "other")
            self.assertEqual(media.merged_variant(disks, 1, "", "b.exe").run,
                             "b.exe")

    def test_the_merge_of_one_set_outlives_the_making_of_anothers(self):
        def unpacked(adf, box):
            tree = box / "files"
            tree.mkdir(parents=True, exist_ok=True)
            for old in tree.iterdir():
                old.unlink()
            (tree / pathlib.Path(adf).stem).write_bytes(EXE)
            return tree
        with unittest.mock.patch.object(media, "_unpack_disk", unpacked):
            one = media.merged_variant(["/d/one-a.adf", "/d/one-b.adf"], 1, "")
            two = media.merged_variant(["/d/two-a.adf", "/d/two-b.adf"], 1, "")
        self.assertNotEqual(one.root, two.root)
        self.assertEqual(sorted(os.listdir(one.root)), ["one-a", "one-b"])
        self.assertEqual(sorted(os.listdir(two.root)), ["two-a", "two-b"])


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

    def test_a_download_asked_to_start_its_script(self):
        top = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, top)
        for k, v in {"DEMOZOO_DIR": top / "nas", "WORK": top / "work"}.items():
            patch = unittest.mock.patch.object(media.config, k, v)
            patch.start()
            self.addCleanup(patch.stop)
        src = media.config.prod_dir(44911)
        src.mkdir(parents=True)
        with zipfile.ZipFile(src / "demo.zip", "w") as z:
            for n, data in {"intro.exe": EXE, "end.exe": EXE * 2,
                            "demo.bat": b"intro.exe\nend.exe\n"}.items():
                z.writestr(n, data)
        (today,), _ = media.variants(44911, "Demo")
        self.assertEqual(today.command, '"end.exe"\n')
        (asked,), _ = media.variants(44911, "Demo", "demo.bat")
        self.assertEqual((asked.run, asked.command),
                         ("demo.bat", GO_ON + "intro.exe\nend.exe\n"))


class DownloadSha256Test(unittest.TestCase):
    def setUp(self):
        top = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(media._rmtree, top)
        patch = unittest.mock.patch.object(media.config, "DEMOZOO_DIR", top)
        patch.start()
        self.addCleanup(patch.stop)
        self.src = media.config.prod_dir(142)
        self.src.mkdir(parents=True)

    def test_one_file_is_its_sha256(self):
        (self.src / "demo.lha").write_bytes(b"abc")
        self.assertEqual(media.download_sha256(142),
                         hashlib.sha256(b"abc").hexdigest())

    def test_a_file_still_being_fetched_is_no_part_of_it(self):
        (self.src / "demo.lha").write_bytes(b"abc")
        (self.src / "demo2.lha.part").write_bytes(b"ab")
        self.assertEqual(media.download_sha256(142),
                         hashlib.sha256(b"abc").hexdigest())

    def test_several_files_change_it_by_content_and_by_name(self):
        def of(files):
            for f in self.src.iterdir():
                f.unlink()
            for name, data in files.items():
                (self.src / name).write_bytes(data)
            return media.download_sha256(142)
        both = of({"a.adf": b"1", "b.adf": b"2"})
        self.assertRegex(both, "^[0-9a-f]{64}$")
        self.assertEqual(of({"b.adf": b"2", "a.adf": b"1"}), both)
        self.assertNotEqual(of({"a.adf": b"1", "b.adf": b"3"}), both)
        self.assertNotEqual(of({"a.adf": b"1", "c.adf": b"2"}), both)
        self.assertNotEqual(of({"a.adf": b"1"}), both)

    def test_no_download_has_none(self):
        self.assertIsNone(media.download_sha256(142))
        self.assertIsNone(media.download_sha256(143))


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
