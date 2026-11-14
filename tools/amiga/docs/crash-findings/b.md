# Crash triage, batch b

Productions: 203703 218092 221488 240311 250551 252140 317487 323381.
Each was rerun one attempt at a time with a scratch driver (single emulator,
screenshots kept, `bp`/`watch`/`regs`/`peek` from the `--dbg` protocol) against
a private DB copy. Machines tried beyond the ladder: the same rungs with
`bogomem_size=0` (512K chip only), `floppy_write_protect=true`, ECS,
68060 with `cpu_data_cache`.

## Verdicts

| prod | title | verdict | class |
|------|-------|---------|-------|
| 317487 | Spinotic (Raize) | **fixed**: needs a write-protected disk | fixable, fixed (`emulator.py`) |
| 203703 | BBStro (Laban) | demo bug: overwrites its own VBL-wait routine | unfixable |
| 221488 | First Intro (Copper Crew) | KS1.2 `jmp $FC0CD8` + its L3 handler trashes a0/a1; loses a timing race on every rung | unfixable (race in the intro) |
| 250551 | Guru Meditation With Premeditation (Melon Dezign) | crashes **on purpose** (the joke is a Guru) | works as designed; verdict label only |
| 252140 | Copy Party in Fredius Home '94 (Nivel 7) | DemoManiac copper-list generator runs away over its own music player | unfixable (engine/demo bug) |
| 323381 | Raster Intro (TNC) | needs 512K chip and no slow RAM; then shows its logo but stays static/silent | partly: needs a 512K-only rung, still not "works" |
| 218092 | Remarkable Intro (The Outrunners) | hard-codes KS1.2 / 512K-only library bases; disk image carries a 1992 bootblock utility that resets the machine; still crashes on a clean bootblock | unfixable for now |
| 240311 | Hidden CocaCola (Drifters/Delight) | crack-pack loader (`run nofastmem`, `Loader-Fax`, CrM `0`); SSP goes to CIA space, Guru on every config tried | unfixable for now (not root-caused) |

## Details

### 317487 Spinotic — fixed

Non-DOS bootblock loads `$3D000`, which clears `$40000-$7A000` and then
reloads its loader from disk in `$3D296`: open trackdisk, `TD_CHANGESTATE`,
then `TD_PROTSTATUS` and **if the disk is not write-protected it skips every
read**. `$60000` stays zero, `jsr $60024` slides through zeros into the
`$DFF182` operand the bootblock patched in at `$600C0`: illegal instruction,
alert 4, on every rung (80000004 on the fast CPUs).

Our harness inserted writable copies of the images. With
`floppy_write_protect=true` it boots to the demo on the plain `a500` (audio on,
13 different screens in 4000 frames).

Fix (`scenedb/emulator.py`, `_uae_config`): every floppy is inserted
write-protected (one global Amiberry option, so it covers swapped-in disks
too). That is what a user does with a demo disk, and no schema change is
needed (it is a property of the harness, not of a run). Test:
`tests/test_emulator.py`.

Regression spot check: see "Spot check" below.

### 203703 BBStro — demo bug

Two-hunk cruncher stub; the intro's main loop calls a VBL wait at `main+$5E`
and, right after it, swaps two longs with `lea main+$5C(pc),a0;
movem.l (a0),d0-d1; exg; movem.l d0-d1,(a0)`. Those 8 bytes are the first
instruction of the VBL wait itself (`move.l $DFF004,d0` becomes `$F004...`),
so the next call is a Line-F (alert 0B). Same on KS1.3 (crash after ~5 s of
text) and KS3.0 (immediately, because it starts faster). All PC-relative, so
no memory layout changes it. It would only survive on a CPU whose instruction
cache keeps the stale routine (68040/060 copyback); a 68060 run with
`cpu_data_cache=true` was too slow to finish under load. Not fixable in the
ladder.

### 221488 First Intro — race in the intro

ByteKiller-style exe decrunching to absolute `$22AE0`. Its level-3 handler
(`$250F4`) clobbers a0/a1 without saving them, then chains with
`jmp $FC0CD8`: the KS1.2 L3 server entry (on 1.3 that address is mid-routine,
illegal instruction at frame 642 on `a500`). On `a500_ks12` the chain is right,
but the server saves the *already clobbered* a0/a1, so the interrupted code
gets them back wrong. The first copper-list build (`$22E18`, called once
without waiting for the raster) is interrupted in our deterministic run, its
`a0` jumps, and it writes copper words over the handler at `$250F4` (watch hit
at frame 641, pc `$22EDE`): alert 4. On hardware it is a few-percent race.
ECS, 512K-only and 1.2 all crash at the same frame. Would need timing jitter
(not something the ladder should grow for one intro).

### 250551 Guru Meditation With Premeditation — crashes on purpose

The intro runs for ~25 s (Melon photo, "Melon dezign in 1993:", title, then
`move.l #$0,$14` / `divs #0,d0` on screen) and then does exactly that: the
zero-divide vector is 0, so the CPU jumps to address 0 and Gurus (alert 4).
7 alive samples (needs 8) before the crash. Behaviour is correct; it is the
verdict label, not the machine. Hand-label it as working if the report needs
it (e.g. `classes.tsv`), nothing to fix in the ladder.

### 252140 Copy Party in Fredius Home '94 — DemoManiac runaway copper list

"Saved by DemoManiac" player exe (27 hunks, complete). On `a1200` its
ProTracker CIA player installs its level-6 handler at `$A240E` (frame 75); at
frame 124 the effect's copper generator (`$24A30`..: one `WAIT`+moves per
line, counter at `$dfb7` and climbing) has run past its buffer and writes
`b501 fffe ...` over the player, and the next CIA-B interrupt executes copper
words: Line-F (8000000B). On the A500 rungs it address-errors inside
graphics.library's copper-list code (PC `$FCFF16`) a little later. The
generator never terminates its table walk; nothing in the machine changes
that (same on 68020/030/060). Unfixable here.

### 323381 Raster Intro — needs 512K chip only, still not "works"

Imploder-style stub: its data hunk has no CHIP flag (1989), so on our A500
(512K chip + 512K slow) the copper list lands in slow RAM (`COP1LC=$C31E9C`).
The copper fetches garbage, which enables and raises interrupts the intro has
no handler for; the CPU ends up at address ~4 inside a level-5 interrupt:
alert 4 (`$79` on KS1.2).

With `bogomem_size=0` (stock 512K A500) on KS1.3 it shows its TNC logo with
copper bars and waits for LMB without crashing, but the main loop runs with
SR=`$2300` (level-3 masked), so its music/VBL handler (`$54A92`) never runs:
static and silent, so `no-activity`. KS1.2 + 512K-only still crashes.

Suggested follow-up (not implemented: it does not make this one pass, and
one example does not justify a rung): a stock `a500_512k` rung (68000, OCS,
KS1.3, 512K chip, no slow RAM) for 1987-89 executables whose hunks lack
MEMF_CHIP. It is the machine most of that era's exes were written on.

### 218092 Remarkable Intro — KS1.2 / 512K-only absolute bases, plus a bootblock utility

The disk is a DOS disk (`s/startup-sequence` = `e 1`) carrying a 1992
"Imagination 1.6" boot utility (by Zulu/Addonic) in the bootblock. It waits
~80 s at its menu, then boots. `e` (288 bytes) wipes `$28000-$7E000`,
reads `1` to `$58000`, RLE-unpacks it (`$B2` escape) to `$28000` and jumps to
`$28020`. The 1987 intro then uses **hard-coded library bases**:
`lea $21FE,a6` (GfxBase, also `$2230` = its copper pointer) and
`lea $5C68,a6` (DOSBase). Dumping RAM showed GfxBase=`$21FE` and a library at
`$5C68` exactly on KS1.2 with 512K chip only (KS1.3 512K-only has GfxBase at
`$221E`; with slow RAM everything moves).

Even on that machine it does not get to `$28020`: the boot utility resets the
machine; with a standard bootblock installed (`xdftool boot install`) KS1.2
still dies during `e`'s load with a privilege violation (alert 8) on
`Supervisor()` executed from a ROM mirror address (`$07E008AA`), i.e. a wild
jump after `e`'s memory wipe. KS1.3 configs: recoverable Guru 4. The root
block date (2040) is not the cause (patched to 1986, same crash).

Side note for the launch fallback (`media.launch_variant`): it replaced the
startup-sequence with `"e"` and dropped the argument `1`, so that variant
could never work for this disk. Keeping a disk's own startup-sequence when its
first command already names an executable in the root would be more correct,
but it does not fix this production, so it is not implemented.

### 240311 Hidden CocaCola — not root-caused

DMS → DOS disk "Delight Brings U..Fresh Warez!": `run nofastmem`,
`Loader-Fax`, `reboot`. `Loader-Fax` (116 bytes) formats the word at absolute
`$2B0` with RawDoFmt and `Execute()`s a command of that *number* (normally
`0`); `0` is a CrM-crunched exe (`libs/CrM.library`, `libs/amos.library`
present). On `a500` the CPU takes an illegal-instruction exception with
SSP=`$BFE8D2` (CIA space), i.e. the stack pointer was already garbage. Same
Guru on 512K-only and with write-protect; KS1.2 shows the same
Supervisor-at-ROM-mirror privilege violation as 218092 (both are DOS disks on
KS1.2; note for whoever looks at the KS1.2 rung: two DOS floppies hit it). Not
resolved in the time spent.

## Spot check for the write-protect change

12 random single-disk **DOS** floppies (the group that could try to write to
their disk) that the sweep has as `works`, rerun as one plain attempt on their
chosen machine with the change: 11 `works`. The 12th, 347759 (Psykotrope
DemoCompil 03, a menu), is `no-activity` with and without write-protect alike;
in the sweep its first attempt was also `no-activity` and the click retry made
it work. So no regression seen. It is a sample of 12, not a sweep; demos that
write to their own disk would now stop at a "write-protected" requester. None
turned up.

The sweep's stored results were made with writable disks. Floppies that
crashed or had no activity should be rerun to pick up the change (it can only
matter to them, given the spot check).

## Code changes (branch crash-b)

- `scenedb/emulator.py`: floppies are inserted write-protected
  (`floppy_write_protect=true`).
- `tests/test_emulator.py`: floppy config is write-protected, HD stays
  writable.

Scratch tools (driver `one.py`, disassembler, RAM dumps) are in
`/tmp/claude-1000/-home-emoon-code-projects-r2-scene-db--claude-worktrees-crash-b/6dc7f246-2a6d-4385-84f9-ca88ee295ef5/scratchpad/tools/`.
