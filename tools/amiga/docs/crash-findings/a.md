# Crash triage, batch a

Branch `crash-a` (worktree `.claude/worktrees/crash-a`), commits `19cd0b5`..`9dce70a`.
Verdicts below are from re-runs with this branch against a private copy of
`scene.db` (`/tmp/claude-1000/crashwork/a/scene.db`), `SCENEDB_LIBS` pointing
at the math libraries from a Workbench disk, and a scratch NAS that adds the
two Repugnance archives `scenedb fetch` now downloads.

| prod | title | verdict | cause | fix |
|---|---|---|---|---|
| 2019 | Hardcore | FIXED (loader) | wrong executable, and it loads its files from DF0: | `372a606`, `515d78e` |
| 7236 | Deep | FIXED (loader); the floppy set already worked | HD variant ran `keppi`, one of 13 parts, not `dEEP` | `372a606` |
| 27135 | Ilex | FIXED (loader) | `ilex-a.dms` and `ilex-b.dms` are the two halves of ONE disk | `9dce70a` |
| 31893 | Fast | FIXED (HD boot) | crashes/halts without the boot setup program (AGA/topaz) | `19cd0b5` |
| 35337 | Repugnance | FIXED (missing data files: fetch + merge) | release split over 3 archives; NAS had 1 | `599a2cf` + `scenedb fetch` |
| 46521 | Motion Blur | FIXED (HD boot), needs `libs/` | needs AGA enabled + mathieeedoub*.library | `19cd0b5` |
| 181975 | NetHed | UNFIXABLE (demo bug, probably) | part 3 plots through a never-set NULL bitplane table | - |
| 182743 | Count Duckula Trainer | FIXED (HD boot) | default font topaz 9 overflows its glyph buffer into its code | `19cd0b5` |

## Re-run results (`run1.py` = `sweep.run_all` capped at 2 emulators)

- 46521 Motion Blur -> a1200: works
- 182743 Count Duckula Trainer -> a500: works
- 35337 Repugnance -> a1200_fast: works (with rpg2/rpg3 fetched)
- 31893 Fast -> a1200: works
- 2019 Hardcore -> HD variant a500: no-activity (loader waits for DF0:), floppy fallback a500: works
- 181975 NetHed -> a500: crash (unchanged)
- 7236 Deep, 27135 Ilex: not swept again (the host ran out of memory: 0 GB available, so I stopped
  starting emulators). Verified by direct runs instead: `dEEP` from HD on a1200_fast plays (audio,
  screens change for 3000 frames); the joined Ilex ADF plays on a1200 and a1200_fast.
- Regression check of the setup program: 10 random HD variants that already worked
  (5 a500, 5 a1200: 232433 182978 263305 225158 223676 23455 131931 233662 10382 207016)
  all still `works`.


## Fixes (all generalise; each commit message has the detail)

1. **`19cd0b5` HD boots run a setup program first** (`scenedb/workbench.py`).
   A hard-drive variant used to boot straight into the demo on a bare ROM.
   `s/scenedb-setup` (68000 code generated in Python, no Commodore binary)
   now runs first and does what SetPatch + Workbench prefs did on a real
   machine:
   - `SetChipRev(SETCHIPREV_BEST)` on V39+: KS3.0 leaves graphics.library
     at ECS until SetPatch, so an OS screen with more than 6 bitplanes fails
     to open. Probably affects many of the ~6,000 HD `no-activity` runs on
     the AGA rungs, not only Motion Blur.
   - topaz 8 as `GfxBase->DefaultFont`: KS1.x without
     `devs:system-configuration` defaults to topaz 9.
   - `libs/` (`SCENEDB_LIBS`, optional, gitignored) is copied into `LIBS:`.
     **To do: populate `libs/`** with the Workbench disk libraries
     (at least `mathieeedoubbas`, `mathieeedoubtrans`, `mathieeesingtrans`,
     `mathtrans`; copies are in
     `~/code/projects/tbl-newage/ToolChain/RunTime/WinUAE/BootPartition.A1200/Libs/`).
2. **`515d78e` failed HD variant → its files on a boot floppy** (`media.floppy_variant`,
   tried via `sweep.fallbacks`), for demos that load from `DF0:`.
3. **`372a606` executable pick**: the title-named executable wins in unpacked
   archives too (it only did for merged sets), and hunk files named like
   data (`.dat .data .bin .ovl`) rank last.
4. **`599a2cf` numbered archives are a set** (`pwl-rpg1.lha`..`rpg3.lha`):
   `fetch` downloads the missing ones, `media` unpacks them into one tree.
   **To do: run `python3 -m scenedb fetch`** against the real NAS (I only
   fetched into a scratch copy).
5. **`9dce70a` partial DMS archives are joined**: DMS headers give the
   cylinder range; archives that are not whole disks are joined into one ADF.

Unit tests: 55 pass (`python3 -m unittest discover -s tests -t .`).

## Per production

### 2019 Hardcore (Anarchy, 1992, OCS)
The LHA holds `hc.1ph-pip.exe` (1K loader), `hc.2xy-ko.dat` (107K, a hunk
file) and `hc.3zf-muh.dat` (data). `_pick_exe` took the biggest hunk file,
the `.dat` overlay, which gurus when started (alert 3/4 on every rung). The
real loader, started from the hard drive, puts up "No disk present in unit 0":
it reads its files from DF0:. With the loader picked and the files on a boot
floppy it plays on a500 (music, scroller).

### 7236 Deep (CNCD/Parallax, 1995, AGA)
The production already passed: the 2-disk DMS set works on a1200_fast. The
crashing variant was the LHA (13 executables): we ran `keppi`, the biggest;
`importante.txt` says "Start the demo with the command dEEP". Now picked by
title; `dEEP` plays from the hard drive on a1200_fast.

### 27135 Ilex (Mystic, 1994, AGA)
`ilex-a.dms` is cylinders 0-39 and `ilex-b.dms` cylinders 40-79 (DMS header,
`xdms v`): one disk split in two, not a two-disk set. Booting half a disk as
disk 1 gave line-F gurus everywhere. Joined, it runs on plain a1200 (the
separate `Mystic-Ilex.adf` variant already worked on a1200_fast; it differs
from the joined image from byte 450581 on, so it is another copy).

### 31893 Fast (Powerline, 1996, tagged OCS)
"4th in Fastcompo at I'96" (file_id.diz). 68000 rungs: alert 0B (line-F, FPU
instructions); a1200/a1200_fast: guru + reboot (no FPU). On the 68030+68882
rung it halted (reason 3, fetch from a non-existing address) at frame 68
without the setup program; with it, it plays (picture, then the scroller
with music). The re-run sweep then picks a1200 (works), so the line-F guru on
the 68000 rungs is not a hard FPU requirement; it is an AGA intro (the OCS
tag is wrong). I did not check which half of the setup (AGA or topaz 8) it needs.

### 35337 Repugnance (Powerline, 1997, AGA)
Demozoo links `pwl-rpg1.lha`, `pwl-rpg2.lha`, `pwl-rpg3.lha`; the NAS had
only rpg1 (executable + 9 of the 48 `data/rep-*.data`). The demo quit (a1200)
or halted (030/060). With the three archives merged into one tree it plays
on a1200_fast (needs fast RAM; plain a1200 quits).

### 46521 Motion Blur (Horizontal Lamerz, 2000, AGA 64K)
(The handoff's "alert 4 in user mode, USP=4".) 68020 C code (`muls.l`), so
the 68000 rungs are expected to fail. On the A1200 rungs: the startup opens
`mathieeedoubbas.library` / `mathieeedoubtrans.library` (disk libraries),
the open fails, `exit()` restores SP from a never-set variable (0), `rts`
jumps to 0 → illegal instruction at $E. With the libraries it opened, then
quit at once: `OpenScreenTags` with depth 8 failed because KS3.0 had not
enabled AGA (no SetPatch); depth 5 opened fine. With both, it runs on a1200.

### 181975 NetHed (Embassy, 1995, AGA 40K) — unfixable here
Plays ~25 s on every rung (Embassy logo, "NetHed" title, a checkerboard
zoom), then halts (double fault) at the start of the next part, on every CPU
including the 68000. That part plots pixels with `bset/bclr d4,(a1,a0.w)`
where `a1 = ($90dd2)+1`, a bitplane pointer table that is never written
(write watch from frame 100 to the crash: no write; the only references to it
are those two reads). So it draws over $0-$2C00, the exception vectors
included, and the next exception double-faults. Same with the setup program.
Looks like a bug in the intro (or a damaged file: the 12K crunched exe is the
only download), not our ladder; 4 alive samples at 250 frames, so it stays
`crash`.

### 182743 Count Duckula Trainer (TRSI/Red Sector, 1990)
Alert 4 (illegal instruction, supervisor) on every rung, also KS1.2 and from
a floppy. The scroller renders each character with graphics `Text()` into an
8x8 bitmap whose plane is at `$63CC6`, 16 bytes right before its blitter
routine at `$63CD6`. With topaz 9 (KS1.x default without
`devs:system-configuration`) Text writes a 9th line over the routine's first
opcode (`$41F9` → `$0100`), and the CPU then hits `$00DF` (illegal). Every
real disk had Workbench's 80-column prefs (topaz 8). With topaz 8 as the
default font it runs on a500.
