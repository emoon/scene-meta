"""PROTOTYPE (throwaway): the last new data read as a stream.

The trace's ``.reads`` file lists, per frame, the first few bytes an
instruction read that it had not read before. A text, a script or a pattern
is read as a stream: each new byte lies just above the reader's last new
one. Table lookups jump about, and go on finding new entries for ever.
"""
import collections, os

FPS = 50
STEP = 16     # bytes above the reader's last new one that continue a stream
WIN = 30      # s within which a reader must make NEED stream reads to count
NEED = 8
VECTORS = 0x400   # the exception vectors: read by every interrupt


def stream_end(reads):
    """Frame of the last stream read; 0 when there is none, None when the
    trace has no reads file (recorded before there was one)."""
    if not os.path.exists(reads):
        return None
    last, at = {}, collections.defaultdict(list)
    with open(reads) as f:
        for line in f:
            frame, kind, pc, addr = line.split(",")
            addr = int(addr, 16)
            if kind != "S" or addr < VECTORS:
                continue
            if pc in last and 0 < addr - last[pc] <= STEP:
                at[pc].append(int(frame))
            last[pc] = addr
    end = 0
    for frames in at.values():
        for k in range(NEED - 1, len(frames)):
            if frames[k] - frames[k - NEED + 1] <= WIN * FPS:
                end = max(end, frames[k])
    return end
