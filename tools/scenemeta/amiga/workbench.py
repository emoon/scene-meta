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
- Disk-based libraries (LIBS_DIR: they come from a Workbench disk, and
  ``require_libs`` stops a run without them): Motion Blur gurus when mathieeedoubbas.library does not open. A
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

from ..core.errors import CannotPlay
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
#       if (out = Output()): Write(out, "\n", 1)  # open lazy KS2+/3.0 CON: (BPLEN=1)
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
    "43fa0060"      # 6c lea     dosname(pc),a1
    "7024"          # 70 moveq   #36,d0
    "4eaefdd8"      # 72 jsr     OpenLibrary(a6)
    "4a80"          # 76 tst.l   d0
    "6750"          # 78 beq.s   done
    "2a40"          # 7a movea.l d0,a5
    "2c4d"          # 7c movea.l a5,a6
    "41fa005a"      # 7e lea     ramenv(pc),a0
    "2208"          # 82 move.l  a0,d1
    "4eaeff88"      # 84 jsr     CreateDir(a6)
    "4a80"          # 88 tst.l   d0              (0 when it exists)
    "6706"          # 8a beq.s   lock
    "2200"          # 8c move.l  d0,d1
    "4eaeffa6"      # 8e jsr     UnLock(a6)
    "41fa0046"      # 92 lock: lea ramenv(pc),a0
    "2208"          # 96 move.l  a0,d1
    "74fe"          # 98 moveq   #ACCESS_READ,d2
    "4eaeffac"      # 9a jsr     Lock(a6)
    "2400"          # 9e move.l  d0,d2
    "670a"          # a0 beq.s   con
    "41fa003e"      # a2 lea     envname(pc),a0
    "2208"          # a6 move.l  a0,d1
    "4eaefd9c"      # a8 jsr     AssignLock(a6)
    "4eaeffc4"      # ac con: jsr Output(a6)
    "2200"          # b0 move.l  d0,d1
    "670c"          # b2 beq.s   close
    "41fa0030"      # b4 lea     nl(pc),a0
    "2408"          # b8 move.l  a0,d2
    "7601"          # ba moveq   #1,d3
    "4eaeffd0"      # bc jsr     Write(a6)
    "224d"          # c0 close: movea.l a5,a1
    "2c780004"      # c2 movea.l 4.w,a6
    "4eaefe62"      # c6 jsr     CloseLibrary(a6)
    "7000"          # ca done: moveq #0,d0
    "4e75"          # cc rts
) + b"dos.library\0RAM:ENV\0ENV\0\n\0"   # ce, da, e2, e6


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
    """``root``/``name``, matched without case as AmigaDOS would; None
    when a file of the tree has the name, so no directory can."""
    for p in root.iterdir():
        if p.name.lower() == name:
            return p if p.is_dir() else None
    return root / name


def require_libs(libs_dir=None):
    """Raise unless the libraries no run does without are there: without
    them a demo that opens one ends at the prompt, and the run reads as a
    production doing nothing."""
    libs_dir = config.LIBS_DIR if libs_dir is None else libs_dir
    have = ({p.name.lower() for p in libs_dir.iterdir()}
            if libs_dir.is_dir() else set())
    if missing := sorted(ALWAYS_LIBS - have):
        raise CannotPlay(f"no {', '.join(missing)} in {libs_dir}")


def _is_packer_lib(name):
    """True for an XPK sub-library (lives in ``LIBS:compressors/``)."""
    low = name.lower()
    return low.startswith(PACKER_PREFIX) and low != "xpkmaster.library"


def assign_lines(assigns):
    """AmigaDOS ``Assign`` lines for a mapping or sequence of ``(name, path)``
    pairs."""
    if not assigns:
        return ""
    items = assigns.items() if isinstance(assigns, dict) else assigns
    out = []
    for name, path in items:
        vol = name.rstrip(":")
        target = f'"{vol}:"' if " " in vol else f"{vol}:"
        out.append(f'Assign >NIL: {target} "{path}"\n')
    return "".join(out)


def _iter_libs(libs_dir):
    """All library files under ``libs_dir`` and its ``compressors/`` subdir."""
    seen = set()
    for p in sorted(libs_dir.iterdir()):
        if p.is_file():
            seen.add(p.name.lower())
            yield p
    comp = _subdir(libs_dir, "compressors")
    if comp is not None and comp.is_dir():
        for p in sorted(comp.iterdir()):
            if p.is_file() and p.name.lower() not in seen:
                seen.add(p.name.lower())
                yield p


def prepare(root, command, libs_dir=None, all_libs=False):
    """Make ``root`` boot like a Workbench disk into ``command`` (the
    startup-sequence text): the setup program runs first, and libraries
    from ``libs_dir`` the tree does not have go into its libs. When
    ``all_libs`` is True (hard-drive boots), every library in ``libs_dir``
    is copied so packed executables whose library names are compressed still
    find them. XPK compressor sub-libraries go into ``libs/compressors/``
    where ``xpkmaster.library`` opens them."""
    s = _subdir(root, "s")
    if s is None:
        raise CannotPlay("no place for the startup-sequence: the download"
                         " has a file named S")
    s.mkdir(exist_ok=True)
    (s / SETUP.split("/")[1]).write_bytes(setup_exe())
    (s / GO_ON.split("/")[1]).write_bytes(go_on_exe())
    (s / "startup-sequence").write_text(
        f"{SETUP}\n{command}", encoding="latin-1")   # AmigaDOS charset
    c = _subdir(root, "c")
    if c is not None and (not c.is_dir()
                          or "assign" not in {p.name.lower()
                                              for p in c.iterdir()}):
        c.mkdir(exist_ok=True)
        (c / "Assign").write_bytes(assign_exe())
    libs_dir = config.LIBS_DIR if libs_dir is None else libs_dir
    libs = _subdir(root, "libs")
    if not libs_dir.is_dir() or libs is None:
        return
    have = {p.name.lower() for p in libs.iterdir()} if libs.is_dir() else set()
    comp = _subdir(libs, "compressors") if libs.is_dir() else libs / "compressors"
    have_comp = ({p.name.lower() for p in comp.iterdir()}
                 if comp is not None and comp.is_dir() else set())
    wanted = (list(_iter_libs(libs_dir)) if all_libs
              else _wanted_libs(root, libs_dir))
    for lib in wanted:
        if _is_packer_lib(lib.name):
            if comp is not None and lib.name.lower() not in have_comp:
                libs.mkdir(exist_ok=True)
                comp.mkdir(exist_ok=True)
                shutil.copyfile(lib, comp / lib.name)
                have_comp.add(lib.name.lower())
        elif lib.name.lower() not in have:
            libs.mkdir(exist_ok=True)
            shutil.copyfile(lib, libs / lib.name)
            have.add(lib.name.lower())


def prepare_wb_boot(sys_root, command, boot_dir=None, assigns=()):
    """Build a Workbench boot volume at ``sys_root`` backed by ``boot_dir``
    (default ``config.A1200_BOOT``), whose ``S/Startup-Sequence`` runs
    SetPatch (loading 68060.library / enabling FPU and AGA), sets up standard
    Workbench assigns and DataTypes, adds any ``Demo:`` system dirs and
    ``assigns``, then ``CD Demo:`` and executes ``command`` (or
    ``Demo:S/Startup-Sequence`` when ``command`` is None)."""
    boot_dir = config.A1200_BOOT if boot_dir is None else boot_dir
    sys_root.mkdir(parents=True, exist_ok=True)
    for entry in boot_dir.iterdir():
        if entry.name.lower() == "s":
            continue
        os.symlink(entry.resolve(), sys_root / entry.name)
    s_dst = sys_root / "S"
    s_dst.mkdir(exist_ok=True)
    s_src = _subdir(boot_dir, "s")
    if s_src is not None and s_src.is_dir():
        for entry in s_src.iterdir():
            if entry.name.lower() == "startup-sequence":
                continue
            os.symlink(entry.resolve(), s_dst / entry.name)
    if command is None:
        launch = "If EXISTS Demo:S/Startup-Sequence\n  Execute Demo:S/Startup-Sequence\nEndIf\n"
    else:
        body = command
        if body.startswith(f"{GO_ON}\n"):
            body = body[len(GO_ON) + 1:]
        launch = body if body.endswith("\n") else body + "\n"
    startup = (
        "FailAt 21\n"
        "C:SetPatch QUIET\n"
        "C:MakeDir RAM:T RAM:Clipboards RAM:ENV RAM:ENV/Sys\n"
        "C:Assign >NIL: ENVARC: SYS:Prefs/Env-Archive\n"
        "If EXISTS ENVARC:\n"
        "  C:Copy >NIL: ENVARC: RAM:ENV ALL NOREQ\n"
        "EndIf\n"
        "C:Assign >NIL: ENV: RAM:ENV\n"
        "C:Assign >NIL: T: RAM:T\n"
        "C:Assign >NIL: CLIPS: RAM:Clipboards\n"
        "C:Assign >NIL: REXX: S:\n"
        "C:Assign >NIL: PRINTERS: DEVS:Printers\n"
        "C:Assign >NIL: KEYMAPS: DEVS:Keymaps\n"
        "C:Assign >NIL: LOCALE: SYS:Locale\n"
        "C:Assign >NIL: PREFS: SYS:Prefs\n"
        "C:Assign >NIL: LIBS: SYS:Classes ADD\n"
        "C:AddDataTypes REFRESH QUIET\n"
        "If EXISTS C:AddAudioModes\n"
        "  C:AddAudioModes >NIL: REFRESH\n"
        "EndIf\n"
        "If EXISTS Demo:Libs\n"
        "  C:Assign >NIL: LIBS: Demo:Libs ADD\n"
        "EndIf\n"
        "If EXISTS Demo:Fonts\n"
        "  C:Assign >NIL: FONTS: Demo:Fonts ADD\n"
        "EndIf\n"
        "If EXISTS Demo:Devs\n"
        "  C:Assign >NIL: DEVS: Demo:Devs ADD\n"
        "EndIf\n"
        "If EXISTS Demo:C\n"
        "  Path Demo:C ADD\n"
        "EndIf\n"
        "Echo \"\"\n"
        "CD Demo:\n"
        + assign_lines(assigns)
        + launch
    )
    (s_dst / "Startup-Sequence").write_text(startup, encoding="latin-1")


def _wanted_libs(root, libs_dir):
    """The files of ``libs_dir`` the tree under ``root`` asks for."""
    avail = list(_iter_libs(libs_dir))
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
