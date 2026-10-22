"""Possession events from the v3 engine, with the legacy derivation as fallback.

Fixtures in tests/fixtures/v3 are real pipeline output: possession_events_v3.jsonl
is the whole clip_027 staged file (8 rows); the legacy file is the clip_027 re-run
trimmed to its confirmed rows plus 3 unconfirmed ones for context.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.application.stats.aggregation import build_possession_events, build_v3_events
from src.application.stats.use_cases import GetEventsUseCase
from tests.application.stats.test_stats_v2_contract import PerFileReader, shot, v2_reader
from tests.application.stats.test_stats_use_cases import FakeAccess, FakeJobs, JOB_ID, TEAM_ID, USER_ID, build_job

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "v3"


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


class TestBuildV3Events(unittest.TestCase):
    def test_real_clip_has_three_passes_and_one_possession_change(self) -> None:
        events = build_v3_events(load("possession_events_v3.jsonl"), fps=30.0)
        self.assertEqual(
            [(e["type"], round(e["timestamp_seconds"], 2)) for e in events],
            [("pass", 4.53), ("pass", 5.27), ("pass", 13.8), ("possession_change", 17.63)],
        )
        change = events[-1]
        self.assertEqual((change["from_team_id"], change["to_team_id"]), (0, 1))
        self.assertEqual(
            (change["from_stable_player_id"], change["to_stable_player_id"]),
            ("player-002", "player-008"),
        )
        first = events[0]
        self.assertEqual(first["event_id"], "ball-transition-119")
        self.assertEqual(first["start_timestamp_seconds"], 3.966666666666667)
        self.assertTrue(first["experimental"])
        self.assertEqual(first["source"], "v3")
        self.assertEqual(first["reason_codes"], ["release_trajectory_reception"])
        self.assertIsNone(first["confidence"])

    def test_classified_types_map_and_other_unknowns_are_dropped(self) -> None:
        def row(tid, kind, src=0, dst=0):
            return {"transition_id": tid, "event_type": kind, "timestamp_end": 1.0,
                    "source_team_id": src, "destination_team_id": dst}

        rows = [
            row("a", "STEAL", 0, 1), row("b", "TURNOVER"), row("c", "LOSS_OF_CONTROL"),
            row("d", "UNKNOWN", 0, 0), row("e", "UNKNOWN", None, 1), row("f", "possession_transfer"),
        ]
        events = build_v3_events(rows, fps=None)
        self.assertEqual([e["type"] for e in events], ["steal", "turnover", "loss_of_control"])

    def test_garbage_rows_never_raise(self) -> None:
        rows = [None, 5, "x", [], {}, {"transition_id": 3, "event_type": "PASS"},
                {"transition_id": "a", "event_type": "PASS"},
                {"transition_id": "b", "event_type": "PASS", "timestamp_end": "soon"},
                {"transition_id": "c", "event_type": "PASS", "timestamp_end": 2.0, "reason_codes": "x"}]
        events = build_v3_events(rows, fps=30.0)
        self.assertEqual([e["event_id"] for e in events], ["c"])
        self.assertEqual(events[0]["reason_codes"], [])


class TestLegacyGap(unittest.TestCase):
    def test_no_pass_across_a_gap_longer_than_one_and_a_half_seconds(self) -> None:
        events = build_possession_events(load("legacy_possession_events_trimmed.jsonl"), fps=30.0)
        self.assertEqual(
            [(e["type"], e["timestamp_seconds"], e["uncertain"]) for e in events],
            [("possession_transfer", 7.467, True), ("possession_transfer", 15.9, True)],
        )

    def test_short_gap_same_team_is_still_a_certain_pass(self) -> None:
        def row(frame, holder):
            return {"frame_index": frame, "status": "confirmed", "stable_player_id": holder, "team_id": 1}

        events = build_possession_events([row(0, "a"), row(30, "b"), row(90, "a")], fps=30.0)
        self.assertEqual([(e["type"], e["uncertain"]) for e in events],
                         [("pass", False), ("possession_transfer", True)])


class TestEventsUseCase(unittest.TestCase):
    def run_use_case(self, reader):
        return GetEventsUseCase(
            jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess(),
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)

    def test_prefers_v3_when_both_files_exist(self) -> None:
        reader = v2_reader([shot(release_timestamp_seconds=1.0)])
        reader.jsonl["possession_events_v3.jsonl"] = load("possession_events_v3.jsonl")
        reader.jsonl["possession_events.jsonl"] = load("legacy_possession_events_trimmed.jsonl")
        result = self.run_use_case(reader)
        self.assertEqual(result["coverage"]["possession_source"], "v3")
        self.assertEqual(result["coverage"]["experimental_events"], 4)
        self.assertEqual({e["source"] for e in result["events"] if e["type"] != "shot"}, {"v3"})

    def test_falls_back_to_legacy_tagged(self) -> None:
        reader = v2_reader([])
        reader.jsonl["possession_events.jsonl"] = load("legacy_possession_events_trimmed.jsonl")
        result = self.run_use_case(reader)
        self.assertEqual(result["coverage"]["possession_source"], "legacy")
        self.assertEqual({e["source"] for e in result["events"]}, {"legacy_holder_change"})

    def test_v3_file_with_no_usable_events_falls_back(self) -> None:
        reader = v2_reader([])
        reader.jsonl["possession_events_v3.jsonl"] = [None, {"x": 1}]
        reader.jsonl["possession_events.jsonl"] = load("legacy_possession_events_trimmed.jsonl")
        self.assertEqual(self.run_use_case(reader)["coverage"]["possession_source"], "legacy")

    def test_no_possession_files_reports_none(self) -> None:
        result = self.run_use_case(v2_reader([shot()]))
        self.assertEqual(result["coverage"]["possession_source"], "none")
