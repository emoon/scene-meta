"""What a Workbench boot gives a demo that our bare startup-sequence does not.

A hard-drive variant boots straight into the demo with nothing but the ROM.
A user's machine had run SetPatch and Workbench's preferences first, and
had the Workbench disk's libraries in LIBS:. ``prepare`` adds the parts of
that a demo can depend on to a boot directory:

- AGA. KS3.0 boots with graphics.library limited to ECS until SetPatch calls
  SetChipRev(): an OS screen deeper than 6 bitplanes fails to open (Motion
  Blur quits at once).
- Topaz 8. Without devs:system-configuration Kickstart 1.x makes the 60
  column topaz 9 the default font; Workbench's preferences set the 80 column
  topaz 8 everybody had. Count Duckula's trainer renders its scroller with
  Text() into an 8 line bitmap placed right before its own code, and a 9th
  line overwrites the next instruction.
- Disk-based libraries (LIBS_DIR, optional: they come from a Workbench
  disk): Motion Blur gurus when mathieeedoubbas.library does not open. A
  library goes in only when a file of the tree names it (a floppy fallback
  has no room for them all), apart from the math libraries.
"""

import os
import pathlib
import shutil
import struct

from . import config

SETUP = "s/scenemeta-setup"

# Copied even when no file names them: packed executables hide the names.
ALWAYS_LIBS = {"mathtrans.library", "mathieeedoubbas.library",
               "mathieeedoubtrans.library", "mathieeesingtrans.library"}
# xpkmaster.library opens its packers by a name it builds.
PACKER_PREFIX = "xpk"

# 68000 code, position independent:
#   gfx = OpenLibrary("graphics.library", 0)
#   if gfx->LibNode.lib_Version >= 39: SetChipRev(SETCHIPREV_BEST)
#   if (f = OpenFont({"topaz.font", 8})): gfx->DefaultFont = f
#   CloseLibrary(gfx)
#   if (dos = OpenLibrary("dos.library", 36)):
#       CreateDir("RAM:ENV"); AssignLock("ENV", Lock("RAM:ENV", SHARED_LOCK))
#       CloseLibrary(dos)
#   return 0
_CODE = bytes.fromhex(
    "2c780004"      # 00 movea.l 4.w,a6
    "43fa0046"      # 04 lea     gfxname(pc),a1
    "7000"          # 08 moveq   #0,d0
    "4eaefdd8"      # 0a jsr     OpenLibrary(a6)
    "2a40"          # 0e movea.l d0,a5
    "4a80"          # 10 tst.l   d0
    "6734"          # 12 beq.s   out
    "2c4d"          # 14 movea.l a5,a6
    "0c6d00270014"  # 16 cmpi.w  #39,lib_Version(a5)
    "6d06"          # 1c blt.s   font
    "70ff"          # 1e moveq   #SETCHIPREV_BEST,d0
    "4eaefc88"      # 20 jsr     SetChipRev(a6)
    "4267"          # 24 font: clr.w -(a7)          ta_Style, ta_Flags
    "3f3c0008"      # 26 move.w  #8,-(a7)           ta_YSize
    "487a0031"      # 2a pea     topaz(pc)          ta_Name
    "204f"          # 2e movea.l a7,a0
    "4eaeffb8"      # 30 jsr     OpenFont(a6)
    "508f"          # 34 addq.l  #8,a7
    "4a80"          # 36 tst.l   d0
    "6704"          # 38 beq.s   close
    "2b40009a"      # 3a move.l  d0,gb_DefaultFont(a5)
    "224d"          # 3e close: movea.l a5,a1
    "2c780004"      # 40 movea.l 4.w,a6
    "4eaefe62"      # 44 jsr     CloseLibrary(a6)
    "6000001e"      # 48 out: bra.w env
) + b"graphics.library\0topaz.font\0" + bytes.fromhex(   # 4c, 5d
    "2c780004"      # 68 env: movea.l 4.w,a6
    "43fa004c"      # 6c lea     dosname(pc),a1
    "7024"          # 70 moveq   #36,d0
    "4eaefdd8"      # 72 jsr     OpenLibrary(a6)
    "4a80"          # 76 tst.l   d0
    "673c"          # 78 beq.s   done
    "2a40"          # 7a movea.l d0,a5
    "2c4d"          # 7c movea.l a5,a6
    "41fa0046"      # 7e lea     ramenv(pc),a0
    "2208"          # 82 move.l  a0,d1
    "4eaeff88"      # 84 jsr     CreateDir(a6)
    "4a80"          # 88 tst.l   d0              (0 when it exists)
    "6706"          # 8a beq.s   lock
    "2200"          # 8c move.l  d0,d1
    "4eaeffa6"      # 8e jsr     UnLock(a6)
    "41fa0032"      # 92 lock: lea ramenv(pc),a0
    "2208"          # 96 move.l  a0,d1
    "74fe"          # 98 moveq   #ACCESS_READ,d2
    "4eaeffac"      # 9a jsr     Lock(a6)
    "2400"          # 9e move.l  d0,d2
    "670a"          # a0 beq.s   close
    "41fa002a"      # a2 lea     envname(pc),a0
    "2208"          # a6 move.l  a0,d1
    "4eaefd9c"      # a8 jsr     AssignLock(a6)
    "224d"          # ac close: movea.l a5,a1
    "2c780004"      # ae movea.l 4.w,a6
    "4eaefe62"      # b2 jsr     CloseLibrary(a6)
    "7000"          # b6 done: moveq #0,d0
    "4e75"          # b8 rts
) + b"dos.library\0RAM:ENV\0ENV\0"   # ba, c6, ce


def setup_exe():
    """The setup program as an AmigaDOS executable (one code hunk)."""
    code = _CODE + b"\0" * (-len(_CODE) % 4)
    n = len(code) // 4
    return (struct.pack(">6I", 0x3F3, 0, 1, 0, 0, n)
            + struct.pack(">2I", 0x3E9, n) + code + struct.pack(">I", 0x3F2))


def _subdir(root, name):
    """``root``/``name``, matched without case as AmigaDOS would."""
    for p in root.iterdir():
        if p.is_dir() and p.name.lower() == name:
            return p
    return root / name


def prepare(root, command, libs_dir=None):
    """Make ``root`` boot like a Workbench disk into ``command`` (the
    startup-sequence text): the setup program runs first, and libraries
    from ``libs_dir`` the tree does not have go into its libs."""
    s = _subdir(root, "s")
    s.mkdir(exist_ok=True)
    (s / SETUP.split("/")[1]).write_bytes(setup_exe())
    (s / "startup-sequence").write_text(
        f"{SETUP}\n{command}", encoding="latin-1")   # AmigaDOS charset
    libs_dir = config.LIBS_DIR if libs_dir is None else libs_dir
    if not libs_dir.is_dir():
        return
    libs = _subdir(root, "libs")
    have = {p.name.lower() for p in libs.iterdir()} if libs.is_dir() else set()
    for lib in _wanted_libs(root, libs_dir):
        if lib.name.lower() not in have:
            libs.mkdir(exist_ok=True)
            shutil.copyfile(lib, libs / lib.name)


def _wanted_libs(root, libs_dir):
    """The files of ``libs_dir`` the tree under ``root`` asks for."""
    avail = [p for p in libs_dir.iterdir() if p.is_file()]
    wanted = {p.name.lower() for p in avail} - ALWAYS_LIBS
    named = set()
    for d, _, files in os.walk(root):
        for f in files:
            data = (pathlib.Path(d) / f).read_bytes().lower()
            named |= {n for n in wanted if n.encode() in data}
            wanted -= named
    if "xpkmaster.library" in named:
        named |= {n for n in wanted if n.startswith(PACKER_PREFIX)}
    return [p for p in avail if p.name.lower() in named | ALWAYS_LIBS]
