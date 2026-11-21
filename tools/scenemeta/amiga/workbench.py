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
- C:Assign, when the tree has none: a launcher script assigns a name its
  parts load from (J: ``assign dev: ""``). Ours takes ``name: path`` only
  and needs Kickstart 2.

It also puts GO_ON there, for a script to run first.
"""

import os
import pathlib
import shutil
import struct

from . import config

SETUP = "s/scenemeta-setup"
# A script that runs this first goes on past a command that fails with less
# than 21: one the download lacks (the author's own fadeout) fails with 10.
# Kickstart 2 and later.
GO_ON = "s/scenemeta-go-on"

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


# 68000 code, position independent. The arguments are ``name: path``, the
# path in quotes or not:
#   if !(dos = OpenLibrary("dos.library", 36)): return 20
#   ok = (lock = Lock(path, SHARED_LOCK)) && AssignLock(name, lock)
#   CloseLibrary(dos)
#   return ok ? 0 : 20
_ASSIGN_CODE = bytes.fromhex(
    "2448"          # 00 movea.l a0,a2
    "2c780004"      # 02 movea.l 4.w,a6
    "43fa008a"      # 06 lea     dosname(pc),a1
    "7024"          # 0a moveq   #36,d0
    "4eaefdd8"      # 0c jsr     OpenLibrary(a6)
    "4a80"          # 10 tst.l   d0
    "677a"          # 12 beq.s   nodos
    "2c40"          # 14 movea.l d0,a6
    "0c1a0020"      # 16 name: cmpi.b #' ',(a2)+
    "67fa"          # 1a beq.s   name
    "538a"          # 1c subq.l  #1,a2
    "260a"          # 1e move.l  a2,d3
    "101a"          # 20 colon: move.b (a2)+,d0
    "0c000020"      # 22 cmpi.b  #' ',d0
    "6552"          # 26 bcs.s   bad             (the line ends: no name)
    "0c00003a"      # 28 cmpi.b  #':',d0
    "66f2"          # 2c bne.s   colon
    "422affff"      # 2e clr.b   -1(a2)
    "0c1a0020"      # 32 path: cmpi.b #' ',(a2)+
    "67fa"          # 36 beq.s   path
    "538a"          # 38 subq.l  #1,a2
    "0c120022"      # 3a cmpi.b  #'"',(a2)
    "6614"          # 3e bne.s   bare
    "528a"          # 40 addq.l  #1,a2
    "220a"          # 42 move.l  a2,d1
    "101a"          # 44 quoted: move.b (a2)+,d0
    "0c000020"      # 46 cmpi.b  #' ',d0
    "6510"          # 4a bcs.s   end
    "0c000022"      # 4c cmpi.b  #'"',d0
    "66f2"          # 50 bne.s   quoted
    "6008"          # 52 bra.s   end
    "220a"          # 54 bare: move.l a2,d1
    "0c1a0020"      # 56 word: cmpi.b #' ',(a2)+
    "62fa"          # 5a bhi.s   word
    "422affff"      # 5c end: clr.b -1(a2)
    "74fe"          # 60 moveq   #ACCESS_READ,d2
    "4eaeffac"      # 62 jsr     Lock(a6)
    "2400"          # 66 move.l  d0,d2
    "6710"          # 68 beq.s   bad
    "2203"          # 6a move.l  d3,d1
    "4eaefd9c"      # 6c jsr     AssignLock(a6)
    "4a80"          # 70 tst.l   d0
    "660a"          # 72 bne.s   ok
    "2202"          # 74 move.l  d2,d1           (the lock is still ours)
    "4eaeffa6"      # 76 jsr     UnLock(a6)
    "7814"          # 7a bad: moveq #20,d4
    "6002"          # 7c bra.s   close
    "7800"          # 7e ok: moveq #0,d4
    "224e"          # 80 close: movea.l a6,a1
    "2c780004"      # 82 movea.l 4.w,a6
    "4eaefe62"      # 86 jsr     CloseLibrary(a6)
    "2004"          # 8a move.l  d4,d0
    "4e75"          # 8c rts
    "7014"          # 8e nodos: moveq #20,d0
    "4e75"          # 90 rts
) + b"dos.library\0"   # 92

# 68000 code, position independent: FailAt 21. A program, as a ``failat``
# line is itself an unknown command on Kickstart 1.x and ends the script
# there; 1.x ends it at the next unknown command all the same.
#   if (cli = BADDR(FindTask(0)->pr_CLI)): cli->cli_FailLevel = 21
#   return 0
_GO_ON_CODE = bytes.fromhex(
    "2c780004"      # 00 movea.l 4.w,a6
    "93c9"          # 04 suba.l  a1,a1
    "4eaefeda"      # 06 jsr     FindTask(a6)
    "2040"          # 0a movea.l d0,a0
    "202800ac"      # 0c move.l  pr_CLI(a0),d0
    "670a"          # 10 beq.s   out
    "e588"          # 12 lsl.l   #2,d0
    "2040"          # 14 movea.l d0,a0
    "7015"          # 16 moveq   #21,d0
    "21400014"      # 18 move.l  d0,cli_FailLevel(a0)
    "7000"          # 1c out: moveq #0,d0
    "4e75"          # 1e rts
)


def setup_exe():
    """The setup program as an AmigaDOS executable."""
    return _exe(_CODE)


def go_on_exe():
    """The program GO_ON names, as an AmigaDOS executable."""
    return _exe(_GO_ON_CODE)


def assign_exe():
    """Our C:Assign as an AmigaDOS executable."""
    return _exe(_ASSIGN_CODE)


def _exe(code):
    """``code`` as an AmigaDOS executable (one code hunk)."""
    code += b"\0" * (-len(code) % 4)
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
    (s / GO_ON.split("/")[1]).write_bytes(go_on_exe())
    (s / "startup-sequence").write_text(
        f"{SETUP}\n{command}", encoding="latin-1")   # AmigaDOS charset
    c = _subdir(root, "c")
    if not c.is_dir() or "assign" not in {p.name.lower() for p in c.iterdir()}:
        c.mkdir(exist_ok=True)
        (c / "Assign").write_bytes(assign_exe())
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
