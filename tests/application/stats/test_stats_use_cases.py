"""Guards and shaping around the statistics reads.

Covers what happens when a job is not finished, when files are missing, and how
per-frame position rows become per-player paths.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.application.jobs.errors import (
    JOB_NOT_FINISHED,
    JOB_NOT_FOUND,
    RESULTS_NOT_AVAILABLE,
    JobError,
)
from src.application.stats.ports import ArtifactReadError
from dataclasses import dataclass

from src.application.stats.use_cases import (
    GetCourtPositionsUseCase,
    GetGameStatsUseCase,
    GetShotChartUseCase,
    GetTeamSidesUseCase,
)


@dataclass
class RosterPlayer:
    id: str
    first_name: str
    last_name: str
    jersey_number: str | None
from src.domain.jobs.entities import JobStatus, ProcessingJob

_UNSET = object()

USER_ID = "user-1"
TEAM_ID = "11111111-1111-1111-1111-111111111111"
JOB_ID = "33333333-3333-3333-3333-333333333333"


def build_job(
    status: JobStatus = JobStatus.DONE,
    results_key: str | None = "results/t/j",
    our_team_side: int | None = None,
    job_id: str = JOB_ID,
    video_id: str = "v1",
    features: dict | None = None,
):
    now = datetime.now(timezone.utc)
    return ProcessingJob(
        id=job_id, video_id=video_id, team_id=TEAM_ID, requested_by_user_id=USER_ID,
        status=status, external_job_id=None, results_key=results_key,
        error_message=None, progress_percent=100,
        started_at=now, finished_at=now, created_at=now, updated_at=now,
        our_team_side=our_team_side, features=features,
    )


class FakeJobs:
    def __init__(self, job=None):
        self.job = job

    def get_by_id(self, **_kwargs):
        return self.job


class FakeAccess:
    def assert_access(self, **_kwargs):
        return None


class FakeRoster:
    """Serves the scout's roster players for the linking-by-number step."""

    def __init__(self, players=None):
        self.players = players or []
        self.calls = 0

    def list_by_owner_and_team(self, **_kwargs):
        self.calls += 1
        return self.players


class FakeReader:
    """Serves canned documents; can also simulate an unreadable file."""

    def __init__(self, documents=None, rows=None, raises=False):
        self.documents = documents or {}
        self.rows = rows or []
        self.raises = raises
        self.requested: list[str] = []

    def read_json(self, *, results_key, filename):
        if self.raises:
            raise ArtifactReadError("storage unavailable")
        self.requested.append(filename)
        return self.documents.get(filename)

    def read_jsonl(self, *, results_key, filename, max_lines):
        if self.raises:
            raise ArtifactReadError("storage unavailable")
        self.requested.append(filename)
        return self.rows[:max_lines]


SHOTS = {"shots": [{
    "event_id": 1, "outcome": "made", "shot_origin_court_xy_m": [3.867, 13.267],
    "shooter_track_id": 9, "shooter_team_id": 1, "start_timestamp_seconds": 4.0,
}]}
TEAMS = {"assignments": [{"track_id": 9, "team_id": 1}]}
NUMBERS = {"tracks": [{"track_id": 9, "status": "confirmed", "number": "22"}]}


class TestGetGameStats(unittest.TestCase):
    def build(self, *, job=_UNSET, reader=None, roster=None):
        return GetGameStatsUseCase(
            jobs=FakeJobs(build_job() if job is _UNSET else job),
            artifacts=reader or FakeReader({
                "projected_shots.json": SHOTS,
                "teams.json": TEAMS,
                "numbers.json": NUMBERS,
            }),
            team_access=FakeAccess(),
            roster=roster or FakeRoster(),
        )

    def test_returns_a_box_score(self) -> None:
        result = self.build().execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["teams"][0]["points"], 2)
        self.assertEqual(result["players"][0]["display_name"], "#22")
        self.assertEqual(len(result["shots"]), 1)

    def test_never_reads_the_large_track_dump(self) -> None:
        """tracks.jsonl can reach ~100MB; it must not be touched by a web request."""

        reader = FakeReader({"projected_shots.json": SHOTS, "teams.json": TEAMS})
        self.build(reader=reader).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertNotIn("tracks.jsonl", reader.requested)

    def test_unfinished_job_is_rejected(self) -> None:
        use_case = self.build(job=build_job(status=JobStatus.RUNNING))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, JOB_NOT_FINISHED)

    def test_unknown_job_is_not_found(self) -> None:
        use_case = self.build(job=None)
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, JOB_NOT_FOUND)

    def test_job_without_a_results_location_is_reported(self) -> None:
        use_case = self.build(job=build_job(results_key=None))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, RESULTS_NOT_AVAILABLE)

    def test_unreadable_storage_becomes_a_clean_error(self) -> None:
        use_case = self.build(reader=FakeReader(raises=True))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, RESULTS_NOT_AVAILABLE)

    def test_job_with_no_output_at_all_is_reported(self) -> None:
        use_case = self.build(reader=FakeReader({}))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, RESULTS_NOT_AVAILABLE)

    def test_missing_numbers_file_still_produces_stats(self) -> None:
        """Jersey reading is optional; totals must survive without it."""

        reader = FakeReader({"projected_shots.json": SHOTS, "teams.json": TEAMS})
        result = self.build(reader=reader).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID
        )
        self.assertEqual(result["teams"][0]["points"], 2)
        self.assertEqual(result["players"][0]["display_name"], "Player 9")


class TestGetShotChart(unittest.TestCase):
    def build(self, *, job=_UNSET, reader=None, roster=None):
        return GetShotChartUseCase(
            jobs=FakeJobs(build_job() if job is _UNSET else job),
            artifacts=reader or FakeReader({
                "projected_shots.json": SHOTS,
                "teams.json": TEAMS,
                "numbers.json": NUMBERS,
            }),
            team_access=FakeAccess(),
            roster=roster or FakeRoster(),
        )

    def test_returns_markers_with_court_geometry(self) -> None:
        result = self.build().execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(len(result["shots"]), 1)
        self.assertEqual(result["shots"][0]["result"], "made")
        self.assertEqual(result["court"]["length_m"], 28.0)

    def test_track_id_filter_is_passed_through(self) -> None:
        result = self.build().execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, track_id=999
        )
        self.assertEqual(result["shots"], [])
        self.assertEqual(result["coverage"]["filtered_to_track_id"], 999)

    def test_never_reads_the_large_track_dump(self) -> None:
        reader = FakeReader({"projected_shots.json": SHOTS, "teams.json": TEAMS})
        self.build(reader=reader).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertNotIn("tracks.jsonl", reader.requested)

    def test_unfinished_job_is_rejected(self) -> None:
        use_case = self.build(job=build_job(status=JobStatus.RUNNING))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, JOB_NOT_FINISHED)

    def test_job_with_no_output_at_all_is_reported(self) -> None:
        use_case = self.build(reader=FakeReader({}))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, RESULTS_NOT_AVAILABLE)


class TestRosterLinkingThroughUseCase(unittest.TestCase):
    """The chosen side plus the roster resolve real names in the stats read."""

    ROSTER = [RosterPlayer(id="p-22", first_name="Jane", last_name="Doe", jersey_number="22")]

    def build(self, *, side):
        return GetGameStatsUseCase(
            jobs=FakeJobs(build_job(our_team_side=side)),
            artifacts=FakeReader({
                "projected_shots.json": SHOTS, "teams.json": TEAMS, "numbers.json": NUMBERS,
            }),
            team_access=FakeAccess(),
            roster=FakeRoster(self.ROSTER),
        )

    def test_chosen_side_gets_real_names(self) -> None:
        result = self.build(side=1).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["our_team_side"], 1)
        linked = next(p for p in result["players"] if p["track_id"] == 9)
        self.assertEqual(linked["display_name"], "Jane Doe")

    def test_no_chosen_side_means_the_roster_is_never_read(self) -> None:
        roster = FakeRoster(self.ROSTER)
        GetGameStatsUseCase(
            jobs=FakeJobs(build_job(our_team_side=None)),
            artifacts=FakeReader({
                "projected_shots.json": SHOTS, "teams.json": TEAMS, "numbers.json": NUMBERS,
            }),
            team_access=FakeAccess(),
            roster=roster,
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        # Nothing to link against without a side, so the roster is left untouched.
        self.assertEqual(roster.calls, 0)


class TestGetTeamSides(unittest.TestCase):
    TEAMS2 = {"assignments": [
        {"track_id": 10, "team_id": 1}, {"track_id": 11, "team_id": 1},
        {"track_id": 20, "team_id": 0},
    ]}
    NUMBERS2 = {"tracks": [
        {"track_id": 10, "status": "confirmed", "number": "7"},
        {"track_id": 11, "status": "confirmed", "number": "9"},
        {"track_id": 20, "status": "confirmed", "number": "23"},
    ]}
    ROSTER = [
        RosterPlayer(id="p7", first_name="Jaylen", last_name="Brown", jersey_number="7"),
        RosterPlayer(id="p9", first_name="Derrick", last_name="White", jersey_number="9"),
    ]

    def build(self, *, roster=None):
        return GetTeamSidesUseCase(
            jobs=FakeJobs(build_job()),
            artifacts=FakeReader({"teams.json": self.TEAMS2, "numbers.json": self.NUMBERS2}),
            team_access=FakeAccess(),
            roster=FakeRoster(self.ROSTER if roster is None else roster),
        )

    def test_suggests_the_side_that_matches_our_roster(self) -> None:
        result = self.build().execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["suggested_team_side"], 1)
        side1 = next(s for s in result["sides"] if s["team_side"] == 1)
        self.assertEqual(side1["roster_matches"], 2)

    def test_no_roster_overlap_makes_no_suggestion(self) -> None:
        empty = [RosterPlayer(id="p0", first_name="No", last_name="One", jersey_number="55")]
        result = self.build(roster=empty).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertIsNone(result["suggested_team_side"])

    def test_reports_the_current_selection(self) -> None:
        use_case = GetTeamSidesUseCase(
            jobs=FakeJobs(build_job(our_team_side=1)),
            artifacts=FakeReader({"teams.json": self.TEAMS2, "numbers.json": self.NUMBERS2}),
            team_access=FakeAccess(),
            roster=FakeRoster(self.ROSTER),
        )
        result = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["our_team_side"], 1)


class FakeJobsForSimilar:
    def __init__(self, target, others):
        self._target = target
        self._all = [target, *others]
        self.set_features_calls = 0

    def get_by_id(self, *, job_id, **_kwargs):
        return next((j for j in self._all if j.id == job_id), None)

    def list_done_by_team(self, **_kwargs):
        return self._all

    def set_features(self, *, job_id, team_id, features):
        self.set_features_calls += 1
        return None


def make_features(*, shot_points, rows):
    from src.domain.stats.similarity import build_clip_features
    shots_doc = {"shots": [{"shot_origin_court_xy_m": xy, "outcome": o} for xy, o in shot_points]}
    position_rows = [{"frame_index": f, "track_id": t, "court_xy_m": [x, y]} for f, t, x, y in rows]
    return build_clip_features(shots_document=shots_doc, position_rows=position_rows)


class TestGetSimilarClips(unittest.TestCase):
    def test_ranks_more_similar_clips_higher_and_excludes_self(self) -> None:
        from src.application.stats.use_cases import GetSimilarClipsUseCase

        rim = make_features(shot_points=[([2.5, 7.5], "made")], rows=[(0, 1, 2.0, 7.5), (1, 1, 2.2, 7.5)])
        arc = make_features(shot_points=[([9.5, 7.5], "missed")], rows=[(0, 1, 25.0, 1.0), (1, 1, 26.0, 14.0)])

        target = build_job(job_id=JOB_ID, features=rim)
        twin = build_job(job_id="twin", video_id="v-twin", features=rim)
        far = build_job(job_id="far", video_id="v-far", features=arc)
        jobs = FakeJobsForSimilar(target, [twin, far])

        use_case = GetSimilarClipsUseCase(
            jobs=jobs, artifacts=FakeReader({}), team_access=FakeAccess()
        )
        result = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)

        ids = [r["job_id"] for r in result["results"]]
        self.assertEqual(ids, ["twin", "far"])
        self.assertNotIn(JOB_ID, ids)
        self.assertGreater(result["results"][0]["score"], result["results"][1]["score"])

    def test_cached_features_are_not_recomputed(self) -> None:
        from src.application.stats.use_cases import GetSimilarClipsUseCase

        feats = make_features(shot_points=[([2.5, 7.5], "made")], rows=[(0, 1, 2.0, 7.5)])
        target = build_job(job_id=JOB_ID, features=feats)
        other = build_job(job_id="o2", video_id="v2", features=feats)
        jobs = FakeJobsForSimilar(target, [other])
        GetSimilarClipsUseCase(
            jobs=jobs, artifacts=FakeReader({}), team_access=FakeAccess()
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(jobs.set_features_calls, 0)

    def test_limit_caps_the_results(self) -> None:
        from src.application.stats.use_cases import GetSimilarClipsUseCase

        feats = make_features(shot_points=[([2.5, 7.5], "made")], rows=[(0, 1, 2.0, 7.5)])
        target = build_job(job_id=JOB_ID, features=feats)
        others = [build_job(job_id=f"o{i}", video_id=f"v{i}", features=feats) for i in range(4)]
        jobs = FakeJobsForSimilar(target, others)
        result = GetSimilarClipsUseCase(
            jobs=jobs, artifacts=FakeReader({}), team_access=FakeAccess()
        ).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, limit=2)
        self.assertEqual(len(result["results"]), 2)


def position_row(frame_index: int, track_id: int, x: float, y: float) -> dict:
    return {"frame_index": frame_index, "track_id": track_id, "court_xy_m": [x, y]}


class TestGetCourtPositions(unittest.TestCase):
    def build(self, rows, *, job=_UNSET):
        return GetCourtPositionsUseCase(
            jobs=FakeJobs(build_job() if job is _UNSET else job),
            artifacts=FakeReader({"teams.json": TEAMS, "numbers.json": NUMBERS}, rows=rows),
            team_access=FakeAccess(),
        )

    def test_groups_per_frame_rows_into_player_paths(self) -> None:
        rows = [
            position_row(0, 9, 6.4, 10.6), position_row(4, 9, 6.8, 10.2),
            position_row(0, 5, 2.4, 5.8),
        ]
        result = self.build(rows).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        by_track = {p["track_id"]: p for p in result["players"]}
        self.assertEqual(len(by_track[9]["positions"]), 2)
        self.assertEqual(len(by_track[5]["positions"]), 1)

    def test_v2_segmented_tracks_group_into_one_path_per_stable_player(self) -> None:
        """A v2 player split across segment track_ids is one path, not many."""

        rows = [
            {"frame_index": 0, "track_id": 100, "stable_player_id": "pX", "court_xy_m": [5.0, 7.5]},
            {"frame_index": 1, "track_id": 101, "stable_player_id": "pX", "court_xy_m": [6.0, 7.5]},
            {"frame_index": 0, "track_id": 200, "stable_player_id": "pY", "court_xy_m": [8.0, 7.5]},
        ]
        result = self.build(rows).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(len(result["players"]), 2)
        by_stable = {p["stable_player_id"]: p for p in result["players"]}
        self.assertEqual(len(by_stable["pX"]["positions"]), 2)
        self.assertEqual(len(by_stable["pY"]["positions"]), 1)

    def test_court_dimensions_are_included_for_drawing(self) -> None:
        result = self.build([position_row(0, 9, 6.4, 10.6)]).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID
        )
        self.assertEqual(result["court"], {"length_m": 28.0, "width_m": 15.0})

    def test_team_and_number_are_attached(self) -> None:
        result = self.build([position_row(0, 9, 6.4, 10.6)]).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID
        )
        self.assertEqual(result["players"][0]["team_id"], 1)
        self.assertEqual(result["players"][0]["jersey_number"], "22")

    def test_broken_projections_are_discarded(self) -> None:
        """A player placed 400m away would wreck a heatmap."""

        rows = [position_row(0, 9, 6.4, 10.6), position_row(4, 9, 400.0, 10.0)]
        result = self.build(rows).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(len(result["players"][0]["positions"]), 1)
        self.assertEqual(result["coverage"]["records_off_court"], 1)

    def test_sampling_thins_long_paths(self) -> None:
        rows = [position_row(i, 9, 5.0 + i * 0.1, 7.5) for i in range(10)]
        result = self.build(rows).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, sample_every=5
        )
        self.assertEqual(len(result["players"][0]["positions"]), 2)

    def test_sampling_is_per_player_not_global(self) -> None:
        """Interleaved rows must not thin one player away entirely."""

        rows = []
        for i in range(6):
            rows.append(position_row(i, 9, 5.0, 7.5))
            rows.append(position_row(i, 5, 8.0, 7.5))
        result = self.build(rows).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, sample_every=3
        )
        counts = {p["track_id"]: len(p["positions"]) for p in result["players"]}
        self.assertEqual(counts, {9: 2, 5: 2})

    def test_movement_reports_distance_and_average_position(self) -> None:
        rows = [position_row(0, 9, 0.0, 0.0), position_row(4, 9, 3.0, 4.0)]
        result = self.build(rows).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        movement = result["players"][0]["movement"]
        self.assertEqual(movement["distance_m"], 5.0)
        self.assertEqual(movement["samples"], 2)
        self.assertEqual(movement["average_position"], {"x_m": 1.5, "y_m": 2.0})

    def test_distance_is_measured_over_the_full_path_not_the_sampled_one(self) -> None:
        """Summing a thinned path would understate how far a player ran."""

        rows = [position_row(i, 9, float(i), 0.0) for i in range(6)]
        result = self.build(rows).execute(
            user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, sample_every=5
        )
        player = result["players"][0]
        self.assertEqual(len(player["positions"]), 2)
        self.assertEqual(player["movement"]["distance_m"], 5.0)
        self.assertEqual(player["movement"]["samples"], 6)

    def test_rows_without_a_track_are_ignored(self) -> None:
        rows = [{"frame_index": 0, "court_xy_m": [5.0, 7.5]}, position_row(0, 9, 5.0, 7.5)]
        result = self.build(rows).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(len(result["players"]), 1)

    def test_empty_positions_file_returns_an_empty_result(self) -> None:
        result = self.build([]).execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["players"], [])
        self.assertFalse(result["coverage"]["truncated"])

    def test_unfinished_job_is_rejected(self) -> None:
        use_case = self.build([], job=build_job(status=JobStatus.QUEUED))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, JOB_NOT_FINISHED)


if __name__ == "__main__":
    unittest.main()


class TestPositionsFromEitherPipeline(unittest.TestCase):
    """A caller should not need to know which pipeline produced the job."""

    def build(self, documents, rows):
        reader = FakeReader(documents, rows=rows)
        return GetCourtPositionsUseCase(
            jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess()
        ), reader

    def test_reads_the_stats_pipeline_position_file(self) -> None:
        rows = [{"frame_index": 0, "track_id": 9, "court_xy_m": [6.4, 10.6]}]
        use_case, _ = self.build({"teams.json": TEAMS, "numbers.json": NUMBERS}, rows)
        result = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["players"][0]["track_id"], 9)
        self.assertEqual(result["coverage"]["source_file"], "projected_tracks.jsonl")

    def test_reads_the_player_positions_pipeline_file(self) -> None:
        """That pipeline names the identifier `player_id`, not `track_id`."""

        class OnlyPlayerPositions(FakeReader):
            def read_jsonl(self, *, results_key, filename, max_lines):
                if filename != "player_positions.jsonl":
                    return []
                return self.rows[:max_lines]

        reader = OnlyPlayerPositions(
            {"teams.json": TEAMS, "numbers.json": NUMBERS},
            rows=[{"frame_index": 0, "player_id": 9, "team_id": 1, "court_xy_m": [6.4, 10.6]}],
        )
        use_case = GetCourtPositionsUseCase(
            jobs=FakeJobs(build_job()), artifacts=reader, team_access=FakeAccess()
        )
        result = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["players"][0]["track_id"], 9)
        self.assertEqual(result["players"][0]["team_id"], 1)
        self.assertEqual(result["coverage"]["source_file"], "player_positions.jsonl")

    def test_no_positions_from_either_pipeline_is_empty_not_an_error(self) -> None:
        use_case, _ = self.build({"teams.json": TEAMS}, [])
        result = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(result["players"], [])
        self.assertIsNone(result["coverage"]["source_file"])
