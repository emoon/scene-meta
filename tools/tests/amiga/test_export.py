import unittest

from scenemeta.amiga import export
from scenemeta.core.export import Variant
from scenemeta.core.result import Key, Swap


def variant(idx=0, kind="hd", disks=(), command='"demo"\n', note="", machine="a500",
            verdict="works", drives=1, reached=None, swaps=()):
    disks = list(disks)
    return Variant(idx, kind, disks, note, {"command": command}, machine, verdict,
                   drives, len(disks) if reached is None else reached, list(swaps))


def entry(*variants, cls=None, groups="Kefrens"):
    return export.entry("Desert Dream", groups, list(variants), cls, "a500")


class EntryTest(unittest.TestCase):
    def test_default_machine_is_left_out(self):
        self.assertEqual(entry(variant()),
                         {"title": "Desert Dream", "group": "Kefrens", "source": "script"})

    def test_no_group(self):
        self.assertNotIn("group", entry(variant(), groups=None))

    def test_other_machine(self):
        self.assertEqual(entry(variant(machine="a1200_fast"))["machine"], "a1200_fast")

    def test_swaps_to_a_tenth_of_a_second_and_key_only_when_pressed(self):
        e = entry(variant(kind="floppy", disks=["/nas/DD-A.adf", "/nas/DD-B.dms", "/nas/DD-C.dms"],
                          swaps=[Swap(2, 536.88, "poll+click", key="lmb"),
                                 Swap(3, 800.0, "poll")]))
        self.assertEqual(e["disks"], ["DD-A.adf", "DD-B.dms", "DD-C.dms"])
        self.assertEqual(e["swaps"], [{"disk": 2, "at": 536.9, "key": "lmb"},
                                      {"disk": 3, "at": 800.0}])

    def test_key_delay_only_when_the_key_did_not_follow_by_the_usual_5_s(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c", "d"], swaps=[
            Swap(2, 80.0, "poll+click+rclick", key="rmb", key_at=90.0),
            Swap(3, 536.88, "poll+click", key="lmb", key_at=541.88),
            Swap(4, 800.0, "scheduled", key="p2fire")]))
        self.assertEqual(e["swaps"], [
            {"disk": 2, "at": 80.0, "key": "rmb", "key_delay": 10.0},
            {"disk": 3, "at": 536.9, "key": "lmb"},
            {"disk": 4, "at": 800.0, "key": "p2fire"}])

    def test_keys_with_no_swap(self):
        v = variant(kind="floppy", disks=["a", "b"])
        v.keys = [Key(86.13, "lmb")]
        e = entry(v)
        self.assertEqual(e["keys"], [{"at": 86.1, "key": "lmb"}])
        self.assertNotIn("swaps", e)

    def test_short_of_the_last_disk_says_so(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c"], reached=1))
        self.assertEqual(e["note"], "the sweep only reached disk 1 of 3")

    def test_a_swap_into_another_drive_says_which(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c"], drives=2,
                          swaps=[Swap(3, 225.0, "poll", drive=2)]))
        self.assertEqual(e["swaps"], [{"disk": 3, "drive": 2, "at": 225.0}])

    def test_second_drive(self):
        e = entry(variant(kind="floppy", disks=["a", "b"], drives=2))
        self.assertEqual(e["drives"], 2)

    def test_failing_production_has_no_machine(self):
        e = entry(variant(machine="a1200", verdict="no-activity"))
        self.assertEqual(e, {"title": "Desert Dream", "group": "Kefrens",
                             "source": "script", "result": "unknown"})
        self.assertEqual(entry(variant(verdict="crash"))["result"], "broken")

    def test_works_then_crash_keeps_its_machine(self):
        e = entry(variant(machine="a1200", verdict="works-then-crash"))
        self.assertEqual((e["machine"], e["result"]), ("a1200", "crashes-later"))

    def test_works_short_is_a_pass(self):
        self.assertNotIn("result", entry(variant(verdict="works-short")))

    def test_running_variant_wins_and_names_its_boot(self):
        # The exe does nothing from a hard drive but runs from a floppy.
        e = entry(variant(0, verdict="no-activity"),
                  variant(1, kind="floppy", disks=["disk.adf"], machine="a500_512k",
                          note='files on a floppy; hd:"demo"'))
        self.assertEqual((e["boot"], e["machine"]), ("floppy", "a500_512k"))
        self.assertNotIn("result", e)

    def test_first_variant_wins_a_tie(self):
        e = entry(variant(0), variant(1, kind="floppy", disks=["disk.adf"], machine="a1200"))
        self.assertNotIn("boot", e)
        self.assertNotIn("machine", e)

    def test_crashing_start_does_not_beat_one_that_plays_first(self):
        e = entry(variant(0, verdict="crash"), variant(1, verdict="works-then-crash"))
        self.assertEqual(e["result"], "crashes-later")

    def test_picked_executable(self):
        e = entry(variant(command='"Greenday.exe"\n', note="12 executables, picked Greenday.exe"))
        self.assertEqual(e["run"], "Greenday.exe")

    def test_the_file_is_the_one_the_sweep_stored(self):
        # Not what its note reads as: the path has a bracket of its own.
        v = variant(kind="floppy", disks=["x-launch.adf"], command=None, note=(
            "launched; patched disk 1 runs Vol:Demo (final) (2 executables,"
            " picked Demo (final))"))
        v.detail.update(run="Demo (final)", choice=True)
        self.assertEqual(entry(v)["run"], "Demo (final)")
        v.detail.update(run="only", choice=False)
        self.assertNotIn("run", entry(v))

    def test_launched_from_a_patched_disk(self):
        e = entry(variant(kind="floppy", disks=["x-launch.adf"], command="", note=(
            "launched; patched disk 1 runs Andromeda - 1992:Intro.exe"
            " (4 executables, picked Intro.exe)")))
        self.assertEqual(e["run"], "Intro.exe")

    def test_merged_set(self):
        e = entry(variant(0, kind="floppy", disks=["a", "b"], verdict="no-activity"),
                  variant(1, note="set merged into one directory; runs script Manipulations"))
        self.assertEqual((e["run"], e["boot"]), ("Manipulations", "hd"))

    def test_hand_classes(self):
        e = entry(variant(kind="floppy", disks=["a", "b"], reached=1), cls=("menu", "part list"))
        self.assertEqual((e["source"], e["kind"], e["note"]), ("ai", "menu", "part list"))
        e = entry(variant(kind="floppy", disks=["a", "b"]), cls=("broken-media", "truncated"))
        self.assertEqual(e["result"], "broken")
        self.assertNotIn("swaps", e)

    def test_use_hd_takes_the_hd_variant(self):
        e = entry(variant(0, kind="floppy", disks=["a", "b"]),
                  variant(1, verdict="no-activity"), cls=("use-hd", "the LHA holds both disks"))
        self.assertEqual((e["boot"], e["result"]), ("hd", "unknown"))
        self.assertNotIn("disks", e)


if __name__ == "__main__":
    unittest.main()
