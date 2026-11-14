#!/usr/bin/env python3
"""Turn VICE's embedded ROM headers into the ROM files a stock VICE install
lacks (Debian's package ships none).

    python3 -m scenedb.c64.tools.extract_roms <vice/include/embedded> [roms-dir]
"""
import pathlib
import re
import sys

# Header -> path under the ROM dir, named as VICE looks them up.
WANTED = {
    "c64kernal.h": "C64/kernal-901227-03.bin",
    "c64basic.h": "C64/basic-901226-01.bin",
    "c64chargen.h": "C64/chargen-901225-01.bin",
    "drivedos1541.h": "DRIVES/dos1541-325302-01+901229-05.bin",
    "drived1541II.h": "DRIVES/d1541II-251968-03.bin",
}


def main(src, dst="roms"):
    dst = pathlib.Path(dst)
    for header, name in WANTED.items():
        text = (pathlib.Path(src) / header).read_text()
        data = bytes(int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", text))
        (dst / name).parent.mkdir(parents=True, exist_ok=True)
        (dst / name).write_bytes(data)
        print(name, len(data))


if __name__ == "__main__":
    main(*sys.argv[1:])
