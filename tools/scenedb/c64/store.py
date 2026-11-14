"""The C64 sweep's log: the shared tables (core/store.py) and what was
observed by hand.

swap_window when a disk change should be made, per variant and disk; one row
            per source: ``sweep`` (from the best run's accepted swaps,
            rebuilt by every sweep) or ``manual`` (observed by hand, never
            touched)
variant_class what a variant needs: flips | standalone | boot_fresh | collection;
            ``manual`` rows are hand-made, ``auto`` rows come from
            ``classify_collections``
manual_boot where a hand-classified variant boots

The view ``schedule`` gives one window per variant and disk (manual first).
The view ``variant_status`` gives each variant's class (manual, auto, derived).

A variant's ``detail`` holds ``boot_disk`` and ``boot_file``; a run's holds
the tail of the emulator ``log`` and ``asked_disk``, when the screen first
asked for a disk. Times are seconds, as everywhere in the log; manual.json
gives them in C64 cycles and is converted when it is loaded.
"""

import json
import os

from ..core import store
from . import config, machines

SCHEMA = """
create table if not exists swap_window (
    prod_id integer not null, variant integer not null, disk integer not null,
    source text not null,
    start real,          -- the demo asks for the disk
    insert_at real,      -- an insert known to work
    "end" real,          -- last insert known to work; null: no limit seen
    key text, key_delay real,      -- key pressed this long after the insert
    pre_keys text,       -- json [[seconds, key], ...]: menu keys before the insert
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
drop view if exists schedule;
create view schedule as
    select w.* from swap_window w
    where w.source = 'manual'
       or not exists (select 1 from swap_window m where m.prod_id = w.prod_id
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


class Store(store.Store):
    def __init__(self, path=None):
        super().__init__(path or config.RESULTS_DB, SCHEMA)

    def put_result(self, prod, problems, variants):
        super().put_result(prod, problems, variants)
        for i, v in enumerate(variants):
            self.put_windows(prod.id, i, v.chosen.swaps)

    def put_windows(self, prod_id, variant, swaps):
        """Rebuild a variant's ``sweep`` windows from the accepted swaps
        (result.Swap) of its best run. The first accepted swap to each disk
        is the one recorded."""
        self.db.execute("delete from swap_window where prod_id=? and variant=?"
                        " and source='sweep'", (prod_id, variant))
        seen = set()
        for s in swaps:
            if not s.accepted or s.disk in seen:
                continue
            seen.add(s.disk)
            delay = s.key_at - s.at if s.key and s.key_at else None
            self.db.execute(
                "insert into swap_window (prod_id, variant, disk, source, start,"
                " insert_at, key, key_delay) values (?,?,?,'sweep',?,?,?,?)",
                (prod_id, variant, s.disk, s.waiting_since, s.at, s.key, delay))
        self.db.commit()

    def rebuild_windows(self):
        """Rebuild every variant's ``sweep`` windows from the stored best runs
        (for databases swept before windows were recorded)."""
        rows = self.db.execute(
            "select p.id, v.idx, v.best_run_id from variant v"
            " join production p on p.id = v.prod_id"
            " where v.best_run_id is not null").fetchall()
        for prod_id, idx, run_id in rows:
            self.put_windows(prod_id, idx, self.swaps(run_id))

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

    def _hz(self, prod_id, variant):
        """The clock of the machine chosen for a variant."""
        row = self.db.execute("select best_machine from variant where prod_id=?"
                              " and idx=?", (prod_id, variant)).fetchone()
        return machines.hz(row[0] if row else None)

    def put_manual(self, entries):
        """Load hand-observed windows and classes (see manual.json, whose
        times are cycles); rows from an earlier load of the same variant
        are replaced."""
        for e in entries:
            key = (e["prod"], e.get("variant", 0))
            hz = self._hz(*key)

            def seconds(cycles):
                return None if cycles is None else cycles / hz
            self.db.execute("delete from variant_class where prod_id=? and "
                            "variant=? and source='manual'", key)
            self.db.execute("delete from swap_window where prod_id=? and "
                            "variant=? and source='manual'", key)
            self.db.execute("delete from manual_boot where prod_id=? and variant=?", key)
            if "boot_disk" in e or "boot_file" in e:
                self.db.execute("insert into manual_boot values (?,?,?,?)",
                                (*key, e.get("boot_disk", 0), e.get("boot_file")))
            self.db.execute(
                "insert into variant_class values (?,?,?,'manual',?)",
                (*key, e["class"], e.get("note")))
            for w in e.get("windows", ()):
                pre_keys = [[seconds(at), k] for at, k in w.get("pre_keys") or ()]
                self.db.execute(
                    "insert into swap_window (prod_id, variant, disk, source, start,"
                    " insert_at, \"end\", key, key_delay, pre_keys, note)"
                    " values (?,?,?,'manual',?,?,?,?,?,?,?)",
                    (*key, w["disk"], seconds(w.get("start")),
                     seconds(w.get("insert_at")), seconds(w.get("end")),
                     w.get("key"), seconds(w.get("key_delay")),
                     json.dumps(pre_keys) if pre_keys else None,
                     w.get("note")))
        self.db.commit()
