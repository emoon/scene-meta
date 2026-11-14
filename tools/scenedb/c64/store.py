"""The results database (sqlite).

production  one row per Demozoo production in scope
variant     each bootable thing found for a production (a disk set)
run         one boot of one variant on one ladder machine
flip        the disk changes a run made, for auto-flipping
flip_window when a disk change should be made, per variant and disk; one row
            per source: ``sweep`` (from the best run's accepted flips, rebuilt
            by every sweep) or ``manual`` (observed by hand, never touched)
variant_class what a variant needs: flips | standalone | boot_fresh | collection;
            ``manual`` rows are hand-made, ``auto`` rows come from
            ``classify_collections``

The view ``best`` gives each variant's chosen machine and its flip schedule.
The view ``schedule`` gives one window per variant and disk (manual first).
The view ``variant_status`` gives each variant's class (manual, auto, derived).
Times are exact C64 cycles since power-on (``stopwatch``); the PAL clock is
985248 Hz, NTSC 1022727 Hz.
"""

import json
import os
import sqlite3
import time

from . import config

SCHEMA = """
create table if not exists production (
    id integer primary key, title text, groups text, types text,
    release_date text, media_problems text);
create table if not exists variant (
    id integer primary key, prod_id integer not null, idx integer not null,
    kind text not null, disks text, disk_count integer, note text,
    best_run_id integer, best_machine text, best_verdict text, done_at text,
    boot_disk integer, boot_file text,
    unique (prod_id, idx));
create table if not exists run (
    id integer primary key, variant_id integer not null, machine text not null,
    budget integer, verdict text, alive integer, crash text,
    crash_cycles integer, ended_cycles integer, wants_disk integer,
    disks_reached integer, detail text, screenshot blob, at text);
create table if not exists flip (
    run_id integer not null, seq integer not null, disk integer,
    trigger text, waiting_since integer, inserted integer, accepted integer,
    screenshot blob, primary key (run_id, seq));
create table if not exists flip_window (
    prod_id integer not null, variant integer not null, disk integer not null,
    source text not null,
    start integer,       -- cycles: the demo asks for the disk
    insert_at integer,   -- cycles: an insert known to work
    "end" integer,       -- cycles: last insert known to work; null: no limit seen
    key text, key_delay integer,   -- key pressed this long after the insert
    pre_keys text,       -- json [[cycles, key], ...]: menu keys before the insert
    note text,
    primary key (prod_id, variant, disk, source));
create table if not exists variant_class (
    prod_id integer not null, variant integer not null, class text not null,
    source text not null, note text,
    primary key (prod_id, variant, source));
create table if not exists manual_boot (   -- where a hand-classified variant boots
    prod_id integer not null, variant integer not null,
    boot_disk integer not null,   -- index into the variant's disks, 0 = first
    boot_file text,               -- directory entry; null = autostart the first file
    primary key (prod_id, variant));
create index if not exists ix_run_variant on run(variant_id);
drop view if exists best;
create view best as
    select p.id prod_id, p.title, p.groups, v.idx variant, v.kind,
           v.disk_count, v.best_machine machine, v.best_verdict verdict,
           r.id run_id, r.disks_reached, r.ended_cycles, r.wants_disk,
           (select group_concat(f.disk || ':' || f.waiting_since || ':' ||
                                f.trigger, ' ')
              from flip f where f.run_id = r.id and f.accepted) flips
    from variant v join production p on p.id = v.prod_id
    left join run r on r.id = v.best_run_id;
drop view if exists schedule;
create view schedule as
    select w.* from flip_window w
    where w.source = 'manual'
       or not exists (select 1 from flip_window m where m.prod_id = w.prod_id
                      and m.variant = w.variant and m.disk = w.disk
                      and m.source = 'manual');
drop view if exists variant_status;
create view variant_status as
    select b.prod_id, b.variant, b.title, b.disk_count, b.disks_reached,
           coalesce((select c.class from variant_class c
                     where c.prod_id = b.prod_id and c.variant = b.variant
                     order by c.source = 'manual' desc limit 1),
                    case when b.disk_count = 1 then 'single'
                         when b.disks_reached >= b.disk_count then 'flips'
                         else 'unresolved' end) class
    from best b;
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
        if "key" not in {r[1] for r in self.db.execute("pragma table_info(flip)")}:
            self.db.execute("alter table flip add column key text")
        if "pre_keys" not in {r[1] for r in
                              self.db.execute("pragma table_info(flip_window)")}:
            self.db.execute("alter table flip_window add column pre_keys text")
        if "boot_file" not in {r[1] for r in self.db.execute("pragma table_info(variant)")}:
            self.db.execute("alter table variant add column boot_disk integer")
            self.db.execute("alter table variant add column boot_file text")
        if "asked_disk" not in {r[1] for r in self.db.execute("pragma table_info(run)")}:
            self.db.execute("alter table run add column asked_disk integer")
        if "key_at" not in {r[1] for r in self.db.execute("pragma table_info(flip)")}:
            self.db.execute("alter table flip add column key_at integer")

    def close(self):
        self.db.close()

    # -- catalog -------------------------------------------------------------
    def put_production(self, prod, problems=()):
        self.db.execute(
            "insert or replace into production values (?,?,?,?,?,?)",
            (prod.id, prod.title, prod.groups, ",".join(prod.types),
             prod.release_date, "; ".join(problems) or None))
        self.db.commit()

    def put_variants(self, prod_id, variants):
        """Replace a production's variants (and their runs). Returns ids."""
        for (vid,) in self.db.execute(
                "select id from variant where prod_id=?", (prod_id,)).fetchall():
            self._delete_runs(vid)
        self.db.execute("delete from variant where prod_id=?", (prod_id,))
        ids = []
        for i, v in enumerate(variants):
            cur = self.db.execute(
                "insert into variant (prod_id, idx, kind, disks, disk_count, note,"
                " boot_disk, boot_file) values (?,?,?,?,?,?,?,?)",
                (prod_id, i, v.kind, json.dumps(v.disks), len(v.disks),
                 v.note or None, v.boot_disk, v.boot_file or None))
            ids.append(cur.lastrowid)
        self.db.commit()
        return ids

    def done_productions(self):
        return {r[0] for r in self.db.execute(
            "select prod_id from variant group by prod_id "
            "having count(*) = count(done_at)")}

    # -- runs ----------------------------------------------------------------
    def put_run(self, variant_id, a):
        """Store one sweep.Attempt."""
        v, log = a.verdict, a.log
        cur = self.db.execute(
            "insert into run (variant_id, machine, budget, verdict, alive, crash,"
            " crash_cycles, ended_cycles, wants_disk, disks_reached, detail,"
            " screenshot, at, asked_disk) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (variant_id, a.machine, a.budget, v.verdict, v.alive, v.crash,
             v.crash_cycles, v.ended_cycles, int(v.wants_disk), a.reached,
             log.detail or None, log.last_shot or None, _now(), log.asked_disk))
        rid = cur.lastrowid
        self.db.executemany(
            "insert into flip (run_id, seq, disk, trigger, waiting_since, inserted,"
            " accepted, screenshot, key, key_at) values (?,?,?,?,?,?,?,?,?,?)",
            [(rid, i, f.disk, f.trigger, f.waiting_since, f.inserted,
              int(f.accepted), f.shot or None, f.key, f.key_at)
             for i, f in enumerate(log.flips)])
        self.db.commit()
        return rid

    def put_windows(self, prod_id, variant, flips):
        """Rebuild a variant's ``sweep`` windows from the accepted flips of its
        best run. The first accepted flip to each disk is the one recorded."""
        self.db.execute("delete from flip_window where prod_id=? and variant=?"
                        " and source='sweep'", (prod_id, variant))
        seen = set()
        for f in flips:
            if not f.accepted or f.disk in seen:
                continue
            seen.add(f.disk)
            delay = f.key_at - f.inserted if f.key and f.key_at else None
            self.db.execute(
                "insert into flip_window (prod_id, variant, disk, source, start,"
                " insert_at, key, key_delay) values (?,?,?,'sweep',?,?,?,?)",
                (prod_id, variant, f.disk, f.waiting_since, f.inserted,
                 f.key, delay))
        self.db.commit()

    def rebuild_windows(self):
        """Rebuild every variant's ``sweep`` windows from the stored best runs
        (for databases swept before windows were recorded)."""
        from .runner import Flip
        rows = self.db.execute(
            "select p.id, v.idx, v.best_run_id from variant v"
            " join production p on p.id = v.prod_id"
            " where v.best_run_id is not null").fetchall()
        for prod_id, idx, run_id in rows:
            flips = [Flip(d, trig, since, ins, bool(acc), key=key, key_at=key_at)
                     for d, trig, since, ins, acc, key, key_at in self.db.execute(
                         "select disk, trigger, waiting_since, inserted, accepted,"
                         " key, key_at from flip where run_id=? order by seq",
                         (run_id,))]
            self.put_windows(prod_id, idx, flips)

    def classify_collections(self):
        """Mark the variants that did not reach all their disks and whose disk
        file names are shared with another production: a party or compilation
        set where the production is one file among many, not a flip chain."""
        rows = self.db.execute(
            "select b.prod_id, b.variant, v.disks from best b"
            " join variant v on v.prod_id = b.prod_id and v.idx = b.variant"
            " where b.disk_count > 1").fetchall()
        sets = {}
        for prod_id, idx, disks in rows:
            names = tuple(sorted(os.path.basename(d).lower()
                                 for d in json.loads(disks)))
            sets.setdefault(names, []).append((prod_id, idx))
        self.db.execute("delete from variant_class where source='auto'")
        short = {(r[0], r[1]) for r in self.db.execute(
            "select prod_id, variant from best where disks_reached < disk_count")}
        for members in sets.values():
            if len({m[0] for m in members}) < 2:
                continue
            for prod_id, idx in members:
                if (prod_id, idx) in short:
                    self.db.execute(
                        "insert or ignore into variant_class values"
                        " (?,?,'collection','auto',?)",
                        (prod_id, idx, f"disk set shared by {len(members)} productions"))
        self.db.commit()

    def put_manual(self, entries):
        """Load hand-observed windows and classes (see manual.json); rows from
        an earlier load of the same variant are replaced."""
        for e in entries:
            key = (e["prod"], e.get("variant", 0))
            self.db.execute("delete from variant_class where prod_id=? and "
                            "variant=? and source='manual'", key)
            self.db.execute("delete from flip_window where prod_id=? and "
                            "variant=? and source='manual'", key)
            self.db.execute("delete from manual_boot where prod_id=? and variant=?", key)
            if "boot_disk" in e or "boot_file" in e:
                self.db.execute("insert into manual_boot values (?,?,?,?)",
                                (*key, e.get("boot_disk", 0), e.get("boot_file")))
            self.db.execute(
                "insert into variant_class values (?,?,?,'manual',?)",
                (*key, e["class"], e.get("note")))
            for w in e.get("windows", ()):
                self.db.execute(
                    "insert into flip_window (prod_id, variant, disk, source, start,"
                    " insert_at, \"end\", key, key_delay, pre_keys, note)"
                    " values (?,?,?,'manual',?,?,?,?,?,?,?)",
                    (*key, w["disk"], w.get("start"), w.get("insert_at"),
                     w.get("end"), w.get("key"), w.get("key_delay"),
                     json.dumps(w["pre_keys"]) if w.get("pre_keys") else None,
                     w.get("note")))
        self.db.commit()

    def finish_variant(self, variant_id, run_id, machine, verdict):
        self.db.execute("update variant set best_run_id=?, best_machine=?,"
                        " best_verdict=?, done_at=? where id=?",
                        (run_id, machine, verdict, _now(), variant_id))
        self.db.commit()

    def _delete_runs(self, variant_id):
        self.db.execute("delete from flip where run_id in "
                        "(select id from run where variant_id=?)", (variant_id,))
        self.db.execute("delete from run where variant_id=?", (variant_id,))
