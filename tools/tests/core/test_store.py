import pathlib
import tempfile
import unittest

from scenemeta.core import export, store, sweep
from scenemeta.core.catalog import Production
from scenemeta.core.result import Run, Swap, Variant

PROD = Production(7, "Demo", "Group", ("ocs",), ("Demo",), "1991", [])


def variant(disks=("a", "b"), runs=None, best=0):
    runs = runs or [Run("m1", 180.0, "works", 60.0, reached=len(disks),
                        swaps=[Swap(2, 536.88, "poll", key="lmb"),
                               Swap(2, 600.0, "idle", accepted=False)])]
    return Variant("floppy", list(disks), "a note", {"own": 1}, runs, best)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "t.db"
        self.db = store.Store(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_what_is_stored_is_what_the_export_reads(self):
        self.db.put_result(PROD, [], [variant()])
        (prod, title, groups, (v,)), = export.productions(self.db)
        self.assertEqual((prod, title, groups), (7, "Demo", "Group"))
        self.assertEqual((v.idx, v.kind, v.disks, v.note, v.detail),
                         (0, "floppy", ["a", "b"], "a note", {"own": 1}))
        self.assertEqual((v.machine, v.verdict, v.drives, v.reached),
                         ("m1", "works", 1, 2))
        # Only the swaps the production took.
        self.assertEqual(v.swaps, [Swap(2, 536.88, "poll", key="lmb")])

    def test_the_chosen_run_is_the_variants_best(self):
        runs = [Run("m1", 180.0, "crash", 0.0), Run("m2", 180.0, "works", 60.0)]
        self.db.put_result(PROD, [], [variant(("a",), runs, best=1)])
        self.assertEqual(self.db.db.execute(
            "select machine, verdict, swaps from best").fetchall(),
            [("m2", "works", None)])
        self.assertEqual(self.db.done_productions(), {7})

    def test_a_new_result_replaces_the_old_one(self):
        self.db.put_result(PROD, [], [variant(), variant()])
        self.db.put_result(PROD, ["no-disk-images"], [])
        q = self.db.db.execute
        self.assertEqual([q(f"select count(*) from {t}").fetchone()[0]
                          for t in ("variant", "run", "swap")], [0, 0, 0])
        self.assertEqual(q("select media_problems from production").fetchall(),
                         [("no-disk-images",)])

    def test_a_file_from_before_the_schema_is_refused(self):
        self.db.db.execute("pragma user_version = 0")
        self.db.close()
        with self.assertRaises(store.LegacyDatabase):
            store.Store(self.path)
        self.db = store.Store(pathlib.Path(self.tmp.name) / "new.db")


def _job(prod):
    if prod.id == 2:
        raise ValueError("boom")
    return ["odd name"], [variant()]


class SweepTest(unittest.TestCase):
    def test_summary(self):
        two_drives = Run("m2", 1.0, "works", 1.0, drives=2, reached=1)
        self.assertEqual(
            sweep.summary([variant(), variant(("a",), [two_drives])]),
            "m1:works 2/2 disks, m2:works 2 drives")

    def test_results_are_stored_and_productions_with_variants_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = store.Store(pathlib.Path(tmp) / "t.db")
            prods = [Production(i, f"P{i}", "", (), (), "", []) for i in (1, 2)]
            lines = []
            log = lambda *a, **kw: lines.append(a[0])
            sweep.run_all(prods, db, _job, jobs=1, log=log)
            self.assertEqual(db.done_productions(), {1})
            self.assertEqual(dict(db.db.execute(
                "select id, media_problems from production")),
                {1: "odd name", 2: "internal-error: ValueError: boom"})
            self.assertTrue(any("P1 -> m1:works 2/2 disks" in s for s in lines))
            del lines[:]
            sweep.run_all(prods, db, _job, jobs=1, log=log)
            self.assertIn("1 productions to run (1 done)", lines[0])
            db.close()


if __name__ == "__main__":
    unittest.main()
