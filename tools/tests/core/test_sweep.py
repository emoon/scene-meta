import pathlib
import tempfile
import unittest

from scenemeta.core import result, store, sweep
from scenemeta.core.catalog import Production
from scenemeta.core.errors import CannotPlay


def prod(id_):
    return Production(id_, f"demo {id_}", "group", ("p",), ("Demo",), "", [])


def job(p):
    """Leaves out production 2, fails on 3, lacks what a run needs on 4."""
    if p.id == 2:
        return None
    if p.id == 3:
        raise ValueError("no emulator")
    if p.id == 4:
        raise CannotPlay("no Kickstart ROM")
    return [], [result.Variant("floppy", ["a"], runs=[result.Run("m", 1, "works", 1)])]


class RunAll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.Store(pathlib.Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def stored(self):
        return self.db.db.execute(
            "select p.id, p.media_problems, v.best_verdict from production p"
            " left join variant v on v.prod_id = p.id order by p.id").fetchall()

    def test_stores_each_result_and_reports_a_failure(self):
        sweep.run_all([prod(1), prod(3)], self.db, job, jobs=1, log=lambda *a, **k: None)
        self.assertEqual(self.stored(), [
            (1, None, "works"), (3, "internal-error: ValueError: no emulator", None)])

    def test_a_job_that_lacks_what_a_run_needs_ends_the_sweep(self):
        # Not a result of production 4, and nothing is stored after it.
        with self.assertRaisesRegex(CannotPlay, "no Kickstart ROM"):
            sweep.run_all([prod(4), prod(1)], self.db, job, jobs=1,
                          log=lambda *a, **k: None)
        self.assertEqual(self.stored(), [])

    def test_a_production_the_job_leaves_out_keeps_what_is_stored(self):
        self.db.put_result(prod(2), [], job(prod(1))[1])
        self.db.db.execute("update variant set done_at = null")   # not finished: runs again
        sweep.run_all([prod(2)], self.db, job, jobs=1, log=lambda *a, **k: None)
        self.assertEqual(self.stored(), [(2, None, "works")])

    def test_again_runs_the_productions_held_finished_too(self):
        quiet = dict(jobs=1, log=lambda *a, **k: None)
        self.db.put_result(prod(1), ["old"], job(prod(1))[1])
        sweep.run_all([prod(1)], self.db, job, **quiet)
        self.assertEqual(self.stored(), [(1, "old", "works")])
        sweep.run_all([prod(1)], self.db, job, again=True, **quiet)
        self.assertEqual(self.stored(), [(1, None, "works")])


if __name__ == "__main__":
    unittest.main()
