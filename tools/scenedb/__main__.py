"""``python3 -m scenedb <platform> <command> ...``: a platform's commands."""

import importlib
import sys

PLATFORMS = ("amiga", "c64")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in PLATFORMS:
        sys.exit(f"usage: python3 -m scenedb {{{','.join(PLATFORMS)}}} <command> ...")
    cli = importlib.import_module(f"{__package__}.{argv[0]}.__main__")
    return cli.main(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
