# Amiberry snapshot

Snapshot of **Amiberry v8.2.2** (upstream tag `v8.2.2`,
https://github.com/BlitterStudio/amiberry), the full (WinUAE-synced,
cycle-accurate) emulator — **not** the Amiberry-*Lite* performance fork the
project used before (issues #73/#74). Lite's optimized chipset mis-rendered
copper-heavy effects (e.g. the Rink a Dink Redux plasma dropped its lower-right
to black, upstream amiberry#1211); v8.2.2's mainline chipset — the accurate
model that used to live on Amiberry's `preview` branch — renders them correctly,
matching WinUAE and real hardware. No vendoring/subtree ceremony — patch in
place, and keep this file current when deviating from upstream.

## Stripped from the snapshot

- Top-level dirs with no build references: `android/`, `libretro/`, `docs/`,
  `tests/`, `.github/`, `.git*`.
- `external/capsimage/` — the SPS/IPF decoder library (non-commercial licence,
  GPL-incompatible; only `dlopen`'d at runtime as an optional IPF disk plugin
  the harness never uses). Its CMake hooks are guarded so the build is graceful
  without it (`cmake/Dependencies.cmake`, `cmake/linux/install.cmake`).
- `whdboot/game-data/whdload_db.json` — a 6 MB WHDLoad database we never touch.
  The `whdboot/` dir itself is kept because the Linux build's POST_BUILD step
  copies it (as are `debian/`, referenced by the Linux install rules).

Kept despite being unused by our config: `src/pcem/`, `src/ppc/`,
`src/qemuvga/`, `src/mame/`, `src/jit/` — each is referenced unconditionally by
the build (e.g. the ImGui GUI's `rom.cpp` includes `pcem/paths.h`) even with
its `USE_*` feature off, so removing it breaks the build.

## Local patches on top of v8.2.2

- `src/dbgproto.cpp` + `src/include/dbgproto.h` — the headless batch debug
  protocol (`--dbg`), unchanged from the Lite snapshot. Repeated
  `--dbg "<cmd>"` argv commands execute in order, one NDJSON result line per
  command on stdout. Commands: `warp on|off`,
  `run frames=N | until=bp|audio-dma|watch max=N`, `peek ADDR SIZE`, `regs`,
  `status`, `screenshot PATH`, `bp set|clear ADDR`,
  `watch set ADDR SIZE | watch clear`, `disasm ADDR [N]` (raw
  opcode words — disassemble host-side with capstone), `load ADDR PATH`,
  `disk swap-next|insert|status|autoswap on|click|off`,
  `display measure on [os=ADDR] | off | status`,
  `trace PATH`, `state save PATH`, `pcs [N]`,
  `input mouse BTN down|up | mouse move|rel X Y |
  mouse click|doubleclick [BTN] | joy PORT BTN down|up | key CODE down|up`
  (inject input for game testing — trainers wait for mouse clicks; button and
  key state changes land immediately, so sequence them around `run frames=N`
  to model press durations; `key` takes an Amiga rawkey code). `joy` PORT is
  the Amiga port (0|1) and BTN is `0-2` or
  `fire|2nd|3rd|up|down|left|right`; injection goes through the abstract
  `INPUTEVENT_JOYn_*` events (`send_input_event`), NOT
  `setjoybuttonstate` — that indexes host joystick devices, of which a
  headless run has none, so it injected nothing. A CPU halt emits
  `{"event":"halt",...}` and
  the process exits 2.

  **CPU cache registers**: `regs` also answers `"cacr"` and `"caar"` (hex),
  the 68020+ cache control/address registers, so a run can show whether Kickstart
  switched the instruction cache on (A1200, KS3.0: `cacr` 1 from early boot).

  **Write watchpoints** (issue #107): `watch set ADDR SIZE` (SIZE <= 64)
  snapshots that region; `run until=watch` re-compares it from the
  per-instruction hook the breakpoints already run under and stops on the
  first difference, emitting
  `{"event":"watch","frame":N,"addr":"..","pc":"..","was":"..","is":".."}`.
  There is no memory-bank hook, so the cost is zero when disarmed and the
  reported `pc` is the instruction AFTER the store — which is what a "who
  clobbered this address" hunt wants. The corollary: a region written by the
  blitter, copper or disk DMA reports whatever `pc` the CPU happened to reach,
  which names no writer at all. The snapshot is re-taken at each
  `run until=watch` and after each hit, so repeated runs walk successive
  writes (a byte-copy loop reports one hit per byte).

  **Reset count** (issue #125): `status` answers `"resets"`, the number of
  RESET instructions executed since power-on, counted in `cpureset()`
  (`src/newcpu.cpp`). That is how an Amiga reboots — RESET, then jump back
  into the ROM — and neither ROM executes one on its own account: kick1.3's
  cold entry is `$FC00D2`, one word past the `$4E70` at `$FC00D0`, and
  Demokick's single `reset` is only reachable through the scanning idiom
  (issue #120). So on everything measured so far the count moves only when
  the disk restarts the machine; it is still a count of RESET instructions,
  not of reboots, and a program may execute one for its own reasons.
  Deliberately not hooked in `m68k_go`'s reset loop: a software reboot never
  leaves the run loop, and hooked there a disk that visibly rebooted three
  times counted 0.

  **Pointer motion** (issue #104, `act_*` in `src/dbgproto.cpp`): the Amiga
  mouse is a delta device, so there is no absolute position to write.
  `move X Y` slams `MOUSE_HOME` (2048) counts into the top-left corner —
  further than any Amiga screen is wide, so Intuition clamps there — and
  walks out to X,Y; `rel DX DY` is the plain delta. Coordinates are pointer
  units, i.e. mouse counter steps, which a standard hires Workbench screen
  maps 1:1 horizontally and 2:1 vertically (the pointer's vertical
  resolution is interlaced). Motion goes through
  `INPUTEVENT_MOUSE1_HORIZ/_VERT`, for the same reason `joy` avoids
  `setjoybuttonstate`: `setmousestate` indexes host mouse devices.
  Two pacing rules are load-bearing:
  - `mouseupdate` moves the emulated counters at most **120 units per frame
    and discards the rest**, so a step injects `MOUSE_STEP` (100) per frame
    and spreads the rest over following frames. A one-shot 500-unit delta
    arrives as 120.
  - Counters only advance when the Amiga side reads the port
    (`readinput` off JOY0DAT/JOY1DAT); with no reader, a frame delivers 1-2
    units. Every OS or game that owns a pointer reads at least once a frame,
    so this only shows up in probes that never touch the port.

  Because frames only elapse inside a `run`, motion and the click helpers
  queue and advance one step per vsync. Each command answers with the
  `"frames"` its queue still needs — hand that to the next `run frames=`
  (`tools/runner.py`'s `move_frames`/`click_frames` compute the same number
  host-side for batches composed up front). `click`/`doubleclick` are
  press/release pairs held `CLICK_HOLD` frames, the pair spaced to land
  inside Intuition's double-click window. `tools/inputtest.py` (ctest
  `input_pointer`) pins all of it against JOY0DAT and CIA-A PRA.

  **Swap-wait detector / autoswap**
  (`disk autoswap on|click|off|status [idle=SECONDS]`): a demo waiting for
  its next disk polls CIA-A PRA /CHNG *with a drive selected* while disk
  DMA is idle — the one signature shared by every wait style in the 12-set
  survey (docs/demo-tricks.md, "disk-swap sample sweep"); bare $BFE001
  reads don't qualify (mouse polling), and head-stepping is only a
  confidence signal (Eon never steps). `src/disk.cpp` notes selected-drive
  PRA reads (`DISK_status_ciaa`), step pulses (`DISK_select`) and DMA
  starts with the selected drive's cylinder (both `DSKLEN` arms) via
  `dbgproto_note_*`; `swap_vsync()` in `src/dbgproto.cpp` runs the
  heuristic once per frame:
  - Nothing triggers before *arming*: a DMA start with the head past
    cyl 15 (`SWAP_MIN_STREAM_CYL`) — early-boot /CHNG interrogation
    otherwise looks like a swap wait. Arming is per disk: every autoswap
    insert resets it, so nothing re-fires until the *new* disk has
    streamed past cyl 15 (accepting a swap involves a step-and-poll
    latch-clear burst plus cyl-0 ID reads that otherwise re-trigger).
  - A poll window opens on a polled frame and dies after a 60-frame poll
    gap (`SWAP_POLL_GAP`; kick13's ~2.5 s trackdisk housekeeping can't
    sustain a window). Only *streaming* DMA — cyl ≥ 2
    (`SWAP_STREAM_CYL`) — resets the window; DMA at cyl 0/1 is an ID
    re-read (9 Fingers re-reads track 0 every ~100 frames while waiting
    and must not restart the clock).
  - `swap-poll` fires when a window sustains 500 frames
    (`SWAP_WAIT_CONFIRM`, ~10 s) with polls in ≥8 frames
    (`SWAP_MIN_POLL_FRAMES`). Poll density and head steps discriminate
    nothing: loaders emit mid-disk bursts of every shape (The Last Drop:
    nine false windows on disk 2 alone, 20–14000 reads each; Odyssey:
    step+poll disk verifications), but they all die when streaming
    resumes within a few hundred frames — only a real wait outlives
    10 s.
  - Opt-in `idle=SECONDS` trigger (`swap-idle`) for prompts that never
    touch the drive (Odyssey: "PRESS LEFT MOUSE BUTTON"): fires after N
    seconds with no DMA and no polls, but only with df0 retracted to
    cyl 0 + motor off — Odyssey's disk A has ~60 s mid-disk lulls parked
    at cyl 8/49, so a bare timeout misfires.

  When armed via `on`/`click`, a trigger inserts the next `-diskswapper=`
  entry (slot shared with `disk swap-next`), emits
  `{"event":"autoswap",...}` (`autoswap-exhausted` when the list runs
  out), and in `click` mode presses LMB once if the insert has not led
  to streaming within ~5 s (`{"event":"autoswap-click"}` — an ID check
  at cyl 0 does not cancel the press; Odyssey reads the new disk's ID
  but still waits for LMB). Streaming re-arms the detector for the next
  disk, so N-disk chains run hands-free. `disk autoswap status` dumps
  the live window/counters.

  An insert is a *hypothesis*, verified by acceptance: polling cannot
  distinguish "waiting for the next disk" from "monitoring that the
  current disk is still in" — The Last Drop presence-polls at cyl 22
  while its voxel part plays from RAM, a drive signature identical to
  its real wait, and it rejects any other disk offered there (one ID
  read, then it polls for the old disk's return). The window is reset
  at insert; *acceptance* = the demo streams the new disk (possibly
  thousands of frames later — the same demo ID-checks a correct disk
  and then plays from RAM for a long time, quiet, before touching it,
  so wall-clock is NOT the criterion); *rejection* = a post-insert poll
  window sustains ~20 s (`SWAP_REJECT_FRAMES`) with no streaming. On
  rejection the old disk is restored, the slot rolled back, and
  `{"event":"autoswap-rollback",...}` emitted; the demo re-accepts its
  disk by itself and the detector may re-fire after ~50 s
  (`SWAP_RETRY_DELAY`) — a monitor phase has resumed streaming by then
  (killing the window), while a genuinely rolled-back real wait just
  retries. `autoswap-exhausted` is one-shot: after the last disk is in,
  its own monitor phases keep firing the detector.
- `src/dbgproto.cpp`, `src/custom.cpp` (`dbgproto_note_line`),
  `src/osdep/amiberry_gfx.cpp` (`screenshot_box`) — **display measure**:
  where a run shows bitplanes, from the registers. `display measure on`
  starts it from nothing, `display measure off` stops it. While it is on,
  the end of every line notes whether the line was shown (bitplane DMA on,
  planes in BPLCON0, inside the vertical display window, outside vertical
  blank) and between which columns: those the horizontal display window
  and the fetch from DDFSTRT to DDFSTOP share, in lores pixels as DIWSTRT
  counts them ($81 is the first of a standard screen). Nothing else is
  touched, so a run is the same with the measure on. The counts are kept
  apart per mode: the resolution (`res`: 0 lores, 1 hires, 2 super-hires),
  interlaced or not (`lace`), and whether COP1LC was the ADDR given as
  `os=` (hex) on every line (`os`: the system's copper list; `status` now
  answers `cop1lc`, so a bare boot tells it). A frame is of the finest
  mode its lines had. `display status` answers `modes`, of each that showed
  a line its `res`, `lace`, `os`, `frames` (those that showed a line),
  `rows` and `cols` (stretches `[from, to, frames]`, `to` not included: in
  how many frames each line and column was shown), then `diw` (`[DIWSTRT, DIWSTOP, lines]` of the
  shown lines, 32 pairs at most, `more_diw` when there were others) and
  `screen`: the size of the picture a screenshot would give now and, as
  `box`, the box of its pixels that are not the border's colour, the
  border being the pixel 8 in from the top left (the first rows and
  columns of the picture are blanked). A line's number is one more than
  the line DIWSTRT names.
- `src/dbgproto.cpp` (r2-scene-db) — `disk autoswap ... idle=N anycyl`:
  `anycyl` drops the idle trigger's df0-at-cyl-0 gate. Soul Kitchen shows
  "Insert disk 2.." waiting for LMB with the head parked at cyl 75, motor
  off, no polls, so neither trigger fired. Off by default (a mid-demo quiet
  stretch would misfire); the r2-scene-db harness uses it only on a retry of
  a multi-disk run that went quiet with disks left to insert.
  `unit=N` makes autoswap insert into (and roll back, and gate its idle
  trigger on) DFN instead of DF0: Soho reads disk 2 from DF1 and then waits
  for disk 3 in DF1 too.
  `rampolls` ignores /CHNG polls whose PC is in Kickstart ROM
  ($E00000-$FFFFFF): trackdisk.device checks for disk changes every ~2 s
  on its own, which looks like a swap wait while a DOS-loaded demo plays
  from RAM (Dark Ages, My Mama Is a Vampire: every poll from ROM). A
  trackloader polls from its own code in RAM. `disk autoswap status`
  reports `rom_polls` next to `total_polls`; `src/disk.cpp` passes the PC
  to `dbgproto_note_chng_poll`.
  `dead=N` ends the batch (`{"event":"dead-end"}`) once the display (hash
  sampled every 25 frames), audio DMA and disk DMA have all been still for
  N frames: a crash or frozen screen need not run out a sweep budget.
- `src/dbgproto.cpp`, `src/audio.cpp`, `src/memory.cpp` — **per-frame trace
  for end-of-demo detection** (`trace PATH`, `state save PATH`, `pcs [N]`):
  - `trace PATH` opens three files — `PATH` (per-frame CSV of `dmacon`, Paula
    write hash/count, audio energy/peak/samples, new-PC / new-RAM-PC counts,
    instruction & ROM counts, `lastdma`, `resets`, `pc`, per-channel state
    `S`/`R`/`P`, `LastAlert`, new RAM read / read-site counts, `solid`,
    `bplcon0`, `cop1lc`, and a 4x8 grid of screen-cell hashes `v0..v31`),
    `PATH.notes` (Paula pointer/period/length writes per channel for song-loop
    matching), and `PATH.reads` (first-time RAM read streams per PC for
    scrolltext/script stream detection). Hooks in `src/audio.cpp`
    (`dbgproto_note_audio_reg`/`_loop`/`_sample`) and `src/memory.cpp`
    (`dbgproto_note_read`, gated by `dbgproto_read_trace`) have zero overhead
    when tracing is off.
  - `state save PATH` schedules a compressed UAE savestate write at the next
    hsync (paired with `--statefile` to resume traces from a checkpoint).
  - `pcs [N]` returns the last `N` (default 64, max 4096) executed PCs
    recorded under `run until=bp`.
- `src/main.cpp` `parse_diskswapper` — repeated `-diskswapper=` arguments
  accumulate into `dfxlist` instead of each restarting at slot 0
  (upstream last-arg-wins dropped every earlier entry; `tools/runner.py`
  passes one argument per extra disk).

  Added to the build via one line in
  `cmake/SourceFiles.cmake` (next to `src/custom.cpp`).
  Hooks (re-ported onto v8.2.2's diverged sources):
  - `src/main.cpp` — `--dbg` argv parsing.
  - `src/custom.cpp` — `dbgproto_vsync` frame counting in the vsync render
    path, audio-DMA detection in `DMACON`, `dbgproto_custom_status` chipset
    snapshot.
  - `src/newcpu.cpp` — per-instruction breakpoint/dispatch gate in the CPU
    run loops our configs actually select: `m68k_run_1_ce` (A500 68000
    cycle-exact tier) and `m68k_run_2ce` (A1200 68EC020 tier — selected by
    `cpu_cycle_exact=true`, which the A1200 config sets explicitly; it used to
    arrive by inheritance from Amiberry's default prefs, there is no
    promotion from `cpu_memory_cycle_exact` in the dispatch). The gate
    bootstraps command dispatch on the first instruction, so a run loop missing
    it never processes `--dbg` commands: the emulation just free-runs in real
    time. `m68k_run_2p` also carries the gate (harmless; kept for any
    compatible-tier config), and so does `m68k_run_2_020` — the 68040/68060
    fast tier the `a1200_060` machine (68060 + `cpu_speed=max`, no
    cycle-exact) selects. Plus the `cpu_halt` event and the `cpureset()`
    reboot count (above).
  - `src/osdep/amiberry.cpp` — non-zero process exit code after a mid-batch
    halt; plus the Esc-to-quit dev convenience (below).
- `src/osdep/amiberry.cpp` — Esc quits the emulator when the env var
  `AMIBERRY_ESC_QUITS` is set (used by `tools/run.py` for interactive launches;
  the emulated Amiga still receives Esc otherwise). Adapted to SDL3's key-event
  API (`event.key.scancode` / `event.key.down`).
- `src/osdep/amiberry.cpp` — Space toggles warp (`warpmode(-1)`) when the env
  var `AMIBERRY_SPACE_WARP` is set (used by `tools/run.py` for interactive
  launches, opt out with `--no-space-warp`; the emulated Amiga still receives
  Space otherwise). Both press and release are consumed so no half key event
  leaks into the Amiga.
- `cmake/SourceFiles.cmake` + `CMakeLists.txt` — macOS builds a **plain
  binary** (`build/amiberry`) instead of an `.app` bundle: the headless harness
  runs the binary from the build tree, so the bundle's resource-copy +
  `dylibbundler` + `codesign` post-build steps (`cmake/macos/install.cmake`)
  are skipped, the `MACOSX_BUNDLE` target metadata is confined to iOS, and the
  macOS output name is the lowercase `amiberry` (matching Linux). No other
  platform is affected.
- `--warp-until-audio-dma` argv flag (`src/main.cpp` parsing,
  `dbgproto.cpp`/`dbgproto.h` for the `dbgproto_warp_until_audio` flag,
  `src/newcpu.cpp` `warpmode_reset`, `src/custom.cpp` DMACON hook) — warp from
  reset until audio DMA first becomes effective, then drop to normal speed:
  an interactive fast-forward through boot/decrunch to the music. Plain warp,
  deliberately not the `warpboot` `turbo_emulation==2` state (whose copper-DMA
  hook would release it long before the music). One-shot: a later reset stays
  realtime. Independent of `--dbg` (reuses the same DMACON audio-edge
  detection); `tools/run.py --warp-until-audio-dma` passes it through for
  interactive launches.
- `src/osdep/amiberry_gfx.cpp` — `headless=true` runs render into
  `amiga_surface` so `--dbg screenshot` captures real frames (upstream's
  headless mode skipped ALL drawing and screenshots came out black):
  - `graphics_init` headless branch goes through `gfxmode_reset` /
    `updatemodes` / `update_gfxparams` / `doInit` (whose own headless branch
    allocates the soft draw buffers) instead of only creating a bare surface —
    without the buffer setup `lockscr` had nothing to hand the Denise drawing
    path.
  - `lockscr` no longer bails on the missing window in headless mode.
  - `amiberry_refresh` skips `present_frame` in headless mode (no GL context;
    calling it segfaulted inside `init_hz` on reset).
  The harness sets `headless=true` in every generated test config
  (`tools/runner.py` BASE/A1200 configs); `tools/run.py` interactive mode
  flips it back to `false`.
- `src/osdep/gfx_window.cpp` — on macOS the emulation window activates and
  takes focus when created (`macos_raise_window`, the same helper the launcher
  GUI already used): a plain binary launched from a terminal is not the
  frontmost app, so without this the window opened behind the terminal.
  Primary monitor only, skipped for hidden/headless windows; no-op off macOS.
- `src/osdep/amiberry_ipc_socket.cpp` — the IPC control socket falls back to a
  **pid-unique** path (`amiberry_<pid>.sock`) when the well-known
  `$XDG_RUNTIME_DIR/amiberry.sock` is taken, instead of scanning
  `amiberry_1..9.sock` and giving up after ten tries (`IPC: Could not find
  available socket path after 10 attempts` — the 2026-08-14 games sweep at
  `--jobs 24` lost a game to it, issue #113). The stale-socket unlink also
  moved to *after* a bind has proved the path both occupied and unreachable:
  the old unconditional pre-bind unlink could delete a concurrent instance's
  live socket. Nothing in the harness connects to this socket — the `--dbg`
  protocol is stdout — it is just opened unconditionally at startup.
- `cmake/Dependencies.cmake` + `cmake/linux/install.cmake` — the `capsimage`
  `add_subdirectory` / `add_dependencies` / `install` hooks are guarded
  (`if(EXISTS ...)` / `if(TARGET capsimage)`) so the tree builds with
  `external/capsimage/` stripped (see above).

### Patches NOT needed on full Amiberry (were Lite-only)

The Lite snapshot also patched a warp/frame-pacing bug (`SDL2_showframe`) and
stubbed `src/midiemu.cpp`. Neither is needed here: v8.2.2 already skips host
frame pacing under `turbo_emulation` (warp), and `midiemu.cpp` self-stubs
behind `#ifdef WITH_MIDIEMU` (off in our build).

## Build

macOS/Linux, from the repo root (Linux is the primary target):

```bash
CC=clang CXX=clang++ cmake -S tools/amiga/amiberry -B build/amiberry -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DUSE_PCEM=OFF -DUSE_PPC=OFF -DUSE_QEMU_PPC=OFF \
    -DUSE_LIBSERIALPORT=OFF -DUSE_LIBENET=OFF -DUSE_PORTMIDI=OFF \
    -DUSE_LIBMPEG2=OFF -DUSE_MPG123=OFF -DUSE_UAENET_PCAP=OFF \
    -DUSE_UAENET_TAP=OFF -DUSE_ZSTD=OFF
cmake --build build/amiberry # -> build/amiberry/amiberry
```

Deps (all via Homebrew on macOS / distro packages on Linux): **SDL3**,
**SDL3_image**, FLAC, libpng, zlib, curl, **nlohmann-json**. v8.2.2 is SDL3
(the Lite snapshot was SDL2). GUI is Dear ImGui (vendored, no SDL_ttf).
The `USE_*=OFF` flags drop optional subsystems the harness doesn't use (PCem
Bridgeboard, PowerPC, serial, netplay, MIDI, CD32 FMV, MP3, uaenet, CHD/zstd).

Scripted run (headless batch protocol):

```bash
build/amiberry/amiberry -f config.uae \
    --dbg "warp on" --dbg "run frames=2500" --dbg "screenshot /tmp/shot.png"
```

## Known limitation: the real SDL video driver does not survive parallel runs

Upstream `main()` does `if (!osdep_platform_init_sdl()) abort();`, and
`osdep_platform_init_sdl` (`src/osdep/amiberry_platform_internal_host.h`) opens
VIDEO/AUDIO/JOYSTICK/GAMEPAD/EVENTS in one `SDL_Init`. Several processes
opening the real video driver at once makes that call fail, and the failure
only reaches the *log file* — so a parallel sweep loses runs to silent
`SIGABRT`s during startup, with no `--dbg` output and nothing on stdout to say
why. Measured here: 4 of 6 concurrent boots aborted.

`tools/runner.py` therefore exports `SDL_VIDEODRIVER=dummy` for every run
(overridable from the environment). Nothing is displayed anyway — the batch
protocol is the whole interface — and `screenshot` still captures the emulated
framebuffer: the PNGs come out **byte-identical** to a real-driver run, so no
signature or golden changes.

Do NOT reach for `SDL_AUDIODRIVER=dummy` as well. It also stops the aborts, but
it **changes the emulation** — the same disk at the same frame yields a
different picture — so it would quietly invalidate every framebuffer signature
the sweeps compare. Audio stays on the real driver.

## Supported concurrency

Verified at **48 simultaneous instances** on this box (32 cores, 62 GB): all 48
bound a distinct IPC socket and unlinked it on exit. The socket path is no
longer a ceiling — the pid-unique fallback above replaced a fixed ten-path
scan. What bounds `--jobs` now is host resources: an instance is one busy core
and ~100 MB RSS under warp, so keep the job count at or below the core count
(`--jobs 24` on a 32-core box is fine). ctest `ipc_concurrency`
(`tools/ipcconctest.py`) holds the sweep's 24 as a regression.

## Known accuracy note

Unlike the Lite snapshot, v8.2.2's default cycle-exact chipset is WinUAE-synced
and renders the demos of this data set (including the Rink a Dink Redux plasma)
without the lower-right dropout Lite showed. If a future divergence from real
hardware turns up, check whether it also reproduces in stock upstream Amiberry
before assuming it is a local-patch regression.
