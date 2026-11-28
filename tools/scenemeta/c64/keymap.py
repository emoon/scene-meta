"""Authoritative C64 input names and X keysyms, without loading X libraries."""

SYMS = {"space": "space", "Return": "Return", "Left": "Left",
            "p1fire": "KP_0", "p2fire": "KP_0",
            **{k: k for k in "0123456789abcdefghijklmnopqrstuvwxyz"},
            **{f"F{n}": f"F{n}" for n in range(1, 9)}}

NAMES = {name.lower(): name for name in SYMS}
