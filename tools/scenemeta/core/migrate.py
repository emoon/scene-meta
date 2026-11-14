"""Convert a sweep database from before the shared schema (core/store.py),
in place.

What the old tables held is the platform's knowledge; it passes the SQL.
This runs it as one transaction: either the whole file is converted or it
is left as it was.
"""

import sqlite3

from . import store


def _missing(db, columns):
    """The statements that bring an older file up to the last legacy shape:
    ``columns`` maps a table to the ``name type`` of columns that were
    added over time."""
    out = []
    for table, wanted in columns.items():
        have = {r[1] for r in db.execute(f"pragma table_info({table})")}
        out += [f"alter table {table} add column {column};"
                for column in wanted if have and column.split()[0] not in have]
    return out


def migrate(path, before, after, extra_schema="", columns=None, functions=()):
    """Convert the database at ``path``. Returns False when it already has
    the shared schema.

    ``before`` drops the views and indexes on the old tables and moves the
    tables out of the way; then the new schema is created; then ``after``
    fills it from the old tables and drops them. ``columns`` are added to
    the old tables first where a file lacks them; ``functions`` are
    ``(name, nargs, fn)`` that the SQL may call.
    """
    db = sqlite3.connect(path, isolation_level=None)
    try:
        if not store.is_legacy(db):
            return False
        for name, nargs, fn in functions:
            db.create_function(name, nargs, fn, deterministic=True)
        script = "\n".join(["begin immediate;", *_missing(db, columns or {}),
                            before, store.SCHEMA, extra_schema, after,
                            f"pragma user_version = {store.VERSION};",
                            "commit;"])
        try:
            db.executescript(script)
        except sqlite3.Error:
            if db.in_transaction:
                db.execute("rollback")
            raise
        db.execute("vacuum")    # the old tables' pages
        return True
    finally:
        db.close()
