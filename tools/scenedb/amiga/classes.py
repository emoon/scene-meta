"""Hand classifications of multi-disk productions the sweep cannot finish
on its own, from looking at their screens (classes.tsv).

menu          a megademo or musicdisk: the user picks a part or a tune, so
              later disks are only asked for on request. Counts as a pass.
use-hd        the production also ships an HD version (an archive holding
              every disk's files), which is what a frontend should run;
              the floppy set's swaps are not worth chasing. Counts as a
              pass.
separate-disks every disk boots and runs on its own; nothing asks for a
              swap, the user boots each disk. Counts as a pass.
install-only  the disks hold an installer or archive, not a bootable demo.
crash         crashes on every machine in the ladder.
broken-media  a disk image of the set is damaged (a truncated DMS).
"""

import csv
import pathlib

PATH = pathlib.Path(__file__).parent / "classes.tsv"
KINDS = ("menu", "use-hd", "separate-disks", "install-only", "crash", "broken-media")
PASS = ("menu", "use-hd", "separate-disks")


def load(path=PATH):
    """``{prod_id: (kind, note)}``."""
    out = {}
    with open(path, newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if not row or row[0].startswith("#"):
                continue
            pid, kind, note = int(row[0]), row[1], row[2] if len(row) > 2 else ""
            if kind not in KINDS:
                raise ValueError(f"{path}: {pid}: unknown class {kind!r}")
            out[pid] = (kind, note)
    return out
