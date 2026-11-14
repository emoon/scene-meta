# Crash triage, batch d (branch `crash-d`)

Re-run on the ladder with the fixes below, using the scenedb sweep code on a
private DB (`/tmp/claude-1000/crashwork/d/scene.db`), max 2 emulators.

## Verdicts

| prod | title | before | after | cause | class |
|---|---|---|---|---|---|
| 139098 | Perehelion | a500 works-then-crash `alert:00040001` @9001 | **a500 works** | stale data in ExecBase->LastAlert, "confirmed" by the run ending | fixed (verdict) |
| 145025 | Exile | a500 works-then-crash `alert:0c400002` @9001 | **a500 works** | same: value sits in LastAlert from frame 1001 while the demo plays | fixed (verdict) |
| 233685 | Reborn | a500 works-then-crash `alert:0c9f1d1c` @9001 | **a500 works** | same | fixed (verdict) |
| 242841 | BBS-Fax Trackmo | a500 works-then-crash `alert:a2841368` @9001 | **a500 works** | same; the demo keeps writing changing data to ExecBase+$202 | fixed (verdict) |
| 193819 | RAF Party Intro | a500 works-then-crash `alert:3` @5251 | **a500_512k works** | intro Gurus when AmigaDOS loads it into slow RAM (CLI task at $C06670); runs on a bare 512K A500 | fixed (new ladder rung) |
| 224067 | Guardian Snail | a500 works-then-crash `alert:4` @7751 | **a500_512k works** | same slow-RAM Guru (it also raises joke alerts 0a/0b/4/3 itself while playing; the onset rule ignores them) | fixed (new ladder rung) |
| 231705 | Nice | a500 works-then-crash `alert:4` @8001 | **a500 works** | waits for LMB to start, quits on the next LMB into a Guru; the 30 s click retry pressed it again | fixed (sweep: retry with only the clicks needed) |
| 191784 | Podtekst | a1200_fast works-then-crash `reboot` | **a1200_fast works** | text joke demo that resets the machine at its end (~70 s) and plays again; no alert | fixed (verdict) |
| 180128 | The Saturne Day | a1200 works-then-crash `alert:8000000b`, 2/3 disks | **a1200 works, 3/3 disks** (scheduled swaps ~4000 and ~9000) | animated "INSERT DISK 2 INTO DF0" prompt the detector does not see; the click retry clicks past it with disk 1 in and the demo Gurus; the scheduled-swap retry was based on that crashed run | fixed in ranking (sweep/verdict), see detail |
| 219234 | Connection Megademo | a1200_fast works-then-crash `alert:8000000b`, 2/2 | **a500 works** 1/2 expected | works on a500 on disk 1 for the whole budget; the "2/2" run had disk 2 forced in by a poll+click and crashed 4 samples later, and outranked the clean run | fixed (ranking) |
| 221840 | Predators Megademo | a500 works-then-crash `halt`, 2/2 | a500_ks12 works-then-crash 2/2 expected (the a500 crash run no longer counts; on ks12 the forced disk 2 played ~100 s before halting) | same pattern: disk 2 forced in at 4418, CPU halt at 4941 | fixed (ranking) |
| 223948 | BAD Megademo 1 | a500 works-then-crash `alert:a`, 2/2 | unchanged (a500 works-then-crash 2/2) | "PRESS BUTTON" menu; a scheduled disk 2 is read and plays ~80 s, then line-A Guru on every machine | open: probably the menu needs a joystick button / part choice, not fixable here |
| 262349 | Motala Party Demo | a500 works-then-crash `alert:4` @3001 | unchanged | plays ~40 s, screen blanks, Guru 4 at the same point on every KS1.x rung (clicks don't matter); chip-only machines fail at once (absolute-address code). AGA rungs now show `alert:8000000b` instead of `reboot` | genuinely broken (crash at its end), unfixable |
| 307284 | Kuchmistrz | a1200_fast works-then-crash `reboot` | a1200_fast works-then-crash `alert:81000005` | plays ~140 s then exec "corrupt memory list" at the same frame on 020/030/060; scene.org zip holds the same file (sha1 identical) | genuinely broken (crash at exit), unfixable |

## Fixes (commits on `crash-d`)

1. `85190bf` **ExecBase per media kind** (`emulator.execbase`). KS3.0 puts
   ExecBase $20 higher when the uae hard drive is mounted ($150c vs $149c on
   the A1200, $40000824 vs $40000804 with Z3 fast). The diskless measurement
   never matched, so **no AGA-rung HD run in the sweep ever had its
   LastAlert read**: dead-end alerts showed up as `reboot`. Every AGA HD
   verdict in `scene.db` with crash `reboot` is suspect (re-run to fix).
2. `4c9c9b6` **verdict**:
   - an alert counts only on the sample where LastAlert *takes* its value
     (onset); a value already there while the demo played is data. On the
     last sample, playing audio is not a Guru. This is what made the
     "@9001" crashes (139098, 145025, 233685, 242841).
   - KS2+ shows a dead-end alert after the reset: if the reset count moved
     between the previous sample and the alert sample, nothing after it
     belongs to the crashed boot (RAF Party Intro on A1200 was hidden by
     the replay).
   - a reset after a boot that played >= WORKS_ALIVE samples, with no
     alert, followed by the demo playing again, is the demo's own restart
     (Podtekst), not a reboot loop.
   - `played_swaps`: in a crashed run, a swapped disk counts toward
     `reached` only if WORKS_ALIVE alive samples follow it before the crash.
     Megademos that loop on disk 1 crashed seconds after a forced disk 2
     and outranked the clean run; and a swap after the crash (Saturne Day)
     no longer makes the crashed run the base for scheduled swaps.
3. `7f9547c` **`a500_512k` rung**: 68000/OCS/KS1.3, 512K chip, no slow
   RAM, after `a500_ks12` (nothing earlier changes).
4. `2176311` **click retry with a cap**: when a clicking attempt came alive
   after N clicks and then crashed and nothing works yet, retry with
   `max_clicks=N`.

Tests: `python3 -m unittest discover -s tests -t .` (57 pass, 13 new).

## Detail / follow-ups

- How the multi-disk ones were checked: a full climb is hours per set
  (36000-frame budgets per disk x dozens of attempts), so 180128 was
  reproduced step by step at 30000 frames (`sweep.attempt` plain, then
  `swap_frames` rounds on it): plain works 1/3 -> scheduled @4001 works
  2/3 -> scheduled @9000 works 3/3, no crash. 219234/221840 expectations
  are from re-applying `played_swaps` to the stored swap/crash frames; not
  re-run end to end.
- 219234/221840/223948 loop on disk 1 (or sit at a "PRESS BUTTON" menu) for
  the whole budget and never ask for disk 2: README's known limit
  (megademo menus). The fix only stops a forced, immediately crashing
  disk 2 from beating a clean run.

- Production impact: (1) means every AGA HD `reboot` verdict, and (2) the
  "@ last sample" alert crashes, should be re-run in the main DB. The sweep
  only re-judges on a re-run (stored verdicts don't change with the code).
  Query: `select ... from run where crash like 'alert:%' and crash_frame =
  frames + 1` for the last-sample ones.
- `a500_512k` costs 1-2 more runs per production that fails the earlier
  rungs.
