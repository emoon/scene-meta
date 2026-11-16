#!/usr/bin/env python3
"""PROTOTYPE (throwaway): song matcher + verdict over a directory of recordings.

    python3 amiga/proto-end-detect/judge.py REC_DIR OUT.json [--jobs 100]

Run from tools/. For every REC_DIR/<id>/trace.csv (with its .notes): the note
matcher, then analyze.verdict(). OUT.json is the list of verdicts; songs are
also written to OUT.songs.json so a rerun of one stage needs no other.
"""
import argparse, json, multiprocessing, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import analyze, notes  # noqa: E402

REC = None
BIG = 12_000_000  # bytes of .notes: ~1M events


def song(i):
    p = f"{REC}/{i}/trace.csv.notes"
    if os.path.exists(p) and os.path.getsize(p) > BIG:  # the matcher does not finish on these
        print("skip", i, flush=True)
        return i, None
    try:
        return i, (notes.song_loop(p) if os.path.exists(p) else None)
    except ValueError:  # a run killed mid-write ends on a cut line
        return i, None


def verdict(args):
    i, s = args
    t = f"{REC}/{i}/trace.csv"
    try:
        rows, cells = analyze.load(t)
        v = analyze.verdict(rows, cells, s and tuple(s), analyze.halted_of(t), analyze.data_of(t))
    except Exception as e:  # one bad trace must not lose the batch
        return {"id": int(i), "ending": "error", "error": repr(e)}
    v["id"] = int(i)
    return v


def main():
    global REC
    ap = argparse.ArgumentParser()
    ap.add_argument("rec")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=100)
    a = ap.parse_args()
    REC = a.rec
    ids = sorted(d for d in os.listdir(REC) if d.isdigit() and os.path.exists(f"{REC}/{d}/trace.csv"))
    with multiprocessing.Pool(a.jobs) as p:
        songs = dict(p.imap_unordered(song, ids, chunksize=1))
        json.dump(songs, open(a.out.replace(".json", ".songs.json"), "w"))
        print("songs done", len(songs), flush=True)
        out = []
        for v in p.imap_unordered(verdict, songs.items(), chunksize=1):
            out.append(v)
    json.dump(out, open(a.out, "w"))
    print("verdicts done", len(out))


if __name__ == "__main__":
    main()
