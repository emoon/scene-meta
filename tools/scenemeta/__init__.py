"""The project's Python: the data files' reader, writer and validator at the
top level, and the sweepers (which machine each production works on and when
it asks for its next disk) in ``core`` and one subpackage per platform.

    python3 -m scenemeta.validate [data-dir]
    python3 -m scenemeta <platform> <command> ...

The top-level modules import nothing from the sweepers, so that checking the
data needs only Python.
"""
