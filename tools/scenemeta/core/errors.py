"""What stops a run before it starts."""


class CannotPlay(Exception):
    """Something a run needs is missing: a ROM, the media, a key that
    cannot be pressed, a ``run`` that is not among the download's files.
    The message names it. Never a verdict: nothing ran."""
