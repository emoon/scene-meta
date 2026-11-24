import contextlib
import io
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from scenemeta.amiga import gate, player
from scenemeta.amiga.store import Store
from scenemeta.amiga.verdict import Verdict
from scenemeta.core.errors import BadEntry, CannotPlay
from scenemeta.core import gate as core
from scenemeta.core import gatelog as core_log
from scenemeta.core.gate import Judgement, Play, Run, SwapTaken


class PlayTest(unittest.TestCase):
    ENTRY = {"title": "x", "disks": ["a.adf", "b.adf"],
             "events": [{"at": 10, "disk": 2}, {"at": 15, "key": "lmb"}]}

    def play(self, run, verdict=Verdict("works", 9)):
        record = Play(True, swaps=(SwapTaken(2, True),))
        outcome = player.Outcome("a500", verdict, [], None, record)
        ready = player.Ready(self.ENTRY, None, None)
        with mock.patch.object(player.Ready, "play", autospec=True,
                               return_value=outcome) as self.played:
            got = gate._play(ready, run)
        self.assertIs(got, record)
        (played,), kw = self.played.call_args
        return played.entry, kw

    def test_a_run_is_the_entry_as_the_gate_changed_it_on_the_runs_seed(self):
        entry, kw = self.play(Run(3, late=True))
        self.assertEqual(entry["events"], [{"at": 40, "disk": 2},
                                           {"at": 45, "key": "lmb"}])
        self.assertEqual(kw["seed"], 3)

    def test_late_runs_as_long_as_its_later_disk_needs(self):
        _, kw = self.play(Run(1, late=True))
        self.assertEqual(kw["frames"], (40 + 5) * 50 + player.TAIL_FRAMES)

    def test_without_a_key_runs_as_long_as_the_entry_as_written(self):
        entry, kw = self.play(Run(1, without=0))
        self.assertEqual(entry["events"], [{"at": 10, "disk": 2}])
        self.assertEqual(kw["frames"], (10 + 5) * 50 + player.TAIL_FRAMES)

    def test_an_emulator_that_showed_nothing_is_an_error_not_a_fail(self):
        with self.assertRaisesRegex(CannotPlay, "no-samples \\(timeout\\)"):
            self.play(Run(1), Verdict("error", 0, crash="no-samples (timeout)"))


class OneTest(unittest.TestCase):
    ENTRY = {"title": "x", "events": [{"at": 10, "disk": 2}]}

    def one(self, play, each=map):
        with mock.patch.object(player, "ready") as self.ready, \
                mock.patch.object(gate.media, "download_sha256",
                                  return_value="aa") as self.sha256, \
                mock.patch.object(gate, "_play", side_effect=play) as self.play:
            return gate._one(7, self.ENTRY, "a500", each)

    def test_the_gates_judgement_of_the_entrys_runs(self):
        said, _ = self.one(lambda ready, run: Play(
            True, swaps=(SwapTaken(2, run.seed != 2),)))
        self.assertEqual(str(said), "fail (seed 2: disk 2 never loaded)")
        self.ready.assert_called_once_with(7, self.ENTRY, "a500")
        self.assertEqual(
            self.play.call_args_list,
            [mock.call(self.ready.return_value, r)
             for r in core.runs(self.ENTRY)])

    def test_a_pass(self):
        said, _ = self.one(
            lambda ready, run: Play(True, swaps=(SwapTaken(2, True),)))
        self.assertEqual(str(said), "pass (3 seeds: came alive, no crash, every"
                         " disk loaded; disk 2 until 40.0)")

    def test_the_sha256_is_of_the_productions_download(self):
        _, sha256 = self.one(lambda ready, run: Play(True))
        self.assertEqual(sha256, "aa")
        self.sha256.assert_called_once_with(7)

    def test_a_run_that_cannot_be_played_is_the_entrys_error(self):
        def cannot(ready, run):
            raise CannotPlay("the emulator gave nothing")
        with self.assertRaisesRegex(CannotPlay, "gave nothing"):
            self.one(cannot)

    def test_the_runs_are_made_through_the_callers_map(self):
        made = []

        def each(play, runs):
            made.extend(runs)
            return map(play, runs)
        self.one(lambda ready, run: Play(True, swaps=(SwapTaken(2, True),)), each)
        self.assertEqual(made, core.runs(self.ENTRY))


def judgement(*passed):
    """A Judgement of an entry that did as ``passed`` says on seeds 1.."""
    seeds = tuple((i + 1, Judgement(p, f"on {i + 1}"))
                  for i, p in enumerate(passed))
    return Judgement(all(passed), "said", seeds=seeds)


class StoreCase(unittest.TestCase):
    """A sweep database and an empty data directory, both thrown away."""
    ENTRIES = {7: {"title": "x"}, 8: {"title": "y"}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name) / "data"
        self.data.mkdir()
        self.db = Store(pathlib.Path(tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.lines = []
        for patch in (
                mock.patch.object(gate.replay, "all_entries",
                                  return_value=self.ENTRIES),
                mock.patch.object(gate.export, "default_machine",
                                  return_value="a500"),
                mock.patch.object(player.media, "require_mirror")):
            patch.start()
            self.addCleanup(patch.stop)

    def log(self, line, **kw):
        self.lines.append(line)

    def run_gate(self, ids, one):
        with mock.patch.object(gate, "_one", side_effect=one):
            return gate.run(ids, self.db, data=self.data, jobs=1, log=self.log)

    def stored(self):
        return [(r.prod, r.seed, r.passed, r.reason, r.sha256, r.player)
                for r in self.db.gated()]


class RunTest(StoreCase):
    def test_one_line_per_production(self):
        said = {7: judgement(True, True), 8: judgement(True, False)}
        errors = self.run_gate([8, 7], lambda p, *a: (said[p], "aa"))
        self.assertEqual(errors, 0)
        self.assertEqual(self.lines, ["7 x: pass (said)", "8 y: fail (said)"])

    def test_a_record_is_stored_per_entry_and_seed(self):
        said = {7: judgement(True, False, True), 8: judgement(True, True)}
        with mock.patch.object(player, "VERSION", "9"):
            self.run_gate([7, 8], lambda p, e, default, each: (said[p], f"sha{p}"))
        self.assertEqual(self.stored(), [
            (7, 1, True, "on 1", "sha7", "9"), (7, 2, False, "on 2", "sha7", "9"),
            (7, 3, True, "on 3", "sha7", "9"),
            (8, 1, True, "on 1", "sha8", "9"), (8, 2, True, "on 2", "sha8", "9")])

    def test_the_runs_of_one_entry_are_made_in_parallel(self):
        # Passes only when two runs of the entry are in flight at once.
        together = threading.Barrier(2, timeout=10)

        def play(ready, run):
            together.wait()
            return Play(True)
        with mock.patch.object(player, "ready"), \
                mock.patch.object(gate.media, "download_sha256",
                                  return_value="aa"), \
                mock.patch.object(gate, "_play", side_effect=play):
            gate.run([7], self.db, data=self.data, jobs=2, log=self.log)
        self.assertEqual(self.lines, ["7 x: pass (2 seeds: came alive, no crash)"])
        self.assertEqual(self.stored(), [
            (7, 1, True, "came alive, no crash", "aa", player.VERSION),
            (7, 2, True, "came alive, no crash", "aa", player.VERSION)])

    def test_an_id_with_no_entry_is_said_and_not_played(self):
        errors = self.run_gate([9], lambda *a: self.fail("played"))
        self.assertEqual((errors, self.lines),
                         (0, ["9: no entry in the data files"]))

    def test_what_cannot_be_played_is_counted_and_not_stored(self):
        self.run_gate([7], lambda *a: (judgement(True, True), "aa"))
        del self.lines[:]

        def cannot(*a):
            raise CannotPlay("no Kickstart ROM")
        errors = self.run_gate([7, 8], cannot)
        self.assertEqual(errors, 1 + 1)
        self.assertEqual(self.lines, ["7 x: error: no Kickstart ROM",
                                      "8 y: error: no Kickstart ROM"])
        # What the gate saw of 7 before stays; nothing is made up of 8.
        self.assertEqual([r[:3] for r in self.stored()],
                         [(7, 1, True), (7, 2, True)])
        self.assertEqual(
            [(e.prod, e.reason, e.entry) for e in self.db.gate_errors()],
            [(p, "no Kickstart ROM", core_log.name(self.ENTRIES[p]))
             for p in (7, 8)])

    def test_nothing_is_written_into_the_data_files(self):
        self.run_gate([7, 8], lambda *a: (judgement(True, False), "aa"))
        self.assertEqual(list(self.data.iterdir()), [])


class EveryEntryTest(StoreCase):
    """``run`` without ids: the entries the log holds no judgement of."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(gate.media, "download_sha256",
                                  side_effect="sha{}".format)
        patch.start()
        self.addCleanup(patch.stop)

    def every(self, one=None):
        del self.lines[:]
        played = []

        def play(p, *a):
            played.append(p)
            return one(p) if one else (judgement(True, True), f"sha{p}")
        errors = self.run_gate(None, play)
        return played, errors

    def test_every_entry_of_the_data_files_is_gated(self):
        self.assertEqual(self.every(), ([7, 8], 0))
        self.assertEqual(self.lines, ["7 x: pass (said)", "8 y: pass (said)"])
        self.assertEqual({r[0] for r in self.stored()}, {7, 8})

    def test_an_entry_judged_pass_or_fail_is_not_played_again(self):
        self.run_gate([7], lambda *a: (judgement(True, False), "sha7"))
        self.assertEqual(self.every(), ([8], 0))
        self.assertEqual(self.lines, ["8 y: pass (said)"])
        self.assertEqual(self.every(), ([], 0))
        self.assertEqual([r[:3] for r in self.stored() if r[0] == 7],
                         [(7, 1, True), (7, 2, False)])

    def test_an_entry_changed_since_is_played_again(self):
        self.every()
        gate.replay.all_entries.return_value = {
            **self.ENTRIES, 8: {"title": "y", "machine": "a1200"}}
        self.assertEqual(self.every()[0], [8])

    def test_another_download_or_player_is_played_again(self):
        self.every()
        gate.media.download_sha256.side_effect = {7: "new", 8: "sha8"}.get
        self.assertEqual(self.every()[0], [7])
        with mock.patch.object(player, "VERSION", "next"):
            self.assertEqual(self.every()[0], [7, 8])

    def test_what_could_not_be_played_is_tried_again(self):
        def one(p):
            if p == 8:
                raise CannotPlay("no media")
            return judgement(True, True), "sha7"
        self.assertEqual(self.every(one), ([7, 8], 1))
        self.assertEqual(self.lines, ["7 x: pass (said)",
                                      "8 y: error: no media"])
        self.assertEqual(self.every(one), ([8], 1))
        self.assertEqual(self.every(), ([8], 0))
        self.assertEqual(self.db.gate_errors(), [])

    def test_no_ids_given_is_not_every_entry(self):
        self.assertEqual(self.run_gate([], lambda *a: self.fail("played")), 0)
        self.assertEqual(self.lines, [])

    def test_ids_are_gated_again_whatever_the_log_holds(self):
        self.every()
        played = []
        self.run_gate([7], lambda p, *a: played.append(p)
                      or (judgement(True, True), "sha7"))
        self.assertEqual(played, [7])


class DemoteTest(unittest.TestCase):
    """Real data files: the demotions are merged into them."""
    FILE = """\
[demozoo.7]
title = "x"
source = "script"
machine = "a1200"
disks = ["a.adf", "b.adf"]
events = [{ at = 10.0, disk = 2 }]

[demozoo.8]
title = "xa"
source = "ai"

[demozoo.9]
title = "xb"
source = "script"

[demozoo.10]
title = "xc"
source = "script"

[demozoo.11]
title = "xd"
source = "script"
"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = pathlib.Path(tmp.name) / "data"
        self.data.mkdir()
        (self.data / "x.toml").write_text(self.FILE)
        self.db = Store(pathlib.Path(tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        found = gate.replay.all_entries(self.data)
        for prod, passed in ((7, (True, False)), (8, (False, True)),
                             (9, (True, True))):
            self.db.put_gate(prod, found[prod], judgement(*passed), "aa", "1")
        self.db.put_gate_error(10, found[10], "no media")
        self.lines = []
        self.sha256_of = lambda prod: "aa"
        self.version = "1"

    def demote(self, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.object(gate.media, "require_mirror"), \
                mock.patch.object(gate.media, "download_sha256",
                                  side_effect=lambda p: self.sha256_of(p)), \
                mock.patch.object(player, "VERSION", self.version):
            gate.demote(self.db, data=self.data, log=self.lines.append, **kw)
        return out.getvalue()

    def test_the_counts_and_each_list(self):
        self.demote()
        self.assertEqual(self.lines, [
            "5 entries: 1 pass, 2 fail, 1 could not be played, 1 not gated"
            " as they stand",
            "\nto demote: 1", "7 x: seed 2: on 2",
            "\nfailed, kept as edited: 1", "8 xa: seed 1: on 1",
            "\ncould not be played: 1", "10 xc: no media",
            "\nnot gated: 1", "11 xd"])

    def test_a_record_of_another_download_or_player_is_not_gated(self):
        self.sha256_of = {7: "new", 8: "aa", 9: "aa"}.get
        self.demote(write=True)
        self.assertEqual(self.lines[0], "5 entries: 1 pass, 1 fail, 1 could not"
                         " be played, 2 not gated as they stand")
        self.assertEqual(self.lines[-4:],
                         ["\nnot gated: 2", "7 x", "11 xd", ""])
        self.assertEqual((self.data / "x.toml").read_text(), self.FILE)
        del self.lines[:]
        self.version = "next"
        self.demote()
        self.assertEqual(self.lines[0], "5 entries: 0 pass, 0 fail, 1 could not"
                         " be played, 4 not gated as they stand")

    def test_without_the_mirror_nothing_is_listed_or_written(self):
        with mock.patch.object(gate.media, "require_mirror",
                               side_effect=CannotPlay("no Demozoo mirror")), \
                self.assertRaisesRegex(CannotPlay, "no Demozoo mirror"):
            gate.demote(self.db, data=self.data, log=self.lines.append,
                        write=True)
        self.assertEqual(self.lines, [])
        self.assertEqual((self.data / "x.toml").read_text(), self.FILE)

    def test_nothing_is_written_unless_asked(self):
        self.demote()
        self.assertEqual((self.data / "x.toml").read_text(), self.FILE)

    def test_written_the_failing_script_entry_is_unknown_and_no_other_changed(self):
        out = self.demote(write=True)
        self.assertIn("0 added, 1 replaced, 0 kept", out)
        self.assertEqual((self.data / "x.toml").read_text(), self.FILE.replace(
            'machine = "a1200"\ndisks = ["a.adf", "b.adf"]\n'
            'events = [{ at = 10.0, disk = 2 }]\n',
            'result = "unknown"\ndisks = ["a.adf", "b.adf"]\n'
            'note = "failed the gate: seed 2: on 2"\n'))

    def test_written_twice_the_second_demotes_nothing(self):
        self.demote(write=True)
        del self.lines[:]
        self.demote(write=True)
        self.assertIn("\nto demote: 0", self.lines)


class FirstTest(StoreCase):
    A, B, C = ({"title": "x", "machine": m} for m in ("a500", "a600", "a1200"))

    def first(self, passing, entries=None, prod=7, version=player.VERSION,
              sha256="aa"):
        """``gate.first`` of one production whose entries on the machines
        ``passing`` pass; ``self.played`` are the machines played."""
        self.played = []

        def one(prod, entry, default, each):
            self.played.append(entry["machine"])
            return judgement(True, entry["machine"] in passing), "aa"
        with mock.patch.object(gate, "_one", side_effect=one), \
                mock.patch.object(player, "VERSION", version), \
                mock.patch.object(gate.media, "download_sha256",
                                  return_value=sha256):
            (got,) = gate.first([(prod, entries or [self.A, self.B, self.C])],
                                self.db, self.data, jobs=1)
        return got

    def logged(self):
        return {(r.entry, r.passed) for r in self.db.gated()}

    def test_the_best_entry_that_passes_and_no_other_is_played(self):
        prod, ok, (entry, said) = self.first({"a500", "a600"})
        self.assertEqual((prod, ok, entry), (7, True, self.A))
        self.assertEqual(self.played, ["a500"])
        self.assertEqual([str(s) for s in said], ["pass (said)"])
        self.assertTrue(core_log.passes(self.db.gated(), self.A))

    def test_a_failed_entry_falls_to_the_next(self):
        _, _, (entry, said) = self.first({"a600"})
        self.assertEqual(entry, self.B)
        self.assertEqual(self.played, ["a500", "a600"])
        self.assertEqual([s.passed for s in said], [False, True])
        # The log is of the entry that is written.
        self.assertTrue(core_log.passes(self.db.gated(), self.B))

    def test_none_passes(self):
        _, ok, (entry, said) = self.first(set())
        self.assertEqual((ok, entry, len(said)), (True, None, 3))
        self.assertEqual(self.logged(), {(core_log.name(self.C), True),
                                         (core_log.name(self.C), False)})

    def test_a_pass_in_the_log_is_not_played_again(self):
        self.first({"a500"})
        _, _, (entry, said) = self.first(set())
        self.assertEqual((entry, said, self.played), (self.A, [], []))

    def test_a_pass_of_a_lesser_entry_stands_when_the_better_fails_again(self):
        self.first({"a600"})
        _, _, (entry, said) = self.first({"a600"})
        self.assertEqual((entry, said, self.played), (self.B, [], ["a500"]))
        self.assertTrue(core_log.passes(self.db.gated(), self.B))

    def test_a_better_entry_that_now_passes_takes_the_log(self):
        self.first({"a600"})
        _, _, (entry, _) = self.first({"a500", "a600"})
        self.assertEqual(entry, self.A)
        self.assertTrue(core_log.passes(self.db.gated(), self.A))

    def test_a_pass_by_another_player_or_of_another_download_is_played_again(self):
        for change in ({"version": "next"}, {"sha256": "new"}):
            self.first({"a500"})
            self.first({"a500"}, **change)
            self.assertEqual(self.played, ["a500"], change)

    def test_a_pass_of_another_entry_is_not_this_ones(self):
        self.first({"a500"}, [self.A])
        self.first({"a600"}, [self.B])
        self.assertEqual(self.played, ["a600"])

    def test_an_entry_that_cannot_be_played_as_written_does_not_pass(self):
        def one(prod, entry, default, each):
            if entry is self.A:
                raise BadEntry("fits none of the download's variants")
            return judgement(True, True), "aa"
        with mock.patch.object(gate, "_one", side_effect=one):
            ((_, ok, (entry, said)),) = gate.first(
                [(7, [self.A, self.B])], self.db, self.data, jobs=1)
        self.assertEqual((ok, entry), (True, self.B))
        self.assertEqual(str(said[0]), "fail (cannot be played: fits none of"
                         " the download's variants)")
        self.assertEqual(self.logged(), {(core_log.name(self.B), True)})

    def test_what_a_run_lacks_is_the_productions_error(self):
        self.first({"a500"})

        def cannot(*a):
            raise CannotPlay("no Kickstart ROM")
        with mock.patch.object(gate, "_one", side_effect=cannot):
            got = list(gate.first([(7, [self.B]), (8, [self.A])], self.db,
                                  self.data, jobs=1))
        self.assertEqual(got, [(7, False, "7 x: error: no Kickstart ROM"),
                               (8, False, "8 x: error: no Kickstart ROM")])
        self.assertTrue(core_log.passes(self.db.gated(), self.A))

    def test_nothing_to_gate_needs_no_mirror(self):
        gate.media.require_mirror.side_effect = CannotPlay("no Demozoo mirror")
        self.assertEqual(list(gate.first([], self.db, self.data)), [])


class SummaryTest(StoreCase):
    def test_the_file_counts_the_entries_per_outcome(self):
        said = {7: judgement(True, True), 8: judgement(True, False)}
        self.run_gate([7, 8], lambda p, *a: (said[p], "aa"))
        path = self.data / "summary.txt"
        self.assertEqual(gate.write_summary(self.db, path), path)
        self.assertEqual(path.read_text().splitlines()[-3:],
                         ["pass      1", "fail      1", "error     0"])

    def test_an_entry_that_could_not_be_played_is_an_error_in_it(self):
        def one(p, *a):
            if p == 8:
                raise CannotPlay("no media")
            return judgement(True, True), "aa"
        self.run_gate([7, 8], one)
        path = gate.write_summary(self.db, self.data / "summary.txt")
        self.assertEqual(path.read_text().splitlines()[-3:],
                         ["pass      1", "fail      0", "error     1"])

    def test_written_twice_of_the_same_log_it_is_the_same_file(self):
        self.run_gate([7, 8], lambda *a: (judgement(True, True), "aa"))
        first = gate.write_summary(self.db, self.data / "a.txt").read_bytes()
        again = gate.write_summary(self.db, self.data / "a.txt").read_bytes()
        self.assertEqual(first, again)

    def test_it_goes_beside_the_tools(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
                gate.config, "GATE_SUMMARY", pathlib.Path(d) / "s.txt"):
            self.assertEqual(gate.write_summary(self.db),
                             pathlib.Path(d) / "s.txt")
            self.assertTrue((pathlib.Path(d) / "s.txt").exists())


class StaleTest(StoreCase):
    def stale(self, sha256_of, version=player.VERSION):
        with mock.patch.object(gate.media, "download_sha256",
                               side_effect=sha256_of), \
                mock.patch.object(player, "VERSION", version):
            gate.stale(self.db, data=self.data, log=self.log)
        return self.lines

    def setUp(self):
        super().setUp()
        self.run_gate([7, 8], lambda p, *a: (judgement(True, True), f"sha{p}"))
        del self.lines[:]

    def test_nothing_changed_nothing_listed(self):
        self.assertEqual(self.stale("sha{}".format), [])

    def test_a_changed_download_is_listed(self):
        self.assertEqual(self.stale({7: "sha7", 8: "new"}.get),
                         ["8 y: download changed"])

    def test_a_changed_player_lists_every_entry(self):
        self.assertEqual(self.stale("sha{}".format, version="next"), [
            f"7 x: gated by player {player.VERSION}, now next",
            f"8 y: gated by player {player.VERSION}, now next"])

    def test_gated_again_it_is_no_longer_listed(self):
        self.run_gate([8], lambda *a: (judgement(True, True), "new"))
        del self.lines[:]
        self.assertEqual(self.stale({7: "sha7", 8: "new"}.get), [])

    def test_an_entry_gone_from_the_data_files_is_not_listed(self):
        gate.replay.all_entries.return_value = {7: {"title": "x"}}
        self.assertEqual(self.stale(lambda p: "new"), ["7 x: download changed"])

    def test_without_the_mirror_nothing_is_listed(self):
        gate.media.require_mirror.side_effect = CannotPlay("no Demozoo mirror")
        with self.assertRaisesRegex(CannotPlay, "no Demozoo mirror"):
            self.stale("sha{}".format)
        self.assertEqual(self.lines, [])


if __name__ == "__main__":
    unittest.main()
