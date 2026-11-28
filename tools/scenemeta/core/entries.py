"""Read the Demozoo entries in one platform data directory."""

import tomllib

from .. import machines as presets


def all_entries(data):
    """``{id: entry}`` of every Demozoo production in the data files."""
    out = {}
    for path in sorted(data.glob("*.toml")):
        if path.name != presets.FILE:
            for key, e in tomllib.loads(path.read_text("utf-8")) \
                    .get("demozoo", {}).items():
                out[int(key)] = e
    return out


