# The "unknown" no-activity groups: what they turned out to be

Clusters are by final-screenshot hash of the best run (nacli `rows.pkl`):
`7c9c8293` = AmigaDOS 1.3 prompt `1>` (305 variants, 154 HD + 151 floppy
fallbacks of the same exes), `6e30fb0d` = CLI with no prompt (160; 83 HD).

## `1>` cluster is not "silent exit" (sample: 24 random HD variants, a500, 1500 frames)

The cluster is the *final* screen, so it also holds programs that ran and then
returned to the prompt, and Gurus whose reboot ended at the prompt.

| class | sample | share | fix owner |
|---|---|---|---|
| real immediate silent exit (alive 0, `1>` by f500) | 5 | ~21% | open (see below) |
| ran 1-3 alive samples, then `1>` | 3 | ~12% | verdict (works-short) |
| short intro, alive 3-6, ended 1750-3000 | 10 | ~42% | verdict (works-short) |
| hidden Guru 0B03800C + reboot loop (mathffp/translator.library family, 17% by strings) | 4 | ~17% | guru detector (LastAlert held, resets climb) |
| static other screen | 2 | ~8% | input |

* PowerPacker stubs (`Nupowerpacker.library` string, 6/154 HD): adding
  powerpacker.library flips 3/4 reruns to running (21693, 22839, 21723); 22095
  opens only dos.library and exits.
* The full BootPartition Libs set changed **0/24** sampled variants: lib
  population is not the cause of the `1>` cluster in general.
* 129/154 HD variants are single-file trees (standalone exe): not a wrong pick.

## `6e30fb0d` blocked at CLI

Task is the Initial CLI waiting on a DOS packet = the program reads stdin
(console handler) or waits for a key/click, with nothing printed.
Probe (RETURN, then LMB, 6 HD variants): 5/6 react (3 reach a Guru
0B03800C, 1 a random-dot screen), 1 ends at `1>`. So mostly **needs-input**
programs (issue input), some of which then Guru like the family above.

## Tools / caveats
* bp on exec.OpenLibrary works (`peek` of A1 needs a 2-pass replay) but the
  ROM polls dos.library ~1000x, 11 min per variant: not for bulk.
* `input key` needs `run frames=N`.
