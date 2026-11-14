import pathlib
import sqlite3
import tempfile
import unittest

from scenedb.c64 import migrate, store
from scenedb.c64.machines import NTSC_HZ, PAL_HZ
from scenedb.core.result import Swap

# An early C64 sweep database: no hand-observation tables, no key_at, no
# boot file, no asked_disk.
EARLY = f"""
create table production (
    id integer primary key, title text, groups text, types text,
    release_date text, media_problems text);
create table variant (
    id integer primary key, prod_id integer not null, idx integer not null,
    kind text not null, disks text, disk_count integer, note text,
    best_run_id integer, best_machine text, best_verdict text, done_at text,
    unique (prod_id, idx));
create table run (
    id integer primary key, variant_id integer not null, machine text not null,
    budget integer, verdict text, alive integer, crash text,
    crash_cycles integer, ended_cycles integer, wants_disk integer,
    disks_reached integer, detail text, screenshot blob, at text);
create index ix_run_variant on run(variant_id);
create table flip (
    run_id integer not null, seq integer not null, disk integer,
    trigger text, waiting_since integer, inserted integer, accepted integer,
    screenshot blob, key text, primary key (run_id, seq));
create view best as select p.id prod_id from variant v
    join production p on p.id = v.prod_id;
insert into production values (9, 'Mojo', 'Bonzai', 'Demo', '2018', null);
insert into variant values (1, 9, 0, 'floppy', '["1.d64", "2.d64"]', 2, null,
                            4, 'ntsc_1541', 'works', 'now');
insert into run values (3, 1, 'pal_1541', {PAL_HZ * 180}, 'crash', 0, 'jam',
                        {PAL_HZ * 7}, null, 0, 1, 'tail', null, 'then');
insert into run values (4, 1, 'ntsc_1541', {NTSC_HZ * 180}, 'works',
                        {NTSC_HZ * 60}, null, null, null, 0, 2, null, null, 'then');
insert into flip values (4, 0, 2, 'poll', {NTSC_HZ * 100}, {NTSC_HZ * 120}, 1,
                         x'89', 'space');
"""

# What later files added.
LATER = f"""
alter table variant add column boot_disk integer;
alter table variant add column boot_file text;
alter table run add column asked_disk integer;
alter table flip add column key_at integer;
create table flip_window (
    prod_id integer not null, variant integer not null, disk integer not null,
    source text not null, start integer, insert_at integer, "end" integer,
    key text, key_delay integer, pre_keys text, note text,
    primary key (prod_id, variant, disk, source));
create table variant_class (
    prod_id integer not null, variant integer not null, class text not null,
    source text not null, note text, primary key (prod_id, variant, source));
create table manual_boot (
    prod_id integer not null, variant integer not null,
    boot_disk integer not null, boot_file text, primary key (prod_id, variant));
update variant set boot_disk = 1, boot_file = 'mojo';
update run set asked_disk = {NTSC_HZ * 90} where id = 4;
update flip set key_at = {NTSC_HZ * 125};
insert into flip_window values (9, 0, 2, 'manual', {NTSC_HZ * 100},
    {NTSC_HZ * 120}, null, 'space', {NTSC_HZ * 5}, '[[{NTSC_HZ * 3}, "space"]]', 'seen');
insert into flip_window values (8, 0, 2, 'manual', {PAL_HZ * 10}, null, null,
    null, null, null, 'no variant: PAL');
insert into variant_class values (9, 0, 'flips', 'manual', null);
"""


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "scene.db"

    def tearDown(self):
        self.tmp.cleanup()

    def legacy(self, script):
        db = sqlite3.connect(self.path)
        db.executescript(script)
        db.close()

    def test_an_early_file(self):
        self.legacy(EARLY)
        self.assertTrue(migrate.run(self.path))
        db = store.Store(self.path)
        q = db.db.execute
        self.assertEqual(q("select platforms from production").fetchall(), [("c64",)])
        self.assertEqual(q("select detail from variant").fetchall(),
                         [('{"boot_disk":0,"boot_file":""}',)])
        # Each run on its own machine's clock.
        self.assertEqual(q(
            "select budget, alive, crash_at, drives, detail from run order by id"
        ).fetchall(), [(180.0, 0.0, 7.0, 1, '{"log":"tail","asked_disk":null}'),
                       (180.0, 60.0, None, 1, '{"log":"","asked_disk":null}')])
        self.assertEqual(db.swaps(4), [Swap(2, 120.0, "poll", True, 100.0, "space")])
        self.assertEqual(q("select screenshot from swap").fetchall(), [(b"\x89",)])
        self.assertEqual(q("select prod_id, class from variant_status").fetchall(),
                         [(9, "flips")])
        db.close()

    def test_a_late_file_with_hand_observations(self):
        self.legacy(EARLY + LATER)
        self.assertTrue(migrate.run(self.path))
        self.assertFalse(migrate.run(self.path))
        db = store.Store(self.path)
        q = db.db.execute
        self.assertEqual(q("select detail from variant").fetchall(),
                         [('{"boot_disk":1,"boot_file":"mojo"}',)])
        self.assertEqual(q("select detail from run where id = 4").fetchall(),
                         [('{"log":"","asked_disk":90.0}',)])
        self.assertEqual(db.swaps(4),
                         [Swap(2, 120.0, "poll", True, 100.0, "space", 125.0)])
        self.assertEqual(q(
            "select prod_id, start, insert_at, key_delay, pre_keys, note"
            " from schedule order by prod_id").fetchall(), [
            (8, 10.0, None, None, None, "no variant: PAL"),
            (9, 100.0, 120.0, 5.0, '[[3.0, "space"]]', "seen")])
        self.assertEqual(q("select class from variant_class").fetchall(), [("flips",)])
        db.close()


if __name__ == "__main__":
    unittest.main()
