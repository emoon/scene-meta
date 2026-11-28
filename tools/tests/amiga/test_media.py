import hashlib
import os
import pathlib
import struct
import subprocess
import tempfile
import unittest
import unittest.mock
import zipfile

from scenemeta.amiga import media, player
from scenemeta.core.errors import CannotPlay

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

    def test_auto_prefers_multipart_launcher_before_a_successful_part(self):
        d = self.tree({"part1.exe": EXE, "part2.exe": EXE * 4,
                       "MyKing.bat": b"part1.exe\npart2.exe\n"})
        v = media._tree_variant(d, "My Kingdom")
        self.assertEqual(v.run, "MyKing.bat")
        self.assertEqual(v.command, GO_ON + "part1.exe\npart2.exe\n")
        self.assertEqual(media._tree_variant(d, "My Kingdom", "part2.exe").run,
                         "part2.exe")

    def test_auto_prefers_root_launcher_that_sets_up_a_viewer(self):
        d = self.tree({"MainActor": EXE, "mainactor/MainView": EXE,
                       "Runme!": b"assign MainActor: mainactor\ncd BillGates\nMainActor:MainView Bill.anim\n",
                       "BillGates/Bill Gates": b"MainActor:MainView Bill.anim\n"})
        v = media._tree_variant(d, "Bill Gates")
        self.assertEqual((v.run, v.root), ("Runme!", str(d)))

    def test_auto_preserves_interpreter_arguments(self):
        d = self.tree({"Karate": EXE, "PointsSO": b"Karate s=SOscroll.txt\n"})
        self.assertEqual(media._tree_variant(d, "Points SO").run, "PointsSO")

    def test_auto_leaves_plain_single_exe_and_unrelated_launchers_alone(self):
        d = self.tree({"Demo": EXE, "runme": b"Demo\n",
                       "other": EXE, "Other.bat": b"other\n"})
        self.assertEqual(media._tree_variant(d, "Demo").run, "Demo")
        d = self.tree({"PlayMusique": EXE, "0init.dat": EXE,
                       "Ukonx": b"0init.dat\nrun PlayMusique\n"})
        self.assertEqual(media._tree_variant(d, "Acid O'Zine").run,
                         "PlayMusique")

    def test_auto_does_not_execute_documentation_or_requestchoice(self):
        d = self.tree({"Demo.exe": EXE, "read_me_now!.ascii": b"Demo.exe\nDemo.exe\n",
                       "StartMe": b'RequestChoice >env:c "Choose" "Start"\nDemo.exe\n'})
        self.assertEqual(media._tree_variant(d, "Demo").run, "Demo.exe")

    def test_auto_numeric_script_keeps_viewer_arguments(self):
        d = self.tree({"Easy": EXE, "2": b"Easy >nil: Demo2\n"})
        self.assertEqual(media._tree_variant(d, "Disco").run, "2")

    def test_system_commands_and_inline_comments_are_not_more_parts(self):
        d = self.tree({"sustain.exe": EXE, "C/cpu": EXE,
                       "runme": b"cpu cache burst\nsustain.exe ; the demo\n"})
        self.assertEqual(media._tree_variant(d, "Sustain").run, "sustain.exe")

    def test_no_executables_means_no_launcher_candidates(self):
        d = self.tree({"readme": b"Hello\n"})
        self.assertIsNone(media._launch_script(d))
        self.assertIsNone(media._tree_variant(d))

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

    def test_skips_non_longword_hunk_files(self):
        # Like OTLUE2Z61.exe (3195 B): starts with HUNK_MAGIC but is not
        # longword-aligned, so AmigaDOS rejects it ("file is not executable").
        bad = media.HUNK_MAGIC + b"\0" * 59   # 63 bytes (mod 4 == 3)
        d = self.tree({"OTLUE2Z61.exe": bad, "sub/real.exe": EXE})
        self.assertIsNone(media.sniff(d / "OTLUE2Z61.exe"))
        self.assertEqual(media._pick_exe(d)[0].name, "real.exe")

    def test_deprioritizes_speedhunk_bbs_ad_stubs(self):
        # Like 2944 / 29162 / 2505: BBS advert stub at root tagged HEADDBGV01
        # plus SpeedHunk HUNK_CODE must lose to the real demo inside a
        # subdirectory, yet still run if it is the only executable.
        bbs_ad = (media.HUNK_MAGIC + b"\0" * 20
                  + b"\x00\x00\x03\xf1\x00\x00\x00\x0b\x00\x00\x00\x00HEADDBGV01"
                  + b"\0" * 18 + media._BBS_AD_CODE + b"\0" * 20)
        d = self.tree({"WHEREFUNROLEZ.EXE": bbs_ad,
                       "advertro/Instinct-AdvertTro.x": EXE})
        self.assertEqual(media._pick_exe(d, "Swappers For Everyone")[0].name,
                         "Instinct-AdvertTro.x")
        d_only = self.tree({"ad.exe": bbs_ad})
        self.assertEqual(media._pick_exe(d_only)[0].name, "ad.exe")
        # Real demos whose linker emitted HEADDBGV01 without the SpeedHunk stub
        # (Embryo 7474) must NOT be demoted.
        real_dbg = (media.HUNK_MAGIC + b"\0" * 20
                    + b"\x00\x00\x03\xf1\x00\x00\x00\x0b\x00\x00\x00\x00HEADDBGV01"
                    + b"\0" * 58)
        d_real = self.tree({"embryo.exe": real_dbg, "other": EXE * 4})
        self.assertEqual(media._pick_exe(d_real, "Embryo")[0].name, "embryo.exe")

    def test_prefers_exe_suffix_and_deprioritizes_ppc_rtg_and_setpatch(self):
        # Mindprobe (7627): .exe beats larger non-.exe sibling part.
        d = self.tree({"tbl-mp.exe": EXE, "landtunnel": EXE * 10,
                       "SetPatch": EXE * 20})
        self.assertEqual(media._pick_exe(d, "Mindprobe")[0].name, "tbl-mp.exe")
        # Amsterdam Blessings (9064) & Zero Divide (49455): native 68k/AGA
        # beats PPC / WarpOS / CGX siblings.
        d_ppc = self.tree({"mwi-amsbless_final.exe": EXE,
                           "mwi-amsbless_final.ppc": EXE * 10})
        self.assertEqual(media._pick_exe(d_ppc, "Amsterdam Blessings")[0].name,
                         "mwi-amsbless_final.exe")
        d_cgx = self.tree({"zerodivide.aga": EXE, "zerodivide.cgx": EXE * 10})
        self.assertEqual(media._pick_exe(d_cgx, "Zero Divide")[0].name,
                         "zerodivide.aga")
        # Single-letter and numbered subpart extensions (.f, .dat1, .2) demoted.
        d_sub = self.tree({"tbl-que.exe": EXE, "tbl-que.f": EXE * 10,
                           "part.dat1": EXE * 20})
        self.assertEqual(media._pick_exe(d_sub, "Queue")[0].name, "tbl-que.exe")

    def test_hd_fallback_tries_launch_script_beside_exe(self):
        # Karate / Engine demos: a launcher script passes s=... b=... w=320 h=240.
        d = self.tree({"Karate": EXE, "Prase Party Story": b"karate s=main.txt w=320"})
        v = media._tree_variant(d, "Prase Party Story")
        fbs = media.fallbacks(v, 1074, "Prase Party Story")
        self.assertEqual(fbs[0][0], "hd")
        sv = fbs[0][1]()
        self.assertEqual((sv.kind, sv.run, sv.choice), ("hd", "Prase Party Story", True))
        self.assertEqual(sv.command, f"{GO_ON}karate s=main.txt w=320\n")

    def test_title_match_beats_shallower_unrelated_exe(self):
        # Party packs / archives with root tools: nested title match wins.
        d = self.tree({"helper.exe": EXE * 4, "64k/3/O.K.exe": EXE})
        self.assertEqual(media._pick_exe(d, "o.k.")[0].name, "O.K.exe")

    def test_deprioritizes_numbered_subpart_exes_but_keeps_cpu_suffixes(self):
        # Captured Dreams (40): tbl-cd.exe (launcher) beats tbl-cd.e03 (part).
        d = self.tree({"tbl-cd.exe": EXE, "tbl-cd.e03": EXE * 10})
        self.assertEqual(media._pick_exe(d, "Captured Dreams")[0].name,
                         "tbl-cd.exe")
        # CPU suffixes (.060) are NOT demoted.
        d_cpu = self.tree({"demo.060": EXE * 4, "helper.exe": EXE})
        self.assertEqual(media._pick_exe(d_cpu, "demo")[0].name, "demo.060")

    def test_launch_script_ignores_doc_files(self):
        # Luminagia.readme mentions Luminagia on its own line; must not run it.
        d = self.tree({"Luminagia": EXE,
                       "Luminagia.readme": b"Luminagia - a demo by ...\n"})
        self.assertIsNone(media._launch_script(d, "Luminagia"))

    def test_launch_script_matches_subdir_exe_with_volume_prefix(self):
        # MindWalker (40318): root `go` script calls `mw:data/mindwalker.exe`.
        d = self.tree({"go": b"assign mw: \"\"\nmw:data/mindwalker.exe\n",
                       "data/mindwalker.exe": EXE})
        self.assertEqual(media._launch_script(d, "MindWalker").name, "go")

    def test_project_icon_default_tool_and_named_roundtrip(self):
        # Ikke Bare Rabarbra (2938): Workbench WBPROJECT icon with Default Tool.
        import struct
        deftool = b"ScalaMMPlayer\0"
        hdr = bytearray(78)
        hdr[0:2] = b"\xe3\x10"
        hdr[48] = 4  # WBPROJECT
        struct.pack_into(">I", hdr, 50, 1)  # has DefaultTool
        icon = bytes(hdr) + struct.pack(">I", len(deftool)) + deftool
        d = self.tree({"ScalaMMPlayer": EXE,
                       "demo.scala": b"SCALA SCRIPT\n",
                       "demo.scala.info": icon})
        pv = media._project_icon(d, "Demo")
        self.assertEqual((pv.command, pv.run), ('"ScalaMMPlayer" "demo.scala"\n', "demo.scala"))
        # Round-trip via _tree_variant(..., run="demo.scala")
        rt = media._tree_variant(d, "Demo", run="demo.scala")
        self.assertEqual((rt.command, rt.run), ('"ScalaMMPlayer" "demo.scala"\n', "demo.scala"))

    def test_inferred_assigns_from_binary_and_readme(self):
        d = self.tree({
            "hate2.exe": EXE + b"\0Hate2:PV.exe\0SYS:Libs\0Nuprogdir:PV.exe\0work:PV.exe\0",
            "PV.exe": EXE,
            "readme.txt": b"Please assign CNCD: to this directory.\n",
            "font/XEN.font": b"x",
        })
        self.assertEqual(media._inferred_assigns(d),
                         {"CNCD": "Demo:", "FONTS": "Demo:font",
                          "Hate2": "Demo:", "work": "Demo:"})

    def test_excludes_slave_bitmap_fonts_and_demotes_starter_and_cli_tools(self):
        d = self.tree({
            "Game.Slave": EXE * 20,
            "aed2.font": b"font",
            "aed2/8f": EXE * 10,
            "S_MDIB_starter": EXE,
            "S_MDIB_starter.info": b"",
            "S_MDIB.exe": EXE * 5,
            "list": EXE * 4,
            "2": EXE,
            "sg2": EXE * 2,
        })
        self.assertEqual(media._pick_exe(d, "Silicon Gfx 2")[0].name, "S_MDIB.exe")
        d2 = self.tree({"2": EXE, "sg2": EXE * 2})
        self.assertEqual(media._pick_exe(d2, "Silicon Gfx 2")[0].name, "sg2")
        # Bare .info does not crash _project_icon / _named_project.
        d3 = self.tree({".info": b"\xe3\x10" + b"\0" * 80, "demo": EXE})
        self.assertIsNone(media._project_icon(d3))
        self.assertIsNone(media._named_project(d3, "demo"))
        # Overlay hunk with size % 4 != 0 is sniffed as exe.
        ovl = media.HUNK_MAGIC + b"\0" * 24 + b"\x00\x00\x03\xf5" + b"\0" * 30
        d4 = self.tree({"fallen_angels": ovl})
        self.assertEqual(media.sniff(d4 / "fallen_angels"), "exe")

    def test_fold_case_dirs_and_merge_disk_dirs(self):
        d = self.tree({"YACS/engine": EXE, "yacs/yacs": b"engine\n"})
        media._fold_case_dirs(d)
        self.assertEqual(len([p for p in d.iterdir() if p.is_dir()]), 1)
        sub = next(p for p in d.iterdir() if p.is_dir())
        self.assertEqual(sorted(p.name for p in sub.iterdir()), ["engine", "yacs"])

        d2 = self.tree({"DISK1/demo": EXE, "DISK2/data.bin": b"hi"})
        media._merge_disk_dirs(d2)
        self.assertTrue((d2 / "DISK1" / "data.bin").is_file())

    def test_ramos_pairs_with_amos_file_and_copies_ancestor_fonts(self):
        d = self.tree({
            "fonts/foo.font": b"f",
            "sub/RAMOS1.2": EXE,
            "sub/MyDemo.AMOS": b"AMOS Basic V1.00" + b"\0" * 100,
        })
        v = media._tree_variant(d)
        self.assertEqual(v.command, '"RAMOS1.2" MyDemo.AMOS\n')
        self.assertTrue((d / "sub" / "fonts" / "foo.font").is_file())

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
    def setUp(self):
        self.top = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("DEMOZOO_DIR", "WORK"):
            self.enterContext(unittest.mock.patch.object(
                media.config, name, self.top / name.lower()))
        self.src = media.config.prod_dir(1)
        self.src.mkdir(parents=True)

    def archive(self, name, files):
        with zipfile.ZipFile(self.src / name, "w") as z:
            for filename, data in files.items():
                z.writestr(filename, data)

    def test_installer_join_resolves_split_numeric_files_in_casefolded_tree(self):
        self.archive("release1.zip", {
            "demo/sub/1": EXE[:32],
            "demo/sub/Install.script": b"jOiN >NIL: 1 2 AS Demo.exe\n",
            "demo/sub/ReadMe": b"old",
        })
        self.archive("release2.zip", {"Demo/Sub/2": EXE[32:],
                                     "Demo/Sub/README": b"new"})
        variants, problems = media.variants(1, "Demo")
        self.assertEqual(problems, [])
        variant, = variants
        self.assertEqual(variant.run, "Demo.exe")
        root = pathlib.Path(variant.root)
        self.assertEqual((root / "Demo.exe").read_bytes(), EXE)
        self.assertEqual((root / "1").read_bytes(), EXE[:32])
        self.assertEqual((root / "2").read_bytes(), EXE[32:])
        self.assertEqual((root / "ReadMe").read_bytes(), b"new")
        self.assertFalse((root / "README").exists())
        self.assertEqual([p.name for p in root.parent.iterdir()], ["sub"])

    def test_documented_join_supports_a_quoted_command_and_casefolded_names(self):
        self.archive("release.zip", {
            "Demo.001": EXE[:32],
            "Demo.002": EXE[32:],
            "Demo.readme": b'  "Join demo.001 DEMO.002 TO Demo.exe"\r\n',
        })
        (variant,), _ = media.variants(1, "Demo")
        self.assertEqual(variant.run, "Demo.exe")
        self.assertEqual((pathlib.Path(variant.root) / "Demo.exe").read_bytes(), EXE)

    def test_join_uses_literal_names_and_the_order_in_the_command(self):
        self.archive("release.zip", {
            "part two": b"second",
            "part one": b"first ",
            "part three": b" third",
            "Install": (b'Join "Part One" "Part Two" "Part Three" '
                        b'TO "Output data" ; install data\n'),
            "main.exe": EXE,
        })
        (variant,), _ = media.variants(1)
        self.assertEqual((pathlib.Path(variant.root) / "Output data").read_bytes(),
                         b"first second third")

    def test_join_skips_missing_parts_and_existing_or_nonlocal_destinations(self):
        (self.top / "outside").write_bytes(b"outside")
        self.archive("release.zip", {
            "file1": b"a", "file2": b"b", "Existing": b"keep",
            "Install": (b"Join file1 missing AS missing.exe\n"
                        b"Join file1 file2 TO existing\n"
                        b"Join file1 file2 TO ../outside\n"
                        b"Join file1 file2 TO SYS:startup-sequence\n"
                        b"Join file1 #? TO wildcard\n"),
            "main.exe": EXE,
        })
        (variant,), _ = media.variants(1)
        root = pathlib.Path(variant.root)
        self.assertEqual((root / "Existing").read_bytes(), b"keep")
        for name in ("existing", "missing.exe", "../outside", "wildcard",
                     "SYS:startup-sequence"):
            self.assertFalse((root / name).exists())
        self.assertEqual((self.top / "outside").read_bytes(), b"outside")

    def test_standalone_launcher_shares_the_companion_archive_boot_directory(self):
        self.archive("effects.zip", {"Release/part": EXE, "Release/data": b"123"})
        (self.src / "Main.exe").write_bytes(EXE)
        variants, problems = media.variants(1, "Main")
        self.assertEqual(problems, [])
        archived, standalone = variants
        self.assertEqual(standalone.run, "Main.exe")
        root = pathlib.Path(standalone.root)
        self.assertEqual((root / "Main.exe").read_bytes(), EXE)
        self.assertEqual((root / "part").read_bytes(), EXE)
        self.assertEqual((root / "data").read_bytes(), b"123")
        self.assertFalse((pathlib.Path(archived.root) / "Main.exe").exists())

    def test_standalone_without_a_unique_companion_remains_independent(self):
        self.archive("effects.zip", {"effects/part": EXE})
        self.archive("other.zip", {"other/part2": EXE})
        (self.src / "Main.exe").write_bytes(EXE)
        variants, _ = media.variants(1)
        variant = next(v for v in variants if v.run == "Main.exe")
        self.assertEqual([p.name for p in pathlib.Path(variant.root).iterdir()],
                         ["Main.exe"])

    def test_standalone_launcher_can_use_a_data_only_archive(self):
        self.archive("data.zip", {"data/picture": b"picture"})
        (self.src / "Main.exe").write_bytes(EXE)
        (variant,), _ = media.variants(1)
        self.assertEqual(variant.run, "Main.exe")
        self.assertEqual((pathlib.Path(variant.root) / "data/picture").read_bytes(),
                         b"picture")

    def test_standalone_does_not_overwrite_case_insensitive_archive_name(self):
        self.archive("release.zip", {"MAIN.EXE": EXE + EXE, "data": b"123"})
        (self.src / "main.exe").write_bytes(EXE)
        variants, _ = media.variants(1)
        archived, standalone = variants
        self.assertEqual([p.name for p in pathlib.Path(standalone.root).iterdir()],
                         ["main.exe"])
        self.assertEqual((pathlib.Path(archived.root) / "MAIN.EXE").read_bytes(),
                         EXE + EXE)

    def test_player_uses_explicit_boot_order_of_a_whole_set(self):
        first, second = "Demo-A.adf", "Demo-B.adf"
        (self.src / first).write_bytes(bytes(media.CYL_BYTES))
        (self.src / second).write_bytes(b"DOS\1" + bytes(media.CYL_BYTES - 4))
        with unittest.mock.patch.object(media, "launch_variant",
                                        return_value=None) as launch:
            (default,), _ = media.variants(1)
            self.assertEqual(media._disk_names(default), [first, second])
            self.assertFalse(default.ffs)
            entry = {"title": "Demo", "disks": [second, first]}
            ordered = player._variant_of(1, entry)
            self.assertEqual(media._disk_names(ordered), [second, first])
            self.assertTrue(ordered.ffs)
            self.assertTrue(ordered.complete)
            self.assertEqual([pathlib.Path(p).name for p in launch.call_args.args[0]],
                             [second, first])
            with self.assertRaisesRegex(CannotPlay, "fits none"):
                player._variant_of(1, {**entry, "disks": [second, second]})

    def test_numbered_archives_unpack_into_one_tree(self):
        # Repugnance: pwl-rpg1.lha holds the demo, rpg2 and rpg3 its data.
        self.archive("pwl-rpg1.zip", {"Repugnance": EXE, "data/rep-001.data": b"1"})
        self.archive("pwl-rpg2.zip", {"data/rep-002.data": b"2"})
        vs, problems = media.variants(1, "Repugnance")
        self.assertEqual(problems, [])
        self.assertEqual(len(vs), 1)
        root = pathlib.Path(vs[0].root)
        self.assertEqual(sorted(p.name for p in (root / "data").iterdir()),
                         ["rep-001.data", "rep-002.data"])

    def test_a_download_asked_to_start_its_script(self):
        self.archive("demo.zip", {"intro.exe": EXE, "end.exe": EXE * 2,
                                  "demo.bat": b"intro.exe\nend.exe\n"})
        (today,), _ = media.variants(1, "Demo")
        self.assertEqual(today.command, GO_ON + "intro.exe\nend.exe\n")
        (bare,), _ = media.variants(1, "Demo", "end.exe")
        self.assertEqual(bare.command, '"end.exe"\n')
        (asked,), _ = media.variants(1, "Demo", "demo.bat")
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
