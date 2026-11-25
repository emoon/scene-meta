#!/usr/bin/env python3
"""PROTOTYPE (throwaway): song matcher + verdict over a directory of recordings.

    python3 amiga/proto-end-detect/judge.py REC_DIR OUT.json [--jobs 100]

Run from tools/. For every REC_DIR/<id>/trace.csv (with its .notes): the note
matcher, then analyze.verdict(). OUT.json is the list of verdicts; songs are
also written to OUT.songs.json so a rerun of one stage needs no other.
"""
import argparse, glob, json, multiprocessing, os, pathlib, sys, tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import analyze, notes  # noqa: E402

REC = None
SWAPS = {}  # id -> [s of each scripted swap]
DATA = pathlib.Path(__file__).resolve().parents[3] / "data" / "amiga"


def _trace_end(trace):
    """Last frame number in trace.csv without parsing the whole file."""
    try:
        with open(trace, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            lines = f.read().splitlines()
            for line in reversed(lines):
                if line and line[0:1].isdigit():
                    return int(line.split(b",", 1)[0])
    except (OSError, ValueError):
        pass
    return None


def song(i):
    t = f"{REC}/{i}/trace.csv"
    p = t + ".notes"
    try:
        return i, (notes.song_loop(p, trace_end=_trace_end(t)) if os.path.exists(p) else None)
    except ValueError:  # a run killed mid-write ends on a cut line
        return i, None


def verdict(args):
    i, s = args
    t = f"{REC}/{i}/trace.csv"
    try:
        rows, cells = analyze.load(t)
        meta = analyze.meta_of(t)
        v = analyze.verdict(
            rows, cells, s and tuple(s),
            halted=analyze.halted_of(t),
            data=analyze.data_of(t),
            swaps=SWAPS.get(int(i), ()),
            meta=meta,
            notes_path=t + ".notes",
        )
    except Exception as e:  # one bad trace must not lose the batch
        return {"id": int(i), "ending": "error", "error": repr(e)}
    v["id"] = int(i)
    return v


def swaps_of_entries():
    out = {}
    for p in glob.glob(str(DATA / "*.toml")):
        for k, e in tomllib.loads(pathlib.Path(p).read_text("utf-8")).get("demozoo", {}).items():
            sw = [ev["at"] for ev in e.get("events", []) if "disk" in ev]
            if sw:
                out[int(k)] = sw
    return out


def main():
    global REC, SWAPS
    ap = argparse.ArgumentParser()
    ap.add_argument("rec")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=100)
    ap.add_argument("--reuse-songs", action="store_true", help="skip the matcher: use OUT.songs.json")
    a = ap.parse_args()
    REC = a.rec
    SWAPS = swaps_of_entries()
    ids = sorted(d for d in os.listdir(REC) if d.isdigit() and os.path.exists(f"{REC}/{d}/trace.csv"))
    with multiprocessing.Pool(a.jobs) as p:
        sf = a.out.replace(".json", ".songs.json")
        if a.reuse_songs:
            songs = json.load(open(sf))
        else:
            songs = dict(p.imap_unordered(song, ids, chunksize=1))
            json.dump(songs, open(sf, "w"))
        print("songs done", len(songs), flush=True)
        out = []
        for v in p.imap_unordered(verdict, songs.items(), chunksize=1):
            out.append(v)
    json.dump(out, open(a.out, "w"))
    print("verdicts done", len(out))


if __name__ == "__main__":
    main()
