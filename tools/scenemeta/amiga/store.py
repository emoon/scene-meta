"""The Amiga sweep's log: the shared tables (core/store.py) and

fetch       downloads of missing disks into the NAS mirror
ending      end-of-demo detection verdicts per production (enddetect/)

A variant's ``detail`` holds ``root`` and ``command`` (the directory and
startup-sequence of a hard-drive boot), ``complete`` (the disk set's
numbers run without a gap) and ``run`` and ``choice`` (the file it starts
and whether an entry names it, see media.Variant). A run's holds the
emulator's ``returncode`` and its ``events``.
"""

import json

from ..core import gatelog, store
from . import config

SCHEMA = """
create table if not exists fetch (
    prod_id integer, name text, url text, status text, detail text, at text,
    primary key (prod_id, name));
create table if not exists ending (
    prod_id integer primary key, entry text not null, ending text not null,
    end_s real, end_part real, trace_s real, detail text not null,
    at text not null);
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

    def put_ending(self, prod_id, entry, result):
        """Store an end-detection verdict dict for ``entry``."""
        self.db.execute(
            "insert or replace into ending values (?,?,?,?,?,?,?,?)",
            (prod_id, gatelog.name(entry), result.get("ending", "unknown"),
             result.get("end"), result.get("end_part"), result.get("trace"),
             json.dumps(result, sort_keys=True), store._now()))
        self.db.commit()

    def ending(self, prod_id):
        """``(entry, result_dict)`` stored for ``prod_id``, or None."""
        row = self.db.execute(
            "select entry, detail from ending where prod_id=?",
            (prod_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def endings(self):
        """``{prod_id: (entry, result_dict)}`` for every stored ending."""
        return {prod: (entry, json.loads(detail))
                for prod, entry, detail in self.db.execute(
                    "select prod_id, entry, detail from ending")}
