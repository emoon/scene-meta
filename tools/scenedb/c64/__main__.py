"""which C64 setup each demo works on, and when its multi-disk
sets ask for the next disk.

    python3 -m scenedb c64 sweep [--ids ...] [--limit N] [--jobs N] [--multi]
    python3 -m scenedb c64 report
"""

import argparse
import json
import sys

from . import catalog, config, store, sweep

MANUAL = config.ROOT / "manual.json"


def _prods(args):
    ids = set(args.ids) if args.ids else None
    prods = catalog.productions(ids)
    if args.since:
        prods = [p for p in prods if p.release_date[:4] >= str(args.since)]
    if args.limit:
        prods = prods[:args.limit]
    return prods


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scenedb c64")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sweep")
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--limit", type=int)
    p.add_argument("--since", type=int, metavar="YEAR",
                   help="only productions released in YEAR or later")
    p.add_argument("--jobs", type=int)
    p.add_argument("--multi", action="store_true",
                   help="only multi-disk variants")
    p.add_argument("--boot", action="store_true",
                   help="boot the file whose name matches the title, not the first")
    sub.add_parser("report")
    sub.add_parser("manual", help="rebuild windows and collections, load manual.json")
    args = ap.parse_args(argv)

    db = store.Store()
    try:
        if args.cmd == "sweep":
            sweep.run_all(_prods(args), db, jobs=args.jobs,
                          multi_only=args.multi, pick_boot=args.boot)
        elif args.cmd == "manual":
            db.rebuild_windows()
            db.classify_collections()
            db.put_manual(json.loads(MANUAL.read_text()))
        elif args.cmd == "report":
            report(db)
    finally:
        db.close()


def report(db):
    q = db.db.execute
    print("variants by chosen machine and verdict:")
    for row in q("select machine, verdict, count(*) from best "
                 "group by 1, 2 order by 1, 2"):
        print("  %-12s %-18s %6d" % row)
    rows = q("""select prod_id, title, machine, verdict, disk_count,
                       disks_reached, flips
                from best where disk_count > 1 order by prod_id""").fetchall()
    short = [r for r in rows if r[5] < r[4]]
    print(f"multi-disk variants, all disks reached / not: "
          f"{len(rows) - len(short)} / {len(short)}")
    for pid, title, machine, v, n, reached, _ in short:
        print(f"    {pid:>7} {title[:40]:40} {machine:10} {v:17} {reached}/{n}")
    print("productions with no bootable media:",
          q("select count(*) from production where id not in "
            "(select prod_id from variant)").fetchone()[0])


if __name__ == "__main__":
    sys.exit(main())
