"""Which SID chip a production's music was written for.

Nothing in a disk image says, and a run cannot tell. Demozoo tags music
``6581`` or ``8580``: a production has the model of its own tags, else the
one its soundtracks agree on. Where the tags name both, or none, the model
is not known.
"""

from ..core import catalog

MODELS = ("6581", "8580")


def model(own, tracks):
    """The model from a production's ``own`` tags and its soundtracks'
    (``tracks``: a set of tags each), or None."""
    found = set(own) or set().union(*tracks)
    return next(iter(found)) if len(found) == 1 else None


def models():
    """``{production id: model}`` of every production whose model is known."""
    tags = catalog.tagged(MODELS)
    tracks = catalog.soundtracks()
    found = {prod: model(tags.get(prod, ()),
                         [tags.get(t, ()) for t in tracks.get(prod, ())])
             for prod in tags.keys() | tracks.keys()}
    return {prod: m for prod, m in found.items() if m}
