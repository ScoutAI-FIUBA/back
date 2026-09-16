from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.jobs.errors import JOB_NOT_FINISHED, JOB_NOT_FOUND, JobError
from src.interfaces.http.routes.stats_router import create_stats_router

TEAM_ID = "11111111-1111-1111-1111-111111111111"
JOB_ID = "33333333-3333-3333-3333-333333333333"

BOX_SCORE = {
    "job_id": JOB_ID,
    "teams": [{"team_id": 1, "points": 2, "field_goals_made": 1, "field_goals_attempted": 1}],
    "players": [{"track_id": 9, "display_name": "#22", "points": 2}],
    "shots": [{"made": True, "points": 2, "court_x_m": 3.87, "court_y_m": 13.27}],
    "coverage": {"measures": ["shooting"], "not_measured": ["rebounds"]},
}

POSITIONS = {
    "job_id": JOB_ID,
    "court": {"length_m": 28.0, "width_m": 15.0},
    "players": [{"track_id": 9, "positions": [{"frame_index": 0, "x_m": 6.4, "y_m": 10.6}]}],
    "coverage": {"records_read": 1, "sample_every": 1, "truncated": False},
}

SHOT_CHART = {
    "job_id": JOB_ID,
    "court": {"length_m": 28.0, "width_m": 15.0, "hoops": {"home": {}, "away": {}}},
    "shots": [{"track_id": 9, "x_m": 3.87, "y_m": 13.27, "made": True, "result": "made"}],
    "players": [{"track_id": 9, "display_name": "#22", "shots": []}],
    "coverage": {"shots_charted": 1, "filtered_to_track_id": None},
}


class _Ok:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self.value


class _Raises:
    def __init__(self, code):
        self.code = code

    def execute(self, **_kwargs):
        raise JobError(code=self.code, message=f"failed: {self.code}")


TEAM_SIDES = {
    "job_id": JOB_ID,
    "our_team_side": None,
    "suggested_team_side": 1,
    "sides": [
        {"team_side": 0, "track_count": 5, "numbers": ["23"], "roster_matches": 0},
        {"team_side": 1, "track_count": 5, "numbers": ["7", "9"], "roster_matches": 2},
    ],
    "roster_numbers_known": 12,
}


SIMILAR = {
    "job_id": JOB_ID,
    "movement_weight": 0.5,
    "results": [{"job_id": "other", "video_id": "v2", "score": 0.82, "shot_score": 0.9, "movement_score": 0.74}],
    "candidates_compared": 1,
}


def build_client(
    *, stats=None, positions=None, shot_chart=None, team_sides=None, similar=None
) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    app.include_router(
        create_stats_router(
            game_stats_use_case=stats or _Ok(BOX_SCORE),
            court_positions_use_case=positions or _Ok(POSITIONS),
            shot_chart_use_case=shot_chart or _Ok(SHOT_CHART),
            team_sides_use_case=team_sides or _Ok(TEAM_SIDES),
            similar_clips_use_case=similar or _Ok(SIMILAR),
        )
    )
    return TestClient(app)


class TestGameStatsEndpoint(unittest.TestCase):
    def test_returns_a_box_score(self) -> None:
        body = build_client().get(f"/jobs/{JOB_ID}/stats", params={"team_id": TEAM_ID}).json()
        self.assertEqual(body["teams"][0]["points"], 2)
        self.assertEqual(body["players"][0]["display_name"], "#22")

    def test_states_what_is_not_measured(self) -> None:
        """So the interface never implies a complete stat line."""

        body = build_client().get(f"/jobs/{JOB_ID}/stats", params={"team_id": TEAM_ID}).json()
        self.assertEqual(body["coverage"]["measures"], ["shooting"])

    def test_unfinished_job_is_conflict(self) -> None:
        client = build_client(stats=_Raises(JOB_NOT_FINISHED))
        response = client.get(f"/jobs/{JOB_ID}/stats", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 409)

    def test_unknown_job_is_404(self) -> None:
        client = build_client(stats=_Raises(JOB_NOT_FOUND))
        response = client.get(f"/jobs/{JOB_ID}/stats", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 404)

    def test_team_id_is_required(self) -> None:
        self.assertEqual(build_client().get(f"/jobs/{JOB_ID}/stats").status_code, 422)

    def test_non_uuid_job_id_is_rejected(self) -> None:
        response = build_client().get("/jobs/not-a-uuid/stats", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 422)


class TestCourtPositionsEndpoint(unittest.TestCase):
    def test_returns_player_paths_with_court_size(self) -> None:
        body = build_client().get(
            f"/jobs/{JOB_ID}/court-positions", params={"team_id": TEAM_ID}
        ).json()
        self.assertEqual(body["court"]["length_m"], 28.0)
        self.assertEqual(body["players"][0]["track_id"], 9)

    def test_sample_every_is_passed_through(self) -> None:
        use_case = _Ok(POSITIONS)
        build_client(positions=use_case).get(
            f"/jobs/{JOB_ID}/court-positions", params={"team_id": TEAM_ID, "sample_every": 10}
        )
        self.assertEqual(use_case.calls[0]["sample_every"], 10)

    def test_sample_every_defaults_to_every_position(self) -> None:
        use_case = _Ok(POSITIONS)
        build_client(positions=use_case).get(
            f"/jobs/{JOB_ID}/court-positions", params={"team_id": TEAM_ID}
        )
        self.assertEqual(use_case.calls[0]["sample_every"], 1)

    def test_sample_every_is_bounded(self) -> None:
        """Guards against a request that would thin the data to nothing."""

        client = build_client()
        self.assertEqual(
            client.get(f"/jobs/{JOB_ID}/court-positions",
                       params={"team_id": TEAM_ID, "sample_every": 0}).status_code, 422)
        self.assertEqual(
            client.get(f"/jobs/{JOB_ID}/court-positions",
                       params={"team_id": TEAM_ID, "sample_every": 5000}).status_code, 422)

    def test_unfinished_job_is_conflict(self) -> None:
        client = build_client(positions=_Raises(JOB_NOT_FINISHED))
        response = client.get(f"/jobs/{JOB_ID}/court-positions", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 409)


class TestShotChartEndpoint(unittest.TestCase):
    def test_returns_markers_with_court_geometry(self) -> None:
        body = build_client().get(
            f"/jobs/{JOB_ID}/shot-chart", params={"team_id": TEAM_ID}
        ).json()
        self.assertEqual(body["shots"][0]["result"], "made")
        self.assertEqual(body["court"]["length_m"], 28.0)

    def test_track_id_is_passed_through(self) -> None:
        use_case = _Ok(SHOT_CHART)
        build_client(shot_chart=use_case).get(
            f"/jobs/{JOB_ID}/shot-chart", params={"team_id": TEAM_ID, "track_id": 9}
        )
        self.assertEqual(use_case.calls[0]["track_id"], 9)

    def test_track_id_is_optional(self) -> None:
        use_case = _Ok(SHOT_CHART)
        build_client(shot_chart=use_case).get(
            f"/jobs/{JOB_ID}/shot-chart", params={"team_id": TEAM_ID}
        )
        self.assertIsNone(use_case.calls[0]["track_id"])

    def test_unknown_job_is_404(self) -> None:
        client = build_client(shot_chart=_Raises(JOB_NOT_FOUND))
        response = client.get(f"/jobs/{JOB_ID}/shot-chart", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 404)

    def test_team_id_is_required(self) -> None:
        self.assertEqual(build_client().get(f"/jobs/{JOB_ID}/shot-chart").status_code, 422)


class TestSimilarClipsEndpoint(unittest.TestCase):
    def test_returns_ranked_results(self) -> None:
        body = build_client().get(
            f"/jobs/{JOB_ID}/similar", params={"team_id": TEAM_ID}
        ).json()
        self.assertEqual(body["results"][0]["score"], 0.82)

    def test_movement_weight_is_passed_through(self) -> None:
        use_case = _Ok(SIMILAR)
        build_client(similar=use_case).get(
            f"/jobs/{JOB_ID}/similar", params={"team_id": TEAM_ID, "movement_weight": 0.8}
        )
        self.assertEqual(use_case.calls[0]["movement_weight"], 0.8)

    def test_movement_weight_is_bounded(self) -> None:
        client = build_client()
        self.assertEqual(
            client.get(f"/jobs/{JOB_ID}/similar",
                       params={"team_id": TEAM_ID, "movement_weight": 2}).status_code, 422)

    def test_unknown_job_is_404(self) -> None:
        client = build_client(similar=_Raises(JOB_NOT_FOUND))
        response = client.get(f"/jobs/{JOB_ID}/similar", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
