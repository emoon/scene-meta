import pathlib
import tempfile
import unittest

from scenemeta.c64 import export, store
from scenemeta.c64.export import Presets, Seen
from scenemeta.c64.store import Window
from scenemeta.core.export import Variant


def variant(disks=("a.d64",), machine="pal_1541", verdict="works", reached=None,
            detail=None):
    disks = list(disks)
    return Variant(0, "floppy", disks, "", detail or {}, machine, verdict, 1,
                   len(disks) if reached is None else reached, [])


def window(disk, at, until=None, key=None, key_delay=None, pre_keys=(), note=None):
    return Window(disk, at, until, key, key_delay, list(pre_keys), note)


PRESETS = Presets("pal_1541", {
    "pal_1541": {"description": "old SID", "video": "pal", "sid": "6581", "drive": "1541"},
    "pal_1541_8580": {"description": "new SID", "video": "pal", "sid": "8580", "drive": "1541"},
    "ntsc_1541": {"video": "ntsc", "sid": "6581", "drive": "1541"}})


def entry(v=None, seen=None, groups="Booze Design", model=None):
    return export.entry("Edge of Disgrace", groups, v or variant(), seen or Seen(),
                        model, PRESETS)


TWO = ("/nas/eod-a.d64", "/nas/eod-b.d64")


class EntryTest(unittest.TestCase):
    def test_default_machine_is_left_out(self):
        self.assertEqual(entry(), {"title": "Edge of Disgrace",
                                   "group": "Booze Design", "source": "script"})

    def test_no_group(self):
        self.assertNotIn("group", entry(groups=""))

    def test_other_machine(self):
        self.assertEqual(entry(variant(machine="ntsc_1541"))["machine"], "ntsc_1541")

    def test_sid_model_picks_the_preset_that_has_it(self):
        self.assertEqual(entry(model="8580")["machine"], "pal_1541_8580")
        self.assertNotIn("sid", entry(model="8580"))

    def test_sid_model_of_the_default_says_nothing(self):
        self.assertEqual(entry(model="6581"), entry())

    def test_sid_model_no_preset_has_is_an_override(self):
        e = entry(variant(machine="ntsc_1541"), model="8580")
        self.assertEqual((e["machine"], e["sid"]), ("ntsc_1541", "8580"))
        self.assertNotIn("sid", entry(variant(machine="ntsc_1541"), model="6581"))

    def test_failing_production_still_names_its_sid(self):
        e = entry(variant(machine="ntsc_1541", verdict="no-activity"), model="8580")
        self.assertEqual((e["machine"], e["result"]), ("pal_1541_8580", "unknown"))

    def test_failing_production_has_no_machine(self):
        e = entry(variant(machine="ntsc_1541", verdict="no-activity"))
        self.assertEqual(e, {"title": "Edge of Disgrace", "group": "Booze Design",
                             "source": "script", "result": "unknown"})
        self.assertEqual(entry(variant(verdict="crash"))["result"], "broken")

    def test_works_then_crash_keeps_its_machine(self):
        e = entry(variant(machine="ntsc_1541", verdict="works-then-crash"))
        self.assertEqual((e["machine"], e["result"]), ("ntsc_1541", "crashes-later"))

    def test_events_to_a_tenth_of_a_second(self):
        e = entry(variant(TWO + ("/nas/eod-c.d64",)), Seen(windows=[
            window(2, 92.04, key="Return", key_delay=20.06),
            window(3, 666.0, until=700.44)]))
        self.assertEqual(e["disks"], ["eod-a.d64", "eod-b.d64", "eod-c.d64"])
        self.assertEqual(e["events"], [
            {"at": 92.0, "disk": 2}, {"at": 112.1, "key": "return"},
            {"at": 666.0, "disk": 3, "until": 700.4}])

    def test_a_key_with_no_delay_follows_its_disk_by_5_s(self):
        e = entry(variant(TWO), Seen(windows=[window(2, 92.04, key="space")]))
        self.assertEqual(e["events"], [{"at": 92.0, "disk": 2},
                                       {"at": 97.0, "key": "space"}])

    def test_short_of_the_last_disk_says_so(self):
        e = entry(variant(TWO + ("c",), reached=2), Seen(windows=[window(2, 92)]))
        self.assertEqual(e["note"], "the sweep only reached disk 2 of 3")

    def test_window_without_a_known_insert_is_no_swap(self):
        e = entry(variant(TWO, reached=1), Seen("boot_fresh", True, "side B boots alone", windows=[
            window(2, None, note="reset and reload")]))
        self.assertNotIn("events", e)
        self.assertEqual((e["kind"], e["source"]), ("boot_fresh", "ai"))
        self.assertEqual(e["note"], "side B boots alone; disk 2: reset and reload")

    def test_keys_before_the_inserts_are_events_in_time_order(self):
        e = entry(variant(TWO + ("c",)), Seen("flips", True, "menu", windows=[
            window(2, 200, pre_keys=[[60.92, "space"]]),
            window(3, 900, pre_keys=[[500, "space"], [30, "F1"]])]))
        self.assertEqual(e["events"], [
            {"at": 30, "key": "f1"}, {"at": 60.9, "key": "space"},
            {"at": 200, "disk": 2}, {"at": 500, "key": "space"},
            {"at": 900, "disk": 3}])

    def test_hand_made_schedule_runs_whatever_the_sweep_saw(self):
        e = entry(variant(TWO, verdict="no-activity", reached=1),
                  Seen("flips", True, "needs Return", windows=[window(2, 300)]))
        self.assertNotIn("result", e)
        self.assertEqual(e["events"], [{"at": 300, "disk": 2}])

    def test_disks_that_do_not_follow_each_other_have_no_events(self):
        for cls in ("standalone", "collection"):
            e = entry(variant(TWO), Seen(cls, windows=[window(2, 300)]))
            self.assertEqual(e["kind"], cls)
            self.assertNotIn("events", e)
            self.assertNotIn("note", e)

    def test_broken_by_hand(self):
        e = entry(variant(TWO, machine="ntsc_1541"),
                  Seen("broken", True, "protection trap", windows=[window(2, 300)]))
        self.assertEqual((e["result"], e["source"], e["note"]),
                         ("broken", "ai", "protection trap"))
        self.assertNotIn("kind", e)
        self.assertNotIn("events", e)
        self.assertNotIn("machine", e)

    def test_boot_disk_counts_from_one(self):
        e = entry(variant(TWO), Seen("collection", boot_disk=1, boot_file="structural"))
        self.assertEqual((e["boot_disk"], e["boot_file"]), (2, "structural"))
        self.assertNotIn("boot_disk", entry(seen=Seen(boot_file="demo")))


class SeenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = store.Store(pathlib.Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_nothing_known(self):
        self.assertEqual(export.seen(self.db, 1, variant(TWO, detail={"boot_file": ""})),
                         Seen())

    def test_sweeps_boot_file(self):
        v = variant(TWO, detail={"boot_disk": 1, "boot_file": "demo"})
        got = export.seen(self.db, 1, v)
        self.assertEqual((got.boot_disk, got.boot_file), (1, "demo"))

    def test_hand_observation_comes_first(self):
        q = self.db.db.execute
        q("insert into variant_class values (1, 0, 'collection', 'auto', 'shared')")
        self.db.put_windows(1, 0, [])
        self.db.put_manual([{"prod": 1, "class": "flips", "note": "menu", "boot_file": "x",
                             "windows": [{"disk": 2, "insert_at": 985_248 * 20,
                                          "end": 985_248 * 30, "key": "space",
                                          "pre_keys": [[985_248 * 3, "space"]]}]}])
        detail = {"boot_disk": 1, "boot_file": "demo"}
        got = export.seen(self.db, 1, variant(TWO, detail=detail))
        self.assertEqual(got, Seen("flips", True, "menu", 0, "x", [
            Window(2, 20.0, 30.0, "space", None, [[3.0, "space"]], None)]))
        # The set it was made for is gone: the media now finds one disk.
        self.assertEqual(export.seen(self.db, 1, variant(detail=detail)),
                         Seen(boot_disk=1, boot_file="demo"))


if __name__ == "__main__":
    unittest.main()
