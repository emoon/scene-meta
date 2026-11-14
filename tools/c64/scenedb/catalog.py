"""Read C64 demo productions and their download links from index.sqlite.

A CSDb release link is not flagged as a download link in demozoo, but the
mirror holds that release's files, so it counts as one.
"""

import collections
import dataclasses
import sqlite3

from . import config

PLATFORM = "Commodore 64"
TYPES = ("Demo", "Intro", "Musicdisk")


@dataclasses.dataclass
class Production:
    id: int
    title: str
    groups: str
    types: tuple
    release_date: str
    links: list        # [(link_class, parameter)] download links


def _connect():
    return sqlite3.connect(f"file:{config.INDEX_DB}?mode=ro", uri=True)


def productions(ids=None):
    """All C64 demos, intros and music disks, ordered by id."""
    db = _connect()
    type_q = ",".join("?" * len(TYPES))
    rows = db.execute(f"""
        select pp.production_id, pt.name
        from productions_production_platforms pp
        join platforms_platform p on p.id = pp.platform_id
        join productions_production_types t on t.production_id = pp.production_id
        join productions_productiontype pt on pt.id = t.productiontype_id
        where p.name = ? and pt.name in ({type_q})""",
                      (PLATFORM, *TYPES)).fetchall()
    types = collections.defaultdict(set)
    for pid, typ in rows:
        if ids is None or pid in ids:
            types[pid].add(typ)

    wanted = sorted(types)
    meta = {}
    links = collections.defaultdict(list)
    for chunk in _chunks(wanted, 900):
        q = ",".join("?" * len(chunk))
        for pid, title, byline, date in db.execute(
                f"select id, title, unparsed_byline, release_date_date "
                f"from productions_production where id in ({q})", chunk):
            meta[pid] = (title, byline or "", date or "")
        for pid, groups in db.execute(f"""
                select pan.production_id, group_concat(n.name, ' / ')
                from productions_production_author_nicks pan
                join demoscene_nick n on n.id = pan.nick_id
                where pan.production_id in ({q})
                group by pan.production_id""", chunk):
            title, _, date = meta.get(pid, ("", "", ""))
            meta[pid] = (title, groups, date)
        for pid, cls, param in db.execute(
                f"select production_id, link_class, parameter "
                f"from productions_productionlink "
                f"where (is_download_link = 1 or link_class = 'CsdbRelease') "
                f"and production_id in ({q}) "
                f"order by id", chunk):
            links[pid].append((cls, param))
    db.close()

    out = []
    for pid in wanted:
        title, groups, date = meta.get(pid, ("", "", ""))
        out.append(Production(pid, title, groups, tuple(sorted(types[pid])),
                              date, links[pid]))
    return out


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
