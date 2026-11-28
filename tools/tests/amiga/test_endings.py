"""Projection, provenance, and read-only command behavior for Issue #18."""
import json
import pathlib
import sqlite3
import tempfile
import tomllib
import unittest
from unittest import mock

from scenemeta import document, merge, validate
from scenemeta.amiga import __main__ as cli, endings
from scenemeta.core import gatelog


def verdict(**overrides):
    return dict(ending="exits", end=120, trace=900, after=780, **overrides)


class EvidenceTest(unittest.TestCase):
    def test_exportable_verdicts(self):
        for ending, expected in (("exits", "exit"), ("stops", "still"),
                                 ("loops", "loop"), ("end-loop", "loop")):
            with self.subTest(ending=ending):
                v = verdict()
                v.update(ending=ending, song_period=30)
                self.assertEqual(endings.fields(v), {"end": 120, "ending": expected})

    def test_uncertain_or_failed_verdicts_stay_in_log(self):
        for ending in ("open", "held", "restarts", "crashed", "not-started", "other"):
            v = verdict()
            v["ending"] = ending
            self.assertEqual(endings.fields(v), {})

    def test_each_warning_blocks_export(self):
        for flag in endings._FLAGS:
            self.assertEqual(endings.fields(verdict(**{flag: True})), {})

    def test_unobserved_or_short_end_is_withheld(self):
        for field, value in (("end", 9), ("end", 880), ("after", 29), ("trace", 120)):
            v = verdict()
            v[field] = value
            self.assertEqual(endings.fields(v), {})

    def test_missing_or_nonfinite_times_are_withheld(self):
        for field in ("end", "trace", "after"):
            for value in (None, True, -1, float("nan"), float("inf"), "120"):
                v = verdict()
                v[field] = value
                self.assertEqual(endings.fields(v), {})

    def test_text_data_and_disk_contradictions_are_withheld(self):
        for change in ({"text_end": 121}, {"last_data": 121}, {"swaps": [121]},
                       {"swaps": [float("nan")]}, {"swaps": "bad"}):
            self.assertEqual(endings.fields(verdict(**change)), {})
        self.assertTrue(endings.fields(verdict(text_end=120, last_data=119, swaps=[80])))

    def test_loop_completion_anchors_must_fit_since_power_on(self):
        for key in ("song_second_pass", "video_shown"):
            v = {**verdict(), "ending": "loops", "song_period": 120, key: 135}
            self.assertFalse(endings.fields(v))
            v["end"] = 135
            self.assertTrue(endings.fields(v))

    def test_loop_needs_observed_period(self):
        v = verdict()
        v["ending"] = "loops"
        self.assertFalse(endings.fields(v))
        for key in ("song_period", "video_period", "landmark_period"):
            self.assertTrue(endings.fields({**v, key: 20}))


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.entry = {"title": "Demo", "source": "script", "run": "Demo.exe"}
        self.held = {1: (gatelog.name(self.entry), verdict())}

    def proposed(self, entry=None, held=None, ids=None):
        return endings.proposals({1: entry or self.entry}, self.held if held is None else held,
                                 ids=ids, log=lambda text: None)

    def test_only_timing_is_added(self):
        self.assertEqual(self.proposed(), [("demozoo", 1, {
            **self.entry, "end": 120, "ending": "exit"})])

    def test_stale_missing_failed_and_unselected_are_kept(self):
        self.assertFalse(self.proposed(held={}))
        self.assertFalse(self.proposed(held={1: ("stale", verdict())}))
        self.assertFalse(self.proposed(entry={**self.entry, "result": "unknown"}))
        self.assertFalse(self.proposed(ids=[]))
        self.assertFalse(self.proposed(ids=[2]))

    def test_hand_entries_are_reported_and_kept(self):
        for source in ("ai", "verified"):
            log = []
            self.assertFalse(endings.proposals({1: {**self.entry, "source": source}},
                                              self.held, log=log.append))
            self.assertIn("entry kept; detector proposes", log[0])

    def test_existing_timing_is_kept(self):
        for timing in ({"end": 50, "ending": "exit"}, {"ending": "interactive"}):
            self.assertFalse(self.proposed(entry={**self.entry, **timing}))

    def test_existing_start_is_respected_and_never_inferred(self):
        self.assertNotIn("start", self.proposed()[0][2])
        self.assertEqual(self.proposed(entry={**self.entry, "start": 20})[0][2]["start"], 20)
        self.assertFalse(self.proposed(entry={**self.entry, "start": 120}))

    def test_annotations_do_not_change_playback_digest(self):
        annotated = {**self.entry, "start": 10, "end": 120, "ending": "exit"}
        self.assertEqual(gatelog.name(self.entry), gatelog.name(annotated))
        base = {**self.entry, "variant": [{"file": "demo.lha", "sha256": "ab" * 32}]}
        variant = {**base, "variant": [{**base["variant"][0], "end": 80, "ending": "still"}]}
        self.assertEqual(gatelog.name(base), gatelog.name(variant))
        self.assertNotEqual(gatelog.name(base), gatelog.name({**base, "run": "Other.exe"}))

    def test_sweep_keeps_timing_only_for_the_same_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            old = {**self.entry, "end": 120, "ending": "exit"}
            (data / "d.toml").write_text(document.render("demozoo", 1, old) + "\n")
            merge.merge(data, [("demozoo", 1, self.entry)])
            self.assertEqual(tomllib.loads((data / "d.toml").read_text())["demozoo"]["1"], old)
            merge.merge(data, [("demozoo", 1, {**self.entry, "run": "Other.exe"})])
            self.assertNotIn("end", tomllib.loads((data / "d.toml").read_text())["demozoo"]["1"])


class CommandTest(unittest.TestCase):
    def test_cli_bypasses_writable_store(self):
        with mock.patch.object(cli.endings, "run", return_value=0) as run, \
                mock.patch.object(cli.cli, "open_store", side_effect=AssertionError("writable")):
            self.assertEqual(cli.main(["export-endings", "--ids", "1", "--write"]), 0)
        run.assert_called_once_with(ids=[1], write=True)

    def test_cli_defaults_to_review(self):
        with mock.patch.object(cli.endings, "run", return_value=0) as run:
            self.assertEqual(cli.main(["export-endings"]), 0)
        run.assert_called_once_with(ids=None, write=False)

    def test_read_only_database_and_idempotent_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            data = root / "data"
            data.mkdir()
            entry = {"title": "Demo", "source": "script"}
            target = data / "d.toml"
            target.write_text(document.render("demozoo", 1, entry) + "\n")
            db_path = root / "scene #1?.db"
            db = sqlite3.connect(db_path)
            db.execute("create table ending(prod_id, entry, detail)")
            db.execute("insert into ending values(?,?,?)", (1, gatelog.name(entry), json.dumps(verdict())))
            db.commit()
            db.close()
            before_db, before_data = db_path.read_bytes(), target.read_bytes()
            args = dict(data=data, db_path=db_path, log=lambda text: None)
            endings.run(**args)
            self.assertEqual(target.read_bytes(), before_data)
            endings.run(**args, write=True)
            changed = target.read_bytes()
            parsed = tomllib.loads(changed.decode())["demozoo"]["1"]
            self.assertEqual(parsed["end"], 120)
            self.assertEqual(parsed["ending"], "exit")
            endings.run(**args, write=True)
            self.assertEqual(target.read_bytes(), changed)
            self.assertEqual(db_path.read_bytes(), before_db)
            with mock.patch.object(endings.sqlite3, "connect", wraps=sqlite3.connect) as connect:
                endings.read(db_path)
            self.assertTrue(connect.call_args.args[0].endswith("?mode=ro"))
            self.assertEqual(connect.call_args.kwargs, {"uri": True, "timeout": 30})

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "missing.db"
            with self.assertRaises(sqlite3.OperationalError):
                endings.read(path)
            self.assertFalse(path.exists())


class TimingValidationTest(unittest.TestCase):
    def problems(self, timing, variant=None):
        entry = dict(title="Demo", source="script", **timing)
        if variant is not None:
            entry["variant"] = [dict(file="demo.lha", sha256="ab" * 32, **variant)]
        return list(validate._production("demozoo", entry, {}))

    def test_known_endings_and_interactive(self):
        for ending in ("exit", "loop", "still"):
            self.assertEqual(self.problems({"start": 5, "end": 120, "ending": ending}), [])
        self.assertEqual(self.problems({"ending": "interactive"}), [])
        self.assertEqual(self.problems({"start": 5}), [])

    def test_timing_must_be_finite_and_nonnegative(self):
        for key in ("start", "end"):
            for value in (-1, True, "10", float("inf"), float("nan")):
                self.assertTrue(self.problems({key: value, "ending": "exit"}))

    def test_end_and_ending_are_paired(self):
        self.assertIn("end and ending must be given together", self.problems({"end": 10}))
        self.assertIn("end and ending must be given together", self.problems({"ending": "still"}))
        self.assertTrue(self.problems({"end": 10, "ending": "exits"}))

    def test_interactive_has_no_end(self):
        self.assertIn("interactive ending must not have end",
                      self.problems({"end": 10, "ending": "interactive"}))

    def test_end_is_after_start_or_power_on(self):
        for timing in ({"end": 0}, {"end": 10, "start": 10}, {"end": 10, "start": 11}):
            self.assertIn("end must be after start (or power-on)",
                          self.problems({**timing, "ending": "still"}))

    def test_variant_uses_effective_inherited_timing(self):
        timing = {"start": 5, "end": 120, "ending": "exit"}
        self.assertEqual(self.problems(timing, {"end": 100}), [])
        self.assertTrue(self.problems(timing, {"start": 125}))
        self.assertTrue(self.problems(timing, {"ending": "interactive"}))
        self.assertEqual(self.problems({}, {"end": 100, "ending": "loop"}), [])
