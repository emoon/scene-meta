"""The events of an entry (docs/DESIGN.md): what is done while it plays."""

FOR_EVER = float("inf")    # an ``until`` that has no end


def ordered(events):
    """``events`` in the order they happen: by time, a disk before a key
    of the same moment (the key may be the one that has it taken)."""
    return sorted(events, key=lambda e: (e["at"], "key" in e))


def patient(events, patience):
    """``events`` as a patient player does them, each a plain event at the
    time it is done: at its ``until``, and every later one moved by as much
    as this one waited. One that may wait for ever is given ``patience``
    seconds."""
    out, waited = [], 0.0
    for event in ordered(events):
        event = dict(event)
        until = event.pop("until", event["at"])
        waited += patience if until == FOR_EVER else until - event["at"]
        event["at"] += waited
        out.append(event)
    return out
