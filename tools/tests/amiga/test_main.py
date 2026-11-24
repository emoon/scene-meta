import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.amiga import __main__ as cli
from scenemeta.amiga import config, expected, export, gate, store
from scenemeta.core.expected import Invalid
from scenemeta.core.gate import Judgement


class GateCommandsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = pathlib.Path(tmp.name)
        for name, path in (("RESULTS_DB", self.top / "scene.db"),
                           ("GATE_SUMMARY", self.top / "gate-summary.txt")):
            patch = mock.patch.object(config, name, path)
            patch.start()
            self.addCleanup(patch.stop)

    def main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def gated(self):
        db = store.Store()
        self.addCleanup(db.close)
        return db.gated()

    def test_replay_is_eager_unless_asked_to_be_patient(self):
        with mock.patch.object(cli.replay, "run", return_value=0) as run:
            self.main("replay", "--ids", "7")
            self.main("replay", "--ids", "7", "--patient")
        self.assertEqual([c.kwargs["patient"] for c in run.call_args_list],
                         [False, True])

    def test_sweep_of_one_machine(self):
        with mock.patch.object(cli.catalog, "productions", return_value=[]), \
                mock.patch.object(cli.sweep, "run_all") as run_all:
            self.main("sweep", "--ids", "7")
            self.main("sweep", "--ids", "7", "--machine", "a500_512k")
        self.assertEqual([c.kwargs["machine"] for c in run_all.call_args_list],
                         [None, "a500_512k"])

    def test_sweep_of_a_machine_that_is_not_one(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            self.main("sweep", "--machine", "a4000")

    def test_gate_stores_into_the_sweep_database(self):
        def run(ids, db, jobs=None):
            db.put_gate(ids[0], {"title": "x"}, Judgement(True, "", seeds=(
                (1, Judgement(True, "ok")),)), "aa", "1")
            return 0
        with mock.patch.object(gate, "run", side_effect=run):
            code, _ = self.main("gate", "--ids", "7")
        self.assertEqual(code, 0)
        self.assertEqual([(r.prod, r.seed) for r in self.gated()], [(7, 1)])

    def test_gate_without_ids_is_of_every_entry(self):
        with mock.patch.object(gate, "run", return_value=0) as run:
            self.assertEqual(self.main("gate", "--jobs", "3")[0], 0)
        self.assertIsNone(run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs, {"jobs": 3})

    def test_gate_demote_writes_only_when_asked(self):
        with mock.patch.object(gate, "demote") as demote:
            self.main("gate-demote")
            self.main("gate-demote", "--write")
        self.assertEqual([c.kwargs for c in demote.call_args_list],
                         [{"write": False}, {"write": True}])
        self.assertIsInstance(demote.call_args.args[0], store.Store)

    def test_gate_fails_when_an_entry_could_not_be_played(self):
        with mock.patch.object(gate, "run", return_value=3):
            self.assertEqual(self.main("gate", "--ids", "7")[0], 1)

    def test_export_gates_into_the_sweep_database(self):
        with mock.patch.object(export, "run", return_value=0) as run:
            self.assertFalse(self.main("export", "--ids", "7", "8",
                                       "--jobs", "3")[0])
        (db,), kw = run.call_args
        self.assertIsInstance(db, store.Store)
        self.assertEqual(kw, {"ids": {7, 8}, "jobs": 3})

    def test_export_of_everything_and_a_production_that_could_not_be_played(self):
        with mock.patch.object(export, "run", return_value=2) as run:
            self.assertEqual(self.main("export")[0], 1)
        self.assertEqual(run.call_args[1], {"ids": set(), "jobs": None})

    def test_gate_summary_writes_the_checked_in_file(self):
        code, out = self.main("gate-summary")
        self.assertFalse(code)
        self.assertEqual(out, f"wrote {config.GATE_SUMMARY}\n")
        self.assertEqual(config.GATE_SUMMARY.read_text().splitlines()[-3:],
                         ["pass      0", "fail      0", "error     0"])

    def test_gate_stale_lists_from_the_sweep_database(self):
        with mock.patch.object(gate, "stale") as stale:
            code, _ = self.main("gate-stale")
        self.assertFalse(code)
        (db,), _ = stale.call_args
        self.assertIsInstance(db, store.Store)

    def test_expected_gates_into_the_sweep_database(self):
        with mock.patch.object(expected, "run", return_value=0) as run:
            self.assertEqual(self.main("expected", "--jobs", "3")[0], 0)
        (db,), kw = run.call_args
        self.assertIsInstance(db, store.Store)
        self.assertEqual(kw, {"jobs": 3})

    def test_expected_fails_when_a_production_could_not_be_played(self):
        with mock.patch.object(expected, "run", return_value=2):
            self.assertEqual(self.main("expected")[0], 1)

    def test_an_expected_file_that_does_not_hold_stops_the_command(self):
        with mock.patch.object(expected, "run", side_effect=Invalid("bad")), \
                self.assertRaises(SystemExit) as stop:
            self.main("expected")
        self.assertEqual(stop.exception.code, f"{config.EXPECTED}:\nbad")


if __name__ == "__main__":
    unittest.main()
