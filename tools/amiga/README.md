# Amiga sweeper

Which Amiga machine configuration each demo works on, and when multi-disk
demos ask for their next disk, so a frontend can pick the config and swap
disks automatically.

Source data is the NAS: `meta/index.sqlite` (the Demozoo export) for the
production list, `demozoo/<id/1000>/<id>/` for the files. Every Amiga OCS/ECS
and AGA demo and intro (`../scenemeta/amiga/catalog.py`) is booted headless in a patched
Amiberry (`amiberry/`, see `amiberry/SNAPSHOT.md`) up a machine ladder until
one works.

## Machine ladder (`../scenemeta/amiga/machines.py`)

| name | machine |
|------|---------|
| `a500` | 68000, OCS, KS1.3, 512K chip + 512K slow |
| `a500_1mb` | 68000, ECS Agnus, KS1.3, 1M chip + 512K slow |
| `a500_ks12` | 68000, OCS, KS1.2, 512K chip + 512K slow |
| `a500_512k` | 68000, OCS, KS1.3, 512K chip |
| `a1200` | 68EC020, AGA, KS3.0, 2M chip |
| `a1200_fast` | 68020, AGA, KS3.0, 2M chip + 8M fast |
| `a1200_030` | 68030 + 68882, AGA, KS3.0, 2M chip + 32M fast |
| `a1200_060` | 68060, AGA, KS3.0, 2M chip + 64M fast |

AGA-only productions start at `a1200`. Productions released before Oct 1992 skip the 030/060 rungs. ROMs go in `roms/` (`kick13.rom`,
`kick30.rom`, and `kick12.rom`, a 256K Kickstart 1.2: without it the
`a500_ks12` rung is skipped). Demos of the 1.2 era hard-code ROM addresses
and guru under 1.3. Some intros only run when AmigaDOS loads them into chip
RAM, i.e. on a bare 512K A500 (`a500_512k`).

## What "works" means (`../scenemeta/amiga/verdict.py`)

Every 250 frames the run records status and a screenshot. A sample is alive
when audio DMA is on or the screen changed (with bitplanes on). A run works
with 8 alive samples (40 s of activity) before any crash: CPU halt, a
dead-end exec alert, a reboot loop, or the emulator dying. Kickstart's own
screens (insert disk, a CLI saying "not enough memory") are static and
silent, so they never count.

## Disk swaps

Disk sets are formed from file names (`../scenemeta/amiga/diskset.py`: `DemoA`/`DemoB`,
`-1`/`-2`, `disk1`, `d2`, ...). Disk 1 boots in DF0, the rest go on the swap
list, and the emulator's swap-wait detector inserts the next disk when the
demo waits for it (CIA /CHNG polling with the drive idle, or a silent prompt;
a mouse click is pressed if the new disk is not picked up). A run chosen with
such a click is run once more with nothing pressed from that insert on, and
the click is only kept when that run falls short: a disk that is slow to
load gets clicked too. Each
insert is stored with its time in `swap`. A multi-disk run that goes quiet with disks
left to insert is retried with the idle trigger's head-position gate off
(`anycyl`).

`scenemeta fetch` downloads set members the NAS mirror is missing (it keeps one
file per production) from files.scene.org into the production's NAS dir.
Numbered archives (`pwl-rpg1.lha` .. `pwl-rpg3.lha`: a release split over
several downloads) are a set too, and unpack into one tree.

## Usage

From `tools/` (the layout and what the platforms share: `../README.md`):

```bash
python3 -m scenemeta amiga fetch                 # missing disks -> NAS
python3 -m scenemeta amiga sweep --jobs 96       # resumable
python3 -m scenemeta amiga sweep --ids 89 142    # specific productions
python3 -m scenemeta amiga report
python3 -m scenemeta amiga export                # scene.db -> ../data/amiga
python3 -m scenemeta amiga replay --ids 142      # play data-file entries as written
python3 -m scenemeta amiga migrate               # convert an older scene.db
python3 -m unittest discover -s tests -t .
```

The sweep's own log is `amiga/scene.db` (sqlite, the shared schema of
`../scenemeta/core/store.py`, times in seconds). The `best` view gives one row
per variant: the chosen machine, its verdict, and its swaps as
`seconds:disk:trigger` (trigger `poll`, `idle`, `reread` or `scheduled`,
`+click` when a click was needed; the click is also the swap's `key`).

`export` (`../scenemeta/amiga/export.py`) merges that into the data files people edit,
`data/amiga/*.toml` (format: `docs/DESIGN.md`). Each
production becomes one entry, taken from the variant that got furthest, and
is marked `script`, or `ai` when it has a hand classification in
`../scenemeta/amiga/classes.tsv`. Only `script` entries are replaced: an entry somebody
edited stays, and where the sweep disagrees with it the difference is
printed.

`replay` (`../scenemeta/amiga/replay.py`) goes the other way: it plays an entry of the
data files exactly as written (its machine, each disk in at its time, each
key after its insert; no detector, no retries) and says whether every disk
was loaded. An entry with keys on its swaps is played once more without
them, which shows whether the keys are needed. Without `--ids` it plays
every entry that has a key on a swap. Left mouse button only so far, and
swapped disks always go into DF0.

Build Amiberry, from the top of the repo. Everything built goes into
`build/`, which is git-ignored, and the sweeper runs the binary from there:

```bash
CC=clang CXX=clang++ cmake -S tools/amiga/amiberry -B build/amiberry -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DUSE_PCEM=OFF -DUSE_PPC=OFF -DUSE_QEMU_PPC=OFF -DUSE_LIBSERIALPORT=OFF \
    -DUSE_LIBENET=OFF -DUSE_PORTMIDI=OFF -DUSE_LIBMPEG2=OFF -DUSE_MPG123=OFF \
    -DUSE_UAENET_PCAP=OFF -DUSE_UAENET_TAP=OFF -DUSE_ZSTD=OFF
cmake --build build/amiberry
```

## Known limits

- Megademos with a selection menu idle in the menu; nobody picks a part, so
  later disks are never requested.
- The swap frame is when the detector fired (about 10 s into a polled wait,
  or the idle timeout), not the first frame of the prompt.
- Executables are booted from a directory hard drive with a one-line
  startup-sequence, run after `s/scenemeta-setup` (`../scenemeta/amiga/workbench.py`):
  what SetPatch and Workbench's preferences did on a user's machine (AGA
  enabled on KS3.0, topaz 8 as the default font). Disk-based libraries
  (mathieeedoubbas, ...) come from `libs/` (`SCENEMETA_LIBS`), copied from a
  Workbench disk; without it, demos that need them fail.
