import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.c64 import entryrunner, machines, media, player, runner, swapwait, vice
from scenemeta.core.errors import CannotPlay
from scenemeta.core.gate import Play, SwapTaken


class FakeVice:
    def __init__(self): self.cycles = 0; self.commands = []; self.presses = []
    def stop(self): return self.cycles, 0
    def run_until(self, cycles, step=0.005):
        self.cycles = cycles; return self.stop()
    def cmd(self, text): self.commands.append((self.cycles, text))
    def press(self, key): self.presses.append((self.cycles, key)); return self.stop()


class DriveTest(unittest.TestCase):
    def drive(self, actions, seconds=20):
        v = FakeVice(); log = runner.RunLog([], set(), [])
        inserts = []
        with mock.patch.object(runner, 'observe'):
            entryrunner._drive(v, ['a.d64', 'b.d64'], actions, seconds,
                                1_000_000, pathlib.Path('/tmp'), log, inserts)
        return v, inserts

    def test_disk_gap_precedes_stated_insert_and_key_keeps_its_time(self):
        v, inserts = self.drive([{'at': 10, 'disk': 2}, {'at': 12, 'key': 'return'}])
        self.assertEqual(v.commands, [(7_000_000, 'detach 8'), (10_000_000, 'attach "b.d64" 8')])
        self.assertEqual(v.presses, [(12_000_000, 'Return')])
        self.assertEqual(inserts, [(2, 10_000_000)])

    def test_swap_back_and_same_time_key_are_literal(self):
        v, inserts = self.drive([{'at': 5, 'disk': 2}, {'at': 10, 'disk': 1},
                                 {'at': 10, 'key': 'f1'}])
        self.assertEqual(inserts, [(2, 5_000_000), (1, 10_000_000)])
        self.assertEqual(v.presses, [(10_000_000, 'F1')])

    def test_no_events_causes_no_automatic_answers_or_swaps(self):
        v, inserts = self.drive([])
        self.assertEqual((v.commands, v.presses, inserts), ([], [], []))

    def test_read_only_media_copies_and_seed_reach_vice(self):
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / 'demo.prg'; src.write_bytes(b'unchanged')
            created = []
            class Instance:
                def __init__(self, machine, disks, tmp, port, file, seed=None):
                    self.disks = disks; created.append((machine, disks, seed))
                def __enter__(self): return self
                def __exit__(self, *args): pass
            def drive(v, disks, actions, seconds, hz, tmp, log, inserts):
                self.assertNotEqual(pathlib.Path(disks[0]), src)
                pathlib.Path(disks[0]).write_bytes(b'writeback')
                log.samples = [swapwait.Sample(i * 10_000_000, 0, 0, str(i)) for i in range(4)]
            with mock.patch.object(vice, 'Vice', Instance), mock.patch.object(entryrunner, '_drive', drive):
                got = entryrunner.run(machines.LADDER[0], media.Variant('prg', [str(src)]), [], 180, 3)
            self.assertTrue(got.ran); self.assertEqual(src.read_bytes(), b'unchanged')
            self.assertEqual(created[0][2], 3)
            self.assertFalse(pathlib.Path(created[0][1][0]).exists())

    def test_crash_before_later_swap_still_reports_that_swap_unloaded(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name in ('a.d64', 'b.d64'):
                p = pathlib.Path(d) / name; p.write_bytes(b'data'); paths.append(str(p))
            def crash(v, disks, actions, seconds, hz, tmp, log, inserts):
                log.samples = [swapwait.Sample(1, 0, 0, 'shot')]
                raise vice.ViceError('closed')
            with mock.patch.object(vice, 'Vice'), mock.patch.object(entryrunner, '_drive', crash):
                got = entryrunner.run(machines.LADDER[0], media.Variant('floppy', paths),
                                      [{'at': 10, 'disk': 2}], 180, 1)
            self.assertEqual((got.crash, got.swaps), ('emulator-exit', (SwapTaken(2, False),)))

    def test_start_failure_is_missing_input_without_a_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'demo.prg'; p.write_bytes(b'data')
            with mock.patch.object(vice, 'Vice', side_effect=vice.StartError('no display')), \
                 self.assertRaises(CannotPlay):
                entryrunner.run(machines.LADDER[0], media.Variant('prg', [str(p)]), [], 180, 1)


class ViceLaunchTest(unittest.TestCase):
    def launch(self, name, seed=2):
        with tempfile.TemporaryDirectory() as d:
            v = vice.Vice(machines.LADDER[0], [name], pathlib.Path(d), 5555, seed=seed)
            with mock.patch.object(vice.subprocess, 'Popen') as popen, \
                 mock.patch.object(vice.Vice, '_connect'), mock.patch.object(vice.Vice, 'stop'):
                v.__enter__()
                argv = popen.call_args.args[0]
                popen.call_args.kwargs['stdout'].close()
        return argv

    def test_crt_attaches_as_cartridge_and_prg_autostarts(self):
        self.assertIn('-cartcrt', self.launch('demo.crt'))
        self.assertIn('-autostart', self.launch('demo.prg'))

    def test_seed_is_set_before_power_on(self):
        argv = self.launch('demo.d64', 3)
        self.assertEqual(argv[-2:], ['-seed', '3'])

    def test_failed_enter_cleans_its_process(self):
        with tempfile.TemporaryDirectory() as d:
            v = vice.Vice(machines.LADDER[0], ['a.d64'], pathlib.Path(d), 5555)
            with mock.patch.object(vice.subprocess, 'Popen') as popen, \
                 mock.patch.object(vice.Vice, '_connect', side_effect=vice.StartError('no monitor')), \
                 mock.patch.object(vice.Vice, '__exit__') as cleanup, \
                 self.assertRaises(vice.StartError):
                v.__enter__()
            cleanup.assert_called_once()
            popen.call_args.kwargs['stdout'].close()
