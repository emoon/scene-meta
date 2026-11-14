"""Converts a C64 sweep database from before the shared schema: cycles
become seconds on the clock of the run's machine, ``flip`` rows become
``swap`` rows, and the columns only this platform has move into ``detail``."""

import json

from ..core import migrate
from . import machines, store

# The tables of hand observations as they were, for files that predate them.
_BEFORE = """
drop view if exists best;
drop view if exists schedule;
drop view if exists variant_status;
drop index if exists ix_run_variant;
create table if not exists flip_window (
    prod_id integer not null, variant integer not null, disk integer not null,
    source text not null, start integer, insert_at integer, "end" integer,
    key text, key_delay integer, pre_keys text, note text,
    primary key (prod_id, variant, disk, source));
alter table production rename to legacy_production;
alter table variant rename to legacy_variant;
alter table run rename to legacy_run;
alter table flip rename to legacy_flip;
alter table flip_window rename to legacy_flip_window;
"""

_AFTER = """
insert into production
    select id, title, groups, 'c64', types, release_date, media_problems
    from legacy_production;
insert into variant (id, prod_id, idx, kind, disks, disk_count, note, detail,
                     best_run_id, best_machine, best_verdict, done_at)
    select id, prod_id, idx, kind, disks, disk_count, note,
           json_object('boot_disk', coalesce(boot_disk, 0),
                       'boot_file', coalesce(boot_file, '')),
           best_run_id, best_machine, best_verdict, done_at
    from legacy_variant;
insert into run (id, variant_id, machine, budget, verdict, alive, crash,
                 crash_at, ended_at, wants_disk, drives, disks_reached, detail,
                 screenshot, at)
    select id, variant_id, machine, budget / hz(machine), verdict,
           alive / hz(machine), crash, crash_cycles / hz(machine),
           ended_cycles / hz(machine), wants_disk, 1, disks_reached,
           json_object('log', coalesce(detail, ''),
                       'asked_disk', asked_disk / hz(machine)),
           screenshot, at
    from legacy_run;
insert into swap (run_id, seq, disk, at, trigger, accepted, waiting_since, key,
                  key_at, screenshot)
    select f.run_id, f.seq, f.disk, f.inserted / hz(r.machine), f.trigger,
           f.accepted, f.waiting_since / hz(r.machine), f.key,
           f.key_at / hz(r.machine), f.screenshot
    from legacy_flip f left join legacy_run r on r.id = f.run_id;
-- A window is on the clock of the machine chosen for its variant.
insert into swap_window
    select prod_id, variant, disk, source, start / h, insert_at / h, "end" / h,
           key, key_delay / h, pre_keys_seconds(pre_keys, h), note
    from (select w.*, hz((select v.best_machine from legacy_variant v
                          where v.prod_id = w.prod_id and v.idx = w.variant)) h
          from legacy_flip_window w);
drop table legacy_production;
drop table legacy_variant;
drop table legacy_run;
drop table legacy_flip;
drop table legacy_flip_window;
"""

# Columns the older files lack.
_COLUMNS = {"variant": ("boot_disk integer", "boot_file text"),
            "run": ("asked_disk integer",),
            "flip": ("key text", "key_at integer"),
            "flip_window": ("pre_keys text",)}


def _hz(machine):
    return float(machines.hz(machine))


def _pre_keys_seconds(pre_keys, hz):
    """``[[cycles, key], ...]`` as JSON, in seconds."""
    if pre_keys is None:
        return None
    return json.dumps([[at / hz, key] for at, key in json.loads(pre_keys)])


def run(path):
    """Convert the database at ``path``; False when there was nothing to do."""
    return migrate.migrate(
        path, _BEFORE, _AFTER, store.SCHEMA, _COLUMNS,
        (("hz", 1, _hz), ("pre_keys_seconds", 2, _pre_keys_seconds)))
