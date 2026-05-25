from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import unittest

from src.application.players.use_cases import (
    AssignPlayerTeamUseCase,
    CreatePlayerUseCase,
    DeletePlayerUseCase,
    ListPlayersByTeamUseCase,
    ListPlayersUseCase,
    UpdatePlayerUseCase,
)
from src.domain.players.entities import Player
from src.interfaces.http.players_router import create_players_router


class _PlayerRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, Player] = {}

    def create(self, player: Player) -> Player:
        self.by_id[player.id] = player
        return player

    def list_all(self) -> list[Player]:
        return list(self.by_id.values())

    def update(self, player: Player) -> Player | None:
        if player.id not in self.by_id:
            return None
        self.by_id[player.id] = player
        return player

    def delete(self, player_id: str) -> bool:
        return self.by_id.pop(player_id, None) is not None

    def assign_team(self, *, player_id: str, team_id: str) -> Player | None:
        player = self.by_id.get(player_id)
        if player is None:
            return None
        updated = Player(
            id=player.id,
            first_name=player.first_name,
            last_name=player.last_name,
            birth_date=player.birth_date,
            height_cm=player.height_cm,
            weight_kg=player.weight_kg,
            primary_position=player.primary_position,
            team_id=team_id,
        )
        self.by_id[player_id] = updated
        return updated

    def list_by_team(self, team_id: str) -> list[Player]:
        return [player for player in self.by_id.values() if player.team_id == team_id]


class _TeamRepo:
    def __init__(self) -> None:
        self.existing_ids: set[str] = set()

    def exists(self, team_id: str) -> bool:
        return team_id in self.existing_ids


class _Ids:
    def __init__(self) -> None:
        self._value = 0

    def new_id(self) -> str:
        self._value += 1
        return f"00000000-0000-4000-8000-{self._value:012d}"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestPlayersRouter(unittest.TestCase):
    def _endpoints(self):
        repo = _PlayerRepo()
        team_repo = _TeamRepo()
        team_repo.existing_ids.add("00000000-0000-4000-8000-000000000010")
        router = create_players_router(
            create_player_use_case=CreatePlayerUseCase(players=repo, ids=_Ids(), uow=_Uow()),
            list_players_use_case=ListPlayersUseCase(players=repo),
            list_players_by_team_use_case=ListPlayersByTeamUseCase(players=repo),
            update_player_use_case=UpdatePlayerUseCase(players=repo, uow=_Uow()),
            delete_player_use_case=DeletePlayerUseCase(players=repo, uow=_Uow()),
            assign_player_team_use_case=AssignPlayerTeamUseCase(players=repo, teams=team_repo, uow=_Uow()),
        )
        create_endpoint = next(
            route.endpoint for route in router.routes if route.path == "/players" and "POST" in route.methods
        )
        list_endpoint = next(
            route.endpoint for route in router.routes if route.path == "/players" and "GET" in route.methods
        )
        update_endpoint = next(
            route.endpoint
            for route in router.routes
            if route.path == "/players/{player_id}" and "PUT" in route.methods
        )
        delete_endpoint = next(
            route.endpoint
            for route in router.routes
            if route.path == "/players/{player_id}" and "DELETE" in route.methods
        )
        assign_team_endpoint = next(
            route.endpoint
            for route in router.routes
            if route.path == "/players/{player_id}/team/{team_id}" and "PUT" in route.methods
        )
        return create_endpoint, list_endpoint, update_endpoint, delete_endpoint, assign_team_endpoint

    def test_players_crud_contract(self) -> None:
        create_endpoint, list_endpoint, update_endpoint, delete_endpoint, assign_team_endpoint = self._endpoints()
        payload = type(
            "PlayerPayload",
            (),
            {
                "first_name": "Lio",
                "last_name": "Messi",
                "birth_date": date(1987, 6, 24),
                "height_cm": 170,
                "weight_kg": 72,
                "primary_position": "RW",
            },
        )()
        created = create_endpoint(payload)
        player_id = created["player"]["id"]

        listed = list_endpoint()
        self.assertEqual(len(listed["players"]), 1)
        self.assertEqual(listed["players"][0]["id"], player_id)

        updated = update_endpoint(
            player_id,
            type(
                "PlayerPayload",
                (),
                {
                    "first_name": "Leo",
                    "last_name": "Messi",
                    "birth_date": date(1987, 6, 24),
                    "height_cm": 171,
                    "weight_kg": 73,
                    "primary_position": "AM",
                },
            )(),
        )
        self.assertEqual(updated["player"]["first_name"], "Leo")

        deleted = delete_endpoint(player_id)
        self.assertEqual(deleted.status_code, 204)

        team_id = "00000000-0000-4000-8000-000000000010"
        assigned = assign_team_endpoint(player_id, team_id)
        self.assertEqual(assigned.status_code, 404)

    def test_update_and_delete_missing_player(self) -> None:
        _, _, update_endpoint, delete_endpoint, assign_team_endpoint = self._endpoints()
        payload = type(
            "PlayerPayload",
            (),
            {
                "first_name": "Leo",
                "last_name": "Messi",
                "birth_date": date(1987, 6, 24),
                "height_cm": 171,
                "weight_kg": 73,
                "primary_position": "AM",
            },
        )()
        missing_id = "00000000-0000-4000-8000-000000000999"
        updated = update_endpoint(missing_id, payload)
        self.assertEqual(updated.status_code, 404)

        deleted = delete_endpoint(missing_id)
        self.assertEqual(deleted.status_code, 404)

        assign_missing_player = assign_team_endpoint(missing_id, "00000000-0000-4000-8000-000000000010")
        self.assertEqual(assign_missing_player.status_code, 404)

    def test_assign_team_and_filter_by_team(self) -> None:
        create_endpoint, list_endpoint, _, _, assign_team_endpoint = self._endpoints()
        payload = type(
            "PlayerPayload",
            (),
            {
                "first_name": "Lio",
                "last_name": "Messi",
                "birth_date": date(1987, 6, 24),
                "height_cm": 170,
                "weight_kg": 72,
                "primary_position": "RW",
            },
        )()
        created = create_endpoint(payload)
        player_id = created["player"]["id"]

        team_id = "00000000-0000-4000-8000-000000000010"
        assigned = assign_team_endpoint(player_id, team_id)
        self.assertEqual(assigned["player"]["team_id"], team_id)

        listed = list_endpoint(team_id)
        self.assertEqual(len(listed["players"]), 1)
        self.assertEqual(listed["players"][0]["id"], player_id)


if __name__ == "__main__":
    unittest.main()
