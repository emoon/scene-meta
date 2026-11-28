import dataclasses
import pathlib
import tempfile
import unittest
from unittest import mock

from scenemeta.c64 import config, entryrunner, gate, machines, media, player, runner, swapwait
from scenemeta.core.errors import BadEntry, CannotPlay
from scenemeta.core.gate import Play, Run, SwapTaken
from scenemeta.machines import load

DATA = pathlib.Path(__file__).resolve().parents[3] / 'data/c64'
DEFAULT, PRESETS, _ = load(DATA / 'machines.toml')


class HardwareTest(unittest.TestCase):
    def machine(self, **entry):
        return machines.resolve(entry, DEFAULT, PRESETS)

    def test_every_checked_in_preset_resolves(self):
        for name in PRESETS:
            m = self.machine(machine=name)
            self.assertEqual(m.name, name)

    def test_sid_preset_and_override(self):
        self.assertIn('257', self.machine(machine='pal_1541_8580').flags)
        self.assertIn('257', self.machine(sid='8580').flags)
        self.assertIn('256', self.machine().flags)

    def test_video_override_controls_clock(self):
        self.assertEqual(self.machine(video='ntsc').hz, machines.NTSC_HZ)

    def test_reu_size_is_literal(self):
        self.assertEqual(self.machine(reu='512K').flags[-3:], ('-reu', '-reusize', '512'))
        self.assertEqual(self.machine(machine='pal_1541_reu').flags[-1], '16384')

    def test_unsupported_hardware_fails_before_boot(self):
        for entry in ({'machine': 'absent'}, {'video': 'xyz'}, {'sid': '42'},
                      {'drive': '1581'}, {'drives': 2}, {'reu': '3M'}):
            with self.subTest(entry=entry), self.assertRaises(BadEntry):
                self.machine(**entry)

    def test_missing_rom_is_a_missing_input(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(CannotPlay, 'ROM'):
            machines.require_roms(pathlib.Path(d))


class ActionsTest(unittest.TestCase):
    ENTRY = {'disks': ['a.d64', 'b.d64'], 'events': [
        {'at': 10, 'until': 20, 'disk': 2}, {'at': 12, 'key': 'return'}]}

    def test_eager_and_patient_times(self):
        self.assertEqual([x['at'] for x in player.actions(self.ENTRY)], [10, 12])
        self.assertEqual([x['at'] for x in player.actions(self.ENTRY, True)], [20, 22])

    def test_infinite_window_has_finite_patience(self):
        entry = {'events': [{'at': 2, 'until': float('inf'), 'key': 'space'}]}
        self.assertEqual(player.actions(entry, True)[0]['at'], 2 + player.PATIENCE)

    def test_disk_before_same_time_key(self):
        entry = {'disks': ['a', 'b'], 'events': [{'at': 2, 'key': 'space'},
                                                 {'at': 2, 'disk': 2}]}
        self.assertIn('disk', player.actions(entry)[0])

    def test_lowercase_function_and_cursor_keys(self):
        for key in ('return', 'left', 'f1', 'f8', 'p1fire', 'p2fire', '1', 'y'):
            self.assertEqual(player.actions({'events': [{'at': 1, 'key': key}]})[0]['key'], key)

    def test_swapping_back_to_boot_disk_is_allowed(self):
        entry = {'disks': ['a', 'b'], 'events': [{'at': 2, 'disk': 1}]}
        self.assertEqual(player.actions(entry)[0]['disk'], 1)

    def test_illegal_events_do_not_start_an_emulator(self):
        for event in ({'at': 1, 'key': 'lmb'}, {'at': 1, 'disk': 3},
                      {'at': 1, 'disk': 2, 'drive': 2}, {'at': 1},
                      {'at': 1, 'key': 'space', 'pos': [1, 2]},
                      {'at': 1, 'key': 'space', 'disk': 2}):
            with self.subTest(event=event), self.assertRaises(BadEntry):
                player.actions({'disks': ['a', 'b'], 'events': [event]})

    def test_budget_follows_last_event(self):
        self.assertEqual(player.seconds_of({}), player.PLAIN_SECONDS)
        self.assertEqual(player.seconds_of(self.ENTRY), 12 + player.TAIL_SECONDS)
        self.assertEqual(player.seconds_of(self.ENTRY, True), 22 + player.TAIL_SECONDS)

    def test_actions_leave_entry_untouched(self):
        before = repr(self.ENTRY)
        player.actions(self.ENTRY, True)
        self.assertEqual(repr(self.ENTRY), before)


class MediaSelectionTest(unittest.TestCase):
    def select(self, entry, variants):
        with mock.patch.object(media, 'production'), \
             mock.patch.object(media, 'playables', return_value=(variants, [])), \
             mock.patch.object(player.bootfile, 'listing', return_value=['demo']):
            return player._variant_of(7, {'title': 'demo', **entry})

    def test_literal_disk_order_and_later_boot_disk(self):
        v = self.select({'disks': ['b.d64', 'a.d64'], 'boot_disk': 2, 'boot_file': 'demo'},
                        [media.Variant('floppy', ['/nas/a.d64', '/nas/b.d64'])])
        self.assertEqual(v.disks, ['/nas/b.d64', '/nas/a.d64'])
        self.assertEqual((v.boot_disk, v.boot_file), (1, 'demo'))

    def test_single_disk_named_from_larger_set(self):
        v = self.select({'disks': ['b.d64']}, [media.Variant('floppy', ['a.d64', 'b.d64'])])
        self.assertEqual(v.disks, ['b.d64'])

    def test_prg_and_cartridge_selected_by_run(self):
        vs = [media.Variant('prg', ['a.prg']), media.Variant('crt', ['b.crt'])]
        for name in ('a.prg', 'b.crt'):
            self.assertEqual(self.select({'run': name}, vs).disks, [name])

    def test_ambiguity_is_not_a_guess(self):
        with self.assertRaises(BadEntry):
            self.select({}, [media.Variant('prg', ['a.prg']), media.Variant('prg', ['b.prg'])])

    def test_missing_named_media_is_not_replaced(self):
        with self.assertRaises(BadEntry):
            self.select({'disks': ['absent.d64']}, [media.Variant('floppy', ['a.d64'])])

    def test_missing_boot_file_and_disk_fail(self):
        for entry in ({'boot_file': 'absent'}, {'boot_disk': 2}, {'boot_disk': 0}):
            with self.subTest(entry=entry), self.assertRaises(BadEntry):
                self.select(entry, [media.Variant('floppy', ['a.d64'])])

    def test_cartridge_cannot_accept_disk_swaps(self):
        with self.assertRaises(BadEntry):
            self.select({'disks': ['a.crt'], 'events': [{'at': 3, 'disk': 1}]},
                        [media.Variant('crt', ['a.crt'])])

    def test_missing_download_is_cannot_play(self):
        with self.assertRaises(CannotPlay):
            self.select({}, [])

    def test_ready_checks_inputs_before_starting(self):
        with mock.patch.object(machines, 'require_roms', side_effect=CannotPlay('ROM')), \
             mock.patch.object(player, '_variant_of') as variant, \
             self.assertRaisesRegex(CannotPlay, 'ROM'):
            player.ready(7, {'title': 'x'}, DEFAULT, PRESETS)
        variant.assert_not_called()

    def test_ready_uses_supplied_presets(self):
        with mock.patch.object(machines, 'require_roms'), \
             mock.patch.object(player.shutil, 'which', return_value='/bin/x'), \
             mock.patch.object(player, '_variant_of', return_value=media.Variant('prg', ['a.prg'])):
            r = player.ready(7, {'machine': 'custom'}, 'custom',
                             {'custom': {'video': 'ntsc', 'sid': '8580', 'drive': '1541'}})
        self.assertEqual(r.machine.hz, machines.NTSC_HZ)


class RecordTest(unittest.TestCase):
    def log(self, drives=(0, 0, 1, 2), crash=None):
        return runner.RunLog([swapwait.Sample(i * 10_000_000, 0, d, str(i))
                              for i, d in enumerate(drives)], set(), [], crash=crash)

    def test_core_record_and_disk_read_evidence(self):
        got = entryrunner.record(self.log(), [(2, 10_000_000)], 1_000_000)
        self.assertIsInstance(got, Play)
        self.assertTrue(got.ran)
        self.assertEqual(got.swaps, (SwapTaken(2, True),))

    def test_sensor_led_motor_and_sync_are_not_reads(self):
        got = entryrunner.record(self.log((0, 0, 0x10, 0x9c)), [(2, 10_000_000)], 1_000_000)
        self.assertEqual(got.swaps, (SwapTaken(2, False),))

    def test_later_swap_cannot_supply_earlier_read_evidence(self):
        got = entryrunner.record(self.log((0, 0, 0, 1)),
                                  [(2, 0), (1, 20_000_000)], 1_000_000)
        self.assertEqual(got.swaps, (SwapTaken(2, False), SwapTaken(1, True)))

    def test_basic_cursor_is_not_alive(self):
        log = self.log(); log.basic = set(range(4))
        self.assertFalse(entryrunner.record(log, [], 1_000_000).ran)

    def test_crash_after_alive_is_kept(self):
        self.assertEqual(entryrunner.record(self.log(crash='jam'), [], 1_000_000).crash, 'jam')

    def test_no_observations_is_an_error(self):
        with self.assertRaises(CannotPlay):
            entryrunner.record(runner.RunLog([], set(), []), [], 1)


class GatePlayTest(unittest.TestCase):
    def test_removed_key_run_has_the_original_budget_and_seed(self):
        entry = {'events': [{'at': 50, 'key': 'space'}]}
        ready = player.Ready(entry, machines.LADDER[0], media.Variant('prg', ['x.prg']))
        with mock.patch.object(player.Ready, 'play', return_value=Play(True)) as play:
            self.assertEqual(gate._play(ready, Run(3, without=0)), Play(True))
        play.assert_called_once_with(seed=3, seconds=50 + player.TAIL_SECONDS, patient=False)

    def test_patient_flag_and_its_budget(self):
        entry = {'events': [{'at': 50, 'until': 90, 'key': 'space'}]}
        ready = player.Ready(entry, machines.LADDER[0], media.Variant('prg', ['x.prg']))
        with mock.patch.object(player.Ready, 'play', return_value=Play(True)) as play:
            gate._play(ready, Run(2, patient=True))
        play.assert_called_once_with(seed=2, seconds=90 + player.TAIL_SECONDS, patient=True)


class InvalidTimesTest(unittest.TestCase):
    def test_invalid_times_are_bad_entries(self):
        for at, until in ((-1, 0), (float('inf'), float('inf')),
                          (float('nan'), 3), (2, 1), (True, 2), ('2', 3)):
            with self.subTest(at=at, until=until), self.assertRaises(BadEntry):
                player.actions({'events': [{'at': at, 'until': until, 'key': 'space'}]})

    def test_disk_indices_must_be_integers(self):
        for disk in (True, 1.5, '2'):
            with self.subTest(disk=disk), self.assertRaises(BadEntry):
                player.actions({'disks': ['a', 'b'], 'events': [{'at': 1, 'disk': disk}]})
