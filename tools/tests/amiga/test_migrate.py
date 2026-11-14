import pathlib
import sqlite3
import tempfile
import unittest

from scenemeta.amiga import migrate, store
from scenemeta.core import export
from scenemeta.core.result import Swap

# The Amiga sweep database as it was before the shared schema.
LEGACY = """
create table production (
    id integer primary key, title text, groups text, platforms text,
    types text, release_date text, media_problems text);
create table variant (
    id integer primary key, prod_id integer not null, idx integer not null,
    kind text not null, disks text, root text, command text,
    disk_count integer, complete integer, note text,
    best_run_id integer, best_machine text, best_verdict text, done_at text,
    unique (prod_id, idx));
create table run (
    id integer primary key, variant_id integer not null, machine text not null,
    frames integer, verdict text, alive integer, crash text,
    crash_frame integer, ended_frame integer, wants_disk integer,
    drives integer, disks_reached integer,
    returncode integer, events text, screenshot blob, at text);
create table swap (
    run_id integer not null, seq integer not null, frame integer,
    disk integer, trigger text, primary key (run_id, seq));
create table fetch (
    prod_id integer, name text, url text, status text, detail text, at text,
    primary key (prod_id, name));
create index ix_run_variant on run(variant_id);
create view best as select p.id prod_id from variant v
    join production p on p.id = v.prod_id;
insert into production values (142, 'Desert Dream', 'Kefrens', 'ocs', 'Demo', '1993', null);
insert into variant values (1, 142, 0, 'floppy', '["A.adf", "B.adf"]', null, null,
                            2, 1, null, 5, 'a500', 'works-then-crash', 'now');
insert into variant values (2, 142, 1, 'hd', '[]', '/work/hd', '"demo"
', 0, 1, 'a note', 6, 'a1200', 'works', 'now');
insert into run values (5, 1, 'a500', 72000, 'works-then-crash', 9, 'halt', 30000,
                        null, 0, 1, 2, 0, '[{"event": "halt"}]', x'89', 'then');
insert into run values (6, 2, 'a1200', 9000, 'works', 8, null, null, 4500, 0, 1,
                        0, 2, '[]', null, 'then');
insert into swap values (5, 0, 26844, 2, 'poll+click');
insert into swap values (5, 1, 40000, 3, 'idle');
insert into fetch values (142, 'B.adf', 'http://x', 'ok', '1 bytes', 'then');
"""


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "scene.db"
        db = sqlite3.connect(self.path)
        db.executescript(LEGACY)
        db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_frames_become_seconds_and_own_columns_detail(self):
        self.assertTrue(migrate.run(self.path))
        db = store.Store(self.path)
        q = db.db.execute
        self.assertEqual(q(
            "select budget, alive, crash_at, ended_at, detail, screenshot"
            " from run order by id").fetchall(), [
            (1440.0, 45.0, 600.0, None,
             '{"returncode":0,"events":[{"event":"halt"}]}', b"\x89"),
            (180.0, 40.0, None, 90.0, '{"returncode":2,"events":[]}', None)])
        floppy, hd = export.variants(db)[142]
        self.assertEqual(floppy.swaps, [Swap(2, 536.88, "poll+click", key="lmb"),
                                        Swap(3, 800.0, "idle")])
        self.assertEqual((floppy.machine, floppy.verdict, floppy.reached),
                         ("a500", "works-then-crash", 2))
        self.assertEqual(hd.detail, {"root": "/work/hd", "command": '"demo"\n',
                                     "complete": True})
        self.assertEqual(db.fetched(), {(142, "B.adf")})
        db.close()

    def test_a_converted_file_is_left_alone(self):
        migrate.run(self.path)
        self.assertFalse(migrate.run(self.path))

    def test_a_failed_conversion_changes_nothing(self):
        db = sqlite3.connect(self.path)
        db.execute("drop table swap")
        before = db.execute("select sql from sqlite_master order by name").fetchall()
        db.close()
        with self.assertRaises(sqlite3.Error):
            migrate.run(self.path)
        db = sqlite3.connect(self.path)
        self.assertEqual(db.execute(
            "select sql from sqlite_master order by name").fetchall(), before)
        self.assertEqual(db.execute("select frames from run").fetchall(),
                         [(72000,), (9000,)])
        db.close()


if __name__ == "__main__":
    unittest.main()
