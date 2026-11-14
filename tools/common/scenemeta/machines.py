"""A platform's machine presets (``machines.toml``)."""

import tomllib

FILE = "machines.toml"


def load(path):
    """``(default, presets, problems)``. presets: name -> its fields."""
    try:
        doc = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        return None, {}, [str(e)]
    presets = {k: v for k, v in doc.items() if isinstance(v, dict)}
    problems = [f"unknown field {name}"
                for name in doc.keys() - presets.keys() - {"default"}]
    default = doc.get("default")
    if default not in presets:
        problems.append("default must name a preset")
    for name, fields in presets.items():
        for field, value in fields.items():
            if not hardware_value(value):
                problems.append(f"[{name}] {field} must be a string or a whole number")
    return default, presets, problems


def hardware_value(v):
    """Is ``v`` a legal value of a hardware field?"""
    return (isinstance(v, str) and v != "") or \
        (isinstance(v, int) and not isinstance(v, bool) and v >= 0)


def hardware_fields(presets):
    """The hardware field names of a platform: the ones its presets use."""
    return {f for p in presets.values() for f in p} - {"description"}
