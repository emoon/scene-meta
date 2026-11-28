"""Bounded dispatch of entry playback with per-production missing-input errors."""

import concurrent.futures as cf

from .errors import CannotPlay


def each_played(todo, one, jobs):
    """Play every ``(prod, entry)`` of ``todo``, ``jobs`` at a time. Yields
    of each, as it ends, ``(prod, True, one(prod, entry))``, or ``(prod,
    False, line)`` with the line that reports why it cannot be played.
    The caller checks shared requirements before dispatch."""

    def report(prod, entry):
        try:
            return prod, True, one(prod, entry)
        except CannotPlay as e:
            return prod, False, f"{prod} {entry['title']}: error: {e}"

    pool = cf.ThreadPoolExecutor(jobs)
    it = iter(todo)
    pending = set()
    try:
        for _ in range(max(1, jobs)):
            pe = next(it, None)
            if pe is None:
                break
            pending.add(pool.submit(report, *pe))
        while pending:
            done, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
            for fut in done:
                res = fut.result()
                pe = next(it, None)
                if pe is not None:
                    pending.add(pool.submit(report, *pe))
                yield res
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
