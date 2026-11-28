import ast
import inspect
import pathlib
import tempfile
import threading
import unittest

from scenemeta.core import corpus, entries, export, gate, gatelog, gaterunner, playback
from scenemeta.core.errors import BadEntry, CannotPlay
from scenemeta.core.gate import Play
from scenemeta.core.store import Store


class RunnerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.db = Store(self.root / 'log.sqlite'); self.addCleanup(self.db.close)
        self.entry = {'title': 'demo', 'source': 'script'}
        self.played = []
        self.version = 'one'
        self.sha = 'sha'

    def one(self, prod, entry, default, each=map, areas=None):
        self.played.append((prod, entry))
        if entry.get('machine') == 'bad':
            raise BadEntry('unknown machine')
        if prod == 9:
            raise CannotPlay('missing download')
        return gate.check(entry, lambda run: Play(entry.get('machine') != 'fail'), each), self.sha

    def runner(self, one=None):
        return gaterunner.Runner(one or self.one, playback.each_played,
                                 lambda prod: self.sha, self.version, 'default')

    def run_all(self, again=False):
        return list(self.runner().each([(7, self.entry)], self.db, 1, again))

    def test_records_of_all_seeds_are_stored(self):
        self.run_all()
        self.assertEqual([(r.prod, r.seed, r.sha256, r.player) for r in self.db.gated()],
                         [(7, 1, 'sha', 'one'), (7, 2, 'sha', 'one')])

    def test_resume_skips_current_entry_and_explicit_run_repeats(self):
        self.run_all(); self.assertEqual(self.run_all(), [])
        self.run_all(True); self.assertEqual(len(self.played), 2)

    def test_cache_invalidates_on_entry_download_and_player(self):
        self.run_all()
        for change in ('entry', 'sha', 'version'):
            if change == 'entry': self.entry = {**self.entry, 'machine': 'other'}
            elif change == 'sha': self.sha = 'new'
            else: self.version = 'two'
            self.assertEqual(len(self.run_all()), 1)

    def test_cannot_play_is_logged_without_a_verdict(self):
        got = list(self.runner().each([(9, self.entry)], self.db, 1))
        self.assertFalse(got[0][1])
        self.assertEqual(self.db.gated(), [])
        self.assertEqual(self.db.gate_errors()[0].reason, 'missing download')

    def test_disappeared_download_during_cache_check_is_logged(self):
        self.run_all()
        runner = self.runner()
        def missing(prod):
            raise CannotPlay('download disappeared')
        runner.sha256_of = missing
        got = list(runner.each([(7, self.entry)], self.db, 1, again=False))
        self.assertFalse(got[0][1])
        self.assertEqual(self.db.gate_errors()[0].reason, 'download disappeared')
        self.assertEqual(len(self.db.gated()), 2)

    def test_recovery_clears_previous_missing_input(self):
        list(self.runner().each([(9, self.entry)], self.db, 1))
        good = lambda p, *args: (gate.check(self.entry, lambda r: Play(True)), 'sha')
        list(self.runner(good).each([(9, self.entry)], self.db, 1))
        self.assertEqual(self.db.gate_errors(), [])

    def test_first_tries_bad_and_failed_candidates_then_passes(self):
        candidates = [{**self.entry, 'machine': m} for m in ('bad', 'fail', 'good')]
        ((prod, ok, (entry, said)),) = self.runner().first([(7, candidates)], self.db, 1)
        self.assertTrue(ok); self.assertEqual(entry, candidates[-1])
        self.assertEqual([s.passed for s in said], [False, False, True])
        self.assertTrue(gatelog.passes(self.db.gated(), entry))

    def test_cached_pass_keeps_its_log_when_better_candidate_fails(self):
        self.run_all()
        candidates = [{**self.entry, 'machine': 'fail'}, self.entry]
        ((_, _, (entry, said)),) = self.runner().first([(7, candidates)], self.db, 1)
        self.assertEqual((entry, said), (self.entry, []))
        self.assertTrue(gatelog.passes(self.db.gated(), self.entry))

    def test_failed_first_has_no_passing_entry(self):
        ((_, ok, (entry, said)),) = self.runner().first(
            [(7, [{**self.entry, 'machine': 'fail'}])], self.db, 1)
        self.assertTrue(ok); self.assertIsNone(entry); self.assertFalse(said[0].passed)

    def test_run_pool_bounds_emulators_across_productions(self):
        active = peak = 0
        lock = threading.Lock()
        together = threading.Barrier(2, timeout=5)
        def play(run):
            nonlocal active, peak
            with lock: active += 1; peak = max(peak, active)
            together.wait()
            with lock: active -= 1
            return Play(True)
        def one(p, e, default, each=map, areas=None):
            return gate.check(e, play, each), 'sha'
        got = list(self.runner(one).each([(p, self.entry) for p in range(4)], self.db, 2))
        self.assertEqual((len(got), peak), (4, 2))

    def test_no_platform_imports_in_shared_modules(self):
        for module in (gaterunner, playback, corpus, entries):
            for node in ast.walk(ast.parse(inspect.getsource(module))):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn('amiga', node.module or '')
                    self.assertNotIn('c64', node.module or '')


class CorpusTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        self.path = self.root / 'expected.toml'
        self.path.write_text('[demozoo.7]\nexpect="plays"\n[demozoo.8]\nexpect="broken"\nwhy="jam"\n')
        self.board = self.root / 'score.txt'
        self.found = {7: {'title': 'a'}, 8: {'title': 'b'}}
        self.lines = []

    def run_corpus(self, error=False):
        def each(todo, *args):
            for p, e in todo:
                yield p, not(error and p == 8), ('8 b: error: ROM' if error and p == 8
                                                else gate.Judgement(p == 7, 'said'))
        return corpus.run(None, self.path, self.board, self.root, each,
                          log=lambda s, **kw: self.lines.append(s), read=lambda d: self.found)

    def test_shared_scoreboard_and_stable_results(self):
        self.assertEqual(self.run_corpus(), 0)
        first = self.board.read_bytes(); self.run_corpus()
        self.assertEqual(first, self.board.read_bytes())
        self.assertIn('as expected 2 of 2', first.decode())

    def test_errors_are_not_failed_plays(self):
        self.assertEqual(self.run_corpus(True), 1)
        self.assertIn('8 broken error', self.board.read_text())

    def test_invalid_corpus_does_not_write_scoreboard(self):
        self.path.write_text('[demozoo.99]\nexpect="plays"\n')
        with self.assertRaises(corpus.expected.Invalid): self.run_corpus()
        self.assertFalse(self.board.exists())
