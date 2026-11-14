"""which Amiga config each demo works on.

    python3 -m scenedb amiga fetch [--ids ...] [--rate 1.0]
    python3 -m scenedb amiga sweep [--ids ...] [--limit N] [--jobs N]
    python3 -m scenedb amiga report
    python3 -m scenedb amiga export
    python3 -m scenedb amiga replay [--ids ...] [--jobs N]
"""

import argparse
import sys

from . import catalog, classes, export, fetch, media, replay, store, sweep


def _prods(args):
    ids = set(args.ids) if args.ids else None
    prods = catalog.productions(ids)
    if args.limit:
        prods = prods[:args.limit]
    return prods


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scenedb amiga")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "sweep"):
        p = sub.add_parser(name)
        p.add_argument("--ids", type=int, nargs="*")
        p.add_argument("--limit", type=int)
        if name == "fetch":
            p.add_argument("--rate", type=float, default=1.0)
        else:
            p.add_argument("--jobs", type=int)
            p.add_argument("--multi", action="store_true",
                           help="only multi-disk variants")
    sub.add_parser("report")
    sub.add_parser("export", help="merge the results into the data files")
    p = sub.add_parser("replay", help="play data-file entries as written")
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--jobs", type=int)
    args = ap.parse_args(argv)

    if args.cmd == "replay":    # reads the data files, not the database
        return replay.run(args.ids, jobs=args.jobs)

    db = store.Store()
    try:
        if args.cmd == "fetch":
            fetch.fetch_all(_prods(args), db, rate=args.rate)
        elif args.cmd == "sweep":
            sweep.run_all(_prods(args), db, jobs=args.jobs,
                          multi_only=args.multi)
        elif args.cmd == "report":
            report(db)
        elif args.cmd == "export":
            export.run(db)
    finally:
        db.close()


def report(db):
    q = db.db.execute
    print("variants by chosen machine and verdict:")
    for row in q("select machine, verdict, count(*) from best "
                 "group by 1, 2 order by 1, 2"):
        print("  %-12s %-18s %6d" % row)
    # Per production, its best multi-disk variant: running and reaching
    # every disk, else running, else whatever got furthest.
    rows = q("""select prod_id, title, machine, verdict, disk_count,
                       disks_reached
                from best where disk_count > 1
                order by prod_id, verdict in ('works', 'works-then-crash') desc,
                         disks_reached * 1.0 / disk_count desc""").fetchall()
    best = {}
    for r in rows:
        best.setdefault(r[0], r)
    ran = {k: r for k, r in best.items() if r[3] in ("works", "works-then-crash")}
    full = {k for k, r in ran.items() if r[5] >= r[4]}
    cls = classes.load()
    labelled = {k: cls[k] for k in set(best) - full if k in cls}
    # Sets that only run once installed: every disk in one directory.
    merged = {r[0] for r in q(
        "select prod_id from variant where note like ? and best_verdict in"
        " ('works', 'works-then-crash')", (media.MERGED_NOTE + "%",))} \
        & set(best) - full
    # A menu has to run to pass; an HD version or separately booted disks
    # are judged apart from the floppy set's own run.
    passed = full | merged | {k for k, (kind, _) in labelled.items()
                              if kind in classes.PASS
                              and (kind != "menu" or k in ran)}
    print(f"multi-disk productions: {len(best)}; running {len(ran)}, "
          f"every disk reached {len(full)}, passing {len(passed)}")
    print(f"  run from one directory (installed): {len(merged)}")
    for k in sorted(merged):
        print(f"    {k:>7} {best[k][1][:40]}")
    labelled = {k: c for k, c in labelled.items() if k not in merged}
    for kind in classes.KINDS:
        ks = sorted(k for k, (c, _) in labelled.items() if c == kind)
        print(f"  {kind}: {len(ks)}")
        for k in ks:
            r = best[k]
            print(f"    {r[0]:>7} {r[1][:40]:40} {r[5]}/{r[4]}  {cls[k][1][:50]}")
    open_ = set(best) - full - merged - set(labelled)
    print("  running but short of the last disk:")
    for k in sorted(open_ & set(ran)):
        r = ran[k]
        print(f"    {r[0]:>7} {r[1][:40]:40} {r[2]:11} {r[3]:17} {r[5]}/{r[4]}")
    print("  not running on any machine:")
    for k in sorted(open_ - set(ran)):
        r = best[k]
        print(f"    {r[0]:>7} {r[1][:40]:40} {r[2]:11} {r[3]}")
    print("productions with no bootable media:",
          q("select count(*) from production where id not in "
            "(select prod_id from variant)").fetchone()[0])


if __name__ == "__main__":
    sys.exit(main())
