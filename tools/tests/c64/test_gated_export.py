import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.c64 import export, gate, store
from scenemeta.core import catalog, gatelog, playback, result
from scenemeta.core.entries import all_entries
from scenemeta.core.errors import CannotPlay
from scenemeta.core.gate import Judgement


class ExportTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        (self.root / 'machines.toml').write_text('default="pal_1541"\n[pal_1541]\nvideo="pal"\nsid="6581"\ndrive="1541"\n[ntsc_1541]\nvideo="ntsc"\nsid="6581"\ndrive="1541"\n')
        self.db = store.Store(self.root / 'log.sqlite'); self.addCleanup(self.db.close)
        self.prod = catalog.Production(7, 'A Demo', 'Group', ('c64',), ('Demo',), '', [])
        self.played = []
        for patch in (mock.patch.object(export.sid, 'models', return_value={}),
                      mock.patch.object(gate.media, 'require_mirror'),
                      mock.patch.object(gate.media, 'download_sha256', return_value='sha')):
            patch.start(); self.addCleanup(patch.stop)

    def populate(self, verdict='works', other=False):
        runs = [result.Run('pal_1541', 180, verdict, 100)]
        if other: runs += [result.Run('ntsc_1541', 180, 'works', 100)]
        self.db.put_result(self.prod, [], [result.Variant('floppy', ['a.d64'], runs=runs)])

    def export(self, passing=(), missing=False, ids=None):
        def one(prod, entry, default, each=map, areas=None, presets=None):
            self.played.append(entry.get('machine', default))
            if missing: raise CannotPlay('ROM missing')
            passed = entry.get('machine', default) in passing
            return Judgement(passed, 'observed', ((1, Judgement(passed, 'observed')),)), 'sha'
        with mock.patch.object(gate, '_one', side_effect=one), contextlib.redirect_stdout(io.StringIO()):
            errors = export.run(self.db, self.root, ids, jobs=1, log=lambda *a, **kw: None)
        return errors, all_entries(self.root).get(7)

    def test_running_script_entry_is_written_only_after_pass(self):
        self.populate()
        errors, entry = self.export({'pal_1541'})
        self.assertEqual(errors, 0); self.assertNotIn('result', entry)
        self.assertTrue(gatelog.passes(self.db.gated(), entry))

    def test_no_pass_writes_unknown_and_removes_playback_settings(self):
        self.populate()
        _, entry = self.export()
        self.assertEqual(entry['result'], 'unknown')
        self.assertNotIn('machine', entry); self.assertNotIn('events', entry)

    def test_alternative_run_that_passes_is_the_written_entry(self):
        self.populate(other=True)
        _, entry = self.export({'ntsc_1541'})
        self.assertEqual(self.played, ['pal_1541', 'ntsc_1541'])
        self.assertEqual(entry['machine'], 'ntsc_1541')
        self.assertTrue(gatelog.passes(self.db.gated(), entry))

    def test_current_cached_pass_is_used(self):
        self.populate(); self.export({'pal_1541'}); self.played.clear()
        self.export(); self.assertEqual(self.played, [])

    def test_missing_inputs_do_not_replace_existing_script_entry(self):
        self.populate(); self.export({'pal_1541'})
        before = (self.root / 'a.toml').read_bytes()
        with mock.patch.object(gate.player, 'VERSION', 'changed'):
            errors, _ = self.export(missing=True)
        self.assertEqual(errors, 1)
        self.assertEqual((self.root / 'a.toml').read_bytes(), before)

    def test_broken_sweep_entry_needs_no_playback(self):
        self.populate('crash')
        _, entry = self.export()
        self.assertEqual(entry['result'], 'broken'); self.assertEqual(self.played, [])

    def test_edited_entries_are_preserved_without_running_gate(self):
        self.populate()
        (self.root / 'a.toml').write_text('[demozoo.7]\ntitle="A Demo"\nsource="verified"\nnote="watched"\n')
        _, entry = self.export()
        self.assertEqual((entry['source'], entry['note']), ('verified', 'watched'))
        self.assertEqual(self.played, [])

    def test_empty_ids_export_nothing(self):
        self.populate(); _, entry = self.export(ids=[])
        self.assertIsNone(entry); self.assertEqual(self.played, [])

    def test_crashes_later_script_is_gated_too(self):
        self.populate('works-then-crash')
        _, entry = self.export()
        self.assertEqual(self.played, ['pal_1541'])
        self.assertEqual(entry['result'], 'unknown')
