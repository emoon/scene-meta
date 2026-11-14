# Crash triage, batch c

Branch `crash-c`. Each production was re-run on single rungs with a scratch
probe (one emulator at a time, max 2), using the private DB copy.

## Verdicts

| prod | title | verdict | cause |
|---:|---|---|---|
| 1923 | Plastic Passion | **fixed (verdict)** | stale LastAlert 00790020 flagged on the last sample; works on a500 |
| 2354 | Fatal Overdrive | **fixed (sweep)** | detector put disk B in too early; works with disk A kept or B in DF1 |
| 3777 | Step By Step | unfixed | needs FPU; music over a black screen, then CPU halt at ~6000 on 030 and 060 |
| 4017 | Kilofix | unfixed (060 FPU fix helps) | needs FPU; picture freezes ~40 s in (030 halts at 4140) |
| 5316 | Absolute Inebriation | **fixed (verdict)** | stale LastAlert 01eb01cf on the last sample; works, 2/2 disks |
| 5325 | Gulf War | unfixable | damaged disk image (broken file chains); Guru 0000000B loading the next part |
| 5327 | The Mouse Ate The Cat | **fixed (verdict)** | stale LastAlert 2000009c; 1 run in 3 still Gurus at a disk load (non-deterministic) |
| 9063 | Metatag Lock K-231277 | unfixed (060 FPU fix helps) | 030 exe: 030 reboots at 7501; 060 now runs, music over a blank Workbench, halt 6953 |
| 9857 | Megademo VIII | **fixed (sweep)** | menu megademo; a blind disk-B insert at the menu crashed and was ranked as "reached 2" |
| 33870 | Session | unfixable | Software Failure 00000004 in the tunnel part on 020/030/060, Z2 or Z3 RAM |
| 92998 | Exasperate | **fixed (verdict)** | stale LastAlert 16d4ef6f on the last sample; works on a500 |
| 96643 | Overvision | **fixed (verdict)** | stale LastAlert 3a543233 (ASCII ":T23"); works on a500 |
| 111363 | Walec | genuine (works-then-crash is right) | intro plays ~40 s, then Guru 81000005 (exec memory list corrupt) on exit |

## Fixes (all generic, with unit tests; 54 tests pass)

1. **Stale LastAlert on the last sample** (`verdict.crash_signal`). An
   alert-looking value at ExecBase+0x202 that the demo kept playing past was
   ignored on every sample *except the last*, which has no later sample to
   prove it harmless. So any demo whose RAM there decodes as an alert became
   works-then-crash at frame budget+1. An alert is now judged from the sample
   it first appeared at (same value, same boot). Real Gurus are unaffected:
   on KS1.3 and KS3.0 they appear with a restart and nothing alive follows.
   In my DB copy, 9 variants have such a run as their best, and there are 92
   such runs in total.
2. **Alert shown after the restart, then a replay** (`verdict.crash_signal`).
   KS3.0 shows the Guru after the reset, and an HD startup-sequence then
   reruns the demo, so `alive_after` hid it (recorded as "reboot", or as
   works on a short run). An alert that first appears together with a reset
   is now the crash.
3. **ExecBase measured on the wrong boot** (`emulator.execbase`). It was
   measured on a floppy boot. An HD run adds UAE's boot ROM board, which
   moves ExecBase in fast RAM ($40000804 -> $40000824 on a1200_fast). So
   `eb_ok` was never true, and **no alert was ever read on HD runs of the
   fast-RAM rungs**. ExecBase is now measured per (machine, hd).
4. **The 060 rung could not run any FPU code** (`machines`, `emulator`).
   - `cpu_no_unimplemented=true` / `fpu_no_unimplemented=true` mean "do NOT
     emulate the instructions the 040/060 lacks" (they trap). machines.py's
     comment intended the opposite. Both are now `false`.
   - UAE also boots a 68060 with its FPU **disabled** (PCR.DFP, like a 060
     board's ROM; 68060.library re-enables it on a real setup). So every FPU
     instruction was a line-F Guru 8000000B ("Program failed"). For the HD
     variants on the 060 rung, the generated startup-sequence now first runs
     a 32-byte tool, `r2-fpu-on` (Supervisor: `movec pcr`, `bclr #1`), which
     the emulator writes into the HD copy. Verified: Step By Step, Kilofix and
     Metatag Lock get past their 8000000B. The new `Machine.fpu_off` flag
     marks the rung.
   - Limits: floppy variants and trees with their own startup-sequence still
     get no FPU on the 060. In my DB copy, about 2,050 non-working HD variants
     have only been tried on the 060 with the FPU off, so some of them may flip.
5. **A swap the demo crashes on does not count as reaching that disk**
   (`verdict.played_on`, `sweep.attempt`). A swap now counts only if the demo
   then had 8 alive samples before any crash. Fatal Overdrive: the poll
   detector inserted disk B at 6084 while disk A still had a part to load,
   and the demo Gurued 00000004 1.5k frames later. The run still counted as
   2/2 disks, so `short()` was false and none of the retries ran (with disk A
   kept, or with disk B in DF1, it plays on). Megademo VIII: the last-resort
   blind insert at its menu crashed and was chosen over the clean runs. The
   rampolls retry still keys on the raw detector swaps.

## Detail

- **2354 Fatal Overdrive**: needs 512K slow RAM at $C00000. It Gurus at
  once with 512K chip only, 1M chip only, or 512K chip + 1M fast; it runs
  code at $C66xxx. The disk-B "Filled elastic lines" Guru (Software Failure
  00000004, task $C81578) only happens after the early autoswap. Probe
  results on a500, 12000 frames: `detect=False` gives works (42 alive), and
  `drives=2` gives works (42 alive, and later it asks for a disk beyond the
  set). The end-to-end `climb()` result on a500 is at the bottom.
- **5325 Gulf War**: DOS disk, `Load_Demo` loads `Zorlac.*`. `xdftool`
  reports Zorlac.006/.010/.011 with invalid file data block chains (wrong
  sequence numbers), and the image has 54 all-zero tracks. `xdms t` says
  the DMS is OK, so the original dump was already damaged. It plays the
  intro and logo, then Gurus 0000000B right after the next load, the same
  on 512K, KS1.2 and 1M. Needs a different dump.
- **5327**: 2 of 3 a500 re-runs work to 9000 (alive 35). One crashed at
  2751 (Guru 0000000A after a reset) where the others start a disk load at
  2719. Emulation is not deterministic: real audio driver timing, see
  SNAPSHOT.md.
- **3777 Step By Step** ("unfinished version" per its infofile): a1200 (2M
  only) says "not enough memory"; on the 020 without an FPU, 8000000B. On
  the 030/68882, and on the 060 with the FPU on, audio DMA plays, but
  bplcon0 stays 0 (black) and the main task waits in exec, then a double
  fault halt at PC $1E (~6000). Not resolved: could be the demo, or timing
  that a non-cycle-exact fast CPU breaks.
- **4017 Kilofix**: same memory/FPU picture. On the 030 the first scene
  shows, then a halt at 4140. On the 060 with the FPU on it reaches "works"
  (music for 3 min), but the frame hash is constant from ~2000. Treat it as
  not working.
- **9063 Metatag Lock**: readme says 030/FPU/16MB, 060 recommended with
  Oxypatcher. The loader picks `mwi-mtag.030`. 030: reboot at 7501. 060
  with the FPU on: music, a Workbench screen, then a halt at 6953.
- **33870 Session**: the Guru is a Software Failure 00000004 (illegal
  instruction) in the second part, on every AGA rung, also with Z2 fast RAM
  instead of Z3. Likely a demo bug (or an unsupported CPU path), not ours.
- **111363 Walec**: after the fixes the crash is recorded as
  `alert:81000005` instead of `reboot`.
- **92998, 1923, 96643, 5316**: confirmed by re-running and looking at the
  samples: the alert value sits unchanged for thousands of frames while
  audio and screen keep changing.

## For the main sweep

Stored verdicts only change on a rerun. Worth rerunning after merging:
- variants whose best run has `crash like 'alert:%' and crash_frame = frames+1`;
- multi-disk variants whose best run crashed after a swap;
- non-working HD variants (060 FPU, plus alerts never read on HD/fast-RAM runs).

## Not verified end to end

The full `climb()` for 2354 on a500 (retries one at a time) was stopped
before it finished: the box ran out of memory (0 GB available) under the
main sweep. The fix for 2354 is backed by the probe runs above
(`detect=False` and `drives=2` both work) and by the unit tests, not by a
complete climb. Rerun `--ids 2354 9857` once the sweep is done.
