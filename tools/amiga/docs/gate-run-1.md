# The first gate run: failures by cause

21 Nov 2026, commit `d390cc7`, player version 1. `scenemeta amiga corpus`,
then `scenemeta amiga gate` over the entries with swaps or keys that are not
in the corpus: 293 productions (222 of the corpus, 120 with swaps or keys,
49 of them in both).

| | gated | pass | fail | error |
|---|---|---|---|---|
| corpus | 222 | 197 | 25 | 0 |
| other entries with swaps or keys | 71 | 27 | 43 | 1 |
| all | 293 | 224 | 68 | 1 |

`corpus-score.txt` did not change: the same 25 fail as in the run of #7.
`gate-summary.txt` has the counts.

## How a cause was found

The gate's line gives the first fault of the first failing seed. Behind each
cause below there is also:

- **replay**: the failing run made once more with a sample every 5 s and the
  pictures kept;
- **key varied**: the entry as written on seed 1, with every swap's key left
  out, `lmb`, and the right button (which the player cannot press; it was
  patched in for this). Given as `none / lmb / rmb`, a letter per swap: `y`
  the disk loaded, `n` it did not, `!` the run crashed;
- **sweep**: the events of the chosen run in the sweep database the entries
  were exported from (it predates the Nov 2026 fixes);
- **detector**: the same media and machine run once by today's sweep code,
  its detector doing the swaps.

A key-varied run that loads every disk is one seed as written, not a gate
pass. No entry was changed.

## Counts by cause

| cause | corpus | other | all | can the schema say it |
|---|---|---|---|---|
| a press the entry lacks, left button | 5 | 9 | 14 | yes |
| a press the schema cannot say, right button | 1 | 1 | 2 | no |
| a key that is not needed | 0 | 2 | 2 | yes |
| swap that is not one, or a crash once the disk loads | 2 | 7 | 9 | yes (`keys`), where it is a click wait |
| swap time | 1 | 0 | 1 | yes |
| swap window under 30 s, or seed-dependent | 3 | 4 | 7 | yes (`until`), but the gate still fails it |
| disk in another drive | 1 | 0 | 1 | no |
| disk 1 back in | 1 | 0 | 1 | yes, but the player refuses it |
| wrong file run (BBS advert viewer) | 9 | 0 | 9 | yes (`run`) |
| crashes whatever the key | 0 | 6 | 6 | - |
| disk never loads whatever the key | 0 | 11 | 11 | not known |
| never comes alive | 2 | 3 | 5 | not known |
| error: entry fits no variant | 0 | 1 | 1 | - |
| | 25 | 43 + 1 | 69 | |

Not seen in this run: a wrong download, a wrong machine. The gate cannot see
a launcher that was not run when the one part started plays for three
minutes (90, 159 pass).

## A press the entry lacks, left button (14)

The disk goes in and nothing reads it; with `key = "lmb"` on the swap it
loads. The sweep clicked (after each pulse of a scheduled insert, or by its
detector) and the export did not write it.

| id | title | gate | key varied | note |
|---|---|---|---|---|
| 18864 | Smart | never came alive | - | no swap: a warning screen, "LMB: Who cares? RMB: ..." from the start; needs an entry in `keys` |
| 119622 | The Animatunes | disk 2 never loaded | n / y / n | 'Hidden Boot' waits for a button from 8.5 s; a click at 10 s also lets the swap at 40 s load |
| 151500 | Time Zone | disk 2 never loaded | n / y / n | last read at 659 s, insert at 690 s; scheduled in the sweep |
| 180128 | The Saturne Day | disks 2, 3 never loaded | nn / yy! / nn | "INSERT DISK 2 INTO DF0:" from 70 s. At 105 s and 180 s with `lmb` both load, then alert 80000004; disk 2 at 75 s with `lmb` loads and plays on. Time and key both |
| 221372 | Mathik | disk 2 never loaded | n / y / y | 'Change Disk' at 380 s; loads at 385 s or 405 s with a click |
| 26938 | Andis Demo | never came alive | n / y / n | read to 1071 s with the click |
| 26946 | Purgatory | never came alive | n / y / n | read to 504 s with the click |
| 143743 | Hexadecimal Perfection | disk 2 never loaded | n / y / n | scheduled in the sweep |
| 223672 | Revenge | disk 2 never loaded | n / y / n | scheduled in the sweep |
| 224091 | Megademo (DH) | disk 2 never loaded | n / y / n | |
| 230486 | Getting In Deep | disk 2 never loaded | n / y / n | scheduled in the sweep |
| 234247 | Ooh! It's Obscene V | disk 2 never loaded | n / y / n | |
| 255398 | Imuzination | disk 2 never loaded | n / y / n | scheduled in the sweep |
| 260275 | Madness Week | disk 2 never loaded | n / y / n | scheduled in the sweep |

## A press the schema cannot say, right button (2)

| id | title | gate | key varied | note |
|---|---|---|---|---|
| 9873 | Lethal Dose 2 | disk 2 never loaded | n / n / y | the entry says `lmb` |
| 236341 | Meteli 4 - Jumala Special | disk 2 never loaded | n / n / y | scheduled in the sweep, no key in the entry |

221372, 74733 and 244877 take either button.

## A key that is not needed (2)

| id | title | gate |
|---|---|---|
| 224322 | Pink Floyd - The Wall | key not needed: lmb of disk 4 |
| 252283 | Smells Like Peanuts | seeds 1, 2: key not needed: lmb of disk 6 |

224322 fails so on every seed; 252283 needs the key on seed 3.

## Swap that is not one, or a crash once the disk loads (9)

Without the click the disk is not read and nothing crashes; with it the
disk loads and a Guru follows within seconds. For 69970 the cause is shown:
the demo waits for a click, not a disk, and its next part is on disk 1. The
others look the same and are not shown to be.

| id | title | gate | key varied | note |
|---|---|---|---|---|
| 69970 | Megademo (Royal Amiga Force) | crashed: alert:00000003 | n / y! / n | a click at 275.7 s and no swap: reads on from disk A at 280 to 291 s, no crash |
| 154472 | Megademo (UFO) | crashed: alert:00000003 | n / y! / n | detector today: no swap wanted in the first 380 s, no crash |
| 158885 | Megademo (Powerslaves) | crashed: alert:0000000a | n / y! / n | detector today: the same crash |
| 219085 | Mekkademo | crashed: alert:00000004 | n / y! / n | detector today: crashes too (alert 0000000b) |
| 244249 | Megademo - Masters At Work | crashed: alert:00000004 | n / y! / n | detector today: no swap, never alive |
| 263719 | Megademo (Trilogy) | crashed: alert:8000000b | n / y! / n | detector today: the same crash |
| 188118 | Runaway | never came alive | n / y! / n | alert 00000003 with the click |
| 263299 | Mega-Demo (Treacl) | disks 2, 3 never loaded | nn / yn! / nn | alert 00000004 after disk 2 |
| 27950 | Control | crashed: alert:8000000a | y! / y! / y! | "Insert Disk 2", loads to cylinder 27, Guru at 90 s, then reboots into disk 2's label screen; the same on `a1200_fast`; detector today: halt. The sweep's click answered the Guru |

## Swap time (1)

| id | title | gate | evidence |
|---|---|---|---|
| 5318 | Virtual Meltdown | disk 2 never loaded; disk 2 until 538.8 | the insert at 508.8 s comes before the prompt and is not seen; at 520 s it loads and plays to 695 s. The late run of the gate loads on every seed |

## Swap window under 30 s, or seed-dependent (7)

The entry plays as written on at least one seed.

| id | title | gate | note |
|---|---|---|---|
| 6750 | Hysteria | seed 2: disks 30 s later, alert:00000004 | seeds 1 and 3 pass. Polls from 184.7 s; the insert at 214.7 s is followed by a Guru at 225 s |
| 164759 | Rayworld | seeds 1, 3: disks 30 s later, halt | seed 2 passes. Polls every 10 s from 45 s; insert at 84.8 s, CPU halt at 88.7 s |
| 185607 | The Fall | every seed: disks 30 s later, disk 2 never loaded | as written it loads on every seed (`until` 121.6). It reads at 139 s whether the disk is there or not |
| 47936 | Hoi Saga Demo 3 | seed 2: disks 30 s later, disk 3 never loaded | every disk loads as written |
| 169514 | Persistence Megademo | seed 3: halt | seeds 1 and 2 pass |
| 170077 | Bliss Out | seed 2: disk 2 never loaded | loads on seed 1 with any key |
| 262819 | Maximum Overdrive | seed 2: disk 2 never loaded | loads on seed 1 with any key |

## Disk in another drive (1)

| id | title | gate | evidence |
|---|---|---|---|
| 221158 | Soho | disk 3 never loaded | `drives = 2`: DF1 reads disk 2 to cylinder 71 by 190 s; disk 3 goes into DF0 at 225 s and is never read. The sweep's note: disks 2 and 3 both go in DF1 |

## Disk 1 back in (1)

| id | title | gate | evidence |
|---|---|---|---|
| 2020 | Megademo (Budbrain) | disk 2 never loaded | disk B is read at 325 s on cylinders 0 and 1 only, and the demo polls for a change again at 334 s: it wants disk A back. An entry with a second swap of `disk = 1` is refused: "no way to put in disk 1: the disks to put in are 2 to 2" |

## Wrong file run (9)

All nine entries are `result = "unknown"` and run a BBS advert viewer: a
"task held" requester at 10 s, on both seeds. The corpus names the demo of
each.

8360 Subzero, 9285 Utmost Vacancy, 32303 Smells Like Lame Spirit,
32581 Hardcore, 32583 Mind Traveller, 35129 Episode, 46968 November Light,
140969 4k Intro, 163844 Determination.

For 9285 and 35129 the corpus says a script starts the demo.

## Crashes whatever the key (6)

| id | title | gate | note |
|---|---|---|---|
| 6956 | Killing Time | alert:80000020 | both swaps load; the alert at 350 s, 16 s after disk 4 |
| 74733 | SunStone | alert:00000003 | the alert at 270 s, 200 s before the swap |
| 143747 | Fugazi | alert:00000004 | the alert at 70 s, before the swap at 75 s |
| 153780 | Mega Demo (Deathstar) | alert:0000000b | disk 2 loads without a click; Guru at 100 s. Detector today: the same |
| 156326 | Genesis | alert:80000006 | a Guru at 15 s, the machine restarts, and all four disks then load and play to 760 s |
| 221840 | Megademo (Predators) | alert:0000000b | disk 2 at 20 s loads, Guru at 60 s. Detector today: no swap, works |

## Disk never loads whatever the key (11)

`n` with no key, `lmb` and the right button. The time, or something else.

| id | title | sweep's swap | note |
|---|---|---|---|
| 747 | So What | poll, both buttons, 6 rollbacks | last read 118 s, insert at 478.7 s |
| 10374 | No Brain - No Pain! | poll, both buttons, 1 rollback | last read 128 s, insert at 221.5 s |
| 95819 | Hit The Road | idle, both buttons | |
| 112329 | Jesus on E's | reread, both buttons | reads on to 325 s |
| 116196 | Megademo IV: Devil's Key | reread, both buttons | disk 2 never, disk 3 loads with `lmb` |
| 214329 | Subliminal XTC | scheduled | `crashes-later` in the entry; nothing after 10 s |
| 223948 | Megademo 1 (BAD) | scheduled | `crashes-later` in the entry |
| 251196 | N-Tro | idle, both buttons | reads to 128 s with a click |
| 254275 | Possessed Megademo | poll, both buttons, 1 rollback | |
| 311968 | Face the Reality | scheduled | |
| 324902 | Guignols Dance 2 | idle, both buttons | `separate-disks`: each disk boots alone |

## Never comes alive (5)

| id | title | note |
|---|---|---|
| 5316 | Absolute Inebriation | `crashes-later`, no swap in the entry. Its loader races: seed 1 reads to 112 s, seed 2 stalls at 6 s |
| 263553 | Cubic Dream | `unknown` in the entry. A black screen in the ROM from 5 s, both seeds |
| 172671 | The Intruder | the disk loads with `lmb` (read to 179 s) and it still never plays |
| 244877 | Skizzo Demo | a Guru box at 340 s as the disk goes in; with a click the disk loads and nothing plays |
| 377595 | Megademo 7 | disk 3 loads at 30 s, then the Kickstart screen from 35 s |

## Error (1)

7534 Switchback: `disks = ['dd-rbs1.dms', 'dd-rbs2.dms']` fits none of the
download's variants. The media now joins the two files into one disk
(`dd-rbs1-joined.adf`); the entry is from before that.

## Player bugs

None found. The one suspected, that a disk the player puts in is not the
change the detector makes, was ruled out: today's sweep code, its detector
swapping, crashes five of the eight crashing entries tried as well
(27950, 153780, 158885, 219085, 263719) and asks for no swap at all in the
other three (154472, 221840, 244249). The entries that fail are stale, not
misplayed: the sweep they come from clicked both buttons, pulsed its
scheduled inserts and answered Gurus with its clicks, and judged the result
with the verdict rules of before Nov 2026.

Two limits of the player the run met, neither a bug: it presses the left
button only (2), and it does not put disk 1 back in (1).

## What this says of the issues that follow

Applied to the tracker on 21 Nov 2026.

- **#9 `run` names a launcher**: confirmed as it was. This run adds no count: the gate
  passes a production whose one part plays. The nine advert-viewer entries
  are `run` corrections, two of them to a script.
- **#10 key names**: changed, it gains the right mouse button (`rmb`), which
  DESIGN.md does not list: 2 productions take nothing else. Nothing in this
  run was shown to need Return, Space or fire; no entry carries one. The
  larger part is the export: 14 entries lack a left click the replay needs,
  2 have one too many.
- **#11 `drive` and `file`**: changed. `drive` stays, for one production
  (221158 Soho); `file` was dropped: no failure came from a choice of download.
- **#12 corrections by hand**: confirmed, with a note that 43 failing
  entries are outside the 84.
- **Not covered by an issue**: a swap back to disk 1 (2020); the seven
  entries that play as written and fail only late or on one seed, which
  `until` can say but the gate's fixed 30 s does not accept.
