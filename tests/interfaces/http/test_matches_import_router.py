from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.matches.excel_import import PreviewMatchStatsImportUseCase
from src.infrastructure.matches.cabb_box_score_parser import MAX_FILE_BYTES, CabbBoxScoreParser
from src.interfaces.http.routes.matches_router import create_matches_router
from tests.box_score_fixtures import as_csv, as_xlsx, grid

HOME = "00000000-0000-4000-8000-000000000010"
AWAY = "00000000-0000-4000-8000-000000000020"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Teams:
    def __init__(self, home="Club Alfa", away="Club Beta"):
        self._names = (home, away)

    def list_by_owner(self, *, owner_user_id):
        return [NS(id=HOME, name=self._names[0]), NS(id=AWAY, name=self._names[1])]


class _Players:
    def list_by_owner_and_team(self, *, owner_user_id, team_id):
        return [NS(id="p4", first_name="Uno", last_name="Alfa", jersey_number="4")] if team_id == HOME else []


def _client(*, with_import: bool = True, teams=None) -> TestClient:
    unused = NS()
    app = FastAPI()

    @app.middleware("http")
    async def user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    app.include_router(
        create_matches_router(
            create_match_use_case=unused,
            list_matches_use_case=unused,
            get_match_use_case=unused,
            replace_match_stats_use_case=unused,
            get_match_stats_use_case=unused,
            update_match_use_case=unused,
            preview_stats_import_use_case=(
                PreviewMatchStatsImportUseCase(parser=CabbBoxScoreParser(), teams=teams or _Teams(), players=_Players())
                if with_import
                else None
            ),
        )
    )
    return TestClient(app)


class TestImportPreviewEndpoint(unittest.TestCase):
    def test_xlsx_upload_returns_a_draft_that_matches_the_put_payload(self) -> None:
        response = _client().post(
            "/matches/stats/import-preview",
            files={"file": ("stats.xlsx", as_xlsx(grid()), XLSX)},
            data={"home_team_id": HOME, "away_team_id": AWAY},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["winner_team_id"], HOME)
        self.assertEqual(body["report"]["linked_players"][0]["player_id"], "p4")
        self.assertEqual(body["stats"]["source"], "cabb_excel")
        for participant in body["participants"]:
            self.assertIn(participant["team_side"], ("HOME", "AWAY"))
            self.assertTrue(participant["display_name"])

    def test_csv_upload_works_and_teams_are_optional(self) -> None:
        response = _client().post(
            "/matches/stats/import-preview",
            files={"file": ("stats.csv", as_csv(grid()), "text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["winner_team_id"])

    def test_invalid_file_is_422_with_the_error_envelope(self) -> None:
        response = _client().post(
            "/matches/stats/import-preview", files={"file": ("x.xlsx", b"garbage", XLSX)}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_STATS_FILE")

    def test_oversized_file_is_413(self) -> None:
        response = _client().post(
            "/matches/stats/import-preview", files={"file": ("x.xlsx", b"x" * (MAX_FILE_BYTES + 10), XLSX)}
        )
        self.assertEqual(response.status_code, 413)

    def test_unknown_team_is_404_and_missing_file_is_422(self) -> None:
        client = _client()
        response = client.post(
            "/matches/stats/import-preview",
            files={"file": ("s.xlsx", as_xlsx(grid()), XLSX)},
            data={"home_team_id": "00000000-0000-4000-8000-0000000000ff"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(client.post("/matches/stats/import-preview").status_code, 422)

    def test_a_different_team_is_422_unless_the_mismatch_is_allowed(self) -> None:
        # HOME still matches through its roster (jersey 4, surname Alfa); AWAY has neither name nor roster.
        client = _client(teams=_Teams("Zeta Squad", "Omega Five"))
        response = client.post(
            "/matches/stats/import-preview",
            files={"file": ("s.xlsx", as_xlsx(grid()), XLSX)},
            data={"home_team_id": HOME, "away_team_id": AWAY},
        )
        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "TEAM_MISMATCH")
        self.assertEqual([t["side"] for t in error["details"]["teams"]], ["AWAY"])
        self.assertEqual(error["details"]["teams"][0]["name_in_file"], "Club Beta")

        allowed = client.post(
            "/matches/stats/import-preview",
            files={"file": ("s.xlsx", as_xlsx(grid()), XLSX)},
            data={"home_team_id": HOME, "away_team_id": AWAY, "allow_team_mismatch": "true"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(any("does not look like" in w for w in allowed.json()["report"]["warnings"]))

    def test_route_is_absent_when_the_use_case_is_not_wired(self) -> None:
        response = _client(with_import=False).post(
            "/matches/stats/import-preview", files={"file": ("s.xlsx", as_xlsx(grid()), XLSX)}
        )
        self.assertNotEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
