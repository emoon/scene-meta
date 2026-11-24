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
| `a500_1mb_chip` | 68000, ECS Agnus, KS1.3, 1M chip |
| `a1200` | 68EC020, AGA, KS3.0, 2M chip |
| `a1200_fast` | 68020, AGA, KS3.0, 2M chip + 8M fast |
| `a1200_030` | 68030 + 68882, AGA, KS3.0, 2M chip + 32M fast |
| `a1200_060` | 68060, AGA, KS3.0, 2M chip + 64M fast |

AGA-only productions start at `a1200`. Productions released before Oct 1992 skip the 030/060 rungs. ROMs go in `roms/` (`kick13.rom`,
`kick30.rom`, and `kick12.rom`, a 256K Kickstart 1.2: without it the
`a500_ks12` rung is skipped). Without `kick13.rom` or `kick30.rom` a sweep
stops before its first production, and no run of any command starts
without the ROM of its machine: the error names the ROM and the directory. Demos of the 1.2 era hard-code ROM addresses
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
the left mouse button is clicked if the new disk is not picked up, then the
right one). Each
insert is stored with its time in `swap`. A multi-disk run that goes quiet with disks
left to insert is retried with the idle trigger's head-position gate off
(`anycyl`).

A run also presses keys nobody asked for: the detector's clicks (a disk
that is slow to load gets clicked too), a click after each scheduled insert,
and on the retries a click, or Return, Space and fire in turn, every 30 s.
So when the chosen run of a machine pressed anything, the player
(`../scenemeta/amiga/player.py`) plays the entry of it: first with no key,
then with one more of the run's presses at a time, the nearest to where it
falls short first, and a press is kept only when the run without it got
less far (as the gate measures it). The presses kept are the swap's `key`
and the run's `keys`; at most 12 such runs are made. A press that only
counts with a later one is not found (Megademo 2 takes Return twice).

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
python3 -m scenemeta amiga export                # scene.db -> ../data/amiga, through the gate
python3 -m scenemeta amiga export --ids 142      # specific productions
python3 -m scenemeta amiga replay --ids 142      # play data-file entries as written
python3 -m scenemeta amiga gate --ids 142        # pass or fail on every seed, and why
python3 -m scenemeta amiga gate                  # every entry not gated yet, resumable
python3 -m scenemeta amiga gate-demote           # the failures: what --write demotes
python3 -m scenemeta amiga gate-summary          # scene.db -> amiga/gate-summary.txt
python3 -m scenemeta amiga gate-stale            # entries to gate again
python3 -m scenemeta amiga corpus                # gate corpus.toml -> amiga/corpus-score.txt
python3 -m scenemeta amiga migrate               # convert an older scene.db
python3 -m unittest discover -s tests -t .
```

The sweep's own log is `amiga/scene.db` (sqlite, the shared schema of
`../scenemeta/core/store.py`, times in seconds). The `best` view gives one row
per variant: the chosen machine, its verdict, and its swaps as
`seconds:disk:trigger` (trigger `poll`, `idle`, `reread` or `scheduled`,
`+click` and `+rclick` when the detector clicked; a swap's `key` is only the
press it was shown to need).

`export` (`../scenemeta/amiga/export.py`) merges that into the data files people edit,
`data/amiga/*.toml` (format: `docs/DESIGN.md`). Each
production becomes one entry, taken from the run that got furthest, and
is marked `script`, or `ai` when it has a hand classification in
`../scenemeta/amiga/classes.tsv`. Only `script` entries are replaced: an entry somebody
edited stays, and where the sweep disagrees with it the difference is
printed.

A `script` entry that says the production runs is written only when it
passed the gate. The entry of the sweep's chosen run is gated first (the
chosen run of each variant, the one that got furthest first); when it fails,
the entries of the next best runs the production came alive in are, three
different entries in all. The first that passes is written. When none does,
the production is written as `result = "unknown"` with a note of what the
sweep saw. A line is printed of each production the gate played, and what it
saw goes into `scene.db` as for `gate`, with a digest of the entry played:
an entry whose pass is in the log, by today's player from today's download,
is not played again, so an export that was stopped goes on where it was.
Productions with a hand classification, and those whose entry in the data
files is `ai` or `verified`, are not gated. A production that could not be
played (a missing ROM or media) keeps the entry it has, and the command
exits with status 1.

`replay` (`../scenemeta/amiga/replay.py`) goes the other way: it plays an entry of the
data files exactly as written (its machine, each disk in at its time, each
key after its insert; no detector, no retries) and says whether every disk
was loaded. The playing is done by the player (`../scenemeta/amiga/player.py`),
the only code that turns an entry and its download into an emulator run;
`shots` goes through it too. An entry with keys on its swaps is played once
more without them, which shows whether the keys are needed. Without `--ids`
it plays every entry that has a key on a swap. The keys are `lmb`, `rmb`,
`return`, `space`, `p1fire` and `p2fire`; a swapped disk goes into DF0, or
into the drive its swap names (`drive = 2` is DF1).

`gate` (`../scenemeta/amiga/gate.py`) prints `pass` or `fail` with the
reason, one line per production of `--ids`. Without `--ids` it is the pass
over every entry of the data files: one the log already holds a judgement
of, pass or fail, of the entry as it is now, by today's player from today's
download, is not played again, so a pass that was stopped goes on where it
was. The rules are the core's
(`../scenemeta/core/gate.py`), judged from the record every platform's
player returns of a run. An entry is played on two seeds of the emulator's
random state, three when it has swaps or keys, and passes when on every
seed:

- the production comes alive, does not crash and loads every disk swapped
  in (an entry with no swaps or keys is watched for three minutes);
- the same holds with every disk put in 30 seconds later, a swap's key
  following its disk;
- no key can be left out: the run without it, as long, gets less far. It
  loads fewer disks, crashes, or last reads a disk earlier (a production
  left at its prompt reads no further).

A fail names the first seed it fails on. The line ends with the `until`
proved of each swap, the latest insert that loaded on every seed: `at` plus
30 seconds, or `at` when only that did. The runs of an entry are made in
parallel, `--jobs` emulators at a time over all entries. A fail is a result
and leaves the exit status 0.

What the gate saw is kept in `scene.db`, table `gate`, and never in the
data files: for each entry and seed whether it passed, the reason, the
SHA-256 of the download it was played from (of a download of several files,
that of each file's name and SHA-256), the player's version
(`player.VERSION`) and when. Gating an entry again replaces its records; an
entry that could not be played keeps the ones it had, and why it could not
is kept beside them (table `gate_error`) until it is judged. `gate-summary`
writes how many entries passed, how many failed and how many could not be
played to `gate-summary.txt` here, which is checked in, so a change in the
numbers shows in a diff.

`gate-demote` reads the log against the data files and writes nothing: the
counts, then four lists. The `script` entries that say the production runs
and failed, each with the first seed it failed on and why; the failing
entries that are `ai` or `verified`; the entries that could not be played,
with what was missing; and the entries with no record of them as they are
now, by today's player from today's download (`gate-stale`). With `--write` the first list is demoted: each becomes
`result = "unknown"` with the reason as its note, without its machine,
swaps and keys. The other lists are for a person. A later `export` puts
the next best runs of a demoted production to the gate.
`gate-stale` lists the gated entries whose download, or the player's
version, is no longer the one of their records: those need the gate again.

`corpus` (`../scenemeta/amiga/corpus.py`) runs the gate over the corpus,
`corpus.toml` here: productions with the outcome expected of them. It is
test data, not part of the data set. A table per production, `[demozoo.N]`:

| field | meaning |
|-------|---------|
| `expect` | `plays`: a correct entry of it passes the gate. `broken`: it does not play on any machine, and `why` says so |
| `cause` | a label, on the 84 productions whose detected end missed the video's length in Nov 2026: what the miss was traced to (`launcher`, `bbs-ad`, `swap`, `machine`, `detector`, ...) |
| `note` | free text: the evidence of the cause, or what the sweep's code says of the production |
| `video` | `[shortest, longest]`, the lengths in seconds of the captures Demozoo links; stored for the end detection, not used yet |

It holds the 209 productions whose end was scored against their videos and
the ones the sweep's code comments name. The file must validate, and every id
in it must have an entry in the data files, or the command stops before its
first run. It prints a line per production as `gate` does, with what was expected,
then the total, and writes `corpus-score.txt` here, which is checked in:
how many productions the gate saw as expected (`plays` and a pass, `broken`
and a fail), and of each what was expected and whether it was `pass`, `fail`
or `error` (could not be played). No reason and no time is in it, so the
file changes only when a result does. What the gate saw goes into `scene.db`
as for `gate`.

An entry that cannot be played is an error, not a result: no ROM for its
machine, no media, a machine the player does not have, a key it has no
name for, or `boot`, `disks` and `run` that fit none of the download's variants
or more than one of them (never another variant in the entry's place). The
variants are the ones the sweep runs, its fallbacks included, and `run`
names the file to start whatever the sweep would pick today. The line says
what is missing, nothing is run for that entry, and the command exits with
status 1. `shots` files a `meta.json` with status `error` when the entry
itself is the cause, so it is not tried again until that file is deleted;
for a missing ROM or missing media it files nothing and tries again next
time. Without the Demozoo mirror `sweep`, `export`, `replay`, `gate`, `corpus` and `shots` stop before
their first production, and a sweep whose ROM goes missing on the way stops
there instead of storing results.

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
  Workbench disk; without the math libraries there nothing is played
  (`workbench.require_libs`): a demo that opens one would end at the
  prompt and read as doing nothing.
- A launcher script an entry's `run` names is the startup-sequence itself,
  after `s/scenemeta-go-on`, which sets the fail level to 21: a command
  that is not there fails with 10, which would end the script (and still
  does on Kickstart 1.x). Of the commands a script may call only `Assign`
  is supplied (ours, `name: path` only, Kickstart 2 and later) beside what
  Kickstart has resident (`cd`, `failat`, `run` on 2 and later, nothing on
  1.x); `copy`, `makedir`, `wait` and the like are "unknown command". A
  sweep picks a script only for a set merged into one directory, and a
  patched disk 1 runs an executable only.
