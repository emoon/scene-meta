# Design

What each demoscene production needs to run correctly: the machine, the disk
swaps, the keys to press. Kept as TOML that people can read and edit, one
repo for every platform, starting with Amiga and C64.

## Principles

- **The TOML is the truth.** The sweepers' sqlite databases are their private
  run logs (one schema for every platform, `tools/README.md`). Nothing is compiled from the TOML; consumers read it as they like.
- **Emulator agnostic.** Entries state hardware facts and what the production
  needs. No emulator names, no emulator options.
- **Only what Amiga and C64 need today.** Adding a TOML field later breaks
  nothing, so nothing is added ahead of a concrete need (patches, click
  positions, download URLs and other platforms all wait).
- **TOML 1.0 only**, so any parser can read the files.

## Layout

```
data/<platform>/machines.toml    machine presets, in hardware terms
data/<platform>/<bucket>.toml    productions
tools/scenemeta/                 validator, merge, and the sweepers: core/ and one subpackage per platform
tools/amiga/                     the Amiga sweeper's patched Amiberry, ROMs, notes
tools/c64/                       the C64 sweeper's ROMs and notes (drives stock VICE)
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
swaps  = [{ disk = 2, at = 536.9, key = "lmb" }]
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
| `result` | only when the production does not simply work: `broken`, `crashes-later`, `unknown` |
| `boot` | `floppy` or `hd`: what to start it from, when that is not the first thing the download offers (an executable that only runs from a floppy, a disk set better run from its hard-drive archive) |
| `kind` | `collection`, `standalone`, `separate-disks`, `menu`, `boot_fresh` |
| `disks` | file names in disk order; multi-disk productions only |
| `swaps` | disk swaps: `disk`, `at`, and optionally `until`, `key`, `key_delay` |
| `keys` | key presses needed before any swap: `at`, `key` |
| `run` | the file to start, when the obvious one is wrong or ambiguous |
| `boot_disk`, `boot_file` | the disk (1-based) and file to boot, when not the first |
| `assign` | AmigaDOS assigns, e.g. `{ Killer = "SYS:" }` |
| `note` | free text |
| `variant` | see below |

All times are seconds of emulated time since power-on. In a swap, `at` is an
insert time known to work and `until` the last one known to work; `key` is
pressed `key_delay` seconds after the insert. Key names are lowercase
(`space`, `return`, `p1fire`, `p2fire`, `lmb`).

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
| `script` | found by a sweep, nobody looked |
| `ai` | worked out with AI assistance |
| `verified` | a person watched the production to its end, including every disk swap, on the stated machine (emulator or real hardware) |

Nothing is `verified` until it has been fully watched. Who verified and when
is in the git history.

A sweep export is a merge: it writes only entries marked `script` and never
touches `ai` or `verified` ones. Where it disagrees with one of those, the
disagreement goes into a report for a person to look at.

## Initial import

- Everything from the two sweeps comes in as `script`.
- Productions in the C64 `manual.json` or the Amiga `classes.tsv` come in as
  `ai`.
- The Amiga sweep's `+click` becomes `key = "lmb"` on the swap, only where
  the sweep actually had to click.
- Frame and cycle counts are converted to seconds.
- A sweep boots one production several ways (its executable from a hard
  drive, the same files on a floppy, each disk set). The entry is the way
  that got furthest; the first one found wins a tie. The others are not
  written, and no `variant` tables are produced yet.

## Order of work

1. Repo skeleton, schema, `machines.toml` for both platforms, validator. Done.
2. Move the two sweepers in (`r2-scene-db`, `r2-scene-db-c64`). Done.
3. Amiga: `scenemeta export` merges the sweep's results and `classes.tsv` into
   `data/amiga`. Done, from the sweep that predates the Nov 2026 fixes.
4. C64: the same for its sweep and `manual.json`.
