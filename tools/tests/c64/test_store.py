import pathlib
import tempfile
import unittest

from scenedb.c64 import store
from scenedb.c64.runner import Flip


def flip(disk, since, inserted, accepted=True, key=None, key_at=None):
    return Flip(disk, "idle", since, inserted, accepted, key=key, key_at=key_at)


class Windows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.Store(pathlib.Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def rows(self, view="schedule"):
        return self.db.db.execute(
            f"select disk, source, start, insert_at, key, key_delay from {view}"
            " order by disk").fetchall()

    def test_accepted_flips_become_sweep_windows(self):
        self.db.put_windows(1, 0, [flip(2, 100, 400, key="space", key_at=420),
                                   flip(3, 900, 1200, accepted=False)])
        self.assertEqual(self.rows(), [(2, "sweep", 100, 400, "space", 20)])

    def test_first_accepted_flip_to_a_disk_is_kept(self):
        self.db.put_windows(1, 0, [flip(2, 100, 400), flip(2, 500, 800)])
        self.assertEqual(self.rows(), [(2, "sweep", 100, 400, None, None)])

    def test_a_new_sweep_replaces_sweep_windows_only(self):
        self.db.db.execute("insert into flip_window (prod_id, variant, disk, source,"
                           " start, insert_at) values (1, 0, 2, 'manual', 7, 9)")
        self.db.put_windows(1, 0, [flip(2, 100, 400)])
        self.db.put_windows(1, 0, [flip(2, 150, 450)])
        sweep = self.db.db.execute("select start from flip_window "
                                   "where source='sweep'").fetchall()
        self.assertEqual(sweep, [(150,)])
        self.assertEqual(self.rows(), [(2, "manual", 7, 9, None, None)])

    def test_manual_window_hides_the_sweep_one_in_the_schedule(self):
        self.db.put_windows(1, 0, [flip(2, 100, 400)])
        self.db.db.execute("insert into flip_window (prod_id, variant, disk, source,"
                           " start, insert_at) values (1, 0, 2, 'manual', 7, 9)")
        self.assertEqual(self.rows(), [(2, "manual", 7, 9, None, None)])

    def test_rebuild_windows_reads_the_stored_best_run(self):
        q = self.db.db.execute
        q("insert into production (id, title) values (1, 'x')")
        q("insert into variant (id, prod_id, idx, kind, disk_count, best_run_id)"
          " values (1, 1, 0, 'k', 2, 5)")
        q("insert into flip (run_id, seq, disk, trigger, waiting_since, inserted,"
          " accepted, key, key_at) values (5, 0, 2, 'idle', 100, 400, 1, 'space', 420)")
        self.db.rebuild_windows()
        self.assertEqual(self.rows(), [(2, "sweep", 100, 400, "space", 20)])

    def test_shared_disk_names_make_a_collection(self):
        q = self.db.db.execute
        for pid in (1, 2, 3):
            q("insert into production (id, title) values (?, 'x')", (pid,))
            q("insert into run (id, variant_id, machine, disks_reached)"
              " values (?, ?, 'm', ?)", (pid, pid, 2 if pid == 3 else 1))
            names = "a.d64" if pid == 3 else "s1.d64"
            q("insert into variant (id, prod_id, idx, kind, disks, disk_count,"
              " best_run_id) values (?, ?, 0, 'k', ?, 2, ?)",
              (pid, pid, '["/p%d/%s", "/p%d/s2.d64"]' % (pid, names, pid), pid))
        self.db.classify_collections()
        got = dict(q("select prod_id, class from variant_status").fetchall())
        self.assertEqual(got, {1: "collection", 2: "collection", 3: "flips"})

    def test_manual_class_overrides_the_derived_one(self):
        q = self.db.db.execute
        q("insert into production (id, title) values (1, 'x')")
        q("insert into variant (id, prod_id, idx, kind, disk_count, best_run_id)"
          " values (1, 1, 0, 'k', 2, 1)")
        q("insert into run (id, variant_id, machine, disks_reached) values (1, 1, 'm', 1)")
        cls = lambda: q("select class from variant_status").fetchone()[0]
        self.assertEqual(cls(), "unresolved")
        q("insert into variant_class values (1, 0, 'standalone', 'manual', null)")
        self.assertEqual(cls(), "standalone")
        q("update run set disks_reached = 2")
        q("delete from variant_class")
        self.assertEqual(cls(), "flips")

    def test_manual_boot_target_is_loaded_and_replaced(self):
        q = self.db.db.execute
        boot = lambda: q("select boot_disk, boot_file from manual_boot").fetchall()
        self.db.put_manual([{"prod": 1, "class": "collection", "boot_disk": 1,
                             "boot_file": "bcf"}])
        self.assertEqual(boot(), [(1, "bcf")])
        self.db.put_manual([{"prod": 1, "class": "standalone"}])
        self.assertEqual(boot(), [])


if __name__ == "__main__":
    unittest.main()
