"""The Amiga sweep's log: the shared tables (core/store.py) and

fetch       downloads of missing disks into the NAS mirror

A variant's ``detail`` holds ``root`` and ``command`` (the directory and
startup-sequence of a hard-drive boot), ``complete`` (the disk set's
numbers run without a gap) and ``run`` and ``choice`` (the file it starts
and whether an entry names it, see media.Variant). A run's holds the
emulator's ``returncode`` and its ``events``.
"""

from ..core import store
from . import config

SCHEMA = """
create table if not exists fetch (
    prod_id integer, name text, url text, status text, detail text, at text,
    primary key (prod_id, name));
"""


class Store(store.Store):
    def __init__(self, path=None):
        super().__init__(path or config.RESULTS_DB, SCHEMA)

    def fetched(self):
        return {(r[0], r[1]) for r in self.db.execute(
            "select prod_id, name from fetch where status = 'ok'")}

    def record_fetch(self, prod_id, name, url, status, detail):
        self.db.execute("insert or replace into fetch values (?,?,?,?,?,?)",
                        (prod_id, name, url, status, detail, store._now()))
        self.db.commit()
