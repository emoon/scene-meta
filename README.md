# demoscene-metadata

What each demoscene production needs to run correctly: which machine, when to
swap disks, which keys to press. Plain TOML, meant to be read and edited by
people. Amiga and C64 so far.

```toml
[demozoo.142]
title  = "Desert Dream"
group  = "Kefrens"
source = "script"
disks  = ["DesertDream-A.adf", "DesertDream-B.adf"]
swaps  = [{ disk = 2, at = 536.9, key = "lmb" }]
```

The format and the reasons behind it are in [DESIGN.md](DESIGN.md).

## Layout

| path | what |
|------|------|
| `data/<platform>/machines.toml` | the machine presets, in hardware terms |
| `data/<platform>/<bucket>.toml` | productions, by first character of the title |
| `tools/common/` | validator |
| `tools/amiga/`, `tools/c64/` | the sweepers that generated the first pass |

## Editing

Find the production in `data/<platform>/<first character of title>.toml`,
change it, and open a pull request. `source` says how much an entry can be
trusted:

| `source` | meaning |
|----------|---------|
| `script` | found by a sweep, nobody looked |
| `ai` | worked out with AI assistance |
| `verified` | you watched it to the end, every disk swap included, on the stated machine |

Set `verified` only when you have watched all of it.

Check your change (Python 3.11 or later, no dependencies):

```bash
cd tools/common
python3 -m scenemeta.validate
python3 -m unittest discover -s tests -t .
```

## Licences

One per directory. `data/` is CC0 (`data/LICENSE`). `tools/` is MIT
(`tools/LICENSE`), except for bundled emulators, which keep their own licence
in their own directory. ROMs are not included.
