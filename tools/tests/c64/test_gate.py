import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.c64 import __main__ as cli, config, expected, gate, player, store
from scenemeta.core import gatelog
from scenemeta.core.errors import CannotPlay
from scenemeta.core.gate import Play


class GateTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        (self.root / 'machines.toml').write_text('default="custom"\n[custom]\nvideo="ntsc"\nsid="8580"\ndrive="1541"\n')
        (self.root / 'a.toml').write_text('[demozoo.7]\ntitle="a"\nsource="script"\n'
                                      '[demozoo.8]\ntitle="aa"\nsource="script"\n'
                                      'disks=["a.d64","b.d64"]\nevents=[{at=30,disk=2}]\n')
        self.db = store.Store(self.root / 'log.sqlite'); self.addCleanup(self.db.close)
        self.lines = []
        for patch in (mock.patch.object(gate.media, 'require_mirror'),
                      mock.patch.object(gate.media, 'download_sha256', return_value='sha')):
            patch.start(); self.addCleanup(patch.stop)

    def log(self, line, **kwargs): self.lines.append(line)

    def run_gate(self, ids, fail=False):
        def ready(p, entry, default, presets):
            self.assertEqual((default, presets['custom']['video']), ('custom', 'ntsc'))
            return mock.Mock(entry=entry)
        with mock.patch.object(player, 'ready', side_effect=ready), \
             mock.patch.object(gate, '_play', return_value=Play(not fail)):
            return gate.run(ids, self.db, self.root, jobs=1, log=self.log)

    def test_entries_with_and_without_swaps_use_same_gate(self):
        self.assertEqual(self.run_gate([7, 8]), 0)
        self.assertEqual([(r.prod, r.seed) for r in self.db.gated()],
                         [(7, 1), (7, 2), (8, 1), (8, 2), (8, 3)])

    def test_empty_ids_plays_nothing_and_unknown_ids_are_reported(self):
        self.run_gate([]); self.assertEqual(self.db.gated(), [])
        self.run_gate([99]); self.assertEqual(self.lines, ['99: no entry in the data files'])

    def test_resume_and_changed_entry(self):
        self.run_gate(None)
        with mock.patch.object(player, 'ready', side_effect=AssertionError('replayed')):
            gate.run(None, self.db, self.root, jobs=1, log=self.log)
        self.run_gate([7], fail=True)
        self.assertFalse(self.db.gated()[0].passed)

    def test_missing_input_logged_as_error_and_summary(self):
        with mock.patch.object(player, 'ready', side_effect=CannotPlay('ROM missing')):
            self.assertEqual(gate.run([7], self.db, self.root, 1, self.log), 1)
        path = gate.write_summary(self.db, self.root / 'summary.txt')
        self.assertIn('error     1', path.read_text())
        self.assertEqual(self.db.gated(), [])

    def test_scoreboard_uses_actual_core_judgements(self):
        path = self.root / 'corpus.txt'
        path.write_text('[demozoo.7]\nexpect="plays"\n[demozoo.8]\nexpect="broken"\nwhy="test crash"\n')
        with mock.patch.object(player, 'ready'), \
             mock.patch.object(gate, '_play', return_value=Play(True)):
            errors = expected.run(self.db, path, self.root / 'board.txt', self.root, 1, self.log)
        self.assertEqual(errors, 0)
        self.assertIn('as expected 1 of 2', (self.root / 'board.txt').read_text())
        self.assertEqual(len(self.db.gated()), 5)


class CommandsTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        for name, value in [('RESULTS_DB', self.root / 'log.sqlite'),
                            ('GATE_SUMMARY', self.root / 'summary.txt')]:
            patch = mock.patch.object(config, name, value); patch.start(); self.addCleanup(patch.stop)

    def main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()): return cli.main(args)

    def test_gate_ids_jobs_and_default_single_worker(self):
        with mock.patch.object(gate, 'run', return_value=0) as run:
            self.assertEqual(self.main('gate', '--ids', '7', '8', '--jobs', '2'), 0)
            self.assertEqual(run.call_args.args[0], [7, 8])
            self.assertEqual(run.call_args.kwargs, {'jobs': 2})
            self.main('gate'); self.assertEqual(run.call_args.args[0], None)
            self.assertEqual(run.call_args.kwargs, {'jobs': 1})

    def test_missing_inputs_are_unsuccessful_commands(self):
        with mock.patch.object(gate, 'run', return_value=2):
            self.assertEqual(self.main('gate'), 1)

    def test_invalid_jobs_do_not_open_database(self):
        for n in ('0', '-1'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit), \
                 mock.patch.object(store, 'Store') as db:
                self.main('gate', '--jobs', n)
            db.assert_not_called()

    def test_summary_command_writes_file(self):
        self.main('gate-summary')
        self.assertTrue(config.GATE_SUMMARY.is_file())

    def test_stale_command_and_corpus_command(self):
        with mock.patch.object(gate, 'stale') as stale:
            self.main('gate-stale'); stale.assert_called_once()
        with mock.patch.object(expected, 'run', return_value=1) as run:
            self.assertEqual(self.main('expected', '--jobs', '2'), 1)
            self.assertEqual(run.call_args.kwargs, {'jobs': 2})

    def test_export_forwards_ids_and_jobs_and_keeps_manual_workflow(self):
        with mock.patch.object(cli, 'load_manual') as manual, \
             mock.patch.object(cli.export, 'run', return_value=1) as run:
            self.assertEqual(self.main('export', '--ids', '7', '--jobs', '2'), 1)
            manual.assert_called_once()
            self.assertEqual(run.call_args.kwargs, {'ids': [7], 'jobs': 2})
