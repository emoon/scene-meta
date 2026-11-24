# C64 sweeper

Which C64 setup each demo works on, and when multi-disk demos ask for their
next disk, so a frontend can flip disks automatically. The C64 twin of
`../amiga`: same shape, the same sweep log (`../README.md`).

Source data is the NAS: `meta/index.sqlite` (the Demozoo export) for the
production list (platform "Commodore 64": Demo, Intro, Musicdisk), and the
release's files from `mirrors/csdb/<CSDb release id>/` or, failing that, the
scene.org zip (`mirrors/sceneorg`, unpacked into `work/media/`). A CSDb
directory that holds an item of another collection under the same id is passed
over (`../scenemeta/c64/csdbmirror.py`). The disk
images of one release are one set, in natural name order (`../scenemeta/c64/diskset.py`;
`.d64` preferred over `.g64` of the same disk).

Every set is autostarted headless in stock VICE 3.7.1 (`x64sc`, under Xvfb) up a
machine ladder until one works.

## Machine ladder (`../scenemeta/c64/machines.py`)

| name | machine |
|------|---------|
| `pal_1541` | C64 PAL (6569), 1541, true drive emulation |
| `ntsc_1541` | C64 NTSC (6567R8), 1541, true drive emulation |

Warp mode is on, sound off, CPU JAM quits the emulator (reported as a crash).

## Setup

Debian's `vice` ships no ROMs. `roms/` holds them under the names VICE looks up
(`roms/C64/`, `roms/DRIVES/`); it is git-ignored. Rebuild it from VICE's embedded
ROM headers (any VICE source tree, e.g. the one under `replay_frontend`):

```bash
python3 -m scenemeta.c64.tools.extract_roms <vice>/include/embedded c64/roms
```

Needs `x64sc` and `xvfb-run` on `PATH` (`SCENEMETA_VICE` overrides the binary).

## How a run is driven (`../scenemeta/c64/vice.py`, `../scenemeta/c64/runner.py`)

VICE has no "run N frames", so the run is paced by wall clock and stamped with
emulated time: the remote monitor (`-remotemonitor`) stops the emulator on any
input, `stopwatch` gives the exact CPU cycle count, `m 8:1c00` reads the 1541's
VIA2 port B, `screenshot` grabs the screen, and `x` resumes. Every 0.1 s of wall
time that is one sample (cycles, PC, drive port, screenshot hash). A run counts
C64 cycles since power-on; the database has them as seconds on the machine's
clock (PAL 985248 Hz, NTSC 1022727 Hz).
Cycle stamps are exact; the moments between samples are not reproducible run to
run.

## What "works" means (`../scenemeta/c64/verdict.py`)

A sample is alive when the screen changed since the previous one and the C64 is
not at the BASIC prompt (cursor blink would otherwise count). A run works with
20 s of C64 time alive before any crash (CPU JAM, emulator death, wall-clock
timeout).

## Disk flips (`../scenemeta/c64/swapwait.py`)

Disk 1 is autostarted in drive 8; a flip is detach, 3 s empty, attach (the
write-protect sensor has to see the slot empty). A demo is waiting for a disk when
the drive port (VIA2 port B, sync bit ignored) holds still:

- `poll`: motor on, port frozen for 20 s. The loader polls for the disk change
  (Mojo, Next Level, Wonderland XIII) or sits in an error state with the LED
  solid on (Edge of Disgrace).
- `idle`: motor off, port frozen for 30 s, and the screen shows at most 8 distinct
  frames in that time: a still or looping prompt (Deus Ex Machina's spinning
  disk). A stopped drive alone is not enough, demo parts that load nothing for a
  minute look the same but show many screens.

- `probe`: motor off, port frozen for 150 s, screen animated: an endless loop with
  a "turn disk" sign (Coma Light 13). A cheap bet; a refused probe backs off 150 s.

After an insert the demo may want a key ("turn disk and press space"). While the
drive stays untouched, `runner.py` presses space, Return, port-2 fire and port-1 fire
5 s apart (`../scenemeta/c64/xinput.py`: XTest events to the emulator's Xvfb window).

A flip counts (`accepted`) once the drive port moves again after the insert. A
disk the demo ignores is taken back out and triggers back off for 30 s.

Each flip is a `swap` row: the disk number, trigger, `waiting_since` (when the
drive went quiet, about when the demo asked), `at` (when the disk went in),
`accepted`, the key pressed after the insert, and the screenshot of the prompt.

## Usage

From `tools/`:

```bash
python3 -m scenemeta c64 sweep --ids 324781 6309     # specific productions
python3 -m scenemeta c64 sweep --multi --jobs 64     # resumable
python3 -m scenemeta c64 report
python3 -m scenemeta c64 manual                      # load manual.json (hand observations)
python3 -m scenemeta c64 export                      # the same, then merge into ../data/c64
python3 -m scenemeta c64 migrate                     # convert an older scene.db
python3 -m unittest discover -s tests -t .
```

Results are in `c64/scene.db` (sqlite, the shared schema of
`../scenemeta/core/store.py`, times in seconds). The `best` view gives one row
per variant: chosen machine, verdict, disks reached, and the accepted `swaps`
as `seconds:disk:trigger`. `manual.json` is written in cycles and converted
when it is loaded.

Tools: `python3 -m scenemeta.c64.tools.pilot <id>` runs one production and prints
flips (`--shots dir` saves the prompts), `scenemeta.c64.tools.trace` prints the
raw drive/screen samples of a disk set (no flipping), `scenemeta.c64.tools.sheet`
makes a contact sheet of screenshots.

## Export (`../scenemeta/c64/export.py`)

`export` writes one entry per swept production into `../data/c64`
(`../docs/DESIGN.md`), `script` from the sweep alone and `ai` where
`manual.json` has the production:

- `result`: `crashes-later` and `broken` from the verdict, `unknown` for a run
  with nothing moving on screen; a hand class `broken` is `broken`, and a
  hand-made schedule counts as running whatever the sweep saw.
- `events` from the `schedule` view: a disk event per window (`at` the
  insert, `until` the window's end), a key event `key_delay` after it where
  the window has a `key` (5 s when it gives no delay, which nobody
  measured), and one for each of
  the windows' `pre_keys`. A set classed `standalone`, `collection` or
  `boot_fresh` gets its `kind` and no events.
- `boot_disk` and `boot_file` from `manual.json`, else the sweep's.
- The SID model, where Demozoo's tags give one: `machine = "pal_1541_8580"`,
  or `sid = "8580"` on a machine that has no such preset. A 6581 is the
  default and says nothing.
- `note`: the hand notes of the production and of each disk.

A hand observation is of a disk set. Where the media now finds a single disk
for the production it is not applied.

## Pilot (famous multi-disk demos, `pal_1541`)

| demo | disks | flips (disk @ waiting since) |
|------|-------|------------------------------|
| Mojo | 4 | 2 @ 3:11 poll, 3 @ 5:38 poll, 4 @ 10:27 poll |
| Next Level | 4 | 2 @ 4:53, 3 @ 9:07, 4 @ 15:31, all poll |
| Wonderland XIII | 3 | 2 @ 4:03 poll, 3 @ 7:12 poll |
| Edge of Disgrace | 3 | 2 @ 1:32 poll, 3 @ 11:06 poll |
| Deus Ex Machina | 2 | 2 @ 7:07 idle |
| Coma Light 13 | 2 | 2 @ 4:58 probe |

## Known limits

- A key is only pressed after a disk went in; prompts that need a key before the demo
  asks for a disk, with an animated screen, are not seen.
- A driveless stretch of an animated part looks like a playing demo, so an
  `idle` flip is only found for still or tightly looping prompts.
- A false trigger is taken back out when the demo ignores the disk, but a demo
  that reads the wrong disk first can hang or crash.
- The SID model is not swept: sound is off and a run cannot tell. The export
  takes it from Demozoo's `6581` and `8580` tags (`../scenemeta/c64/sid.py`).
- Only 1541 + PAL/NTSC is tried, and a REU for a demo that asks: no 1541-II. Cartridge
  and PRG-only releases are not picked up (disk images only).
- The insert happens 20-30 s after the demo asked (the detector needs the drive quiet that long);
  `waiting_since` is the better "asked at" estimate.
