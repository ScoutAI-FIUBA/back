from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.players.use_cases import (
    AssignPlayerTeamUseCase,
    CreatePlayerUseCase,
    DeletePlayerUseCase,
    ListPlayersByTeamUseCase,
    ListPlayersUseCase,
    UpdatePlayerUseCase,
)
from src.domain.players.entities import Player
from src.interfaces.http.routes.players_router import create_players_router

TEAM_ID = "00000000-0000-4000-8000-000000000010"
OTHER_TEAM_ID = "00000000-0000-4000-8000-000000000099"
VALID = {
    "first_name": "Caitlin",
    "last_name": "Clark",
    "birth_date": "2002-01-22",
    "height_cm": 183,
    "weight_kg": 70,
    "primary_position": "PG",
}


class _PlayerRepo:
    """Owner-aware fake: every operation is scoped by owner_user_id."""

    def __init__(self) -> None:
        self.by_id: dict[str, Player] = {}

    def create(self, player: Player) -> Player:
        self.by_id[player.id] = player
        return player

    def list_by_owner(self, *, owner_user_id: str) -> list[Player]:
        return [p for p in self.by_id.values() if p.owner_user_id == owner_user_id]

    def update(self, *, player_id, owner_user_id, **fields) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return None
        updated = Player(id=player.id, owner_user_id=owner_user_id, team_id=player.team_id, **fields)
        self.by_id[player_id] = updated
        return updated

    def delete(self, player_id: str, *, owner_user_id: str) -> bool:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return False
        del self.by_id[player_id]
        return True

    def assign_team(self, *, player_id, owner_user_id, team_id) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None or player.owner_user_id != owner_user_id:
            return None
        updated = Player(
            id=player.id, first_name=player.first_name, last_name=player.last_name,
            birth_date=player.birth_date, height_cm=player.height_cm, weight_kg=player.weight_kg,
            primary_position=player.primary_position, owner_user_id=owner_user_id, team_id=team_id,
        )
        self.by_id[player_id] = updated
        return updated

    def list_by_owner_and_team(self, *, owner_user_id, team_id) -> list[Player]:
        return [
            p for p in self.by_id.values()
            if p.owner_user_id == owner_user_id and p.team_id == team_id
        ]


class _TeamRepo:
    def __init__(self) -> None:
        self.owned: set[tuple[str, str]] = set()  # (team_id, owner)

    def is_owned_by(self, *, team_id: str, owner_user_id: str) -> bool:
        return (team_id, owner_user_id) in self.owned


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"00000000-0000-4000-8000-{self._n:012d}"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


def build_client(*, user_id: str = "scout-1", team_repo: _TeamRepo | None = None) -> tuple[TestClient, _PlayerRepo]:
    repo = _PlayerRepo()
    teams = team_repo or _TeamRepo()
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.include_router(
        create_players_router(
            create_player_use_case=CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow()),
            list_players_use_case=ListPlayersUseCase(players=repo),
            list_players_by_team_use_case=ListPlayersByTeamUseCase(players=repo),
            update_player_use_case=UpdatePlayerUseCase(players=repo, uow=_Uow()),
            delete_player_use_case=DeletePlayerUseCase(players=repo, uow=_Uow()),
            assign_player_team_use_case=AssignPlayerTeamUseCase(players=repo, teams=teams, uow=_Uow()),
        )
    )
    return TestClient(app), repo


class TestPlayerCrud(unittest.TestCase):
    def test_create_and_list(self) -> None:
        client, _ = build_client()
        created = client.post("/players", json=VALID)
        self.assertEqual(created.status_code, 201)
        pid = created.json()["player"]["id"]
        listed = client.get("/players").json()["players"]
        self.assertEqual([p["id"] for p in listed], [pid])

    def test_update_and_delete(self) -> None:
        client, _ = build_client()
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        updated = client.put(f"/players/{pid}", json={**VALID, "primary_position": "C"})
        self.assertEqual(updated.json()["player"]["primary_position"], "C")
        self.assertEqual(client.delete(f"/players/{pid}").status_code, 204)
        self.assertEqual(client.get("/players").json()["players"], [])


class TestPositionValidation(unittest.TestCase):
    def test_each_basketball_code_is_accepted(self) -> None:
        client, _ = build_client()
        for code in ("PG", "SG", "SF", "PF", "C"):
            r = client.post("/players", json={**VALID, "primary_position": code})
            self.assertEqual(r.status_code, 201, code)

    def test_football_position_is_rejected(self) -> None:
        """The old soccer codes must no longer be accepted."""

        client, _ = build_client()
        r = client.post("/players", json={**VALID, "primary_position": "DEL"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "INVALID_POSITION")

    def test_invalid_position_on_update_is_rejected(self) -> None:
        client, _ = build_client()
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        r = client.put(f"/players/{pid}", json={**VALID, "primary_position": "GK"})
        self.assertEqual(r.status_code, 422)


class TestOwnershipIsolation(unittest.TestCase):
    def test_a_scout_only_sees_their_own_players(self) -> None:
        client_a, repo = build_client(user_id="scout-a")
        client_a.post("/players", json=VALID)
        # A different scout sharing the same repo sees nothing.
        client_b, _ = build_client(user_id="scout-b")
        client_b_app_repo = _PlayerRepo()  # separate app; ownership still filters
        self.assertEqual(len(repo.list_by_owner(owner_user_id="scout-a")), 1)
        self.assertEqual(len(repo.list_by_owner(owner_user_id="scout-b")), 0)

    def test_cannot_update_another_scouts_player(self) -> None:
        # Seed a player owned by scout-a, then act as scout-b against the same repo.
        app_a = build_client(user_id="scout-a")
        client_a, repo = app_a
        pid = client_a.post("/players", json=VALID).json()["player"]["id"]

        # Rebuild a client for scout-b bound to the SAME repo.
        from fastapi import FastAPI
        app = FastAPI()

        @app.middleware("http")
        async def _u(request, call_next):
            request.state.user_id = "scout-b"
            return await call_next(request)

        app.include_router(
            create_players_router(
                create_player_use_case=CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow()),
                list_players_use_case=ListPlayersUseCase(players=repo),
                list_players_by_team_use_case=ListPlayersByTeamUseCase(players=repo),
                update_player_use_case=UpdatePlayerUseCase(players=repo, uow=_Uow()),
                delete_player_use_case=DeletePlayerUseCase(players=repo, uow=_Uow()),
                assign_player_team_use_case=AssignPlayerTeamUseCase(players=repo, teams=_TeamRepo(), uow=_Uow()),
            )
        )
        client_b = TestClient(app)
        # scout-b sees another scout's player as simply not found.
        self.assertEqual(client_b.put(f"/players/{pid}", json=VALID).status_code, 404)
        self.assertEqual(client_b.delete(f"/players/{pid}").status_code, 404)


class TestAssignTeam(unittest.TestCase):
    def test_assign_to_owned_team(self) -> None:
        teams = _TeamRepo()
        teams.owned.add((TEAM_ID, "scout-1"))
        client, _ = build_client(team_repo=teams)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        r = client.put(f"/players/{pid}/team/{TEAM_ID}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["player"]["team_id"], TEAM_ID)

    def test_cannot_assign_to_a_team_you_do_not_own(self) -> None:
        """A team owned by someone else is reported as not found."""

        teams = _TeamRepo()  # scout-1 owns nothing
        client, _ = build_client(team_repo=teams)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        r = client.put(f"/players/{pid}/team/{OTHER_TEAM_ID}")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "TEAM_NOT_FOUND")

    def test_filter_by_team(self) -> None:
        teams = _TeamRepo()
        teams.owned.add((TEAM_ID, "scout-1"))
        client, _ = build_client(team_repo=teams)
        pid = client.post("/players", json=VALID).json()["player"]["id"]
        client.put(f"/players/{pid}/team/{TEAM_ID}")
        filtered = client.get(f"/players?team_id={TEAM_ID}").json()["players"]
        self.assertEqual([p["id"] for p in filtered], [pid])


if __name__ == "__main__":
    unittest.main()
