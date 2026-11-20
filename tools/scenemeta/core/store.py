"""The sweep's own log (sqlite), the same tables for every platform.

production  one row per Demozoo production in scope
variant     each bootable thing found for a production
run         one boot of one variant on one machine
swap        the disk changes a run made

All times are seconds of emulated time since power-on, as in the data
files (``run.at`` is the wall clock). The ``detail`` columns hold JSON that
only the platform reads. The view ``best`` gives each variant's chosen
machine and the swaps of its chosen run as ``at:disk:trigger``.

A platform adds its own tables by passing more schema.
"""

import dataclasses
import json
import sqlite3
import time

from .result import Key, Swap

VERSION = 1    # pragma user_version; 0 is a database from before this schema

SCHEMA = """
create table if not exists production (
    id integer primary key, title text, groups text, platforms text,
    types text, release_date text, media_problems text);
create table if not exists variant (
    id integer primary key, prod_id integer not null, idx integer not null,
    kind text not null, disks text, disk_count integer, note text,
    detail text,
    best_run_id integer, best_machine text, best_verdict text, done_at text,
    unique (prod_id, idx));
create table if not exists run (
    id integer primary key, variant_id integer not null, machine text not null,
    budget real, verdict text, alive real, crash text, crash_at real,
    ended_at real, wants_disk integer, drives integer, disks_reached integer,
    detail text, screenshot blob, at text);
create table if not exists swap (
    run_id integer not null, seq integer not null, disk integer, at real,
    trigger text, accepted integer, waiting_since real, key text, key_at real,
    screenshot blob, primary key (run_id, seq));
create index if not exists ix_run_variant on run(variant_id);
drop view if exists best;
create view best as
    select p.id prod_id, p.title, p.groups, p.platforms, v.idx variant,
           v.kind, v.disk_count, v.best_machine machine,
           v.best_verdict verdict, r.id run_id, r.drives, r.disks_reached,
           r.ended_at, r.wants_disk,
           (select group_concat(s.at || ':' || s.disk || ':' || s.trigger, ' ')
              from swap s where s.run_id = r.id and s.accepted) swaps
    from variant v join production p on p.id = v.prod_id
    left join run r on r.id = v.best_run_id;
"""


def _with_keys(r):
    """The run's detail; its key presses ride in it, as ``keys``."""
    return {**r.detail, "keys": [dataclasses.asdict(k) for k in r.keys]} \
        if r.keys else r.detail


class LegacyDatabase(Exception):
    """The file is a sweep database from before the shared schema."""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def is_legacy(db):
    """Does the connection hold tables of the schema before VERSION?"""
    return db.execute("pragma user_version").fetchone()[0] < VERSION and \
        db.execute("select count(*) from sqlite_master").fetchone()[0] > 0


class Store:
    def __init__(self, path, extra_schema=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=60)
        if is_legacy(self.db):
            self.db.close()
            raise LegacyDatabase(path)
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA + extra_schema)
        self.db.execute(f"pragma user_version = {VERSION}")

    def close(self):
        self.db.close()

    # -- results -------------------------------------------------------------
    def put_result(self, prod, problems, variants):
        """Store what a sweep found for one production: ``variants`` are
        result.Variant, in the order the media gave. Whatever was stored
        for the production before is replaced."""
        self.put_production(prod, problems)
        ids = self.put_variants(prod.id, variants)
        for vid, v in zip(ids, variants):
            run_ids = [self.put_run(vid, r) for r in v.runs]
            self.finish_variant(vid, run_ids[v.best], v.chosen.machine,
                                v.chosen.verdict)

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
                "insert into variant (prod_id, idx, kind, disks, disk_count,"
                " note, detail) values (?,?,?,?,?,?,?)",
                (prod_id, i, v.kind, json.dumps(v.disks), len(v.disks),
                 v.note or None, json.dumps(v.detail)))
            ids.append(cur.lastrowid)
        self.db.commit()
        return ids

    def done_productions(self):
        return {r[0] for r in self.db.execute(
            "select prod_id from variant group by prod_id "
            "having count(*) = count(done_at)")}

    def put_run(self, variant_id, r):
        """Store one result.Run. Returns its id."""
        cur = self.db.execute(
            "insert into run (variant_id, machine, budget, verdict, alive, crash,"
            " crash_at, ended_at, wants_disk, drives, disks_reached, detail,"
            " screenshot, at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (variant_id, r.machine, r.budget, r.verdict, r.alive, r.crash,
             r.crash_at, r.ended_at, int(r.wants_disk), r.drives, r.reached,
             json.dumps(_with_keys(r)), r.screenshot or None, _now()))
        rid = cur.lastrowid
        self.db.executemany(
            "insert into swap (run_id, seq, disk, at, trigger, accepted,"
            " waiting_since, key, key_at, screenshot) values (?,?,?,?,?,?,?,?,?,?)",
            [(rid, i, s.disk, s.at, s.trigger, int(s.accepted),
              s.waiting_since, s.key, s.key_at, s.screenshot or None)
             for i, s in enumerate(r.swaps)])
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

    # -- reading -------------------------------------------------------------
    def keys(self, run_id):
        """The result.Key presses of one run."""
        (detail,) = self.db.execute("select detail from run where id=?",
                                    (run_id,)).fetchone()
        return [Key(**k) for k in json.loads(detail or "{}").get("keys", [])]

    def swaps(self, run_id):
        """The result.Swap rows of one run, in order (screenshots left out)."""
        return [Swap(disk, at, trigger, bool(accepted), since, key, key_at)
                for disk, at, trigger, accepted, since, key, key_at
                in self.db.execute(
                    "select disk, at, trigger, accepted, waiting_since, key,"
                    " key_at from swap where run_id=? order by seq", (run_id,))]
