"""Statistics from the v2 pipeline artifacts (player summary, paths, new shot fields).

Fixtures are small inline documents shaped like the pipeline's new files. Every
test that matters for old jobs also runs against legacy-only artifacts, because
jobs processed before these files existed must keep answering as before.
"""

from __future__ import annotations

import unittest

from src.application.jobs.errors import JOB_NOT_FINISHED, RESULTS_NOT_AVAILABLE, JobError
from src.application.stats.aggregation import build_game_stats, build_shot_chart
from src.application.stats.use_cases import (
    MAX_EVENTS,
    MAX_POSITION_RECORDS,
    GetCourtPositionsUseCase,
    GetEventsUseCase,
    GetGameStatsUseCase,
    GetShotChartUseCase,
    GetSimilarClipsUseCase,
    GetTeamSidesUseCase,
)
from src.domain.jobs.entities import JobStatus
from src.domain.stats.similarity import (
    FEATURE_VERSION,
    resample_rows,
    rows_from_player_paths,
)
from tests.application.stats.test_stats_use_cases import (
    FakeAccess,
    FakeJobs,
    FakeJobsForSimilar,
    FakeRoster,
    JOB_ID,
    TEAM_ID,
    USER_ID,
    build_job,
)

TWO_POINT_XY = [3.867, 13.267]
THREE_POINT_XY = [9.5, 7.5]


class PerFileReader:
    """Serves each file name its own content, like the real storage does."""

    def __init__(self, documents=None, jsonl=None):
        self.documents = documents or {}
        self.jsonl = jsonl or {}
        self.requested: list[str] = []

    def read_json(self, *, results_key, filename):
        self.requested.append(filename)
        return self.documents.get(filename)

    def read_jsonl(self, *, results_key, filename, max_lines):
        self.requested.append(filename)
        return list(self.jsonl.get(filename, []))[:max_lines]


def shot(**overrides) -> dict:
    base = {
        "event_id": 1,
        "outcome": "made",
        "outcome_confidence": "detected",
        "outcome_source": "ball_in_basket",
        "shot_origin_court_xy_m": TWO_POINT_XY,
        "shooter_track_id": 3000007,
        "shooter_stable_player_id": "player-010",
        "shooter_team_id": 1,
        "start_timestamp_seconds": 4.0,
        "end_timestamp_seconds": 6.5,
        "release_timestamp_seconds": 4.4,
        "resolved_timestamp_seconds": 7.0,
        "shot_type": "jump_shot",
        "shooter_attribution_method": "action_box_vote",
        "shooter_candidates": [{"stable_player_id": "player-010", "team_id": 1, "score": 3.0}],
        "needs_review": False,
    }
    base.update(overrides)
    return base


SUMMARY = {
    "schema_version": 1,
    "fps": 30.0,
    "frame_count": 900,
    "duration_seconds": 30.0,
    "players": [
        {
            "stable_player_id": "player-010", "team_id": 1, "team_agreement": 0.95,
            "track_ids": [7, 3000007], "frames_observed": 600, "seconds_observed": 20.0,
            "first_frame": 0, "last_frame": 899, "distance_m": 55.5, "avg_xy_m": [5.0, 6.0],
            "jersey": {"number": "30", "status": "confirmed", "support_count": 4},
        },
        {
            "stable_player_id": "player-011", "team_id": None, "team_agreement": 0.6,
            "track_ids": [8], "frames_observed": 300, "seconds_observed": 10.0,
            "first_frame": 10, "last_frame": 400, "distance_m": 12.0, "avg_xy_m": None,
            "jersey": {"number": None, "status": "ambiguous", "support_count": 2},
        },
    ],
    "ball": {"detected_frames": 450, "frames": 900},
}
PATHS = [
    {"stable_player_id": "player-010", "team_id": 1, "hz": 5,
     "points": [[0, 5.0, 6.0], [6, 5.5, 6.0], [12, 6.0, 6.5]]},
    {"stable_player_id": "player-011", "team_id": None, "hz": 5,
     "points": [[0, 20.0, 7.0], [6, 400.0, 7.0]]},
]
RESULTS = {"video": {"fps": 30.0, "frame_count": 900, "duration_seconds": 30.0}}
TEAMS_V2 = {"assignments_by_track_id": {"7": 1, "3000007": 1, "8": 0}}


def v2_reader(shots, **extra_docs) -> PerFileReader:
    documents = {
        "projected_shots.json": {"shots": shots},
        "teams.json": TEAMS_V2,
        "player_summary.json": SUMMARY,
        "results.json": RESULTS,
        **extra_docs,
    }
    return PerFileReader(documents, jsonl={"player_paths.jsonl": PATHS})


def stats_for(reader, roster=None) -> dict:
    return GetGameStatsUseCase(
        jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess(),
        roster=roster or FakeRoster(),
    ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)


class TestSummarySource(unittest.TestCase):
    def test_players_come_from_the_summary_with_new_fields(self) -> None:
        result = stats_for(v2_reader([shot()]))
        player = next(p for p in result["players"] if p["stable_player_id"] == "player-010")
        self.assertEqual(player["seconds_observed"], 20.0)
        self.assertEqual(player["distance_m"], 55.5)
        self.assertEqual(player["jersey_number"], "30")
        self.assertEqual(player["jersey_status"], "confirmed")
        self.assertEqual(player["jersey_support_count"], 4)
        self.assertEqual(player["team_agreement"], 0.95)
        self.assertEqual(player["observations"], 600)
        other = next(p for p in result["players"] if p["stable_player_id"] == "player-011")
        self.assertEqual(other["jersey_status"], "ambiguous")
        # No dominant team in the summary: the track assignments decide.
        self.assertEqual(other["team_id"], 0)
        self.assertEqual(len(result["players"]), 2)

    def test_summary_means_the_per_frame_file_is_never_read(self) -> None:
        reader = v2_reader([shot()])
        result = stats_for(reader)
        self.assertNotIn("projected_tracks.jsonl", reader.requested)
        self.assertEqual(result["coverage"]["positions_source"], "player_summary")
        self.assertFalse(result["coverage"]["positions_truncated"])
        self.assertEqual(result["video"], {"fps": 30.0, "duration_seconds": 30.0})

    def test_ball_visibility_and_measures(self) -> None:
        coverage = stats_for(v2_reader([shot()]))["coverage"]
        self.assertEqual(coverage["ball_visibility_pct"], 50.0)
        self.assertIn("distance", coverage["measures"])
        for absent in ("free_throws", "blocks", "passes", "possessions", "assists", "rebounds"):
            self.assertIn(absent, coverage["not_measured"])

    def test_shooter_is_read_directly_from_the_stable_id(self) -> None:
        # The track id is unknown to every map; only the direct field can name them.
        result = stats_for(v2_reader([shot(shooter_track_id=999999)]))
        self.assertEqual(result["shots"][0]["stable_player_id"], "player-010")
        player = next(p for p in result["players"] if p["stable_player_id"] == "player-010")
        self.assertEqual(player["field_goals_made"], 1)

    def test_shooter_with_only_a_stable_id_is_still_attributed(self) -> None:
        result = stats_for(v2_reader([shot(shooter_track_id=None)]))
        self.assertEqual(result["coverage"]["shots_without_shooter"], 0)
        self.assertEqual(result["shots"][0]["jersey_number"], "30")

    def test_old_track_map_is_the_fallback_when_the_shot_has_no_stable_id(self) -> None:
        old = shot(shooter_stable_player_id=None, shooter_track_id=7)
        result = stats_for(v2_reader([old]))
        self.assertEqual(result["shots"][0]["stable_player_id"], "player-010")

    def test_stable_ids_beyond_the_legacy_row_cap_still_resolve(self) -> None:
        """The cap used to drop the map silently; the summary has no cap."""

        reader = v2_reader([shot(shooter_stable_player_id=None, shooter_track_id=3000007)])
        reader.jsonl["projected_tracks.jsonl"] = [
            {"frame_index": i, "track_id": 1, "stable_player_id": "player-999"}
            for i in range(MAX_POSITION_RECORDS)
        ]
        result = stats_for(reader)
        self.assertEqual(result["shots"][0]["stable_player_id"], "player-010")
        self.assertFalse(result["coverage"]["positions_truncated"])

    def test_number_fragments_still_merge_with_summary_ids(self) -> None:
        summary = {
            **SUMMARY,
            "players": [
                SUMMARY["players"][0],
                {**SUMMARY["players"][0], "stable_player_id": "player-020", "track_ids": [20],
                 "frames_observed": 100, "seconds_observed": 3.0, "distance_m": 4.5},
            ],
        }
        reader = v2_reader([shot(), shot(event_id=2, shooter_stable_player_id="player-020")])
        reader.documents["player_summary.json"] = summary
        result = stats_for(reader)
        self.assertEqual(len(result["players"]), 1)
        merged = result["players"][0]
        self.assertEqual(merged["field_goals_attempted"], 2)
        self.assertEqual(merged["seconds_observed"], 23.0)
        self.assertEqual(merged["distance_m"], 60.0)
        self.assertEqual({row["stable_player_id"] for row in result["shots"]}, {"player-010"})

    def test_on_court_uses_summary_observations(self) -> None:
        result = stats_for(v2_reader([]))
        self.assertTrue(all(p["on_court"] for p in result["players"]))

    def test_unreadable_summary_falls_back_to_legacy(self) -> None:
        class Broken(PerFileReader):
            def read_json(self, *, results_key, filename):
                if filename == "player_summary.json":
                    from src.application.stats.ports import ArtifactReadError
                    raise ArtifactReadError("too big")
                return super().read_json(results_key=results_key, filename=filename)

        reader = Broken(
            {"projected_shots.json": {"shots": [shot(shooter_stable_player_id=None, shooter_track_id=7)]},
             "teams.json": TEAMS_V2},
            jsonl={"projected_tracks.jsonl": [{"frame_index": 0, "track_id": 7, "stable_player_id": "p-legacy"}]},
        )
        result = stats_for(reader)
        self.assertEqual(result["shots"][0]["stable_player_id"], "p-legacy")
        self.assertEqual(result["coverage"]["positions_source"], "projected_tracks")


class TestLegacyOnlyArtifacts(unittest.TestCase):
    ROWS = [
        {"frame_index": 0, "track_id": 7, "stable_player_id": "p-a", "court_xy_m": [5.0, 5.0]},
        {"frame_index": 1, "track_id": 7, "stable_player_id": "p-a", "court_xy_m": [5.0, 5.0]},
    ]

    def reader(self, rows=None, with_results=True):
        documents = {
            "projected_shots.json": {"shots": [{
                "event_id": 1, "outcome": "missed", "shot_origin_court_xy_m": TWO_POINT_XY,
                "shooter_track_id": 7, "shooter_team_id": 1, "start_timestamp_seconds": 4.0,
            }]},
            "teams.json": {"assignments_by_track_id": {"7": 1}},
        }
        if with_results:
            documents["results.json"] = RESULTS
        return PerFileReader(documents, jsonl={"projected_tracks.jsonl": rows or self.ROWS})

    def test_old_job_keeps_its_shape_and_gains_null_new_fields(self) -> None:
        result = stats_for(self.reader())
        player = result["players"][0]
        self.assertEqual(player["stable_player_id"], "p-a")
        self.assertEqual(player["field_goals_attempted"], 1)
        self.assertIsNone(player["distance_m"])
        self.assertEqual(player["jersey_status"], "unknown")
        # seconds come from legacy frames over the fps in results.json
        self.assertAlmostEqual(player["seconds_observed"], 0.07, places=2)
        row = result["shots"][0]
        self.assertIsNone(row["needs_review"])
        self.assertEqual(row["shooter_candidates"], [])
        self.assertIsNone(row["release_timestamp_seconds"])
        coverage = result["coverage"]
        self.assertEqual(coverage["positions_source"], "projected_tracks")
        self.assertFalse(coverage["positions_truncated"])
        self.assertIsNone(coverage["ball_visibility_pct"])
        self.assertEqual(coverage["measures"], ["shooting"])

    def test_missing_results_json_is_tolerated(self) -> None:
        result = stats_for(self.reader(with_results=False))
        self.assertEqual(result["video"], {"fps": None, "duration_seconds": None})
        self.assertIsNone(result["players"][0]["seconds_observed"])

    def test_over_cap_legacy_file_is_flagged_truncated(self) -> None:
        rows = [
            {"frame_index": i, "track_id": 7, "stable_player_id": "p-a"}
            for i in range(MAX_POSITION_RECORDS + 5)
        ]
        coverage = stats_for(self.reader(rows))["coverage"]
        self.assertTrue(coverage["positions_truncated"])
        self.assertEqual(coverage["positions_source"], "projected_tracks")

    def test_court_positions_flags_truncation_on_legacy(self) -> None:
        rows = [
            {"frame_index": i, "track_id": 7, "court_xy_m": [5.0, 5.0]}
            for i in range(MAX_POSITION_RECORDS)
        ]
        result = GetCourtPositionsUseCase(
            jobs=FakeJobs(build_job()), artifacts=self.reader(rows), team_access=FakeAccess()
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertTrue(result["coverage"]["positions_truncated"])
        self.assertTrue(result["coverage"]["truncated"])
        self.assertEqual(result["coverage"]["positions_source"], "projected_tracks")


class TestOutcomeBuckets(unittest.TestCase):
    def stats(self, shots):
        return build_game_stats(
            shots_document={"shots": shots}, teams_document=TEAMS_V2, numbers_document=None,
            summary_players={p["stable_player_id"]: p for p in SUMMARY["players"]},
        ).to_dict()

    def player(self, stats):
        return next(p for p in stats["players"] if p["stable_player_id"] == "player-010")

    def test_unresolved_is_excluded_from_attempts_and_percentage(self) -> None:
        stats = self.stats([
            shot(event_id=1),
            shot(event_id=2, outcome="missed", outcome_confidence="timeout"),
            shot(event_id=3, outcome="unknown", outcome_confidence="unresolved",
                 resolution_reason="ball_in_basket_unconfirmed"),
            shot(event_id=4, outcome="unknown", outcome_confidence="unresolved",
                 resolution_reason="end_of_clip"),
        ])
        player = self.player(stats)
        self.assertEqual(player["field_goals_attempted"], 2)
        self.assertEqual(player["field_goal_pct"], 0.5)
        self.assertEqual(player["unresolved_attempts"], 2)
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual((team["field_goals_attempted"], team["unresolved_attempts"]), (2, 2))
        zone = next(iter(player["by_zone"].values()))
        self.assertEqual((zone["attempted"], zone["unresolved_attempts"]), (2, 2))
        coverage = stats["coverage"]
        self.assertEqual(coverage["unresolved_attempts"], 2)
        self.assertEqual(coverage["shots_by_outcome"], {"made": 1, "missed": 1, "unresolved": 2})

    def test_a_zone_with_only_unresolved_shots_is_reported_without_a_percentage(self) -> None:
        stats = self.stats([shot(outcome="unknown", outcome_confidence="unresolved")])
        zone = next(iter(self.player(stats)["by_zone"].values()))
        self.assertEqual((zone["made"], zone["attempted"], zone["unresolved_attempts"]), (0, 0, 1))
        self.assertIsNone(zone["pct"])
        self.assertIsNone(self.player(stats)["field_goal_pct"])

    def test_inferred_make_counts_as_made_and_is_flagged_on_the_row(self) -> None:
        stats = self.stats([shot(outcome_confidence="inferred", outcome_source="rim_trajectory")])
        self.assertEqual(self.player(stats)["field_goals_made"], 1)
        self.assertEqual(self.player(stats)["points"], 2)
        row = stats["shots"][0]
        self.assertTrue(row["made"])
        self.assertEqual(row["outcome_confidence"], "inferred")
        self.assertEqual(row["outcome_source"], "rim_trajectory")

    def test_team_only_shot_counts_for_the_team_via_shooter_team_id(self) -> None:
        stats = self.stats([shot(shooter_track_id=None, shooter_stable_player_id=None,
                                 shooter_team_id=0, needs_review=True)])
        team = next(t for t in stats["teams"] if t["team_id"] == 0)
        self.assertEqual(team["field_goals_made"], 1)
        self.assertEqual(stats["coverage"]["shots_without_shooter"], 1)
        self.assertEqual(self.player(stats)["field_goals_attempted"], 0)

    def test_by_shot_type_per_player_and_team(self) -> None:
        stats = self.stats([
            shot(event_id=1, shot_type="layup"),
            shot(event_id=2, shot_type="layup", outcome="missed"),
            shot(event_id=3, shot_type="jump_shot"),
            shot(event_id=4, shot_type="jump_shot", outcome="unknown"),
        ])
        expected = {"jump_shot": {"made": 1, "attempted": 1}, "layup": {"made": 1, "attempted": 2}}
        self.assertEqual(self.player(stats)["by_shot_type"], expected)
        team = next(t for t in stats["teams"] if t["team_id"] == 1)
        self.assertEqual(team["by_shot_type"], expected)

    def test_points_still_come_from_location(self) -> None:
        stats = self.stats([shot(shot_origin_court_xy_m=THREE_POINT_XY)])
        self.assertEqual(self.player(stats)["points"], 3)

    def test_needs_review_and_new_fields_pass_through(self) -> None:
        stats = self.stats([shot(needs_review=True), shot(event_id=2)])
        row = stats["shots"][0]
        self.assertTrue(row["needs_review"])
        self.assertEqual(row["release_timestamp_seconds"], 4.4)
        self.assertEqual(row["resolved_timestamp_seconds"], 7.0)
        self.assertEqual(row["shooter_candidates"][0]["stable_player_id"], "player-010")
        self.assertEqual(stats["coverage"]["shots_needing_review"], 1)

    def test_shot_chart_markers_carry_confidence_and_review_flag(self) -> None:
        chart = build_shot_chart(
            shots_document={"shots": [shot(needs_review=True, outcome="unknown")]},
            teams_document=TEAMS_V2, numbers_document=None,
            summary_players={p["stable_player_id"]: p for p in SUMMARY["players"]},
        )
        marker = chart["shots"][0]
        self.assertEqual(marker["result"], "unknown")
        self.assertTrue(marker["needs_review"])
        self.assertEqual(chart["players"][0]["stable_player_id"], "player-010")


class TestCourtPositionsFromPaths(unittest.TestCase):
    def run_use_case(self, reader, **kwargs):
        return GetCourtPositionsUseCase(
            jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess()
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, **kwargs)

    def test_serves_paths_with_summary_movement(self) -> None:
        reader = v2_reader([])
        result = self.run_use_case(reader)
        self.assertNotIn("projected_tracks.jsonl", reader.requested)
        coverage = result["coverage"]
        self.assertEqual(coverage["positions_source"], "player_summary")
        self.assertFalse(coverage["positions_truncated"])
        by_id = {p["stable_player_id"]: p for p in result["players"]}
        first = by_id["player-010"]
        self.assertEqual(len(first["positions"]), 3)
        self.assertEqual(first["movement"]["distance_m"], 55.5)
        self.assertEqual(first["movement"]["average_position"], {"x_m": 5.0, "y_m": 6.0})
        self.assertEqual(first["jersey_number"], "30")
        self.assertEqual(first["team_id"], 1)
        # off-court point is dropped and counted; the average is computed when absent
        second = by_id["player-011"]
        self.assertEqual(len(second["positions"]), 1)
        self.assertEqual(coverage["records_off_court"], 1)
        self.assertEqual(second["movement"]["average_position"], {"x_m": 20.0, "y_m": 7.0})
        self.assertEqual(second["team_id"], 0)

    def test_sampling_thins_positions_but_not_distance(self) -> None:
        result = self.run_use_case(v2_reader([]), sample_every=2)
        first = next(p for p in result["players"] if p["stable_player_id"] == "player-010")
        self.assertEqual(len(first["positions"]), 2)
        self.assertEqual(first["movement"]["distance_m"], 55.5)

    def test_summary_without_paths_falls_back_to_legacy_rows(self) -> None:
        reader = v2_reader([])
        reader.jsonl = {"projected_tracks.jsonl": [
            {"frame_index": 0, "track_id": 7, "court_xy_m": [5.0, 5.0]}
        ]}
        result = self.run_use_case(reader)
        self.assertEqual(result["coverage"]["source_file"], "projected_tracks.jsonl")
        self.assertEqual(result["coverage"]["positions_source"], "projected_tracks")


class TestEvents(unittest.TestCase):
    def run_use_case(self, reader, job=None):
        return GetEventsUseCase(
            jobs=FakeJobs(build_job() if job is None else job), artifacts=reader,
            team_access=FakeAccess(),
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)

    def possession(self):
        def row(frame, status, stable=None, team=None):
            return {"frame_index": frame, "timestamp_seconds": None, "status": status,
                    "stable_player_id": stable, "player_track_id": None, "team_id": team,
                    "confidence": 0.8}
        return [
            row(0, "unknown"), row(30, "confirmed", "player-010", 1),
            row(45, "lost"), row(60, "confirmed", "player-012", 1),
            row(150, "confirmed", "player-011", 0), row(160, "confirmed", "player-011", 0),
        ]

    def test_shot_events_use_release_time_and_follow_the_schema(self) -> None:
        reader = v2_reader([
            shot(event_id=2, start_timestamp_seconds=9.0, release_timestamp_seconds=None),
            shot(event_id=1, outcome="unknown", outcome_confidence="unresolved"),
        ])
        result = self.run_use_case(reader)
        self.assertEqual(result["video"], {"fps": 30.0, "duration_seconds": 30.0})
        first, second = result["events"]
        self.assertEqual((first["event_id"], second["event_id"]), (1, 2))
        self.assertEqual(first["type"], "shot")
        self.assertEqual(first["timestamp_seconds"], 4.4)       # release, not detector start
        self.assertEqual(second["timestamp_seconds"], 9.0)      # no release: detector start
        self.assertEqual(first["outcome"], "unresolved")
        self.assertEqual(second["outcome"], "made")
        self.assertEqual(
            set(first),
            {"type", "event_id", "timestamp_seconds", "end_timestamp_seconds", "outcome",
             "outcome_confidence", "shot_type", "stable_player_id", "team_id", "jersey_number",
             "court_x_m", "court_y_m", "needs_review"},
        )
        self.assertEqual(second["jersey_number"], "30")
        self.assertEqual(second["court_x_m"], 3.87)

    def test_unlocated_shots_stay_in_the_timeline(self) -> None:
        result = self.run_use_case(v2_reader([shot(shot_origin_court_xy_m=None)]))
        event = result["events"][0]
        self.assertIsNone(event["court_x_m"])

    def test_possession_events_are_experimental_and_ordered_with_shots(self) -> None:
        reader = v2_reader([shot(release_timestamp_seconds=1.5)])
        reader.jsonl["possession_events.jsonl"] = self.possession()
        result = self.run_use_case(reader)
        kinds = [(e["type"], e["timestamp_seconds"]) for e in result["events"]]
        self.assertEqual(kinds, [("shot", 1.5), ("pass", 2.0), ("possession_transfer", 5.0)])
        possession = [e for e in result["events"] if e["type"] != "shot"]
        self.assertTrue(all(e["experimental"] for e in possession))
        self.assertEqual(possession[0]["from_stable_player_id"], "player-010")
        self.assertEqual(possession[0]["to_stable_player_id"], "player-012")
        self.assertEqual(result["coverage"]["experimental_events"], 2)

    def test_no_possession_file_means_only_shots(self) -> None:
        result = self.run_use_case(v2_reader([shot()]))
        self.assertEqual([e["type"] for e in result["events"]], ["shot"])
        self.assertEqual(result["coverage"]["experimental_events"], 0)

    def test_events_are_capped_and_shots_keep_priority(self) -> None:
        shots = [shot(event_id=i, release_timestamp_seconds=100.0 + i) for i in range(10)]
        reader = v2_reader(shots)
        many = []
        for i in range(MAX_EVENTS):
            many += [
                {"frame_index": i * 4, "status": "confirmed", "stable_player_id": "a", "team_id": 1},
                {"frame_index": i * 4 + 2, "status": "confirmed", "stable_player_id": "b", "team_id": 1},
            ]
        reader.jsonl["possession_events.jsonl"] = many
        result = self.run_use_case(reader)
        self.assertEqual(len(result["events"]), MAX_EVENTS)
        self.assertEqual(sum(1 for e in result["events"] if e["type"] == "shot"), 10)
        times = [e["timestamp_seconds"] for e in result["events"]]
        self.assertEqual(times, sorted(times))

    def test_old_job_resolves_the_shooter_through_the_track_map(self) -> None:
        old = shot(shooter_stable_player_id=None, shooter_track_id=7)
        reader = PerFileReader(
            {"projected_shots.json": {"shots": [old]}, "teams.json": TEAMS_V2},
            jsonl={"projected_tracks.jsonl": [{"track_id": 7, "stable_player_id": "p-legacy"}]},
        )
        self.assertEqual(self.run_use_case(reader)["events"][0]["stable_player_id"], "p-legacy")

    def test_unfinished_and_empty_jobs_are_rejected(self) -> None:
        with self.assertRaises(JobError) as ctx:
            self.run_use_case(v2_reader([]), job=build_job(status=JobStatus.RUNNING))
        self.assertEqual(ctx.exception.code, JOB_NOT_FINISHED)
        with self.assertRaises(JobError) as ctx:
            self.run_use_case(PerFileReader({}))
        self.assertEqual(ctx.exception.code, RESULTS_NOT_AVAILABLE)


class TestTeamSidesWithSummary(unittest.TestCase):
    def test_sides_use_summary_track_ids(self) -> None:
        reader = PerFileReader({
            "teams.json": TEAMS_V2,
            "numbers.json": {"players": [{"stable_player_id": "player-010", "status": "confirmed",
                                          "number": "30"}]},
            "player_summary.json": SUMMARY,
        })
        result = GetTeamSidesUseCase(
            jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess(),
            roster=FakeRoster(),
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        side1 = next(s for s in result["sides"] if s["team_side"] == 1)
        self.assertEqual(side1["numbers"], ["30"])
        self.assertEqual(side1["track_count"], 1)
        self.assertNotIn("projected_tracks.jsonl", reader.requested)


class TestSimilarClipsFeatures(unittest.TestCase):
    def test_feature_version_was_bumped_and_stale_cache_is_recomputed(self) -> None:
        self.assertGreaterEqual(FEATURE_VERSION, 3)
        stale = {"version": FEATURE_VERSION - 1}
        target = build_job(job_id=JOB_ID, features=stale)
        jobs = FakeJobsForSimilar(target, [])
        reader = v2_reader([shot()])
        with self.assertRaises(Exception) as ctx:
            GetSimilarClipsUseCase(jobs=jobs, artifacts=reader, team_access=FakeAccess()).execute(
                user_id=USER_ID, team_id=TEAM_ID, job_id="missing"
            )
        self.assertIsInstance(ctx.exception, JobError)
        GetSimilarClipsUseCase(jobs=jobs, artifacts=reader, team_access=FakeAccess()).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID
        )
        self.assertEqual(jobs.set_features_calls, 1)
        self.assertIn("player_paths.jsonl", reader.requested)

    def test_paths_become_tick_aligned_rows(self) -> None:
        rows = rows_from_player_paths(PATHS, fps=30.0)
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["frame_index"] for r in rows[:3]], [0, 1, 2])
        self.assertEqual(rows[0]["stable_player_id"], "player-010")

    def test_per_frame_rows_are_thinned_to_five_hz(self) -> None:
        rows = [{"frame_index": f, "track_id": 1, "court_xy_m": [1.0, 1.0]} for f in range(60)]
        thinned = resample_rows(rows, fps=30.0)
        self.assertEqual(len(thinned), 10)


class TestEventsEndpoint(unittest.TestCase):
    def client(self, use_case):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.interfaces.http.routes.stats_router import create_stats_router

        app = FastAPI()

        @app.middleware("http")
        async def _inject_user(request, call_next):
            request.state.user_id = USER_ID
            return await call_next(request)

        unused = object()
        app.include_router(create_stats_router(
            game_stats_use_case=unused, court_positions_use_case=unused,
            shot_chart_use_case=unused, team_sides_use_case=unused,
            similar_clips_use_case=unused, events_use_case=use_case,
        ))
        return TestClient(app)

    def test_returns_events_through_the_real_use_case(self) -> None:
        use_case = GetEventsUseCase(
            jobs=FakeJobs(build_job()), artifacts=v2_reader([shot()]), team_access=FakeAccess()
        )
        body = self.client(use_case).get(f"/jobs/{JOB_ID}/events", params={"team_id": TEAM_ID}).json()
        self.assertEqual(body["events"][0]["type"], "shot")
        self.assertEqual(body["video"]["fps"], 30.0)

    def test_unfinished_job_maps_to_conflict(self) -> None:
        use_case = GetEventsUseCase(
            jobs=FakeJobs(build_job(status=JobStatus.RUNNING)), artifacts=v2_reader([]),
            team_access=FakeAccess(),
        )
        response = self.client(use_case).get(f"/jobs/{JOB_ID}/events", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 409)

    def test_team_id_is_required(self) -> None:
        use_case = GetEventsUseCase(
            jobs=FakeJobs(build_job()), artifacts=v2_reader([]), team_access=FakeAccess()
        )
        self.assertEqual(self.client(use_case).get(f"/jobs/{JOB_ID}/events").status_code, 422)


if __name__ == "__main__":
    unittest.main()
