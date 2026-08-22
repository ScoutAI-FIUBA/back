from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.matches.errors import INVALID_MATCH_TEAMS, PLAYER_NOT_FOUND
from src.application.matches.use_cases import (
    CreateMatchUseCase,
    GetMatchStatsUseCase,
    GetMatchUseCase,
    ListMatchesUseCase,
    ReplaceMatchStatsUseCase,
)
from src.domain.matches.entities import Match, MatchParticipant, MatchStatsView
from src.domain.players.entities import Player
from src.interfaces.http.routes.matches_router import create_matches_router


HOME_TEAM_ID = "00000000-0000-4000-8000-000000000010"
AWAY_TEAM_ID = "00000000-0000-4000-8000-000000000020"
MATCH_ID = "00000000-0000-4000-8000-000000000001"


def _match() -> Match:
    now = datetime.now(timezone.utc)
    return Match(
        id=MATCH_ID,
        owner_user_id="user-1",
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        match_date=date(2024, 1, 1),
        description="League night",
        created_at=now,
        updated_at=now,
    )


class _MatchRepo:
    def __init__(self) -> None:
        self.match = _match()
        self.replaced_view = MatchStatsView(match=self.match, participants=[])

    def create(self, match: Match) -> Match:
        self.match = match
        return match

    def list_by_owner(self, *, owner_user_id: str, team_id: str | None = None) -> list[Match]:
        del owner_user_id, team_id
        return [self.match]

    def get_by_id(self, *, match_id: str, owner_user_id: str) -> Match | None:
        if self.match.id != match_id or self.match.owner_user_id != owner_user_id:
            return None
        return self.match

    def replace_stats(self, *, match_id: str, owner_user_id: str, stats, winner_team_id, participants):
        found = self.get_by_id(match_id=match_id, owner_user_id=owner_user_id)
        if found is None:
            return None
        updated_match = Match(
            id=found.id,
            owner_user_id=found.owner_user_id,
            home_team_id=found.home_team_id,
            away_team_id=found.away_team_id,
            winner_team_id=winner_team_id,
            match_date=found.match_date,
            description=found.description,
            stats=stats,
            created_at=found.created_at,
            updated_at=found.updated_at,
        )
        self.match = updated_match
        self.replaced_view = MatchStatsView(match=updated_match, participants=participants)
        return self.replaced_view

    def get_stats(self, *, match_id: str, owner_user_id: str) -> MatchStatsView | None:
        found = self.get_by_id(match_id=match_id, owner_user_id=owner_user_id)
        if found is None:
            return None
        return self.replaced_view


class _TeamRepo:
    def __init__(self) -> None:
        self.owned = {(HOME_TEAM_ID, "user-1"), (AWAY_TEAM_ID, "user-1")}

    def is_owned_by(self, *, team_id: str, owner_user_id: str) -> bool:
        return (team_id, owner_user_id) in self.owned


class _PlayerRepo:
    def __init__(self) -> None:
        self.players: dict[tuple[str, str], Player] = {}

    def get_by_id(self, *, player_id: str, owner_user_id: str) -> Player | None:
        return self.players.get((player_id, owner_user_id))


class _Ids:
    def __init__(self) -> None:
        self.count = 1

    def new_id(self) -> str:
        value = f"generated-{self.count}"
        self.count += 1
        return value


class _Uow:
    @contextmanager
    def transaction(self):
        yield


def _build_client(*, players: _PlayerRepo | None = None) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    match_repo = _MatchRepo()
    team_repo = _TeamRepo()
    player_repo = players or _PlayerRepo()
    ids = _Ids()
    uow = _Uow()

    app.include_router(
        create_matches_router(
            create_match_use_case=CreateMatchUseCase(matches=match_repo, teams=team_repo, ids=ids, uow=uow),
            list_matches_use_case=ListMatchesUseCase(matches=match_repo, teams=team_repo),
            get_match_use_case=GetMatchUseCase(matches=match_repo),
            replace_match_stats_use_case=ReplaceMatchStatsUseCase(matches=match_repo, players=player_repo, ids=ids, uow=uow),
            get_match_stats_use_case=GetMatchStatsUseCase(matches=match_repo),
        )
    )
    return TestClient(app)


class TestMatchesRouter(unittest.TestCase):
    def test_create_match_rejects_same_home_and_away_team(self) -> None:
        client = _build_client()

        response = client.post(
            "/matches",
            json={
                "home_team_id": "00000000-0000-4000-8000-000000000001",
                "away_team_id": "00000000-0000-4000-8000-000000000001",
                "match_date": "2024-01-01",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], INVALID_MATCH_TEAMS)

    def test_replace_match_stats_rejects_missing_participant_player(self) -> None:
        client = _build_client()

        response = client.put(
            "/matches/00000000-0000-4000-8000-000000000001/stats",
            json={
                "stats": {"opaque": True},
                "winner_team_id": HOME_TEAM_ID,
                "participants": [
                    {
                        "team_side": "HOME",
                        "display_name": "Ghost",
                        "player_id": "00000000-0000-4000-8000-000000000099",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], PLAYER_NOT_FOUND)

    def test_replace_match_stats_rejects_cross_owner_participant_player(self) -> None:
        players = _PlayerRepo()
        players.players[("00000000-0000-4000-8000-000000000099", "user-2")] = Player(
            id="00000000-0000-4000-8000-000000000099",
            first_name="Other",
            last_name="Owner",
            birth_date=date(2000, 1, 1),
            height_cm=180,
            weight_kg=75,
            primary_position="PG",
            owner_user_id="user-2",
        )
        client = _build_client(players=players)

        response = client.put(
            "/matches/00000000-0000-4000-8000-000000000001/stats",
            json={
                "stats": {"opaque": True},
                "winner_team_id": HOME_TEAM_ID,
                "participants": [
                    {
                        "team_side": "HOME",
                        "display_name": "Other Owner",
                        "player_id": "00000000-0000-4000-8000-000000000099",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], PLAYER_NOT_FOUND)
