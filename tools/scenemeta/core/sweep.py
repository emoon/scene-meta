"""Run a platform's sweep over many productions: in parallel, resumable,
each production's results stored as it finishes."""

import concurrent.futures as cf
import os
import traceback

from .errors import CannotPlay


def _guarded(job, prod):
    """Worker: ``job(prod)``, an exception reported per production. Not a
    CannotPlay: what that run lacked, every later one lacks too."""
    try:
        return prod, job(prod), None
    except CannotPlay:
        raise
    except Exception:  # noqa: BLE001 - reported per production
        return prod, ([], []), traceback.format_exc()


def summary(variants):
    """What was chosen for each variant, for the progress line."""
    return ", ".join(
        f"{b.machine}:{b.verdict}"
        + (f" {b.reached}/{len(v.disks)} disks" if len(v.disks) > 1 else "")
        + (f" {b.drives} drives" if b.drives > 1 else "")
        for v, b in ((v, v.chosen) for v in variants))


def run_all(prods, store, job, jobs=None, log=print, again=False):
    """Sweep ``prods`` that the store does not hold finished yet, or with
    ``again`` every one of them.

    ``job(prod)`` is the platform's work on one production, run in a worker
    process (so it must pickle): it returns ``(problems, variants)``, the
    media problems as strings and a result.Variant per bootable thing, or
    None for a production it leaves out: what the store holds of it stays.
    A job that raises CannotPlay ends the sweep with that error: nothing
    is stored of its production, and the ones not started are not run.
    """
    jobs = jobs or max(1, (os.cpu_count() or 2) * 3 // 4)
    done = () if again else store.done_productions()
    todo = [p for p in prods if p.id not in done]
    log(f"{len(todo)} productions to run ({len(prods) - len(todo)} done), "
        f"{jobs} jobs")
    with cf.ProcessPoolExecutor(jobs) as pool:
        futs = [pool.submit(_guarded, job, p) for p in todo]
        for n, fut in enumerate(cf.as_completed(futs), 1):
            try:
                prod, result, err = fut.result()
            except CannotPlay:
                for f in futs:
                    f.cancel()
                raise
            if result is None:
                log(f"[{n}/{len(todo)}] {prod.id} {prod.title} -> left out",
                    flush=True)
                continue
            problems, variants = result
            if err:
                problems = problems + [f"internal-error: {err.splitlines()[-1]}"]
                log(err)
            store.put_result(prod, problems, variants)
            log(f"[{n}/{len(todo)}] {prod.id} {prod.title} -> "
                f"{summary(variants) or '; '.join(problems) or '-'}",
                flush=True)
