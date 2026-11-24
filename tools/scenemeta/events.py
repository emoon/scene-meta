"""The events of an entry (docs/DESIGN.md): what is done while it plays."""


def ordered(events):
    """``events`` in the order they happen: by time, a disk before a key
    of the same moment (the key may be the one that has it taken)."""
    return sorted(events, key=lambda e: (e["at"], "key" in e))
