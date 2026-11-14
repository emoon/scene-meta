"""Read Amiga demo productions and their download links from index.sqlite."""

import collections
import dataclasses
import sqlite3

from . import config

PLATFORMS = {"Amiga OCS/ECS": "ocs", "Amiga AGA": "aga"}
# Executable demo/intro types only; music, packs, cracktros, diskmags etc. are out.
TYPES = ("Demo", "Intro", "32b Intro", "64b Intro", "128b Intro", "256b Intro",
         "512b Intro", "1K Intro", "2K Intro", "4K Intro", "8K Intro",
         "16K Intro", "32K Intro", "40k Intro", "64K Intro", "96K Intro",
         "100K Intro", "Executable Music", "32K Executable Music",
         "64K Executable Music", "Executable Graphics",
         "4K Executable Graphics")


@dataclasses.dataclass
class Production:
    id: int
    title: str
    groups: str
    platforms: tuple   # subset of ("ocs", "aga")
    types: tuple
    release_date: str
    links: list        # [(link_class, parameter)] download links

    @property
    def is_aga(self):
        return "aga" in self.platforms and "ocs" not in self.platforms


def _connect():
    return sqlite3.connect(f"file:{config.INDEX_DB}?mode=ro", uri=True)


def productions(ids=None):
    """All Amiga OCS/ECS + AGA demos and intros, ordered by id."""
    db = _connect()
    plat_q = ",".join("?" * len(PLATFORMS))
    type_q = ",".join("?" * len(TYPES))
    rows = db.execute(f"""
        select pp.production_id, p.name, pt.name
        from productions_production_platforms pp
        join platforms_platform p on p.id = pp.platform_id
        join productions_production_types t on t.production_id = pp.production_id
        join productions_productiontype pt on pt.id = t.productiontype_id
        where p.name in ({plat_q}) and pt.name in ({type_q})""",
                      (*PLATFORMS, *TYPES)).fetchall()
    plats, types = collections.defaultdict(set), collections.defaultdict(set)
    for pid, plat, typ in rows:
        if ids is None or pid in ids:
            plats[pid].add(PLATFORMS[plat])
            types[pid].add(typ)

    wanted = sorted(plats)
    meta = {}
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

    links = collections.defaultdict(list)
    for chunk in _chunks(wanted, 900):
        q = ",".join("?" * len(chunk))
        for pid, cls, param in db.execute(
                f"select production_id, link_class, parameter "
                f"from productions_productionlink "
                f"where is_download_link = 1 and production_id in ({q}) "
                f"order by id", chunk):
            links[pid].append((cls, param))
    db.close()

    out = []
    for pid in wanted:
        title, groups, date = meta.get(pid, ("", "", ""))
        out.append(Production(pid, title, groups, tuple(sorted(plats[pid])),
                              tuple(sorted(types[pid])), date, links[pid]))
    return out


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
