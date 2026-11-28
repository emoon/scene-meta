# Design

What each demoscene production needs to run correctly: the machine, the disk
swaps, the keys to press. Kept as TOML that people can read and edit, one
repo for every platform, starting with Amiga and C64.

## Principles

- The TOML is the truth. The sweepers' sqlite databases are their private
  run logs (one schema for every platform, `tools/README.md`). Nothing is
  compiled from the TOML; consumers read it as they like.
- Entries are emulator agnostic. They state hardware facts and what the
  production needs. No emulator names, no emulator options.
- The files hold only what Amiga and C64 need today. Adding a TOML field
  later breaks nothing, so nothing is added ahead of a concrete need
  (patches, click positions, download URLs and other platforms all wait).
- TOML 1.0 only, so any parser can read the files.

## Layout

```
data/<platform>/machines.toml    machine presets, in hardware terms
data/<platform>/<bucket>.toml    productions
tools/scenemeta/                 validator, merge, and the sweepers: core/ and one subpackage per platform
tools/amiga/                     the Amiga sweeper's patched Amiberry, ROMs, notes
tools/c64/                       the C64 sweeper's ROMs and notes (drives stock VICE)
build/                           everything that is built (Amiberry), git-ignored
```

One licence per directory: `data/` is CC0, each emulator keeps its own, the
rest of `tools/` is MIT. ROMs are never included.

Productions are bucketed by the first character of the title as written (no
stripping of "The"): `a.toml` .. `z.toml`, `0-9.toml`, and `misc.toml` for
everything else. Entries are sorted by title, then ID. Machine and type are
not used for the split: both are things an edit can change.

Every tested production is listed, working or not, so that absence means
"never tested". Fields equal to the platform default are omitted.

## Machines

`machines.toml` names the default preset and defines each preset in hardware
terms. An entry picks a preset with `machine` (omitted when it is the
default) and may override single hardware fields on top of it:

```toml
[demozoo.4321]
title   = "Some Demo"
group   = "Some Group"
source  = "ai"
machine = "a1200"
fast    = "4M"
```

The hardware field names of a platform are exactly the ones its
`machines.toml` uses; a value is a string or a whole number (`drives = 2`).
A new preset is added when the same override keeps recurring.

## Entries

```toml
[demozoo.142]
title  = "Desert Dream"
group  = "Kefrens"
source = "script"
disks  = ["DesertDream-A.adf", "DesertDream-B.adf"]
events = [{ at = 536.9, until = 566.9, disk = 2 }, { at = 541.9, key = "lmb" }]
```

The key is `[demozoo.N]`, or `[csdb.N]` when Demozoo has no entry. The other
database's ID may be given as a cross-reference field (`csdb = 1234`). An ID
appears once per platform, as a key or as a cross-reference.

| field | meaning |
|-------|---------|
| `title`, `group` | for the reader, and for bucketing and sorting; `group` is optional |
| `source` | how the entry was found, see below; required |
| `machine` | preset name; omitted when it is the platform default |
| hardware fields | overrides on the preset |
| `result` | only when the production does not simply work: `broken`, `crashes-later`, `unknown`, `unsupported` |
| `boot` | `floppy` or `hd`: what to start it from, when that is not the first thing the download offers (an executable that only runs from a floppy, a disk set better run from its hard-drive archive) |
| `kind` | `collection`, `standalone`, `separate-disks`, `menu`, `boot_fresh` |
| `disks` | file names in disk order: a multi-disk production's, or the one disk meant where the download has several |
| `events` | what is done while it plays, in the order it happens: each has `at`, optionally `until`, and is a disk that goes in (`disk`, and optionally `drive`) or a key pressed (`key`, and optionally `pos = [x, y]` for a positioned mouse click) |
| `run` | the file to start, when the obvious one is wrong or ambiguous: an executable, or the download's launcher script (see below) |
| `boot_disk`, `boot_file` | the disk (1-based) and file to boot, when not the first |
| `assign` | AmigaDOS assigns, e.g. `{ Killer = "SYS:" }` |
| `area` | `[width, height]` of the part of the screen the production draws into, when it was measured (see below) |
| `aspect` | `16:9` when that part of the screen has that shape, whatever the pixels: 320x180, and 640x180 in hires; no other shape is said |
| `note` | free text |
| `variant` | see below |

All times are seconds of emulated time since power-on. An event is one
thing done at its `at`, and says which by the field it has: `disk` or
`key`, one of them. Another kind of event will be another field. `disk` is
the number of the disk that goes in (1 when the production booted from a
later one). `drive` is the drive the disk goes into when that
is not the first: 2 or more, and no more than the machine's `drives` (on
Amiga `drive = 2` is DF1). A key that has a disk taken is an event of its
own, after the disk's.

An event of either kind has a window. `at` is the earliest time it is known
to work, `until` the latest; with no `until` only `at` is known.
`until = inf` says the event may wait for ever (a disk prompt with no
timeout), which a time, the latest anybody tried, does not. Events are in
the order of their `at`, whatever their `until`.

Which end of a window is taken is the player's setting and not the entry's.
An eager player does every event at its `at`. A patient one does it at its
`until` and lets the production show what it shows while it waits (a part
that an early disk skips). Every later event is then done as much later as
this one waited, since the production stood still that long, and the waits
add up; an event that may wait for ever waits as long as the player
chooses. A production that does not stand still while it waits (a part on
a timer whatever is pressed) cannot be said yet.

Key names are lowercase (`space`, `return`, `p1fire`, `p2fire`, `lmb`,
`rmb`: the fire button of the joystick in port 1 or 2, the left and the
right mouse button). On Amiga these six are all there are, and another name
is an error.

Where a download ships a script that runs its parts in turn (`.bat`,
`RunMe`, `start`, `execute_me`), `run` names the script, by its name or its
path in the download, and not one of the parts. The script is executed as
AmigaDOS would from its own directory, so the order of the parts, its `cd`
and its assigns are the download's own and the entry repeats none of them. On
Kickstart 2 and later a command the download does not ship (the author's
own `fadeout`) is skipped and the script goes on, `cd` is built in and
`assign name: path` works; no other Workbench command is supplied. On
Kickstart 1.x a script can only run its parts.

`area` is for a frontend that shows the production full screen and not
with thick borders: some productions draw into 320x180 in the middle of
the 320x256 PAL screen, others into 320x200, and nothing in a download
says so. It is the part of the screen the production draws into, in the
finest pixels it uses: a production with a hires interlaced picture is
640x512 when its parts fill the PAL screen, however much of it is lores.
A part drawn into less does not change it, and a title that fills the
screen for a few seconds before a smaller main part is of it: a player that
cuts to the area must show every part whole. The system's
own screen while the production loads is not the production's. An area of
320x180 has `aspect = "16:9"`, and so has the same part of the screen in
finer pixels: a hires pixel is half as wide and an interlaced line half as
high, so 640x180 and 640x360 are that shape too. Any other area stands alone: 320x200 is
usually still 4:3, so a player may cut the borders away but must not
stretch the picture. How a production is shown is the player's choice.
Neither field changes how the production is run, so an entry with them
plays as the same entry without.

Settings sit on the production. A variant appears only when one specific
download needs different settings; it is identified by file name and SHA-256
and may carry any of the settings fields:

```toml
[[demozoo.142.variant]]
file    = "DesertDream-fixed.lha"
sha256  = "..."
machine = "a1200"
```

## Provenance

One level per production, lowest first:

| `source` | meaning |
|----------|---------|
| `script` | found by a sweep and passed the gate, nobody looked |
| `ai` | worked out with AI assistance |
| `verified` | a person watched the production to its end, including every disk swap, on the stated machine (emulator or real hardware) |

Nothing is `verified` until it has been fully watched. Who verified and when
is in the git history.

A sweep export is a merge: it writes only entries marked `script` and never
touches `ai` or `verified` ones. Where it disagrees with one of those, the
disagreement goes into a report for a person to look at.

The export writes a working entry only when that entry passed the gate
(Amiga; the C64 has no gate yet). When the sweep's best run does not, its
next best are tried, three in all; then the production is written as
`result = "unknown"`.

## Initial import

- Everything from the two sweeps comes in as `script`.
- Productions in the C64 `manual.json` or the Amiga `classes.tsv` come in as
  `ai`.
- The Amiga sweep's `+click` becomes `key = "lmb"` on the swap, only where
  the sweep actually had to click.
- Frame and cycle counts are converted to seconds.
- A C64 production's SID model is not something a sweep can find. It comes
  from Demozoo's `6581` and `8580` tags on the production or on its
  soundtracks, where they agree.
- A sweep boots one production several ways (its executable from a hard
  drive, the same files on a floppy, each disk set). The entry is the way
  that got furthest; the first one found wins a tie. The others are not
  written, and no `variant` tables are produced yet.

## Order of work

1. Repo skeleton, schema, `machines.toml` for both platforms, validator. Done.
2. Move the two sweepers in (`r2-scene-db`, `r2-scene-db-c64`). Done.
3. Amiga: `scenemeta export` merges the sweep's results and `classes.tsv` into
   `data/amiga`. Done, from the sweep that predates the Nov 2026 fixes.
4. C64: the same for its sweep and `manual.json`. Done.
