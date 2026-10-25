from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.matches.errors import MatchError, TEAM_NOT_FOUND as MATCH_TEAM_NOT_FOUND
from src.application.team.errors import TEAM_DELETE_CONFLICT, TEAM_HAS_MATCHES, TeamError
from src.application.team.use_cases import CreateTeamUseCase, DeleteTeamUseCase, ListTeamsUseCase, UpdateTeamUseCase
from src.domain.matches.entities import TeamMatchResultSummary, TeamStatsSummary
from src.domain.team.entities import Team
from src.interfaces.http.routes.team_router import create_team_router


class _TeamsRepo:
    def __init__(self, *, stored_is_own: bool = False, exists: bool = False) -> None:
        self.raise_conflict = False
        self.stored_is_own = stored_is_own
        self.exists = exists

    def create(self, team: Team) -> Team:
        return team

    def list_by_owner(self, *, owner_user_id: str) -> list[Team]:
        del owner_user_id
        return []

    def update(
        self,
        team_id: str,
        *,
        owner_user_id: str,
        name: str,
        short_name: str,
        city: str,
        country: str,
        is_own: bool | None = None,
    ):
        del owner_user_id
        if not self.exists:
            return None
        # Mirrors COALESCE(%(is_own)s, is_own) in the SQL adapter.
        if is_own is not None:
            self.stored_is_own = is_own
        return Team(
            id=team_id,
            name=name,
            short_name=short_name,
            city=city,
            country=country,
            owner_user_id="user-1",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            is_own=self.stored_is_own,
        )

    def delete(self, team_id: str, *, owner_user_id: str) -> bool:
        del team_id, owner_user_id
        if self.raise_conflict:
            raise TeamError(code=TEAM_HAS_MATCHES, message="Team has persisted matches")
        return True


class _Clock:
    def now(self):
        return datetime.now(timezone.utc)


class _Ids:
    def new_id(self) -> str:
        return "team-1"


class _DeleteTeamUseCase:
    def __init__(self, *, conflict_code: str | None = None) -> None:
        self._conflict_code = conflict_code

    def execute(self, command):
        del command
        if self._conflict_code is not None:
            message = (
                "Team has persisted matches"
                if self._conflict_code == TEAM_HAS_MATCHES
                else "Team cannot be deleted because related records still reference it"
            )
            raise TeamError(code=self._conflict_code, message=message)
        return True


class _TeamStatsUseCase:
    def __init__(self, *, missing: bool = False) -> None:
        self._missing = missing

    def execute(self, *, user_id: str, team_id: str) -> TeamStatsSummary:
        del user_id
        if self._missing:
            raise MatchError(code=MATCH_TEAM_NOT_FOUND, message="Team not found")
        return TeamStatsSummary(
            team_id=team_id,
            matches_played=1,
            wins=1,
            losses=0,
            results=[
                TeamMatchResultSummary(
                    match_id="match-1",
                    match_date=datetime(2024, 1, 2, tzinfo=timezone.utc).date(),
                    home_team_id=team_id,
                    away_team_id="team-2",
                    winner_team_id=team_id,
                    description="Final",
                    result="WIN",
                )
            ],
        )


def _build_client(
    *, delete_conflict_code: str | None = None, missing_stats_team: bool = False, teams: _TeamsRepo | None = None
) -> TestClient:
    teams = teams or _TeamsRepo()
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    app.include_router(
        create_team_router(
            create_team_use_case=CreateTeamUseCase(teams=teams, clock=_Clock(), ids=_Ids()),
            list_teams_use_case=ListTeamsUseCase(teams=teams),
            update_team_use_case=UpdateTeamUseCase(teams=teams),
            delete_team_use_case=_DeleteTeamUseCase(conflict_code=delete_conflict_code),
            get_team_stats_use_case=_TeamStatsUseCase(missing=missing_stats_team),
        )
    )
    return TestClient(app)


_TEAM_BODY = {"name": "Alpha", "short_name": "ALP", "city": "Cordoba", "country": "Argentina"}
_TEAM_URL = "/teams/00000000-0000-4000-8000-000000000001"


class TestTeamRouter(unittest.TestCase):
    def test_create_without_is_own_defaults_to_false(self) -> None:
        response = _build_client().post("/teams", json=_TEAM_BODY)
        self.assertEqual(response.status_code, 201)
        self.assertIs(response.json()["team"]["is_own"], False)

    def test_create_with_is_own_true(self) -> None:
        response = _build_client().post("/teams", json={**_TEAM_BODY, "is_own": True})
        self.assertEqual(response.status_code, 201)
        self.assertIs(response.json()["team"]["is_own"], True)

    def test_put_without_is_own_keeps_stored_value(self) -> None:
        client = _build_client(teams=_TeamsRepo(stored_is_own=True, exists=True))
        response = client.put(_TEAM_URL, json=_TEAM_BODY)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["team"]["is_own"], True)

    def test_put_with_null_is_own_keeps_stored_value(self) -> None:
        client = _build_client(teams=_TeamsRepo(stored_is_own=True, exists=True))
        response = client.put(_TEAM_URL, json={**_TEAM_BODY, "is_own": None})
        self.assertIs(response.json()["team"]["is_own"], True)

    def test_put_with_false_changes_stored_value(self) -> None:
        client = _build_client(teams=_TeamsRepo(stored_is_own=True, exists=True))
        response = client.put(_TEAM_URL, json={**_TEAM_BODY, "is_own": False})
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["team"]["is_own"], False)

    def test_put_with_true_changes_stored_value(self) -> None:
        client = _build_client(teams=_TeamsRepo(stored_is_own=False, exists=True))
        response = client.put(_TEAM_URL, json={**_TEAM_BODY, "is_own": True})
        self.assertIs(response.json()["team"]["is_own"], True)

    def test_list_includes_is_own(self) -> None:
        teams = _TeamsRepo()
        teams.list_by_owner = lambda *, owner_user_id: [  # type: ignore[method-assign]
            Team(
                id="t1",
                name="A",
                short_name="A",
                city="c",
                country="x",
                owner_user_id=owner_user_id,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                is_own=True,
            )
        ]
        response = _build_client(teams=teams).get("/teams")
        self.assertIs(response.json()["teams"][0]["is_own"], True)

    def test_delete_team_maps_match_conflict_to_409_envelope(self) -> None:
        client = _build_client(delete_conflict_code=TEAM_HAS_MATCHES)
        response = client.delete("/teams/00000000-0000-4000-8000-000000000001")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], TEAM_HAS_MATCHES)

    def test_delete_team_maps_generic_conflict_to_409_envelope(self) -> None:
        client = _build_client(delete_conflict_code=TEAM_DELETE_CONFLICT)
        response = client.delete("/teams/00000000-0000-4000-8000-000000000001")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], TEAM_DELETE_CONFLICT)

    def test_get_team_stats_returns_summary(self) -> None:
        client = _build_client()
        response = client.get("/teams/00000000-0000-4000-8000-000000000001/stats")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["team"]["wins"], 1)

    def test_get_team_stats_maps_missing_team(self) -> None:
        client = _build_client(missing_stats_team=True)
        response = client.get("/teams/00000000-0000-4000-8000-000000000001/stats")
        self.assertEqual(response.status_code, 404)
