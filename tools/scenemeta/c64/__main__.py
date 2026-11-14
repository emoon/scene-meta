"""Which C64 setup each demo works on, and when its multi-disk
sets ask for the next disk.

    python3 -m scenemeta c64 sweep [--ids ...] [--limit N] [--jobs N] [--multi]
    python3 -m scenemeta c64 report
    python3 -m scenemeta c64 migrate [scene.db]
"""

import json
import sys

from ..core import cli
from . import catalog, config, migrate, store, sweep

MANUAL = config.ROOT / "manual.json"


def _prods(args):
    since = args.since and (lambda p: p.release_date[:4] >= str(args.since))
    return cli.selected(catalog.productions, args, since)


def main(argv=None):
    ap, sub, p = cli.parser("c64")
    p.add_argument("--since", type=int, metavar="YEAR",
                   help="only productions released in YEAR or later")
    p.add_argument("--boot", action="store_true",
                   help="boot the file whose name matches the title, not the first")
    sub.add_parser("manual", help="rebuild windows and collections, load manual.json")
    args = ap.parse_args(argv)

    if args.cmd == "migrate":
        return cli.migrate(migrate.run, args.db or config.RESULTS_DB)

    db = cli.open_store("c64", store.Store)
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
                       disks_reached, swaps
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
