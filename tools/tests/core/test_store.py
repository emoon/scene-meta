import pathlib
import tempfile
import unittest

from scenemeta.core import export, gatelog, store, sweep
from scenemeta.core.catalog import Production
from scenemeta.core.gate import Judgement
from scenemeta.core.result import Key, Run, Swap, Variant

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

    def test_the_drive_of_a_swap_is_kept(self):
        runs = [Run("m1", 180.0, "works", 60.0, drives=2, reached=3,
                    swaps=[Swap(3, 225.0, "poll", drive=2)])]
        self.db.put_result(PROD, [], [variant(("a", "b", "c"), runs)])
        (_, _, _, (v,)), = export.productions(self.db)
        self.assertEqual(v.swaps, [Swap(3, 225.0, "poll", drive=2)])

    def test_a_database_from_before_swaps_had_a_drive_is_read(self):
        self.db.put_result(PROD, [], [variant()])
        self.db.db.execute("alter table swap drop column drive")
        self.db.db.commit()
        self.db.close()
        self.db = store.Store(self.path)
        (_, _, _, (v,)), = export.productions(self.db)
        self.assertEqual(v.swaps, [Swap(2, 536.88, "poll", key="lmb")])

    def test_key_presses_with_no_swap_are_kept(self):
        runs = [Run("m1", 180.0, "works", 60.0, keys=[Key(86.1, "lmb")])]
        self.db.put_result(PROD, [], [variant(("a",), runs)])
        (_, _, _, (v,)), = export.productions(self.db)
        self.assertEqual(v.keys, [Key(86.1, "lmb")])

    def test_the_chosen_run_is_the_variants_best(self):
        runs = [Run("m1", 180.0, "crash", 0.0), Run("m2", 180.0, "works", 60.0)]
        self.db.put_result(PROD, [], [variant(("a",), runs, best=1)])
        self.assertEqual(self.db.db.execute(
            "select machine, verdict, swaps from best").fetchall(),
            [("m2", "works", None)])
        self.assertEqual(self.db.done_productions(), {7})

    def test_every_run_of_a_variant_and_which_one_was_chosen(self):
        runs = [Run("m1", 180.0, "crash", 0.0),
                Run("m2", 180.0, "works", 60.0, drives=2,
                    swaps=[Swap(2, 10.0, "poll")]),
                Run("m3", 180.0, "works-then-crash", 60.0)]
        self.db.put_result(PROD, [], [variant(("a", "b"), runs, best=1),
                                      variant(("c",))])
        (_, _, _, got), = export.productions(self.db, every=True)
        self.assertEqual(
            [(v.idx, v.machine, v.verdict, v.drives, v.chosen) for v in got],
            [(0, "m1", "crash", 1, False), (0, "m2", "works", 2, True),
             (0, "m3", "works-then-crash", 1, False), (1, "m1", "works", 1, True)])
        self.assertEqual([len(v.swaps) for v in got], [0, 1, 0, 1])
        (_, _, _, chosen), = export.productions(self.db)
        self.assertEqual(chosen, [got[1], got[3]])

    def test_a_new_result_replaces_the_old_one(self):
        self.db.put_result(PROD, [], [variant(), variant()])
        self.db.put_result(PROD, ["no-disk-images"], [])
        q = self.db.db.execute
        self.assertEqual([q(f"select count(*) from {t}").fetchone()[0]
                          for t in ("variant", "run", "swap")], [0, 0, 0])
        self.assertEqual(q("select media_problems from production").fetchall(),
                         [("no-disk-images",)])

    def gate(self, prod, *seeds, sha256="aa", player="1", entry=None):
        self.db.put_gate(prod, entry or {"title": "x"}, Judgement(
            all(p for _, p in seeds), "", seeds=tuple(
                (seed, Judgement(p, f"why {seed}")) for seed, p in seeds)),
            sha256, player)

    def test_the_gate_stores_one_record_per_entry_and_seed(self):
        self.gate(8, (1, True), (2, True))
        self.gate(7, (1, True), (2, False), (3, True))
        got = self.db.gated()
        self.assertEqual(
            [(r.prod, r.seed, r.passed, r.reason, r.sha256, r.player)
             for r in got],
            [(7, 1, True, "why 1", "aa", "1"), (7, 2, False, "why 2", "aa", "1"),
             (7, 3, True, "why 3", "aa", "1"), (8, 1, True, "why 1", "aa", "1"),
             (8, 2, True, "why 2", "aa", "1")])
        self.assertRegex(got[0].at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_gating_an_entry_again_replaces_its_records_only(self):
        self.gate(7, (1, True), (2, True), (3, True))
        self.gate(8, (1, True), (2, True))
        self.gate(7, (1, False), (2, True), sha256="bb", player="2")
        self.assertEqual(
            [(r.prod, r.seed, r.passed, r.sha256, r.player)
             for r in self.db.gated()],
            [(7, 1, False, "bb", "2"), (7, 2, True, "bb", "2"),
             (8, 1, True, "aa", "1"), (8, 2, True, "aa", "1")])

    def test_a_record_names_the_entry_it_is_of(self):
        entry = {"title": "x", "machine": "a1200"}
        self.gate(7, (1, True), (2, True), entry=entry)
        self.assertEqual({r.entry for r in self.db.gated()},
                         {gatelog.name(entry)})

    def test_a_log_from_before_records_named_their_entry_is_read(self):
        self.gate(7, (1, True))
        self.db.db.execute("alter table gate drop column entry")
        self.db.db.commit()
        self.db.close()
        self.db = store.Store(self.path)
        self.assertEqual([(r.prod, r.entry) for r in self.db.gated()],
                         [(7, None)])
        self.gate(8, (1, True))
        self.assertEqual(self.db.gated()[1].entry, gatelog.name({"title": "x"}))

    def test_why_an_entry_could_not_be_played_is_stored_beside_its_records(self):
        entry = {"title": "x", "machine": "a1200"}
        self.gate(7, (1, True))
        self.db.put_gate_error(7, entry, "no ROM")
        self.db.put_gate_error(7, entry, "no media")
        self.db.put_gate_error(5, entry, "no ROM")
        self.assertEqual(
            [(e.prod, e.reason, e.entry) for e in self.db.gate_errors()],
            [(5, "no ROM", gatelog.name(entry)),
             (7, "no media", gatelog.name(entry))])
        self.assertRegex(self.db.gate_errors()[0].at, r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(len(self.db.gated()), 1)

    def test_a_judgement_takes_the_place_of_the_entrys_error(self):
        self.db.put_gate_error(7, {"title": "x"}, "no ROM")
        self.db.put_gate_error(8, {"title": "x"}, "no ROM")
        self.gate(7, (1, False))
        self.assertEqual([e.prod for e in self.db.gate_errors()], [8])

    def test_the_gate_log_outlives_a_new_sweep_result(self):
        self.gate(7, (1, True), (2, True))
        self.db.put_result(PROD, [], [variant()])
        self.assertEqual(len(self.db.gated()), 2)

    def test_the_gate_log_is_kept_between_runs(self):
        self.gate(7, (1, True), (2, True))
        self.db.close()
        self.db = store.Store(self.path)
        self.assertEqual(len(self.db.gated()), 2)

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
