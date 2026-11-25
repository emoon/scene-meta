"""PROTOTYPE (throwaway): the last new data read as a stream.

The trace's ``.reads`` file lists, per frame, the first few bytes an
instruction read that it had not read before. A text, a script or a pattern
is read as a stream: each new byte lies just above the reader's last new
one, with nothing the reader has read before right above it. Table lookups
jump about and go on finding new entries for ever; an index that moves
smoothly (an angle into a sine table) fills the gaps between entries it has
read, which is not a stream either.
"""
import collections, os

FPS = 50
STEP = 16     # bytes above the reader's last new one that continue a stream
WIN = 30      # s within which a reader must make NEED stream reads to count
NEED = 8
VECTORS = 0x400   # the exception vectors: read by every interrupt
ROM_START = 0xe00000
ROM_END = 0x1000000


def stream_end(reads):
    """Frame of the last stream read; 0 when there is none, None when the
    trace has no reads file (recorded before there was one)."""
    if not os.path.exists(reads):
        return None
    last, seen, at = {}, collections.defaultdict(set), collections.defaultdict(list)
    with open(reads) as f:
        for line in f:
            parts = line.split(",")
            if len(parts) != 4:
                continue
            try:
                frame_i = int(parts[0])
                kind = parts[1]
                pc_i = int(parts[2], 16)
                addr = int(parts[3], 16)
            except ValueError:
                continue
            if kind != "S" or addr < VECTORS or ROM_START <= pc_i < ROM_END:
                continue
            if pc_i in last and 0 < addr - last[pc_i] <= STEP and not any(
                    a in seen[pc_i] for a in range(addr + 1, addr + STEP + 1)):
                at[pc_i].append(frame_i)
            last[pc_i] = addr
            seen[pc_i].add(addr)
    end = 0
    for frames in at.values():
        for k in range(NEED - 1, len(frames)):
            if frames[k] - frames[k - NEED + 1] <= WIN * FPS:
                end = max(end, frames[k])
    return end
