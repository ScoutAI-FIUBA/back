import unittest
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.players.errors import PLAYER_NOT_FOUND, PlayerError
from src.interfaces.http.routes.players_router import create_players_router

PLAYER = "00000000-0000-4000-8000-000000000001"


def _shot(**overrides):
    return {"shot_key": "j:1", "shot_id": 1, "job_id": "j", "video_id": "v", "video_title": "clip", "x_m": 1.0,
            "y_m": 2.0, "made": True, "result": "made", "shot_value": 3, "zone": "above_the_break",
            "shot_type": "jump_shot", "distance_m": 7.2, "timestamp_seconds": 6.67,
            "outcome_confidence": "detected", "outcome_source": "ball_path", "release_timestamp_seconds": 6.1,
            "resolved_timestamp_seconds": 7.0, "attribution": "action_box_vote", "needs_review": False, **overrides}


CHART = {"player_id": PLAYER, "calc_version": 2,
         "player": {"id": PLAYER, "first_name": "Jaylen", "last_name": "Brown", "jersey_number": "7",
                    "team_id": None},
         "court": {"length_m": 28.0}, "shots": [_shot()],
         "coverage": {"shots_charted": 1, "made": 1, "missed": 0, "unresolved": 0, "videos": 1}}

SECTION = {"made": 1, "attempted": 2, "pct": 0.5}
TOTALS = {"player_id": PLAYER, "calc_version": 2, "games": 2, "points": 5, "field_goals": SECTION,
          "two_point": {"made": 0, "attempted": 0, "pct": None}, "three_point": SECTION, "unresolved_attempts": 0,
          "seconds_on_screen": 22.5, "distance_m": None,
          "by_zone": {"paint": {"made": 1, "attempted": 2, "unresolved_attempts": 0, "pct": 0.5}},
          "by_shot_type": {}, "not_measured": ["rebounds"],
          "videos": [{"job_id": "j", "video_id": "v", "video_title": "clip", "jersey_number": "7",
                      "seconds_on_screen": 10.5, "distance_m": 21.0, "points": 3, "field_goals_made": 1,
                      "field_goals_attempted": 1, "two_point_made": 0, "two_point_attempted": 0,
                      "three_point_made": 1, "three_point_attempted": 1, "unresolved_attempts": 0}]}


class _Chart:
    def __init__(self, payload=None):
        self.payload = payload or CHART

    def execute(self, *, user_id, player_id):
        if player_id != PLAYER:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return self.payload


class _Totals:
    def __init__(self, payload=None):
        self.payload = payload or TOTALS

    def execute(self, *, user_id, player_id):
        if player_id != PLAYER:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return self.payload


def _client(*, wired=True, chart=None, totals=None) -> TestClient:
    unused = NS()
    app = FastAPI()

    @app.middleware("http")
    async def user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    app.include_router(create_players_router(
        create_player_use_case=unused, list_players_use_case=unused, list_players_by_team_use_case=unused,
        update_player_use_case=unused, delete_player_use_case=unused, assign_player_team_use_case=unused,
        get_player_stats_use_case=unused, get_player_matches_use_case=unused,
        get_player_shot_chart_use_case=_Chart(chart) if wired else None,
        get_player_analysis_stats_use_case=_Totals(totals) if wired else None))
    return TestClient(app)


class TestPlayerAnalysisEndpoints(unittest.TestCase):
    def test_shot_chart_and_analysis_stats(self) -> None:
        client = _client()
        chart = client.get(f"/players/{PLAYER}/shot-chart")
        self.assertEqual(chart.status_code, 200)
        self.assertEqual(chart.json()["shots"][0]["result"], "made")
        totals = client.get(f"/players/{PLAYER}/analysis-stats")
        self.assertEqual((totals.status_code, totals.json()["points"]), (200, 5))

    def test_the_responses_have_the_documented_shape(self) -> None:
        client = _client()
        chart = client.get(f"/players/{PLAYER}/shot-chart").json()
        self.assertEqual(set(chart), {"player_id", "player", "calc_version", "court", "shots", "coverage"})
        self.assertEqual(set(chart["shots"][0]), set(_shot()))
        self.assertEqual(set(chart["player"]), {"id", "first_name", "last_name", "jersey_number", "team_id"})
        totals = client.get(f"/players/{PLAYER}/analysis-stats").json()
        self.assertEqual(totals["calc_version"], 2)
        self.assertEqual(totals["seconds_on_screen"], 22.5)
        self.assertNotIn("seconds_observed", totals)
        self.assertEqual(totals["field_goals"], {"made": 1, "attempted": 2, "pct": 0.5})  # a fraction
        self.assertEqual(totals["two_point"]["pct"], None)
        self.assertNotIn("seconds_observed", totals["videos"][0])
        self.assertEqual(totals["videos"][0]["seconds_on_screen"], 10.5)

    def test_a_payload_off_the_contract_is_not_served(self) -> None:
        # The models are the contract: a shot value of 1 or a result nobody knows must not leak out.
        bad = {**CHART, "shots": [_shot(shot_value=1)]}
        with self.assertRaises(Exception):
            _client(chart=bad).get(f"/players/{PLAYER}/shot-chart")
        bad = {**CHART, "shots": [_shot(result="maybe")]}
        with self.assertRaises(Exception):
            _client(chart=bad).get(f"/players/{PLAYER}/shot-chart")

    def test_unknown_player_uses_the_error_envelope(self) -> None:
        response = _client().get("/players/00000000-0000-4000-8000-0000000000ff/shot-chart")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "PLAYER_NOT_FOUND")

    def test_routes_are_optional_so_existing_wiring_keeps_working(self) -> None:
        self.assertEqual(_client(wired=False).get(f"/players/{PLAYER}/shot-chart").status_code, 404)


if __name__ == "__main__":
    unittest.main()
