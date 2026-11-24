import pathlib
import tempfile
import tomllib
import unittest

from scenemeta import document, merge, validate

MACHINES = 'default = "a500"\n\n[a500]\ncpu = "68000"\n\n[a1200]\ncpu = "68ec020"\n'


def script(title, **more):
    return {"title": title, "source": "script", **more}


class DocumentTest(unittest.TestCase):
    def test_render_reads_back(self):
        entry = {"note": 'say "hi"\\ there\n', "title": "Désert", "source": "ai",
                 "events": [{"at": 536.9, "disk": 2}, {"at": 541.9, "key": "lmb"}], "fast": "4M",
                 "machine": "a1200", "assign": {"Killer": "SYS:", "my dir": "x"},
                 "disks": ["a.adf", "b.adf"], "drives": 2,
                 "variant": [{"sha256": "ab" * 32, "file": "x.lha", "machine": "a500"}]}
        text = document.render("demozoo", 142, entry)
        self.assertEqual(tomllib.loads(text)["demozoo"]["142"], entry)

    def test_field_order(self):
        text = document.render("demozoo", 1, {"note": "n", "fast": "4M", "machine": "a1200",
                                              "source": "ai", "title": "T"})
        self.assertEqual(text, '[demozoo.1]\ntitle = "T"\nsource = "ai"\n'
                               'machine = "a1200"\nfast = "4M"\nnote = "n"')

    def test_split_keeps_comments_with_their_block(self):
        text = ('# about this file\n\n[demozoo.1]\ntitle = "A"  # why\n\n'
                '# watched on a real A500\n[csdb.2]\ntitle = "B"\n\n'
                '[[csdb.2.variant]]\nfile = "x"\n')
        preamble, blocks = document.split(text)
        self.assertEqual(preamble, "# about this file")
        self.assertEqual(blocks[("demozoo", 1)], '[demozoo.1]\ntitle = "A"  # why')
        self.assertEqual(blocks[("csdb", 2)], '# watched on a real A500\n[csdb.2]\n'
                         'title = "B"\n\n[[csdb.2.variant]]\nfile = "x"')
        self.assertEqual(document.join(preamble, blocks.values()), text)


class MergeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name)
        self.dir = self.data / "amiga"
        self.dir.mkdir()
        (self.dir / "machines.toml").write_text(MACHINES)

    def merge(self, *new):
        report = merge.merge(self.dir, new)
        self.assertEqual(validate.check(self.data), [])
        return report

    def test_new_entries_are_bucketed_and_sorted(self):
        r = self.merge(("demozoo", 9, script("Dream On")), ("demozoo", 3, script("9 Fingers")),
                       ("demozoo", 5, script("Desert Dream")), ("demozoo", 4, script("dream on")))
        self.assertEqual((r.added, r.files), (4, 2))
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.toml")),
                         ["0-9.toml", "d.toml", "machines.toml"])
        self.assertEqual(list(tomllib.loads((self.dir / "d.toml").read_text())["demozoo"]),
                         ["5", "4", "9"])

    def test_script_entry_is_replaced(self):
        self.merge(("demozoo", 5, script("Desert Dream")))
        r = self.merge(("demozoo", 5, script("Desert Dream", machine="a1200")))
        self.assertEqual((r.added, r.replaced, r.kept), (0, 1, 0))
        self.assertIn('machine = "a1200"', (self.dir / "d.toml").read_text())

    def test_same_result_writes_nothing(self):
        self.merge(("demozoo", 5, script("Desert Dream")))
        r = self.merge(("demozoo", 5, script("Desert Dream")))
        self.assertEqual((r.replaced, r.files), (0, 0))

    def test_edited_entry_is_kept_and_the_difference_reported(self):
        text = ('# checked on real hardware\n[demozoo.5]\ntitle = "Desert Dream"\n'
                'source = "verified"\nmachine = "a1200"  # needs AGA\n')
        (self.dir / "d.toml").write_text(text)
        r = self.merge(("demozoo", 5, script("Desert Dream", result="unknown")),
                       ("demozoo", 6, script("Dawn")))
        self.assertEqual((r.added, r.kept), (1, 1))
        self.assertEqual(r.disagreements, [
            "[demozoo.5] Desert Dream: machine: has 'a1200', sweep says None",
            "[demozoo.5] Desert Dream: result: has None, sweep says 'unknown'"])
        self.assertEqual((self.dir / "d.toml").read_text(),
                         '[demozoo.6]\ntitle = "Dawn"\nsource = "script"\n\n' + text)

    def test_agreeing_with_an_edited_entry_reports_nothing(self):
        (self.dir / "d.toml").write_text(
            '[demozoo.5]\ntitle = "Desert Dream"\nsource = "ai"\nnote = "watched"\n')
        self.assertEqual(self.merge(("demozoo", 5, script("Desert dream"))).disagreements, [])

    def test_retitled_entry_moves_file(self):
        self.merge(("demozoo", 5, script("Desert Dream")))
        r = self.merge(("demozoo", 5, script("The Desert Dream")))
        self.assertEqual(r.files, 2)
        self.assertFalse((self.dir / "d.toml").exists())
        self.assertTrue((self.dir / "t.toml").exists())


if __name__ == "__main__":
    unittest.main()
