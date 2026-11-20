"""What stops a run before it starts."""


class CannotPlay(Exception):
    """Something a run needs is missing: a ROM, the media, a key that
    cannot be pressed, a ``run`` that is not among the download's files.
    The message names it. Never a verdict: nothing ran."""


class BadEntry(CannotPlay):
    """What is missing is something the entry itself asks for: a machine,
    a key, media the download does not have. The same entry cannot be
    played until it, or the player, changes."""
