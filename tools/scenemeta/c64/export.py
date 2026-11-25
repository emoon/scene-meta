"""Writes the sweep's results and the hand observations into the shared
data files (``data/c64``, see docs/DESIGN.md): one entry per production.

A production the sweep found is ``script``; one with a hand observation
(manual.json) is ``ai``. The SID model comes from Demozoo's tags (sid.py),
on top of the machine the sweep chose. The merge replaces only ``script`` entries, so
whatever somebody edited in the data files stays.
"""

import dataclasses
import os

from .. import events, machines
from ..core import export
from . import config, sid

_RESULT = {"works-then-crash": "crashes-later", "crash": "broken"}
_KIND = ("collection", "standalone", "boot_fresh")


@dataclasses.dataclass
class Seen:
    """What the store holds of a variant besides its runs."""
    cls: str = None          # flips | standalone | collection | boot_fresh | broken
    manual: bool = False     # the class was given by hand
    note: str = None
    boot_disk: int = 0       # index of the disk to boot
    boot_file: str = None    # its directory entry; None: the first file
    windows: list = dataclasses.field(default_factory=list)   # store.Window


@dataclasses.dataclass
class Presets:
    """The machines an entry can name (machines.toml)."""
    default: str
    presets: dict            # name -> its fields

    def _hardware(self, name):
        return {f: self.presets[name][f]
                for f in machines.hardware_fields(self.presets)
                if f in self.presets[name]}

    def fields(self, name, model=None):
        """The entry fields that say preset ``name`` with SID ``model``
        (None: not known): the preset that is exactly that machine, else
        ``name`` with the model on top. The default preset is left out."""
        want = {**self._hardware(name), **({"sid": model} if model else {})}
        match = next((n for n in (name, *self.presets)
                      if self._hardware(n) == want), None)
        fields = {"machine": match} if match else {"machine": name, "sid": model}
        if fields["machine"] == self.default:
            del fields["machine"]
        return fields


def seen(store, prod_id, v):
    """The Seen of ``v``, an export.Variant of ``prod_id``."""
    boot = v.detail.get("boot_disk", 0), v.detail.get("boot_file") or None
    if len(v.disks) < 2:
        # Classes and windows are of a disk set. One made by hand before the
        # media found the production's own disk says nothing of that disk.
        return Seen(boot_disk=boot[0], boot_file=boot[1])
    cls, source, note = store.variant_class(prod_id, v.idx) or (None, None, None)
    return Seen(cls, source == "manual", note,
                *(store.manual_boot(prod_id, v.idx) or boot),
                store.schedule(prod_id, v.idx))


# Seconds from an insert to its key where a window gives no delay. Nobody
# measured it: the delays that were measured are 10 s and more.
KEY_DELAY = 5.0


def _events(windows):
    """The windows as an entry says them, in time order: each disk that
    goes in, the key pressed after it, and the keys to press before."""
    out = [{"at": round(at, 1), "key": key.lower()}
           for w in windows for at, key in w.pre_keys]
    for w in windows:
        if w.at is None:
            continue
        at = round(w.at, 1)
        out.append({"at": at, "disk": w.disk})
        if w.until is not None:
            out[-1]["until"] = round(w.until, 1)
        if w.key:
            delay = KEY_DELAY if w.key_delay is None else round(w.key_delay, 1)
            out.append({"at": round(at + delay, 1), "key": w.key.lower()})
    return events.ordered(out)


def _note(seen):
    """The hand's notes: the variant's, then each disk's."""
    return "; ".join(([seen.note] if seen.note else []) +
                     [f"disk {w.disk}: {w.note}" for w in seen.windows if w.note])


def entry(title, groups, v, seen, model, presets):
    """The data-file entry of one production from its export.Variant, what
    was Seen of it and its SID ``model`` (None: not known)."""
    if seen.cls == "broken":
        result = "broken"
    elif v.verdict == "works" or (seen.manual and seen.cls == "flips"):
        result = None           # a hand-made schedule was seen to play
    else:
        result = _RESULT.get(v.verdict, "unknown")
    runs = result in (None, "crashes-later")
    # The disks follow each other, as far as anybody knows.
    chain = runs and seen.cls in (None, "flips")

    e = {"title": title}
    if groups:
        e["group"] = groups
    e["source"] = "ai" if seen.manual else "script"
    # A production that does not run has no machine of its own, but its
    # music still names a chip.
    e.update(presets.fields(v.machine if runs else presets.default, model))
    if seen.cls in _KIND:
        e["kind"] = seen.cls
    if result:
        e["result"] = result
    if len(v.disks) > 1:
        e["disks"] = [os.path.basename(d) for d in v.disks]
    if chain:
        if does := _events(seen.windows):
            e["events"] = does
    if seen.boot_disk:
        e["boot_disk"] = seen.boot_disk + 1
    if seen.boot_file:
        e["boot_file"] = seen.boot_file
    if note := _note(seen):
        e["note"] = note
    elif chain and v.reached < len(v.disks):
        e["note"] = f"the sweep only reached disk {max(v.reached, 1)} of {len(v.disks)}"
    return e


def entries(store, models, presets):
    """``(namespace, id, entry)`` of every production with a finished
    variant. The media gives a production one variant: its disk set.
    ``models``: sid.models()."""
    for prod, title, groups, variants in export.productions(store):
        v = variants[0]
        yield "demozoo", prod, entry(title, groups, v, seen(store, prod, v),
                                     models.get(prod), presets)


def run(store, data=None):
    data = data or config.DATA_DIR
    export.run(data, entries(store, sid.models(), Presets(*export.presets(data))))
