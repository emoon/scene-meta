import contextlib
import io
import pathlib
import tempfile
import tomllib
import unittest
from unittest import mock

from scenemeta import document
from scenemeta.amiga import export, gate, player
from scenemeta.amiga.store import Store
from scenemeta.core import gatelog, result
from scenemeta.core.catalog import Production
from scenemeta.core.errors import CannotPlay
from scenemeta.core.export import Variant
from scenemeta.core.gate import Judgement
from scenemeta.core.result import Key, Swap

MACHINES = ('default = "a500"\n\n[a500]\ncpu = "68000"\n\n'
            '[a600]\ncpu = "68000"\n\n[a1200]\ncpu = "68ec020"\n')


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

    def test_events_to_a_tenth_of_a_second_and_a_key_only_when_pressed(self):
        e = entry(variant(kind="floppy", disks=["/nas/DD-A.adf", "/nas/DD-B.dms", "/nas/DD-C.dms"],
                          swaps=[Swap(2, 536.88, "poll+click", key="lmb"),
                                 Swap(3, 800.0, "poll")]))
        self.assertEqual(e["disks"], ["DD-A.adf", "DD-B.dms", "DD-C.dms"])
        self.assertEqual(e["events"], [{"at": 536.9, "disk": 2},
                                       {"at": 541.9, "key": "lmb"},
                                       {"at": 800.0, "disk": 3}])

    def test_a_swaps_key_is_an_event_when_it_was_pressed_else_5_s_on(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c", "d"], swaps=[
            Swap(2, 80.0, "poll+click+rclick", key="rmb", key_at=90.0),
            Swap(3, 536.88, "poll+click", key="lmb", key_at=541.88),
            Swap(4, 800.0, "scheduled", key="p2fire")]))
        self.assertEqual(e["events"], [
            {"at": 80.0, "disk": 2}, {"at": 90.0, "key": "rmb"},
            {"at": 536.9, "disk": 3}, {"at": 541.9, "key": "lmb"},
            {"at": 800.0, "disk": 4}, {"at": 805.0, "key": "p2fire"}])

    def test_events_are_in_the_order_they_happen(self):
        v = variant(kind="floppy", disks=["a", "b"],
                    swaps=[Swap(2, 80.0, "poll", key="lmb", key_at=80.0)])
        v.keys = [Key(120.0, "space"), Key(30.0, "lmb")]
        self.assertEqual(entry(v)["events"], [
            {"at": 30.0, "key": "lmb"}, {"at": 80.0, "disk": 2},
            {"at": 80.0, "key": "lmb"}, {"at": 120.0, "key": "space"}])

    def test_keys_with_no_swap(self):
        v = variant(kind="floppy", disks=["a", "b"])
        v.keys = [Key(86.13, "lmb")]
        e = entry(v)
        self.assertEqual(e["events"], [{"at": 86.1, "key": "lmb"}])

    def test_short_of_the_last_disk_says_so(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c"], reached=1))
        self.assertEqual(e["note"], "the sweep only reached disk 1 of 3")

    def test_a_swap_into_another_drive_says_which(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c"], drives=2,
                          swaps=[Swap(3, 225.0, "poll", drive=2)]))
        self.assertEqual(e["events"], [{"at": 225.0, "disk": 3, "drive": 2}])

    def test_a_swap_with_a_window_says_its_until(self):
        e = entry(variant(kind="floppy", disks=["a", "b", "c"], swaps=[
            Swap(2, 536.88, "poll", key="lmb", key_at=541.88, until=566.88),
            Swap(3, 800.0, "poll")]))
        self.assertEqual(e["events"], [
            {"at": 536.9, "disk": 2, "until": 566.9},
            {"at": 541.9, "key": "lmb"}, {"at": 800.0, "disk": 3}])

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
        self.assertNotIn("events", e)

    def test_use_hd_takes_the_hd_variant(self):
        e = entry(variant(0, kind="floppy", disks=["a", "b"]),
                  variant(1, verdict="no-activity"), cls=("use-hd", "the LHA holds both disks"))
        self.assertEqual((e["boot"], e["result"]), ("hd", "unknown"))
        self.assertNotIn("disks", e)


class RunsTest(unittest.TestCase):
    """The entries of a production's runs, as the gate is asked them."""

    def alive(self, *variants):
        return export.alive("Desert Dream", None, list(variants), "a500")

    def run_of(self, idx, machine, verdict="works", chosen=False, **kw):
        v = variant(idx, machine=machine, verdict=verdict, **kw)
        v.chosen = chosen
        return v

    def test_the_chosen_run_of_each_variant_then_the_others(self):
        got = self.alive(
            self.run_of(0, "a600"),
            self.run_of(0, "a1200", "works-then-crash", chosen=True),
            self.run_of(1, "a3000", chosen=True, kind="floppy", disks=["d.adf"]),
            self.run_of(1, "a4000", kind="floppy", disks=["d.adf"]))
        self.assertEqual(
            [(e.get("boot", "hd"), e["machine"], e.get("result")) for e in got],
            [("floppy", "a3000", None), ("hd", "a1200", "crashes-later"),
             ("hd", "a600", None), ("floppy", "a4000", None)])

    def test_the_first_is_the_entry_of_the_run_that_got_furthest(self):
        runs = [self.run_of(0, "a600"), self.run_of(0, "a1200", chosen=True)]
        self.assertEqual(self.alive(*runs)[0], entry(*runs, groups=None))

    def test_a_run_the_production_never_came_alive_in_is_no_entry(self):
        self.assertEqual(self.alive(
            self.run_of(0, "a600", "crash"),
            self.run_of(0, "a1200", "no-activity", chosen=True)), [])

    def test_of_two_runs_as_good_the_one_made_first(self):
        got = self.alive(self.run_of(0, "a500", "crash", chosen=True),
                         self.run_of(0, "a600"), self.run_of(0, "a1200"))
        self.assertEqual([e["machine"] for e in got], ["a600", "a1200"])

    def test_a_production_no_entry_of_passed_is_unknown_and_says_why(self):
        runs = [self.run_of(0, "a500", "crash", chosen=True),
                self.run_of(0, "a600"),
                self.run_of(1, "a1200", chosen=True, kind="floppy",
                            disks=["a", "b"], swaps=[Swap(2, 80.0, "poll")])]
        self.assertEqual(
            export.failed("Desert Dream", "Kefrens", runs, "a500"),
            {"title": "Desert Dream", "group": "Kefrens", "source": "script",
             "boot": "floppy", "result": "unknown", "disks": ["a", "b"],
             "note": "the sweep saw works on a1200; no entry of it passed"
                     " the gate"})


def judgement(passed):
    return Judgement(passed, "said", seeds=((1, Judgement(passed, "on 1")),))


class ExportTest(unittest.TestCase):
    """The export of a sweep database into data files, both thrown away;
    the entries on the machines of ``self.passing`` pass the gate."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name) / "data"
        self.data.mkdir()
        (self.data / "machines.toml").write_text(MACHINES)
        self.db = Store(pathlib.Path(tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.passing, self.played, self.lines, self.classes = set(), [], [], {}

        def one(prod, entry, default, each):
            machine = entry.get("machine", default)
            self.played.append((prod, machine))
            return judgement(machine in self.passing), "aa"
        for patch in (
                mock.patch.object(gate, "_one", side_effect=one),
                mock.patch.object(gate.media, "download_sha256",
                                  return_value="aa"),
                mock.patch.object(player.media, "require_mirror"),
                mock.patch.object(export.classes, "load",
                                  side_effect=lambda: self.classes)):
            patch.start()
            self.addCleanup(patch.stop)

    def swept(self, prod, *machines, verdict="works"):
        """A production the sweep ran on each of ``machines``, the first
        its chosen run."""
        runs = [result.Run(m, 180.0, verdict, 60.0) for m in machines]
        self.db.put_result(
            Production(prod, f"Demo {prod}", "Group", ("ocs",), ("Demo",),
                       "1991", []),
            [], [result.Variant("hd", [], "", {"command": '"demo"\n'}, runs)])

    def has(self, prod, **entry):
        """An entry the data files hold before the export."""
        entry = {"title": f"Demo {prod}", **entry}
        (self.data / "d.toml").write_text(
            document.render("demozoo", prod, entry) + "\n")
        return entry

    def export(self, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.errors = export.run(
                self.db, data=self.data, jobs=1,
                log=lambda line, **_: self.lines.append(line), **kw)
        self.report = out.getvalue().splitlines()
        return {int(k): e for k, e in tomllib.loads(
            (self.data / "d.toml").read_text()).get("demozoo", {}).items()}

    def passed(self, prod, entry):
        return gatelog.passes([r for r in self.db.gated() if r.prod == prod],
                              entry)

    def test_no_running_script_entry_without_a_pass_in_the_log(self):
        self.passing = {"a500", "a1200"}
        self.swept(7, "a500")
        self.swept(8, "a600", "a1200")
        self.swept(9, "a600")
        self.swept(10, "a500", verdict="no-activity")
        got = self.export()
        self.assertEqual(
            {p: (e.get("machine", "a500"), e.get("result"))
             for p, e in got.items()},
            {7: ("a500", None), 8: ("a1200", None), 9: ("a500", "unknown"),
             10: ("a500", "unknown")})
        for prod, entry in got.items():
            self.assertEqual(self.passed(prod, entry), "result" not in entry,
                             prod)
        self.assertEqual(self.errors, 0)

    def test_the_best_run_fails_and_the_second_passes(self):
        self.passing = {"a1200"}
        self.swept(7, "a600", "a1200", "a3000")
        self.assertEqual(self.export()[7], {
            "title": "Demo 7", "group": "Group", "source": "script",
            "machine": "a1200"})
        self.assertEqual(self.played, [(7, "a600"), (7, "a1200")])
        self.assertEqual(self.lines, ["7 Demo 7: fail (said), then pass (said)"])

    def test_after_three_failures_it_is_unknown_with_a_note(self):
        self.passing = {"a4000"}
        self.swept(7, "a600", "a1200", "a3000", "a4000")
        self.assertEqual(self.export()[7], {
            "title": "Demo 7", "group": "Group", "source": "script",
            "result": "unknown",
            "note": "the sweep saw works on a600; no entry of it passed the"
                    " gate"})
        self.assertEqual([m for _, m in self.played], ["a600", "a1200", "a3000"])
        self.assertEqual(
            self.lines,
            ["7 Demo 7: fail (said), then fail (said), then fail (said)"])

    def test_an_entry_somebody_worked_on_is_kept_and_what_differs_reported(self):
        for source in ("ai", "verified"):
            self.passing = {"a600"}
            self.swept(7, "a600")
            before = self.has(7, source=source, machine="a1200")
            self.assertEqual(self.export()[7], before)
            self.assertEqual(self.played, [], "not gated in its place")
            self.assertEqual(self.report, [
                "0 added, 0 replaced, 1 kept as edited; 0 files written",
                "differs: [demozoo.7] Demo 7: machine: has 'a1200', sweep"
                " says 'a600'"])

    def test_a_script_entry_is_replaced(self):
        self.passing = {"a600"}
        self.swept(7, "a600")
        self.has(7, source="script", machine="a1200")
        self.assertEqual(self.export()[7]["machine"], "a600")

    def test_a_hand_class_is_written_as_the_sweep_saw_it(self):
        self.classes = {7: ("menu", "part list")}
        self.swept(7, "a600")
        got = self.export()[7]
        self.assertEqual((got["source"], got["machine"], got["kind"]),
                         ("ai", "a600", "menu"))
        self.assertEqual(self.played, [])

    def test_exported_again_nothing_is_played(self):
        self.passing = {"a600"}
        self.swept(7, "a600")
        first = self.export()
        del self.played[:], self.lines[:]
        self.assertEqual(self.export(), first)
        self.assertEqual((self.played, self.lines), ([], []))

    def test_a_production_that_could_not_be_played_stays_as_it_is(self):
        self.swept(7, "a600")
        before = self.has(7, source="script", machine="a1200")
        gate._one.side_effect = CannotPlay("no Kickstart ROM")
        self.assertEqual(self.export()[7], before)
        self.assertEqual((self.errors, self.lines),
                         (1, ["7 Demo 7: error: no Kickstart ROM"]))

    def test_only_the_productions_asked_for(self):
        self.passing = {"a600"}
        self.swept(7, "a600")
        self.swept(8, "a600")
        self.assertEqual(list(self.export(ids={8})), [8])
        self.assertEqual(self.played, [(8, "a600")])


if __name__ == "__main__":
    unittest.main()
