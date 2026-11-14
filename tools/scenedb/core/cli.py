"""The command line every platform shares: ``sweep`` and ``report``, and how
productions are picked. A platform adds its own commands and options."""

import argparse


def parser(platform):
    """``(parser, subparsers, sweep)`` for ``scenedb <platform>``."""
    ap = argparse.ArgumentParser(prog=f"scenedb {platform}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sweep = sub.add_parser("sweep")
    selection(sweep)
    sweep.add_argument("--jobs", type=int)
    sweep.add_argument("--multi", action="store_true",
                       help="only multi-disk variants")
    sub.add_parser("report")
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
