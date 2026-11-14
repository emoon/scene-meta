"""The command line every platform shares: ``sweep`` and ``report``, and how
productions are picked. A platform adds its own commands and options."""

import argparse
import sys

from . import store


def parser(platform):
    """``(parser, subparsers, sweep)`` for ``scenemeta <platform>``."""
    ap = argparse.ArgumentParser(prog=f"scenemeta {platform}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sweep = sub.add_parser("sweep")
    selection(sweep)
    sweep.add_argument("--jobs", type=int)
    sweep.add_argument("--multi", action="store_true",
                       help="only multi-disk variants")
    sub.add_parser("report")
    p = sub.add_parser("migrate", help="convert a sweep database from before"
                                       " the shared schema, in place")
    p.add_argument("db", nargs="?", help="default: the platform's database")
    return ap, sub, sweep


def selection(p):
    """The options that pick productions."""
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--limit", type=int)


def selected(productions, args, keep=None):
    """The productions ``args`` picks; ``productions(ids)`` is the platform's
    catalog. ``keep`` narrows them further, before the limit counts."""
    prods = productions(set(args.ids) if args.ids else None)
    if keep:
        prods = [p for p in prods if keep(p)]
    return prods[:args.limit] if args.limit else prods


def migrate(run, path):
    """The ``migrate`` command: ``run(path)`` is the platform's migration."""
    print(f"{path}: converted" if run(path) else
          f"{path}: already has the shared schema")


def open_store(platform, make):
    """``make()``, the platform's store; exits with what to do when the file
    is from before the shared schema."""
    try:
        return make()
    except store.LegacyDatabase as e:
        sys.exit(f"{e} predates the shared schema; convert it with"
                 f" `python3 -m scenemeta {platform} migrate {e}`")
