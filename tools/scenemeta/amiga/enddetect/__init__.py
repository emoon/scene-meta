"""Amiga end-of-demo detection from per-frame Amiberry traces.

Combines four signal extractors:
- ``notes``: Paula note-event song-loop matcher
- ``video``: per-cell screen-grid video loop and landmark detector
- ``streams``: sequential RAM data and scrolltext stream detector
- ``analyze``: verdict classifier combining all trace signals

``runner`` drives Amiberry to record traces, runs analysis, stores verdicts
in ``scene.db`` (``ending`` table), and supports batch re-analysis of
existing recording directories.
"""

from .analyze import analyze_trace, load, verdict
from .runner import DEFAULT_FRAMES, build_commands, detect, judge_dir, record, run

__all__ = [
    "DEFAULT_FRAMES",
    "analyze_trace",
    "build_commands",
    "detect",
    "judge_dir",
    "load",
    "record",
    "run",
    "verdict",
]
