"""The results database (sqlite).

production  one row per Demozoo production in scope
variant     each bootable thing found for a production (disk set or hd exe)
run         one boot of one variant on one ladder machine
swap        the disk changes a run made (frame + disk), for auto-switching
fetch       downloads of missing disks into the NAS mirror

The view ``best`` gives each variant's chosen machine and its swap schedule.
"""

import json
import sqlite3
import time

from . import config

SCHEMA = """
create table if not exists production (
    id integer primary key, title text, groups text, platforms text,
    types text, release_date text, media_problems text);
create table if not exists variant (
    id integer primary key, prod_id integer not null, idx integer not null,
    kind text not null, disks text, root text, command text,
    disk_count integer, complete integer, note text,
    best_run_id integer, best_machine text, best_verdict text, done_at text,
    unique (prod_id, idx));
create table if not exists run (
    id integer primary key, variant_id integer not null, machine text not null,
    frames integer, verdict text, alive integer, crash text,
    crash_frame integer, ended_frame integer, wants_disk integer,
    drives integer, disks_reached integer,
    returncode integer, events text, screenshot blob, at text);
create table if not exists swap (
    run_id integer not null, seq integer not null, frame integer,
    disk integer, trigger text, primary key (run_id, seq));
create table if not exists fetch (
    prod_id integer, name text, url text, status text, detail text, at text,
    primary key (prod_id, name));
create index if not exists ix_run_variant on run(variant_id);
drop view if exists best;
create view best as
    select p.id prod_id, p.title, p.groups, p.platforms, v.idx variant,
           v.kind, v.disk_count, v.complete, v.best_machine machine,
           v.best_verdict verdict, r.id run_id, r.drives, r.disks_reached,
           r.ended_frame,
           (select group_concat(s.frame || ':' || s.disk || ':' || s.trigger, ' ')
              from swap s where s.run_id = r.id) swaps
    from variant v join production p on p.id = v.prod_id
    left join run r on r.id = v.best_run_id;
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Store:
    def __init__(self, path=None):
        path = path or config.RESULTS_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=60)
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # -- catalog -------------------------------------------------------------
    def put_production(self, prod, problems=()):
        self.db.execute(
            "insert or replace into production values (?,?,?,?,?,?,?)",
            (prod.id, prod.title, prod.groups, ",".join(prod.platforms),
             ",".join(prod.types), prod.release_date,
             "; ".join(problems) or None))
        self.db.commit()

    def put_variants(self, prod_id, variants):
        """Replace a production's variants (and their runs). Returns ids."""
        old = [r[0] for r in self.db.execute(
            "select id from variant where prod_id=?", (prod_id,))]
        for vid in old:
            self._delete_runs(vid)
        self.db.execute("delete from variant where prod_id=?", (prod_id,))
        ids = []
        for i, v in enumerate(variants):
            cur = self.db.execute(
                "insert into variant (prod_id, idx, kind, disks, root, command,"
                " disk_count, complete, note) values (?,?,?,?,?,?,?,?,?)",
                (prod_id, i, v.kind, json.dumps(v.disks), v.root, v.command,
                 len(v.disks), int(v.complete), v.note or None))
            ids.append(cur.lastrowid)
        self.db.commit()
        return ids

    def variant_done(self, variant_id):
        r = self.db.execute("select done_at from variant where id=?",
                            (variant_id,)).fetchone()
        return bool(r and r[0])

    def done_productions(self):
        return {r[0] for r in self.db.execute(
            "select prod_id from variant group by prod_id "
            "having count(*) = count(done_at)")}

    # -- runs ----------------------------------------------------------------
    def put_run(self, variant_id, a):
        """Store one sweep.Attempt."""
        v, log = a.verdict, a.log
        cur = self.db.execute(
            "insert into run (variant_id, machine, frames, verdict, alive, crash,"
            " crash_frame, ended_frame, wants_disk, drives, disks_reached,"
            " returncode, events, screenshot, at)"
            " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (variant_id, a.machine, a.frames, v.verdict, v.alive, v.crash,
             v.crash_frame, v.ended_frame, int(v.wants_disk), a.drives,
             a.reached, log.returncode, json.dumps(log.events),
             log.last_shot or None, _now()))
        rid = cur.lastrowid
        self.db.executemany("insert into swap values (?,?,?,?,?)",
                            [(rid, i, f, d, t)
                             for i, (f, d, t) in enumerate(a.swaps)])
        self.db.commit()
        return rid

    def finish_variant(self, variant_id, run_id, machine, verdict):
        self.db.execute("update variant set best_run_id=?, best_machine=?,"
                        " best_verdict=?, done_at=? where id=?",
                        (run_id, machine, verdict, _now(), variant_id))
        self.db.commit()

    def _delete_runs(self, variant_id):
        self.db.execute("delete from swap where run_id in "
                        "(select id from run where variant_id=?)", (variant_id,))
        self.db.execute("delete from run where variant_id=?", (variant_id,))

    # -- fetch ---------------------------------------------------------------
    def fetched(self):
        return {(r[0], r[1]) for r in self.db.execute(
            "select prod_id, name from fetch where status = 'ok'")}

    def record_fetch(self, prod_id, name, url, status, detail):
        self.db.execute("insert or replace into fetch values (?,?,?,?,?,?)",
                        (prod_id, name, url, status, detail, _now()))
        self.db.commit()
