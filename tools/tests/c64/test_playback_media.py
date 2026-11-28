import pathlib
import tempfile
import unittest
import zipfile
from unittest import mock

from scenemeta.c64 import media
from scenemeta.core.catalog import Production
from scenemeta.core.errors import CannotPlay


class PlaybackMediaTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = pathlib.Path(t.name)
        for attr, value in (('SCENEORG_DIR', self.root), ('WORK', self.root / 'work')):
            patch = mock.patch.object(media.config, attr, value); patch.start(); self.addCleanup(patch.stop)

    def prod(self, *files):
        return Production(7, 'x', '', ('c64',), ('Demo',), '', [('SceneOrgFile', f) for f in files])

    def test_bare_prg_and_crt_are_playable_but_not_sweep_disks(self):
        for name in ('demo.prg', 'demo.crt'):
            (self.root / name).write_bytes(b'data')
            prod = self.prod(name)
            self.assertEqual(media.variants(prod)[0], [])
            self.assertEqual(media.playables(prod)[0][0].kind, name[-3:])

    def test_program_zip_preserves_nested_names_and_ignores_unsafe_paths(self):
        with zipfile.ZipFile(self.root / 'release.zip', 'w') as z:
            for name in ('nested/demo.prg', '../bad.crt', '/bad.prg'):
                z.writestr(name, b'program')
        found, problems = media.playables(self.prod('release.zip'))
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].disks[0].endswith('nested/demo.prg'))
        self.assertFalse((self.root / 'bad.crt').exists())

    def digest(self, *names):
        with mock.patch.object(media, 'production', return_value=self.prod(*names)):
            return media.download_sha256(7)

    def test_digest_changes_when_source_bytes_change(self):
        f = self.root / 'a.prg'; f.write_bytes(b'old')
        old = self.digest('a.prg'); self.assertEqual(old, self.digest('a.prg'))
        f.write_bytes(b'new'); self.assertNotEqual(old, self.digest('a.prg'))

    def test_digest_is_of_source_zip_not_extracted_media(self):
        with zipfile.ZipFile(self.root / 'a.zip', 'w') as z: z.writestr('a.prg', b'old')
        old = self.digest('a.zip'); media.playables(self.prod('a.zip'))
        for p in (self.root / 'work').rglob('a.prg'): p.write_bytes(b'changed')
        self.assertEqual(old, self.digest('a.zip'))

    def test_no_download_has_no_digest(self):
        with self.assertRaises(CannotPlay): self.digest('absent.prg')
