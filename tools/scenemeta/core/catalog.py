"""Read a platform's productions and their download links from index.sqlite
(the Demozoo export)."""

import collections
import dataclasses
import sqlite3

from . import config


@dataclasses.dataclass
class Production:
    id: int
    title: str
    groups: str
    platforms: tuple   # the platform's own tags for Demozoo's platforms
    types: tuple
    release_date: str
    links: list        # [(link_class, parameter)] download links


def _connect():
    return sqlite3.connect(f"file:{config.INDEX_DB}?mode=ro", uri=True)


def ids_without_screenshots():
    """The ids of the Demozoo productions that have no screenshot."""
    db = _connect()
    try:
        return {pid for (pid,) in db.execute(
            "select id from productions_production where id not in "
            "(select production_id from productions_screenshot)")}
    finally:
        db.close()


def productions(platforms, types, ids=None, link_classes=()):
    """The productions of ``platforms`` (Demozoo platform name -> tag) that
    have one of ``types``, ordered by id. Links of ``link_classes`` count as
    downloads besides the ones Demozoo flags as such."""
    db = _connect()
    plat_q = ",".join("?" * len(platforms))
    type_q = ",".join("?" * len(types))
    rows = db.execute(f"""
        select pp.production_id, p.name, pt.name
        from productions_production_platforms pp
        join platforms_platform p on p.id = pp.platform_id
        join productions_production_types t on t.production_id = pp.production_id
        join productions_productiontype pt on pt.id = t.productiontype_id
        where p.name in ({plat_q}) and pt.name in ({type_q})""",
                      (*platforms, *types)).fetchall()
    plats, kinds = collections.defaultdict(set), collections.defaultdict(set)
    for pid, plat, typ in rows:
        if ids is None or pid in ids:
            plats[pid].add(platforms[plat])
            kinds[pid].add(typ)

    wanted = sorted(plats)
    meta = {}
    links = collections.defaultdict(list)
    class_q = ",".join("?" * len(link_classes))
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
                f"where (is_download_link = 1 or link_class in ({class_q})) "
                f"and production_id in ({q}) "
                f"order by id", (*link_classes, *chunk)):
            links[pid].append((cls, param))
    db.close()

    out = []
    for pid in wanted:
        title, groups, date = meta.get(pid, ("", "", ""))
        out.append(Production(pid, title, groups, tuple(sorted(plats[pid])),
                              tuple(sorted(kinds[pid])), date, links[pid]))
    return out


def tagged(names):
    """``{production id: its tags among names}`` of every production that
    has one of them."""
    db = _connect()
    q = ",".join("?" * len(names))
    out = collections.defaultdict(set)
    for pid, tag in db.execute(f"""
            select ti.object_id, t.name
            from taggit_taggeditem ti
            join taggit_tag t on t.id = ti.tag_id
            join django_content_type c on c.id = ti.content_type_id
            where c.app_label = 'productions' and c.model = 'production'
              and t.name in ({q})""", tuple(names)):
        out[pid].add(tag)
    db.close()
    return dict(out)


def soundtracks():
    """``{production id: the ids of its soundtracks}``: the music
    productions Demozoo links it to."""
    db = _connect()
    out = collections.defaultdict(list)
    for pid, track in db.execute(
            "select production_id, soundtrack_id from productions_soundtracklink"):
        out[pid].append(track)
    db.close()
    return dict(out)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
