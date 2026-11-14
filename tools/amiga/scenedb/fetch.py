"""Fetch the missing disks of multi-disk releases into the NAS mirror.

The NAS mirror keeps one file per production, so when a release's disks are
separate download links only one of them is on disk. This downloads the other
members of the set (from files.scene.org) next to it. A release split over
numbered archives (pwl-rpg1.lha .. pwl-rpg3.lha) is a set too.
"""

import os
import sqlite3
import time
import urllib.parse
import urllib.request

from . import config, diskset, media

USER_AGENT = "r2-scene-db/0.1 (Amiga demo config survey)"


def url_for(link_class, parameter):
    if link_class == "AmigascneFile":
        return "https://files.scene.org/get/mirrors/amigascne" + _quote(parameter)
    if link_class == "SceneOrgFile":
        return "https://files.scene.org/get" + _quote(parameter)
    if link_class == "UntergrundFile":
        return "https://ftp.untergrund.net" + _quote(parameter)
    if link_class == "BaseUrl" and parameter.startswith(("http://", "https://")):
        return parameter
    return None


def _quote(path):
    # Some parameters arrive already encoded (%26, %21, "/%20Groups"):
    # normalise to the plain path first so nothing is encoded twice.
    plain = "/".join(p.strip() for p in urllib.parse.unquote(path).split("/"))
    return urllib.parse.quote(plain, safe="/")


def link_name(parameter):
    return os.path.basename(urllib.parse.unquote(parameter.rstrip("/"))).strip()


def renamed_params(prod_id):
    """``{parameter: resolved_param}`` for links the NAS link state found
    renamed upstream (e.g. a .dms that is now an .adf)."""
    try:
        db = sqlite3.connect(f"file:{config.STATE_DB}?mode=ro", uri=True)
        rows = db.execute("select parameter, resolved_param from link_state "
                          "where prod_id=? and resolved_param is not null",
                          (prod_id,)).fetchall()
        db.close()
    except sqlite3.Error:
        return {}
    return dict(rows)


def missing_members(prod):
    """``[(name, [urls])]`` of disk-set members linked from ``prod`` that are
    not in its NAS directory. Only sets of two or more disks count; of several
    linked sets, the one with the most disks already on the NAS wins."""
    renamed = renamed_params(prod.id)
    urls = {}
    for cls, param in prod.links:
        name = link_name(param)
        cands = [u for u in (url_for(cls, param),
                             url_for(cls, renamed[param]) if param in renamed
                             else None) if u]
        if cands and (diskset.is_disk_image(name)
                      or name.lower().endswith(media.ARCHIVE_EXTS)):
            urls.setdefault(name, [])
            urls[name] += [u for u in cands if u not in urls[name]]
    sets = [s for s in diskset.group(list(urls)) if len(s) > 1]
    if not sets:
        return []
    d = config.prod_dir(prod.id)
    have = {n.lower() for n in os.listdir(d)} if d.is_dir() else set()
    have_keys = {diskset.parse(n) for n in have}

    def present(name):
        # The same disk under another case or format already counts.
        return name.lower() in have or diskset.parse(name) in have_keys

    best = max(sets, key=lambda s: (sum(map(present, s)), len(s)))
    return [(n, urls[n]) for n in best if not present(n)]


def download(url, dest, timeout=60):
    """Download ``url`` to ``dest`` atomically. Raises on HTTP errors and on
    an HTML page served in place of a file."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if data[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("server returned an HTML page")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return len(data)


def fetch_all(prods, store, rate=1.0, log=print):
    """Download every missing set member, at most one request per ``rate``
    seconds. Successes are recorded in ``store`` so a rerun skips them;
    failures are retried."""
    done = store.fetched()
    for prod in prods:
        for name, urls in missing_members(prod):
            if (prod.id, name) in done:
                continue
            errors = []
            for url in urls:
                # A renamed link is saved under its current name.
                dest = config.prod_dir(prod.id) / link_name(url)
                try:
                    size = download(url, dest)
                    store.record_fetch(prod.id, name, url, "ok", f"{size} bytes")
                    log(f"ok    {prod.id} {dest.name} ({size} bytes)")
                    break
                except Exception as e:  # noqa: BLE001 - every failure is recorded
                    errors.append(f"{url}: {e}")
                finally:
                    time.sleep(rate)
            else:
                store.record_fetch(prod.id, name, urls[-1], "error",
                                   " | ".join(errors)[:500])
                log(f"error {prod.id} {name}: {errors[-1]}")
