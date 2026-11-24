"""Which Amiga config each demo works on.

    python3 -m scenemeta amiga fetch [--ids ...] [--rate 1.0]
    python3 -m scenemeta amiga sweep [--ids ...] [--limit N] [--jobs N]
                                     [--machine NAME] [--again]
    python3 -m scenemeta amiga report
    python3 -m scenemeta amiga export [--ids ...] [--jobs N]
    python3 -m scenemeta amiga replay [--ids ...] [--jobs N] [--patient]
    python3 -m scenemeta amiga gate [--ids ...] [--jobs N]
    python3 -m scenemeta amiga gate-demote [--write]
    python3 -m scenemeta amiga gate-summary
    python3 -m scenemeta amiga gate-stale
    python3 -m scenemeta amiga expected [--jobs N]
    python3 -m scenemeta amiga shots --out DIR [--ids ...] [--jobs N]
    python3 -m scenemeta amiga migrate [scene.db]
"""

import os
import sys

from ..core import cli
from . import (catalog, classes, config, expected, export, fetch, gate,
               machines, media, migrate, replay, shots, store, sweep)
from ..core.expected import Invalid
from ..core.errors import CannotPlay


def _prods(args):
    return cli.selected(catalog.productions, args)


def main(argv=None):
    ap, sub, p = cli.parser("amiga")
    p.add_argument("--machine", choices=list(machines.BY_NAME),
                   help="only the productions that work on this machine,"
                   " swept before or not")
    p.add_argument("--again", action="store_true",
                   help="the productions swept before too, each up the whole"
                   " ladder")
    p = sub.add_parser("fetch")
    cli.selection(p)
    p.add_argument("--rate", type=float, default=1.0)
    p = sub.add_parser("export", help="merge the results into the data"
                       " files, the entries that pass the gate")
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--jobs", type=int)
    p = sub.add_parser("replay", help="play data-file entries as written")
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--jobs", type=int)
    p.add_argument("--patient", action="store_true",
                   help="every event at its until, not its at")
    p = sub.add_parser("gate", help="pass or fail of data-file entries;"
                       " without --ids, of every one not gated yet")
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--jobs", type=int)
    p = sub.add_parser("gate-demote", help="the entries the gate failed:"
                       " which it demotes to unknown, which are kept")
    p.add_argument("--write", action="store_true",
                   help="write the demotions into the data files")
    sub.add_parser("gate-summary", help="write the counts of what the gate"
                   " saw to the checked-in file")
    sub.add_parser("gate-stale", help="the entries whose download or player"
                   " changed since the gate saw them")
    p = sub.add_parser("expected", help="gate the expected productions and"
                       " write the checked-in scoreboard")
    p.add_argument("--jobs", type=int)
    p = sub.add_parser("shots", help="screenshots of the entries Demozoo has"
                       " none of")
    p.add_argument("--out", default=os.environ.get("SCENEMETA_SHOTS"),
                   help="where they go (default $SCENEMETA_SHOTS)")
    p.add_argument("--ids", type=int, nargs="*")
    p.add_argument("--jobs", type=int)
    args = ap.parse_args(argv)
    if args.cmd == "shots" and not args.out:
        ap.error("shots needs --out or $SCENEMETA_SHOTS")
    try:
        return _command(args)
    except CannotPlay as e:
        sys.exit(f"scenemeta amiga {args.cmd}: {e}")
    except Invalid as e:
        sys.exit(f"{config.EXPECTED}:\n{e}")


def _command(args):
    # replay and shots read the data files, not the database; an entry
    # that could not be played fails the command.
    if args.cmd == "replay":
        return min(1, replay.run(args.ids, jobs=args.jobs,
                                 patient=args.patient))
    if args.cmd == "shots":
        return min(1, shots.run(args.out, args.ids, jobs=args.jobs))
    if args.cmd == "migrate":
        return cli.migrate(migrate.run, args.db or config.RESULTS_DB)

    db = cli.open_store("amiga", store.Store)
    try:
        if args.cmd == "fetch":
            fetch.fetch_all(_prods(args), db, rate=args.rate)
        elif args.cmd == "sweep":
            sweep.run_all(_prods(args), db, jobs=args.jobs,
                          multi_only=args.multi, machine=args.machine,
                          again=args.again)
        elif args.cmd == "report":
            report(db)
        elif args.cmd == "export":
            return min(1, export.run(db, ids=set(args.ids or ()),
                                     jobs=args.jobs))
        elif args.cmd == "gate":
            return min(1, gate.run(args.ids, db, jobs=args.jobs))
        elif args.cmd == "gate-demote":
            gate.demote(db, write=args.write)
        elif args.cmd == "gate-summary":
            print(f"wrote {gate.write_summary(db)}")
        elif args.cmd == "gate-stale":
            gate.stale(db)
        elif args.cmd == "expected":
            return min(1, expected.run(db, jobs=args.jobs))
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
