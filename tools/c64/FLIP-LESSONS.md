# How C64 demos do disk flips (shared lessons for investigating agents)

Append-only per-agent sections at the bottom. Seed facts from earlier sessions:

- Most demos need no key. About half the real flips print "turn disk and press space": insert first, then one space ~15-17M cycles later. Space against disk 1 is destructive.
- Timing drifts 20-40M cycles between runs; most windows have no upper limit. PAL = 985248 cycles/s.
- Press nothing before the autostart load ends (a space at 20M broke Insomnia's RUN).
- `no-activity` is often a static picture / text page / key-wait screen, not a failure.
- Disk names like 6581/8580 or A/B alternatives are usually standalone, not a chain.
- A demo that has ended (BASIC READY, end card) makes later inserts look "accepted"; judge by whether a NEW part appears.
- Compilation sets: each production is one file on a shared disk set; boot that file (`vice.Vice(..., boot_file)`).
- VICE quirks: Sphaeristerium intro hangs (needs poke c444=46 at ~25M, key d); a REU demo requiring exactly 512 KB fails on the 16 MB REU machine; Dawnfall 7676 needs NTSC and a named boot file.
- Some demos boot side B / disk 3 first (boot_disk > 0).
- Classes: flips, standalone, collection, boot_fresh, broken.

## Agent fl2 (2026-11-13)
- Check `md5sum` of the listed disks FIRST. 333377, 289552, 336832, 332633 each listed 2 "disks" that are byte-identical copies in the same csdb mirror dir (original name + a normalized-name copy). They are single-disk productions, not multi-disk; classify standalone, no emulator needed.
- Suggested code fix: dedupe disk images by content hash in media.variants so these never count as multi-disk.

## Agent fl3 (2026-11-13)
- Same duplicate-image pattern as fl2: 200318 (3 copies), 340019 (2), 346738 (2) are byte-identical `.d64` copies in one csdb dir (md5sum). Standalone, no emulator.
- 170118 Fishing Furiously: two different images, but each has a single PRG (plain vs "packed" build). Alternatives, standalone. Quick check: `c1541 -attach X -list`; one file per disk and nearly full-size differences mean versions, not a chain.
- No emulator runs were needed for any of the four.

## Agent fl1 (2026-11-13)
- Check `md5sum` of the disks first: 323951 and 357269 were byte-identical duplicate d64s (standalone, no emulator). 356112 had two different dumps of the same one-file demo (alt versions, standalone).
- Quick triage by `c1541 -list`: two images each with one prg of the same name = alternatives. A disk with 0 blocks free + a second disk titled "dox"/docs = game + docs (Ego Trip 2 = The Jet crack), not a chain.
- No emulator runs used for this set.

## Agent fl0 (2026-11-13)
- Check md5sum of the listed disks before anything else: 3 of 4 ids had two byte-identical d64 copies (the second often a mojibake or alternative file name), so they are single-disk, not multi-disk.
- 299223 STL First Demo: a CSDb release can bundle an unrelated intro on disk 1 (Starline III). The sweep "works" verdict was on the wrong disk. `pilot.py --boot` picks disk 2 file "stl first demo", which runs fine with no flip. The verdict reports wants_disk=True there, but that is a false signal; the scroller is just a long text.
- Mistake to avoid: do not treat a "works" verdict on disk 1 as covering the whole set when the disk labels differ.

## Agent fl4 (2026-11-13)
- 291041, 348148, 362201, 344362: two non-identical d64s in one csdb dir, each with ONE prg of the same name and same block count, only the disk header/cracker tag differs (XIDEX, THC, TDD, Legion, TWA). Different re-releases of one file = alternatives, standalone. `c1541 -list` of both is enough; no emulator.
- Suggested detector: same single-file directory (name + blocks) on every image => not a chain.

## Agent fl5 (2026-11-13)
- Quad Core 178399: 4 disks are tl/tr/bl/br quarters for four simultaneous C64s (readme.txt next to the disks says so). Always read readme/txt files in the csdb mirror dir (`ls` it) before emulating; here it settled it. Standalone.
- Enola Gay 281289, Goodbye Oregon 360402, Platoon Demo 332610: two different md5 images but each has one prg of same name/size, only disk label differs (cracker/release wrapper). Standalone alternatives; `c1541 -list` was enough.
- No emulator runs used.

## Agent fl7 (2026-11-13)
- 184030, 323322, 361259, 362203: same pattern as fl4: two non-identical d64s in one csdb dir, each with ONE prg of the same name and (near) same block count; only the disk header/cracker tag differs. Alternatives, standalone; `c1541 -list` + md5 was enough, no emulator.
- Frodigi 8 (323322): both images are full (0 blocks free) with a single 9-block "boot" prg and the same header; `-fixed` is a patched re-release (8k bytes differ). Still alternatives, not a chain.
- Mistake to avoid: do not spend emulator runs when every image has one prg of the same name.

## Agent fl8 (2026-11-13)
- 119307, 183240, 345099, 336325: same pattern as fl4/fl5: non-identical d64s in one csdb dir, each with ONE prg of near-same name. Standalone, no emulator.
- Proof trick for "same file under a different name": `c1541 -attach X -read "<name>" out.prg` on both disks, then `cmp`. 336325 gave byte-identical prgs (names differ), so it is one file re-wrapped.
- Differing block counts (Just Fun 58 vs 78, Reader-Intro 3 versions 61/60/45) are cracker/fix versions, still alternatives.
- 345099 Just Fun is no-activity in VICE on PAL and NTSC; not triaged, may be a static or key-wait screen.

## Agent fl9 (2026-11-13)
- 187858 Escos 1: two non-identical d64s with ONE prg each but DIFFERENT names (Derby Day / Derby Day 2) are two parts of a game, not alternatives; here disk 1 dies with ?FILE NOT FOUND (data files absent from both dumps) before any flip. Check the last sweep screenshot text for BASIC errors; a flip cannot fix missing files. broken.
- 351326, 359135: single-prg disks (blank vs TDD header; gsg_demo vs nothing_men) = standalone, c1541 -list was enough. For 359135 the sweep ran the bundled intro on disk 1; the actual production is disk 2 (cf. fl0's 299223).
- 298793 "Scroll Machine" is really Wizardry II (A boot, B master, C scenario, custom formats listed "Empty image" by c1541). Game-driven swaps; S at menu -> BASIC `LOAD"*",8,1` hangs in VICE whether disk 1 or 3 is in. A "works" sweep screenshot with a game menu does not mean a demo chain.
- 4 pilot/prekey2 runs total; killed x64sc by PID (cmdline contains r2-scene-db-c64/roms); pgrep -x x64sc clean.

## Agent fl6 (2026-11-13)
- 331407, 343598, 343461: two non-identical single-prg d64s (same prg name, same/near block counts, different disk header or packer, e.g. "differentpack" in the file name) = alternatives, standalone; `c1541 -list` suffices, no emulator.
- 364571 Plasmarocity (csdb 4937) is really the game crack "Tongue of the Fatman" (cracktro "Mongu's Fight Palace"): both sides are custom-format trackloader images (side 2 lists as "Empty image", 0 blocks free). Intro waits for space (~60M); the game then runs. x64sc dies on its own at ~320-357M cycles in every run: classify broken.
- VICE quirk: this x64sc may die right on a key press (one run died at the space at 60M). Do not mistake it for the demo's doing; check the same run twice.
- Mistake to avoid: a sweep "probe" insert at ~13M (waiting_since while the intro still loads) says nothing about the real flip.

## Agent fl11 (2026-11-13)
- 286685 House Party: 3 listed d64s = 2 identical (md5) + a different release with another file (59 vs 68 blocks). Standalone alternatives; md5sum + `c1541 -list` was enough.
- 205327 Baertige: one 73-block file on side 2 of "Willow 2004 Partydisk" (2 sides, entries listed with `----` separator del lines). Collection; also a stray `.t64` in the csdb dir.
- 39420 Meat Krest = Mean Streets (Access game) crack on 4 disk sides; crack shows a Nostalgia scroller intro and a trainer menu with START GAME preselected. In-game swaps are gameplay-driven; not scriptable. The sweep "works" is only the intro. Same shape as fl9's Wizardry II.
- 196768 Mental Hangower: music collection on 2 sides, works only on NTSC (PAL: no-activity). Menu (Collection/Intro/Note) ignores space and p2fire; Return on "The collection" gives a black screen with idle drive for 240M+ cycles. Unresolved: try cursor Down/1/2 keys (xinput.Keys.SYMS lacks them; setdefault name->name works for letters/digits only, `Down` needs adding) and NTSC.
- Mistake to avoid: the first screenshot of a run can differ between runs (Mean Streets showed the trainer menu in pilot, a scroller intro in prekey); judge on several shots.
- 5 prekey/pilot runs on 196768, 3 on 39420; no x64sc left behind.

## Agent fl12 (2026-11-13)
- 58690 Basic Rlt Compo (one 2-block BASIC file on a party compilation disk 2) and 205099 Structural (one 121-block prg on compilation disk 2): collections, boot_disk=1 + the file name; both run with no flip. Sweep "works" on 58690 was disk 1 (an unrelated adventure). A d64 image with error-info bytes appended (175531 bytes, 001a.d64) hung at LOADING; the clean copy of the same file on another disk booted.
- 367893 Kilju (Conquestador crack, 3 disks main/game/save): intros need two spaces (~100M and ~300M cycles) to reach the game menu (~400M). Game (main) file lives only on disk 2, so a flip is likely once a game starts, but the player-setup screen (F7) was not passed. Not resolved.
- 355205 Farewell! (ICOSD0-6): front-end disk 0 goes straight to "Game Over" on any key under VICE; never asked for a disk. Not resolved.
- Tooling: fine sampling (run_for 0.003-0.02 s, screenshot md5 change detect) is the way to see short prompts; the stock sample step (0.1 s ~ 10M cycles) can skip a short "insert disk" screen. Add SYMS "F7" etc. by monkeypatching xinput.Keys.SYMS. Bitmap/sprite text is not in screen RAM $0400; use screenshots, not peeks, to read it.
- Mistake to avoid: screenshot-per-change on animated intros produces hundreds of PNGs; sample every N cycles instead.

## Agent fl13 (2026-11-13)
- 268593 Out of Contex: a real flip the sweep missed. TURN DISK screen (a big "TURN" logo over a floppy) appears ~154-180M cycles and stays 400M+. Insert side B at 230M, space ~17M later; new parts (car, tunnel, cube) follow. Inserting at 154M (before the prompt, mid-load) hung on a pink screen with one "e": never insert before the TURN screen is up. Method that found it: run with NO insert for 600M cycles with a screenshot every 25M (pk.py copy with --maxc) and read the contact sheet first, then insert.
- 279855 Electrosound History Book: sweep verdict was ?FILE NOT FOUND because disk 1 of the list is "Bonus Goodies side 1"; the real prod is disk 3 (use `--order 3,1,2` in prekey). Title card waits for space (~100M), then a music player; drive idle after 72M. Bonus disks = loose tune PRGs. Standalone.
- 173898 Cascade: three d64 where two (intro.d64, paralax.d64) are single-file dev parts from source subfolders (csdb dir has datafiles/); disk 1 alone is the whole demo (drive idle after 71M). Standalone.
- 167513 "War of the Worlds" is Mate In Two, a chess game with problem files spread over 3 disks (001-130/131-270/271-315). User-driven; not scriptable with our keys.
- VICE/xinput quirk: each `press` (including numpad joystick keys via SYMS monkeypatch KP_6 etc.) costs ~12M cycles of emulation, so cursor navigation by joystick taps is far too slow; hold-key support would be needed.
- Tip: prekey.py only prints drive changes after the insert; a copy that prints them always (pk2.py) shows whether a demo ever touches the drive again, which is a cheap "no flip" proof.

## Agent fl15 (2026-11-13)
- 167020 Candle Wax, 53903 Just One Screen, 196150 Digi-Riffs: csdb dirs with 3 d64s that are wrapper variants / unrelated bundled releases (Bill Gates Gut crack, Interjam'98 compilation, x01 extras disk); every image carries the whole production (both parts) on one disk. Standalone via `c1541 -list` only.
- 168685 Melangerie Mediocre: production is disk C ("myd 2013", = myd-bcc2013.d64, identical md5) of the BCC#7 partydisk A/B/C; loader + parts 01-06 all on C, runs 150M+ cycles with no swap. pilot --boot finds no match because the file is "melange.mediocre" (dot). Run one disk alone with a dataclasses.replace(variant, disks=[...], boot_disk=0) + runner.run script (fl15/one.py in the scratchpad).
- 4 emulator runs (1 pilot, 3 direct); no x64sc left behind.

## Agent fl14 (2026-11-13)
- 346133 Multiverse 100% (4 sides, X'24) is a real chain: the plain pilot.py --minutes 24 found all three flips (polled "FLIP DISK" pictures, accepted, no key). Waits at ~252M/486M/798M, inserts ~80M later (332M/565M/877M). Untouched by the sweep before only because no flip was recorded.
- 336216 "Moon Music Collection" = The Wrath of Denethenor crack (title is a mislabel); 349958 "Testicle Drive" = Elvira (Czech, Flair); 359538 "Strive" = Perfect Score SAT prep (12 independent boot disks). Titles can be wrong: always look at the disk listing / header / sweep screenshot first. Games with "Please insert disk side #3 and press RETURN" ask from gameplay, no scripted window: standalone.
- Elvira CZ in VICE: without key the pilot ends in BASIC garbage ~210M. Intro key n (~60M), then p2fire (not p1fire, not space) at >285M starts the game. p1fire is not accepted by every title; try p2fire.
- Wrath: key 2 at the menu (~60M) leads to a "insert side #3 and press RETURN" prompt around 900M.
- Tooling: other agents' x64sc show up in pgrep; check the process age/ppid before assuming a leftover is yours. All my runs ended on their own.

## Agent fl10 (2026-11-13)
- 166545 Algo Dreams: real 4-side flip, "Turn Disk" picture card, no key; insert ~80M cycles after the card (disk 2 at 295M, disk 3 at ~494M). Disk 4 never accepted in VICE (garbled bitmap stuck); x64sc died once right after the disk 3 insert.
- 318272 MADLIB Vol 1: music-disk player with 20 data disks; the flip is "insert, then F1 ~20M later" (list changes). F1 is not in xinput.Keys.SYMS: add SYMS["F1"]="F1". Looks like a collection, but a real key-driven flip.
- 160815 "Beatnik" is really Onslaught's Deadlock Preview (dev versions on 2 disks) = standalone. Its Y/N trainer prompt only appears after the autostart load (~100-160M); a key at 40M/60M broke the load (screen: READY. with no run). Press y/n >= 160M.
- 58418 csdb 162 is a tools collection (Jergan div code), not the production: check the mirror dir name against the title.
- Tooling: pk3.py (prekey2 + `--more CYC:DISK,...` extra inserts and `--morekeys`) in the fl10 scratch dir. Do NOT poll with `until` loops in the foreground bash: they hit the 600s timeout and leave orphaned loops; use hc wait on the named terminal.

## Agent fl18 (2026-11-13)
- 171331 Wavey and 312560 Last Dance: the production is ONE disk named like the title (wavey.d64, last_dance.d64) shipped next to unrelated compilation/artwork sides in the csdb dir; sweep "works" ran disk 1 (wrong disk, same as fl0/fl9/fl15). Boot the title-named image alone (`dataclasses.replace(variant, disks=[...], boot_disk=0, boot_file=None)`, one.py in fl18 scratch). Standalone.
- 178171 CCCP Smessel II: collection disk + a re-release disk containing the byte-identical prg (`c1541 -read` + cmp). Standalone.
- 376425 Audial Extreme: 4-side music disk; side "d - Start_Side" (listed last in the dir) holds the menu, sweep order a,b,c,d boots the wrong side. Boot d first (`--order 4,1,2,3`), Return at ~41M, player up by ~85M. Inserting side a plus space/Return gave no drive activity. In one run Return led to a grey screen for 800M+; same keys, ~100K cycle difference, so menu timing is fragile.
- Tool tip: prekey2 `--at <huge>` plus `--pre` is a no-insert run; a copy of prekey that prints drive activity always would settle "does the keypress load anything" (not done here).

## Agent fl17 (2026-11-13)
- 204034 Deep (Pride): real flip, but the demo is key-gated through ALL side-A parts. n (trainer y/n) at 30M, then one space per part (~every 100M from 45M to 940M); "PLEASE FLIP DISK OVER !!" appears ~1000M; insert side B at ~1100M, one space ~19M later loads side B (effect-menu part). Window needs ~10 pre_keys.
- VICE quirk: detach/insert while the drive is busy loading (drive reg f0 or the like) killed x64sc twice (monitor closed) at 563M and 653M. Insert only after the flip prompt is on screen.
- 206217 Viper Designs: 5 disk images were 3 identical md5 + 2 other packs of the same 2-part demo; part II loads from disk 1 after a space at ~120M. Standalone.
- 357973 Incest = Wizard's Crown crack: prompts "INSERT GAME DISK(FRONT)" and "INSERT DISK1" alternate; no flip script found (like Wizardry II in fl9). 355215 Just Alf = Dungeon! game + scenario disks, standalone.
- Tooling: seq.py (scratchpad fl17) takes a list "cycle:key" / "cycle:insN" events to script several inserts and keys in one run; sheet.py builds a contact sheet from a shots dir (PIL available): read the sheet first, then single frames.

## Agent fl16 (2026-11-13)
- 346986 Dodger (SOTE German RPG, NATO): a game whose three sides are A game / B data / C save in custom format. It asks for disks by TEXT in its own message line: "BITTE DISKETTE:C" (~540-575M cycles, after the story pages each need a space), then after C is in, "BITTE DISKETTE:B"; insert disk 3 at ~640M, disk 2 at ~720M and the game starts. The sweep's generic probe never saw this because the story pages need spaces first. Tip: when a game pauses on a text intro, space every 60M, then read the screenshot text.
- Tooling: copied prekey2.py to fl16/two.py with `--ins CYCLE:disk,...` for a second insert (insert two disks in sequence).
- 171243 Late Xmas: 3 d64 = 3 independent football-tournament programs (Em 88, Euro 1992, Euro 88/Italia 90). Standalone; ran each disk alone with `--order`.
- 50092 Topless: Normal/Party version d64s, same files; standalone alternatives.
- 359147 Blaa (Scream): disk 1 is a long chain of key-driven parts (space, groupname prompt "enter your groupname" accepts any letter + Return, instruction page needs Return, then space per part). Each run to 1.5G cycles takes ~15 min wall; did not reach the flip in 7 runs. Never found a TURN DISK prompt; the final Scream scroller runs 1.5G+ cycles. Mistake: inserting disk 2 at fixed cycles against intro parts only shows drive blips, not a flip.
- Tooling: contact sheets (PIL, 0.4 scale, 6 columns) of every Nth screenshot are the fastest way to read these runs. No x64sc left behind (pgrep shows only another agent's).

## Agent fl19 (2026-11-13)
- 294235 Summer Games II crack (XAKK): intro needs space ~60M, then d (fastloader prompt) ~90M, n (reset records) ~120M, game menu ~150-250M, then name/country entry. The sweep stopped at the FastLoader prompt (key-wait) and called it works. Swaps are gameplay-driven: standalone.
- 126530 Justice (Laser Inc.): space advances every part; at ~290M an instructions page wants Return, and Return KILLS x64sc (2 of 2 runs, reproducible; only p1fire/p2fire left to try). Disks 1-1/1-2 are two sides, 2-1 is a one-disk re-release.
- 126542 Air Dance II: booting side 2 first hangs at a static logo card after ~207M with the drive idle; space, inserting side 1, and the alt loader "metal max-g load" change nothing. Unresolved/broken.
- 201706 Rigid: menu key 1 opens a song list; drive stays busy after any insert but nothing visible changes; cannot confirm playing without audio or cursor keys. Unresolved.
- Tool tip: `PRE=$(python3 -c "print(','.join(f'{c}000000:space' for c in range(100,700,40)))")` gives a space every 40M; hash screenshots (md5) to find where the screen stops changing instead of viewing hundreds of PNGs. A tiny PIL contact-sheet script (3 columns) saves reads.
- Mistake to avoid: spaces pressed before the demo expects them are harmless, but Return in x64sc may crash the emulator; check the traceback "monitor closed" before blaming the demo.

## Agent fl21 (2026-11-13)
- All four ids standalone, decided without an emulator from `c1541 -list` + `-read` + `cmp`: 350177 Metal Warrior 2 (disk A original, disk B "plus" trained version, each with the full level file set); 356889 Kult (compilation disk065a + a single-demo disk with a byte-identical prg); 356910 Excellent/Russia (game disk + two "sg" save-game disks, used only from in-game save/load); 357401 Contact HTG (two different single-prg copies).
- Tell-tale signs of non-chains: both disks contain the same file names; a disk labelled with a different disk id ("sg") holding only save slots (svN); a compilation disk next to a single-production disk.
- Mistake to avoid: sweep "works" on a multi-disk csdb dir only says disk 1 ran; with a compilation as disk 1 it may not be the production's own disk.

## Agent fl20 (2026-11-13)
- 349660 Sagor (Conan adventure, 3 disks of chapter data) and 331665 The Hobbit (disk B = empty save image): game cracks, swaps gameplay-driven, standalone. 350800 Pick That Tune: program on disk 0, disks 1/2 are extra category data files chosen by the player; standalone. Quick tell: later disks with only data/"game" seq files or "Empty image" = game data/save, not a demo chain.
- 357667 Beach Party: csdb dir has the real demo disk plus a bigger group compilation containing the same file names; sweep ran the compilation (disk 1). Boot the title-named disk alone with fl18/one.py (order 2): runs 150M cycles, no flip. Same pattern as fl0/fl9/fl18.
- 1 emulator run; no x64sc left behind (another agent's x64sc showed up in pgrep).

## Agent fl23 (2026-11-13)
- 363137 Bugs Bunny Show 2 = one file on side B of a German diskmag (CCA Clubdisk 4); side A is texts. Collection, boot_disk 2 + file "bugs bunny 2/bcf" (boot_file via vice.Vice(..., boot_file)). Runs without flip, drive idle after 92M.
- 365845 Samples-1: disks a/b are two independent sample players (each with own menu and its own samples), standalone; b is a 175531-byte image (error bytes) that nevertheless booted here.
- 348797 First Aid+ = Passeggeri del Vento (Infogames adventure) crack; disk 2 holds later episode files, requested from gameplay. Standalone. The sweep "no-activity" was just a plain yellow first frame.
- 358442 Deus Ex (Falcon Soft, 2023): start disk shows the logo loop until space (~300M), then a joystick-port-2 pointer menu with "Play Intro" (the 2nd disk is "intro disk"). Unresolved: pointer is a sprite, one numpad tap = ~12M cycles and moves it off screen; need held joystick / proper mouse to click. The pilot's "flip" there is meaningless (inserted into a black loading screen).
- Tooling: fl23/pk.py in the scratchpad takes `--ev CYC:key|insN,...` (KP_1..9 map to port-2 joystick, Down/Up/F-keys added via SYMS) and saves a screenshot after every event; sheet.py + md5-change listing of a `--every` dir is the fast way to read a run.
- Mistake to avoid: `prekey2.py --at 2000000000` runs a 2G-cycle no-insert pass (~30 min wall); use pk.py with --end instead.

## Agent fl25 (2026-11-13)
- 338543 The Digital Brain 2: a menu-driven digi disk. Sweep only saw the intro scroller. space ~142M ends the intro, menu at ~150M; F3 (Brian Part 3) loads then shows a black screen with "FLIP DISK * PRESS SPACE !" at ~205M; insert disk 2 ~245M, space ~25M later; disk 2 (fake directory, 0 blocks free, 626 data sectors) then loads continuously for 600M+ cycles with the menu picture frozen. F1 plays from disk 1 with no drive activity. New visible part not confirmed (menu screen unchanged until 900M). Key lesson: when the sweep "works" on a key-wait intro, press space before concluding no flip, then try each menu key.
- 367872 Braggin' Dize = World Games crack (event files on disks 2/3, gameplay-chosen): standalone. 357405 Perfect Timing: two copies of one prg (1 byte differs): standalone. 368857 Day Of Darkness: menu disk + 22 single-game disks with identical loader: collection.
- Mistake to avoid (tooling): `hc run --bg` children did not inherit exported SCENEDB_ROMS/WORK in my first run (x64sc died at startup, "monitor closed"); set the env inside the `sh -c` (e.g. `. env.sh;`).
- Tip: copy pk.py (fl23) and change the sys.path worktree to your own; contact sheet with PIL beats viewing frames one by one.

## Agent fl24 (2026-11-13)
- 344445 Carmen Sandiego USA (side 2 = "please boot other side" dummy dels, game data), 345987 Summer Games (G64+2 d64), 339076 Abstract D-mo #1 (compilation + identical prg on disk 2): all standalone (games / alternatives), decided by listing + cmp, one attract-loop emulator check.
- 362837 Hondani Meetro 2024: side A starts with a fake "AI chat" REPL where EACH KEY PRESS TYPES ONE CHARACTER of a script (~45 chars; space works, 15M cycles apart, 100M..990M) before RUN starts the demo. Sweep keys only typed a few characters, so it never got going. Then ~2G+ cycles of parts/scroller with no TURN DISK; inserting disk 2 triggers only an ending sequence ("THE SUN IS GONE") then BASIC. Unresolved.
- Tooling: `hc run --bg` does NOT inherit exported env; pass `env SCENEDB_ROMS=... SCENEDB_WORK=... python3 ...` inline or the run fails with "Couldn't load kernal ROM". `hc wait` times out at 600s; just call it again.
- Mistake to avoid: an "accepted" insert that immediately produces an end card is not evidence of a flip.

## Agent fl27 (2026-11-13)
- 348108 Explorers v3 (two one-prg d64s, 13008 vs 13007 bytes), 349996 Legendary Oldies #02 (side 2 = text seq files only; scroller idle on the drive after 40M), 367143 Muzak Disk no 1 (disk 2 = ripp#21-40 loose tune prgs; intro never touches the drive after 31M, spaces to 450M): all standalone.
- 357184 No Way Out: csdb dir has an unrelated Fear release as disk 1 plus two images of the real demo. Part loader asks for the part by file name, so "NoWayOut.Fear.d64" (names "part 2/fear.....") dies to BASIC READY after the first space while "No Way Out_FEAR.d64" runs: when a run lands in READY with the drive toggling d2/da at pc e5xx, try the other image before calling it broken.
- Tooling: `sheet.py` in tools/ crashes without an output extension; pass `out.jpg`. Own copy at the fl27 scratchpad.

## Agent fl22 (2026-11-13)
- 343317 Reluge 101%: two byte-identical d64 + an extras/notes/soundtrack disk. Standalone. 357935 ECG in Radio 1: duplicate + re-release of one 198-block prg. Standalone. No emulator.
- 349280 Dentagardo: autostart of the first file ("-->dentagardo<--", BASIC SYS 2049) ends at READY/blank blue in VICE, but pilot called it "works". Booting file "1-a new megademo" runs the demo. A real card "Insert Side B, and Press Space" appears ~400-440M after 5 spaces (100/161/220/281/340M). Insert + space ~19M later drops to READY (drive loops e5xx, no part 9). Unresolved.
- 366535 Revolution (TNG): intro waits for space at ~60-100M; parts advance with a space each ~60M; then a digiload text story runs >2.2G cycles. x64sc died on a key press in 2 of 5 runs (same inputs sometimes survive). Flip not reached.
- Tooling: copy prekey.py with `--boot FILE` (vice.Vice boot_file arg) and `--end CYCLES` (otherwise `--at huge` never ends, it ran 4G cycles); a contact sheet (PIL, every Nth shot) per run is the fastest read. Do not `pkill -f prekey` from the same bash command line (it matches and kills your own shell). `hc run --bg` terminals do not inherit `export`; prefix `env SCENEDB_ROMS=... SCENEDB_WORK=...` or the emulator fails with missing kernal.

## Agent fl29 (2026-11-13)
- 386374 Wobbler Music (compilation + single-prg disk, cmp identical prg) and 331559 Cxart II (2 md5-identical + 1 re-headered copy): alternatives, standalone. 339092 "We're out of this World" is really Math Blaster (program disk + seq data disk): standalone. 336678 Wrong Bus: 4 G64 of Movie Maker (program/movies/shape libs), menu-driven tool: standalone, playback not verified.
- Mistake to avoid: snapshot db `flip` table has no variant_id column here; use `.schema` first. No emulator used.

## Agent fl28 (2026-11-13)
- 357558 Questron II crack, 353156 Conquest of Amy (text adventure + chapter picture disks), 347321 Win Lose or Draw (game + quiz data disk): game/adventure disk sets, swaps from gameplay: standalone, decided from `c1541 -list` + the sweep screenshot, no emulator. Titles of these are mislabels (profane title, different real game).
- 336821 Digi View (Warriors): demo parts advance one per space (~100M, 220M, ... last ~380M) with black music parts in between; it ends in BASIC with garbage. Side B has a garbled directory (0-block files, PETSCII-junk names) and does not boot (LOADING, READY.). Standalone; the sweep "works-then-crash" came from the probe insert into a running part (x64sc exited ~20M later), same quirk as fl17.
- Mistake to avoid: reading a long black screen as a prompt; sample screenshots at fixed intervals and map them to the key times before concluding.

## Agent fl26 (2026-11-13)
- 322083 Soundtrack of Mutants (compilation disk + single-file disk, alternatives), 308466 Hi-Fi Music Box (disk 1 is a 2278-byte junk file, not a d64: `c1541` says unknown GCR image; check `ls -l` sizes), 346097 Crazy Toaster II (Scooby Doo adventure + 4 chapter data disks): all standalone, no emulator.
- 333397 Depression (Fantasia): BASIC wedge "FANTASIA-BASIC V9.9 / READY FOR DEPRESSION ?" needs key y at >=170M (sweep stops there; its idle flip probes mean nothing). Every part then sits at "PRESS SPACE FOR THE NEXT PART": one space per ~40M from 230M to ~910M gets through side 1 a-h. Part i = "i.diskchange" (text "REMEMBER 2 TURN DISK B4 U LEAVE"); after the last space the demo drops to a bare READY. and stays; inserting side 2 + space there did nothing. Unresolved; try inserting side 2 at the last prompt BEFORE the final space.
- Tooling: sampling every 2M cycles (--every 2000000) with md5 change detection finds short screens; pk.py filename by 100k cycles. hc kill of the pilot leaves the x64sc running? check `ps` parents; other agents' x64sc show up in pgrep.

## Agent fl33 (2026-11-13)
- An "accepted" flip with no drive motion after the insert (`read_after` False) came from `moved_on`: the keys the runner presses (space, p1fire, p2fire) advance a waiting game menu from memory (Summer Games 345987). Real flips found so far (Algo Dreams, Multiverse) are accepted by `read_after` within ~3-6M cycles of the insert, no key.
- Fix on branch fl33 (6187c20): `moved_on(..., until=first_key_at)` ignores screens after our own first key press.
- Method: copy pilot to dump `log.samples` + flips to a pickle, then evaluate `read_after`/`moved_on` offline per flip; no extra emulator runs needed to compare rules.
- Shell gotcha: `hc run --bg ... sh -c` does not inherit exported SCENEDB_ROMS/SCENEDB_WORK; export inside the sh -c string or the emulator cannot find the kernal ROM.

## Agent fl30 (2026-11-13)
- Never read the screen at 0x0400: demos move it. Screen = (3-(dd00&3))*0x4000 + ((d018>>4)&15)*0x400 (Dodger prompt at 0x7800, story at 0x5C00). Now `Vice.screen_ram()`.
- Monitor default view hides RAM under I/O and reads I/O only when banked in: use `bank io` for $DD00/$D018 and `bank ram` for screen/memory dumps, then `bank default` (`Vice.peek(bank=)`). `m ram:0400` syntax does not exist.
- Prompts can be inverse video (codes +0x80): mask bit 7.
- Find a drawn text in an unknown charset: dump 64K via `bank ram`, search for a window whose repeat pattern equals the string's (e.g. BITTE DISKETTE:C).
- The prompt only exists after the keys the manual window presses (Dodger story spaces, DB2 space+F3), so a text detector cannot help a generic run that presses nothing.

## Agent fl36 (2026-11-13)
- 201706 Rigid (sample music disk, sides A-F): side A = player only, sides B-F = songs. Menu key 1 (~100M) lists songs of ALL sides; insert side B then Return (~38M later) loads the selected song ("NNN wait..." counter, then credits). Space and fire do nothing. A music disk whose player lists tracks of other sides is a user-driven flip, not just a collection; insert + the player's select key is the window. Check by pointing the cursor at a song from another side.
- Don't judge "drive keeps toggling" (drive port f0<->f8 every ~1M, pc in ROM idle loop) as loading: look at the screen, a still list with toggling drive is idle.
- 358442 Deus EX: a static logo ("works" in sweep) hides a mouse-pointer menu that only appears after space (~212M, p2fire alone does not). Joystick-as-mouse via xinput: one press holds ~12M cycles and overshoots (arrow left the screen after two KP_3). A short-hold press is needed in xinput (HOLD is 0.4 s wall) before pointer menus can be driven.
- Budget: contact sheet of a 900M no-key run (every 45M) tells in one look if anything ever changes; I used 10 runs, 2 too many, on pointer experiments that need the xinput change first.

## Agent fl38 (2026-11-13)
- 355205 Farewell! is a real game ("It came on six disks!", 2004): space on the title makes the player die within ~10M cycles ("Game Over") and the title returns; disk requests are gameplay-driven. Standalone. Check `strings` on disk 1 for message texts ("Insert ... Then press space", "Game Over", "Hit a key to start") before burning runs.
- 367893 Kilju/Conquestador: a menu game; F3 prints a text prompt ">>>PLEASE SAVE-GAME-DISK" and any key returns to the menu, F4 lists the inserted disk. In the 4-player setup screen each TYP key sets that player and advances the pointer (n = none, m = human then name letters + Return + level digit); no key I tried (space, F1, F7, Return) starts the game. Swaps are menu/gameplay-driven: standalone.
- 359147 Blaa: directory check shows parts 5-6 only on side 2, so a flip exists, but after ~640M cycles the drive is idle and the Scream scroller runs to 1.6G; keys space/Return/F1/fires and an insert at 1504M change nothing. The csdb variant mixes two 2-disk sets (Side1+Side2 and _a+_b); split them.
- Tooling: `pk.py --every 10000000` plus a PIL contact sheet (md5-uniq the files first) is the quickest read; `hc wait` caps near 120s in a foreground Bash, so wait with `timeout 110 hc wait NAME --timeout 100` repeatedly.

## Agent fl39 (2026-11-13)
- Digital Brain 2 338543: a menu demo can need MORE than the flip: after the prompt part (F3) and the insert the menu just returns; the disk 2 content is reached by another menu key (F5 -> 'The Death Trousers'). Control: F5 on disk 1 alone does nothing, so that proves disk 2 matters. When a flip shows "nothing new", try the other menu entries after the insert before calling it unverified.
- A continuous c3xx drive-toggle loop after an insert is a part's loader wandering, not new content; judge by screenshots.
- flip_window cannot store "key N cycles after the insert" beyond the single `key`; Digital Brain 2 needs F5 ~55M after the insert.
- prekey2 --after counts from the insert; with --at huge it runs for ages (3 runs wasted 2.3G cycles). Always set --at to a real value.
- Air Dance II 126542: the logo hangs with the drive idle, so inserting side 1 is irrelevant; NTSC makes it a blank screen. Crunched part, no key found.

## Agent fl37 (2026-11-13)
- "Return kills x64sc" is a misattribution: the machines run with -jamaction 5, so any CPU JAM (main OR the 1541 CPU) exits the process. 126530 died once with "1541 (8) CPU: JAM at $0029" and survived the same keys another time; 196768 NTSC died once at 22M with no key ("Main CPU: JAM at $FF09"). Timing-dependent, repeat the same run before blaming a key. Since fl37's commit, run.crash = "jam" and detail starts with the JAM line (the old 600-char tail only held the shutdown dump).
- Keys sent during a drive-code upload/fastloader start (e.g. a load beginning ~403M in Justice) are the likely JAM trigger; avoid pressing while the drive port changes.
- A black screen with $D011=0, default IRQ vector and idle drive after a menu Return is not a jukebox playing: SID regs were static (peek $D400-$D418).
- In multi-part scene demos, space skips parts: sampling the screenshot md5 every 10M shows when a static page (e.g. an instructions page) is reached.

## Agent fl34 (2026-11-13)
- 333397 Depression: side 1 ends (after i.diskchange + a space, ~963M) in a bare BASIC READY with the drive still inside the demo's fast-loader code. Inserting side 2 and pressing space does nothing; `LOAD"*",8` hangs at SEARCHING FOR *. Monitor `reset 8` (drive reset) + insert + typed `LOAD"*",8` + `RUN` loads side 2 (part j runs). So "insert at READY does nothing" can mean the demo expects a manual LOAD, not that the disk is not accepted. A manual.json window cannot express drive reset/typed text.
- 349280 Dentagardo: same "card -> space -> READY with no drive activity" pattern, but the screen editor is trashed ($D5=0x4f, cursor off), typed text does not appear. Do not read a keyboard wait loop at pc e5cf/e5d1 as "waiting for disk": it is just READY.
- Tooling: put text into the C64 key buffer from the monitor: `> 0277 <petscii bytes>` then `> 00c6 <count>` (max 10 chars unless `> 0289 28`); `reset 8` resets the drive only; `m dd00`, `m 0400`, `m 00d1 00d6` show the screen editor state. All VICE monitor commands go through `Vice.cmd` while stopped.
- Wall time: ~1000M cycles takes ~3 min under hc run --bg, much faster than the 15 min earlier notes feared.

## Agent fl31 (2026-11-13)
- 268593 Out of Contex: the "TURN DISK" wait is a drive that toggles only the MOTOR bit every 2-5M cycles for hundreds of M (loader polling for a disk change), not a frozen port. Old trigger saw an active drive. Fixed in code (swapwait.pulse_since, branch fl31 commit 04cefc0): >=4 motor-only flips <8M apart = poll; after the insert the motor bit is ignored when judging "read" because the pulses go on until the demo reads. Pilot 8 min: disk 2 accepted at 320M, no key.
- 204034 Deep: runner.answer_key now answers "(Y/N)" with n and "press space" text with space, which takes it past the trainer into the key-gated parts. The remaining parts have no readable text; a space on a still screen is too weak and inserting mid-demo wedges the next load (blue empty screen with one dot). No generic rule found for those; keep the hand window.
- Drive-trace trick: run a single-disk variant (dataclasses.replace(variant, disks=disks[:1])) and print drive port changes plus distinct screen md5 per 50M; shows polls, blips and still screens without any flip noise.
- `hc run --bg python3 ...` does not inherit exported env vars: use `env SCENEDB_ROMS=... SCENEDB_WORK=... python3 ...`, otherwise the run has zero samples and a confusing IndexError.
- Baseline check without touching the tree: `git worktree add <dir> <commit>` and run pilot there.

## Agent fl32 (2026-11-13)
- A false early flip is harmful, not just wasted: inserting then pulling a disk while a part is only playing can garble the demo so the real prompt later is refused (Multiverse 346133 disk 4: 3/4 in the sweep, 4/4 when disk 4 is vetoed until 780M). `runner.run` now retries once with the refused disk vetoed to insert+120M after a real flip.
- The animated-poll rule (motor on, port frozen, 75M) fires on real flip cards too; insert-waiting_since = 78M for all real Multiverse/Algo flips, so a threshold cannot separate a card from a playing part. Do not raise it blindly.
- `hc run` shells do not inherit exported SCENEDB_ROMS/WORK: set them inside `sh -c`, or VICE says "Couldn't load kernal ROM" and every machine errors.
- Check the db before trusting a brief: snap4/scene_v8 already had 3/4 for both productions.
- Algo Dreams 166545: x64sc exits ~70M cycles after the disk-3 insert (pal 597M, ntsc 637M); disk 4 is still unreached.

## Agent fl35 (2026-11-13)
- 366535 Revolution (TNG): the 4 listed d64s are two wrappers (Revolution_SA/SB and TNG ...-s1/s2) of the same 2 sides, identical file contents. `c1541 -read` + md5 of the big files shows it. Code now drops such copies in diskset.distinct (content fingerprint, only when the listed files account for the BAM-used sectors; fake-directory trackloader disks like Multiverse 346133 must not match each other: 1-block dummy files, raw tracks).
- Revolution story: key-driven, one space per part, even the long scroller story (idle drive from 615M, no TURN DISK ever). With disk 2 in at 1304M, spaces at 1361M and 1441M advance to new parts and the second one touches the drive. Not proven that disk 2 is needed (no control run). 4 of 8 runs never left the first picture with the same keys (key ignored at 100M, drive idle at pc cc3x), 1 run killed x64sc on a key press: repeat the first space until the drive starts loading.
- Side B of Meetro 362837 is not bootable (no BASIC stub) and holds 25 a0..e4 files + ti/f6: it is data for side A's loader. Untested lead: files named f5 (A) / f6 (B) look like function-key parts.
- Tooling: `save "file" 0 0000 ffff` in the monitor gives a RAM dump (v.cmd), `resourceset WarpMode 1` needs quotes ("WarpMode" 1); drive-change counts per 100M cycles in the log are a fast "is it loading" signal.
- Mistake to avoid: after changing media code, scripts that use `--order 3,4` against the old disk list fail with IndexError; use explicit image paths in a driver.
