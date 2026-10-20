import unittest
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.players.errors import PLAYER_NOT_FOUND, PlayerError
from src.interfaces.http.routes.players_router import create_players_router

PLAYER = "00000000-0000-4000-8000-000000000001"


class _Chart:
    def execute(self, *, user_id, player_id):
        if player_id != PLAYER:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return {"player_id": player_id, "court": {}, "shots": [{"x_m": 1.0, "y_m": 2.0, "result": "made"}],
                "coverage": {"shots_charted": 1}}


class _Totals:
    def execute(self, *, user_id, player_id):
        if player_id != PLAYER:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return {"player_id": player_id, "games": 2, "points": 5}


def _client(*, wired=True) -> TestClient:
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
        get_player_shot_chart_use_case=_Chart() if wired else None,
        get_player_analysis_stats_use_case=_Totals() if wired else None))
    return TestClient(app)


class TestPlayerAnalysisEndpoints(unittest.TestCase):
    def test_shot_chart_and_analysis_stats(self) -> None:
        client = _client()
        chart = client.get(f"/players/{PLAYER}/shot-chart")
        self.assertEqual(chart.status_code, 200)
        self.assertEqual(chart.json()["shots"][0]["result"], "made")
        totals = client.get(f"/players/{PLAYER}/analysis-stats")
        self.assertEqual((totals.status_code, totals.json()["points"]), (200, 5))

    def test_unknown_player_uses_the_error_envelope(self) -> None:
        response = _client().get("/players/00000000-0000-4000-8000-0000000000ff/shot-chart")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "PLAYER_NOT_FOUND")

    def test_routes_are_optional_so_existing_wiring_keeps_working(self) -> None:
        self.assertEqual(_client(wired=False).get(f"/players/{PLAYER}/shot-chart").status_code, 404)


if __name__ == "__main__":
    unittest.main()
