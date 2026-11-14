"""Converts an Amiga sweep database from before the shared schema: frames
and sample counts become seconds, the columns only this platform has move
into ``detail``, and a swap's click (``+click`` in its trigger) becomes
its key."""

from ..core import migrate
from . import store
from .machines import FPS
from .sweep import SAMPLE_FRAMES

_BEFORE = """
drop view if exists best;
drop index if exists ix_run_variant;
alter table variant rename to legacy_variant;
alter table run rename to legacy_run;
alter table swap rename to legacy_swap;
"""

_AFTER = f"""
insert into variant (id, prod_id, idx, kind, disks, disk_count, note, detail,
                     best_run_id, best_machine, best_verdict, done_at)
    select id, prod_id, idx, kind, disks, disk_count, note,
           json_object('root', root, 'command', command, 'complete',
                       json(case when complete then 'true' else 'false' end)),
           best_run_id, best_machine, best_verdict, done_at
    from legacy_variant;
insert into run (id, variant_id, machine, budget, verdict, alive, crash,
                 crash_at, ended_at, wants_disk, drives, disks_reached, detail,
                 screenshot, at)
    select id, variant_id, machine, frames / {FPS}.0, verdict,
           alive * {SAMPLE_FRAMES} / {FPS}.0, crash, crash_frame / {FPS}.0,
           ended_frame / {FPS}.0, wants_disk, drives, disks_reached,
           json_object('returncode', returncode, 'events',
                       json(case when json_valid(events) then events else '[]' end)),
           screenshot, at
    from legacy_run;
insert into swap (run_id, seq, disk, at, trigger, accepted, key)
    select run_id, seq, disk, frame / {FPS}.0, trigger, 1,
           case when trigger like '%click%' then 'lmb' end
    from legacy_swap;
drop table legacy_variant;
drop table legacy_run;
drop table legacy_swap;
"""

# Columns the oldest files lack.
_COLUMNS = {"variant": ("complete integer",),
            "run": ("wants_disk integer", "drives integer",
                    "disks_reached integer", "returncode integer",
                    "events text")}


def run(path):
    """Convert the database at ``path``; False when there was nothing to do."""
    return migrate.migrate(path, _BEFORE, _AFTER, store.SCHEMA, _COLUMNS)
