# Tools

| path | what |
|------|------|
| `scenemeta/` | one package: the data files' reader, writer and validator at the top level (no dependencies, used by CI), and the sweepers |
| `scenemeta/core/` | what every platform's sweeper shares |
| `scenemeta/amiga/`, `scenemeta/c64/` | the platforms |
| `amiga/`, `c64/` | what a platform keeps outside the code: its emulator, ROMs, work directory, sweep database, notes |
| `../build/` | everything that is built (Amiberry and its build log), git-ignored |
| `tests/` | the tests: `test_merge.py` and `test_validate.py` for the data files, a directory per sweeper part |

```bash
cd tools
python3 -m scenemeta amiga sweep --ids 142     # or: c64
python3 -m scenemeta amiga report
python3 -m unittest discover -s tests -t .
```

A sweep boots every production of a platform in an emulator, up a ladder of
machines until one works, swaps disks when the production waits for one, and
logs every run in `<platform>/scene.db`. The export then merges what was
found into `data/<platform>` (see `../docs/DESIGN.md`).

## What the core does

| module | what |
|--------|------|
| `core/config.py` | the NAS, and a platform's ROM, work, database and data paths (`SCENEMETA_NAS`, `SCENEMETA_ROMS`, `SCENEMETA_WORK`, `SCENEMETA_DB`, `SCENEMETA_DATA`) |
| `core/catalog.py` | the productions of a platform and their download links, from the Demozoo index |
| `core/result.py` | the records a platform reports: `Variant`, `Run`, `Swap` |
| `core/gate.py` | the record a platform's player returns of a run (`Play`) and the gate: the runs to make of an entry (several seeds, the disks late, each key left out) and pass or fail of them, with a reason |
| `core/gatelog.py` | what the gate saw of each entry, a record per entry and seed, or why it could not be played: the summary of counts that is checked in, the entries to gate again, and whether the log holds a pass of an entry |
| `core/demote.py` | what a gate pass over every entry means for the data files: the failing `script` entries to demote to `unknown`, the failing ones somebody worked on, and those not judged |
| `core/corpus.py` | a platform's corpus, productions with the outcome expected of them, and the scoreboard of the gate over it that is checked in |
| `core/store.py` | the sweep log: `production`, `variant`, `run`, `swap`, and the `best` view; the gate's log, `gate` |
| `core/sweep.py` | the sweep driver: worker processes, resume, storing, progress |
| `core/export.py` | reads the runs of each variant, says which entries of a production are put to the gate (three, best first), and merges entries into the data files |
| `core/cli.py` | the `sweep`, `report` and `migrate` commands and the `--ids`/`--limit` selection |
| `core/migrate.py` | converts a sweep database from before the shared schema |

Every time the core sees is seconds of emulated time since power-on, as in
the data files. Inside a run a platform counts what its emulator counts
(Amiga frames, C64 CPU cycles) and converts when it fills in the records.

The seam is one production's sweep: the core never talks to an emulator.
Amiberry is given a script and its output is parsed afterwards; VICE is
driven live through its monitor. Both end in the same records.

## Adding a platform

A platform is a subpackage with:

- `catalog.py`: its Demozoo platform names and production types, passed to
  `core.catalog.productions`.
- `config.py`: `core.config.home("<platform>")` plus its own paths (the
  emulator binary, its mirrors).
- The work on one production, a function the sweep driver runs in a worker:
  find the media, run each bootable variant up the machine ladder, and
  return `(problems, [result.Variant])` with every `result.Run` made and
  the index of the chosen one. How it drives its emulator, detects a wait
  for a disk and judges a run is its own.
- `store.py`: `core.store.Store`, with more schema if it keeps tables of
  its own. What only this platform stores of a variant or a run goes into
  their `detail` (JSON).
- `export.py`: what a data-file entry says, from `core.export.productions`;
  `core.export.run` merges the entries.
- `__main__.py`: `core.cli.parser` plus its own commands. Add the name to
  `PLATFORMS` in `scenemeta/__main__.py`.
- `data/<platform>/machines.toml` for its presets, and `tools/<platform>/`
  for its emulator and ROMs.

## Older sweep databases

A database written before the shared schema (Amiga frames, C64 cycles and
`flip` tables) is refused. Convert it in place, one transaction:

```bash
python3 -m scenemeta amiga migrate path/to/scene.db
```

The old tools cannot read a converted file: copy it first if they still
need it.
